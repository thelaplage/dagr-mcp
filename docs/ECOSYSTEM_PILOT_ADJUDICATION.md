# Ecosystem Pilot Adjudication

This pilot records DAGR MCP's current repository truth in `.ecosystem/`
declarations aligned to the checked-out `arcs-ecosystem-kit` v0.1 schema shape.
It does not vendor the kit, add a runtime dependency on the kit, redefine SRS
semantics, alter receipt behavior, or patch another repository.

The proposed constitutional architecture under test is:

```text
Layer -> Authority -> Contracts -> Implementations -> Repositories
```

That model is a proposed coordination input. It is not ratified doctrine.

## Schema Validation

| Area | Status | Finding |
| --- | --- | --- |
| Repository identity | PASS | `REPOSITORY.yaml` can represent repository type, authority status, lifecycle, substrate role, and constitutional roles as separate axes. |
| Architecture passport | PASS | `ARCHITECTURE_PASSPORT.yaml` can model DAGR MCP as primary `L5` with secondary `L3` and `L4` implementation roles. |
| Authority references | PASS | `AUTHORITY_REFERENCES.yaml` can separate semantic authority, current implementation, candidate implementation, historical implementation, producers, consumers, verifier counterparts, and migration status. |
| Capability bindings | PASS | `CAPABILITY_BINDINGS.yaml` now records bindings only. It does not define canonical capability semantics. |
| Contract bindings | PASS | `CONTRACT_BINDINGS.yaml` can represent provided and consumed contracts with separate semantic authority and implementation sides. |
| Dependencies | PASS | `DEPENDENCIES.yaml` can distinguish runtime, adapter, schema, validation, implementation, and optional-consumer dependencies. |
| Boundaries | PASS | `BOUNDARIES.yaml` can represent runtime-import, verifier-isolation, semantic-authority, policy, product-adapter, and data boundaries. |
| Responsibilities | PASS | `RESPONSIBILITIES.yaml` can represent owned implementation responsibilities and explicitly unowned concerns. |
| Compatibility projection | PARTIAL | The schema can represent profile/product/adapter/verifier projections, but product/profile version fields are less natural for ranges such as `fastmcp>=3.4.4,<4`. |
| Conformance projection | PARTIAL | The schema accepts one A-E declaration plus gates; DAGR MCP still needs dimension-level PASS/PARTIAL/AMBIGUOUS findings to avoid over-certification. |
| Exceptions | PASS | Transitional exceptions can be represented with schema-valid IDs and scoped records. |
| Release state | PASS | Release state can record required gates and dependent releases without changing runtime behavior. |

## Fields Accepted

- `schema` and `schema_version` replace the earlier provisional `schema_ref`
  and `schema_status` shape.
- `constitutional_roles.primary_layer` and `secondary_layers` preserve the
  separate layer-role axes.
- `authority.status` keeps implementation status separate from repository type,
  lifecycle, conformance, and semantic authority.
- `semantic_authority.repository: null` with `status: unresolved` can represent
  unresolved L2 governed-action/protocol authority.
- `historical_implementations` records `garp-sdk` provenance without making it
  current semantic authority by default.
- `verifier_counterparts` records `arcs-verify` as an independent counterpart,
  not as producer runtime code.
- `declarations.defines: []` in `CAPABILITY_BINDINGS.yaml` prevents DAGR MCP
  from claiming canonical capability definitions.
- `native_registry_refs` can cite richer local and sibling registries without
  copying their semantics.
- `forbidden_dependencies` in `BOUNDARIES.yaml` can encode producer/verifier
  and kit/runtime separation.

## Fields Requiring Amendment

- Compatibility product/profile projections should allow explicit version-range
  objects. Current declarations must place ranges in `authority_version` or
  notes.
- Compatibility and conformance projections should allow nullable or unresolved
  authority repositories where a repository is intentionally recording an
  unresolved authority question.
- Conformance should support dimension-level statuses directly:
  `PASS`, `FAIL`, `PARTIAL`, `NOT_APPLICABLE`, `NOT_EVALUATED`, and
  `AMBIGUOUS`.
