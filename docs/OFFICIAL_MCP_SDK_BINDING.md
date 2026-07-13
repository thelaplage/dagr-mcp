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
| Direct vs transitive | Currently **transitive** through `fastmcp` (fastmcp depends on `mcp`). A5 imports it **directly**, so it is declared as an explicit, bounded **optional extra** `official-sdk = ["mcp>=1.16,<2"]` rather than relied on accidentally (see §8). |

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
| tasks / task-submitted | `@server.call_tool()` accepts a returned `mcp.types.CreateTaskResult` (fields `meta`, `task`) and passes it through as task-submission. This is a **genuine** SDK shape (the same `CreateTaskResult` the A4 binding already recognizes). Note: the SDK marks the *experimental tasks API* deprecated for mcp 2.0, but the `CreateTaskResult` **type** and its pass-through in the call-tool wrapper are present and stable in 1.28.1. |
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
| task-submitted | `CreateTaskResult` | `task_submitted` |
| input-required / elicitation | `ElicitRequest`/`ElicitResult` (continuable) and `UrlElicitationRequiredError` (interrupted) | **unsupported** in both modes (§10) |

The receipt outcome tokens (`result_returned`, `error_returned`, `exception`,
`task_submitted`, `indeterminate`) belong to the **shared receipt profile**
`srs.mcp.sdk_enforcement/v0.1`, not to either binding — so both bindings project
neutral outcomes onto the *same* profile tokens. Only the **binding-version
stamp** differs (see the mask, §"binding identity").

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
A5 imports it **directly**, `pyproject.toml` declares an explicit, bounded
optional extra:

```toml
[project.optional-dependencies]
official-sdk = ["mcp>=1.16,<2"]
```

This keeps the base install unchanged (FastMCP remains the default binding),
avoids depending on a transitive version *accidentally*, and lets the CI
official-SDK lane pin the **exact proven constraint `mcp==1.28.1`**. The binding
imports the SDK lazily so that importing package metadata or the neutral core
never eagerly imports `mcp` or `fastmcp`.

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
  exception, task_submitted, cancellation, timeout (subsumed → exception).
- Explicitly unsupported states: `input_required` (both `continuable` and
  `interrupted` modes) — failed explicitly, never normalized (§10).
