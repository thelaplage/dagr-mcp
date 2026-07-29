"""Runnable example: a real stateless Streamable HTTP (2026-07-28) DAGR server.

Built entirely from public ``mcp==2.0.0`` APIs
(``mcp.server.lowlevel.Server``, ``Server.streamable_http_app``) plus
``dagr-mcp-core`` and ``dagr-mcp-sdk-v2`` -- no private SDK symbol, no
``fastmcp``. Run standalone as a real network server:

    pip install -e packages/dagr-mcp-core -e packages/dagr-mcp-sdk-v2
    uvicorn examples.http_proof_v2.server:app --host 127.0.0.1 --port 8765

Or call :func:`build_app` directly to embed the same construction in another
script with your own receipts directory (see ``client_proof.py``, which does
exactly this behind a real uvicorn server on a background thread).
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp import types as mcp_types
from mcp.server.transport_security import TransportSecuritySettings

from dagr_mcp_core.srs_receipts import RawEnvelopeFileSink, SignedReceiptEmitter, SigningIdentity
from dagr_mcp_sdk_v2.adapter import SdkV2BindingConfig, SdkV2LifecycleAdapter
from dagr_mcp_sdk_v2.server import GovernedTool, build_governed_server

DEFAULT_RECEIPTS_DIR = Path(
    os.environ.get("DAGR_HTTP_PROOF_RECEIPTS_DIR", "/tmp/dagr-http-proof-v2-receipts")
)


async def echo_tool(arguments):
    text = str(arguments.get("text", ""))
    return mcp_types.CallToolResult(content=[mcp_types.TextContent(type="text", text=text)], isError=False)


async def boom_tool(_arguments):
    raise ValueError("intentional failure for the demo's error-path proof")


def build_app(receipts_dir: Path = DEFAULT_RECEIPTS_DIR, *, allowed_hosts: list[str] | None = None):
    """Return ``(asgi_app, signing_identity, receipts_dir)``.

    A fresh :class:`SigningIdentity` is generated per call (never persisted)
    so each run's receipts are independently verifiable against that run's own
    trust bundle -- see ``client_proof.py``.
    """

    identity = SigningIdentity.generate(
        issuer_id="issuer:http-proof-v2", key_id="issuer.http-proof-v2/key/1"
    )
    sink = RawEnvelopeFileSink(receipts_dir)
    emitter = SignedReceiptEmitter(identity=identity, sink=sink)
    config = SdkV2BindingConfig(
        runtime_instance_id="rt:http-proof-v2",
        boundary_id="b:http-proof-v2",
        policy_pack_id="p:http-proof-v2",
        policy_pack_version="1",
        tool_classes={"echo": "read", "boom": "write"},
    )
    adapter = SdkV2LifecycleAdapter(emitter=emitter, config=config)
    tools = [
        GovernedTool(
            definition=mcp_types.Tool(
                name="echo",
                description="Echo the given text back.",
                inputSchema={"type": "object", "properties": {"text": {"type": "string"}}},
            ),
            handler=echo_tool,
        ),
        GovernedTool(
            definition=mcp_types.Tool(name="boom", description="Always raises.", inputSchema={"type": "object"}),
            handler=boom_tool,
        ),
    ]
    server = build_governed_server(
        "dagr-mcp-http-proof-v2", adapter=adapter, tools=tools, version="0.2.0"
    )
    asgi_app = server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=allowed_hosts or ["127.0.0.1:8765", "localhost:8765", "testserver"]
        ),
    )
    return asgi_app, identity, receipts_dir


# Module-level app object for `uvicorn examples.http_proof_v2.server:app`.
app, _identity, _receipts_dir = build_app()


if __name__ == "__main__":
    import uvicorn

    print("DAGR-governed MCP server (official-mcp-sdk.python.v0.2)")
    print("  http://127.0.0.1:8765/mcp")
    print(f"  receipts written to: {_receipts_dir}")
    uvicorn.run(app, host="127.0.0.1", port=8765)
