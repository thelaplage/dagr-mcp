"""Sprint A3 — the binding-neutral lifecycle core, verified against the oracle.

These tests prove the extracted core in :mod:`dagr_mcp_lifecycle.core` /
:mod:`dagr_mcp_lifecycle.models` faithfully represents the semantic decisions
frozen in Sprint A1 (``docs/BEHAVIORAL_FREEZE.md``) and named in Sprint A2
(:mod:`dagr_mcp_lifecycle.contract` / :mod:`dagr_mcp_lifecycle.binding_mask`),
without touching the live FastMCP execution path.

The verification has five strands:

1. **Isolation** — the core imports no binding package and calls no side-effect
   module (proved in fresh subprocess interpreters and by source scan).
2. **Determinism** — identical inputs yield equal plans.
3. **Mask agreement** — the core plan projects onto the A2 FastMCP mask exactly.
4. **Shadow adapter over A1 fixtures** — every committed A1 characterization
   (the 3 admission + 5 outcome signed goldens) is driven through a neutral
   shadow adapter, and the core plan's neutral facts match the fixture bytes.
5. **Token totality + honesty** — every neutral contract token is implemented
   or explicitly unsupported; nothing is silently repaired or minted.

The binding remains the oracle; nothing here emits a receipt or rewires it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, get_args

import pytest

from dagr_mcp import fastmcp_binding, srs_receipts
from dagr_mcp_lifecycle import binding_mask, contract, core, models
from dagr_mcp_lifecycle.models import (
    AdmissionRequest,
    ExecutionObservation,
    LifecyclePlan,
    UnsupportedLifecycleEvent,
    UnsupportedLifecycleResult,
)

ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "tests/golden/behavioral_freeze"


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FREEZE / name).read_text(encoding="utf-8"))


def _run_probe(script: str) -> subprocess.CompletedProcess[str]:
    """Run an import/side-effect probe in a fresh interpreter.

    A subprocess is required: the pytest process has already imported the binding
    and many stdlib side-effect modules, so isolation can only be observed with a
    clean ``sys.modules``.
    """

    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


# =========================================================================== #
# 1. Isolation: no binding import, no side-effect module                      #
# =========================================================================== #


def test_core_imports_no_binding_or_arcs_package():
    forbidden = ("dagr_mcp", "fastmcp", "mcp", "arcs_verify", "arcs_amnesiac", "garp_sdk")
    script = (
        "import sys, importlib\n"
        "importlib.import_module('dagr_mcp_lifecycle.core')\n"
        "importlib.import_module('dagr_mcp_lifecycle.models')\n"
        "roots = {k.split('.', 1)[0] for k in sys.modules}\n"
        f"forbidden = {forbidden!r}\n"
        "bad = sorted(r for r in forbidden if r in roots)\n"
        "print('BAD=' + ','.join(bad))\n"
        "sys.exit(1 if bad else 0)\n"
    )
    proc = _run_probe(script)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_core_imports_no_side_effect_module():
    # No network, filesystem, environment, clock, UUID, hashing, signing, or
    # randomness module is pulled in by importing the core.
    side_effect_roots = (
        "os",
        "io",
        "socket",
        "ssl",
        "subprocess",
        "pathlib",
        "tempfile",
        "shutil",
        "time",
        "datetime",
        "uuid",
        "hashlib",
        "hmac",
        "secrets",
        "random",
        "urllib",
        "http",
        "requests",
        "cryptography",
        "rfc8785",
    )
    script = (
        "import sys, importlib\n"
        "before = set(sys.modules)\n"
        "importlib.import_module('dagr_mcp_lifecycle.core')\n"
        "importlib.import_module('dagr_mcp_lifecycle.models')\n"
        "new = {k.split('.', 1)[0] for k in set(sys.modules) - before}\n"
        f"suspects = {side_effect_roots!r}\n"
        "bad = sorted(r for r in suspects if r in new)\n"
        "print('BAD=' + ','.join(bad))\n"
        "sys.exit(1 if bad else 0)\n"
    )
    proc = _run_probe(script)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_core_and_models_source_import_only_neutral_vocabulary():
    # Static proof: the only non-stdlib import in the core/models source is the
    # neutral dagr_mcp_lifecycle vocabulary — never dagr_mcp, fastmcp, mcp, arcs,
    # or a side-effect module.
    import ast

    forbidden_roots = {
        "dagr_mcp",
        "fastmcp",
        "mcp",
        "arcs_verify",
        "arcs_amnesiac",
        "garp_sdk",
        "os",
        "socket",
        "subprocess",
        "pathlib",
        "time",
        "datetime",
        "uuid",
        "hashlib",
        "hmac",
        "secrets",
        "random",
        "rfc8785",
        "cryptography",
        "urllib",
        "http",
    }
    allowed_prefix = "dagr_mcp_lifecycle"
    for module in (core, models):
        source = Path(module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    assert root not in forbidden_roots, (module.__name__, alias.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                root = mod.split(".", 1)[0]
                if root == "__future__":
                    continue
                # Only the neutral package or a standard-library module (dataclasses,
                # typing, ast). Never a forbidden root.
                assert root not in forbidden_roots, (module.__name__, mod)
                if root and not mod.startswith(allowed_prefix):
                    assert root in {"dataclasses", "typing"}, (module.__name__, mod)


def test_core_can_be_used_without_the_binding_present():
    # The whole planning surface runs in a cold interpreter that never imports
    # the binding. Proves the core is usable binding-free.
    script = (
        "import sys\n"
        "from dagr_mcp_lifecycle import core\n"
        "from dagr_mcp_lifecycle.models import AdmissionRequest, ExecutionObservation\n"
        "p = core.plan_lifecycle(AdmissionRequest('admitted', tool_class='write'),\n"
        "                        ExecutionObservation('result'))\n"
        "assert p.record_count == 2\n"
        "roots = {k.split('.', 1)[0] for k in sys.modules}\n"
        "assert 'dagr_mcp' not in roots and 'fastmcp' not in roots\n"
        "sys.exit(0)\n"
    )
    proc = _run_probe(script)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# =========================================================================== #
# 2. Determinism                                                              #
# =========================================================================== #

_ALL_REQUESTS = [
    AdmissionRequest("admitted", tool_class="read"),
    AdmissionRequest("admitted", tool_class="write"),
    AdmissionRequest("admitted", tool_class="destructive"),
    AdmissionRequest("admitted", tool_class="read", emit_read_admission_before_execution=False),
    AdmissionRequest("refused", refusal_ground="policy_refused"),
    AdmissionRequest("refused", refusal_ground="unknown_tool_fail_closed"),
    AdmissionRequest("refused", refusal_ground="required_sink_unavailable"),
    AdmissionRequest("deferred", review_object_created=True),
    AdmissionRequest("deferred", review_object_created=False),
    AdmissionRequest("admitted", tool_class="write", has_parent_boundary=True),
]
_ALL_OBSERVATIONS = [
    ExecutionObservation("result"),
    ExecutionObservation("error"),
    ExecutionObservation("exception", exception_class="ValueError"),
    ExecutionObservation("task_submitted"),
    ExecutionObservation("timeout"),
    ExecutionObservation("cancellation"),
    ExecutionObservation("input_required", input_required_mode="continuable"),
]


@pytest.mark.parametrize("request_", _ALL_REQUESTS)
@pytest.mark.parametrize("observation", _ALL_OBSERVATIONS)
def test_identical_inputs_yield_equal_plans(request_, observation):
    first = core.plan_lifecycle(request_, observation)
    second = core.plan_lifecycle(request_, observation)
    assert first == second
    # Frozen dataclasses compare by value; equal plans hash-compare too when
    # they are plans (UnsupportedLifecycleResult is also a frozen dataclass).
    assert type(first) is type(second)


def test_admission_and_outcome_planning_are_each_deterministic():
    for request_ in _ALL_REQUESTS:
        assert core.plan_admission(request_) == core.plan_admission(request_)
    admitted = core.plan_admission(AdmissionRequest("admitted", tool_class="write"))
    for observation in _ALL_OBSERVATIONS:
        assert core.plan_outcome(admitted, observation) == core.plan_outcome(
            admitted, observation
        )


# =========================================================================== #
# 3. Mask agreement — the core plan projects onto the A2 mask exactly          #
# =========================================================================== #


def test_every_neutral_disposition_projects_onto_the_mask():
    # admitted / refused / deferred each resolve to a disposition the mask maps
    # to the live binding disposition token.
    cases = {
        "admitted": AdmissionRequest("admitted", tool_class="write"),
        "refused": AdmissionRequest("refused", refusal_ground="policy_refused"),
        "deferred": AdmissionRequest("deferred", review_object_created=True),
    }
    for neutral, request_ in cases.items():
        plan = core.plan_admission(request_)
        assert plan.resolved_disposition == neutral
        assert plan.record is not None
        binding_token = binding_mask.project_disposition(plan.record.disposition)
        assert binding_token in get_args(fastmcp_binding.Disposition)


def test_core_outcome_status_matches_the_mask_classification():
    for outcome in contract.NEUTRAL_OUTCOMES:
        entry = binding_mask.project_outcome(outcome)
        assert core.core_outcome_status(outcome) == entry.status, outcome


def test_supported_outcome_record_families_match_the_mask_binding_token():
    admitted = core.plan_admission(AdmissionRequest("admitted", tool_class="write"))
    observations = {
        "result": ExecutionObservation("result"),
        "error": ExecutionObservation("error"),
        "exception": ExecutionObservation("exception", exception_class="ValueError"),
        "task_submitted": ExecutionObservation("task_submitted"),
        "timeout": ExecutionObservation("timeout"),
        "cancellation": ExecutionObservation("cancellation"),
    }
    for neutral, observation in observations.items():
        plan = core.plan_outcome(admitted, observation)
        assert isinstance(plan, models.OutcomePlan)
        assert plan.record is not None
        # The record family projects to the same binding token the mask names for
        # the ORIGINAL neutral observation (timeout is subsumed onto exception).
        mask_token = binding_mask.project_outcome(neutral).binding_token
        record_token = binding_mask.project_outcome(plan.record.outcome).binding_token
        assert record_token == mask_token, (neutral, record_token, mask_token)


def test_result_digest_responsibility_matches_the_contract_and_mask():
    admitted = core.plan_admission(AdmissionRequest("admitted", tool_class="write"))
    for outcome in ("result", "error", "exception", "task_submitted", "cancellation"):
        plan = core.plan_outcome(admitted, ExecutionObservation(
            outcome, exception_class="ValueError" if outcome == "exception" else None
        ))
        expected = outcome in contract.RESULT_DIGEST_OUTCOMES
        assert plan.record.carries_result_digest is expected, outcome
        if expected:
            assert "compute_result_digest" in plan.record.adapter_responsibilities
    # Timeout is subsumed onto exception and carries no result digest.
    tplan = core.plan_outcome(admitted, ExecutionObservation("timeout"))
    assert tplan.record.carries_result_digest is False
    assert "timeout" in contract.NO_RESULT_DIGEST_OUTCOMES


def test_attestation_limit_families_resolve_through_the_mask():
    # Every family the core attaches resolves to a concrete binding limit string.
    admitted = core.plan_admission(AdmissionRequest("admitted", tool_class="write"))
    families = set(admitted.record.attestation_limit_families)
    for observation in _ALL_OBSERVATIONS[:-1]:  # exclude the unsupported one
        plan = core.plan_outcome(admitted, observation)
        families |= set(plan.record.attestation_limit_families)
    for family in families:
        assert family in binding_mask.ATTESTATION_LIMIT_MASK
        assert isinstance(binding_mask.ATTESTATION_LIMIT_MASK[family], str)


# =========================================================================== #
# 4. Shadow adapter over the A1 characterization fixtures                      #
# =========================================================================== #
# The shadow adapter takes a core plan and the *minted* facts of a committed A1
# fixture (which the adapter, not the core, owns), projects the plan onto the
# binding via the A2 mask, and asserts the neutral facts equal the fixture's
# observable bytes. This drives every A1 characterization through the core
# without emitting a receipt or touching the live path.


def _admission_semantic_projection(plan_record) -> dict[str, Any]:
    """Project a core admission record intent onto the mask's binding facts."""

    projection: dict[str, Any] = {
        "receipt_kind": "admission",
        "disposition": binding_mask.project_disposition(plan_record.disposition),
        "carries_argument_digest": plan_record.carries_argument_digest,
    }
    if plan_record.reason_code is not None:
        projection["reason_code"] = plan_record.reason_code
    if plan_record.carries_review_object_ref:
        projection["has_review_object_ref"] = True
    if plan_record.retry_contract is not None:
        projection["retry_contract"] = plan_record.retry_contract
    return projection


