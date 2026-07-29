# Binding Version Registry

Binding versions identify the emitter-owned integration surface that observed and receipted a call. They do not revise the SRS profile and MUST NOT be invented ad hoc at call sites.

| Value | Status | Meaning |
|---|---|---|
| `direct-harness.v0.1` | active | The synchronous direct harness included in `dagr-mcp`. |
| `fastmcp.middleware.v0.1` | active | The FastMCP middleware binding specified for WP4. |
| `official-mcp-sdk.python.v0.1` | active | The official Python MCP SDK (`mcp`) lowlevel-server binding added in Sprint A5 (`dagr_mcp_sdk_binding`), pinned to `mcp==1.29.0`. See [OFFICIAL_MCP_SDK_BINDING.md](OFFICIAL_MCP_SDK_BINDING.md). |
| `official-mcp-sdk.python.v0.2` | active | The official Python MCP SDK binding over protocol `2026-07-28` (`mcp==2.0.0`, `packages/dagr-mcp-sdk-v2`). Registered in `dagr_mcp_core.srs_receipts` (the [`dagr-mcp-core` extraction fork](CORE_EXTRACTION_FORK.md)'s own registry) — **not** in the root `dagr_mcp.srs_receipts` registry above, which is frozen legacy code. See [DAGR_MCP_SDK_V2_BINDING.md](DAGR_MCP_SDK_V2_BINDING.md). |

New values require a reviewed registry change before use. Existing values remain stable for receipt verification and migration.

The emitter accepts a binding version only if it is registered. The Sprint A1
freeze pins the original registry literal (`srs_receipts.REGISTERED_BINDING_VERSIONS`
= `direct-harness.v0.1`, `fastmcp.middleware.v0.1`) byte-for-byte; post-freeze
bindings are registered additively in `srs_receipts.ADDITIONAL_BINDING_VERSIONS`,
and the emitter gate consults `ALL_REGISTERED_BINDING_VERSIONS` (the union). The
receipt schema/profile version is unchanged across all bindings — only the
binding identity differs.

`official-mcp-sdk.python.v0.2` is a special case: it is registered only in the
`dagr-mcp-core` package's own, independently-forked `srs_receipts` module (see
[CORE_EXTRACTION_FORK.md](CORE_EXTRACTION_FORK.md)), not in the root package's
registry documented above. The root `dagr-mcp` distribution's registry is
unmodified by the v0.2 binding's introduction.
