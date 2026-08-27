"""Fail-closed verifier for the exact google/sam alpha.7 release used by SAM-LIVE-CHAIN0."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

PINS = {
    "sam_Darwin_arm64.tar.gz": "6c97d964e118bded0d25133e1f8a20d723648ea7415108788ce058006b061a81",
    "bin/sam-control-plane": "b1e8457409012bde0f9f0fde02517d3aff4e48b0a0c02ea129b843f2c509ad49",
    "bin/sam-router": "0299d54df4c69c1189d7f37b19c8a915a6224c7b9fe4767ad96bf28961ccb6ce",
    "bin/sam-node": "4f5775af9fd679a1fc4e9de5f3338c2ddd05c095407223cac8df67bcc006dfd8",
    "bin/mcp-client": "01330bad86b999e371a7abf5ef08ddac2a3d63db00d9216437b8708cf4fa8e23",
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("release_root", type=Path)
    args = ap.parse_args()
    failed = False
    for rel, expected in PINS.items():
        path = args.release_root / rel
        if not path.is_file():
            print(f"MISSING {rel}")
            failed = True
            continue
        actual = digest(path)
        ok = actual == expected
        print(f"{'PASS' if ok else 'FAIL'} {rel} sha256:{actual}")
        failed |= not ok
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
