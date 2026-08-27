# SAM-LIVE-CHAIN0 — empirical proof and clean-replay lane

Status: **DRAFT / AUTHORITY_MOVEMENT=0 / DO NOT MERGE WITHOUT OWNER REVIEW**.

This lane follows merged `SAM-NATIVE-MCP-BIND0` (#74) and records two things
without conflating them:

1. the frozen evidence from the successful 2026-08-26 native Darwin/arm64 run;
2. a reconstructed harness intended to reproduce the same structural chain from
   a clean checkout.

The original historical `up.sh` was lost when a parallel session removed its
worktree. The replacement in `tools/sam_live_chain0/up.sh` is therefore labeled
**reconstructed**. Nothing in this lane claims byte identity with that lost file.

## Empirically established on 2026-08-26

The frozen run established:

- google/sam `v0.1.0-alpha.7` / `a5f2c4e` runs natively from the official
  Darwin/arm64 prebuilt release; no Go, Linux, Docker, cloud, or spend was
  required for that path;
- a local mock OIDC issuer was required on loopback, so the run was not
  air-gapped from its identity service;
- real control-plane + router + three `sam-node` processes formed the mesh;
- native semantic parity passed through
  `get_mesh_info → discover_remote_services → find_remote_tools → describe_remote_tool → call_remote_tool`,
  including `hello(name="SAM") → "Hello, SAM!"`;
- the governed `settle` call passed through `SamNativeConnector` composed on the
  existing `RemoteToolConnector` seam and emitted admission + outcome SRS receipts;
- both receipts shared `logical_call_id req:live-market0:1`;
- independent ARCS replay from the verifier's own environment returned aggregate
  exit code `0`.

Those historical facts are preserved in `evidence/sam-live-chain0/CHAIN_REPORT.md`
and `EVIDENCE_MANIFEST.md`.

## What this draft adds

`tools/sam_live_chain0/` reconstructs the smallest local replay surface:

- fail-closed verification of the exact official alpha.7 archive/binary pins;
- loopback mock OIDC;
- control-plane + router + three-node bring-up and teardown;
- loopback greeter and deterministic market MCP fixtures;
- a semantic probe over the actual SAM MCP tools;
- a governed market call using the merged `SamNativeConnector` and existing
  gateway adapter to emit a new admission/outcome packet.

The reconstructed harness has now been **run on the Darwin host** from a clean,
isolated checkout with the pinned release bytes and with the historical
`_sam-runtime` directory moved out of reach (proving self-sufficiency). The
clean-checkout reproduction passed every acceptance gate below, and its newly
emitted packet was independently replayed by ARCS at aggregate exit code `0`.
That reproduction evidence is frozen **separately** under
`evidence/sam-live-chain0-repro/`, a second native execution distinct from the
2026-08-26 historical bundle — new UUIDs, signatures, and logs, matched on
structural and constitutional facts, not byte identity. Owner review still gates
ready-flip and merge; this lane asserts no `AUTHORITY_MOVEMENT`.

## Clean replay acceptance

A clean replay may close only if all are true:

1. release archive and four required binaries match the frozen SHA-256 pins;
2. all process listeners used by the harness are loopback-only;
3. three real `sam-node` processes enroll and expose working MCP endpoints;
4. `get_mesh_info` succeeds for all three nodes;
5. native discover/find/describe/call produces `Hello, SAM!`;
6. governed fixture `settle` returns `admitted` / `result` and two receipt handles;
7. emitted receipt bytes exclude raw arguments/results according to the existing
   SRS profile;
8. admission and outcome share `req:live-market0:1`;
9. ARCS, from its own environment and without producer imports, returns aggregate
   exit code `0` on both new receipts;
10. teardown leaves no tracked process or known listener behind.

## Non-equivalences

- official prebuilt works on Darwin/arm64 != source build needs no Go toolchain;
- SAM discovery != DAGR eligibility;
- SAM authentication != execution authorization;
- route success != semantic truth;
- fixture `settled` != real financial settlement;
- signed receipt != external-world event truth;
- ARCS receipt verification != proposition verification;
- clean structural replay != byte-identical historical replay.

No ready flip or merge is authorized by this lane.
