from __future__ import annotations

import base64
import copy
import json
from pathlib import Path

import pytest
import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator

from dagr_mcp.enforcement_harness import HarnessConfig, HarnessSinks, ToolPolicy, wrap_handler
from dagr_mcp.sdk_spine import InMemoryEventSink, InMemoryReviewObjectSink
from dagr_mcp.srs_bridge import BridgeConfig, HarnessSRSBridge
from dagr_mcp.srs_receipts import RawEnvelopeFileSink, ReceiptContentError, SignedReceiptEmitter, SigningIdentity

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "dagr_mcp/vendor/srs/srs-envelope-v0.2.0.schema.json").read_text())


def decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify(envelope: dict, bundle: dict) -> None:
    assert not list(Draft202012Validator(SCHEMA).iter_errors(envelope))
    entry = bundle["issuers"][0]
    preimage = copy.deepcopy(envelope)
    signature = decode(preimage["receipt_signature"].pop("signature"))
    canonical = rfc8785.dumps(preimage)
    Ed25519PublicKey.from_public_bytes(decode(entry["public_key"])).verify(signature, canonical)


def build(tmp_path: Path):
    identity = SigningIdentity.generate(issuer_id="issuer:test", key_id="issuer.test/key/1")
    sink = RawEnvelopeFileSink(tmp_path)
    emitter = SignedReceiptEmitter(identity=identity, sink=sink)
    bridge = HarnessSRSBridge(
        emitter=emitter,
        config=BridgeConfig(
            runtime_instance_id="runtime:test:1",
            boundary_id="boundary:test:1",
            policy_pack_id="policy:test",
            policy_pack_version="1",
        ),
    )
    return identity, sink, bridge


def test_admitted_call_emits_linked_signed_receipts_before_and_after(tmp_path):
    identity, sink, bridge = build(tmp_path)
    observed = {"receipt_count_at_inner": None}

    def inner(tool_name, arguments, context=None):
        observed["receipt_count_at_inner"] = len(list(tmp_path.glob("*.json")))
        return {"ok": True, "count": 1}

    wrapped = wrap_handler(
        inner,
        HarnessConfig("1", "module", "1", "profile", "policy"),
        HarnessSinks(event=InMemoryEventSink()),
        policies=[ToolPolicy("records.lookup", "read", "allow")],
        srs_bridge=bridge,
    )
    result = wrapped("records.lookup", {"record_ref": "record:1"}, {"request_ref": "call-1", "actor_ref": "actor:1"})
    assert result.ok
    assert observed["receipt_count_at_inner"] == 1
    paths = sorted(tmp_path.glob("urn_srs_receipt_*.json"))
    assert len(paths) == 2
    receipts = [json.loads(path.read_text()) for path in paths]
    admission = next(item for item in receipts if item["receipt_kind"] == "admission")
    outcome = next(item for item in receipts if item["receipt_kind"] == "outcome")
    assert outcome["admission_receipt_ref"] == admission["receipt_id"]
    bundle = identity.trust_bundle()
    for receipt in receipts:
        verify(receipt, bundle)


def test_refused_call_is_terminal_and_handler_does_not_run(tmp_path):
    identity, sink, bridge = build(tmp_path)
    called = False

    def inner(*args, **kwargs):
        nonlocal called
        called = True
        return {}

    wrapped = wrap_handler(
        inner,
        HarnessConfig("1", "module", "1", "profile", "policy"),
        HarnessSinks(event=InMemoryEventSink()),
        policies=[ToolPolicy("danger", "destructive", "deny")],
        srs_bridge=bridge,
    )
    result = wrapped("danger", {"record_ref": "record:1"}, {"request_ref": "call-2"})
    assert not result.ok
    assert not called
    receipts = [json.loads(path.read_text()) for path in tmp_path.glob("urn_srs_receipt_*.json")]
    assert len(receipts) == 1
    assert receipts[0]["disposition"] == "refused"


def test_gate_emits_terminal_deferred_admission(tmp_path):
    identity, sink, bridge = build(tmp_path)
    wrapped = wrap_handler(
        lambda *args, **kwargs: {"unexpected": True},
        HarnessConfig("1", "module", "1", "profile", "policy"),
        HarnessSinks(event=InMemoryEventSink(), review=InMemoryReviewObjectSink()),
        policies=[ToolPolicy("write", "write", "gate", review_required=True)],
        srs_bridge=bridge,
    )
    result = wrapped("write", {"record_ref": "record:1"}, {"request_ref": "call-3"})
    assert not result.ok
    receipt = json.loads(next(tmp_path.glob("urn_srs_receipt_*.json")).read_text())
    assert receipt["disposition"] == "deferred_for_review"
    assert receipt["retry_contract"] == "retry_after_approval"
    assert receipt["review_object_ref"]


def test_raw_content_rejected_before_signing(tmp_path):
    identity, sink, bridge = build(tmp_path)
    with pytest.raises(ReceiptContentError):
        identity.sign_envelope({
            "receipt_signature": {"algorithm": "Ed25519", "canonicalization": "RFC8785-JCS", "key_id": "x", "signature": ""},
            "extensions": {"mcp": {"arguments": {"secret": True}}},
        })


def test_trust_bundle_contains_no_private_key_material(tmp_path):
    identity, sink, bridge = build(tmp_path)
    bundle = identity.trust_bundle()
    text = json.dumps(bundle).lower()
    assert "private_key" not in text
    assert "seed" not in text
    path = sink.write_trust_bundle(bundle)
    assert path.exists()


def test_review_object_creation_failure_is_terminal_refusal(tmp_path):
    identity, sink, bridge = build(tmp_path)
    called = False

    class FailingReviewSink(InMemoryReviewObjectSink):
        def create_review_object(self, review):
            raise RuntimeError("unavailable")

    def inner(*args, **kwargs):
        nonlocal called
        called = True
        return {"unexpected": True}

    wrapped = wrap_handler(
        inner,
        HarnessConfig("1", "module", "1", "profile", "policy"),
        HarnessSinks(event=InMemoryEventSink(), review=FailingReviewSink()),
        policies=[ToolPolicy("write", "write", "gate", review_required=True)],
        srs_bridge=bridge,
    )
    result = wrapped("write", {"record_ref": "record:1"}, {"request_ref": "call-4"})
    assert not result.ok
    assert not called
    receipts = [json.loads(path.read_text()) for path in tmp_path.glob("urn_srs_receipt_*.json")]
    assert len(receipts) == 1
    assert receipts[0]["disposition"] == "refused"
    assert receipts[0]["reason_code"] == "review_object_creation_failed"
    assert "review_object_ref" not in receipts[0]
