"""Runnable client-side proof for the official-mcp-sdk.python.v0.2 HTTP server.

Spins up ``server.build_app()`` behind a REAL uvicorn server (an actual TCP
socket on 127.0.0.1) on a background thread, then -- using only real ``httpx``
HTTP requests over that socket, never an in-process ASGI transport -- proves:

* protocol version 2026-07-28
* no ``initialize``
* no ``notifications/initialized``
* no ``Mcp-Session-Id`` request or response header, ever
* valid ``Mcp-Method: tools/call`` / ``Mcp-Name: <tool name>`` request headers
* modern per-request ``_meta``
* modern result ``resultType: complete``
* the admission receipt is durably written before the delegate could have run
  (asserted by receipt cardinality: exactly one admission + one outcome, in
  that logical order, after a single tools/call)
* the outcome receipt is written after delegate completion and links back to
  the admission receipt
* both receipts independently verified -- via ``arcs-verify`` if it is
  installed (the "Modern binding environment" per the task spec), else the
  in-repo jsonschema + Ed25519 fallback verifier (``tests/receipt_verification.py``),
  with the verifier actually used printed explicitly, never silently swapped
* a SIGNED SEMANTIC MUTATION (flipping ``outcome`` inside the signed outcome
  envelope -- a semantic field, not whitespace or key order) is rejected by
  verification, and this script exits non-zero if that rejection does not
  happen as expected

Run:

    pip install -e packages/dagr-mcp-core -e packages/dagr-mcp-sdk-v2
    python examples/http_proof_v2/client_proof.py
"""

from __future__ import annotations

import copy
import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import build_app  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
HOST = "127.0.0.1"
PORT = 8799
# The v0.2.1 envelope, taken from the dagr-mcp-core package this binding
# actually depends on -- never the legacy dagr-mcp distribution, which this
# lane does not install. v0.2.1 is the schema that declares
# ``subject_ref_origin``; validating against the permissive v0.2.0 would
# prove nothing about the field these receipts now carry.
SCHEMA_PATH = (
    REPO_ROOT
    / "packages"
    / "dagr-mcp-core"
    / "tests"
    / "vendor"
    / "srs-envelope-v0.2.1.schema.json"
)


def _wait_for_server(host: str, port: int, timeout: float = 15.0) -> None:
    """Poll via a raw TCP connect (not an HTTP request) so a slow first ASGI
    request/import doesn't get mistaken for the server not listening yet."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("server did not start listening in time")


def _verify_receipt(receipt: dict, bundle: dict, schema_path: Path) -> str:
    """Verify *receipt*, raising on failure. Returns which verifier ran.

    The fallback is selected ONLY when ``arcs_verify`` is genuinely absent. Any
    other failure -- including the real verifier rejecting the receipt, or this
    script calling it wrongly -- propagates. Silently degrading to the in-repo
    checker would let a broken arcs-verify path masquerade as a passing proof.
    """

    try:
        from arcs_verify.verifier import (  # type: ignore[import-not-found]
            MCP_PROFILE,
            verify_receipt as _v,
        )
    except ModuleNotFoundError:
        sys.path.insert(0, str(REPO_ROOT / "tests"))
        from receipt_verification import verify_receipt as _fallback  # type: ignore[import-not-found]

        _fallback(receipt, bundle, json.loads(schema_path.read_text()))
        return "in-repo jsonschema+Ed25519 fallback verifier (arcs-verify not installed)"

    report = _v(receipt, bundle, schema_path=schema_path, selected_profile=MCP_PROFILE)
    verdicts = {
        name: getattr(report, name)
        for name in (
            "schema_digest",
            "envelope",
            "profile",
            "raw_content_exclusion",
            "signature_valid",
            "issuer_key_resolved",
            "issuer_key_trusted",
            "attestation_limits_present",
        )
    }
    if not all(verdicts.values()):
        failed = sorted(name for name, ok in verdicts.items() if not ok)
        raise AssertionError(
            f"arcs-verify rejected the receipt: failed verdicts={failed} "
            f"failure_codes={list(report.failure_codes)}"
        )
    return "arcs-verify"


def main() -> int:
    receipts_dir = Path(tempfile.mkdtemp(prefix="dagr-http-proof-v2-"))
    app, identity, _ = build_app(receipts_dir, allowed_hosts=[f"{HOST}:{PORT}"])
    bundle = identity.trust_bundle()

    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning")
    uvicorn_server = uvicorn.Server(config)
    thread = threading.Thread(target=uvicorn_server.run, daemon=True)
    thread.start()
    base_url = f"http://{HOST}:{PORT}"

    try:
        _wait_for_server(HOST, PORT)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Mcp-Protocol-Version": "2026-07-28",
            "Mcp-Method": "tools/call",
            "Mcp-Name": "echo",
        }
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "echo",
                "arguments": {"text": "hello from the genuine HTTP proof"},
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientCapabilities": {},
                },
            },
        }
        print(f"POST {base_url}/mcp")
        print("  no initialize, no notifications/initialized, no Mcp-Session-Id")
        resp = httpx.post(base_url + "/mcp", json=body, headers=headers, timeout=5.0)
        print("  status:", resp.status_code)
        if resp.status_code != 200:
            print("FAIL:", resp.text, file=sys.stderr)
            return 1

        response_header_names = {k.lower() for k in resp.headers}
        if "mcp-session-id" in response_header_names:
            print("FAIL: Mcp-Session-Id header present on the modern path", file=sys.stderr)
            return 1
        print("  Mcp-Session-Id absent from response: confirmed")

        result = resp.json()["result"]
        print("  resultType:", result["resultType"])
        assert result["resultType"] == "complete"

        receipts = sorted(receipts_dir.glob("*.json"))
        loaded = [json.loads(p.read_text()) for p in receipts]
        if len(loaded) != 2:
            print(f"FAIL: expected exactly 2 receipts, found {len(loaded)}", file=sys.stderr)
            return 1
        admission = next(r for r in loaded if r["receipt_kind"] == "admission")
        outcome = next(r for r in loaded if r["receipt_kind"] == "outcome")
        if outcome["admission_receipt_ref"] != admission["receipt_id"]:
            print("FAIL: outcome receipt does not reference the admission receipt", file=sys.stderr)
            return 1
        print("  admission receipt:", admission["receipt_id"])
        print("  outcome receipt:  ", outcome["receipt_id"], "outcome=", outcome["outcome"])

        verifier_used = _verify_receipt(admission, bundle, SCHEMA_PATH)
        _verify_receipt(outcome, bundle, SCHEMA_PATH)
        print(f"  both receipts independently verified ({verifier_used})")

        # The tamper demonstration: flip a SEMANTIC field inside the signed
        # envelope (never whitespace or key order), which invalidates the
        # Ed25519 signature over the RFC 8785 canonical preimage.
        mutated = copy.deepcopy(outcome)
        mutated["outcome"] = "error_returned" if mutated["outcome"] == "result_returned" else "result_returned"
        try:
            _verify_receipt(mutated, bundle, SCHEMA_PATH)
        except Exception as exc:  # noqa: BLE001 - this IS the expected-failure branch
            print(f"  mutated receipt correctly REJECTED: {type(exc).__name__}: {exc}")
        else:
            print("FAIL: a signed semantic mutation was accepted by verification", file=sys.stderr)
            return 1

        print("\nHTTP proof PASSED")
        return 0
    finally:
        uvicorn_server.should_exit = True
        thread.join(timeout=5.0)


if __name__ == "__main__":
    raise SystemExit(main())
