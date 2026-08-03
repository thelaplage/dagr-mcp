---
id: CLOSE_MEMO_gateway_stdio_child_connector_AUG03
title: Gateway lane close memo -- generic governed stdio child-process connector v0.1
date: 2026-08-03
classification: Internal / Feature / Lane Close
status: Draft
---

## Scope

This lane implements a second client-side Gateway connector,
`dagr_mcp_service.connectors.stdio`, named optionally in
`docs/GATEWAY_SERVICE_ADAPTER_SCOPE.md` §13's proposed package shape
(`connectors/stdio.py`, alongside `connectors/http.py`) but left unbuilt when
A9 shipped only the Streamable HTTP remote connector (PR #17). It governs an
**unmodified, arbitrary external MCP server binary** launched as an
operator-configured child process, speaking the standard MCP stdio
`initialize` / `tools/list` / `tools/call` lifecycle to it as a client,
through the same pinned `mcp==1.29.0` client transport the remote connector
already uses (`mcp.client.stdio`, `mcp.client.session.ClientSession`). It
imports and forks nothing from the child server's own implementation.

It is generic dagr-mcp transport/binding work: no product-specific names,
policies, schemas, paths, or assumptions appear anywhere in the new code.

It does not add a new lifecycle binding, a new receipt family, or any change
to `dagr_mcp_service.contract`, `dagr_mcp_service.adapter`,
`dagr_mcp_lifecycle`, or either existing binding (`fastmcp.middleware.v0.1`,
`official-mcp-sdk.python.v0.1`). Like the memory (A8) and remote (A9)
connectors before it, it plugs into the existing, frozen
`connector.resolve(target_handle, tool_name)` seam unmodified.

- **Base SHA:** `653946d60c6f34625008992c80daadceb5a58652`
  (`feat: add executable governed-memory vertical demo (#25)`)
- **Branch:** `feat/stdio-child-connector-v0-1`

## Files changed

New:

- `dagr_mcp_service/connectors/stdio.py` -- `StdioToolConnector`,
  `StdioTargetConfig`, `StdioTargetResolutionRefused`,
  `StdioTargetResolutionFailureReason`, `StdioToolHandler`,
  `discover_tools`.
- `tests/_stdio_fake_mcp_child.py` -- a well-behaved, real FastMCP stdio
  server fixture (`echo`, `boom`, `observed_cwd`, `observed_env` tools), run
  as an actual subprocess.
- `tests/_stdio_raw_fake_mcp_child.py` -- a hand-rolled, dependency-free
  (no `mcp` import) JSON-RPC stdio child that deterministically misbehaves
  in a selectable way (`normal`, `bad_protocol_version`, `hang_on_call`,
  `crash_after_accept`, `close_after_accept`, `malformed_call_response`,
  `noisy_stderr`, and the three `side_effect_then_*` modes that perform a
  real, durable side effect before failing), for exercising failure postures
  the pinned SDK's own server cannot be made to produce. It also records the
  JSON-RPC method order and side effects to operator-named files, so method
  sequencing and forwarded-exactly-once are proven from the child's own
  observations rather than the client's.
- `tests/test_gateway_service_stdio_connector.py` -- 69 tests, unit-level
  coverage of the connector module itself (construction/validation,
  `resolve()` no-I/O discipline, real child-process round trips, argument
  forwarding, environment scoping, tool discovery, failure-cause
  translation, process cleanup/orphan prevention, concurrency isolation,
  import purity).
- `tests/test_gateway_service_stdio_integration.py` -- 30 tests, the
  connector driven end to end through `execute_governed_call`, parametrized
  across both bindings where applicable (admitted-exactly-once,
  refused/deferred-never-reach-child, mutated-evidence-fails-verification,
  no-raw-content-in-receipts, deterministic failure postures composing
  correctly as `disposition="admitted", outcome="exception"` rather than
  being conflated with a policy refusal).

Modified:

- `dagr_mcp_service/connectors/__init__.py` -- added `stdio` to the lazy
  PEP 562 submodule set (`_LAZY_SUBMODULES`, `__all__`), updated the module
  docstring. `memory` and `remote` are unaffected.
- `docs/GATEWAY_SERVICE_ADAPTER_SCOPE.md` -- added a dated update note under
  the existing historical-record banner; no historical section rewritten.
- `docs/PRODUCT_ARCHITECTURE.md` -- "Service and connector composition"
  section now names the stdio connector.
- `CHANGELOG.md` -- one `### Added` entry under `[0.1.0] - Unreleased`.

No other file changed. `pyproject.toml` is untouched: `mcp==1.29.0` was
already declared under the `official-sdk` extra, and `mcp.client.stdio` is
part of that same package -- no new dependency, no new extra.

## Design decisions

**Command allowlist boundary.** `StdioTargetConfig.command` is a fixed,
operator-authored argv tuple; `StdioToolConnector.targets` is the closed
registry keyed by `target_server_ref.handle` (identical allowlist shape to
the memory and remote connectors). On top of that, `command[0]` (the
executable) must be an absolute filesystem path -- never resolved against
`$PATH` at call time -- the stdio analogue of the remote connector's
construction-time scheme/host pinning. `command` is always passed as an
explicit argv list to the OS process launcher, never through a shell.

**Tool discovery is explicit, out-of-band, and never automatic.**
`StdioTargetConfig.known_tools` is a required, closed `frozenset[str]`;
`resolve()` performs a synchronous, zero-I/O two-level lookup (target
handle, then tool name against `known_tools`) and refuses an unknown tool
with `unknown_tool_fail_closed` before any process is ever spawned --
mirroring the memory connector's discipline rather than the remote
connector's forward-and-let-the-target-error posture, because stdio has no
per-call network round trip cheap enough to justify deferring the check.
`discover_tools(command, ...)` is the module's own explicit,
operator-invoked capability for populating `known_tools` from a real
child's own declared `tools/list` result ahead of time.

**No per-call trusted-context injection seam.** Unlike the remote
connector, `StdioToolConnector` defines no `bind_trusted_context`: per the
scope document's own comparison table, a stdio target's trusted-context
source (subprocess env / launch args) is fixed once, at
`StdioTargetConfig` construction, with no live per-call wire location (no
header, no query string) to inject a caller-specific credential into.
`execute_governed_call`'s `getattr(connector, "bind_trusted_context",
None)` probe is unaffected, exactly as it already is for the memory
connector.

**Environment scoping and disclosed secret-handling limits.** A target's
`env` is additive configuration merged over the SDK's own
`get_default_environment()` safe subset (`HOME`, `LOGNAME`, `PATH`,
`SHELL`, `TERM`, `USER` on POSIX) -- never this process's full
`os.environ`. Verified empirically
(`test_unrelated_parent_environment_variable_does_not_reach_the_child`): an
unrelated secret set in the parent test process's environment does not
reach the child. An operator's own declared `env` values may themselves be
secret; this module discloses (module docstring) that it cannot control
what the child process does with its own environment once launched, and
never digests, logs, or receipts an env value -- verified
(`test_no_raw_arguments_results_or_env_secrets_in_emitted_receipts`).

**Honest, closed failure-cause translation, empirically verified against
the installed `mcp==1.29.0` client, not assumed:**

1. `asyncio.CancelledError` -- passed through unchanged.
2. `OSError` at process spawn, **and only before the session is handed to
   its caller** (confirmed from the installed SDK's own `stdio_client`
   source: it catches exactly `OSError` around process creation) ->
   `ConnectionError`. Phase-gated by `post_forward`: once a `tools/call`
   could be on the wire this bucket is closed, so the one diagnostic that
   reads as "nothing ran" cannot cover a call that may have run. See
   "Post-forward outcome semantics" below.
3. An `McpError` with `error.code == 408` (the same transport-agnostic
   `BaseSession.send_request` timeout code the remote connector already
   reuses) or a plain `TimeoutError` -> `TimeoutError`.
4. Everything else -- confirmed empirically to include a child that exits
   mid-call (the SDK's own receive loop fails every in-flight request with
   a distinct `CONNECTION_CLOSED` `McpError` the moment the read stream
   ends; deliberately **not** promoted to `ConnectionError`, since the
   child did start and "unavailable" would overclaim), a malformed
   JSON-RPC line from the child (silently dropped by the SDK's own
   parser -- confirmed the default `ClientSession` message handler is a
   no-op for a parse-error `Exception`, so a malformed response manifests
   as a bounded timeout rather than an immediate distinct failure; the
   fixture and test document this precisely rather than asserting a wrong
   claim), and the SDK's own `RuntimeError("Unsupported protocol version
   ...")` from `ClientSession.initialize()` for a protocol-version
   mismatch -- collapsed into one generic `RuntimeError`.

**Process cleanup and orphan prevention** rely entirely on the pinned
SDK's own `stdio_client` teardown (`start_new_session=True` process-group
placement, stdin-close-then-grace-period-then-`killpg`
SIGTERM/SIGKILL-escalation via `_terminate_process_tree`), unmodified by
this module. Verified with dedicated PID-liveness tests
(`test_no_orphan_process_remains_after_a_normal_call` /
`..._after_a_timeout` / `..._after_cancellation`) rather than assumed.

