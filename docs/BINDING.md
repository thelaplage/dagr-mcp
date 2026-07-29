# FastMCP Binding

`DAGRMiddleware` is the `fastmcp.middleware.v0.1` binding for FastMCP tool calls. It consumes the public signed receipt emitter and records admission and outcome receipts without changing the MCP protocol, FastMCP tool handlers, the frozen SRS profile, or the WP3 emitter contract.

> For the official MCP SDK bindings (not FastMCP), see
> [OFFICIAL_MCP_SDK_BINDING.md](OFFICIAL_MCP_SDK_BINDING.md) (`v0.1`, `mcp==1.29.0`)
> and [DAGR_MCP_SDK_V2_BINDING.md](DAGR_MCP_SDK_V2_BINDING.md) (`v0.2`,
> `mcp==2.0.0`, built on the [`dagr-mcp-core` extraction fork](CORE_EXTRACTION_FORK.md)).

## Middleware Order

Install DAGR once at the institutional trust boundary. In FastMCP order terms, add it before middleware whose behavior should be observed as part of the governed call.

Declared consequences:

- Refusals that happen before DAGR runs are not DAGR receipts.
- Cache hits returned by downstream middleware are receipted as `result_returned`; the receipt does not claim handler execution.
- Retry middleware downstream of DAGR collapses multiple handler attempts into one logical outcome receipt.
- Middleware upstream of DAGR is outside the observed boundary unless it emits its own independent evidence.

The default is one DAGR middleware at the outer institutional boundary. Do not install multiple DAGR instances around the same logical call unless the deployment intentionally records separate boundaries and links them with `parent_receipt_ref`.

## Admission

The binding snapshots the request, resolves the actor, resolves policy, and evaluates the disposition before calling the tool handler.

- `refused`: emits a terminal refused admission receipt and raises `ToolError("Call refused by admission policy")`.
- `deferred_for_review`: creates the durable review object first. If that fails, it emits a terminal refused admission receipt with `reason_code` set to `review_object_creation_failed` and no `review_object_ref`. If creation succeeds, it emits a deferred admission receipt with `review_object_ref` and `retry_contract` set to `retry_after_approval`, then raises `ToolError` carrying the public review reference. The request is not parked.
- `admitted`: emits an admission receipt before execution for `write` and `destructive` tool classes. Read tools default to the same behavior, with fail-open pre-execution receipt failure permitted by configuration.

Authenticated FastMCP token claims are projected to hash scoped actor references. Raw access tokens are never written to receipts, gap spools, or demo fixtures. STDIO and direct programmatic calls resolve to `actor:anonymous_or_local`.

## Outcomes

After `call_next`, the binding records the observed boundary result and returns the original FastMCP result unchanged.

- `ToolResult` and compatible tool result objects are projected through the four-member `fastmcp.tool_result.v1` projection: `content`, `structuredContent`, `_meta`, and `isError`.
- The projection is JCS canonicalized and hashed before the outcome receipt is emitted.
- `isError=True` becomes `error_returned`; otherwise the outcome is `result_returned`.
- `CreateTaskResult` becomes `task_submitted` and does not claim task execution or completion.
- `CancelledError` emits a best-effort `indeterminate` outcome with the constrained cancellation facts, then re-raises.
- Other exceptions emit an `exception` outcome with the exception class name only, then re-raise.

If an outcome receipt cannot be durably accepted after execution, the binding returns the actual result, leaves the admission receipt open, and writes a typed `receipt_gap` operational event through the independent emergency spool path when configured. It does not claim that an indeterminate or other outcome receipt exists unless the primary receipt sink accepted it.

## Mounted Servers

For mounted FastMCP servers, prefer DAGR on the parent boundary when the parent is the institutional trust boundary. Child middleware may still be useful for a second, narrower boundary, but it should use `parent_receipt_ref` and the same logical call reference so verifiers and operators can distinguish deliberate linked receipts from accidental duplicates.

Middleware state does not automatically cross FastMCP mount boundaries. If a mounted deployment needs shared actor or parent receipt state, pass it through explicit resolver configuration rather than relying on private FastMCP internals.

## Proxy Boundaries

For proxy or aggregator deployments, set a distinct `boundary_id`, set `parent_receipt_ref` when the upstream receipt is known, and add the proxy attestation limit:

`The receipt attests only to what crossed and returned through the proxy boundary.`

Proxy receipts attest to observations at the proxy boundary. They do not establish claims about hidden upstream execution unless linked upstream evidence exists.

## Attestation Limits

The frozen profile limits used by the emitter remain unchanged:

`The receipt attests only to governance conditions at the named admission boundary.`

`The receipt establishes the request, admission disposition, and semantic result returned at the configured boundary. It does not independently establish that the underlying tool body executed for this invocation, because middleware such as caches may satisfy a call without handler execution.`

`The receipt establishes admission and submission to the configured task backend. It does not establish execution or completion.`
