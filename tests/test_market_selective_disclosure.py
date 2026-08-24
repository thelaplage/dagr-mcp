"""MARKET-SELECTIVE-DISCLOSURE0 (L07): audience-scoped market metadata disclosure.

Goal: audience-scoped market metadata with hard-blocked authority/trust/
standing/secret fields. disclosure != verdict; disclosing a field grants no
authority and does not admit. Metadata-only (no raw args/results/creds).
"""

import dataclasses

import pytest

from dagr_mcp.market_selective_disclosure import (
    AUTHORITY_EFFECT,
    DISCLOSURE_KIND,
    MARKET_FORBIDDEN_SEGMENTS,
    DisclosureRule,
    MarketSelectiveDisclosureError,
    SelectiveDisclosureEnvelope,
    disclose,
    is_market_forbidden_field,
)

VALID_DIGEST = "d" * 64


def test_forbidden_fields_never_disclosed():
    p = {"offer_id": "o1", "price": 20, "trusted": True, "private_key": "secret"}
    e = disclose(
        object_id="o1",
        object_digest=VALID_DIGEST,
        payload=p,
        rule=DisclosureRule("buyer", ("offer_id", "price", "trusted", "private_key")),
    )
    assert e.disclosed == {"offer_id": "o1", "price": 20}
    assert e.authority_effect == "none"


def test_disclosed_never_includes_hard_blocked_family_even_when_present_and_requested():
    """authority/trust/standing/secret (and their common variants) are always dropped."""
    p = {
        "offer_id": "o1",
        "authority": "root",
        "authorized": True,
        "authorization": "bearer xyz",
        "trust": "high",
        "trusted": True,
        "standing": "good",
        "secret": "s",
        "secrets": ["s1"],
        "admitted": True,
    }
    rule = DisclosureRule("buyer", tuple(p.keys()))
    e = disclose(object_id="o1", object_digest=VALID_DIGEST, payload=p, rule=rule)
    assert e.disclosed == {"offer_id": "o1"}
    for forbidden in (
        "authority",
        "authorized",
        "authorization",
        "trust",
        "trusted",
        "standing",
        "secret",
        "secrets",
        "admitted",
    ):
        assert forbidden not in e.disclosed
        assert forbidden in e.blocked_fields


def test_hard_block_is_segment_exact_not_substring():
    """outstanding_balance must survive: 'standing' is a substring but not a segment."""
    assert is_market_forbidden_field("outstanding_balance") is False
    assert is_market_forbidden_field("standing") is True
    assert is_market_forbidden_field("standing_tier") is True
    assert is_market_forbidden_field("authority_level") is True
    assert is_market_forbidden_field("is_trusted") is True
    assert is_market_forbidden_field("secret_key") is True
    assert is_market_forbidden_field("price") is False


def test_raw_content_family_blocked_even_though_not_market_specific():
    """Metadata-only: no raw args/results/creds, reusing srs_receipts.RAW_KEYS."""
    p = {
        "offer_id": "o1",
        "access_token": "tok",
        "arguments": {"x": 1},
        "result": "value",
        "api_key": "k",
    }
    rule = DisclosureRule("buyer", tuple(p.keys()))
    e = disclose(object_id="o1", object_digest=VALID_DIGEST, payload=p, rule=rule)
    assert e.disclosed == {"offer_id": "o1"}
    for raw in ("access_token", "arguments", "result", "api_key"):
        assert raw not in e.disclosed
        assert raw in e.blocked_fields


def test_audience_scoping_produces_different_disclosures_from_same_payload():
    p = {"offer_id": "o1", "price": 20, "provider_id": "p1", "secret": "s"}
    buyer_rule = DisclosureRule("buyer", ("offer_id", "price"))
    provider_rule = DisclosureRule("provider", ("offer_id", "provider_id", "secret"))

    buyer_envelope = disclose(
        object_id="o1", object_digest=VALID_DIGEST, payload=p, rule=buyer_rule
    )
    provider_envelope = disclose(
        object_id="o1", object_digest=VALID_DIGEST, payload=p, rule=provider_rule
    )

    assert buyer_envelope.disclosed == {"offer_id": "o1", "price": 20}
    assert buyer_envelope.audience == "buyer"
    assert provider_envelope.disclosed == {"offer_id": "o1", "provider_id": "p1"}
    assert provider_envelope.audience == "provider"
    assert "secret" not in provider_envelope.disclosed


