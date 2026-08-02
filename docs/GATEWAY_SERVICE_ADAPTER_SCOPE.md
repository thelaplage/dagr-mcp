# DAGR Gateway Service Adapter — Scope and Decision Record (v0.1)

> **Historical scope record.** This document describes the repository before
> `dagr_mcp_service` and its in-process / remote connector surfaces were
> implemented. Statements below such as “does not exist today” are preserved as
> historical findings at the named base commit, not as the current inventory.
> See [PRODUCT_ARCHITECTURE.md](PRODUCT_ARCHITECTURE.md) for current state.

**Status:** Scoping and inventory only. No server, transport, remote caller,
queue, persistence layer, receipt-subscription service, or Bossy integration is
implemented by this document or the PR that introduces it.

**Sprint:** DAGR MCP A6.
**Base:** `9874486e36dbe543dab903e2de7df46ec60004bb`
(`feat: add official Python MCP SDK lifecycle binding (#11)`).

This document is a byte-grounded inventory and an implementation-scoping contract
and decision record. Every existing symbol it names was verified against the
repository at the base commit. Where it proposes a name, signature, module, or
transport, it says so explicitly and marks the decision as *ratification
pending*. It writes no Python, schema, receipt profile, CI, dependency, or
public-API change.

Cross-references (all resolve in this repository):

- [`docs/NEUTRAL_LIFECYCLE_CONTRACT.md`](NEUTRAL_LIFECYCLE_CONTRACT.md)
- [`docs/NEUTRAL_LIFECYCLE_CORE.md`](NEUTRAL_LIFECYCLE_CORE.md)
- [`docs/FASTMCP_CORE_REBINDING.md`](FASTMCP_CORE_REBINDING.md)
- [`docs/OFFICIAL_MCP_SDK_BINDING.md`](OFFICIAL_MCP_SDK_BINDING.md)
- [`docs/BINDING_VERSIONS.md`](BINDING_VERSIONS.md)

---

## Executive finding

**What exists.** DAGR has two implemented lifecycle *bindings* that both defer
every lifecycle decision to a single binding-neutral core, plus a shared signed
receipt emitter, a refs-only custody-projection contract, a policy-profile
projection, sink protocols with in-memory implementations, and a synchronous
enforcement harness. Both bindings are **server-side interceptors**: they sit
*inside* or *around* an MCP server and observe a `tools/call` as it is handled.

**What is reusable.** Directly reusable, unchanged: the neutral core
(`dagr_mcp_lifecycle`), the signed emitter (`dagr_mcp.srs_receipts`), the
shared neutral adapter layer (`dagr_mcp_sdk_binding.neutral`), the sink
protocols and `ReviewObject`/custody contracts (`dagr_mcp.sdk_spine`,
`dagr_mcp.mcp_record_custody_gateway`), the policy-profile projection
(`dagr_mcp.policy_profile`), and both binding adapters' construction surfaces.
The official-SDK adapter's `governed_call(..., delegate=...)` seam is the
natural insertion point for a client-side forwarder — but the forwarder does
not exist.

**What is missing.** There is no neutral service operation, no request/response
DTO for a remote caller, no configuration-driven binding *selector*, no
client-side connector that forwards a call to a *remote* MCP server, no way to
return a business result together with receipt handles to another process, and
no way to expose emitted receipts across a process boundary beyond files on
disk. No transport, service loop, worker, queue, or subscription code is
present.

**Production service adapter present?** **No.** Confirmed empty by inspection.
The only symbol carrying "gateway" in its name — `MCPRecordCustodyGateway` in
`dagr_mcp/mcp_record_custody_gateway.py` — is explicitly a refs-only contract
object with "no MCP client/server runtime; no HTTP adapter; … no sink write; no
record admission" (its own module docstring). It is a data contract, not a
service. A repository-wide sweep for `asgi|uvicorn|starlette|aiohttp|httpx|`
`fastapi|flask|websocket|streamable|stdio_server|sse|subscri|worker|queue|`
`celery|remote` over `dagr_mcp*` source (excluding tests) returns no transport,
service, or forwarding implementation.

---

## 1. Purpose and non-goals

The Gateway Service Adapter is the neutral service/composition seam that lets an
agent/demo host submit a governed MCP tool call that DAGR admits, forwards to an
arbitrary MCP server (including `bossy-mcp`), and attests with signed receipts —
without putting DAGR code into `bossy-mcp` and without putting ARCS in the
runtime critical path.

**Purpose.**

- Present one transport-neutral operation that accepts a neutral admission
  request and returns a business result plus receipt handles.
- Select a *configured* DAGR binding and delegate all protocol behavior to it.
- Preserve the A1/A4/A5 behavioral freezes and the neutral core's authority
  over every lifecycle decision.

**Non-goals (binding commitments for this and the immediate follow-on PRs).**

- **Adapter is DAGR-owned.** It lives in this repository, under DAGR's release
  gate and naming discipline.
- **`bossy-mcp` remains DAGR-free.** No DAGR import, middleware, or receipt code
  is added to `bossy-mcp`. The adapter treats it as an ordinary remote MCP
  server reached through a client connector.
- **ARCS remains independent and out of path.** The adapter never calls ARCS.
  Verification is asynchronous and consumes emitted receipts after the fact.
- **The adapter does not implement MCP itself.** It constructs no protocol
  framing, negotiates no capabilities, and parses no wire messages of its own.
- **The adapter delegates protocol behavior to supported bindings**
  (`fastmcp.middleware.v0.1`, `official-mcp-sdk.python.v0.1`).
- **No production transport is selected or implemented by this PR.** §7
  recommends a first transport; the choice is left as a ratification decision.

---

## 2. Exact current-state inventory

All paths are repository-relative. Signatures are quoted from the base commit.

### 2.1 FastMCP binding — construction and invocation

- Module: `dagr_mcp/fastmcp_binding.py`.
- `BINDING_VERSION = "fastmcp.middleware.v0.1"`.
- `class DAGRMiddleware(Middleware)` — constructed
  `DAGRMiddleware(*, emitter: SignedReceiptEmitter, config: DAGRMiddlewareConfig)`.
- **Invocation seam:** `async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext) -> ToolResult`.
  This is a FastMCP *server-side middleware hook*. The actual tool runs inside
  `await call_next(context)`. It is **not** a remote client call.
