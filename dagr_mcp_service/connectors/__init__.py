"""Client-side, in-process connector package for the Gateway (Sprint A8).

Scope: ``docs/GATEWAY_SERVICE_ADAPTER_SCOPE.md`` §13, work package A8. This
sprint adds exactly one connector — :mod:`dagr_mcp_service.connectors.memory`,
an in-process (test/single-process) local-target resolver. No network
transport connector (``stdio.py`` / ``http.py``) is added here; those remain
A9 scope.

**Import discipline.** Matches the lazy PEP 562 discipline
:mod:`dagr_mcp_service`, :mod:`dagr_mcp_lifecycle`, and
:mod:`dagr_mcp_sdk_binding` already use: importing this package never starts
a transport or binds a socket, and the ``memory`` submodule itself imports
neither ``mcp`` nor ``fastmcp``.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

__all__ = ["memory"]

_LAZY_SUBMODULES = frozenset({"memory"})


def __getattr__(name: str):
    if name in _LAZY_SUBMODULES:
        module = importlib.import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _LAZY_SUBMODULES)


if TYPE_CHECKING:  # pragma: no cover - import-time typing only, not eager at runtime.
    from dagr_mcp_service.connectors import memory
