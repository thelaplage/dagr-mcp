"""Sprint A2 hardening — freeze the neutral package against later false parity.

The ``dagr_mcp_lifecycle`` package ships publicly but is *outside* the Sprint A1
``dagr_mcp``-only public-API snapshot. These focused tests add the smallest
executable freeze needed so the neutral package cannot later drift into claiming
parity with the A1 binding surface:

1. version identifiers are explicit and pinned (no draft/latest/mutable/unpinned);
2. the neutral package's own public surface is frozen against a committed snapshot;
3. import direction is preserved (the neutral contract never pulls the binding in);
4. the mask is a total, duplicate-free classification with full binding coverage;
5. protocol stamps are exact and pinned, with no invented MCP protocol version;
6. the existing A2 decisions (timeout subsumed, input_required unsupported, the
   mask describes rather than repairs) are preserved.

Nothing here emits into production paths, moves binding code, or introduces a
second binding. The binding remains the oracle.
"""

from __future__ import annotations

import importlib
import json
import pkgutil
import re
import subprocess
import sys
import types
from pathlib import Path
from typing import Any, get_args

import pytest

from dagr_mcp import fastmcp_binding, srs_receipts

import dagr_mcp_lifecycle
from dagr_mcp_lifecycle import binding_mask, contract

from tests.behavioral_freeze_recipe import generate_frozen_receipts

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "tests/golden/neutral_lifecycle/public_api_surface.json"

# Identifier tokens that would make a version mutable / unpinned. A pinned
# identifier must contain none of these as a standalone token.
FORBIDDEN_VERSION_TOKENS = frozenset(
    {
        "draft",
        "latest",
        "main",
        "dev",
        "snapshot",
        "unpinned",
        "mutable",
        "wildcard",
        "head",
        "nightly",
        "edge",
    }
)


def _committed_snapshot() -> dict[str, Any]:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def _tokens(identifier: str) -> set[str]:
    return {tok for tok in re.split(r"[^A-Za-z0-9]+", identifier.lower()) if tok}


def _run_import_probe(script: str) -> subprocess.CompletedProcess[str]:
    """Run an import-direction probe in a *fresh* interpreter.

    A subprocess is required: the pytest process has already imported
    ``dagr_mcp`` and ``fastmcp``, so import direction can only be observed in a
    clean interpreter.
    """

    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


# --------------------------------------------------------------------------- #
# 1. Explicit, pinned version identifiers                                      #
# --------------------------------------------------------------------------- #


def test_contract_and_mask_versions_are_explicit_and_pinned():
    # Both contracts carry explicit id + version identifiers.
    assert contract.CONTRACT_ID == "dagr.mcp.lifecycle_contract"
    assert contract.CONTRACT_VERSION == "v0.1"
    assert binding_mask.MASK_ID == "dagr.mcp.lifecycle_binding_mask"
    assert binding_mask.MASK_VERSION == "v0.1"

    # Versions are pinned vN.M, never draft/latest/mutable/unpinned.
    for version in (contract.CONTRACT_VERSION, binding_mask.MASK_VERSION):
        assert re.fullmatch(r"v\d+\.\d+", version), version

    # No identifier carries a mutable/unpinned token.
    identifiers = (
        contract.CONTRACT_ID,
        contract.CONTRACT_VERSION,
        binding_mask.MASK_ID,
        binding_mask.MASK_VERSION,
        binding_mask.MASK_BINDING_TARGET,
    )
    for identifier in identifiers:
        assert identifier, "empty identifier"
        assert not (_tokens(identifier) & FORBIDDEN_VERSION_TOKENS), identifier


def test_mask_binding_target_is_the_pinned_live_binding():
    # The mask names an exact, pinned binding target that equals the live
    # binding version and ends in a pinned vN.M.
    assert binding_mask.MASK_BINDING_TARGET == fastmcp_binding.BINDING_VERSION
    assert binding_mask.MASK_BINDING_TARGET == "fastmcp.middleware.v0.1"
    assert re.search(r"v\d+\.\d+$", binding_mask.MASK_BINDING_TARGET)
    assert binding_mask.BINDING_VERSION == binding_mask.MASK_BINDING_TARGET


# --------------------------------------------------------------------------- #
# 2. Explicit public API + committed public-surface snapshot                  #
# --------------------------------------------------------------------------- #


