"""Trade admission boundary proof (DAGR-TRADE0).

This module does not implement or change enforcement. It drives the
existing ``dagr_mcp.enforcement_harness.wrap_handler`` -- through the neutral
``dagr_mcp.operator_admission_resolver`` translation only -- over two
distinct tools, sharing one guarded boundary and one fake broker handler,
and records what was actually observed: whether the broker handler ran, and
what signed SRS receipts were emitted.

Tool identities and their admission outcomes are supplied by the caller of
this demo (see ``build_trade_boundary_policies``), exactly as an operator's
own policy authority would supply them in a real deployment. This module
itself carries no finance-, compliance-, MNPI-, issuer-, or
restricted-list-specific vocabulary: it knows two tool names
(``read_market_research``, ``place_trade_order``) as opaque strings and two
neutral outcomes (``admitted``, ``refused``) -- nothing about *why* either
outcome was chosen. The fake broker handler is a demonstration stand-in with
no real brokerage integration; its only observable effect is an in-process
invocation counter and ledger, identical in kind to
``dagr_mcp.first_run_demo.NativeActionSentinel``.
"""

from __future__ import annotations

import datetime
import json
import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .enforcement_harness import GovernedResult, HarnessConfig, HarnessSinks, wrap_handler
from .operator_admission_resolver import resolve_operator_admission
from .sdk_spine import InMemoryEventSink
from .srs_bridge import BridgeConfig, HarnessSRSBridge
from .srs_receipts import RawEnvelopeFileSink, SignedReceiptEmitter, SigningIdentity

PROFILE = "srs.mcp.sdk_enforcement.v0.1"

READ_MARKET_RESEARCH_TOOL = "read_market_research"
PLACE_TRADE_ORDER_TOOL = "place_trade_order"

# Distinctive canary values in the raw arguments. Neither string appears
# anywhere in this module's receipt-adjacent code; their sole purpose is to
# let a test assert their absence from every emitted receipt byte, proving
# raw call content never entered the receipt contract (only its hash does).
READ_MARKET_RESEARCH_ARGUMENTS = {
    "query_ref": "trade-boundary-demo:research-query:1",
    "raw_query_canary": "RAW_RESEARCH_QUERY_TEXT_MUST_NOT_APPEAR_IN_RECEIPT",
}
PLACE_TRADE_ORDER_ARGUMENTS = {
    "order_ref": "trade-boundary-demo:order:1",
    "raw_order_canary": "RAW_ORDER_PAYLOAD_MUST_NOT_APPEAR_IN_RECEIPT",
}

SIDE_EFFECTS_SCHEMA = "dagr.trade_boundary.side_effects.v0.1"
_CAPTURE_KEY_SEED = b"\x02" * 32
_CAPTURE_EPOCH = "2026-01-01T00:00:00Z"

QUICKSTART_COMMANDS = [
    "python -m venv .venv",
    "source .venv/bin/activate  # Windows: .venv\\Scripts\\activate",
    "python -m pip install dagr-mcp",
    "python -m dagr_mcp.trade_boundary_demo --output ./dagr-trade-boundary-output",
]


class BrokerDispatchSentinel:
    """Demonstration stand-in for a real broker/dispatch integration.

    Not a real brokerage integration. Its only observable consequence is an
    append-only ledger and a monotonic invocation counter, read before and
    after each call to prove whether the broker handler ran. The harness
    calls this only on the admitted path -- there is no code in this module
    that can invoke it directly on a refused call.
    """

    def __init__(self) -> None:
        self.invocation_count = 0
        self.ledger: list[dict[str, Any]] = []

    def __call__(self, tool_name: str, arguments: Any, context: Any = None) -> dict[str, Any]:
        self.invocation_count += 1
        entry = {"seq": self.invocation_count, "tool_name": tool_name}
        self.ledger.append(entry)
        return {"broker_dispatch_executed": True, "seq": entry["seq"]}


class _FixedClock:
    """Deterministic ``issued_at`` sequence for capture mode."""

    def __init__(self, start: str = _CAPTURE_EPOCH) -> None:
        self._current = datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))

    def __call__(self) -> str:
        value = self._current.isoformat(timespec="seconds").replace("+00:00", "Z")
        self._current += datetime.timedelta(seconds=1)
        return value


def _capture_receipt_id_factory():
    counters: dict[str, int] = {}

    def factory(receipt_kind: str) -> str:
        counters[receipt_kind] = counters.get(receipt_kind, 0) + 1
        return f"urn:srs:receipt:{receipt_kind}:trade-boundary-capture-{counters[receipt_kind]:04d}"

    return factory


