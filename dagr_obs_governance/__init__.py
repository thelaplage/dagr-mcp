"""dagr_obs_governance — DAGR enforcement harness composition for the OBS broadcast control surface.

This package composes the existing dagr_mcp enforcement harness around the narrow
OBS MCP control surface defined by the srs.broadcast_control.v0.1 profile.

It does NOT reimplement Gateway policy evaluation and does NOT modify any existing module.
"""

from .delegation import BroadcastDelegation
from .governance import GovernedObsResult, run_obs_governed_call
from .policy import (
    ALLOWED_MIXED_OPS,
    ALLOWED_SCENE_OPS,
    HARD_DENY_OPS,
    HIGHER_SCOPE_OPS,
    PolicyDecision as ObsPolicyDecision,
    evaluate_policy,
)

__all__ = [
    "ALLOWED_MIXED_OPS",
    "ALLOWED_SCENE_OPS",
    "BroadcastDelegation",
    "GovernedObsResult",
    "HARD_DENY_OPS",
    "HIGHER_SCOPE_OPS",
    "ObsPolicyDecision",
    "evaluate_policy",
    "run_obs_governed_call",
]
