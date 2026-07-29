"""Supported construction surface for the official-SDK-v2 DAGR binding.

Wires an :class:`dagr_mcp_sdk_v2.adapter.SdkV2LifecycleAdapter` onto an
``mcp.server.lowlevel.Server`` using the SDK's public, documented low-level
handler-composition surface -- constructor-kwarg registration
(``Server(..., on_call_tool=..., on_list_tools=...)``), never the private
``mcp.server._streamable_http_modern`` module and never
``handle_modern_request``. The governed ASGI app is built with the public
``Server.streamable_http_app(stateless_http=True)`` (see
``examples/http_proof_v2``), which serves protocol ``2026-07-28`` traffic on
the SDK's own modern, no-handshake, no-``Mcp-Session-Id`` path regardless of
the ``stateless_http`` flag (that flag only affects legacy-protocol routing).

Scope: ``tools/call`` with ``resultType: complete`` only. This module does not
advertise or support MRTR (``input_required``); see
:class:`dagr_mcp_sdk_v2.adapter.InputRequiredUnsupported`.

Importing this module imports the official SDK (``mcp``) but never ``fastmcp``
and starts no transport.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Callable

from mcp import types as mcp_types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server

from dagr_mcp_sdk_v2.adapter import SdkV2LifecycleAdapter, ToolHandler

# A delegated call handler dispatches an admitted call for tools not in the
# explicit registry: ``async def handler(name, arguments) -> result``.
DelegatedCallHandler = Callable[[str, Mapping[str, Any]], Any]


@dataclass(frozen=True, slots=True)
class GovernedTool:
    """A fixture tool: its v2 SDK definition and its dispatch handler."""

    definition: mcp_types.Tool
    handler: ToolHandler


def _registry(tools: Sequence[GovernedTool]) -> dict[str, GovernedTool]:
    registry: dict[str, GovernedTool] = {}
    for tool in tools:
        registry[tool.definition.name] = tool
    return registry


def _make_delegate(
    name: str,
    registry: Mapping[str, GovernedTool],
    delegated_call_handler: DelegatedCallHandler | None,
) -> ToolHandler:
    """Return the dispatch delegate for *name* (registry, else delegated handler).

    The delegate is invoked by the adapter ONLY when admission proceeds, so an
    unknown/refused tool never reaches a missing handler in ordinary operation;
    the ``_missing`` fallback below only fires on a genuine registry/policy
    misconfiguration (a tool_class configured admitted with no matching handler).
    """

    tool = registry.get(name)
    if tool is not None:
        return tool.handler
    if delegated_call_handler is not None:
        async def _delegate(arguments: Mapping[str, Any]) -> Any:
            return await _maybe_await(delegated_call_handler(name, arguments))

        return _delegate

    def _missing(_arguments: Mapping[str, Any]) -> Any:
        raise LookupError(f"no delegated handler for admitted tool {name!r}")

    return _missing


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def build_governed_server(
    name: str,
    *,
    adapter: SdkV2LifecycleAdapter,
    tools: Sequence[GovernedTool] = (),
    delegated_call_handler: DelegatedCallHandler | None = None,
    version: str | None = None,
) -> Server:
    """Create a fresh lowlevel ``Server`` with DAGR-governed ``tools/call``.

    ``tools`` are the fixture tools exposed by ``tools/list`` and dispatched by
    ``tools/call``. ``delegated_call_handler`` dispatches admitted calls for
    names not in ``tools``. The governed handler runs the neutral lifecycle
    around each dispatch and emits signed receipts; admission is decided (and
    the admission receipt durably emitted) strictly before the delegate is
    invoked.
    """

    registry = _registry(tools)
    definitions = [tool.definition for tool in tools]

    async def on_list_tools(
        _ctx: ServerRequestContext[Any, Any], _params: mcp_types.PaginatedRequestParams | None
    ) -> mcp_types.ListToolsResult:
        return mcp_types.ListToolsResult(tools=list(definitions))

    async def on_call_tool(
        ctx: ServerRequestContext[Any, Any], params: mcp_types.CallToolRequestParams
    ) -> mcp_types.CallToolResult:
        delegate = _make_delegate(params.name, registry, delegated_call_handler)
        return await adapter.governed_call_tool(ctx, params, delegate)

    return Server(
        name,
        version=version or "",
        on_call_tool=on_call_tool,
        on_list_tools=on_list_tools,
    )


__all__ = ["GovernedTool", "DelegatedCallHandler", "build_governed_server"]
