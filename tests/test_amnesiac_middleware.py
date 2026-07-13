"""FastMCP Client tests through the real DAGRMiddleware + SignedReceiptEmitter.

These drive the four Amnesiac tools through a real ``FastMCP`` server with the
existing ``DAGRMiddleware`` and a real ``SignedReceiptEmitter`` — no parallel
receipt family. They verify write/read classification via receipts, fail-closed
write-receipt failure, that capability-unavailable classifies as
``error_returned`` (never ``result_returned``), that outcome receipts verify,
and that custody projections are refs-only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastmcp")
pytest.importorskip("rfc8785")
pytest.importorskip("jsonschema")

from fastmcp import FastMCP
from fastmcp.client import Client
from fastmcp.exceptions import ToolError

from dagr_mcp.amnesiac_fastmcp import (
    AMNESIAC_TOOL_CLASSES,
    install_amnesiac_tools,
)
from dagr_mcp.fastmcp_binding import DAGRMiddleware, DAGRMiddlewareConfig
from dagr_mcp.srs_receipts import (
    RawEnvelopeFileSink,
    ReceiptWriteError,
    SignedReceiptEmitter,
    SigningIdentity,
)
from tests.amnesiac_fakes import FakeAmnesiacService, UnavailableAmnesiacService
from tests.receipt_verification import verify_receipt

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (ROOT / "dagr_mcp/vendor/srs/srs-envelope-v0.2.0.schema.json").read_text()
)

RAW_MARKERS = ("model_output", "prompt", "tool_arguments", "transcript", "raw_payload", "claim_text")


def _emitter(tmp_path: Path) -> tuple[SignedReceiptEmitter, SigningIdentity, Path]:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = SigningIdentity.generate(
        issuer_id="issuer:test:amnesiac", key_id="issuer.test.amnesiac/key/1"
    )
    return SignedReceiptEmitter(identity=identity, sink=sink), identity, directory


def _config(**overrides: Any) -> DAGRMiddlewareConfig:
    base = dict(
        runtime_instance_id="runtime:test:amnesiac",
        boundary_id="boundary:test:amnesiac",
        policy_pack_id="policy:test:amnesiac",
        policy_pack_version="2026.07.12",
        tool_classes={},
    )
    base.update(overrides)
    return DAGRMiddlewareConfig(**base)


def _read_receipts(directory: Path) -> list[dict[str, Any]]:
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(directory.glob("urn_srs_receipt_*.json"))
    ]


def _install(server: FastMCP, service: Any, emitter: SignedReceiptEmitter, **cfg: Any):
    return install_amnesiac_tools(server, service, emitter=emitter, config=_config(**cfg))


async def test_write_tools_get_write_admission_and_read_gets_read_classification(tmp_path: Path):
    emitter, identity, directory = _emitter(tmp_path)
    server = FastMCP("amnesiac-mw")
    # emit_read_admission_before_execution=False makes the read/write difference
    # observable in the receipts: writes emit a pre-execution admission; the
    # read (compile_context) does not.
    install = _install(
        server, FakeAmnesiacService(), emitter, emit_read_admission_before_execution=False
    )
    # The install merged and validated all four classifications.
    assert install.tool_classes == AMNESIAC_TOOL_CLASSES

    async with Client(server) as client:
        await client.call_tool("amnesiac.propose_candidates", {"source_ref": "s", "candidates": [{"claim": "x happened"}]})
        await client.call_tool("amnesiac.record_outcome", {"agent_outcome_ref": "agent_outcome:1"})
        await client.call_tool("amnesiac.request_reopening", {"candidate_ref": "candidate:1", "trigger_ref": "new_evidence_admitted"})
        await client.call_tool("amnesiac.compile_context", {"task": "summarize"})

    receipts = _read_receipts(directory)
    bundle = identity.trust_bundle()
    for receipt in receipts:
        verify_receipt(receipt, bundle, SCHEMA)  # ARCS Verify-style independent check

    admission_tools = {
        r["requested_tool_name"] for r in receipts if r["receipt_kind"] == "admission"
    }
    assert "amnesiac.propose_candidates" in admission_tools
    assert "amnesiac.record_outcome" in admission_tools
    assert "amnesiac.request_reopening" in admission_tools
    # The read tool emitted NO pre-execution admission (read classification).
    assert "amnesiac.compile_context" not in admission_tools


async def test_write_receipt_failure_is_fail_closed_read_is_fail_open(tmp_path: Path):
    class FailingEmitter:
        def emit_admission(self, **_kwargs: Any) -> str:
            raise ReceiptWriteError("sink failed")

        def emit_outcome(self, **_kwargs: Any) -> str:
            raise ReceiptWriteError("sink failed")

    server = FastMCP("amnesiac-failclosed")
    install_amnesiac_tools(
        server,
        FakeAmnesiacService(),
        emitter=FailingEmitter(),  # type: ignore[arg-type]
        config=_config(),
    )
    async with Client(server) as client:
        # A write tool fails closed when its admission receipt cannot be written.
        with pytest.raises(ToolError):
            await client.call_tool(
                "amnesiac.propose_candidates",
                {"source_ref": "s", "candidates": [{"claim": "x"}]},
            )
        # The read tool fails open and still returns its result.
        result = await client.call_tool("amnesiac.compile_context", {"task": "t"})
        assert result.structured_content["selector_profile"].endswith("reference_context_selector.v0")


async def test_capability_unavailable_classifies_error_returned_not_result_returned(tmp_path: Path):
    emitter, identity, directory = _emitter(tmp_path)
    server = FastMCP("amnesiac-unavailable")
    install_amnesiac_tools(
        server, UnavailableAmnesiacService(), emitter=emitter, config=_config()
    )
    async with Client(server) as client:
        result = await client.call_tool(
            "amnesiac.propose_candidates",
            {"source_ref": "s", "candidates": [{"claim": "x"}]},
            raise_on_error=False,
        )
    assert result.is_error is True
    assert result.structured_content["status"] == "capability_unavailable"

    receipts = _read_receipts(directory)
    outcomes = [r for r in receipts if r["receipt_kind"] == "outcome"]
    assert outcomes, "an outcome receipt must be emitted"
    # The unavailable op is classified as error_returned, never result_returned.
    assert all(r["outcome"] == "error_returned" for r in outcomes)
    assert not any(r["outcome"] == "result_returned" for r in outcomes)


async def test_reopening_capability_unavailable_is_error_result(tmp_path: Path):
    # A service whose reopening reports capability_unavailable as a status must
    # still surface as a fail-closed error result, classified error_returned.
    from dagr_mcp.amnesiac_contracts import RequestReopeningResponse, ReopeningStatus

    class ReopeningUnavailableService(FakeAmnesiacService):
        def request_reopening(self, request):
            return RequestReopeningResponse(
                candidate_ref=request.candidate_ref,
                status=ReopeningStatus.CAPABILITY_UNAVAILABLE,
                detail="FINAL guard not confirmed",
            )

    emitter, identity, directory = _emitter(tmp_path)
    server = FastMCP("amnesiac-reopen-unavailable")
    install_amnesiac_tools(server, ReopeningUnavailableService(), emitter=emitter, config=_config())
    async with Client(server) as client:
        result = await client.call_tool(
            "amnesiac.request_reopening",
            {"candidate_ref": "candidate:1", "trigger_ref": "new_evidence_admitted"},
            raise_on_error=False,
        )
    assert result.is_error is True
    assert result.structured_content["status"] == "capability_unavailable"
    outcomes = [r for r in _read_receipts(directory) if r["receipt_kind"] == "outcome"]
    assert outcomes and all(r["outcome"] == "error_returned" for r in outcomes)


async def test_outcome_receipts_verify_and_custody_is_refs_only(tmp_path: Path):
    arcs = pytest.importorskip("arcs_amnesiac")  # noqa: F841
    pytest.importorskip("garp_sdk")
    from dagr_mcp.amnesiac_native import NativeAmnesiacService
    from dagr_mcp.amnesiac_stores import (
        InMemoryAgentOutcomeStore,
        InMemoryCandidateStore,
        InMemoryContextPacketStore,
    )
    from arcs_amnesiac.claim_graph import ClaimGraph
    from arcs_amnesiac.claim_graph_types import ClaimNode, LifecycleState
    from garp_sdk.agent_outcome_object import AgentOutcomeObject

    graph = ClaimGraph()
    graph.add_node(
        ClaimNode(
            claim_id="claim:a",
            normalized_text="admitted claim",
            lifecycle_state=LifecycleState.ACTIVE,
            admission_state="admitted",
        )
    )
    outcome_store = InMemoryAgentOutcomeStore()
    outcome_store.put(
        "agent_outcome:o1",
        AgentOutcomeObject.from_dict(
            {
                "outcome_id": "o1",
                "source_kind": "synthetic_fixture",
                "generated_by": "agent:test",
                "summary_label": "notify compliance",
                "summary_ref": "summary:abc",
            }
        ),
    )
    service = NativeAmnesiacService(
        candidate_store=InMemoryCandidateStore(),
        agent_outcome_store=outcome_store,
        claim_graph=graph,
        context_packet_store=InMemoryContextPacketStore(),
    )

    emitter, identity, directory = _emitter(tmp_path)
    server = FastMCP("amnesiac-native-mw")
    install_amnesiac_tools(server, service, emitter=emitter, config=_config())

    async with Client(server) as client:
        propose = await client.call_tool(
            "amnesiac.propose_candidates",
            {"source_ref": "source:x", "candidates": [{"claim": "The filing occurred"}]},
        )
        outcome = await client.call_tool(
            "amnesiac.record_outcome", {"agent_outcome_ref": "agent_outcome:o1"}
        )
        context = await client.call_tool("amnesiac.compile_context", {"task": "summarize"})

    # Refs-only custody: the projections carry candidate/packet/outcome refs and
    # NO raw payload.
    cand_ref = propose.structured_content["results"][0]["candidate_ref"]
    assert cand_ref.startswith("candidate:")
    assert outcome.structured_content["candidate_ref"].startswith("candidate:")
    assert outcome.structured_content["outcome_ref"] == "agent_outcome:o1"
    assert context.structured_content["context_packet_ref"].startswith("packet:")

    # Every emitted receipt verifies under the independent verifier, and no
    # receipt carries a raw-payload marker (custody is hash/ref only).
    receipts = _read_receipts(directory)
    bundle = identity.trust_bundle()
    assert receipts
    for receipt in receipts:
        verify_receipt(receipt, bundle, SCHEMA)
        blob = json.dumps(receipt)
        for marker in RAW_MARKERS:
            assert f'"{marker}"' not in blob

    outcomes = [r for r in receipts if r["receipt_kind"] == "outcome"]
    assert outcomes
    assert all(r["outcome"] == "result_returned" for r in outcomes)
    # Outcome receipts attest by digest, never raw result.
    assert all("result_digest" in r for r in outcomes)
