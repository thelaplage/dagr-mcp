# DAGR MCP Behavioral Freeze — Sprint A1 Durable Contract

This document is the durable, human-readable contract for the DAGR MCP binding's
**observable behavior** as frozen in Sprint A1 (multi-binding behavioral freeze).
It exists so that Sprint A2 (neutral lifecycle contract / core extraction) and any
later cross-binding parity work can be measured against a single written baseline
without re-reading the fixtures each time.

Every statement below is **derived from the committed characterization tests and
golden fixtures**, not from intent. Where a statement is frozen, the exact test
function and/or golden file that pins it is named. If the code and this document
ever disagree, the committed tests and goldens are authoritative and this document
is the defect.

**Scope discipline.** The freeze captured behavior; it did not refactor it. No
production module was modified, no neutral core was invented, no implementation
file moved, no public interface was renamed, and no receipt semantics, projection
identifiers, golden digests, or signing bytes changed. The A1 diff is `tests/`
only. This document adds no source, changes no bytes, and touches no identifiers.

---

## 1. Anchoring SHAs

| Role | SHA |
|------|-----|
| **A0 base** (required base of PR #7) | `1a7ec47546ba54f3521870f35ac4f78b803fa84c` |
| **A1 head** (this freeze) | `d4f81a2a7a7168026bbdfa2bed8b5e8a7728eb6f` |
| **ARCS authority** (`arcs-verify`, co-installed, unmodified) | `da89ebe36f1e4d9921aeeb7ff12f377d6804e8f7` |

A0 (`1a7ec47`, "rename result-shaped delivery status and restore ARCS
verification", #6) is the merge that renamed the delivery governance field and
that the ARCS authority `da89ebe` guard was written against. A1 (`d4f81a2`) is the
characterization-only freeze commit that this document contracts.

`arcs-verify da89ebe` is the *authority* for freeze items 14 and 15: it supplies
the `srs.mcp.sdk_enforcement.v0.1` verifier and the non-Boolean governance-field
guard. It is co-installed, never modified.

---

## 2. Admission disposition matrix

Frozen by `test_freeze_disposition_vocabulary`,
`test_freeze_admission_receipts_carry_frozen_dispositions`, and the reason-code
tests in the item-2 section.

The admission-disposition vocabulary is exactly:

```
fastmcp_binding.Disposition = ("admitted", "refused", "deferred_for_review")
```

The tool-class vocabulary the FastMCP binding admits against is exactly:

```
fastmcp_binding.ToolClass = ("read", "write", "destructive")
```

Every admission receipt carries `receipt_kind = "admission"` and
`tool_resolution_status = "not_observed"` — admission never observes tool
resolution.

| Trigger | `disposition` | `reason_code` | Other frozen fields | Pinned by |
|---------|---------------|---------------|---------------------|-----------|
| Policy `deny` | `refused` | `policy_refused` | — | `test_freeze_reason_code_deny` |
| Unknown tool (no matching policy) | `refused` | `unknown_tool_fail_closed` | fail-closed | `test_freeze_reason_code_unknown_tool_fail_closed` |
| `gate` + `review_required`, **review sink present** | `deferred_for_review` | — | `retry_contract = "retry_after_approval"`, `review_object_ref` set | `test_freeze_deferral_reason_and_retry_contract` |
| `gate` + `review_required`, **review sink absent** | `refused` | `required_sink_unavailable` | `GovernedResult.failure_reason = "review_object_sink_unavailable"` | `test_freeze_gate_without_review_sink_reason_code` |
| `allow` | `admitted` | — | proceeds to outcome (§4) | `test_freeze_admission_receipts_carry_frozen_dispositions`, `test_freeze_admitted_call_emits_two_receipts_admission_then_outcome` |

The three admission dispositions are additionally frozen as committed signed
fixtures: `admission-admitted`, `admission-refused`, `admission-deferred` (§11).

---

## 3. Refusal and deferral reason codes

Frozen by the item-2 tests above. The reason-code vocabulary observed at the
admission boundary is:

- **`policy_refused`** — explicit `deny` policy.
- **`unknown_tool_fail_closed`** — no policy resolves the requested tool; the
  binding fails closed rather than admitting.
- **`required_sink_unavailable`** — a required sink (including a review sink made
  effectively-required by a `review_required` gate) is unavailable at the health
  check that runs *before* gating. See §16 (residual).
- **Deferral** is not a refusal: it emits `disposition = "deferred_for_review"`
  with `retry_contract = "retry_after_approval"` and a `review_object_ref`.

`review_object_creation_failed` is **not** reachable via a *missing* review sink;
it is reachable only via a review sink that is *present but raises*, which is
covered outside this freeze by `tests/test_srs_receipts.py`. This asymmetry is the
recorded residual in §16.

---

## 4. Outcome matrix

Frozen by `test_freeze_outcome_vocabulary_and_attestation_limits` and
`test_freeze_binding_maps_cancellation_to_indeterminate_with_governance_fields`,
and captured as five committed signed fixtures (§11).

| `outcome` | `result_digest` | Attestation limit added | `extensions.mcp` extra | Governance Booleans |
|-----------|-----------------|-------------------------|------------------------|---------------------|
| `result_returned` | present (`sha256:…`) | `RESULT_LIMIT` | — | none |
| `error_returned` | present (`sha256:…`) | `RESULT_LIMIT` | — | none |
| `task_submitted` | **absent** | `TASK_LIMIT` | — | none |
| `exception` | **absent** | (base limit only) | `exception_class` | none |
| `indeterminate` | **absent** | (base limit only) | — | all three (§7) |

`RESULT_LIMIT` and `TASK_LIMIT` are the exact strings defined in
`dagr_mcp/srs_receipts.py` (`RESULT_LIMIT` at line 28, `TASK_LIMIT` at line 34).
Membership is asserted with `srs_receipts.RESULT_LIMIT in r["attestation_limits"]`
and `srs_receipts.TASK_LIMIT in task["attestation_limits"]`.

Binding-source mapping (frozen by inspecting
`DAGRMiddleware.on_call_tool` source):

- `asyncio.CancelledError` → `outcome="indeterminate"` with
  `"request_cancelled": True`, `"execution_state_unknown": True`,
  `"delivery_incomplete": True`.
- Any other inner exception → `outcome="exception"` with
  `exception_class=type(exc).__name__`.

---

## 5. Receipt cardinality and admission/outcome linkage

**Cardinality** — frozen by
`test_freeze_admitted_call_emits_two_receipts_admission_then_outcome` and
`test_freeze_terminal_refusal_emits_single_receipt`:

- An **admitted** call emits **exactly 2** receipts: the admission receipt is
  written to disk *before the inner handler runs* (`seen_at_inner["count"] == 1`),
  then the outcome receipt is written after. Final on-disk set is
  `["admission", "outcome"]`.
- A **terminal refusal** emits **exactly 1** receipt, and the inner handler
  **never runs** (`ran["inner"] is False`).

**Linkage** — frozen by
`test_freeze_every_outcome_references_the_admission_receipt` and
`test_freeze_bridge_result_outcome_links_to_admission`:

- Every outcome receipt's `admission_receipt_ref` equals the admitted admission
  receipt's `receipt_id`. In the committed fixtures all five outcomes reference
  `FREEZE_ADMISSION_ID = "urn:srs:receipt:admission:freeze-admitted"`.
- In a live harness run, `outcome["admission_receipt_ref"] ==
  admission["receipt_id"]` holds against the freshly generated ids.

---

## 6. Refusal and deferral reason codes (registry summary)

Consolidated reason-code registry as frozen (superset of §3, for quick reference):

| Kind | Code | Source of freeze |
|------|------|------------------|
| Refusal | `policy_refused` | deny policy |
| Refusal | `unknown_tool_fail_closed` | unknown tool, fail-closed |
| Refusal | `required_sink_unavailable` | required/effective-required sink missing |
| Deferral | *(no reason_code)* — `retry_contract = retry_after_approval` | `review_required` gate with review sink |

---

## 7. Cancellation-governance fields

Frozen by `test_freeze_cancellation_field_registry`,
`test_freeze_cancellation_fields_present_only_on_indeterminate`, and
`test_freeze_cancellation_fields_are_boolean_only_and_indeterminate_only`.

The registry is exactly:

```
srs_receipts.CANCELLATION_FIELD_NAMES == frozenset({
    "request_cancelled",
    "execution_state_unknown",
    "delivery_incomplete",
})
```

Invariants:

- **A0 rename holds.** No `result`-shaped token survives:
  `"result_not_delivered" not in CANCELLATION_FIELD_NAMES` and
  `not any("result" in n for n in CANCELLATION_FIELD_NAMES)`. (The neutral
  `delivery_incomplete` name is deliberate — an ARCS raw-content profile rejects
  any `(?:^|_)result(?:$|_)` key, so a `result_*` name would collide with
  raw-content exclusion even though its value is a governance Boolean. See
  `srs_receipts.py` lines 58–65.)
- **Indeterminate-only.** All three fields are `True` on the `indeterminate`
  receipt and **absent from every other emitted receipt**.
- **Boolean-only, refused pre-sign.** The emitter refuses, *before signing and
  writing nothing*:
  - a cancellation field on a non-`indeterminate` outcome →
    `ReceiptContentError` matching `"only on indeterminate"`;
  - a non-Boolean cancellation value → `ReceiptContentError` matching
    `"must be boolean"`;
  - an unknown binding-owned field → `ReceiptContentError` matching
    `"unknown binding-owned field"`.
  After all three rejections, `not list(tmp_path.glob("urn_srs_receipt_*.json"))`.

---

## 8. Argument and FastMCP result-digest projections

**Argument digest** — frozen by `test_freeze_argument_digest_is_rfc8785_sha256`:

- `sha256_digest(x)` canonicalizes `x` with RFC 8785 JCS and prefixes `sha256:`.
- Key-order independent: `sha256_digest({"b":2,"a":1}) == sha256_digest({"a":1,"b":2})`.
- Length is exactly `len("sha256:") + 64`.

**Result digest** — frozen by `test_freeze_result_digest_uses_four_member_projection`,
`test_freeze_projection_member_identifiers`,
`test_freeze_projection_golden_digest_is_unchanged`, and
`test_freeze_binding_and_receipt_projection_agree`:

- `fastmcp_tool_result_digest(...)` digests the exact four-member
  `fastmcp.tool_result.v1` projection, in this key order:

  ```
  ["content", "structuredContent", "_meta", "isError"]
  ```

- `project_fastmcp_tool_result(result)` returns those four keys in that order.
- The digest is `"sha256:" + sha256(rfc8785.dumps(projection)).hexdigest()`.
- The frozen golden projection digest is exactly:

  ```
  sha256:26380b315cd335987c15079418c54df086c9a8b3dc7642691ab77b19752a26ce
  ```

  (computed over `ToolResult(content=["golden"],
  structured_content={"record_ref":"record:golden","found":True},
  meta={"fixture":"fastmcp.tool_result.v1"})` at FastMCP 3.4.4).
- The binding path and the receipt path agree:
  `sha256_digest(project_fastmcp_tool_result(r))` equals
  `fastmcp_tool_result_digest(content=…, structured_content=…, meta=…,
  is_error=…)` for the same result.

The digest pin is FastMCP-version-sensitive; it is exact at **FastMCP 3.4.4**.

---

## 9. Custody observations and attestation limits

Frozen by `test_freeze_custody_status_vocabulary`,
`test_freeze_custody_projections_match_committed_golden`,
`test_freeze_custody_gateway_hash_is_deterministic`, and
`test_freeze_custody_non_claim_and_exclusion_flags`. Golden:
`tests/golden/behavioral_freeze/custody_projections.json` (18 projections).

**Vocabularies (exact order):**

- 9 custody statuses: `custody_record_ready`, `custody_record_partial`,
  `trace_only`, `unsupported_boundary_type`, `missing_actor_context`,
  `missing_target_context`, `privacy_blocked`, `policy_refused`, `needs_review`.
- 4 boundary types: `mcp_tool_call`, `mcp_resource_read`,
  `mcp_prompt_retrieval`, `agent_delegation`.
- 3 receipt families: `connection`, `provenance`, `sdk_enforcement`.
- 2 agent-delegation body kinds:
  `AGENT_DELEGATION_BODY_KINDS == frozenset({"agent_delegation_issued",
  "agent_delegation_revoked"})`.

The 18 committed projections cover: one per custody status (9), one per boundary
type (4), one per receipt family (3), and one per delegation body kind (2).

**Determinism.** For every projection, `body["gateway_hash"] ==
mcp_record_custody_gateway_hash(body)`. The recipe pins `observed_at` to
`2026-07-13T00:00:00Z` (otherwise auto-`_now_utc_iso`).

**Non-claim / exclusion posture** (true for every projection):

- Exclusion flags all `True`: `raw_payload_excluded`, `private_path_redacted`,
  `tool_arguments_excluded`, `credential_secret_excluded`.
- Non-claim flags all `False`: `record_admission_claimed`, `mcp_protocol_modified`,
  `mcp_authority_granted`, `model_output_verified`.
- `schema_version == "garp.mcp_record_custody_gateway.v0.1"` and
  `gateway_kind == "mcp_record_custody_gateway"`. The gateway introduces no new
  SRS receipt family.

---

## 10. Attestation limits (per receipt class)

The attestation-limit lists are byte-frozen inside the signed golden receipts
(§11) and covered by the signature (§13). Every receipt carries the base limit
(`BASE_LIMIT`) plus the FastMCP boundary limit (`FREEZE_BOUNDARY_LIMIT`), and
result/error/task receipts add their class limit:

| Class | Limits (in order) |
|-------|-------------------|
| admission (all) | base, boundary |
| `result_returned` / `error_returned` | base, `RESULT_LIMIT`, boundary |
| `task_submitted` | base, `TASK_LIMIT`, boundary |
| `exception` | base, boundary |
| `indeterminate` | base, boundary |

---

## 11. Public API snapshot posture

Frozen by `test_freeze_public_api_surface_matches_committed_snapshot`,
`test_freeze_package_reexports_nothing_but_submodules`, and
`test_freeze_key_module_all_lists_are_exact`. Golden:
`tests/golden/behavioral_freeze/public_api_surface.json`.

- The snapshot records `__all__` (sorted) for **every** module under `dagr_mcp`,
  or `null` when the module defines none. Of **17** modules snapshotted, **9
  define `__all__`** and **8 do not**.
  - Define `__all__`: `amnesiac_fastmcp`, `amnesiac_native`, `amnesiac_stores`,
    `enforcement_harness`, `fastmcp_binding`, `mcp_record_custody_gateway`,
    `policy_profile`, `sdk_spine`, `tool_call_disposition`.
  - No `__all__`: `dagr_mcp` (package), `amnesiac_contracts`, `async_sinks`,
    `demo`, `lint`, `lint.matter_scope`, `srs_bridge`, `srs_receipts`.
- The `dagr_mcp` package surface is **submodules only** — every public
  (non-underscore) attribute is a `ModuleType`; no re-exported classes or
  functions.
- Spot-frozen: `fastmcp_binding.__all__` matches the committed sorted list,
  `srs_receipts` defines no `__all__`, `project_fastmcp_tool_result` is in
  `fastmcp_binding.__all__`, and `wrap_handler` is in
  `enforcement_harness.__all__`.

> Note: the committed snapshot's 9-defines / 8-omits split is authoritative here
> and supersedes any narrative "9 / 7" count in the PR description; the difference
> is `dagr_mcp` (the package) and `dagr_mcp.lint.matter_scope`, both of which the
> snapshot records as `null`.

---

## 12. Committed golden fixtures

All under `tests/golden/behavioral_freeze/`:

| File | Contents |
|------|----------|
| `urn_srs_receipt_admission_freeze-admitted.json` | admission / `admitted` |
| `urn_srs_receipt_admission_freeze-refused.json` | admission / `refused` |
| `urn_srs_receipt_admission_freeze-deferred.json` | admission / `deferred_for_review` |
| `urn_srs_receipt_outcome_freeze-result-returned.json` | outcome / `result_returned` |
| `urn_srs_receipt_outcome_freeze-error-returned.json` | outcome / `error_returned` |
| `urn_srs_receipt_outcome_freeze-exception.json` | outcome / `exception` (`exception_class="TimeoutError"`) |
| `urn_srs_receipt_outcome_freeze-task-submitted.json` | outcome / `task_submitted` |
| `urn_srs_receipt_outcome_freeze-indeterminate.json` | outcome / `indeterminate` (three cancellation Booleans) |
| `issuer-keys.json` | public-only trust bundle (`srs.trust_bundle.v0.1`) |
| `arcs_expectations.json` | per-class 9-verdict ARCS oracle (§14/15) |
| `custody_projections.json` | 18 custody projections (§9) |
| `public_api_surface.json` | module `__all__` snapshot (§11) |

Recipes that regenerate them deterministically:
`tests/behavioral_freeze_recipe.py` (signed receipts) and
`tests/behavioral_freeze_custody.py` (custody projections).

---

## 13. The three freeze layers

The freeze is defined in three nested layers of increasing strictness. A2 parity
work must state which layer a change touches.

### Layer 1 — semantic invariants

The behavioral facts that hold independent of exact bytes. These are the portable
contract other bindings must also satisfy:

- Disposition vocabulary (§2) and tool-class vocabulary.
- Outcome vocabulary and per-outcome digest / attestation-limit shape (§4).
- Receipt cardinality (2 for admitted, 1 for terminal refusal; admission on disk
  before inner runs; inner never runs on refusal) and admission→outcome linkage
  (§5).
- Reason-code registry (§3/§6).
- Cancellation fields are Boolean-only and indeterminate-only; A0 rename holds
  (§7).
- Argument/result digest algebra and projection identifiers; binding and receipt
  digest paths agree (§8).
- Custody non-claim / exclusion posture and deterministic `gateway_hash` (§9).
- Public API is submodules-only at the package; per-module `__all__` snapshot
  (§11).
- Unsupported / absent behavior (§15).

### Layer 2 — normalized-equality projection

Frozen by `test_freeze_unsigned_content_projection_is_stable_across_real_clock_and_uuid`.

The equality projection drops exactly the permitted-volatile fields:

```
NONDETERMINISTIC_RECEIPT_FIELDS = ("receipt_id", "issued_at", "receipt_signature")
```

With a **live** `uuid4` + wall-clock emitter (no id/clock factories), the projected
admission content is **byte-for-byte equal** to the committed
`admission-admitted` fixture's projection, while the volatile fields genuinely
differ (`live["receipt_id"] != committed["receipt_id"]`). This is the layer other
bindings are compared at when their ids/clocks/signatures legitimately differ.

**The exact permitted volatile fields are only these three:**

- `receipt_id` — UUID-backed; pinned in fixtures via the emitter id factory.
- `issued_at` — wall clock; pinned to `2026-07-13T00:00:00Z` via the clock
  factory (`FREEZE_ISSUED_AT`). Verified by
  `test_freeze_permitted_nondeterministic_fields_are_pinned`
  (`receipt["issued_at"] == FREEZE_ISSUED_AT` and `receipt_id` starts with
  `urn:srs:receipt:`).
- `receipt_signature` — deterministic under a fixed Ed25519 seed (so byte-frozen
  in Layer 3), but treated as volatile in the Layer-2 projection so a live key can
  differ.

For custody projections, the single pinned volatile field is `observed_at`.

### Layer 3 — exact deterministic bytes

Frozen by `test_freeze_receipts_are_byte_stable_and_match_committed_golden`,
`test_freeze_signatures_verify_under_the_frozen_identity`,
`test_freeze_signature_covers_every_field`, and
`test_freeze_custody_projections_match_committed_golden`.

- Determinism source: a fixed 32-byte Ed25519 seed `bytes(range(32))`
  (`FREEZE_PRIVATE_SEED`), issuer `issuer:dagr:behavioral-freeze`, key id
  `issuer.dagr.behavioral-freeze/receipt-signing/v1`, public key
  `A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg`. Ed25519 signatures are
  deterministic (RFC 8032), so signature bytes are stable across runs and
  machines.
- Regenerating with `generate_frozen_receipts()` reproduces every committed
  receipt's bytes exactly (`actual_bytes == committed_bytes`).
- Every field is signature-covered: mutating `outcome`, `delivery_incomplete`, or
  `admission_receipt_ref` on `outcome-indeterminate` raises `InvalidSignature`.
- Signing envelope facts (byte-frozen in every fixture):
  `receipt_version = "srs.core.v5.1"`, `profile_id = "srs.mcp.sdk_enforcement"`,
  `profile_version = "v0.1"`, `protocol_binding = "mcp"`,
  `receipt_type = "sdk_enforcement"`, `retention_class_applied = "hash_only"`,
  `extensions.mcp.binding_version = "fastmcp.middleware.v0.1"`, and signature block
  `algorithm = "Ed25519"`, `canonicalization = "RFC8785-JCS"`.

Committed-fixture paths for Layer 3 are the twelve files listed in §12.

---

## 14. Timeout posture (explicit)

**Timeout is frozen as an `exception` outcome carrying `exception_class =
"TimeoutError"`. It is NOT a distinct outcome, and it is NOT unsupported.**

There is no dedicated timeout branch in the binding. A `TimeoutError` raised by
the inner handler is an ordinary inner exception and maps, like any other
exception, to `outcome = "exception"` with
`extensions.mcp.exception_class = type(exc).__name__`, and **no** `result_digest`.

Cited tests:

- `test_freeze_outcome_vocabulary_and_attestation_limits` asserts, on the
  committed `outcome-exception` fixture:
  `exc["outcome"] == "exception"`,
  `exc["extensions"]["mcp"]["exception_class"] == "TimeoutError"`, and
  `"result_digest" not in exc`.
- `test_freeze_binding_maps_cancellation_to_indeterminate_with_governance_fields`
  asserts the binding source maps any inner exception via
  `outcome="exception"` + `exception_class=type(exc).__name__`, and separately
  maps **cooperative cancellation** (`asyncio.CancelledError`) to
  `outcome="indeterminate"` with the three cancellation Booleans — a *distinct*
  path from a raised `TimeoutError`.

So: a raised timeout → `exception` (with `TimeoutError` class); cooperative
cancellation → `indeterminate`. The committed `exception` golden literally uses
`exception_class="TimeoutError"`, making `TimeoutError` a signed, byte-frozen
fixture class.

---

## 15. Unsupported or deliberately absent behavior

Frozen by the item-13 tests.

- **Only two registered binding versions.**
  `srs_receipts.REGISTERED_BINDING_VERSIONS == frozenset({"direct-harness.v0.1",
  "fastmcp.middleware.v0.1"})`
  (`test_freeze_only_registered_binding_versions_are_accepted`).
- **Unregistered binding version refused pre-sign.** Emitting with
  `binding_version="invented.binding.v9"` raises `ReceiptContentError` matching
  `"unregistered binding_version"` and writes nothing to disk
  (`test_freeze_unregistered_binding_version_is_refused`).
- **Single post-execution failure mode.**
  `fastmcp_binding.PostExecutionReceiptFailureMode == ("alert_and_return_result",)`
  and `DAGRMiddlewareConfig(...).post_execution_receipt_failure ==
  "alert_and_return_result"` (`test_freeze_post_execution_failure_mode_is_single_valued`).
- **Amnesiac capability-unavailable is an error result, never success.**
  `amnesiac_fastmcp._capability_unavailable_result(...)` returns `is_error=True`,
  its projection has `isError=True` and
  `structuredContent["status"] == "capability_unavailable"`; the middleware would
  therefore classify it `error_returned`, never `result_returned`
  (`test_freeze_amnesiac_capability_unavailable_is_error_result_not_success`).
- **Raw-content keys refused.**
  `srs_receipts.enforce_raw_content_exclusion({"extensions":{"mcp":{"result":…}}})`
  raises `ReceiptContentError` matching `"forbidden raw-content key"`
  (`test_freeze_raw_content_keys_are_refused`).

Deliberately absent / recorded-not-reconciled (from the freeze notes, not
normalized here): public-but-unexported symbols
(`fastmcp_binding.default_actor_resolution` and the module-level aliases
`ToolClass`, `Disposition`, `PoliciesInput`, `WrappedHandler`); and the
`ToolClass` name collision (3 `Literal` members in `fastmcp_binding` vs 6 in
`enforcement_harness`). These are frozen in the surface snapshot as-is.

---

## 16. ARCS verification and the re-signed non-Boolean rejection

Frozen by `test_freeze_all_receipt_classes_pass_full_arcs_verification`,
`test_freeze_committed_expectations_are_internally_complete`, and
`test_freeze_resigned_non_boolean_delivery_field_is_rejected_by_arcs`. These
require co-installed `arcs_verify` and **skip cleanly** in the standalone lane
(3 skips). Profile: `srs.mcp.sdk_enforcement.v0.1`. Oracle:
`arcs_expectations.json`.

**Item 14 — all 8 classes verify clean.** Each of the 8 signed classes (3
admission + 5 outcome) passes the full **9-verdict** profile. The frozen verdict
oracle for every class is:

| Verdict | Frozen value |
|---------|--------------|
| `envelope` | `true` |
| `schema_digest` | `true` |
| `signature_valid` | `true` |
| `issuer_key_resolved` | `true` |
| `issuer_key_trusted` | `true` |
| `raw_content_exclusion` | `true` |
| `attestation_limits_present` | `true` |
| `profile` | `true` |
| `chain_status` | `"not_applicable"` |

with `passed = true` and `failure_codes = []` for every class. The expectations
set is internally complete: its `name`s are exactly the eight class names.

**Item 15 — re-signed non-Boolean governance field rejected on a profile ground.**
A genuinely re-signed `indeterminate` receipt whose `delivery_incomplete` Boolean
is swapped for raw transcript material verifies as:

- `signature_valid == True` (the re-sign is genuine, not a broken signature),
- `profile == False`,
- `passed == False`,
- `failure_codes` contains
  `"profile.non_boolean_governance_field:delivery_incomplete"`.

This is the guard `arcs-verify da89ebe` added, closing the A0 cross-repo gap: a
`result`-shaped value cannot be smuggled through the governance Boolean even under
a valid signature.

---

## 17. The `required_sink_unavailable` residual

Recorded, not normalized. Frozen by
`test_freeze_gate_without_review_sink_reason_code`.

A `review_required` gate makes the review sink an **effective required sink**. When
that sink is absent, its absence is caught by the required-sink **health check**
that runs *before* `_gate_call`. The observable result is therefore:

- `GovernedResult.failure_reason == "review_object_sink_unavailable"`, and
- the emitted refusal `reason_code == "required_sink_unavailable"`

— **not** `review_object_creation_failed`. That latter code is reachable only via
a review sink that is *present but raises during object creation*, which is
covered by `tests/test_srs_receipts.py`, outside this freeze. A2 must preserve
this ordering (health check before gate) or explicitly re-baseline the reason
code.

---

## 18. Verification commands and results

Run 2026-07-13 against A1 head `d4f81a2`. Environment: **Python 3.13.4, FastMCP
3.4.4, cryptography 46.0.7, rfc8785 0.1.4**; co-installed lane adds
**arcs-verify 0.1.1 @ `da89ebe`, arcs-amnesiac 0.2.0, garp-sdk 0.1.0**.

**Standalone lane** (`dagr-mcp[dev]` only; no `arcs_verify` / `arcs_amnesiac` /
`garp_sdk`):

```
$ python -m pytest -q
230 passed, 18 skipped
```

**Co-installed lane** (`+ arcs-verify@da89ebe + arcs-amnesiac@0.2.0 + garp-sdk@0.1.0`):

```
$ python -m pytest -q
270 passed
```

**Canonical ARCS suite** (unmodified, at `da89ebe`):

```
$ (cd ../arcs-verify && python -m pytest -q)
108 passed
```

**Public-release scan:**

```
$ python tools/check_public_release.py .
PASS: 0 finding(s)
```

**Committed-fixture / frozen-contract / projection-golden / freeze suite** (co-installed):

```
$ python -m pytest tests/test_fastmcp_fixture_generator.py tests/test_frozen_contract.py \
    tests/test_fastmcp_projection_golden.py tests/test_behavioral_freeze.py -q
48 passed
```

**Freeze suite alone:** `40 passed` co-installed; `37 passed, 3 skipped`
standalone (items 14 & 15 skip without `arcs_verify`).

**Package build** (`.github/workflows/package-build.yml` steps, run locally):

```
$ python -m build --sdist --wheel --outdir dist
Successfully built dagr_mcp-0.1.0.tar.gz and dagr_mcp-0.1.0-py3-none-any.whl
$ python -m twine check dist/*
PASSED  (wheel + sdist)
$ dagr-mcp --help            # installed-command smoke
OK
$ python -c "import importlib.metadata as m; print('dagr-mcp', m.version('dagr-mcp'))"
dagr-mcp 0.1.0
```

All lanes green; frozen fixtures verified byte-stable.
