# DAGR-MCP-APPS0 — recon

## External pattern studied

`espirado/mcp-resources-apps-demo` uses MCP Apps (`io.modelcontextprotocol/ui`) with a structured result tool bound to a `ui://` resource. Raw document/page access is separated into app-only read helpers; the ordinary semantic tool returns references rather than document bytes.

## DAGR adoption decision

This is a strong interoperability pattern because it preserves the distinction between semantic result metadata and raw/resource content. DAGR should not become the UI/resource producer: an Apps-aware binding/composition owner should carry SDK-owned UI metadata and govern helper tool calls through the neutral DAGR lifecycle.

The current `official-mcp-sdk.python.v0.2` binding is **not** that Apps-aware owner surface.

## Non-collapse rules

- `_meta.ui.resourceUri` and app visibility are transport/UI metadata, not authority;
- `ui://` resource availability is not admission, standing, verification, or evidence;
- an app-only helper is not exempt from DAGR admission;
- resource/document bytes must remain excluded from metadata-only receipts;
- current receipt attestation limits remain unchanged.

## SRS vNext fence

SRS-VNEXT-EMITTER0 (#81) is landed on current `main`. It remains separately owned and orthogonal: it adds an opt-in external-profile receipt emitter plus tests/docs, without changing SDK-v2 server construction or adding Apps capability/resource hosting. This lane does not alter its profile/envelope semantics or use Apps metadata to justify a new receipt profile.

## Resolved gate

Current bytes still use low-level `mcp.server.Server`, explicitly exclude high-level `MCPServer`, and serve protocol `2026-07-28` on the no-`initialize`, no-`Mcp-Session-Id` path. The studied Apps pattern requires the missing high-level capability/resource-host surface.

**Terminal:** `NOT_SUPPORTED_BY_CURRENT_BINDING`  
**Posture:** `RECON_COMPLETE / NO_CONSTRUCTION_ON_CURRENT_BINDING`  
**Authority:** `AUTHORITY_MOVEMENT=0`
