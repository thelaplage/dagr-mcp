"""Structural guardrails for the reconstructed SAM-LIVE-CHAIN0 replay lane.

No SAM process or network call is started by this test.
"""
from __future__ import annotations

import ast
import importlib.util
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools" / "sam_live_chain0"
EVIDENCE = ROOT / "evidence" / "sam-live-chain0"


def _load_result_shapes():
    """Import the stdlib-only parser module by path (tools/ is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "_sam_result_shapes", TOOLS / "_result_shapes.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Block:
    def __init__(self, text: str) -> None:
        self.text = text


class _Result:
    def __init__(self, *, structuredContent=None, content=None) -> None:
        self.structuredContent = structuredContent
        self.content = content


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


def test_up_sh_seeds_policy_before_router_enrollment() -> None:
    """Regression for clean-replay attempt 1 (@3be3749): the reconstructed up.sh
    omitted the /policies seed, so router enrollment failed 403 (role not
    authorized). Enrollment requires a group->role binding to exist first."""
    up = text(TOOLS / "up.sh")
    assert "/policies" in up
    policy_pos = up.index("/policies")
    # node role grants exactly the services this replay uses
    for svc in ("system://sam.catalog", "mcp://greeter", "mcp://market"):
        assert svc in up
    # the POST must happen textually BEFORE the router is started
    assert "start_bg router" in up
    assert policy_pos < up.index("start_bg router"), "policy seed must precede router enrollment"


def test_up_sh_binds_router_and_node_to_distinct_groups() -> None:
    """Identity separation: router-client -> group:routers -> sam:role:router;
    nodes -> group:sam-live-chain0 -> sam:role:node. Distinct groups so a node
    identity is never authorized for the router role."""
    up = text(TOOLS / "up.sh")
    mock = text(TOOLS / "mock_oidc.py")
    # the policy binds each role to its OWN group, not one shared group
    assert '"role":"sam:role:router","members":["group:routers"]' in up.replace(" ", "")
    assert '"role":"sam:role:node","members":["group:sam-live-chain0"]' in up.replace(" ", "")
    # the mock issues the matching groups per client identity
    assert '"routers"' in mock and '"sam-live-chain0"' in mock
    assert 'router-client' in mock


def test_up_sh_has_hostile_node_to_router_refusal_check() -> None:
    """A node identity must be refused the router role; up.sh proves it at runtime
    (mint a node token, attempt router enrollment, require fail-closed refusal)."""
    up = text(TOOLS / "up.sh")
    assert "node-hostile" in up
    assert "HOSTILE REFUSAL FAILED" in up
    assert re.search(r"not authorized.*forbidden.*403|403", up)


def test_tools_from_result_reads_alpha7_bare_json_array_in_content() -> None:
    """alpha.7's Go sam-node returns the tool list as a bare JSON array in text
    content and does NOT set structuredContent — the exact shape that broke the
    attempt-2 probe. Freeze it."""
    tfr = _load_result_shapes().tools_from_result
    payload = '[{"peer_id":"p1","tool_name":"mcp://greeter/hello"},' \
              '{"peer_id":"p1","tool_name":"mcp://greeter/shout"}]'
    result = _Result(structuredContent=None, content=[_Block(payload)])
    tools = tfr(result)
    assert [t["tool_name"] for t in tools] == ["mcp://greeter/hello", "mcp://greeter/shout"]


def test_tools_from_result_reads_structured_fallbacks() -> None:
    """Structured shapes other estate servers may use are also tolerated."""
    tfr = _load_result_shapes().tools_from_result
    row = {"peer_id": "p1", "tool_name": "mcp://market/settle"}
    assert tfr(_Result(structuredContent=[row])) == [row]
    assert tfr(_Result(structuredContent={"tools": [row]})) == [row]
    assert tfr(_Result(structuredContent={"result": [row]})) == [row]
    # content-embedded {"tools": [...]} dict
    assert tfr(_Result(content=[_Block('{"tools":[{"tool_name":"x"}]}')])) == [{"tool_name": "x"}]


def test_tools_from_result_fails_closed_on_unknown_or_malformed() -> None:
    """Unknown/empty/malformed shapes yield [] so callers fail closed on count,
    never on a raise."""
    tfr = _load_result_shapes().tools_from_result
    assert tfr(_Result()) == []
    assert tfr(_Result(structuredContent={"other": 1})) == []
    assert tfr(_Result(content=[_Block("not json")])) == []
    assert tfr(_Result(content=[_Block('{"scalar": 1}')])) == []


def test_python_and_shell_sources_parse() -> None:
    for path in TOOLS.glob("*.py"):
        ast.parse(text(path), filename=str(path))
    for path in (TOOLS / "up.sh", TOOLS / "down.sh"):
        subprocess.run(["bash", "-n", str(path)], check=True)


def test_draft_doc_keeps_owner_gate_open() -> None:
    doc = text(ROOT / "docs" / "SAM_LIVE_CHAIN0.md")
    assert "DO NOT MERGE WITHOUT OWNER REVIEW" in doc
    # the doc now records that the clean-checkout reproduction actually ran...
    assert "run on the Darwin host" in doc
    assert "evidence/sam-live-chain0-repro" in doc
    # ...while still holding the owner gate open
    assert "No ready flip or merge is authorized" in doc
    assert "Owner review still gates" in doc


def test_historical_arcs_exit_zero_is_preserved_as_evidence_not_new_run_claim() -> None:
    report = text(EVIDENCE / "CHAIN_REPORT.md")
    manifest = text(EVIDENCE / "EVIDENCE_MANIFEST.md")
    doc = text(ROOT / "docs" / "SAM_LIVE_CHAIN0.md")
    assert "aggregate exit 0" in report
    assert "aggregate exit code: **0**" in manifest
    assert re.search(r"aggregate\s+exit\s+code\s+`0`", doc)
