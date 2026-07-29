# dagr-mcp-sdk-v2

The `official-mcp-sdk.python.v0.2` DAGR governed binding: a governed
`tools/call` handler composed around the official Python MCP SDK's low-level
`mcp.server.lowlevel.Server`, for protocol `2026-07-28` (`mcp==2.0.0`).

Built on [`dagr-mcp-core`](../dagr-mcp-core) — never on the root `dagr-mcp`
distribution or `fastmcp`. See
[`../../docs/DAGR_MCP_SDK_V2_BINDING.md`](../../docs/DAGR_MCP_SDK_V2_BINDING.md)
for the governed-handler contract, the frozen result-digest projection, and the
acceptance matrix, and
[`../../docs/CORE_EXTRACTION_FORK.md`](../../docs/CORE_EXTRACTION_FORK.md) for
how this binding relates to the `official-mcp-sdk.python.v0.1` binding
(`dagr_mcp_sdk_binding`, pinned to `mcp==1.29.0`, part of the frozen legacy
`dagr-mcp` distribution).

## Scope

Supports `tools/call` with `resultType: complete` only. Does not support MRTR
(`input_required`) — a delegate that returns `InputRequiredResult` is an
explicit, fail-closed binding capability difference (see the docs above), not
a supported outcome.

## Dependencies

`dagr-mcp-core`, `mcp==2.0.0` (exact pin). Never `fastmcp`, never `mcp<2`.

Do not install this package into the same environment as the root `dagr-mcp`
distribution or any `mcp<2`/`fastmcp` package — `mcp` 1.x and 2.x are not
designed to coexist.
