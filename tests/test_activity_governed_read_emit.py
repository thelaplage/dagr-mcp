"""Issuer-side tests for the ``srs.activity.governed_read.v0.1`` emit path.

ACT3 substrate lane 2/3: dagr-mcp is the ISSUER. These tests assert that an
emitted admitted receipt and an emitted refused receipt STRUCTURALLY match the
frozen arcs-srs #34 schema and are field-by-field identical to the golden
vectors (excluding the signature block). They import NO arcs-verify code and
copy NO verifier adjudication logic — independent verification is lane 3's job.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from dagr_mcp.srs_receipts import (
    ACTIVITY_GOVERNED_READ_PROFILE_ID,
    ACTIVITY_GOVERNED_READ_PROFILE_VERSION,
    RawEnvelopeFileSink,
    ReceiptContentError,
    SignedReceiptEmitter,
    SigningIdentity,
)

_VENDOR = Path(__file__).parent / "vendor" / "arcs_srs_activity_governed_read"


def _load(name: str) -> dict:
    return json.loads((_VENDOR / name).read_text())


SCHEMA = _load("schema.json")
GOLDEN_ADMITTED = _load("golden-admitted.json")
GOLDEN_REFUSED = _load("golden-refused.json")

# The golden vectors are unsigned field fixtures; the issuer additionally stamps
# a ``receipt_signature`` block. The schema's ``additionalProperties: true``
# admits it, and we compare shape "not signature bytes" — so we drop only that
# one key before the field-by-field equality.
_SIGNATURE_KEY = "receipt_signature"


def _emitter(tmp_path: Path) -> SignedReceiptEmitter:
    # issuer_id matches the golden vectors so a full field-by-field equality is
    # possible; the emitter sources issuer_id from the signing identity.
    identity = SigningIdentity.generate(
        issuer_id="issuer.test/governed-read/2026-01",
        key_id="issuer.test/governed-read/key/1",
    )
    return SignedReceiptEmitter(identity=identity, sink=RawEnvelopeFileSink(tmp_path))


def _emit_matching_golden(tmp_path: Path, golden: dict) -> dict:
    """Emit a receipt fed the exact inputs of ``golden`` and return the written
    receipt as parsed from the sink."""
    emitter = _emitter(tmp_path)
    receipt_id = emitter.emit_activity_governed_read(
        runtime_instance_id=golden["runtime_instance_id"],
        boundary_id=golden["boundary_id"],
        acting_principal_ref=golden["acting_principal_ref"],
        read_request_ref=golden["read_request_ref"],
        basis_version_ref=golden["basis_version_ref"],
        basis_snapshot_digest=golden["basis_snapshot_digest"],
        read_disposition=golden["read_disposition"],
        visibility=golden["visibility"],
        admitted_result_ref=golden.get("admitted_result_ref"),
        refusal_class=golden.get("refusal_class"),
        session_ref=golden.get("session_ref"),
        produced_receipt_refs=golden["produced_receipt_refs"],
        protocol_binding=golden["protocol_binding"],
        issued_at=golden["issued_at"],
        receipt_id=golden["receipt_id"],
        extensions=golden["extensions"],
    )
    written = json.loads((tmp_path / f"{receipt_id}.json").read_text())
    return written


# --- schema (structural) validity of the golden vendors themselves -----------

def test_vendored_golden_vectors_validate_against_frozen_schema():
    jsonschema.validate(GOLDEN_ADMITTED, SCHEMA)
    jsonschema.validate(GOLDEN_REFUSED, SCHEMA)


# --- admitted -----------------------------------------------------------------

def test_emitted_admitted_matches_golden_shape_field_by_field(tmp_path):
    written = _emit_matching_golden(tmp_path, GOLDEN_ADMITTED)
    assert _SIGNATURE_KEY in written  # issuer signed it
    body = {k: v for k, v in written.items() if k != _SIGNATURE_KEY}
    # Identical field set (shape) ...
    assert set(body.keys()) == set(GOLDEN_ADMITTED.keys())
    # ... and identical values on every field (not signature bytes).
    assert body == GOLDEN_ADMITTED


def test_emitted_admitted_is_structurally_schema_valid(tmp_path):
    written = _emit_matching_golden(tmp_path, GOLDEN_ADMITTED)
    # The signed receipt (signature block included) validates; the schema admits
    # additional properties.
    jsonschema.validate(written, SCHEMA)
    for field in SCHEMA["required"]:
        assert field in written, f"required field missing: {field}"


def test_admitted_carries_result_ref_and_no_refusal(tmp_path):
    written = _emit_matching_golden(tmp_path, GOLDEN_ADMITTED)
    assert written["read_disposition"] == "admitted"
    assert written["admitted_result_ref"] == GOLDEN_ADMITTED["admitted_result_ref"]
    assert "refusal_class" not in written
    # subject binding: subject_ref == basis_version_ref
    assert written["subject_ref"] == written["basis_version_ref"]
    # profile identity is the activity profile, per-receipt.
    assert written["profile_id"] == ACTIVITY_GOVERNED_READ_PROFILE_ID
    assert written["profile_version"] == ACTIVITY_GOVERNED_READ_PROFILE_VERSION
    assert written["receipt_type"] == "provenance"
    assert written["identity_posture"] == "declared"


# --- refused (a refused read still emits a receipt) ---------------------------

def test_emitted_refused_matches_golden_shape_field_by_field(tmp_path):
    written = _emit_matching_golden(tmp_path, GOLDEN_REFUSED)
    body = {k: v for k, v in written.items() if k != _SIGNATURE_KEY}
    assert set(body.keys()) == set(GOLDEN_REFUSED.keys())
    assert body == GOLDEN_REFUSED


def test_emitted_refused_is_structurally_schema_valid(tmp_path):
    written = _emit_matching_golden(tmp_path, GOLDEN_REFUSED)
    jsonschema.validate(written, SCHEMA)
    for field in SCHEMA["required"]:
        assert field in written, f"required field missing: {field}"


def test_refused_carries_refusal_class_and_no_result_ref(tmp_path):
    written = _emit_matching_golden(tmp_path, GOLDEN_REFUSED)
    assert written["read_disposition"] == "refused"
    assert written["refusal_class"] == GOLDEN_REFUSED["refusal_class"]
    assert "admitted_result_ref" not in written
    assert written["produced_receipt_refs"] == []  # absence discipline, may be empty


# --- issuer-side well-formedness guards (NOT verifier adjudication) -----------

def test_admitted_without_result_ref_is_refused_at_build(tmp_path):
    with pytest.raises(ReceiptContentError):
        _emitter(tmp_path).build_activity_governed_read(
            runtime_instance_id="r",
            boundary_id="b",
            acting_principal_ref="urn:dagr.principal:declared:x",
            read_request_ref="sha256:" + "1" * 64,
            basis_version_ref="urn:dagr.basis:edition:c@1",
            basis_snapshot_digest="sha256:" + "2" * 64,
            read_disposition="admitted",
            visibility="PRIVATE_ORG",
            # admitted_result_ref intentionally omitted
        )


def test_refused_with_result_ref_is_refused_at_build(tmp_path):
    with pytest.raises(ReceiptContentError):
        _emitter(tmp_path).build_activity_governed_read(
            runtime_instance_id="r",
            boundary_id="b",
            acting_principal_ref="urn:dagr.principal:declared:x",
            read_request_ref="sha256:" + "1" * 64,
            basis_version_ref="urn:dagr.basis:edition:c@1",
            basis_snapshot_digest="sha256:" + "2" * 64,
            read_disposition="refused",
            visibility="PRIVATE_ORG",
            refusal_class="POLICY_REFUSED",
            admitted_result_ref="sha256:" + "3" * 64,  # illegal on a refusal
        )


def test_unknown_refusal_class_is_rejected(tmp_path):
    with pytest.raises(ReceiptContentError):
        _emitter(tmp_path).build_activity_governed_read(
            runtime_instance_id="r",
            boundary_id="b",
            acting_principal_ref="urn:dagr.principal:declared:x",
            read_request_ref="sha256:" + "1" * 64,
            basis_version_ref="urn:dagr.basis:edition:c@1",
            basis_snapshot_digest="sha256:" + "2" * 64,
            read_disposition="refused",
            visibility="PRIVATE_ORG",
            refusal_class="NOT_A_REAL_CLASS",
        )


def test_visibility_outside_closed_set_is_rejected(tmp_path):
    with pytest.raises(ReceiptContentError):
        _emitter(tmp_path).build_activity_governed_read(
            runtime_instance_id="r",
            boundary_id="b",
            acting_principal_ref="urn:dagr.principal:declared:x",
            read_request_ref="sha256:" + "1" * 64,
            basis_version_ref="urn:dagr.basis:edition:c@1",
            basis_snapshot_digest="sha256:" + "2" * 64,
            read_disposition="admitted",
            visibility="WORLD_READABLE",  # not a C8 member
            admitted_result_ref="sha256:" + "3" * 64,
        )


def test_no_aggregate_field_is_emitted(tmp_path):
    # C6 no-aggregate: none of the schema-forbidden aggregate keys appear.
    written = _emit_matching_golden(tmp_path, GOLDEN_ADMITTED)
    forbidden = {
        "aggregate_verdict", "aggregate_activity_verdict", "trust_score",
        "reputation", "reputation_score", "activity_score", "reliance_score",
        "standing_score", "read_count_verdict",
    }
    assert forbidden.isdisjoint(written.keys())
