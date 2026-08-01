"""Behavioral equivalence: dagr_mcp_core.lifecycle vs. the legacy dagr_mcp_lifecycle.

This is the "did the fork change lifecycle-planning behavior" proof, run in the
full dev environment (both packages installed side by side) -- distinct from
``test_core_standalone.py``, which proves the isolated core-only environment.
Compares plan *field values* structurally (``dataclasses.asdict``) rather than
by class identity, since the two packages deliberately define independent
dataclass types after the fork.
"""

from __future__ import annotations

import dataclasses
import itertools

import pytest

pytest.importorskip("dagr_mcp_lifecycle")

from dagr_mcp_core.lifecycle import core as core_v2
from dagr_mcp_core.lifecycle import models as models_v2

from dagr_mcp_lifecycle import core as core_legacy
from dagr_mcp_lifecycle import models as models_legacy


def _as_dict(value):
    if dataclasses.is_dataclass(value):
        return {k: _as_dict(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, (list, tuple)):
        return [_as_dict(v) for v in value]
    return value


ADMISSION_CASES = [
    dict(disposition="admitted", tool_class="read"),
    dict(disposition="admitted", tool_class="read", emit_read_admission_before_execution=False),
    dict(disposition="admitted", tool_class="write"),
    dict(disposition="admitted", tool_class="destructive"),
    dict(disposition="refused", refusal_ground="policy_refused"),
    dict(disposition="refused", refusal_ground="unknown_tool_fail_closed"),
    dict(disposition="refused", refusal_ground="required_sink_unavailable"),
    dict(disposition="deferred", review_object_created=True),
    dict(disposition="deferred", review_object_created=False),
]

OUTCOME_CASES = [
    dict(observation="result"),
    dict(observation="error"),
    dict(observation="exception", exception_class="ValueError"),
    dict(observation="task_submitted"),
    dict(observation="timeout"),
    dict(observation="cancellation"),
]


@pytest.mark.parametrize("case", ADMISSION_CASES)
def test_plan_admission_equivalent(case):
    plan_v2 = core_v2.plan_admission(models_v2.AdmissionRequest(**case))
    plan_legacy = core_legacy.plan_admission(models_legacy.AdmissionRequest(**case))
    assert _as_dict(plan_v2) == _as_dict(plan_legacy)


@pytest.mark.parametrize(
    "admission_case,outcome_case",
    list(itertools.product(
        [c for c in ADMISSION_CASES if c["disposition"] == "admitted"], OUTCOME_CASES
    )),
)
def test_plan_outcome_strict_equivalent(admission_case, outcome_case):
    admission_v2 = core_v2.plan_admission(models_v2.AdmissionRequest(**admission_case))
    admission_legacy = core_legacy.plan_admission(models_legacy.AdmissionRequest(**admission_case))

    outcome_v2 = core_v2.plan_outcome_strict(
        admission_v2, models_v2.ExecutionObservation(**outcome_case)
    )
    outcome_legacy = core_legacy.plan_outcome_strict(
        admission_legacy, models_legacy.ExecutionObservation(**outcome_case)
    )
    assert _as_dict(outcome_v2) == _as_dict(outcome_legacy)


def test_input_required_unsupported_in_both():
    admission_v2 = core_v2.plan_admission(models_v2.AdmissionRequest(disposition="admitted"))
    admission_legacy = core_legacy.plan_admission(models_legacy.AdmissionRequest(disposition="admitted"))

    with pytest.raises(models_v2.UnsupportedLifecycleEvent):
        core_v2.plan_outcome_strict(
            admission_v2, models_v2.ExecutionObservation(observation="input_required")
        )
    with pytest.raises(models_legacy.UnsupportedLifecycleEvent):
        core_legacy.plan_outcome_strict(
            admission_legacy, models_legacy.ExecutionObservation(observation="input_required")
        )
