"""Framework-neutral contract + FastMCP registration tests (no producer).

These run without ``arcs_amnesiac`` installed. They exercise the corrected
contract semantics through a fake service, real FastMCP registration of the four
tools, the install-surface classification validation, and the fail-closed
capability-unavailable error result. Native producer-backed behavior is NOT
asserted here — see ``test_amnesiac_native.py``.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fastmcp")

from dagr_mcp.amnesiac_contracts import (
    AdmissionStatus,
    CompileContextRequest,
    ProposalStatus,
    ProposeCandidatesRequest,
    ProposedClaim,
    RecordOutcomeRequest,
    ReopeningStatus,
    RequestReopeningRequest,
)
from dagr_mcp.amnesiac_fastmcp import (
    AMNESIAC_TOOL_CLASSES,
    AmnesiacClassificationError,
    install_amnesiac_tools,
    merge_amnesiac_tool_classes,
    register_amnesiac_tools,
    validate_amnesiac_tool_classes,
)
from tests.amnesiac_fakes import FakeAmnesiacService, UnavailableAmnesiacService


# -- the contract dropped request_admission ---------------------------------


def test_propose_request_has_no_request_admission_field():
    req = ProposeCandidatesRequest(source_ref="s", candidates=[ProposedClaim(claim="x")])
    assert not hasattr(req, "request_admission")


def test_record_outcome_request_is_refs_only():
    req = RecordOutcomeRequest(agent_outcome_ref="agent_outcome:1")
    # No raw fields on the contract at all.
    for forbidden in ("outcome", "model_output", "prompt", "prompt_ref", "claim", "tool_arguments"):
        assert not hasattr(req, forbidden)


# -- contract semantics through the fake ------------------------------------


def test_propose_is_recorded_not_admitted():
    svc = FakeAmnesiacService()
    resp = svc.propose_candidates(
        ProposeCandidatesRequest(
            source_ref="source:x",
            candidates=[ProposedClaim(claim="The filing occurred on June 3")],
        )
    )
    r = resp.results[0]
    assert r.proposal_status is ProposalStatus.CANDIDATE_RECORDED
    assert r.admission_status is AdmissionStatus.NOT_REQUESTED
    assert r.candidate_ref and r.content_hash
    assert resp.admission_performed is False


def test_final_candidate_reopening_is_refused():
    svc = FakeAmnesiacService()
    resp = svc.request_reopening(
        RequestReopeningRequest(candidate_ref="candidate:final", trigger_ref="trigger:x")
    )
    assert resp.status is ReopeningStatus.FINAL_REFUSED


def test_record_outcome_becomes_candidate_not_admitted_memory():
    svc = FakeAmnesiacService()
    resp = svc.record_outcome(
        RecordOutcomeRequest(agent_outcome_ref="agent_outcome:1")
    )
    assert resp.admission_status is AdmissionStatus.NOT_REQUESTED
    assert resp.candidate_ref


def test_compile_context_is_marked_reference_selector_v0_with_all_limitations():
    svc = FakeAmnesiacService()
    resp = svc.compile_context(CompileContextRequest(task="summarize"))
    assert resp.selector_profile == "amnesiac.reference_context_selector.v0"
    assert resp.full_governed_context_planner is False
    joined = " ".join(resp.limitations)
    for needle in (
        "No semantic ranking",
        "No tenant authorization",
        "No actor entitlement",
        "No purpose-limitation",
        "No contradiction-completeness",
        "No vector retrieval",
        "not the full governed context planner",
    ):
        assert needle in joined


# -- FastMCP registration (real fastmcp) ------------------------------------


def _make_server():
    from fastmcp import FastMCP

    return FastMCP("amnesiac-test")


async def _tool_names(server):
    tools = await server.list_tools()
    return [t.name for t in tools]


async def _get_tool(server, name):
    return await server.get_tool(name)


def test_all_four_tools_register():
    server = _make_server()
    register_amnesiac_tools(server, FakeAmnesiacService())
    names = set(asyncio.run(_tool_names(server)))
    assert {
        "amnesiac.propose_candidates",
        "amnesiac.compile_context",
        "amnesiac.request_reopening",
        "amnesiac.record_outcome",
    } <= names


def test_write_read_classification_covers_all_tools():
    assert AMNESIAC_TOOL_CLASSES["amnesiac.propose_candidates"] == "write"
    assert AMNESIAC_TOOL_CLASSES["amnesiac.record_outcome"] == "write"
    assert AMNESIAC_TOOL_CLASSES["amnesiac.request_reopening"] == "write"
    assert AMNESIAC_TOOL_CLASSES["amnesiac.compile_context"] == "read"


def test_capability_unavailable_is_an_error_result_not_a_success_dict():
    server = _make_server()
    register_amnesiac_tools(server, UnavailableAmnesiacService())
    tool = asyncio.run(_get_tool(server, "amnesiac.propose_candidates"))
    result = tool.fn(source_ref="s", candidates=[{"claim": "x"}])
    # It is a FastMCP error result (isError True) carrying structured content,
    # not an ordinary success dictionary.
    assert getattr(result, "is_error", False) is True
    structured = result.structured_content
    assert structured["status"] == "capability_unavailable"
    assert structured["operation"] == "amnesiac.propose_candidates"
    assert "detail" in structured


def test_record_outcome_refuses_raw_payload_via_tool_error():
    from fastmcp.exceptions import ToolError

    server = _make_server()
    register_amnesiac_tools(server, FakeAmnesiacService())
    tool = asyncio.run(_get_tool(server, "amnesiac.record_outcome"))
    for raw_field in ("model_output", "claim", "prompt", "tool_arguments"):
        with pytest.raises(ToolError):
            tool.fn(agent_outcome={"summary_ref": "s", raw_field: "raw"})


# -- install-surface classification validation ------------------------------


def test_merge_tool_classes_is_nonmutating_and_complete():
    base = {"other.tool": "read"}
    merged = merge_amnesiac_tool_classes(base)
    assert base == {"other.tool": "read"}  # unchanged
    for name, cls in AMNESIAC_TOOL_CLASSES.items():
        assert merged[name] == cls


def test_validate_fails_on_omitted_classification():
    partial = dict(AMNESIAC_TOOL_CLASSES)
    del partial["amnesiac.record_outcome"]
    with pytest.raises(AmnesiacClassificationError):
        validate_amnesiac_tool_classes(partial)


def test_validate_fails_on_wrong_classification():
    wrong = dict(AMNESIAC_TOOL_CLASSES)
    wrong["amnesiac.compile_context"] = "write"  # must be read
    with pytest.raises(AmnesiacClassificationError):
        validate_amnesiac_tool_classes(wrong)


def test_merge_conflict_is_an_error_not_a_silent_override():
    with pytest.raises(AmnesiacClassificationError):
        merge_amnesiac_tool_classes({"amnesiac.compile_context": "write"})


def test_install_requires_middleware_or_emitter_and_config():
    server = _make_server()
    with pytest.raises(ValueError):
        install_amnesiac_tools(server, FakeAmnesiacService())
