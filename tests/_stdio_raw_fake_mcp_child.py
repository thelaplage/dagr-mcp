"""Deterministic, hand-rolled (no ``mcp`` dependency) fake MCP stdio child
that misbehaves in specific, selectable ways -- for exercising
:mod:`dagr_mcp_service.connectors.stdio`'s failure-posture translation.

Run as a standalone script, never imported, selected by ``sys.argv[1]``:

* ``normal`` -- a minimal, spec-shaped MCP stdio server (initialize,
  ``tools/list``, ``tools/call``) implemented without the ``mcp`` package, so
  the connector test suite is not itself dependent on the SDK's own server
  implementation to prove basic protocol compatibility.
* ``bad_protocol_version`` -- answers ``initialize`` with an unsupported
  ``protocolVersion``, deterministically triggering the pinned client's own
  ``RuntimeError("Unsupported protocol version ...")``.
* ``hang_on_call`` -- completes ``initialize`` normally, then never responds
  to ``tools/call`` -- deterministically triggering the connector's timeout.
* ``crash_after_accept`` -- completes ``initialize`` normally, then exits
  nonzero immediately upon receiving ``tools/call``, writing no response --
  deterministically triggering a child-exit-mid-call failure.
* ``malformed_call_response`` -- completes ``initialize`` normally, then
  answers ``tools/call`` with a line that is not valid JSON at all, then
  stays alive without ever sending a valid response -- deterministically
  proving a malformed line never satisfies the call with wrong data and
  never hangs indefinitely (the connector's own timeout bounds it).
* ``close_after_accept`` -- completes ``initialize`` normally, then closes
  its own stdout and exits *zero* upon receiving ``tools/call``, writing no
  response -- a clean connection close rather than a crash.
* ``noisy_stderr`` -- writes a large volume of text to stderr both before
  and while answering ``tools/call`` normally, proving stderr can never
  corrupt or interleave with the stdout JSON-RPC channel and can never
  deadlock the call on a full pipe buffer.
* ``side_effect_then_hang`` / ``side_effect_then_crash`` /
  ``side_effect_then_close`` -- **record a real, externally observable side
  effect first** (one line appended to the file named by
  ``DAGR_STDIO_RAW_SIDE_EFFECT_LOG``), and only then hang, exit nonzero, or
  close cleanly without ever answering. These are the fixtures that make the
  post-forward semantics undeniable: the work *did* happen, the client
  cannot observe it, and the governed response must therefore never claim
  the call was prevented or did not execute.

Two optional environment variables, honored in every mode:

* ``DAGR_STDIO_RAW_METHOD_LOG`` -- append each received JSON-RPC ``method``
  to this file, in arrival order, so a test can prove ``initialize``
  precedes any ``tools/list``/``tools/call`` and that an admitted call is
  forwarded exactly once.
* ``DAGR_STDIO_RAW_SIDE_EFFECT_LOG`` -- see the ``side_effect_*`` modes.

This script never imports this repository's code and never imports ``mcp``:
it exists precisely to misbehave in ways a spec-compliant server built on the
pinned SDK cannot, so each failure posture is fully within this fixture's
own control.
"""

from __future__ import annotations

import json
import os
import sys
import time

MODE = sys.argv[1] if len(sys.argv) > 1 else "normal"
# Optional third argv: a path this process writes its own PID to on startup,
# so a test can later confirm (via ``os.kill(pid, 0)``) that no orphan of
# this exact process remains once the connector call has returned.
_PID_FILE = sys.argv[2] if len(sys.argv) > 2 else None
if _PID_FILE:
    with open(_PID_FILE, "w", encoding="utf-8") as _pid_handle:
        _pid_handle.write(str(os.getpid()))


def _read_message() -> dict | None:
    line = sys.stdin.readline()
    if not line:
        return None
    return json.loads(line)


def _write_json(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _write_raw(text: str) -> None:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    sys.stdout.flush()


def _append(env_var: str, line: str) -> None:
    path = os.environ.get(env_var)
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _record_side_effect() -> None:
    """Perform the externally observable "work" of this call.

    Deliberately done *before* the mode's failure behavior, and deliberately
    durable (a file the parent test can read), so the test can prove the
    side effect really occurred even though the client will never observe a
    result for the call that caused it.
    """

    _append("DAGR_STDIO_RAW_SIDE_EFFECT_LOG", "side-effect-performed")


def _spew_stderr(marker: str) -> None:
    for index in range(2000):
        sys.stderr.write(f"{marker}-stderr-noise-{index} {'x' * 80}\n")
    sys.stderr.flush()


def main() -> None:
    if MODE == "noisy_stderr":
        _spew_stderr("startup")

    while True:
        try:
            message = _read_message()
        except json.JSONDecodeError:
            continue
        if message is None:
            return

        method = message.get("method")
        request_id = message.get("id")
        if method:
            _append("DAGR_STDIO_RAW_METHOD_LOG", str(method))

        if method == "initialize":
            protocol_version = "1999-01-01" if MODE == "bad_protocol_version" else "2025-06-18"
            _write_json(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": protocol_version,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "raw-fixture", "version": "0.0.0"},
                    },
                }
            )
            continue

        if method == "notifications/initialized":
            continue

        if method == "tools/list":
            _write_json(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [
                            {
                                "name": "raw-echo",
                                "inputSchema": {"type": "object", "properties": {}},
                            }
                        ]
                    },
                }
            )
            continue

        if method == "tools/call":
            if MODE == "hang_on_call":
                time.sleep(3600)
                continue
            if MODE == "crash_after_accept":
                sys.exit(1)
            if MODE == "close_after_accept":
                sys.stdout.close()
                sys.exit(0)
            if MODE == "malformed_call_response":
                _write_raw("this-is-not-json{{{")
                time.sleep(3600)
                continue
            if MODE == "side_effect_then_hang":
                _record_side_effect()
                time.sleep(3600)
                continue
            if MODE == "side_effect_then_crash":
                _record_side_effect()
                sys.exit(1)
            if MODE == "side_effect_then_close":
                _record_side_effect()
                sys.stdout.close()
                sys.exit(0)
            if MODE == "noisy_stderr":
                _spew_stderr("during-call")
            _write_json(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": "raw-ok"}],
                        "isError": False,
                    },
                }
            )
            continue

        # Unknown method: ignore, matching a permissive/no-op server.


if __name__ == "__main__":
    main()