**stderr never corrupts the stdout JSON-RPC channel** -- structurally true
of `mcp.client.stdio` already (independent OS file descriptors), and each
call additionally redirects the child's stderr to a private per-call
*anonymous* temporary file (never the parent's own stderr, never an
undrained pipe) that has no filesystem name to leak on any exit path, and is
never read into an exception,
log, or receipt.

## Scope of the public claim

The connector ships as a **generic governed one-shot/restart-safe stdio MCP
connector v0.1**. "Generic" is bounded to the *child binary* (any unmodified
external MCP server speaking stdio), not to MCP server topologies. Because
every governed call is an independent spawn -> `initialize` -> one
`tools/list` or `tools/call` -> teardown cycle, the following are
**unsupported in v0.1 and recorded as future scope, not as defects hidden
behind the word "generic"**:

- long-lived session state held across governed calls;
- server subscriptions / server-push streams that must outlive a call;
- persistent server-side resources (open handles, caches, loaded models);
- cross-call initialization state;
- sampling roots, elicitation, or other negotiated state retained across
  calls.

Such a server still runs, but each call sees a freshly initialized process.
A persistent-child connector is a distinct future lane.

## Post-forward outcome semantics (adjudicated)

The pivotal boundary is whether `tools/call` was written to the child's
stdin. Admission is decided and the admission receipt emitted **before** any
child is spawned, so a REFUSED or DEFERRED call reaches the child **zero
times** (the connector handler is never invoked at all). An ADMITTED call is
forwarded **exactly once** -- one spawn, one `tools/call`, no retry layer.

