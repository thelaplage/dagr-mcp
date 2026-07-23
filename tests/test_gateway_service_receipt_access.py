"""Sprint A10 — single-handle receipt resolution (``dagr_mcp_service.access``).

Proves a returned ``ReceiptHandle`` (from both A8's in-process adapter and
A9's remote connector) resolves back to its exact, existing signed receipt
envelope through the configured ``FilesystemReceiptSource``, that every
fail-closed path in the required parse/schema/signature/identifier/family
sequence actually fails closed, and that the filesystem reader cannot be
tricked into reading outside its configured root. See
``docs/GATEWAY_SERVICE_ADAPTER_SCOPE.md`` §9/§12/§13, work package A10.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastmcp")
pytest.importorskip("mcp")

from dagr_mcp.srs_receipts import (
    RawEnvelopeFileSink,
    ReceiptContext,
    SignedReceiptEmitter,
    SigningIdentity,
    sha256_digest,
)
from dagr_mcp_service.access import (
    RECEIPT_ACCESS_DIAGNOSTIC_CODES,
    FilesystemReceiptSource,
    ReceiptAccessConfig,
    ReceiptAccessContext,
    ReceiptNotFound,
    resolve_receipt,
)
from dagr_mcp_service.adapter import GatewayAdapterConfig, execute_governed_call
from dagr_mcp_service.connectors.memory import InMemoryToolConnector
from dagr_mcp_service.contract import (
    CallerGovernedCallRequest,
    GovernedCallRequest,
    ReceiptHandle,
    TargetServerRef,
    TrustedActorRef,
    TrustedTenantRef,
)
from dagr_mcp_service.resolution import (
    FASTMCP_BINDING_VERSION,
    SDK_BINDING_VERSION,
    BindingSelectorKey,
)

from tests._gateway_service_remote_fixtures import loopback_mcp_server  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
BOTH_BINDINGS = (FASTMCP_BINDING_VERSION, SDK_BINDING_VERSION)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _identity(key_id: str = "issuer.test.access/key/1") -> SigningIdentity:
    return SigningIdentity.generate(issuer_id="issuer:test:access", key_id=key_id)


def _context(**overrides: Any) -> ReceiptContext:
    base: dict[str, Any] = dict(
        runtime_instance_id="runtime:test:access",
        boundary_id="boundary:test:access",
        policy_pack_id="policy:test:access",
        policy_pack_version="2026.07.23",
        subject_ref="tool-call:call:test",
        logical_call_id="call:test",
        binding_version="fastmcp.middleware.v0.1",
    )
    base.update(overrides)
    return ReceiptContext(**base)


def _emit_admission(
    sink: Any,
    identity: SigningIdentity,
    *,
    context: ReceiptContext | None = None,
    disposition: str = "admitted",
    tool_name: str = "echo",
    argument_digest: str | None = None,
    **kwargs: Any,
) -> str:
    emitter = SignedReceiptEmitter(identity=identity, sink=sink)
    return emitter.emit_admission(
        context=context or _context(),
        requested_tool_name=tool_name,
        argument_digest=argument_digest or sha256_digest({"x": 1}),
        disposition=disposition,
        **kwargs,
    )


def _emit_outcome(
    sink: Any,
    identity: SigningIdentity,
    *,
    admission_receipt_ref: str,
    context: ReceiptContext | None = None,
    outcome: str = "result_returned",
    **kwargs: Any,
) -> str:
    emitter = SignedReceiptEmitter(identity=identity, sink=sink)
    if outcome in ("result_returned", "error_returned") and "result_digest" not in kwargs:
        kwargs["result_digest"] = sha256_digest({"ok": True})
    return emitter.emit_outcome(
        context=context or _context(),
        admission_receipt_ref=admission_receipt_ref,
        outcome=outcome,
        **kwargs,
    )


def _read_envelopes(directory: Path) -> dict[str, dict[str, Any]]:
    envelopes: dict[str, dict[str, Any]] = {}
    for path in directory.glob("*.json"):
        if path.name == "issuer-keys.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        envelopes[data["receipt_id"]] = data
    return envelopes


def _write_raw(directory: Path, receipt_id: str, payload: bytes) -> Path:
    from dagr_mcp.srs_receipts import _SAFE_FILE  # type: ignore[attr-defined]

    filename = _SAFE_FILE.sub("_", receipt_id) + ".json"
    target = directory / filename
    target.write_bytes(payload)
    return target


def _digest(arguments: dict[str, Any]) -> str:
    return sha256_digest(dict(arguments))


def _caller_request(
    *,
    selector: str = "primary",
    target: str = "mem:fixture",
    tool: str = "echo",
    arguments: dict[str, Any],
    policy_profile_ref: str = "policy-profile:default",
    request_ref: str = "req:1",
) -> CallerGovernedCallRequest:
    return CallerGovernedCallRequest(
        request_ref=request_ref,
        binding_selector=BindingSelectorKey(key=selector),
        target_server_ref=TargetServerRef(handle=target),
        tool_name=tool,
        argument_digest=_digest(arguments),
        policy_profile_ref=policy_profile_ref,
    )


def _resolved_request(
    *, actor_ref: str = "actor:test:known", tenant_ref: str | None = None, **kwargs: Any
) -> GovernedCallRequest:
    caller = _caller_request(**kwargs)
    return GovernedCallRequest.from_caller_request(
        caller,
        actor_ref=TrustedActorRef(ref=actor_ref),
        tenant_ref=TrustedTenantRef(ref=tenant_ref) if tenant_ref is not None else None,
    )


def _build_adapter_config(
    tmp_path: Path, *, connector: Any, selector: str = "primary", binding_version: str = FASTMCP_BINDING_VERSION
) -> tuple[GatewayAdapterConfig, SigningIdentity, Path]:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    config = GatewayAdapterConfig(
        binding_registry={selector: binding_version},
        connector=connector,
        identity=identity,
        sink=sink,
        runtime_instance_id="runtime:test:gateway",
        boundary_id="boundary:test:gateway",
        policy_pack_id="policy:test:gateway",
        policy_pack_version="2026.07.23",
    )
    return config, identity, directory


async def _echo(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"echoed": True}


def _access_config(directory: Path, identity: SigningIdentity, **overrides: Any) -> ReceiptAccessConfig:
    return ReceiptAccessConfig(
        provider=FilesystemReceiptSource(root=directory),
        trust_bundle=identity.trust_bundle(),
        **overrides,
    )


# --------------------------------------------------------------------------- #
# 1/3 — a real A8 handle resolves to its exact receipt; verifier round trip   #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_a8_handle_resolves_to_its_exact_receipt(tmp_path: Path, binding_version: str) -> None:
    connector = InMemoryToolConnector({"mem:fixture": {"echo": _echo}})
    config, identity, directory = _build_adapter_config(
        tmp_path, connector=connector, binding_version=binding_version
    )
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert response.decision.disposition == "admitted"
    assert len(response.receipts) == 2
    on_disk = _read_envelopes(directory)
    access_config = _access_config(directory, identity)

    for handle in response.receipts:
        result = resolve_receipt(handle, config=access_config)
        assert result.diagnostic_code is None
        assert result.verified is not None
        assert dict(result.verified.envelope) == on_disk[handle.receipt_id]
        assert result.verified.envelope["receipt_id"] == handle.receipt_id
        assert result.verified.envelope["receipt_kind"] == handle.receipt_kind


# --------------------------------------------------------------------------- #
# 2 — a real A9 (remote) handle resolves to its exact receipt                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("binding_version", BOTH_BINDINGS)
async def test_a9_handle_resolves_to_its_exact_receipt(
    tmp_path: Path, binding_version: str, loopback_mcp_server
) -> None:
    from dagr_mcp_service.connectors.remote import RemoteTargetConfig, RemoteToolConnector

    connector = RemoteToolConnector(
        {
            "bossy:test": RemoteTargetConfig(
                handle="bossy:test",
                endpoint_uri=loopback_mcp_server.base_url,
                allow_insecure_loopback=True,
            )
        }
    )
    config, identity, directory = _build_adapter_config(
        tmp_path, connector=connector, binding_version=binding_version, selector="primary"
    )
    request = _resolved_request(arguments={"x": "hi"}, target="bossy:test", tool="echo")

    response = await execute_governed_call(request, arguments={"x": "hi"}, config=config)

    assert response.decision.disposition == "admitted"
    assert response.decision.outcome == "result"
    assert len(response.receipts) == 2
    on_disk = _read_envelopes(directory)
    access_config = _access_config(directory, identity)

    for handle in response.receipts:
        result = resolve_receipt(handle, config=access_config)
        assert result.diagnostic_code is None
        assert dict(result.verified.envelope) == on_disk[handle.receipt_id]


# --------------------------------------------------------------------------- #
# 3/38 — existing (ARCS-facing) verifier accepts the resolved envelope output #
# --------------------------------------------------------------------------- #


def test_resolved_envelope_round_trips_through_the_independent_arcs_verifier(tmp_path: Path) -> None:
    arcs_verify = pytest.importorskip("arcs_verify")
    from arcs_verify.verifier import verify_receipt

    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    admission_id = _emit_admission(sink, identity)
    handle = ReceiptHandle(receipt_id=admission_id, receipt_kind="admission")

    access_config = _access_config(directory, identity)
    result = resolve_receipt(handle, config=access_config)
    assert result.diagnostic_code is None

    schema_path = Path(arcs_verify.__file__).resolve().parent / "data" / "srs-envelope-v0.2.0.schema.json"
    report = verify_receipt(
        dict(result.verified.envelope),
        dict(identity.trust_bundle()),
        schema_path=schema_path,
        selected_profile="srs.mcp.sdk_enforcement.v0.1",
    )
    assert report.passed, report.failure_codes


def test_resolved_envelope_round_trips_through_the_repositorys_own_bundled_verifier(
    tmp_path: Path,
) -> None:
    """CI-enforced companion to the test above.

    ``arcs-verify`` is a separate, sibling project — it is not a
    pip-installable dependency of this repository and is not installed in
    this repository's own CI, so the ``importorskip``-guarded test above is
    a best-effort *local* proof only. This test proves the identical claim
    (byte-parity envelope, real JSON-Schema validation, real Ed25519
    signature verification) using only what this repository actually ships
    and actually runs in CI: the bundled schema
    (``dagr_mcp/vendor/srs/srs-envelope-v0.2.0.schema.json``, packaged into
    the wheel — see ``[tool.setuptools.package-data]``) and this
    repository's own test-only verifier (``tests/receipt_verification.py``),
    which needs only the declared ``dev`` extra's ``jsonschema`` dependency.
    """

    from tests.receipt_verification import verify_receipt as verify_with_bundled_schema

    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    admission_id = _emit_admission(sink, identity)
    handle = ReceiptHandle(receipt_id=admission_id, receipt_kind="admission")

    access_config = _access_config(directory, identity)
    result = resolve_receipt(handle, config=access_config)
    assert result.diagnostic_code is None

    schema_path = ROOT / "dagr_mcp" / "vendor" / "srs" / "srs-envelope-v0.2.0.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    # Raises on any failure; a clean return is the pass signal (matches the
    # existing convention every other caller of this test-only verifier in
    # this repository already relies on).
    verify_with_bundled_schema(dict(result.verified.envelope), dict(identity.trust_bundle()), schema)


# --------------------------------------------------------------------------- #
# 6 — unknown handle fails closed                                            #
# --------------------------------------------------------------------------- #


def test_unknown_handle_fails_closed(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    directory.mkdir()
    identity = _identity()
    handle = ReceiptHandle(receipt_id="urn:srs:receipt:admission:does-not-exist", receipt_kind="admission")

    result = resolve_receipt(handle, config=_access_config(directory, identity))

    assert result.verified is None
    assert result.diagnostic_code == "unknown_handle"


# --------------------------------------------------------------------------- #
# 7 — caller cannot supply a path                                            #
# --------------------------------------------------------------------------- #


def test_provider_seam_accepts_only_a_receipt_handle_never_a_path(tmp_path: Path) -> None:
    import inspect

    signature = inspect.signature(FilesystemReceiptSource.fetch)
    params = list(signature.parameters)
    assert params[:2] == ["self", "handle"]
    for name in ("path", "filename", "uri", "location"):
        assert name not in signature.parameters


# --------------------------------------------------------------------------- #
# 8 — traversal / absolute path / encoded traversal / separator tricks       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "malicious_receipt_id",
    [
        "../../../etc/passwd",
        "/etc/passwd",
        "..%2f..%2f..%2fetc%2fpasswd",
        "....//....//etc/passwd",
        "a/../../b",
        "\\..\\..\\windows\\system32",
    ],
)
def test_path_traversal_and_separator_tricks_cannot_escape_the_configured_root(
    tmp_path: Path, malicious_receipt_id: str
) -> None:
    directory = tmp_path / "receipts"
    directory.mkdir()
    secret = tmp_path / "outside-secret.txt"
    secret.write_text("do-not-leak", encoding="utf-8")

    identity = _identity()
    handle = ReceiptHandle(receipt_id=malicious_receipt_id, receipt_kind="admission")

    result = resolve_receipt(handle, config=_access_config(directory, identity))

    assert result.diagnostic_code == "unknown_handle"
    assert result.verified is None
    assert "do-not-leak" not in repr(result)


# --------------------------------------------------------------------------- #
# 9 — symlink escape is rejected                                             #
# --------------------------------------------------------------------------- #


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    directory.mkdir()
    secret = tmp_path / "outside-secret.json"
    secret.write_text(json.dumps({"receipt_id": "not-a-real-receipt"}), encoding="utf-8")

    receipt_id = "urn:srs:receipt:admission:sneaky"
    from dagr_mcp.srs_receipts import _SAFE_FILE  # type: ignore[attr-defined]

    filename = _SAFE_FILE.sub("_", receipt_id) + ".json"
    (directory / filename).symlink_to(secret)

    identity = _identity()
    handle = ReceiptHandle(receipt_id=receipt_id, receipt_kind="admission")

    result = resolve_receipt(handle, config=_access_config(directory, identity))

    assert result.diagnostic_code == "unknown_handle"
    assert result.verified is None


# --------------------------------------------------------------------------- #
# 10 — directory and special-file targets are rejected                       #
# --------------------------------------------------------------------------- #


def test_directory_target_is_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    directory.mkdir()
    receipt_id = "urn:srs:receipt:admission:is-a-dir"
    from dagr_mcp.srs_receipts import _SAFE_FILE  # type: ignore[attr-defined]

    filename = _SAFE_FILE.sub("_", receipt_id) + ".json"
    (directory / filename).mkdir()

    identity = _identity()
    handle = ReceiptHandle(receipt_id=receipt_id, receipt_kind="admission")

    result = resolve_receipt(handle, config=_access_config(directory, identity))

    assert result.diagnostic_code == "unknown_handle"


# --------------------------------------------------------------------------- #
# 11 — filename/handle identity cannot override envelope identity            #
# --------------------------------------------------------------------------- #


def test_filename_identity_cannot_override_envelope_identity(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    real_id = _emit_admission(sink, identity)

    # Overwrite the file the sink itself wrote (found by the exact same
    # filename a resolve for `real_id` would look up) with a DIFFERENT,
    # validly-signed envelope whose own receipt_id disagrees with the name.
    other_id = _emit_admission(sink, identity)
    other_envelope = _read_envelopes(directory)[other_id]
    from dagr_mcp.srs_receipts import _SAFE_FILE  # type: ignore[attr-defined]

    filename = _SAFE_FILE.sub("_", real_id) + ".json"
    (directory / filename).write_text(json.dumps(other_envelope), encoding="utf-8")

    handle = ReceiptHandle(receipt_id=real_id, receipt_kind="admission")
    result = resolve_receipt(handle, config=_access_config(directory, identity))

    assert result.diagnostic_code == "identifier_mismatch"
    assert result.verified is None


# --------------------------------------------------------------------------- #
# 12 — receipt-ID mismatch fails                                              #
# --------------------------------------------------------------------------- #


def test_receipt_id_mismatch_fails(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    real_id = _emit_admission(sink, identity)

    wrong_handle = ReceiptHandle(receipt_id=real_id + "-decoy", receipt_kind="admission")
    result = resolve_receipt(wrong_handle, config=_access_config(directory, identity))

    assert result.diagnostic_code == "unknown_handle"


# --------------------------------------------------------------------------- #
# 13 — receipt-family/type mismatch fails                                    #
# --------------------------------------------------------------------------- #


def test_receipt_family_mismatch_fails(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    admission_id = _emit_admission(sink, identity)

    wrong_kind_handle = ReceiptHandle(receipt_id=admission_id, receipt_kind="outcome")
    result = resolve_receipt(wrong_kind_handle, config=_access_config(directory, identity))

    assert result.diagnostic_code == "family_mismatch"
    assert result.verified is None


# --------------------------------------------------------------------------- #
# 14 — malformed JSON fails                                                   #
# --------------------------------------------------------------------------- #


def test_malformed_json_fails(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    directory.mkdir()
    receipt_id = "urn:srs:receipt:admission:garbage"
    _write_raw(directory, receipt_id, b"{not valid json::")

    identity = _identity()
    handle = ReceiptHandle(receipt_id=receipt_id, receipt_kind="admission")
    result = resolve_receipt(handle, config=_access_config(directory, identity))

    assert result.diagnostic_code == "malformed_envelope"


# --------------------------------------------------------------------------- #
# 15 — schema-invalid receipt fails                                          #
# --------------------------------------------------------------------------- #


def test_schema_invalid_receipt_fails(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    directory.mkdir()
    receipt_id = "urn:srs:receipt:admission:incomplete"
    payload = json.dumps({"receipt_id": receipt_id, "receipt_kind": "admission"}).encode()
    _write_raw(directory, receipt_id, payload)

    identity = _identity()
    handle = ReceiptHandle(receipt_id=receipt_id, receipt_kind="admission")
    result = resolve_receipt(handle, config=_access_config(directory, identity))

    assert result.diagnostic_code == "schema_failure"


# --------------------------------------------------------------------------- #
# 16 — tampered content fails signature verification                        #
# --------------------------------------------------------------------------- #


def test_tampered_content_fails_signature_verification(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    admission_id = _emit_admission(sink, identity)

    envelope = _read_envelopes(directory)[admission_id]
    tampered = copy.deepcopy(envelope)
    tampered["requested_tool_name"] = "not-the-original-tool"
    from dagr_mcp.srs_receipts import _SAFE_FILE  # type: ignore[attr-defined]

    filename = _SAFE_FILE.sub("_", admission_id) + ".json"
    (directory / filename).write_text(json.dumps(tampered), encoding="utf-8")

    handle = ReceiptHandle(receipt_id=admission_id, receipt_kind="admission")
    result = resolve_receipt(handle, config=_access_config(directory, identity))

    assert result.diagnostic_code == "signature_failure"


# --------------------------------------------------------------------------- #
# 17 — valid receipt signed by an untrusted key fails                        #
# --------------------------------------------------------------------------- #


def test_receipt_signed_by_an_untrusted_key_fails(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    trusted_identity = _identity()
    untrusted_identity = SigningIdentity.generate(
        issuer_id="issuer:test:untrusted", key_id="issuer.test.untrusted/key/1"
    )
    admission_id = _emit_admission(sink, untrusted_identity)

    handle = ReceiptHandle(receipt_id=admission_id, receipt_kind="admission")
    # Verify against the *trusted* identity's own keyring, which never
    # contains the untrusted issuer's key at all.
    result = resolve_receipt(handle, config=_access_config(directory, trusted_identity))

    assert result.diagnostic_code == "signature_failure"


def test_receipt_from_a_key_explicitly_marked_untrusted_fails(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    admission_id = _emit_admission(sink, identity)

    bundle = copy.deepcopy(identity.trust_bundle())
    bundle["issuers"][0]["trusted"] = False

    handle = ReceiptHandle(receipt_id=admission_id, receipt_kind="admission")
    config = ReceiptAccessConfig(provider=FilesystemReceiptSource(root=directory), trust_bundle=bundle)
    result = resolve_receipt(handle, config=config)

    assert result.diagnostic_code == "signature_failure"


# --------------------------------------------------------------------------- #
# 20/21 — applicable actor/tenant mismatch fails                             #
# --------------------------------------------------------------------------- #


def test_applicable_actor_mismatch_fails(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    admission_id = _emit_admission(sink, identity, context=_context(actor_ref="actor:owner"))

    handle = ReceiptHandle(receipt_id=admission_id, receipt_kind="admission")
    context = ReceiptAccessContext(actor_ref="actor:someone-else")
    result = resolve_receipt(handle, config=_access_config(directory, identity), context=context)

    assert result.diagnostic_code == "association_mismatch"


def test_applicable_tenant_mismatch_fails(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    admission_id = _emit_admission(
        sink, identity, context=_context(actor_ref="actor:owner", tenant_id="tenant:owner")
    )

    handle = ReceiptHandle(receipt_id=admission_id, receipt_kind="admission")
    context = ReceiptAccessContext(tenant_ref="tenant:someone-else")
    result = resolve_receipt(handle, config=_access_config(directory, identity), context=context)

    assert result.diagnostic_code == "association_mismatch"


def test_absent_envelope_actor_ref_is_not_applicable_and_does_not_mismatch(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    # No actor_ref supplied to the emit at all -> not present on the envelope.
    admission_id = _emit_admission(sink, identity, context=_context())

    handle = ReceiptHandle(receipt_id=admission_id, receipt_kind="admission")
    context = ReceiptAccessContext(actor_ref="actor:whoever")
    result = resolve_receipt(handle, config=_access_config(directory, identity), context=context)

    assert result.diagnostic_code is None
    assert result.verified is not None


# --------------------------------------------------------------------------- #
# access_unauthorized / context-unavailable posture                          #
# --------------------------------------------------------------------------- #


def test_missing_required_actor_context_refuses_before_touching_the_provider(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    admission_id = _emit_admission(sink, identity)

    calls: list[Any] = []

    class _SpyProvider:
        def fetch(self, handle, **kwargs):
            calls.append(handle)
            return FilesystemReceiptSource(root=directory).fetch(handle, **kwargs)

    handle = ReceiptHandle(receipt_id=admission_id, receipt_kind="admission")
    config = ReceiptAccessConfig(
        provider=_SpyProvider(), trust_bundle=identity.trust_bundle(), require_actor_context=True
    )
    result = resolve_receipt(handle, config=config)

    assert result.diagnostic_code == "access_unauthorized"
    assert calls == []


# --------------------------------------------------------------------------- #
# provider_failure never leaks the underlying exception content              #
# --------------------------------------------------------------------------- #


def test_unexpected_provider_exception_becomes_a_content_free_provider_failure(tmp_path: Path) -> None:
    class _BrokenProvider:
        def fetch(self, handle, **kwargs):
            raise RuntimeError("super secret internal detail")

    identity = _identity()
    handle = ReceiptHandle(receipt_id="urn:srs:receipt:admission:whatever", receipt_kind="admission")
    config = ReceiptAccessConfig(provider=_BrokenProvider(), trust_bundle=identity.trust_bundle())
    result = resolve_receipt(handle, config=config)

    assert result.diagnostic_code == "provider_failure"
    assert "super secret internal detail" not in repr(result)


# --------------------------------------------------------------------------- #
# 24/25 — one immutable byte snapshot; no TOCTOU reread after verification    #
# --------------------------------------------------------------------------- #


def test_bytes_are_read_exactly_once_per_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    admission_id = _emit_admission(sink, identity)

    open_calls: list[Any] = []
    real_open = os.open

    def _counting_open(path, flags, *args, **kwargs):
        open_calls.append(path)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", _counting_open)

    handle = ReceiptHandle(receipt_id=admission_id, receipt_kind="admission")
    result = resolve_receipt(handle, config=_access_config(directory, identity))

    assert result.diagnostic_code is None
    assert len(open_calls) == 1


def test_a_later_on_disk_mutation_cannot_change_an_already_returned_envelope(tmp_path: Path) -> None:
    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    admission_id = _emit_admission(sink, identity)

    handle = ReceiptHandle(receipt_id=admission_id, receipt_kind="admission")
    access_config = _access_config(directory, identity)
    first = resolve_receipt(handle, config=access_config)
    assert first.diagnostic_code is None
    snapshot = dict(first.verified.envelope)

    from dagr_mcp.srs_receipts import _SAFE_FILE  # type: ignore[attr-defined]

    filename = _SAFE_FILE.sub("_", admission_id) + ".json"
    (directory / filename).write_text('{"receipt_id": "mutated-after-the-fact"}', encoding="utf-8")

    assert dict(first.verified.envelope) == snapshot
    assert first.verified.envelope["receipt_id"] == admission_id


# --------------------------------------------------------------------------- #
# 26/27/28 — default handle-only behavior unaffected; inline is operator-run  #
# --------------------------------------------------------------------------- #


async def test_execute_governed_call_stays_handle_only_and_unmodified_by_this_lane(tmp_path: Path) -> None:
    connector = InMemoryToolConnector({"mem:fixture": {"echo": _echo}})
    config, _identity_obj, _directory = _build_adapter_config(tmp_path, connector=connector)
    request = _resolved_request(arguments={"x": 1})

    response = await execute_governed_call(request, arguments={"x": 1}, config=config)

    assert all(handle.location_handle is None for handle in response.receipts)


def test_inline_access_is_a_separate_operator_invoked_operation_not_a_request_field() -> None:
    import inspect

    from dagr_mcp_service.contract import CallerGovernedCallRequest

    fields = {f for f in inspect.signature(CallerGovernedCallRequest).parameters}
    assert "inline" not in fields
    assert "include_receipts" not in fields
    assert not any("inline" in f or "access" in f for f in fields)


# --------------------------------------------------------------------------- #
# 29 — no path, signer, key, raw args, or credential ever appears in result   #
# --------------------------------------------------------------------------- #


def test_no_sensitive_material_appears_in_repr_of_results_or_config(tmp_path: Path) -> None:
    import base64

    from cryptography.hazmat.primitives import serialization

    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    admission_id = _emit_admission(sink, identity)

    handle = ReceiptHandle(receipt_id=admission_id, receipt_kind="admission")
    access_config = _access_config(directory, identity)
    result = resolve_receipt(handle, config=access_config)

    assert str(directory) not in repr(result)
    assert str(directory) not in repr(access_config.provider)

    private_bytes = identity.private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    private_b64 = base64.urlsafe_b64encode(private_bytes).decode("ascii")
    assert private_b64 not in repr(result)
    assert private_b64 not in repr(access_config)


# --------------------------------------------------------------------------- #
# 30 — concurrent resolutions remain isolated                                 #
# --------------------------------------------------------------------------- #


def test_concurrent_resolutions_do_not_cross_handles_or_contexts(tmp_path: Path) -> None:
    import concurrent.futures

    directory = tmp_path / "receipts"
    sink = RawEnvelopeFileSink(directory)
    identity = _identity()
    ids = [
        _emit_admission(
            sink, identity, context=_context(logical_call_id=f"call:{i}", actor_ref=f"actor:{i}")
        )
        for i in range(8)
    ]
    handles = [ReceiptHandle(receipt_id=receipt_id, receipt_kind="admission") for receipt_id in ids]
    access_config = _access_config(directory, identity)

    def _resolve(index: int) -> tuple[int, Any]:
        context = ReceiptAccessContext(actor_ref=f"actor:{index}")
        return index, resolve_receipt(handles[index], config=access_config, context=context)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_resolve, range(8)))

    for index, result in results:
        assert result.diagnostic_code is None
        assert result.verified.envelope["logical_call_id"] == f"call:{index}"
        assert result.verified.envelope["actor_ref"] == f"actor:{index}"


# --------------------------------------------------------------------------- #
# 32/33 — no subscription/streaming/watcher/polling/background task/host      #
# --------------------------------------------------------------------------- #


def test_no_subscription_streaming_watcher_polling_background_task_or_host_surface() -> None:
    source = (ROOT / "dagr_mcp_service" / "access.py").read_text(encoding="utf-8")
    forbidden = (
        "subscri",
        "streaming",
        "watcher",
        "poll_",
        "asyncio.create_task",
        "threading.Thread",
        "uvicorn",
        "fastapi",
        "starlette",
        "asgi",
        "socketserver",
    )
    lowered = source.lower()
    for token in forbidden:
        assert token not in lowered, f"forbidden token found in access.py: {token!r}"


# --------------------------------------------------------------------------- #
# 34 — no new receipt family or schema                                        #
# --------------------------------------------------------------------------- #


def test_access_module_never_signs_or_mints_a_receipt() -> None:
    source = (ROOT / "dagr_mcp_service" / "access.py").read_text(encoding="utf-8")
    for forbidden in (
        "import SignedReceiptEmitter",
        "SignedReceiptEmitter(",
        ".sign_envelope(",
        ".emit_admission(",
        ".emit_outcome(",
        "import RawEnvelopeFileSink",
        "RawEnvelopeFileSink(",
    ):
        assert forbidden not in source, f"forbidden construct found in access.py: {forbidden!r}"


# --------------------------------------------------------------------------- #
# 35 — package import remains lazy and opens no files                        #
# --------------------------------------------------------------------------- #


def test_importing_the_access_module_does_not_eagerly_import_transport_or_open_files() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys\n"
                "import dagr_mcp_service\n"
                "import dagr_mcp_service.access\n"
                "assert 'mcp' not in sys.modules, 'mcp imported at access module import'\n"
                "assert 'fastmcp' not in sys.modules, 'fastmcp imported at access module import'\n"
                "assert 'httpx' not in sys.modules, 'httpx imported at access module import'\n"
                "assert 'jsonschema' not in sys.modules, 'jsonschema imported at access module import'\n"
                "print('OK')\n"
            ),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "OK" in completed.stdout


def test_access_is_reachable_as_a_lazy_attribute_of_the_service_package() -> None:
    import dagr_mcp_service

    module = dagr_mcp_service.access
    assert module.__name__ == "dagr_mcp_service.access"


# --------------------------------------------------------------------------- #
# closed diagnostic vocabulary sanity                                        #
# --------------------------------------------------------------------------- #


def test_diagnostic_vocabulary_is_closed_and_content_free() -> None:
    assert len(RECEIPT_ACCESS_DIAGNOSTIC_CODES) == len(set(RECEIPT_ACCESS_DIAGNOSTIC_CODES))
    for code in RECEIPT_ACCESS_DIAGNOSTIC_CODES:
        assert isinstance(code, str) and code
        assert " " not in code
