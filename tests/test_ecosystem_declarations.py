from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
ECOSYSTEM = ROOT / ".ecosystem"
KIT_SCHEMAS = ROOT.parent / "arcs-ecosystem-kit" / "schemas"

requires_ecosystem_kit = pytest.mark.skipif(
    not KIT_SCHEMAS.exists(),
    reason="arcs-ecosystem-kit not checked out beside dagr-mcp; schema validation skipped",
)

SCHEMA_BY_DECLARATION = {
    "REPOSITORY.yaml": "ecosystem.repository.v0.1.schema.json",
    "ARCHITECTURE_PASSPORT.yaml": "ecosystem.architecture-passport.v0.1.schema.json",
    "AUTHORITY_REFERENCES.yaml": "ecosystem.authority-references.v0.1.schema.json",
    "CAPABILITY_BINDINGS.yaml": "ecosystem.capability-bindings.v0.1.schema.json",
    "CONTRACT_BINDINGS.yaml": "ecosystem.contract-bindings.v0.1.schema.json",
    "DEPENDENCIES.yaml": "ecosystem.dependencies.v0.1.schema.json",
    "LANES.yaml": "ecosystem.lanes.v0.1.schema.json",
    "COMPATIBILITY_PROJECTION.yaml": "ecosystem.compatibility-projection.v0.1.schema.json",
    "CONFORMANCE_PROJECTION.yaml": "ecosystem.conformance-projection.v0.1.schema.json",
    "EXCEPTIONS.yaml": "ecosystem.exceptions.v0.1.schema.json",
    "RELEASE_STATE.yaml": "ecosystem.release-state.v0.1.schema.json",
    "BOUNDARIES.yaml": "ecosystem.boundaries.v0.1.schema.json",
    "RESPONSIBILITIES.yaml": "ecosystem.responsibilities.v0.1.schema.json",
}

EXPECTED_DECLARATIONS = set(SCHEMA_BY_DECLARATION)

LEGACY_DECLARATION_NAMES = {
    "CAPABILITIES.yaml",
    "CONTRACTS.yaml",
    "COMPATIBILITY.yaml",
    "CONFORMANCE.yaml",
}


def _load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path.name} must parse to a mapping"
    return data


def _declarations() -> dict[str, dict[str, Any]]:
    return {name: _load(ECOSYSTEM / name) for name in sorted(EXPECTED_DECLARATIONS)}


def _walk(value: Any) -> Iterator[Any]:
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def test_all_ecosystem_declaration_files_exist() -> None:
    actual = {path.name for path in ECOSYSTEM.glob("*.yaml")}
    assert actual == EXPECTED_DECLARATIONS
    assert actual.isdisjoint(LEGACY_DECLARATION_NAMES)


@requires_ecosystem_kit
def test_ecosystem_declarations_validate_against_checked_out_kit_schemas() -> None:
    for declaration_name, schema_name in sorted(SCHEMA_BY_DECLARATION.items()):
        schema_path = KIT_SCHEMAS / schema_name
        assert schema_path.exists(), schema_name
        schema = _load(schema_path)
        data = _load(ECOSYSTEM / declaration_name)
        validator = jsonschema.Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
        assert not errors, (
            declaration_name,
            [f"{'/'.join(map(str, error.path))}: {error.message}" for error in errors],
        )
        assert data["schema"] == schema["$id"], declaration_name
        assert data["schema_version"] == "0.1", declaration_name


def test_repository_identity_values_are_consistent() -> None:
    for name, data in _declarations().items():
        if name == "REPOSITORY.yaml":
            assert data["repository"]["name"] == "dagr-mcp"
        else:
            assert data["repository"] == "dagr-mcp", name


