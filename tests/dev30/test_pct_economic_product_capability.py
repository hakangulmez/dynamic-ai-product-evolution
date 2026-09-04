"""Tests for the first-stage economic-product and capability smoke."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.pct_combined_snapshot import CombinedSnapshotFailure
from dynamic_ai_products.pct_economic_product_capability import (
    OUTPUT_SCHEMA,
    validate_economic_product_capability_output,
)
from dynamic_ai_products.pct_economic_product_capability_smoke import (
    run_economic_product_capability_smoke,
)

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
        }],
        "not_selected_product_ids": ["P2"],
    }


def _validate(value: dict) -> dict:
    return validate_economic_product_capability_output(
        json.dumps(value), PACKET, DISCOVERY, VALIDATOR
    )


def test_accepts_direct_economic_product_and_capability_output() -> None:
    assert _validate(_output()) == _output()


def test_refuses_duplicate_discovery_candidate_assignment() -> None:
    output = _output()
    output["economic_products"][0]["source_product_ids"] = ["P1", "P2"]
    output["not_selected_product_ids"] = ["P2"]
    with pytest.raises(CombinedSnapshotFailure, match="selected or not selected"):
        _validate(output)


def test_refuses_unresolvable_capability_evidence() -> None:
    output = _output()
    output["economic_products"][0]["capabilities"][0]["passage_refs"] = ["P002"]
    with pytest.raises(CombinedSnapshotFailure, match="absent references"):
        _validate(output)


def test_refuses_discovery_family_id_as_source_product_id() -> None:
    output = _output()
    output["economic_products"][0]["source_product_ids"] = ["F1"]
    with pytest.raises(CombinedSnapshotFailure, match="does not match"):
        _validate(output)


def test_prompt_places_item1_before_discovery_and_contains_no_task_layer() -> None:
    prompt = (ROOT / "prompts/extraction/pct_item1_economic_product_capability_v1.md").read_text()
    assert prompt.index("the complete verified Item 1 packet") < prompt.index("discovery candidate map")
    assert "task family" not in prompt.lower()
    assert "customer **tasks**" not in prompt


def test_v2_product_capability_successor_keeps_family_ids_out_of_sources() -> None:
    prompt = (ROOT / "prompts/extraction/pct_item1_economic_product_capability_v2.md").read_text()
    assert prompt.index("the complete verified Item 1 packet") < prompt.index("discovery candidate map")
    assert "Do not return tasks in this\nstage." in prompt
    assert "Do not invent a product catalogue beyond the supplied discovery" in prompt
    assert "A product-family name is parent context, not a source product" in prompt
    assert (
        "Never return an economic product with an empty `source_product_ids` array."
        in " ".join(prompt.split())
    )
    assert "Treat each discovery product ID as a separate economic product by default." in prompt
    assert "Do not combine candidates merely because they belong to the same family," in prompt
    assert "A distinct named application or\nplatform remains separate" in prompt
    assert "separately identifiable\ncustomer offering." in prompt
    assert "Combine candidates only where Item 1 expressly establishes" in prompt
    assert (
        "do not also return any of those same candidates as separate economic products."
        in " ".join(prompt.split())
    )
    assert '"source_product_ids": ["P2"]' in prompt


def test_v3_product_capability_prompt_preserves_child_product_defaults() -> None:
    prompt = (ROOT / "prompts/extraction/pct_item1_economic_product_capability_v3.md").read_text()
    assert prompt.index("complete verified Item 1 packet") < prompt.index("discovery map")
    assert "A product family is parent context." in prompt
    assert "Treat each discovery product candidate as one economic product by default." in prompt
    assert "same suite, cloud, subscription, or family." in prompt
    assert "A plan, bundle, or package that merely contains other products is not" in prompt
    assert "Every discovery product ID must appear exactly once" in prompt
    assert "not a product name, benefit, strategy, or\ntask." in prompt
    assert '"source_product_ids": ["P2"]' in prompt


def test_dry_run_creates_no_directory(tmp_path: Path) -> None:
    result = run_economic_product_capability_smoke(
        plan=[{"issuer_name": "Example"}],
        packets_by_key={},
        discoveries_by_key={},
        output_root=tmp_path,
        run_id="product-capability-dry",
        prompt_sha256="prompt",
        schema_sha256="schema",
        discovery_records_sha256="discovery",
        generate=None,
        model={},
        clock=lambda: None,  # type: ignore[arg-type]
        dry_run=True,
    )
    assert result["run_dir"] is None
    assert not (tmp_path / "product-capability-dry").exists()
