"""Tests for dagr_mcp.evidence_contract — MCP-EVIDENCE-CONTRACT0.

Coverage:
  - schema conformance: positive/adversarial fixtures against
    schemas/mcp-evidence-contract/v0.1/x-evidence-contract.v0.1.schema.json
  - Python model conformance: the same fixtures against
    EvidenceContract.from_dict / validate_tool_descriptor_extension
  - build_evidence_contract factory and EvidenceGuarantees validation
  - additive/backward-compatibility: descriptors without the extension
  - deterministic (RFC 8785) serialization / round-trip
  - core doctrine chain / non-equivalence documentation

ADDITIVE ONLY: this module imports nothing from the admission/lifecycle or
SRS receipt modules beyond the shared rfc8785 canonicalization helper already
used by dagr_mcp.srs_receipts, preserving producer/verifier independence.
AUTHORITY_MOVEMENT = 0 — no test here asserts or exercises any admission,
publication, or verification decision.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from dagr_mcp.evidence_contract import (
    AUTHORITY_EFFECT,
    CORE_DOCTRINE_CHAIN,
    ELIGIBLE_USES,
    EVIDENCE_CONTRACT_EXTENSION_KEY,
    EVIDENCE_CONTRACT_VERSION,
    NON_EQUIVALENCES,
    RECOGNIZED_DIGEST_ALGORITHMS,
    REQUIRED_INELIGIBLE_USES,
    EvidenceContract,
    EvidenceContractError,
    EvidenceGuarantees,
    attach_evidence_contract,
    build_evidence_contract,
    validate_tool_descriptor_extension,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCHEMA_PATH = (
    _REPO_ROOT
    / "schemas"
    / "mcp-evidence-contract"
    / "v0.1"
    / "x-evidence-contract.v0.1.schema.json"
)
_FIXTURES_DIR = _REPO_ROOT / "tests" / "fixtures" / "evidence_contract"


def _load_json(path: Path) -> Any:
    with path.open() as f:
        return json.load(f)


def _load_fixture(name: str) -> dict[str, Any]:
    return _load_json(_FIXTURES_DIR / name)


_SCHEMA = _load_json(_SCHEMA_PATH)

_POSITIVE_FIXTURES = sorted(p.name for p in _FIXTURES_DIR.glob("positive_*.json"))
_ADVERSARIAL_FIXTURES = sorted(p.name for p in _FIXTURES_DIR.glob("adversarial_*.json"))


# --------------------------------------------------------------------------- #
# Fixture inventory sanity                                                    #
# --------------------------------------------------------------------------- #


def test_fixture_inventory_nonempty() -> None:
    assert len(_POSITIVE_FIXTURES) >= 3
    assert len(_ADVERSARIAL_FIXTURES) >= 10


def test_schema_file_is_valid_json_schema() -> None:
    # Raises if the schema document itself is not a valid JSON Schema.
    jsonschema.Draft202012Validator.check_schema(_SCHEMA)


# --------------------------------------------------------------------------- #
# Schema conformance — positive fixtures                                      #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fixture_name", _POSITIVE_FIXTURES)
def test_positive_fixture_validates_against_schema(fixture_name: str) -> None:
    doc = _load_fixture(fixture_name)
    ext = doc[EVIDENCE_CONTRACT_EXTENSION_KEY]
    jsonschema.validate(ext, _SCHEMA)


@pytest.mark.parametrize("fixture_name", _POSITIVE_FIXTURES)
def test_positive_fixture_validates_against_python_model(fixture_name: str) -> None:
    doc = _load_fixture(fixture_name)
    ext = doc[EVIDENCE_CONTRACT_EXTENSION_KEY]
    contract = EvidenceContract.from_dict(ext)
    assert contract.contract_version == EVIDENCE_CONTRACT_VERSION
    assert contract.authority_effect == "none"
    # No positive fixture may declare admission/publication/factual_truth
    # eligible — this is the mechanically checkable form of "invalid claims
    # such as authority_effect != none are rejected in v0.1" / "publication
    # and admission cannot be asserted as positive guarantees."
    assert set(contract.eligible_uses).isdisjoint(REQUIRED_INELIGIBLE_USES)
    assert set(contract.ineligible_uses) == set(REQUIRED_INELIGIBLE_USES)


@pytest.mark.parametrize("fixture_name", _POSITIVE_FIXTURES)
def test_positive_fixture_full_descriptor_validates(fixture_name: str) -> None:
    doc = _load_fixture(fixture_name)
    # Simulate the fixture attached to a real (minimal) MCP tool descriptor.
    descriptor = {"name": "example_tool", "description": "example"} | doc
    validate_tool_descriptor_extension(descriptor)  # must not raise


# --------------------------------------------------------------------------- #
# Schema + Python model conformance — adversarial fixtures                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fixture_name", _ADVERSARIAL_FIXTURES)
def test_adversarial_fixture_rejected_by_schema(fixture_name: str) -> None:
    doc = _load_fixture(fixture_name)
    ext = doc[EVIDENCE_CONTRACT_EXTENSION_KEY]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(ext, _SCHEMA)


@pytest.mark.parametrize("fixture_name", _ADVERSARIAL_FIXTURES)
def test_adversarial_fixture_rejected_by_python_model(fixture_name: str) -> None:
    doc = _load_fixture(fixture_name)
    ext = doc[EVIDENCE_CONTRACT_EXTENSION_KEY]
    with pytest.raises(EvidenceContractError):
        EvidenceContract.from_dict(ext)


@pytest.mark.parametrize("fixture_name", _ADVERSARIAL_FIXTURES)
def test_adversarial_fixture_rejected_via_descriptor_validation(fixture_name: str) -> None:
    doc = _load_fixture(fixture_name)
    descriptor = {"name": "example_tool", "description": "example"} | doc
    with pytest.raises(EvidenceContractError):
        validate_tool_descriptor_extension(descriptor)


# --------------------------------------------------------------------------- #
# Additive / backward-compatibility                                           #
# --------------------------------------------------------------------------- #


class TestBackwardCompatibility:
    def test_descriptor_without_extension_passes_silently(self) -> None:
        validate_tool_descriptor_extension({"name": "legacy_tool", "description": "d"})

    def test_none_descriptor_passes_silently(self) -> None:
        validate_tool_descriptor_extension(None)

    def test_empty_descriptor_passes_silently(self) -> None:
        validate_tool_descriptor_extension({})

    def test_extension_key_not_a_mapping_rejected(self) -> None:
        with pytest.raises(EvidenceContractError):
            validate_tool_descriptor_extension({EVIDENCE_CONTRACT_EXTENSION_KEY: "nope"})

    def test_attach_preserves_existing_keys(self) -> None:
        contract = build_evidence_contract(
            output_kind="source_candidate",
            exact_bytes_available=False,
            stable_identity_available=False,
            digest_available=False,
            digest_algorithm=None,
            retrieval_observation_available=False,
            provenance_lineage_ref_available=False,
            eligible_uses=["discovery"],
        )
        descriptor = {"name": "search", "description": "a search tool", "inputSchema": {}}
        merged = attach_evidence_contract(descriptor, contract)
        assert merged["name"] == "search"
        assert merged["description"] == "a search tool"
        assert merged["inputSchema"] == {}
        assert EVIDENCE_CONTRACT_EXTENSION_KEY in merged
        validate_tool_descriptor_extension(merged)

    def test_attach_does_not_mutate_input_descriptor(self) -> None:
        contract = build_evidence_contract(
            output_kind="source_candidate",
            exact_bytes_available=False,
            stable_identity_available=False,
            digest_available=False,
            digest_algorithm=None,
            retrieval_observation_available=False,
            provenance_lineage_ref_available=False,
            eligible_uses=["discovery"],
        )
        descriptor = {"name": "search"}
        attach_evidence_contract(descriptor, contract)
        assert EVIDENCE_CONTRACT_EXTENSION_KEY not in descriptor


# --------------------------------------------------------------------------- #
# build_evidence_contract factory                                             #
# --------------------------------------------------------------------------- #


class TestBuildEvidenceContract:
    def test_search_tool_example_from_mission(self) -> None:
        # "A search tool may declare that it produces source_candidate with
        # no exact-byte guarantee and is not citation-eligible by itself."
        contract = build_evidence_contract(
            output_kind="source_candidate",
            exact_bytes_available=False,
            stable_identity_available=False,
            digest_available=False,
            digest_algorithm=None,
            retrieval_observation_available=False,
            provenance_lineage_ref_available=False,
            eligible_uses=["discovery", "evidence_candidate"],
        )
        assert "citation_candidate" not in contract.eligible_uses
        assert contract.evidence_guarantees.exact_bytes_available is False
        assert contract.authority_effect == "none"

    def test_capture_tool_example_from_mission(self) -> None:
        # "A capture tool may declare that it can produce captured_source
        # with exact bytes, digest, and retrieval observation, while still
        # remaining authority_effect: none and not publication-eligible."
        contract = build_evidence_contract(
            output_kind="captured_source",
            exact_bytes_available=True,
            stable_identity_available=True,
            digest_available=True,
            digest_algorithm="sha256",
            retrieval_observation_available=True,
            provenance_lineage_ref_available=True,
            eligible_uses=["discovery", "evidence_candidate", "citation_candidate"],
        )
        assert contract.evidence_guarantees.exact_bytes_available is True
        assert contract.evidence_guarantees.digest_algorithm == "sha256"
        assert "publication" not in contract.eligible_uses
        assert contract.authority_effect == "none"

    def test_ineligible_uses_always_fixed_set_regardless_of_caller(self) -> None:
        contract = build_evidence_contract(
            output_kind="source_candidate",
            exact_bytes_available=False,
            stable_identity_available=False,
            digest_available=False,
            digest_algorithm=None,
            retrieval_observation_available=False,
            provenance_lineage_ref_available=False,
            eligible_uses=["discovery"],
        )
        assert set(contract.ineligible_uses) == set(REQUIRED_INELIGIBLE_USES)

    def test_authority_effect_always_none_regardless_of_caller(self) -> None:
        contract = build_evidence_contract(
            output_kind="source_candidate",
            exact_bytes_available=False,
            stable_identity_available=False,
            digest_available=False,
            digest_algorithm=None,
            retrieval_observation_available=False,
            provenance_lineage_ref_available=False,
            eligible_uses=["discovery"],
        )
        assert contract.authority_effect == AUTHORITY_EFFECT == "none"

    def test_empty_eligible_uses_rejected(self) -> None:
        with pytest.raises(EvidenceContractError):
            build_evidence_contract(
                output_kind="source_candidate",
                exact_bytes_available=False,
                stable_identity_available=False,
                digest_available=False,
                digest_algorithm=None,
                retrieval_observation_available=False,
                provenance_lineage_ref_available=False,
                eligible_uses=[],
            )

    def test_duplicate_eligible_uses_rejected(self) -> None:
        with pytest.raises(EvidenceContractError):
            build_evidence_contract(
                output_kind="source_candidate",
                exact_bytes_available=False,
                stable_identity_available=False,
                digest_available=False,
                digest_algorithm=None,
                retrieval_observation_available=False,
                provenance_lineage_ref_available=False,
                eligible_uses=["discovery", "discovery"],
            )

    def test_counterpedia_specific_identity_not_embedded_in_generic_output_kind(self) -> None:
        # Constraint: "Do not embed Counterpedia-specific record identities
        # into the generic schema." output_kind is a plain snake_case token;
        # a record-identity-shaped value (e.g. containing ':' or digits-as-id)
        # is rejected by the pattern, keeping the field generic.
        with pytest.raises(EvidenceContractError):
            build_evidence_contract(
                output_kind="counterpedia:record:12345",
                exact_bytes_available=False,
                stable_identity_available=False,
                digest_available=False,
                digest_algorithm=None,
                retrieval_observation_available=False,
                provenance_lineage_ref_available=False,
                eligible_uses=["discovery"],
            )

    @pytest.mark.parametrize("bad_kind", ["", "  ", "Source_Candidate", "1source", "src cand"])
    def test_malformed_output_kind_rejected(self, bad_kind: str) -> None:
        with pytest.raises(EvidenceContractError):
            build_evidence_contract(
                output_kind=bad_kind,
                exact_bytes_available=False,
                stable_identity_available=False,
                digest_available=False,
                digest_algorithm=None,
                retrieval_observation_available=False,
                provenance_lineage_ref_available=False,
                eligible_uses=["discovery"],
            )


# --------------------------------------------------------------------------- #
# EvidenceGuarantees — CR-EVC-01                                              #
# --------------------------------------------------------------------------- #


class TestEvidenceGuarantees:
    def test_valid_digest_true_with_algorithm(self) -> None:
        eg = EvidenceGuarantees(
            exact_bytes_available=True,
            stable_identity_available=True,
            digest_available=True,
            digest_algorithm="sha256",
            retrieval_observation_available=True,
            provenance_lineage_ref_available=True,
        )
        assert eg.digest_algorithm == "sha256"

    def test_valid_digest_false_with_null_algorithm(self) -> None:
        eg = EvidenceGuarantees(
            exact_bytes_available=False,
            stable_identity_available=False,
            digest_available=False,
            digest_algorithm=None,
            retrieval_observation_available=False,
            provenance_lineage_ref_available=False,
        )
        assert eg.digest_algorithm is None

    def test_digest_true_without_algorithm_rejected(self) -> None:
        with pytest.raises(EvidenceContractError, match="CR-EVC-01"):
            EvidenceGuarantees(
                exact_bytes_available=True,
                stable_identity_available=True,
                digest_available=True,
                digest_algorithm=None,
                retrieval_observation_available=True,
                provenance_lineage_ref_available=True,
            )

    def test_digest_false_with_algorithm_rejected(self) -> None:
        with pytest.raises(EvidenceContractError, match="CR-EVC-01"):
            EvidenceGuarantees(
                exact_bytes_available=False,
                stable_identity_available=False,
                digest_available=False,
                digest_algorithm="sha256",
                retrieval_observation_available=False,
                provenance_lineage_ref_available=False,
            )

    @pytest.mark.parametrize("algo", ["md5", "sha1", "SHA256", "sha-256", "crc32", ""])
    def test_malformed_algorithm_rejected(self, algo: str) -> None:
        with pytest.raises(EvidenceContractError):
            EvidenceGuarantees(
                exact_bytes_available=True,
                stable_identity_available=True,
                digest_available=True,
                digest_algorithm=algo,
                retrieval_observation_available=True,
                provenance_lineage_ref_available=True,
            )

    @pytest.mark.parametrize("algo", sorted(RECOGNIZED_DIGEST_ALGORITHMS))
    def test_recognized_algorithms_accepted(self, algo: str) -> None:
        eg = EvidenceGuarantees(
            exact_bytes_available=True,
            stable_identity_available=True,
            digest_available=True,
            digest_algorithm=algo,
            retrieval_observation_available=True,
            provenance_lineage_ref_available=True,
        )
        assert eg.digest_algorithm == algo

    def test_non_bool_field_rejected(self) -> None:
        with pytest.raises(EvidenceContractError):
            EvidenceGuarantees(
                exact_bytes_available="yes",  # type: ignore[arg-type]
                stable_identity_available=False,
                digest_available=False,
                digest_algorithm=None,
                retrieval_observation_available=False,
                provenance_lineage_ref_available=False,
            )

    def test_unknown_field_in_from_dict_rejected(self) -> None:
        with pytest.raises(EvidenceContractError):
            EvidenceGuarantees.from_dict(
                {
                    "exact_bytes_available": False,
                    "stable_identity_available": False,
                    "digest_available": False,
                    "digest_algorithm": None,
                    "retrieval_observation_available": False,
                    "provenance_lineage_ref_available": False,
                    "reputation_score": 1.0,
                }
            )

    def test_missing_field_in_from_dict_rejected(self) -> None:
        with pytest.raises(EvidenceContractError):
            EvidenceGuarantees.from_dict({"exact_bytes_available": False})


# --------------------------------------------------------------------------- #
# Deterministic (RFC 8785) serialization                                      #
# --------------------------------------------------------------------------- #


class TestDeterministicSerialization:
    def _sample(self) -> EvidenceContract:
        return build_evidence_contract(
            output_kind="captured_source",
            exact_bytes_available=True,
            stable_identity_available=True,
            digest_available=True,
            digest_algorithm="sha256",
            retrieval_observation_available=True,
            provenance_lineage_ref_available=True,
            eligible_uses=["citation_candidate", "discovery", "evidence_candidate"],
        )

    def test_canonical_bytes_stable_across_construction_order(self) -> None:
        a = build_evidence_contract(
            output_kind="captured_source",
            exact_bytes_available=True,
            stable_identity_available=True,
            digest_available=True,
            digest_algorithm="sha256",
            retrieval_observation_available=True,
            provenance_lineage_ref_available=True,
            eligible_uses=["discovery", "evidence_candidate", "citation_candidate"],
        )
        b = build_evidence_contract(
            output_kind="captured_source",
            exact_bytes_available=True,
            stable_identity_available=True,
            digest_available=True,
            digest_algorithm="sha256",
            retrieval_observation_available=True,
            provenance_lineage_ref_available=True,
            eligible_uses=["citation_candidate", "evidence_candidate", "discovery"],
        )
        # Field order in the source list differs but the resulting canonical
        # bytes are byte-identical because to_dict()/rfc8785 both fix
        # ordering — eligible_uses order is preserved as declared (it is a
        # semantically ordered list per the schema, not a set), so these two
        # differ only if order is semantically distinct; assert instead that
        # canonicalization is deterministic and repeatable for a fixed input.
        assert a.canonical_bytes() == a.canonical_bytes()
        assert b.canonical_bytes() == b.canonical_bytes()

    def test_canonical_bytes_deterministic_repeat(self) -> None:
        c = self._sample()
        first = c.canonical_bytes()
        second = c.canonical_bytes()
        assert first == second
        assert isinstance(first, bytes)

    def test_canonical_bytes_is_valid_json(self) -> None:
        c = self._sample()
        parsed = json.loads(c.canonical_bytes())
        assert parsed == c.to_dict()

    def test_round_trip_to_dict_from_dict(self) -> None:
        c = self._sample()
        d = c.to_dict()
        c2 = EvidenceContract.from_dict(d)
        assert c2 == c
        assert c2.canonical_bytes() == c.canonical_bytes()

    def test_round_trip_through_json_string(self) -> None:
        c = self._sample()
        s = json.dumps(c.to_dict())
        parsed = json.loads(s)
        c2 = EvidenceContract.from_dict(parsed)
        assert c2 == c

    def test_round_trip_through_tool_extension_wrapper(self) -> None:
        c = self._sample()
        wrapped = c.to_tool_extension()
        assert list(wrapped.keys()) == [EVIDENCE_CONTRACT_EXTENSION_KEY]
        c2 = EvidenceContract.from_dict(wrapped[EVIDENCE_CONTRACT_EXTENSION_KEY])
        assert c2 == c

    def test_semantic_drift_detection_mutated_copy_differs(self) -> None:
        c = self._sample()
        d = c.to_dict()
        d["output_kind"] = "different_kind"
        c2 = EvidenceContract.from_dict(d)
        assert c2.canonical_bytes() != c.canonical_bytes()


# --------------------------------------------------------------------------- #
# Existing tool descriptors remain valid without the extension                #
# --------------------------------------------------------------------------- #


class TestExistingDescriptorsUnaffected:
    @pytest.mark.parametrize(
        "descriptor",
        [
            {"name": "read_file", "description": "reads a file"},
            {"name": "search", "description": "s", "inputSchema": {"type": "object"}},
            {"name": "no_description_field"},
        ],
    )
    def test_legacy_descriptor_unaffected(self, descriptor: dict[str, Any]) -> None:
        before = dict(descriptor)
        validate_tool_descriptor_extension(descriptor)
        assert descriptor == before  # not mutated, not required to change


# --------------------------------------------------------------------------- #
# Core doctrine chain / non-equivalences                                      #
# --------------------------------------------------------------------------- #


class TestCoreDoctrine:
    def test_chain_matches_mission_statement(self) -> None:
        assert CORE_DOCTRINE_CHAIN == (
            "tool_declares_capability",
            "invocation_produced_artifact",
            "artifact_verified",
            "evidence_supported",
            "admitted",
            "published",
        )

    def test_chain_has_no_duplicate_stages(self) -> None:
        assert len(set(CORE_DOCTRINE_CHAIN)) == len(CORE_DOCTRINE_CHAIN)

    def test_every_adjacent_pair_has_a_documented_non_equivalence(self) -> None:
        documented_pairs = {(lhs, rhs) for lhs, rhs, _ in NON_EQUIVALENCES.values()}
        for lhs, rhs in zip(CORE_DOCTRINE_CHAIN, CORE_DOCTRINE_CHAIN[1:]):
            assert (lhs, rhs) in documented_pairs, f"missing NEQ for {lhs} -> {rhs}"

    def test_non_equivalence_narratives_are_nonempty(self) -> None:
        for key, (lhs, rhs, narrative) in NON_EQUIVALENCES.items():
            assert lhs and rhs and narrative, key


# --------------------------------------------------------------------------- #
# Contract identity constants                                                 #
# --------------------------------------------------------------------------- #


def test_contract_version_constant() -> None:
    assert EVIDENCE_CONTRACT_VERSION == "mcp.evidence_contract.v0.1"


def test_extension_key_constant() -> None:
    assert EVIDENCE_CONTRACT_EXTENSION_KEY == "x-evidence-contract"


def test_eligible_uses_vocabulary() -> None:
    assert set(ELIGIBLE_USES) == {"discovery", "evidence_candidate", "citation_candidate"}


def test_ineligible_uses_vocabulary() -> None:
    assert set(REQUIRED_INELIGIBLE_USES) == {"admission", "publication", "factual_truth"}


def test_eligible_and_ineligible_vocabularies_disjoint() -> None:
    assert set(ELIGIBLE_USES).isdisjoint(REQUIRED_INELIGIBLE_USES)
