"""Sprint A4 — proof that the live FastMCP path is rebound onto the neutral core.

These tests are the A4 rebinding proof. They demonstrate, without regenerating a
single A1 golden, that:

* the live ``dagr_mcp.fastmcp_binding`` path imports and *invokes* the A3 core
  (:mod:`dagr_mcp_lifecycle.core`) for its lifecycle decisions;
* the admission decision literals that used to be encoded independently in the
  production adapter are gone — the core is the sole admission authority, and the
  adapter obeys the plan it returns;
* the only lifecycle literals left inline in ``on_call_tool`` are the A1-frozen
  cancellation/exception *binding projections*, and those are proved byte-equal
  to what the core plan projects through the A2 mask;
* the neutral core still imports no FastMCP / binding package;
* the frozen fail-closed and cardinality observables are unchanged.

The differential oracle ``_former_admission_decision`` reproduces the pre-A4
production decision tree for comparison against the core plan. It is test-only —
it is deliberately NOT a second production authority.
"""

from __future__ import annotations

import asyncio
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastmcp")

from fastmcp.exceptions import ToolError
from fastmcp.tools.base import ToolResult

from dagr_mcp import fastmcp_binding
from dagr_mcp_lifecycle import binding_mask, contract, core
from dagr_mcp_lifecycle.core import plan_admission, plan_outcome_strict
from dagr_mcp_lifecycle.models import (
    AdmissionRequest,
    ExecutionObservation,
    OutcomePlan,
    OutcomeRecordIntent,
    UnsupportedLifecycleEvent,
)

from tests.test_fastmcp_binding import (
    build_binding,
    call_direct,
    read_receipts,
    split_pair,
)


# --------------------------------------------------------------------------- #
# 1. The live path imports AND invokes the A3 core                            #
# --------------------------------------------------------------------------- #


def test_live_fastmcp_path_imports_the_core_planners():
    """The binding's ``plan_admission`` / ``plan_outcome_strict`` are the core's."""

    assert fastmcp_binding.plan_admission is core.plan_admission
    assert fastmcp_binding.plan_outcome_strict is core.plan_outcome_strict
    assert fastmcp_binding.plan_admission.__module__ == "dagr_mcp_lifecycle.core"


async def test_on_call_tool_invokes_the_core_for_admission_and_outcome(
    monkeypatch, tmp_path: Path
):
    """An admitted call routes both its admission and outcome through the core."""

    seen = {"admission": 0, "outcome": 0}
    real_admission = fastmcp_binding.plan_admission
    real_outcome = fastmcp_binding.plan_outcome_strict

    def spy_admission(request):
        seen["admission"] += 1
        return real_admission(request)

    def spy_outcome(plan, observation):
        seen["outcome"] += 1
        return real_outcome(plan, observation)

    monkeypatch.setattr(fastmcp_binding, "plan_admission", spy_admission)
    monkeypatch.setattr(fastmcp_binding, "plan_outcome_strict", spy_outcome)

    middleware, _identity, directory = build_binding(
        tmp_path, tool_classes={"t.read": "read"}
    )
    await call_direct(middleware, "t.read", ToolResult(content="ok"))

    assert seen == {"admission": 1, "outcome": 1}
    # And the observable is unchanged: exactly the admission+outcome pair.
    kinds = sorted(r["receipt_kind"] for r in read_receipts(directory))
    assert kinds == ["admission", "outcome"]


async def test_core_plan_is_authoritative_for_execution_proceeds(
    monkeypatch, tmp_path: Path
):
    """If the core says a call does not proceed, the adapter refuses it.

    The policy resolver still returns ``admitted``; only the core plan is forced
    to a refusal. The adapter honours the plan — proof the core, not a shadow
    branch in the adapter, drives whether execution proceeds.
    """

    def forced_refusal(_request):
        return plan_admission(
            AdmissionRequest("refused", refusal_ground="policy_refused")
        )

    monkeypatch.setattr(fastmcp_binding, "plan_admission", forced_refusal)

    middleware, _identity, directory = build_binding(
        tmp_path, tool_classes={"t.read": "read"}
    )
    with pytest.raises(ToolError, match="Call refused by admission policy"):
        await call_direct(middleware, "t.read", ToolResult(content="never"))

    receipts = read_receipts(directory)
    assert len(receipts) == 1
    assert receipts[0]["receipt_kind"] == "admission"
    assert receipts[0]["disposition"] == "refused"
    assert receipts[0]["reason_code"] == "policy_refused"


