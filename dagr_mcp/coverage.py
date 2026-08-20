"""Additive CoverageObservation adapter — dagr.coverage.v0.1.

This module is ADDITIVE ONLY. It introduces no new admission semantics, makes no
runtime authority decisions, and does not change any existing lifecycle decisions.
It observes facts already produced by the admission/execution lifecycle and
projects them into a coverage posture.

Contract: dagr.coverage.v0.1

Non-equivalences (NEQ-COV-01 through NEQ-COV-07):
  NEQ-COV-01: coverage:complete ≠ mcp_action:admitted
  NEQ-COV-02: coverage:complete ≠ evidence:supported
  NEQ-COV-03: coverage:incomparable ≠ mcp_action:refused
  NEQ-COV-04: coverage:not_evaluated ≠ verifier:pass
  NEQ-COV-05: mcp_action:admitted ≠ coverage:complete
  NEQ-COV-06: mcp_action:refused ≠ coverage:incomparable
  NEQ-COV-07: verifier:pass ≠ coverage:not_evaluated

INCOMPARABLE invariant:
  "incomparable" = single-observation posture (this observation cannot be
      compared with another; no basis for comparison within the observation).
  "diff_incomparable" = cross-observation aggregate (two or more observations
      are of different kinds and cannot be meaningfully aggregated).
  These are DISTINCT concepts and must NOT be conflated.

Domain namespace rule: domain tokens use qualified prefixes.
  Use: "mcp_action:admitted", "mcp_action:refused", "mcp_action:deferred"
  Never: bare "admitted", "refused", "deferred"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# --------------------------------------------------------------------------- #
# Contract identity                                                           #
# --------------------------------------------------------------------------- #

COVERAGE_CONTRACT_ID = "dagr.coverage.v0.1"

# --------------------------------------------------------------------------- #
# Posture type                                                                #
# --------------------------------------------------------------------------- #

CoveragePosture = Literal["complete", "partial", "not_evaluated", "incomparable"]

COVERAGE_POSTURES: tuple[CoveragePosture, ...] = (
    "complete",
    "partial",
    "not_evaluated",
    "incomparable",
)

# Postures that require a non-empty reasons list (CR-COV-03).
_REASONS_REQUIRED_POSTURES: frozenset[CoveragePosture] = frozenset(
    {"partial", "not_evaluated", "incomparable"}
)

# --------------------------------------------------------------------------- #
# Non-equivalences (NEQ-COV-01–07)                                           #
# --------------------------------------------------------------------------- #
# Each entry is (lhs_label, rhs_label, narrative). These are documentation and
# assertion targets — they express what must NOT be inferred from a posture.

NON_EQUIVALENCES: dict[str, tuple[str, str, str]] = {
    "NEQ-COV-01": (
        "coverage:complete",
        "mcp_action:admitted",
        "A complete coverage posture does not imply the action was admitted; "
        "coverage tracks observability across lifecycle phases, not admission.",
    ),
    "NEQ-COV-02": (
        "coverage:complete",
        "evidence:supported",
        "A complete coverage posture does not imply the underlying evidence is "
        "supported or verified — those are separate verifier determinations.",
    ),
    "NEQ-COV-03": (
        "coverage:incomparable",
        "mcp_action:refused",
        "An incomparable posture means this observation cannot be compared "
        "within its own observation; it does not mean the action was refused.",
    ),
    "NEQ-COV-04": (
        "coverage:not_evaluated",
        "verifier:pass",
        "A not_evaluated posture means the phase was not reached or assessed; "
        "it is not a passing verdict from any verifier.",
    ),
    "NEQ-COV-05": (
        "mcp_action:admitted",
        "coverage:complete",
        "An admitted action does not guarantee complete coverage across all "
        "lifecycle phases; execution or evaluation may still be absent.",
    ),
    "NEQ-COV-06": (
        "mcp_action:refused",
        "coverage:incomparable",
        "A refused action is a lifecycle disposition; incomparable is a "
        "coverage posture. They arise from different observations.",
    ),
    "NEQ-COV-07": (
        "verifier:pass",
        "coverage:not_evaluated",
        "A verifier pass is an affirmative finding; not_evaluated means the "
        "phase was not assessed. They are not inverses or equivalents.",
    ),
}

# --------------------------------------------------------------------------- #
# INCOMPARABLE invariant                                                      #
# --------------------------------------------------------------------------- #

INCOMPARABLE_INVARIANT: dict[str, str] = {
    "incomparable": (
        "Single-observation posture: this individual observation cannot be "
        "compared (e.g. a phase was not reached so comparison is undefined). "
        "Scoped to one CoverageObservation instance."
    ),
    "diff_incomparable": (
        "Cross-observation aggregate posture: two or more observations are of "
        "structurally different kinds and cannot be meaningfully aggregated or "
        "compared against each other. Scoped across a collection of observations. "
        "This is a DISTINCT concept from the single-observation 'incomparable'."
    ),
}

# --------------------------------------------------------------------------- #
# Error type                                                                  #
# --------------------------------------------------------------------------- #


class CoverageConformanceError(ValueError):
    """Raised when a CoverageObservation violates a conformance rule.

    CR-COV-03: reasons must be non-empty for partial / not_evaluated /
    incomparable postures.
    """


# --------------------------------------------------------------------------- #
# CoverageObservation dataclass                                               #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CoverageObservation:
    """A single coverage observation for a governed action.

    Fields
    ------
    domain : str
        Qualified domain token, e.g. ``"mcp_action"``. Never a bare lifecycle
        disposition token — domain tokens live in their own namespace.
    subject_ref : str
        Reference to the subject being observed, e.g. ``"tool:<tool_name>"``
        or a receipt ref.
    expected : bool | None
        Whether the phase/action was expected to occur. ``None`` = unknown.
    attempted : bool | None
        Whether the phase/action was attempted. ``None`` = unknown.
    executed : bool | None
        Whether the phase/action executed to completion. ``None`` = unknown.
    evaluated : bool | None
        Whether the outcome was evaluated (e.g. by a verifier or policy).
        ``None`` = unknown.
    coverage_posture : CoveragePosture
        The derived posture for this observation.
    reasons : list[str]
        Non-empty when posture is ``partial``, ``not_evaluated``, or
        ``incomparable`` (CR-COV-03). May be empty only for ``complete``.
    """

    domain: str
    subject_ref: str
    expected: bool | None
    attempted: bool | None
    executed: bool | None
    evaluated: bool | None
    coverage_posture: CoveragePosture
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.domain:
            raise CoverageConformanceError("domain must be non-empty")
        if not self.subject_ref:
            raise CoverageConformanceError("subject_ref must be non-empty")
        if self.coverage_posture not in COVERAGE_POSTURES:
            raise CoverageConformanceError(
                f"coverage_posture must be one of {COVERAGE_POSTURES!r}, "
                f"got {self.coverage_posture!r}"
            )
        # CR-COV-03: reasons must be non-empty for non-complete postures.
        if self.coverage_posture in _REASONS_REQUIRED_POSTURES and not self.reasons:
            raise CoverageConformanceError(
                f"CR-COV-03: reasons must be non-empty when coverage_posture "
                f"is {self.coverage_posture!r}"
            )


# --------------------------------------------------------------------------- #
# Posture derivation                                                          #
# --------------------------------------------------------------------------- #


def _derive_mcp_action_posture(
    *,
    expected: bool | None,
    attempted: bool | None,
    executed: bool | None,
    evaluated: bool | None,
    admission_outcome_token: str | None,
) -> tuple[CoveragePosture, list[str]]:
    """Derive coverage posture from lifecycle phase booleans.

    Parameters
    ----------
    expected, attempted, executed, evaluated :
        Phase booleans; ``None`` = unknown/not reached.
    admission_outcome_token :
        The string token from the admission lifecycle (e.g.
        ``"mcp_action:admitted"``, ``"mcp_action:refused"``,
        ``"mcp_action:deferred"``). Referenced by name string only — never
        imported from the admission module — to preserve producer/verifier
        independence.

    Returns
    -------
    (posture, reasons)
        ``reasons`` is non-empty whenever posture is partial/not_evaluated/
        incomparable (satisfies CR-COV-03).
    """

    # All four phases known and True → complete.
    if (
        expected is True
        and attempted is True
        and executed is True
        and evaluated is True
    ):
        return "complete", []

    reasons: list[str] = []

    # Any phase explicitly False → partial (something was skipped or failed).
    if any(v is False for v in (expected, attempted, executed, evaluated)):
        for name, val in (
            ("expected", expected),
            ("attempted", attempted),
            ("executed", executed),
            ("evaluated", evaluated),
        ):
            if val is False:
                reasons.append(f"phase_{name}_false")
        # If admission_outcome_token indicates a refused or deferred action,
        # note it — but do NOT conflate with incomparable (NEQ-COV-03/06).
        if admission_outcome_token in (
            "mcp_action:refused",
            "mcp_action:deferred",
        ):
            reasons.append(f"admission_outcome:{admission_outcome_token}")
        return "partial", reasons

    # Any phase is None and none are False → not_evaluated (unknown reach).
    if any(v is None for v in (expected, attempted, executed, evaluated)):
        for name, val in (
            ("expected", expected),
            ("attempted", attempted),
            ("executed", executed),
            ("evaluated", evaluated),
        ):
            if val is None:
                reasons.append(f"phase_{name}_unknown")
        return "not_evaluated", reasons

    # All four phases known but not all True — logically shouldn't reach here
    # unless all are True (handled above) or some False (handled above).
    # Remaining case: incomparable (no basis for comparison within observation).
    reasons.append("phase_combination_not_comparable")
    return "incomparable", reasons


# --------------------------------------------------------------------------- #
# Factory                                                                     #
# --------------------------------------------------------------------------- #


def create_mcp_action_observation(
    tool_name: str,
    *,
    admission_outcome_token: str | None = None,
    execution_succeeded: bool | None = None,
    extra_reasons: list[str] | None = None,
) -> CoverageObservation:
    """Factory for a ``mcp_action`` domain CoverageObservation.

    Maps the already-produced admission/execution lifecycle facts into a
    CoverageObservation. Does NOT make admission decisions, does NOT alter any
    lifecycle state, and is purely additive.

    Parameters
    ----------
    tool_name :
        The name of the governed tool (used in ``subject_ref``).
    admission_outcome_token :
        The qualified admission outcome string from the lifecycle, e.g.
        ``"mcp_action:admitted"``, ``"mcp_action:refused"``,
        ``"mcp_action:deferred"``. Pass ``None`` when the admission outcome is
        not known at observation time.
    execution_succeeded :
        Whether execution completed without error. Only meaningful when the
        action was admitted; pass ``None`` when not applicable or unknown.
    extra_reasons :
        Additional caller-supplied reason strings appended to derived reasons.
        Useful when the caller has context the factory cannot derive.

    Returns
    -------
    CoverageObservation
        A validated, immutable observation. Raises ``CoverageConformanceError``
        on conformance violations (e.g. CR-COV-03).

    Domain namespace rule
    ---------------------
    ``domain`` is always ``"mcp_action"`` — never a bare lifecycle disposition
    token. Bare tokens like ``"admitted"`` / ``"refused"`` / ``"deferred"``
    belong to the lifecycle namespace, not the coverage domain namespace.
    """

    if not tool_name or not tool_name.strip():
        raise CoverageConformanceError("tool_name must be non-empty")

    domain = "mcp_action"
    subject_ref = f"tool:{tool_name.strip()}"

    # Map admission outcome token → phase booleans.
    # We reference tokens by name string only — never import the admission
    # module's enum/constants — to maintain producer/verifier independence.
    if admission_outcome_token == "mcp_action:admitted":
        expected = True
        attempted = True
        # executed depends on whether execution itself succeeded
        executed = execution_succeeded
        # evaluated = True if execution completed (outcome was observed)
        evaluated = True if execution_succeeded is True else None
    elif admission_outcome_token in ("mcp_action:refused", "mcp_action:deferred"):
        # Action was not executed; execution phases are False (not merely unknown).
        expected = True
        attempted = True
        executed = False
        evaluated = False
    elif admission_outcome_token is None:
        # Admission outcome unknown at observation time.
        expected = None
        attempted = None
        executed = None
        evaluated = None
    else:
        # Unknown token — treat phases as unknown; caller must supply reasons.
        expected = None
        attempted = None
        executed = None
        evaluated = None

    posture, reasons = _derive_mcp_action_posture(
        expected=expected,
        attempted=attempted,
        executed=executed,
        evaluated=evaluated,
        admission_outcome_token=admission_outcome_token,
    )

    if extra_reasons:
        reasons = list(reasons) + [r for r in extra_reasons if r]

    return CoverageObservation(
        domain=domain,
        subject_ref=subject_ref,
        expected=expected,
        attempted=attempted,
        executed=executed,
        evaluated=evaluated,
        coverage_posture=posture,
        reasons=tuple(reasons),
    )


__all__ = [
    "COVERAGE_CONTRACT_ID",
    "COVERAGE_POSTURES",
    "INCOMPARABLE_INVARIANT",
    "NON_EQUIVALENCES",
    "CoverageConformanceError",
    "CoverageObservation",
    "CoveragePosture",
    "create_mcp_action_observation",
]
