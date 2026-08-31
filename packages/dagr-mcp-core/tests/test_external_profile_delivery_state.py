from __future__ import annotations

import json
from pathlib import Path

from dagr_mcp_core.external_profile_receipts import (
    ExternalProfileReceiptContract,
    ExternalProfileSignedReceiptEmitter,
)
from dagr_mcp_core.srs_receipts import RawEnvelopeFileSink, ReceiptContext, SigningIdentity


def test_indeterminate_delivery_state_is_namespaced_not_top_level(
    tmp_path: Path,
    external_profile_contract: ExternalProfileReceiptContract,
) -> None:
    emitter = ExternalProfileSignedReceiptEmitter(
        contract=external_profile_contract,
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
        outcome="indeterminate",
        binding_owned_fields={
            "request_cancelled": True,
            "execution_state_unknown": True,
            "delivery_incomplete": True,
        },
    )
    path = tmp_path / (receipt_id.replace(":", "_") + ".json")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    for key in ("request_cancelled", "execution_state_unknown", "delivery_incomplete"):
        assert key not in receipt
    assert receipt["extensions"]["org.counterpedia"]["delivery_state"] == {
        "request_cancelled": True,
        "execution_state_unknown": True,
        "delivery_incomplete": True,
    }
