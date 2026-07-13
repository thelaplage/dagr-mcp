"""Binding-neutral MCP lifecycle contract and the FastMCP binding mask.

This package is deliberately separate from the ``dagr_mcp`` binding package.

* :mod:`dagr_mcp_lifecycle.contract` declares the *binding-neutral* lifecycle
  vocabulary — the portable names a governed MCP call moves through, independent
  of any one binding.
* :mod:`dagr_mcp_lifecycle.binding_mask` is the explicit mask that maps the
  existing, unmodified ``fastmcp.middleware.v0.1`` binding onto that vocabulary.

The mask *describes* the binding; it never normalizes or repairs it. The
external FastMCP binding (``dagr_mcp.fastmcp_binding`` + ``dagr_mcp.srs_receipts``)
remains the sole behavioral oracle. Nothing here extracts, moves, or replaces
binding implementation, and nothing here emits receipts.
"""

from __future__ import annotations

__all__ = ["contract", "binding_mask"]
