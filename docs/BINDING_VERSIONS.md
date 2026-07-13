# Binding Version Registry

Binding versions identify the emitter-owned integration surface that observed and receipted a call. They do not revise the SRS profile and MUST NOT be invented ad hoc at call sites.

| Value | Status | Meaning |
|---|---|---|
| `direct-harness.v0.1` | active | The synchronous direct harness included in `dagr-mcp`. |
| `fastmcp.middleware.v0.1` | active | The FastMCP middleware binding specified for WP4. |
| `official-mcp-sdk.python.v0.1` | active | The official Python MCP SDK (`mcp`) lowlevel-server binding added in Sprint A5 (`dagr_mcp_sdk_binding`). See [OFFICIAL_MCP_SDK_BINDING.md](OFFICIAL_MCP_SDK_BINDING.md). |

New values require a reviewed registry change before use. Existing values remain stable for receipt verification and migration.

The emitter accepts a binding version only if it is registered. The Sprint A1
freeze pins the original registry literal (`srs_receipts.REGISTERED_BINDING_VERSIONS`
= `direct-harness.v0.1`, `fastmcp.middleware.v0.1`) byte-for-byte; post-freeze
bindings are registered additively in `srs_receipts.ADDITIONAL_BINDING_VERSIONS`,
and the emitter gate consults `ALL_REGISTERED_BINDING_VERSIONS` (the union). The
receipt schema/profile version is unchanged across all bindings — only the
binding identity differs.
