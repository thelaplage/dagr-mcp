"""Sprint A8 — the in-process ``execute_governed_call`` adapter.

Proves the first executable Gateway composition seam: both existing lifecycle
bindings (``fastmcp.middleware.v0.1``, ``official-mcp-sdk.python.v0.1``) are
driven in-process, unchanged, through their own real execution seams, with no
network transport, no caller-authority smuggling, and no idempotency surface.
See ``docs/GATEWAY_SERVICE_ADAPTER_SCOPE.md`` §3/§4/§6/§8/§9/§10, work
package A8.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("fastmcp")
pytest.importorskip("mcp")

from dagr_mcp.sdk_spine import InMemoryReviewObjectSink
from dagr_mcp.srs_receipts import (
    RawEnvelopeFileSink,
    ReceiptWriteError,
    SignedReceiptEmitter,
    SigningIdentity,
    sha256_digest,
)
from dagr_mcp_lifecycle.contract import NEUTRAL_REFUSAL_GROUNDS
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
from dagr_mcp_service.resolution import (
    FASTMCP_BINDING_VERSION,
    SDK_BINDING_VERSION,
    BindingSelectorKey,
)

ROOT = Path(__file__).resolve().parents[1]
BOTH_BINDINGS = (FASTMCP_BINDING_VERSION, SDK_BINDING_VERSION)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def read_receipts(directory: Path) -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("urn_srs_receipt_*.json"))
    ]


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
    session_ref: str | None = None,
) -> CallerGovernedCallRequest:
    return CallerGovernedCallRequest(
        request_ref=request_ref,
        binding_selector=BindingSelectorKey(key=selector),
        target_server_ref=TargetServerRef(handle=target),
        tool_name=tool,
        argument_digest=_digest(arguments),
        policy_profile_ref=policy_profile_ref,
        parent_receipt_ref=parent_receipt_ref,
        session_ref=session_ref,
    )


def _resolved_request(
    *,
    actor_ref: str = "actor:test:known",
    tenant_ref: str | None = None,
    **kwargs: Any,
) -> GovernedCallRequest:
    caller = _caller_request(**kwargs)
    return GovernedCallRequest.from_caller_request(
        caller,
        actor_ref=TrustedActorRef(ref=actor_ref),
        tenant_ref=TrustedTenantRef(ref=tenant_ref) if tenant_ref is not None else None,
    )


def _build_config(
    tmp_path: Path,
    *,
    connector: Any,
    selector: str = "primary",
    binding_version: str = FASTMCP_BINDING_VERSION,
    sink: Any | None = None,
    **overrides: Any,
) -> tuple[GatewayAdapterConfig, SigningIdentity, Path]:
    directory = tmp_path / "receipts"
    sink = sink if sink is not None else RawEnvelopeFileSink(directory)
    identity = SigningIdentity.generate(
        issuer_id="issuer:test:gateway", key_id="issuer.test.gateway/key/1"
    )
    binding_registry = overrides.pop("binding_registry", {selector: binding_version})
    config = GatewayAdapterConfig(
        binding_registry=binding_registry,
        connector=connector,
        identity=identity,
        sink=sink,
        runtime_instance_id="runtime:test:gateway",
        boundary_id="boundary:test:gateway",
        policy_pack_id="policy:test:gateway",
        policy_pack_version="2026.07.19",
        **overrides,
    )
    return config, identity, directory


async def _echo(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"echoed": True}


# --------------------------------------------------------------------------- #
# 1/2/3/24 — boundary discipline: request type, digest, no authority smuggling #
# --------------------------------------------------------------------------- #


async def test_execute_governed_call_rejects_a_non_governed_call_request(tmp_path: Path) -> None:
    connector = InMemoryToolConnector({"mem:fixture": {"echo": _echo}})
    config, _identity, _directory = _build_config(tmp_path, connector=connector)
    caller_request = _caller_request(arguments={"x": 1})

    with pytest.raises(TypeError):
        await execute_governed_call(caller_request, arguments={"x": 1}, config=config)  # type: ignore[arg-type]


async def test_argument_digest_mismatch_fails_closed_before_policy_or_execution(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []

    async def counting_echo(arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append(arguments)
        return {"echoed": True}

    connector = InMemoryToolConnector({"mem:fixture": {"echo": counting_echo}})
    config, _identity, directory = _build_config(tmp_path, connector=connector)
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 999}, config=config)

    assert response.decision.disposition == "refused"
    assert response.diagnostic_code == "malformed_request"
    assert response.receipts == ()
    assert not calls
    assert read_receipts(directory) == []


async def test_transient_arguments_cannot_reassert_actor_or_tenant(tmp_path: Path) -> None:
    arguments = {"actor_ref": "actor:evil", "tenant_id": "tenant:evil", "payload": 1}
    connector = InMemoryToolConnector({"mem:fixture": {"echo": _echo}})
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=FASTMCP_BINDING_VERSION
    )
    request = _resolved_request(
        arguments=arguments, actor_ref="actor:test:known", tenant_ref="tenant:test:known"
    )

    response = await execute_governed_call(request, arguments=arguments, config=config)

    assert response.decision.disposition == "admitted"
    admission = next(r for r in read_receipts(directory) if r["receipt_kind"] == "admission")
    assert admission["actor_ref"] == "actor:test:known"
    assert admission["tenant_id"] == "tenant:test:known"
    assert "evil" not in json.dumps(admission)


# --------------------------------------------------------------------------- #
# 4/5/6/7/8 — binding selection: known/unknown/unavailable, no substitution   #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_known_selector_resolves_and_executes_through_the_configured_binding(
    tmp_path: Path, binding_version: str
) -> None:
    connector = InMemoryToolConnector({"mem:fixture": {"echo": _echo}})
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision == response.decision  # sanity: constructed without raising
    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "result"
    receipts = read_receipts(directory)
    assert receipts
    assert all(r["extensions"]["mcp"]["binding_version"] == binding_version for r in receipts)


async def test_unknown_selector_fails_closed_with_zero_executions(tmp_path: Path) -> None:
    calls: list[Any] = []

    async def counting(_arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append(1)
        return {}

    connector = InMemoryToolConnector({"mem:fixture": {"echo": counting}})
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_registry={"other-key": FASTMCP_BINDING_VERSION}
    )
    request = _resolved_request(arguments={"x": 1}, selector="primary")

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision.disposition == "refused"
    assert response.diagnostic_code == "unknown_binding"
    assert response.receipts == ()
    assert not calls
    assert read_receipts(directory) == []


async def test_unavailable_binding_fails_closed_with_zero_executions_and_no_substitution(
    tmp_path: Path,
) -> None:
    calls: list[Any] = []

    async def counting(_arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append(1)
        return {}

    connector = InMemoryToolConnector({"mem:fixture": {"echo": counting}})
    config, _identity, directory = _build_config(
        tmp_path,
        connector=connector,
        binding_version=SDK_BINDING_VERSION,
        is_binding_available=lambda _version: False,
    )
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision.disposition == "refused"
    assert response.diagnostic_code == "binding_unavailable"
    assert response.receipts == ()
    assert not calls
    assert read_receipts(directory) == []
    # No substitution: the receipt directory must show no FastMCP-stamped
    # receipt either -- nothing was ever emitted at all.


async def test_direct_harness_binding_version_remains_non_selectable(tmp_path: Path) -> None:
    connector = InMemoryToolConnector({"mem:fixture": {"echo": _echo}})
    config, _identity, directory = _build_config(
        tmp_path,
        connector=connector,
        binding_registry={"primary": "direct-harness.v0.1"},
    )
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision.disposition == "refused"
    assert response.diagnostic_code == "unknown_binding"
    assert read_receipts(directory) == []


# --------------------------------------------------------------------------- #
# 9/10 — connector target resolution fails before execution                   #
# --------------------------------------------------------------------------- #


async def test_unknown_target_handle_fails_before_execution(tmp_path: Path) -> None:
    calls: list[Any] = []

    async def counting(_arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append(1)
        return {}

    connector = InMemoryToolConnector({"mem:fixture": {"echo": counting}})
    config, _identity, directory = _build_config(tmp_path, connector=connector)
    request = _resolved_request(arguments={"x": 1}, target="mem:does-not-exist")

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision.disposition == "refused"
    assert response.diagnostic_code == "remote_unavailable"
    assert not calls
    assert read_receipts(directory) == []


async def test_unknown_tool_fails_before_execution(tmp_path: Path) -> None:
    calls: list[Any] = []

    async def counting(_arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append(1)
        return {}

    connector = InMemoryToolConnector({"mem:fixture": {"echo": counting}})
    config, _identity, directory = _build_config(tmp_path, connector=connector)
    request = _resolved_request(arguments={"x": 1}, tool="no-such-tool")

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision.disposition == "refused"
    assert response.diagnostic_code == "unknown_tool_fail_closed"
    assert not calls
    assert read_receipts(directory) == []


# --------------------------------------------------------------------------- #
# 11 — raw arguments never persisted, logged, or returned untouched           #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_raw_arguments_are_not_persisted_on_receipts(
    tmp_path: Path, binding_version: str
) -> None:
    marker = "SECRET-ARGUMENT-MARKER-42"
    arguments = {"payload": marker}

    async def non_echoing(_arguments: dict[str, Any]) -> dict[str, Any]:
        return {"status": "ok"}

    connector = InMemoryToolConnector({"mem:fixture": {"echo": non_echoing}})
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(arguments=arguments)

    response = await execute_governed_call(request, arguments=arguments, config=config)

    assert response.business_result.payload == {"status": "ok"}
    for receipt in read_receipts(directory):
        assert marker not in json.dumps(receipt)


# --------------------------------------------------------------------------- #
# 12/13/19/25 — admitted result round-trips through both bindings             #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_admitted_result_round_trips_and_returns_ordered_receipt_handles(
    tmp_path: Path, binding_version: str
) -> None:
    connector = InMemoryToolConnector({"mem:fixture": {"echo": _echo}})
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "result"
    assert response.business_result.result_kind == "result"
    assert response.business_result.payload == {"echoed": True}
    assert len(response.receipts) == 2
    assert response.receipts[0].receipt_kind == "admission"
    assert response.receipts[1].receipt_kind == "outcome"
    assert response.diagnostic_code is None


async def test_common_lifecycle_behavior_is_conformant_across_both_bindings(tmp_path: Path) -> None:
    connector = InMemoryToolConnector({"mem:fixture": {"echo": _echo}})
    responses = {}
    for binding_version in BOTH_BINDINGS:
        config, _identity, _directory = _build_config(
            tmp_path / binding_version.replace(".", "_"),
            connector=connector,
            binding_version=binding_version,
        )
        request = _resolved_request(arguments={"x": 1})
        responses[binding_version] = await execute_governed_call(
            request, arguments={"x": 1}, config=config
        )

    fastmcp_response = responses[FASTMCP_BINDING_VERSION]
    sdk_response = responses[SDK_BINDING_VERSION]
    assert fastmcp_response.decision == sdk_response.decision
    assert fastmcp_response.business_result.result_kind == sdk_response.business_result.result_kind
    assert fastmcp_response.business_result.payload == sdk_response.business_result.payload
    assert len(fastmcp_response.receipts) == len(sdk_response.receipts) == 2


# --------------------------------------------------------------------------- #
# 14/20 — refusal: single receipt, never executes                             #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_refusal_returns_single_admission_receipt_and_never_executes(
    tmp_path: Path, binding_version: str
) -> None:
    calls: list[Any] = []

    async def counting(_arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append(1)
        return {}

    def policy_resolver(_snapshot: Any, _actor: Any) -> Any:
        return SimpleNamespace(
            disposition="refused",
            tool_class="read",
            reason_code="policy_refused",
            parent_receipt_ref=None,
            additional_attestation_limits=(),
        )

    connector = InMemoryToolConnector({"mem:fixture": {"echo": counting}})
    config, _identity, directory = _build_config(
        tmp_path,
        connector=connector,
        binding_version=binding_version,
        policy_resolver=policy_resolver,
    )
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision.disposition == "refused"
    assert response.decision.outcome is None
    assert response.diagnostic_code == "policy_refused"
    assert response.diagnostic_code in NEUTRAL_REFUSAL_GROUNDS
    assert response.business_result is None
    assert len(response.receipts) == 1
    assert response.receipts[0].receipt_kind == "admission"
    assert not calls


# --------------------------------------------------------------------------- #
# 15/20 — deferral: single receipt with review ref, never executes            #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_deferral_returns_single_receipt_with_review_ref_and_never_executes(
    tmp_path: Path, binding_version: str
) -> None:
    calls: list[Any] = []

    async def counting(_arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append(1)
        return {}

    def policy_resolver(_snapshot: Any, _actor: Any) -> Any:
        return SimpleNamespace(
            disposition="deferred_for_review",
            tool_class="write",
            reason_code=None,
            parent_receipt_ref=None,
            additional_attestation_limits=(),
        )

    connector = InMemoryToolConnector({"mem:fixture": {"echo": counting}})
    review_sink = InMemoryReviewObjectSink()
    config, _identity, directory = _build_config(
        tmp_path,
        connector=connector,
        binding_version=binding_version,
        policy_resolver=policy_resolver,
        review_object_creator=review_sink,
    )
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision.disposition == "deferred"
    assert response.diagnostic_code == "deferred_for_review"
    assert response.retry_instruction == "retry_after_approval"
    assert response.review_object_ref is not None
    assert response.business_result is None
    assert len(response.receipts) == 1
    assert not calls


# --------------------------------------------------------------------------- #
# 16 — tool-level error is structurally distinct from governance refusal      #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_admitted_tool_level_error_is_distinct_from_governance_refusal(
    tmp_path: Path, binding_version: str
) -> None:
    async def erroring(_arguments: dict[str, Any]) -> Any:
        return SimpleNamespace(content=[{"type": "text", "text": "boom"}], is_error=True)

    connector = InMemoryToolConnector({"mem:fixture": {"echo": erroring}})
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "error"
    assert response.business_result.result_kind == "error"
    assert len(response.receipts) == 2
    # Distinct from a governance refusal: business_result is present, and the
    # disposition is admitted, not refused.
    assert response.decision.disposition != "refused"
    assert response.business_result is not None


# --------------------------------------------------------------------------- #
# 17 — exception: no business result, correct outcome                        #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_admitted_exception_produces_no_business_result(
    tmp_path: Path, binding_version: str
) -> None:
    async def raising(_arguments: dict[str, Any]) -> Any:
        raise ValueError("internal tool detail that must never leak")

    connector = InMemoryToolConnector({"mem:fixture": {"echo": raising}})
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "exception"
    assert response.business_result is None
    assert response.diagnostic_code == "remote_exception"
    assert len(response.receipts) == 2
    assert "internal tool detail" not in json.dumps(dataclasses.asdict(response), default=str)
    for receipt in read_receipts(directory):
        assert "internal tool detail" not in json.dumps(receipt)


# --------------------------------------------------------------------------- #
# 18 — cancellation: three neutral facts; target does not continue unnoticed  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_cancellation_preserves_all_three_neutral_facts_and_stops_the_target(
    tmp_path: Path, binding_version: str
) -> None:
    reached_after_sleep = {"value": False}

    async def slow(_arguments: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(10)
        reached_after_sleep["value"] = True
        return {"should": "never happen"}

    connector = InMemoryToolConnector({"mem:fixture": {"echo": slow}})
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(arguments={"x": 1})

    task = asyncio.ensure_future(
        execute_governed_call(request, arguments={"x": 1}, config=config)
    )
    await asyncio.sleep(0.05)
    task.cancel()
    response = await task

    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "cancellation"
    assert response.diagnostic_code == "cancelled"
    assert response.business_result is None
    assert response.cancellation_facts is not None
    assert response.cancellation_facts.request_cancelled is True
    assert response.cancellation_facts.execution_state_unknown is True
    assert response.cancellation_facts.delivery_incomplete is True

    # The target must not silently continue running after the adapter has
    # already reported a completed (cancellation) response.
    await asyncio.sleep(0.2)
    assert reached_after_sleep["value"] is False


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_non_cancelled_completed_response_leaves_no_target_task_running(
    tmp_path: Path, binding_version: str
) -> None:
    # Companion to the cancellation test: for an ordinary (non-cancelled)
    # completed response, the target has genuinely finished -- there is no
    # detached background continuation left over either.
    completed = {"value": False}

    async def quick(_arguments: dict[str, Any]) -> dict[str, Any]:
        completed["value"] = True
        return {"echoed": True}

    connector = InMemoryToolConnector({"mem:fixture": {"echo": quick}})
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision.outcome == "result"
    assert completed["value"] is True
    assert len(asyncio.all_tasks() - {asyncio.current_task()}) == 0


# --------------------------------------------------------------------------- #
# 21 — required pre-execution sink failure prevents tool execution            #
# --------------------------------------------------------------------------- #


class _AlwaysFailingSink:
    def write(self, _envelope: dict[str, Any]) -> str:
        raise ReceiptWriteError("simulated durable sink failure")

    def write_trust_bundle(self, *_args: Any, **_kwargs: Any) -> Any:
        raise ReceiptWriteError("simulated durable sink failure")


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_required_pre_execution_sink_failure_prevents_execution(
    tmp_path: Path, binding_version: str
) -> None:
    calls: list[Any] = []

    async def counting(_arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append(1)
        return {}

    connector = InMemoryToolConnector({"mem:fixture": {"echo": counting}})
    # "write" tool class defaults to fail_closed pre-execution receipt
    # failure on both bindings.
    config, _identity, _directory = _build_config(
        tmp_path,
        connector=connector,
        binding_version=binding_version,
        sink=_AlwaysFailingSink(),
        tool_classes={"echo": "write"},
    )
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision.disposition == "refused"
    assert response.diagnostic_code == "required_sink_unavailable"
    assert response.receipts == ()
    assert not calls


# --------------------------------------------------------------------------- #
# 21a — a pre-admission operator/resolver failure is not a fabricated sink    #
# outage: no receipt write was ever attempted, so it must not be classified  #
# as required_sink_unavailable, and it must remain distinguishable from a    #
# genuine sink failure.                                                      #
# --------------------------------------------------------------------------- #


class _RaisingPolicyResolverError(RuntimeError):
    """A distinctive, narrow marker exception for the raising resolver below."""


def _raising_policy_resolver(_snapshot: Any, _actor: Any) -> Any:
    raise _RaisingPolicyResolverError("boom from policy resolver, before any receipt write")


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_pre_admission_resolver_failure_executes_no_target_and_is_not_sink_unavailable(
    tmp_path: Path, binding_version: str
) -> None:
    calls: list[Any] = []

    async def counting(_arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append(1)
        return {}

    connector = InMemoryToolConnector({"mem:fixture": {"echo": counting}})
    config, _identity, directory = _build_config(
        tmp_path,
        connector=connector,
        binding_version=binding_version,
        policy_resolver=_raising_policy_resolver,
    )
    request = _resolved_request(arguments={"x": 1})

    with pytest.raises(_RaisingPolicyResolverError):
        await execute_governed_call(request, arguments={"x": 1}, config=config)

    # No target execution, no fabricated receipt, and -- because this never
    # produces a GovernedCallResponse at all -- no possibility of a false
    # required_sink_unavailable (or any other) diagnostic.
    assert not calls
    assert read_receipts(directory) == []


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_pre_admission_resolver_failure_and_genuine_sink_failure_stay_distinguishable(
    tmp_path: Path, binding_version: str
) -> None:
    connector = InMemoryToolConnector({"mem:fixture": {"echo": _echo}})
    request = _resolved_request(arguments={"x": 1})

    resolver_config, _identity, resolver_directory = _build_config(
        tmp_path / "resolver",
        connector=connector,
        binding_version=binding_version,
        policy_resolver=_raising_policy_resolver,
    )
    with pytest.raises(_RaisingPolicyResolverError):
        await execute_governed_call(request, arguments={"x": 1}, config=resolver_config)
    assert read_receipts(resolver_directory) == []

    sink_config, _identity2, _sink_directory = _build_config(
        tmp_path / "sink",
        connector=connector,
        binding_version=binding_version,
        sink=_AlwaysFailingSink(),
        tool_classes={"echo": "write"},
    )
    sink_response = await execute_governed_call(request, arguments={"x": 1}, config=sink_config)

    # The two failure causes never collapse into the same, or an
    # indistinguishable, outcome: one propagates the operator's own
    # exception (no response at all), the other returns a grounded refusal.
    assert sink_response.decision.disposition == "refused"
    assert sink_response.diagnostic_code == "required_sink_unavailable"
    assert sink_response.receipts == ()


# --------------------------------------------------------------------------- #
# 22 — post-execution receipt failure preserves alert_and_return_result       #
# --------------------------------------------------------------------------- #


class _FailAfterNSink:
    """Delegates to a real sink but raises starting from the Nth write call."""

    def __init__(self, inner: Any, fail_from_call_index: int) -> None:
        self._inner = inner
        self._fail_from_call_index = fail_from_call_index
        self._calls = 0

    def write(self, envelope: dict[str, Any]) -> str:
        index = self._calls
        self._calls += 1
        if index >= self._fail_from_call_index:
            raise ReceiptWriteError("simulated post-execution sink failure")
        return self._inner.write(envelope)

    def write_trust_bundle(self, *args: Any, **kwargs: Any) -> Any:
        return self._inner.write_trust_bundle(*args, **kwargs)


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_post_execution_receipt_failure_still_returns_business_result(
    tmp_path: Path, binding_version: str
) -> None:
    directory = tmp_path / "receipts"
    real_sink = RawEnvelopeFileSink(directory)
    failing_sink = _FailAfterNSink(real_sink, fail_from_call_index=1)

    connector = InMemoryToolConnector({"mem:fixture": {"echo": _echo}})
    config, _identity, _directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version, sink=failing_sink
    )
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "result"
    assert response.business_result is not None
    assert response.business_result.payload == {"echoed": True}
    # Only the admission receipt was durably written; the outcome write
    # failed and the existing binding's alert_and_return_result posture
    # still returns the business result.
    assert len(response.receipts) == 1
    assert response.receipts[0].receipt_kind == "admission"


# --------------------------------------------------------------------------- #
# 23 — receipt handles expose no signer or unrestricted storage path          #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_receipt_handles_expose_no_signer_or_storage_path(
    tmp_path: Path, binding_version: str
) -> None:
    connector = InMemoryToolConnector({"mem:fixture": {"echo": _echo}})
    config, _identity, _directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    field_names = {f.name for f in dataclasses.fields(ReceiptHandle)}
    assert field_names == {"receipt_id", "receipt_kind", "location_handle"}
    for handle in response.receipts:
        assert handle.location_handle is None


# --------------------------------------------------------------------------- #
# 23a — ReceiptHandle carries the sink-returned identifier, not the           #
# pre-write envelope's own field                                              #
# --------------------------------------------------------------------------- #


class _RemappingIdSink:
    """Delegates to a real sink but returns an identifier the envelope never carries."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._calls = 0

    def write(self, envelope: dict[str, Any]) -> str:
        self._inner.write(envelope)
        self._calls += 1
        return f"sink-assigned-id-{self._calls}"

    def write_trust_bundle(self, *args: Any, **kwargs: Any) -> Any:
        return self._inner.write_trust_bundle(*args, **kwargs)


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_receipt_handle_uses_the_sink_returned_identifier(
    tmp_path: Path, binding_version: str
) -> None:
    directory = tmp_path / "receipts"
    remapping_sink = _RemappingIdSink(RawEnvelopeFileSink(directory))

    connector = InMemoryToolConnector({"mem:fixture": {"echo": _echo}})
    config, _identity, _directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version, sink=remapping_sink
    )
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert [handle.receipt_id for handle in response.receipts] == [
        "sink-assigned-id-1",
        "sink-assigned-id-2",
    ]
    # The durably written envelopes still carry their own minted receipt_id
    # (the emitter's, not the sink's) -- proving the response handle came
    # from the sink's return value, not read back off the envelope.
    on_disk_ids = {receipt["receipt_id"] for receipt in read_receipts(directory)}
    assert on_disk_ids.isdisjoint({"sink-assigned-id-1", "sink-assigned-id-2"})


