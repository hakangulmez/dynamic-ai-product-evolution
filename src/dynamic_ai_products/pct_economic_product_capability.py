"""Validate Item 1 economic-product and capability output."""

from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator

from .human_review_overlay import passage_refs
from .pct_combined_snapshot import CombinedSnapshotFailure

OUTPUT_CONTRACT = "pct_item1_economic_product_capability_output@0.1.0"
OUTPUT_SCHEMA = "schemas/pct_item1_economic_product_capability_output.v1.schema.json"


def _unique(entries: list[dict[str, Any]], *, kind: str) -> set[str]:
    identifiers = [entry["id"] for entry in entries]
    if len(identifiers) != len(set(identifiers)):
        raise CombinedSnapshotFailure("duplicate_local_id", f"{kind} contains duplicate IDs.")
    return set(identifiers)


def _check_refs(entries: list[dict[str, Any]], refs: set[str]) -> None:
    for entry in entries:
        missing = [reference for reference in entry["passage_refs"] if reference not in refs]
        if missing:
            raise CombinedSnapshotFailure(
                "evidence_reference_unresolvable",
                f"{entry['id']} names absent references: {missing}.",
            )


def validate_economic_product_capability_output(
    raw: str,
    packet: dict[str, Any],
    discovery: dict[str, Any],
    validator: Draft202012Validator,
) -> dict[str, Any]:
    """Validate exact candidate accounting and product-local capabilities."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CombinedSnapshotFailure("invalid_model_json", str(exc)) from exc
    errors = sorted(validator.iter_errors(parsed), key=lambda error: error.json_path)
    if errors:
        raise CombinedSnapshotFailure("snapshot_contract_violation", errors[0].message)

    candidate_ids = {entry["id"] for entry in discovery["products"]}
    selected: list[str] = []
    _unique(parsed["economic_products"], kind="economic_products")
    refs = set(passage_refs(packet))
    for product in parsed["economic_products"]:
        selected.extend(product["source_product_ids"])
        _check_refs([product, *product["capabilities"]], refs)
        _unique(product["capabilities"], kind=f"{product['id']} capabilities")
    if len(selected) != len(set(selected)):
        raise CombinedSnapshotFailure(
            "candidate_partition_violation", "A discovery product is selected more than once."
        )
    not_selected = parsed["not_selected_product_ids"]
    if set(selected) | set(not_selected) != candidate_ids or set(selected) & set(not_selected):
        raise CombinedSnapshotFailure(
            "candidate_partition_violation",
            "Every discovery product must be selected or not selected exactly once.",
        )
    return parsed
