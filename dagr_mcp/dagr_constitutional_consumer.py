"""dagr-mcp constitutional alignment — DAGR-MIGRATION-WAVE-0 L10.

Declares dagr-mcp's role as the SRS receipt emitter under the DAGR
Constitutional Contract v0.1. dagr-mcp owns emission, not verification,
policy authority, or semantic truth.

emitting a receipt != verifying it != it being true
emitter != verifier != constitutional authority

Exports:
  - DAGR_CONSTITUTIONAL_CONTRACT_ID / _STATUS
  - EMITTER_ROLE, EMITTER_DOMAIN
  - DOMAIN_NEQ_ASSERTIONS  (domain-qualified; constitutional form per L00 NEQ-09 pattern)
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Constitutional contract reference
# ---------------------------------------------------------------------------

DAGR_CONSTITUTIONAL_CONTRACT_ID = "dagr.constitutional-contract.v0.1"
DAGR_CONSTITUTIONAL_CONTRACT_STATUS = "DRAFT R1 (Lane 00 / DAGR-MIGRATION-WAVE-0)"

# ---------------------------------------------------------------------------
# Emitter role declaration
# ---------------------------------------------------------------------------

EMITTER_ROLE = "srs_receipt_emitter"
EMITTER_DOMAIN = "mcp_action"

# ---------------------------------------------------------------------------
# Domain-qualified NEQ assertions (constitutional form, per L00 NEQ-09 pattern)
# ---------------------------------------------------------------------------

DOMAIN_NEQ_ASSERTIONS: tuple[str, ...] = (
    # Emitting a receipt != verifying it
    "mcp_action:emitting_receipt != arcs:verifying_receipt",
    # Receipt present != action was permitted
    "mcp_action:receipt_present != action:permitted",
    # Receipt present != action is true
    "mcp_action:receipt_present != action:factually_true",
    # Emitter != verifier (producer/verifier independence is inviolate)
    "mcp_action:srs_receipt_emitter != arcs:verifier",
    # Emitter != constitutional authority
    "mcp_action:srs_receipt_emitter != dagr:constitutional_authority",
    # Refused/failed receipt != success
    "mcp_action:refused_receipt != action:permitted",
    "mcp_action:deferred_receipt != action:permitted",
    # Signing a receipt != certifying the real-world event occurred
    "mcp_action:signed_receipt != real_world:event_occurred",
    # SRS profile compliance != semantic truth of the action
    "mcp_action:srs_profile_compliant != action:factually_true",
    # Verifier reference in receipt != independent recomputed verification
    "mcp_action:verifier_reference != arcs:recomputed_finding",
    # Admission disposition != evidence standing
    "mcp_action:admitted != evidence:SUPPORTED",
    "mcp_action:refused != evidence:CONTRADICTED",
)
