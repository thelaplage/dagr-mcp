"""Sprint A9 — the remote connector driven through
``dagr_mcp_service.adapter.execute_governed_call``, end to end.

Proves the remote connector composes with the unmodified A7 contract, the
unmodified A1/A4/A5 lifecycle bindings, and the A8 adapter exactly the way
the memory connector already does — the only new adapter-visible behavior is
the additive ``bind_trusted_context`` hook and the ``ConnectionError`` ->
``remote_unavailable`` distinction (see ``dagr_mcp_service/adapter.py``'s A9
docstring addendum). Driven against a real loopback MCP server over the
pinned ``mcp==1.28.1`` Streamable HTTP client transport (see
``tests/_gateway_service_remote_fixtures.py``). See
``docs/GATEWAY_SERVICE_ADAPTER_SCOPE.md`` §3/§4/§6/§8/§9/§10/§12, work
package A9.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import socket
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastmcp")
pytest.importorskip("mcp")

from dagr_mcp.srs_receipts import RawEnvelopeFileSink, SigningIdentity, sha256_digest
from dagr_mcp_service.adapter import GatewayAdapterConfig, execute_governed_call
from dagr_mcp_service.connectors.remote import (
    RemoteCredential,
    RemoteTargetConfig,
    RemoteToolConnector,
    TrustedOutboundContext,
)
from dagr_mcp_service.contract import (
    CallerGovernedCallRequest,
    GovernedCallRequest,
    TargetServerRef,
    TrustedActorRef,
    TrustedTenantRef,
)
from dagr_mcp_service.resolution import (
    FASTMCP_BINDING_VERSION,
    SDK_BINDING_VERSION,
    BindingSelectorKey,
)

from tests._gateway_service_remote_fixtures import LoopbackMcpServer, loopback_mcp_server  # noqa: F401

BOTH_BINDINGS = (FASTMCP_BINDING_VERSION, SDK_BINDING_VERSION)


# --------------------------------------------------------------------------- #
# Helpers (mirrors tests/test_gateway_service_adapter.py's conventions)      #
# --------------------------------------------------------------------------- #


def _digest(arguments: dict[str, Any]) -> str:
    return sha256_digest(dict(arguments))


def _caller_request(
    *,
    selector: str = "primary",
    target: str = "bossy:test",
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


def _build_config(
    tmp_path: Path,
    *,
    connector: Any,
    selector: str = "primary",
    binding_version: str = FASTMCP_BINDING_VERSION,
    **overrides: Any,
) -> tuple[GatewayAdapterConfig, SigningIdentity, Path]:
    directory = tmp_path / "receipts"
    sink = overrides.pop("sink", None) or RawEnvelopeFileSink(directory)
    identity = SigningIdentity.generate(
        issuer_id="issuer:test:gateway-a9", key_id="issuer.test.gateway-a9/key/1"
    )
    binding_registry = overrides.pop("binding_registry", {selector: binding_version})
    config = GatewayAdapterConfig(
        binding_registry=binding_registry,
        connector=connector,
        identity=identity,
        sink=sink,
        runtime_instance_id="runtime:test:gateway-a9",
        boundary_id="boundary:test:gateway-a9",
        policy_pack_id="policy:test:gateway-a9",
        policy_pack_version="2026.07.19",
        **overrides,
    )
    return config, identity, directory


def _remote_connector(base_url: str, **target_overrides: Any) -> RemoteToolConnector:
    return RemoteToolConnector(
        {
            "bossy:test": RemoteTargetConfig(
                handle="bossy:test",
                endpoint_uri=base_url,
                allow_insecure_loopback=True,
                timeout_seconds=target_overrides.pop("timeout_seconds", 5.0),
                **target_overrides,
            )
        }
    )


def read_receipts(directory: Path) -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("urn_srs_receipt_*.json"))
    ]


# --------------------------------------------------------------------------- #
# Admitted result / tool-level error -- both bindings                        #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_admitted_remote_result_round_trips_through_both_bindings(
    tmp_path: Path, binding_version: str, loopback_mcp_server: LoopbackMcpServer
) -> None:
    connector = _remote_connector(loopback_mcp_server.base_url)
    config, _identity, _directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(arguments={"x": "hello"})

    response = await execute_governed_call(request, arguments={"x": "hello"}, config=config)

    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "result"
    assert response.business_result.result_kind == "result"
    assert len(response.receipts) == 2


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_remote_tool_level_error_is_distinct_from_governance_refusal(
    tmp_path: Path, binding_version: str, loopback_mcp_server: LoopbackMcpServer
) -> None:
    connector = _remote_connector(loopback_mcp_server.base_url)
    config, _identity, _directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(tool="boom", arguments={"x": "hello"})

    response = await execute_governed_call(request, arguments={"x": "hello"}, config=config)

    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "error"
    assert response.business_result.result_kind == "error"
    assert response.decision.disposition != "refused"
    assert len(response.receipts) == 2


# --------------------------------------------------------------------------- #
# Diagnostic mapping: remote_unavailable vs. remote_exception vs. cancelled  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_remote_unavailable_maps_accurately_and_is_distinct_from_generic_exception(
    tmp_path: Path, binding_version: str
) -> None:
    connector = RemoteToolConnector(
        {
            "bossy:down": RemoteTargetConfig(
                handle="bossy:down",
                endpoint_uri="http://127.0.0.1:1/mcp",
                allow_insecure_loopback=True,
                timeout_seconds=3.0,
            )
        }
    )
    config, _identity, _directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(target="bossy:down", arguments={"x": "hello"})

    response = await execute_governed_call(request, arguments={"x": "hello"}, config=config)

    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "exception"
    assert response.diagnostic_code == "remote_unavailable"
    assert response.business_result is None
    # Admission still durably recorded; the tool was attempted (governance
    # already committed) even though the connection itself never succeeded.
    assert len(response.receipts) == 2


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_remote_protocol_exception_maps_to_the_generic_remote_exception_bucket(
    tmp_path: Path, binding_version: str, loopback_mcp_server: LoopbackMcpServer
) -> None:
    connector = _remote_connector(loopback_mcp_server.base_url, timeout_seconds=1.0)
    config, _identity, _directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    # "slow" outlives the 1s target timeout -- an application-level McpError
    # timeout, translated to TimeoutError, distinct from remote_unavailable.
    request = _resolved_request(tool="slow", arguments={"x": "hello", "seconds": 5.0})

    response = await execute_governed_call(
        request, arguments={"x": "hello", "seconds": 5.0}, config=config
    )

    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "exception"
    assert response.diagnostic_code == "remote_exception"
    assert response.diagnostic_code != "remote_unavailable"
    # A timeout never claims to know execution did not happen: no
    # cancellation_facts are fabricated for a timeout, and the outcome family
    # is the same honest "exception" both bindings already use for a timeout
    # (§14 subsumption) -- this module invents no new claim.
    assert response.cancellation_facts is None


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_cancellation_carries_grounded_cancellation_facts_over_the_remote_connector(
    tmp_path: Path, binding_version: str, loopback_mcp_server: LoopbackMcpServer
) -> None:
    connector = _remote_connector(loopback_mcp_server.base_url, timeout_seconds=30.0)
    config, _identity, _directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(tool="slow", arguments={"x": "hello", "seconds": 30.0})

    task = asyncio.ensure_future(
        execute_governed_call(request, arguments={"x": "hello", "seconds": 30.0}, config=config)
    )
    await asyncio.sleep(1.0)
    task.cancel()
    # Both bindings' own except-asyncio.CancelledError handling (frozen A1/A4/
    # A5 behavior, unmodified by A9) catches the cancellation, records it, and
    # returns a normal GovernedCallResponse rather than letting the
    # CancelledError propagate out of execute_governed_call -- confirmed by
    # dagr_mcp_service/adapter.py's own _execute_via_fastmcp/_execute_via_sdk
    # ``except asyncio.CancelledError as exc: return _classify(...)``.
    response = await task

    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "cancellation"
    assert response.diagnostic_code == "cancelled"
    assert response.business_result is None
    assert response.cancellation_facts is not None
    assert response.cancellation_facts.request_cancelled is True
    assert response.cancellation_facts.execution_state_unknown is True
    assert response.cancellation_facts.delivery_incomplete is True


# --------------------------------------------------------------------------- #
# Fail-closed: unknown target / unsupported scheme / digest mismatch never   #
# open a socket or reach the credential provider.                            #
# --------------------------------------------------------------------------- #


async def test_unknown_target_handle_refuses_and_opens_no_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = RemoteToolConnector(
        {
            "bossy:test": RemoteTargetConfig(
                handle="bossy:test", endpoint_uri="https://bossy.example.com/mcp"
            )
        }
    )
    config, _identity, _directory = _build_config(tmp_path, connector=connector)
    request = _resolved_request(target="bossy:does-not-exist", arguments={"x": "hi"})

    def _forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("unknown target handle must never open a socket")

    monkeypatch.setattr(socket, "socket", _forbidden)

    response = await execute_governed_call(request, arguments={"x": "hi"}, config=config)

    assert response.decision.disposition == "refused"
    assert response.diagnostic_code == "remote_unavailable"
    assert response.receipts == ()


async def test_digest_mismatch_performs_no_credential_lookup_or_network_operation(
    tmp_path: Path, loopback_mcp_server: LoopbackMcpServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider_calls: list[TrustedOutboundContext] = []
    policy_calls: list[Any] = []

    async def provider(context: TrustedOutboundContext) -> RemoteCredential:
        provider_calls.append(context)
        return RemoteCredential(headers={"Authorization": "Bearer should-never-be-used"})

    def _policy_resolver(snapshot: Any, actor: Any) -> Any:
        from types import SimpleNamespace

        policy_calls.append((snapshot, actor))
        return SimpleNamespace(
            disposition="admitted",
            tool_class="read",
            reason_code=None,
            parent_receipt_ref=None,
            additional_attestation_limits=(),
        )

    connector = _remote_connector(loopback_mcp_server.base_url, credential_provider=provider)
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, policy_resolver=_policy_resolver
    )
    request = _resolved_request(arguments={"x": "hello"})

    def _forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a digest mismatch must never open a socket")

    monkeypatch.setattr(socket, "socket", _forbidden)

    # Deliberately mismatched: the request's digest was computed over
    # {"x": "hello"}, but a different mapping is supplied at call time. This
    # must fail closed at the synchronous snapshot/digest step in
    # ``execute_governed_call`` -- before binding selection, before the
    # policy resolver, before the credential provider, before any receipt
    # write, and before any socket.
    response = await execute_governed_call(
        request, arguments={"x": "tampered"}, config=config
    )

    assert response.decision.disposition == "refused"
    assert response.diagnostic_code == "malformed_request"
    assert response.receipts == ()
    assert policy_calls == []
    assert provider_calls == []
    assert read_receipts(directory) == []


async def test_unknown_binding_opens_no_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = RemoteToolConnector(
        {
            "bossy:test": RemoteTargetConfig(
                handle="bossy:test", endpoint_uri="https://bossy.example.com/mcp"
            )
        }
    )
    config, _identity, _directory = _build_config(
        tmp_path, connector=connector, binding_registry={"primary": "some.other.binding.v9"}
    )
    request = _resolved_request(arguments={"x": "hi"})

    def _forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("an unknown binding must never open a socket")

    monkeypatch.setattr(socket, "socket", _forbidden)

    response = await execute_governed_call(request, arguments={"x": "hi"}, config=config)

    assert response.decision.disposition == "refused"
    assert response.diagnostic_code == "unknown_binding"


async def test_unavailable_binding_opens_no_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = RemoteToolConnector(
        {
            "bossy:test": RemoteTargetConfig(
                handle="bossy:test", endpoint_uri="https://bossy.example.com/mcp"
            )
        }
    )
    config, _identity, _directory = _build_config(
        tmp_path, connector=connector, is_binding_available=lambda _v: False
    )
    request = _resolved_request(arguments={"x": "hi"})

    def _forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("an unavailable binding must never open a socket")

    monkeypatch.setattr(socket, "socket", _forbidden)

    response = await execute_governed_call(request, arguments={"x": "hi"}, config=config)

    assert response.decision.disposition == "refused"
    assert response.diagnostic_code == "binding_unavailable"


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_policy_refusal_opens_no_remote_connection(
    tmp_path: Path, binding_version: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = RemoteToolConnector(
        {
            "bossy:test": RemoteTargetConfig(
                handle="bossy:test", endpoint_uri="https://bossy.example.com/mcp"
            )
        }
    )

    def _refusing_policy_resolver(_snapshot: Any, _actor: Any) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(
            disposition="refused",
            tool_class="read",
            reason_code="policy_refused",
            parent_receipt_ref=None,
            additional_attestation_limits=(),
        )

    config, _identity, _directory = _build_config(
        tmp_path,
        connector=connector,
        binding_version=binding_version,
        policy_resolver=_refusing_policy_resolver,
    )
    request = _resolved_request(arguments={"x": "hi"})

    def _forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a policy refusal must never open a socket")

    monkeypatch.setattr(socket, "socket", _forbidden)

    response = await execute_governed_call(request, arguments={"x": "hi"}, config=config)

    assert response.decision.disposition == "refused"


# --------------------------------------------------------------------------- #
# No caller-authority smuggling                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_transient_arguments_cannot_reassert_actor_tenant_or_credentials(
    tmp_path: Path, binding_version: str, loopback_mcp_server: LoopbackMcpServer
) -> None:
    seen_context: list[TrustedOutboundContext] = []

    async def provider(context: TrustedOutboundContext) -> RemoteCredential:
        seen_context.append(context)
        return RemoteCredential(headers={"Authorization": "Bearer operator-issued"})

    connector = _remote_connector(loopback_mcp_server.base_url, credential_provider=provider)
    config, _identity, _directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    decoy_arguments = {
        "x": "hi",
        "actor_ref": "actor:sha256:attacker-supplied",
        "tenant_ref": "tenant:sha256:attacker-supplied",
        "Authorization": "Bearer attacker-supplied",
        "credential": "attacker-supplied",
    }
    request = _resolved_request(
        actor_ref="actor:test:real",
        tenant_ref="tenant:test:real",
        arguments=decoy_arguments,
        tool="observed_headers",
    )

    response = await execute_governed_call(request, arguments=decoy_arguments, config=config)

    assert response.decision.disposition == "admitted"
    assert len(seen_context) == 1
    assert seen_context[0].actor_ref == "actor:test:real"
    assert seen_context[0].tenant_ref == "tenant:test:real"

    observed_remote_headers = json.loads(response.business_result.payload.content[0].text)
    assert observed_remote_headers.get("authorization") == "Bearer operator-issued"


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_the_exact_verified_argument_snapshot_is_what_reaches_the_remote_tool(
    tmp_path: Path, binding_version: str, loopback_mcp_server: LoopbackMcpServer
) -> None:
    connector = _remote_connector(loopback_mcp_server.base_url)
    config, _identity, _directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    arguments = {"x": "exact-snapshot-value"}
    request = _resolved_request(arguments=arguments)

    response = await execute_governed_call(request, arguments=arguments, config=config)

    assert response.business_result.payload.content[0].text == "echo:exact-snapshot-value"


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_arguments_mutated_before_the_call_have_no_bearing_on_the_call(
    tmp_path: Path, binding_version: str, loopback_mcp_server: LoopbackMcpServer
) -> None:
    """Narrow, call-time-only sanity check -- NOT proof of race safety.

    This only proves that mutating the caller's own dict *before*
    ``execute_governed_call`` is invoked has no bearing on the call, since a
    different, already-settled mapping is what is actually passed in. It
    says nothing about a mutation racing the awaited admission window
    between digest verification and transmission -- that is what
    ``test_fastmcp_top_level_mutation_during_awaited_admission_is_not_transmitted``
    and
    ``test_fastmcp_nested_mutation_during_awaited_admission_is_not_transmitted``
    below actually reproduce and close.
    """

    connector = _remote_connector(loopback_mcp_server.base_url)
    config, _identity, _directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    mutable_arguments = {"x": "original"}
    request = _resolved_request(arguments=mutable_arguments)

    # Mutate before execute_governed_call is ever invoked.
    mutable_arguments["x"] = "mutated-before-call"

    response = await execute_governed_call(
        request, arguments={"x": "original"}, config=config
    )

    assert response.business_result.payload.content[0].text == "echo:original"


async def test_fastmcp_top_level_mutation_during_awaited_admission_is_not_transmitted(
    tmp_path: Path, loopback_mcp_server: LoopbackMcpServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduces and closes the independent-review finding.

    A real async policy resolver (a real awaited admission extension point)
    suspends mid-call; while it is suspended, a second task mutates the
    caller-owned ``mutable_arguments`` mapping in place. Before the fix,
    ``execute_governed_call`` verified the digest over the pre-mutation
    value but the FastMCP binding's ``call_next`` closure re-read the same
    shared mapping later, after the suspension -- transmitting the mutated
    value to the real remote tool while the admission receipt kept
    attesting the original, verified digest. Capturing at
    ``dagr_mcp_service.connectors.remote._call_remote_tool`` (the actual
    wire boundary) proves what was really sent.
    """

    import dagr_mcp_service.connectors.remote as remote_module

    transmitted: list[dict[str, Any]] = []
    original_call_remote_tool = remote_module._call_remote_tool

    async def _capturing_call_remote_tool(
        target: Any, tool_name: str, arguments: Any, *, context: Any
    ) -> Any:
        transmitted.append(dict(arguments))
        return await original_call_remote_tool(target, tool_name, arguments, context=context)

    monkeypatch.setattr(remote_module, "_call_remote_tool", _capturing_call_remote_tool)

    resume = asyncio.Event()

    async def _suspending_policy_resolver(_snapshot: Any, _actor: Any) -> Any:
        from types import SimpleNamespace

        await resume.wait()
        return SimpleNamespace(
            disposition="admitted",
            tool_class="read",
            reason_code=None,
            parent_receipt_ref=None,
            additional_attestation_limits=(),
        )

    connector = _remote_connector(loopback_mcp_server.base_url)
    config, _identity, directory = _build_config(
        tmp_path,
        connector=connector,
        binding_version=FASTMCP_BINDING_VERSION,
        policy_resolver=_suspending_policy_resolver,
    )
    mutable_arguments = {"x": "verified-value"}
    request = _resolved_request(arguments=mutable_arguments)

    call_task = asyncio.ensure_future(
        execute_governed_call(request, arguments=mutable_arguments, config=config)
    )
    # Yield enough turns for the task to reach the suspended policy
    # resolver -- everything before it (snapshot/digest verification,
    # binding selection, connector resolution) is synchronous.
    await asyncio.sleep(0.05)
    mutable_arguments["x"] = "mutated-during-admission"
    resume.set()
    response = await call_task

    assert transmitted == [{"x": "verified-value"}]
    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "result"
    assert response.business_result.payload.content[0].text == "echo:verified-value"

    envelopes = read_receipts(directory)
    admission = next(e for e in envelopes if e["receipt_kind"] == "admission")
    assert admission["argument_digest"] == sha256_digest({"x": "verified-value"})
    assert "mutated-during-admission" not in json.dumps(envelopes)


