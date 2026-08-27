"""Structural guardrails for the reconstructed SAM-LIVE-CHAIN0 replay lane.

No SAM process or network call is started by this test.
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools" / "sam_live_chain0"
EVIDENCE = ROOT / "evidence" / "sam-live-chain0"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_harness_is_explicitly_reconstructed_not_historical_recovery() -> None:
    doc = text(ROOT / "docs" / "SAM_LIVE_CHAIN0.md")
    readme = text(TOOLS / "README.md")
    assert "reconstructed" in doc.lower()
    assert "lost" in doc.lower()
    assert "reconstruction" in readme.lower()
    assert "not a recovered copy" in readme.lower()


def test_release_pins_match_frozen_manifest() -> None:
    manifest = text(EVIDENCE / "EVIDENCE_MANIFEST.md")
    verify = text(TOOLS / "verify_pins.py")
    expected = {
        "6c97d964e118bded0d25133e1f8a20d723648ea7415108788ce058006b061a81",
        "b1e8457409012bde0f9f0fde02517d3aff4e48b0a0c02ea129b843f2c509ad49",
        "0299d54df4c69c1189d7f37b19c8a915a6224c7b9fe4767ad96bf28961ccb6ce",
        "4f5775af9fd679a1fc4e9de5f3338c2ddd05c095407223cac8df67bcc006dfd8",
        "01330bad86b999e371a7abf5ef08ddac2a3d63db00d9216437b8708cf4fa8e23",
    }
    for digest in expected:
        assert digest in manifest
        assert digest in verify


def test_replay_surfaces_are_loopback_only() -> None:
    corpus = "\n".join(text(p) for p in [
        TOOLS / "up.sh",
        TOOLS / "mock_oidc.py",
        TOOLS / "greeter_server.py",
        TOOLS / "market_server.py",
        TOOLS / "provider-node-config.yaml",
    ])
    assert "127.0.0.1" in corpus
    assert "0.0.0.0" not in corpus
    assert "bananas.sam-mesh.dev" not in corpus
    assert "hub.sam-mesh.dev" not in corpus


def test_market_fixture_cannot_be_read_as_real_financial_settlement() -> None:
    server = text(TOOLS / "market_server.py").lower()
    docs = text(ROOT / "docs" / "SAM_LIVE_CHAIN0.md").lower()
    assert '"authority_effect": "none"' in server
    assert "not a financial settlement" in server
    assert "fixture `settled` != real financial settlement" in docs


def test_governed_call_freezes_same_logical_call_id_and_two_receipt_kinds() -> None:
    live = text(TOOLS / "live_market0.py")
    assert 'REQUEST_REF = "req:live-market0:1"' in live
    assert 'summary["receipt_kinds"] != ["admission", "outcome"]' in live
    assert 'summary["disposition"] != "admitted"' in live
    assert 'summary["outcome"] != "result"' in live


def test_semantic_probe_requires_native_tool_sequence_and_hello() -> None:
    probe = text(TOOLS / "probe_semantic.py")
    for token in ("discover_sam_peers", "find_sam_remote_tools", "describe_sam_remote_tool", "SamNativeConnector"):
        assert token in probe
    assert "Hello, SAM!" in probe


def test_python_and_shell_sources_parse() -> None:
    for path in TOOLS.glob("*.py"):
        ast.parse(text(path), filename=str(path))
    for path in (TOOLS / "up.sh", TOOLS / "down.sh"):
        subprocess.run(["bash", "-n", str(path)], check=True)


def test_draft_doc_keeps_owner_gate_open() -> None:
    doc = text(ROOT / "docs" / "SAM_LIVE_CHAIN0.md")
    assert "DO NOT MERGE WITHOUT OWNER REVIEW" in doc
    assert "does not claim a second native SAM execution" in doc
    assert "No ready flip or merge is authorized" in doc


def test_historical_arcs_exit_zero_is_preserved_as_evidence_not_new_run_claim() -> None:
    report = text(EVIDENCE / "CHAIN_REPORT.md")
    manifest = text(EVIDENCE / "EVIDENCE_MANIFEST.md")
    doc = text(ROOT / "docs" / "SAM_LIVE_CHAIN0.md")
    assert "aggregate exit 0" in report
    assert "aggregate exit code: **0**" in manifest
    assert re.search(r"aggregate\s+exit\s+code\s+`0`", doc)
    assert "syntax-checked" in doc