| Failure mode | Child received call? | Side effect possible? | Execution/outcome receipt | Response vocabulary |
| --- | --- | --- | --- | --- |
| Spawn failure (pre-forward) | no | **no** | admission + outcome | `admitted` / `exception`, `remote_unavailable` |
| Timeout after forwarding | yes | **unknown** | admission + outcome | `admitted` / `exception`, `remote_exception` |
| Cancellation after forwarding | yes | **unknown** | admission + outcome | `admitted` / `cancellation`, `cancelled` |
| Child exit after forwarding | yes | **unknown** | admission + outcome | `admitted` / `exception`, `remote_exception` |
| Malformed response after forwarding | yes | **unknown** | admission + outcome | `admitted` / `exception`, `remote_exception` |
| Connection close after forwarding | yes | **unknown** | admission + outcome | `admitted` / `exception`, `remote_exception` |

No new receipt field and no new disposition was introduced. Cancellation is
the one post-forward mode with a *dedicated* indeterminacy representation in
the existing vocabulary: `CancellationFacts(request_cancelled=True,
execution_state_unknown=True, delivery_incomplete=True)`.

The other four post-forward modes have only `exception`, so this is stated
explicitly:

> **`outcome="exception"` means the transport or tool result was not
> successfully observed. It does not prove the side effect did not occur.**

