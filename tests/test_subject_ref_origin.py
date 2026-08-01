"""Subject-reference origin disclosure — SRS envelope v0.2.1.

The envelope gains exactly one optional field, ``subject_ref_origin``, carrying a
closed five-value vocabulary. This module proves that every emitter path in this
repository declares it at its *own* decision branch, that the declaration
survives signing and a write/read round trip, that it validates against the
pinned v0.2.1 schema, that an out-of-vocabulary declaration is refused rather
than quietly degraded into absence, and that genuine absence stays a distinct
reading.

Two things this module deliberately does not do. It does not validate the field
against the v0.2.0 schema and call that a proof: v0.2.0 is top-level permissive,
so it accepts the field without checking it, and a test resting on that would be
defective. And the checks in :mod:`tests.receipt_verification` used here are
local in-repo checks — they are not ARCS Verify and are not reported as it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("rfc8785")
pytest.importorskip("jsonschema")

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator

from dagr_mcp.srs_bridge import BridgeConfig, HarnessSRSBridge
from dagr_mcp.srs_receipts import (
    RECEIPT_VERSION,
    SUBJECT_REF_ORIGIN_NOT_DECLARED,
    SUBJECT_REF_ORIGINS,
    RawEnvelopeFileSink,
    ReceiptContentError,
    ReceiptContext,
    SignedReceiptEmitter,
    SigningIdentity,
    read_subject_ref_origin,
)
from tests import receipt_verification
from tests.receipt_verification import subject_ref_origin_reading, verify_receipt

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "dagr_mcp" / "vendor" / "srs"
# The *selected validation schema* for every envelope proof in this module. The
# v0.2.1 pin is what makes these validations mean anything about the field.
SCHEMA_V0_2_1_PATH = VENDOR / "srs-envelope-v0.2.1.schema.json"
SCHEMA_V0_2_0_PATH = VENDOR / "srs-envelope-v0.2.0.schema.json"
SCHEMA_V0_2_1 = json.loads(SCHEMA_V0_2_1_PATH.read_text(encoding="utf-8"))
SCHEMA_V0_2_0 = json.loads(SCHEMA_V0_2_0_PATH.read_text(encoding="utf-8"))

DECLARED_ORIGINS = (
    "supplied_subject",
    "derived_from_session",
    "derived_from_request",
    "derived_from_supplied_correlation",
    "binding_minted",
)

# A fixed seed keeps the emitted example receipts reproducible. Test-only: it has
# no production validity and signs nothing outside this suite.
EXAMPLE_ONLY_PRIVATE_SEED = bytes(range(32, 64))


# --------------------------------------------------------------------------- #
# Emission helpers                                                            #
# --------------------------------------------------------------------------- #


def example_identity() -> SigningIdentity:
    return SigningIdentity(
        issuer_id="issuer:test:subject-ref-origin",
        key_id="issuer.test.subject-ref-origin/key/1",
        private_key=Ed25519PrivateKey.from_private_bytes(EXAMPLE_ONLY_PRIVATE_SEED),
    )


def build_emitter(directory: Path) -> tuple[SigningIdentity, SignedReceiptEmitter]:
    identity = example_identity()
    return identity, SignedReceiptEmitter(
        identity=identity, sink=RawEnvelopeFileSink(directory)
    )


def emitted(directory: Path) -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("urn_srs_receipt_*.json"))
    ]


def emit_admission_from(
    context: ReceiptContext, directory: Path
) -> tuple[SigningIdentity, dict[str, Any]]:
    """Emit a real signed admission receipt from *context* and read it back."""

    identity, emitter = build_emitter(directory)
    receipt_id = emitter.emit_admission(
        context=context,
        requested_tool_name="records.lookup",
        argument_digest="sha256:" + "a" * 64,
        disposition="admitted",
    )
    receipt = next(r for r in emitted(directory) if r["receipt_id"] == receipt_id)
    return identity, receipt


def assert_valid_under_pinned_v0_2_1(receipt: dict[str, Any]) -> None:
    assert not list(Draft202012Validator(SCHEMA_V0_2_1).iter_errors(receipt))


# --------------------------------------------------------------------------- #
# Binding drivers — each returns a receipt emitted through the real branch     #
# --------------------------------------------------------------------------- #


def bridge_receipt(directory: Path, *, session_ref: str | None, request_ref: str | None):
    """Drive the direct-harness bridge's own subject-reference decision."""

    identity, emitter = build_emitter(directory)
    bridge = HarnessSRSBridge(
        emitter=emitter,
        config=BridgeConfig(
            runtime_instance_id="runtime:test:bridge",
            boundary_id="boundary:test:bridge",
            policy_pack_id="policy:test:bridge",
            policy_pack_version="1",
        ),
    )
    harness_context = SimpleNamespace(
        session_ref=session_ref,
        request_ref=request_ref,
        actor_ref="actor:test:bridge",
        arguments_hash="sha256:" + "b" * 64,
    )
    receipt_id = bridge.emit_admission(
        harness_context=harness_context,
        tool_name="records.lookup",
        disposition="admitted",
    )
    receipt = next(r for r in emitted(directory) if r["receipt_id"] == receipt_id)
    return identity, receipt


