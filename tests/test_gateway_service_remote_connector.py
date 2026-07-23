"""Sprint A9 — the client-side remote MCP connector
(``dagr_mcp_service.connectors.remote``).

Unit-level coverage of the connector module itself, driven against a real
loopback MCP server over the pinned ``mcp==1.28.1`` Streamable HTTP client
transport (see ``tests/_gateway_service_remote_fixtures.py``). Covers: the
frozen A8 connector seam; operator-only target configuration and endpoint
validation; no caller-suppliable URL/scheme/host/port/header/credential;
credential/context provider semantics and lifetime; honest failure
classification (connection unavailable vs. timeout vs. cancellation vs.
generic exception); connection cleanup on every exit path; concurrency
isolation; and import purity. See
``docs/GATEWAY_SERVICE_ADAPTER_SCOPE.md`` §7, §8, §12, §13, work package A9.
"""

from __future__ import annotations

import asyncio
import inspect
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastmcp")
pytest.importorskip("mcp")

from dagr_mcp_service.connectors.memory import InMemoryToolConnector
from dagr_mcp_service.connectors.remote import (
    RemoteCredential,
    RemoteTargetConfig,
    RemoteTargetResolutionRefused,
    RemoteToolConnector,
    TrustedOutboundContext,
    _flatten_exception_group,
    _origin,
    _redirect_credential_guard,
    _translate_transport_failure,
)

from tests._gateway_service_remote_fixtures import LoopbackMcpServer, loopback_mcp_server  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# RemoteTargetConfig — endpoint validation at construction time              #
# --------------------------------------------------------------------------- #


def test_https_endpoint_is_accepted() -> None:
    RemoteTargetConfig(handle="bossy:prod", endpoint_uri="https://bossy.example.com/mcp")


def test_http_to_a_non_loopback_host_is_rejected_even_with_the_loopback_flag() -> None:
    with pytest.raises(ValueError, match="insecure-loopback"):
        RemoteTargetConfig(
            handle="bossy:evil",
            endpoint_uri="http://example.com/mcp",
            allow_insecure_loopback=True,
        )


def test_http_to_loopback_without_the_explicit_flag_is_rejected() -> None:
    with pytest.raises(ValueError, match="insecure-loopback"):
        RemoteTargetConfig(handle="bossy:test", endpoint_uri="http://127.0.0.1:8080/mcp")


def test_http_to_loopback_with_the_explicit_flag_is_accepted() -> None:
    RemoteTargetConfig(
        handle="bossy:test",
        endpoint_uri="http://127.0.0.1:8080/mcp",
        allow_insecure_loopback=True,
    )
    RemoteTargetConfig(
        handle="bossy:test",
        endpoint_uri="http://localhost:8080/mcp",
        allow_insecure_loopback=True,
    )


@pytest.mark.parametrize("scheme", ["ftp", "ws", "wss", "file", "stdio", ""])
def test_unsupported_schemes_are_rejected(scheme: str) -> None:
    uri = f"{scheme}://127.0.0.1:8080/mcp" if scheme else "127.0.0.1:8080/mcp"
    with pytest.raises(ValueError):
        RemoteTargetConfig(handle="bossy:test", endpoint_uri=uri, allow_insecure_loopback=True)


def test_url_userinfo_is_rejected() -> None:
    with pytest.raises(ValueError, match="userinfo"):
        RemoteTargetConfig(handle="bossy:test", endpoint_uri="https://user:pass@bossy.example.com/mcp")


def test_url_userinfo_without_password_is_rejected() -> None:
    with pytest.raises(ValueError, match="userinfo"):
        RemoteTargetConfig(handle="bossy:test", endpoint_uri="https://trusted.example.com@evil.example.com/mcp")


def test_url_fragment_is_rejected() -> None:
    with pytest.raises(ValueError, match="fragment"):
        RemoteTargetConfig(handle="bossy:test", endpoint_uri="https://bossy.example.com/mcp#frag")


def test_non_positive_timeout_is_rejected() -> None:
    with pytest.raises(ValueError):
        RemoteTargetConfig(
            handle="bossy:test", endpoint_uri="https://bossy.example.com/mcp", timeout_seconds=0
        )
    with pytest.raises(ValueError):
        RemoteTargetConfig(
            handle="bossy:test", endpoint_uri="https://bossy.example.com/mcp", timeout_seconds=-1
        )