- `@dataclass(slots=True) class DAGRMiddlewareConfig` — fields include
  `runtime_instance_id`, `boundary_id`, `policy_pack_id`, `policy_pack_version`,
  `tool_classes`, `actor_resolver`, `policy_resolver`, `review_object_creator`,
  `pre_execution_receipt_failure`, `post_execution_receipt_failure`,
  `emit_read_admission_before_execution`, `emergency_spool_path`,
  `parent_receipt_ref`, `logical_call_id_override`, `subject_ref_override`,
  `result_projection_observer`, `additional_attestation_limits`.
- Resolved value types: `RequestSnapshot`, `ActorResolution`, `BindingPolicy`.
- Resolver contracts: `ActorResolver`, `PolicyResolver` (Protocols),
  `ReviewObjectCreator` (callable type alias).
- Helpers: `default_actor_resolution()`, `project_fastmcp_tool_result(result)`,
  `CREATE_TASK_RESULT_IMPORT_PATH`.

### 2.2 Official Python MCP SDK binding — construction and invocation

- Package: `dagr_mcp_sdk_binding/` (adapter, mask, server, neutral submodules).
- `BINDING_VERSION = "official-mcp-sdk.python.v0.1"` (exposed by the package
  root *without* importing the SDK; submodules are PEP 562 lazy).
- `class SdkLifecycleAdapter` — constructed
  `SdkLifecycleAdapter(*, emitter: SignedReceiptEmitter, config: SdkBindingConfig)`.
- **Invocation seam:**
  `async def governed_call(self, tool_name, arguments, delegate: ToolHandler, *, request_context: RequestContext | None = None) -> Any`.
  The tool runs inside `await _maybe_await(delegate(arguments or {}))`. The
  `delegate` is the sole execution seam — today wired only to local dispatch.
- `ToolHandler = Callable[[Mapping[str, Any]], Awaitable[Any] | Any]`.
- `@dataclass(slots=True) class SdkBindingConfig` — same field set as the
  FastMCP config, with `SdkActorResolver` / `SdkPolicyResolver` Protocols.
- Construction surface: `dagr_mcp_sdk_binding/server.py` —
  `GovernedTool(definition, handler)`,
  `wrap_server(server: Server, adapter, *, tools=(), delegated_call_handler=None)`,
  `build_governed_server(name, *, adapter, tools=(), delegated_call_handler=None, version=None)`.
  These register `@server.list_tools()` / `@server.call_tool()` on an
  `mcp.server.lowlevel.Server` and read the **trusted** `server.request_context`.
  This is again **server-side** handler registration, not a remote client.
- Transport-native errors: `SDKBindingError`, `ToolRefused`, `ToolDeferred`,
  `AdmissionReceiptUnavailable`, `TaskSubmissionUnsupported`.
- Helpers: `default_sdk_actor_resolution()`, `project_sdk_tool_result(result)`.

### 2.3 Binding-neutral core — inputs and outputs

- Package: `dagr_mcp_lifecycle/` (`contract.py`, `models.py`, `core.py`,
  `binding_mask.py`).
- Inputs (`models.py`): `AdmissionRequest(disposition, tool_class,`
  `refusal_ground, review_object_created, emit_read_admission_before_execution,`
  `has_parent_boundary)`; `ExecutionObservation(observation, exception_class,`
  `input_required_mode)`.
- Outputs: `AdmissionPlan`, `OutcomePlan`, `LifecyclePlan`,
  `AdmissionRecordIntent`, `OutcomeRecordIntent`, `UnsupportedLifecycleResult`,
  `UnsupportedLifecycleEvent`.
- Planners (`core.py`): `plan_admission`, `plan_outcome`, `plan_outcome_strict`,
  `plan_lifecycle`, `plan_lifecycle_strict`, `core_outcome_status`.
- The core mints no identifier, timestamp, signature, digest value, protocol
  version, or binding identifier; those are enumerated as
  `AdapterResponsibility` values and are the adapter's duty.
- Neutral vocabulary (`contract.py`): dispositions
  `admitted|refused|deferred`; refusal grounds `policy_refused |`
  `unknown_tool_fail_closed | required_sink_unavailable |`
  `review_object_creation_failed`; outcomes `result | error | exception |`
  `task_submitted | timeout | cancellation | input_required`;
  `RECEIPT_CARDINALITY = {admitted: 2, refused: 1, deferred: 1}`;
  `DEFERRAL_CONTINUATION_CONTRACT = "retry_after_approval"`.

### 2.4 Policy and actor resolution contracts

- **Actor resolution** is derived *only* from the trusted transport context,
  never from model arguments. FastMCP: `ActorResolver(context, snapshot)` and
  `default_actor_resolution()` reading `fastmcp.server.dependencies`
  `get_access_token()`. Official SDK: `SdkActorResolver(request_context,`
  `snapshot)` and `default_sdk_actor_resolution()` reading
  `mcp.server.auth.middleware.auth_context.get_access_token()`. Both hash claims
  into scoped refs (`actor:sha256:…`, `tenant:sha256:…`, `workspace:sha256:…`).
- **Policy resolution** returns a `BindingPolicy(disposition, tool_class,`
  `reason_code, parent_receipt_ref, additional_attestation_limits)`. The default
  resolver admits and reads `tool_classes.get(name, "read")`.
- **Policy-profile projection** (`dagr_mcp/policy_profile.py`):
  `project_policy_profile`, `load_policy_profile`, `PolicyProfileProjection`,
  `SinkRequirements`, with `required_sink_failure_behavior ∈ {fail_closed,`
  `degraded, pending, advisory}` (default `fail_closed`).
- The harness (`dagr_mcp/enforcement_harness.py`) has its own richer
  `ToolPolicy`/`PolicyDecision` types with decisions
  `allow|deny|gate|defer|fail_closed`.

### 2.5 Signed receipt emitter — construction

- Module: `dagr_mcp/srs_receipts.py`.
- `SigningIdentity` (Ed25519; `generate(*, issuer_id, key_id)`,
  `trust_bundle()`, `sign_envelope()`), `ReceiptContext(...)`,
  `SignedReceiptEmitter(*, identity, sink, receipt_id_factory=None,`
  `issued_at_factory=None)`.