# --------------------------------------------------------------------------- #
# 26 — task_submitted capability difference is explicit and fail-closed       #
# --------------------------------------------------------------------------- #


def _task_result() -> Any:
    from mcp.types import CreateTaskResult, Task

    now = datetime.now(UTC)
    return CreateTaskResult(
        task=Task(
            taskId="task:gateway:test:1",
            status="working",
            createdAt=now,
            lastUpdatedAt=now,
            ttl=None,
        )
    )


async def test_task_submission_is_unsupported_and_fail_closed_over_the_sdk_binding(
    tmp_path: Path,
) -> None:
    async def submits_task(_arguments: dict[str, Any]) -> Any:
        return _task_result()

    connector = InMemoryToolConnector({"mem:fixture": {"echo": submits_task}})
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=SDK_BINDING_VERSION
    )
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision.disposition == "admitted"
    assert response.decision.outcome is None
    assert response.diagnostic_code == "unsupported_lifecycle_state"
    assert response.business_result is None
    assert len(response.receipts) == 1
    assert response.receipts[0].receipt_kind == "admission"


async def test_task_submission_is_supported_and_explicit_over_the_fastmcp_binding(
    tmp_path: Path,
) -> None:
    async def submits_task(_arguments: dict[str, Any]) -> Any:
        return _task_result()

    connector = InMemoryToolConnector({"mem:fixture": {"echo": submits_task}})
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=FASTMCP_BINDING_VERSION
    )
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "task_submitted"
    assert response.business_result is None
    receipts = read_receipts(directory)
    outcome_receipt = next(r for r in receipts if r["receipt_kind"] == "outcome")
    assert outcome_receipt["outcome"] == "task_submitted"


