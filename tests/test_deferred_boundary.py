"""Tests for the deferred tool boundary and resume binding (W2-03).

Acceptance gates verified here:
* Deferred calls spawn zero child processes (inner is never called from defer_call).
* Only a later admitted reevaluation may execute.
* Replay cannot execute twice (terminal-state protection).
* Wrong-actor: decision actor_ref mismatch is refused.
* Changed-args: digest mismatch at resume is refused.
* Stale response: decision.decided_at before slot.created_at is refused.
* Timeout: elapsed gate_timeout_seconds is refused before execution.
* Refusal: rejected decision does not execute.
* Admission: approved + matching args → inner executes exactly once, result returned.
* Execution failure: inner raises → DeferredExecutionFailureError, slot refused.
* Review object is created in the sink at defer time.
* Pending slots list is accurate.
* Slot not found: resume against unknown correlation_ref raises.
* deferred decision keeps slot pending (no execution).
"""

from __future__ import annotations

import time
import threading
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

import pytest

from dagr_mcp.deferred_boundary import (
    DeferralResult,
    DeferredActorMismatchError,
    DeferredArgumentMismatchError,
    DeferredBoundary,
    DeferredExecutionFailureError,
    DeferredReviewObjectSinkError,
    DeferredSlot,
    DeferredSlotNotFoundError,
    DeferredSlotTerminalError,
    DeferredStaleResponseError,
    DeferredTimeoutError,
    ResumeResult,
    make_deferred_boundary,
    make_review_decision,
)
from dagr_mcp.sdk_spine import (
    InMemoryEventSink,
    InMemoryReviewObjectSink,
    ReviewDecision,
    SinkReadError,
    now_utc_iso,
)
from dagr_mcp.tool_call_disposition import hash_tool_call_arguments


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


ARGS = {"param": "value", "count": 3}
TOOL_NAME = "do_something"


def _make_boundary(inner=None, *, review_sink=None, event_sink=None):
    return make_deferred_boundary(inner, review_sink=review_sink, event_sink=event_sink)


def _later_timestamp(base: str, seconds: float = 1.0) -> str:
    """Return an ISO timestamp *seconds* after *base*."""
    dt = datetime.fromisoformat(base.replace("Z", "+00:00")) + timedelta(seconds=seconds)
    return dt.isoformat().replace("+00:00", "Z")


def _earlier_timestamp(base: str, seconds: float = 10.0) -> str:
    """Return an ISO timestamp *seconds* before *base*."""
    dt = datetime.fromisoformat(base.replace("Z", "+00:00")) - timedelta(seconds=seconds)
    return dt.isoformat().replace("+00:00", "Z")


class _CountingInner:
    """Inner handler that counts calls and returns a fixed result."""

    def __init__(self, result=None, raise_exc=None):
        self.call_count = 0
        self._result = result or {"executed": True}
        self._raise = raise_exc

    def __call__(self, tool_name: str, arguments: Any) -> Any:
        self.call_count += 1
        if self._raise is not None:
            raise self._raise
        return self._result


class _FailingReviewSink:
    """Review sink whose create_review_object always fails."""

    def create_review_object(self, review_object) -> str:
        raise RuntimeError("sink exploded")

    def record_decision(self, review_object_id, decision):
        raise RuntimeError("sink exploded")

    def list_pending(self, review_object_type=None):
        return []

    def health(self):
        from dagr_mcp.sdk_spine import make_sink_health, SINK_TYPE_REVIEW_OBJECT
        return make_sink_health(sink_type=SINK_TYPE_REVIEW_OBJECT, available=False)

    def supports_capability(self, capability):
        return False


# ---------------------------------------------------------------------------
# 1. defer_call spawns ZERO child invocations
# ---------------------------------------------------------------------------


