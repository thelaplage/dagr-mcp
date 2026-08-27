"""Loopback-only derivative of google/sam alpha.7 greeter MCP example."""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("greeter", host="127.0.0.1", port=7778)


@mcp.tool()
def hello(name: str) -> str:
    return f"Hello, {name}!"


@mcp.tool()
def shout(text: str) -> str:
    return f"{text.upper()}!"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
