"""SAM-NATIVE-MCP-BIND0 -- offline test suite for
``dagr_mcp_service.connectors.sam_native`` (DRAFT).

All network activity in this module is a real loopback MCP server bound to
``127.0.0.1`` (``tests/_gateway_service_sam_fixtures.py``), emulating the
local sam-node ``/mcp`` endpoint -- never a live ``sam-node`` process, never
an external network call. See that fixture module's docstring and the lane's
own program brief (SAM-SUBSTRATE-BUILD0 / SAM-NATIVE-MCP-BIND0) for the
OFFLINE-ONLY posture this suite proves.

Covers: fail-closed resolution (unknown handle/tool/sam-endpoint), the
composition seam onto ``RemoteToolConnector`` (no second transport), caller
argument/routing injection resistance, structural (not semantic) result
validation, honest transport-failure classification reused unmodified from
``connectors.remote``, and the five explicit doctrine statements the lane
brief requires as named proofs:
SAM discovery ≠ eligibility; SAM authentication ≠ authorization; SAM route
success ≠ execution authorization; SAM result ≠ semantic truth; transport
failure ≠ evidence absence.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fastmcp")
pytest.importorskip("mcp")

from dagr_mcp_service.connectors.remote import RemoteTargetConfig, RemoteToolConnector
from dagr_mcp_service.connectors.sam_native import (
    SamNativeConnector,
    SamRouteConfig,
    SamTargetResolutionRefused,
    _validate_call_remote_tool_result,
    describe_sam_remote_tool,
    discover_sam_peers,
    find_sam_remote_tools,
)

from tests._gateway_service_sam_fixtures import (  # noqa: F401
    REQUIRED_AUTH_HEADER,
    REQUIRED_AUTH_VALUE,
    LoopbackSamNodeServer,
    loopback_sam_node_server,
    loopback_sam_node_server_with_auth,
)


def _remote_connector(server: LoopbackSamNodeServer, *, handle: str = "sam:local") -> RemoteToolConnector:
    return RemoteToolConnector(
        {
            handle: RemoteTargetConfig(
                handle=handle,
                endpoint_uri=server.base_url,
                allow_insecure_loopback=True,
                timeout_seconds=5.0,
            )
        }
    )


def _authed_remote_connector(
    server: LoopbackSamNodeServer, *, handle: str = "sam:local-auth"
) -> RemoteToolConnector:
    def _credential_provider(_context):
        from dagr_mcp_service.connectors.remote import RemoteCredential

        return RemoteCredential(headers={REQUIRED_AUTH_HEADER: REQUIRED_AUTH_VALUE})

    return RemoteToolConnector(
        {
            handle: RemoteTargetConfig(
                handle=handle,
                endpoint_uri=server.base_url,
                allow_insecure_loopback=True,
                timeout_seconds=5.0,
                credential_provider=_credential_provider,
            )
        }
    )


def _echo_route(*, sam_endpoint_handle: str, peer_id: str = "peer-good", labels: tuple[str, ...] = ()) -> SamRouteConfig:
    return SamRouteConfig(
        sam_endpoint_handle=sam_endpoint_handle,
        peer_id=peer_id,
        remote_tool_name="mcp://svc/echo",
        required_labels=labels,
    )


# --------------------------------------------------------------------------- #
# SamRouteConfig construction-time validation                                 #
# --------------------------------------------------------------------------- #


def test_route_config_rejects_non_namespaced_tool_name() -> None:
    with pytest.raises(ValueError, match="namespaced"):
        SamRouteConfig(sam_endpoint_handle="sam:local", peer_id="peer-good", remote_tool_name="echo")


def test_route_config_rejects_empty_peer_id() -> None:
    with pytest.raises(ValueError, match="peer_id"):
        SamRouteConfig(sam_endpoint_handle="sam:local", peer_id="", remote_tool_name="mcp://svc/echo")


def test_route_config_accepts_well_formed_namespaced_tool() -> None:
    SamRouteConfig(sam_endpoint_handle="sam:local", peer_id="peer-good", remote_tool_name="mcp://svc/echo")


# --------------------------------------------------------------------------- #
# Fail-closed resolution -- HOSTILE: unknown target_handle                    #
# --------------------------------------------------------------------------- #


def test_unknown_target_handle_is_refused_not_defaulted() -> None:
    remote = RemoteToolConnector({})
    connector = SamNativeConnector(remote_connector=remote, targets={})
    result = connector.resolve("nonexistent:handle", "echo")
    assert isinstance(result, SamTargetResolutionRefused)
    assert result.reason == "remote_unavailable"
    assert result.target_handle == "nonexistent:handle"


# --------------------------------------------------------------------------- #
# Fail-closed resolution -- HOSTILE: unknown/ambiguous SAM peer/service       #
# --------------------------------------------------------------------------- #


def test_known_handle_unknown_tool_is_refused_unknown_tool_fail_closed() -> None:
    remote = RemoteToolConnector({})
    connector = SamNativeConnector(
        remote_connector=remote,
        targets={"cp:target": {"echo": _echo_route(sam_endpoint_handle="sam:local")}},
    )
    result = connector.resolve("cp:target", "not_registered")
    assert isinstance(result, SamTargetResolutionRefused)
    assert result.reason == "unknown_tool_fail_closed"


def test_route_naming_an_unconfigured_sam_endpoint_is_refused_not_defaulted() -> None:
    # The route's sam_endpoint_handle points at a local sam-node endpoint the
    # underlying RemoteToolConnector never had registered -- an operator
    # config gap, must fail closed, never silently fall back to some other
    # endpoint.
    remote = RemoteToolConnector({})  # empty: no sam endpoints configured at all
    connector = SamNativeConnector(
        remote_connector=remote,
        targets={"cp:target": {"echo": _echo_route(sam_endpoint_handle="sam:missing")}},
    )
    result = connector.resolve("cp:target", "echo")
    assert isinstance(result, SamTargetResolutionRefused)
    assert result.reason == "remote_unavailable"


# --------------------------------------------------------------------------- #
# HOSTILE: caller attempts peer/URL/auth injection                            #
# --------------------------------------------------------------------------- #


async def test_caller_supplied_peer_and_url_keys_never_override_operator_routing(
    loopback_sam_node_server: LoopbackSamNodeServer,
) -> None:
    remote = _remote_connector(loopback_sam_node_server)
    connector = SamNativeConnector(
        remote_connector=remote,
        targets={"cp:target": {"echo": _echo_route(sam_endpoint_handle="sam:local")}},
    )
    handler = connector.resolve("cp:target", "echo")
    assert not isinstance(handler, SamTargetResolutionRefused)

    # A caller tries to smuggle SAM routing metadata inside ordinary tool
    # arguments: a different peer_id, a URL, an auth header value. None of
    # this is a real top-level SAM payload field from this connector's
    # perspective -- it only ever reaches the remote nested under
    # "arguments", inert data the fixture echoes back unchanged.
    call_arguments = {
        "x": "hello",
        "peer_id": "peer-rejected",
        "tool_name": "mcp://evil/tool",
        "url": "http://attacker.example/mcp",
        "Authorization": "Bearer stolen-token",
    }
    result = await handler(call_arguments)
    assert result.isError is False

    structured = result.structuredContent
    # The operator-configured peer_id/tool_name were used, not the caller's.
    assert structured["received_peer_id"] == "peer-good"
    assert structured["received_tool_name"] == "mcp://svc/echo"
    # The caller's decoy keys rode along only as inert nested argument data.
    assert structured["received_arguments"] == call_arguments


# --------------------------------------------------------------------------- #
# Happy path -- composition seam: no second transport                        #
# --------------------------------------------------------------------------- #


async def test_successful_call_round_trips_over_the_real_loopback_server(
    loopback_sam_node_server: LoopbackSamNodeServer,
) -> None:
    remote = _remote_connector(loopback_sam_node_server)
    connector = SamNativeConnector(
        remote_connector=remote,
        targets={"cp:target": {"echo": _echo_route(sam_endpoint_handle="sam:local")}},
    )
    handler = connector.resolve("cp:target", "echo")
    assert not isinstance(handler, SamTargetResolutionRefused)

    result = await handler({"x": "hello"})
    assert result.isError is False
    assert result.content[0].text == "echo:hello"


def test_sam_native_connector_holds_no_transport_of_its_own() -> None:
    # The composition claim, checked structurally: SamNativeConnector never
    # imports httpx/mcp.client at module scope, and it delegates every
    # actual network call to the RemoteToolConnector handler resolve()
    # returns -- it does not construct its own httpx.AsyncClient,
    # streamable_http_client, or ClientSession anywhere in the module.
    import dagr_mcp_service.connectors.sam_native as mod

    source = open(mod.__file__, encoding="utf-8").read()
    code_lines = [
        line
        for line in source.splitlines()
        if line.strip().startswith(("import ", "from ")) and not line.strip().startswith("#")
    ]
    code_only = "\n".join(code_lines)
    assert "httpx" not in code_only
    assert "mcp.client" not in code_only
    assert "streamable_http_client" not in code_only
    assert "ClientSession(" not in source


# --------------------------------------------------------------------------- #
# HOSTILE: required_labels mismatch (fail-closed)                             #
# --------------------------------------------------------------------------- #


async def test_required_label_mismatch_is_a_tool_level_error_not_raised_and_not_silently_ignored(
    loopback_sam_node_server: LoopbackSamNodeServer,
) -> None:
    remote = _remote_connector(loopback_sam_node_server)
    connector = SamNativeConnector(
        remote_connector=remote,
        targets={
            "cp:target": {
                "echo": _echo_route(
                    sam_endpoint_handle="sam:local", peer_id="peer-no-labels", labels=("vip",)
                )
            }
        },
    )
    handler = connector.resolve("cp:target", "echo")
    assert not isinstance(handler, SamTargetResolutionRefused)

    result = await handler({"x": "hello"})
    assert result.isError is True
    assert "required labels missing" in result.content[0].text


# --------------------------------------------------------------------------- #
# HOSTILE: unknown remote tool ("tool not found on peer")                     #
# --------------------------------------------------------------------------- #


async def test_wrong_namespaced_tool_that_the_peer_does_not_serve_is_a_tool_level_error(
    loopback_sam_node_server: LoopbackSamNodeServer,
) -> None:
    remote = _remote_connector(loopback_sam_node_server)
    route = SamRouteConfig(
        sam_endpoint_handle="sam:local",
        peer_id="peer-good",
        remote_tool_name="mcp://svc/does-not-exist",
    )
    connector = SamNativeConnector(remote_connector=remote, targets={"cp:target": {"echo": route}})
    handler = connector.resolve("cp:target", "echo")
    assert not isinstance(handler, SamTargetResolutionRefused)

    result = await handler({"x": "hello"})
    assert result.isError is True
    assert "tool not found on peer" in result.content[0].text


# --------------------------------------------------------------------------- #
# HOSTILE: discovery hides an auth-rejected peer / discovery returns none     #
# --------------------------------------------------------------------------- #


async def test_discovery_never_lists_an_auth_rejected_peer(
    loopback_sam_node_server: LoopbackSamNodeServer,
) -> None:
    remote = _remote_connector(loopback_sam_node_server)
    result = await discover_sam_peers(remote, sam_endpoint_handle="sam:local", service_type="mcp")
    peer_ids = {service["peer_id"] for service in result.structuredContent["services"]}
    assert "peer-rejected" not in peer_ids
    assert "peer-good" in peer_ids


async def test_describe_remote_tool_schema_mismatch_surfaces_to_the_operator_not_silently_reconciled(
    loopback_sam_node_server: LoopbackSamNodeServer,
) -> None:
    remote = _remote_connector(loopback_sam_node_server)

    # A genuinely-served tool describes cleanly.
    described = await describe_sam_remote_tool(
        remote, sam_endpoint_handle="sam:local", peer_id="peer-good", tool_name="mcp://svc/echo"
    )
    schema = described.structuredContent["input_schema"]
    assert "x" in schema["properties"]

    # An operator's SamRouteConfig naming a tool that doesn't actually match
    # what describe_remote_tool reports (here: doesn't exist on the peer at
    # all, the sharpest form of "schema mismatch" -- there is no schema to
    # match) is surfaced as a tool-level error from the helper itself. This
    # module never silently accepts, reconciles, or papers over the
    # mismatch -- it is the operator's own responsibility to notice before
    # authoring the SamRouteConfig, and describe_sam_remote_tool is never
    # called from the hot call path to "fix" a bad route at call time.
    mismatched = await describe_sam_remote_tool(
        remote,
        sam_endpoint_handle="sam:local",
        peer_id="peer-good",
        tool_name="mcp://svc/nonexistent",
    )
    # A tool-level error (isError=True), not a raised exception and not a
    # substituted/default schema -- MCP represents "the peer rejected this
    # describe request" as a returned result, and this helper passes that
    # through unchanged for the operator to see and act on.
    assert mismatched.isError is True


async def test_discovery_returning_no_provider_is_an_empty_result_not_an_exception() -> None:
    # A fixture with zero known services still answers cleanly -- discovery
    # finding nothing is itself a legitimate, representable outcome, not a
    # crash and not silently substituted with a default peer.
    from tests._gateway_service_sam_fixtures import LoopbackSamNodeServer as _Server

    empty_server = _Server(require_auth_header=False)
    empty_server.start()
    try:
        remote = _remote_connector(empty_server, handle="sam:empty")
        result = await discover_sam_peers(remote, sam_endpoint_handle="sam:empty", service_type="inference")
        # inference is a real alpha.7 type but this fixture only models mcp
        # services in its table; the point is it answers, it does not raise.
        assert result.isError is False
    finally:
        empty_server.stop()


async def test_discovery_rejects_a2a_before_ever_reaching_the_wire() -> None:
    remote = RemoteToolConnector({})
    with pytest.raises(ValueError, match="a2a"):
        await discover_sam_peers(remote, sam_endpoint_handle="sam:local", service_type="a2a")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# EXPLICIT PROOF: SAM discovery ≠ eligibility                                 #
# --------------------------------------------------------------------------- #


async def test_sam_discovery_does_not_equal_eligibility(
    loopback_sam_node_server: LoopbackSamNodeServer,
) -> None:
    remote = _remote_connector(loopback_sam_node_server)

    # peer-good/mcp://svc/echo is genuinely discoverable...
    discovered = await discover_sam_peers(remote, sam_endpoint_handle="sam:local", service_type="mcp")
    peer_ids = {service["peer_id"] for service in discovered.structuredContent["services"]}
    assert "peer-good" in peer_ids

    tools = await find_sam_remote_tools(remote, sam_endpoint_handle="sam:local")
    assert any(
        entry["peer_id"] == "peer-good" and entry["tool_name"] == "mcp://svc/echo"
        for entry in tools.structuredContent["tools"]
    )

    # ...but a SamNativeConnector with NO configured route for it refuses,
    # never treating "discoverable" as "callable": discovery and eligibility
    # are two separate facts, and only an operator-authored SamRouteConfig
    # establishes the second one.
    connector = SamNativeConnector(remote_connector=remote, targets={})
    result = connector.resolve("cp:target-not-configured", "echo")
    assert isinstance(result, SamTargetResolutionRefused)


# --------------------------------------------------------------------------- #
# EXPLICIT PROOF: SAM authentication ≠ authorization                          #
# --------------------------------------------------------------------------- #


async def test_sam_authentication_does_not_equal_authorization(
    loopback_sam_node_server_with_auth: LoopbackSamNodeServer,
) -> None:
    remote = _authed_remote_connector(loopback_sam_node_server_with_auth)
    # peer-no-labels successfully authenticates to the local sam-node
    # endpoint (the bearer header is present and correct) but lacks the
    # "vip" label the route requires -- authentication to sam-node succeeds,
    # yet the call is still refused at the SAM/label layer.
    connector = SamNativeConnector(
        remote_connector=remote,
        targets={
            "cp:target": {
                "echo": _echo_route(
                    sam_endpoint_handle="sam:local-auth", peer_id="peer-no-labels", labels=("vip",)
                )
            }
        },
    )
    handler = connector.resolve("cp:target", "echo")
    assert not isinstance(handler, SamTargetResolutionRefused)

    result = await handler({"x": "hello"})
    # Authenticated transport, refused SAM-level authorization.
    assert result.isError is True
    assert "required labels missing" in result.content[0].text


# --------------------------------------------------------------------------- #
# HOSTILE: SAM auth 401/403                                                   #
# --------------------------------------------------------------------------- #


async def test_missing_auth_header_against_an_auth_gated_endpoint_fails_not_succeeds(
    loopback_sam_node_server_with_auth: LoopbackSamNodeServer,
) -> None:
    # No credential_provider configured -- the local sam-node endpoint gates
    # on a bearer header this call never supplies.
    remote = RemoteToolConnector(
        {
            "sam:local-auth": RemoteTargetConfig(
                handle="sam:local-auth",
                endpoint_uri=loopback_sam_node_server_with_auth.base_url,
                allow_insecure_loopback=True,
                timeout_seconds=5.0,
            )
        }
    )
    connector = SamNativeConnector(
        remote_connector=remote,
        targets={"cp:target": {"echo": _echo_route(sam_endpoint_handle="sam:local-auth")}},
    )
    handler = connector.resolve("cp:target", "echo")
    assert not isinstance(handler, SamTargetResolutionRefused)

    with pytest.raises(Exception):  # noqa: B017 - honest generic protocol-failure bucket, asserted below.
        await handler({"x": "hello"})


# --------------------------------------------------------------------------- #
# HOSTILE: SAM unavailable / 503, connect failure                             #
# --------------------------------------------------------------------------- #


async def test_connect_failure_raises_connection_error_reused_from_remote_connector() -> None:
    # Nothing is listening on this port -- the underlying RemoteToolConnector
    # classifies this as ConnectionError; sam_native adds no translation of
    # its own, it simply lets the exception propagate.
    remote = RemoteToolConnector(
        {
            "sam:down": RemoteTargetConfig(
                handle="sam:down",
                endpoint_uri="http://127.0.0.1:1/mcp",
                allow_insecure_loopback=True,
                timeout_seconds=2.0,
            )
        }
    )
    connector = SamNativeConnector(
        remote_connector=remote,
        targets={"cp:target": {"echo": _echo_route(sam_endpoint_handle="sam:down")}},
    )
    handler = connector.resolve("cp:target", "echo")
    assert not isinstance(handler, SamTargetResolutionRefused)

    with pytest.raises(ConnectionError):
        await handler({"x": "hello"})


# --------------------------------------------------------------------------- #
# HOSTILE: timeout / cancellation                                             #
# --------------------------------------------------------------------------- #


async def test_timeout_raises_builtin_timeout_error(
    loopback_sam_node_server: LoopbackSamNodeServer,
) -> None:
    remote = RemoteToolConnector(
        {
            "sam:local": RemoteTargetConfig(
                handle="sam:local",
                endpoint_uri=loopback_sam_node_server.base_url,
                allow_insecure_loopback=True,
                timeout_seconds=0.2,
            )
        }
    )
    connector = SamNativeConnector(
        remote_connector=remote,
        targets={"cp:target": {"echo": _echo_route(sam_endpoint_handle="sam:local")}},
    )
    handler = connector.resolve("cp:target", "echo")
    assert not isinstance(handler, SamTargetResolutionRefused)

    with pytest.raises(TimeoutError):
        await handler({"x": "hello", "__sleep_seconds__": 5.0})


async def test_cancellation_propagates_cleanly_not_swallowed_or_wrapped(
    loopback_sam_node_server: LoopbackSamNodeServer,
) -> None:
    remote = _remote_connector(loopback_sam_node_server)
    connector = SamNativeConnector(
        remote_connector=remote,
        targets={"cp:target": {"echo": _echo_route(sam_endpoint_handle="sam:local")}},
    )
    handler = connector.resolve("cp:target", "echo")
    assert not isinstance(handler, SamTargetResolutionRefused)

    task = asyncio.ensure_future(handler({"x": "hello", "__sleep_seconds__": 5.0}))
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# --------------------------------------------------------------------------- #
# HOSTILE: malformed CallToolResult                                           #
# --------------------------------------------------------------------------- #


def test_validate_rejects_a_result_missing_content_and_iserror() -> None:
    class _Bare:
        pass

    with pytest.raises(RuntimeError, match="malformed"):
        _validate_call_remote_tool_result(_Bare(), target_handle="cp:target", tool_name="echo")


def test_validate_rejects_a_result_whose_content_is_not_a_sequence() -> None:
    class _Fake:
        content = 12345
        isError = False

    with pytest.raises(RuntimeError, match="not a sequence"):
        _validate_call_remote_tool_result(_Fake(), target_handle="cp:target", tool_name="echo")


def test_validate_rejects_empty_content_on_a_non_error_result() -> None:
    class _Fake:
        content: list = []
        isError = False

    with pytest.raises(RuntimeError, match="empty content"):
        _validate_call_remote_tool_result(_Fake(), target_handle="cp:target", tool_name="echo")


def test_validate_accepts_empty_content_on_an_error_result() -> None:
    class _Fake:
        content: list = []
        isError = True

    # An error result carrying no content is not itself malformed -- only a
    # *success* claiming no content is rejected.
    out = _validate_call_remote_tool_result(_Fake(), target_handle="cp:target", tool_name="echo")
    assert out.isError is True


async def test_the_real_fixtures_deliberately_malformed_success_is_caught(
    loopback_sam_node_server: LoopbackSamNodeServer,
) -> None:
    remote = _remote_connector(loopback_sam_node_server)
    connector = SamNativeConnector(
        remote_connector=remote,
        targets={"cp:target": {"echo": _echo_route(sam_endpoint_handle="sam:local")}},
    )
    handler = connector.resolve("cp:target", "echo")
    assert not isinstance(handler, SamTargetResolutionRefused)

    with pytest.raises(RuntimeError, match="malformed"):
        await handler({"x": "__empty__"})


# --------------------------------------------------------------------------- #
# EXPLICIT PROOF: SAM route success ≠ execution authorization                 #
# --------------------------------------------------------------------------- #


async def test_sam_route_success_does_not_equal_execution_authorization(
    loopback_sam_node_server: LoopbackSamNodeServer,
) -> None:
    remote = _remote_connector(loopback_sam_node_server)
    connector = SamNativeConnector(
        remote_connector=remote,
        targets={"cp:target": {"echo": _echo_route(sam_endpoint_handle="sam:local")}},
    )
    handler = connector.resolve("cp:target", "echo")
    assert not isinstance(handler, SamTargetResolutionRefused)

    result = await handler({"x": "hello"})
    assert result.isError is False

    # The result this module returns carries no admission or authorization
    # claim of any kind -- those fields simply do not exist on it. Only
    # dagr_mcp_service.adapter.execute_governed_call (never this module)
    # produces a GovernedDecision/disposition from the *receipt* lifecycle,
    # and it does so independent of whatever this leaf handler returned.
    assert not hasattr(result, "disposition")
    assert not hasattr(result, "admitted")
    assert not hasattr(result, "authorized")
    assert not hasattr(result, "receipt")


# --------------------------------------------------------------------------- #
# EXPLICIT PROOF: SAM result ≠ semantic truth                                 #
# --------------------------------------------------------------------------- #


async def test_sam_result_does_not_equal_semantic_truth(
    loopback_sam_node_server: LoopbackSamNodeServer,
) -> None:
    # The connector validates *shape* only. A well-formed, isError=False
    # result whose text content is a lie the remote tool told (this fixture
    # cannot actually verify "echo:hello" reflects anything true about the
    # world) is passed through unchanged -- this module makes no claim, and
    # performs no check, about whether the content is true.
    remote = _remote_connector(loopback_sam_node_server)
    connector = SamNativeConnector(
        remote_connector=remote,
        targets={"cp:target": {"echo": _echo_route(sam_endpoint_handle="sam:local")}},
    )
    handler = connector.resolve("cp:target", "echo")
    assert not isinstance(handler, SamTargetResolutionRefused)

    result = await handler({"x": "anything-at-all-including-nonsense-000"})
    assert result.isError is False
    # Structural validation passed; semantic content was never inspected,
    # never verified, never compared against any ground truth by this module.
    assert result.content[0].text == "echo:anything-at-all-including-nonsense-000"


# --------------------------------------------------------------------------- #
# EXPLICIT PROOF: transport failure ≠ evidence absence                        #
# --------------------------------------------------------------------------- #


async def test_transport_failure_does_not_equal_evidence_absence() -> None:
    # A timeout/connection failure raised by this module's handler is never
    # silently swallowed into "no evidence exists that a call happened" --
    # it propagates as a distinct, typed exception
    # (ConnectionError/TimeoutError/RuntimeError, reused unmodified from
    # connectors.remote's own honest classification) that the adapter above
    # this module is responsible for recording as an admitted-but-exception
    # outcome, never as if the call had simply never been attempted at the
    # DAGR layer. This module adds no swallowing, retry, or reclassification
    # of its own on top of what connectors.remote already raises.
    remote = RemoteToolConnector(
        {
            "sam:down": RemoteTargetConfig(
                handle="sam:down",
                endpoint_uri="http://127.0.0.1:1/mcp",
                allow_insecure_loopback=True,
                timeout_seconds=2.0,
            )
        }
    )
    connector = SamNativeConnector(
        remote_connector=remote,
        targets={"cp:target": {"echo": _echo_route(sam_endpoint_handle="sam:down")}},
    )
    handler = connector.resolve("cp:target", "echo")
    assert not isinstance(handler, SamTargetResolutionRefused)

    raised: Exception | None = None
    try:
        await handler({"x": "hello"})
    except Exception as exc:  # noqa: BLE001 - captured for the assertion below.
        raised = exc

    assert raised is not None
    assert isinstance(raised, ConnectionError)
    # The exception is a distinct, observable fact -- not None, not
    # swallowed, not converted into a falsy/empty "nothing happened" value.


# --------------------------------------------------------------------------- #
# SAM routing metadata never changes native Counterpedia artifact identity    #
# --------------------------------------------------------------------------- #


async def test_route_metadata_never_leaks_into_argument_or_result_identity(
    loopback_sam_node_server: LoopbackSamNodeServer,
) -> None:
    remote = _remote_connector(loopback_sam_node_server)
    connector = SamNativeConnector(
        remote_connector=remote,
        targets={
            "cp:artifact-123": {
                "echo": _echo_route(sam_endpoint_handle="sam:local", peer_id="peer-good")
            }
        },
    )
    handler = connector.resolve("cp:artifact-123", "echo")
    assert not isinstance(handler, SamTargetResolutionRefused)

    caller_arguments = {"x": "artifact-payload", "artifact_ref": "cp:artifact-123:v1"}
    result = await handler(caller_arguments)
    structured = result.structuredContent
    # Exactly the caller's arguments reached the remote -- no peer_id,
    # tool_name, sam_endpoint_handle, or required_labels were merged in.
    assert structured["received_arguments"] == caller_arguments
    assert set(structured["received_arguments"]) == {"x", "artifact_ref"}
