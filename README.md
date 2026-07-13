# DAGR MCP

DAGR MCP binds MCP tool execution — through the FastMCP framework — to signed,
metadata-only SRS receipt emission at a configured trust boundary.

It is a receipt **emitter / runtime binding**. It is not a verifier, gateway,
proxy, scanner, policy engine, or certification service. Admission decisions are
supplied by operator-configured resolvers; the binding records them, signs a
receipt, and — for refused or deferred dispositions — stops the call at the
boundary. Independent verification is a separate program in a separate
repository ([ARCS Verify](https://github.com/thelaplage/arcs-verify)).

<!-- layer-map -->

| Role | Surface |
|---|---|
| Standard | ARCS |
| Receipt protocol and profiles | SRS |
| Open runtime and adapters | DAGR |
| Public reference implementations | DAGR MCP and ARCS Verify |
| Public read and demo surfaces | GARPedia, Overlay, Showcase |
| Commercial operator products | Countervail, Workbench, managed deployments |

MCP is DAGR's first supported binding. This package is the public-canonical
MCP-shaped admission runtime and signed SRS emitter. It does not claim to be a
transport-neutral runtime.

## Current binding boundary

The current framework integration is **FastMCP `3.4.4`** (declared as
`fastmcp>=3.4.4,<4` in `pyproject.toml`; version measured from the installed
package). The FastMCP middleware records this binding identifier in every
receipt it emits:

- `binding_version`: **`fastmcp.middleware.v0.1`**, carried at
  `extensions.mcp.binding_version`.

The framework-specific integration (a `fastmcp` middleware and its `ToolResult`
projection) is isolated from the SRS receipt contract: the emitter in
`dagr_mcp/srs_receipts.py` constructs and signs receipts and knows nothing about
FastMCP. The registry in `docs/BINDING_VERSIONS.md` also records a
`direct-harness.v0.1` binding used by the non-framework demo path.

FastMCP is the one binding the current executable bytes and tests implement. A
multi-binding runtime is architectural / future scope; this v0.1 documentation
does not claim any other framework binding exists.

## Emit here, verify there

The emitter and the verifier are separate roles in separate repositories:

- **This repository (emit):** signs and serializes SRS receipts to files. It
  never verifies its own output.
- **[ARCS Verify](https://github.com/thelaplage/arcs-verify) (verify):** reads
  the serialized receipt bytes plus a serialized trust bundle and a pinned
  schema, and recomputes envelope, profile, raw-content, signature, key, and
  attestation results from those bytes alone.

There is no shared in-process verification: ARCS Verify imports no emitter or
producer code, and the emitter imports no verifier code. The only thing that
crosses the boundary is a serialized receipt file.

## Five-minute path

Follow **[docs/QUICKSTART.md](docs/QUICKSTART.md)**. From two clean clones it
installs this emitter and ARCS Verify into separate virtual environments, runs
the real installed `dagr-mcp` demo to produce receipts in a temporary output
directory, then independently verifies them with a separately installed
`arcs-verify` CLI. No receipt is hand-authored, no network fetch happens during
emission or verification, and no private credential is used.

## Receipt lifecycle and cardinality

The binding emits two receipt **kinds**:

- `admission` — the request snapshot and admission disposition, emitted before
  the tool handler runs (for `admitted`) or in place of it (for `refused` /
  `deferred_for_review`).
- `outcome` — the observed boundary result, emitted after the handler returns.

Receipt count is **per disposition and outcome**, not a fixed two-per-call:

| Scenario | Receipts | Kinds |
|---|---|---|
| Admitted call that runs and returns a result | 2 | `admission` (`admitted`) + `outcome` (`result_returned`) |
| Admitted call returning an error result (`isError`) | 2 | `admission` + `outcome` (`error_returned`) |
| Admitted call raising an exception | 2 | `admission` + `outcome` (`exception`) |
| Admitted call cancelled mid-flight | 2 | `admission` + best-effort `outcome` (`indeterminate`) |
| Admitted call returning a task submission | 2 | `admission` + `outcome` (`task_submitted`) |
| Refused by admission policy | 1 | `admission` (`refused`) |
| Deferred for review | 1 | `admission` (`deferred_for_review`) |
| Read call with pre-execution admission disabled by config | 0 | none |

The default demo path is an admitted read that runs, so it emits **two**
receipts. Do not assume every invocation always emits two receipts — refusals
and deferrals emit one, and an outcome-sink failure after execution leaves the
admission receipt standing plus a local `receipt_gap` event rather than
fabricating an outcome.

### Linkage

In the two-receipt case, the `outcome` receipt links to its `admission` receipt
through the `admission_receipt_ref` field (it holds the admission `receipt_id`).

A separate top-level `parent_receipt_ref` field is emitted **only** when the
deployment configures one (`DAGRMiddlewareConfig.parent_receipt_ref` or a
policy-supplied value), which is how deliberately linked boundaries (mounted or
proxy deployments) are distinguished from accidental duplicates. The demo does
not configure it, so demo receipts carry no `parent_receipt_ref`.

## Emitter coverage table

Fields below are the exact names the emitter writes. Conditions are what current
bytes produce.

| Field | Value / condition |
|---|---|
| `receipt_version` | `srs.core.v5.1` (always) |
| `profile_id` / `profile_version` | `srs.mcp.sdk_enforcement` / `v0.1` (always) |
| `protocol_binding` / `boundary_type` | `mcp` / `mcp_tool_call` (always) |
| `extensions.mcp.binding_version` | `fastmcp.middleware.v0.1` for the FastMCP path (always for that binding) |
| `runtime_instance_id`, `boundary_id` | operator-configured boundary identifiers (always) |
| `logical_call_id`, `subject_ref` | scoped, hash-derived call/subject references (always) |
| `receipt_kind` | `admission` or `outcome` |
| `disposition` | `admitted` / `refused` / `deferred_for_review` (admission receipts) |
| `outcome` | `result_returned` / `error_returned` / `exception` / `indeterminate` / `task_submitted` (outcome receipts) |
| `admission_receipt_ref` | present on `outcome` receipts; links to the admission `receipt_id` |
| `parent_receipt_ref` | present only when the deployment configures a parent link; absent otherwise |
| `attestation_limits` | non-empty list of limit strings (see below) |
| `argument_digest`, `result_digest` | `sha256:` digests of hashed projections; never raw arguments or results |
| `reason_code` | present on refused/deferred admission receipts when set (e.g. `policy_refused`, `review_object_creation_failed`) |
| `extensions.mcp.exception_class` | exception class name only, on `exception` outcomes |
| `artifact_classes_excluded` | `raw_prompt`, `raw_output`, `raw_tool_arguments`, `raw_tool_result` (always) |
| `retention_class_applied` | `hash_only` (always) |

## Attestation limits

`attestation_limits` is always present and holds non-empty strings. It starts
with the base limit and accumulates limits that apply to the specific receipt:

- Base (every receipt): *"The receipt attests only to governance conditions at
  the named admission boundary."*
- Result outcomes (`result_returned` / `error_returned`) add a limit stating the
  receipt establishes the request, admission disposition, and semantic result at
  the boundary, and does **not** independently establish that the underlying
  tool body ran for that invocation (a downstream cache may satisfy a call
  without handler execution).
- Task submissions (`task_submitted`) add a limit stating the receipt covers
  admission and submission only, not execution or completion.
- The FastMCP middleware adds an installed-at-the-boundary limit by default.

These limits constrain what the receipt asserts. The receipt does not prove more
than the limits it declares.

## Raw-content discipline

Receipts are metadata-only and hash / reference based. The emitter enforces this
at signing and at write time (`enforce_raw_content_exclusion`): a fixed set of
raw-content and credential keys (tool arguments, result bodies, prompts,
transcripts, passwords, tokens, private keys, and similar) is rejected, and
private path markers are rejected. Arguments and results appear only as
`sha256:` digests of canonicalized projections; `retention_class_applied` is
`hash_only` and the four raw artifact classes are listed under
`artifact_classes_excluded`.

No passwords, tokens, payload bodies, or governed raw content are written to
receipts, trust bundles, or gap spools. The signature covers the RFC8785-JCS
canonical preimage of the receipt, so a receipt that verifies is the receipt as
signed under the resolved key; ARCS Verify recomputes that from the serialized
bytes.

## Verification-result semantics

When ARCS Verify checks a serialized receipt it reports **eight Boolean
results** and, separately, a `chain_status` string. The eight Booleans (in the
verifier's report order) are:

`schema_digest`, `envelope`, `profile`, `raw_content_exclusion`,
`signature_valid`, `issuer_key_resolved`, `issuer_key_trusted`,
`attestation_limits_present`.

See the [ARCS Verify README](https://github.com/thelaplage/arcs-verify) for the
exact meaning of each. `chain_status` is reported **separately** and is not a
ninth Boolean; for a standalone receipt it is `not_applicable`, which is **not**
a PASS — it means no cross-artifact chain was in scope. A clean acceptance is
therefore *eight Boolean results true plus `chain_status: not_applicable`* — not
"nine" of anything.

## Limitations

- A valid signature proves the receipt was issued and unmodified under the
  resolved trusted key. It does **not** prove the underlying tool result was
  truthful, nor that the described real-world event occurred.
- The runtime receipts observe only tool calls that pass through the wrapped
  middleware at the configured boundary. They do not observe MCP traffic that
  bypasses that path, and the binding is not a network proxy or a gateway.
- Coverage is limited to the execution paths the current code actually wraps.
- This binding is not a gateway, proxy, RBAC system, or policy engine, and it
  issues no certification or comparative claim about any implementation.

## Development

Requires Python **3.11 or newer** (`requires-python = ">=3.11"`).

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q                       # 158 tests
python tools/check_public_release.py .    # public-release / producer-independence guard
```

`tools/check_public_release.py` is the public-release guard: it rejects private
paths, internal reviewer references, private import roots, forbidden raw-content
keys in fixtures, and withdrawn claim language, and it enforces the
producer-independence and layer-map invariants used at launch.

## Naming

This repository does not select a final published distribution / install name.
The current project and import names (`dagr-mcp` / `dagr_mcp`) are reported as
current byte facts, but the eventual package-index install command
(`pip install @@RUNTIME_DISTRIBUTION@@`) is resolved in one substitution step at
launch. See [docs/NAMING.md](docs/NAMING.md). The quickstart installs from the
source clone and needs no package name.
