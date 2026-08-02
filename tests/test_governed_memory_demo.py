"""Executable governed-memory vertical demo."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dagr_mcp.governed_memory_demo import (
    RAW_DEMO_TEXT,
    WORKFLOW_SCHEMA,
    run_governed_memory_demo_async,
)


@pytest.mark.asyncio
async def test_reference_demo_emits_receipts_and_refs_only_workflow_index(tmp_path: Path):
    pytest.importorskip("fastmcp")
    pytest.importorskip("rfc8785")
    out = await run_governed_memory_demo_async(
        tmp_path / "demo", service_mode="reference"
    )
    manifest_path = out / "governed-memory-workflow.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["schema"] == WORKFLOW_SCHEMA
    assert manifest["service_mode"] == "reference"
    assert manifest["service_claim"] == "reference_contract_only"
    assert set(manifest["operations"]) == {
        "propose_candidates",
        "compile_context",
        "request_reopening",
        "record_outcome",
    }
    assert manifest["operations"]["propose_candidates"]["result"][
        "admission_performed"
    ] is False
    assert manifest["operations"]["record_outcome"]["result"][
        "admission_status"
    ] == "not_requested"
    assert manifest["operations"]["compile_context"]["result"][
        "full_governed_context_planner"
    ] is False

    encoded = manifest_path.read_text(encoding="utf-8")
    for raw_text in RAW_DEMO_TEXT:
        assert raw_text not in encoded

    receipt_files = sorted(out.glob("urn_srs_receipt_*.json"))
    assert receipt_files
    assert len(receipt_files) == len(manifest["receipt_set"])
    for entry in manifest["receipt_set"]:
        path = out / entry["path"]
        assert path.exists()
        assert len(entry["sha256"]) == 64

    receipt_blobs = [json.loads(path.read_text()) for path in receipt_files]
    admission_receipts = [
        item for item in receipt_blobs if item["receipt_kind"] == "admission"
    ]
    outcome_receipts = [
        item for item in receipt_blobs if item["receipt_kind"] == "outcome"
    ]

    assert len(admission_receipts) == 4
    assert len(outcome_receipts) == 4

    tool_names = {
        item["requested_tool_name"] for item in admission_receipts
    }
    assert tool_names == {
        "amnesiac.propose_candidates",
        "amnesiac.compile_context",
        "amnesiac.request_reopening",
        "amnesiac.record_outcome",
    }

    admission_by_id = {
        item["receipt_id"]: item for item in admission_receipts
    }
    assert len(admission_by_id) == 4

    for outcome_receipt in outcome_receipts:
        admission_ref = outcome_receipt["admission_receipt_ref"]
        assert admission_ref in admission_by_id
        assert (
            outcome_receipt["logical_call_id"]
            == admission_by_id[admission_ref]["logical_call_id"]
        )


def test_native_mode_fails_with_actionable_install_hint_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
):
    import dagr_mcp.governed_memory_demo as demo

    monkeypatch.setattr(demo, "amnesiac_available", lambda: False)
    with pytest.raises(RuntimeError, match=r"\[amnesiac\]"):
        demo._native_service()


def test_reference_service_preserves_proposal_and_admission_distinction():
    from dagr_mcp.amnesiac_contracts import (
        ProposeCandidatesRequest,
        ProposedClaim,
    )
    from dagr_mcp.governed_memory_demo import _ReferenceDemoService

    result = _ReferenceDemoService().propose_candidates(
        ProposeCandidatesRequest(
            source_ref="source:test",
            candidates=[ProposedClaim(claim="candidate only")],
        )
    )
    assert result.admission_performed is False
    assert result.results[0].admission_status.value == "not_requested"


def test_cli_source_exposes_explicit_service_mode():
    source = (Path(__file__).resolve().parents[1] / "dagr_mcp" / "demo.py").read_text(
        encoding="utf-8"
    )
    assert '"governed-memory-demo"' in source
    assert 'choices=("native", "reference")' in source
    assert 'default="native"' in source
