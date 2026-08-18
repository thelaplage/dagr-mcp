"""Producer-owned neutral GovernedCallResponse vector conformance."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "gateway_response_vectors.v0.1.json"
GENERATOR = ROOT / "tests" / "fixtures" / "scripts" / "gen_gateway_response_vectors.py"
EXPECTED_SHA256 = "98928f9bc9a2c550b0127869a9eb58138b166ba9c3aab6e8aa713a27586937c1"


def test_gateway_response_vectors_regenerate_byte_identically(tmp_path: Path) -> None:
    committed = FIXTURE.read_bytes()
    assert hashlib.sha256(committed).hexdigest() == EXPECTED_SHA256

    regenerated = tmp_path / "gateway_response_vectors.v0.1.json"
    subprocess.run(
        [sys.executable, str(GENERATOR), "--output", str(regenerated)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert regenerated.read_bytes() == committed


def test_vector_family_covers_neutral_response_classes_without_product_vocabulary() -> None:
    vectors = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(vectors) == {
        "admitted_result",
        "admitted_error",
        "admitted_exception",
        "admitted_timeout",
        "refused",
        "deferred",
        "cancellation",
        "task_submitted",
        "unsupported_lifecycle",
    }

    assert vectors["admitted_result"]["decision"] == {
        "disposition": "admitted",
        "outcome": "result",
    }
    assert vectors["admitted_error"]["decision"]["outcome"] == "error"
    assert vectors["admitted_exception"]["decision"]["outcome"] == "exception"
    assert vectors["admitted_timeout"]["decision"]["outcome"] == "timeout"
    assert vectors["refused"]["decision"] == {
        "disposition": "refused",
        "outcome": None,
    }
    assert vectors["deferred"]["decision"] == {
        "disposition": "deferred",
        "outcome": None,
    }
    assert vectors["cancellation"]["decision"]["outcome"] == "cancellation"
    assert vectors["task_submitted"]["decision"]["outcome"] == "task_submitted"
    assert vectors["unsupported_lifecycle"]["decision"] is None
    assert vectors["unsupported_lifecycle"]["diagnostic_code"] == "unsupported_lifecycle_state"

    serialized = json.dumps(vectors, sort_keys=True).lower()
    for forbidden in (
        "counterplayer",
        "researchtask",
        "researchfinding",
        "researchrun",
        "research_utility",
        "provider.search",
        "provider.open",
    ):
        assert forbidden not in serialized
