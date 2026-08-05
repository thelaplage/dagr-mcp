"""consequence_linker — links an execution receipt to an OBS native event.

The link_consequence function creates an observed_consequence receipt that
correlates a governed execution receipt with a native OBS product state event.

Invariants:
- native_event_ref is stored as sha256 of the event dict, NOT the raw event.
- No raw OBS event payload is stored in the receipt.
- receipt_kind is always "observed_consequence".
- A successful downstream call does NOT prove delivery; this linker is the
  mechanism for asserting a correlated native event, still as hash-only.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

PROFILE_ID = "srs.broadcast_control"
PROFILE_VERSION = "v0.1"
RECEIPT_VERSION = "srs.core.v5.1"

BROADCAST_ATTESTATION_LIMITS = (
    "The receipt declares a governed broadcast control operation under the "
    "srs.broadcast_control profile. It does not independently establish that "
    "the broadcast product received, executed, or entered the declared target "
    "state. MCP call success does not establish delivery; delivery requires a "
    "correlated native product state event."
)


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_hash(obj: Any) -> str:
    """Return sha256:<hex> digest of the JSON-serialized object."""
    if isinstance(obj, bytes):
        raw = obj
    elif isinstance(obj, str):
        raw = obj.encode("utf-8")
    elif obj is None:
        raw = b"null"
    else:
        try:
            raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        except TypeError:
            raw = str(obj).encode("utf-8")
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _make_receipt_id() -> str:
    return f"urn:srs:receipt:obs-consequence:{uuid.uuid4()}"


def link_consequence(
    execution_receipt: dict,
    native_event: dict,
    *,
    consequence_window_ms: int = 5000,
) -> dict:
    """Return an observed_consequence receipt linking execution to a native OBS event.

    The native_event dict is hashed and stored as a sha256 ref only. The raw
    event dict is NEVER stored in the receipt.

    Parameters
    ----------
    execution_receipt
        The execution receipt dict from run_obs_governed_call (disposition="admitted").
    native_event
        The OBS native event dict (references only — no raw payload stored).
        Stored as sha256:<hash> in the consequence receipt.
    consequence_window_ms
        Maximum time window in milliseconds between execution and native event.
        Stored in the receipt for verifier use; not enforced here.

    Returns
    -------
    dict
        An observed_consequence SRS receipt. receipt_kind == "observed_consequence".
        native_event_ref is sha256 of the event dict, not the raw event.
    """
    # Hash the native event — raw event never enters the receipt
    native_event_ref = _stable_hash(native_event)

    issued_at = _now_utc_iso()

    receipt: dict = {
        "receipt_id": _make_receipt_id(),
        "receipt_version": RECEIPT_VERSION,
        "profile_id": PROFILE_ID,
        "profile_version": PROFILE_VERSION,
        "receipt_kind": "observed_consequence",
        "capture_posture": "dagr_governed",
        "boundary_type": "broadcast_control_boundary",
        "receipt_type": "provenance",
        "issued_at": issued_at,
        # Link back to the execution receipt
        "execution_receipt_id": execution_receipt.get("receipt_id"),
        "delegation_id": execution_receipt.get("delegation_id"),
        "actor_ref": execution_receipt.get("actor_ref"),
        "obs_instance_ref": execution_receipt.get("obs_instance_ref"),
        "operation_name": execution_receipt.get("operation_name"),
        # Native event reference — hash only, never raw
        "native_event_ref": native_event_ref,
        "consequence_window_ms": consequence_window_ms,
        # target_state required on observed_consequence kind per S0 profile
        "target_state": execution_receipt.get("target_state"),
        "attestation_limits": [BROADCAST_ATTESTATION_LIMITS],
        "retention_class_applied": "hash_only",
        "requires_signing": False,
        "extensions": {
            "garp": {
                "mcp_success_proves_delivery": False,
                "profile_id": PROFILE_ID,
                "profile_version": PROFILE_VERSION,
                "consequence_correlated": True,
            }
        },
    }

    return receipt


__all__ = ["link_consequence"]
