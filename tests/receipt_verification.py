"""Local in-repo receipt checks used by this repository's own test suite.

This module is a test helper. It is not ARCS Verify, is not a substitute for it,
and must not be reported as it: it runs no verifier package, selects no profile,
and produces no verifier verdict object. It checks a receipt against a supplied
JSON Schema and the Ed25519 signature over the RFC 8785 preimage, plus the
locally-declared subject-reference origin reading below.
"""

from __future__ import annotations

import base64
import copy
from typing import Any, Mapping

import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator

# Restated here rather than imported from the emitter, so this check reads the
# field against an independent copy of the closed vocabulary instead of against
# whatever the code under test happens to believe. ``NOT_DECLARED_READING`` is a
# reading of absence only and is deliberately absent from the emittable set.
DECLARED_SUBJECT_REF_ORIGINS = frozenset({
    "supplied_subject",
    "derived_from_session",
    "derived_from_request",
    "derived_from_supplied_correlation",
    "binding_minted",
})
NOT_DECLARED_READING = "not_declared"


def decode_base64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def subject_ref_origin_reading(receipt: Mapping[str, Any]) -> str:
    """Read the receipt's declared subject-reference origin.

    Genuine absence reads as ``not_declared``, which stays distinct from every
    declared class. A present value outside the closed vocabulary is a failure,
    never a fallback to absence.
    """

    if "subject_ref_origin" not in receipt:
        return NOT_DECLARED_READING
    origin = receipt["subject_ref_origin"]
    assert isinstance(origin, str), origin
    assert origin in DECLARED_SUBJECT_REF_ORIGINS, origin
    return origin


def verify_receipt(
    receipt: Mapping[str, Any],
    bundle: Mapping[str, Any],
    schema: Mapping[str, Any],
) -> None:
    assert not list(Draft202012Validator(schema).iter_errors(receipt))
    reading = subject_ref_origin_reading(receipt)
    assert reading in DECLARED_SUBJECT_REF_ORIGINS or reading == NOT_DECLARED_READING
    preimage = copy.deepcopy(dict(receipt))
    signature = decode_base64url(preimage["receipt_signature"].pop("signature"))
    key_id = preimage["receipt_signature"]["key_id"]
    entries = [entry for entry in bundle["issuers"] if entry["key_id"] == key_id]
    assert len(entries) == 1
    Ed25519PublicKey.from_public_bytes(
        decode_base64url(entries[0]["public_key"])
    ).verify(signature, rfc8785.dumps(preimage))
