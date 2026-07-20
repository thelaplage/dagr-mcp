---
id: CLOSE_MEMO_gateway_a8_in_process_adapter_JUL19
title: Gateway lane close memo -- A8 in-process adapter and memory connector
date: 2026-07-19
classification: Internal / Feature / Lane Close
status: Draft
---

## Scope

This lane implements work package A8 of the DAGR Gateway Service Adapter,
as scoped in `docs/GATEWAY_SERVICE_ADAPTER_SCOPE.md` (§15) and gated on A7
(PR #15, `dagr_mcp_service.contract` / `dagr_mcp_service.resolution`, base
`b71e1f845ed14ad7ee4315a6132c517324c3bdb2`). It adds the first executable,
in-process Gateway composition seam: `dagr_mcp_service.adapter.
execute_governed_call`, driving both existing lifecycle bindings
(`fastmcp.middleware.v0.1`, `official-mcp-sdk.python.v0.1`) unchanged, plus
`dagr_mcp_service.connectors.memory`, an in-process, allowlisted local-target
connector. It does not add A9 (a remote transport connector) or A10 (the
receipt-handle access/composition seam).

- **Base SHA:** `b71e1f845ed14ad7ee4315a6132c517324c3bdb2`
- **Branch:** `feat/gateway-in-process-adapter-v0-1`
- **Final head SHA:** recorded at commit time below (see `git log -1`).

## Files changed

New:

- `dagr_mcp_service/adapter.py` -- `GatewayAdapterConfig`,
  `execute_governed_call(request, *, arguments, config)`.
- `dagr_mcp_service/connectors/__init__.py` -- lazy PEP 562 package root for
  the connector package (matches the sibling-package convention).
- `dagr_mcp_service/connectors/memory.py` -- `InMemoryToolConnector`,
  `MemoryTargetResolutionRefused`, `LocalToolHandler`.
- `tests/test_gateway_service_adapter.py` -- 49 tests (41 unparametrized +
  parametrized pairs across both bindings).
- `tests/test_gateway_service_memory_connector.py` -- 8 tests.

Modified:

- `dagr_mcp_service/__init__.py` -- added `adapter` and `connectors` to the
  package's lazy-submodule set (`_LAZY_SUBMODULES`), updated `__all__` and
  the module docstring's "what this sprint adds" description. No behavior
  change to the existing `contract`/`resolution` lazy binding.
- `tests/test_gateway_service_contract.py` -- **one deviation from the
  originally scoped allowed-diff list**, recorded here per the review-stop
  rule rather than silently widened. The A7-era test
  `test_no_adapter_execution_or_access_module_exists_yet` asserted that
  `dagr_mcp_service.adapter`, `dagr_mcp_service.connectors`, and
  `execute_governed_call` did not exist -- an assertion A8's own authorized
  scope directly contradicts. There is no way to satisfy "full stable
  pytest suite passes" (an explicit A8 validation requirement) without
  updating this one now-stale assertion. The fix is narrowly mechanical: the
  test was renamed to `test_no_access_module_exists_yet` and now asserts
  only that `dagr_mcp_service.access` (A10 scope) still does not exist;
  the `adapter`/`connectors` assertions were removed rather than inverted
  into a positive claim, since positive-existence coverage for those two
  modules already lives in `tests/test_gateway_service_adapter.py` and
  `tests/test_gateway_service_memory_connector.py`. No other line in this
  file changed.

## Public A8 surface

