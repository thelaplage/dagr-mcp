"""Deterministic, well-behaved fake MCP stdio child for the stdio connector
test suite (``tests/test_gateway_service_stdio_connector.py`` and
``tests/test_gateway_service_stdio_integration.py``).

Run as a standalone script (``python _stdio_fake_mcp_child.py``), never
imported: :mod:`dagr_mcp_service.connectors.stdio` launches it as a real
subprocess and speaks the standard MCP stdio initialize / ``tools/list`` /
``tools/call`` lifecycle to it, exactly as it would to any real,
independently-authored external MCP server -- this file contains no DAGR
code and imports nothing from this repository, matching the requirement that
the connector governs an external server without importing its
implementation.

Not itself a pytest test module (no ``test_*`` collected here) -- a small,
focused fixture, mirroring
``tests/_gateway_service_remote_fixtures.py``'s real-loopback-server
approach but for a stdio child instead of an HTTP one.
"""

from __future__ import annotations

import os

from fastmcp import FastMCP

server = FastMCP("dagr-stdio-fixture")


def _call_log_path() -> str | None:
    return os.environ.get("DAGR_STDIO_FIXTURE_CALL_LOG")


@server.tool()
def echo(x: str) -> str:
    """Round-trips ``x`` and, if configured, appends one line to a call-log
    file -- used to prove a governed call reaches this child exactly once."""

    log_path = _call_log_path()
    if log_path:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(f"echo:{x}\n")
    return f"echo:{x}"


@server.tool()
def boom(x: str) -> str:
    raise ValueError("boom-internal-detail")


@server.tool()
def observed_cwd() -> str:
    """Returns the working directory this child process was actually launched
    in -- used to prove ``StdioTargetConfig.cwd`` is explicit and honored,
    rather than silently inherited from wherever the parent happened to be."""

    return os.getcwd()


@server.tool()
def observed_env(name: str) -> str | None:
    """Returns the value of one environment variable this child process
    actually received -- used to prove operator-configured ``env`` reaches
    the child, and that it never widens beyond what was configured."""

    return os.environ.get(name)


if __name__ == "__main__":
    server.run(transport="stdio", show_banner=False)
