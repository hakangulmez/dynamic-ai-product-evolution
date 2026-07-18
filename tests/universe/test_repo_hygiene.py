"""Repository hygiene: UTF-8 integrity and REPO_MANIFEST completeness."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

TEXT_SUFFIXES = {".py", ".md", ".json", ".yaml", ".yml", ".toml", ".txt"}
SCAN_DIRS = ["src", "pipelines", "tests", "docs", "evals", "configs", "prompts", "schemas"]
# Escaped so this scanner file does not trip its own detector: the classic
# UTF-8-read-as-Latin-1 lead bytes and a stray BOM.
MOJIBAKE_MARKERS = (
    "\u00c3",
    "\u00c5\u00b8",
    "\u00e2\u20ac",
    "\u00f0\u0178",
    "\ufeff",
)


def _text_files():
    for directory in SCAN_DIRS:
        for path in (ROOT / directory).rglob("*"):
            if path.is_file() and path.suffix in TEXT_SUFFIXES and "__pycache__" not in path.parts:
                yield path


def test_sources_are_strict_utf8_without_mojibake() -> None:
    problems = []
    for path in _text_files():
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            problems.append((str(path.relative_to(ROOT)), f"not UTF-8: {exc}"))
            continue
        for marker in MOJIBAKE_MARKERS:
            if marker in text:
                problems.append((str(path.relative_to(ROOT)), f"mojibake marker {marker!r}"))
    assert not problems, f"Encoding problems found: {problems}"


def test_repo_manifest_lists_all_source_files() -> None:
    manifest_text = (ROOT / "REPO_MANIFEST.md").read_text(encoding="utf-8")
    manifest_files = re.findall(r"^- `([^`]+)`$", manifest_text, flags=re.MULTILINE)

    duplicates = sorted({f for f in manifest_files if manifest_files.count(f) > 1})
    assert not duplicates, f"Duplicate manifest entries: {duplicates}"

    tracked = set(
        subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    )
    untracked = set(
        subprocess.check_output(
            ["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True
        ).splitlines()
    )
    current = tracked | untracked

    missing = sorted(set(manifest_files) - current)
    extra = sorted(current - set(manifest_files))
    assert not missing, f"Manifest lists files that do not exist: {missing}"
    assert not extra, f"Source files missing from REPO_MANIFEST.md: {extra}"

    forbidden = [f for f in manifest_files if f.startswith((".venv", ".obsidian", "tmp/", "/tmp"))]
    assert not forbidden, f"Manifest lists runtime/ignored paths: {forbidden}"