```python
# dagr_mcp_service/adapter.py
@dataclass(frozen=True, slots=True, kw_only=True)
class GatewayAdapterConfig:
    binding_registry: Mapping[str, str]
    connector: Any
    identity: SigningIdentity
    sink: Any
    runtime_instance_id: str
    boundary_id: str
    policy_pack_id: str
    policy_pack_version: str
    tool_classes: Mapping[str, str] = ...
    policy_resolver: Any | None = None
    review_object_creator: Any | None = None
    pre_execution_receipt_failure: Mapping[str, str] = ...
    post_execution_receipt_failure: str = "alert_and_return_result"
    emit_read_admission_before_execution: bool = True
    emergency_spool_path: Path | None = None
    parent_receipt_ref: str | None = None
    additional_attestation_limits: tuple[str, ...] = ()
    is_binding_available: Callable[[str], bool] | None = None

async def execute_governed_call(
    request: GovernedCallRequest, *, arguments: Mapping[str, Any], config: GatewayAdapterConfig
) -> GovernedCallResponse: ...

# dagr_mcp_service/connectors/memory.py
class InMemoryToolConnector:
    def __init__(self, targets: Mapping[str, Mapping[str, LocalToolHandler]]) -> None: ...
    def resolve(self, target_handle: str, tool_name: str) -> LocalToolHandler | MemoryTargetResolutionRefused: ...

@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryTargetResolutionRefused:
    target_handle: str
    tool_name: str
    reason: Literal["remote_unavailable", "unknown_tool_fail_closed"]
```

There is deliberately no `actor_resolver` field on `GatewayAdapterConfig`:
the trusted actor/tenant projection is always derived internally from
`GovernedCallRequest.actor_ref`/`.tenant_ref`, never from operator config or
caller input (§8). Internal helpers (`_CapturingSink`, `_classify`,
`_execute_via_fastmcp`, `_execute_via_sdk`, `_refusal_diagnostic`,
`_receipt_handle`, `_binding_config_kwargs`, `_actor_resolution_kwargs`) are
not exported.

## Invocation composition per binding

Neither binding was modified. Each is driven through its own real,
already-existing execution seam:

- **FastMCP (`fastmcp.middleware.v0.1`).** `_execute_via_fastmcp` builds a
  `DAGRMiddleware` directly (no `FastMCP()` server / `Client` pair
  constructed) and drives it exactly the way
  `tests/test_fastmcp_binding.py`'s own `call_direct` test helper does: a
  synthetic `fastmcp.server.middleware.MiddlewareContext` wrapping an
  `mcp.types.CallToolRequestParams(name=tool_name, arguments=...)`, and a
  `call_next` callback that awaits the resolved local target directly.
  `await middleware.on_call_tool(context, call_next)` is the real,
  unmodified lifecycle path -- admission, policy, review, and outcome
  emission all run inside it exactly as they do standalone.
- **Official SDK (`official-mcp-sdk.python.v0.1`).** `_execute_via_sdk`
  constructs an `SdkLifecycleAdapter` and calls its public
  `governed_call(tool_name, arguments, delegate, request_context=None)`
  directly -- the binding's own documented "sole execution seam"
  (`dagr_mcp_sdk_binding/adapter.py`). No `mcp.server.lowlevel.Server` /
  `ClientSession` pair is constructed; `request_context=None` because A8
  supplies trust through its own `actor_resolver` closure instead (see
  below), matching how the binding's `_resolve_actor` already tolerates an
  absent `request_context`.

Both binding capability differences are preserved, not papered over: the
SDK binding's `TaskSubmissionUnsupported` (returned as
`diagnostic_code="unsupported_lifecycle_state"`, `decision.outcome=None`,
one admission receipt, no business result) is caught explicitly in
`_execute_via_sdk`, distinct from the generic exception path; the FastMCP
binding's `task_submitted` support is preserved and surfaced as
`decision.outcome="task_submitted"` (see
`test_task_submission_is_supported_and_explicit_over_the_fastmcp_binding`
vs. `test_task_submission_is_unsupported_and_fail_closed_over_the_sdk_binding`).

## Transient argument / digest binding

`execute_governed_call`'s `arguments` parameter is keyword-only and
verified with `sha256_digest(dict(arguments)) == request.argument_digest`
as the very first step -- before binding selection, connector resolution,
policy, or any receipt emission. On mismatch: `diagnostic_code=
"malformed_request"`, `decision.disposition="refused"`, `receipts=()`,
zero executions
(`test_argument_digest_mismatch_fails_closed_before_policy_or_execution`).
`arguments` is never stored on `GovernedCallRequest`, never placed on a
receipt (only `argument_digest`, computed independently by each binding
from the same `arguments` mapping, ever reaches a receipt), and falls out
of scope once the one call it was passed to completes
(`test_raw_arguments_are_not_persisted_on_receipts`).

## Trusted actor/tenant projection

