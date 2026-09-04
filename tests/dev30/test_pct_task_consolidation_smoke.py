"""Tests for final consolidation over fixed upstream PCT task candidates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

from dynamic_ai_products.pct_task_consolidation_smoke import (
    consolidation_candidate_map,
    render_consolidation_prompt,
    run_task_consolidation_smoke,
    validate_consolidation_output,
)

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = Draft202012Validator(
    json.loads((ROOT / "schemas/pct_item1_task_consolidation_output.v1.schema.json").read_text())
)


def _product_snapshot() -> dict:
    return {"economic_products": [{
        "id": "EP1", "name": "Image platform", "source_product_ids": ["P1"], "passage_refs": ["P001"],
        "capabilities": [
            {"id": "C1", "text": "edit images", "passage_refs": ["P001"]},
            {"id": "C2", "text": "store images", "passage_refs": ["P002"]},
        ],
    }]}


def _task_snapshot() -> dict:
    return {"tasks": [
        {"id": "T1", "economic_product_id": "EP1", "capability_refs": ["EP1:C1"], "text": "edit images for projects", "passage_refs": ["P001"]},
        {"id": "T2", "economic_product_id": "EP1", "capability_refs": ["EP1:C2"], "text": "store images for projects", "passage_refs": ["P002"]},
    ]}


def _source() -> dict:
    return {"issuer_name": "Example", "cik": "0000000001", "accession": "0000000001-22-000001", "packet_sha256": "packet", "product_snapshot": _product_snapshot(), "task_snapshot": _task_snapshot()}


def _output() -> str:
    return json.dumps({"final_tasks": [{"id": "FT1", "economic_product_id": "EP1", "source_task_ids": ["T1", "T2"], "capability_refs": ["EP1:C1", "EP1:C2"], "text": "edit and store project images"}], "excluded_task_candidates": [], "unresolved_task_ids": []})


def test_prompt_receives_fixed_maps_not_item1_text() -> None:
    prompt = render_consolidation_prompt("PROMPT", consolidation_candidate_map(_product_snapshot(), _task_snapshot()))
    assert "Baseline Item 1" not in prompt
    assert "Customers use" not in prompt
    assert '"task_candidates"' in prompt


def test_validated_final_task_inherits_source_evidence() -> None:
    snapshot = validate_consolidation_output(_output(), consolidation_candidate_map(_product_snapshot(), _task_snapshot()), VALIDATOR)
    assert snapshot["final_tasks"][0]["source_passage_refs"] == ["P001", "P002"]


def test_validator_refuses_incomplete_candidate_disposition() -> None:
    raw = json.dumps({"final_tasks": [{"id": "FT1", "economic_product_id": "EP1", "source_task_ids": ["T1"], "capability_refs": ["EP1:C1"], "text": "edit project images"}], "excluded_task_candidates": [], "unresolved_task_ids": []})
    try:
        validate_consolidation_output(raw, consolidation_candidate_map(_product_snapshot(), _task_snapshot()), VALIDATOR)
    except Exception as exc:
        assert getattr(exc, "reason_code") == "task_candidate_partition_violation"
    else:  # pragma: no cover
        raise AssertionError("Incomplete candidate disposition was accepted.")


def test_validator_accepts_prompt_interface_level_reason() -> None:
    raw = json.dumps({"final_tasks": [{"id": "FT1", "economic_product_id": "EP1", "source_task_ids": ["T1"], "capability_refs": ["EP1:C1"], "text": "edit project images"}], "excluded_task_candidates": [{"task_id": "T2", "reason": "interface_level_step"}], "unresolved_task_ids": []})
    snapshot = validate_consolidation_output(
        raw, consolidation_candidate_map(_product_snapshot(), _task_snapshot()), VALIDATOR
    )
    assert snapshot["excluded_task_candidates"][0]["reason"] == "interface_level_step"


def test_run_writes_a_final_consolidation_smoke(tmp_path: Path) -> None:
    result = run_task_consolidation_smoke(
        source_records=[_source()], template="PROMPT", validator=VALIDATOR, output_root=tmp_path,
        run_id="consolidation", source_stage1_sha256="one", source_stage2_sha256="two",
        generate=lambda _: _output(), model={}, clock=lambda: datetime(2026, 9, 3, tzinfo=timezone.utc),
    )
    assert result["manifest"]["counts"] == {"extracted": 1, "review_uncertain": 0}
    assert (tmp_path / "consolidation" / "pct_item1_task_consolidation_human_review.html").exists()


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    result = run_task_consolidation_smoke(
        source_records=[_source()], template="PROMPT", validator=VALIDATOR, output_root=tmp_path,
        run_id="dry", source_stage1_sha256="one", source_stage2_sha256="two", generate=None,
        model={}, clock=lambda: datetime(2026, 9, 3, tzinfo=timezone.utc), dry_run=True,
    )
    assert result["run_dir"] is None
    assert not (tmp_path / "dry").exists()