def test_layer_and_authority_model_is_provisional_and_axis_separated() -> None:
    declarations = _declarations()
    repository = declarations["REPOSITORY.yaml"]
    assert repository["constitutional_roles"]["primary_layer"] == "L5"
    assert set(repository["constitutional_roles"]["secondary_layers"]) == {"L3", "L4"}
    assert repository["authority"]["status"] == "current_implementation"
    assert repository["authority"]["semantic_authority_for"] == []

    architecture = declarations["ARCHITECTURE_PASSPORT.yaml"]
    assert architecture["constitutional_layers"] == {"primary": "L5", "secondary": ["L3", "L4"]}
    roles = {(item["layer"], item["role"]) for item in architecture["secondary_implementation_roles"]}
    assert ("L3", "runtime_binding") in roles
    assert ("L4", "emitter") in roles

    authority_refs = declarations["AUTHORITY_REFERENCES.yaml"]["authorities"]
    refs = {item["concern"]: item for item in authority_refs}
    assert refs["srs_evidence_semantics"]["semantic_authority"]["repository"] == "arcs-srs"
    assert refs["independent_verification"]["semantic_authority"]["repository"] == "arcs-verify"
    assert refs["governed_action_and_protocol_semantics"]["semantic_authority"]["repository"] is None
    assert refs["governed_action_and_protocol_semantics"]["semantic_authority"]["status"] == "unresolved"
    assert refs["srs_evidence_semantics"]["historical_implementations"][0]["repository"] == "garp-sdk"


def test_a0_a6_inputs_are_referenced_as_proposed_unratified_inputs() -> None:
    authorities = _declarations()["AUTHORITY_REFERENCES.yaml"]["authorities"]
    inputs = next(item for item in authorities if item["concern"] == "constitutional_architecture_inputs_A0_A6")
    evidence_ids = {ref["id"] for ref in inputs["evidence_refs"]}
    assert evidence_ids == {
        "A0.docs.ARCS_CONSTITUTIONAL_LAYER_MODEL",
        "A1.docs.GARP_DOCTRINE_COMPATIBILITY",
        "A2.docs.adr.0001-schema-identifier-namespace",
        "A3.docs.SCHEMA_CATALOG",
        "A4.docs.LAYER_AUTHORITY_RULES",
        "A5.docs.SCHEMA_OWNERSHIP",
        "A6.docs.EXISTING_ECOSYSTEM_ASSET_MAP",
    }
    assert inputs["migration"]["authorized"] is False
    assert inputs["assertion_status"] == "partial"
    assert "not ratified doctrine" in inputs["migration"]["notes"]


def test_declarations_do_not_classify_dagr_mcp_as_a_verifier() -> None:
    declarations = _declarations()
    repository = declarations["REPOSITORY.yaml"]
    assert "verifier" not in repository["repository"]["types"]
    assert repository["authority"]["status"] != "verifier_counterpart"

    forbidden_phrases = {
        "dagr mcp is a verifier",
        "dagr-mcp is a verifier",
        "dagr mcp verifier",
        "dagr-mcp verifier",
    }
    text = "\n".join(
        (ECOSYSTEM / name).read_text(encoding="utf-8").lower().replace("_", " ")
        for name in EXPECTED_DECLARATIONS
    )
    for phrase in forbidden_phrases:
        assert phrase not in text


def test_srs_core_v5_1_is_not_declared_as_a_public_srs_release() -> None:
    text = "\n".join((ECOSYSTEM / name).read_text(encoding="utf-8") for name in EXPECTED_DECLARATIONS)
    lower = text.lower()
    assert "current_public_srs_release" not in lower
    assert "public_srs_release: srs.core.v5.1" not in lower
    assert "public release: srs.core.v5.1" not in lower
    assert "srs.core.v5.1" in text
    assert "internal/pre-public" in text


