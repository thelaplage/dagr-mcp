# Ecosystem Pilot Adjudication

This pilot models repository-local truth in provisional `.ecosystem/`
declarations. It does not vendor `arcs-ecosystem-kit`, does not define a local
schema, and does not patch another repository.

The requested `garp-doctrine` manifest, schema, registry, and internal doctrine
files are not present in this checkout. Adjudication therefore uses only
repository-local doctrine and architecture sources.

## Declaration Areas

| Area | Status | Finding |
|---|---|---|
| Repository classification | PASS | DAGR MCP needs separate axes for repository type, authority status, architecture layer, and lifecycle stage. |
| Architecture passport | PASS | Current multi-binding architecture fits a passport model if adapter/runtime binding terminology is first-class. |
| Capability mapping | PARTIAL | Current behavior maps to a small vocabulary, but canonical capability semantics are not owned here. |
| Capability bindings | PASS | Bindings need a distinct declaration that references GARP SDK, SRS, ARCS Verify, Workbench, Amnesiac, and Countervail vocabulary surfaces without redefining them. |
| Contracts | PASS | Actual contracts can be inventoried with authority, role, version/fact, stability, direction, and evidence. |
| Dependencies | PASS | Runtime imports, optional integrations, validation dependencies, vendored schema artifacts, and downstream consumers must be separate categories. |
| Lanes | PARTIAL | The active pilot lane is clear; historical sprint lanes are documented, but local branch presence alone should not imply active coordination. |
| Compatibility | PASS | Multi-binding compatibility, registry split, SDK version pins, and environment isolation fit naturally. |
| Conformance | PARTIAL | Dimension-by-dimension statuses are more accurate than a single A-E level. |
| Exceptions | PASS | Genuine transitional exceptions exist: naming, schema validation availability, absent doctrine sources, and SDK v2 environment isolation. |
| Release state | PARTIAL | Release state needs command/result fields, but exact results are better recorded at lane close than frozen as doctrine facts. |

## Fields The Kit Must Support

- `schema_ref` plus a way to mark a declaration as provisional pending kit
  validation.
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
- Conformance dimensions using `PASS`, `FAIL`, `PARTIAL`, `NOT_APPLICABLE`,
  `NOT_EVALUATED`, and `AMBIGUOUS`.
- Exception records that can cite evidence and remain empty when no exception
  exists.
- Lane declarations that separate active lane IDs from observed local branches
  and historical lanes.
- Explicit support for "current implementation byte fact" values that are not
  normative standard semantics.

## Duplicate Existing Doctrine

The kit should avoid restating doctrine that already belongs in canonical
`garp-doctrine`, including substrate vertical separation, reviewable assertions,
and governed evolution principles. Repository declarations should cite those
authorities when available and record checkout limitations when they are absent.

## Concepts Requiring Separate Axes

- Runtime binding, adapter, and reference app are separate repository types.
- Active implementation authority is distinct from canonical doctrine authority.
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

## Schema Proposals That Would Misrepresent DAGR MCP

- A single `repository_type` enum would flatten the real axes and force an
  inaccurate choice between runtime binding, adapter, and reference app.
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
- A global fixed receipt count would contradict current documented cardinality
  and sink-gap behavior.
- A schema that requires package-index naming readiness would misstate the
  current operator-gated distribution-name posture.

## Coordination Notes For arcs-ecosystem-kit

The kit should validate declaration shape while preserving the ability to record
evidence-honest ambiguity. DAGR MCP needs provisional declarations to carry
checkout limitations, implementation byte facts, non-owned concerns, and
dimension-level conformance without implying runtime, receipt, SRS, or verifier
changes.