**Hardening applied in this pass.** `_translate_stdio_failure` gained a
`post_forward` phase gate. `ConnectionError` is the only exception type the
A8 adapter narrows to `remote_unavailable` -- the one diagnostic readable as
"the call never reached the target" -- and it is now structurally
unreachable once `_stdio_session` has yielded. Previously an `OSError`
raised after forwarding could have reached that bucket. The gate is
one-directional: it can only move a classification *away* from claiming
non-execution.

Tests that make the distinction undeniable
(`side_effect_then_hang` / `_crash` / `_close` fixture modes have the child
perform a **real, durable, externally observable side effect** and *then*
fail):

- `test_a_forwarded_call_whose_side_effect_really_happened_is_never_reported_as_prevented`
  (E2E, both bindings x 3 modes) -- side-effect log proves the work happened;
  response is `admitted`/`exception`/`remote_exception`, never
  `remote_unavailable`, never `refused`.
- `test_cancellation_after_forwarding_records_execution_state_unknown`
  (both bindings) -- cancels only after the side effect has provably
  occurred; asserts `execution_state_unknown is True`.
- `test_remote_unavailable_is_reachable_only_from_the_pre_spawn_path` --
  the pre/post contrast that gives the diagnostic its meaning.
- `test_post_forward_oserror_is_never_a_connection_error`,
  `test_post_forward_gate_never_suppresses_cancellation_or_timeout`,
  `test_a_real_side_effect_that_is_never_observed_is_not_reported_as_unavailable`
  (unit).

## Protocol and discovery record

- Installed SDK: **`mcp==1.29.0`** (pinned; already declared under the
  `official-sdk` extra -- no new dependency).
- `mcp.shared.version.LATEST_PROTOCOL_VERSION` = `2025-11-25`;
  `SUPPORTED_PROTOCOL_VERSIONS` = `["2024-11-05", "2025-03-26",
  "2025-06-18", "2025-11-25"]`. Pinned by
  `test_installed_mcp_sdk_version_and_protocol_versions_are_as_recorded`, so
  a drift fails rather than silently invalidating this record.
- `initialize` strictly precedes any list/call, and the side-effecting
  `tools/call` is written exactly once --
  `test_initialize_precedes_the_call_and_the_call_is_sent_exactly_once`
  (method-order log written by the child itself).
- **Recorded honestly rather than wished away:** the pinned SDK's
  `ClientSession.call_tool` issues a *follow-up* `tools/list` of its own
  (`_validate_tool_result` refreshes its output-schema cache). That round
  trip is read-only, occurs strictly *after* the `tools/call` response is
  received, never re-sends the call, and never feeds `resolve()`. The
  "forwarded exactly once" claim is about the side-effecting `tools/call`,
  which it remains.
- Unsupported negotiated protocol fails closed --
  `test_bad_protocol_version_raises_generic_runtime_error` (the fixture's
  `1999-01-01` is asserted to be genuinely outside the supported set).
- `tools/list` names are discovery output, **not** admitted capability --
  `test_discovery_output_is_not_automatically_admitted_capability`: the child
  really declares `raw-echo`, the operator's `known_tools` omits it,
  resolution still refuses with `unknown_tool_fail_closed` and emits not one
  additional byte of protocol traffic.
- Unknown tools never spawn the child --
  `test_unknown_tool_refuses_before_any_child_process_exists`.

## Command and environment boundary (re-reviewed)

