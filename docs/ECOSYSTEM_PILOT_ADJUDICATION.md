# Ecosystem Pilot Adjudication

This pilot models repository-local truth in provisional `.ecosystem/`
declarations. It does not vendor `arcs-ecosystem-kit`, does not define a local
schema, and does not patch another repository.

The concurrent kit lane is now testing a proposed architecture model ordered as
Layer -> Authority -> Contracts -> Implementations -> Repositories. This pilot
uses that model provisionally and does not claim it is ratified doctrine.

The requested `garp-doctrine` manifest, schema, registry, and internal doctrine
files are not present in this checkout. Adjudication therefore uses only
repository-local doctrine and architecture sources.

## Declaration Areas

| Area | Status | Finding |
|---|---|---|
| Repository classification | PASS | DAGR MCP needs separate axes for repository type, authority status, architecture layer, and lifecycle stage. |
| Layer projection | PASS | DAGR MCP fits primary `L5 product_and_protocol_adapters` with secondary `L3 runtime_and_policy_implementation` and `L4 evidence_production` roles, if the schema supports primary and secondary roles. |
| Authority references | PASS | The model can represent DAGR MCP accurately only if current implementation, semantic authority, candidate owner, historical source, and verifier counterpart are separate axes. |
| Architecture passport | PASS | Current multi-binding architecture fits a passport model if adapter/runtime binding terminology and proposed layer roles are first-class. |
| Capability bindings | PARTIAL | Current behavior can be bound to a small vocabulary, but governed-action/protocol authority remains unresolved where current evidence does not establish a ratified owner. |
| Contract bindings | PASS | Actual contracts can be inventoried with current implementation, semantic authority, candidate owner, historical source, role, version/fact, stability, direction, and evidence. |
| Dependencies | PASS | Runtime imports, optional integrations, validation dependencies, vendored schema artifacts, and downstream consumers must be separate categories. |
| Lanes | PARTIAL | The active pilot lane is clear; historical sprint lanes are documented, but local branch presence alone should not imply active coordination. |
| Compatibility projection | PASS | Multi-binding compatibility, registry split, SDK version pins, and environment isolation fit naturally as an implementation projection. |
| Conformance projection | PARTIAL | Dimension-by-dimension statuses are more accurate than a single A-E level or repository-wide certification. |
| Exceptions | PASS | Genuine transitional exceptions exist: naming, schema validation availability, absent doctrine sources, and SDK v2 environment isolation. |
| Release state | PARTIAL | Release state needs command/result fields, but exact results are better recorded at lane close than frozen as doctrine facts. |

## Fields The Kit Must Support

- `schema_ref` plus a way to mark a declaration as provisional pending kit
  validation.
- A top-level declaration for authority references.
- A way to mark a layer model as proposed under test, without claiming ratified
  doctrine.
- Layer roles with one primary layer and zero or more secondary roles.
- Repository `types` as a list, not a single enum.
- Authority status independent from repository type.
- Architecture layer and role independent from product lifecycle stage.
- Owned and unowned concern lists.
- Contract direction values such as `provided`, `consumed`, `emitted`,
  `validated`, and combinations of those.
- Dependency categories that distinguish runtime import, optional integration,
  vendored schema artifact, validation dependency, and downstream consumer.
- Capability fields for `defined_elsewhere`, `implemented_here`,
  `consumed_here`, `product_native_mapping`, `planned`, `partial`, and
  `validated`.
- A separate capability-binding declaration that can reference externally owned
  vocabulary surfaces and explicitly state that canonical capability definitions
  are not claimed by this repository.
- Contract-binding declarations that distinguish current implementation,
  semantic authority, candidate owner, and historical source on each binding.
- Projection declarations for compatibility and conformance, separate from
  source authority or certification.
- Conformance dimensions using `PASS`, `FAIL`, `PARTIAL`, `NOT_APPLICABLE`,
  `NOT_EVALUATED`, and `AMBIGUOUS`.
- Exception records that can cite evidence and remain empty when no exception
  exists.
- Lane declarations that separate active lane IDs from observed local branches
  and historical lanes.
- Explicit support for "current implementation byte fact" values that are not
  normative standard semantics.
- An unresolved authority state for governed-action/protocol semantics when
  current repository evidence does not establish a ratified owner.
