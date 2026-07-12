from __future__ import annotations

import base64
import copy
import json
from pathlib import Path

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator

from dagr_mcp.demo import run_demo

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "dagr_mcp/vendor/srs/srs-envelope-v0.2.0.schema.json").read_text())


def decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def independent_verify(receipt: dict, public_key: bytes) -> bool:
    signature = decode(receipt["receipt_signature"]["signature"])
    preimage = copy.deepcopy(receipt)
    del preimage["receipt_signature"]["signature"]
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, rfc8785.dumps(preimage))
        return True
    except InvalidSignature:
        return False


def test_demo_receipts_verify_and_mutation_contract(tmp_path):
    output = run_demo(tmp_path / "output")
    bundle = json.loads((output / "issuer-keys.json").read_text())
    public_key = decode(bundle["issuers"][0]["public_key"])
    receipts = [json.loads(path.read_text()) for path in output.glob("urn_srs_receipt_*.json")]
    assert {receipt["receipt_kind"] for receipt in receipts} == {"admission", "outcome"}
    for receipt in receipts:
        assert not list(Draft202012Validator(SCHEMA).iter_errors(receipt))
        assert independent_verify(receipt, public_key)
    admission = next(receipt for receipt in receipts if receipt["receipt_kind"] == "admission")
    outcome = next(receipt for receipt in receipts if receipt["receipt_kind"] == "outcome")
    assert outcome["admission_receipt_ref"] == admission["receipt_id"]

    semantic_mutation = copy.deepcopy(outcome)
    semantic_mutation["outcome"] = "error_returned"
    assert not independent_verify(semantic_mutation, public_key)

    reordered = json.loads(json.dumps(outcome, sort_keys=False, indent=7))
    assert independent_verify(reordered, public_key)


def test_demo_writes_no_private_key_material(tmp_path):
    output = run_demo(tmp_path / "output")
    for path in output.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8").lower()
            assert "private_key" not in text
            assert "begin private key" not in text
            assert "seed" not in text
