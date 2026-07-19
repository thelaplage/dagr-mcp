"""Sprint A7 — Gateway request/response contract (dagr_mcp_service.contract).

Covers the two-stage caller-authority boundary (§3.3), the response-class
invariants (§4/§10), and the import-purity/no-execution guarantees the A7
acceptance criteria (scope §15) require.
"""

from __future__ import annotations

import dataclasses
import subprocess
import sys
from pathlib import Path

import pytest

from dagr_mcp_service.contract import (
    ALL_DIAGNOSTIC_CODES,
    BOUNDARY_TYPE,
    PROHIBITED_CALLER_AUTHORITY_KEYS,
    BusinessResult,
    CallerGovernedCallRequest,
    CancellationFacts,
    GovernedCallRequest,
    GovernedCallResponse,
    GovernedDecision,
    ReceiptHandle,
    TargetServerRef,
    TrustedActorRef,
    TrustedTenantRef,
)
from dagr_mcp_service.resolution import BindingSelectorKey

ROOT = Path(__file__).resolve().parents[1]

MINIMAL_CALLER_PAYLOAD = {
    "request_ref": "req-1",
    "binding_selector": "primary",
    "target_server_ref": "bossy-mcp-staging",
    "tool_name": "list_widgets",
    "argument_digest": "sha256:" + "0" * 64,
    "policy_profile_ref": "default",
}


def _minimal_caller_request() -> CallerGovernedCallRequest:
    return CallerGovernedCallRequest(
        request_ref="req-1",
        binding_selector=BindingSelectorKey(key="primary"),
        target_server_ref=TargetServerRef(handle="bossy-mcp-staging"),
        tool_name="list_widgets",
        argument_digest="sha256:" + "0" * 64,
        policy_profile_ref="default",
    )


# --------------------------------------------------------------------------- #
# 1. Minimum external caller request validates                                #
# --------------------------------------------------------------------------- #


def test_minimum_external_caller_request_validates() -> None:
    caller_request = CallerGovernedCallRequest.from_untrusted_mapping(MINIMAL_CALLER_PAYLOAD)
    assert caller_request.request_ref == "req-1"
    assert caller_request.binding_selector == BindingSelectorKey(key="primary")
    assert caller_request.target_server_ref == TargetServerRef(handle="bossy-mcp-staging")
    assert caller_request.boundary_type == BOUNDARY_TYPE


def test_caller_request_accepts_optional_fields() -> None:
    payload = dict(
        MINIMAL_CALLER_PAYLOAD, session_ref="session-1", meta_digest="sha256:" + "1" * 64
    )
    caller_request = CallerGovernedCallRequest.from_untrusted_mapping(payload)
    assert caller_request.session_ref == "session-1"
    assert caller_request.meta_digest == "sha256:" + "1" * 64


def test_caller_request_rejects_missing_required_field() -> None:
    payload = dict(MINIMAL_CALLER_PAYLOAD)
    del payload["tool_name"]
    with pytest.raises(ValueError):
        CallerGovernedCallRequest.from_untrusted_mapping(payload)


# --------------------------------------------------------------------------- #
# 2. Service-resolved actor/tenant context remains structurally separate      #
# --------------------------------------------------------------------------- #


def test_caller_request_type_has_no_actor_or_tenant_field() -> None:
    field_names = {field.name for field in dataclasses.fields(CallerGovernedCallRequest)}
    assert "actor_ref" not in field_names
    assert "tenant_ref" not in field_names


def test_governed_call_request_requires_actor_ref_as_separate_keyword() -> None:
    caller_request = _minimal_caller_request()
    resolved = GovernedCallRequest.from_caller_request(
        caller_request, actor_ref=TrustedActorRef(ref="actor:sha256:" + "a" * 64)
    )
    assert resolved.actor_ref == TrustedActorRef(ref="actor:sha256:" + "a" * 64)
    assert resolved.request_ref == caller_request.request_ref
    assert resolved.tool_name == caller_request.tool_name


def test_governed_call_request_from_caller_request_ignores_any_caller_supplied_trust() -> None:
    # CallerGovernedCallRequest cannot carry actor_ref/tenant_ref at all (no
    # such fields exist), so from_caller_request's actor_ref/tenant_ref can
    # only come from its own keyword arguments -- proving the two stages are
    # structurally, not just conventionally, separate.
    caller_request = _minimal_caller_request()
    resolved = GovernedCallRequest.from_caller_request(
        caller_request,
        actor_ref=TrustedActorRef(ref="actor:sha256:" + "b" * 64),
        tenant_ref=TrustedTenantRef(ref="tenant:sha256:" + "c" * 64),
    )
    assert resolved.tenant_ref == TrustedTenantRef(ref="tenant:sha256:" + "c" * 64)


