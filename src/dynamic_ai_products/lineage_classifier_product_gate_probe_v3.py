"""Governed execution route for the fixed five-filing CORE-definition wording probe."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .classifier_pilot_v3 import (
    PILOT_V3_AXES,
    PILOT_V3_AXES_CONTRACT,
    PILOT_V3_AXES_SCHEMA,
    PILOT_V3_RECORD_CONTRACT,
    PILOT_V3_RECORD_SCHEMA,
    build_pilot_v3_record,
)
from .classifier_product_gate_probe_selection import (
    PROBE_SELECTION_CONTRACT,
    PROBE_SELECTION_KIND,
    require_product_gate_probe_selection,
)
from .lineage_classifier_pilot_v1 import (
    PilotRunRoute,
    _require_pilot_run,
    _run_lineage_classifier_pilot,
)
from .universe.lineage_screen import ScreenInputError, ScreenRunResult

__all__ = [
    "PRODUCT_GATE_PROBE_V3_ROUTE",
    "require_product_gate_probe_run_v3",
    "run_product_gate_probe_v3",
]


def _load_probe_selection(path: Path, digest: str, root: Path, authorization: dict) -> dict:
    selection = require_product_gate_probe_selection(
        path, expected_sha256=digest, repo_root=root)
    for key in (
        "coverage_cohort_id",
        "coverage_cohort_manifest_sha256",
        "coverage_cohort_records_sha256",
    ):
        if selection[key] != authorization[key]:
            raise ScreenInputError("Authorization and probe selection bind different coverage inputs.")
    return selection


PRODUCT_GATE_PROBE_V3_ROUTE = PilotRunRoute(
    run_kind="classifier_product_gate_probe_v3",
    records_filename="universe_classifier_product_gate_probe_v3_records.jsonl",
    manifest_filename="universe_classifier_product_gate_probe_v3_manifest.json",
    raw_responses_filename="universe_classifier_product_gate_probe_v3_raw_responses.jsonl",
    manifest_contract="universe_classifier_product_gate_probe_manifest@0.3.0",
    manifest_schema="schemas/universe_classifier_product_gate_probe_manifest.v3.schema.json",
    authorization_contract="universe_classifier_product_gate_probe_authorization@0.3.0",
    authorization_schema="schemas/universe_classifier_product_gate_probe_authorization.v3.schema.json",
    run_root_name="universe-classifier-product-gate-probe-v3-runs",
    selection_contract=PROBE_SELECTION_CONTRACT,
    selection_kind=PROBE_SELECTION_KIND,
    selection_source="annual_coverage",
    load_selection=_load_probe_selection,
    prompt_path="prompts/discovery/software_universe_classifier_pilot.v9.md",
    axes_schema=PILOT_V3_AXES_SCHEMA,
    axes_contract=PILOT_V3_AXES_CONTRACT,
    record_schema=PILOT_V3_RECORD_SCHEMA,
    record_contract=PILOT_V3_RECORD_CONTRACT,
    judgement_axes=PILOT_V3_AXES,
    build_record=build_pilot_v3_record,
    scope_min_rows=5,
    scope_max_rows=5,
    scope_exact_rows=5,
    record_order="product_gate_probe_row_order",
    selection_group_field=None,
    selection_group_count_name=None,
    scope_noun="five-filing product-gate wording probe",
)


def run_product_gate_probe_v3(
    *, repo_root: str | Path, cohort_manifest_path: str | Path,
    coverage_manifest_path: str | Path, packet_manifest_path: str | Path,
    selection_path: str | Path, governance_root: str | Path,
    authorization_reference: str, authorization_sha256: str,
    output_dir: str | Path, run_id: str, clock: Callable[[], datetime],
    dry_run: bool = False, client_factory: Any = None,
    sleep: Callable[[float], None] | None = None,
) -> ScreenRunResult:
    return _run_lineage_classifier_pilot(
        route=PRODUCT_GATE_PROBE_V3_ROUTE,
        repo_root=repo_root,
        cohort_manifest_path=cohort_manifest_path,
        coverage_manifest_path=coverage_manifest_path,
        packet_manifest_path=packet_manifest_path,
        selection_path=selection_path,
        governance_root=governance_root,
        authorization_reference=authorization_reference,
        authorization_sha256=authorization_sha256,
        output_dir=output_dir,
        run_id=run_id,
        clock=clock,
        dry_run=dry_run,
        client_factory=client_factory,
        sleep=sleep,
    )


def require_product_gate_probe_run_v3(run_dir: str | Path) -> Path:
    return _require_pilot_run(run_dir, route=PRODUCT_GATE_PROBE_V3_ROUTE)
