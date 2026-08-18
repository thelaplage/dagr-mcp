#!/usr/bin/env python3
"""Generate neutral GovernedCallResponse vectors from the producer contract.

These vectors freeze only dagr-mcp's generic gateway response surface. They
contain no Counterplayer, research, provider-search, or provider-open semantics.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from dagr_mcp_service.contract import (
    BusinessResult,
    CancellationFacts,
    GovernedCallResponse,
    GovernedDecision,
    ReceiptHandle,
)


def _receipt(receipt_id: str, receipt_kind: str) -> ReceiptHandle:
    return ReceiptHandle(receipt_id=receipt_id, receipt_kind=receipt_kind)


def build_vectors() -> dict[str, dict]:
    responses = {
        "admitted_result": GovernedCallResponse(
            request_ref="req-vector-result",
            logical_call_id="call:vector:result",
            decision=GovernedDecision(disposition="admitted", outcome="result"),
            business_result=BusinessResult(
                result_kind="result", payload={"ok": True, "items": [1, 2]}
            ),
            receipts=(
                _receipt("r-vector-result-admission", "admission"),
                _receipt("r-vector-result-outcome", "outcome"),
            ),
        ),
        "admitted_error": GovernedCallResponse(
            request_ref="req-vector-error",
            logical_call_id="call:vector:error",
            decision=GovernedDecision(disposition="admitted", outcome="error"),
            business_result=BusinessResult(
                result_kind="error", payload={"message": "boom"}
            ),
            receipts=(
                _receipt("r-vector-error-admission", "admission"),
                _receipt("r-vector-error-outcome", "outcome"),
            ),
            diagnostic_code="tool_error",
        ),
        "admitted_exception": GovernedCallResponse(
            request_ref="req-vector-exception",
            logical_call_id="call:vector:exception",
            decision=GovernedDecision(disposition="admitted", outcome="exception"),
            receipts=(
                _receipt("r-vector-exception-admission", "admission"),
                _receipt("r-vector-exception-outcome", "outcome"),
            ),
            diagnostic_code="remote_exception",
        ),
        "admitted_timeout": GovernedCallResponse(
            request_ref="req-vector-timeout",
            logical_call_id="call:vector:timeout",
            decision=GovernedDecision(disposition="admitted", outcome="timeout"),
            receipts=(
                _receipt("r-vector-timeout-admission", "admission"),
                _receipt("r-vector-timeout-outcome", "outcome"),
            ),
        ),
        "refused": GovernedCallResponse(
            request_ref="req-vector-refused",
            logical_call_id="call:vector:refused",
            decision=GovernedDecision(disposition="refused"),
            receipts=(_receipt("r-vector-refused-admission", "admission"),),
            diagnostic_code="policy_refused",
        ),
        "deferred": GovernedCallResponse(
            request_ref="req-vector-deferred",
            logical_call_id="call:vector:deferred",
            decision=GovernedDecision(disposition="deferred"),
            receipts=(_receipt("r-vector-deferred-admission", "admission"),),
            review_object_ref="review:vector:1",
            retry_instruction="retry_after_approval",
            diagnostic_code="deferred_for_review",
        ),
        "cancellation": GovernedCallResponse(
            request_ref="req-vector-cancel",
            logical_call_id="call:vector:cancel",
            decision=GovernedDecision(disposition="admitted", outcome="cancellation"),
            receipts=(
                _receipt("r-vector-cancel-admission", "admission"),
                _receipt("r-vector-cancel-outcome", "outcome"),
            ),
            cancellation_facts=CancellationFacts(
                request_cancelled=True,
                execution_state_unknown=True,
                delivery_incomplete=True,
            ),
            diagnostic_code="cancelled",
        ),
        "task_submitted": GovernedCallResponse(
            request_ref="req-vector-task",
            logical_call_id="call:vector:task",
            decision=GovernedDecision(disposition="admitted", outcome="task_submitted"),
            receipts=(
                _receipt("r-vector-task-admission", "admission"),
                _receipt("r-vector-task-outcome", "outcome"),
            ),
        ),
        # The service contract represents its currently unsupported
        # input_required lifecycle row with decision=None rather than coercing
        # it into an admitted/refused/deferred decision.
        "unsupported_lifecycle": GovernedCallResponse(
            request_ref="req-vector-unsupported",
            logical_call_id="call:vector:unsupported",
            decision=None,
            diagnostic_code="unsupported_lifecycle_state",
        ),
    }
    return {name: response.to_dict() for name, response in responses.items()}


def render_vectors() -> bytes:
    return (
        json.dumps(build_vectors(), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    payload = render_vectors()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
