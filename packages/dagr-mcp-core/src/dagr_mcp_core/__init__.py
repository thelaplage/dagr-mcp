"""dagr-mcp-core — protocol-neutral DAGR receipt and lifecycle substrate.

A one-way extraction fork (not a shared-source shim) of the neutral receipt and
lifecycle logic already present, unmodified, in the ``dagr-mcp`` distribution's
``dagr_mcp.srs_receipts`` and ``dagr_mcp_lifecycle.{contract,models,core}``
modules. See ``docs/CORE_EXTRACTION_FORK.md`` for:

* the exact fork commit and the SHA-256 of every extracted source file
  (``packages/dagr-mcp-core/EXTRACTION_MANIFEST.json``, checked by
  ``tools/check_core_extraction_manifest.py``);
* the maintenance policy — this package is canonical for v0.2+ binding
  development; the root ``dagr-mcp`` distribution is frozen legacy
  compatibility code with no obligation to track future changes here; any
  cross-cutting security fix needed in both requires an explicit coordinated
  backport with renewed parity evidence.

Depends only on ``cryptography`` and ``rfc8785`` — never ``mcp``, never
``fastmcp``.

Submodules:

* :mod:`dagr_mcp_core.srs_receipts` — signed SRS receipt construction, signing
  identity, receipt context, digest helpers, the file-based receipt sink, and
  binding-version registration.
* :mod:`dagr_mcp_core.lifecycle` — the binding-neutral lifecycle contract,
  models, and pure planning core (``plan_admission`` / ``plan_outcome_strict``).
"""

from __future__ import annotations

from dagr_mcp_core import srs_receipts as srs_receipts
from dagr_mcp_core import lifecycle as lifecycle

__all__ = ["srs_receipts", "lifecycle"]
