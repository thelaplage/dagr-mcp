# DAGR-MCP-APPS0 — binding inspection gate

**Status:** RESOLVED  
**Terminal:** `NOT_SUPPORTED_BY_CURRENT_BINDING`  
**Authority:** `AUTHORITY_MOVEMENT=0`

The gate was rechecked after SRS-VNEXT-EMITTER0 (#81) landed. Current `main` still uses the same low-level Official MCP SDK v2 server construction and the same protocol `2026-07-28` no-handshake path.

| Surface | Current binding finding | Evidence / consequence |
|---|---|---|
| tool `_meta` | generic Tool metadata may be carried as part of the registered `mcp_types.Tool` definition | `tools/list` returns the registered definitions; generic metadata carriage alone does not establish Apps capability support |
| `ui/resourceUri` | no Apps capability contract is advertised | no high-level Apps extension composition exists on this binding |
| tool annotations | carried only as ordinary Tool-definition data where supported by the SDK type | does not create Apps/resource semantics or authority |
| app-only visibility | not provided by the DAGR SDK-v2 server construction | studied Apps visibility semantics require an Apps-aware extension surface |
| resources/list/read | not composed by `build_governed_server` | current owner surface exposes `tools/list` and governed `tools/call`, not an Apps resource host |
| tools/call admission path | supported | existing `SdkV2LifecycleAdapter` governs tool dispatch; no Apps exemption exists |
| receipt projection | existing DAGR/SRS lifecycle only | landed #81 adds an opt-in external-profile emitter but does not add Apps semantics or alter server construction |
| raw-content exclusion | no Apps resource-read path exists here | resource/document bytes are not introduced by this binding; a future Apps owner must separately prove receipt exclusion |

The blocking fact is the missing Apps capability/resource-host contract, not merely whether an arbitrary `_meta` key can survive a Tool definition. Adding high-level `MCPServer`/Apps composition to this frozen binding would be a new binding/composition decision, not a metadata-preservation patch.

SRS-VNEXT-EMITTER0 (#81) is landed and remains orthogonal: its changed files are the external-profile receipt emitter plus its tests/docs. This recon consumes none of those profile/envelope semantics.
