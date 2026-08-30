# DAGR-MCP-APPS0 — binding result

## Terminal

`NOT_SUPPORTED_BY_CURRENT_BINDING`

`AUTHORITY_MOVEMENT=0`

## Exact current-byte finding

The current Official MCP SDK v2 DAGR binding is intentionally built on the low-level `mcp.server.Server` and protocol `2026-07-28`.

`docs/DAGR_MCP_SDK_V2_BINDING.md` and `dagr_mcp_sdk_v2/server.py` both explicitly state that this binding:

- uses `Server(..., on_call_tool=..., on_list_tools=...)`;
- never uses the high-level `MCPServer` layer;
- serves the modern stateless protocol path with no `initialize` handshake and no `Mcp-Session-Id`;
- exposes `tools/list` by returning the registered `mcp_types.Tool` definitions;
- governs only the existing `tools/call` dispatch through `SdkV2LifecycleAdapter`.

The studied MCP Apps specimen (`espirado/mcp-resources-apps-demo`) depends on the high-level Apps extension surface: `Apps()`, `MCPServer(..., extensions=[apps])`, an advertised `io.modelcontextprotocol/ui` capability, `ui://` resources, and app-only tool visibility.

The required capability-advertisement contract therefore does not exist on this binding. Preserving a tool `_meta` field alone would not constitute MCP Apps support because the extension capability/resource host contract is absent.

## Why this is a STOP rather than an adapter patch

Adding `MCPServer`/Apps to `dagr-mcp-sdk-v2` would change the binding construction model and protocol surface that current bytes deliberately freeze. That is not a metadata-preservation repair and cannot be justified by this interoperability lane.

This result does **not** say DAGR can never govern MCP Apps. It says the current `official-mcp-sdk.python.v0.2` binding is not the owner surface on which to claim full Apps support.

A future Apps integration, if desired, needs a separately scoped binding/composition decision that explicitly owns the high-level MCP Apps protocol surface and then reuses the neutral DAGR lifecycle rather than modifying this frozen binding by stealth.

## Non-claims

- no new DAGR binding is created here;
- no receipt profile changes;
- no SRS vNext semantics consumed from PR #81;
- no assertion that Apps UI metadata is authority;
- no claim that low-level Tool `_meta` transport equals Apps capability support.

## Result

Recon completed. Construction is stopped on the current binding by design.