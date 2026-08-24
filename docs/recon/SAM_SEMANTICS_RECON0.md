# SAM-SEMANTICS-RECON0: SAM <-> DAGR/MCP semantics crosswalk

> Status: RECON. DRAFT. Non-normative until a separate lane, with its own
> review, wires any of this into a real adapter. This document and its
> companion JSON make no admission, execution, or evidentiary claims of
> their own; see [`AUTHORITY_MOVEMENT`](#authority_movement) below.

## Mission

Produce a source-grounded semantic crosswalk between Google's
[Sovereign Agent Mesh (SAM)](https://github.com/google/sam) and the
DAGR/MCP boundary this repository implements, without importing SAM-specific
authority semantics into DAGR. SAM is treated throughout as an external
execution/network substrate: something DAGR can, in a future lane, observe
and describe, never something DAGR trusts by default.

This is lane `SAM-SEMANTICS-RECON0` (`docs/dispatch/SAM-SEMANTICS-RECON0.md`).
It is recon-only: no production SAM adapter, no new admission or execution
behavior, and no change to any existing receipt wire format ships in this
lane.

## Source pin

| | |
|---|---|
| Repository | https://github.com/google/sam |
| Revision reviewed | `2cbd07acd6ed66ddc56c29ca2e3188721255d151` |
| Retrieved | 2026-08-24T07:29:37Z |
| Upstream disclaimer | "This is not an officially supported Google product." (README.md, *Disclaimer* section, at the pinned revision) |

If current SAM source at a later revision differs from what is recorded
here, the current source wins and the discrepancy should be recorded as a
new entry or an amendment to this pin -- not silently assumed away.

## Method

The crosswalk was built by reading the SAM repository's own source at the
pinned revision -- primarily `api/sam.proto` (the wire schema shared by every
SAM component), `internal/identity/` (Biscuit minting/verification, OIDC/JWT
translation), `internal/node/` (enrollment, service registry, discovery
consumption, MCP handlers, per-request authorization, label gating, the
OpenAI-compatible inference facade), and `internal/router/` (relay ACLs,
mutual authentication, lease renewal, mesh-event verification) -- and, for
each of the ten required assertion categories, recording:

- the exact SAM source surface (file + line range) the assertion comes from;
- the observed field / event / API;
- the **minimal meaning** that surface actually licenses;
- explicit **non-equivalences**: what it does *not* prove;
- a semantic class (`identity`, `discovery`, `transport`, `authorization`,
  `execution`, `evidence`, or `derived_state`);
- an `authority_effect`, which is `none` for every single entry in this
  lane (see [AUTHORITY_MOVEMENT](#authority_movement)).

The machine-readable form is
[`generated/recon/sam-semantics-crosswalk.v0.1.json`](../../generated/recon/sam-semantics-crosswalk.v0.1.json),
produced deterministically by
[`tools/generate_sam_semantics_crosswalk.py`](../../tools/generate_sam_semantics_crosswalk.py).
Structural and content invariants are checked by
[`tests/test_sam_semantics_recon.py`](../../tests/test_sam_semantics_recon.py).
Re-running the generator against an unchanged pin reproduces the committed
JSON byte-for-byte; that equality is itself a test.

## Crosswalk summary

18 grounded (or, in one case, deliberately fail-closed) entries cover all
ten required categories:

| Category | Entries |
|---|---|
| Node identity / enrollment | `SAM-ID-01`, `SAM-ID-02` |
| Router / relay membership | `SAM-ROUTER-01`, `SAM-ROUTER-02` |
| Service advertisement | `SAM-SVC-ADV-01`, `SAM-SVC-ADV-02` |
| Service discovery | `SAM-DISC-01` |
| Tool discovery | `SAM-TOOL-DISC-01` |
| Invocation request | `SAM-INVOKE-01` |
| Invocation result | `SAM-INVOKE-RESULT-01` |
| Policy / role / target authorization | `SAM-AUTHZ-01`, `SAM-AUTHZ-02`, `SAM-AUTHZ-03` |
| Lease / session / connection | `SAM-LEASE-01`, `SAM-CONN-01`, `SAM-UNRESOLVED-01` |
| Inference / provider-routing | `SAM-INFER-01`, `SAM-INFER-02` |

Full field-level detail (source citation, minimal meaning, non-equivalences)
lives in the JSON, keyed by entry `id`; the notes below are the narrative
summary of what fell out of reading the source.

### What SAM's own source already says about its non-authorization surfaces

Two of the most load-bearing findings in this recon are not inferences --
they are direct quotes from SAM's own doc comments:

- `api/sam.proto` on `ServiceAnnounce` (the gossip message that drives
  service/tool discovery): "It is a routing hint signed at the pubsub layer
  by the announcing peer: consumers use it for freshness and load
  awareness, **never for authorization**."
- `internal/node/discovery/discovery.go`'s package doc: "Announcements are
  routing hints authenticated by the pubsub layer's message signing --
  **never authorization inputs**."

SAM's authors already draw the `authenticated != authorized_for_this_context`
line for gossip. This recon's job was to find where SAM draws that line
*everywhere else* (enrollment, relay membership, per-request Datalog
authorization, label matching, tool-call invocation) and make each of those
boundaries explicit and separately citable, since the mandatory
non-equivalence ladder for this lane has more links than that one.

### Identity: two distinct, non-interchangeable principals

SAM has two identity concepts that must not be confused with each other or
with anything in Counterpedia/DAGR:

1. A **peer_id**: a libp2p key-derived identifier, bound into a Biscuit at
   enrollment (`SAM-ID-01`). This is a transport/cryptographic identity for
   one running node process.
2. An **agent identifier**: a DNS-shaped, operator-namespaced policy string
   (`api/agent.go`), asserted by the connecting node on a per-request basis
   and injected into the Datalog authorizer as a claim, not trusted from
   inside the token (`SAM-ID-02`).

Neither is, or should be mapped onto, Counterpedia record/subject identity.
Both are scoped entirely to one SAM mesh's own operator namespace.

### Authorization is per-request, per-callee, and never portable

The single most important finding for future integration work: SAM
authorization (`SAM-AUTHZ-01`) is a Datalog proof evaluated **locally by
the peer being called, for one specific request, right now** -- over facts
that peer injects itself, plus whatever role/target grants were compiled
into the caller's Biscuit at mint time, plus whatever dynamic policy rules
the callee currently holds. A pass on one node is not evidence of a pass
anywhere else, is not a record of anything, and expires with the Biscuit.
It is not, and cannot be, treated as a DAGR admission decision.

### Discovery and advertisement are unverified until independently checked

Service advertisement (DHT presence, gossip `ServiceAnnounce`) and tool
discovery both have an "unverified claim" layer and, where SAM's own code
needs something stronger, a separate verification step layered on top:

- DHT advertisement is gated behind a live liveness probe of the backend
  (`SAM-SVC-ADV-01`), but that only proves the backend answered a probe --
  not that it is authorized for any given caller.
- `find_remote_tools` explicitly re-verifies gossip-derived tool candidates
  by opening a live MCP session and calling `ListTools` before returning
  them (`SAM-TOOL-DISC-01`) -- the implementation itself does not trust
  gossip alone.
- Label-based routing (`region`, etc.) is gossip-advertised for ranking
  only; a caller that actually requires a label fetches the peer's Biscuit
  directly and checks a control-plane-attested fact, fail-closed
  (`SAM-AUTHZ-03`).

### Invocation: transport success is not authorization, and result delivery is not truth

`CallMCPTool` (`SAM-INVOKE-01`) distinguishes a transport/reachability
failure (retried) from `ErrAuthRejected`, a distinct sentinel the source
itself documents as "a service-level authorization denial from a remote
peer, as opposed to a transport/connectivity failure" -- and does not retry
it. A returned `CallToolResult` (`SAM-INVOKE-RESULT-01`) proves the
authenticated round trip completed; no additional content-level signature
over the result payload was found in the reviewed source, so `executed` in
SAM's sense never implies `output_trusted`, `evidence_supported`,
`admitted`, or `published` in DAGR's sense.

## Mandatory non-equivalences

Preserved verbatim, in order, and never collapsed by any entry in the
crosswalk:

```
authenticated != discoverable != invocable != authorized_for_this_context !=
executed != output_trusted != evidence_supported != admitted != published
```

SAM identity must not be treated as Counterpedia record identity. SAM
authorization must not be treated as DAGR domain admission, evidentiary
standing, factual truth, publication standing, or delegated authority
beyond what the cited SAM source actually proves.

## What this lane deliberately left unresolved

Per the lane's STOP conditions, a claim that could not be grounded in
current source was left unresolved rather than invented. One surface was
flagged `observation_only` for exactly this reason:

- **`SAM-UNRESOLVED-01` -- mesh-wide revocation propagation.** SAM routers
  verify `MeshEvent{BANNED, KEY_ROTATION, POLICY_UPDATE}` gossip
  (`internal/router/router.go` `verifyEvent`), but this pass did not trace
  the full propagation-latency or mid-session-eviction contract (that would
  require reading `internal/controlplane/*` and the DNS/TCP sync path,
  which were out of scope for this recon). Whether an already-open
  authenticated stream is forcibly closed when a `BANNED` event for its
  peer arrives elsewhere in the mesh is **not established** by this recon
  and must not be assumed.

No SAM network credentials, and no live public testnet interaction, were
needed to produce this crosswalk: everything above is grounded in the
public repository source at the pinned revision.

## Non-goals (this lane)

- No production SAM adapter, connector, or client ships in this lane.
- No existing DAGR receipt wire format was modified.
- No new global DAGR state was introduced.
- No claim beyond what `google/sam`'s own repository states about its
  support status is made (see the disclaimer quoted above).
- No SAM network credentials or live testnet access were used or required.

## AUTHORITY_MOVEMENT

`AUTHORITY_MOVEMENT = 0`. Every entry in the crosswalk carries
`authority_effect: "none"`, because no existing dagr-mcp contract currently
licenses any SAM assertion -- identity, discovery, or authorization -- to
carry DAGR admission, evidentiary, or authorization weight. This recon adds
mapping and vocabulary, not trust. dagr-mcp's own repository contract
(`CLAUDE.md`) already draws this line for its own receipts ("emitting a
receipt != verifying it != it being true"); this lane extends the same
discipline to an external substrate rather than making an exception for it.

## PR posture

DRAFT only. Not to be merged by this lane. See the dispatch record for
source pins, test results, and the `AUTHORITY_MOVEMENT` line the reviewing
human should check.