def test_unsupported_scheme_opens_no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("no socket may be opened for a config that fails to construct")

    monkeypatch.setattr(socket, "socket", _forbidden)
    with pytest.raises(ValueError):
        RemoteTargetConfig(handle="bossy:evil", endpoint_uri="http://evil.example.com/mcp")


# --------------------------------------------------------------------------- #
# RemoteToolConnector construction and resolve()                             #
# --------------------------------------------------------------------------- #


def test_connector_rejects_a_registry_key_that_does_not_match_the_configs_own_handle() -> None:
    target = RemoteTargetConfig(handle="bossy:prod", endpoint_uri="https://bossy.example.com/mcp")
    with pytest.raises(ValueError):
        RemoteToolConnector({"bossy:other-key": target})


def test_connector_does_not_mutate_the_registry_it_was_constructed_with() -> None:
    target = RemoteTargetConfig(handle="bossy:prod", endpoint_uri="https://bossy.example.com/mcp")
    targets = {"bossy:prod": target}
    connector = RemoteToolConnector(targets)

    targets["bossy:new"] = RemoteTargetConfig(
        handle="bossy:new", endpoint_uri="https://new.example.com/mcp"
    )

    resolved = connector.resolve("bossy:new", "echo")
    assert isinstance(resolved, RemoteTargetResolutionRefused)


def test_resolve_signature_matches_the_frozen_a8_connector_seam() -> None:
    # The A8 seam (dagr_mcp_service.adapter.execute_governed_call) calls
    # connector.resolve(target_handle, tool_name) unconditionally; a remote
    # connector must accept that exact call, just like the memory connector.
    signature = inspect.signature(RemoteToolConnector.resolve)
    assert set(signature.parameters) == {"self", "target_handle", "tool_name"}


def test_resolve_unknown_target_handle_refuses_with_remote_unavailable() -> None:
    connector = RemoteToolConnector(
        {"bossy:prod": RemoteTargetConfig(handle="bossy:prod", endpoint_uri="https://bossy.example.com/mcp")}
    )

    resolved = connector.resolve("bossy:does-not-exist", "echo")

    assert isinstance(resolved, RemoteTargetResolutionRefused)
    assert resolved.reason == "remote_unavailable"
    assert resolved.target_handle == "bossy:does-not-exist"
    assert resolved.tool_name == "echo"


def test_resolve_unknown_target_handle_opens_no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = RemoteToolConnector(
        {"bossy:prod": RemoteTargetConfig(handle="bossy:prod", endpoint_uri="https://bossy.example.com/mcp")}
    )

    def _forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("resolving an unknown target handle must open no socket")

    monkeypatch.setattr(socket, "socket", _forbidden)
    resolved = connector.resolve("bossy:does-not-exist", "echo")
    assert isinstance(resolved, RemoteTargetResolutionRefused)


def test_resolve_known_target_returns_a_callable_and_opens_no_socket_by_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = RemoteToolConnector(
        {"bossy:prod": RemoteTargetConfig(handle="bossy:prod", endpoint_uri="https://bossy.example.com/mcp")}
    )

    def _forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("resolve() itself must never open a socket -- only invoking its result may")

    monkeypatch.setattr(socket, "socket", _forbidden)
    resolved = connector.resolve("bossy:prod", "echo")
    assert callable(resolved)


def test_resolved_handler_signature_carries_only_arguments() -> None:
    connector = RemoteToolConnector(
        {"bossy:prod": RemoteTargetConfig(handle="bossy:prod", endpoint_uri="https://bossy.example.com/mcp")}
    )
    handler = connector.resolve("bossy:prod", "echo")
    signature = inspect.signature(handler)
    assert list(signature.parameters) == ["call_arguments"]


# --------------------------------------------------------------------------- #
# Real loopback calls -- result, tool-level error, unavailable target         #
# --------------------------------------------------------------------------- #


async def test_admitted_result_round_trips_over_a_real_loopback_server(
    loopback_mcp_server: LoopbackMcpServer,
) -> None:
    connector = RemoteToolConnector(
        {
            "bossy:test": RemoteTargetConfig(
                handle="bossy:test",
                endpoint_uri=loopback_mcp_server.base_url,
                allow_insecure_loopback=True,
                timeout_seconds=5.0,
            )
        }
    )
    handler = connector.resolve("bossy:test", "echo")

    result = await handler({"x": "hello"})

    assert result.isError is False
    assert result.content[0].text == "echo:hello"


