"""Permanent guard: the canonical enforcement harness must not depend on the monolith.

``dagr_mcp.enforcement_harness`` was extracted from garp-local's
``garp_core.enforcement_harness`` so downstream adapters (e.g. arcs-anchor's
MCP harness adapter) can consume a canonical SDK harness instead of importing
the monolith. That guarantee only holds if the extracted module - and its
transitive import closure - never reaches back into ``garp_core`` or any
sibling-repo internals.

The guarantee is about *dependency*, not the literal token: the module
docstring intentionally names its monolith origin
(``garp_core.enforcement_harness``) for provenance. What must never
exist is a `garp_core` (or sibling-repo) **import**, directly or in the
transitive closure.

It is permanent. Any helper the harness needs lives inside ``dagr_mcp``.
"""

from __future__ import annotations

import re
from pathlib import Path

import dagr_mcp.enforcement_harness as harness


FORBIDDEN_IMPORT_PATTERNS: list[tuple[str, str]] = [
    (r"^\s*import\s+garp_core(\.|\s|$)", "imports garp_core"),
    (r"^\s*from\s+garp_core(\.|\s)", "imports from garp_core"),
    (r"^\s*import\s+garp_local(\.|\s|$)", "imports garp_local"),
    (r"^\s*from\s+garp_local(\.|\s)", "imports from garp_local"),
    (r"^\s*import\s+arcs_amnesiac(\.|\s|$)", "imports arcs_amnesiac"),
    (r"^\s*from\s+arcs_amnesiac(\.|\s)", "imports from arcs_amnesiac"),
    (r"^\s*import\s+arcs_anchor(\.|\s|$)", "imports arcs_anchor"),
    (r"^\s*from\s+arcs_anchor(\.|\s)", "imports from arcs_anchor"),
    (r"^\s*import\s+garp_boundary(\.|\s|$)", "imports garp_boundary"),
    (r"^\s*from\s+garp_boundary(\.|\s)", "imports from garp_boundary"),
]


def _harness_source_path() -> Path:
    path = Path(harness.__file__)
    assert path.name == "enforcement_harness.py", f"unexpected module file: {path}"
    return path


def test_harness_source_has_no_garp_core_or_sibling_imports() -> None:
    source = _harness_source_path().read_text(encoding="utf-8")
    offenders: list[str] = []
    for line_no, line in enumerate(source.splitlines(), start=1):
        for pattern, label in FORBIDDEN_IMPORT_PATTERNS:
            if re.search(pattern, line):
                offenders.append(f"enforcement_harness.py:{line_no}: {label}: {line.strip()}")
    assert not offenders, (
        "dagr_mcp.enforcement_harness must not import garp_core or sibling-repo "
        "internals:\n" + "\n".join(offenders)
    )


def test_harness_import_closure_excludes_garp_core() -> None:
    """The transitive import closure of the harness must not pull in garp_core.

    Importing ``dagr_mcp.enforcement_harness`` (done at module load above)
    must not, directly or transitively, register any ``garp_core`` /
    sibling-repo module in ``sys.modules``.
    """
    import sys

    forbidden_roots = (
        "garp_core",
        "garp_local",
        "arcs_amnesiac",
        "arcs_anchor",
        "garp_boundary",
    )
    leaked = sorted(
        name
        for name in sys.modules
        if name == "" or name.split(".", 1)[0] in forbidden_roots
    )
    assert not leaked, (
        "importing dagr_mcp.enforcement_harness leaked forbidden modules into "
        f"sys.modules: {leaked}"
    )


def test_harness_exposes_expected_sdk_exports() -> None:
    """The extracted module exports the canonical harness surface."""
    for symbol in ("wrap_handler", "HarnessConfig", "HarnessSinks", "ToolPolicy"):
        assert symbol in harness.__all__, f"{symbol} missing from __all__"
        assert hasattr(harness, symbol), f"{symbol} not exported by module"
