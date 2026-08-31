from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from dagr_mcp_core.external_profile_receipts import ExternalProfileReceiptContract

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "arcs_srs_483c73e0"
_ENVELOPE_PATH = _FIXTURE_ROOT / "envelope-v0-next.schema.json"


@pytest.fixture
def arcs_vnext_envelope_bytes() -> bytes:
    return _ENVELOPE_PATH.read_bytes()


@pytest.fixture
def external_profile_declaration(arcs_vnext_envelope_bytes: bytes) -> dict:
    return {
        "schema": "srs.external-profile-declaration/v0.1",
        "profile_id": "org.counterpedia.srs.mcp_read.v1",
        "profile_version": "v1",
        "publisher_ref": "org.counterpedia",
        "compatible_envelopes": [
            {
                "published_version": "v0-next",
                "sha256": hashlib.sha256(arcs_vnext_envelope_bytes).hexdigest(),
            }
        ],
        "permitted_receipt_types": [
            "org.counterpedia.mcp.read.admission",
            "org.counterpedia.mcp.read.outcome",
        ],
        "receipt_type_classifications": [
            {
                "receipt_type": "org.counterpedia.mcp.read.admission",
                "receipt_class": "governance_decision",
                "receipt_kind": "admission",
            },
            {
                "receipt_type": "org.counterpedia.mcp.read.outcome",
                "receipt_class": "outcome",
                "receipt_kind": "outcome",
            },
        ],
        "extension_namespace": "org.counterpedia",
        "raw_content_posture": "hash_only",
        "signing_required": True,
        "attestation_limits_required": True,
        "unknown_profile_behavior": "preserve_identity_and_do_not_infer",
        "conformance_vectors_ref": (
            "thelaplage/arcs-srs@483c73e02ca87b286597eb234c759d93aeed687d"
        ),
    }


@pytest.fixture
def external_profile_contract_kwargs(
    arcs_vnext_envelope_bytes: bytes,
    external_profile_declaration: dict,
) -> dict:
    profile_bytes = json.dumps(
        external_profile_declaration,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "profile_id": "org.counterpedia.srs.mcp_read.v1",
        "profile_version": "v1",
        "emitter_id": "dagr-mcp:counterpedia-read",
        "extension_namespace": "org.counterpedia",
        "admission_receipt_type": "org.counterpedia.mcp.read.admission",
        "outcome_receipt_type": "org.counterpedia.mcp.read.outcome",
        "envelope_contract_id": "srs-envelope-v0-next",
        "envelope_contract_version": "v0-next",
        "envelope_contract_digest": "sha256:"
        + hashlib.sha256(arcs_vnext_envelope_bytes).hexdigest(),
        "profile_contract_digest": "sha256:" + hashlib.sha256(profile_bytes).hexdigest(),
        "envelope_contract_bytes": arcs_vnext_envelope_bytes,
        "profile_contract_bytes": profile_bytes,
    }


@pytest.fixture
def external_profile_contract(external_profile_contract_kwargs: dict) -> ExternalProfileReceiptContract:
    return ExternalProfileReceiptContract(**external_profile_contract_kwargs)
