# DAGR-MCP-APPS0

**Status:** DRAFT construction lane / DO NOT MERGE  
**Authority:** `AUTHORITY_MOVEMENT=0`

## Mission

Characterize and, only where the current owner surface already supports it, prove that MCP Apps metadata survives the existing Official MCP SDK 2.x DAGR governed boundary.

Reference specimen: `espirado/mcp-resources-apps-demo` (`io.modelcontextprotocol/ui`, `_meta.ui.resourceUri`, `ui://` resources, and `visibility=["app"]` helpers).

The reference is an interoperability specimen only. Do not vendor it, copy its domain semantics, create an Apps-specific lifecycle, or alter canonical SRS/DAGR semantics.

## First gate

Read the current SDK-v2 binding and record whether tool `_meta`, annotations, app visibility, and resource metadata are preserved, intentionally filtered, or lost. Locate current raw-content exclusion and receipt projection. Inspect active PRs touching the same surfaces, especially SRS-VNEXT-EMITTER0; this lane must not absorb its semantics.

## Required proof, if buildable on current owner surfaces

- normal MCP App result tool retains `ui/resourceUri` metadata;
- `ui://` resource remains addressable through the SDK;
- app-only helper remains app-only after DAGR wrapping;
- app-only helper still traverses ordinary DAGR admission;
- refusal prevents helper execution exactly as for any governed tool;
- UI/resource bytes never enter metadata-only SRS receipts;
- malicious `_meta` keys cannot inject disposition, standing, verification, signer, receipt type, policy, or authority fields;
- legacy FastMCP and historical emitter bytes remain unchanged.

If the SDK strips required metadata before DAGR can observe or preserve it, return a typed `NOT_SUPPORTED_BY_CURRENT_BINDING` result. Do not fabricate support.

## Permanent non-claims

MCP Apps metadata is transport/UI metadata. It is not DAGR authority, SRS authority, evidence, admission, standing, verification, or truth. A DAGR boundary observation must not be described as omniscient execution truth beyond current receipt attestation limits.

## Deliverables

Focused implementation/proof only on the existing SDK-v2 surface, focused tests, exact execution evidence, and `docs/recon/DAGR-MCP-APPS0.md`.