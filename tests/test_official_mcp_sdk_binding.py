"""Sprint A5 — the official Python MCP SDK lifecycle binding.

Proves the second binding, over the *real* official-SDK in-process server/client
transport and the live adapter path:

* tools/list exposes the fixture tools and tools/call reaches the adapter;
* the neutral core is actually invoked on the live path;
* trusted request context reaches actor/policy resolution and model arguments
  cannot smuggle authority;
* admitted execution produces admission + outcome; refused/deferred never execute;
* exception / timeout / cancellation invoke the core;
* a divergent mask/core projection fails closed before a contradictory receipt;
* required-sink failure matches the FastMCP freeze;
* unsupported input_required fails explicitly;
* importing the binding pulls in no FastMCP and starts no transport;
* the binding's own bytes are deterministic.

Execution uses ``mcp.shared.memory.create_connected_server_and_client_session``
(the official in-process transport), never stdio/SSE/HTTP.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("mcp")
pytest.importorskip("rfc8785")
pytest.importorskip("jsonschema")

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator
from mcp import types as mcp_types
from mcp.shared.memory import create_connected_server_and_client_session as connect

from dagr_mcp import srs_receipts
from dagr_mcp.srs_receipts import (
    RawEnvelopeFileSink,
    ReceiptWriteError,
    SignedReceiptEmitter,
    SigningIdentity,
)
from dagr_mcp_lifecycle import contract
from dagr_mcp_lifecycle.models import (
    ExecutionObservation,
    OutcomePlan,
    OutcomeRecordIntent,
    UnsupportedLifecycleEvent,
)
from dagr_mcp_sdk_binding import adapter as adapter_mod
from dagr_mcp_sdk_binding.adapter import (
    BINDING_VERSION,
    AdmissionReceiptUnavailable,
    BindingPolicy,
    SdkBindingConfig,
    SdkLifecycleAdapter,
    ToolDeferred,
    ToolRefused,
)
from dagr_mcp_sdk_binding.server import GovernedTool, build_governed_server

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (ROOT / "dagr_mcp/vendor/srs/srs-envelope-v0.2.0.schema.json").read_text()
)
SURFACE_SNAPSHOT = ROOT / "tests/golden/official_mcp_sdk/public_api_surface.json"


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_signature(receipt: dict[str, Any], bundle: dict[str, Any]) -> None:
    assert not list(Draft202012Validator(SCHEMA).iter_errors(receipt))
    preimage = copy.deepcopy(receipt)
    signature = _decode(preimage["receipt_signature"].pop("signature"))
    entry = bundle["issuers"][0]
    Ed25519PublicKey.from_public_bytes(_decode(entry["public_key"])).verify(
        signature, rfc8785.dumps(preimage)
    )


def read_receipts(directory: Path) -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("urn_srs_receipt_*.json"))
    ]


def split_pair(receipts: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    admission = next(r for r in receipts if r["receipt_kind"] == "admission")
    outcome = next(r for r in receipts if r["receipt_kind"] == "outcome")
    return admission, outcome


def build_sdk_adapter(
    tmp_path: Path,
    *,
    policy_resolver: Any | None = None,
    actor_resolver: Any | None = None,
    review_object_creator: Any | None = None,
    tool_classes: dict[str, str] | None = None,
    sink: Any | None = None,
    emergency_spool_path: Path | None = None,
) -> tuple[SdkLifecycleAdapter, SigningIdentity, Path]:
    directory = tmp_path / "receipts"
    identity = SigningIdentity.generate(
        issuer_id="issuer:test:sdk", key_id="issuer.test.sdk/key/1"
    )
    emitter = SignedReceiptEmitter(
        identity=identity, sink=sink or RawEnvelopeFileSink(directory)
    )
    adapter = SdkLifecycleAdapter(
        emitter=emitter,
        config=SdkBindingConfig(
            runtime_instance_id="runtime:test:sdk",
            boundary_id="boundary:test:sdk",
            policy_pack_id="policy:test:sdk",
            policy_pack_version="2026.07.13",
            tool_classes=tool_classes or {},
            policy_resolver=policy_resolver,
            actor_resolver=actor_resolver,
            review_object_creator=review_object_creator,
            emergency_spool_path=emergency_spool_path,
        ),
    )
    return adapter, identity, directory


def _delegate(result: Any):
    async def handler(_arguments):
        if isinstance(result, BaseException):
            raise result
        return result

    return handler


async def run_call(
    adapter: SdkLifecycleAdapter,
    name: str,
    result: Any,
    *,
    arguments: dict[str, Any] | None = None,
    request_context: Any | None = None,
) -> Any:
    return await adapter.governed_call(
        name, arguments or {}, _delegate(result), request_context=request_context
    )


def call_tool_result(text: str, *, is_error: bool = False) -> mcp_types.CallToolResult:
    return mcp_types.CallToolResult(
        content=[mcp_types.TextContent(type="text", text=text)], isError=is_error
    )


def fixture_tool(name: str, handler) -> GovernedTool:
    return GovernedTool(
        definition=mcp_types.Tool(
            name=name,
            description="fixture",
            inputSchema={"type": "object", "properties": {"x": {"type": "string"}}},
        ),
        handler=handler,
    )


# --------------------------------------------------------------------------- #
# 1. Live in-process transport: list + call reach the adapter and the core     #
# --------------------------------------------------------------------------- #


async def test_tools_list_exposes_fixture_tools(tmp_path: Path):
    adapter, _identity, _directory = build_sdk_adapter(
        tmp_path, tool_classes={"echo": "read"}
    )

    async def echo(_args):
        return call_tool_result("ok")

    server = build_governed_server(
        "dagr-sdk", adapter=adapter, tools=[fixture_tool("echo", echo)]
    )
    async with connect(server) as client:
        await client.initialize()
        listed = await client.list_tools()
    assert [t.name for t in listed.tools] == ["echo"]


async def test_tools_call_reaches_adapter_and_invokes_core(monkeypatch, tmp_path: Path):
    adapter, identity, directory = build_sdk_adapter(
        tmp_path, tool_classes={"echo": "read"}
    )

    seen = {"admission": 0, "outcome": 0}
    real_admission = adapter_mod.plan_admission
    real_outcome = adapter_mod.plan_outcome_strict

    def spy_admission(request):
        seen["admission"] += 1
        return real_admission(request)

    def spy_outcome(plan, obs):
        seen["outcome"] += 1
        return real_outcome(plan, obs)

    monkeypatch.setattr(adapter_mod, "plan_admission", spy_admission)
    monkeypatch.setattr(adapter_mod, "plan_outcome_strict", spy_outcome)

    async def echo(_args):
        return call_tool_result("ok")

    server = build_governed_server(
        "dagr-sdk", adapter=adapter, tools=[fixture_tool("echo", echo)]
    )
    async with connect(server) as client:
        await client.initialize()
        res = await client.call_tool("echo", {"x": "hi"})

    assert res.isError is False
    assert seen == {"admission": 1, "outcome": 1}  # the core drove both phases
    kinds = sorted(r["receipt_kind"] for r in read_receipts(directory))
    assert kinds == ["admission", "outcome"]
    bundle = identity.trust_bundle()
    for receipt in read_receipts(directory):
        verify_signature(receipt, bundle)
        assert receipt["extensions"]["mcp"]["binding_version"] == BINDING_VERSION


# --------------------------------------------------------------------------- #
# 2. Trusted context reaches resolution; model args cannot smuggle authority   #
# --------------------------------------------------------------------------- #


async def test_trusted_request_context_reaches_actor_resolution(tmp_path: Path):
    seen_context: dict[str, Any] = {}

    def actor_resolver(request_context, snapshot):
        seen_context["request_id"] = getattr(request_context, "request_id", None)
        # The resolver sees only the hash-only snapshot for the request facts.
        assert snapshot.arguments_digest.startswith("sha256:")
        from dagr_mcp_sdk_binding.adapter import ActorResolution

        return ActorResolution(
            actor_ref="actor:trusted",
            tenant_id="tenant:from-trusted-context",
        )

    adapter, _identity, directory = build_sdk_adapter(
        tmp_path, tool_classes={"echo": "read"}, actor_resolver=actor_resolver
    )
    ctx = SimpleNamespace(
        request_id="req-42", session=SimpleNamespace(session_id="sess-1"), meta=None
    )
    await run_call(adapter, "echo", call_tool_result("ok"), request_context=ctx)

    assert seen_context["request_id"] == "req-42"
    admission, _outcome = split_pair(read_receipts(directory))
    assert admission["actor_ref"] == "actor:trusted"
    assert admission["tenant_id"] == "tenant:from-trusted-context"


async def test_model_arguments_cannot_smuggle_authority(tmp_path: Path):
    captured: dict[str, Any] = {}

    def policy_resolver(snapshot, actor):
        captured["snapshot"] = snapshot
        captured["actor"] = actor
        return BindingPolicy(disposition="admitted", tool_class="read")

    adapter, _identity, directory = build_sdk_adapter(
        tmp_path, policy_resolver=policy_resolver
    )
    # Hostile arguments attempting to define authority fields.
    hostile = {
        "organization": "acme",
        "tenant_id": "evil-tenant",
        "actor": "root",
        "role": "admin",
        "jwt": "forged.jwt.token",
        "signing_identity": "issuer:evil",
        "parent_receipt_ref": "urn:evil",
    }
    await run_call(adapter, "echo", call_tool_result("ok"), arguments=hostile)

    # The default (anonymous) actor was used — no authority came from arguments.
    admission, _outcome = split_pair(read_receipts(directory))
    assert admission["actor_ref"] == "actor:anonymous_or_local"
    assert "tenant_id" not in admission
    assert "workspace_id" not in admission
    assert "parent_receipt_ref" not in admission
    # The policy resolver never received the raw arguments — only a hash-only
    # snapshot (no field carries the raw argument values).
    snap = captured["snapshot"]
    assert not hasattr(snap, "arguments")
    assert "evil-tenant" not in json.dumps(read_receipts(directory))


# --------------------------------------------------------------------------- #
# 3. Admission dispositions and outcomes                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("tool_class", ["read", "write", "destructive"])
async def test_admitted_call_produces_admission_and_outcome(
    tmp_path: Path, tool_class: str
):
    adapter, identity, directory = build_sdk_adapter(
        tmp_path, tool_classes={"echo": tool_class}
    )
    await run_call(adapter, "echo", call_tool_result("ok"))

    receipts = read_receipts(directory)
    admission, outcome = split_pair(receipts)
    assert admission["disposition"] == "admitted"
    assert outcome["outcome"] == "result_returned"
    assert outcome["admission_receipt_ref"] == admission["receipt_id"]
    assert "result_digest" in outcome
    bundle = identity.trust_bundle()
    for receipt in receipts:
        verify_signature(receipt, bundle)


async def test_error_tool_result_is_error_returned(tmp_path: Path):
    adapter, _identity, directory = build_sdk_adapter(
        tmp_path, tool_classes={"echo": "read"}
    )
    await run_call(adapter, "echo", call_tool_result("nope", is_error=True))
    _admission, outcome = split_pair(read_receipts(directory))
    assert outcome["outcome"] == "error_returned"
    assert "result_digest" in outcome


async def test_policy_refusal_emits_one_admission_and_never_executes(tmp_path: Path):
    executed = {"ran": False}

    async def tool(_args):
        executed["ran"] = True
        return call_tool_result("never")

    def resolver(_snapshot, _actor):
        return BindingPolicy(disposition="refused", tool_class="read")

    adapter, _identity, directory = build_sdk_adapter(
        tmp_path, policy_resolver=resolver
    )
    with pytest.raises(ToolRefused):
        await adapter.governed_call("echo", {}, tool)

    assert executed["ran"] is False
    receipts = read_receipts(directory)
    assert len(receipts) == 1
    assert receipts[0]["receipt_kind"] == "admission"
    assert receipts[0]["disposition"] == "refused"
    assert receipts[0]["reason_code"] == "policy_refused"


async def test_deferred_emits_review_admission_and_never_executes(tmp_path: Path):
    executed = {"ran": False}

    async def tool(_args):
        executed["ran"] = True
        return call_tool_result("never")

    def resolver(_snapshot, _actor):
        return BindingPolicy(disposition="deferred_for_review", tool_class="write")

    def creator(_snapshot, _actor, _policy):
        return "review:object:123"

    adapter, _identity, directory = build_sdk_adapter(
        tmp_path, policy_resolver=resolver, review_object_creator=creator
    )
    with pytest.raises(ToolDeferred):
        await adapter.governed_call("danger", {}, tool)

    assert executed["ran"] is False
    receipts = read_receipts(directory)
    assert len(receipts) == 1
    assert receipts[0]["disposition"] == "deferred_for_review"
    assert receipts[0]["review_object_ref"] == "review:object:123"
    assert receipts[0]["retry_contract"] == "retry_after_approval"


async def test_review_object_creation_failure_is_refused_with_frozen_ground(
    tmp_path: Path,
):
    def resolver(_snapshot, _actor):
        return BindingPolicy(disposition="deferred_for_review", tool_class="write")

    def creator(_snapshot, _actor, _policy):
        raise RuntimeError("review sink raised")

    adapter, _identity, directory = build_sdk_adapter(
        tmp_path, policy_resolver=resolver, review_object_creator=creator
    )
    with pytest.raises(ToolRefused):
        await run_call(adapter, "danger", call_tool_result("never"))

    receipts = read_receipts(directory)
    assert len(receipts) == 1
    assert receipts[0]["disposition"] == "refused"
    # Never repaired into required_sink_unavailable.
    assert receipts[0]["reason_code"] == "review_object_creation_failed"


async def test_task_submitted_outcome(tmp_path: Path):
    adapter, _identity, directory = build_sdk_adapter(
        tmp_path, tool_classes={"submit": "write"}
    )
    task_result = mcp_types.CreateTaskResult(
        task=mcp_types.Task(
            taskId="task-1",
            status="working",
            createdAt="2026-01-01T00:00:00Z",
            lastUpdatedAt="2026-01-01T00:00:00Z",
            ttl=None,
        )
    )
    await run_call(adapter, "submit", task_result)
    _admission, outcome = split_pair(read_receipts(directory))
    assert outcome["outcome"] == "task_submitted"
    assert "result_digest" not in outcome
    assert srs_receipts.TASK_LIMIT in outcome["attestation_limits"]


# --------------------------------------------------------------------------- #
# 4. Exception / timeout / cancellation invoke the core                        #
# --------------------------------------------------------------------------- #


def _observation_spy(monkeypatch):
    seen: list[ExecutionObservation] = []
    real = adapter_mod.plan_outcome_strict

    def spy(plan, obs):
        seen.append(obs)
        return real(plan, obs)

    monkeypatch.setattr(adapter_mod, "plan_outcome_strict", spy)
    return seen


async def test_raised_exception_invokes_core_and_records_exception(
    monkeypatch, tmp_path: Path
):
    seen = _observation_spy(monkeypatch)
    adapter, _identity, directory = build_sdk_adapter(
        tmp_path, tool_classes={"boom": "write"}
    )
    with pytest.raises(ValueError):
        await run_call(adapter, "boom", ValueError("sensitive detail"))

    assert [o.observation for o in seen] == ["exception"]
    assert seen[0].exception_class == "ValueError"
    _admission, outcome = split_pair(read_receipts(directory))
    assert outcome["outcome"] == "exception"
    assert outcome["extensions"]["mcp"]["exception_class"] == "ValueError"
    assert "result_digest" not in outcome
    assert "sensitive detail" not in json.dumps(read_receipts(directory))


async def test_raised_timeout_is_subsumed_to_exception_timeouterror(
    monkeypatch, tmp_path: Path
):
    seen = _observation_spy(monkeypatch)
    adapter, _identity, directory = build_sdk_adapter(
        tmp_path, tool_classes={"slow": "write"}
    )
    with pytest.raises(TimeoutError):
        await run_call(adapter, "slow", TimeoutError("slow"))

    # The adapter hands the core a neutral 'timeout'; the core subsumes it.
    assert [o.observation for o in seen] == ["timeout"]
    _admission, outcome = split_pair(read_receipts(directory))
    assert outcome["outcome"] == "exception"
    assert outcome["extensions"]["mcp"]["exception_class"] == "TimeoutError"
    assert "result_digest" not in outcome


async def test_cancellation_invokes_core_and_records_indeterminate(
    monkeypatch, tmp_path: Path
):
    seen = _observation_spy(monkeypatch)
    adapter, _identity, directory = build_sdk_adapter(
        tmp_path, tool_classes={"cancel": "write"}
    )
    with pytest.raises(asyncio.CancelledError):
        await run_call(adapter, "cancel", asyncio.CancelledError())

    assert [o.observation for o in seen] == ["cancellation"]
    _admission, outcome = split_pair(read_receipts(directory))
    assert outcome["outcome"] == "indeterminate"
    assert outcome["request_cancelled"] is True
    assert outcome["execution_state_unknown"] is True
    assert outcome["delivery_incomplete"] is True
    assert "result_digest" not in outcome


# --------------------------------------------------------------------------- #
# 5. Fail-closed: divergent projection, required sink, unsupported state        #
# --------------------------------------------------------------------------- #


def _divergent_result_plan(_plan, _obs) -> OutcomePlan:
    return OutcomePlan(
        observation="result",
        record=OutcomeRecordIntent(
            outcome="result",
            subsumed_from=None,
            exception_class=None,
            carries_result_digest=True,
            references_admission=True,
            governance_facts=(),
            governance_facts_value=True,
            attestation_limit_families=("base", "result", "boundary"),
            adapter_responsibilities=(),
        ),
    )


async def test_divergent_core_projection_fails_closed_before_receipt(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setattr(adapter_mod, "plan_outcome_strict", _divergent_result_plan)
    adapter, _identity, directory = build_sdk_adapter(
        tmp_path, tool_classes={"boom": "write"}
    )
    with pytest.raises(adapter_mod.SDKBindingError, match="diverged"):
        await run_call(adapter, "boom", ValueError("boom"))

    # Only the admission receipt exists — no contradictory outcome receipt.
    assert [r["receipt_kind"] for r in read_receipts(directory)] == ["admission"]


async def test_required_sink_unavailable_is_preserved_like_the_freeze(tmp_path: Path):
    def resolver(_snapshot, _actor):
        return BindingPolicy(
            disposition="refused",
            tool_class="write",
            reason_code="required_sink_unavailable",
        )

    adapter, _identity, directory = build_sdk_adapter(
        tmp_path, policy_resolver=resolver
    )
    with pytest.raises(ToolRefused):
        await run_call(adapter, "danger", call_tool_result("never"))

    receipts = read_receipts(directory)
    assert len(receipts) == 1
    assert receipts[0]["reason_code"] == "required_sink_unavailable"


async def test_fail_closed_admission_sink_failure_blocks_execution(tmp_path: Path):
    class FailingSink:
        def write(self, _envelope):
            raise ReceiptWriteError("sink down")

    executed = {"ran": False}

    async def tool(_args):
        executed["ran"] = True
        return call_tool_result("never")

    adapter, _identity, directory = build_sdk_adapter(
        tmp_path, tool_classes={"danger": "write"}, sink=FailingSink()
    )
    with pytest.raises(AdmissionReceiptUnavailable):
        await adapter.governed_call("danger", {}, tool)

    assert executed["ran"] is False
    assert read_receipts(directory) == []


async def test_unsupported_input_required_fails_explicitly(tmp_path: Path):
    """input_required is refused by the core; it is never coerced into an outcome."""

    adapter, _identity, directory = build_sdk_adapter(
        tmp_path, tool_classes={"echo": "write"}
    )
    # Capture a real admission plan/context/ref from an admitted call.
    captured: dict[str, Any] = {}
    real_emit = adapter._emit_planned_outcome

    def capture(admission_plan, receipt_context, snapshot, ref, *a, **k):
        captured.update(plan=admission_plan, ctx=receipt_context, snap=snapshot, ref=ref)
        return real_emit(admission_plan, receipt_context, snapshot, ref, *a, **k)

    adapter._emit_planned_outcome = capture  # type: ignore[assignment]
    await run_call(adapter, "echo", call_tool_result("ok"))
    before = len(read_receipts(directory))

    for mode in contract.INPUT_REQUIRED_MODES:
        with pytest.raises(UnsupportedLifecycleEvent):
            adapter._project_core_outcome(
                captured["plan"],
                ExecutionObservation("input_required", input_required_mode=mode),
                captured["ctx"],
                captured["snap"],
                captured["ref"],
                frozen_outcome="exception",
                exception_class="ValueError",
            )
    assert len(read_receipts(directory)) == before  # nothing emitted


# --------------------------------------------------------------------------- #
# 6. Determinism of the binding's own bytes                                    #
# --------------------------------------------------------------------------- #


def _deterministic_adapter(directory: Path) -> SdkLifecycleAdapter:
    identity = SigningIdentity(
        issuer_id="issuer:det",
        key_id="issuer.det/key/1",
        private_key=_DET_KEY,
    )
    emitter = SignedReceiptEmitter(
        identity=identity,
        sink=RawEnvelopeFileSink(directory),
        receipt_id_factory=lambda kind: f"urn:srs:receipt:{kind}:det",
        issued_at_factory=lambda: "2026-01-01T00:00:00Z",
    )
    return SdkLifecycleAdapter(
        emitter=emitter,
        config=SdkBindingConfig(
            runtime_instance_id="rt",
            boundary_id="b",
            policy_pack_id="p",
            policy_pack_version="1",
            tool_classes={"echo": "read"},
            subject_ref_override="subject:det",
            logical_call_id_override="call:det",
        ),
    )


from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_DET_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


async def test_binding_bytes_are_deterministic_across_runs(tmp_path: Path):
    async def run(directory: Path) -> list[bytes]:
        adapter = _deterministic_adapter(directory)
        await run_call(adapter, "echo", call_tool_result("ok"))
        return [
            rfc8785.dumps({k: v for k, v in r.items() if k != "receipt_signature"})
            for r in read_receipts(directory)
        ]

    first = await run(tmp_path / "run1")
    second = await run(tmp_path / "run2")
    assert first == second
    assert len(first) == 2  # admission + outcome, both stable


# --------------------------------------------------------------------------- #
# 7. Import isolation and no transport                                         #
# --------------------------------------------------------------------------- #


def _run(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script], cwd=str(ROOT), capture_output=True, text=True
    )


def test_importing_binding_pulls_in_no_fastmcp():
    script = (
        "import sys\n"
        "import dagr_mcp_sdk_binding.adapter, dagr_mcp_sdk_binding.mask, "
        "dagr_mcp_sdk_binding.server\n"
        "roots = {k.split('.', 1)[0] for k in sys.modules}\n"
        "assert 'mcp' in roots, 'the official SDK must be imported'\n"
        "assert 'fastmcp' not in roots, 'the official-SDK binding must not import fastmcp'\n"
        "print('clean')\n"
    )
    proc = _run(script)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "clean"


def test_root_import_is_lazy_and_binding_free():
    script = (
        "import sys\n"
        "import dagr_mcp_sdk_binding as pkg\n"
        "roots = {k.split('.', 1)[0] for k in sys.modules}\n"
        # Importing the root package pulls in neither SDK nor FastMCP.
        "assert 'mcp' not in roots, 'root import must be lazy'\n"
        "assert 'fastmcp' not in roots\n"
        # The metadata stamp is available without the SDK.
        "assert pkg.BINDING_VERSION == 'official-mcp-sdk.python.v0.1'\n"
        "assert pkg.__all__ == ['BINDING_VERSION', 'adapter', 'mask', 'server']\n"
        # First access lazily loads the submodule (and pulls the SDK in only now).
        "_ = pkg.adapter\n"
        "assert 'mcp' in {k.split('.', 1)[0] for k in sys.modules}\n"
        "print('clean')\n"
    )
    proc = _run(script)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "clean"


def test_importing_neutral_core_imports_neither_binding():
    script = (
        "import importlib, sys\n"
        "importlib.import_module('dagr_mcp_lifecycle.core')\n"
        "importlib.import_module('dagr_mcp_lifecycle.models')\n"
        "roots = {k.split('.', 1)[0] for k in sys.modules}\n"
        "for forbidden in ('dagr_mcp_sdk_binding', 'fastmcp', 'mcp'):\n"
        "    assert forbidden not in roots, forbidden\n"
        "print('clean')\n"
    )
    proc = _run(script)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "clean"


async def test_no_production_transport_is_started(tmp_path: Path):
    """Building and exercising the binding uses only the in-process transport.

    A governed server is a plain object with registered handlers; nothing calls
    ``server.run(...)`` with a stdio/SSE/HTTP transport. The only transport used
    anywhere in these tests is the in-memory client/server session.
    """

    adapter, _identity, _directory = build_sdk_adapter(
        tmp_path, tool_classes={"echo": "read"}
    )

    async def echo(_args):
        return call_tool_result("ok")

    server = build_governed_server(
        "dagr-sdk", adapter=adapter, tools=[fixture_tool("echo", echo)]
    )
    # No running session/transport is attached by construction.
    assert getattr(server, "_session", None) is None
    async with connect(server) as client:  # the in-memory transport only
        await client.initialize()
        res = await client.call_tool("echo", {"x": "hi"})
    assert res.isError is False


# --------------------------------------------------------------------------- #
# 8. Public-surface snapshot (cold process)                                    #
# --------------------------------------------------------------------------- #


def test_committed_public_surface_snapshot_generated_from_cold_process():
    script = (
        "import sys, json, pkgutil, importlib\n"
        "assert 'fastmcp' not in sys.modules\n"
        "import dagr_mcp_sdk_binding as pkg\n"
        "names = ['dagr_mcp_sdk_binding']\n"
        "for mi in pkgutil.walk_packages(pkg.__path__, prefix='dagr_mcp_sdk_binding.'):\n"
        "    names.append(mi.name)\n"
        "modules = {}\n"
        "for name in sorted(names):\n"
        "    mod = importlib.import_module(name)\n"
        "    all_ = getattr(mod, '__all__', None)\n"
        "    modules[name] = sorted(all_) if all_ is not None else None\n"
        "surface = {'modules': modules, 'package_public_names': sorted(pkg.__all__)}\n"
        "sys.stdout.write('SURFACE=' + json.dumps(surface))\n"
    )
    proc = _run(script)
    assert proc.returncode == 0, proc.stderr
    generated = json.loads(proc.stdout.split("SURFACE=", 1)[1])
    committed = json.loads(SURFACE_SNAPSHOT.read_text(encoding="utf-8"))
    assert generated == committed
