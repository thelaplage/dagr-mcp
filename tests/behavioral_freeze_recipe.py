"""Frozen deterministic recipe for the DAGR MCP behavioral-freeze fixtures.

Sprint A1 (multi-binding behavioral freeze) captures the *observable* behavior of
the external FastMCP binding before any neutral-core extraction. This module is a
characterization helper only: it drives the real, unmodified
``dagr_mcp.srs_receipts`` emitter with a fixed Ed25519 identity and deterministic
id/clock factories so that the exact signed bytes of every emitted receipt class
are reproducible and committable.

Nothing here is production code. It invents no core, moves no implementation, and
changes no semantics. Every value it produces is read straight from the current
repository bytes and frozen as the oracle.

Determinism sources:

* Ed25519 signatures are deterministic (RFC 8032), so a fixed 32-byte seed yields
  identical signature bytes across runs and machines.
* ``receipt_id`` and ``issued_at`` are injected via the emitter's factory hooks,
  removing the only two nondeterministic fields (UUID + wall clock).

The generated set covers every receipt class the binding can emit:

* three admission dispositions: ``admitted`` / ``refused`` / ``deferred_for_review``;
* five outcome kinds: ``result_returned`` / ``error_returned`` / ``exception`` /
  ``task_submitted`` / ``indeterminate`` (the last carries the three cancellation
  governance Booleans).

All five outcome receipts reference the single ``admitted`` admission receipt,
freezing the admission->outcome parent/reference relationship.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from dagr_mcp.srs_receipts import (
    RawEnvelopeFileSink,
    ReceiptContext,
    SignedReceiptEmitter,
    SigningIdentity,
)

# --- Frozen signing identity -------------------------------------------------
# The 32-byte range seed is the same construction the existing emitter-extension
# and delivery-collision suites use; a scoped, public-only issuer identity.
FREEZE_ISSUER_ID = "issuer:dagr:behavioral-freeze"
FREEZE_KEY_ID = "issuer.dagr.behavioral-freeze/receipt-signing/v1"
FREEZE_PRIVATE_SEED = bytes(range(32))

# The only two otherwise-nondeterministic receipt fields, pinned.
FREEZE_ISSUED_AT = "2026-07-13T00:00:00Z"

# The FastMCP middleware boundary limit, appended by the binding on every receipt.
FREEZE_BOUNDARY_LIMIT = (
    "The middleware is installed once at the institutional trust boundary; "
    "receipts attest only to observations at that boundary."
)

# The admitted admission receipt that every outcome receipt references.
FREEZE_ADMISSION_ID = "urn:srs:receipt:admission:freeze-admitted"

FREEZE_ARGUMENT_DIGEST = "sha256:" + "a" * 64
FREEZE_RESULT_DIGEST = "sha256:" + "d" * 64
FREEZE_ERROR_DIGEST = "sha256:" + "e" * 64


def freeze_identity() -> SigningIdentity:
    return SigningIdentity(
        issuer_id=FREEZE_ISSUER_ID,
        key_id=FREEZE_KEY_ID,
        private_key=Ed25519PrivateKey.from_private_bytes(FREEZE_PRIVATE_SEED),
    )


def _context(**overrides: Any) -> ReceiptContext:
    values: dict[str, Any] = {
        "runtime_instance_id": "runtime:freeze:1",
        "boundary_id": "boundary:freeze:1",
        "policy_pack_id": "policy:freeze",
        "policy_pack_version": "1",
        "subject_ref": "subject:freeze:1",
        "logical_call_id": "call:freeze:1",
        "actor_ref": "actor:freeze:1",
        "binding_version": "fastmcp.middleware.v0.1",
    }
    values.update(overrides)
    return ReceiptContext(**values)


@dataclass(frozen=True)
class FrozenReceipt:
    """One emitted receipt: its friendly name, sink filename, and loaded body."""

    name: str
    receipt_id: str
    filename: str
    receipt: dict[str, Any]


# Sink filename derivation mirrors RawEnvelopeFileSink._SAFE_FILE.
import re as _re

_SAFE_FILE = _re.compile(r"[^A-Za-z0-9._-]+")


def _filename_for(receipt_id: str) -> str:
    return _SAFE_FILE.sub("_", receipt_id) + ".json"


# Ordered emission plan. Each entry is (name, kind, emit-kwargs). The id factory
# hands out ids in this exact order, so ids and bytes are reproducible.
_ORDER: tuple[tuple[str, str, str], ...] = (
    ("admission-admitted", "admission", FREEZE_ADMISSION_ID),
    ("admission-refused", "admission", "urn:srs:receipt:admission:freeze-refused"),
    ("admission-deferred", "admission", "urn:srs:receipt:admission:freeze-deferred"),
    ("outcome-result-returned", "outcome", "urn:srs:receipt:outcome:freeze-result-returned"),
    ("outcome-error-returned", "outcome", "urn:srs:receipt:outcome:freeze-error-returned"),
    ("outcome-exception", "outcome", "urn:srs:receipt:outcome:freeze-exception"),
    ("outcome-task-submitted", "outcome", "urn:srs:receipt:outcome:freeze-task-submitted"),
    ("outcome-indeterminate", "outcome", "urn:srs:receipt:outcome:freeze-indeterminate"),
)


def generate_frozen_receipts(directory: Path) -> list[FrozenReceipt]:
    """Emit the full frozen receipt set into ``directory`` (deterministic bytes)."""

    directory = Path(directory)
    identity = freeze_identity()
    sink = RawEnvelopeFileSink(directory)

    id_queue = [entry[2] for entry in _ORDER]

    def id_factory(_receipt_kind: str) -> str:
        return id_queue.pop(0)

    emitter = SignedReceiptEmitter(
        identity=identity,
        sink=sink,
        receipt_id_factory=id_factory,
        issued_at_factory=lambda: FREEZE_ISSUED_AT,
    )

    # --- admissions ---
    emitter.emit_admission(
        context=_context(logical_call_id="call:freeze:admitted"),
        requested_tool_name="records.lookup",
        argument_digest=FREEZE_ARGUMENT_DIGEST,
        disposition="admitted",
        additional_attestation_limits=(FREEZE_BOUNDARY_LIMIT,),
    )
    emitter.emit_admission(
        context=_context(logical_call_id="call:freeze:refused"),
        requested_tool_name="danger.delete",
        argument_digest="sha256:" + "b" * 64,
        disposition="refused",
        reason_code="policy_refused",
        additional_attestation_limits=(FREEZE_BOUNDARY_LIMIT,),
    )
    emitter.emit_admission(
        context=_context(logical_call_id="call:freeze:deferred"),
        requested_tool_name="records.write",
        argument_digest="sha256:" + "c" * 64,
        disposition="deferred_for_review",
        review_object_ref="review:freeze:1",
        retry_contract="retry_after_approval",
        additional_attestation_limits=(FREEZE_BOUNDARY_LIMIT,),
    )

    # --- outcomes (all reference the admitted admission receipt) ---
    emitter.emit_outcome(
        context=_context(logical_call_id="call:freeze:result"),
        admission_receipt_ref=FREEZE_ADMISSION_ID,
        outcome="result_returned",
        result_digest=FREEZE_RESULT_DIGEST,
        additional_attestation_limits=(FREEZE_BOUNDARY_LIMIT,),
    )
    emitter.emit_outcome(
        context=_context(logical_call_id="call:freeze:error"),
        admission_receipt_ref=FREEZE_ADMISSION_ID,
        outcome="error_returned",
        result_digest=FREEZE_ERROR_DIGEST,
        additional_attestation_limits=(FREEZE_BOUNDARY_LIMIT,),
    )
    emitter.emit_outcome(
        context=_context(logical_call_id="call:freeze:exception"),
        admission_receipt_ref=FREEZE_ADMISSION_ID,
        outcome="exception",
        exception_class="TimeoutError",
        additional_attestation_limits=(FREEZE_BOUNDARY_LIMIT,),
    )
    emitter.emit_outcome(
        context=_context(logical_call_id="call:freeze:task"),
        admission_receipt_ref=FREEZE_ADMISSION_ID,
        outcome="task_submitted",
        additional_attestation_limits=(FREEZE_BOUNDARY_LIMIT,),
    )
    emitter.emit_outcome(
        context=_context(logical_call_id="call:freeze:indeterminate"),
        admission_receipt_ref=FREEZE_ADMISSION_ID,
        outcome="indeterminate",
        binding_owned_fields={
            "request_cancelled": True,
            "execution_state_unknown": True,
            "delivery_incomplete": True,
        },
        additional_attestation_limits=(FREEZE_BOUNDARY_LIMIT,),
    )

    results: list[FrozenReceipt] = []
    for name, _kind, receipt_id in _ORDER:
        filename = _filename_for(receipt_id)
        body = json.loads((directory / filename).read_text(encoding="utf-8"))
        results.append(FrozenReceipt(name=name, receipt_id=receipt_id, filename=filename, receipt=body))
    return results


def write_frozen_trust_bundle(directory: Path, filename: str = "issuer-keys.json") -> Path:
    """Write the public-only trust bundle for the frozen identity."""

    identity = freeze_identity()
    sink = RawEnvelopeFileSink(directory)
    return sink.write_trust_bundle(identity.trust_bundle(), filename=filename)
