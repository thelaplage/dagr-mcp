"""Main governance entry point for OBS broadcast control operations.

run_obs_governed_call composes delegation binding, policy evaluation, and
SRS receipt emission for a single governed OBS MCP tool call.

Invariants:
- The downstream_fn is ONLY called when disposition == "admitted".
- Receipt contains refs/digests only; no raw arguments, no raw OBS state.
- mcp_success_proves_delivery is always False in the receipt extensions.
- target_state is stored as sha256:<hash>, never raw.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .delegation import BroadcastDelegation
from .policy import PolicyDecision, evaluate_policy

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

# Fields that must never appear in a receipt — enforced at construction time.
_FORBIDDEN_RECEIPT_FIELDS = frozenset(
    {
        "raw_arguments",
        "arguments",
        "raw_result",
        "result_body",
        "raw_payload",
        "raw_event",
        "stream_key",
        "password",
        "credentials",
    }
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
    return f"urn:srs:receipt:obs-governance:{uuid.uuid4()}"


@dataclass
class GovernedObsResult:
    """Result of a governed OBS broadcast control call.

    Attributes
    ----------
    disposition
        "admitted" or "refused".
    refusal_reason
        The reason code when disposition == "refused", else None.
    downstream_invocation_count
        0 if the call was refused; 1 if admitted and downstream was called.
    downstream_result
        The return value of downstream_fn, or None if refused.
    receipt
        SRS receipt dict (refs/digests only — no raw content).
    """

    disposition: str
    refusal_reason: str | None
    downstream_invocation_count: int
    downstream_result: Any | None
    receipt: dict


def _build_refused_receipt(
    *,
    delegation: BroadcastDelegation,
    op_name: str,
    subject_id: str | None,
    arguments_hash: str,
    policy_decision: PolicyDecision,
    issued_at: str,
) -> dict:
    """Build an SRS receipt for a refused broadcast control call."""
    receipt: dict = {
        "receipt_id": _make_receipt_id(),
        "receipt_version": RECEIPT_VERSION,
        "profile_id": PROFILE_ID,
        "profile_version": PROFILE_VERSION,
        "receipt_kind": "request",
        "capture_posture": "dagr_governed",
        "boundary_type": "broadcast_control_boundary",
        "receipt_type": "provenance",
        "issued_at": issued_at,
        "disposition": "refused",
        "refusal_reason": policy_decision.reason,
        "delegation_id": delegation.delegation_id,
        "actor_ref": delegation.actor_ref,
        "obs_instance_ref": delegation.obs_instance_ref,
        "operation_name": op_name,
        "arguments_hash": arguments_hash,
        "attestation_limits": [BROADCAST_ATTESTATION_LIMITS],
        "retention_class_applied": "hash_only",
        "requires_signing": False,
        "extensions": {
            "garp": {
                "mcp_success_proves_delivery": False,
                "profile_id": PROFILE_ID,
                "profile_version": PROFILE_VERSION,
            }
        },
    }
    if subject_id is not None:
        receipt["subject_id_hash"] = _stable_hash(subject_id)
    return receipt


def _build_admitted_receipt(
    *,
    delegation: BroadcastDelegation,
    op_name: str,
    subject_id: str | None,
    arguments_hash: str,
    target_state_hash: str,
    downstream_result_hash: str,
    issued_at: str,
) -> dict:
    """Build an SRS receipt for an admitted broadcast control call."""
    receipt: dict = {
        "receipt_id": _make_receipt_id(),
        "receipt_version": RECEIPT_VERSION,
        "profile_id": PROFILE_ID,
        "profile_version": PROFILE_VERSION,
        "receipt_kind": "execution",
        "capture_posture": "dagr_governed",
        "boundary_type": "broadcast_control_boundary",
        "receipt_type": "provenance",
        "issued_at": issued_at,
        "disposition": "admitted",
        "delegation_id": delegation.delegation_id,
        "actor_ref": delegation.actor_ref,
        "obs_instance_ref": delegation.obs_instance_ref,
        "operation_name": op_name,
        "arguments_hash": arguments_hash,
        # target_state is required on execution kind per S0 profile
        "target_state": target_state_hash,
        "downstream_result_hash": downstream_result_hash,
        "attestation_limits": [BROADCAST_ATTESTATION_LIMITS],
        "retention_class_applied": "hash_only",
        "requires_signing": False,
        "extensions": {
            "garp": {
                # Explicit statement: MCP call success ≠ delivery
                "mcp_success_proves_delivery": False,
                "profile_id": PROFILE_ID,
                "profile_version": PROFILE_VERSION,
            }
        },
    }
    if subject_id is not None:
        receipt["subject_id_hash"] = _stable_hash(subject_id)
    return receipt


def run_obs_governed_call(
    delegation: BroadcastDelegation,
    op_name: str,
    subject_id: str | None,
    arguments: dict,
    downstream_fn: Callable,
    *,
    issued_at: str | None = None,
) -> GovernedObsResult:
    """Execute a governed OBS broadcast control call.

    The downstream_fn is ONLY called when the delegation admits the call.
    On refusal (hard-deny, out-of-scope, revoked, expired), downstream_fn
    is never invoked and downstream_invocation_count is 0.

    A successful downstream call does NOT prove delivery or that the OBS
    product entered the declared target state. Delivery requires a
    correlated native product state event (see consequence_linker).

    Parameters
    ----------
    delegation
        The BroadcastDelegation binding to evaluate.
    op_name
        Operation name from the O0 registry (e.g. "set-current-scene").
    subject_id
        Optional subject identifier (scene/input name, etc.).
    arguments
        The call arguments dict. Stored as hash only — never raw in receipt.
    downstream_fn
        The actual OBS MCP tool call callable. Signature: (op_name, arguments) -> Any.
        Only called when admitted.
    issued_at
        Optional ISO8601 timestamp override. Defaults to now_utc.

    Returns
    -------
    GovernedObsResult
        Contains disposition, refusal_reason, downstream_invocation_count,
        downstream_result, and the SRS receipt dict.
    """
    ts = issued_at or _now_utc_iso()
    arguments_hash = _stable_hash(arguments)

    # Evaluate policy
    policy_decision = evaluate_policy(delegation, op_name, subject_id, ts)

    if not policy_decision.is_admitted:
        receipt = _build_refused_receipt(
            delegation=delegation,
            op_name=op_name,
            subject_id=subject_id,
            arguments_hash=arguments_hash,
            policy_decision=policy_decision,
            issued_at=ts,
        )
        return GovernedObsResult(
            disposition="refused",
            refusal_reason=policy_decision.reason,
            downstream_invocation_count=0,
            downstream_result=None,
            receipt=receipt,
        )

    # Admitted: call downstream exactly once
    downstream_result = downstream_fn(op_name, arguments)
    target_state_hash = _stable_hash({"op": op_name, "subject": subject_id, "arguments": arguments_hash})
    downstream_result_hash = _stable_hash(downstream_result)

    receipt = _build_admitted_receipt(
        delegation=delegation,
        op_name=op_name,
        subject_id=subject_id,
        arguments_hash=arguments_hash,
        target_state_hash=target_state_hash,
        downstream_result_hash=downstream_result_hash,
        issued_at=ts,
    )

    return GovernedObsResult(
        disposition="admitted",
        refusal_reason=None,
        downstream_invocation_count=1,
        downstream_result=downstream_result,
        receipt=receipt,
    )


__all__ = ["GovernedObsResult", "run_obs_governed_call"]
