"""Client-side connector package for the Gateway (Sprints A8, A9).

Scope: ``docs/GATEWAY_SERVICE_ADAPTER_SCOPE.md`` §13, work packages A8/A9.
A8 added :mod:`dagr_mcp_service.connectors.memory`, an in-process
(test/single-process) local-target resolver. A9 adds
:mod:`dagr_mcp_service.connectors.remote`, a client-side connector to a
genuinely remote MCP server over the pinned ``mcp==1.28.1`` client's
Streamable HTTP transport. A later, additive change adds
:mod:`dagr_mcp_service.connectors.stdio`, the ``connectors/stdio.py`` client
connector §13 names as an optional sibling to ``connectors/http.py`` --
governing an unmodified, operator-launched external MCP server child process
over stdio without importing or forking that server's implementation. A
further, additive, DRAFT change (program ``SAM-SUBSTRATE-BUILD0``, lane
``SAM-NATIVE-MCP-BIND0``) adds :mod:`dagr_mcp_service.connectors.sam_native`,
an adapter to google/sam v0.1.0-alpha.7's native MCP surface reached through
the local ``sam-node run`` process's own Streamable-HTTP ``/mcp`` endpoint --
composed *on top of* the ``remote`` submodule's :class:`RemoteToolConnector`
rather than adding a second transport. No generic pluggable-transport
framework is added; each connector remains one concrete transport (or, for
``sam_native``, one concrete adapter over an existing one).

**Import discipline.** Matches the lazy PEP 562 discipline
:mod:`dagr_mcp_service`, :mod:`dagr_mcp_lifecycle`, and
:mod:`dagr_mcp_sdk_binding` already use: importing this package never starts
a transport, spawns a process, or binds a socket. The ``memory`` submodule
imports neither ``mcp`` nor ``fastmcp``; the ``remote`` submodule imports
neither ``httpx`` nor ``mcp.client.*`` at module scope; the ``stdio``
submodule imports neither ``mcp`` nor ``anyio`` at module scope; the
``sam_native`` submodule imports only ``remote`` (plus stdlib ``re``) at
module scope and holds no transport of its own -- all import any real
transport lazily, only inside the coroutine that actually opens a connection
or spawns a child.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

__all__ = ["memory", "remote", "stdio", "sam_native"]

_LAZY_SUBMODULES = frozenset({"memory", "remote", "stdio", "sam_native"})


def __getattr__(name: str):
    if name in _LAZY_SUBMODULES:
        module = importlib.import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _LAZY_SUBMODULES)


if TYPE_CHECKING:  # pragma: no cover - import-time typing only, not eager at runtime.
    from dagr_mcp_service.connectors import memory, remote, sam_native, stdio
