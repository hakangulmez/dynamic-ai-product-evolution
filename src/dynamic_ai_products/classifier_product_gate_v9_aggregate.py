"""Fail-closed aggregate for every governed V9 product-gate batch."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from .classifier_product_gate_batch_plan import require_product_gate_batch_plan
from .lineage_classifier_product_gate_batch_v3 import (
    PRODUCT_GATE_BATCH_V3_ROUTE,
    require_product_gate_batch_run_v3,
)
from .provenance import WriteOnceError, write_bytes_once
from .universe.freeze import create_run_directory
from .universe.lineage_screen import (
    ScreenInputError,
    _canonical_line,
    _load_schema,
    _sha256,
    _validate,
)

__all__ = [
    "AGGREGATE_CONTRACT",
    "AGGREGATE_MANIFEST_FILENAME",
    "AGGREGATE_MANIFEST_SCHEMA",
    "AGGREGATE_RECORD_SCHEMA",
    "CORE_FILENAME",
    "CANDIDATES_FILENAME",
    "UNRESOLVED_FILENAME",
    "build_product_gate_v9_aggregate",
    "require_product_gate_v9_aggregate",
]

AGGREGATE_CONTRACT = "universe_classifier_product_gate_v9_aggregate_manifest@0.1.0"
AGGREGATE_MANIFEST_FILENAME = "universe_classifier_product_gate_v9_aggregate_manifest.json"
AGGREGATE_MANIFEST_SCHEMA = "schemas/universe_classifier_product_gate_v9_aggregate_manifest.v1.schema.json"
AGGREGATE_RECORD_SCHEMA = "schemas/universe_classifier_product_gate_v9_aggregate_record.v1.schema.json"
CANDIDATES_FILENAME = "universe_classifier_product_gate_v9_software_candidates.jsonl"
CORE_FILENAME = "universe_classifier_product_gate_v9_core_software.jsonl"
UNRESOLVED_FILENAME = "universe_classifier_product_gate_v9_unresolved.jsonl"
_V9_PROMPT = "prompts/discovery/software_universe_classifier_pilot.v9.md"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ScreenInputError(f"Aggregate input is missing: {path}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _aggregate_row(record: dict[str, Any], *, role: str, batch_id: str, run_id: str) -> dict[str, Any]:
    return {
        "aggregate_role": role,
        "cik": record["cik"],
        "accession": record["accession"],
        "source_batch_id": batch_id,
        "source_run_id": run_id,
        "source_record_sha256": _sha256((_canonical_line(record) + "\n").encode("utf-8")),
        "record_kind": record["record_kind"],
        "axes": record["axes"],
        "review_reason_code": record["review_reason_code"],
    }


def _checked_batches(root: Path, plan: dict[str, Any], run_dirs: Iterable[str | Path]) -> list[tuple[dict[str, Any], dict[str, Any], Path, list[dict[str, Any]]]]:
    expected = {batch["batch_id"]: batch for batch in plan["batches"]}
    loaded: dict[str, tuple[dict[str, Any], dict[str, Any], Path, list[dict[str, Any]]]] = {}
    for supplied in run_dirs:
        directory = Path(supplied)
        manifest_path = require_product_gate_batch_run_v3(directory)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _validate(
            manifest,
            _load_schema(root, PRODUCT_GATE_BATCH_V3_ROUTE.manifest_schema),
            "V9 batch manifest",
        )
        selection = manifest["sources"]["selection"]
        batch_id = selection["batch_id"]
        if batch_id not in expected or batch_id in loaded:
            raise ScreenInputError("Aggregate inputs do not name each planned V9 batch exactly once.")
        batch = expected[batch_id]
        if selection["batch_plan_id"] != plan["batch_plan_id"]:
            raise ScreenInputError("A batch manifest names a different batch plan.")
        if selection["batch_ordinal"] != batch["batch_ordinal"]:
            raise ScreenInputError("A batch manifest has the wrong plan ordinal.")
        if manifest["prompt_template_path"] != _V9_PROMPT:
            raise ScreenInputError("A batch did not run the frozen V9 prompt.")
        if manifest["prompt_template_sha256"] != _sha256((root / _V9_PROMPT).read_bytes()):
            raise ScreenInputError("A batch does not hash to the frozen V9 prompt.")
        records_path = directory / PRODUCT_GATE_BATCH_V3_ROUTE.records_filename
        records_raw = records_path.read_bytes()
        if _sha256(records_raw) != manifest["output_hashes"][PRODUCT_GATE_BATCH_V3_ROUTE.records_filename]:
            raise ScreenInputError("A batch records file no longer matches its manifest.")
        records = _read_jsonl(records_path)
        record_schema = _load_schema(root, PRODUCT_GATE_BATCH_V3_ROUTE.record_schema)
        for record in records:
            _validate(record, record_schema, "V9 batch record")
        planned_keys = [(row["cik"], row["accession"]) for row in batch["rows"]]
        if [(row["cik"], row["accession"]) for row in records] != planned_keys:
            raise ScreenInputError("A batch records order does not match its planned filing order.")
        loaded[batch_id] = (batch, manifest, directory, records)
    if set(loaded) != set(expected):
        raise ScreenInputError("Cannot aggregate until every planned V9 batch is present exactly once.")
    return [loaded[batch["batch_id"]] for batch in plan["batches"]]


def build_product_gate_v9_aggregate(
    *, repo_root: str | Path, batch_plan_path: str | Path, batch_plan_sha256: str,
    batch_run_dirs: Iterable[str | Path], output_dir: str | Path, aggregate_id: str,
    clock: Callable[[], datetime], dry_run: bool = False,
) -> dict[str, Any]:
    """Aggregate all and only the complete V9 batch-plan population."""
    root = Path(repo_root)
    plan_path = Path(batch_plan_path)
    plan = require_product_gate_batch_plan(plan_path, expected_sha256=batch_plan_sha256, repo_root=root)
    batches = _checked_batches(root, plan, batch_run_dirs)
    candidates: list[dict[str, Any]] = []
    core: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    all_records: list[dict[str, Any]] = []
    batch_runs: list[dict[str, Any]] = []
    for batch, manifest, directory, records in batches:
        all_records.extend(records)
        for record in records:
            if record["record_kind"] == "review_uncertain":
                unresolved.append(_aggregate_row(record, role="unresolved", batch_id=batch["batch_id"], run_id=manifest["run_id"]))
                continue
            axes = record["axes"]
            if axes["customer_facing_digital_product"] == "YES":
                candidates.append(_aggregate_row(record, role="software_candidate", batch_id=batch["batch_id"], run_id=manifest["run_id"]))
            if axes["software_centrality"] == "CORE":
                core.append(_aggregate_row(record, role="core_software", batch_id=batch["batch_id"], run_id=manifest["run_id"]))
        manifest_path = directory / PRODUCT_GATE_BATCH_V3_ROUTE.manifest_filename
        records_path = directory / PRODUCT_GATE_BATCH_V3_ROUTE.records_filename
        batch_runs.append({
            "batch_id": batch["batch_id"], "batch_ordinal": batch["batch_ordinal"],
            "run_id": manifest["run_id"], "run_dir": str(directory),
            "manifest_sha256": _sha256(manifest_path.read_bytes()),
            "records_sha256": _sha256(records_path.read_bytes()),
        })
    planned = [key for batch in plan["batches"] for key in [(r["cik"], r["accession"]) for r in batch["rows"]]]
    classified = [row for row in all_records if row["record_kind"] == "classified"]
    payloads = {
        CANDIDATES_FILENAME: "".join(_canonical_line(row) + "\n" for row in candidates).encode("utf-8"),
        CORE_FILENAME: "".join(_canonical_line(row) + "\n" for row in core).encode("utf-8"),
        UNRESOLVED_FILENAME: "".join(_canonical_line(row) + "\n" for row in unresolved).encode("utf-8"),
    }
    record_schema = _load_schema(root, AGGREGATE_RECORD_SCHEMA)
    for row in [*candidates, *core, *unresolved]:
        _validate(row, record_schema, "V9 aggregate record")
    manifest = {
        "aggregate_contract": AGGREGATE_CONTRACT,
        "aggregate_id": aggregate_id,
        "run_timestamp": clock().isoformat(),
        "prompt_template_path": _V9_PROMPT,
        "prompt_template_sha256": _sha256((root / _V9_PROMPT).read_bytes()),
        "batch_plan_path": str(plan_path),
        "batch_plan_sha256": batch_plan_sha256,
        "coverage_cohort_id": plan["coverage_cohort"]["coverage_cohort_id"],
        "coverage_cohort_manifest_sha256": plan["coverage_cohort"]["manifest_sha256"],
        "batch_runs": batch_runs,
        "output_hashes": {name: _sha256(raw) for name, raw in payloads.items()},
        "counts": {
            "planned_rows": len(planned), "classified_rows": len(classified),
            "review_uncertain_rows": len(unresolved), "software_candidate_rows": len(candidates),
            "core_software_rows": len(core),
            "no_or_unknown_rows": len(classified) - len(candidates),
        },
        "reconciliation": {
            "every planned filing appears once in the supplied records": [(r["cik"], r["accession"]) for r in all_records] == planned,
            "classified and unresolved records partition the planned population": len(classified) + len(unresolved) == len(planned),
            "CORE is a subset of the software-candidate output": {(r["cik"], r["accession"]) for r in core} <= {(r["cik"], r["accession"]) for r in candidates},
            "every output record points to one supplied batch run": all(r["source_batch_id"] in {b["batch_id"] for b in batch_runs} for r in [*candidates, *core, *unresolved]),
            "all planned batches are present in order": [b["batch_id"] for b in batch_runs] == [b["batch_id"] for b in plan["batches"]],
        },
        "promotable": False,
        "limitations": [
            "Software candidates and CORE rows are model-derived V9 outputs, not human-reviewed research membership decisions.",
            "Review-uncertain filings are retained separately and are not silently treated as NO.",
            "This artifact is valid only after every planned annual-coverage batch is present exactly once.",
        ],
    }
    _validate(manifest, _load_schema(root, AGGREGATE_MANIFEST_SCHEMA), "V9 aggregate manifest")
    if dry_run:
        return manifest
    run_dir = create_run_directory(output_dir, aggregate_id)
    try:
        for filename, raw in payloads.items():
            write_bytes_once(run_dir / filename, raw, what=f"V9 aggregate {filename}")
        write_bytes_once(run_dir / AGGREGATE_MANIFEST_FILENAME, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"), what="V9 aggregate manifest")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    return manifest


def require_product_gate_v9_aggregate(run_dir: str | Path, *, repo_root: str | Path) -> Path:
    """Load one self-consistent V9 full-coverage aggregate and nothing else."""
    directory = Path(run_dir)
    manifest_path = directory / AGGREGATE_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ScreenInputError("A V9 aggregate manifest is missing.")
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    if manifest.get("aggregate_contract") != AGGREGATE_CONTRACT:
        raise ScreenInputError("The aggregate declares a different contract.")
    _validate(manifest, _load_schema(Path(repo_root), AGGREGATE_MANIFEST_SCHEMA), "V9 aggregate manifest")
    prompt = Path(repo_root) / _V9_PROMPT
    if not prompt.is_file() or _sha256(prompt.read_bytes()) != manifest["prompt_template_sha256"]:
        raise ScreenInputError("The aggregate no longer hashes to the frozen V9 prompt.")
    for filename, digest in manifest["output_hashes"].items():
        path = directory / filename
        if not path.is_file() or _sha256(path.read_bytes()) != digest:
            raise ScreenInputError("An aggregate output is missing or no longer hashes to its manifest.")
    return manifest_path
