# Governed-memory vertical demo

This demo calls all four Amnesiac operations through a real FastMCP server with
DAGR middleware installed. The output contains signed DAGR receipts, the public
trust bundle and an unsigned refs/digests-only workflow index.

## Native producer path

Install the optional producer dependencies and run:

```bash
python -m pip install -e '.[amnesiac]'
OUT="$(mktemp -d)"
dagr-mcp governed-memory-demo --output "$OUT"
```

Native mode constructs a real Amnesiac `ClaimGraph`, `ShadowGraph`, candidate
store, outcome store and context-packet store. It then calls:

1. `amnesiac.propose_candidates` — proposal only; no admission;
2. `amnesiac.compile_context` — admitted selection plus explicit exclusions;
3. `amnesiac.request_reopening` — request only; caller cannot force reopening;
4. `amnesiac.record_outcome` — refs-only outcome bridge to a candidate.

The workflow index deliberately omits the raw proposed claim text. It contains
operation results, receipt filenames and SHA-256 values, the trust-bundle hash
and limitations. It is an artifact index, not a signature or verification
report.

Verify the receipt set independently in a separately installed ARCS Verify
environment:

```bash
for receipt in "$OUT"/urn_srs_receipt_*.json; do
  arcs-verify "$receipt" \
    --keyring "$OUT/issuer-keys.json" \
    --profile srs.mcp.sdk_enforcement.v0.1
done
```

## Reference mode

```bash
dagr-mcp governed-memory-demo --service-mode reference --output "$OUT"
```

Reference mode exists for CI and contract smoke where the optional producer is
not installed. Its workflow index is marked `reference_contract_only`; it is not
Amnesiac producer evidence and must not be presented as the native product
proof.

## Boundaries

- Proposal is not admission.
- Reopening is not admission and cannot be forced by the caller.
- `record_outcome` accepts refs-only input.
- `compile_context` is still the deterministic reference selector, not the full
  governed context planner.
- DAGR emits receipts but never verifies them.
- The workflow index is unsigned and makes no authenticity claim.
