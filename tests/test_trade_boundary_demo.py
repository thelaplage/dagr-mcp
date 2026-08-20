"""DAGR-TRADE0: observed admitted-vs-refused trade admission boundary proof.

These tests prove the pre-dispatch-refusal claim by observation rather than
assertion, over two distinct tools sharing one wrap_handler-based boundary
and one broker sentinel:

    read_market_research -> admitted -> broker invoked exactly once
                                       -> admission + outcome receipts
    place_trade_order    -> refused   -> broker invoked zero times
                                       -> admission receipt only

Every acceptance criterion below is mechanically checked against emitted
artifacts (invocation counters, receipt counts, receipt fields, an
independent Ed25519 re-verification, and -- when the real ``arcs-verify``
CLI is on PATH -- the actual external verifier) rather than asserted by
narration.
"""

from __future__ import annotations

import base64
import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator

from dagr_mcp.enforcement_harness import HarnessSinks, wrap_handler
from dagr_mcp.sdk_spine import InMemoryEventSink
from dagr_mcp.srs_bridge import BridgeConfig, HarnessSRSBridge
from dagr_mcp.trade_boundary_demo import (
    BrokerDispatchSentinel,
    PLACE_TRADE_ORDER_ARGUMENTS,
    PLACE_TRADE_ORDER_TOOL,
    PROFILE,
    READ_MARKET_RESEARCH_ARGUMENTS,
    READ_MARKET_RESEARCH_TOOL,
    BoundaryObservation,
    _build_emitter,
    _config,
    build_side_effects_payload,
    build_trade_boundary_policies,
    run_trade_boundary_proof,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "dagr_mcp/vendor/srs/srs-envelope-v0.2.0.schema.json").read_text())

RAW_RESEARCH_CANARY = READ_MARKET_RESEARCH_ARGUMENTS["raw_query_canary"]
RAW_ORDER_CANARY = PLACE_TRADE_ORDER_ARGUMENTS["raw_order_canary"]


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


# ---------------------------------------------------------------------------
# Core admission-boundary proof
# ---------------------------------------------------------------------------


def test_refused_call_is_denied_before_dispatch(tmp_path):
    proof = run_trade_boundary_proof(tmp_path / "output")
    refused = proof.refused
    assert refused.tool_name == PLACE_TRADE_ORDER_TOOL
    assert refused.policy_decision == "deny"
    assert refused.result.ok is False
    assert refused.result.failure_reason == "denied"
    # Delta-based, not absolute-zero: the admitted call ran first and already
    # advanced the shared sentinel to 1, so a hardcoded "count == 0" check
    # would misreport this. Only before == after (no delta) reads correctly.
    assert refused.invocation_count_after == refused.invocation_count_before
    assert refused.broker_dispatched is False


def test_admitted_call_dispatches_exactly_once_and_emits_expected_pair(tmp_path):
    proof = run_trade_boundary_proof(tmp_path / "output")
    admitted = proof.admitted
    assert admitted.tool_name == READ_MARKET_RESEARCH_TOOL
    assert admitted.policy_decision == "allow"
    assert admitted.result.ok is True
    assert admitted.invocation_count_after == admitted.invocation_count_before + 1
    assert admitted.broker_dispatched is True
    assert len(admitted.result.receipt_refs) == 2

    receipts = [json.loads(p.read_text()) for p in proof.directory.glob("urn_srs_receipt_*.json")]
    admission = next(r for r in receipts if r["receipt_id"] == admitted.result.receipt_refs[0])
    outcome = next(r for r in receipts if r["receipt_id"] == admitted.result.receipt_refs[1])
    assert admission["receipt_kind"] == "admission"
    assert admission["disposition"] == "admitted"
    assert admission["requested_tool_name"] == READ_MARKET_RESEARCH_TOOL
    assert outcome["receipt_kind"] == "outcome"


def test_refused_call_emits_exactly_one_admission_receipt_and_no_outcome_receipt(tmp_path):
    proof = run_trade_boundary_proof(tmp_path / "output")
    refused = proof.refused
    admission_ref = refused.result.context.admission_receipt_ref
    assert admission_ref is not None

    receipts = [json.loads(p.read_text()) for p in proof.directory.glob("urn_srs_receipt_*.json")]
    # Only admission receipts carry requested_tool_name; outcome receipts
    # link back to their admission via admission_receipt_ref instead.
    place_trade_admissions = [
        r for r in receipts
        if r["receipt_kind"] == "admission" and r["requested_tool_name"] == PLACE_TRADE_ORDER_TOOL
    ]
    assert len(place_trade_admissions) == 1
    assert place_trade_admissions[0]["receipt_id"] == admission_ref
    assert place_trade_admissions[0]["disposition"] == "refused"
    assert place_trade_admissions[0]["reason_code"] == "policy_refused"

    outcomes_linked_to_refusal = [
        r for r in receipts
        if r["receipt_kind"] == "outcome" and r["admission_receipt_ref"] == admission_ref
    ]
    assert outcomes_linked_to_refusal == []


