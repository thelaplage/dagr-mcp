from __future__ import annotations

import asyncio
import base64
import copy
import importlib.metadata
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("fastmcp")
pytest.importorskip("rfc8785")
pytest.importorskip("jsonschema")

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastmcp import FastMCP
from fastmcp.client import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from jsonschema import Draft202012Validator
from mcp.types import CallToolRequestParams, CreateTaskResult, Task, TextContent

from dagr_mcp.fastmcp_binding import (
    BINDING_VERSION,
    CREATE_TASK_RESULT_IMPORT_PATH,
    PROXY_BOUNDARY_LIMIT,
    ActorResolution,
    BindingPolicy,
    DAGRMiddleware,
    DAGRMiddlewareConfig,
    default_actor_resolution,
    project_fastmcp_tool_result,
)
from dagr_mcp.sdk_spine import InMemoryReviewObjectSink
from dagr_mcp.srs_receipts import (
    RESULT_LIMIT,
    TASK_LIMIT,
    RawEnvelopeFileSink,
    ReceiptWriteError,
    SignedReceiptEmitter,
    SigningIdentity,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (ROOT / "dagr_mcp/vendor/srs/srs-envelope-v0.2.0.schema.json").read_text()
)


def decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_signature(receipt: dict[str, Any], bundle: dict[str, Any]) -> None:
    assert not list(Draft202012Validator(SCHEMA).iter_errors(receipt))
    preimage = copy.deepcopy(receipt)
    signature = decode(preimage["receipt_signature"].pop("signature"))
    entry = bundle["issuers"][0]
    Ed25519PublicKey.from_public_bytes(decode(entry["public_key"])).verify(
        signature,
        rfc8785.dumps(preimage),
    )


def signature_ok(receipt: dict[str, Any], bundle: dict[str, Any]) -> bool:
    try:
        verify_signature(receipt, bundle)
        return True
    except InvalidSignature:
        return False


def read_receipts(directory: Path) -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("urn_srs_receipt_*.json"))
    ]


