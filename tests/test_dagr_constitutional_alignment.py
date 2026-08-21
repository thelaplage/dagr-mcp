"""L10: DAGR constitutional alignment tests for dagr-mcp.

Verifies that dagr-mcp correctly declares its emitter role under the
DAGR Constitutional Contract v0.1, and propagates dagr_constitution_id
through ReceiptContext.
"""
from __future__ import annotations

import pytest

from dagr_mcp.dagr_constitutional_consumer import (
    DAGR_CONSTITUTIONAL_CONTRACT_ID,
    DAGR_CONSTITUTIONAL_CONTRACT_STATUS,
    EMITTER_ROLE,
    EMITTER_DOMAIN,
    DOMAIN_NEQ_ASSERTIONS,
)
from dagr_mcp.srs_receipts import ReceiptContext


# ---------------------------------------------------------------------------
# Constitutional constants
# ---------------------------------------------------------------------------

class TestConstitutionalConstants:
    def test_contract_id_exact_value(self):
        assert DAGR_CONSTITUTIONAL_CONTRACT_ID == "dagr.constitutional-contract.v0.1"

    def test_emitter_role(self):
        assert EMITTER_ROLE == "srs_receipt_emitter"

    def test_emitter_domain(self):
        assert EMITTER_DOMAIN == "mcp_action"

    def test_contract_status_mentions_wave0(self):
        assert "DAGR-MIGRATION-WAVE-0" in DAGR_CONSTITUTIONAL_CONTRACT_STATUS


# ---------------------------------------------------------------------------
# DOMAIN_NEQ_ASSERTIONS
# ---------------------------------------------------------------------------

class TestDomainNeqAssertions:
    def test_is_non_empty_tuple(self):
        assert isinstance(DOMAIN_NEQ_ASSERTIONS, tuple)
        assert len(DOMAIN_NEQ_ASSERTIONS) > 0

    def test_all_entries_contain_neq_operator(self):
        for entry in DOMAIN_NEQ_ASSERTIONS:
            assert "!=" in entry, f"Entry missing !=: {entry!r}"

    def test_all_entries_use_mcp_action_prefix(self):
        for entry in DOMAIN_NEQ_ASSERTIONS:
            assert entry.startswith("mcp_action:"), (
                f"All L10 NEQ assertions must start with 'mcp_action:': {entry!r}"
            )

    def test_contains_emitter_neq_verifier(self):
        assert any(
            "srs_receipt_emitter" in e and "arcs:verifier" in e
            for e in DOMAIN_NEQ_ASSERTIONS
        )

    def test_contains_receipt_present_neq_permitted(self):
        assert any(
            "receipt_present" in e and "permitted" in e
            for e in DOMAIN_NEQ_ASSERTIONS
        )

    def test_contains_emitting_neq_verifying(self):
        assert any(
            "emitting_receipt" in e and "verifying_receipt" in e
            for e in DOMAIN_NEQ_ASSERTIONS
        )

    def test_contains_signed_receipt_neq_real_world_event(self):
        assert any(
            "signed_receipt" in e and "event_occurred" in e
            for e in DOMAIN_NEQ_ASSERTIONS
        )

    def test_contains_emitter_neq_constitutional_authority(self):
        assert any(
            "srs_receipt_emitter" in e and "constitutional_authority" in e
            for e in DOMAIN_NEQ_ASSERTIONS
        )


# ---------------------------------------------------------------------------
# ReceiptContext carries dagr_constitution_id
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

    def test_receipt_context_default_value_matches_constant(self):
        ctx = _make_receipt_context()
        assert ctx.dagr_constitution_id == DAGR_CONSTITUTIONAL_CONTRACT_ID

    def test_receipt_context_field_is_exactly_canonical_string(self):
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

    def test_constitution_id_not_a_receipt_disposition(self):
        ctx = _make_receipt_context()
        assert ctx.dagr_constitution_id != "admitted"
        assert ctx.dagr_constitution_id != "refused"
        assert ctx.dagr_constitution_id != "deferred"
        assert ctx.dagr_constitution_id != EMITTER_ROLE