| Requirement | Status | Evidence |
| --- | --- | --- |
| Executable explicit and allowlisted | met | `targets` registry is the closed set; `test_resolve_unknown_target_handle_refuses_with_remote_unavailable` |
| No shell interpolation | met | argv list to the OS launcher; `test_no_shell_interpretation_surface_on_the_module` |
| No ambient `$PATH` search | met | `command[0]` must be absolute; `test_a_bare_name_that_really_exists_on_path_is_still_rejected` (**new** -- a name `$PATH` *would* resolve is still rejected) |
| argv immutable / operator-authored | met | frozen dataclass + tuple-only; `test_command_must_be_a_tuple_not_a_mutable_sequence`, `test_config_is_frozen_so_argv_cannot_be_swapped_after_validation` (**new**) |
| cwd explicit | met | `test_explicit_cwd_is_honored_by_the_child` (**new**, via an `observed_cwd` tool on the real child) |
| Inherited environment closed/minimal | met | SDK `get_default_environment()` subset; `test_unrelated_parent_environment_variable_does_not_reach_the_child` |
| Secrets absent from receipts/logs/exceptions | met | `test_no_raw_arguments_results_or_env_secrets_in_emitted_receipts`; `test_no_env_value_or_command_path_appears_in_a_raised_exception` (**new**) |
| stderr never corrupts stdout JSON-RPC | met | `test_a_chatty_stderr_child_never_corrupts_the_stdout_jsonrpc_channel` (**new**, ~160KB of stderr before and during the call) |
| Temporary stderr artifact removed on every exit path | met, **hardened** | see below |

**Temporary stderr sink -- defect found and fixed in this pass.** The
original implementation used `tempfile.mkstemp` plus an `os.unlink` in a
`finally`. Under the async-generator teardown path, the generator could be
suspended and finalized late by the garbage collector, leaving a *stray
named file* observable on disk after the call had returned (reproduced as an
intermittent test failure, ~1 run in 5). It now uses an **anonymous**
`tempfile.TemporaryFile`, which is unlinked at creation: there is no name
that could be observed and no unlink that could be skipped, on any exit
path. Regression tests
(`test_temporary_stderr_file_is_deleted_on_the_success_path` /
`..._spawn_failure_path` / `..._timeout_path` / `..._cancellation_path`) pin
`tempfile.tempdir` to a private per-test directory and assert **no named
entry of any kind** survives -- deliberately unfiltered, so the probe cannot
pass vacuously.

## Test results

All runs below use `set -o pipefail` so a recorded status reflects the real
command, not a trailing `tail`.

```
tests/test_gateway_service_stdio_connector.py
tests/test_gateway_service_stdio_integration.py     99 passed          (exit 0)
```

Zero skips in the focused suites: the independent-verifier tests run, they do
not silently opt out.

Full repository suite after this change: **1002 passed, 10 skipped**, zero
failures, zero regressions (exit 0).

Release gates:

- `tools/check_public_release.py .` -- `PASS: 0 finding(s)` (exit 0).
- `tools/check_core_extraction_manifest.py` -- `core extraction manifest OK:
  4 entries verified against fork_commit 4b30f9fd8b863b6909b0d83090a785811e32cd0e`
  (exit 0; this lane touches no file the manifest tracks).
- Import/lazy-loading: importing `dagr_mcp_service.connectors` eagerly
  imports none of `mcp`, `anyio`, `fastmcp`, `httpx`; lazy submodules are
  `['memory', 'remote', 'stdio']` (exit 0).

## Independent verification record (Gate 5)

The bundled/local mutation verifier alone does **not** satisfy the
emitter/verifier separation claim. This lane-close therefore ran the real,
separately built `arcs-verify` out of band, in its own interpreter, against
receipts emitted by the stdio connector.

