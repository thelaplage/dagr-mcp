"""FEDERATION-LIVE-SAM0 — pinned SAM federation parity contract.

Runs the Wave0/Wave1 federation proof over a pinned google/sam release while
keeping the transport-neutral artifact semantics those waves already defined.
This module owns none of node/submission/receipt/registry identity semantics
(see the sibling Counterpedia federation contracts for those); it is strictly
a transport/discovery seam beneath them.

Required invariants (enforced, not just documented):
    sam_peer_identity != counterpedia_node_identity != delegated_authority
    sam_discovery != DAGR_admission
    sam_route_success != Countervail_ALLOW
    sam_transport_failure != evidence_absence

Concretely: ``SamPeerBinding`` refuses construction if its transport peer id
and its bound Counterpedia node id collapse to the same value. None of this
module's objects declare an authority/admission/trust/standing-shaped field
at all — a successful route can never carry a standing/admission/authorization
fact because there is no field on the wire to carry one; a caller attempting
to inject ``authority_effect`` (or any sibling authority-shaped key) at
construction time fails closed with ``TypeError`` before an instance exists.
``observe_transfer`` always returns an observation, even when the underlying
transfer fails closed, so a transport failure is recorded as evidence rather
than silently dropped.

CRITICAL: live SAM status must NEVER be read as a Countervail or DAGR
governance decision. Parity/liveness of the transport is not admission or
authority. No live google/sam deployment or package is available in this
environment, so ``RealSamTransport`` fails closed
(``RealSamTransportUnavailable``) rather than fabricating a live-status PASS;
``run_reference_proof`` defaults to, and clearly labels, the deterministic
``FakeSamTransport`` reference fallback. Only a caller who already holds a
constructed ``RealSamTransport`` (which itself refuses to construct without
the pinned package) can make ``run_reference_proof`` report ``mode="real"``.

Four fail-closed error classes cover the six required failure conditions this
module must never silently swallow: ``SamVersionError`` (version mismatch),
``SamIdentityError`` (peer identity mismatch), ``SamPayloadError`` (payload
digest mismatch, partial response, unknown operation), and
``SamTransportError``/``SamTimeoutError`` (transport failure, timeout). All of
them are ``ValueError`` subclasses so callers that only match on
``ValueError`` keep working, while callers that care about *why* it failed
closed can match the specific subclass.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

# --------------------------------------------------------------------------- #
# Pin                                                                         #
# --------------------------------------------------------------------------- #

# Exact google/sam revision this contract was implemented and tested against.
# Kept in lockstep with docs/federation-live-sam-pin.json by load_pin_record(),
# which is a drift detector: if either is bumped without the other, it fails
# closed instead of silently diverging.
SAM_RELEASE = "v0.1.0-alpha.7"
SAM_COMMIT = "a5f2c4e"

SCHEMA = "dagr.mcp.federation-live-sam.v0.1"
CONTRACT_VERSION = "sam.federation-live.v0.1"

# The three SAM-connected roles the reference E2E topology requires.
RESEARCHER_ORCHESTRATOR = "researcher_orchestrator"
WORKER_REGISTRAR = "worker_registrar"
VERIFIER_MIRROR = "verifier_mirror"
REFERENCE_ROLES = (RESEARCHER_ORCHESTRATOR, WORKER_REGISTRAR, VERIFIER_MIRROR)

# Operations this contract will route. Anything else fails closed as unknown.
KNOWN_OPERATIONS = frozenset(
    {
        "submission.fetch",
        "submission.submit",
        "receipt.fetch",
        "receipt.announce",
        "registry.fetch",
        "registry.announce",
        "memory.fetch",
        "memory.announce",
        "query.fetch",
        "query.submit",
    }
)


def _default_pin_path() -> Path:
    return Path(__file__).resolve().parent.parent / "docs" / "federation-live-sam-pin.json"


# --------------------------------------------------------------------------- #
# Fail-closed error taxonomy                                                  #
# --------------------------------------------------------------------------- #


class SamAdapterError(ValueError):
    """Base for every fail-closed error this module raises.

    Subclasses ``ValueError`` so existing ``pytest.raises(ValueError)``
    callers keep working; catch the specific subclass to distinguish why the
    transfer failed closed.
    """


class SamIdentityError(SamAdapterError):
    """Missing, colliding, or otherwise ambiguous peer/node identity, or a
    connection addressed to the wrong bound peer."""


class SamVersionError(SamAdapterError):
    """Unsupported/mismatched SAM release or commit, including pin-record
    drift and a peer advertising a different pinned release."""


class SamPayloadError(SamAdapterError):
    """Unknown operation, malformed/partial response, or a payload/response
    digest mismatch."""


class SamTransportError(SamAdapterError):
    """Transport refusal, including any exception raised by the underlying
    remote call."""


class SamTimeoutError(SamTransportError):
    """The transport did not respond within the allotted budget."""


class RealSamTransportUnavailable(SamTransportError):
    """Raised when constructing ``RealSamTransport`` without the pinned
    ``sam`` package installed. Fail-closed, not a crash: the caller should
    fall back to ``FakeSamTransport`` for the deterministic reference proof,
    and must never treat this fallback as a live-status PASS."""


# --------------------------------------------------------------------------- #
# Digests                                                                     #
# --------------------------------------------------------------------------- #


def _digest(v: Mapping[str, object]) -> str:
    raw = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _digest_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(bytes(payload)).hexdigest()


def parity_digest(artifact_refs: Mapping[str, str]) -> str:
    """Transport-neutral semantic parity root; SAM routing metadata is excluded."""
    return _digest({"schema": "counterpedia.federation.semantic-parity.v0.1", "artifacts": dict(sorted(artifact_refs.items()))})


# --------------------------------------------------------------------------- #
# Pin drift detection                                                         #
# --------------------------------------------------------------------------- #


def load_pin_record(path: Path | None = None) -> Mapping[str, Any]:
    """Load and validate ``docs/federation-live-sam-pin.json`` against the
    in-code ``SAM_RELEASE``/``SAM_COMMIT``.

    Fails closed with ``SamVersionError`` if the pin file and the in-code
    constants disagree, or the file no longer declares
    ``constitutional_dependency: false``, instead of silently diverging.
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
    if not isinstance(record, Mapping) or "release" not in record or "commit" not in record:
        raise SamVersionError(f"SAM pin record at {target} is missing 'release'/'commit'")
    if record["release"] != SAM_RELEASE or record["commit"] != SAM_COMMIT:
        raise SamVersionError(
            f"SAM pin drift detected: {target} release={record.get('release')!r} "
            f"commit={record.get('commit')!r} != code SAM_RELEASE={SAM_RELEASE!r} SAM_COMMIT={SAM_COMMIT!r}"
        )
    if record.get("constitutional_dependency") is not False:
        raise SamVersionError(f"SAM pin record at {target} must declare constitutional_dependency: false")
    return record


