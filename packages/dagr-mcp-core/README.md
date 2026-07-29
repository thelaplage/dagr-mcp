# dagr-mcp-core

Protocol-neutral DAGR signed-receipt and lifecycle substrate. No `mcp`, no
`fastmcp`, no transport, no binding-specific type anywhere in this package.

This is a **one-way extraction fork** of the neutral logic already present,
unmodified, in the `dagr-mcp` distribution (`dagr_mcp.srs_receipts` and
`dagr_mcp_lifecycle.{contract,models,core}`) — not a shim, not a package that
re-imports the legacy tree. See
[`../../docs/CORE_EXTRACTION_FORK.md`](../../docs/CORE_EXTRACTION_FORK.md) for
the fork commit, the exact per-file provenance (source path, SHA-256 at the
fork commit, destination path, destination SHA-256 — machine-checked by
`tools/check_core_extraction_manifest.py`), and the maintenance policy: this
package is canonical for `official-mcp-sdk.python.v0.2` and later binding
development; the root `dagr-mcp` distribution is frozen legacy compatibility
code with no obligation to track future changes here.

## Contents

- `dagr_mcp_core.srs_receipts` — signed SRS receipt construction, signing
  identity, receipt context, digest helpers, the file-based receipt sink, and
  binding-version registration.
- `dagr_mcp_core.lifecycle` — the binding-neutral lifecycle contract, models,
  and pure planning core (`plan_admission` / `plan_outcome_strict`).

## Dependencies

`cryptography`, `rfc8785`. Nothing else.
