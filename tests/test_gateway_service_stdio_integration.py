"""The stdio child-process connector, driven through
``dagr_mcp_service.adapter.execute_governed_call``, end to end.

Proves the stdio connector composes with the unmodified A7 contract, the
unmodified lifecycle bindings, and the A8 adapter exactly the way the memory
and remote connectors already do -- no adapter change was needed to support
it. Driven against two real child-process fixtures: a well-behaved FastMCP
stdio server (``tests/_stdio_fake_mcp_child.py``) and a hand-rolled
misbehaving raw JSON-RPC child (``tests/_stdio_raw_fake_mcp_child.py``).

Covers the required proof surface: an ADMITTED call reaches the child
exactly once; a REFUSED call produces evidence and reaches the child zero
times; a DEFERRED call produces evidence and reaches the child zero times;
mutating an emitted receipt fails independent verification; no raw protected
content (arguments, results, or operator env secrets) appears in emitted
receipts; and the connector's own deterministic failure postures (timeout,
child crash) surface as the correct, distinct governed outcome, never
conflated with a policy refusal. See
``docs/GATEWAY_SERVICE_ADAPTER_SCOPE.md`` §3/§4/§6/§8/§9/§10/§12.
"""

from __future__ import annotations

import asyncio
import copy
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.exceptions import InvalidSignature

pytest.importorskip("fastmcp")
pytest.importorskip("mcp")

from dagr_mcp.sdk_spine import InMemoryReviewObjectSink
from dagr_mcp.srs_receipts import RawEnvelopeFileSink, SigningIdentity, sha256_digest
from dagr_mcp_service.adapter import GatewayAdapterConfig, execute_governed_call
from dagr_mcp_service.connectors.stdio import StdioTargetConfig, StdioToolConnector
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
FASTMCP_FIXTURE = str(ROOT / "tests" / "_stdio_fake_mcp_child.py")
RAW_FIXTURE = str(ROOT / "tests" / "_stdio_raw_fake_mcp_child.py")
BOTH_BINDINGS = (FASTMCP_BINDING_VERSION, SDK_BINDING_VERSION)


# --------------------------------------------------------------------------- #
# Helpers (mirrors tests/test_gateway_service_adapter.py's conventions)      #
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
    target: str = "local:fixture",
    tool: str = "echo",
    arguments: dict[str, Any],
    policy_profile_ref: str = "policy-profile:default",
    request_ref: str = "req:1",
) -> CallerGovernedCallRequest:
    return CallerGovernedCallRequest(
        request_ref=request_ref,
        binding_selector=BindingSelectorKey(key=selector),
        target_server_ref=TargetServerRef(handle=target),
        tool_name=tool,
        argument_digest=_digest(arguments),
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
        issuer_id="issuer:test:stdio-gateway", key_id="issuer.test.stdio-gateway/key/1"
    )
    binding_registry = overrides.pop("binding_registry", {selector: binding_version})
    config = GatewayAdapterConfig(
        binding_registry=binding_registry,
        connector=connector,
        identity=identity,
        sink=sink,
        runtime_instance_id="runtime:test:stdio-gateway",
        boundary_id="boundary:test:stdio-gateway",
        policy_pack_id="policy:test:stdio-gateway",
        policy_pack_version="2026.08.03",
        **overrides,
    )
    return config, identity, directory


def _fixture_connector(*, timeout_seconds: float = 10.0, env: dict[str, str] | None = None) -> StdioToolConnector:
    return StdioToolConnector(
        {
            "local:fixture": StdioTargetConfig(
                handle="local:fixture",
                command=(PY, FASTMCP_FIXTURE),
                known_tools=frozenset({"echo", "boom", "observed_env"}),
                env=dict(env) if env else {},
                timeout_seconds=timeout_seconds,
            )
        }
    )


# --------------------------------------------------------------------------- #
# 2 — ADMITTED call reaches the child exactly once                           #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_admitted_call_is_forwarded_to_the_child_exactly_once(
    tmp_path: Path, binding_version: str
) -> None:
    log_path = tmp_path / "call-log.txt"
    connector = _fixture_connector(env={"DAGR_STDIO_FIXTURE_CALL_LOG": str(log_path)})
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(arguments={"x": "once"})

    response = await execute_governed_call(request, arguments={"x": "once"}, config=config)

    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "result"
    assert len(response.receipts) == 2
    assert log_path.read_text(encoding="utf-8").splitlines() == ["echo:once"]


