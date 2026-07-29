# Official Python MCP SDK v2 binding (`official-mcp-sdk.python.v0.2`)

The third DAGR lifecycle binding, and the first to speak protocol
`2026-07-28`. Built entirely on [`dagr-mcp-core`](CORE_EXTRACTION_FORK.md)
(never the frozen legacy `dagr-mcp` distribution, never `fastmcp`), against
the exact pin `mcp==2.0.0`.

Package: `packages/dagr-mcp-sdk-v2` (`dagr_mcp_sdk_v2` on the import path).

## 1. Exact stable SDK APIs used

* `mcp.server.lowlevel.Server` (also importable as `mcp.server.Server`),
  constructed with `on_call_tool=` / `on_list_tools=` constructor kwargs — the
  SDK's public, documented handler-composition surface. No decorator API, no
  monkeypatching.
* `Server.streamable_http_app(stateless_http=True, json_response=True, ...)` —
  the public builder for the Streamable HTTP ASGI app.
* `mcp.server.context.ServerRequestContext` — the per-request context type the
  handler receives. The adapter reads only `ctx.method` and `ctx.request_id`
  (via `getattr`) from it; it never reaches into transport/session internals.
* `mcp_types.CallToolRequestParams`, `mcp_types.CallToolResult`,
  `mcp_types.InputRequiredResult` — the SDK-facing request/result types.
* `mcp.shared.exceptions.MCPError` — the public seam for signaling a specific,
  message-carrying JSON-RPC error from a handler (see §4).

**Never used**: `mcp.server._streamable_http_modern` (private),
`handle_modern_request` (private), `fastmcp`, `mcp<2`.

## 2. The governed `tools/call` handler contract

See `dagr_mcp_sdk_v2/adapter.py:SdkV2LifecycleAdapter.governed_call_tool`. In
order:

1. Assert `ctx.method == "tools/call"`.
2. `tool_name = params.name`; `argument_digest = sha256_digest(params.arguments or {})`.
3. Resolve actor (trusted context only, never `params.arguments`) and the
   tool's governed class from `SdkV2BindingConfig.tool_classes` — a tool name
   absent from that mapping is an admission-time refusal
   (`unknown_tool_fail_closed`), never a delegate dispatch.
4. `plan_admission(...)` via `dagr_mcp_core.lifecycle.core`.
5. Emit the signed admission receipt via `dagr_mcp_core`'s
   `SignedReceiptEmitter` **before** any delegate call.
6. Refused (including an admission-sink failure under a fail-closed policy):
   delegate never runs; a `ToolRefused` (`MCPError`) is raised.
7. Admitted: invoke the delegate exactly once; classify the result through the
   frozen projection (§3); emit exactly one linked outcome receipt via
   `plan_outcome_strict`.
8. A delegate returning `InputRequiredResult`: fail closed (§4) — no outcome
   receipt is ever emitted for this event.

## 3. The frozen result-digest projection

`dagr_mcp_sdk_v2/result_digest.py:project_v2_tool_result`. Exactly five keys,
in this order, using the actual `CallToolResult` field names:

```
content, structured_content, _meta, is_error, result_type
```

Built from `CallToolResult.model_dump(mode="json", by_alias=True)`, so every
content block is fully normalized to plain JSON before RFC 8785
canonicalization — no transport-local object, Python repr, or memory address
can reach the digest. Golden vectors:
`packages/dagr-mcp-sdk-v2/tests/golden/result_digest_vectors.json`, verified
by `packages/dagr-mcp-sdk-v2/tests/test_result_digest_golden.py`. Regenerate
(only if the projection deliberately changes) with:

```bash
python3 - <<'PY'
import json
from mcp import types as mcp_types
from dagr_mcp_sdk_v2.result_digest import project_v2_tool_result
from dagr_mcp_core.srs_receipts import sha256_digest
# ... construct the same three CallToolResult cases as the test file and
# json.dump({"case": {"projection": ..., "digest": ...}, ...}, ...)
PY
```

## 4. MRTR / `input_required` scope

