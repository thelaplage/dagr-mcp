---
id: CLOSE_MEMO_gateway_a9_remote_connector_JUL19
title: Gateway lane close memo -- A9 client-side remote MCP connector
date: 2026-07-21
classification: Internal / Feature / Lane Close
status: Draft
---

## Scope

This lane implements work package A9 of the DAGR Gateway Service Adapter, as
scoped in `docs/GATEWAY_SERVICE_ADAPTER_SCOPE.md` (§7, §8, §12, §13, §15) and
gated on A8 (PR #16, `dagr_mcp_service.adapter` / `dagr_mcp_service.
connectors.memory`, base `b71e1f845ed14ad7ee4315a6132c517324c3bdb2`). It adds
one client-side connector, `dagr_mcp_service.connectors.remote`, that reaches
a genuinely remote, operator-allowlisted MCP server over the pinned
`mcp==1.28.1` client's Streamable HTTP transport, plus two narrow additive
changes to `dagr_mcp_service.adapter` that let it compose with the frozen A8
seam. It does not add A10 (the receipt-handle content/access seam), a public
Gateway host, inbound JWT parsing, Bossy-specific code, or any retry/replay/
idempotency behavior.

- **Base SHA:** `694da62aad12648702e3306fe7125e4dbb43b28d` (A8, PR #16)
- **Branch:** `feat/gateway-remote-connector-v0-1`
- **Final head SHA:** recorded at commit time below (see `git log -1`).

## Files changed

New:

- `dagr_mcp_service/connectors/remote.py` -- `RemoteToolConnector`,
  `RemoteTargetConfig`, `TrustedOutboundContext`, `RemoteCredential`,
  `RemoteCredentialProvider`, `RemoteTargetResolutionRefused`,
  `RemoteToolHandler`.
- `tests/_gateway_service_remote_fixtures.py` -- shared `loopback_mcp_server`
  pytest fixture: a real FastMCP `http_app()` server run over `uvicorn` in a
  background thread bound to an OS-assigned `127.0.0.1` port, with four test
  tools (`echo`, `boom`, `slow`, `observed_headers`).
- `tests/test_gateway_service_remote_connector.py` -- 54 tests, unit-level
  coverage of the connector module itself.
- `tests/test_gateway_service_remote_integration.py` -- 33 tests, the
  connector driven end to end through `execute_governed_call`, parametrized
  across both bindings where applicable.

Modified:

- `dagr_mcp_service/connectors/__init__.py` -- added `remote` to the lazy
  PEP 562 submodule set (`_LAZY_SUBMODULES`, `__all__`), updated the module
  docstring. `memory` is unaffected.
- `dagr_mcp_service/adapter.py` -- two narrow, additive changes (see
  "Adapter changes" below). No change to `GatewayAdapterConfig`'s field set,
  `_CapturingSink`, receipt-capture ordering, or either binding's own
  execution path.

No other file changed. `pyproject.toml` is untouched: `mcp==1.28.1` was
already declared under the `official-sdk` extra (A5), and `httpx` is already
present transitively (via `fastmcp`) in every environment this repository's
test/build tooling uses -- confirmed by `pip show httpx` inside the
project's `.venv` before writing any code, and by the clean-wheel smoke
below succeeding with `pip install dagr_mcp-0.1.0-py3-none-any.whl[official-sdk]
uvicorn` alone.

## Adapter changes

Both changes are additive and inert for the existing memory connector.

1. **`bind_trusted_context` rebinding hook.** After `config.connector.
   resolve(target_handle, tool_name)` returns a callable,
   `execute_governed_call` now does
   `getattr(config.connector, "bind_trusted_context", None)` and, only if
   non-`None`, calls it with the resolved handler plus the request's
   already-resolved `target_handle`, `tool_name`, `actor_ref`, `tenant_ref`,
   `parent_receipt_ref`, and `request_ref`, using its return value in place
   of the original handler. `connector.resolve(target_handle, tool_name)`
   itself is unchanged -- still exactly two positional arguments, matching
   `InMemoryToolConnector.resolve`'s frozen A8 signature
   (`test_resolve_signature_matches_the_frozen_a8_connector_seam`).
   `InMemoryToolConnector` defines no `bind_trusted_context`, so this is a
   no-op for every A8 deployment/test
   (`test_memory_connector_is_unaffected_by_the_a9_bind_trusted_context_hook`).
2. **`ConnectionError` -> `remote_unavailable` diagnostic.** `_classify`'s
   `disposition == "admitted"` branch now checks
   `isinstance(raised, ConnectionError)`: true -> `diagnostic_code=
   "remote_unavailable"`; false (including every other exception type, as
   before) -> `diagnostic_code="remote_exception"`, unchanged. The memory
   connector never raises `ConnectionError`, so this branch's behavior for
   A8 is unchanged (proven by the unmodified A8 suite still passing
   byte-for-byte, 55/55).

Neither change alters `GatewayAdapterConfig`'s fields, receipt-capture
ordering, or either binding's own admission/execution/outcome path.

## Remote client and transport

The pinned `mcp==1.28.1` client's Streamable HTTP transport
(`mcp.client.streamable_http.streamable_http_client` +
`mcp.client.session.ClientSession`) is the only transport implemented. No
stdio, WebSocket, SSE, or generic pluggable-transport abstraction exists
(`test_no_stdio_websocket_sse_subprocess_or_generic_transport_surface_on_the_module`).
One `ClientSession.call_tool` per invocation of a resolved handler; no
reconnect, backoff, or dedup key.

## Endpoint, redirect, and proxy posture (SSRF discipline)

- **No caller-suppliable connection facts.** `GovernedCallRequest` carries
  only `target_server_ref.handle`; every URL, scheme, host, port, path,
  timeout, redirect policy, and credential-provider binding lives in
  operator-authored `RemoteTargetConfig`, keyed by handle in
  `RemoteToolConnector`'s registry. No tool argument or request field can
  supply any of these.
- **Validation at construction time, not call time.**
  `RemoteTargetConfig.__post_init__` requires `https` unless the operator
  sets `allow_insecure_loopback=True` for a `127.0.0.1`/`localhost`/`::1`
  `http` target; rejects URL userinfo and a fragment outright; a config that
  fails these checks cannot be constructed, so it can never enter a
  connector's registry or open a socket
  (`test_unsupported_scheme_opens_no_socket`,
  `test_http_to_a_non_loopback_host_is_rejected_even_with_the_loopback_flag`,
  `test_url_userinfo_is_rejected`, `test_url_fragment_is_rejected`).
- **Unknown handle / unsupported scheme opens no connection.**
  `RemoteToolConnector.resolve` is a plain dict lookup with no I/O
  (`test_resolve_known_target_returns_a_callable_and_opens_no_socket_by_itself`,
  `test_resolve_unknown_target_handle_opens_no_socket`); at the adapter
  layer, `test_unknown_target_handle_refuses_and_opens_no_socket` proves the
  same through `execute_governed_call`.
- **Redirects.** `allow_redirects` defaults to `False` (httpx never sends a
  second request without it). If an operator opts a target in, a request
  event hook (`_redirect_credential_guard`) strips every
  credential-provider-supplied header name whenever a redirect's resolved
  origin (scheme, hostname, port) differs from `endpoint_uri`'s origin --
  stricter than httpx's own cross-origin `Authorization`-only stripping,
  since it covers arbitrary operator-chosen header names
  (`test_redirect_guard_strips_credential_headers_on_cross_origin_redirect`,
  `test_redirect_guard_strips_credential_headers_on_cross_port_redirect`,
  `test_redirect_guard_leaves_same_origin_headers_untouched`).
- **Environment proxies.** The outbound `httpx.AsyncClient` always sets
  `trust_env=False`; `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` can never
  silently reroute a credentialed connection
  (`test_trust_env_is_always_false_even_without_redirects_or_credentials`).

## Trusted outbound-context provider and credential handling

- `TrustedOutboundContext` carries only already-resolved opaque refs
  (`target_handle`, `tool_name`, `actor_ref`, `tenant_ref`,
  `parent_receipt_ref`, `request_ref`) -- no raw tool arguments, no
  credential, no signing identity. It is delivered to a connector's
  operator-configured `credential_provider` only via the additive
  `bind_trusted_context` hook, never serialized to a header, URL, or tool
  argument by this module itself.
- **No ratified wire format.** This repository still ratifies no HTTP
  header name or JWT claim for `actor_ref`/`tenant_ref`, per the governing
  scope document's hard authority gate. A provider decides, out of band, how
  (or whether) to turn the trusted context into outbound credential
  material.
- **Credential lifetime.** A provider's `RemoteCredential.headers` is
  obtained immediately before the connection opens (`_resolve_credential_
  headers`, called at the top of `_call_remote_tool`), held only as a local
  variable, merged into a per-call `httpx.AsyncClient` that is never
  retained past that one call, and never logged, receipted, or returned.
  `test_credential_provider_headers_actually_reach_the_wire` proves the
  header actually reaches the remote tool over the real loopback server;
  `test_credentials_never_appear_in_response_or_receipts` proves a planted
  secret is absent from `repr(response)`, `repr(response.business_result)`,
  `repr(response.receipts)`, and every on-disk receipt envelope, across both
  bindings.
- **Provider failure opens no connection.** A raising `credential_provider`
  propagates before `_call_remote_tool` imports `httpx`/`mcp.client` or
  constructs a socket (`test_credential_provider_failure_opens_no_connection_
  and_is_not_connection_error`, socket.socket monkeypatched to raise). It is
  never wrapped as `ConnectionError` (that would falsely claim a remote
  contact attempt); it surfaces through the existing, unmodified A8 generic
  exception path as `diagnostic_code="remote_exception"`, never
  `remote_unavailable`
  (`test_credential_provider_failure_is_admitted_exception_not_remote_
  unavailable`).
- **Caller arguments cannot supply credentials or headers.**
  `test_transient_arguments_cannot_reassert_actor_tenant_or_credentials`
  plants decoy `actor_ref`/`tenant_ref`/`Authorization`/`credential` keys in
  the transient tool-argument mapping and proves the provider only ever
  sees the request's real, already-resolved `actor_ref`/`tenant_ref`, and
  the wire header is the operator-issued one, never the decoy.
- **Concurrent calls cannot mix credentials.** Two targets with distinct
  providers, called concurrently via `asyncio.gather` at both the
  connector level (`test_concurrent_calls_do_not_mix_credentials_arguments_
  or_results`) and through `execute_governed_call`
  (`test_concurrent_governed_calls_do_not_mix_credentials_or_results`,
  both bindings), each observe only their own header on the wire. No
  per-call mutable state is stored on the connector instance -- each
  `resolve`/`bind_trusted_context` call closes a fresh local closure over
  its own `target`/`context`.

## No side effects before admission

Verified for both bindings via `monkeypatch.setattr(socket, "socket",
_forbidden)` (any attempted socket construction raises `AssertionError`),
each proving zero credential-provider calls and zero sockets:

- unknown target handle -- `test_unknown_target_handle_refuses_and_opens_no_socket`
- digest mismatch -- `test_digest_mismatch_performs_no_credential_lookup_or_network_operation`
  (also asserts `provider_calls == []`)
- unknown binding -- `test_unknown_binding_opens_no_socket`
- unavailable binding -- `test_unavailable_binding_opens_no_socket`
- policy refusal -- `test_policy_refusal_opens_no_remote_connection` (both bindings)
- unsupported/rejected endpoint config -- `test_unsupported_scheme_opens_no_socket`
  (construction itself fails before a `RemoteTargetConfig` can exist)

Ordering is structural, not just tested: `RemoteToolConnector.resolve` is a
dict lookup, and `bind_trusted_context` only builds a closure -- neither
imports `httpx`/`mcp.client` or touches the network. The credential provider
call and socket construction happen exclusively inside `_call_remote_tool`,
which is reachable only through the handler closure invoked as `call_next`
(FastMCP)/`delegate` (SDK) -- both bindings' own frozen, unmodified admission
path calls that seam strictly after the admission receipt write succeeds
(A1/A4/A5 behavior, not touched by this lane). A required admission-sink
failure therefore also precedes any connector code running, inherited
unmodified from A8's own `_CapturingSink`/`write_failed` guard
(`tests/test_gateway_service_adapter.py::test_required_pre_execution_sink_
failure_prevents_execution`, unmodified by this lane, still passing).

## Execution uncertainty

`_translate_transport_failure` flattens the `BaseExceptionGroup` the pinned
`mcp` client wraps almost every failure in (confirmed empirically against
the installed `mcp==1.28.1`, not assumed), then classifies into four honest,
content-free buckets, in priority order:

1. `asyncio.CancelledError` -- passed through unwrapped.
2. `httpx.ConnectError` -- translated to plain `ConnectionError`: no
   socket-level connection was ever established
   (`diagnostic_code="remote_unavailable"` at the adapter layer).
3. An `McpError` with `error.code == 408` (the exact value `mcp.shared.
   session.BaseSession.send_request` stamps on its own read-timeout,
   confirmed by reading the pinned `mcp==1.28.1` source) or any
   `httpx.TimeoutException` -- translated to plain `TimeoutError`, which
   both existing bindings already special-case into their own honest
   "execution state unknown" timeout handling (§14 subsumption, unmodified).
4. Anything else -- generic `RuntimeError`
   (`diagnostic_code="remote_exception"`), no further cause claimed.

None of the four translated exceptions embeds the original message, host,
port, or credential
(`test_translated_exceptions_never_embed_the_original_message`). Remote
tool-level errors (`isError=True` results) are returned, not raised, and
stay structurally distinct from governance refusal
(`test_remote_tool_level_error_is_distinct_from_governance_refusal`, both
bindings: `disposition="admitted"`, `outcome="error"`, never
`disposition="refused"`). Cancellation mid-call propagates unwrapped and
both bindings' existing `except asyncio.CancelledError` handling records
`cancellation_facts` (`request_cancelled`, `execution_state_unknown`,
`delivery_incomplete`, all `True`) without fabricating a timeout or
remote-unavailable claim
(`test_cancellation_carries_grounded_cancellation_facts_over_the_remote_
connector`, both bindings). `test_exactly_one_remote_call_is_made_per_
governed_invocation` (both bindings) monkeypatches `_call_remote_tool` with
a call counter and proves exactly one call per `execute_governed_call`
invocation; `test_no_retry_idempotency_or_dedup_names_appear_on_the_remote_
connector_module` and `test_no_public_host_route_subprocess_or_queue_api_
exists_on_remote_module` prove no retry/replay/dedup/exactly-once surface
exists anywhere on the module.

## Connection cleanup

`_call_remote_tool` owns the `httpx.AsyncClient` in its own `async with`
block (constructed with `http_client=` passed to `streamable_http_client`,
which per the pinned `mcp==1.28.1` source only closes a client it created
itself -- a caller-passed client is otherwise leaked). This is the fix for
the real defect the prior session in this lane found and fixed: without
owning the client directly, `streamable_http_client` would never close it,
leaking one `httpx.AsyncClient`/connection pool per call.
`test_connection_closes_after_result_error_exception_and_cancellation`
spies on `httpx.AsyncClient.__aexit__` and proves `is_closed is True` after
every one of: a normal result, a tool-level error, a `ConnectionError`
(refused connection), a `TimeoutError`, and a cancelled in-flight call --
five sequential cases against the same connector instance, `closes ==
[True, True, True, True, True]`. Provider failure and malformed-response
cases are covered structurally: a failing credential provider raises before
`httpx.AsyncClient` is even constructed (nothing to leak), and a malformed
remote response is caught by the same generic `except BaseException`
`async with` block as any other protocol exception, so the same
`__aexit__`-runs-on-every-exit-path proof applies.

## Concurrent-call isolation

Proven at both the connector level (`test_concurrent_calls_do_not_mix_
credentials_arguments_or_results`) and through the full adapter
(`test_concurrent_governed_calls_do_not_mix_credentials_or_results`, both
bindings): two overlapping `asyncio.gather`'d calls to distinct targets with
distinct credential providers each observe only their own header, argument,
and result; `response_a.receipts != response_b.receipts`. No per-call
mutable state is stored on `RemoteToolConnector` -- `_targets` is populated
once at construction and never written to afterward; every call builds a
fresh local closure and a fresh `TrustedOutboundContext`.

## No-retry / no-idempotency posture

No retry, backoff, reconnect-and-replay, dedup key, or exactly-once claim
anywhere in `dagr_mcp_service.connectors.remote` or the two adapter changes.
One `ClientSession.call_tool` per resolved-handler invocation
(`test_exactly_one_remote_call_is_made_per_governed_invocation`, both
bindings); no name containing `idempot`/`dedup`/`exactly_once`/`replay`/
`retry` appears on the module's public surface
(`test_no_retry_idempotency_or_dedup_names_appear_on_the_remote_connector_
module`).

## Actor/tenant wire-format status

Unchanged from A8/scope §8: still no ratified HTTP header, JWT claim, or
other wire representation for `actor_ref`/`tenant_ref`. This lane proves
only that the trusted, already-resolved values reach the credential
provider seam intact (`test_bind_trusted_context_delivers_the_exact_
resolved_refs_to_the_provider`) and that whatever a provider derives from
them reaches the wire (`test_credential_provider_headers_actually_reach_
the_wire`) -- it does not claim, prove, or assert that any specific remote
server authenticates or understands the resulting header. The §8
double-control claim remains open, as it was after A8.

## Test results

```
$HOME/Developer/repos/dagr-mcp/.venv/bin/pytest tests/test_gateway_service_remote_connector.py -q
54 passed in 8.44s

$HOME/Developer/repos/dagr-mcp/.venv/bin/pytest tests/test_gateway_service_remote_integration.py -q
33 passed in 5.38s

$HOME/Developer/repos/dagr-mcp/.venv/bin/pytest tests/test_gateway_service_adapter.py tests/test_gateway_service_memory_connector.py -q
55 passed in 1.31s

$HOME/Developer/repos/dagr-mcp/.venv/bin/pytest tests/test_gateway_service_contract.py tests/test_gateway_service_resolution.py -q
73 passed in 0.67s

$HOME/Developer/repos/dagr-mcp/.venv/bin/pytest tests/test_fastmcp_binding.py tests/test_official_mcp_sdk_binding.py -q
50 passed in 2.00s

$HOME/Developer/repos/dagr-mcp/.venv/bin/pytest -q
743 passed, 2 skipped in 19.99s

$HOME/Developer/repos/dagr-mcp/.venv/bin/python tools/check_public_release.py .
PASS: 0 finding(s)

$HOME/Developer/repos/dagr-mcp/.venv/bin/pytest tests/test_no_private_import_roots.py -q
1 passed in 0.01s
```

743 passed / 2 skipped is exactly the A8 corrective-pass baseline (656
passed/2 skipped -- confirmed by rerunning the full suite with the two new
A9 test files excluded: `656 passed, 2 skipped`) plus this lane's 87 focused
tests (54 + 33), with no other file's collected test count changed; the
skip count (2) is unchanged from A8, so this lane introduces no new skip.

Wheel (`dagr_mcp-0.1.0-py3-none-any.whl`) and sdist
(`dagr_mcp-0.1.0.tar.gz`) both built via `python -m build` with no
`pyproject.toml` change. Wheel-content inspection (`unzip -l`) and sdist
inspection (`tar tzf`) both confirm `dagr_mcp_service/connectors/remote.py`
is present alongside the existing `dagr_mcp_service`/`.connectors` modules.

**Clean-wheel loopback smoke.** A fresh venv (no repository checkout on
`sys.path`) with `pip install dagr_mcp-0.1.0-py3-none-any.whl[official-sdk]
uvicorn` drove one admitted `execute_governed_call` through each binding
(`fastmcp.middleware.v0.1`, `official-mcp-sdk.python.v0.1`) against a real
loopback FastMCP `http_app()` server, asserting the packaged
`dagr_mcp_service.connectors.remote` module round-trips a result
end-to-end with only the installed wheel importable:

```
OK fastmcp.middleware.v0.1: GovernedDecision(disposition='admitted', outcome='result')
OK official-mcp-sdk.python.v0.1: GovernedDecision(disposition='admitted', outcome='result')
CLEAN WHEEL SMOKE: OK
```

`git diff --check` reported no whitespace errors. All build/cache artifacts
(`build/`, `dist/`, `*.egg-info`, `__pycache__/`, `.pyc`/`.pyo`,
`.pytest_cache/`) and the temporary clean-wheel venv were removed before
staging.

## Known FastMCP main-canary condition

Not investigated or fixed, per this lane's instructions. The known,
out-of-scope FastMCP main-prerelease canary condition
(`CREATE_TASK_RESULT_IMPORT_PATH` falling back to `mcp_types.
CreateTaskResult` when `mcp.types.CreateTaskResult` is unavailable) did not
manifest during this lane's verification runs; `mcp==1.28.1` (the pinned,
exercised version) was installed throughout, including in the clean-wheel
smoke venv.

## Explicit absences

- **No public Gateway host or production identity claim.** Nothing in this
  lane starts, binds, or exposes a server; `dagr_mcp_service.connectors.
  remote` is a client only. No ASGI/HTTP server framework name (`fastapi`,
  `starlette`, `flask`, `django`, `uvicorn`, `asgi`) appears anywhere in the
  module's code
  (`test_no_public_host_or_server_startup_surface_on_the_module`). The
  loopback server used by this lane's own tests exists solely inside
  `tests/_gateway_service_remote_fixtures.py`, a test-only fixture, never
  shipped or importable from the packaged `dagr_mcp_service` surface.
- **No inbound JWT parsing.** This module never parses, validates, or
  decodes a JWT or any other inbound credential; it only ever forwards
  whatever opaque `RemoteCredential.headers` an operator-configured provider
  returns, outbound.
- **No Bossy-specific code.** Nothing in `dagr_mcp_service.connectors.remote`
  or the two `dagr_mcp_service.adapter` changes names Bossy, RLS, or any
  Bossy-specific behavior.
- **No retry, replay, deduplication, idempotency, or exactly-once claim.**
  See "No-retry / no-idempotency posture" above.
- **No A10 receipt-content access.** This lane does not read, resolve, or
  expose receipt bytes/content by handle; `ReceiptHandle.location_handle`
  remains `None` in every response this lane produces, unchanged from A8.
- **No import-time transport.** Importing `dagr_mcp_service.connectors` or
  `dagr_mcp_service.connectors.remote` never imports `httpx` or
  `mcp.client.streamable_http`
  (`test_importing_the_connector_package_does_not_eagerly_import_the_
  remote_sdk_or_http_stack`,
  `test_importing_the_remote_module_itself_does_not_eagerly_import_the_
  http_stack`, both via a subprocess-isolated `sys.modules` check).

## A10 boundary

A10 (receipt-handle content/access seam) remains separately gated and
out of scope for this lane. `ReceiptHandle.location_handle` stays `None`
across every response class this lane produces, exactly as A8 left it; this
lane adds no mechanism to resolve a receipt handle to durable content.

## Independent adversarial review required

This lane has not undergone independent adversarial review. Per the
governing instructions for this lane, the PR opened from this branch is
kept as a draft and is not marked ready; independent review is required
before that status changes.
