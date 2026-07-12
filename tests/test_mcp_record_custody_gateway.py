from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from dagr_mcp.mcp_record_custody_gateway import (
    MCP_RECORD_CUSTODY_GATEWAY_KIND,
    MCP_RECORD_CUSTODY_GATEWAY_SCHEMA,
    MCP_RECORD_CUSTODY_GATEWAY_VOCABULARY,
    AGENT_DELEGATION_BODY_KINDS,
    GatewayBoundaryType,
    GatewayCustodyStatus,
    GatewayProtocolBinding,
    GatewayReceiptFamily,
    MCPRecordCustodyGateway,
    MCPRecordCustodyGatewayError,
    build_mcp_record_custody_gateway,
    mcp_record_custody_gateway_hash,
)


def _kwargs(**overrides):
    base = {
        "gateway_event_id": "gateway_event:syn-001",
        "record_candidate_ref": "record_candidate:syn-001",
        "generated_by": "garp-sdk-test",
        "boundary_type": GatewayBoundaryType.MCP_TOOL_CALL,
        "receipt_family": GatewayReceiptFamily.PROVENANCE,
        "protocol_binding": GatewayProtocolBinding.MCP,
        "custody_status": GatewayCustodyStatus.CUSTODY_RECORD_READY,
        "observed_at": "2026-05-25T22:00:00Z",
    }
    base.update(overrides)
    return base


def test_minimal_gateway_is_refs_only_and_non_admitting() -> None:
    projection = build_mcp_record_custody_gateway(**_kwargs())

    assert projection["schema_version"] == MCP_RECORD_CUSTODY_GATEWAY_SCHEMA
    assert projection["gateway_kind"] == MCP_RECORD_CUSTODY_GATEWAY_KIND
    assert projection["gateway_event_id"] == "gateway_event:syn-001"
    assert projection["record_candidate_ref"] == "record_candidate:syn-001"
    assert projection["boundary_type"] == "mcp_tool_call"
    assert projection["receipt_family"] == "provenance"
    assert projection["protocol_binding"] == "mcp"
    assert projection["custody_status"] == "custody_record_ready"
    assert projection["gateway_vocabulary"] == list(
        MCP_RECORD_CUSTODY_GATEWAY_VOCABULARY
    )

    assert projection["raw_payload_excluded"] is True
    assert projection["private_path_redacted"] is True
    assert projection["tool_arguments_excluded"] is True
    assert projection["credential_secret_excluded"] is True

    assert projection["record_admission_claimed"] is False
    assert projection["mcp_protocol_modified"] is False
    assert projection["mcp_authority_granted"] is False
    assert projection["model_output_verified"] is False

    assert projection["gateway_hash"].startswith("sha256:")
    assert projection["gateway_hash"] == mcp_record_custody_gateway_hash(projection)


def test_full_gateway_with_reference_families() -> None:
    projection = build_mcp_record_custody_gateway(
        **_kwargs(
            actor_ref="actor:operator-1",
            target_ref="tool:search/v1",
            session_ref="session:agent-7",
            boundary_ref="boundary:mcp-server-1",
            trace_context_ref="trace_context:syn-001",
            bridge_ref="trace-bridge:syn-001",
            user_context_ref="user_context:operator-1",
            delegated_credential_ref="credential:delegation-abc",
            policy_outcome_ref="policy_outcome:allow",
            request_hash="sha256:aaaa",
            response_hash="sha256:bbbb",
            output_ref="custody_record_candidate:1",
            span_refs=["span:root", "span:child"],
            event_refs=["event:tool_call_open", "event:tool_call_close"],
            receipt_refs=["sdk_enforcement_receipt:1"],
            linkage_refs=["linkage:credential-abc"],
            extensions={"source": "synthetic-fixture", "version": 1},
        )
    )

    assert projection["actor_ref"] == "actor:operator-1"
    assert projection["target_ref"] == "tool:search/v1"
    assert projection["delegated_credential_ref"] == "credential:delegation-abc"
    assert projection["span_refs"] == ["span:root", "span:child"]
    assert projection["linkage_refs"] == ["linkage:credential-abc"]
    assert projection["extensions"] == {"source": "synthetic-fixture", "version": 1}


