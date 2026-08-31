from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from dagr_mcp_core.external_profile_receipts import (
    ARCS_SRS_EXTERNAL_PROFILE_SCHEMA_GIT_BLOB,
    ARCS_SRS_VNEXT_ENVELOPE_GIT_BLOB,
    ExternalProfileReceiptContract,
    ExternalProfileSignedReceiptEmitter,
)
from dagr_mcp_core.srs_receipts import RawEnvelopeFileSink, ReceiptContext, SigningIdentity

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "arcs_srs_483c73e0"
_ENVELOPE_SCHEMA_PATH = _FIXTURE_ROOT / "envelope-v0-next.schema.json"
_PROFILE_SCHEMA_PATH = _FIXTURE_ROOT / "external-profile-declaration.schema.json"


def _git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def _context() -> ReceiptContext:
    return ReceiptContext(
        runtime_instance_id="runtime:test",
        boundary_id="boundary:test",
        policy_pack_id="policy:test",
        policy_pack_version="1",
        subject_ref="subject:test",
        logical_call_id="call:test",
        binding_version="official-mcp-sdk.python.v0.2",
    )


def _emitter(directory: Path, contract: ExternalProfileReceiptContract) -> ExternalProfileSignedReceiptEmitter:
    counter = {"value": 0}

    def receipt_id(kind: str) -> str:
        counter["value"] += 1
        return f"receipt:{kind}:{counter['value']}"

    return ExternalProfileSignedReceiptEmitter(
        contract=contract,
        identity=SigningIdentity.generate(issuer_id="issuer:test", key_id="key:test"),
        sink=RawEnvelopeFileSink(directory),
        receipt_id_factory=receipt_id,
        issued_at_factory=lambda: "2026-08-30T00:00:00Z",
    )


def _load(directory: Path, receipt_id: str) -> dict:
    return json.loads(
        (directory / (receipt_id.replace(":", "_") + ".json")).read_text(encoding="utf-8")
    )


def test_schema_fixtures_are_exact_final_arcs_git_blobs() -> None:
    assert _git_blob_sha(_ENVELOPE_SCHEMA_PATH.read_bytes()) == ARCS_SRS_VNEXT_ENVELOPE_GIT_BLOB
    assert _git_blob_sha(_PROFILE_SCHEMA_PATH.read_bytes()) == ARCS_SRS_EXTERNAL_PROFILE_SCHEMA_GIT_BLOB


def test_profile_declaration_conforms_to_exact_arcs_external_profile_schema(
    external_profile_declaration: dict,
) -> None:
    schema = json.loads(_PROFILE_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(external_profile_declaration)


def test_all_emitted_vnext_variants_conform_to_exact_arcs_envelope_schema(
    tmp_path: Path,
    external_profile_contract: ExternalProfileReceiptContract,
) -> None:
    schema = json.loads(_ENVELOPE_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    emitter = _emitter(tmp_path, external_profile_contract)
    context = _context()

    admission_id = emitter.emit_admission(
        context=context,
        requested_tool_name="get_entry",
        argument_digest="sha256:" + "a" * 64,
        disposition="admitted",
    )
    result_id = emitter.emit_outcome(
        context=context,
        admission_receipt_ref=admission_id,
        outcome="result_returned",
        result_digest="sha256:" + "b" * 64,
    )
    indeterminate_id = emitter.emit_outcome(
        context=context,
        admission_receipt_ref=admission_id,
        outcome="indeterminate",
        binding_owned_fields={
            "request_cancelled": True,
            "execution_state_unknown": True,
            "delivery_incomplete": True,
        },
    )
    exception_id = emitter.emit_outcome(
        context=context,
        admission_receipt_ref=admission_id,
        outcome="exception",
        exception_class="RuntimeError",
    )

    for receipt_id in (admission_id, result_id, indeterminate_id, exception_id):
        validator.validate(_load(tmp_path, receipt_id))
