"""Native producer-backed tests against the current arcs-amnesiac tree.

These skip unless the exact producer surfaces are importable. They assert real
producer behavior — persistence-without-admission, the refs-only bridge, a real
ContextPacket, the real reopening path, and the fail-closed FINAL guard — not
fake-service contract behavior.

Producer symbols are imported lazily, through the ``p`` fixture, rather than at
module top level. ``dagr_mcp`` keeps a permanent import-direction guarantee and
the session's ``conftest`` purges producer roots from ``sys.modules`` after each
test; importing lazily keeps collection clean and ensures every producer import
inside a single test (test-side and native-side) resolves to one consistent
module instance.
"""

from __future__ import annotations

import importlib
import importlib.util
import types

import pytest

if importlib.util.find_spec("arcs_amnesiac") is None or importlib.util.find_spec("garp_sdk") is None:
    pytest.skip("arcs_amnesiac / garp_sdk not installed", allow_module_level=True)

from dagr_mcp.amnesiac_contracts import (
    AdmissionStatus,
    CapabilityUnavailable,
    CompileContextRequest,
    ProposalStatus,
    ProposeCandidatesRequest,
    ProposedClaim,
    RawPayloadRefused,
    RecordOutcomeRequest,
    ReopeningStatus,
    RequestReopeningRequest,
)
from dagr_mcp.amnesiac_native import (
    NativeAmnesiacService,
    final_guard_confirmed,
    probe_final_guard,
)
from dagr_mcp.amnesiac_stores import (
    InMemoryAgentOutcomeStore,
    InMemoryCandidateStore,
    InMemoryContextPacketStore,
)


@pytest.fixture
def p() -> types.SimpleNamespace:
    """Lazily import the producer symbols this module needs, fresh per test."""
    cg = importlib.import_module("arcs_amnesiac.claim_graph")
    cgt = importlib.import_module("arcs_amnesiac.claim_graph_types")
    sg = importlib.import_module("arcs_amnesiac.shadow_graph")
    sgr = importlib.import_module("arcs_amnesiac.shadow_graph_reopening")
    aoo = importlib.import_module("garp_sdk.agent_outcome_object")
    return types.SimpleNamespace(
        ClaimGraph=cg.ClaimGraph,
        ClaimNode=cgt.ClaimNode,
        LifecycleState=cgt.LifecycleState,
        ReconsiderabilityTrigger=sg.ReconsiderabilityTrigger,
        RejectedCandidate=sg.RejectedCandidate,
        RejectedCandidateLifecycle=sg.RejectedCandidateLifecycle,
        ShadowGraph=sg.ShadowGraph,
        ReopeningDecision=sgr.ReopeningDecision,
        ReopeningRequest=sgr.ReopeningRequest,
        reopen_candidate=sgr.reopen_candidate,
        AgentOutcomeObject=aoo.AgentOutcomeObject,
    )


def _admitted_node(p, claim_id, text, *, profile_scope=None, created_at=None):
    kwargs = dict(
        claim_id=claim_id,
        normalized_text=text,
        lifecycle_state=p.LifecycleState.ACTIVE,
        admission_state="admitted",
        profile_scope=profile_scope,
    )
    if created_at is not None:
        kwargs["created_at"] = created_at
    return p.ClaimNode(**kwargs)


def _outcome_dict(**overrides):
    base = {
        "outcome_id": "o1",
        "source_kind": "synthetic_fixture",
        "generated_by": "agent:test",
        "summary_label": "notify compliance",
        "summary_ref": "summary:abc",
        "receipt_refs": ["receipt:1"],
        "review_object_refs": ["review:1"],
    }
    base.update(overrides)
    return base


# -- propose: persisted but NOT admitted ------------------------------------


def test_propose_persists_candidate_but_does_not_admit(p):
    store = InMemoryCandidateStore()
    graph = p.ClaimGraph()
    svc = NativeAmnesiacService(candidate_store=store, claim_graph=graph)
    resp = svc.propose_candidates(
        ProposeCandidatesRequest(
            source_ref="source:x",
            candidates=[ProposedClaim(claim="The filing occurred on June 3")],
        )
    )
    r = resp.results[0]
    assert r.proposal_status is ProposalStatus.CANDIDATE_RECORDED
    assert r.admission_status is AdmissionStatus.NOT_REQUESTED
    assert resp.admission_performed is False
    assert len(store) == 1
    assert store.get(r.candidate_ref) is not None
    assert r.candidate_ref.startswith("candidate:")
    assert r.content_hash.startswith("sha256:")