def test_json_round_trip_is_stable() -> None:
    obj = MCPRecordCustodyGateway(
        **_kwargs(
            receipt_family="connection",
            custody_status="custody_record_partial",
            span_refs=["span:1"],
            extensions={"alpha": 1},
        )
    )

    once = obj.to_dict()
    twice = MCPRecordCustodyGateway.from_dict(once).to_dict()
    from_json = MCPRecordCustodyGateway.from_json(obj.to_json()).to_dict()

    assert once == twice
    assert once == from_json
    assert once["gateway_hash"] == mcp_record_custody_gateway_hash(once)


def test_hash_is_deterministic_and_content_sensitive() -> None:
    first = build_mcp_record_custody_gateway(**_kwargs())
    second = build_mcp_record_custody_gateway(**_kwargs())
    changed = build_mcp_record_custody_gateway(
        **_kwargs(record_candidate_ref="record_candidate:syn-002")
    )

    assert first == second
    assert changed["gateway_hash"] != first["gateway_hash"]


def test_all_boundary_types_serialize() -> None:
    for boundary in (
        "mcp_tool_call",
        "mcp_resource_read",
        "mcp_prompt_retrieval",
        "agent_delegation",
    ):
        projection = build_mcp_record_custody_gateway(
            **_kwargs(boundary_type=boundary)
        )
        assert projection["boundary_type"] == boundary


def test_all_receipt_families_serialize() -> None:
    for family in ("connection", "provenance", "sdk_enforcement"):
        projection = build_mcp_record_custody_gateway(
            **_kwargs(receipt_family=family)
        )
        assert projection["receipt_family"] == family


def test_all_nine_custody_statuses_serialize() -> None:
    expected = {
        "custody_record_ready",
        "custody_record_partial",
        "trace_only",
        "unsupported_boundary_type",
        "missing_actor_context",
        "missing_target_context",
        "privacy_blocked",
        "policy_refused",
        "needs_review",
    }
    seen = set()
    for status in expected:
        projection = build_mcp_record_custody_gateway(**_kwargs(custody_status=status))
        seen.add(projection["custody_status"])
    assert seen == expected
    assert {member.value for member in GatewayCustodyStatus} == expected


def test_agent_delegation_boundary_with_auth_md_binding() -> None:
    projection = build_mcp_record_custody_gateway(
        **_kwargs(
            boundary_type="agent_delegation",
            receipt_family="sdk_enforcement",
            protocol_binding="auth_md",
            delegated_credential_ref="credential:auth_md-12345",
            extensions={"auth_md": {"credential_id": "credential:auth_md-12345"}},
        )
    )
    assert projection["boundary_type"] == "agent_delegation"
    assert projection["protocol_binding"] == "auth_md"
    assert projection["delegated_credential_ref"] == "credential:auth_md-12345"
    assert (
        projection["extensions"]["auth_md"]["credential_id"]
        == "credential:auth_md-12345"
    )


def test_allows_registered_agent_delegation_body_kinds() -> None:
    for body_kind in AGENT_DELEGATION_BODY_KINDS:
        projection = build_mcp_record_custody_gateway(
            **_kwargs(
                boundary_type="agent_delegation",
                receipt_family="connection",
                protocol_binding="auth_md",
                delegated_credential_ref="credential:delegation-abc",
                extensions={"garp": {"body": {"body_kind": body_kind}}},
            )
        )

        assert projection["boundary_type"] == "agent_delegation"
        assert projection["protocol_binding"] == "auth_md"
        assert projection["extensions"]["garp"]["body"]["body_kind"] == body_kind


def test_rejects_admission_protocol_authority_and_verification_claims() -> None:
    for field_name, message in (
        ("record_admission_claimed", "record_admission_claimed must be False"),
        ("mcp_protocol_modified", "mcp_protocol_modified must be False"),
        ("mcp_authority_granted", "mcp_authority_granted must be False"),
        ("model_output_verified", "model_output_verified must be False"),
    ):
        with pytest.raises(MCPRecordCustodyGatewayError, match=message):
            build_mcp_record_custody_gateway(**_kwargs(**{field_name: True}))


def test_rejects_false_exclusion_flags() -> None:
    for field_name, message in (
        ("raw_payload_excluded", "raw_payload_excluded must be True"),
        ("private_path_redacted", "private_path_redacted must be True"),
        ("tool_arguments_excluded", "tool_arguments_excluded must be True"),
        ("credential_secret_excluded", "credential_secret_excluded must be True"),
    ):
        with pytest.raises(MCPRecordCustodyGatewayError, match=message):
            build_mcp_record_custody_gateway(**_kwargs(**{field_name: False}))