def test_governed_call_request_from_caller_request_rejects_non_caller_request_type() -> None:
    with pytest.raises(TypeError):
        GovernedCallRequest.from_caller_request(
            "not-a-caller-request", actor_ref=TrustedActorRef(ref="actor:sha256:" + "a" * 64)
        )


# --------------------------------------------------------------------------- #
# 3. External authority-smuggling fields are rejected                         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "key,value",
    [
        ("actor_ref", "actor:sha256:" + "a" * 64),
        ("tenant_ref", "tenant:sha256:" + "b" * 64),
        ("role", "admin"),
        ("policy_decision", "admit"),
        ("policy_outcome", "admitted"),
        ("disposition", "admitted"),
        ("credential", "Bearer some-token"),
        ("credentials", "Bearer some-token"),
        ("signing_identity", "issuer:key-1"),
        ("signer", "issuer:key-1"),
        ("binding_version", "fastmcp.middleware.v0.1"),
        ("receipt_id", "urn:srs:receipt:admission:deadbeef"),
        ("custody_status", "admitted"),
        ("custody_disposition", "admitted"),
    ],
)
def test_from_untrusted_mapping_rejects_prohibited_authority_field(key: str, value: object) -> None:
    payload = dict(MINIMAL_CALLER_PAYLOAD, **{key: value})
    with pytest.raises(ValueError):
        CallerGovernedCallRequest.from_untrusted_mapping(payload)


def test_prohibited_caller_authority_keys_are_all_rejected_not_merely_ignored() -> None:
    for key in PROHIBITED_CALLER_AUTHORITY_KEYS:
        payload = dict(MINIMAL_CALLER_PAYLOAD, **{key: "smuggled-value"})
        with pytest.raises(ValueError):
            CallerGovernedCallRequest.from_untrusted_mapping(payload)
    # And the rejection is a raise, not a silent drop: the valid subset of
    # keys alone (without the smuggled one) still validates.
    assert CallerGovernedCallRequest.from_untrusted_mapping(MINIMAL_CALLER_PAYLOAD) is not None


def test_from_untrusted_mapping_rejects_arbitrary_unrecognized_field() -> None:
    payload = dict(MINIMAL_CALLER_PAYLOAD, made_up_field="anything")
    with pytest.raises(ValueError):
        CallerGovernedCallRequest.from_untrusted_mapping(payload)


def test_from_untrusted_mapping_rejects_non_mapping_payload() -> None:
    with pytest.raises(TypeError):
        CallerGovernedCallRequest.from_untrusted_mapping(["not", "a", "mapping"])  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 10/11. Minimum valid response construction; admitted result/error separation #
# --------------------------------------------------------------------------- #


def test_minimum_valid_admitted_result_response() -> None:
    response = GovernedCallResponse(
        request_ref="req-1",
        logical_call_id="call:1",
        decision=GovernedDecision(disposition="admitted", outcome="result"),
        business_result=BusinessResult(result_kind="result", payload={"ok": True}),
        receipts=(
            ReceiptHandle(receipt_id="r-admission", receipt_kind="admission"),
            ReceiptHandle(receipt_id="r-outcome", receipt_kind="outcome"),
        ),
    )
    assert response.decision.outcome == "result"
    assert response.business_result.result_kind == "result"


def test_admitted_tool_level_error_response() -> None:
    response = GovernedCallResponse(
        request_ref="req-1",
        logical_call_id="call:1",
        decision=GovernedDecision(disposition="admitted", outcome="error"),
        business_result=BusinessResult(result_kind="error", payload={"message": "boom"}),
        receipts=(
            ReceiptHandle(receipt_id="r-admission", receipt_kind="admission"),
            ReceiptHandle(receipt_id="r-outcome", receipt_kind="outcome"),
        ),
        diagnostic_code="tool_error",
    )
    assert response.business_result.result_kind == "error"


def test_business_result_rejected_for_non_result_non_error_outcome() -> None:
    with pytest.raises(ValueError):
        GovernedCallResponse(
            request_ref="req-1",
            logical_call_id="call:1",
            decision=GovernedDecision(disposition="admitted", outcome="exception"),
            business_result=BusinessResult(result_kind="result", payload=None),
        )


