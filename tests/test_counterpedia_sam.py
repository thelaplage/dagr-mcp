import json

import pytest

from dagr_mcp.counterpedia_sam import (
    SAM_PIN,
    FakeSamTransport,
    RealSamTransport,
    RealSamTransportUnavailable,
    SamIdentityError,
    SamPayloadError,
    SamPeer,
    SamTransportAdapter,
    SamTransportError,
    SamVersionError,
    load_pin_record,
    sam_available,
)


def test_capability_observation_is_transport_only():
    peer = SamPeer(peer_id="sam:peer-a", counterpedia_node_id="node:researcher-a")
    observation = SamTransportAdapter.observe_capabilities(peer, ["cp.submission.submit", "cp.receipt.fetch"])
    assert observation.peer_id == "sam:peer-a"
    assert observation.counterpedia_node_id == "node:researcher-a"
    assert observation.authority_effect == "none"


def test_successful_route_does_not_become_allow():
    calls = []

    def remote(peer_id, operation, arguments):
        calls.append((peer_id, operation, arguments))
        return {"status": "received", "packet_digest": arguments["packet_digest"]}

    adapter = SamTransportAdapter(remote)
    result = adapter.invoke(
        SamPeer(peer_id="sam:peer-b", counterpedia_node_id="node:intake-b"),
        "cp.submission.submit",
        {"packet_digest": "sha256:" + "a" * 64},
    )
    assert result.authority_effect == "none"
    assert "decision" not in result.payload
    assert calls


@pytest.mark.parametrize("field", ["standing", "admitted", "published", "authorized", "decision"])
def test_transport_rejects_authority_injection(field):
    adapter = SamTransportAdapter(lambda *_: {"ok": True})
    with pytest.raises(ValueError):
        adapter.invoke(SamPeer(peer_id="sam:p"), "cp.receipt.fetch", {field: True})


def test_response_guard_rejects_authority_injection():
    adapter = SamTransportAdapter(lambda *_: {"admitted": True})
    with pytest.raises(ValueError):
        adapter.invoke(SamPeer(peer_id="sam:p"), "cp.receipt.fetch", {"digest": "sha256:" + "a" * 64})


def test_unknown_operations_fail_closed():
    adapter = SamTransportAdapter(lambda *_: {})
    with pytest.raises(ValueError):
        adapter.invoke(SamPeer(peer_id="sam:p"), "cp.admit", {})


# --------------------------------------------------------------------------- #
# Required invariant: sam_peer_identity != counterpedia_node_identity        #
# --------------------------------------------------------------------------- #


def test_peer_identity_cannot_collapse_into_node_identity():
    with pytest.raises(SamIdentityError):
        SamPeer(peer_id="same:id", counterpedia_node_id="same:id")


def test_peer_id_must_be_non_empty():
    with pytest.raises(SamIdentityError):
        SamPeer(peer_id="")


def test_node_id_must_be_non_empty_when_provided():
    with pytest.raises(SamIdentityError):
        SamPeer(peer_id="sam:p", counterpedia_node_id="   ")


def test_locator_requires_observed_at():
    with pytest.raises(SamIdentityError):
        SamPeer(peer_id="sam:p", locator="multiaddr:/ip4/127.0.0.1")


# --------------------------------------------------------------------------- #
# Fail-closed: unsupported contract version                                   #
# --------------------------------------------------------------------------- #


def test_invoke_fails_closed_on_unsupported_contract_version():
    adapter = SamTransportAdapter(lambda *_: {"status": "received"})
    peer = SamPeer(peer_id="sam:p", contract_version="sam.transport.v9.9")
    with pytest.raises(SamVersionError):
        adapter.invoke(peer, "cp.receipt.fetch", {"digest": "sha256:" + "a" * 64})


def test_observe_capabilities_fails_closed_on_unsupported_contract_version():
    peer = SamPeer(peer_id="sam:p", contract_version="sam.transport.v9.9")
    with pytest.raises(SamVersionError):
        SamTransportAdapter.observe_capabilities(peer, ["cp.receipt.fetch"])


# --------------------------------------------------------------------------- #
# Fail-closed: stale / unresolvable locator                                   #
# --------------------------------------------------------------------------- #


def test_invoke_fails_closed_on_stale_locator():
    adapter = SamTransportAdapter(lambda *_: {"status": "received"}, locator_ttl_seconds=60)
    peer = SamPeer(peer_id="sam:p", locator="multiaddr:/ip4/127.0.0.1", locator_observed_at=1000.0)
    with pytest.raises(SamTransportError):
        adapter.invoke(peer, "cp.receipt.fetch", {"digest": "sha256:" + "a" * 64}, now=1000.0 + 61)