- Emit methods: `emit_admission(*, context, requested_tool_name,`
  `argument_digest, disposition, review_object_ref=None, retry_contract=None,`
  `reason_code=None, additional_attestation_limits=())` → receipt id;
  `emit_outcome(*, context, admission_receipt_ref, outcome, result_digest=None,`
  `exception_class=None, additional_attestation_limits=(),`
  `binding_owned_fields=None)` → receipt id.
- Profile constants: `RECEIPT_VERSION = "srs.core.v5.1"`,
  `PROFILE_ID = "srs.mcp.sdk_enforcement"`, `PROFILE_VERSION = "v0.1"`.
- Binding-version gate: `REGISTERED_BINDING_VERSIONS`
  (`direct-harness.v0.1`, `fastmcp.middleware.v0.1`),
  `ADDITIONAL_BINDING_VERSIONS` (`official-mcp-sdk.python.v0.1`), and the union
  `ALL_REGISTERED_BINDING_VERSIONS` the emitter's `_common` requires.
- Content discipline: `enforce_raw_content_exclusion`, `RAW_KEYS`,
  `PRIVATE_MARKERS`, `ReceiptContentError`, `ReceiptWriteError`.

### 2.6 Receipt sinks and custody storage

- **Receipt sink:** `RawEnvelopeFileSink(directory)` — atomic
  one-envelope-per-file, owner-only permissions, `write(envelope) -> receipt_id`,
  `write_trust_bundle(...)`. No private signing key is persisted. This is the
  only durable receipt store present; it is a local filesystem sink.
- **Sink protocols** (`dagr_mcp/sdk_spine.py`): `EventSink`, `ReceiptSink`,
  `ArtifactSink`, `ReviewObjectSink`, `LintFindingSink`, each with `health() ->`
  `SinkHealth` and `supports_capability`. In-memory implementations exist for
  all five. `SinkHealth` durability values include `memory|file|database|`
  `remote|unknown`; no non-memory implementation ships in this repository.
- **Custody projection** (`dagr_mcp/mcp_record_custody_gateway.py`):
  `MCPRecordCustodyGateway` / `build_mcp_record_custody_gateway(**kwargs)`,
  schema `garp.mcp_record_custody_gateway.v0.1`, nine `GatewayCustodyStatus`
  values, four `GatewayBoundaryType` values, three `GatewayReceiptFamily`
  values, refs-and-hashes only, `observed_at` timestamp. No sink write, no
  record admission, no runtime.

### 2.7 Review-object creation

- Contract object: `ReviewObject` in `dagr_mcp/sdk_spine.py`
  (`review_object_type`, `governance_state`, `context_payload`,
  `allowed_actions`, `created_at`, `origin_event_id`). Canonical states
  `pending|approved|rejected|deferred|expired`.
- Both binding adapters mint a review object via a configured
  `review_object_creator` (`_create_review_object`) *before* the core can
  resolve a deferral; a creator that raises resolves — in the core — to a
  refusal on `review_object_creation_failed` (never
  `required_sink_unavailable`).
- Harness path: `build_tool_call_disposition_review_object(...)` in
  `dagr_mcp/tool_call_disposition.py`, driven by `_gate_call` in the harness.
- Durable review queue: `ReviewObjectSink.create_review_object` / in-memory
  `InMemoryReviewObjectSink`. No cross-process review-object service exists.

### 2.8 Failure-policy configuration

- Pre-execution receipt failure (per tool class):
  `pre_execution_receipt_failure: Mapping[ToolClass, "fail_closed"|"fail_open"]`,
  defaulting `read→fail_open`, `write→fail_closed`, `destructive→fail_closed`,
  on both binding configs.
- Post-execution receipt failure:
  `post_execution_receipt_failure = "alert_and_return_result"`.
- `emit_read_admission_before_execution: bool = True`.
- Sink-requirement failure behavior on the policy profile:
  `required_sink_failure_behavior` (default `fail_closed`).
- Receipt-gap telemetry: `local_telemetry` list plus an optional atomic
  `emergency_spool_path` append (both adapters).

### 2.9 Existing direct harness and CLI behavior

- **Direct harness:** `dagr_mcp/enforcement_harness.py` — `wrap_handler(inner,`
  `config, sinks, policies=None, policy_profile=None, srs_bridge=None)` returns
  a synchronous `wrapped(tool_name, arguments, context) -> GovernedResult`. It
  emits events, evaluates `ToolPolicy`, gates review-required calls, writes
  hash-only receipts, and (via an optional `srs_bridge`) signed SRS receipts. It
  "does not implement an MCP server and ships no runtime policy packs."
- **SRS bridge:** `dagr_mcp/srs_bridge.py` — `HarnessSRSBridge` /
  `BridgeConfig`, default `binding_version = "direct-harness.v0.1"`.
- **CLI / process surface:** `dagr_mcp/demo.py` — `main()` behind console
  scripts `dagr-mcp` and `dagr-mcp-demo`. `run_demo(output, direct=False)` runs
  either the direct-harness path or a FastMCP demo that constructs a
  `FastMCP("dagr-mcp-demo")` server and drives it through an **in-process**
  `fastmcp.client.Client(server)` (in-memory transport). It prints an
  `arcs-verify` command over the written receipts.

### 2.10 Packaging, entry points, process surfaces

- `pyproject.toml`: `name = "dagr-mcp"`, `version = "0.1.0"`,
  `requires-python = ">=3.11"`, `license = "Apache-2.0"`.
- Runtime deps: `cryptography>=46.0.4,<47`, `fastmcp>=3.4.4,<4`,
  `rfc8785==0.1.4`.
- Optional extras: `dev`; `amnesiac = [arcs-amnesiac>=0.2.0, garp-sdk>=0.1.0]`;
  `official-sdk = [mcp==1.28.1]` (exact pin — see
  [`docs/OFFICIAL_MCP_SDK_BINDING.md`](OFFICIAL_MCP_SDK_BINDING.md)).
- Console scripts: `dagr-mcp` and `dagr-mcp-demo`, both `dagr_mcp.demo:main`.
- Package discovery: `[tool.setuptools.packages.find] include = ["dagr_mcp*"]`
  — the glob matches `dagr_mcp`, `dagr_mcp_lifecycle`, and `dagr_mcp_sdk_binding`
  today, and would match a new `dagr_mcp_service` package.
- No `[project.entry-points]` plugin groups. No long-running process, server
  daemon, or worker.

