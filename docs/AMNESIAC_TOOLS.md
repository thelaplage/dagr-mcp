# Governed Amnesiac tools (FastMCP binding)

Four MCP tools that expose ARCS Amnesiac agent-memory operations through the
existing DAGR MCP admission runtime. The design preserves a three-layer split:

| Layer | Module | Imports the producer? |
| --- | --- | --- |
| Framework-neutral contract | `dagr_mcp/amnesiac_contracts.py`, `dagr_mcp/amnesiac_stores.py` | No |
| Native service (the only producer-backed layer) | `dagr_mcp/amnesiac_native.py` | Yes — lazily, at call time |
| FastMCP binding + install surface | `dagr_mcp/amnesiac_fastmcp.py` | No |

The native layer imports `arcs_amnesiac` **lazily** (availability is detected
with `importlib.util.find_spec`, real calls are method-local). Importing any
`dagr_mcp` module therefore never pulls the producer into the process — the
package's permanent import-direction guarantee holds
(`tests/test_no_private_import_roots.py` and the closure guards).

## Tools and classification

| Tool | Class | What it does |
| --- | --- | --- |
| `amnesiac.propose_candidates` | write | Constructs real `CandidateClaim` objects and persists them through an injected `CandidateStore`. **Proposal-only** — never admits, makes no ClaimGraph/ShadowGraph transition. |
| `amnesiac.record_outcome` | write | **Refs-only.** Bridges an `AgentOutcomeObject` (by ref via `AgentOutcomeStore`, or a refs-only mapping) to a `CandidateClaim` via `bridge_agent_outcome_to_candidate`. Refuses raw model output / prompts / claims / tool arguments. |
| `amnesiac.request_reopening` | write | Real ShadowGraph reopening through the real transition guard. Refuses FINAL. The caller cannot choose `REOPENED` — only an injected admission authority with a ratified decision ref can. |
| `amnesiac.compile_context` | read | `amnesiac.reference_context_selector.v0`: deterministic admitted-lifecycle + `record_scope` + `as_of` filtering + item budget, then the real `build_context_packet_from_graph`; persists the packet. Not the full governed context planner. |

## Installation

```python
from dagr_mcp.amnesiac_fastmcp import install_amnesiac_tools
from dagr_mcp.amnesiac_native import NativeAmnesiacService

service = NativeAmnesiacService(
    candidate_store=..., agent_outcome_store=..., claim_graph=...,
    shadow_graph=..., context_packet_store=...,
)
install_amnesiac_tools(server, service, emitter=signed_receipt_emitter, config=dagr_config)
```

`install_amnesiac_tools` merges the four tool classes into
`DAGRMiddlewareConfig.tool_classes`, **fails validation** if any classification is
unknown or omitted (so a write tool can never silently default to read), installs
(or validates) a single `DAGRMiddleware`, and reuses the existing
`SignedReceiptEmitter`. No parallel receipt family is created.

## Fail-closed behavior

When the native producer or a required persistence surface is unavailable, the
tool returns a FastMCP **error result** (`isError = true`) whose structured
content is `{"status": "capability_unavailable", "operation": ..., "detail": ...}`
— never an ordinary success dictionary. DAGRMiddleware therefore classifies the
outcome as `error_returned`, never `result_returned`.

## FINAL-guard detection

`request_reopening` asserts native FINAL refusal only when the installed producer
carries the merged FINAL guard, confirmed by **probe** (not by a symbol check): a
temporary FINAL `RejectedCandidate` is run through `reopen_candidate` for every
`ReopeningDecision`, and the guard is confirmed only if every call raises the
canonical FINAL-terminal refusal while the candidate stays FINAL. A stale,
pre-guard producer tree is reported as unguarded, and reopening stays
`capability_unavailable`.

## Optional dependency

The producer is an optional integration, not a base dependency:

```
pip install 'dagr-mcp[amnesiac]'   # arcs-amnesiac + garp-sdk
```

Without it, the binding still imports and fails closed with
`capability_unavailable`; the native test suite skips.
