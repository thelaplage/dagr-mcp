# Vendored: arcs-srs `srs.activity.governed_read.v0.1` (frozen contract)

These three files are copied verbatim from the (still unmerged) arcs-srs PR #34
so the dagr-mcp issuer test suite can assert its emitted receipts structurally
match the frozen schema and the golden vectors WITHOUT importing arcs-verify.

- Source repo: arcs-srs
- Branch: `feat/srs-activity-governed-read-schema-v0-1`
- Head: `47c95f8`

Files:
- `schema.json`          — `schemas/activity-profiles/v0.1/srs.activity.governed_read.v0.1.schema.json`
- `golden-admitted.json` — `conformance/profiles/srs.activity.governed_read.v0.1/fixtures/valid/governed-read-admitted.json`
- `golden-refused.json`  — `conformance/profiles/srs.activity.governed_read.v0.1/fixtures/valid/governed-read-refused.json`

REBASE ACTION: when arcs-srs #34 merges, re-vendor these from the merged commit
and update the head SHA above. This is the ISSUER side only; independent
verification of these receipts is arcs-verify's job (ACT3 lane 3), never here.
