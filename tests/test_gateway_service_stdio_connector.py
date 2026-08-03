"""The client-side stdio child-process connector
(``dagr_mcp_service.connectors.stdio``).

Unit-level coverage of the connector module itself, driven against two real
subprocesses: a well-behaved FastMCP stdio server
(``tests/_stdio_fake_mcp_child.py``) and a hand-rolled, deliberately
misbehaving raw JSON-RPC child (``tests/_stdio_raw_fake_mcp_child.py``).
Covers: the frozen A8 connector seam; operator-only target configuration and
the command-allowlist/absolute-path boundary; no caller-suppliable command,
argument, or environment variable; fail-closed unknown-target/unknown-tool
resolution with zero process I/O; tool discovery; argument forwarding;
environment scoping; honest failure classification (spawn-unavailable vs.
timeout vs. child-exit-mid-call vs. malformed response vs. protocol-version
mismatch vs. cancellation); process cleanup and orphan prevention; and
import purity. See ``docs/GATEWAY_SERVICE_ADAPTER_SCOPE.md`` §7, §12, §13.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")
pytest.importorskip("fastmcp")

from dagr_mcp_service.connectors.stdio import (
    StdioTargetConfig,
    StdioTargetResolutionRefused,
    StdioToolConnector,
    _flatten_exception_group,
    _translate_stdio_failure,
    discover_tools,
)

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
FASTMCP_FIXTURE = str(ROOT / "tests" / "_stdio_fake_mcp_child.py")
RAW_FIXTURE = str(ROOT / "tests" / "_stdio_raw_fake_mcp_child.py")


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - would mean it's alive but not ours
        return True
    return True


async def _wait_until_dead(pid: int, *, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_is_alive(pid):
            return True
        await asyncio.sleep(0.05)
    return not _process_is_alive(pid)


# --------------------------------------------------------------------------- #
# StdioTargetConfig -- construction-time validation (the allowlist boundary)  #
# --------------------------------------------------------------------------- #


def test_absolute_executable_path_is_accepted() -> None:
    StdioTargetConfig(
        handle="local:test", command=(PY, FASTMCP_FIXTURE), known_tools=frozenset({"echo"})
    )


@pytest.mark.parametrize("command", [("relative-binary",), ("./relative", "arg"), ("",)])
def test_non_absolute_executable_path_is_rejected(command: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        StdioTargetConfig(handle="local:test", command=command, known_tools=frozenset())


def test_empty_command_is_rejected() -> None:
    with pytest.raises(ValueError):
        StdioTargetConfig(handle="local:test", command=(), known_tools=frozenset())


def test_command_with_empty_argument_is_rejected() -> None:
    with pytest.raises(ValueError):
        StdioTargetConfig(handle="local:test", command=(PY, ""), known_tools=frozenset())


def test_non_positive_timeout_is_rejected() -> None:
    with pytest.raises(ValueError):
        StdioTargetConfig(
            handle="local:test",
            command=(PY, FASTMCP_FIXTURE),
            known_tools=frozenset(),
            timeout_seconds=0,
        )
    with pytest.raises(ValueError):
        StdioTargetConfig(
            handle="local:test",
            command=(PY, FASTMCP_FIXTURE),
            known_tools=frozenset(),
            timeout_seconds=-5,
        )


def test_known_tools_must_be_a_frozenset() -> None:
    with pytest.raises(TypeError):
        StdioTargetConfig(
            handle="local:test",
            command=(PY, FASTMCP_FIXTURE),
            known_tools={"echo"},  # a plain set, not a frozenset
        )


def test_env_values_must_be_strings() -> None:
    with pytest.raises(ValueError):
        StdioTargetConfig(
            handle="local:test",
            command=(PY, FASTMCP_FIXTURE),
            known_tools=frozenset(),
            env={"KEY": 123},  # type: ignore[dict-item]
        )


def test_empty_handle_is_rejected() -> None:
    with pytest.raises(ValueError):
        StdioTargetConfig(handle="  ", command=(PY, FASTMCP_FIXTURE), known_tools=frozenset())


def test_invalid_command_opens_no_process(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("no process may be spawned for a config that fails to construct")

    monkeypatch.setattr("anyio.open_process", _forbidden)
    with pytest.raises(ValueError):
        StdioTargetConfig(handle="local:evil", command=("relative",), known_tools=frozenset())


# --------------------------------------------------------------------------- #
# StdioToolConnector construction and resolve() -- no I/O                    #
# --------------------------------------------------------------------------- #


def test_connector_rejects_a_registry_key_that_does_not_match_the_configs_own_handle() -> None:
    target = StdioTargetConfig(
        handle="local:a", command=(PY, FASTMCP_FIXTURE), known_tools=frozenset({"echo"})
    )
    with pytest.raises(ValueError):
        StdioToolConnector({"local:other-key": target})


def test_connector_does_not_mutate_the_registry_it_was_constructed_with() -> None:
    target = StdioTargetConfig(
        handle="local:a", command=(PY, FASTMCP_FIXTURE), known_tools=frozenset({"echo"})
    )
    targets = {"local:a": target}
    connector = StdioToolConnector(targets)

    targets["local:new"] = StdioTargetConfig(
        handle="local:new", command=(PY, FASTMCP_FIXTURE), known_tools=frozenset({"echo"})
    )

    resolved = connector.resolve("local:new", "echo")
    assert isinstance(resolved, StdioTargetResolutionRefused)


def test_resolve_signature_matches_the_frozen_a8_connector_seam() -> None:
    signature = inspect.signature(StdioToolConnector.resolve)
    assert set(signature.parameters) == {"self", "target_handle", "tool_name"}


def test_resolve_unknown_target_handle_refuses_with_remote_unavailable() -> None:
    connector = StdioToolConnector(
        {
            "local:a": StdioTargetConfig(
                handle="local:a", command=(PY, FASTMCP_FIXTURE), known_tools=frozenset({"echo"})
            )
        }
    )

    resolved = connector.resolve("local:does-not-exist", "echo")

    assert isinstance(resolved, StdioTargetResolutionRefused)
    assert resolved.reason == "remote_unavailable"
    assert resolved.target_handle == "local:does-not-exist"
    assert resolved.tool_name == "echo"


def test_resolve_unknown_tool_under_known_target_refuses_with_unknown_tool_fail_closed() -> None:
    connector = StdioToolConnector(
        {
            "local:a": StdioTargetConfig(
                handle="local:a", command=(PY, FASTMCP_FIXTURE), known_tools=frozenset({"echo"})
            )
        }
    )

    resolved = connector.resolve("local:a", "no-such-tool")

    assert isinstance(resolved, StdioTargetResolutionRefused)
    assert resolved.reason == "unknown_tool_fail_closed"


def test_resolve_never_spawns_a_process(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = StdioToolConnector(
        {
            "local:a": StdioTargetConfig(
                handle="local:a", command=(PY, FASTMCP_FIXTURE), known_tools=frozenset({"echo"})
            )
        }
    )

    async def _forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("resolve() itself must never spawn a process")

    monkeypatch.setattr("anyio.open_process", _forbidden)

    resolved_known = connector.resolve("local:a", "echo")
    assert callable(resolved_known)
    resolved_unknown_target = connector.resolve("local:missing", "echo")
    assert isinstance(resolved_unknown_target, StdioTargetResolutionRefused)
    resolved_unknown_tool = connector.resolve("local:a", "missing-tool")
    assert isinstance(resolved_unknown_tool, StdioTargetResolutionRefused)


def test_resolved_handler_signature_carries_only_arguments() -> None:
    connector = StdioToolConnector(
        {
            "local:a": StdioTargetConfig(
                handle="local:a", command=(PY, FASTMCP_FIXTURE), known_tools=frozenset({"echo"})
            )
        }
    )
    handler = connector.resolve("local:a", "echo")
    signature = inspect.signature(handler)
    assert list(signature.parameters) == ["call_arguments"]


# --------------------------------------------------------------------------- #
# Real child-process calls -- result, tool-level error, argument forwarding   #
# --------------------------------------------------------------------------- #


async def test_admitted_result_round_trips_over_a_real_child_process() -> None:
    connector = StdioToolConnector(
        {
            "local:a": StdioTargetConfig(
                handle="local:a",
                command=(PY, FASTMCP_FIXTURE),
                known_tools=frozenset({"echo"}),
                timeout_seconds=10.0,
            )
        }
    )
    handler = connector.resolve("local:a", "echo")

    result = await handler({"x": "hello"})

    assert result.isError is False
    assert result.content[0].text == "echo:hello"


async def test_tool_level_error_is_returned_not_raised() -> None:
    connector = StdioToolConnector(
        {
            "local:a": StdioTargetConfig(
                handle="local:a",
                command=(PY, FASTMCP_FIXTURE),
                known_tools=frozenset({"boom"}),
                timeout_seconds=10.0,
            )
        }
    )
    handler = connector.resolve("local:a", "boom")

    result = await handler({"x": "hello"})

    assert result.isError is True
    assert "boom-internal-detail" in result.content[0].text


async def test_argument_values_forwarded_to_the_child_are_byte_exact(tmp_path: Path) -> None:
    connector = StdioToolConnector(
        {
            "local:a": StdioTargetConfig(
                handle="local:a",
                command=(PY, FASTMCP_FIXTURE),
                known_tools=frozenset({"echo"}),
                timeout_seconds=10.0,
            )
        }
    )
    handler = connector.resolve("local:a", "echo")

    distinctive = "forward-me-exactly-éè☃"
    result = await handler({"x": distinctive})

    assert result.content[0].text == f"echo:{distinctive}"


async def test_call_reaches_the_child_exactly_once(tmp_path: Path) -> None:
    log_path = tmp_path / "call-log.txt"
    connector = StdioToolConnector(
        {
            "local:a": StdioTargetConfig(
                handle="local:a",
                command=(PY, FASTMCP_FIXTURE),
                known_tools=frozenset({"echo"}),
                env={"DAGR_STDIO_FIXTURE_CALL_LOG": str(log_path)},
                timeout_seconds=10.0,
            )
        }
    )
    handler = connector.resolve("local:a", "echo")

    await handler({"x": "once"})

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert lines == ["echo:once"]


# --------------------------------------------------------------------------- #
# Environment scoping                                                        #
# --------------------------------------------------------------------------- #


async def test_operator_declared_env_reaches_the_child() -> None:
    connector = StdioToolConnector(
        {
            "local:a": StdioTargetConfig(
                handle="local:a",
                command=(PY, FASTMCP_FIXTURE),
                known_tools=frozenset({"observed_env"}),
                env={"DAGR_STDIO_FIXTURE_SECRET": "sk-test-proof-value"},
                timeout_seconds=10.0,
            )
        }
    )
    handler = connector.resolve("local:a", "observed_env")

    result = await handler({"name": "DAGR_STDIO_FIXTURE_SECRET"})

    assert "sk-test-proof-value" in result.content[0].text


async def test_unrelated_parent_environment_variable_does_not_reach_the_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DAGR_STDIO_UNRELATED_PARENT_SECRET", "must-not-leak")

    connector = StdioToolConnector(
        {
            "local:a": StdioTargetConfig(
                handle="local:a",
                command=(PY, FASTMCP_FIXTURE),
                known_tools=frozenset({"observed_env"}),
                timeout_seconds=10.0,
            )
        }
    )
    handler = connector.resolve("local:a", "observed_env")

    result = await handler({"name": "DAGR_STDIO_UNRELATED_PARENT_SECRET"})

    # The child never received it: this module merges the operator's
    # declared ``env`` onto the SDK's own safe default subset, never the
    # DAGR process's full os.environ. A missing env var renders as no text
    # content at all (the tool returned None), which itself is proof enough,
    # but the substring check stays in place in case that rendering changes.
    rendered = result.content[0].text if result.content else ""
    assert "must-not-leak" not in (rendered or "")


# --------------------------------------------------------------------------- #
# Tool discovery                                                             #
# --------------------------------------------------------------------------- #


async def test_discover_tools_returns_the_childs_declared_tool_names() -> None:
    names = await discover_tools([PY, FASTMCP_FIXTURE])

    assert set(names) == {"echo", "boom", "observed_cwd", "observed_env"}


async def test_discover_tools_opens_and_closes_its_own_process(tmp_path: Path) -> None:
    pid_file = tmp_path / "discover.pid"
    names = await discover_tools([PY, RAW_FIXTURE, "normal", str(pid_file)])

    assert names == ("raw-echo",)
    pid = int(pid_file.read_text(encoding="utf-8"))
    assert await _wait_until_dead(pid)


# --------------------------------------------------------------------------- #
# Failure-cause translation -- unit level, no process                        #
# --------------------------------------------------------------------------- #


def test_translate_stdio_failure_prefers_oserror_over_generic() -> None:
    translated = _translate_stdio_failure(
        BaseExceptionGroup("eg", [FileNotFoundError("no such file")])
    )
    assert isinstance(translated, ConnectionError)


def test_translate_stdio_failure_maps_mcp_timeout_error_code() -> None:
    from mcp.shared.exceptions import McpError
    from mcp.types import ErrorData

    timeout_error = McpError(ErrorData(code=408, message="Timed out"))
    translated = _translate_stdio_failure(BaseExceptionGroup("eg", [timeout_error]))
    assert isinstance(translated, TimeoutError)


def test_translate_stdio_failure_maps_plain_timeout_error() -> None:
    translated = _translate_stdio_failure(BaseExceptionGroup("eg", [TimeoutError("slow")]))
    assert isinstance(translated, TimeoutError)


def test_translate_stdio_failure_falls_back_to_generic_runtime_error() -> None:
    translated = _translate_stdio_failure(BaseExceptionGroup("eg", [ValueError("odd")]))
    assert isinstance(translated, RuntimeError)
    assert not isinstance(translated, ConnectionError | TimeoutError)


def test_translate_stdio_failure_preserves_cancelled_error_unwrapped() -> None:
    cancelled = asyncio.CancelledError()
    translated = _translate_stdio_failure(BaseExceptionGroup("eg", [cancelled]))
    assert translated is cancelled


def test_flatten_exception_group_handles_nested_groups() -> None:
    leaf = ValueError("deep")
    nested = BaseExceptionGroup("inner", [leaf])
    outer = BaseExceptionGroup("outer", [nested])
    assert _flatten_exception_group(outer) == [leaf]


def test_translated_exceptions_never_embed_the_original_message() -> None:
    original = FileNotFoundError("no such file or directory: /super/secret/path/binary")
    translated = _translate_stdio_failure(BaseExceptionGroup("eg", [original]))
    assert "/super/secret/path/binary" not in str(translated)


# --------------------------------------------------------------------------- #
# Real deterministic failure postures -- spawn failure, timeout, child exit, #
# malformed response, protocol-version mismatch, cancellation                #
# --------------------------------------------------------------------------- #


async def test_spawn_failure_raises_connection_error() -> None:
    connector = StdioToolConnector(
        {
            "local:missing": StdioTargetConfig(
                handle="local:missing",
                command=("/nonexistent/absolute/path/to/a/binary",),
                known_tools=frozenset({"echo"}),
                timeout_seconds=5.0,
            )
        }
    )
    handler = connector.resolve("local:missing", "echo")

    with pytest.raises(ConnectionError) as excinfo:
        await handler({"x": "hi"})

    assert "/nonexistent/absolute/path/to/a/binary" not in str(excinfo.value)


async def test_timeout_raises_builtin_timeout_error() -> None:
    connector = StdioToolConnector(
        {
            "raw:hang": StdioTargetConfig(
                handle="raw:hang",
                command=(PY, RAW_FIXTURE, "hang_on_call"),
                known_tools=frozenset({"raw-echo"}),
                timeout_seconds=1.5,
            )
        }
    )
    handler = connector.resolve("raw:hang", "raw-echo")

    with pytest.raises(TimeoutError):
        await handler({"x": "hi"})


async def test_child_exit_mid_call_raises_generic_runtime_error_not_connection_or_timeout() -> None:
    connector = StdioToolConnector(
        {
            "raw:crash": StdioTargetConfig(
                handle="raw:crash",
                command=(PY, RAW_FIXTURE, "crash_after_accept"),
                known_tools=frozenset({"raw-echo"}),
                timeout_seconds=5.0,
            )
        }
    )
    handler = connector.resolve("raw:crash", "raw-echo")

    with pytest.raises(RuntimeError) as excinfo:
        await handler({"x": "hi"})

    assert not isinstance(excinfo.value, ConnectionError | TimeoutError)


async def test_malformed_response_never_returns_a_result_and_stays_bounded() -> None:
    connector = StdioToolConnector(
        {
            "raw:malformed": StdioTargetConfig(
                handle="raw:malformed",
                command=(PY, RAW_FIXTURE, "malformed_call_response"),
                known_tools=frozenset({"raw-echo"}),
                timeout_seconds=1.5,
            )
        }
    )
    handler = connector.resolve("raw:malformed", "raw-echo")

    start = time.monotonic()
    with pytest.raises(Exception) as excinfo:
        await handler({"x": "hi"})
    elapsed = time.monotonic() - start

    # A malformed line is never silently treated as a valid result, and the
    # call never hangs indefinitely -- it fails within a small bounded
    # multiple of the configured timeout (the SDK's own graceful-then-forced
    # process teardown adds a little beyond the raw timeout).
    assert elapsed < 10.0
    assert not isinstance(excinfo.value, asyncio.CancelledError)


async def test_bad_protocol_version_raises_generic_runtime_error() -> None:
    connector = StdioToolConnector(
        {
            "raw:badversion": StdioTargetConfig(
                handle="raw:badversion",
                command=(PY, RAW_FIXTURE, "bad_protocol_version"),
                known_tools=frozenset({"raw-echo"}),
                timeout_seconds=5.0,
            )
        }
    )
    handler = connector.resolve("raw:badversion", "raw-echo")

    with pytest.raises(RuntimeError) as excinfo:
        await handler({"x": "hi"})

    assert not isinstance(excinfo.value, ConnectionError | TimeoutError)


async def test_cancellation_propagates_cleanly_not_swallowed_or_wrapped() -> None:
    connector = StdioToolConnector(
        {
            "raw:hang": StdioTargetConfig(
                handle="raw:hang",
                command=(PY, RAW_FIXTURE, "hang_on_call"),
                known_tools=frozenset({"raw-echo"}),
                timeout_seconds=30.0,
            )
        }
    )
    handler = connector.resolve("raw:hang", "raw-echo")

    task = asyncio.ensure_future(handler({"x": "hi"}))
    await asyncio.sleep(0.5)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


# --------------------------------------------------------------------------- #
# Process cleanup and orphan prevention                                      #
# --------------------------------------------------------------------------- #


async def test_no_orphan_process_remains_after_a_normal_call(tmp_path: Path) -> None:
    pid_file = tmp_path / "normal.pid"
    connector = StdioToolConnector(
        {
            "raw:normal": StdioTargetConfig(
                handle="raw:normal",
                command=(PY, RAW_FIXTURE, "normal", str(pid_file)),
                known_tools=frozenset({"raw-echo"}),
                timeout_seconds=10.0,
            )
        }
    )
    handler = connector.resolve("raw:normal", "raw-echo")

    await handler({"x": "hi"})

    pid = int(pid_file.read_text(encoding="utf-8"))
    assert await _wait_until_dead(pid)


async def test_no_orphan_process_remains_after_a_timeout(tmp_path: Path) -> None:
    pid_file = tmp_path / "hang.pid"
    connector = StdioToolConnector(
        {
            "raw:hang": StdioTargetConfig(
                handle="raw:hang",
                command=(PY, RAW_FIXTURE, "hang_on_call", str(pid_file)),
                known_tools=frozenset({"raw-echo"}),
                timeout_seconds=1.5,
            )
        }
    )
    handler = connector.resolve("raw:hang", "raw-echo")

    with pytest.raises(TimeoutError):
        await handler({"x": "hi"})

    pid = int(pid_file.read_text(encoding="utf-8"))
    assert await _wait_until_dead(pid, timeout=8.0)


async def test_no_orphan_process_remains_after_cancellation(tmp_path: Path) -> None:
    pid_file = tmp_path / "cancel.pid"
    connector = StdioToolConnector(
        {
            "raw:hang": StdioTargetConfig(
                handle="raw:hang",
                command=(PY, RAW_FIXTURE, "hang_on_call", str(pid_file)),
                known_tools=frozenset({"raw-echo"}),
                timeout_seconds=30.0,
            )
        }
    )
    handler = connector.resolve("raw:hang", "raw-echo")

    task = asyncio.ensure_future(handler({"x": "hi"}))
    while not pid_file.exists():
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    pid = int(pid_file.read_text(encoding="utf-8"))
    assert await _wait_until_dead(pid, timeout=8.0)


# --------------------------------------------------------------------------- #
# Concurrency isolation                                                      #
# --------------------------------------------------------------------------- #


async def test_concurrent_calls_do_not_mix_arguments_or_results(tmp_path: Path) -> None:
    connector = StdioToolConnector(
        {
            "local:a": StdioTargetConfig(
                handle="local:a",
                command=(PY, FASTMCP_FIXTURE),
                known_tools=frozenset({"echo"}),
                timeout_seconds=10.0,
            ),
            "local:b": StdioTargetConfig(
                handle="local:b",
                command=(PY, FASTMCP_FIXTURE),
                known_tools=frozenset({"echo"}),
                timeout_seconds=10.0,
            ),
        }
    )

    echo_a = connector.resolve("local:a", "echo")
    echo_b = connector.resolve("local:b", "echo")

    results = await asyncio.gather(echo_a({"x": "from-a"}), echo_b({"x": "from-b"}))

    assert results[0].content[0].text == "echo:from-a"
    assert results[1].content[0].text == "echo:from-b"


# --------------------------------------------------------------------------- #
# Import purity and no-forbidden-surface checks                              #
# --------------------------------------------------------------------------- #


def test_importing_the_connector_package_does_not_eagerly_import_the_stdio_sdk_or_anyio() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys\n"
                "import dagr_mcp_service\n"
                "import dagr_mcp_service.connectors\n"
                "assert 'anyio' not in sys.modules, 'anyio imported at connectors package import'\n"
                "assert 'mcp.client.stdio' not in sys.modules, "
                "'mcp.client.stdio imported at connectors package import'\n"
                "print('OK')\n"
            ),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "OK" in completed.stdout


def test_importing_the_stdio_module_itself_does_not_eagerly_import_the_process_stack() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys\n"
                "from dagr_mcp_service.connectors import stdio\n"
                "assert 'anyio' not in sys.modules, 'anyio imported at stdio module import'\n"
                "assert 'mcp.client.stdio' not in sys.modules, "
                "'mcp.client.stdio imported at stdio module import'\n"
                "print('OK')\n"
            ),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "OK" in completed.stdout


def test_no_websocket_sse_http_or_generic_transport_surface_on_the_module() -> None:
    import dagr_mcp_service.connectors.stdio as stdio_module

    lines = Path(stdio_module.__file__).read_text(encoding="utf-8").splitlines()
    code_lines = [
        line
        for line in lines
        if not line.strip().startswith("#") and '"""' not in line and "'''" not in line
    ]
    code_text = "\n".join(code_lines)

    for forbidden in ("httpx", "websocket", "sse_client", "streamable_http", "urlsplit", "socket."):
        assert forbidden not in code_text, f"unexpected transport surface: {forbidden!r}"


