# CLAUDE.md
> Status: agent guidance only; non-normative. Repository contracts, cited authorities, and admitted artifacts control where they differ.

## Repository lifecycle
ACTIVE

## Ecosystem rule
One authority per contract family. If another repository owns a contract, profile, schema, verifier, semantic rule, or custody invariant, consume or pin that authority. Do not recreate a convenient local dialect.

## Cross-repository evidence rule
A green local test suite does not prove interoperability. Where this repository consumes another repository's artifact, tests should use literal output from the real producer at a pinned commit whenever practical, preserving original bytes and provenance.

## Repository role
dagr-mcp is a producer of runtime SRS receipts: it emits signed SRS envelopes conformant to the profiles arcs-srs defines, and records refusal / non-execution evidence. It owns emission, not meaning or verification.

## Authority boundary
AUTHORITATIVE FOR:
- Producer-side receipt emission and signing
- Per-profile identity constants and vendored SRS vectors it pins
- Refusal / non-execution evidence (e.g. child-zero sentinels)

NOT AUTHORITATIVE FOR:
- SRS serialization / profile definitions (arcs-srs)
- Independent verification (arcs-verify)
- Semantic truth, custody, admission

## Upstream authorities
- SRS profiles / envelopes / vectors -> arcs-srs (pin the profile digest; vendor the vectors)
- Semantic rules -> garp-doctrine

## Downstream consumers
- arcs-verify -> independently verifies the literal receipts emitted here
- counterpedia-agent, dagr-ops, dagr packs -> drive emission through the real middleware

## Critical invariants
- emitting a receipt != verifying it != it being true
- a verifier reference is not a verification
- refused/failed execution must be represented honestly, never as success

## Repository-specific red lines
- NEVER import arcs-verify or copy verifier logic — issuer/verifier separation is inviolate.
- Per-profile identity constants; never widen a single global PROFILE_ID to cover a second profile.
- Do not reinterpret SRS semantics locally; vendor and pin from arcs-srs.

## Required validation
- `python -m pytest` (full suite) green

## Related repositories
- arcs-srs — SRS profile / serialization authority (upstream)
- arcs-verify — independent verifier of emitted receipts (never imported here)
- garp-doctrine — semantic authority
- arcs-srs-store — custody
