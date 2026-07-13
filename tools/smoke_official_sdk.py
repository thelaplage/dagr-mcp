#!/usr/bin/env python3
"""Clean-wheel official-SDK smoke: real in-process ``tools/list`` + ``tools/call``.

Runs the second (official Python MCP SDK) DAGR binding against the SDK's real
in-process client/server transport
(``mcp.shared.memory.create_connected_server_and_client_session``) — no stdio,
SSE, HTTP, or ASGI transport — and asserts:

* ``tools/list`` returns the fixture tool;
* an admitted ``tools/call`` returns a non-error result and writes a linked
  admission + ``result_returned`` outcome receipt pair;
* a delegated tool returning ``mcp.types.CreateTaskResult`` fails closed (the
  capability difference: the bound ``tools/call`` seam does not carry it), surfaces
  as an ``isError`` result, and writes NO ``task_submitted`` receipt.

Intended to run from an environment where ``dagr-mcp`` is installed from the built
wheel (run from a directory that does NOT contain the repo source, so the wheel is
exercised rather than the working tree). Exits non-zero on any failure.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path


def _fail(message: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"official-sdk smoke FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


async def _main() -> None:
    from mcp import types as mcp_types
    from mcp.shared.memory import create_connected_server_and_client_session as connect

    from dagr_mcp.srs_receipts import RawEnvelopeFileSink, SignedReceiptEmitter, SigningIdentity
    from dagr_mcp_sdk_binding.adapter import SdkBindingConfig, SdkLifecycleAdapter
    from dagr_mcp_sdk_binding.server import GovernedTool, build_governed_server

    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw) / "receipts"
        identity = SigningIdentity.generate(
            issuer_id="issuer:smoke:sdk", key_id="issuer.smoke.sdk/key/1"
        )
        emitter = SignedReceiptEmitter(identity=identity, sink=RawEnvelopeFileSink(directory))
        adapter = SdkLifecycleAdapter(
            emitter=emitter,
            config=SdkBindingConfig(
                runtime_instance_id="rt:smoke",
                boundary_id="b:smoke",
                policy_pack_id="p:smoke",
                policy_pack_version="1",
                tool_classes={"echo": "read", "submit": "write"},
            ),
        )

        async def echo(_args):
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text="ok")], isError=False
            )

        async def submit(_args):
            return mcp_types.CreateTaskResult(
                task=mcp_types.Task(
                    taskId="task-smoke",
                    status="working",
                    createdAt="2026-01-01T00:00:00Z",
                    lastUpdatedAt="2026-01-01T00:00:00Z",
                    ttl=None,
                )
            )

        def _tool(name, handler):
            return GovernedTool(
                definition=mcp_types.Tool(
                    name=name, description="smoke", inputSchema={"type": "object"}
                ),
                handler=handler,
            )

        server = build_governed_server(
            "dagr-sdk-smoke",
            adapter=adapter,
            tools=[_tool("echo", echo), _tool("submit", submit)],
        )

        async with connect(server) as client:
            await client.initialize()

            listed = await client.list_tools()
            names = sorted(t.name for t in listed.tools)
            if names != ["echo", "submit"]:
                _fail(f"tools/list returned {names!r}")

            result = await client.call_tool("echo", {})
            if result.isError:
                _fail("admitted echo call returned isError=True")

            # task submission fails closed → isError result, no task_submitted receipt.
            task_res = await client.call_tool("submit", {})
            if not task_res.isError:
                _fail("returned CreateTaskResult was not failed-closed to an isError result")

        receipts = [
            json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(directory.glob("urn_srs_receipt_*.json"))
        ]
        kinds = sorted(r["receipt_kind"] for r in receipts)
        if "admission" not in kinds or "outcome" not in kinds:
            _fail(f"expected admission + outcome receipts, got kinds={kinds!r}")
        outcomes = [r.get("outcome") for r in receipts if r["receipt_kind"] == "outcome"]
        if "result_returned" not in outcomes:
            _fail(f"expected a result_returned outcome, got {outcomes!r}")
        if any(o == "task_submitted" for o in outcomes):
            _fail("a task_submitted outcome receipt was emitted; it must be unsupported")

    print("official-sdk smoke OK: tools/list + tools/call over real in-process transport")


if __name__ == "__main__":
    asyncio.run(_main())
