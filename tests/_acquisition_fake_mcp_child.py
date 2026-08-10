"""Hermetic fake EXTERNAL acquisition MCP stdio child (DAGR-MCP-SOURCE0).

Run as a standalone script (``python _acquisition_fake_mcp_child.py``), never
imported: :mod:`dagr_mcp_service.connectors.stdio` launches it as a real
subprocess and speaks the standard MCP stdio initialize / ``tools/list`` /
``tools/call`` lifecycle to it, exactly as it would to the real, independently
authored ``counterpedia-acquisition`` MCP server.

This file contains **no DAGR code and imports nothing from this repository**,
and imports nothing from ``counterpedia_acquisition`` either — it is a *fake*
stand-in that reproduces only the external surface's observable protocol facts,
pinned in :mod:`dagr_mcp_service.acquisition_connector`:

* the four dotted, acquisition-scoped, proposal-only tool names
  (``acquisition.capture_url`` / ``acquisition.process_source`` /
  ``acquisition.compare_captures`` / ``acquisition.process_browser_observation``);
* the ``acquisition.mcp_surface.v0.1`` surface-schema tag echoed in each result;
* proposal-only result shapes: refs / digests only, ``is_proposal`` true, an
  explicit ``source_capture`` eligibility hint, never an aggregate trust score,
  never an admit/approve/publish/verify verdict.

It is hermetic: no network, no model, no API key. A distinct ``DAGR_ACQ_FIXTURE``
env var switches deterministic failure postures so the governed connector's
outcome-uncertainty handling can be exercised without any real acquisition
backend. Two optional log files (``DAGR_ACQ_CALL_LOG``, ``DAGR_ACQ_SIDE_EFFECT_LOG``)
let a test prove exactly-once delivery and post-forward side-effect occurrence.
"""

from __future__ import annotations

import os
import time

from fastmcp import FastMCP

server = FastMCP("fake-external-acquisition")

_SURFACE_SCHEMA = "acquisition.mcp_surface.v0.1"


def _append(env_key: str, line: str) -> None:
    path = os.environ.get(env_key)
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def _fake_digest(value: str) -> str:
    # A stand-in content-address digest ref. Not a real hash of any bytes — this
    # is a fake server; it only needs to look like the refs/digests the real
    # proposal-only surface returns (never raw bytes).
    return "sha256:" + f"{abs(hash(value)) & ((1 << 256) - 1):064x}"


def _maybe_fail(mode: str) -> None:
    """Enact the configured post-forward failure posture, if any.

    ``hang`` sleeps far past any test timeout (the connector's own timeout fires,
    surfacing an admitted-but-uncertain outcome); ``crash`` exits the process
    abruptly mid-call; ``error`` raises so the tool returns an MCP tool error.
    Each is reached only *after* the call has been forwarded to this child, so a
    test can prove the governed outcome preserves uncertainty rather than coerces
    a success — the side-effect log is standing proof the work reached here.
    """

    if mode == "hang":
        time.sleep(3600)
    elif mode == "crash":
        os._exit(7)
    elif mode == "error":
        raise ValueError("acquisition-internal-failure-detail")


@server.tool(name="acquisition.capture_url")
def capture_url(url: str) -> dict:
    """Proposal-only capture projection: refs/digests, never raw bytes."""
    _append("DAGR_ACQ_CALL_LOG", f"capture_url:{url}")
    _append("DAGR_ACQ_SIDE_EFFECT_LOG", "side-effect-performed")
    _maybe_fail(os.environ.get("DAGR_ACQ_FIXTURE", ""))
    return {
        "tool": "acquisition.capture_url",
        "surface_schema": _SURFACE_SCHEMA,
        "capture_status": "captured",
        "capture_id": "capture:fake:0001",
        "captured_object_address": _fake_digest(url),
        "byte_count": len(url),
    }


@server.tool(name="acquisition.process_source")
def process_source(input_locator: str) -> dict:
    """Proposal-only source-session projection.

    Returns a grounded proposal (``is_proposal`` true) plus an explicit
    ``source_capture`` eligibility hint — a producer fact, never a verdict. No
    admission, standing, or verification is asserted.
    """
    _append("DAGR_ACQ_CALL_LOG", f"process_source:{input_locator}")
    _append("DAGR_ACQ_SIDE_EFFECT_LOG", "side-effect-performed")
    _maybe_fail(os.environ.get("DAGR_ACQ_FIXTURE", ""))
    return {
        "tool": "acquisition.process_source",
        "surface_schema": _SURFACE_SCHEMA,
        "session_status": "composed",
        "source_id": "source:fake:0001",
        "captured_object_address": _fake_digest(input_locator),
        "grounded_proposal": {
            "is_proposal": True,
            "proposal_ref": "proposal:fake:0001",
            "grounded_claim_count": 2,
        },
        # A producer fact — a referenced source_capture eligibility hint that
        # stays a proposal-adjacent fact; the governed boundary confers nothing.
        "source_capture_binding_status": "SRS-source-capture-ineligible",
        "declaring_artifact_ref": "declaration:fake:0001",
    }


@server.tool(name="acquisition.compare_captures")
def compare_captures(left: str, right: str) -> dict:
    _append("DAGR_ACQ_CALL_LOG", f"compare_captures:{left}|{right}")
    _maybe_fail(os.environ.get("DAGR_ACQ_FIXTURE", ""))
    return {
        "tool": "acquisition.compare_captures",
        "surface_schema": _SURFACE_SCHEMA,
        "comparison": {"left_ref": _fake_digest(left), "right_ref": _fake_digest(right), "identical": left == right},
    }


@server.tool(name="acquisition.process_browser_observation")
def process_browser_observation(observation: str) -> dict:
    _append("DAGR_ACQ_CALL_LOG", f"process_browser_observation:{observation}")
    _maybe_fail(os.environ.get("DAGR_ACQ_FIXTURE", ""))
    return {
        "tool": "acquisition.process_browser_observation",
        "surface_schema": _SURFACE_SCHEMA,
        "session_status": "composed",
        "grounded_proposal": {"is_proposal": True, "proposal_ref": "proposal:fake:0002"},
        "observation_hint_present": True,
    }


if __name__ == "__main__":
    server.run(transport="stdio", show_banner=False)