async def test_remote_tool_level_error_is_returned_not_raised(
    loopback_mcp_server: LoopbackMcpServer,
) -> None:
    connector = RemoteToolConnector(
        {
            "bossy:test": RemoteTargetConfig(
                handle="bossy:test",
                endpoint_uri=loopback_mcp_server.base_url,
                allow_insecure_loopback=True,
                timeout_seconds=5.0,
            )
        }
    )
    handler = connector.resolve("bossy:test", "boom")

    result = await handler({"x": "hello"})

    assert result.isError is True
    # The tool's own exception message is on the remote server's content --
    # this module never fabricates or suppresses it, but also never widens
    # it with anything of its own (URL, header, credential).
    assert "boom-internal-detail" in result.content[0].text


async def test_connection_unavailable_raises_connection_error() -> None:
    connector = RemoteToolConnector(
        {
            "bossy:down": RemoteTargetConfig(
                handle="bossy:down",
                endpoint_uri="http://127.0.0.1:1/mcp",
                allow_insecure_loopback=True,
                timeout_seconds=3.0,
            )
        }
    )
    handler = connector.resolve("bossy:down", "echo")

    with pytest.raises(ConnectionError) as excinfo:
        await handler({"x": "hello"})

    # Content-free: no host, port, or scheme leaks into the message.
    assert "127.0.0.1" not in str(excinfo.value)
    assert ":1" not in str(excinfo.value)


async def test_dns_failure_also_raises_connection_error() -> None:
    connector = RemoteToolConnector(
        {
            "bossy:nowhere": RemoteTargetConfig(
                handle="bossy:nowhere",
                endpoint_uri="https://this-host-should-not-exist.invalid/mcp",
                timeout_seconds=3.0,
            )
        }
    )
    handler = connector.resolve("bossy:nowhere", "echo")

    with pytest.raises(ConnectionError):
        await handler({"x": "hello"})


async def test_timeout_raises_builtin_timeout_error(loopback_mcp_server: LoopbackMcpServer) -> None:
    connector = RemoteToolConnector(
        {
            "bossy:test": RemoteTargetConfig(
                handle="bossy:test",
                endpoint_uri=loopback_mcp_server.base_url,
                allow_insecure_loopback=True,
                timeout_seconds=1.0,
            )
        }
    )
    handler = connector.resolve("bossy:test", "slow")

    with pytest.raises(TimeoutError):
        await handler({"x": "hello", "seconds": 10.0})


async def test_cancellation_propagates_cleanly_not_swallowed_or_wrapped(
    loopback_mcp_server: LoopbackMcpServer,
) -> None:
    connector = RemoteToolConnector(
        {
            "bossy:test": RemoteTargetConfig(
                handle="bossy:test",
                endpoint_uri=loopback_mcp_server.base_url,
                allow_insecure_loopback=True,
                timeout_seconds=30.0,
            )
        }
    )
    handler = connector.resolve("bossy:test", "slow")

    task = asyncio.ensure_future(handler({"x": "hello", "seconds": 30.0}))
    await asyncio.sleep(0.5)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


# --------------------------------------------------------------------------- #
# Connection cleanup on every exit path                                      #
# --------------------------------------------------------------------------- #