def test_propose_creates_no_claim_graph_node(p):
    store = InMemoryCandidateStore()
    graph = p.ClaimGraph()
    svc = NativeAmnesiacService(candidate_store=store, claim_graph=graph)
    svc.propose_candidates(
        ProposeCandidatesRequest(
            source_ref="source:x",
            candidates=[ProposedClaim(claim="A claim"), ProposedClaim(claim="Another claim")],
        )
    )
    assert len(graph) == 0
    assert graph.list_nodes() == []


def test_propose_without_store_reports_constructed_not_recorded(p):
    svc = NativeAmnesiacService()  # producer available, no persistence
    resp = svc.propose_candidates(
        ProposeCandidatesRequest(source_ref="s", candidates=[ProposedClaim(claim="claim text")])
    )
    assert resp.results[0].proposal_status is ProposalStatus.CANDIDATE_CONSTRUCTED


def test_propose_malformed_claim_is_rejected_not_recorded(p):
    store = InMemoryCandidateStore()
    svc = NativeAmnesiacService(candidate_store=store)
    resp = svc.propose_candidates(
        ProposeCandidatesRequest(source_ref="s", candidates=[ProposedClaim(claim="   ")])
    )
    assert resp.results[0].proposal_status is ProposalStatus.REJECTED_MALFORMED
    assert len(store) == 0


# -- record_outcome: refs-only bridge to a real CandidateClaim ---------------


def test_refs_only_outcome_mapping_bridges_to_real_candidate(p):
    store = InMemoryCandidateStore()
    svc = NativeAmnesiacService(candidate_store=store)
    resp = svc.record_outcome(RecordOutcomeRequest(agent_outcome=_outcome_dict()))
    assert resp.bridge_status == "candidate_created"
    assert resp.candidate_ref.startswith("candidate:")
    assert resp.candidate_content_hash.startswith("sha256:")
    assert resp.outcome_ref == "agent_outcome:o1"
    assert resp.admission_status is AdmissionStatus.NOT_REQUESTED
    assert resp.claim_text_excluded and resp.tool_arguments_excluded
    assert resp.admission_claimed is False
    assert store.get(resp.candidate_ref) is not None


def test_refs_only_outcome_ref_resolves_through_store(p):
    outcome_store = InMemoryAgentOutcomeStore()
    outcome_store.put("agent_outcome:o1", p.AgentOutcomeObject.from_dict(_outcome_dict()))
    cand_store = InMemoryCandidateStore()
    svc = NativeAmnesiacService(candidate_store=cand_store, agent_outcome_store=outcome_store)
    resp = svc.record_outcome(RecordOutcomeRequest(agent_outcome_ref="agent_outcome:o1"))
    assert resp.candidate_ref.startswith("candidate:")
    assert cand_store.get(resp.candidate_ref) is not None


@pytest.mark.parametrize("raw_field", ["model_output", "claim", "prompt", "tool_arguments"])
def test_record_outcome_refuses_raw_payload_fields(p, raw_field):
    svc = NativeAmnesiacService(candidate_store=InMemoryCandidateStore())
    with pytest.raises(RawPayloadRefused):
        svc.record_outcome(
            RecordOutcomeRequest(agent_outcome=_outcome_dict(**{raw_field: "raw value"}))
        )


def test_record_outcome_requires_exactly_one_input(p):
    svc = NativeAmnesiacService(candidate_store=InMemoryCandidateStore())
    with pytest.raises(RawPayloadRefused):
        svc.record_outcome(RecordOutcomeRequest())
    with pytest.raises(RawPayloadRefused):
        svc.record_outcome(
            RecordOutcomeRequest(agent_outcome_ref="agent_outcome:o1", agent_outcome=_outcome_dict())
        )


# -- compile_context: v0 selector builds and stores a real ContextPacket -----


