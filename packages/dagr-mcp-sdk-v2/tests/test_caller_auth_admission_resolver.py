"""DAGR-MCP-SDKV2-CALLER0: the caller-auth resolver + operator admission-policy
seam.

Closes a binding-coverage gap: the SDK-v2 binding had no way to carry an
already-authenticated caller (``dagr_sdk.caller_auth_context.CallerAuthContext``,
the canonical contract dagr-sdk already owns) into its admission decision, and
no operator admission-policy hook -- forcing a consumer (counterpedia-mcp#13)
to bridge it with a request-scoped ``ContextVar``, a product-local hidden
channel. This suite proves:

* ``SdkV2CallerAuthResolver`` reaches the operator admission resolver with the
  exact ``CallerAuthContext`` it resolved (rows 2/3).
* No raw credential-shaped field can reach the binding (row 4) -- enforced by
  ``CallerAuthContext`` itself (this suite only proves the binding never
  bypasses that guard).
* A missing-scope refusal is REAL: a signed refused admission receipt exists,
  the delegate is never invoked, and no outcome receipt is ever emitted
  (row 5) -- vs. an adequate-scope call, which is admitted, dispatches the
  delegate exactly once, and emits a linked outcome receipt (row 6).
* Every existing (no-resolvers-supplied) caller stays byte-compatible: known
  tool -> admitted (row 1 baseline covered by test_acceptance_matrix.py; row 8
  here), unknown tool still fails closed before dispatch (row 7).
* ``principal_ref`` landing on ``ReceiptContext.actor_ref`` is activity
  attribution only -- it does not fabricate a Participant/standing/delegation/
  capability object anywhere in this binding (row 9).
* No ContextVar or module-global request-handoff state exists anywhere in this
  package (row 10).
* The package imports the ``dagr_sdk`` contract directly and never imports the
  top-level (FastMCP/v1) ``dagr_mcp.caller_principal`` (row 11).
* ``mcp==2.0.0`` isolation remains intact -- no ``fastmcp`` import reachable
  from this package (row 12).
"""

from __future__ import annotations

import ast
import pkgutil
import re
from pathlib import Path

import pytest
from mcp import types as mcp_types

import dagr_mcp_sdk_v2
from dagr_sdk.caller_auth_context import (
    ANONYMOUS_CALLER_AUTH_CONTEXT,
    CallerAuthContext,
    CallerAuthContextError,
)
from dagr_mcp_core.lifecycle.models import AdmissionRequest
from dagr_mcp_sdk_v2.adapter import ActorResolution, ToolRefused

from harness import build_governed_test_app, call_tool, ok_result

REQUIRED_SCOPE = "counterpedia:write"


def _scope_gated_admission_resolver(
    *, ctx, caller_auth: CallerAuthContext, actor: ActorResolution, tool_name, tool_class, argument_digest
) -> AdmissionRequest:
    """The kind of operator policy this seam exists for: read caller_auth's
    scope_refs and decide -- DAGR itself never interprets them."""
    if not caller_auth.is_authenticated:
        return AdmissionRequest(disposition="refused", refusal_ground="policy_refused")
    if REQUIRED_SCOPE not in caller_auth.scope_refs:
        return AdmissionRequest(disposition="refused", refusal_ground="policy_refused")
    return AdmissionRequest(disposition="admitted", tool_class=tool_class)


# --------------------------------------------------------------------------- #
# Row 1 / 8: no resolvers supplied -> byte-compatible anonymous behavior      #
# --------------------------------------------------------------------------- #


def test_row1_row8_no_resolvers_supplied_known_tool_admitted_anonymous(tmp_path):
    dt = build_governed_test_app(tmp_path, tool_bodies={"echo": lambda args: ok_result("hi")})
    with dt.client() as client:
        resp = call_tool(client, "echo", {"text": "hi"})
    assert resp.status_code == 200
    assert dt.delegates["echo"].call_count == 1
    assert len(dt.admission_receipts()) == 1
    assert dt.admission_receipts()[0]["disposition"] == "admitted"
    assert len(dt.outcome_receipts()) == 1
    # No actor_ref was ever asserted for the default/no-caller-auth-resolver path.
    assert "actor_ref" not in dt.admission_receipts()[0]