async def test_connection_closes_after_result_error_exception_and_cancellation(
    loopback_mcp_server: LoopbackMcpServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    closes: list[bool] = []
    original_aexit = httpx.AsyncClient.__aexit__

    async def _spy_aexit(self: Any, *args: Any, **kwargs: Any) -> Any:
        outcome = await original_aexit(self, *args, **kwargs)
        closes.append(self.is_closed)
        return outcome

    monkeypatch.setattr(httpx.AsyncClient, "__aexit__", _spy_aexit)

    connector = RemoteToolConnector(
        {
            "bossy:test": RemoteTargetConfig(
                handle="bossy:test",
                endpoint_uri=loopback_mcp_server.base_url,
                allow_insecure_loopback=True,
                timeout_seconds=5.0,
            ),
            "bossy:down": RemoteTargetConfig(
                handle="bossy:down",
                endpoint_uri="http://127.0.0.1:1/mcp",
                allow_insecure_loopback=True,
                timeout_seconds=3.0,
            ),
        }
    )

    await connector.resolve("bossy:test", "echo")({"x": "a"})
    assert closes == [True]

    await connector.resolve("bossy:test", "boom")({"x": "a"})
    assert closes == [True, True]

    with pytest.raises(ConnectionError):
        await connector.resolve("bossy:down", "echo")({"x": "a"})
    assert closes == [True, True, True]

    with pytest.raises(TimeoutError):
        await connector.resolve("bossy:test", "slow")({"x": "a", "seconds": 10.0})
    assert closes == [True, True, True, True]

    task = asyncio.ensure_future(
        connector.resolve("bossy:test", "slow")({"x": "a", "seconds": 30.0})
    )
    await asyncio.sleep(0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closes == [True, True, True, True, True]


# --------------------------------------------------------------------------- #
# Credential / trusted-context seam                                          #
# --------------------------------------------------------------------------- #


async def test_bind_trusted_context_delivers_the_exact_resolved_refs_to_the_provider(
    loopback_mcp_server: LoopbackMcpServer,
) -> None:
    seen: list[TrustedOutboundContext] = []

    async def provider(context: TrustedOutboundContext) -> RemoteCredential | None:
        seen.append(context)
        return None

    connector = RemoteToolConnector(
        {
            "bossy:test": RemoteTargetConfig(
                handle="bossy:test",
                endpoint_uri=loopback_mcp_server.base_url,
                allow_insecure_loopback=True,
                timeout_seconds=5.0,
                credential_provider=provider,
            )
        }
    )
    handler = connector.resolve("bossy:test", "echo")
    bound = connector.bind_trusted_context(
        handler,
        target_handle="bossy:test",
        tool_name="echo",
        actor_ref="actor:sha256:known",
        tenant_ref="tenant:sha256:known",
        parent_receipt_ref="urn:srs:receipt:admission:parent-1",
        request_ref="req:42",
    )

    await bound({"x": "hi"})

    assert len(seen) == 1
    context = seen[0]
    assert context.target_handle == "bossy:test"
    assert context.tool_name == "echo"
    assert context.actor_ref == "actor:sha256:known"
    assert context.tenant_ref == "tenant:sha256:known"
    assert context.parent_receipt_ref == "urn:srs:receipt:admission:parent-1"
    assert context.request_ref == "req:42"


async def test_credential_provider_headers_actually_reach_the_wire(
    loopback_mcp_server: LoopbackMcpServer,
) -> None:
    async def provider(context: TrustedOutboundContext) -> RemoteCredential:
        return RemoteCredential(headers={"Authorization": "Bearer a9-proof-token"})

    connector = RemoteToolConnector(
        {
            "bossy:test": RemoteTargetConfig(
                handle="bossy:test",
                endpoint_uri=loopback_mcp_server.base_url,
                allow_insecure_loopback=True,
                timeout_seconds=5.0,
                credential_provider=provider,
            )
        }
    )
    handler = connector.resolve("bossy:test", "observed_headers")
    bound = connector.bind_trusted_context(
        handler,
        target_handle="bossy:test",
        tool_name="observed_headers",
        actor_ref="actor:sha256:known",
        tenant_ref=None,
        parent_receipt_ref=None,
        request_ref="req:1",
    )

    result = await bound({})

    import json

    observed = json.loads(result.content[0].text)
    assert observed.get("authorization") == "Bearer a9-proof-token"


async def test_credential_provider_returning_none_sends_no_authorization_header(
    loopback_mcp_server: LoopbackMcpServer,
) -> None:
    async def provider(context: TrustedOutboundContext) -> RemoteCredential | None:
        return None

    connector = RemoteToolConnector(
        {
            "bossy:test": RemoteTargetConfig(
                handle="bossy:test",
                endpoint_uri=loopback_mcp_server.base_url,
                allow_insecure_loopback=True,
                timeout_seconds=5.0,
                credential_provider=provider,
            )
        }
    )
    handler = connector.resolve("bossy:test", "observed_headers")

    result = await handler({})

    import json

    observed = json.loads(result.content[0].text)
    assert "authorization" not in observed


async def test_no_auth_target_never_calls_a_provider_and_sends_no_authorization_header(
    loopback_mcp_server: LoopbackMcpServer,
) -> None:
    connector = RemoteToolConnector(
        {
            "bossy:test": RemoteTargetConfig(
                handle="bossy:test",
                endpoint_uri=loopback_mcp_server.base_url,
                allow_insecure_loopback=True,
                timeout_seconds=5.0,
                credential_provider=None,
            )
        }
    )
    handler = connector.resolve("bossy:test", "observed_headers")

    result = await handler({})

    import json

    observed = json.loads(result.content[0].text)
    assert "authorization" not in observed


async def test_credential_provider_failure_opens_no_connection_and_is_not_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_provider(context: TrustedOutboundContext) -> RemoteCredential:
        raise RuntimeError("credential-backend-unreachable: sk-should-never-leak")

    connector = RemoteToolConnector(
        {
            "bossy:test": RemoteTargetConfig(
                handle="bossy:test",
                endpoint_uri="https://bossy.example.com/mcp",
                timeout_seconds=5.0,
                credential_provider=failing_provider,
            )
        }
    )
    handler = connector.resolve("bossy:test", "echo")

    def _forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a failing credential provider must open no socket")

    monkeypatch.setattr(socket, "socket", _forbidden)

    with pytest.raises(RuntimeError) as excinfo:
        await handler({"x": "hi"})

    # Not a ConnectionError: a credential failure must never be mistaken for
    # a remote-server failure, since no connection was attempted at all.
    assert not isinstance(excinfo.value, ConnectionError)


def test_credential_provider_failure_message_never_reaches_a_governed_call_response() -> None:
    # A structural guarantee, not a behavioral one: the connector re-raises
    # the provider's own exception unchanged (see the prior test) rather than
    # wrapping or logging it, and dagr_mcp_service.adapter._classify (A8,
    # unmodified for this path) only ever reads a raised exception's *type*,
    # never its message, onto a receipt or a GovernedCallResponse -- verified
    # directly against the adapter's source below, without re-deriving A8's
    # own frozen behavior.
    import dagr_mcp_service.adapter as adapter_module

    source = inspect.getsource(adapter_module._classify)
    assert "str(raised)" not in source
    assert "raised.args" not in source


# --------------------------------------------------------------------------- #
# Redirect credential guard and environment-proxy posture                    #
# --------------------------------------------------------------------------- #


class _FakeRequest:
    def __init__(self, url: str, headers: dict[str, str]) -> None:
        self.url = url
        self.headers = dict(headers)


async def test_redirect_guard_leaves_same_origin_headers_untouched() -> None:
    guard = _redirect_credential_guard(
        _origin("https://bossy.example.com/mcp"), ("Authorization", "X-Api-Key")
    )
    request = _FakeRequest(
        "https://bossy.example.com/mcp2", {"Authorization": "Bearer t", "X-Api-Key": "k"}
    )

    await guard(request)

    assert request.headers == {"Authorization": "Bearer t", "X-Api-Key": "k"}


async def test_redirect_guard_strips_credential_headers_on_cross_origin_redirect() -> None:
    guard = _redirect_credential_guard(
        _origin("https://bossy.example.com/mcp"), ("Authorization", "X-Api-Key")
    )
    request = _FakeRequest(
        "https://attacker.example.com/mcp", {"Authorization": "Bearer t", "X-Api-Key": "k"}
    )

    await guard(request)

    assert "Authorization" not in request.headers
    assert "X-Api-Key" not in request.headers


async def test_redirect_guard_strips_credential_headers_on_cross_port_redirect() -> None:
    # Same host, different port is a different origin.
    guard = _redirect_credential_guard(
        _origin("https://bossy.example.com:8443/mcp"), ("Authorization",)
    )
    request = _FakeRequest("https://bossy.example.com:9443/mcp", {"Authorization": "Bearer t"})

    await guard(request)

    assert "Authorization" not in request.headers


async def test_no_redirect_guard_is_installed_when_redirects_are_disallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _RecordingAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured.update(kwargs)
            raise RuntimeError("stop before any real network attempt")

    async def provider(context: TrustedOutboundContext) -> RemoteCredential:
        return RemoteCredential(headers={"Authorization": "Bearer t"})

    connector = RemoteToolConnector(
        {
            "bossy:test": RemoteTargetConfig(
                handle="bossy:test",
                endpoint_uri="https://bossy.example.com/mcp",
                allow_redirects=False,
                credential_provider=provider,
            )
        }
    )
    handler = connector.resolve("bossy:test", "echo")

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _RecordingAsyncClient)

    with pytest.raises(RuntimeError, match="remote MCP protocol or decoding exception"):
        await handler({"x": "hi"})

    assert captured["event_hooks"] is None
    assert captured["trust_env"] is False


async def test_redirect_guard_is_installed_when_redirects_are_allowed_and_credentialed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _RecordingAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured.update(kwargs)
            raise RuntimeError("stop before any real network attempt")

    async def provider(context: TrustedOutboundContext) -> RemoteCredential:
        return RemoteCredential(headers={"Authorization": "Bearer t"})

    connector = RemoteToolConnector(
        {
            "bossy:test": RemoteTargetConfig(
                handle="bossy:test",
                endpoint_uri="https://bossy.example.com/mcp",
                allow_redirects=True,
                credential_provider=provider,
            )
        }
    )
    handler = connector.resolve("bossy:test", "echo")

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _RecordingAsyncClient)

    with pytest.raises(RuntimeError, match="remote MCP protocol or decoding exception"):
        await handler({"x": "hi"})

    assert captured["event_hooks"] is not None
    assert "request" in captured["event_hooks"]
    assert captured["trust_env"] is False


