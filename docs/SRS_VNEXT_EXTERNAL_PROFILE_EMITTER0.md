# SRS-VNEXT-EMITTER0

**Status:** DRAFT / candidate-consumer implementation  
**Authority movement:** `0`

This lane makes the SRS vNext/external-profile model executable in the
canonical `dagr-mcp-core` receipt substrate without changing the historical
`SignedReceiptEmitter` wire contract.

## Contract

`ExternalProfileSignedReceiptEmitter` is opt-in and requires an explicit
`ExternalProfileReceiptContract` carrying:

- application-owned profile id/version;
- globally namespaced admission and outcome receipt types;
- globally namespaced extension namespace;
- emitter identity;
- exact envelope-contract and profile-contract digest refs; and
- the actual envelope/profile contract bytes those digest refs claim to bind.

A syntactically valid digest is not sufficient. Construction fails closed unless
`envelope_contract_digest` and `profile_contract_digest` recompute from the
supplied bytes. The envelope bytes have a second, independent identity gate:
their Git blob must equal the exact final ARCS SRS #57 successor-envelope blob
`39beaeaa65ab97e6e81d32057b52ac20c3f8a1ea` from merge
`483c73e02ca87b286597eb234c759d93aeed687d`.

The application-owned profile bytes are parsed before emission and must agree
with the configured profile id/version, extension namespace, admission/outcome
receipt types, exact vNext envelope SHA-256, signing posture, attestation-limit
posture, and unknown-profile behavior.

It emits the successor carrier fields `envelope_schema_version` and
`emitter_id`, plus byte-bound `contract_refs`, while inheriting the existing
admission/outcome lifecycle methods and Ed25519/RFC8785 signing machinery.

The existing `SignedReceiptEmitter` remains the byte-stable
`srs.mcp.sdk_enforcement.v0.1` producer. No default changes.

## Deliberate DAGR boundary

This lane does **not** synthesize `dagr_binding`.

The current historical MCP vocabulary is consumer-local/unbound; there is no
implicit `mcp_action -> action` bridge. A later application composition may
supply a DAGR binding only when it has a real domain-owned vocabulary,
decision digest, and contract digest satisfying the DAGR↔SRS binding contract.

Therefore:

```text
runtime admission plan != generic DAGR-owned decision object
mcp_action              != action
SRS external profile    != DAGR domain standing
receipt emitted         != authorization or truth
```

## Candidate standards pins

The standards bytes are now merged upstream but remain explicitly proposed /
pre-1.0 / non-canonical; merge is not ratification or canonical promotion.

- arcs-srs #56 — SRS External Profile Contract v0.1, merge
  `bb0874838c03b7cf0784ec2a0c1a8cf292b9be99`;
- arcs-srs #57 — SRS-RECEIPT-TYPE-RECON0 / Envelope v0-next, merge
  `483c73e02ca87b286597eb234c759d93aeed687d`;
- exact successor-envelope blob:
  `39beaeaa65ab97e6e81d32057b52ac20c3f8a1ea`;
- exact external-profile declaration-schema blob:
  `4832c73870820575362ccd98868de990c51b74c1`;
- dagr-spec #13 — DAGR↔SRS binding and extension-domain contract (referenced for
  the non-fabrication boundary; not serialized by this lane).

The implementation does not vendor an SRS runtime and does not ratify those
standards. The two exact ARCS schema files are copied under `tests/fixtures/`
only so conformance tests can prove the bytes they validate against have the
same Git object identities as the upstream final merge.

## Proof obligation

The focused repair proof must establish all of the following:

1. the two schema fixtures reproduce the exact final ARCS Git blobs;
2. the application profile declaration validates against the exact external-
   profile declaration schema;
3. emitted admission, result, indeterminate-delivery, and exception receipts
   validate against the exact vNext envelope schema with format checking;
4. valid-looking but false digest claims fail closed;
5. altered envelope bytes fail the immutable ARCS Git-blob pin even when the
   caller recomputes a matching SHA-256 for the altered bytes;
6. the historical `SignedReceiptEmitter` default/wire shape remains unchanged;
7. no `dagr_binding` is fabricated and independent verification remains an
   ARCS Verify responsibility.

Repository-suite or CI results count only when commands actually execute. A
workflow with no runner steps is infrastructure/no-execution evidence, not a
passing or failing code verdict.
