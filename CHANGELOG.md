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
- `dagr_mcp_service.connectors.stdio`, a **generic governed
  one-shot/restart-safe stdio MCP connector v0.1** for external MCP servers:
  launches an operator-configured child
  command (explicit argv, additive-only environment) and speaks the standard
  MCP stdio `initialize` / `tools/list` / `tools/call` lifecycle to it over
  the same pinned `mcp` client the remote connector already uses, without
  importing or forking the child server's implementation. Plugs into the
  existing, frozen `connector.resolve(target_handle, tool_name)` seam with no
  change to `dagr_mcp_service.adapter`, `contract.py`, or either lifecycle
  binding — a refused or deferred call never reaches the child, an admitted
  call is forwarded exactly once, and every call is an independent
  spawn/negotiate/call/teardown cycle with no long-lived child process and no
  orphan left behind. Because each call is one-shot, MCP servers requiring
  long-lived session state, server subscriptions, persistent server-side
  resources, cross-call initialization state, or retained sampling roots are
  unsupported in v0.1 and recorded as future scope. After a call has been
  forwarded, a timeout, cancellation, child exit, malformed response, or
  connection close may leave the external side effect uncertain:
  `outcome="exception"` records that the transport or tool result was not
  successfully observed and does not prove the side effect did not occur;
  the `remote_unavailable` diagnostic is structurally reachable only from
  the pre-spawn path. See `dagr_mcp_service/connectors/stdio.py` and
  `docs/GATEWAY_SERVICE_ADAPTER_SCOPE.md`'s §13/§15 update note.
- `subject_ref_origin` disclosure on the `official-mcp-sdk.python.v0.2` binding
  path, carried into `dagr-mcp-core` and `dagr-mcp-sdk-v2` when the SDK-v2 work
  was reconciled onto the base that introduced the field. Four of the five
  vocabulary classes are structurally reachable on this path and each is proved
  at the binding's own decision branch; `derived_from_session` is structurally
  **unreachable** and documented as such, because protocol `2026-07-28` is a
  self-contained POST with no `initialize` handshake and no `Mcp-Session-Id`,
  and the SDK's `ServerSession` exposes no session identifier for a session
  branch to read. The binding declares no session origin rather than
  substituting another class for it. `SdkV2BindingConfig` gains the
  `subject_ref_override` and `logical_call_id_override` fields the FastMCP and
  v0.1 SDK bindings already carry, with identical precedence.
- Optional `subject_ref_origin` disclosure on emitted receipts, from the closed
  five-value SRS envelope v0.2.1 vocabulary (`supplied_subject`,
  `derived_from_session`, `derived_from_request`,
  `derived_from_supplied_correlation`, `binding_minted`). Every emitter path —
  the direct-harness bridge, the FastMCP binding, and the official-SDK binding —
  declares it at its own decision branch, so a receipt states how its subject
  reference was actually obtained rather than leaving it to be inferred. No
  fallback and no subject-reference or logical-call behavior changed; the field
  is purely additive. A value outside the vocabulary is refused before signing
  rather than degraded into absence, and `not_declared` is a reader rendering of
  a genuinely absent field, never an emitted value. The v0.2.1 envelope schema is
  vendored alongside the retained v0.2.0 pin
  (`srs-envelope@0.2.1+sha256:2afa1ec9f093fd7c06c4f5db7bfd37cc63e64e3dcbe47c963f4df586a1c18ca1`)
  and is the schema emitted envelopes are validated against for this field;
  receipts declare no envelope schema version of their own.
- Second lifecycle binding over the official Python MCP SDK
  (`dagr_mcp_sdk_binding`, binding version `official-mcp-sdk.python.v0.1`),
  binding the `mcp.server.lowlevel.Server` call-tool handler seam onto the
  Sprint A3 neutral lifecycle core. The FastMCP binding remains the default and
  is unchanged. Includes an official-SDK binding mask, a supported server
  construction surface, and a cross-binding conformance corpus proving both
  bindings agree on every binding-neutral semantic field (the only permitted
  difference is the intentionally-distinct binding-version stamp). One lifecycle
  state is an explicit **binding capability difference**: `task_submitted` — the
  `mcp.types.CreateTaskResult` type exists, but it is not a genuine result of the
  bound `tools/call` client seam (which parses responses as `CallToolResult`), so
  the official-SDK binding marks it unsupported and fails closed rather than
  coercing it; the FastMCP `task_submitted` behavior is unchanged, and the
  cross-binding corpus records the difference. The `mcp` dependency is declared as
  the optional `official-sdk` extra **pinned to the exact proven version
  `mcp==1.28.1`** (the only version exercised against the binding, its mask, the
  real in-process transport, and the cross-binding corpus); the receipt
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
