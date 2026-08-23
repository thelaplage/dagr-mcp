# SAM-SEMANTICS-RECON0

## Mission

Produce a source-grounded semantic crosswalk between Google Sovereign Agent Mesh (SAM) and the DAGR/MCP boundary without importing SAM-specific authority semantics into DAGR.

## Starting point

Review the current `google/sam` repository and current `dagr-mcp` contracts. Treat SAM as an external execution/network substrate. Distinguish what SAM observations prove from what they do not prove.

## Required outputs

1. `docs/recon/SAM_SEMANTICS_RECON0.md`
2. `generated/recon/sam-semantics-crosswalk.v0.1.json`
3. deterministic checker/tests for the crosswalk

The crosswalk must cover at least:
- node identity / enrollment
- router / relay membership
- service advertisement
- service discovery
- tool discovery
- invocation request
- invocation result
- policy / role / target authorization assertions exposed by SAM
- lease/session/connection observations where present
- inference/provider-routing observations where present

For each assertion, record:
- SAM source surface
- observed field / event / API
- minimal meaning licensed by that surface
- explicit non-equivalences
- whether it is identity, discovery, transport, authorization, execution, evidence, or derived state
- `authority_effect`, defaulting to `none` unless an existing DAGR contract explicitly licenses otherwise

## Mandatory non-equivalences

The lane must explicitly preserve:

`authenticated != discoverable != invocable != authorized_for_this_context != executed != output_trusted != evidence_supported != admitted != published`

SAM identity must not be treated as Counterpedia record identity. SAM authorization must not be treated as DAGR domain admission, evidentiary standing, factual truth, publication standing, or delegated authority beyond what the SAM source actually proves.

## Constraints

- Recon first; no production SAM adapter in this lane.
- Do not modify existing receipt wire formats.
- Do not introduce a new global DAGR state.
- Do not claim that SAM is an officially supported Google product beyond what its repository states.
- Pin reviewed SAM revision/tag/commit and retrieval date in the recon output.
- If current SAM behavior differs from prior notes, current source wins and the discrepancy must be recorded.
- `AUTHORITY_MOVEMENT = 0`.

## Acceptance gates

- Every semantic claim is tied to an exact SAM source file/API/doc/revision.
- Every positive mapping has at least one explicit `does_not_prove` entry.
- Unknown/unstable SAM surfaces fail closed to `observation_only`.
- Generated JSON is deterministic under repeated generation.
- Existing `dagr-mcp` tests remain unchanged except for new additive recon tests.

## STOP conditions

STOP rather than inventing semantics if:
- a required SAM assertion cannot be located in current source;
- the same SAM field has materially conflicting meanings across code/docs;
- mapping it would require changing a constitutional DAGR contract;
- the lane would need SAM network credentials or a live public testnet to establish a claim that can instead remain unresolved.

## PR posture

DRAFT only. Do not merge. Report source pins, tests, unresolved mappings, and `AUTHORITY_MOVEMENT`.