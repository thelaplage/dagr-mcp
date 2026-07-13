# Official Python MCP SDK — lifecycle binding seam inventory (Sprint A5)

Status: **admitted**. A supported, public interception seam exists; no SDK
internals are monkeypatched. This document is the mandatory Phase 1 inventory
that gates the implementation. It records the exact installed SDK, the server
surfaces, the interception seam, how trusted context reaches a handler, how the
SDK represents each lifecycle state, and the in-process transport used by the
tests. The binding is implemented in the top-level package
[`dagr_mcp_sdk_binding`](../dagr_mcp_sdk_binding); the neutral core
(`dagr_mcp_lifecycle`) remains the single semantic authority.

The FastMCP binding (`fastmcp.middleware.v0.1`) is unchanged. A5 adds a **second**
binding; it does not replace FastMCP.

---

## 1. The exact installed official MCP SDK package

| Fact | Value |
| --- | --- |
| Distribution name | `mcp` (the official *Model Context Protocol* Python SDK) |
| Version proven | **1.28.1** |
| Import roots | `mcp`, `mcp.server.lowlevel`, `mcp.server.session`, `mcp.shared`, `mcp.types`, `mcp.server.auth` |
| Python supported by this repo | 3.11 / 3.12 / 3.13 (`requires-python = ">=3.11"`); proven on 3.13.4 |
| Direct vs transitive | Currently **transitive** through `fastmcp` (fastmcp depends on `mcp`). A5 imports it **directly**, so it is declared as an explicit **optional extra** pinned to the exact proven version — `official-sdk = ["mcp==1.28.1"]` — rather than relied on accidentally (see §8). |

`fastmcp_binding.py` already imports one symbol from the official SDK
(`mcp.types.CreateTaskResult`), so the official SDK is not new to the tree; A5
formalizes the dependency for the second binding.

---

## 2. SDK server surfaces

The canonical, protocol-level server is `mcp.server.lowlevel.Server`. (The SDK
also ships `mcp.server.fastmcp.FastMCP`, an ergonomic layer *over* the lowlevel
server; it is a different object from the standalone `fastmcp` PyPI package used
by the A4 binding. A5 binds the **lowlevel** server, the narrowest official
protocol surface.)

| Surface | Official SDK shape |
| --- | --- |
| `tools/list` | `@server.list_tools()` decorator registers a handler returning `list[mcp.types.Tool]`; the SDK caches them and answers `ListToolsRequest`. |
| `tools/call` | `@server.call_tool()` decorator registers `async def handler(name: str, arguments: dict)`; the SDK wraps it, validates input against `inputSchema`, normalizes the return, and answers `CallToolRequest`. |
| request context | `server.request_context` — a `contextvars`-backed `mcp.shared.context.RequestContext` carrying `request_id`, `meta`, `session`, `lifespan_context`, `experimental` (task metadata), `request` (transport request, e.g. the ASGI request for HTTP). Set by the SDK per request in `_handle_request`; raises `LookupError` outside a request. |
| cancellation | A client `CancelledNotification` cancels the in-flight request; the anyio cancel scope raises `anyio.get_cancelled_exc_class()` (under asyncio, `asyncio.CancelledError`) inside the handler. `CancelledError` derives from `BaseException`, so it **propagates past** the `call_tool` wrapper's `except Exception` and is handled in `_handle_request`. |
| returned tool content | Handler may return unstructured content (`list[ContentBlock]`), structured content (`dict`), a `(content, structured)` tuple, or a full `mcp.types.CallToolResult`. The wrapper builds a `CallToolResult(content, structuredContent, isError=False)`. |
| returned tool errors | A `CallToolResult` with `isError=True`. The wrapper also converts a raised (ordinary) `Exception` into `isError=True` via `_make_error_result(str(e))` (**it does not propagate**). Input/output-schema validation failures also become `isError=True` results. |
| raised exceptions | Ordinary `Exception` raised in the handler → converted to an `isError=True` result by the wrapper (see above). `BaseException` (e.g. `CancelledError`) propagates. |
| tasks / task-submitted | **Not carried by the bound `tools/call` seam.** The `mcp.types.CreateTaskResult` type exists, and the lowlevel `@server.call_tool()` handler does wrap a returned `CreateTaskResult` in a `ServerResult`. But the client seam this binding is exercised through — `mcp.client.session.ClientSession.call_tool` — hardcodes `result_type=CallToolResult` and validates the response against it; `CallToolResult.content` is **required** and a serialized `CreateTaskResult` carries none, so `CallToolResult.model_validate(response)` raises a pydantic `ValidationError` on the client. `CreateTaskResult` is genuinely received only through the **separate, deprecated** experimental tasks extension (`ClientSession.experimental.call_tool_as_task`, a *task-augmented* `CallToolRequest` parsed with `result_type=CreateTaskResult`). This binding therefore marks `task_submitted` **unsupported** and fails closed (`TaskSubmissionUnsupported`) on a returned `CreateTaskResult`; it never coerces it into `result_returned`/`error_returned`. See §6 and "tasks" below. |
| elicitation / input-required | Present: `mcp.types.ElicitRequest`/`ElicitResult` (session-driven `elicit`, resumable) and `mcp.shared.exceptions.UrlElicitationRequiredError` (URL elicitation → protocol error `-32042`, non-resumable in-band). See §6/§10. |

