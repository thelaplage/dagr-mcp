"""Signed SRS receipt construction for the MCP admission profile."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import rfc8785
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

RECEIPT_VERSION = "srs.core.v5.1"
PROFILE_ID = "srs.mcp.sdk_enforcement"
PROFILE_VERSION = "v0.1"
SIGNATURE_ALGORITHM = "Ed25519"
CANONICALIZATION = "RFC8785-JCS"
TRUST_BUNDLE_VERSION = "srs.trust_bundle.v0.1"
RESULT_LIMIT = (
    "The receipt establishes the request, admission disposition, and semantic result "
    "returned at the configured boundary. It does not independently establish that "
    "the underlying tool body executed for this invocation, because middleware such "
    "as caches may satisfy a call without handler execution."
)
TASK_LIMIT = (
    "The receipt establishes admission and submission to the configured task backend. "
    "It does not establish execution or completion."
)
BASE_LIMIT = "The receipt attests only to governance conditions at the named admission boundary."
RAW_KEYS = frozenset({
    "prompt_text", "transcript", "raw_payload", "tool_arguments", "arguments",
    "result_body", "headers", "prompt", "raw_prompt", "raw_output", "result",
    "tool_result", "request_body", "response_body", "access_token", "private_key",
    "credential_secret", "client_secret", "refresh_token", "api_key", "password",
})
PRIVATE_MARKERS = (
    "/" + "Users" + "/",
    "/" + "home" + "/",
    "/" + "private" + "/" + "var",
    "C:" + "\\" + "\\",
    "~" + "/" + "garp-",
    "~" + "/" + "arcs-anchor",
)
EXCLUDED_CLASSES = ["raw_prompt", "raw_output", "raw_tool_arguments", "raw_tool_result"]
_SAFE_FILE = re.compile(r"[^A-Za-z0-9._-]+")


class ReceiptContentError(ValueError):
    """Receipt contains a prohibited raw-content field or private reference."""


class ReceiptWriteError(RuntimeError):
    """Receipt could not be durably accepted by the configured sink."""


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def sha256_digest(value: Any) -> str:
    try:
        canonical = rfc8785.dumps(value)
    except Exception as exc:
        raise ReceiptContentError("value is not RFC 8785 canonicalizable") from exc
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _walk(value: Any):
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key), item
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield None, item
            yield from _walk(item)


def enforce_raw_content_exclusion(value: Any) -> None:
    for key, item in _walk(value):
        if key in RAW_KEYS:
            raise ReceiptContentError(f"forbidden raw-content key: {key}")
        if isinstance(item, str) and any(marker in item for marker in PRIVATE_MARKERS):
            raise ReceiptContentError("private reference marker is prohibited")


def now_utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class SigningIdentity:
    issuer_id: str
    key_id: str
    private_key: Ed25519PrivateKey
    not_before: str = "2026-01-01T00:00:00Z"
    not_after: str = "2036-01-01T00:00:00Z"

    @classmethod
    def generate(cls, *, issuer_id: str, key_id: str) -> "SigningIdentity":
        return cls(issuer_id=issuer_id, key_id=key_id, private_key=Ed25519PrivateKey.generate())

    def public_key_bytes(self) -> bytes:
        return self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def trust_bundle(self) -> dict[str, Any]:
        return {
            "trust_bundle_version": TRUST_BUNDLE_VERSION,
            "issuers": [{
                "issuer_id": self.issuer_id,
                "key_id": self.key_id,
                "algorithm": SIGNATURE_ALGORITHM,
                "public_key": b64url_encode(self.public_key_bytes()),
                "not_before": self.not_before,
                "not_after": self.not_after,
                "trusted": True,
            }],
        }

    def sign_envelope(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        signed = copy.deepcopy(dict(envelope))
        signed["receipt_signature"] = {
            "algorithm": SIGNATURE_ALGORITHM,
            "canonicalization": CANONICALIZATION,
            "key_id": self.key_id,
            "signature": "",
        }
        preimage = copy.deepcopy(signed)
        del preimage["receipt_signature"]["signature"]
        try:
            canonical = rfc8785.dumps(preimage)
        except Exception as exc:
            raise ReceiptContentError("preimage_canonicalization_failed") from exc
        signed["receipt_signature"]["signature"] = b64url_encode(self.private_key.sign(canonical))
        enforce_raw_content_exclusion(signed)
        return signed


@dataclass(frozen=True, slots=True)
class ReceiptContext:
    runtime_instance_id: str
    boundary_id: str
    policy_pack_id: str
    policy_pack_version: str
    subject_ref: str
    logical_call_id: str
    actor_ref: str | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None


class RawEnvelopeFileSink:
    """Atomic one-envelope-per-file sink.

    No private signing key is persisted. Receipt and trust-bundle files contain
    public or hash-only material and are written with owner-only permissions.
    """

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            self.directory.chmod(0o700)
        except OSError:
            pass

    def write(self, envelope: Mapping[str, Any]) -> str:
        enforce_raw_content_exclusion(envelope)
        receipt_id = str(envelope["receipt_id"])
        filename = _SAFE_FILE.sub("_", receipt_id) + ".json"
        target = self.directory / filename
        payload = json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        fd, tmp_name = tempfile.mkstemp(prefix=".receipt-", suffix=".tmp", dir=self.directory)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        except Exception as exc:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise ReceiptWriteError("receipt sink write failed") from exc
        return receipt_id

    def write_trust_bundle(self, bundle: Mapping[str, Any], filename: str = "issuer-keys.json") -> Path:
        if any(key in json.dumps(bundle).lower() for key in ("private_key", "secret", "seed")):
            raise ReceiptContentError("trust bundle contains private material")
        target = self.directory / filename
        payload = json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        fd, tmp_name = tempfile.mkstemp(prefix=".bundle-", suffix=".tmp", dir=self.directory)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return target


class SignedReceiptEmitter:
    def __init__(self, *, identity: SigningIdentity, sink: RawEnvelopeFileSink):
        self.identity = identity
        self.sink = sink

    def _common(self, context: ReceiptContext, *, receipt_kind: str, artifact_class: str) -> dict[str, Any]:
        envelope: dict[str, Any] = {
            "receipt_version": RECEIPT_VERSION,
            "profile_id": PROFILE_ID,
            "profile_version": PROFILE_VERSION,
            "receipt_id": f"urn:srs:receipt:{receipt_kind}:{uuid.uuid4()}",
            "receipt_type": "sdk_enforcement",
            "receipt_kind": receipt_kind,
            "boundary_type": "mcp_tool_call",
            "protocol_binding": "mcp",
            "subject_ref": context.subject_ref,
            "issuer_id": self.identity.issuer_id,
            "runtime_instance_id": context.runtime_instance_id,
            "boundary_id": context.boundary_id,
            "logical_call_id": context.logical_call_id,
            "issued_at": now_utc_iso(),
            "artifact_classes_covered": [artifact_class],
            "artifact_classes_excluded": list(EXCLUDED_CLASSES),
            "attestation_limits": [BASE_LIMIT],
            "retention_class_applied": "hash_only",
            "extensions": {"mcp": {"binding_version": "direct-harness.v0.1"}},
        }
        if context.actor_ref:
            envelope["actor_ref"] = context.actor_ref
        if context.tenant_id:
            envelope["tenant_id"] = context.tenant_id
        if context.workspace_id:
            envelope["workspace_id"] = context.workspace_id
        return envelope

    def emit_admission(
        self,
        *,
        context: ReceiptContext,
        requested_tool_name: str,
        argument_digest: str,
        disposition: str,
        review_object_ref: str | None = None,
        retry_contract: str | None = None,
        reason_code: str | None = None,
    ) -> str:
        envelope = self._common(context, receipt_kind="admission", artifact_class="tool_call_admission")
        envelope.update({
            "requested_tool_name": requested_tool_name,
            "tool_resolution_status": "not_observed",
            "argument_digest": argument_digest,
            "policy_pack_id": context.policy_pack_id,
            "policy_pack_version": context.policy_pack_version,
            "disposition": disposition,
        })
        if review_object_ref:
            envelope["review_object_ref"] = review_object_ref
        if retry_contract:
            envelope["retry_contract"] = retry_contract
        if reason_code:
            envelope["reason_code"] = reason_code
        signed = self.identity.sign_envelope(envelope)
        return self.sink.write(signed)

    def emit_outcome(
        self,
        *,
        context: ReceiptContext,
        admission_receipt_ref: str,
        outcome: str,
        result_digest: str | None = None,
        exception_class: str | None = None,
    ) -> str:
        envelope = self._common(context, receipt_kind="outcome", artifact_class="tool_call_outcome")
        envelope.update({
            "admission_receipt_ref": admission_receipt_ref,
            "outcome": outcome,
        })
        if result_digest:
            envelope["result_digest"] = result_digest
        if exception_class:
            envelope["extensions"]["mcp"]["exception_class"] = exception_class
        if outcome in {"result_returned", "error_returned"}:
            envelope["attestation_limits"].append(RESULT_LIMIT)
        if outcome == "task_submitted":
            envelope["attestation_limits"].append(TASK_LIMIT)
        signed = self.identity.sign_envelope(envelope)
        return self.sink.write(signed)