# --------------------------------------------------------------------------- #
# 3/4 — REFUSED and DEFERRED calls produce evidence and never reach the child #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_refused_call_produces_evidence_and_never_reaches_the_child(
    tmp_path: Path, binding_version: str
) -> None:
    log_path = tmp_path / "call-log.txt"
    connector = _fixture_connector(env={"DAGR_STDIO_FIXTURE_CALL_LOG": str(log_path)})

    def policy_resolver(_snapshot: Any, _actor: Any) -> Any:
        return SimpleNamespace(
            disposition="refused",
            tool_class="read",
            reason_code="policy_refused",
            parent_receipt_ref=None,
            additional_attestation_limits=(),
        )

    config, _identity, directory = _build_config(
        tmp_path,
        connector=connector,
        binding_version=binding_version,
        policy_resolver=policy_resolver,
    )
    request = _resolved_request(arguments={"x": "should-not-run"})

    response = await execute_governed_call(
        request, arguments={"x": "should-not-run"}, config=config
    )

    assert response.decision.disposition == "refused"
    assert response.diagnostic_code == "policy_refused"
    assert response.business_result is None
    assert len(response.receipts) == 1
    assert response.receipts[0].receipt_kind == "admission"
    receipts = read_receipts(directory)
    assert len(receipts) == 1
    assert receipts[0]["disposition"] == "refused"
    assert not log_path.exists()


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_deferred_call_produces_evidence_and_never_reaches_the_child(
    tmp_path: Path, binding_version: str
) -> None:
    log_path = tmp_path / "call-log.txt"
    connector = _fixture_connector(env={"DAGR_STDIO_FIXTURE_CALL_LOG": str(log_path)})

    def policy_resolver(_snapshot: Any, _actor: Any) -> Any:
        return SimpleNamespace(
            disposition="deferred_for_review",
            tool_class="write",
            reason_code=None,
            parent_receipt_ref=None,
            additional_attestation_limits=(),
        )

    review_sink = InMemoryReviewObjectSink()
    config, _identity, directory = _build_config(
        tmp_path,
        connector=connector,
        binding_version=binding_version,
        policy_resolver=policy_resolver,
        review_object_creator=review_sink,
    )
    request = _resolved_request(arguments={"x": "should-not-run"})

    response = await execute_governed_call(
        request, arguments={"x": "should-not-run"}, config=config
    )

    assert response.decision.disposition == "deferred"
    assert response.diagnostic_code == "deferred_for_review"
    assert response.retry_instruction == "retry_after_approval"
    assert response.review_object_ref is not None
    assert response.business_result is None
    assert len(response.receipts) == 1
    receipts = read_receipts(directory)
    assert len(receipts) == 1
    assert receipts[0]["disposition"] == "deferred_for_review"
    assert not log_path.exists()


async def test_unknown_tool_refuses_before_any_child_process_exists(tmp_path: Path) -> None:
    log_path = tmp_path / "call-log.txt"
    connector = StdioToolConnector(
        {
            "local:fixture": StdioTargetConfig(
                handle="local:fixture",
                command=(PY, FASTMCP_FIXTURE),
                known_tools=frozenset({"echo"}),  # "no-such-tool" is deliberately absent
                env={"DAGR_STDIO_FIXTURE_CALL_LOG": str(log_path)},
            )
        }
    )
    config, _identity, directory = _build_config(tmp_path, connector=connector)
    request = _resolved_request(arguments={"x": 1}, tool="no-such-tool")

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision.disposition == "refused"
    assert response.diagnostic_code == "unknown_tool_fail_closed"
    assert not log_path.exists()
    # Target/tool resolution happens before the binding (and its policy
    # engine) ever runs, so this is a pre-admission refusal that never
    # reaches the neutral core at all -- no admission receipt is emitted for
    # it, matching the identical unknown-tool behavior the memory connector
    # already has (dagr_mcp_service.adapter.execute_governed_call returns
    # immediately once connector.resolve() itself refuses).
    assert response.receipts == ()
    assert read_receipts(directory) == []


# --------------------------------------------------------------------------- #
# 5 — mutation of emitted evidence fails independent verification            #
# --------------------------------------------------------------------------- #


