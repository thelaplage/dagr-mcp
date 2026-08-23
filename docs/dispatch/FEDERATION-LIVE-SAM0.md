# FEDERATION-LIVE-SAM0

PROGRAM: COUNTERPEDIA-FEDERATION-WAVE2
LANE: L05
REPO: thelaplage/dagr-mcp
BASE: main
STATUS: DRAFT
AUTHORITY_MOVEMENT: 0

## Goal
Run the federation proof over a real pinned google/sam deployment while preserving the transport-neutral artifact semantics already defined in Wave0/Wave1.

## Required invariants
`SAM peer identity != Counterpedia node identity != delegated authority`.
`SAM discovery != DAGR admission`.
`SAM route success != Countervail ALLOW`.
`SAM transport failure != evidence absence`.

## Required work
1. Pin an exact google/sam release/commit and record the pin in machine-readable config.
2. Stand up at least three SAM-connected roles matching the reference E2E topology: researcher/orchestrator, worker/registrar, verifier/mirror.
3. Reuse existing `SamTransportAdapter`/MCP seams where available; do not create alternate federation object formats.
4. Demonstrate transport of submission/receipt/registry/memory/query references or packets without modifying their canonical bytes/digests.
5. Bind SAM transport peer IDs through FEDERATION-IDENTITY0-compatible metadata when available; otherwise expose unresolved binding explicitly.
6. Exercise service discovery, remote MCP invocation, disconnect/reconnect, and exact-byte fetch.
7. Capture transport observations and latency/error diagnostics with authority_effect:none.
8. Provide a one-command local proof script plus deterministic fake/reference fallback using the same application semantics.
9. Fail closed on SAM version mismatch, peer identity mismatch, payload digest mismatch, timeout, partial response, and unknown remote operation.

## Acceptance proof
The same Wave2 run must produce the same native artifact IDs/digests over reference transport and real SAM transport. Any transport-specific differences must remain outside semantic identity.

## Non-goals
No SAM fork. No SAM as constitutional dependency. No DAGR/SRS/Counterpedia semantic changes. No consensus. No auto-trust from peer authentication.
