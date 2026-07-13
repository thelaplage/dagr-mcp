"""A stale, pre-guard ShadowGraph reopening surface.

This fixture mimics an ``arcs_amnesiac`` producer tree from *before* the FINAL
transition guard (commit ``b6f09fb``) landed: ``reopen_candidate`` here happily
reopens a FINAL candidate instead of refusing it. It exists so a regression test
can prove that ``probe_final_guard`` reports such a tree as UNGUARDED — that a
stale tree is never represented as guarded.

It deliberately reuses the real ``RejectedCandidate`` / ``RejectedCandidateLifecycle``
shapes (imported lazily) so only the reopening transition differs.
"""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum
from types import SimpleNamespace
from typing import Any


class ReopeningDecision(StrEnum):
    REOPENED = "reopened"
    DECLINED = "declined"
    REQUIRES_REVIEW = "requires_review"


def _pre_guard_reopen(candidate: Any, request: Any, decision: Any, rationale: str = "") -> tuple[Any, Any]:
    """Pre-guard behavior: reopen unconditionally, INCLUDING for FINAL.

    This is exactly the defect the FINAL guard closes. A probe that trusts a
    symbol like ``hasattr(reo, "reopen_candidate")`` would call this "guarded";
    the fail-closed probe must not.
    """
    from arcs_amnesiac.shadow_graph import RejectedCandidateLifecycle

    new_lifecycle = RejectedCandidateLifecycle.REOPENED_FOR_REVIEW
    outcome = SimpleNamespace(
        outcome_ref=f"reopening:{request.request_ref}",
        request_ref=request.request_ref,
        candidate_ref=candidate.candidate_ref,
        decision=decision,
        is_active_in_admission_loop=lambda: decision == ReopeningDecision.REOPENED,
    )
    return replace(candidate, lifecycle=new_lifecycle), outcome


def build_preguard_reopening_module() -> SimpleNamespace:
    """The stale reopening module surface for ``probe_final_guard``."""

    class ReopeningRequestShim:
        def __init__(self, *, request_ref, candidate_ref, arriving_trigger, submitted_by_ref, submitted_at=""):
            self.request_ref = request_ref
            self.candidate_ref = candidate_ref
            self.arriving_trigger = arriving_trigger
            self.submitted_by_ref = submitted_by_ref
            self.submitted_at = submitted_at

    return SimpleNamespace(
        ReopeningDecision=ReopeningDecision,
        ReopeningRequest=ReopeningRequestShim,
        reopen_candidate=_pre_guard_reopen,
    )


def build_preguard_shadow_module() -> SimpleNamespace:
    """The stale shadow module surface (reuses the real base objects)."""
    from arcs_amnesiac.shadow_graph import RejectedCandidate, RejectedCandidateLifecycle

    return SimpleNamespace(
        RejectedCandidate=RejectedCandidate,
        RejectedCandidateLifecycle=RejectedCandidateLifecycle,
    )
