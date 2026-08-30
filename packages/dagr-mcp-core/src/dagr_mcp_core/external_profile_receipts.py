"""Opt-in SRS vNext external-profile receipt emission.

This module is additive.  The historical ``SignedReceiptEmitter`` in
``dagr_mcp_core.srs_receipts`` remains the byte-stable
``srs.mcp.sdk_enforcement.v0.1`` / Envelope v0.2.1 producer.  Callers must
explicitly construct :class:`ExternalProfileSignedReceiptEmitter` to emit the
successor envelope.

The emitter owns serialization only.  It does not decide domain semantics,
DAGR domain identity, authorization, standing, or truth.  In particular this
module does not synthesize a ``dagr_binding`` and does not map the historical
consumer-local ``mcp_action`` vocabulary to the DAGR ``action`` domain.

Candidate contract basis (DRAFT / non-canonical at implementation time):
- arcs-srs #57 SRS-RECEIPT-TYPE-RECON0 / Envelope v0-next
- arcs-srs #56 SRS External Profile Contract v0.1

``AUTHORITY_MOVEMENT = 0``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from dagr_mcp_core.srs_receipts import (
    ReceiptContentError,
    ReceiptContext,
    SignedReceiptEmitter,
)

ENVELOPE_SCHEMA_VERSION = "srs-envelope-v0-next"
_DIGEST_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_EXTERNAL_PROFILE_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9][A-Za-z0-9_-]*)+\.v[0-9]+$"
)
_NAMESPACED_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9][A-Za-z0-9_-]*)+$"
)
_EXTERNAL_RECEIPT_TYPE_RE = re.compile(
    r"^(?!srs\.)(?!garp\.)[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9][A-Za-z0-9_-]*){2,}$"
)
_PROFILE_VERSION_RE = re.compile(r"^v[0-9]+(?:\.[0-9]+)*$")


@dataclass(frozen=True, slots=True)
class ExternalProfileReceiptContract:
    """Application-owned external-profile projection selected by an operator.

    Every field here is configuration, not inferred authority.  Contract
    digests bind the emitted receipt to exact bytes; this object does not fetch
    or validate those bytes and does not claim that a referenced candidate has
    been ratified.
    """

    profile_id: str
    profile_version: str
    emitter_id: str
    extension_namespace: str
    admission_receipt_type: str
    outcome_receipt_type: str
    envelope_contract_id: str
    envelope_contract_version: str
    envelope_contract_digest: str
    profile_contract_digest: str
    boundary_type: str = "mcp_tool_call"
    protocol_binding: str = "mcp"

    def __post_init__(self) -> None:
        if not _EXTERNAL_PROFILE_ID_RE.fullmatch(self.profile_id):
            raise ValueError("profile_id must be a globally namespaced external profile id ending in .vN")
        if self.profile_id.startswith(("srs.", "garp.")):
            raise ValueError("external profile may not claim the reserved srs.* or garp.* namespace")
        if not _PROFILE_VERSION_RE.fullmatch(self.profile_version):
            raise ValueError("profile_version must use vN[.N...] syntax")
        if not self.emitter_id:
            raise ValueError("emitter_id must be non-empty")
        if not _NAMESPACED_ID_RE.fullmatch(self.extension_namespace):
            raise ValueError("extension_namespace must be globally namespaced")
        if self.extension_namespace.startswith(("srs.", "garp.")) or self.extension_namespace in {
            "srs",
            "garp",
        }:
            raise ValueError("external extension namespace may not claim srs or garp")
        for label, receipt_type in (
            ("admission_receipt_type", self.admission_receipt_type),
            ("outcome_receipt_type", self.outcome_receipt_type),
        ):
            if not _EXTERNAL_RECEIPT_TYPE_RE.fullmatch(receipt_type):
                raise ValueError(f"{label} must be a globally namespaced external receipt type")
        for label, value in (
            ("envelope_contract_id", self.envelope_contract_id),
            ("envelope_contract_version", self.envelope_contract_version),
            ("boundary_type", self.boundary_type),
            ("protocol_binding", self.protocol_binding),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{label} must be non-empty")
        for label, digest in (
            ("envelope_contract_digest", self.envelope_contract_digest),
            ("profile_contract_digest", self.profile_contract_digest),
        ):
            if not _DIGEST_REF_RE.fullmatch(digest):
                raise ValueError(f"{label} must be sha256:<64 lowercase hex>")

    def receipt_type_for(self, receipt_kind: str) -> str:
        if receipt_kind == "admission":
            return self.admission_receipt_type
        if receipt_kind == "outcome":
            return self.outcome_receipt_type
        raise ReceiptContentError(f"unsupported external-profile receipt_kind: {receipt_kind!r}")


class ExternalProfileSignedReceiptEmitter(SignedReceiptEmitter):
    """Signed MCP lifecycle emitter for an explicitly selected SRS vNext profile.

    ``emit_admission`` and ``emit_outcome`` are inherited unchanged from the
    existing emitter.  Only the common envelope projection is replaced.  The
    existing lifecycle adapters therefore keep their execution semantics while
    an operator can opt into a different, byte-bound carrier/profile.
    """

    def __init__(self, *, contract: ExternalProfileReceiptContract, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.contract = contract

    def _common(
        self,
        context: ReceiptContext,
        *,
        receipt_kind: str,
        artifact_class: str,
    ) -> dict[str, Any]:
        # Reuse only the already-hardened common MCP runtime projection and its
        # binding/subject-origin guards.  Replace every profile/carrier-owned
        # value before the envelope can be signed or written.
        envelope = super()._common(
            context,
            receipt_kind=receipt_kind,
            artifact_class=artifact_class,
        )
        contract = self.contract
        envelope["envelope_schema_version"] = ENVELOPE_SCHEMA_VERSION
        envelope["emitter_id"] = contract.emitter_id
        envelope["profile_id"] = contract.profile_id
        envelope["profile_version"] = contract.profile_version
        envelope["receipt_type"] = contract.receipt_type_for(receipt_kind)
        envelope["boundary_type"] = contract.boundary_type
        envelope["protocol_binding"] = contract.protocol_binding
        envelope["contract_refs"] = {
            "envelope_contract": {
                "id": contract.envelope_contract_id,
                "version": contract.envelope_contract_version,
                "digest": contract.envelope_contract_digest,
            },
            "profile_contract": {
                "id": contract.profile_id,
                "version": contract.profile_version,
                "digest": contract.profile_contract_digest,
            },
        }

        # The legacy emitter carries binding metadata under extensions.mcp.
        # vNext external profiles use their own globally-scoped extension
        # namespace.  Moving this neutral binding-version observation does not
        # create domain authority and deliberately does not manufacture a DAGR
        # binding.
        legacy_mcp = envelope.get("extensions", {}).get("mcp", {})
        binding_version = legacy_mcp.get("binding_version", context.binding_version)
        envelope["extensions"] = {
            contract.extension_namespace: {
                "mcp_binding": {"binding_version": binding_version},
            }
        }
        return envelope
