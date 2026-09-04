"""Validate capabilities while preserving a fixed economic-product map."""

from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator

from .human_review_overlay import passage_refs
from .pct_combined_snapshot import CombinedSnapshotFailure

OUTPUT_CONTRACT = "pct_item1_capability_extraction_output@0.1.0"
OUTPUT_SCHEMA = "schemas/pct_item1_capability_extraction_output.v1.schema.json"


def validate_capability_extraction_output(
    raw: str, packet: dict[str, Any], economic_products: dict[str, Any], validator: Draft202012Validator
) -> dict[str, Any]:
    """Return the fixed product map enriched with product-local capabilities."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CombinedSnapshotFailure("invalid_model_json", str(exc)) from exc
    errors = sorted(validator.iter_errors(parsed), key=lambda error: error.json_path)
    if errors:
        raise CombinedSnapshotFailure("snapshot_contract_violation", errors[0].message)
    fixed = {product["id"]: product for product in economic_products["economic_products"]}
    groups = parsed["economic_product_capabilities"]
    group_ids = [group["economic_product_id"] for group in groups]
    if len(group_ids) != len(set(group_ids)) or set(group_ids) != set(fixed):
        raise CombinedSnapshotFailure("economic_product_partition_violation", "Every fixed economic product must appear exactly once.")
    available_refs = set(passage_refs(packet))
    enriched: list[dict[str, Any]] = []
    for group in groups:
        capabilities = group["capabilities"]
        ids = [capability["id"] for capability in capabilities]
        if len(ids) != len(set(ids)):
            raise CombinedSnapshotFailure("duplicate_local_id", f"{group['economic_product_id']} repeats a capability ID.")
        if any(reference not in available_refs for capability in capabilities for reference in capability["passage_refs"]):
            raise CombinedSnapshotFailure("evidence_reference_unresolvable", f"{group['economic_product_id']} names an absent P reference.")
        enriched.append({**fixed[group["economic_product_id"]], "capabilities": capabilities})
    return {"economic_products": enriched}
