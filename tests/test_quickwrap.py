from __future__ import annotations

import json
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.client import Client

import dagr_mcp


async def test_quickwrap_installs_existing_fastmcp_binding(tmp_path: Path) -> None:
    server = FastMCP("quickwrap-test")
    assert (
        dagr_mcp.quickwrap(
            server,
            output=tmp_path,
            tool_classes={"ping": "read"},
        )
        is server
    )

    @server.tool
    async def ping(value: str) -> dict[str, str]:
        return {"value": value}

    async with Client(server) as client:
        result = await client.call_tool("ping", {"value": "pong"})
        assert result is not None

    trust_bundle = json.loads((tmp_path / "issuer-keys.json").read_text(encoding="utf-8"))
    assert trust_bundle["issuers"][0]["issuer_id"] == "issuer:dagr:quickwrap"

    receipts = sorted(tmp_path.glob("urn_srs_receipt_*.json"))
    assert len(receipts) == 2
    kinds = {json.loads(path.read_text(encoding="utf-8"))["receipt_kind"] for path in receipts}
    assert kinds == {"admission", "outcome"}
