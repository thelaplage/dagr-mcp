"""Sprint A5 — the ``official-mcp-sdk.python.v0.1`` binding mask.

Proves the second binding's mask is a total, duplicate-free, fail-closed
classification of the neutral contract, grounded in the actually-installed
official SDK and the shared receipt emitter, with a distinct binding-version
stamp that never collides with the frozen A1 registry or the FastMCP binding, and
that it is a *separate* mask from the FastMCP A2 mask (the two are never merged).
"""

from __future__ import annotations

import pytest

pytest.importorskip("mcp")
pytest.importorskip("rfc8785")

from mcp import types as mcp_types

from dagr_mcp import srs_receipts
from dagr_mcp_lifecycle import binding_mask as fastmcp_mask
from dagr_mcp_lifecycle import contract
from dagr_mcp_sdk_binding import mask


# --------------------------------------------------------------------------- #
# Totality and drift                                                          #
# --------------------------------------------------------------------------- #


def test_mask_matches_binding_oracle():
    mask.verify_mask_matches_binding()


def test_mapping_is_total_and_duplicate_free():
    mask.verify_mapping_total()

    # Every neutral token is classified exactly once.
    assert {e.neutral_token for e in mask.DISPOSITION_MASK} == set(
        contract.NEUTRAL_DISPOSITIONS
    )
    assert {e.neutral_token for e in mask.OUTCOME_MASK} == set(
        contract.NEUTRAL_OUTCOMES
    )
    assert {e.neutral_token for e in mask.CANCELLATION_FACT_MASK} == set(
        contract.NEUTRAL_CANCELLATION_FACTS
    )
    assert {e.neutral_token for e in mask.INPUT_REQUIRED_MASK} == set(
        contract.INPUT_REQUIRED_MODES
    )


def test_unknown_token_on_either_side_fails_totality():
    # A neutral outcome the mask does not classify fails the partition.
    with pytest.raises(AssertionError):
        mask.verify_mapping_total(neutral_outcomes=contract.NEUTRAL_OUTCOMES + ("phantom",))
    # A live emitter outcome token the mask does not cover fails coverage.
    with pytest.raises(AssertionError):
        mask.verify_mapping_total(
            live_outcome_tokens=set(mask.BINDING_OUTCOME_TOKENS) | {"invented_token"}
        )


def test_no_silent_fallback_for_unknown_tokens():
    with pytest.raises(KeyError):
        mask.project_disposition("not_a_disposition")
    with pytest.raises(KeyError):
        mask.project_outcome("not_an_outcome")
    with pytest.raises(KeyError):
        mask.project_cancellation_fact("not_a_fact")


# --------------------------------------------------------------------------- #
# Outcome / disposition projections onto the shared profile tokens            #
# --------------------------------------------------------------------------- #


def test_neutral_outcomes_project_to_shared_profile_tokens():
    assert mask.project_outcome("result").binding_token == "result_returned"
    assert mask.project_outcome("error").binding_token == "error_returned"
    assert mask.project_outcome("exception").binding_token == "exception"
    assert mask.project_outcome("cancellation").binding_token == "indeterminate"

    # timeout is subsumed onto the exception family (not a dedicated token).
    timeout = mask.project_outcome("timeout")
    assert timeout.status == "subsumed"
    assert timeout.binding_token == "exception"


def test_task_submitted_is_unsupported_capability_difference():
    """task_submitted is a profile token this binding does not observe.

    The mcp.types.CreateTaskResult type exists and the profile can stamp
    task_submitted (the FastMCP binding does), but the bound tools/call client
    seam cannot carry a CreateTaskResult, so this binding fails closed. It is a
    genuine capability difference, not a normalization.
    """

    entry = mask.project_outcome("task_submitted")
    assert entry.status == "unsupported"
    assert entry.binding_token is None
    # It is a real profile token (⊆ what the emitter can stamp) that this binding
    # explicitly does not observe.
    assert "task_submitted" in mask.BINDING_OUTCOME_TOKENS
    assert mask.BINDING_UNSUPPORTED_OUTCOME_TOKENS == frozenset({"task_submitted"})
    assert mask.BINDING_UNSUPPORTED_OUTCOME_TOKENS <= mask.BINDING_OUTCOME_TOKENS
    # Byte-grounding: the type exists, but CallToolResult.content is required and a
    # CreateTaskResult has no content, so the tools/call client seam cannot parse it.
    assert hasattr(mcp_types, "CreateTaskResult")
    assert mcp_types.CallToolResult.model_fields["content"].is_required()
    assert "content" not in mcp_types.CreateTaskResult.model_fields


def test_dispositions_project_to_the_shared_tokens():
    assert mask.project_disposition("admitted") == "admitted"
    assert mask.project_disposition("refused") == "refused"
    assert mask.project_disposition("deferred") == "deferred_for_review"


def test_input_required_is_unsupported_in_both_modes():
    assert mask.project_outcome("input_required").status == "unsupported"
    assert mask.project_outcome("input_required").binding_token is None
    assert all(e.status == "unsupported" for e in mask.INPUT_REQUIRED_MASK)
    assert all(e.binding_token is None for e in mask.INPUT_REQUIRED_MASK)


# --------------------------------------------------------------------------- #
# Binding identity: distinct, registered, never colliding                     #
# --------------------------------------------------------------------------- #


