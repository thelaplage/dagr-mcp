# MCP Evidence Contract (`x-evidence-contract`) — v0.1

`MCP-EVIDENCE-CONTRACT0`. `AUTHORITY_MOVEMENT = 0`. Status: `DRAFT`, additive only.

## What this is

A portable, additive, machine-readable declaration that MAY be attached to an
MCP tool description under the `x-evidence-contract` key, so discovery can
express what a tool is *capable of producing* without confusing capability
metadata with truth, admission, publication, or authority.

This contract is **transport- and vendor-neutral**. SAM is one motivating
consumer of it — SAM is not referenced anywhere in the schema or the Python
model, and this contract does not encode SAM node identity or any
Counterpedia-specific record identity. Any MCP host, registry, or client may
read and filter on this extension.

- Schema (declarative authority for non-Python consumers):
  [`schemas/mcp-evidence-contract/v0.1/x-evidence-contract.v0.1.schema.json`](../schemas/mcp-evidence-contract/v0.1/x-evidence-contract.v0.1.schema.json)
- Python model / validation support: [`dagr_mcp/evidence_contract.py`](../dagr_mcp/evidence_contract.py)
- Fixtures (positive + adversarial): [`tests/fixtures/evidence_contract/`](../tests/fixtures/evidence_contract/)
- Tests: [`tests/test_evidence_contract.py`](../tests/test_evidence_contract.py)

## Core doctrine — do not weaken

A tool declaration is a claim about the tool *contract*, not proof that any
particular invocation satisfied it.

```
tool_declares_capability != invocation_produced_artifact
invocation_produced_artifact != artifact_verified
artifact_verified != evidence_supported
evidence_supported != admitted
admitted != published
```

A discovery registry may filter on this contract, but it must never upgrade
the standing of returned content because of it. Emitter assertion is never
independently-recomputed finding; disclosure is never verdict.

`dagr_mcp.evidence_contract.NON_EQUIVALENCES` encodes each adjacent pair in
that chain as a machine-checkable narrative (`NEQ-EVC-01` .. `NEQ-EVC-05`),
mirroring the existing `NON_EQUIVALENCES` convention in `dagr_mcp.coverage`.

## v0.1 shape

```json
{
  "x-evidence-contract": {
    "contract_version": "mcp.evidence_contract.v0.1",
    "output_kind": "captured_source",
    "evidence_guarantees": {
      "exact_bytes_available": true,
      "stable_identity_available": true,
      "digest_available": true,
      "digest_algorithm": "sha256",
      "retrieval_observation_available": true,
      "provenance_lineage_ref_available": true
    },
    "eligible_uses": ["discovery", "evidence_candidate", "citation_candidate"],
    "ineligible_uses": ["admission", "publication", "factual_truth"],
    "authority_effect": "none"
  }
}
```

### Fields

| Field | Type | Notes |
|---|---|---|
| `contract_version` | `const` | Fixed to `mcp.evidence_contract.v0.1` for this schema generation. A future v0.2 gets its own constant and its own schema file — never a widened v0.1. |
| `output_kind` | `string`, `^[a-z][a-z0-9_]*$` | Generic, vendor-neutral token (e.g. `source_candidate`, `captured_source`). MUST NOT encode a product-specific record identity. |
| `evidence_guarantees.exact_bytes_available` | `bool` | Exact bytes of the underlying artifact, vs. a paraphrase/rendering. |
| `evidence_guarantees.stable_identity_available` | `bool` | A stable, re-resolvable identity reference. |
| `evidence_guarantees.digest_available` | `bool` | A content digest is claimed. |
| `evidence_guarantees.digest_algorithm` | `"sha256" \| "sha512" \| null` | Required (non-null, recognized) when `digest_available` is `true`; MUST be `null` when `digest_available` is `false` (`CR-EVC-01`). |
| `evidence_guarantees.retrieval_observation_available` | `bool` | An observation of the retrieval event itself, independent of content truth. |
| `evidence_guarantees.provenance_lineage_ref_available` | `bool` | A *reference* to provenance/lineage — never inline provenance content. |
| `eligible_uses` | array, closed enum | Subset of `{discovery, evidence_candidate, citation_candidate}`. Non-empty, no duplicates. |
| `ineligible_uses` | array, closed enum | Fixed to exactly `{admission, publication, factual_truth}` — every v0.1 declaration must disclose the full set. |
| `authority_effect` | `const` | Fixed to `"none"` in v0.1. |

