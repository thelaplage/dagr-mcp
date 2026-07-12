"""Behavior-preserving port of garp-local's enforcement-harness test suite.

Imports resolve against the canonical SDK (``dagr_mcp.*``) rather than the
garp-local monolith (``garp_core.*``). The assertions are unchanged from
garp-local so the extracted harness is held to the monolith's behavior
contract: happy path, refused/blocked, review-required gate, and
event/receipt/review-object sink emission, all on hash-only payloads.
"""

from __future__ import annotations

from typing import Any

from dagr_mcp.enforcement_harness import (
    HarnessConfig,
    HarnessSinks,
    ToolPolicy,
    wrap_handler,
)
from dagr_mcp.sdk_spine import (
    InMemoryEventSink,
    InMemoryReceiptSink,
    InMemoryReviewObjectSink,
)
from dagr_mcp.tool_call_disposition import validate_tool_call_disposition_review_object


class RecordingHandler:
    def __init__(self, *, fail: bool = False, result: Any | None = None) -> None:
        self.calls: list[tuple[str, Any, Any]] = []
        self.fail = fail
        self.result = {"status": "ok"} if result is None else result

    def handle_tool_call(
        self,
        tool_name: str,
        arguments: Any,
        context: Any = None,
    ) -> Any:
        self.calls.append((tool_name, arguments, context))
        if self.fail:
            raise RuntimeError("handler failed")
        return self.result


def _config() -> HarnessConfig:
    return HarnessConfig(
        harness_version="0.1.0",
        module_id="module.test",
        module_version="1.2.3",
        profile_ref="profile:test",
        policy_ref="policy:test",
        policy_hash="sha256:policy",
    )


def _allow_policy(
    tool_name: str = "read_status",
    *,
    receipt_required: bool = False,
) -> ToolPolicy:
    return ToolPolicy(
        tool_name=tool_name,
        tool_class="read",
        decision="allow",
        receipt_required=receipt_required,
        required_sinks=["event", "receipt"] if receipt_required else ["event"],
    )


def _event_types(event_sink: InMemoryEventSink) -> list[str]:
    return [event.event_type for event in event_sink.events.values()]


def test_allowed_read_tool_emits_requested_and_executed_events() -> None:
    handler = RecordingHandler(result={"value": "done"})
    event_sink = InMemoryEventSink()
    wrapped = wrap_handler(
        handler,
        _config(),
        HarnessSinks(event=event_sink),
        policies=[_allow_policy()],
    )

    governed = wrapped(
        "read_status",
        {"query": "case-count"},
        context={"actor_ref": "actor:test", "session_ref": "session:1"},
    )

    assert governed.ok is True
    assert governed.result == {"value": "done"}
    assert handler.calls == [
        (
            "read_status",
            {"query": "case-count"},
            {"actor_ref": "actor:test", "session_ref": "session:1"},
        )
    ]
    assert governed.event_refs == ["event:1", "event:2"]
    assert _event_types(event_sink) == [
        "mcp.tool.call.requested",
        "mcp.tool.call.executed",
    ]
    assert governed.context is not None
    assert governed.context.arguments_hash.startswith("sha256:")
    assert governed.context.result_hash is not None
    for et in ("mcp.tool.call.requested", "mcp.tool.call.executed"):
        ev = next(e for e in event_sink.events.values() if e.event_type == et)
        assert ev.detail["argument_hash"] == ev.detail["arguments_hash"]
        assert ev.detail["argument_hash"].startswith("sha256:")
        assert "query" not in ev.detail


def test_receipt_required_writes_receipt_through_receipt_sink() -> None:
    handler = RecordingHandler(result={"value": "done"})
    event_sink = InMemoryEventSink()
    receipt_sink = InMemoryReceiptSink()
    wrapped = wrap_handler(
        handler,
        _config(),
        HarnessSinks(event=event_sink, receipt=receipt_sink),
        policies=[_allow_policy(receipt_required=True)],
    )

    governed = wrapped("read_status", {"query": "case-count"})

    assert governed.ok is True
    assert governed.receipt_refs == ["receipt:1"]
    receipt = receipt_sink.receipts["receipt:1"]
    assert receipt.receipt_type == "sdk_enforcement"
    assert receipt.boundary_type == "mcp_tool_call"
    assert receipt.protocol_binding == "mcp"
    assert receipt.policy_ref == "policy:test"
    assert receipt.policy_hash == "sha256:policy"
    assert receipt.critical_extensions == ["mcp"]
    assert receipt.extensions["mcp"]["mcp_tool_name"] == "read_status"
    assert receipt.extensions["mcp"]["mcp_arguments_hash"].startswith("sha256:")
    assert receipt.extensions["mcp"]["mcp_result_hash"].startswith("sha256:")


