"""Shared loopback sam-node ``/mcp`` fixture for the SAM-native connector suite.

Not itself a pytest test module (no ``test_*`` collected here). Emulates the
local sam-node process's Streamable-HTTP ``/mcp`` endpoint the way
``tests/_gateway_service_remote_fixtures.py`` emulates a generic remote MCP
server: a real FastMCP app, run via ``uvicorn`` in a background thread bound
to ``127.0.0.1``, driven over the actual pinned ``mcp`` client transport
through :mod:`dagr_mcp_service.connectors.remote`. This is the OFFLINE mock
the SAM-NATIVE-MCP-BIND0 lane's posture requires -- no live ``sam-node``
binary, no external network, ever. It exposes the same four native tool
names alpha.7's sam-node exposes on ``/mcp``
(``discover_remote_services``, ``find_remote_tools``,
``describe_remote_tool``, ``call_remote_tool``) with a small, fixed, in-memory
peer/tool table encoding the hostile scenarios this lane must prove
fail-closed.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Iterator

import pytest

pytest.importorskip("fastmcp")
pytest.importorskip("mcp")
pytest.importorskip("uvicorn")

# Imported at module scope (not inside _build_sam_fixture_app) because this
# module has ``from __future__ import annotations``: a locally-imported name
# used only in a function's own annotations would be an unresolvable forward
# reference at schema-generation time, since FastMCP/pydantic evaluate those
# annotations against the function's *module* globals, not its local scope.
from fastmcp.tools.tool import ToolResult  # noqa: E402

# Peers this fixture "knows about" -- i.e. peers the mesh has actually
# connected and whose control-plane biscuit the fixture pretends sam-node
# already validated. Each entry's labels are what a required_labels check is
# evaluated against.
_KNOWN_PEERS: dict[str, frozenset[str]] = {
    "peer-good": frozenset({"vip"}),
    "peer-no-labels": frozenset(),
}

# A peer sam-node's own mesh layer auth-rejected. Per the upstream contract,
# an auth-rejected peer is HIDDEN from discovery -- it never appears in
# _KNOWN_PEERS/discover_remote_services, but call_remote_tool against it
# still exists as a distinct, explicit failure path (a caller who already
# knew the peer id from some other source, e.g. a stale config, still gets a
# fail-closed answer, never a silent substitution).
_AUTH_REJECTED_PEER = "peer-rejected"

# Namespaced remote tools the fixture actually knows how to "route" a
# call_remote_tool call to, keyed by (peer_id, tool_name).
_KNOWN_REMOTE_TOOLS: frozenset[tuple[str, str]] = frozenset(
    {
        ("peer-good", "mcp://svc/echo"),
        ("peer-no-labels", "mcp://svc/echo"),
    }
)

REQUIRED_AUTH_HEADER = "X-Sam-Authentication"
REQUIRED_AUTH_VALUE = "Bearer test-fixture-token"


def _build_sam_fixture_app(*, require_auth_header: bool):
    from fastmcp import FastMCP
    from fastmcp.exceptions import ToolError

    server = FastMCP("sam-node-loopback-fixture")

    @server.tool()
    def discover_remote_services(
        type: str,
        name: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict:
        if type not in ("mcp", "inference"):
            raise ToolError(f"unsupported discovery type {type!r}")
        # peer-rejected is deliberately absent: an auth-rejected peer is
        # hidden from discovery, never listed.
        services = [{"peer_id": peer_id, "service_name": "svc"} for peer_id in _KNOWN_PEERS]
        return {"services": services}

    @server.tool()
    def find_remote_tools(
        intent: str | None = None,
        peer_id: str | None = None,
        service_name: str | None = None,
        tool_name: str | None = None,
    ) -> dict:
        tools = [
            {"peer_id": pid, "tool_name": tname} for pid, tname in sorted(_KNOWN_REMOTE_TOOLS)
        ]
        return {"tools": tools}

    @server.tool()
    def describe_remote_tool(peer_id: str, tool_name: str) -> dict:
        if (peer_id, tool_name) not in _KNOWN_REMOTE_TOOLS:
            raise ToolError("tool not found on peer")
        return {
            "peer_id": peer_id,
            "tool_name": tool_name,
            "input_schema": {"type": "object", "properties": {"x": {"type": "string"}}},
        }

    @server.tool()
    async def call_remote_tool(
        peer_id: str,
        tool_name: str,
        arguments: dict | None = None,
        required_labels: list[str] | None = None,
    ) -> ToolResult:
        arguments = arguments or {}
        required_labels = required_labels or []

        # A test-only slowness hook, nested inside "arguments" -- the only
        # field this tool's real alpha.7 signature has that a caller's own
        # payload ever reaches. A real remote tool being slow is exactly
        # what this simulates; it is never a top-level SAM routing field.
        sleep_seconds = arguments.get("__sleep_seconds__")
        if sleep_seconds is not None:
            await asyncio.sleep(sleep_seconds)

        if peer_id == _AUTH_REJECTED_PEER:
            return ToolResult(content="peer auth rejected", is_error=True)

        labels = _KNOWN_PEERS.get(peer_id)
        if labels is None:
            return ToolResult(content="peer not connected", is_error=True)

        missing = sorted(set(required_labels) - labels)
        if missing:
            return ToolResult(content=f"required labels missing: {missing}", is_error=True)

        if (peer_id, tool_name) not in _KNOWN_REMOTE_TOOLS:
            return ToolResult(content="tool not found on peer", is_error=True)

        if peer_id == "peer-good" and arguments.get("x") == "__empty__":
            # A deliberately malformed-looking success: isError False but no
            # content -- exercises the connector's own structural validation,
            # independent of what the real mcp client would ever produce.
            return ToolResult(content=[], structured_content={}, is_error=False)

        # Echo back exactly what was received (peer_id, tool_name,
        # arguments) so a test can prove no SAM routing metadata leaked into
        # -- or out of -- the argument/result identity, and that caller-
        # supplied decoy keys never override the operator-resolved values.
        return ToolResult(
            content=f"echo:{arguments.get('x')}",
            structured_content={
                "received_peer_id": peer_id,
                "received_tool_name": tool_name,
                "received_arguments": arguments,
            },
            is_error=False,
        )

    app = server.http_app(path="/mcp")

    if require_auth_header:
        from starlette.responses import PlainTextResponse

        inner_app = app

        async def _auth_gate(scope, receive, send):
            if scope["type"] == "http":
                headers = dict(scope.get("headers") or [])
                value = headers.get(REQUIRED_AUTH_HEADER.lower().encode("latin-1"))
                if value is None or value.decode("latin-1") != REQUIRED_AUTH_VALUE:
                    response = PlainTextResponse("unauthorized", status_code=401)
                    await response(scope, receive, send)
                    return
            await inner_app(scope, receive, send)

        return _auth_gate

    return app


class LoopbackSamNodeServer:
    """A real Streamable HTTP server emulating sam-node's ``/mcp`` endpoint,
    bound to an OS-assigned loopback port.
    """

    def __init__(self, *, require_auth_header: bool = False) -> None:
        self.require_auth_header = require_auth_header
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(128)
        self.port: int = self._sock.getsockname()[1]
        self.base_url: str = f"http://127.0.0.1:{self.port}/mcp"
        self._server = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        import uvicorn

        app = _build_sam_fixture_app(require_auth_header=self.require_auth_header)
        config = uvicorn.Config(app, log_level="warning")
        self._server = uvicorn.Server(config)
        self._server.install_signal_handlers = False

        def _run() -> None:
            asyncio.run(self._server.serve(sockets=[self._sock]))

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

        deadline = time.monotonic() + 10.0
        while not self._server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        if not self._server.started:
            raise RuntimeError("SAM loopback fixture server did not start in time")

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=10.0)


@pytest.fixture(scope="module")
def loopback_sam_node_server() -> Iterator[LoopbackSamNodeServer]:
    server = LoopbackSamNodeServer(require_auth_header=False)
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture(scope="module")
def loopback_sam_node_server_with_auth() -> Iterator[LoopbackSamNodeServer]:
    server = LoopbackSamNodeServer(require_auth_header=True)
    server.start()
    try:
        yield server
    finally:
        server.stop()
