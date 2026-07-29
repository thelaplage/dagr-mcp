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
    RawEnvelopeFileSink,
    ReceiptContext,
    SignedReceiptEmitter,
    SigningIdentity,
    sha256_digest,
)

from receipt_verification import verify_receipt

SCHEMA = json.loads(
    (Path(__file__).parent / "vendor" / "srs-envelope-v0.2.0.schema.json").read_text()
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
