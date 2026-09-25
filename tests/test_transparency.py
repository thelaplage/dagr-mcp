from __future__ import annotations

from dataclasses import dataclass

import pytest

from dagr_mcp.transparency import (
    PublishingReceiptSink,
    TransparencyPublicationRequest,
    TransparencyPublicationResult,
    TransparencyPublicationState,
)


class RecordingInnerSink:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.calls = []

    def write(self, envelope):
        self.calls.append(dict(envelope))
        if self.fail:
            raise RuntimeError("srs sink failed")
        return envelope["receipt_id"]


class RecordingPublisher:
    def __init__(self, *, state=TransparencyPublicationState.REGISTERED, fail=False):
        self.state = state
        self.fail = fail
        self.requests = []

    def publish(self, request):
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("scitt unavailable")
        return TransparencyPublicationResult(
            schema="dagr.transparency_publication_result.v0.1",
            receipt_id=request.receipt_id,
            state=self.state,
            statement_digest="sha256:" + "1" * 64,
            receipt_digest=(
                "sha256:" + "2" * 64
                if self.state is TransparencyPublicationState.REGISTERED
                else None
            ),
        )


class RecordingResultSink:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.results = []

    def write(self, result):
        self.results.append(result)
        if self.fail:
            raise RuntimeError("result sink failed")


def _receipt(disposition="refused"):
    return {
        "receipt_version": "srs.core.v5.1",
        "profile_id": "srs.mcp.sdk_enforcement",
        "profile_version": "v0.1",
        "receipt_id": "urn:srs:receipt:admission:test",
        "receipt_kind": "admission",
        "subject_ref": "urn:subject:test",
        "disposition": disposition,
        "argument_digest": "sha256:" + "a" * 64,
        "receipt_signature": {
            "algorithm": "Ed25519",
            "canonicalization": "RFC8785-JCS",
            "key_id": "test",
            "signature": "test",
        },
    }


def test_no_publisher_is_behaviorally_transparent() -> None:
    inner = RecordingInnerSink()
    wrapper = PublishingReceiptSink(inner)
    envelope = _receipt()

    receipt_id = wrapper.write(envelope)

    assert receipt_id == envelope["receipt_id"]
    assert inner.calls == [envelope]


def test_publisher_runs_only_after_inner_commit() -> None:
    inner = RecordingInnerSink()
    publisher = RecordingPublisher()
    results = RecordingResultSink()
    wrapper = PublishingReceiptSink(inner, publisher=publisher, result_sink=results)
    envelope = _receipt()

    receipt_id = wrapper.write(envelope)

    assert receipt_id == envelope["receipt_id"]
    assert len(inner.calls) == 1
    assert len(publisher.requests) == 1
    assert len(results.results) == 1
    assert results.results[0].state is TransparencyPublicationState.REGISTERED


def test_inner_srs_sink_failure_prevents_any_publication() -> None:
    inner = RecordingInnerSink(fail=True)
    publisher = RecordingPublisher()
    wrapper = PublishingReceiptSink(inner, publisher=publisher)

    with pytest.raises(RuntimeError, match="srs sink failed"):
        wrapper.write(_receipt())

    assert publisher.requests == []


def test_publication_failure_never_reclassifies_committed_receipt() -> None:
    inner = RecordingInnerSink()
    publisher = RecordingPublisher(fail=True)
    results = RecordingResultSink()
    wrapper = PublishingReceiptSink(inner, publisher=publisher, result_sink=results)
    envelope = _receipt(disposition="refused")

    receipt_id = wrapper.write(envelope)

    assert receipt_id == envelope["receipt_id"]
    assert inner.calls[0]["disposition"] == "refused"
    assert len(results.results) == 1
    assert results.results[0].state is TransparencyPublicationState.TRANSPORT_FAILED


def test_result_sink_failure_cannot_turn_publication_into_dagr_failure() -> None:
    inner = RecordingInnerSink()
    publisher = RecordingPublisher()
    results = RecordingResultSink(fail=True)
    wrapper = PublishingReceiptSink(inner, publisher=publisher, result_sink=results)

    assert wrapper.write(_receipt()) == "urn:srs:receipt:admission:test"


def test_publication_request_is_digest_only_and_binds_signed_receipt() -> None:
    envelope = _receipt()
    request = TransparencyPublicationRequest.from_envelope(envelope)
    payload = request.payload_bytes()

    assert request.receipt_id == envelope["receipt_id"]
    assert request.receipt_kind == "admission"
    assert request.receipt_digest.startswith("sha256:")
    assert b"argument_digest" not in payload
    assert b"receipt_signature" not in payload
    assert b"disposition" not in payload
    assert b"tool_arguments" not in payload


def test_same_content_receipt_mutation_changes_binding_digest() -> None:
    a = _receipt()
    b = _receipt()
    b["receipt_signature"] = dict(b["receipt_signature"])
    b["receipt_signature"]["signature"] = "different"

    assert (
        TransparencyPublicationRequest.from_envelope(a).receipt_digest
        != TransparencyPublicationRequest.from_envelope(b).receipt_digest
    )
