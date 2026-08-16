"""Product-neutral governed-action membrane v0.1.

This module is a thin, offline membrane around the existing neutral receipt
substrate. It models a governed action request, a deterministic ALLOW / REFUSE /
DEFER decision, and the bounded receipt facts that can be emitted through the
shared SRS machinery.

It is intentionally product-neutral:

* no MCP types;
* no transport side effects;
* no truth / verification / confidence semantics;
* no source-record or standing vocabulary.

The module only uses the neutral lifecycle substrate and the shared SRS receipt
emitter. It deep-freezes caller-owned request state before any identity digest is
derived so later caller mutation cannot affect the request, the decision, or the
resulting receipt facts.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from dagr_mcp_core.lifecycle.core import plan_outcome_strict
from dagr_mcp_core.lifecycle.models import (
    AdmissionPlan,
    ExecutionObservation,
    NeutralDisposition,
    NeutralOutcome,
)
from dagr_mcp_core.srs_receipts import ReceiptContext, SignedReceiptEmitter, sha256_digest

GovernedActionDecisionLabel = Literal["allow", "refuse", "defer"]
GOVERNED_ACTION_DECISION_LABELS: tuple[GovernedActionDecisionLabel, ...] = (
    "allow",
    "refuse",
    "defer",
)

GovernedActionReasonCode = Literal[
    "policy_refused",
    "unknown_tool_fail_closed",
    "unknown_capability_fail_closed",
    "capability_mismatch",
    "scope_widening_attempt",
    "malformed_principal",
    "unknown_policy_fail_closed",
    "malformed_policy",
    "policy_version_mismatch",
]
GOVERNED_ACTION_REASON_CODES: tuple[GovernedActionReasonCode, ...] = (
    "policy_refused",
    "unknown_tool_fail_closed",
    "unknown_capability_fail_closed",
    "capability_mismatch",
    "scope_widening_attempt",
    "malformed_principal",
    "unknown_policy_fail_closed",
    "malformed_policy",
    "policy_version_mismatch",
)


def _validate_non_empty_text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _validate_principal_ref(name: str, value: Any) -> str:
    value = _validate_non_empty_text(name, value)
    if ":" not in value:
        raise ValueError(f"{name} must be a principal-shaped reference")
    return value


def _validate_policy_ref(name: str, value: Any) -> str:
    value = _validate_non_empty_text(name, value)
    if ":" not in value:
        raise ValueError(f"{name} must be a policy-shaped reference")
    return value


def _freeze_value(value: Any) -> Any:
    """Deep-freeze JSON-like caller input into a detached immutable snapshot."""

    if isinstance(value, Mapping):
        return (
            "__mapping__",
            tuple(sorted(((str(key), _freeze_value(item)) for key, item in value.items()), key=lambda kv: kv[0])),
        )
    if isinstance(value, list):
        return ("__sequence__", tuple(_freeze_value(item) for item in value))
    if isinstance(value, tuple):
        return ("__sequence__", tuple(_freeze_value(item) for item in value))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported semantic value type: {type(value).__name__}")


def _thaw_value(value: Any) -> Any:
    if isinstance(value, tuple) and len(value) == 2 and value[0] == "__mapping__":
        return {key: _thaw_value(item) for key, item in value[1]}
    if isinstance(value, tuple) and len(value) == 2 and value[0] == "__sequence__":
        return [_thaw_value(item) for item in value[1]]
    return value


def _freeze_correlation_metadata(metadata: Mapping[str, Any] | None) -> tuple[tuple[str, Any], ...]:
    if metadata is None:
        return ()
    frozen = _freeze_value(metadata)
    if not (
        isinstance(frozen, tuple)
        and len(frozen) == 2
        and frozen[0] == "__mapping__"
    ):
        raise TypeError("correlation metadata must be mapping-like")
    return tuple(frozen[1])


def _identity_payload(
    *,
    request_ref: str,
    principal_ref: str,
    tool_name: str,
    action_name: str,
    requested_scope: str,
    policy_ref: str,
    policy_version: str,
    session_ref: str | None,
    arguments_snapshot: Any,
) -> dict[str, Any]:
    return {
        "request_ref": request_ref,
        "principal_ref": principal_ref,
        "tool_name": tool_name,
        "action_name": action_name,
        "requested_scope": requested_scope,
        "policy_ref": policy_ref,
        "policy_version": policy_version,
        "session_ref": session_ref,
        "arguments_snapshot": _thaw_value(arguments_snapshot),
    }


def _decision_payload(
    *,
    request_identity: str,
    decision: GovernedActionDecisionLabel,
    reason_code: str | None,
    policy_ref: str,
    policy_version: str,
    considered_capability: str,
    considered_scope: str,
) -> dict[str, Any]:
    return {
        "request_identity": request_identity,
        "decision": decision,
        "reason_code": reason_code,
        "policy_ref": policy_ref,
        "policy_version": policy_version,
        "considered_capability": considered_capability,
        "considered_scope": considered_scope,
    }


def _receipt_payload(
    *,
    request_identity: str,
    decision_identity: str,
    decision: GovernedActionDecisionLabel,
    execution_performed: bool,
    execution_outcome: NeutralOutcome | None,
    execution_summary_digest: str | None,
) -> dict[str, Any]:
    return {
        "request_identity": request_identity,
        "decision_identity": decision_identity,
        "decision": decision,
        "execution_performed": execution_performed,
        "execution_outcome": execution_outcome,
        "execution_summary_digest": execution_summary_digest,
    }


@dataclass(frozen=True, slots=True)
class GovernedActionBoundaryConfig:
    """Policy and capability rails for a governed action membrane."""

    policy_ref: str
    policy_version: str
    known_capabilities: frozenset[str]
    admitted_capabilities: frozenset[str]
    deferred_capabilities: frozenset[str] = frozenset()
    admitted_scopes: frozenset[str] = frozenset()
    boundary_id: str = "boundary:governed-action"
    runtime_instance_id: str = "runtime:governed-action"
    policy_pack_id: str = "policy-pack:governed-action"
    policy_pack_version: str = "v0.1"

    def __post_init__(self) -> None:
        _validate_policy_ref("policy_ref", self.policy_ref)
        _validate_non_empty_text("policy_version", self.policy_version)
        if not isinstance(self.known_capabilities, frozenset):
            raise TypeError("known_capabilities must be a frozenset of strings")
        if not isinstance(self.admitted_capabilities, frozenset):
            raise TypeError("admitted_capabilities must be a frozenset of strings")
        if not isinstance(self.deferred_capabilities, frozenset):
            raise TypeError("deferred_capabilities must be a frozenset of strings")
        if not isinstance(self.admitted_scopes, frozenset):
            raise TypeError("admitted_scopes must be a frozenset of strings")


@dataclass(frozen=True, slots=True)
class GovernedActionRequest:
    """Deep-frozen request snapshot for a governed action."""

    request_ref: str
    principal_ref: str
    tool_name: str
    action_name: str
    requested_scope: str
    policy_ref: str
    policy_version: str
    arguments_snapshot: Any
    session_ref: str | None = None
    correlation_metadata: tuple[tuple[str, Any], ...] = ()
    request_identity: str = field(init=False)
    argument_digest: str = field(init=False)

    def __post_init__(self) -> None:
        request_ref = _validate_non_empty_text("request_ref", self.request_ref)
        principal_ref = _validate_principal_ref("principal_ref", self.principal_ref)
        tool_name = _validate_non_empty_text("tool_name", self.tool_name)
        action_name = _validate_non_empty_text("action_name", self.action_name)
        requested_scope = _validate_non_empty_text("requested_scope", self.requested_scope)
        policy_ref = _validate_policy_ref("policy_ref", self.policy_ref)
        policy_version = _validate_non_empty_text("policy_version", self.policy_version)

        arguments_snapshot = _freeze_value(self.arguments_snapshot)
        correlation_metadata = _freeze_correlation_metadata(dict(self.correlation_metadata))
        session_ref = self.session_ref
        if session_ref is not None:
            session_ref = _validate_non_empty_text("session_ref", session_ref)

        object.__setattr__(self, "request_ref", request_ref)
        object.__setattr__(self, "principal_ref", principal_ref)
        object.__setattr__(self, "tool_name", tool_name)
        object.__setattr__(self, "action_name", action_name)
        object.__setattr__(self, "requested_scope", requested_scope)
        object.__setattr__(self, "policy_ref", policy_ref)
        object.__setattr__(self, "policy_version", policy_version)
        object.__setattr__(self, "session_ref", session_ref)
        object.__setattr__(self, "arguments_snapshot", arguments_snapshot)
        object.__setattr__(self, "correlation_metadata", correlation_metadata)

        object.__setattr__(
            self,
            "argument_digest",
            sha256_digest(_thaw_value(arguments_snapshot)),
        )
        object.__setattr__(
            self,
            "request_identity",
            sha256_digest(
                _identity_payload(
                    request_ref=request_ref,
                    principal_ref=principal_ref,
                    tool_name=tool_name,
                    action_name=action_name,
                    requested_scope=requested_scope,
                    policy_ref=policy_ref,
                    policy_version=policy_version,
                    session_ref=session_ref,
                    arguments_snapshot=arguments_snapshot,
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class GovernedActionDecision:
    """Deterministic ALLOW / REFUSE / DEFER decision for one request."""

    request_identity: str
    decision: GovernedActionDecisionLabel
    considered_capability: str
    considered_scope: str
    policy_ref: str
    policy_version: str
    reason_code: GovernedActionReasonCode | None = None
    correlation_metadata: tuple[tuple[str, Any], ...] = ()
    decision_identity: str = field(init=False)

    def __post_init__(self) -> None:
        if self.decision not in GOVERNED_ACTION_DECISION_LABELS:
            raise ValueError(f"unknown governed-action decision {self.decision!r}")
        if self.reason_code is not None and self.reason_code not in GOVERNED_ACTION_REASON_CODES:
            raise ValueError(f"unknown governed-action reason code {self.reason_code!r}")
        object.__setattr__(self, "considered_capability", _validate_non_empty_text("considered_capability", self.considered_capability))
        object.__setattr__(self, "considered_scope", _validate_non_empty_text("considered_scope", self.considered_scope))
        object.__setattr__(self, "policy_ref", _validate_non_empty_text("policy_ref", self.policy_ref))
        object.__setattr__(self, "policy_version", _validate_non_empty_text("policy_version", self.policy_version))
        object.__setattr__(self, "correlation_metadata", _freeze_correlation_metadata(dict(self.correlation_metadata)))
        object.__setattr__(
            self,
            "decision_identity",
            sha256_digest(
                _decision_payload(
                    request_identity=self.request_identity,
                    decision=self.decision,
                    reason_code=self.reason_code,
                    policy_ref=self.policy_ref,
                    policy_version=self.policy_version,
                    considered_capability=self.considered_capability,
                    considered_scope=self.considered_scope,
                )
            ),
        )

    @property
    def neutral_disposition(self) -> NeutralDisposition:
        return {
            "allow": "admitted",
            "refuse": "refused",
            "defer": "deferred",
        }[self.decision]


@dataclass(frozen=True, slots=True)
class GovernedActionResult:
    """Bounded facts for a governed action request / decision / receipt chain."""

    request: GovernedActionRequest
    decision: GovernedActionDecision
    execution_performed: bool
    execution_outcome: NeutralOutcome | None
    execution_exception_class: str | None
    execution_summary_digest: str | None
    admission_receipt_ref: str | None
    outcome_receipt_ref: str | None
    receipt_persisted: bool
    receipt_gap: bool
    receipt_identity: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "receipt_identity",
            sha256_digest(
                _receipt_payload(
                    request_identity=self.request.request_identity,
                    decision_identity=self.decision.decision_identity,
                    decision=self.decision.decision,
                    execution_performed=self.execution_performed,
                    execution_outcome=self.execution_outcome,
                    execution_summary_digest=self.execution_summary_digest,
                )
            ),
        )


def decide_governed_action(
    request: GovernedActionRequest,
    config: GovernedActionBoundaryConfig,
) -> GovernedActionDecision:
    """Deterministically classify a request under a closed policy/config pair."""

    if request.policy_ref != config.policy_ref:
        return GovernedActionDecision(
            request_identity=request.request_identity,
            decision="refuse",
            considered_capability=request.tool_name,
            considered_scope=request.requested_scope,
            policy_ref=config.policy_ref,
            policy_version=config.policy_version,
            reason_code="unknown_policy_fail_closed",
            correlation_metadata=request.correlation_metadata,
        )

    if request.policy_version != config.policy_version:
        return GovernedActionDecision(
            request_identity=request.request_identity,
            decision="refuse",
            considered_capability=request.tool_name,
            considered_scope=request.requested_scope,
            policy_ref=config.policy_ref,
            policy_version=config.policy_version,
            reason_code="policy_version_mismatch",
            correlation_metadata=request.correlation_metadata,
        )

    if request.tool_name not in config.known_capabilities:
        return GovernedActionDecision(
            request_identity=request.request_identity,
            decision="refuse",
            considered_capability=request.tool_name,
            considered_scope=request.requested_scope,
            policy_ref=config.policy_ref,
            policy_version=config.policy_version,
            reason_code="unknown_tool_fail_closed",
            correlation_metadata=request.correlation_metadata,
        )

    if request.tool_name in config.deferred_capabilities:
        return GovernedActionDecision(
            request_identity=request.request_identity,
            decision="defer",
            considered_capability=request.tool_name,
            considered_scope=request.requested_scope,
            policy_ref=config.policy_ref,
            policy_version=config.policy_version,
            correlation_metadata=request.correlation_metadata,
        )

    if request.tool_name not in config.admitted_capabilities:
        return GovernedActionDecision(
            request_identity=request.request_identity,
            decision="refuse",
            considered_capability=request.tool_name,
            considered_scope=request.requested_scope,
            policy_ref=config.policy_ref,
            policy_version=config.policy_version,
            reason_code="capability_mismatch",
            correlation_metadata=request.correlation_metadata,
        )

    if config.admitted_scopes and request.requested_scope not in config.admitted_scopes:
        return GovernedActionDecision(
            request_identity=request.request_identity,
            decision="refuse",
            considered_capability=request.tool_name,
            considered_scope=request.requested_scope,
            policy_ref=config.policy_ref,
            policy_version=config.policy_version,
            reason_code="scope_widening_attempt",
            correlation_metadata=request.correlation_metadata,
        )

    return GovernedActionDecision(
        request_identity=request.request_identity,
        decision="allow",
        considered_capability=request.tool_name,
        considered_scope=request.requested_scope,
        policy_ref=config.policy_ref,
        policy_version=config.policy_version,
        correlation_metadata=request.correlation_metadata,
    )


def _emit_admission(
    *,
    emitter: SignedReceiptEmitter,
    receipt_context: ReceiptContext,
    request: GovernedActionRequest,
    decision: GovernedActionDecision,
) -> str:
    kwargs: dict[str, Any] = {
        "context": receipt_context,
        "requested_tool_name": request.tool_name,
        "argument_digest": request.argument_digest,
        "disposition": decision.neutral_disposition,
        "additional_attestation_limits": (),
    }
    if decision.reason_code is not None:
        kwargs["reason_code"] = decision.reason_code
    if decision.decision == "defer":
        kwargs["retry_contract"] = "retry_after_approval"
    return emitter.emit_admission(**kwargs)


def _emit_outcome(
    *,
    emitter: SignedReceiptEmitter,
    receipt_context: ReceiptContext,
    admission_receipt_ref: str,
    execution_outcome: NeutralOutcome,
    execution_result: Any | None = None,
    execution_exception_class: str | None = None,
) -> str:
    planned = plan_outcome_strict(
        AdmissionPlan(
            requested_disposition="admitted",
            resolved_disposition="admitted",
            record=None,
            admission_recorded=True,
            execution_proceeds=True,
        ),
        ExecutionObservation(
            observation=execution_outcome,
            exception_class=execution_exception_class,
        ),
    ).record
    assert planned is not None

    emission_kwargs: dict[str, Any] = {
        "context": receipt_context,
        "admission_receipt_ref": admission_receipt_ref,
        "outcome": {
            "result": "result_returned",
            "error": "error_returned",
            "exception": "exception",
            "task_submitted": "task_submitted",
            "timeout": "exception",
            "cancellation": "indeterminate",
            "input_required": "indeterminate",
        }[execution_outcome],
    }
    if planned.carries_result_digest and execution_result is not None:
        emission_kwargs["result_digest"] = sha256_digest(execution_result)
    if planned.exception_class is not None:
        emission_kwargs["exception_class"] = planned.exception_class
    return emitter.emit_outcome(**emission_kwargs)


def run_governed_action(
    request: GovernedActionRequest,
    *,
    config: GovernedActionBoundaryConfig,
    receipt_context: ReceiptContext,
    executor: Callable[[Mapping[str, Any]], Any],
    emitter: SignedReceiptEmitter,
) -> GovernedActionResult:
    """Execute a governed action with deterministic decisioning and receipts."""

    decision = decide_governed_action(request, config)
    admission_receipt_ref = _emit_admission(
        emitter=emitter,
        receipt_context=receipt_context,
        request=request,
        decision=decision,
    )

    if decision.decision != "allow":
        return GovernedActionResult(
            request=request,
            decision=decision,
            execution_performed=False,
            execution_outcome=None,
            execution_exception_class=None,
            execution_summary_digest=None,
            admission_receipt_ref=admission_receipt_ref,
            outcome_receipt_ref=None,
            receipt_persisted=True,
            receipt_gap=False,
        )

    execution_performed = True
    execution_result: Any | None = None
    execution_outcome: NeutralOutcome = "result"
    execution_exception_class: str | None = None
    try:
        execution_result = executor(_thaw_value(request.arguments_snapshot))
    except TimeoutError as exc:
        execution_outcome = "timeout"
        execution_exception_class = type(exc).__name__
    except Exception as exc:  # noqa: BLE001 - we classify then re-raise nothing.
        execution_outcome = "exception"
        execution_exception_class = type(exc).__name__
        execution_result = None

    execution_summary_digest: str | None
    if execution_outcome in ("result", "error"):
        execution_summary_digest = sha256_digest(execution_result)
    else:
        execution_summary_digest = sha256_digest(
            {
                "execution_outcome": execution_outcome,
                "exception_class": execution_exception_class,
            }
        )

    outcome_receipt_ref: str | None = None
    receipt_gap = False
    receipt_persisted = True
    try:
        outcome_receipt_ref = _emit_outcome(
            emitter=emitter,
            receipt_context=receipt_context,
            admission_receipt_ref=admission_receipt_ref,
            execution_outcome=execution_outcome,
            execution_result=execution_result,
            execution_exception_class=execution_exception_class,
        )
    except Exception:  # noqa: BLE001 - a durability gap never reclassifies execution.
        receipt_gap = True
        receipt_persisted = False

    return GovernedActionResult(
        request=request,
        decision=decision,
        execution_performed=execution_performed,
        execution_outcome=execution_outcome,
        execution_exception_class=execution_exception_class,
        execution_summary_digest=execution_summary_digest,
        admission_receipt_ref=admission_receipt_ref,
        outcome_receipt_ref=outcome_receipt_ref,
        receipt_persisted=receipt_persisted,
        receipt_gap=receipt_gap,
    )


__all__ = [
    "GovernedActionBoundaryConfig",
    "GovernedActionDecision",
    "GovernedActionDecisionLabel",
    "GovernedActionRequest",
    "GovernedActionReasonCode",
    "GovernedActionResult",
    "GOVERNED_ACTION_DECISION_LABELS",
    "GOVERNED_ACTION_REASON_CODES",
    "decide_governed_action",
    "run_governed_action",
]
