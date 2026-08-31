"""Governed V5 route for the product-first Item 1 software-universe gate."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .classifier_pilot_selection_v2 import (
    PILOT_SELECTION_V2_CONTRACT,
    PILOT_SELECTION_V2_KIND,
    require_pilot_selection_v2,
)
from .classifier_pilot_v3 import (
    PILOT_V3_AXES,
    PILOT_V3_AXES_CONTRACT,
    PILOT_V3_AXES_SCHEMA,
    PILOT_V3_RECORD_CONTRACT,
    PILOT_V3_RECORD_SCHEMA,
    build_pilot_v3_record,
)
from .lineage_classifier_pilot_v1 import (
    PilotRunRoute,
    _require_pilot_run,
    _run_lineage_classifier_pilot,
)
from .universe.lineage_screen import ScreenRunResult

__all__ = ["PILOT_V5_ROUTE", "require_pilot_run_v5", "run_lineage_classifier_pilot_v5"]

PILOT_V4_PROMPT_PATH = "prompts/discovery/software_universe_classifier_pilot.v4.md"


def _load_v2_selection(path: Path, digest: str, root: Path, _authorization: dict) -> dict:
    return require_pilot_selection_v2(path, expected_sha256=digest, repo_root=root)


PILOT_V5_ROUTE = PilotRunRoute(
    run_kind="classifier_pilot_v5",
    records_filename="universe_classifier_pilot_v5_records.jsonl",
    manifest_filename="universe_classifier_pilot_v5_manifest.json",
    raw_responses_filename="universe_classifier_pilot_v5_raw_responses.jsonl",
    manifest_contract="universe_classifier_pilot_manifest@0.5.0",
    manifest_schema="schemas/universe_classifier_pilot_manifest.v5.schema.json",
    authorization_contract="universe_classifier_pilot_authorization@0.5.0",
    authorization_schema="schemas/universe_classifier_pilot_authorization.v5.schema.json",
    run_root_name="universe-classifier-pilot-v5-runs",
    selection_contract=PILOT_SELECTION_V2_CONTRACT,
    selection_kind=PILOT_SELECTION_V2_KIND,
    selection_source="annual_coverage",
    load_selection=_load_v2_selection,
    prompt_path=PILOT_V4_PROMPT_PATH,
    axes_schema=PILOT_V3_AXES_SCHEMA,
    axes_contract=PILOT_V3_AXES_CONTRACT,
    record_schema=PILOT_V3_RECORD_SCHEMA,
    record_contract=PILOT_V3_RECORD_CONTRACT,
    judgement_axes=PILOT_V3_AXES,
    build_record=build_pilot_v3_record,
    scope_min_rows=10, scope_max_rows=10, scope_exact_rows=10,
    record_order="pilot_selection_row_order",
    selection_group_field="pilot_stratum",
    selection_group_count_name="by_pilot_stratum",
    scope_noun="ten named pilot filings",
)


def run_lineage_classifier_pilot_v5(
    *, repo_root: str | Path, cohort_manifest_path: str | Path,
    coverage_manifest_path: str | Path, packet_manifest_path: str | Path,
    selection_path: str | Path, governance_root: str | Path,
    authorization_reference: str, authorization_sha256: str,
    output_dir: str | Path, run_id: str, clock: Callable[[], datetime],
    dry_run: bool = False, client_factory: Any = None,
    sleep: Callable[[float], None] | None = None,
) -> ScreenRunResult:
    return _run_lineage_classifier_pilot(
        route=PILOT_V5_ROUTE, repo_root=repo_root,
        cohort_manifest_path=cohort_manifest_path,
        coverage_manifest_path=coverage_manifest_path,
        packet_manifest_path=packet_manifest_path, selection_path=selection_path,
        governance_root=governance_root,
        authorization_reference=authorization_reference,
        authorization_sha256=authorization_sha256, output_dir=output_dir,
        run_id=run_id, clock=clock, dry_run=dry_run,
        client_factory=client_factory, sleep=sleep)


def require_pilot_run_v5(run_dir: str | Path) -> Path:
    return _require_pilot_run(run_dir, route=PILOT_V5_ROUTE)
