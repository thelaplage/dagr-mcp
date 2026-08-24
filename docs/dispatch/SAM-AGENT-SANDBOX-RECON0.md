# SAM-AGENT-SANDBOX-RECON0

PROGRAM: COUNTERPEDIA-SAM-SOURCE-ALIGNMENT0
LANE: L00
REPO: thelaplage/dagr-mcp
BASE: main
STATUS: DRAFT
SOURCE_PIN: google/sam@2cbd07acd6ed66ddc56c29ca2e3188721255d151
AUTHORITY_MOVEMENT: 0

## Mission
Produce a source-grounded recon of SAM's Agent Sandbox Connector API and define the exact semantic seam Counterpedia/DAGR may consume without importing SAM identity, admission, or egress semantics as DAGR authority.

This is recon first. Do not ship a production adapter in this lane.

## Source surfaces to read
At minimum inspect the pinned `api/sam.proto` definitions and the concrete implementation paths for:
- `AgentBundle`
- `AgentEgress`
- `AgentSecret`
- `AgentIngress`
- `AgentAttachRequest/Response`
- `AgentDetachRequest/Response`
- `AgentRefreshRequest/Response`
- `AgentStatusRequest/Response`

Trace enough implementation to establish what is host-enforced, what is merely declared, what is persisted, what is idempotent, and what is removed on detach. If the source does not establish a behavior, mark it unresolved.

## Required outputs
1. `docs/recon/SAM_AGENT_SANDBOX_RECON0.md` with exact source citations and source pin.
2. `generated/recon/sam-agent-sandbox-crosswalk.v0.1.json` generated deterministically.
3. A deterministic checker/test that rejects unsupported semantic upgrades.
4. A small implementation-seam note naming the downstream owning repos without writing their adapters here.

## Required semantic distinctions
Preserve at least:

`external_platform_id != sam_agent_id != transport_peer_id != Counterpedia_node_id != organization_identity`.

`agent_bundle_declared != agent_attached != task_authorized != sam_callee_authorized != executed`.

`agent_egress_allowlisted != Countervail_ALLOW`.

`credential_path_present != secret_value_observed`.

`SAM_agent_attach != DAGR_admission`.

`AgentStatus.attached != executing != authorized_for_this_context`.

`bundle_portable_across_hosts != memory_admitted != identity_equivalent`.

## Load-bearing source rule
SAM's own connector comment says identity must never arrive in-band from inside the sandbox because the agent could lie about it. Preserve that principle explicitly. Any future Counterplayer binding must receive host/platform identity through a trusted outer boundary rather than allowing a task payload or model output to self-assert its governed principal.

## Structural-absence rule
Do not put `authority_effect`, `admission_effect`, `trust_effect`, `standing_effect`, `truth_effect`, or equivalent none-pinned fields on crosswalk entries. Non-authority is expressed by minimal licensed meaning plus explicit `does_not_prove` entries. `AUTHORITY_MOVEMENT: 0` remains lane/run metadata only.

## Required adversarial cases
- agent payload attempts to provide its own governed `agent_id`;
- bundle carries secret material rather than a secret path/ref;
- external ID is rendered as equivalent to canonical SAM agent ID;
- `AgentAttach` is rendered as Countervail authorization or DAGR admission;
- egress allowlist is rendered as permission to execute a specific task;
- `AgentStatus.attached=true` is rendered as current execution or authorization;
- detach is assumed to revoke unrelated DAGR/Counterpedia identity bindings;
- source behavior is missing and generator fabricates a stronger meaning.

## Acceptance gates
- Every positive semantic claim cites exact pinned SAM source.
- Every crosswalk row carries at least one `does_not_prove` statement.
- Generator is byte-deterministic for an unchanged source map.
- Unsupported/unknown source behavior fails closed to `unresolved` or `observation_only`.
- No authority-shaped none-pinned field exists in the generated crosswalk entries.
- No existing dagr-mcp runtime semantics are changed.

## STOP conditions
STOP and record the seam if implementing the recon would require:
- guessing how SAM host enforcement works without locating source;
- treating in-band agent identity as governed identity;
- treating SAM attach/egress/status as DAGR or Countervail decisions;
- changing DAGR constitutional contracts;
- live SAM credentials to prove a point that can remain unresolved.

## PR posture
DRAFT only. No merge. Report source pins, exact unresolved questions, deterministic test result, and `AUTHORITY_MOVEMENT=0`.