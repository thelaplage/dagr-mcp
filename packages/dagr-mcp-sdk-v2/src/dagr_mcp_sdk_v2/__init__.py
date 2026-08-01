"""DAGR lifecycle binding over the official Python MCP SDK v2 (protocol 2026-07-28).

The *modern* DAGR lifecycle binding (``official-mcp-sdk.python.v0.2``), built on
``dagr-mcp-core`` (never the frozen legacy ``dagr-mcp`` distribution) and
``mcp==2.0.0``. Every lifecycle *decision* is deferred to the single neutral
core (:mod:`dagr_mcp_core.lifecycle.core`); this package owns only the v2 SDK
binding responsibilities: request/result extraction, trusted request-context
extraction, exception-object inspection, argument/result canonicalization and
digests, signing (via ``dagr_mcp_core.srs_receipts``), and the frozen result-
digest projection.

Submodules:

* :mod:`dagr_mcp_sdk_v2.adapter` -- the governed ``tools/call`` handler and
  construction config.
* :mod:`dagr_mcp_sdk_v2.result_digest` -- the frozen v2 tool-result projection.
* :mod:`dagr_mcp_sdk_v2.server` -- the supported ``mcp`` server construction
  surface (``Server(on_call_tool=..., on_list_tools=...)``).

The binding-version stamp is available as :data:`BINDING_VERSION` *without*
importing the official SDK. The three submodules are declared but loaded
lazily (PEP 562): importing this package -- or ``dagr_mcp_core`` -- never
eagerly imports ``mcp`` and never starts a transport. The first attribute
access imports the requested submodule.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

BINDING_VERSION = "official-mcp-sdk.python.v0.2"

__all__ = ["BINDING_VERSION", "adapter", "result_digest", "server"]

_LAZY_SUBMODULES = frozenset({"adapter", "result_digest", "server"})


def __getattr__(name: str):
    if name in _LAZY_SUBMODULES:
        module = importlib.import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _LAZY_SUBMODULES | {"BINDING_VERSION"})


if TYPE_CHECKING:  # pragma: no cover - import-time typing only, not eager at runtime.
    from dagr_mcp_sdk_v2 import adapter, result_digest, server
