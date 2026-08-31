# DAGR-MCP-APPS0

**Status:** COMPLETED RECON / NO CONSTRUCTION ON CURRENT BINDING  
**Terminal:** `NOT_SUPPORTED_BY_CURRENT_BINDING`  
**Authority:** `AUTHORITY_MOVEMENT=0`

## Mission

Characterize and, only where the current owner surface already supports it, prove that MCP Apps metadata survives the existing Official MCP SDK 2.x DAGR governed boundary.

Reference specimen: `espirado/mcp-resources-apps-demo` (`io.modelcontextprotocol/ui`, `_meta.ui.resourceUri`, `ui://` resources, and `visibility=["app"]` helpers).

The reference is an interoperability specimen only. Do not vendor it, copy its domain semantics, create an Apps-specific lifecycle, or alter canonical SRS/DAGR semantics.

## Resolved gate

Current `main` still constructs `official-mcp-sdk.python.v0.2` with the low-level `mcp.server.Server`, `on_call_tool` / `on_list_tools`, and the modern no-`initialize`, no-`Mcp-Session-Id` protocol path. It explicitly does not use the high-level `MCPServer` layer required by the studied Apps extension surface.

SRS-VNEXT-EMITTER0 (#81) is now landed on `main`. Its delta is limited to the opt-in external-profile receipt emitter plus tests/docs; it does not change SDK-v2 server construction, resource hosting, Apps capability advertisement, or the protocol handshake. This lane consumes none of its profile/envelope semantics.

## Required proof, if a future owner surface supports Apps

- normal MCP App result tool retains `ui/resourceUri` metadata;
- `ui://` resource remains addressable through the SDK;
- app-only helper remains app-only after DAGR wrapping;
- app-only helper still traverses ordinary DAGR admission;
- refusal prevents helper execution exactly as for any governed tool;
- UI/resource bytes never enter metadata-only SRS receipts;
- malicious `_meta` keys cannot inject disposition, standing, verification, signer, receipt type, policy, or authority fields;
- legacy FastMCP and historical emitter bytes remain unchanged.

These proofs are **not buildable on the current binding** because the Apps capability/resource-host contract is absent. Preserving generic Tool `_meta` alone is insufficient. Do not fabricate support.

## Permanent non-claims

MCP Apps metadata is transport/UI metadata. It is not DAGR authority, SRS authority, evidence, admission, standing, verification, or truth. A DAGR boundary observation must not be described as omniscient execution truth beyond current receipt attestation limits.

## Disposition

Record the negative compatibility result in `docs/recon/DAGR-MCP-APPS0-RESULT.md`. A future Apps integration requires a separately scoped binding/composition owner that explicitly owns the high-level Apps protocol surface and reuses the neutral DAGR lifecycle without silently widening `official-mcp-sdk.python.v0.2`.
