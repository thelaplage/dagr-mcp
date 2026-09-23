"""Front-door documentation must describe the implemented repository."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_readme_names_all_implemented_binding_surfaces():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for required in (
        "packages/dagr-mcp-core",
        "packages/dagr-mcp-sdk-v2",
        "mcp==2.0.0",
        "dagr_mcp_service",
        "ARCS Amnesiac",
        "ARCS Verify",
        "Counterpedia",
    ):
        assert required in text
    assert "FastMCP is the one binding" not in text
    assert "multi-binding runtime is architectural / future scope" not in text


def test_historical_gateway_scope_is_labeled_historical():
    text = (ROOT / "docs/GATEWAY_SERVICE_ADAPTER_SCOPE.md").read_text(encoding="utf-8")
    assert "Historical scope record" in text
    assert "PRODUCT_ARCHITECTURE.md" in text


def test_product_architecture_preserves_authority_boundaries():
    text = (ROOT / "docs/PRODUCT_ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "proposal only; never admission" in text
    assert "not the full governed context planner" in text
    assert "does not certify the producer" in text
