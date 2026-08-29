"""dagr-mcp constitutional alignment — DAGR-MIGRATION-WAVE-0 L10.

Disposition B / DAGR-MCP-CONSTITUTION-RECON1 keeps the historical L10
consumer labels byte-for-byte for provenance while removing any implication
that they are the active constitutional frontier.

The shared DAGR constitutional grammar is owned by ``thelaplage/dagr-spec``.
The current v0.2 grammar there is PROPOSED / UNRATIFIED / NON-CANONICAL; this
consumer must not promote it, invent a replacement constitutional-contract id,
or manufacture a semantic mapping from the local ``mcp_action`` label to the
reserved DAGR ``action`` domain.

``mcp_action`` is therefore retained only as a consumer-local, presently
unbound historical emitter-context label. It is not a DAGR DomainRef value.

The SRS wire contract is unchanged: ``dagr_constitution_id`` remains
emitter-context-only and is not serialized into signed SRS receipts.

emitting a receipt != verifying it != it being true
emitter != verifier != constitutional authority

Exports:
  - DAGR_CONSTITUTIONAL_CONTRACT_ID / _STATUS
  - DAGR_CONSTITUTIONAL_CONTRACT_DEPRECATED
  - DAGR_CONSTITUTIONAL_GRAMMAR_OWNER / _STATUS
  - EMITTER_ROLE, EMITTER_DOMAIN, EMITTER_DOMAIN_SCOPE
  - DOMAIN_NEQ_ASSERTIONS
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Historical consumer contract reference / current grammar ownership
# ---------------------------------------------------------------------------

# Historical L10 consumer identifier retained byte-for-byte for provenance.
# It is not a dagr-spec ratification token and is not the active frontier.
DAGR_CONSTITUTIONAL_CONTRACT_ID = "dagr.constitutional-contract.v0.1"
DAGR_CONSTITUTIONAL_CONTRACT_STATUS = (
    "DEPRECATED / HISTORICAL L10 COMPATIBILITY (DAGR-MIGRATION-WAVE-0)"
)
DAGR_CONSTITUTIONAL_CONTRACT_DEPRECATED = True

# Ownership reference only. These declarations do not vendor dagr-spec
# semantics into this consumer and do not ratify the proposed v0.2 grammar.
DAGR_CONSTITUTIONAL_GRAMMAR_OWNER = "thelaplage/dagr-spec"
DAGR_CONSTITUTIONAL_GRAMMAR_STATUS = "PROPOSED / UNRATIFIED / NON-CANONICAL"

# ---------------------------------------------------------------------------
# Emitter role declaration
# ---------------------------------------------------------------------------

EMITTER_ROLE = "srs_receipt_emitter"
# Historical/local L10 label retained byte-for-byte. It is NOT a DAGR DomainRef
# and no ``mcp_action -> action`` equivalence or compatibility mapping is made.
EMITTER_DOMAIN = "mcp_action"
EMITTER_DOMAIN_SCOPE = "consumer_local_unbound"

# ---------------------------------------------------------------------------
# Historical/local NEQ assertions retained exactly from L10.
# These are consumer assertions; their presence does not make dagr-mcp the
# owner of constitutional semantics.
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
