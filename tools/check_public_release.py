#!/usr/bin/env python3
"""Dependency-free public release gate."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Iterator

TEXT_SUFFIXES = {
    ".c", ".cc", ".css", ".go", ".h", ".html", ".java", ".js", ".json",
    ".jsx", ".md", ".mjs", ".py", ".rs", ".sh", ".toml", ".ts", ".tsx",
    ".txt", ".yaml", ".yml",
}
MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdx"}
RECEIPT_DIR_NAMES = {"fixtures", "vectors", "packs"}
RAW_CONTENT_KEYS = {
    "prompt_text", "transcript", "raw_payload", "tool_arguments", "arguments",
    "result_body", "headers",
}
PRIVATE_PATH_MARKERS = (
    "/" + "Users" + "/",
    "/" + "home" + "/",
    "/" + "private" + "/" + "var",
    "C:" + "\\" + "\\",
    "~" + "/" + "garp-",
    "~" + "/" + "arcs-anchor",
)
INTERNAL_REVIEWER = "Stein" + "er"
PRIVATE_IMPORT_ROOTS = ("garp" + "_sdk", "garp" + "_core", "garp" + "_local")
WITHDRAWN_LANGUAGE = (
    "none is externally verifiable",
    "the record-governance layer is empty",
    "empty layer",
    "has no peer",
    "payload" + "-free",
    "tool" + "_executed",
    "any byte change",
    "bytes on the wire",
)
DATestamp_RE = re.compile(r"_[A-Z]{3}[0-9]{2}(?:\.[^.]+)?$")
IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_\.]*)", re.MULTILINE)


@dataclass(frozen=True)
class Finding:
    rule_id: str
    path: str
    message: str


def _git_files(root: Path) -> list[Path] | None:
    if not (root / ".git").exists():
        return None
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return [root / item.decode("utf-8", "surrogateescape") for item in proc.stdout.split(b"\0") if item]


def tracked_files(root: Path) -> list[Path]:
    git_files = _git_files(root)
    if git_files is not None:
        return [path for path in git_files if path.is_file()]
    return [
        path for path in root.rglob("*")
        if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts
    ]


def relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def is_internal_doc(rel: str) -> bool:
    return rel == "docs/internal" or rel.startswith("docs/internal/")


def read_text(path: Path) -> str | None:
    if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"README", "LICENSE", "SECURITY"}:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def iter_json_keys(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from iter_json_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_json_keys(item)


def is_receipt_fixture(rel: str) -> bool:
    path = Path(rel)
    return path.suffix.lower() == ".json" and any(part in RECEIPT_DIR_NAMES for part in path.parts)


def load_brand_denylist(script_dir: Path) -> list[str]:
    path = script_dir / "brand_denylist.txt"
    if not path.exists():
        return []
    values: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        value = raw.strip()
        if value and not value.startswith("#"):
            values.append(value)
    return values


def check(root: Path, *, script_dir: Path | None = None) -> list[Finding]:
    findings: list[Finding] = []
    files = tracked_files(root)
    text_by_rel: dict[str, str] = {}
    for path in files:
        rel = relative(root, path)
        text = read_text(path)
        if text is not None:
            text_by_rel[rel] = text

        name = path.name
        if not is_internal_doc(rel) and (name.startswith("IN___") or name.startswith("ARCS_-_IN___")):
            findings.append(Finding("PR001", rel, "internal-prefixed filename outside docs/internal"))
        if not is_internal_doc(rel) and DATestamp_RE.search(name):
            findings.append(Finding("PR002", rel, "internal datestamp filename outside docs/internal"))

    for rel, text in text_by_rel.items():
        for marker in PRIVATE_PATH_MARKERS:
            if marker in text:
                findings.append(Finding("PR003", rel, f"absolute or private path marker found: {marker}"))
        if INTERNAL_REVIEWER in text:
            findings.append(Finding("PR004", rel, "internal reviewer reference found"))

    if not (root / "LICENSE").is_file():
        findings.append(Finding("PR005", "LICENSE", "missing root LICENSE"))
    if not (root / "SECURITY.md").is_file():
        findings.append(Finding("PR006", "SECURITY.md", "missing root SECURITY.md"))

    readme_path = next((root / name for name in ("README.md", "README.rst", "README") if (root / name).is_file()), None)
    readme_text = read_text(readme_path) if readme_path else None
    if not readme_text or not (
        "<!-- layer-map -->" in readme_text
        or "Standard (ARCS)" in readme_text
        or "Receipt protocol and profiles" in readme_text
    ):
        findings.append(Finding("PR007", readme_path.name if readme_path else "README.md", "README missing layer-map marker or six-role surface map"))
    if readme_text and "DAGR" in readme_text and "MCP" in readme_text and "first supported binding" not in readme_text:
        findings.append(Finding("PR008", readme_path.name if readme_path else "README.md", "README lacks required first-binding language"))

    for rel, text in text_by_rel.items():
        if is_receipt_fixture(rel):
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            keys = set(iter_json_keys(payload))
            for key in sorted(keys.intersection(RAW_CONTENT_KEYS)):
                findings.append(Finding("PR009", rel, f"receipt fixture carries forbidden raw-content key: {key}"))
            if isinstance(payload, dict) and {"receipt_type", "boundary_type", "extensions"}.issubset(payload) and "receipt_version" not in payload:
                findings.append(Finding("PR009", rel, "SRS receipt candidate lacks receipt_version"))

        if Path(rel).suffix.lower() == ".py":
            for match in IMPORT_RE.finditer(text):
                root_name = match.group(1).split(".", 1)[0]
                if root_name in PRIVATE_IMPORT_ROOTS:
                    findings.append(Finding("PR010", rel, f"private import root found: {root_name}"))

        if Path(rel).suffix.lower() in MARKDOWN_SUFFIXES:
            lower = text.lower()
            for phrase in WITHDRAWN_LANGUAGE:
                if phrase.lower() in lower:
                    findings.append(Finding("PR011", rel, f"withdrawn language found: {phrase}"))

    denylist = load_brand_denylist(script_dir or Path(__file__).resolve().parent)
    naming_path = "docs/NAMING.md"
    for brand in denylist:
        for rel, text in text_by_rel.items():
            if rel in {naming_path, "brand_denylist.txt"}:
                continue
            if brand.lower() in text.lower():
                findings.append(Finding("PR012", rel, f"candidate brand outside {naming_path}: {brand}"))

    return sorted(findings, key=lambda item: (item.rule_id, item.path, item.message))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("repo_root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    root = args.repo_root.expanduser().resolve()
    if not root.is_dir():
        print(f"usage error: repository root is not a directory: {root}", file=sys.stderr)
        return 2
    findings = check(root)
    if args.as_json:
        print(json.dumps({"repo_root": str(root), "finding_count": len(findings), "findings": [asdict(item) for item in findings]}, indent=2, sort_keys=True))
    else:
        for item in findings:
            print(f"{item.rule_id} {item.path}: {item.message}")
        print(f"{'PASS' if not findings else 'FAIL'}: {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