async def _run_admitted_call_and_capture_receipts(
    tmp_path: Path,
) -> tuple[list[dict[str, Any]], SigningIdentity]:
    connector = _fixture_connector()
    config, identity, directory = _build_config(tmp_path, connector=connector)
    request = _resolved_request(arguments={"x": "verify-me"})

    response = await execute_governed_call(request, arguments={"x": "verify-me"}, config=config)
    assert response.decision.disposition == "admitted"

    receipts = read_receipts(directory)
    assert receipts
    return receipts, identity


async def test_mutated_receipt_fails_independent_verification_unmutated_passes(
    tmp_path: Path,
) -> None:
    """CI-enforced: uses only this repository's own bundled schema and
    test-only verifier (``tests/receipt_verification.py``), exactly like
    ``test_gateway_service_receipt_access.py``'s companion test for the A10
    access seam. ``arcs-verify`` is a separate, sibling project not installed
    in this repository's own CI; the best-effort cross-check against the
    real package is a separate, ``importorskip``-guarded test below.
    """

    receipts, identity = await _run_admitted_call_and_capture_receipts(tmp_path)

    from tests.receipt_verification import verify_receipt as verify_with_bundled_schema

    schema_path = ROOT / "dagr_mcp" / "vendor" / "srs" / "srs-envelope-v0.2.0.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    bundle = dict(identity.trust_bundle())

    for receipt in receipts:
        # The genuine, untouched envelope verifies cleanly.
        verify_with_bundled_schema(dict(receipt), bundle, schema)

        # A single-field mutation invalidates the deterministic signature,
        # exactly as the existing behavioral-freeze suite already proves for
        # the FastMCP binding's own receipts (tests/test_behavioral_freeze.py
        # ``test_freeze_signature_covers_every_field``) -- this proves the
        # identical claim for a receipt produced through the stdio connector.
        tampered = copy.deepcopy(receipt)
        tampered["logical_call_id"] = "urn:tampered:not-the-real-call"
        with pytest.raises(InvalidSignature):
            verify_with_bundled_schema(dict(tampered), bundle, schema)


STDIO_ARCS_PROFILE = "srs.mcp.sdk_enforcement.v0.1"


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_stdio_receipts_verify_under_the_independent_arcs_verifier(
    tmp_path: Path, binding_version: str
) -> None:
    """The lane-closing proof, against the real, separately-installed
    ``arcs-verify`` package -- a verifier this repository does not own and
    cannot influence at run time.

    Proves, for receipts produced through the stdio connector:

    1. the genuine admission *and* outcome receipts both pass;
    2. a one-field mutation fails;
    3. the applicable pinned profile is the one the verifier used, and it is
       the profile the receipts themselves declare (not a caller-chosen label
       the verifier merely echoed);
    4. the trust bundle is load-bearing -- a foreign bundle fails the same,
       untouched receipt.

    Import isolation (the producer is never in the verifier's process) is
    proven separately, in a fresh interpreter, by
    ``test_importing_arcs_verify_does_not_import_dagr_mcp_producer_modules``.
    """

    arcs_verify = pytest.importorskip("arcs_verify")
    from arcs_verify.verifier import PROFILE_IDENTITIES
    from arcs_verify.verifier import verify_receipt as arcs_verify_receipt

    connector = _fixture_connector()
    config, identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(arguments={"x": "verify-me"})

    response = await execute_governed_call(request, arguments={"x": "verify-me"}, config=config)
    assert response.decision.disposition == "admitted"

    receipts = read_receipts(directory)
    bundle = dict(identity.trust_bundle())

    # Both receipt classes of an admitted call are present and get verified --
    # not just whichever one happened to sort first.
    kinds = [receipt["receipt_kind"] for receipt in receipts]
    assert kinds == ["admission", "outcome"], kinds

    # The profile the verifier is told to apply is pinned by the verifier's own
    # identity table, and is the profile the emitted receipts declare. Without
    # this, `selected_profile` would be an unchecked caller assertion.
    pinned_profile_id, pinned_profile_version = PROFILE_IDENTITIES[STDIO_ARCS_PROFILE]

    arcs_schema_path = (
        Path(arcs_verify.__file__).resolve().parent / "data" / "srs-envelope-v0.2.0.schema.json"
    )
    for receipt in receipts:
        assert receipt["profile_id"] == pinned_profile_id
        assert receipt["profile_version"] == pinned_profile_version

        report = arcs_verify_receipt(
            dict(receipt),
            bundle,
            schema_path=arcs_schema_path,
            selected_profile=STDIO_ARCS_PROFILE,
        )
        assert report.passed, report.failure_codes

        # Each independently-checkable dimension actually ran and actually
        # passed -- `passed` alone would not distinguish "checked and clean"
        # from a future verifier that silently stopped checking.
        assert report.schema_digest
        assert report.envelope
        assert report.profile
        assert report.raw_content_exclusion
        assert report.signature_valid
        assert report.issuer_key_resolved
        assert report.issuer_key_trusted
        assert report.attestation_limits_present

        # (2) A single-field mutation is caught, and caught as a *signature*
        # failure -- the mutation stays schema- and profile-valid, so this
        # isolates the cryptographic binding rather than an incidental
        # structural complaint.
        tampered = copy.deepcopy(receipt)
        tampered["logical_call_id"] = "urn:tampered:not-the-real-call"
        tampered_report = arcs_verify_receipt(
            tampered,
            bundle,
            schema_path=arcs_schema_path,
            selected_profile=STDIO_ARCS_PROFILE,
        )
        assert not tampered_report.passed
        assert not tampered_report.signature_valid
        assert "signature_invalid" in tampered_report.failure_codes, (
            tampered_report.failure_codes
        )

        # (4) The trust bundle is load-bearing: a well-formed bundle for a
        # *different* issuer rejects this same untouched receipt.
        foreign_identity = SigningIdentity.generate(
            issuer_id="issuer:test:not-the-stdio-gateway",
            key_id="issuer.test.not-the-stdio-gateway/key/1",
        )
        foreign_report = arcs_verify_receipt(
            dict(receipt),
            dict(foreign_identity.trust_bundle()),
            schema_path=arcs_schema_path,
            selected_profile=STDIO_ARCS_PROFILE,
        )
        assert not foreign_report.passed
        assert not foreign_report.issuer_key_resolved
        assert "key_id_unresolved" in foreign_report.failure_codes, (
            foreign_report.failure_codes
        )