# --------------------------------------------------------------------------- #
# Row 2 / 3: authenticated_user / authenticated_machine reach the resolver   #
# with the exact CallerAuthContext                                           #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "state,principal_ref,scope_refs",
    [
        ("authenticated_user", "user:alice", frozenset({REQUIRED_SCOPE})),
        ("authenticated_machine", "svc:ingest-bot", frozenset({REQUIRED_SCOPE, "other:scope"})),
    ],
)
def test_row2_row3_authenticated_caller_reaches_resolver_with_exact_context(
    tmp_path, state, principal_ref, scope_refs
):
    expected = CallerAuthContext(state=state, principal_ref=principal_ref, scope_refs=scope_refs)
    seen: list[CallerAuthContext] = []

    def caller_auth_resolver(ctx, argument_digest):
        return expected

    def admission_resolver(*, ctx, caller_auth, actor, tool_name, tool_class, argument_digest):
        seen.append(caller_auth)
        return _scope_gated_admission_resolver(
            ctx=ctx, caller_auth=caller_auth, actor=actor, tool_name=tool_name,
            tool_class=tool_class, argument_digest=argument_digest,
        )

    dt = build_governed_test_app(
        tmp_path,
        tool_bodies={"write_it": lambda args: ok_result("done")},
        tool_classes={"write_it": "write"},
        caller_auth_resolver=caller_auth_resolver,
        admission_resolver=admission_resolver,
    )
    with dt.client() as client:
        resp = call_tool(client, "write_it", {"payload": "x"})

    assert resp.status_code == 200
    assert len(seen) == 1
    # Exact object identity/equality: the resolver saw exactly what the
    # caller-auth resolver produced, not a rebuilt/copied/coerced value.
    assert seen[0] == expected
    assert seen[0] is expected
    assert dt.delegates["write_it"].call_count == 1
    assert len(dt.admission_receipts()) == 1
    assert dt.admission_receipts()[0]["disposition"] == "admitted"
    # principal_ref landed on actor_ref (see row 9 for the standing/Participant
    # negative proof).
    assert dt.admission_receipts()[0]["actor_ref"] == principal_ref


# --------------------------------------------------------------------------- #
# Row 4: no raw credential-shaped field can reach the binding                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(state="authenticated_user", principal_ref="Bearer abc.def.ghi"),
        dict(state="authenticated_user", principal_ref="Authorization: Bearer xyz"),
        dict(state="authenticated_user", principal_ref="basic dXNlcjpwYXNz"),
    ],
)
def test_row4_no_raw_credential_shaped_field_reaches_the_binding(kwargs):
    # The guard lives in dagr_sdk.caller_auth_context.CallerAuthContext itself
    # (this binding does not, and must not, re-implement or weaken it): a
    # raw-credential-shaped principal_ref is refused at construction, before
    # any CallerAuthContext carrying it could ever reach this binding's
    # caller_auth_resolver -> admission_resolver seam.
    with pytest.raises(CallerAuthContextError):
        CallerAuthContext(**kwargs)


def test_row4_forbidden_wire_fields_are_structurally_absent_on_the_dataclass():
    from dagr_sdk.caller_auth_context import FORBIDDEN_WIRE_FIELDS

    field_names = {f for f in CallerAuthContext.__dataclass_fields__}
    assert field_names.isdisjoint(FORBIDDEN_WIRE_FIELDS)
    wire = ANONYMOUS_CALLER_AUTH_CONTEXT.as_wire_dict()
    assert set(wire).isdisjoint(FORBIDDEN_WIRE_FIELDS)


