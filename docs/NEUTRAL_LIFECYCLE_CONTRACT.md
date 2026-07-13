# DAGR MCP Neutral Lifecycle Contract — Sprint A2 (v0.1)

This document defines the **binding-neutral lifecycle vocabulary** for a governed
MCP tool call, and the **explicit mask** that maps the existing
`fastmcp.middleware.v0.1` binding onto that vocabulary.

It is the Sprint A2 companion to [`BEHAVIORAL_FREEZE.md`](BEHAVIORAL_FREEZE.md).
The freeze captured *what the FastMCP binding observably does*; this contract
names those facts in binding-neutral terms so that later bindings (and the
eventual neutral core) can be measured against one written vocabulary rather than
against the fixtures directly.

**The binding remains the oracle.** The mask *describes* the binding; it does not
normalize, repair, or change it. Where the binding has no dedicated observation
for a neutral event, the mask records that plainly rather than inventing one.

## Authority and anchoring

| Role | Value |
|------|-------|
| Required base | `9e861ad5040691944bc19e33fc60ca0c72b3fbba` (freeze commit, #7) |
| Behavioral authority | [`docs/BEHAVIORAL_FREEZE.md`](BEHAVIORAL_FREEZE.md) |
| ARCS authority (co-installed, unmodified) | `da89ebe36f1e4d9921aeeb7ff12f377d6804e8f7` |

Every claim below is derived from the current repository bytes — the
`dagr_mcp.fastmcp_binding` middleware, the `dagr_mcp.srs_receipts` emitter, the
`dagr_mcp.mcp_record_custody_gateway` projection, and the committed
behavioral-freeze fixtures under `tests/golden/behavioral_freeze/`. If this
document and the code disagree, the committed tests and goldens are authoritative
and this document is the defect.

## Scope discipline

This sprint adds a contract and a mask; it changes no binding behavior.

- **No core extraction.** No implementation was moved or lifted into a core.
- **No implementation file moves.** The binding modules are byte-unchanged.
- **No second binding, no public API replacement.** The `dagr_mcp` package
  surface is byte-identical; the frozen public-API snapshot
  (`public_api_surface.json`) is untouched. The neutral vocabulary and mask live
  in a *separate* top-level package, `dagr_mcp_lifecycle`, precisely so the
  frozen `dagr_mcp` surface stays frozen and the neutral contract does not live
  inside the binding it describes.
- **No receipt schema or profile bump, no golden digest changes, no signing-byte
  changes, no `arcs-verify` changes, no TypeScript binding.**
- **No semantic repair hidden in the contract.** Every mask entry that does not
  correspond to a dedicated binding disposition is marked `subsumed` or
  `unsupported`, never silently mapped to something adjacent.

## Modules and grounding

| Module | Role |
|--------|------|
| `dagr_mcp_lifecycle/contract.py` | The binding-neutral vocabulary. Imports nothing from `dagr_mcp`. |
| `dagr_mcp_lifecycle/binding_mask.py` | The mask that maps the live binding onto the vocabulary; reads binding-side values back from `dagr_mcp` so it cannot drift. |
| `tests/test_neutral_lifecycle_contract.py` | Grounds every mask claim against a live emitter run and the committed freeze fixtures. |

`binding_mask.verify_mask_matches_binding()` is the drift guard: it reads only
from the live binding modules and fails if the mask has drifted from them.

---

## 1. Call admission

A governed call is evaluated at the boundary **before the tool body runs**. The
neutral admission dispositions are exactly:

```
contract.NEUTRAL_DISPOSITIONS == ("admitted", "refused", "deferred")
```

The mask projects them onto the binding's `Disposition` Literal
(`typing.get_args(fastmcp_binding.Disposition)`):

| Neutral disposition | Binding token | Status |
|---------------------|---------------|--------|
| `admitted` | `admitted` | direct |
| `refused` | `refused` | direct |
| `deferred` | `deferred_for_review` | direct |

`deferred` is the neutral name the binding spells `deferred_for_review`; the
mask records that name difference explicitly. Admission never observes tool
resolution — every admission record carries `tool_resolution_status =
"not_observed"`.

## 2. Admitted, refused, and deferred dispositions

- **Admitted** — an admission record is written before execution for governed
  classes, and the call proceeds to an outcome (§3–4).
- **Refused** — a single terminal refused admission record; the binding raises
  `ToolError` and the inner handler never runs.
- **Deferred** — a deferred admission record carrying a `review_object_ref` and
  `retry_contract`. A deferral is **not** a refusal: it carries no `reason_code`
  and instead offers a continuation contract.

Neutral refusal grounds and the binding `reason_code` each maps to:

| Neutral ground | Binding `reason_code` | When |
|----------------|-----------------------|------|
| `policy_refused` | `policy_refused` | explicit deny policy |
| `unknown_tool_fail_closed` | `unknown_tool_fail_closed` | no policy resolves the tool; fail closed |
| `required_sink_unavailable` | `required_sink_unavailable` | a required (or effectively-required) sink is missing at the pre-gate health check |
| `review_object_creation_failed` | `review_object_creation_failed` | a review sink is present but raises during creation |

The `required_sink_unavailable` / `review_object_creation_failed` asymmetry is
the recorded residual in `BEHAVIORAL_FREEZE.md` §17; the mask preserves it rather
than smoothing it over.

The deferral continuation contract is:

```
contract.DEFERRAL_CONTINUATION_CONTRACT == "retry_after_approval"
```

## 3. Execution start and completion

Admission for a governed class is durably observed **before** execution
(`execution_start`); the boundary observes the call returning or terminating
**after** (`execution_completion`).

```
contract.EXECUTION_BOUNDARIES == ("execution_start", "execution_completion")
```

These are phase boundaries at the middleware, not a claim that the underlying
tool body ran for this invocation — a downstream cache may satisfy a call without
handler execution (see the result attestation limit, §8).

## 4. Result, error, exception, task-submitted, timeout, and cancellation mapping

The neutral terminal outcomes are:

```
contract.NEUTRAL_OUTCOMES == (
    "result", "error", "exception", "task_submitted",
    "timeout", "cancellation", "input_required",
)
```

The mask projects each onto the binding. The complete set of outcome tokens the
emitter can stamp is:

```
binding_mask.BINDING_OUTCOME_TOKENS == {
    "result_returned", "error_returned", "exception",
    "task_submitted", "indeterminate",
}
```

grounded by driving the live emitter and collecting every `outcome` field.

| Neutral outcome | Binding token | Status | Result digest | Notes |
|-----------------|---------------|--------|---------------|-------|
| `result` | `result_returned` | direct | present | `ToolResult`, `isError=False` |
| `error` | `error_returned` | direct | present | `ToolResult`, `isError=True` |
| `exception` | `exception` | direct | absent | inner raise; `exception_class` only |
| `task_submitted` | `task_submitted` | direct | absent | a `CreateTaskResult`; submission only |
| `timeout` | `exception` | **subsumed** | absent | no dedicated disposition — see below |
| `cancellation` | `indeterminate` | direct | absent | cooperative cancel; §6 governance facts |
| `input_required` | *(none)* | **unsupported** | — | §5 |

**Timeout is subsumed, not distinct.** There is no dedicated timeout branch in
the binding. A raised `TimeoutError` is an ordinary inner exception and is
recorded as `outcome = "exception"` with
`extensions.mcp.exception_class = "TimeoutError"`. The committed `outcome-exception`
golden literally uses `exception_class = "TimeoutError"`, so this is a signed,
byte-frozen fixture. Cooperative cancellation (`asyncio.CancelledError`) is a
*distinct* path that maps to `indeterminate`.

The task-result type the binding recognizes is read from
`fastmcp_binding.CREATE_TASK_RESULT_IMPORT_PATH` (`mcp.types.CreateTaskResult` at
FastMCP 3.4.4).

## 5. Continuable / interrupted `input_required`

`input_required` is part of the neutral vocabulary, with two modes:

```
contract.INPUT_REQUIRED_MODES == ("continuable", "interrupted")
```

- **continuable** — a call that pauses awaiting further input and can be resumed.
- **interrupted** — a call that stops awaiting input without a resumable
  continuation.

**Both modes are `unsupported` in this binding.** The FastMCP binding has no
elicitation or continuation branch; it carries no dedicated disposition for a
paused call. Anything the boundary happens to return as a `ToolResult` would be
classified by its `isError` flag as `result_returned` / `error_returned` — it
would *not* be distinctly recognized as a continuation. The mask records this as
`unsupported` rather than masking a paused call onto a returned result.

## 6. Cancellation governance facts

Cooperative cancellation (`asyncio.CancelledError`) maps to the `indeterminate`
outcome carrying three neutral governance facts:

```
contract.NEUTRAL_CANCELLATION_FACTS == (
    "request_cancelled", "execution_state_unknown", "delivery_incomplete",
)
```

The mask binds these to the binding-owned field registry
`srs_receipts.CANCELLATION_FIELD_NAMES`. They are constrained by the emitter,
**before signing and writing nothing**:

- **Indeterminate-only** — a cancellation field on any non-`indeterminate`
  outcome raises `ReceiptContentError` ("only on indeterminate").
- **Boolean-only** — a non-Boolean cancellation value raises
  `ReceiptContentError` ("must be boolean").

`delivery_incomplete` is deliberately **not** named with a `result`-shaped token:
an ARCS raw-content profile rejects any `result`-shaped key, so a `result_*`
governance field would collide with raw-content exclusion even though its value
is a governance Boolean. The A0 rename holds — no `result`-shaped governance
field survives.

## 7. Receipt cardinality and parent / reference relationships

The neutral count of durable governance records per disposition:

```
contract.RECEIPT_CARDINALITY == {"admitted": 2, "refused": 1, "deferred": 1}
```

- An **admitted** call emits exactly two records: the admission record (written
  before the inner handler runs) then the outcome record.
- A **terminal refusal** and a **deferral** each emit exactly one record; the
  inner handler never runs.

Reference edges:

```
contract.RECEIPT_REFERENCE_EDGES == ("outcome_to_admission", "parent_reference")
```

- `outcome_to_admission` — every outcome record's
  `admission_receipt_ref` (`binding_mask.OUTCOME_TO_ADMISSION_FIELD`) equals the
  admitting admission record's `receipt_id`. In the committed fixtures all five
  outcomes reference `urn:srs:receipt:admission:freeze-admitted`.
- `parent_reference` — an admission record may carry `parent_receipt_ref`
  (`binding_mask.PARENT_REFERENCE_FIELD`) when boundaries are deliberately linked
  (mounted or proxy deployments).

## 8. Custody observations and attestation limits

Custody observation is a **non-claim posture**: the boundary records that it
observed a call and excluded raw content, without asserting authority over, or
modification of, the protocol or the model output. The mask binds the neutral
flag names to the identically-named custody-gateway fields:

- Exclusion flags, all `True`:
  `contract.CUSTODY_EXCLUSION_FLAGS` = `raw_payload_excluded`,
  `private_path_redacted`, `tool_arguments_excluded`, `credential_secret_excluded`.
- Non-claim flags, all `False`:
  `contract.CUSTODY_NON_CLAIM_FLAGS` = `record_admission_claimed`,
  `mcp_protocol_modified`, `mcp_authority_granted`, `model_output_verified`.

The custody vocabulary sizes are pinned against the gateway enums: **9** custody
statuses, **4** boundary types, **3** receipt families
(`GatewayCustodyStatus` / `GatewayBoundaryType` / `GatewayReceiptFamily`). The
gateway schema is `garp.mcp_record_custody_gateway.v0.1`, and it introduces no
new SRS receipt family.

Neutral attestation-limit families bind to the exact binding strings:

| Family | Binding string source | Applies to |
|--------|-----------------------|------------|
| `base` | `srs_receipts.BASE_LIMIT` | every record |
| `result` | `srs_receipts.RESULT_LIMIT` | `result` / `error` outcomes |
| `task` | `srs_receipts.TASK_LIMIT` | `task_submitted` outcome |
| `boundary` | `fastmcp_binding.DEFAULT_BOUNDARY_LIMIT` | records at the middleware boundary |

The base limit is on every record; the result limit only on result/error; the
task limit only on task-submission — grounded against the committed fixtures.

## 9. Argument and result digest responsibilities

Digests are hash-only projections.

```
contract.DIGEST_CANONICALIZATION == "RFC8785-JCS"   # == srs_receipts.CANONICALIZATION
contract.DIGEST_PREFIX          == "sha256:"
```

- **Argument digest** — `sha256_digest(x)` canonicalizes `x` with RFC 8785 JCS
  and prefixes `sha256:`. It is key-order independent and of length
  `len("sha256:") + 64`. It is always present on an admission record.
- **Result digest** — `fastmcp_tool_result_digest(...)` digests the exact
  four-member `fastmcp.tool_result.v1` projection, in this key order:

  ```
  binding_mask.FASTMCP_RESULT_PROJECTION_KEYS ==
      ("content", "structuredContent", "_meta", "isError")
  ```

  The binding path and the receipt path agree:
  `sha256_digest(project_fastmcp_tool_result(r))` equals
  `fastmcp_tool_result_digest(...)` for the same result. The result digest is
  present only for `result` / `error`, and **absent** for `task_submitted`,
  `exception`, `timeout`, and `cancellation`
  (`contract.NO_RESULT_DIGEST_OUTCOMES`).

## 10. Protocol and binding stamps

Every record carries stamps identifying the protocol it governs and the binding
that produced it. The mask reads these from the binding constants (and verifies
the three inline emitter literals against an emitted record):

```
binding_mask.PROTOCOL_STAMPS == {
    "protocol_binding": "mcp",
    "boundary_type": "mcp_tool_call",
    "receipt_type": "sdk_enforcement",
    "profile_id": "srs.mcp.sdk_enforcement",
    "profile_version": "v0.1",
    "receipt_version": "srs.core.v5.1",
}
binding_mask.BINDING_STAMPS   == {"binding_version": "fastmcp.middleware.v0.1"}
binding_mask.SIGNATURE_STAMPS == {"algorithm": "Ed25519", "canonicalization": "RFC8785-JCS"}
```

`binding_version` is the live `fastmcp_binding.BINDING_VERSION`, and it is one of
the registered binding versions
(`srs_receipts.REGISTERED_BINDING_VERSIONS`). `retention_class_applied` is
`hash_only`.

## 11. Unsupported lifecycle events

The mask names two classes of neutral events the binding does not carry as
dedicated dispositions, and it says which is which:

- **`subsumed`** — `timeout`. Observed, but recorded onto the `exception` token
  (with the raised class), not a dedicated timeout disposition (§4).
- **`unsupported`** — `input_required` in both `continuable` and `interrupted`
  modes. No observation, no dedicated token (§5).

Nothing is silently mapped: a subsumed event names the token it is recorded onto,
and an unsupported event carries `binding_token = None`.

---

## The three-layer parity model

A binding claiming parity with another is compared at one of three nested,
increasingly strict layers. A parity claim **must state which layer it is made
at**.

```
contract.PARITY_LAYERS == ("semantic", "normalized_equality", "exact_unsigned_bytes")
```

### Layer 1 — semantic parity

The behavioral facts that hold independent of exact bytes: the disposition and
outcome vocabularies (§1, §4), receipt cardinality and reference edges (§7), the
cancellation-fact posture (§6), the digest responsibilities (§9), the non-claim
custody posture (§8), and the protocol and binding stamps (§10). This is the
portable contract any binding must satisfy. Permitted differences: none at this
layer beyond naming (the mask records naming differences explicitly).

### Layer 2 — normalized equality with explicit permitted differences

A record is byte-for-byte equal under RFC 8785 canonicalization once the
permitted-volatile fields are dropped:

```
contract.PERMITTED_NORMALIZED_DIFFERENCE_FIELDS ==
    ("receipt_id", "issued_at", "receipt_signature")
```

Only those three fields — identifier, wall clock, signature — may legitimately
differ across independent emitters. `binding_mask.normalized_projection(...)`
drops exactly these. A live-clock / live-UUID emit of the admitted admission
record is normalized-equal to the committed golden while its `receipt_id`
genuinely differs. For custody projections the single permitted-volatile field is
`observed_at`.

### Layer 3 — exact RFC 8785 unsigned-envelope bytes where deterministic

The exact RFC 8785 canonical bytes of the **unsigned envelope** — the record with
its `receipt_signature` block removed — are identical wherever the producing
identity, identifier, and clock are pinned.
`binding_mask.unsigned_envelope_bytes(...)` computes them. Regenerating the frozen
receipt set reproduces each committed golden's unsigned-envelope bytes exactly.
This is the strictest layer and holds only for the deterministic fixtures
(fixed Ed25519 seed, pinned id and clock); it does not hold where a live signature
or clock legitimately varies — that is what Layer 2 is for.

---

## Verification

Run 2026-07-13 against base `9e861ad`. Environment: **Python 3.14.5, FastMCP
3.4.4, cryptography 46.0.7, rfc8785 0.1.4**; co-installed lane adds
**arcs-verify 0.1.1 @ `da89ebe`, arcs-amnesiac 0.2.0, garp-sdk 0.1.0**.

| Lane | Command | Result |
|------|---------|--------|
| Standalone DAGR | `python -m pytest -q` | `247 passed, 18 skipped` |
| Co-installed DAGR | `python -m pytest -q` | `287 passed` |
| Neutral contract suite | `python -m pytest -q tests/test_neutral_lifecycle_contract.py` | `17 passed` |
| Canonical ARCS (unmodified `da89ebe`) | `(cd ../arcs-verify && python -m pytest -q)` | `108 passed` |
| Public-release scan | `python tools/check_public_release.py .` | `PASS: 0 finding(s)` |
| Package build | `python -m build` + `twine check dist/*` | built + `PASSED` |

The standalone and co-installed suites each grew by the **17** new contract tests
(230 → 247 standalone, 270 → 287 co-installed). No pre-existing test changed, and
the frozen public-API snapshot, golden digests, and signing bytes are unchanged.
