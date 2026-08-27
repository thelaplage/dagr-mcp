"""Clean-replay governed market fixture over a real local SAM alpha.7 mesh.

Discovery is used only by this operator harness to identify the unique fixture
provider. It does not make discovery equal eligibility: the selected route is
then frozen into ``SamRouteConfig`` before the governed call executes.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from dagr_mcp.srs_receipts import RawEnvelopeFileSink, SigningIdentity, sha256_digest
from dagr_mcp_service.adapter import GatewayAdapterConfig, execute_governed_call
from dagr_mcp_service.connectors.remote import RemoteCredential, RemoteTargetConfig, RemoteToolConnector
from dagr_mcp_service.connectors.sam_native import SamNativeConnector, SamRouteConfig, find_sam_remote_tools
from dagr_mcp_service.contract import CallerGovernedCallRequest, GovernedCallRequest, TargetServerRef, TrustedActorRef
from dagr_mcp_service.resolution import BindingSelectorKey, FASTMCP_BINDING_VERSION

SAM_HANDLE = "sam:live-chain0"
TARGET_HANDLE = "market:fixture"
TOOL_ALIAS = "settle"
REMOTE_TOOL = "mcp://market/settle"


def _tools_from_result(result) -> list:
    """Extract the find_remote_tools list from a CallToolResult. alpha.7's Go
    sam-node returns a bare JSON array in text content and does not populate
    structuredContent["tools"]; tolerate both shapes."""
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
REQUEST_REF = "req:live-market0:1"


def _credential(token: str):
    def provider(_context):
        return RemoteCredential(headers={"X-Sam-Authentication": f"Bearer {token}"})
    return provider


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sam-endpoint", default="http://127.0.0.1:18101/mcp")
    ap.add_argument("--api-token", default="secret-token")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    sink = RawEnvelopeFileSink(args.output)
    identity = SigningIdentity.generate(
        issuer_id="issuer:sam-live-chain0",
        key_id="issuer.sam-live-chain0/key/1",
    )
    sink.write_trust_bundle(identity.trust_bundle())

    remote = RemoteToolConnector({
        SAM_HANDLE: RemoteTargetConfig(
            handle=SAM_HANDLE,
            endpoint_uri=args.sam_endpoint,
            allow_insecure_loopback=True,
            timeout_seconds=15.0,
            credential_provider=_credential(args.api_token),
        )
    })

    discovered = await find_sam_remote_tools(remote, sam_endpoint_handle=SAM_HANDLE)
    tools = _tools_from_result(discovered)
    matches = [row for row in tools if row.get("tool_name") == REMOTE_TOOL]
    peer_ids = sorted({str(row.get("peer_id")) for row in matches if row.get("peer_id")})
    if len(peer_ids) != 1:
        raise RuntimeError(f"expected exactly one {REMOTE_TOOL} provider; got {peer_ids!r}")

    connector = SamNativeConnector(
        remote_connector=remote,
        targets={TARGET_HANDLE: {TOOL_ALIAS: SamRouteConfig(
            sam_endpoint_handle=SAM_HANDLE,
            peer_id=peer_ids[0],
            remote_tool_name=REMOTE_TOOL,
        )}},
    )

    call_args = {"instrument": "DEMO", "quantity": 1}
    caller = CallerGovernedCallRequest(
        request_ref=REQUEST_REF,
        binding_selector=BindingSelectorKey(key="primary"),
        target_server_ref=TargetServerRef(handle=TARGET_HANDLE),
        tool_name=TOOL_ALIAS,
        argument_digest=sha256_digest(call_args),
        policy_profile_ref="policy-profile:sam-live-chain0",
    )
    request = GovernedCallRequest.from_caller_request(
        caller,
        actor_ref=TrustedActorRef(ref="actor:sam-live-chain0"),
    )
    config = GatewayAdapterConfig(
        binding_registry={"primary": FASTMCP_BINDING_VERSION},
        connector=connector,
        identity=identity,
        sink=sink,
        runtime_instance_id="runtime:sam-live-chain0",
        boundary_id="boundary:sam-live-chain0",
        policy_pack_id="policy:sam-live-chain0",
        policy_pack_version="2026.08.26",
        tool_classes={TOOL_ALIAS: "write"},
        additional_attestation_limits=(
            "The market backend is a deterministic fixture; result_returned does not establish a real financial settlement.",
        ),
    )

    response = await execute_governed_call(request, arguments=call_args, config=config)
    summary = {
        "logical_call_id": response.logical_call_id,
        "disposition": response.decision.disposition,
        "outcome": response.decision.outcome,
        "receipt_kinds": [r.receipt_kind for r in response.receipts],
        "provider_peer_id": peer_ids[0],
        "authority_effect": "none",
    }
    print(json.dumps(summary, sort_keys=True))
    if summary["logical_call_id"] != REQUEST_REF:
        return 2
    if summary["disposition"] != "admitted" or summary["outcome"] != "result":
        return 3
    if summary["receipt_kinds"] != ["admission", "outcome"]:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
