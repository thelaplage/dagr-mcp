from __future__ import annotations

import base64
import copy
from typing import Any, Mapping

import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator


def decode_base64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_receipt(
    receipt: Mapping[str, Any],
    bundle: Mapping[str, Any],
    schema: Mapping[str, Any],
) -> None:
    assert not list(Draft202012Validator(schema).iter_errors(receipt))
    preimage = copy.deepcopy(dict(receipt))
    signature = decode_base64url(preimage["receipt_signature"].pop("signature"))
    key_id = preimage["receipt_signature"]["key_id"]
    entries = [entry for entry in bundle["issuers"] if entry["key_id"] == key_id]
    assert len(entries) == 1
    Ed25519PublicKey.from_public_bytes(
        decode_base64url(entries[0]["public_key"])
    ).verify(signature, rfc8785.dumps(preimage))
