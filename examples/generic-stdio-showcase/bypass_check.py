"""Bypass check: launch the SAME real filesystem MCP server directly with the
official `mcp` SDK client, with NO dagr-mcp connector/adapter/policy in the
loop at all, and perform the exact class of write that the governed run in
live_run.py refused.

This proves the connector is a configured binding an operator chooses to put
in front of the child process -- not an unbypassable enforcement boundary
around the child binary itself. Anything that can invoke the target stdio
server's own binary directly bypasses dagr-mcp's policy entirely. See the
example README for the full limitation statement.

This file is self-contained and portable: it hardcodes no machine-specific
paths. The allowed root is created at runtime unless --allowed-root is given.

Run:

    python bypass_check.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


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
    return parser.parse_args()


ARGS = _parse_args()

NPX = ARGS.npx or shutil.which("npx")
if not NPX:
    raise SystemExit(
        "npx not found. Install Node.js, or pass --npx /path/to/npx, or set "
        "DAGR_MCP_SHOWCASE_NPX."
    )

ALLOWED_ROOT = Path(ARGS.allowed_root).resolve() if ARGS.allowed_root else Path(
    tempfile.mkdtemp(prefix="dagr-mcp-showcase-bypass-")
)
ALLOWED_ROOT.mkdir(parents=True, exist_ok=True)
BYPASS_TARGET = ALLOWED_ROOT / "bypass_proof_ungoverned_write.txt"


async def main():
    params = StdioServerParameters(
        command=NPX, args=["-y", "@modelcontextprotocol/server-filesystem", str(ALLOWED_ROOT)]
    )
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w, read_timeout_seconds=timedelta(seconds=30)) as session:
            await session.initialize()
            result = await session.call_tool(
                "write_file",
                {
                    "path": str(BYPASS_TARGET),
                    "content": "written with ZERO dagr-mcp governance in the loop\n",
                },
            )
            print("call_tool result isError:", result.isError)
    exists = BYPASS_TARGET.exists()
    print("BYPASS_TARGET_EXISTS_AFTER_DIRECT_CALL:", exists)
    if exists:
        print("BYPASS_TARGET_CONTENT:", BYPASS_TARGET.read_text())


if __name__ == "__main__":
    asyncio.run(main())