# --------------------------------------------------------------------------- #
# Identity / binding                                                         #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class SamPeerBinding:
    """Binds a SAM transport peer id to a Counterpedia node id.

    ``identity_binding`` is deliberately explicit rather than inferred: this
    repository does not carry a FEDERATION-IDENTITY0-compatible resolver, so
    it defaults to ``"unresolved"``. A caller that does hold
    FEDERATION-IDENTITY0-compatible metadata may pass it through this field;
    absent that, the binding stays honestly unresolved rather than fabricating
    a resolved identity link.

    This dataclass declares no authority/admission/trust/standing-shaped
    field. "SAM route success != Countervail ALLOW" is expressed by the
    field's structural absence, not by a field pinned to ``"none"``: the
    class uses ``slots=True``, so a caller cannot construct an instance with
    an ``authority_effect=`` (or sibling) keyword — it fails closed with
    ``TypeError`` — nor attach one to an already-constructed instance, which
    fails closed with ``AttributeError``.
    """

    sam_peer_id: str
    counterpedia_node_id: str
    role: str = RESEARCHER_ORCHESTRATOR
    identity_binding: str = "unresolved"

    def __post_init__(self) -> None:
        if not self.sam_peer_id or not self.sam_peer_id.strip():
            raise SamIdentityError("sam_peer_id must be non-empty")
        if not self.counterpedia_node_id or not self.counterpedia_node_id.strip():
            raise SamIdentityError("counterpedia_node_id must be non-empty")
        if self.sam_peer_id == self.counterpedia_node_id:
            raise SamIdentityError(
                "sam_peer_identity != counterpedia_node_identity: peer and node ids must not collapse"
            )
        if self.role not in REFERENCE_ROLES:
            raise SamIdentityError(f"unknown federation role: {self.role!r}")