def test_business_result_rejected_when_disposition_is_not_admitted() -> None:
    with pytest.raises(ValueError):
        GovernedCallResponse(
            request_ref="req-1",
            logical_call_id="call:1",
            decision=GovernedDecision(disposition="refused"),
            business_result=BusinessResult(result_kind="result", payload=None),
        )


# --------------------------------------------------------------------------- #
# 12. Refused response invariants                                             #
# --------------------------------------------------------------------------- #


def test_refused_response_invariants() -> None:
    response = GovernedCallResponse(
        request_ref="req-1",
        logical_call_id="call:1",
        decision=GovernedDecision(disposition="refused"),
        receipts=(ReceiptHandle(receipt_id="r-admission", receipt_kind="admission"),),
        diagnostic_code="policy_refused",
    )
    assert response.business_result is None
    assert response.decision.outcome is None


def test_refused_disposition_cannot_carry_an_outcome() -> None:
    with pytest.raises(ValueError):
        GovernedDecision(disposition="refused", outcome="result")


# --------------------------------------------------------------------------- #
# 13. Deferred / review / continuation invariants                             #
# --------------------------------------------------------------------------- #


def test_deferred_response_invariants() -> None:
    response = GovernedCallResponse(
        request_ref="req-1",
        logical_call_id="call:1",
        decision=GovernedDecision(disposition="deferred"),
        receipts=(ReceiptHandle(receipt_id="r-admission", receipt_kind="admission"),),
        review_object_ref="review:1",
        retry_instruction="retry_after_approval",
        diagnostic_code="deferred_for_review",
    )
    assert response.retry_instruction == "retry_after_approval"
    assert response.review_object_ref == "review:1"


def test_retry_after_approval_rejected_for_non_deferred_disposition() -> None:
    with pytest.raises(ValueError):
        GovernedCallResponse(
            request_ref="req-1",
            logical_call_id="call:1",
            decision=GovernedDecision(disposition="refused"),
            receipts=(ReceiptHandle(receipt_id="r-admission", receipt_kind="admission"),),
            retry_instruction="retry_after_approval",
        )


# --------------------------------------------------------------------------- #
# 14. Cancellation facts remain distinct                                      #
# --------------------------------------------------------------------------- #


def test_cancellation_facts_only_valid_with_cancellation_outcome() -> None:
    response = GovernedCallResponse(
        request_ref="req-1",
        logical_call_id="call:1",
        decision=GovernedDecision(disposition="admitted", outcome="cancellation"),
        receipts=(
            ReceiptHandle(receipt_id="r-admission", receipt_kind="admission"),
            ReceiptHandle(receipt_id="r-outcome", receipt_kind="outcome"),
        ),
        cancellation_facts=CancellationFacts(
            request_cancelled=True, execution_state_unknown=True, delivery_incomplete=True
        ),
        diagnostic_code="cancelled",
    )
    assert response.cancellation_facts.execution_state_unknown is True


def test_cancellation_facts_rejected_for_non_cancellation_outcome() -> None:
    with pytest.raises(ValueError):
        GovernedCallResponse(
            request_ref="req-1",
            logical_call_id="call:1",
            decision=GovernedDecision(disposition="admitted", outcome="result"),
            cancellation_facts=CancellationFacts(),
        )


# --------------------------------------------------------------------------- #
# 15. Unsupported lifecycle state remains non-coerced                         #
# --------------------------------------------------------------------------- #


def test_unsupported_lifecycle_state_response() -> None:
    response = GovernedCallResponse(
        request_ref="req-1",
        logical_call_id="call:1",
        decision=None,
        diagnostic_code="unsupported_lifecycle_state",
    )
    assert response.decision is None
    assert response.receipts == ()


def test_decision_none_requires_unsupported_lifecycle_diagnostic() -> None:
    with pytest.raises(ValueError):
        GovernedCallResponse(
            request_ref="req-1",
            logical_call_id="call:1",
            decision=None,
            diagnostic_code="policy_refused",
        )


def test_unsupported_lifecycle_state_cannot_carry_receipts() -> None:
    with pytest.raises(ValueError):
        GovernedCallResponse(
            request_ref="req-1",
            logical_call_id="call:1",
            decision=None,
            diagnostic_code="unsupported_lifecycle_state",
            receipts=(ReceiptHandle(receipt_id="r-1", receipt_kind="admission"),),
        )


