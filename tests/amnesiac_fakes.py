"""Deterministic fakes for the Amnesiac contract and binding tests.

These implement the framework-neutral ``AmnesiacService`` without a producer, so
the contract semantics and the FastMCP binding can be exercised where
``arcs_amnesiac`` is not installed. They are NOT native validation — native
producer-backed behavior lives in ``test_amnesiac_native.py``.
"""

from __future__ import annotations

from typing import Mapping

from dagr_mcp.amnesiac_contracts import (
    AdmissionStatus,
    CandidateResult,
    CapabilityUnavailable,
    CompileContextResponse,
    ExcludedItem,
    ProposalStatus,
    ProposeCandidatesResponse,
    RawPayloadRefused,
    RecordOutcomeResponse,
    ReopeningStatus,
    RequestReopeningResponse,
)

# The raw-payload key floor the refs-only fake refuses (a small illustrative
# subset; the native layer uses the full garp-sdk floor).
_RAW_KEYS = frozenset(
    {"model_output", "claim", "prompt", "tool_arguments", "transcript", "raw_payload"}
)


def _refuse_raw(mapping: Mapping[str, object]) -> None:
    for key, value in mapping.items():
        if isinstance(key, str) and key.strip().lower() in _RAW_KEYS:
            raise RawPayloadRefused(f"refs-only; raw-payload field {key!r} is refused")
        if isinstance(value, Mapping):
            _refuse_raw(value)


class FakeAmnesiacService:
    """A deterministic fake that honors the corrected contract without a producer."""

    def propose_candidates(self, request):
        results = []
        for i, c in enumerate(request.candidates):
            results.append(
                CandidateResult(
                    candidate_ref=f"candidate:{i:024d}",
                    content_hash=f"sha256:{i:064d}",
                    proposal_status=ProposalStatus.CANDIDATE_RECORDED,
                    admission_status=AdmissionStatus.NOT_REQUESTED,
                )
            )
        return ProposeCandidatesResponse(
            source_ref=request.source_ref, results=results, admission_performed=False
        )

    def compile_context(self, request):
        return CompileContextResponse(
            context_packet_ref="packet:fake",
            context_packet_hash="sha256:" + "0" * 64,
            selected_claim_refs=["claim:a"],
            excluded=[ExcludedItem(claim_ref="claim:b", reason_code="outside_as_of_boundary")],
        )

    def request_reopening(self, request):
        if request.candidate_ref == "candidate:final":
            return RequestReopeningResponse(
                candidate_ref=request.candidate_ref,
                status=ReopeningStatus.FINAL_REFUSED,
                lifecycle_before="final",
                lifecycle_after="final",
                detail="FINAL candidates are terminal",
            )
        return RequestReopeningResponse(
            candidate_ref=request.candidate_ref,
            status=ReopeningStatus.REOPENING_REQUESTED,
        )

    def record_outcome(self, request):
        has_ref = bool(request.agent_outcome_ref)
        has_map = request.agent_outcome is not None
        if has_ref == has_map:
            raise RawPayloadRefused(
                "record_outcome requires exactly one of agent_outcome_ref or agent_outcome"
            )
        if has_map:
            _refuse_raw(request.agent_outcome)
        return RecordOutcomeResponse(
            outcome_ref="agent_outcome:fake",
            bridge_status="candidate_created",
            candidate_ref="candidate:from_outcome",
            candidate_content_hash="sha256:" + "a" * 64,
            context_packet_ref=request.context_packet_ref,
            admission_status=AdmissionStatus.NOT_REQUESTED,
        )


class UnavailableAmnesiacService:
    """Simulates a missing producer: every op raises CapabilityUnavailable."""

    def propose_candidates(self, request):
        raise CapabilityUnavailable("amnesiac.propose_candidates", "no producer")

    def compile_context(self, request):
        raise CapabilityUnavailable("amnesiac.compile_context", "no producer")

    def request_reopening(self, request):
        # Reopening reports capability unavailable as a normal status value in
        # the contract; the native layer does the same. It is still a valid
        # response object (not an error result) for reopening specifically.
        raise CapabilityUnavailable("amnesiac.request_reopening", "no producer")

    def record_outcome(self, request):
        raise CapabilityUnavailable("amnesiac.record_outcome", "no producer")