def test_receipt_required_with_missing_receipt_sink_fails_closed() -> None:
    handler = RecordingHandler()
    event_sink = InMemoryEventSink()
    wrapped = wrap_handler(
        handler,
        _config(),
        HarnessSinks(event=event_sink),
        policies=[_allow_policy(receipt_required=True)],
    )

    governed = wrapped("read_status", {"query": "case-count"})

    assert governed.ok is False
    assert governed.failure_reason == "receipt_sink_unavailable"
    assert handler.calls == []
    assert _event_types(event_sink) == [
        "mcp.tool.call.requested",
        "mcp.tool.call.rejected",
    ]


def test_unknown_tool_fails_closed_by_default() -> None:
    handler = RecordingHandler()
    event_sink = InMemoryEventSink()
    wrapped = wrap_handler(
        handler,
        _config(),
        HarnessSinks(event=event_sink),
        policies=[],
    )

    governed = wrapped("unknown_tool", {"query": "case-count"})

    assert governed.ok is False
    assert governed.failure_reason == "unknown_tool"
    assert handler.calls == []
    assert _event_types(event_sink) == [
        "mcp.tool.call.requested",
        "mcp.tool.call.rejected",
    ]


def test_denied_tool_emits_rejected_and_does_not_execute() -> None:
    handler = RecordingHandler()
    event_sink = InMemoryEventSink()
    wrapped = wrap_handler(
        handler,
        _config(),
        HarnessSinks(event=event_sink),
        policies=[
            ToolPolicy(
                tool_name="delete_record",
                tool_class="destructive",
                decision="deny",
                required_sinks=["event"],
                reason="policy_denied",
            )
        ],
    )

    governed = wrapped("delete_record", {"record_id": "rec-1"})

    assert governed.ok is False
    assert governed.failure_reason == "denied"
    assert handler.calls == []
    assert _event_types(event_sink) == [
        "mcp.tool.call.requested",
        "mcp.tool.call.rejected",
    ]
    assert event_sink.events["event:2"].detail["reason"] == "policy_denied"


def test_inner_exception_emits_failed_event_and_returns_governed_failure() -> None:
    handler = RecordingHandler(fail=True)
    event_sink = InMemoryEventSink()
    wrapped = wrap_handler(
        handler,
        _config(),
        HarnessSinks(event=event_sink),
        policies=[_allow_policy()],
    )

    governed = wrapped("read_status", {"query": "case-count"})

    assert governed.ok is False
    assert governed.failure_reason == "inner_exception"
    assert handler.calls == [("read_status", {"query": "case-count"}, None)]
    assert _event_types(event_sink) == [
        "mcp.tool.call.requested",
        "mcp.tool.call.failed",
    ]
    assert event_sink.events["event:2"].detail["failure_class"] == "RuntimeError"


def test_gated_tool_creates_review_object_and_does_not_execute() -> None:
    handler = RecordingHandler()
    event_sink = InMemoryEventSink()
    review_sink = InMemoryReviewObjectSink()
    wrapped = wrap_handler(
        handler,
        _config(),
        HarnessSinks(event=event_sink, review=review_sink),
        policies=[
            ToolPolicy(
                tool_name="publish_record",
                tool_class="write",
                decision="gate",
                receipt_required=False,
                review_required=True,
                required_sinks=["event", "review"],
                reason="review_required",
                gate_timeout_seconds=30,
            )
        ],
    )

    governed = wrapped("publish_record", {"record_id": "rec-1"})

    assert governed.ok is False
    assert governed.failure_reason == "gated_pending"
    assert governed.review_object_ref == "review:1"
    assert handler.calls == []
    assert _event_types(event_sink) == [
        "mcp.tool.call.requested",
        "mcp.tool.call.gated",
    ]
    review_object = review_sink.review_objects["review:1"]
    assert review_object.review_object_type == "tool_call_disposition"
    assert review_object.governance_state == "pending"
    assert review_object.origin_event_id == "event:1"
    assert review_object.context_payload["tool_name"] == "publish_record"
    assert review_object.context_payload["argument_hash"].startswith("sha256:")
    assert "arguments_hash" not in review_object.context_payload
    assert "record_id" not in review_object.context_payload
    validate_tool_call_disposition_review_object(review_object)
    gated = next(
        e for e in event_sink.events.values() if e.event_type == "mcp.tool.call.gated"
    )
    assert gated.detail["argument_hash"].startswith("sha256:")
    assert gated.detail["arguments_hash"] == gated.detail["argument_hash"]


