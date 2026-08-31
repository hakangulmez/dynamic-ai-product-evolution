"""Deterministic 100-row partition of the annual-coverage cohort.

This module deliberately performs no classification.  It freezes the exact
population and order for a future governed product-gate execution, so an
interrupted batch can be retried without reselecting firms or silently moving
rows between batches.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .classifier_annual_coverage_cohort import (
    COVERAGE_EXCLUSIONS_FILENAME,
    COVERAGE_MANIFEST_CONTRACT,
    COVERAGE_MANIFEST_FILENAME,
    COVERAGE_RECORDS_FILENAME,
    require_annual_coverage_cohort,
)
from .provenance import WriteOnceError, write_bytes_once
from .universe.lineage_screen import (
    ScreenInputError,
    _decode_utf8,
    _load_schema,
    _sha256,
)

__all__ = [
    "BATCH_PLAN_CONTRACT",
    "BATCH_PLAN_FILENAME",
    "BATCH_PLAN_SCHEMA",
    "BATCH_SIZE",
    "SELECTION_KIND",
    "build_product_gate_batch_plan",
    "require_product_gate_batch_plan",
]

BATCH_SIZE = 100
BATCH_PLAN_CONTRACT = "universe_classifier_product_gate_batch_plan@0.1.0"
BATCH_PLAN_SCHEMA = "schemas/universe_classifier_product_gate_batch_plan.v1.schema.json"
BATCH_PLAN_FILENAME = "universe_classifier_product_gate_batch_plan.json"
SELECTION_KIND = "classifier_product_gate_batch_plan_v1"


def _validate(value: dict[str, Any], schema: dict[str, Any], what: str) -> None:
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: str(error.json_path),
    )
    if errors:
        raise ScreenInputError(
            f"{what} violates its contract at {errors[0].json_path}: "
            f"{errors[0].message}")


def _read_pinned(path: Path, expected: str, what: str) -> bytes:
    if not path.is_file():
        raise ScreenInputError(f"{what} not found: {path}")
    raw = path.read_bytes()
    if _sha256(raw) != expected:
        raise ScreenInputError(f"{what} no longer hashes to its pinned digest.")
    return raw


def _plan_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy only execution-relevant, audit-only coverage fields in source order."""
    return [{
        "cik": row["cik"],
        "accession": row["accession"],
        "company_id": row["company_id"],
        "source_id": row["source_id"],
        "packet_sha256": row["packet_sha256"],
        "admission_origin": row["admission_origin"],
        "screen_status": row["screen_status"],
        "admission_provenance": dict(row["admission_provenance"]),
        "coverage_class": row["coverage_class"],
        "observed_annual_filing_years": list(row["observed_annual_filing_years"]),
    } for row in rows]