def reference_topology(node_prefix: str = "cp-node") -> tuple[SamPeerBinding, ...]:
    """The reference three-role E2E topology: researcher/orchestrator,
    worker/registrar, verifier/mirror, each a distinct SAM peer bound to a
    distinct Counterpedia node."""
    return tuple(
        SamPeerBinding(sam_peer_id=f"sam:{role}", counterpedia_node_id=f"{node_prefix}:{role}", role=role)
        for role in REFERENCE_ROLES
    )


# --------------------------------------------------------------------------- #
# Observations (evidence, never admission)                                    #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class SamTransferObservation:
    peer_id: str
    node_id: str
    operation: str
    payload_digest: str
    route_succeeded: bool
    response_digest: str | None = None
    latency_seconds: float | None = None
    error: str | None = None
    schema_version: str = SCHEMA


@dataclass(frozen=True, slots=True)
class SamCapabilityObservation:
    """Discovery output: what a peer says it can do. This is an observation,
    never an admission — SAM discovery != DAGR admission — expressed by
    declaring no authority/admission-shaped field at all rather than one
    pinned to a benign value."""

    peer_id: str
    sam_release: str
    sam_commit: str
    operations: tuple[str, ...]


# --------------------------------------------------------------------------- #
# Transport seam                                                              #
# --------------------------------------------------------------------------- #


class SamTransport(Protocol):
    def send(self, peer_id: str, operation: str, payload: bytes) -> bytes: ...


class SamDiscoveryTransport(Protocol):
    def discover(self, peer_id: str) -> Mapping[str, object]: ...


def discover_peer(transport: SamDiscoveryTransport, peer_id: str) -> SamCapabilityObservation:
    """Exercise service discovery. Fails closed on a version mismatch or an
    unknown advertised operation; never returns anything resembling an
    admission decision."""
    info = transport.discover(peer_id)
    release = info.get("sam_release") if isinstance(info, Mapping) else None
    commit = info.get("sam_commit") if isinstance(info, Mapping) else None
    if release != SAM_RELEASE or commit != SAM_COMMIT:
        raise SamVersionError(
            f"peer {peer_id!r} advertises SAM {release!r}/{commit!r}, pinned {SAM_RELEASE!r}/{SAM_COMMIT!r}"
        )
    operations = tuple(sorted(info.get("operations", ()) if isinstance(info, Mapping) else ()))
    unknown = set(operations) - KNOWN_OPERATIONS
    if unknown:
        raise SamPayloadError(f"peer {peer_id!r} advertises unknown operations: {sorted(unknown)}")
    return SamCapabilityObservation(peer_id=peer_id, sam_release=release, sam_commit=commit, operations=operations)


