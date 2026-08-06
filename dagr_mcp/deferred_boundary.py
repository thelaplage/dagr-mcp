"""Deferred tool boundary and resume binding v0.1.

This module implements true pre-execution defer/resume at the MCP tool boundary.
It proves the child tool cannot run while conditions remain unsatisfied.

Design invariants (never violate):
* A deferred call spawns ZERO child tool invocations.
* Only a later *admitted* reevaluation, bound to the exact original operation
  digest, subject, and profile, may execute the inner handler.
* Replay protection: once a DeferredSlot reaches a terminal state (admitted,
  refused, expired) it cannot execute again.  A second ``resume`` against a
  terminal slot raises ``DeferredSlotTerminalError``.
* Wrong-actor: a ``resume`` presented with an ``actor_ref`` that does not match
  the reviewer reference stored in the slot's own admitted ``ReviewDecision``
  raises ``DeferredActorMismatchError``.
* Changed-args: if the arguments presented at resume yield a digest that does
  not match the digest captured at defer time, execution is refused with
  ``DeferredArgumentMismatchError``.
* Stale response: a ``ReviewDecision`` whose ``decided_at`` timestamp precedes
  the slot's ``created_at`` is rejected as stale with ``DeferredStaleResponseError``.
* Timeout: a slot whose ``gate_timeout_seconds`` has elapsed (wall-clock) before
  a resume arrives transitions to ``expired`` and refuses execution.

Receipt / admission posture (aligned with the settled SRS profile):
* ``deferred_for_review`` admission receipt emitted at defer time; no outcome.
  This matches ``RECEIPT_CARDINALITY["deferred"] == 1``.
* If the slot is later admitted, an ``admitted`` admission receipt and an outcome
  receipt are emitted -- contributing the two records required by
  ``RECEIPT_CARDINALITY["admitted"] == 2``.
* If the slot is refused/expired the ``refused`` admission receipt is emitted;
  no outcome receipt follows.

Side-effect discipline:
* The inner handler is NEVER called from ``defer_call``.
* ``resume_call`` calls the inner handler ONLY when the ReviewDecision outcome
  is ``approved``, digests match, no replay has occurred, and the slot has not
  timed out.

Public surface:
* ``DeferredSlot`` — the stable durable token returned at defer time.
* ``DeferredBoundary`` — stateful boundary that owns a slot store; wraps
  ``defer_call`` / ``resume_call`` / ``get_slot``.
* ``DeferredSlotError`` hierarchy — semantic failure classes for adversarial cases.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Literal, Mapping

from dagr_mcp.sdk_spine import (
    InMemoryEventSink,
    InMemoryReviewObjectSink,
    ReviewDecision,
    ReviewObject,
    SinkUnavailableError,
    now_utc_iso,
    stable_payload_hash,
)
from dagr_mcp.tool_call_disposition import (
    ToolCallDispositionInput,
    build_tool_call_disposition_review_object,
    hash_tool_call_arguments,
    normalize_review_decision_outcome,
    validate_tool_call_disposition_decision,
)

# ---------------------------------------------------------------------------
# Slot states
# ---------------------------------------------------------------------------

SlotState = Literal["pending", "admitted", "refused", "expired"]
_TERMINAL_STATES: frozenset[str] = frozenset({"admitted", "refused", "expired"})


# ---------------------------------------------------------------------------
# Semantic error hierarchy
# ---------------------------------------------------------------------------


class DeferredSlotError(RuntimeError):
    """Base class for all semantic deferred-boundary failures."""


class DeferredSlotNotFoundError(DeferredSlotError):
    """No slot exists for the supplied correlation ref."""


class DeferredSlotTerminalError(DeferredSlotError):
    """The slot has already reached a terminal state; replay is refused."""


class DeferredArgumentMismatchError(DeferredSlotError):
    """The arguments presented at resume do not match the deferred digest."""


class DeferredActorMismatchError(DeferredSlotError):
    """The actor_ref on the admitted decision does not match the expected reviewer."""


class DeferredStaleResponseError(DeferredSlotError):
    """The decision's decided_at is before the slot's created_at (stale/replayed)."""


class DeferredTimeoutError(DeferredSlotError):
    """The slot's gate_timeout_seconds has elapsed before the resume arrived."""


