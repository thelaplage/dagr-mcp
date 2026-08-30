# DAGR-NOOA-INTEROP-RECON0

**Status:** DRAFT recon lane / DO NOT MERGE  
**Authority:** `AUTHORITY_MOVEMENT=0`

## Mission

Determine whether an unmodified or minimally configured NVIDIA OO Agents / NOOA client can consume a DAGR-wrapped MCP server through ordinary MCP semantics.

Reference specimen: `espirado/labs-OO-Agents`, especially MCPManager, streamable HTTP, structured return contracts, tracing, progressive disclosure, secret resolution, and its explicit OS-level containment boundary.

## Questions to prove

1. MCP initialize compatibility.
2. `tools/list` compatibility.
3. `tools/call` compatibility.
4. Refused/deferred DAGR behavior as observed by NOOA.
5. Whether NOOA retries, rewrites, or masks typed refusals.
6. Whether metadata required by the DAGR/SRS boundary survives.
7. Whether NOOA trace identifiers can be correlated by reference with DAGR artifacts without becoming receipt authority.
8. Header/secret handling.
9. Cancellation/task behavior where exposed.
10. Exact incompatibilities and failure modes.

## Constraints

Do not add NOOA as the DAGR runtime, treat NOOA tracing as authoritative, treat AST validation as containment, copy NOOA memory/context semantics into Amnesiac, or build a bespoke adapter when plain MCP compatibility works.

Prefer docs-only recon. A tiny isolated example is allowed only if it avoids production dependency widening; any dependency must remain optional/dev/example scope.

## Terminal

`INTEROP = COMPATIBLE | PARTIAL | INCOMPATIBLE | NOT_EVALUATED`, with evidence for every claim.

## Deliverables

`docs/recon/DAGR-NOOA-INTEROP-RECON0.md` and, only if justified, an isolated interoperability example.