class TestDeferCallNoExecution:
    def test_inner_is_never_called_from_defer_call(self):
        inner = _CountingInner()
        boundary = _make_boundary(inner)
        boundary.defer_call(TOOL_NAME, ARGS)
        assert inner.call_count == 0, "inner must not be called during defer_call"

    def test_defer_returns_deferral_result(self):
        boundary = _make_boundary()
        result = boundary.defer_call(TOOL_NAME, ARGS)
        assert isinstance(result, DeferralResult)

    def test_defer_result_has_stable_correlation_ref(self):
        boundary = _make_boundary()
        r1 = boundary.defer_call(TOOL_NAME, ARGS)
        r2 = boundary.defer_call(TOOL_NAME, ARGS)
        assert r1.correlation_ref != r2.correlation_ref

    def test_defer_result_has_argument_digest(self):
        boundary = _make_boundary()
        result = boundary.defer_call(TOOL_NAME, ARGS)
        expected = hash_tool_call_arguments(ARGS)
        assert result.argument_digest == expected

    def test_defer_result_has_review_object_ref(self):
        boundary = _make_boundary()
        result = boundary.defer_call(TOOL_NAME, ARGS)
        assert result.review_object_ref is not None
        assert len(result.review_object_ref) > 0

    def test_slot_is_pending_after_defer(self):
        boundary = _make_boundary()
        result = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(result.correlation_ref)
        assert slot is not None
        assert slot.state == "pending"

    def test_slot_argument_digest_is_immutable(self):
        boundary = _make_boundary()
        result = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(result.correlation_ref)
        assert slot.argument_digest == result.argument_digest

    def test_review_object_created_in_sink(self):
        review_sink = InMemoryReviewObjectSink()
        boundary = _make_boundary(review_sink=review_sink)
        result = boundary.defer_call(TOOL_NAME, ARGS)
        pending = review_sink.list_pending()
        assert any(
            ro.review_object_id == result.review_object_ref for ro in pending
        ), "review object must be in the sink after defer"

    def test_pending_slots_list_reflects_deferred_slots(self):
        boundary = _make_boundary()
        r1 = boundary.defer_call(TOOL_NAME, ARGS)
        r2 = boundary.defer_call("another_tool", {"x": 1})
        pending = boundary.pending_slots()
        refs = {s.correlation_ref for s in pending}
        assert r1.correlation_ref in refs
        assert r2.correlation_ref in refs

    def test_defer_with_non_mapping_arguments_raises(self):
        boundary = _make_boundary()
        with pytest.raises(Exception):
            boundary.defer_call(TOOL_NAME, ["not", "a", "mapping"])

    def test_review_sink_failure_raises_deferred_review_object_sink_error(self):
        boundary = make_deferred_boundary(review_sink=_FailingReviewSink())
        with pytest.raises(DeferredReviewObjectSinkError):
            boundary.defer_call(TOOL_NAME, ARGS)


# ---------------------------------------------------------------------------
# 2. Admission path: approved decision + correct args → executes exactly once
# ---------------------------------------------------------------------------


class TestResumeAdmitted:
    def test_admitted_resume_executes_inner(self):
        inner = _CountingInner()
        boundary = _make_boundary(inner)
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref, decision="approved")
        resume = boundary.resume_call(dr.correlation_ref, dec, ARGS)
        assert inner.call_count == 1

    def test_admitted_resume_returns_inner_result(self):
        inner = _CountingInner(result={"answer": 42})
        boundary = _make_boundary(inner)
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref)
        resume = boundary.resume_call(dr.correlation_ref, dec, ARGS)
        assert resume.result == {"answer": 42}
        assert resume.state == "admitted"
        assert resume.failure_reason is None

    def test_admitted_slot_is_terminal(self):
        boundary = _make_boundary()
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref)
        boundary.resume_call(dr.correlation_ref, dec, ARGS)
        updated_slot = boundary.get_slot(dr.correlation_ref)
        assert updated_slot.state == "admitted"

    def test_admitted_slot_removed_from_pending(self):
        boundary = _make_boundary()
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref)
        boundary.resume_call(dr.correlation_ref, dec, ARGS)
        pending = boundary.pending_slots()
        assert all(s.correlation_ref != dr.correlation_ref for s in pending)


# ---------------------------------------------------------------------------
# 3. Replay protection: terminal slot cannot execute twice
# ---------------------------------------------------------------------------


