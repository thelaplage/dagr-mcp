"""Packaging regression: SDK-v2 must express dagr-sdk as a package-version
requirement, never a source-transport (git+/direct-URL) pin.

DAGR-MCP-SDKV2-OFFLINE-DEPENDENCY0. A `dagr-sdk @ git+https://...` direct
reference forced pip to `git clone` from GitHub at install time, which broke
offline/vendored installs (e.g. the LIVE0 `python:3.12-slim` image, which has
no `git`). The runtime compatibility contract this package expresses is a
*version* (``dagr-sdk==0.1.0``); the exact source *provenance* (commit) is a
consumer/build concern and must not leak into this package's metadata as a
network transport.

This inspects the REAL built wheel metadata (setuptools backend, no build
isolation so no network fetch), not just the pyproject source text, so it
catches a direct-URL requirement regardless of how it is spelled.
"""

from __future__ import annotations

from pathlib import Path

from build.util import project_wheel_metadata

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def _runtime_requires_dist() -> list[str]:
    metadata = project_wheel_metadata(_PACKAGE_ROOT, isolated=False)
    assert metadata.get("Name") == "dagr-mcp-sdk-v2"
    # Only unconditional (non-extra) runtime requirements.
    return [
        req
        for req in (metadata.get_all("Requires-Dist") or [])
        if "extra ==" not in req
    ]


def test_dagr_sdk_is_a_version_requirement_not_a_url() -> None:
    requires = _runtime_requires_dist()
    dagr_sdk = [r for r in requires if r.split()[0].split("==")[0].split("@")[0].strip() == "dagr-sdk"]
    assert dagr_sdk == ["dagr-sdk==0.1.0"], (
        "SDK-v2 must require dagr-sdk by version, exactly 'dagr-sdk==0.1.0'; "
        f"got {dagr_sdk!r}"
    )


def test_no_direct_url_transport_for_dagr_sdk() -> None:
    requires = _runtime_requires_dist()
    for req in requires:
        assert "git+" not in req, f"no VCS transport allowed in metadata: {req!r}"
        assert "@ " not in req, f"no direct-URL (PEP 508 '@') requirement allowed: {req!r}"


def test_isolation_and_core_deps_preserved() -> None:
    requires = set(_runtime_requires_dist())
    assert "mcp==2.0.0" in requires, "mcp==2.0.0 isolation pin must be preserved"
    assert "dagr-mcp-core" in requires, "dagr-mcp-core dependency must be preserved"
