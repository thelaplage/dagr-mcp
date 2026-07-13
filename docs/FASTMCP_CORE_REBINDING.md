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

The rebinding covers **every** live outcome family. Admission and the
result / error / task-submitted outcomes route through the core; the cancellation
and raised-exception outcomes — which an earlier A4 revision still emitted from
independent inline decisions — now also invoke `plan_outcome_strict`, so the core
is the sole runtime authority for the neutral outcome family, whether a result
digest is carried, the cancellation governance facts, and the timeout→exception
subsumption. The A1-frozen inline literals survive only as **checked projection
invariants** that fail closed against the core plan (see below). Two further
correctness points are addressed: the adapter routes a raised `TimeoutError`
through the core's timeout path rather than describing the subsumption only in a
test, and an opaque `BindingPolicy.reason_code` outside the core's closed
vocabulary is preserved verbatim instead of crashing the closed core (§7).

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
| Outcome record family for **every** live outcome — result / error / task_submitted **and** exception / cancellation | `plan_outcome_strict → OutcomeRecordIntent.outcome` |
| Result-digest presence per outcome | `OutcomeRecordIntent.carries_result_digest` |
| Cancellation governance-fact posture (all three, `True`, indeterminate-only) | `OutcomeRecordIntent.governance_facts` |
| Timeout → exception subsumption (`exception_class="TimeoutError"`) on the **live** path | adapter identifies the raised `TimeoutError` and hands the core `ExecutionObservation("timeout")`; `SUBSUMED_OUTCOMES` records it onto the exception family |
| Receipt cardinality (admitted → 2, refused/deferred → 1) | `plan_admission` + `plan_outcome_strict` record existence |
| The refusal **decision** for every disposition (opaque reason codes stay adapter-owned, §7 below) | `plan_admission → AdmissionPlan.resolved_disposition` / `execution_proceeds` |
| `input_required` is unsupported, never coerced — including via the exception/cancellation fallback | `plan_outcome_strict` raises `UnsupportedLifecycleEvent` |

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
7. `result = await call_next(context)`. Both interruption branches now route
   through the core via `_project_core_outcome`, which invokes
   `plan_outcome_strict(admission_plan, observation)` and makes the returned record
   the runtime authority (outcome family, digest presence, governance facts):
   - `asyncio.CancelledError` → `_project_core_outcome(...,
     ExecutionObservation("cancellation"), frozen_outcome="indeterminate",
     frozen_binding_owned_fields={the three `True` Booleans})`; re-raise.
   - other `Exception` → the adapter inspects the raised object, derives
     `exception_class=type(exc).__name__`, and identifies a `TimeoutError`
     (`isinstance(exc, TimeoutError)`), building `ExecutionObservation("timeout")`
     for a timeout — routing it through the core's timeout→exception subsumption —
     or `ExecutionObservation("exception", exception_class=…)` otherwise, then
     `_project_core_outcome(..., frozen_outcome="exception",
     exception_class=type(exc).__name__)`; re-raise.
8. `result` branch: `CreateTaskResult` → `_emit_planned_outcome(...,
   ExecutionObservation("task_submitted"))`; otherwise project the FastMCP result,
   compute the digest, classify `ExecutionObservation("error" | "result")`, and
   `_emit_planned_outcome(...)`. `_emit_planned_outcome` calls
   `plan_outcome_strict` and projects `record.outcome` → binding token via the
   mask, supplying the digest only when `record.carries_result_digest`.

### The cancellation/exception literals are checked projection invariants

A1 freezes the cancellation/exception mapping by **source inspection**
(`test_freeze_binding_maps_cancellation_to_indeterminate_with_governance_fields`
asserts `outcome="indeterminate"`, the three governance Booleans,
`outcome="exception"`, and `exception_class=type(exc).__name__` appear literally
in `on_call_tool`). Those literals therefore remain spelled inline — but they are
no longer a **second decision authority**. They are passed into
`_project_core_outcome` as the `frozen_outcome` / `frozen_binding_owned_fields`
the emit is *expected* to produce, and the helper:

1. invokes `plan_outcome_strict` so the **core** decides the neutral outcome
   family, whether a result digest is carried, and the cancellation governance
   facts (and subsumes a `timeout` observation onto the exception family);
2. projects the core record through the A2 mask (`project_outcome`,
   `project_cancellation_fact`);
