# FastMCP Core Rebinding — Sprint A4

This document records how the **live FastMCP production adapter**
(`dagr_mcp.fastmcp_binding.DAGRMiddleware`) was rebound onto the binding-neutral
lifecycle **core** extracted in Sprint A3 (`dagr_mcp_lifecycle.core` /
`dagr_mcp_lifecycle.models`).

This was a **rebinding**, not a semantic revision. Every A1 observable — receipt
envelopes, signing bytes, custody projections, errors, reason codes, cardinality,
and the public surface — is preserved exactly. The A1 behavioral freeze
(`docs/BEHAVIORAL_FREEZE.md`) remains the observable oracle; the committed A1
goldens were **not** regenerated, and no receipt schema, profile, package
version, signing key, or digest changed.

## Anchoring

| Role | Value |
|------|-------|
| Required base | `64f392247788bc9c21a7c07870c72ccad4f163b7` (feat: extract binding-neutral MCP lifecycle core, #9) |
| Neutral core | `dagr_mcp_lifecycle.core` / `dagr_mcp_lifecycle.models` (A3) |
| Neutral contract | `dagr_mcp_lifecycle.contract` v0.1 (A2) |
| Binding mask | `dagr_mcp_lifecycle.binding_mask` v0.1 (A2) — the neutral→binding projection authority |
| Observable oracle | A1 behavioral freeze (`d4f81a2`), committed goldens under `tests/golden/behavioral_freeze/` |
| ARCS authority | `arcs-verify` `da89ebe`, co-installed, unmodified |

## What changed

The rebinding is confined to `dagr_mcp/fastmcp_binding.py` (adapter) plus a new
test file `tests/test_fastmcp_core_rebinding.py` (proof). No new module was added
to the `dagr_mcp` package (the A1 public-API snapshot enumerates the package with
`pkgutil.walk_packages`, so a new submodule would break the frozen surface); the
adapter helpers are private functions/methods inside the existing binding module,
and `fastmcp_binding.__all__` is unchanged.

Before A4, `DAGRMiddleware.on_call_tool` carried its **own** copy of the lifecycle
decision tree — the disposition branches, the review-object-failure resolution,
the "record admission before execution" predicate, and the outcome-family
classification. After A4 those decisions are made by the neutral core, and the
adapter only converts inputs into neutral models and projects the returned plan
back into the existing emitter calls.

## Core-owned decisions

The core (`plan_admission`, `plan_outcome_strict`) is now the single authority for
every lifecycle decision it implements:

| Decision | Core surface |
|----------|--------------|
| Admission disposition resolution (admitted / refused / deferred) | `plan_admission → AdmissionPlan.resolved_disposition` |
| Whether execution proceeds | `AdmissionPlan.execution_proceeds` |
| Whether an admission record is durably observed before execution | `AdmissionPlan.admission_recorded` (write/destructive always; read per `emit_read_admission_before_execution`) |
| Deferral whose review object failed → refusal on `review_object_creation_failed` | `plan_admission` with `review_object_created=False` (never `required_sink_unavailable`; §17 residual preserved) |
| Refusal ground carried verbatim (incl. `required_sink_unavailable`) | `AdmissionRecordIntent.reason_code` |
| Deferral continuation contract (`retry_after_approval`) | `AdmissionRecordIntent.retry_contract` |
| Outcome record family (result / error / exception / task_submitted / cancellation) | `plan_outcome_strict → OutcomeRecordIntent.outcome` |
| Result-digest presence per outcome | `OutcomeRecordIntent.carries_result_digest` |
| Cancellation governance-fact posture (all three, `True`, indeterminate-only) | `OutcomeRecordIntent.governance_facts` |
| Timeout → exception subsumption (`exception_class="TimeoutError"`) | `SUBSUMED_OUTCOMES`, exercised by the differential harness (see below) |
| Receipt cardinality (admitted → 2, refused/deferred → 1) | `plan_admission` + `plan_outcome_strict` record existence |
| `input_required` is unsupported, never coerced | `plan_outcome_strict` raises `UnsupportedLifecycleEvent` |

The neutral→binding token projection is owned by the A2 **mask**
(`project_disposition`, `project_outcome`, `project_cancellation_fact`), which is
verified against the live binding by `verify_mask_matches_binding`. The adapter
imports the mask lazily inside its projection helpers to avoid the
mask↔binding import cycle.

## Adapter-owned responsibilities

Everything the neutral core deliberately does **not** do stays in the adapter:

- timestamps (`issued_at`) and identifiers (`receipt_id`, review-object ref);
- RFC 8785 canonicalization, digests (`sha256_digest`,
  `fastmcp_tool_result_digest`), and Ed25519 signing;
- protocol / binding stamps (`protocol_binding="mcp"`,
  `binding_version="fastmcp.middleware.v0.1"`) and custody storage;
- FastMCP request/result extraction (`project_fastmcp_tool_result`,
  `_snapshot_request`) and exception-object inspection
  (`asyncio.CancelledError` vs a generic exception; `type(exc).__name__`);
- transport behavior, the review-object side effect, actor resolution, and the
  receipt-failure policy (fail-open / fail-closed, emergency spool, receipt-gap
  telemetry).

Classifying a raw FastMCP result or exception into a neutral
`ExecutionObservation`, and projecting a neutral record family back onto the
binding token, are adapter responsibilities — the *decision* of what record the
observation produces is the core's.

## Exact production call path (after rebinding)

`DAGRMiddleware.on_call_tool(context, call_next)`:

1. `_snapshot_request` → `_resolve_actor` → `_resolve_policy` → `_receipt_context`
   (all adapter-owned; unchanged).
2. `neutral_disposition = _to_neutral_disposition(policy.disposition)`.
3. If deferred: `_create_review_object(...)` (adapter side effect) sets
   `review_object_created` (`True`, or `False` on failure with
   `_record_review_failure`).
4. `admission_plan = plan_admission(self._neutral_admission_request(...))` — **core
   decides** disposition, execution-proceeds, and admission-recorded.
5. If `not admission_plan.execution_proceeds`:
   `_project_terminal_admission(...)` emits the single terminal admission record
   the plan describes (`project_disposition` → binding token; `record.reason_code`
   / `record.retry_contract`) and raises the frozen `ToolError`
   (`"Call refused by admission policy"` /
   `"Review admission receipt could not be durably accepted"` /
   `"Call deferred for review: …"`).
6. If `admission_plan.admission_recorded`: `_emit_admission(disposition="admitted")`
   captures `admission_receipt_ref`; on emit failure the adapter's fail-open /
   fail-closed policy applies (unchanged).
7. `result = await call_next(context)`.
   - `asyncio.CancelledError` → inline **A1-frozen** emit
     `outcome="indeterminate"` with the three `True` governance Booleans; re-raise.
   - other `Exception` → inline **A1-frozen** emit `outcome="exception"`,
     `exception_class=type(exc).__name__`; re-raise. (A raised `TimeoutError` is an
     ordinary inner exception here — see below.)
8. `result` branch: `CreateTaskResult` → `_emit_planned_outcome(...,
   ExecutionObservation("task_submitted"))`; otherwise project the FastMCP result,
   compute the digest, classify `ExecutionObservation("error" | "result")`, and
   `_emit_planned_outcome(...)`. `_emit_planned_outcome` calls
   `plan_outcome_strict` and projects `record.outcome` → binding token via the
   mask, supplying the digest only when `record.carries_result_digest`.

### Why the cancellation/exception emits remain inline

A1 freezes the cancellation/exception mapping by **source inspection**
(`test_freeze_binding_maps_cancellation_to_indeterminate_with_governance_fields`
asserts `outcome="indeterminate"`, the three governance Booleans,
`outcome="exception"`, and `exception_class=type(exc).__name__` appear literally
in `on_call_tool`). Those two emits therefore keep their frozen inline
binding-projection literals. They are proved byte-equal to what the core plans and
the mask projects by `test_frozen_cancellation_literals_equal_the_core_projection`
and `test_frozen_exception_literal_equals_the_core_projection`, so the two
spellings of the same fact cannot drift apart. This is a frozen A1 residual and is
**not** repaired, renamed, or reinterpreted in this sprint.

## Explicitly unsupported lifecycle state

`input_required` (in both `continuable` and `interrupted` modes) remains
explicitly unsupported. The binding has no elicitation / continuation branch, the
mask classifies it `unsupported`, and `plan_outcome_strict` raises
`UnsupportedLifecycleEvent` rather than coercing it into a supported outcome. The
production adapter never mints an `input_required` observation.

## Timeout posture (unchanged)

The production adapter does **not** distinctly observe a timeout: a raised
`TimeoutError` flows through the generic `except Exception` branch and is recorded
as `outcome="exception"` with `exception_class="TimeoutError"` and no
`result_digest` — exactly as A1 §14 freezes it, and exactly as the mask marks
`timeout` *subsumed*. The core's `timeout → exception` subsumption is the neutral
statement of the same fact; it is exercised by
`test_core_timeout_subsumption_projects_to_the_same_exception_token`, which proves
the subsumed family projects to the same binding token (`exception`) and exception
class. No production path mints a neutral `timeout` token.

## Differential harness (test-only)

`tests/test_fastmcp_core_rebinding.py::_former_admission_decision` reproduces the
**pre-A4** production admission decision tree and asserts, across the
disposition × tool-class × review × read-admission matrix, that the core plan
reproduces it exactly (`test_former_admission_decision_agrees_with_core_plan`).
This oracle exists only to demonstrate parity; it is not wired into any production
path, so no second production authority is retained.

Additional proofs in the same file:

- `test_live_fastmcp_path_imports_the_core_planners` /
  `test_on_call_tool_invokes_the_core_for_admission_and_outcome` — the live path
  imports and invokes the core.
- `test_core_plan_is_authoritative_for_execution_proceeds` /
  `…_for_admission_recorded` — forcing the core plan changes the adapter's
  behavior, proving the core (not a shadow branch) drives control flow.
- `test_admission_decision_literals_no_longer_encoded_in_adapter` /
  `test_result_error_task_tokens_come_from_the_mask_not_inline_literals` — the
  admission decision literals and the outcome-classification ternary are gone from
  the adapter; only frozen binding-projection literals remain.
- `test_core_still_imports_no_fastmcp_or_binding_package` — importing the core in a
  clean process pulls in no `dagr_mcp` / `fastmcp` / `mcp` root.

## Parity verification results

Run 2026-07-13 against branch `feat/fastmcp-core-rebinding-v0-1` (base `64f3922`).
Environment: Python 3.13, FastMCP 3.4.4, rfc8785 0.1.4; co-installed lane adds
`arcs-verify @ da89ebe`, `arcs-amnesiac`, `garp-sdk`.

| Check | Result |
|-------|--------|
| Standalone DAGR full suite | **394 passed, 18 skipped** |
| Co-installed DAGR full suite | **434 passed** |
| A1 behavioral-freeze suite | **40 passed** (co-installed); **37 passed, 3 skipped** (standalone) |
| A2 contract / mask / hardening / lazy-export suites | **43 passed** |
| A3 neutral-core suite | **97 passed** (both lanes) |
| A4 rebinding suite (`test_fastmcp_core_rebinding.py`) | **24 passed** |
| Canonical ARCS suite (`arcs-verify @ da89ebe`, unmodified) | **108 passed** |
| Fixture regeneration check (`tools/generate_fastmcp_fixtures.py --check`) | **PASS — committed FastMCP fixtures match fresh 3.4.4 generation** (fixtures unmodified) |
| Public-release scan (`tools/check_public_release.py .`) | **PASS: 0 finding(s)** |
| Package build (`python -m build --sdist --wheel`) | **Successfully built `dagr_mcp-0.1.0.tar.gz` and `dagr_mcp-0.1.0-py3-none-any.whl`** |
| `twine check` | **PASSED** (wheel + sdist) |
| Clean-wheel FastMCP execution smoke | **OK** — end-to-end `tools/call` through the installed wheel emits the `admitted` + `result_returned` signed pair, outcome references admission, `binding_version="fastmcp.middleware.v0.1"`; `fastmcp_binding.plan_admission is dagr_mcp_lifecycle.core.plan_admission` |

The A1 goldens (signed receipts, custody projections, public-API snapshot) are
byte-identical: the freeze suite regenerates and compares them and passes in both
lanes, and the fixture check confirms no fixture drift.

## Constraints honored

No receipt schema or profile bump; no package-version bump; no public API
replacement; no new binding; no MCP SDK binding; no ARCS changes; no transport or
deployment work; no golden regeneration to accept drift; no signing-key or digest
changes. `enforcement_harness` (the separate `direct-harness.v0.1` binding) is out
of scope for this FastMCP-only rebinding and is unchanged.
