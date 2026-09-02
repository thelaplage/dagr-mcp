# Vendored `dagr_sdk` caller-auth-context conformance fixtures

Mirrors the existing `arcs-srs` -> `arcs-verify` commit-pinned vendoring
pattern (`tools/vendor/arcs-verify-<commit>.tar` in `arcs-srs`): DAGR-MCP
consumes the canonical, `dagr-sdk`-owned `CallerAuthContext` wire contract's
committed conformance manifest and v0.1 golden vectors so the cross-language
specimen test (`tests/test_caller_principal.py::test_golden_vector_survives_wire_to_dagr_mcp_policy_resolver`)
does not depend on the *installed* `dagr-sdk` distribution shipping its
`tests/` directory (it does not — its `pyproject.toml` packages only
`dagr_sdk*` / `garp_sdk*`).

- Source repository: `https://github.com/thelaplage/dagr-sdk`
- Source commit: `f11fbf817ea3b4af150e15effae9448c470e247d`
- Source paths:
  - `manifests/caller_auth_context.v0.1.json`
    (sha256:45ba593b7368196c4e35998092b2301c79b42dfe0e7d199e098c89a6f15f8d50)
  - `tests/fixtures/caller_auth_context/v0.1.vectors.json`
    (sha256:012943148399b634bad0faf7e0ee650e79085ae8d72a5daa1e6033082952d0b1)

These are byte-identical copies. `dagr_sdk.caller_auth_context.CallerAuthContext`
remains the sole authority for the contract itself; nothing here re-derives,
re-validates, or reinterprets it. Bump this vendor pin only alongside the
`dagr-sdk` dependency pin in `pyproject.toml`.
