# CP-DAGR-MCP-ACQ0-PROOF: counterpedia-acquisition stdio MCP showcase

A small, runnable live-run companion to **DAGR-MCP-SOURCE0** (PR #41,
merged `a9e7088`): `dagr_mcp_service.acquisition_connector`, which pins
`counterpedia-acquisition`'s real MCP tool surface as a
`StdioTargetConfig` / `StdioToolConnector` target but was previously only
exercised against a *hermetic fake* MCP child
(`tests/_acquisition_fake_mcp_child.py`, 22 tests). This example drives that
exact same merged factory (`build_acquisition_connector`) against a real,
unmodified `counterpedia-acquisition` checkout's actual MCP server
(`acquisition.mcp_server`, official `mcp==1.29.0` SDK), launched as a real
child process over stdio.

## Status: PROOF, not the full ACQ0 seam

```
CP-DAGR-MCP-ACQ0-PROOF
✅ real dagr-mcp StdioToolConnector (DAGR-MCP-SOURCE0's own pinned factory)
✅ real unmodified counterpedia-acquisition MCP child
✅ real MCP handshake
✅ real HTTP acquisition
✅ real DAGR admission + outcome SRS receipts
✅ refusal-before-execution proven externally (fixture hit counters)
✅ zero changes to acquisition
✅ zero changes to authoring

CP-DAGR-MCP-ACQ0
PARTIAL — transport/runtime wedge proven
HOLD — actual authoring process_source seam not yet governed
```

This example proves DAGR can govern an unmodified Counterpedia acquisition
MCP server through the existing generic stdio connector. It does **not**
replace `McpStdioAcquisitionToolTransport`, does **not** govern
`ProducerAcquisitionToolClient.process_source()`, does **not** modify
ACQ1-HTTP, does **not** modify AUTHOR-HTTP, and makes **no** claim about
Counterpedia admission or verification. `counterpedia-authoring`'s real
producer re-fetch seam actually calls `acquisition.process_source` — this
example only exercises that tool as a **refused** case (see scenario 3
below), deliberately, to stay decoupled from authoring's in-flight
`fix/author-acq0-producer-contract-boundary-v0-1` branch. Governing the
real `process_source` seam is a distinct follow-on,
**CP-DAGR-MCP-ACQ0-BIND**, once that branch lands:

```
CP-DAGR-MCP-ACQ0-PROOF      ← this example
          ↓
REAL-CONTENT-AUTHOR0 / producer-contract work lands
          ↓
CP-DAGR-MCP-ACQ0-BIND
DagrGovernedAcquisitionToolTransport
          ↓
actual acquisition.process_source through DAGR
          ↓
admission/outcome receipts on the real Draft from URL path
```

## What this proves

Running `live_run.py` demonstrates **one configured governed path** through
`dagr_mcp_service.acquisition_connector.build_acquisition_connector` /
`execute_governed_call`, over the real `acquisition` MCP server, with no
mocks or stubs of either repo:

- **1 admit**: `acquisition.capture_url` against a local HTTP fixture this
  example's policy allows. The child process runs, performs a real HTTP GET,
  and returns a real `CaptureUrlResult`; a matching admission+outcome SRS
  receipt pair is emitted.
- **3 refuse**, each verified against an external sentinel (a fixture-server
  hit counter, not merely the returned decision — this is the strongest
  part of the evidence: refusal is proven by what did *not* happen
  externally, not by DAGR self-reporting `"refused"`):
  - `acquisition.capture_url` against a *second*, out-of-scope fixture URL —
    refused by this example's own policy layer; that fixture's hit counter
    must stay at 0.
  - `acquisition.process_source` — refused before the child is ever spawned
    (this showcase's launcher wires no `observer`, so the surface itself
    would fail closed with `McpSurfaceError` if this tool were ever
    actually invoked; refusing it here also keeps this proof decoupled from
    authoring's real, in-flight usage of this same tool — see "Status"
    above); the in-scope fixture's hit counter must stay unchanged from the
    admit case.
  - `acquisition.delete_everything` — a tool name not in the connector's own
    `known_tools` allowlist at all, refused fail-closed by the connector
    itself, before any policy resolver runs and before any admission
    receipt is emitted.

**What this does *not* claim:** this example does not demonstrate that
"acquisition is governed" in general, nor any aggregate trust / safety /
verification verdict about acquisition, its captured content, or
Counterpedia standing. A DAGR admission/outcome receipt records that a call
was admitted and observed at this boundary — it is **not** acquisition's own
source/capture/provenance evidence and does not establish source truth,
custody, verification, or Counterpedia admission. See the ecosystem
invariant: emitter assertion ≠ independently-recomputed finding; disclosure
≠ verdict.

## Prerequisites

- Python >= 3.11 (this example was run against dagr-mcp's own `.venv`,
  Python 3.13)
- A local checkout of `dagr-mcp` with its `official-sdk` extra installed
  (`mcp==1.29.0`, `anyio`, `dagr_mcp_sdk_binding`)
- A local checkout of `counterpedia-acquisition` (its base package has zero
  MCP dependency; this example only needs the `mcp` package importable in
  *dagr-mcp's* environment, since `live_run.py` launches the child with
  `PYTHONPATH=<acquisition>/src` against dagr-mcp's own interpreter — no
  separate install of `counterpedia-acquisition` or its `[mcp]` extra is
  required)

## Run

```bash
cd dagr-mcp
export DAGR_MCP_SHOWCASE_WORKDIR="$(mktemp -d)"

# Defaults to a sibling ../../counterpedia-acquisition checkout; override
# with --acquisition-path or ACQUISITION_REPO_PATH if yours lives elsewhere.
.venv/bin/python3 examples/counterpedia-acquisition-showcase/live_run.py
```

Nothing generated by this script (receipts, the trust bundle, or the JSON
output file) is meant to be committed — see the example-local `.gitignore`.
Signing keys are generated at runtime by `SigningIdentity.generate(...)`;
none are baked into any committed file. The two fixture HTTP servers bind to
`127.0.0.1` on OS-assigned ports and never make real external network
requests.

## Files

- `launch_acquisition_mcp.py` — standalone launcher giving
  `StdioTargetConfig.command` something runnable; wires an
  `InMemoryObjectStore` and no `observer`, so only the model-free
  acquisition tools are servable without a fail-closed `McpSurfaceError`.
- `live_run.py` — the governed run: 1 admit + 3 refuse against the real
  server, driven through DAGR-MCP-SOURCE0's own merged
  `build_acquisition_connector` factory, with fixture-server hit-counter
  checks proving the out-of-scope URL was never fetched and the in-scope
  URL was fetched exactly once, plus signed receipts written to the workdir.

## Next steps (not built here)

- Independent verification of the emitted receipts with a
  separately-installed `arcs-verify`, mirroring
  `examples/generic-stdio-showcase/verify_receipts.py`.
- **CP-DAGR-MCP-ACQ0-BIND**: wiring `counterpedia-authoring`'s
  `AcquisitionToolTransport` protocol to a
  `DagrGovernedAcquisitionToolTransport` implementation that routes through
  this same connector, so the real producer re-fetch seam
  (`ProducerAcquisitionToolClient.process_source()`) gains these receipts —
  deferred until `REAL-CONTENT-AUTHOR0` / the in-flight
  `fix/author-acq0-producer-contract-boundary-v0-1` branch settles.
