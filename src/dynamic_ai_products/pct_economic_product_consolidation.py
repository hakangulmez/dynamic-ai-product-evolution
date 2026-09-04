"""Validate Item 1 economic-product consolidation over discovery candidates."""

from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator

from .human_review_overlay import passage_refs
from .pct_combined_snapshot import CombinedSnapshotFailure

OUTPUT_CONTRACT = "pct_item1_economic_product_consolidation_output@0.1.0"
OUTPUT_SCHEMA = "schemas/pct_item1_economic_product_consolidation_output.v1.schema.json"


def validate_economic_product_consolidation_output(
    raw: str, packet: dict[str, Any], discovery: dict[str, Any], validator: Draft202012Validator
) -> dict[str, Any]:
    """Require an evidence-resolved exact partition of discovery candidates."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CombinedSnapshotFailure("invalid_model_json", str(exc)) from exc
    errors = sorted(validator.iter_errors(parsed), key=lambda error: error.json_path)
    if errors:
        raise CombinedSnapshotFailure("snapshot_contract_violation", errors[0].message)
    products = parsed["economic_products"]
    ids = [product["id"] for product in products]
    if len(ids) != len(set(ids)):
        raise CombinedSnapshotFailure("duplicate_local_id", "Economic product IDs repeat.")
    available_refs = set(passage_refs(packet))
    selected: list[str] = []
    for product in products:
        if not all(reference in available_refs for reference in product["passage_refs"]):
            raise CombinedSnapshotFailure("evidence_reference_unresolvable", f"{product['id']} names an absent P reference.")
        selected.extend(product["source_product_ids"])
    candidate_ids = {product["id"] for product in discovery["products"]}
    unselected = parsed["not_selected_product_ids"]
    if len(selected) != len(set(selected)) or set(selected) & set(unselected) or set(selected) | set(unselected) != candidate_ids:
        raise CombinedSnapshotFailure("candidate_partition_violation", "Every discovery product must be selected or not selected exactly once.")
    return parsed
