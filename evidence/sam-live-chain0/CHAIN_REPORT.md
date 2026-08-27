# SAM live chain — run report (2026-08-26)

Empirical clearance of the unmoved hard gate from COUNTERPEDIA-RECON-LIVE0 /
SAM-SUBSTRATE-BUILD0, **executed natively on this darwin/arm64 host**.

## What ran

| Stage | Result | Evidence |
|---|---|---|
| real sam-node (L04) | **PASS** | 3-node libp2p mesh: control-plane + router + 3× sam-node + mock-OIDC, all `127.0.0.1`, alpha.7 native binaries |
| native tool flow / semantic parity | **PASS** | `get_mesh_info`→`discover_remote_services`→`find_remote_tools`→`describe_remote_tool`→`call_remote_tool`; `hello`→"Hello, SAM!", double-hop verbatim |
| LIVE-MARKET0 (L05) | **PASS** | governed `settle` via dagr-mcp `SamNativeConnector` (#74, composed on `RemoteToolConnector`) → `admitted`/`result`, 2 signed SRS receipts |
| MarketAuditPacket export | **PASS** | `state/market-audit-packet/` — admission + outcome receipts + issuer trust bundle |
| ARCS offline replay (L06) | **PASS** | `arcs-verify` (own venv, no producer import) — all checks PASS on both receipts, aggregate exit 0 |

## Key facts

- **SAM pin:** google/sam `v0.1.0-alpha.7` (commit `a5f2c4e`). Binaries: official
  prebuilt `sam_Darwin_arm64.tar.gz` (sha256 `6c97d964…`, checksum-verified). **No Go
  toolchain, no docker, no Linux, no cloud, no spend.**
- **Not air-gapped (as HARNESS-RECON0 predicted):** control-plane hard-requires a
  reachable OIDC issuer; satisfied locally by the repo's own `mock_oidc.py` on
  `127.0.0.1:18080`. 8 local listening sockets, loopback only.
- **Governed transaction:** `logical_call_id req:live-market0:1` — admission (`admitted`)
  + outcome (`result_returned`) of the same call. Profile `srs.mcp.sdk_enforcement v0.1`,
  Ed25519 / RFC8785-JCS, metadata-only (`raw_content_exclusion: PASS`).

## Non-conflation (asserted, not hidden)

- route-success ≠ authorization ≠ semantic truth.
- The `market` backend is a deterministic test fixture; a settled result is a
  transport+routing+governance fact, **not** a real-world financial settlement.
- The verifier recomputes *receipt* structure/signature; it does not prove the
  real-world event. `emitter assertion ≠ recomputed finding` holds.

## Posture

- All processes are local, unprivileged, `127.0.0.1`-bound; teardown via
  `harness/down.sh` (or kill the recorded pids).
- Harness lives in `_sam-runtime/harness/` (relocated after the original
  `feat/sam-live-harness0` git worktree was removed by a parallel session).
- AUTHORITY_MOVEMENT=0. Nothing merged, nothing pushed, no ratification claimed.