async def test_fastmcp_nested_mutation_during_awaited_admission_is_not_transmitted(
    tmp_path: Path, loopback_mcp_server: LoopbackMcpServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same race as the top-level test, but on nested mutable content.

    A top-level-only ``dict(arguments)`` copy would still share the nested
    ``dict``/``list`` objects with the caller's mapping and would leak this
    mutation straight through; a shallow-copy implementation must fail this
    test.
    """

    import dagr_mcp_service.connectors.remote as remote_module

    transmitted: list[dict[str, Any]] = []
    original_call_remote_tool = remote_module._call_remote_tool

    async def _capturing_call_remote_tool(
        target: Any, tool_name: str, arguments: Any, *, context: Any
    ) -> Any:
        transmitted.append(json.loads(json.dumps(dict(arguments))))
        return await original_call_remote_tool(target, tool_name, arguments, context=context)

    monkeypatch.setattr(remote_module, "_call_remote_tool", _capturing_call_remote_tool)

    resume = asyncio.Event()

    async def _suspending_policy_resolver(_snapshot: Any, _actor: Any) -> Any:
        from types import SimpleNamespace

        await resume.wait()
        return SimpleNamespace(
            disposition="admitted",
            tool_class="read",
            reason_code=None,
            parent_receipt_ref=None,
            additional_attestation_limits=(),
        )

    connector = _remote_connector(loopback_mcp_server.base_url)
    config, _identity, directory = _build_config(
        tmp_path,
        connector=connector,
        binding_version=FASTMCP_BINDING_VERSION,
        policy_resolver=_suspending_policy_resolver,
    )
    verified_snapshot = {
        "x": "outer",
        "items": {"list": [1, 2, {"inner": "orig"}], "flag": True},
    }
    mutable_arguments = json.loads(json.dumps(verified_snapshot))
    request = _resolved_request(arguments=mutable_arguments)

    call_task = asyncio.ensure_future(
        execute_governed_call(request, arguments=mutable_arguments, config=config)
    )
    await asyncio.sleep(0.05)
    # Mutate only nested containers -- never the top-level dict itself.
    mutable_arguments["items"]["list"].append("smuggled")
    mutable_arguments["items"]["list"][2]["inner"] = "mutated-during-admission"
    mutable_arguments["items"]["flag"] = False
    resume.set()
    response = await call_task

    assert transmitted == [verified_snapshot]
    assert response.decision.disposition == "admitted"

    envelopes = read_receipts(directory)
    admission = next(e for e in envelopes if e["receipt_kind"] == "admission")
    assert admission["argument_digest"] == sha256_digest(verified_snapshot)
    serialized_envelopes = json.dumps(envelopes)
    assert "smuggled" not in serialized_envelopes
    assert "mutated-during-admission" not in serialized_envelopes


async def test_sdk_binding_receives_the_same_detached_snapshot_not_the_original_mapping(
    tmp_path: Path, loopback_mcp_server: LoopbackMcpServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Narrow official-SDK parity check for the same detached-snapshot fix.

    Proves ``_execute_via_sdk`` is handed the exact snapshot
    ``execute_governed_call`` froze and verified -- never the caller-owned
    ``mutable_arguments`` object -- without re-running the full FastMCP race
    suite above.
    """

    import dagr_mcp_service.adapter as adapter_module

    captured: list[Any] = []
    original_execute_via_sdk = adapter_module._execute_via_sdk

    async def _capturing_execute_via_sdk(
        request: Any, arguments: Any, handler: Any, config: Any
    ) -> Any:
        captured.append(arguments)
        return await original_execute_via_sdk(request, arguments, handler, config)

    monkeypatch.setattr(adapter_module, "_execute_via_sdk", _capturing_execute_via_sdk)

    connector = _remote_connector(loopback_mcp_server.base_url)
    config, _identity, _directory = _build_config(
        tmp_path, connector=connector, binding_version=SDK_BINDING_VERSION
    )
    mutable_arguments = {"x": "sdk-verified-value"}
    request = _resolved_request(arguments=mutable_arguments)

    response = await execute_governed_call(request, arguments=mutable_arguments, config=config)

    assert len(captured) == 1
    assert captured[0] == {"x": "sdk-verified-value"}
    assert captured[0] is not mutable_arguments

    mutable_arguments["x"] = "mutated-after-call"
    assert captured[0] == {"x": "sdk-verified-value"}
    assert response.business_result.payload.content[0].text == "echo:sdk-verified-value"


# --------------------------------------------------------------------------- #
# Credential absence from response / receipts / raised errors                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_credentials_never_appear_in_response_or_receipts(
    tmp_path: Path, binding_version: str, loopback_mcp_server: LoopbackMcpServer
) -> None:
    secret = "sk-A9-NEVER-LEAK-abc123"  # noqa: S105 - test fixture literal, not a real secret.

    async def provider(context: TrustedOutboundContext) -> RemoteCredential:
        return RemoteCredential(headers={"Authorization": f"Bearer {secret}"})

    connector = _remote_connector(loopback_mcp_server.base_url, credential_provider=provider)
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(arguments={"x": "hi"})

    response = await execute_governed_call(request, arguments={"x": "hi"}, config=config)

    # response.to_json() is not used here: business_result.payload carries
    # the binding's raw, un-projected tool result object (a pre-existing A8
    # characteristic, not something A9 changes -- see contract.py's own
    # BusinessResult docstring), which is not JSON-serializable by plain
    # json.dumps. repr() over the full response dataclass tree is a strictly
    # broader net for a credential-leak scan than JSON serialization would be
    # anyway, since it also covers any non-JSON-safe field.
    assert secret not in repr(response)
    assert secret not in repr(response.business_result)
    assert secret not in repr(response.receipts)

    for envelope in read_receipts(directory):
        assert secret not in json.dumps(envelope)


