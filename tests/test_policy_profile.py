from __future__ import annotations

import json
from pathlib import Path

import pytest

from dagr_mcp import policy_profile as policy_profile_mod
from dagr_mcp.policy_profile import (
    PolicyProfileError,
    PolicyProfileProjection,
    harness_projection_from_profile,
    load_policy_profile,
    matter_scope_projection_from_profile,
    project_policy_profile,
    sink_requirements_from_profile,
)


def test_empty_profile_defaults_no_required_sinks() -> None:
    projected = project_policy_profile({})

    assert projected.harness.sink_requirements.event_sink_required is False
    assert projected.harness.sink_requirements.receipt_sink_required is False
    assert projected.harness.tool_policy_group is None
    assert "missing_harness_group" in projected.warnings


def test_top_level_sink_requirements() -> None:
    projected = project_policy_profile(
        {
            "harness": {},
            "sink_requirements": {
                "event_sink_required": True,
                "receipt_sink_required": True,
                "health_check_mode": "per_operation",
                "required_sink_failure_behavior": "fail_closed",
            },
        }
    )

    sinks = projected.harness.sink_requirements
    assert sinks.event_sink_required is True
    assert sinks.receipt_sink_required is True
    assert sinks.health_check_mode == "per_operation"
    assert sinks.requires_event_sink() is True
    assert sinks.requires_receipt_sink() is True
    assert "missing_harness_group" not in projected.warnings


def test_nested_harness_sink_requirements() -> None:
    projected = project_policy_profile(
        {
            "harness": {
                "tool_policy_group": "g",
                "sink_requirements": {
                    "artifact_sink_required": True,
                    "review_object_sink_required": True,
                },
            },
        }
    )

    s = projected.harness.sink_requirements
    assert s.artifact_sink_required is True
    assert s.review_object_sink_required is True
    assert s.requires_review_object_sink() is True


def test_nested_sink_requirements_override_top_level_with_warning() -> None:
    projected = project_policy_profile(
        {
            "sink_requirements": {
                "event_sink_required": True,
                "receipt_sink_required": False,
                "health_check_mode": "explicit",
            },
            "harness": {
                "sink_requirements": {
                    "event_sink_required": False,
                    "receipt_sink_required": True,
                    "health_check_mode": "scheduled",
                },
            },
        }
    )

    s = projected.harness.sink_requirements
    assert s.event_sink_required is False
    assert s.receipt_sink_required is True
    assert s.health_check_mode == "scheduled"
    assert "sink_requirements_nested_overrides_top_level" in projected.warnings


def test_malformed_sink_requirements_type_raises() -> None:
    with pytest.raises(PolicyProfileError, match="sink_requirements must be a mapping"):
        project_policy_profile({"sink_requirements": []})


def test_non_boolean_sink_flag_raises() -> None:
    with pytest.raises(PolicyProfileError, match="event_sink_required must be a boolean"):
        project_policy_profile(
            {"harness": {}, "sink_requirements": {"event_sink_required": 1}}
        )


def test_invalid_health_check_mode_raises() -> None:
    with pytest.raises(PolicyProfileError, match="invalid health_check_mode"):
        project_policy_profile(
            {
                "harness": {},
                "sink_requirements": {"health_check_mode": "nope"},
            }
        )


def test_invalid_required_sink_failure_behavior_raises() -> None:
    with pytest.raises(PolicyProfileError, match="invalid required_sink_failure_behavior"):
        project_policy_profile(
            {
                "harness": {},
                "sink_requirements": {"required_sink_failure_behavior": "panic"},
            }
        )


@pytest.mark.parametrize(
    "bad_timeout",
    [0, -1, "30", 1.5, True],
)
def test_gate_timeout_must_be_positive_integer(bad_timeout: object) -> None:
    with pytest.raises(PolicyProfileError, match="gate_timeout_seconds"):
        project_policy_profile(
            {"harness": {"gate_timeout_seconds": bad_timeout}},
        )


def test_gate_timeout_positive_accepted() -> None:
    h = harness_projection_from_profile({"harness": {"gate_timeout_seconds": 30}})
    assert h.gate_timeout_seconds == 30


def test_missing_harness_warns_and_defaults_harness_projection() -> None:
    projected = project_policy_profile({"profile_id": "x"})

    assert "missing_harness_group" in projected.warnings
    assert projected.harness.tool_policy_group is None
    assert projected.harness.review_required is False


def test_unknown_fields_are_ignored() -> None:
    projected = project_policy_profile(
        {
            "noise": {"nested": True},
            "harness": {"tool_policy_group": "default_mcp_tools"},
            "extra_root": 123,
        }
    )

    assert projected.harness.tool_policy_group == "default_mcp_tools"


def test_load_policy_profile_reads_json(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {
                "profile_id": "example",
                "schema_version": "garp.profile.v1.1",
                "harness": {"emit_receipt": True},
            }
        ),
        encoding="utf-8",
    )

    projected = load_policy_profile(path)

    assert isinstance(projected, PolicyProfileProjection)
    assert projected.profile_id == "example"
    assert projected.source_schema_version == "garp.profile.v1.1"
    assert projected.harness.emit_receipt is True


def test_policy_profile_source_has_no_local_sinks_import() -> None:
    src = Path(policy_profile_mod.__file__).read_text(encoding="utf-8")
    assert "local_sinks" not in src


def test_sink_requirements_from_profile_matches_projection_merge() -> None:
    profile = {
        "sink_requirements": {"lint_finding_sink_required": True},
        "harness": {"sink_requirements": {"lint_finding_sink_required": False}},
    }
    assert sink_requirements_from_profile(profile).lint_finding_sink_required is False
    assert (
        project_policy_profile(profile).harness.sink_requirements.lint_finding_sink_required
        is False
    )


def test_project_policy_profile_rejects_non_mapping() -> None:
    with pytest.raises(PolicyProfileError, match="profile must be a mapping"):
        project_policy_profile([])  # type: ignore[arg-type]


def test_harness_must_be_mapping_when_present() -> None:
    with pytest.raises(PolicyProfileError, match="harness must be a mapping"):
        project_policy_profile({"harness": "broken"})


def test_nested_sink_requirements_invalid_type() -> None:
    with pytest.raises(PolicyProfileError, match="harness.sink_requirements"):
        project_policy_profile({"harness": {"sink_requirements": []}})


def test_matter_scope_projection_supports_ms_rule_groups() -> None:
    profile = {
        "matter_scope": {
            "banned_phrase": [
                {"phrase": "synthetic banned", "severity": "error"},
            ],
            "canonical_figure_lock": {
                "forbidden_near_misses": [{"phrase": "Figur A"}],
                "allowed_alternates": [{"phrase": "Figure Alpha", "severity": "info"}],
            },
            "exhibit_tag_format": {"tag_pattern": r"EX-\d{3}", "severity": "warning"},
            "cross_filing_scope": {"mode": "future-compatible"},
            "phase_marker": {"stage": "pre-filing"},
        }
    }
    scope = matter_scope_projection_from_profile(profile)
    assert len(scope.banned_phrase) == 1
    assert len(scope.canonical_figure_lock_forbidden) == 1
    assert len(scope.canonical_figure_lock_allowed) == 1
    assert scope.exhibit_tag_format_pattern == r"EX-\d{3}"
    assert scope.cross_filing_scope == {"mode": "future-compatible"}
    assert scope.phase_marker == {"stage": "pre-filing"}
