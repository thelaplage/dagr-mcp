"""Shared test fixtures.

``dagr_mcp`` carries a permanent import-direction guarantee: its canonical
modules must not pull the producer (``arcs_amnesiac``) or the monolith
(``garp_core`` / ``garp_local`` / sibling repos) into the process. Several guard
tests assert this by scanning global ``sys.modules`` for forbidden roots.

The Amnesiac native tests legitimately exercise the producer and therefore load
``arcs_amnesiac`` while they run. This autouse fixture purges those forbidden
roots from ``sys.modules`` after each test, restoring the clean-process
invariant the guards depend on. It is a no-op for tests that never load a
producer. Purging happens only in teardown, so within a single test every
producer import (test-side and native-side) resolves to one consistent module
instance.
"""

from __future__ import annotations

import sys

import pytest

_PRODUCER_ROOTS = (
    "arcs_amnesiac",
    "garp_core",
    "garp_local",
    "garp_doctrine",
    "arcs_anchor",
    "garp_boundary",
)


@pytest.fixture(autouse=True)
def _purge_producer_modules_after_test():
    yield
    for name in list(sys.modules):
        if name.split(".", 1)[0] in _PRODUCER_ROOTS:
            del sys.modules[name]
