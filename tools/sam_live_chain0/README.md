# SAM-LIVE-CHAIN0 clean replay harness

This directory is a **reconstruction**, not a recovered copy of the historical
`up.sh` that was lost when the original worktree was removed. It is intentionally
kept separate from `evidence/sam-live-chain0/`, which records what actually ran
on 2026-08-26.

## Pin and posture

- google/sam `v0.1.0-alpha.7`, commit `a5f2c4ea0f95b20aa30b047c51b83a11258185c3`
- official `sam_Darwin_arm64.tar.gz`; `verify_pins.py` fails closed against the
  archive and binary SHA-256 values from the frozen evidence manifest
- loopback-only local mesh; no cloud and no source build
- mock OIDC is required; this is therefore local/offline-from-external-services,
  not air-gapped from an identity issuer
- `market_server.py` is a deterministic fixture. `settle` is not a financial event.
- `AUTHORITY_MOVEMENT=0`

## Clean replay

The release directory must have this layout:

```text
$SAM_RELEASE_ROOT/
  sam_Darwin_arm64.tar.gz
  bin/sam-control-plane
  bin/sam-router
  bin/sam-node
  bin/mcp-client
```

The Python environment used by the repo must provide its normal MCP dependencies,
plus `PyJWT` and `cryptography` for the local OIDC fixture.

```bash
export SAM_RELEASE_ROOT=/path/to/pinned/sam-alpha7
bash tools/sam_live_chain0/up.sh
python tools/sam_live_chain0/live_market0.py \
  --output .sam-live-chain0/evidence/market-audit-packet
```

`up.sh` refuses release-byte drift before starting anything, starts the local
OIDC/control-plane/router/three-node mesh, waits for all three node MCP endpoints,
and requires the native semantic path to produce `Hello, SAM!` through
`discover_remote_services → find_remote_tools → describe_remote_tool → call_remote_tool`.

`live_market0.py` then discovers exactly one `mcp://market/settle` provider as
an **operator harness step**, freezes that peer/tool into `SamRouteConfig`, and
runs the call through `execute_governed_call`. Discovery itself does not grant
eligibility.

Always tear down:

```bash
bash tools/sam_live_chain0/down.sh
```

## L06 / ARCS acceptance

ARCS verification deliberately stays outside this producer repo and must run
from the verifier's own environment. A clean replay is complete only when the
new packet yields:

- one admission receipt and one outcome receipt
- same `logical_call_id` (`req:live-market0:1`)
- admission `admitted`; outcome `result_returned`
- independent `arcs-verify` aggregate exit code `0`

The newly generated UUIDs, signatures, logs, and digests are **not expected to
be byte-identical** to the historical run. The acceptance target is structural
and constitutional equivalence, not replaying historical randomness.