async def test_core_plan_is_authoritative_for_admission_recorded(
    monkeypatch, tmp_path: Path
):
    """If the core plans no admission record, the adapter emits nothing at all."""

    def forced_skip(_request):
        return plan_admission(
            AdmissionRequest(
                "admitted",
                tool_class="read",
                emit_read_admission_before_execution=False,
            )
        )

    monkeypatch.setattr(fastmcp_binding, "plan_admission", forced_skip)

    middleware, _identity, directory = build_binding(
        tmp_path, tool_classes={"t.read": "read"}
    )
    result = await call_direct(middleware, "t.read", ToolResult(content="ok"))
    assert result is not None
    assert read_receipts(directory) == []


# --------------------------------------------------------------------------- #
# 2. The admission decision literals are gone from the production adapter      #
# --------------------------------------------------------------------------- #


def test_admission_decision_literals_no_longer_encoded_in_adapter():
    """The pre-A4 admission decision tree is no longer independently encoded."""

    source = inspect.getsource(fastmcp_binding.DAGRMiddleware.on_call_tool)

    # The disposition branch literals and the review-failure reason literal used
    # to live here; they now live in the core.
    assert 'disposition == "refused"' not in source
    assert 'disposition == "deferred_for_review"' not in source
    assert '"review_object_creation_failed"' not in source
    assert '"retry_after_approval"' not in source
    assert 'reason_code="policy_refused"' not in source
    assert 'reason_code=policy.reason_code or "policy_refused"' not in source

    # The independent "must record admission before execution" predicate is gone.
    assert not hasattr(fastmcp_binding.DAGRMiddleware, "_must_emit_admission_before_execution")
    # The old side-effect helpers are replaced by the neutral projection helpers.
    assert not hasattr(fastmcp_binding.DAGRMiddleware, "_emit_terminal_refusal")
    assert not hasattr(fastmcp_binding.DAGRMiddleware, "_defer_for_review")
    assert hasattr(fastmcp_binding.DAGRMiddleware, "_neutral_admission_request")
    assert hasattr(fastmcp_binding.DAGRMiddleware, "_project_terminal_admission")
    assert hasattr(fastmcp_binding.DAGRMiddleware, "_emit_planned_outcome")

    # The adapter reaches the core planners by name.
    assert "plan_admission(" in source
    assert "_emit_planned_outcome(" in source


def test_result_error_task_tokens_come_from_the_mask_not_inline_literals():
    """The result/error/task outcome family is classified neutrally, then projected.

    The pre-A4 ``outcome = "error_returned" if projection["isError"] else
    "result_returned"`` classification ternary and the inline
    ``outcome="task_submitted"`` emit are gone; the adapter now names a neutral
    ExecutionObservation and lets the core+mask project the binding token. (The
    surviving ``attempted_outcome="result_returned"`` label is an adapter-owned
    receipt-gap telemetry string, not a lifecycle-outcome decision, and is frozen
    by A1.)
    """

    source = inspect.getsource(fastmcp_binding.DAGRMiddleware.on_call_tool)
    assert 'if projection["isError"] else "result_returned"' not in source
    assert 'outcome = "error_returned"' not in source
    assert 'outcome="task_submitted"' not in source
    # The neutral classification is what drives the outcome now.
    assert 'ExecutionObservation("task_submitted")' in source
    assert 'ExecutionObservation(' in source


# --------------------------------------------------------------------------- #
# 3. The frozen cancellation/exception literals equal the core projection      #
# --------------------------------------------------------------------------- #