This binding supports `tools/call` with `resultType: complete` only. It does
**not** support MRTR. A delegate that returns `InputRequiredResult` triggers
`dagr_mcp_sdk_v2.adapter.InputRequiredUnsupported`, a subclass of
`mcp.shared.exceptions.MCPError`.

Raising `MCPError` (rather than returning an `isError` `CallToolResult`) is a
verified-safe, public seam on this SDK version: `handler_exception_to_error_data`
(`mcp/shared/jsonrpc_dispatcher.py`) maps an `MCPError` to *its own carried*
`ErrorData` — the exact message reaches the wire — whereas an arbitrary
non-`MCPError` exception collapses to a generic `"Internal server error"`
(`mcp/server/runner.py:modern_error_data`). So raising here yields the
"explicit supported diagnostic" the governed-handler contract requires,
verified empirically (not assumed) against the installed SDK before this
binding was written this way. `ToolRefused` (refusal) uses the same mechanism.

No outcome receipt is ever emitted for `input_required`: the neutral core's
`contract.UNSUPPORTED_OUTCOMES` already hard-stops this token, so
`plan_outcome_strict` raises `UnsupportedLifecycleEvent` rather than planning
any record — the adapter's guard around that call is a checked invariant, not
the mechanism that prevents the receipt.

## 5. Binding-version registration

`official-mcp-sdk.python.v0.2` is registered only in `dagr_mcp_core.srs_receipts.ADDITIONAL_BINDING_VERSIONS`
(the `dagr-mcp-core` fork's own copy of the registry) — **not** in the root
`dagr_mcp.srs_receipts` registry, which is unmodified. See
[BINDING_VERSIONS.md](BINDING_VERSIONS.md) and
[CORE_EXTRACTION_FORK.md](CORE_EXTRACTION_FORK.md).

## 6. Acceptance matrix

`packages/dagr-mcp-sdk-v2/tests/test_acceptance_matrix.py` covers all 10
required rows (admitted/success, refused, `is_error`, delegate-raises,
admission-sink-failure, outcome-sink-failure, `input_required`, unknown tool,
cancellation before delegate, cancellation during delegate), each asserting
delegate-invocation count and receipt cardinality mechanically. The
common-path rows run over the real stateless Streamable HTTP ASGI app (the
full `mcp==2.0.0` stack, via `packages/dagr-mcp-sdk-v2/tests/harness.py`); the
failure-injection rows call the adapter directly with a minimal duck-typed
context (the adapter only reads `ctx.method` / `ctx.request_id`).

## 7. Genuine stateless HTTP proof

`examples/http_proof_v2/server.py` + `client_proof.py` — a runnable,
self-contained example that spins up a real `uvicorn` server (an actual TCP
socket on `127.0.0.1`) and issues real `httpx` HTTP requests against it,
proving: protocol `2026-07-28`; no `initialize`; no
`notifications/initialized`; no `Mcp-Session-Id` request or response header;
valid `Mcp-Method`/`Mcp-Name` headers; modern request `_meta`; modern result
`resultType: complete`; admission-then-outcome receipt cardinality and
linkage; both receipts independently verified (`arcs-verify` if installed,
else the in-repo jsonschema+Ed25519 fallback, with the verifier actually used
printed explicitly); and a signed **semantic** mutation (flipping `outcome`
inside the signed envelope, never whitespace/key order) rejected by
verification, with the script exiting non-zero if that rejection does not
happen. Run:

```bash
pip install -e packages/dagr-mcp-core -e packages/dagr-mcp-sdk-v2
python examples/http_proof_v2/client_proof.py
```

`tests/test_http_proof_v2.py` is the CI-safe counterpart: identical app
construction, driven over `starlette.testclient.TestClient` (the real ASGI
app object and lifespan, no network port) so it is deterministic in CI. It
skips cleanly wherever `mcp==2.0.0` / `dagr-mcp-sdk-v2` are not installed.

## 8. Environment isolation

Do not install `dagr-mcp-sdk-v2` into the same environment as the root
`dagr-mcp` distribution, any `mcp<2`, or `fastmcp` — `mcp` 1.x and 2.x are not
designed to coexist. See the "Required environments" section of the task spec
and `docs/CORE_EXTRACTION_FORK.md`.
