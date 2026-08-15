from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from dagr_mcp.srs_receipts import (
    BASE_LIMIT,
    PROFILE_ID,
    PROFILE_VERSION,
    RECEIPT_VERSION,
    RawEnvelopeFileSink,
    ReceiptContext,
    SignedReceiptEmitter,
    SigningIdentity,
)


def _identity() -> SigningIdentity:
    return SigningIdentity.generate(
        issuer_id="issuer:test:graph-identity",
        key_id="issuer.test.graph-identity/key/1",
    )


def _context(**overrides: object) -> ReceiptContext:
    values: dict[str, object] = {
        # Topology-looking values are intentional hostile inputs; the receipt
        # must not upgrade them into graph identity.
        "runtime_instance_id": "runtime:cluster-a/node-7",
        "boundary_id": "boundary:unix:/var/run/docker.sock",
        "policy_pack_id": "policy:test:graph-identity",
        "policy_pack_version": "2026.08.15",
        "subject_ref": "subject:test:graph-identity",
        "logical_call_id": "call:test:graph-identity",
    }
    values.update(overrides)
    return ReceiptContext(**values)  # type: ignore[arg-type]


def _emit_admission(tmp_path: Path) -> dict[str, object]:
    identity = _identity()
    emitter = SignedReceiptEmitter(identity=identity, sink=RawEnvelopeFileSink(tmp_path))
    receipt_id = emitter.emit_admission(
        context=_context(),
        requested_tool_name="records.lookup",
        argument_digest="sha256:" + "a" * 64,
        disposition="admitted",
    )
    receipt = next(
        receipt
        for receipt in (
            json.loads(path.read_text(encoding="utf-8"))
            for path in tmp_path.glob("urn_srs_receipt_*.json")
        )
        if receipt["receipt_id"] == receipt_id
    )
    return receipt


def test_receipt_context_has_no_graph_identity_fields() -> None:
    field_names = {field.name for field in dataclasses.fields(ReceiptContext)}
    assert "graph_ref" not in field_names
    assert "graph_ref_origin" not in field_names
    assert "named_graph_ref" not in field_names


def test_governed_emission_does_not_reconstruct_graph_identity_from_topology(tmp_path: Path) -> None:
    receipt = _emit_admission(tmp_path)

    assert "graph_ref" not in receipt
    assert "graph_ref_origin" not in receipt
    assert receipt["subject_ref"] == "subject:test:graph-identity"
    assert receipt["extensions"] == {"mcp": {"binding_version": "direct-harness.v0.1"}}
    assert receipt["attestation_limits"] == [BASE_LIMIT]
    assert receipt["receipt_version"] == RECEIPT_VERSION
    assert receipt["profile_id"] == PROFILE_ID
    assert receipt["profile_version"] == PROFILE_VERSION


def test_manual_extension_injection_is_not_a_governed_graph_resolution_rule() -> None:
    identity = _identity()
    signed = identity.sign_envelope(
        {
            "receipt_version": RECEIPT_VERSION,
            "profile_id": PROFILE_ID,
            "profile_version": PROFILE_VERSION,
            "receipt_id": "urn:srs:receipt:admission:graph-draft",
            "receipt_type": "sdk_enforcement",
            "receipt_kind": "admission",
            "boundary_type": "mcp_tool_call",
            "protocol_binding": "mcp",
            "subject_ref": "subject:test:graph-identity",
            "issuer_id": "issuer:test:graph-identity",
            "runtime_instance_id": "runtime:test:graph-identity",
            "boundary_id": "boundary:test:graph-identity",
            "logical_call_id": "call:test:graph-identity",
            "issued_at": "2026-08-15T00:00:00Z",
            "artifact_classes_covered": ["tool_call_admission"],
            "artifact_classes_excluded": ["raw_prompt"],
            "attestation_limits": [BASE_LIMIT],
            "retention_class_applied": "hash_only",
            "extensions": {
                "mcp": {
                    "binding_version": "direct-harness.v0.1",
                    "graph_ref": "graph:test:alpha",
                }
            },
            "requested_tool_name": "records.lookup",
            "tool_resolution_status": "not_observed",
            "argument_digest": "sha256:" + "b" * 64,
            "policy_pack_id": "policy:test:graph-identity",
            "policy_pack_version": "2026.08.15",
            "disposition": "admitted",
            "receipt_signature": {
                "algorithm": "Ed25519",
                "canonicalization": "RFC8785-JCS",
                "key_id": "issuer.test.graph-identity/key/1",
                "signature": "",
            },
        }
    )

    assert signed["extensions"]["mcp"]["graph_ref"] == "graph:test:alpha"