def test_frozen_cancellation_literals_equal_the_core_projection():
    """The A1-frozen inline ``indeterminate`` emit equals the core's plan.

    ``on_call_tool`` keeps the cancellation projection literals inline because
    A1 freezes them by source inspection. This test proves those literals are
    exactly what the core plans and the A2 mask projects, so the two can never
    drift apart despite being spelled in two places.
    """

    admitted = plan_admission(AdmissionRequest("admitted", tool_class="write"))
    record = plan_outcome_strict(admitted, ExecutionObservation("cancellation")).record
    assert record is not None

    # Family projects to the binding's cancellation token.
    assert binding_mask.project_outcome(record.outcome).binding_token == "indeterminate"
    # No result digest on a cancellation.
    assert record.carries_result_digest is False
    # The three governance Booleans, projected through the mask, are exactly the
    # frozen inline dict in on_call_tool.
    projected = {
        binding_mask.project_cancellation_fact(fact): record.governance_facts_value
        for fact in record.governance_facts
    }
    assert projected == {
        "request_cancelled": True,
        "execution_state_unknown": True,
        "delivery_incomplete": True,
    }

    # And those exact literals are still present in the frozen source.
    source = inspect.getsource(fastmcp_binding.DAGRMiddleware.on_call_tool)
    assert 'outcome="indeterminate"' in source
    for literal in (
        '"request_cancelled": True',
        '"execution_state_unknown": True',
        '"delivery_incomplete": True',
    ):
        assert literal in source


def test_frozen_exception_literal_equals_the_core_projection():
    """The A1-frozen inline ``exception`` emit equals the core's plan."""

    admitted = plan_admission(AdmissionRequest("admitted", tool_class="write"))
    record = plan_outcome_strict(
        admitted, ExecutionObservation("exception", exception_class="ValueError")
    ).record
    assert record is not None
    assert binding_mask.project_outcome(record.outcome).binding_token == "exception"
    assert record.carries_result_digest is False

    source = inspect.getsource(fastmcp_binding.DAGRMiddleware.on_call_tool)
    assert 'outcome="exception"' in source
    assert "exception_class=type(exc).__name__" in source


# --------------------------------------------------------------------------- #
# 4. Differential: the former decision tree agrees with the core plan          #
# --------------------------------------------------------------------------- #


def _former_admission_decision(
    *, binding_disposition, tool_class, reason_code, review_object_created, emit_read
):
    """Reproduce the pre-A4 production admission decision (test-only oracle).

    This mirrors the exact branches DAGRMiddleware.on_call_tool used before the
    rebinding. It exists ONLY to be compared against the core plan below; it is
    not wired into any production path.
    """

    if binding_disposition == "refused":
        return {
            "proceeds": False,
            "records_admission": True,
            "binding_disposition": "refused",
            "reason_code": reason_code or "policy_refused",
        }
    if binding_disposition == "deferred_for_review":
        if not review_object_created:
            return {
                "proceeds": False,
                "records_admission": True,
                "binding_disposition": "refused",
                "reason_code": "review_object_creation_failed",
            }
        return {
            "proceeds": False,
            "records_admission": True,
            "binding_disposition": "deferred_for_review",
            "reason_code": None,
        }
    # admitted
    recorded = tool_class in ("write", "destructive") or emit_read
    return {
        "proceeds": True,
        "records_admission": recorded,
        "binding_disposition": "admitted" if recorded else None,
        "reason_code": None,
    }


_MATRIX = [
    ("admitted", "read", None, None, True),
    ("admitted", "read", None, None, False),
    ("admitted", "write", None, None, True),
    ("admitted", "write", None, None, False),
    ("admitted", "destructive", None, None, True),
    ("refused", "read", "policy_refused", None, True),
    ("refused", "read", "unknown_tool_fail_closed", None, True),
    ("refused", "write", "required_sink_unavailable", None, True),
    ("refused", "read", None, None, True),  # None reason -> policy_refused default
    ("deferred_for_review", "write", None, True, True),
    ("deferred_for_review", "write", None, False, True),
]


@pytest.mark.parametrize(
    "binding_disposition,tool_class,reason_code,review_created,emit_read", _MATRIX
)
def test_former_admission_decision_agrees_with_core_plan(
    binding_disposition, tool_class, reason_code, review_created, emit_read
):
    """The core plan reproduces the former production decision, exactly."""

    neutral = fastmcp_binding._to_neutral_disposition(binding_disposition)
    request = AdmissionRequest(
        disposition=neutral,
        tool_class=tool_class,
        refusal_ground=reason_code if neutral == "refused" else None,
        review_object_created=review_created,
        emit_read_admission_before_execution=emit_read,
    )
    # The adapter fills the refused default exactly as the former tree did.
    if neutral == "refused":
        request = AdmissionRequest(
            disposition=neutral,
            tool_class=tool_class,
            refusal_ground=(reason_code or "policy_refused"),
            emit_read_admission_before_execution=emit_read,
        )

    plan = plan_admission(request)
    oracle = _former_admission_decision(
        binding_disposition=binding_disposition,
        tool_class=tool_class,
        reason_code=reason_code,
        review_object_created=review_created,
        emit_read=emit_read,
    )

    assert plan.execution_proceeds == oracle["proceeds"]
    assert (plan.record is not None) == oracle["records_admission"]
    if plan.record is not None:
        assert (
            binding_mask.project_disposition(plan.record.disposition)
            == oracle["binding_disposition"]
        )
        assert plan.record.reason_code == oracle["reason_code"]