def _outcome_semantic_projection(plan_record) -> dict[str, Any]:
    projection: dict[str, Any] = {
        "receipt_kind": "outcome",
        "outcome": binding_mask.project_outcome(plan_record.outcome).binding_token,
        "carries_result_digest": plan_record.carries_result_digest,
        "references_admission": plan_record.references_admission,
    }
    if plan_record.exception_class is not None:
        projection["exception_class"] = plan_record.exception_class
    if plan_record.governance_facts:
        projection["governance_facts"] = {
            binding_mask.project_cancellation_fact(f): plan_record.governance_facts_value
            for f in plan_record.governance_facts
        }
    return projection


def _limits_present(plan_record, fixture) -> bool:
    concrete = {
        binding_mask.ATTESTATION_LIMIT_MASK[f]
        for f in plan_record.attestation_limit_families
    }
    return concrete <= set(fixture["attestation_limits"])


def test_shadow_adapter_reproduces_the_three_admission_fixtures():
    cases = [
        (
            "urn_srs_receipt_admission_freeze-admitted.json",
            AdmissionRequest("admitted", tool_class="write"),
        ),
        (
            "urn_srs_receipt_admission_freeze-refused.json",
            AdmissionRequest("refused", refusal_ground="policy_refused"),
        ),
        (
            "urn_srs_receipt_admission_freeze-deferred.json",
            AdmissionRequest("deferred", review_object_created=True),
        ),
    ]
    for filename, request_ in cases:
        fixture = _fixture(filename)
        plan = core.plan_admission(request_)
        assert plan.record is not None
        projection = _admission_semantic_projection(plan.record)

        assert projection["receipt_kind"] == fixture["receipt_kind"]
        assert projection["disposition"] == fixture["disposition"]
        # Every admission fixture carries an argument digest.
        assert projection["carries_argument_digest"] is True
        assert fixture["argument_digest"].startswith(contract.DIGEST_PREFIX)
        # reason_code / retry_contract / review_object_ref agree field-by-field.
        assert projection.get("reason_code") == fixture.get("reason_code")
        assert projection.get("retry_contract") == fixture.get("retry_contract")
        assert projection.get("has_review_object_ref", False) == (
            "review_object_ref" in fixture
        )
        assert _limits_present(plan.record, fixture)


