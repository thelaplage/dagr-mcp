from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path

import pytest

from dagr_mcp.demo import run_fastmcp_demo_async
from dagr_mcp.srs_receipts import sha256_digest
from tests.receipt_verification import verify_receipt
from tools.generate_fastmcp_fixtures import (
    EXPECTED_FILES,
    FAST_MCP_VERSION,
    GOLDEN_DIR,
    generate_fixture_set,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (ROOT / "dagr_mcp/vendor/srs/srs-envelope-v0.2.0.schema.json").read_text(
        encoding="utf-8"
    )
)
CURRENT_FASTMCP_VERSION = importlib.metadata.version("fastmcp")
FLOOR_ONLY = pytest.mark.skipif(
    CURRENT_FASTMCP_VERSION != FAST_MCP_VERSION,
    reason="deterministic fixture generation is pinned to FastMCP 3.4.4",
)

VERDICT_KEYS = {
    "schema_digest",
    "envelope",
    "profile",
    "raw_content_exclusion",
    "signature_valid",
    "issuer_key_resolved",
    "issuer_key_trusted",
    "attestation_limits_present",
    "chain_status",
}


def _bytes(directory: Path) -> dict[str, bytes]:
    return {name: (directory / name).read_bytes() for name in EXPECTED_FILES}


@FLOOR_ONLY
def test_generator_is_byte_stable_and_matches_committed_golden(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_result = generate_fixture_set(first)
    second_result = generate_fixture_set(second)

    assert _bytes(first) == _bytes(second)
    assert _bytes(first) == _bytes(GOLDEN_DIR)
    assert first_result.projection == second_result.projection

    outcome = json.loads(
        (first / "outcome-result-returned.json").read_text(encoding="utf-8")
    )
    assert outcome["result_digest"] == sha256_digest(first_result.projection)
    assert outcome["result_digest"] == first_result.result_digest


def test_committed_receipts_verify_under_frozen_rule():
    bundle = json.loads(
        (GOLDEN_DIR / "issuer-keys.json").read_text(encoding="utf-8")
    )
    for name in ("admission-admitted.json", "outcome-result-returned.json"):
        receipt = json.loads((GOLDEN_DIR / name).read_text(encoding="utf-8"))
        verify_receipt(receipt, bundle, SCHEMA)


def test_expectations_contract_is_complete_and_exact():
    expectations = json.loads(
        (GOLDEN_DIR / "expectations.json").read_text(encoding="utf-8")
    )
    assert set(expectations) == {"profile", "keyring", "receipts"}
    assert expectations["profile"] == "srs.mcp.sdk_enforcement.v0.1"
    assert expectations["keyring"] == "issuer-keys.json"
    assert [entry["path"] for entry in expectations["receipts"]] == [
        "admission-admitted.json",
        "outcome-result-returned.json",
    ]
    for entry in expectations["receipts"]:
        assert set(entry) == {"path", "verdicts", "expected_failure_codes"}
        assert set(entry["verdicts"]) == VERDICT_KEYS
        assert entry["verdicts"]["chain_status"] == "not_applicable"
        assert all(
            value is True
            for key, value in entry["verdicts"].items()
            if key != "chain_status"
        )
        assert entry["expected_failure_codes"] == []



def test_fixture_identity_is_scoped_and_bundle_is_public_only():
    bundle_text = (GOLDEN_DIR / "issuer-keys.json").read_text(encoding="utf-8")
    bundle = json.loads(bundle_text)
    entry = bundle["issuers"][0]

    assert entry["issuer_id"] == "issuer:dagr:fastmcp-fixture"
    assert entry["key_id"] == "issuer.dagr.fastmcp-fixture/receipt-signing/v1"
    assert entry["trusted"] is True
    assert all(
        marker not in bundle_text.lower()
        for marker in ("private_key", "secret", "seed")
    )

def test_generator_is_pinned_to_lowest_supported_fastmcp_lane():
    assert FAST_MCP_VERSION == "3.4.4"


@FLOOR_ONLY
@pytest.mark.asyncio
async def test_default_demo_outcome_digest_matches_generated_fixture(
    tmp_path: Path,
):
    directory = await run_fastmcp_demo_async(tmp_path / "default-demo")
    receipts = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in directory.glob("urn_srs_receipt_*.json")
    ]
    outcomes = [
        receipt
        for receipt in receipts
        if receipt["receipt_kind"] == "outcome"
    ]
    assert len(outcomes) == 1

    committed = json.loads(
        (GOLDEN_DIR / "outcome-result-returned.json").read_text(
            encoding="utf-8"
        )
    )
    assert outcomes[0]["result_digest"] == committed["result_digest"]