Both bindings' existing resolver seams are used unmodified. `_execute_via_
fastmcp` supplies `DAGRMiddlewareConfig(actor_resolver=...)`;
`_execute_via_sdk` supplies `SdkBindingConfig(actor_resolver=...)`. In both
cases the resolver is a closure that ignores its `context`/`request_context`
and `snapshot` parameters entirely and returns
`ActorResolution(actor_ref=request.actor_ref.ref, tenant_id=request.
tenant_ref.ref if request.tenant_ref else None)` -- a value closed over from
the already-resolved `GovernedCallRequest`, never re-derived from a
transport or from tool arguments. `workspace_id` has no counterpart on
`GovernedCallRequest` and is left `None`.
`test_transient_arguments_cannot_reassert_actor_or_tenant` proves a decoy
`actor_ref`/`tenant_id` key placed in the transient `arguments` mapping has
no effect on the stamped receipt.

## Memory target allowlist model

`InMemoryToolConnector` is constructed from an operator-provided
`Mapping[target_handle, Mapping[tool_name, LocalToolHandler]]`. Its
`resolve(target_handle, tool_name)` performs a plain two-level dict lookup
and returns either the registered callable or a
`MemoryTargetResolutionRefused` fact -- never raises, never substitutes.
Reused diagnostics (no new taxonomy): an unregistered `target_handle` reuses
`remote_unavailable` (§4/§10's existing "target/remote unavailable"
diagnostic); an unregistered `tool_name` under a known handle reuses the
neutral core's own `unknown_tool_fail_closed` refusal ground. The connector
never receives call arguments (`resolve`'s signature has no argument
parameter at all -- checked by
`test_resolve_signature_carries_no_argument_parameter`) and has no
URL/hostname/port/subprocess/socket surface.

## Receipt-handle capture method

Neither binding returns emitted receipt ids to its own caller today (both
discard the outcome id and never return the admission id past their own
call boundary -- confirmed by re-reading both bindings in full). Rather than
modify either binding's return value or its emitter, A8 wraps the
operator-configured sink in `_CapturingSink`, a pure pass-through proxy: its
`write(envelope)` forwards to the real sink unchanged and additionally
appends a copy of the envelope to a local list; `write_trust_bundle` is
forwarded untouched. A fresh `SignedReceiptEmitter(identity=config.identity,
sink=_CapturingSink(config.sink, captured))` is constructed per call. After
the call, `_classify` builds `ReceiptHandle(receipt_id=..., receipt_kind=...,
location_handle=None)` for each captured envelope, in the order the binding
itself emitted them (admission first, outcome second when present) -- signed
receipt bytes durably written to `config.sink` are byte-identical to what
either binding would write unmodified; A8 only additionally observes them.
`location_handle` is always `None` in this lane (no unrestricted storage
path is ever returned); A10 owns handle-to-content resolution.

A second, load-bearing use of the same captured envelopes: **response
classification is derived from receipt structure (count and
`disposition`/`outcome` fields), never from raised-exception identity.**
The FastMCP binding raises the single `fastmcp.exceptions.ToolError` type
for every terminal admission outcome (refused, deferred, and
pre-execution-receipt-unavailable alike), so exception type alone cannot
distinguish them reliably. `_classify` instead inspects: zero captured
receipts + an exception -> `required_sink_unavailable` (the durable
admission write itself failed); one captured admission receipt with
`disposition=="refused"` -> refused, diagnostic narrowed from the
receipt's own `reason_code` to the closed `NEUTRAL_REFUSAL_GROUNDS`
vocabulary exactly as both bindings' own §7 discipline already does;
`disposition=="deferred_for_review"` -> deferred, `review_object_ref`/
`retry_instruction` read off the same envelope; `disposition=="admitted"`
with a raised exception -> the tool's own exception,
`diagnostic_code="remote_exception"`. A normal (non-raising) return reads
the outcome envelope's `outcome` field when present (`"error_returned"` /
`"result_returned"` / `"task_submitted"`), falling back to inspecting
`raw_result.is_error`/`.isError` directly (the same convention both
bindings' own projectors use) only for the rare case where the outcome
receipt itself failed to write (best-effort post-execution failure,
`alert_and_return_result`) and so no outcome envelope was captured at all.

## Supported response classes

All eight response classes named in scope §4 are implemented and tested,
across both bindings where applicable:

1. Admitted result -- `test_admitted_result_round_trips_and_returns_ordered_receipt_handles`.
2. Admitted tool-level error -- `test_admitted_tool_level_error_is_distinct_from_governance_refusal`.
3. Admitted exception -- `test_admitted_exception_produces_no_business_result` (raw exception message never leaks into the response or any receipt).
4. Refused -- `test_refusal_returns_single_admission_receipt_and_never_executes`.
5. Deferred for review -- `test_deferral_returns_single_receipt_with_review_ref_and_never_executes`.
6. Cancellation/indeterminate -- `test_cancellation_preserves_all_three_neutral_facts_and_stops_the_target` (all three `CancellationFacts` booleans `True`; a companion test proves the target coroutine genuinely stops rather than continuing unnoticed in the background).
7. Required sink unavailable -- `test_required_pre_execution_sink_failure_prevents_execution` (a `write`-classified tool with an always-failing sink; zero executions).
8. Explicitly unsupported lifecycle state -- exercised via the SDK binding's `task_submitted` capability gap (`test_task_submission_is_unsupported_and_fail_closed_over_the_sdk_binding`); `input_required` remains structurally unreachable through either binding's current code paths (neither binding ever constructs that neutral observation), so it is not independently exercisable at the A8 composition layer -- consistent with `dagr_mcp_lifecycle`'s own `UnsupportedLifecycleResult` non-coercion discipline.

Plus three A8-level pre-binding refusals not named as separate response-
contract rows but sharing the same `refused`, zero-receipt shape:
`malformed_request` (digest mismatch), `unknown_binding`/`binding_unavailable`
(binding selection), and `remote_unavailable`/`unknown_tool_fail_closed`
(connector target resolution) -- all proven to execute zero tool calls.

## Test results

```
$HOME/Developer/repos/dagr-mcp/.venv/bin/pytest tests/test_gateway_service_adapter.py tests/test_gateway_service_memory_connector.py -q
49 passed in 1.44s