async def test_credential_provider_failure_is_admitted_exception_not_remote_unavailable(
    tmp_path: Path,
) -> None:
    async def failing_provider(context: TrustedOutboundContext) -> RemoteCredential:
        raise RuntimeError("credential-backend-unreachable")

    connector = RemoteToolConnector(
        {
            "bossy:test": RemoteTargetConfig(
                handle="bossy:test",
                endpoint_uri="https://bossy.example.com/mcp",
                credential_provider=failing_provider,
            )
        }
    )
    config, _identity, _directory = _build_config(tmp_path, connector=connector)
    request = _resolved_request(arguments={"x": "hi"})

    response = await execute_governed_call(request, arguments={"x": "hi"}, config=config)

    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "exception"
    # Not remote_unavailable: no connection was ever attempted, so this must
    # not claim the remote target was contacted and failed.
    assert response.diagnostic_code == "remote_exception"


# --------------------------------------------------------------------------- #
# Receipt handles, ordering, and no signer/key/path leakage                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_receipt_handles_are_ordered_admission_then_outcome_and_carry_no_location(
    tmp_path: Path, binding_version: str, loopback_mcp_server: LoopbackMcpServer
) -> None:
    connector = _remote_connector(loopback_mcp_server.base_url)
    config, _identity, _directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(arguments={"x": "hi"})

    response = await execute_governed_call(request, arguments={"x": "hi"}, config=config)

    assert [handle.receipt_kind for handle in response.receipts] == ["admission", "outcome"]
    for handle in response.receipts:
        assert handle.location_handle is None


