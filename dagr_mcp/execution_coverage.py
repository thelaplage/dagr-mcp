"""ExecutionCoverage — orthogonal plan-level execution completeness artifact.

Tracks the outcome distribution of a governed action plan without collapsing
into a scalar PASS/FAIL. Admission outcome (admitted | refused | deferred) and
execution completeness are **orthogonal** dimensions. This artifact captures the
latter and must never be confused with the former.

Key invariant (non-negotiable):
  A plan where 6/8 actions are admitted and 5/6 execute successfully is NOT the
  same as a plan where all 8 are refused. The individual counts are facts; no
  single scalar may substitute for the full distribution.

This module is ADDITIVE — it introduces no changes to the existing SRS receipt
structure. It does not import arcs-verify. It does not produce admission receipts.

AUTHORITY_MOVEMENT = 0
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

ActionAdmissionOutcome = Literal["admitted", "refused", "deferred"]
ActionExecutionOutcome = Literal["executed_successfully", "execution_failed", "not_attempted"]

# Combined per-action record an accumulator accepts.
ActionOutcome = Literal[
    "admitted_and_executed_successfully",
    "admitted_and_execution_failed",
    "admitted_and_not_attempted",
    "refused",
    "deferred",
]

_VALID_ACTION_OUTCOMES: frozenset[str] = frozenset(
    {
        "admitted_and_executed_successfully",
        "admitted_and_execution_failed",
        "admitted_and_not_attempted",
        "refused",
        "deferred",
    }
)

# The canonical projection key order for coverage_digest computation. Order is
# frozen here; any future addition appends to the END — never reorders existing
# keys, since existing digests are byte-pinned evidence.
_DIGEST_PROJECTION_KEYS: tuple[str, ...] = (
    "planned_action_count",
    "attempted_action_count",
    "admitted_count",
    "refused_count",
    "deferred_count",
    "executed_successfully_count",
    "execution_failed_count",
    "not_attempted_count",
)


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------

class ExecutionCoverageError(ValueError):
    """Invalid inputs for ExecutionCoverage construction."""


# ---------------------------------------------------------------------------
# Core artifact
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ExecutionCoverage:
    """Plan-level execution completeness record.

    This is NOT a quality score. This is NOT PASS/FAIL. This is NOT an
    admission receipt. It is an additive, orthogonal artifact that records
    how completely a governed action plan was attempted and executed.

    All counts are retained separately and must not be collapsed into a scalar.
    ``coverage_digest`` is a deterministic ``sha256:`` over the canonical count
    projection, enabling downstream verification of the record's integrity
    without importing producer or verifier code.

    AUTHORITY_MOVEMENT = 0. This artifact introduces no new authority. It does
    not modify, reinterpret, or extend the SRS envelope schema.
    """

    planned_action_count: int
    attempted_action_count: int
    admitted_count: int
    refused_count: int
    deferred_count: int
    executed_successfully_count: int
    execution_failed_count: int
    not_attempted_count: int
    coverage_digest: str  # sha256: over canonical count projection

    def as_dict(self) -> dict[str, Any]:
        """Serializable projection — all counts plus digest. No scalar quality score."""
        return {
            "planned_action_count": self.planned_action_count,
            "attempted_action_count": self.attempted_action_count,
            "admitted_count": self.admitted_count,
            "refused_count": self.refused_count,
            "deferred_count": self.deferred_count,
            "executed_successfully_count": self.executed_successfully_count,
            "execution_failed_count": self.execution_failed_count,
            "not_attempted_count": self.not_attempted_count,
            "coverage_digest": self.coverage_digest,
        }


# ---------------------------------------------------------------------------
# Digest computation (frozen projection order)
# ---------------------------------------------------------------------------

def _compute_coverage_digest(counts: dict[str, int]) -> str:
    """Deterministic ``sha256:`` over the canonical count projection.

    Key order is frozen by ``_DIGEST_PROJECTION_KEYS``. Adding a new count
    field appends to the projection key tuple — it never reorders existing
    keys, so historical digests remain byte-stable.
    """
    projection: dict[str, int] = {k: counts[k] for k in _DIGEST_PROJECTION_KEYS}
    canonical = json.dumps(projection, sort_keys=False, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


# ---------------------------------------------------------------------------
# Builder (mutable accumulator)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ExecutionCoverageBuilder:
    """Mutable accumulator for plan-level action outcomes.

    Call ``record_action_outcome`` once per governed action in a plan, then
    call ``build`` to mint an immutable ``ExecutionCoverage``.

    The builder does NOT track admission or generate SRS receipts. It records
    only the outcome distribution required for execution completeness.
    """

    _planned_action_count: int = field(default=0)
    _admitted_count: int = field(default=0)
    _refused_count: int = field(default=0)
    _deferred_count: int = field(default=0)
    _executed_successfully_count: int = field(default=0)
    _execution_failed_count: int = field(default=0)
    _not_attempted_count: int = field(default=0)

    def record_action_outcome(self, outcome: str) -> None:
        """Record a single governed action's outcome.

        ``outcome`` must be one of the ``_VALID_ACTION_OUTCOMES`` literals.
        Every ``record_action_outcome`` call increments ``planned_action_count``.

        The composite outcomes encode the admission disposition + execution
        result as one atomic fact:
          - ``admitted_and_executed_successfully`` — admitted, handler ran, no exception
          - ``admitted_and_execution_failed``       — admitted, handler ran, raised
          - ``admitted_and_not_attempted``          — admitted, but handler was not called
          - ``refused``                             — refused before execution
          - ``deferred``                            — deferred for review; not executed
        """
        if outcome not in _VALID_ACTION_OUTCOMES:
            raise ExecutionCoverageError(
                f"unknown action outcome: {outcome!r}; "
                f"must be one of {sorted(_VALID_ACTION_OUTCOMES)}"
            )
        self._planned_action_count += 1

        if outcome == "admitted_and_executed_successfully":
            self._admitted_count += 1
            self._executed_successfully_count += 1
        elif outcome == "admitted_and_execution_failed":
            self._admitted_count += 1
            self._execution_failed_count += 1
        elif outcome == "admitted_and_not_attempted":
            self._admitted_count += 1
            self._not_attempted_count += 1
        elif outcome == "refused":
            self._refused_count += 1
        elif outcome == "deferred":
            self._deferred_count += 1

    def build(self) -> ExecutionCoverage:
        """Finalize the builder into an immutable ``ExecutionCoverage``.

        ``attempted_action_count`` = admitted_count (admitted actions were
        submitted to the handler boundary, regardless of handler outcome).
        Refused and deferred actions were never attempted.
        """
        attempted = self._admitted_count
        counts: dict[str, int] = {
            "planned_action_count": self._planned_action_count,
            "attempted_action_count": attempted,
            "admitted_count": self._admitted_count,
            "refused_count": self._refused_count,
            "deferred_count": self._deferred_count,
            "executed_successfully_count": self._executed_successfully_count,
            "execution_failed_count": self._execution_failed_count,
            "not_attempted_count": self._not_attempted_count,
        }
        digest = _compute_coverage_digest(counts)
        return ExecutionCoverage(
            planned_action_count=counts["planned_action_count"],
            attempted_action_count=counts["attempted_action_count"],
            admitted_count=counts["admitted_count"],
            refused_count=counts["refused_count"],
            deferred_count=counts["deferred_count"],
            executed_successfully_count=counts["executed_successfully_count"],
            execution_failed_count=counts["execution_failed_count"],
            not_attempted_count=counts["not_attempted_count"],
            coverage_digest=digest,
        )


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def build_execution_coverage(outcomes: Sequence[str]) -> ExecutionCoverage:
    """Build an ``ExecutionCoverage`` from a sequence of action outcome strings.

    Equivalent to calling ``ExecutionCoverageBuilder.record_action_outcome``
    once per entry, then ``build()``. Raises ``ExecutionCoverageError`` on any
    unrecognized outcome value.
    """
    builder = ExecutionCoverageBuilder()
    for outcome in outcomes:
        builder.record_action_outcome(outcome)
    return builder.build()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_execution_coverage(coverage: ExecutionCoverage) -> None:
    """Structural validation of an ``ExecutionCoverage`` artifact.

    Checks:
    - All counts are non-negative integers.
    - planned >= attempted >= 0.
    - attempted == admitted_count (by definition).
    - admitted_count == executed_successfully + execution_failed + not_attempted.
    - planned == admitted + refused + deferred.
    - coverage_digest matches the recomputed digest.
    - No scalar quality score is present (structural, not semantic).

    Raises ``ExecutionCoverageError`` on any violation.
    """
    int_fields = {
        "planned_action_count": coverage.planned_action_count,
        "attempted_action_count": coverage.attempted_action_count,
        "admitted_count": coverage.admitted_count,
        "refused_count": coverage.refused_count,
        "deferred_count": coverage.deferred_count,
        "executed_successfully_count": coverage.executed_successfully_count,
        "execution_failed_count": coverage.execution_failed_count,
        "not_attempted_count": coverage.not_attempted_count,
    }

    for name, value in int_fields.items():
        if not isinstance(value, int) or isinstance(value, bool):
            raise ExecutionCoverageError(f"{name} must be a non-negative int")
        if value < 0:
            raise ExecutionCoverageError(f"{name} must be >= 0, got {value}")

    if coverage.attempted_action_count != coverage.admitted_count:
        raise ExecutionCoverageError(
            f"attempted_action_count ({coverage.attempted_action_count}) "
            f"must equal admitted_count ({coverage.admitted_count})"
        )

    admitted_total = (
        coverage.executed_successfully_count
        + coverage.execution_failed_count
        + coverage.not_attempted_count
    )
    if admitted_total != coverage.admitted_count:
        raise ExecutionCoverageError(
            f"admitted_count ({coverage.admitted_count}) must equal "
            f"executed_successfully + execution_failed + not_attempted "
            f"({admitted_total})"
        )

    disposition_total = (
        coverage.admitted_count
        + coverage.refused_count
        + coverage.deferred_count
    )
    if disposition_total != coverage.planned_action_count:
        raise ExecutionCoverageError(
            f"planned_action_count ({coverage.planned_action_count}) must equal "
            f"admitted + refused + deferred ({disposition_total})"
        )

    if not isinstance(coverage.coverage_digest, str):
        raise ExecutionCoverageError("coverage_digest must be a str")
    if not coverage.coverage_digest.startswith("sha256:"):
        raise ExecutionCoverageError("coverage_digest must start with sha256:")

    counts: dict[str, int] = {k: int_fields[k] for k in _DIGEST_PROJECTION_KEYS}
    expected_digest = _compute_coverage_digest(counts)
    if coverage.coverage_digest != expected_digest:
        raise ExecutionCoverageError(
            f"coverage_digest mismatch: stored={coverage.coverage_digest!r} "
            f"recomputed={expected_digest!r}"
        )


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    "ActionAdmissionOutcome",
    "ActionExecutionOutcome",
    "ActionOutcome",
    "ExecutionCoverage",
    "ExecutionCoverageBuilder",
    "ExecutionCoverageError",
    "build_execution_coverage",
    "validate_execution_coverage",
]