def test_no_shell_interpretation_surface_on_the_module() -> None:
    import dagr_mcp_service.connectors.stdio as stdio_module

    source = Path(stdio_module.__file__).read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "os.system(" not in source


def test_stdio_connector_defines_no_bind_trusted_context_hook() -> None:
    # A stdio target's trusted-context source is fixed at config-construction
    # time (subprocess env / launch args); there is no live, per-call wire
    # location to inject a caller-specific credential into, so this
    # connector must not define the optional A9 hook
    # dagr_mcp_service.adapter.execute_governed_call probes for via
    # getattr(connector, "bind_trusted_context", None).
    assert not hasattr(StdioToolConnector, "bind_trusted_context")


# --------------------------------------------------------------------------- #
# Post-forward phase gate -- ConnectionError ("nothing ran") is reachable     #
# only before the tools/call could have been written to the child's stdin     #
# --------------------------------------------------------------------------- #


def test_pre_forward_oserror_is_a_connection_error() -> None:
    # The pre-forward phase is the *only* phase in which this module is
    # allowed to make the narrow "no execution happened" claim the A8 adapter
    # reads as remote_unavailable.
    translated = _translate_stdio_failure(
        BaseExceptionGroup("eg", [FileNotFoundError("no such file")]), post_forward=False
    )
    assert isinstance(translated, ConnectionError)


