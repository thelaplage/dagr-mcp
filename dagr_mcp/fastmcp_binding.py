"""FastMCP middleware binding for signed DAGR/SRS receipts."""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
import os
import tempfile
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, TypeAlias

import rfc8785

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult

try:
    from mcp.types import CreateTaskResult

    CREATE_TASK_RESULT_IMPORT_PATH = "mcp.types.CreateTaskResult"
except ImportError:  # pragma: no cover - exercised by the FastMCP main canary.
    from mcp_types import CreateTaskResult  # type: ignore[no-redef]

    CREATE_TASK_RESULT_IMPORT_PATH = "mcp_types.CreateTaskResult"

from dagr_mcp.sdk_spine import ReviewObject, now_utc_iso
from dagr_mcp.srs_receipts import (
    ReceiptContentError,
    ReceiptContext,
    ReceiptWriteError,
    SignedReceiptEmitter,
    fastmcp_tool_result_digest,
    sha256_digest,
)

ToolClass: TypeAlias = Literal["read", "write", "destructive"]
Disposition: TypeAlias = Literal["admitted", "refused", "deferred_for_review"]
ReceiptFailureMode: TypeAlias = Literal["fail_closed", "fail_open"]
PostExecutionReceiptFailureMode: TypeAlias = Literal["alert_and_return_result"]

BINDING_VERSION = "fastmcp.middleware.v0.1"
DEFAULT_ANONYMOUS_ACTOR_REF = "actor:anonymous_or_local"
DEFAULT_BOUNDARY_LIMIT = (
    "The middleware is installed once at the institutional trust boundary; "
    "receipts attest only to observations at that boundary."
)
PROXY_BOUNDARY_LIMIT = (
    "The receipt attests only to what crossed and returned through the proxy boundary."
)


@dataclass(frozen=True, slots=True)
class RequestSnapshot:
    """Hash-only request facts captured before policy evaluation."""

    tool_name: str
    arguments_digest: str
    logical_call_id: str
    subject_ref: str
    session_ref: str | None = None
    request_ref: str | None = None
    meta_digest: str | None = None


@dataclass(frozen=True, slots=True)
class ActorResolution:
    """Actor identity projected into receipt-safe scoped references."""

    actor_ref: str = DEFAULT_ANONYMOUS_ACTOR_REF
    tenant_id: str | None = None
    workspace_id: str | None = None


@dataclass(frozen=True, slots=True)
class BindingPolicy:
    """Admission disposition and tool class resolved for a tool call."""

    disposition: Disposition = "admitted"
    tool_class: ToolClass = "read"
    reason_code: str | None = None
    parent_receipt_ref: str | None = None
    additional_attestation_limits: tuple[str, ...] = ()


class ActorResolver(Protocol):
    def __call__(
        self,
        context: MiddlewareContext[Any],
        snapshot: RequestSnapshot,
    ) -> ActorResolution | Awaitable[ActorResolution]:
        ...


class PolicyResolver(Protocol):
    def __call__(
        self,
        snapshot: RequestSnapshot,
        actor: ActorResolution,
    ) -> BindingPolicy | Awaitable[BindingPolicy]:
        ...


ReviewObjectCreator: TypeAlias = Callable[
    [RequestSnapshot, ActorResolution, BindingPolicy],
    str | Awaitable[str],
]


@dataclass(slots=True)
class DAGRMiddlewareConfig:
    """Configuration for the FastMCP binding."""

    runtime_instance_id: str
    boundary_id: str
    policy_pack_id: str
    policy_pack_version: str
    tool_classes: Mapping[str, ToolClass] = field(default_factory=dict)
    actor_resolver: ActorResolver | None = None
    policy_resolver: PolicyResolver | None = None
    review_object_creator: ReviewObjectCreator | Any | None = None
    pre_execution_receipt_failure: Mapping[ToolClass, ReceiptFailureMode] = field(
        default_factory=lambda: {
            "read": "fail_open",
            "write": "fail_closed",
            "destructive": "fail_closed",
        }
    )
    post_execution_receipt_failure: PostExecutionReceiptFailureMode = (
        "alert_and_return_result"
    )
    emit_read_admission_before_execution: bool = True
    emergency_spool_path: Path | None = None
    parent_receipt_ref: str | None = None
    logical_call_id_override: str | None = None
    subject_ref_override: str | None = None
    result_projection_observer: Callable[[Mapping[str, Any]], None] | None = None
    additional_attestation_limits: tuple[str, ...] = (DEFAULT_BOUNDARY_LIMIT,)


