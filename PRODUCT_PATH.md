# Product Path

## Human Problem

Developers need to add governed enforcement and portable evidence to MCP
activity without rewriting each server or trusting the emitter as its own
verifier.

## Existing Workflow

MCP calls usually execute through host or framework-specific paths. Developers
may have tracing or logs, but often lack an enforceable pre-execution decision
and independently verifiable portable evidence for the governed boundary.

## Invariant

A proposed consequential tool action must be governed before execution.

DAGR MCP enforces that invariant only for calls routed through the configured
boundary. It does not claim coverage for MCP traffic that bypasses the binding
or for retention behavior inside the underlying server.

## Integration Boundary

The current integration boundaries are:

| Boundary | Current fact |
|---|---|
| FastMCP middleware | Active compatibility path in the root distribution |
| Official MCP SDK 1.x | Active binding through `dagr_mcp_sdk_binding` |
| Protocol-neutral core | Extracted substrate under `packages/dagr-mcp-core` |
| Official MCP SDK 2.x | Isolated binding under `packages/dagr-mcp-sdk-v2` |
| Service composition | Neutral request/response, connectors, and receipt access |
| Amnesiac | Optional memory operations exposed through DAGR |

## First Proof Moment

The current proof moment is byte-grounded:

1. A safe/read call is admitted through a configured DAGR boundary.
2. A dangerous or policy-refused call is prevented before execution.
3. Metadata-only SRS receipts are emitted according to disposition and outcome.
4. Serialized receipts are independently verified by ARCS Verify.

Receipt cardinality is variable. An admitted call that runs and returns normally
usually emits an admission and outcome receipt. A refusal or deferral emits a
single terminal admission receipt. Some read configurations emit no pre-execution
receipt, and an outcome sink failure after execution leaves an admission receipt
plus local gap telemetry rather than fabricating an outcome.

## Expansion

Named vertical packs can route their consequential MCP actions through this
boundary. GARPedia can consume verified projections. Amnesiac can expose
candidate proposal, reference-context selection, reopening requests, and
refs-only outcome recording through DAGR. Countervail or managed deployments can
operate policy and runtime configuration around the boundary.

Those are expansion paths, not claims that every integration is completed in
this repository.
