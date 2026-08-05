"""Standalone tool-discovery check: exercises dagr-mcp's stdio connector
`discover_tools()` helper against the real, official
`@modelcontextprotocol/server-filesystem` stdio MCP server, independent of
the full governed-call path in live_run.py. Useful for confirming what tool
names the target server actually advertises before writing a policy for it.

This file is self-contained and portable: it hardcodes no machine-specific
paths. The allowed root is created at runtime unless --allowed-root is given.

Run:

    python discover_full.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allowed-root",
        default="",
        help="Allowed-root directory passed to the filesystem MCP server. "
        "Defaults to a fresh tempfile.mkdtemp() directory.",
    )
    parser.add_argument(
        "--npx",
        default=os.environ.get("DAGR_MCP_SHOWCASE_NPX", ""),
        help="Path to the npx binary. Defaults to whatever `npx` resolves "
        "to on PATH.",
    )
    parser.add_argument(
        "--dagr-mcp-path",
        default=os.environ.get("DAGR_MCP_PATH", ""),
        help="Optional path to a dagr-mcp checkout to prepend to sys.path.",
    )
    return parser.parse_args()


_ARGS = _parse_args()

if _ARGS.dagr_mcp_path:
    sys.path.insert(0, str(Path(_ARGS.dagr_mcp_path).resolve()))

from dagr_mcp_service.connectors.stdio import discover_tools  # noqa: E402

NPX = _ARGS.npx or shutil.which("npx")
if not NPX:
    raise SystemExit(
        "npx not found. Install Node.js, or pass --npx /path/to/npx, or set "
        "DAGR_MCP_SHOWCASE_NPX."
    )

ALLOWED_ROOT = Path(_ARGS.allowed_root).resolve() if _ARGS.allowed_root else Path(
    tempfile.mkdtemp(prefix="dagr-mcp-showcase-discover-")
)
ALLOWED_ROOT.mkdir(parents=True, exist_ok=True)


async def main():
    names = await discover_tools(
        [NPX, "-y", "@modelcontextprotocol/server-filesystem", str(ALLOWED_ROOT)],
        timeout_seconds=30.0,
    )
    print("ALLOWED_ROOT:", ALLOWED_ROOT)
    print("DISCOVERED_TOOLS:", names)


if __name__ == "__main__":
    asyncio.run(main())
