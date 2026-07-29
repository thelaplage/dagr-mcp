"""The v0.2 governed-binding acceptance matrix (all 10 required rows).

Rows that exercise the common, happy-ish paths (admitted/success, refused,
is_error, delegate-raises, unknown-tool) run through the REAL stateless
Streamable HTTP (2026-07-28) app -- the full ``mcp==2.0.0`` ASGI stack, via
``harness.py`` -- so admission-before-dispatch and delegate-invocation-count
are proven at the transport boundary, not just inside the adapter.

Rows that need precise failure injection (admission/outcome sink failure,
``input_required``, cancellation before/during delegate) call
``adapter.governed_call_tool`` directly with a minimal duck-typed context
object. The adapter only reads ``ctx.method`` and (via ``getattr``)
``ctx.request_id`` -- it never touches session/transport internals -- so a
``types.SimpleNamespace`` stand-in is a faithful substitute for these rows and
avoids depending on ``asyncio.CancelledError`` propagating correctly through
TestClient's portal/anyio task-group machinery, which is not what these rows
are trying to prove.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from mcp import types as mcp_types

from dagr_mcp_core.srs_receipts import RawEnvelopeFileSink, SignedReceiptEmitter, SigningIdentity
from dagr_mcp_sdk_v2.adapter import (
    InputRequiredUnsupported,
    SdkV2BindingConfig,
    SdkV2LifecycleAdapter,
    ToolRefused,
)

from harness import build_governed_test_app, call_tool, error_result, ok_result

# --------------------------------------------------------------------------- #
# Rows proven end-to-end over the real stateless HTTP app                     #
# --------------------------------------------------------------------------- #


def test_row_admitted_successful_complete_result(tmp_path):
    dt = build_governed_test_app(tmp_path, tool_bodies={"echo": lambda args: ok_result("hi")})
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


def test_row_admitted_tool_returns_is_error(tmp_path):
    dt = build_governed_test_app(tmp_path, tool_bodies={"fail": lambda args: error_result("nope")})
    with dt.client() as client:
        resp = call_tool(client, "fail", {})
    assert resp.status_code == 200
    body = resp.json()["result"]
    assert body["isError"] is True
    assert dt.delegates["fail"].call_count == 1
    assert len(dt.admission_receipts()) == 1
    assert len(dt.outcome_receipts()) == 1
    assert dt.outcome_receipts()[0]["outcome"] == "error_returned"
    assert "result_digest" in dt.outcome_receipts()[0]


def test_row_admitted_delegate_raises(tmp_path):
    def _boom(_args):
        raise ValueError("kaboom")

    dt = build_governed_test_app(tmp_path, tool_bodies={"boom": _boom})
    with dt.client() as client:
        resp = call_tool(client, "boom", {})
    # The exception propagates as an MCP-level error, not a 200 isError result.
    assert resp.status_code != 200 or "error" in resp.json()
    assert dt.delegates["boom"].call_count == 1
    assert len(dt.admission_receipts()) == 1
    assert len(dt.outcome_receipts()) == 1
    outcome = dt.outcome_receipts()[0]
    assert outcome["outcome"] == "exception"
    assert outcome["extensions"]["mcp"]["exception_class"] == "ValueError"
    assert "result_digest" not in outcome


def test_row_unknown_tool_no_unauthorized_dispatch(tmp_path):
    """Covers both the "refused" and "unknown tool" matrix rows.

    This adapter's only admission-time refusal path is tool-name
    classification (see ``adapter.py`` module docstring: any name absent from
    ``tool_classes`` refuses on ``unknown_tool_fail_closed``), so both rows
    share this one assertion shape: no dispatch, one refusal admission
    receipt, no outcome receipt.
    """

    dt = build_governed_test_app(tmp_path, tool_bodies={"echo": lambda args: ok_result()})
    with dt.client() as client:
        resp = call_tool(client, "nonexistent-tool", {})
    assert dt.delegates["echo"].call_count == 0
    assert len(dt.admission_receipts()) == 1
    refusal = dt.admission_receipts()[0]
    assert refusal["disposition"] == "refused"
    assert refusal["reason_code"] == "unknown_tool_fail_closed"
    assert len(dt.outcome_receipts()) == 0
    body = resp.json()
    assert "error" in body


# --------------------------------------------------------------------------- #
# Rows proven via direct adapter injection                                    #
# --------------------------------------------------------------------------- #


def _identity_emitter(tmp_path, name="direct"):
    identity = SigningIdentity.generate(issuer_id=f"issuer:{name}", key_id=f"issuer.{name}/key/1")
    sink = RawEnvelopeFileSink(tmp_path / name)
    return SignedReceiptEmitter(identity=identity, sink=sink), tmp_path / name


def _ctx(request_id: str = "req-1"):
    return SimpleNamespace(method="tools/call", request_id=request_id, meta=None)


def _params(name: str, arguments: dict[str, Any] | None = None) -> mcp_types.CallToolRequestParams:
    return mcp_types.CallToolRequestParams(name=name, arguments=arguments or {})


class _RaisingSink:
    """A receipt sink that always fails to write."""

    def write(self, envelope):
        raise RuntimeError("sink unavailable")


class _FlakyAfterFirstSink:
    """Writes the first N envelopes normally, then fails every write after."""

    def __init__(self, real_sink, succeed_first: int):
        self._real = real_sink
        self._succeed_first = succeed_first
        self._count = 0

    def write(self, envelope):
        self._count += 1
        if self._count <= self._succeed_first:
            return self._real.write(envelope)
        raise RuntimeError("sink unavailable after first write")


def test_row_admission_sink_fails(tmp_path):
    identity = SigningIdentity.generate(issuer_id="issuer:sinkfail", key_id="issuer.sinkfail/key/1")
    emitter = SignedReceiptEmitter(identity=identity, sink=_RaisingSink())
    config = SdkV2BindingConfig(
        runtime_instance_id="rt", boundary_id="b", policy_pack_id="p", policy_pack_version="1",
        tool_classes={"write_tool": "write"},  # write defaults to fail_closed
    )
    adapter = SdkV2LifecycleAdapter(emitter=emitter, config=config)
    calls = []

    async def delegate(args):
        calls.append(args)
        return ok_result()

    with pytest.raises(ToolRefused):
        asyncio.run(adapter.governed_call_tool(_ctx(), _params("write_tool"), delegate))

    assert calls == []  # delegate never ran
    assert len(adapter.local_telemetry) == 1
    assert adapter.local_telemetry[0]["attempted_receipt_kind"] == "admission"


def test_row_outcome_sink_fails(tmp_path):
    real_sink = RawEnvelopeFileSink(tmp_path / "outcome-fail")
    identity = SigningIdentity.generate(issuer_id="issuer:outcomefail", key_id="issuer.outcomefail/key/1")
    flaky = _FlakyAfterFirstSink(real_sink, succeed_first=1)  # admission write succeeds, outcome write fails
    emitter = SignedReceiptEmitter(identity=identity, sink=flaky)
    config = SdkV2BindingConfig(
        runtime_instance_id="rt", boundary_id="b", policy_pack_id="p", policy_pack_version="1",
        tool_classes={"echo": "read"},
    )
    adapter = SdkV2LifecycleAdapter(emitter=emitter, config=config)

    async def delegate(args):
        return ok_result()

    result = asyncio.run(adapter.governed_call_tool(_ctx(), _params("echo"), delegate))
    # The bounded post-execution custody failure: the semantic result is still
    # returned to the caller (delegate already ran and cannot be undone), but
    # no outcome receipt exists and the failure is recorded in telemetry.
    assert result.is_error is False
    admission_files = list((tmp_path / "outcome-fail").glob("*.json"))
    assert len(admission_files) == 1  # only the admission receipt was durably written
    assert any(e["attempted_receipt_kind"] == "outcome" for e in adapter.local_telemetry)


def test_row_input_required_fails_closed_no_misleading_outcome(tmp_path):
    emitter, directory = _identity_emitter(tmp_path, "input-required")
    config = SdkV2BindingConfig(
        runtime_instance_id="rt", boundary_id="b", policy_pack_id="p", policy_pack_version="1",
        tool_classes={"paused": "read"},
    )
    adapter = SdkV2LifecycleAdapter(emitter=emitter, config=config)

    async def delegate(args):
        return mcp_types.InputRequiredResult(request_state="opaque-state")

    with pytest.raises(InputRequiredUnsupported):
        asyncio.run(adapter.governed_call_tool(_ctx(), _params("paused"), delegate))

    receipts = [__import__("json").loads(p.read_text()) for p in directory.glob("*.json")]
    admission = [r for r in receipts if r["receipt_kind"] == "admission"]
    outcome = [r for r in receipts if r["receipt_kind"] == "outcome"]
    assert len(admission) == 1  # one proceed, admission already emitted before dispatch
    assert len(outcome) == 0  # no misleading complete outcome


def test_row_cancellation_before_delegate_never_runs(tmp_path):
    """Cancellation between admission decision and delegate invocation.

    ``asyncio.CancelledError`` is a ``BaseException`` in modern Python, so the
    adapter's ``except Exception`` around admission-receipt emission does NOT
    catch it -- it propagates immediately, and the delegate is never reached.
    Simulated here by having the sink itself raise CancelledError from
    ``write()``, exactly at the point admission emission would occur.
    """

    class _CancellingSink:
        def write(self, envelope):
            raise asyncio.CancelledError()

    identity = SigningIdentity.generate(issuer_id="issuer:cancel-before", key_id="issuer.cancel-before/key/1")
    emitter = SignedReceiptEmitter(identity=identity, sink=_CancellingSink())
    config = SdkV2BindingConfig(
        runtime_instance_id="rt", boundary_id="b", policy_pack_id="p", policy_pack_version="1",
        tool_classes={"echo": "read"},
    )
    adapter = SdkV2LifecycleAdapter(emitter=emitter, config=config)
    calls = []

    async def delegate(args):
        calls.append(args)
        return ok_result()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(adapter.governed_call_tool(_ctx(), _params("echo"), delegate))
    assert calls == []


def test_row_cancellation_during_delegate(tmp_path):
    emitter, directory = _identity_emitter(tmp_path, "cancel-during")
    config = SdkV2BindingConfig(
        runtime_instance_id="rt", boundary_id="b", policy_pack_id="p", policy_pack_version="1",
        tool_classes={"echo": "read"},
    )
    adapter = SdkV2LifecycleAdapter(emitter=emitter, config=config)
    calls = []

    async def delegate(args):
        calls.append(args)
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(adapter.governed_call_tool(_ctx(), _params("echo"), delegate))

    assert len(calls) == 1  # at most once (exactly once here)
    receipts = [__import__("json").loads(p.read_text()) for p in directory.glob("*.json")]
    admission = [r for r in receipts if r["receipt_kind"] == "admission"]
    outcome = [r for r in receipts if r["receipt_kind"] == "outcome"]
    assert len(admission) == 1
    assert len(outcome) == 1
    assert outcome[0]["outcome"] == "indeterminate"
    assert outcome[0]["request_cancelled"] is True
    assert outcome[0]["execution_state_unknown"] is True
    assert outcome[0]["delivery_incomplete"] is True
    assert "result_digest" not in outcome[0]