# --------------------------------------------------------------------------- #
# 16. Receipt cardinality follows disposition/outcome                         #
# --------------------------------------------------------------------------- #


def test_admitted_response_accepts_up_to_two_receipts() -> None:
    response = GovernedCallResponse(
        request_ref="req-1",
        logical_call_id="call:1",
        decision=GovernedDecision(disposition="admitted", outcome="result"),
        business_result=BusinessResult(result_kind="result", payload=None),
        receipts=(
            ReceiptHandle(receipt_id="r-admission", receipt_kind="admission"),
            ReceiptHandle(receipt_id="r-outcome", receipt_kind="outcome"),
        ),
    )
    assert len(response.receipts) == 2


def test_admitted_read_skip_path_may_carry_zero_receipts() -> None:
    # An admitted read configured not to observe admission before execution
    # produces no governance record at all (dagr_mcp_lifecycle.models
    # AdmissionPlan/OutcomePlan's optional ``record``); the ceiling is a
    # maximum, not an exact count.
    response = GovernedCallResponse(
        request_ref="req-1",
        logical_call_id="call:1",
        decision=GovernedDecision(disposition="admitted", outcome="result"),
        business_result=BusinessResult(result_kind="result", payload=None),
        receipts=(),
    )
    assert response.receipts == ()


def test_refused_response_rejects_more_than_one_receipt() -> None:
    with pytest.raises(ValueError):
        GovernedCallResponse(
            request_ref="req-1",
            logical_call_id="call:1",
            decision=GovernedDecision(disposition="refused"),
            receipts=(
                ReceiptHandle(receipt_id="r-1", receipt_kind="admission"),
                ReceiptHandle(receipt_id="r-2", receipt_kind="outcome"),
            ),
        )


def test_deferred_response_rejects_more_than_one_receipt() -> None:
    with pytest.raises(ValueError):
        GovernedCallResponse(
            request_ref="req-1",
            logical_call_id="call:1",
            decision=GovernedDecision(disposition="deferred"),
            receipts=(
                ReceiptHandle(receipt_id="r-1", receipt_kind="admission"),
                ReceiptHandle(receipt_id="r-2", receipt_kind="outcome"),
            ),
        )


def test_admitted_response_rejects_more_than_two_receipts() -> None:
    with pytest.raises(ValueError):
        GovernedCallResponse(
            request_ref="req-1",
            logical_call_id="call:1",
            decision=GovernedDecision(disposition="admitted", outcome="result"),
            business_result=BusinessResult(result_kind="result", payload=None),
            receipts=(
                ReceiptHandle(receipt_id="r-1", receipt_kind="admission"),
                ReceiptHandle(receipt_id="r-2", receipt_kind="outcome"),
                ReceiptHandle(receipt_id="r-3", receipt_kind="outcome"),
            ),
        )


def test_required_sink_unavailable_refusal_permits_zero_receipts() -> None:
    response = GovernedCallResponse(
        request_ref="req-1",
        logical_call_id="call:1",
        decision=GovernedDecision(disposition="refused"),
        receipts=(),
        diagnostic_code="required_sink_unavailable",
    )
    assert response.receipts == ()


# --------------------------------------------------------------------------- #
# 17. Deterministic projection                                                #
# --------------------------------------------------------------------------- #


def test_caller_request_to_json_is_deterministic() -> None:
    caller_request = _minimal_caller_request()
    assert caller_request.to_json() == caller_request.to_json()
    reconstructed = CallerGovernedCallRequest(
        request_ref="req-1",
        binding_selector=BindingSelectorKey(key="primary"),
        target_server_ref=TargetServerRef(handle="bossy-mcp-staging"),
        tool_name="list_widgets",
        argument_digest="sha256:" + "0" * 64,
        policy_profile_ref="default",
    )
    assert caller_request.to_json() == reconstructed.to_json()


def test_governed_call_response_to_dict_and_to_json_round_trip_json_safe_payload() -> None:
    response = GovernedCallResponse(
        request_ref="req-1",
        logical_call_id="call:1",
        decision=GovernedDecision(disposition="admitted", outcome="result"),
        business_result=BusinessResult(result_kind="result", payload={"a": 1, "b": [1, 2, 3]}),
        receipts=(ReceiptHandle(receipt_id="r-1", receipt_kind="admission"),),
    )
    as_dict = response.to_dict()
    assert as_dict["request_ref"] == "req-1"
    assert as_dict["business_result"]["payload"] == {"a": 1, "b": [1, 2, 3]}
    assert response.to_json() == response.to_json()