3. verifies the projection equals the frozen inline literal — outcome token, the
   `carries_result_digest is False` invariant, and the governance-fact dict — and
   **fails closed** (raises a deterministic `ToolError`, *before* any emit) on any
   mismatch;
4. emits the core-derived projection, not the literal.

So the frozen literal survives A1 source inspection as a *checked invariant*, the
core is the runtime authority, and the two spellings of the same fact can never
diverge without a fail-closed error. This is proved by
`test_frozen_cancellation_literals_equal_the_core_projection`,
`test_frozen_exception_literal_equals_the_core_projection`, the production-path
invocation tests (`test_cancellation_actually_invokes_plan_outcome_strict`,
`test_ordinary_exception_actually_invokes_plan_outcome_strict`,
`test_raised_timeout_actually_invokes_the_core_timeout_exception_path`,
`test_cancellation_governance_facts_are_obtained_from_the_core_record`), and the
fail-closed tests
(`test_divergent_core_outcome_family_fails_closed_before_any_receipt`,
`test_divergent_core_governance_facts_fail_closed_before_any_receipt`).

## Explicitly unsupported lifecycle state

`input_required` (in both `continuable` and `interrupted` modes) remains
explicitly unsupported. The binding has no elicitation / continuation branch, the
mask classifies it `unsupported`, and `plan_outcome_strict` raises
`UnsupportedLifecycleEvent` rather than coercing it into a supported outcome. The
production cancellation/exception branches only ever construct `cancellation`,
`timeout`, or `exception` observations, so an `input_required` can never arise
there; `test_input_required_cannot_enter_the_outcome_fallback` proves the property
from the other side — handed an `input_required` observation, `_project_core_outcome`
fails closed via `plan_outcome_strict` before any emit, so it cannot be coerced
into a supported cancellation/exception outcome.

## Timeout posture (observable unchanged; now core-authoritative on the live path)

The observable is exactly what A1 §14 freezes: a raised `TimeoutError` is recorded
as `outcome="exception"` with `exception_class="TimeoutError"` and no
`result_digest`. What changed in this hardening is *who decides it on the live
path*. The adapter now **identifies** the `TimeoutError` (adapter responsibility,
§4) and hands the core `ExecutionObservation("timeout")`; the core subsumes it onto
the exception family (`SUBSUMED_OUTCOMES`), which the mask projects to the binding
token `exception`. The adapter-owned `exception_class` (`type(exc).__name__`) is
`TimeoutError` for a genuine `TimeoutError`, so the emitted receipt is byte-for-byte
what the frozen generic-exception path produced — and because both the
timeout-subsumed and the direct-exception observations land on the same
`exception` family with no digest, an ordinary (non-timeout) exception is
observably identical either way. `test_raised_timeout_actually_invokes_the_core_timeout_exception_path`
proves the live path passes the `timeout` observation to the core and still emits
the frozen shape; `test_core_timeout_subsumption_projects_to_the_same_exception_token`
proves the neutral subsumption lands on the same binding token and class.

## Refusal decision vs. reason code (§7)

`BindingPolicy.reason_code` is an arbitrary `str | None`, and a policy provider
may return an **opaque** code outside the core's closed neutral
`NEUTRAL_REFUSAL_GROUNDS` vocabulary (`policy_refused`,
`unknown_tool_fail_closed`, `required_sink_unavailable`,
`review_object_creation_failed`). The core is authoritative only for the refusal
**decision** — that the call is refused, produces a single terminal admission
record, and does not proceed — not for the opaque reason string. The adapter
therefore:

- maps the binding reason code onto a **closed** neutral ground for the core
  (`_neutral_refusal_ground`: a known ground passes through verbatim; an opaque
  code or `None` resolves to `policy_refused`), so the core never sees a token
  outside its vocabulary and never raises on production input; and
- stamps the **verbatim** binding reason code on the emitted receipt
  (`_binding_refusal_reason_code`, defaulting to `policy_refused`), preserving the
  pre-core behavior exactly rather than silently narrowing an opaque code to the
  neutral ground.

A deferral that the core resolves to a refusal (its review object failed to
create) still emits the core's governance ground `review_object_creation_failed`
unchanged — never `required_sink_unavailable` (§17). This is proved by
`test_opaque_reason_code_maps_to_a_closed_ground_but_emits_verbatim` and
`test_opaque_binding_reason_code_survives_to_the_receipt`, and the in-vocabulary
goldens are unaffected (for a known code the two projections coincide).

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