async def test_trust_env_is_always_false_even_without_redirects_or_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _RecordingAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured.update(kwargs)
            raise RuntimeError("stop before any real network attempt")

    connector = RemoteToolConnector(
        {
            "bossy:test": RemoteTargetConfig(
                handle="bossy:test", endpoint_uri="https://bossy.example.com/mcp"
            )
        }
    )
    handler = connector.resolve("bossy:test", "echo")

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _RecordingAsyncClient)

    with pytest.raises(RuntimeError, match="remote MCP protocol or decoding exception"):
        await handler({"x": "hi"})

    assert captured["trust_env"] is False
    assert captured["event_hooks"] is None


# --------------------------------------------------------------------------- #
# Exception translation (unit-level, no network)                             #
# --------------------------------------------------------------------------- #


def test_translate_transport_failure_prefers_connect_error_over_generic() -> None:
    import httpx

    connect_error = httpx.ConnectError("refused")
    translated = _translate_transport_failure(BaseExceptionGroup("eg", [connect_error]))
    assert isinstance(translated, ConnectionError)


def test_translate_transport_failure_maps_mcp_timeout_error_code() -> None:
    from mcp.shared.exceptions import McpError
    from mcp.types import ErrorData

    timeout_error = McpError(ErrorData(code=408, message="Timed out"))
    translated = _translate_transport_failure(BaseExceptionGroup("eg", [timeout_error]))
    assert isinstance(translated, TimeoutError)