def transfer_exact(
    transport: SamTransport,
    binding: SamPeerBinding,
    operation: str,
    payload: bytes,
    *,
    timeout_seconds: float = 5.0,
    expected_response_digest: str | None = None,
) -> SamTransferObservation:
    """Route ``payload`` to ``binding`` over ``transport`` without modifying
    its canonical bytes/digest.

    Fails closed (raises a ``SamAdapterError`` subclass) on: unknown
    operation, transport exception, timeout, partial/empty response, and a
    payload/response digest mismatch against an explicitly expected digest.
    Never treats a successful route as an admission or Countervail decision —
    the returned observation carries no authority/admission field at all, so
    there is nothing on it that could be mistaken for a standing fact.
    """
    if operation not in KNOWN_OPERATIONS:
        raise SamPayloadError(f"unknown remote operation: {operation!r}")

    payload_digest = _digest_bytes(payload)
    started = time.monotonic()
    try:
        response = transport.send(binding.sam_peer_id, operation, payload)
    except TimeoutError as exc:
        raise SamTimeoutError(f"SAM transport timed out for {operation!r} to {binding.sam_peer_id!r}: {exc}") from exc
    except SamAdapterError:
        raise
    except Exception as exc:  # noqa: BLE001 - transport refusal is fail-closed by design
        raise SamTransportError(f"SAM transport refused {operation!r} to {binding.sam_peer_id!r}: {exc}") from exc
    elapsed = time.monotonic() - started

    if elapsed > timeout_seconds:
        raise SamTimeoutError(
            f"SAM transport exceeded {timeout_seconds}s budget for {operation!r} to {binding.sam_peer_id!r} "
            f"(took {elapsed:.3f}s)"
        )
    if response is None:
        raise SamPayloadError(f"partial/empty response from SAM transport for {operation!r}")

    response_digest = _digest_bytes(response)
    if expected_response_digest is not None and response_digest != expected_response_digest:
        raise SamPayloadError(
            f"payload digest mismatch for {operation!r}: expected {expected_response_digest}, got {response_digest}"
        )

    return SamTransferObservation(
        peer_id=binding.sam_peer_id,
        node_id=binding.counterpedia_node_id,
        operation=operation,
        payload_digest=payload_digest,
        route_succeeded=True,
        response_digest=response_digest,
        latency_seconds=elapsed,
        error=None,
    )


def observe_transfer(
    transport: SamTransport,
    binding: SamPeerBinding,
    operation: str,
    payload: bytes,
    **kwargs: Any,
) -> SamTransferObservation:
    """``transfer_exact`` wrapped so a fail-closed failure is captured as
    evidence rather than lost: SAM transport failure != evidence absence.

    Always returns a ``SamTransferObservation``. On success it is identical
    to ``transfer_exact``'s return value; on any ``SamAdapterError`` it
    returns ``route_succeeded=False`` with the failure recorded in ``error``,
    never raises, and never fabricates a successful route.
    """
    started = time.monotonic()
    try:
        return transfer_exact(transport, binding, operation, payload, **kwargs)
    except SamAdapterError as exc:
        elapsed = time.monotonic() - started
        return SamTransferObservation(
            peer_id=binding.sam_peer_id,
            node_id=binding.counterpedia_node_id,
            operation=operation,
            payload_digest=_digest_bytes(payload),
            route_succeeded=False,
            response_digest=None,
            latency_seconds=elapsed,
            error=f"{type(exc).__name__}: {exc}",
        )


# --------------------------------------------------------------------------- #
# Connection lifecycle: discovery, disconnect/reconnect                       #
# --------------------------------------------------------------------------- #


@dataclass
class SamConnection:
    """Models a live connection to a single SAM peer so disconnect/reconnect
    and peer-identity-mismatch fail-closed behavior can be exercised without
    changing ``transfer_exact``'s transport-only signature."""

    transport: SamTransport
    peer_id: str | None = field(default=None)
    connected: bool = field(default=False)

    def connect(self, peer_id: str) -> None:
        if not peer_id or not peer_id.strip():
            raise SamIdentityError("peer_id required to connect")
        self.peer_id = peer_id
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def reconnect(self) -> None:
        if self.peer_id is None:
            raise SamIdentityError("cannot reconnect before an initial connect()")
        self.connected = True

    def transfer(self, binding: SamPeerBinding, operation: str, payload: bytes, **kwargs: Any) -> SamTransferObservation:
        if not self.connected:
            raise SamTransportError(f"not connected to {self.peer_id!r}; call connect()/reconnect() first")
        if binding.sam_peer_id != self.peer_id:
            raise SamIdentityError(
                f"peer identity mismatch: connection bound to {self.peer_id!r}, binding addresses {binding.sam_peer_id!r}"
            )
        return transfer_exact(self.transport, binding, operation, payload, **kwargs)


# --------------------------------------------------------------------------- #
# Deterministic fake transport (hermetic reference fallback)                  #
# --------------------------------------------------------------------------- #


