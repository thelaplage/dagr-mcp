"""Iron TransformService boundary for DAGR MCP `mcp.tools/call` governance.

This module is intentionally narrow:

* it recognizes only explicitly scoped MCP JSON-RPC ``tools/call`` requests;
* it never executes a downstream tool after returning ``CONTINUE``;
* it reuses the existing DAGR receipt machinery only for the pre-execution
  admission/refusal/defer boundary; and
* it treats response handling as observation only.

The upstream producer contract is pinned at:

* repository: https://github.com/paradigmxyz/iron-proxy
* commit: 564f7bac971dd3d3f077c23a7aaa7484671ed39f
* proto path: proto/transform/v1/transform.proto
* grpc shim path: internal/transform/grpc/grpc.go

The vendored proto fixture and manifest under ``tests/vendor`` capture those
facts for deterministic conformance checks.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping
from urllib.parse import urlsplit

from dagr_mcp.sdk_spine import stable_payload_hash
from dagr_mcp.srs_bridge import BridgeConfig, HarnessSRSBridge
from dagr_mcp.srs_receipts import SignedReceiptEmitter, sha256_digest
from dagr_mcp_service.contract import GovernedCallResponse, GovernedDecision, ReceiptHandle


TransformAction = Literal["CONTINUE", "REJECT"]

_JSONRPC_VERSION = "2.0"
_MCP_METHOD = "tools/call"
_DEFAULT_JSONRPC_ERROR_CODE = -32001
_DEFAULT_JSONRPC_ERROR_MESSAGE = "blocked by dagr governance"
_MALFORMED_JSONRPC_ERROR_MESSAGE = "malformed mcp tools/call"
_OUT_OF_SCOPE = "out_of_scope"
_IN_SCOPE = "in_scope"
_OBSERVED_ONLY = "observed_only"
_OPERATION_DIGEST_ANNOTATION_KEYS = ("operation_digest", "dagr.operation_digest")


@dataclass(frozen=True, slots=True)
class HeaderValues:
    values: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, HeaderValues] = field(default_factory=dict)
    body: bytes = b""
    host: str = ""
    remote_addr: str = ""


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status_code: int
    headers: Mapping[str, HeaderValues] = field(default_factory=dict)
    body: bytes = b""


@dataclass(frozen=True, slots=True)
class TunnelRequestTransform:
    name: str
    annotations: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TunnelInfo:
    target: str
    request_transforms: tuple[TunnelRequestTransform, ...] = ()


@dataclass(frozen=True, slots=True)
class TransformContext:
    sni: str = ""
    client_cert_der: bytes = b""
    tunnel: TunnelInfo | None = None


@dataclass(frozen=True, slots=True)
class TransformRequestRequest:
    context: TransformContext
    request: HttpRequest


@dataclass(frozen=True, slots=True)
class TransformRequestResponse:
    action: TransformAction
    response: HttpResponse | None = None
    modified_request: HttpRequest | None = None
    annotations: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TransformResponseRequest:
    context: TransformContext
    request: HttpRequest
    response: HttpResponse


@dataclass(frozen=True, slots=True)
class TransformResponseResponse:
    action: TransformAction
    modified_response: HttpResponse | None = None
    annotations: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IronMCPServerScope:
    """Operator-authored scope for one declared MCP server."""

    host_patterns: tuple[str, ...]
    path_patterns: tuple[str, ...] = ("/mcp", "/mcp/*")
    allowed_tools: frozenset[str] = frozenset()
    server_name: str | None = None

    def __post_init__(self) -> None:
        if not self.host_patterns:
            raise ValueError("host_patterns must not be empty")
        if not self.allowed_tools:
            raise ValueError("allowed_tools must not be empty")


@dataclass(frozen=True, slots=True)
class IronAdmissionDecision:
    disposition: Literal["admitted", "refused", "deferred"]
    reason_code: str | None = None
    review_object_ref: str | None = None

    def __post_init__(self) -> None:
        if self.disposition not in ("admitted", "refused", "deferred"):
            raise ValueError(
                "disposition must be one of admitted/refused/deferred"
            )
        if self.disposition == "admitted" and self.reason_code is not None:
            raise ValueError("admitted decisions must not carry a reason_code")
        if self.disposition != "admitted" and self.reason_code is None:
            raise ValueError("refused/deferred decisions require a reason_code")


@dataclass(frozen=True, slots=True)
class MCPCallFacts:
    request_ref: str
    jsonrpc_id: str | None
    tool_name: str
    arguments: Mapping[str, Any]
    host: str
    path: str
    request_digest: str
    operation_digest: str


IronAdmissionResolver = Callable[[MCPCallFacts], IronAdmissionDecision]


@dataclass(frozen=True, slots=True)
class IronTransformBoundaryConfig:
    """Operator/deployment configuration for the adapter boundary."""

    scopes: tuple[IronMCPServerScope, ...]
    runtime_instance_id: str
    boundary_id: str
    policy_pack_id: str
    policy_pack_version: str
    source_repo: str = "https://github.com/paradigmxyz/iron-proxy"
    source_commit: str = "564f7bac971dd3d3f077c23a7aaa7484671ed39f"
    source_proto_path: str = "proto/transform/v1/transform.proto"
    source_proto_sha256: str = "7a47034c89081111b43b742ff399192489fb22173b36336e184a924b89aa0a86"
    source_grpc_path: str = "internal/transform/grpc/grpc.go"
    source_grpc_sha256: str = "afe63faaf8bace57f098153369208f12b0c816accae4f4bbc7ff0eab5434034e"
    governed_scope_ref: str = "mcp.tools.call.v0.1"
    actor_ref: str = "actor:iron-proxy"
    tenant_id: str | None = None
    binding_version: str = "direct-harness.v0.1"
    admission_resolver: IronAdmissionResolver | None = None
    receipt_bridge: HarnessSRSBridge | None = None
    admission_reason_message: str = _DEFAULT_JSONRPC_ERROR_MESSAGE
    malformed_reason_message: str = _MALFORMED_JSONRPC_ERROR_MESSAGE


def validate_iron_contract_manifest(manifest: Mapping[str, Any]) -> None:
    """Fail closed when the pinned upstream Iron contract manifest drifts."""

    if not isinstance(manifest, Mapping):
        raise TypeError(f"manifest must be a mapping, got {type(manifest).__name__}")

    required = {
        "upstream_repo": "https://github.com/paradigmxyz/iron-proxy",
        "upstream_commit": "564f7bac971dd3d3f077c23a7aaa7484671ed39f",
        "source_proto_path": "proto/transform/v1/transform.proto",
        "source_proto_sha256": "7a47034c89081111b43b742ff399192489fb22173b36336e184a924b89aa0a86",
        "source_grpc_path": "internal/transform/grpc/grpc.go",
        "source_grpc_sha256": "afe63faaf8bace57f098153369208f12b0c816accae4f4bbc7ff0eab5434034e",
        "license": "Apache-2.0",
    }
    for key, expected in required.items():
        value = manifest.get(key)
        if value != expected:
            raise ValueError(f"{key} must be {expected!r}, got {value!r}")

    fixture = manifest.get("fixture_path")
    if fixture is not None and not isinstance(fixture, str):
        raise ValueError("fixture_path must be a string when provided")


@dataclass(frozen=True, slots=True)
class _ParsedCall:
    request_ref: str
    jsonrpc_id: str | None
    tool_name: str
    arguments: Mapping[str, Any]
    host: str
    path: str
    request_digest: str
    operation_digest: str


def _header_lookup(headers: Mapping[str, HeaderValues], name: str) -> str | None:
    for key, values in headers.items():
        if key.lower() == name.lower():
            if values.values:
                return values.values[0]
            return ""
    return None


def _request_host(request: HttpRequest) -> str:
    if request.host:
        parsed = urlsplit(f"//{request.host}")
        if parsed.hostname:
            return parsed.hostname
    parsed = urlsplit(request.url)
    return parsed.hostname or request.host or ""


def _request_path(request: HttpRequest) -> str:
    parsed = urlsplit(request.url)
    return parsed.path or "/"


def _matches_scope(request: HttpRequest, scope: IronMCPServerScope) -> bool:
    host = _request_host(request)
    path = _request_path(request)
    return any(fnmatch.fnmatch(host, pattern) for pattern in scope.host_patterns) and any(
        fnmatch.fnmatch(path, pattern) for pattern in scope.path_patterns
    )


def _match_scope(config: IronTransformBoundaryConfig, request: HttpRequest) -> IronMCPServerScope | None:
    for scope in config.scopes:
        if _matches_scope(request, scope):
            return scope
    return None


def _content_type(request: HttpRequest) -> str:
    return _header_lookup(request.headers, "content-type") or ""


def _is_json_request(request: HttpRequest) -> bool:
    return "application/json" in _content_type(request).lower()


def _raw_body_digest(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _jsonrpc_id_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (bool, int, float)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return sha256_digest(value)


def _parse_call(request: HttpRequest, scope: IronMCPServerScope, body: bytes) -> MCPCallFacts | None:
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    if payload.get("jsonrpc") != _JSONRPC_VERSION or payload.get("method") != _MCP_METHOD:
        return None

    params = payload.get("params")
    if not isinstance(params, dict):
        return None
    tool_name = params.get("name")
    arguments = params.get("arguments")
    if not isinstance(tool_name, str) or not tool_name.strip():
        return None
    if arguments is None or not isinstance(arguments, Mapping):
        return None

    host = _request_host(request)
    path = _request_path(request)
    request_digest = _raw_body_digest(body)
    operation_digest = stable_payload_hash(
        {
            "scope": scope.server_name or scope.host_patterns[0],
            "host": host,
            "path": path,
            "method": _MCP_METHOD,
            "tool_name": tool_name,
            "arguments": dict(arguments),
        }
    )

    request_ref = f"iron:{operation_digest}"
    return MCPCallFacts(
        request_ref=request_ref,
        jsonrpc_id=_jsonrpc_id_text(payload.get("id")),
        tool_name=tool_name,
        arguments=dict(arguments),
        host=host,
        path=path,
        request_digest=request_digest,
        operation_digest=operation_digest,
    )


def _incoming_operation_digests(context: TransformContext) -> set[str]:
    if context.tunnel is None:
        return set()
    digests: set[str] = set()
    for transform in context.tunnel.request_transforms:
        for key, value in transform.annotations.items():
            if key in _OPERATION_DIGEST_ANNOTATION_KEYS and isinstance(value, str):
                digests.add(value)
    return digests


def _make_jsonrpc_error_response(
    request_id: str | None,
    *,
    message: str,
    code: int = _DEFAULT_JSONRPC_ERROR_CODE,
) -> HttpResponse:
    payload = {
        "jsonrpc": _JSONRPC_VERSION,
        "id": request_id,
        "error": {"code": code, "message": message},
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return HttpResponse(
        status_code=200,
        headers={"Content-Type": HeaderValues(("application/json",))},
        body=body,
    )


def _default_decision(_facts: MCPCallFacts) -> IronAdmissionDecision:
    return IronAdmissionDecision(disposition="admitted")


def _governed_decision(
    config: IronTransformBoundaryConfig,
    facts: MCPCallFacts,
    scope: IronMCPServerScope,
) -> IronAdmissionDecision:
    if facts.tool_name not in scope.allowed_tools:
        return IronAdmissionDecision(
            disposition="refused",
            reason_code="unknown_tool_fail_closed",
        )
    if config.admission_resolver is None:
        return _default_decision(facts)
    decision = config.admission_resolver(facts)
    if not isinstance(decision, IronAdmissionDecision):
        raise TypeError(
            "admission_resolver must return an IronAdmissionDecision"
        )
    return decision


def _receipt_bridge(config: IronTransformBoundaryConfig) -> HarnessSRSBridge | None:
    return config.receipt_bridge


def _receipt_context(config: IronTransformBoundaryConfig, facts: MCPCallFacts) -> Any:
    return type(
        "_IronReceiptContext",
        (),
        {
            "request_ref": facts.request_ref,
            "session_ref": None,
            "actor_ref": config.actor_ref,
            "arguments_hash": facts.operation_digest,
        },
    )()


def _admission_annotations(
    *,
    config: IronTransformBoundaryConfig,
    scope: IronMCPServerScope,
    facts: MCPCallFacts,
    decision: IronAdmissionDecision,
    receipt_ref: str | None = None,
    extra_status: str | None = None,
) -> dict[str, str]:
    annotations: dict[str, str] = {
        "dagr.scope": config.governed_scope_ref,
        "dagr.scope_name": scope.server_name or scope.host_patterns[0],
        "dagr.scope_state": _IN_SCOPE,
        "dagr.request_ref": facts.request_ref,
        "dagr.jsonrpc_id": facts.jsonrpc_id or "",
        "dagr.operation_digest": facts.operation_digest,
        "dagr.request_digest": facts.request_digest,
        "dagr.source_repo": config.source_repo,
        "dagr.source_commit": config.source_commit,
        "dagr.source_proto_path": config.source_proto_path,
        "dagr.source_proto_sha256": config.source_proto_sha256,
        "dagr.source_grpc_path": config.source_grpc_path,
        "dagr.source_grpc_sha256": config.source_grpc_sha256,
        "dagr.decision": decision.disposition,
    }
    if decision.reason_code is not None:
        annotations["dagr.reason_code"] = decision.reason_code
    if decision.review_object_ref is not None:
        annotations["dagr.review_object_ref"] = decision.review_object_ref
    if receipt_ref is not None:
        annotations["dagr.receipt_ref"] = receipt_ref
    if extra_status is not None:
        annotations["dagr.status"] = extra_status
    return annotations


def _out_of_scope_annotations(config: IronTransformBoundaryConfig, request: HttpRequest) -> dict[str, str]:
    host = _request_host(request)
    path = _request_path(request)
    return {
        "dagr.scope": config.governed_scope_ref,
        "dagr.scope_state": _OUT_OF_SCOPE,
        "dagr.request_host": host,
        "dagr.request_path": path,
        "dagr.source_repo": config.source_repo,
        "dagr.source_commit": config.source_commit,
        "dagr.source_proto_path": config.source_proto_path,
        "dagr.source_proto_sha256": config.source_proto_sha256,
    }


def _observation_annotations(
    config: IronTransformBoundaryConfig, request: HttpRequest, response: HttpResponse
) -> dict[str, str]:
    host = _request_host(request)
    path = _request_path(request)
    response_digest = "sha256:" + hashlib.sha256(response.body).hexdigest()
    response_kind = "unknown"
    try:
        payload = json.loads(response.body.decode("utf-8"))
        if isinstance(payload, dict):
            if "error" in payload:
                response_kind = "jsonrpc_error"
            elif "result" in payload:
                response_kind = "jsonrpc_result"
            else:
                response_kind = "jsonrpc_object"
        elif isinstance(payload, list):
            response_kind = "jsonrpc_batch"
    except Exception:
        response_kind = "opaque"
    return {
        "dagr.scope": config.governed_scope_ref,
        "dagr.scope_state": _OBSERVED_ONLY,
        "dagr.request_host": host,
        "dagr.request_path": path,
        "dagr.observed.response_digest": response_digest,
        "dagr.observed.response_kind": response_kind,
        "dagr.source_repo": config.source_repo,
        "dagr.source_commit": config.source_commit,
        "dagr.source_proto_path": config.source_proto_path,
        "dagr.source_proto_sha256": config.source_proto_sha256,
    }


def _record_admission(
    *,
    config: IronTransformBoundaryConfig,
    facts: MCPCallFacts,
    decision: IronAdmissionDecision,
) -> ReceiptHandle | None:
    bridge = _receipt_bridge(config)
    if bridge is None:
        return None

    harness_context = _receipt_context(config, facts)
    disposition = decision.disposition
    if disposition == "admitted":
        receipt_id = bridge.emit_admission(
            harness_context=harness_context,
            tool_name=facts.tool_name,
            disposition="admitted",
            additional_attestation_limits=(),
        )
    elif disposition == "deferred":
        receipt_id = bridge.emit_admission(
            harness_context=harness_context,
            tool_name=facts.tool_name,
            disposition="deferred",
            review_object_ref=decision.review_object_ref
            or f"iron-review:{facts.operation_digest}",
            retry_contract="retry_after_approval",
            reason_code=decision.reason_code,
            additional_attestation_limits=(),
        )
    else:
        receipt_id = bridge.emit_admission(
            harness_context=harness_context,
            tool_name=facts.tool_name,
            disposition="refused",
            reason_code=decision.reason_code,
            additional_attestation_limits=(),
        )
    return ReceiptHandle(receipt_id=receipt_id, receipt_kind="admission")


def _evaluate_request(
    config: IronTransformBoundaryConfig, request: HttpRequest, context: TransformContext
) -> tuple[TransformRequestResponse, GovernedCallResponse | None]:
    scope = _match_scope(config, request)
    if scope is None:
        return (
            TransformRequestResponse(
                action="CONTINUE",
                annotations=_out_of_scope_annotations(config, request),
            ),
            None,
        )

    if not request.method.upper() == "POST" or not _is_json_request(request):
        return (
            TransformRequestResponse(
                action="REJECT",
                response=_make_jsonrpc_error_response(
                    None, message=_MALFORMED_JSONRPC_ERROR_MESSAGE
                ),
                annotations={
                    **_out_of_scope_annotations(config, request),
                    "dagr.scope_state": _IN_SCOPE,
                    "dagr.decision": "refused",
                    "dagr.reason_code": "malformed_request",
                },
            ),
            GovernedCallResponse(
                request_ref=f"iron:{_raw_body_digest(request.body)}",
                logical_call_id=f"iron:{_raw_body_digest(request.body)}",
                decision=GovernedDecision(disposition="refused"),
                receipts=(),
                diagnostic_code="malformed_request",
            ),
        )

    call = _parse_call(request, scope, request.body)
    if call is None:
        return (
            TransformRequestResponse(
                action="REJECT",
                response=_make_jsonrpc_error_response(
                    None, message=_MALFORMED_JSONRPC_ERROR_MESSAGE
                ),
                annotations={
                    **_out_of_scope_annotations(config, request),
                    "dagr.scope_state": _IN_SCOPE,
                    "dagr.decision": "refused",
                    "dagr.reason_code": "malformed_request",
                },
            ),
            GovernedCallResponse(
                request_ref=f"iron:{_raw_body_digest(request.body)}",
                logical_call_id=f"iron:{_raw_body_digest(request.body)}",
                decision=GovernedDecision(disposition="refused"),
                receipts=(),
                diagnostic_code="malformed_request",
            ),
        )

    incoming_digests = _incoming_operation_digests(context)
    if incoming_digests and call.operation_digest not in incoming_digests:
        return (
            TransformRequestResponse(
                action="REJECT",
                response=_make_jsonrpc_error_response(
                    call.jsonrpc_id, message=_MALFORMED_JSONRPC_ERROR_MESSAGE
                ),
                annotations={
                    **_admission_annotations(
                        config=config,
                        scope=scope,
                        facts=call,
                        decision=IronAdmissionDecision(
                            disposition="refused",
                            reason_code="malformed_request",
                        ),
                        extra_status="tampered_operation_digest",
                    ),
                    "dagr.tampered_operation_digest": "true",
                },
            ),
            GovernedCallResponse(
                request_ref=call.request_ref,
                logical_call_id=call.request_ref,
                decision=GovernedDecision(disposition="refused"),
                receipts=(),
                diagnostic_code="malformed_request",
            ),
        )

    decision = _governed_decision(config, call, scope)
    receipt = _record_admission(config=config, facts=call, decision=decision)
    receipt_handles = (receipt,) if receipt is not None else ()

    if decision.disposition == "admitted":
        response = TransformRequestResponse(
            action="CONTINUE",
            annotations=_admission_annotations(
                config=config,
                scope=scope,
                facts=call,
                decision=decision,
                receipt_ref=receipt.receipt_id if receipt is not None else None,
            ),
        )
        governed = GovernedCallResponse(
            request_ref=call.request_ref,
            logical_call_id=call.request_ref,
            decision=GovernedDecision(disposition="admitted"),
            receipts=receipt_handles,
        )
        return response, governed

    if decision.disposition == "deferred":
        response = TransformRequestResponse(
            action="REJECT",
            response=_make_jsonrpc_error_response(
                call.jsonrpc_id, message=config.admission_reason_message
            ),
            annotations=_admission_annotations(
                config=config,
                scope=scope,
                facts=call,
                decision=decision,
                receipt_ref=receipt.receipt_id if receipt is not None else None,
                extra_status="deferred",
            ),
        )
        governed = GovernedCallResponse(
            request_ref=call.request_ref,
            logical_call_id=call.request_ref,
            decision=GovernedDecision(disposition="deferred"),
            receipts=receipt_handles,
            review_object_ref=decision.review_object_ref
            or f"iron-review:{call.operation_digest}",
            retry_instruction="retry_after_approval",
            diagnostic_code="deferred_for_review",
        )
        return response, governed

    response = TransformRequestResponse(
        action="REJECT",
        response=_make_jsonrpc_error_response(
            call.jsonrpc_id, message=config.admission_reason_message
        ),
        annotations=_admission_annotations(
            config=config,
            scope=scope,
            facts=call,
            decision=decision,
            receipt_ref=receipt.receipt_id if receipt is not None else None,
            extra_status="refused",
        ),
    )
    governed = GovernedCallResponse(
        request_ref=call.request_ref,
        logical_call_id=call.request_ref,
        decision=GovernedDecision(disposition="refused"),
        receipts=receipt_handles,
        diagnostic_code=decision.reason_code or "policy_refused",
    )
    return response, governed


class IronTransformBoundary:
    """TransformService-compatible adapter boundary for DAGR MCP governance."""

    def __init__(self, config: IronTransformBoundaryConfig) -> None:
        self.config = config

    def TransformRequest(self, request: TransformRequestRequest) -> TransformRequestResponse:
        response, _ = _evaluate_request(self.config, request.request, request.context)
        return response

    def TransformResponse(self, request: TransformResponseRequest) -> TransformResponseResponse:
        scope = _match_scope(self.config, request.request)
        if scope is None:
            return TransformResponseResponse(
                action="CONTINUE",
                annotations=_out_of_scope_annotations(self.config, request.request),
            )
        return TransformResponseResponse(
            action="CONTINUE",
            annotations=_observation_annotations(
                self.config, request.request, request.response
            ),
        )


def build_default_admission_bridge(
    *,
    emitter: SignedReceiptEmitter,
    runtime_instance_id: str,
    boundary_id: str,
    policy_pack_id: str,
    policy_pack_version: str,
    binding_version: str = "direct-harness.v0.1",
    parent_receipt_ref: str | None = None,
) -> HarnessSRSBridge:
    """Return the receipt bridge used by the adapter in tests or embedded use."""

    return HarnessSRSBridge(
        emitter=emitter,
        config=BridgeConfig(
            runtime_instance_id=runtime_instance_id,
            boundary_id=boundary_id,
            policy_pack_id=policy_pack_id,
            policy_pack_version=policy_pack_version,
            binding_version=binding_version,
            parent_receipt_ref=parent_receipt_ref,
        ),
    )


__all__ = [
    "TransformAction",
    "HeaderValues",
    "HttpRequest",
    "HttpResponse",
    "TunnelRequestTransform",
    "TunnelInfo",
    "TransformContext",
    "TransformRequestRequest",
    "TransformRequestResponse",
    "TransformResponseRequest",
    "TransformResponseResponse",
    "IronMCPServerScope",
    "IronAdmissionDecision",
    "MCPCallFacts",
    "IronAdmissionResolver",
    "IronTransformBoundaryConfig",
    "validate_iron_contract_manifest",
    "IronTransformBoundary",
    "build_default_admission_bridge",
]
