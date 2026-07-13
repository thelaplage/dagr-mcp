"""Sprint A5 — cross-binding conformance corpus.

One shared scenario corpus drives BOTH the rebound FastMCP adapter
(``dagr_mcp.fastmcp_binding.DAGRMiddleware``) and the official-SDK adapter
(``dagr_mcp_sdk_binding.adapter.SdkLifecycleAdapter``) through equivalent calls,
and proves they agree on every binding-neutral semantic fact.

Both bindings are driven with a *matched* deterministic emitter configuration
(the same signing identity, deterministic id/clock factories, the same
runtime/boundary/policy identifiers, the same subject/actor, the same attestation
limits, the same tool result). The neutral core and the shared receipt emitter
are the single semantic authority, so the two bindings' receipts are expected to
differ **only** in the intentionally-distinct binding-version stamp (and the
signature computed over it). Every other field must be byte-for-byte equal.

The only permitted differences are documented and asserted narrowly:

* ``extensions.mcp.binding_version`` — the intentionally-distinct stamp,
  removed by ``mask.strip_binding_stamp`` (the single binding-specific field);
* ``receipt_signature`` — the Ed25519 signature, which necessarily differs once
  the stamped bytes differ.

There is no broad "normalize everything" helper: after removing exactly those two
fields, the corpus asserts full dict/byte equality, so any unexplained difference
fails the test.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

pytest.importorskip("fastmcp")
pytest.importorskip("mcp")
pytest.importorskip("rfc8785")
pytest.importorskip("jsonschema")

import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from mcp import types as mcp_types
from mcp.types import CallToolRequestParams

from fastmcp.server.middleware import MiddlewareContext

from dagr_mcp import fastmcp_binding, srs_receipts
from dagr_mcp.fastmcp_binding import DAGRMiddleware, DAGRMiddlewareConfig
from dagr_mcp.mcp_record_custody_gateway import build_mcp_record_custody_gateway
from dagr_mcp.srs_receipts import (
    RawEnvelopeFileSink,
    SignedReceiptEmitter,
    SigningIdentity,
)
from dagr_mcp_lifecycle import contract
from dagr_mcp_lifecycle.core import plan_admission, plan_outcome_strict
from dagr_mcp_lifecycle.models import AdmissionRequest, ExecutionObservation
from dagr_mcp_sdk_binding import mask as sdk_mask
from dagr_mcp_sdk_binding import neutral
from dagr_mcp_sdk_binding.adapter import SdkBindingConfig, SdkLifecycleAdapter

# Fixed identity + clock so the ONLY difference between the two bindings' bytes is
# the binding-version stamp (and its signature).
_DET_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
FIXED_ISSUED_AT = "2026-01-01T00:00:00Z"

# The exact dotted leaf paths permitted to differ across the two bindings: the
# intentionally-distinct binding stamp, and the signature computed over the bytes
# that include it. Every other leaf must be identical.
PERMITTED_DIFFERENCE_FIELDS = (
    "extensions.mcp.binding_version",
    "receipt_signature.signature",
)

# Equivalent tool results for the two bindings (same attribute projection → same
# result digest). A CreateTaskResult instance is shared as-is (same class in both).
RESULT_OK = SimpleNamespace(
    content=[mcp_types.TextContent(type="text", text="ok")],
    structured_content=None,
    meta=None,
    is_error=False,
)
RESULT_ERR = SimpleNamespace(
    content=[mcp_types.TextContent(type="text", text="bad")],
    structured_content=None,
    meta=None,
    is_error=True,
)
TASK_RESULT = mcp_types.CreateTaskResult(
    task=mcp_types.Task(
        taskId="task-1",
        status="working",
        createdAt=FIXED_ISSUED_AT,
        lastUpdatedAt=FIXED_ISSUED_AT,
        ttl=None,
    )
)


# --------------------------------------------------------------------------- #
# Scenario model                                                              #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Scenario:
    name: str
    tool: str
    tool_class: str
    disposition: str = "admitted"  # binding disposition token
    reason_code: str | None = None
    result: Any = None  # returned result OR a BaseException to raise
    review_ref: str | None = None
    review_raises: bool = False
    # Neutral facts derived by the core (filled in _expected).
    expected_kinds: tuple[str, ...] = ()


def _identity() -> SigningIdentity:
    return SigningIdentity(
        issuer_id="issuer:conformance",
        key_id="issuer.conformance/key/1",
        private_key=_DET_KEY,
    )


def _emitter(directory: Path, identity: SigningIdentity) -> SignedReceiptEmitter:
    return SignedReceiptEmitter(
        identity=identity,
        sink=RawEnvelopeFileSink(directory),
        receipt_id_factory=lambda kind: f"urn:srs:receipt:{kind}:fixed",
        issued_at_factory=lambda: FIXED_ISSUED_AT,
    )


def _review_creator(scenario: Scenario):
    if scenario.disposition != "deferred_for_review":
        return None

    def creator(_snapshot, _actor, _policy):
        if scenario.review_raises:
            raise RuntimeError("review sink raised")
        return scenario.review_ref or "review:fixed"

    return creator


def read_receipts(directory: Path) -> list[dict[str, Any]]:
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(directory.glob("urn_srs_receipt_*.json"))
    ]


# --------------------------------------------------------------------------- #
# Drivers                                                                     #
# --------------------------------------------------------------------------- #


async def drive_fastmcp(scenario: Scenario, directory: Path) -> list[dict[str, Any]]:
    emitter = _emitter(directory, _identity())
    config = DAGRMiddlewareConfig(
        runtime_instance_id="rt:conf",
        boundary_id="b:conf",
        policy_pack_id="p:conf",
        policy_pack_version="1",
        tool_classes={scenario.tool: scenario.tool_class},
        policy_resolver=lambda _s, _a: fastmcp_binding.BindingPolicy(
            disposition=scenario.disposition,
            tool_class=scenario.tool_class,
            reason_code=scenario.reason_code,
        ),
        review_object_creator=_review_creator(scenario),
        subject_ref_override="subject:conf",
        logical_call_id_override="call:conf",
        additional_attestation_limits=(neutral.DEFAULT_BOUNDARY_LIMIT,),
    )
    middleware = DAGRMiddleware(emitter=emitter, config=config)
    context = MiddlewareContext(
        message=CallToolRequestParams(name=scenario.tool, arguments={}),
        method="tools/call",
    )

    async def call_next(_context):
        if isinstance(scenario.result, BaseException):
            raise scenario.result
        return scenario.result

    try:
        await middleware.on_call_tool(context, call_next)
    except (Exception, asyncio.CancelledError):
        pass
    return read_receipts(directory)


async def drive_sdk(scenario: Scenario, directory: Path) -> list[dict[str, Any]]:
    emitter = _emitter(directory, _identity())
    config = SdkBindingConfig(
        runtime_instance_id="rt:conf",
        boundary_id="b:conf",
        policy_pack_id="p:conf",
        policy_pack_version="1",
        tool_classes={scenario.tool: scenario.tool_class},
        policy_resolver=lambda _s, _a: neutral.BindingPolicy(
            disposition=scenario.disposition,
            tool_class=scenario.tool_class,
            reason_code=scenario.reason_code,
        ),
        review_object_creator=_review_creator(scenario),
        subject_ref_override="subject:conf",
        logical_call_id_override="call:conf",
        additional_attestation_limits=(neutral.DEFAULT_BOUNDARY_LIMIT,),
    )
    adapter = SdkLifecycleAdapter(emitter=emitter, config=config)

    async def delegate(_arguments):
        if isinstance(scenario.result, BaseException):
            raise scenario.result
        return scenario.result

    try:
        await adapter.governed_call(scenario.tool, {}, delegate, request_context=None)
    except (Exception, asyncio.CancelledError):
        pass
    return read_receipts(directory)


# --------------------------------------------------------------------------- #
# Corpus                                                                      #
# --------------------------------------------------------------------------- #

SCENARIOS: tuple[Scenario, ...] = (
    Scenario("admitted_read", "reader", "read", result=RESULT_OK),
    Scenario("admitted_write", "writer", "write", result=RESULT_OK),
    Scenario(
        "policy_refusal", "reader", "read",
        disposition="refused", reason_code="policy_refused",
    ),
    Scenario(
        "deferred_for_review", "writer", "write",
        disposition="deferred_for_review", review_ref="review:fixed",
    ),
    Scenario(
        "review_object_creation_failure", "writer", "write",
        disposition="deferred_for_review", review_raises=True,
    ),
    Scenario("result_returned", "reader", "read", result=RESULT_OK),
    Scenario("error_returned", "reader", "read", result=RESULT_ERR),
    Scenario("raised_exception", "writer", "write", result=ValueError("boom")),
    Scenario("raised_timeout", "writer", "write", result=TimeoutError("slow")),
    Scenario("task_submitted", "writer", "write", result=TASK_RESULT),
    Scenario("cancellation", "writer", "write", result=asyncio.CancelledError()),
    Scenario(
        "required_sink_unavailable", "writer", "write",
        disposition="refused", reason_code="required_sink_unavailable",
    ),
)


def _neutral_disposition(scenario: Scenario) -> str:
    return neutral.to_neutral_disposition(scenario.disposition)  # type: ignore[arg-type]


def _expected_neutral(scenario: Scenario) -> dict[str, Any]:
    """Derive the neutral admission/outcome plan for a scenario from the core."""

    disp = _neutral_disposition(scenario)
    review_created = None
    if disp == "deferred":
        review_created = not scenario.review_raises
    admission = plan_admission(
        AdmissionRequest(
            disposition=disp,  # type: ignore[arg-type]
            tool_class=scenario.tool_class,  # type: ignore[arg-type]
            refusal_ground=scenario.reason_code if disp == "refused" else None,
            review_object_created=review_created,
        )
    )
    outcome = None
    if admission.execution_proceeds and isinstance(scenario.result, BaseException) is False:
        obs = ExecutionObservation("error" if _is_error_result(scenario.result) else "result")
        outcome = plan_outcome_strict(admission, obs)
    elif admission.execution_proceeds and isinstance(scenario.result, BaseException):
        if isinstance(scenario.result, asyncio.CancelledError):
            obs = ExecutionObservation("cancellation")
        elif isinstance(scenario.result, TimeoutError):
            obs = ExecutionObservation("timeout")
        else:
            obs = ExecutionObservation("exception", exception_class=type(scenario.result).__name__)
        outcome = plan_outcome_strict(admission, obs)
    elif admission.execution_proceeds and isinstance(scenario.result, mcp_types.CreateTaskResult):
        outcome = plan_outcome_strict(admission, ExecutionObservation("task_submitted"))
    return {"admission": admission, "outcome": outcome}


def _is_error_result(result: Any) -> bool:
    if isinstance(result, mcp_types.CreateTaskResult):
        return False
    return bool(getattr(result, "is_error", getattr(result, "isError", False)))


# --------------------------------------------------------------------------- #
# Byte / field comparison                                                     #
# --------------------------------------------------------------------------- #


def _strip_permitted(receipt: dict[str, Any]) -> dict[str, Any]:
    """Remove ONLY the two documented permitted-difference fields."""

    out = sdk_mask.strip_binding_stamp(receipt)  # drops extensions.mcp.binding_version
    out.pop("receipt_signature", None)
    return out


def _by_kind(receipts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["receipt_kind"]: r for r in receipts}


# --------------------------------------------------------------------------- #
# The conformance proof                                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
async def test_cross_binding_semantic_and_byte_conformance(
    scenario: Scenario, tmp_path: Path
):
    fastmcp_receipts = await drive_fastmcp(scenario, tmp_path / "fastmcp")
    sdk_receipts = await drive_sdk(scenario, tmp_path / "sdk")

    expected = _expected_neutral(scenario)
    admission_plan = expected["admission"]
    outcome_plan = expected["outcome"]

    # --- receipt cardinality matches the neutral plan and both bindings ----- #
    if admission_plan.execution_proceeds:
        expected_count = 1 + (1 if (outcome_plan and outcome_plan.record) else 0)
    else:
        expected_count = 1  # a single terminal admission record
    assert len(fastmcp_receipts) == expected_count
    assert len(sdk_receipts) == expected_count

    # --- receipt kinds match ------------------------------------------------ #
    fk = _by_kind(fastmcp_receipts)
    sk = _by_kind(sdk_receipts)
    assert set(fk) == set(sk)

    # --- every binding-neutral field matches exactly; only the stamp + its --- #
    # --- signature differ. After stripping exactly those, bytes are equal. -- #
    for kind in fk:
        f = fk[kind]
        s = sk[kind]

        # The binding stamp is intentionally different (the one permitted diff)…
        assert f["extensions"]["mcp"]["binding_version"] == "fastmcp.middleware.v0.1"
        assert s["extensions"]["mcp"]["binding_version"] == "official-mcp-sdk.python.v0.1"
        # …and the signatures differ because the stamped bytes differ.
        assert f["receipt_signature"]["signature"] != s["receipt_signature"]["signature"]

        # After removing exactly the two documented fields, everything is equal.
        f_stripped = _strip_permitted(f)
        s_stripped = _strip_permitted(s)
        assert f_stripped == s_stripped, (kind, scenario.name)
        assert rfc8785.dumps(f_stripped) == rfc8785.dumps(s_stripped)

    # --- explicit per-field semantic comparison (disposition, reason, etc.) - #
    fa, sa = fk["admission"], sk["admission"]
    assert fa["disposition"] == sa["disposition"]
    assert fa.get("reason_code") == sa.get("reason_code")
    assert fa.get("review_object_ref") == sa.get("review_object_ref")
    assert fa.get("retry_contract") == sa.get("retry_contract")
    assert fa["argument_digest"] == sa["argument_digest"]
    assert fa["attestation_limits"] == sa["attestation_limits"]

    if "outcome" in fk:
        fo, so = fk["outcome"], sk["outcome"]
        assert fo["outcome"] == so["outcome"]
        assert ("result_digest" in fo) == ("result_digest" in so)
        assert fo.get("result_digest") == so.get("result_digest")
        assert fo["admission_receipt_ref"] == so["admission_receipt_ref"]
        # outcome→admission reference edge is identical across bindings.
        assert fo["admission_receipt_ref"] == fa["receipt_id"]
        # cancellation governance facts (present only on indeterminate).
        for fact in contract.NEUTRAL_CANCELLATION_FACTS:
            assert fo.get(fact) == so.get(fact)


# --------------------------------------------------------------------------- #
# Determinism of each binding's own bytes                                     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
async def test_each_binding_is_deterministic_across_runs(scenario: Scenario, tmp_path: Path):
    def _unsigned(receipts):
        return [
            rfc8785.dumps({k: v for k, v in r.items() if k != "receipt_signature"})
            for r in receipts
        ]

    fm1 = _unsigned(await drive_fastmcp(scenario, tmp_path / "fm1"))
    fm2 = _unsigned(await drive_fastmcp(scenario, tmp_path / "fm2"))
    sdk1 = _unsigned(await drive_sdk(scenario, tmp_path / "sdk1"))
    sdk2 = _unsigned(await drive_sdk(scenario, tmp_path / "sdk2"))
    assert fm1 == fm2  # FastMCP bytes stable
    assert sdk1 == sdk2  # official-SDK bytes stable


# --------------------------------------------------------------------------- #
# Custody-observation parity                                                  #
# --------------------------------------------------------------------------- #


async def test_custody_observations_are_binding_neutral(tmp_path: Path):
    """A custody projection built from each binding's admission receipt agrees.

    The custody-gateway projection carries the non-claim / exclusion posture. Both
    bindings' admission receipts carry identical boundary/family/protocol/actor
    facts, so the custody records they yield are identical modulo the volatile
    observation timestamp.
    """

    scenario = Scenario("admitted_read", "reader", "read", result=RESULT_OK)
    fastmcp_receipts = await drive_fastmcp(scenario, tmp_path / "fastmcp")
    sdk_receipts = await drive_sdk(scenario, tmp_path / "sdk")

    def custody(receipt: dict[str, Any]) -> dict[str, Any]:
        # ``generated_by`` is pinned to a binding-neutral value on purpose: the
        # custody observation posture must not depend on which binding produced
        # the receipt, so a fixed generator id keeps the projection comparable.
        return build_mcp_record_custody_gateway(
            gateway_event_id="gw:conf:1",
            record_candidate_ref=receipt["receipt_id"],
            generated_by="binding:cross-conformance",
            boundary_type=receipt["boundary_type"],
            receipt_family=receipt["receipt_type"],
            protocol_binding=receipt["protocol_binding"],
            custody_status="custody_record_ready",
            actor_ref=receipt["actor_ref"],
            target_ref=receipt["requested_tool_name"],
            observed_at="2026-07-13T00:00:00Z",
        )

    fa = next(r for r in fastmcp_receipts if r["receipt_kind"] == "admission")
    sa = next(r for r in sdk_receipts if r["receipt_kind"] == "admission")
    f_custody = sdk_mask.custody_normalized_projection(custody(fa))
    s_custody = sdk_mask.custody_normalized_projection(custody(sa))
    assert f_custody == s_custody


# --------------------------------------------------------------------------- #
# Fail-open / fail-closed parity under an admission sink failure               #
# --------------------------------------------------------------------------- #


class _FailingSink:
    def write(self, _envelope):
        raise srs_receipts.ReceiptWriteError("sink down")


async def _drive_with_failing_sink(binding: str, tool_class: str, tmp_path: Path):
    identity = _identity()
    emitter = SignedReceiptEmitter(identity=identity, sink=_FailingSink())
    tool = "t"
    if binding == "fastmcp":
        mw = DAGRMiddleware(
            emitter=emitter,
            config=DAGRMiddlewareConfig(
                runtime_instance_id="rt", boundary_id="b", policy_pack_id="p",
                policy_pack_version="1", tool_classes={tool: tool_class},
            ),
        )
        ctx = MiddlewareContext(
            message=CallToolRequestParams(name=tool, arguments={}), method="tools/call"
        )

        async def call_next(_c):
            return RESULT_OK

        raised = False
        try:
            await mw.on_call_tool(ctx, call_next)
        except Exception:
            raised = True
        return raised
    else:
        adapter = SdkLifecycleAdapter(
            emitter=emitter,
            config=SdkBindingConfig(
                runtime_instance_id="rt", boundary_id="b", policy_pack_id="p",
                policy_pack_version="1", tool_classes={tool: tool_class},
            ),
        )

        async def delegate(_a):
            return RESULT_OK

        raised = False
        try:
            await adapter.governed_call(tool, {}, delegate, request_context=None)
        except Exception:
            raised = True
        return raised


async def test_fail_open_and_fail_closed_parity(tmp_path: Path):
    # A read fails OPEN in both bindings: the call proceeds despite the sink
    # failure (no exception raised out of the boundary).
    assert await _drive_with_failing_sink("fastmcp", "read", tmp_path) is False
    assert await _drive_with_failing_sink("sdk", "read", tmp_path) is False
    # A write fails CLOSED in both bindings: the boundary raises.
    assert await _drive_with_failing_sink("fastmcp", "write", tmp_path) is True
    assert await _drive_with_failing_sink("sdk", "write", tmp_path) is True


# --------------------------------------------------------------------------- #
# Unsupported input_required is unsupported in BOTH bindings                   #
# --------------------------------------------------------------------------- #


def test_input_required_unsupported_in_both_bindings():
    from dagr_mcp_lifecycle import binding_mask as fastmcp_mask

    assert fastmcp_mask.project_outcome("input_required").status == "unsupported"
    assert sdk_mask.project_outcome("input_required").status == "unsupported"
    # Both bindings share the neutral core, which refuses to plan the event.
    admitted = plan_admission(AdmissionRequest("admitted", tool_class="write"))
    for mode in contract.INPUT_REQUIRED_MODES:
        with pytest.raises(Exception):
            plan_outcome_strict(
                admitted,
                ExecutionObservation("input_required", input_required_mode=mode),
            )


# --------------------------------------------------------------------------- #
# The permitted differences are exactly the two documented fields              #
# --------------------------------------------------------------------------- #


async def test_permitted_differences_are_exactly_documented(tmp_path: Path):
    """Prove the ONLY differing fields across bindings are the documented two."""

    scenario = Scenario("admitted_read", "reader", "read", result=RESULT_OK)
    fk = _by_kind(await drive_fastmcp(scenario, tmp_path / "fastmcp"))
    sk = _by_kind(await drive_sdk(scenario, tmp_path / "sdk"))

    for kind in fk:
        diffs = _deep_diff_paths(fk[kind], sk[kind])
        assert set(diffs) == set(PERMITTED_DIFFERENCE_FIELDS), (kind, diffs)


def _deep_diff_paths(a: Any, b: Any, prefix: str = "") -> list[str]:
    """Return dotted paths whose leaf values differ between *a* and *b*."""

    paths: list[str] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in set(a) | set(b):
            child = f"{prefix}.{key}" if prefix else key
            if key not in a or key not in b:
                paths.append(child)
            else:
                paths.extend(_deep_diff_paths(a[key], b[key], child))
    elif a != b:
        paths.append(prefix)
    return paths
