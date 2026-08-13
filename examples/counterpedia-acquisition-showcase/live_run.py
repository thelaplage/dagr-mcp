"""LIVE example: DAGR-MCP-SOURCE0's own merged, pinned connector factory
(``dagr_mcp_service.acquisition_connector.build_acquisition_connector``,
PR #41 / a9e7088) driving a REAL, unmodified ``counterpedia-acquisition``
MCP server (``acquisition.mcp_server`` over the official ``mcp==1.29.0``
SDK) as a child process over stdio.

DAGR-MCP-SOURCE0 landed the pinned target config and 22 hermetic tests
against a *fake* MCP child (``tests/_acquisition_fake_mcp_child.py``). This
script is that connector's live-run companion: same
``build_acquisition_connector`` factory, same pinned tool names/handle, but
a real subprocess, a real MCP handshake, and a real outbound HTTP fetch
(against a local fixture server this script starts itself -- no real
external network access). No mocks or stubs of dagr-mcp or of
counterpedia-acquisition anywhere in this file.

CP-DAGR-MCP-ACQ0-PROOF, not CP-DAGR-MCP-ACQ0: this proves the generic
transport/runtime wedge -- dagr-mcp can govern the real acquisition MCP
child end to end -- standing alone, independent of counterpedia-authoring.
It deliberately does NOT call ``acquisition.process_source`` (the tool
counterpedia-authoring's real producer re-fetch seam,
``ProducerAcquisitionToolClient`` / ``McpStdioAcquisitionToolTransport``,
actually uses) -- that call is exercised here only as a REFUSED case, to
keep this proof decoupled from authoring's in-flight
``fix/author-acq0-producer-contract-boundary-v0-1`` work. Governing the
real ``process_source`` seam is CP-DAGR-MCP-ACQ0-BIND, a follow-on once that
branch lands. Nothing in counterpedia-acquisition or counterpedia-authoring
is modified by this example.

Scenarios exercised:
  1. ADMIT  -- acquisition.capture_url against a fixture URL this example's
              policy allows (the "in-scope" local HTTP fixture). Child
              spawned once, a real HTTP GET happens, a real CaptureUrlResult
              comes back, receipts emitted.
  2. REFUSE -- acquisition.capture_url against a URL this example's policy
              does NOT allow (a second, "out-of-scope" local HTTP fixture).
              Refused by this example's own policy layer, not by the target
              server -- the out-of-scope fixture's hit counter must stay 0.
  3. REFUSE -- acquisition.process_source, a tool this showcase's launcher
              cannot safely serve (it wires no ``observer``, so the surface
              itself would fail closed with McpSurfaceError if ever called).
              This example's policy refuses the whole tool class before the
              child is ever spawned; the in-scope fixture's hit counter must
              stay unchanged from scenario 1.
  4. REFUSE (fail-closed, unknown tool) -- a tool name that is not in the
              connector's own known_tools allowlist at all. Refused by
              StdioToolConnector.resolve() itself, before the (optional)
              policy_resolver ever runs and before any admission receipt is
              emitted.

This script demonstrates ONE configured governed path over ONE real
Counterpedia-native stdio MCP server. It does not claim that "acquisition is
governed" in general, nor any aggregate trust/safety/verification verdict
about acquisition, its captured content, or Counterpedia standing -- see the
README's "What this does not claim" section. A DAGR admission/outcome
receipt records that a call was admitted and observed at this boundary; it
is not acquisition's own source/capture/provenance evidence and does not
substitute for it.

This file is self-contained and portable: it hardcodes no machine-specific
paths except the counterpedia-acquisition checkout location, which is
supplied via --acquisition-path / ACQUISITION_REPO_PATH.

Run (see README.md for full prerequisites):

    export DAGR_MCP_SHOWCASE_WORKDIR="$(mktemp -d)"
    python live_run.py --acquisition-path /path/to/counterpedia-acquisition
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from socketserver import TCPServer
from types import SimpleNamespace


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workdir",
        default=os.environ.get("DAGR_MCP_SHOWCASE_WORKDIR", ""),
        help="Directory to hold generated receipts and output JSON. "
        "Defaults to a fresh tempfile.mkdtemp() directory (or the "
        "DAGR_MCP_SHOWCASE_WORKDIR environment variable). Never commit it.",
    )
    parser.add_argument(
        "--acquisition-path",
        default=os.environ.get("ACQUISITION_REPO_PATH", ""),
        help="Path to a counterpedia-acquisition checkout (its src/ layout "
        "-- this script adds <path>/src to the launched child's "
        "PYTHONPATH). Defaults to a sibling '../../../counterpedia-"
        "acquisition' directory next to this dagr-mcp checkout.",
    )
    parser.add_argument(
        "--dagr-mcp-path",
        default=os.environ.get("DAGR_MCP_PATH", ""),
        help="Optional path to a dagr-mcp checkout to prepend to sys.path, "
        "for running against a local source tree without `pip install`.",
    )
    return parser.parse_args()


_ARGS = _parse_args()

if _ARGS.dagr_mcp_path:
    sys.path.insert(0, str(Path(_ARGS.dagr_mcp_path).resolve()))

import anyio  # noqa: E402

from dagr_mcp.srs_receipts import RawEnvelopeFileSink, SigningIdentity, sha256_digest  # noqa: E402
from dagr_mcp_service.acquisition_connector import (  # noqa: E402
    ACQUISITION_SURFACE_COMMIT,
    ACQUISITION_TOOL_CAPTURE_URL,
    ACQUISITION_TOOL_NAMES,
    ACQUISITION_TOOL_PROCESS_SOURCE,
    DEFAULT_ACQUISITION_TARGET_HANDLE,
    build_acquisition_connector,
)
from dagr_mcp_service.adapter import GatewayAdapterConfig, execute_governed_call  # noqa: E402
from dagr_mcp_service.contract import (  # noqa: E402
    CallerGovernedCallRequest,
    GovernedCallRequest,
    TargetServerRef,
    TrustedActorRef,
)
from dagr_mcp_service.resolution import SDK_BINDING_VERSION, BindingSelectorKey  # noqa: E402

WORKDIR = Path(_ARGS.workdir).resolve() if _ARGS.workdir else Path(tempfile.mkdtemp(prefix="dagr-mcp-cp-acq-showcase-"))
WORKDIR.mkdir(parents=True, exist_ok=True)
RECEIPTS_DIR = WORKDIR / "receipts"

_THIS_DIR = Path(__file__).resolve().parent
ACQUISITION_REPO = (
    Path(_ARGS.acquisition_path).resolve()
    if _ARGS.acquisition_path
    else (_THIS_DIR / ".." / ".." / ".." / "counterpedia-acquisition").resolve()
)
ACQUISITION_SRC = ACQUISITION_REPO / "src"
if not (ACQUISITION_SRC / "acquisition" / "__init__.py").exists():
    raise SystemExit(
        f"counterpedia-acquisition not found at {ACQUISITION_REPO} "
        "(expected src/acquisition/__init__.py). Pass --acquisition-path "
        "or set ACQUISITION_REPO_PATH."
    )

LAUNCHER = str(_THIS_DIR / "launch_acquisition_mcp.py")
PYTHON_EXECUTABLE = sys.executable

# DAGR-MCP-SOURCE0's own pinned target handle/tool-name set (PR #41), not a
# copy: this example imports and drives the merged factory directly rather
# than re-declaring its own StdioTargetConfig, so it stays byte-identical to
# what that module actually pins if it ever changes.
TARGET_HANDLE = DEFAULT_ACQUISITION_TARGET_HANDLE

CONNECTOR = build_acquisition_connector(
    (PYTHON_EXECUTABLE, LAUNCHER),
    env={"PYTHONPATH": str(ACQUISITION_SRC)},
    timeout_seconds=30.0,
)


# ---------------------------------------------------------------------------
# In-scope / out-of-scope fixture HTTP servers. Both run in THIS process; the
# child process performs a real outbound HTTP GET against whichever one a
# call's URL points at, so their hit counters are an honest, external check
# of whether the child actually fetched -- not a claim self-reported by the
# governed call path.
# ---------------------------------------------------------------------------


def _make_fixture_server(label: str, hits: dict) -> tuple[TCPServer, str]:
    body = f"<html><body>synthetic fixture: {label}</body></html>".encode("utf-8")

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            hits[label] = hits.get(label, 0) + 1
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            pass

    server = TCPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{port}/"


def classify(tool_name: str, arguments: dict, *, in_scope_url: str) -> SimpleNamespace:
    """The example policy this showcase demonstrates:

    - only acquisition.capture_url is admitted at all -- this operator's
      launcher wires no observer, so process_source / compare_captures /
      process_browser_observation are refused as a whole tool class (they
      would fail closed inside the surface anyway; this policy refuses them
      BEFORE the child is even spawned, which is the point of the boundary).
    - a capture_url call is admitted only if its url argument is exactly the
      configured in-scope fixture URL; any other url (e.g. the out-of-scope
      fixture) is refused.
    """

    if tool_name != ACQUISITION_TOOL_CAPTURE_URL:
        return SimpleNamespace(
            disposition="refused",
            tool_class="acquisition-tool",
            reason_code="policy_refused",
            parent_receipt_ref=None,
            additional_attestation_limits=(),
        )

    if arguments.get("url") != in_scope_url:
        return SimpleNamespace(
            disposition="refused",
            tool_class="acquisition-tool",
            reason_code="policy_refused",
            parent_receipt_ref=None,
            additional_attestation_limits=(),
        )

    return SimpleNamespace(
        disposition="admitted",
        tool_class="acquisition-tool",
        reason_code=None,
        parent_receipt_ref=None,
        additional_attestation_limits=(),
    )


def build_config(policy_resolver, identity: SigningIdentity) -> GatewayAdapterConfig:
    sink = RawEnvelopeFileSink(RECEIPTS_DIR)
    return GatewayAdapterConfig(
        binding_registry={"primary": SDK_BINDING_VERSION},
        connector=CONNECTOR,
        identity=identity,
        sink=sink,
        runtime_instance_id="runtime:showcase:counterpedia-acquisition-mcp-live",
        boundary_id="boundary:showcase:counterpedia-acquisition-mcp-live",
        policy_pack_id="policy:showcase:counterpedia-acquisition-mcp-live",
        policy_pack_version="example-0.1",
        policy_resolver=policy_resolver,
    )


async def run_one(*, request_ref: str, tool_name: str, arguments: dict, seq: int, identity: SigningIdentity, in_scope_url: str):
    disposition_ns = classify(tool_name, arguments, in_scope_url=in_scope_url)

    def policy_resolver(_snapshot, _actor):
        return disposition_ns

    config = build_config(policy_resolver, identity)

    digest = sha256_digest(dict(arguments))
    caller = CallerGovernedCallRequest(
        request_ref=request_ref,
        binding_selector=BindingSelectorKey(key="primary"),
        target_server_ref=TargetServerRef(handle=TARGET_HANDLE),
        tool_name=tool_name,
        argument_digest=digest,
        policy_profile_ref="policy-profile:showcase-counterpedia-acquisition-mcp",
    )
    request = GovernedCallRequest.from_caller_request(
        caller, actor_ref=TrustedActorRef(ref="actor:showcase:operator")
    )

    response = await execute_governed_call(request, arguments=arguments, config=config)
    return {
        "seq": seq,
        "request_ref": request_ref,
        "tool_name": tool_name,
        "arguments": arguments,
        "predicted_disposition": disposition_ns.disposition,
        "disposition": response.decision.disposition,
        "outcome": getattr(response.decision, "outcome", None),
        "diagnostic_code": response.diagnostic_code,
        "num_receipts": len(response.receipts),
        "business_result_repr": (
            None if response.business_result is None else repr(response.business_result)[:400]
        ),
        "identity_issuer_id": identity.issuer_id,
    }


async def main():
    if RECEIPTS_DIR.exists():
        shutil.rmtree(RECEIPTS_DIR)
    RECEIPTS_DIR.mkdir(parents=True)

    hits: dict = {}
    in_scope_server, in_scope_url = _make_fixture_server("in-scope", hits)
    out_of_scope_server, out_of_scope_url = _make_fixture_server("out-of-scope", hits)

    identity = SigningIdentity.generate(
        issuer_id="issuer:showcase:counterpedia-acquisition-mcp-live",
        key_id="issuer.showcase.counterpedia-acquisition-mcp-live/key/1",
    )
    (WORKDIR / "trust_bundle.json").write_text(json.dumps(dict(identity.trust_bundle()), indent=2))

    results = []
    try:
        # 1. ADMIT: capture_url against the in-scope fixture.
        results.append(
            await run_one(
                request_ref="req:showcase:1:admit-capture-in-scope",
                tool_name="acquisition.capture_url",
                arguments={"url": in_scope_url},
                seq=1,
                identity=identity,
                in_scope_url=in_scope_url,
            )
        )

        # 2. REFUSE: capture_url against the out-of-scope fixture.
        results.append(
            await run_one(
                request_ref="req:showcase:2:refuse-capture-out-of-scope",
                tool_name="acquisition.capture_url",
                arguments={"url": out_of_scope_url},
                seq=2,
                identity=identity,
                in_scope_url=in_scope_url,
            )
        )

        # 3. REFUSE: process_source -- refused deliberately, both because
        #    this showcase's launcher wires no observer (the surface itself
        #    would fail closed with McpSurfaceError if this tool were ever
        #    actually invoked here) AND to keep this proof decoupled from
        #    counterpedia-authoring's real usage of this exact tool
        #    (ProducerAcquisitionToolClient's producer re-fetch seam) while
        #    that repo's fix/author-acq0-producer-contract-boundary-v0-1 is
        #    in flight. Governing the real process_source call is
        #    CP-DAGR-MCP-ACQ0-BIND, a follow-on once that branch lands --
        #    NOT proven by this script.
        results.append(
            await run_one(
                request_ref="req:showcase:3:refuse-process-source",
                tool_name=ACQUISITION_TOOL_PROCESS_SOURCE,
                arguments={"url": in_scope_url},
                seq=3,
                identity=identity,
                in_scope_url=in_scope_url,
            )
        )

        # 4. REFUSE (fail-closed): tool name not in the connector's own
        #    known_tools allowlist at all.
        results.append(
            await run_one(
                request_ref="req:showcase:4:refuse-unknown-tool",
                tool_name="acquisition.delete_everything",
                arguments={"url": in_scope_url},
                seq=4,
                identity=identity,
                in_scope_url=in_scope_url,
            )
        )
    finally:
        in_scope_server.shutdown()
        out_of_scope_server.shutdown()

    sentinel_report = {
        "in_scope_hits": hits.get("in-scope", 0),
        "out_of_scope_hits": hits.get("out-of-scope", 0),
        "expected_in_scope_hits": 1,
        "expected_out_of_scope_hits": 0,
    }

    receipt_files = sorted(RECEIPTS_DIR.glob("urn_srs_receipt_*.json"))
    receipt_summaries = []
    for p in receipt_files:
        env = json.loads(p.read_text())
        receipt_summaries.append(
            {
                "file": p.name,
                "receipt_kind": env.get("receipt_kind"),
                "disposition": env.get("disposition"),
                "outcome": env.get("outcome"),
                "reason_code": env.get("reason_code"),
                "profile_id": env.get("profile_id"),
                "profile_version": env.get("profile_version"),
            }
        )

    out = {
        "workdir": str(WORKDIR),
        "acquisition_repo": str(ACQUISITION_REPO),
        "acquisition_surface_pinned_commit": ACQUISITION_SURFACE_COMMIT,
        "acquisition_tool_names_pinned": list(ACQUISITION_TOOL_NAMES),
        "target_handle": TARGET_HANDLE,
        "results": results,
        "sentinel_report": sentinel_report,
        "receipt_files": [str(p) for p in receipt_files],
        "receipt_summaries": receipt_summaries,
    }
    (WORKDIR / "live_run_output.json").write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps(out, indent=2, default=str))
    print(f"\nWORKDIR={WORKDIR}", file=sys.stderr)


if __name__ == "__main__":
    anyio.run(main)
