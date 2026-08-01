"""Standalone dagr-mcp-core proof: no mcp, no fastmcp, receipts verify.

Intended to run in a virtualenv where ONLY ``dagr-mcp-core`` (and its ``dev``
extra: pytest, jsonschema) is installed -- never the root ``dagr-mcp``
distribution, ``mcp``, or ``fastmcp``. See ``docs/CORE_EXTRACTION_FORK.md``
"Core environment" for how to set that venv up.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dagr_mcp_core.lifecycle.core import plan_admission, plan_outcome_strict
from dagr_mcp_core.lifecycle.models import AdmissionRequest, ExecutionObservation
from dagr_mcp_core.srs_receipts import (
    SUBJECT_REF_ORIGIN_NOT_DECLARED,
    SUBJECT_REF_ORIGINS,
    RawEnvelopeFileSink,
    ReceiptContentError,
    ReceiptContext,
    SignedReceiptEmitter,
    SigningIdentity,
    read_subject_ref_origin,
    sha256_digest,
)

from receipt_verification import verify_receipt

VENDOR = Path(__file__).parent / "vendor"
SCHEMA_V0_2_0_PATH = VENDOR / "srs-envelope-v0.2.0.schema.json"
SCHEMA_V0_2_1_PATH = VENDOR / "srs-envelope-v0.2.1.schema.json"
SCHEMA = json.loads(SCHEMA_V0_2_0_PATH.read_text())
# The v0.2.1 envelope is the schema that actually declares
# ``subject_ref_origin``; v0.2.0 is top-level permissive and would accept the
# field without checking it, so every origin proof below validates against
# v0.2.1. Both pins are retained — v0.2.1 does not replace v0.2.0.
SCHEMA_V0_2_1 = json.loads(SCHEMA_V0_2_1_PATH.read_text())

DECLARED_ORIGINS = (
    "supplied_subject",
    "derived_from_session",
    "derived_from_request",
    "derived_from_supplied_correlation",
    "binding_minted",
)


def test_mcp_is_not_installed():
    with pytest.raises(ModuleNotFoundError):
        import mcp  # noqa: F401


def test_fastmcp_is_not_installed():
    with pytest.raises(ModuleNotFoundError):
        import fastmcp  # noqa: F401


def test_end_to_end_admitted_call_receipts_verify(tmp_path):
    identity = SigningIdentity.generate(
        issuer_id="issuer:core-standalone", key_id="issuer.core-standalone/key/1"
    )
    sink = RawEnvelopeFileSink(tmp_path / "receipts")
    emitter = SignedReceiptEmitter(identity=identity, sink=sink)
    bundle = identity.trust_bundle()

    context = ReceiptContext(
        runtime_instance_id="rt:standalone",
        boundary_id="b:standalone",
        policy_pack_id="p:standalone",
        policy_pack_version="1",
        subject_ref="subject:call:1",
        logical_call_id="call:1",
        binding_version="official-mcp-sdk.python.v0.2",
    )

    admission_plan = plan_admission(AdmissionRequest(disposition="admitted", tool_class="read"))
    assert admission_plan.execution_proceeds
    assert admission_plan.record is not None

    admission_receipt_id = emitter.emit_admission(
        context=context,
        requested_tool_name="echo",
        argument_digest=sha256_digest({"text": "hi"}),
        disposition="admitted",
    )

    outcome_plan = plan_outcome_strict(
        admission_plan, ExecutionObservation(observation="result")
    )
    assert outcome_plan.record is not None
    assert outcome_plan.record.carries_result_digest

    outcome_receipt_id = emitter.emit_outcome(
        context=context,
        admission_receipt_ref=admission_receipt_id,
        outcome="result_returned",
        result_digest=sha256_digest({"content": [], "structuredContent": None, "_meta": None, "isError": False}),
    )

    written = [json.loads(p.read_text()) for p in (tmp_path / "receipts").glob("*.json")]
    receipts_by_id = {receipt["receipt_id"]: receipt for receipt in written}
    admission_receipt = receipts_by_id[admission_receipt_id]
    outcome_receipt = receipts_by_id[outcome_receipt_id]

    verify_receipt(admission_receipt, bundle, SCHEMA)
    verify_receipt(outcome_receipt, bundle, SCHEMA)
    assert outcome_receipt["admission_receipt_ref"] == admission_receipt_id


# --------------------------------------------------------------------------- #
# Subject-reference origin disclosure — SRS envelope v0.2.1                    #
#                                                                             #
# The extraction fork carries the same closed vocabulary and the same          #
# exact-membership rejection as the legacy emitter it was forked from. These   #
# checks run with neither mcp nor fastmcp installed, so they prove the         #
# disclosure is a property of the neutral core rather than of any binding.     #
# --------------------------------------------------------------------------- #


def _emitter(directory: Path):
    identity = SigningIdentity.generate(
        issuer_id="issuer:core-origin", key_id="issuer.core-origin/key/1"
    )
    return identity, SignedReceiptEmitter(
        identity=identity, sink=RawEnvelopeFileSink(directory)
    )


def _emit(context: ReceiptContext, directory: Path):
    identity, emitter = _emitter(directory)
    receipt_id = emitter.emit_admission(
        context=context,
        requested_tool_name="echo",
        argument_digest="sha256:" + "a" * 64,
        disposition="admitted",
    )
    receipt = next(
        json.loads(p.read_text())
        for p in directory.glob("*.json")
        if json.loads(p.read_text())["receipt_id"] == receipt_id
    )
    return identity, receipt


def _context(**overrides) -> ReceiptContext:
    base = dict(
        runtime_instance_id="rt:origin",
        boundary_id="b:origin",
        policy_pack_id="p:origin",
        policy_pack_version="1",
        subject_ref="subject:call:1",
        logical_call_id="call:1",
        binding_version="official-mcp-sdk.python.v0.2",
    )
    base.update(overrides)
    return ReceiptContext(**base)


def test_pinned_envelope_schemas_are_both_present_and_distinct():
    """v0.2.1 is additive: it declares the field, v0.2.0 does not, both retained."""

    assert "subject_ref_origin" not in json.loads(SCHEMA_V0_2_0_PATH.read_text())["properties"]
    declared = SCHEMA_V0_2_1["properties"]["subject_ref_origin"]
    assert declared["type"] == "string"
    assert declared["enum"] == list(DECLARED_ORIGINS)
    assert SUBJECT_REF_ORIGINS == set(DECLARED_ORIGINS)


def test_not_declared_is_a_reading_only_and_never_an_enum_member():
    assert SUBJECT_REF_ORIGIN_NOT_DECLARED == "not_declared"
    assert SUBJECT_REF_ORIGIN_NOT_DECLARED not in SUBJECT_REF_ORIGINS
    assert SUBJECT_REF_ORIGIN_NOT_DECLARED not in SCHEMA_V0_2_1_PATH.read_text()


@pytest.mark.parametrize("origin", DECLARED_ORIGINS)
def test_core_emits_and_verifies_every_declared_origin(origin, tmp_path):
    identity, receipt = _emit(_context(subject_ref_origin=origin), tmp_path / origin)
    assert receipt["subject_ref_origin"] == origin
    assert read_subject_ref_origin(receipt) == origin
    verify_receipt(receipt, identity.trust_bundle(), SCHEMA_V0_2_1)


def test_core_genuine_absence_is_a_distinct_reading(tmp_path):
    identity, receipt = _emit(_context(), tmp_path)
    assert "subject_ref_origin" not in receipt
    assert read_subject_ref_origin(receipt) == SUBJECT_REF_ORIGIN_NOT_DECLARED
    assert read_subject_ref_origin(receipt) not in SUBJECT_REF_ORIGINS
    verify_receipt(receipt, identity.trust_bundle(), SCHEMA_V0_2_1)


@pytest.mark.parametrize(
    "bad", ["not_declared", "", "SUPPLIED_SUBJECT", "sixth_value", 123, True]
)
def test_core_refuses_out_of_vocabulary_before_signing(bad, tmp_path):
    _identity, emitter = _emitter(tmp_path)
    with pytest.raises(ReceiptContentError, match="outside the closed vocabulary"):
        emitter.emit_admission(
            context=_context(subject_ref_origin=bad),
            requested_tool_name="echo",
            argument_digest="sha256:" + "a" * 64,
            disposition="admitted",
        )
    # Refusal, not a silent downgrade to a receipt that merely declares nothing.
    assert not list(tmp_path.glob("*.json"))


def test_core_signature_covers_the_declared_origin(tmp_path):
    from cryptography.exceptions import InvalidSignature

    identity, receipt = _emit(
        _context(subject_ref_origin="derived_from_request"), tmp_path
    )
    tampered = dict(receipt)
    tampered["subject_ref_origin"] = "supplied_subject"
    with pytest.raises(InvalidSignature):
        verify_receipt(tampered, identity.trust_bundle(), SCHEMA_V0_2_1)
