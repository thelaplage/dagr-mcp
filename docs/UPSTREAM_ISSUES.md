# Draft FastMCP Upstream Issues

These are draft issue notes only. They are not filed from this work package. Filing waits for the external-maintainer integration path so DAGR integrates through public FastMCP contracts rather than adapting private internals.

## 1. Stable Task Result Import Path

FastMCP 3.4.4 returns `mcp.types.CreateTaskResult` for task-submitted calls. FastMCP main may expose the same public concept from `mcp_types.CreateTaskResult`.

Request: document and stabilize the import path or provide a FastMCP-owned re-export for middleware authors.

## 2. Public Tool Resolution Observation

Admission middleware can observe the requested tool name before resolution, but there is no public hook to observe the resolved tool identity or a bounded resolution failure after admission without relying on private provider details.

Request: expose a public resolution observation object for `on_call_tool`.

## 3. Outcome Shape Contract for Middleware

Middleware receives `ToolResult`, task results, or exceptions depending on the execution path. The exact result and error shape is documented across several pages rather than as one middleware contract.

Request: publish a concise `on_call_tool` result contract covering `ToolResult`, protocol error results, `ToolError`, and task-submitted results.

## 4. Request and Session Reference Access

The documented `fastmcp_context.request_id` and `session_id` fields are useful for scoped evidence, but availability varies by transport and lifecycle phase.

Request: document stable request and session reference semantics for middleware, including direct programmatic calls and STDIO.

## 5. Auth Claim Projection Guidance

`get_access_token()` is public, but guidance for middleware that needs claims without retaining raw bearer tokens is not centralized.

Request: document a claims-only pattern and clarify which token fields are safe to project into audit references.

## 6. Mounted Server State Handoff

FastMCP documents that middleware state does not automatically cross mount boundaries. Evidence middleware needs an explicit way to hand off parent boundary references to child boundaries.

Request: provide a public, request-scoped state handoff example for mounted servers.

## 7. Middleware Interaction With Cache and Retry Middleware

Cache and retry middleware can be deliberately placed downstream of evidence middleware, but the observable consequences are left to each integration.

Request: document standard examples for cache hits, retries, and middleware-returned results so audit middleware can state its claims precisely.
