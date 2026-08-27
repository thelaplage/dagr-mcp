"""Deterministic local MCP market fixture for SAM-LIVE-CHAIN0.

A successful ``settle`` result is a transport/governance fixture fact only.
It is not a financial settlement and carries no external-world authority.
"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("market", host="127.0.0.1", port=7779)


@mcp.tool()
def settle(instrument: str = "DEMO", quantity: int = 1) -> dict:
    """Return a deterministic fixture settlement result."""
    return {
        "fixture": "sam-live-market0",
        "status": "settled",
        "instrument": instrument,
        "quantity": quantity,
        "authority_effect": "none",
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
