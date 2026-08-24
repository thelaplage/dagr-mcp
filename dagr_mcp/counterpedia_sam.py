"""SAM transport adapter for Counterpedia federation artifacts.

SAM is treated strictly as transport/discovery: the first transport adapter
beneath the portable Counterpedia/SRS contracts, not a constitutional
dependency of them. This module owns none of node/submission/receipt/corpus
identity semantics (see the CP-NODE-CONTRACT0 / CP-SUBMISSION-PACKET0 /
SRS-RECEIPT-MESH0 / RECEIPT-WITNESS0 / CP-CORPUS-MIRROR-MESH0 sibling lanes
for those) and makes no admission or Countervail decision.

Required invariants (enforced, not just documented):
  sam_peer_identity != counterpedia_node_identity != delegated_authority
  sam_can_route != countervail_allow

Concretely: a ``SamPeer`` refuses construction if its transport peer id and
its locally-bound Counterpedia node reference collapse to the same value, and
``SamTransportAdapter.invoke`` refuses any transport arguments or response
that carry a standing/admission/authorization field — a successful route is
never allowed to become an allow decision.

Fail-closed error categories map onto the four failure classes the adapter
must never silently swallow: identity, version, payload, and transport. All
of them are ``ValueError`` subclasses so callers that only match on
``ValueError`` (as the original test surface does) keep working, while
callers that care about *why* it failed closed can match the specific type.

No hard dependency: importing this module never imports the ``sam`` package.
``RealSamTransport`` guards that import behind ``sam_available()`` and fails
closed (``RealSamTransportUnavailable``) when the pinned package is absent,
exactly like the existing Amnesiac native-integration guard
(``dagr_mcp/amnesiac_native.py``). ``FakeSamTransport`` is a fully
deterministic, hermetic stand-in used by tests and local development; it
implements the same ``RemoteToolCaller`` seam so the adapter code under test
is identical whether the transport is real or fake.
"""
from __future__ import annotations

import importlib.util
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

# --------------------------------------------------------------------------- #
# Pin                                                                         #
# --------------------------------------------------------------------------- #

# Exact google/sam revision/release this adapter was implemented and tested
# against. Kept in lockstep with docs/sam-pin.json by load_pin_record(), which
# is a drift detector: if either is bumped without the other, it fails closed
# instead of silently diverging.
SAM_PIN = "v0.1.0-alpha.7"

SAM_ADAPTER_CONTRACT_VERSION = "sam.transport.v0.1"
SUPPORTED_SAM_CONTRACT_VERSIONS = frozenset({SAM_ADAPTER_CONTRACT_VERSION})

DEFAULT_LOCATOR_TTL_SECONDS = 300.0

COUNTERPEDIA_SAM_OPERATIONS = frozenset({
    "cp.receipt.announce",
    "cp.receipt.fetch",
    "cp.submission.submit",
    "cp.submission.fetch",
    "cp.snapshot.announce",
    "cp.snapshot.fetch",
    "cp.witness.submit",
})

# Fields that would smuggle a standing/admission/authorization decision
# through what must remain a bare transport hop. Checked on both request
# arguments and transport responses.
_AUTHORITY_FIELDS = frozenset({
    "standing",
    "admitted",
    "published",
    "authorized",
    "decision",
    "countervail_allow",
})


# --------------------------------------------------------------------------- #
# Fail-closed error taxonomy                                                  #
# --------------------------------------------------------------------------- #


class SamAdapterError(ValueError):
    """Base for every fail-closed error this adapter raises.

    Subclasses ``ValueError`` so existing ``pytest.raises(ValueError)``
    callers keep working; catch the specific subclass to distinguish why the
    adapter refused.
    """


class SamIdentityError(SamAdapterError):
    """Missing, ambiguous, or colliding peer/node identity, or an
    unresolvable locator."""


class SamVersionError(SamAdapterError):
    """Unsupported SAM adapter contract version, or a pin-record mismatch."""


