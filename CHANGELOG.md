# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
The versioning policy is described in [docs/VERSIONING.md](docs/VERSIONING.md).

## [0.1.0] - Unreleased

The release date is intentionally unset. A date is assigned only by the P4 /
go-day tagging commit that creates the `v0.1.0` tag. The version recorded here
and in package metadata does not by itself mean that a tag, a release, or public
availability exists.

### Added
- Second lifecycle binding over the official Python MCP SDK
  (`dagr_mcp_sdk_binding`, binding version `official-mcp-sdk.python.v0.1`),
  binding the `mcp.server.lowlevel.Server` call-tool handler seam onto the
  Sprint A3 neutral lifecycle core. The FastMCP binding remains the default and
  is unchanged. Includes an official-SDK binding mask, a supported server
  construction surface, and a cross-binding conformance corpus proving both
  bindings agree on every binding-neutral semantic field (the only permitted
  difference is the intentionally-distinct binding-version stamp). The `mcp`
  dependency is declared as the optional `official-sdk` extra; the receipt
  schema/profile is unchanged. See
  [docs/OFFICIAL_MCP_SDK_BINDING.md](docs/OFFICIAL_MCP_SDK_BINDING.md).
- Public-canonical MCP admission runtime carved from the enforcement harness:
  disposition, policy profile, matter-scope lint, sink protocols and in-memory
  sinks, the refs-only record-custody gateway, and the SRS bridge.
- Signed SRS receipt emitter producing linked **admission** and **outcome**
  receipts under `srs.mcp.sdk_enforcement.v0.1`. The default success outcome is
  `result_returned`; receipts carry only references and `sha256:` digests, never
  raw governed content.
- FastMCP middleware binding (`fastmcp.middleware.v0.1`) over the committed
  FastMCP range `fastmcp>=3.4.4,<4`, installing at the admission boundary with
  configurable admission resolvers, fail-closed/fail-open receipt-failure
  policy, and conservative cancellation handling.
- `dagr-mcp` / `dagr-mcp-demo` console commands. `dagr-mcp demo --output <dir>`
  runs an admitted read through the binding and writes the admission and outcome
  receipts plus a public trust bundle. The demo mints a fresh ephemeral Ed25519
  key per run and never serializes the private key.
- Emitted receipts verify independently under a separately installed ARCS Verify
  ([ARCS Verify](https://github.com/thelaplage/arcs-verify)): eight Boolean
  results plus a separate `chain_status`.
- Governed Amnesiac tool surface bound through the same admission runtime:
  the four MCP tools (`amnesiac.propose_candidates`, `amnesiac.record_outcome`,
  `amnesiac.request_reopening`, `amnesiac.compile_context`) in
  `dagr_mcp/amnesiac_contracts.py`, `dagr_mcp/amnesiac_stores.py`,
  `dagr_mcp/amnesiac_native.py`, and `dagr_mcp/amnesiac_fastmcp.py`. The native
  producer (`arcs-amnesiac`) is an **optional** integration installed via the
  `amnesiac` extra (`pip install 'dagr-mcp[amnesiac]'`, pulling `arcs-amnesiac`
  and `garp-sdk`); it is imported lazily and never at module load, so the base
  package's import-direction guarantee holds. Without the extra the binding
  still imports and fails closed with `capability_unavailable`. See
  [docs/AMNESIAC_TOOLS.md](docs/AMNESIAC_TOOLS.md).
- Apache-2.0 packaging metadata: the complete license text, trove classifiers,
  repository and issue URLs, and declared runtime dependencies (`cryptography`,
  `fastmcp`, `rfc8785`), plus the optional `amnesiac` extra
  (`arcs-amnesiac>=0.2.0`, `garp-sdk>=0.1.0`).

### Notes
- The final published distribution name and its install command are
  operator-gated and resolved in a single substitution step at launch; see
  [docs/NAMING.md](docs/NAMING.md). The current project name `dagr-mcp` and
  import root `dagr_mcp` are byte-grounded facts, not the final published
  distribution name.
- CI runs FastMCP 3.4.4 as the lowest supported lane and the latest released
  FastMCP 3 as a compatibility lane; FastMCP `main` is an allowed-failure canary
  and is not a supported target.
