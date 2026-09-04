"""Offline tests for the development-only product-structure smoke."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.pct_combined_snapshot import CombinedSnapshotFailure
from dynamic_ai_products.pct_product_structure import (
    OUTPUT_SCHEMA,
    validate_product_structure_output,
)

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = Draft202012Validator(json.loads((ROOT / OUTPUT_SCHEMA).read_text()))
PACKET = {"passages": [{"passage_id": "one", "text": "One."}]}


def _output() -> dict:
    return {
        "product_families": [{"id": "F1", "name": "Example suite", "passage_refs": ["P001"]}],
        "products": [{"id": "P1", "name": "Example product", "product_family_id": "F1", "availability_status": "general_availability", "passage_refs": ["P001"]}],
    }


def _validate(value: dict) -> dict:
    return validate_product_structure_output(json.dumps(value), PACKET, VALIDATOR)


def test_valid_structure_accepts_a_named_family_and_linked_product() -> None:
    assert _validate(_output()) == _output()


def test_product_may_have_no_named_family() -> None:
    value = _output()
    value["products"][0]["product_family_id"] = None
    assert _validate(value)["products"][0]["product_family_id"] is None


def test_structure_drops_an_unlinked_family_without_changing_products() -> None:
    value = _output()
    value["product_families"].append(
        {"id": "F2", "name": "Unused named suite", "passage_refs": ["P001"]}
    )

    snapshot = _validate(value)

    assert snapshot["product_families"] == [_output()["product_families"][0]]
    assert snapshot["products"] == value["products"]


def test_structure_refuses_dangling_family_pipeline_fields_and_bad_refs() -> None:
    value = _output()
    value["products"][0]["product_family_id"] = "F9"
    with pytest.raises(CombinedSnapshotFailure) as error:
        _validate(value)
    assert error.value.reason_code == "dangling_product_family_reference"

    value = _output()
    value["products"][0]["evidence_text"] = "must be pipeline derived"
    with pytest.raises(CombinedSnapshotFailure, match="Additional properties"):
        _validate(value)

    value = _output()
    value["products"][0]["passage_refs"] = ["P01"]
    with pytest.raises(CombinedSnapshotFailure) as error:
        _validate(value)
    assert error.value.reason_code in {"snapshot_contract_violation", "evidence_reference_unresolvable"}


def test_prompt_has_family_product_boundary_and_excludes_later_layers() -> None:
    text = (ROOT / "prompts/extraction/pct_item1_product_structure_v1.md").read_text()
    assert "A product family is not itself a product" in text
    assert "only if at least one returned product names it through" in text
    assert "A family may have one product when Item 1 establishes no" in text
    assert "Do not use substantially the same named commercial grouping as both a product" in text
    assert "Do not turn a list of names into a product catalogue" in text
    assert "Do not assess or describe products beyond their commercial structure." in text
    assert "Do not extract capabilities or customer tasks." in text
