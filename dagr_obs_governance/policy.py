"""Policy evaluation for OBS broadcast control operations.

Operation tiers (from dagr-pack-obs O0 registry):

HARD_DENY_OPS
    Operations that are unconditionally refused for any delegation under this
    governance module. Includes toggle operations (forbidden by srs.broadcast_control
    S0 profile) and operations excluded from the demo delegation scope.

ALLOWED_SCENE_OPS
    Scene routing operations that are permitted when within the delegation's
    operation family.

ALLOWED_MIXED_OPS
    Mixed state operations (mute, scene item enable) permitted when within the
    delegation's operation family and subject scope.

HIGHER_SCOPE_OPS
    Streaming/recording operations that require explicit inclusion in the
    delegation's operation_family; refused if not explicitly granted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .delegation import BroadcastDelegation

# Toggles are forbidden by srs.broadcast_control S0 profile.
# Additional hard-deny operations from the O0 registry:
# arbitrary_vendor_request, custom_event, arbitrary_hotkey,
# arbitrary_settings, persistent_data_write are never permitted.
# stop-stream is hard-denied for the demo delegation.
HARD_DENY_OPS: frozenset[str] = frozenset(
    {
        # Profile-forbidden: toggle operations
        "toggle",
        "toggle-mute",
        "toggle-stream",
        "toggle-record",
        "toggle-scene-item",
        "toggle-virtual-camera",
        "toggle-replay-buffer",
        # Registry hard-deny operations
        "arbitrary_vendor_request",
        "arbitrary-vendor-request",
        "custom_event",
        "custom-event",
        "arbitrary_hotkey",
        "arbitrary-hotkey",
        "arbitrary_settings",
        "arbitrary-settings",
        "persistent_data_write",
        "persistent-data-write",
        # Demo delegation: stop-stream is hard-denied
        "stop-stream",
    }
)

ALLOWED_SCENE_OPS: frozenset[str] = frozenset(
    {
        "set-current-scene",
        "set-preview-scene",
        "trigger-studio-transition",
    }
)

ALLOWED_MIXED_OPS: frozenset[str] = frozenset(
    {
        "set-input-mute",
        "set-scene-item-enabled",
    }
)

HIGHER_SCOPE_OPS: frozenset[str] = frozenset(
    {
        "start-stream",
        "start-record",
        "stop-record",
    }
)

PolicyDecisionValue = Literal[
    "admitted",
    "refused",
    "refused_revoked",
    "refused_out_of_scope",
    "refused_hard_deny",
]


@dataclass(frozen=True)
class PolicyDecision:
    """The result of evaluating broadcast control policy for a single call.

    Attributes
    ----------
    decision
        One of: "admitted", "refused", "refused_revoked",
        "refused_out_of_scope", "refused_hard_deny".
    reason
        Human-readable explanation for the decision.
    """

    decision: PolicyDecisionValue
    reason: str

    @property
    def is_admitted(self) -> bool:
        return self.decision == "admitted"


def evaluate_policy(
    delegation: BroadcastDelegation,
    op_name: str,
    subject_id: str | None,
    timestamp: str,
) -> PolicyDecision:
    """Evaluate broadcast control policy for a proposed operation.

    Evaluation order:
    1. Revocation check — refuses immediately if delegation.revoked.
    2. Validity window — refuses if timestamp is outside valid_from/valid_until.
    3. Hard-deny check — refuses operations in HARD_DENY_OPS unconditionally.
    4. Operation family check — refuses if op_name not in delegation.operation_family.
    5. Subject scope check — refuses if subject_id is outside delegation.subject_ids.
    6. Admits the operation.

    Parameters
    ----------
    delegation
        The BroadcastDelegation to evaluate against.
    op_name
        The operation name from the O0 registry (e.g. "set-current-scene").
    subject_id
        Optional subject identifier (scene name, input name, etc.).
    timestamp
        ISO8601 timestamp for the validity window check.
    """
    # Step 1: revocation
    if delegation.revoked:
        return PolicyDecision(
            decision="refused_revoked",
            reason="delegation_revoked",
        )

    # Step 2: validity window
    if not delegation.is_valid_at(timestamp):
        return PolicyDecision(
            decision="refused",
            reason="delegation_not_valid_at_timestamp",
        )

    # Step 3: hard-deny
    if op_name in HARD_DENY_OPS:
        return PolicyDecision(
            decision="refused_hard_deny",
            reason=f"operation_hard_denied:{op_name}",
        )

    # Step 4: operation family scope
    if not delegation.allows_operation(op_name):
        return PolicyDecision(
            decision="refused_out_of_scope",
            reason=f"operation_not_in_delegation_family:{op_name}",
        )

    # Step 5: subject scope
    if not delegation.allows_subject(subject_id):
        return PolicyDecision(
            decision="refused_out_of_scope",
            reason=f"subject_not_in_delegation_scope:{subject_id}",
        )

    # Step 6: admit
    return PolicyDecision(
        decision="admitted",
        reason="policy_admitted",
    )


__all__ = [
    "ALLOWED_MIXED_OPS",
    "ALLOWED_SCENE_OPS",
    "HARD_DENY_OPS",
    "HIGHER_SCOPE_OPS",
    "PolicyDecision",
    "PolicyDecisionValue",
    "evaluate_policy",
]
