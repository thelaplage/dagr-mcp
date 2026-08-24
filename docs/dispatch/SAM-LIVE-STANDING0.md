# SAM-LIVE-STANDING0

PROGRAM: COUNTERPEDIA-SAM-SOURCE-ALIGNMENT0
LANE: L03
REPO: thelaplage/dagr-mcp
BASE: feat/federation-live-sam0
STATUS: DRAFT
SOURCE_PIN: google/sam@2cbd07acd6ed66ddc56c29ca2e3188721255d151
DEPENDS_ON: FEDERATION-LIVE-SAM0
AUTHORITY_MOVEMENT: 0

## Mission
Correct the standing and reporting surface of FEDERATION-LIVE-SAM0 so reference/fake transport parity cannot be rendered as a completed real-SAM network proof.

The historical lane name may remain. The execution report must decompose what was actually evaluated.

## Required invariants

`reference_transport_pass != real_SAM_evaluated`.

`real_SAM_not_evaluated != real_SAM_failed`.

`SAM_route_success != Countervail_ALLOW`.

`transport_parity != semantic_truth != evidence_admission`.

## Required work
1. Reuse the existing live-SAM implementation and source pin; do not create another transport adapter.
2. Define a lane-local report shape using existing repo result conventions. It must separately report at least:
   - source pin verified;
   - reference/fake transport evaluated + result;
   - real SAM transport evaluated + result;
   - artifact/digest parity evaluated + result;
   - identity-binding evaluation;
   - unresolved/not-evaluated reasons.
3. `RealSamTransportUnavailable` or equivalent environment absence must yield `NOT_EVALUATED` for real SAM execution, never PASS.
4. A real SAM attempt that ran and failed must remain FAILED, not NOT_EVALUATED.
5. Do not emit a single undifferentiated PASS if some required semantic dimensions were not evaluated.
6. Preserve transport-neutral artifact IDs/digests and keep transport diagnostics outside semantic identity.
7. Remove none-pinned authority-shaped runtime fields from report or transport observations; structural absence plus explicit limitations is required.
8. External/readme wording must not claim "live SAM proof completed" unless the real transport dimension was actually evaluated successfully.

## Required negative tests
- reference adapter passes and overall report says real SAM PASS;
- real transport unavailable is converted to PASS;
- real transport executed and failed is converted to NOT_EVALUATED;
- source pin mismatch still reports parity PASS;
- transport latency/peer metadata changes semantic artifact identity;
- a real SAM route success is rendered as Countervail authorization or DAGR admission;
- overall PASS hides a `NOT_EVALUATED` dimension.

## Acceptance gates
- Existing reference/fake tests remain deterministic.
- One fixture proves `reference=PASS`, `real_sam=NOT_EVALUATED` with no overall semantic overclaim.
- One fixture proves a real-attempt failure remains FAILED.
- If live credentials/environment are available, a real run may be evaluated, but the lane must not require them to preserve honest standing.
- Report serialization is deterministic and carries explicit limitation/reason refs.

## STOP conditions
STOP if implementation would require:
- inventing a global DAGR verification state;
- treating test infrastructure availability as evidence about SAM correctness;
- rewriting historical run evidence rather than superseding/reporting it;
- changing canonical federation artifact identity to include SAM-specific diagnostics.

## PR posture
DRAFT stacked correction. No merge. Report the pre/post standing behavior, test matrix, and `AUTHORITY_MOVEMENT=0`.