---

## 3. Narrowest public, supported interception seam

**Registering the call-tool handler** via the official `@server.call_tool()`
decorator (and `@server.list_tools()` for discovery). The DAGR binding registers
a governed handler that:

1. reads trusted request context from `server.request_context`;
2. runs the neutral lifecycle (admission → execute → outcome) around a
   **delegated** tool dispatch (a caller-supplied tool registry or call handler);
3. emits signed receipts through the existing `SignedReceiptEmitter`.

This is a first-class, documented public API — the intended extension point for
a protocol-level server. No private attribute, no `request_handlers`
mutation-by-hand, and no monkeypatch is used.

---

## 4. Is there a genuine middleware/interceptor API?

**No FastMCP-shaped middleware exists on the lowlevel server.** The lowlevel
`Server` has no `add_middleware`/`Middleware` concept; interception is done by
*being* the registered handler. (The SDK's own `mcp.server.fastmcp.FastMCP`
layer and the separate `fastmcp` PyPI package have their own middleware notions;
neither is assumed here.) A5 therefore does **not** assume FastMCP's middleware
shape — it uses handler registration, the official protocol-level seam.

---

## 5. How actor / tenant / auth / transport metadata reach a handler

Trusted context is **server/transport-supplied**, strictly separate from
model-supplied tool arguments:

- **Trusted:** `server.request_context` (`request_id`, `session`, `meta`,
  `lifespan_context`, `request`) and, when an auth transport middleware is
  installed, `mcp.server.auth.middleware.auth_context.get_access_token()` — a
  `contextvars`-backed `AccessToken` (fields `token`, `client_id`, `scopes`,
  `expires_at`, `resource`, `subject`, `claims`). This mirrors the FastMCP
  binding's `get_access_token()` seam.
- **Untrusted:** the `arguments: dict` handed to the call-tool handler is the
  model-supplied payload.

The DAGR actor/policy resolvers receive only the trusted `RequestContext` (and
the hash-only request snapshot), never a channel by which tool `arguments` could
define organization, tenant, actor, role, JWT, credentials, signing identity, or
receipt parentage. Authority fields appearing in `arguments` are ignored (§8 of
the sprint contract).

---

## 6. How the official SDK represents each lifecycle state

| Neutral state | Official SDK representation | Binding disposition (receipt profile token) |
| --- | --- | --- |
| successful result | `CallToolResult(isError=False)` (or content/dict/tuple normalized to it) | `result_returned` |
| tool-level error result | `CallToolResult(isError=True)` (incl. wrapper-converted exceptions and schema-validation failures) | `error_returned` |
| raised exception (observed by adapter) | The adapter catches the delegated tool's raised `Exception` **before** the SDK wrapper converts it, records `exception_class`, then lets the SDK project the transport error | `exception` |
| cancellation | `asyncio.CancelledError` / `anyio` cancelled (BaseException, propagates) | `indeterminate` (+ 3 governance Booleans) |
| timeout | A raised `TimeoutError` — an ordinary inner exception (no dedicated SDK timeout state) | `exception` (subsumed, `exception_class="TimeoutError"`, §14) |
| task-submitted | `CreateTaskResult` (only via the separate experimental tasks extension, not the bound `tools/call` client seam) | **unsupported** — fails closed, never coerced (see "tasks" below) |
| input-required / elicitation | `ElicitRequest`/`ElicitResult` (continuable) and `UrlElicitationRequiredError` (interrupted) | **unsupported** in both modes (§10) |

The receipt outcome tokens (`result_returned`, `error_returned`, `exception`,
`task_submitted`, `indeterminate`) belong to the **shared receipt profile**
`srs.mcp.sdk_enforcement/v0.1`, not to either binding — so both bindings project
neutral outcomes onto the *same* profile token set. Only the **binding-version
stamp** differs (see the mask, §"binding identity"). Which of those profile
tokens each binding actually *observes* is a separate matter: `task_submitted` is
a profile token the FastMCP binding stamps but this binding does **not** observe
(see "tasks").

