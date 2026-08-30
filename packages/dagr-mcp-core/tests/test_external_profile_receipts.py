from __future__ import annotations

import json
from pathlib import Path

import pytest

from dagr_mcp_core.external_profile_receipts import (
    ExternalProfileReceiptContract,
    ExternalProfileSignedReceiptEmitter,
)
from dagr_mcp_core.srs_receipts import (
    RawEnvelopeFileSink,
    ReceiptContext,
    SignedReceiptEmitter,
    SigningIdentity,
)


def _contract() -> ExternalProfileReceiptContract:
    return ExternalProfileReceiptContract(
        profile_id="org.counterpedia.srs.mcp_read.v1",
        profile_version="v1",
        emitter_id="dagr-mcp:counterpedia-read",
        extension_namespace="org.counterpedia",
        admission_receipt_type="org.counterpedia.mcp.read.admission",
        outcome_receipt_type="org.counterpedia.mcp.read.outcome",
        envelope_contract_id="srs-envelope-v0-next",
        envelope_contract_version="v0-next",
        envelope_contract_digest="sha256:" + "1" * 64,
        profile_contract_digest="sha256:" + "2" * 64,
    )


def _context() -> ReceiptContext:
    return ReceiptContext(
        runtime_instance_id="runtime:test",
        boundary_id="boundary:test",
        policy_pack_id="policy:test",
        policy_pack_version="1",
        subject_ref="subject:test",
        logical_call_id="call:test",
        binding_version="official-mcp-sdk.python.v0.2",
    )


def _identity() -> SigningIdentity:
    return SigningIdentity.generate(issuer_id="issuer:test", key_id="key:test")


def _load_receipt(directory: Path, receipt_id: str) -> dict:
    expected = directory / (receipt_id.replace(":", "_") + ".json")
    return json.loads(expected.read_text(encoding="utf-8"))


def test_external_profile_emission_is_opt_in_and_does_not_mutate_legacy_shape(tmp_path: Path) -> None:
    legacy_dir = tmp_path / "legacy"
    next_dir = tmp_path / "next"
    identity = _identity()

    legacy = SignedReceiptEmitter(
        identity=identity,
        sink=RawEnvelopeFileSink(legacy_dir),
        receipt_id_factory=lambda kind: f"legacy:{kind}",
        issued_at_factory=lambda: "2026-08-30T00:00:00Z",
    )
    legacy_id = legacy.emit_admission(
        context=_context(),
        requested_tool_name="get_entry",
        argument_digest="sha256:" + "a" * 64,
        disposition="admitted",
    )
    legacy_receipt = _load_receipt(legacy_dir, legacy_id)
    assert legacy_receipt["profile_id"] == "srs.mcp.sdk_enforcement"
    assert legacy_receipt["receipt_type"] == "sdk_enforcement"
    assert "envelope_schema_version" not in legacy_receipt
    assert "emitter_id" not in legacy_receipt
    assert "contract_refs" not in legacy_receipt

    successor = ExternalProfileSignedReceiptEmitter(
        contract=_contract(),
        identity=identity,
        sink=RawEnvelopeFileSink(next_dir),
        receipt_id_factory=lambda kind: f"next:{kind}",
        issued_at_factory=lambda: "2026-08-30T00:00:00Z",
    )
    next_id = successor.emit_admission(
        context=_context(),
        requested_tool_name="get_entry",
        argument_digest="sha256:" + "a" * 64,
        disposition="admitted",
    )
    receipt = _load_receipt(next_dir, next_id)
    assert receipt["envelope_schema_version"] == "srs-envelope-v0-next"
    assert receipt["emitter_id"] == "dagr-mcp:counterpedia-read"
    assert receipt["profile_id"] == "org.counterpedia.srs.mcp_read.v1"
    assert receipt["profile_version"] == "v1"
    assert receipt["receipt_type"] == "org.counterpedia.mcp.read.admission"
    assert receipt["contract_refs"]["envelope_contract"]["digest"] == "sha256:" + "1" * 64
    assert receipt["contract_refs"]["profile_contract"]["digest"] == "sha256:" + "2" * 64
    assert receipt["extensions"] == {
        "org.counterpedia": {
            "mcp_binding": {"binding_version": "official-mcp-sdk.python.v0.2"}
        }
    }
    assert "dagr_binding" not in json.dumps(receipt, sort_keys=True)


def test_admission_and_outcome_use_distinct_application_owned_receipt_types(tmp_path: Path) -> None:
    emitter = ExternalProfileSignedReceiptEmitter(
        contract=_contract(),
        identity=_identity(),
        sink=RawEnvelopeFileSink(tmp_path),
        receipt_id_factory=lambda kind: f"receipt:{kind}",
        issued_at_factory=lambda: "2026-08-30T00:00:00Z",
    )
    admission_id = emitter.emit_admission(
        context=_context(),
        requested_tool_name="get_entry",
        argument_digest="sha256:" + "a" * 64,
        disposition="admitted",
    )
    outcome_id = emitter.emit_outcome(
        context=_context(),
        admission_receipt_ref=admission_id,
        outcome="result_returned",
        result_digest="sha256:" + "b" * 64,
    )
    admission = _load_receipt(tmp_path, admission_id)
    outcome = _load_receipt(tmp_path, outcome_id)
    assert admission["receipt_type"] == "org.counterpedia.mcp.read.admission"
    assert outcome["receipt_type"] == "org.counterpedia.mcp.read.outcome"
    assert outcome["admission_receipt_ref"] == admission_id


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("profile_id", "srs.external.bad.v1"),
        ("extension_namespace", "garp.vendor"),
        ("admission_receipt_type", "sdk_enforcement"),
        ("outcome_receipt_type", "srs.vendor.outcome"),
        ("envelope_contract_digest", "1" * 64),
        ("profile_contract_digest", "sha256:" + "A" * 64),
    ],
)
def test_contract_configuration_fails_closed(field: str, value: str) -> None:
    kwargs = {
        "profile_id": "org.counterpedia.srs.mcp_read.v1",
        "profile_version": "v1",
        "emitter_id": "dagr-mcp:counterpedia-read",
        "extension_namespace": "org.counterpedia",
        "admission_receipt_type": "org.counterpedia.mcp.read.admission",
        "outcome_receipt_type": "org.counterpedia.mcp.read.outcome",
        "envelope_contract_id": "srs-envelope-v0-next",
        "envelope_contract_version": "v0-next",
        "envelope_contract_digest": "sha256:" + "1" * 64,
        "profile_contract_digest": "sha256:" + "2" * 64,
    }
    kwargs[field] = value
    with pytest.raises(ValueError):
        ExternalProfileReceiptContract(**kwargs)