def _build_emitter(directory: Path, *, capture: bool) -> tuple[SigningIdentity, SignedReceiptEmitter]:
    sink = RawEnvelopeFileSink(directory)
    if capture:
        identity = SigningIdentity(
            issuer_id="issuer:dagr:trade-boundary-capture",
            key_id="issuer.dagr.trade-boundary-capture/receipt-signing/fixed",
            private_key=Ed25519PrivateKey.from_private_bytes(_CAPTURE_KEY_SEED),
        )
        emitter = SignedReceiptEmitter(
            identity=identity,
            sink=sink,
            receipt_id_factory=_capture_receipt_id_factory(),
            issued_at_factory=_FixedClock(),
        )
    else:
        identity = SigningIdentity.generate(
            issuer_id="issuer:dagr:trade-boundary",
            key_id="issuer.dagr.trade-boundary/receipt-signing/ephemeral",
        )
        emitter = SignedReceiptEmitter(identity=identity, sink=sink)
    sink.write_trust_bundle(identity.trust_bundle())
    return identity, emitter


def _config() -> HarnessConfig:
    return HarnessConfig(
        harness_version="v0.1",
        module_id="dagr-mcp-trade-boundary",
        module_version="v0.1",
        profile_ref=PROFILE,
        policy_ref="policy:dagr:trade-boundary@v0.1",
    )


def build_trade_boundary_policies():
    """Resolve the two demo tools' policies through the neutral resolver.

    This is the ONLY place in this module where a tool name is paired with
    an admission outcome. Everything downstream of this function (the
    harness, the bridge, the emitter) is exactly the same generic machinery
    ``dagr_mcp.first_run_demo`` already exercises for an unrelated tool.
    """

    return [
        resolve_operator_admission(
            tool_name=READ_MARKET_RESEARCH_TOOL,
            tool_class="read",
            decision="admitted",
        ),
        resolve_operator_admission(
            tool_name=PLACE_TRADE_ORDER_TOOL,
            tool_class="external_action",
            decision="refused",
            reason="policy_refused",
        ),
    ]


@dataclass
class BoundaryObservation:
    name: str
    tool_name: str
    policy_decision: str
    result: GovernedResult
    invocation_count_before: int
    invocation_count_after: int

    @property
    def broker_dispatched(self) -> bool:
        return self.invocation_count_after > self.invocation_count_before


@dataclass
class TradeBoundaryProof:
    admitted: BoundaryObservation
    refused: BoundaryObservation
    directory: Path
    capture_mode: bool
    side_effects_path: Path
    quickstart_path: Path


def _run_call(
    *,
    name: str,
    tool_name: str,
    arguments: Mapping[str, Any],
    handler,
    sentinel: BrokerDispatchSentinel,
    request_ref: str,
) -> BoundaryObservation:
    before = sentinel.invocation_count
    result = handler(
        tool_name,
        arguments,
        {"request_ref": request_ref, "actor_ref": "actor:dagr:trade-boundary"},
    )
    after = sentinel.invocation_count
    return BoundaryObservation(
        name=name,
        tool_name=tool_name,
        policy_decision=result.policy_decision.decision if result.policy_decision else "unknown",
        result=result,
        invocation_count_before=before,
        invocation_count_after=after,
    )


def _receipt_refs(observation: BoundaryObservation) -> dict[str, str | None]:
    result = observation.result
    if result.ok:
        refs = result.receipt_refs
        return {
            "admission_receipt_ref": refs[0] if len(refs) > 0 else None,
            "outcome_receipt_ref": refs[1] if len(refs) > 1 else None,
        }
    context = result.context
    admission_ref = context.admission_receipt_ref if context is not None else None
    return {"admission_receipt_ref": admission_ref, "outcome_receipt_ref": None}


def _scenario_payload(observation: BoundaryObservation) -> dict[str, Any]:
    return {
        "tool_name": observation.tool_name,
        "policy_decision": observation.policy_decision,
        "governed_ok": observation.result.ok,
        "failure_reason": observation.result.failure_reason,
        "broker_dispatched": observation.broker_dispatched,
        "inner_invocation_count_before": observation.invocation_count_before,
        "inner_invocation_count_after": observation.invocation_count_after,
        **_receipt_refs(observation),
    }