def _fastmcp_middleware(directory: Path, **overrides: Any):
    from dagr_mcp.fastmcp_binding import DAGRMiddleware, DAGRMiddlewareConfig

    identity, emitter = build_emitter(directory)
    middleware = DAGRMiddleware(
        emitter=emitter,
        config=DAGRMiddlewareConfig(
            runtime_instance_id="runtime:test:fastmcp",
            boundary_id="boundary:test:fastmcp",
            policy_pack_id="policy:test:fastmcp",
            policy_pack_version="1",
            **overrides,
        ),
    )
    return identity, middleware


def fastmcp_receipt(
    directory: Path,
    *,
    session_id: str | None = None,
    request_id: str | None = None,
    **overrides: Any,
):
    """Drive the FastMCP middleware's own subject-reference decision."""

    from dagr_mcp.fastmcp_binding import BindingPolicy, default_actor_resolution

    identity, middleware = _fastmcp_middleware(directory, **overrides)
    context = SimpleNamespace(
        message=SimpleNamespace(name="records.lookup", arguments={"record_ref": "r:1"}),
        fastmcp_context=SimpleNamespace(request_id=request_id, session_id=session_id),
    )
    snapshot = middleware._snapshot_request(context)
    receipt_context = middleware._receipt_context(
        snapshot, default_actor_resolution(), BindingPolicy()
    )
    _identity, receipt = emit_admission_from(receipt_context, directory)
    return identity, snapshot, receipt


def _sdk_adapter(directory: Path, **overrides: Any):
    from dagr_mcp_sdk_binding.adapter import SdkBindingConfig, SdkLifecycleAdapter

    identity, emitter = build_emitter(directory)
    adapter = SdkLifecycleAdapter(
        emitter=emitter,
        config=SdkBindingConfig(
            runtime_instance_id="runtime:test:sdk",
            boundary_id="boundary:test:sdk",
            policy_pack_id="policy:test:sdk",
            policy_pack_version="1",
            **overrides,
        ),
    )
    return identity, adapter


def sdk_receipt(
    directory: Path,
    *,
    session_id: str | None = None,
    request_id: str | None = None,
    **overrides: Any,
):
    """Drive the official-SDK adapter's own subject-reference decision."""

    from dagr_mcp_sdk_binding.adapter import default_sdk_actor_resolution
    from dagr_mcp_sdk_binding.neutral import BindingPolicy

    identity, adapter = _sdk_adapter(directory, **overrides)
    request_context = SimpleNamespace(
        request_id=request_id,
        session=SimpleNamespace(session_id=session_id),
        meta=None,
    )
    snapshot = adapter._snapshot_request(
        "records.lookup", {"record_ref": "r:1"}, request_context
    )
    receipt_context = adapter._receipt_context(
        snapshot, default_sdk_actor_resolution(), BindingPolicy()
    )
    _identity, receipt = emit_admission_from(receipt_context, directory)
    return identity, snapshot, receipt


# --------------------------------------------------------------------------- #
# The pinned schema itself declares the field  (required proof 8)             #
# --------------------------------------------------------------------------- #


