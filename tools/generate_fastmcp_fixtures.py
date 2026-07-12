#!/usr/bin/env python3
"""Generate reproducible receipts from the real FastMCP middleware demo path."""

from __future__ import annotations

import argparse
import asyncio
import copy
import importlib.metadata
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from dagr_mcp.srs_receipts import (
    RawEnvelopeFileSink,
    SignedReceiptEmitter,
    SigningIdentity,
    sha256_digest,
)

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / "tests/golden/fastmcp_demo"
PATCH_PATH = ROOT / "arcs-verify-implementation-fixtures.patch"
FAST_MCP_VERSION = "3.4.4"
ARCS_BASE_COMMIT = "aafbdf4f8467d2b66233d4aa7c786ec2681212ce"
ARCS_IMPLEMENTATION_DIR = Path(
    "packs/srs.mcp.sdk_enforcement/v0.1/implementation/"
    "dagr-mcp-fastmcp-demo"
)
PROFILE = "srs.mcp.sdk_enforcement.v0.1"
EXPECTED_FILES = (
    "admission-admitted.json",
    "outcome-result-returned.json",
    "issuer-keys.json",
    "expectations.json",
)

# Public test seed only. It has no production validity and must never be reused
# by the default demo or any deployed signing identity.
FIXTURE_ONLY_PRIVATE_SEED = bytes.fromhex(
    "9b9e53f89bc13ef8378184d7a076fc07"
    "e9e70b7d41d3c398a1345a317c926b72"
)
FIXTURE_ISSUER_ID = "issuer:dagr:fastmcp-fixture"
FIXTURE_KEY_ID = "issuer.dagr.fastmcp-fixture/receipt-signing/v1"
FIXTURE_RUNTIME_ID = "runtime:dagr:fastmcp-fixture"
FIXTURE_LOGICAL_CALL_ID = "call:dagr:fastmcp-fixture:1"
FIXTURE_SUBJECT_REF = "tool-call:call:dagr:fastmcp-fixture:1"
FIXTURE_RECEIPT_IDS = {
    "admission": "urn:srs:receipt:admission:dagr-fastmcp-fixture-1",
    "outcome": "urn:srs:receipt:outcome:dagr-fastmcp-fixture-1",
}
FIXTURE_TIMES = (
    "2026-07-12T12:00:00Z",
    "2026-07-12T12:00:01Z",
)


@dataclass(frozen=True, slots=True)
class GenerationResult:
    projection: Mapping[str, Any]
    result_digest: str


class _FixedClock:
    def __init__(self) -> None:
        self._values = iter(FIXTURE_TIMES)

    def __call__(self) -> str:
        try:
            return next(self._values)
        except StopIteration as exc:
            raise RuntimeError("fixture clock exhausted") from exc


def _require_fastmcp_floor() -> None:
    actual = importlib.metadata.version("fastmcp")
    if actual != FAST_MCP_VERSION:
        raise RuntimeError(
            f"fixture generation requires fastmcp=={FAST_MCP_VERSION}; found {actual}"
        )


def _fixture_identity() -> SigningIdentity:
    return SigningIdentity(
        issuer_id=FIXTURE_ISSUER_ID,
        key_id=FIXTURE_KEY_ID,
        private_key=Ed25519PrivateKey.from_private_bytes(
            FIXTURE_ONLY_PRIVATE_SEED
        ),
    )


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _expectations() -> dict[str, Any]:
    verdicts: dict[str, bool | str] = {
        "schema_digest": True,
        "envelope": True,
        "profile": True,
        "raw_content_exclusion": True,
        "signature_valid": True,
        "issuer_key_resolved": True,
        "issuer_key_trusted": True,
        "attestation_limits_present": True,
        "chain_status": "not_applicable",
    }
    return {
        "profile": PROFILE,
        "keyring": "issuer-keys.json",
        "receipts": [
            {
                "path": "admission-admitted.json",
                "verdicts": copy.deepcopy(verdicts),
                "expected_failure_codes": [],
            },
            {
                "path": "outcome-result-returned.json",
                "verdicts": copy.deepcopy(verdicts),
                "expected_failure_codes": [],
            },
        ],
    }


