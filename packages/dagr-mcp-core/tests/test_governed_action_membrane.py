"""Product-neutral governed-action membrane proofs (v0.1).

These tests prove the smallest governed-action extension stays detached from
caller's nested mutable state, emits bounded SRS receipts, and preserves the
RF-05 distinction between execution fact and later durability fact.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

import pytest

from dagr_mcp_core.lifecycle.governed_action import (
    GOVERNED_ACTION_REASON_CODES,
    GovernedActionBoundaryConfig,
    GovernedActionRequest,
    decide_governed_action,
    run_governed_action,
)
from dagr_mcp_core.srs_receipts import RawEnvelopeFileSink, ReceiptContext, SignedReceiptEmitter, SigningIdentity

from receipt_verification import verify_receipt

VENDOR = Path(__file__).parent / "vendor"
SCHEMA_V0_2_0_PATH = VENDOR / "srs-envelope-v0.2.0.schema.json"
SCHEMA_V0_2_0 = json.loads(SCHEMA_V0_2_0_PATH.read_text())
PROFILE = "srs.mcp.sdk_enforcement.v0.1"


def _emitter(directory: Path):
    identity = SigningIdentity.generate(
        issuer_id="issuer:governed-action", key_id="issuer.governed-action/key/1"
    )
    sink = RawEnvelopeFileSink(directory)
    emitter = SignedReceiptEmitter(identity=identity, sink=sink)
    sink.write_trust_bundle(identity.trust_bundle())
    return identity, emitter


def _context() -> ReceiptContext:
    return ReceiptContext(
        runtime_instance_id="runtime:governed-action:test",
        boundary_id="boundary:governed-action:test",
        policy_pack_id="policy-pack:governed-action:test",
        policy_pack_version="v0.1",
        subject_ref="subject:governed-action:test",
        logical_call_id="call:governed-action:test",
        binding_version="official-mcp-sdk.python.v0.2",
    )


def _config() -> GovernedActionBoundaryConfig:
    return GovernedActionBoundaryConfig(
        policy_ref="policy:governed-action",
        policy_version="v0.1",
        known_capabilities=frozenset(
            {
                "allow_capability",
                "refuse_capability",
                "defer_capability",
                "mismatch_capability",
                "scope_capability",
                "exception_capability",
                "gap_capability",
            }
        ),
        admitted_capabilities=frozenset(
            {
                "allow_capability",
                "exception_capability",
                "gap_capability",
                "scope_capability",
            }
        ),
        deferred_capabilities=frozenset({"defer_capability"}),
        admitted_scopes=frozenset({"scope:bounded"}),
    )


def _request(
    *,
    tool_name: str,
    principal_ref: str = "principal:alice",
    policy_ref: str = "policy:governed-action",
    policy_version: str = "v0.1",
    requested_scope: str = "scope:bounded",
    arguments: dict[str, Any] | None = None,
) -> GovernedActionRequest:
    return GovernedActionRequest(
        request_ref="request:governed-action:1",
        principal_ref=principal_ref,
        tool_name=tool_name,
        action_name="governed_action",
        requested_scope=requested_scope,
        policy_ref=policy_ref,
        policy_version=policy_version,
        arguments_snapshot=arguments or {"payload": {"nested": ["alpha", {"canary": "beta"}]}},
        session_ref="session:governed-action:1",
        correlation_metadata={"audit": "opaque", "trace": "trace-1"},
    )


def _semantic_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    cleaned = copy.deepcopy(receipt)
    cleaned.pop("receipt_id", None)
    cleaned.pop("issued_at", None)
    cleaned.pop("receipt_signature", None)
    cleaned.pop("admission_receipt_ref", None)
    return cleaned


class _CountingExecutor:
    def __init__(self, *, result: Any = None, raises: BaseException | None = None):
        self.count = 0
        self.result = result if result is not None else {"ok": True}
        self.raises = raises

    def __call__(self, arguments: Mapping[str, Any]) -> Any:
        self.count += 1
        if self.raises is not None:
            raise self.raises
        return self.result


class _FlakyAfterFirstWriteSink:
    def __init__(self, real_sink):
        self._real = real_sink
        self._count = 0

    def write(self, envelope):
        self._count += 1
        if self._count == 1:
            return self._real.write(envelope)
        raise RuntimeError("receipt sink unavailable")


def test_closed_reason_vocabulary_is_explicit_and_small():
    assert GOVERNED_ACTION_REASON_CODES == (
        "policy_refused",
        "unknown_tool_fail_closed",
        "unknown_capability_fail_closed",
        "capability_mismatch",
        "scope_widening_attempt",
        "malformed_principal",
        "unknown_policy_fail_closed",
        "malformed_policy",
        "policy_version_mismatch",
    )


def test_request_is_deeply_detached_from_nested_caller_state():
    raw_arguments = {"outer": {"inner": ["alpha", {"canary": "beta"}]}}
    request = _request(tool_name="allow_capability", arguments=raw_arguments)
    before_identity = request.request_identity
    before_digest = request.argument_digest

    raw_arguments["outer"]["inner"][1]["canary"] = "mutated"

    assert request.request_identity == before_identity
    assert request.argument_digest == before_digest
    decision = decide_governed_action(request, _config())
    assert decision.decision == "allow"
    assert decision.decision_identity == decide_governed_action(request, _config()).decision_identity


@pytest.mark.parametrize(
    "request_factory, expected_decision, expected_reason",
    [
        (lambda: _request(tool_name="allow_capability"), "allow", None),
        (lambda: _request(tool_name="refuse_capability"), "refuse", "capability_mismatch"),
        (lambda: _request(tool_name="defer_capability"), "defer", None),
        (lambda: _request(tool_name="unknown_capability"), "refuse", "unknown_tool_fail_closed"),
        (lambda: _request(tool_name="scope_capability", requested_scope="scope:widened"), "refuse", "scope_widening_attempt"),
        (lambda: _request(tool_name="allow_capability", policy_ref="policy:other"), "refuse", "unknown_policy_fail_closed"),
        (lambda: _request(tool_name="allow_capability", policy_version="v0.2"), "refuse", "policy_version_mismatch"),
    ],
)
def test_deterministic_decision_boundary(request_factory, expected_decision, expected_reason):
    request = request_factory()
    decision = decide_governed_action(request, _config())
    assert decision.decision == expected_decision
    assert decision.reason_code == expected_reason
    assert decision.request_identity == request.request_identity
    assert decision.decision_identity


def test_malformed_principal_and_policy_fail_closed_before_decision():
    with pytest.raises(ValueError):
        _request(tool_name="allow_capability", principal_ref="alice")
    with pytest.raises(ValueError):
        _request(tool_name="allow_capability", policy_ref="policy-governed-action")
    with pytest.raises(ValueError):
        _request(tool_name="allow_capability", policy_version=" ")


def test_allow_calls_executor_exactly_once_and_emits_linked_receipts(tmp_path):
    identity, emitter = _emitter(tmp_path / "allow")
    executor = _CountingExecutor(result={"answer": 42})
    request = _request(tool_name="allow_capability")
    result = run_governed_action(
        request,
        config=_config(),
        receipt_context=_context(),
        executor=executor,
        emitter=emitter,
    )
    assert executor.count == 1
    assert result.execution_performed is True
    assert result.execution_outcome == "result"
    assert result.receipt_gap is False
    assert result.admission_receipt_ref is not None
    assert result.outcome_receipt_ref is not None

    receipts = [json.loads(path.read_text()) for path in (tmp_path / "allow").glob("urn_srs_receipt_*.json")]
    assert len(receipts) == 2
    admission = next(r for r in receipts if r["receipt_kind"] == "admission")
    outcome = next(r for r in receipts if r["receipt_kind"] == "outcome")
    assert admission["disposition"] == "admitted"
    assert admission["requested_tool_name"] == "allow_capability"
    assert outcome["outcome"] == "result_returned"
    assert outcome["admission_receipt_ref"] == admission["receipt_id"]
    verify_receipt(admission, identity.trust_bundle(), SCHEMA_V0_2_0)
    verify_receipt(outcome, identity.trust_bundle(), SCHEMA_V0_2_0)


@pytest.mark.parametrize(
    "tool_name, expected_reason",
    [
        ("unknown_capability", "unknown_tool_fail_closed"),
        ("refuse_capability", "capability_mismatch"),
        ("scope_capability", "scope_widening_attempt"),
    ],
)
def test_refuse_never_calls_executor_and_emits_only_admission(tool_name, expected_reason, tmp_path):
    _, emitter = _emitter(tmp_path / tool_name)
    executor = _CountingExecutor()
    request = _request(tool_name=tool_name, requested_scope="scope:widened" if tool_name == "scope_capability" else "scope:bounded")
    result = run_governed_action(
        request,
        config=_config(),
        receipt_context=_context(),
        executor=executor,
        emitter=emitter,
    )
    assert executor.count == 0
    assert result.execution_performed is False
    assert result.execution_outcome is None
    assert result.decision.reason_code == expected_reason
    assert result.receipt_gap is False
    receipts = [json.loads(path.read_text()) for path in (tmp_path / tool_name).glob("urn_srs_receipt_*.json")]
    assert len(receipts) == 1
    admission = receipts[0]
    assert admission["receipt_kind"] == "admission"
    assert admission["disposition"] == "refused"
    assert admission["reason_code"] == expected_reason


def test_defer_never_calls_executor_and_emits_deferred_evidence(tmp_path):
    _, emitter = _emitter(tmp_path / "defer")
    executor = _CountingExecutor()
    request = _request(tool_name="defer_capability")
    result = run_governed_action(
        request,
        config=_config(),
        receipt_context=_context(),
        executor=executor,
        emitter=emitter,
    )
    assert executor.count == 0
    assert result.execution_performed is False
    assert result.decision.decision == "defer"
    receipts = [json.loads(path.read_text()) for path in (tmp_path / "defer").glob("urn_srs_receipt_*.json")]
    assert len(receipts) == 1
    admission = receipts[0]
    assert admission["disposition"] == "deferred"
    assert admission["retry_contract"] == "retry_after_approval"


def test_executor_exception_is_recorded_as_execution_not_refusal(tmp_path):
    identity, emitter = _emitter(tmp_path / "boom")
    executor = _CountingExecutor(raises=ValueError("boom"))
    request = _request(tool_name="exception_capability")
    result = run_governed_action(
        request,
        config=_config(),
        receipt_context=_context(),
        executor=executor,
        emitter=emitter,
    )
    assert executor.count == 1
    assert result.execution_performed is True
    assert result.execution_outcome == "exception"
    assert result.execution_exception_class == "ValueError"
    assert result.decision.decision == "allow"
    receipts = [json.loads(path.read_text()) for path in (tmp_path / "boom").glob("urn_srs_receipt_*.json")]
    assert len(receipts) == 2
    outcome = next(r for r in receipts if r["receipt_kind"] == "outcome")
    assert outcome["outcome"] == "exception"
    assert outcome["extensions"]["mcp"]["exception_class"] == "ValueError"
    verify_receipt(outcome, identity.trust_bundle(), SCHEMA_V0_2_0)


def test_persistence_failure_after_execution_preserves_execution_fact(tmp_path):
    real_sink_dir = tmp_path / "gap"
    identity = SigningIdentity.generate(
        issuer_id="issuer:governed-action-gap", key_id="issuer.governed-action-gap/key/1"
    )
    real_sink = RawEnvelopeFileSink(real_sink_dir)
    emitter = SignedReceiptEmitter(identity=identity, sink=_FlakyAfterFirstWriteSink(real_sink))
    real_sink.write_trust_bundle(identity.trust_bundle())

    executor = _CountingExecutor(result={"result": "kept"})
    request = _request(tool_name="gap_capability")
    result = run_governed_action(
        request,
        config=_config(),
        receipt_context=_context(),
        executor=executor,
        emitter=emitter,
    )

    assert executor.count == 1
    assert result.execution_performed is True
    assert result.execution_outcome == "result"
    assert result.receipt_persisted is False
    assert result.receipt_gap is True
    receipts = [json.loads(path.read_text()) for path in real_sink_dir.glob("urn_srs_receipt_*.json")]
    assert len(receipts) == 1
    assert receipts[0]["receipt_kind"] == "admission"


def test_emitted_receipts_exclude_raw_secret_arguments(tmp_path):
    _, emitter = _emitter(tmp_path / "secrets")
    canary = "RAW_SECRET_CANARY_MUST_NOT_APPEAR"
    request = _request(
        tool_name="allow_capability",
        arguments={"nested": {"canary": canary}},
    )
    result = run_governed_action(
        request,
        config=_config(),
        receipt_context=_context(),
        executor=_CountingExecutor(result={"ok": True}),
        emitter=emitter,
    )
    assert result.execution_performed is True
    for path in (tmp_path / "secrets").glob("*.json"):
        payload = path.read_bytes()
        assert canary.encode() not in payload


def test_mutating_caller_state_after_request_construction_does_not_change_semantic_identity(tmp_path):
    raw_arguments = {"nested": {"canary": "RAW_IMMUTABLE_CANARY"}}
    request = _request(tool_name="allow_capability", arguments=raw_arguments)
    config = _config()
    decision_before = decide_governed_action(request, config)
    _, emitter_before = _emitter(tmp_path / "immut-before")
    result_before = run_governed_action(
        request,
        config=config,
        receipt_context=_context(),
        executor=_CountingExecutor(result={"ok": True}),
        emitter=emitter_before,
    )

    raw_arguments["nested"]["canary"] = "MUTATED"

    decision_after = decide_governed_action(request, config)
    _, emitter_after = _emitter(tmp_path / "immut-after")
    result_after = run_governed_action(
        request,
        config=config,
        receipt_context=_context(),
        executor=_CountingExecutor(result={"ok": True}),
        emitter=emitter_after,
    )

    assert decision_before.decision_identity == decision_after.decision_identity
    assert result_before.receipt_identity == result_after.receipt_identity

    receipts_before = [
        json.loads(path.read_text())
        for path in (tmp_path / "immut-before").glob("urn_srs_receipt_*.json")
    ]
    receipts_after = [
        json.loads(path.read_text())
        for path in (tmp_path / "immut-after").glob("urn_srs_receipt_*.json")
    ]
    assert len(receipts_before) == len(receipts_after) == 2
    before = sorted(json.dumps(_semantic_receipt(r), sort_keys=True) for r in receipts_before)
    after = sorted(json.dumps(_semantic_receipt(r), sort_keys=True) for r in receipts_after)
    assert before == after


def test_arcs_verify_if_available_on_emitted_receipts(tmp_path):
    if shutil.which("arcs-verify") is None:
        pytest.skip("arcs-verify not installed; external verification skipped")

    _, emitter = _emitter(tmp_path / "verify")
    request = _request(tool_name="allow_capability")
    run_governed_action(
        request,
        config=_config(),
        receipt_context=_context(),
        executor=_CountingExecutor(result={"ok": True}),
        emitter=emitter,
    )
    keyring = tmp_path / "verify" / "issuer-keys.json"
    for path in (tmp_path / "verify").glob("urn_srs_receipt_*.json"):
        proc = subprocess.run(
            [
                "arcs-verify",
                str(path),
                "--keyring",
                str(keyring),
                "--profile",
                PROFILE,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
