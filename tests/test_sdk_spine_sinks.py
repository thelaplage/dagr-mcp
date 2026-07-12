from __future__ import annotations

from dataclasses import asdict

import pytest

from dagr_mcp.sdk_spine import (
    REVIEW_DECISION_OUTCOMES,
    REVIEW_OBJECT_STATES,
    EventEnvelope,
    GovernedArtifact,
    InMemoryArtifactSink,
    InMemoryEventSink,
    InMemoryLintFindingSink,
    InMemoryReceiptSink,
    InMemoryReviewObjectSink,
    LintFinding,
    ReceiptEnvelope,
    ReviewDecision,
    ReviewObject,
    SinkUnavailableError,
    capabilities_for_sink_type,
    is_review_decision_ref,
    normalize_actor_ref,
    normalize_review_decision_outcome,
    normalize_review_decision_ref,
    normalize_review_object_state,
    review_decision_ref_from_sink_ref,
    stable_payload_hash,
    validate_actor_ref,
)
from dagr_mcp.tool_call_disposition import timeout_decision_outcome


NOW = "2026-05-06T12:00:00Z"


def test_review_decision_ref_helpers_accept_sink_shapes() -> None:
    assert is_review_decision_ref("review_decision:file:1") is True
    assert is_review_decision_ref("review_decision:garp_local:42") is True
    assert normalize_review_decision_ref("review_decision:File:7") == "review_decision:file:7"
    assert review_decision_ref_from_sink_ref("review_decision:garp_local:3") == "review_decision:garp_local:3"


def test_review_decision_ref_helpers_reject_review_object_and_memory_refs() -> None:
    assert is_review_decision_ref("review_object:file:1") is False
    assert is_review_decision_ref("decision:1") is False
    assert is_review_decision_ref("") is False


def test_normalize_review_decision_ref_rejects_malformed() -> None:
    for bad in (
        "review_decision:file",
        "review_decision:file:x",
        "review_decision:file:0",
        "review_decision:file:01",
        "not_a_ref",
    ):
        with pytest.raises(ValueError, match="not a review_decision ref"):
            normalize_review_decision_ref(bad)


def _event(event_type: str = "mcp.tool.call.requested") -> EventEnvelope:
    return EventEnvelope(event_type=event_type, occurred_at=NOW)


def _receipt() -> ReceiptEnvelope:
    return ReceiptEnvelope(
        receipt_type="sdk_enforcement",
        boundary_type="mcp_tool_call",
        protocol_binding="mcp",
        issued_at=NOW,
        artifact_classes_covered=["metadata", "argument_hash", "result_hash"],
        artifact_classes_excluded=[
            "raw_prompt",
            "raw_output",
            "raw_tool_arguments",
            "raw_tool_result",
        ],
        attestation_limits=[
            "Receipt attests only to governance conditions at the harness boundary."
        ],
    )


def test_sink_health_shape_for_each_in_memory_sink() -> None:
    sinks = [
        (InMemoryEventSink(), "event"),
        (InMemoryReceiptSink(), "receipt"),
        (InMemoryArtifactSink(), "artifact"),
        (InMemoryReviewObjectSink(), "review_object"),
        (InMemoryLintFindingSink(), "lint_finding"),
    ]

    for sink, sink_type in sinks:
        health = sink.health()

        assert health.status == "available"
        assert health.sink_type == sink_type
        assert health.implementation == "memory"
        assert health.durability == "memory"
        assert health.writable is True
        assert health.readable is True
        assert health.checked_at.endswith("Z")
        assert health.degraded_reason is None
        assert health.last_error is None
        assert health.capabilities == capabilities_for_sink_type(
            health.sink_type, writable=True, readable=True
        )


def test_event_sink_writes_one_event_and_batch_events_with_stable_refs() -> None:
    sink = InMemoryEventSink()

    first_ref = sink.write_event(_event())
    batch_refs = sink.write_events(
        [_event("mcp.tool.call.executed"), _event("mcp.tool.call.failed")]
    )

    assert first_ref == "event:1"
    assert batch_refs == ["event:2", "event:3"]
    assert sink.events[first_ref].event_id == first_ref
    assert sink.events["event:2"].event_type == "mcp.tool.call.executed"


def test_receipt_sink_writes_and_verifies_known_receipt() -> None:
    sink = InMemoryReceiptSink()

    receipt_ref = sink.write_receipt(_receipt())
    result = sink.verify_receipt(receipt_ref)

    assert receipt_ref == "receipt:1"
    assert result.ok is True
    assert result.detail["receipt_ref"] == receipt_ref
    assert result.detail["cryptographic_verification"] == "not_implemented"


