from __future__ import annotations

import dagr_mcp
from dagr_mcp.fastmcp_binding import DAGRMiddleware, DAGRMiddlewareConfig, ToolClass
from dagr_mcp.srs_receipts import RawEnvelopeFileSink, SignedReceiptEmitter, SigningIdentity


def test_explicit_fastmcp_surface_is_discoverable_from_package_root() -> None:
    expected = {
        "DAGRMiddleware": DAGRMiddleware,
        "DAGRMiddlewareConfig": DAGRMiddlewareConfig,
        "RawEnvelopeFileSink": RawEnvelopeFileSink,
        "SignedReceiptEmitter": SignedReceiptEmitter,
        "SigningIdentity": SigningIdentity,
        "ToolClass": ToolClass,
    }

    assert set(dagr_mcp.__all__) == {*expected, "quickwrap"}
    for name, canonical in expected.items():
        assert getattr(dagr_mcp, name) is canonical, name
    assert callable(dagr_mcp.quickwrap)