def test_neutral_public_api_surface_matches_committed_snapshot():
    committed = _committed_snapshot()

    names = ["dagr_mcp_lifecycle"]
    for module_info in pkgutil.walk_packages(
        dagr_mcp_lifecycle.__path__, prefix="dagr_mcp_lifecycle."
    ):
        names.append(module_info.name)

    live: dict[str, Any] = {}
    for name in sorted(names):
        module = importlib.import_module(name)
        all_ = getattr(module, "__all__", None)
        live[name] = sorted(all_) if all_ is not None else None

    assert live == committed["modules"]


def test_neutral_package_root_reexports_only_declared_submodules():
    # The root __all__ is a deliberate, submodule-only surface — no accidental
    # exports of classes / functions / constants.
    assert dagr_mcp_lifecycle.__all__ == ["contract", "binding_mask"]
    # Importing the declared names yields modules, nothing else.
    for name in dagr_mcp_lifecycle.__all__:
        value = importlib.import_module(f"dagr_mcp_lifecycle.{name}")
        assert isinstance(value, types.ModuleType), name
    # Every non-underscore attribute already bound on the root is a submodule.
    for name in dir(dagr_mcp_lifecycle):
        if name.startswith("_"):
            continue
        assert isinstance(getattr(dagr_mcp_lifecycle, name), types.ModuleType), name


def test_submodule_all_lists_are_explicit_and_deliberate():
    committed = _committed_snapshot()["modules"]
    # Both submodules define an explicit __all__ (no accidental surface).
    assert contract.__all__, "contract must declare __all__"
    assert binding_mask.__all__, "binding_mask must declare __all__"
    assert sorted(contract.__all__) == committed["dagr_mcp_lifecycle.contract"]
    assert sorted(binding_mask.__all__) == committed["dagr_mcp_lifecycle.binding_mask"]
    # __all__ has no duplicates and every name is a real attribute.
    for module in (contract, binding_mask):
        assert len(module.__all__) == len(set(module.__all__))
        for name in module.__all__:
            assert hasattr(module, name), (module.__name__, name)


def test_neutral_snapshot_is_disjoint_from_a1_dagr_mcp_snapshot():
    # The neutral freeze must not overlap module names with the frozen A1
    # dagr_mcp-only snapshot, so it can never be mistaken for A1 parity.
    a1 = json.loads(
        (ROOT / "tests/golden/behavioral_freeze/public_api_surface.json").read_text(
            encoding="utf-8"
        )
    )
    neutral_modules = set(_committed_snapshot()["modules"])
    a1_modules = set(a1["modules"])
    assert neutral_modules & a1_modules == set()
    assert all(name.startswith("dagr_mcp_lifecycle") for name in neutral_modules)
    assert all(name.startswith("dagr_mcp") and not name.startswith(
        "dagr_mcp_lifecycle") for name in a1_modules)


# --------------------------------------------------------------------------- #
# 3. Import direction                                                          #
# --------------------------------------------------------------------------- #


def test_neutral_contract_imports_without_any_binding_package():
    forbidden = ("dagr_mcp", "fastmcp", "arcs_verify", "arcs_amnesiac", "garp_sdk")
    script = (
        "import sys, importlib\n"
        "importlib.import_module('dagr_mcp_lifecycle.contract')\n"
        "roots = {k.split('.', 1)[0] for k in sys.modules}\n"
        f"forbidden = {forbidden!r}\n"
        "bad = sorted(r for r in forbidden if r in roots)\n"
        "print('BAD=' + ','.join(bad))\n"
        "sys.exit(1 if bad else 0)\n"
    )
    proc = _run_import_probe(script)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_neutral_package_root_does_not_eagerly_import_the_binding():
    # Importing the package root eagerly binds only the neutral contract; it must
    # not pull the FastMCP binding (dagr_mcp / fastmcp) into memory.
    forbidden = ("dagr_mcp", "fastmcp")
    script = (
        "import sys, importlib\n"
        "importlib.import_module('dagr_mcp_lifecycle')\n"
        "roots = {k.split('.', 1)[0] for k in sys.modules}\n"
        f"forbidden = {forbidden!r}\n"
        "bad = sorted(r for r in forbidden if r in roots)\n"
        "assert 'dagr_mcp_lifecycle' in sys.modules\n"
        "print('BAD=' + ','.join(bad))\n"
        "sys.exit(1 if bad else 0)\n"
    )
    proc = _run_import_probe(script)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_binding_mask_submodule_may_depend_on_the_binding():
    # Positive control: the mask submodule is allowed to depend on dagr_mcp, and
    # importing it does pull the binding in. This proves the direction test above
    # is meaningful, not vacuous.
    script = (
        "import sys, importlib\n"
        "importlib.import_module('dagr_mcp_lifecycle.binding_mask')\n"
        "roots = {k.split('.', 1)[0] for k in sys.modules}\n"
        "assert 'dagr_mcp' in roots, 'binding_mask should import dagr_mcp'\n"
        "sys.exit(0)\n"
    )
    proc = _run_import_probe(script)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --------------------------------------------------------------------------- #
