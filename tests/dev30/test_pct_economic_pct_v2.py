"""Tests for the direct economic PCT successor with nested tasks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.pct_combined_snapshot import CombinedSnapshotFailure
from dynamic_ai_products.pct_economic_pct_v2 import (
    OUTPUT_SCHEMA,
    validate_economic_pct_output_v2,
)
from dynamic_ai_products.pct_economic_pct_v2_smoke import build_economic_pct_plan

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = Draft202012Validator(json.loads((ROOT / OUTPUT_SCHEMA).read_text()))
PACKET = {"passages": [{"passage_id": "one", "text": "One."}]}
DISCOVERY = {"product_families": [], "products": [{"id": "P1"}, {"id": "P2"}]}


def _output() -> dict:
    return {
        "economic_products": [{
            "id": "EP1", "name": "Example", "source_product_ids": ["P1"],
            "passage_refs": ["P001"],
            "capabilities": [{"id": "C1", "text": "edit images", "passage_refs": ["P001"]}],
            "task_families": [{"id": "TF1", "name": "Image work", "task_ids": ["T1"], "passage_refs": ["P001"]}],
            "tasks": [{"id": "T1", "task_family_id": "TF1", "capability_ids": ["C1"], "text": "edit images for projects", "passage_refs": ["P001"]}],
        }],
        "not_selected_product_ids": ["P2"],
    }


def _validate(value: dict) -> dict:
    return validate_economic_pct_output_v2(json.dumps(value), PACKET, DISCOVERY, VALIDATOR)


def test_v2_accepts_product_local_task_family_and_task() -> None:
    assert _validate(_output()) == _output()


def test_v2_smoke_imports_shared_v1_plan_builder() -> None:
    assert callable(build_economic_pct_plan)


@pytest.mark.parametrize("collection,field,value", [
    ("tasks", "task_family_id", "TF9"),
    ("tasks", "capability_ids", ["C9"]),
    ("task_families", "task_ids", ["T9"]),
])
def test_v2_refuses_dangling_local_links(collection, field, value) -> None:
    output = _output()
    output["economic_products"][0][collection][0][field] = value
    with pytest.raises(CombinedSnapshotFailure):
        _validate(output)


def test_v2_refuses_task_family_that_does_not_partition_tasks() -> None:
    output = _output()
    output["economic_products"][0]["task_families"][0]["task_ids"] = []
    with pytest.raises(CombinedSnapshotFailure):
        _validate(output)


def test_v2_prompt_preserves_v1_semantics_and_adds_tasks() -> None:
    v1 = (ROOT / "prompts/extraction/pct_item1_economic_pct_v1.md").read_text()
    v2 = (ROOT / "prompts/extraction/pct_item1_economic_pct_v2.md").read_text()
    assert "For every discovery product ID, do exactly one" in v1 and v2
    assert "durable **task families** as customer outcomes or coherent workflows" in v2
    assert "A task family is the customer result it\nenables." in v2
    assert "4. state the distinct customer **tasks** within each task family." in v2
    assert "A task is a distinct customer action\nwithin that task family." in v2
    assert "**Status:" not in v2
