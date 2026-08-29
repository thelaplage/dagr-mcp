"""L10 / RECON1: DAGR constitutional alignment tests for dagr-mcp.

Disposition B preserves historical L10 consumer labels as deprecated/local-only
provenance, references dagr-spec as the grammar owner, and proves that this
reconciliation does not alter signed SRS admission/outcome bytes.
"""
from __future__ import annotations

import hashlib

import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from dagr_mcp.dagr_constitutional_consumer import (
    DAGR_CONSTITUTIONAL_CONTRACT_DEPRECATED,
    DAGR_CONSTITUTIONAL_CONTRACT_ID,
    DAGR_CONSTITUTIONAL_CONTRACT_STATUS,
    DAGR_CONSTITUTIONAL_GRAMMAR_OWNER,
    DAGR_CONSTITUTIONAL_GRAMMAR_STATUS,
    DOMAIN_NEQ_ASSERTIONS,
    EMITTER_DOMAIN,
    EMITTER_DOMAIN_SCOPE,
    EMITTER_ROLE,
)
from dagr_mcp.srs_receipts import (
    ReceiptContext,
    SignedReceiptEmitter,
    SigningIdentity,
)


# Baseline commitments captured from exact main 1fdb61f7250c0623b90f84a6b090adcd426f294b
# before the disposition-B declaration change. The fixture below uses only
# deterministic inputs (fixed Ed25519 private key, ids, timestamp and digests).
_BASELINE_ADMISSION_CANONICAL_SHA256 = (
    "36fda5df4dbd3f7ba102d0ba98338ef6fd84226d596ce93c0537ef38ae6becd7"
)
_BASELINE_OUTCOME_CANONICAL_SHA256 = (
    "da59499007eed475affd1d6a8d613326836ede7a4200ff23dfc5d7bdbee4bb86"
)


# ---------------------------------------------------------------------------
# Constitutional / ownership declarations
# ---------------------------------------------------------------------------

class TestConstitutionalConstants:
    def test_historical_contract_id_is_retained_exactly(self):
        assert DAGR_CONSTITUTIONAL_CONTRACT_ID == "dagr.constitutional-contract.v0.1"

    def test_historical_contract_projection_is_explicitly_deprecated(self):
        assert DAGR_CONSTITUTIONAL_CONTRACT_DEPRECATED is True
        assert DAGR_CONSTITUTIONAL_CONTRACT_STATUS == (
            "DEPRECATED / HISTORICAL L10 COMPATIBILITY (DAGR-MIGRATION-WAVE-0)"
        )

    def test_dagr_spec_is_named_as_grammar_owner_without_ratification_claim(self):
        assert DAGR_CONSTITUTIONAL_GRAMMAR_OWNER == "thelaplage/dagr-spec"
        assert DAGR_CONSTITUTIONAL_GRAMMAR_STATUS == (
            "PROPOSED / UNRATIFIED / NON-CANONICAL"
        )

    def test_emitter_role_is_retained(self):
        assert EMITTER_ROLE == "srs_receipt_emitter"

    def test_mcp_action_is_retained_but_explicitly_local_and_unbound(self):
        assert EMITTER_DOMAIN == "mcp_action"
        assert EMITTER_DOMAIN_SCOPE == "consumer_local_unbound"
        assert EMITTER_DOMAIN != "action"


# ---------------------------------------------------------------------------
# Historical/local DOMAIN_NEQ_ASSERTIONS retained exactly
# ---------------------------------------------------------------------------

_EXPECTED_DOMAIN_NEQ_ASSERTIONS = (
    "mcp_action:emitting_receipt != arcs:verifying_receipt",
    "mcp_action:receipt_present != action:permitted",
    "mcp_action:receipt_present != action:factually_true",
    "mcp_action:srs_receipt_emitter != arcs:verifier",
    "mcp_action:srs_receipt_emitter != dagr:constitutional_authority",
    "mcp_action:refused_receipt != action:permitted",
    "mcp_action:deferred_receipt != action:permitted",
    "mcp_action:signed_receipt != real_world:event_occurred",
    "mcp_action:srs_profile_compliant != action:factually_true",
    "mcp_action:verifier_reference != arcs:recomputed_finding",
    "mcp_action:admitted != evidence:SUPPORTED",
    "mcp_action:refused != evidence:CONTRADICTED",
)


class TestDomainNeqAssertions:
    def test_exact_historical_local_assertion_set_is_retained(self):
        assert DOMAIN_NEQ_ASSERTIONS == _EXPECTED_DOMAIN_NEQ_ASSERTIONS

    def test_all_entries_contain_neq_operator(self):
        for entry in DOMAIN_NEQ_ASSERTIONS:
            assert "!=" in entry, f"Entry missing !=: {entry!r}"

    def test_all_entries_use_local_mcp_action_prefix(self):
        for entry in DOMAIN_NEQ_ASSERTIONS:
            assert entry.startswith("mcp_action:"), (
                f"All retained L10 NEQ assertions must start with 'mcp_action:': {entry!r}"
            )

    def test_emitter_neq_verifier_is_exact(self):
        assert "mcp_action:srs_receipt_emitter != arcs:verifier" in DOMAIN_NEQ_ASSERTIONS

    def test_receipt_present_neq_permitted_is_exact(self):
        assert "mcp_action:receipt_present != action:permitted" in DOMAIN_NEQ_ASSERTIONS

    def test_emitting_neq_verifying_is_exact(self):
        assert "mcp_action:emitting_receipt != arcs:verifying_receipt" in DOMAIN_NEQ_ASSERTIONS

    def test_signed_receipt_neq_real_world_event_is_exact(self):
        assert "mcp_action:signed_receipt != real_world:event_occurred" in DOMAIN_NEQ_ASSERTIONS

    def test_emitter_neq_constitutional_authority_is_exact(self):
        assert (
            "mcp_action:srs_receipt_emitter != dagr:constitutional_authority"
            in DOMAIN_NEQ_ASSERTIONS
        )