def test_importing_arcs_verify_does_not_import_dagr_mcp_producer_modules() -> None:
    """(3) The independent verifier is genuinely independent: importing
    ``arcs_verify`` pulls in none of this repository's producer packages, so a
    passing verification cannot be an artifact of producer code running inside
    the verifier's own process. Proven in a fresh interpreter, because this
    test session has every producer module imported already.
    """

    pytest.importorskip("arcs_verify")

    producer_packages = (
        "dagr_mcp",
        "dagr_mcp_service",
        "dagr_mcp_lifecycle",
        "dagr_mcp_sdk_binding",
        "dagr_mcp_continuation",
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys\n"
                "import arcs_verify\n"
                "import arcs_verify.verifier\n"
                f"producers = {producer_packages!r}\n"
                "leaked = sorted(\n"
                "    name\n"
                "    for name in sys.modules\n"
                "    if any(name == p or name.startswith(p + '.') for p in producers)\n"
                ")\n"
                "assert not leaked, 'producer modules imported by arcs_verify: ' "
                "+ ', '.join(leaked)\n"
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


# --------------------------------------------------------------------------- #
# 8 — no raw protected content in emitted receipts                           #
# --------------------------------------------------------------------------- #


async def test_no_raw_arguments_results_or_env_secrets_in_emitted_receipts(
    tmp_path: Path,
) -> None:
    distinctive_argument = "raw-argument-must-not-be-receipted-9f2c"
    distinctive_secret = "sk-operator-secret-must-not-be-receipted-7a1e"
    connector = _fixture_connector(env={"DAGR_STDIO_FIXTURE_SECRET": distinctive_secret})
    config, _identity, directory = _build_config(tmp_path, connector=connector)
    request = _resolved_request(arguments={"x": distinctive_argument})

    response = await execute_governed_call(
        request, arguments={"x": distinctive_argument}, config=config
    )
    assert response.decision.disposition == "admitted"

    raw_text = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(directory.glob("*.json"))
    )
    assert distinctive_argument not in raw_text
    assert distinctive_secret not in raw_text
    assert "DAGR_STDIO_FIXTURE_SECRET" not in raw_text


