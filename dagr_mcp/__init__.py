"""Public-canonical MCP admission runtime."""

# DAGR-MCP-IMPORT-ISOLATION-FIX0: defer ONLY the FastMCP-bearing public surface.
#
# The regression: LEGIBILITY1 (#50, e4a4f92) made dagr_mcp/__init__ EAGERLY
# `from .fastmcp_binding import ...` (and quickwrap, whose module imports
# fastmcp_binding). fastmcp_binding imports fastmcp, so importing ANY core
# dagr_mcp.* submodule (sdk_spine, srs_receipts — both themselves fastmcp-clean)
# transitively pulled the OPTIONAL FastMCP framework into core adapter/binding
# import paths, violating the optional-transport isolation the negative-space
# tests guard (see also the core-only CI lane, which asserts fastmcp is NOT
# installed). LEGIBILITY1 intended to expose the construction NAMES, not to force
# fastmcp into every core import → regression, not intent.
#
# Scope of the repair is EXACTLY the contamination root:
#   * FastMCP-bearing names (DAGRMiddleware / DAGRMiddlewareConfig / ToolClass,
#     from .fastmcp_binding) and `quickwrap` (its module imports fastmcp_binding)
#     become LAZY — reachable identically as dagr_mcp.DAGRMiddleware /
#     dagr_mcp.quickwrap etc., resolved on first access and cached, so FastMCP
#     loads only at the explicit construction-surface access point.
#   * srs_receipts is FastMCP-CLEAN (stdlib + crypto/rfc8785 + constitutional
#     consumer); it is kept EAGER so the pre-existing observable behavior is
#     preserved — `import dagr_mcp` immediately provides the dagr_mcp.srs_receipts
#     submodule and its three exported classes, unchanged.
#
# No SDK / gateway / FastMCP-construction semantics change; no new deps (only
# stdlib importlib/sys/types). The public surface (names + __all__) is identical.
#
# A module __class__ swap (not a bare PEP 562 __getattr__) is required because
# the re-exported FUNCTION `quickwrap` shares its name with the `quickwrap`
# SUBMODULE: importing that submodule (e.g. pkgutil.walk_packages, as the
# behavioral-freeze test does) binds the module object over the function, and a
# miss-only __getattr__ never fires once the attribute exists. __getattribute__
# intercepts that single colliding name so the public function always wins; the
# other lazy names have no collision and are served by __getattr__ with caching.

import importlib as _importlib
import sys as _sys
import types as _types

# FastMCP-clean receipt exports: keep EAGER (old behavior preserved).
from .srs_receipts import RawEnvelopeFileSink, SignedReceiptEmitter, SigningIdentity

__all__ = [
    "DAGRMiddleware",
    "DAGRMiddlewareConfig",
    "RawEnvelopeFileSink",
    "SignedReceiptEmitter",
    "SigningIdentity",
    "ToolClass",
    "quickwrap",
]

# FastMCP-bearing public names only -> the (relative) submodule they come from.
_LAZY_EXPORTS = {
    "DAGRMiddleware": ".fastmcp_binding",
    "DAGRMiddlewareConfig": ".fastmcp_binding",
    "ToolClass": ".fastmcp_binding",
    "quickwrap": ".quickwrap",
}


class _LazyExportModule(_types.ModuleType):
    def __getattribute__(self, name):
        if name == "quickwrap":
            # The FUNCTION must win over the same-named submodule that a submodule
            # import may have bound into __dict__. Resolve (once) and cache.
            d = _types.ModuleType.__getattribute__(self, "__dict__")
            fn = d.get("_quickwrap_fn")
            if fn is None:
                fn = getattr(_importlib.import_module(".quickwrap", __name__), "quickwrap")
                d["_quickwrap_fn"] = fn
            return fn
        return _types.ModuleType.__getattribute__(self, name)

    def __getattr__(self, name):
        source = _LAZY_EXPORTS.get(name)
        if source is None:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        value = getattr(_importlib.import_module(source, __name__), name)
        setattr(self, name, value)  # cache: subsequent access is a normal lookup
        return value

    def __dir__(self):
        keys = _types.ModuleType.__getattribute__(self, "__dict__")
        return sorted(set(keys) | set(__all__))


_sys.modules[__name__].__class__ = _LazyExportModule