The differential oracle proves *equivalence*; it is not, on its own, proof that the
live cancellation/exception path *invokes* the core. The production-path tests
supply that proof directly by spying on the live `plan_outcome_strict`, forcing a
divergent core plan, and exercising the reason-code projection:

- `test_cancellation_actually_invokes_plan_outcome_strict` /
  `test_ordinary_exception_actually_invokes_plan_outcome_strict` /
  `test_raised_timeout_actually_invokes_the_core_timeout_exception_path` — the live
  cancellation, exception, and timeout paths each call `plan_outcome_strict` with
  the expected neutral observation (`cancellation` / `exception` / `timeout`).
- `test_cancellation_governance_facts_are_obtained_from_the_core_record` — the
  emitted cancellation Booleans equal the core record projected through the mask.
- `test_divergent_core_outcome_family_fails_closed_before_any_receipt` /
  `test_divergent_core_governance_facts_fail_closed_before_any_receipt` — a
  monkeypatched divergent core plan raises a deterministic projection error and no
  contradictory outcome receipt is written (only the admission record exists).
- `test_input_required_cannot_enter_the_outcome_fallback` — the fallback helper
  fails closed on an `input_required` observation instead of coercing it.
- `test_opaque_reason_code_maps_to_a_closed_ground_but_emits_verbatim` /
  `test_opaque_binding_reason_code_survives_to_the_receipt` — an opaque
  out-of-vocabulary reason code is emitted verbatim while the core still decides
  the refusal (§7).

## Parity verification results

Run 2026-07-13 against branch `feat/fastmcp-core-rebinding-v0-1` (base `64f3922`).
Environment: Python 3.13, FastMCP 3.4.4, rfc8785 0.1.4; co-installed lane adds
`arcs-verify @ da89ebe`, `arcs-amnesiac`, `garp-sdk`.

| Check | Result |
|-------|--------|
| Standalone DAGR full suite | **403 passed, 18 skipped** |
| Co-installed DAGR full suite | **443 passed** |
| A1 behavioral-freeze suite | **40 passed** (co-installed); **37 passed, 3 skipped** (standalone) |
| A2 contract / mask / hardening / lazy-export suites | **43 passed** (both lanes) |
| A3 neutral-core suite | **97 passed** (both lanes) |
| A4 rebinding suite (`test_fastmcp_core_rebinding.py`) | **33 passed** (both lanes) — 24 prior + 9 new production-path / fail-closed / §7 tests |
| Canonical ARCS suite (`arcs-verify @ da89ebe`, unmodified) | **108 passed** |
| Fixture regeneration check (`tools/generate_fastmcp_fixtures.py --check`) | **PASS — committed FastMCP fixtures match fresh 3.4.4 generation** (fixtures unmodified) |
| Public-release scan (`tools/check_public_release.py .`) | **PASS: 0 finding(s)** |
| Package build (`python -m build --sdist --wheel`) | **Successfully built `dagr_mcp-0.1.0.tar.gz` and `dagr_mcp-0.1.0-py3-none-any.whl`** |
| `twine check` | **PASSED** (wheel + sdist) |
| Clean-wheel FastMCP execution smoke | **OK** — end-to-end `tools/call` through the installed wheel (run outside the source tree) emits both the `admitted` + `result_returned` pair (result-digest present) **and** the rebound exception outcome for a raised `TimeoutError` (`admitted` + `exception`, `exception_class="TimeoutError"`, no `result_digest`); each outcome references its admission, `binding_version="fastmcp.middleware.v0.1"`; `fastmcp_binding.plan_admission is dagr_mcp_lifecycle.core.plan_admission` and likewise for `plan_outcome_strict` |

The A1 goldens (signed receipts, custody projections, public-API snapshot) are
byte-identical: the freeze suite regenerates and compares them and passes in both
lanes, and the fixture check confirms no fixture drift.

## Constraints honored

No receipt schema or profile bump; no package-version bump; no public API
replacement; no new binding; no MCP SDK binding; no ARCS changes; no transport or
deployment work; no golden regeneration to accept drift; no signing-key or digest
changes. `enforcement_harness` (the separate `direct-harness.v0.1` binding) is out
of scope for this FastMCP-only rebinding and is unchanged.
