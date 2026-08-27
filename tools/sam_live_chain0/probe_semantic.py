"""Probe the native SAM semantic path against the clean-replay mesh."""
from __future__ import annotations

import argparse
import asyncio

from _result_shapes import tools_from_result
from dagr_mcp_service.connectors.remote import RemoteCredential, RemoteTargetConfig, RemoteToolConnector
from dagr_mcp_service.connectors.sam_native import (
    SamNativeConnector,
    SamRouteConfig,
    discover_sam_peers,
    find_sam_remote_tools,
    describe_sam_remote_tool,
)

HANDLE = "sam:live-chain0"
HELLO = "mcp://greeter/hello"


def provider(token: str):
    def _p(_context):
        return RemoteCredential(headers={"X-Sam-Authentication": f"Bearer {token}"})
    return _p


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sam-endpoint", default="http://127.0.0.1:18101/mcp")
    ap.add_argument("--api-token", default="secret-token")
    args = ap.parse_args()

    remote = RemoteToolConnector({HANDLE: RemoteTargetConfig(
        handle=HANDLE,
        endpoint_uri=args.sam_endpoint,
        allow_insecure_loopback=True,
        timeout_seconds=15.0,
        credential_provider=provider(args.api_token),
    )})
    discovered = await discover_sam_peers(remote, sam_endpoint_handle=HANDLE, service_type="mcp")
    if discovered.isError:
        raise RuntimeError("discover_remote_services failed")
    tools_result = await find_sam_remote_tools(remote, sam_endpoint_handle=HANDLE)
    tools = tools_from_result(tools_result)
    peers = sorted({str(t["peer_id"]) for t in tools if t.get("tool_name") == HELLO and t.get("peer_id")})
    if len(peers) != 1:
        raise RuntimeError(f"expected one greeter provider, got {peers!r}")
    described = await describe_sam_remote_tool(remote, sam_endpoint_handle=HANDLE, peer_id=peers[0], tool_name=HELLO)
    if described.isError:
        raise RuntimeError("describe_remote_tool failed")
    connector = SamNativeConnector(
        remote_connector=remote,
        targets={"greeter:fixture": {"hello": SamRouteConfig(
            sam_endpoint_handle=HANDLE,
            peer_id=peers[0],
            remote_tool_name=HELLO,
        )}},
    )
    handler = connector.resolve("greeter:fixture", "hello")
    result = await handler({"name": "SAM"})
    if result.isError:
        raise RuntimeError("call_remote_tool returned error")
    text = "\n".join(getattr(c, "text", "") for c in result.content)
    if "Hello, SAM!" not in text:
        raise RuntimeError(f"unexpected greeter result: {text!r}")
    print("SAM-LIVE-CHAIN0 semantic parity: PASS — discover→find→describe→call_remote_tool; Hello, SAM!")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
