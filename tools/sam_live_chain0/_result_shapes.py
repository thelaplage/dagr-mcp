"""Shape-tolerant extraction of a find_remote_tools tool list.

alpha.7's Go sam-node returns the tool list as a bare JSON array inside the
CallToolResult's text content and does NOT populate ``structuredContent["tools"]``.
The pinned Python mcp client used elsewhere in the estate can, for other servers,
surface a structured object instead. This helper tolerates every observed shape so
the semantic probe and the governed-call driver never depend on one server's
serialization choice. Kept import-light (stdlib only) so it is unit-testable
without importing the SAM connector stack.
"""
from __future__ import annotations

import json
from typing import Any


def tools_from_result(result: Any) -> list:
    """Return the list of tool rows from a find_remote_tools CallToolResult.

    Accepts, in order: ``structuredContent`` as a list; ``structuredContent`` as
    a dict under ``tools`` or ``result``; else the first text-content block parsed
    as JSON (a bare array, or a dict with a ``tools`` list). Returns ``[]`` when no
    shape matches — callers fail closed on an unexpected count, never on a raise.
    """
    sc = getattr(result, "structuredContent", None)
    if isinstance(sc, list):
        return sc
    if isinstance(sc, dict):
        for key in ("tools", "result"):
            if isinstance(sc.get(key), list):
                return sc[key]
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            continue
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("tools"), list):
            return data["tools"]
    return []
