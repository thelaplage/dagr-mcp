"""Sprint A2 hardening — the neutral package's lazy ``binding_mask`` export.

The package root declares ``__all__ == ["contract", "binding_mask"]`` but does
**not** import ``binding_mask`` eagerly: that submodule pulls the FastMCP binding
(``dagr_mcp`` / ``fastmcp``) into memory, and the neutral package must be
importable without the binding present.

The in-process public-surface tests can *falsely pass* here: this test process
(and the sibling hardening module) imports ``binding_mask`` at module import
time, which binds ``dagr_mcp_lifecycle.binding_mask`` as a package attribute. A
declared public name that is only reachable *because of an earlier import* is a
false clean — a genuinely fresh::

    import dagr_mcp_lifecycle
    dagr_mcp_lifecycle.binding_mask

must resolve the declared name on its own, via the package's PEP 562
``__getattr__`` lazy loader, without the root having eagerly imported the
binding.

Every proof here therefore runs in a **fresh subprocess interpreter** that
begins with a clean ``sys.modules`` — the only place import direction and lazy
binding can be observed truthfully, because the pytest process has already
imported the binding. Nothing here emits into production paths, moves binding
code, changes goldens, or introduces a second binding.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "tests/golden/neutral_lifecycle/public_api_surface.json"


def _committed_snapshot() -> dict[str, Any]:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def _run(script: str) -> subprocess.CompletedProcess[str]:
    """Run *script* in a fresh interpreter with a clean ``sys.modules``.

    A subprocess is required: this pytest process has already imported
    ``dagr_mcp`` / ``fastmcp`` / ``dagr_mcp_lifecycle.binding_mask``, so neither
    import direction nor the lazy-binding-from-cold-start can be observed in it.
    """

    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _ok(proc: subprocess.CompletedProcess[str]) -> None:
    assert proc.returncode == 0, proc.stdout + proc.stderr


# A cold-start preamble asserting the binding is genuinely absent before any
# explicit ``binding_mask`` access. Reused by several probes.
_COLD_START = (
    "import sys\n"
    "assert 'dagr_mcp_lifecycle' not in sys.modules\n"
    "assert 'dagr_mcp' not in sys.modules\n"
    "assert 'fastmcp' not in sys.modules\n"
    "import dagr_mcp_lifecycle as pkg\n"
)


# --------------------------------------------------------------------------- #
# Root import exposes ``contract`` and stays binding-free                      #
# --------------------------------------------------------------------------- #


def test_fresh_root_import_exposes_contract_without_the_binding():
    script = _COLD_START + (
        # contract is eagerly bound and usable...
        "assert pkg.contract.CONTRACT_ID == 'dagr.mcp.lifecycle_contract'\n"
        "assert 'dagr_mcp_lifecycle.contract' in sys.modules\n"
        # ...while the binding stays entirely out of the process.
        "roots = {k.split('.', 1)[0] for k in sys.modules}\n"
        "assert 'dagr_mcp' not in roots, 'root import must not load dagr_mcp'\n"
        "assert 'fastmcp' not in roots, 'root import must not load fastmcp'\n"
        # binding_mask is declared but NOT yet imported by the mere root import.
        "assert 'dagr_mcp_lifecycle.binding_mask' not in sys.modules\n"
        "assert 'binding_mask' not in vars(pkg)\n"
        # It is nonetheless discoverable on the declared surface.
        "assert pkg.__all__ == ['contract', 'binding_mask']\n"
        "assert 'binding_mask' in dir(pkg)\n"
    )
    _ok(_run(script))


# --------------------------------------------------------------------------- #
# First explicit access lazily loads and caches the real submodule            #
# --------------------------------------------------------------------------- #


def test_fresh_attribute_access_lazily_loads_the_real_submodule():
    script = _COLD_START + (
        # Accessing the attribute triggers PEP 562 __getattr__, which imports
        # the real submodule and pulls the binding in only now.
        "bm = pkg.binding_mask\n"
        "import types\n"
        "assert isinstance(bm, types.ModuleType)\n"
        "assert bm is sys.modules['dagr_mcp_lifecycle.binding_mask']\n"
        "assert bm.__name__ == 'dagr_mcp_lifecycle.binding_mask'\n"
        # It is the real mask, not a stub.
        "assert bm.MASK_ID == 'dagr.mcp.lifecycle_binding_mask'\n"
        "assert bm.MASK_VERSION == 'v0.1'\n"
        # Loading it is what pulled the binding into memory (positive control).
        "roots = {k.split('.', 1)[0] for k in sys.modules}\n"
        "assert 'dagr_mcp' in roots, 'accessing binding_mask must load dagr_mcp'\n"
    )
    _ok(_run(script))


def test_fresh_attribute_access_caches_the_submodule_on_the_package():
    script = _COLD_START + (
        "assert 'binding_mask' not in vars(pkg)\n"
        "first = pkg.binding_mask\n"
        # After first access the submodule is cached in the package __dict__, so
        # later lookups resolve directly and never re-enter __getattr__.
        "assert 'binding_mask' in vars(pkg)\n"
        "assert vars(pkg)['binding_mask'] is first\n"
        "second = pkg.binding_mask\n"
        "assert first is second\n"
        "assert first is sys.modules['dagr_mcp_lifecycle.binding_mask']\n"
    )
    _ok(_run(script))


# --------------------------------------------------------------------------- #
# Direct submodule import forms resolve the declared name                      #
# --------------------------------------------------------------------------- #


def test_fresh_from_import_binding_mask_works():
    script = (
        "import sys\n"
        "assert 'dagr_mcp' not in sys.modules and 'fastmcp' not in sys.modules\n"
        "from dagr_mcp_lifecycle import binding_mask\n"
        "import types\n"
        "assert isinstance(binding_mask, types.ModuleType)\n"
        "assert binding_mask.MASK_ID == 'dagr.mcp.lifecycle_binding_mask'\n"
        "assert binding_mask is sys.modules['dagr_mcp_lifecycle.binding_mask']\n"
        # And it is bound on the package, same object.
        "import dagr_mcp_lifecycle as pkg\n"
        "assert pkg.binding_mask is binding_mask\n"
    )
    _ok(_run(script))


def test_fresh_star_import_resolves_every_all_name():
    script = (
        "import types\n"
        "ns = {}\n"
        "exec('from dagr_mcp_lifecycle import *', ns)\n"
        "import dagr_mcp_lifecycle as pkg\n"
        # Every declared public name resolves, and each is a real submodule.
        "for name in pkg.__all__:\n"
        "    assert name in ns, name\n"
        "    assert isinstance(ns[name], types.ModuleType), name\n"
        "assert ns['contract'].CONTRACT_ID == 'dagr.mcp.lifecycle_contract'\n"
        "assert ns['binding_mask'].MASK_ID == 'dagr.mcp.lifecycle_binding_mask'\n"
    )
    _ok(_run(script))


# --------------------------------------------------------------------------- #
# Unknown attributes fail normally                                            #
# --------------------------------------------------------------------------- #


def test_fresh_unknown_attribute_raises_attribute_error():
    script = _COLD_START + (
        "import types\n"
        # A name that is neither a real global nor a declared lazy submodule.
        "for bad in ('does_not_exist', 'dagr_mcp', 'fastmcp', 'binding_masks'):\n"
        "    try:\n"
        "        getattr(pkg, bad)\n"
        "    except AttributeError:\n"
        "        pass\n"
        "    else:\n"
        "        raise SystemExit('expected AttributeError for ' + bad)\n"
        # The failed lookups did not drag the binding in.
        "roots = {k.split('.', 1)[0] for k in sys.modules}\n"
        "assert 'dagr_mcp' not in roots and 'fastmcp' not in roots\n"
    )
    _ok(_run(script))


# --------------------------------------------------------------------------- #
# The committed public-surface snapshot generated from a cold process          #
# --------------------------------------------------------------------------- #


def test_committed_public_surface_snapshot_generated_from_cold_process():
    # Regenerate the public-surface snapshot in a fresh interpreter that has NOT
    # imported binding_mask beforehand, then compare it to the committed golden.
    # This proves the snapshot holds without relying on an earlier import binding
    # the attribute — the exact false-clean the in-process test cannot rule out.
    script = (
        "import sys, json, pkgutil, importlib\n"
        "assert 'dagr_mcp' not in sys.modules and 'fastmcp' not in sys.modules\n"
        "import dagr_mcp_lifecycle as pkg\n"
        "assert 'dagr_mcp_lifecycle.binding_mask' not in sys.modules\n"
        "names = ['dagr_mcp_lifecycle']\n"
        "for mi in pkgutil.walk_packages(pkg.__path__, prefix='dagr_mcp_lifecycle.'):\n"
        "    names.append(mi.name)\n"
        "modules = {}\n"
        "for name in sorted(names):\n"
        "    mod = importlib.import_module(name)\n"
        "    all_ = getattr(mod, '__all__', None)\n"
        "    modules[name] = sorted(all_) if all_ is not None else None\n"
        "surface = {\n"
        "    'modules': modules,\n"
        "    'package_public_names': sorted(pkg.__all__),\n"
        "}\n"
        "sys.stdout.write('SURFACE=' + json.dumps(surface))\n"
    )
    proc = _run(script)
    _ok(proc)

    marker = "SURFACE="
    assert marker in proc.stdout, proc.stdout + proc.stderr
    generated = json.loads(proc.stdout.split(marker, 1)[1])
    assert generated == _committed_snapshot()

    # The declared root surface names exactly the two submodules, and the
    # regenerated snapshot names binding_mask as a declared-but-lazy submodule.
    assert generated["package_public_names"] == ["binding_mask", "contract"]
    assert "dagr_mcp_lifecycle.binding_mask" in generated["modules"]