def _arcs_verify_command(directory: Path) -> str:
    receipt_glob = shlex.quote(str(directory)) + "/urn_srs_receipt_*.json"
    keyring = str(directory / "issuer-keys.json")
    return (
        "for receipt in "
        f"{receipt_glob}; do "
        "arcs-verify \"$receipt\" "
        f"--keyring {shlex.quote(keyring)} "
        f"--profile {PROFILE}; "
        "done"
    )


def build_side_effects_payload(
    *,
    admitted: BoundaryObservation,
    refused: BoundaryObservation,
    directory: Path,
    capture_mode: bool,
) -> dict[str, Any]:
    return {
        "schema": SIDE_EFFECTS_SCHEMA,
        "boundary_linkage": (
            "operator_admission_decision -> resolve_operator_admission -> "
            "wrap_handler -> broker_dispatch_or_non_dispatch -> receipt_chain"
        ),
        "capture_mode": capture_mode,
        "scenarios": {
            "admitted": _scenario_payload(admitted),
            "refused": _scenario_payload(refused),
        },
        "quickstart_commands": list(QUICKSTART_COMMANDS),
        "arcs_verify_command": _arcs_verify_command(directory),
    }


def run_trade_boundary_proof(output: Path | None = None, *, capture: bool = False) -> TradeBoundaryProof:
    directory = output or Path(tempfile.mkdtemp(prefix="dagr-mcp-trade-boundary-"))
    directory.mkdir(parents=True, exist_ok=True)

    _identity, emitter = _build_emitter(directory, capture=capture)
    bridge = HarnessSRSBridge(
        emitter=emitter,
        config=BridgeConfig(
            runtime_instance_id="runtime:dagr:trade-boundary",
            boundary_id="boundary:dagr:trade-boundary-harness",
            policy_pack_id="policy:dagr:trade-boundary",
            policy_pack_version="v0.1",
        ),
    )

    sentinel = BrokerDispatchSentinel()
    config = _config()
    sinks = HarnessSinks(event=InMemoryEventSink())

    # One shared guarded boundary for BOTH tools -- a single wrap_handler
    # call site resolving each tool's policy from the same map, exactly as a
    # real deployment would front two tools with one admission boundary.
    handler = wrap_handler(
        sentinel,
        config,
        sinks,
        policies=build_trade_boundary_policies(),
        srs_bridge=bridge,
    )

    # Admitted first, then refused, sharing one sentinel: the refused
    # scenario's "unchanged" reading is therefore a before/after delta over
    # an already-nonzero counter, not an absolute-zero check a hardcoded
    # literal could satisfy by coincidence. Same ordering rationale as
    # dagr_mcp.first_run_demo.run_first_run_proof.
    admitted = _run_call(
        name="admitted",
        tool_name=READ_MARKET_RESEARCH_TOOL,
        arguments=READ_MARKET_RESEARCH_ARGUMENTS,
        handler=handler,
        sentinel=sentinel,
        request_ref="call:dagr:trade-boundary:admitted",
    )
    refused = _run_call(
        name="refused",
        tool_name=PLACE_TRADE_ORDER_TOOL,
        arguments=PLACE_TRADE_ORDER_ARGUMENTS,
        handler=handler,
        sentinel=sentinel,
        request_ref="call:dagr:trade-boundary:refused",
    )

    side_effects = build_side_effects_payload(
        admitted=admitted, refused=refused, directory=directory, capture_mode=capture,
    )
    side_effects_path = directory / "side_effects.json"
    side_effects_path.write_text(
        json.dumps(side_effects, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    quickstart_path = directory / "quickstart.txt"
    quickstart_path.write_text("\n".join(QUICKSTART_COMMANDS) + "\n", encoding="utf-8")

    return TradeBoundaryProof(
        admitted=admitted,
        refused=refused,
        directory=directory,
        capture_mode=capture,
        side_effects_path=side_effects_path,
        quickstart_path=quickstart_path,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the DAGR trade admission boundary proof")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--capture", action="store_true")
    args = parser.parse_args(argv)

    proof = run_trade_boundary_proof(args.output, capture=args.capture)
    print(f"Wrote artifacts to {proof.directory}")
    print(json.dumps(json.loads(proof.side_effects_path.read_text()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BoundaryObservation",
    "BrokerDispatchSentinel",
    "PLACE_TRADE_ORDER_ARGUMENTS",
    "PLACE_TRADE_ORDER_TOOL",
    "READ_MARKET_RESEARCH_ARGUMENTS",
    "READ_MARKET_RESEARCH_TOOL",
    "TradeBoundaryProof",
    "build_side_effects_payload",
    "build_trade_boundary_policies",
    "run_trade_boundary_proof",
]