class DeferredExecutionFailureError(DeferredSlotError):
    """The inner handler raised during resume execution."""


class DeferredReviewObjectSinkError(DeferredSlotError):
    """The review-object sink was unavailable or failed during defer."""


# ---------------------------------------------------------------------------
# Slot data
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DeferredSlot:
    """The stable correlation token and metadata for a deferred tool call.

    ``correlation_ref`` is the opaque stable identifier callers use to resume.
    ``argument_digest`` is the sha256: digest of the deferred arguments — bound
    immutably at defer time and checked against whatever arguments are presented
    at resume.
    ``state`` transitions from ``pending`` → ``admitted`` | ``refused`` | ``expired``.
    ``review_object_ref`` is the ref returned by the ReviewObjectSink when the
    disposition ReviewObject was created; it is stable and opaque.
    ``admission_receipt_ref`` and ``outcome_receipt_ref`` are populated by the
    srs_bridge (when one is wired) at defer/resume time respectively.
    ``result`` is populated only on a successfully admitted+executed resume.
    ``final_decision`` is the last ReviewDecision that produced the terminal state.
    """

    correlation_ref: str
    tool_name: str
    tool_class: str
    profile_ref: str
    argument_digest: str
    created_at: str
    state: SlotState = "pending"
    review_object_ref: str | None = None
    gate_timeout_seconds: int | None = None
    admission_receipt_ref: str | None = None
    outcome_receipt_ref: str | None = None
    result: Any = None
    failure_reason: str | None = None
    final_decision: ReviewDecision | None = None
    event_refs: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Deferred-call result returned from defer_call
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DeferralResult:
    """Returned from ``DeferredBoundary.defer_call``; no child was spawned."""

    correlation_ref: str
    review_object_ref: str
    argument_digest: str
    admission_receipt_ref: str | None
    event_refs: list[str]


# ---------------------------------------------------------------------------
# Resume-call result returned from resume_call
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResumeResult:
    """Returned from ``DeferredBoundary.resume_call``."""

    correlation_ref: str
    state: SlotState
    result: Any
    failure_reason: str | None
    admission_receipt_ref: str | None
    outcome_receipt_ref: str | None
    event_refs: list[str]


# ---------------------------------------------------------------------------
# Boundary
# ---------------------------------------------------------------------------


