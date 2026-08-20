"""Tests for dagr_mcp.coverage — dagr.coverage.v0.1 conformance.

Coverage: CR-COV-03 enforcement, posture derivation, NEQ assertions,
INCOMPARABLE invariant, domain namespace rule.

ADDITIVE ONLY: these tests import nothing from the admission/lifecycle modules
to avoid blurring the producer/verifier independence boundary.
"""

from __future__ import annotations

import pytest

from dagr_mcp.coverage import (
    COVERAGE_CONTRACT_ID,
    COVERAGE_POSTURES,
    INCOMPARABLE_INVARIANT,
    NON_EQUIVALENCES,
    CoverageConformanceError,
    CoverageObservation,
    create_mcp_action_observation,
)


# --------------------------------------------------------------------------- #
# Contract identity                                                           #
# --------------------------------------------------------------------------- #


def test_contract_id() -> None:
    assert COVERAGE_CONTRACT_ID == "dagr.coverage.v0.1"


def test_posture_set() -> None:
    assert set(COVERAGE_POSTURES) == {"complete", "partial", "not_evaluated", "incomparable"}


# --------------------------------------------------------------------------- #
# CR-COV-03 enforcement                                                       #
# --------------------------------------------------------------------------- #


def test_cr_cov_03_partial_empty_reasons_raises() -> None:
    """CR-COV-03: partial posture with empty reasons must raise."""
    with pytest.raises(CoverageConformanceError, match="CR-COV-03"):
        CoverageObservation(
            domain="mcp_action",
            subject_ref="tool:some_tool",
            expected=True,
            attempted=True,
            executed=False,
            evaluated=False,
            coverage_posture="partial",
            reasons=(),
        )


def test_cr_cov_03_not_evaluated_empty_reasons_raises() -> None:
    """CR-COV-03: not_evaluated posture with empty reasons must raise."""
    with pytest.raises(CoverageConformanceError, match="CR-COV-03"):
        CoverageObservation(
            domain="mcp_action",
            subject_ref="tool:some_tool",
            expected=None,
            attempted=None,
            executed=None,
            evaluated=None,
            coverage_posture="not_evaluated",
            reasons=(),
        )


def test_cr_cov_03_incomparable_empty_reasons_raises() -> None:
    """CR-COV-03: incomparable posture with empty reasons must raise."""
    with pytest.raises(CoverageConformanceError, match="CR-COV-03"):
        CoverageObservation(
            domain="mcp_action",
            subject_ref="tool:some_tool",
            expected=True,
            attempted=True,
            executed=True,
            evaluated=True,
            coverage_posture="incomparable",
            reasons=(),
        )


def test_cr_cov_03_complete_empty_reasons_passes() -> None:
    """CR-COV-03: complete posture with empty reasons is valid."""
    obs = CoverageObservation(
        domain="mcp_action",
        subject_ref="tool:my_tool",
        expected=True,
        attempted=True,
        executed=True,
        evaluated=True,
        coverage_posture="complete",
        reasons=(),
    )
    assert obs.coverage_posture == "complete"
    assert obs.reasons == ()


def test_cr_cov_03_partial_with_reasons_passes() -> None:
    """CR-COV-03: partial posture with non-empty reasons is valid."""
    obs = CoverageObservation(
        domain="mcp_action",
        subject_ref="tool:my_tool",
        expected=True,
        attempted=True,
        executed=False,
        evaluated=False,
        coverage_posture="partial",
        reasons=("phase_executed_false",),
    )
    assert obs.coverage_posture == "partial"
    assert len(obs.reasons) >= 1


def test_cr_cov_03_not_evaluated_with_reasons_passes() -> None:
    """CR-COV-03: not_evaluated posture with non-empty reasons is valid."""
    obs = CoverageObservation(
        domain="mcp_action",
        subject_ref="tool:my_tool",
        expected=None,
        attempted=None,
        executed=None,
        evaluated=None,
        coverage_posture="not_evaluated",
        reasons=("phase_expected_unknown", "phase_attempted_unknown"),
    )
    assert obs.coverage_posture == "not_evaluated"
    assert len(obs.reasons) >= 1


def test_cr_cov_03_incomparable_with_reasons_passes() -> None:
    """CR-COV-03: incomparable posture with non-empty reasons is valid."""
    obs = CoverageObservation(
        domain="mcp_action",
        subject_ref="tool:my_tool",
        expected=True,
        attempted=True,
        executed=True,
        evaluated=True,
        coverage_posture="incomparable",
        reasons=("phase_combination_not_comparable",),
    )
    assert obs.coverage_posture == "incomparable"
    assert len(obs.reasons) >= 1


