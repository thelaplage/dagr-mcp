"""DAGR Gateway Service Adapter — neutral contract and model layer (Sprint A7).

This package is the *service-seam* sibling of :mod:`dagr_mcp_lifecycle`
(binding-neutral lifecycle vocabulary) and :mod:`dagr_mcp_sdk_binding`
(a concrete binding). Its purpose and scope are recorded in
``docs/GATEWAY_SERVICE_ADAPTER_SCOPE.md`` (§13, §15, work package A7).

**What this sprint (A7) adds.** Two submodules — data models, validation, and
the one pure configuration lookup A7's acceptance criteria (§15) name
explicitly:

* :mod:`dagr_mcp_service.contract` — a two-stage request contract
  (``CallerGovernedCallRequest``, the untrusted caller-facing input, and
  ``GovernedCallRequest``, the internal service-resolved request — see §3.3)
  plus ``GovernedCallResponse`` and the supporting value types that separate
  the response's distinct concerns (business result, DAGR decision, receipt
  handles, custody reference, retry/continuation instruction, diagnostic
  code) per §4 of the scope document.
* :mod:`dagr_mcp_service.resolution` — binding *selector* types (a selector
  key type and a ``BindingHandle``-shaped resolved-identity type) plus
  ``select_binding(...)``: a narrow, pure, transport-free lookup from an
  operator-configured selector key to a registered binding identity,
  fail-closed on an unknown or unavailable binding (§5.2).

**What this sprint explicitly does NOT add.** No ``adapter.py``
(``execute_governed_call`` orchestration, A8), no ``connectors/`` (client-side
transport forwarders, A9), no ``access.py`` (receipt-handle resolution seam,
A10). No transport, execution, binding invocation, receipt emission, or real
actor/tenant resolution exists anywhere in this package —
``select_binding(...)`` resolves a *selector key* to a *binding identity*
only; it never imports, constructs, or calls a binding. No idempotency,
deduplication, or exactly-once guarantee is encoded here or claimed by it
(see scope §11 — those questions remain open).

**Import discipline.** This package must be importable with neither ``mcp``
nor ``fastmcp`` (nor any HTTP/ASGI/database/queue library) installed, and
importing it must never start a transport or bind a socket — the same
discipline :mod:`dagr_mcp_lifecycle` and :mod:`dagr_mcp_sdk_binding` already
guarantee via PEP 562 lazy submodules. Neither ``contract`` nor
``resolution`` needs such a library in A7; both are declared as lazily bound
submodules anyway, both for consistency with the sibling packages' convention
and so later work packages (A8's ``adapter.py``, A9's ``connectors/``) can be
added beside them under the same lazy-loading discipline without changing
this file's shape.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

# Pure metadata: importable with neither a transport library nor any
# submodule's own dependencies present.
SERVICE_PACKAGE_ID = "dagr.mcp.gateway_service"
SERVICE_PACKAGE_VERSION = "v0.1"

__all__ = [
    "SERVICE_PACKAGE_ID",
    "SERVICE_PACKAGE_VERSION",
    "contract",
    "resolution",
]

_LAZY_SUBMODULES = frozenset({"contract", "resolution"})


def __getattr__(name: str):
    if name in _LAZY_SUBMODULES:
        module = importlib.import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(
        set(globals()) | _LAZY_SUBMODULES | {"SERVICE_PACKAGE_ID", "SERVICE_PACKAGE_VERSION"}
    )


if TYPE_CHECKING:  # pragma: no cover - import-time typing only, not eager at runtime.
    from dagr_mcp_service import contract, resolution
