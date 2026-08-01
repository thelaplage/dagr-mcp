# The `dagr-mcp-core` extraction fork

`packages/dagr-mcp-core` is a **one-way extraction fork**, not a second live
implementation kept in sync with the root `dagr-mcp` distribution by
convention, and not a shim that re-imports the root package's modules.

## Fork point

- **Fork commit**: `4b30f9fd8b863b6909b0d83090a785811e32cd0e`
- **Previous fork commit**: `292f7abeb66bad3c42a678c5a5c933aec511c986`. The fork
  point moved on 2026-08-01, when this work was reconciled onto the then-current
  authorized base. `4b30f9f` (#23) added the optional `subject_ref_origin`
  disclosure to `dagr_mcp/srs_receipts.py`, so the extracted copy was
  regenerated from the post-merge legacy file and carries that disclosure too.
  The three `dagr_mcp_lifecycle/*` sources are byte-identical at both commits;
  only `srs_receipts.py` actually moved. The manifest records the superseded
  commit as `previous_fork_commit` rather than silently dropping it — an
  obsolete fork claim is worse than no claim, because the drift check would
  keep passing against a commit nobody forked from.
- **Manifest**: [`packages/dagr-mcp-core/EXTRACTION_MANIFEST.json`](../packages/dagr-mcp-core/EXTRACTION_MANIFEST.json)
  — one entry per extracted file, recording the SHA-256 of the *original* file's
  git blob at the fork commit and the SHA-256 of the *extracted* file's current
  content, plus an itemized list of the intentional deltas between them.
- **Drift check**: [`tools/check_core_extraction_manifest.py`](../tools/check_core_extraction_manifest.py)
  recomputes all three hashes (pinned blob, current legacy file, current
  extracted file) on every CI run and fails loudly, naming the drifted file, if
  either side of the fork has been edited without a corresponding, deliberate
  manifest update. This is what makes the fork point auditable rather than
  aspirational.

## What was extracted, and what deliberately was not

| Extracted | From | To |
|---|---|---|
| Signed receipt construction, signing identity, receipt context, digest helpers, the file sink, binding-version registration | `dagr_mcp/srs_receipts.py` | `dagr_mcp_core.srs_receipts` |
| Binding-neutral lifecycle vocabulary | `dagr_mcp_lifecycle/contract.py` | `dagr_mcp_core.lifecycle.contract` |
| Neutral lifecycle input/output dataclasses | `dagr_mcp_lifecycle/models.py` | `dagr_mcp_core.lifecycle.models` |
| The pure admission/outcome planner | `dagr_mcp_lifecycle/core.py` | `dagr_mcp_core.lifecycle.core` |

**Not extracted, on purpose:**

- `dagr_mcp_lifecycle/binding_mask.py` — imports `dagr_mcp.fastmcp_binding`
  directly at module level. Despite living in the `dagr_mcp_lifecycle`
  directory, it is FastMCP-binding-specific, not neutral, and forking it would
  drag a transitive `fastmcp` dependency into `dagr-mcp-core`.
- `dagr_mcp/sdk_spine.py`'s review-object/async-sink machinery — the
  `official-mcp-sdk.python.v0.2` binding's acceptance matrix has no
  `deferred`/review-object case (only `admitted`/`refused`), so no review-object
  creation path is needed, and `now_utc_iso` is already present in
  `srs_receipts.py`.

Each extracted file's docstring carries a short fork-provenance note pointing
back here, and every content delta from the original (import-path rewrites,
the docstring itself, and the single `ADDITIONAL_BINDING_VERSIONS` addition in
`srs_receipts.py`) is itemized in `EXTRACTION_MANIFEST.json`.

## Byte-parity, as distinct from the manifest

The manifest proves *source drift* (did either copy's bytes change since the
fork). It deliberately does **not** assert that source and destination file
bytes are equal to each other — they aren't, by design (see
`documented_deltas`). The separate proof that the fork did not change
*behavior* is:

- `packages/dagr-mcp-core/tests/test_core_lifecycle_equivalence.py` — for a
  battery of admission/outcome inputs, `dagr_mcp_core.lifecycle.core` and the
  legacy `dagr_mcp_lifecycle.core` produce structurally identical plans.
- `tests/test_core_extraction_byte_parity.py` — for the existing
  `behavioral_freeze`, `fastmcp_demo`, and `official_mcp_sdk` golden fixture
  scenarios, the legacy `dagr_mcp.srs_receipts.SignedReceiptEmitter` and the new
  `dagr_mcp_core.srs_receipts.SignedReceiptEmitter` emit byte-identical signed
  envelopes (including the Ed25519 signature, which is deterministic under RFC
  8032 given an identical preimage and key) when given identical fixed IDs,
  timestamps, and signing keys.

## Maintenance policy

- **`dagr-mcp-core` is canonical** for `official-mcp-sdk.python.v0.2` and any
  later binding development. New protocol-neutral receipt/lifecycle work
  happens here.
- **The root `dagr-mcp` distribution is frozen legacy compatibility code.**
  `dagr_mcp/srs_receipts.py` and `dagr_mcp_lifecycle/{contract,models,core}.py`
  are not expected to track future changes made in `dagr-mcp-core`, and
  `dagr-mcp-core` is never imported from, or added as a runtime dependency of,
  the root package.
- **This repository does not have two co-equal current receipt
  implementations.** There is one canonical implementation
  (`dagr-mcp-core`, for v0.2+) and one frozen legacy implementation (the root
  package, serving `direct-harness.v0.1`, `fastmcp.middleware.v0.1`, and
  `official-mcp-sdk.python.v0.1` exactly as before).
- **Cross-cutting fixes.** If a defect is found that affects both the frozen
  legacy implementation and `dagr-mcp-core` (for example, a signing or
  canonicalization correctness bug), it requires an explicit, separately
  reviewed backport lane that patches both copies and produces renewed
  byte-parity evidence (re-running the equivalence and byte-parity tests above
  against the patched state) — it is never assumed safe to patch one and leave
  the other, and it is never assumed safe to silently re-derive one from the
  other after the fork.
