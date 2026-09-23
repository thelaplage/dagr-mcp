# Brand residue inventory — DAGR-MCP-BRAND-HYGIENE0 v0.1

Measured at `origin/main` `d28fce97`, 2026-09-23.

Retires **active Garpedia product language** from `dagr-mcp` while preserving
every token that carries wire identity, package identity, provenance, or a
migration decision owned elsewhere. The distinction is the same one applied to
receipt conformance: a name that *identifies* something is not the same as a
name that *brands* it.

## Before → after

| | Occurrences | Files |
|---|---:|---:|
| Before | 285 | 69 |
| After | 278 | 66 |
| **`GARPedia` (active product name)** | **7 → 0** | 4 → 0 |

The 7 removed are the entire active-brand set. The 278 survivors are justified
below, by class.

## Changed — active product branding (7)

| File:line | Was | Now |
|---|---|---|
| `README.md:22` | `Public read and demo surfaces \| GARPedia, Overlay, Showcase` | `Counterpedia, Overlay, Showcase` |
| `README.md:74` | `-> human and agent projection in GARPedia` | `… in Counterpedia` |
| `docs/PRODUCT_ARCHITECTURE.md:15` | `\| GARPedia \| public record, sources, history…` | `\| Counterpedia \| …` |
| `docs/PRODUCT_ARCHITECTURE.md:86` | `project … material to GARPedia.` | `… to Counterpedia.` |
| `docs/PRODUCT_ARCHITECTURE.md:88` | `the … GARPedia projection` | `the … Counterpedia projection` |
| `.ecosystem/RESPONSIBILITIES.yaml:132` | `authority_repository: "GARPedia"` | `"Counterpedia"` |
| `tests/test_docs_current_surface.py:17` | asserts `"GARPedia"` in README | asserts `"Counterpedia"` |

The test is the load-bearing one. `test_readme_names_all_implemented_binding_surfaces`
**required** the README to contain `GARPedia`, so it actively pinned the retired
brand: the README could not be corrected without it failing. Its intent — the
front door must name the public projection surface — is unchanged; only the
surface's name moved. Leaving it would have made the repo's own test suite the
thing blocking the migration.

## Preserved, with justification

### Frozen wire identity — 25
`garp.mcp_record_custody_gateway.v0.1` and the `GARP body kinds` vocabulary it
governs (`dagr_mcp/mcp_record_custody_gateway.py`, `docs/BEHAVIORAL_FREEZE.md`,
`docs/GATEWAY_SERVICE_ADAPTER_SCOPE.md`, `docs/NEUTRAL_LIFECYCLE_CONTRACT.md`).
A schema discriminator is identity. Renaming it changes what receipts mean and
breaks every consumer that matches on it. **Never rewrite.**

### Live package identity — `garp-sdk` / `garp_sdk`, 84
`pyproject.toml` declares the real extra
`amnesiac = ["arcs-amnesiac>=0.2.0", "garp-sdk>=0.1.0"]`. The
`thelaplage/garp-sdk` repository exists and is **not archived** (last push
2026-08-09). Every doc reference describes an installable dependency.

**Classification: ACTIVE COMPATIBILITY — blocked on SDK migration authority.**
`dagr-sdk` exists and is actively developed (last push 2026-09-22), so a
`garp-sdk` → `dagr-sdk` migration is plausibly intended, but that decision is
owned by the SDK repositories, not by `dagr-mcp`. Renaming here by inference
would make the install instructions **false** — `pip install 'dagr-mcp[amnesiac]'`
resolves `garp-sdk`, and a doc saying otherwise is a defect, not hygiene.
Blocked pending that separately owned decision.

### Live sibling repositories — 51
`garp-doctrine` (20), `garp-core`/`garp_core` (22), `garp-local`/`garp_local`
(20), `garp-boundary`/`garp_boundary` (9), and the `GarpLocalReviewObjectSink`
class name. These name repositories and symbols that currently exist under those
names. Each is subject to the estate-wide DAGR migration, and each migrates when
its owning repository does — not when a downstream consumer's docs are edited.

### Historical provenance and frozen fixtures
`tests/golden/behavioral_freeze/custody_projections.json` (38) and the other
golden files are **byte-pinned frozen goldens**; editing them would invalidate
the freeze they exist to hold. `garp-sdk-freeze-notices.patch` (18) is a
historical patch artifact. `docs/internal/CLOSE_MEMO_*.md` are dated memos
describing what happened under the names in use at the time.
`tests/test_enforcement_harness_no_garp_core.py` (19) encodes an *absence*
assertion whose subject is the legacy name — renaming it would silently change
what the test proves. `tests/test_agent_plugins_conformance.py:22` already
labels its own literals "compatibility debt".

### Configuration consumed elsewhere — `.garp/doctrine_manifest.json`
Read by **13 files in `garp-ops`**. Renaming the directory from `dagr-mcp`
would break a consumer in another repository. Belongs to the `garp-ops`
retirement lane.

## Acceptance

- ✅ No active Garpedia product language remains. `GARPedia` occurs **0** times
  outside this inventory; the only surviving instances are the before-state
  quotations in the table above, which are the record of what was removed:

  ```bash
  grep -rn 'GARPedia' . | grep -v '/\.git/' | grep -v BRAND_RESIDUE_INVENTORY | wc -l   # => 0
  ```
- ✅ Every surviving `GARP`/`garp` token falls into exactly one justified class
  above: frozen wire identity, live package identity, live sibling repository,
  historical provenance / frozen fixture, or configuration owned elsewhere.
- ✅ No wire identifier, schema name, pin, fixture, or golden file was modified.

## Verification at exact head

Suite run in bounded batches (the full run is OOM-killed on this machine, exit
137 — a local resource limit, not a repository condition):

```
1516 tests collected
batch 1  215 passed, 3 skipped      batch 5  317 passed
batch 2  265 passed, 1 skipped      batch 6  175 passed, 2 skipped, 1 failed
batch 3  236 passed, 2 skipped, 1 failed   batch 7   13 passed, 1 failed
batch 4  286 passed, 1 skipped
```

**Changed-surface tests: 15 passed, 1 skipped** —
`tests/test_docs_current_surface.py` and `tests/test_ecosystem_declarations.py`,
the two suites that read every file this lane touches.

### The failures are pre-existing, proven against a pristine baseline

A detached worktree at clean `origin/main` `d28fce97` reproduces the same three:

| Test | clean `origin/main` | this branch |
|---|---|---|
| `test_gateway_response_vectors_regenerate_byte_identically` | FAIL | FAIL |
| `test_shipped_tests_resolve_fixtures_inside_their_own_sdist[dagr-mcp-sdk-v2]` | FAIL | FAIL |
| `test_generated_receipts_pass_the_real_arcs_verify_cli` | FAIL | FAIL |

The third is an environment defect, not a code one: the installed `arcs-verify`
CLI loads an x86_64 native module on an arm64 host —
*"incompatible architecture (have 'arm64', need 'x86_64')"*.

One further test, `test_timeout_after_forwarding_preserves_uncertainty`, failed
**only inside the large batch** and passes deterministically in isolation (2/2)
and across its own file (22/22). It is timing-sensitive under memory pressure,
not a regression: nothing in this change touches the gateway connector path.

**Net: zero regression. No test passes at `origin/main` and fails here.**

## Explicitly out of scope

CI and GitHub Actions; the `dagr-mcp` quickstart; the `garp-sdk` → `dagr-sdk`
rename; `.garp/` directory retirement; the domain posture
(`counterpedia.vercel.app` / `counterpedia.org`) tracked in dagr-ops #55.