def test_gate_tool_rejects_non_mapping_arguments() -> None:
    handler = RecordingHandler()
    wrapped = wrap_handler(
        handler,
        _config(),
        HarnessSinks(event=InMemoryEventSink(), review=InMemoryReviewObjectSink()),
        policies=[
            ToolPolicy(
                tool_name="publish_record",
                tool_class="write",
                decision="gate",
                receipt_required=False,
                review_required=True,
                required_sinks=["event", "review"],
                reason="review_required",
                gate_timeout_seconds=30,
            )
        ],
    )

    governed = wrapped("publish_record", ["not-a-mapping"])

    assert governed.ok is False
    assert governed.failure_reason == "tool_call_arguments_not_mapping"
    assert handler.calls == []


def test_gate_tool_disposition_invalid_gate_timeout_zero_fails_closed() -> None:
    handler = RecordingHandler()
    event_sink = InMemoryEventSink()
    review_sink = InMemoryReviewObjectSink()
    wrapped = wrap_handler(
        handler,
        _config(),
        HarnessSinks(event=event_sink, review=review_sink),
        policies=[
            ToolPolicy(
                tool_name="publish_record",
                tool_class="write",
                decision="gate",
                receipt_required=False,
                review_required=True,
                required_sinks=["event", "review"],
                reason="review_required",
                gate_timeout_seconds=0,
            )
        ],
    )

    governed = wrapped("publish_record", {"record_id": "rec-1"})

    assert governed.ok is False
    assert governed.failure_reason == "tool_call_disposition_invalid"
    assert handler.calls == []
    assert review_sink.review_objects == {}


def test_allow_with_review_required_still_executes_without_disposition_gate() -> None:
    """``review_required`` alone does not gate execution; only ``decision == gate`` does."""
    handler = RecordingHandler()
    event_sink = InMemoryEventSink()
    review_sink = InMemoryReviewObjectSink()
    wrapped = wrap_handler(
        handler,
        _config(),
        HarnessSinks(event=event_sink, review=review_sink),
        policies=[
            ToolPolicy(
                tool_name="read_status",
                tool_class="read",
                decision="allow",
                receipt_required=False,
                review_required=True,
                required_sinks=["event", "review"],
                reason="ops_prefers_review_sink",
            )
        ],
    )

    governed = wrapped("read_status", {"query": "case-count"})

    assert governed.ok is True
    assert governed.result == {"status": "ok"}
    assert handler.calls == [("read_status", {"query": "case-count"}, None)]
    assert review_sink.review_objects == {}
    assert _event_types(event_sink) == [
        "mcp.tool.call.requested",
        "mcp.tool.call.executed",
    ]


def test_unavailable_event_sink_fails_closed_before_execution() -> None:
    handler = RecordingHandler()
    event_sink = InMemoryEventSink(available=False)
    wrapped = wrap_handler(
        handler,
        _config(),
        HarnessSinks(event=event_sink),
        policies=[_allow_policy()],
    )

    governed = wrapped("read_status", {"query": "case-count"})

    assert governed.ok is False
    assert governed.failure_reason == "event_sink_unavailable"
    assert governed.event_refs == []
    assert handler.calls == []


def test_events_and_receipts_store_hashes_not_raw_payloads() -> None:
    handler = RecordingHandler(result={"secret_result": "do-not-store-result"})
    event_sink = InMemoryEventSink()
    receipt_sink = InMemoryReceiptSink()
    wrapped = wrap_handler(
        handler,
        _config(),
        HarnessSinks(event=event_sink, receipt=receipt_sink),
        policies=[_allow_policy(receipt_required=True)],
    )

    governed = wrapped("read_status", {"secret_arg": "do-not-store-arg"})

    assert governed.ok is True
    event_details = [event.detail for event in event_sink.events.values()]
    receipt = receipt_sink.receipts["receipt:1"]
    serialized_sink_records = repr(event_details) + repr(receipt.extensions)

    assert "do-not-store-arg" not in serialized_sink_records
    assert "do-not-store-result" not in serialized_sink_records
    assert "secret_arg" not in serialized_sink_records
    assert "secret_result" not in serialized_sink_records
    assert "argument_hash" in serialized_sink_records
    assert "arguments_hash" in serialized_sink_records
    assert "mcp_arguments_hash" in serialized_sink_records
    assert "mcp_result_hash" in serialized_sink_records


def test_wrapper_supports_callable_inner() -> None:
    calls: list[tuple[str, Any, Any]] = []

    def inner(tool_name: str, arguments: Any, context: Any = None) -> Any:
        calls.append((tool_name, arguments, context))
        return {"callable": True}

    event_sink = InMemoryEventSink()
    wrapped = wrap_handler(
        inner,
        _config(),
        HarnessSinks(event=event_sink),
        policies=[_allow_policy()],
    )

    governed = wrapped("read_status", {"query": "case-count"}, context={"req": "1"})

    assert governed.ok is True
    assert governed.result == {"callable": True}
    assert calls == [("read_status", {"query": "case-count"}, {"req": "1"})]
    assert _event_types(event_sink) == [
        "mcp.tool.call.requested",
        "mcp.tool.call.executed",
    ]
