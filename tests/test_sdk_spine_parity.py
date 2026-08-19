from __future__ import annotations

import dagr_mcp.sdk_spine as mcp_spine
import dagr_sdk.sdk_spine as canonical_spine


def test_mcp_spine_is_exact_projection_of_canonical_sdk_spine() -> None:
    assert mcp_spine.__all__ == canonical_spine.__all__
    for name in canonical_spine.__all__:
        assert getattr(mcp_spine, name) is getattr(canonical_spine, name), name


def test_mcp_spine_declares_canonical_source() -> None:
    assert mcp_spine.CANONICAL_SPINE_MODULE == "dagr_sdk.sdk_spine"
