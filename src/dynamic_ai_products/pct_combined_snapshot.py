"""Validate the development-only combined Item 1 PCT snapshot response.

This module deliberately reuses the classifier packet's displayed ``P001``
mapping.  It neither selects nor re-segments Item 1 text: a reference is
resolved only against the complete packet that was rendered to the model.
"""

from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator

from .human_review_overlay import passage_refs

OUTPUT_CONTRACT = "pct_item1_combined_snapshot_output@0.1.0"
OUTPUT_SCHEMA = "schemas/pct_item1_combined_snapshot_output.v1.schema.json"
OUTPUT_CONTRACT_V2 = "pct_item1_combined_snapshot_output@0.2.0"
OUTPUT_SCHEMA_V2 = "schemas/pct_item1_combined_snapshot_output.v2.schema.json"
OUTPUT_CONTRACT_V3 = "pct_item1_combined_snapshot_output@0.3.0"
OUTPUT_SCHEMA_V3 = "schemas/pct_item1_combined_snapshot_output.v3.schema.json"
OUTPUT_CONTRACT_V4 = "pct_item1_combined_snapshot_output@0.4.0"
OUTPUT_SCHEMA_V4 = "schemas/pct_item1_combined_snapshot_output.v4.schema.json"


class CombinedSnapshotFailure(ValueError):
    """A model output is not a valid, resolvable combined snapshot."""

    def __init__(self, reason_code: str, detail: str):
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(detail)


def _require_unique_ids(entries: list[dict[str, Any]], *, kind: str) -> set[str]:
    ids = [entry["id"] for entry in entries]
    if len(ids) != len(set(ids)):
        raise CombinedSnapshotFailure(
            "duplicate_local_id", f"{kind} contains a duplicate local identifier."
        )
    return set(ids)


def _require_resolvable_refs(entry: dict[str, Any], *, label: str,
                             refs: dict[str, str]) -> None:
    missing = [ref for ref in entry["passage_refs"] if ref not in refs]
    if missing:
        raise CombinedSnapshotFailure(
            "evidence_reference_unresolvable",
            f"{label} names passage references absent from the displayed packet: {missing}."
        )


def _validate_snapshot(
    raw: str, packet: dict[str, Any], validator: Draft202012Validator, *,
    contract: str, task_key: str, family_key: str | None = None,
) -> dict[str, Any]:
    """Parse one contract version and verify its local relationships."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CombinedSnapshotFailure(
            "invalid_model_json", f"Model output is not valid JSON: {exc}."
        ) from exc
    if not isinstance(parsed, dict):
        raise CombinedSnapshotFailure(
            "invalid_model_json", "Model output is JSON but not an object."
        )
    errors = sorted(validator.iter_errors(parsed), key=lambda error: error.json_path)
    if errors:
        raise CombinedSnapshotFailure(
            "snapshot_contract_violation",
            f"Model output violates {contract} at {errors[0].json_path}: "
            f"{errors[0].message}",
        )

    products = _require_unique_ids(parsed["products"], kind="products")
    capabilities = _require_unique_ids(parsed["capabilities"], kind="capabilities")
    capability_products = {
        entry["id"]: entry["product_id"] for entry in parsed["capabilities"]
    }
    _require_unique_ids(parsed[task_key], kind=task_key)
    families = (
        _require_unique_ids(parsed[family_key], kind=family_key)
        if family_key is not None else set()
    )
    refs = passage_refs(packet)

    for entry in parsed["products"]:
        if family_key is not None and (
            entry["product_family_id"] is not None
            and entry["product_family_id"] not in families
        ):
            raise CombinedSnapshotFailure(
                "dangling_product_family_reference",
                f"{entry['id']} names absent product family "
                f"{entry['product_family_id']!r}.",
            )
        _require_resolvable_refs(entry, label=entry["id"], refs=refs)
    if family_key is not None:
        for entry in parsed[family_key]:
            _require_resolvable_refs(entry, label=entry["id"], refs=refs)
    for entry in parsed["capabilities"]:
        if entry["product_id"] not in products:
            raise CombinedSnapshotFailure(
                "dangling_product_reference",
                f"{entry['id']} names absent product {entry['product_id']!r}.",
            )
        _require_resolvable_refs(entry, label=entry["id"], refs=refs)
    for entry in parsed[task_key]:
        if entry["product_id"] not in products:
            raise CombinedSnapshotFailure(
                "dangling_product_reference",
                f"{entry['id']} names absent product {entry['product_id']!r}.",
            )
        missing_capabilities = [
            capability_id for capability_id in entry["capability_ids"]
            if capability_id not in capabilities
        ]
        if missing_capabilities:
            raise CombinedSnapshotFailure(
                "dangling_capability_reference",
                f"{entry['id']} names absent capabilities {missing_capabilities}.",
            )
        wrong_product = [
            capability_id for capability_id in entry["capability_ids"]
            if capability_products[capability_id] != entry["product_id"]
        ]
        if wrong_product:
            raise CombinedSnapshotFailure(
                "cross_product_capability_reference",
                f"{entry['id']} links capabilities from a different product: "
                f"{wrong_product}.",
            )
        _require_resolvable_refs(entry, label=entry["id"], refs=refs)
    return parsed


def validate_combined_snapshot_output(
    raw: str, packet: dict[str, Any], validator: Draft202012Validator
) -> dict[str, Any]:
    """Validate the original product-capability-task smoke contract.

    It intentionally performs no reference repair: ``P01`` is not silently
    rewritten to ``P001`` on this P001-rendered route.
    """
    return _validate_snapshot(
        raw, packet, validator, contract=OUTPUT_CONTRACT, task_key="tasks"
    )


def validate_combined_snapshot_output_v2(
    raw: str, packet: dict[str, Any], validator: Draft202012Validator
) -> dict[str, Any]:
    """Validate the compact product-capability-task-family smoke contract."""
    return _validate_snapshot(
        raw, packet, validator, contract=OUTPUT_CONTRACT_V2,
        task_key="task_families",
    )


def validate_combined_snapshot_output_v3(
    raw: str, packet: dict[str, Any], validator: Draft202012Validator
) -> dict[str, Any]:
    """Validate the explicit product-family-product-capability-task smoke contract."""
    return _validate_snapshot(
        raw, packet, validator, contract=OUTPUT_CONTRACT_V3, task_key="tasks",
        family_key="product_families",
    )


def validate_combined_snapshot_output_v4(
    raw: str, packet: dict[str, Any], validator: Draft202012Validator
) -> dict[str, Any]:
    """Validate the explicit-family task-family smoke contract."""
    return _validate_snapshot(
        raw, packet, validator, contract=OUTPUT_CONTRACT_V4,
        task_key="task_families", family_key="product_families",
    )
