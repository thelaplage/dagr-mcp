"""Shared loopback MCP server fixture for the A9 remote-connector test suite.

Not itself a pytest test module (no ``test_*`` collected here) — a small,
focused support module for ``tests/test_gateway_service_remote_connector.py``
and ``tests/test_gateway_service_remote_integration.py``. Spins up a real MCP
server over Streamable HTTP (FastMCP's own ``http_app()`` ASGI app, run via
``uvicorn`` in a background thread bound to ``127.0.0.1``) so both test
modules drive the actual pinned ``mcp==1.28.1`` client transport
(``dagr_mcp_service.connectors.remote``) against a genuine remote server
process, not a mock — per the governing scope document's instruction to use
"a real loopback remote MCP server and the actual pinned client transport."
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


def _build_fixture_app():
    from fastmcp import FastMCP
    from fastmcp.server.dependencies import get_http_headers

    server = FastMCP("a9-loopback-fixture")

    @server.tool()
    def echo(x: str) -> str:
        return f"echo:{x}"

    @server.tool()
    def boom(x: str) -> str:
        raise ValueError("boom-internal-detail")

    @server.tool()
    async def slow(x: str, seconds: float = 10.0) -> str:
        await asyncio.sleep(seconds)
        return f"slow-done:{x}"

    @server.tool()
    def observed_headers(
        # FastMCP tools reject *args/**kwargs (ParsedFunction.from_function);
        # these named, defaulted, ignored parameters let a test pass a decoy
        # argument bundle (proving those values reach the remote tool only as
        # inert argument data, never as headers or trusted context) without
        # the call failing pydantic's "unexpected keyword argument" check.
        x: str | None = None,
        actor_ref: str | None = None,
        tenant_ref: str | None = None,
        Authorization: str | None = None,
        credential: str | None = None,
    ) -> dict[str, str]:
        # Lets a test prove a credential provider's headers actually reached
        # the wire, without the connector itself ever needing to expose them.
        # include_all=True: FastMCP's default strips "authorization" (among
        # others) as a hop-by-hop/security-sensitive header; this fixture
        # tool exists specifically to observe it, so the test-only server
        # must ask for it explicitly.
        return dict(get_http_headers(include_all=True))

    return server.http_app(path="/mcp")


class LoopbackMcpServer:
    """A real Streamable HTTP MCP server bound to an OS-assigned loopback port."""

    def __init__(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(128)
        self.port: int = self._sock.getsockname()[1]
        self.base_url: str = f"http://127.0.0.1:{self.port}/mcp"
        self._server = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        import uvicorn

        app = _build_fixture_app()
        config = uvicorn.Config(app, log_level="warning")
        self._server = uvicorn.Server(config)
        # Signal-handler installation only works on the main thread; this
        # server always runs on a background thread.
        self._server.install_signal_handlers = False

        def _run() -> None:
            asyncio.run(self._server.serve(sockets=[self._sock]))

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

        deadline = time.monotonic() + 10.0
        while not self._server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        if not self._server.started:
            raise RuntimeError("A9 loopback fixture server did not start in time")

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=10.0)


@pytest.fixture(scope="module")
def loopback_mcp_server() -> Iterator[LoopbackMcpServer]:
    server = LoopbackMcpServer()
    server.start()
    try:
        yield server
    finally:
        server.stop()
