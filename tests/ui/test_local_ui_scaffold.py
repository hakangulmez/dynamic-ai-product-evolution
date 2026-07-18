from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_research_console_scaffold_exists() -> None:
    assert (REPO_ROOT / "apps/research_console/app.py").is_file()
    assert (REPO_ROOT / "docs/implementation/OBSIDIAN_AND_STREAMLIT_SETUP.md").is_file()
    assert (REPO_ROOT / "RESEARCH_HOME.md").is_file()


def test_console_is_explicitly_read_only_before_harness() -> None:
    app_text = (REPO_ROOT / "apps/research_console/app.py").read_text(encoding="utf-8")
    assert "read-only" in app_text.lower()
    assert "evaluation harness" in app_text.lower()
