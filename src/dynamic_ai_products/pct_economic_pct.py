"""Validate candidate-constrained economic PCT output for one Item 1 packet."""

from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator

from .human_review_overlay import passage_refs
from .pct_combined_snapshot import CombinedSnapshotFailure

OUTPUT_CONTRACT = "pct_item1_economic_pct_output@0.1.0"
OUTPUT_SCHEMA = "schemas/pct_item1_economic_pct_output.v1.schema.json"


def _require_unique(entries: list[dict[str, Any]], *, key: str, kind: str) -> set[str]:
    values = [entry[key] for entry in entries]
    if len(values) != len(set(values)):
        raise CombinedSnapshotFailure("duplicate_local_id", f"{kind} contains a duplicate ID.")
    return set(values)


def _require_resolvable_refs(entry: dict[str, Any], *, refs: set[str]) -> None:
    missing = [reference for reference in entry["passage_refs"] if reference not in refs]
    if missing:
        raise CombinedSnapshotFailure(
            "evidence_reference_unresolvable",
            f"{entry['id']} names absent passage references: {missing}.",
        )


def validate_economic_pct_output(
    raw: str,
    packet: dict[str, Any],
    discovery: dict[str, Any],
    validator: Draft202012Validator,
) -> dict[str, Any]:
    """Validate an exact partition of discovered products and PCT references."""
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

    candidate_ids = {entry["id"] for entry in discovery["products"]}
    selected: list[str] = []
    economic_ids = _require_unique(parsed["economic_products"], key="id", kind="economic_products")
    refs = set(passage_refs(packet))
    for product in parsed["economic_products"]:
        selected.extend(product["source_product_ids"])
        _require_resolvable_refs(product, refs=refs)
        capability_ids = _require_unique(product["capabilities"], key="id", kind=product["id"] + " capabilities")
        task_ids = _require_unique(product["task_families"], key="id", kind=product["id"] + " task_families")
        if len(task_ids) != len(product["task_families"]):  # defensive, documented near uniqueness
            raise AssertionError("Task IDs must be unique.")
        for capability in product["capabilities"]:
            _require_resolvable_refs(capability, refs=refs)
        for task in product["task_families"]:
            _require_resolvable_refs(task, refs=refs)
            missing_capabilities = [
                identifier for identifier in task["capability_ids"] if identifier not in capability_ids
            ]
            if missing_capabilities:
                raise CombinedSnapshotFailure(
                    "dangling_capability_reference",
                    f"{task['id']} names absent capabilities: {missing_capabilities}.",
                )
    if len(selected) != len(set(selected)):
        raise CombinedSnapshotFailure(
            "candidate_partition_violation",
            "A discovery product is selected by more than one economic product.",
        )
    not_selected = parsed["not_selected_product_ids"]
    if set(selected) | set(not_selected) != candidate_ids or set(selected) & set(not_selected):
        raise CombinedSnapshotFailure(
            "candidate_partition_violation",
            "Every discovery product must appear exactly once as selected or not selected.",
        )
    unknown = (set(selected) | set(not_selected)) - candidate_ids
    if unknown:
        raise CombinedSnapshotFailure(
            "unknown_discovery_product_id",
            f"Output names candidate IDs not present in discovery: {sorted(unknown)}.",
        )
    if len(economic_ids) != len(parsed["economic_products"]):
        raise AssertionError("Economic product IDs must be unique.")
    return parsed
