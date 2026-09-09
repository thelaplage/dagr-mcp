from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"


def _dagr_sdk_requirements() -> list[str]:
    payload = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    dependencies = payload["project"]["dependencies"]
    assert isinstance(dependencies, list)
    return [
        item
        for item in dependencies
        if isinstance(item, str)
        and item.split(";", 1)[0].strip().lower().startswith("dagr-sdk")
    ]


def test_top_level_dagr_sdk_dependency_is_version_requirement() -> None:
    assert _dagr_sdk_requirements() == ["dagr-sdk==0.1.0"]


def test_top_level_dagr_sdk_dependency_has_no_network_transport() -> None:
    requirement = _dagr_sdk_requirements()[0].lower()
    assert "git+" not in requirement
    assert "http://" not in requirement
    assert "https://" not in requirement
    assert " @ " not in requirement