def test_full_proof_emits_exactly_three_receipts_total(tmp_path):
    proof = run_trade_boundary_proof(tmp_path / "output")
    receipts = [json.loads(p.read_text()) for p in proof.directory.glob("urn_srs_receipt_*.json")]
    assert len(receipts) == 3
    assert sorted(r["receipt_kind"] for r in receipts) == ["admission", "admission", "outcome"]
    assert sorted(r["disposition"] for r in receipts if r["receipt_kind"] == "admission") == [
        "admitted", "refused",
    ]


# ---------------------------------------------------------------------------
# Isolated (fresh-sentinel) proof: broker sentinel remains absolute zero on a
# refused call with no prior admitted call to have advanced it. Complements
# the delta-based proof above rather than replacing it -- together they show
# both that a refusal never dispatches AND that the delta check isn't
# vacuously true only because nothing else runs.
# ---------------------------------------------------------------------------


def test_isolated_refused_call_leaves_broker_sentinel_at_absolute_zero(tmp_path):
    directory = tmp_path / "output"
    directory.mkdir()
    _identity, emitter = _build_emitter(directory, capture=False)
    bridge = HarnessSRSBridge(
        emitter=emitter,
        config=BridgeConfig(
            runtime_instance_id="runtime:test:isolated",
            boundary_id="boundary:test:isolated",
            policy_pack_id="policy:test:isolated",
            policy_pack_version="v0.1",
        ),
    )
    sentinel = BrokerDispatchSentinel()
    assert sentinel.invocation_count == 0

    handler = wrap_handler(
        sentinel,
        _config(),
        HarnessSinks(event=InMemoryEventSink()),
        policies=build_trade_boundary_policies(),
        srs_bridge=bridge,
    )
    result = handler(
        PLACE_TRADE_ORDER_TOOL,
        PLACE_TRADE_ORDER_ARGUMENTS,
        {"request_ref": "call:test:isolated-refused", "actor_ref": "actor:test"},
    )

    assert result.ok is False
    assert sentinel.invocation_count == 0
    assert sentinel.ledger == []


def test_broker_sentinel_itself_increments_when_actually_called():
    # Sanity check on the fake, not the harness: the sentinel is not a stub
    # that always reads zero regardless of invocation.
    sentinel = BrokerDispatchSentinel()
    assert sentinel.invocation_count == 0
    sentinel("read_market_research", {"x": 1})
    assert sentinel.invocation_count == 1
    assert sentinel.ledger == [{"seq": 1, "tool_name": "read_market_research"}]


# ---------------------------------------------------------------------------
# Raw content exclusion: arguments/results never enter the receipt contract
# ---------------------------------------------------------------------------


def test_raw_arguments_never_appear_in_any_emitted_receipt_bytes(tmp_path):
    proof = run_trade_boundary_proof(tmp_path / "output")
    for path in proof.directory.glob("urn_srs_receipt_*.json"):
        raw_bytes = path.read_bytes()
        assert RAW_RESEARCH_CANARY.encode() not in raw_bytes, path.name
        assert RAW_ORDER_CANARY.encode() not in raw_bytes, path.name
    # Also confirm the canaries are real (present in the arguments dicts
    # actually passed into the boundary), so their absence above is a
    # meaningful exclusion, not a typo that was never in scope to leak.
    assert RAW_RESEARCH_CANARY in READ_MARKET_RESEARCH_ARGUMENTS["raw_query_canary"]
    assert RAW_ORDER_CANARY in PLACE_TRADE_ORDER_ARGUMENTS["raw_order_canary"]


def test_receipts_carry_argument_digest_not_raw_arguments(tmp_path):
    proof = run_trade_boundary_proof(tmp_path / "output")
    receipts = [json.loads(p.read_text()) for p in proof.directory.glob("urn_srs_receipt_*.json")]
    admissions = [r for r in receipts if r["receipt_kind"] == "admission"]
    assert len(admissions) == 2
    for receipt in admissions:
        assert receipt["argument_digest"].startswith("sha256:")
        assert set(receipt.keys()).isdisjoint(
            {"arguments", "raw_arguments", "tool_arguments", "raw_tool_arguments"}
        )


# ---------------------------------------------------------------------------
# Schema conformance + independent signature re-verification
# ---------------------------------------------------------------------------


def test_emitted_receipts_pass_schema_and_signature_verification(tmp_path):
    proof = run_trade_boundary_proof(tmp_path / "output")
    bundle = json.loads((proof.directory / "issuer-keys.json").read_text())
    public_key = _decode(bundle["issuers"][0]["public_key"])
    receipts = [json.loads(p.read_text()) for p in proof.directory.glob("urn_srs_receipt_*.json")]
    assert len(receipts) == 3
    for receipt in receipts:
        assert not list(Draft202012Validator(SCHEMA).iter_errors(receipt))
        assert _independent_verify(receipt, public_key)


# ---------------------------------------------------------------------------
# Determinism (capture mode) -- parity with dagr_mcp.first_run_demo
# ---------------------------------------------------------------------------