# 4. Mapping totality                                                          #
# --------------------------------------------------------------------------- #


def test_mapping_is_total_duplicate_free_and_fully_covers_the_binding():
    # Passes only if the mask is a total, duplicate-free classification with
    # full binding-side coverage. Reads only the live oracle.
    binding_mask.verify_mapping_total()

    # Each neutral vocabulary is classified exactly once, statuses valid.
    valid = set(get_args(binding_mask.MappingStatus))
    for entries, neutral in (
        (binding_mask.DISPOSITION_MASK, contract.NEUTRAL_DISPOSITIONS),
        (binding_mask.OUTCOME_MASK, contract.NEUTRAL_OUTCOMES),
        (binding_mask.CANCELLATION_FACT_MASK, contract.NEUTRAL_CANCELLATION_FACTS),
    ):
        tokens = [e.neutral_token for e in entries]
        assert len(tokens) == len(set(tokens))  # no duplicates
        assert set(tokens) == set(neutral)  # no unclassified token
        assert all(e.status in valid for e in entries)


def test_every_binding_side_token_in_the_a1_oracle_is_represented():
    # Dispositions — the live Disposition Literal.
    live_disp = set(get_args(fastmcp_binding.Disposition))
    masked_disp = {
        e.binding_token
        for e in binding_mask.DISPOSITION_MASK
        if e.status == "direct" and e.binding_token is not None
    }
    assert masked_disp == live_disp

    # Outcomes — the tokens the live emitter can actually stamp.
    covered_out = {
        e.binding_token
        for e in binding_mask.OUTCOME_MASK
        if e.status in ("direct", "subsumed") and e.binding_token is not None
    }
    assert covered_out == set(binding_mask.BINDING_OUTCOME_TOKENS)

    # Governance — the binding-owned cancellation field registry.
    masked_fields = {
        e.binding_token
        for e in binding_mask.CANCELLATION_FACT_MASK
        if e.binding_token is not None
    }
    assert masked_fields == set(srs_receipts.CANCELLATION_FIELD_NAMES)


def test_binding_outcome_tokens_are_grounded_in_the_live_emitter(tmp_path):
    frozen = {fr.name: fr.receipt for fr in generate_frozen_receipts(tmp_path)}
    live_outcomes = {
        fr["outcome"] for name, fr in frozen.items() if name.startswith("outcome-")
    }
    assert live_outcomes == set(binding_mask.BINDING_OUTCOME_TOKENS)


def test_a_new_token_on_either_side_fails_until_classified():
    # A new binding-side disposition token fails until the mask classifies it.
    with pytest.raises(AssertionError):
        binding_mask.verify_mapping_total(
            live_dispositions=set(get_args(fastmcp_binding.Disposition))
            | {"quarantined"}
        )
    # A new binding-side outcome token fails until classified.
    with pytest.raises(AssertionError):
        binding_mask.verify_mapping_total(
            live_outcome_tokens=set(binding_mask.BINDING_OUTCOME_TOKENS)
            | {"escalated"}
        )
    # A new binding-side governance field fails until classified.
    with pytest.raises(AssertionError):
        binding_mask.verify_mapping_total(
            live_cancellation_fields=set(srs_receipts.CANCELLATION_FIELD_NAMES)
            | {"aborted"}
        )
    # A new neutral outcome token fails until the mask classifies it.
    with pytest.raises(AssertionError):
        binding_mask.verify_mapping_total(
            neutral_outcomes=contract.NEUTRAL_OUTCOMES + ("resumed",)
        )
    # A new neutral disposition token fails until classified.
    with pytest.raises(AssertionError):
        binding_mask.verify_mapping_total(
            neutral_dispositions=contract.NEUTRAL_DISPOSITIONS + ("held",)
        )
    # Sanity: with the real oracle the totality proof passes.
    binding_mask.verify_mapping_total()


# --------------------------------------------------------------------------- #
# 5. Protocol stamps                                                           #
# --------------------------------------------------------------------------- #