# ---------------------------------------------------------------------------
# ReceiptContext carries the historical id only as emitter context
# ---------------------------------------------------------------------------

def _make_receipt_context(**kwargs):
    defaults = dict(
        runtime_instance_id="test-runtime-001",
        boundary_id="test-boundary",
        policy_pack_id="test-pack",
        policy_pack_version="v0.1",
        subject_ref="tool_call:test-tool",
        logical_call_id="call-001",
    )
    defaults.update(kwargs)
    return ReceiptContext(**defaults)


class TestReceiptContextDagrConstitutionId:
    def test_receipt_context_has_field(self):
        ctx = _make_receipt_context()
        assert hasattr(ctx, "dagr_constitution_id")

    def test_receipt_context_default_value_matches_historical_constant(self):
        ctx = _make_receipt_context()
        assert ctx.dagr_constitution_id == DAGR_CONSTITUTIONAL_CONTRACT_ID

    def test_receipt_context_field_retains_exact_historical_string(self):
        ctx = _make_receipt_context()
        assert ctx.dagr_constitution_id == "dagr.constitutional-contract.v0.1"

    def test_existing_optional_fields_unaffected(self):
        ctx = _make_receipt_context(
            subject_ref_origin="dagr_mcp_tool_hash",
            actor_ref="test-actor",
            tenant_id="tenant-1",
        )
        assert ctx.subject_ref_origin == "dagr_mcp_tool_hash"
        assert ctx.actor_ref == "test-actor"
        assert ctx.tenant_id == "tenant-1"
        assert ctx.dagr_constitution_id == DAGR_CONSTITUTIONAL_CONTRACT_ID

    def test_constitution_id_not_a_receipt_disposition_or_role(self):
        ctx = _make_receipt_context()
        assert ctx.dagr_constitution_id not in {
            "admitted",
            "refused",
            "deferred",
            EMITTER_ROLE,
        }


# ---------------------------------------------------------------------------
# Byte-level SRS wire freeze
# ---------------------------------------------------------------------------

class _CaptureSink:
    def __init__(self):
        self.envelopes = []

    def write(self, envelope):
        self.envelopes.append(envelope)
        return str(envelope["receipt_id"])


def _golden_context(*, dagr_constitution_id: str) -> ReceiptContext:
    return ReceiptContext(
        runtime_instance_id="runtime:constitution-recon-golden",
        boundary_id="boundary:constitution-recon-golden",
        policy_pack_id="policy:constitution-recon-golden",
        policy_pack_version="v0.1",
        subject_ref="tool_call:constitution-recon-golden",
        logical_call_id="call:constitution-recon-golden",
        dagr_constitution_id=dagr_constitution_id,
    )


def _materialize_signed_wire(*, dagr_constitution_id: str):
    identity = SigningIdentity(
        issuer_id="issuer:dagr-mcp:golden",
        key_id="key:dagr-mcp:golden",
        private_key=Ed25519PrivateKey.from_private_bytes(bytes([7]) * 32),
    )
    sink = _CaptureSink()
    emitter = SignedReceiptEmitter(
        identity=identity,
        sink=sink,
        receipt_id_factory=lambda kind: (
            f"urn:srs:receipt:{kind}:constitution-recon-golden"
        ),
        issued_at_factory=lambda: "2026-08-29T00:00:00Z",
    )
    context = _golden_context(dagr_constitution_id=dagr_constitution_id)

    admission_ref = emitter.emit_admission(
        context=context,
        requested_tool_name="constitution.recon.golden",
        argument_digest="sha256:" + "a" * 64,
        disposition="admitted",
    )
    emitter.emit_outcome(
        context=context,
        admission_receipt_ref=admission_ref,
        outcome="result_returned",
        result_digest="sha256:" + "b" * 64,
    )

    assert len(sink.envelopes) == 2
    return tuple(rfc8785.dumps(envelope) for envelope in sink.envelopes)


class TestSignedSrsWireFreeze:
    def test_declaration_reconciliation_is_byte_identical_to_pinned_baseline(self):
        admission_bytes, outcome_bytes = _materialize_signed_wire(
            dagr_constitution_id=DAGR_CONSTITUTIONAL_CONTRACT_ID
        )

        # These SHA-256 commitments were captured from the exact pre-change main
        # pinned above. A declaration-only reconciliation must not move either.
        assert hashlib.sha256(admission_bytes).hexdigest() == (
            _BASELINE_ADMISSION_CANONICAL_SHA256
        )
        assert hashlib.sha256(outcome_bytes).hexdigest() == (
            _BASELINE_OUTCOME_CANONICAL_SHA256
        )

    def test_dagr_constitution_id_is_provably_out_of_band_for_signed_wire(self):
        historical = _materialize_signed_wire(
            dagr_constitution_id="dagr.constitutional-contract.v0.1"
        )
        hostile_future_label = _materialize_signed_wire(
            dagr_constitution_id="consumer-local-sentinel-that-must-not-hit-wire"
        )

        # Exact canonical bytes, not merely selected fields, are identical for
        # admission and outcome. Therefore dagr_constitution_id remains
        # emitter-context-only and cannot change signing bytes or their digests.
        assert historical == hostile_future_label
        assert [hashlib.sha256(value).hexdigest() for value in historical] == [
            _BASELINE_ADMISSION_CANONICAL_SHA256,
            _BASELINE_OUTCOME_CANONICAL_SHA256,
        ]
