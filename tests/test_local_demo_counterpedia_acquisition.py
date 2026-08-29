"""Hostile-gate tests for the LOCAL-DEMO Counterpedia acquisition adapter factory.

These are correctness tests for
``dagr_mcp_local_demo.counterpedia_acquisition:build_adapter`` and the narrow,
owner-frozen local-demo policy it encodes. They assert the fail-closed custody
contract, the exact admit/refuse policy, delegate-invocation only on admitted
calls, and the structural metadata-only property of the emitted SRS receipts.

Gate map (see the DAGR-LOCAL-DEMO-FACTORY0 report for the deferred-to-acquisition
gates): G1, G4, G5, G6, G7, G8, G9, G10, G11, G12(partial), G13 are exercised
here. G2/G3 (MODULE:CALLABLE parsing, missing module/callable) are owned by
acquisition's ``load_dagr_adapter`` and are asserted here only insofar as the
isinstance gate they culminate in is reproduced.
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

from dagr_mcp_local_demo import counterpedia_acquisition as factory
from dagr_mcp_local_demo.counterpedia_acquisition import (
    ALLOWED_TOOL,
    EVIDENCE_DIR_ENV,
    FIXED_ACTOR_REF,
    REFUSAL_REASON_CODE,
    LocalDemoConfigError,
    build_adapter,
)

ALLOWED = ALLOWED_TOOL
CAPTURE_URL = "acquisition.capture_url"
PROCESS_SOURCE = "acquisition.process_source"
UNKNOWN = "acquisition.definitely_not_a_real_tool"


# --------------------------------------------------------------------------- #
# Fixtures / helpers                                                          #
# --------------------------------------------------------------------------- #


@pytest.fixture()
def evidence_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "evidence"
    d.mkdir()
    monkeypatch.setenv(EVIDENCE_DIR_ENV, str(d))
    return d


class _RecordingDelegate:
    """Async tool delegate that records whether it was invoked."""

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


# --------------------------------------------------------------------------- #
# G1 — missing / invalid required env → fail closed                          #
# --------------------------------------------------------------------------- #


def test_g1_missing_evidence_env_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(EVIDENCE_DIR_ENV, raising=False)
    with pytest.raises(LocalDemoConfigError):
        build_adapter()


def test_g1_blank_evidence_env_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EVIDENCE_DIR_ENV, "   ")
    with pytest.raises(LocalDemoConfigError):
        build_adapter()


def test_g1_nonexistent_evidence_dir_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EVIDENCE_DIR_ENV, str(tmp_path / "does-not-exist"))
    with pytest.raises(LocalDemoConfigError):
        build_adapter()


def test_g1_file_not_dir_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "a-file"
    f.write_text("x")
    monkeypatch.setenv(EVIDENCE_DIR_ENV, str(f))
    with pytest.raises(LocalDemoConfigError):
        build_adapter()


def test_g1_non_writable_dir_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = tmp_path / "ro"
    d.mkdir()
    d.chmod(0o500)
    monkeypatch.setenv(EVIDENCE_DIR_ENV, str(d))
    try:
        with pytest.raises(LocalDemoConfigError):
            build_adapter()
    finally:
        d.chmod(0o700)


# --------------------------------------------------------------------------- #
# G4 / G5 / G6 — isinstance gate the acquisition loader enforces             #
# --------------------------------------------------------------------------- #


def test_g6_build_adapter_returns_real_adapter(evidence_dir: Path) -> None:
    adapter = build_adapter()
    assert isinstance(adapter, SdkLifecycleAdapter)


def test_g4_none_is_not_an_adapter() -> None:
    # A factory returning None is rejected by acquisition's nominal gate; the gate
    # is exactly this isinstance check. Our factory never returns None (it raises).
    assert not isinstance(None, SdkLifecycleAdapter)


def test_g5_ducktyped_lookalike_rejected() -> None:
    class _Lookalike:
        def __init__(self):
            self.emitter = None
            self.config = None

        async def governed_call(self, *a, **k):  # pragma: no cover - never called
            return None

    assert not isinstance(_Lookalike(), SdkLifecycleAdapter)


# --------------------------------------------------------------------------- #
# G7 — process_held_capture → admitted + write, delegate invoked             #
# --------------------------------------------------------------------------- #


async def test_g7_process_held_capture_admitted(evidence_dir: Path) -> None:
    adapter = build_adapter()
    delegate = _RecordingDelegate(result={"draft_ref": "sha256:abc"})

    result = await adapter.governed_call(ALLOWED, {"capture_ref": "sha256:deadbeef"}, delegate)

    assert delegate.called is True
    assert result == {"draft_ref": "sha256:abc"}

    receipts = _load_receipts(evidence_dir)
    admissions = [r for r in receipts if r["receipt_kind"] == "admission"]
    assert admissions, "an admission receipt must be emitted"
    admission = admissions[0]
    assert admission["disposition"] == "admitted"
    assert admission["requested_tool_name"] == ALLOWED
    assert admission.get("actor_ref") == FIXED_ACTOR_REF
    # Frozen ids present on the receipt.
    assert admission["policy_pack_id"] == "policy:counterpedia-local-demo:authoring-accept0"
    assert admission["policy_pack_version"] == "0.1"
    assert admission["boundary_id"] == "counterpedia-acquisition-mcp:live-authoring-accept0"
    assert admission["runtime_instance_id"] == "counterpedia-local-demo:live-authoring-accept0"


async def test_g7_tool_class_write_via_admission_then_outcome(evidence_dir: Path) -> None:
    # tool_class=write is expressed to the adapter through both the policy resolver
    # and tool_classes; a write admission is durably recorded BEFORE execution,
    # then an outcome is emitted. Presence of both records with a result digest
    # (not raw result) is the observable proof the write path ran.
    adapter = build_adapter()
    delegate = _RecordingDelegate(result={"draft_ref": "sha256:abc"})
    await adapter.governed_call(ALLOWED, {"capture_ref": "sha256:deadbeef"}, delegate)
    receipts = _load_receipts(evidence_dir)
    kinds = {r["receipt_kind"] for r in receipts}
    assert "admission" in kinds and "outcome" in kinds
    outcome = next(r for r in receipts if r["receipt_kind"] == "outcome")
    assert "result_digest" in outcome  # hash-only, never the raw result


# --------------------------------------------------------------------------- #
# G8 / G9 / G10 — every other tool → refused, delegate NOT invoked           #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("tool", [CAPTURE_URL, PROCESS_SOURCE, UNKNOWN])
async def test_g8_g9_g10_out_of_scope_refused(evidence_dir: Path, tool: str) -> None:
    adapter = build_adapter()
    delegate = _RecordingDelegate()

    with pytest.raises(ToolRefused):
        await adapter.governed_call(tool, {"url": "https://example.test"}, delegate)

    assert delegate.called is False, "delegate must NOT run for a refused call"

    receipts = _load_receipts(evidence_dir)
    admissions = [r for r in receipts if r["receipt_kind"] == "admission"]
    assert admissions, "a terminal refused admission receipt must be emitted"
    refused = admissions[0]
    assert refused["disposition"] == "refused"
    assert refused["requested_tool_name"] == tool
    assert refused["reason_code"] == REFUSAL_REASON_CODE
    # No outcome receipt for a refused call (tool body never ran).
    assert not [r for r in receipts if r["receipt_kind"] == "outcome"]


async def test_no_defer_path_ever(evidence_dir: Path) -> None:
    # The policy has no deferral branch: out-of-scope tools REFUSE. Assert no
    # emitted admission is ever a deferral.
    adapter = build_adapter()
    for tool in (CAPTURE_URL, PROCESS_SOURCE, UNKNOWN):
        with pytest.raises(ToolRefused):
            await adapter.governed_call(tool, {}, _RecordingDelegate())
    for r in _load_receipts(evidence_dir):
        assert r.get("disposition") != "deferred"
        assert "review_object_ref" not in r


# --------------------------------------------------------------------------- #
# G11 — write-class admission-receipt failure before execution → fail closed  #
# --------------------------------------------------------------------------- #


async def test_g11_admission_receipt_failure_fails_closed_no_delegate(
    evidence_dir: Path,
) -> None:
    adapter = build_adapter()
    delegate = _RecordingDelegate()

    # Force the durable admission-receipt write to fail. write is fail_closed by
    # default, so the call must abort BEFORE the delegate runs.
    def _boom(*args, **kwargs):
        raise RuntimeError("sink unavailable")

    adapter.emitter.emit_admission = _boom  # type: ignore[method-assign]

    with pytest.raises(AdmissionReceiptUnavailable):
        await adapter.governed_call(ALLOWED, {"capture_ref": "sha256:x"}, delegate)

    assert delegate.called is False, "write must not execute without a durable admission receipt"


# --------------------------------------------------------------------------- #
# G12 — emitted SRS receipt is structurally an SRS envelope (distinct kind)   #
# --------------------------------------------------------------------------- #


async def test_g12_srs_receipt_is_srs_envelope_not_capture_receipt(
    evidence_dir: Path,
) -> None:
    # Partial, structural proof in dagr-mcp: the receipts emitted here are SRS
    # enforcement envelopes (receipt_type=sdk_enforcement, receipt_kind in
    # {admission, outcome}) with an srs.core receipt_version. They carry NONE of
    # acquisition's CaptureReceipt body fields. Full distinctness from the
    # acquisition CaptureReceipt object must be exercised in the acquisition
    # integration (that type lives in counterpedia-acquisition, not here).
    adapter = build_adapter()
    await adapter.governed_call(ALLOWED, {"capture_ref": "sha256:x"}, _RecordingDelegate())
    for r in _load_receipts(evidence_dir):
        assert r["receipt_version"].startswith("srs.core")
        assert r["receipt_type"] == "sdk_enforcement"
        assert r["receipt_kind"] in {"admission", "outcome"}
        # Not an acquisition CaptureReceipt: no capture-body discriminators.
        assert "capture_ref" not in r
        assert r.get("tool") is None


# --------------------------------------------------------------------------- #
# G13 — no source bytes / credentials in emitted receipt content              #
# --------------------------------------------------------------------------- #


async def test_g13_no_source_bytes_or_credentials_in_receipts(evidence_dir: Path) -> None:
    adapter = build_adapter()
    secret_arg = "SUPER-SECRET-CAPTURE-BYTES-AND-API-KEY-sk-live-DEADBEEF"
    secret_result_marker = "RAW-SOURCE-DOCUMENT-BODY-CONFIDENTIAL"
    delegate = _RecordingDelegate(result={"body": secret_result_marker})

    await adapter.governed_call(
        ALLOWED,
        {"capture_ref": "sha256:x", "credential": secret_arg, "raw_bytes": secret_arg},
        delegate,
    )

    for p in _receipt_files(evidence_dir):
        raw = p.read_text()
        assert secret_arg not in raw, "raw argument/credential leaked into a receipt"
        assert secret_result_marker not in raw, "raw result body leaked into a receipt"

    # And the receipts DO carry the hash-only projections instead.
    receipts = _load_receipts(evidence_dir)
    admission = next(r for r in receipts if r["receipt_kind"] == "admission")
    assert admission["argument_digest"].startswith("sha256:")
    assert admission["retention_class_applied"] == "hash_only"
    outcome = next(r for r in receipts if r["receipt_kind"] == "outcome")
    assert outcome["result_digest"].startswith("sha256:")


# --------------------------------------------------------------------------- #
# Custody — public trust material persisted, no private key on disk           #
# --------------------------------------------------------------------------- #


def test_custody_public_trust_bundle_written_no_private_key(evidence_dir: Path) -> None:
    build_adapter()
    bundle_path = evidence_dir / "issuer-keys.json"
    assert bundle_path.exists(), "public trust bundle must be preserved with the evidence"
    bundle_text = bundle_path.read_text().lower()
    for marker in ("private_key", "secret", "seed"):
        assert marker not in bundle_text
    bundle = json.loads(bundle_path.read_text())
    assert bundle["issuers"][0]["public_key"]

    # No file anywhere under the evidence dir should contain private-key material.
    for p in evidence_dir.rglob("*"):
        if p.is_file():
            txt = p.read_text().lower()
            assert "private_key" not in txt
            assert "-----begin" not in txt  # no PEM private material


def test_fixed_actor_is_never_derived_from_arguments(evidence_dir: Path) -> None:
    # Even if arguments try to assert an actor, the fixed resolver ignores them.
    from dagr_mcp_sdk_binding.neutral import RequestSnapshot

    snap = RequestSnapshot(
        tool_name=ALLOWED,
        arguments_digest="sha256:x",
        logical_call_id="call:x",
        subject_ref="tool-call:call:x",
    )
    resolution = factory._fixed_actor_resolver(
        {"actor_ref": "actor:attacker-supplied"}, snap
    )
    assert resolution.actor_ref == FIXED_ACTOR_REF