def test_selected_validation_schema_declares_subject_ref_origin():
    """The schema these proofs validate against declares the field itself.

    Without this, an envelope proof would show only that a permissive schema
    tolerated an unknown key.
    """

    declared = SCHEMA_V0_2_1["properties"]["subject_ref_origin"]
    assert declared["type"] == "string"
    assert declared["enum"] == list(DECLARED_ORIGINS)


def test_v0_2_0_validation_would_prove_nothing_about_the_field():
    """v0.2.0 is top-level permissive: it accepts the field without checking it.

    This is why the proofs above pin v0.2.1. A receipt carrying a *bogus* origin
    still validates against v0.2.0, so a v0.2.0 pass is not evidence.
    """

    assert "subject_ref_origin" not in SCHEMA_V0_2_0["properties"]
    assert SCHEMA_V0_2_0["additionalProperties"] is True

    bogus = {
        "receipt_version": RECEIPT_VERSION,
        "receipt_id": "urn:srs:receipt:admission:probe",
        "receipt_type": "sdk_enforcement",
        "boundary_type": "mcp_tool_call",
        "protocol_binding": "mcp",
        "subject_ref": "subject:probe",
        "subject_ref_origin": "not_a_declared_class",
        "issued_at": "2026-08-01T00:00:00Z",
        "artifact_classes_covered": ["tool_call_admission"],
        "artifact_classes_excluded": [],
        "attestation_limits": ["limit"],
        "extensions": {},
    }
    assert not list(Draft202012Validator(SCHEMA_V0_2_0).iter_errors(bogus))
    assert list(Draft202012Validator(SCHEMA_V0_2_1).iter_errors(bogus))


def test_emitter_vocabulary_is_exactly_the_schema_enum():
    assert SUBJECT_REF_ORIGINS == set(SCHEMA_V0_2_1["properties"]["subject_ref_origin"]["enum"])
    assert SUBJECT_REF_ORIGINS == set(DECLARED_ORIGINS)


