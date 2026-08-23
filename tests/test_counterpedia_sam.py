import pytest

from dagr_mcp.counterpedia_sam import SamPeer, SamTransportAdapter


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
