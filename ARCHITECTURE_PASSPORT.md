# Architecture Passport

## Mission

DAGR MCP is the governed runtime boundary for MCP tool calls. It projects
binding-specific requests into protocol-neutral lifecycle decisions, emits
signed metadata-only SRS receipts, and prevents refused or deferred calls from
executing at the configured boundary.

This repository is an emitter, runtime binding, adapter/interception boundary,
and reference implementation. It is not the ARCS standard, SRS authority,
policy authority, verifier, durable memory system, public evidence view,
certification service, gateway or network proxy, RBAC system, or Countervail.

## Owned Layer

The owned layer is `product_translation_and_execution_boundary`; the role is
substrate. The runtime sits inside configured MCP binding paths and turns host
or framework-specific tool-call events into a neutral admission and outcome
lifecycle.

Current real surfaces are multi-binding:

| Surface | Current role |
|---|---|
| FastMCP middleware | Active legacy compatibility runtime binding |
| Official MCP SDK 1.x | Active compatibility binding over `mcp==1.29.0` |
| `packages/dagr-mcp-core` | Protocol-neutral lifecycle and receipt substrate |
| Official MCP SDK 2.x | Isolated binding over `mcp==2.0.0` |
| `dagr_mcp_service` | Neutral service and connector composition layer |
| Amnesiac tools | Optional operation exposure through the DAGR boundary |

## Imported Concepts

DAGR MCP imports MCP as the governed protocol surface, SRS as the emitted
receipt envelope/profile vocabulary, ARCS Verify as the separate independent
verification program, and ARCS Amnesiac as an optional producer integration.

The current emitted receipt byte facts are:

| Field | Value |
|---|---|
| `receipt_version` | `srs.core.v5.1` |
| `profile_id` | `srs.mcp.sdk_enforcement` |
| `profile_version` | `v0.1` |

`srs.core.v5.1` is treated here only as current implementation lineage, not as
an SRS public-release statement.

## Exported Contracts

The repository exports or validates these contracts:

| Contract | Role |
|---|---|
| `dagr.mcp.lifecycle_contract` | Binding-neutral lifecycle vocabulary |
| `dagr.mcp.lifecycle_binding_mask` | FastMCP binding projection mask |
| `docs/BINDING_VERSIONS.md` | Binding identifier registry |
| `srs.mcp.sdk_enforcement` emitted facts | Admission/outcome receipt profile use |
| `srs.trust_bundle.v0.1` | Trust-bundle production |
| `dagr.mcp.gateway_service_contract` | Neutral service request/response model |
| `garp.mcp_record_custody_gateway.v0.1` | Refs-and-hashes custody projection |

ARCS Verify report contracts are consumed for compatibility but remain owned by
the ARCS Verify repository. Only serialized receipts, trust bundles, and schema
artifacts cross that boundary.

## Extension Points

The repository exposes extension points for actor resolution, policy resolution,
review-object creation, receipt sinks, official-SDK delegate handlers, service
connectors, and optional Amnesiac service injection. These are integration
points around the governed boundary; they are not mechanisms for tool arguments
to assert actor, tenant, credential, signing, or receipt authority.

## Compatibility Guarantees

The current compatibility posture is conservative:

- FastMCP behavior remains frozen against committed behavioral fixtures.
- Binding identifiers are stable receipt facts, not package versions.
- The root distribution remains legacy compatibility code.
- `dagr-mcp-core` imports no `mcp` or `fastmcp`.
- The SDK v2 binding is isolated because `mcp` 1.x and 2.x are not designed to
  coexist.
- Receipt schema/profile values are not changed by this pilot.

## Security Boundary

Governance happens before execution for consequential tool actions at the
configured boundary. Refused and deferred calls do not run. Receipts are
metadata-only: arguments and results are represented by `sha256:` digests, raw
artifact classes are excluded, and prohibited raw-content or credential keys
are rejected before signing and writing.

The boundary observes only traffic routed through the configured binding. It
does not observe MCP traffic that bypasses that path, and it does not prove
server-internal retention behavior.

## Attestation Limits

A valid DAGR receipt proves that the receipt was issued and unmodified under the
resolved trusted key and within the receipt's stated attestation limits. It does
not prove the underlying event was historically true, that a downstream cache did
or did not satisfy the call, that the model/provider retained nothing, or that
all surrounding systems behaved correctly.

## Producer And Verifier Separation

This repository produces signed serialized receipts and trust bundles. ARCS
Verify independently recomputes verification results from serialized artifacts.
DAGR MCP does not turn its own output into a verdict and does not import ARCS
Verify as a runtime dependency.

## Transitional Architecture

The repository currently carries frozen legacy compatibility code, a separately
extracted core, an isolated SDK v2 package, and optional Amnesiac integration.
That split is real architecture, not a single FastMCP-only implementation.

The requested `garp-doctrine` source files are not present in this checkout, so
this passport reconciles only against repository-local doctrine and architecture
documents.
