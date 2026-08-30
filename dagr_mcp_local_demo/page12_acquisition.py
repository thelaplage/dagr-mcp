"""LOCAL-DEMO-ONLY zero-argument DAGR adapter factory for PAGE12 capture.

.. warning::

   **LOCAL DEMO ONLY. EXPLICITLY NON-PRODUCTION.** This module encodes a single,
   owner-frozen, deliberately narrow demo policy for
   ``PAGE12-GOVERNED-CAPTURE0`` — the governed capture of exactly the 74
   authorized ``needs_capture`` source locators of the PAGE10 acceptance corpus,
   frozen by PAGE10-SOURCE-TRAVERSE0 (counterpedia-authoring #189). It is not a
   production policy pack, is not wired into any released runtime path, and must
   never be used to govern a real institutional trust boundary.

Canonical selector (what a caller passes to acquisition's ``load_dagr_adapter``)::

    dagr_mcp_local_demo.page12_acquisition:build_adapter

This is a THIRD, distinct local-demo factory alongside
``dagr_mcp_local_demo.counterpedia_acquisition`` (LIVE-AUTHORING-ACCEPT0, admits
ONLY ``acquisition.process_held_capture``) and
``dagr_mcp_local_demo.wave100_acquisition`` (WAVE100, admits ``capture_url`` but
under a wave100-labelled boundary/actor/policy-pack). Both are frozen and are
neither modified nor widened here. PAGE12 needs its OWN factory precisely so its
receipts carry honest PAGE12 provenance rather than wave100's labels; reusing the
wave100 factory would stamp PAGE12 captures with wave100 boundary/actor ids. This
module provides the narrow, distinctly-labelled PAGE12 policy instead.

The factory is **zero-argument**. It returns a real
:class:`dagr_mcp_sdk_binding.adapter.SdkLifecycleAdapter`, so acquisition's
``isinstance(result, SdkLifecycleAdapter)`` nominal gate passes. It reads exactly
one piece of caller-selected configuration — the durable evidence directory — and
**fails closed** (raises) if that configuration is missing or invalid.

Frozen policy encoded here (verbatim, not broadened)
----------------------------------------------------

* **scope** — ``PAGE12-GOVERNED-CAPTURE0`` local demo only; NON-PRODUCTION.
* **allowed tool** — ``acquisition.capture_url`` ONLY → ``disposition=admitted``,
  ``tool_class=write``.
* **every other tool** — ``disposition=refused`` with
  ``reason_code=local_demo_tool_not_allowed``. There is **no** wildcard admit and
  **no** defer/review path: an out-of-scope tool REFUSES, it never defers. In
  particular ``acquisition.process_held_capture`` (the LIVE-AUTHORING tool) is
  refused here — the two demo policies stay disjoint.
* **actor** — FIXED ``actor:counterpedia-local-demo:page12-operator``. It is
  never derived from tool arguments, the request URL, or captured content.
* **ids** — ``runtime_instance_id``, ``boundary_id``, ``policy_pack_id`` and
  ``policy_pack_version`` are fixed to the frozen PAGE12 local-demo values below.
* **signing / custody** — an ephemeral, per-run, NON-PRODUCTION
  :class:`~dagr_mcp.srs_receipts.SigningIdentity` is generated in memory. The
  private key is **never** persisted, logged, or returned. The corresponding
  PUBLIC verification/trust material (the trust bundle) is written alongside the
  run evidence so a verifier can recompute signatures. Signed envelopes land in
  the caller-selected durable evidence directory via
  :class:`~dagr_mcp.srs_receipts.RawEnvelopeFileSink` — never an anonymous
  throwaway tempdir. If the required evidence/custody configuration is missing or
  invalid, the factory fails closed.

The source scope (the exact 74 authorized locators) is NOT re-encoded here: it is
enforced by the PAGE12 capture driver, which consumes the frozen #189 manifest
and drives the generic governed capture consumer
(``acquisition.wave100_live.GovernedCaptureSurface``). The SdkBindingConfig
interface exposes no canonical per-argument/domain constraint seam to duplicate
the locator set into. This factory governs the *tool* (``acquisition.capture_url``
admit / everything-else refuse); the driver governs *which locators* are driven.

Nothing in this module removes acquisition's requirement that an operator supply
a factory; it merely provides one acceptable, narrow, PAGE12 local-demo factory.
"""