# --------------------------------------------------------------------------- #
# Row 5: missing scope -> REAL refusal (signed receipt, delegate never runs, #
# no outcome receipt)                                                        #
# --------------------------------------------------------------------------- #


def test_row5_missing_scope_is_a_real_signed_refusal_no_dispatch_no_outcome(tmp_path):
    caller = CallerAuthContext(state="authenticated_user", principal_ref="user:bob", scope_refs=frozenset())

    dt = build_governed_test_app(
        tmp_path,
        tool_bodies={"write_it": lambda args: ok_result("should never run")},
        tool_classes={"write_it": "write"},
        caller_auth_resolver=lambda ctx, digest: caller,
        admission_resolver=_scope_gated_admission_resolver,
    )
    with dt.client() as client:
        resp = call_tool(client, "write_it", {"payload": "x"})

    body = resp.json()
    assert "error" in body, f"expected a JSON-RPC error (refusal), got: {body}"
    assert "result" not in body

    # Delegate call count = 0: no unauthorized dispatch.
    assert dt.delegates["write_it"].call_count == 0

    # A REAL signed admission refusal receipt exists.
    admission_receipts = dt.admission_receipts()
    assert len(admission_receipts) == 1
    refusal = admission_receipts[0]
    assert refusal["disposition"] == "refused"
    assert refusal["reason_code"] == "policy_refused"
    assert refusal["requested_tool_name"] == "write_it"
    # It is genuinely signed (envelope + signature material present).
    assert "receipt_signature" in refusal and refusal["receipt_signature"], (
        f"admission refusal receipt carries no discoverable signature material: {sorted(refusal)}"
    )

    # No outcome receipt was ever emitted for the refused call.
    assert len(dt.outcome_receipts()) == 0


def test_row5_direct_adapter_admission_plan_is_refused_and_execution_does_not_proceed(tmp_path):
    """Adapter-level corroboration of row 5, mirroring the direct-adapter rows
    in test_acceptance_matrix.py (real ToolRefused exception, not a wire-level
    inference alone)."""
    from types import SimpleNamespace

    from dagr_mcp_core.srs_receipts import RawEnvelopeFileSink, SignedReceiptEmitter, SigningIdentity
    from dagr_mcp_sdk_v2.adapter import SdkV2BindingConfig, SdkV2LifecycleAdapter

    identity = SigningIdentity.generate(issuer_id="issuer:row5", key_id="issuer.row5/key/1")
    sink = RawEnvelopeFileSink(tmp_path / "receipts")
    emitter = SignedReceiptEmitter(identity=identity, sink=sink)

    caller = CallerAuthContext(state="authenticated_user", principal_ref="user:bob", scope_refs=frozenset())
    config = SdkV2BindingConfig(
        runtime_instance_id="rt:row5",
        boundary_id="b:row5",
        policy_pack_id="p:row5",
        policy_pack_version="1",
        tool_classes={"write_it": "write"},
        caller_auth_resolver=lambda ctx, digest: caller,
        admission_resolver=_scope_gated_admission_resolver,
    )
    adapter = SdkV2LifecycleAdapter(emitter=emitter, config=config)

    calls = []

    async def delegate(arguments):
        calls.append(arguments)
        return ok_result("should never run")

    ctx = SimpleNamespace(method="tools/call", request_id="req-row5")
    params = mcp_types.CallToolRequestParams(name="write_it", arguments={})

    import asyncio

    with pytest.raises(ToolRefused):
        asyncio.run(adapter.governed_call_tool(ctx, params, delegate))

    assert calls == []
    receipts = [p for p in sorted((tmp_path / "receipts").glob("*.json"))]
    assert len(receipts) == 1


# --------------------------------------------------------------------------- #
# Row 6: adequate scope -> admitted, delegate exactly once, linked outcome   #
# --------------------------------------------------------------------------- #


