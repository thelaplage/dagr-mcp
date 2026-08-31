"""Opt-in SRS vNext external-profile receipt emission.

This module is additive. The historical ``SignedReceiptEmitter`` in
``dagr_mcp_core.srs_receipts`` remains the byte-stable
``srs.mcp.sdk_enforcement.v0.1`` / Envelope v0.2.1 producer. Callers must
explicitly construct :class:`ExternalProfileSignedReceiptEmitter` to emit the
successor envelope.

The emitter owns serialization only. It does not decide domain semantics,
DAGR domain identity, authorization, standing, truth, or independent SRS
verification. In particular this module does not synthesize a ``dagr_binding``
and does not map the historical consumer-local ``mcp_action`` vocabulary to the
DAGR ``action`` domain.

Candidate contract basis (merged bytes, still DRAFT / non-canonical):
- arcs-srs #57 merge 483c73e02ca87b286597eb234c759d93aeed687d
  / Envelope v0-next blob 39beaeaa65ab97e6e81d32057b52ac20c3f8a1ea
- arcs-srs #56 SRS External Profile Contract v0.1

``AUTHORITY_MOVEMENT = 0``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from dagr_mcp_core.srs_receipts import (
    CANCELLATION_FIELD_NAMES,
    RESULT_LIMIT,
    TASK_LIMIT,
    ReceiptContentError,
    ReceiptContext,
    SignedReceiptEmitter,
    enforce_raw_content_exclusion,
)

ENVELOPE_SCHEMA_VERSION = "srs-envelope-v0-next"
ARCS_SRS_VNEXT_MERGE_COMMIT = "483c73e02ca87b286597eb234c759d93aeed687d"
ARCS_SRS_VNEXT_ENVELOPE_GIT_BLOB = "39beaeaa65ab97e6e81d32057b52ac20c3f8a1ea"
ARCS_SRS_EXTERNAL_PROFILE_SCHEMA_GIT_BLOB = "4832c73870820575362ccd98868de990c51b74c1"
SUPPORTED_ENVELOPE_CONTRACT_ID = "srs-envelope-v0-next"
SUPPORTED_ENVELOPE_CONTRACT_VERSION = "v0-next"
_SUPPORTED_ENVELOPE_SCHEMA_ID = (
    "https://arcs.example/schemas/srs/successor/envelope-v0-next.schema.json"
)
_EXTERNAL_PROFILE_DECLARATION_SCHEMA = "srs.external-profile-declaration/v0.1"
_EXTERNAL_PROFILE_UNKNOWN_BEHAVIOR = "preserve_identity_and_do_not_infer"
_DIGEST_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
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
_PROFILE_REQUIRED_KEYS = frozenset(
    {
        "schema",
        "profile_id",
        "profile_version",
        "publisher_ref",
        "compatible_envelopes",
        "permitted_receipt_types",
        "receipt_type_classifications",
        "extension_namespace",
        "raw_content_posture",
        "signing_required",
        "attestation_limits_required",
        "unknown_profile_behavior",
        "conformance_vectors_ref",
    }
)
_PROFILE_ALLOWED_KEYS = _PROFILE_REQUIRED_KEYS | frozenset(
    {"external_contract_refs", "migration_ref"}
)
_RECEIPT_CLASSES = frozenset(
    {
        "governance_decision",
        "lifecycle_event",
        "outcome",
        "provenance",
        "verification_report",
    }
)
_FROZEN_V0_2_1_RECEIPT_TYPES = frozenset(
    {"sdk_enforcement", "grace_session", "connection", "provenance"}
)


def _sha256_ref(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()  # noqa: S324 - Git object identity, not security


def _load_json_object(label: str, data: bytes) -> dict[str, Any]:
    if not isinstance(data, bytes) or not data:
        raise ValueError(f"{label} must be non-empty bytes")
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be UTF-8 JSON bytes") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must decode to a JSON object")
    return parsed


def _require_unique_strings(label: str, value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    if any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{label} must contain non-empty strings only")
    if len(value) != len(set(value)):
        raise ValueError(f"{label} must contain unique values")
    return value


def _validate_profile_declaration(
    profile: dict[str, Any],
    *,
    expected_envelope_sha256: str,
) -> tuple[set[str], dict[tuple[str, str | None], str]]:
    """Fail closed on the pinned declaration grammar used by this emitter.

    This is a consumer-side pre-emission guard over the exact #57 declaration
    shape, not an independent SRS verifier and not a replacement for ARCS Verify.
    Its purpose is narrower: do not sign a receipt under profile bytes that are
    malformed or internally inconsistent for fields this emitter relies upon.
    """

    missing = _PROFILE_REQUIRED_KEYS - profile.keys()
    unknown = profile.keys() - _PROFILE_ALLOWED_KEYS
    if missing:
        raise ValueError(f"profile contract missing required keys: {sorted(missing)}")
    if unknown:
        raise ValueError(f"profile contract contains unknown keys: {sorted(unknown)}")

    if profile.get("schema") != _EXTERNAL_PROFILE_DECLARATION_SCHEMA:
        raise ValueError("unsupported external profile declaration schema")
    profile_id = profile.get("profile_id")
    if not isinstance(profile_id, str) or not _EXTERNAL_PROFILE_ID_RE.fullmatch(profile_id):
        raise ValueError("profile contract contains an invalid profile_id")
    if profile_id.startswith(("srs.", "garp.")):
        raise ValueError("profile contract claims a reserved profile namespace")
    profile_version = profile.get("profile_version")
    if not isinstance(profile_version, str) or not _PROFILE_VERSION_RE.fullmatch(profile_version):
        raise ValueError("profile contract contains an invalid profile_version")
    for label in ("publisher_ref", "conformance_vectors_ref"):
        if not isinstance(profile.get(label), str) or not profile[label]:
            raise ValueError(f"profile {label} must be non-empty")

    extension_namespace = profile.get("extension_namespace")
    if not isinstance(extension_namespace, str) or not _NAMESPACED_ID_RE.fullmatch(
        extension_namespace
    ):
        raise ValueError("profile contract contains an invalid extension_namespace")
    if extension_namespace.startswith(("srs.", "garp.")) or extension_namespace in {
        "srs",
        "garp",
    }:
        raise ValueError("profile contract claims a reserved extension namespace")

    if profile.get("raw_content_posture") not in {
        "profile_defined",
        "metadata_only",
        "hash_only",
    }:
        raise ValueError("unsupported raw_content_posture")
    if type(profile.get("signing_required")) is not bool:
        raise ValueError("profile signing_required must be boolean")
    if profile.get("signing_required") is not True:
        raise ValueError("signed external-profile emitter requires signing_required=true")
    if profile.get("attestation_limits_required") is not True:
        raise ValueError("external profile must require attestation limits")
    if profile.get("unknown_profile_behavior") != _EXTERNAL_PROFILE_UNKNOWN_BEHAVIOR:
        raise ValueError("external profile must preserve unknown profile identity without inference")

    migration_ref = profile.get("migration_ref")
    if migration_ref is not None and not isinstance(migration_ref, str):
        raise ValueError("profile migration_ref must be a string or null")
    external_refs = profile.get("external_contract_refs")
    if external_refs is not None:
        _require_unique_strings("profile external_contract_refs", external_refs)

    compatibility = profile.get("compatible_envelopes")
    if not isinstance(compatibility, list) or not compatibility:
        raise ValueError("profile compatible_envelopes must be a non-empty list")
    compatibility_keys: set[tuple[str, str]] = set()
    for item in compatibility:
        if not isinstance(item, dict) or set(item) != {"published_version", "sha256"}:
            raise ValueError("profile compatible_envelopes contains a malformed entry")
        version = item.get("published_version")
        digest = item.get("sha256")
        if not isinstance(version, str) or not version:
            raise ValueError("profile compatible envelope version must be non-empty")
        if not isinstance(digest, str) or not _SHA256_HEX_RE.fullmatch(digest):
            raise ValueError("profile compatible envelope sha256 must be 64 lowercase hex")
        key = (version, digest)
        if key in compatibility_keys:
            raise ValueError("profile compatible_envelopes must contain unique entries")
        compatibility_keys.add(key)
    if (SUPPORTED_ENVELOPE_CONTRACT_VERSION, expected_envelope_sha256) not in compatibility_keys:
        raise ValueError("profile does not bind the exact pinned vNext envelope bytes")

    permitted_list = _require_unique_strings(
        "profile permitted_receipt_types", profile.get("permitted_receipt_types")
    )
    for receipt_type in permitted_list:
        if receipt_type not in _FROZEN_V0_2_1_RECEIPT_TYPES and not _EXTERNAL_RECEIPT_TYPE_RE.fullmatch(
            receipt_type
        ):
            raise ValueError("profile permitted_receipt_types contains an invalid type")
    permitted = set(permitted_list)
    if any(version == "0.2.1" for version, _ in compatibility_keys):
        non_frozen = permitted - _FROZEN_V0_2_1_RECEIPT_TYPES
        if non_frozen:
            raise ValueError("v0.2.1-compatible profile may permit only frozen receipt types")

    classifications = profile.get("receipt_type_classifications")
    if not isinstance(classifications, list) or not classifications:
        raise ValueError("profile receipt_type_classifications must be a non-empty list")
    exact_entries: set[tuple[str, str, str | None]] = set()
    mapping: dict[tuple[str, str | None], str] = {}
    covered: set[str] = set()
    for item in classifications:
        if not isinstance(item, dict):
            raise ValueError("profile receipt_type_classifications contains a non-object")
        if not {"receipt_type", "receipt_class"} <= set(item) or set(item) - {
            "receipt_type",
            "receipt_class",
            "receipt_kind",
        }:
            raise ValueError("invalid receipt_type_classification entry")
        receipt_type = item.get("receipt_type")
        receipt_class = item.get("receipt_class")
        receipt_kind = item.get("receipt_kind")
        if not isinstance(receipt_type, str) or receipt_type not in permitted:
            raise ValueError("classification references a non-permitted receipt type")
        if receipt_class not in _RECEIPT_CLASSES:
            raise ValueError("classification contains an invalid receipt_class")
        if receipt_kind is not None and (not isinstance(receipt_kind, str) or not receipt_kind):
            raise ValueError("classification receipt_kind must be non-empty when present")
        exact_key = (receipt_type, receipt_class, receipt_kind)
        if exact_key in exact_entries:
            raise ValueError("profile receipt_type_classifications must contain unique entries")
        exact_entries.add(exact_key)
        covered.add(receipt_type)
        key = (receipt_type, receipt_kind)
        prior = mapping.get(key)
        if prior is not None and prior != receipt_class:
            raise ValueError("conflicting duplicate receipt classification")
        mapping[key] = receipt_class
    unclassified = permitted - covered
    if unclassified:
        raise ValueError(f"profile has unclassified permitted receipt types: {sorted(unclassified)}")

    if "sdk_enforcement" in permitted:
        for required_kind in ("admission", "outcome"):
            if ("sdk_enforcement", required_kind) not in mapping:
                raise ValueError(
                    f"sdk_enforcement classification missing receipt_kind={required_kind}"
                )
        if ("sdk_enforcement", None) in mapping:
            raise ValueError("sdk_enforcement classification must be receipt-kind-qualified")

    return permitted, mapping


@dataclass(frozen=True, slots=True)
class ExternalProfileReceiptContract:
    """Application-owned external-profile projection selected by an operator.

    ``contract_refs`` is an exact byte-identity claim. Therefore syntactically
    valid caller-supplied digests are insufficient: callers must provide the
    actual envelope/profile contract bytes and every serialized digest is
    checked against those bytes before any receipt can be emitted.

    The envelope contract is additionally pinned to the exact ARCS SRS vNext
    Git blob merged by #57. The profile remains application-owned. This class
    applies a fail-closed consumer-side guard to the exact declaration fields it
    relies on, but it does not claim independent SRS verification.
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
    envelope_contract_bytes: bytes
    profile_contract_bytes: bytes
    boundary_type: str = "mcp_tool_call"
    protocol_binding: str = "mcp"

    def __post_init__(self) -> None:
        if not _EXTERNAL_PROFILE_ID_RE.fullmatch(self.profile_id):
            raise ValueError(
                "profile_id must be a globally namespaced external profile id ending in .vN"
            )
        if self.profile_id.startswith(("srs.", "garp.")):
            raise ValueError(
                "external profile may not claim the reserved srs.* or garp.* namespace"
            )
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
                raise ValueError(
                    f"{label} must be a globally namespaced external receipt type"
                )
        for label, value in (
            ("boundary_type", self.boundary_type),
            ("protocol_binding", self.protocol_binding),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{label} must be non-empty")
        if self.envelope_contract_id != SUPPORTED_ENVELOPE_CONTRACT_ID:
            raise ValueError("unsupported envelope_contract_id")
        if self.envelope_contract_version != SUPPORTED_ENVELOPE_CONTRACT_VERSION:
            raise ValueError("unsupported envelope_contract_version")
        for label, digest in (
            ("envelope_contract_digest", self.envelope_contract_digest),
            ("profile_contract_digest", self.profile_contract_digest),
        ):
            if not _DIGEST_REF_RE.fullmatch(digest):
                raise ValueError(f"{label} must be sha256:<64 lowercase hex>")

        envelope = _load_json_object("envelope_contract_bytes", self.envelope_contract_bytes)
        if _git_blob_sha(self.envelope_contract_bytes) != ARCS_SRS_VNEXT_ENVELOPE_GIT_BLOB:
            raise ValueError("envelope_contract_bytes do not match the pinned ARCS SRS vNext blob")
        if envelope.get("$id") != _SUPPORTED_ENVELOPE_SCHEMA_ID:
            raise ValueError("pinned envelope schema id mismatch")
        properties = envelope.get("properties")
        if not isinstance(properties, dict):
            raise ValueError("pinned envelope schema properties missing")
        if properties.get("envelope_schema_version", {}).get("const") != ENVELOPE_SCHEMA_VERSION:
            raise ValueError("pinned envelope schema version mismatch")
        if properties.get("receipt_version", {}).get("const") != "srs.core.v5.1":
            raise ValueError("pinned envelope receipt_version mismatch")
        expected_envelope_digest = _sha256_ref(self.envelope_contract_bytes)
        if self.envelope_contract_digest != expected_envelope_digest:
            raise ValueError("envelope_contract_digest does not match envelope_contract_bytes")

        profile = _load_json_object("profile_contract_bytes", self.profile_contract_bytes)
        permitted, classifications = _validate_profile_declaration(
            profile,
            expected_envelope_sha256=expected_envelope_digest.removeprefix("sha256:"),
        )
        if profile.get("profile_id") != self.profile_id:
            raise ValueError("profile_id does not match profile contract bytes")
        if profile.get("profile_version") != self.profile_version:
            raise ValueError("profile_version does not match profile contract bytes")
        if profile.get("extension_namespace") != self.extension_namespace:
            raise ValueError("extension_namespace does not match profile contract bytes")
        for expected in (self.admission_receipt_type, self.outcome_receipt_type):
            if expected not in permitted:
                raise ValueError(f"profile does not permit configured receipt type: {expected}")
        for receipt_type, receipt_kind in (
            (self.admission_receipt_type, "admission"),
            (self.outcome_receipt_type, "outcome"),
        ):
            if (receipt_type, receipt_kind) not in classifications and (
                receipt_type,
                None,
            ) not in classifications:
                raise ValueError(
                    f"profile classification does not cover {receipt_kind} receipt type"
                )

        expected_profile_digest = _sha256_ref(self.profile_contract_bytes)
        if self.profile_contract_digest != expected_profile_digest:
            raise ValueError("profile_contract_digest does not match profile_contract_bytes")

    def receipt_type_for(self, receipt_kind: str) -> str:
        if receipt_kind == "admission":
            return self.admission_receipt_type
        if receipt_kind == "outcome":
            return self.outcome_receipt_type
        raise ReceiptContentError(
            f"unsupported external-profile receipt_kind: {receipt_kind!r}"
        )


class ExternalProfileSignedReceiptEmitter(SignedReceiptEmitter):
    """Signed MCP lifecycle emitter for an explicitly selected SRS vNext profile.

    ``emit_admission`` is inherited unchanged. ``emit_outcome`` preserves the
    existing lifecycle behavior but keeps binding-owned exception/delivery
    metadata inside the selected external namespace rather than assuming legacy
    top-level/bare-``mcp`` slots. The common envelope projection is replaced for
    both receipt kinds.
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
        # binding/subject-origin guards. Replace every profile/carrier-owned
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
        # namespace. Moving this neutral binding-version observation does not
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

    def _apply_binding_owned_fields(
        self,
        envelope: dict[str, Any],
        *,
        outcome: str,
        binding_owned_fields: Mapping[str, bool] | None,
    ) -> None:
        """Project SDK-v2 delivery facts into the open namespaced extension.

        The historical v0.2.1 emitter serialized these three Boolean facts at
        top level. Envelope v0-next is top-level ``additionalProperties:false``
        and does not define those legacy slots, while its ``extensions`` member
        is explicitly open for namespaced evolution. The vNext projection keeps
        the same facts but moves them under ``delivery_state`` rather than
        reopening or mutating the reviewed envelope schema.
        """

        if not binding_owned_fields:
            return
        if outcome != "indeterminate":
            raise ReceiptContentError(
                "cancellation fields are permitted only on indeterminate outcomes"
            )
        projected: dict[str, bool] = {}
        for key, value in binding_owned_fields.items():
            if key not in CANCELLATION_FIELD_NAMES:
                raise ReceiptContentError(f"unknown binding-owned field: {key}")
            if type(value) is not bool:
                raise ReceiptContentError(
                    f"binding-owned field must be boolean: {key}"
                )
            projected[key] = value
        extension = envelope["extensions"][self.contract.extension_namespace]
        extension["delivery_state"] = projected

    def emit_outcome(
        self,
        *,
        context: ReceiptContext,
        admission_receipt_ref: str,
        outcome: str,
        result_digest: str | None = None,
        exception_class: str | None = None,
        additional_attestation_limits: Sequence[str] = (),
        binding_owned_fields: Mapping[str, bool] | None = None,
    ) -> str:
        """Emit an outcome without reintroducing legacy bare/top-level extensions."""

        envelope = self._common(
            context,
            receipt_kind="outcome",
            artifact_class="tool_call_outcome",
        )
        envelope.update(
            {
                "admission_receipt_ref": admission_receipt_ref,
                "outcome": outcome,
            }
        )
        if result_digest:
            envelope["result_digest"] = result_digest
        if exception_class:
            extension = envelope["extensions"][self.contract.extension_namespace]
            extension["exception_class"] = exception_class
        if outcome in {"result_returned", "error_returned"}:
            envelope["attestation_limits"].append(RESULT_LIMIT)
        if outcome == "task_submitted":
            envelope["attestation_limits"].append(TASK_LIMIT)
        self._append_attestation_limits(envelope, additional_attestation_limits)
        self._apply_binding_owned_fields(
            envelope,
            outcome=outcome,
            binding_owned_fields=binding_owned_fields,
        )
        enforce_raw_content_exclusion(envelope)
        signed = self.identity.sign_envelope(envelope)
        return self.sink.write(signed)
