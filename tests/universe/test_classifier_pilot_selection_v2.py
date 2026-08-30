"""Contract tests for the annual-coverage-backed pilot selection."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dynamic_ai_products import classifier_pilot_selection_v2 as selection
from dynamic_ai_products.universe.lineage_screen import ScreenInputError


ROOT = Path(__file__).resolve().parents[2]
COVERAGE = ROOT / (
    "data/runs/universe-annual-coverage-cohorts/"
    "universe-annual-coverage-cohort-v1-20260829/"
    "universe_annual_coverage_cohort_manifest.json")
CANDIDATE = ROOT / (
    "data/runs/universe-classifier-candidate-cohorts/"
    "universe-classifier-candidate-cohort-v1-20260824/"
    "universe_classifier_candidate_cohort_manifest.json")
PACKETS = ROOT / (
    "data/runs/baseline-packets/baseline-packets-domestic-text-lineage-v5-20260819/"
    "baseline_packet_manifest.json")
CLOCK = lambda: datetime(2026, 8, 29, tzinfo=timezone.utc)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def built(tmp_path):
    if not COVERAGE.is_file() or not CANDIDATE.is_file():
        pytest.skip("committed ADR-138 artifacts are absent from this checkout")
    return selection.build_pilot_selection_v2_artifact(
        repo_root=ROOT,
        coverage_manifest_path=COVERAGE,
        coverage_manifest_sha256=digest(COVERAGE),
        candidate_cohort_manifest_path=CANDIDATE,
        candidate_cohort_manifest_sha256=digest(CANDIDATE),
        packet_manifest_path=PACKETS,
        packet_manifest_sha256=digest(PACKETS),
        output_path=tmp_path / selection.PILOT_SELECTION_V2_FILENAME,
        selection_id="fixture-pilot-v2",
        clock=CLOCK,
    )


def test_named_rows_are_unique_and_have_expected_coverage(built):
    assert len(selection.PILOT_ROWS_V2) == 10
    assert len({row[:2] for row in selection.PILOT_ROWS_V2}) == 10
    assert built["counts"]["selected_rows"] == 10
    assert built["counts"]["by_admission_origin"] == {
        "human_review": 2, "model_screen": 8}
    assert built["counts"]["by_screen_status"] == {
        "LIKELY_ELIGIBLE": 5, "BOUNDARY_OR_UNCERTAIN": 5}
    for row in built["rows"]:
        assert {2022, 2023, 2024, 2025} <= set(row["observed_annual_filing_years"])


def test_selection_binds_annual_source_not_old_calibration_selection(built):
    assert built["selection_contract"] == selection.PILOT_SELECTION_V2_CONTRACT
    assert "source_selection_path" not in built
    assert "source_selection_sha256" not in built
    assert built["coverage_cohort_manifest_path"] == str(COVERAGE)
    assert built["coverage_cohort_manifest_sha256"] == digest(COVERAGE)


def test_dry_run_writes_nothing(tmp_path):
    if not COVERAGE.is_file() or not CANDIDATE.is_file():
        pytest.skip("committed ADR-138 artifacts are absent from this checkout")
    output = tmp_path / "absent" / selection.PILOT_SELECTION_V2_FILENAME
    built = selection.build_pilot_selection_v2_artifact(
        repo_root=ROOT, coverage_manifest_path=COVERAGE,
        coverage_manifest_sha256=digest(COVERAGE),
        candidate_cohort_manifest_path=CANDIDATE,
        candidate_cohort_manifest_sha256=digest(CANDIDATE),
        packet_manifest_path=PACKETS,
        packet_manifest_sha256=digest(PACKETS),
        output_path=output, selection_id="dry", clock=CLOCK, dry_run=True)
    assert len(built["rows"]) == 10
    assert not output.exists() and not output.parent.exists()


def test_written_selection_round_trips_under_its_own_schema(tmp_path):
    if not COVERAGE.is_file() or not CANDIDATE.is_file():
        pytest.skip("committed ADR-138 artifacts are absent from this checkout")
    output = tmp_path / selection.PILOT_SELECTION_V2_FILENAME
    built = selection.build_pilot_selection_v2_artifact(
        repo_root=ROOT, coverage_manifest_path=COVERAGE,
        coverage_manifest_sha256=digest(COVERAGE),
        candidate_cohort_manifest_path=CANDIDATE,
        candidate_cohort_manifest_sha256=digest(CANDIDATE),
        packet_manifest_path=PACKETS,
        packet_manifest_sha256=digest(PACKETS), output_path=output,
        selection_id="round-trip", clock=CLOCK)
    assert selection.require_pilot_selection_v2(
        output, expected_sha256=digest(output), repo_root=ROOT) == built


def test_loader_refuses_v1_selection(tmp_path):
    foreign = tmp_path / selection.PILOT_SELECTION_V2_FILENAME
    foreign.write_text('{"selection_contract":"universe_classifier_pilot_selection@0.1.0"}')
    with pytest.raises(ScreenInputError, match="different pilot selection contract"):
        selection.require_pilot_selection_v2(
            foreign, expected_sha256=digest(foreign), repo_root=ROOT)
