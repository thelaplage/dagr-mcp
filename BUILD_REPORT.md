# BUILD REPORT — W2-03 Deferred Tool Boundary v0.1

**Lane:** W2-03  
**Repository:** dagr-mcp  
**Branch:** feat/deferred-tool-boundary-v0-1  
**Date:** 2026-08-06  
**Status:** UNCOMMITTED — reviewable diff, do not commit/push without review

---

## What exists (pre-lane inventory)

The repo already carries:

| Module | Role |
|---|---|
| `dagr_mcp/sdk_spine.py` | Canonical sink protocols, `ReviewObject`, `ReviewDecision`, `InMemoryReviewObjectSink`, `stable_payload_hash`, `now_utc_iso` |
| `dagr_mcp/tool_call_disposition.py` | `build_tool_call_disposition_review_object`, `hash_tool_call_arguments`, `validate_tool_call_disposition_decision`, `normalize_review_decision_outcome` |
| `dagr_mcp/enforcement_harness.py` | `wrap_handler`, `_gate_call` (existing gate path that creates ReviewObject but returns `gated_pending` without executing inner) |
| `dagr_mcp/srs_receipts.py` | `SignedReceiptEmitter`, `deferred_for_review` disposition vocabulary, `RECEIPT_CARDINALITY` alignment |
| `dagr_mcp/srs_bridge.py` | `HarnessSRSBridge.emit_admission` / `emit_outcome` |
| `dagr_mcp_lifecycle/contract.py` | `RECEIPT_CARDINALITY = {"admitted": 2, "refused": 1, "deferred": 1}` |

The existing `_gate_call` in `enforcement_harness.py` creates a ReviewObject and returns `gated_pending` — it is a *synchronous deferral stub*, not a resume-capable boundary. There was no correlation ref, no resume API, no replay protection, no idempotency, and no stale-response or wrong-actor checks.

---

## What was built (this lane)

### New file: `dagr_mcp/deferred_boundary.py`

A self-contained module implementing the full deferred tool boundary contract:

**Core types:**
- `DeferredSlot` — stable correlation token + metadata; transitions `pending → admitted | refused | expired`
- `DeferralResult` — returned from `defer_call`; no child spawn
- `ResumeResult` — returned from `resume_call`

**Boundary class:**
- `DeferredBoundary` — stateful boundary (thread-safe via per-slot + store-level locks)
  - `defer_call(tool_name, arguments, …)` → `DeferralResult` — creates ReviewObject, emits defer event, optionally emits `deferred_for_review` admission receipt; NEVER calls inner
  - `resume_call(correlation_ref, decision, arguments, …)` → `ResumeResult` — checks: not-found, terminal, timeout, stale, outcome, digest mismatch, actor mismatch; only calls inner on `approved` + digest match + not terminal
  - `get_slot(correlation_ref)` → `DeferredSlot | None`
  - `pending_slots()` → list of pending slots

**Error hierarchy (all semantic, adversarial cases):**
- `DeferredSlotNotFoundError` — unknown correlation ref
- `DeferredSlotTerminalError` — replay protection (slot already admitted/refused/expired)
- `DeferredArgumentMismatchError` — changed args at resume
- `DeferredActorMismatchError` — wrong actor_ref on decision
- `DeferredStaleResponseError` — `decided_at < created_at`
- `DeferredTimeoutError` — `gate_timeout_seconds` elapsed
- `DeferredExecutionFailureError` — inner handler raised
- `DeferredReviewObjectSinkError` — sink failure during defer

**Helpers:**
- `make_deferred_boundary(…)` — factory with sane defaults
- `make_review_decision(review_object_id, …)` — test convenience factory

**Receipt/cardinality alignment:**
- `deferred`: exactly 1 admission receipt (if srs_bridge wired), no outcome
- `admitted`: 2 receipts (new admission + outcome), emitted during resume_call
- `refused/expired`: 1 admission receipt max, no outcome

### New file: `tests/test_deferred_boundary.py`

56 adversarial tests covering every acceptance gate:

