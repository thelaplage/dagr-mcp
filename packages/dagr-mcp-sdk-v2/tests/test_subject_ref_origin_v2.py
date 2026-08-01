"""Subject-reference origin disclosure on the official-SDK-v2 binding path.

The SRS envelope v0.2.1 field ``subject_ref_origin`` carries a closed five-value
vocabulary. This module establishes, for the ``official-mcp-sdk.python.v0.2``
binding specifically:

* which origin classes are structurally reachable on this path, each proved at
  the binding's own decision branch (:meth:`SdkV2LifecycleAdapter._receipt_context`)
  rather than by constructing a receipt by hand;
* that two of them reach real receipts over the genuine ``mcp==2.0.0`` stateless
  Streamable HTTP stack, not merely through a directly-driven adapter;
* that ``derived_from_session`` is structurally UNREACHABLE here, and why that
  is a property of protocol 2026-07-28 rather than an omission in this binding;
* that the closed vocabulary is enforced by the neutral core for this binding's
  emissions exactly as it is for every other binding.

The v0.2.1 schema is the selected validation schema throughout. v0.2.0 is
top-level permissive and would accept the field without checking it, so a
v0.2.0 pass would be no evidence at all about this field.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from dagr_mcp_core.srs_receipts import (
    SUBJECT_REF_ORIGIN_NOT_DECLARED,
    SUBJECT_REF_ORIGINS,
    ReceiptContentError,
    read_subject_ref_origin,
)
from dagr_mcp_sdk_v2.adapter import (
    ActorResolution,
    SdkV2BindingConfig,
    SdkV2LifecycleAdapter,
)

from harness import build_governed_test_app, call_tool, ok_result

# The pinned v0.2.1 envelope, vendored beside this package's own tests rather
# than read across the repository from dagr-mcp-core. This distribution ships a
# runnable test surface, so a shipped test may only depend on files that travel
# inside its own sdist; a sibling-package path resolves in a repository checkout
# and nowhere else. The digest assertion below is what keeps the two copies from
# drifting apart -- they are the same pinned bytes, not merely similar files.
SCHEMA_V0_2_1_PATH = Path(__file__).parent / "vendor" / "srs-envelope-v0.2.1.schema.json"
SCHEMA_V0_2_1 = json.loads(SCHEMA_V0_2_1_PATH.read_text(encoding="utf-8"))

VENDORED_V0_2_1_SHA256 = (
    "2afa1ec9f093fd7c06c4f5db7bfd37cc63e64e3dcbe47c963f4df586a1c18ca1"
)

DECLARED_ORIGINS = (
    "supplied_subject",
    "derived_from_session",
    "derived_from_request",
    "derived_from_supplied_correlation",
    "binding_minted",
)

# What this binding can actually produce. `derived_from_session` is absent by
# protocol, not by oversight -- see the dedicated test below.
REACHABLE_ON_V2 = frozenset(
    {
        "supplied_subject",
        "derived_from_request",
        "derived_from_supplied_correlation",
        "binding_minted",
    }
)
STRUCTURALLY_UNREACHABLE_ON_V2 = frozenset({"derived_from_session"})


def valid_under_v0_2_1(receipt: dict) -> None:
    assert not list(Draft202012Validator(SCHEMA_V0_2_1).iter_errors(receipt))


def _adapter(**overrides) -> SdkV2LifecycleAdapter:
    """An adapter with no emitter work needed -- `_receipt_context` is pure."""

    config = SdkV2BindingConfig(
        runtime_instance_id="rt:v2-origin",
        boundary_id="b:v2-origin",
        policy_pack_id="p:v2-origin",
        policy_pack_version="1",
        **overrides,
    )
    return SdkV2LifecycleAdapter(emitter=None, config=config)  # type: ignore[arg-type]


def _ctx(request_id: object | None):
    """A stand-in for the SDK's per-request context carrying only what the
    binding's subject-reference branch actually reads."""

    return SimpleNamespace(request_id=request_id)


# --------------------------------------------------------------------------- #
# Vocabulary and partition                                                    #
# --------------------------------------------------------------------------- #


def test_vendored_schema_matches_the_pin():
    """The locally vendored copy is the pinned v0.2.1 bytes, not a lookalike."""

    import hashlib

    assert (
        hashlib.sha256(SCHEMA_V0_2_1_PATH.read_bytes()).hexdigest()
        == VENDORED_V0_2_1_SHA256
    )


