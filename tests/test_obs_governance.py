"""Tests for dagr_obs_governance — OBS broadcast control governance module.

These tests verify:
1. Admitted action reaches downstream exactly once.
2. Refused action (hard deny) reaches downstream zero times.
3. Post-revocation action reaches downstream zero times.
4. Out-of-scope subject is refused.
5. Payload binding: target_state in receipt is a hash, not raw.
6. Raw content never enters the receipt.
7. Mid-session revocation: two calls, revoke between them.
8. Out-of-scope operation family.
9. Consequence linker returns observed_consequence receipt with hash ref.
10. Validity window: expired delegation is refused.

No imports of mcp, fastmcp, or obs-mcp are used — tests run without them.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from dagr_obs_governance.consequence_linker import link_consequence
from dagr_obs_governance.delegation import BroadcastDelegation
from dagr_obs_governance.governance import run_obs_governed_call
from dagr_obs_governance.policy import (
    ALLOWED_MIXED_OPS,
    ALLOWED_SCENE_OPS,
    HARD_DENY_OPS,
    HIGHER_SCOPE_OPS,
    evaluate_policy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _past_iso(days: int = 1) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.isoformat().replace("+00:00", "Z")


def _future_iso(days: int = 1) -> str:
    dt = datetime.now(timezone.utc) + timedelta(days=days)
    return dt.isoformat().replace("+00:00", "Z")


def _make_delegation(
    *,
    operation_family: frozenset[str] | None = None,
    subject_ids: frozenset[str] | None = None,
    revoked: bool = False,
    valid_from: str | None = None,
    valid_until: str | None = None,
) -> BroadcastDelegation:
    if operation_family is None:
        # Default: scene ops + mixed ops (but NOT stop-stream which is hard-denied)
        operation_family = ALLOWED_SCENE_OPS | ALLOWED_MIXED_OPS
    return BroadcastDelegation(
        delegation_id="delegation:test:001",
        actor_ref="actor:agent/demo-broadcaster",
        obs_instance_ref="obs:local/default",
        scene_collection=None,
        operation_family=operation_family,
        subject_ids=subject_ids,
        valid_from=valid_from or _past_iso(1),
        valid_until=valid_until or _future_iso(1),
        revoked=revoked,
    )


class _DownstreamCounter:
    """Fake downstream callable that counts invocations."""

    def __init__(self, result: Any = None) -> None:
        self.count = 0
        self._result = result or {"obs_status": "ok"}

    def __call__(self, op_name: str, arguments: dict) -> Any:
        self.count += 1
        return self._result


# ---------------------------------------------------------------------------
# Test 1: Admitted action reaches downstream exactly once
# ---------------------------------------------------------------------------

def test_admitted_action_reaches_downstream_exactly_once() -> None:
    delegation = _make_delegation()
    downstream = _DownstreamCounter()

    result = run_obs_governed_call(
        delegation=delegation,
        op_name="set-current-scene",
        subject_id="Scene A",
        arguments={"sceneName": "Scene A"},
        downstream_fn=downstream,
    )

    assert result.downstream_invocation_count == 1, (
        f"Expected downstream called once; got {result.downstream_invocation_count}"
    )
    assert result.disposition == "admitted"
    assert result.refusal_reason is None
    assert downstream.count == 1


# ---------------------------------------------------------------------------
# Test 2: Refused action (hard deny) reaches downstream zero times
# ---------------------------------------------------------------------------

def test_hard_deny_stop_stream_reaches_downstream_zero_times() -> None:
    # stop-stream is in HARD_DENY_OPS for demo delegation
    delegation = _make_delegation()
    downstream = _DownstreamCounter()

    result = run_obs_governed_call(
        delegation=delegation,
        op_name="stop-stream",
        subject_id=None,
        arguments={},
        downstream_fn=downstream,
    )

    assert result.downstream_invocation_count == 0
    assert result.disposition == "refused"
    assert result.refusal_reason is not None
    assert downstream.count == 0


def test_hard_deny_toggle_reaches_downstream_zero_times() -> None:
    delegation = _make_delegation()
    downstream = _DownstreamCounter()

    result = run_obs_governed_call(
        delegation=delegation,
        op_name="toggle-mute",
        subject_id=None,
        arguments={},
        downstream_fn=downstream,
    )

    assert result.downstream_invocation_count == 0
    assert result.disposition == "refused"
    assert downstream.count == 0


# ---------------------------------------------------------------------------
# Test 3: Post-revocation action reaches downstream zero times
# ---------------------------------------------------------------------------

def test_revoked_delegation_reaches_downstream_zero_times() -> None:
    delegation = _make_delegation(revoked=True)
    downstream = _DownstreamCounter()

    result = run_obs_governed_call(
        delegation=delegation,
        op_name="set-current-scene",
        subject_id=None,
        arguments={"sceneName": "Scene A"},
        downstream_fn=downstream,
    )

    assert result.downstream_invocation_count == 0
    assert result.disposition == "refused"
    assert "revoked" in result.refusal_reason
    assert downstream.count == 0


# ---------------------------------------------------------------------------
# Test 4: Out-of-scope subject is refused
# ---------------------------------------------------------------------------

def test_out_of_scope_subject_is_refused() -> None:
    delegation = _make_delegation(
        subject_ids=frozenset({"scene-a", "scene-b"}),
    )
    downstream = _DownstreamCounter()

    result = run_obs_governed_call(
        delegation=delegation,
        op_name="set-current-scene",
        subject_id="scene-c",
        arguments={"sceneName": "scene-c"},
        downstream_fn=downstream,
    )

    assert result.disposition == "refused"
    assert result.downstream_invocation_count == 0
    assert downstream.count == 0
    assert result.refusal_reason is not None


# ---------------------------------------------------------------------------
# Test 5: target_state in receipt is a hash, not raw
# ---------------------------------------------------------------------------

def test_target_state_in_receipt_is_a_hash_not_raw() -> None:
    delegation = _make_delegation()
    downstream = _DownstreamCounter(result={"status": "scene_changed"})

    result = run_obs_governed_call(
        delegation=delegation,
        op_name="set-current-scene",
        subject_id="Scene A",
        arguments={"sceneName": "Scene A"},
        downstream_fn=downstream,
    )

    assert result.disposition == "admitted"
    receipt = result.receipt
    assert "target_state" in receipt, "receipt must have target_state on execution kind"
    target_state = receipt["target_state"]
    assert isinstance(target_state, str), "target_state must be a string"
    assert target_state.startswith("sha256:"), (
        f"target_state must be a sha256 hash, got: {target_state!r}"
    )


# ---------------------------------------------------------------------------
# Test 6: Raw content never enters the receipt
# ---------------------------------------------------------------------------

_RAW_FIELD_PREFIXES = ("raw_",)
_FORBIDDEN_FIELDS = frozenset(
    {"arguments", "result_body", "raw_arguments", "raw_result", "stream_key",
     "password", "credentials", "raw_payload", "raw_event"}
)


def _walk_receipt(receipt: dict, path: str = "") -> list[str]:
    """Return list of forbidden field names found in the receipt."""
    violations = []
    for key, value in receipt.items():
        full_path = f"{path}.{key}" if path else key
        if key in _FORBIDDEN_FIELDS:
            violations.append(full_path)
        if any(key.startswith(prefix) for prefix in _RAW_FIELD_PREFIXES):
            violations.append(full_path)
        if isinstance(value, dict):
            violations.extend(_walk_receipt(value, path=full_path))
    return violations


def test_raw_content_never_enters_receipt_admitted() -> None:
    delegation = _make_delegation()
    downstream = _DownstreamCounter()

    result = run_obs_governed_call(
        delegation=delegation,
        op_name="set-current-scene",
        subject_id="Scene A",
        arguments={"sceneName": "Scene A", "stream_key": "secret-key-should-not-appear"},
        downstream_fn=downstream,
    )

    assert result.disposition == "admitted"
    violations = _walk_receipt(result.receipt)
    assert violations == [], f"Forbidden fields in receipt: {violations}"


def test_raw_content_never_enters_receipt_refused() -> None:
    delegation = _make_delegation()
    downstream = _DownstreamCounter()

    result = run_obs_governed_call(
        delegation=delegation,
        op_name="stop-stream",
        subject_id=None,
        arguments={"stream_key": "secret-key-should-not-appear"},
        downstream_fn=downstream,
    )

    assert result.disposition == "refused"
    violations = _walk_receipt(result.receipt)
    assert violations == [], f"Forbidden fields in receipt: {violations}"


# ---------------------------------------------------------------------------
# Test 7: Mid-session revocation: two calls, revoke between them
# ---------------------------------------------------------------------------

def test_mid_session_revocation() -> None:
    delegation = _make_delegation(revoked=False)
    downstream = _DownstreamCounter()

    # First call: admitted
    result1 = run_obs_governed_call(
        delegation=delegation,
        op_name="set-current-scene",
        subject_id=None,
        arguments={"sceneName": "Scene A"},
        downstream_fn=downstream,
    )
    assert result1.disposition == "admitted"
    assert result1.downstream_invocation_count == 1

    # Revoke the delegation (produce a new frozen delegation with revoked=True)
    revoked_delegation = dataclasses.replace(delegation, revoked=True)

    # Second call: refused (delegation is now revoked)
    result2 = run_obs_governed_call(
        delegation=revoked_delegation,
        op_name="set-current-scene",
        subject_id=None,
        arguments={"sceneName": "Scene B"},
        downstream_fn=downstream,
    )
    assert result2.disposition == "refused"
    assert result2.downstream_invocation_count == 0

    # Total downstream calls: only 1 (the first)
    assert downstream.count == 1


# ---------------------------------------------------------------------------
# Test 8: Out-of-scope operation family
# ---------------------------------------------------------------------------

def test_out_of_scope_operation_family_is_refused() -> None:
    # Delegation allows only set-current-scene
    delegation = _make_delegation(
        operation_family=frozenset({"set-current-scene"}),
    )
    downstream = _DownstreamCounter()

    result = run_obs_governed_call(
        delegation=delegation,
        op_name="set-input-mute",
        subject_id=None,
        arguments={"inputName": "Mic", "inputMuted": True},
        downstream_fn=downstream,
    )

    assert result.disposition == "refused"
    assert result.downstream_invocation_count == 0
    assert downstream.count == 0
    assert result.refusal_reason is not None


# ---------------------------------------------------------------------------
# Test 9: Consequence linker returns observed_consequence receipt with hash ref
# ---------------------------------------------------------------------------

def test_consequence_linker_returns_observed_consequence_receipt() -> None:
    delegation = _make_delegation()
    downstream = _DownstreamCounter(result={"status": "scene_changed"})

    result = run_obs_governed_call(
        delegation=delegation,
        op_name="set-current-scene",
        subject_id="Scene A",
        arguments={"sceneName": "Scene A"},
        downstream_fn=downstream,
    )
    assert result.disposition == "admitted"

    # Simulate a native OBS event (e.g. CurrentProgramSceneChanged)
    native_event = {
        "event_type": "CurrentProgramSceneChanged",
        "scene_name": "Scene A",
        "event_id": "obs-native-event-001",
    }

    consequence_receipt = link_consequence(
        execution_receipt=result.receipt,
        native_event=native_event,
        consequence_window_ms=5000,
    )

    assert consequence_receipt["receipt_kind"] == "observed_consequence", (
        f"Expected receipt_kind='observed_consequence', got {consequence_receipt['receipt_kind']!r}"
    )

    # native_event_ref must be a sha256 hash, not the raw event
    native_event_ref = consequence_receipt.get("native_event_ref")
    assert native_event_ref is not None, "consequence receipt must have native_event_ref"
    assert isinstance(native_event_ref, str)
    assert native_event_ref.startswith("sha256:"), (
        f"native_event_ref must be a sha256 hash, got: {native_event_ref!r}"
    )

    # Verify raw event did not enter the receipt
    violations = _walk_receipt(consequence_receipt)
    assert violations == [], f"Forbidden fields in consequence receipt: {violations}"


# ---------------------------------------------------------------------------
# Test 10: Validity window: expired delegation is refused
# ---------------------------------------------------------------------------

def test_expired_delegation_is_refused() -> None:
    # Delegation expired in the past
    delegation = _make_delegation(
        valid_from=_past_iso(2),
        valid_until=_past_iso(1),  # expired 1 day ago
    )
    downstream = _DownstreamCounter()

    result = run_obs_governed_call(
        delegation=delegation,
        op_name="set-current-scene",
        subject_id=None,
        arguments={"sceneName": "Scene A"},
        downstream_fn=downstream,
    )

    assert result.disposition == "refused"
    assert result.downstream_invocation_count == 0
    assert downstream.count == 0


def test_not_yet_valid_delegation_is_refused() -> None:
    # Delegation starts in the future
    delegation = _make_delegation(
        valid_from=_future_iso(1),
        valid_until=_future_iso(2),
    )
    downstream = _DownstreamCounter()

    result = run_obs_governed_call(
        delegation=delegation,
        op_name="set-current-scene",
        subject_id=None,
        arguments={"sceneName": "Scene A"},
        downstream_fn=downstream,
    )

    assert result.disposition == "refused"
    assert result.downstream_invocation_count == 0
    assert downstream.count == 0


# ---------------------------------------------------------------------------
# Additional correctness tests
# ---------------------------------------------------------------------------

def test_receipt_has_correct_profile_fields_on_admitted() -> None:
    delegation = _make_delegation()
    downstream = _DownstreamCounter()

    result = run_obs_governed_call(
        delegation=delegation,
        op_name="set-preview-scene",
        subject_id=None,
        arguments={"sceneName": "Scene B"},
        downstream_fn=downstream,
    )

    assert result.disposition == "admitted"
    receipt = result.receipt
    assert receipt["profile_id"] == "srs.broadcast_control"
    assert receipt["profile_version"] == "v0.1"
    assert receipt["receipt_kind"] == "execution"
    assert receipt["capture_posture"] == "dagr_governed"
    assert receipt["extensions"]["garp"]["mcp_success_proves_delivery"] is False


def test_receipt_has_correct_profile_fields_on_refused() -> None:
    delegation = _make_delegation()
    downstream = _DownstreamCounter()

    result = run_obs_governed_call(
        delegation=delegation,
        op_name="stop-stream",
        subject_id=None,
        arguments={},
        downstream_fn=downstream,
    )

    assert result.disposition == "refused"
    receipt = result.receipt
    assert receipt["profile_id"] == "srs.broadcast_control"
    assert receipt["profile_version"] == "v0.1"
    assert receipt["receipt_kind"] == "request"
    assert receipt["capture_posture"] == "dagr_governed"
    assert receipt["extensions"]["garp"]["mcp_success_proves_delivery"] is False


def test_higher_scope_ops_refused_when_not_in_family() -> None:
    """start-stream not in delegation family -> refused_out_of_scope."""
    delegation = _make_delegation(
        operation_family=ALLOWED_SCENE_OPS,  # no higher scope ops
    )
    downstream = _DownstreamCounter()

    result = run_obs_governed_call(
        delegation=delegation,
        op_name="start-stream",
        subject_id=None,
        arguments={},
        downstream_fn=downstream,
    )

    assert result.disposition == "refused"
    assert result.downstream_invocation_count == 0


def test_higher_scope_ops_admitted_when_in_family() -> None:
    """start-stream admitted when delegation explicitly includes it."""
    delegation = _make_delegation(
        operation_family=ALLOWED_SCENE_OPS | HIGHER_SCOPE_OPS,
    )
    downstream = _DownstreamCounter(result={"status": "stream_started"})

    result = run_obs_governed_call(
        delegation=delegation,
        op_name="start-stream",
        subject_id=None,
        arguments={},
        downstream_fn=downstream,
    )

    assert result.disposition == "admitted"
    assert result.downstream_invocation_count == 1


def test_downstream_fn_not_called_on_hard_deny() -> None:
    """Verify downstream is NEVER called for any hard-deny operation."""
    delegation = _make_delegation(
        operation_family=frozenset(HARD_DENY_OPS),  # even if family "allows" hard-deny ops
    )
    downstream = _DownstreamCounter()

    for op in ["stop-stream", "toggle", "custom-event", "arbitrary-hotkey"]:
        result = run_obs_governed_call(
            delegation=delegation,
            op_name=op,
            subject_id=None,
            arguments={},
            downstream_fn=downstream,
        )
        assert result.disposition == "refused", f"Expected refused for hard-deny op {op!r}"
        assert result.downstream_invocation_count == 0

    assert downstream.count == 0, "downstream should never be called for hard-deny ops"


def test_subject_none_admitted_when_no_subject_restriction() -> None:
    """subject_id=None is admitted when delegation has no subject restriction."""
    delegation = _make_delegation(subject_ids=None)
    downstream = _DownstreamCounter()

    result = run_obs_governed_call(
        delegation=delegation,
        op_name="set-current-scene",
        subject_id=None,
        arguments={"sceneName": "any-scene"},
        downstream_fn=downstream,
    )

    assert result.disposition == "admitted"
    assert result.downstream_invocation_count == 1


def test_consequence_receipt_links_to_execution_receipt_id() -> None:
    """Consequence receipt carries the execution receipt_id as a link."""
    delegation = _make_delegation()
    downstream = _DownstreamCounter()

    result = run_obs_governed_call(
        delegation=delegation,
        op_name="set-current-scene",
        subject_id=None,
        arguments={"sceneName": "Scene A"},
        downstream_fn=downstream,
    )
    assert result.disposition == "admitted"

    native_event = {"event_type": "CurrentProgramSceneChanged", "scene_name": "Scene A"}
    consequence = link_consequence(result.receipt, native_event)

    assert consequence["execution_receipt_id"] == result.receipt["receipt_id"]
    assert consequence["receipt_kind"] == "observed_consequence"
    assert consequence["target_state"] == result.receipt["target_state"]