def test_not_declared_is_a_reading_only_and_never_an_enum_member():
    assert SUBJECT_REF_ORIGIN_NOT_DECLARED == "not_declared"
    assert SUBJECT_REF_ORIGIN_NOT_DECLARED not in SUBJECT_REF_ORIGINS
    assert (
        SUBJECT_REF_ORIGIN_NOT_DECLARED
        not in SCHEMA_V0_2_1["properties"]["subject_ref_origin"]["enum"]
    )
    assert SUBJECT_REF_ORIGIN_NOT_DECLARED not in SCHEMA_V0_2_1_PATH.read_text(
        encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# Direct-harness bridge branches  (proofs 2, 3, 5)                            #
# --------------------------------------------------------------------------- #


def test_bridge_declares_derived_from_session(tmp_path):
    _identity, receipt = bridge_receipt(
        tmp_path, session_ref="session:sha256:aa", request_ref="request:sha256:bb"
    )
    assert receipt["subject_ref"] == "session:sha256:aa"
    assert receipt["subject_ref_origin"] == "derived_from_session"
    assert_valid_under_pinned_v0_2_1(receipt)


def test_bridge_declares_derived_from_request(tmp_path):
    _identity, receipt = bridge_receipt(
        tmp_path, session_ref=None, request_ref="request:sha256:bb"
    )
    assert receipt["subject_ref"] == "request:sha256:bb"
    assert receipt["subject_ref_origin"] == "derived_from_request"
    assert_valid_under_pinned_v0_2_1(receipt)


def test_bridge_declares_binding_minted(tmp_path):
    _identity, receipt = bridge_receipt(tmp_path, session_ref=None, request_ref=None)
    assert receipt["subject_ref"].startswith("tool-call:call-")
    assert receipt["subject_ref_origin"] == "binding_minted"
    assert_valid_under_pinned_v0_2_1(receipt)


def test_bridge_has_no_operator_override_branches():
    """The bridge takes no subject or correlation override, so two classes
    genuinely do not arise on this path — they are not silently substituted."""

    import dataclasses

    fields = {f.name for f in dataclasses.fields(BridgeConfig)}
    assert "subject_ref_override" not in fields
    assert "logical_call_id_override" not in fields


# --------------------------------------------------------------------------- #
# FastMCP middleware branches  (proofs 1-5)                                   #
# --------------------------------------------------------------------------- #


def test_fastmcp_declares_supplied_subject(tmp_path):
    _identity, snapshot, receipt = fastmcp_receipt(
        tmp_path,
        session_id="session-1",
        request_id="request-1",
        subject_ref_override="subject:operator:supplied",
    )
    assert receipt["subject_ref"] == "subject:operator:supplied"
    assert snapshot.subject_ref_origin == "supplied_subject"
    assert receipt["subject_ref_origin"] == "supplied_subject"
    assert_valid_under_pinned_v0_2_1(receipt)


def test_fastmcp_declares_derived_from_session(tmp_path):
    _identity, _snapshot, receipt = fastmcp_receipt(
        tmp_path, session_id="session-1", request_id="request-1"
    )
    assert receipt["subject_ref"].startswith("session:sha256:")
    assert receipt["subject_ref_origin"] == "derived_from_session"
    assert_valid_under_pinned_v0_2_1(receipt)


def test_fastmcp_declares_derived_from_request(tmp_path):
    _identity, _snapshot, receipt = fastmcp_receipt(
        tmp_path, session_id=None, request_id="request-1"
    )
    assert receipt["subject_ref"].startswith("request:sha256:")
    assert receipt["subject_ref_origin"] == "derived_from_request"
    assert_valid_under_pinned_v0_2_1(receipt)


def test_fastmcp_declares_derived_from_supplied_correlation(tmp_path):
    _identity, _snapshot, receipt = fastmcp_receipt(
        tmp_path,
        session_id=None,
        request_id=None,
        logical_call_id_override="call:operator:supplied",
    )
    assert receipt["logical_call_id"] == "call:operator:supplied"
    assert receipt["subject_ref"] == "tool-call:call:operator:supplied"
    assert receipt["subject_ref_origin"] == "derived_from_supplied_correlation"
    assert_valid_under_pinned_v0_2_1(receipt)


def test_fastmcp_declares_binding_minted(tmp_path):
    _identity, _snapshot, receipt = fastmcp_receipt(
        tmp_path, session_id=None, request_id=None
    )
    assert receipt["subject_ref"].startswith("tool-call:call:")
    assert receipt["subject_ref_origin"] == "binding_minted"
    assert_valid_under_pinned_v0_2_1(receipt)


def test_fastmcp_minted_and_supplied_correlation_are_not_collapsed(tmp_path):
    """Both branches build the same *shape* of subject reference. They remain two
    decisions, and the receipt says which one happened."""

    minted = tmp_path / "minted"
    supplied = tmp_path / "supplied"
    _i1, _s1, minted_receipt = fastmcp_receipt(minted, session_id=None, request_id=None)
    _i2, _s2, supplied_receipt = fastmcp_receipt(
        supplied,
        session_id=None,
        request_id=None,
        logical_call_id_override="call:operator:supplied",
    )
    assert minted_receipt["subject_ref"].startswith("tool-call:")
    assert supplied_receipt["subject_ref"].startswith("tool-call:")
    assert minted_receipt["subject_ref_origin"] == "binding_minted"
    assert supplied_receipt["subject_ref_origin"] == "derived_from_supplied_correlation"


# --------------------------------------------------------------------------- #
# Official-SDK adapter branches  (proofs 1-5)                                 #
# --------------------------------------------------------------------------- #


def test_sdk_declares_supplied_subject(tmp_path):
    _identity, snapshot, receipt = sdk_receipt(
        tmp_path,
        session_id="session-1",
        request_id="request-1",
        subject_ref_override="subject:operator:supplied",
    )
    assert receipt["subject_ref"] == "subject:operator:supplied"
    assert snapshot.subject_ref_origin == "supplied_subject"
    assert receipt["subject_ref_origin"] == "supplied_subject"
    assert_valid_under_pinned_v0_2_1(receipt)


def test_sdk_declares_derived_from_session(tmp_path):
    _identity, _snapshot, receipt = sdk_receipt(
        tmp_path, session_id="session-1", request_id="request-1"
    )
    assert receipt["subject_ref"].startswith("session:sha256:")
    assert receipt["subject_ref_origin"] == "derived_from_session"
    assert_valid_under_pinned_v0_2_1(receipt)


def test_sdk_declares_derived_from_request(tmp_path):
    _identity, _snapshot, receipt = sdk_receipt(
        tmp_path, session_id=None, request_id="request-1"
    )
    assert receipt["subject_ref"].startswith("request:sha256:")
    assert receipt["subject_ref_origin"] == "derived_from_request"
    assert_valid_under_pinned_v0_2_1(receipt)


def test_sdk_declares_derived_from_supplied_correlation(tmp_path):
    _identity, _snapshot, receipt = sdk_receipt(
        tmp_path,
        session_id=None,
        request_id=None,
        logical_call_id_override="call:operator:supplied",
    )
    assert receipt["logical_call_id"] == "call:operator:supplied"
    assert receipt["subject_ref"] == "tool-call:call:operator:supplied"
    assert receipt["subject_ref_origin"] == "derived_from_supplied_correlation"
    assert_valid_under_pinned_v0_2_1(receipt)


def test_sdk_declares_binding_minted(tmp_path):
    _identity, _snapshot, receipt = sdk_receipt(tmp_path, session_id=None, request_id=None)
    assert receipt["subject_ref"].startswith("tool-call:call:")
    assert receipt["subject_ref_origin"] == "binding_minted"
    assert_valid_under_pinned_v0_2_1(receipt)


# --------------------------------------------------------------------------- #
# Live FastMCP path                                                           #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_live_fastmcp_call_emits_the_declared_origin(tmp_path):
    """The disclosure reaches receipts through the real middleware call path,
    not only through a directly-driven snapshot."""

    pytest.importorskip("fastmcp")
    from fastmcp import FastMCP
    from fastmcp.client import Client

    from dagr_mcp.fastmcp_binding import DAGRMiddleware, DAGRMiddlewareConfig

    directory = tmp_path / "receipts"
    identity, emitter = build_emitter(directory)
    server = FastMCP("dagr-mcp-subject-ref-origin")
    server.add_middleware(
        DAGRMiddleware(
            emitter=emitter,
            config=DAGRMiddlewareConfig(
                runtime_instance_id="runtime:test:live",
                boundary_id="boundary:test:live",
                policy_pack_id="policy:test:live",
                policy_pack_version="1",
                tool_classes={"records_lookup": "read"},
                subject_ref_override="subject:operator:live",
            ),
        )
    )

    @server.tool
    async def records_lookup(record_ref: str) -> dict[str, object]:
        return {"record_ref": record_ref, "found": True}

    async with Client(server) as client:
        await client.call_tool("records_lookup", {"record_ref": "record:1"})

    receipts = emitted(directory)
    assert len(receipts) == 2
    for receipt in receipts:
        assert receipt["subject_ref_origin"] == "supplied_subject"
        assert_valid_under_pinned_v0_2_1(receipt)
        verify_receipt(receipt, identity.trust_bundle(), SCHEMA_V0_2_1)


# --------------------------------------------------------------------------- #
# Round-trip survival  (required proof 6)                                     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("origin", DECLARED_ORIGINS)
def test_declared_origin_survives_signing_and_a_write_read_round_trip(origin, tmp_path):
    directory = tmp_path / origin
    identity, receipt = emit_admission_from(
        ReceiptContext(
            runtime_instance_id="runtime:test:roundtrip",
            boundary_id="boundary:test:roundtrip",
            policy_pack_id="policy:test:roundtrip",
            policy_pack_version="1",
            subject_ref="subject:test:roundtrip",
            subject_ref_origin=origin,
            logical_call_id="call:test:roundtrip",
            binding_version="fastmcp.middleware.v0.1",
        ),
        directory,
    )
    # Read back from the durable sink, not from the in-memory envelope.
    assert receipt["subject_ref_origin"] == origin
    assert read_subject_ref_origin(receipt) == origin
    assert_valid_under_pinned_v0_2_1(receipt)
    verify_receipt(receipt, identity.trust_bundle(), SCHEMA_V0_2_1)

    # A second read of the same file is stable.
    reread = emitted(directory)[0]
    assert reread == receipt


def test_signature_covers_the_declared_origin(tmp_path):
    from cryptography.exceptions import InvalidSignature

    identity, receipt = emit_admission_from(
        ReceiptContext(
            runtime_instance_id="runtime:test:sig",
            boundary_id="boundary:test:sig",
            policy_pack_id="policy:test:sig",
            policy_pack_version="1",
            subject_ref="subject:test:sig",
            subject_ref_origin="derived_from_session",
            logical_call_id="call:test:sig",
            binding_version="fastmcp.middleware.v0.1",
        ),
        tmp_path,
    )
    tampered = copy.deepcopy(receipt)
    tampered["subject_ref_origin"] = "supplied_subject"
    with pytest.raises(InvalidSignature):
        verify_receipt(tampered, identity.trust_bundle(), SCHEMA_V0_2_1)


# --------------------------------------------------------------------------- #
# Out-of-vocabulary declarations fail  (required proof 9)                     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "bad",
    [
        "not_declared",
        "",
        "SUPPLIED_SUBJECT",
        "derived_from_subject",
        "sixth_value",
        123,
        True,
        ["supplied_subject"],
        {"origin": "supplied_subject"},
    ],
)
def test_out_of_vocabulary_declaration_is_refused_and_never_becomes_absence(
    bad, tmp_path
):
    _identity, emitter = build_emitter(tmp_path)
    context = ReceiptContext(
        runtime_instance_id="runtime:test:bad",
        boundary_id="boundary:test:bad",
        policy_pack_id="policy:test:bad",
        policy_pack_version="1",
        subject_ref="subject:test:bad",
        subject_ref_origin=bad,  # type: ignore[arg-type]
        logical_call_id="call:test:bad",
        binding_version="fastmcp.middleware.v0.1",
    )
    with pytest.raises(ReceiptContentError, match="outside the closed vocabulary"):
        emitter.emit_admission(
            context=context,
            requested_tool_name="records.lookup",
            argument_digest="sha256:" + "a" * 64,
            disposition="admitted",
        )
    # Nothing was written: the refusal is not a silent downgrade to a receipt
    # that merely declares nothing.
    assert not emitted(tmp_path)


