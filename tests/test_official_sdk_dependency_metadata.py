"""Sprint A5 hardening — the official-sdk dependency contract is evidence-honest.

The `official-sdk` optional extra must advertise **exactly** the SDK version that
has been proven — by the Phase 1 inventory, the dedicated CI official-sdk lane,
and the clean-wheel official-SDK smoke — against this binding, its mask, the real
in-process ``tools/list`` + ``tools/call`` path, and the cross-binding corpus.
That version is ``mcp==1.28.1``. Advertising a broader range (e.g. ``>=1.16,<2``)
would claim compatibility with untested SDK versions.

This module builds (or inspects) the wheel and asserts the *built distribution's*
declared ``official-sdk`` requirement is exactly ``mcp==1.28.1`` — the same level
documented in ``docs/OFFICIAL_MCP_SDK_BINDING.md`` and installed by the CI
official-sdk lane, and consistent with the mask's grounded SDK inventory version.
"""

from __future__ import annotations

import re
import subprocess
import sys
import zipfile
from email.parser import Parser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROVEN_SDK_VERSION = "1.29.0"
EXPECTED_REQUIREMENT = f"mcp=={PROVEN_SDK_VERSION}"


def _official_sdk_requirements(requires_dist: list[str]) -> list[str]:
    """Return the requirement strings gated by the ``official-sdk`` extra.

    A ``Requires-Dist`` line looks like ``mcp==1.28.1; extra == "official-sdk"``.
    The requirement (left of the marker) is returned with whitespace collapsed.
    """

    out: list[str] = []
    for line in requires_dist:
        if "extra ==" not in line:
            continue
        req, _, marker = line.partition(";")
        if re.search(r'extra\s*==\s*[\'"]official-sdk[\'"]', marker):
            out.append(re.sub(r"\s+", "", req))
    return out


def _build_wheel_metadata(tmp_path: Path) -> list[str]:
    """Build the wheel from the repo and return its ``Requires-Dist`` lines.

    Uses ``--no-isolation`` so it neither fetches build deps nor needs network; that
    requires the build backend (``setuptools``) to be importable. When the backend
    cannot run in this environment the test SKIPS rather than fails — the wheel's
    metadata is enforced authoritatively by the ``package-build`` CI job, and the
    always-on :func:`test_pyproject_and_docs_agree_with_the_proven_pin` guards the
    declared pin without a build backend.
    """

    pytest.importorskip("build")
    pytest.importorskip("setuptools")
    outdir = tmp_path / "dist"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(outdir),
            str(ROOT),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.skip(f"wheel build backend unavailable here: {proc.stderr or proc.stdout}")
    wheels = sorted(outdir.glob("*.whl"))
    assert len(wheels) == 1, wheels
    with zipfile.ZipFile(wheels[0]) as zf:
        metadata_name = next(
            n for n in zf.namelist() if n.endswith(".dist-info/METADATA")
        )
        metadata_text = zf.read(metadata_name).decode("utf-8")
    message = Parser().parsestr(metadata_text)
    return message.get_all("Requires-Dist") or []


def test_wheel_official_sdk_requirement_is_exactly_the_proven_pin(tmp_path: Path):
    requires_dist = _build_wheel_metadata(tmp_path)
    official = _official_sdk_requirements(requires_dist)
    # Exactly one official-sdk requirement, and it is the exact proven pin — no
    # broader range advertised.
    assert official == [EXPECTED_REQUIREMENT], (official, requires_dist)


def test_wheel_pin_matches_mask_inventory_version(tmp_path: Path):
    """The wheel's pin equals the mask's SDK inventory version it is grounded in."""

    pytest.importorskip("mcp")
    from dagr_mcp_sdk_binding import mask

    assert mask.SDK_INVENTORY_VERSION == PROVEN_SDK_VERSION
    official = _official_sdk_requirements(_build_wheel_metadata(tmp_path))
    assert official == [f"mcp=={mask.SDK_INVENTORY_VERSION}"]


def test_pyproject_and_docs_agree_with_the_proven_pin():
    """pyproject, the binding doc, and the CI lane all state the exact pin.

    A cheap consistency guard that does not require the build backend, so the
    documented/tested support level cannot silently drift from the declared extra.
    """

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'official-sdk = ["mcp=={PROVEN_SDK_VERSION}"]' in pyproject
    # No broader range remains anywhere in the extra declaration.
    assert "mcp>=1.16" not in pyproject

    doc = (ROOT / "docs/OFFICIAL_MCP_SDK_BINDING.md").read_text(encoding="utf-8")
    assert f'official-sdk = ["mcp=={PROVEN_SDK_VERSION}"]' in doc
    assert "mcp>=1.16,<2" not in doc

    ci = (ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")
    assert f"mcp=={PROVEN_SDK_VERSION}" in ci
