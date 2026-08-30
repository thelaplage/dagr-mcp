# DAGR-NOOA-INTEROP-RECON0 — initial recon

## External surface studied

`espirado/labs-OO-Agents` exposes MCP tools through `MCPManager`, supports streamable HTTP, traces nested method calls, validates typed outputs, and explicitly treats in-process code checks as defense in depth rather than containment.

## Adoption decision

Treat NOOA as an external agent client candidate, not as a DAGR runtime dependency or authority source. Plain MCP compatibility is preferred over any bespoke adapter.

## What may correlate

NOOA trace identifiers may be useful correlation references if an integration can carry them without mutating canonical DAGR/SRS semantics. Such traces remain client observations; they are not receipts and do not independently establish execution.

## Security boundary

NOOA-generated code execution and its AST/module checks are outside DAGR's containment guarantees. DAGR should govern exposed tool calls at its own boundary and must not imply that client-runtime sandboxing is provided by DAGR.

## Next construction question

Probe initialize, tools/list, tools/call, refusals/deferrals, metadata preservation, secret/header behavior, and cancellation/task semantics using ordinary MCP first. Add no production dependency unless a minimal optional example is justified.

**Current posture:** `READY_FOR_INTEROP_PROBE` / `AUTHORITY_MOVEMENT=0`.