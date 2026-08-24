"""CG execution packet ref extension for SRS envelopes — EXECUTION-BINDING0 L07.

Builds and validates the extensions.cg.execution_packet_ref sub-object per
schemas/cg-extensions/v0.1/srs.cg.execution_packet_ref.v0.1.schema.json
(authority: arcs-srs).

REF-ONLY discipline: only the digest reference is carried in the receipt —
no raw packet content, no result bytes, no claim payload. Consistent with
the SRS retention_class_applied: "hash_only" posture.

Vocabulary (EXECUTION-BINDING-VOCAB0):
  ref != replay, replay != truth, digest_present != replay_complete
  This object carries NO authority claim: authority_effect (and any other
  authority-shaped key) is structurally absent, never a pinned "none" value.
  Structural absence is enforced fail-closed: any attempt to inject an
  authority-shaped or otherwise unrecognized key into execution_packet_ref
  is rejected by validate_cg_extension (NE-11 remediation).

Usage::

    from dagr_mcp.cg_extension import build_cg_extension

    # Call build_cg_extension with the digest and packet_id you retained at
    # CG query time, then pass the result as extensions= to any receipt builder.
    ext = build_cg_extension(
        execution_packet_digest="sha256:<64 hex>",
        packet_id="cg:execution-packet:sha256:<same 64 hex>",
    )
    # ext == {"cg": {"execution_packet_ref": {"execution_packet_digest": ...,
    #                                          "packet_id": ...}}}
    receipt = builder.build_activity_governed_read(..., extensions=ext)
"""

from __future__ import annotations

import re
from typing import Any

_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_PACKET_ID_PATTERN = re.compile(r"^cg:execution-packet:sha256:[0-9a-f]{64}$")
_SHA256_PREFIX = "sha256:"
_PACKET_ID_PREFIX = "cg:execution-packet:sha256:"

_EXTENSION_KEY = "cg"
_EXEC_PACKET_REF_KEY = "execution_packet_ref"
# REF-ONLY discipline, enforced fail-closed: execution_packet_ref carries
# exactly these two reference fields and nothing else. This structurally
# excludes authority_effect and every other authority-shaped key (NE-11) —
# there is no value that makes this object an authority claim, so the field
# does not exist on it at all.
_ALLOWED_REF_KEYS = frozenset({"execution_packet_digest", "packet_id"})


class CGExtensionError(ValueError):
    """Raised when a CG extension constraint is violated."""


def build_cg_extension(
    execution_packet_digest: str,
    packet_id: str,
) -> dict[str, Any]:
    """Build a validated extensions.cg sub-object for an SRS receipt.

    REF-ONLY: only the digest reference is carried, never raw content.
    Carries no authority claim: authority_effect is structurally absent,
    not a pinned "none" — EXECUTION-BINDING-VOCAB0 / NE-11.

    Args:
        execution_packet_digest: sha256 digest of the CG execution packet.
            Format: "sha256:<64 lowercase hex>".
        packet_id: stable packet identifier encoding the digest.
            Format: "cg:execution-packet:sha256:<same 64 hex>".

    Returns:
        dict suitable for use as the extensions= kwarg of any dagr-mcp receipt
        builder: ``{"cg": {"execution_packet_ref": {...}}}``.

    Raises:
        CGExtensionError: if any input violates REF-ONLY or format constraints.
    """
    if not isinstance(execution_packet_digest, str) or not _SHA256_PATTERN.match(
        execution_packet_digest
    ):
        raise CGExtensionError(
            f"execution_packet_digest must be sha256:<64 lowercase hex>; "
            f"got {execution_packet_digest!r}"
        )

    if not isinstance(packet_id, str) or not _PACKET_ID_PATTERN.match(packet_id):
        raise CGExtensionError(
            f"packet_id must be cg:execution-packet:sha256:<64 lowercase hex>; "
            f"got {packet_id!r}"
        )

    # packet_id must encode the same hex as execution_packet_digest.
    hex_from_digest = execution_packet_digest[len(_SHA256_PREFIX):]
    hex_from_packet_id = packet_id[len(_PACKET_ID_PREFIX):]
    if hex_from_digest != hex_from_packet_id:
        raise CGExtensionError(
            "packet_id must encode the same hex as execution_packet_digest; "
            f"digest hex={hex_from_digest!r}, packet_id hex={hex_from_packet_id!r}"
        )

    return {
        _EXTENSION_KEY: {
            _EXEC_PACKET_REF_KEY: {
                "execution_packet_digest": execution_packet_digest,
                "packet_id": packet_id,
            }
        }
    }


def validate_cg_extension(extensions: dict[str, Any] | None) -> None:
    """Validate extensions.cg.execution_packet_ref if present.

    Called by receipt builders to guard the CG extension sub-object.
    A missing or None extensions dict passes silently. Only raises when
    extensions["cg"] is present but malformed.

    Fail-closed REF-ONLY enforcement: execution_packet_ref may contain
    exactly {execution_packet_digest, packet_id} and nothing else. Any
    other key — including authority_effect or any other authority-shaped
    field (admission_effect, trust_effect, authorized, admitted, ...) — is
    rejected. This object carries no authority claim, not even a "none"
    one; the field is structurally absent, so injecting it is refused
    rather than accepted (NE-11).

    Raises:
        CGExtensionError: if extensions.cg is present but violates constraints.
    """
    if not extensions:
        return
    cg = extensions.get(_EXTENSION_KEY)
    if cg is None:
        return
    if not isinstance(cg, dict):
        raise CGExtensionError("extensions.cg must be a dict")
    ref = cg.get(_EXEC_PACKET_REF_KEY)
    if ref is None:
        return
    if not isinstance(ref, dict):
        raise CGExtensionError("extensions.cg.execution_packet_ref must be a dict")
    extra_keys = set(ref.keys()) - _ALLOWED_REF_KEYS
    if extra_keys:
        raise CGExtensionError(
            "extensions.cg.execution_packet_ref carries no authority claim "
            "and permits only execution_packet_digest and packet_id; "
            f"rejected unexpected/authority-shaped key(s): {sorted(extra_keys)!r}"
        )
    digest = ref.get("execution_packet_digest")
    if not isinstance(digest, str) or not _SHA256_PATTERN.match(digest):
        raise CGExtensionError(
            "extensions.cg.execution_packet_ref.execution_packet_digest "
            f"must be sha256:<64 hex>; got {digest!r}"
        )
    pid = ref.get("packet_id")
    if not isinstance(pid, str) or not _PACKET_ID_PATTERN.match(pid):
        raise CGExtensionError(
            "extensions.cg.execution_packet_ref.packet_id "
            f"must be cg:execution-packet:sha256:<64 hex>; got {pid!r}"
        )
    hex_d = digest[len(_SHA256_PREFIX):]
    hex_p = pid[len(_PACKET_ID_PREFIX):]
    if hex_d != hex_p:
        raise CGExtensionError(
            "extensions.cg.execution_packet_ref.packet_id does not encode "
            "execution_packet_digest"
        )


__all__ = [
    "CGExtensionError",
    "build_cg_extension",
    "validate_cg_extension",
]