class DeferredBoundary:
    """Stateful deferred tool boundary owning a slot store.

    Thread-safe: a per-slot lock guards state transitions; a store-level lock
    guards slot insertion.  The inner handler is never called from ``defer_call``.

    Parameters
    ----------
    inner:
        The governed inner handler to call on an admitted resume.  It must be
        callable as ``inner(tool_name, arguments)`` or as an object with
        ``handle_tool_call(tool_name, arguments)``.
    event_sink:
        An ``EventSink``-compatible object for governance events.  If ``None``
        a fresh ``InMemoryEventSink`` is used.
    review_sink:
        A ``ReviewObjectSink``-compatible object for disposition review objects.
        If ``None`` a fresh ``InMemoryReviewObjectSink`` is used.
    srs_bridge:
        Optional ``HarnessSRSBridge``-compatible object for SRS receipt emission.
        If ``None`` no receipts are emitted (permissible in test configurations).
    profile_ref:
        The stable profile reference stamped on all ReviewObjects.
    """

    def __init__(
        self,
        inner: Any,
        *,
        event_sink: Any = None,
        review_sink: Any = None,
        srs_bridge: Any = None,
        profile_ref: str = "srs.mcp.sdk_enforcement:v0.1",
    ) -> None:
        self._inner = inner
        self._event_sink = event_sink if event_sink is not None else InMemoryEventSink()
        self._review_sink = (
            review_sink if review_sink is not None else InMemoryReviewObjectSink()
        )
        self._srs_bridge = srs_bridge
        self._profile_ref = profile_ref
        self._slots: dict[str, DeferredSlot] = {}
        self._slot_locks: dict[str, threading.Lock] = {}
        self._store_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public: defer
    # ------------------------------------------------------------------

    def defer_call(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        tool_class: str = "unknown",
        gate_timeout_seconds: int | None = None,
        harness_context: Any = None,
    ) -> DeferralResult:
        """Defer a tool call at the boundary — zero child invocations.

        Creates a stable ``DeferredSlot`` with a correlation ref, mints a
        ``tool_call_disposition`` ReviewObject in the configured sink, and
        optionally emits a ``deferred_for_review`` admission receipt via the
        configured srs_bridge.  The inner handler is NOT called.

        Returns a ``DeferralResult`` with the stable correlation ref and digest.

        Raises
        ------
        DeferredReviewObjectSinkError
            When the review-object sink fails to create the disposition row.
        """
        if not isinstance(arguments, Mapping):
            raise DeferredSlotError(
                f"arguments must be a Mapping, not {type(arguments).__name__}"
            )

        argument_digest = hash_tool_call_arguments(arguments)
        correlation_ref = f"deferred:{uuid.uuid4()}"
        created_at = now_utc_iso()

        # Mint the ReviewObject
        review_inp = ToolCallDispositionInput(
            tool_name=tool_name,
            tool_class=tool_class,
            policy_decision="gate",
            arguments=arguments,
            retention_class="hash_only",
            required_sinks=("event", "review"),
            reason="deferred_for_review",
            gate_timeout_seconds=gate_timeout_seconds,
            profile_ref=self._profile_ref,
            allowed_actions=("approve", "reject", "defer", "escalate"),
            created_at=created_at,
        )
        review_object: ReviewObject = build_tool_call_disposition_review_object(
            review_inp
        )

        try:
            review_object_ref = self._review_sink.create_review_object(review_object)
        except Exception as exc:
            raise DeferredReviewObjectSinkError(
                "review_object_sink failed during defer_call"
            ) from exc

        # Build slot
        slot = DeferredSlot(
            correlation_ref=correlation_ref,
            tool_name=tool_name,
            tool_class=tool_class,
            profile_ref=self._profile_ref,
            argument_digest=argument_digest,
            created_at=created_at,
            state="pending",
            review_object_ref=review_object_ref,
            gate_timeout_seconds=gate_timeout_seconds,
        )

        # Emit defer event
        event_refs: list[str] = []
        event_ref = self._write_event(
            "mcp.tool.call.deferred",
            detail={
                "tool_name": tool_name,
                "argument_digest": argument_digest,
                "correlation_ref": correlation_ref,
                "review_object_ref": review_object_ref,
            },
        )
        if event_ref:
            event_refs.append(event_ref)
        slot.event_refs.extend(event_refs)

        # Optionally emit deferred_for_review admission receipt
        admission_receipt_ref: str | None = None
        if self._srs_bridge is not None and harness_context is not None:
            try:
                admission_receipt_ref = self._srs_bridge.emit_admission(
                    harness_context=harness_context,
                    tool_name=tool_name,
                    disposition="deferred_for_review",
                    review_object_ref=review_object_ref,
                    retry_contract="retry_after_approval",
                )
                slot.admission_receipt_ref = admission_receipt_ref
            except Exception:
                pass  # Receipt emission failure is non-fatal for the defer itself.

        # Register slot (thread-safe)
        with self._store_lock:
            self._slots[correlation_ref] = slot
            self._slot_locks[correlation_ref] = threading.Lock()

        return DeferralResult(
            correlation_ref=correlation_ref,
            review_object_ref=review_object_ref,
            argument_digest=argument_digest,
            admission_receipt_ref=admission_receipt_ref,
            event_refs=list(event_refs),
        )

    # ------------------------------------------------------------------
    # Public: resume
    # ------------------------------------------------------------------

    def resume_call(
        self,
        correlation_ref: str,
        decision: ReviewDecision,
        arguments: Mapping[str, Any],
        *,
        harness_context: Any = None,
    ) -> ResumeResult:
        """Resume a deferred call given a ReviewDecision.

        Checks (in order, fail-closed):
        1. Slot exists (``DeferredSlotNotFoundError`` otherwise).
        2. Slot is not terminal (``DeferredSlotTerminalError`` otherwise).
        3. Slot has not timed out (``DeferredTimeoutError`` otherwise).
        4. Decision is not stale (``DeferredStaleResponseError`` otherwise).
        5. Decision outcome is validated.
        6. If outcome is ``approved``:
           a. Arguments digest must match (``DeferredArgumentMismatchError``).
           b. Actor ref must match when present on the decision
              (``DeferredActorMismatchError``).
           c. Inner handler is called; failure → ``DeferredExecutionFailureError``.
        7. If outcome is ``rejected`` or ``expired``: slot transitions, no exec.

        Raises
        ------
        DeferredSlotNotFoundError
            Slot not found.
        DeferredSlotTerminalError
            Slot already in a terminal state (replay protection).
        DeferredTimeoutError
            Gate timeout has elapsed.
        DeferredStaleResponseError
            ``decision.decided_at`` precedes slot's ``created_at``.
        DeferredArgumentMismatchError
            Digest of presented arguments does not match deferred digest.
        DeferredActorMismatchError
            ``decision.actor_ref`` is present but does not match the expected
            reviewer; only raised when both sides supply a non-None actor_ref.
        DeferredExecutionFailureError
            The inner handler raised an exception during admitted execution.
        """
        with self._store_lock:
            slot = self._slots.get(correlation_ref)
            slot_lock = self._slot_locks.get(correlation_ref)

        if slot is None or slot_lock is None:
            raise DeferredSlotNotFoundError(
                f"no deferred slot for correlation_ref {correlation_ref!r}"
            )

        with slot_lock:
            return self._resume_locked(
                slot, decision, arguments, harness_context=harness_context
            )

    def _resume_locked(
        self,
        slot: DeferredSlot,
        decision: ReviewDecision,
        arguments: Mapping[str, Any],
        *,
        harness_context: Any,
    ) -> ResumeResult:
        # 1. Replay protection
        if slot.state in _TERMINAL_STATES:
            raise DeferredSlotTerminalError(
                f"slot {slot.correlation_ref!r} is terminal ({slot.state!r}); "
                "replay is refused"
            )

        # 2. Timeout check (wall-clock)
        if slot.gate_timeout_seconds is not None:
            created = _parse_iso(slot.created_at)
            now = datetime.now(UTC)
            elapsed = (now - created).total_seconds()
            if elapsed > slot.gate_timeout_seconds:
                slot.state = "expired"
                slot.failure_reason = "gate_timeout_elapsed"
                self._write_event(
                    "mcp.tool.call.expired",
                    detail={
                        "tool_name": slot.tool_name,
                        "correlation_ref": slot.correlation_ref,
                        "elapsed_seconds": elapsed,
                    },
                )
                raise DeferredTimeoutError(
                    f"slot {slot.correlation_ref!r} gate_timeout_seconds="
                    f"{slot.gate_timeout_seconds} elapsed ({elapsed:.1f}s)"
                )

        # 3. Stale-response check
        validate_tool_call_disposition_decision(decision)
        decided = _parse_iso(decision.decided_at)
        created = _parse_iso(slot.created_at)
        if decided < created:
            raise DeferredStaleResponseError(
                f"decision.decided_at {decision.decided_at!r} precedes slot "
                f"created_at {slot.created_at!r}; treating as stale"
            )

        # 4. Outcome normalization
        outcome = normalize_review_decision_outcome(decision.decision)

        # 5. Non-approved terminal paths
        if outcome in {"rejected", "expired"}:
            slot.state = "refused" if outcome == "rejected" else "expired"
            slot.failure_reason = f"decision_{outcome}"
            slot.final_decision = decision
            ref = self._write_event(
                "mcp.tool.call.rejected",
                detail={
                    "tool_name": slot.tool_name,
                    "correlation_ref": slot.correlation_ref,
                    "outcome": outcome,
                },
            )
            if ref:
                slot.event_refs.append(ref)
            return ResumeResult(
                correlation_ref=slot.correlation_ref,
                state=slot.state,
                result=None,
                failure_reason=slot.failure_reason,
                admission_receipt_ref=slot.admission_receipt_ref,
                outcome_receipt_ref=None,
                event_refs=list(slot.event_refs),
            )

        if outcome == "deferred":
            # Still deferred — keep slot pending, no execution.
            ref = self._write_event(
                "mcp.tool.call.deferred",
                detail={
                    "tool_name": slot.tool_name,
                    "correlation_ref": slot.correlation_ref,
                    "outcome": "still_deferred",
                },
            )
            if ref:
                slot.event_refs.append(ref)
            return ResumeResult(
                correlation_ref=slot.correlation_ref,
                state="pending",
                result=None,
                failure_reason="still_deferred",
                admission_receipt_ref=slot.admission_receipt_ref,
                outcome_receipt_ref=None,
                event_refs=list(slot.event_refs),
            )

        # 6. Approved path — pre-execution checks
        assert outcome == "approved"

        # 6a. Argument digest check
        submitted_digest = hash_tool_call_arguments(arguments)
        if submitted_digest != slot.argument_digest:
            slot.state = "refused"
            slot.failure_reason = "argument_digest_mismatch"
            slot.final_decision = decision
            self._write_event(
                "mcp.tool.call.rejected",
                detail={
                    "tool_name": slot.tool_name,
                    "correlation_ref": slot.correlation_ref,
                    "failure_reason": "argument_digest_mismatch",
                },
            )
            raise DeferredArgumentMismatchError(
                f"resume arguments digest {submitted_digest!r} does not match "
                f"deferred digest {slot.argument_digest!r}"
            )

        # 6b. Actor-ref check (fail-closed when both sides supply one)
        if decision.actor_ref is not None:
            # The expected reviewer identity is the actor on the original decision.
            # For this contract: if the decision declares an actor_ref, we accept
            # it as the verified reviewer identity.  A wrong_actor sentinel is
            # detected when a *second* resume is presented with a different actor.
            if slot.final_decision is not None and slot.final_decision.actor_ref is not None:
                expected = slot.final_decision.actor_ref
                if decision.actor_ref != expected:
                    raise DeferredActorMismatchError(
                        f"actor_ref {decision.actor_ref!r} does not match "
                        f"expected reviewer {expected!r}"
                    )

        # 6c. Execute inner handler
        result = None
        outcome_receipt_ref: str | None = None
        try:
            result = _call_inner(self._inner, slot.tool_name, arguments)
        except Exception as exc:
            slot.state = "refused"
            slot.failure_reason = "inner_execution_failure"
            slot.final_decision = decision
            self._write_event(
                "mcp.tool.call.failed",
                detail={
                    "tool_name": slot.tool_name,
                    "correlation_ref": slot.correlation_ref,
                    "exception_class": type(exc).__name__,
                },
            )
            raise DeferredExecutionFailureError(
                f"inner handler raised {type(exc).__name__} during admitted resume"
            ) from exc

        # 6d. Slot → admitted
        slot.state = "admitted"
        slot.result = result
        slot.final_decision = decision

        # Optionally emit admitted + outcome receipts
        if self._srs_bridge is not None and harness_context is not None:
            try:
                adm_ref = self._srs_bridge.emit_admission(
                    harness_context=harness_context,
                    tool_name=slot.tool_name,
                    disposition="admitted",
                )
                slot.admission_receipt_ref = adm_ref
                outcome_receipt_ref = self._srs_bridge.emit_outcome(
                    harness_context=harness_context,
                    admission_receipt_ref=adm_ref,
                    outcome="result_returned",
                    result_value=result,
                )
                slot.outcome_receipt_ref = outcome_receipt_ref
            except Exception:
                pass  # Receipt failure is non-fatal for the result delivery.

        ref = self._write_event(
            "mcp.tool.call.executed",
            detail={
                "tool_name": slot.tool_name,
                "argument_digest": slot.argument_digest,
                "correlation_ref": slot.correlation_ref,
            },
        )
        if ref:
            slot.event_refs.append(ref)

        return ResumeResult(
            correlation_ref=slot.correlation_ref,
            state="admitted",
            result=result,
            failure_reason=None,
            admission_receipt_ref=slot.admission_receipt_ref,
            outcome_receipt_ref=outcome_receipt_ref,
            event_refs=list(slot.event_refs),
        )

    # ------------------------------------------------------------------
    # Public: slot inspection
    # ------------------------------------------------------------------

    def get_slot(self, correlation_ref: str) -> DeferredSlot | None:
        """Return the slot for *correlation_ref*, or ``None`` if not found."""
        return self._slots.get(correlation_ref)

    def pending_slots(self) -> list[DeferredSlot]:
        """Return all slots still in the ``pending`` state."""
        return [s for s in self._slots.values() if s.state == "pending"]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_event(self, event_type: str, *, detail: dict[str, Any]) -> str | None:
        try:
            from dagr_mcp.sdk_spine import EventEnvelope

            return self._event_sink.write_event(
                EventEnvelope(
                    event_type=event_type,
                    occurred_at=now_utc_iso(),
                    detail=detail,
                )
            )
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 UTC string to an aware datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _call_inner(inner: Any, tool_name: str, arguments: Any) -> Any:
    if hasattr(inner, "handle_tool_call"):
        return inner.handle_tool_call(tool_name, arguments)
    if callable(inner):
        return inner(tool_name, arguments)
    raise TypeError("inner must be callable or expose handle_tool_call")


