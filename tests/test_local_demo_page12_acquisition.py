"""Hostile-gate tests for the LOCAL-DEMO PAGE12 acquisition adapter factory.

Correctness tests for ``dagr_mcp_local_demo.page12_acquisition:build_adapter``
and the narrow, owner-frozen PAGE12 local-demo policy it encodes. They assert
the fail-closed custody contract, the exact admit/refuse policy (``capture_url``
admitted; every other tool — including the LIVE-AUTHORING ``process_held_capture``
— refused), delegate-invocation only on admitted calls, and the structural
metadata-only property of the emitted SRS receipts.

This factory is DISJOINT from ``dagr_mcp_local_demo.counterpedia_acquisition``:
the tool it admits here is exactly the tool that one refuses, and vice versa.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dagr_mcp_sdk_binding.adapter import (
    AdmissionReceiptUnavailable,
    SdkLifecycleAdapter,
    ToolRefused,
)

from dagr_mcp_local_demo import page12_acquisition as factory
from dagr_mcp_local_demo.page12_acquisition import (
    ALLOWED_TOOL,
    EVIDENCE_DIR_ENV,
    FIXED_ACTOR_REF,
    REFUSAL_REASON_CODE,
    LocalDemoConfigError,
    build_adapter,
)

ALLOWED = ALLOWED_TOOL  # acquisition.capture_url
PROCESS_HELD = "acquisition.process_held_capture"  # the LIVE-AUTHORING tool — refused here
PROCESS_SOURCE = "acquisition.process_source"
UNKNOWN = "acquisition.definitely_not_a_real_tool"


@pytest.fixture()
def evidence_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "evidence"
    d.mkdir()
    monkeypatch.setenv(EVIDENCE_DIR_ENV, str(d))
    return d


class _RecordingDelegate:
    def __init__(self, result=None):
        self.called = False
        self.calls: list[dict] = []
        self._result = result if result is not None else {"ok": True}

    async def __call__(self, arguments):
        self.called = True
        self.calls.append(dict(arguments))
        return self._result


def _receipt_files(evidence_dir: Path) -> list[Path]:
    return [p for p in evidence_dir.glob("*.json") if p.name != "issuer-keys.json"]


def _load_receipts(evidence_dir: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in _receipt_files(evidence_dir)]


# ---- G1: missing / invalid required env → fail closed ----

def test_g1_missing_evidence_env_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(EVIDENCE_DIR_ENV, raising=False)
    with pytest.raises(LocalDemoConfigError):
        build_adapter()


def test_g1_blank_evidence_env_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EVIDENCE_DIR_ENV, "   ")
    with pytest.raises(LocalDemoConfigError):
        build_adapter()


def test_g1_nonexistent_evidence_dir_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EVIDENCE_DIR_ENV, str(tmp_path / "nope"))
    with pytest.raises(LocalDemoConfigError):
        build_adapter()


def test_g1_file_not_dir_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "a-file"; f.write_text("x")
    monkeypatch.setenv(EVIDENCE_DIR_ENV, str(f))
    with pytest.raises(LocalDemoConfigError):
        build_adapter()


def test_g1_non_writable_dir_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = tmp_path / "ro"; d.mkdir(); d.chmod(0o500)
    monkeypatch.setenv(EVIDENCE_DIR_ENV, str(d))
    try:
        with pytest.raises(LocalDemoConfigError):
            build_adapter()
    finally:
        d.chmod(0o700)


# ---- G6: real adapter ----

def test_g6_build_adapter_returns_real_adapter(evidence_dir: Path) -> None:
    assert isinstance(build_adapter(), SdkLifecycleAdapter)


# ---- G7: capture_url → admitted + write, delegate invoked ----

async def test_g7_capture_url_admitted(evidence_dir: Path) -> None:
    adapter = build_adapter()
    delegate = _RecordingDelegate(result={"capture_status": "captured", "capture_id": "cap-1"})
    result = await adapter.governed_call(ALLOWED, {"url": "https://en.wikipedia.org/wiki/X"}, delegate)
    assert delegate.called is True
    assert result == {"capture_status": "captured", "capture_id": "cap-1"}
    admissions = [r for r in _load_receipts(evidence_dir) if r["receipt_kind"] == "admission"]
    assert admissions
    a = admissions[0]
    assert a["disposition"] == "admitted"
    assert a["requested_tool_name"] == ALLOWED == "acquisition.capture_url"
    assert a.get("actor_ref") == FIXED_ACTOR_REF == "actor:counterpedia-local-demo:page12-operator"
    assert a["policy_pack_id"] == "policy:counterpedia-local-demo:page12-governed-capture0"
    assert a["policy_pack_version"] == "0.1"
    assert a["boundary_id"] == "counterpedia-acquisition-mcp:page12-governed-capture0"
    assert a["runtime_instance_id"] == "counterpedia-local-demo:page12-governed-capture0"


async def test_g7_write_admission_then_outcome_digest_only(evidence_dir: Path) -> None:
    adapter = build_adapter()
    await adapter.governed_call(ALLOWED, {"url": "https://en.wikipedia.org/wiki/X"},
                                _RecordingDelegate(result={"capture_id": "cap-1"}))
    receipts = _load_receipts(evidence_dir)
    kinds = {r["receipt_kind"] for r in receipts}
    assert "admission" in kinds and "outcome" in kinds
    outcome = next(r for r in receipts if r["receipt_kind"] == "outcome")
    assert "result_digest" in outcome  # hash-only, never the raw result


# ---- G8/9/10: every other tool refused (incl. LIVE-AUTHORING's process_held_capture) ----

@pytest.mark.parametrize("tool", [PROCESS_HELD, PROCESS_SOURCE, UNKNOWN])
async def test_out_of_scope_refused(evidence_dir: Path, tool: str) -> None:
    adapter = build_adapter()
    delegate = _RecordingDelegate()
    with pytest.raises(ToolRefused):
        await adapter.governed_call(tool, {"url": "https://example.test"}, delegate)
    assert delegate.called is False
    receipts = _load_receipts(evidence_dir)
    admissions = [r for r in receipts if r["receipt_kind"] == "admission"]
    assert admissions
    refused = admissions[0]
    assert refused["disposition"] == "refused"
    assert refused["requested_tool_name"] == tool
    assert refused["reason_code"] == REFUSAL_REASON_CODE
    assert not [r for r in receipts if r["receipt_kind"] == "outcome"]


async def test_process_held_capture_specifically_refused(evidence_dir: Path) -> None:
    # The two demo factories are disjoint: PAGE12 refuses the LIVE-AUTHORING tool.
    adapter = build_adapter()
    delegate = _RecordingDelegate()
    with pytest.raises(ToolRefused):
        await adapter.governed_call(PROCESS_HELD, {"capture_ref": "sha256:x"}, delegate)
    assert delegate.called is False


async def test_no_defer_path_ever(evidence_dir: Path) -> None:
    adapter = build_adapter()
    for tool in (PROCESS_HELD, PROCESS_SOURCE, UNKNOWN):
        with pytest.raises(ToolRefused):
            await adapter.governed_call(tool, {}, _RecordingDelegate())
    for r in _load_receipts(evidence_dir):
        assert r.get("disposition") != "deferred"
        assert "review_object_ref" not in r


# ---- G11: admission-receipt failure before execution → fail closed ----

async def test_g11_admission_receipt_failure_fails_closed_no_delegate(evidence_dir: Path) -> None:
    adapter = build_adapter()
    delegate = _RecordingDelegate()

    def _boom(*args, **kwargs):
        raise RuntimeError("sink unavailable")

    adapter.emitter.emit_admission = _boom  # type: ignore[method-assign]
    with pytest.raises(AdmissionReceiptUnavailable):
        await adapter.governed_call(ALLOWED, {"url": "https://en.wikipedia.org/wiki/X"}, delegate)
    assert delegate.called is False


# ---- G12: emitted receipt is an SRS enforcement envelope, not a CaptureReceipt ----

async def test_g12_srs_envelope_not_capture_receipt(evidence_dir: Path) -> None:
    adapter = build_adapter()
    await adapter.governed_call(ALLOWED, {"url": "https://en.wikipedia.org/wiki/X"}, _RecordingDelegate())
    for r in _load_receipts(evidence_dir):
        assert r["receipt_version"].startswith("srs.core")
        assert r["receipt_type"] == "sdk_enforcement"
        assert r["receipt_kind"] in {"admission", "outcome"}
        assert "capture_ref" not in r
        assert r.get("tool") is None


# ---- G13: no raw URL / source bytes / credentials in receipt content ----

async def test_g13_no_raw_url_bytes_or_credentials_in_receipts(evidence_dir: Path) -> None:
    adapter = build_adapter()
    secret_url = "https://secret.example.test/RAW-URL-MUST-NOT-LEAK?token=sk-live-DEADBEEF"
    secret_arg = "SUPER-SECRET-CAPTURE-BYTES-AND-API-KEY-sk-live-DEADBEEF"
    secret_result_marker = "RAW-SOURCE-DOCUMENT-BODY-CONFIDENTIAL"
    delegate = _RecordingDelegate(result={"body": secret_result_marker})
    await adapter.governed_call(
        ALLOWED,
        {"url": secret_url, "credential": secret_arg, "raw_bytes": secret_arg},
        delegate,
    )
    blob = "\n".join(p.read_text() for p in _receipt_files(evidence_dir))
    assert secret_url not in blob
    assert secret_arg not in blob
    assert secret_result_marker not in blob
    assert "RAW-URL-MUST-NOT-LEAK" not in blob
