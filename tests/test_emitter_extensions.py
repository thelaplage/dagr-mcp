from __future__ import annotations

import base64
import copy
import hashlib
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from jsonschema import Draft202012Validator

from dagr_mcp.srs_bridge import BridgeConfig, HarnessSRSBridge
from dagr_mcp.srs_receipts import (
    BASE_LIMIT,
    CANCELLATION_FIELD_NAMES,
    EXCLUDED_CLASSES,
    PROFILE_ID,
    PROFILE_VERSION,
    RECEIPT_VERSION,
    RawEnvelopeFileSink,
    ReceiptContentError,
    ReceiptContext,
    SignedReceiptEmitter,
    SigningIdentity,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "dagr_mcp/vendor/srs/srs-envelope-v0.2.0.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
PROXY_LIMIT = (
    "The receipt attests only to what crossed and returned through the proxy boundary."
)
FIXED_UUID = uuid.UUID("11111111-2222-3333-4444-555555555555")
FIXED_TIME = "2026-07-11T20:00:00Z"


def decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def fixed_identity() -> SigningIdentity:
    return SigningIdentity(
        issuer_id="issuer:test",
        key_id="issuer.test/key/1",
        private_key=Ed25519PrivateKey.from_private_bytes(bytes(range(32))),
    )


def build(tmp_path: Path) -> tuple[SigningIdentity, RawEnvelopeFileSink, SignedReceiptEmitter]:
    identity = fixed_identity()
    sink = RawEnvelopeFileSink(tmp_path)
    return identity, sink, SignedReceiptEmitter(identity=identity, sink=sink)


def context(**overrides: object) -> ReceiptContext:
    values: dict[str, object] = {
        "runtime_instance_id": "runtime:test:1",
        "boundary_id": "boundary:test:1",
        "policy_pack_id": "policy:test",
        "policy_pack_version": "1",
        "subject_ref": "subject:test:1",
        "logical_call_id": "call:test:1",
        "actor_ref": "actor:test:1",
    }
    values.update(overrides)
    return ReceiptContext(**values)  # type: ignore[arg-type]


def load_receipt(tmp_path: Path, receipt_id: str) -> dict[str, object]:
    matches = []
    for path in tmp_path.glob("urn_srs_receipt_*.json"):
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if receipt["receipt_id"] == receipt_id:
            matches.append(receipt)
    assert len(matches) == 1
    return matches[0]


def verify_signature(receipt: dict[str, object], identity: SigningIdentity) -> None:
    preimage = copy.deepcopy(receipt)
    signature = decode(preimage["receipt_signature"].pop("signature"))  # type: ignore[union-attr]
    canonical = rfc8785.dumps(preimage)
    Ed25519PublicKey.from_public_bytes(identity.public_key_bytes()).verify(
        signature, canonical
    )


def test_default_direct_shape_is_unchanged(monkeypatch, tmp_path):
    import dagr_mcp.srs_receipts as receipts_module

    monkeypatch.setattr(receipts_module.uuid, "uuid4", lambda: FIXED_UUID)
    monkeypatch.setattr(receipts_module, "now_utc_iso", lambda: FIXED_TIME)
    identity, _sink, emitter = build(tmp_path)

    receipt_id = emitter.emit_admission(
        context=context(),
        requested_tool_name="records.lookup",
        argument_digest="sha256:" + "a" * 64,
        disposition="admitted",
    )
    actual = load_receipt(tmp_path, receipt_id)

    expected_unsigned = {
        "receipt_version": RECEIPT_VERSION,
        "profile_id": PROFILE_ID,
        "profile_version": PROFILE_VERSION,
        "receipt_id": f"urn:srs:receipt:admission:{FIXED_UUID}",
        "receipt_type": "sdk_enforcement",
        "receipt_kind": "admission",
        "boundary_type": "mcp_tool_call",
        "protocol_binding": "mcp",
        "subject_ref": "subject:test:1",
        "issuer_id": "issuer:test",
        "runtime_instance_id": "runtime:test:1",
        "boundary_id": "boundary:test:1",
        "logical_call_id": "call:test:1",
        "issued_at": FIXED_TIME,
        "artifact_classes_covered": ["tool_call_admission"],
        "artifact_classes_excluded": list(EXCLUDED_CLASSES),
        "attestation_limits": [BASE_LIMIT],
        "retention_class_applied": "hash_only",
        "extensions": {"mcp": {"binding_version": "direct-harness.v0.1"}},
        "actor_ref": "actor:test:1",
        "requested_tool_name": "records.lookup",
        "tool_resolution_status": "not_observed",
        "argument_digest": "sha256:" + "a" * 64,
        "policy_pack_id": "policy:test",
        "policy_pack_version": "1",
        "disposition": "admitted",
    }
    expected = identity.sign_envelope(expected_unsigned)
    assert actual == expected
    assert "parent_receipt_ref" not in actual


def test_bridge_passes_binding_context_and_extension_parameters(tmp_path):
    identity, _sink, emitter = build(tmp_path)
    bridge = HarnessSRSBridge(
        emitter=emitter,
        config=BridgeConfig(
            runtime_instance_id="runtime:test:1",
            boundary_id="boundary:test:1",
            policy_pack_id="policy:test",
            policy_pack_version="1",
            binding_version="fastmcp.middleware.v0.1",
        ),
    )
    harness_context = SimpleNamespace(
        request_ref="call:test:bridge",
        session_ref="subject:test:bridge",
        actor_ref="actor:test:bridge",
        arguments_hash="sha256:" + "b" * 64,
    )
    admission_ref = bridge.emit_admission(
        harness_context=harness_context,
        tool_name="records.lookup",
        disposition="admitted",
        parent_receipt_ref="urn:srs:receipt:parent:1",
        additional_attestation_limits=(PROXY_LIMIT,),
    )
    outcome_ref = bridge.emit_outcome(
        harness_context=harness_context,
        admission_receipt_ref=admission_ref,
        outcome="indeterminate",
        binding_owned_fields={
            "request_cancelled": True,
            "execution_state_unknown": True,
            "delivery_incomplete": True,
        },
        parent_receipt_ref="urn:srs:receipt:parent:1",
        additional_attestation_limits=(PROXY_LIMIT,),
    )
    outcome = load_receipt(tmp_path, outcome_ref)
    assert outcome["extensions"]["mcp"]["binding_version"] == "fastmcp.middleware.v0.1"  # type: ignore[index]
    assert outcome["parent_receipt_ref"] == "urn:srs:receipt:parent:1"
    assert outcome["attestation_limits"][-1] == PROXY_LIMIT  # type: ignore[index]
    for field in CANCELLATION_FIELD_NAMES:
        assert outcome[field] is True
    verify_signature(outcome, identity)


def test_attestation_limits_append_once_in_order(tmp_path):
    _identity, _sink, emitter = build(tmp_path)
    receipt_id = emitter.emit_admission(
        context=context(),
        requested_tool_name="records.lookup",
        argument_digest="sha256:" + "c" * 64,
        disposition="admitted",
        additional_attestation_limits=(PROXY_LIMIT, PROXY_LIMIT, "Second limit."),
    )
    receipt = load_receipt(tmp_path, receipt_id)
    assert receipt["attestation_limits"] == [BASE_LIMIT, PROXY_LIMIT, "Second limit."]


@pytest.mark.parametrize("bad_limit", ["", "   ", 7, None])
def test_invalid_attestation_limits_fail_before_signing(tmp_path, bad_limit):
    _identity, _sink, emitter = build(tmp_path)
    with pytest.raises(ReceiptContentError):
        emitter.emit_admission(
            context=context(),
            requested_tool_name="records.lookup",
            argument_digest="sha256:" + "d" * 64,
            disposition="admitted",
            additional_attestation_limits=(bad_limit,),  # type: ignore[arg-type]
        )
    assert not list(tmp_path.glob("urn_srs_receipt_*.json"))


def test_bare_string_is_not_accepted_as_attestation_sequence(tmp_path):
    _identity, _sink, emitter = build(tmp_path)
    with pytest.raises(ReceiptContentError, match="sequence of strings"):
        emitter.emit_admission(
            context=context(),
            requested_tool_name="records.lookup",
            argument_digest="sha256:" + "d" * 64,
            disposition="admitted",
            additional_attestation_limits=PROXY_LIMIT,  # type: ignore[arg-type]
        )
    assert not list(tmp_path.glob("urn_srs_receipt_*.json"))


def test_cancellation_fields_are_constrained_at_emit_time(tmp_path):
    _identity, _sink, emitter = build(tmp_path)
    allowed = {name: True for name in CANCELLATION_FIELD_NAMES}
    receipt_id = emitter.emit_outcome(
        context=context(),
        admission_receipt_ref="urn:srs:receipt:admission:1",
        outcome="indeterminate",
        binding_owned_fields=allowed,
    )
    receipt = load_receipt(tmp_path, receipt_id)
    assert all(receipt[name] is True for name in CANCELLATION_FIELD_NAMES)

    with pytest.raises(ReceiptContentError, match="only on indeterminate"):
        emitter.emit_outcome(
            context=context(logical_call_id="call:test:2"),
            admission_receipt_ref="urn:srs:receipt:admission:2",
            outcome="result_returned",
            result_digest="sha256:" + "e" * 64,
            binding_owned_fields={"request_cancelled": True},
        )
    with pytest.raises(ReceiptContentError, match="unknown binding-owned field"):
        emitter.emit_outcome(
            context=context(logical_call_id="call:test:3"),
            admission_receipt_ref="urn:srs:receipt:admission:3",
            outcome="indeterminate",
            binding_owned_fields={"unknown_fact": True},
        )
    with pytest.raises(ReceiptContentError, match="collides with core field"):
        emitter.emit_outcome(
            context=context(logical_call_id="call:test:4"),
            admission_receipt_ref="urn:srs:receipt:admission:4",
            outcome="indeterminate",
            binding_owned_fields={"outcome": True},
        )
    with pytest.raises(ReceiptContentError, match="must be boolean"):
        emitter.emit_outcome(
            context=context(logical_call_id="call:test:5"),
            admission_receipt_ref="urn:srs:receipt:admission:5",
            outcome="indeterminate",
            binding_owned_fields={"request_cancelled": 1},  # type: ignore[dict-item]
        )


def test_unregistered_binding_version_fails_before_signing(tmp_path):
    _identity, _sink, emitter = build(tmp_path)
    with pytest.raises(ReceiptContentError, match="unregistered binding_version"):
        emitter.emit_admission(
            context=context(binding_version="invented.binding.v9"),
            requested_tool_name="records.lookup",
            argument_digest="sha256:" + "f" * 64,
            disposition="admitted",
        )
    assert not list(tmp_path.glob("urn_srs_receipt_*.json"))


def test_each_new_fact_is_signature_covered(tmp_path):
    identity, _sink, emitter = build(tmp_path)
    receipt_id = emitter.emit_outcome(
        context=context(
            binding_version="fastmcp.middleware.v0.1",
            parent_receipt_ref="urn:srs:receipt:parent:1",
        ),
        admission_receipt_ref="urn:srs:receipt:admission:1",
        outcome="indeterminate",
        additional_attestation_limits=(PROXY_LIMIT,),
        binding_owned_fields={
            "request_cancelled": True,
            "execution_state_unknown": True,
            "delivery_incomplete": True,
        },
    )
    receipt = load_receipt(tmp_path, receipt_id)
    verify_signature(receipt, identity)

    mutations = []
    changed = copy.deepcopy(receipt)
    changed["extensions"]["mcp"]["binding_version"] = "direct-harness.v0.1"  # type: ignore[index]
    mutations.append(changed)
    changed = copy.deepcopy(receipt)
    changed["parent_receipt_ref"] = "urn:srs:receipt:parent:2"
    mutations.append(changed)
    changed = copy.deepcopy(receipt)
    changed["attestation_limits"][-1] = "Changed proxy limit."  # type: ignore[index]
    mutations.append(changed)
    for field in CANCELLATION_FIELD_NAMES:
        changed = copy.deepcopy(receipt)
        changed[field] = False
        mutations.append(changed)

    for mutation in mutations:
        with pytest.raises(InvalidSignature):
            verify_signature(mutation, identity)


def _fallback_nine_verdicts(receipt: dict[str, object], bundle: dict[str, object]) -> dict[str, object]:
    schema_bytes = SCHEMA_PATH.read_bytes()
    schema_digest = hashlib.sha256(schema_bytes).hexdigest() == (
        "d03aad1d5517e2acb65d5c866905aed7219bcbbfadd1a4a97eac546dd23f0333"
    )
    envelope = not list(Draft202012Validator(SCHEMA).iter_errors(receipt))
    profile = (
        receipt.get("receipt_version") == RECEIPT_VERSION
        and receipt.get("profile_id") == PROFILE_ID
        and receipt.get("profile_version") == PROFILE_VERSION
        and receipt.get("receipt_kind") == "outcome"
        and receipt.get("outcome") == "indeterminate"
        and receipt.get("admission_receipt_ref")
    )
    forbidden = {
        "prompt_text", "transcript", "raw_payload", "tool_arguments", "arguments",
        "result_body", "headers", "prompt", "raw_prompt", "raw_output", "result",
        "tool_result", "request_body", "response_body", "access_token", "private_key",
    }

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key, item
                yield from walk(item)
        elif isinstance(value, list):
            for item in value:
                yield None, item
                yield from walk(item)

    raw_content_exclusion = not any(key in forbidden for key, _ in walk(receipt))
    signature_valid = True
    try:
        entry = bundle["issuers"][0]  # type: ignore[index]
        preimage = copy.deepcopy(receipt)
        signature = decode(preimage["receipt_signature"].pop("signature"))  # type: ignore[union-attr]
        Ed25519PublicKey.from_public_bytes(decode(entry["public_key"])).verify(  # type: ignore[index]
            signature, rfc8785.dumps(preimage)
        )
    except Exception:
        signature_valid = False
    entry = bundle["issuers"][0]  # type: ignore[index]
    key_id = receipt["receipt_signature"]["key_id"]  # type: ignore[index]
    issuer_key_resolved = entry["key_id"] == key_id  # type: ignore[index]
    issuer_key_trusted = (
        issuer_key_resolved
        and entry["trusted"] is True  # type: ignore[index]
        and entry["issuer_id"] == receipt["issuer_id"]  # type: ignore[index]
    )
    attestation_limits_present = bool(receipt.get("attestation_limits"))
    return {
        "schema_digest": schema_digest,
        "envelope": envelope,
        "profile": bool(profile),
        "raw_content_exclusion": raw_content_exclusion,
        "signature_valid": signature_valid,
        "issuer_key_resolved": issuer_key_resolved,
        "issuer_key_trusted": issuer_key_trusted,
        "attestation_limits_present": attestation_limits_present,
        "chain_status": "not_applicable",
    }


def test_combined_extension_receipt_passes_all_boolean_verdicts_with_chain_status(tmp_path):
    identity, _sink, emitter = build(tmp_path)
    receipt_id = emitter.emit_outcome(
        context=context(
            binding_version="fastmcp.middleware.v0.1",
            parent_receipt_ref="urn:srs:receipt:parent:1",
        ),
        admission_receipt_ref="urn:srs:receipt:admission:1",
        outcome="indeterminate",
        additional_attestation_limits=(PROXY_LIMIT,),
        binding_owned_fields={
            "request_cancelled": True,
            "execution_state_unknown": True,
            "delivery_incomplete": True,
        },
    )
    receipt = load_receipt(tmp_path, receipt_id)
    bundle = identity.trust_bundle()

    try:
        from arcs_verify.verifier import verify_receipt
    except ModuleNotFoundError:
        report = _fallback_nine_verdicts(receipt, bundle)
        print("arcs-verify unavailable; used frozen-rule nine-verdict fallback")
    else:
        verified = verify_receipt(
            receipt,
            bundle,
            schema_path=SCHEMA_PATH,
            selected_profile="srs.mcp.sdk_enforcement.v0.1",
        )
        report = verified.to_dict()

    for verdict in (
        "schema_digest",
        "envelope",
        "profile",
        "raw_content_exclusion",
        "signature_valid",
        "issuer_key_resolved",
        "issuer_key_trusted",
        "attestation_limits_present",
    ):
        assert report[verdict] is True, report
    assert report["chain_status"] == "not_applicable"
