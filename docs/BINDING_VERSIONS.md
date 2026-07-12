# Binding Version Registry

Binding versions identify the emitter-owned integration surface that observed and receipted a call. They do not revise the SRS profile and MUST NOT be invented ad hoc at call sites.

| Value | Status | Meaning |
|---|---|---|
| `direct-harness.v0.1` | active | The synchronous direct harness included in `dagr-mcp`. |
| `fastmcp.middleware.v0.1` | reserved | The FastMCP middleware binding specified for WP4. |

New values require a reviewed registry change before use. Existing values remain stable for receipt verification and migration.
