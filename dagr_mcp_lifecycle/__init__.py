"""Binding-neutral MCP lifecycle contract and the FastMCP binding mask.

This package is deliberately separate from the ``dagr_mcp`` binding package.

* :mod:`dagr_mcp_lifecycle.contract` declares the *binding-neutral* lifecycle
  vocabulary — the portable names a governed MCP call moves through, independent
  of any one binding. It imports nothing from ``dagr_mcp``.
* :mod:`dagr_mcp_lifecycle.binding_mask` is the explicit mask that maps the
  existing, unmodified ``fastmcp.middleware.v0.1`` binding onto that vocabulary.
  It *depends on* ``dagr_mcp`` on purpose — the binding is the oracle.

**Import direction is deliberate.** Importing this package root, or
``dagr_mcp_lifecycle.contract``, must never eagerly import the FastMCP binding
(``dagr_mcp`` / ``fastmcp``): the neutral vocabulary has to be usable without the
binding present. So the root eagerly binds only the neutral ``contract``
submodule; ``binding_mask`` is a declared but lazily-imported submodule that
pulls in ``dagr_mcp`` only when it is itself imported.

The mask *describes* the binding; it never normalizes or repairs it. The
external FastMCP binding (``dagr_mcp.fastmcp_binding`` + ``dagr_mcp.srs_receipts``)
remains the sole behavioral oracle. Nothing here extracts, moves, or replaces
binding implementation, and nothing here emits receipts.

This package ships publicly but is *outside* the Sprint A1 ``dagr_mcp``-only
public-API snapshot. Its own public surface is frozen separately by
``tests/test_lifecycle_contract_hardening.py`` against
``tests/golden/neutral_lifecycle/public_api_surface.json`` so a later change
cannot silently claim parity with the A1 binding surface.
"""

# NB: no ``from __future__ import annotations`` here — that binds an
# ``annotations`` attribute on the package, which would be an accidental public
# export. The root deliberately exposes submodules only.

# Eager import of the neutral vocabulary only. This is binding-free (it imports
# nothing from ``dagr_mcp`` / ``fastmcp``), so importing the package root keeps
# the neutral contract available without pulling the binding into memory.
from dagr_mcp_lifecycle import contract as contract

# ``binding_mask`` is intentionally NOT imported here: it depends on ``dagr_mcp``
# and importing it eagerly would violate the neutral package's import direction.
# It is declared public and is imported lazily on first explicit use, e.g.
# ``from dagr_mcp_lifecycle import binding_mask``.

__all__ = ["contract", "binding_mask"]
