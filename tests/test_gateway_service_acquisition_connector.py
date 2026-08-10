"""DAGR-MCP-SOURCE0 — the EXTERNAL acquisition MCP surface (ACQ-MCP0), governed
through this repository's *existing* stdio connector, lifecycle bindings, and
``execute_governed_call`` composition, end to end.

Proves the smallest composition: the acquisition surface is pinned by
protocol/commit (:mod:`dagr_mcp_service.acquisition_connector`) and driven as an
unmodified external MCP stdio server via
:class:`dagr_mcp_service.connectors.stdio.StdioToolConnector` — no acquisition
implementation is imported, no new authority is invented, and the DAGR receipts
emitted are this repository's *own* admission/outcome receipts (never relabeled
editorial ``source_capture`` receipts, never an ``arcs-verify`` verdict).

Hermetic: a local fake external acquisition MCP child
(``tests/_acquisition_fake_mcp_child.py``) stands in for the real
``counterpedia-acquisition`` server. No network, no model, no API key.

Covers the required proof surface:

* an ADMITTED call reaches the external child EXACTLY once and emits DAGR
  admission + outcome receipts;
* a REFUSED / DEFERRED call reaches the child ZERO times and still produces
  admission evidence;
* an unknown (unpinned) tool and a changed-args / digest mismatch both fail
  closed before any child is spawned (the argument-digest binding the existing
  boundary supports; content-dedup idempotency is explicitly out of scope);
* a tool error / timeout / cancellation preserves outcome UNCERTAINTY (never a
  fabricated success, never ``remote_unavailable`` after the call was forwarded);
* emitted receipts stay metadata-only (``retention_class_applied=hash_only``,
  no raw arguments/results/env secrets);
* the governed result is never treated as verification — a returned proposal
  stays a proposal (``is_proposal`` true), no verifier verdict is emitted;
* no producer/verifier ownership crossing — importing the connector module
  imports neither ``counterpedia_acquisition`` nor ``arcs_verify``.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("fastmcp")
pytest.importorskip("mcp")

from dagr_mcp.sdk_spine import InMemoryReviewObjectSink
from dagr_mcp.srs_receipts import RawEnvelopeFileSink, SigningIdentity, sha256_digest
from dagr_mcp_service.acquisition_connector import (
    ACQUISITION_TOOL_CAPTURE_URL,
    ACQUISITION_TOOL_NAMES,
    ACQUISITION_TOOL_PROCESS_SOURCE,
    DEFAULT_ACQUISITION_TARGET_HANDLE,
    acquisition_stdio_target,
    build_acquisition_connector,
)
from dagr_mcp_service.adapter import GatewayAdapterConfig, execute_governed_call
from dagr_mcp_service.connectors.stdio import StdioToolConnector
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

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
ACQ_FIXTURE = str(ROOT / "tests" / "_acquisition_fake_mcp_child.py")
BOTH_BINDINGS = (FASTMCP_BINDING_VERSION, SDK_BINDING_VERSION)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
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
    target: str = DEFAULT_ACQUISITION_TARGET_HANDLE,
    tool: str = ACQUISITION_TOOL_PROCESS_SOURCE,
    arguments: dict[str, Any],
    argument_digest: str | None = None,
    policy_profile_ref: str = "policy-profile:default",
    request_ref: str = "req:acq:1",
) -> CallerGovernedCallRequest:
    return CallerGovernedCallRequest(
        request_ref=request_ref,
        binding_selector=BindingSelectorKey(key=selector),
        target_server_ref=TargetServerRef(handle=target),
        tool_name=tool,
        argument_digest=argument_digest if argument_digest is not None else _digest(arguments),
        policy_profile_ref=policy_profile_ref,
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
    sink = RawEnvelopeFileSink(directory)
    identity = SigningIdentity.generate(
        issuer_id="issuer:test:acq-gateway", key_id="issuer.test.acq-gateway/key/1"
    )
    binding_registry = overrides.pop("binding_registry", {selector: binding_version})
    config = GatewayAdapterConfig(
        binding_registry=binding_registry,
        connector=connector,
        identity=identity,
        sink=sink,
        runtime_instance_id="runtime:test:acq-gateway",
        boundary_id="boundary:test:acq-gateway",
        policy_pack_id="policy:test:acq-gateway",
        policy_pack_version="2026.08.10",
        **overrides,
    )
    return config, identity, directory


def _connector(
    *, timeout_seconds: float = 10.0, env: dict[str, str] | None = None
) -> StdioToolConnector:
    return build_acquisition_connector(
        (PY, ACQ_FIXTURE), env=env, timeout_seconds=timeout_seconds
    )


def _refuse_resolver(reason_code: str = "policy_refused") -> Any:
    def policy_resolver(_snapshot: Any, _actor: Any) -> Any:
        return SimpleNamespace(
            disposition="refused",
            tool_class="read",
            reason_code=reason_code,
            parent_receipt_ref=None,
            additional_attestation_limits=(),
        )

    return policy_resolver


def _defer_resolver() -> Any:
    def policy_resolver(_snapshot: Any, _actor: Any) -> Any:
        return SimpleNamespace(
            disposition="deferred_for_review",
            tool_class="write",
            reason_code=None,
            parent_receipt_ref=None,
            additional_attestation_limits=(),
        )

    return policy_resolver


# --------------------------------------------------------------------------- #
# Registration / pin sanity                                                    #
# --------------------------------------------------------------------------- #


def test_pinned_target_exposes_exactly_the_four_acquisition_tools() -> None:
    target = acquisition_stdio_target((PY, ACQ_FIXTURE))
    assert target.handle == DEFAULT_ACQUISITION_TARGET_HANDLE
    assert target.known_tools == frozenset(ACQUISITION_TOOL_NAMES)
    assert set(ACQUISITION_TOOL_NAMES) == {
        "acquisition.capture_url",
        "acquisition.process_source",
        "acquisition.compare_captures",
        "acquisition.process_browser_observation",
    }


# --------------------------------------------------------------------------- #
# ADMITTED call reaches the external child EXACTLY once                         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_admitted_call_reaches_the_external_surface_exactly_once(
    tmp_path: Path, binding_version: str
) -> None:
    call_log = tmp_path / "call-log.txt"
    connector = _connector(env={"DAGR_ACQ_CALL_LOG": str(call_log)})
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    args = {"input_locator": "https://example.test/article"}
    request = _resolved_request(arguments=args)

    response = await execute_governed_call(request, arguments=args, config=config)

    # Governed: admitted, and the DAGR admission + outcome receipts both emitted.
    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "result"
    assert len(response.receipts) == 2
    assert [r.receipt_kind for r in response.receipts] == ["admission", "outcome"]

    # Delivered to the external surface EXACTLY once.
    assert call_log.read_text(encoding="utf-8").splitlines() == [
        "process_source:https://example.test/article"
    ]

    receipts = read_receipts(directory)
    assert len(receipts) == 2
    assert receipts[0]["receipt_kind"] == "admission"
    assert receipts[0]["disposition"] == "admitted"
    assert receipts[1]["receipt_kind"] == "outcome"


async def test_admitted_capture_url_reaches_the_surface_exactly_once(tmp_path: Path) -> None:
    call_log = tmp_path / "call-log.txt"
    connector = _connector(env={"DAGR_ACQ_CALL_LOG": str(call_log)})
    config, _identity, _directory = _build_config(tmp_path, connector=connector)
    args = {"url": "https://example.test/x"}
    request = _resolved_request(tool=ACQUISITION_TOOL_CAPTURE_URL, arguments=args)

    response = await execute_governed_call(request, arguments=args, config=config)

    assert response.decision.disposition == "admitted"
    assert call_log.read_text(encoding="utf-8").splitlines() == ["capture_url:https://example.test/x"]


# --------------------------------------------------------------------------- #
# The governed result is never treated as verification / a proposal stays one   #
# --------------------------------------------------------------------------- #


def _payload_text(payload: Any) -> str:
    """Best-effort string view of a returned tool result, for content assertions."""
    for attr in ("structuredContent", "content"):
        value = getattr(payload, attr, None)
        if value is not None:
            try:
                return json.dumps(value, default=str)
            except TypeError:
                return str(value)
    return str(payload)


async def test_returned_proposal_is_not_promoted_and_no_verdict_is_conferred(
    tmp_path: Path,
) -> None:
    connector = _connector()
    config, _identity, _directory = _build_config(tmp_path, connector=connector)
    args = {"input_locator": "https://example.test/article"}
    request = _resolved_request(arguments=args)

    response = await execute_governed_call(request, arguments=args, config=config)

    # The boundary records a *governance* disposition ("admitted"), never a
    # verification/approval verdict; GovernedCallResponse carries no verdict field.
    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "result"
    assert not hasattr(response, "verdict")
    assert not hasattr(response.decision, "verified")

    # The proposal artifact comes back through the governed response WITHOUT
    # being promoted: is_proposal stays true, and its source_capture eligibility
    # stays a producer-fact hint — the governed call confers no admission/standing.
    text = _payload_text(response.business_result.payload)
    assert "is_proposal" in text
    assert "proposal:fake:0001" in text
    assert response.business_result.result_kind == "result"


# --------------------------------------------------------------------------- #
# REFUSED / DEFERRED calls reach the external child ZERO times                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_refused_call_reaches_the_surface_zero_times(
    tmp_path: Path, binding_version: str
) -> None:
    call_log = tmp_path / "call-log.txt"
    connector = _connector(env={"DAGR_ACQ_CALL_LOG": str(call_log)})
    config, _identity, directory = _build_config(
        tmp_path,
        connector=connector,
        binding_version=binding_version,
        policy_resolver=_refuse_resolver(),
    )
    args = {"input_locator": "https://example.test/should-not-run"}
    request = _resolved_request(arguments=args)

    response = await execute_governed_call(request, arguments=args, config=config)

    assert response.decision.disposition == "refused"
    assert response.diagnostic_code == "policy_refused"
    assert response.business_result is None
    assert len(response.receipts) == 1
    assert response.receipts[0].receipt_kind == "admission"

    receipts = read_receipts(directory)
    assert len(receipts) == 1
    assert receipts[0]["disposition"] == "refused"
    # ZERO downstream calls: the external child was never spawned.
    assert not call_log.exists()


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_deferred_call_reaches_the_surface_zero_times(
    tmp_path: Path, binding_version: str
) -> None:
    call_log = tmp_path / "call-log.txt"
    connector = _connector(env={"DAGR_ACQ_CALL_LOG": str(call_log)})
    config, _identity, directory = _build_config(
        tmp_path,
        connector=connector,
        binding_version=binding_version,
        policy_resolver=_defer_resolver(),
        review_object_creator=InMemoryReviewObjectSink(),
    )
    args = {"input_locator": "https://example.test/should-not-run"}
    request = _resolved_request(arguments=args)

    response = await execute_governed_call(request, arguments=args, config=config)

    assert response.decision.disposition == "deferred"
    assert response.diagnostic_code == "deferred_for_review"
    assert response.review_object_ref is not None
    assert response.business_result is None
    assert len(response.receipts) == 1

    receipts = read_receipts(directory)
    assert len(receipts) == 1
    assert receipts[0]["disposition"] == "deferred_for_review"
    assert not call_log.exists()


async def test_unknown_tool_refuses_before_any_child_is_spawned(tmp_path: Path) -> None:
    call_log = tmp_path / "call-log.txt"
    # A tool name outside the pinned acquisition set is not in known_tools.
    connector = build_acquisition_connector(
        (PY, ACQ_FIXTURE), env={"DAGR_ACQ_CALL_LOG": str(call_log)}
    )
    config, _identity, directory = _build_config(tmp_path, connector=connector)
    args = {"x": 1}
    request = _resolved_request(tool="acquisition.not_a_real_tool", arguments=args)

    response = await execute_governed_call(request, arguments=args, config=config)

    assert response.decision.disposition == "refused"
    assert response.diagnostic_code == "unknown_tool_fail_closed"
    # Pre-admission connector refusal: no child, no receipts.
    assert response.receipts == ()
    assert read_receipts(directory) == []
    assert not call_log.exists()


# --------------------------------------------------------------------------- #
# Changed args / digest mismatch: fail closed before any child is spawned       #
# (argument-digest binding the existing boundary supports; content-dedup        #
#  idempotency is explicitly out of scope — see dagr_mcp_service __init__)       #
# --------------------------------------------------------------------------- #


async def test_changed_arguments_against_a_stale_digest_fails_closed(tmp_path: Path) -> None:
    call_log = tmp_path / "call-log.txt"
    connector = _connector(env={"DAGR_ACQ_CALL_LOG": str(call_log)})
    config, _identity, directory = _build_config(tmp_path, connector=connector)

    committed_args = {"input_locator": "https://example.test/committed"}
    # The request commits to the digest of committed_args...
    request = _resolved_request(arguments=committed_args)
    # ...but a *different* argument mapping is presented at execution time.
    tampered_args = {"input_locator": "https://example.test/tampered"}

    response = await execute_governed_call(request, arguments=tampered_args, config=config)

    assert response.decision.disposition == "refused"
    assert response.diagnostic_code == "malformed_request"
    # The digest binding stops it before the binding, receipts, or any child.
    assert response.receipts == ()
    assert read_receipts(directory) == []
    assert not call_log.exists()


# --------------------------------------------------------------------------- #
# Outcome UNCERTAINTY preserved on error / timeout / cancellation                #
# (never coerced to success/PASS, never claimed non-delivery after forwarding)   #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_tool_error_is_an_admitted_error_not_a_success(
    tmp_path: Path, binding_version: str
) -> None:
    # A tool that raises inside the external MCP server returns an MCP error
    # *result* (isError=True) over the protocol — the call completed, with an
    # error. The boundary faithfully records that as outcome="error", never
    # coerced to a success/result.
    connector = _connector(env={"DAGR_ACQ_FIXTURE": "error"})
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    args = {"input_locator": "https://example.test/boom"}
    request = _resolved_request(arguments=args)

    response = await execute_governed_call(request, arguments=args, config=config)

    # Admission happened; the outcome is an honest error, never a fake success.
    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "error"
    assert response.decision.outcome != "result"
    assert response.business_result is not None
    assert response.business_result.result_kind == "error"
    assert len(response.receipts) == 2
    receipts = read_receipts(directory)
    assert receipts[1]["outcome"] == "error_returned"


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_timeout_after_forwarding_preserves_uncertainty(
    tmp_path: Path, binding_version: str
) -> None:
    side_effect_log = tmp_path / "side-effect.txt"
    connector = _connector(
        env={"DAGR_ACQ_FIXTURE": "hang", "DAGR_ACQ_SIDE_EFFECT_LOG": str(side_effect_log)},
        timeout_seconds=1.5,
    )
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    args = {"input_locator": "https://example.test/hang"}
    request = _resolved_request(arguments=args)

    response = await execute_governed_call(request, arguments=args, config=config)

    # The side effect really, durably happened on the external surface.
    assert side_effect_log.read_text(encoding="utf-8").splitlines() == ["side-effect-performed"]

    # And the governed outcome preserves uncertainty: admitted + exception, and
    # crucially NOT remote_unavailable (which would falsely claim non-delivery),
    # and NOT coerced to a result/success.
    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "exception"
    assert response.diagnostic_code == "remote_exception"
    assert response.diagnostic_code != "remote_unavailable"
    assert response.decision.disposition != "refused"
    receipts = read_receipts(directory)
    assert len(receipts) == 2
    assert receipts[1]["outcome"] == "exception"


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_cancellation_after_forwarding_records_execution_state_unknown(
    tmp_path: Path, binding_version: str
) -> None:
    side_effect_log = tmp_path / "side-effect.txt"
    connector = _connector(
        env={"DAGR_ACQ_FIXTURE": "hang", "DAGR_ACQ_SIDE_EFFECT_LOG": str(side_effect_log)},
        timeout_seconds=60.0,
    )
    config, _identity, _directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    args = {"input_locator": "https://example.test/hang"}
    request = _resolved_request(arguments=args)

    task = asyncio.ensure_future(
        execute_governed_call(request, arguments=args, config=config)
    )
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline and not side_effect_log.exists():
        await asyncio.sleep(0.05)
    assert side_effect_log.exists(), "child never reached the side effect; test setup is invalid"

    task.cancel()
    response = await task

    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "cancellation"
    assert response.diagnostic_code == "cancelled"
    assert response.cancellation_facts is not None
    assert response.cancellation_facts.request_cancelled is True
    # The vocabulary's own words for "we do not know whether it ran".
    assert response.cancellation_facts.execution_state_unknown is True
    assert response.cancellation_facts.delivery_incomplete is True


async def test_spawn_failure_is_remote_unavailable_only_pre_forward(tmp_path: Path) -> None:
    # A target whose command cannot be spawned at all: nothing was ever
    # forwarded, so remote_unavailable is the grounded, honest diagnostic.
    connector = build_acquisition_connector(("/nonexistent/absolute/path/to/acq-server",))
    config, _identity, _directory = _build_config(tmp_path, connector=connector)
    args = {"input_locator": "https://example.test/x"}
    request = _resolved_request(arguments=args)

    response = await execute_governed_call(request, arguments=args, config=config)

    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "exception"
    assert response.diagnostic_code == "remote_unavailable"


# --------------------------------------------------------------------------- #
# Receipt limits: metadata-only, hash refs, no raw content / env secrets        #
# --------------------------------------------------------------------------- #


async def test_emitted_receipts_are_metadata_only_hash_only(tmp_path: Path) -> None:
    connector = _connector()
    config, _identity, directory = _build_config(tmp_path, connector=connector)
    args = {"input_locator": "https://example.test/article"}
    request = _resolved_request(arguments=args)

    response = await execute_governed_call(request, arguments=args, config=config)
    assert response.decision.disposition == "admitted"

    receipts = read_receipts(directory)
    assert receipts
    for receipt in receipts:
        assert receipt["retention_class_applied"] == "hash_only"
        # Metadata-only: no raw-content keys leak onto the envelope.
        for forbidden in ("arguments", "tool_arguments", "raw_payload", "result_body", "prompt_text"):
            assert forbidden not in receipt


async def test_no_raw_arguments_results_or_env_secrets_in_receipts(tmp_path: Path) -> None:
    distinctive_argument = "raw-locator-must-not-be-receipted-9f2c"
    distinctive_secret = "sk-acq-operator-secret-must-not-be-receipted-7a1e"
    connector = _connector(env={"DAGR_ACQ_OPERATOR_SECRET": distinctive_secret})
    config, _identity, directory = _build_config(tmp_path, connector=connector)
    args = {"input_locator": distinctive_argument}
    request = _resolved_request(arguments=args)

    response = await execute_governed_call(request, arguments=args, config=config)
    assert response.decision.disposition == "admitted"

    raw_text = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(directory.glob("*.json"))
    )
    assert distinctive_argument not in raw_text
    assert distinctive_secret not in raw_text
    assert "DAGR_ACQ_OPERATOR_SECRET" not in raw_text


# --------------------------------------------------------------------------- #
# No producer/verifier ownership crossing                                       #
# --------------------------------------------------------------------------- #


def test_connector_module_imports_no_verifier_and_no_acquisition_producer() -> None:
    """Importing the pin/registration module must pull in neither the external
    acquisition producer (``counterpedia_acquisition``) nor the sibling verifier
    (``arcs_verify``). Proven in a fresh interpreter so this session's already
    imported modules cannot mask a real import.
    """

    completed = subprocess.run(
        [
            PY,
            "-c",
            (
                "import sys\n"
                "import dagr_mcp_service.acquisition_connector\n"
                "forbidden = ('counterpedia_acquisition', 'arcs_verify')\n"
                "leaked = sorted(\n"
                "    name for name in sys.modules\n"
                "    if any(name == p or name.startswith(p + '.') for p in forbidden)\n"
                ")\n"
                "assert not leaked, 'forbidden modules imported: ' + ', '.join(leaked)\n"
                "print('OK')\n"
            ),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().endswith("OK")


def test_connector_module_source_contains_no_forbidden_imports() -> None:
    source = (
        ROOT / "dagr_mcp_service" / "acquisition_connector.py"
    ).read_text(encoding="utf-8")
    assert "import counterpedia_acquisition" not in source
    assert "from counterpedia_acquisition" not in source
    assert "import arcs_verify" not in source
    assert "from arcs_verify" not in source