def test_post_forward_oserror_is_never_a_connection_error() -> None:
    # Same OSError, after the session was handed to its caller: a tools/call
    # may already be on the wire and the child may already have performed the
    # side effect, so "unavailable"/"nothing ran" is no longer grounded. It
    # must degrade to the generic, honest "not successfully observed" bucket.
    translated = _translate_stdio_failure(
        BaseExceptionGroup("eg", [FileNotFoundError("no such file")]), post_forward=True
    )
    assert isinstance(translated, RuntimeError)
    assert not isinstance(translated, ConnectionError | TimeoutError)


def test_post_forward_gate_never_suppresses_cancellation_or_timeout() -> None:
    # The gate is one-directional: it may only move a classification *away*
    # from claiming non-execution. Cancellation and timeout -- neither of
    # which claims non-execution -- are unaffected by it.
    cancelled = asyncio.CancelledError()
    assert _translate_stdio_failure(BaseExceptionGroup("eg", [cancelled]), post_forward=True) is (
        cancelled
    )
    assert isinstance(
        _translate_stdio_failure(BaseExceptionGroup("eg", [TimeoutError("slow")]), post_forward=True),
        TimeoutError,
    )


def test_post_forward_defaults_to_false_so_the_gate_is_explicit() -> None:
    # The permissive value is the default only because every *pre*-forward
    # call site is the one that needs it; the single post-forward call site
    # in _stdio_session passes the flag explicitly.
    import inspect as _inspect

    signature = _inspect.signature(_translate_stdio_failure)
    assert signature.parameters["post_forward"].default is False
    assert signature.parameters["post_forward"].kind is _inspect.Parameter.KEYWORD_ONLY