def test_outcome_emission_refuses_the_same_way(tmp_path):
    _identity, emitter = build_emitter(tmp_path)
    with pytest.raises(ReceiptContentError, match="outside the closed vocabulary"):
        emitter.emit_outcome(
            context=ReceiptContext(
                runtime_instance_id="runtime:test:bad",
                boundary_id="boundary:test:bad",
                policy_pack_id="policy:test:bad",
                policy_pack_version="1",
                subject_ref="subject:test:bad",
                subject_ref_origin="not_declared",
                logical_call_id="call:test:bad",
                binding_version="fastmcp.middleware.v0.1",
            ),
            admission_receipt_ref="urn:srs:receipt:admission:1",
            outcome="result_returned",
            result_digest="sha256:" + "c" * 64,
        )
    assert not emitted(tmp_path)


@pytest.mark.parametrize("bad", ["not_declared", "sixth_value", 7, None])
def test_reader_refuses_a_present_but_malformed_value(bad):
    receipt = {"subject_ref": "subject:x", "subject_ref_origin": bad}
    with pytest.raises(ReceiptContentError, match="outside the closed vocabulary"):
        read_subject_ref_origin(receipt)
    with pytest.raises(AssertionError):
        subject_ref_origin_reading(receipt)


# --------------------------------------------------------------------------- #
# Genuine absence stays distinct  (required proof 10)                         #
# --------------------------------------------------------------------------- #