def test_translate_transport_failure_maps_httpx_read_timeout() -> None:
    import httpx

    read_timeout = httpx.ReadTimeout("read timed out")
    translated = _translate_transport_failure(BaseExceptionGroup("eg", [read_timeout]))
    assert isinstance(translated, TimeoutError)


def test_translate_transport_failure_falls_back_to_generic_runtime_error() -> None:
    translated = _translate_transport_failure(BaseExceptionGroup("eg", [ValueError("odd")]))
    assert isinstance(translated, RuntimeError)
    assert not isinstance(translated, ConnectionError | TimeoutError)


def test_translate_transport_failure_preserves_cancelled_error_unwrapped() -> None:
    cancelled = asyncio.CancelledError()
    translated = _translate_transport_failure(BaseExceptionGroup("eg", [cancelled]))
    assert translated is cancelled


def test_flatten_exception_group_handles_nested_groups() -> None:
    leaf = ValueError("deep")
    nested = BaseExceptionGroup("inner", [leaf])
    outer = BaseExceptionGroup("outer", [nested])
    assert _flatten_exception_group(outer) == [leaf]


def test_translated_exceptions_never_embed_the_original_message() -> None:
    import httpx

    original = httpx.ConnectError("connect to 10.0.0.1:9999 failed: secret-detail")
    translated = _translate_transport_failure(BaseExceptionGroup("eg", [original]))
    assert "10.0.0.1" not in str(translated)
    assert "secret-detail" not in str(translated)


# --------------------------------------------------------------------------- #
# Concurrency isolation                                                      #
# --------------------------------------------------------------------------- #


