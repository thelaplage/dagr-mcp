"""Compatibility projection of the canonical DAGR SDK spine.

The implementation authority for these wire shapes and sink contracts is
``dagr_sdk.sdk_spine``.  This module exists only so existing ``dagr_mcp`` imports
remain source-compatible; it must not grow an independent implementation.
"""

from __future__ import annotations

from dagr_sdk import sdk_spine as _canonical

CANONICAL_SPINE_MODULE = "dagr_sdk.sdk_spine"

__all__ = list(_canonical.__all__)
globals().update({name: getattr(_canonical, name) for name in __all__})
