"""Structural boundaries: no network, no model, no clock, one-way dependency."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from dynamic_ai_products.ingestion import preflight as pf  # noqa: E402
from dynamic_ai_products.ingestion.errors import IngestionError  # noqa: E402
from dynamic_ai_products.provenance import WriteOnceError  # noqa: E402
from ingestion_test_helpers import preflight_kwargs  # noqa: E402

INGESTION_DIR = Path("src/dynamic_ai_products/ingestion")
UNIVERSE_DIR = Path("src/dynamic_ai_products/universe")


def _ingestion_sources() -> list[Path]:
    return sorted(INGESTION_DIR.glob("*.py"))


def _module_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    return names


# --- Dependency direction -----------------------------------------------------


def test_universe_never_imports_ingestion() -> None:
    """Import-level check: prose mentioning ingestion is not a dependency."""
    offenders = []
    for path in sorted(UNIVERSE_DIR.glob("*.py")):
        for name in _module_names(path):
            if "ingestion" in name.split("."):
                offenders.append((path.name, name))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                for alias in node.names:
                    if alias.name == "ingestion":
                        offenders.append((path.name, alias.name))
    assert not offenders, f"universe must not depend on ingestion: {offenders}"


def test_ingestion_package_exists_outside_universe() -> None:
    assert INGESTION_DIR.is_dir()
    assert not (UNIVERSE_DIR / "ingestion.py").exists()


# --- No network ---------------------------------------------------------------


def test_no_network_symbol_anywhere_in_the_package() -> None:
    forbidden_modules = {"httpx", "requests", "urllib", "socket", "http", "ftplib"}
    offenders = []
    for path in _ingestion_sources():
        for name in _module_names(path):
            root = name.split(".")[0]
            if root in forbidden_modules:
                offenders.append((path.name, name))
    assert not offenders, f"ingestion must contain no transport: {offenders}"


def test_no_url_literal_in_the_package() -> None:
    offenders = []
    for path in _ingestion_sources():
        text = path.read_text(encoding="utf-8")
        for marker in ("http://", "https://", "www.", "sec.gov"):
            if marker in text:
                offenders.append((path.name, marker))
    assert not offenders, f"ingestion must carry no URL literal: {offenders}"


# --- No model, no harness -----------------------------------------------------


def test_no_provider_prompt_or_harness_import() -> None:
    forbidden = {"anthropic", "openai", "evaluation", "prompts"}
    offenders = []
    for path in _ingestion_sources():
        for name in _module_names(path):
            if any(part in forbidden for part in name.split(".")):
                offenders.append((path.name, name))
    assert not offenders, f"ingestion must not reach extraction or harness: {offenders}"


def test_no_stage_05_plus_reference() -> None:
    offenders = []
    for path in _ingestion_sources():
        text = path.read_text(encoding="utf-8")
        for marker in ("extract_products", "extract_tasks", "run_evaluation"):
            if marker in text:
                offenders.append((path.name, marker))
    assert not offenders


def test_no_cli_entry_point() -> None:
    for path in _ingestion_sources():
        text = path.read_text(encoding="utf-8")
        assert "__main__" not in text
        assert "typer" not in text


# --- No clock, no VCS ---------------------------------------------------------


def test_no_clock_or_vcs_read() -> None:
    offenders = []
    for path in _ingestion_sources():
        text = path.read_text(encoding="utf-8")
        for marker in (
            "datetime.now",
            "time.time",
            "utcnow",
            "subprocess",
            "rev-parse",
        ):
            if marker in text:
                offenders.append((path.name, marker))
    assert not offenders, f"identity must be injected, not read: {offenders}"


# --- Error boundary -----------------------------------------------------------


def test_write_once_error_never_escapes_the_public_api(tmp_path: Path) -> None:
    kwargs = preflight_kwargs(tmp_path)
    pf.run_ingestion_preflight(**kwargs)
    # A second identical run collides; the failure must be the typed boundary.
    with pytest.raises(IngestionError) as excinfo:
        pf.run_ingestion_preflight(**kwargs)
    assert not isinstance(excinfo.value, WriteOnceError)
    assert excinfo.value.reason_code


def test_stage_artifact_translates_the_neutral_error(tmp_path: Path) -> None:
    from dynamic_ai_products.ingestion.publication import stage_artifact

    staging = tmp_path / "staging"
    staging.mkdir()
    stage_artifact(staging, "a/b.json", b"{}\n")
    with pytest.raises(IngestionError) as excinfo:
        stage_artifact(staging, "a/b.json", b"{}\n")
    assert excinfo.value.reason_code == "destination_exists"
    assert isinstance(excinfo.value.__cause__, WriteOnceError)


# --- Temporal contamination ---------------------------------------------------


def test_eligibility_uses_publication_date_not_retrieval_timestamp(
    tmp_path: Path,
) -> None:
    """retrieval_timestamp is 2026-07-27, seventeen months past the cutoff.

    If it were ever compared against the cutoff the filing would be rejected,
    so a passing run proves publication_date is the temporal input.
    """
    kwargs = preflight_kwargs(tmp_path)
    stamps = [entry["retrieval_timestamp"] for entry in kwargs["receipt"]["retrievals"]]
    assert all(stamp > kwargs["observation_cutoff_date"] for stamp in stamps)

    result = pf.run_ingestion_preflight(**kwargs)
    assert result.verdict == "ready_for_extraction"

    import pyarrow.parquet as pq

    table = pq.read_table(result.run_root / "normalized" / "documents.parquet")
    row = table.to_pylist()[0]
    assert row["temporal_validity"] == "valid"
    assert row["publication_date"] <= kwargs["observation_cutoff_date"]
    assert row["retrieval_timestamp"] > kwargs["observation_cutoff_date"]


def test_adoption_module_never_compares_retrieval_timestamp_to_cutoff() -> None:
    text = (INGESTION_DIR / "adoption.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            rendered = ast.dump(node)
            if "retrieval_timestamp" in rendered and "cutoff" in rendered:
                pytest.fail("retrieval_timestamp must never be a temporal input")


# --- Increment A writes nothing under data/ -----------------------------------


def test_increment_a_creates_no_data_artifact(tmp_path: Path) -> None:
    before = sorted(p.as_posix() for p in Path("data").rglob("*") if p.is_file())
    pf.run_ingestion_preflight(**preflight_kwargs(tmp_path))
    after = sorted(p.as_posix() for p in Path("data").rglob("*") if p.is_file())
    assert before == after, "no run may write under data/ during Increment A"
