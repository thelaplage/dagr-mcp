# Optional SCITT transparency publication

DAGR MCP can optionally publish a digest-only binding of an **already committed**
signed SRS receipt to a SCITT Transparency Service.

This is a post-commit side effect. It is not part of admission.

```text
DAGR decision
    ↓
signed SRS receipt
    ↓
configured SRS sink commits
    ↓
----------------------------- governance transaction complete
    ↓
optional transparency publisher
    ↓
SCITT Signed Statement → SCRAPI
```

## Invariants

- The existing SRS receipt sink commits first.
- A failure from that SRS sink still fails receipt emission normally.
- SCITT transport failure, Transparency Service refusal, or transparency-result
  custody failure never changes DAGR disposition or tool execution.
- Refused DAGR calls are eligible for publication exactly like admitted/outcome
  receipts; the two refusal namespaces are unrelated.
- The SCITT statement payload contains a digest binding, not tool arguments,
  results, prompts, transcripts, credentials, or the full SRS envelope.
- The publisher does not verify the returned SCITT Receipt. Verification belongs
  to an independent verifier such as ARCS Verify.

## Surface

`dagr_mcp.transparency.PublishingReceiptSink` wraps any existing receipt sink.
With no publisher configured it is behaviorally transparent.

`ScittStatementPublisher` is optional and imports `scitt-cose` only when used.
Install the opt-in extra for that adapter:

```bash
pip install -e ".[scitt]"
```

`ScrapiClient` is deliberately pinned in code/documentation to
`draft-ietf-scitt-scrapi-11` behavior. It performs one `POST /entries`:

- `201` + Location + Receipt bytes → `REGISTERED`;
- `202` + Location → `PENDING` (no inline polling);
- `400` → `TS_REFUSED`;
- transport/other response problems → `TRANSPORT_FAILED`.

A future SCRAPI revision is an explicit adapter review, not a silent semantic
upgrade.

## Publication-result custody

`JsonlTransparencyResultSink` can retain publication metadata and the exact
returned SCITT Receipt bytes (hex-encoded) on a separate plane. Failure to write
that sidecar cannot retroactively turn an already committed SRS receipt into a
DAGR receipt failure.