async def test_concurrent_calls_do_not_mix_credentials_arguments_or_results(
    loopback_mcp_server: LoopbackMcpServer,
) -> None:
    async def provider_a(context: TrustedOutboundContext) -> RemoteCredential:
        return RemoteCredential(headers={"Authorization": "Bearer token-a"})

    async def provider_b(context: TrustedOutboundContext) -> RemoteCredential:
        return RemoteCredential(headers={"Authorization": "Bearer token-b"})

    connector = RemoteToolConnector(
        {
            "bossy:a": RemoteTargetConfig(
                handle="bossy:a",
                endpoint_uri=loopback_mcp_server.base_url,
                allow_insecure_loopback=True,
                timeout_seconds=5.0,
                credential_provider=provider_a,
            ),
            "bossy:b": RemoteTargetConfig(
                handle="bossy:b",
                endpoint_uri=loopback_mcp_server.base_url,
                allow_insecure_loopback=True,
                timeout_seconds=5.0,
                credential_provider=provider_b,
            ),
        }
    )

    handler_a = connector.resolve("bossy:a", "observed_headers")
    handler_b = connector.resolve("bossy:b", "observed_headers")

    echo_a = connector.resolve("bossy:a", "echo")
    echo_b = connector.resolve("bossy:b", "echo")

    results = await asyncio.gather(
        handler_a({}),
        handler_b({}),
        echo_a({"x": "from-a"}),
        echo_b({"x": "from-b"}),
    )

    import json

    headers_a = json.loads(results[0].content[0].text)
    headers_b = json.loads(results[1].content[0].text)
    assert headers_a["authorization"] == "Bearer token-a"
    assert headers_b["authorization"] == "Bearer token-b"
    assert results[2].content[0].text == "echo:from-a"
    assert results[3].content[0].text == "echo:from-b"


# --------------------------------------------------------------------------- #
# Import purity and no-forbidden-surface checks                              #
# --------------------------------------------------------------------------- #


def test_importing_the_connector_package_does_not_eagerly_import_the_remote_sdk_or_http_stack() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys\n"
                "import dagr_mcp_service\n"
                "import dagr_mcp_service.connectors\n"
                "assert 'httpx' not in sys.modules, 'httpx imported at connectors package import'\n"
                "assert 'mcp.client.streamable_http' not in sys.modules, "
                "'mcp.client.streamable_http imported at connectors package import'\n"
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


def test_importing_the_remote_module_itself_does_not_eagerly_import_the_http_stack() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys\n"
                "from dagr_mcp_service.connectors import remote\n"
                "assert 'httpx' not in sys.modules, 'httpx imported at remote module import'\n"
                "assert 'mcp.client.streamable_http' not in sys.modules, "
                "'mcp.client.streamable_http imported at remote module import'\n"
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


def test_no_stdio_websocket_sse_subprocess_or_generic_transport_surface_on_the_module() -> None:
    import dagr_mcp_service.connectors.remote as remote_module

    lines = Path(remote_module.__file__).read_text(encoding="utf-8").splitlines()
    code_lines = [
        line
        for line in lines
        if not line.strip().startswith("#") and '"""' not in line and "'''" not in line
    ]
    code_text = "\n".join(code_lines)

    for forbidden in (
        "subprocess",
        "stdio",
        "websocket",
        "asyncio.create_subprocess",
        "sse_client",
        "Popen",
    ):
        assert forbidden not in code_text, f"unexpected transport surface: {forbidden!r}"


def test_no_public_host_or_server_startup_surface_on_the_module() -> None:
    import dagr_mcp_service.connectors.remote as remote_module

    lines = Path(remote_module.__file__).read_text(encoding="utf-8").splitlines()
    code_lines = [
        line
        for line in lines
        if not line.strip().startswith("#") and '"""' not in line and "'''" not in line
    ]
    code_text = "\n".join(code_lines)

    for forbidden in ("fastapi", "starlette", "flask", "django", "uvicorn", "asgi"):
        assert forbidden not in code_text.lower(), f"unexpected server-hosting surface: {forbidden!r}"


def test_memory_connector_is_unaffected_by_the_a9_bind_trusted_context_hook() -> None:
    # dagr_mcp_service.adapter checks getattr(config.connector,
    # "bind_trusted_context", None); the memory connector must continue to
    # define no such method at all.
    assert not hasattr(InMemoryToolConnector, "bind_trusted_context")