### 2.11 Existing HTTP / stdio / ASGI / service / worker / queue / subscription code

**None.** No such module exists in `dagr_mcp*` source. The FastMCP and official
SDK libraries provide their own transports, but this repository imports only
their *server construction* and *in-process client* surfaces (for the FastMCP
demo) and never starts, binds, or listens on a transport of its own. The
custody-gateway module explicitly disclaims any HTTP adapter or MCP runtime.

### 2.12 Request IDs, logical-call IDs, parent references, correlation, idempotency

- **Logical call id:** `logical_call_id` — override, else the request-scoped
  hash ref, else `call:<uuid4>`.
- **Subject ref:** `subject_ref` — override, else session ref, else request ref,
  else `tool-call:<logical_call_id>`.
- **Request / session refs:** `request_ref`/`session_ref` are scoped hashes of
  the transport's `request_id` / `session_id` (`request:sha256:…`,
  `session:sha256:…`), captured from the trusted context.
- **Parent receipt reference:** `parent_receipt_ref` (config or per-policy),
  carried onto the emitted receipt; the neutral edge is `parent_reference`.
- **Outcome→admission reference:** every outcome receipt carries
  `admission_receipt_ref` (neutral edge `outcome_to_admission`).
- **Correlation across records:** `runtime_instance_id`, `boundary_id`,
  `logical_call_id` appear on every receipt and on receipt-gap telemetry.
- **Idempotency:** *none.* There is no idempotency key, no dedup ledger, and no
  response replay. `receipt_id` defaults to `urn:srs:receipt:<kind>:<uuid4>` —
  a fresh identifier per emit. A retried request produces fresh receipts.

### 2.13 Can any current API …?

| Capability | Present today? | Evidence |
|---|---|---|
| Accept a neutral **remote** admission request | **No** | No request DTO or entry point exists; adapters take in-process binding types. |
| Select a binding from configuration | **No** | Each adapter *is* one binding; no selector maps a config value to a binding. |
| Forward a call to a **remote** MCP server | **No** | Both adapters intercept server-side; `governed_call`'s `delegate` runs locally; no client connector exists. |
| Return a business result **plus receipt handles** | **Partial / No** | Adapters return the business result only; receipt ids are returned by the emitter internally, not surfaced to a caller as handles. |
| Expose emitted receipts to another process | **Partial** | Only as files written by `RawEnvelopeFileSink`; there is no query/handle/subscription API. |

---

## 3. Service boundary

### 3.1 The conceptual operation

Proposed neutral operation (**name ratification pending** — the official-SDK
adapter already defines `SdkLifecycleAdapter.governed_call`, so the service seam
must be named distinctly to avoid collision):

```
execute_governed_call(request: GovernedCallRequest) -> GovernedCallResponse
```

It is transport-neutral: it does not name HTTP, stdio, or any framing. A
concrete transport (§7) is a thin front that deserializes into
`GovernedCallRequest`, calls this operation, and serializes
`GovernedCallResponse`. The operation internally (a) validates the request,
(b) selects the configured binding (§5), (c) resolves actor/policy from
*trusted* context, (d) obtains the admission plan from the neutral core, (e) for
an admitted call, forwards through the selected binding's connector to the
target MCP server, and (f) records outcome receipts.

### 3.2 Minimum request facts

`GovernedCallRequest` must carry, and only carry:

- **request/correlation identifier** — caller-supplied opaque id used as the
  logical-call correlation seed (never trusted as an actor claim).
- **configured binding identifier** — a *selector key*, not a free binding
  string (§5); resolved against operator configuration.
- **trusted actor reference** — derived by the service from the authenticated
  transport context, *not* read from this field if a caller supplies one; the
  field documents the resolved value the service will stamp.
- **trusted tenant / organization reference** — when applicable; same
  trust rule as actor.
- **boundary type** — pinned to `mcp_tool_call` for v0.1.
- **target MCP server reference** — an operator-allowlisted server *handle*
  (§12 SSRF), not an arbitrary URL from the model.
- **tool name** — the remote tool to invoke.
- **refs-only argument projection or argument digest/reference** — the adapter
  digests arguments (`sha256:` over the RFC 8785 canonical form) exactly as the
  bindings do; the request carries the digest/reference, not raw arguments,
  wherever the caller can supply them pre-digested. Raw arguments that must
  transit to the remote server are held only long enough to forward and are
  never placed on a receipt.
- **policy profile reference** — selects the `PolicyProfileProjection`.
- **optional parent receipt reference** — for deliberate boundary linkage.
- **transport-agnostic metadata allowlist** — a closed set of non-sensitive
  keys (e.g. client protocol hints) that may be digested into `meta_digest`.

### 3.3 Prohibited caller authority

The request must **not** be able to assert any of the following; each is
resolved by the service or refused:

- caller-selected signing identity;
- caller-selected role;
- caller-selected policy outcome (admit/refuse/defer);
- caller-selected organization authority;
- raw credentials in the payload;
- service-role credentials (there is no service-role fallback — §12);
- arbitrary receipt IDs;
- arbitrary custody disposition (`GatewayCustodyStatus`);
- arbitrary binding-version stamp (the stamp is the *selected binding's* fixed
  identity, gated by `ALL_REGISTERED_BINDING_VERSIONS`).

This mirrors the existing discipline: both adapters derive actor/tenant from the
trusted context only and pass a *neutral* refusal ground to the core, while the
binding-version stamp is a fixed constant per binding.

---

## 4. Response contract

`GovernedCallResponse` separates five concerns that must never be conflated:

1. **MCP business result** — the remote tool result (or tool-level error
   payload), passed through to the caller. Present only for admitted calls that
   returned.
2. **DAGR decision** — the resolved neutral disposition/outcome
   (`admitted|refused|deferred` and, for executed calls, the outcome family).
3. **Receipt handles/references** — the `receipt_id`(s) emitted, and/or a
   location handle. Never the signer, signing key, or an unrestricted storage
   path.
4. **Custody observation reference** — an optional `MCPRecordCustodyGateway`
   projection reference associated with the logical call.
5. **Retry/continuation instruction** — e.g. `retry_after_approval` for a
   deferral; a retry posture for transient remote failures (§10).
6. **Adapter diagnostic code** — a stable, content-free code
   (e.g. `required_sink_unavailable`, `remote_unavailable`), never a raw
   exception or stack.

Per response class:

