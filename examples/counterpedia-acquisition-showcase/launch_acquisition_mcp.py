"""Standalone launcher for counterpedia-acquisition's official-MCP-SDK stdio
server (``acquisition.mcp_server.run_stdio``).

This file lives entirely in dagr-mcp. It does not modify
counterpedia-acquisition in any way -- that repo ships no console script and
no ``__main__`` block for its MCP transport (``run_stdio(surface)`` is a bare
async function the caller must invoke), so this launcher exists purely to
give :class:`dagr_mcp_service.connectors.stdio.StdioTargetConfig` a runnable
``command``.

Requires the ``acquisition`` package to be importable -- pass its ``src/``
directory via the ``PYTHONPATH`` environment variable at launch (see
``live_run.py``, which sets this in ``StdioTargetConfig.env``). Requires no
model backend: this launcher wires an ``InMemoryObjectStore`` only, so the
surface's ``observer`` stays ``None`` and only the model-free tools
(``acquisition.capture_url``, ``acquisition.compare_captures``) are usable
without a fail-closed ``McpSurfaceError``.
"""

from __future__ import annotations

import anyio

from acquisition import InMemoryObjectStore
from acquisition.mcp_server import run_stdio
from acquisition.mcp_surface import AcquisitionMcpSurface

if __name__ == "__main__":
    anyio.run(run_stdio, AcquisitionMcpSurface(InMemoryObjectStore()))
