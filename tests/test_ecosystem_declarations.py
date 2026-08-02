from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
ECOSYSTEM = ROOT / ".ecosystem"

EXPECTED_DECLARATIONS = {
    "REPOSITORY.yaml",
    "ARCHITECTURE_PASSPORT.yaml",
    "CAPABILITIES.yaml",
    "CAPABILITY_BINDINGS.yaml",
    "CONTRACTS.yaml",
    "DEPENDENCIES.yaml",
    "LANES.yaml",
    "COMPATIBILITY.yaml",
    "CONFORMANCE.yaml",
    "EXCEPTIONS.yaml",
    "RELEASE_STATE.yaml",
}


def _load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path.name} must parse to a mapping"
    return data


def _declarations() -> dict[str, dict[str, Any]]:
    return {name: _load(ECOSYSTEM / name) for name in EXPECTED_DECLARATIONS}


def _walk(value: Any) -> Iterator[Any]:
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def test_all_provisional_ecosystem_declaration_files_exist() -> None:
    actual = {path.name for path in ECOSYSTEM.glob("*.yaml")}
    assert actual == EXPECTED_DECLARATIONS


def test_ecosystem_declarations_parse_and_carry_schema_identifiers() -> None:
    for name, data in _declarations().items():
        assert data["schema_ref"].startswith("arcs.ecosystem."), name
        assert data["schema_status"] == "provisional_pending_arcs_ecosystem_kit"
        assert data["declaration_id"].startswith("dagr-mcp."), name
        assert data["declaration_kind"], name


def test_repository_identity_values_are_consistent() -> None:
    for name, data in _declarations().items():
        identity = data.get("repository_identity") or data.get("repository")
        assert isinstance(identity, dict), name
        assert identity.get("name") == "dagr-mcp", name
        if "canonical_repo" in identity:
            assert identity["canonical_repo"] == "thelaplage/dagr-mcp", name


def test_declarations_do_not_classify_dagr_mcp_as_a_verifier() -> None:
    declarations = _declarations()
    repository_types = declarations["REPOSITORY.yaml"]["repository"]["types"]
    assert "verifier" not in repository_types

    classification = declarations["REPOSITORY.yaml"]["classification"]
    assert "verifier" not in classification["is"]

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


def test_srs_core_v5_1_is_not_declared_as_current_public_srs_release() -> None:
    text = "\n".join((ECOSYSTEM / name).read_text(encoding="utf-8") for name in EXPECTED_DECLARATIONS)
    lower = text.lower()
    assert "current public srs release" not in lower
    assert "current_public_srs_release" not in lower
    assert "public_srs_release" not in lower
    assert "srs.core.v5.1" in text


def test_capability_declaration_does_not_claim_canonical_semantic_ownership() -> None:
    capabilities = _declarations()["CAPABILITIES.yaml"]
    assert capabilities["capability_semantics"]["canonical_semantic_owner"] == "defined_elsewhere"
    assert capabilities["capability_bindings"]["canonical_capability_definitions"] == "not_claimed"
    for value in _walk(capabilities["capabilities"]):
        assert value != {"canonical_semantic_owner": "dagr-mcp"}
        if isinstance(value, dict):
            assert value.get("canonical_semantic_owner") != "dagr-mcp"
            assert value.get("semantic_authority") != "dagr-mcp"


def test_capability_bindings_reference_external_vocabularies_without_defining_them() -> None:
    bindings = _declarations()["CAPABILITY_BINDINGS.yaml"]
    assert bindings["canonical_capability_definitions"] == "not_claimed"
    policy = bindings["definition_policy"]
    assert policy["does_not_define_canonical_capabilities"] is True
    assert policy["does_not_define_garp_sdk_boundary_vocabulary"] is True
    assert policy["does_not_define_srs_profile_or_envelope_semantics"] is True
    assert policy["does_not_define_arcs_verify_report_contracts"] is True
    assert policy["does_not_define_countervail_receipt_ingest_semantics"] is True

    surface_ids = {surface["id"] for surface in bindings["external_vocabulary_surfaces"]}
    assert "garp_sdk.runtime_surface_registry" in surface_ids
    assert "garp_sdk.boundary_contracts" in surface_ids
    assert "arcs_srs.mcp_sdk_enforcement_profile" in surface_ids
    assert "arcs_verify.dagr_srs_report_v0_2" in surface_ids
    assert "dagr_workbench.service_ownership" in surface_ids
    assert "countervail.dagr_receipt_ingest_contract" in surface_ids

    for binding in bindings["capability_bindings"]:
        assert binding["capability_definition_authority"] != "dagr-mcp"
        assert "definition" not in binding


def test_arcs_verify_is_not_modeled_as_runtime_import_dependency() -> None:
    dependencies = _declarations()["DEPENDENCIES.yaml"]["dependencies"]
    validation_deps = dependencies["validation"]
    arcs_verify = next(item for item in validation_deps if item["name"] == "arcs-verify")
    assert arcs_verify["dependency_role"] == "independent_validation_and_release_dependency"
    assert arcs_verify["runtime_import"] is False
    assert arcs_verify["modeled_as_runtime_import_dependency"] is False

    for package in dependencies["python_package"]:
        assert package["name"] != "arcs-verify"


def test_active_lane_id_is_unique_within_lane_file() -> None:
    lanes = _declarations()["LANES.yaml"]["active_lanes"]
    lane_ids = [lane["lane_id"] for lane in lanes]
    assert lane_ids == ["dagr-mcp-ecosystem-doctrine-pilot-v0-1"]
    assert len(lane_ids) == len(set(lane_ids))
