#!/usr/bin/env python3
"""Generate the SAM <-> DAGR/MCP semantics crosswalk (SAM-SEMANTICS-RECON0).

This is a recon artifact, not a runtime component. It maps assertions
observable in the `google/sam` ("Sovereign Agent Mesh") repository to the
minimal meaning those assertions actually license, and records the explicit
non-equivalences that meaning does NOT include.

Hard constraints (see docs/recon/SAM_SEMANTICS_RECON0.md and
docs/dispatch/SAM-SEMANTICS-RECON0.md for the full lane spec):

- This module imports nothing from dagr_mcp and is imported by nothing in
  dagr_mcp. SAM is not, and must not become, a constitutional dependency of
  this repository. AUTHORITY_MOVEMENT = 0.
- No entry in this crosswalk carries DAGR admission, evidentiary, or
  authorization weight -- and that is expressed structurally: no entry
  defines an authority/admission/standing field at all (rule NE-11: "no
  authority" must be structural absence, not a field pinned to "none"). Each
  entry's `minimal_meaning` states only what its SAM source surface actually
  licenses, and its `does_not_prove` list states explicitly what that
  meaning does not license -- including, where relevant, that it is not
  authorization, not a DAGR admission decision, not evidentiary standing,
  and not publication. `_reject_authority_shaped_fields()` below enforces
  this at construction time: it is not merely a convention.
- Output is deterministic: same input, same bytes, every run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "generated/recon/sam-semantics-crosswalk.v0.1.json"

CROSSWALK_VERSION = "0.1.0"

# Pinned source. Re-pin (new revision + new retrieved_at) before trusting a
# regenerated crosswalk against a different SAM state; per the lane's STOP
# conditions, current source always wins over these notes.
SAM_REPO = "https://github.com/google/sam"
SAM_REVISION = "2cbd07acd6ed66ddc56c29ca2e3188721255d151"
SAM_RETRIEVED_AT = "2026-08-24T07:29:37Z"
SAM_DISCLAIMER = (
    "This is not an officially supported Google product. "
    "(README.md, \"Disclaimer\" section, pinned revision)"
)

# The mandatory non-equivalence ladder from the lane spec, preserved verbatim
# and in order. No entry's `does_not_prove` list may be read as collapsing
# any adjacent pair of these terms.
NON_EQUIVALENCE_LADDER: tuple[str, ...] = (
    "authenticated",
    "discoverable",
    "invocable",
    "authorized_for_this_context",
    "executed",
    "output_trusted",
    "evidence_supported",
    "admitted",
    "published",
)

# The ten categories the lane spec requires coverage of, verbatim category
# keys used on each entry below.
REQUIRED_CATEGORIES: tuple[str, ...] = (
    "node_identity_enrollment",
    "router_relay_membership",
    "service_advertisement",
    "service_discovery",
    "tool_discovery",
    "invocation_request",
    "invocation_result",
    "policy_role_target_authorization",
    "lease_session_connection",
    "inference_provider_routing",
)

# whether it is identity, discovery, transport, authorization, execution,
# evidence, or derived state (spec's own enum, verbatim).
SEMANTIC_CLASSES: tuple[str, ...] = (
    "identity",
    "discovery",
    "transport",
    "authorization",
    "execution",
    "evidence",
    "derived_state",
)

STATUSES: tuple[str, ...] = ("grounded", "observation_only")

# rule NE-11: fields that would give an entry authority/admission/trust/
# standing shape. None of these may ever appear on a crosswalk entry -- not
# even pinned to a benign value like "none" or 0. "No authority" must be
# expressed by these keys being structurally ABSENT from the entry, never by
# serializing one of them with a none-pinned value.
FORBIDDEN_AUTHORITY_FIELDS: frozenset[str] = frozenset({
    "authority_effect",
    "admission_effect",
    "trust_effect",
    "standing_effect",
    "truth_effect",
    "registry_mutation_effect",
    "authority_posture",
    "trusted",
    "authorized",
    "admitted",
    "standing",
})


def _reject_authority_shaped_fields(entry: dict[str, Any]) -> None:
    """Fail closed against any authority-shaped field on a crosswalk entry.

    This is the enforcement half of rule NE-11: it is not enough that the
    generator's own literal source happens not to set one of these fields
    today. Absence must be enforced at construction time so that neither a
    future edit nor untrusted/injected entry data can reintroduce one --
    even pinned to a "none"/benign value, which NE-11 treats as equally
    non-compliant as a live value.
    """
    present = FORBIDDEN_AUTHORITY_FIELDS & entry.keys()
    if present:
        raise ValueError(
            f"{entry.get('id', '<unknown>')}: refusing to emit "
            f"authority-shaped field(s) {sorted(present)} on a SAM "
            "crosswalk entry -- non-authority must be structural absence, "
            "never a none-pinned field (rule NE-11)"
        )


def _entry(
    *,
    id: str,
    category: str,
    status: str,
    sam_source_surface: str,
    observed_surface: str,
    minimal_meaning: str,
    does_not_prove: list[str],
    semantic_class: str,
    notes: str = "",
) -> dict[str, Any]:
    assert category in REQUIRED_CATEGORIES, category
    assert status in STATUSES, status
    assert semantic_class in SEMANTIC_CLASSES, semantic_class
    assert does_not_prove, f"{id}: every entry needs >=1 does_not_prove item"
    entry = {
        "id": id,
        "category": category,
        "status": status,
        "sam_source_surface": sam_source_surface,
        "observed_surface": observed_surface,
        "minimal_meaning": minimal_meaning,
        "does_not_prove": does_not_prove,
        "semantic_class": semantic_class,
        "notes": notes,
    }
    _reject_authority_shaped_fields(entry)
    return entry


def _build_entries() -> list[dict[str, Any]]:
    return [
        _entry(
            id="SAM-ID-01",
            category="node_identity_enrollment",
            status="grounded",
            sam_source_surface=(
                "internal/node/enroll.go Enroll() L62-110, EnrollBootstrap() "
                "L189-369; internal/identity/biscuit.go mintBiscuit() L64-226"
            ),
            observed_surface=(
                "api.EnrollRequest/EnrollResponse (api/sam.proto L53-71); "
                "api.BootstrapEnrollRequest/Response (api/sam.proto L84-102)"
            ),
            minimal_meaning=(
                "A libp2p peer holding an ed25519 keypair presented an "
                "OIDC-issued JWT (or a pre-shared bootstrap token) to a SAM "
                "control plane over HTTP(S). Having validated that "
                "credential and translated its claims into policy facts, "
                "the control plane issued a Biscuit token cryptographically "
                "binding a node(<peer_id>) fact, plus role/label facts, to "
                "that specific peer_id."
            ),
            does_not_prove=[
                "does not prove the peer_id belongs to any real-world "
                "organization, person, or Counterpedia subject",
                "does not prove the human/service account referenced by the "
                "JWT is itself trustworthy -- only that VerifyJWT (internal/"
                "identity/oidc.go L26-100) accepted its signature and audience",
                "'authenticated' (peer holds a control-plane-issued Biscuit "
                "bound to its peer_id) != 'authorized_for_this_context' "
                "(evaluated later, per request; see SAM-AUTHZ-01)",
                "enrollment mints a credential; it does not itself admit or "
                "execute anything",
            ],
            semantic_class="identity",
        ),
        _entry(
            id="SAM-ID-02",
            category="node_identity_enrollment",
            status="grounded",
            sam_source_surface=(
                "api/agent.go ValidateAgentID()/AgentMember() L22-118; "
                "internal/node/middleware.go L250-260"
            ),
            observed_surface=(
                "AuthFrame.agent field (api/sam.proto L29); api.FactAgent facts"
            ),
            minimal_meaning=(
                "SAM defines a second, DNS-shaped, operator-namespaced "
                "'agent' principal string distinct from a node's libp2p "
                "peer_id. A connector translates an external identity (e.g. "
                "a SPIFFE URI) into this string; the calling node then "
                "asserts which agent it speaks for on each request. "
                "middleware.go injects this claim into the Datalog "
                "authorizer 'rather than trusted from the token, so it is "
                "visible to policy while staying plainly what it is: an "
                "assertion by the peer at the other end' (L250-253)."
            ),
            does_not_prove=[
                "a SAM agent identifier is a policy-string convention local "
                "to one SAM mesh's operator namespace; it is never "
                "equivalent to, and must not be mapped onto, Counterpedia "
                "record/subject identity or any real-world entity identity",
                "the agent claim is asserted by the calling node, not "
                "independently verified by SAM at the point of use -- "
                "'agent=X' on a request proves only that the connecting "
                "node said X",
                "an asserted agent claim licenses no authority or admission "
                "on its own: it is not authorization, it is not evidentiary "
                "standing for any downstream decision, and it is not "
                "published as any DAGR/Counterpedia record",
            ],
            semantic_class="identity",
        ),
        _entry(
            id="SAM-ROUTER-01",
            category="router_relay_membership",
            status="grounded",
            sam_source_surface=(
                "internal/router/router.go relayACL L64-94, "
                "authenticatedPeers/bannedPeers L97-120, HandleAuthHandshake "
                "L846-895, performMutualAuth L898-962"
            ),
            observed_surface=(
                "api.AuthFrame/AuthResponse (api/sam.proto L21-36); libp2p "
                "circuitv2 relay ACL AllowReserve/AllowConnect"
            ),
            minimal_meaning=(
                "A router admits a peer into its relay-reservation and "
                "relay-connect paths only after that peer completed a "
                "mutual Biscuit handshake on the router's own AuthN stream "
                "and the router's local relayACL finds the peer in "
                "authenticatedPeers and not in bannedPeers. For "
                "router-to-router peering, performMutualAuth additionally "
                "requires the remote Biscuit to carry the configured "
                "RequiredRole fact (L941-958)."
            ),
            does_not_prove=[
                "relay membership is a transport-layer decision made "
                "independently by each router's own in-memory map, not a "
                "mesh-wide or control-plane-recorded state -- one router's "
                "authenticatedPeers entry says nothing about any other router",
                "'authenticated' (Biscuit signature + peer-binding verified) "
                "!= 'authorized_for_this_context' (the relay ACL is a "
                "coarse allow/deny on relay use, not the per-target-service "
                "decision made in SamNode.Authorize; see SAM-AUTHZ-01)",
            ],
            semantic_class="transport",
        ),
        _entry(
            id="SAM-ROUTER-02",
            category="router_relay_membership",
            status="grounded",
            sam_source_surface="internal/router/router.go renewLease() L642-740",
            observed_surface=(
                "api.RouterLeaseRequest{peer_id, addresses, biscuit, "
                "connected_peers, dht_size} / api.RouterLeaseResponse"
                "{success, error, expires_at} (api/sam.proto L165-177)"
            ),
            minimal_meaning=(
                "A router periodically self-reports its own addresses, its "
                "currently connected peer set, and its DHT routing-table "
                "size to the control plane over HTTPS, authenticated by its "
                "own Biscuit; the control plane responds with a lease "
                "expiry, or a 401 that triggers re-enrollment."
            ),
            does_not_prove=[
                "connected_peers and dht_size are the router's own "
                "unverified self-report -- the observation records what the "
                "router claimed, not an independently measured mesh "
                "topology fact",
                "a successful lease renewal proves the router's Biscuit was "
                "valid at renewal time, not that the router is healthy, "
                "reachable, or behaving correctly as a relay",
                "a lease self-report is a connectivity/liveness fact only: "
                "it grants no authority, admission, or evidentiary standing "
                "to the router or to any peer it reports, and it is not "
                "itself a published DAGR/Counterpedia record",
            ],
            semantic_class="derived_state",
        ),
        _entry(
            id="SAM-SVC-ADV-01",
            category="service_advertisement",
            status="grounded",
            sam_source_surface=(
                "internal/node/service_registry.go Register()/advertisable()"
                "/ReprovideAll() L44-256"
            ),
            observed_surface=(
                "api.RegisterServiceRequest{service, target_url|command} "
                "(api/sam.proto L123-129); Kademlia DHT Provide(name_cid), "
                "Provide(type_cid)"
            ),
            minimal_meaning=(
                "A node that registered a local service publishes two "
                "Kademlia DHT provider records (service-type CID and "
                "service-name CID) only if a liveness probe of the backend "
                "succeeded within a 2s timeout (advertisable(), L44-60); a "
                "backend that fails the probe is registered locally but "
                "withheld from the DHT until a later probe succeeds "
                "(L81-88, L199-256)."
            ),
            does_not_prove=[
                "DHT presence means 'the node observed this backend answer "
                "a liveness probe recently' -- it is not a claim that the "
                "backend correctly implements MCP, that its tools work, or "
                "that it is authorized for any particular caller",
                "discoverable (present as a DHT provider record) != "
                "invocable (a caller must still open an authenticated MCP "
                "stream and pass per-request authorization; see "
                "SAM-INVOKE-01, SAM-AUTHZ-01)",
            ],
            semantic_class="discovery",
        ),
        _entry(
            id="SAM-SVC-ADV-02",
            category="service_advertisement",
            status="grounded",
            sam_source_surface=(
                "internal/node/discovery/discovery.go package doc + "
                "Announcement type L15-62"
            ),
            observed_surface=(
                "api.ServiceAnnounce{peer_id, type, service_name, keys, "
                "labels, active_requests, latency_ewma_ms, timestamp} "
                "gossiped over per-key GossipSub topics (api/sam.proto "
                "L138-156)"
            ),
            minimal_meaning=(
                "A provider periodically gossips a ServiceAnnounce on the "
                "per-routing-key pubsub topics that currently have "
                "subscribers, self-reporting routing keys, operator-"
                "declared labels, and coarse load hints. Both the proto "
                "comment ('a routing hint signed at the pubsub layer... "
                "never authorization inputs', L140-141) and the package doc "
                "('never authorization inputs', L19-20) say this in those "
                "words."
            ),
            does_not_prove=[
                "SAM's own source states this is never an authorization "
                "input: authenticated (pubsub-signed, and peer_id claim "
                "checked against the message signer in observe(), "
                "internal/node/discovery/view.go L117-122) != "
                "authorized_for_this_context",
                "operator-declared labels in a gossip announce are "
                "unverified self-report until independently checked "
                "against the peer's control-plane-attested Biscuit facts "
                "(see SAM-AUTHZ-03)",
            ],
            semantic_class="discovery",
        ),
        _entry(
            id="SAM-DISC-01",
            category="service_discovery",
            status="grounded",
            sam_source_surface=(
                "internal/node/mcp_handlers.go handleDiscoverRemoteServices "
                "L79-127"
            ),
            observed_surface=(
                "discover_remote_services MCP tool -> api.DiscoveredProvider"
                "{peer_id, local_proxy_url, srv_name, srv_description} "
                "(api/sam.proto L131-136)"
            ),
            minimal_meaning=(
                "discover_remote_services returns the set of DHT/gossip-"
                "observed providers currently known to the local node's "
                "discovery view for a given service type/name: a read of "
                "local, possibly stale, cached observation state."
            ),
            does_not_prove=[
                "a peer appearing in this list has been contacted, is "
                "currently reachable, or will accept a connection -- it is "
                "aggregated from provider records that are themselves not "
                "authorization inputs (see SAM-SVC-ADV-01/02)",
                "does not prove the provider's tools are invocable by the "
                "querying node under current policy",
                "a cached discovery entry carries no authority or admission "
                "weight of its own; it is not evidentiary standing for any "
                "tool call and is not a decision of any kind",
            ],
            semantic_class="discovery",
        ),
        _entry(
            id="SAM-TOOL-DISC-01",
            category="tool_discovery",
            status="grounded",
            sam_source_surface=(
                "internal/node/mcp_handlers.go handleFindRemoteTools "
                "L312-393, gossipToolRows L429-450, "
                "verifyGossipToolRowsWithFetcher L460-542, "
                "fetchRemoteToolCatalogue L575-648 (calls session.ListTools "
                "at L614)"
            ),
            observed_surface=(
                "find_remote_tools MCP tool; MCP ListTools JSON-RPC method "
                "over an authenticated per-peer stream"
            ),
            minimal_meaning=(
                "find_remote_tools first assembles gossip-derived tool-name "
                "candidates (unverified), then re-verifies each candidate "
                "by opening a real MCP session to the claimed peer and "
                "calling ListTools before returning it "
                "(verifyGossipToolRowsWithFetcher). The implementation "
                "itself therefore treats a bare gossip claim as "
                "insufficient and requires a live protocol round-trip to "
                "confirm a tool actually exists at that peer."
            ),
            does_not_prove=[
                "a verified tool listing proves the peer's MCP server "
                "currently advertises a tool of that name/schema at "
                "ListTools time -- it does not prove the tool is authorized "
                "for this caller (see SAM-AUTHZ-01) or that invoking it "
                "will succeed",
                "unverified gossip-only rows remain explicitly weaker "
                "evidence than the verified rows this code path produces; "
                "the two must not be conflated",
            ],
            semantic_class="discovery",
        ),
        _entry(
            id="SAM-INVOKE-01",
            category="invocation_request",
            status="grounded",
            sam_source_surface=(
                "internal/node/mcp.go CallMCPTool L281-317, "
                "ConnectMCPSession L325-430, ErrAuthRejected L319-323; "
                "internal/node/mcp_handlers.go handleCallRemoteTool "
                "L238-253"
            ),
            observed_surface=(
                "call_remote_tool MCP tool -> opens a libp2p stream on "
                "api.MCPProtocolID, performs a Biscuit AuthFrame handshake, "
                "then sends an MCP CallTool JSON-RPC request"
            ),
            minimal_meaning=(
                "An invocation request is a node opening an authenticated "
                "libp2p stream to a target peer, presenting its Biscuit, "
                "then sending a standard MCP CallTool request. The code "
                "distinguishes a transport/reachability failure (retried up "
                "to 3x with backoff) from ErrAuthRejected, documented as "
                "marking 'a service-level authorization denial from a "
                "remote peer, as opposed to a transport/connectivity "
                "failure' (L319-323) -- which is never retried."
            ),
            does_not_prove=[
                "completing the Biscuit handshake proves the caller is "
                "authenticated to that peer at that moment -- it does not "
                "by itself prove the specific tool call will be authorized "
                "(evaluated server-side per request; see SAM-AUTHZ-01) or "
                "will execute correctly",
                "requiredLabels passed to CallMCPTool are fail-closed "
                "verified against the target's control-plane-attested "
                "labels before request data leaves the caller (see "
                "SAM-AUTHZ-03) -- a caller-side precondition, not proof the "
                "callee will also authorize the call",
            ],
            semantic_class="transport",
        ),
        _entry(
            id="SAM-INVOKE-RESULT-01",
            category="invocation_result",
            status="grounded",
            sam_source_surface=(
                "internal/node/mcp.go CallMCPTool return path L281-317; "
                "internal/node/gate.go StreamTransport L149-204"
            ),
            observed_surface=(
                "MCP CallToolResult content returned over the same "
                "already-Biscuit-authenticated libp2p stream used for the "
                "request"
            ),
            minimal_meaning=(
                "An invocation result is whatever MCP CallToolResult "
                "content the remote peer's MCP server returned over the "
                "authenticated stream. Delivery integrity depends on the "
                "libp2p/TLS-secured transport (i.e. 'executed' means the "
                "call round-tripped and returned a result), not on any "
                "separate content-signing of the result payload itself; no "
                "additional per-message signature over CallToolResult "
                "content was found in the reviewed source."
            ),
            does_not_prove=[
                "executed (a CallToolResult was returned) != output_trusted "
                "-- SAM authenticates the channel and the calling/called "
                "peers, not the semantic correctness or truthfulness of the "
                "tool's output content",
                "does not prove the result is evidence_supported, admitted, "
                "or published in any DAGR/Counterpedia sense; SAM has no "
                "receipt, disposition, or evidentiary concept of its own "
                "for this content",
            ],
            semantic_class="execution",
        ),
        _entry(
            id="SAM-AUTHZ-01",
            category="policy_role_target_authorization",
            status="grounded",
            sam_source_surface=(
                "internal/node/middleware.go Authorize() L202-345; "
                "internal/node/policy.go BuildPolicyRules() L11-133"
            ),
            observed_surface=(
                "per-request Biscuit Datalog authorization over injected "
                "FactService/FactAgent/FactConnectionPeerID facts, "
                "BaselineTargetCheck/BaselinePolicies/BaselineRules, plus "
                "roles/bindings from api.PolicyConfigUpdateRequest (api/"
                "sam.proto L179-206) compiled by BuildPolicyRules"
            ),
            minimal_meaning=(
                "Authorization for one request is a Datalog proof run "
                "locally by the peer being called, over facts it injects "
                "itself (claimed target service/agent, connection peer_id) "
                "plus whatever role/target grants the control plane "
                "compiled into the caller's Biscuit at mint time "
                "(mintBiscuit, internal/identity/biscuit.go L64-226) and "
                "whatever dynamic mesh policy rules the callee currently "
                "holds (middleware.go L291-298). A pass means only: this "
                "Datalog world, evaluated by this callee, right now, "
                "authorizes this (service, target) pair for this Biscuit."
            ),
            does_not_prove=[
                "authorized_for_this_context is evaluated independently by "
                "every callee for every request; it is not a global, "
                "portable, or previously-recorded admission decision, and a "
                "grant by one node says nothing about any other node's "
                "evaluation of the same Biscuit",
                "a role/target grant compiled from PolicyConfigUpdateRequest "
                "is a control-plane operator's current configuration, not a "
                "DAGR admission decision, and must never be treated as "
                "domain admission, evidentiary standing, factual truth, or "
                "delegated DAGR/Counterpedia authority",
            ],
            semantic_class="authorization",
        ),
        _entry(
            id="SAM-AUTHZ-02",
            category="policy_role_target_authorization",
            status="grounded",
            sam_source_surface=(
                "internal/router/router.go performMutualAuth role check "
                "L941-958; internal/identity/biscuit.go VerifyBiscuitRole() "
                "L431-457"
            ),
            observed_surface=(
                "Biscuit role() fact checked via a Datalog Check against a "
                "specific expected role string"
            ),
            minimal_meaning=(
                "'Holds role X' is narrower than general authorization: a "
                "Check requiring role(\"X\") to be provable succeeded "
                "against one specific Biscuit, verified by one specific "
                "verifier holding the matching public key, before token "
                "expiry."
            ),
            does_not_prove=[
                "does not prove the role assignment reflects current "
                "control-plane operator intent -- only that the Biscuit, as "
                "signed, carries a role() fact of that name",
                "role != target authorization: AllowedTargets/"
                "AllowedServices are separate PolicyRole fields compiled "
                "into separate Datalog facts (BuildServiceDatalogFacts/"
                "BuildTargetDatalogFacts, internal/node/policy.go), so "
                "holding a role does not by itself imply any target grant",
            ],
            semantic_class="authorization",
        ),
        _entry(
            id="SAM-AUTHZ-03",
            category="policy_role_target_authorization",
            status="grounded",
            sam_source_surface=(
                "internal/node/labels_gate.go VerifyPeerLabels() L31-70+"
            ),
            observed_surface=(
                "api.FactLabel Biscuit facts fetched directly from the "
                "target peer and checked fail-closed against requiredLabels"
            ),
            minimal_meaning=(
                "A caller that requires a peer to hold specific labels "
                "(e.g. region) does not trust the gossip-advertised label "
                "map: it fetches the target's Biscuit directly and checks "
                "for a matching control-plane-attested label() fact, "
                "rejecting fail-closed a peer that returns no Biscuit or "
                "lacks the fact, with a bounded 5-minute positive-result "
                "cache (L31-43, L59-70)."
            ),
            does_not_prove=[
                "gossip-declared labels (see SAM-SVC-ADV-02) are explicitly "
                "a ranking/routing hint only; only this control-plane-"
                "attested Biscuit check is treated by SAM's own code as "
                "authorization-grade",
                "a cached positive verdict can be up to 5 minutes stale "
                "relative to the peer's current label facts",
            ],
            semantic_class="authorization",
        ),
        _entry(
            id="SAM-LEASE-01",
            category="lease_session_connection",
            status="grounded",
            sam_source_surface=(
                "api.TokenRefreshRequest/Response, api.TokenRevokeRequest/"
                "Response (api/sam.proto L212-230); internal/identity/"
                "biscuit.go VerifyAndExtractPeerID() L364-429"
            ),
            observed_surface=(
                "token refresh: challenge_signature+timestamp -> new "
                "biscuit_token+expires_at; token revoke: peer_id -> "
                "success/error"
            ),
            minimal_meaning=(
                "A node can renew its Biscuit before expiry by proving "
                "continued possession of its private key, without a fresh "
                "OIDC/bootstrap round-trip; VerifyAndExtractPeerID's own "
                "doc comment says it 'does NOT perform time checks, making "
                "it suitable for token refresh flows' (L364-366). The "
                "control plane can separately revoke a peer_id."
            ),
            does_not_prove=[
                "a successful refresh proves key possession, not that the "
                "original enrollment grounds (JWT claims, labels, role) are "
                "still accurate -- refresh explicitly skips re-verifying them",
                "revocation propagation timing and mid-session enforcement "
                "were not traced end-to-end in this recon; see "
                "SAM-UNRESOLVED-01",
                "a token refresh or revoke changes only SAM's own local "
                "credential lifecycle; it confers no DAGR admission, "
                "evidentiary standing, or publication status, and is not "
                "itself a DAGR/Counterpedia decision",
            ],
            semantic_class="derived_state",
        ),
        _entry(
            id="SAM-CONN-01",
            category="lease_session_connection",
            status="grounded",
            sam_source_surface=(
                "internal/node/connection_monitor.go checkRouterConnection() "
                "L19-99; internal/node/gate.go StreamTransport.SessionID() "
                "L191-194"
            ),
            observed_surface=(
                "local mesh-connectivity health check (stable/reconnected "
                "booleans); MCP session id = remote peer ID string"
            ),
            minimal_meaning=(
                "'Connected' is a local, point-in-time liveness observation "
                "of this node's own link to its configured routers, "
                "recovered opportunistically via stored P2P addresses or "
                "HTTP control-plane fallback. An MCP 'session' over a "
                "libp2p stream is identified only by the remote peer's ID, "
                "not a separately minted session token."
            ),
            does_not_prove=[
                "a locally-observed 'stable' connection state says nothing "
                "about connection quality or authorization state as seen by "
                "the remote router -- it is this node's own reconnection-"
                "loop bookkeeping",
                "session identity being the bare peer ID means a session "
                "observation is exactly as strong as the peer-ID-binding of "
                "the underlying Biscuit (see SAM-ID-01) and no stronger",
            ],
            semantic_class="derived_state",
        ),
        _entry(
            id="SAM-INFER-01",
            category="inference_provider_routing",
            status="grounded",
            sam_source_surface=(
                "internal/node/inference_engine.go openAIEngine.Models() "
                "L48-64; internal/node/openai_facade.go collectModels() "
                "L253-302, providersFor() L198-226, staleLocked()/"
                "refreshLocked() L241-248"
            ),
            observed_surface=(
                "OpenAI-compatible GET /v1/models probed against local "
                "services first, then mesh-discovered peers "
                "(fetchRemoteModels); result cached with a TTL, treated as "
                "stale whenever empty"
            ),
            minimal_meaning=(
                "The model->provider map the OpenAI-compatible facade "
                "exposes is built by actively probing each known local "
                "service's and each mesh-discovered peer's /v1/models "
                "endpoint within the current TTL window, preferring local "
                "services first in iteration order: a live-probed "
                "inventory, not a control-plane-issued or authorization-"
                "checked capability grant."
            ),
            does_not_prove=[
                "a model appearing in this view proves only that some peer's "
                "/v1/models responded with that model ID at probe time -- "
                "not a claim about quality, availability guarantees, or the "
                "caller's authorization to use it",
                "does not prove request routing to a provider succeeds or "
                "is authorized; providersFor only selects a candidate -- "
                "actual invocation is a separate authenticated call subject "
                "to SAM-AUTHZ-01",
            ],
            semantic_class="derived_state",
        ),
        _entry(
            id="SAM-INFER-02",
            category="inference_provider_routing",
            status="grounded",
            sam_source_surface=(
                "internal/node/openai_facade.go facadeRR atomic.Uint64 "
                "L304-306, handleCompletions() L335+"
            ),
            observed_surface=(
                "round-robin selection across equally-ranked modelProvider "
                "entries for a requested model"
            ),
            minimal_meaning=(
                "When more than one provider serves a requested model, the "
                "facade spreads load round-robin across them: a load-"
                "distribution heuristic over the already-probed provider "
                "set from SAM-INFER-01, not a quality-, cost-, or policy-"
                "based routing decision."
            ),
            does_not_prove=[
                "round-robin selection does not prove the chosen provider "
                "is the best, cheapest, most authorized, or most "
                "trustworthy option -- it is unweighted rotation over "
                "whichever providers most recently answered a models probe",
            ],
            semantic_class="derived_state",
        ),
        _entry(
            id="SAM-UNRESOLVED-01",
            category="lease_session_connection",
            status="observation_only",
            sam_source_surface=(
                "api.MeshEvent (api/sam.proto L40-51); internal/router/"
                "router.go verifyEvent() L550-568, "
                "listenForControlPlaneEvents() L569-624"
            ),
            observed_surface=(
                "MeshEvent{type: BANNED|KEY_ROTATION|POLICY_UPDATE, "
                "peer_id, timestamp, new_public_key, signature} pushed "
                "over the router's EventTopic"
            ),
            minimal_meaning=(
                "Routers listen for and cryptographically verify "
                "(verifyEvent) BANNED/KEY_ROTATION/POLICY_UPDATE gossip "
                "events. This recon confirms the event shape and that "
                "verification happens, but did NOT trace the full "
                "propagation-latency and mid-session-eviction contract "
                "(e.g. internal/controlplane/*, dnstcp.go were out of "
                "scope for this pass) -- per the lane's STOP conditions, "
                "this stays unresolved rather than being asserted."
            ),
            does_not_prove=[
                "does not establish that revocation is propagated "
                "synchronously mesh-wide, or that an already-open "
                "authenticated stream is forcibly closed when a BANNED "
                "event for its peer arrives elsewhere in the mesh",
                "even where confirmed, SAM's own ban/policy propagation is "
                "a mesh-transport control decision internal to SAM; it is "
                "not, and does not become, a DAGR admission, evidentiary "
                "standing, or publication decision",
            ],
            semantic_class="derived_state",
            notes=(
                "Fails closed to observation_only per the lane's "
                "acceptance gates: unknown/unstable SAM surfaces must not "
                "be asserted as grounded mappings."
            ),
        ),
    ]


def build_crosswalk() -> dict[str, Any]:
    """Return the full crosswalk document as a plain JSON-able dict."""
    entries = _build_entries()

    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids)), "duplicate entry id"

    covered = {e["category"] for e in entries}
    missing = set(REQUIRED_CATEGORIES) - covered
    assert not missing, f"crosswalk missing required categories: {missing}"

    return {
        "lane": "SAM-SEMANTICS-RECON0",
        "crosswalk_version": CROSSWALK_VERSION,
        "authority_movement": 0,
        "generated_by": "tools/generate_sam_semantics_crosswalk.py",
        "sam_source": {
            "repo": SAM_REPO,
            "revision": SAM_REVISION,
            "retrieved_at": SAM_RETRIEVED_AT,
            "disclaimer": SAM_DISCLAIMER,
        },
        "mandatory_non_equivalence_ladder": list(NON_EQUIVALENCE_LADDER),
        "required_categories": list(REQUIRED_CATEGORIES),
        "semantic_classes": list(SEMANTIC_CLASSES),
        "entries": sorted(entries, key=lambda e: e["id"]),
    }


def render(data: dict[str, Any]) -> str:
    """Canonical, deterministic JSON rendering: sorted keys, fixed indent."""
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def generate_crosswalk(output_path: Path = OUTPUT_PATH) -> dict[str, Any]:
    """Build the crosswalk and write it deterministically to output_path."""
    data = build_crosswalk()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render(data), encoding="utf-8")
    return data


def main() -> None:
    generate_crosswalk()
    print(f"wrote {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