def test_protocol_stamps_are_pinned_with_no_invented_version(tmp_path):
    # The discipline holds: every declared stamp is a non-empty pinned identifier.
    binding_mask.assert_protocol_stamps_pinned()

    # Only the exact observable protocol-binding token is pinned.
    assert binding_mask.OBSERVED_PROTOCOL_BINDING == "mcp"
    assert (
        binding_mask.PROTOCOL_STAMPS["protocol_binding"]
        == binding_mask.OBSERVED_PROTOCOL_BINDING
    )
    assert binding_mask.classify_protocol_stamp("mcp") == "pinned"

    # No invented MCP protocol version: not declared, classified unsupported.
    assert "protocol_version" not in binding_mask.PROTOCOL_STAMPS
    assert binding_mask.NEGOTIATED_MCP_PROTOCOL_VERSION_STATUS == "unsupported"

    # Grounded: a live emitted record carries exactly the pinned protocol_binding
    # and no protocol-version field.
    receipt = {fr.name: fr.receipt for fr in generate_frozen_receipts(tmp_path)}[
        "admission-admitted"
    ]
    assert receipt["protocol_binding"] == binding_mask.OBSERVED_PROTOCOL_BINDING
    assert "protocol_version" not in receipt
    assert "protocolVersion" not in receipt


def test_empty_draft_latest_wildcard_inferred_stamps_are_unsupported():
    for bad in binding_mask.REJECTED_PROTOCOL_STAMP_FORMS:
        assert binding_mask.classify_protocol_stamp(bad) == "unsupported", bad
    assert binding_mask.classify_protocol_stamp(None) == "unsupported"
    assert binding_mask.classify_protocol_stamp("mcp/2025-06-18") == "unsupported"
    # The rejected-forms list explicitly names the required cases.
    for form in ("", "draft", "latest", "*", "inferred"):
        assert form in binding_mask.REJECTED_PROTOCOL_STAMP_FORMS


def test_the_binding_never_stamps_a_protocol_version_field():
    # The mask must not invent a version the binding cannot observe. Prove the
    # binding source never references an MCP protocol-version field, so there is
    # nothing to observe.
    package = ROOT / "dagr_mcp"
    needles = ("protocol_version", "protocolVersion", "protocol-version")
    offenders: list[str] = []
    for path in package.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(needle in text for needle in needles):
            offenders.append(path.name)
    assert offenders == [], offenders


# --------------------------------------------------------------------------- #
# 6. Preserved A2 decisions                                                    #
# --------------------------------------------------------------------------- #


def test_timeout_remains_subsumed_by_exception_with_timeouterror(tmp_path):
    entry = binding_mask.project_outcome("timeout")
    assert entry.status == "subsumed"
    assert entry.binding_token == "exception"
    frozen = {fr.name: fr.receipt for fr in generate_frozen_receipts(tmp_path)}
    exc = frozen["outcome-exception"]
    assert exc["outcome"] == "exception"
    assert exc["extensions"]["mcp"]["exception_class"] == "TimeoutError"
    # Timeout carries no dedicated binding disposition token.
    assert "timeout" not in binding_mask.BINDING_OUTCOME_TOKENS


def test_input_required_modes_remain_neutral_but_unsupported():
    # Both modes are still part of the neutral contract...
    assert contract.INPUT_REQUIRED_MODES == ("continuable", "interrupted")
    # ...and both remain unsupported by the current FastMCP mask.
    assert {e.neutral_token for e in binding_mask.INPUT_REQUIRED_MASK} == set(
        contract.INPUT_REQUIRED_MODES
    )
    assert all(e.status == "unsupported" for e in binding_mask.INPUT_REQUIRED_MASK)
    assert all(e.binding_token is None for e in binding_mask.INPUT_REQUIRED_MASK)
    assert binding_mask.project_outcome("input_required").status == "unsupported"


def test_mask_describes_the_binding_and_does_not_repair_it():
    # No unsupported entry is silently repaired onto an adjacent binding token.
    for entries in (
        binding_mask.OUTCOME_MASK,
        binding_mask.INPUT_REQUIRED_MASK,
        binding_mask.DISPOSITION_MASK,
        binding_mask.CANCELLATION_FACT_MASK,
    ):
        for entry in entries:
            if entry.status == "unsupported":
                assert entry.binding_token is None, entry
            else:
                assert entry.binding_token is not None, entry
    # The drift guard ties every claim back to the live oracle.
    binding_mask.verify_mask_matches_binding()
