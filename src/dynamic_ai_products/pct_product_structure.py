"""Validate the development-only Item 1 product-family/product map."""

from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator

from .human_review_overlay import passage_refs
from .pct_combined_snapshot import CombinedSnapshotFailure

OUTPUT_CONTRACT = "pct_item1_product_structure_output@0.1.0"
OUTPUT_SCHEMA = "schemas/pct_item1_product_structure_output.v1.schema.json"


def _drop_unlinked_families(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Keep only parents that organise at least one returned product.

    The raw model response remains archived by the caller.  This deterministic
    projection removes a named grouping that has no child product in the
    validated map; it never adds, renames, or reassigns a product.
    """
    linked_family_ids = {
        product["product_family_id"]
        for product in snapshot["products"]
        if product["product_family_id"] is not None
    }
    return {
        **snapshot,
        "product_families": [
            family
            for family in snapshot["product_families"]
            if family["id"] in linked_family_ids
        ],
    }


def validate_product_structure_output(
    raw: str, packet: dict[str, Any], validator: Draft202012Validator
) -> dict[str, Any]:
    """Validate local family/product links and displayed P001 addresses."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CombinedSnapshotFailure("invalid_model_json", str(exc)) from exc
    errors = sorted(validator.iter_errors(parsed), key=lambda error: error.json_path)
    if errors:
        raise CombinedSnapshotFailure(
            "snapshot_contract_violation",
            f"Model output violates {OUTPUT_CONTRACT} at {errors[0].json_path}: "
            f"{errors[0].message}",
        )
    families = [entry["id"] for entry in parsed["product_families"]]
    products = [entry["id"] for entry in parsed["products"]]
    if len(families) != len(set(families)) or len(products) != len(set(products)):
        raise CombinedSnapshotFailure("duplicate_local_id", "Family or product IDs repeat.")
    refs = passage_refs(packet)
    for entry in [*parsed["product_families"], *parsed["products"]]:
        missing = [ref for ref in entry["passage_refs"] if ref not in refs]
        if missing:
            raise CombinedSnapshotFailure(
                "evidence_reference_unresolvable",
                f"{entry['id']} names absent passage references: {missing}.",
            )
    for product in parsed["products"]:
        family_id = product["product_family_id"]
        if family_id is not None and family_id not in families:
            raise CombinedSnapshotFailure(
                "dangling_product_family_reference",
                f"{product['id']} names absent product family {family_id!r}.",
            )
    return _drop_unlinked_families(parsed)
