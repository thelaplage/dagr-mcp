# DAGR-MCP-APPS0 — binding result

## Terminal

`NOT_SUPPORTED_BY_CURRENT_BINDING`

`AUTHORITY_MOVEMENT=0`

## Current-byte finding

The Official MCP SDK v2 DAGR binding on current `main` is intentionally built on the low-level `mcp.server.Server` and protocol `2026-07-28`.

`docs/DAGR_MCP_SDK_V2_BINDING.md` and `dagr_mcp_sdk_v2/server.py` explicitly state that this binding:

- uses `Server(..., on_call_tool=..., on_list_tools=...)`;
- never uses the high-level `MCPServer` layer;
- serves the modern stateless protocol path with no `initialize` handshake and no `Mcp-Session-Id`;
- exposes `tools/list` by returning the registered `mcp_types.Tool` definitions;
- governs only the existing `tools/call` dispatch through `SdkV2LifecycleAdapter`.

The studied MCP Apps specimen (`espirado/mcp-resources-apps-demo`) depends on the high-level Apps extension surface: `Apps()`, `MCPServer(..., extensions=[apps])`, an advertised `io.modelcontextprotocol/ui` capability, `ui://` resources, and app-only tool visibility.

The required capability-advertisement and resource-host contract therefore does not exist on this binding. Preserving generic Tool `_meta` fields alone would not constitute MCP Apps support.

## Post-#81 reconciliation

SRS-VNEXT-EMITTER0 (#81) is now landed on `main`. Its changed files are limited to the opt-in external-profile receipt emitter plus its tests and documentation. It does not modify `dagr_mcp_sdk_v2/server.py`, the low-level Server construction, resource hosting, Apps capability advertisement, or the no-handshake protocol path.

Therefore #81 does not alter this terminal finding. This recon consumes none of its profile/envelope semantics and makes no receipt-profile changes.

## Why this is a STOP rather than an adapter patch

Adding `MCPServer`/Apps to `dagr-mcp-sdk-v2` would change the binding construction model and protocol surface that current bytes deliberately freeze. That is not a metadata-preservation repair and cannot be justified by this interoperability lane.

This result does **not** say DAGR can never govern MCP Apps. It says the current `official-mcp-sdk.python.v0.2` binding is not the owner surface on which to claim full Apps support.

A future Apps integration, if desired, needs a separately scoped binding/composition decision that explicitly owns the high-level MCP Apps protocol surface and then reuses the neutral DAGR lifecycle rather than modifying this frozen binding by stealth.

## Non-claims

- no new DAGR binding is created here;
- no receipt profile changes;
- no SRS vNext semantics are imported into Apps handling;
- no assertion that Apps UI metadata is authority;
- no claim that low-level Tool `_meta` transport equals Apps capability support.

## Result

Recon completed and revalidated against current `main`. Construction is stopped on the current binding by design.
