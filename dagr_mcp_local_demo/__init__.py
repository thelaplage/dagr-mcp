"""LOCAL-DEMO-ONLY, explicitly NON-PRODUCTION helpers for dagr-mcp.

This package is **not** part of the frozen dagr-mcp runtime surface and carries
no production semantics. It exists only to host small, clearly-labelled,
local-demo adapter factories that wire the existing
:class:`dagr_mcp_sdk_binding.adapter.SdkLifecycleAdapter` for specific,
owner-frozen demo policies.

Nothing here broadens the runtime, adds a production policy pack, or weakens any
consumer's fail-closed factory contract. See each module's docstring for the
exact frozen policy it encodes.
"""

from __future__ import annotations

__all__ = ["counterpedia_acquisition", "wave100_acquisition", "page12_acquisition"]
