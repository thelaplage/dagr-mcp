"""Pinned registration of the EXTERNAL acquisition MCP surface (ACQ-MCP0).

Scope: DAGR-MCP-SOURCE0 — govern calls to the external, independently-authored
counterpedia-acquisition MCP tool surface through this repository's *existing*
stdio service connector and the *existing* lifecycle bindings, without importing
that surface's implementation and without inventing any new authority here.

What this module is
-------------------
A single, narrow registration helper that pins the external acquisition surface
as a :class:`dagr_mcp_service.connectors.stdio.StdioTargetConfig` /
:class:`~dagr_mcp_service.connectors.stdio.StdioToolConnector` target. It adds
**no** tool logic, **no** transport of its own, and **no** decision authority: it
only encodes, as reproduced constants and one config factory, the protocol/commit
facts an operator needs to point the *existing* governed stdio connector at the
*existing* external acquisition MCP server.

Governing an EXTERNAL boundary — pinned by protocol/commit, never imported
-------------------------------------------------------------------------
The acquisition surface lives in a *different* repository
(``counterpedia-acquisition``). Per DAGR-MCP-SOURCE0 the whole point is to govern
it as an EXTERNAL MCP tool boundary, so this module deliberately does **not**
import ``counterpedia_acquisition`` (or any of its modules). It pins the surface
the same way :mod:`dagr_mcp_service.resolution` pins the FastMCP binding version —
by reproducing the load-bearing literals with a recorded provenance comment,
cross-checkable against the real source but never coupling this repository's
import graph to it:

* ``ACQUISITION_SURFACE_REPO`` / ``ACQUISITION_SURFACE_COMMIT`` — the exact
  upstream repository and merged commit that froze this tool surface
  (``counterpedia-acquisition`` main ``2398f17``,
  "feat(mcp): proposal-only acquisition tool surface v0.1").
* ``ACQUISITION_SURFACE_SCHEMA`` — the surface's own frozen schema tag,
  reproduced from ``acquisition.mcp_surface.MCP_SURFACE_SCHEMA``.
* :data:`ACQUISITION_TOOL_NAMES` — the four dotted, acquisition-scoped tool
  names the surface exposes, reproduced from
  ``acquisition.mcp_surface.TOOL_NAMES``.
* ``ACQUISITION_SDK_PIN`` — the surface serves those tools over the official MCP
  Python SDK, the ecosystem-frozen ``mcp==1.29.0`` — the *same* client transport
  this repository's stdio connector already speaks. The binding this repository
  selects to govern the call (``official-mcp-sdk.python.v0.1`` or
  ``fastmcp.middleware.v0.1``) is a **receipt fact**, distinct from the external
  server's own SDK.

Because the surface speaks standard MCP stdio, the *existing*
:class:`~dagr_mcp_service.connectors.stdio.StdioToolConnector` governs it with no
new transport code: every governed call is one independent
``spawn -> initialize -> one tools/call -> teardown`` cycle against the
operator-launched external server, exactly as it would be for any other
unmodified external MCP server.

What a DAGR receipt emitted over this connector DOES and DOES NOT prove
----------------------------------------------------------------------
Driving a call through this target and
:func:`dagr_mcp_service.adapter.execute_governed_call` causes this repository's
*own* signed SRS admission/outcome receipts to be emitted (metadata-only, hash
refs; ``retention_class_applied=hash_only``). Those receipts prove **only what
the configured DAGR boundary recorded and signed** about the governed call:
whether it was admitted / refused / deferred, and — for an admitted call — the
neutral outcome family the boundary observed.

A DAGR receipt emitted here is emphatically **NOT**:

* an editorial ``source_capture`` receipt or any acquisition producer fact — the
  acquisition surface mints those itself; this boundary neither relabels its own
  receipts as such nor promotes the ones it forwards;
* an ``arcs-verify`` result or any independent verification verdict — this
  repository is a producer, not a verifier, and imports no verifier;
* evidence that the referenced source, capture, or proposal is true, admitted,
  standing, or verified.

No promotion of what the surface returns
----------------------------------------
The acquisition surface is proposal-only: it returns refs / digests / proposal
artifacts (``is_proposal=true``, ``source_capture`` eligibility hints, an
explicit unbound state on non-match). This connector returns those artifacts
through the governed response **without promoting them**: a proposal stays a
proposal, a referenced ``source_capture`` receipt stays a producer fact, and no
admission / standing / verification is conferred by the mere fact that the call
was governed. Governing the call records that the call happened at this
boundary; it confers no editorial or verification status on the call's result.

Import discipline
-----------------
Importing this module (and :mod:`dagr_mcp_service`) never imports ``mcp``,
``fastmcp``, ``counterpedia_acquisition``, ``arcs_verify``, or a transport
library. It imports only the pure, transport-free
:class:`~dagr_mcp_service.connectors.stdio.StdioTargetConfig` /
:class:`~dagr_mcp_service.connectors.stdio.StdioToolConnector` data types, whose
own PEP 562 lazy discipline defers every real transport import to the coroutine
that actually opens a connection.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from dagr_mcp_service.connectors.stdio import StdioTargetConfig, StdioToolConnector

# --------------------------------------------------------------------------- #
# Provenance pins — reproduced literals, never imported (see module docstring). #
# --------------------------------------------------------------------------- #

# counterpedia-acquisition main, PR #23: "feat(mcp): proposal-only acquisition
# tool surface v0.1". The surface froze at this commit; these literals are
# reproduced from src/acquisition/mcp_surface.py at that commit, not imported.
ACQUISITION_SURFACE_REPO = "counterpedia-acquisition"
ACQUISITION_SURFACE_COMMIT = "2398f17"

# Reproduced from acquisition.mcp_surface.MCP_SURFACE_SCHEMA.
ACQUISITION_SURFACE_SCHEMA = "acquisition.mcp_surface.v0.1"

# The external surface serves its tools over the official MCP Python SDK, the
# ecosystem-frozen version (acquisition's optional ``[mcp]`` extra; this
# repository's own ``official-sdk`` extra pins the identical version).
ACQUISITION_SDK_PIN = "mcp==1.29.0"

# Reproduced from acquisition.mcp_surface.TOOL_NAMES (dotted, acquisition-scoped,
# proposal-only). These are stable, receipt-adjacent routing facts — the closed
# set of tool names a governed call to this surface may name. A tool name outside
# this set is refused (``unknown_tool_fail_closed``) before any process spawns.
ACQUISITION_TOOL_CAPTURE_URL = "acquisition.capture_url"
ACQUISITION_TOOL_PROCESS_SOURCE = "acquisition.process_source"
ACQUISITION_TOOL_COMPARE_CAPTURES = "acquisition.compare_captures"
ACQUISITION_TOOL_PROCESS_BROWSER_OBSERVATION = "acquisition.process_browser_observation"

ACQUISITION_TOOL_NAMES: tuple[str, ...] = (
    ACQUISITION_TOOL_CAPTURE_URL,
    ACQUISITION_TOOL_PROCESS_SOURCE,
    ACQUISITION_TOOL_COMPARE_CAPTURES,
    ACQUISITION_TOOL_PROCESS_BROWSER_OBSERVATION,
)

# The default operator-facing target handle a caller's GovernedCallRequest names
# to route to this surface. It carries no authority; it is a routing label the
# operator maps to the pinned config below.
DEFAULT_ACQUISITION_TARGET_HANDLE = "external:counterpedia-acquisition"


def acquisition_stdio_target(
    command: Sequence[str],
    *,
    handle: str = DEFAULT_ACQUISITION_TARGET_HANDLE,
    known_tools: frozenset[str] = frozenset(ACQUISITION_TOOL_NAMES),
    env: Mapping[str, str] | None = None,
    cwd: str | None = None,
    timeout_seconds: float = 30.0,
) -> StdioTargetConfig:
    """Pin the external acquisition MCP server as one stdio target config.

    ``command`` is the operator-authored, argv-and-environment-pinned launch of
    the *external* acquisition MCP server (``command[0]`` must be an absolute
    path — enforced by :class:`StdioTargetConfig`). It is deployment
    configuration, never a caller/tool argument and never a request field: a
    ``GovernedCallRequest`` only ever carries the target *handle*, resolved here
    against operator config.

    ``known_tools`` defaults to the full pinned :data:`ACQUISITION_TOOL_NAMES`
    set. An operator may pass a narrower subset to expose fewer of the surface's
    tools through this boundary; a tool name outside the supplied set is refused
    before any process is spawned. This helper adds no tool logic — it only
    fills a :class:`StdioTargetConfig` with the pinned facts.
    """

    return StdioTargetConfig(
        handle=handle,
        command=tuple(command),
        known_tools=frozenset(known_tools),
        env=dict(env) if env else {},
        cwd=cwd,
        timeout_seconds=timeout_seconds,
    )


def build_acquisition_connector(
    command: Sequence[str],
    *,
    handle: str = DEFAULT_ACQUISITION_TARGET_HANDLE,
    known_tools: frozenset[str] = frozenset(ACQUISITION_TOOL_NAMES),
    env: Mapping[str, str] | None = None,
    cwd: str | None = None,
    timeout_seconds: float = 30.0,
) -> StdioToolConnector:
    """Build a governed stdio connector pinned to the external acquisition surface.

    Thin composition over the *existing*
    :class:`~dagr_mcp_service.connectors.stdio.StdioToolConnector`: it registers a
    single acquisition target (see :func:`acquisition_stdio_target`) and returns
    the connector ready to hand to
    :func:`dagr_mcp_service.adapter.execute_governed_call`. No new connector type,
    no new decision path.
    """

    target = acquisition_stdio_target(
        command,
        handle=handle,
        known_tools=known_tools,
        env=env,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
    )
    return StdioToolConnector({target.handle: target})


__all__ = [
    "ACQUISITION_SURFACE_REPO",
    "ACQUISITION_SURFACE_COMMIT",
    "ACQUISITION_SURFACE_SCHEMA",
    "ACQUISITION_SDK_PIN",
    "ACQUISITION_TOOL_CAPTURE_URL",
    "ACQUISITION_TOOL_PROCESS_SOURCE",
    "ACQUISITION_TOOL_COMPARE_CAPTURES",
    "ACQUISITION_TOOL_PROCESS_BROWSER_OBSERVATION",
    "ACQUISITION_TOOL_NAMES",
    "DEFAULT_ACQUISITION_TARGET_HANDLE",
    "acquisition_stdio_target",
    "build_acquisition_connector",
]