async def _generate_live(output: Path) -> GenerationResult:
    _require_fastmcp_floor()

    from fastmcp import FastMCP
    from fastmcp.client import Client

    from dagr_mcp.fastmcp_binding import (
        DAGRMiddleware,
        DAGRMiddlewareConfig,
    )

    output.mkdir(parents=True, exist_ok=True)
    observed: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="dagr-fastmcp-fixture-") as raw:
        staging = Path(raw)
        identity = _fixture_identity()
        sink = RawEnvelopeFileSink(staging)
        sink.write_trust_bundle(identity.trust_bundle())
        emitter = SignedReceiptEmitter(
            identity=identity,
            sink=sink,
            receipt_id_factory=lambda kind: FIXTURE_RECEIPT_IDS[kind],
            issued_at_factory=_FixedClock(),
        )
        server = FastMCP("dagr-mcp-fastmcp-fixture")
        server.add_middleware(
            DAGRMiddleware(
                emitter=emitter,
                config=DAGRMiddlewareConfig(
                    runtime_instance_id=FIXTURE_RUNTIME_ID,
                    boundary_id="boundary:dagr:fastmcp",
                    policy_pack_id="policy:dagr:demo",
                    policy_pack_version="v0.1",
                    tool_classes={"records_lookup": "read"},
                    logical_call_id_override=FIXTURE_LOGICAL_CALL_ID,
                    subject_ref_override=FIXTURE_SUBJECT_REF,
                    result_projection_observer=lambda projection: observed.append(
                        copy.deepcopy(dict(projection))
                    ),
                ),
            )
        )

        @server.tool
        async def records_lookup(record_ref: str) -> dict[str, object]:
            return {"record_ref": record_ref, "found": True}

        async with Client(server) as client:
            result = await client.call_tool(
                "records_lookup",
                {"record_ref": "record:demo:1"},
            )

        if result.data != {"record_ref": "record:demo:1", "found": True}:
            raise RuntimeError(f"unexpected fixture demo result: {result.data!r}")
        if len(observed) != 1:
            raise RuntimeError(
                f"expected one middleware projection; found {len(observed)}"
            )

        receipt_paths = sorted(staging.glob("urn_srs_receipt_*.json"))
        if len(receipt_paths) != 2:
            raise RuntimeError(
                f"expected two emitted receipts; found {len(receipt_paths)}"
            )
        receipts = {
            payload["receipt_kind"]: (path, payload)
            for path in receipt_paths
            for payload in [json.loads(path.read_text(encoding="utf-8"))]
        }
        if set(receipts) != {"admission", "outcome"}:
            raise RuntimeError(f"unexpected receipt kinds: {sorted(receipts)}")

        projection = observed[0]
        result_digest = sha256_digest(projection)
        outcome = receipts["outcome"][1]
        if outcome.get("result_digest") != result_digest:
            raise RuntimeError(
                "middleware-observed projection digest does not match outcome receipt"
            )

        shutil.copyfile(
            receipts["admission"][0],
            output / "admission-admitted.json",
        )
        shutil.copyfile(
            receipts["outcome"][0],
            output / "outcome-result-returned.json",
        )
        shutil.copyfile(
            staging / "issuer-keys.json",
            output / "issuer-keys.json",
        )
        _write_json(output / "expectations.json", _expectations())

    return GenerationResult(
        projection=copy.deepcopy(projection),
        result_digest=result_digest,
    )


def generate_fixture_set(output: Path) -> GenerationResult:
    return asyncio.run(_generate_live(output))


def _file_bytes(directory: Path) -> dict[str, bytes]:
    names = {path.name for path in directory.iterdir() if path.is_file()}
    expected = set(EXPECTED_FILES)
    if names != expected:
        raise RuntimeError(
            f"fixture file set mismatch: expected {sorted(expected)}, "
            f"found {sorted(names)}"
        )
    return {name: (directory / name).read_bytes() for name in EXPECTED_FILES}


def check_committed_fixtures() -> None:
    with tempfile.TemporaryDirectory(prefix="dagr-fastmcp-fixture-check-") as raw:
        generated = Path(raw)
        generate_fixture_set(generated)
        actual = _file_bytes(generated)
    committed = _file_bytes(GOLDEN_DIR)
    mismatches = [name for name in EXPECTED_FILES if actual[name] != committed[name]]
    if mismatches:
        raise RuntimeError(
            "committed FastMCP fixtures differ from fresh generation: "
            + ", ".join(mismatches)
        )


def regenerate_arcs_patch(
    *,
    arcs_repo: Path,
    fixture_directory: Path,
    patch_path: Path,
) -> None:
    arcs_repo = arcs_repo.resolve()
    subprocess.run(
        ["git", "-C", str(arcs_repo), "cat-file", "-e", f"{ARCS_BASE_COMMIT}^{{commit}}"],
        check=True,
    )
    with tempfile.TemporaryDirectory(prefix="arcs-fastmcp-patch-") as raw:
        worktree = Path(raw) / "arcs"
        subprocess.run(
            [
                "git",
                "-C",
                str(arcs_repo),
                "worktree",
                "add",
                "--detach",
                str(worktree),
                ARCS_BASE_COMMIT,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        try:
            target = worktree / ARCS_IMPLEMENTATION_DIR
            target.mkdir(parents=True, exist_ok=True)
            for name in EXPECTED_FILES:
                shutil.copyfile(fixture_directory / name, target / name)
            diff = subprocess.run(
                [
                    "git",
                    "-C",
                    str(worktree),
                    "diff",
                    "--no-ext-diff",
                    "--binary",
                    "--",
                    ARCS_IMPLEMENTATION_DIR.as_posix(),
                ],
                check=True,
                stdout=subprocess.PIPE,
            ).stdout
        finally:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(arcs_repo),
                    "worktree",
                    "remove",
                    "--force",
                    str(worktree),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
            )
    if not diff:
        raise RuntimeError("ARCS fixture patch is unexpectedly empty")
    patch_path.write_bytes(diff)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=GOLDEN_DIR)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--arcs-repo", type=Path)
    parser.add_argument("--patch-output", type=Path, default=PATCH_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.check:
        check_committed_fixtures()
        print(
            f"PASS: committed FastMCP fixtures match fresh {FAST_MCP_VERSION} generation"
        )
        return 0

    result = generate_fixture_set(args.output)
    if args.arcs_repo is None:
        raise SystemExit("--arcs-repo is required when regenerating canonical fixtures")
    regenerate_arcs_patch(
        arcs_repo=args.arcs_repo,
        fixture_directory=args.output,
        patch_path=args.patch_output,
    )
    print(
        json.dumps(
            {
                "fastmcp_version": FAST_MCP_VERSION,
                "fixture_directory": str(args.output),
                "result_digest": result.result_digest,
                "patch": str(args.patch_output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