def test_v0_selector_builds_and_stores_real_context_packet(p):
    graph = p.ClaimGraph()
    graph.add_node(_admitted_node(p, "claim:a", "admitted one"))
    graph.add_node(_admitted_node(p, "claim:b", "admitted two"))
    graph.add_node(
        p.ClaimNode(claim_id="claim:c", normalized_text="a candidate", lifecycle_state=p.LifecycleState.CANDIDATE)
    )
    packet_store = InMemoryContextPacketStore()
    svc = NativeAmnesiacService(claim_graph=graph, context_packet_store=packet_store)
    resp = svc.compile_context(CompileContextRequest(task="summarize the filings"))

    assert resp.selected_claim_refs == ["claim:a", "claim:b"]
    assert ("claim:c", "not_admitted_lifecycle") in [
        (e.claim_ref, e.reason_code) for e in resp.excluded
    ]
    assert len(packet_store) == 1
    packet = packet_store.get(resp.context_packet_ref)
    assert packet is not None
    packet.assert_integrity()
    assert resp.context_packet_hash == packet.packet_hash
    assert resp.context_packet_hash.startswith("sha256:")


def test_v0_selector_respects_scope_asof_and_budget(p):
    graph = p.ClaimGraph()
    graph.add_node(_admitted_node(p, "claim:a", "scoped one", profile_scope="matter:1", created_at="2026-01-01T00:00:00Z"))
    graph.add_node(_admitted_node(p, "claim:b", "scoped two", profile_scope="matter:2", created_at="2026-01-01T00:00:00Z"))
    graph.add_node(_admitted_node(p, "claim:c", "too new", profile_scope="matter:1", created_at="2026-12-01T00:00:00Z"))
    packet_store = InMemoryContextPacketStore()
    svc = NativeAmnesiacService(claim_graph=graph, context_packet_store=packet_store)

    resp = svc.compile_context(
        CompileContextRequest(
            task="t", record_scope=["matter:1"], as_of="2026-06-01T00:00:00Z", item_budget=5
        )
    )
    reasons = {e.claim_ref: e.reason_code for e in resp.excluded}
    assert resp.selected_claim_refs == ["claim:a"]
    assert reasons["claim:b"] == "outside_record_scope"
    assert reasons["claim:c"] == "outside_as_of_boundary"


def test_compile_context_without_graph_is_capability_unavailable(p):
    svc = NativeAmnesiacService(context_packet_store=InMemoryContextPacketStore())
    with pytest.raises(CapabilityUnavailable):
        svc.compile_context(CompileContextRequest(task="t"))


# -- request_reopening: real ShadowGraph path --------------------------------


def test_reconsiderable_candidate_follows_real_reopening_path(p):
    recon = p.RejectedCandidate(
        candidate_ref="candidate:recon", rejection_reason="r",
        lifecycle=p.RejectedCandidateLifecycle.RECONSIDERABLE,
    )
    svc = NativeAmnesiacService(shadow_graph=p.ShadowGraph().add(recon))
    resp = svc.request_reopening(
        RequestReopeningRequest(candidate_ref="candidate:recon", trigger_ref="new_evidence_admitted")
    )
    assert resp.status is ReopeningStatus.REOPENING_REQUESTED
    assert resp.lifecycle_after == "reconsiderable"
    assert resp.outcome_ref is not None


def test_caller_cannot_force_reopened_without_admission_authority(p):
    recon = p.RejectedCandidate(
        candidate_ref="candidate:recon", rejection_reason="r",
        lifecycle=p.RejectedCandidateLifecycle.RECONSIDERABLE,
    )
    svc = NativeAmnesiacService(shadow_graph=p.ShadowGraph().add(recon))
    resp = svc.request_reopening(
        RequestReopeningRequest(
            candidate_ref="candidate:recon", trigger_ref="new_evidence_admitted",
            ratified_decision_ref="decision:forged",  # no authority injected
        )
    )
    assert resp.status is ReopeningStatus.REOPENING_REQUESTED
    assert resp.lifecycle_after != "reopened_for_review"