# --------------------------------------------------------------------------- #
# Failure postures compose correctly through the adapter, distinct from a    #
# policy refusal (decision status recorded separately from outcome status)   #
# --------------------------------------------------------------------------- #


def _raw_connector(mode: str, *, timeout_seconds: float = 2.0) -> StdioToolConnector:
    return StdioToolConnector(
        {
            "raw:fixture": StdioTargetConfig(
                handle="raw:fixture",
                command=(PY, RAW_FIXTURE, mode),
                known_tools=frozenset({"raw-echo"}),
                timeout_seconds=timeout_seconds,
            )
        }
    )


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_child_timeout_is_an_admitted_exception_not_a_policy_refusal(
    tmp_path: Path, binding_version: str
) -> None:
    connector = _raw_connector("hang_on_call", timeout_seconds=1.5)
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(arguments={"x": 1}, target="raw:fixture", tool="raw-echo")

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    # Admission still happened -- the tool was governed and dispatched; the
    # timeout is an *execution*-side fact, never mistaken for a policy
    # decision, exactly the separation the required behavior names.
    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "exception"
    assert len(response.receipts) == 2
    receipts = read_receipts(directory)
    assert receipts[0]["disposition"] == "admitted"
    assert receipts[1]["outcome"] == "exception"


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_child_crash_mid_call_is_an_admitted_exception_not_a_policy_refusal(
    tmp_path: Path, binding_version: str
) -> None:
    connector = _raw_connector("crash_after_accept", timeout_seconds=5.0)
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(arguments={"x": 1}, target="raw:fixture", tool="raw-echo")

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "exception"
    assert response.diagnostic_code == "remote_exception"
    assert len(response.receipts) == 2


async def test_spawn_unavailable_target_is_remote_unavailable_diagnostic(tmp_path: Path) -> None:
    connector = StdioToolConnector(
        {
            "raw:missing": StdioTargetConfig(
                handle="raw:missing",
                command=("/nonexistent/absolute/path/to/a/binary",),
                known_tools=frozenset({"raw-echo"}),
                timeout_seconds=5.0,
            )
        }
    )
    config, _identity, directory = _build_config(tmp_path, connector=connector)
    request = _resolved_request(arguments={"x": 1}, target="raw:missing", tool="raw-echo")

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "exception"
    assert response.diagnostic_code == "remote_unavailable"


# --------------------------------------------------------------------------- #
# Post-forward outcome semantics                                              #
#                                                                             #
# The pivotal boundary is whether the tools/call was written to the child's   #
# stdin. Before it, no side effect can have occurred. After it, the child may #
# have done the work and this connector may simply never learn the result.    #
# These tests make that distinction undeniable by having the child perform a  #
# real, durable, externally observable side effect and *then* fail.           #
# --------------------------------------------------------------------------- #


