from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN_DIRS = [ROOT / "prompts", ROOT / "schemas", ROOT / "src", ROOT / "pipelines"]
FORBIDDEN_PATH_MARKERS = ["thesis_repo", "thesis_clean"]
# Legacy score abbreviations are allowed in policy/handoff docs but not operational artifacts.
FORBIDDEN_OPERATIONAL_TERMS = ["pds_firm_parent_balanced", "stage_combined_v18", "call1_profile_and_coverage"]


def test_no_forbidden_paths_or_operational_markers() -> None:
    hits = []
    for directory in SCAN_DIRS:
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            for marker in FORBIDDEN_PATH_MARKERS + FORBIDDEN_OPERATIONAL_TERMS:
                if marker.lower() in text:
                    hits.append((str(path.relative_to(ROOT)), marker))
    assert not hits, f"Legacy contamination markers found: {hits}"
