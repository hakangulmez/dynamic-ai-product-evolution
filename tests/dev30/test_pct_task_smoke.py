"""Tests for the task-granularity A/B smoke."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.pct_combined_snapshot import CombinedSnapshotFailure
from dynamic_ai_products.pct_task_smoke import _validate, task_candidate_map

ROOT = Path(__file__).resolve().parents[2]
PACKET = {"passages": [{"passage_id": "one", "text": "One."}]}
CANDIDATES = {"economic_products": [{"id": "EP1", "name": "Example", "source_product_ids": ["P1"], "passage_refs": ["P001"], "capabilities": [{"capability_ref": "EP1:C1", "text": "edit images", "passage_refs": ["P001"]}]}]}


def _flat() -> dict:
    return {"tasks": [{"id": "T1", "economic_product_id": "EP1", "capability_refs": ["EP1:C1"], "text": "edit images", "passage_refs": ["P001"]}]}


def _hierarchy() -> dict:
    return {"task_families": [{"id": "TF1", "economic_product_id": "EP1", "name": "Image editing", "task_ids": ["T1"], "passage_refs": ["P001"]}], "tasks": _flat()["tasks"]}


def _validator(name: str) -> Draft202012Validator:
    path = ROOT / "schemas" / f"pct_item1_tasks_{name}_output.v2.schema.json"
    return Draft202012Validator(json.loads(path.read_text()))


def test_flat_and_hierarchy_accept_one_valid_task() -> None:
    assert _validate(json.dumps(_flat()), PACKET, CANDIDATES, _validator("flat"), hierarchy=False) == _flat()
    assert _validate(json.dumps(_hierarchy()), PACKET, CANDIDATES, _validator("hierarchy"), hierarchy=True) == _hierarchy()


def test_task_refuses_unknown_product_cross_product_capability_and_missing_product() -> None:
    value = _flat()
    value["tasks"][0]["economic_product_id"] = "EP9"
    with pytest.raises(CombinedSnapshotFailure, match="EP9"):
        _validate(json.dumps(value), PACKET, CANDIDATES, _validator("flat"), hierarchy=False)

    value = _flat()
    value["tasks"][0]["capability_refs"] = ["EP1:C9"]
    with pytest.raises(CombinedSnapshotFailure, match="another product"):
        _validate(json.dumps(value), PACKET, CANDIDATES, _validator("flat"), hierarchy=False)

    with pytest.raises(CombinedSnapshotFailure, match="Every input economic product"):
        _validate(json.dumps({"tasks": []}), PACKET, CANDIDATES, _validator("flat"), hierarchy=False)


def test_task_can_be_limited_to_upstream_selected_evidence() -> None:
    packet = {"passages": [
        {"passage_id": "one", "text": "One."},
        {"passage_id": "two", "text": "Two."},
    ]}
    value = _flat()
    value["tasks"][0]["passage_refs"] = ["P002"]
    with pytest.raises(CombinedSnapshotFailure, match="outside the available task evidence"):
        _validate(
            json.dumps(value), packet, CANDIDATES, _validator("flat"),
            hierarchy=False, allowed_refs={"P001"},
        )


def test_hierarchy_requires_exact_one_family_per_task() -> None:
    value = _hierarchy()
    value["task_families"][0]["task_ids"] = []
    with pytest.raises(CombinedSnapshotFailure, match="non-empty"):
        _validate(json.dumps(value), PACKET, CANDIDATES, _validator("hierarchy"), hierarchy=True)

    value = _hierarchy()
    value["task_families"].append(value["task_families"][0] | {"id": "TF2"})
    with pytest.raises(CombinedSnapshotFailure, match="exactly one family"):
        _validate(json.dumps(value), PACKET, CANDIDATES, _validator("hierarchy"), hierarchy=True)


def test_candidate_map_excludes_prior_task_families() -> None:
    snapshot = {"economic_products": [{"id": "EP1", "name": "Example", "source_product_ids": ["P1"], "passage_refs": ["P001"], "capabilities": [{"id": "C1", "text": "edit images", "passage_refs": ["P001"]}], "task_families": [{"id": "old"}]}]}
    assert task_candidate_map(snapshot) == CANDIDATES


def test_prompts_are_real_ab_variants() -> None:
    flat = (ROOT / "prompts/extraction/pct_item1_tasks_flat_v2.md").read_text()
    hierarchy = (ROOT / "prompts/extraction/pct_item1_tasks_hierarchy_v2.md").read_text()
    assert "task families" not in flat.lower()
    assert "task families" in hierarchy.lower()
    assert "Split tasks when" in flat and "Split tasks when" in hierarchy


def test_v3_task_successor_uses_a_fixed_map_and_action_object_tasks() -> None:
    prompt = (ROOT / "prompts/extraction/pct_item1_tasks_flat_v3.md").read_text()
    assert prompt.index("the complete verified Item 1 packet") < prompt.index("fixed economic-product")
    assert "do not add, remove, merge, rename" in prompt
    assert "action that the customer performs on an\nidentifiable object" in prompt
    assert "not as a benefit, desired result, or performance improvement." in prompt
    assert "Do not create one task for every capability." in prompt
    assert "Do not\nrestate a capability as a task." in prompt


def test_v4_task_successor_uses_capability_to_task_granularity_rules() -> None:
    prompt = (ROOT / "prompts/extraction/pct_item1_tasks_flat_v4.md").read_text()
    assert prompt.index("the complete verified Item 1 packet") < prompt.index("fixed economic-product")
    assert "Combine capabilities into one task\nwhen they support the same customer action on the same object." in prompt
    assert "materially different\nobject, deliverable, or work objective." in prompt
    assert "Do not split one customer job into a\ncatalogue of feature-level tasks." in prompt
    assert "When a product has only one supported customer action,\none task is sufficient." in prompt


def test_v5_task_successor_uses_only_selected_upstream_evidence() -> None:
    prompt = (ROOT / "prompts/extraction/pct_item1_tasks_flat_v5.md").read_text()
    assert "selected Item 1 evidence bundle" in prompt
    assert "only Item 1 evidence available for this stage." in " ".join(prompt.split())
    assert "Do not infer information from Item 1 passages not supplied." in prompt
    assert "from the selected evidence\nbundle." in prompt
