"""Tests for direct economic PCT V3 without a task-family layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.pct_combined_snapshot import CombinedSnapshotFailure
from dynamic_ai_products.pct_economic_pct_v3 import (
    OUTPUT_SCHEMA,
    validate_economic_pct_output_v3,
)
from dynamic_ai_products.pct_economic_pct_v3_smoke import run_economic_pct_v3_smoke

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = Draft202012Validator(json.loads((ROOT / OUTPUT_SCHEMA).read_text()))
PACKET = {"passages": [{"passage_id": "one", "text": "One."}]}
DISCOVERY = {"product_families": [], "products": [{"id": "P1"}, {"id": "P2"}]}


def _output() -> dict:
    return {
        "economic_products": [{
            "id": "EP1",
            "name": "Example",
            "source_product_ids": ["P1"],
            "passage_refs": ["P001"],
            "capabilities": [{"id": "C1", "text": "edit images", "passage_refs": ["P001"]}],
            "tasks": [{
                "id": "T1",
                "capability_ids": ["C1"],
                "text": "edit images for projects",
                "passage_refs": ["P001"],
            }],
        }],
        "not_selected_product_ids": ["P2"],
    }


def _validate(value: dict) -> dict:
    return validate_economic_pct_output_v3(json.dumps(value), PACKET, DISCOVERY, VALIDATOR)


def test_v3_accepts_direct_product_capability_task_output() -> None:
    assert _validate(_output()) == _output()


def test_v3_refuses_task_with_dangling_capability() -> None:
    output = _output()
    output["economic_products"][0]["tasks"][0]["capability_ids"] = ["C9"]
    with pytest.raises(CombinedSnapshotFailure, match="absent capability"):
        _validate(output)


def test_v3_refuses_unresolvable_task_evidence() -> None:
    output = _output()
    output["economic_products"][0]["tasks"][0]["passage_refs"] = ["P002"]
    with pytest.raises(CombinedSnapshotFailure, match="absent references"):
        _validate(output)


def test_v3_refuses_incomplete_discovery_candidate_partition() -> None:
    output = _output()
    output["not_selected_product_ids"] = []
    with pytest.raises(CombinedSnapshotFailure, match="selected or not selected"):
        _validate(output)


def test_v3_refuses_candidate_returned_in_combined_and_separate_products() -> None:
    output = _output()
    output["economic_products"][0]["source_product_ids"] = ["P1", "P2"]
    output["economic_products"].append({
        **_output()["economic_products"][0],
        "id": "EP2",
        "source_product_ids": ["P2"],
    })
    output["not_selected_product_ids"] = []
    with pytest.raises(CombinedSnapshotFailure, match="selected more than once"):
        _validate(output)


def test_v3_prompt_shows_item1_before_discovery_and_has_no_task_family_layer() -> None:
    prompt = (ROOT / "prompts/extraction/pct_item1_economic_pct_v3.md").read_text()
    assert prompt.index("the complete verified Item 1 packet") < prompt.index("discovery candidate map")
    assert "task family" not in prompt.lower()
    assert "commercially meaningful action that the customer" in prompt
    assert (
        "When you combine product candidates into one economic product, do not also\n"
        "return any of those same candidates as separate economic products."
    ) in prompt
    assert "A product-family ID (`F#`) may help name or organize an economic product" in prompt
    assert "more underlying product IDs (`P#`) in `source_product_ids`." in prompt
    assert "independently commercially distinct" in prompt
    assert "modules, brands, editions, features, or" in prompt
    assert "action that the customer performs on an\nidentifiable object" in prompt
    assert "not as a benefit, desired result, or performance improvement." in prompt


def test_v3_dry_run_creates_no_directory(tmp_path: Path) -> None:
    result = run_economic_pct_v3_smoke(
        plan=[{"issuer_name": "Example"}],
        packets_by_key={},
        discoveries_by_key={},
        output_root=tmp_path,
        run_id="v3-dry",
        prompt_sha256="prompt",
        schema_sha256="schema",
        discovery_records_sha256="discovery",
        generate=None,
        model={},
        clock=lambda: None,  # type: ignore[arg-type]
        dry_run=True,
    )
    assert result["run_dir"] is None
    assert not (tmp_path / "v3-dry").exists()