def test_shadow_adapter_reproduces_the_five_outcome_fixtures():
    admitted = core.plan_admission(AdmissionRequest("admitted", tool_class="write"))
    cases = [
        ("urn_srs_receipt_outcome_freeze-result-returned.json", ExecutionObservation("result")),
        ("urn_srs_receipt_outcome_freeze-error-returned.json", ExecutionObservation("error")),
        (
            "urn_srs_receipt_outcome_freeze-exception.json",
            # The committed exception golden is a TimeoutError; a timeout is
            # subsumed onto exception with exactly that class, so the timeout
            # observation reproduces it.
            ExecutionObservation("timeout"),
        ),
        ("urn_srs_receipt_outcome_freeze-task-submitted.json", ExecutionObservation("task_submitted")),
        ("urn_srs_receipt_outcome_freeze-indeterminate.json", ExecutionObservation("cancellation")),
    ]
    for filename, observation in cases:
        fixture = _fixture(filename)
        plan = core.plan_outcome(admitted, observation)
        assert isinstance(plan, models.OutcomePlan)
        assert plan.record is not None
        projection = _outcome_semantic_projection(plan.record)

        assert projection["receipt_kind"] == fixture["receipt_kind"]
        assert projection["outcome"] == fixture["outcome"]
        # Result digest presence matches the fixture exactly.
        assert projection["carries_result_digest"] == ("result_digest" in fixture)
        # Every outcome references the admission record.
        assert projection["references_admission"] is True
        assert binding_mask.OUTCOME_TO_ADMISSION_FIELD in fixture
        # Exception class (incl. the subsumed TimeoutError) matches.
        if "exception_class" in projection:
            assert (
                projection["exception_class"]
                == fixture["extensions"]["mcp"]["exception_class"]
            )
        else:
            assert "exception_class" not in fixture.get("extensions", {}).get("mcp", {})
        # Cancellation governance Booleans match the fixture bytes.
        if "governance_facts" in projection:
            for field_name, value in projection["governance_facts"].items():
                assert fixture[field_name] is value
        assert _limits_present(plan.record, fixture)