class TestReplayProtection:
    def test_replay_approved_raises_terminal_error(self):
        inner = _CountingInner()
        boundary = _make_boundary(inner)
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref)
        boundary.resume_call(dr.correlation_ref, dec, ARGS)
        assert inner.call_count == 1
        # Second resume attempt must fail
        dec2 = make_review_decision(slot.review_object_ref)
        with pytest.raises(DeferredSlotTerminalError):
            boundary.resume_call(dr.correlation_ref, dec2, ARGS)
        assert inner.call_count == 1, "inner must not be called a second time"

    def test_replay_refused_raises_terminal_error(self):
        boundary = _make_boundary()
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref, decision="rejected")
        boundary.resume_call(dr.correlation_ref, dec, ARGS)
        dec2 = make_review_decision(slot.review_object_ref, decision="approved")
        with pytest.raises(DeferredSlotTerminalError):
            boundary.resume_call(dr.correlation_ref, dec2, ARGS)

    def test_replay_expired_raises_terminal_error(self):
        boundary = _make_boundary()
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref, decision="expired")
        boundary.resume_call(dr.correlation_ref, dec, ARGS)
        dec2 = make_review_decision(slot.review_object_ref, decision="approved")
        with pytest.raises(DeferredSlotTerminalError):
            boundary.resume_call(dr.correlation_ref, dec2, ARGS)


# ---------------------------------------------------------------------------
# 4. Wrong-actor sentinel
# ---------------------------------------------------------------------------


class TestWrongActor:
    def test_second_resume_different_actor_raises(self):
        """After a first approved resume with actor_ref=A, a second (replay) attempt
        with actor_ref=B must fail with DeferredSlotTerminalError (replay), not proceed.
        The actor-mismatch check only applies within a single admitted resume attempt
        where the slot records a previous decision actor that differs from the new one.
        """
        inner = _CountingInner()
        boundary = _make_boundary(inner)
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)

        dec1 = make_review_decision(
            slot.review_object_ref,
            decision="approved",
            actor_ref="local_operator:alice",
        )
        boundary.resume_call(dr.correlation_ref, dec1, ARGS)
        assert inner.call_count == 1

        dec2 = make_review_decision(
            slot.review_object_ref,
            decision="approved",
            actor_ref="local_operator:bob",
        )
        # Replay protection fires before actor check
        with pytest.raises(DeferredSlotTerminalError):
            boundary.resume_call(dr.correlation_ref, dec2, ARGS)
        assert inner.call_count == 1

    def test_actor_ref_mismatch_within_resume_when_final_decision_recorded(self):
        """Simulate a scenario where the slot already has a final_decision recorded
        with actor_ref=alice, and a new resume arrives with actor_ref=bob.
        The boundary must refuse with DeferredActorMismatchError (not execute).
        """
        # We manually pre-set the final_decision to simulate a scenario where
        # a pending slot has a provisional decision recorded.
        inner = _CountingInner()
        boundary = _make_boundary(inner)
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)

        # Inject a provisional final_decision with actor_ref=alice
        slot.final_decision = ReviewDecision(
            decision="approved",
            review_object_id=slot.review_object_ref,
            decided_at=now_utc_iso(),
            actor_ref="local_operator:alice",
        )

        dec = make_review_decision(
            slot.review_object_ref,
            decision="approved",
            actor_ref="local_operator:bob",  # mismatched
        )
        with pytest.raises(DeferredActorMismatchError):
            boundary.resume_call(dr.correlation_ref, dec, ARGS)
        assert inner.call_count == 0


# ---------------------------------------------------------------------------
# 5. Changed-args sentinel
# ---------------------------------------------------------------------------


class TestChangedArgs:
    def test_different_args_at_resume_raises(self):
        inner = _CountingInner()
        boundary = _make_boundary(inner)
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref, decision="approved")
        different_args = {"param": "different_value", "count": 99}
        with pytest.raises(DeferredArgumentMismatchError):
            boundary.resume_call(dr.correlation_ref, dec, different_args)
        assert inner.call_count == 0

    def test_arg_mismatch_sets_slot_refused(self):
        boundary = _make_boundary()
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref, decision="approved")
        with pytest.raises(DeferredArgumentMismatchError):
            boundary.resume_call(dr.correlation_ref, dec, {"wrong": "args"})
        updated = boundary.get_slot(dr.correlation_ref)
        assert updated.state == "refused"

    def test_arg_mismatch_does_not_allow_retry_with_correct_args(self):
        """After a mismatch refuses the slot, a subsequent resume with correct args
        must fail with DeferredSlotTerminalError (slot is already terminal/refused)."""
        inner = _CountingInner()
        boundary = _make_boundary(inner)
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref, decision="approved")
        with pytest.raises(DeferredArgumentMismatchError):
            boundary.resume_call(dr.correlation_ref, dec, {"wrong": "args"})
        dec2 = make_review_decision(slot.review_object_ref, decision="approved")
        with pytest.raises(DeferredSlotTerminalError):
            boundary.resume_call(dr.correlation_ref, dec2, ARGS)
        assert inner.call_count == 0


