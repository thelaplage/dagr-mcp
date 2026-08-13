"""Unit tests for the neutral operator admission resolver (DAGR-TRADE0)."""

from __future__ import annotations

import pytest

from dagr_mcp.enforcement_harness import ToolPolicy
from dagr_mcp.operator_admission_resolver import (
    DEFAULT_REFUSAL_REASON,
    OperatorAdmissionResolverError,
    resolve_operator_admission,
)


def test_admitted_decision_resolves_to_allow_policy():
    policy = resolve_operator_admission(
        tool_name="some_tool", tool_class="read", decision="admitted",
    )
    assert isinstance(policy, ToolPolicy)
    assert policy.tool_name == "some_tool"
    assert policy.tool_class == "read"
    assert policy.decision == "allow"
    assert policy.reason == "operator_admitted"


def test_refused_decision_resolves_to_deny_policy_with_default_reason():
    policy = resolve_operator_admission(
        tool_name="some_tool", tool_class="external_action", decision="refused",
    )
    assert policy.decision == "deny"
    assert policy.reason == DEFAULT_REFUSAL_REASON
    assert policy.reason == "policy_refused"


def test_caller_supplied_reason_overrides_default():
    policy = resolve_operator_admission(
        tool_name="some_tool",
        tool_class="external_action",
        decision="refused",
        reason="operator_supplied_reason_code",
    )
    assert policy.reason == "operator_supplied_reason_code"


@pytest.mark.parametrize("bad_decision", ["allow", "deny", "approved", "ADMITTED", "", None, 1, True])
def test_unrecognized_decision_fails_closed(bad_decision):
    with pytest.raises(OperatorAdmissionResolverError):
        resolve_operator_admission(tool_name="t", tool_class="read", decision=bad_decision)


@pytest.mark.parametrize("bad_name", ["", "   ", None, 1, []])
def test_empty_or_non_string_tool_name_fails_closed(bad_name):
    with pytest.raises(OperatorAdmissionResolverError):
        resolve_operator_admission(tool_name=bad_name, tool_class="read", decision="admitted")


def test_non_string_reason_fails_closed():
    with pytest.raises(OperatorAdmissionResolverError):
        resolve_operator_admission(
            tool_name="t", tool_class="read", decision="admitted", reason=123,
        )


def test_gate_timeout_seconds_passes_through():
    policy = resolve_operator_admission(
        tool_name="t", tool_class="read", decision="admitted", gate_timeout_seconds=30,
    )
    assert policy.gate_timeout_seconds == 30


def test_resolver_has_no_domain_specific_vocabulary_in_its_own_source():
    # Structural guard: this module must never grow finance/compliance
    # vocabulary. A grep-style check over its own source text, run as a test
    # so a future edit that reintroduces domain vocabulary fails CI here
    # rather than only at review time.
    import inspect

    from dagr_mcp import operator_admission_resolver

    source = inspect.getsource(operator_admission_resolver).lower()
    banned_substrings = [
        "countervail", "mnpi", "insider", "issuer", "restricted list",
        "restricted_list", "compliance", "fsi", "watchlist", "wall-crossed",
        "wall_crossed",
    ]
    hits = [needle for needle in banned_substrings if needle in source]
    assert hits == [], f"operator_admission_resolver.py contains domain vocabulary: {hits}"
