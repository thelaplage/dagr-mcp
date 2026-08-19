# Public FastMCP surface

The root `dagr_mcp` package intentionally exposes both the zero-config convenience
path and the explicit construction primitives needed to leave that convenience
path without discovering private module layout.

```python
from dagr_mcp import (
    DAGRMiddleware,
    DAGRMiddlewareConfig,
    RawEnvelopeFileSink,
    SignedReceiptEmitter,
    SigningIdentity,
    ToolClass,
    quickwrap,
)
```

`quickwrap` remains the local/evaluation convenience. The explicit primitives are
the public construction surface for operator-managed signing identity, policy
resolution, boundary identifiers, tool classification, and sink placement.

This surface does not make DAGR MCP a policy authority, verifier, or key-custody
system. Applications remain responsible for operator policy and production key
custody; ARCS Verify remains the independent verifier.
