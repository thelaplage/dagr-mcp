"""Shared test harness: a real stateless Streamable HTTP (2026-07-28) app.

Used by both the acceptance-matrix tests (this package) and the genuine HTTP
proof tests (``tests/test_http_proof_v2.py`` at the repo root). Every call
here goes through the real ``mcp==2.0.0`` ASGI stack -- ``Server.
streamable_http_app`` -- never a hand-rolled stand-in for it.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import types as mcp_types
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
from starlette.testclient import TestClient

from dagr_mcp_core.srs_receipts import RawEnvelopeFileSink, SignedReceiptEmitter, SigningIdentity
from dagr_mcp_sdk_v2.adapter import SdkV2BindingConfig, SdkV2LifecycleAdapter
from dagr_mcp_sdk_v2.server import GovernedTool, build_governed_server

PROTOCOL_VERSION = "2026-07-28"


def request_headers(*, method: str, name: str) -> dict[str, str]:
    """The exact required header set for a modern stateless request. No
    ``Mcp-Session-Id`` is ever sent -- the modern path never reads it."""

    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Mcp-Protocol-Version": PROTOCOL_VERSION,
        "Mcp-Method": method,
        "Mcp-Name": name,
    }


def tools_call_body(request_id: int, tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """The exact required body shape: no ``initialize``, per-request `_meta`."""

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": dict(arguments),
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
                "io.modelcontextprotocol/clientCapabilities": {},
            },
        },
    }


@dataclass
class RecordingDelegate:
    """Wraps a tool body, recording invocation count and call order."""

    body: Callable[[Mapping[str, Any]], Any]
    calls: list[Mapping[str, Any]] = field(default_factory=list)

    async def __call__(self, arguments: Mapping[str, Any]) -> Any:
        self.calls.append(dict(arguments))
        result = self.body(arguments)
        if hasattr(result, "__await__"):
            result = await result
        return result

    @property
    def call_count(self) -> int:
        return len(self.calls)


def ok_result(text: str = "ok") -> mcp_types.CallToolResult:
    return mcp_types.CallToolResult(content=[mcp_types.TextContent(type="text", text=text)], isError=False)


def error_result(text: str = "boom") -> mcp_types.CallToolResult:
    return mcp_types.CallToolResult(content=[mcp_types.TextContent(type="text", text=text)], isError=True)


@dataclass
class GovernedTestApp:
    server: Server
    app: Any
    adapter: SdkV2LifecycleAdapter
    emitter: SignedReceiptEmitter
    receipts_dir: Path
    delegates: dict[str, RecordingDelegate]

    def client(self) -> TestClient:
        return TestClient(self.app)

    def receipts(self) -> list[dict[str, Any]]:
        return [json.loads(p.read_text()) for p in sorted(self.receipts_dir.glob("*.json"))]

    def admission_receipts(self) -> list[dict[str, Any]]:
        return [r for r in self.receipts() if r["receipt_kind"] == "admission"]

    def outcome_receipts(self) -> list[dict[str, Any]]:
        return [r for r in self.receipts() if r["receipt_kind"] == "outcome"]


def build_governed_test_app(
    tmp_path: Path,
    *,
    tool_bodies: Mapping[str, Callable[[Mapping[str, Any]], Any]],
    tool_classes: Mapping[str, str] | None = None,
    pre_execution_receipt_failure: Mapping[str, str] | None = None,
    emitter: SignedReceiptEmitter | None = None,
    receipts_dir: Path | None = None,
) -> GovernedTestApp:
    """Build a real governed v2 Server + stateless ASGI app for one test.

    ``tool_bodies`` maps tool name -> a plain (sync or async) callable; each is
    wrapped in a :class:`RecordingDelegate` so invocation count/order can be
    mechanically asserted per the acceptance matrix.
    """

    receipts_dir = receipts_dir or (tmp_path / "receipts")
    if emitter is None:
        identity = SigningIdentity.generate(issuer_id="issuer:v2-test", key_id="issuer.v2-test/key/1")
        sink = RawEnvelopeFileSink(receipts_dir)
        emitter = SignedReceiptEmitter(identity=identity, sink=sink)

    tool_classes = dict(tool_classes or {name: "read" for name in tool_bodies})
    config = SdkV2BindingConfig(
        runtime_instance_id="rt:v2-test",
        boundary_id="b:v2-test",
        policy_pack_id="p:v2-test",
        policy_pack_version="1",
        tool_classes=tool_classes,  # type: ignore[arg-type]
        pre_execution_receipt_failure=(
            pre_execution_receipt_failure  # type: ignore[arg-type]
            or {"read": "fail_open", "write": "fail_closed", "destructive": "fail_closed"}
        ),
    )
    adapter = SdkV2LifecycleAdapter(emitter=emitter, config=config)

    delegates = {name: RecordingDelegate(body) for name, body in tool_bodies.items()}
    tools = [
        GovernedTool(
            definition=mcp_types.Tool(name=name, description=name, inputSchema={"type": "object"}),
            handler=delegate,
        )
        for name, delegate in delegates.items()
    ]

    server = build_governed_server("dagr-mcp-sdk-v2-test", adapter=adapter, tools=tools, version="0.0.1")
    app = server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(allowed_hosts=["testserver"]),
    )
    return GovernedTestApp(
        server=server, app=app, adapter=adapter, emitter=emitter,
        receipts_dir=receipts_dir, delegates=delegates,
    )


def call_tool(client: TestClient, tool_name: str, arguments: Mapping[str, Any], *, request_id: int = 1):
    return client.post(
        "/mcp",
        json=tools_call_body(request_id, tool_name, arguments),
        headers=request_headers(method="tools/call", name=tool_name),
    )