def test_capability_bindings_do_not_claim_canonical_semantic_ownership() -> None:
    capabilities = _declarations()["CAPABILITY_BINDINGS.yaml"]
    assert capabilities["declarations"]["defines"] == []
    implemented = capabilities["declarations"]["implements"]
    for binding in implemented:
        semantic_authority = binding["semantic_authority"]
        assert semantic_authority["repository"] != "dagr-mcp"
        assert binding["relationship"] in {"implements", "partial"}
        if semantic_authority["repository"] is None:
            assert semantic_authority["status"] == "unresolved"

    memory_admit = [
        binding
        for binding in capabilities["declarations"]["consumes"]
        if binding["capability_ref"] == "MEMORY_ADMIT"
    ]
    assert len(memory_admit) == 1
    assert memory_admit[0]["assertion_status"] == "not_applicable"
    assert memory_admit[0]["reachability"] == "not_reachable"

    for value in _walk(capabilities):
        if isinstance(value, dict):
            assert value.get("canonical_semantic_owner") != "dagr-mcp"


def test_contract_bindings_distinguish_implementation_and_semantic_authority() -> None:
    contracts = _declarations()["CONTRACT_BINDINGS.yaml"]
    provided = {item["contract_id"]: item for item in contracts["provided"]}
    consumed = {item["contract_id"]: item for item in contracts["consumed"]}

    srs_admission = provided["srs.mcp.sdk_enforcement.admission_emission"]
    assert srs_admission["provider_implementation"]["repository"] == "dagr-mcp"
    assert srs_admission["semantic_authority"]["repository"] == "arcs-srs"

    srs_version = consumed["srs.core.v5_1"]
    assert srs_version["semantic_authority"]["status"] == "historical"
    assert "not a public SRS release claim" in srs_version["notes"]

    verifier = consumed["arcs.verify.report.v0_2"]
    assert verifier["provider_implementation"]["repository"] == "arcs-verify"
    assert verifier["semantic_authority"]["repository"] == "arcs-verify"
    assert "not a runtime import dependency" in verifier["compatibility"]["migration_notes"]


def test_arcs_verify_is_not_modeled_as_runtime_import_dependency() -> None:
    dependencies = _declarations()["DEPENDENCIES.yaml"]["dependencies"]
    arcs_verify = next(item for item in dependencies if item["repository"] == "arcs-verify")
    assert arcs_verify["dependency_type"] == "validation"
    assert arcs_verify["required"] is False
    assert "not imported by runtime code" in arcs_verify["reason"]
    assert "never a runtime import dependency" in arcs_verify["compatibility_notes"]

    runtime_dependency_repositories = {
        item["repository"] for item in dependencies if item["dependency_type"] == "runtime"
    }
    assert "arcs-verify" not in runtime_dependency_repositories


def test_policy_decisions_are_not_receipt_dispositions() -> None:
    compatibility = (ECOSYSTEM / "COMPATIBILITY_PROJECTION.yaml").read_text(encoding="utf-8")
    assert "allow, deny, gate, defer, and fail_closed" in compatibility
    assert "admitted, refused, and deferred_for_review" in compatibility

    boundaries = _declarations()["BOUNDARIES.yaml"]["boundaries"]
    policy_boundary = next(item for item in boundaries if item["id"] == "runtime-policy-decision-boundary")
    assert "not SRS receipt dispositions" in policy_boundary["notes"]


def test_architecture_passport_known_exceptions_match_exceptions_file() -> None:
    declarations = _declarations()
    known_exceptions = set(declarations["ARCHITECTURE_PASSPORT.yaml"]["known_exceptions"])
    exception_ids = {item["id"] for item in declarations["EXCEPTIONS.yaml"]["exceptions"]}
    assert known_exceptions == exception_ids


def test_active_lane_id_is_unique_within_lane_file() -> None:
    lanes = _declarations()["LANES.yaml"]["lanes"]
    lane_ids = [lane["lane_id"] for lane in lanes]
    assert lane_ids == ["dagr-mcp-ecosystem-doctrine-pilot-v0-1"]
    assert len(lane_ids) == len(set(lane_ids))