from __future__ import annotations

import os
from pathlib import Path

from dagr_mcp.srs_receipts import (
    RawEnvelopeFileSink,
    SignedReceiptEmitter,
    SigningIdentity,
)
from dagr_mcp_sdk_binding.adapter import SdkBindingConfig, SdkLifecycleAdapter
from dagr_mcp_sdk_binding.neutral import (
    ActorResolution,
    BindingPolicy,
    RequestSnapshot,
)

# --------------------------------------------------------------------------- #
# Frozen PAGE12 local-demo policy constants (do NOT broaden)                 #
# --------------------------------------------------------------------------- #

#: The single tool this local-demo policy admits. Every other tool is refused.
ALLOWED_TOOL: str = "acquisition.capture_url"

#: Fixed actor reference. NEVER derived from arguments, the URL, or captured
#: content.
FIXED_ACTOR_REF: str = "actor:counterpedia-local-demo:page12-operator"

#: Refusal reason code emitted for every out-of-scope (non-allowed) tool.
REFUSAL_REASON_CODE: str = "local_demo_tool_not_allowed"

RUNTIME_INSTANCE_ID: str = "counterpedia-local-demo:page12-governed-capture0"
BOUNDARY_ID: str = "counterpedia-acquisition-mcp:page12-governed-capture0"
POLICY_PACK_ID: str = "policy:counterpedia-local-demo:page12-governed-capture0"
POLICY_PACK_VERSION: str = "0.1"

#: Clearly non-production ephemeral signing issuer identity (public label only;
#: the private key material is generated per-run in memory and never persisted).
_ISSUER_ID: str = "urn:counterpedia-local-demo:nonprod-ephemeral-issuer:page12"

#: Caller-selected, REQUIRED environment variable naming the durable evidence
#: directory that receives signed SRS envelopes and the public trust bundle. The
#: factory fails closed if it is unset or does not name a writable directory. A
#: PAGE12-specific variable keeps this evidence trail disjoint from the
#: LIVE-AUTHORING-ACCEPT0 factory's.
EVIDENCE_DIR_ENV: str = "COUNTERPEDIA_LOCAL_DEMO_PAGE12_EVIDENCE_DIR"


class LocalDemoConfigError(RuntimeError):
    """Raised (fail-closed) when the required evidence/custody config is invalid.

    Its message intentionally names only the env var and a non-sensitive reason;
    it never carries signing/private material.
    """


# --------------------------------------------------------------------------- #
# The frozen resolvers                                                        #
# --------------------------------------------------------------------------- #


def _fixed_actor_resolver(request_context: object, snapshot: RequestSnapshot) -> ActorResolution:
    """Return the FIXED demo operator actor, ignoring all request-derived input.

    Neither argument is consulted: the actor is a constant, so no actor identity
    can ever be smuggled in through tool arguments, the request URL, request
    context, or captured content.
    """

    return ActorResolution(actor_ref=FIXED_ACTOR_REF)


def _narrow_policy_resolver(snapshot: RequestSnapshot, actor: ActorResolution) -> BindingPolicy:
    """Admit ONLY ``acquisition.capture_url`` (write); REFUSE all else.

    There is no wildcard admit and no defer/review path. An out-of-scope tool is
    refused with the frozen ``local_demo_tool_not_allowed`` reason code, which the
    adapter preserves verbatim on the terminal admission receipt.
    """

    if snapshot.tool_name == ALLOWED_TOOL:
        return BindingPolicy(disposition="admitted", tool_class="write")
    return BindingPolicy(
        disposition="refused",
        tool_class="read",
        reason_code=REFUSAL_REASON_CODE,
    )


