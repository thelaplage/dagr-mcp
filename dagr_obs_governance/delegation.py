"""BroadcastDelegation — scoped delegation binding for OBS broadcast control operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _parse_iso(ts: str) -> datetime:
    """Parse ISO8601 timestamp, returning a UTC-aware datetime."""
    # Handle trailing Z
    normalized = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


@dataclass(frozen=True)
class BroadcastDelegation:
    """A scoped, time-bounded delegation binding for OBS broadcast control operations.

    Fields
    ------
    delegation_id
        Stable opaque identifier for this delegation binding.
    actor_ref
        Reference to the agent/actor this delegation is issued to.
        e.g. "actor:agent/demo-broadcaster"
    obs_instance_ref
        Reference to the specific OBS instance this delegation covers.
        e.g. "obs:local/default"
    scene_collection
        Optional: the OBS scene collection this delegation is scoped to.
        None means any scene collection is permitted.
    operation_family
        Frozenset of allowed operation names from the OBS operation registry.
    subject_ids
        Optional: frozenset of permitted subject IDs (scene names, input names, etc.).
        None means any subject is permitted within the operation family.
    valid_from
        ISO8601 timestamp; delegation is not valid before this time.
    valid_until
        ISO8601 timestamp; delegation expires at this time.
    revoked
        If True, this delegation has been revoked and no calls may proceed.
    """

    delegation_id: str
    actor_ref: str
    obs_instance_ref: str
    scene_collection: str | None
    operation_family: frozenset[str]
    subject_ids: frozenset[str] | None
    valid_from: str
    valid_until: str
    revoked: bool = False

    def is_valid_at(self, iso_timestamp: str) -> bool:
        """Return True if this delegation is temporally valid at the given timestamp.

        A revoked delegation is never valid.
        """
        if self.revoked:
            return False
        try:
            ts = _parse_iso(iso_timestamp)
            from_dt = _parse_iso(self.valid_from)
            until_dt = _parse_iso(self.valid_until)
        except (ValueError, TypeError):
            return False
        return from_dt <= ts <= until_dt

    def allows_operation(self, op_name: str) -> bool:
        """Return True if op_name is within this delegation's operation family."""
        return op_name in self.operation_family

    def allows_subject(self, subject_id: str | None) -> bool:
        """Return True if subject_id is permitted by this delegation.

        If subject_ids is None, any subject is permitted.
        If subject_id is None, it is permitted when there is no subject restriction.
        """
        if self.subject_ids is None:
            return True
        if subject_id is None:
            # No specific subject requested; permitted when no restriction.
            return True
        return subject_id in self.subject_ids


__all__ = ["BroadcastDelegation"]