def test_receipt_sink_verify_missing_receipt_returns_not_ok() -> None:
    result = InMemoryReceiptSink().verify_receipt("receipt:missing")

    assert result.ok is False
    assert result.reason == "receipt_not_found"
    assert result.detail["cryptographic_verification"] == "not_applicable"


def test_in_memory_receipt_verify_fail_closed_when_sink_unavailable() -> None:
    sink = InMemoryReceiptSink()
    ref = sink.write_receipt(_receipt())
    sink.set_available(False)

    result = sink.verify_receipt(ref)

    assert result.ok is False
    assert result.reason == "receipt_sink_unavailable"


def test_artifact_sink_writes_reads_and_lists_artifact() -> None:
    sink = InMemoryArtifactSink()
    artifact = GovernedArtifact(
        artifact_type="source_claim_support_review_queue",
        created_at=NOW,
        private=True,
        required=True,
        optional_derived=False,
        payload_hash=stable_payload_hash({"claim": "supported"}),
    )

    artifact_ref = sink.write_artifact(artifact, {"claim": "supported"})
    read_back = sink.read_artifact(artifact_ref)

    assert artifact_ref == "artifact:1"
    assert read_back.artifact_ref == artifact_ref
    assert sink.list_artifacts() == [read_back]


def test_in_memory_review_object_sink_has_no_decision_lookup_helpers() -> None:
    sink = InMemoryReviewObjectSink()
    assert not hasattr(sink, "latest_decision_lookup")
    assert not hasattr(sink, "terminal_decision_lookup")


def test_review_object_sink_creates_pending_object_and_records_decision() -> None:
    sink = InMemoryReviewObjectSink()
    review_object = ReviewObject(
        review_object_type="tool_call_disposition",
        governance_state="pending",
        context_payload={"tool_name": "search"},
        allowed_actions=["approve", "reject", "defer"],
        created_at=NOW,
    )

    review_ref = sink.create_review_object(review_object)

    assert review_ref == "review:1"
    assert [obj.review_object_id for obj in sink.list_pending()] == [review_ref]

    decision_ref = sink.record_decision(
        review_ref,
        ReviewDecision(
            decision="approved",
            review_object_id=review_ref,
            decided_at=NOW,
            actor_ref="actor:test",
        ),
    )

    assert decision_ref == "decision:1"
    assert sink.list_pending() == []


def test_lint_finding_sink_writes_findings_and_summarizes_counts() -> None:
    sink = InMemoryLintFindingSink()
    findings = [
        LintFinding(rule_id="SR-08", severity="error", message="Missing source"),
        LintFinding(rule_id="AT-01", severity="warning", message="Attribution gap"),
        LintFinding(rule_id="SR-08", severity="error", message="Missing source"),
    ]

    batch_ref = sink.write_findings(findings)
    summary = sink.summarize()

    assert batch_ref == "lint_batch:1"
    assert summary["total"] == 3
    assert summary["by_severity"] == {"error": 2, "warning": 1}
    assert summary["by_rule_id"] == {"SR-08": 2, "AT-01": 1}
    assert summary["by_rule_family"] == {}


def test_unavailable_sink_raises_on_required_write() -> None:
    sink = InMemoryEventSink(available=False)

    with pytest.raises(SinkUnavailableError):
        sink.write_event(_event())

    health = sink.health()
    assert health.status == "unavailable"
    assert health.writable is False
    assert health.readable is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("pending", "pending"),
        ("PENDING", "pending"),
        ("deferred", "deferred"),
        ("Deferred", "deferred"),
        ("approved", "approved"),
        ("rejected", "rejected"),
        ("expired", "expired"),
        ("in_review", "pending"),
        ("escalated", "pending"),
    ],
)
def test_normalize_review_object_state_accepts_canonical_and_aliases(
    raw: str, expected: str
) -> None:
    assert normalize_review_object_state(raw) == expected


def test_normalize_review_object_state_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown review object governance_state"):
        normalize_review_object_state("banana")


@pytest.mark.parametrize("raw", sorted(REVIEW_DECISION_OUTCOMES))
def test_normalize_review_decision_outcome_accepts_canonical(raw: str) -> None:
    assert normalize_review_decision_outcome(raw) == raw


@pytest.mark.parametrize("raw", ["APPROVED", "Rejected"])
def test_normalize_review_decision_outcome_is_case_insensitive(raw: str) -> None:
    assert normalize_review_decision_outcome(raw) == raw.lower()


def test_normalize_review_decision_outcome_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown review decision outcome"):
        normalize_review_decision_outcome("banana")


