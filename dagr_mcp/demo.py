"""Generate a signed admission/outcome pair without a framework dependency."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from .enforcement_harness import HarnessConfig, HarnessSinks, ToolPolicy, wrap_handler
from .sdk_spine import InMemoryEventSink
from .srs_bridge import BridgeConfig, HarnessSRSBridge
from .srs_receipts import RawEnvelopeFileSink, SignedReceiptEmitter, SigningIdentity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Receipt output directory. Defaults to an ephemeral directory.")
    return parser


def run_demo(output: Path | None = None) -> Path:
    directory = output or Path(tempfile.mkdtemp(prefix="dagr-mcp-demo-"))
    sink = RawEnvelopeFileSink(directory)
    identity = SigningIdentity.generate(
        issuer_id="issuer:dagr:demo",
        key_id="issuer.dagr.demo/receipt-signing/ephemeral",
    )
    sink.write_trust_bundle(identity.trust_bundle())
    bridge = HarnessSRSBridge(
        emitter=SignedReceiptEmitter(identity=identity, sink=sink),
        config=BridgeConfig(
            runtime_instance_id="runtime:dagr:demo",
            boundary_id="boundary:dagr:direct-harness",
            policy_pack_id="policy:dagr:demo",
            policy_pack_version="v0.1",
        ),
    )

    def lookup(tool_name: str, arguments: object, context: object = None) -> dict[str, object]:
        return {"record_ref": "record:demo:1", "found": True}

    governed = wrap_handler(
        lookup,
        HarnessConfig(
            harness_version="v0.1",
            module_id="dagr-mcp-demo",
            module_version="v0.1",
            profile_ref="srs.mcp.sdk_enforcement.v0.1",
            policy_ref="policy:dagr:demo@v0.1",
        ),
        HarnessSinks(event=InMemoryEventSink()),
        policies=[ToolPolicy(tool_name="records.lookup", tool_class="read", decision="allow")],
        srs_bridge=bridge,
    )
    result = governed(
        "records.lookup",
        {"record_ref": "record:demo:1"},
        {"request_ref": "call:dagr:demo:1", "actor_ref": "actor:dagr:demo"},
    )
    if not result.ok:
        raise RuntimeError(f"governed demo failed: {result.failure_reason}")
    return directory


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    directory = run_demo(args.output)
    receipt_paths = sorted(path for path in directory.glob("*.json") if path.name != "issuer-keys.json")
    print(json.dumps({
        "output_directory": str(directory),
        "trust_bundle": str(directory / "issuer-keys.json"),
        "receipts": [str(path) for path in receipt_paths],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
