---
id: CLOSE_MEMO_gateway_a7_contract_models_JUL19
title: Gateway lane close memo -- A7 neutral call contract and models
date: 2026-07-19
classification: Internal / Feature / Lane Close
status: Draft
---

## Scope

This lane implements work package A7 of the DAGR Gateway Service
Adapter, as scoped in PR #12 (`docs/GATEWAY_SERVICE_ADAPTER_SCOPE.md`,
base `88c66d8aa149d5b8c5fe79a8c5eff0a1a41f83db`): "Contract and models
only." It adds one new package, `dagr_mcp_service`, and its test
coverage. It does not add `adapter.py` (`execute_governed_call`
orchestration, A8), `connectors/` (client-side transport forwarders,
A9), or `access.py` (receipt-handle resolution seam, A10). This lane
performed no redesign of the A6 scope document and no additional
style pass beyond the formatting already present at session start.

## Files added

- `dagr_mcp_service/__init__.py` -- package root; pure metadata
  (`SERVICE_PACKAGE_ID`, `SERVICE_PACKAGE_VERSION`) plus PEP 562 lazy
  submodule binding for `contract` and `resolution`, matching the
  lazy-import discipline already established by `dagr_mcp_lifecycle`
  and `dagr_mcp_sdk_binding`.
- `dagr_mcp_service/contract.py` -- the two-stage request contract and
  the response model. Public types: `CallerGovernedCallRequest`,
  `GovernedCallRequest`, `TrustedActorRef`, `TrustedTenantRef`,
  `TargetServerRef`, `GovernedCallResponse`, `GovernedDecision`,
  `ReceiptHandle`, `BusinessResult`, `CancellationFacts`,
  `GatewayDiagnosticCode`, plus the module constants
  `GATEWAY_DIAGNOSTIC_CODES`, `ALL_DIAGNOSTIC_CODES`,
  `PROHIBITED_CALLER_AUTHORITY_KEYS`, `SERVICE_ID`, `SERVICE_VERSION`,
  `BOUNDARY_TYPE`.
- `dagr_mcp_service/resolution.py` -- binding-selector types and the
  one pure lookup function A7's acceptance criteria name explicitly.
  Public types: `BindingSelectorKey`, `BindingHandle`,
  `BindingResolutionRefused`, `BindingResolutionFailureReason`, the
  function `select_binding(...)`, and the constants
  `FASTMCP_BINDING_VERSION`, `SDK_BINDING_VERSION`,
  `SUPPORTED_BINDING_VERSIONS`.
- `tests/test_gateway_service_contract.py` -- 45 tests covering the
  contract module.
- `tests/test_gateway_service_resolution.py` -- 28 tests covering the
  resolution module.

## Two-stage caller/resolved authority boundary

Per scope §3.3, a caller must not be able to assert trusted actor or
tenant identity, role, policy outcome, organization authority, a
credential, a signing identity, an arbitrary receipt id, an arbitrary
custody disposition, or an arbitrary binding-version stamp. This is
enforced structurally, not by convention:

- `CallerGovernedCallRequest` is the public, untrusted, caller-facing
  input type. It has no `actor_ref`/`tenant_ref`/credential/role/
  policy/binding-version-stamp field at all -- there is nowhere on the
  type to put one. Its `from_untrusted_mapping(...)` deserializer
  checks incoming payload keys against a closed allowlist and raises
  `ValueError` on any key outside it, including every key named in
  `PROHIBITED_CALLER_AUTHORITY_KEYS`. An unrecognized key is refused
  the same way a named prohibited key is -- never silently dropped.
- `GovernedCallRequest` is the internal, service-resolved request. Its
  `actor_ref`/`tenant_ref` fields are reachable only via
  `from_caller_request(...)`, which takes them as separate
  keyword-only arguments the caller payload cannot supply. The method
  never reads a trust value off the `CallerGovernedCallRequest` it is
  given, because that type carries none.

Neither type, nor `select_binding(...)`, performs actor/tenant
resolution from a transport or auth context -- there is no transport
context anywhere in this package. A8's adapter is the intended caller
of `from_caller_request(...)`, supplying `actor_ref`/`tenant_ref` from
its own trusted-context resolver.

## Selector unknown/unavailable fail-closed behavior

`select_binding(binding_registry, selector, ...)` resolves a caller
opaque `BindingSelectorKey` against operator-provided configuration
and returns either a `BindingHandle` or a `BindingResolutionRefused`.
There is no third outcome:

