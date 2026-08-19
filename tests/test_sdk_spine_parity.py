from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = ROOT / "SPINE_SOURCE.json"
PROJECTED_PATH = ROOT / "dagr_mcp" / "sdk_spine.py"


def _git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()  # noqa: S324 - Git object identity


def test_sdk_spine_projection_matches_pinned_canonical_blob() -> None:
    pin = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    assert pin["schema"] == "dagr.sdk-spine-pin.v0.1"
    assert pin["authority"] == {
        "repository": "thelaplage/dagr-sdk",
        "path": "dagr_sdk/sdk_spine.py",
        "commit": "bd8606e609246c53ef74d9c90a529aa737206585",
        "git_blob_sha": "d69a72aa8af2e3d6f7104889f090472bb2cbbbda",
    }
    assert pin["projection"] == {
        "path": "dagr_mcp/sdk_spine.py",
        "mode": "byte_exact_generated_mirror",
        "independent_edits_allowed": False,
    }
    assert _git_blob_sha(PROJECTED_PATH.read_bytes()) == pin["authority"]["git_blob_sha"]
