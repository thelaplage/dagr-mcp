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
from mcp.server import ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_REQUEST

from dagr_sdk.caller_auth_context import ANONYMOUS_CALLER_AUTH_CONTEXT, CallerAuthContext

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


class AdmissionDeferredUnsupported(SDKV2BindingError):
    """Raised (fail-closed) when an operator admission resolver returns a
    ``"deferred"`` disposition.

    This lane (DAGR-MCP-SDKV2-CALLER0) gives the v0.2 binding a real operator
    admission-policy seam over the existing ``admitted`` / ``refused``
    dispositions only; it does not build deferred-for-review support (review
    object sinks, retry contracts) for this binding. A resolver that returns
    ``disposition="deferred"`` fails closed here rather than being silently
    coerced toward ``admitted`` or ``refused``.
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


class SdkV2CallerAuthResolver(Protocol):
    """Resolve the already-authenticated caller from the *trusted* request
    context only, projecting it onto the canonical
    :class:`dagr_sdk.caller_auth_context.CallerAuthContext` wire contract.

    Exactly like :class:`SdkV2ActorResolver`, this is never handed the
    model-supplied tool arguments -- only the SDK's trusted
    ``ServerRequestContext`` and the already-computed argument digest -- so a
    tool argument can never assert caller identity. This binding does not
    authenticate anything itself: a resolver here only *projects* a caller
    assertion an upstream, operator-owned auth boundary (e.g. an ARCS Forum
    ingress, or any other operator auth layer) has already validated. See
    ``dagr_sdk.caller_auth_context`` for what ``CallerAuthContext`` is (and is
    not) -- in particular, it carries no standing, delegation, or capability;
    it is not a route to DAGR admission by itself.
    """

    def __call__(
        self, ctx: ServerRequestContext[Any, Any], argument_digest: str
    ) -> CallerAuthContext | Awaitable[CallerAuthContext]: ...


class SdkV2AdmissionResolver(Protocol):
    """The operator admission-policy seam: decide the neutral admission
    disposition for one governed, already-known-tool call.

    Handed the resolved ``CallerAuthContext`` and ``ActorResolution`` (both
    already computed from trusted context, never from tool arguments), plus
    the tool name/class and argument digest, and returns a
    :class:`dagr_mcp_core.lifecycle.models.AdmissionRequest` -- the *same*
    neutral request type ``plan_admission`` already consumes for the built-in
    unknown-tool refusal path. This binding invents no second decision
    vocabulary: the resolver's own reasoning (e.g. "this caller's
    ``scope_refs`` do not include the scope this tool requires") is entirely
    the operator's, expressed as *whichever* neutral
    ``AdmissionRequest`` the operator returns -- DAGR itself never inspects
    ``CallerAuthContext.scope_refs`` or attaches any meaning to them.

    A refusal ground the operator resolver returns must be one of
    ``dagr_mcp_core.lifecycle.contract.NEUTRAL_REFUSAL_GROUNDS`` (the same
    closed vocabulary ``plan_admission`` already enforces for every other
    caller of this core); ``"policy_refused"`` is the general-purpose ground
    for an operator policy decision that isn't one of the three more specific
    grounds.
    """

    def __call__(
        self,
        *,
        ctx: ServerRequestContext[Any, Any],
        caller_auth: CallerAuthContext,
        actor: ActorResolution,
        tool_name: str,
        tool_class: GovernedToolClass,
        argument_digest: str,
    ) -> AdmissionRequest | Awaitable[AdmissionRequest]: ...


@dataclass(slots=True)
class SdkV2BindingConfig:
    """Configuration for the official-SDK v0.2 binding (no module-global state)."""

    runtime_instance_id: str
    boundary_id: str
    policy_pack_id: str
    policy_pack_version: str
    tool_classes: Mapping[str, GovernedToolClass] = field(default_factory=dict)
    actor_resolver: SdkV2ActorResolver | None = None
    # Consumes the canonical dagr-sdk caller-identity contract. Defaults to
    # ``None``, in which case every governed call resolves to
    # ``ANONYMOUS_CALLER_AUTH_CONTEXT`` (see ``_resolve_caller_auth``) -- so
    # every existing SDK-v2 caller that never supplies this stays exactly
    # byte-compatible with pre-DAGR-MCP-SDKV2-CALLER0 behavior.
    caller_auth_resolver: SdkV2CallerAuthResolver | None = None
    # The operator admission-policy seam. Defaults to ``None``, in which case
    # every known tool resolves to ``AdmissionRequest(disposition="admitted",
    # tool_class=tool_class)`` -- byte-identical to this binding's admission
    # decision before this seam existed. The built-in unknown-tool refusal
    # (``unknown_tool_fail_closed``) is unconditional and never routed through
    # this resolver -- it is decided before a resolver would ever see the
    # call, exactly as before.
    admission_resolver: SdkV2AdmissionResolver | None = None
    # Operator correlation overrides, matching the FastMCP and v0.1 SDK bindings
    # field-for-field. They exist here for the same reason they exist there: an
    # operator that already has its own subject or call-correlation identity can
    # supply it instead of letting the binding derive or mint one. They also make
    # the ``supplied_subject`` and ``derived_from_supplied_correlation`` origin
    # classes structurally reachable on this path (see ``_receipt_context``).
    logical_call_id_override: str | None = None
    subject_ref_override: str | None = None
    # Explicit opt-in: when True, this binding mints a fresh opaque
    # ``call:<uuid4>`` logical call id for *every* governed ``tools/call``
    # invocation, even when the trusted request context carries a
    # ``request_id`` that would otherwise be reused as the correlation
    # reference. Identity minting stays binding-owned -- no operator
    # callable/factory participates (see ``_receipt_context``). Defaults to
    # ``False`` so every existing caller's behavior is unchanged. Conflicts
    # with ``logical_call_id_override`` (see ``__post_init__``): the operator
    # cannot both supply a correlation id and ask the binding to mint one.
    mint_logical_call_id: bool = False
    pre_execution_receipt_failure: Mapping[GovernedToolClass, ReceiptFailureMode] = field(
        default_factory=lambda: {
            "read": "fail_open",
            "write": "fail_closed",
            "destructive": "fail_closed",
        }
    )
    additional_attestation_limits: tuple[str, ...] = (DEFAULT_BOUNDARY_LIMIT,)

    def __post_init__(self) -> None:
        if self.logical_call_id_override is not None and self.mint_logical_call_id:
            raise ValueError(
                "SdkV2BindingConfig: logical_call_id_override and "
                "mint_logical_call_id=True are conflicting operator "
                "instructions -- supply an explicit correlation id or ask "
                "the binding to mint one, not both."
            )


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

        caller_auth = await self._resolve_caller_auth(ctx, argument_digest)
        actor = await self._resolve_actor(ctx, argument_digest, caller_auth)
        tool_class = self.config.tool_classes.get(tool_name)
        receipt_context = self._receipt_context(ctx, actor)

        if tool_class is None:
            admission_plan = plan_admission(
                AdmissionRequest(disposition="refused", refusal_ground="unknown_tool_fail_closed")
            )
            self._emit_terminal_refusal(admission_plan, receipt_context, tool_name, argument_digest)
            raise ToolRefused(f"Unknown tool {tool_name!r}; no unauthorized dispatch")

        admission_request = await self._resolve_admission(
            ctx=ctx,
            caller_auth=caller_auth,
            actor=actor,
            tool_name=tool_name,
            tool_class=tool_class,
            argument_digest=argument_digest,
        )
        admission_plan = plan_admission(admission_request)

        if admission_plan.resolved_disposition == "refused":
            # Real refusal: the operator admission resolver decided this call
            # does not proceed. Emit the signed refused admission receipt
            # (exactly the same terminal path the built-in unknown-tool
            # refusal above uses) and stop -- the delegate never runs, and no
            # outcome receipt is ever emitted for a call that was refused.
            self._emit_terminal_refusal(admission_plan, receipt_context, tool_name, argument_digest)
            ground = admission_plan.record.reason_code if admission_plan.record is not None else None
            raise ToolRefused(
                f"Admission refused for {tool_name!r}" + (f" ({ground})" if ground else "")
            )
        if admission_plan.resolved_disposition == "deferred":  # pragma: no cover
            # Structurally unreachable: _narrow_operator_admission_request
            # already rejects an operator-requested "deferred" disposition
            # with AdmissionDeferredUnsupported BEFORE plan_admission is ever
            # called, and every other admission_request this method builds
            # (the unknown-tool refusal and the default admit) is
            # "refused"/"admitted" only. Kept as a checked invariant guard --
            # exactly the same pattern InputRequiredUnsupported's core-invariant
            # check above uses -- so a future change that let "deferred"
            # reach plan_admission would surface loudly instead of silently.
            raise AdmissionDeferredUnsupported(
                f"Operator admission resolver deferred {tool_name!r}; the "
                f"{BINDING_VERSION} binding does not support deferred-for-review "
                "admission."
            )
        assert admission_plan.resolved_disposition == "admitted"
        assert admission_plan.execution_proceeds

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

    async def _resolve_caller_auth(
        self, ctx: ServerRequestContext[Any, Any], argument_digest: str
    ) -> CallerAuthContext:
        if self.config.caller_auth_resolver is not None:
            resolved = self.config.caller_auth_resolver(ctx, argument_digest)
            if inspect.isawaitable(resolved):
                resolved = await resolved
            if not isinstance(resolved, CallerAuthContext):
                raise SDKV2BindingError(
                    "caller_auth_resolver returned "
                    f"{type(resolved).__name__}, not a "
                    "dagr_sdk.caller_auth_context.CallerAuthContext; failing "
                    "closed rather than carrying an unvalidated caller "
                    "assertion into admission."
                )
            return resolved
        return ANONYMOUS_CALLER_AUTH_CONTEXT

    async def _resolve_actor(
        self,
        ctx: ServerRequestContext[Any, Any],
        argument_digest: str,
        caller_auth: CallerAuthContext,
    ) -> ActorResolution:
        if self.config.actor_resolver is not None:
            resolved = self.config.actor_resolver(ctx, argument_digest)
            if inspect.isawaitable(resolved):
                resolved = await resolved
            return resolved
        # ActorResolution stays a separate, narrower concept from caller
        # authentication -- see the module docstring and
        # SdkV2AdmissionResolver's own docstring. The only default coupling
        # between the two is this one field-copy: an authenticated caller's
        # opaque principal_ref becomes the activity-attribution actor_ref on
        # the receipt (the existing ReceiptContext.actor_ref field, unchanged
        # shape); an anonymous caller yields no actor_ref, exactly as before
        # this lane. This does not create a Participant, standing,
        # delegation, or capability -- it is the same attribution semantic
        # ActorResolution already had, now with a sensible non-None default
        # for an authenticated caller instead of always None.
        if caller_auth.is_authenticated:
            return ActorResolution(actor_ref=caller_auth.principal_ref)
        return ActorResolution()

    async def _resolve_admission(
        self,
        *,
        ctx: ServerRequestContext[Any, Any],
        caller_auth: CallerAuthContext,
        actor: ActorResolution,
        tool_name: str,
        tool_class: GovernedToolClass,
        argument_digest: str,
    ) -> AdmissionRequest:
        if self.config.admission_resolver is not None:
            resolved = self.config.admission_resolver(
                ctx=ctx,
                caller_auth=caller_auth,
                actor=actor,
                tool_name=tool_name,
                tool_class=tool_class,
                argument_digest=argument_digest,
            )
            if inspect.isawaitable(resolved):
                resolved = await resolved
            if not isinstance(resolved, AdmissionRequest):
                raise SDKV2BindingError(
                    f"admission_resolver for {tool_name!r} returned "
                    f"{type(resolved).__name__}, not an "
                    "dagr_mcp_core.lifecycle.models.AdmissionRequest; "
                    "failing closed rather than planning an unvalidated "
                    "admission decision."
                )
            return self._narrow_operator_admission_request(
                resolved, tool_class=tool_class, tool_name=tool_name
            )
        # No operator resolver supplied: byte-identical to this binding's
        # admission decision before this seam existed -- every known tool is
        # admitted.
        return AdmissionRequest(disposition="admitted", tool_class=tool_class)

    def _narrow_operator_admission_request(
        self,
        operator_request: AdmissionRequest,
        *,
        tool_class: GovernedToolClass,
        tool_name: str,
    ) -> AdmissionRequest:
        """BINDING VALIDATION / NARROWING: the operator resolver's own
        ``AdmissionRequest`` object is NEVER forwarded verbatim into
        ``plan_admission``. Only two fields of it are ever honored --
        ``disposition`` (constrained to ``admitted``/``refused``) and, when
        refused, ``refusal_ground`` -- and the resulting request is REBUILT
        entirely from binding-owned state plus those two operator-permitted
        values.

        This closes the seam an operator resolver could otherwise use to
        reach binding-owned lifecycle semantics through ``AdmissionRequest``:
        it cannot suppress a read admission record via
        ``emit_read_admission_before_execution=False``, cannot present a
        ``tool_class`` different from this binding's own classification
        (``SdkV2BindingConfig.tool_classes``), and cannot manufacture a
        ``disposition="deferred"`` + ``review_object_created=False`` state
        that ``plan_admission`` would otherwise resolve into a real
        ``review_object_creation_failed`` refusal -- this SDK-v2 binding
        creates no review object, so that state would be semantically
        fabricated, not observed.
        """
        disposition = operator_request.disposition
        if disposition == "deferred":
            # Rejected BEFORE plan_admission ever runs: no admission record is
            # planned, no receipt (refusal or otherwise) is emitted for this
            # event, and no review-object state is ever touched.
            raise AdmissionDeferredUnsupported(
                f"Operator admission resolver requested deferred-for-review "
                f"admission for {tool_name!r}; the {BINDING_VERSION} binding "
                "does not support operator-manufactured deferral -- it "
                "creates no review object, so a deferred/"
                "review_object_created admission state would be fabricated, "
                "not observed. Rejected before core admission planning."
            )
        if disposition not in ("admitted", "refused"):
            raise SDKV2BindingError(
                f"admission_resolver for {tool_name!r} returned an "
                f"unrecognized disposition {disposition!r}; the operator may "
                "decide only 'admitted' or 'refused'."
            )
        if disposition == "refused":
            return AdmissionRequest(
                disposition="refused",
                tool_class=tool_class,
                refusal_ground=operator_request.refusal_ground,
            )
        # "admitted" -- every other field the operator's object may have
        # carried (tool_class, review_object_created,
        # emit_read_admission_before_execution, has_parent_boundary) is
        # discarded; the binding reconstitutes admission from its own state
        # only. emit_read_admission_before_execution / has_parent_boundary
        # stay at AdmissionRequest's own defaults (True / False) here because
        # this binding does not yet expose operator control over either --
        # adding that control is a separate, explicitly binding-owned config
        # surface, not something an operator's admission_resolver return
        # value can reach.
        return AdmissionRequest(disposition="admitted", tool_class=tool_class)

    def _receipt_context(
        self, ctx: ServerRequestContext[Any, Any], actor: ActorResolution
    ) -> ReceiptContext:
        request_id = getattr(ctx, "request_id", None)
        request_ref = f"request:{request_id}" if request_id is not None else None
        # Precedence: an explicit operator-supplied correlation id always wins;
        # otherwise, an explicit mint-per-invocation opt-in wins over reusing
        # the request reference (the whole point of the flag is to ignore
        # available request correlation for logical-call identity); otherwise
        # the request reference is reused as before; otherwise the binding
        # mints a fallback id. ``__post_init__`` already refuses the
        # ``logical_call_id_override`` + ``mint_logical_call_id=True``
        # combination, so at most one of the first two conditions is ever true.
        if self.config.logical_call_id_override:
            logical_call_id = self.config.logical_call_id_override
        elif self.config.mint_logical_call_id:
            logical_call_id = f"call:{uuid.uuid4()}"
        elif request_ref:
            logical_call_id = request_ref
        else:
            logical_call_id = f"call:{uuid.uuid4()}"
        # Each branch below both obtains the subject reference and declares how it
        # was obtained. The last two branches build the same subject string but
        # are not the same decision: one derives it from a correlation the
        # operator supplied, the other from a call id this binding minted.
        #
        # There is deliberately no ``derived_from_session`` branch here. Protocol
        # 2026-07-28 — the only protocol this binding serves — is a self-contained
        # POST with no ``initialize`` handshake and no ``Mcp-Session-Id``, and the
        # SDK's ``ServerRequestContext.session`` (a ``ServerSession``) exposes no
        # session identifier at all. That class is therefore structurally
        # unreachable on this path as a matter of the protocol, not an omission,
        # and is never substituted for by another class. See
        # docs/DAGR_MCP_SDK_V2_BINDING.md.
        if self.config.subject_ref_override:
            subject_ref = self.config.subject_ref_override
            subject_ref_origin = "supplied_subject"
        elif self.config.mint_logical_call_id:
            subject_ref = f"tool-call:{logical_call_id}"
            subject_ref_origin = "binding_minted"
        elif request_ref:
            subject_ref = request_ref
            subject_ref_origin = "derived_from_request"
        elif self.config.logical_call_id_override:
            subject_ref = f"tool-call:{logical_call_id}"
            subject_ref_origin = "derived_from_supplied_correlation"
        else:
            subject_ref = f"tool-call:{logical_call_id}"
            subject_ref_origin = "binding_minted"
        return ReceiptContext(
            runtime_instance_id=self.config.runtime_instance_id,
            boundary_id=self.config.boundary_id,
            policy_pack_id=self.config.policy_pack_id,
            policy_pack_version=self.config.policy_pack_version,
            subject_ref=subject_ref,
            subject_ref_origin=subject_ref_origin,
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
    "AdmissionDeferredUnsupported",
    "ToolHandler",
    "ActorResolution",
    "SdkV2ActorResolver",
    "SdkV2CallerAuthResolver",
    "SdkV2AdmissionResolver",
    "SdkV2BindingConfig",
    "SdkV2LifecycleAdapter",
]