# ---------------------------------------------------------------------------
# 6. Stale-response sentinel
# ---------------------------------------------------------------------------


class TestStaleResponse:
    def test_decided_at_before_created_at_raises(self):
        boundary = _make_boundary()
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        stale_decided_at = _earlier_timestamp(slot.created_at, seconds=30)
        dec = ReviewDecision(
            decision="approved",
            review_object_id=slot.review_object_ref,
            decided_at=stale_decided_at,
        )
        with pytest.raises(DeferredStaleResponseError):
            boundary.resume_call(dr.correlation_ref, dec, ARGS)

    def test_stale_response_does_not_execute_inner(self):
        inner = _CountingInner()
        boundary = _make_boundary(inner)
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        stale_decided_at = _earlier_timestamp(slot.created_at, seconds=5)
        dec = ReviewDecision(
            decision="approved",
            review_object_id=slot.review_object_ref,
            decided_at=stale_decided_at,
        )
        with pytest.raises(DeferredStaleResponseError):
            boundary.resume_call(dr.correlation_ref, dec, ARGS)
        assert inner.call_count == 0

    def test_decided_at_equal_to_created_at_is_accepted(self):
        """decided_at == created_at is NOT stale (boundary is inclusive)."""
        boundary = _make_boundary()
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = ReviewDecision(
            decision="approved",
            review_object_id=slot.review_object_ref,
            decided_at=slot.created_at,  # exactly equal
        )
        result = boundary.resume_call(dr.correlation_ref, dec, ARGS)
        assert result.state == "admitted"


# ---------------------------------------------------------------------------
# 7. Timeout sentinel
# ---------------------------------------------------------------------------


class TestTimeout:
    def test_elapsed_gate_timeout_raises(self):
        boundary = _make_boundary()
        # Use gate_timeout_seconds=1; then sleep slightly more than 1s
        dr = boundary.defer_call(TOOL_NAME, ARGS, gate_timeout_seconds=1)
        time.sleep(1.05)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref, decision="approved")
        with pytest.raises(DeferredTimeoutError):
            boundary.resume_call(dr.correlation_ref, dec, ARGS)

    def test_timeout_sets_slot_expired(self):
        boundary = _make_boundary()
        dr = boundary.defer_call(TOOL_NAME, ARGS, gate_timeout_seconds=1)
        time.sleep(1.05)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref, decision="approved")
        with pytest.raises(DeferredTimeoutError):
            boundary.resume_call(dr.correlation_ref, dec, ARGS)
        updated = boundary.get_slot(dr.correlation_ref)
        assert updated.state == "expired"

    def test_timeout_does_not_execute_inner(self):
        inner = _CountingInner()
        boundary = _make_boundary(inner)
        dr = boundary.defer_call(TOOL_NAME, ARGS, gate_timeout_seconds=1)
        time.sleep(1.05)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref, decision="approved")
        with pytest.raises(DeferredTimeoutError):
            boundary.resume_call(dr.correlation_ref, dec, ARGS)
        assert inner.call_count == 0

    def test_within_timeout_is_accepted(self):
        inner = _CountingInner()
        boundary = _make_boundary(inner)
        dr = boundary.defer_call(TOOL_NAME, ARGS, gate_timeout_seconds=30)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref, decision="approved")
        result = boundary.resume_call(dr.correlation_ref, dec, ARGS)
        assert result.state == "admitted"
        assert inner.call_count == 1

    def test_expired_timeout_is_terminal(self):
        boundary = _make_boundary()
        dr = boundary.defer_call(TOOL_NAME, ARGS, gate_timeout_seconds=1)
        time.sleep(1.05)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref, decision="approved")
        with pytest.raises(DeferredTimeoutError):
            boundary.resume_call(dr.correlation_ref, dec, ARGS)
        dec2 = make_review_decision(slot.review_object_ref, decision="approved")
        with pytest.raises(DeferredSlotTerminalError):
            boundary.resume_call(dr.correlation_ref, dec2, ARGS)


