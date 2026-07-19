"""Sprint A8 — the in-process memory connector (dagr_mcp_service.connectors.memory).

Covers: allowlisted local-target resolution by ``(target_handle, tool_name)``
only; fail-closed refusal (never substitution) for an unknown target handle
or an unknown tool name; no URL/host/port/subprocess/socket surface exists on
the connector at all; no raw-argument retention (the connector never sees
call arguments in the first place).
"""

from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

from dagr_mcp_service.connectors.memory import (
    InMemoryToolConnector,
    MemoryTargetResolutionRefused,
)

ROOT = Path(__file__).resolve().parents[1]


async def _echo(arguments):
    return dict(arguments)


def test_resolve_known_target_and_tool_returns_the_registered_callable() -> None:
    connector = InMemoryToolConnector({"mem:fixture": {"echo": _echo}})

    resolved = connector.resolve("mem:fixture", "echo")

    assert resolved is _echo


def test_resolve_unknown_target_handle_refuses_with_remote_unavailable() -> None:
    connector = InMemoryToolConnector({"mem:fixture": {"echo": _echo}})

    resolved = connector.resolve("mem:does-not-exist", "echo")

    assert isinstance(resolved, MemoryTargetResolutionRefused)
    assert resolved.reason == "remote_unavailable"
    assert resolved.target_handle == "mem:does-not-exist"
    assert resolved.tool_name == "echo"


def test_resolve_unknown_tool_under_known_target_refuses_with_unknown_tool_fail_closed() -> None:
    connector = InMemoryToolConnector({"mem:fixture": {"echo": _echo}})

    resolved = connector.resolve("mem:fixture", "no-such-tool")

    assert isinstance(resolved, MemoryTargetResolutionRefused)
    assert resolved.reason == "unknown_tool_fail_closed"


def test_resolve_never_substitutes_a_different_registered_tool() -> None:
    other_calls: list[str] = []

    async def other(_arguments):
        other_calls.append("called")
        return {}

    connector = InMemoryToolConnector({"mem:fixture": {"echo": _echo, "other": other}})

    resolved = connector.resolve("mem:fixture", "does-not-exist")

    assert isinstance(resolved, MemoryTargetResolutionRefused)
    assert not other_calls


def test_connector_does_not_mutate_the_registry_it_was_constructed_with() -> None:
    targets = {"mem:fixture": {"echo": _echo}}
    connector = InMemoryToolConnector(targets)

    connector.resolve("mem:fixture", "echo")
    targets["mem:fixture"]["mutated"] = _echo  # mutate the caller's own dict

    # The connector took its own copy; the external mutation must not appear.
    resolved = connector.resolve("mem:fixture", "mutated")
    assert isinstance(resolved, MemoryTargetResolutionRefused)


def test_resolve_signature_carries_no_argument_parameter() -> None:
    # The connector must never receive call arguments at all -- only routing
    # facts (target handle, tool name) -- so it structurally cannot retain
    # them.
    signature = inspect.signature(InMemoryToolConnector.resolve)
    assert set(signature.parameters) == {"self", "target_handle", "tool_name"}


def test_no_url_host_port_subprocess_socket_surface_on_the_connector_module() -> None:
    # Checks actual import/usage statements only -- the module's own
    # docstring legitimately *names* these prohibited concepts (to disclaim
    # them), so a raw substring scan of the whole file would false-positive
    # on its own documentation.
    import dagr_mcp_service.connectors.memory as memory_module

    lines = Path(memory_module.__file__).read_text(encoding="utf-8").splitlines()
    code_lines = [
        line
        for line in lines
        if line.strip().startswith(("import ", "from "))
    ]
    forbidden_modules = (
        "socket",
        "subprocess",
        "urllib",
        "httpx",
        "aiohttp",
        "asyncio",
    )
    hits = [
        line
        for line in code_lines
        if any(f" {module}" in f" {line}" or line.strip().startswith(module) for module in forbidden_modules)
    ]
    assert not hits, hits


def test_fresh_import_of_connectors_package_does_not_pull_in_transport_or_storage_libraries() -> None:
    script = (
        "import sys\n"
        "import dagr_mcp_service.connectors\n"
        "import dagr_mcp_service.connectors.memory\n"
        "roots = {m.split('.', 1)[0] for m in sys.modules}\n"
        "forbidden = {\n"
        "    'mcp', 'fastmcp', 'uvicorn', 'starlette', 'aiohttp', 'httpx',\n"
        "    'fastapi', 'flask', 'sqlalchemy', 'psycopg2', 'pika', 'kombu', 'celery',\n"
        "    'socket',\n"
        "}\n"
        "hit = roots & forbidden\n"
        "assert not hit, hit\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