def test_in_memory_review_sink_rejects_invalid_governance_state_on_create() -> None:
    sink = InMemoryReviewObjectSink()
    bad = ReviewObject(
        review_object_type="tool_call_disposition",
        governance_state="not_a_state",
        context_payload={},
        allowed_actions=["approve"],
        created_at=NOW,
    )
    with pytest.raises(ValueError, match="unknown review object governance_state"):
        sink.create_review_object(bad)


def test_in_memory_review_sink_normalizes_legacy_escalated_on_create() -> None:
    sink = InMemoryReviewObjectSink()
    obj = ReviewObject(
        review_object_type="t",
        governance_state="escalated",
        context_payload={},
        allowed_actions=[],
        created_at=NOW,
    )
    ref = sink.create_review_object(obj)
    assert sink.review_objects[ref].governance_state == "pending"


def test_in_memory_review_sink_record_decision_rejects_invalid_outcome() -> None:
    sink = InMemoryReviewObjectSink()
    ref = sink.create_review_object(
        ReviewObject(
            review_object_type="tool_call_disposition",
            governance_state="pending",
            context_payload={"tool_name": "search"},
            allowed_actions=["approve", "reject", "defer"],
            created_at=NOW,
        )
    )
    with pytest.raises(ValueError, match="unknown review decision outcome"):
        sink.record_decision(
            ref,
            ReviewDecision(
                decision="approved_pending",
                review_object_id=ref,
                decided_at=NOW,
            ),
        )


@pytest.mark.parametrize("outcome", sorted(REVIEW_DECISION_OUTCOMES))
def test_in_memory_review_sink_record_decision_accepts_outcomes(outcome: str) -> None:
    sink = InMemoryReviewObjectSink()
    ref = sink.create_review_object(
        ReviewObject(
            review_object_type="tool_call_disposition",
            governance_state="pending",
            context_payload={},
            allowed_actions=[],
            created_at=NOW,
        )
    )
    sink.record_decision(
        ref,
        ReviewDecision(decision=outcome, review_object_id=ref, decided_at=NOW),
    )
    assert sink.review_objects[ref].governance_state == outcome
    assert sink.list_pending() == []


def test_deferred_decision_closes_pending_queue_entry() -> None:
    sink = InMemoryReviewObjectSink()
    ref = sink.create_review_object(
        ReviewObject(
            review_object_type="tool_call_disposition",
            governance_state="pending",
            context_payload={},
            allowed_actions=[],
            created_at=NOW,
        )
    )
    assert len(sink.list_pending()) == 1
    sink.record_decision(
        ref,
        ReviewDecision(decision="deferred", review_object_id=ref, decided_at=NOW),
    )
    assert sink.list_pending() == []


def test_review_object_states_constant_matches_public_contract() -> None:
    assert REVIEW_OBJECT_STATES == {
        "pending",
        "approved",
        "rejected",
        "deferred",
        "expired",
    }


def test_stable_payload_hash_is_deterministic_for_dict_key_order() -> None:
    first = {"b": 2, "a": {"d": 4, "c": 3}}
    second = {"a": {"c": 3, "d": 4}, "b": 2}

    assert stable_payload_hash(first) == stable_payload_hash(second)


def test_receipt_envelope_does_not_require_raw_payload() -> None:
    receipt = _receipt()

    assert "payload" not in asdict(receipt)
    assert receipt.extensions == {}


def test_normalize_actor_ref_accepts_allowed_prefixes() -> None:
    assert normalize_actor_ref("local_operator:alice.v1") == "local_operator:alice.v1"
    assert normalize_actor_ref("Delegated_Agent:bot-01") == "delegated_agent:bot-01"
    assert normalize_actor_ref("service_account:ci_runner") == "service_account:ci_runner"
    assert (
        normalize_actor_ref("external_reviewer:partner_org.auditor")
        == "external_reviewer:partner_org.auditor"
    )


def test_normalize_actor_ref_rejects_unknown_prefix() -> None:
    with pytest.raises(ValueError, match="unknown actor_ref prefix"):
        normalize_actor_ref("admin:root")


def test_normalize_actor_ref_rejects_whitespace_and_email_like() -> None:
    with pytest.raises(ValueError, match="whitespace"):
        normalize_actor_ref("local_operator: bad")
    with pytest.raises(ValueError, match="email"):
        normalize_actor_ref("local_operator:user@example.com")


def test_validate_actor_ref_required_flag() -> None:
    assert validate_actor_ref(None, required=False) is None
    with pytest.raises(ValueError, match="required"):
        validate_actor_ref(None, required=True)
    assert validate_actor_ref("local_operator:x", required=False) == "local_operator:x"


def test_timeout_decision_outcome_is_valid_review_decision_outcome() -> None:
    assert normalize_review_decision_outcome(timeout_decision_outcome()) == "expired"