$HOME/Developer/repos/dagr-mcp/.venv/bin/pytest tests/test_gateway_service_contract.py tests/test_gateway_service_resolution.py -q
73 passed in 0.68s

$HOME/Developer/repos/dagr-mcp/.venv/bin/pytest tests/test_fastmcp_binding.py tests/test_official_mcp_sdk_binding.py -q
50 passed in 2.06s

$HOME/Developer/repos/dagr-mcp/.venv/bin/pytest -q
650 passed, 2 skipped in ~8s

$HOME/Developer/repos/dagr-mcp/.venv/bin/python tools/check_public_release.py .
PASS: 0 finding(s)
```

Wheel (`dagr_mcp-0.1.0-py3-none-any.whl`) and sdist
(`dagr_mcp-0.1.0.tar.gz`) both built via `python -m build` with no
`pyproject.toml` change: the existing `[tool.setuptools.packages.find]
include = ["dagr_mcp*"]` glob already recurses into the new
`dagr_mcp_service.connectors` subpackage. Wheel-content inspection
(`unzip -l`) confirms all six `dagr_mcp_service`/`dagr_mcp_service.
connectors` modules are present, including the two new A8 files. A
clean-wheel smoke test (fresh venv, `pip install dagr_mcp-0.1.0-py3-none-
any.whl[official-sdk]`, no repository checkout on `sys.path`) drove one
admitted governed call through each binding successfully. `git diff --check`
reported no whitespace errors. Build, `*.egg-info`, `__pycache__`, `*.pyc`,
and `.pytest_cache` artifacts produced during verification were removed
before commit.

The known, out-of-scope FastMCP main-prerelease canary condition
(`CREATE_TASK_RESULT_IMPORT_PATH` falling back to `mcp_types.
CreateTaskResult` when `mcp.types.CreateTaskResult` is unavailable) was
left untouched per this lane's instructions; it did not manifest during
this lane's verification runs (`mcp==1.28.1` was installed throughout).

## Explicit absences

- **No network transport.** No socket, HTTP/ASGI client or server, stdio
  transport, subprocess, queue, or worker anywhere in the new code.
  `test_no_network_socket_is_created_during_an_admitted_call` monkeypatches
  `socket.socket` to raise and drives one admitted call through each
  binding without tripping it.
- **No Bossy-specific code.** Nothing in `dagr_mcp_service.adapter` or
  `.connectors.memory` names Bossy, RLS, or any Bossy-specific behavior;
  the connector is a narrow, generic in-process registry.
- **No JWT propagation proof.** No credential, JWT, or `Authorization`
  header handling exists in this lane; the §8 double-control claim remains
  unproven and unclaimed, exactly as scope §8 requires until A9's
  end-to-end test exists.
- **No idempotency, deduplication, retry, or exactly-once behavior.**
  `GatewayAdapterConfig` carries no idempotency key, dedup key, replay
  ledger, or retry-policy field
  (`test_no_idempotency_or_exactly_once_surface_on_the_adapter_config`);
  no public or private name on the `adapter` module contains
  `idempot`/`dedup`/`exactly_once`/`replay`
  (`test_no_idempotency_or_retry_names_appear_in_the_adapter_public_surface`).
  Each `execute_governed_call` invocation is an independent attempt with
  fresh receipt ids, exactly as both underlying bindings already produce
  standalone.
- **No import-time transport.** Importing `dagr_mcp_service`,
  `dagr_mcp_service.adapter`, or `dagr_mcp_service.connectors`/`.memory`
  never imports `mcp`, `fastmcp`, or any HTTP/ASGI/database/queue library;
  the concrete binding module for whichever binding a given call actually
  selects is imported lazily, inside `_execute_via_fastmcp`/
  `_execute_via_sdk` only.

## Corrective pass — independent review findings (JUL19, same day)

An independent read-only review of this lane, prior to marking it ready,
reproduced two defects in the original `dagr_mcp_service/adapter.py`. Both
are fixed in a follow-up corrective commit on this same branch; no other
file in the original diff list changed.

**Finding 1 — a pre-admission operator/resolver failure was misclassified as
a sink outage.** The original `_classify` treated *any* raised exception
with zero captured receipts as `required_sink_unavailable` -- including the
case where a configured `policy_resolver` (or another pre-admission
resolver) raises *before* the binding ever attempts a receipt write. Since
neither binding wraps its `_resolve_policy`/`_resolve_actor` call in a
try/except, such a failure propagates as the resolver's own exception with
`captured == []`, which the old code could not distinguish from "the
durable admission write itself raised." The result was a false
`required_sink_unavailable` governance diagnostic for a condition that never
touched the sink at all.

Fix: `_CapturingSink` now tracks `write_failed`, set only when its own
`write(envelope)` call to the inner sink raises. `_execute_via_fastmcp` and
`_execute_via_sdk` now guard the generic `except Exception` branch: when
`not captured and not capturing_sink.write_failed`, the caught exception is
re-raised (`raise`) rather than passed to `_classify` -- no target
execution, no fabricated receipt, no response at all, and therefore no
possibility of a false diagnostic. `_classify`'s `not captured` branch (and
its docstring) now documents that it may only be reached once a caller has
already confirmed a grounded sink-write failure via `write_failed`; the
pre-existing genuine sink-failure path (`_AlwaysFailingSink`,
`test_required_pre_execution_sink_failure_prevents_execution`) is
unchanged and still returns `required_sink_unavailable`. No exception
message, stack, or resolver internals are placed on any
`GovernedCallResponse` -- the raw exception simply propagates out of
`execute_governed_call` as a Python exception, never as response content.
Applied identically to both `_execute_via_fastmcp` and `_execute_via_sdk`.

**Finding 2 — `ReceiptHandle.receipt_id` was read back from the pre-write
envelope instead of the sink's own return value.** `_CapturingSink.write`
called `receipt_id = inner.write(envelope)` but then captured a copy of the
*envelope* and later built `ReceiptHandle.receipt_id` from
`envelope["receipt_id"]` -- silently assuming the sink's returned identifier
always equals the envelope's own field. Every sink shipped in this
repository happens to satisfy that assumption (`RawEnvelopeFileSink.write`
returns `str(envelope["receipt_id"])`), so the bug was latent, not
observed, in this lane's own test suite.

Fix: introduced a narrow, immutable `_CapturedReceipt` record
(`receipt_id`, `receipt_kind`, `disposition`, `outcome`, `reason_code`,
`review_object_ref` -- the minimum fields `_classify` needs) built from the
sink's own return value (`str(receipt_id)`), not the envelope. Nothing is
appended to `captured` when the sink write raises. `_receipt_handle` now
takes a `_CapturedReceipt` and reads `.receipt_id` directly. Per-call
capture isolation (a fresh `list`/`_CapturingSink` per `execute_governed_call`
invocation) and admission-before-outcome ordering are both unchanged.

**Regression tests added** (`tests/test_gateway_service_adapter.py`, both
bindings unless noted):

- `test_pre_admission_resolver_failure_executes_no_target_and_is_not_sink_unavailable`
  -- a raising `policy_resolver` executes no target, writes no receipt, and
  propagates its own exception type rather than returning any response.
- `test_pre_admission_resolver_failure_and_genuine_sink_failure_stay_distinguishable`
  -- drives both failure causes back to back and asserts they never
  collapse into the same (or an indistinguishable) outcome: one raises, the
  other returns a grounded `required_sink_unavailable` refusal.
- `test_receipt_handle_uses_the_sink_returned_identifier` -- a custom
  `_RemappingIdSink` returns an identifier distinct from the envelope's own
  `receipt_id`; asserts `response.receipts[*].receipt_id` matches the
  sink's return value and is disjoint from the on-disk envelope's own ids.

## Corrective-pass test results

```
$HOME/Developer/repos/dagr-mcp/.venv/bin/pytest tests/test_gateway_service_adapter.py -q
47 passed in 2.02s

