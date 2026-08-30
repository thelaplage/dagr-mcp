from __future__ import annotations

import json
from pathlib import Path

from dagr_mcp_core.external_profile_receipts import (
    ExternalProfileReceiptContract,
    ExternalProfileSignedReceiptEmitter,
)
from dagr_mcp_core.srs_receipts import RawEnvelopeFileSink, ReceiptContext, SigningIdentity


def test_exception_outcome_stays_inside_application_namespace(tmp_path: Path) -> None:
    contract = ExternalProfileReceiptContract(
        profile_id="org.counterpedia.srs.mcp_read.v1",
        profile_version="v1",
        emitter_id="dagr-mcp:counterpedia-read",
        extension_namespace="org.counterpedia",
        admission_receipt_type="org.counterpedia.mcp.read.admission",
        outcome_receipt_type="org.counterpedia.mcp.read.outcome",
        envelope_contract_id="srs-envelope-v0-next",
        envelope_contract_version="v0-next",
        envelope_contract_digest="sha256:" + "1" * 64,
        profile_contract_digest="sha256:" + "2" * 64,
    )
    emitter = ExternalProfileSignedReceiptEmitter(
        contract=contract,
        identity=SigningIdentity.generate(issuer_id="issuer:test", key_id="key:test"),
        sink=RawEnvelopeFileSink(tmp_path),
        receipt_id_factory=lambda kind: f"receipt:{kind}",
        issued_at_factory=lambda: "2026-08-30T00:00:00Z",
    )
    context = ReceiptContext(
        runtime_instance_id="runtime:test",
        boundary_id="boundary:test",
        policy_pack_id="policy:test",
        policy_pack_version="1",
        subject_ref="subject:test",
        logical_call_id="call:test",
        binding_version="official-mcp-sdk.python.v0.2",
    )
    receipt_id = emitter.emit_outcome(
        context=context,
        admission_receipt_ref="receipt:admission",
        outcome="exception",
        exception_class="RuntimeError",
    )
    path = tmp_path / (receipt_id.replace(":", "_") + ".json")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert "mcp" not in receipt["extensions"]
    assert receipt["extensions"]["org.counterpedia"]["exception_class"] == "RuntimeError"
