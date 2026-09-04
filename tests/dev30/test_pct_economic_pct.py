"""Tests for discovery-constrained economic PCT output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.pct_combined_snapshot import CombinedSnapshotFailure
from dynamic_ai_products.pct_economic_pct import OUTPUT_SCHEMA, validate_economic_pct_output
from dynamic_ai_products.pct_economic_pct_smoke import (
    build_economic_pct_plan,
    run_economic_pct_smoke,
)

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = Draft202012Validator(json.loads((ROOT / OUTPUT_SCHEMA).read_text()))
PACKET = {"passages": [{"passage_id": "one", "text": "One."}]}
DISCOVERY = {"product_families": [], "products": [{"id": "P1"}, {"id": "P2"}]}


def _output() -> dict:
    return {
        "economic_products": [{
            "id": "EP1", "name": "Example platform", "source_product_ids": ["P1"],
            "passage_refs": ["P001"],
            "capabilities": [{"id": "C1", "text": "manage records", "passage_refs": ["P001"]}],
            "task_families": [{"id": "TF1", "capability_ids": ["C1"], "text": "manage records", "customer_outcome": "maintain records", "passage_refs": ["P001"]}],
        }],
        "not_selected_product_ids": ["P2"],
    }


def _validate(value: dict) -> dict:
    return validate_economic_pct_output(json.dumps(value), PACKET, DISCOVERY, VALIDATOR)


def test_economic_pct_accepts_exact_discovery_partition() -> None:
    assert _validate(_output()) == _output()


@pytest.mark.parametrize("change", [
    lambda value: value.update(not_selected_product_ids=[]),
    lambda value: value["economic_products"][0].update(source_product_ids=["P1", "P9"]),
    lambda value: value.update(not_selected_product_ids=["P1", "P2"]),
])
def test_economic_pct_refuses_missing_unknown_or_duplicate_candidate_assignment(change) -> None:
    value = _output()
    change(value)
    with pytest.raises(CombinedSnapshotFailure) as error:
        _validate(value)
    assert error.value.reason_code in {"candidate_partition_violation", "unknown_discovery_product_id"}


def test_economic_pct_refuses_cross_product_capability_and_bad_reference() -> None:
    value = _output()
    value["economic_products"][0]["task_families"][0]["capability_ids"] = ["C9"]
    with pytest.raises(CombinedSnapshotFailure) as error:
        _validate(value)
    assert error.value.reason_code == "dangling_capability_reference"

    value = _output()
    value["economic_products"][0]["passage_refs"] = ["P002"]
    with pytest.raises(CombinedSnapshotFailure) as error:
        _validate(value)
    assert error.value.reason_code == "evidence_reference_unresolvable"


def test_prompt_keeps_discovery_as_candidate_map_and_requires_accounting() -> None:
    text = (ROOT / "prompts/extraction/pct_item1_economic_pct_v1.md").read_text()
    assert "candidate map is high-recall working material, not a finding" in text
    assert "do exactly one" in text
    assert "Do not create\na detailed product catalogue" in text


def test_economic_smoke_plan_renders_saved_candidate_map_and_dry_run_does_not_call() -> None:
    packet = {
        "cik": "0000796343", "accession": "0000796343-22-000032", "packet_sha256": "a" * 64,
        "baseline_cutoff": "2022-01-01", "passages": [{"passage_id": "one", "text": "One."}],
    }
    packets = {("0000796343", "0000796343-22-000032"): packet}
    discoveries = {("0000796343", "0000796343-22-000032"): DISCOVERY}
    plan_from_partial_discovery = build_economic_pct_plan(
        prompt_text="Prompt", packets_by_key=packets, discoveries_by_key=discoveries
    )
    assert len(plan_from_partial_discovery) == 1
    assert "Discovery candidate map" in plan_from_partial_discovery[0]["rendered_prompt"]

    plan = [{"issuer_name": "Example", "cik": "1", "accession": "a", "packet_sha256": "a" * 64, "rendered_prompt": "x", "rendered_prompt_sha256": "b" * 64}] * 5
    result = run_economic_pct_smoke(plan=plan, packets_by_key={}, discoveries_by_key={}, output_root=ROOT / "unused", run_id="dry", prompt_sha256="a" * 64, schema_sha256="b" * 64, discovery_records_sha256="c" * 64, generate=None, model={}, clock=lambda: None, dry_run=True)
    assert result["run_dir"] is None


def test_economic_smoke_module_has_a_cli_entrypoint() -> None:
    source = (ROOT / "src/dynamic_ai_products/pct_economic_pct_smoke.py").read_text()
    assert 'if __name__ == "__main__"' in source
