"""``SdkV2BindingConfig.mint_logical_call_id`` -- explicit opt-in per-invocation
binding-minted call identity (SDKV2-CALLID-MINT0).

This flag is additive, opt-in, and off by default. It lets an operator ask the
``official-mcp-sdk.python.v0.2`` binding to mint a fresh opaque
``call:<uuid4()>`` logical call id for *every* governed ``tools/call``
invocation, even when the trusted request context already carries a
``request_id`` that would otherwise be reused as the correlation reference.
Identity minting stays binding-owned: no operator callable, factory,
timestamp, counter, or model-supplied value ever participates (see
``SdkV2LifecycleAdapter._receipt_context``).

These tests establish:

* default behavior (flag ``False``) is byte-for-byte unchanged -- including
  the pre-existing ``request:0`` falsy-but-not-None edge case;
* with the flag on, two separate invocations that share the same
  ``request_id`` mint two *different* logical call ids;
* one governed invocation mints exactly once -- its admission and outcome
  receipts carry the identical minted id, because both are built from the one
  ``ReceiptContext`` constructed at the top of ``governed_call_tool``;
* ``subject_ref``/``subject_ref_origin`` semantics are preserved exactly: a
  ``subject_ref_override`` always wins regardless of minting, and minting
  (with no override) always declares the existing ``binding_minted`` token,
  never a new vocabulary value;
* ``logical_call_id_override`` and ``mint_logical_call_id=True`` are
  conflicting operator instructions and fail closed at construction time;
* the minted id shape is exactly ``call:`` followed by a parseable UUID, with
  nothing else (no timestamp, no counter, no argument/request content) baked
  into it;
* tool admission/refusal, result-digest, and outcome-vocabulary behavior are
  identical whether or not the flag is set.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from dagr_mcp_core.srs_receipts import RawEnvelopeFileSink, SignedReceiptEmitter, SigningIdentity
from dagr_mcp_sdk_v2.adapter import ActorResolution, SdkV2BindingConfig, SdkV2LifecycleAdapter

from harness import build_governed_test_app, call_tool, error_result, ok_result


def _adapter(**overrides) -> SdkV2LifecycleAdapter:
    config = SdkV2BindingConfig(
        runtime_instance_id="rt:v2-mint",
        boundary_id="b:v2-mint",
        policy_pack_id="p:v2-mint",
        policy_pack_version="1",
        **overrides,
    )
    return SdkV2LifecycleAdapter(emitter=None, config=config)  # type: ignore[arg-type]


def _ctx(request_id: object | None):
    return SimpleNamespace(request_id=request_id)


# --------------------------------------------------------------------------- #
# 1. Default unchanged                                                        #
# --------------------------------------------------------------------------- #


def test_default_flag_false_request_id_zero_still_yields_request_zero():
    """The falsy-but-not-None ``request_id=0`` edge case must survive
    untouched: ``0 is not None`` so ``request_ref`` is truthy, and the
    default-False flag never intervenes."""

    ctx = _adapter()._receipt_context(_ctx(0), ActorResolution())
    assert ctx.logical_call_id == "request:0"
    assert ctx.subject_ref == "request:0"
    assert ctx.subject_ref_origin == "derived_from_request"


# --------------------------------------------------------------------------- #
# 2. Flag true mints regardless of request_id                                 #
# --------------------------------------------------------------------------- #


def test_mint_true_request_id_zero_mints_a_fresh_call_id():
    ctx = _adapter(mint_logical_call_id=True)._receipt_context(_ctx(0), ActorResolution())
    assert ctx.logical_call_id.startswith("call:")
    minted_uuid = ctx.logical_call_id.removeprefix("call:")
    assert uuid.UUID(minted_uuid)  # parses without raising


# --------------------------------------------------------------------------- #
# 3. Two separate calls, same request_id, flag true => different ids          #
# --------------------------------------------------------------------------- #


def test_mint_true_two_invocations_same_request_id_differ():
    adapter = _adapter(mint_logical_call_id=True)
    first = adapter._receipt_context(_ctx(0), ActorResolution())
    second = adapter._receipt_context(_ctx(0), ActorResolution())
    assert first.logical_call_id != second.logical_call_id


def test_mint_true_two_http_invocations_same_request_id_differ(tmp_path):
    """Two genuine governed HTTP calls that both use JSON-RPC request id 1
    (a fresh TestClient POST each time, same ``id`` on the wire) mint two
    distinct logical call ids -- proven at real admission receipts, not just
    inside the adapter."""

    dt = build_governed_test_app(
        tmp_path, tool_bodies={"echo": lambda args: ok_result("hi")}, mint_logical_call_id=True
    )
    with dt.client() as client:
        call_tool(client, "echo", {}, request_id=1)
        call_tool(client, "echo", {}, request_id=1)
    admissions = dt.admission_receipts()
    assert len(admissions) == 2
    ids = {r["logical_call_id"] for r in admissions}
    assert len(ids) == 2
    for call_id in ids:
        assert call_id.startswith("call:")


# --------------------------------------------------------------------------- #
# 4. Admission/outcome pair from one invocation share the same id             #
# --------------------------------------------------------------------------- #


def test_mint_true_admission_and_outcome_share_one_minted_id(tmp_path):
    dt = build_governed_test_app(
        tmp_path, tool_bodies={"echo": lambda args: ok_result("hi")}, mint_logical_call_id=True
    )
    with dt.client() as client:
        call_tool(client, "echo", {}, request_id=7)
    admissions = dt.admission_receipts()
    outcomes = dt.outcome_receipts()
    assert len(admissions) == 1
    assert len(outcomes) == 1
    assert admissions[0]["logical_call_id"] == outcomes[0]["logical_call_id"]
    assert admissions[0]["logical_call_id"].startswith("call:")
    # outcome pairing is via admission_receipt_ref, not logical_call_id
    assert outcomes[0]["admission_receipt_ref"] == admissions[0]["receipt_id"]


# --------------------------------------------------------------------------- #
# 5/6. subject_ref / subject_ref_origin preserved exactly                     #
# --------------------------------------------------------------------------- #


def test_subject_override_wins_over_minting():
    ctx = _adapter(
        subject_ref_override="subject:operator:supplied", mint_logical_call_id=True
    )._receipt_context(_ctx(0), ActorResolution())
    assert ctx.subject_ref == "subject:operator:supplied"
    assert ctx.subject_ref_origin == "supplied_subject"
    # logical_call_id is still freshly minted even though subject is overridden.
    assert ctx.logical_call_id.startswith("call:")


def test_no_subject_override_mint_true_derives_from_minted_id_binding_minted_origin():
    ctx = _adapter(mint_logical_call_id=True)._receipt_context(_ctx(0), ActorResolution())
    assert ctx.subject_ref == f"tool-call:{ctx.logical_call_id}"
    assert ctx.subject_ref_origin == "binding_minted"


def test_no_subject_override_mint_true_wins_over_request_ref_for_subject_too():
    """Not just logical_call_id -- the subject derivation must also prefer the
    minted id over reusing the request reference when the flag is set."""

    ctx = _adapter(mint_logical_call_id=True)._receipt_context(_ctx("req-9"), ActorResolution())
    assert ctx.subject_ref != "request:req-9"
    assert ctx.subject_ref == f"tool-call:{ctx.logical_call_id}"
    assert ctx.subject_ref_origin == "binding_minted"


# --------------------------------------------------------------------------- #
# 7. No request id + flag false => existing fallback (binding_minted) intact  #
# --------------------------------------------------------------------------- #


def test_no_request_id_flag_false_existing_fallback_unchanged():
    ctx = _adapter()._receipt_context(_ctx(None), ActorResolution())
    assert ctx.logical_call_id.startswith("call:")
    assert ctx.subject_ref == f"tool-call:{ctx.logical_call_id}"
    assert ctx.subject_ref_origin == "binding_minted"


# --------------------------------------------------------------------------- #
# 8/9. Conflict validation, fail-closed at construction                       #
# --------------------------------------------------------------------------- #


def test_override_and_mint_true_together_fails_closed_at_construction():
    with pytest.raises(ValueError):
        SdkV2BindingConfig(
            runtime_instance_id="rt",
            boundary_id="b",
            policy_pack_id="p",
            policy_pack_version="1",
            logical_call_id_override="call:operator:supplied",
            mint_logical_call_id=True,
        )


def test_override_alone_mint_false_existing_behavior_unchanged():
    ctx = _adapter(logical_call_id_override="call:operator:supplied")._receipt_context(
        _ctx(None), ActorResolution()
    )
    assert ctx.logical_call_id == "call:operator:supplied"
    assert ctx.subject_ref == "tool-call:call:operator:supplied"
    assert ctx.subject_ref_origin == "derived_from_supplied_correlation"


# --------------------------------------------------------------------------- #
# 10/11. Minted id shape: exactly call:<uuid>, no extra content               #
# --------------------------------------------------------------------------- #


def test_minted_id_shape_is_exactly_call_prefix_plus_parseable_uuid():
    ctx = _adapter(mint_logical_call_id=True)._receipt_context(_ctx(123), ActorResolution())
    assert ctx.logical_call_id.count(":") == 1
    prefix, _, tail = ctx.logical_call_id.partition(":")
    assert prefix == "call"
    parsed = uuid.UUID(tail)
    assert str(parsed) == tail  # canonical hyphenated form, nothing appended


def test_minted_id_uses_the_production_uuid4_path_deterministically_patched():
    """Production uses ``uuid.uuid4()``; patch it to prove the minting call
    site is exactly that -- no timestamp/counter/request-argument content
    contributes to the id."""

    fixed = uuid.UUID("00000000-0000-4000-8000-000000000000")
    with patch("dagr_mcp_sdk_v2.adapter.uuid.uuid4", return_value=fixed):
        ctx = _adapter(mint_logical_call_id=True)._receipt_context(
            _ctx("req-should-not-appear"), ActorResolution()
        )
    assert ctx.logical_call_id == f"call:{fixed}"
    assert "req-should-not-appear" not in ctx.logical_call_id


# --------------------------------------------------------------------------- #
# 12/13/14/15/16/17/18. Unrelated lifecycle semantics unchanged with flag on  #
# --------------------------------------------------------------------------- #


def test_admission_and_refusal_semantics_unchanged_with_mint_true(tmp_path):
    dt = build_governed_test_app(
        tmp_path,
        tool_bodies={"echo": lambda args: ok_result("hi")},
        mint_logical_call_id=True,
    )
    with dt.client() as client:
        resp = call_tool(client, "echo", {})
    assert resp.status_code == 200
    assert dt.admission_receipts()[0]["disposition"] == "admitted"


def test_unknown_tool_fails_closed_with_mint_true(tmp_path):
    dt = build_governed_test_app(
        tmp_path, tool_bodies={"echo": lambda args: ok_result("hi")}, mint_logical_call_id=True
    )
    with dt.client() as client:
        resp = call_tool(client, "nope", {})
    body = resp.json()
    assert "error" in body
    admissions = dt.admission_receipts()
    assert len(admissions) == 1
    assert admissions[0]["disposition"] == "refused"
    assert admissions[0]["reason_code"] == "unknown_tool_fail_closed"


def test_error_result_digest_and_outcome_vocabulary_unchanged_with_mint_true(tmp_path):
    dt = build_governed_test_app(
        tmp_path, tool_bodies={"fail": lambda args: error_result("nope")}, mint_logical_call_id=True
    )
    with dt.client() as client:
        resp = call_tool(client, "fail", {})
    body = resp.json()["result"]
    assert body["isError"] is True
    outcomes = dt.outcome_receipts()
    assert outcomes[0]["outcome"] == "error_returned"
    assert "result_digest" in outcomes[0]


def test_delegate_raises_exception_outcome_unchanged_with_mint_true(tmp_path):
    def _boom(_args):
        raise ValueError("kaboom")

    dt = build_governed_test_app(tmp_path, tool_bodies={"boom": _boom}, mint_logical_call_id=True)
    with dt.client() as client:
        call_tool(client, "boom", {})
    outcomes = dt.outcome_receipts()
    assert outcomes[0]["outcome"] == "exception"
    assert outcomes[0]["extensions"]["mcp"]["exception_class"] == "ValueError"
