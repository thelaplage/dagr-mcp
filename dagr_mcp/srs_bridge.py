"""Bridge between the synchronous harness and signed SRS admission receipts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from .srs_receipts import ReceiptContext, SignedReceiptEmitter, fastmcp_tool_result_digest


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    runtime_instance_id: str
    boundary_id: str
    policy_pack_id: str
    policy_pack_version: str


class HarnessSRSBridge:
    def __init__(self, *, emitter: SignedReceiptEmitter, config: BridgeConfig):
        self.emitter = emitter
        self.config = config

    def _context(self, harness_context: Any) -> ReceiptContext:
        logical = harness_context.request_ref or f"call-{uuid.uuid4()}"
        subject = harness_context.session_ref or harness_context.request_ref or f"tool-call:{logical}"
        return ReceiptContext(
            runtime_instance_id=self.config.runtime_instance_id,
            boundary_id=self.config.boundary_id,
            policy_pack_id=self.config.policy_pack_id,
            policy_pack_version=self.config.policy_pack_version,
            subject_ref=subject,
            logical_call_id=logical,
            actor_ref=harness_context.actor_ref,
        )

    def emit_admission(
        self,
        *,
        harness_context: Any,
        tool_name: str,
        disposition: str,
        review_object_ref: str | None = None,
        retry_contract: str | None = None,
        reason_code: str | None = None,
    ) -> str:
        return self.emitter.emit_admission(
            context=self._context(harness_context),
            requested_tool_name=tool_name,
            argument_digest=harness_context.arguments_hash,
            disposition=disposition,
            review_object_ref=review_object_ref,
            retry_contract=retry_contract,
            reason_code=reason_code,
        )

    def emit_outcome(
        self,
        *,
        harness_context: Any,
        admission_receipt_ref: str,
        outcome: str,
        result_digest: str | None = None,
        result_value: Any | None = None,
        exception_class: str | None = None,
    ) -> str:
        if result_digest is None and outcome in {"result_returned", "error_returned"}:
            result_digest = fastmcp_tool_result_digest(
                content=None, structured_content=result_value, meta=None,
                is_error=outcome == "error_returned")
        return self.emitter.emit_outcome(
            context=self._context(harness_context),
            admission_receipt_ref=admission_receipt_ref,
            outcome=outcome,
            result_digest=result_digest,
            exception_class=exception_class,
        )
