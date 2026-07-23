"""Sprint A10 — admission/outcome receipt composition (``dagr_mcp_service.access``).

Proves ``compose_receipts``/``access_governed_call_receipts`` build an
ordered (admission, outcome) composition from a real ``GovernedCallResponse``
end to end, that refusal/deferral shapes (admission-only) compose correctly,
and that every cross-envelope association check — call, actor, tenant,
boundary, runtime, and parent/custody — fails closed on a mismatch rather
than silently composing receipts from different governed calls. See
``docs/GATEWAY_SERVICE_ADAPTER_SCOPE.md`` §9, work package A10.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastmcp")
pytest.importorskip("mcp")

from dagr_mcp.srs_receipts import (
    RawEnvelopeFileSink,
    ReceiptContext,
    SignedReceiptEmitter,
    SigningIdentity,
    sha256_digest,
)
from dagr_mcp_service.access import (
    FilesystemReceiptSource,
    ReceiptAccessConfig,
    ReceiptAccessContext,
    access_governed_call_receipts,
    compose_receipts,
)
from dagr_mcp_service.adapter import GatewayAdapterConfig, execute_governed_call
from dagr_mcp_service.connectors.memory import InMemoryToolConnector
from dagr_mcp_service.contract import (
    CallerGovernedCallRequest,
    GovernedCallRequest,
    ReceiptHandle,
    TargetServerRef,
    TrustedActorRef,
    TrustedTenantRef,
)
from dagr_mcp_service.resolution import FASTMCP_BINDING_VERSION, BindingSelectorKey

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _identity(key_id: str = "issuer.test.composition/key/1") -> SigningIdentity:
    return SigningIdentity.generate(issuer_id="issuer:test:composition", key_id=key_id)


def _context(**overrides: Any) -> ReceiptContext:
    base: dict[str, Any] = dict(
        runtime_instance_id="runtime:test:composition",
        boundary_id="boundary:test:composition",
        policy_pack_id="policy:test:composition",
        policy_pack_version="2026.07.23",
        subject_ref="tool-call:call:test",
        logical_call_id="call:test",
        binding_version="fastmcp.middleware.v0.1",
    )
    base.update(overrides)
    return ReceiptContext(**base)


def _emit_admission(sink: Any, identity: SigningIdentity, *, context: ReceiptContext | None = None, **kwargs: Any) -> str:
    emitter = SignedReceiptEmitter(identity=identity, sink=sink)
    kwargs.setdefault("disposition", "admitted")
    kwargs.setdefault("requested_tool_name", "echo")
    kwargs.setdefault("argument_digest", sha256_digest({"x": 1}))
    return emitter.emit_admission(context=context or _context(), **kwargs)


def _emit_outcome(
    sink: Any,
    identity: SigningIdentity,
    *,
    admission_receipt_ref: str,
    context: ReceiptContext | None = None,
    outcome: str = "result_returned",
    **kwargs: Any,
) -> str:
    emitter = SignedReceiptEmitter(identity=identity, sink=sink)
    if outcome in ("result_returned", "error_returned") and "result_digest" not in kwargs:
        kwargs["result_digest"] = sha256_digest({"ok": True})
    return emitter.emit_outcome(
        context=context or _context(), admission_receipt_ref=admission_receipt_ref, outcome=outcome, **kwargs
    )


def _access_config(directory: Path, identity: SigningIdentity, **overrides: Any) -> ReceiptAccessConfig:
    return ReceiptAccessConfig(
        provider=FilesystemReceiptSource(root=directory), trust_bundle=identity.trust_bundle(), **overrides
    )


def _digest(arguments: dict[str, Any]) -> str:
    return sha256_digest(dict(arguments))


def _caller_request(
    *,
    selector: str = "primary",
    target: str = "mem:fixture",
    tool: str = "echo",
    arguments: dict[str, Any],
    policy_profile_ref: str = "policy-profile:default",
    request_ref: str = "req:1",
    parent_receipt_ref: str | None = None,
) -> CallerGovernedCallRequest:
    return CallerGovernedCallRequest(
        request_ref=request_ref,
        binding_selector=BindingSelectorKey(key=selector),
        target_server_ref=TargetServerRef(handle=target),
        tool_name=tool,
        argument_digest=_digest(arguments),
        policy_profile_ref=policy_profile_ref,
        parent_receipt_ref=parent_receipt_ref,
    )


def _resolved_request(
    *, actor_ref: str = "actor:test:known", tenant_ref: str | None = None, **kwargs: Any
) -> GovernedCallRequest:
    caller = _caller_request(**kwargs)
    return GovernedCallRequest.from_caller_request(
        caller,
        actor_ref=TrustedActorRef(ref=actor_ref),
        tenant_ref=TrustedTenantRef(ref=tenant_ref) if tenant_ref is not None else None,
    )


def _build_adapter_config(tmp_path: Path, *, connector: Any, selector: str = "primary") -> tuple[GatewayAdapterConfig, SigningIdentity, Path]:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    config = GatewayAdapterConfig(
        binding_registry={selector: FASTMCP_BINDING_VERSION},
        connector=connector,
        identity=identity,
        sink=sink,
        runtime_instance_id="runtime:test:gateway",
        boundary_id="boundary:test:gateway",
        policy_pack_id="policy:test:gateway",
        policy_pack_version="2026.07.23",
    )
    return config, identity, directory


async def _echo(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"echoed": True}


# --------------------------------------------------------------------------- #
# 4 — admission + outcome compose in verified order                          #
# --------------------------------------------------------------------------- #


async def test_admission_and_outcome_compose_in_verified_order(tmp_path: Path) -> None:
    connector = InMemoryToolConnector({"mem:fixture": {"echo": _echo}})
    config, identity, directory = _build_adapter_config(tmp_path, connector=connector)
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)
    assert len(response.receipts) == 2

    access_config = _access_config(directory, identity)
    composition = access_governed_call_receipts(response, config=access_config)

    assert composition.diagnostic_code is None
    assert composition.admission is not None
    assert composition.outcome is not None
    assert composition.admission.envelope["receipt_kind"] == "admission"
    assert composition.outcome.envelope["receipt_kind"] == "outcome"
    assert composition.outcome.envelope["admission_receipt_ref"] == composition.admission.envelope["receipt_id"]


async def test_composition_is_order_independent_of_input_list_position(tmp_path: Path) -> None:
    connector = InMemoryToolConnector({"mem:fixture": {"echo": _echo}})
    config, identity, directory = _build_adapter_config(tmp_path, connector=connector)
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)
    reversed_handles = tuple(reversed(response.receipts))
    assert reversed_handles[0].receipt_kind == "outcome"

    access_config = _access_config(directory, identity)
    composition = compose_receipts(
        reversed_handles, config=access_config, expected_logical_call_id=response.logical_call_id
    )

    assert composition.diagnostic_code is None
    assert composition.admission.envelope["receipt_kind"] == "admission"
    assert composition.outcome.envelope["receipt_kind"] == "outcome"


# --------------------------------------------------------------------------- #
# 5 — refusal and deferral receipt shapes compose correctly (admission-only) #
# --------------------------------------------------------------------------- #


async def test_refusal_composes_with_only_an_admission_receipt(tmp_path: Path) -> None:
    connector = InMemoryToolConnector({"mem:fixture": {"echo": _echo}})
    config, identity, directory = _build_adapter_config(tmp_path, connector=connector)

    def _refusing_policy_resolver(_snapshot: Any, _actor: Any) -> Any:
        from dagr_mcp.fastmcp_binding import BindingPolicy

        return BindingPolicy(disposition="refused", tool_class="read", reason_code="policy_refused")

    import dataclasses

    config = dataclasses.replace(config, policy_resolver=_refusing_policy_resolver)
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)
    assert response.decision.disposition == "refused"
    assert len(response.receipts) == 1

    access_config = _access_config(directory, identity)
    composition = access_governed_call_receipts(response, config=access_config)

    assert composition.diagnostic_code is None
    assert composition.admission is not None
    assert composition.admission.envelope["disposition"] == "refused"
    assert composition.outcome is None


async def test_deferral_composes_with_only_an_admission_receipt(tmp_path: Path) -> None:
    connector = InMemoryToolConnector({"mem:fixture": {"echo": _echo}})
    config, identity, directory = _build_adapter_config(tmp_path, connector=connector)

    def _deferring_policy_resolver(_snapshot: Any, _actor: Any) -> Any:
        from dagr_mcp.fastmcp_binding import BindingPolicy

        return BindingPolicy(disposition="deferred_for_review", tool_class="read")

    def _review_object_creator(_snapshot: Any, _actor: Any, _policy: Any) -> str:
        return "review:test:1"

    import dataclasses

    config = dataclasses.replace(
        config, policy_resolver=_deferring_policy_resolver, review_object_creator=_review_object_creator
    )
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)
    assert response.decision.disposition == "deferred"
    assert len(response.receipts) == 1

    access_config = _access_config(directory, identity)
    composition = access_governed_call_receipts(response, config=access_config)

    assert composition.diagnostic_code is None
    assert composition.admission is not None
    assert composition.admission.envelope["disposition"] == "deferred_for_review"
    assert composition.outcome is None


# --------------------------------------------------------------------------- #
# ambiguous handle lists fail closed                                         #
# --------------------------------------------------------------------------- #


def test_more_than_one_handle_of_the_same_kind_fails_closed(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    first = _emit_admission(sink, identity)
    second = _emit_admission(sink, identity)

    handles = (
        ReceiptHandle(receipt_id=first, receipt_kind="admission"),
        ReceiptHandle(receipt_id=second, receipt_kind="admission"),
    )
    composition = compose_receipts(
        handles, config=_access_config(directory, identity), expected_logical_call_id="call:test"
    )

    assert composition.diagnostic_code == "family_mismatch"
    assert composition.admission is None
    assert composition.outcome is None


def test_outcome_handle_without_its_admission_handle_fails_closed(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    admission_id = _emit_admission(sink, identity)
    outcome_id = _emit_outcome(sink, identity, admission_receipt_ref=admission_id)

    # Only the outcome handle is offered -- its own admission_receipt_ref is
    # never independently verified because no admission handle accompanies
    # it, so this must fail closed rather than compose a lone outcome.
    handles = (ReceiptHandle(receipt_id=outcome_id, receipt_kind="outcome"),)
    composition = compose_receipts(
        handles, config=_access_config(directory, identity), expected_logical_call_id="call:test"
    )

    assert composition.diagnostic_code == "association_mismatch"
    assert composition.admission is None
    assert composition.outcome is None


# --------------------------------------------------------------------------- #
# 19 — mismatched admission and outcome receipts cannot compose              #
# --------------------------------------------------------------------------- #


def test_outcome_referencing_a_different_admission_cannot_compose(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()

    admission_a = _emit_admission(sink, identity, requested_tool_name="tool-a")
    admission_b = _emit_admission(sink, identity, requested_tool_name="tool-b")
    outcome_for_b = _emit_outcome(sink, identity, admission_receipt_ref=admission_b)

    handles = (
        ReceiptHandle(receipt_id=admission_a, receipt_kind="admission"),
        ReceiptHandle(receipt_id=outcome_for_b, receipt_kind="outcome"),
    )
    composition = compose_receipts(
        handles, config=_access_config(directory, identity), expected_logical_call_id="call:test"
    )

    assert composition.diagnostic_code == "association_mismatch"


# --------------------------------------------------------------------------- #
# call/logical_call_id mismatch                                              #
# --------------------------------------------------------------------------- #


def test_logical_call_id_mismatch_against_expectation_fails_closed(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    admission_id = _emit_admission(sink, identity, context=_context(logical_call_id="call:real"))

    handle = ReceiptHandle(receipt_id=admission_id, receipt_kind="admission")
    composition = compose_receipts(
        (handle,), config=_access_config(directory, identity), expected_logical_call_id="call:different"
    )

    assert composition.diagnostic_code == "association_mismatch"


# --------------------------------------------------------------------------- #
# 20/21 — actor/tenant mismatch between admission and outcome                #
# --------------------------------------------------------------------------- #


def test_actor_mismatch_between_admission_and_outcome_fails_closed(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()

    admission_id = _emit_admission(sink, identity, context=_context(actor_ref="actor:one"))
    outcome_id = _emit_outcome(
        sink, identity, admission_receipt_ref=admission_id, context=_context(actor_ref="actor:two")
    )

    handles = (
        ReceiptHandle(receipt_id=admission_id, receipt_kind="admission"),
        ReceiptHandle(receipt_id=outcome_id, receipt_kind="outcome"),
    )
    composition = compose_receipts(
        handles, config=_access_config(directory, identity), expected_logical_call_id="call:test"
    )

    assert composition.diagnostic_code == "association_mismatch"


def test_tenant_mismatch_between_admission_and_outcome_fails_closed(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()

    admission_id = _emit_admission(
        sink, identity, context=_context(actor_ref="actor:one", tenant_id="tenant:one")
    )
    outcome_id = _emit_outcome(
        sink,
        identity,
        admission_receipt_ref=admission_id,
        context=_context(actor_ref="actor:one", tenant_id="tenant:two"),
    )

    handles = (
        ReceiptHandle(receipt_id=admission_id, receipt_kind="admission"),
        ReceiptHandle(receipt_id=outcome_id, receipt_kind="outcome"),
    )
    composition = compose_receipts(
        handles, config=_access_config(directory, identity), expected_logical_call_id="call:test"
    )

    assert composition.diagnostic_code == "association_mismatch"


# --------------------------------------------------------------------------- #
# 22 — boundary/runtime mismatch between admission and outcome               #
# --------------------------------------------------------------------------- #


def test_boundary_mismatch_between_admission_and_outcome_fails_closed(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()

    admission_id = _emit_admission(sink, identity, context=_context(boundary_id="boundary:one"))
    outcome_id = _emit_outcome(
        sink, identity, admission_receipt_ref=admission_id, context=_context(boundary_id="boundary:two")
    )

    handles = (
        ReceiptHandle(receipt_id=admission_id, receipt_kind="admission"),
        ReceiptHandle(receipt_id=outcome_id, receipt_kind="outcome"),
    )
    composition = compose_receipts(
        handles, config=_access_config(directory, identity), expected_logical_call_id="call:test"
    )

    assert composition.diagnostic_code == "association_mismatch"


def test_runtime_mismatch_between_admission_and_outcome_fails_closed(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()

    admission_id = _emit_admission(sink, identity, context=_context(runtime_instance_id="runtime:one"))
    outcome_id = _emit_outcome(
        sink,
        identity,
        admission_receipt_ref=admission_id,
        context=_context(runtime_instance_id="runtime:two"),
    )

    handles = (
        ReceiptHandle(receipt_id=admission_id, receipt_kind="admission"),
        ReceiptHandle(receipt_id=outcome_id, receipt_kind="outcome"),
    )
    composition = compose_receipts(
        handles, config=_access_config(directory, identity), expected_logical_call_id="call:test"
    )

    assert composition.diagnostic_code == "association_mismatch"


# --------------------------------------------------------------------------- #
# 23 — parent/custody mismatch                                                #
# --------------------------------------------------------------------------- #


def test_parent_receipt_ref_mismatch_against_expectation_fails_closed(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    admission_id = _emit_admission(sink, identity, context=_context(parent_receipt_ref="urn:srs:receipt:admission:parent-real"))

    handle = ReceiptHandle(receipt_id=admission_id, receipt_kind="admission")
    composition = compose_receipts(
        (handle,),
        config=_access_config(directory, identity),
        expected_logical_call_id="call:test",
        expected_parent_receipt_ref="urn:srs:receipt:admission:parent-different",
    )

    assert composition.diagnostic_code == "association_mismatch"


def test_access_governed_call_receipts_checks_parent_receipt_ref_from_the_response(tmp_path: Path) -> None:
    from dagr_mcp_service.contract import GovernedCallResponse, GovernedDecision

    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()

    real_parent = _emit_admission(sink, identity, requested_tool_name="parent-tool")
    admission_id = _emit_admission(
        sink, identity, context=_context(parent_receipt_ref=real_parent)
    )

    # GovernedCallResponse.parent_receipt_ref is not populated by A8's current
    # adapter (always None in every response class it produces today); build
    # one directly to prove access_governed_call_receipts' own pass-through
    # of this field, for a caller/deployment that does populate it.
    response = GovernedCallResponse(
        request_ref="req:1",
        logical_call_id="call:test",
        decision=GovernedDecision(disposition="admitted"),
        receipts=(ReceiptHandle(receipt_id=admission_id, receipt_kind="admission"),),
        parent_receipt_ref=real_parent,
    )

    access_config = _access_config(directory, identity)
    matching = access_governed_call_receipts(response, config=access_config)
    assert matching.diagnostic_code is None
    assert matching.admission.envelope["parent_receipt_ref"] == real_parent

    mismatched_response = GovernedCallResponse(
        request_ref="req:1",
        logical_call_id="call:test",
        decision=GovernedDecision(disposition="admitted"),
        receipts=(ReceiptHandle(receipt_id=admission_id, receipt_kind="admission"),),
        parent_receipt_ref="urn:srs:receipt:admission:not-the-real-parent",
    )
    mismatched = access_governed_call_receipts(mismatched_response, config=access_config)
    assert mismatched.diagnostic_code == "association_mismatch"


# --------------------------------------------------------------------------- #
# context-level actor/tenant association mismatch propagates from resolve    #
# --------------------------------------------------------------------------- #


def test_context_actor_mismatch_propagates_as_the_composition_diagnostic(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    admission_id = _emit_admission(sink, identity, context=_context(actor_ref="actor:owner"))

    handle = ReceiptHandle(receipt_id=admission_id, receipt_kind="admission")
    composition = compose_receipts(
        (handle,),
        config=_access_config(directory, identity),
        expected_logical_call_id="call:test",
        context=ReceiptAccessContext(actor_ref="actor:intruder"),
    )

    assert composition.diagnostic_code == "association_mismatch"


# --------------------------------------------------------------------------- #
# 31 — concurrent compositions do not cross handles or envelopes             #
# --------------------------------------------------------------------------- #


def test_concurrent_compositions_do_not_cross_handles_or_envelopes(tmp_path: Path) -> None:
    import concurrent.futures

    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    access_config = _access_config(directory, identity)

    pairs = []
    for i in range(6):
        admission_id = _emit_admission(
            sink, identity, requested_tool_name=f"tool-{i}", context=_context(logical_call_id=f"call:{i}")
        )
        outcome_id = _emit_outcome(
            sink, identity, admission_receipt_ref=admission_id, context=_context(logical_call_id=f"call:{i}")
        )
        pairs.append((admission_id, outcome_id))

    def _compose(index: int) -> Any:
        admission_id, outcome_id = pairs[index]
        handles = (
            ReceiptHandle(receipt_id=admission_id, receipt_kind="admission"),
            ReceiptHandle(receipt_id=outcome_id, receipt_kind="outcome"),
        )
        return index, compose_receipts(
            handles, config=access_config, expected_logical_call_id=f"call:{index}"
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_compose, range(6)))

    for index, composition in results:
        assert composition.diagnostic_code is None
        assert composition.admission.envelope["requested_tool_name"] == f"tool-{index}"
        assert composition.admission.envelope["logical_call_id"] == f"call:{index}"
        assert composition.outcome.envelope["logical_call_id"] == f"call:{index}"


# --------------------------------------------------------------------------- #
# empty composition (no handles) never fabricates content                    #
# --------------------------------------------------------------------------- #


def test_empty_handle_list_composes_to_nothing_without_error(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    directory.mkdir()
    identity = _identity()

    composition = compose_receipts(
        (), config=_access_config(directory, identity), expected_logical_call_id="call:test"
    )

    assert composition.diagnostic_code is None
    assert composition.admission is None
    assert composition.outcome is None
