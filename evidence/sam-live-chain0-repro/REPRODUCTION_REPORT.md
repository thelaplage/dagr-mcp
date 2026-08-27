# SAM-LIVE-CHAIN0 — clean-checkout reproduction (authoritative)

A **clean-checkout reproduction** of the native governed SAM chain, distinct from
the 2026-08-26 historical run under `evidence/sam-live-chain0/`. Produced from an
isolated worktree with the historical `_sam-runtime` moved out of reach and a
freshly downloaded pinned release asset — proving self-sufficiency.

Reproduction date: 2026-08-27 (local darwin/arm64 host). This generation uses
**router/node identity separation** and supersedes the earlier `dd98b4e`
intermediate (which bound both roles to one shared group); that intermediate is
preserved in git history, not as a separate evidence dir.

## Posture

- Fresh `sam_Darwin_arm64.tar.gz` download; `verify_pins.py` PASS on all 5 SHAs.
- Historical `_sam-runtime/` moved aside for the whole run (hostile self-sufficiency check).
- Loopback-only; mock OIDC on 127.0.0.1; no cloud, no spend, no source build.
- `market` is a deterministic fixture; `settled` is NOT a financial event.
- `AUTHORITY_MOVEMENT=0`; no PR/merge/ratification asserted by this run.

## Gate results (binary)

| Gate | Result |
|---|---|
| static pytest gate (15 tests) | PASS |
| fresh pinned asset (verify_pins 5/5) | PASS |
| historical `_sam-runtime` inaccessible | PASS |
| policy seed + identity separation | PASS |
| **hostile node→router enrollment refusal (fail-closed)** | PASS |
| router enrollment | PASS |
| 3 real sam-node mesh | PASS |
| `get_mesh_info` ×3 | PASS |
| `discover → find → describe → call_remote_tool` | PASS |
| `Hello, SAM!` | PASS |
| governed `settle` | PASS |
| independent ARCS (own env) aggregate exit | 0 |
| teardown / ports free | PASS |

Retained outputs for every gate are under `run-logs/`; digests and release pins
are in `EVIDENCE_MANIFEST.md`.

## Identity separation (owner correction)

- `mock_oidc.py`: `router-client` → `group:routers` / `sam:role:router`; ordinary
  nodes → `group:sam-live-chain0` / `sam:role:node`.
- `up.sh` `/policies`: `group:routers → sam:role:router`, `group:sam-live-chain0
  → sam:role:node` (distinct groups per role).
- `up.sh` proves the separation at runtime: a node-role token attempting router
  enrollment is refused fail-closed (`run-logs/hostile-node-as-router.log`).

## Structural facts (NOT byte-identical to other generations)

- `logical_call_id`: `req:live-market0:1` (admission + outcome, same call)
- admission `disposition`: `admitted`; outcome `outcome`: `result_returned`
- profile `srs.mcp.sdk_enforcement v0.1`, Ed25519 / RFC8785-JCS, metadata-only
- New UUIDs, signatures, timestamps, logs, and digests differ by design; the
  acceptance target is structural and constitutional equivalence.

See `ATTEMPT1_DIAGNOSTIC.md` for the frozen attempt-1 (`3be3749`) failure record.
