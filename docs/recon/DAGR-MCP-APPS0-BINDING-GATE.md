# DAGR-MCP-APPS0 — binding inspection gate

Construction must first answer from current `main` bytes:

| Surface | Preserve / filter / lose | Evidence |
|---|---|---|
| tool `_meta` | TBD | exact SDK-v2 binding path required |
| `ui/resourceUri` | TBD | exact SDK-v2 binding path required |
| tool annotations | TBD | exact SDK-v2 binding path required |
| app-only visibility | TBD | exact SDK-v2 binding path required |
| resources/list/read | TBD | exact SDK-v2 binding path required |
| tools/call admission path | TBD | existing DAGR lifecycle only |
| receipt projection | TBD | no Apps-specific receipt semantics |
| raw-content exclusion | TBD | resource/document bytes must remain excluded |

If required metadata is lost before DAGR can lawfully preserve it, the terminal is `NOT_SUPPORTED_BY_CURRENT_BINDING`; adapter invention is not an automatic repair.

PR #81 remains separately owned and must not be pulled into this lane.

`AUTHORITY_MOVEMENT=0`.