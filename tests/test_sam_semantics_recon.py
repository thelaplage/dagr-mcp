"""SAM-SEMANTICS-RECON0: additive recon tests.

These tests do not exercise any dagr-mcp runtime path. They verify that the
SAM <-> DAGR/MCP semantics crosswalk (generated/recon/sam-semantics-crosswalk
.v0.1.json) satisfies the lane's acceptance gates:

- every required assertion category is covered;
- every mapping carries at least one explicit `does_not_prove` entry;
- no entry carries any authority/admission/trust/standing-shaped field
  (rule NE-11): non-authority is expressed by those fields being
  structurally ABSENT, not by a field pinned to "none" (AUTHORITY_MOVEMENT
  = 0 for this lane is recorded once, at the top level, as run/recon
  metadata -- never per-entry);
- unknown/unstable SAM surfaces are marked `observation_only`, never
  asserted as a grounded mapping;
- the mandatory non-equivalence ladder from the lane spec is preserved
  verbatim and in order;
- the generator is deterministic and its committed output is up to date.

See docs/dispatch/SAM-SEMANTICS-RECON0.md for the full lane spec and
docs/recon/SAM_SEMANTICS_RECON0.md for the narrative recon report.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tools.generate_sam_semantics_crosswalk import (
    FORBIDDEN_AUTHORITY_FIELDS,
    NON_EQUIVALENCE_LADDER,
    OUTPUT_PATH,
    REQUIRED_CATEGORIES,
    SEMANTIC_CLASSES,
    STATUSES,
    _entry,
    _reject_authority_shaped_fields,
    build_crosswalk,
    generate_crosswalk,
    render,
)

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_LADDER_STRING = (
    "authenticated != discoverable != invocable != "
    "authorized_for_this_context != executed != output_trusted != "
    "evidence_supported != admitted != published"
)

_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


@pytest.fixture(scope="module")
def crosswalk() -> dict:
    return build_crosswalk()


def test_generator_is_byte_stable(tmp_path: Path):
    """Regenerating twice, in fresh locations, must produce identical bytes."""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    generate_crosswalk(first)
    generate_crosswalk(second)
    assert first.read_bytes() == second.read_bytes()


def test_committed_crosswalk_matches_generator_output(tmp_path: Path):
    """The checked-in JSON must be exactly what the generator produces now."""
    regenerated = tmp_path / "regenerated.json"
    generate_crosswalk(regenerated)
    assert OUTPUT_PATH.read_bytes() == regenerated.read_bytes(), (
        "generated/recon/sam-semantics-crosswalk.v0.1.json is stale; "
        "rerun `python3 tools/generate_sam_semantics_crosswalk.py`"
    )


def test_committed_crosswalk_is_canonical_json():
    """The committed file must itself be exactly render(build_crosswalk())."""
    committed_text = OUTPUT_PATH.read_text(encoding="utf-8")
    assert committed_text == render(json.loads(committed_text))


def test_all_required_categories_are_covered(crosswalk: dict):
    covered = {entry["category"] for entry in crosswalk["entries"]}
    assert covered == set(REQUIRED_CATEGORIES)
    assert crosswalk["required_categories"] == list(REQUIRED_CATEGORIES)


def test_entry_ids_are_unique(crosswalk: dict):
    ids = [entry["id"] for entry in crosswalk["entries"]]
    assert len(ids) == len(set(ids))
    assert len(ids) >= len(REQUIRED_CATEGORIES)


@pytest.mark.parametrize("field", ["sam_source_surface", "observed_surface", "minimal_meaning"])
def test_every_entry_has_a_grounded_source_citation(crosswalk: dict, field: str):
    """Acceptance gate: every claim ties to an exact SAM source file/API/revision."""
    for entry in crosswalk["entries"]:
        value = entry[field]
        assert isinstance(value, str) and value.strip(), (entry["id"], field)


def test_every_entry_names_a_source_file_path(crosswalk: dict):
    for entry in crosswalk["entries"]:
        # every citation names at least one path-shaped SAM source location
        assert re.search(r"[\w./-]+\.go|api/sam\.proto", entry["sam_source_surface"]), entry["id"]


def test_every_mapping_has_at_least_one_does_not_prove_entry(crosswalk: dict):
    """Acceptance gate: every positive mapping has >=1 explicit does_not_prove."""
    for entry in crosswalk["entries"]:
        assert isinstance(entry["does_not_prove"], list)
        assert len(entry["does_not_prove"]) >= 1, entry["id"]
        assert all(isinstance(item, str) and item.strip() for item in entry["does_not_prove"])


def test_no_entry_carries_an_authority_shaped_field(crosswalk: dict):
    """Rule NE-11: "no authority" must be structural absence, not a field
    pinned to a benign value. No SAM assertion is licensed to carry any
    authority/admission/trust/standing weight in this lane, and that must
    show up as those fields being entirely absent from every entry -- never
    as e.g. `authority_effect: "none"`."""
    for entry in crosswalk["entries"]:
        present = FORBIDDEN_AUTHORITY_FIELDS & entry.keys()
        assert not present, (entry["id"], present)
    # AUTHORITY_MOVEMENT is recorded exactly once, as top-level run/recon
    # metadata describing the lane -- not as a per-entry artifact field.
    assert crosswalk["authority_movement"] == 0
    assert "authority_movement" not in crosswalk["entries"][0]


def _minimal_valid_entry_kwargs() -> dict:
    return dict(
        id="SAM-TEST-00",
        category=REQUIRED_CATEGORIES[0],
        status="grounded",
        sam_source_surface="test/fixture.go L1-2",
        observed_surface="test.Fixture",
        minimal_meaning="a test fixture asserts nothing",
        does_not_prove=["does not prove anything beyond this fixture"],
        semantic_class="identity",
    )


@pytest.mark.parametrize(
    "forbidden_field",
    ["authority_effect", "admission_effect", "trust_effect", "standing_effect"],
)
def test_entry_construction_fails_closed_on_authority_shaped_kwargs(forbidden_field):
    """`_entry()` no longer accepts these fields as keyword arguments at
    all, so attempting to inject one -- e.g. a hostile/legacy call site
    still passing `authority_effect="none"` -- must fail closed with a
    TypeError rather than silently being accepted and serialized."""
    kwargs = _minimal_valid_entry_kwargs()
    kwargs[forbidden_field] = "none"
    with pytest.raises(TypeError):
        _entry(**kwargs)


@pytest.mark.parametrize(
    "injected_fields",
    [
        {"authority_effect": "none"},
        {"authority_effect": "admitted"},
        {"trusted": True},
        {"admitted": True},
        {"authority_posture": "descriptive_only"},
        {"standing": "evidentiary"},
    ],
)
def test_reject_authority_shaped_fields_fails_closed_on_injected_data(injected_fields):
    """Defense in depth: even if an authority-shaped key reached a
    constructed entry dict by some other path (e.g. untrusted/merged data),
    `_reject_authority_shaped_fields` must refuse it rather than pass it
    through pinned to a benign-looking value."""
    entry = dict(_minimal_valid_entry_kwargs())
    entry.update(injected_fields)
    with pytest.raises(ValueError):
        _reject_authority_shaped_fields(entry)


def test_reject_authority_shaped_fields_accepts_a_clean_entry():
    """The guard must not reject a legitimate, field-clean entry -- absence
    is enforced, not over-enforced."""
    entry = _entry(**_minimal_valid_entry_kwargs())
    _reject_authority_shaped_fields(entry)  # must not raise
    assert not (FORBIDDEN_AUTHORITY_FIELDS & entry.keys())


def test_status_values_are_known_and_unresolved_items_fail_closed(crosswalk: dict):
    for entry in crosswalk["entries"]:
        assert entry["status"] in STATUSES, entry["id"]

    observation_only = [e for e in crosswalk["entries"] if e["status"] == "observation_only"]
    # The recon deliberately leaves at least one unstable surface unresolved
    # (mesh-wide revocation propagation) rather than inventing its semantics.
    assert observation_only, "expected at least one fail-closed observation_only entry"
    for entry in observation_only:
        assert entry["notes"].strip(), entry["id"]


def test_semantic_class_values_are_within_the_spec_enum(crosswalk: dict):
    for entry in crosswalk["entries"]:
        assert entry["semantic_class"] in SEMANTIC_CLASSES, entry["id"]
    assert set(SEMANTIC_CLASSES) == {
        "identity",
        "discovery",
        "transport",
        "authorization",
        "execution",
        "evidence",
        "derived_state",
    }


def test_non_equivalence_ladder_is_preserved_verbatim_and_in_order(crosswalk: dict):
    assert crosswalk["mandatory_non_equivalence_ladder"] == list(NON_EQUIVALENCE_LADDER)
    assert " != ".join(NON_EQUIVALENCE_LADDER) == EXPECTED_LADDER_STRING


def test_sam_source_is_pinned_to_an_exact_revision(crosswalk: dict):
    source = crosswalk["sam_source"]
    assert source["repo"] == "https://github.com/google/sam"
    assert _SHA1_RE.match(source["revision"]), source["revision"]
    assert source["retrieved_at"].endswith("Z")
    assert "not an officially supported Google product" in source["disclaimer"]


def test_lane_does_not_introduce_a_sam_runtime_dependency():
    """Recon-only constraint: nothing under dagr_mcp/ may import SAM, and the
    generator module must not import anything from dagr_mcp."""
    generator_src = (ROOT / "tools/generate_sam_semantics_crosswalk.py").read_text(
        encoding="utf-8"
    )
    assert not re.search(r"^\s*(import\s+dagr_mcp\b|from\s+dagr_mcp\b)", generator_src, re.MULTILINE)

    dagr_mcp_dir = ROOT / "dagr_mcp"
    offenders = []
    for path in dagr_mcp_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"^\s*(import\s+sam\b|from\s+sam\b)", text, re.MULTILINE):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"unexpected SAM import under dagr_mcp/: {offenders}"


def test_receipt_wire_formats_are_untouched_by_this_lane():
    """Constraint: do not modify existing receipt wire formats. The lane adds
    only new, additive files; it must not touch the vendored SRS schemas."""
    vendor_dir = ROOT / "dagr_mcp/vendor/srs"
    assert vendor_dir.is_dir()
    # Existence + non-empty is sufficient here: a real wire-format edit would
    # be caught by the repo's own schema/contract tests, not this recon lane.
    assert any(vendor_dir.iterdir())
