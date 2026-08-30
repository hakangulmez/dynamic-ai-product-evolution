"""Governed execution successor for the annual-coverage-backed pilot selection.

V2 changes only provenance: it consumes the ADR-139 selection drawn from the
completed annual-coverage cohort.  The Item 1 prompt, four model axes, record
contract and non-fatal review semantics remain the released V1 values.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .classifier_pilot_selection_v2 import (
    PILOT_SELECTION_V2_CONTRACT,
    PILOT_SELECTION_V2_KIND,
    require_pilot_selection_v2,
)
from .lineage_classifier_pilot_v1 import (
    PilotRunRoute,
    _require_pilot_run,
    _run_lineage_classifier_pilot,
)
from .universe.lineage_screen import ScreenRunResult

__all__ = [
    "PILOT_V2_ROUTE",
    "require_pilot_run_v2",
    "run_lineage_classifier_pilot_v2",
]


def _load_v2_selection(path: Path, digest: str, root: Path) -> dict:
    return require_pilot_selection_v2(
        path, expected_sha256=digest, repo_root=root)


PILOT_V2_ROUTE = PilotRunRoute(
    run_kind="classifier_pilot_v2",
    records_filename="universe_classifier_pilot_v2_records.jsonl",
    manifest_filename="universe_classifier_pilot_v2_manifest.json",
    raw_responses_filename="universe_classifier_pilot_v2_raw_responses.jsonl",
    manifest_contract="universe_classifier_pilot_manifest@0.2.0",
    manifest_schema="schemas/universe_classifier_pilot_manifest.v2.schema.json",
    authorization_contract="universe_classifier_pilot_authorization@0.2.0",
    authorization_schema="schemas/universe_classifier_pilot_authorization.v2.schema.json",
    run_root_name="universe-classifier-pilot-v2-runs",
    selection_contract=PILOT_SELECTION_V2_CONTRACT,
    selection_kind=PILOT_SELECTION_V2_KIND,
    selection_source="annual_coverage",
    load_selection=_load_v2_selection,
)


def run_lineage_classifier_pilot_v2(
    *, repo_root: str | Path, cohort_manifest_path: str | Path,
    coverage_manifest_path: str | Path, packet_manifest_path: str | Path,
    selection_path: str | Path, governance_root: str | Path,
    authorization_reference: str, authorization_sha256: str,
    output_dir: str | Path, run_id: str, clock: Callable[[], datetime],
    dry_run: bool = False, client_factory: Any = None,
    sleep: Callable[[float], None] | None = None,
) -> ScreenRunResult:
    """Run the V2 ten-firm pilot under its own authorization and manifest."""
    return _run_lineage_classifier_pilot(
        route=PILOT_V2_ROUTE, repo_root=repo_root,
        cohort_manifest_path=cohort_manifest_path,
        coverage_manifest_path=coverage_manifest_path,
        packet_manifest_path=packet_manifest_path, selection_path=selection_path,
        governance_root=governance_root,
        authorization_reference=authorization_reference,
        authorization_sha256=authorization_sha256, output_dir=output_dir,
        run_id=run_id, clock=clock, dry_run=dry_run,
        client_factory=client_factory, sleep=sleep)


def require_pilot_run_v2(run_dir: str | Path) -> Path:
    """Refuse a V1 run or a failed V2 run before consuming any output."""
    return _require_pilot_run(run_dir, route=PILOT_V2_ROUTE)