@pytest.mark.parametrize(
    "mode", ["side_effect_then_hang", "side_effect_then_crash", "side_effect_then_close"]
)
async def test_a_real_side_effect_that_is_never_observed_is_not_reported_as_unavailable(
    tmp_path: Path, mode: str
) -> None:
    """The undeniable case: the child really did the work, then never answered.

    Whatever exception this connector raises, it must not be a
    ``ConnectionError`` -- the one type the A8 adapter narrows to the
    ``remote_unavailable`` diagnostic, i.e. the one reading that would assert
    the call never reached the target. It provably did reach the target: the
    side-effect log says so.
    """

    side_effect_log = tmp_path / "side-effect.txt"
    connector = StdioToolConnector(
        {
            "raw:side-effect": StdioTargetConfig(
                handle="raw:side-effect",
                command=(PY, RAW_FIXTURE, mode),
                known_tools=frozenset({"raw-echo"}),
                env={"DAGR_STDIO_RAW_SIDE_EFFECT_LOG": str(side_effect_log)},
                timeout_seconds=1.5,
            )
        }
    )
    handler = connector.resolve("raw:side-effect", "raw-echo")

    with pytest.raises((RuntimeError, TimeoutError)) as excinfo:
        await handler({"x": "hi"})

    # The side effect really happened...
    assert side_effect_log.read_text(encoding="utf-8").splitlines() == ["side-effect-performed"]
    # ...and the raised failure never claims otherwise.
    assert not isinstance(excinfo.value, ConnectionError)