- selector key absent from `binding_registry`, or present but mapped
  to a value outside `SUPPORTED_BINDING_VERSIONS` -> refused with
  `reason="unknown_binding"`;
- selector key resolves to a supported binding version whose
  underlying library is not importable (via a pure
  `importlib.util.find_spec` probe, never an actual import) ->
  refused with `reason="binding_unavailable"`.

Both `reason` values reuse the exact spellings
`dagr_mcp_service.contract.GATEWAY_DIAGNOSTIC_CODES` already names, so
a caller can carry the value straight onto
`GovernedCallResponse.diagnostic_code` without re-spelling it.
`select_binding(...)` never substitutes a different binding for an
unknown or unavailable one, and imports no binding implementation
module itself (`tests/test_gateway_service_resolution.py::test_select_binding_imports_no_binding_module`
covers this).

## Tests and package results

```
$HOME/Developer/repos/dagr-mcp/.venv/bin/pytest tests/test_gateway_service_contract.py tests/test_gateway_service_resolution.py -q
73 passed in 0.79s

$HOME/Developer/repos/dagr-mcp/.venv/bin/pytest -q
601 passed, 2 skipped in 6.47s

$HOME/Developer/repos/dagr-mcp/.venv/bin/python tools/check_public_release.py .
PASS: 0 finding(s)
```

Wheel (`dagr_mcp-0.1.0-py3-none-any.whl`) and sdist
(`dagr_mcp-0.1.0.tar.gz`) both built successfully via `python -m
build` and both contain all three `dagr_mcp_service` modules
(`__init__.py`, `contract.py`, `resolution.py`). `git diff --cached
--check` reported no whitespace errors on the staged change set.
Build, `*.egg-info`, `__pycache__`, `*.pyc`, and `.pytest_cache`
artifacts produced during verification were removed before commit.

Known, out-of-scope FastMCP main-prerelease canary warnings/skips in
the full suite were left untouched per this lane's instructions.

## What this lane explicitly does not add

- **Transport.** No socket, HTTP/ASGI listener, or MCP transport
  binding of any kind. `dagr_mcp_service` is importable with neither
  `mcp` nor `fastmcp` installed (`test_fresh_import_of_contract_does_not_pull_in_transport_or_storage_libraries`,
  `test_fresh_import_of_service_package_does_not_pull_in_transport_or_storage_libraries`,
  `test_fresh_import_of_resolution_does_not_pull_in_mcp_or_fastmcp`).
- **Execution.** No tool is invoked, no binding is constructed or
  called; `select_binding(...)` performs a dict lookup plus one
  availability probe and returns before any execution step.
- **Receipt emission.** `ReceiptHandle` is a typed reference wrapper
  only -- this package never mints, signs, or persists a receipt.
- **Tenant lookup.** No directory, database, or auth-context query of
  any kind; `TrustedTenantRef`/`TrustedActorRef` wrap an
  already-resolved string supplied by the caller of
  `from_caller_request(...)`.
- **Credential parsing.** No credential, signing identity, or
  policy-decision value is read, parsed, or accepted anywhere in this
  package; `PROHIBITED_CALLER_AUTHORITY_KEYS` names these fields
  precisely so `from_untrusted_mapping(...)` can refuse them.
- **Idempotency / exactly-once behavior.** No deduplication key,
  durable replay ledger, or exactly-once guarantee is encoded by any
  type in this package (§11 of the scope document leaves this
  explicitly open); `test_no_idempotency_or_exactly_once_surface_on_the_contract_types`
  covers the absence.

## A8 boundary

A8 ("Adapter -- `execute_governed_call` orchestration") is the next
work package. It is the first component in this lineage permitted to:

1. resolve `actor_ref`/`tenant_ref` from an authenticated transport or
   auth context and call `GovernedCallRequest.from_caller_request(...)`
   with the result;
2. call `dagr_mcp_service.resolution.select_binding(...)` with a real
   operator-provided `binding_registry` and act on its result;
3. invoke a resolved binding to actually forward a call (A9's
   connectors do the transport-level forward; A8 orchestrates around
   it);
4. construct a `GovernedCallResponse` from a real lifecycle outcome,
   including emitting and referencing real `ReceiptHandle`s.

Everything up to and including that first `execute_governed_call`
invocation remains out of scope for this repository until A8 lands;
`dagr_mcp_service` as it stands after this lane contains no code path
that performs any of the four items above.