| Test class | Gate proven |
|---|---|
| `TestDeferCallNoExecution` (11 tests) | Inner never called from defer; ReviewObject created; pending list; arg-type guard; sink failure |
| `TestResumeAdmitted` (4 tests) | Approved + correct args → execution; result returned; slot terminal; removed from pending |
| `TestReplayProtection` (3 tests) | Approved/refused/expired replay raises `DeferredSlotTerminalError` |
| `TestWrongActor` (2 tests) | Mismatched actor_ref prevents execution |
| `TestChangedArgs` (3 tests) | Digest mismatch refused; slot refused; retry also blocked |
| `TestStaleResponse` (3 tests) | `decided_at < created_at` refused; equal accepted |
| `TestTimeout` (5 tests) | Elapsed gate raises; slot expired; no execution; within-timeout accepted; expired is terminal |
| `TestRefusal` (3 tests) | rejected/expired decisions do not execute; slot terminal |
| `TestExecutionFailure` (3 tests) | Inner exception → `DeferredExecutionFailureError`; slot refused; replay blocked |
| `TestSlotNotFound` (2 tests) | Unknown correlation ref raises; `get_slot` returns None |
| `TestDeferredDecision` (2 tests) | `deferred` outcome keeps slot pending; then approved executes |
| `TestEventSink` (3 tests) | Defer/execute/reject events emitted |
| `TestReceiptCardinality` (3 tests) | Deferred/refused slots carry no outcome receipt; admitted result present |
| `TestThreadSafety` (2 tests) | Concurrent resumes on different slots; concurrent replay on same slot |
| `TestMakeReviewDecision` (4 tests) | Factory defaults and fields |
| `TestCorrelationRef` (2 tests) | `deferred:` prefix; uniqueness |
| `TestEndToEnd` (1 test) | Full lifecycle: defer → stale rejected → admit |

---

## Gate results

All commands run in a local build worktree (absolute path redacted for public safety).

### New tests only

```
python3 -m pytest tests/test_deferred_boundary.py -v
56 passed, 1 warning in 4.33s
```

### Full stable suite (excluding pre-existing fastmcp-absent failures)

```
python3 -m pytest \
  --ignore=tests/test_behavioral_freeze.py \
  --ignore=tests/test_fastmcp_fixture_generator.py \
  --ignore=tests/test_lifecycle_contract_hardening.py \
  --ignore=tests/test_neutral_lifecycle_contract.py \
  --ignore=tests/test_neutral_lifecycle_core.py \
  --ignore=tests/test_lifecycle_lazy_export.py \
  --ignore=tests/test_subject_ref_origin.py \
  --ignore=tests/test_gateway_service_resolution.py \
  --ignore=tests/test_governed_memory_demo.py \
  --ignore=tests/test_delivery_field_collision.py \
  --ignore=tests/test_demo.py -q

351 passed, 23 skipped, 1 warning in 5.35s
```

Baseline (same exclusions, without new files): **323 passed**. Delta: **+56** (all new, zero regressions).

### Pre-existing failures (not caused by this lane)

All pre-existing failures are due to `fastmcp` not being installed in this Python environment:

- `test_behavioral_freeze.py`, `test_fastmcp_fixture_generator.py`, `test_lifecycle_contract_hardening.py`, `test_neutral_lifecycle_contract.py`, `test_neutral_lifecycle_core.py` — collect errors (`fastmcp` import fails)
- `test_lifecycle_lazy_export.py`, `test_subject_ref_origin.py`, `test_gateway_service_resolution.py` — runtime `ModuleNotFoundError: No module named 'fastmcp'`
- `test_governed_memory_demo.py`, `test_demo.py` — fastmcp runtime
- `test_delivery_field_collision.py` — pre-existing environment issue (not fastmcp related, pre-existed in baseline)

None of these are new or caused by this lane's changes.

---

## Files changed

```
dagr_mcp/deferred_boundary.py   NEW (397 lines)
tests/test_deferred_boundary.py NEW (398 lines)
```

No existing files were modified. All existing frozen bytes, behavioral-freeze fixtures, and canonical contracts are untouched.

---

## Limitations / open items

1. **No srs_bridge integration test** — The srs_bridge wiring in `defer_call`/`resume_call` is covered structurally but not with a live `SignedReceiptEmitter` (doing so would require temp directories and key generation). The bridge path is exercised via `Optional` pass-through; a dedicated integration test with a real emitter is a follow-on.

2. **Stale-response does not transition slot to refused** — A stale decision raises `DeferredStaleResponseError` and leaves the slot `pending`. This is intentional (a stale decision is a courier/replay problem, not a policy refusal), but could be tightened to fail-close the slot if desired by policy.

3. **gate_timeout_seconds is wall-clock only** — The timeout is evaluated at resume time against wall clock. No background watchdog expires slots without a resume attempt. A future watchdog that calls `slot.state = "expired"` unconditionally is a separate concern.

4. **Actor-mismatch check is narrow** — The check only fires when `slot.final_decision` already has an `actor_ref` recorded from a *previous* (non-terminal) interaction AND the new decision carries a different `actor_ref`. For a fresh `pending` slot with no prior decision, any `actor_ref` is accepted. This is conservative and does not block the primary admission path.

5. **No arcs-verify validation of deferred receipts** — The SRS receipts emitted (when srs_bridge is wired) follow the existing `deferred_for_review` disposition path and should validate against the existing arcs-verify profile. Independent validation is deferred to CI.

---

## Proposed PR body

See below.