def test_shadow_adapter_reproduces_frozen_receipt_cardinality():
    # admitted → 2 (admission + outcome); refused → 1; deferred → 1.
    admitted = core.plan_lifecycle(
        AdmissionRequest("admitted", tool_class="write"), ExecutionObservation("result")
    )
    refused = core.plan_lifecycle(
        AdmissionRequest("refused", refusal_ground="policy_refused")
    )
    deferred = core.plan_lifecycle(
        AdmissionRequest("deferred", review_object_created=True)
    )
    assert admitted.record_count == contract.RECEIPT_CARDINALITY["admitted"] == 2
    assert refused.record_count == contract.RECEIPT_CARDINALITY["refused"] == 1
    assert deferred.record_count == contract.RECEIPT_CARDINALITY["deferred"] == 1


def test_timeout_subsumption_matches_the_frozen_exception_golden():
    # §14 of the freeze: a raised timeout is recorded as exception/TimeoutError.
    fixture = _fixture("urn_srs_receipt_outcome_freeze-exception.json")
    admitted = core.plan_admission(AdmissionRequest("admitted", tool_class="write"))
    plan = core.plan_outcome(admitted, ExecutionObservation("timeout"))
    assert plan.record.outcome == "exception"
    assert plan.record.subsumed_from == "timeout"
    assert plan.record.exception_class == "TimeoutError"
    assert fixture["extensions"]["mcp"]["exception_class"] == "TimeoutError"
    assert plan.record.carries_result_digest is False