# ---------------------------------------------------------------------------
# 8. Refusal path: rejected decision does not execute
# ---------------------------------------------------------------------------


class TestRefusal:
    def test_rejected_decision_does_not_execute_inner(self):
        inner = _CountingInner()
        boundary = _make_boundary(inner)
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref, decision="rejected")
        result = boundary.resume_call(dr.correlation_ref, dec, ARGS)
        assert inner.call_count == 0
        assert result.state == "refused"
        assert result.result is None

    def test_rejected_slot_is_terminal(self):
        boundary = _make_boundary()
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref, decision="rejected")
        boundary.resume_call(dr.correlation_ref, dec, ARGS)
        updated = boundary.get_slot(dr.correlation_ref)
        assert updated.state == "refused"

    def test_expired_decision_does_not_execute_inner(self):
        inner = _CountingInner()
        boundary = _make_boundary(inner)
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref, decision="expired")
        result = boundary.resume_call(dr.correlation_ref, dec, ARGS)
        assert inner.call_count == 0
        assert result.state == "expired"


# ---------------------------------------------------------------------------
# 9. Execution failure: inner raises → DeferredExecutionFailureError
# ---------------------------------------------------------------------------


class TestExecutionFailure:
    def test_inner_exception_raises_deferred_execution_failure(self):
        inner = _CountingInner(raise_exc=ValueError("boom"))
        boundary = _make_boundary(inner)
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref, decision="approved")
        with pytest.raises(DeferredExecutionFailureError):
            boundary.resume_call(dr.correlation_ref, dec, ARGS)

    def test_inner_exception_sets_slot_refused(self):
        inner = _CountingInner(raise_exc=RuntimeError("inner failed"))
        boundary = _make_boundary(inner)
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref, decision="approved")
        with pytest.raises(DeferredExecutionFailureError):
            boundary.resume_call(dr.correlation_ref, dec, ARGS)
        updated = boundary.get_slot(dr.correlation_ref)
        assert updated.state == "refused"
        assert updated.failure_reason == "inner_execution_failure"

    def test_inner_exception_prevents_replay(self):
        inner = _CountingInner(raise_exc=RuntimeError("boom"))
        boundary = _make_boundary(inner)
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref, decision="approved")
        with pytest.raises(DeferredExecutionFailureError):
            boundary.resume_call(dr.correlation_ref, dec, ARGS)
        dec2 = make_review_decision(slot.review_object_ref, decision="approved")
        with pytest.raises(DeferredSlotTerminalError):
            boundary.resume_call(dr.correlation_ref, dec2, ARGS)


# ---------------------------------------------------------------------------
# 10. Slot not found
# ---------------------------------------------------------------------------


class TestSlotNotFound:
    def test_resume_unknown_correlation_ref_raises(self):
        boundary = _make_boundary()
        dec = make_review_decision("review:1", decision="approved")
        with pytest.raises(DeferredSlotNotFoundError):
            boundary.resume_call("deferred:does-not-exist", dec, ARGS)

    def test_get_slot_unknown_ref_returns_none(self):
        boundary = _make_boundary()
        assert boundary.get_slot("deferred:nonexistent") is None


# ---------------------------------------------------------------------------
# 11. deferred decision keeps slot pending
# ---------------------------------------------------------------------------


class TestDeferredDecision:
    def test_deferred_outcome_keeps_slot_pending(self):
        inner = _CountingInner()
        boundary = _make_boundary(inner)
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref, decision="deferred")
        result = boundary.resume_call(dr.correlation_ref, dec, ARGS)
        assert inner.call_count == 0
        assert result.state == "pending"
        updated = boundary.get_slot(dr.correlation_ref)
        assert updated.state == "pending"

    def test_deferred_then_approved_executes(self):
        inner = _CountingInner()
        boundary = _make_boundary(inner)
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)

        dec_defer = make_review_decision(slot.review_object_ref, decision="deferred")
        boundary.resume_call(dr.correlation_ref, dec_defer, ARGS)
        assert inner.call_count == 0

        dec_approve = make_review_decision(slot.review_object_ref, decision="approved")
        result = boundary.resume_call(dr.correlation_ref, dec_approve, ARGS)
        assert inner.call_count == 1
        assert result.state == "admitted"