# --------------------------------------------------------------------------- #
# Factory: complete posture (all phases True)                                 #
# --------------------------------------------------------------------------- #


def test_factory_admitted_executed_complete() -> None:
    """Admitted + execution_succeeded=True → complete posture, empty reasons."""
    obs = create_mcp_action_observation(
        "fetch_data",
        admission_outcome_token="mcp_action:admitted",
        execution_succeeded=True,
    )
    assert obs.coverage_posture == "complete"
    assert obs.reasons == ()
    assert obs.domain == "mcp_action"
    assert obs.subject_ref == "tool:fetch_data"
    assert obs.expected is True
    assert obs.attempted is True
    assert obs.executed is True
    assert obs.evaluated is True


# --------------------------------------------------------------------------- #
# Factory: partial posture (refused/deferred)                                 #
# --------------------------------------------------------------------------- #


def test_factory_refused_partial() -> None:
    """Refused action → partial posture (executed=False, evaluated=False)."""
    obs = create_mcp_action_observation(
        "delete_record",
        admission_outcome_token="mcp_action:refused",
    )
    assert obs.coverage_posture == "partial"
    assert obs.executed is False
    assert obs.evaluated is False
    assert len(obs.reasons) >= 1
    # NEQ-COV-03: incomparable ≠ refused — refused produces partial, not incomparable
    assert obs.coverage_posture != "incomparable"


def test_factory_deferred_partial() -> None:
    """Deferred action → partial posture."""
    obs = create_mcp_action_observation(
        "send_message",
        admission_outcome_token="mcp_action:deferred",
    )
    assert obs.coverage_posture == "partial"
    assert obs.executed is False
    assert len(obs.reasons) >= 1


def test_factory_admitted_execution_failed_partial() -> None:
    """Admitted but execution_succeeded=False → partial (executed=False)."""
    obs = create_mcp_action_observation(
        "write_file",
        admission_outcome_token="mcp_action:admitted",
        execution_succeeded=False,
    )
    assert obs.coverage_posture == "partial"
    assert obs.executed is False
    assert len(obs.reasons) >= 1


# --------------------------------------------------------------------------- #
# Factory: not_evaluated posture (unknown admission)                          #
# --------------------------------------------------------------------------- #


def test_factory_unknown_admission_not_evaluated() -> None:
    """No admission token → not_evaluated, all phases None."""
    obs = create_mcp_action_observation("inspect_tool")
    assert obs.coverage_posture == "not_evaluated"
    assert obs.expected is None
    assert obs.attempted is None
    assert obs.executed is None
    assert obs.evaluated is None
    assert len(obs.reasons) >= 1
    # NEQ-COV-04: not_evaluated ≠ verifier:pass
    assert obs.coverage_posture != "verifier:pass"  # type-level, always true; documents NEQ


# --------------------------------------------------------------------------- #
# Domain namespace rule                                                       #
# --------------------------------------------------------------------------- #


def test_domain_is_mcp_action_not_bare() -> None:
    """domain must be 'mcp_action', not a bare lifecycle disposition token."""
    obs = create_mcp_action_observation(
        "read_file",
        admission_outcome_token="mcp_action:admitted",
        execution_succeeded=True,
    )
    # Domain namespace rule: use qualified domain, not bare disposition tokens.
    assert obs.domain == "mcp_action"
    assert obs.domain not in ("admitted", "refused", "deferred")


def test_subject_ref_format() -> None:
    """subject_ref uses 'tool:<tool_name>' format."""
    obs = create_mcp_action_observation(
        "my_tool",
        admission_outcome_token="mcp_action:admitted",
        execution_succeeded=True,
    )
    assert obs.subject_ref == "tool:my_tool"


# --------------------------------------------------------------------------- #
# INCOMPARABLE invariant                                                      #
# --------------------------------------------------------------------------- #


def test_incomparable_invariant_keys() -> None:
    """INCOMPARABLE_INVARIANT must document both 'incomparable' and 'diff_incomparable'."""
    assert "incomparable" in INCOMPARABLE_INVARIANT
    assert "diff_incomparable" in INCOMPARABLE_INVARIANT


