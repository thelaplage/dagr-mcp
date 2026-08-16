"""Binding-neutral MCP lifecycle contract, models, and core (fork).

Fork of ``dagr_mcp_lifecycle``'s neutral submodules (``contract``, ``models``,
``core``) only. ``dagr_mcp_lifecycle.binding_mask`` is deliberately not forked:
it imports ``dagr_mcp.fastmcp_binding`` directly and is FastMCP-binding-specific
despite living in that package. See ``docs/CORE_EXTRACTION_FORK.md``.

All three submodules here are free of any binding SDK import, so — unlike the
legacy package, which lazily binds ``binding_mask`` to avoid eagerly importing
``dagr_mcp`` — this package imports all of its submodules eagerly.
"""

from __future__ import annotations

from dagr_mcp_core.lifecycle import contract as contract
from dagr_mcp_core.lifecycle import models as models
from dagr_mcp_core.lifecycle import core as core
from dagr_mcp_core.lifecycle import governed_action as governed_action

__all__ = ["contract", "models", "core", "governed_action"]