# --------------------------------------------------------------------------- #
# 18. Invalid closed vocabulary values fail                                   #
# --------------------------------------------------------------------------- #


def test_disposition_outside_neutral_vocabulary_fails() -> None:
    with pytest.raises(ValueError):
        GovernedDecision(disposition="made-up-disposition")


def test_outcome_outside_neutral_vocabulary_fails() -> None:
    with pytest.raises(ValueError):
        GovernedDecision(disposition="admitted", outcome="made-up-outcome")


def test_diagnostic_code_outside_closed_vocabulary_fails() -> None:
    with pytest.raises(ValueError):
        GovernedCallResponse(
            request_ref="req-1",
            logical_call_id="call:1",
            decision=GovernedDecision(disposition="refused"),
            diagnostic_code="made-up-diagnostic",
        )


def test_receipt_kind_outside_closed_vocabulary_fails() -> None:
    with pytest.raises(ValueError):
        ReceiptHandle(receipt_id="r-1", receipt_kind="made-up-kind")  # type: ignore[arg-type]


def test_boundary_type_is_pinned_and_rejects_other_values() -> None:
    with pytest.raises(ValueError):
        CallerGovernedCallRequest.from_untrusted_mapping(
            dict(MINIMAL_CALLER_PAYLOAD, boundary_type="mcp_resource_read")
        )


def test_all_diagnostic_codes_are_accepted() -> None:
    for code in ALL_DIAGNOSTIC_CODES:
        decision = (
            None if code == "unsupported_lifecycle_state" else GovernedDecision(disposition="refused")
        )
        response = GovernedCallResponse(
            request_ref="req-1",
            logical_call_id="call:1",
            decision=decision,
            diagnostic_code=code,
        )
        assert response.diagnostic_code == code


# --------------------------------------------------------------------------- #
# 19/20. Import purity; no adapter execution or exactly-once surface          #
# --------------------------------------------------------------------------- #


def test_fresh_import_of_contract_does_not_pull_in_transport_or_storage_libraries() -> None:
    script = (
        "import sys\n"
        "from dagr_mcp_service import contract\n"
        "roots = {m.split('.', 1)[0] for m in sys.modules}\n"
        "forbidden = {\n"
        "    'mcp', 'fastmcp', 'asyncio', 'uvicorn', 'starlette', 'aiohttp',\n"
        "    'httpx', 'fastapi', 'flask', 'sqlalchemy', 'psycopg2', 'pika',\n"
        "    'kombu', 'celery',\n"
        "}\n"
        "hit = roots & forbidden\n"
        "assert not hit, hit\n"
        "assert contract.SERVICE_ID == 'dagr.mcp.gateway_service_contract'\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_fresh_import_of_service_package_does_not_pull_in_transport_or_storage_libraries() -> None:
    script = (
        "import sys\n"
        "import dagr_mcp_service\n"
        "roots = {m.split('.', 1)[0] for m in sys.modules}\n"
        "forbidden = {\n"
        "    'mcp', 'fastmcp', 'uvicorn', 'starlette', 'aiohttp', 'httpx',\n"
        "    'fastapi', 'flask', 'sqlalchemy', 'psycopg2', 'pika', 'kombu', 'celery',\n"
        "}\n"
        "hit = roots & forbidden\n"
        "assert not hit, hit\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_no_adapter_execution_or_access_module_exists_yet() -> None:
    # A7's prohibited scope (scope §15): no connector, no transport, no
    # receipt emission, no execute_governed_call orchestration. Proven by
    # these modules simply not existing in the package yet.
    import dagr_mcp_service

    for forbidden_submodule in ("adapter", "connectors", "access"):
        with pytest.raises(ModuleNotFoundError):
            __import__(f"dagr_mcp_service.{forbidden_submodule}")
    assert not hasattr(dagr_mcp_service, "execute_governed_call")


def test_no_idempotency_or_exactly_once_surface_on_the_contract_types() -> None:
    # §11 leaves idempotency/exactly-once explicitly open; this module must
    # not encode a dedup key or replay ledger field on either request type.
    caller_field_names = {f.name for f in dataclasses.fields(CallerGovernedCallRequest)}
    resolved_field_names = {f.name for f in dataclasses.fields(GovernedCallRequest)}
    for forbidden_name in ("idempotency_key", "dedup_key", "replay_of", "exactly_once"):
        assert forbidden_name not in caller_field_names
        assert forbidden_name not in resolved_field_names
