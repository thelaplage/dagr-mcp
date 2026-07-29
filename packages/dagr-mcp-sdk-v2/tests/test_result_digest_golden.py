"""Golden vectors for the frozen v2 tool-result digest projection.

``tests/golden/result_digest_vectors.json`` is generated (not hand-typed) by a
one-off script that calls ``project_v2_tool_result`` + ``sha256_digest``
directly and writes the result -- see the generation command in
``docs/DAGR_MCP_SDK_V2_BINDING.md``. This test recomputes each case fresh and
asserts byte-for-byte equality against the committed fixture, so any change to
the projection (key set, key order, normalization) fails loudly here first.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp import types as mcp_types

from dagr_mcp_core.srs_receipts import sha256_digest
from dagr_mcp_sdk_v2.result_digest import PROJECTION_KEYS, project_v2_tool_result

GOLDEN = json.loads(
    (Path(__file__).parent / "golden" / "result_digest_vectors.json").read_text()
)


def test_projection_keys_are_frozen():
    assert PROJECTION_KEYS == ("content", "structured_content", "_meta", "is_error", "result_type")


def test_text_ok_matches_golden():
    result = mcp_types.CallToolResult(
        content=[mcp_types.TextContent(type="text", text="hi")],
        structuredContent=None,
        isError=False,
    )
    projection = project_v2_tool_result(result)
    case = GOLDEN["text_ok"]
    assert projection == case["projection"]
    assert sha256_digest(projection) == case["digest"]


def test_text_error_matches_golden():
    result = mcp_types.CallToolResult(
        content=[mcp_types.TextContent(type="text", text="nope")],
        isError=True,
    )
    projection = project_v2_tool_result(result)
    case = GOLDEN["text_error"]
    assert projection == case["projection"]
    assert sha256_digest(projection) == case["digest"]


def test_structured_only_matches_golden():
    result = mcp_types.CallToolResult(
        content=[],
        structuredContent={"ok": True, "count": 3},
        isError=False,
    )
    projection = project_v2_tool_result(result)
    case = GOLDEN["structured_only"]
    assert projection == case["projection"]
    assert sha256_digest(projection) == case["digest"]


def test_result_type_is_stamped_complete_by_default():
    result = mcp_types.CallToolResult(content=[mcp_types.TextContent(type="text", text="x")])
    projection = project_v2_tool_result(result)
    assert projection["result_type"] == "complete"


def test_digest_is_deterministic_across_equivalent_calls():
    a = project_v2_tool_result(mcp_types.CallToolResult(content=[mcp_types.TextContent(type="text", text="x")]))
    b = project_v2_tool_result(mcp_types.CallToolResult(content=[mcp_types.TextContent(type="text", text="x")]))
    assert sha256_digest(a) == sha256_digest(b)