| Response class | Business result | DAGR decision | Receipt handles | Custody ref | Retry/continuation | Diagnostic |
|---|---|---|---|---|---|---|
| **admitted result** | tool result | admitted + `result` | admission + outcome (2) | optional | none | none |
| **admitted tool-level error** | error payload | admitted + `error` | admission + outcome (2) | optional | caller-defined | `tool_error` |
| **admitted exception** | none | admitted + `exception` | admission + outcome (2, no result digest) | optional | none/none-safe | `remote_exception` |
| **refused** | none | refused | admission (1) | optional | none | refusal ground verbatim |
| **deferred for review** | none | deferred | admission (1) w/ review ref | optional | `retry_after_approval` | `deferred_for_review` |
| **cancellation/indeterminate** | none | admitted + `indeterminate` | admission + outcome (2) w/ three cancellation Booleans | optional | indeterminate | `cancelled` |
| **required sink unavailable** | none | refused | 0 or 1 (best effort) | none | operator | `required_sink_unavailable` |
| **explicitly unsupported lifecycle state** | none | n/a | 0 | none | none | `unsupported_lifecycle_state` |

**Never returned:** raw signer or signing key, raw credentials, policy
internals, or an unrestricted receipt-storage filesystem path.

---

## 5. Binding resolution

Configuration selects exactly one binding per deployment (or per allowlisted
target), from the two registered identities:

- `fastmcp.middleware.v0.1` (`dagr_mcp.fastmcp_binding`);
- `official-mcp-sdk.python.v0.1` (`dagr_mcp_sdk_binding`).

**Selection is operator/deployment configuration, never a model tool argument.**
The `configured binding identifier` in the request (§3.2) is a *selector key*
resolved against an operator-provided map; a caller cannot introduce a new
binding string or a binding-version stamp. The stamp on every receipt is the
selected binding's fixed `BINDING_VERSION`, which must be a member of
`ALL_REGISTERED_BINDING_VERSIONS` or the emitter's `_common` refuses it.

### 5.1 Capability differences to honor

| Capability | `fastmcp.middleware.v0.1` | `official-mcp-sdk.python.v0.1` |
|---|---|---|
| `task_submitted` outcome | supported (observes `CreateTaskResult`) | **unsupported** over `ClientSession.call_tool`; adapter raises `TaskSubmissionUnsupported` (fails closed) |
| `input_required` | unsupported (neutral, not carried) | unsupported (both modes; elicitation exists in the SDK but is deliberately not a DAGR disposition) |
| Interception seam | FastMCP middleware `on_call_tool` | lowlevel `Server.call_tool` handler registration |
| Trusted context source | `fastmcp.server.dependencies.get_access_token()` | `mcp.server.auth.middleware.auth_context.get_access_token()` |
| Transport-native refusal signal | `fastmcp.exceptions.ToolError` | `SDKBindingError` subclasses |

These differences are recorded byte-for-byte in the A5 mask
(`dagr_mcp_sdk_binding/mask.py`, `BINDING_UNSUPPORTED_OUTCOME_TOKENS`) and the A2
mask, and are grounded against the installed SDK by `verify_mask_matches_binding`.

### 5.2 Fail-closed for unknown/unavailable binding

- An unknown selector key → refuse with a stable diagnostic
  (`unknown_binding`); no default binding is chosen.
- A configured-but-unavailable binding (its optional dependency is not
  installed — e.g. `official-sdk` extra absent) → refuse with
  `binding_unavailable`; the service never silently substitutes the other
  binding. Neither failure executes the remote tool.

---

## 6. Invocation topology

Three shapes were evaluated. **Server-side interception and client-side
forwarding are deliberately kept separate**, because the existing bindings do
the former and the demonstrator needs the latter.

### A. In-process wrapping of a locally constructed MCP server

The adapter constructs (or is handed) an MCP server *in this process* and
governs its `tools/call`. This is exactly what exists today:
`DAGRMiddleware.on_call_tool` and `wrap_server(...)` + in-process
`Client(server)`. **Useful for tests and single-process deployments; it is not
the demonstrator shape** because `bossy-mcp` is a separate server.

### B. Adapter as an MCP *client* forwarding to a remote MCP server

The adapter is an MCP *client* that connects to a remote MCP server and forwards
the admitted call. **This connector does not exist today.** The official-SDK
adapter's `governed_call(..., delegate=...)` seam is where such a client
forwarder would be injected: the `delegate` would issue a
`ClientSession.call_tool(...)` against the remote server and return its
`CallToolResult`. Building this connector (client-side) is net-new work.

### C. Adapter as a *service* receiving neutral requests and delegating to a configured binding-specific connector

The adapter is a service that accepts `GovernedCallRequest` (§3), selects a
binding (§5), and delegates to that binding's **client-side connector** (shape
B) to reach the remote MCP server. This composes shapes B into a request/response
service.

**Required shape for the Bossy demonstrator: C, built on B.** The topology is:

```
Agent/demo host
  → DAGR Gateway Service Adapter        (shape C: neutral request in)
  → configured DAGR binding             (§5 selection)
  → binding client connector            (shape B: NEW — client to remote MCP)
  → bossy-mcp MCP server                (remote; DAGR-free)
  → result                              (business result back to the caller)
  → DAGR receipts emitted out of band   (signed, to a sink)
  → ARCS verifies independently         (asynchronous, out of path)
```

The current binding adapters are **not** remote-client connectors; they are
server-side interceptors. A6 does not assume otherwise. A8 builds shape A/C
in-process first (no network), and A9 builds the shape-B connector for one
selected transport.

---

## 7. Transport decision surface

Compared for the client connector to the remote MCP server. **Deprecated
HTTP+SSE is explicitly not a target.**

| Property | stdio | Streamable HTTP | In-process memory (tests) |
|---|---|---|---|
| Trusted context source | subprocess env / launch args | HTTP `Authorization` header + request context | direct Python call |
| Authentication location | process ownership / launch | header-borne bearer/JWT at the HTTP edge | none (test) |
| Cancellation propagation | process signal / stream close → `CancelledError` | HTTP request cancel / stream close → `CancelledError` | task cancellation |
| Protocol-version metadata | initialize handshake (not stamped — see mask) | initialize handshake (not stamped) | handshake (not stamped) |
| Deployment implications | co-located subprocess; no network surface | network service; needs TLS, allowlist, host pinning | none; unit/integration tests |
| Observability | process logs | HTTP logs + request ids | in-test assertions |
| Retry duplication risk | low (single stream) | higher (HTTP retries can duplicate) → §11 | none |

