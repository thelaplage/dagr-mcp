"""Small, explicit FastMCP convenience wrapper.

``quickwrap`` is the zero-config development path for putting the existing DAGR
FastMCP middleware around a server.  It does not mint a second lifecycle or
policy implementation: all enforcement remains in :mod:`dagr_mcp.fastmcp_binding`.

The defaults intentionally use an ephemeral signing identity and the binding's
existing default-admit policy posture.  Production deployments should construct
``DAGRMiddlewareConfig`` and ``SigningIdentity`` explicitly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .fastmcp_binding import DAGRMiddleware, DAGRMiddlewareConfig, ToolClass
from .srs_receipts import RawEnvelopeFileSink, SignedReceiptEmitter, SigningIdentity


def quickwrap(
    server: Any,
    *,
    output: str | Path = ".dagr/receipts",
    runtime_instance_id: str = "runtime:dagr:quickwrap",
    boundary_id: str = "boundary:dagr:fastmcp",
    policy_pack_id: str = "policy:dagr:quickwrap",
    policy_pack_version: str = "v0.1",
    tool_classes: Mapping[str, ToolClass] | None = None,
) -> Any:
    """Install the existing DAGR FastMCP middleware and return ``server``.

    ``quickwrap(server)`` is deliberately a convenience surface, not a new
    authority surface.  Receipts are written beneath ``output`` together with
    the public trust bundle needed to verify them.  The generated signing key is
    process-local and ephemeral.
    """

    sink = RawEnvelopeFileSink(Path(output))
    identity = SigningIdentity.generate(
        issuer_id="issuer:dagr:quickwrap",
        key_id="issuer.dagr.quickwrap/receipt-signing/ephemeral",
    )
    sink.write_trust_bundle(identity.trust_bundle())
    emitter = SignedReceiptEmitter(identity=identity, sink=sink)
    server.add_middleware(
        DAGRMiddleware(
            emitter=emitter,
            config=DAGRMiddlewareConfig(
                runtime_instance_id=runtime_instance_id,
                boundary_id=boundary_id,
                policy_pack_id=policy_pack_id,
                policy_pack_version=policy_pack_version,
                tool_classes=dict(tool_classes or {}),
            ),
        )
    )
    return server


__all__ = ["quickwrap"]