async def test_connection_close_after_forwarding_is_not_a_connection_error() -> None:
    connector = StdioToolConnector(
        {
            "raw:close": StdioTargetConfig(
                handle="raw:close",
                command=(PY, RAW_FIXTURE, "close_after_accept"),
                known_tools=frozenset({"raw-echo"}),
                timeout_seconds=5.0,
            )
        }
    )
    handler = connector.resolve("raw:close", "raw-echo")

    with pytest.raises(RuntimeError) as excinfo:
        await handler({"x": "hi"})

    assert not isinstance(excinfo.value, ConnectionError | TimeoutError)


# --------------------------------------------------------------------------- #
# Command and environment boundary -- cwd, argv immutability, stderr channel, #
# temporary-errlog cleanup on every exit path                                 #
# --------------------------------------------------------------------------- #


async def test_explicit_cwd_is_honored_by_the_child(tmp_path: Path) -> None:
    workdir = tmp_path / "explicit-workdir"
    workdir.mkdir()
    connector = StdioToolConnector(
        {
            "local:cwd": StdioTargetConfig(
                handle="local:cwd",
                command=(PY, FASTMCP_FIXTURE),
                known_tools=frozenset({"observed_cwd"}),
                cwd=str(workdir),
                timeout_seconds=15.0,
            )
        }
    )
    handler = connector.resolve("local:cwd", "observed_cwd")

    result = await handler({})

    observed = result.content[0].text
    assert Path(observed).resolve() == workdir.resolve()


