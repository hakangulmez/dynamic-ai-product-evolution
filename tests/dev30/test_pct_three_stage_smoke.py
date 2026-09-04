"""Tests for product consolidation -> capability -> task extraction smoke."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

from dynamic_ai_products.pct_capability_extraction import validate_capability_extraction_output
from dynamic_ai_products.pct_economic_product_consolidation import (
    validate_economic_product_consolidation_output,
)
from dynamic_ai_products.pct_three_stage_smoke import (
    _render_with_item1,
    run_three_stage_smoke,
)

ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION_VALIDATOR = Draft202012Validator(json.loads((ROOT / "schemas/pct_item1_economic_product_consolidation_output.v1.schema.json").read_text()))
CAPABILITY_VALIDATOR = Draft202012Validator(json.loads((ROOT / "schemas/pct_item1_capability_extraction_output.v1.schema.json").read_text()))
TASK_VALIDATOR = Draft202012Validator(json.loads((ROOT / "schemas/pct_item1_tasks_flat_output.v2.schema.json").read_text()))


def _packet() -> dict:
    return {
        "cik": "0000000001", "accession": "0000000001-22-000001",
        "baseline_cutoff": "2022-12-31", "packet_sha256": "packet",
        "passages": [{"passage_id": "one", "text": "Customers buy the image platform."}],
    }


def _discovery() -> dict:
    return {"product_families": [], "products": [{"id": "P1", "name": "Editor", "passage_refs": ["P001"]}, {"id": "P2", "name": "Viewer", "passage_refs": ["P001"]}]}


def _consolidation() -> str:
    return json.dumps({"economic_products": [{"id": "EP1", "name": "Image platform", "source_product_ids": ["P1", "P2"], "passage_refs": ["P001"]}], "not_selected_product_ids": []})


def _capabilities() -> str:
    return json.dumps({"economic_product_capabilities": [{"economic_product_id": "EP1", "capabilities": [{"id": "C1", "text": "edit images", "passage_refs": ["P001"]}]}]})


def _tasks() -> str:
    return json.dumps({"tasks": [{"id": "T1", "economic_product_id": "EP1", "capability_refs": ["EP1:C1"], "text": "edit project images", "passage_refs": ["P001"]}]})


def test_consolidation_requires_an_exact_candidate_partition() -> None:
    result = validate_economic_product_consolidation_output(_consolidation(), _packet(), _discovery(), CONSOLIDATION_VALIDATOR)
    assert result["economic_products"][0]["source_product_ids"] == ["P1", "P2"]


def test_capability_stage_preserves_product_identity() -> None:
    products = json.loads(_consolidation())
    result = validate_capability_extraction_output(_capabilities(), _packet(), products, CAPABILITY_VALIDATOR)
    assert result["economic_products"][0]["id"] == "EP1"
    assert result["economic_products"][0]["source_product_ids"] == ["P1", "P2"]


def test_capability_prompt_input_is_fixed_product_map() -> None:
    prompt = _render_with_item1("CAPABILITY", _packet(), "Fixed economic-product map", json.loads(_consolidation()))
    assert "## Baseline Item 1" in prompt
    assert "Fixed economic-product map" in prompt
    assert '"EP1"' in prompt


def test_three_stage_smoke_stops_before_final_consolidation(tmp_path: Path) -> None:
    plan = [{"issuer_name": "Example", "cik": "0000000001", "accession": "0000000001-22-000001", "packet_sha256": "packet", "stage1_prompt": "ONE", "stage1_prompt_sha256": "one"}]
    responses = iter([_consolidation(), _capabilities(), _tasks()])
    result = run_three_stage_smoke(
        plan=plan, packets_by_key={("0000000001", "0000000001-22-000001"): _packet()}, discoveries_by_key={("0000000001", "0000000001-22-000001"): _discovery()},
        capability_template="TWO", task_template="THREE", consolidation_validator=CONSOLIDATION_VALIDATOR,
        capability_validator=CAPABILITY_VALIDATOR, task_validator=TASK_VALIDATOR, output_root=tmp_path,
        run_id="three-stage", consolidation_prompt_sha256="one", capability_prompt_sha256="two", task_prompt_sha256="three", discovery_records_sha256="source", generate=lambda _: next(responses), model={}, clock=lambda: datetime(2026, 9, 3, tzinfo=timezone.utc),
    )
    assert result["manifest"]["counts"] == {"stage1_extracted": 1, "stage1_review_uncertain": 0, "stage2_extracted": 1, "stage2_review_uncertain": 0, "stage3_extracted": 1, "stage3_review_uncertain": 0}
    assert not any("final" in path.name for path in (tmp_path / "three-stage").iterdir())


def test_three_stage_dry_run_writes_nothing(tmp_path: Path) -> None:
    result = run_three_stage_smoke(
        plan=[], packets_by_key={}, discoveries_by_key={}, capability_template="TWO", task_template="THREE", consolidation_validator=CONSOLIDATION_VALIDATOR, capability_validator=CAPABILITY_VALIDATOR, task_validator=TASK_VALIDATOR, output_root=tmp_path, run_id="dry", consolidation_prompt_sha256="one", capability_prompt_sha256="two", task_prompt_sha256="three", discovery_records_sha256="source", generate=None, model={}, clock=lambda: datetime(2026, 9, 3, tzinfo=timezone.utc), dry_run=True,
    )
    assert result["run_dir"] is None
    assert not (tmp_path / "dry").exists()
