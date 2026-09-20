"""DAGR-SDKV2-POSTOUTCOME0: optional, generic post-outcome composition seam.

Closes a binding-coverage gap: ``_emit_outcome_from_observation`` already
receives the durable outcome-receipt reference string back from
``emitter.emit_outcome`` but previously discarded it -- there was no way for
an operator to compose anything AFTER a governed call's outcome receipt has
been durably written. This suite proves the seam this lane adds
(``SdkV2BindingConfig.post_outcome_hook`` / ``PostOutcomeEvent``):

* No hook configured -> byte-identical behavior to before this seam existed
  (every other test file in this package already proves this implicitly by
  passing unmodified; this file adds an explicit check too).
* Mechanical ordering: delegate dispatch < durable outcome-receipt write <
  hook invocation < return to caller -- proven by an observed sequence list,
  not by inspection.
* The hook receives the EXACT outcome-receipt ref string ``emit_outcome``
  returned, and the correct ``admission_receipt_ref``.
* The hook is invoked exactly once per completed governed execution.
* The hook is NEVER invoked on: admission refusal, admission-receipt
  failure/no admission ref, or ``input_required`` -- i.e. any path where no
  durable outcome receipt exists.
* A raising hook is a POST-EXECUTION failure only: the result is still
  returned unchanged, local telemetry records the gap, the already-emitted
  outcome receipt is never rewritten, and no fabricated ref is produced.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from mcp import types as mcp_types

from dagr_mcp_core.srs_receipts import RawEnvelopeFileSink, SignedReceiptEmitter, SigningIdentity
from dagr_mcp_sdk_v2.adapter import (
    PostOutcomeEvent,
    SdkV2BindingConfig,
    SdkV2LifecycleAdapter,
    ToolRefused,
)

from harness import build_governed_test_app, call_tool, error_result, ok_result


def _ctx(request_id: str = "req-1"):
    return SimpleNamespace(method="tools/call", request_id=request_id, meta=None)


def _params(name: str, arguments: dict[str, Any] | None = None) -> mcp_types.CallToolRequestParams:
    return mcp_types.CallToolRequestParams(name=name, arguments=arguments or {})


class _RaisingSink:
    """A receipt sink that always fails to write."""

    def write(self, envelope):
        raise RuntimeError("sink unavailable")


# --------------------------------------------------------------------------- #
# No hook configured -> byte-identical behavior                              #
# --------------------------------------------------------------------------- #


def test_no_hook_configured_is_byte_identical_to_base_behavior(tmp_path):
    dt = build_governed_test_app(tmp_path, tool_bodies={"echo": lambda args: ok_result("hi")})
    assert dt.adapter.config.post_outcome_hook is None
    with dt.client() as client:
        resp = call_tool(client, "echo", {"text": "hi"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["resultType"] == "complete"
    assert body["result"]["isError"] is False
    assert dt.delegates["echo"].call_count == 1
    assert len(dt.admission_receipts()) == 1
    assert dt.admission_receipts()[0]["disposition"] == "admitted"
    assert len(dt.outcome_receipts()) == 1
    assert dt.outcome_receipts()[0]["outcome"] == "result_returned"
    assert dt.outcome_receipts()[0]["admission_receipt_ref"] == dt.admission_receipts()[0]["receipt_id"]
    # No local telemetry was ever recorded -- the seam is entirely inert when
    # unconfigured.
    assert dt.adapter.local_telemetry == []


# --------------------------------------------------------------------------- #
# Mechanical ordering proof (invariant 10)                                   #
# --------------------------------------------------------------------------- #


def test_ordering_delegate_then_outcome_write_then_hook_then_return(tmp_path):
    events: list[str] = []

    identity = SigningIdentity.generate(issuer_id="issuer:ordering", key_id="issuer.ordering/key/1")
    real_sink = RawEnvelopeFileSink(tmp_path / "ordering")

    class _RecordingSink:
        def write(self, envelope):
            ref = real_sink.write(envelope)
            if envelope["receipt_kind"] == "outcome":
                events.append(f"outcome_write:{ref}")
            return ref

    emitter = SignedReceiptEmitter(identity=identity, sink=_RecordingSink())

    def hook(event: PostOutcomeEvent) -> None:
        events.append(f"hook:{event.outcome_receipt_ref}")

    config = SdkV2BindingConfig(
        runtime_instance_id="rt", boundary_id="b", policy_pack_id="p", policy_pack_version="1",
        tool_classes={"echo": "read"},
        post_outcome_hook=hook,
    )
    adapter = SdkV2LifecycleAdapter(emitter=emitter, config=config)

    async def delegate(args):
        events.append("delegate")
        return ok_result("hi")

    result = asyncio.run(adapter.governed_call_tool(_ctx(), _params("echo"), delegate))
    events.append("return")

    assert result.is_error is False
    assert len(events) == 4
    assert events[0] == "delegate"
    assert events[1].startswith("outcome_write:")
    assert events[2].startswith("hook:")
    assert events[3] == "return"
    # The hook saw the exact ref string the outcome write produced.
    assert events[1].split(":", 1)[1] == events[2].split(":", 1)[1]


def test_ordering_exactly_once_per_completed_governed_execution(tmp_path):
    calls: list[PostOutcomeEvent] = []

    identity = SigningIdentity.generate(issuer_id="issuer:once", key_id="issuer.once/key/1")
    sink = RawEnvelopeFileSink(tmp_path / "once")
    emitter = SignedReceiptEmitter(identity=identity, sink=sink)

    def hook(event: PostOutcomeEvent) -> None:
        calls.append(event)

    config = SdkV2BindingConfig(
        runtime_instance_id="rt", boundary_id="b", policy_pack_id="p", policy_pack_version="1",
        tool_classes={"echo": "read"},
        post_outcome_hook=hook,
    )
    adapter = SdkV2LifecycleAdapter(emitter=emitter, config=config)

    async def delegate(args):
        return ok_result("hi")

    for i in range(3):
        asyncio.run(adapter.governed_call_tool(_ctx(request_id=f"req-{i}"), _params("echo"), delegate))

    assert len(calls) == 3
    assert len({c.outcome_receipt_ref for c in calls}) == 3  # each call got a distinct ref


# --------------------------------------------------------------------------- #
# Exact ref / payload content                                                #
# --------------------------------------------------------------------------- #


def test_hook_receives_exact_outcome_ref_and_admission_ref_and_payload(tmp_path):
    seen: list[PostOutcomeEvent] = []

    dt = build_governed_test_app(
        tmp_path,
        tool_bodies={"echo": lambda args: ok_result("hi")},
        post_outcome_hook=lambda event: seen.append(event),
    )
    with dt.client() as client:
        resp = call_tool(client, "echo", {"text": "payload"})
    assert resp.status_code == 200

    assert len(seen) == 1
    event = seen[0]
    admission = dt.admission_receipts()[0]
    outcome = dt.outcome_receipts()[0]
    assert event.admission_receipt_ref == admission["receipt_id"]
    assert event.outcome_receipt_ref == outcome["receipt_id"]
    assert event.tool_name == "echo"
    assert dict(event.arguments) == {"text": "payload"}
    assert event.delegate_result is not None
    assert event.receipt_context.logical_call_id == admission["logical_call_id"]
    assert event.result_digest == outcome.get("result_digest")


def test_hook_receives_correct_result_digest_for_error_result(tmp_path):
    seen: list[PostOutcomeEvent] = []
    dt = build_governed_test_app(
        tmp_path,
        tool_bodies={"fail": lambda args: error_result("nope")},
        post_outcome_hook=lambda event: seen.append(event),
    )
    with dt.client() as client:
        call_tool(client, "fail", {})
    assert len(seen) == 1
    outcome = dt.outcome_receipts()[0]
    assert seen[0].result_digest == outcome["result_digest"]
    assert seen[0].result_digest is not None


# --------------------------------------------------------------------------- #
# No callback on non-completed-outcome paths                                 #
# --------------------------------------------------------------------------- #


def test_no_callback_on_admission_refusal(tmp_path):
    calls: list[PostOutcomeEvent] = []
    dt = build_governed_test_app(
        tmp_path,
        tool_bodies={"echo": lambda args: ok_result("should never run")},
        post_outcome_hook=lambda event: calls.append(event),
    )
    with dt.client() as client:
        resp = call_tool(client, "nonexistent-tool", {})
    body = resp.json()
    assert "error" in body
    assert dt.delegates["echo"].call_count == 0
    assert calls == []


def test_no_callback_on_admission_receipt_failure_fail_closed(tmp_path):
    identity = SigningIdentity.generate(issuer_id="issuer:sinkfail", key_id="issuer.sinkfail/key/1")
    emitter = SignedReceiptEmitter(identity=identity, sink=_RaisingSink())
    calls: list[PostOutcomeEvent] = []
    config = SdkV2BindingConfig(
        runtime_instance_id="rt", boundary_id="b", policy_pack_id="p", policy_pack_version="1",
        tool_classes={"write_tool": "write"},  # write defaults to fail_closed
        post_outcome_hook=lambda event: calls.append(event),
    )
    adapter = SdkV2LifecycleAdapter(emitter=emitter, config=config)
    delegate_calls = []

    async def delegate(args):
        delegate_calls.append(args)
        return ok_result()

    with pytest.raises(ToolRefused):
        asyncio.run(adapter.governed_call_tool(_ctx(), _params("write_tool"), delegate))

    assert delegate_calls == []  # delegate never ran
    assert calls == []
    assert len(adapter.local_telemetry) == 1
    assert adapter.local_telemetry[0]["attempted_receipt_kind"] == "admission"


def test_no_callback_on_input_required(tmp_path):
    calls: list[PostOutcomeEvent] = []

    async def paused(_args):
        return mcp_types.InputRequiredResult(request_state="opaque-continuation-token")

    dt = build_governed_test_app(
        tmp_path,
        tool_bodies={"paused_tool": paused},
        post_outcome_hook=lambda event: calls.append(event),
    )
    with dt.client() as client:
        resp = call_tool(client, "paused_tool", {})
    body = resp.json()
    assert "error" in body
    assert len(dt.admission_receipts()) == 1
    assert len(dt.outcome_receipts()) == 0
    assert calls == []


# --------------------------------------------------------------------------- #
# Callback failure is post-execution only                                    #
# --------------------------------------------------------------------------- #


def test_callback_raising_result_still_returned_telemetry_recorded_no_rewrite(tmp_path):
    def raising_hook(event: PostOutcomeEvent) -> None:
        raise RuntimeError("consumer composition failed")

    dt = build_governed_test_app(
        tmp_path,
        tool_bodies={"echo": lambda args: ok_result("hi")},
        post_outcome_hook=raising_hook,
    )
    with dt.client() as client:
        resp = call_tool(client, "echo", {"text": "hi"})

    # The result is still returned to the caller, unchanged.
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["resultType"] == "complete"
    assert body["result"]["isError"] is False
    assert dt.delegates["echo"].call_count == 1

    # The durable outcome receipt already written is never rewritten, deleted,
    # or replaced with a fabricated ref -- exactly one outcome receipt exists,
    # unchanged in shape.
    outcome_receipts = dt.outcome_receipts()
    assert len(outcome_receipts) == 1
    assert outcome_receipts[0]["outcome"] == "result_returned"

    # Local telemetry recorded the callback failure distinctly from an
    # admission/outcome receipt-write failure.
    assert len(dt.adapter.local_telemetry) == 1
    assert dt.adapter.local_telemetry[0]["attempted_receipt_kind"] == "post_outcome_hook"
    assert dt.adapter.local_telemetry[0]["failure_class"] == "RuntimeError"


def test_async_hook_is_awaited_and_can_also_raise(tmp_path):
    calls: list[PostOutcomeEvent] = []

    async def async_hook(event: PostOutcomeEvent) -> None:
        calls.append(event)

    dt = build_governed_test_app(
        tmp_path,
        tool_bodies={"echo": lambda args: ok_result("hi")},
        post_outcome_hook=async_hook,
    )
    with dt.client() as client:
        resp = call_tool(client, "echo", {"text": "hi"})
    assert resp.status_code == 200
    assert len(calls) == 1
    assert dt.adapter.local_telemetry == []

    async def async_raising_hook(event: PostOutcomeEvent) -> None:
        raise ValueError("async composition failed")

    dt2 = build_governed_test_app(
        tmp_path / "second",
        tool_bodies={"echo": lambda args: ok_result("hi")},
        post_outcome_hook=async_raising_hook,
    )
    with dt2.client() as client:
        resp2 = call_tool(client, "echo", {"text": "hi"})
    assert resp2.status_code == 200
    assert resp2.json()["result"]["isError"] is False
    assert len(dt2.outcome_receipts()) == 1
    assert len(dt2.adapter.local_telemetry) == 1
    assert dt2.adapter.local_telemetry[0]["attempted_receipt_kind"] == "post_outcome_hook"
    assert dt2.adapter.local_telemetry[0]["failure_class"] == "ValueError"