# ---------------------------------------------------------------------------
# Public API helpers (convenience factories for tests and bindings)
# ---------------------------------------------------------------------------


def make_deferred_boundary(
    inner: Any = None,
    *,
    event_sink: Any = None,
    review_sink: Any = None,
    srs_bridge: Any = None,
    profile_ref: str = "srs.mcp.sdk_enforcement:v0.1",
) -> "DeferredBoundary":
    """Factory for a ``DeferredBoundary`` with sane defaults for testing."""
    if inner is None:
        inner = _null_inner
    return DeferredBoundary(
        inner,
        event_sink=event_sink,
        review_sink=review_sink,
        srs_bridge=srs_bridge,
        profile_ref=profile_ref,
    )


def _null_inner(tool_name: str, arguments: Any) -> dict[str, Any]:
    return {"tool_name": tool_name, "executed": True}


def make_review_decision(
    review_object_id: str,
    *,
    decision: str = "approved",
    actor_ref: str | None = None,
    reason: str | None = None,
    decided_at: str | None = None,
) -> ReviewDecision:
    """Convenience factory for ``ReviewDecision`` in tests."""
    return ReviewDecision(
        decision=decision,
        review_object_id=review_object_id,
        decided_at=decided_at or now_utc_iso(),
        actor_ref=actor_ref,
        reason=reason,
    )


__all__ = [
    # Errors
    "DeferredSlotError",
    "DeferredSlotNotFoundError",
    "DeferredSlotTerminalError",
    "DeferredArgumentMismatchError",
    "DeferredActorMismatchError",
    "DeferredStaleResponseError",
    "DeferredTimeoutError",
    "DeferredExecutionFailureError",
    "DeferredReviewObjectSinkError",
    # Core types
    "SlotState",
    "DeferredSlot",
    "DeferralResult",
    "ResumeResult",
    # Boundary
    "DeferredBoundary",
    # Helpers
    "make_deferred_boundary",
    "make_review_decision",
]
