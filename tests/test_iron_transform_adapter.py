from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from dagr_mcp.srs_receipts import RawEnvelopeFileSink, SigningIdentity, SignedReceiptEmitter
from dagr_mcp_service.iron_transform import (
    HeaderValues,
    HttpRequest,
    HttpResponse,
    IronAdmissionDecision,
    IronMCPServerScope,
    IronTransformBoundary,
    IronTransformBoundaryConfig,
    TransformContext,
    TransformRequestRequest,
    TransformResponseRequest,
    TunnelInfo,
    TunnelRequestTransform,
    build_default_admission_bridge,
    validate_iron_contract_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "tests" / "vendor" / "iron_proxy_transform_v1"


def _read_receipts(directory: Path) -> list[dict[str, object]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("urn_srs_receipt_*.json"))
    ]


def _build_boundary(tmp_path: Path, *, resolver=None) -> tuple[IronTransformBoundary, Path]:
    sink_dir = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(sink_dir)
    identity = SigningIdentity.generate(
        issuer_id="issuer:test:iron", key_id="issuer.test.iron/key/1"
    )
    emitter = SignedReceiptEmitter(identity=identity, sink=sink)
    bridge = build_default_admission_bridge(
        emitter=emitter,
        runtime_instance_id="runtime:test:iron",
        boundary_id="boundary:test:iron",
        policy_pack_id="policy:test:iron",
        policy_pack_version="2026.08.11",
    )
    scope = IronMCPServerScope(
        host_patterns=("github.mcp.local",),
        path_patterns=("/mcp", "/mcp/*"),
        allowed_tools=frozenset({"search_repositories"}),
        server_name="github",
    )
    config = IronTransformBoundaryConfig(
        scopes=(scope,),
        runtime_instance_id="runtime:test:iron",
        boundary_id="boundary:test:iron",
        policy_pack_id="policy:test:iron",
        policy_pack_version="2026.08.11",
        admission_resolver=resolver,
        receipt_bridge=bridge,
    )
    return IronTransformBoundary(config), sink_dir


def _tools_call_request(
    *,
    tool_name: str = "search_repositories",
    arguments: dict[str, object] | None = None,
    body_id: object = 1,
    method: str = "POST",
    content_type: str = "application/json; charset=utf-8",
    host: str = "github.mcp.local",
    path: str = "/mcp",
) -> TransformRequestRequest:
    payload = {
        "jsonrpc": "2.0",
        "id": body_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments or {"q": "dagr"}},
    }
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    request = HttpRequest(
        method=method,
        url=f"https://{host}{path}",
        headers={"Content-Type": HeaderValues(values=(content_type,))},
        body=body,
        host=host,
        remote_addr="192.0.2.10:443",
    )
    return TransformRequestRequest(context=TransformContext(), request=request)


def test_admitted_in_scope_tools_call_returns_continue_and_emits_one_receipt(tmp_path: Path) -> None:
    boundary, sink_dir = _build_boundary(tmp_path)
    response = boundary.TransformRequest(_tools_call_request())

    assert response.action == "CONTINUE"
    assert response.modified_request is None
    assert response.response is None
    assert response.annotations["dagr.decision"] == "admitted"
    assert response.annotations["dagr.scope_state"] == "in_scope"
    assert "dagr.receipt_ref" in response.annotations

    receipts = _read_receipts(sink_dir)
    assert len(receipts) == 1
    assert receipts[0]["receipt_kind"] == "admission"
    assert receipts[0]["disposition"] == "admitted"


def test_refused_in_scope_tools_call_returns_reject_and_zero_downstream(tmp_path: Path) -> None:
    boundary, sink_dir = _build_boundary(
        tmp_path,
        resolver=lambda _facts: IronAdmissionDecision(
            disposition="refused", reason_code="policy_refused"
        ),
    )
    response = boundary.TransformRequest(_tools_call_request(arguments={"q": "deny"}))

    assert response.action == "REJECT"
    assert response.response is not None
    body = json.loads(response.response.body.decode("utf-8"))
    assert body["error"]["message"] == "blocked by dagr governance"
    assert response.annotations["dagr.decision"] == "refused"
    assert response.annotations["dagr.reason_code"] == "policy_refused"

    receipts = _read_receipts(sink_dir)
    assert len(receipts) == 1
    assert receipts[0]["disposition"] == "refused"
    assert receipts[0]["reason_code"] == "policy_refused"


def test_deferred_in_scope_tools_call_returns_reject_and_zero_downstream(tmp_path: Path) -> None:
    boundary, sink_dir = _build_boundary(
        tmp_path,
        resolver=lambda _facts: IronAdmissionDecision(
            disposition="deferred",
            reason_code="policy_refused",
            review_object_ref="iron-review:abc123",
        ),
    )
    response = boundary.TransformRequest(_tools_call_request(arguments={"q": "defer"}))

    assert response.action == "REJECT"
    assert response.annotations["dagr.decision"] == "deferred"
    assert response.annotations["dagr.review_object_ref"] == "iron-review:abc123"
    assert response.annotations["dagr.status"] == "deferred"

    receipts = _read_receipts(sink_dir)
    assert len(receipts) == 1
    assert receipts[0]["disposition"] == "deferred"
    assert receipts[0]["retry_contract"] == "retry_after_approval"


