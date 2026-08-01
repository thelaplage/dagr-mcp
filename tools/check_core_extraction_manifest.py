#!/usr/bin/env python3
"""Check that neither side of the dagr-mcp-core extraction fork has drifted.

Reads ``packages/dagr-mcp-core/EXTRACTION_MANIFEST.json`` and, for every
extraction entry, recomputes:

* the SHA-256 of the ORIGINAL (legacy) file's git blob at the recorded
  ``fork_commit`` -- this stays fixed forever, since the manifest pins a
  specific commit, not "the current state of main". It exists to prove the
  fork commit itself is unambiguous and the manifest is not lying about what
  was extracted.
* the SHA-256 of the ORIGINAL (legacy) file's CURRENT content at HEAD -- this
  is what actually catches an unnoticed edit to the frozen legacy file: if
  someone edits ``dagr_mcp/srs_receipts.py`` after the fork without updating
  this manifest, this hash changes and the check fails.
* the SHA-256 of the extracted (``dagr_mcp_core``) file's current content --
  catches an unnoticed edit to the extracted baseline the same way.

This is deliberately NOT a check that source bytes equal destination bytes --
see ``documented_deltas`` in the manifest for the (intentional, itemized)
differences. Behavioral parity of emitted receipts is a separate proof (see
``tests/test_core_extraction_byte_parity.py``).

Exits non-zero with a description of every drifted file.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "packages" / "dagr-mcp-core" / "EXTRACTION_MANIFEST.json"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_blob_at_commit(commit: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        capture_output=True,
        check=True,
        cwd=REPO_ROOT,
    ).stdout


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text())
    fork_commit = manifest["fork_commit"]
    failures: list[str] = []

    for entry in manifest["extractions"]:
        source_path = entry["source_path"]
        dest_path = entry["dest_path"]

        # (1) The fork-commit blob must still hash to what the manifest says --
        # otherwise the manifest itself is describing the wrong fork point.
        pinned_blob = _git_blob_at_commit(fork_commit, source_path)
        pinned_hash = _sha256(pinned_blob)
        if pinned_hash != entry["source_sha256"]:
            failures.append(
                f"{source_path}: recorded source_sha256 does not match the "
                f"file's git blob at fork_commit {fork_commit} "
                f"(recorded={entry['source_sha256']}, at_fork_commit={pinned_hash}). "
                "The manifest itself is inconsistent with the fork commit it names."
            )

        # (2) The legacy file's CURRENT content at HEAD must still match the
        # fork-commit blob -- this is the "unnoticed edit to the original"
        # detector. A legitimate, reviewed change to the legacy file requires a
        # deliberate manifest update (bump fork_commit / source_sha256 / add a
        # documented_delta), not a silent drift.
        current_source = (REPO_ROOT / source_path).read_bytes()
        current_source_hash = _sha256(current_source)
        if current_source_hash != entry["source_sha256"]:
            failures.append(
                f"{source_path}: current content does not match the pinned "
                f"fork-commit hash (pinned={entry['source_sha256']}, "
                f"current={current_source_hash}). The frozen legacy file has "
                "changed since the fork -- update EXTRACTION_MANIFEST.json "
                "deliberately (with a documented_deltas entry or a new fork_commit) "
                "if this was intentional."
            )

        # (3) The extracted (dagr_mcp_core) file's current content must match
        # its recorded hash -- the "unnoticed edit to the extracted baseline"
        # detector.
        dest_full = REPO_ROOT / dest_path
        if not dest_full.exists():
            failures.append(f"{dest_path}: file listed in manifest does not exist")
            continue
        current_dest_hash = _sha256(dest_full.read_bytes())
        if current_dest_hash != entry["dest_sha256"]:
            failures.append(
                f"{dest_path}: current content does not match the recorded "
                f"dest_sha256 (recorded={entry['dest_sha256']}, "
                f"current={current_dest_hash}). Update EXTRACTION_MANIFEST.json "
                "deliberately if this edit was intentional."
            )

    if failures:
        print("core extraction manifest check FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(
        f"core extraction manifest OK: {len(manifest['extractions'])} entries "
        f"verified against fork_commit {fork_commit}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