def test_command_must_be_a_tuple_not_a_mutable_sequence() -> None:
    # argv is operator-authored and immutable: a list would let a caller who
    # obtained a reference to it mutate the launched command after the config
    # was validated.
    with pytest.raises(ValueError, match="non-empty tuple"):
        StdioTargetConfig(
            handle="local:x",
            command=[PY, FASTMCP_FIXTURE],  # type: ignore[arg-type]
            known_tools=frozenset({"echo"}),
        )


def test_a_bare_name_that_really_exists_on_path_is_still_rejected() -> None:
    # Not merely "invalid names are rejected": a name that $PATH *would*
    # resolve is still rejected, proving the check bans ambient PATH search
    # rather than banning typos.
    import shutil as _shutil

    resolvable = _shutil.which("python3") or _shutil.which("sh")
    assert resolvable is not None
    bare_name = Path(resolvable).name

    with pytest.raises(ValueError, match="absolute"):
        StdioTargetConfig(
            handle="local:bare",
            command=(bare_name,),
            known_tools=frozenset({"echo"}),
        )


def test_config_is_frozen_so_argv_cannot_be_swapped_after_validation() -> None:
    target = StdioTargetConfig(
        handle="local:frozen",
        command=(PY, FASTMCP_FIXTURE),
        known_tools=frozenset({"echo"}),
    )
    with pytest.raises((AttributeError, TypeError)):
        target.command = ("/bin/sh", "-c", "echo pwned")  # type: ignore[misc]


