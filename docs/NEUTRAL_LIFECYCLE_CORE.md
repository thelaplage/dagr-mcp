# DAGR MCP Neutral Lifecycle Core — Sprint A3 (v0.1)

This document describes the **binding-neutral, executable lifecycle core**
extracted in Sprint A3. The core is a set of pure, deterministic planning
functions that represent the semantic decisions **frozen in A1**
([`BEHAVIORAL_FREEZE.md`](BEHAVIORAL_FREEZE.md)) and **named in A2**
([`NEUTRAL_LIFECYCLE_CONTRACT.md`](NEUTRAL_LIFECYCLE_CONTRACT.md),
`dagr_mcp_lifecycle.contract`, `dagr_mcp_lifecycle.binding_mask`).

**The FastMCP binding remains the behavioral oracle.** This sprint *extracts* the
core; it does **not** replace or rewire the production FastMCP binding. Rebinding
the live path onto the core is Sprint A4. Every A1 golden byte, every public API
snapshot, and the live execution path are unchanged.

## Authority and anchoring

| Role | Value |
|------|-------|
| Required base | `ce718b8787c4c0eabae82882a39b809e6169c682` (A2 contract + mask, #8) |
| Behavioral authority | [`docs/BEHAVIORAL_FREEZE.md`](BEHAVIORAL_FREEZE.md) |
| Neutral vocabulary | `dagr_mcp_lifecycle.contract` v0.1 |
| FastMCP mask | `dagr_mcp_lifecycle.binding_mask` v0.1 |
| ARCS authority (co-installed, unmodified) | `da89ebe36f1e4d9921aeeb7ff12f377d6804e8f7` |

## Modules

| Module | Role |
|--------|------|
| `dagr_mcp_lifecycle/models.py` | Explicit typed inputs and outputs (frozen dataclasses + `Literal` tokens). Imports only the neutral `contract`. |
| `dagr_mcp_lifecycle/core.py` | Pure deterministic transition/planning functions. Imports only `contract` and `models`. |
| `tests/test_neutral_lifecycle_core.py` | Isolation, determinism, mask agreement, the A1-fixture shadow adapter, token totality, and no-repair / no-minting proofs. |

The core is a **separate, additive layer** in the existing `dagr_mcp_lifecycle`
package. It is not exported from the package root (the root surface stays
`["contract", "binding_mask"]`, submodules-only), and it does not live inside the
binding it represents. `core.py` and `models.py` are added to the neutral
package's own public-surface snapshot
(`tests/golden/neutral_lifecycle/public_api_surface.json`), which remains
disjoint from the A1 `dagr_mcp` snapshot.

## What the core owns, and what it does not

The core owns **semantic facts only**. It is a *planner*: given a resolved
admission decision and an already-classified execution observation, it returns a
`LifecyclePlan` describing which governance records exist, what neutral facts each
carries, and which responsibilities belong to the adapter.

The core **never**:

- imports FastMCP, the MCP SDK, any transport, or any binding-specific
  request/result type;
- depends on any ARCS package;
- performs a side effect — no network, filesystem, environment, clock, UUID,
  hashing, or signing (proved by fresh-subprocess import probes and an AST source
  scan);
- mints a receipt id, timestamp, signature, digest **value**, protocol version,
  or binding identifier.

Everything a concrete binding must do to turn a plan into a signed, transported,
custody-stored record is enumerated as an `AdapterResponsibility` and attached to
each planned record, so the boundary is explicit and testable:

```
mint_receipt_id · mint_issued_at · compute_argument_digest · compute_result_digest
mint_review_object_ref · canonicalize_record · sign_record · stamp_protocol_binding
stamp_binding_version · store_custody_projection · transport_record
```

A record intent carries `carries_argument_digest = True` (a *duty*), not a digest;
it declares `stamp_protocol_binding` / `stamp_binding_version` responsibilities,
never the values `"mcp"` or `"fastmcp.middleware.v0.1"`. Custody storage,
canonicalization, signing, and transport are all adapter concerns, distinguished
from the core's semantic facts.

## What the core represents

| Frozen fact (A1/A2) | Core representation |
|---------------------|---------------------|
| Admission request and decision | `AdmissionRequest` → `plan_admission` → `AdmissionPlan` |
| Admitted / refused / deferred dispositions | `AdmissionRecordIntent.disposition`; refusal grounds in `reason_code` |
| Execution start / proceed | `AdmissionPlan.execution_proceeds` / `admission_recorded` |
| Result, error, exception, task-submitted, indeterminate outcomes | `OutcomeRecordIntent.outcome` (`cancellation` → indeterminate via the mask) |
| Cancellation governance facts | `OutcomeRecordIntent.governance_facts` = the three Booleans, all `True`, indeterminate-only |
| **Timeout as exception with `TimeoutError`** | `plan_outcome(timeout)` → exception record, `subsumed_from="timeout"`, `exception_class="TimeoutError"`, no result digest (§14) |
| **Unsupported `input_required`** | `plan_outcome` returns `UnsupportedLifecycleResult` (never an outcome); `plan_outcome_strict` raises `UnsupportedLifecycleEvent` |
| Receipt cardinality and admission/outcome linkage | `LifecyclePlan.record_count` (2 / 1 / 1); `OutcomeRecordIntent.references_admission` |
| Custody observations and attestation limits | `attestation_limit_families` (resolved to strings by the mask); custody storage is an adapter responsibility |
| Argument / result digest responsibilities | `carries_argument_digest` / `carries_result_digest` + `compute_*_digest` responsibilities |
| Protocol and binding stamps | declared as `stamp_protocol_binding` / `stamp_binding_version` adapter responsibilities |

### No silent repair

- A refusal on `required_sink_unavailable` stays refused on that exact ground —
  the core never repairs it (§17 residual preserved).
- A deferral whose review object **failed to create** resolves to a refusal on
  `review_object_creation_failed`, **never** onto `required_sink_unavailable`
  (the two grounds are distinct and never swapped). A genuine deferral (review
  object created) never becomes a refusal.

### Unsupported events are never normalized

`input_required` in either mode returns an explicit `UnsupportedLifecycleResult`
(`supported = False`) or, via the strict planners, raises
`UnsupportedLifecycleEvent`. It is never coerced into `result_returned` /
`error_returned` or any other supported outcome.

## The A3 shadow adapter

`tests/test_neutral_lifecycle_core.py` runs **every A1 characterization** — the
three admission goldens (`admitted` / `refused` / `deferred_for_review`) and the
five outcome goldens (`result_returned` / `error_returned` / `exception` /
`task_submitted` / `indeterminate`) — through a neutral **shadow adapter**. The
adapter projects a core plan onto the binding via the A2 mask and asserts the
neutral facts equal the committed fixture bytes: disposition, reason code,
retry contract, review-object reference, outcome token, result-digest presence,
admission linkage, cancellation Booleans, the subsumed `TimeoutError`, and the
attestation-limit strings. No receipt is emitted and the live path is untouched.

The core plan is additionally compared **directly against the A2 mask**:
`core.core_outcome_status(token)` equals `binding_mask.project_outcome(token).status`
for every neutral outcome, and every neutral disposition/outcome projects onto a
live binding token. Every neutral contract token is proved to be either
implemented by the core (`direct` / `subsumed`) or explicitly unsupported.

## Verification

Run 2026-07-13 against base `ce718b8`. Environment: **Python 3.14.5, FastMCP
3.4.4, cryptography 46.0.7, rfc8785 0.1.4**; co-installed lane adds **arcs-verify
0.1.1 @ `da89ebe`, arcs-amnesiac 0.2.0, garp-sdk 0.1.0**.

| Lane | Command | Result |
|------|---------|--------|
| Standalone DAGR | `python -m pytest -q` | `370 passed, 18 skipped` |
| Co-installed DAGR | `python -m pytest -q` | `410 passed` |
| A3 core suite | `python -m pytest -q tests/test_neutral_lifecycle_core.py` | `97 passed` |
| A1 freeze checks | `python -m pytest -q tests/test_behavioral_freeze.py tests/test_frozen_contract.py tests/test_fastmcp_projection_golden.py tests/test_fastmcp_fixture_generator.py` | `48 passed` (co-installed) |
| A2 contract / mask | `python -m pytest -q tests/test_neutral_lifecycle_contract.py tests/test_lifecycle_contract_hardening.py tests/test_lifecycle_lazy_export.py` | `43 passed` |
| Canonical ARCS (unmodified `da89ebe`) | `(cd ../arcs-verify && python -m pytest -q)` | `108 passed` |
| Fixture / freeze check | `python tools/generate_fastmcp_fixtures.py --check` | committed fixtures match a fresh 3.4.4 generation |
| Public-release scan | `python tools/check_public_release.py .` | `PASS: 0 finding(s)` |
| Package build | `python -m build` + `twine check dist/*` | built (wheel ships `dagr_mcp_lifecycle.core` + `.models`) + `PASSED` |
| Clean-wheel import smoke | install wheel in a fresh venv, import outside the repo | `dagr_mcp_lifecycle.core` plans a full lifecycle with no binding present |

The A3 diff adds `dagr_mcp_lifecycle/core.py`, `dagr_mcp_lifecycle/models.py`,
`tests/test_neutral_lifecycle_core.py`, this document, and the two new module
entries in the neutral public-surface snapshot. No pre-existing source or test
was modified; the A1 `dagr_mcp` public-API snapshot, golden digests, signing
bytes, and the live FastMCP execution path are all unchanged.
