"""DAGR-MCP-IMPORT-ISOLATION-FIX0 — both halves of the lazy-re-export repair.

Proves simultaneously:

  (A) importing dagr_mcp, or any core dagr_mcp.* submodule, or the SDK-binding /
      service adapters, does NOT pull the optional FastMCP framework into
      sys.modules; and

  (B) the LEGIBILITY0/#50 construction surface is still fully reachable — the
      public names resolve lazily at the explicit access point (and FastMCP is
      allowed to load only there), so the repair restores optional-transport
      isolation without deleting the surface.

Each check runs in a FRESH interpreter so sys.modules starts clean. The three
pre-existing negative-space tests (test_official_mcp_sdk_binding /
test_gateway_service_adapter / test_gateway_service_receipt_access) are left
unchanged; this file is an explicit, self-contained regression proof.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _run(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script], cwd=str(ROOT), capture_output=True, text=True
    )


# --- Half A: core / adapter imports must not eagerly pull FastMCP -------------

@pytest.mark.parametrize(
    "import_stmt",
    [
        "import dagr_mcp",
        "import dagr_mcp.sdk_spine",
        "import dagr_mcp.srs_receipts",
        "import dagr_mcp_service.adapter",
        "import dagr_mcp_service.access",
        "import dagr_mcp_sdk_binding.adapter",
    ],
)
def test_core_and_adapter_imports_do_not_pull_fastmcp(import_stmt: str) -> None:
    script = (
        "import sys\n"
        f"{import_stmt}\n"
        "roots = {k.split('.', 1)[0] for k in sys.modules}\n"
        "assert 'fastmcp' not in roots, "
        f"{import_stmt!r} + ' must not eagerly import fastmcp'\n"
        "print('clean')\n"
    )
    proc = _run(script)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "clean"


# --- Half B: the construction surface still resolves (lazy opt-in) ------------

def test_public_surface_resolves_lazily_at_access_point() -> None:
    pytest.importorskip("fastmcp")  # the FastMCP-bearing names require it present
    script = (
        "import sys\n"
        "import dagr_mcp\n"
        # Importing the package alone does NOT load FastMCP...
        "roots = {k.split('.', 1)[0] for k in sys.modules}\n"
        "assert 'fastmcp' not in roots, 'import dagr_mcp must stay FastMCP-free'\n"
        # ...but the construction surface is still reachable and resolves to the
        # real object (FastMCP may load only at THIS explicit access point).
        "mw = dagr_mcp.DAGRMiddleware\n"
        "import dagr_mcp.fastmcp_binding as fb\n"
        "assert mw is fb.DAGRMiddleware, 'lazy re-export resolved to the wrong object'\n"
        # Cached like an ordinary re-export (no repeated resolution).
        "assert dagr_mcp.DAGRMiddleware is mw, 'lazy re-export not cached'\n"
        # Every frozen public name resolves.
        "for n in dagr_mcp.__all__:\n"
        "    getattr(dagr_mcp, n)\n"
        # __dir__ exposes the frozen surface.
        "assert set(dagr_mcp.__all__) <= set(dir(dagr_mcp)), '__dir__ dropped public names'\n"
        "print('ok')\n"
    )
    proc = _run(script)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


def test_fastmcp_clean_names_resolve_without_fastmcp() -> None:
    # The srs_receipts-sourced names are FastMCP-clean; they must resolve even
    # in an interpreter that never loads FastMCP.
    script = (
        "import sys\n"
        "import dagr_mcp\n"
        "for n in ('RawEnvelopeFileSink', 'SignedReceiptEmitter', 'SigningIdentity'):\n"
        "    getattr(dagr_mcp, n)\n"
        "roots = {k.split('.', 1)[0] for k in sys.modules}\n"
        "assert 'fastmcp' not in roots, 'resolving srs_receipts names must not load fastmcp'\n"
        "print('clean')\n"
    )
    proc = _run(script)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "clean"


def test_srs_receipts_export_stays_eager() -> None:
    # srs_receipts is FastMCP-clean, so the repair deliberately leaves it EAGER:
    # `import dagr_mcp` must still make the submodule and its three classes
    # immediately available (pre-existing observable behavior), while remaining
    # FastMCP-free. Only the FastMCP-bearing surface is deferred.
    script = (
        "import sys\n"
        "import dagr_mcp\n"
        "roots = {k.split('.', 1)[0] for k in sys.modules}\n"
        "assert 'fastmcp' not in roots, 'import dagr_mcp must stay FastMCP-free'\n"
        # eager submodule attribute exists without any explicit submodule import:
        "assert dagr_mcp.srs_receipts is sys.modules['dagr_mcp.srs_receipts'], "
        "'srs_receipts must stay eager'\n"
        # and its three exported classes are the submodule's, bound eagerly:
        "for n in ('RawEnvelopeFileSink', 'SignedReceiptEmitter', 'SigningIdentity'):\n"
        "    assert getattr(dagr_mcp, n) is getattr(dagr_mcp.srs_receipts, n), n\n"
        "print('eager')\n"
    )
    proc = _run(script)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "eager"