def build_product_gate_batch_plan(
    *, repo_root: str | Path, coverage_manifest_path: str | Path,
    coverage_manifest_sha256: str, output_path: str | Path,
    batch_plan_id: str, clock: Callable[[], datetime], dry_run: bool = False,
) -> dict[str, Any]:
    """Build one write-once plan covering every included coverage row exactly once."""
    root = Path(repo_root)
    manifest_path = Path(coverage_manifest_path)
    if manifest_path.name != COVERAGE_MANIFEST_FILENAME:
        raise ScreenInputError("The annual coverage manifest has the wrong filename.")
    manifest_raw = _read_pinned(
        manifest_path, coverage_manifest_sha256, "Annual coverage manifest")
    require_annual_coverage_cohort(manifest_path.parent)
    coverage = json.loads(_decode_utf8(manifest_raw, COVERAGE_MANIFEST_FILENAME))
    if coverage.get("manifest_contract") != COVERAGE_MANIFEST_CONTRACT:
        raise ScreenInputError("The presented artifact is not an annual coverage cohort.")
    if not (coverage.get("no_model_call") is True
            and coverage.get("is_software_universe") is False
            and coverage.get("is_classifier_output") is False
            and coverage.get("applied_after_high_recall_screen") is True):
        raise ScreenInputError("The coverage cohort does not carry the required ADR-138 identity.")

    records_raw = _read_pinned(
        manifest_path.parent / COVERAGE_RECORDS_FILENAME,
        coverage["output_hashes"][COVERAGE_RECORDS_FILENAME],
        "Annual coverage records")
    # Force the exclusion hash to be checked too: a plan should not pretend it
    # knows the complete source partition if its dropped complement drifted.
    _read_pinned(
        manifest_path.parent / COVERAGE_EXCLUSIONS_FILENAME,
        coverage["output_hashes"][COVERAGE_EXCLUSIONS_FILENAME],
        "Annual coverage exclusions")
    rows = [json.loads(line) for line in _decode_utf8(
        records_raw, COVERAGE_RECORDS_FILENAME).splitlines() if line.strip()]
    if len(rows) != coverage["counts"]["included"]:
        raise ScreenInputError("Coverage records disagree with their manifest count.")
    keys = [(row["cik"], row["accession"]) for row in rows]
    if len(set(keys)) != len(keys):
        raise ScreenInputError("Coverage records contain a duplicate filing identity.")

    batches: list[dict[str, Any]] = []
    for start in range(0, len(rows), BATCH_SIZE):
        selected = _plan_rows(rows[start:start + BATCH_SIZE])
        ordinal = len(batches) + 1
        batches.append({
            "batch_id": f"batch-{ordinal:04d}",
            "batch_ordinal": ordinal,
            "first_row_ordinal": start + 1,
            "last_row_ordinal": start + len(selected),
            "rows": selected,
        })

    planned_keys = [
        (row["cik"], row["accession"])
        for batch in batches for row in batch["rows"]]
    plan = {
        "batch_plan_contract": BATCH_PLAN_CONTRACT,
        "batch_plan_id": batch_plan_id,
        "selection_kind": SELECTION_KIND,
        "batch_size": BATCH_SIZE,
        "coverage_cohort": {
            "coverage_cohort_id": coverage["coverage_cohort_id"],
            "manifest_path": str(manifest_path),
            "manifest_sha256": coverage_manifest_sha256,
            "records_jsonl_sha256": _sha256(records_raw),
            "included_rows": len(rows),
        },
        "batches": batches,
        "counts": {
            "selected_rows": len(rows),
            "batch_count": len(batches),
            "full_batches": len(rows) // BATCH_SIZE,
            "final_batch_rows": len(batches[-1]["rows"]),
        },
        "no_model_call": True,
        "is_software_universe": False,
        "is_classifier_output": False,
        "covers_full_coverage_cohort": True,
        "reconciliation": {
            "every included coverage row is selected exactly once": (
                planned_keys == keys and len(set(planned_keys)) == len(planned_keys)),
            "batch boundaries are contiguous in coverage-record order": all(
                batch["first_row_ordinal"] == (
                    1 if index == 0 else batches[index - 1]["last_row_ordinal"] + 1)
                and batch["last_row_ordinal"]
                == batch["first_row_ordinal"] + len(batch["rows"]) - 1
                for index, batch in enumerate(batches)),
            "only the final batch may be short": all(
                len(batch["rows"]) == BATCH_SIZE
                for batch in batches[:-1]),
            "the plan is bound to the pinned annual coverage cohort": (
                _sha256(manifest_raw) == coverage_manifest_sha256
                and _sha256(records_raw)
                == coverage["output_hashes"][COVERAGE_RECORDS_FILENAME]),
        },
        "run_timestamp": clock().isoformat(),
        "limitations": [
            "This is a model-free execution plan, not a software universe and not a classifier output.",
            "Batching bounds operational interruption loss; it does not create a right to make model calls.",
            "Every batch still requires its own authorization, and a later aggregate may accept only a complete, disjoint set of verified batch manifests.",
            "The plan inherits annual-coverage survivor conditioning and must not be read as a software-membership filter.",
        ],
    }
    _validate(plan, _load_schema(root, BATCH_PLAN_SCHEMA), "Product-gate batch plan")
    if dry_run:
        return plan
    try:
        write_bytes_once(
            Path(output_path),
            (json.dumps(plan, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            what="product-gate batch plan")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    return plan


def require_product_gate_batch_plan(
    path: str | Path, *, expected_sha256: str, repo_root: str | Path,
) -> dict[str, Any]:
    """Load a pinned, schema-valid full-coverage batch plan and nothing else."""
    target = Path(path)
    if target.name != BATCH_PLAN_FILENAME:
        raise ScreenInputError(
            f"A product-gate batch plan must be {BATCH_PLAN_FILENAME}; this is a different artifact.")
    raw = _read_pinned(target, expected_sha256, "Product-gate batch plan")
    plan = json.loads(_decode_utf8(raw, BATCH_PLAN_FILENAME))
    if plan.get("batch_plan_contract") != BATCH_PLAN_CONTRACT:
        raise ScreenInputError("The artifact declares a different batch-plan contract.")
    _validate(plan, _load_schema(Path(repo_root), BATCH_PLAN_SCHEMA), "Product-gate batch plan")
    return plan
