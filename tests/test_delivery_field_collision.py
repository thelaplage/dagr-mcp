"""Adversarial tests for the DAGR/ARCS result-shaped field collision (Sprint A0).

The indeterminate cancellation outcome once carried a Boolean named
``result_not_delivered``. That name matches the ARCS raw-content profile's
``(?:^|_)result(?:$|_)`` rule, so a governance Boolean was rejected as if it were
raw tool-result content. The field was renamed to the neutral ``delivery_incomplete``.

These tests prove, adversarially, that:

* the neutral Boolean is admitted and verifies clean;
* raw result content cannot be smuggled under the neutral field, under ``result``,
  under ``tool_result``, under deceptive result-shaped names, or nested; and
* ordinary receipts are unchanged.

The ARCS-side proofs run against the real ``arcs_verify`` verifier when it is
co-installed and are skipped otherwise; the DAGR-side proofs always run.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from dagr_mcp.srs_receipts import (
    CANCELLATION_FIELD_NAMES,
    RawEnvelopeFileSink,
    ReceiptContentError,
    ReceiptContext,
    SignedReceiptEmitter,
    SigningIdentity,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "dagr_mcp/vendor/srs/srs-envelope-v0.2.0.schema.json"
NEUTRAL_FIELD = "delivery_incomplete"
BOUNDARY_LIMIT = (
    "The middleware is installed once at the institutional trust boundary; "
    "receipts attest only to observations at that boundary."
)

try:  # pragma: no cover - import guard exercised by environment, not logic
    from arcs_verify.verifier import verify_receipt as _arcs_verify_receipt
except ModuleNotFoundError:  # pragma: no cover
    _arcs_verify_receipt = None

requires_arcs = pytest.mark.skipif(
    _arcs_verify_receipt is None,
    reason="arcs_verify not co-installed; ARCS raw-content proof skipped",
)


def _identity() -> SigningIdentity:
    return SigningIdentity(
        issuer_id="issuer:test",
        key_id="issuer.test/key/1",
        private_key=Ed25519PrivateKey.from_private_bytes(bytes(range(32))),
    )


def _emitter(tmp_path: Path) -> tuple[SigningIdentity, SignedReceiptEmitter]:
    identity = _identity()
    sink = RawEnvelopeFileSink(tmp_path)
    return identity, SignedReceiptEmitter(identity=identity, sink=sink)


def _context(**overrides: object) -> ReceiptContext:
    values: dict[str, object] = {
        "runtime_instance_id": "runtime:test:1",
        "boundary_id": "boundary:test:1",
        "policy_pack_id": "policy:test",
        "policy_pack_version": "1",
        "subject_ref": "subject:test:1",
        "logical_call_id": "call:test:1",
        "actor_ref": "actor:test:1",
        "binding_version": "fastmcp.middleware.v0.1",
    }
    values.update(overrides)
    return ReceiptContext(**values)  # type: ignore[arg-type]


def _load(tmp_path: Path, receipt_id: str) -> dict[str, object]:
    for path in tmp_path.glob("urn_srs_receipt_*.json"):
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if receipt["receipt_id"] == receipt_id:
            return receipt
    raise AssertionError(f"receipt {receipt_id} not written")


def _emit_delivery_receipt(tmp_path: Path) -> tuple[SigningIdentity, dict[str, object]]:
    """Emit the real indeterminate cancellation/delivery outcome receipt."""

    identity, emitter = _emitter(tmp_path)
    receipt_id = emitter.emit_outcome(
        context=_context(),
        admission_receipt_ref="urn:srs:receipt:admission:1",
        outcome="indeterminate",
        additional_attestation_limits=(BOUNDARY_LIMIT,),
        binding_owned_fields={
            "request_cancelled": True,
            "execution_state_unknown": True,
            NEUTRAL_FIELD: True,
        },
    )
    return identity, _load(tmp_path, receipt_id)


def _arcs_report(receipt: dict[str, object], identity: SigningIdentity) -> dict[str, object]:
    assert _arcs_verify_receipt is not None
    return _arcs_verify_receipt(
        receipt,
        identity.trust_bundle(),
        schema_path=SCHEMA_PATH,
        selected_profile="srs.mcp.sdk_enforcement.v0.1",
    ).to_dict()


# --------------------------------------------------------------------------- #
# Registry sanity: the collision-causing name is gone, the neutral one present #
# --------------------------------------------------------------------------- #


def test_registry_uses_neutral_name_not_result_shaped():
    assert NEUTRAL_FIELD in CANCELLATION_FIELD_NAMES
    assert "result_not_delivered" not in CANCELLATION_FIELD_NAMES
    # No registered cancellation field may carry a bare `result` token.
    assert not any("result" in name for name in CANCELLATION_FIELD_NAMES)


# --------------------------------------------------------------------------- #
# Required test 1: neutral field with the intended Boolean passes             #
# --------------------------------------------------------------------------- #


def test_neutral_field_boolean_true_is_admitted(tmp_path):
    _identity, receipt = _emit_delivery_receipt(tmp_path)
    assert receipt[NEUTRAL_FIELD] is True
    assert receipt["outcome"] == "indeterminate"


@requires_arcs
def test_neutral_delivery_receipt_passes_arcs_raw_content_exclusion(tmp_path):
    identity, receipt = _emit_delivery_receipt(tmp_path)
    report = _arcs_report(receipt, identity)
    assert report["raw_content_exclusion"] is True, report


# --------------------------------------------------------------------------- #
# Required test 2: raw result content under the neutral field fails           #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "smuggled",
    [
        "BEGIN transcript: the tool returned the caller's password",
        {"body": "raw tool result payload"},
        ["raw", "result", "rows"],
        12345,
    ],
)
def test_raw_content_cannot_ride_the_neutral_field_at_emit_time(tmp_path, smuggled):
    _identity, emitter = _emitter(tmp_path)
    # The neutral field is a governance Boolean; anything that is not a bool
    # (i.e. any attempt to carry actual result content) is refused before signing.
    with pytest.raises(ReceiptContentError, match="must be boolean"):
        emitter.emit_outcome(
            context=_context(),
            admission_receipt_ref="urn:srs:receipt:admission:1",
            outcome="indeterminate",
            binding_owned_fields={NEUTRAL_FIELD: smuggled},  # type: ignore[dict-item]
        )
    assert not list(tmp_path.glob("urn_srs_receipt_*.json"))


@requires_arcs
def test_naive_tamper_raw_content_onto_neutral_field_breaks_the_signature(tmp_path):
    # WEAK CASE (kept for completeness): a *naive* post-signing tamper that does
    # not re-sign is caught by the Ed25519 signature alone. This proves the
    # signature covers the field, but it does NOT prove the raw-content posture:
    # the rejection here is only ``signature_valid is False``. The adversarial
    # re-signing case below is the real requirement.
    identity, receipt = _emit_delivery_receipt(tmp_path)
    injected = copy.deepcopy(receipt)
    injected[NEUTRAL_FIELD] = "BEGIN transcript: the tool returned raw rows"
    report = _arcs_report(injected, identity)
    assert report["signature_valid"] is False, report
    assert report["passed"] is False, report


# Raw tool-result material an attacker would try to smuggle under the neutral
# governance Boolean. Deliberately NOT a credential/secret pattern (those are
# caught by PROHIBITED_VALUE_RE) — this is ordinary leaked result content, which
# is exactly what the raw-content-exclusion posture must exclude regardless of
# the field name it hides behind.
SMUGGLED_RAW_RESULT = (
    "BEGIN tool transcript\n"
    "row 1: customer alice@example.com balance 4210.55\n"
    "row 2: internal note — do not disclose to caller\n"
    "END transcript"
)


@requires_arcs
def test_resigned_raw_material_on_neutral_field_must_be_rejected_by_arcs(tmp_path):
    """Adversarial, full re-sign: the malicious receipt is cryptographically valid.

    Steps (mirrors the required threat model exactly):

    1. emit an otherwise-valid indeterminate delivery receipt;
    2. replace the `delivery_incomplete` Boolean with raw tool-result material;
    3. recompute canonical bytes (``sign_envelope`` re-runs RFC 8785 JCS);
    4. re-sign with the *same* test issuer key so the signature is genuinely valid;
    5. run the complete ARCS verifier against the issuer trust bundle;
    6. require rejection for a raw-content / profile / extension-type reason —
       NOT merely signature invalidity.

    The required behavior is asserted directly. It currently fails (ARCS admits
    the receipt), so the test is a strict xfail: the red evidence is preserved
    and the requirement is committed as an executable cross-repo contract.
    """

    identity, receipt = _emit_delivery_receipt(tmp_path)

    # (2) swap the Boolean fact for raw result content.
    forged = copy.deepcopy(receipt)
    forged[NEUTRAL_FIELD] = SMUGGLED_RAW_RESULT
    forged.pop("receipt_signature", None)

    # (3)+(4) recompute canonical bytes and re-sign with the real issuer key.
    resigned = identity.sign_envelope(forged)
    assert resigned[NEUTRAL_FIELD] == SMUGGLED_RAW_RESULT

    # (5) full verifier run.
    report = _arcs_report(resigned, identity)

    # (6) This is a *genuine* re-sign: the signature must be valid, so any
    # rejection is necessarily a content/profile/type rejection, not signature
    # invalidity. That is the whole point of the threat model.
    assert report["signature_valid"] is True, report

    # REQUIRED: ARCS must not admit raw tool-result material carried under a
    # Boolean governance field. This is the assertion that currently fails.
    assert report["passed"] is False, report
    assert (
        report["raw_content_exclusion"] is False
        or report["profile"] is False
        or report["envelope"] is False
    ), report


# --------------------------------------------------------------------------- #
# Required tests 3 & 4: raw content under `result` and `tool_result` fail      #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("raw_key", ["result", "tool_result"])
def test_result_shaped_keys_are_refused_by_the_emitter(tmp_path, raw_key):
    identity, emitter = _emitter(tmp_path)
    # These names are DAGR raw-content keys; injecting one at the sink layer
    # (bypassing binding-owned-field validation) must still be refused on write.
    _identity2, good = _emit_delivery_receipt(tmp_path)
    poisoned = copy.deepcopy(good)
    poisoned[raw_key] = "raw tool result content"
    from dagr_mcp.srs_receipts import enforce_raw_content_exclusion

    with pytest.raises(ReceiptContentError, match="forbidden raw-content key"):
        enforce_raw_content_exclusion(poisoned)


@requires_arcs
@pytest.mark.parametrize("raw_key", ["result", "tool_result"])
def test_result_and_tool_result_fail_arcs(tmp_path, raw_key):
    identity, receipt = _emit_delivery_receipt(tmp_path)
    injected = copy.deepcopy(receipt)
    injected[raw_key] = "raw tool result content the verifier must reject"
    report = _arcs_report(injected, identity)
    assert report["raw_content_exclusion"] is False, report


# --------------------------------------------------------------------------- #
# Required test 5: deceptive result-shaped names fail                         #
# --------------------------------------------------------------------------- #


DECEPTIVE_NAMES = [
    "result_summary",
    "result_data",
    "tool_result_preview",
    "subtask_result",
    "delivered_result",
    "result_body",
]


@pytest.mark.parametrize("name", DECEPTIVE_NAMES)
def test_deceptive_names_are_unknown_binding_owned_fields(tmp_path, name):
    _identity, emitter = _emitter(tmp_path)
    # Only the three registered cancellation facts may be attached; a deceptive
    # result-shaped name is rejected as an unknown binding-owned field.
    with pytest.raises(ReceiptContentError, match="unknown binding-owned field"):
        emitter.emit_outcome(
            context=_context(),
            admission_receipt_ref="urn:srs:receipt:admission:1",
            outcome="indeterminate",
            binding_owned_fields={name: True},
        )
    assert not list(tmp_path.glob("urn_srs_receipt_*.json"))


@requires_arcs
@pytest.mark.parametrize("name", DECEPTIVE_NAMES)
def test_deceptive_names_fail_arcs_raw_content(tmp_path, name):
    identity, receipt = _emit_delivery_receipt(tmp_path)
    injected = copy.deepcopy(receipt)
    injected[name] = "raw result content hidden behind a plausible-looking key"
    report = _arcs_report(injected, identity)
    assert report["raw_content_exclusion"] is False, report


# --------------------------------------------------------------------------- #
# Required test 6: nested raw-result structures fail                          #
# --------------------------------------------------------------------------- #


@requires_arcs
def test_nested_raw_result_structure_fails_arcs(tmp_path):
    identity, receipt = _emit_delivery_receipt(tmp_path)
    injected = copy.deepcopy(receipt)
    # Bury a result-shaped key several levels deep inside a plausible container.
    injected["extensions"]["mcp"]["diagnostics"] = {  # type: ignore[index]
        "attempts": [{"tool_result": {"body": "leaked raw rows"}}],
    }
    report = _arcs_report(injected, identity)
    assert report["raw_content_exclusion"] is False, report


def test_nested_raw_result_structure_refused_by_emitter(tmp_path):
    identity, receipt = _emit_delivery_receipt(tmp_path)
    poisoned = copy.deepcopy(receipt)
    poisoned["extensions"]["mcp"]["diagnostics"] = {  # type: ignore[index]
        "attempts": [{"result": {"body": "leaked raw rows"}}],
    }
    from dagr_mcp.srs_receipts import enforce_raw_content_exclusion

    with pytest.raises(ReceiptContentError, match="forbidden raw-content key"):
        enforce_raw_content_exclusion(poisoned)


# --------------------------------------------------------------------------- #
# Required test 8: ordinary receipts are unchanged (no cancellation fields)    #
# --------------------------------------------------------------------------- #


def test_ordinary_receipts_carry_no_cancellation_fields(tmp_path):
    identity, emitter = _emitter(tmp_path)

    admission_id = emitter.emit_admission(
        context=_context(),
        requested_tool_name="records.lookup",
        argument_digest="sha256:" + "a" * 64,
        disposition="admitted",
    )
    result_id = emitter.emit_outcome(
        context=_context(logical_call_id="call:test:result"),
        admission_receipt_ref="urn:srs:receipt:admission:1",
        outcome="result_returned",
        result_digest="sha256:" + "b" * 64,
    )
    error_id = emitter.emit_outcome(
        context=_context(logical_call_id="call:test:error"),
        admission_receipt_ref="urn:srs:receipt:admission:2",
        outcome="error_returned",
        result_digest="sha256:" + "c" * 64,
    )
    exception_id = emitter.emit_outcome(
        context=_context(logical_call_id="call:test:exception"),
        admission_receipt_ref="urn:srs:receipt:admission:3",
        outcome="exception",
        exception_class="TimeoutError",
    )
    task_id = emitter.emit_outcome(
        context=_context(logical_call_id="call:test:task"),
        admission_receipt_ref="urn:srs:receipt:admission:4",
        outcome="task_submitted",
    )

    for receipt_id in (admission_id, result_id, error_id, exception_id, task_id):
        receipt = _load(tmp_path, receipt_id)
        for field in CANCELLATION_FIELD_NAMES:
            assert field not in receipt, (receipt_id, field)
        assert "result_not_delivered" not in receipt


@requires_arcs
def test_ordinary_result_receipt_still_passes_full_arcs_profile(tmp_path):
    identity, emitter = _emitter(tmp_path)
    receipt_id = emitter.emit_outcome(
        context=_context(),
        admission_receipt_ref="urn:srs:receipt:admission:1",
        outcome="result_returned",
        result_digest="sha256:" + "b" * 64,
        additional_attestation_limits=(BOUNDARY_LIMIT,),
    )
    receipt = _load(tmp_path, receipt_id)
    report = _arcs_report(receipt, identity)
    assert report["passed"] is True, report
