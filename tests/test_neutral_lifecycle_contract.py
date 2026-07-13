"""Sprint A2 — neutral MCP lifecycle contract and binding mask.

These tests pin the binding-neutral lifecycle vocabulary
(:mod:`dagr_mcp_lifecycle.contract`) and prove the FastMCP binding mask
(:mod:`dagr_mcp_lifecycle.binding_mask`) *describes the binding faithfully*.

The external FastMCP binding remains the oracle. Every mask claim is grounded
either against a live emitter run or against the Sprint A1 committed
behavioral-freeze fixtures, which are regenerated deterministically here. The
mask never normalizes or repairs the binding; where the binding has no dedicated
observation for a neutral event (``timeout``, ``input_required``), the mask says
so, and these tests confirm it against the binding's actual behavior.

Nothing here emits into production paths, moves binding code, or introduces a
second binding.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dagr_mcp import fastmcp_binding, srs_receipts
from dagr_mcp.srs_receipts import (
    RawEnvelopeFileSink,
    ReceiptContentError,
    ReceiptContext,
    SignedReceiptEmitter,
    fastmcp_tool_result_digest,
    sha256_digest,
)
from dagr_mcp.fastmcp_binding import project_fastmcp_tool_result
from dagr_mcp.mcp_record_custody_gateway import (
    GatewayBoundaryType,
    GatewayCustodyStatus,
    GatewayReceiptFamily,
)

from dagr_mcp_lifecycle import binding_mask, contract

from tests.behavioral_freeze_recipe import (
    FREEZE_ADMISSION_ID,
    FREEZE_ARGUMENT_DIGEST,
    FREEZE_BOUNDARY_LIMIT,
    freeze_identity,
    generate_frozen_receipts,
)

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests/golden/behavioral_freeze"


def _committed(name: str) -> dict[str, Any]:
    return json.loads((GOLDEN / name).read_text(encoding="utf-8"))


_GOLDEN_BY_NAME = {
    "admission-admitted": "urn_srs_receipt_admission_freeze-admitted.json",
    "admission-refused": "urn_srs_receipt_admission_freeze-refused.json",
    "admission-deferred": "urn_srs_receipt_admission_freeze-deferred.json",
    "outcome-result-returned": "urn_srs_receipt_outcome_freeze-result-returned.json",
    "outcome-error-returned": "urn_srs_receipt_outcome_freeze-error-returned.json",
    "outcome-exception": "urn_srs_receipt_outcome_freeze-exception.json",
    "outcome-task-submitted": "urn_srs_receipt_outcome_freeze-task-submitted.json",
    "outcome-indeterminate": "urn_srs_receipt_outcome_freeze-indeterminate.json",
}


def _golden(name: str) -> dict[str, Any]:
    return _committed(_GOLDEN_BY_NAME[name])


# --------------------------------------------------------------------------- #
# Drift guard — the mask must agree with the live binding oracle              #
# --------------------------------------------------------------------------- #


def test_mask_matches_binding_oracle():
    # Raises AssertionError on any drift from the live binding modules.
    binding_mask.verify_mask_matches_binding()


def test_neutral_vocabulary_is_frozen():
    assert contract.CONTRACT_ID == "dagr.mcp.lifecycle_contract"
    assert contract.CONTRACT_VERSION == "v0.1"
    assert contract.NEUTRAL_DISPOSITIONS == ("admitted", "refused", "deferred")
    assert contract.NEUTRAL_OUTCOMES == (
        "result",
        "error",
        "exception",
        "task_submitted",
        "timeout",
        "cancellation",
        "input_required",
    )
    assert contract.INPUT_REQUIRED_MODES == ("continuable", "interrupted")
    assert contract.NEUTRAL_CANCELLATION_FACTS == (
        "request_cancelled",
        "execution_state_unknown",
        "delivery_incomplete",
    )
    assert contract.PARITY_LAYERS == (
        "semantic",
        "normalized_equality",
        "exact_unsigned_bytes",
    )
    # The neutral event catalogue names every phase exactly.
    phases = {e.phase for e in contract.NEUTRAL_LIFECYCLE_EVENTS}
    assert phases == set(contract.LIFECYCLE_PHASES)


# --------------------------------------------------------------------------- #
# Call admission and dispositions                                             #
# --------------------------------------------------------------------------- #


def test_call_admission_dispositions_map_to_binding():
    # The mask's direct disposition tokens are exactly the binding's Literal.
    import typing

    live = set(typing.get_args(fastmcp_binding.Disposition))
    assert {binding_mask.project_disposition(n) for n in contract.NEUTRAL_DISPOSITIONS} == live

    # Grounded against the committed admission goldens.
    assert _golden("admission-admitted")["disposition"] == binding_mask.project_disposition("admitted")
    assert _golden("admission-refused")["disposition"] == binding_mask.project_disposition("refused")
    assert _golden("admission-deferred")["disposition"] == binding_mask.project_disposition("deferred")

    # Admission never observes tool resolution.
    assert _golden("admission-admitted")["tool_resolution_status"] == "not_observed"


def test_refused_and_deferred_reason_and_continuation():
    # Every neutral refusal ground is masked to a binding reason_code.
    assert {e.neutral_token for e in binding_mask.REFUSAL_GROUND_MASK} == set(
        contract.NEUTRAL_REFUSAL_GROUNDS
    )
    # A refusal carries a reason_code; a deferral carries a review ref + retry.
    assert _golden("admission-refused")["reason_code"] == "policy_refused"
    deferred = _golden("admission-deferred")
    assert deferred["retry_contract"] == contract.DEFERRAL_CONTINUATION_CONTRACT
    assert deferred["review_object_ref"]
    assert "reason_code" not in deferred  # a deferral is not a refusal


def test_execution_start_and_completion_boundaries():
    assert contract.EXECUTION_BOUNDARIES == ("execution_start", "execution_completion")
    # Admission is the execution-start record; outcome is the completion record.
    assert _golden("admission-admitted")["receipt_kind"] == "admission"
    assert _golden("outcome-result-returned")["receipt_kind"] == "outcome"


# --------------------------------------------------------------------------- #
# Outcome mapping grounded in the live emitter                                #
# --------------------------------------------------------------------------- #


def test_outcome_tokens_grounded_in_live_emitter(tmp_path):
    frozen = {fr.name: fr.receipt for fr in generate_frozen_receipts(tmp_path)}
    live_outcomes = {
        fr["outcome"] for name, fr in frozen.items() if name.startswith("outcome-")
    }
    # The emitter stamps exactly the outcome tokens the mask declares.
    assert live_outcomes == binding_mask.BINDING_OUTCOME_TOKENS

    # Every direct/subsumed outcome maps onto one of those tokens.
    for entry in binding_mask.OUTCOME_MASK:
        if entry.status == "unsupported":
            assert entry.binding_token is None
        else:
            assert entry.binding_token in live_outcomes

    assert binding_mask.project_outcome("result").binding_token == "result_returned"
    assert binding_mask.project_outcome("error").binding_token == "error_returned"
    assert binding_mask.project_outcome("exception").binding_token == "exception"
    assert binding_mask.project_outcome("task_submitted").binding_token == "task_submitted"
    assert binding_mask.project_outcome("cancellation").binding_token == "indeterminate"


def test_result_task_exception_timeout_cancellation_details(tmp_path):
    frozen = {fr.name: fr.receipt for fr in generate_frozen_receipts(tmp_path)}

    # result / error carry a result digest; task / exception / indeterminate do not.
    assert frozen["outcome-result-returned"]["result_digest"].startswith("sha256:")
    assert frozen["outcome-error-returned"]["result_digest"].startswith("sha256:")
    assert "result_digest" not in frozen["outcome-task-submitted"]
    assert "result_digest" not in frozen["outcome-exception"]
    assert "result_digest" not in frozen["outcome-indeterminate"]

    # Timeout is SUBSUMED onto exception (no dedicated disposition): a raised
    # TimeoutError is recorded as outcome='exception' + exception_class.
    timeout_entry = binding_mask.project_outcome("timeout")
    assert timeout_entry.status == "subsumed"
    assert timeout_entry.binding_token == "exception"
    exc = frozen["outcome-exception"]
    assert exc["outcome"] == "exception"
    assert exc["extensions"]["mcp"]["exception_class"] == "TimeoutError"

    # Cancellation carries the three governance Booleans, all True, on indeterminate.
    indet = frozen["outcome-indeterminate"]
    assert indet["outcome"] == "indeterminate"
    for fact in contract.NEUTRAL_CANCELLATION_FACTS:
        assert indet[fact] is True


def test_input_required_is_unsupported():
    # Both neutral modes are unsupported by this binding.
    assert {e.neutral_token for e in binding_mask.INPUT_REQUIRED_MASK} == set(
        contract.INPUT_REQUIRED_MODES
    )
    assert all(e.status == "unsupported" for e in binding_mask.INPUT_REQUIRED_MASK)
    assert all(e.binding_token is None for e in binding_mask.INPUT_REQUIRED_MASK)

    entry = binding_mask.project_outcome("input_required")
    assert entry.status == "unsupported"
    assert entry.binding_token is None
    # The binding has no outcome token for a paused call.
    assert "input_required" not in binding_mask.BINDING_OUTCOME_TOKENS


# --------------------------------------------------------------------------- #
# Cancellation governance facts                                               #
# --------------------------------------------------------------------------- #


def test_cancellation_facts_map_and_are_constrained(tmp_path):
    masked = {
        e.binding_token for e in binding_mask.CANCELLATION_FACT_MASK if e.binding_token
    }
    assert masked == set(srs_receipts.CANCELLATION_FIELD_NAMES)
    # A0 rename holds: no result-shaped governance field survives.
    assert "delivery_incomplete" in masked
    assert not any("result" in name for name in masked)

    identity = freeze_identity()
    emitter = SignedReceiptEmitter(identity=identity, sink=RawEnvelopeFileSink(tmp_path))
    ctx = _admitted_context()

    # Indeterminate-only: a cancellation field on a non-indeterminate outcome is
    # refused before signing.
    with pytest.raises(ReceiptContentError, match="only on indeterminate"):
        emitter.emit_outcome(
            context=ctx,
            admission_receipt_ref=FREEZE_ADMISSION_ID,
            outcome="result_returned",
            result_digest="sha256:" + "d" * 64,
            binding_owned_fields={"request_cancelled": True},
        )
    # Boolean-only: a non-Boolean cancellation value is refused before signing.
    with pytest.raises(ReceiptContentError, match="must be boolean"):
        emitter.emit_outcome(
            context=ctx,
            admission_receipt_ref=FREEZE_ADMISSION_ID,
            outcome="indeterminate",
            binding_owned_fields={"delivery_incomplete": "no"},
        )


# --------------------------------------------------------------------------- #
# Receipt cardinality and parent/reference relationships                      #
# --------------------------------------------------------------------------- #


def test_receipt_cardinality_and_reference_edges():
    assert binding_mask.RECEIPT_CARDINALITY == {
        "admitted": 2,
        "refused": 1,
        "deferred": 1,
    }
    assert contract.RECEIPT_REFERENCE_EDGES == ("outcome_to_admission", "parent_reference")
    assert binding_mask.OUTCOME_TO_ADMISSION_FIELD == "admission_receipt_ref"

    # Every outcome record references the admitted admission record.
    admission_id = _golden("admission-admitted")["receipt_id"]
    assert admission_id == FREEZE_ADMISSION_ID
    for name in _GOLDEN_BY_NAME:
        if name.startswith("outcome-"):
            ref = _golden(name)[binding_mask.OUTCOME_TO_ADMISSION_FIELD]
            assert ref == admission_id


# --------------------------------------------------------------------------- #
# Custody observations and attestation limits                                 #
# --------------------------------------------------------------------------- #


def test_custody_non_claim_posture_and_vocab_sizes():
    assert binding_mask.CUSTODY_STATUS_COUNT == len(tuple(GatewayCustodyStatus)) == 9
    assert binding_mask.CUSTODY_BOUNDARY_TYPE_COUNT == len(tuple(GatewayBoundaryType)) == 4
    assert binding_mask.CUSTODY_RECEIPT_FAMILY_COUNT == len(tuple(GatewayReceiptFamily)) == 3

    projections = _committed("custody_projections.json")
    assert len(projections) == 18
    for body in projections.values():
        for flag in contract.CUSTODY_EXCLUSION_FLAGS:
            assert body[flag] is True
        for flag in contract.CUSTODY_NON_CLAIM_FLAGS:
            assert body[flag] is False
        assert body["schema_version"] == binding_mask.CUSTODY_SCHEMA_VERSION


def test_attestation_limit_families_are_grounded(tmp_path):
    frozen = {fr.name: fr.receipt for fr in generate_frozen_receipts(tmp_path)}
    base = binding_mask.ATTESTATION_LIMIT_MASK["base"]
    result_limit = binding_mask.ATTESTATION_LIMIT_MASK["result"]
    task_limit = binding_mask.ATTESTATION_LIMIT_MASK["task"]

    # The base limit is on every record; the result limit only on result/error;
    # the task limit only on task_submitted.
    for fr in frozen.values():
        assert base in fr["attestation_limits"]
    assert result_limit in frozen["outcome-result-returned"]["attestation_limits"]
    assert result_limit in frozen["outcome-error-returned"]["attestation_limits"]
    assert task_limit in frozen["outcome-task-submitted"]["attestation_limits"]
    assert task_limit not in frozen["outcome-result-returned"]["attestation_limits"]
    assert result_limit not in frozen["outcome-task-submitted"]["attestation_limits"]


# --------------------------------------------------------------------------- #
# Argument / result digest responsibilities                                   #
# --------------------------------------------------------------------------- #


def test_digest_responsibilities():
    # Argument digest algebra: RFC 8785 JCS, key-order independent, fixed length.
    assert sha256_digest({"b": 2, "a": 1}) == sha256_digest({"a": 1, "b": 2})
    assert len(sha256_digest({"x": 1})) == len("sha256:") + 64
    assert contract.DIGEST_CANONICALIZATION == binding_mask.DIGEST_CANONICALIZATION

    # Result digest: the exact four-member projection, binding path == receipt path.
    assert binding_mask.FASTMCP_RESULT_PROJECTION_KEYS == (
        "content",
        "structuredContent",
        "_meta",
        "isError",
    )

    class _R:
        content = ["x"]
        structured_content = {"found": True}
        meta = {"k": "v"}
        is_error = False

    projection = project_fastmcp_tool_result(_R())
    assert tuple(projection.keys()) == binding_mask.FASTMCP_RESULT_PROJECTION_KEYS
    assert sha256_digest(projection) == fastmcp_tool_result_digest(
        content=projection["content"],
        structured_content=projection["structuredContent"],
        meta=projection["_meta"],
        is_error=projection["isError"],
    )

    # Which neutral outcomes carry / omit a result digest.
    assert set(contract.RESULT_DIGEST_OUTCOMES) == {"result", "error"}
    assert set(contract.NO_RESULT_DIGEST_OUTCOMES) == {
        "task_submitted",
        "exception",
        "timeout",
        "cancellation",
    }


# --------------------------------------------------------------------------- #
# Protocol and binding stamps                                                 #
# --------------------------------------------------------------------------- #


def test_protocol_and_binding_stamps(tmp_path):
    receipt = {fr.name: fr.receipt for fr in generate_frozen_receipts(tmp_path)}[
        "admission-admitted"
    ]
    for field, value in binding_mask.PROTOCOL_STAMPS.items():
        assert receipt[field] == value
    assert (
        receipt["extensions"]["mcp"]["binding_version"]
        == binding_mask.BINDING_STAMPS["binding_version"]
        == fastmcp_binding.BINDING_VERSION
    )
    sig = receipt["receipt_signature"]
    assert sig["algorithm"] == binding_mask.SIGNATURE_STAMPS["algorithm"]
    assert sig["canonicalization"] == binding_mask.SIGNATURE_STAMPS["canonicalization"]
    assert receipt["retention_class_applied"] == "hash_only"


# --------------------------------------------------------------------------- #
# Three-layer parity model                                                    #
# --------------------------------------------------------------------------- #


def test_parity_model_layers_declared():
    assert tuple(spec.layer for spec in contract.PARITY_MODEL) == contract.PARITY_LAYERS
    by_layer = {spec.layer: spec for spec in contract.PARITY_MODEL}
    assert by_layer["semantic"].permitted_difference_fields == ()
    assert by_layer["normalized_equality"].permitted_difference_fields == (
        "receipt_id",
        "issued_at",
        "receipt_signature",
    )
    assert by_layer["exact_unsigned_bytes"].permitted_difference_fields == ()


def test_layer3_exact_unsigned_envelope_bytes_are_deterministic(tmp_path):
    """Layer 3: the RFC 8785 unsigned-envelope bytes are exact and reproducible."""

    regenerated = {fr.name: fr.receipt for fr in generate_frozen_receipts(tmp_path)}
    for name, committed_file in _GOLDEN_BY_NAME.items():
        committed = _committed(committed_file)
        assert binding_mask.unsigned_envelope_bytes(
            regenerated[name]
        ) == binding_mask.unsigned_envelope_bytes(committed)
        # The signature block is what the unsigned envelope drops.
        assert "receipt_signature" not in binding_mask.unsigned_envelope(committed)


def test_layer2_normalized_equality_permits_only_volatile_fields(tmp_path):
    """Layer 2: a live-clock/UUID emit is normalized-equal to the committed golden.

    Only receipt_id / issued_at / receipt_signature differ; every other field is
    byte-for-byte equal under RFC 8785 canonicalization.
    """

    committed = _golden("admission-admitted")

    # A genuinely live emitter: default UUID id factory + wall-clock issued_at.
    emitter = SignedReceiptEmitter(
        identity=freeze_identity(), sink=RawEnvelopeFileSink(tmp_path)
    )
    live_id = emitter.emit_admission(
        context=_admitted_context(),
        requested_tool_name="records.lookup",
        argument_digest=FREEZE_ARGUMENT_DIGEST,
        disposition="admitted",
        additional_attestation_limits=(FREEZE_BOUNDARY_LIMIT,),
    )
    live = json.loads(
        (tmp_path / (_safe(live_id) + ".json")).read_text(encoding="utf-8")
    )

    # The volatile fields genuinely differ...
    assert live["receipt_id"] != committed["receipt_id"]
    # ...while the normalized projection is byte-for-byte equal.
    assert binding_mask.normalized_projection_bytes(
        live
    ) == binding_mask.normalized_projection_bytes(committed)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _admitted_context() -> ReceiptContext:
    """The exact ReceiptContext behind the committed admitted admission golden."""

    return ReceiptContext(
        runtime_instance_id="runtime:freeze:1",
        boundary_id="boundary:freeze:1",
        policy_pack_id="policy:freeze",
        policy_pack_version="1",
        subject_ref="subject:freeze:1",
        logical_call_id="call:freeze:admitted",
        actor_ref="actor:freeze:1",
        binding_version="fastmcp.middleware.v0.1",
    )


def _safe(receipt_id: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9._-]+", "_", receipt_id)