# --------------------------------------------------------------------------- #
# Concurrency isolation through execute_governed_call                        #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_concurrent_governed_calls_do_not_mix_credentials_or_results(
    tmp_path: Path, binding_version: str, loopback_mcp_server: LoopbackMcpServer
) -> None:
    async def provider_a(context: TrustedOutboundContext) -> RemoteCredential:
        return RemoteCredential(headers={"Authorization": "Bearer concurrent-a"})

    async def provider_b(context: TrustedOutboundContext) -> RemoteCredential:
        return RemoteCredential(headers={"Authorization": "Bearer concurrent-b"})

    connector = RemoteToolConnector(
        {
            "bossy:a": RemoteTargetConfig(
                handle="bossy:a",
                endpoint_uri=loopback_mcp_server.base_url,
                allow_insecure_loopback=True,
                timeout_seconds=5.0,
                credential_provider=provider_a,
            ),
            "bossy:b": RemoteTargetConfig(
                handle="bossy:b",
                endpoint_uri=loopback_mcp_server.base_url,
                allow_insecure_loopback=True,
                timeout_seconds=5.0,
                credential_provider=provider_b,
            ),
        }
    )
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request_a = _resolved_request(
        target="bossy:a",
        tool="observed_headers",
        arguments={},
        request_ref="req:a",
        actor_ref="actor:test:a",
    )
    request_b = _resolved_request(
        target="bossy:b",
        tool="observed_headers",
        arguments={},
        request_ref="req:b",
        actor_ref="actor:test:b",
    )

    response_a, response_b = await asyncio.gather(
        execute_governed_call(request_a, arguments={}, config=config),
        execute_governed_call(request_b, arguments={}, config=config),
    )

    headers_a = json.loads(response_a.business_result.payload.content[0].text)
    headers_b = json.loads(response_b.business_result.payload.content[0].text)
    assert headers_a["authorization"] == "Bearer concurrent-a"
    assert headers_b["authorization"] == "Bearer concurrent-b"
    assert response_a.request_ref == "req:a"
    assert response_b.request_ref == "req:b"
    assert response_a.receipts != response_b.receipts