class DAGRMiddleware(Middleware):
    """FastMCP ``tools/call`` middleware that emits signed admission receipts."""

    def __init__(self, *, emitter: SignedReceiptEmitter, config: DAGRMiddlewareConfig):
        self.emitter = emitter
        self.config = config
        self.local_telemetry: list[dict[str, Any]] = []

    async def on_call_tool(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, ToolResult],
    ) -> ToolResult:
        snapshot = self._snapshot_request(context)
        actor = await self._resolve_actor(context, snapshot)
        policy = await self._resolve_policy(snapshot, actor)
        receipt_context = self._receipt_context(snapshot, actor, policy)

        if policy.disposition == "refused":
            self._emit_terminal_refusal(receipt_context, snapshot, policy)
            raise ToolError("Call refused by admission policy")

        if policy.disposition == "deferred_for_review":
            await self._defer_for_review(receipt_context, snapshot, actor, policy)

        admission_receipt_ref: str | None = None
        if self._must_emit_admission_before_execution(policy.tool_class):
            try:
                admission_receipt_ref = self._emit_admission(
                    receipt_context,
                    snapshot,
                    policy,
                    disposition="admitted",
                )
            except Exception as exc:  # noqa: BLE001 - fail policy classifies it.
                self._record_receipt_failure(
                    receipt_context,
                    snapshot,
                    attempted_receipt_kind="admission",
                    failure=exc,
                )
                if self._pre_execution_failure_mode(policy.tool_class) == "fail_closed":
                    raise ToolError(
                        "Admission receipt could not be durably accepted"
                    ) from None

        try:
            result = await call_next(context)
        except asyncio.CancelledError:
            if admission_receipt_ref is not None:
                self._emit_outcome_best_effort(
                    receipt_context,
                    snapshot,
                    admission_receipt_ref,
                    outcome="indeterminate",
                    binding_owned_fields={
                        "request_cancelled": True,
                        "execution_state_unknown": True,
                        "result_not_delivered": True,
                    },
                )
            raise
        except Exception as exc:
            if admission_receipt_ref is not None:
                self._emit_outcome_best_effort(
                    receipt_context,
                    snapshot,
                    admission_receipt_ref,
                    outcome="exception",
                    exception_class=type(exc).__name__,
                )
            raise

        if admission_receipt_ref is None:
            return result

        if isinstance(result, CreateTaskResult):
            self._emit_post_execution_outcome(
                receipt_context,
                snapshot,
                admission_receipt_ref,
                result,
                outcome="task_submitted",
            )
            return result

        try:
            projection = project_fastmcp_tool_result(result)
            if self.config.result_projection_observer is not None:
                self.config.result_projection_observer(copy.deepcopy(projection))
            result_digest = fastmcp_tool_result_digest(
                content=projection["content"],
                structured_content=projection["structuredContent"],
                meta=projection["_meta"],
                is_error=projection["isError"],
            )
            outcome = "error_returned" if projection["isError"] else "result_returned"
        except Exception as exc:  # noqa: BLE001 - post-execution failure policy applies.
            self._record_receipt_failure(
                receipt_context,
                snapshot,
                attempted_receipt_kind="outcome",
                attempted_outcome="result_returned",
                admission_receipt_ref=admission_receipt_ref,
                failure=exc,
            )
            return result

        self._emit_post_execution_outcome(
            receipt_context,
            snapshot,
            admission_receipt_ref,
            result,
            outcome=outcome,
            result_digest=result_digest,
        )
        return result

    def _snapshot_request(self, context: MiddlewareContext[Any]) -> RequestSnapshot:
        message = context.message
        tool_name = str(getattr(message, "name", ""))
        arguments = getattr(message, "arguments", None)
        if arguments is None:
            arguments = {}
        meta = _get_meta(message)

        request_id = _context_attr(context.fastmcp_context, "request_id")
        session_id = _context_attr(context.fastmcp_context, "session_id")
        request_ref = _scoped_hash_ref("request", request_id) if request_id else None
        session_ref = _scoped_hash_ref("session", session_id) if session_id else None
        logical_call_id = (
            self.config.logical_call_id_override
            or request_ref
            or f"call:{uuid.uuid4()}"
        )
        subject_ref = (
            self.config.subject_ref_override
            or session_ref
            or request_ref
            or f"tool-call:{logical_call_id}"
        )

        return RequestSnapshot(
            tool_name=tool_name,
            arguments_digest=sha256_digest(arguments),
            logical_call_id=logical_call_id,
            subject_ref=subject_ref,
            session_ref=session_ref,
            request_ref=request_ref,
            meta_digest=sha256_digest(meta) if meta is not None else None,
        )

    async def _resolve_actor(
        self,
        context: MiddlewareContext[Any],
        snapshot: RequestSnapshot,
    ) -> ActorResolution:
        if self.config.actor_resolver is not None:
            resolved = self.config.actor_resolver(context, snapshot)
            if inspect.isawaitable(resolved):
                resolved = await resolved
            return resolved
        return default_actor_resolution()

    async def _resolve_policy(
        self,
        snapshot: RequestSnapshot,
        actor: ActorResolution,
    ) -> BindingPolicy:
        if self.config.policy_resolver is not None:
            resolved = self.config.policy_resolver(snapshot, actor)
            if inspect.isawaitable(resolved):
                resolved = await resolved
            return resolved
        return BindingPolicy(
            disposition="admitted",
            tool_class=self.config.tool_classes.get(snapshot.tool_name, "read"),
        )

    def _receipt_context(
        self,
        snapshot: RequestSnapshot,
        actor: ActorResolution,
        policy: BindingPolicy,
    ) -> ReceiptContext:
        return ReceiptContext(
            runtime_instance_id=self.config.runtime_instance_id,
            boundary_id=self.config.boundary_id,
            policy_pack_id=self.config.policy_pack_id,
            policy_pack_version=self.config.policy_pack_version,
            subject_ref=snapshot.subject_ref,
            logical_call_id=snapshot.logical_call_id,
            actor_ref=actor.actor_ref,
            tenant_id=actor.tenant_id,
            workspace_id=actor.workspace_id,
            binding_version=BINDING_VERSION,
            parent_receipt_ref=(
                policy.parent_receipt_ref
                if policy.parent_receipt_ref is not None
                else self.config.parent_receipt_ref
            ),
        )

    def _emit_terminal_refusal(
        self,
        receipt_context: ReceiptContext,
        snapshot: RequestSnapshot,
        policy: BindingPolicy,
    ) -> None:
        try:
            self._emit_admission(
                receipt_context,
                snapshot,
                policy,
                disposition="refused",
                reason_code=policy.reason_code or "policy_refused",
            )
        except Exception as exc:  # noqa: BLE001 - do not leak signer/sink failures.
            self._record_receipt_failure(
                receipt_context,
                snapshot,
                attempted_receipt_kind="admission",
                failure=exc,
            )

    async def _defer_for_review(
        self,
        receipt_context: ReceiptContext,
        snapshot: RequestSnapshot,
        actor: ActorResolution,
        policy: BindingPolicy,
    ) -> None:
        try:
            review_object_ref = await self._create_review_object(
                snapshot,
                actor,
                policy,
            )
        except Exception as exc:  # noqa: BLE001 - review creation failure is terminal.
            self._record_review_failure(receipt_context, snapshot, exc)
            try:
                self._emit_admission(
                    receipt_context,
                    snapshot,
                    policy,
                    disposition="refused",
                    reason_code="review_object_creation_failed",
                )
            except Exception as receipt_exc:  # noqa: BLE001
                self._record_receipt_failure(
                    receipt_context,
                    snapshot,
                    attempted_receipt_kind="admission",
                    failure=receipt_exc,
                )
            raise ToolError("Call refused by admission policy") from None

        try:
            self._emit_admission(
                receipt_context,
                snapshot,
                policy,
                disposition="deferred_for_review",
                review_object_ref=review_object_ref,
                retry_contract="retry_after_approval",
            )
        except Exception as exc:  # noqa: BLE001
            self._record_receipt_failure(
                receipt_context,
                snapshot,
                attempted_receipt_kind="admission",
                failure=exc,
            )
            raise ToolError(
                "Review admission receipt could not be durably accepted"
            ) from None

        raise ToolError(f"Call deferred for review: {review_object_ref}")

    async def _create_review_object(
        self,
        snapshot: RequestSnapshot,
        actor: ActorResolution,
        policy: BindingPolicy,
    ) -> str:
        creator = self.config.review_object_creator
        if creator is None:
            raise RuntimeError("review object creator is not configured")

        if callable(creator):
            ref = creator(snapshot, actor, policy)
        elif hasattr(creator, "create_review_object"):
            ref = creator.create_review_object(
                ReviewObject(
                    review_object_type="mcp_tool_call",
                    governance_state="pending",
                    context_payload={
                        "tool_name": snapshot.tool_name,
                        "argument_digest": snapshot.arguments_digest,
                        "actor_ref": actor.actor_ref,
                        "logical_call_id": snapshot.logical_call_id,
                    },
                    allowed_actions=["approve", "reject", "defer"],
                    created_at=now_utc_iso(),
                    origin_event_id=snapshot.request_ref,
                )
            )
        elif hasattr(creator, "create"):
            ref = creator.create(
                {
                    "review_object_type": "mcp_tool_call",
                    "governance_state": "pending",
                    "tool_name": snapshot.tool_name,
                    "argument_digest": snapshot.arguments_digest,
                    "actor_ref": actor.actor_ref,
                    "logical_call_id": snapshot.logical_call_id,
                }
            )
        else:
            raise TypeError("review object creator is not callable")

        if inspect.isawaitable(ref):
            ref = await ref
        if not isinstance(ref, str) or not ref:
            raise RuntimeError("review object creator returned an invalid ref")
        return ref

    def _must_emit_admission_before_execution(self, tool_class: ToolClass) -> bool:
        if tool_class in {"write", "destructive"}:
            return True
        return self.config.emit_read_admission_before_execution

    def _pre_execution_failure_mode(self, tool_class: ToolClass) -> ReceiptFailureMode:
        return self.config.pre_execution_receipt_failure.get(tool_class, "fail_closed")

    def _emit_admission(
        self,
        receipt_context: ReceiptContext,
        snapshot: RequestSnapshot,
        policy: BindingPolicy,
        *,
        disposition: Disposition,
        review_object_ref: str | None = None,
        retry_contract: str | None = None,
        reason_code: str | None = None,
    ) -> str:
        return self.emitter.emit_admission(
            context=receipt_context,
            requested_tool_name=snapshot.tool_name,
            argument_digest=snapshot.arguments_digest,
            disposition=disposition,
            review_object_ref=review_object_ref,
            retry_contract=retry_contract,
            reason_code=reason_code,
            additional_attestation_limits=self._attestation_limits(policy),
        )

    def _emit_post_execution_outcome(
        self,
        receipt_context: ReceiptContext,
        snapshot: RequestSnapshot,
        admission_receipt_ref: str,
        result: Any,
        *,
        outcome: str,
        result_digest: str | None = None,
    ) -> None:
        try:
            self.emitter.emit_outcome(
                context=receipt_context,
                admission_receipt_ref=admission_receipt_ref,
                outcome=outcome,
                result_digest=result_digest,
                additional_attestation_limits=self._attestation_limits(None),
            )
        except Exception as exc:  # noqa: BLE001 - post-execution policy returns result.
            self._record_receipt_failure(
                receipt_context,
                snapshot,
                attempted_receipt_kind="outcome",
                attempted_outcome=outcome,
                admission_receipt_ref=admission_receipt_ref,
                failure=exc,
            )
            if self.config.post_execution_receipt_failure != "alert_and_return_result":
                self.local_telemetry.append(
                    {
                        "event_type": "unsupported_post_execution_failure_mode",
                        "mode": self.config.post_execution_receipt_failure,
                        "result_class": type(result).__name__,
                    }
                )

    def _emit_outcome_best_effort(
        self,
        receipt_context: ReceiptContext,
        snapshot: RequestSnapshot,
        admission_receipt_ref: str,
        *,
        outcome: str,
        result_digest: str | None = None,
        exception_class: str | None = None,
        binding_owned_fields: Mapping[str, bool] | None = None,
    ) -> None:
        try:
            self.emitter.emit_outcome(
                context=receipt_context,
                admission_receipt_ref=admission_receipt_ref,
                outcome=outcome,
                result_digest=result_digest,
                exception_class=exception_class,
                additional_attestation_limits=self._attestation_limits(None),
                binding_owned_fields=binding_owned_fields,
            )
        except Exception as exc:  # noqa: BLE001
            self._record_receipt_failure(
                receipt_context,
                snapshot,
                attempted_receipt_kind="outcome",
                attempted_outcome=outcome,
                admission_receipt_ref=admission_receipt_ref,
                failure=exc,
            )

    def _attestation_limits(self, policy: BindingPolicy | None) -> tuple[str, ...]:
        limits = list(self.config.additional_attestation_limits)
        if policy is not None:
            limits.extend(policy.additional_attestation_limits)
        return tuple(dict.fromkeys(limits))

    def _record_review_failure(
        self,
        receipt_context: ReceiptContext,
        snapshot: RequestSnapshot,
        failure: BaseException,
    ) -> None:
        self.local_telemetry.append(
            {
                "event_type": "review_object_creation_failed",
                "occurred_at": now_utc_iso(),
                "runtime_instance_id": receipt_context.runtime_instance_id,
                "boundary_id": receipt_context.boundary_id,
                "logical_call_id": snapshot.logical_call_id,
                "requested_tool_name": snapshot.tool_name,
                "failure_class": type(failure).__name__,
            }
        )

    def _record_receipt_failure(
        self,
        receipt_context: ReceiptContext,
        snapshot: RequestSnapshot,
        *,
        attempted_receipt_kind: str,
        failure: BaseException,
        attempted_outcome: str | None = None,
        admission_receipt_ref: str | None = None,
    ) -> None:
        event = {
            "event_type": "receipt_gap",
            "occurred_at": now_utc_iso(),
            "runtime_instance_id": receipt_context.runtime_instance_id,
            "boundary_id": receipt_context.boundary_id,
            "logical_call_id": snapshot.logical_call_id,
            "requested_tool_name": snapshot.tool_name,
            "attempted_receipt_kind": attempted_receipt_kind,
            "attempted_outcome": attempted_outcome,
            "admission_receipt_ref": admission_receipt_ref,
            "failure_class": _classified_failure(failure),
        }
        self.local_telemetry.append(event)
        self._append_emergency_spool(event)

    def _append_emergency_spool(self, event: Mapping[str, Any]) -> None:
        if self.config.emergency_spool_path is None:
            return
        try:
            path = Path(self.config.emergency_spool_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                event,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8") + b"\n"
            fd, tmp_name = tempfile.mkstemp(
                prefix=".receipt-gap-",
                suffix=".tmp",
                dir=path.parent,
            )
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                with path.open("ab") as target:
                    target.write(payload)
                    target.flush()
                    os.fsync(target.fileno())
                os.unlink(tmp_name)
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        except Exception as exc:  # noqa: BLE001 - local telemetry only.
            self.local_telemetry.append(
                {
                    "event_type": "receipt_gap_spool_failed",
                    "occurred_at": now_utc_iso(),
                    "failure_class": type(exc).__name__,
                }
            )


def default_actor_resolution() -> ActorResolution:
    """Resolve FastMCP authenticated contexts without retaining raw tokens."""

    try:
        token = get_access_token()
    except Exception:  # noqa: BLE001 - direct/stdio calls have no token context.
        token = None
    if token is None:
        return ActorResolution()

    claims = getattr(token, "claims", None) or {}
    if not isinstance(claims, Mapping):
        claims = {}
    if claims:
        actor_ref = _scoped_hash_ref("actor", claims)
    else:
        token_fallback = {
            "client_id": getattr(token, "client_id", None),
            "scopes": sorted(str(scope) for scope in getattr(token, "scopes", []) or []),
            "resource": getattr(token, "resource", None),
        }
        actor_ref = _scoped_hash_ref("actor", token_fallback)
    tenant_id = _claim_string(claims, ("tenant_id", "tid", "tenant"))
    workspace_id = _claim_string(claims, ("workspace_id", "wid", "workspace"))
    return ActorResolution(
        actor_ref=actor_ref,
        tenant_id=_scoped_hash_ref("tenant", tenant_id) if tenant_id else None,
        workspace_id=_scoped_hash_ref("workspace", workspace_id)
        if workspace_id
        else None,
    )


def project_fastmcp_tool_result(result: Any) -> dict[str, Any]:
    """Return the exact four-member ``fastmcp.tool_result.v1`` projection."""

    content = _jsonable(getattr(result, "content", []))
    structured_content = _jsonable(
        getattr(result, "structured_content", getattr(result, "structuredContent", None))
    )
    meta = _jsonable(getattr(result, "meta", getattr(result, "_meta", None)))
    is_error = bool(getattr(result, "is_error", getattr(result, "isError", False)))
    projection = {
        "content": content,
        "structuredContent": structured_content,
        "_meta": meta,
        "isError": is_error,
    }
    rfc8785.dumps(projection)
    return projection


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_jsonable(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json", by_alias=True, exclude_none=True)
    if hasattr(value, "dict") and callable(value.dict):
        return value.dict(by_alias=True, exclude_none=True)
    try:
        dumped = json.loads(json.dumps(value))
    except TypeError:
        dumped = str(value)
    return dumped


def _classified_failure(failure: BaseException) -> str:
    if isinstance(failure, ReceiptWriteError):
        return "receipt_sink_failure"
    if isinstance(failure, ReceiptContentError):
        return "receipt_signing_or_content_failure"
    if isinstance(failure, OSError):
        return "receipt_spool_io_failure"
    return type(failure).__name__


def _context_attr(context: Any, name: str) -> str | None:
    if context is None:
        return None
    try:
        value = getattr(context, name)
    except Exception:  # noqa: BLE001
        return None
    if value is None:
        return None
    return str(value)


def _get_meta(message: Any) -> Any | None:
    for name in ("meta", "_meta"):
        try:
            value = getattr(message, name)
        except Exception:  # noqa: BLE001
            continue
        if value is not None:
            return value
    return None


def _scoped_hash_ref(prefix: str, value: Any) -> str:
    digest = sha256_digest(value).removeprefix("sha256:")
    return f"{prefix}:sha256:{digest}"


def _claim_string(claims: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = claims.get(key)
        if isinstance(value, str) and value:
            return value
    return None


__all__ = [
    "ActorResolution",
    "BINDING_VERSION",
    "CREATE_TASK_RESULT_IMPORT_PATH",
    "DAGRMiddleware",
    "DAGRMiddlewareConfig",
    "BindingPolicy",
    "RequestSnapshot",
    "project_fastmcp_tool_result",
]
