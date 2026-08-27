# SAM-LIVE-CHAIN0 — clean-checkout reproduction (2nd generation)

This bundle records a **clean-checkout reproduction** run of the reconstructed
harness, distinct from the historical 2026-08-26 empirical run under
`evidence/sam-live-chain0/`. It was produced from an isolated worktree with the
historical `_sam-runtime` directory moved out of reach and a freshly downloaded
pinned release asset — proving the harness is self-sufficient.

Reproduction date: 2026-08-27 (local darwin/arm64 host).

## Posture

- Fresh `sam_Darwin_arm64.tar.gz` download; `verify_pins.py` PASS on all 5 SHAs.
- Historical `_sam-runtime/` moved aside for the whole run (hostile self-sufficiency check).
- Loopback-only; mock OIDC on 127.0.0.1; no cloud, no spend, no source build.
- `market` is a deterministic fixture; `settled` is NOT a financial event.
- `AUTHORITY_MOVEMENT=0`; no PR/merge/ratification asserted by this run.

## Gate results (binary)

| Gate | Result |
|---|---|
| static pytest gate (10 tests, incl. policy regression) | PASS |
| fresh pinned asset (verify_pins 5/5) | PASS |
| historical `_sam-runtime` inaccessible | PASS |
| policy seed | PASS |
| router enrollment | PASS |
| 3 real sam-node mesh | PASS |
| `get_mesh_info` ×3 | PASS |
| `discover → find → describe → call_remote_tool` | PASS |
| `Hello, SAM!` | PASS |
| governed `settle` | PASS |
| independent ARCS (own env) aggregate exit | 0 |
| teardown / ports free | PASS |

## Structural facts (NOT byte-identical to the historical run)

- `logical_call_id`: `req:live-market0:1` (admission + outcome, same call)
- admission `disposition`: `admitted`; outcome `outcome`: `result_returned`
- receipt kinds: `admission`, `outcome`
- profile `srs.mcp.sdk_enforcement v0.1`, Ed25519 / RFC8785-JCS, metadata-only
- New UUIDs, signatures, timestamps, logs, and digests differ from the historical
  run by design. The acceptance target is **structural and constitutional
  equivalence**, not replay of historical randomness.

## Repair delta vs `3be3749` (immutable failed attempt 1)

`3be3749`'s harness was landed but never run clean; running it revealed three
defects, all fixed in the repair commit that carries this bundle:

1. **Missing `/policies` seed** (up.sh) — router enrolled `403: role not
   authorized`. Fixed by seeding `group:sam-live-chain0 → sam:role:router,
   sam:role:node` before router start. (`group:sam-live-chain0` because this
   fixture's mock issues that group to every client, router-client included.)
2. **`probe_semantic.py` tool parsing** — read `structuredContent["tools"]`, but
   alpha.7's Go sam-node returns a bare JSON array in `content`; every discovery
   yielded `[]`. Fixed with a shape-tolerant extractor.
3. **`live_market0.py` tool parsing** — identical bug; identical fix.

See `../sam-live-chain0/` for the historical run and `ATTEMPT1_DIAGNOSTIC.md`
for the frozen attempt-1 failure record.
