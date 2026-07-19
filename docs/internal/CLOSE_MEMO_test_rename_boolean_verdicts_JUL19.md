---
id: CLOSE_MEMO_test_rename_boolean_verdicts_JUL19
title: Hygiene lane close memo -- verifier test rename
date: 2026-07-19
classification: Internal / Hygiene / Lane Close
status: Draft
---

## Scope

This lane renamed one test function in `dagr-mcp` and touched no
other file. It corrected a naming trap identified by the Lane 0
reconciliation memo dated 2026-07-18: the test
`test_combined_extension_receipt_passes_all_nine_verdicts` asserted
a Boolean set whose count does not match the count implied by its
own name, and citing the test by name alone would misreport
arcs-verify's public verdict shape.

## What was verified before mutation

Read `arcs_verify/verifier.py` at local HEAD in the `arcs-verify`
repo (read-only, no git operations). The `VerificationReport`
dataclass and `verify_receipt()` expose exactly eight Boolean
verdict fields in the public serialized shape returned by
`to_dict()`: `schema_digest`, `envelope`, `profile`,
`raw_content_exclusion`, `signature_valid`, `issuer_key_resolved`,
`issuer_key_trusted`, `attestation_limits_present`. Separately,
`chain_status` is a non-Boolean status field (string, value
`not_applicable` for standalone receipts). `failure_codes` and
`details` are diagnostic list fields, not verdicts. `to_dict()` also
adds a derived `passed` Boolean (an AND of the eight verdicts plus
the `chain_status` equality check) -- this is a summary field, not
an independent verdict, and is not asserted by the test and not
counted toward the verdict total, consistent with how the doctrine
passage below treats it.

The garp-doctrine memo
`IN___DAGR_MCP_Bossy_Demo_Scoping_Memo_v0_2_1_JUL11.md` (dated
2026-07-11, classification Internal / Founder / Lane Scoping)
establishes doctrine authority for this count. Its corrections
table states:

> Verifier claim language | "Nine green verdicts" | Eight PASS
> Boolean verdicts plus `chain_status: not_applicable` for
> standalone receipts; not_applicable is not PASS

This matches the arcs-verify public shape read at current HEAD
exactly: eight Booleans plus one non-Boolean status field.

The renamed test's assertion block asserts exactly those eight
Boolean fields are `True` in a loop, then separately asserts
`report["chain_status"] == "not_applicable"`. Assertion count and
assertion targets match the public shape and match doctrine's
framing. No later ratified successor doctrine (the JUL13
ratification record, the JUL13 ratification erratum, or the JUL19
broadcast standards ratification record) states that the numeric
count is contractual or must appear in the test name, so the
exception clause in the lane's operator instructions does not
apply. The default Boolean-set-agnostic form was used.

## What was renamed

`test_combined_extension_receipt_passes_all_nine_verdicts` became
`test_combined_extension_receipt_passes_all_boolean_verdicts_with_chain_status`
in `tests/test_emitter_extensions.py`. No other file in `dagr-mcp`
matched the string `passes_all_nine_verdicts`; this was the sole
occurrence and the sole mutation.

## What was deliberately not touched

Two other identifiers in the same file carry an adjacent "nine"
framing but do not match the mandated grep string
(`passes_all_nine_verdicts`) and were left untouched per this
lane's literal scope:

- The helper function `_fallback_nine_verdicts` (used only when
  `arcs_verify` is not importable).
- Its companion diagnostic string, `"arcs-verify unavailable; used
  frozen-rule nine-verdict fallback"`.

Both compute or describe the same eight-Boolean-plus-chain-status
shape under a "nine" label. They are candidates for a future
narrow hygiene lane but fall outside this lane's exact-string scope
and were not renamed here.

No assertion was changed. No fixture name was changed. No asserted
value was changed. `pyproject.toml`, README structural content, and
`STEINER_GATE.md` were not touched. No test was added or removed.

## Verification result

```
cd dagr-mcp && ./.venv/bin/pytest -k "combined_extension_receipt_passes" -x -q
1 passed, 529 deselected
```

The renamed test runs green in isolation under the repo's own
`.venv` (the bare `pytest` on PATH fails collection on an unrelated
module, `test_behavioral_freeze.py`, due to a missing `rfc8785`
import outside the venv -- a pre-existing environment condition,
not caused by this lane).

## Standing blockers, confirmed untouched

G1, the PyPI squat, G5, `STEINER_GATE.md`, `pyproject.toml`, the
frozen binding registry, and all fixtures and asserted values were
not read for the purpose of mutation and were not modified.
