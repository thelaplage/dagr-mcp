# Capability Mapping

This is a small implementation-neutral inventory of current DAGR MCP behavior.
It is not a canonical capability registry. Detailed bindings to externally
owned vocabulary surfaces are declared in `.ecosystem/CAPABILITY_BINDINGS.yaml`;
that file references GARP SDK, SRS, ARCS Verify, Workbench, Amnesiac, and
Countervail material rather than redefining those terms here.

Under the current pilot update, governed-action/protocol authority remains
unresolved unless current repository evidence establishes a ratified owner.
`arcs-srs` is the relevant evidence/schema semantic authority, ARCS Verify is
an independent verifier counterpart, and `garp-sdk` is treated as historical
source-estate vocabulary rather than current authority by default.

| Capability | Status here | Mapping |
|---|---|---|
| `TOOL_EXECUTION` | Implemented, validated | Governed MCP `tools/call` execution through configured bindings; refused/deferred calls stop before execution |
| `RESOURCE_READ` | Partial | Read-class tool calls and custody vocabulary include resource-read concepts; no general MCP resource/read binding is claimed |
| `EXTERNAL_ACTION` | Partial | Harness class and remote connector behavior cover external action shape; no canonical semantics owned here |
| `CREDENTIALED_ACTION` | Partial | Remote connector credential provider path exists; credentials are excluded from responses and receipts |
| `MEMORY_PROPOSE` | Implemented as optional adapter exposure | `amnesiac.propose_candidates`; proposal only, never admission |
| `MEMORY_ADMIT` | Not implemented here | Durable memory admission is owned elsewhere |
| `MEMORY_RECORD_OUTCOME` | Implemented as optional adapter exposure | `amnesiac.record_outcome`; refs-only bridge |
| `MEMORY_COMPILE_CONTEXT` | Partial | `amnesiac.compile_context`; deterministic reference selector v0, not full governed context planner |
| `MEMORY_REQUEST_REOPENING` | Implemented as optional adapter exposure | `amnesiac.request_reopening`; caller cannot force reopening |

## Ownership Rules

DAGR MCP owns the adapter behavior that exposes or governs these actions at the
MCP boundary. It does not own canonical ecosystem capability semantics, SRS
normative semantics, ARCS validity, or Amnesiac memory-admission semantics.

## Evidence

Primary evidence is in `README.md`, `docs/PRODUCT_ARCHITECTURE.md`,
`docs/AMNESIAC_TOOLS.md`, `dagr_mcp/fastmcp_binding.py`,
`dagr_mcp_sdk_binding/adapter.py`, `packages/dagr-mcp-sdk-v2/`, and the
corresponding test suites.