async def test_a_chatty_stderr_child_never_corrupts_the_stdout_jsonrpc_channel() -> None:
    # ~160KB of stderr, far past any pipe buffer, written both before and
    # during the call: the JSON-RPC result must still arrive intact and the
    # call must not deadlock on an undrained stderr pipe.
    connector = StdioToolConnector(
        {
            "raw:noisy": StdioTargetConfig(
                handle="raw:noisy",
                command=(PY, RAW_FIXTURE, "noisy_stderr"),
                known_tools=frozenset({"raw-echo"}),
                timeout_seconds=20.0,
            )
        }
    )
    handler = connector.resolve("raw:noisy", "raw-echo")

    result = await handler({"x": "hi"})

    assert result.content[0].text == "raw-ok"
    assert result.isError is False


@pytest.fixture
def private_tempdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``tempfile`` at a private, per-test directory.

    The connector's per-call child-stderr sink is allocated through
    ``tempfile``, which resolves its directory at call time. Pinning that
    directory per test makes the "no artifact survives any exit path"
    assertion hermetic: the only process that can create an entry here is the
    call under test, so a leftover is unambiguously the connector's leak
    rather than shared-/tmp noise from a concurrent run.
    """

    import tempfile as _tempfile

    private = tmp_path / "connector-tempdir"
    private.mkdir()
    monkeypatch.setattr(_tempfile, "tempdir", str(private))
    return private


def _errlogs_in(directory: Path) -> set[str]:
    """Every named entry the connector left behind, whatever it is called.

    Deliberately not filtered to a known filename prefix. The child-stderr
    sink is anonymous (``tempfile.TemporaryFile`` unlinks it at creation), so
    a probe matching one expected prefix would pass vacuously and stop testing
    anything -- including a future implementation that goes back to a named
    file. This catches any named artifact left in the connector's temp
    directory, whatever an implementation chooses to call it.
    """

    return {path.name for path in directory.iterdir()}


async def test_temporary_stderr_file_is_deleted_on_the_success_path(
    private_tempdir: Path,
) -> None:
    connector = StdioToolConnector(
        {
            "local:ok": StdioTargetConfig(
                handle="local:ok",
                command=(PY, FASTMCP_FIXTURE),
                known_tools=frozenset({"echo"}),
                timeout_seconds=15.0,
            )
        }
    )
    handler = connector.resolve("local:ok", "echo")

    await handler({"x": "hi"})

    assert _errlogs_in(private_tempdir) == set()


async def test_temporary_stderr_file_is_deleted_on_the_spawn_failure_path(
    private_tempdir: Path,
) -> None:
    connector = StdioToolConnector(
        {
            "local:missing": StdioTargetConfig(
                handle="local:missing",
                command=("/nonexistent/absolute/path/to/a/binary",),
                known_tools=frozenset({"echo"}),
                timeout_seconds=5.0,
            )
        }
    )
    handler = connector.resolve("local:missing", "echo")

    with pytest.raises(ConnectionError):
        await handler({"x": "hi"})

    assert _errlogs_in(private_tempdir) == set()


async def test_temporary_stderr_file_is_deleted_on_the_timeout_path(
    private_tempdir: Path,
) -> None:
    connector = StdioToolConnector(
        {
            "raw:hang": StdioTargetConfig(
                handle="raw:hang",
                command=(PY, RAW_FIXTURE, "hang_on_call"),
                known_tools=frozenset({"raw-echo"}),
                timeout_seconds=1.5,
            )
        }
    )
    handler = connector.resolve("raw:hang", "raw-echo")

    with pytest.raises(TimeoutError):
        await handler({"x": "hi"})

    assert _errlogs_in(private_tempdir) == set()


async def test_temporary_stderr_file_is_deleted_on_the_cancellation_path(
    private_tempdir: Path,
) -> None:
    connector = StdioToolConnector(
        {
            "raw:hang": StdioTargetConfig(
                handle="raw:hang",
                command=(PY, RAW_FIXTURE, "hang_on_call"),
                known_tools=frozenset({"raw-echo"}),
                timeout_seconds=60.0,
            )
        }
    )
    handler = connector.resolve("raw:hang", "raw-echo")

    task = asyncio.ensure_future(handler({"x": "hi"}))
    await asyncio.sleep(1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert _errlogs_in(private_tempdir) == set()


async def test_no_env_value_or_command_path_appears_in_a_raised_exception() -> None:
    secret = "sk-must-never-appear-in-an-exception-4b7d"
    connector = StdioToolConnector(
        {
            "raw:hang": StdioTargetConfig(
                handle="raw:hang",
                command=(PY, RAW_FIXTURE, "hang_on_call"),
                known_tools=frozenset({"raw-echo"}),
                env={"DAGR_STDIO_RAW_SECRET": secret},
                timeout_seconds=1.5,
            )
        }
    )
    handler = connector.resolve("raw:hang", "raw-echo")

    with pytest.raises(TimeoutError) as excinfo:
        await handler({"x": "hi"})

    rendered = f"{excinfo.value!r} {excinfo.value!s} {excinfo.value.args!r}"
    assert secret not in rendered
    assert "DAGR_STDIO_RAW_SECRET" not in rendered
    assert RAW_FIXTURE not in rendered


# --------------------------------------------------------------------------- #
# Protocol and discovery claims                                              #
# --------------------------------------------------------------------------- #


async def test_initialize_precedes_the_call_and_the_call_is_sent_exactly_once(
    tmp_path: Path,
) -> None:
    method_log = tmp_path / "methods.txt"
    connector = StdioToolConnector(
        {
            "raw:methods": StdioTargetConfig(
                handle="raw:methods",
                command=(PY, RAW_FIXTURE, "normal"),
                known_tools=frozenset({"raw-echo"}),
                env={"DAGR_STDIO_RAW_METHOD_LOG": str(method_log)},
                timeout_seconds=15.0,
            )
        }
    )
    handler = connector.resolve("raw:methods", "raw-echo")

    await handler({"x": "hi"})

    methods = method_log.read_text(encoding="utf-8").splitlines()

    # initialize strictly precedes the call, and the side-effecting
    # tools/call is written exactly once -- there is no retry layer.
    assert methods[0] == "initialize"
    assert methods.count("tools/call") == 1
    assert methods.index("initialize") < methods.index("tools/call")

    # Recorded honestly rather than wished away: the pinned mcp==1.29.0
    # ClientSession.call_tool issues a *follow-up* tools/list of its own
    # (ClientSession._validate_tool_result refreshes its output-schema cache
    # when the called tool is not already in it). That round trip is
    # read-only, happens strictly *after* the tools/call response has been
    # received, and never re-sends the call -- so "forwarded exactly once"
    # is about the side-effecting tools/call, which it remains. It is not a
    # pre-admission capability probe: nothing about it feeds resolve().
    assert methods.count("tools/list") <= 1
    if "tools/list" in methods:
        assert methods.index("tools/call") < methods.index("tools/list")


async def test_discovery_output_is_not_automatically_admitted_capability(
    tmp_path: Path,
) -> None:
    """tools/list names are discovery output, not an allowlist.

    The child really does declare ``raw-echo``; the operator's
    ``known_tools`` deliberately does not include it. Resolution must still
    refuse, and must refuse without spawning anything.
    """

    method_log = tmp_path / "methods.txt"
    discovered = await discover_tools(
        (PY, RAW_FIXTURE, "normal"),
        env={"DAGR_STDIO_RAW_METHOD_LOG": str(method_log)},
        timeout_seconds=15.0,
    )
    assert "raw-echo" in discovered

    connector = StdioToolConnector(
        {
            "raw:not-admitted": StdioTargetConfig(
                handle="raw:not-admitted",
                command=(PY, RAW_FIXTURE, "normal"),
                known_tools=frozenset(),  # operator declined to admit anything
                env={"DAGR_STDIO_RAW_METHOD_LOG": str(method_log)},
                timeout_seconds=15.0,
            )
        }
    )
    before = method_log.read_text(encoding="utf-8")

    refusal = connector.resolve("raw:not-admitted", "raw-echo")

    assert isinstance(refusal, StdioTargetResolutionRefused)
    assert refusal.reason == "unknown_tool_fail_closed"
    # Not one additional byte of protocol traffic: no second child was spawned.
    assert method_log.read_text(encoding="utf-8") == before


def test_installed_mcp_sdk_version_and_protocol_versions_are_as_recorded() -> None:
    """Pins the exact facts the close memo and docs record.

    If the SDK or its supported protocol-version set moves, this fails and
    the recorded claim has to be re-derived rather than silently drifting.
    """

    from importlib.metadata import version

    from mcp.shared.version import LATEST_PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS

    assert version("mcp") == "1.29.0"
    assert LATEST_PROTOCOL_VERSION == "2025-11-25"
    assert list(SUPPORTED_PROTOCOL_VERSIONS) == [
        "2024-11-05",
        "2025-03-26",
        "2025-06-18",
        "2025-11-25",
    ]
    # The bad_protocol_version fixture's value must stay genuinely
    # unsupported, or the fail-closed negotiation test proves nothing.
    assert "1999-01-01" not in SUPPORTED_PROTOCOL_VERSIONS