def test_vocabulary_matches_the_pinned_schema_enum():
    assert SUBJECT_REF_ORIGINS == set(
        SCHEMA_V0_2_1["properties"]["subject_ref_origin"]["enum"]
    )
    assert SUBJECT_REF_ORIGINS == set(DECLARED_ORIGINS)


def test_reachability_partition_is_exhaustive_and_disjoint():
    """Every declared class is accounted for as reachable or documented-unreachable."""

    assert REACHABLE_ON_V2.isdisjoint(STRUCTURALLY_UNREACHABLE_ON_V2)
    assert REACHABLE_ON_V2 | STRUCTURALLY_UNREACHABLE_ON_V2 == set(DECLARED_ORIGINS)


def test_not_declared_is_never_emitted_by_this_binding():
    assert SUBJECT_REF_ORIGIN_NOT_DECLARED not in SUBJECT_REF_ORIGINS
    assert SUBJECT_REF_ORIGIN_NOT_DECLARED not in DECLARED_ORIGINS


# --------------------------------------------------------------------------- #
# Each reachable class, at the binding's own decision branch                   #
# --------------------------------------------------------------------------- #


def test_supplied_subject_branch():
    ctx = _adapter(subject_ref_override="subject:operator:supplied")._receipt_context(
        _ctx("req-1"), ActorResolution()
    )
    assert ctx.subject_ref == "subject:operator:supplied"
    assert ctx.subject_ref_origin == "supplied_subject"


def test_derived_from_request_branch():
    ctx = _adapter()._receipt_context(_ctx("req-1"), ActorResolution())
    assert ctx.subject_ref == "request:req-1"
    assert ctx.subject_ref_origin == "derived_from_request"


def test_derived_from_supplied_correlation_branch():
    """No request id, but the operator supplied the call correlation."""

    ctx = _adapter(logical_call_id_override="call:operator:supplied")._receipt_context(
        _ctx(None), ActorResolution()
    )
    assert ctx.logical_call_id == "call:operator:supplied"
    assert ctx.subject_ref == "tool-call:call:operator:supplied"
    assert ctx.subject_ref_origin == "derived_from_supplied_correlation"


def test_binding_minted_branch():
    """No request id and no operator correlation: this binding minted the id."""

    ctx = _adapter()._receipt_context(_ctx(None), ActorResolution())
    assert ctx.logical_call_id.startswith("call:")
    assert ctx.subject_ref == f"tool-call:{ctx.logical_call_id}"
    assert ctx.subject_ref_origin == "binding_minted"


def test_minted_and_supplied_correlation_are_not_collapsed():
    """Both build the same *shape* of subject reference and remain two decisions."""

    minted = _adapter()._receipt_context(_ctx(None), ActorResolution())
    supplied = _adapter(
        logical_call_id_override="call:operator:supplied"
    )._receipt_context(_ctx(None), ActorResolution())

    assert minted.subject_ref.startswith("tool-call:")
    assert supplied.subject_ref.startswith("tool-call:")
    assert minted.subject_ref_origin == "binding_minted"
    assert supplied.subject_ref_origin == "derived_from_supplied_correlation"


def test_request_id_wins_over_a_supplied_correlation():
    """Precedence matches the FastMCP and v0.1 SDK bindings exactly: a real
    request reference is a stronger subject than a supplied call correlation."""

    ctx = _adapter(logical_call_id_override="call:operator:supplied")._receipt_context(
        _ctx("req-1"), ActorResolution()
    )
    assert ctx.subject_ref == "request:req-1"
    assert ctx.subject_ref_origin == "derived_from_request"


@pytest.mark.parametrize("origin", sorted(REACHABLE_ON_V2))
def test_every_reachable_origin_is_in_the_closed_vocabulary(origin):
    assert origin in SUBJECT_REF_ORIGINS


# --------------------------------------------------------------------------- #
# Why derived_from_session is structurally unreachable here                    #
# --------------------------------------------------------------------------- #


def test_protocol_2026_07_28_has_no_session_identifier_to_derive_from():
    """The unreachability is a protocol fact, mechanically checked.

    Protocol 2026-07-28 is a self-contained POST: no ``initialize`` handshake
    and no ``Mcp-Session-Id``. The SDK's ``ServerSession`` -- what
    ``ServerRequestContext.session`` holds -- correspondingly exposes no session
    identifier of any kind. There is therefore nothing for a
    ``derived_from_session`` branch to read, and this binding does not invent
    one or substitute another class in its place.
    """

    from mcp.server.session import ServerSession

    identifier_attrs = [
        name
        for name in dir(ServerSession)
        if not name.startswith("_") and ("session_id" in name or name == "id")
    ]
    assert identifier_attrs == [], identifier_attrs


