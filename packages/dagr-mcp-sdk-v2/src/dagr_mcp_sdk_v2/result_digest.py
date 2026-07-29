"""The frozen `mcp==2.0.0` tool-result digest projection.

Digests exactly the five fields the task requires: ``content``,
``structured_content``, ``_meta``, ``is_error``, ``result_type`` -- the actual
``mcp_types.CallToolResult`` field names (SDK-facing, not the wire aliases).
Uses ``CallToolResult.model_dump(mode="json", by_alias=True)`` so every content
block (``TextContent``, etc.) is fully normalized to plain JSON before
canonicalization -- no transport-local object, Python repr, or memory address
can leak into the digest.

See ``docs/DAGR_MCP_SDK_V2_BINDING.md`` for the frozen definition and golden
vectors (``packages/dagr-mcp-sdk-v2/tests/test_result_digest_golden.py``).
"""

from __future__ import annotations

from typing import Any

import rfc8785
from mcp import types as mcp_types

# The exact, frozen key set and order of the digest projection. Any change here
# is a breaking change to every future result digest and must be documented as
# such (see docs/DAGR_MCP_SDK_V2_BINDING.md).
PROJECTION_KEYS: tuple[str, ...] = (
    "content",
    "structured_content",
    "_meta",
    "is_error",
    "result_type",
)


def project_v2_tool_result(result: mcp_types.CallToolResult) -> dict[str, Any]:
    """Return the frozen five-member projection of a v2 `CallToolResult`.

    Raises if *result* is not RFC 8785 canonicalizable (surfaced by the caller
    as a receipt-content error, same as every other digest in this codebase).
    """

    dumped = result.model_dump(mode="json", by_alias=True, exclude_none=False)
    projection = {
        "content": dumped.get("content", []),
        "structured_content": dumped.get("structuredContent"),
        "_meta": dumped.get("_meta"),
        "is_error": bool(dumped.get("isError", False)),
        "result_type": dumped.get("resultType", "complete"),
    }
    rfc8785.dumps(projection)  # validate canonicalizability eagerly, same failure mode as sha256_digest
    return projection


__all__ = ["PROJECTION_KEYS", "project_v2_tool_result"]