def test_rejects_private_paths_anywhere() -> None:
    with pytest.raises(
        MCPRecordCustodyGatewayError, match="private reference marker"
    ):
        build_mcp_record_custody_gateway(
            **_kwargs(target_ref="file:///Users/operator/tool.json")
        )

    with pytest.raises(
        MCPRecordCustodyGatewayError, match="private reference marker"
    ):
        build_mcp_record_custody_gateway(
            **_kwargs(extensions={"path": "/private/matter/trace.json"})
        )


def test_rejects_raw_payload_keys() -> None:
    for raw_key in (
        "prompt",
        "transcript",
        "model_output",
        "tool_arguments",
        "request_body",
        "response_headers",
        "raw_payload",
    ):
        with pytest.raises(
            MCPRecordCustodyGatewayError, match="raw/private payload"
        ):
            build_mcp_record_custody_gateway(
                **_kwargs(extensions={raw_key: "not allowed"})
            )


def test_rejects_credential_secret_keys() -> None:
    for secret_key in (
        "credential_secret",
        "client_secret",
        "access_token",
        "refresh_token",
        "id_token",
        "bearer_token",
        "api_key",
        "private_key",
        "password",
    ):
        with pytest.raises(
            MCPRecordCustodyGatewayError, match="credential secret"
        ):
            build_mcp_record_custody_gateway(
                **_kwargs(extensions={secret_key: "not allowed"})
            )


def test_serialized_gateway_contains_no_private_payload_markers() -> None:
    projection = build_mcp_record_custody_gateway(
        **_kwargs(
            span_refs=["span:1"],
            event_refs=["event:1"],
            extensions={"safe_label": "synthetic"},
        )
    )
    rendered = json.dumps(projection, sort_keys=True)

    assert "/Users/" not in rendered
    assert "/private/" not in rendered
    assert "query_logs/" not in rendered
    assert "prompt_text" not in rendered
    assert "\"tool_arguments\"" not in rendered
    assert "\"client_secret\"" not in rendered
    assert "\"access_token\"" not in rendered


def test_schema_and_enum_guards_are_stable() -> None:
    with pytest.raises(
        MCPRecordCustodyGatewayError, match="schema_version must be"
    ):
        build_mcp_record_custody_gateway(
            **_kwargs(schema_version="garp.mcp_record_custody_gateway.v9")
        )

    with pytest.raises(MCPRecordCustodyGatewayError, match="boundary_type must be"):
        build_mcp_record_custody_gateway(**_kwargs(boundary_type="runtime_call"))

    with pytest.raises(MCPRecordCustodyGatewayError, match="receipt_family must be"):
        build_mcp_record_custody_gateway(**_kwargs(receipt_family="grace_session"))

    with pytest.raises(MCPRecordCustodyGatewayError, match="custody_status must be"):
        build_mcp_record_custody_gateway(**_kwargs(custody_status="ready"))


def test_required_fields_are_non_empty() -> None:
    for field_name in ("gateway_event_id", "record_candidate_ref", "generated_by"):
        with pytest.raises(
            MCPRecordCustodyGatewayError, match="must be a non-empty string"
        ):
            build_mcp_record_custody_gateway(**_kwargs(**{field_name: ""}))


def test_module_has_no_monolith_or_runtime_dependency() -> None:
    module = importlib.import_module("dagr_mcp.mcp_record_custody_gateway")
    source = module.__loader__.get_source(module.__name__)  # type: ignore[union-attr]
    assert source is not None

    for forbidden in (
        "garp_core",
        "garp_local",
        "garp_doctrine",
        "arcs_amnesiac",
        "arcs_anchor",
        "garp_boundary",
        "fastapi",
        "requests",
        "httpx",
    ):
        assert forbidden not in source, f"source references {forbidden!r}"

    assert "import opentelemetry" not in source
    assert "from opentelemetry" not in source

    forbidden_roots = (
        "garp_core",
        "garp_local",
        "garp_doctrine",
        "arcs_amnesiac",
        "arcs_anchor",
        "garp_boundary",
    )
    leaked = sorted(
        name for name in sys.modules if name.split(".", 1)[0] in forbidden_roots
    )
    assert not leaked, f"import leaked forbidden modules: {leaked}"


def test_module_source_performs_no_filesystem_io() -> None:
    source_path = Path(importlib.import_module(
        "dagr_mcp.mcp_record_custody_gateway"
    ).__file__)
    text = source_path.read_text(encoding="utf-8")

    assert ".write_text(" not in text
    assert ".write_bytes(" not in text
    assert "open(" not in text
    assert "Path(" not in text
