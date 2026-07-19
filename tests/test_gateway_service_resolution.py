"""Sprint A7 — binding-selector types and lookup (dagr_mcp_service.resolution).

Covers the data shapes §13 calls for, the fail-closed *representability*
§5.2 requires, and ``select_binding``'s narrow, pure, transport-free lookup
from an operator-configured selector key to a registered binding identity
(§5.2, A7 acceptance criteria in scope §15).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from dagr_mcp_service.resolution import (
    FASTMCP_BINDING_VERSION,
    SDK_BINDING_VERSION,
    SUPPORTED_BINDING_VERSIONS,
    BindingHandle,
    BindingResolutionRefused,
    BindingSelectorKey,
    select_binding,
)

ROOT = Path(__file__).resolve().parents[1]


def test_binding_selector_key_holds_an_opaque_string() -> None:
    key = BindingSelectorKey(key="primary")
    assert key.key == "primary"


def test_binding_selector_key_rejects_empty_string() -> None:
    with pytest.raises(ValueError):
        BindingSelectorKey(key="")


def test_binding_handle_accepts_both_registered_binding_versions() -> None:
    for version in SUPPORTED_BINDING_VERSIONS:
        handle = BindingHandle(binding_version=version)
        assert handle.binding_version == version


def test_binding_handle_rejects_unregistered_binding_version() -> None:
    # An unknown selector key resolving to an arbitrary string must not be
    # representable as a BindingHandle at all (§5.2's "no default binding is
    # chosen" posture starts here, at the type level).
    with pytest.raises(ValueError):
        BindingHandle(binding_version="made-up-binding.v9")


def test_binding_handle_rejects_direct_harness_binding_version() -> None:
    # direct-harness.v0.1 is registered on the shared receipt emitter
    # (dagr_mcp.srs_receipts.ALL_REGISTERED_BINDING_VERSIONS) but is not a
    # Gateway-selectable binding (§5 names exactly two). Proves resolution.py
    # did not just reuse the emitter's full registered set.
    with pytest.raises(ValueError):
        BindingHandle(binding_version="direct-harness.v0.1")


def test_supported_binding_versions_is_exactly_the_two_named_in_scope() -> None:
    assert SUPPORTED_BINDING_VERSIONS == {
        "fastmcp.middleware.v0.1",
        "official-mcp-sdk.python.v0.1",
    }


def test_sdk_binding_version_matches_the_live_sdk_binding_package() -> None:
    import dagr_mcp_sdk_binding

    assert SDK_BINDING_VERSION == dagr_mcp_sdk_binding.BINDING_VERSION


def test_fastmcp_binding_version_literal_matches_the_live_fastmcp_binding() -> None:
    # dagr_mcp_service.resolution cannot import dagr_mcp.fastmcp_binding
    # itself (it imports fastmcp at module scope); this process is allowed
    # to, so it grounds the reproduced literal against the real binding here.
    import dagr_mcp.fastmcp_binding as fastmcp_binding

    assert FASTMCP_BINDING_VERSION == fastmcp_binding.BINDING_VERSION


def test_select_binding_resolves_a_known_selector_key() -> None:
    registry = {"primary": SDK_BINDING_VERSION}
    result = select_binding(registry, BindingSelectorKey(key="primary"))
    assert result == BindingHandle(binding_version=SDK_BINDING_VERSION)


def test_select_binding_resolves_both_registered_binding_identities() -> None:
    registry = {"fast": FASTMCP_BINDING_VERSION, "sdk": SDK_BINDING_VERSION}
    fast = select_binding(registry, BindingSelectorKey(key="fast"))
    sdk = select_binding(registry, BindingSelectorKey(key="sdk"))
    assert fast == BindingHandle(binding_version=FASTMCP_BINDING_VERSION)
    assert sdk == BindingHandle(binding_version=SDK_BINDING_VERSION)


def test_select_binding_fails_closed_on_unknown_selector_key() -> None:
    registry = {"primary": SDK_BINDING_VERSION}
    result = select_binding(registry, BindingSelectorKey(key="nonexistent"))
    assert result == BindingResolutionRefused(
        selector_key="nonexistent", reason="unknown_binding"
    )


def test_select_binding_fails_closed_when_registry_value_is_not_a_supported_binding() -> None:
    # A misconfigured registry entry (e.g. an operator typo, or a
    # direct-harness identity — §5 names exactly two Gateway-selectable
    # bindings) must refuse, never substitute a supported binding instead.
    registry = {"primary": "direct-harness.v0.1"}
    result = select_binding(registry, BindingSelectorKey(key="primary"))
    assert result == BindingResolutionRefused(
        selector_key="primary", reason="unknown_binding"
    )


def test_select_binding_fails_closed_on_unavailable_binding() -> None:
    registry = {"sdk": SDK_BINDING_VERSION}
    result = select_binding(
        registry,
        BindingSelectorKey(key="sdk"),
        is_binding_available=lambda _binding_version: False,
    )
    assert result == BindingResolutionRefused(
        selector_key="sdk", reason="binding_unavailable"
    )


def test_select_binding_never_silently_substitutes_another_binding() -> None:
    # Every non-success path is a refusal naming the reason (§5.2's "the
    # service never silently substitutes the other binding"); there is no
    # third outcome that returns a different BindingHandle than requested.
    registry = {"sdk": SDK_BINDING_VERSION}
    result = select_binding(
        registry,
        BindingSelectorKey(key="sdk"),
        is_binding_available=lambda _binding_version: False,
    )
    assert not isinstance(result, BindingHandle)
    assert isinstance(result, BindingResolutionRefused)


def test_select_binding_rejects_non_mapping_registry() -> None:
    with pytest.raises(TypeError):
        select_binding(["not", "a", "mapping"], BindingSelectorKey(key="primary"))  # type: ignore[arg-type]


def test_select_binding_rejects_non_selector_key_argument() -> None:
    with pytest.raises(TypeError):
        select_binding({"primary": SDK_BINDING_VERSION}, "primary")  # type: ignore[arg-type]


def test_select_binding_imports_no_binding_module() -> None:
    # select_binding must resolve without importing dagr_mcp.fastmcp_binding
    # or dagr_mcp_sdk_binding.adapter/mask/server — only the package-root
    # metadata this module already imports. Proven in a fresh subprocess so
    # no earlier test's imports mask a violation.
    script = (
        "import sys\n"
        "from dagr_mcp_service.resolution import (\n"
        "    SDK_BINDING_VERSION, BindingSelectorKey, select_binding,\n"
        ")\n"
        "registry = {'sdk': SDK_BINDING_VERSION}\n"
        "select_binding(registry, BindingSelectorKey(key='sdk'))\n"
        "assert 'dagr_mcp.fastmcp_binding' not in sys.modules\n"
        "assert 'dagr_mcp_sdk_binding.adapter' not in sys.modules\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_fresh_import_of_resolution_does_not_pull_in_mcp_or_fastmcp() -> None:
    script = (
        "import sys\n"
        "assert 'mcp' not in sys.modules and 'fastmcp' not in sys.modules\n"
        "from dagr_mcp_service import resolution\n"
        "roots = {m.split('.', 1)[0] for m in sys.modules}\n"
        "assert 'mcp' not in roots, roots\n"
        "assert 'fastmcp' not in roots, roots\n"
        "assert resolution.SDK_BINDING_VERSION == 'official-mcp-sdk.python.v0.1'\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
