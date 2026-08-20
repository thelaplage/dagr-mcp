# FLAGSHIP-DEMO0 — Governed Agent Action: End-to-End Chain

This example walks through the complete DAGR/ARCS governed-action chain using a
synthetic Theranos CA-9 appeal research scenario. It is the primary public demo
for the DAGR/ARCS ecosystem.

**Authority limits apply throughout. Read them before interpreting any output.**

## What this demo shows

```
research question
  → governed agent action  (dagr-mcp emits signed SRS receipts)
  → evidence trail         (discovered / fetched / cited / relied-upon sources)
  → projection             (arcs-verify recomputes from bytes; 8 boolean results)
  → recovery               (replay from serialized receipt bytes; detects drift)
```

### Five steps in detail

| Step | What happens | What it establishes | What it does NOT establish |
|---|---|---|---|
| **1. Research question** | Structured document with non-claims declared upfront | The question scope, input ref, traversal parameters | Truth, completeness, source authority |
| **2. Governed actions** | Three tool calls through the `direct-harness.v0.1` boundary: discover (admit), fetch×2 (admit), mutate (refuse) | Which tools ran, which were refused; signed SRS receipt per call | Source truth; model retention; provider behaviour |
| **3. Evidence trail** | Four-layer trail built from receipt data: discovered / fetched / cited / relied-upon | Layered research posture with observation refs | Evidentiary support; completeness; proximity = support |
| **4. Projection** | `arcs-verify` runs as a **subprocess** (never imported); reports 8 boolean results per receipt | Structural validity, signature, profile conformance | Source truth; `PASS != source truth`; `not_applicable != PASS` |
| **5. Recovery** | Re-read bytes from disk; digest binding checked | Bytes did not drift since emission | Real-world event proven; authenticity beyond receipt structure |

---

## Scenario

**Research question:** What governed sources support the public record on the
Theranos criminal appeal before the Ninth Circuit?

**Input ref:** `record:theranos-ca9-appeal`

**Scenario note:** This demo uses a **synthetic** scenario. No external source
is queried. No production signing credential is used. Sources appear by ref and
category label only — no raw content is returned or stored.

---

## Running the demo

### Prerequisites

```bash
# Install dagr-mcp from repo root in its own environment
python3 -m venv dagr-mcp/.venv
source dagr-mcp/.venv/bin/activate
python -m pip install -e dagr-mcp
```

Optionally, install `arcs-verify` in a **separate** environment (Step 4 is
skipped but otherwise labelled with expected output if absent):

```bash
deactivate
python3 -m venv arcs-verify/.venv
source arcs-verify/.venv/bin/activate
python -m pip install -e arcs-verify
```

### Run

```bash
# Step-by-step output (default)
python examples/flagship-demo0/flagship_demo.py

# Write receipts to a specific directory
python examples/flagship-demo0/flagship_demo.py --output /tmp/flagship-run

# Machine-readable JSON report
python examples/flagship-demo0/flagship_demo.py --json
```

### Expected output (default mode)

```
FLAGSHIP-DEMO0 — research question → governed action →
               evidence trail → projection → recovery

Authority limits apply throughout. See module docstring.
Scenario: SYNTHETIC (no real network calls; no real credentials).

────────────────────────────────────────────────────────────────────────

[1/5] RESEARCH QUESTION
  Question : What governed sources support the public record on
             the Theranos criminal appeal before the Ninth Circuit?
  Input ref: record:theranos-ca9-appeal
  Non-claims (4):
    • question_execution != truth
    • graph_reachability != evidentiary_support
    • source_set != completeness_of_world
    • candidate_found != canonical_identity

────────────────────────────────────────────────────────────────────────

[2/5] GOVERNED ACTIONS  (dagr-mcp enforcement harness, direct-harness.v0.1)
  Profile  : srs.mcp.sdk_enforcement.v0.1
  Tools    : source.discover (read/allow) | source.fetch (read/allow) | source.mutate (write/deny)
  Receipts emitted: 7 total (3 admitted-admission + 3 outcome + 1 refused-admission)
    source.discover                   ADMITTED  body_ran=True
    source.fetch                      ADMITTED  body_ran=True
    source.fetch                      ADMITTED  body_ran=True
    source.mutate                     REFUSED [deny]  body_ran=False

────────────────────────────────────────────────────────────────────────

[3/5] EVIDENCE TRAIL
  Discovered : 3 source(s)
    • urn:source:court:ca9-theranos-19-50246  [source_recurrence]
    • urn:source:sec:theranos-2016-annual-report  [page_link]
    • urn:source:news:wsj-theranos-2018-09-05  [page_link]
  Fetched    : 2 source(s)  (governed; receipts emitted)
  Cited      : 1 source(s)
  Relied upon: 1 source(s)
  Observation refs (from admission receipts): 3

────────────────────────────────────────────────────────────────────────

[4/5] PROJECTION  (arcs-verify subprocess — never imported)
  [... PASS/SKIP per receipt ...]

────────────────────────────────────────────────────────────────────────

[5/5] RECOVERY  (replay from serialized bytes)
  STABLE — bytes on disk match emission-time receipt IDs
```

