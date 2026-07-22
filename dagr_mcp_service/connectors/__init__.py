"""Client-side connector package for the Gateway (Sprints A8, A9).

Scope: ``docs/GATEWAY_SERVICE_ADAPTER_SCOPE.md`` §13, work packages A8/A9.
A8 added :mod:`dagr_mcp_service.connectors.memory`, an in-process
(test/single-process) local-target resolver. A9 adds
:mod:`dagr_mcp_service.connectors.remote`, a client-side connector to a
genuinely remote MCP server over the pinned ``mcp==1.28.1`` client's
Streamable HTTP transport. No generic pluggable-transport framework or
second transport (stdio, WebSocket, SSE) is added; §13/A9 scope prefers one
concrete remote connector.

**Import discipline.** Matches the lazy PEP 562 discipline
:mod:`dagr_mcp_service`, :mod:`dagr_mcp_lifecycle`, and
:mod:`dagr_mcp_sdk_binding` already use: importing this package never starts
a transport or binds a socket. The ``memory`` submodule imports neither
``mcp`` nor ``fastmcp``; the ``remote`` submodule imports neither ``httpx``
nor ``mcp.client.*`` at module scope — both are imported lazily, only inside
the coroutine that actually opens a connection.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

__all__ = ["memory", "remote"]

_LAZY_SUBMODULES = frozenset({"memory", "remote"})


def __getattr__(name: str):
    if name in _LAZY_SUBMODULES:
        module = importlib.import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _LAZY_SUBMODULES)


if TYPE_CHECKING:  # pragma: no cover - import-time typing only, not eager at runtime.
    from dagr_mcp_service.connectors import memory, remote
