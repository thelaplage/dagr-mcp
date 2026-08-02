# DAGR MCP product architecture

This document is the front-door map for the implemented repository. Historical
scope and decision records remain useful evidence, but they are not a current
inventory.

## Responsibility boundaries

| Layer | Owns | Does not own |
|---|---|---|
| `garp-ingest` | source capture, extraction, derivation and provenance | durable memory admission |
| ARCS Amnesiac | candidate, admission, refusal, reopening, supersession and context packets | MCP transport behavior |
| DAGR MCP | runtime admission boundary, dispatch control and signed receipt emission | independent verification or durable-memory ratification |
| ARCS Verify | recomputation from serialized artifacts | producer execution or truth of the underlying event |
| GARPedia | public record, sources, history, alternatives and verification projection | mutable admission authority |

## Implemented DAGR surfaces

### Root compatibility distribution

The root `dagr-mcp` distribution retains the FastMCP 3.x runtime and the
official MCP SDK 1.29.0 compatibility binding. It also contains the framework-
neutral Amnesiac contracts and the optional native producer adapter.

### Protocol-neutral core

`packages/dagr-mcp-core` contains the extracted lifecycle and receipt substrate.
It imports neither `mcp` nor `fastmcp`. Its extraction manifest keeps the fork
relationship to the root compatibility code explicit and testable.

### Official SDK v2 binding

`packages/dagr-mcp-sdk-v2` binds the neutral core to `mcp==2.0.0`, protocol
`2026-07-28`, through the public low-level `Server` surface. It does not migrate
the root distribution or select itself as a production default.

### Service and connector composition

`dagr_mcp_service` implements neutral request/response, binding selection,
in-process and remote connectors, receipt access and composition seams. The
historical gateway scope document records the pre-implementation analysis and is
marked accordingly.

### Amnesiac operations

The four exposed operations are:

- `amnesiac.propose_candidates` — proposal only; never admission;
- `amnesiac.compile_context` — deterministic reference selector v0; it is not the full governed context planner;
- `amnesiac.request_reopening` — producer transition guard, with caller unable
  to force reopening;
- `amnesiac.record_outcome` — refs-only bridge from a governed agent outcome to
  a candidate.

## Current product milestone

The next useful proof is a vertical governed-memory workflow, not another
binding abstraction:

1. construct or resolve real Amnesiac state;
2. call the Amnesiac operations through DAGR;
3. retain only refs, digests and lifecycle results at the DAGR boundary;
4. emit signed admission/outcome receipts;
5. verify those receipts independently in ARCS Verify;
6. project selected, excluded, refused and reconsiderable material to GARPedia.

The full governed context planner and GARPedia projection remain separate
product work. The existing reference selector must not be renamed or presented
as that planner.

## Claim discipline

A clean DAGR receipt establishes what the configured boundary recorded and
signed within its declared attestation limits. It does not establish that the
underlying event was true. A clean ARCS Verify report establishes structural and
cryptographic results for supplied bytes; it does not certify the producer.