# --------------------------------------------------------------------------- #
# Evidence / custody wiring                                                   #
# --------------------------------------------------------------------------- #


def _resolve_evidence_dir() -> Path:
    """Resolve and validate the caller-selected evidence directory (fail closed).

    Requires ``COUNTERPEDIA_LOCAL_DEMO_PAGE12_EVIDENCE_DIR`` to name an existing,
    writable directory. It is deliberately NOT auto-created and NEVER falls back
    to an anonymous tempdir: a missing/invalid value is a hard, fail-closed error.
    """

    raw = os.environ.get(EVIDENCE_DIR_ENV)
    if not raw or not raw.strip():
        raise LocalDemoConfigError(
            f"{EVIDENCE_DIR_ENV} is required and must name a durable, writable "
            "evidence directory (local-demo custody must not use a throwaway tempdir)"
        )
    path = Path(raw).expanduser()
    if not path.exists():
        raise LocalDemoConfigError(
            f"{EVIDENCE_DIR_ENV} does not exist; the caller must create the durable "
            "evidence directory before invoking the local-demo factory"
        )
    if not path.is_dir():
        raise LocalDemoConfigError(f"{EVIDENCE_DIR_ENV} does not name a directory")
    if not os.access(path, os.W_OK | os.X_OK):
        raise LocalDemoConfigError(f"{EVIDENCE_DIR_ENV} is not a writable directory")
    return path


def build_adapter() -> SdkLifecycleAdapter:
    """Zero-argument LOCAL-DEMO factory returning a governed ``SdkLifecycleAdapter``.

    Fails closed if the required evidence/custody configuration
    (``COUNTERPEDIA_LOCAL_DEMO_PAGE12_EVIDENCE_DIR``) is missing or invalid. On
    success it mirrors the LIVE-AUTHORING-ACCEPT0 factory's composition exactly,
    changing only the admitted tool (``acquisition.capture_url``), the fixed
    PAGE12 actor/ids, and the evidence env:

    1. Validates the caller-selected durable evidence directory.
    2. Generates an ephemeral, per-run, NON-PRODUCTION signing identity in memory
       (private key never persisted / logged / returned).
    3. Writes the PUBLIC trust bundle into the evidence directory so a verifier
       can recompute signatures.
    4. Builds a :class:`RawEnvelopeFileSink` under the evidence directory and a
       :class:`SignedReceiptEmitter` over the ephemeral identity.
    5. Constructs the narrow, frozen :class:`SdkBindingConfig` and returns the
       adapter. Receipt-failure maps are left at their defaults
       (write → ``fail_closed``).
    """

    evidence_dir = _resolve_evidence_dir()

    identity = SigningIdentity.generate(issuer_id=_ISSUER_ID, key_id=f"{_ISSUER_ID}/key/1")

    sink = RawEnvelopeFileSink(evidence_dir)
    sink.write_trust_bundle(identity.trust_bundle())

    emitter = SignedReceiptEmitter(identity=identity, sink=sink)

    config = SdkBindingConfig(
        runtime_instance_id=RUNTIME_INSTANCE_ID,
        boundary_id=BOUNDARY_ID,
        policy_pack_id=POLICY_PACK_ID,
        policy_pack_version=POLICY_PACK_VERSION,
        tool_classes={ALLOWED_TOOL: "write"},
        actor_resolver=_fixed_actor_resolver,
        policy_resolver=_narrow_policy_resolver,
    )

    return SdkLifecycleAdapter(emitter=emitter, config=config)


__all__ = [
    "ALLOWED_TOOL",
    "BOUNDARY_ID",
    "EVIDENCE_DIR_ENV",
    "FIXED_ACTOR_REF",
    "LocalDemoConfigError",
    "POLICY_PACK_ID",
    "POLICY_PACK_VERSION",
    "REFUSAL_REASON_CODE",
    "RUNTIME_INSTANCE_ID",
    "build_adapter",
]
