"""FRAME builder tests: fixture-only EDGAR full-index parsing.

Governed by SPEC-001 Stage A and docs/THESIS_EXECUTION_PLAN.md W1. Everything
here runs over the synthetic fixture bundle in
``evals/fixtures/edgar_full_index``; no network, no model calls (W0 gate).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.universe.frame import (
    AMENDMENT_CANDIDATE_RULE,
    FrameInputError,
    FrameParameters,
    parse_master_index,
    run_frame_builder,
)
from dynamic_ai_products.universe.io_utils import read_json, read_jsonl, sha256_file
from dynamic_ai_products.universe.models import HistoricalAnnualFiler

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "evals" / "fixtures" / "edgar_full_index"
PROJECT_CONFIG = ROOT / "configs" / "project.yaml"
FRAME_SCHEMA_PATH = ROOT / "schemas" / "filer_frame_manifest.schema.json"
FRAME_MODULE_PATH = ROOT / "src" / "dynamic_ai_products" / "universe" / "frame.py"
CLI = ROOT / "pipelines" / "00_build_company_universe.py"
EXPECTED = read_json(FIXTURE_DIR / "expected_frame.json")

WINDOW_START = date.fromisoformat("2022-08-01")
WINDOW_END = date.fromisoformat("2023-02-28")

VALID_HEADER = "CIK|Company Name|Form Type|Date Filed|Filename"
VALID_SEPARATOR = "-" * 80
VALID_ROW = (
    "2000001|SYNTHETIC LEDGERWORKS INC|10-K|2022-09-15|"
    "edgar/data/2000001/0002000001-22-000010.txt"
)


def _run(output_dir: Path, run_id: str):
    return run_frame_builder(
        repo_root=ROOT,
        project_config_path=PROJECT_CONFIG,
        index_dir=FIXTURE_DIR,
        output_dir=output_dir,
        run_id=run_id,
        filing_window_start=WINDOW_START,
        filing_window_end=WINDOW_END,
    )


@pytest.fixture(scope="module")
def frame_run(tmp_path_factory: pytest.TempPathFactory):
    return _run(tmp_path_factory.mktemp("frame-run"), "pytest-frame")


# --- master.idx structural format --------------------------------------------


def test_missing_table_header_is_a_structural_error() -> None:
    text = "Some preamble\n\nCIK|Name|Form|Date|File\n" + VALID_SEPARATOR + "\n"
    with pytest.raises(FrameInputError):
        parse_master_index(text, source_name="broken.idx")


def test_missing_separator_is_a_structural_error() -> None:
    text = f"Preamble\n\n{VALID_HEADER}\n{VALID_ROW}\n"
    with pytest.raises(FrameInputError):
        parse_master_index(text, source_name="broken.idx")


def test_variable_preamble_text_is_permitted() -> None:
    for preamble in (
        "Description: variant one\n\n",
        "Description:  x\nLast Data Received: y\nComments: z\n\n\n",
        "",
    ):
        text = f"{preamble}{VALID_HEADER}\n{VALID_SEPARATOR}\n{VALID_ROW}\n"
        parsed = parse_master_index(text, source_name="variant.idx")
        assert len(parsed.rows) == 1 and not parsed.parse_failures


def test_fixture_files_all_parse_with_distinct_preambles(frame_run) -> None:
    assert frame_run.counts["index_files"] == 3
    assert frame_run.counts["parsed_rows"] == EXPECTED["counts"]["parsed_rows"]


# --- parameters ---------------------------------------------------------------


def test_inverted_filing_window_is_rejected() -> None:
    with pytest.raises(FrameInputError):
        FrameParameters(
            filing_window_start=WINDOW_END,
            filing_window_end=WINDOW_START,
            domestic_forms=("10-K",),
            extension_forms=(),
        )


def test_overlapping_form_scopes_are_rejected() -> None:
    with pytest.raises(FrameInputError):
        FrameParameters(
            filing_window_start=WINDOW_START,
            filing_window_end=WINDOW_END,
            domestic_forms=("10-K",),
            extension_forms=("10-K", "20-F"),
        )


# --- gold comparison ----------------------------------------------------------


def test_counts_match_gold(frame_run) -> None:
    assert frame_run.counts == EXPECTED["counts"]
    assert frame_run.out_of_scope_form_counts == EXPECTED["out_of_scope_form_counts"]
    assert all(frame_run.reconciliation.values())


def test_partitions_match_gold(frame_run) -> None:
    domestic = read_jsonl(frame_run.run_dir / "historical_annual_filers.jsonl")
    fpi = read_jsonl(frame_run.run_dir / "fpi_extension_filers.jsonl")
    assert [
        [r["cik"], r["accession_number"]] for r in domestic
    ] == EXPECTED["domestic_filer_accessions"]
    assert [r["accession_number"] for r in fpi] == EXPECTED["fpi_extension_accessions"]


# --- filer-accession (CIK, accession) grain and record shape ------------------


def test_filing_history_is_preserved_per_filer_accession(frame_run) -> None:
    domestic = read_jsonl(frame_run.run_dir / "historical_annual_filers.jsonl")
    ledgerworks = [r for r in domestic if r["cik"] == "0002000001"]
    assert len(ledgerworks) == 2  # two annual filings, no CIK/firm-year collapse
    assert {r["accession_number"] for r in ledgerworks} == {
        "0002000001-22-000010",
        "0002000001-23-000002",
    }


def test_records_validate_as_historical_annual_filer(frame_run) -> None:
    for artefact in ("historical_annual_filers.jsonl", "fpi_extension_filers.jsonl"):
        for payload in read_jsonl(frame_run.run_dir / artefact):
            record = HistoricalAnnualFiler.model_validate(payload)
            assert record.baseline_status == "unknown"  # baseline cutoff is W0-owned


def test_accession_derived_from_filename_with_raw_provenance(frame_run) -> None:
    domestic = read_jsonl(frame_run.run_dir / "historical_annual_filers.jsonl")
    for record in domestic:
        raw = next(
            s for s in record["source_ids"] if s.startswith("sec_filename:")
        ).removeprefix("sec_filename:")
        stem = raw.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        assert record["accession_number"] == stem
        assert any(
            s.startswith("edgar_full_index:") for s in record["source_ids"]
        )


# --- amendments ---------------------------------------------------------------


def test_amendments_create_no_annual_observation(frame_run) -> None:
    annual_accessions = {
        r["accession_number"]
        for artefact in ("historical_annual_filers.jsonl", "fpi_extension_filers.jsonl")
        for r in read_jsonl(frame_run.run_dir / artefact)
    }
    links = read_jsonl(frame_run.run_dir / "amendment_links.jsonl")
    assert len(links) == 3
    assert not {l["amendment_accession"] for l in links} & annual_accessions


def test_amendment_originals_are_deterministic_candidates_not_proven(frame_run) -> None:
    links = read_jsonl(frame_run.run_dir / "amendment_links.jsonl")
    key_fields = [
        {
            "amendment_accession": l["amendment_accession"],
            "partition": l["partition"],
            "candidate_status": l["candidate_status"],
            "candidate_original_accession": l["candidate_original_accession"],
        }
        for l in links
    ]
    assert key_fields == EXPECTED["amendment_links"]
    for link in links:
        assert link["candidate_rule"] == AMENDMENT_CANDIDATE_RULE
    # The 2022-11-20 amendment must pick the 2022-09-15 filing, not the later
    # 2023 annual filing by the same CIK: latest *preceding* filing only.
    matched = next(
        l for l in links if l["amendment_accession"] == "0002000001-22-000015"
    )
    assert matched["candidate_original_accession"] == "0002000001-22-000010"
    unmatched = next(l for l in links if l["candidate_status"] == "unmatched")
    assert unmatched["candidate_original_accession"] is None


# --- exhaustive, mutually exclusive accounting -------------------------------


def test_reconciliation_identities_are_exhaustive(frame_run) -> None:
    counts = frame_run.counts
    assert counts["data_lines"] == counts["parsed_rows"] + counts["parse_failures"]
    assert counts["parsed_rows"] == (
        counts["admitted_rows"]
        + counts["duplicate_rows"]
        + counts["integrity_failure_rows"]
    )
    assert counts["admitted_rows"] == (
        counts["domestic_annual_records"]
        + counts["fpi_extension_records"]
        + counts["amendment_links"]
        + counts["out_of_scope_form_rows"]
        + counts["out_of_window_rows"]
    )


def test_conflicting_same_filer_accession_rows_are_integrity_failures(
    frame_run,
) -> None:
    failures = read_jsonl(frame_run.run_dir / "frame_integrity_failures.jsonl")
    assert [
        [f["cik"], f["accession_number"]] for f in failures
    ] == EXPECTED["integrity_failure_filer_accessions"]
    conflict = failures[0]
    assert conflict["reason_code"] == "conflicting_same_filer_accession_rows"
    assert len(conflict["rows"]) == 2
    # Neither conflicting row enters any frame partition; only this
    # filer-accession group is excluded.
    for artefact in ("historical_annual_filers.jsonl", "fpi_extension_filers.jsonl"):
        for record in read_jsonl(frame_run.run_dir / artefact):
            assert (record["cik"], record["accession_number"]) != (
                conflict["cik"],
                conflict["accession_number"],
            )


def test_combined_multi_filer_annual_filing_yields_one_record_per_filer(
    frame_run,
) -> None:
    # ADR-080: one accession under several filer CIKs is a legitimate
    # combined submission — one domestic record per filer, never an
    # integrity failure, and no filer's annual record is silently excluded.
    expected = EXPECTED["combined_filing"]
    domestic = read_jsonl(frame_run.run_dir / "historical_annual_filers.jsonl")
    combined = [
        r for r in domestic if r["accession_number"] == expected["accession"]
    ]
    assert sorted(r["cik"] for r in combined) == expected["filer_ciks"]
    failures = read_jsonl(frame_run.run_dir / "frame_integrity_failures.jsonl")
    assert all(
        f["accession_number"] != expected["accession"] for f in failures
    )
    duplicates = read_jsonl(frame_run.run_dir / "frame_duplicates.jsonl")
    assert all(
        d["accession_number"] != expected["accession"] for d in duplicates
    )


def test_identical_duplicate_row_is_recorded_against_first_occurrence(frame_run) -> None:
    duplicates = read_jsonl(frame_run.run_dir / "frame_duplicates.jsonl")
    assert [d["accession_number"] for d in duplicates] == EXPECTED[
        "duplicate_accessions"
    ]
    assert duplicates[0]["first_source_index_file"] == "master-2022-QTR3.idx"
    assert duplicates[0]["source_index_file"] == "master-2022-QTR4.idx"


def test_parse_failures_are_explicit_with_raw_lines(frame_run) -> None:
    failures = read_jsonl(frame_run.run_dir / "frame_parse_failures.jsonl")
    assert sorted(f["reason_code"] for f in failures) == EXPECTED[
        "parse_failure_reasons"
    ]
    for failure in failures:
        assert failure["raw_line"].strip()
        assert failure["source_index_file"] and failure["source_line"] > 0


def test_out_of_window_rows_are_counted_on_both_sides(frame_run) -> None:
    assert frame_run.counts["out_of_window_rows"] == 2  # 2022-07-15 and 2023-03-10


# --- manifest, determinism, immutability -------------------------------------


def test_manifest_is_schema_valid_with_source_hashes(frame_run) -> None:
    manifest = read_json(frame_run.manifest_path)
    Draft202012Validator(read_json(FRAME_SCHEMA_PATH)).validate(manifest)
    assert manifest["filing_window_start"] == "2022-08-01"
    assert manifest["filing_window_end"] == "2023-02-28"
    assert manifest["domestic_forms"] == ["10-K", "10-KT"]
    assert manifest["extension_forms"] == ["20-F", "40-F"]
    for entry in manifest["index_files"]:
        assert entry["sha256"] == sha256_file(FIXTURE_DIR / entry["filename"])
    for filename, digest in manifest["output_hashes"].items():
        assert sha256_file(frame_run.run_dir / filename) == digest


def test_two_runs_produce_byte_identical_artefacts(frame_run, tmp_path: Path) -> None:
    second = _run(tmp_path, "pytest-frame-repeat")
    for artefact in (
        "historical_annual_filers.jsonl",
        "fpi_extension_filers.jsonl",
        "amendment_links.jsonl",
        "frame_parse_failures.jsonl",
        "frame_duplicates.jsonl",
        "frame_integrity_failures.jsonl",
    ):
        assert (second.run_dir / artefact).read_bytes() == (
            frame_run.run_dir / artefact
        ).read_bytes(), artefact
    assert second.counts == frame_run.counts


def test_run_directory_is_never_reused(frame_run) -> None:
    with pytest.raises(FileExistsError):
        _run(frame_run.run_dir.parent, frame_run.run_id)


def test_unlisted_index_file_is_refused(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    shutil.copytree(FIXTURE_DIR, bundle)
    (bundle / "master-stray.idx").write_text(
        f"{VALID_HEADER}\n{VALID_SEPARATOR}\n{VALID_ROW}\n", encoding="utf-8"
    )
    with pytest.raises(FrameInputError, match="disagree"):
        run_frame_builder(
            repo_root=ROOT,
            project_config_path=PROJECT_CONFIG,
            index_dir=bundle,
            output_dir=tmp_path / "out",
            run_id="stray",
            filing_window_start=WINDOW_START,
            filing_window_end=WINDOW_END,
        )


# --- naming guard (binding correction: no analytical_period in FRAME) --------


def test_frame_carries_no_analytical_period_naming() -> None:
    for path in (FRAME_MODULE_PATH, FRAME_SCHEMA_PATH, CLI):
        assert "analytical_period" not in path.read_text(encoding="utf-8"), path


# --- CLI ----------------------------------------------------------------------


def _cli(*extra: str, cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *extra], capture_output=True, text=True, cwd=cwd
    )


def _frame_args(output_dir: Path, run_id: str) -> list[str]:
    return [
        "--mode", "frame",
        "--config", str(PROJECT_CONFIG),
        "--index-dir", str(FIXTURE_DIR),
        "--filing-window-start", "2022-08-01",
        "--filing-window-end", "2023-02-28",
        "--output-dir", str(output_dir),
        "--run-id", run_id,
    ]


def test_cli_frame_mode_runs_and_writes_manifest(tmp_path: Path) -> None:
    completed = _cli(*_frame_args(tmp_path / "out", "cli-frame"))
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["frame_version"] == "FRAME_v0.0-fixture"
    assert payload["counts"] == EXPECTED["counts"]
    run_dir = Path(payload["run_dir"])
    assert (run_dir / "filer_frame_manifest.json").exists()


def test_cli_frame_dry_run_writes_nothing(tmp_path: Path) -> None:
    output_dir = tmp_path / "dry"
    completed = _cli(*_frame_args(output_dir, "cli-frame-dry"), "--dry-run")
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["dry_run"] is True and payload["run_dir"] is None
    assert not output_dir.exists()


def test_cli_frame_mode_rejects_sentinel_flags(tmp_path: Path) -> None:
    completed = _cli(
        *_frame_args(tmp_path / "out", "cli-cross"),
        "--input", str(FIXTURE_DIR),
    )
    assert completed.returncode == 2
    assert "--input" in completed.stderr


def test_cli_sentinel_mode_rejects_frame_flags(tmp_path: Path) -> None:
    completed = _cli(
        "--config", str(ROOT / "configs" / "universe_sample_rules.yaml"),
        "--input", str(ROOT / "evals" / "fixtures" / "universe_sentinel"),
        "--output-dir", str(tmp_path / "out"),
        "--run-id", "cli-cross-sentinel",
        "--index-dir", str(FIXTURE_DIR),
    )
    assert completed.returncode == 2
    assert "--index-dir" in completed.stderr


def test_cli_default_mode_is_sentinel_and_requires_input(tmp_path: Path) -> None:
    completed = _cli(
        "--config", str(ROOT / "configs" / "universe_sample_rules.yaml"),
        "--output-dir", str(tmp_path / "out"),
        "--run-id", "cli-no-input",
    )
    assert completed.returncode == 2
    assert "sentinel mode requires: --input" in completed.stderr


def test_cli_frame_mode_rejects_invalid_window_date(tmp_path: Path) -> None:
    args = _frame_args(tmp_path / "out", "cli-bad-date")
    args[args.index("2022-08-01")] = "not-a-date"
    completed = _cli(*args)
    assert completed.returncode == 2
    assert "invalid filing-window date" in completed.stderr