class SamPayloadError(SamAdapterError):
    """Unsupported operation, malformed arguments/response, or an attempted
    authority/standing injection."""


class SamTransportError(SamAdapterError):
    """Transport refusal, including a stale/unresolvable locator and any
    exception raised by the underlying remote call."""


class RealSamTransportUnavailable(SamTransportError):
    """Raised when constructing ``RealSamTransport`` without the pinned
    ``sam`` package installed. Fail-closed, not a crash: the caller should
    fall back to ``FakeSamTransport`` for hermetic paths."""


# --------------------------------------------------------------------------- #
# Data model                                                                  #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SamPeer:
    """A SAM transport peer, optionally bound to a local Counterpedia node
    reference.

    ``peer_id`` and ``counterpedia_node_id`` are deliberately kept as two
    distinct fields rather than one: SAM peer identity is a transport-layer
    fact, Counterpedia node identity is a portable-contract fact, and this
    adapter refuses to let them collapse into each other.
    """

    peer_id: str
    counterpedia_node_id: str | None = None
    contract_version: str = SAM_ADAPTER_CONTRACT_VERSION
    # Opaque SAM locator (e.g. a multiaddr/service record) and the local
    # unix-epoch time it was last observed fresh. Both are optional — most
    # tests and simple callers never resolve a locator at all — but if a
    # locator is present it must be resolvable and dated, so staleness can be
    # evaluated at invoke() time.
    locator: str | None = None
    locator_observed_at: float | None = None

    def __post_init__(self) -> None:
        if not self.peer_id or not self.peer_id.strip():
            raise SamIdentityError("sam_peer_identity: peer_id must be non-empty")
        if self.counterpedia_node_id is not None and not self.counterpedia_node_id.strip():
            raise SamIdentityError(
                "counterpedia_node_id must be non-empty when provided (ambiguous node identity)"
            )
        if self.counterpedia_node_id is not None and self.counterpedia_node_id == self.peer_id:
            raise SamIdentityError(
                "sam_peer_identity != counterpedia_node_identity: peer_id and "
                "counterpedia_node_id must not be the same value"
            )
        if self.locator is not None and not self.locator.strip():
            raise SamIdentityError("locator, if present, must be non-empty (unresolvable locator)")
        if self.locator is not None and self.locator_observed_at is None:
            raise SamIdentityError(
                "a locator requires locator_observed_at to evaluate staleness (unresolvable locator)"
            )


@dataclass(frozen=True)
class CapabilityObservation:
    """Discovery output: what a peer says it can do, with zero authority
    effect. This is an *observation*, never an admission."""

    peer_id: str
    counterpedia_node_id: str | None
    operations: tuple[str, ...]
    contract_version: str = SAM_ADAPTER_CONTRACT_VERSION
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


# --------------------------------------------------------------------------- #
# Adapter                                                                     #
# --------------------------------------------------------------------------- #


