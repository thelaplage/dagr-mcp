"""FEDERATION-LIVE-SAM0: pinned SAM federation parity contract.

Exercises the Required work items from docs/dispatch/FEDERATION-LIVE-SAM0.md
against the deterministic reference fallback (``FakeSamTransport``): pin
drift detection, the three-role reference topology, discovery, exact-byte
submit/fetch round trips, disconnect/reconnect, evidence capture on failure,
and every required fail-closed path (version mismatch, peer identity
mismatch, payload digest mismatch, timeout, partial response, unknown
operation). No live google/sam deployment is available in this environment;
this suite proves the module never fabricates a live-status PASS in that
absence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dagr_mcp.federation_live_sam import (
    KNOWN_OPERATIONS,
    REFERENCE_ROLES,
    SAM_COMMIT,
    SAM_RELEASE,
    FakeSamTransport,
    RealSamTransport,
    RealSamTransportUnavailable,
    SamCapabilityObservation,
    SamConnection,
    SamIdentityError,
    SamPayloadError,
    SamPeerBinding,
    SamTimeoutError,
    SamTransportError,
    SamVersionError,
    discover_peer,
    load_pin_record,
    observe_transfer,
    parity_digest,
    reference_topology,
    run_reference_proof,
    sam_available,
    transfer_exact,
)


class Fake:
    """Bare echo transport used by the original parity-contract smoke test."""

    def send(self, peer_id, operation, payload):
        return payload


class RaisingTransport:
    def __init__(self, exc: Exception):
        self._exc = exc

    def send(self, peer_id, operation, payload):
        raise self._exc


class PartialResponseTransport:
    def send(self, peer_id, operation, payload):
        return None


# --------------------------------------------------------------------------- #
# Original smoke tests (kept intact)                                          #
# --------------------------------------------------------------------------- #


def test_pinned_release_and_identity_separation():
    assert SAM_RELEASE == "v0.1.0-alpha.7" and SAM_COMMIT == "a5f2c4e"
    b = SamPeerBinding("sam:peer-a", "cp-node:a")
    o = transfer_exact(Fake(), b, "submission.fetch", b"abc")
    assert o.route_succeeded
    assert not hasattr(o, "authority_effect")
    assert o.peer_id != o.node_id


def test_semantic_parity_ignores_transport_metadata():
    refs = {"submission": "sha256:" + "1" * 64, "receipt": "sha256:" + "2" * 64}
    assert parity_digest(refs) == parity_digest(dict(reversed(list(refs.items()))))


# --------------------------------------------------------------------------- #
# 1. Pin: machine-readable config, drift detection                            #
# --------------------------------------------------------------------------- #


def test_pin_record_matches_code_constants():
    record = load_pin_record()
    assert record["release"] == SAM_RELEASE
    assert record["commit"] == SAM_COMMIT
    assert record["constitutional_dependency"] is False


def test_pin_record_drift_fails_closed(tmp_path: Path):
    drifted = tmp_path / "federation-live-sam-pin.json"
    drifted.write_text(
        json.dumps({"release": "v9.9.9", "commit": "deadbee", "constitutional_dependency": False}),
        encoding="utf-8",
    )
    with pytest.raises(SamVersionError):
        load_pin_record(drifted)


def test_pin_record_constitutional_dependency_must_be_false(tmp_path: Path):
    bad = tmp_path / "federation-live-sam-pin.json"
    bad.write_text(
        json.dumps({"release": SAM_RELEASE, "commit": SAM_COMMIT, "constitutional_dependency": True}),
        encoding="utf-8",
    )
    with pytest.raises(SamVersionError):
        load_pin_record(bad)


def test_pin_record_missing_file_fails_closed(tmp_path: Path):
    with pytest.raises(SamVersionError):
        load_pin_record(tmp_path / "does-not-exist.json")


# --------------------------------------------------------------------------- #
# 2. Reference topology: three distinct SAM-connected roles                   #
# --------------------------------------------------------------------------- #


def test_reference_topology_has_three_distinct_roles():
    bindings = reference_topology()
    assert len(bindings) == 3
    assert {b.role for b in bindings} == set(REFERENCE_ROLES)
    assert len({b.sam_peer_id for b in bindings}) == 3
    assert len({b.counterpedia_node_id for b in bindings}) == 3
    for b in bindings:
        assert b.sam_peer_id != b.counterpedia_node_id
        assert not hasattr(b, "authority_effect")


def test_binding_rejects_role_outside_reference_topology():
    with pytest.raises(SamIdentityError):
        SamPeerBinding("sam:x", "cp-node:x", role="not_a_role")


def test_binding_rejects_authority_shaped_field_injection():
    """NE-11: "no authority" is structural absence, not a field pinned to a
    benign value. SamPeerBinding declares no authority_effect (or sibling)
    field at all, so injecting one — whatever value it carries — fails
    closed at construction time instead of being silently accepted."""
    hostile_kwargs = [
        {"authority_effect": "none"},
        {"authority_effect": "admitted"},
        {"admission_effect": "admitted"},
        {"trust_effect": "granted"},
        {"standing_effect": "granted"},
        {"trusted": True},
        {"admitted": True},
    ]
    for kwargs in hostile_kwargs:
        with pytest.raises(TypeError):
            SamPeerBinding("sam:x", "cp-node:x", **kwargs)


def test_binding_has_no_authority_effect_slot_at_all():
    """Defense in depth is structural, not a runtime re-check: SamPeerBinding
    uses ``slots=True``, so a caller cannot forge an authority-shaped
    attribute onto an already-constructed instance either. Attempting it
    fails closed with AttributeError because there is no such slot."""
    binding = SamPeerBinding("sam:x", "cp-node:x", role="worker_registrar")
    with pytest.raises(AttributeError):
        object.__setattr__(binding, "authority_effect", "admitted")


def test_binding_identity_binding_defaults_unresolved():
    b = SamPeerBinding("sam:x", "cp-node:x")
    assert b.identity_binding == "unresolved"
    # FEDERATION-IDENTITY0-compatible metadata may be supplied explicitly when available.
    b2 = SamPeerBinding("sam:y", "cp-node:y", identity_binding="federation-identity:v0.1:sha256:" + "0" * 64)
    assert b2.identity_binding.startswith("federation-identity:")


# --------------------------------------------------------------------------- #
# 3/6. Discovery: SAM discovery != DAGR admission                             #
# --------------------------------------------------------------------------- #


def test_discover_peer_returns_observation_not_admission():
    transport = FakeSamTransport()
    obs = discover_peer(transport, "sam:worker_registrar")
    assert isinstance(obs, SamCapabilityObservation)
    assert not hasattr(obs, "authority_effect")
    assert obs.sam_release == SAM_RELEASE and obs.sam_commit == SAM_COMMIT
    assert set(obs.operations) <= KNOWN_OPERATIONS


def test_discover_peer_fails_closed_on_version_mismatch():
    transport = FakeSamTransport(sam_release="v9.9.9")
    with pytest.raises(SamVersionError):
        discover_peer(transport, "sam:worker_registrar")


def test_discover_peer_fails_closed_on_unknown_operation():
    transport = FakeSamTransport(operations={"submission.fetch", "not.a.real.op"})
    with pytest.raises(SamPayloadError):
        discover_peer(transport, "sam:worker_registrar")


# --------------------------------------------------------------------------- #
# 4/6. Exact-byte transport: submit -> fetch round trip preserves bytes       #
# --------------------------------------------------------------------------- #


def test_submit_then_fetch_round_trips_exact_bytes():
    transport = FakeSamTransport()
    binding = SamPeerBinding("sam:worker_registrar", "cp-node:worker_registrar", role="worker_registrar")
    payload = b'{"kind":"receipt","value":42}'

    submitted = transfer_exact(transport, binding, "receipt.announce", payload)
    fetched = transfer_exact(transport, binding, "receipt.fetch", payload)

    assert submitted.route_succeeded and fetched.route_succeeded
    assert submitted.response_digest == fetched.response_digest
    assert fetched.response_digest == submitted.payload_digest == fetched.payload_digest


def test_expected_response_digest_mismatch_fails_closed():
    transport = FakeSamTransport()
    binding = SamPeerBinding("sam:worker_registrar", "cp-node:worker_registrar", role="worker_registrar")
    payload = b"canonical-bytes"
    transfer_exact(transport, binding, "receipt.announce", payload)

    wrong_digest = "sha256:" + "f" * 64
    with pytest.raises(SamPayloadError):
        transfer_exact(transport, binding, "receipt.fetch", payload, expected_response_digest=wrong_digest)


# --------------------------------------------------------------------------- #
# 7/9. Evidence capture: transport failure != evidence absence                #
# --------------------------------------------------------------------------- #


def test_observe_transfer_captures_failure_as_evidence_not_absence():
    transport = FakeSamTransport()  # nothing has been submitted yet
    binding = SamPeerBinding("sam:verifier_mirror", "cp-node:verifier_mirror", role="verifier_mirror")

    obs = observe_transfer(transport, binding, "registry.fetch", b"whatever")

    assert obs is not None
    assert obs.route_succeeded is False
    assert obs.error is not None and "SamTransportError" in obs.error
    assert not hasattr(obs, "authority_effect")
    assert obs.latency_seconds is not None


def test_observe_transfer_passes_through_success():
    transport = FakeSamTransport()
    binding = SamPeerBinding("sam:worker_registrar", "cp-node:worker_registrar", role="worker_registrar")
    transfer_exact(transport, binding, "receipt.announce", b"x")
    obs = observe_transfer(transport, binding, "receipt.fetch", b"x")
    assert obs.route_succeeded is True and obs.error is None


# --------------------------------------------------------------------------- #
# 6/9. Connection lifecycle: disconnect/reconnect, peer identity mismatch     #
# --------------------------------------------------------------------------- #


def test_connection_requires_connect_before_transfer():
    conn = SamConnection(FakeSamTransport())
    binding = SamPeerBinding("sam:worker_registrar", "cp-node:worker_registrar", role="worker_registrar")
    with pytest.raises(SamTransportError):
        conn.transfer(binding, "receipt.announce", b"x")


def test_connection_disconnect_then_reconnect():
    conn = SamConnection(FakeSamTransport())
    binding = SamPeerBinding("sam:worker_registrar", "cp-node:worker_registrar", role="worker_registrar")

    conn.connect("sam:worker_registrar")
    conn.transfer(binding, "receipt.announce", b"x")

    conn.disconnect()
    with pytest.raises(SamTransportError):
        conn.transfer(binding, "receipt.fetch", b"x")

    conn.reconnect()
    obs = conn.transfer(binding, "receipt.fetch", b"x")
    assert obs.route_succeeded


def test_connection_fails_closed_on_peer_identity_mismatch():
    conn = SamConnection(FakeSamTransport())
    conn.connect("sam:worker_registrar")
    other_peer_binding = SamPeerBinding("sam:verifier_mirror", "cp-node:verifier_mirror", role="verifier_mirror")
    with pytest.raises(SamIdentityError):
        conn.transfer(other_peer_binding, "receipt.announce", b"x")


# --------------------------------------------------------------------------- #
# 9. Remaining fail-closed classes: unknown op, timeout, partial response     #
# --------------------------------------------------------------------------- #


def test_unknown_operation_fails_closed():
    binding = SamPeerBinding("sam:worker_registrar", "cp-node:worker_registrar", role="worker_registrar")
    with pytest.raises(SamPayloadError):
        transfer_exact(FakeSamTransport(), binding, "not.a.real.op", b"x")


def test_binding_authority_effect_injection_fails_before_transfer_is_reached():
    # There is no authority_effect slot to forge onto a constructed binding
    # (see test_binding_has_no_authority_effect_slot_at_all), and no keyword
    # to inject one at construction time (see
    # test_binding_rejects_authority_shaped_field_injection): both fail
    # closed before a binding carrying such a fact could ever reach
    # transfer_exact. This asserts transfer_exact's own guard surface is
    # narrower now — only routing-shaped concerns (unknown operation, etc.)
    # remain to check on a valid binding.
    binding = SamPeerBinding("sam:x", "cp-node:x", role="worker_registrar")
    obs = transfer_exact(FakeSamTransport(), binding, "receipt.announce", b"x")
    assert obs.route_succeeded
    assert not hasattr(obs, "authority_effect")


def test_transport_timeout_fails_closed():
    binding = SamPeerBinding("sam:x", "cp-node:x")
    with pytest.raises(SamTimeoutError):
        transfer_exact(RaisingTransport(TimeoutError("simulated")), binding, "receipt.announce", b"x")


def test_partial_response_fails_closed():
    binding = SamPeerBinding("sam:x", "cp-node:x")
    with pytest.raises(SamPayloadError):
        transfer_exact(PartialResponseTransport(), binding, "receipt.announce", b"x")


def test_generic_transport_exception_wrapped_fail_closed():
    binding = SamPeerBinding("sam:x", "cp-node:x")
    with pytest.raises(SamTransportError):
        transfer_exact(RaisingTransport(ConnectionError("refused")), binding, "receipt.announce", b"x")


# --------------------------------------------------------------------------- #
# Real transport: guarded import, fails closed absent the pinned package      #
# --------------------------------------------------------------------------- #


def test_sam_package_not_installed_in_this_environment():
    # This lane never fabricates a live-status PASS: it must observe (not
    # assume) that the pinned package is genuinely absent here.
    assert sam_available() is False


def test_real_sam_transport_fails_closed_when_package_unavailable():
    class DummyClient:
        def call_tool(self, *, peer_id, tool, arguments):  # pragma: no cover - never reached
            raise AssertionError("must not be called: RealSamTransport must refuse construction first")

    with pytest.raises(RealSamTransportUnavailable):
        RealSamTransport(DummyClient())


# --------------------------------------------------------------------------- #
# 8/Acceptance proof: one-command reference proof, labeled, deterministic     #
# --------------------------------------------------------------------------- #


def test_run_reference_proof_defaults_to_labeled_reference_mode():
    report = run_reference_proof()
    assert report["mode"] == "reference"
    assert report["all_routes_succeeded"] is True
    assert set(report["artifact_refs"]) == {"submission", "receipt", "registry"}
    assert all("authority_effect" not in o for o in report["observations"])


def test_run_reference_proof_never_claims_real_mode_without_a_real_transport():
    # transport=None (the default) and an explicit FakeSamTransport must both
    # report "reference" — only a caller already holding a constructed
    # RealSamTransport instance (impossible here; the package is absent) can
    # produce mode="real".
    assert run_reference_proof(None)["mode"] == "reference"
    assert run_reference_proof(FakeSamTransport())["mode"] == "reference"


def test_run_reference_proof_parity_digest_is_transport_instance_independent():
    """Acceptance proof: the same Wave2 run produces the same native artifact
    digests regardless of which transport session carried them; only the
    application-level bytes affect the parity digest, never routing metadata
    such as which FakeSamTransport instance or peer connection handled it."""
    report_a = run_reference_proof(FakeSamTransport())
    report_b = run_reference_proof(FakeSamTransport())
    assert report_a["parity_digest"] == report_b["parity_digest"]
    assert report_a["artifact_refs"] == report_b["artifact_refs"]