---

## What is produced

Running the demo writes the following to the output directory:

| File | Contents |
|---|---|
| `urn_srs_receipt_admission_*.json` | Signed admission receipt (admitted or refused) |
| `urn_srs_receipt_outcome_*.json` | Signed outcome receipt (linked to admission) |
| `issuer-keys.json` | Trust bundle: public verification key + issuer identifiers |

The demo generates a fresh ephemeral Ed25519 signing key per run. The private
key lives only in process memory. Only the public key appears in `issuer-keys.json`.
Because each run mints a new key and new identifiers, receipt IDs, signatures,
and file SHA-256s differ per run.

---

## Sources: four categories

| Category | What it means | What it does NOT mean |
|---|---|---|
| **Discovered** | Found by graph traversal (refs only, no raw content) | Complete; verified; primary |
| **Fetched** | Retrieved under governed boundary; receipt emitted | Content authenticated; content true |
| **Cited** | Referenced in the constructed record (refs only) | Evidentiary support established |
| **Relied-upon** | Named as the evidentiary basis | Independent verification complete |

---

## Authority limits

These are stated by the demo itself and must not be overridden by output framing:

- `receipt_emission != verification`
- `admitted != source_truth`
- `refused != fraud`
- `PASS != source_truth`
- `not_evaluated != PASS`
- `not_applicable != PASS`
- `byte_stable != authenticated`
- `no_drift_detected != real_world_event_proven`
- `observation_ref != independent_verification`
- `evidence_trail != verdict`

---

## Verifying the receipts independently

After running the demo, verify each receipt as a separate step (requires
`arcs-verify` installed in a separate environment):

```bash
OUT=<output directory from demo>

for receipt in "$OUT"/urn_srs_receipt_*.json; do
  echo "== $(basename "$receipt") =="
  arcs-verify "$receipt" \
    --keyring "$OUT/issuer-keys.json" \
    --profile srs.mcp.sdk_enforcement.v0.1 \
    --json
done
```

Expected 8 boolean results per receipt (admitted receipts):

| Field | Expected |
|---|---|
| `schema_digest` | PASS |
| `envelope` | PASS |
| `profile` | PASS |
| `raw_content_exclusion` | PASS |
| `signature_valid` | PASS |
| `issuer_key_resolved` | PASS |
| `issuer_key_trusted` | PASS |
| `attestation_limits_present` | PASS |
| `chain_status` | `not_applicable` — reported separately, **not** a ninth PASS |

---

## Architecture position

This demo sits at the emitter layer. The full chain is:

```
garp-doctrine  ──governs──▶  arcs-srs  ──schema/profiles──▶  dagr-mcp  ──emits receipts──▶  arcs-verify
 (authority)                 (standard)      (vendored)        (emitter)      (bytes only)     (verifier)
```

`dagr-mcp` (this repo) owns emission. `arcs-verify` owns verification. They
share no code. The demo preserves this split: the script emits receipts through
the real dagr-mcp harness and invokes arcs-verify only as a subprocess.

---

## Related

- `examples/generic-stdio-showcase/` — governed stdio MCP connector over a real third-party server
- `examples/counterpedia-acquisition-showcase/` — governed acquisition over the Counterpedia read API
- `docs/QUICKSTART.md` — five-minute quickstart (FastMCP binding)
- `dagr_mcp/first_run_demo.py` — admitted-vs-refused proof (same handler, same args)