### Why `eligible_uses` and `ineligible_uses` don't overlap by construction

`publication` and `admission` cannot be asserted as positive guarantees in
v0.1. This is enforced structurally, not by convention: the `eligible_uses`
enum is closed to exactly `{discovery, evidence_candidate,
citation_candidate}`, so `admission`, `publication`, `factual_truth`, or any
other token (e.g. `verified`, `published`) is rejected at the schema and the
Python-model layer alike — there is no code path that accepts them.

## Example target behavior (from the mission)

- A **search tool** may declare `output_kind: source_candidate` with no
  exact-byte guarantee, eligible only for `discovery` /
  `evidence_candidate` — not citation-eligible by itself. See
  `tests/fixtures/evidence_contract/positive_search_tool_source_candidate.json`.
- A **capture tool** may declare `output_kind: captured_source` with exact
  bytes, a digest, and a retrieval observation, while still keeping
  `authority_effect: none` and never asserting `publication` as an eligible
  use. See
  `tests/fixtures/evidence_contract/positive_capture_tool_captured_source.json`.

## Compatibility

Additive only. An MCP tool description that omits `x-evidence-contract`
remains fully valid — `dagr_mcp.evidence_contract.validate_tool_descriptor_extension`
passes silently when the key is absent, `None`, or the descriptor itself is
`None`/empty. This module changes no wire format, no MCP protocol behavior,
and no existing SRS receipt shape; it does not import `dagr_mcp.srs_receipts`
or any admission/lifecycle module.

Unknown fields — at the top level of the extension or inside
`evidence_guarantees` — fail closed (are rejected), per this repository's
existing compatibility conventions (see `dagr_mcp.cg_extension` for the
established pattern this module follows).

## Non-goals (this lane)

- No scoring or reputation system.
- No automatic admission or promotion of anything the contract describes.
- No SAM node identity or Counterpedia record identity in the generic schema.
- No change to the MCP protocol, the constitutional DAGR state model, or any
  existing SRS receipt wire format. (Per the lane's STOP condition, none of
  those were required to implement this extension — the seam is a plain-dict
  `x-evidence-contract` object attached to a tool descriptor, validated
  independently of any transport.)

## Using it

```python
from dagr_mcp.evidence_contract import build_evidence_contract, attach_evidence_contract

contract = build_evidence_contract(
    output_kind="captured_source",
    exact_bytes_available=True,
    stable_identity_available=True,
    digest_available=True,
    digest_algorithm="sha256",
    retrieval_observation_available=True,
    provenance_lineage_ref_available=True,
    eligible_uses=["discovery", "evidence_candidate", "citation_candidate"],
)

tool_descriptor = {"name": "capture_source", "description": "..."}
tool_descriptor = attach_evidence_contract(tool_descriptor, contract)
# tool_descriptor now also carries "x-evidence-contract"; every prior key is
# preserved unchanged (attach_evidence_contract never mutates its input).
```

To validate an untrusted descriptor (e.g. one read from a remote tool
listing) before trusting its `x-evidence-contract`:

```python
from dagr_mcp.evidence_contract import validate_tool_descriptor_extension, EvidenceContractError

try:
    validate_tool_descriptor_extension(remote_tool_descriptor)
except EvidenceContractError as exc:
    ...  # reject/ignore the extension; the rest of the descriptor is unaffected
```