### tasks — an explicit binding capability difference

`mcp.types.CreateTaskResult` is a real SDK type, but it is **not** a genuine
result of the `tools/call` client seam this binding binds:

- The lowlevel `Server.call_tool` handler wraps a returned `CreateTaskResult` in
  `ServerResult(CreateTaskResult)`.
- But `ClientSession.call_tool(...)` calls
  `send_request(..., result_type=types.CallToolResult)`, and `send_request`
  finishes with `CallToolResult.model_validate(response.result)`.
  `CallToolResult.content` is a **required** field; a serialized
  `CreateTaskResult` has no `content`, so the client raises a pydantic
  `ValidationError`. This was verified end-to-end over the real in-process
  transport.
- `CreateTaskResult` is genuinely received only through the **separate,
  deprecated** experimental tasks extension:
  `ClientSession.experimental.call_tool_as_task(...)` sends a *task-augmented*
  `CallToolRequest` (a `task` param on `CallToolRequestParams`) and parses the
  response with `result_type=CreateTaskResult`. The SDK itself deprecates this
  API for mcp 2.0 ("tasks (SEP-1686) were removed from the MCP specification and
  are expected to return as a separate MCP extension").

Accordingly, the A5 mask marks `task_submitted` **unsupported**
(`mask.BINDING_UNSUPPORTED_OUTCOME_TOKENS == {"task_submitted"}`) and the adapter
fails closed with `TaskSubmissionUnsupported` if a delegated tool returns a
`CreateTaskResult` — it never stamps a `task_submitted` receipt and never coerces
the value into `result_returned`/`error_returned`. The **FastMCP** binding's
`task_submitted` behavior is unchanged; the cross-binding corpus records this as
an explicit capability difference rather than normalizing it.

---

## 7. In-process transport for tools/list + tools/call

Yes. `mcp.shared.memory.create_connected_server_and_client_session(server, ...)`
connects a real `mcp.client.session.ClientSession` to the real lowlevel `Server`
over in-memory anyio object streams — exercising `initialize`, `tools/list`, and
`tools/call` with **no** stdio, SSE, Streamable HTTP, or ASGI transport. A5's
execution tests drive the live adapter through this in-process client. The smoke
was proven during this inventory (list → `["echo"]`, call → `isError=False`).

---

## 8. Dependency status and declaration

The repository reaches `mcp` only transitively through `fastmcp` today. Because
A5 imports it **directly**, `pyproject.toml` declares an explicit optional extra,
**pinned to the exact version proven** by this inventory, the dedicated CI
official-SDK lane, and the clean-wheel official-SDK smoke:

```toml
[project.optional-dependencies]
official-sdk = ["mcp==1.28.1"]
```

This keeps the base install unchanged (FastMCP remains the default binding) and
avoids depending on a transitive version *accidentally*. The extra is pinned to
`mcp==1.28.1` — the **only** SDK version exercised against this binding, its
mask, the real in-process `tools/list` + `tools/call` path, and the cross-binding
corpus — rather than advertising a broader range (e.g. `>=1.16,<2`) that no test
covers. A wider range is a future task that must first prove each claimed
compatibility boundary (earliest/maximum supported version) in a clean
environment with its own stable CI lane; until then the honest contract is the
single proven pin. The dedicated CI official-SDK lane installs this exact pin
(`mcp==1.28.1`). A wheel-metadata test
(`tests/test_official_sdk_dependency_metadata.py`) asserts the built wheel's
declared `official-sdk` requirement is exactly `mcp==1.28.1`, matching this
document and the CI lane. The binding imports the SDK lazily so that importing
package metadata or the neutral core never eagerly imports `mcp` or `fastmcp`.

---

## Binding identity

- Binding target / version stamp: **`official-mcp-sdk.python.v0.1`**
  (distinct from `fastmcp.middleware.v0.1`; never reused).
- Receipt schema/profile: **unchanged** — `srs.core.v5.1` /
  `srs.mcp.sdk_enforcement` / `v0.1`. Binding identity differs; schema semantics
  do not.
- Public seam used: `@server.call_tool()` + `@server.list_tools()` handler
  registration on `mcp.server.lowlevel.Server`.
- Supported lifecycle states: admitted, refused, deferred, result, error,
  exception, cancellation, timeout (subsumed → exception).
- Explicitly unsupported states: `task_submitted` (the `CreateTaskResult` type
  exists in `mcp.types` but is not a genuine result of the bound `tools/call`
  seam — see "tasks"); `input_required` (both `continuable` and `interrupted`
  modes) — each failed explicitly, never normalized (§10).
