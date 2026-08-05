"""LIVE example: the merged dagr-mcp governed stdio connector in front of the
real, official ``@modelcontextprotocol/server-filesystem`` stdio MCP server.

Real subprocess. Real MCP handshake. Real dagr-mcp adapter/connector code.
No mocks, no stubs.

Scenarios exercised:
  1. ADMIT  -- read_text_file on a path inside the allowed root.
              Child spawned once, real content returned, receipts emitted.
  2. REFUSE -- write_file inside the allowed root (this example's policy
              never admits the mutating tool class). A sentinel file must
              NOT exist afterward -- proves the child ran ZERO times.
  3. REFUSE -- read_text_file on a path OUTSIDE the allowed root (policy
              path-containment check). Proves containment is enforced by
              dagr-mcp's own policy layer, not merely by the child server's
              own --allowed-root flag.
  4. REFUSE (fail-closed, unknown tool) -- a tool name that is not in the
              connector's own known_tools allowlist at all. Refused by
              StdioToolConnector.resolve() itself, before the (optional)
              policy_resolver ever runs and before any admission receipt is
              emitted.

This script demonstrates ONE configured governed path over ONE generic,
third-party stdio MCP server. It does not claim that "the filesystem is
governed" in general, nor any aggregate trust/safety verdict about the
target server -- see the example README for the bypass limitation.

This file is self-contained and portable: it hardcodes no machine-specific
paths. All working directories are created at runtime (see --workdir /
--allowed-root / --outside-root below, or the environment variable
DAGR_MCP_SHOWCASE_WORKDIR).

Run (see README.md for full prerequisites):

    export DAGR_MCP_SHOWCASE_WORKDIR="$(mktemp -d)"
    python live_run.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workdir",
        default=os.environ.get("DAGR_MCP_SHOWCASE_WORKDIR", ""),
        help=(
            "Directory to hold generated receipts, trust bundle, and output "
            "JSON. Defaults to a fresh tempfile.mkdtemp() directory (or the "
            "DAGR_MCP_SHOWCASE_WORKDIR environment variable if set). Never "
            "commit the contents of this directory."
        ),
    )
    parser.add_argument(
        "--allowed-root",
        default="",
        help="Allowed-root directory passed to the filesystem MCP server. "
        "Defaults to <workdir>/allowed_root, created fresh.",
    )
    parser.add_argument(
        "--outside-root",
        default="",
        help="A directory OUTSIDE the allowed root, used for the "
        "containment-refusal scenario. Defaults to <workdir>/outside_root.",
    )
    parser.add_argument(
        "--npx",
        default=os.environ.get("DAGR_MCP_SHOWCASE_NPX", ""),
        help="Path to the npx binary. Defaults to whatever `npx` resolves "
        "to on PATH.",
    )
    parser.add_argument(
        "--dagr-mcp-path",
        default=os.environ.get("DAGR_MCP_PATH", ""),
        help="Optional path to a dagr-mcp checkout to prepend to sys.path, "
        "for running against a local source tree without `pip install`.",
    )
    return parser.parse_args()


_ARGS = _parse_args()

if _ARGS.dagr_mcp_path:
    sys.path.insert(0, str(Path(_ARGS.dagr_mcp_path).resolve()))

import anyio  # noqa: E402

from dagr_mcp.srs_receipts import RawEnvelopeFileSink, SigningIdentity, sha256_digest  # noqa: E402
from dagr_mcp_service.adapter import GatewayAdapterConfig, execute_governed_call  # noqa: E402
from dagr_mcp_service.connectors.stdio import StdioTargetConfig, StdioToolConnector  # noqa: E402
from dagr_mcp_service.contract import (  # noqa: E402
    CallerGovernedCallRequest,
    GovernedCallRequest,
    TargetServerRef,
    TrustedActorRef,
)
from dagr_mcp_service.resolution import FASTMCP_BINDING_VERSION, BindingSelectorKey  # noqa: E402

WORKDIR = Path(_ARGS.workdir).resolve() if _ARGS.workdir else Path(tempfile.mkdtemp(prefix="dagr-mcp-showcase-"))
WORKDIR.mkdir(parents=True, exist_ok=True)
ALLOWED_ROOT = Path(_ARGS.allowed_root).resolve() if _ARGS.allowed_root else WORKDIR / "allowed_root"
OUTSIDE_ROOT = Path(_ARGS.outside_root).resolve() if _ARGS.outside_root else WORKDIR / "outside_root"
RECEIPTS_DIR = WORKDIR / "receipts"

NPX = _ARGS.npx or shutil.which("npx")
if not NPX:
    raise SystemExit(
        "npx not found. Install Node.js, or pass --npx /path/to/npx, or set "
        "DAGR_MCP_SHOWCASE_NPX."
    )

REAL_TOOLS = (
    "read_file",
    "read_text_file",
    "read_media_file",
    "read_multiple_files",
    "write_file",
    "edit_file",
    "create_directory",
    "list_directory",
    "list_directory_with_sizes",
    "directory_tree",
    "move_file",
    "search_files",
    "get_file_info",
    "list_allowed_directories",
)

MUTATING_TOOLS = {"write_file", "edit_file", "create_directory", "move_file"}
SAFE_READ_TOOLS = set(REAL_TOOLS) - MUTATING_TOOLS

CONNECTOR = StdioToolConnector(
    {
        "local:filesystem-mcp": StdioTargetConfig(
            handle="local:filesystem-mcp",
            command=(NPX, "-y", "@modelcontextprotocol/server-filesystem", str(ALLOWED_ROOT)),
            known_tools=frozenset(REAL_TOOLS),
            timeout_seconds=30.0,
        )
    }
)


def _path_args(tool_name: str, arguments: dict) -> list[str]:
    if tool_name == "read_multiple_files":
        return list(arguments.get("paths", []))
    for key in ("path", "source", "destination"):
        if key in arguments:
            value = arguments[key]
            return [value] if isinstance(value, str) else []
    return []


def _within_allowed_root(path_str: str) -> bool:
    try:
        resolved = Path(path_str).resolve()
    except OSError:
        return False
    try:
        resolved.relative_to(ALLOWED_ROOT.resolve())
        return True
    except ValueError:
        return False


def classify(tool_name: str, arguments: dict) -> SimpleNamespace:
    """The example policy this showcase demonstrates:

    - any mutating tool class (write_file/edit_file/create_directory/move_file)
      is refused outright, regardless of path -- this policy admits reads only.
    - any read tool is admitted only if every path argument it names resolves
      inside the configured allowed root; otherwise refused.
    - list_allowed_directories takes no path argument and is treated as a safe,
      admitted introspection call.
    """

    if tool_name in MUTATING_TOOLS:
        return SimpleNamespace(
            disposition="refused",
            tool_class="write",
            reason_code="policy_refused",
            parent_receipt_ref=None,
            additional_attestation_limits=(),
        )

    if tool_name == "list_allowed_directories":
        return SimpleNamespace(
            disposition="admitted",
            tool_class="read",
            reason_code=None,
            parent_receipt_ref=None,
            additional_attestation_limits=(),
        )

    paths = list(_path_args(tool_name, arguments))
    if paths and not all(_within_allowed_root(p) for p in paths):
        return SimpleNamespace(
            disposition="refused",
            tool_class="read",
            reason_code="policy_refused",
            parent_receipt_ref=None,
            additional_attestation_limits=(),
        )

    return SimpleNamespace(
        disposition="admitted",
        tool_class="read",
        reason_code=None,
        parent_receipt_ref=None,
        additional_attestation_limits=(),
    )


def build_config(policy_resolver, identity: SigningIdentity) -> GatewayAdapterConfig:
    sink = RawEnvelopeFileSink(RECEIPTS_DIR)
    config = GatewayAdapterConfig(
        binding_registry={"primary": FASTMCP_BINDING_VERSION},
        connector=CONNECTOR,
        identity=identity,
        sink=sink,
        runtime_instance_id="runtime:showcase:filesystem-mcp-live",
        boundary_id="boundary:showcase:filesystem-mcp-live",
        policy_pack_id="policy:showcase:filesystem-mcp-live",
        policy_pack_version="example-0.1",
        policy_resolver=policy_resolver,
    )
    return config


async def run_one(*, request_ref: str, tool_name: str, arguments: dict, seq: int, identity: SigningIdentity):
    disposition_ns = classify(tool_name, arguments)

    def policy_resolver(_snapshot, _actor):
        return disposition_ns

    config = build_config(policy_resolver, identity)

    digest = sha256_digest(dict(arguments))
    caller = CallerGovernedCallRequest(
        request_ref=request_ref,
        binding_selector=BindingSelectorKey(key="primary"),
        target_server_ref=TargetServerRef(handle="local:filesystem-mcp"),
        tool_name=tool_name,
        argument_digest=digest,
        policy_profile_ref="policy-profile:showcase-filesystem-mcp",
    )
    request = GovernedCallRequest.from_caller_request(
        caller, actor_ref=TrustedActorRef(ref="actor:showcase:operator")
    )

    response = await execute_governed_call(request, arguments=arguments, config=config)
    return {
        "seq": seq,
        "request_ref": request_ref,
        "tool_name": tool_name,
        "arguments": arguments,
        "predicted_disposition": disposition_ns.disposition,
        "disposition": response.decision.disposition,
        "outcome": getattr(response.decision, "outcome", None),
        "diagnostic_code": response.diagnostic_code,
        "num_receipts": len(response.receipts),
        "business_result_repr": (
            None if response.business_result is None else repr(response.business_result)[:400]
        ),
        "identity_issuer_id": identity.issuer_id,
    }


async def main():
    ALLOWED_ROOT.mkdir(parents=True, exist_ok=True)
    (ALLOWED_ROOT / "sample.txt").write_text("hello from inside the allowed root\n")

    if RECEIPTS_DIR.exists():
        shutil.rmtree(RECEIPTS_DIR)
    RECEIPTS_DIR.mkdir(parents=True)

    identity = SigningIdentity.generate(
        issuer_id="issuer:showcase:filesystem-mcp-live",
        key_id="issuer.showcase.filesystem-mcp-live/key/1",
    )
    (WORKDIR / "trust_bundle.json").write_text(json.dumps(dict(identity.trust_bundle()), indent=2))

    results = []

    # Sentinel setup for the "refuse write" case: the target path the write
    # would create if (and only if) the child actually ran.
    write_sentinel = ALLOWED_ROOT / "should_not_be_created.txt"
    if write_sentinel.exists():
        write_sentinel.unlink()

    outside_target = OUTSIDE_ROOT / "outside_secret.txt"
    OUTSIDE_ROOT.mkdir(parents=True, exist_ok=True)
    if not outside_target.exists():
        outside_target.write_text("pre-existing outside-root content, must remain unread\n")

    # 1. ADMIT: read_text_file inside allowed root.
    results.append(
        await run_one(
            request_ref="req:showcase:1:admit-read-in-root",
            tool_name="read_text_file",
            arguments={"path": str(ALLOWED_ROOT / "sample.txt")},
            seq=1,
            identity=identity,
        )
    )

    # 2. REFUSE: write_file inside allowed root -- mutating tool class refused.
    results.append(
        await run_one(
            request_ref="req:showcase:2:refuse-write",
            tool_name="write_file",
            arguments={
                "path": str(write_sentinel),
                "content": "this content must never land on disk",
            },
            seq=2,
            identity=identity,
        )
    )

    # 3. REFUSE: read_text_file outside allowed root -- path containment.
    results.append(
        await run_one(
            request_ref="req:showcase:3:refuse-read-outside-root",
            tool_name="read_text_file",
            arguments={"path": str(outside_target)},
            seq=3,
            identity=identity,
        )
    )

    # 4. REFUSE (fail-closed): tool name not in the connector's own allowlist.
    results.append(
        await run_one(
            request_ref="req:showcase:4:refuse-unknown-tool",
            tool_name="delete_everything",
            arguments={"path": str(ALLOWED_ROOT)},
            seq=4,
            identity=identity,
        )
    )

    # Sentinel checks -- did the child actually run zero times for the refused calls?
    sentinel_report = {
        "write_sentinel_path": str(write_sentinel),
        "write_sentinel_exists_after_refusal": write_sentinel.exists(),
        "outside_target_path": str(outside_target),
        "outside_target_content_unchanged": outside_target.read_text()
        == "pre-existing outside-root content, must remain unread\n",
    }

    receipt_files = sorted(RECEIPTS_DIR.glob("urn_srs_receipt_*.json"))
    receipt_summaries = []
    for p in receipt_files:
        env = json.loads(p.read_text())
        receipt_summaries.append(
            {
                "file": p.name,
                "receipt_kind": env.get("receipt_kind"),
                "disposition": env.get("disposition"),
                "outcome": env.get("outcome"),
                "reason_code": env.get("reason_code"),
                "profile_id": env.get("profile_id"),
                "profile_version": env.get("profile_version"),
            }
        )

    out = {
        "workdir": str(WORKDIR),
        "results": results,
        "sentinel_report": sentinel_report,
        "receipt_files": [str(p) for p in receipt_files],
        "receipt_summaries": receipt_summaries,
    }
    (WORKDIR / "live_run_output.json").write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps(out, indent=2, default=str))
    print(f"\nWORKDIR={WORKDIR}", file=sys.stderr)


if __name__ == "__main__":
    anyio.run(main)