def test_incomparable_vs_diff_incomparable_distinct() -> None:
    """
    'incomparable' and 'diff_incomparable' are DISTINCT concepts:
      - incomparable: single-observation posture (this obs cannot be compared)
      - diff_incomparable: cross-observation aggregate (different obs types)
    They must not be conflated. A single CoverageObservation with posture
    'incomparable' does NOT imply a cross-observation diff_incomparable verdict.
    """
    # Single-observation: incomparable is a CoveragePosture value
    assert "incomparable" in COVERAGE_POSTURES
    # Cross-observation: diff_incomparable is NOT a CoveragePosture value
    assert "diff_incomparable" not in COVERAGE_POSTURES
    # Their descriptions must be present and distinct
    inc_desc = INCOMPARABLE_INVARIANT["incomparable"]
    diff_desc = INCOMPARABLE_INVARIANT["diff_incomparable"]
    assert inc_desc != diff_desc
    assert "single" in inc_desc.lower() or "individual" in inc_desc.lower()
    assert "cross" in diff_desc.lower() or "collection" in diff_desc.lower()


# --------------------------------------------------------------------------- #
# NEQ assertions (NEQ-COV-01 through NEQ-COV-07)                             #
# --------------------------------------------------------------------------- #


def test_neq_all_seven_present() -> None:
    """All seven NEQ entries must be present in NON_EQUIVALENCES."""
    for key in (
        "NEQ-COV-01",
        "NEQ-COV-02",
        "NEQ-COV-03",
        "NEQ-COV-04",
        "NEQ-COV-05",
        "NEQ-COV-06",
        "NEQ-COV-07",
    ):
        assert key in NON_EQUIVALENCES, f"Missing NEQ entry: {key}"


def test_neq_cov_01_complete_ne_admitted() -> None:
    """NEQ-COV-01: coverage:complete ≠ mcp_action:admitted."""
    lhs, rhs, _ = NON_EQUIVALENCES["NEQ-COV-01"]
    assert lhs == "coverage:complete"
    assert rhs == "mcp_action:admitted"
    # Runtime check: an admitted action whose execution is unknown is NOT complete.
    obs = create_mcp_action_observation(
        "tool_x",
        admission_outcome_token="mcp_action:admitted",
        execution_succeeded=None,
    )
    # admitted but execution unknown → not_evaluated (not complete)
    assert obs.coverage_posture != "complete"


def test_neq_cov_03_incomparable_ne_refused() -> None:
    """NEQ-COV-03: coverage:incomparable ≠ mcp_action:refused."""
    obs = create_mcp_action_observation(
        "tool_y",
        admission_outcome_token="mcp_action:refused",
    )
    # A refused action produces partial, not incomparable.
    assert obs.coverage_posture != "incomparable"


def test_neq_cov_04_not_evaluated_ne_verifier_pass() -> None:
    """NEQ-COV-04: coverage:not_evaluated ≠ verifier:pass (semantic boundary)."""
    obs = create_mcp_action_observation("tool_z")
    assert obs.coverage_posture == "not_evaluated"
    # not_evaluated is not a pass; the reasons field must explain why.
    assert len(obs.reasons) >= 1


# --------------------------------------------------------------------------- #
# Validation guards                                                           #
# --------------------------------------------------------------------------- #


def test_empty_tool_name_raises() -> None:
    with pytest.raises(CoverageConformanceError):
        create_mcp_action_observation("")


def test_empty_domain_raises() -> None:
    with pytest.raises(CoverageConformanceError):
        CoverageObservation(
            domain="",
            subject_ref="tool:x",
            expected=True,
            attempted=True,
            executed=True,
            evaluated=True,
            coverage_posture="complete",
            reasons=(),
        )


def test_invalid_posture_raises() -> None:
    with pytest.raises(CoverageConformanceError):
        CoverageObservation(
            domain="mcp_action",
            subject_ref="tool:x",
            expected=True,
            attempted=True,
            executed=True,
            evaluated=True,
            coverage_posture="unknown_posture",  # type: ignore[arg-type]
            reasons=(),
        )


def test_extra_reasons_appended() -> None:
    """extra_reasons are appended to derived reasons."""
    obs = create_mcp_action_observation(
        "my_tool",
        admission_outcome_token="mcp_action:refused",
        extra_reasons=["caller_context_note"],
    )
    assert "caller_context_note" in obs.reasons


def test_observation_is_frozen() -> None:
    """CoverageObservation is immutable."""
    obs = create_mcp_action_observation(
        "my_tool",
        admission_outcome_token="mcp_action:admitted",
        execution_succeeded=True,
    )
    with pytest.raises((AttributeError, TypeError)):
        obs.domain = "other"  # type: ignore[misc]