$HOME/Developer/repos/dagr-mcp/.venv/bin/pytest tests/test_gateway_service_adapter.py tests/test_gateway_service_memory_connector.py -q
55 passed in 1.39s

$HOME/Developer/repos/dagr-mcp/.venv/bin/pytest tests/test_gateway_service_contract.py tests/test_gateway_service_resolution.py -q
73 passed in 0.73s

$HOME/Developer/repos/dagr-mcp/.venv/bin/pytest tests/test_fastmcp_binding.py tests/test_official_mcp_sdk_binding.py -q
50 passed in 2.03s

$HOME/Developer/repos/dagr-mcp/.venv/bin/pytest -q
656 passed, 2 skipped in 8.58s

$HOME/Developer/repos/dagr-mcp/.venv/bin/python tools/check_public_release.py .
PASS: 0 finding(s)
```

Wheel (`dagr_mcp-0.1.0-py3-none-any.whl`) and sdist
(`dagr_mcp-0.1.0.tar.gz`) rebuilt cleanly via `python -m build`; wheel
content inspection confirms all six `dagr_mcp_service`/`.connectors`
modules are present with the corrected `adapter.py`. A fresh clean-wheel
smoke test (new venv, `pip install dagr_mcp-0.1.0-py3-none-any.whl
[official-sdk]`, no repository checkout on `sys.path`) drove one admitted
governed call through each binding successfully. `git diff --check`
reported no whitespace errors. All build/cache artifacts were removed
before staging.

## A9 boundary

A9 ("one selected remote transport / client connector") is the next work
package. It is the first component in this lineage permitted to:

1. add a client-side connector that forwards a call to a genuinely remote
   MCP server (`connectors/http.py` and/or `connectors/stdio.py`), behind a
   new optional dependency extra;
2. accept or propagate a caller-presented credential (e.g. a Bossy JWT)
   toward that remote server;
3. implement or exercise SSRF/allowlist host-pinning behavior for a real
   network target;
4. run the named JWT-propagation acceptance test that would let the §8
   double-control claim be asserted as proven, rather than left open.

`dagr_mcp_service.connectors.memory.InMemoryToolConnector` remains the only
connector this repository ships after this lane; it resolves an
operator-registered local callable and nothing else. Everything this lane
adds continues to operate entirely in-process, with the same binding
selection (`dagr_mcp_service.resolution.select_binding`) and the same two
binding identities A9 will reuse unchanged.
