"""Official Python MCP SDK v2 (protocol 2026-07-28) lifecycle adapter.

The governed ``tools/call`` handler contract: receive the SDK's trusted
``ServerRequestContext`` and typed ``CallToolRequestParams``, resolve actor and
policy only from trusted context, make the admission decision via
:mod:`dagr_mcp_core.lifecycle.core`, durably emit the signed admission receipt
*before* any delegate dispatch, and -- if admission proceeds -- invoke the
delegate exactly once, classify its result through the frozen
:mod:`dagr_mcp_sdk_v2.result_digest` projection, and emit exactly one linked
outcome receipt.

This binding's ``tools/call`` scope is ``resultType: complete`` only; a
delegate returning ``InputRequiredResult`` is an explicit, fail-closed binding
capability difference (mirroring how the ``official-mcp-sdk.python.v0.1``
binding fails closed on ``CreateTaskResult`` -- see
``dagr_mcp_sdk_binding.adapter.TaskSubmissionUnsupported``), not a coerced
outcome.

Refusal and the input_required capability difference are both signaled by
raising an :class:`mcp.shared.exceptions.MCPError` subclass. This is a public,
verified-safe seam on the v2 SDK: ``ServerRunner``/``modern_error_data`` maps an
``MCPError`` to its own carried ``ErrorData`` (message and all) on the wire,
rather than collapsing it to a generic "Internal server error" (which is what
happens to an arbitrary, non-``MCPError`` exception) -- so raising here yields
the "explicit supported diagnostic" the governed-handler contract requires,
never a server crash.

Unknown-tool handling is a deliberate behavior difference from the
``official-mcp-sdk.python.v0.1`` binding: v0.1's default policy resolver admits
any tool name not otherwise classified (as "read"); v0.2's acceptance matrix
requires "no unauthorized dispatch" for an unrecognized tool, so the default
policy here refuses (``unknown_tool_fail_closed``) any tool name absent from
``SdkV2BindingConfig.tool_classes``.
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeAlias

from mcp import types as mcp_types
from mcp.server.context import ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp_types import INVALID_REQUEST

from dagr_mcp_core.lifecycle.core import plan_admission, plan_outcome_strict
from dagr_mcp_core.lifecycle.models import (
    AdmissionPlan,
    AdmissionRequest,
    ExecutionObservation,
    UnsupportedLifecycleEvent,
)
from dagr_mcp_core.srs_receipts import ReceiptContext, SignedReceiptEmitter, sha256_digest

from dagr_mcp_sdk_v2.result_digest import project_v2_tool_result

BINDING_VERSION = "official-mcp-sdk.python.v0.2"

# The boundary limit every receipt this binding emits carries, mirroring the
# FastMCP and v0.1 bindings' own DEFAULT_BOUNDARY_LIMIT convention.
DEFAULT_BOUNDARY_LIMIT = (
    "The governed handler is composed once around the tools/call dispatch of a "
    "single stateless Streamable HTTP (protocol 2026-07-28) server app; "
    "receipts attest only to observations at that boundary."
)

GovernedToolClass = Literal["read", "write", "destructive"]
Disposition = Literal["admitted", "refused"]
ReceiptFailureMode = Literal["fail_open", "fail_closed"]

# Neutral outcome record family -> the binding's outcome token. Identical to the
# FastMCP / v0.1 binding vocabulary; task_submitted is out of scope for v2 (this
# binding supports tools/call, resultType=complete, only -- see module docstring
# of dagr_mcp_sdk_v2.server).
_OUTCOME_TOKEN_MAP: Mapping[str, str] = {
    "result": "result_returned",
    "error": "error_returned",
    "exception": "exception",
    "cancellation": "indeterminate",
}


class SDKV2BindingError(MCPError):
    """Base class for the v0.2 binding's fail-closed diagnostics.

    Subclasses :class:`mcp.shared.exceptions.MCPError` so the SDK's own
    exception-to-``ErrorData`` mapping (``handler_exception_to_error_data``)
    preserves the exact message on the wire instead of collapsing it to a
    generic internal-error response.
    """

    def __init__(self, message: str, *, code: int = INVALID_REQUEST) -> None:
        super().__init__(code=code, message=message)


class ToolRefused(SDKV2BindingError):
    """Raised when admission refuses a call; the delegate never runs."""


class InputRequiredUnsupported(SDKV2BindingError):
    """Raised (fail-closed) when a delegate returns ``InputRequiredResult``.

    This binding does not support MRTR yet (see the module docstring of
    :mod:`dagr_mcp_sdk_v2.server`). No outcome receipt is emitted for this
    event -- the neutral core's ``UNSUPPORTED_OUTCOMES`` already hard-stops
    ``input_required``, so nothing is ever planned for it, matching "no
    misleading complete outcome."
    """


ToolHandler: TypeAlias = Callable[
    [Mapping[str, Any]], "Awaitable[mcp_types.CallToolResult | mcp_types.InputRequiredResult] | mcp_types.CallToolResult"
]


@dataclass(frozen=True, slots=True)
class ActorResolution:
    actor_ref: str | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None


class SdkV2ActorResolver(Protocol):
    """Resolve actor identity from the *trusted* request context only.

    Never handed the model-supplied tool arguments -- only the SDK's trusted
    :class:`ServerRequestContext` and the already-computed argument digest (for
    logging/correlation use, never for authority) -- so a tool argument can
    never define actor/tenant identity.
    """

    def __call__(
        self, ctx: ServerRequestContext[Any, Any], argument_digest: str
    ) -> ActorResolution | Awaitable[ActorResolution]: ...


@dataclass(slots=True)
class SdkV2BindingConfig:
    """Configuration for the official-SDK v0.2 binding (no module-global state)."""

    runtime_instance_id: str
    boundary_id: str
    policy_pack_id: str
    policy_pack_version: str
    tool_classes: Mapping[str, GovernedToolClass] = field(default_factory=dict)
    actor_resolver: SdkV2ActorResolver | None = None
    pre_execution_receipt_failure: Mapping[GovernedToolClass, ReceiptFailureMode] = field(
        default_factory=lambda: {
            "read": "fail_open",
            "write": "fail_closed",
            "destructive": "fail_closed",
        }
    )
    additional_attestation_limits: tuple[str, ...] = (DEFAULT_BOUNDARY_LIMIT,)


class SdkV2LifecycleAdapter:
    """Governs an official-SDK-v2 ``tools/call`` around the neutral lifecycle core."""

    def __init__(self, *, emitter: SignedReceiptEmitter, config: SdkV2BindingConfig) -> None:
        self.emitter = emitter
        self.config = config
        self.local_telemetry: list[dict[str, Any]] = []

    async def governed_call_tool(
        self,
        ctx: ServerRequestContext[Any, Any],
        params: mcp_types.CallToolRequestParams,
        delegate: ToolHandler,
    ) -> mcp_types.CallToolResult:
        """Run the neutral lifecycle around a delegated ``tools/call`` dispatch."""

        if ctx.method != "tools/call":
            raise SDKV2BindingError(
                f"governed_call_tool invoked for non-tools/call method {ctx.method!r}"
            )

        tool_name = params.name
        arguments = dict(params.arguments or {})
        argument_digest = sha256_digest(arguments)

        actor = await self._resolve_actor(ctx, argument_digest)
        tool_class = self.config.tool_classes.get(tool_name)
        receipt_context = self._receipt_context(ctx, actor)

        if tool_class is None:
            admission_plan = plan_admission(
                AdmissionRequest(disposition="refused", refusal_ground="unknown_tool_fail_closed")
            )
            self._emit_terminal_refusal(admission_plan, receipt_context, tool_name, argument_digest)
            raise ToolRefused(f"Unknown tool {tool_name!r}; no unauthorized dispatch")

        admission_plan = plan_admission(AdmissionRequest(disposition="admitted", tool_class=tool_class))
        assert admission_plan.execution_proceeds  # "admitted" always proceeds; policy never returns "refused" here.

        admission_receipt_ref: str | None = None
        if admission_plan.admission_recorded:
            try:
                admission_receipt_ref = self.emitter.emit_admission(
                    context=receipt_context,
                    requested_tool_name=tool_name,
                    argument_digest=argument_digest,
                    disposition="admitted",
                    additional_attestation_limits=self.config.additional_attestation_limits,
                )
            except Exception as exc:  # noqa: BLE001 - fail policy classifies it.
                self._record_receipt_failure(receipt_context, "admission", exc)
                if self._pre_execution_failure_mode(tool_class) == "fail_closed":
                    raise ToolRefused(
                        f"Admission receipt could not be durably accepted for {tool_name!r}"
                    ) from None
                # fail_open: proceed with no admission reference; no outcome will
                # be emitted later either (mirrors the admitted-read-skip path).

        try:
            result = await _maybe_await(delegate(arguments))
        except asyncio.CancelledError:
            if admission_receipt_ref is not None:
                self._emit_outcome_from_observation(
                    admission_plan, receipt_context, admission_receipt_ref,
                    ExecutionObservation(observation="cancellation"),
                )
            raise
        except Exception as exc:  # noqa: BLE001 - classified into a neutral outcome, then re-raised.
            if admission_receipt_ref is not None:
                observation = (
                    ExecutionObservation(observation="timeout")
                    if isinstance(exc, TimeoutError)
                    else ExecutionObservation(observation="exception", exception_class=type(exc).__name__)
                )
                self._emit_outcome_from_observation(
                    admission_plan, receipt_context, admission_receipt_ref, observation
                )
            raise

        if isinstance(result, mcp_types.InputRequiredResult) or getattr(result, "result_type", "complete") == "input_required":
            if admission_receipt_ref is not None:
                # The core's UNSUPPORTED_OUTCOMES already hard-stops this event:
                # plan_outcome_strict raises, and nothing is ever emitted for it.
                # This call exists only as a checked invariant -- if the core ever
                # started planning a record for input_required, this would surface
                # that divergence loudly instead of silently emitting a misleading
                # receipt.
                try:
                    plan_outcome_strict(admission_plan, ExecutionObservation(observation="input_required"))
                    raise SDKV2BindingError(  # pragma: no cover - core invariant guard
                        "core unexpectedly planned an outcome record for input_required"
                    )
                except UnsupportedLifecycleEvent:
                    pass
            raise InputRequiredUnsupported(
                f"Tool {tool_name!r} returned an input_required result; the "
                f"{BINDING_VERSION} binding does not support MRTR and fails "
                "closed rather than emitting a misleading complete outcome."
            )

        if admission_receipt_ref is None:
            return result

        projection = project_v2_tool_result(result)
        result_digest = sha256_digest(projection)
        observation = ExecutionObservation(
            observation="error" if projection["is_error"] else "result"
        )
        self._emit_outcome_from_observation(
            admission_plan, receipt_context, admission_receipt_ref, observation,
            result_digest=result_digest,
        )
        return result

    # ------------------------------------------------------------------ #
    # Trusted-context extraction                                         #
    # ------------------------------------------------------------------ #

    async def _resolve_actor(
        self, ctx: ServerRequestContext[Any, Any], argument_digest: str
    ) -> ActorResolution:
        if self.config.actor_resolver is not None:
            resolved = self.config.actor_resolver(ctx, argument_digest)
            if inspect.isawaitable(resolved):
                resolved = await resolved
            return resolved
        return ActorResolution()

    def _receipt_context(
        self, ctx: ServerRequestContext[Any, Any], actor: ActorResolution
    ) -> ReceiptContext:
        request_id = getattr(ctx, "request_id", None)
        request_ref = f"request:{request_id}" if request_id is not None else None
        logical_call_id = request_ref or f"call:{uuid.uuid4()}"
        subject_ref = request_ref or f"tool-call:{logical_call_id}"
        return ReceiptContext(
            runtime_instance_id=self.config.runtime_instance_id,
            boundary_id=self.config.boundary_id,
            policy_pack_id=self.config.policy_pack_id,
            policy_pack_version=self.config.policy_pack_version,
            subject_ref=subject_ref,
            logical_call_id=logical_call_id,
            actor_ref=actor.actor_ref,
            tenant_id=actor.tenant_id,
            workspace_id=actor.workspace_id,
            binding_version=BINDING_VERSION,
        )

    # ------------------------------------------------------------------ #
    # Admission / outcome emission                                       #
    # ------------------------------------------------------------------ #

    def _pre_execution_failure_mode(self, tool_class: GovernedToolClass) -> ReceiptFailureMode:
        return self.config.pre_execution_receipt_failure.get(tool_class, "fail_closed")

    def _emit_terminal_refusal(
        self,
        admission_plan: AdmissionPlan,
        receipt_context: ReceiptContext,
        tool_name: str,
        argument_digest: str,
    ) -> None:
        record = admission_plan.record
        assert record is not None  # a refused disposition always plans a record.
        try:
            self.emitter.emit_admission(
                context=receipt_context,
                requested_tool_name=tool_name,
                argument_digest=argument_digest,
                disposition="refused",
                reason_code=record.reason_code,
                additional_attestation_limits=self.config.additional_attestation_limits,
            )
        except Exception as exc:  # noqa: BLE001 - do not leak signer/sink failures to the caller.
            self._record_receipt_failure(receipt_context, "admission", exc)

    def _emit_outcome_from_observation(
        self,
        admission_plan: AdmissionPlan,
        receipt_context: ReceiptContext,
        admission_receipt_ref: str,
        observation: ExecutionObservation,
        *,
        result_digest: str | None = None,
    ) -> None:
        record = plan_outcome_strict(admission_plan, observation).record
        if record is None:  # pragma: no cover - guarded by admission_receipt_ref.
            return
        outcome_token = _OUTCOME_TOKEN_MAP[record.outcome]
        binding_owned_fields = (
            {fact: record.governance_facts_value for fact in record.governance_facts}
            if record.governance_facts
            else None
        )
        try:
            self.emitter.emit_outcome(
                context=receipt_context,
                admission_receipt_ref=admission_receipt_ref,
                outcome=outcome_token,
                result_digest=result_digest if record.carries_result_digest else None,
                exception_class=record.exception_class,
                additional_attestation_limits=self.config.additional_attestation_limits,
                binding_owned_fields=binding_owned_fields,
            )
        except Exception as exc:  # noqa: BLE001 - post-execution failure policy: return result, record telemetry.
            self._record_receipt_failure(receipt_context, "outcome", exc)

    def _record_receipt_failure(
        self, receipt_context: ReceiptContext, attempted_receipt_kind: str, failure: BaseException
    ) -> None:
        self.local_telemetry.append({
            "event_type": "receipt_gap",
            "runtime_instance_id": receipt_context.runtime_instance_id,
            "boundary_id": receipt_context.boundary_id,
            "logical_call_id": receipt_context.logical_call_id,
            "attempted_receipt_kind": attempted_receipt_kind,
            "failure_class": type(failure).__name__,
        })


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


__all__ = [
    "BINDING_VERSION",
    "DEFAULT_BOUNDARY_LIMIT",
    "GovernedToolClass",
    "Disposition",
    "ReceiptFailureMode",
    "SDKV2BindingError",
    "ToolRefused",
    "InputRequiredUnsupported",
    "ToolHandler",
    "ActorResolution",
    "SdkV2ActorResolver",
    "SdkV2BindingConfig",
    "SdkV2LifecycleAdapter",
]
