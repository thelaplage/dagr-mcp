# CP-SAM-ADAPTER0

PROGRAM: COUNTERPEDIA-FEDERATED-PROOF0
LANE: L05
REPO: thelaplage/dagr-mcp
BASE: main
STATUS: DRAFT
AUTHORITY_MOVEMENT: 0

## Goal
Implement SAM as the first transport adapter for the portable node/submission/receipt/corpus contracts without allowing SAM identity, discovery, or routing facts to become DAGR or Counterpedia authority.

## Required invariant
`sam_peer_identity != counterpedia_node_identity != delegated_authority`, and `sam_can_route != countervail_allow`.

## Inputs from sibling lanes
- CP-NODE-CONTRACT0
- CP-SUBMISSION-PACKET0
- SRS-RECEIPT-MESH0
- RECEIPT-WITNESS0
- CP-CORPUS-MIRROR-MESH0

Treat those contracts as portable owners; if they are not yet merged, use pinned fixture copies/adapters in tests rather than silently redefining their semantics here.

## Deliverables
1. A thin `SamTransportAdapter`/equivalent that binds a SAM peer/service identity to a locally configured Counterpedia node descriptor reference without equating the two identities.
2. MCP-facing operations sufficient for the proof only: announce/fetch receipt, submit/fetch submission packet, announce/fetch corpus snapshot objects, and optional witness submission.
3. Explicit discovery projection translating SAM service/tool discovery into capability availability observations with `authority_effect: none`.
4. Fail-closed mapping for missing/ambiguous peer identity, unsupported contract version, malformed payload, transport refusal, and stale/unresolvable locator.
5. No admission logic, no Countervail decision logic, no SRS schema ownership, no corpus identity ownership.
6. Local/reference integration harness that can run with SAM when installed but also exercises the same adapter interface against a deterministic fake transport.
7. Source pins documenting the exact google/sam revision or release used by the implementation; SAM drift must be detectable.
8. Tests proving that authenticated/discovered/routable peers still cannot inject standing/admission/publication fields through the adapter.

## Stop conditions
- Do not fork SAM.
- Do not make SAM a required dependency for core package import/validation.
- Do not copy SAM authorization semantics into DAGR.
- Do not turn GossipSub/service discovery into corpus consensus.

## Acceptance
The same portable packet/receipt fixture can cross the adapter through a real or fake SAM transport and emerge byte-identical, while every authority/standing decision remains outside the adapter.