def split_pair(receipts: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    admission = next(item for item in receipts if item["receipt_kind"] == "admission")
    outcome = next(item for item in receipts if item["receipt_kind"] == "outcome")
    return admission, outcome


def assert_all_receipts_verify(
    directory: Path,
    identity: SigningIdentity,
) -> list[dict[str, Any]]:
    receipts = read_receipts(directory)
    bundle = identity.trust_bundle()
    for receipt in receipts:
        verify_signature(receipt, bundle)
        assert receipt["extensions"]["mcp"]["binding_version"] == BINDING_VERSION
    return receipts


def build_binding(
    tmp_path: Path,
    *,
    policy_resolver: Any | None = None,
    actor_resolver: Any | None = None,
    review_object_creator: Any | None = None,
    tool_classes: dict[str, str] | None = None,
    emergency_spool_path: Path | None = None,
    parent_receipt_ref: str | None = None,
    additional_limits: tuple[str, ...] = (),
) -> tuple[DAGRMiddleware, SigningIdentity, Path]:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = SigningIdentity.generate(
        issuer_id="issuer:test:fastmcp",
        key_id="issuer.test.fastmcp/key/1",
    )
    emitter = SignedReceiptEmitter(identity=identity, sink=sink)
    limits = (
        (
            "The middleware is installed once at the institutional trust boundary; "
            "receipts attest only to observations at that boundary."
        ),
        *additional_limits,
    )
    middleware = DAGRMiddleware(
        emitter=emitter,
        config=DAGRMiddlewareConfig(
            runtime_instance_id="runtime:test:fastmcp",
            boundary_id="boundary:test:fastmcp",
            policy_pack_id="policy:test:fastmcp",
            policy_pack_version="2026.07.11",
            tool_classes=tool_classes or {},
            policy_resolver=policy_resolver,
            actor_resolver=actor_resolver,
            review_object_creator=review_object_creator,
            emergency_spool_path=emergency_spool_path,
            parent_receipt_ref=parent_receipt_ref,
            additional_attestation_limits=limits,
        ),
    )
    return middleware, identity, directory


def build_server(tmp_path: Path, **kwargs: Any) -> tuple[FastMCP, DAGRMiddleware, SigningIdentity, Path]:
    server = FastMCP("dagr-fastmcp-test")
    middleware, identity, directory = build_binding(tmp_path, **kwargs)
    server.add_middleware(middleware)
    return server, middleware, identity, directory


async def call_direct(
    middleware: DAGRMiddleware,
    name: str,
    result: Any | BaseException,
    arguments: dict[str, Any] | None = None,
) -> Any:
    context = MiddlewareContext(
        message=CallToolRequestParams(name=name, arguments=arguments or {}),
        method="tools/call",
    )

    async def call_next(_context: MiddlewareContext[Any]) -> Any:
        if isinstance(result, BaseException):
            raise result
        return result

    return await middleware.on_call_tool(context, call_next)


async def test_normal_async_tool_emits_admission_and_result_outcome(tmp_path: Path):
    server, _middleware, identity, directory = build_server(tmp_path)

    @server.tool
    async def lookup(record_ref: str) -> dict[str, Any]:
        return {"record_ref": record_ref, "found": True}

    async with Client(server) as client:
        result = await client.call_tool("lookup", {"record_ref": "record:1"})

    assert result.data == {"record_ref": "record:1", "found": True}
    receipts = assert_all_receipts_verify(directory, identity)
    admission, outcome = split_pair(receipts)
    assert admission["disposition"] == "admitted"
    assert outcome["admission_receipt_ref"] == admission["receipt_id"]
    assert outcome["outcome"] == "result_returned"
    assert RESULT_LIMIT in outcome["attestation_limits"]


async def test_normal_sync_tool_returns_without_event_loop_blocking(tmp_path: Path):
    server, _middleware, identity, directory = build_server(tmp_path)
    marker = asyncio.Event()

    @server.tool
    def add(a: int, b: int) -> int:
        return a + b

    async def mark_loop_progress() -> None:
        await asyncio.sleep(0)
        marker.set()

    async with Client(server) as client:
        progress = asyncio.create_task(mark_loop_progress())
        result = await client.call_tool("add", {"a": 2, "b": 3})
        await progress

    assert marker.is_set()
    assert result.data == 5
    receipts = assert_all_receipts_verify(directory, identity)
    assert split_pair(receipts)[1]["outcome"] == "result_returned"


async def test_error_tool_result_is_classified_error_returned(tmp_path: Path):
    middleware, identity, directory = build_binding(tmp_path)
    returned = SimpleNamespace(
        content=[TextContent(type="text", text="not found")],
        structured_content=None,
        meta=None,
        is_error=True,
    )

    result = await call_direct(middleware, "cached-error", returned)

    assert result is returned
    receipts = assert_all_receipts_verify(directory, identity)
    assert split_pair(receipts)[1]["outcome"] == "error_returned"


async def test_raised_tool_error_is_exception_outcome_and_propagates(tmp_path: Path):
    server, _middleware, identity, directory = build_server(tmp_path)

    @server.tool
    async def explode() -> str:
        raise ToolError("sensitive detail must not enter receipts")

    async with Client(server) as client:
        with pytest.raises(ToolError):
            await client.call_tool("explode", {})

    receipts = assert_all_receipts_verify(directory, identity)
    _admission, outcome = split_pair(receipts)
    assert outcome["outcome"] == "exception"
    assert outcome["extensions"]["mcp"]["exception_class"] == "ToolError"
    assert "sensitive detail" not in json.dumps(receipts)


async def test_unknown_tool_has_admission_and_exception_without_resolution_claim(tmp_path: Path):
    server, _middleware, identity, directory = build_server(tmp_path)

    async with Client(server) as client:
        with pytest.raises(ToolError):
            await client.call_tool("missing_tool", {})

    receipts = assert_all_receipts_verify(directory, identity)
    admission, outcome = split_pair(receipts)
    assert admission["tool_resolution_status"] == "not_observed"
    assert outcome["outcome"] == "exception"


async def test_policy_refusal_never_executes_handler(tmp_path: Path):
    called = False

    def resolver(_snapshot: Any, _actor: ActorResolution) -> BindingPolicy:
        return BindingPolicy(
            disposition="refused",
            tool_class="destructive",
            reason_code="policy_refused",
        )

    server, _middleware, identity, directory = build_server(
        tmp_path,
        policy_resolver=resolver,
    )

    @server.tool
    async def destroy() -> str:
        nonlocal called
        called = True
        return "unexpected"

    async with Client(server) as client:
        with pytest.raises(ToolError, match="Call refused by admission policy"):
            await client.call_tool("destroy", {})

    assert called is False
    receipts = assert_all_receipts_verify(directory, identity)
    assert len(receipts) == 1
    assert receipts[0]["disposition"] == "refused"
    assert receipts[0]["reason_code"] == "policy_refused"


async def test_review_required_creates_object_and_never_parks_request(tmp_path: Path):
    called = False
    review_refs: list[str] = []

    def resolver(_snapshot: Any, _actor: ActorResolution) -> BindingPolicy:
        return BindingPolicy(disposition="deferred_for_review", tool_class="write")

    def create_review(_snapshot: Any, _actor: ActorResolution, _policy: BindingPolicy) -> str:
        review_refs.append("review:public:1")
        return review_refs[-1]

    server, _middleware, identity, directory = build_server(
        tmp_path,
        policy_resolver=resolver,
        review_object_creator=create_review,
    )

    @server.tool
    async def update() -> str:
        nonlocal called
        called = True
        return "unexpected"

    async with Client(server) as client:
        with pytest.raises(ToolError, match="review:public:1"):
            await client.call_tool("update", {})

    assert called is False
    assert review_refs == ["review:public:1"]
    receipts = assert_all_receipts_verify(directory, identity)
    assert len(receipts) == 1
    assert receipts[0]["disposition"] == "deferred_for_review"
    assert receipts[0]["review_object_ref"] == "review:public:1"
    assert receipts[0]["retry_contract"] == "retry_after_approval"


async def test_review_object_creation_failure_is_terminal_refusal(tmp_path: Path):
    called = False

    def resolver(_snapshot: Any, _actor: ActorResolution) -> BindingPolicy:
        return BindingPolicy(disposition="deferred_for_review", tool_class="write")

    def fail_review(_snapshot: Any, _actor: ActorResolution, _policy: BindingPolicy) -> str:
        raise RuntimeError("queue unavailable")

    server, _middleware, identity, directory = build_server(
        tmp_path,
        policy_resolver=resolver,
        review_object_creator=fail_review,
    )

    @server.tool
    async def update() -> str:
        nonlocal called
        called = True
        return "unexpected"

    async with Client(server) as client:
        with pytest.raises(ToolError, match="Call refused by admission policy"):
            await client.call_tool("update", {})

    assert called is False
    receipts = assert_all_receipts_verify(directory, identity)
    assert len(receipts) == 1
    assert receipts[0]["disposition"] == "refused"
    assert receipts[0]["reason_code"] == "review_object_creation_failed"
    assert "review_object_ref" not in receipts[0]


async def test_review_object_sink_contract_is_usable(tmp_path: Path):
    def resolver(_snapshot: Any, _actor: ActorResolution) -> BindingPolicy:
        return BindingPolicy(disposition="deferred_for_review", tool_class="write")

    middleware, identity, directory = build_binding(
        tmp_path,
        policy_resolver=resolver,
        review_object_creator=InMemoryReviewObjectSink(),
    )

    with pytest.raises(ToolError, match="review"):
        await call_direct(middleware, "needs-review", ToolResult(content=["unused"]))

    receipts = assert_all_receipts_verify(directory, identity)
    assert receipts[0]["disposition"] == "deferred_for_review"


async def test_receipt_signature_mutation_contract_for_fastmcp_receipt(tmp_path: Path):
    middleware, identity, directory = build_binding(tmp_path)
    result = ToolResult(content=["ok"], structured_content={"ok": True})
    await call_direct(middleware, "lookup", result)
    receipts = assert_all_receipts_verify(directory, identity)
    _admission, outcome = split_pair(receipts)
    bundle = identity.trust_bundle()

    changed = copy.deepcopy(outcome)
    changed["outcome"] = "error_returned"
    assert signature_ok(changed, bundle) is False

    reordered = json.loads(json.dumps(outcome, indent=5, sort_keys=False))
    verify_signature(reordered, bundle)


async def test_cache_hit_from_inner_middleware_receipts_result_returned(tmp_path: Path):
    called = False
    server, _middleware, identity, directory = build_server(tmp_path)

    class StoredResultMiddleware(Middleware):
        async def on_call_tool(self, context: MiddlewareContext[Any], call_next: Any) -> Any:
            return ToolResult(content=["cached"], structured_content={"result": "cached"})

    server.add_middleware(StoredResultMiddleware())

    @server.tool
    async def cached() -> str:
        nonlocal called
        called = True
        return "unexpected"

    async with Client(server) as client:
        result = await client.call_tool("cached", {})

    assert called is False
    assert result.data == "cached"
    assert result.structured_content == {"result": "cached"}
    receipts = assert_all_receipts_verify(directory, identity)
    assert split_pair(receipts)[1]["outcome"] == "result_returned"
    assert RESULT_LIMIT in split_pair(receipts)[1]["attestation_limits"]


async def test_retry_middleware_collapses_to_one_logical_outcome(tmp_path: Path):
    server, _middleware, identity, directory = build_server(tmp_path)
    attempts = 0

    class RetryOnceMiddleware(Middleware):
        async def on_call_tool(self, context: MiddlewareContext[Any], call_next: Any) -> Any:
            try:
                return await call_next(context)
            except Exception:
                return await call_next(context)

    server.add_middleware(RetryOnceMiddleware())

    @server.tool
    async def flaky() -> dict[str, int]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient")
        return {"attempts": attempts}

    async with Client(server) as client:
        result = await client.call_tool("flaky", {})

    assert result.data == {"attempts": 2}
    receipts = assert_all_receipts_verify(directory, identity)
    assert [item["receipt_kind"] for item in receipts].count("outcome") == 1
    assert split_pair(receipts)[1]["outcome"] == "result_returned"


async def test_create_task_result_emits_task_submitted_only(tmp_path: Path):
    if importlib.metadata.version("fastmcp") == "3.4.4":
        assert CREATE_TASK_RESULT_IMPORT_PATH == "mcp.types.CreateTaskResult"

    middleware, identity, directory = build_binding(tmp_path)
    now = datetime.now(UTC)
    task_result = CreateTaskResult(
        task=Task(
            taskId="task:test:1",
            status="working",
            createdAt=now,
            lastUpdatedAt=now,
            ttl=None,
        )
    )

    returned = await call_direct(middleware, "background", task_result)

    assert returned is task_result
    receipts = assert_all_receipts_verify(directory, identity)
    assert split_pair(receipts)[1]["outcome"] == "task_submitted"
    assert TASK_LIMIT in split_pair(receipts)[1]["attestation_limits"]


async def test_cancelled_call_gets_best_effort_indeterminate_and_reraises(tmp_path: Path):
    middleware, identity, directory = build_binding(tmp_path)

    with pytest.raises(asyncio.CancelledError):
        await call_direct(middleware, "slow", asyncio.CancelledError())

    receipts = assert_all_receipts_verify(directory, identity)
    _admission, outcome = split_pair(receipts)
    assert outcome["outcome"] == "indeterminate"
    assert outcome["request_cancelled"] is True
    assert outcome["execution_state_unknown"] is True
    assert outcome["result_not_delivered"] is True


async def test_timeout_does_not_record_success_after_effect_may_have_happened(tmp_path: Path):
    server, _middleware, identity, directory = build_server(
        tmp_path,
        tool_classes={"slow_write": "write"},
    )
    effects: list[str] = []

    @server.tool
    async def slow_write() -> str:
        effects.append("started")
        await asyncio.sleep(10)
        return "done"

    async with Client(server) as client:
        with pytest.raises(Exception):
            await client.call_tool("slow_write", {}, timeout=0.01)

    assert effects == ["started"]
    receipts = assert_all_receipts_verify(directory, identity)
    outcomes = [item for item in receipts if item["receipt_kind"] == "outcome"]
    assert not outcomes or outcomes[0]["outcome"] != "result_returned"


async def test_pre_execution_signer_failure_honors_tool_class_policy(tmp_path: Path):
    class FailingEmitter:
        def emit_admission(self, **_kwargs: Any) -> str:
            raise ReceiptWriteError("sink failed")

        def emit_outcome(self, **_kwargs: Any) -> str:
            raise AssertionError("outcome should not be reached")

    closed = DAGRMiddleware(
        emitter=FailingEmitter(),  # type: ignore[arg-type]
        config=DAGRMiddlewareConfig(
            runtime_instance_id="runtime:test",
            boundary_id="boundary:test",
            policy_pack_id="policy:test",
            policy_pack_version="1",
            tool_classes={"write_tool": "write"},
        ),
    )
    open_ = DAGRMiddleware(
        emitter=FailingEmitter(),  # type: ignore[arg-type]
        config=DAGRMiddlewareConfig(
            runtime_instance_id="runtime:test",
            boundary_id="boundary:test",
            policy_pack_id="policy:test",
            policy_pack_version="1",
            tool_classes={"read_tool": "read"},
        ),
    )

    with pytest.raises(ToolError, match="durably accepted"):
        await call_direct(closed, "write_tool", ToolResult(content=["blocked"]))

    result = ToolResult(content=["allowed"], structured_content={"ok": True})
    returned = await call_direct(open_, "read_tool", result)
    assert returned is result


async def test_outcome_sink_failure_returns_result_and_writes_receipt_gap(tmp_path: Path):
    directory = tmp_path / "receipts"
    spool = tmp_path / "emergency" / "receipt-gaps.jsonl"
    identity = SigningIdentity.generate(
        issuer_id="issuer:test:gap",
        key_id="issuer.test.gap/key/1",
    )
    real_emitter = SignedReceiptEmitter(
        identity=identity,
        sink=RawEnvelopeFileSink(directory),
    )

    class AdmissionOnlyEmitter:
        def emit_admission(self, **kwargs: Any) -> str:
            return real_emitter.emit_admission(**kwargs)

        def emit_outcome(self, **_kwargs: Any) -> str:
            raise ReceiptWriteError("primary sink unavailable")

    middleware = DAGRMiddleware(
        emitter=AdmissionOnlyEmitter(),  # type: ignore[arg-type]
        config=DAGRMiddlewareConfig(
            runtime_instance_id="runtime:test:gap",
            boundary_id="boundary:test:gap",
            policy_pack_id="policy:test",
            policy_pack_version="1",
            emergency_spool_path=spool,
        ),
    )
    result = ToolResult(content=["ok"], structured_content={"ok": True})

    returned = await call_direct(middleware, "lookup", result)

    assert returned is result
    receipts = assert_all_receipts_verify(directory, identity)
    assert [receipt["receipt_kind"] for receipt in receipts] == ["admission"]
    event = json.loads(spool.read_text(encoding="utf-8").splitlines()[0])
    assert event["event_type"] == "receipt_gap"
    assert event["attempted_receipt_kind"] == "outcome"
    assert event["failure_class"] == "receipt_sink_failure"


async def test_parent_receipt_and_proxy_boundary_semantics_are_recorded(tmp_path: Path):
    middleware, identity, directory = build_binding(
        tmp_path,
        parent_receipt_ref="urn:srs:receipt:parent:1",
        additional_limits=(PROXY_BOUNDARY_LIMIT,),
    )
    await call_direct(middleware, "proxied", ToolResult(content=["ok"]))
    receipts = assert_all_receipts_verify(directory, identity)
    for receipt in receipts:
        assert receipt["parent_receipt_ref"] == "urn:srs:receipt:parent:1"
        assert PROXY_BOUNDARY_LIMIT in receipt["attestation_limits"]


async def test_mounted_server_uses_parent_boundary_without_duplicate_receipts(tmp_path: Path):
    parent, _middleware, identity, directory = build_server(tmp_path)
    child = FastMCP("child")

    @child.tool
    async def mounted_lookup() -> dict[str, bool]:
        return {"mounted": True}

    parent.mount(child, namespace="child")

    async with Client(parent) as client:
        tools = await client.list_tools()
        mounted_name = next(tool.name for tool in tools if "mounted_lookup" in tool.name)
        result = await client.call_tool(mounted_name, {})

    assert result.data == {"mounted": True}
    receipts = assert_all_receipts_verify(directory, identity)
    admission, outcome = split_pair(receipts)
    assert admission["logical_call_id"] == outcome["logical_call_id"]
    assert [item["receipt_kind"] for item in receipts] == ["admission", "outcome"]


async def test_direct_programmatic_call_uses_anonymous_local_actor(tmp_path: Path):
    middleware, identity, directory = build_binding(tmp_path)
    await call_direct(middleware, "direct", ToolResult(content=["ok"]))
    receipts = assert_all_receipts_verify(directory, identity)
    admission, _outcome = split_pair(receipts)
    assert admission["actor_ref"] == "actor:anonymous_or_local"
    assert admission["subject_ref"].startswith("tool-call:call:")


async def test_authenticated_claims_are_hashed_and_raw_token_absent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    raw_token = "raw-token-never-write"
    token = SimpleNamespace(
        token=raw_token,
        claims={"sub": "user-123", "tenant_id": "tenant-a"},
        client_id="client-a",
        scopes=["tools"],
        resource="mcp",
    )
    import dagr_mcp.fastmcp_binding as binding_module

    monkeypatch.setattr(binding_module, "get_access_token", lambda: token)
    actor = default_actor_resolution()
    assert actor.actor_ref.startswith("actor:sha256:")

    middleware, identity, directory = build_binding(tmp_path)
    await call_direct(middleware, "auth", ToolResult(content=["ok"]))
    receipts = assert_all_receipts_verify(directory, identity)
    rendered = json.dumps(receipts)
    assert raw_token not in rendered
    for path in directory.rglob("*"):
        if path.is_file():
            assert raw_token not in path.read_text(encoding="utf-8")


async def test_stdio_like_call_without_token_is_anonymous_or_local(tmp_path: Path):
    middleware, identity, directory = build_binding(tmp_path)
    await call_direct(middleware, "stdio", ToolResult(content=["ok"]))
    receipts = assert_all_receipts_verify(directory, identity)
    assert split_pair(receipts)[0]["actor_ref"] == "actor:anonymous_or_local"


async def test_fixture_overrides_capture_live_middleware_projection(tmp_path: Path):
    directory = tmp_path / "receipts"
    identity = SigningIdentity.generate(
        issuer_id="issuer:test:projection-observer",
        key_id="issuer.test.projection-observer/key/1",
    )
    observed: list[dict[str, Any]] = []
    middleware = DAGRMiddleware(
        emitter=SignedReceiptEmitter(
            identity=identity,
            sink=RawEnvelopeFileSink(directory),
        ),
        config=DAGRMiddlewareConfig(
            runtime_instance_id="runtime:test:projection-observer",
            boundary_id="boundary:test:projection-observer",
            policy_pack_id="policy:test:projection-observer",
            policy_pack_version="1",
            logical_call_id_override="call:fixture:fastmcp:1",
            subject_ref_override="tool-call:fixture:fastmcp:1",
            result_projection_observer=lambda projection: observed.append(
                dict(projection)
            ),
        ),
    )
    result = ToolResult(
        content=[TextContent(type="text", text='{"found":true}')],
        structured_content={"found": True},
    )

    returned = await call_direct(
        middleware,
        "records_lookup",
        result,
        {"record_ref": "record:demo:1"},
    )

    assert returned is result
    assert observed == [project_fastmcp_tool_result(result)]

    receipts = assert_all_receipts_verify(directory, identity)
    assert len(receipts) == 2
    for receipt in receipts:
        assert receipt["logical_call_id"] == "call:fixture:fastmcp:1"
        assert receipt["subject_ref"] == "tool-call:fixture:fastmcp:1"
