# LIVE-SAM0

PROGRAM: COUNTERPEDIA-RECON-LIVE0
LANE: L04
REPO: thelaplage/dagr-mcp
BASE: main
STATUS: DRAFT
AUTHORITY_MOVEMENT: 0

## Goal
Run the reconciled federation proof over a real pinned `google/sam` deployment and prove transport parity against the reference transport without changing native artifact semantics.

## Prerequisites
- SAM-SOURCE-ALIGNMENT-CLOSE0 says `LIVE_SAM_READY:true` on one exact SAM source pin.
- FEDERATION-COMPOSE0 passes on reference transport.
- No unresolved HIGH NE-11 finding on transport/identity objects consumed here.

## Topology
Stand up at least three independently identified roles:
1. buyer/orchestrator;
2. provider/worker;
3. witness/verifier.
Separate process/container storage and identities. No shared mutable state as a substitute for transport.

## Required proof
Run the same logical transaction over:
A. deterministic reference transport;
B. real SAM.
Compare native artifact identities/digests at every semantic boundary. SAM metadata may differ; native semantic artifacts must not.

## Required invariants
`sam_peer_authenticated != counterpedia_node_identified != organization_recognized != action_authorized`
`sam_discovered != market_eligible`
`sam_route_success != execution_authorized`
`sam_transport_failure != evidence_absent`
`reference_transport_PASS != real_sam_PASS`

## Standing honesty
If real SAM cannot be installed, started, connected, or exercised on the exact pin, emit `NOT_EVALUATED` with the blocking cause. Never substitute fake/reference transport success for a real-SAM PASS.

## Tests / scenarios
- discovery of provider capability hint;
- exact-byte request/response transfer;
- remote invocation under separate Countervail/DAGR authorization;
- receipt announcement/fetch;
- witness delivery;
- disconnect/reconnect;
- wrong peer/node binding;
- route succeeds but authorization refuses;
- source pin/version mismatch.

## Outputs
- machine-readable real-SAM run report with exact SAM pin;
- reference-vs-SAM parity table;
- native artifact digest comparison;
- transport observations separate from semantic outcomes;
- bounded failure reports.

## Non-goals
No SAM fork, no SAM-native Counterpedia ontology, no SAM authority semantics, no hidden direct HTTP/import path presented as SAM.

## Acceptance
A reviewer can prove that the same native Counterpedia/DAGR/SRS artifacts retain identical semantic identity over reference transport and real SAM, or the lane honestly remains NOT_EVALUATED.