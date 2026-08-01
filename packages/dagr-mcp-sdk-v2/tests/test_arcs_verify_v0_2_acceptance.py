"""ARCS Verify acceptance of SDK-v2 receipts under DAGR SRS report contract v0.2.

The v0.2 verification-report contract is internally release-closed: it is v0.1
plus exactly one field, ``subject_ref_origin_disclosed``. These tests prove, with
the real external verifier rather than this repository's own checks, that:

* valid receipts emitted by ``official-mcp-sdk.python.v0.2`` over the genuine
  ``mcp==2.0.0`` stateless HTTP stack are accepted -- all eight Boolean verdicts
  true, no failure codes, and a report that validates against the v0.2 contract;
* the report discloses the *correct* origin value for the branch that actually
  ran, not merely some member of the vocabulary;
* a validly-signed **semantic mutation** fails verification;
* the origin disclosure is itself signature-covered, so it cannot be edited
  after signing;
* a present-but-out-of-vocabulary origin is invalid input to the verifier and is
  never laundered into the ``not_declared`` reading.

``arcs_verify`` is co-installed only in the multi-binding lane, so this module
skips when it is absent -- the same convention ``tests/test_behavioral_freeze.py``
uses. It is never silently replaced by the in-repo fallback checker: if the real
verifier is not present, these proofs do not run and do not claim to.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
from pathlib import Path

import pytest

from harness import build_governed_test_app, call_tool, ok_result

try:  # arcs_verify is co-installed only in the multi-binding lane.
    import arcs_verify
    from arcs_verify import dagr_report_v0_2 as dagr_report
    from arcs_verify.verifier import MCP_PROFILE, verify_receipt
except ModuleNotFoundError:  # pragma: no cover - lane-dependent
    arcs_verify = None

pytestmark = pytest.mark.skipif(
    arcs_verify is None,
    reason="arcs_verify not co-installed; ARCS Verify acceptance proofs skipped",
)

# The v0.2.1 envelope pin this repository vendors. The verifier ships its own
# copy; asserting the two are byte-identical is what makes "the verifier
# validated it" mean the same thing as "it validates against our pin".
VENDORED_V0_2_1_SHA256 = (
    "2afa1ec9f093fd7c06c4f5db7bfd37cc63e64e3dcbe47c963f4df586a1c18ca1"
)

# The ARCS Verify main this binding was validated against. The v0.2 contract
# requires a well-formed 40-hex commit in the report's provenance block, so a
# value is needed to build a report at all. It is report provenance only --
# nothing below asserts anything about it, and the verdicts and the origin
# disclosure are what these proofs actually check.
VALIDATED_AGAINST_VERIFIER_COMMIT = "4c3793b547b15dd2e5ac3d470ecd07e60274a956"


def _schema_path() -> Path:
    root = Path(inspect.getfile(arcs_verify)).parent
    candidates = sorted(root.rglob("srs-envelope-v0.2.1.schema.json"))
    assert candidates, "arcs-verify ships no v0.2.1 envelope schema"
    return candidates[0]


def _schema_sha256() -> str:
    return hashlib.sha256(_schema_path().read_bytes()).hexdigest()


def _governed_call(tmp_path: Path, **config_overrides):
    app = build_governed_test_app(
        tmp_path, tool_bodies={"echo": lambda _a: ok_result()}, **config_overrides
    )
    with app.client() as client:
        assert call_tool(client, "echo", {"text": "hi"}).status_code == 200
    receipts = app.receipts()
    assert receipts, "expected emitted receipts"
    return app, receipts


def _report(receipt: dict, trust_bundle: dict) -> dict:
    """Build the full v0.2 report through the real verifier."""

    verification = verify_receipt(
        receipt,
        trust_bundle,
        schema_path=_schema_path(),
        selected_profile=MCP_PROFILE,
    )
    return dagr_report.build_verification_report(
        receipt,
        verification,
        selected_profile=MCP_PROFILE,
        trust_bundle=trust_bundle,
        verifier_commit=VALIDATED_AGAINST_VERIFIER_COMMIT,
        envelope_schema_sha256=_schema_sha256(),
    )


def test_verifier_envelope_schema_matches_the_vendored_pin():
    """The verifier validates against the same bytes this repo pins."""

    assert _schema_sha256() == VENDORED_V0_2_1_SHA256


def test_valid_sdk_v2_receipts_are_accepted_and_disclose_the_origin(tmp_path):
    app, receipts = _governed_call(tmp_path)
    trust = app.emitter.identity.trust_bundle()

    kinds = set()
    for receipt in receipts:
        report = _report(receipt, trust)

        assert dagr_report.validate_verification_report(report) == []
        assert report["report_version"] == "v0.2"
        assert report["report_contract_id"] == "srs.dagr_verification_report.v0.2"

        verdicts = report["verdicts"]
        assert len(verdicts) == 8, verdicts
        assert all(verdicts.values()), verdicts
        assert report["failure_codes"] == []

        # Over the real transport every JSON-RPC request carries an id, so the
        # branch that actually ran is the request-derived one.
        assert report["subject_ref_origin_disclosed"] == "derived_from_request"
        kinds.add(receipt["receipt_kind"])

    assert kinds == {"admission", "outcome"}


def test_supplied_subject_is_disclosed_as_supplied(tmp_path):
    """The disclosure tracks the branch that ran, not a fixed value."""

    app, receipts = _governed_call(
        tmp_path, subject_ref_override="subject:operator:supplied"
    )
    trust = app.emitter.identity.trust_bundle()

    for receipt in receipts:
        report = _report(receipt, trust)
        assert dagr_report.validate_verification_report(report) == []
        assert all(report["verdicts"].values())
        assert report["subject_ref_origin_disclosed"] == "supplied_subject"


def test_validly_signed_semantic_mutation_fails_verification(tmp_path):
    """Flipping a semantic field inside the signed envelope must be rejected."""

    app, receipts = _governed_call(tmp_path)
    trust = app.emitter.identity.trust_bundle()
    outcome = next(r for r in receipts if r["receipt_kind"] == "outcome")
    assert outcome["outcome"] == "result_returned"

    mutated = copy.deepcopy(outcome)
    mutated["outcome"] = "error_returned"

    report = _report(mutated, trust)
    assert report["verdicts"]["signature_valid"] is False
    assert not all(report["verdicts"].values())
    assert "signature_invalid" in report["failure_codes"]


def test_origin_disclosure_is_signature_covered(tmp_path):
    """The origin cannot be edited after signing without failing verification."""

    app, receipts = _governed_call(tmp_path)
    trust = app.emitter.identity.trust_bundle()
    outcome = next(r for r in receipts if r["receipt_kind"] == "outcome")
    assert outcome["subject_ref_origin"] == "derived_from_request"

    mutated = copy.deepcopy(outcome)
    mutated["subject_ref_origin"] = "supplied_subject"

    report = _report(mutated, trust)
    assert report["verdicts"]["signature_valid"] is False
    assert "signature_invalid" in report["failure_codes"]


def test_out_of_vocabulary_origin_is_invalid_input_not_absence(tmp_path):
    """A sixth value is refused by the verifier, never rendered not_declared."""

    app, receipts = _governed_call(tmp_path)
    trust = app.emitter.identity.trust_bundle()
    mutated = copy.deepcopy(receipts[0])
    mutated["subject_ref_origin"] = "sixth_value"

    with pytest.raises(dagr_report.MalformedSubjectRefOrigin):
        _report(mutated, trust)