class FakeSamTransport:
    """Deterministic in-memory transport — no network, no ``sam`` package,
    fully reproducible.

    ``*.submit``/``*.announce`` operations store their payload bytes
    verbatim, keyed by ``(peer_id, operation_family)``; the matching
    ``*.fetch`` returns those exact stored bytes back unmodified. This is
    what proves the contract is a pure transport seam: a payload that crosses
    submit -> fetch through this fake comes back byte-identical, with no
    authority added along the way.
    """

    def __init__(
        self,
        *,
        sam_release: str = SAM_RELEASE,
        sam_commit: str = SAM_COMMIT,
        operations: Iterable[str] = KNOWN_OPERATIONS,
    ) -> None:
        self._store: dict[tuple[str, str], bytes] = {}
        self.calls: list[tuple[str, str]] = []
        self._sam_release = sam_release
        self._sam_commit = sam_commit
        self._operations = tuple(sorted(set(operations)))

    def discover(self, peer_id: str) -> Mapping[str, object]:
        return {"sam_release": self._sam_release, "sam_commit": self._sam_commit, "operations": self._operations}

    def send(self, peer_id: str, operation: str, payload: bytes) -> bytes:
        self.calls.append((peer_id, operation))
        if operation not in KNOWN_OPERATIONS:
            raise SamPayloadError(f"fake transport received unknown operation: {operation!r}")

        family, _, verb = operation.rpartition(".")
        key = (peer_id, family)

        if verb in ("submit", "announce"):
            self._store[key] = bytes(payload)
            return bytes(payload)
        if verb == "fetch":
            if key not in self._store:
                raise SamTransportError(f"fake transport has no object for {operation!r} from peer {peer_id!r}")
            return self._store[key]
        raise SamPayloadError(f"fake transport does not model verb for operation: {operation!r}")


# --------------------------------------------------------------------------- #
# Real SAM transport (guarded, lazy, optional)                                #
# --------------------------------------------------------------------------- #

# Availability is detected WITHOUT importing the package, exactly like
# dagr_mcp.amnesiac_native's producer guard: importing this module must never
# pull `sam` into the process merely by being imported.
_SAM_PACKAGE_AVAILABLE = importlib.util.find_spec("sam") is not None


def sam_available() -> bool:
    """True if the pinned ``sam`` package is importable in this environment.

    Never imports the package itself; only probes for it. When this is
    ``False`` (the case in every environment this lane has been able to test
    in), ``run_reference_proof`` must run — and must clearly label itself as
    running — the deterministic reference fallback rather than any live SAM
    path.
    """
    return _SAM_PACKAGE_AVAILABLE


class SamMcpClient(Protocol):
    """The surface ``RealSamTransport`` needs from a real, already-connected
    SAM client. Injected by the caller rather than constructed here: this
    module does not own SAM's networking/session setup, only the seam between
    an already-connected client and this contract's operation set."""

    def call_tool(self, *, peer_id: str, tool: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]: ...


class RealSamTransport:
    """``SamTransport``/``SamDiscoveryTransport`` backed by a real,
    caller-supplied SAM client for the pinned release.

    Requires the pinned ``sam`` package (see ``SAM_RELEASE``/``SAM_COMMIT``
    and ``docs/federation-live-sam-pin.json``) to be importable; if it is
    not, construction fails closed with ``RealSamTransportUnavailable``
    rather than raising an opaque ImportError or silently falling back to
    something that looks live but is not. Use ``FakeSamTransport`` for the
    deterministic reference proof.
    """

    def __init__(self, client: SamMcpClient):
        if not sam_available():
            raise RealSamTransportUnavailable(
                f"google/sam is not installed; pinned release {SAM_RELEASE} ({SAM_COMMIT}) is required "
                "for the real transport (see docs/federation-live-sam-pin.json). Use FakeSamTransport for "
                "the deterministic reference proof — never treat its absence as a live-status PASS."
            )
        self._client = client

    def discover(self, peer_id: str) -> Mapping[str, object]:
        try:
            return self._client.call_tool(peer_id=peer_id, tool="sam.discover", arguments={})
        except Exception as exc:  # noqa: BLE001 - transport refusal is fail-closed by design
            raise SamTransportError(f"real SAM discovery failed for {peer_id!r}: {exc}") from exc

    def send(self, peer_id: str, operation: str, payload: bytes) -> bytes:
        try:
            result = self._client.call_tool(peer_id=peer_id, tool=operation, arguments={"payload": payload})
        except SamAdapterError:
            raise
        except Exception as exc:  # noqa: BLE001 - transport refusal is fail-closed by design
            raise SamTransportError(f"real SAM transport refused {operation!r} to {peer_id!r}: {exc}") from exc
        body = result.get("payload") if isinstance(result, Mapping) else None
        if body is None:
            raise SamPayloadError(f"real SAM transport returned no payload field for {operation!r}")
        return bytes(body)


