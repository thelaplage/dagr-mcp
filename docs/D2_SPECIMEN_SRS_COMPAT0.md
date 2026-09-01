# D2 Specimen SRS Compatibility Proof

Status: **DRAFT / PROOF-ONLY / AUTHORITY_MOVEMENT=0**

Purpose: establish whether current `dagr-mcp` can freshly generate the historical SRS receipt family that Countervail Gate D is already ratified to verify, without repinning Gate D or introducing any new authority semantics.

## Exact bases

- `dagr-mcp` base: `3a3bd386971748fccfc186d8cbdda59c2287dbd6`
- Countervail Gate-D ARCS pin: `ee98a1f6cc88687ff101633ef857e214193cfce3`
- Gate-D ARCS subcommand: `dagr-report-v0-2`
- Gate-D selected profile: `srs.mcp.sdk_enforcement.v0.1`
- Gate-D envelope schema: `arcs_verify/data/srs-envelope-v0.2.1.schema.json`
- Gate-D report contract: `srs.dagr_verification_report.v0.2`

## Producer-side result

Current `dagr_mcp_core.srs_receipts.SignedReceiptEmitter` remains the historical v0.2.1 producer and exposes:

```text
receipt_version = srs.core.v5.1
profile_id      = srs.mcp.sdk_enforcement
profile_version = v0.1
receipt_type    = sdk_enforcement
boundary_type   = mcp_tool_call
protocol_binding = mcp
signature       = Ed25519 / RFC8785-JCS
```

`SigningIdentity.generate(...)` creates a fresh Ed25519 key and `trust_bundle()` exports public trust material without private-key bytes. `SignedReceiptEmitter` freshly emits signed admission and outcome receipts through `RawEnvelopeFileSink`.

The focused test `packages/dagr-mcp-core/tests/test_d2_specimen_srs_compat0.py` exercises that real emitter with a specimen-local key and verifies the exact Gate-D profile identity, the admission→outcome reference, signature surface, and trust-bundle public-material boundary.

## Important trust wording

The generated keyring sets its one issuer entry's SRS `trusted` flag to `true` because that is the verifier input required to exercise trust-relative signature verification. For the D2 specimen this means only:

> trusted by the bounded specimen-local trust bundle supplied to that verification run.

It MUST NOT be rendered or described as institutional trust, organizational authorization, production trust, compliance approval, or a Countervail authority fact.

## What this PR does not prove

This DAGR-MCP lane does not execute ARCS Verify and does not claim a verifier PASS. Independent verifier execution belongs to Countervail Gate D and must occur from the exact clean pinned ARCS checkout.

Therefore the cross-repo result is currently:

```text
fresh DAGR-MCP historical SRS emission        PROVABLE IN THIS LANE
exact Gate-D profile identity                 MATCHES BY CONTRACT IDENTITY
fresh Ed25519 specimen-local signing          PROVABLE IN THIS LANE
specimen trust-bundle generation              PROVABLE IN THIS LANE
actual ARCS child-process invocation           NOT_EVALUATED HERE
Gate-D VERIFIER_PASS                           NOT_EVALUATED HERE
Gate-C MATCH                                   NOT_EVALUATED HERE
```

The eventual Countervail specimen runner must consume the freshly emitted receipt/trust bytes and invoke the already-ratified Gate-D executor. A missing pinned checkout, dirty checkout, verifier repin, malformed report, or non-zero source-integrity path must remain `NOT_EVALUATED`/fail closed according to Gate D.

## Permanent separations

```text
producer-side compatibility != independent verification
specimen-local trust         != institutional trust
signature validity           != Countervail authorization
DAGR receipt                 != Countervail LEP receipt
same specimen run            != authority bridge
```

No production source is changed by this proof lane.
