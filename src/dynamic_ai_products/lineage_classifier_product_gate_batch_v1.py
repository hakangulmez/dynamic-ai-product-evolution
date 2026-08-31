"""Governed execution route for one 100-row product-gate batch.

The route consumes a hash-bound batch plan and one named batch from it.  It is
deliberately non-promotable: a complete software universe can be produced only
by a later aggregate that verifies all planned batches, without overlap.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .classifier_annual_coverage_cohort import COVERAGE_MANIFEST_FILENAME, require_annual_coverage_cohort
from .classifier_product_gate_batch_plan import BATCH_PLAN_CONTRACT, SELECTION_KIND, require_product_gate_batch_plan
from .classifier_pilot_v3 import PILOT_V3_AXES, PILOT_V3_AXES_CONTRACT, PILOT_V3_AXES_SCHEMA, PILOT_V3_RECORD_CONTRACT, PILOT_V3_RECORD_SCHEMA, build_pilot_v3_record
from .lineage_classifier_pilot_v1 import PilotRunRoute, _require_pilot_run, _run_lineage_classifier_pilot
from .universe.lineage_screen import ScreenInputError, ScreenRunResult, _decode_utf8, _sha256

__all__ = ["PRODUCT_GATE_BATCH_ROUTE", "require_product_gate_batch_run", "run_product_gate_batch"]


def _load_batch_plan(path: Path, digest: str, root: Path, authorization: dict) -> dict:
    plan = require_product_gate_batch_plan(path, expected_sha256=digest, repo_root=root)
    if plan["batch_plan_contract"] != BATCH_PLAN_CONTRACT:
        raise ScreenInputError("The batch plan declares a different contract.")
    coverage_source = plan["coverage_cohort"]
    if (coverage_source["coverage_cohort_id"] != authorization["coverage_cohort_id"]
            or coverage_source["manifest_sha256"] != authorization["coverage_cohort_manifest_sha256"]
            or coverage_source["records_jsonl_sha256"] != authorization["coverage_cohort_records_sha256"]):
        raise ScreenInputError("Authorization and batch plan bind different coverage cohorts.")
    coverage_path = Path(coverage_source["manifest_path"])
    if coverage_path.name != COVERAGE_MANIFEST_FILENAME or not coverage_path.is_file():
        raise ScreenInputError("The batch plan's annual coverage manifest is unavailable.")
    if _sha256(coverage_path.read_bytes()) != coverage_source["manifest_sha256"]:
        raise ScreenInputError("The batch plan's annual coverage manifest drifted.")
    require_annual_coverage_cohort(coverage_path.parent)
    coverage = json.loads(_decode_utf8(coverage_path.read_bytes(), COVERAGE_MANIFEST_FILENAME))
    candidate = coverage["sources"]["candidate_cohort"]
    matches = [batch for batch in plan["batches"]
               if batch["batch_id"] == authorization["batch_id"]]
    if len(matches) != 1:
        raise ScreenInputError("Authorization names no unique batch in the batch plan.")
    batch = matches[0]
    if authorization["logical_row_cap"] != len(batch["rows"]):
        raise ScreenInputError("Authorization does not state this batch's exact row count.")
    return {
        "selection_id": f"{plan['batch_plan_id']}:{batch['batch_id']}",
        "selection_kind": SELECTION_KIND,
        "batch_plan_id": plan["batch_plan_id"], "batch_id": batch["batch_id"],
        "batch_ordinal": batch["batch_ordinal"], "rows": [dict(row) for row in batch["rows"]],
        "candidate_cohort_id": candidate["cohort_id"],
        "candidate_cohort_manifest_sha256": candidate["manifest_sha256"],
        "coverage_cohort_id": coverage_source["coverage_cohort_id"],
        "coverage_cohort_manifest_sha256": coverage_source["manifest_sha256"],
        "coverage_cohort_records_sha256": coverage_source["records_jsonl_sha256"],
    }


PRODUCT_GATE_BATCH_ROUTE = PilotRunRoute(
    run_kind="classifier_product_gate_batch_v1",
    records_filename="universe_classifier_product_gate_batch_records.jsonl",
    manifest_filename="universe_classifier_product_gate_batch_manifest.json",
    raw_responses_filename="universe_classifier_product_gate_batch_raw_responses.jsonl",
    manifest_contract="universe_classifier_product_gate_batch_manifest@0.1.0",
    manifest_schema="schemas/universe_classifier_product_gate_batch_manifest.v1.schema.json",
    authorization_contract="universe_classifier_product_gate_batch_authorization@0.1.0",
    authorization_schema="schemas/universe_classifier_product_gate_batch_authorization.v1.schema.json",
    run_root_name="universe-classifier-product-gate-batch-runs",
    selection_contract=BATCH_PLAN_CONTRACT, selection_kind=SELECTION_KIND,
    selection_source="batch_plan", load_selection=_load_batch_plan,
    prompt_path="prompts/discovery/software_universe_classifier_pilot.v4.md",
    axes_schema=PILOT_V3_AXES_SCHEMA, axes_contract=PILOT_V3_AXES_CONTRACT,
    record_schema=PILOT_V3_RECORD_SCHEMA, record_contract=PILOT_V3_RECORD_CONTRACT,
    judgement_axes=PILOT_V3_AXES, build_record=build_pilot_v3_record,
    scope_min_rows=1, scope_max_rows=100, scope_exact_rows=None,
    record_order="batch_plan_row_order", selection_group_field=None,
    selection_group_count_name=None, scope_noun="product-gate batch",
)


def run_product_gate_batch(
    *, repo_root: str | Path, cohort_manifest_path: str | Path,
    coverage_manifest_path: str | Path, packet_manifest_path: str | Path,
    batch_plan_path: str | Path, governance_root: str | Path,
    authorization_reference: str, authorization_sha256: str,
    output_dir: str | Path, run_id: str, clock: Callable[[], datetime],
    dry_run: bool = False, client_factory: Any = None,
    sleep: Callable[[float], None] | None = None,
) -> ScreenRunResult:
    return _run_lineage_classifier_pilot(
        route=PRODUCT_GATE_BATCH_ROUTE, repo_root=repo_root,
        cohort_manifest_path=cohort_manifest_path,
        coverage_manifest_path=coverage_manifest_path,
        packet_manifest_path=packet_manifest_path, selection_path=batch_plan_path,
        governance_root=governance_root,
        authorization_reference=authorization_reference,
        authorization_sha256=authorization_sha256, output_dir=output_dir,
        run_id=run_id, clock=clock, dry_run=dry_run,
        client_factory=client_factory, sleep=sleep)


def require_product_gate_batch_run(run_dir: str | Path) -> Path:
    return _require_pilot_run(run_dir, route=PRODUCT_GATE_BATCH_ROUTE)