**Recommendation (ratification pending):**

- **Tests: in-process memory transport** — deterministic, no network, mirrors
  the existing FastMCP demo's `Client(server)` pattern. Adopt in A8.
- **First remote transport for the demonstrator: Streamable HTTP.** `bossy-mcp`
  is a separate network service whose row-level authority (RLS) depends on the
  caller's JWT arriving in an HTTP `Authorization` header; stdio cannot carry
  that header context. Streamable HTTP is therefore the realistic demonstrator
  transport. Adopt in A9 *after* the JWT-propagation proof (§8).
- **stdio** is retained as a simpler co-located option for a non-Bossy
  end-to-end proof, but is not the demonstrator target.

This is a recommendation, not an implementation. The transport remains unratified pending
A9's PR, not here.

---

## 8. Authority and tenant model

Complete trust chain (v0.1):

1. **Who authenticates the initiating caller.** The transport front (A9)
   authenticates the agent/demo host at its edge (e.g. an HTTP bearer at the
   Streamable HTTP boundary). The Gateway does not mint caller identity.
2. **Where actor identity is derived.** From the *trusted* transport/auth
   context only — the same discipline as `default_actor_resolution()` /
   `default_sdk_actor_resolution()`: claims are hashed into scoped refs. Never
   from tool arguments.
3. **Where Bossy JWT credentials originate.** The caller (agent/demo host)
   presents a Bossy-issued JWT. The Gateway carries it as an opaque credential
   toward the remote connector; it never places it on a receipt and never mints
   or substitutes one.
4. **How organization authority reaches `bossy-mcp`.** Through the connector
   forwarding the caller's JWT to `bossy-mcp` (e.g. as the HTTP `Authorization`
   header on the Streamable HTTP call), so Bossy applies its own RLS/org
   authority server-side. DAGR does not implement or replace Bossy authority.
5. **Why tool arguments cannot override it.** Actor/tenant/authority are
   resolved from trusted context before the tool name and arguments are even
   forwarded; the request DTO's actor/tenant fields are documentation of the
   resolved value, not an input the caller can set (§3.3).
6. **How DAGR policy authority stays distinct from Bossy RLS authority.** DAGR
   decides *admission* (admit/refuse/defer) at its boundary via the neutral
   core and policy profile; Bossy decides *data-row authorization* inside
   `bossy-mcp` via RLS. They are independent controls at different layers.

**Double-control claim — conditional.** The claim that a call is subject to
*both* DAGR admission control and Bossy RLS control holds **only if** the
selected Bossy operation is proven to preserve the caller's JWT/RLS through the
complete remote execution path (caller → Gateway → connector → `bossy-mcp` →
row authorization). Until that end-to-end proof exists (a named A9/demo
acceptance test), the double-control claim is marked **unproven** and must not be
asserted as established.

---

## 9. Receipt and verification topology

- **Admission durability before forwarding.** For write/destructive tool classes
  the neutral core requires the admission record to be durably observed before
  execution (`ADMISSION_BEFORE_EXECUTION_REQUIRED`), and for reads it is the
  default (`emit_read_admission_before_execution=True`). The Gateway must
  therefore durably accept the admission receipt (or fail closed per class)
  *before* the connector forwards a governed-class call.
- **Outcome receipts.** Written after the remote call returns/raises/cancels,
  each referencing its admission receipt (`admission_receipt_ref`). Cardinality
  follows `RECEIPT_CARDINALITY` (admitted → 2, refused/deferred → 1).
- **How the response references receipts.** The response returns receipt
  *handles* (ids and/or a location handle), not inline signer material (§4).
- **Handles vs inline receipts.** Default to **handles**; returning inline
  receipt envelopes is an optional, opt-in mode (they are refs-and-hashes only
  and safe to return, but larger). The demonstrator retrieves receipts by
  reading the configured sink (files today) using the returned handles.
- **Why ARCS is asynchronous and out of path.** ARCS verifies signed receipts
  after emission; it is never called during the request. The Gateway's only
  obligation is durable emission. Verification independence is preserved.
- **Custody association.** An optional `MCPRecordCustodyGateway` projection
  associates the logical call (`logical_call_id`, boundary type, receipt
  family, refs) with the emitted receipts, carrying refs and hashes only.
- **Retention and privacy.** Receipts are `retention_class_applied = "hash_only"`
  and exclude raw arguments/results (`enforce_raw_content_exclusion`). Raw
  arguments transit to the remote server only for forwarding and are never
  persisted on a receipt.

No public receipt-subscription endpoint is invented; none exists, and the
demonstrator consumes receipts from the sink by handle.

---

## 10. Failure matrix

`fc` = fail-closed, `fo` = fail-open. "Remote executes?" is whether the tool
body on `bossy-mcp` runs.

| Failure state | Remote executes? | Response class | Receipt cardinality | Retry posture | Operator visibility | Posture |
|---|---|---|---|---|---|---|
| Malformed request | No | refused (`malformed_request`) | 0 | fix & resubmit | diagnostic | fc |
| Missing trusted actor | No | refused | 0–1 | re-auth | diagnostic | fc |
| Missing tenant context | No | refused (when tenant required) | 0–1 | re-auth | diagnostic | fc |
| Unknown binding | No | refused (`unknown_binding`) | 0 | fix config | diagnostic | fc |
| Binding unavailable | No | refused (`binding_unavailable`) | 0 | install extra | diagnostic | fc |
| Policy refusal | No | refused (ground verbatim) | 1 | per policy | admission receipt | fc |
| Deferred review | No | deferred | 1 (+review ref) | `retry_after_approval` | admission receipt | fc |
| Review-object creation failure | No | refused (`review_object_creation_failed`) | 1 | operator | admission receipt + telemetry | fc |
| Required receipt sink unavailable | No (governed classes) | refused (`required_sink_unavailable`) | 0–1 best effort | operator | telemetry/spool | fc |
| Remote MCP server unavailable | No | admitted-then-failed / `remote_unavailable` | admission (1); outcome per §11 **open** | bounded retry (idempotency-gated) | telemetry | fc |
| Remote timeout | Unknown | `exception` (subsumed §14) | 2 | see §11 **open** | telemetry | fc |
| Remote cancellation | Unknown | indeterminate (3 Booleans) | 2 | indeterminate | telemetry | fc |
| Malformed remote MCP result | Yes | `result`/`error` digest fails → outcome-emission failure path | admission (1) + best-effort outcome | none | telemetry | fo for read result return |
| Receipt emission failure after remote execution | Yes | business result returned; `alert_and_return_result` | 1 (admission) + gap telemetry | operator | telemetry/spool | fo (post-exec) |
| Duplicate/retried request | Possibly (no dedup today) | depends | fresh receipts each attempt | **open** (§11) | telemetry | **undecided** |
| Unsupported task/input-required state | No (SDK task); n/a | `unsupported_lifecycle_state` | 0 | none | diagnostic | fc |