def test_result_error_task_families_project_to_the_former_tokens():
    """The former outcome tokens equal the core family projected through the mask."""

    admitted = plan_admission(AdmissionRequest("admitted", tool_class="write"))
    cases = {
        ("result", False): "result_returned",
        ("error", False): "error_returned",
        ("task_submitted", False): "task_submitted",
    }
    for (neutral, is_error), former_token in cases.items():
        record = plan_outcome_strict(
            admitted, ExecutionObservation(neutral)
        ).record
        assert record is not None
        assert binding_mask.project_outcome(record.outcome).binding_token == former_token
        # Only result/error carry a result digest; task does not.
        assert record.carries_result_digest is (neutral in ("result", "error"))


# --------------------------------------------------------------------------- #
# 5. Timeout posture and the unsupported input_required state                  #
# --------------------------------------------------------------------------- #


async def test_raised_timeout_is_recorded_as_exception_class_timeouterror(
    tmp_path: Path,
):
    """A raised TimeoutError is an ordinary inner exception (frozen §14)."""

    middleware, identity, directory = build_binding(
        tmp_path, tool_classes={"t.read": "read"}
    )
    with pytest.raises(TimeoutError):
        await call_direct(middleware, "t.read", TimeoutError("slow"))

    admission, outcome = split_pair(read_receipts(directory))
    assert outcome["outcome"] == "exception"
    assert outcome["extensions"]["mcp"]["exception_class"] == "TimeoutError"
    assert "result_digest" not in outcome


def test_core_timeout_subsumption_projects_to_the_same_exception_token():
    """The core's timeout→exception subsumption matches the production exception.

    The production adapter never mints a neutral ``timeout`` token — a raised
    TimeoutError is classified as a generic ``exception`` (matching the frozen
    binding, whose mask marks ``timeout`` as *subsumed*). The core's subsumption
    path is proved here to land on the same binding token and exception class, so
    the two descriptions of the same fact agree.
    """

    admitted = plan_admission(AdmissionRequest("admitted", tool_class="write"))
    timeout_record = plan_outcome_strict(
        admitted, ExecutionObservation("timeout")
    ).record
    assert timeout_record is not None
    assert timeout_record.subsumed_from == "timeout"
    assert binding_mask.project_outcome(timeout_record.outcome).binding_token == "exception"
    assert timeout_record.exception_class == "TimeoutError"
    assert timeout_record.carries_result_digest is False


def test_input_required_remains_explicitly_unsupported():
    """The core refuses to plan an ``input_required`` outcome; it is not coerced."""

    admitted = plan_admission(AdmissionRequest("admitted", tool_class="write"))
    for mode in contract.INPUT_REQUIRED_MODES:
        with pytest.raises(UnsupportedLifecycleEvent):
            plan_outcome_strict(
                admitted,
                ExecutionObservation("input_required", input_required_mode=mode),
            )
    assert binding_mask.project_outcome("input_required").status == "unsupported"


# --------------------------------------------------------------------------- #
# 6. The rebinding did not drag a binding into the neutral core                #
# --------------------------------------------------------------------------- #