class SamTransportAdapter:
    """Thin transport seam. Every method fails closed; none of them ever
    produce or consume standing/admission/authorization facts."""

    def __init__(
        self,
        call_remote_tool: RemoteToolCaller,
        *,
        locator_ttl_seconds: float = DEFAULT_LOCATOR_TTL_SECONDS,
    ):
        self._call_remote_tool = call_remote_tool
        self._locator_ttl_seconds = locator_ttl_seconds

    @staticmethod
    def observe_capabilities(peer: SamPeer, operations: Iterable[str]) -> CapabilityObservation:
        if peer.contract_version not in SUPPORTED_SAM_CONTRACT_VERSIONS:
            raise SamVersionError(f"unsupported SAM adapter contract version: {peer.contract_version!r}")
        normalized = tuple(sorted(set(operations)))
        unknown = set(normalized) - COUNTERPEDIA_SAM_OPERATIONS
        if unknown:
            raise SamPayloadError(f"unknown Counterpedia SAM operations: {sorted(unknown)}")
        return CapabilityObservation(
            peer_id=peer.peer_id,
            counterpedia_node_id=peer.counterpedia_node_id,
            operations=normalized,
            contract_version=peer.contract_version,
        )

    def invoke(
        self,
        peer: SamPeer,
        operation: str,
        arguments: Mapping[str, Any],
        *,
        now: float | None = None,
    ) -> TransportResult:
        if operation not in COUNTERPEDIA_SAM_OPERATIONS:
            raise SamPayloadError(f"operation not allowed by adapter: {operation}")

        if peer.contract_version not in SUPPORTED_SAM_CONTRACT_VERSIONS:
            raise SamVersionError(f"unsupported SAM adapter contract version: {peer.contract_version!r}")

        if peer.locator is not None:
            current = time.time() if now is None else now
            assert peer.locator_observed_at is not None  # guaranteed by SamPeer.__post_init__
            age = current - peer.locator_observed_at
            if age < 0 or age > self._locator_ttl_seconds:
                raise SamTransportError(
                    f"stale or unresolvable locator for peer {peer.peer_id!r} (age={age!r}s, "
                    f"ttl={self._locator_ttl_seconds!r}s)"
                )

        if not isinstance(arguments, Mapping):
            raise SamPayloadError("transport arguments must be a mapping")
        if any(key in arguments for key in _AUTHORITY_FIELDS):
            raise SamPayloadError("transport arguments may not inject authority/standing")

        try:
            response = self._call_remote_tool(peer.peer_id, operation, dict(arguments))
        except SamAdapterError:
            raise
        except Exception as exc:  # noqa: BLE001 - transport refusal is fail-closed by design
            raise SamTransportError(f"SAM transport refused operation {operation!r}: {exc}") from exc

        if not isinstance(response, Mapping):
            raise SamPayloadError("SAM remote tool response must be an object")
        if any(key in response for key in _AUTHORITY_FIELDS):
            raise SamPayloadError("transport response attempted authority/standing injection")

        return TransportResult(peer_id=peer.peer_id, operation=operation, payload=dict(response))


# --------------------------------------------------------------------------- #
# Deterministic fake transport (hermetic tests / local dev)                   #
# --------------------------------------------------------------------------- #