def test_genuine_absence_is_a_distinct_reading(tmp_path):
    identity, receipt = emit_admission_from(
        ReceiptContext(
            runtime_instance_id="runtime:test:absent",
            boundary_id="boundary:test:absent",
            policy_pack_id="policy:test:absent",
            policy_pack_version="1",
            subject_ref="subject:test:absent",
            logical_call_id="call:test:absent",
            binding_version="fastmcp.middleware.v0.1",
        ),
        tmp_path,
    )
    assert "subject_ref_origin" not in receipt
    assert read_subject_ref_origin(receipt) == SUBJECT_REF_ORIGIN_NOT_DECLARED
    assert read_subject_ref_origin(receipt) not in SUBJECT_REF_ORIGINS
    # Absence is fully conformant under the pinned schema.
    assert_valid_under_pinned_v0_2_1(receipt)
    verify_receipt(receipt, identity.trust_bundle(), SCHEMA_V0_2_1)


def test_historical_committed_receipts_read_as_not_declared():
    """Committed receipts predating this step are read, not re-emitted. They
    declare nothing, and that stays distinct from every declared class."""

    golden = ROOT / "tests" / "golden" / "behavioral_freeze"
    receipts = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(golden.glob("urn_srs_receipt_*.json"))
    ]
    assert receipts, "expected committed historical receipts to read"
    for receipt in receipts:
        assert "subject_ref_origin" not in receipt
        assert read_subject_ref_origin(receipt) == SUBJECT_REF_ORIGIN_NOT_DECLARED
        assert subject_ref_origin_reading(receipt) == "not_declared"
        # Still valid under the newer pinned schema; nothing about them changed.
        assert_valid_under_pinned_v0_2_1(receipt)