| Field | Value |
| --- | --- |
| Verifier repository | `~/Developer/repos/arcs-verify` (`github.com/thelaplage/arcs-verify`) |
| Verifier commit | `e6d6eaca68b85428c1a8b7674a8cf4d6269952d6` |
| Verifier tree | `9dc06120de18b60898187062438def1bb896f374` |
| Verifier worktree state | clean (`git status --porcelain` empty) |
| Distribution | `arcs-verify 0.1.1` |
| Environment | a dedicated venv containing **only** `arcs-verify` and its deps (`cryptography`, `rfc8785`, `jsonschema`); no `dagr-mcp`, no `mcp`, no `fastmcp` |
| Command | `arcs-verify <receipt> --keyring <trust-bundle> --profile srs.mcp.sdk_enforcement.v0.1` |
| Profile | `srs.mcp.sdk_enforcement.v0.1` (matches the `profile_id`/`profile_version` the receipts themselves declare) |
| Schema | `arcs_verify/data/srs-envelope-v0.2.0.schema.json`, sha256 `d03aad1d5517e2acb65d5c866905aed7219bcbbfadd1a4a97eac546dd23f0333` |
| Trust inputs | `SigningIdentity.trust_bundle()` for `issuer:test:stdio-gateway`, key `issuer.test.stdio-gateway/key/1`, Ed25519 |
| Receipts under test | one `admission` + one `outcome`, emitted by `execute_governed_call` driving `StdioToolConnector` against the real child fixture |

Result:

```
unmodified admission receipt:  schema_digest/envelope/profile/raw_content_exclusion/
                               signature_valid/issuer_key_resolved/issuer_key_trusted/
                               attestation_limits_present = PASS    exit 0
unmodified outcome receipt:    (same, all PASS)                     exit 0
mutated receipt (logical_call_id changed, signature untouched):
                               signature_valid = FAIL
                               failure_code: signature_invalid      exit 1
```

Producer-import isolation, proven twice:

1. Out of band -- from a neutral working directory, the verifier venv's
   `sys.path` contains no repository entry and
   `find_spec` resolves none of `dagr_mcp`, `dagr_mcp_service`,
   `dagr_mcp_lifecycle`, `dagr_mcp_sdk_binding`, `mcp`, `fastmcp`. Running
   `arcs_verify.cli.main` in-process and then inspecting `sys.modules`
   yields `PRODUCER_MODULES_LOADED=[]`.
2. In the suite -- `test_importing_arcs_verify_does_not_import_dagr_mcp_producer_modules`
   spawns a fresh interpreter, imports `arcs_verify` and
   `arcs_verify.verifier`, and asserts no producer package appears in
   `sys.modules`.

In-suite verification (`test_stdio_receipts_verify_under_the_independent_arcs_verifier`,
both bindings) additionally proves each verifier dimension actually ran and
passed (rather than trusting `passed` alone), that a mutation fails
specifically as `signature_invalid`, and that the trust bundle is
load-bearing (a foreign issuer bundle rejects the same untouched receipt as
`key_id_unresolved`). `arcs-verify` is installed in this repository's dev
venv, so these tests **executed** this run -- they did not skip.

**Honest limits.** `arcs-verify` remains an `importorskip`-guarded
cross-check in CI, because it is a sibling project this repository does not
declare as a dependency. The out-of-band isolated-venv run above is what
substantiates the separation claim for *this* lane-close; the in-suite tests
are the ongoing regression guard. Verification checks the emitted
**evidence** (schema, profile, raw-content exclusion, signature, issuer
trust) -- never the truth of the real-world event a call may have caused.

## Documentation note

This repository has no `CLAIMS_LEDGER.md`; the equivalent role is played by
`CHANGELOG.md`, `docs/PRODUCT_ARCHITECTURE.md`,
`docs/GATEWAY_SERVICE_ADAPTER_SCOPE.md`'s dated update note, and this memo.
No ecosystem/capability-declaration file exists on this branch to update.
No product-specific (e.g. messaging-vendor) language appears anywhere in the
new code, tests, or documentation.

## Required-proof checklist

1. Deterministic fake stdio MCP child fixture -- `tests/_stdio_fake_mcp_child.py`
   (well-behaved) and `tests/_stdio_raw_fake_mcp_child.py` (deterministically
   misbehaving, selectable by mode).
2. ADMITTED call reaches child exactly once --
   `test_call_reaches_the_child_exactly_once` (unit),
   `test_admitted_call_is_forwarded_to_the_child_exactly_once` (E2E, both
   bindings), proven via an append-only call-log file the child writes.