def test_invoke_succeeds_within_locator_ttl():
    adapter = SamTransportAdapter(lambda *_: {"status": "received"}, locator_ttl_seconds=60)
    peer = SamPeer(peer_id="sam:p", locator="multiaddr:/ip4/127.0.0.1", locator_observed_at=1000.0)
    result = adapter.invoke(
        peer, "cp.receipt.fetch", {"digest": "sha256:" + "a" * 64}, now=1000.0 + 30
    )
    assert result.authority_effect == "none"


# --------------------------------------------------------------------------- #
# Fail-closed: transport refusal                                              #
# --------------------------------------------------------------------------- #


def test_invoke_wraps_remote_exceptions_as_transport_error():
    def boom(*_):
        raise RuntimeError("connection reset")

    adapter = SamTransportAdapter(boom)
    peer = SamPeer(peer_id="sam:p")
    with pytest.raises(SamTransportError):
        adapter.invoke(peer, "cp.receipt.fetch", {"digest": "sha256:" + "a" * 64})


def test_invoke_fails_closed_on_non_mapping_response():
    adapter = SamTransportAdapter(lambda *_: "not-a-mapping")
    peer = SamPeer(peer_id="sam:p")
    with pytest.raises(SamPayloadError):
        adapter.invoke(peer, "cp.receipt.fetch", {"digest": "sha256:" + "a" * 64})


# --------------------------------------------------------------------------- #
# FakeSamTransport: deterministic, byte-identical round trip                  #
# --------------------------------------------------------------------------- #


def test_fake_transport_round_trip_is_byte_identical():
    transport = FakeSamTransport()
    adapter = SamTransportAdapter(transport)
    peer = SamPeer(peer_id="sam:peer-a", counterpedia_node_id="node:researcher-a")

    fixture = {
        "packet_digest": "sha256:" + "b" * 64,
        "subject_ref": "receipt:governed:tool-call-1",
        "nested": {"a": 1, "b": [1, 2, 3]},
    }

    announce = adapter.invoke(peer, "cp.receipt.announce", fixture)
    assert announce.authority_effect == "none"
    assert announce.payload["echo"] == fixture

    fetch = adapter.invoke(peer, "cp.receipt.fetch", {"packet_digest": fixture["packet_digest"]})
    assert fetch.authority_effect == "none"
    assert fetch.payload["object"] == fixture
    assert "decision" not in fetch.payload
    assert "admitted" not in fetch.payload


def test_fake_transport_fetch_without_announce_fails_closed():
    transport = FakeSamTransport()
    adapter = SamTransportAdapter(transport)
    peer = SamPeer(peer_id="sam:peer-a")
    with pytest.raises(SamTransportError):
        adapter.invoke(peer, "cp.snapshot.fetch", {"snapshot_ref": "snapshot:1"})


def test_fake_transport_still_rejects_authority_injection():
    transport = FakeSamTransport()
    adapter = SamTransportAdapter(transport)
    peer = SamPeer(peer_id="sam:peer-a")
    with pytest.raises(SamPayloadError):
        adapter.invoke(peer, "cp.submission.submit", {"decision": "admit"})


# --------------------------------------------------------------------------- #
# RealSamTransport: guarded, lazy, fails closed without the pinned package    #
# --------------------------------------------------------------------------- #


def test_sam_available_does_not_import_sam():
    # Calling sam_available() must be side-effect free with respect to the
    # `sam` package itself; it only probes for the module spec.
    import sys

    before = set(sys.modules)
    sam_available()
    after = set(sys.modules)
    assert "sam" not in (after - before)


def test_real_sam_transport_fails_closed_when_package_absent():
    if sam_available():
        pytest.skip("pinned sam package is installed in this environment")

    class _StubClient:
        def call_tool(self, *, peer_id, tool, arguments):  # pragma: no cover - unreachable
            return {"status": "received"}

    with pytest.raises(RealSamTransportUnavailable):
        RealSamTransport(_StubClient())


# --------------------------------------------------------------------------- #
# Pin drift detection                                                         #
# --------------------------------------------------------------------------- #


def test_pin_record_matches_code_constant():
    record = load_pin_record()
    assert record["release"] == SAM_PIN
    assert record["constitutional_dependency"] is False


def test_pin_record_drift_is_detected(tmp_path):
    drifted = tmp_path / "sam-pin.json"
    drifted.write_text(json.dumps({"release": "v9.9.9", "constitutional_dependency": False}))
    with pytest.raises(SamVersionError):
        load_pin_record(drifted)


def test_pin_record_rejects_constitutional_dependency_claim(tmp_path):
    bad = tmp_path / "sam-pin.json"
    bad.write_text(json.dumps({"release": SAM_PIN, "constitutional_dependency": True}))
    with pytest.raises(SamVersionError):
        load_pin_record(bad)