def test_only_requested_and_present_fields_are_disclosed():
    p = {"offer_id": "o1", "price": 20, "internal_note": "not requested"}
    rule = DisclosureRule("buyer", ("offer_id", "not_a_real_field"))
    e = disclose(object_id="o1", object_digest=VALID_DIGEST, payload=p, rule=rule)
    assert e.disclosed == {"offer_id": "o1"}
    assert "internal_note" not in e.disclosed
    assert "not_a_real_field" not in e.disclosed
    # Unrequested-but-present payload fields show up as redacted, not blocked.
    assert "internal_note" in e.redacted_fields
    assert "not_a_real_field" not in e.blocked_fields


def test_disclosure_never_admits_and_is_not_a_verdict():
    p = {"offer_id": "o1"}
    rule = DisclosureRule("buyer", ("offer_id",))
    e = disclose(object_id="o1", object_digest=VALID_DIGEST, payload=p, rule=rule)

    assert e.authority_effect == AUTHORITY_EFFECT == "none"
    assert e.disclosure_kind == DISCLOSURE_KIND
    field_names = {f.name for f in dataclasses.fields(SelectiveDisclosureEnvelope)}
    # Never structurally confusable with an SRS receipt.
    assert "disposition" not in field_names
    assert "receipt_kind" not in field_names
    assert "receipt_version" not in field_names


@pytest.mark.parametrize("bad_digest", ["", "not-hex", "sha256:tooshort", "SHA256:" + "a" * 64])
def test_invalid_object_digest_is_refused(bad_digest):
    p = {"offer_id": "o1"}
    rule = DisclosureRule("buyer", ("offer_id",))
    with pytest.raises(MarketSelectiveDisclosureError):
        disclose(object_id="o1", object_digest=bad_digest, payload=p, rule=rule)


def test_object_digest_accepts_sha256_prefixed_form():
    p = {"offer_id": "o1"}
    rule = DisclosureRule("buyer", ("offer_id",))
    e = disclose(
        object_id="o1",
        object_digest="sha256:" + "a" * 64,
        payload=p,
        rule=rule,
    )
    assert e.object_digest == "sha256:" + "a" * 64


def test_empty_object_id_is_refused():
    p = {"offer_id": "o1"}
    rule = DisclosureRule("buyer", ("offer_id",))
    with pytest.raises(MarketSelectiveDisclosureError):
        disclose(object_id="", object_digest=VALID_DIGEST, payload=p, rule=rule)


def test_empty_audience_is_refused():
    p = {"offer_id": "o1"}
    rule = DisclosureRule("", ("offer_id",))
    with pytest.raises(MarketSelectiveDisclosureError):
        disclose(object_id="o1", object_digest=VALID_DIGEST, payload=p, rule=rule)


def test_non_mapping_payload_is_refused():
    rule = DisclosureRule("buyer", ("offer_id",))
    with pytest.raises(MarketSelectiveDisclosureError):
        disclose(object_id="o1", object_digest=VALID_DIGEST, payload=["not", "a", "dict"], rule=rule)


def test_envelope_and_rule_are_immutable():
    rule = DisclosureRule("buyer", ("offer_id",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        rule.audience = "other"

    e = disclose(
        object_id="o1", object_digest=VALID_DIGEST, payload={"offer_id": "o1"}, rule=rule
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.authority_effect = "full"


def test_market_forbidden_segments_covers_all_four_named_families():
    """Goal states exactly: authority, trust, standing, secret."""
    for family in ("authority", "trust", "standing", "secret"):
        assert family in MARKET_FORBIDDEN_SEGMENTS
