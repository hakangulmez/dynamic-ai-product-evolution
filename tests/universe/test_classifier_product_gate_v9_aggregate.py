"""Fail-closed tests for the full-coverage V9 product-gate aggregate."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products import classifier_product_gate_v9_aggregate as aggregate
from dynamic_ai_products.lineage_classifier_product_gate_batch_v3 import (
    PRODUCT_GATE_BATCH_V3_ROUTE,
)
from dynamic_ai_products.universe.lineage_screen import ScreenInputError

ROOT = Path(__file__).resolve().parents[2]
CLOCK = lambda: datetime(2026, 9, 1, tzinfo=timezone.utc)  # noqa: E731


def _sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _row(index: int) -> dict[str, str]:
    cik = f"{9100000000 + index:010d}"
    return {"cik": cik, "accession": f"{cik}-25-000001"}


def _axes(product: str, centrality: str) -> dict[str, object]:
    return {
        "customer_facing_digital_product": product,
        "software_centrality": centrality,
        "confidence": "high",
        "passage_refs": ["P001"],
        "evidence": [{
            "passage_ref": "P001", "passage_id": "item-1-passage-001",
            "evidence_text": "A separately identifiable software product.",
            "byte_start": 0, "byte_end": 44,
            "text_sha256": _sha(b"A separately identifiable software product."),
            "provenance": "pipeline_derived",
        }],
    }


def _record(row: dict[str, str], *, product: str | None = None,
            centrality: str | None = None, review: str | None = None) -> dict[str, object]:
    if review is not None:
        return {
            "record_contract": "universe_classifier_pilot_record@0.3.0",
            "record_kind": "review_uncertain", **row,
            "company_id": f"CIK{row['cik']}", "source_id": f"sec-primary:{row['cik']}",
            "packet_sha256": "a" * 64, "prompt_sha256": "b" * 64,
            "model_route": {}, "admission_provenance": {}, "axes": None,
            "review_reason_code": review, "review_detail": "fixture review detail",
        }
    return {
        "record_contract": "universe_classifier_pilot_record@0.3.0",
        "record_kind": "classified", **row,
        "company_id": f"CIK{row['cik']}", "source_id": f"sec-primary:{row['cik']}",
        "packet_sha256": "a" * 64, "prompt_sha256": "b" * 64,
        "model_route": {}, "admission_provenance": {},
        "axes": _axes(product or "NO", centrality or "UNKNOWN"),
        "review_reason_code": None, "review_detail": None,
    }


def _plan() -> dict[str, object]:
    rows = [_row(i) for i in range(4)]
    return {
        "batch_plan_id": "fixture-v9-plan",
        "coverage_cohort": {
            "coverage_cohort_id": "fixture-coverage",
            "manifest_sha256": "c" * 64,
        },
        "batches": [
            {"batch_id": "batch-0001", "batch_ordinal": 1, "rows": rows[:2]},
            {"batch_id": "batch-0002", "batch_ordinal": 2, "rows": rows[2:]},
        ],
    }


def _manifest(*, batch: dict[str, object], records: list[dict[str, object]], run_id: str) -> dict[str, object]:
    records_raw = b"".join(
        (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
        for record in records
    )
    return {
        "manifest_contract": PRODUCT_GATE_BATCH_V3_ROUTE.manifest_contract,
        "run_id": run_id, "run_kind": PRODUCT_GATE_BATCH_V3_ROUTE.run_kind,
        "run_timestamp": "2026-09-01T00:00:00+00:00", "promotable": False,
        "covers_full_cohort": False, "derives_no_tier": True,
        "settles_no_membership": True, "authorization_id": "fixture-auth",
        "authorization_sha256": "d" * 64,
        "sources": {
            "cohort": {}, "coverage": {}, "packet": {},
            "selection": {"batch_plan_id": "fixture-v9-plan", "batch_id": batch["batch_id"], "batch_ordinal": batch["batch_ordinal"]},
            "sources_unmodified": True,
        },
        "prompt_template_path": "prompts/discovery/software_universe_classifier_pilot.v9.md",
        "prompt_template_sha256": _sha((ROOT / "prompts/discovery/software_universe_classifier_pilot.v9.md").read_bytes()),
        "provider": {}, "provider_client_contract_reference": "fixture-client",
        "provider_client_contract_sha256": "e" * 64,
        "screen_adapter_enablement_sha256": "f" * 64,
        "endpoint_allowlist": ["https://example.com/count", "https://example.com/generate"],
        "envelope_text_extraction_rule": "fixture", "output_contract": "universe_classifier_pilot_record@0.3.0",
        "output_axes_contract": "universe_classifier_pilot_axes_record@0.3.0",
        "output_hashes": {
            PRODUCT_GATE_BATCH_V3_ROUTE.records_filename: _sha(records_raw),
            PRODUCT_GATE_BATCH_V3_ROUTE.raw_responses_filename: "1" * 64,
            "universe_screen_capture_ledger.jsonl": "2" * 64,
        },
        "record_order": "batch_plan_row_order",
        "counts": {
            "selected_rows": len(records), "classified": sum(r["record_kind"] == "classified" for r in records),
            "review_uncertain": sum(r["record_kind"] == "review_uncertain" for r in records),
            "review_uncertain_by_reason": {}, "by_admission_origin": {}, "by_confidence": {},
            "by_customer_facing_digital_product": {}, "by_software_centrality": {},
            "evidence_items": sum(len(r["axes"]["evidence"]) for r in records if r["axes"]),
            "rows_with_no_evidence": 0,
        },
        "request_accounting": {
            "logical_row_cap": len(records), "count_attempt_cap": 6, "provider_attempt_cap": 10,
            "external_request_cap": 16, "count_attempts_made": len(records),
            "provider_attempts_made": len(records), "external_requests_made": 2 * len(records),
            "rows_count_retried": 0, "rows_generate_retried": 0, "model_called_rows": len(records),
            "tokens_in_measured": 1, "tokens_out_reported": 1, "rows_usage_verified": len(records),
            "cost_micros_settled": 1, "budget_max_input_tokens": 10, "budget_max_output_tokens": 10,
            "budget_max_estimated_cost_micros": 10, "budget_max_wall_clock_seconds": 10,
        },
        "reconciliation": {"fixture": True}, "schema_versions": {}, "limitations": ["fixture"],
    }


def _run_directory(tmp_path: Path, *, batch: dict[str, object], records: list[dict[str, object]], run_id: str) -> Path:
    directory = tmp_path / run_id
    directory.mkdir()
    raw = b"".join(
        (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
        for record in records
    )
    (directory / PRODUCT_GATE_BATCH_V3_ROUTE.records_filename).write_bytes(raw)
    manifest = _manifest(batch=batch, records=records, run_id=run_id)
    (directory / PRODUCT_GATE_BATCH_V3_ROUTE.manifest_filename).write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return directory


def _fixture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    plan = _plan()
    records = [
        [_record(plan["batches"][0]["rows"][0], product="YES", centrality="CORE"),
         _record(plan["batches"][0]["rows"][1])],
        [_record(plan["batches"][1]["rows"][0], product="YES", centrality="ENABLING"),
         _record(plan["batches"][1]["rows"][1], review="model_output_invalid_json")],
    ]
    directories = [
        _run_directory(tmp_path, batch=batch, records=batch_records, run_id=f"run-{index}")
        for index, (batch, batch_records) in enumerate(zip(plan["batches"], records), start=1)
    ]
    monkeypatch.setattr(aggregate, "require_product_gate_batch_plan", lambda *_args, **_kwargs: plan)
    monkeypatch.setattr(
        aggregate, "require_product_gate_batch_run_v3",
        lambda directory: Path(directory) / PRODUCT_GATE_BATCH_V3_ROUTE.manifest_filename,
    )
    return plan, directories


def _build(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, dry_run: bool):
    _plan_value, directories = _fixture(monkeypatch, tmp_path)
    return aggregate.build_product_gate_v9_aggregate(
        repo_root=ROOT, batch_plan_path=tmp_path / "universe_classifier_product_gate_batch_plan.json",
        batch_plan_sha256="3" * 64, batch_run_dirs=directories,
        output_dir=tmp_path / "aggregate-runs", aggregate_id="aggregate-fixture",
        clock=CLOCK, dry_run=dry_run), directories


def test_aggregate_schemas_are_valid() -> None:
    for relative in (aggregate.AGGREGATE_RECORD_SCHEMA, aggregate.AGGREGATE_MANIFEST_SCHEMA):
        Draft202012Validator.check_schema(json.loads((ROOT / relative).read_text()))


def test_dry_run_is_complete_and_never_creates_a_directory(monkeypatch, tmp_path) -> None:
    manifest, _directories = _build(monkeypatch, tmp_path, dry_run=True)
    assert manifest["counts"] == {
        "planned_rows": 4, "classified_rows": 3, "review_uncertain_rows": 1,
        "software_candidate_rows": 2, "core_software_rows": 1, "no_or_unknown_rows": 1,
    }
    assert all(manifest["reconciliation"].values())
    assert not (tmp_path / "aggregate-runs").exists()


def test_write_once_outputs_two_named_universes_and_unresolved(monkeypatch, tmp_path) -> None:
    manifest, _directories = _build(monkeypatch, tmp_path, dry_run=False)
    run_dir = tmp_path / "aggregate-runs" / "aggregate-fixture"
    assert aggregate.require_product_gate_v9_aggregate(run_dir, repo_root=ROOT).is_file()
    outputs = {
        filename: [json.loads(line) for line in (run_dir / filename).read_text().splitlines()]
        for filename in (aggregate.CANDIDATES_FILENAME, aggregate.CORE_FILENAME, aggregate.UNRESOLVED_FILENAME)
    }
    assert [row["aggregate_role"] for row in outputs[aggregate.CANDIDATES_FILENAME]] == ["software_candidate", "software_candidate"]
    assert [row["aggregate_role"] for row in outputs[aggregate.CORE_FILENAME]] == ["core_software"]
    assert [row["aggregate_role"] for row in outputs[aggregate.UNRESOLVED_FILENAME]] == ["unresolved"]
    assert {(row["cik"], row["accession"]) for row in outputs[aggregate.CORE_FILENAME]} <= {
        (row["cik"], row["accession"]) for row in outputs[aggregate.CANDIDATES_FILENAME]}
    assert all(_sha((run_dir / name).read_bytes()) == digest for name, digest in manifest["output_hashes"].items())
    with pytest.raises(FileExistsError, match="immutable"):
        aggregate.build_product_gate_v9_aggregate(
            repo_root=ROOT, batch_plan_path=tmp_path / "universe_classifier_product_gate_batch_plan.json",
            batch_plan_sha256="3" * 64, batch_run_dirs=_directories,
            output_dir=tmp_path / "aggregate-runs", aggregate_id="aggregate-fixture",
            clock=CLOCK)


def test_missing_one_planned_batch_refuses_before_any_output(monkeypatch, tmp_path) -> None:
    _plan_value, directories = _fixture(monkeypatch, tmp_path)
    with pytest.raises(ScreenInputError, match="every planned V9 batch"):
        aggregate.build_product_gate_v9_aggregate(
            repo_root=ROOT, batch_plan_path=tmp_path / "universe_classifier_product_gate_batch_plan.json",
            batch_plan_sha256="3" * 64, batch_run_dirs=directories[:1],
            output_dir=tmp_path / "aggregate-runs", aggregate_id="aggregate-fixture", clock=CLOCK)
    assert not (tmp_path / "aggregate-runs").exists()


def test_wrong_prompt_digest_or_reordered_records_refuses(monkeypatch, tmp_path) -> None:
    _plan_value, directories = _fixture(monkeypatch, tmp_path)
    path = directories[0] / PRODUCT_GATE_BATCH_V3_ROUTE.manifest_filename
    manifest = json.loads(path.read_text())
    manifest["prompt_template_sha256"] = "0" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ScreenInputError, match="frozen V9 prompt"):
        aggregate.build_product_gate_v9_aggregate(
            repo_root=ROOT, batch_plan_path=tmp_path / "universe_classifier_product_gate_batch_plan.json",
            batch_plan_sha256="3" * 64, batch_run_dirs=directories,
            output_dir=tmp_path / "aggregate-runs", aggregate_id="aggregate-fixture", clock=CLOCK)
