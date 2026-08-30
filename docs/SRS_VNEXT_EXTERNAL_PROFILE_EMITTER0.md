# SRS-VNEXT-EMITTER0

**Status:** DRAFT / candidate-consumer implementation  
**Authority movement:** `0`

This lane makes the reviewed SRS vNext/external-profile model executable in the
canonical `dagr-mcp-core` receipt substrate without changing the historical
`SignedReceiptEmitter` wire contract.

## Contract

`ExternalProfileSignedReceiptEmitter` is opt-in and requires an explicit
`ExternalProfileReceiptContract` carrying:

- application-owned profile id/version;
- globally namespaced admission and outcome receipt types;
- globally namespaced extension namespace;
- emitter identity;
- exact envelope-contract and profile-contract digest refs.

It emits the successor carrier fields `envelope_schema_version` and
`emitter_id`, plus exact `contract_refs`, while inheriting the existing
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

This implementation is intentionally downstream of the reviewed-but-unlanded
standards campaign:

- arcs-srs #56 — SRS External Profile Contract v0.1
- arcs-srs #57 — SRS-RECEIPT-TYPE-RECON0 / Envelope v0-next
- dagr-spec #13 — DAGR↔SRS binding and extension-domain contract (referenced for
  the non-fabrication boundary; not serialized by this lane)

The implementation does not vendor or ratify those standards. Consumer lanes
must pin the exact bytes they claim to use and independent verification remains
an ARCS Verify responsibility.

## Proof obligation

Before readiness, run the `dagr-mcp-core` suite and the focused
`test_external_profile_receipts.py` tests. The downstream integration proof must
also validate emitted bytes against the exact vNext envelope + profile schemas
and independently verify the signature/trust findings; emitter tests alone are
not an interoperability proof.
