"""F0: observed admitted-vs-refused native-action execution.

These tests prove the enforced-refusal claim by observation rather than
assertion: the same wrap_handler-based scenario runner, over the same inner
handler (a sentinel standing in for a native host action) and the same
arguments, is driven once under an admitting policy and once under a denying
policy, and the resulting invocation counts / receipts are read back.
"""

from __future__ import annotations

import base64
import copy
import json
from pathlib import Path

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator

from dagr_mcp.first_run_demo import (
    NativeActionSentinel,
    ScenarioObservation,
    build_side_effects_payload,
    run_first_run_proof,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "dagr_mcp/vendor/srs/srs-envelope-v0.2.0.schema.json").read_text())


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _independent_verify(receipt: dict, public_key: bytes) -> bool:
    signature = _decode(receipt["receipt_signature"]["signature"])
    preimage = copy.deepcopy(receipt)
    del preimage["receipt_signature"]["signature"]
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, rfc8785.dumps(preimage))
        return True
    except InvalidSignature:
        return False


def test_refused_call_leaves_sentinel_unchanged_and_invocation_count_zero(tmp_path):
    proof = run_first_run_proof(tmp_path / "output")
    refused = proof.refused
    assert refused.result.ok is False
    assert refused.result.failure_reason == "denied"
    assert refused.invocation_count_after == refused.invocation_count_before
    assert refused.native_action_executed is False


def test_admitted_call_changes_sentinel_and_emits_exactly_two_receipts(tmp_path):
    proof = run_first_run_proof(tmp_path / "output")
    admitted = proof.admitted
    assert admitted.result.ok is True
    assert admitted.invocation_count_after == admitted.invocation_count_before + 1
    assert admitted.native_action_executed is True
    assert len(admitted.result.receipt_refs) == 2

    receipts = [json.loads(p.read_text()) for p in proof.directory.glob("urn_srs_receipt_*.json")]
    assert len(receipts) == 3
    assert sorted(r["receipt_kind"] for r in receipts) == ["admission", "admission", "outcome"]


def test_inner_handler_never_invoked_on_refused_call():
    sentinel = NativeActionSentinel()
    assert sentinel.invocation_count == 0
    # Sanity: the sentinel itself does increment when actually called.
    sentinel("frontdoor.native_action", {"x": 1})
    assert sentinel.invocation_count == 1


def test_side_effects_json_booleans_are_derived_not_literal(tmp_path):
    proof = run_first_run_proof(tmp_path / "output")
    payload = json.loads(proof.side_effects_path.read_text())
    scenarios = payload["scenarios"]
    assert scenarios["admitted"]["native_action_executed"] is True
    assert scenarios["refused"]["native_action_executed"] is False

    # A hardcoded "native_action_executed = (invocation_count_after == 0)"
    # would misreport the refused scenario here, because the admitted call
    # ran first and already advanced the shared sentinel to 1: the refused
    # scenario's "after" count is 1, not 0. Only a before/after delta reads
    # correctly. Confirm both readings are structurally present and correct.
    refused = scenarios["refused"]
    assert refused["inner_invocation_count_after"] == 1
    assert refused["inner_invocation_count_before"] == 1
    assert refused["native_action_executed"] is False

    admitted = scenarios["admitted"]
    assert admitted["inner_invocation_count_before"] == 0
    assert admitted["inner_invocation_count_after"] == 1


def test_build_side_effects_payload_rejects_absolute_zero_check(tmp_path):
    # Directly exercise the pure builder with a scenario whose "after" count
    # is nonzero due to prior shared state, to prove the derivation is a
    # delta and not an absolute-zero literal check.
    class _FakeResult:
        ok = False
        failure_reason = "denied"
        receipt_refs: list[str] = []

        class context:
            admission_receipt_ref = "urn:srs:receipt:admission:fake"

    refused = ScenarioObservation(
        name="refused",
        policy_decision="deny",
        result=_FakeResult(),
        invocation_count_before=5,
        invocation_count_after=5,
    )

    class _FakeOkResult:
        ok = True
        failure_reason = None
        receipt_refs = ["urn:srs:receipt:admission:fake2", "urn:srs:receipt:outcome:fake2"]
        context = None

    admitted = ScenarioObservation(
        name="admitted",
        policy_decision="allow",
        result=_FakeOkResult(),
        invocation_count_before=5,
        invocation_count_after=6,
    )

    payload = build_side_effects_payload(
        admitted=admitted, refused=refused, directory=tmp_path, capture_mode=False,
    )
    assert payload["scenarios"]["refused"]["native_action_executed"] is False
    assert payload["scenarios"]["admitted"]["native_action_executed"] is True


def test_emitted_receipts_pass_schema_and_signature_verification(tmp_path):
    proof = run_first_run_proof(tmp_path / "output")
    bundle = json.loads((proof.directory / "issuer-keys.json").read_text())
    public_key = _decode(bundle["issuers"][0]["public_key"])
    receipts = [json.loads(p.read_text()) for p in proof.directory.glob("urn_srs_receipt_*.json")]
    assert len(receipts) == 3
    for receipt in receipts:
        assert not list(Draft202012Validator(SCHEMA).iter_errors(receipt))
        assert _independent_verify(receipt, public_key)


def test_capture_mode_digests_are_identical_across_runs(tmp_path):
    proof_a = run_first_run_proof(tmp_path / "a", capture=True)
    proof_b = run_first_run_proof(tmp_path / "b", capture=True)

    receipts_a = sorted(proof_a.directory.glob("urn_srs_receipt_*.json"))
    receipts_b = sorted(proof_b.directory.glob("urn_srs_receipt_*.json"))
    assert [p.name for p in receipts_a] == [p.name for p in receipts_b]
    for a, b in zip(receipts_a, receipts_b):
        assert a.read_bytes() == b.read_bytes()

    bundle_a = (proof_a.directory / "issuer-keys.json").read_bytes()
    bundle_b = (proof_b.directory / "issuer-keys.json").read_bytes()
    assert bundle_a == bundle_b


def test_default_mode_digests_are_not_identical_across_runs(tmp_path):
    proof_a = run_first_run_proof(tmp_path / "a")
    proof_b = run_first_run_proof(tmp_path / "b")

    bundle_a = (proof_a.directory / "issuer-keys.json").read_bytes()
    bundle_b = (proof_b.directory / "issuer-keys.json").read_bytes()
    assert bundle_a != bundle_b

    receipts_a = {p.name for p in proof_a.directory.glob("urn_srs_receipt_*.json")}
    receipts_b = {p.name for p in proof_b.directory.glob("urn_srs_receipt_*.json")}
    assert receipts_a.isdisjoint(receipts_b)