- A historical-source role for source estates such as `garp-sdk`, distinct from
  current semantic authority.

## Duplicate Existing Doctrine

The kit should avoid restating doctrine that already belongs in canonical
`garp-doctrine`, including substrate vertical separation, reviewable assertions,
and governed evolution principles. Repository declarations should cite those
authorities when available and record checkout limitations when they are absent.

## Concepts Requiring Separate Axes

- Runtime binding, adapter, and reference app are separate repository types.
- Active implementation authority is distinct from canonical doctrine authority.
- Current implementation is distinct from semantic authority.
- Semantic authority is distinct from independent verifier counterpart.
- Candidate owner is distinct from verified owner or traffic cutover.
- Historical source is distinct from current authority by default.
- SRS profile consumption is distinct from SRS normative ownership.
- Producer receipt emission is distinct from independent verification.
- Policy decision vocabulary is distinct from receipt disposition vocabulary.
- Capability semantic ownership is distinct from implementation exposure.
- Capability definitions are distinct from repository-local capability
  bindings.
- Package dependency is distinct from validation dependency.
- Public release readiness is distinct from naming/distribution readiness.
- Workbench service grouping is distinct from verified ownership or cutover.
- Countervail receipt ingest expectations are distinct from DAGR MCP runtime
  dependencies.
- `arcs-srs` evidence/schema authority is distinct from DAGR MCP's current
  implementation of an emitter over that profile.
- `arcs-verify` report authority is distinct from DAGR MCP's compatibility with
  independent verification.

## Implementation Facts That Should Not Become Standard Semantics

- `receipt_version: srs.core.v5.1` is a current implementation byte fact and
  internal/pre-public lineage for this repository, not a public SRS release
  statement.
- Binding identifiers such as `fastmcp.middleware.v0.1` and
  `official-mcp-sdk.python.v0.1` are DAGR MCP receipt facts, not universal MCP
  package version semantics.
- The current receipt-cardinality ceilings are implementation contract facts and
  include configuration and sink-failure caveats.
- The FastMCP task-submitted path and official-SDK unsupported task/input
  behavior are binding-specific facts.
- `compile_context` is a deterministic reference selector v0 here, not the full
  governed context planner.
- The proposed layer IDs (`L3`, `L4`, `L5`) are pilot modeling coordinates, not
  ratified doctrine.
- `garp-sdk` vocabulary references are historical or adjacent source-estate
  facts unless a separate authority declaration establishes current authority.

## Schema Proposals That Would Misrepresent DAGR MCP

- A single `repository_type` enum would flatten the real axes and force an
  inaccurate choice between runtime binding, adapter, and reference app.
- A schema that makes layer model fields imply ratified doctrine would overstate
  the status of the concurrent kit lane.
- A schema that allows only one layer role would misrepresent DAGR MCP's primary
  adapter role plus runtime-policy and evidence-production secondary roles.
- A schema that collapses authority into repository ownership would misrepresent
  `arcs-srs`, ARCS Verify, Workbench, Countervail, and `garp-sdk` relationships.
- A boolean `is_verifier` or verifier role inferred from receipt compatibility
  would misstate producer/verifier separation.
- A single "capabilities implemented" list without semantic authority and
  validation state would imply DAGR owns canonical capability semantics.
- A capability schema that requires embedded canonical definitions would force
  this repository to redefine terms that belong to GARP SDK, SRS, ARCS Verify,
  Workbench, Amnesiac, or Countervail.
- A dependency model that treats ARCS Verify as a runtime import would be false.
- A Workbench integration field that treats `dagr_mcp_tooling` as ownership or
  live traffic routing would contradict the Workbench registry's unverified
  candidate-target posture.
- A default rule that treats `garp-sdk` as current authority would overstate the
  available evidence; it is historical integrated source-estate material here.
- A global fixed receipt count would contradict current documented cardinality
  and sink-gap behavior.
- A schema that requires package-index naming readiness would misstate the
  current operator-gated distribution-name posture.

## Coordination Notes For arcs-ecosystem-kit

The kit should validate declaration shape while preserving the ability to record
evidence-honest ambiguity. DAGR MCP needs provisional declarations to carry
checkout limitations, implementation byte facts, non-owned concerns, unresolved
semantic authority, historical source references, and dimension-level
projections without implying runtime, receipt, SRS, or verifier changes.
