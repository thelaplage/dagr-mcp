from __future__ import annotations

import hashlib
import json

import pytest

from dagr_mcp_core.external_profile_receipts import ExternalProfileReceiptContract


def _rebind_profile(kwargs: dict, profile: dict) -> dict:
    changed = dict(kwargs)
    profile_bytes = json.dumps(profile, sort_keys=True, separators=(",", ":")).encode("utf-8")
    changed["profile_contract_bytes"] = profile_bytes
    changed["profile_contract_digest"] = "sha256:" + hashlib.sha256(profile_bytes).hexdigest()
    return changed


def test_malformed_compatibility_entry_fails_before_emission(
    external_profile_contract_kwargs: dict,
) -> None:
    profile = json.loads(external_profile_contract_kwargs["profile_contract_bytes"])
    profile["compatible_envelopes"][0]["caller_selected_ref"] = "latest"
    kwargs = _rebind_profile(external_profile_contract_kwargs, profile)
    with pytest.raises(ValueError, match="malformed entry"):
        ExternalProfileReceiptContract(**kwargs)


def test_duplicate_classification_entry_fails_before_emission(
    external_profile_contract_kwargs: dict,
) -> None:
    profile = json.loads(external_profile_contract_kwargs["profile_contract_bytes"])
    profile["receipt_type_classifications"].append(
        dict(profile["receipt_type_classifications"][0])
    )
    kwargs = _rebind_profile(external_profile_contract_kwargs, profile)
    with pytest.raises(ValueError, match="unique entries"):
        ExternalProfileReceiptContract(**kwargs)


def test_unclassified_permitted_type_fails_before_emission(
    external_profile_contract_kwargs: dict,
) -> None:
    profile = json.loads(external_profile_contract_kwargs["profile_contract_bytes"])
    profile["permitted_receipt_types"].append("org.counterpedia.mcp.read.audit")
    kwargs = _rebind_profile(external_profile_contract_kwargs, profile)
    with pytest.raises(ValueError, match="unclassified permitted receipt types"):
        ExternalProfileReceiptContract(**kwargs)


def test_v0_2_1_compatibility_cannot_coexist_with_namespaced_types(
    external_profile_contract_kwargs: dict,
) -> None:
    profile = json.loads(external_profile_contract_kwargs["profile_contract_bytes"])
    profile["compatible_envelopes"].append(
        {"published_version": "0.2.1", "sha256": "0" * 64}
    )
    kwargs = _rebind_profile(external_profile_contract_kwargs, profile)
    with pytest.raises(ValueError, match="v0.2.1-compatible profile"):
        ExternalProfileReceiptContract(**kwargs)
