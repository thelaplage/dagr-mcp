"""SAM transport adapter for Counterpedia federation artifacts.

SAM is treated strictly as transport/discovery. SAM peer identity is not a
Counterpedia node identity, and successful routing is not a Countervail allow
or DAGR standing transition.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Protocol

SAM_PIN = "v0.1.0-alpha.7"

COUNTERPEDIA_SAM_OPERATIONS = frozenset({
    "cp.receipt.announce",
    "cp.receipt.fetch",
    "cp.submission.submit",
    "cp.submission.fetch",
    "cp.snapshot.announce",
    "cp.snapshot.fetch",
    "cp.witness.submit",
})


@dataclass(frozen=True)
class SamPeer:
    peer_id: str
    counterpedia_node_id: str | None = None


@dataclass(frozen=True)
class CapabilityObservation:
    peer_id: str
    counterpedia_node_id: str | None
    operations: tuple[str, ...]
    transport: str = "sam"
    authority_effect: str = "none"


@dataclass(frozen=True)
class TransportResult:
    peer_id: str
    operation: str
    payload: Mapping[str, Any]
    authority_effect: str = "none"


class RemoteToolCaller(Protocol):
    def __call__(self, peer_id: str, operation: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]: ...


class SamTransportAdapter:
    def __init__(self, call_remote_tool: RemoteToolCaller):
        self._call_remote_tool = call_remote_tool

    @staticmethod
    def observe_capabilities(peer: SamPeer, operations: Iterable[str]) -> CapabilityObservation:
        normalized = tuple(sorted(set(operations)))
        unknown = set(normalized) - COUNTERPEDIA_SAM_OPERATIONS
        if unknown:
            raise ValueError(f"unknown Counterpedia SAM operations: {sorted(unknown)}")
        return CapabilityObservation(
            peer_id=peer.peer_id,
            counterpedia_node_id=peer.counterpedia_node_id,
            operations=normalized,
        )

    def invoke(self, peer: SamPeer, operation: str, arguments: Mapping[str, Any]) -> TransportResult:
        if operation not in COUNTERPEDIA_SAM_OPERATIONS:
            raise ValueError(f"operation not allowed by adapter: {operation}")
        if any(key in arguments for key in ("standing", "admitted", "published", "authorized", "decision")):
            raise ValueError("transport arguments may not inject authority/standing")
        response = self._call_remote_tool(peer.peer_id, operation, dict(arguments))
        if not isinstance(response, Mapping):
            raise TypeError("SAM remote tool response must be an object")
        if any(key in response for key in ("standing", "admitted", "published", "authorized", "decision")):
            raise ValueError("transport response attempted authority/standing injection")
        return TransportResult(peer_id=peer.peer_id, operation=operation, payload=dict(response))