def test_capture_mode_digests_are_identical_across_runs(tmp_path):
    proof_a = run_trade_boundary_proof(tmp_path / "a", capture=True)
    proof_b = run_trade_boundary_proof(tmp_path / "b", capture=True)

    receipts_a = sorted(proof_a.directory.glob("urn_srs_receipt_*.json"))
    receipts_b = sorted(proof_b.directory.glob("urn_srs_receipt_*.json"))
    assert [p.name for p in receipts_a] == [p.name for p in receipts_b]
    for a, b in zip(receipts_a, receipts_b):
        assert a.read_bytes() == b.read_bytes()


def test_default_mode_digests_are_not_identical_across_runs(tmp_path):
    proof_a = run_trade_boundary_proof(tmp_path / "a")
    proof_b = run_trade_boundary_proof(tmp_path / "b")
    bundle_a = (proof_a.directory / "issuer-keys.json").read_bytes()
    bundle_b = (proof_b.directory / "issuer-keys.json").read_bytes()
    assert bundle_a != bundle_b


# ---------------------------------------------------------------------------
# Side-effects payload: booleans are derived, not literal
# ---------------------------------------------------------------------------


def test_side_effects_json_booleans_are_derived_not_literal(tmp_path):
    proof = run_trade_boundary_proof(tmp_path / "output")
    payload = json.loads(proof.side_effects_path.read_text())
    scenarios = payload["scenarios"]
    assert scenarios["admitted"]["broker_dispatched"] is True
    assert scenarios["refused"]["broker_dispatched"] is False
    assert scenarios["refused"]["inner_invocation_count_before"] == 1
    assert scenarios["refused"]["inner_invocation_count_after"] == 1


def test_build_side_effects_payload_rejects_absolute_zero_check(tmp_path):
    class _FakeResult:
        ok = False
        failure_reason = "denied"
        receipt_refs: list[str] = []
        policy_decision = None

        class context:
            admission_receipt_ref = "urn:srs:receipt:admission:fake"

    refused = BoundaryObservation(
        name="refused", tool_name=PLACE_TRADE_ORDER_TOOL, policy_decision="deny",
        result=_FakeResult(), invocation_count_before=5, invocation_count_after=5,
    )

    class _FakeOkResult:
        ok = True
        failure_reason = None
        receipt_refs = ["urn:srs:receipt:admission:fake2", "urn:srs:receipt:outcome:fake2"]
        context = None
        policy_decision = None

    admitted = BoundaryObservation(
        name="admitted", tool_name=READ_MARKET_RESEARCH_TOOL, policy_decision="allow",
        result=_FakeOkResult(), invocation_count_before=5, invocation_count_after=6,
    )

    payload = build_side_effects_payload(
        admitted=admitted, refused=refused, directory=tmp_path, capture_mode=False,
    )
    assert payload["scenarios"]["refused"]["broker_dispatched"] is False
    assert payload["scenarios"]["admitted"]["broker_dispatched"] is True


# ---------------------------------------------------------------------------
# The real arcs-verify CLI, when available. Cross-repo: skipped, not failed,
# when the sibling verifier isn't installed in this environment -- DAGR's own
# suite must stay green without that dependency, per the ARCS-TRADE0 staging.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("arcs-verify") is None, reason="arcs-verify CLI not installed")
def test_generated_receipts_pass_the_real_arcs_verify_cli(tmp_path):
    proof = run_trade_boundary_proof(tmp_path / "output")
    keyring = proof.directory / "issuer-keys.json"
    for receipt_path in sorted(proof.directory.glob("urn_srs_receipt_*.json")):
        result = subprocess.run(
            ["arcs-verify", str(receipt_path), "--keyring", str(keyring), "--profile", PROFILE, "--json"],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, f"{receipt_path.name}: {result.stdout}\n{result.stderr}"
        report = json.loads(result.stdout)
        assert report["passed"] is True
        assert report["raw_content_exclusion"] is True
        assert report["signature_valid"] is True


# ---------------------------------------------------------------------------
# Structural guard: this module's own source text (comments and docstrings
# included) must never spell out domain-specific vocabulary, even to
# disavow it -- a disavowal sentence that names the banned terms defeats
# itself the moment it's read out of context. Mirrors the same guard on
# operator_admission_resolver.py; this file has weaker obligations (it is
# allowed to know the two demo tool names) but the same banned-terms list.
# ---------------------------------------------------------------------------


def test_trade_boundary_demo_source_has_no_disavowed_domain_vocabulary():
    import inspect

    from dagr_mcp import trade_boundary_demo

    source = inspect.getsource(trade_boundary_demo).lower()
    banned_substrings = [
        "countervail", "mnpi", "insider", "restricted list",
        "restricted_list", "compliance", "fsi", "watchlist", "wall-crossed",
        "wall_crossed",
    ]
    hits = [needle for needle in banned_substrings if needle in source]
    assert hits == [], f"trade_boundary_demo.py contains domain vocabulary: {hits}"
