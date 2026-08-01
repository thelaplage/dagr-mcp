"""Packaging inventory guards for the two distributions under ``packages/``.

Both distributions deliberately ship a runnable test surface in their sdists.
That intent is only real if every helper and fixture the shipped tests import
travels with them -- and it silently was not: setuptools' default sdist rules
ship ``tests/test*.py`` and nothing else, so ``dagr-mcp-core`` shipped tests that
could not import ``receipt_verification`` and had no ``tests/vendor/``, and
``dagr-mcp-sdk-v2`` shipped four test modules that could not import
``harness``. Each package now carries a ``MANIFEST.in``; these tests are what
keep it honest.

The guards below fail when:

* a shipped test imports a sibling helper module that is absent from the sdist;
* a shipped test reads a fixture directory that is absent from the sdist;
* ``dagr-mcp-core``'s vendored envelope schemas are missing;
* ``dagr-mcp-sdk-v2``'s ``tests/harness.py`` is missing;
* either wheel acquires test files (wheels stay runtime-only);
* either sdist acquires unrelated repository material.

Each package is copied to a temporary directory before building, so a build
never writes ``build/`` or ``*.egg-info`` into the working tree.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("build", reason="the `build` frontend is required to build dists")

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("dagr-mcp-core", "dagr-mcp-sdk-v2")

# Everything a distribution's sdist is allowed to contain, as top-level paths
# relative to the sdist root. Anything else is unrelated repository material.
ALLOWED_SDIST_ROOTS = {"src", "tests"}
ALLOWED_SDIST_FILES = {
    "LICENSE",
    "MANIFEST.in",
    "PKG-INFO",
    "README.md",
    "pyproject.toml",
    "setup.cfg",
}

# Build artifacts and caches that must never be copied into a build, nor appear
# in a produced sdist.
NEVER_SHIP = ("__pycache__", ".pyc", ".pyo", ".so", ".egg-info", ".venv", ".DS_Store")

_IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.py[cod]", "*.egg-info", "build", "dist", ".venv", ".pytest_cache"
)


def _has_setuptools() -> bool:
    """Can this interpreter host the build backend without isolation?"""

    return (
        subprocess.run(
            [sys.executable, "-c", "import setuptools"], capture_output=True
        ).returncode
        == 0
    )


def _build(package: str, destination: Path) -> tuple[Path, Path]:
    """Copy *package* out of the tree, build both artifacts, return their paths.

    Builds without isolation when this interpreter already provides the
    setuptools backend -- that keeps the guard fast and offline. Otherwise it
    falls back to an isolated build, which provisions the backend itself.
    """

    source = destination / "src-copy"
    shutil.copytree(REPO_ROOT / "packages" / package, source, ignore=_IGNORE)
    outdir = destination / "dist"
    command = [sys.executable, "-m", "build", "--outdir", str(outdir), str(source)]
    if _has_setuptools():
        command.insert(3, "--no-isolation")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.fail(
            f"building {package} failed:\n"
            f"command: {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    sdist = next(iter(outdir.glob("*.tar.gz")))
    wheel = next(iter(outdir.glob("*.whl")))
    return sdist, wheel


def _sdist_members(sdist: Path) -> set[str]:
    """Sdist member paths, relative to the single ``NAME-VERSION/`` root."""

    with tarfile.open(sdist) as archive:
        names = [n for n in archive.getnames() if "/" in n]
    return {n.split("/", 1)[1] for n in names if n.split("/", 1)[1]}


def _wheel_members(wheel: Path) -> set[str]:
    return set(zipfile.ZipFile(wheel).namelist())


def _sibling_helper_imports(test_source: str, available: set[str]) -> set[str]:
    """Top-level modules imported by *test_source* that are sibling helpers."""

    tree = ast.parse(test_source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
    return imported & available


@pytest.fixture(scope="module", params=PACKAGES)
def built(request, tmp_path_factory):
    package = request.param
    destination = tmp_path_factory.mktemp(package.replace("-", "_"))
    sdist, wheel = _build(package, destination)
    return package, sdist, wheel


# --------------------------------------------------------------------------- #
# The sdist test surface is self-contained                                     #
# --------------------------------------------------------------------------- #


def test_every_shipped_test_can_import_its_helpers(built, tmp_path):
    """A shipped test must never import a helper the sdist omits.

    This is the exact defect that shipped: the tests were present, the helper
    they imported was not, and nothing failed until someone extracted the sdist.
    """

    package, sdist, _wheel = built
    with tarfile.open(sdist) as archive:
        archive.extractall(tmp_path, filter="data")
    root = next(iter(tmp_path.iterdir()))
    tests = root / "tests"
    assert tests.is_dir(), f"{package}: sdist ships no tests/ directory"

    # Sibling helpers are the non-test modules sitting beside the shipped tests.
    helpers = {p.stem for p in tests.glob("*.py") if not p.name.startswith("test_")}
    shipped_tests = sorted(tests.glob("test_*.py"))
    assert shipped_tests, f"{package}: sdist ships no test modules"

    # Any sibling module a shipped test imports must itself be shipped. Compare
    # against the union of shipped helpers and every helper in the working tree,
    # so a helper that exists in-tree but was dropped from the sdist is caught.
    in_tree = {
        p.stem
        for p in (REPO_ROOT / "packages" / package / "tests").glob("*.py")
        if not p.name.startswith("test_")
    }
    for test_file in shipped_tests:
        needed = _sibling_helper_imports(test_file.read_text(encoding="utf-8"), in_tree)
        missing = needed - helpers
        assert not missing, (
            f"{package}: {test_file.name} imports {sorted(missing)}, "
            f"which the sdist does not ship"
        )


def test_shipped_tests_resolve_fixtures_inside_their_own_sdist(built):
    """No shipped test may reach a sibling package or above its own root."""

    package, sdist, _wheel = built
    offenders: list[str] = []
    with tarfile.open(sdist) as archive:
        for member in archive.getmembers():
            relative = member.name.split("/", 1)[1] if "/" in member.name else ""
            if not (relative.startswith("tests/") and relative.endswith(".py")):
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            tree = ast.parse(extracted.read().decode("utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if node.value in PACKAGES or node.value.startswith(".."):
                        offenders.append(f"{relative}:{node.lineno}: {node.value!r}")
                if isinstance(node, ast.Subscript) and getattr(node.value, "attr", None) == "parents":
                    index = getattr(node.slice, "value", None)
                    if isinstance(index, int) and index >= 2:
                        offenders.append(f"{relative}:{node.lineno}: parents[{index}]")
    assert not offenders, f"{package}: shipped tests reach outside the sdist: {offenders}"


def test_core_sdist_ships_its_vendored_schemas(built):
    package, sdist, _wheel = built
    if package != "dagr-mcp-core":
        pytest.skip("core-specific fixture requirement")
    members = _sdist_members(sdist)
    for schema in (
        "tests/vendor/srs-envelope-v0.2.0.schema.json",
        "tests/vendor/srs-envelope-v0.2.1.schema.json",
    ):
        assert schema in members, f"core sdist omits {schema}"
    assert "tests/receipt_verification.py" in members


def test_sdk_v2_sdist_ships_harness_and_fixtures(built):
    package, sdist, _wheel = built
    if package != "dagr-mcp-sdk-v2":
        pytest.skip("sdk-v2-specific fixture requirement")
    members = _sdist_members(sdist)
    for required in (
        "tests/harness.py",
        "tests/golden/result_digest_vectors.json",
        "tests/vendor/srs-envelope-v0.2.1.schema.json",
    ):
        assert required in members, f"sdk-v2 sdist omits {required}"


# --------------------------------------------------------------------------- #
# Wheels stay runtime-only; sdists stay scoped to their own package            #
# --------------------------------------------------------------------------- #


def test_wheel_is_runtime_only(built):
    """A wheel must never acquire tests, helpers, or test fixtures."""

    package, _sdist, wheel = built
    members = _wheel_members(wheel)
    leaked = [
        name
        for name in members
        if name.startswith("tests/")
        or "/tests/" in name
        or Path(name).name in {"harness.py", "receipt_verification.py"}
        or "/vendor/" in name
        or "/golden/" in name
    ]
    assert not leaked, f"{package}: wheel acquired test material: {sorted(leaked)}"


def test_sdist_contains_no_unrelated_repository_material(built):
    package, sdist, _wheel = built
    unrelated: list[str] = []
    for relative in sorted(_sdist_members(sdist)):
        head = relative.split("/", 1)[0]
        if head in ALLOWED_SDIST_ROOTS or relative in ALLOWED_SDIST_FILES:
            continue
        unrelated.append(relative)
    assert not unrelated, f"{package}: sdist contains unrelated material: {unrelated}"


def test_neither_artifact_ships_caches_or_build_output(built):
    package, sdist, wheel = built
    for label, members in (("sdist", _sdist_members(sdist)), ("wheel", _wheel_members(wheel))):
        # `.egg-info` is a legitimate, setuptools-generated part of an sdist.
        forbidden = [
            name
            for name in members
            if any(token in name for token in NEVER_SHIP)
            and not (label == "sdist" and ".egg-info" in name)
        ]
        assert not forbidden, f"{package}: {label} ships build/cache output: {sorted(forbidden)}"
