"""Tests for the pre-validated caller principal seam (DAGR-MCP-PRINCIPAL0).

Seam-1 closure: ``dagr_mcp.caller_principal.CallerPrincipal`` is now a thin
adapter over the canonical ``dagr_sdk.caller_auth_context.CallerAuthContext``
wire contract, not an independent three-field shape. These tests cover: the
three distinguishable caller states (delegated to the SDK contract), that
credential-shape validation lives in exactly one place (the SDK contract,
never re-implemented here), lossless projection onto the existing duck-typed
``caller_context`` surface already consumed by
``dagr_mcp.enforcement_harness.wrap_handler``, an operator policy resolver
reaching an authenticated principal and refusing on a missing scope (never a
hardcoded DAGR rule), that the principal never changes tool identity, that
admission/outcome receipt linkage through the existing SRS ``actor_ref``
field is unchanged whether or not a principal is supplied, and a
cross-language golden-vector proof that the SDK's committed v0.1 wire
vectors survive vector -> ``CallerAuthContext`` -> DAGR MCP unchanged.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from dagr_sdk.caller_auth_context import CallerAuthContext, CallerAuthContextError

from dagr_mcp.caller_principal import (
    ANONYMOUS_CALLER_PRINCIPAL,
    CALLER_PRINCIPAL_STATES,
    CallerPrincipal,
    CallerPrincipalError,
)
from dagr_mcp.enforcement_harness import HarnessConfig, HarnessSinks, ToolPolicy, wrap_handler
from dagr_mcp.operator_admission_resolver import resolve_operator_admission
from dagr_mcp.sdk_spine import InMemoryEventSink
from dagr_mcp.srs_bridge import BridgeConfig, HarnessSRSBridge
from dagr_mcp.srs_receipts import RawEnvelopeFileSink, SignedReceiptEmitter, SigningIdentity


def _auth(**kwargs) -> CallerAuthContext:
    return CallerAuthContext(**kwargs)


def _principal(**kwargs) -> CallerPrincipal:
    return CallerPrincipal(auth=_auth(**kwargs))


# --------------------------------------------------------------------------- #
# CallerPrincipal is a thin adapter: no re-declared credential validation.   #
# --------------------------------------------------------------------------- #


def test_caller_principal_error_is_the_sdk_contract_error():
    # Exactly one validation authority: CallerPrincipalError IS
    # CallerAuthContextError, not a parallel, re-implemented exception type.
    assert CallerPrincipalError is CallerAuthContextError


def test_caller_principal_wraps_exactly_one_auth_context_field():
    field_names = {f.name for f in dataclasses.fields(CallerPrincipal)}
    assert field_names == {"auth"}


def test_caller_principal_rejects_non_auth_context_payload():
    with pytest.raises(CallerPrincipalError):
        CallerPrincipal(auth={"state": "anonymous"})  # type: ignore[arg-type]


def test_malformed_auth_context_construction_fails_in_the_sdk_contract():
    # Credential-shape / state-vocabulary guards are exercised (and owned)
    # entirely by dagr_sdk.caller_auth_context; CallerPrincipal adds none.
    with pytest.raises(CallerAuthContextError):
        _auth(state="superuser", principal_ref="user:1")
    with pytest.raises(CallerAuthContextError):
        _auth(state="authenticated_user", principal_ref="Bearer abc.def.ghi")
    with pytest.raises(CallerAuthContextError):
        _auth(state="anonymous", principal_ref="user:1")


# --------------------------------------------------------------------------- #
# Three distinguishable caller states, delegated to the SDK contract          #
# --------------------------------------------------------------------------- #


def test_three_caller_states_are_closed_and_distinguishable():
    assert CALLER_PRINCIPAL_STATES == (
        "anonymous",
        "authenticated_machine",
        "authenticated_user",
    )
    anon = _principal(state="anonymous")
    user = _principal(state="authenticated_user", principal_ref="user:1")
    machine = _principal(
        state="authenticated_machine", principal_ref="svc:acct:1", scope_refs={"read"}
    )
    assert {anon.state, user.state, machine.state} == set(CALLER_PRINCIPAL_STATES)
    assert anon.is_authenticated is False
    assert user.is_authenticated is True
    assert machine.is_authenticated is True
    assert anon.principal_ref is None
    assert user.principal_ref == "user:1"
    assert machine.scopes == frozenset({"read"})


def test_projections_never_carry_more_than_ref_state_scopes():
    principal = _principal(
        state="authenticated_machine",
        principal_ref="svc:acct:9",
        scope_refs={"read", "write"},
    )
    context = principal.to_caller_context(session_ref="session:1", request_ref="req:1")
    assert set(context) == {"actor_ref", "session_ref", "request_ref"}
    assert context["actor_ref"] == "svc:acct:9"

    resolver_view = principal.for_policy_resolver()
    assert set(resolver_view) == {"principal_state", "principal_ref", "scopes"}
    assert resolver_view["scopes"] == ("read", "write")
    serialized = json.dumps(resolver_view)
    for banned in ("bearer", "token", "password", "secret"):
        assert banned not in serialized.lower()


# --------------------------------------------------------------------------- #
# Lossless projection onto the existing duck-typed caller_context surface    #
# --------------------------------------------------------------------------- #


def _config() -> HarnessConfig:
    return HarnessConfig(
        harness_version="0.1.0",
        module_id="module.test",
        module_version="1.2.3",
        profile_ref="profile:test",
        policy_ref="policy:test",
    )


def _allow_policy(tool_name: str = "read_status") -> ToolPolicy:
    return ToolPolicy(tool_name=tool_name, tool_class="read", decision="allow")


def test_anonymous_principal_preserves_existing_no_context_behavior():
    handler_calls: list[tuple[str, object, object]] = []

    def inner(tool_name, arguments, context=None):
        handler_calls.append((tool_name, arguments, context))
        return {"ok": True}

    wrapped = wrap_handler(
        inner,
        _config(),
        HarnessSinks(event=InMemoryEventSink()),
        policies=[_allow_policy()],
    )

    baseline = wrapped("read_status", {"q": 1})
    principal_context = ANONYMOUS_CALLER_PRINCIPAL.to_caller_context()
    via_anonymous_principal = wrapped("read_status", {"q": 1}, context=principal_context)

    assert baseline.ok is True and via_anonymous_principal.ok is True
    assert baseline.context.actor_ref is None
    assert via_anonymous_principal.context.actor_ref is None
    assert baseline.context.session_ref == via_anonymous_principal.context.session_ref
    assert baseline.policy_decision.decision == via_anonymous_principal.policy_decision.decision


def test_authenticated_principal_actor_ref_reaches_harness_context():
    def inner(tool_name, arguments, context=None):
        return {"ok": True}

    wrapped = wrap_handler(
        inner,
        _config(),
        HarnessSinks(event=InMemoryEventSink()),
        policies=[_allow_policy()],
    )

    principal = _principal(state="authenticated_user", principal_ref="user:42")
    governed = wrapped(
        "read_status", {"q": 1}, context=principal.to_caller_context(session_ref="session:7")
    )

    assert governed.ok is True
    assert governed.context.actor_ref == "user:42"
    assert governed.context.session_ref == "session:7"


def test_principal_does_not_change_tool_identity():
    calls: list[str] = []

    def inner(tool_name, arguments, context=None):
        calls.append(tool_name)
        return {"ok": True}

    wrapped = wrap_handler(
        inner,
        _config(),
        HarnessSinks(event=InMemoryEventSink()),
        policies=[_allow_policy("records.lookup")],
    )

    anon_result = wrapped(
        "records.lookup", {"id": 1}, context=ANONYMOUS_CALLER_PRINCIPAL.to_caller_context()
    )
    user = _principal(state="authenticated_user", principal_ref="user:1")
    user_result = wrapped("records.lookup", {"id": 1}, context=user.to_caller_context())
    machine = _principal(
        state="authenticated_machine", principal_ref="svc:1", scope_refs={"read"}
    )
    machine_result = wrapped("records.lookup", {"id": 1}, context=machine.to_caller_context())

    assert calls == ["records.lookup", "records.lookup", "records.lookup"]
    for result in (anon_result, user_result, machine_result):
        assert result.policy_decision.decision == "allow"
        assert result.policy_decision.policy_ref == "policy:test"


# --------------------------------------------------------------------------- #
# Operator policy resolver sees safe principal/scopes; refusal is operator-  #
# owned, never a hardcoded DAGR rule.                                        #
# --------------------------------------------------------------------------- #


def _operator_policy_function(principal: CallerPrincipal, *, required_scope: str):
    """Stand-in for an operator's own, out-of-repo policy resolver.

    This function lives conceptually outside DAGR (a fixture here only to
    exercise the seam); DAGR supplies nothing but the safe view from
    :meth:`CallerPrincipal.for_policy_resolver`.
    """

    view = principal.for_policy_resolver()
    if required_scope not in view["scopes"]:
        return "refused", f"missing_scope:{required_scope}"
    return "admitted", None


def test_authenticated_principal_reaches_policy_resolver_and_missing_scope_is_refused():
    principal = _principal(state="authenticated_user", principal_ref="user:7", scope_refs={"read"})

    decision, reason = _operator_policy_function(principal, required_scope="write")
    assert decision == "refused"
    assert reason == "missing_scope:write"

    policy = resolve_operator_admission(
        tool_name="records.write", tool_class="write", decision=decision, reason=reason
    )
    assert policy.decision == "deny"
    assert policy.reason == "missing_scope:write"


def test_authenticated_principal_with_required_scope_is_admitted():
    principal = _principal(
        state="authenticated_machine", principal_ref="svc:1", scope_refs={"read", "write"}
    )

    decision, reason = _operator_policy_function(principal, required_scope="write")
    assert decision == "admitted"

    policy = resolve_operator_admission(
        tool_name="records.write", tool_class="write", decision=decision, reason=reason
    )
    assert policy.decision == "allow"


def test_anonymous_principal_has_no_scopes_for_resolver():
    view = ANONYMOUS_CALLER_PRINCIPAL.for_policy_resolver()
    assert view["scopes"] == ()
    assert view["principal_ref"] is None
    assert view["principal_state"] == "anonymous"


# --------------------------------------------------------------------------- #
# Receipt discipline: existing actor_ref SRS surface only; admission/outcome #
# linkage unchanged with or without a principal.                             #
# --------------------------------------------------------------------------- #


def _srs_bridge(tmp_path: Path):
    identity = SigningIdentity.generate(issuer_id="issuer:test", key_id="issuer.test/key/1")
    sink = RawEnvelopeFileSink(tmp_path)
    emitter = SignedReceiptEmitter(identity=identity, sink=sink)
    bridge = HarnessSRSBridge(
        emitter=emitter,
        config=BridgeConfig(
            runtime_instance_id="runtime:test:1",
            boundary_id="boundary:test:1",
            policy_pack_id="policy:test",
            policy_pack_version="1",
        ),
    )
    return identity, bridge


def test_admission_outcome_linkage_unchanged_with_authenticated_principal(tmp_path):
    identity, bridge = _srs_bridge(tmp_path)

    def inner(tool_name, arguments, context=None):
        return {"ok": True, "count": 1}

    wrapped = wrap_handler(
        inner,
        HarnessConfig("1", "module", "1", "profile", "policy"),
        HarnessSinks(event=InMemoryEventSink()),
        policies=[ToolPolicy("records.lookup", "read", "allow")],
        srs_bridge=bridge,
    )

    principal = _principal(state="authenticated_user", principal_ref="user:99", scope_refs={"read"})
    result = wrapped(
        "records.lookup",
        {"record_ref": "record:1"},
        principal.to_caller_context(session_ref="session:call-1"),
    )
    assert result.ok is True

    paths = sorted(tmp_path.glob("urn_srs_receipt_*.json"))
    assert len(paths) == 2
    receipts = [json.loads(path.read_text()) for path in paths]
    admission = next(item for item in receipts if item["receipt_kind"] == "admission")
    outcome = next(item for item in receipts if item["receipt_kind"] == "outcome")

    # Linkage identical in shape to the no-principal path (test_srs_receipts.py).
    assert outcome["admission_receipt_ref"] == admission["receipt_id"]

    # Only the existing actor_ref field carries the principal; no new field,
    # no raw credential, no email/display name anywhere in either receipt.
    assert admission["actor_ref"] == "user:99"
    assert outcome["actor_ref"] == "user:99"
    for receipt in receipts:
        rendered = json.dumps(receipt)
        for banned in ("bearer", "password", "@", "scopes"):
            assert banned not in rendered.lower()


def test_admission_outcome_linkage_unchanged_when_anonymous(tmp_path):
    identity, bridge = _srs_bridge(tmp_path)

    def inner(tool_name, arguments, context=None):
        return {"ok": True, "count": 1}

    wrapped = wrap_handler(
        inner,
        HarnessConfig("1", "module", "1", "profile", "policy"),
        HarnessSinks(event=InMemoryEventSink()),
        policies=[ToolPolicy("records.lookup", "read", "allow")],
        srs_bridge=bridge,
    )

    result = wrapped(
        "records.lookup",
        {"record_ref": "record:1"},
        ANONYMOUS_CALLER_PRINCIPAL.to_caller_context(session_ref="session:call-2"),
    )
    assert result.ok is True

    paths = sorted(tmp_path.glob("urn_srs_receipt_*.json"))
    assert len(paths) == 2
    receipts = [json.loads(path.read_text()) for path in paths]
    admission = next(item for item in receipts if item["receipt_kind"] == "admission")
    outcome = next(item for item in receipts if item["receipt_kind"] == "outcome")

    assert outcome["admission_receipt_ref"] == admission["receipt_id"]
    assert "actor_ref" not in admission
    assert "actor_ref" not in outcome


# --------------------------------------------------------------------------- #
# Cross-language golden specimen: SDK v0.1 wire vectors -> CallerAuthContext #
# -> DAGR MCP adapters -> fixture operator policy resolver.                  #
# --------------------------------------------------------------------------- #


def _dagr_sdk_vectors_path() -> Path:
    # The installed dagr-sdk *distribution* packages only dagr_sdk*/garp_sdk*
    # (its own pyproject.toml [tool.setuptools.packages.find]) -- it does not
    # ship tests/fixtures/, so the committed conformance vectors are consumed
    # from the vendored, commit-pinned copy instead (see
    # dagr_mcp/vendor/dagr_sdk_caller_auth_context/PROVENANCE.md), mirroring
    # the existing arcs-srs -> arcs-verify commit-pin vendoring pattern.
    root = Path(__file__).resolve().parents[1]
    candidate = (
        root
        / "dagr_mcp"
        / "vendor"
        / "dagr_sdk_caller_auth_context"
        / "v0.1.vectors.json"
    )
    if candidate.exists():
        return candidate
    raise FileNotFoundError(
        "vendored dagr_sdk v0.1 caller_auth_context golden vectors not found "
        f"at {candidate}"
    )


def _load_golden_vectors() -> list[dict]:
    payload = json.loads(_dagr_sdk_vectors_path().read_text(encoding="utf-8"))
    assert payload["contract_schema_version"] == "dagr.caller_auth_context.v0.1"
    return payload["vectors"]


GOLDEN_VECTORS = _load_golden_vectors()


def test_golden_vectors_cover_all_three_states():
    states = {vector["construct"]["state"] for vector in GOLDEN_VECTORS}
    assert states == {"anonymous", "authenticated_user", "authenticated_machine"}


@pytest.mark.parametrize(
    "vector", GOLDEN_VECTORS, ids=[vector["name"] for vector in GOLDEN_VECTORS]
)
def test_golden_vector_survives_wire_to_dagr_mcp_policy_resolver(vector, tmp_path):
    construct = vector["construct"]
    expected_wire = vector["expected_wire"]

    # 1. wire vector -> canonical SDK contract (exactly as the SDK's own
    #    conformance tests construct it; scope_refs is a list on the wire,
    #    a frozenset on the contract).
    kwargs = dict(construct)
    if "scope_refs" in kwargs:
        kwargs["scope_refs"] = frozenset(kwargs["scope_refs"])
    auth = CallerAuthContext(**kwargs)

    # The contract's own wire projection must reproduce the committed vector
    # byte-for-byte (modulo list/set ordering, already normalized above).
    wire = auth.as_wire_dict()
    assert wire["state"] == expected_wire["state"]
    assert wire["principal_ref"] == expected_wire["principal_ref"]
    assert sorted(wire["scope_refs"]) == sorted(expected_wire["scope_refs"])

    # 2. CallerAuthContext -> DAGR-MCP-local adapter.
    principal = CallerPrincipal.from_auth_context(auth)
    assert principal.state == expected_wire["state"]
    assert principal.principal_ref == expected_wire["principal_ref"]
    assert sorted(principal.scopes) == sorted(expected_wire["scope_refs"])

    # 3. adapter -> real wrap_handler call, through the existing duck-typed
    #    caller_context surface and the real SRS admission/outcome path.
    identity, bridge = _srs_bridge(tmp_path)

    def inner(tool_name, arguments, context=None):
        return {"ok": True}

    wrapped = wrap_handler(
        inner,
        HarnessConfig("1", "module", "1", "profile", "policy"),
        HarnessSinks(event=InMemoryEventSink()),
        policies=[ToolPolicy("records.lookup", "read", "allow")],
        srs_bridge=bridge,
    )
    result = wrapped(
        "records.lookup",
        {"record_ref": "record:1"},
        principal.to_caller_context(session_ref=f"session:{vector['name']}"),
    )
    assert result.ok is True
    assert result.context.actor_ref == expected_wire["principal_ref"]

    paths = sorted(tmp_path.glob("urn_srs_receipt_*.json"))
    receipts = [json.loads(path.read_text()) for path in paths]
    admission = next(item for item in receipts if item["receipt_kind"] == "admission")
    outcome = next(item for item in receipts if item["receipt_kind"] == "outcome")
    assert outcome["admission_receipt_ref"] == admission["receipt_id"]
    if principal.is_authenticated:
        assert admission["actor_ref"] == expected_wire["principal_ref"]
    else:
        assert "actor_ref" not in admission

    # 4. adapter -> fixture operator policy resolver, proving the specimen
    #    reaches a policy decision without DAGR interpreting scopes itself.
    decision, reason = _operator_policy_function(principal, required_scope="read")
    if "read" in principal.scopes:
        assert decision == "admitted"
    else:
        assert decision == "refused"
        assert reason == "missing_scope:read"
