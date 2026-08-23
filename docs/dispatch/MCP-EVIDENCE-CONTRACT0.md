# MCP-EVIDENCE-CONTRACT0

## Mission

Define a portable, additive machine-readable evidence contract for MCP tools so discovery can express what a tool is capable of producing without confusing capability metadata with truth, admission, publication, or authority.

This contract must be transport- and vendor-neutral. SAM is one motivating consumer, not the contract owner.

## Required outputs

1. A versioned schema for `x-evidence-contract` metadata attached to an MCP tool description.
2. Python model/validation support in `dagr-mcp`.
3. Positive and adversarial fixtures.
4. Documentation defining semantics and non-equivalences.
5. Deterministic serialization tests.

## Minimum v0.1 fields

The schema should be deliberately small. It must support at least:
- `contract_version`
- `output_kind`
- `evidence_guarantees`
  - exact bytes available or not
  - stable identity available or not
  - digest availability / algorithm where promised
  - retrieval observation availability
  - provenance/lineage reference availability
- `eligible_uses`
  - discovery
  - evidence_candidate
  - citation_candidate
- `ineligible_uses`
  - admission
  - publication
  - factual_truth
- `authority_effect`, fixed to `none` in v0.1

Use explicit booleans/enums instead of prose where a deterministic contract is possible. Do not claim a guarantee that cannot be mechanically interpreted.

## Core doctrine

A tool declaration is a claim about the tool contract, not proof that any particular invocation satisfied it.

Preserve:

`tool_declares_capability != invocation_produced_artifact != artifact_verified != evidence_supported != admitted != published`

A discovery registry may filter on the contract, but it must not upgrade the standing of returned content.

## Example target behavior

A search tool may declare that it produces `source_candidate` with no exact-byte guarantee and is not citation-eligible by itself.

A capture tool may declare that it can produce `captured_source` with exact bytes, digest, and retrieval observation, while still remaining `authority_effect: none` and not publication-eligible.

## Constraints

- Additive only; do not break current MCP tool descriptors.
- Unknown fields fail closed according to existing repo compatibility conventions.
- Do not embed Counterpedia-specific record identities into the generic schema.
- Do not encode SAM node identity in the generic schema.
- No scoring/reputation system in this lane.
- No automatic admission/promotion.
- `AUTHORITY_MOVEMENT = 0`.

## Acceptance gates

- Existing tool descriptors remain valid without `x-evidence-contract`.
- When present, the extension validates deterministically.
- Invalid claims such as `authority_effect != none` are rejected in v0.1.
- `publication` and `admission` cannot be asserted as positive guarantees.
- Serialization round-trips without semantic drift.
- Adversarial fixtures cover unknown keys, contradictory guarantees, malformed algorithms, and attempts to inject standing/verification/published state.
- Tests prove the metadata changes discovery/filtering only, not evidentiary standing.

## STOP conditions

STOP if implementing the extension requires changing the constitutional DAGR state model, the MCP protocol itself, or existing receipt wire formats. Record the seam instead.

## PR posture

DRAFT only. Do not merge. Report schema path, fixtures, test results, compatibility impact, and `AUTHORITY_MOVEMENT`.