Unresolved policy questions (remote-unavailable outcome cardinality, retry
posture, duplicate handling) are **not decided here**; they are carried openly
into §11.

---

## 11. Idempotency and retry ledger (open questions preserved)

The repository has **no idempotency mechanism today** (§2.12). The following
remain explicitly **open** and must be ratified before any exactly-once claim:

- **Durable execution artifact shape** — what durable record (if any) marks
  "this logical call has begun/completed." Candidates: (a) reuse the admission
  receipt id as the execution marker; (b) a separate execution-ledger row. No
  ledger exists today.
- **Canonical idempotency key** — candidates: caller request id; or a digest
  over `(binding, target, tool_name, argument_digest, actor_ref, tenant_ref)`.
  Consequence: a caller-supplied key trusts the caller; a derived key changes
  when any governed input changes.
- **Retry deduplication** — needs the key above plus a durable seen-set with a
  TTL. Consequence: without durability, dedup is best-effort and resets on
  restart.
- **Response replay** — returning the prior response for a duplicate key
  requires persisting responses (or at least receipt handles), which the current
  refs-only posture does not do.
- **Sink backpressure** — a slow/unavailable sink under load either blocks
  (fail-closed latency) or spools (`emergency_spool_path`) and alerts; no queue
  exists.
- **Partial execution followed by receipt failure** — the remote tool ran but
  the outcome receipt could not be written. Today the post-execution policy is
  `alert_and_return_result` (fail-open) with gap telemetry; a stricter mode is
  possible but unbuilt.

**No exactly-once execution is claimed.** Without a durable execution guarantee,
the Gateway offers at-most-once *admission* (fail-closed before governed
execution) and best-effort outcome recording, not exactly-once *execution*.

---

## 12. Security and privacy

- **Refs-only request posture.** The request carries argument digests/references
  wherever possible; raw arguments that must reach the remote server are held
  transiently for forwarding only and never placed on a receipt.
- **Argument canonicalization/digesting.** `sha256:` over the RFC 8785 (JCS)
  canonical form, identical to `sha256_digest` / `fastmcp_tool_result_digest`,
  so digests match across bindings.
- **Secret exclusion.** `enforce_raw_content_exclusion` (`RAW_KEYS`,
  `PRIVATE_MARKERS`) already refuses credential and raw-content keys on any
  receipt; the Gateway relies on it and never widens it.
- **Credential custody.** The caller's Bossy JWT is opaque to DAGR, forwarded to
  the remote server, never logged, never persisted, never receipted.
- **Tenant isolation.** Tenant/workspace are scoped hashes derived from trusted
  claims; no cross-tenant default.
- **SSRF / remote-server allowlisting.** The `target MCP server reference` is an
  operator-allowlisted *handle*, not an arbitrary URL from the model or caller.
- **Outbound host restrictions.** The connector may reach only allowlisted
  hosts; everything else is refused before any connection.
- **Remote server identity pinning.** For Streamable HTTP, the remote server's
  TLS identity/host is pinned per allowlist entry.
- **Signer separation.** The signing key never leaves `SigningIdentity`; it is
  not returned, logged, or persisted (`RawEnvelopeFileSink` stores public/hash
  material only).
- **Log redaction.** Diagnostics are stable content-free codes
  (`classified_failure`); raw exceptions and payloads are not logged.
- **No service-role fallback.** There is no ambient service credential that
  substitutes for a missing caller credential; a missing/invalid caller
  credential refuses.

---

## 13. Proposed package shape

Recommended (narrowest, repository-conventional) — a new sibling package
matching the existing `dagr_mcp_lifecycle` / `dagr_mcp_sdk_binding` convention,
already covered by the `include = ["dagr_mcp*"]` discovery glob:

```
dagr_mcp_service/
  __init__.py        # BINDING-free metadata; PEP 562 lazy submodules; no transport at import
  contract.py        # GovernedCallRequest / GovernedCallResponse DTOs + validation (A7)
  resolution.py      # binding selector: config key -> registered binding (A7/A8)
  adapter.py         # execute_governed_call orchestration over a selected binding (A8)
  connectors/        # client-side forwarders (A9) — one module per transport, optional deps
    memory.py        # in-process (tests)
    stdio.py         # stdio client connector
    http.py          # Streamable HTTP client connector
  access.py          # receipt-handle / composition seam (A10)
```

Conceptual interfaces only (no implementation this sprint):

```
# contract.py
class GovernedCallRequest:   ...   # §3.2 fields, refs-only
class GovernedCallResponse:  ...   # §4 five/six-part separation

# resolution.py
def select_binding(config, key) -> BindingHandle: ...   # fail-closed on unknown/unavailable

# adapter.py
async def execute_governed_call(request) -> GovernedCallResponse: ...

# connectors/base.py
class RemoteToolConnector(Protocol):
    async def call_tool(self, tool_name, arguments, *, trusted_context) -> Any: ...
```

The package plan must preserve:

- **`dagr_mcp_lifecycle` independence** — the service imports the core; the core
  never imports the service.
- **Both existing binding public surfaces** — reused unchanged; not rewired.
- **A1/A4/A5 behavioral freezes** — no change to
  `dagr_mcp.srs_receipts.REGISTERED_BINDING_VERSIONS`, the binding masks, the
  emitted receipt bytes, or the public API snapshots.
- **Explicit optional dependencies** — transport libraries go in new
  `[project.optional-dependencies]` extras (e.g. `service-http`), never in base
  deps.
