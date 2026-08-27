"""SAM-native MCP connector — DRAFT, offline-only (SAM-NATIVE-MCP-BIND0).

Scope: program ``SAM-SUBSTRATE-BUILD0``, lane ``SAM-NATIVE-MCP-BIND0``. This
module is an **adapter to google/sam v0.1.0-alpha.7's native MCP surface**,
not a second generic MCP-over-HTTP transport. It composes underneath
:class:`dagr_mcp_service.connectors.remote.RemoteToolConnector`: the local
``sam-node run`` process's Streamable-HTTP ``/mcp`` endpoint is, at the wire
level, exactly the kind of remote target :mod:`dagr_mcp_service.connectors.
remote` already governs (endpoint validation, credential lifecycle, redirect
policy, timeout/connection-failure translation, import discipline). This
module owns only what is SAM-specific and not already owned there:
Counterpedia ``target_server_ref.handle`` -> SAM ``peer_id``/namespaced
remote-tool-name translation, SAM native call-argument shape
(``call_remote_tool{peer_id, tool_name, arguments, required_labels?}``), and
SAM-specific structural result validation. It does not reimplement HTTP
transport, endpoint validation, or credential handling — those stay owned by
:class:`~dagr_mcp_service.connectors.remote.RemoteToolConnector`.

**No caller-supplied sam-node URL, peer_id, service routing override, auth
token/header, transport, socket, SAM release/commit, or required_labels
policy.** :class:`SamRouteConfig` is closed, immutable, operator-authored
configuration keyed by ``(target_server_ref.handle, tool_name)`` — mirroring
:mod:`dagr_mcp_service.connectors.memory`'s and
:mod:`dagr_mcp_service.connectors.stdio`'s two-level allowlist model. A
caller's ``GovernedCallRequest`` supplies only the target handle, the tool
name, and ordinary governed tool arguments; every SAM routing fact (which
peer, which namespaced remote tool, which label policy, which local
sam-node endpoint) is looked up from that pair against
:class:`SamNativeConnector`'s operator-provided registry, never read from a
tool argument or the request itself. An unknown handle, an unknown tool
name, or a handle whose configured local sam-node endpoint is itself
unregistered on the underlying :class:`RemoteToolConnector` all resolve to
:class:`SamTargetResolutionRefused` — never a nearest-peer or default-routing
substitution.

**Discovery is explicit, operator-invoked, and off the hot call path** —
mirroring :mod:`dagr_mcp_service.connectors.stdio`'s ``discover_tools``
discipline. :func:`discover_sam_peers`, :func:`find_sam_remote_tools`, and
:func:`describe_sam_remote_tool` exist so an operator can populate a
:class:`SamRouteConfig` registry ahead of time by asking the real local
sam-node process what it currently sees. None of the three is ever called by
:meth:`SamNativeConnector.resolve` or by the handler it returns, and none of
their results is ever written back into a connector's routing table by this
module. **This is the module's concrete answer to "SAM discovery ≠
eligibility": a peer or tool appearing in a discovery response never, by
itself, becomes reachable through this connector.** Only an operator's own,
separately-authored :class:`SamRouteConfig` entry does that. alpha.7 rejects
``type="a2a"`` in ``discover_remote_services`` (only ``"mcp"``/``"inference"``
are real service types at this pin) — :func:`discover_sam_peers` rejects it
too, before ever calling the local endpoint, rather than forwarding it and
letting the remote reject it.

**SAM-specific result validation is structural only, never semantic.**
:func:`_validate_call_remote_tool_result` checks that the local sam-node
``call_remote_tool`` response has the shape a ``mcp.types.CallToolResult``
must have (a ``content`` sequence and an ``isError``/``is_error`` boolean,
with non-empty ``content`` on a non-error result) and raises
:class:`RuntimeError` — the same generic, closed-vocabulary
``remote_exception`` bucket :mod:`dagr_mcp_service.connectors.remote` and
:mod:`dagr_mcp_service.connectors.stdio` both already use for "the transport
or tool result was not successfully observed" — when it does not. It never
inspects, interprets, or asserts anything about the *content* of a
well-formed result: **a SAM route reaching a peer and getting back a
well-formed, ``isError=False`` result is a transport-and-routing fact, not an
execution-authorization fact, and not a claim about the semantic truth of
whatever the remote tool reported.** Nothing in this module sets, reads, or
implies a DAGR admission disposition or a Countervail authorization outcome
— those remain entirely owned by :func:`dagr_mcp_service.adapter.
execute_governed_call` and the neutral lifecycle core it drives, which this
module's returned handler is only ever a leaf callable underneath.

**Argument integrity.** The ``arguments`` sub-object this module places
inside its ``call_remote_tool`` payload is built as ``dict(call_arguments)``
from the caller's already-digest-verified snapshot (see
:mod:`dagr_mcp_service.connectors.remote`'s identical note on why this copy
is a serialization-boundary convenience, not what makes the value
trustworthy) — nothing from :class:`SamRouteConfig` (``peer_id``,
``remote_tool_name``, ``required_labels``, ``sam_endpoint_handle``) is ever
merged into it, and nothing from the caller's arguments is ever allowed to
override ``peer_id``/``tool_name``/``required_labels`` in the outer payload:
those three keys are always set, last, from the operator-authored
:class:`SamRouteConfig`, never from anything the caller supplied. A caller
that includes keys named ``peer_id``, ``tool_name``, ``url``, or similar
inside its own tool arguments only ever reaches the remote as inert data
nested under ``arguments`` — never as SAM routing metadata, and never
folded into any artifact identity this module returns.

**Peer identity at alpha.7.** There is no ``AuthFrame.agent`` at this pin,
and this module operates entirely at the local client ``/mcp`` layer — mesh
membership, biscuit verification, and per-peer authorization are sam-node's
own server-side concern, never re-derived, re-checked, or asserted by this
module. A well-formed, ``isError=False`` ``call_remote_tool`` result proves
only that the local sam-node process accepted and relayed the call; this
module makes no independent claim about the mesh-level identity or
trustworthiness of the peer that answered.

**Import discipline.** Importing this module never imports ``httpx``,
``mcp.client.*``, or any HTTP/network library — it holds no transport of its
own; the only import boundary it owns is a plain ``re`` module-scope import
for namespaced-tool-name validation.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias

from dagr_mcp_service.connectors.remote import (
    RemoteTargetResolutionRefused,
    RemoteToolConnector,
)

# A resolved SAM-routed target handler: given the (already argument-digest-
# verified) call arguments, returns the double-hop-verbatim remote result or
# raises. Structurally identical to the sibling connectors' handler aliases
# (all four connectors are driven through the same A8
# ``connector.resolve(...)`` seam), redefined here rather than imported so
# this module stays independently importable without pulling in any sibling
# connector besides ``remote`` (whose transport it composes underneath).
SamToolHandler: TypeAlias = Callable[[Mapping[str, Any]], "Awaitable[Any] | Any"]

SamTargetResolutionFailureReason = Literal["remote_unavailable", "unknown_tool_fail_closed"]

# The one local sam-node native MCP tool this connector's hot call path ever
# invokes. ``discover_remote_services``/``find_remote_tools``/
# ``describe_remote_tool`` are reachable only through the separate,
# operator-invoked helper functions below — never from here.
_CALL_REMOTE_TOOL_NAME = "call_remote_tool"
_DISCOVER_REMOTE_SERVICES_TOOL_NAME = "discover_remote_services"
_FIND_REMOTE_TOOLS_TOOL_NAME = "find_remote_tools"
_DESCRIBE_REMOTE_TOOL_TOOL_NAME = "describe_remote_tool"

# alpha.7's own real service-type vocabulary for ``discover_remote_services``
# (see the module docstring's "Discovery is explicit" section) -- ``"a2a"``
# is rejected by alpha.7 itself; this module refuses it before ever placing
# it on the wire, rather than forwarding it and letting the remote reject it.
SamDiscoveryServiceType = Literal["mcp", "inference"]
_SAM_DISCOVERY_SERVICE_TYPES: frozenset[str] = frozenset({"mcp", "inference"})

# A SAM namespaced remote tool name: ``scheme://service/tool`` (at least one
# ``/`` after the authority, requiring a non-empty tool segment). Deliberately
# stricter than a bare URL parse so a config value that merely *looks* like a
# tool reference (e.g. a bare tool name someone forgot to namespace) fails at
# construction time rather than being forwarded to the local sam-node
# endpoint and diagnosed only there.
_NAMESPACED_TOOL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://[^/]+/.+$")


@dataclass(frozen=True, slots=True, kw_only=True)
class SamRouteConfig:
    """Closed, immutable, operator-authored SAM route for one ``(target_handle,
    tool_name)`` pair.

    Every SAM routing fact a call needs lives here, fixed by the operator at
    configuration time: which local sam-node endpoint to reach (a lookup key
    into the underlying :class:`RemoteToolConnector`'s own registry, never a
    URL this module holds directly), which mesh peer, which namespaced
    remote tool, and which label policy. A caller's ``GovernedCallRequest``
    never supplies any of these.
    """

    sam_endpoint_handle: str
    peer_id: str
    remote_tool_name: str
    required_labels: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.sam_endpoint_handle, str) or not self.sam_endpoint_handle.strip():
            raise ValueError("SamRouteConfig.sam_endpoint_handle must be a non-empty string")
        if not isinstance(self.peer_id, str) or not self.peer_id.strip():
            raise ValueError("SamRouteConfig.peer_id must be a non-empty string")
        if not isinstance(self.remote_tool_name, str) or not _NAMESPACED_TOOL_RE.match(
            self.remote_tool_name
        ):
            raise ValueError(
                "SamRouteConfig.remote_tool_name must be an explicit "
                "'scheme://service/tool' namespaced SAM tool reference; got "
                f"{self.remote_tool_name!r}"
            )
        if not isinstance(self.required_labels, tuple):
            raise TypeError(
                "SamRouteConfig.required_labels must be a tuple of strings, "
                f"got {type(self.required_labels).__name__}"
            )
        for label in self.required_labels:
            if not isinstance(label, str) or not label:
                raise ValueError(
                    f"SamRouteConfig.required_labels entries must be non-empty strings, got {label!r}"
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class SamTargetResolutionRefused:
    """A fail-closed SAM-target resolution outcome.

    ``reason`` reuses the same two stable diagnostics
    :mod:`dagr_mcp_service.connectors.memory` and
    :mod:`dagr_mcp_service.connectors.stdio` already use rather than
    inventing a new taxonomy: an unregistered ``target_server_ref.handle``,
    or a handle whose configured local sam-node endpoint is itself
    unregistered on the underlying :class:`RemoteToolConnector`, both read as
    ``remote_unavailable``; an unregistered ``tool_name`` under a known
    handle reads as ``unknown_tool_fail_closed``. There is no third variant
    that substitutes another peer or another tool -- every non-success path
    is one of these two refusals, returned before any call is attempted.
    """

    target_handle: str
    tool_name: str
    reason: SamTargetResolutionFailureReason


def _validate_call_remote_tool_result(
    raw: Any, *, target_handle: str, tool_name: str
) -> Any:
    """Structural-only validation of a ``call_remote_tool`` response.

    Confirms the double-hop-verbatim result the local sam-node endpoint
    returned has the shape a ``mcp.types.CallToolResult`` must have -- a
    ``content`` sequence and an ``isError``/``is_error`` boolean, non-empty
    ``content`` when ``isError`` is falsy -- and raises :class:`RuntimeError`
    (the same generic ``remote_exception`` bucket the sibling connectors use)
    when it does not. See the module docstring's "SAM-specific result
    validation is structural only, never semantic" section: this function
    never reads, interprets, or asserts anything about *what* a well-formed
    result's content says.
    """

    del target_handle, tool_name  # identifying context only, not consulted here.

    content = getattr(raw, "content", None)
    if content is None and isinstance(raw, Mapping):
        content = raw.get("content")
    is_error = getattr(raw, "isError", None)
    if is_error is None:
        is_error = getattr(raw, "is_error", None)
    if is_error is None and isinstance(raw, Mapping):
        is_error = raw.get("isError", raw.get("is_error"))

    if content is None or is_error is None:
        raise RuntimeError(
            "malformed SAM call_remote_tool result: missing content or isError"
        )
    if not isinstance(content, Sequence) or isinstance(content, str | bytes):
        raise RuntimeError("malformed SAM call_remote_tool result: content is not a sequence")
    if not isinstance(is_error, bool):
        raise RuntimeError("malformed SAM call_remote_tool result: isError is not a boolean")
    if not is_error and len(content) == 0:
        raise RuntimeError(
            "malformed SAM call_remote_tool result: empty content on a non-error result"
        )
    return raw


class SamNativeConnector:
    """Resolves ``(target_handle, tool_name)`` to a SAM-``call_remote_tool``-
    calling closure, composed on top of :class:`RemoteToolConnector`.

    ``targets`` is operator/deployment configuration -- never a model tool
    argument and never a caller-selected peer or remote tool -- mapping an
    allowlisted DAGR/Counterpedia target handle to its exposed
    tool-name -> :class:`SamRouteConfig` registry (mirroring
    :class:`~dagr_mcp_service.connectors.memory.InMemoryToolConnector`'s and
    :class:`~dagr_mcp_service.connectors.stdio.StdioToolConnector`'s
    two-level allowlist shape). ``remote_connector`` is the already-configured
    :class:`RemoteToolConnector` whose registry contains the local sam-node
    ``/mcp`` endpoint(s) a route's ``sam_endpoint_handle`` names -- this
    class never constructs a :class:`~dagr_mcp_service.connectors.remote.
    RemoteTargetConfig` itself and never holds a URL, credential provider,
    or transport setting of its own.
    """

    def __init__(
        self,
        *,
        remote_connector: RemoteToolConnector,
        targets: Mapping[str, Mapping[str, SamRouteConfig]],
    ) -> None:
        if not isinstance(remote_connector, RemoteToolConnector):
            raise TypeError(
                "SamNativeConnector.remote_connector must be a RemoteToolConnector, "
                f"got {type(remote_connector).__name__}"
            )
        normalized: dict[str, dict[str, SamRouteConfig]] = {}
        for handle, tools in targets.items():
            tool_map: dict[str, SamRouteConfig] = {}
            for tool_name, route in tools.items():
                if not isinstance(route, SamRouteConfig):
                    raise TypeError(
                        "SamNativeConnector targets values must be SamRouteConfig, "
                        f"got {type(route).__name__}"
                    )
                tool_map[str(tool_name)] = route
            normalized[str(handle)] = tool_map
        self._targets: dict[str, dict[str, SamRouteConfig]] = normalized
        self._remote_connector = remote_connector

    def resolve(
        self, target_handle: str, tool_name: str
    ) -> SamToolHandler | SamTargetResolutionRefused:
        """Look up ``target_handle``/``tool_name`` only -- no network I/O.

        Matches the frozen A8 connector seam
        :func:`dagr_mcp_service.adapter.execute_governed_call` calls
        unconditionally, and the exact ``(self, target_handle, tool_name)``
        shape every sibling connector's ``resolve`` already uses.
        """

        tools = self._targets.get(target_handle)
        if tools is None:
            return SamTargetResolutionRefused(
                target_handle=target_handle, tool_name=tool_name, reason="remote_unavailable"
            )
        route = tools.get(tool_name)
        if route is None:
            return SamTargetResolutionRefused(
                target_handle=target_handle,
                tool_name=tool_name,
                reason="unknown_tool_fail_closed",
            )

        inner = self._remote_connector.resolve(route.sam_endpoint_handle, _CALL_REMOTE_TOOL_NAME)
        if isinstance(inner, RemoteTargetResolutionRefused):
            # The route names a local sam-node endpoint the underlying
            # RemoteToolConnector does not have configured -- an operator
            # configuration gap, not a caller-reachable ambiguity. Fails
            # closed the same way an unknown target_handle does, never by
            # falling back to a default endpoint.
            return SamTargetResolutionRefused(
                target_handle=target_handle, tool_name=tool_name, reason="remote_unavailable"
            )

        async def _handler(call_arguments: Mapping[str, Any]) -> Any:
            payload: dict[str, Any] = {
                "peer_id": route.peer_id,
                "tool_name": route.remote_tool_name,
                "arguments": dict(call_arguments),
            }
            if route.required_labels:
                payload["required_labels"] = list(route.required_labels)
            raw = await inner(payload)
            return _validate_call_remote_tool_result(
                raw, target_handle=target_handle, tool_name=tool_name
            )

        return _handler


async def discover_sam_peers(
    remote_connector: RemoteToolConnector,
    *,
    sam_endpoint_handle: str,
    service_type: SamDiscoveryServiceType = "mcp",
    name: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> Any:
    """Operator-invoked discovery helper -- never called by :meth:`SamNativeConnector.resolve`.

    Calls the local sam-node endpoint's own ``discover_remote_services``
    native tool and returns its raw result unchanged, for an operator to
    inspect *ahead of time* while building a :class:`SamRouteConfig`
    registry. See the module docstring: this function's result is never
    written back into any connector's routing table by this module --
    discovery listing a peer never, by itself, makes that peer reachable
    through :class:`SamNativeConnector`.
    """

    if service_type not in _SAM_DISCOVERY_SERVICE_TYPES:
        raise ValueError(
            "discover_sam_peers: alpha.7's discover_remote_services only "
            f"supports type in {sorted(_SAM_DISCOVERY_SERVICE_TYPES)!r}; got "
            f"{service_type!r} (type='a2a' is rejected by alpha.7 itself)"
        )
    handler = remote_connector.resolve(sam_endpoint_handle, _DISCOVER_REMOTE_SERVICES_TOOL_NAME)
    if isinstance(handler, RemoteTargetResolutionRefused):
        raise LookupError(
            f"discover_sam_peers: sam_endpoint_handle {sam_endpoint_handle!r} is not "
            "configured on the underlying RemoteToolConnector"
        )
    args: dict[str, Any] = {"type": service_type}
    if name is not None:
        args["name"] = name
    if limit is not None:
        args["limit"] = limit
    if offset is not None:
        args["offset"] = offset
    return await handler(args)


async def find_sam_remote_tools(
    remote_connector: RemoteToolConnector,
    *,
    sam_endpoint_handle: str,
    intent: str | None = None,
    peer_id: str | None = None,
    service_name: str | None = None,
    tool_name: str | None = None,
) -> Any:
    """Operator-invoked discovery helper for ``find_remote_tools``.

    Same discipline as :func:`discover_sam_peers`: never called from the hot
    call path, result never written back into a connector's routing table.
    """

    handler = remote_connector.resolve(sam_endpoint_handle, _FIND_REMOTE_TOOLS_TOOL_NAME)
    if isinstance(handler, RemoteTargetResolutionRefused):
        raise LookupError(
            f"find_sam_remote_tools: sam_endpoint_handle {sam_endpoint_handle!r} is not "
            "configured on the underlying RemoteToolConnector"
        )
    args: dict[str, Any] = {}
    if intent is not None:
        args["intent"] = intent
    if peer_id is not None:
        args["peer_id"] = peer_id
    if service_name is not None:
        args["service_name"] = service_name
    if tool_name is not None:
        args["tool_name"] = tool_name
    return await handler(args)


async def describe_sam_remote_tool(
    remote_connector: RemoteToolConnector,
    *,
    sam_endpoint_handle: str,
    peer_id: str,
    tool_name: str,
) -> Any:
    """Operator-invoked discovery helper for ``describe_remote_tool``.

    Same discipline as :func:`discover_sam_peers`: never called from the hot
    call path. A schema mismatch between what this returns and what an
    operator expected is surfaced to the operator as this function's raw
    return value -- it is never silently accepted, resolved, or reconciled
    by this module, and it is never used to admit or authorize a call.
    """

    handler = remote_connector.resolve(sam_endpoint_handle, _DESCRIBE_REMOTE_TOOL_TOOL_NAME)
    if isinstance(handler, RemoteTargetResolutionRefused):
        raise LookupError(
            f"describe_sam_remote_tool: sam_endpoint_handle {sam_endpoint_handle!r} is not "
            "configured on the underlying RemoteToolConnector"
        )
    return await handler({"peer_id": peer_id, "tool_name": tool_name})


__all__ = [
    "SamToolHandler",
    "SamTargetResolutionFailureReason",
    "SamTargetResolutionRefused",
    "SamRouteConfig",
    "SamNativeConnector",
    "SamDiscoveryServiceType",
    "discover_sam_peers",
    "find_sam_remote_tools",
    "describe_sam_remote_tool",
]
