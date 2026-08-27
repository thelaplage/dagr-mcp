"""Probe the native SAM semantic path against the clean-replay mesh."""
from __future__ import annotations

import argparse
import asyncio
import json

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


def _tools_from_result(result) -> list:
    """Extract the find_remote_tools list from a CallToolResult.

    alpha.7's Go sam-node returns the tool list as a bare JSON array in the
    result's text content and does NOT populate structuredContent["tools"];
    tolerate both shapes rather than assuming one."""
    sc = getattr(result, "structuredContent", None)
    if isinstance(sc, list):
        return sc
    if isinstance(sc, dict):
        for key in ("tools", "result"):
            if isinstance(sc.get(key), list):
                return sc[key]
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            continue
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("tools"), list):
            return data["tools"]
    return []


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
    tools = _tools_from_result(tools_result)
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