def test_malformed_in_scope_tools_call_fails_closed_before_forwarding(tmp_path: Path) -> None:
    boundary, sink_dir = _build_boundary(tmp_path)
    request = _tools_call_request()
    malformed = TransformRequestRequest(
        context=TransformContext(),
        request=HttpRequest(
            method="POST",
            url=request.request.url,
            headers=request.request.headers,
            body=b"{not-json",
            host=request.request.host,
            remote_addr=request.request.remote_addr,
        ),
    )

    response = boundary.TransformRequest(malformed)

    assert response.action == "REJECT"
    assert response.annotations["dagr.reason_code"] == "malformed_request"
    assert _read_receipts(sink_dir) == []


def test_unknown_tool_fails_closed_according_to_existing_dagr_semantics(tmp_path: Path) -> None:
    boundary, sink_dir = _build_boundary(tmp_path)
    response = boundary.TransformRequest(
        _tools_call_request(tool_name="delete_repo", arguments={"repo": "x"})
    )

    assert response.action == "REJECT"
    assert response.annotations["dagr.reason_code"] == "unknown_tool_fail_closed"

    receipts = _read_receipts(sink_dir)
    assert len(receipts) == 1
    assert receipts[0]["reason_code"] == "unknown_tool_fail_closed"


def test_out_of_scope_ordinary_http_is_not_evaluated_and_emits_no_receipt(
    tmp_path: Path,
) -> None:
    boundary, sink_dir = _build_boundary(tmp_path)
    request = TransformRequestRequest(
        context=TransformContext(),
        request=HttpRequest(
            method="GET",
            url="https://example.com/status",
            headers={"Content-Type": HeaderValues(values=("text/plain",))},
            body=b"plain text",
            host="example.com",
            remote_addr="198.51.100.5:443",
        ),
    )

    response = boundary.TransformRequest(request)

    assert response.action == "CONTINUE"
    assert response.annotations["dagr.scope_state"] == "out_of_scope"
    assert "dagr.receipt_ref" not in response.annotations
    assert _read_receipts(sink_dir) == []


def test_tampered_operation_digest_fails_closed(tmp_path: Path) -> None:
    boundary, sink_dir = _build_boundary(tmp_path)
    request = _tools_call_request()
    context = TransformContext(
        tunnel=TunnelInfo(
            target="github.mcp.local",
            request_transforms=(
                TunnelRequestTransform(
                    name="prior-transform",
                    annotations={"dagr.operation_digest": "sha256:bad"},
                ),
            ),
        )
    )
    tampered = TransformRequestRequest(context=context, request=request.request)

    response = boundary.TransformRequest(tampered)

    assert response.action == "REJECT"
    assert response.annotations["dagr.tampered_operation_digest"] == "true"
    assert response.annotations["dagr.reason_code"] == "malformed_request"
    assert _read_receipts(sink_dir) == []


def test_annotations_and_receipts_do_not_include_raw_secrets_or_payload(tmp_path: Path) -> None:
    secret = "sk-test-super-secret"
    boundary, sink_dir = _build_boundary(tmp_path)
    response = boundary.TransformRequest(
        _tools_call_request(arguments={"q": "dagr", "secret": secret})
    )

    annotation_dump = json.dumps(response.annotations, sort_keys=True)
    assert secret not in annotation_dump
    assert '"secret"' not in annotation_dump

    receipts = _read_receipts(sink_dir)
    assert receipts
    receipt_dump = json.dumps(receipts[0], sort_keys=True)
    assert secret not in receipt_dump
    assert '"secret"' not in receipt_dump


def test_transform_response_is_observation_only(tmp_path: Path) -> None:
    boundary, sink_dir = _build_boundary(tmp_path)
    request = _tools_call_request()
    response = boundary.TransformResponse(
        TransformResponseRequest(
            context=TransformContext(),
            request=request.request,
            response=HttpResponse(
                status_code=200,
                headers={"Content-Type": HeaderValues(values=("application/json",))},
                body=b'{"jsonrpc":"2.0","id":1,"result":{"ok":true}}',
            ),
        )
    )

    assert response.action == "CONTINUE"
    assert response.modified_response is None
    assert response.annotations["dagr.scope_state"] == "observed_only"
    assert "dagr.observed.response_digest" in response.annotations
    assert _read_receipts(sink_dir) == []


def test_upstream_proto_fixture_matches_pinned_source_manifest() -> None:
    manifest = json.loads((VENDOR / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    proto_bytes = (VENDOR / "transform.proto").read_bytes()
    proto_sha256 = hashlib.sha256(proto_bytes).hexdigest()

    assert proto_sha256 == manifest["source_proto_sha256"]
    assert (VENDOR / "transform.proto").read_text(encoding="utf-8").startswith(
        "syntax = \"proto3\";"
    )
    validate_iron_contract_manifest(manifest)


def test_stale_or_wrong_upstream_contract_pin_fails_closed() -> None:
    manifest = json.loads((VENDOR / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    bad_manifest = dict(manifest, upstream_commit="0000000000000000000000000000000000000000")

    try:
        validate_iron_contract_manifest(bad_manifest)
    except ValueError as exc:
        assert "upstream_commit" in str(exc)
    else:  # pragma: no cover - the failure path is what the test is asserting.
        raise AssertionError("stale upstream manifest should fail closed")


def test_iron_transform_module_imports_no_iron_business_logic() -> None:
    module_path = ROOT / "dagr_mcp_service" / "iron_transform.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)

    assert not any(name.startswith("iron_proxy") for name in imports)
    assert "paradigmxyz" not in imports
    assert "fastmcp" not in imports
    assert "mcp" not in imports

