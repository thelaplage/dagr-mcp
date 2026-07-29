# Public-export allowlist — v0.2 lane (official SDK v2 governed binding)

Every file this lane adds or touches, and its disposition for a clean public
export. Nothing in this lane's diff falls outside the allowlisted set below —
this list is exhaustive for the lane, not just representative.

`tools/check_public_release.py .` passes with 0 findings against the full
repository including every file in this lane (private-path markers, internal
reviewer names, raw-content keys, withdrawn language — none present).

## Include

### `packages/dagr-mcp-core/` — new distribution
```
pyproject.toml
README.md
LICENSE
EXTRACTION_MANIFEST.json
src/dagr_mcp_core/__init__.py
src/dagr_mcp_core/srs_receipts.py
src/dagr_mcp_core/lifecycle/__init__.py
src/dagr_mcp_core/lifecycle/contract.py
src/dagr_mcp_core/lifecycle/core.py
src/dagr_mcp_core/lifecycle/models.py
tests/receipt_verification.py
tests/test_core_standalone.py
tests/test_core_lifecycle_equivalence.py
tests/vendor/srs-envelope-v0.2.0.schema.json
```

### `packages/dagr-mcp-sdk-v2/` — new distribution
```
pyproject.toml
README.md
LICENSE
src/dagr_mcp_sdk_v2/__init__.py
src/dagr_mcp_sdk_v2/adapter.py
src/dagr_mcp_sdk_v2/result_digest.py
src/dagr_mcp_sdk_v2/server.py
tests/harness.py
tests/test_acceptance_matrix.py
tests/test_result_digest_golden.py
tests/test_input_required_fail_closed.py
tests/golden/result_digest_vectors.json
```

### `examples/http_proof_v2/` — modern stateless example
```
server.py
client_proof.py
```

### Public documentation and profiles
```
docs/CORE_EXTRACTION_FORK.md
docs/DAGR_MCP_SDK_V2_BINDING.md
docs/PUBLIC_EXPORT_ALLOWLIST_V0_2.md   (this file)
```

### Root-repo tests required to establish this lane's claims
```
tests/test_core_extraction_byte_parity.py
tests/test_http_proof_v2.py
```

### Root-repo tooling required to establish this lane's claims
```
tools/check_core_extraction_manifest.py
```

### Minimal, surgical edits to existing public files (no new exclusions introduced)
```
pyproject.toml                          -- adds `testpaths = ["tests"]` only (test-collection scoping; no dependency/import/binding-behavior change)
docs/BINDING.md                         -- adds a cross-reference paragraph
docs/BINDING_VERSIONS.md                -- adds the official-mcp-sdk.python.v0.2 registry row
docs/VERSIONING.md                      -- adds a cross-reference note
.github/workflows/test.yml              -- adds core-only / core-extraction-parity / sdk-v2 jobs
.github/workflows/package-build.yml     -- adds build-core-and-sdk-v2 job
```

## Explicitly excluded

None of these exist in, or are referenced by, any file this lane adds:

```
amnesiac_contracts.py
amnesiac_fastmcp.py
amnesiac_native.py
amnesiac_stores.py
private-engine imports
internal planning documents
retired Steiner material
Bossy-specific material
```

Confirmed by direct search: no file under `packages/`, `examples/http_proof_v2/`,
or this lane's new/edited `docs/`/`tests/`/`tools/`/`.github/` files imports
`dagr_mcp.amnesiac_contracts`, `dagr_mcp.amnesiac_fastmcp`,
`dagr_mcp.amnesiac_native`, `dagr_mcp.amnesiac_stores`, or any private-engine
module. This lane does not touch `dagr_mcp_service/` (the Gateway Service
Adapter) at all.

## Not touched by this lane (frozen, per docs/CORE_EXTRACTION_FORK.md)

```
dagr_mcp/                (root package — every file)
dagr_mcp_lifecycle/       (every file)
dagr_mcp_sdk_binding/     (official-mcp-sdk.python.v0.1 — every file)
dagr_mcp_service/         (Gateway Service Adapter — every file)
```

## Repository visibility

This lane does not flip repository visibility. It only adds public-safe
content per the checks above.