def test_core_still_imports_no_fastmcp_or_binding_package():
    """Importing the core in a clean process pulls in no binding root (A4 guard)."""

    code = (
        "import importlib, sys\n"
        "importlib.import_module('dagr_mcp_lifecycle.core')\n"
        "importlib.import_module('dagr_mcp_lifecycle.models')\n"
        "roots = {k.split('.', 1)[0] for k in sys.modules}\n"
        "for forbidden in ('dagr_mcp', 'fastmcp', 'mcp'):\n"
        "    assert forbidden not in roots, forbidden\n"
        "print('clean')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "clean"


# --------------------------------------------------------------------------- #
# 7. The cancellation / exception paths INVOKE the core on the live path       #
# --------------------------------------------------------------------------- #
# The differential tests above prove the frozen inline literals *equal* the core
# projection. These tests go further: they prove the production cancellation and
# raised-exception paths actually *call* plan_outcome_strict with the right
# neutral observation, so the core — not an independent inline decision — is the
# runtime authority for those outcome families too.


def _outcome_observation_spy(monkeypatch):
    """Record every ExecutionObservation the live path hands plan_outcome_strict."""

    seen: list[ExecutionObservation] = []
    real = fastmcp_binding.plan_outcome_strict

    def spy(plan, observation):
        seen.append(observation)
        return real(plan, observation)

    monkeypatch.setattr(fastmcp_binding, "plan_outcome_strict", spy)
    return seen


async def test_cancellation_actually_invokes_plan_outcome_strict(
    monkeypatch, tmp_path: Path
):
    """asyncio.CancelledError routes through plan_outcome_strict('cancellation')."""

    seen = _outcome_observation_spy(monkeypatch)
    middleware, _identity, directory = build_binding(
        tmp_path, tool_classes={"t.write": "write"}
    )

    with pytest.raises(asyncio.CancelledError):
        await call_direct(middleware, "t.write", asyncio.CancelledError())

    assert [o.observation for o in seen] == ["cancellation"]
    _admission, outcome = split_pair(read_receipts(directory))
    assert outcome["outcome"] == "indeterminate"


async def test_ordinary_exception_actually_invokes_plan_outcome_strict(
    monkeypatch, tmp_path: Path
):
    """A raised ValueError routes through plan_outcome_strict('exception')."""

    seen = _outcome_observation_spy(monkeypatch)
    middleware, _identity, directory = build_binding(
        tmp_path, tool_classes={"t.write": "write"}
    )

    with pytest.raises(ValueError):
        await call_direct(middleware, "t.write", ValueError("boom"))

    assert len(seen) == 1
    assert seen[0].observation == "exception"
    assert seen[0].exception_class == "ValueError"
    _admission, outcome = split_pair(read_receipts(directory))
    assert outcome["outcome"] == "exception"
    assert outcome["extensions"]["mcp"]["exception_class"] == "ValueError"
    assert "result_digest" not in outcome


async def test_raised_timeout_actually_invokes_the_core_timeout_exception_path(
    monkeypatch, tmp_path: Path
):
    """A raised TimeoutError routes through the core's timeout→exception path.

    The adapter *identifies* the TimeoutError and hands the core a neutral
    ``timeout`` observation; the core subsumes it onto the exception family with
    ``exception_class='TimeoutError'``. The observable stays exactly the frozen §14
    shape (outcome ``exception``, class ``TimeoutError``, no ``result_digest``).
    """

    seen = _outcome_observation_spy(monkeypatch)
    middleware, _identity, directory = build_binding(
        tmp_path, tool_classes={"t.write": "write"}
    )

    with pytest.raises(TimeoutError):
        await call_direct(middleware, "t.write", TimeoutError("slow"))

    assert len(seen) == 1
    assert seen[0].observation == "timeout"  # the core timeout path, not "exception"
    _admission, outcome = split_pair(read_receipts(directory))
    assert outcome["outcome"] == "exception"
    assert outcome["extensions"]["mcp"]["exception_class"] == "TimeoutError"
    assert "result_digest" not in outcome


async def test_cancellation_governance_facts_are_obtained_from_the_core_record(
    tmp_path: Path,
):
    """The emitted cancellation Booleans equal the core record projected via the mask."""

    middleware, _identity, directory = build_binding(
        tmp_path, tool_classes={"t.write": "write"}
    )
    with pytest.raises(asyncio.CancelledError):
        await call_direct(middleware, "t.write", asyncio.CancelledError())

    _admission, outcome = split_pair(read_receipts(directory))

    # Independently derive what the core record projects and compare field-by-field.
    admitted = plan_admission(AdmissionRequest("admitted", tool_class="write"))
    record = plan_outcome_strict(admitted, ExecutionObservation("cancellation")).record
    assert record is not None
    expected = {
        binding_mask.project_cancellation_fact(fact): record.governance_facts_value
        for fact in record.governance_facts
    }
    assert expected == {
        "request_cancelled": True,
        "execution_state_unknown": True,
        "delivery_incomplete": True,
    }
    for field, value in expected.items():
        assert outcome[field] is value
    assert outcome["outcome"] == "indeterminate"


# --------------------------------------------------------------------------- #
# 8. Fail-closed projection: a divergent core plan never emits a receipt        #
# --------------------------------------------------------------------------- #


def _divergent_result_plan(_plan, _observation) -> OutcomePlan:
    """A core plan whose family projects to ``result_returned`` — deliberately wrong."""

    return OutcomePlan(
        observation="result",
        record=OutcomeRecordIntent(
            outcome="result",
            subsumed_from=None,
            exception_class=None,
            carries_result_digest=True,
            references_admission=True,
            governance_facts=(),
            governance_facts_value=True,
            attestation_limit_families=("base", "result", "boundary"),
            adapter_responsibilities=(),
        ),
    )


def _divergent_cancellation_missing_facts(_plan, _observation) -> OutcomePlan:
    """A cancellation plan that projects to ``indeterminate`` but drops its facts."""

    return OutcomePlan(
        observation="cancellation",
        record=OutcomeRecordIntent(
            outcome="cancellation",
            subsumed_from=None,
            exception_class=None,
            carries_result_digest=False,
            references_admission=True,
            governance_facts=(),  # the three governance Booleans are missing
            governance_facts_value=True,
            attestation_limit_families=("base", "boundary"),
            adapter_responsibilities=(),
        ),
    )


async def test_divergent_core_outcome_family_fails_closed_before_any_receipt(
    monkeypatch, tmp_path: Path
):
    """A core outcome that projects off the frozen exception literal fails closed."""

    monkeypatch.setattr(fastmcp_binding, "plan_outcome_strict", _divergent_result_plan)
    middleware, _identity, directory = build_binding(
        tmp_path, tool_classes={"t.write": "write"}
    )

    with pytest.raises(ToolError, match="diverged from the frozen binding literal"):
        await call_direct(middleware, "t.write", ValueError("boom"))

    # Only the admission receipt exists — no contradictory outcome receipt.
    receipts = read_receipts(directory)
    assert [r["receipt_kind"] for r in receipts] == ["admission"]


async def test_divergent_core_governance_facts_fail_closed_before_any_receipt(
    monkeypatch, tmp_path: Path
):
    """A cancellation core record missing its governance facts fails closed."""

    monkeypatch.setattr(
        fastmcp_binding, "plan_outcome_strict", _divergent_cancellation_missing_facts
    )
    middleware, _identity, directory = build_binding(
        tmp_path, tool_classes={"t.write": "write"}
    )

    with pytest.raises(ToolError, match="governance facts diverged"):
        await call_direct(middleware, "t.write", asyncio.CancelledError())

    receipts = read_receipts(directory)
    assert [r["receipt_kind"] for r in receipts] == ["admission"]


# --------------------------------------------------------------------------- #
# 9. input_required can never enter the exception / cancellation fallback       #
# --------------------------------------------------------------------------- #


async def test_input_required_cannot_enter_the_outcome_fallback(tmp_path: Path):
    """Handed to the live fallback helper, an input_required event fails closed.

    The production cancellation/exception branches only ever construct
    ``cancellation`` / ``timeout`` / ``exception`` observations, so an
    ``input_required`` never arises there. This proves the safety property from the
    other side: even if the fallback helper is invoked with the unsupported event,
    ``plan_outcome_strict`` raises ``UnsupportedLifecycleEvent`` *before* any emit,
    so it cannot be coerced into a supported cancellation/exception outcome.
    """

    middleware, _identity, directory = build_binding(
        tmp_path, tool_classes={"t.write": "write"}
    )

    # Capture a real admission plan / context / receipt ref from an admitted call.
    captured: dict[str, object] = {}
    real_emit_planned = middleware._emit_planned_outcome

    def capture(admission_plan, receipt_context, snapshot, admission_receipt_ref, *a, **k):
        captured.update(
            plan=admission_plan,
            ctx=receipt_context,
            snap=snapshot,
            ref=admission_receipt_ref,
        )
        return real_emit_planned(
            admission_plan, receipt_context, snapshot, admission_receipt_ref, *a, **k
        )

    middleware._emit_planned_outcome = capture  # type: ignore[assignment]
    await call_direct(middleware, "t.write", ToolResult(content="ok"))
    before = len(read_receipts(directory))

    for mode in contract.INPUT_REQUIRED_MODES:
        with pytest.raises(UnsupportedLifecycleEvent):
            middleware._project_core_outcome(
                captured["plan"],
                ExecutionObservation("input_required", input_required_mode=mode),
                captured["ctx"],
                captured["snap"],
                captured["ref"],
                frozen_outcome="exception",
                exception_class="ValueError",
            )

    # The refused fallback emitted nothing.
    assert len(read_receipts(directory)) == before


# --------------------------------------------------------------------------- #
# 10. Opaque binding reason codes are preserved (core owns only the decision)   #
# --------------------------------------------------------------------------- #


def test_opaque_reason_code_maps_to_a_closed_ground_but_emits_verbatim():
    """§7: the core sees a closed neutral ground; the adapter keeps the opaque code."""

    opaque = fastmcp_binding.BindingPolicy(
        disposition="refused", reason_code="tenant_quota_exceeded"
    )
    # The core is handed a valid closed ground (it owns the refusal *decision*)…
    assert (
        fastmcp_binding.DAGRMiddleware._neutral_refusal_ground(opaque)
        == "policy_refused"
    )
    assert (
        fastmcp_binding.DAGRMiddleware._neutral_refusal_ground(opaque)
        in contract.NEUTRAL_REFUSAL_GROUNDS
    )
    # …while the adapter preserves the opaque code for the emitted receipt.
    assert (
        fastmcp_binding.DAGRMiddleware._binding_refusal_reason_code(opaque)
        == "tenant_quota_exceeded"
    )

    # A known ground is passed through unchanged on both sides.
    known = fastmcp_binding.BindingPolicy(
        disposition="refused", reason_code="required_sink_unavailable"
    )
    assert (
        fastmcp_binding.DAGRMiddleware._neutral_refusal_ground(known)
        == "required_sink_unavailable"
    )
    assert (
        fastmcp_binding.DAGRMiddleware._binding_refusal_reason_code(known)
        == "required_sink_unavailable"
    )

    # A missing code defaults to policy_refused on both sides.
    default = fastmcp_binding.BindingPolicy(disposition="refused")
    assert (
        fastmcp_binding.DAGRMiddleware._neutral_refusal_ground(default)
        == "policy_refused"
    )
    assert (
        fastmcp_binding.DAGRMiddleware._binding_refusal_reason_code(default)
        == "policy_refused"
    )


async def test_opaque_binding_reason_code_survives_to_the_receipt(
    monkeypatch, tmp_path: Path
):
    """A refusal with an out-of-vocabulary reason code emits it verbatim, no crash.

    The core is fed a closed neutral ground, so it still decides the refusal
    (``execution_proceeds is False``); the adapter stamps the opaque binding code
    on the emitted receipt rather than crashing on the core's closed vocabulary.
    """

    handler_ran = False

    def resolver(_snapshot, _actor):
        return fastmcp_binding.BindingPolicy(
            disposition="refused",
            tool_class="destructive",
            reason_code="tenant_quota_exceeded",
        )

    seen_plans: list[object] = []
    real_admission = fastmcp_binding.plan_admission

    def spy_admission(request):
        plan = real_admission(request)
        seen_plans.append(plan)
        return plan

    monkeypatch.setattr(fastmcp_binding, "plan_admission", spy_admission)
    middleware, _identity, directory = build_binding(tmp_path, policy_resolver=resolver)

    with pytest.raises(ToolError, match="Call refused by admission policy"):
        await call_direct(middleware, "danger", ToolResult(content="never"))

    # The core still decided the refusal (execution does not proceed)…
    assert seen_plans and seen_plans[0].execution_proceeds is False
    assert seen_plans[0].resolved_disposition == "refused"
    # …and the opaque binding code reached the receipt verbatim.
    receipts = read_receipts(directory)
    assert len(receipts) == 1
    assert receipts[0]["disposition"] == "refused"
    assert receipts[0]["reason_code"] == "tenant_quota_exceeded"
    assert handler_ran is False
