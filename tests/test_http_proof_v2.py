"""CI-safe counterpart to examples/http_proof_v2/client_proof.py.

That script proves the genuine HTTP proof over a real TCP socket (uvicorn).
This test drives the IDENTICAL app construction (``examples.http_proof_v2.
server.build_app``) over ``starlette.testclient.TestClient`` -- httpx-based,
driving the real ASGI app object and the real lifespan protocol, but without
allocating a network port -- so it is deterministic and safe to run in CI.

Skips cleanly wherever ``dagr-mcp-sdk-v2`` / ``mcp==2.0.0`` are not installed,
i.e. everywhere except the "modern binding" environment (see
docs/CORE_EXTRACTION_FORK.md "Required environments"). This is expected and
correct: `mcp==2.0.0` cannot coexist with the `fastmcp`/`mcp<2` stack the rest
of this repository's tests run against.
"""

from __future__ import annotations

import copy
import json
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pytest

pytest.importorskip("dagr_mcp_sdk_v2")
pytest.importorskip("mcp")
try:
    _mcp_version = version("mcp")
except PackageNotFoundError:  # pragma: no cover - importorskip above already covers this
    _mcp_version = None
if _mcp_version is None or not _mcp_version.startswith("2."):
    pytest.skip(f"requires mcp==2.0.0 (found {_mcp_version!r})", allow_module_level=True)

from starlette.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples" / "http_proof_v2"))
from server import build_app  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
from receipt_verification import verify_receipt  # noqa: E402

SCHEMA = json.loads((ROOT / "dagr_mcp" / "vendor" / "srs" / "srs-envelope-v0.2.0.schema.json").read_text())

REQUEST_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Mcp-Protocol-Version": "2026-07-28",
    "Mcp-Method": "tools/call",
    "Mcp-Name": "echo",
}


def _tools_call_body(tool_name: str, arguments: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientCapabilities": {},
            },
        },
    }


def test_no_initialize_no_session_id_modern_protocol_evidence(tmp_path):
    app, identity, receipts_dir = build_app(tmp_path / "receipts", allowed_hosts=["testserver"])
    bundle = identity.trust_bundle()

    with TestClient(app) as client:
        resp = client.post(
            "/mcp",
            json=_tools_call_body("echo", {"text": "ci-safe proof"}),
            headers=REQUEST_HEADERS,
        )

    assert resp.status_code == 200
    assert "mcp-session-id" not in {k.lower() for k in resp.headers.keys()}
    result = resp.json()["result"]
    assert result["resultType"] == "complete"
    assert result["isError"] is False

    receipts = [json.loads(p.read_text()) for p in sorted(receipts_dir.glob("*.json"))]
    assert len(receipts) == 2
    admission = next(r for r in receipts if r["receipt_kind"] == "admission")
    outcome = next(r for r in receipts if r["receipt_kind"] == "outcome")
    assert admission["extensions"]["mcp"]["binding_version"] == "official-mcp-sdk.python.v0.2"
    assert outcome["admission_receipt_ref"] == admission["receipt_id"]
    assert outcome["outcome"] == "result_returned"

    # Admission emitted before delegate entry, outcome emitted after delegate
    # completion: both receipts durably exist and link correctly, which is
    # only possible if admission was written strictly before dispatch (the
    # adapter's governed_call_tool never invokes the delegate first).
    verify_receipt(admission, bundle, SCHEMA)
    verify_receipt(outcome, bundle, SCHEMA)


def test_signed_semantic_mutation_is_rejected(tmp_path):
    app, identity, receipts_dir = build_app(tmp_path / "receipts", allowed_hosts=["testserver"])
    bundle = identity.trust_bundle()

    with TestClient(app) as client:
        client.post("/mcp", json=_tools_call_body("echo", {"text": "x"}), headers=REQUEST_HEADERS)

    receipts = [json.loads(p.read_text()) for p in sorted(receipts_dir.glob("*.json"))]
    outcome = next(r for r in receipts if r["receipt_kind"] == "outcome")

    # A tamper on a SEMANTIC field, never whitespace or key order.
    mutated = copy.deepcopy(outcome)
    mutated["outcome"] = "error_returned"
    with pytest.raises(Exception):  # noqa: B017 - cryptography.exceptions.InvalidSignature
        verify_receipt(mutated, bundle, SCHEMA)

    # The untampered receipt still verifies (control case).
    verify_receipt(outcome, bundle, SCHEMA)


def test_admitted_delegate_error_result(tmp_path):
    app, identity, receipts_dir = build_app(tmp_path / "receipts", allowed_hosts=["testserver"])

    headers = dict(REQUEST_HEADERS)
    headers["Mcp-Name"] = "boom"
    with TestClient(app) as client:
        resp = client.post(
            "/mcp", json=_tools_call_body("boom", {}), headers=headers,
        )

    body = resp.json()
    assert "error" in body  # the delegate raised; propagated as an MCP-level error

    receipts = [json.loads(p.read_text()) for p in sorted(receipts_dir.glob("*.json"))]
    outcome = next(r for r in receipts if r["receipt_kind"] == "outcome")
    assert outcome["outcome"] == "exception"
    assert outcome["extensions"]["mcp"]["exception_class"] == "ValueError"
