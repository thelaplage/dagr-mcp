from __future__ import annotations

import json
from pathlib import Path

from dagr_mcp_core.srs_receipts import (
    PROFILE_ID,
    PROFILE_VERSION,
    RECEIPT_VERSION,
    ReceiptContext,
    RawEnvelopeFileSink,
    SignedReceiptEmitter,
    SigningIdentity,
)


GATE_D_ARCS_VERIFY_COMMIT = "ee98a1f6cc88687ff101633ef857e214193cfce3"
GATE_D_REPORT_CONTRACT_ID = "srs.dagr_verification_report.v0.2"
GATE_D_PROFILE = "srs.mcp.sdk_enforcement.v0.1"
GATE_D_ENVELOPE_SCHEMA = "srs-envelope-v0.2.1.schema.json"


def _load_single_receipt(directory: Path, receipt_kind: str) -> dict:
    matches = []
    for path in directory.glob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("receipt_kind") == receipt_kind:
            matches.append(value)
    assert len(matches) == 1
    return matches[0]


def test_historical_emitter_freshly_produces_gate_d_profile_receipts(tmp_path: Path) -> None:
    """Producer-side compatibility proof for the first D2 A-F specimen.

    This test intentionally does NOT claim independent ARCS verification. It
    proves that current dagr-mcp can freshly generate the exact historical SRS
    receipt/profile family Gate D is ratified to execute. The actual pinned
    ARCS subprocess remains an independent Countervail Gate-D observation.
    """

    receipt_dir = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(receipt_dir)
    identity = SigningIdentity.generate(
        issuer_id="specimen:dagr-mcp:issuer:local",
        key_id="specimen:dagr-mcp:key:local",
    )
    emitter = SignedReceiptEmitter(
        identity=identity,
        sink=sink,
        receipt_id_factory=lambda kind: f"urn:srs:receipt:{kind}:d2-specimen-001",
        issued_at_factory=lambda: "2026-09-01T00:00:00Z",
    )
    context = ReceiptContext(
        runtime_instance_id="runtime:d2-specimen:001",
        boundary_id="boundary:d2-specimen:mcp:001",
        policy_pack_id="countervail.d2.specimen",
        policy_pack_version="v0.1",
        subject_ref="subject:d2-specimen:001",
        subject_ref_origin="binding_minted",
        logical_call_id="logical-call:d2-specimen:001",
        binding_version="direct-harness.v0.1",
    )

    admission_ref = emitter.emit_admission(
        context=context,
        requested_tool_name="countervail.specimen.local_ledger_append",
        argument_digest="sha256:" + "a" * 64,
        disposition="admitted",
        reason_code="specimen_admitted",
    )
    outcome_ref = emitter.emit_outcome(
        context=context,
        admission_receipt_ref=admission_ref,
        outcome="result_returned",
        result_digest="sha256:" + "b" * 64,
    )

    admission = _load_single_receipt(receipt_dir, "admission")
    outcome = _load_single_receipt(receipt_dir, "outcome")
    trust_bundle = identity.trust_bundle()

    assert PROFILE_ID == "srs.mcp.sdk_enforcement"
    assert PROFILE_VERSION == "v0.1"
    assert RECEIPT_VERSION == "srs.core.v5.1"
    assert GATE_D_PROFILE == f"{PROFILE_ID}.{PROFILE_VERSION}"

    for receipt in (admission, outcome):
        assert receipt["receipt_version"] == RECEIPT_VERSION
        assert receipt["profile_id"] == PROFILE_ID
        assert receipt["profile_version"] == PROFILE_VERSION
        assert receipt["receipt_type"] == "sdk_enforcement"
        assert receipt["boundary_type"] == "mcp_tool_call"
        assert receipt["protocol_binding"] == "mcp"
        assert receipt["subject_ref_origin"] == "binding_minted"
        assert receipt["receipt_signature"]["algorithm"] == "Ed25519"
        assert receipt["receipt_signature"]["canonicalization"] == "RFC8785-JCS"
        assert receipt["receipt_signature"]["key_id"] == "specimen:dagr-mcp:key:local"
        assert receipt["receipt_signature"]["signature"]
        assert "private_key" not in json.dumps(receipt).lower()

    assert admission_ref == admission["receipt_id"]
    assert outcome_ref == outcome["receipt_id"]
    assert outcome["admission_receipt_ref"] == admission_ref
    assert outcome["outcome"] == "result_returned"
    assert outcome["result_digest"] == "sha256:" + "b" * 64

    assert trust_bundle["trust_bundle_version"] == "srs.trust_bundle.v0.1"
    assert len(trust_bundle["issuers"]) == 1
    issuer = trust_bundle["issuers"][0]
    assert issuer["issuer_id"] == "specimen:dagr-mcp:issuer:local"
    assert issuer["key_id"] == "specimen:dagr-mcp:key:local"
    assert issuer["algorithm"] == "Ed25519"
    assert issuer["trusted"] is True
    assert issuer["public_key"]
    assert "private_key" not in json.dumps(trust_bundle).lower()


def test_gate_d_pin_is_recorded_as_external_verifier_requirement() -> None:
    # These constants are witnesses for the cross-repo acceptance harness only.
    # They do not repin dagr-mcp or make this producer its own verifier.
    assert GATE_D_ARCS_VERIFY_COMMIT == "ee98a1f6cc88687ff101633ef857e214193cfce3"
    assert GATE_D_REPORT_CONTRACT_ID == "srs.dagr_verification_report.v0.2"
    assert GATE_D_PROFILE == "srs.mcp.sdk_enforcement.v0.1"
    assert GATE_D_ENVELOPE_SCHEMA == "srs-envelope-v0.2.1.schema.json"