def test_binding_declares_no_session_origin_on_any_input():
    """No combination of inputs this binding reads yields the session class."""

    produced = set()
    for request_id in ("req-1", None):
        for overrides in (
            {},
            {"subject_ref_override": "subject:operator:supplied"},
            {"logical_call_id_override": "call:operator:supplied"},
            {
                "subject_ref_override": "subject:operator:supplied",
                "logical_call_id_override": "call:operator:supplied",
            },
        ):
            ctx = _adapter(**overrides)._receipt_context(
                _ctx(request_id), ActorResolution()
            )
            produced.add(ctx.subject_ref_origin)

    assert produced == REACHABLE_ON_V2
    assert produced.isdisjoint(STRUCTURALLY_UNREACHABLE_ON_V2)


# --------------------------------------------------------------------------- #
# Real receipts over the genuine stateless HTTP stack                          #
# --------------------------------------------------------------------------- #


def test_live_http_call_declares_derived_from_request(tmp_path):
    """Over the real 2026-07-28 transport every JSON-RPC request carries an id,
    so the ordinary governed call declares ``derived_from_request``."""

    app = build_governed_test_app(tmp_path, tool_bodies={"echo": lambda a: ok_result()})
    with app.client() as client:
        response = call_tool(client, "echo", {"text": "hi"})
    assert response.status_code == 200

    receipts = app.receipts()
    assert receipts, "expected emitted receipts"
    for receipt in receipts:
        assert receipt["subject_ref_origin"] == "derived_from_request"
        assert read_subject_ref_origin(receipt) == "derived_from_request"
        valid_under_v0_2_1(receipt)


def test_live_http_call_declares_supplied_subject(tmp_path):
    app = build_governed_test_app(
        tmp_path,
        tool_bodies={"echo": lambda a: ok_result()},
        subject_ref_override="subject:operator:supplied",
    )
    with app.client() as client:
        response = call_tool(client, "echo", {"text": "hi"})
    assert response.status_code == 200

    receipts = app.receipts()
    assert receipts
    for receipt in receipts:
        assert receipt["subject_ref"] == "subject:operator:supplied"
        assert receipt["subject_ref_origin"] == "supplied_subject"
        valid_under_v0_2_1(receipt)


def test_live_http_admission_and_outcome_agree_on_the_origin(tmp_path):
    """Both receipts for one call declare the same origin -- the disclosure is a
    property of the call, not of an individual emission."""

    app = build_governed_test_app(tmp_path, tool_bodies={"echo": lambda a: ok_result()})
    with app.client() as client:
        call_tool(client, "echo", {"text": "hi"})

    admissions = app.admission_receipts()
    outcomes = app.outcome_receipts()
    assert admissions and outcomes
    origins = {r["subject_ref_origin"] for r in admissions + outcomes}
    assert origins == {"derived_from_request"}


# --------------------------------------------------------------------------- #
# The closed vocabulary is enforced for this binding's emissions too           #
# --------------------------------------------------------------------------- #


def test_out_of_vocabulary_origin_is_refused_before_signing(tmp_path):
    """The neutral core refuses, so this binding cannot emit a sixth value even
    if a future change tried to declare one."""

    from dagr_mcp_core.srs_receipts import (
        RawEnvelopeFileSink,
        ReceiptContext,
        SignedReceiptEmitter,
        SigningIdentity,
    )

    directory = tmp_path / "receipts"
    emitter = SignedReceiptEmitter(
        identity=SigningIdentity.generate(
            issuer_id="issuer:v2-origin", key_id="issuer.v2-origin/key/1"
        ),
        sink=RawEnvelopeFileSink(directory),
    )
    with pytest.raises(ReceiptContentError, match="outside the closed vocabulary"):
        emitter.emit_admission(
            context=ReceiptContext(
                runtime_instance_id="rt:v2-origin",
                boundary_id="b:v2-origin",
                policy_pack_id="p:v2-origin",
                policy_pack_version="1",
                subject_ref="subject:x",
                subject_ref_origin="derived_from_session_somehow",
                logical_call_id="call:1",
                binding_version="official-mcp-sdk.python.v0.2",
            ),
            requested_tool_name="echo",
            argument_digest="sha256:" + "a" * 64,
            disposition="admitted",
        )
    assert not directory.exists() or not list(directory.glob("*.json"))
