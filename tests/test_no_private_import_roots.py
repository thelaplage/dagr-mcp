from pathlib import Path


def test_no_private_import_roots():
    package = Path(__file__).resolve().parents[1] / "dagr_mcp"
    forbidden = ("garp" + "_sdk", "garp" + "_core", "garp" + "_local")
    for path in package.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for root in forbidden:
            assert f"from {root}" not in text
            assert f"import {root}" not in text
