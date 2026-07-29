"""Focused input_required fail-closed proof, over the real stateless HTTP app.

Complements the ``input_required`` row in ``test_acceptance_matrix.py`` (which
proves the adapter-level receipt cardinality) with the wire-level proof: the
HTTP response is a genuine JSON-RPC error (never a disguised `200 complete` or
`200 isError` result), and the error carries an explicit, tool-named
diagnostic rather than a generic message.
"""

from __future__ import annotations

from mcp import types as mcp_types

from harness import build_governed_test_app, call_tool


def test_input_required_result_is_a_wire_level_error_not_a_disguised_success(tmp_path):
    async def paused(_args):
        return mcp_types.InputRequiredResult(request_state="opaque-continuation-token")

    dt = build_governed_test_app(tmp_path, tool_bodies={"paused_tool": paused})
    with dt.client() as client:
        resp = call_tool(client, "paused_tool", {})

    body = resp.json()
    assert "error" in body, f"expected a JSON-RPC error, got: {body}"
    assert "result" not in body
    assert "paused_tool" in body["error"]["message"]
    assert "input_required" in body["error"]["message"] or "MRTR" in body["error"]["message"]

    # Admission proceeded (one receipt); no outcome was ever planned for it.
    assert len(dt.admission_receipts()) == 1
    assert dt.admission_receipts()[0]["disposition"] == "admitted"
    assert len(dt.outcome_receipts()) == 0
    assert dt.delegates["paused_tool"].call_count == 1