# --------------------------------------------------------------------------- #
# 27/28/29 — import purity and no network socket                              #
# --------------------------------------------------------------------------- #


def test_fresh_import_of_adapter_module_does_not_pull_in_transport_or_storage_libraries() -> None:
    script = (
        "import sys\n"
        "from dagr_mcp_service import adapter\n"
        "roots = {m.split('.', 1)[0] for m in sys.modules}\n"
        "forbidden = {\n"
        "    'mcp', 'fastmcp', 'uvicorn', 'starlette', 'aiohttp', 'httpx',\n"
        "    'fastapi', 'flask', 'sqlalchemy', 'psycopg2', 'pika', 'kombu', 'celery',\n"
        "}\n"
        "hit = roots & forbidden\n"
        "assert not hit, hit\n"
        "assert hasattr(adapter, 'execute_governed_call')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_fresh_import_of_service_package_still_starts_no_transport_with_a8_present() -> None:
    script = (
        "import sys\n"
        "import dagr_mcp_service\n"
        "import dagr_mcp_service.connectors\n"
        "roots = {m.split('.', 1)[0] for m in sys.modules}\n"
        "forbidden = {\n"
        "    'mcp', 'fastmcp', 'uvicorn', 'starlette', 'aiohttp', 'httpx',\n"
        "    'fastapi', 'flask', 'sqlalchemy', 'psycopg2', 'pika', 'kombu', 'celery',\n"
        "}\n"
        "hit = roots & forbidden\n"
        "assert not hit, hit\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_no_network_socket_is_created_during_an_admitted_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, binding_version: str
) -> None:
    def _forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("socket.socket() was called during an in-process governed call")

    monkeypatch.setattr(socket, "socket", _forbidden)

    connector = InMemoryToolConnector({"mem:fixture": {"echo": _echo}})
    config, _identity, _directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision.disposition == "admitted"


# --------------------------------------------------------------------------- #
# 30 — no idempotency, deduplication, retry, or exactly-once API              #
# --------------------------------------------------------------------------- #


def test_no_idempotency_or_exactly_once_surface_on_the_adapter_config() -> None:
    field_names = {f.name for f in dataclasses.fields(GatewayAdapterConfig)}
    for forbidden_name in (
        "idempotency_key",
        "dedup_key",
        "replay_of",
        "exactly_once",
        "retry_policy",
        "max_retries",
    ):
        assert forbidden_name not in field_names


def test_no_idempotency_or_retry_names_appear_in_the_adapter_public_surface() -> None:
    import dagr_mcp_service.adapter as adapter_module

    forbidden_substrings = ("idempot", "dedup", "exactly_once", "replay")
    public_names = [name for name in dir(adapter_module) if not name.startswith("_")]
    for name in public_names:
        lowered = name.lower()
        for forbidden in forbidden_substrings:
            assert forbidden not in lowered, name