def test_injected_admission_authority_can_reopen_with_ratified_ref(p):
    class Authority:
        def ratify_reopening(self, candidate_ref, ratified_decision_ref):
            return p.ReopeningDecision.REOPENED, ratified_decision_ref

    recon = p.RejectedCandidate(
        candidate_ref="candidate:recon", rejection_reason="r",
        lifecycle=p.RejectedCandidateLifecycle.RECONSIDERABLE,
    )
    svc = NativeAmnesiacService(
        shadow_graph=p.ShadowGraph().add(recon), admission_authority=Authority()
    )
    resp = svc.request_reopening(
        RequestReopeningRequest(
            candidate_ref="candidate:recon", trigger_ref="new_evidence_admitted",
            ratified_decision_ref="decision:ratified:1",
        )
    )
    assert resp.status is ReopeningStatus.REOPENED
    assert resp.lifecycle_after == "reopened_for_review"
    assert resp.decision_ref == "decision:ratified:1"


def test_already_reopened_candidate_is_not_demoted(p):
    reopened = p.RejectedCandidate(
        candidate_ref="candidate:active", rejection_reason="r",
        lifecycle=p.RejectedCandidateLifecycle.REOPENED_FOR_REVIEW,
    )
    svc = NativeAmnesiacService(shadow_graph=p.ShadowGraph().add(reopened))
    resp = svc.request_reopening(
        RequestReopeningRequest(candidate_ref="candidate:active", trigger_ref="new_evidence_admitted")
    )
    # A candidate already in the active admission loop must not be demoted back
    # to reconsiderable by a bare reopening request.
    assert resp.status is ReopeningStatus.REOPENING_REQUESTED
    assert resp.lifecycle_after == "reopened_for_review"


# -- FINAL candidate refused for every reopening decision --------------------


def test_final_candidate_refused_through_service(p):
    final = p.RejectedCandidate(
        candidate_ref="candidate:final", rejection_reason="r",
        lifecycle=p.RejectedCandidateLifecycle.FINAL,
    )
    svc = NativeAmnesiacService(shadow_graph=p.ShadowGraph().add(final))
    resp = svc.request_reopening(
        RequestReopeningRequest(candidate_ref="candidate:final", trigger_ref="new_evidence_admitted")
    )
    assert resp.status is ReopeningStatus.FINAL_REFUSED
    assert "cannot be reopened or rewritten" in (resp.detail or "")


def test_final_candidate_refused_for_every_decision_at_producer(p):
    final = p.RejectedCandidate(
        candidate_ref="candidate:final", rejection_reason="r",
        lifecycle=p.RejectedCandidateLifecycle.FINAL,
    )
    request = p.ReopeningRequest(
        request_ref="req:1", candidate_ref="candidate:final",
        arriving_trigger="new_evidence_admitted", submitted_by_ref="op:1",
    )
    for decision in p.ReopeningDecision:
        with pytest.raises(ValueError, match="cannot be reopened or rewritten"):
            p.reopen_candidate(final, request, decision)
        assert final.lifecycle is p.RejectedCandidateLifecycle.FINAL


# -- FINAL guard confirmation + stale-tree regression ------------------------


def test_final_guard_confirmed_on_current_tree(p):
    assert final_guard_confirmed() is True


def test_stale_preguard_tree_is_detected_as_unguarded(p):
    from tests.preguard_producer_fixture import (
        build_preguard_reopening_module,
        build_preguard_shadow_module,
    )

    stale_reopening = build_preguard_reopening_module()
    stale_shadow = build_preguard_shadow_module()
    assert probe_final_guard(reopening_module=stale_reopening, shadow_module=stale_shadow) is False


def test_stale_tree_reopening_is_capability_unavailable_not_final_refusal(p):
    from tests.preguard_producer_fixture import (
        build_preguard_reopening_module,
        build_preguard_shadow_module,
    )

    stale_reopening = build_preguard_reopening_module()
    stale_shadow = build_preguard_shadow_module()

    import dagr_mcp.amnesiac_native as native

    original = native.final_guard_confirmed
    native.final_guard_confirmed = lambda: probe_final_guard(
        reopening_module=stale_reopening, shadow_module=stale_shadow
    )
    try:
        final = p.RejectedCandidate(
            candidate_ref="candidate:final", rejection_reason="r",
            lifecycle=p.RejectedCandidateLifecycle.FINAL,
        )
        svc = NativeAmnesiacService(shadow_graph=p.ShadowGraph().add(final))
        resp = svc.request_reopening(
            RequestReopeningRequest(candidate_ref="candidate:final", trigger_ref="new_evidence_admitted")
        )
        assert resp.status is ReopeningStatus.CAPABILITY_UNAVAILABLE
    finally:
        native.final_guard_confirmed = original