# ---------------------------------------------------------------------------
# 12. Event sink integration
# ---------------------------------------------------------------------------


class TestEventSink:
    def test_defer_writes_event(self):
        event_sink = InMemoryEventSink()
        boundary = make_deferred_boundary(event_sink=event_sink)
        boundary.defer_call(TOOL_NAME, ARGS)
        events = list(event_sink.events.values())
        event_types = [e.event_type for e in events]
        assert "mcp.tool.call.deferred" in event_types

    def test_admitted_resume_writes_executed_event(self):
        event_sink = InMemoryEventSink()
        boundary = make_deferred_boundary(event_sink=event_sink)
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref, decision="approved")
        boundary.resume_call(dr.correlation_ref, dec, ARGS)
        events = list(event_sink.events.values())
        event_types = [e.event_type for e in events]
        assert "mcp.tool.call.executed" in event_types

    def test_rejected_resume_writes_rejected_event(self):
        event_sink = InMemoryEventSink()
        boundary = make_deferred_boundary(event_sink=event_sink)
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref, decision="rejected")
        boundary.resume_call(dr.correlation_ref, dec, ARGS)
        events = list(event_sink.events.values())
        event_types = [e.event_type for e in events]
        assert "mcp.tool.call.rejected" in event_types


# ---------------------------------------------------------------------------
# 13. Receipt cardinality alignment with SRS profile
# ---------------------------------------------------------------------------


class TestReceiptCardinality:
    """Verify the receipt-gap / cardinality contract described in the module doc."""

    def test_deferred_slot_has_no_outcome_receipt(self):
        """A freshly deferred slot should produce at most an admission receipt,
        never an outcome receipt -- RECEIPT_CARDINALITY["deferred"] == 1."""
        boundary = _make_boundary()
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        assert slot.outcome_receipt_ref is None

    def test_refused_slot_has_no_outcome_receipt(self):
        boundary = _make_boundary()
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref, decision="rejected")
        result = boundary.resume_call(dr.correlation_ref, dec, ARGS)
        assert result.outcome_receipt_ref is None

    def test_admitted_slot_result_fields_populated(self):
        """After admission the result is present and slot is terminal."""
        inner = _CountingInner(result={"value": 7})
        boundary = _make_boundary(inner)
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)
        dec = make_review_decision(slot.review_object_ref, decision="approved")
        result = boundary.resume_call(dr.correlation_ref, dec, ARGS)
        assert result.result == {"value": 7}
        updated = boundary.get_slot(dr.correlation_ref)
        assert updated.result == {"value": 7}


# ---------------------------------------------------------------------------
# 14. Thread safety: two concurrent resumes on different slots
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_resumes_on_different_slots_both_succeed(self):
        results: list[ResumeResult] = []
        errors: list[Exception] = []

        inner = _CountingInner()
        boundary = _make_boundary(inner)

        dr1 = boundary.defer_call("tool_a", {"x": 1})
        dr2 = boundary.defer_call("tool_b", {"x": 2})

        slot1 = boundary.get_slot(dr1.correlation_ref)
        slot2 = boundary.get_slot(dr2.correlation_ref)

        def do_resume(cr, review_id, args):
            try:
                dec = make_review_decision(review_id, decision="approved")
                r = boundary.resume_call(cr, dec, args)
                results.append(r)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(
            target=do_resume,
            args=(dr1.correlation_ref, slot1.review_object_ref, {"x": 1}),
        )
        t2 = threading.Thread(
            target=do_resume,
            args=(dr2.correlation_ref, slot2.review_object_ref, {"x": 2}),
        )
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert not errors, f"concurrent resume errors: {errors}"
        assert len(results) == 2
        assert all(r.state == "admitted" for r in results)
        assert inner.call_count == 2

    def test_concurrent_replay_on_same_slot_only_one_succeeds(self):
        """Two concurrent resumes on the SAME slot: exactly one must succeed
        and the other must raise DeferredSlotTerminalError (replay protection)."""
        successes: list[ResumeResult] = []
        terminal_errors: list[DeferredSlotTerminalError] = []
        other_errors: list[Exception] = []

        inner = _CountingInner()
        barrier = threading.Barrier(2)
        boundary = _make_boundary(inner)

        dr = boundary.defer_call(TOOL_NAME, ARGS)
        slot = boundary.get_slot(dr.correlation_ref)

        def do_resume():
            dec = make_review_decision(slot.review_object_ref, decision="approved")
            barrier.wait()  # Start both threads at the same time
            try:
                r = boundary.resume_call(dr.correlation_ref, dec, ARGS)
                successes.append(r)
            except DeferredSlotTerminalError as e:
                terminal_errors.append(e)
            except Exception as e:
                other_errors.append(e)

        t1 = threading.Thread(target=do_resume)
        t2 = threading.Thread(target=do_resume)
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert not other_errors, f"unexpected errors: {other_errors}"
        assert len(successes) == 1, "exactly one resume must succeed"
        assert len(terminal_errors) == 1, "exactly one replay must be refused"
        assert inner.call_count == 1, "inner must execute exactly once"


