"""Byte-parity proof: dagr_mcp_core.srs_receipts vs. the frozen legacy emitter.

This is the "did the dagr-mcp-core extraction fork change receipt-emission
behavior" proof, distinct from ``tools/check_core_extraction_manifest.py``
(which only checks source-file drift, not behavior).

For each of the three binding-version tokens the legacy emitter's registry
carries at HEAD (the direct harness, the FastMCP v0.1 binding, and the
official-SDK v0.1 binding), this drives the SAME deterministic 8-receipt
battery (three admission dispositions, five outcome kinds) through both:

* ``dagr_mcp.srs_receipts.SignedReceiptEmitter`` (the untouched, frozen legacy
  emitter -- every existing binding's fixtures ultimately go through this one
  class's ``_common``/``emit_admission``/``emit_outcome``, so this single
  battery stands in for the behavioral_freeze, fastmcp_demo, and
  official_mcp_sdk fixture scenarios: they differ only in binding_version and
  tool-specific arguments, never in emitter logic); and
* ``dagr_mcp_core.srs_receipts.SignedReceiptEmitter`` (the extraction fork),

with an identical fixed signing key, identical fixed receipt-id/issued-at
factories, and identical arguments -- then asserts the RFC 8785 canonical bytes
of every emitted envelope, INCLUDING the Ed25519 signature (deterministic
under RFC 8032 given an identical preimage and key), are exactly equal.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import dagr_mcp.srs_receipts as legacy_srs
import dagr_mcp_core.srs_receipts as core_srs

# --------------------------------------------------------------------------- #
# Fixed, shared-across-both-emitters determinism inputs                       #
# --------------------------------------------------------------------------- #

PARITY_ISSUER_ID = "issuer:dagr:core-extraction-parity"
PARITY_KEY_ID = "issuer.dagr.core-extraction-parity/receipt-signing/v1"
PARITY_PRIVATE_SEED = bytes(range(32))
PARITY_ISSUED_AT = "2026-07-29T00:00:00Z"

PARITY_ARGUMENT_DIGEST = "sha256:" + "a" * 64
PARITY_RESULT_DIGEST = "sha256:" + "d" * 64
PARITY_ERROR_DIGEST = "sha256:" + "e" * 64

# (name, receipt_id) in emission order -- both runs mint ids from this exact
# queue via the emitter's factory hook, so ids are reproducible and matched.
_ORDER: tuple[tuple[str, str], ...] = (
    ("admission-admitted", "urn:srs:receipt:admission:parity-admitted"),
    ("admission-refused", "urn:srs:receipt:admission:parity-refused"),
    ("admission-deferred", "urn:srs:receipt:admission:parity-deferred"),
    ("outcome-result-returned", "urn:srs:receipt:outcome:parity-result-returned"),
    ("outcome-error-returned", "urn:srs:receipt:outcome:parity-error-returned"),
    ("outcome-exception", "urn:srs:receipt:outcome:parity-exception"),
    ("outcome-task-submitted", "urn:srs:receipt:outcome:parity-task-submitted"),
    ("outcome-indeterminate", "urn:srs:receipt:outcome:parity-indeterminate"),
)

# The three binding-version tokens exercised by the existing, unmodified
# bindings (direct harness, FastMCP v0.1, official-SDK v0.1), each of which is
# registered in BOTH the legacy emitter's frozen registry and the core fork's
# copy of it (see EXTRACTION_MANIFEST.json's documented_deltas -- the fork only
# ADDS official-mcp-sdk.python.v0.2, it never removes an existing token).
BINDING_VERSIONS = (
    "direct-harness.v0.1",
    "fastmcp.middleware.v0.1",
    "official-mcp-sdk.python.v0.1",
)


def _generate(srs_module, directory: Path, binding_version: str) -> dict[str, dict[str, Any]]:
    """Emit the fixed 8-receipt battery through *srs_module* and return name -> envelope."""

    identity = srs_module.SigningIdentity(
        issuer_id=PARITY_ISSUER_ID,
        key_id=PARITY_KEY_ID,
        private_key=Ed25519PrivateKey.from_private_bytes(PARITY_PRIVATE_SEED),
    )
    sink = srs_module.RawEnvelopeFileSink(directory)
    id_queue = [receipt_id for _name, receipt_id in _ORDER]

    def id_factory(_receipt_kind: str) -> str:
        return id_queue.pop(0)

    emitter = srs_module.SignedReceiptEmitter(
        identity=identity,
        sink=sink,
        receipt_id_factory=id_factory,
        issued_at_factory=lambda: PARITY_ISSUED_AT,
    )

    def context(**overrides: Any):
        values: dict[str, Any] = {
            "runtime_instance_id": "runtime:parity:1",
            "boundary_id": "boundary:parity:1",
            "policy_pack_id": "policy:parity",
            "policy_pack_version": "1",
            "subject_ref": "subject:parity:1",
            "logical_call_id": "call:parity:1",
            "actor_ref": "actor:parity:1",
            "binding_version": binding_version,
        }
        values.update(overrides)
        return srs_module.ReceiptContext(**values)

    admitted_id = _ORDER[0][1]

    emitter.emit_admission(
        context=context(logical_call_id="call:parity:admitted"),
        requested_tool_name="records.lookup",
        argument_digest=PARITY_ARGUMENT_DIGEST,
        disposition="admitted",
    )
    emitter.emit_admission(
        context=context(logical_call_id="call:parity:refused"),
        requested_tool_name="danger.delete",
        argument_digest="sha256:" + "b" * 64,
        disposition="refused",
        reason_code="policy_refused",
    )
    emitter.emit_admission(
        context=context(logical_call_id="call:parity:deferred"),
        requested_tool_name="records.write",
        argument_digest="sha256:" + "c" * 64,
        disposition="deferred_for_review",
        review_object_ref="review:parity:1",
        retry_contract="retry_after_approval",
    )
    emitter.emit_outcome(
        context=context(logical_call_id="call:parity:result"),
        admission_receipt_ref=admitted_id,
        outcome="result_returned",
        result_digest=PARITY_RESULT_DIGEST,
    )
    emitter.emit_outcome(
        context=context(logical_call_id="call:parity:error"),
        admission_receipt_ref=admitted_id,
        outcome="error_returned",
        result_digest=PARITY_ERROR_DIGEST,
    )
    emitter.emit_outcome(
        context=context(logical_call_id="call:parity:exception"),
        admission_receipt_ref=admitted_id,
        outcome="exception",
        exception_class="TimeoutError",
    )
    emitter.emit_outcome(
        context=context(logical_call_id="call:parity:task"),
        admission_receipt_ref=admitted_id,
        outcome="task_submitted",
    )
    emitter.emit_outcome(
        context=context(logical_call_id="call:parity:indeterminate"),
        admission_receipt_ref=admitted_id,
        outcome="indeterminate",
        binding_owned_fields={
            "request_cancelled": True,
            "execution_state_unknown": True,
            "delivery_incomplete": True,
        },
    )

    receipts: dict[str, dict[str, Any]] = {}
    for name, receipt_id in _ORDER:
        matches = [
            json.loads(p.read_text())
            for p in directory.glob("*.json")
            if json.loads(p.read_text()).get("receipt_id") == receipt_id
        ]
        assert len(matches) == 1, (name, receipt_id, list(directory.glob("*.json")))
        receipts[name] = matches[0]
    return receipts


@pytest.mark.parametrize("binding_version", BINDING_VERSIONS)
def test_core_extraction_byte_parity(tmp_path, binding_version):
    legacy_receipts = _generate(legacy_srs, tmp_path / "legacy", binding_version)
    core_receipts = _generate(core_srs, tmp_path / "core", binding_version)

    assert set(legacy_receipts) == set(core_receipts) == {name for name, _ in _ORDER}

    for name in legacy_receipts:
        legacy_bytes = rfc8785.dumps(legacy_receipts[name])
        core_bytes = rfc8785.dumps(core_receipts[name])
        assert legacy_bytes == core_bytes, (
            f"{name} ({binding_version}): canonical bytes diverged between the "
            "legacy emitter and the dagr-mcp-core extraction fork"
        )
