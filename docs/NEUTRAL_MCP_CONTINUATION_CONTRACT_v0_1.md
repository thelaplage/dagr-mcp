# DAGR MCP Neutral Continuation Contract (v0.1)

This document describes the **framework-neutral continuation contract**
introduced by this package: `dagr_mcp_continuation/__init__.py`. It represents
the identity and round linkage of a paused-and-resumable MCP call, and enforces
the ratified admission prerequisite before a continuation is ever built.

`dagr_mcp_continuation` is a new top-level sibling package — `dagr_mcp`,
`dagr_mcp_lifecycle`, and `dagr_mcp_sdk_binding` each already carry their own
frozen, walked public-surface snapshot, and any new file placed inside an
existing one of those packages is discovered by that walk. A new sibling
package keeps this addition outside every existing frozen package-surface
snapshot, with no golden, dependency, package-root export, or
packaging-configuration change: the existing `include = ["dagr_mcp*"]`
setuptools discovery pattern already covers it.

## Authority

Authorized by the DAGR MCP 2026-07-28 Decision Ratification Record v0.1,
merged in `garp-doctrine` at `33099657b5beb41e2388018183aaf2a1e8f31659`. That
record ratifies exactly one immediate implementation package — this one — as
additive, framework-neutral work. It does not authorize a production
migration, an SDK-v2 binding, a FastMCP-4 spike, or any receipt/profile
change.

## Scope

This is a **framework-neutral contract only**. It imports nothing beyond the
Python standard library's dataclass facilities and the existing canonical
neutral lifecycle vocabulary in `dagr_mcp_lifecycle.contract`. It contains no
MCP wire type, no official SDK type, no FastMCP type, and no JSON-RPC/HTTP/
Tasks type. Mapping this contract onto any concrete wire representation is
adapter-owned work that comes later; this package does not do it.

## Identity and round linkage

`ContinuationIdentity` is an adapter-supplied, immutable record of exactly:

```python
interaction_id: str        # stable across the whole interaction
request_id: str            # this attempt only — fresh on every retry
parent_request_id: str     # links this attempt to its immediate predecessor
round_number: int          # adapter-supplied round count
```

Every value comes from the caller. This module mints no identifier, no clock
value, no hash, and no round number — it only validates what it is given, and
preserves accepted strings byte-for-byte (surrounding whitespace may cause
rejection, but never rewriting).

`ContinuationIdentity` fails closed unless:

- all three IDs are non-empty strings once whitespace-only values are
  rejected;
- `interaction_id != request_id`;
- `request_id != parent_request_id`;
- `round_number` is an actual `int` (not `bool`) and `>= 1`.

## The admission prerequisite

`require_continuation_admission` enforces the ratified simultaneous gate:

```text
execution_proceeds is True
admission_recorded is True
admission_record is not None
```

All three conditions are checked by identity, not truthiness: a truthy
non-Boolean such as `1` or `"true"` does not satisfy either Boolean condition.
Any other combination — including every refused, deferred, or
unrecorded-admission path — raises `ContinuationContractError` with the
message:

```text
Refused, deferred, or unrecorded-admission paths cannot continue.
```

The opaque `admission_record` is checked only for identity against `None`. It
is never stored, serialized, inspected, or exposed by this module.

## The outcome boundary

`NeutralContinuation` pairs a validated `ContinuationIdentity` with the
existing canonical `InputRequiredMode` outcome from
`dagr_mcp_lifecycle.contract`, and accepts only its `continuable` value.

- **`continuable`** is the only outcome eligible for a neutral continuation.
- **`interrupted`** — the other existing mode of the same type — remains
  unsupported here, exactly as it is unsupported by the current FastMCP
  binding mask.
- `input_required` (the outer neutral outcome), `completed`, `refused`,
  `deferred`, `error`, `indeterminate`, and any other string are all rejected
  rather than normalized into `continuable`. No exception is ever converted
  into a continuation.

`input_required` remains adapter-level future mapping. This contract does not
name or model any wire `resultType`.

## The builder

`build_neutral_continuation` is a pure constructor:

1. enforces the admission prerequisite;
2. enforces the exact `continuable` outcome;
3. returns a `NeutralContinuation` containing only the validated identity and
   outcome.

It does not accept or inspect raw request state or wire material — no
`requestState`, `inputRequests`, `inputResponses`, `headers`, `Authorization`,
`cookies`, `Mcp-Param-*` values, trace baggage, or wire `resultType`/
`clientInfo`. It is keyword-only, so an unexpected keyword argument (for
example a raw `requestState` blob) raises `TypeError` rather than being
silently accepted. It does not catch arbitrary exceptions.

## Minimal example

```python
from dagr_mcp_continuation import (
    ContinuationIdentity,
    build_neutral_continuation,
)

identity = ContinuationIdentity(
    interaction_id="interaction-example",
    request_id="request-round-2",
    parent_request_id="request-round-1",
    round_number=2,
)

continuation = build_neutral_continuation(
    outcome="continuable",
    identity=identity,
    execution_proceeds=True,
    admission_recorded=True,
    admission_record=admission_record,  # opaque; supplied by the adapter
)
```

No UUID generation and no clock reads appear in this example — both IDs are
caller-supplied placeholders, exactly as the contract requires.

## What stays frozen

This package changes nothing about the existing v0.1 surface:

- `dagr_mcp_lifecycle/contract.py` and `dagr_mcp_lifecycle/__init__.py` are
  byte-unchanged, including their package-root exports.
- The existing FastMCP binding (`dagr_mcp.fastmcp_binding`,
  `dagr_mcp.srs_receipts`, `dagr_mcp.srs_bridge`) is untouched.
- The official SDK binding (`dagr_mcp_sdk_binding`) is untouched.
- No receipt byte, SRS profile, verifier behavior, or existing golden changes.
- Production remains on FastMCP 3 (`fastmcp>=3.4.4,<4`) and the current v1
  official-SDK binding identity (`official-mcp-sdk.python.v0.1`).

## Explicit non-authorizations

This package does **not** implement, and its existence does not authorize:

- official MCP SDK v2;
- FastMCP 4;
- SRS profile v0.2;
- ARCS Verify profile v0.2;
- any receipt change;
- any golden change;
- Tasks parity;
- Bossy;
- a production migration.

Each of the above requires its own isolated branch/PR, its own scope, and its
own independent review — no implicit authorization follows from appearing in
this document.