def test_binding_stamp_is_distinct_and_registered():
    assert mask.MASK_BINDING_TARGET == "official-mcp-sdk.python.v0.1"
    assert mask.BINDING_VERSION == "official-mcp-sdk.python.v0.1"
    assert mask.BINDING_VERSION != "fastmcp.middleware.v0.1"

    # Registered as an additive binding identity the emitter accepts — but NOT in
    # the frozen A1 registry literal (that stays byte-identical).
    assert mask.BINDING_VERSION in srs_receipts.ALL_REGISTERED_BINDING_VERSIONS
    assert mask.BINDING_VERSION in srs_receipts.ADDITIONAL_BINDING_VERSIONS
    assert mask.BINDING_VERSION not in srs_receipts.REGISTERED_BINDING_VERSIONS
    assert srs_receipts.REGISTERED_BINDING_VERSIONS == frozenset(
        {"direct-harness.v0.1", "fastmcp.middleware.v0.1"}
    )


def test_receipt_profile_is_shared_but_binding_identity_differs():
    # The receipt profile/schema stamps are identical across bindings (shared
    # profile), so cross-binding semantic fields match…
    assert mask.PROTOCOL_STAMPS == fastmcp_mask.PROTOCOL_STAMPS
    assert mask.PROTOCOL_STAMPS["profile_id"] == srs_receipts.PROFILE_ID
    assert mask.PROTOCOL_STAMPS["profile_version"] == srs_receipts.PROFILE_VERSION
    assert mask.PROTOCOL_STAMPS["receipt_version"] == srs_receipts.RECEIPT_VERSION
    # …while the binding-version stamp is intentionally different.
    assert mask.BINDING_STAMPS != fastmcp_mask.BINDING_STAMPS
    assert mask.BINDING_STAMPS == {"binding_version": "official-mcp-sdk.python.v0.1"}


def test_attestation_limits_are_identity_equal_to_shared_constants():
    assert mask.ATTESTATION_LIMIT_MASK["base"] == srs_receipts.BASE_LIMIT
    assert mask.ATTESTATION_LIMIT_MASK["result"] == srs_receipts.RESULT_LIMIT
    assert mask.ATTESTATION_LIMIT_MASK["task"] == srs_receipts.TASK_LIMIT
    # The boundary limit is byte-identical to the FastMCP binding's default.
    from dagr_mcp import fastmcp_binding

    assert mask.ATTESTATION_LIMIT_MASK["boundary"] == fastmcp_binding.DEFAULT_BOUNDARY_LIMIT


# --------------------------------------------------------------------------- #
# Grounding in the installed official SDK                                     #
# --------------------------------------------------------------------------- #


def test_mask_is_grounded_in_installed_official_sdk():
    assert mask.SDK_IMPORT_ROOT == "mcp"
    assert mask.SDK_INVENTORY_VERSION == "1.28.1"
    from importlib.metadata import version

    assert version("mcp") == mask.SDK_INVENTORY_VERSION
    assert "isError" in mcp_types.CallToolResult.model_fields
    assert hasattr(mcp_types, "CreateTaskResult")
    # Elicitation IS available in the SDK yet the mask marks input_required
    # unsupported — the seam exists, the binding deliberately does not carry it.
    assert hasattr(mcp_types, "ElicitResult")
    assert mask.project_outcome("input_required").status == "unsupported"


# --------------------------------------------------------------------------- #
# Protocol-stamp discipline                                                   #
# --------------------------------------------------------------------------- #


def test_protocol_stamp_discipline():
    mask.assert_protocol_stamps_pinned()
    assert mask.classify_protocol_stamp("mcp") == "pinned"
    assert mask.classify_protocol_stamp(None) == "unsupported"
    for bad in mask.REJECTED_PROTOCOL_STAMP_FORMS:
        assert mask.classify_protocol_stamp(bad) == "unsupported"
    assert mask.NEGOTIATED_MCP_PROTOCOL_VERSION_STATUS == "unsupported"
    assert "protocol_version" not in mask.PROTOCOL_STAMPS


# --------------------------------------------------------------------------- #
# The two masks are separate, never merged                                    #
# --------------------------------------------------------------------------- #


def test_sdk_mask_is_separate_from_the_fastmcp_mask():
    assert mask.MASK_ID != fastmcp_mask.MASK_ID
    assert mask.MASK_BINDING_TARGET != fastmcp_mask.MASK_BINDING_TARGET
    assert mask is not fastmcp_mask
    assert mask.__name__ == "dagr_mcp_sdk_binding.mask"
    assert fastmcp_mask.__name__ == "dagr_mcp_lifecycle.binding_mask"
    # Both nonetheless share the same profile outcome-token set (the profile, not
    # the binding, owns them).
    assert mask.BINDING_OUTCOME_TOKENS == fastmcp_mask.BINDING_OUTCOME_TOKENS
    # …but they differ in which of those tokens each binding OBSERVES:
    # task_submitted is a genuine capability difference. FastMCP maps it directly;
    # the official-SDK binding marks it unsupported (its tools/call client seam
    # cannot carry a CreateTaskResult). This is recorded, not normalized.
    assert fastmcp_mask.project_outcome("task_submitted").status == "direct"
    assert fastmcp_mask.project_outcome("task_submitted").binding_token == "task_submitted"
    assert mask.project_outcome("task_submitted").status == "unsupported"
    assert mask.BINDING_UNSUPPORTED_OUTCOME_TOKENS == frozenset({"task_submitted"})


def test_receipt_cardinality_mirrors_the_neutral_contract():
    assert mask.RECEIPT_CARDINALITY == dict(contract.RECEIPT_CARDINALITY)
    assert mask.RECEIPT_CARDINALITY == {"admitted": 2, "refused": 1, "deferred": 1}