- **No import-time transport startup** — importing `dagr_mcp_service` (or the
  core) must not import `mcp`/`fastmcp`/an HTTP stack or bind a socket, exactly
  as the two binding packages already guarantee via PEP 562 lazy submodules.

---

## 14. Test and conformance plan (future implementation)

- **Neutral request validation** — well-formed/malformed `GovernedCallRequest`;
  authority-smuggling fields ignored/refused.
- **Binding selection** — known key → correct binding; unknown → `unknown_binding`;
  unavailable extra → `binding_unavailable`; no silent substitution.
- **Both bindings** — parity of admission/outcome across
  `fastmcp.middleware.v0.1` and `official-mcp-sdk.python.v0.1` for the same
  neutral request.
- **Real remote MCP transport** — end-to-end against a fixture MCP server over
  the selected transport (in-memory first, then the ratified remote transport).
- **Lifecycle classes** — admitted/refused/deferred/error/exception/cancellation,
  and `task_submitted`/`input_required` fail-closed per binding capability.
- **Sink failure** — required-sink-unavailable (fail-closed pre-exec) and
  post-execution emission failure (`alert_and_return_result`).
- **Retries** — behavior under duplicate requests once §11 is ratified.
- **Authority smuggling** — caller-supplied actor/tenant/role/policy/binding
  stamp cannot influence the resolved decision.
- **Bossy caller-JWT propagation** — the named acceptance test that makes the
  §8 double-control claim provable (JWT/RLS preserved to `bossy-mcp`).
- **Receipt handles** — response carries handles that resolve to the emitted
  receipts; no signer/key/path leakage.
- **ARCS out-of-path verification** — emitted receipts verify with `arcs-verify`
  after the fact, with no ARCS call during the request.
- **Clean-wheel service smoke** — install the built wheel with only the declared
  extras and exercise `execute_governed_call` in-process.
- **Cross-binding parity** — extend the existing cross-binding conformance
  corpus to the service seam.

---

## 15. Implementation work packages

Each work package is a small PR. Sequencing follows the byte inventory: the
missing pieces are the request/response contract, the binding selector, the
in-process orchestration, and — net-new — the client-side connector.

### A7 — Contract and models only
- **Repository:** `dagr-mcp`.
- **Artifact:** `dagr_mcp_service/contract.py` (+ `resolution.py` selector
  types), no transport, no execution.
- **Prerequisites:** this document (A6) ratified.
- **Acceptance tests:** request validation; authority-field rejection; selector
  key → binding identity; fail-closed unknown/unavailable.
- **Prohibited scope:** no connector, no transport, no receipt emission.

### A8 — In-process adapter
- **Repository:** `dagr-mcp`.
- **Artifact:** `dagr_mcp_service/adapter.py` (`execute_governed_call`) over a
  selected binding using shape A / in-process connector; `connectors/memory.py`.
- **Prerequisites:** A7.
- **Acceptance tests:** admitted/refused/deferred/error/exception/cancellation
  end-to-end in-process; receipt cardinality; handles in the response; both
  bindings.
- **Prohibited scope:** no network transport; no remote host; no idempotency
  ledger.

### A9 — One selected remote transport (client connector)
- **Repository:** `dagr-mcp`.
- **Artifact:** the ratified connector (recommended: `connectors/http.py`
  Streamable HTTP; `connectors/stdio.py` optional) behind a new optional extra;
  no import-time startup.
- **Prerequisites:** A8; §7 transport ratified; §12 allowlist/pinning design.
- **Acceptance tests:** real remote MCP call to a fixture server; SSRF/allowlist
  refusal; cancellation/timeout propagation; retry-duplication behavior per the
  §11 ratification.
- **Prohibited scope:** no `bossy-mcp`-specific code; no ARCS in path.

### A10 — Receipt-access / composition seam
- **Repository:** `dagr-mcp`.
- **Artifact:** `dagr_mcp_service/access.py` — resolve returned receipt handles
  to receipts from the configured sink; optional inline-receipt mode; custody
  association.
- **Prerequisites:** A8 (and A9 for remote handles).
- **Acceptance tests:** handle → receipt round-trip; no signer/key/path leakage;
  ARCS-verifiable output.
- **Prohibited scope:** no subscription endpoint; no new receipt family.

### Demo-repo integration (afterward, separate repository)
- **Repository:** the demonstrator/demo host (not `dagr-mcp`, not `bossy-mcp`).
- **Artifact:** wiring the agent/demo host to `execute_governed_call`, pointing
  the connector at a real `bossy-mcp`, and running the §8 JWT-propagation proof.
- **Prerequisites:** A9, A10; a running `bossy-mcp`.
- **Acceptance tests:** the double-control acceptance test (§8); ARCS verifies
  emitted receipts independently.
- **Prohibited scope:** no DAGR code added to `bossy-mcp`.

---

## 16. Definition of done for the scoping sprint

This sprint is done when, and only when, all of the following hold — all are met
by this document:

- [x] **Byte-grounded inventory** — §2, every named symbol verified against the
  base commit.
- [x] **Explicit proven-empty service finding** — Executive finding + §2.11 +
  §2.13: no production service adapter, no transport, no forwarding, no
  idempotency.
- [x] **Defined conceptual request/response contracts** — §3 (request), §4
  (response), with the naming caveat flagged.
- [x] **Binding-resolution posture** — §5, including capability differences and
  fail-closed behavior.
- [x] **Transport recommendation** — §7 (in-memory for tests, Streamable HTTP
  for the demonstrator, stdio retained), left as a ratification decision.
- [x] **Authority map** — §8, with the double-control claim marked conditional.
- [x] **Failure matrix** — §10, with unresolved questions deferred to §11.
- [x] **Idempotency / open-question ledger** — §11, no exactly-once claim.
- [x] **Implementation PR sequence** — §15 (A7 → A8 → A9 → A10 → demo).
- [x] **No production implementation** — this PR is documentation-only.

### Verification performed for this PR

- Documentation links (§ cross-references) resolve to existing files in `docs/`.
- Every existing symbol named in §2 was read from current bytes at base
  `9874486e36dbe543dab903e2de7df46ec60004bb`.
- No Python source, schema, receipt profile, CI, dependency, or public API is
  changed; the diff is documentation-only (this single new file).
- The public-release scan (`tools/check_public_release.py`) remains clean.
- Repository tests are unchanged; running them is unaffected by this file.
