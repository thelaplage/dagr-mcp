"""Sprint A5 coverage ledger — a coverage proof, not a new conformance harness.

Every A5-required lifecycle scenario is mapped, explicitly, to the three places it
must be covered:

* an **official-SDK real-transport / live-adapter** test
  (``tests/test_official_mcp_sdk_binding.py``);
* a **FastMCP equivalent** test (the frozen binding's behavior);
* a **cross-binding** entry — either a byte-equality scenario in the shared
  conformance corpus (``tests/test_cross_binding_conformance.py`` ``SCENARIOS``),
  or, for a capability that is not byte-identical across bindings, an explicit
  test recording the difference / the unsupported capability.

This module does not re-run those tests; it asserts the ledger is faithful — that
every referenced test callable and every referenced corpus scenario actually
exists. If a scenario's coverage is renamed or deleted, this ledger fails, so the
mapping cannot silently rot. ``task_submitted`` and ``input_required`` are the two
capability-difference rows: they are covered by explicit unsupported /
capability-difference tests rather than a byte-equality corpus scenario.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

pytest.importorskip("mcp")
pytest.importorskip("fastmcp")

import tests.test_behavioral_freeze as freeze
import tests.test_cross_binding_conformance as cross
import tests.test_fastmcp_binding as fmcp
import tests.test_fastmcp_core_rebinding as fcore
import tests.test_official_mcp_sdk_binding as sdk

# Test-module registry for the ledger's references.
_MODULES = {
    "sdk": sdk,
    "fmcp": fmcp,
    "fcore": fcore,
    "freeze": freeze,
    "cross": cross,
}


@dataclass(frozen=True)
class LedgerRow:
    scenario: str
    # (module_alias, test_function_name) references proving official-SDK coverage.
    sdk_tests: tuple[tuple[str, str], ...]
    # (module_alias, test_function_name) references proving FastMCP coverage.
    fastmcp_tests: tuple[tuple[str, str], ...]
    # Either ("scenario", name) — a byte-equality corpus scenario — or
    # ("test", func) — an explicit capability-difference / unsupported test.
    cross_binding: tuple[str, str]


# --------------------------------------------------------------------------- #
# The ledger                                                                  #
# --------------------------------------------------------------------------- #

LEDGER: tuple[LedgerRow, ...] = (
    LedgerRow(
        "admitted read",
        (("sdk", "test_admitted_call_produces_admission_and_outcome"),
         ("sdk", "test_tools_call_reaches_adapter_and_invokes_core")),
        (("fmcp", "test_normal_async_tool_emits_admission_and_result_outcome"),),
        ("scenario", "admitted_read"),
    ),
    LedgerRow(
        "admitted write",
        (("sdk", "test_admitted_call_produces_admission_and_outcome"),),
        (("fmcp", "test_normal_async_tool_emits_admission_and_result_outcome"),),
        ("scenario", "admitted_write"),
    ),
    LedgerRow(
        "refusal",
        (("sdk", "test_policy_refusal_emits_one_admission_and_never_executes"),),
        (("fmcp", "test_policy_refusal_never_executes_handler"),),
        ("scenario", "policy_refusal"),
    ),
    LedgerRow(
        "deferred review",
        (("sdk", "test_deferred_emits_review_admission_and_never_executes"),),
        (("fmcp", "test_review_required_creates_object_and_never_parks_request"),),
        ("scenario", "deferred_for_review"),
    ),
    LedgerRow(
        "review-object creation failure",
        (("sdk", "test_review_object_creation_failure_is_refused_with_frozen_ground"),),
        (("fmcp", "test_review_object_creation_failure_is_terminal_refusal"),),
        ("scenario", "review_object_creation_failure"),
    ),
    LedgerRow(
        "result",
        (("sdk", "test_admitted_call_produces_admission_and_outcome"),),
        (("fmcp", "test_normal_async_tool_emits_admission_and_result_outcome"),),
        ("scenario", "result_returned"),
    ),
    LedgerRow(
        "tool-level error",
        (("sdk", "test_error_tool_result_is_error_returned"),),
        (("fmcp", "test_error_tool_result_is_classified_error_returned"),),
        ("scenario", "error_returned"),
    ),
    LedgerRow(
        "ordinary exception",
        (("sdk", "test_raised_exception_invokes_core_and_records_exception"),),
        (("fmcp", "test_raised_tool_error_is_exception_outcome_and_propagates"),),
        ("scenario", "raised_exception"),
    ),
    LedgerRow(
        "TimeoutError",
        (("sdk", "test_raised_timeout_is_subsumed_to_exception_timeouterror"),),
        (("fmcp", "test_timeout_does_not_record_success_after_effect_may_have_happened"),
         ("fcore", "test_raised_timeout_is_recorded_as_exception_class_timeouterror")),
        ("scenario", "raised_timeout"),
    ),
    LedgerRow(
        "task_submitted (explicitly unsupported on official-SDK; supported on FastMCP)",
        (("sdk", "test_task_submission_is_unsupported_and_fails_closed"),
         ("sdk", "test_task_submission_unsupported_over_real_transport"),
         ("sdk", "test_bound_tools_call_seam_cannot_carry_create_task_result")),
        (("fmcp", "test_create_task_result_emits_task_submitted_only"),),
        ("test", "test_task_submitted_is_an_explicit_binding_capability_difference"),
    ),
    LedgerRow(
        "cancellation",
        (("sdk", "test_cancellation_invokes_core_and_records_indeterminate"),),
        (("fmcp", "test_cancelled_call_gets_best_effort_indeterminate_and_reraises"),),
        ("scenario", "cancellation"),
    ),
    LedgerRow(
        "required_sink_unavailable",
        (("sdk", "test_required_sink_unavailable_is_preserved_like_the_freeze"),),
        (("freeze", "test_freeze_gate_without_review_sink_reason_code"),),
        ("scenario", "required_sink_unavailable"),
    ),
    LedgerRow(
        "input_required — both modes explicitly unsupported",
        (("sdk", "test_unsupported_input_required_fails_explicitly"),),
        (("fcore", "test_input_required_remains_explicitly_unsupported"),
         ("fcore", "test_input_required_cannot_enter_the_outcome_fallback")),
        ("test", "test_input_required_unsupported_in_both_bindings"),
    ),
)

# The exact set of A5-required scenarios this ledger must cover (the sprint list).
REQUIRED_SCENARIOS = frozenset(
    {
        "admitted read",
        "admitted write",
        "refusal",
        "deferred review",
        "review-object creation failure",
        "result",
        "tool-level error",
        "ordinary exception",
        "TimeoutError",
        "task_submitted (explicitly unsupported on official-SDK; supported on FastMCP)",
        "cancellation",
        "required_sink_unavailable",
        "input_required — both modes explicitly unsupported",
    }
)


def _resolve(ref: tuple[str, str]):
    module_alias, name = ref
    module = _MODULES[module_alias]
    return getattr(module, name, None)


def test_ledger_covers_every_required_scenario():
    covered = {row.scenario for row in LEDGER}
    assert covered == REQUIRED_SCENARIOS, (
        covered ^ REQUIRED_SCENARIOS,
    )
    # No duplicate rows.
    assert len(covered) == len(LEDGER)


@pytest.mark.parametrize("row", LEDGER, ids=lambda r: r.scenario)
def test_every_ledger_reference_exists(row: LedgerRow):
    # Official-SDK real-transport / live-adapter coverage exists.
    assert row.sdk_tests, row.scenario
    for ref in row.sdk_tests:
        assert callable(_resolve(ref)), ("missing SDK test", row.scenario, ref)

    # FastMCP equivalent coverage exists.
    assert row.fastmcp_tests, row.scenario
    for ref in row.fastmcp_tests:
        assert callable(_resolve(ref)), ("missing FastMCP test", row.scenario, ref)

    # Cross-binding coverage: a corpus scenario, or an explicit test.
    kind, value = row.cross_binding
    if kind == "scenario":
        names = {s.name for s in cross.SCENARIOS}
        assert value in names, ("missing corpus scenario", row.scenario, value)
    elif kind == "test":
        assert callable(getattr(cross, value, None)), (
            "missing explicit cross-binding test",
            row.scenario,
            value,
        )
    else:  # pragma: no cover - guards the ledger's own shape.
        raise AssertionError(("bad cross-binding kind", kind))


def test_capability_difference_rows_are_not_in_the_byte_equality_corpus():
    """task_submitted / input_required must NOT be byte-equality corpus scenarios.

    They are genuine capability differences; folding them into the byte-equality
    corpus would falsely claim the two bindings agree. They are covered by explicit
    tests instead — which is exactly what the ledger records.
    """

    corpus_names = {s.name for s in cross.SCENARIOS}
    assert "task_submitted" not in corpus_names
    assert "input_required" not in corpus_names
    for row in LEDGER:
        if row.scenario.startswith("task_submitted") or row.scenario.startswith(
            "input_required"
        ):
            assert row.cross_binding[0] == "test", row.scenario
