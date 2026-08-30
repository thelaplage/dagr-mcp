# DAGR-MCP-APPS0 — initial recon

## External pattern studied

`espirado/mcp-resources-apps-demo` uses MCP Apps (`io.modelcontextprotocol/ui`) with a structured result tool bound to a `ui://` resource. Raw document/page access is separated into app-only read helpers; the ordinary semantic tool returns references rather than document bytes.

## DAGR adoption decision

This is a strong interoperability pattern because it preserves the distinction between semantic result metadata and raw/resource content. DAGR should not become the UI/resource producer: the existing MCP binding should carry SDK-owned metadata and govern helper tool calls exactly as it governs other calls.

## Non-collapse rules

- `_meta.ui.resourceUri` and app visibility are transport/UI metadata, not authority;
- `ui://` resource availability is not admission, standing, verification, or evidence;
- an app-only helper is not exempt from DAGR admission;
- resource/document bytes must remain excluded from metadata-only receipts;
- current receipt attestation limits remain unchanged.

## Concurrency fence

SRS-VNEXT-EMITTER0 is separately owned by active PR #81. This lane must not change its profile/envelope semantics or use Apps metadata to justify a new receipt profile.

## Next gate

Inspect the current Official MCP SDK 2.x binding to determine where tool `_meta`, annotations, visibility, and resource metadata flow or are filtered. Construction is lawful only on that existing surface; otherwise return `NOT_SUPPORTED_BY_CURRENT_BINDING`.

**Current posture:** `RECON_COMPLETE_FOR_BINDING_INSPECTION` / `AUTHORITY_MOVEMENT=0`.