# =========================================================================== #
# 5. Token totality + honesty (no repair, no minting)                          #
# =========================================================================== #


def test_every_neutral_outcome_is_implemented_or_explicitly_unsupported():
    for outcome in contract.NEUTRAL_OUTCOMES:
        status = core.core_outcome_status(outcome)
        assert status in ("direct", "subsumed", "unsupported"), outcome
    # The unsupported set is exactly input_required, matching the mask.
    unsupported = {
        o for o in contract.NEUTRAL_OUTCOMES if core.core_outcome_status(o) == "unsupported"
    }
    assert unsupported == {"input_required"}
    assert set(models.UNSUPPORTED_OUTCOMES) == unsupported


def test_every_neutral_disposition_is_planned():
    planned = set()
    for request_ in (
        AdmissionRequest("admitted", tool_class="write"),
        AdmissionRequest("refused", refusal_ground="policy_refused"),
        AdmissionRequest("deferred", review_object_created=True),
    ):
        planned.add(core.plan_admission(request_).resolved_disposition)
    assert planned == set(contract.NEUTRAL_DISPOSITIONS)


def test_input_required_returns_an_explicit_unsupported_result_not_an_outcome():
    admitted = core.plan_admission(AdmissionRequest("admitted", tool_class="write"))
    for mode in contract.INPUT_REQUIRED_MODES:
        result = core.plan_outcome(
            admitted, ExecutionObservation("input_required", input_required_mode=mode)
        )
        assert isinstance(result, UnsupportedLifecycleResult)
        assert result.supported is False
        assert result.event == "input_required"
        assert result.modes == (mode,)
    # With no mode, both modes are reported.
    result = core.plan_outcome(admitted, ExecutionObservation("input_required"))
    assert set(result.modes) == set(contract.INPUT_REQUIRED_MODES)


def test_input_required_strict_planners_raise():
    admitted = core.plan_admission(AdmissionRequest("admitted", tool_class="write"))
    with pytest.raises(UnsupportedLifecycleEvent):
        core.plan_outcome_strict(admitted, ExecutionObservation("input_required"))
    with pytest.raises(UnsupportedLifecycleEvent):
        core.plan_lifecycle_strict(
            AdmissionRequest("admitted", tool_class="write"),
            ExecutionObservation("input_required"),
        )


def test_required_sink_unavailable_is_never_silently_repaired():
    # A refusal on required_sink_unavailable stays refused/required_sink_unavailable.
    plan = core.plan_admission(
        AdmissionRequest("refused", refusal_ground="required_sink_unavailable")
    )
    assert plan.resolved_disposition == "refused"
    assert plan.record.reason_code == "required_sink_unavailable"
    assert plan.execution_proceeds is False


def test_deferral_review_failure_resolves_to_review_object_creation_failed_only():
    # §17 residual: a review object that fails to create resolves to
    # review_object_creation_failed, NEVER to required_sink_unavailable.
    plan = core.plan_admission(
        AdmissionRequest("deferred", review_object_created=False)
    )
    assert plan.requested_disposition == "deferred"
    assert plan.resolved_disposition == "refused"
    assert plan.record.reason_code == "review_object_creation_failed"
    assert plan.record.reason_code != "required_sink_unavailable"
    # And a genuine deferral (review created) never becomes a refusal.
    ok = core.plan_admission(AdmissionRequest("deferred", review_object_created=True))
    assert ok.resolved_disposition == "deferred"
    assert ok.record.reason_code is None


