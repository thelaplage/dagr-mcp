# DAGR MCP — five-minute quickstart

Emit signed SRS receipts from the real installed demo, then verify them with a
**separately installed** ARCS Verify. Every command below is copy-pasteable by
an authenticated operator with access to both private repositories. No receipt
is hand-authored, no network fetch happens during emission or verification, and
no private credential or committed fixture is used or modified.

Run everything from an empty working directory of your choice.

## 1. Clone both repositories

```bash
git clone https://github.com/thelaplage/dagr-mcp.git dagr-mcp
git clone https://github.com/thelaplage/arcs-verify.git arcs-verify
```

The published distribution names and `pip install` commands are not finalized
yet (see [NAMING.md](NAMING.md)), so this quickstart installs both from their
clones.

## 2. Install the emitter in its own clean environment

Requires Python **3.11 or newer**.

```bash
python3 -m venv dagr-mcp/.venv
source dagr-mcp/.venv/bin/activate        # Windows: dagr-mcp\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e dagr-mcp
```

This installs the `dagr-mcp` console command (and FastMCP `3.4.4`) from the
local source tree — not from any package index.

## 3. Emit receipts to a temporary output directory

```bash
OUT="$(mktemp -d)"
dagr-mcp demo --output "$OUT"
echo "emitter exit code: $?"              # 0
```

The default demo runs an **admitted read** through the FastMCP middleware
binding (`fastmcp.middleware.v0.1`), so it writes **two** receipts plus a
matching trust bundle into `"$OUT"`:

- `urn_srs_receipt_admission_*.json` — the `admission` receipt (`admitted`).
- `urn_srs_receipt_outcome_*.json` — the `outcome` receipt (`result_returned`),
  linked to the admission receipt via `admission_receipt_ref`.
- `issuer-keys.json` — a trust bundle holding only the run's **public** signing
  key (no private material).

The demo mints a fresh ephemeral signing key and new identifiers/timestamps on
every run, so the receipt `receipt_id`s, signatures, and file SHA-256s differ
each time. It is not byte-reproducible; the reproducible golden fixtures under
`tests/golden/` are produced separately by the test-only fixture generator.

## 4. Inspect the coverage fields

Read the emitted receipts with the standard-library JSON tools (no extra
package needed):

```bash
python3 - "$OUT" <<'PY'
import glob, json, os, sys
out = sys.argv[1]
for path in sorted(glob.glob(os.path.join(out, "urn_srs_receipt_*.json"))):
    r = json.load(open(path))
    print("file:", os.path.basename(path))
    print("  receipt_kind      :", r.get("receipt_kind"))
    print("  profile           :", f'{r["profile_id"]} {r["profile_version"]}')
    print("  binding_version   :", r["extensions"]["mcp"].get("binding_version"))
    print("  parent_receipt_ref:", r.get("parent_receipt_ref", "(absent)"))
    print("  admission_ref     :", r.get("admission_receipt_ref", "(n/a — admission receipt)"))
    print("  attestation_limits:", len(r.get("attestation_limits", [])), "limit(s)")
    print("  retention_class   :", r.get("retention_class_applied"))
    print("  excluded classes  :", ", ".join(r.get("artifact_classes_excluded", [])))
PY
```

Expected: `binding_version` is `fastmcp.middleware.v0.1`; `parent_receipt_ref`
is **absent** (the demo configures no parent link); the `outcome` receipt names
its `admission_receipt_ref`; `attestation_limits` is non-empty (2 on the
admission receipt, 3 on the outcome receipt); `retention_class` is `hash_only`;
and the four raw artifact classes are excluded — arguments and results appear
only as `sha256:` digests, never as raw content.

## 5. Install the verifier in a separate clean environment

The verifier is installed and run independently — it imports no emitter code and
recomputes every result from the serialized receipt bytes.

```bash
deactivate 2>/dev/null || true
python3 -m venv arcs-verify/.venv
source arcs-verify/.venv/bin/activate     # Windows: arcs-verify\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e arcs-verify
```

`arcs-verify` **main includes `688a1881c779d7f038be68df6d867dac67d5c2b0`** (the
merged launch-packaging P1 commit). This quickstart installs current `main`;
you do not need to check out that commit, because current `main` descends from
it. Confirm ancestry with:

```bash
git -C arcs-verify merge-base --is-ancestor \
  688a1881c779d7f038be68df6d867dac67d5c2b0 main \
  && echo "arcs-verify main descends from P1: yes"
```

## 6. Verify the emitted receipts

Verify each emitted receipt against the trust bundle the demo wrote beside it,
using the named profile:

```bash
for receipt in "$OUT"/urn_srs_receipt_*.json; do
  echo "== $(basename "$receipt") =="
  arcs-verify "$receipt" \
    --keyring "$OUT/issuer-keys.json" \
    --profile srs.mcp.sdk_enforcement.v0.1
  echo "verifier exit code: $?"
done
```

For each receipt, expect the **eight Boolean results**, then the separate
`chain_status`:

| Result | Expected |
|---|---|
| `schema_digest` | PASS |
| `envelope` | PASS |
| `profile` | PASS |
| `raw_content_exclusion` | PASS |
| `signature_valid` | PASS |
| `issuer_key_resolved` | PASS |
| `issuer_key_trusted` | PASS |
| `attestation_limits_present` | PASS |
| `chain_status` | `not_applicable` (reported separately; **not** a ninth PASS) |

Expected verifier exit code: **0** for each receipt. `chain_status:
not_applicable` means no cross-artifact chain was in scope — it is not a PASS,
and a clean acceptance is *eight Boolean results true plus `chain_status:
not_applicable`*, never "nine" of anything. Add `--json` for the full
machine-readable report (`passed`, `failure_codes`, and details).

Negative-verification examples (mutated receipts whose signatures no longer
match their bytes) live in the ARCS Verify quickstart. The emitter has no
committed negative demo path, so none is invented here.

## What a clean result means

A clean result establishes that each emitted receipt matches the pinned SRS
envelope schema and the `srs.mcp.sdk_enforcement.v0.1` profile, carries only
references and digests, and was signed and unmodified under the resolved,
trusted demo key. It does not certify the emitting implementation and does not
prove the underlying tool result was true. See the **Limitations** section of
the [README](../README.md).
