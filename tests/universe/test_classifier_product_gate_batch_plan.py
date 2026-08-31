"""Fixture-first tests for the model-free 100-row product-gate batch plan."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from dynamic_ai_products import classifier_product_gate_batch_plan as plan
from dynamic_ai_products import lineage_classifier_product_gate_batch_v1 as batch_run
from dynamic_ai_products import lineage_classifier_pilot_v1 as pilot_run
from dynamic_ai_products.classifier_annual_coverage_cohort import (
    COVERAGE_EXCLUSIONS_FILENAME,
    COVERAGE_MANIFEST_CONTRACT,
    COVERAGE_MANIFEST_FILENAME,
    COVERAGE_RECORDS_FILENAME,
)
from dynamic_ai_products.classifier_candidate_cohort import COHORT_RECORDS_FILENAME
from dynamic_ai_products.universe.lineage_screen import ScreenInputError

ROOT = Path(__file__).resolve().parents[2]
CLOCK = lambda: datetime(2026, 8, 31, tzinfo=timezone.utc)  # noqa: E731

sys.path.insert(0, str(Path(__file__).parent))

from test_classifier_calibration_selection import (  # noqa: E402
    cohort as cohort,  # noqa: F401,PLC0414 - re-exported pytest fixture
    packet_cohort as packet_cohort,  # noqa: F401,PLC0414
    release as release,  # noqa: F401,PLC0414
)
from test_classifier_pilot_v1_run import _grant  # noqa: E402


def _sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _row(index: int) -> dict:
    cik = f"{9000000000 + index:010d}"
    return {
        "cik": cik, "accession": f"{cik}-22-000001", "company_id": f"CIK{cik}",
        "source_id": f"sec-primary:{cik}", "packet_sha256": _sha(cik.encode()),
        "admission_origin": "model_screen" if index % 2 else "human_review",
        "screen_status": "LIKELY_ELIGIBLE" if index % 2 else "BOUNDARY_OR_UNCERTAIN",
        "admission_provenance": {"release_id": "fixture"},
        "coverage_class": "complete_2021_2025",
        "observed_annual_filing_years": [2021, 2022, 2023, 2024, 2025],
    }


def _coverage(tmp_path: Path, count: int = 201):
    directory = tmp_path / "coverage"
    directory.mkdir()
    records = "".join(json.dumps(_row(i), sort_keys=True) + "\n" for i in range(count)).encode()
    exclusions = b""
    (directory / COVERAGE_RECORDS_FILENAME).write_bytes(records)
    (directory / COVERAGE_EXCLUSIONS_FILENAME).write_bytes(exclusions)
    manifest = {
        "manifest_contract": COVERAGE_MANIFEST_CONTRACT,
        "coverage_cohort_id": "coverage-fixture",
        "no_model_call": True, "is_software_universe": False,
        "is_classifier_output": False, "applied_after_high_recall_screen": True,
        "counts": {"included": count},
        "sources": {"candidate_cohort": {
            "cohort_id": "candidate-fixture", "manifest_sha256": "a" * 64,
            "records_jsonl_sha256": "b" * 64}},
        "output_hashes": {
            COVERAGE_RECORDS_FILENAME: _sha(records),
            COVERAGE_EXCLUSIONS_FILENAME: _sha(exclusions),
        },
    }
    path = directory / COVERAGE_MANIFEST_FILENAME
    path.write_bytes((json.dumps(manifest, sort_keys=True) + "\n").encode())
    return path, _sha(path.read_bytes())


def _build(tmp_path: Path, *, count: int = 201, dry_run: bool = True):
    coverage, digest = _coverage(tmp_path, count)
    output = tmp_path / plan.BATCH_PLAN_FILENAME
    result = plan.build_product_gate_batch_plan(
        repo_root=ROOT, coverage_manifest_path=coverage,
        coverage_manifest_sha256=digest, output_path=output,
        batch_plan_id="product-gate-batches-fixture", clock=CLOCK,
        dry_run=dry_run)
    return result, output, coverage, digest


def test_plan_partitions_source_order_into_fixed_100_row_batches(tmp_path):
    result, _output, _coverage_path, _digest = _build(tmp_path)
    assert result["counts"] == {
        "selected_rows": 201, "batch_count": 3, "full_batches": 2,
        "final_batch_rows": 1}
    assert [(b["batch_id"], b["first_row_ordinal"], b["last_row_ordinal"], len(b["rows"]))
            for b in result["batches"]] == [
                ("batch-0001", 1, 100, 100),
                ("batch-0002", 101, 200, 100),
                ("batch-0003", 201, 201, 1)]
    assert all(result["reconciliation"].values())


def test_dry_run_creates_no_artifact(tmp_path):
    _result, output, _coverage_path, _digest = _build(tmp_path, dry_run=True)
    assert not output.exists()


def test_write_once_round_trip_and_loader(tmp_path):
    result, output, _coverage_path, _digest = _build(tmp_path, dry_run=False)
    assert output.is_file()
    assert plan.require_product_gate_batch_plan(
        output, expected_sha256=_sha(output.read_bytes()), repo_root=ROOT) == result
    with pytest.raises(ScreenInputError, match="already exists"):
        plan.build_product_gate_batch_plan(
            repo_root=ROOT, coverage_manifest_path=_coverage_path,
            coverage_manifest_sha256=_digest, output_path=output,
            batch_plan_id="new-id", clock=CLOCK)


def test_loader_refuses_a_wrong_filename_and_digest(tmp_path):
    _result, output, _coverage_path, _digest = _build(tmp_path, dry_run=False)
    with pytest.raises(ScreenInputError, match="different artifact"):
        plan.require_product_gate_batch_plan(
            output.with_name("not-a-plan.json"), expected_sha256="0" * 64,
            repo_root=ROOT)
    with pytest.raises(ScreenInputError, match="pinned digest"):
        plan.require_product_gate_batch_plan(
            output, expected_sha256="0" * 64, repo_root=ROOT)


def test_builder_refuses_coverage_record_drift(tmp_path):
    coverage, digest = _coverage(tmp_path, 1)
    records = coverage.parent / COVERAGE_RECORDS_FILENAME
    records.write_bytes(records.read_bytes() + b"\n")
    with pytest.raises(ScreenInputError, match="Annual coverage output"):
        plan.build_product_gate_batch_plan(
            repo_root=ROOT, coverage_manifest_path=coverage,
            coverage_manifest_sha256=digest,
            output_path=tmp_path / plan.BATCH_PLAN_FILENAME,
            batch_plan_id="drift", clock=CLOCK, dry_run=True)


def test_completed_adr_138_cohort_derives_the_expected_2799_row_plan(tmp_path):
    """Pin the live model-free input when it is present; never write beside it."""
    coverage = (ROOT / "data/runs/universe-annual-coverage-cohorts"
                / "universe-annual-coverage-cohort-v1-20260829"
                / COVERAGE_MANIFEST_FILENAME)
    if not coverage.is_file():
        pytest.skip("The completed ADR-138 annual-coverage artifact is not present.")
    result = plan.build_product_gate_batch_plan(
        repo_root=ROOT, coverage_manifest_path=coverage,
        coverage_manifest_sha256=_sha(coverage.read_bytes()),
        output_path=tmp_path / plan.BATCH_PLAN_FILENAME,
        batch_plan_id="live-input-check", clock=CLOCK, dry_run=True)
    assert result["counts"] == {
        "selected_rows": 2799, "batch_count": 28, "full_batches": 27,
        "final_batch_rows": 99}
    assert all(result["reconciliation"].values())


def test_batch_route_selects_only_the_authorized_named_batch(tmp_path):
    _result, output, coverage, digest = _build(tmp_path, count=201, dry_run=False)
    authorization = {
        "batch_id": "batch-0002",
        "logical_row_cap": 100,
        "coverage_cohort_id": "coverage-fixture",
        "coverage_cohort_manifest_sha256": digest,
        "coverage_cohort_records_sha256": _sha(
            (coverage.parent / COVERAGE_RECORDS_FILENAME).read_bytes()),
    }
    selection = batch_run._load_batch_plan(  # private seam: no model route here
        output, _sha(output.read_bytes()), ROOT, authorization)
    assert selection["batch_id"] == "batch-0002"
    assert len(selection["rows"]) == 100
    assert selection["rows"][0]["cik"] == _row(100)["cik"]
    with pytest.raises(ScreenInputError, match="exact row count"):
        batch_run._load_batch_plan(
            output, _sha(output.read_bytes()), ROOT,
            {**authorization, "logical_row_cap": 99})


def _coverage_from_candidate_cohort(tmp_path: Path, cohort, *, count: int = 10):
    """A genuine candidate/packet fixture behind a model-free coverage artifact."""
    directory = tmp_path / "coverage-from-candidate"
    directory.mkdir()
    rows = [{
        **row,
        "coverage_class": "complete_2021_2025",
        "observed_annual_filing_years": [2021, 2022, 2023, 2024, 2025],
    } for row in cohort.rows[:count]]
    records = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows).encode()
    exclusions = b""
    (directory / COVERAGE_RECORDS_FILENAME).write_bytes(records)
    (directory / COVERAGE_EXCLUSIONS_FILENAME).write_bytes(exclusions)
    candidate_records = (cohort.path.parent / COHORT_RECORDS_FILENAME).read_bytes()
    manifest = {
        "manifest_contract": COVERAGE_MANIFEST_CONTRACT,
        "coverage_cohort_id": "coverage-from-candidate-fixture",
        "no_model_call": True, "is_software_universe": False,
        "is_classifier_output": False, "applied_after_high_recall_screen": True,
        "counts": {"included": count},
        "sources": {"candidate_cohort": {
            "cohort_id": "cohort-fixture", "manifest_sha256": cohort.sha256,
            "records_jsonl_sha256": _sha(candidate_records)}},
        "output_hashes": {
            COVERAGE_RECORDS_FILENAME: _sha(records),
            COVERAGE_EXCLUSIONS_FILENAME: _sha(exclusions),
        },
    }
    path = directory / COVERAGE_MANIFEST_FILENAME
    path.write_bytes((json.dumps(manifest, sort_keys=True) + "\n").encode())
    return path, _sha(path.read_bytes()), rows


def test_batch_route_dry_run_resolves_one_authorized_batch_without_provider(
        cohort, packet_cohort, tmp_path):
    coverage, coverage_sha, rows = _coverage_from_candidate_cohort(tmp_path, cohort)
    plan_path = tmp_path / plan.BATCH_PLAN_FILENAME
    built = plan.build_product_gate_batch_plan(
        repo_root=ROOT, coverage_manifest_path=coverage,
        coverage_manifest_sha256=coverage_sha, output_path=plan_path,
        batch_plan_id="batch-plan-fixture", clock=CLOCK)
    selection = SimpleNamespace(rows=rows, path=plan_path,
                                sha256=_sha(plan_path.read_bytes()))
    base = _grant(cohort, selection, tmp_path, name="batch-governance")
    authorization = {
        **base.authorization,
        "authorization_contract": batch_run.PRODUCT_GATE_BATCH_ROUTE.authorization_contract,
        "authorization_id": "batch-fixture", "run_kind": batch_run.PRODUCT_GATE_BATCH_ROUTE.run_kind,
        "output_contract": batch_run.PRODUCT_GATE_BATCH_ROUTE.record_contract,
        "output_axes_contract": batch_run.PRODUCT_GATE_BATCH_ROUTE.axes_contract,
        "prompt_template_path": batch_run.PRODUCT_GATE_BATCH_ROUTE.prompt_path,
        "prompt_template_sha256": _sha((ROOT / batch_run.PRODUCT_GATE_BATCH_ROUTE.prompt_path).read_bytes()),
        "selection_artifact_path": str(plan_path),
        "selection_artifact_sha256": _sha(plan_path.read_bytes()),
        "selection_kind": plan.SELECTION_KIND, "batch_id": "batch-0001",
        "coverage_cohort_id": built["coverage_cohort"]["coverage_cohort_id"],
        "coverage_cohort_manifest_sha256": coverage_sha,
        "coverage_cohort_records_sha256": _sha(
            (coverage.parent / COVERAGE_RECORDS_FILENAME).read_bytes()),
    }
    raw = (json.dumps(authorization, indent=2, sort_keys=True) + "\n").encode()
    reference = "batch_authorization.json"
    (base.root / reference).write_bytes(raw)

    run = batch_run.run_product_gate_batch(
        repo_root=ROOT, cohort_manifest_path=cohort.path,
        coverage_manifest_path=coverage, packet_manifest_path=packet_cohort.manifest_path,
        batch_plan_path=plan_path, governance_root=base.root,
        authorization_reference=reference, authorization_sha256=_sha(raw),
        output_dir=tmp_path / "batch-output", run_id="batch-fixture-run",
        clock=CLOCK, dry_run=True,
        client_factory=lambda **_kwargs: pytest.fail("dry run constructed a provider"),
    )
    assert run.status == "dry_run" and run.run_dir is None
    assert run.request_accounting == {
        "selected_rows": 10, "model_called_rows": 10, "logical_row_cap": 10,
        "count_attempt_cap": 30, "provider_attempt_cap": 50,
        "external_request_cap": 80,
    }
    assert not (tmp_path / "batch-output").exists()