def test_refused_and_deferred_never_proceed_to_execution():
    for request_ in (
        AdmissionRequest("refused", refusal_ground="policy_refused"),
        AdmissionRequest("deferred", review_object_created=True),
        AdmissionRequest("deferred", review_object_created=False),
    ):
        plan = core.plan_admission(request_)
        assert plan.execution_proceeds is False
    # An outcome observation on a non-proceeding admission yields no outcome record.
    refused = core.plan_admission(AdmissionRequest("refused", refusal_ground="policy_refused"))
    outcome = core.plan_outcome(refused, ExecutionObservation("result"))
    assert outcome.record is None


def test_admitted_read_skip_produces_no_admission_or_outcome_record():
    request_ = AdmissionRequest(
        "admitted", tool_class="read", emit_read_admission_before_execution=False
    )
    plan = core.plan_lifecycle(request_, ExecutionObservation("result"))
    assert isinstance(plan, LifecyclePlan)
    assert plan.admission.admission_recorded is False
    assert plan.admission.record is None
    assert plan.admission.execution_proceeds is True
    assert plan.outcome.record is None
    assert plan.record_count == 0


# --- No minting ------------------------------------------------------------ #

_FORBIDDEN_MINTED_SUBSTRINGS = (
    "sha256:",  # a digest value
    "urn:srs:receipt:",  # a minted receipt id
    "issuer:",  # an issuer id
    "2026-",  # an ISO wall-clock stamp
    "Ed25519",  # a signature algorithm/value
    "fastmcp.middleware",  # a binding identifier
)


def _iter_record_intents():
    for request_ in _ALL_REQUESTS:
        admission = core.plan_admission(request_)
        if admission.record is not None:
            yield admission.record
        if admission.execution_proceeds and admission.admission_recorded:
            for observation in _ALL_OBSERVATIONS:
                plan = core.plan_outcome(admission, observation)
                if isinstance(plan, models.OutcomePlan) and plan.record is not None:
                    yield plan.record


def test_no_record_intent_carries_a_minted_value():
    # The core mints no id, timestamp, signature, digest value, protocol version,
    # or binding identifier. Every record-intent field value is a neutral token,
    # a Boolean, or an adapter-responsibility token — never a minted string.
    for record in _iter_record_intents():
        assert is_dataclass(record)
        for f in fields(record):
            value = getattr(record, f.name)
            strings: list[str] = []
            if isinstance(value, str):
                strings = [value]
            elif isinstance(value, tuple):
                strings = [v for v in value if isinstance(v, str)]
            for s in strings:
                for needle in _FORBIDDEN_MINTED_SUBSTRINGS:
                    assert needle not in s, (record, f.name, s)


def test_minting_and_stamping_are_declared_adapter_responsibilities():
    # Every record explicitly hands id/clock/signature/protocol/binding stamping,
    # canonicalization, and transport to the adapter.
    required = {
        "mint_receipt_id",
        "mint_issued_at",
        "canonicalize_record",
        "sign_record",
        "stamp_protocol_binding",
        "stamp_binding_version",
        "transport_record",
    }
    for record in _iter_record_intents():
        assert required <= set(record.adapter_responsibilities), record
        # Every declared responsibility is a known token.
        for token in record.adapter_responsibilities:
            assert token in models.ADAPTER_RESPONSIBILITIES, token


def test_core_never_names_the_protocol_or_binding_stamp_values():
    # The core owns no protocol-binding token ("mcp") or binding version; those
    # are the mask's / adapter's. Prove neither appears as a value the core emits.
    for record in _iter_record_intents():
        for f in fields(record):
            value = getattr(record, f.name)
            if isinstance(value, str):
                assert value != binding_mask.OBSERVED_PROTOCOL_BINDING
                assert value != fastmcp_binding.BINDING_VERSION


# --- Core / contract identity ---------------------------------------------- #


def test_core_version_identifiers_are_pinned():
    assert models.CORE_ID == "dagr.mcp.lifecycle_core"
    assert models.CORE_VERSION == "v0.1"


def test_core_governance_registry_matches_the_binding_registry():
    # The core's cancellation facts are the frozen registry, and their neutral
    # names map onto the binding's owned governance fields via the mask.
    admitted = core.plan_admission(AdmissionRequest("admitted", tool_class="write"))
    plan = core.plan_outcome(admitted, ExecutionObservation("cancellation"))
    assert set(plan.record.governance_facts) == set(contract.NEUTRAL_CANCELLATION_FACTS)
    mapped = {binding_mask.project_cancellation_fact(f) for f in plan.record.governance_facts}
    assert mapped == set(srs_receipts.CANCELLATION_FIELD_NAMES)
