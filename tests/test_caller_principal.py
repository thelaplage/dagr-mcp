"""Tests for the pre-validated caller principal seam (DAGR-MCP-PRINCIPAL0).

Covers: the three distinguishable caller states, structural exclusion of raw
credentials from the principal type, lossless projection onto the existing
duck-typed ``caller_context`` surface already consumed by
``dagr_mcp.enforcement_harness.wrap_handler``, an operator policy resolver
reaching an authenticated principal and refusing on a missing scope (never a
hardcoded DAGR rule), that the principal never changes tool identity, and
that admission/outcome receipt linkage through the existing SRS ``actor_ref``
field is unchanged whether or not a principal is supplied.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

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


# --------------------------------------------------------------------------- #
# Three distinguishable caller states                                        #
# --------------------------------------------------------------------------- #


def test_three_caller_states_are_closed_and_distinguishable():
    assert CALLER_PRINCIPAL_STATES == (
        "anonymous",
        "authenticated_user",
        "authenticated_machine",
    )
    anon = CallerPrincipal(state="anonymous")
    user = CallerPrincipal(state="authenticated_user", principal_ref="user:1")
    machine = CallerPrincipal(
        state="authenticated_machine", principal_ref="svc:acct:1", scopes={"read"}
    )
    assert {anon.state, user.state, machine.state} == set(CALLER_PRINCIPAL_STATES)
    assert anon.is_authenticated is False
    assert user.is_authenticated is True
    assert machine.is_authenticated is True


def test_anonymous_principal_forbids_ref_and_scopes():
    with pytest.raises(CallerPrincipalError):
        CallerPrincipal(state="anonymous", principal_ref="user:1")
    with pytest.raises(CallerPrincipalError):
        CallerPrincipal(state="anonymous", scopes={"read"})


@pytest.mark.parametrize("state", ["authenticated_user", "authenticated_machine"])
def test_authenticated_principal_requires_nonempty_ref(state):
    with pytest.raises(CallerPrincipalError):
        CallerPrincipal(state=state, principal_ref=None)
    with pytest.raises(CallerPrincipalError):
        CallerPrincipal(state=state, principal_ref="   ")


def test_unrecognized_state_fails_closed():
    with pytest.raises(CallerPrincipalError):
        CallerPrincipal(state="superuser", principal_ref="user:1")


# --------------------------------------------------------------------------- #
# Raw credential structurally impossible to serialize through the type       #
# --------------------------------------------------------------------------- #


def test_principal_type_has_no_credential_field():
    field_names = {f.name for f in dataclasses.fields(CallerPrincipal)}
    assert field_names == {"state", "principal_ref", "scopes"}
    for forbidden in ("token", "bearer", "api_key", "password", "secret", "credential"):
        assert forbidden not in field_names


def test_principal_constructor_rejects_unknown_credential_kwargs():
    with pytest.raises(TypeError):
        CallerPrincipal(  # type: ignore[call-arg]
            state="authenticated_user",
            principal_ref="user:1",
            bearer_token="secret-value",
        )


@pytest.mark.parametrize(
    "raw",
    [
        "Bearer abc123.def456.ghi789",
        "bearer sometoken",
        "Basic dXNlcjpwYXNz",
        "Authorization: Bearer xyz",
    ],
)
def test_bearer_shaped_value_rejected_as_principal_ref(raw):
    with pytest.raises(CallerPrincipalError):
        CallerPrincipal(state="authenticated_user", principal_ref=raw)


def test_whitespace_in_principal_ref_rejected():
    with pytest.raises(CallerPrincipalError):
        CallerPrincipal(state="authenticated_user", principal_ref="user 1")


def test_projections_never_carry_more_than_ref_state_scopes():
    principal = CallerPrincipal(
        state="authenticated_machine", principal_ref="svc:acct:9", scopes={"read", "write"}
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

    principal = CallerPrincipal(state="authenticated_user", principal_ref="user:42")
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
    user = CallerPrincipal(state="authenticated_user", principal_ref="user:1")
    user_result = wrapped(
        "records.lookup", {"id": 1}, context=user.to_caller_context()
    )
    machine = CallerPrincipal(
        state="authenticated_machine", principal_ref="svc:1", scopes={"read"}
    )
    machine_result = wrapped(
        "records.lookup", {"id": 1}, context=machine.to_caller_context()
    )

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
    principal = CallerPrincipal(
        state="authenticated_user", principal_ref="user:7", scopes={"read"}
    )

    decision, reason = _operator_policy_function(principal, required_scope="write")
    assert decision == "refused"
    assert reason == "missing_scope:write"

    policy = resolve_operator_admission(
        tool_name="records.write", tool_class="write", decision=decision, reason=reason
    )
    assert policy.decision == "deny"
    assert policy.reason == "missing_scope:write"


def test_authenticated_principal_with_required_scope_is_admitted():
    principal = CallerPrincipal(
        state="authenticated_machine", principal_ref="svc:1", scopes={"read", "write"}
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

    principal = CallerPrincipal(
        state="authenticated_user", principal_ref="user:99", scopes={"read"}
    )
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
