"""Stage 00B baseline-carrier tests (W2-A, ADR-088) — fully offline.

Every run derives its carrier from a frame built out of the committed
synthetic fixtures into a temporary directory; nothing reads ``data/runs``,
no network exists, and no model is called. The carrier decides no exclusion:
these tests pin that every frame filer is retained, that issuer status stays
unknown with an explicit basis, and that no DERA module and no
``issuer_filters`` dependency enters the stage.
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

import dynamic_ai_products.universe.baseline_carrier as bc
from dynamic_ai_products.universe.baseline_carrier import (
    CarrierInputError,
    run_baseline_carrier,
)
from dynamic_ai_products.universe.frame import run_frame_builder
from dynamic_ai_products.universe.io_utils import read_json, read_jsonl

ROOT = Path(__file__).resolve().parents[2]
FRAME_FIXTURE_DIR = ROOT / "evals" / "fixtures" / "edgar_full_index"
PROJECT_CONFIG = ROOT / "configs" / "project.yaml"
CARRIER_SCHEMA_PATH = (
    ROOT / "schemas" / "universe_baseline_carrier_manifest.schema.json"
)
CLI = ROOT / "pipelines" / "00_build_company_universe.py"
EXPECTED = read_json(FRAME_FIXTURE_DIR / "expected_carrier.json")


@pytest.fixture(scope="module")
def fixture_frame(tmp_path_factory: pytest.TempPathFactory):
    """A frame built from the committed fixtures, in a temp dir."""
    out = tmp_path_factory.mktemp("frame")
    result = run_frame_builder(
        repo_root=ROOT,
        project_config_path=PROJECT_CONFIG,
        index_dir=FRAME_FIXTURE_DIR,
        output_dir=out,
        run_id="carrier-tests-frame",
        filing_window_start=date(2022, 8, 1),
        filing_window_end=date(2023, 2, 28),
    )
    return result.run_dir / "filer_frame_manifest.json"


@pytest.fixture(scope="module")
def gold_run(fixture_frame, tmp_path_factory: pytest.TempPathFactory):
    out = tmp_path_factory.mktemp("carrier")
    result = run_baseline_carrier(
        repo_root=ROOT,
        project_config_path=PROJECT_CONFIG,
        frame_manifest_path=fixture_frame,
        output_dir=out,
        run_id="carrier-tests-gold",
    )
    manifest = read_json(result.manifest_path)
    rows = read_jsonl(result.run_dir / bc.CARRIER_ROWS_FILENAME)
    return result, manifest, rows


def test_gold_counts_match_expected(gold_run):
    _, manifest, _ = gold_run
    assert manifest["counts"] == EXPECTED["counts"]
    assert manifest["baseline_cutoff"] == EXPECTED["baseline_cutoff"]
    assert all(manifest["reconciliation"].values())


def test_gold_manifest_validates_against_canonical_schema(gold_run):
    _, manifest, _ = gold_run
    schema = read_json(CARRIER_SCHEMA_PATH)
    assert not list(Draft202012Validator(schema).iter_errors(manifest))


def test_gold_membership_matches_expected(gold_run):
    _, _, rows = gold_run
    candidates = [
        [r["stratum"], r["cik"], r["baseline_accession"]]
        for r in rows
        if r["baseline_status"] == "baseline_candidate"
    ]
    entrants = [
        [r["stratum"], r["cik"], r["first_filing_date"]]
        for r in rows
        if r["baseline_status"] == "post_baseline_entrant"
    ]
    assert candidates == EXPECTED["baseline_candidates"]
    assert entrants == EXPECTED["post_baseline_entrants"]
    assert [r["cik"] for r in rows if r["dual_stratum"]] == (
        EXPECTED["dual_stratum_ciks"]
    )
    assert [r["cik"] for r in rows if r["baseline_tie_broken"]] == (
        EXPECTED["ties_broken"]
    )


def test_baseline_is_latest_filing_on_or_before_cutoff(gold_run):
    # LEDGERWORKS filed annually on both sides of the cutoff; the baseline
    # is the 2022-09-15 10-K, never the later 2023-01-25 one.
    _, _, rows = gold_run
    (row,) = [
        r for r in rows
        if r["stratum"] == "domestic" and r["cik"] == "0002000001"
    ]
    assert row["baseline_status"] == "baseline_candidate"
    assert row["baseline_accession"] == "0002000001-22-000010"
    assert row["baseline_filing_date"] == "2022-09-15"
    assert row["filings_count"] == 2
    assert row["last_filing_date"] == "2023-01-25"


def test_post_cutoff_only_firms_are_retained_entrants(gold_run):
    _, _, rows = gold_run
    for cik in ("0002000012", "0002000013", "0002000014"):
        (row,) = [
            r for r in rows
            if r["stratum"] == "domestic" and r["cik"] == cik
        ]
        assert row["baseline_status"] == "post_baseline_entrant"
        assert row["baseline_accession"] is None
        assert row["baseline_canonical_name"] is None


def test_combined_filing_yields_one_row_per_filer(gold_run):
    # The combined 40-F (one accession, two filer CIKs, ADR-080) yields two
    # carrier rows sharing the baseline accession.
    _, _, rows = gold_run
    shared = [
        r for r in rows
        if r["baseline_accession"] == "0002000015-22-000003"
    ]
    assert [r["cik"] for r in shared] == ["0002000015", "0002000016"]
    assert all(r["stratum"] == "fpi_extension" for r in shared)


def test_no_exclusions_every_frame_filer_is_carried(gold_run, fixture_frame):
    _, _, rows = gold_run
    frame_dir = fixture_frame.parent
    expected_keys = {
        (stratum, record["cik"])
        for stratum, filename in (
            ("domestic", "historical_annual_filers.jsonl"),
            ("fpi_extension", "fpi_extension_filers.jsonl"),
        )
        for record in read_jsonl(frame_dir / filename)
    }
    assert {(r["stratum"], r["cik"]) for r in rows} == expected_keys


def test_issuer_status_unknown_with_declared_basis(gold_run):
    _, manifest, rows = gold_run
    assert manifest["issuer_status_basis"] == (
        "cover_page_evidence_not_yet_observed"
    )
    for row in rows:
        assert row["issuer_status"] == "unknown"
        assert row["issuer_status_basis"] == (
            "cover_page_evidence_not_yet_observed"
        )


def test_cutoff_comes_from_project_config(gold_run):
    _, manifest, _ = gold_run
    frozen = yaml.safe_load(PROJECT_CONFIG.read_text(encoding="utf-8"))[
        "universe"
    ]["baseline_cutoff"]
    assert manifest["baseline_cutoff"] == str(frozen) == "2022-11-29"


def test_manifest_records_freeze_reference_and_nonfrozen_frame(gold_run):
    # The fixture frame is not the frozen FRAME_v1; the manifest must say so
    # while still citing the committed freeze record by content hash.
    _, manifest, _ = gold_run
    freeze = manifest["frame_freeze"]
    assert freeze["path"] == "configs/frame_v1_freeze.json"
    assert freeze["frozen_version"] == "FRAME_v1"
    assert freeze["frame_is_frozen_frame"] is False
    from dynamic_ai_products.universe.io_utils import sha256_file

    assert freeze["record_sha256"] == sha256_file(
        ROOT / "configs" / "frame_v1_freeze.json"
    )


def test_no_dera_and_no_issuer_filters_dependency():
    source = (
        ROOT
        / "src" / "dynamic_ai_products" / "universe" / "baseline_carrier.py"
    ).read_text(encoding="utf-8")
    assert "frame_dera_validation" not in source
    assert "dera_acquisition" not in source
    assert "issuer_filters" not in source.replace(
        "``issuer_filters`` is intentionally not imported", ""
    )


def test_same_day_tie_breaks_to_highest_accession(tmp_path):
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    (index_dir / "master-2022-QTR3.idx").write_text(
        "CIK|Company Name|Form Type|Date Filed|Filename\n"
        + "-" * 80 + "\n"
        "3000001|SYNTHETIC TIE CORP|10-K|2022-09-01|"
        "edgar/data/3000001/0003000001-22-000001.txt\n"
        "3000001|SYNTHETIC TIE CORP|10-K|2022-09-01|"
        "edgar/data/3000001/0003000001-22-000002.txt\n",
        encoding="utf-8",
    )
    (index_dir / "fixture_manifest.json").write_text(
        json.dumps(
            {
                "description": "same-day duplicate annual filings tie case",
                "frame_version_on_build": "FRAME_v0.0-tie-fixture",
                "index_files": ["master-2022-QTR3.idx"],
            }
        ),
        encoding="utf-8",
    )
    frame = run_frame_builder(
        repo_root=ROOT,
        project_config_path=PROJECT_CONFIG,
        index_dir=index_dir,
        output_dir=tmp_path / "frame",
        run_id="tie-frame",
        filing_window_start=date(2022, 8, 1),
        filing_window_end=date(2023, 2, 28),
    )
    result = run_baseline_carrier(
        repo_root=ROOT,
        project_config_path=PROJECT_CONFIG,
        frame_manifest_path=frame.run_dir / "filer_frame_manifest.json",
        output_dir=tmp_path / "carrier",
        run_id="tie-carrier",
    )
    (row,) = read_jsonl(result.run_dir / bc.CARRIER_ROWS_FILENAME)
    assert row["baseline_status"] == "baseline_candidate"
    assert row["baseline_accession"] == "0003000001-22-000002"
    assert row["baseline_tie_broken"] is True
    assert result.counts["baseline_ties_broken"] == 1


def test_tampered_frame_artifact_is_refused(fixture_frame, tmp_path):
    copy_dir = tmp_path / "tampered-frame"
    shutil.copytree(fixture_frame.parent, copy_dir)
    target = copy_dir / "historical_annual_filers.jsonl"
    target.write_text(
        target.read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )
    with pytest.raises(CarrierInputError, match="hash mismatch"):
        run_baseline_carrier(
            repo_root=ROOT,
            project_config_path=PROJECT_CONFIG,
            frame_manifest_path=copy_dir / "filer_frame_manifest.json",
            output_dir=tmp_path / "carrier",
            run_id="tampered-carrier",
        )
    assert not (tmp_path / "carrier").exists()


def test_cutoff_outside_frame_window_is_refused(fixture_frame, tmp_path):
    config = tmp_path / "project.yaml"
    config.write_text(
        "universe:\n  baseline_cutoff: 2010-01-01\n", encoding="utf-8"
    )
    with pytest.raises(CarrierInputError, match="outside the frame filing"):
        run_baseline_carrier(
            repo_root=ROOT,
            project_config_path=config,
            frame_manifest_path=fixture_frame,
            output_dir=tmp_path / "carrier",
            run_id="bad-cutoff-carrier",
        )
    assert not (tmp_path / "carrier").exists()


def test_missing_cutoff_in_config_is_refused(fixture_frame, tmp_path):
    config = tmp_path / "project.yaml"
    config.write_text("universe: {}\n", encoding="utf-8")
    with pytest.raises(CarrierInputError, match="baseline_cutoff"):
        run_baseline_carrier(
            repo_root=ROOT,
            project_config_path=config,
            frame_manifest_path=fixture_frame,
            output_dir=tmp_path / "carrier",
            run_id="no-cutoff-carrier",
        )


def test_rerun_of_existing_run_id_is_refused(fixture_frame, tmp_path):
    out = tmp_path / "carrier"
    run_baseline_carrier(
        repo_root=ROOT,
        project_config_path=PROJECT_CONFIG,
        frame_manifest_path=fixture_frame,
        output_dir=out,
        run_id="immutable-carrier",
    )
    before = sorted(
        p.name for p in (out / "immutable-carrier").iterdir()
    )
    with pytest.raises(FileExistsError):
        run_baseline_carrier(
            repo_root=ROOT,
            project_config_path=PROJECT_CONFIG,
            frame_manifest_path=fixture_frame,
            output_dir=out,
            run_id="immutable-carrier",
        )
    assert sorted(
        p.name for p in (out / "immutable-carrier").iterdir()
    ) == before


def test_dry_run_writes_nothing(fixture_frame, tmp_path):
    out = tmp_path / "carrier"
    result = run_baseline_carrier(
        repo_root=ROOT,
        project_config_path=PROJECT_CONFIG,
        frame_manifest_path=fixture_frame,
        output_dir=out,
        run_id="dry-carrier",
        dry_run=True,
    )
    assert result.dry_run is True
    assert result.run_dir is None
    assert result.counts == EXPECTED["counts"]
    assert not out.exists()


def test_registry_carries_the_carrier_schema(gold_run):
    _, manifest, _ = gold_run
    registry = read_json(ROOT / "schemas" / "schema_version_manifest.json")
    assert (
        registry["schemas"]["universe_baseline_carrier_manifest"] == "0.1.0"
    )
    assert manifest["schema_versions"] == {
        "universe_baseline_carrier_manifest": "0.1.0"
    }


def test_cli_mode_runs_and_reports(fixture_frame, tmp_path):
    import subprocess
    import sys

    completed = subprocess.run(
        [
            sys.executable, str(CLI),
            "--mode", "baseline-carrier",
            "--config", str(PROJECT_CONFIG),
            "--frame-manifest", str(fixture_frame),
            "--output-dir", str(tmp_path / "carrier"),
            "--run-id", "cli-carrier",
        ],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["counts"] == EXPECTED["counts"]
    assert all(payload["reconciliation"].values())


def test_cli_rejects_cross_mode_flags(fixture_frame, tmp_path):
    import subprocess
    import sys

    completed = subprocess.run(
        [
            sys.executable, str(CLI),
            "--mode", "baseline-carrier",
            "--config", str(PROJECT_CONFIG),
            "--frame-manifest", str(fixture_frame),
            "--dera-dir", str(tmp_path),
            "--output-dir", str(tmp_path / "carrier"),
            "--run-id", "cli-bad-carrier",
        ],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode != 0
    assert "does not accept" in completed.stderr