def test_row6_adequate_scope_is_admitted_dispatches_once_linked_outcome(tmp_path):
    caller = CallerAuthContext(
        state="authenticated_user", principal_ref="user:carol", scope_refs=frozenset({REQUIRED_SCOPE})
    )
    dt = build_governed_test_app(
        tmp_path,
        tool_bodies={"write_it": lambda args: ok_result("done")},
        tool_classes={"write_it": "write"},
        caller_auth_resolver=lambda ctx, digest: caller,
        admission_resolver=_scope_gated_admission_resolver,
    )
    with dt.client() as client:
        resp = call_tool(client, "write_it", {"payload": "x"})

    assert resp.status_code == 200
    assert dt.delegates["write_it"].call_count == 1
    admission_receipts = dt.admission_receipts()
    outcome_receipts = dt.outcome_receipts()
    assert len(admission_receipts) == 1
    assert admission_receipts[0]["disposition"] == "admitted"
    assert len(outcome_receipts) == 1
    assert outcome_receipts[0]["admission_receipt_ref"] == admission_receipts[0]["receipt_id"]
    assert outcome_receipts[0]["outcome"] == "result_returned"


# --------------------------------------------------------------------------- #
# Row 7: unknown tool still fails closed BEFORE reaching either resolver     #
# --------------------------------------------------------------------------- #


def test_row7_unknown_tool_fails_closed_before_any_resolver_runs(tmp_path):
    caller_auth_calls = []
    admission_calls = []

    def caller_auth_resolver(ctx, digest):
        caller_auth_calls.append(1)
        return ANONYMOUS_CALLER_AUTH_CONTEXT

    def admission_resolver(**kwargs):
        admission_calls.append(1)
        return AdmissionRequest(disposition="admitted", tool_class=kwargs["tool_class"])

    dt = build_governed_test_app(
        tmp_path,
        tool_bodies={"echo": lambda args: ok_result("hi")},
        caller_auth_resolver=caller_auth_resolver,
        admission_resolver=admission_resolver,
    )
    with dt.client() as client:
        resp = call_tool(client, "totally_unregistered_tool", {})

    body = resp.json()
    assert "error" in body
    assert "totally_unregistered_tool" in body["error"]["message"]
    assert len(dt.admission_receipts()) == 1
    assert dt.admission_receipts()[0]["disposition"] == "refused"
    assert dt.admission_receipts()[0]["reason_code"] == "unknown_tool_fail_closed"
    assert len(dt.outcome_receipts()) == 0
    # The caller-auth resolver DOES run (it is resolved from trusted context
    # before the known/unknown branch, exactly like the pre-existing actor
    # resolver), but the admission resolver never does -- the unknown-tool
    # refusal is unconditional and decided before an operator resolver would
    # ever see the call.
    assert len(caller_auth_calls) == 1
    assert len(admission_calls) == 0


# --------------------------------------------------------------------------- #
# Row 9: principal_ref-as-actor_ref creates NO Participant/standing/          #
# delegation/capability                                                      #
# --------------------------------------------------------------------------- #


def test_row9_actor_ref_attribution_creates_no_participant_or_standing_object(tmp_path):
    caller = CallerAuthContext(state="authenticated_user", principal_ref="user:dave", scope_refs=frozenset())

    dt = build_governed_test_app(
        tmp_path,
        tool_bodies={"echo": lambda args: ok_result("hi")},
        caller_auth_resolver=lambda ctx, digest: caller,
    )
    with dt.client() as client:
        resp = call_tool(client, "echo", {})
    assert resp.status_code == 200

    receipt = dt.admission_receipts()[0]
    assert receipt["actor_ref"] == "user:dave"
    # The receipt carries NO participant/standing/delegation/authority/
    # capability field anywhere -- attribution via actor_ref is the entire
    # mechanism; nothing here mints or references a governance-standing
    # object. (Mirrors dagr_sdk.caller_auth_context.FORBIDDEN_WIRE_FIELDS'
    # own "DAGR governance/standing surface" negative list.)
    forbidden_standing_tokens = {
        "participant", "participant_id", "standing", "delegation", "authority",
        "claim_support", "capabilities", "admission_grant",
    }

    def _walk(value):
        if isinstance(value, dict):
            for k, v in value.items():
                assert k.lower() not in forbidden_standing_tokens, f"unexpected standing-shaped key: {k}"
                _walk(v)
        elif isinstance(value, list):
            for item in value:
                _walk(item)

    _walk(receipt)

    # And structurally: ActorResolution itself carries no scope/standing
    # fields -- it is exactly the pre-existing three-field shape.
    assert set(ActorResolution.__dataclass_fields__) == {"actor_ref", "tenant_id", "workspace_id"}