# --------------------------------------------------------------------------- #
# The local checker reads and checks the field  (required proof 11)           #
# --------------------------------------------------------------------------- #


def test_local_receipt_check_reads_and_checks_the_field(tmp_path):
    identity, receipt = emit_admission_from(
        ReceiptContext(
            runtime_instance_id="runtime:test:check",
            boundary_id="boundary:test:check",
            policy_pack_id="policy:test:check",
            policy_pack_version="1",
            subject_ref="subject:test:check",
            subject_ref_origin="derived_from_request",
            logical_call_id="call:test:check",
            binding_version="fastmcp.middleware.v0.1",
        ),
        tmp_path,
    )
    assert subject_ref_origin_reading(receipt) == "derived_from_request"
    verify_receipt(receipt, identity.trust_bundle(), SCHEMA_V0_2_1)

    # A receipt carrying a value outside the closed vocabulary does not pass the
    # local check, even before any signature question is reached.
    bogus = copy.deepcopy(receipt)
    bogus["subject_ref_origin"] = "sixth_value"
    with pytest.raises(AssertionError):
        verify_receipt(bogus, identity.trust_bundle(), SCHEMA_V0_2_1)


def test_local_receipt_check_is_not_arcs_verify():
    """The helper above is this repository's own check. It is neither named nor
    described as the external verifier, and it imports none of it."""

    source = (ROOT / "tests" / "receipt_verification.py").read_text(encoding="utf-8")
    assert "arcs_verify" not in source
    assert "ARCS Verify" in source  # the disclaimer itself
    assert not hasattr(receipt_verification, "verify")
    assert receipt_verification.DECLARED_SUBJECT_REF_ORIGINS == SUBJECT_REF_ORIGINS
    assert receipt_verification.NOT_DECLARED_READING == SUBJECT_REF_ORIGIN_NOT_DECLARED


# --------------------------------------------------------------------------- #
# Version boundary                                                            #
# --------------------------------------------------------------------------- #


def test_receipt_version_is_unchanged_and_no_envelope_version_is_self_declared(tmp_path):
    _identity, receipt = emit_admission_from(
        ReceiptContext(
            runtime_instance_id="runtime:test:version",
            boundary_id="boundary:test:version",
            policy_pack_id="policy:test:version",
            policy_pack_version="1",
            subject_ref="subject:test:version",
            subject_ref_origin="binding_minted",
            logical_call_id="call:test:version",
            binding_version="fastmcp.middleware.v0.1",
        ),
        tmp_path,
    )
    assert RECEIPT_VERSION == "srs.core.v5.1"
    assert receipt["receipt_version"] == "srs.core.v5.1"
    # The envelope artifact version is established by the pinned schema and the
    # validation path, never by a field the receipt asserts about itself.
    assert not [key for key in receipt if "envelope" in key.lower()]
    assert "0.2.1" not in json.dumps(receipt)
