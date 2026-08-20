"""Tests for ExecutionCoverage — EXEC-COVERAGE0.

Key invariants under test:
  1. Counts cannot collapse: a plan where 6/8 are admitted and 5/6 execute
     successfully is NOT the same as a plan where all 8 are refused.
  2. Admission outcome != execution completeness.
  3. Refused action != failed execution (distinct counters).
  4. No scalar quality score (coverage_digest encodes counts, not a verdict).
  5. ExecutionCoverage is additive — no imports from arcs-verify, no changes
     to SRS receipt structure.

AUTHORITY_MOVEMENT = 0.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from dagr_mcp.execution_coverage import (
    ExecutionCoverage,
    ExecutionCoverageBuilder,
    ExecutionCoverageError,
    _DIGEST_PROJECTION_KEYS,
    _VALID_ACTION_OUTCOMES,
    _compute_coverage_digest,
    build_execution_coverage,
    validate_execution_coverage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_coverage(
    *,
    planned: int = 0,
    attempted: int = 0,
    admitted: int = 0,
    refused: int = 0,
    deferred: int = 0,
    executed_successfully: int = 0,
    execution_failed: int = 0,
    not_attempted: int = 0,
    digest: str | None = None,
) -> ExecutionCoverage:
    counts = {
        "planned_action_count": planned,
        "attempted_action_count": attempted,
        "admitted_count": admitted,
        "refused_count": refused,
        "deferred_count": deferred,
        "executed_successfully_count": executed_successfully,
        "execution_failed_count": execution_failed,
        "not_attempted_count": not_attempted,
    }
    d = digest if digest is not None else _compute_coverage_digest(counts)
    return ExecutionCoverage(
        planned_action_count=planned,
        attempted_action_count=attempted,
        admitted_count=admitted,
        refused_count=refused,
        deferred_count=deferred,
        executed_successfully_count=executed_successfully,
        execution_failed_count=execution_failed,
        not_attempted_count=not_attempted,
        coverage_digest=d,
    )


# ---------------------------------------------------------------------------
# 1. Counts cannot collapse — the central non-collapse invariant
# ---------------------------------------------------------------------------

class TestNonCollapseInvariant:
    """Prove that distinct coverage distributions cannot be made equal."""

    def test_admitted_6_of_8_ne_refused_8_of_8(self):
        """6/8 admitted, 5/6 executed != 0/8 admitted (all refused)."""
        plan_a = build_execution_coverage([
            "admitted_and_executed_successfully",
            "admitted_and_executed_successfully",
            "admitted_and_executed_successfully",
            "admitted_and_executed_successfully",
            "admitted_and_executed_successfully",
            "admitted_and_execution_failed",
            "refused",
            "refused",
        ])
        plan_b = build_execution_coverage([
            "refused",
            "refused",
            "refused",
            "refused",
            "refused",
            "refused",
            "refused",
            "refused",
        ])

        assert plan_a.planned_action_count == plan_b.planned_action_count == 8
        # admitted counts differ
        assert plan_a.admitted_count == 6
        assert plan_b.admitted_count == 0
        # refused counts differ
        assert plan_a.refused_count == 2
        assert plan_b.refused_count == 8
        # execution counts differ
        assert plan_a.executed_successfully_count == 5
        assert plan_b.executed_successfully_count == 0
        # digests differ — no collapse
        assert plan_a.coverage_digest != plan_b.coverage_digest

    def test_refused_ne_execution_failed(self):
        """A refused action is NOT the same as a failed execution."""
        all_refused = build_execution_coverage(["refused", "refused", "refused"])
        all_failed = build_execution_coverage([
            "admitted_and_execution_failed",
            "admitted_and_execution_failed",
            "admitted_and_execution_failed",
        ])

        assert all_refused.planned_action_count == all_failed.planned_action_count == 3
        # They differ on every admission/execution axis
        assert all_refused.refused_count == 3
        assert all_failed.refused_count == 0
        assert all_refused.execution_failed_count == 0
        assert all_failed.execution_failed_count == 3
        assert all_refused.admitted_count == 0
        assert all_failed.admitted_count == 3
        # Digests must differ
        assert all_refused.coverage_digest != all_failed.coverage_digest

    def test_deferred_ne_refused_ne_failed(self):
        """Three distinct non-execution reasons produce three distinct distributions."""
        all_refused = build_execution_coverage(["refused"])
        all_deferred = build_execution_coverage(["deferred"])
        all_failed = build_execution_coverage(["admitted_and_execution_failed"])

        assert all_refused.refused_count == 1
        assert all_deferred.deferred_count == 1
        assert all_failed.execution_failed_count == 1

        digests = {
            all_refused.coverage_digest,
            all_deferred.coverage_digest,
            all_failed.coverage_digest,
        }
        assert len(digests) == 3, "refused/deferred/failed must produce distinct digests"

    def test_partial_plan_ne_full_refused_even_with_same_planned_count(self):
        """Partial success in a 4-action plan != all-refused 4-action plan."""
        partial = build_execution_coverage([
            "admitted_and_executed_successfully",
            "admitted_and_executed_successfully",
            "refused",
            "refused",
        ])
        all_refused = build_execution_coverage(["refused", "refused", "refused", "refused"])

        assert partial.planned_action_count == all_refused.planned_action_count == 4
        assert partial.coverage_digest != all_refused.coverage_digest


# ---------------------------------------------------------------------------
# 2. Builder accumulation
# ---------------------------------------------------------------------------

class TestBuilder:
    def test_empty_builder(self):
        builder = ExecutionCoverageBuilder()
        cov = builder.build()
        assert cov.planned_action_count == 0
        assert cov.attempted_action_count == 0
        assert cov.admitted_count == 0
        assert cov.refused_count == 0
        assert cov.deferred_count == 0
        assert cov.executed_successfully_count == 0
        assert cov.execution_failed_count == 0
        assert cov.not_attempted_count == 0
        validate_execution_coverage(cov)

    def test_all_outcome_types(self):
        builder = ExecutionCoverageBuilder()
        builder.record_action_outcome("admitted_and_executed_successfully")
        builder.record_action_outcome("admitted_and_execution_failed")
        builder.record_action_outcome("admitted_and_not_attempted")
        builder.record_action_outcome("refused")
        builder.record_action_outcome("deferred")
        cov = builder.build()

        assert cov.planned_action_count == 5
        assert cov.admitted_count == 3
        assert cov.refused_count == 1
        assert cov.deferred_count == 1
        assert cov.executed_successfully_count == 1
        assert cov.execution_failed_count == 1
        assert cov.not_attempted_count == 1
        assert cov.attempted_action_count == 3  # == admitted_count
        validate_execution_coverage(cov)

    def test_unknown_outcome_raises(self):
        builder = ExecutionCoverageBuilder()
        with pytest.raises(ExecutionCoverageError, match="unknown action outcome"):
            builder.record_action_outcome("pass")

    def test_unknown_outcome_scalar_raises(self):
        """No scalar quality labels are valid outcome keys."""
        for bad in ("pass", "fail", "ok", "success", "error", "admitted", "refused"):
            # "admitted" and "refused" alone are not valid composite outcomes
            if bad not in _VALID_ACTION_OUTCOMES:
                builder = ExecutionCoverageBuilder()
                with pytest.raises(ExecutionCoverageError):
                    builder.record_action_outcome(bad)

    def test_repeated_build_is_independent(self):
        """Each build() call from the same builder state produces equal values."""
        builder = ExecutionCoverageBuilder()
        builder.record_action_outcome("admitted_and_executed_successfully")
        cov1 = builder.build()
        cov2 = builder.build()
        assert cov1 == cov2


# ---------------------------------------------------------------------------
# 3. build_execution_coverage convenience factory
# ---------------------------------------------------------------------------

class TestFactory:
    def test_empty_sequence(self):
        cov = build_execution_coverage([])
        assert cov.planned_action_count == 0
        validate_execution_coverage(cov)

    def test_single_admitted_success(self):
        cov = build_execution_coverage(["admitted_and_executed_successfully"])
        assert cov.planned_action_count == 1
        assert cov.admitted_count == 1
        assert cov.executed_successfully_count == 1
        assert cov.refused_count == 0
        validate_execution_coverage(cov)

    def test_all_valid_outcome_strings(self):
        outcomes = list(_VALID_ACTION_OUTCOMES)
        cov = build_execution_coverage(outcomes)
        assert cov.planned_action_count == len(outcomes)
        validate_execution_coverage(cov)

    def test_invalid_outcome_string_raises(self):
        with pytest.raises(ExecutionCoverageError):
            build_execution_coverage(["admitted_and_executed_successfully", "PASS"])


# ---------------------------------------------------------------------------
# 4. Digest determinism and stability
# ---------------------------------------------------------------------------

class TestDigest:
    def test_digest_is_deterministic(self):
        cov1 = build_execution_coverage(["admitted_and_executed_successfully", "refused"])
        cov2 = build_execution_coverage(["admitted_and_executed_successfully", "refused"])
        assert cov1.coverage_digest == cov2.coverage_digest

    def test_digest_starts_with_sha256(self):
        cov = build_execution_coverage(["refused"])
        assert cov.coverage_digest.startswith("sha256:")

    def test_digest_changes_when_counts_change(self):
        cov_refused = build_execution_coverage(["refused"])
        cov_success = build_execution_coverage(["admitted_and_executed_successfully"])
        assert cov_refused.coverage_digest != cov_success.coverage_digest

    def test_digest_projection_key_order_frozen(self):
        """Projection key order must not change — historical digests are byte-pinned evidence."""
        expected_order = (
            "planned_action_count",
            "attempted_action_count",
            "admitted_count",
            "refused_count",
            "deferred_count",
            "executed_successfully_count",
            "execution_failed_count",
            "not_attempted_count",
        )
        assert _DIGEST_PROJECTION_KEYS == expected_order

    def test_digest_is_stable_across_calls(self):
        counts = {k: 0 for k in _DIGEST_PROJECTION_KEYS}
        counts["planned_action_count"] = 3
        counts["admitted_count"] = 2
        counts["attempted_action_count"] = 2
        counts["refused_count"] = 1
        counts["executed_successfully_count"] = 2
        d1 = _compute_coverage_digest(counts)
        d2 = _compute_coverage_digest(counts)
        assert d1 == d2
        assert d1.startswith("sha256:")


# ---------------------------------------------------------------------------
# 5. validate_execution_coverage
# ---------------------------------------------------------------------------

class TestValidation:
    def test_valid_empty_coverage(self):
        cov = build_execution_coverage([])
        validate_execution_coverage(cov)  # must not raise

    def test_valid_mixed_coverage(self):
        cov = build_execution_coverage([
            "admitted_and_executed_successfully",
            "admitted_and_execution_failed",
            "refused",
            "deferred",
        ])
        validate_execution_coverage(cov)

    def test_negative_count_fails(self):
        counts = {k: 0 for k in _DIGEST_PROJECTION_KEYS}
        cov = ExecutionCoverage(
            planned_action_count=-1,
            attempted_action_count=0,
            admitted_count=0,
            refused_count=0,
            deferred_count=0,
            executed_successfully_count=0,
            execution_failed_count=0,
            not_attempted_count=0,
            coverage_digest=_compute_coverage_digest({**counts, "planned_action_count": -1}),
        )
        with pytest.raises(ExecutionCoverageError, match="planned_action_count must be >= 0"):
            validate_execution_coverage(cov)

    def test_attempted_ne_admitted_fails(self):
        # Build valid counts manually and then tamper
        cov = build_execution_coverage(["admitted_and_executed_successfully"])
        # Manufacture an artifact with attempted != admitted
        counts = {k: 0 for k in _DIGEST_PROJECTION_KEYS}
        counts["planned_action_count"] = 1
        counts["attempted_action_count"] = 99  # tampered
        counts["admitted_count"] = 1
        counts["executed_successfully_count"] = 1
        tampered = ExecutionCoverage(
            planned_action_count=1,
            attempted_action_count=99,
            admitted_count=1,
            refused_count=0,
            deferred_count=0,
            executed_successfully_count=1,
            execution_failed_count=0,
            not_attempted_count=0,
            coverage_digest=_compute_coverage_digest(counts),
        )
        with pytest.raises(ExecutionCoverageError, match="attempted_action_count"):
            validate_execution_coverage(tampered)

    def test_admitted_total_mismatch_fails(self):
        counts = {k: 0 for k in _DIGEST_PROJECTION_KEYS}
        counts["planned_action_count"] = 2
        counts["attempted_action_count"] = 2
        counts["admitted_count"] = 2
        # executed_successfully + execution_failed + not_attempted == 1, not 2
        counts["executed_successfully_count"] = 1
        tampered = ExecutionCoverage(
            planned_action_count=2,
            attempted_action_count=2,
            admitted_count=2,
            refused_count=0,
            deferred_count=0,
            executed_successfully_count=1,
            execution_failed_count=0,
            not_attempted_count=0,
            coverage_digest=_compute_coverage_digest(counts),
        )
        with pytest.raises(ExecutionCoverageError, match="admitted_count"):
            validate_execution_coverage(tampered)

    def test_planned_total_mismatch_fails(self):
        counts = {k: 0 for k in _DIGEST_PROJECTION_KEYS}
        counts["planned_action_count"] = 5  # claimed 5
        counts["attempted_action_count"] = 1
        counts["admitted_count"] = 1
        counts["refused_count"] = 1
        # admitted(1) + refused(1) = 2, not 5
        counts["executed_successfully_count"] = 1
        tampered = ExecutionCoverage(
            planned_action_count=5,
            attempted_action_count=1,
            admitted_count=1,
            refused_count=1,
            deferred_count=0,
            executed_successfully_count=1,
            execution_failed_count=0,
            not_attempted_count=0,
            coverage_digest=_compute_coverage_digest(counts),
        )
        with pytest.raises(ExecutionCoverageError, match="planned_action_count"):
            validate_execution_coverage(tampered)

    def test_digest_mismatch_fails(self):
        cov = build_execution_coverage(["refused"])
        # Manufacture a coverage with a wrong digest
        tampered = ExecutionCoverage(
            planned_action_count=cov.planned_action_count,
            attempted_action_count=cov.attempted_action_count,
            admitted_count=cov.admitted_count,
            refused_count=cov.refused_count,
            deferred_count=cov.deferred_count,
            executed_successfully_count=cov.executed_successfully_count,
            execution_failed_count=cov.execution_failed_count,
            not_attempted_count=cov.not_attempted_count,
            coverage_digest="sha256:" + "0" * 64,  # wrong
        )
        with pytest.raises(ExecutionCoverageError, match="coverage_digest mismatch"):
            validate_execution_coverage(tampered)


# ---------------------------------------------------------------------------
# 6. as_dict projection
# ---------------------------------------------------------------------------

class TestAsDict:
    def test_as_dict_keys_present(self):
        cov = build_execution_coverage(["admitted_and_executed_successfully", "refused"])
        d = cov.as_dict()
        expected_keys = {
            "planned_action_count",
            "attempted_action_count",
            "admitted_count",
            "refused_count",
            "deferred_count",
            "executed_successfully_count",
            "execution_failed_count",
            "not_attempted_count",
            "coverage_digest",
        }
        assert set(d.keys()) == expected_keys

    def test_as_dict_no_scalar_quality_score(self):
        """The dict projection must not contain any scalar quality verdict."""
        cov = build_execution_coverage(["admitted_and_executed_successfully"])
        d = cov.as_dict()
        for key in d:
            assert key not in {"pass", "fail", "ok", "verdict", "quality", "score"}

    def test_as_dict_values_match_attributes(self):
        cov = build_execution_coverage([
            "admitted_and_executed_successfully",
            "admitted_and_execution_failed",
            "refused",
            "deferred",
        ])
        d = cov.as_dict()
        assert d["planned_action_count"] == cov.planned_action_count
        assert d["admitted_count"] == cov.admitted_count
        assert d["refused_count"] == cov.refused_count
        assert d["deferred_count"] == cov.deferred_count
        assert d["executed_successfully_count"] == cov.executed_successfully_count
        assert d["execution_failed_count"] == cov.execution_failed_count
        assert d["coverage_digest"] == cov.coverage_digest


# ---------------------------------------------------------------------------
# 7. No SRS receipt structure modified — isolation check
# ---------------------------------------------------------------------------

class TestIsolation:
    def test_no_srs_receipt_import(self):
        """ExecutionCoverage must not import arcs-verify or receipt signing code."""
        import dagr_mcp.execution_coverage as ec_module
        import inspect
        src = inspect.getsource(ec_module)
        # Should not import arcs_verify
        assert "arcs_verify" not in src
        assert "import arcs_verify" not in src

    def test_srs_receipts_module_unchanged(self):
        """Importing execution_coverage must not mutate srs_receipts module state."""
        import dagr_mcp.srs_receipts as srs
        before_attrs = set(dir(srs))
        import dagr_mcp.execution_coverage  # noqa: F401
        after_attrs = set(dir(srs))
        assert before_attrs == after_attrs

    def test_execution_coverage_not_in_srs_receipts(self):
        """ExecutionCoverage must not appear in srs_receipts.__all__."""
        import dagr_mcp.srs_receipts as srs
        all_names = getattr(srs, "__all__", [])
        assert "ExecutionCoverage" not in all_names
        assert "ExecutionCoverageBuilder" not in all_names

    def test_no_authority_movement(self):
        """Module docstring asserts AUTHORITY_MOVEMENT = 0."""
        import dagr_mcp.execution_coverage as ec_module
        assert "AUTHORITY_MOVEMENT = 0" in (ec_module.__doc__ or "")
