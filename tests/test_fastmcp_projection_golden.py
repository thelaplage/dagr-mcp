from __future__ import annotations

import hashlib

import pytest

pytest.importorskip("fastmcp")
pytest.importorskip("rfc8785")

import rfc8785
from fastmcp.tools.base import ToolResult

from dagr_mcp.fastmcp_binding import project_fastmcp_tool_result

GOLDEN_PROJECTION_DIGEST = (
    "sha256:26380b315cd335987c15079418c54df086c9a8b3dc7642691ab77b19752a26ce"
)


def test_fastmcp_tool_result_projection_golden() -> None:
    result = ToolResult(
        content=["golden"],
        structured_content={"record_ref": "record:golden", "found": True},
        meta={"fixture": "fastmcp.tool_result.v1"},
    )
    canonical = rfc8785.dumps(project_fastmcp_tool_result(result))
    assert "sha256:" + hashlib.sha256(canonical).hexdigest() == GOLDEN_PROJECTION_DIGEST