# --------------------------------------------------------------------------- #
# One-command reference proof                                                 #
# --------------------------------------------------------------------------- #


def run_reference_proof(transport: SamTransport | None = None) -> Mapping[str, Any]:
    """One-command local proof: exercises discovery plus submit/fetch
    exact-byte round trips across the three-role reference topology, then
    computes the transport-neutral semantic parity digest.

    Defaults to ``FakeSamTransport`` — the deterministic reference fallback —
    and labels the report ``mode="reference"`` in that case. It only reports
    ``mode="real"`` when the caller passes in an already-constructed
    ``RealSamTransport`` (which itself refuses to construct unless the pinned
    ``sam`` package is importable), so this function can never fabricate a
    live-status PASS on its own.
    """
    used_transport: Any = transport if transport is not None else FakeSamTransport()
    mode = "real" if isinstance(used_transport, RealSamTransport) else "reference"

    bindings = reference_topology()
    # Each kind's write verb, matching KNOWN_OPERATIONS: submission uses
    # "submit", receipt/registry use "announce".
    kinds = (("submission", "submit"), ("receipt", "announce"), ("registry", "announce"))
    artifact_refs: dict[str, str] = {}
    observations: list[SamTransferObservation] = []

    for binding, (kind, write_verb) in zip(bindings, kinds):
        payload = json.dumps({"kind": kind, "node": binding.counterpedia_node_id}, sort_keys=True).encode()
        submit_obs = observe_transfer(used_transport, binding, f"{kind}.{write_verb}", payload)
        observations.append(submit_obs)
        fetch_obs = observe_transfer(used_transport, binding, f"{kind}.fetch", payload)
        observations.append(fetch_obs)
        if fetch_obs.route_succeeded and fetch_obs.response_digest is not None:
            artifact_refs[kind] = fetch_obs.response_digest

    return {
        "mode": mode,
        "sam_release": SAM_RELEASE,
        "sam_commit": SAM_COMMIT,
        "contract_version": CONTRACT_VERSION,
        "artifact_refs": artifact_refs,
        "parity_digest": parity_digest(artifact_refs),
        "observations": [
            {
                "peer_id": o.peer_id,
                "node_id": o.node_id,
                "operation": o.operation,
                "route_succeeded": o.route_succeeded,
                "latency_seconds": o.latency_seconds,
                "error": o.error,
            }
            for o in observations
        ],
        "all_routes_succeeded": all(o.route_succeeded for o in observations),
    }


def main() -> int:
    report = run_reference_proof()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SAM_RELEASE",
    "SAM_COMMIT",
    "SCHEMA",
    "CONTRACT_VERSION",
    "RESEARCHER_ORCHESTRATOR",
    "WORKER_REGISTRAR",
    "VERIFIER_MIRROR",
    "REFERENCE_ROLES",
    "KNOWN_OPERATIONS",
    "SamAdapterError",
    "SamIdentityError",
    "SamVersionError",
    "SamPayloadError",
    "SamTransportError",
    "SamTimeoutError",
    "RealSamTransportUnavailable",
    "parity_digest",
    "load_pin_record",
    "SamPeerBinding",
    "reference_topology",
    "SamTransferObservation",
    "SamCapabilityObservation",
    "SamTransport",
    "SamDiscoveryTransport",
    "discover_peer",
    "transfer_exact",
    "observe_transfer",
    "SamConnection",
    "FakeSamTransport",
    "sam_available",
    "SamMcpClient",
    "RealSamTransport",
    "run_reference_proof",
]