3. REFUSED call produces evidence, reaches child zero times --
   `test_refused_call_produces_evidence_and_never_reaches_the_child` (both
   bindings): one admission receipt with `disposition="refused"`, no
   call-log file created.
4. DEFERRED call produces evidence, reaches child zero times --
   `test_deferred_call_produces_evidence_and_never_reaches_the_child` (both
   bindings): one admission receipt with `disposition="deferred_for_review"`,
   no call-log file created.
5. Mutation of emitted evidence fails independent verification --
   `test_mutated_receipt_fails_independent_verification_unmutated_passes`
   (CI-enforced, uses only the bundled schema and this repository's own
   test-only verifier): the genuine envelope verifies cleanly; a
   single-field mutation raises `cryptography.exceptions.InvalidSignature`.
   Independent verification against the real, separately-built `arcs-verify`
   is recorded in full under "Independent verification record (Gate 5)"
   above: an isolated-venv CLI run out of band, plus
   `test_stdio_receipts_verify_under_the_independent_arcs_verifier` and
   `test_importing_arcs_verify_does_not_import_dagr_mcp_producer_modules` in
   the suite (both executed, not skipped, this run).
6. Child timeout/crash/malformed-JSON tests -- covered in both the unit
   suite (`test_timeout_raises_builtin_timeout_error`,
   `test_child_exit_mid_call_raises_generic_runtime_error_...`,
   `test_malformed_response_never_returns_a_result_and_stays_bounded`) and
   the E2E suite (`test_child_timeout_is_an_admitted_exception_...`,
   `test_child_crash_mid_call_is_an_admitted_exception_...`), the latter
   proving the failure surfaces as `disposition="admitted",
   outcome="exception"` -- decision status recorded separately from
   execution/outcome status, never conflated with a policy refusal.
7. Tool discovery and argument-forwarding tests --
   `test_discover_tools_returns_the_childs_declared_tool_names`,
   `test_discover_tools_opens_and_closes_its_own_process`,
   `test_argument_values_forwarded_to_the_child_are_byte_exact` (non-ASCII
   content included).
8. No raw protected content under the selected profile --
   `test_no_raw_arguments_results_or_env_secrets_in_emitted_receipts`: a
   distinctive argument value and a distinctive operator-env secret value
   are both absent from every byte of every emitted receipt file.
9. Compatibility with the currently selected MCP SDK/version -- built and
   tested against the same pinned `mcp==1.29.0` the `official-sdk` extra
   already declares; no new dependency. Import-purity tests confirm `mcp`
   and `anyio` are never imported eagerly.
10. Architecture and claims ledger updates -- this memo,
    `docs/GATEWAY_SERVICE_ADAPTER_SCOPE.md`'s dated update note,
    `docs/PRODUCT_ARCHITECTURE.md`, `CHANGELOG.md`.

## What this lane does not claim

- No new lifecycle binding and no new binding-version identity are
  registered; `docs/BINDING_VERSIONS.md` is unchanged.
- No idempotency or retry framework, and no exactly-once *execution*
  guarantee -- identical posture to the remote connector (§11 of the scope
  document remains open and is not touched here). "Forwarded exactly once"
  is a claim about the `tools/call` this connector writes, not about how
  many times the external side effect took effect, which DAGR cannot
  observe.
- No claim that `outcome="exception"` means the side effect did not occur.
  It means the transport or tool result was not successfully observed. See
  "Post-forward outcome semantics" above.
- No claim that receipt verification establishes the truth of the
  real-world event. It establishes the integrity and provenance of the
  emitted evidence only.
- No support for long-lived session state, server subscriptions, persistent
  server-side resources, cross-call initialization state, or retained
  sampling roots -- see "Scope of the public claim" above.
- No long-lived child process across calls; each governed call is an
  independent spawn/negotiate/call/teardown cycle. A deployment that needs a
  persistent child (e.g. for expensive startup cost) is out of scope for
  this v0.1.
- No generic pluggable-transport framework -- one concrete stdio connector,
  matching the repository's existing "one concrete connector per transport"
  convention.
