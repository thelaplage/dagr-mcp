"""Frozen deterministic recipe for MCP Record Custody Gateway projections.

Characterization helper for Sprint A1. It drives the real, unmodified
``dagr_mcp.mcp_record_custody_gateway`` contract with a pinned ``observed_at`` so
the refs-only projection body and its deterministic ``gateway_hash`` are
reproducible and committable. No semantics are changed.

Coverage:

* one projection for each of the nine canonical custody observation statuses;
* every boundary type and receipt family the v0.1 contract binds to;
* the two registered ``agent_delegation`` body kinds carried in refs-only
  ``extensions.garp.body`` content.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dagr_mcp.mcp_record_custody_gateway import (
    GatewayCustodyStatus,
    build_mcp_record_custody_gateway,
)

FREEZE_OBSERVED_AT = "2026-07-13T00:00:00Z"


@dataclass(frozen=True)
class FrozenGateway:
    name: str
    body: dict[str, Any]


def _build(name: str, **kwargs: Any) -> FrozenGateway:
    kwargs.setdefault("observed_at", FREEZE_OBSERVED_AT)
    kwargs.setdefault("generated_by", "binding:behavioral-freeze")
    return FrozenGateway(name=name, body=build_mcp_record_custody_gateway(**kwargs))


def generate_frozen_gateways() -> list[FrozenGateway]:
    """Build the full frozen custody-projection set (deterministic bodies)."""

    out: list[FrozenGateway] = []

    # One projection per custody observation status (item 9 vocabulary).
    for status in GatewayCustodyStatus:
        out.append(
            _build(
                f"status-{status.value}",
                gateway_event_id=f"gw:freeze:{status.value}",
                record_candidate_ref="rc:freeze:1",
                boundary_type="mcp_tool_call",
                receipt_family="sdk_enforcement",
                custody_status=status.value,
                actor_ref="actor:freeze:1",
                target_ref="tool:freeze:1",
            )
        )

    # Boundary-type coverage.
    for boundary in (
        "mcp_tool_call",
        "mcp_resource_read",
        "mcp_prompt_retrieval",
        "agent_delegation",
    ):
        out.append(
            _build(
                f"boundary-{boundary}",
                gateway_event_id=f"gw:freeze:boundary:{boundary}",
                record_candidate_ref="rc:freeze:2",
                boundary_type=boundary,
                receipt_family="sdk_enforcement",
                actor_ref="actor:freeze:1",
                target_ref="target:freeze:1",
            )
        )

    # Receipt-family coverage.
    for family in ("connection", "provenance", "sdk_enforcement"):
        out.append(
            _build(
                f"family-{family}",
                gateway_event_id=f"gw:freeze:family:{family}",
                record_candidate_ref="rc:freeze:3",
                boundary_type="mcp_tool_call",
                receipt_family=family,
                actor_ref="actor:freeze:1",
                target_ref="tool:freeze:1",
            )
        )

    # The two registered agent_delegation body kinds, carried refs-only.
    for body_kind in ("agent_delegation_issued", "agent_delegation_revoked"):
        out.append(
            _build(
                f"body-{body_kind}",
                gateway_event_id=f"gw:freeze:body:{body_kind}",
                record_candidate_ref="rc:freeze:4",
                boundary_type="agent_delegation",
                receipt_family="provenance",
                actor_ref="actor:freeze:1",
                delegated_credential_ref="cred:freeze:1",
                extensions={"garp": {"body": {"body_kind": body_kind}}},
            )
        )

    return out