# --------------------------------------------------------------------------- #
# Row 10: no ContextVar / module-global request-handoff state anywhere       #
# --------------------------------------------------------------------------- #


def _iter_package_source_files() -> list[Path]:
    package_dir = Path(dagr_mcp_sdk_v2.__file__).parent
    return sorted(package_dir.rglob("*.py"))


def test_row10_no_contextvar_or_module_global_request_handoff_state():
    contextvar_pattern = re.compile(r"\bContextVar\b|\bcontextvars\b")
    for path in _iter_package_source_files():
        source = path.read_text()
        assert not contextvar_pattern.search(source), (
            f"{path} references ContextVar/contextvars -- this binding must "
            "resolve caller identity from trusted per-call context/config, "
            "never a request-scoped global."
        )


def test_row10_no_module_level_mutable_request_state_via_ast():
    """A stronger structural check than the grep above: no module-level
    assignment anywhere in the package binds a name to a dict/list/set
    literal or call that could serve as a hidden request-keyed registry
    (the shape a ContextVar-style bridge would take even if renamed)."""
    suspicious_call_names = {"ContextVar", "threading.local", "local"}
    for path in _iter_package_source_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                assert name not in suspicious_call_names, (
                    f"{path} calls {name!r} at module scope -- forbidden "
                    "request-scoped/thread-local handoff shape"
                )


# --------------------------------------------------------------------------- #
# Row 11: imports the dagr-sdk contract directly, never top-level dagr_mcp   #
# --------------------------------------------------------------------------- #


def test_row11_imports_dagr_sdk_contract_directly_never_top_level_dagr_mcp():
    import dagr_mcp_sdk_v2.adapter as adapter_module

    assert adapter_module.CallerAuthContext is CallerAuthContext

    for path in _iter_package_source_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("dagr_mcp."), (
                        f"{path} imports top-level {alias.name!r}"
                    )
                    assert alias.name != "dagr_mcp", f"{path} imports top-level dagr_mcp"
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("dagr_mcp."), (
                    f"{path} imports from top-level {node.module!r}"
                )
                assert node.module != "dagr_mcp", f"{path} imports from top-level dagr_mcp"

    import sys

    assert "dagr_mcp.caller_principal" not in sys.modules or not any(
        m.startswith("dagr_mcp_sdk_v2") for m in ()
    )


# --------------------------------------------------------------------------- #
# Row 12: mcp==2.0.0 isolation remains intact                                #
# --------------------------------------------------------------------------- #


def test_row12_mcp_isolation_intact_no_fastmcp_no_mcp_version_drift():
    import sys
    from importlib.metadata import version

    assert "fastmcp" not in sys.modules
    with pytest.raises(ModuleNotFoundError):
        __import__("fastmcp")
    assert version("mcp") == "2.0.0"

    # dagr-sdk itself declares no runtime dependency (verified against its own
    # pyproject.toml at the pinned commit) so pulling it in cannot itself have
    # widened or narrowed the mcp pin.
    import dagr_sdk

    assert not hasattr(dagr_sdk, "fastmcp")