def _side_effect_connector(
    mode: str, side_effect_log: Path, *, timeout_seconds: float = 2.0
) -> StdioToolConnector:
    return StdioToolConnector(
        {
            "raw:fixture": StdioTargetConfig(
                handle="raw:fixture",
                command=(PY, RAW_FIXTURE, mode),
                known_tools=frozenset({"raw-echo"}),
                env={"DAGR_STDIO_RAW_SIDE_EFFECT_LOG": str(side_effect_log)},
                timeout_seconds=timeout_seconds,
            )
        }
    )


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
@pytest.mark.parametrize(
    "mode", ["side_effect_then_hang", "side_effect_then_crash", "side_effect_then_close"]
)
async def test_a_forwarded_call_whose_side_effect_really_happened_is_never_reported_as_prevented(
    tmp_path: Path, binding_version: str, mode: str
) -> None:
    """The load-bearing honesty test for this lane.

    The child performs the side effect, then hangs / crashes / closes without
    ever answering. The governed response must:

    * still say ``admitted`` -- the call was governed and dispatched;
    * carry ``outcome="exception"`` -- the result was not observed;
    * **never** carry ``remote_unavailable``, the one diagnostic that reads
      as "the call never reached the target".

    ``outcome="exception"`` here means "the transport or tool result was not
    successfully observed". It does not mean, and must never be read as
    meaning, that the side effect did not occur -- the side-effect log is
    standing proof that it did.
    """

    side_effect_log = tmp_path / "side-effect.txt"
    connector = _side_effect_connector(mode, side_effect_log)
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(arguments={"x": 1}, target="raw:fixture", tool="raw-echo")

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    # The side effect really, durably happened.
    assert side_effect_log.read_text(encoding="utf-8").splitlines() == ["side-effect-performed"]

    # And nothing in the governed response contradicts that.
    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "exception"
    assert response.diagnostic_code == "remote_exception"
    assert response.diagnostic_code != "remote_unavailable"
    assert response.decision.disposition != "refused"

    receipts = read_receipts(directory)
    assert len(receipts) == 2
    assert receipts[0]["disposition"] == "admitted"
    assert receipts[1]["outcome"] == "exception"


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_cancellation_after_forwarding_records_execution_state_unknown(
    tmp_path: Path, binding_version: str
) -> None:
    """Cancellation is the one post-forward mode with a *dedicated*
    indeterminacy representation in the existing vocabulary.

    The child has provably already performed the side effect when the
    cancellation lands, and the response says so in the only way the
    vocabulary allows: ``execution_state_unknown=True``. It does not claim
    the call was prevented.
    """

    side_effect_log = tmp_path / "side-effect.txt"
    connector = _side_effect_connector("side_effect_then_hang", side_effect_log, timeout_seconds=60.0)
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(arguments={"x": 1}, target="raw:fixture", tool="raw-echo")

    task = asyncio.ensure_future(
        execute_governed_call(request, arguments={"x": 1}, config=config)
    )
    # Cancel only once the side effect has provably already occurred, so the
    # test is about post-forward cancellation and nothing else.
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
    assert side_effect_log.read_text(encoding="utf-8").splitlines() == ["side-effect-performed"]


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_connection_close_after_forwarding_is_an_admitted_exception(
    tmp_path: Path, binding_version: str
) -> None:
    connector = _raw_connector("close_after_accept", timeout_seconds=5.0)
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(arguments={"x": 1}, target="raw:fixture", tool="raw-echo")

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "exception"
    assert response.diagnostic_code == "remote_exception"


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_malformed_response_after_forwarding_is_an_admitted_exception(
    tmp_path: Path, binding_version: str
) -> None:
    # A malformed line is dropped by the pinned SDK's own parser, so this
    # posture manifests as a bounded timeout -- but it is still post-forward,
    # so it must land in the same honest bucket and never claim non-delivery.
    connector = _raw_connector("malformed_call_response", timeout_seconds=1.5)
    config, _identity, directory = _build_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(arguments={"x": 1}, target="raw:fixture", tool="raw-echo")

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "exception"
    assert response.diagnostic_code == "remote_exception"


async def test_remote_unavailable_is_reachable_only_from_the_pre_spawn_path(
    tmp_path: Path,
) -> None:
    """The contrast that gives ``remote_unavailable`` its meaning.

    Only a failure to spawn the child at all -- provably before any
    tools/call could have been written -- produces ``remote_unavailable``.
    Every post-forward failure mode in this module produces
    ``remote_exception`` instead. If this pairing ever collapses, a
    definitely-not-executed claim would start covering may-have-executed
    calls.
    """

    # Pre-forward: nothing was ever spawned, so "unavailable" is grounded.
    unavailable_connector = StdioToolConnector(
        {
            "raw:missing": StdioTargetConfig(
                handle="raw:missing",
                command=("/nonexistent/absolute/path/to/a/binary",),
                known_tools=frozenset({"raw-echo"}),
                timeout_seconds=5.0,
            )
        }
    )
    config, _identity, _directory = _build_config(tmp_path, connector=unavailable_connector)
    request = _resolved_request(arguments={"x": 1}, target="raw:missing", tool="raw-echo")
    pre_forward = await execute_governed_call(request, arguments={"x": 1}, config=config)
    assert pre_forward.diagnostic_code == "remote_unavailable"

    # Post-forward: the work may have happened, so "unavailable" is not.
    side_effect_log = tmp_path / "side-effect.txt"
    post_config, _post_identity, _post_directory = _build_config(
        tmp_path / "post",
        connector=_side_effect_connector("side_effect_then_crash", side_effect_log),
    )
    post_request = _resolved_request(
        arguments={"x": 1}, target="raw:fixture", tool="raw-echo", request_ref="req:2"
    )
    post_forward = await execute_governed_call(
        post_request, arguments={"x": 1}, config=post_config
    )
    assert post_forward.diagnostic_code == "remote_exception"
    assert side_effect_log.exists()
