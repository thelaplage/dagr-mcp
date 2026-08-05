"""Independent verification of live_run.py's receipts using the REAL,
separately-installed arcs-verify package -- this file imports no dagr_mcp
producer module. Intended to be run as its own fresh interpreter process
(a plain `python verify_receipts.py`, not imported into the producer's
process), matching the merged connector's own
test_stdio_receipts_verify_under_the_independent_arcs_verifier /
test_importing_arcs_verify_does_not_import_dagr_mcp_producer_modules pattern.

This file is self-contained and portable: it hardcodes no machine-specific
paths. Point it at the workdir produced by live_run.py via --workdir or the
DAGR_MCP_SHOWCASE_WORKDIR environment variable.

Run (after live_run.py has populated the same workdir):

    python verify_receipts.py --workdir "$DAGR_MCP_SHOWCASE_WORKDIR"
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path

import arcs_verify
from arcs_verify.verifier import PROFILE_IDENTITIES, verify_receipt as arcs_verify_receipt

STDIO_PROFILE = "srs.mcp.sdk_enforcement.v0.1"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workdir",
        default=os.environ.get("DAGR_MCP_SHOWCASE_WORKDIR", ""),
        required=not os.environ.get("DAGR_MCP_SHOWCASE_WORKDIR"),
        help="Workdir populated by live_run.py (contains receipts/ and "
        "trust_bundle.json). Defaults to DAGR_MCP_SHOWCASE_WORKDIR.",
    )
    return parser.parse_args()


def producer_isolation_check() -> dict:
    producer_packages = (
        "dagr_mcp",
        "dagr_mcp_service",
        "dagr_mcp_lifecycle",
        "dagr_mcp_sdk_binding",
        "dagr_mcp_continuation",
    )
    leaked = sorted(
        name
        for name in sys.modules
        if any(name == p or name.startswith(p + ".") for p in producer_packages)
    )
    return {"producer_modules_in_this_process": leaked, "isolated": leaked == []}


def main() -> None:
    args = _parse_args()
    workdir = Path(args.workdir).resolve()
    receipts_dir = workdir / "receipts"
    trust_bundle_path = workdir / "trust_bundle.json"
    arcs_schema_path = Path(arcs_verify.__file__).resolve().parent / "data" / "srs-envelope-v0.2.0.schema.json"

    bundle = json.loads(trust_bundle_path.read_text())
    receipt_paths = sorted(receipts_dir.glob("urn_srs_receipt_*.json"))

    pinned_profile_id, pinned_profile_version = PROFILE_IDENTITIES[STDIO_PROFILE]

    genuine_results = []
    mutation_results = []
    genuine_pass_count = 0
    mutation_caught_count = 0

    for path in receipt_paths:
        receipt = json.loads(path.read_text())

        report = arcs_verify_receipt(
            dict(receipt),
            bundle,
            schema_path=arcs_schema_path,
            selected_profile=STDIO_PROFILE,
        )
        passed = bool(report.passed)
        genuine_pass_count += 1 if passed else 0
        genuine_results.append(
            {
                "file": path.name,
                "receipt_kind": receipt.get("receipt_kind"),
                "profile_id_matches_pinned": receipt.get("profile_id") == pinned_profile_id,
                "profile_version_matches_pinned": receipt.get("profile_version")
                == pinned_profile_version,
                "passed": passed,
                "schema_digest": bool(report.schema_digest),
                "envelope": bool(report.envelope),
                "profile": bool(report.profile),
                "raw_content_exclusion": bool(report.raw_content_exclusion),
                "signature_valid": bool(report.signature_valid),
                "issuer_key_resolved": bool(report.issuer_key_resolved),
                "issuer_key_trusted": bool(report.issuer_key_trusted),
                "attestation_limits_present": bool(report.attestation_limits_present),
                "failure_codes": list(report.failure_codes) if not passed else [],
            }
        )

        # Mutate exactly one field and confirm the tamper is caught.
        tampered = copy.deepcopy(receipt)
        if "logical_call_id" in tampered:
            tampered["logical_call_id"] = "urn:tampered:not-the-real-call"
        else:
            # Fallback mutation for any receipt shape lacking that field.
            tampered["reason_code"] = "TAMPERED-FIELD"

        tampered_report = arcs_verify_receipt(
            tampered,
            bundle,
            schema_path=arcs_schema_path,
            selected_profile=STDIO_PROFILE,
        )
        caught_as_signature_invalid = (
            not tampered_report.passed
            and not tampered_report.signature_valid
            and "signature_invalid" in tampered_report.failure_codes
        )
        mutation_caught_count += 1 if caught_as_signature_invalid else 0
        mutation_results.append(
            {
                "file": path.name,
                "tampered_field": "logical_call_id" if "logical_call_id" in receipt else "reason_code",
                "tampered_passed": bool(tampered_report.passed),
                "tampered_signature_valid": bool(tampered_report.signature_valid),
                "tampered_failure_codes": list(tampered_report.failure_codes),
                "caught_as_signature_invalid": caught_as_signature_invalid,
            }
        )

    out = {
        "workdir": str(workdir),
        "arcs_verify_module_file": arcs_verify.__file__,
        "pinned_profile_id": pinned_profile_id,
        "pinned_profile_version": pinned_profile_version,
        "receipt_count": len(receipt_paths),
        "genuine_pass_count": genuine_pass_count,
        "genuine_total": len(receipt_paths),
        "mutation_caught_count": mutation_caught_count,
        "mutation_total": len(receipt_paths),
        "genuine_results": genuine_results,
        "mutation_results": mutation_results,
        "producer_isolation": producer_isolation_check(),
    }
    print(json.dumps(out, indent=2, default=str))
    (workdir / "verify_output.json").write_text(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