class FakeSamTransport:
    """Deterministic in-memory ``RemoteToolCaller`` — no network, no ``sam``
    package, fully reproducible.

    ``*.announce`` and ``*.submit`` operations store their argument payload
    verbatim, keyed by ``(peer_id, operation_family)``; the matching
    ``*.fetch`` returns that exact stored payload back. This is what proves
    the adapter is a pure transport seam: a fixture that crosses
    announce -> fetch through this fake comes back byte-identical, with no
    authority added along the way.
    """

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], Mapping[str, Any]] = {}
        self.calls: list[tuple[str, str, Mapping[str, Any]]] = []

    def __call__(self, peer_id: str, operation: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append((peer_id, operation, dict(arguments)))

        if operation not in COUNTERPEDIA_SAM_OPERATIONS:
            raise SamPayloadError(f"fake transport received unknown operation: {operation}")

        family, _, verb = operation.rpartition(".")
        key = (peer_id, family)

        if verb in ("announce", "submit"):
            self._store[key] = dict(arguments)
            return {"status": "received", "echo": dict(arguments)}

        if verb == "fetch":
            if key not in self._store:
                raise SamTransportError(
                    f"fake transport has no object for {operation!r} from peer {peer_id!r}"
                )
            return {"status": "found", "object": dict(self._store[key])}

        raise SamPayloadError(f"fake transport does not model verb for operation: {operation}")


# --------------------------------------------------------------------------- #
# Real SAM transport (guarded, lazy, optional)                                #
# --------------------------------------------------------------------------- #

# Availability is detected WITHOUT importing the package, exactly like
# dagr_mcp.amnesiac_native's producer guard: importing this module must never
# pull `sam` into the process merely by being imported.
_SAM_AVAILABLE = importlib.util.find_spec("sam") is not None


def sam_available() -> bool:
    """True if the pinned ``sam`` package is importable in this environment.

    Never imports the package itself; only probes for it.
    """
    return _SAM_AVAILABLE


class SamMcpClient(Protocol):
    """The surface ``RealSamTransport`` needs from a real SAM client.

    Injected by the caller rather than constructed here: this adapter does
    not own SAM's networking/session setup, only the seam between an
    already-connected client and the Counterpedia MCP operation contract.
    """

    def call_tool(self, *, peer_id: str, tool: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]: ...


class RealSamTransport:
    """``RemoteToolCaller`` backed by a real, caller-supplied SAM client.

    Requires the pinned ``sam`` package (see ``SAM_PIN`` / ``docs/sam-pin.json``)
    to be installed; if it is not, construction fails closed with
    ``RealSamTransportUnavailable`` rather than raising an opaque ImportError
    or silently falling back to something that looks real but is not. Use
    ``FakeSamTransport`` for hermetic paths where the real package is
    unavailable or undesired.
    """

    def __init__(self, client: SamMcpClient):
        if not sam_available():
            raise RealSamTransportUnavailable(
                f"google/sam is not installed; pinned release {SAM_PIN} is required "
                "for the real transport (see docs/sam-pin.json). Use "
                "FakeSamTransport for hermetic paths."
            )
        self._client = client

    def __call__(self, peer_id: str, operation: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            return self._client.call_tool(peer_id=peer_id, tool=operation, arguments=arguments)
        except SamAdapterError:
            raise
        except Exception as exc:  # noqa: BLE001 - transport refusal is fail-closed by design
            raise SamTransportError(f"real SAM transport refused operation {operation!r}: {exc}") from exc


# --------------------------------------------------------------------------- #
# Pin drift detection                                                         #
# --------------------------------------------------------------------------- #


def _default_pin_path() -> Path:
    return Path(__file__).resolve().parent.parent / "docs" / "sam-pin.json"


def load_pin_record(path: Path | None = None) -> Mapping[str, Any]:
    """Load and validate ``docs/sam-pin.json`` against the in-code ``SAM_PIN``.

    This is the drift detector required by the lane spec ("SAM drift must be
    detectable"): if the pin file and the in-code constant disagree, or the
    file no longer declares ``constitutional_dependency: false``, this fails
    closed with ``SamVersionError`` instead of silently diverging.
    """
    target = path or _default_pin_path()
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise SamVersionError(f"unable to read SAM pin record at {target}: {exc}") from exc
    try:
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SamVersionError(f"malformed SAM pin record at {target}: {exc}") from exc
    if not isinstance(record, Mapping) or "release" not in record:
        raise SamVersionError(f"SAM pin record at {target} is missing a 'release' field")
    if record["release"] != SAM_PIN:
        raise SamVersionError(
            f"SAM pin drift detected: {target} release={record['release']!r} "
            f"!= code SAM_PIN={SAM_PIN!r}"
        )
    if record.get("constitutional_dependency") is not False:
        raise SamVersionError(
            f"SAM pin record at {target} must declare constitutional_dependency: false"
        )
    return record


__all__ = [
    "SAM_PIN",
    "SAM_ADAPTER_CONTRACT_VERSION",
    "SUPPORTED_SAM_CONTRACT_VERSIONS",
    "DEFAULT_LOCATOR_TTL_SECONDS",
    "COUNTERPEDIA_SAM_OPERATIONS",
    "SamAdapterError",
    "SamIdentityError",
    "SamVersionError",
    "SamPayloadError",
    "SamTransportError",
    "RealSamTransportUnavailable",
    "SamPeer",
    "CapabilityObservation",
    "TransportResult",
    "RemoteToolCaller",
    "SamTransportAdapter",
    "FakeSamTransport",
    "sam_available",
    "SamMcpClient",
    "RealSamTransport",
    "load_pin_record",
]