# --------------------------------------------------------------------------- #
# No retry / idempotency surface; one remote call per governed invocation    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_exactly_one_remote_call_is_made_per_governed_invocation(
    tmp_path: Path,
    binding_version: str,
    loopback_mcp_server: LoopbackMcpServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dagr_mcp_service.connectors.remote as remote_module

    call_count = {"n": 0}
    original = remote_module._call_remote_tool

    async def _counted(*args: Any, **kwargs: Any) -> Any:
        call_count["n"] += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(remote_module, "_call_remote_tool", _counted)

    connector = _remote_connector(loopback_mcp_server.base_url)
    config, _identity, _directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(arguments={"x": "hi"})

    await execute_governed_call(request, arguments={"x": "hi"}, config=config)

    assert call_count["n"] == 1


def test_no_retry_idempotency_or_dedup_names_appear_on_the_remote_connector_module() -> None:
    import dagr_mcp_service.connectors.remote as remote_module

    public_names = [name for name in dir(remote_module) if not name.startswith("_")]
    for name in public_names:
        lowered = name.lower()
        assert "idempot" not in lowered
        assert "dedup" not in lowered
        assert "exactly_once" not in lowered
        assert "replay" not in lowered
        assert "retry" not in lowered


def test_no_public_host_route_subprocess_or_queue_api_exists_on_remote_module() -> None:
    import dagr_mcp_service.connectors.remote as remote_module

    source = inspect.getsource(remote_module)
    for forbidden in (
        "/call",
        "add_route",
        "APIRouter",
        "Popen",
        "create_subprocess",
        "Queue(",
        "celery",
    ):
        assert forbidden not in source