- The kit should provide a first-class place for proposed input bundles such as
  A0-A6. In this checkout no literal A0-A6 document IDs were found in the kit
  docs, so DAGR MCP records exact sibling document paths under A0-A6 pilot input
  labels in `AUTHORITY_REFERENCES.yaml`.
- A generic schema should not force policy-decision vocabulary and receipt
  disposition vocabulary into one field. DAGR MCP must preserve the distinction.
- Release state can say a gate is required and passed, but exact command output
  remains final-report evidence rather than durable doctrine.

## Unresolved L2/L3/L4 Questions

- L2: Whether governed-action/protocol semantics are ARCS-neutral,
  DAGR-governed, or owned by another authority remains unresolved in current
  repository evidence.
- L3: The boundary between DAGR runtime/policy implementation and Countervail
  institutional policy semantics remains unresolved.
- L3: `garp-sdk` remains historical integrated source-estate material and
  optional integration material, not current authority by default.
- L4: Whether evidence production eventually moves to a separate
  `dagr-evidence` authority is outside this repository's current evidence.
- L4/L6: DAGR MCP emits evidence; ARCS Verify independently verifies serialized
  artifacts. The producer/verifier boundary must remain exact.

## Repository-Native Facts Outside Generic Schemas

- `receipt_version: srs.core.v5.1` is an emitted byte fact and
  internal/pre-public lineage, not a public SRS release claim.
- `profile_id: srs.mcp.sdk_enforcement` and `profile_version: v0.1` are current
  implementation byte facts consumed from SRS artifacts.
- Runtime policy decisions are `allow`, `deny`, `gate`, `defer`, and
  `fail_closed`; receipt dispositions are `admitted`, `refused`, and
  `deferred_for_review`.
- Receipt cardinality is conditional and variable. DAGR MCP must not be modeled
  as always producing exactly two receipts per invocation.
- Binding identifiers such as `fastmcp.middleware.v0.1` and
  `official-mcp-sdk.python.v0.2` are DAGR MCP receipt/binding facts, not generic
  framework version semantics.
- FastMCP compatibility, official MCP SDK 1.x binding, protocol-neutral core,
  official MCP SDK 2.x isolated binding, and neutral service composition are all
  current multi-binding architecture facts.
- Workbench service grouping evidence identifies DAGR MCP as a candidate target
  only. It is not ownership, compatibility proof, or traffic cutover.
- Countervail receipt-ingest expectations are downstream consumer facts, not
  DAGR MCP runtime imports.

## Proposed Inputs

The exact checked-out input paths referenced by this pilot are:

| Input label | Exact document path | Status |
| --- | --- | --- |
| A0 | `sibling:arcs-ecosystem-kit:docs/ARCS_CONSTITUTIONAL_LAYER_MODEL.md` | Proposed, unratified |
| A1 | `sibling:arcs-ecosystem-kit:docs/GARP_DOCTRINE_COMPATIBILITY.md` | Proposed, unratified |
| A2 | `sibling:arcs-ecosystem-kit:docs/adr/0001-schema-identifier-namespace.md` | Kit PR 1 ADR input |
| A3 | `sibling:arcs-ecosystem-kit:docs/SCHEMA_CATALOG.md` | Proposed schema catalog |
| A4 | `sibling:arcs-ecosystem-kit:docs/LAYER_AUTHORITY_RULES.md` | Proposed authority rules |
| A5 | `sibling:arcs-ecosystem-kit:docs/SCHEMA_OWNERSHIP.md` | Proposed schema ownership |
| A6 | `sibling:arcs-ecosystem-kit:docs/EXISTING_ECOSYSTEM_ASSET_MAP.md` | Proposed asset map |

The A0-A6 labels are pilot coordination labels in this repository. They are not
evidence of ratification.

## Doctrine Reconciliation Limit

The requested `garp-doctrine` files are not physically present inside this
DAGR MCP checkout. The pilot inspected available sibling and repository-local
references instead, including the kit's GARP compatibility document and layer
catalog. It does not fabricate missing doctrine content and does not supersede
`garp-doctrine`.

## Coordination Notes

`arcs-ecosystem-kit` should continue treating these declarations as projection
and coordination schemas. They should validate shape while preserving
evidence-honest ambiguity, unresolved authorities, historical source estates,
non-owned concerns, and repository-native byte facts that should not become
standard semantics.