# ---------------------------------------------------------------------------
# 15. make_review_decision helper
# ---------------------------------------------------------------------------


class TestMakeReviewDecision:
    def test_defaults_to_approved(self):
        dec = make_review_decision("review:1")
        assert dec.decision == "approved"

    def test_custom_decision(self):
        dec = make_review_decision("review:1", decision="rejected")
        assert dec.decision == "rejected"

    def test_actor_ref_propagated(self):
        dec = make_review_decision("review:1", actor_ref="local_operator:alice")
        assert dec.actor_ref == "local_operator:alice"

    def test_decided_at_is_set(self):
        dec = make_review_decision("review:1")
        # Should be a valid ISO timestamp
        dt = datetime.fromisoformat(dec.decided_at.replace("Z", "+00:00"))
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# 16. Profile and correlation ref format
# ---------------------------------------------------------------------------


class TestCorrelationRef:
    def test_correlation_ref_starts_with_deferred(self):
        boundary = _make_boundary()
        dr = boundary.defer_call(TOOL_NAME, ARGS)
        assert dr.correlation_ref.startswith("deferred:")

    def test_correlation_refs_are_unique(self):
        boundary = _make_boundary()
        refs = {boundary.defer_call(TOOL_NAME, ARGS).correlation_ref for _ in range(20)}
        assert len(refs) == 20


# ---------------------------------------------------------------------------
# 17. Full end-to-end: defer → (stale attempt) → (timeout check) → admit
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_full_defer_admit_cycle(self):
        """Canonical happy path: defer → stale rejected → correct admit."""
        inner = _CountingInner(result={"final": True})
        event_sink = InMemoryEventSink()
        review_sink = InMemoryReviewObjectSink()
        boundary = DeferredBoundary(
            inner, event_sink=event_sink, review_sink=review_sink
        )

        # 1. Defer
        dr = boundary.defer_call(TOOL_NAME, ARGS, gate_timeout_seconds=60)
        assert boundary.get_slot(dr.correlation_ref).state == "pending"
        assert inner.call_count == 0

        # 2. Verify review object created
        pending_ros = review_sink.list_pending()
        assert any(ro.review_object_id == dr.review_object_ref for ro in pending_ros)

        # 3. Stale decision rejected
        slot = boundary.get_slot(dr.correlation_ref)
        stale_dec = ReviewDecision(
            decision="approved",
            review_object_id=dr.review_object_ref,
            decided_at=_earlier_timestamp(slot.created_at, 60),
        )
        with pytest.raises(DeferredStaleResponseError):
            boundary.resume_call(dr.correlation_ref, stale_dec, ARGS)
        assert inner.call_count == 0
        assert boundary.get_slot(dr.correlation_ref).state == "pending"

        # 4. Valid admit
        dec = make_review_decision(dr.review_object_ref, decision="approved")
        result = boundary.resume_call(dr.correlation_ref, dec, ARGS)
        assert result.state == "admitted"
        assert result.result == {"final": True}
        assert inner.call_count == 1

        # 5. Verify events
        event_types = [e.event_type for e in event_sink.events.values()]
        assert "mcp.tool.call.deferred" in event_types
        assert "mcp.tool.call.executed" in event_types
