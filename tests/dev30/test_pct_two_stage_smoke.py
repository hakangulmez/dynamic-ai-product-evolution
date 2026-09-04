"""Tests for the bounded two-stage Item 1 PCT smoke."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

from dynamic_ai_products.pct_economic_product_capability import OUTPUT_SCHEMA as PRODUCT_SCHEMA
from dynamic_ai_products.pct_two_stage_smoke import (
    build_two_stage_plan,
    project_discovery_for_product_capability,
    render_product_capability_prompt,
    render_task_prompt,
    run_two_stage_smoke,
)

ROOT = Path(__file__).resolve().parents[2]
PRODUCT_VALIDATOR = Draft202012Validator(json.loads((ROOT / PRODUCT_SCHEMA).read_text()))
TASK_VALIDATOR = Draft202012Validator(
    json.loads((ROOT / "schemas/pct_item1_tasks_flat_output.v2.schema.json").read_text())
)


def _packet(cik: str, accession: str) -> dict:
    return {
        "cik": cik, "accession": accession, "baseline_cutoff": "2022-12-31",
        "packet_sha256": f"packet-{cik}",
        "passages": [{
            "passage_id": "one", "text": "Customers use the platform to edit images.",
            "byte_start": 0, "byte_end": 49,
        }],
    }


def _discovery() -> dict:
    return {"product_families": [], "products": [{"id": "P1"}]}


def _product_output() -> str:
    return json.dumps({"economic_products": [{
        "id": "EP1", "name": "Image platform", "source_product_ids": ["P1"],
        "passage_refs": ["P001"],
        "capabilities": [{"id": "C1", "text": "edit images", "passage_refs": ["P001"]}],
    }], "not_selected_product_ids": []})


def _task_output() -> str:
    return json.dumps({"tasks": [{
        "id": "T1", "economic_product_id": "EP1", "capability_refs": ["EP1:C1"],
        "text": "edit images for projects", "passage_refs": ["P001"],
    }]})


def test_renderers_place_item1_before_their_maps() -> None:
    packet = _packet("0000796343", "0000796343-22-000032")
    product = render_product_capability_prompt("PRODUCT", packet, _discovery())
    task = render_task_prompt("TASK", packet, {"economic_products": []})
    assert product.index("## Baseline Item 1") < product.index("## Discovery candidate map")
    assert task.index("## Baseline Item 1") < task.index("## Fixed economic-product")


def test_task_renderer_can_limit_item1_to_upstream_selected_evidence() -> None:
    packet = _packet("0000796343", "0000796343-22-000032")
    candidates = {
        "economic_products": [{
            "id": "EP1", "name": "Image platform", "source_product_ids": ["P1"],
            "passage_refs": ["P001"],
            "capabilities": [{
                "capability_ref": "EP1:C1", "text": "edit images", "passage_refs": ["P001"],
            }],
        }],
    }
    prompt = render_task_prompt(
        "TASK", packet, candidates, selected_evidence_only=True
    )
    assert "## Baseline Item 1" not in prompt
    assert prompt.index("## Fixed economic-product") < prompt.index("## Selected Item 1 evidence")
    assert "[P001]\nCustomers use the platform to edit images." in prompt


def test_product_candidate_projection_preserves_family_members_but_hides_f_ids() -> None:
    discovery = {
        "product_families": [{"id": "F1", "name": "Creative suite", "passage_refs": ["P001"]}],
        "products": [
            {"id": "P1", "name": "Editor", "product_family_id": "F1", "passage_refs": ["P001"]},
            {"id": "P2", "name": "Viewer", "product_family_id": None, "passage_refs": ["P001"]},
        ],
    }
    projection = project_discovery_for_product_capability(discovery)
    assert projection["product_families"] == [{
        "name": "Creative suite", "associated_product_ids": ["P1"], "passage_refs": ["P001"],
    }]
    assert "F1" not in json.dumps(projection)
    prompt = render_product_capability_prompt("PRODUCT", _packet("0000796343", "0000796343-22-000032"), discovery)
    assert "F1" not in prompt


def test_two_stage_smoke_only_calls_tasks_for_validated_stage_one(tmp_path: Path) -> None:
    key = ("0000796343", "0000796343-22-000032")
    plan = [{
        "issuer_name": "Adobe", "cik": key[0], "accession": key[1],
        "packet_sha256": "packet", "stage1_prompt": "stage one", "stage1_prompt_sha256": "one",
    }]
    responses = iter([_product_output(), _task_output()])
    result = run_two_stage_smoke(
        plan=plan,
        packets_by_key={key: _packet(*key)},
        discoveries_by_key={key: _discovery()},
        task_template="TASK",
        product_validator=PRODUCT_VALIDATOR,
        task_validator=TASK_VALIDATOR,
        output_root=tmp_path,
        run_id="two-stage",
        product_prompt_path="prompts/extraction/pct_item1_economic_product_capability_v3.md",
        product_prompt_sha256="product",
        task_prompt_path="prompts/extraction/pct_item1_tasks_flat_v5.md",
        task_prompt_sha256="task",
        discovery_records_sha256="discovery",
        generate=lambda _: next(responses),
        model={},
        clock=lambda: datetime(2026, 9, 3, tzinfo=timezone.utc),
    )
    assert result["manifest"]["counts"] == {
        "stage1_extracted": 1, "stage1_review_uncertain": 0,
        "stage2_extracted": 1, "stage2_review_uncertain": 0,
    }
    assert result["manifest"]["product_capability_prompt"] == {
        "path": "prompts/extraction/pct_item1_economic_product_capability_v3.md",
        "sha256": "product",
    }
    assert result["manifest"]["customer_tasks_prompt"] == {
        "path": "prompts/extraction/pct_item1_tasks_flat_v5.md",
        "sha256": "task",
    }
    assert result["manifest"]["limitations"][0] == (
        "Development-only five-firm smoke; not a sample or full run."
    )
    assert result["stage2_records"][0]["snapshot"]["tasks"][0]["text"] == "edit images for projects"


def test_two_stage_dry_run_writes_nothing(tmp_path: Path) -> None:
    result = run_two_stage_smoke(
        plan=[], packets_by_key={}, discoveries_by_key={}, task_template="TASK",
        product_validator=PRODUCT_VALIDATOR, task_validator=TASK_VALIDATOR,
        output_root=tmp_path, run_id="dry", product_prompt_sha256="product",
        task_prompt_sha256="task", discovery_records_sha256="discovery", generate=None,
        model={}, clock=lambda: datetime(2026, 9, 3, tzinfo=timezone.utc), dry_run=True,
    )
    assert result["run_dir"] is None
    assert not (tmp_path / "dry").exists()


def test_plan_uses_only_rows_with_both_packet_and_discovery() -> None:
    key = ("0000796343", "0000796343-22-000032")
    plan = build_two_stage_plan(
        product_capability_template="PRODUCT",
        packets_by_key={key: _packet(*key)}, discoveries_by_key={key: _discovery()},
    )
    assert [row["issuer_name"] for row in plan] == ["Adobe"]
