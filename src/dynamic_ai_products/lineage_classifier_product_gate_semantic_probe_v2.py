"""Governed V11 execution route for the fixed 23-filing semantic probe."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from .lineage_classifier_pilot_v1 import _require_pilot_run, _run_lineage_classifier_pilot
from .lineage_classifier_product_gate_semantic_probe_v1 import (
    PRODUCT_GATE_SEMANTIC_PROBE_V1_ROUTE,
)
from .universe.lineage_screen import ScreenRunResult

__all__ = [
    "PRODUCT_GATE_SEMANTIC_PROBE_V2_ROUTE",
    "require_product_gate_semantic_probe_run_v2",
    "run_product_gate_semantic_probe_v2",
]


# The selection, its twenty-three filings, and every transport invariant are
# deliberately inherited.  Only the prompt and the V2 route-owned contracts
# and output names move, so the two-test wording experiment remains isolated.
PRODUCT_GATE_SEMANTIC_PROBE_V2_ROUTE = replace(
    PRODUCT_GATE_SEMANTIC_PROBE_V1_ROUTE,
    run_kind="classifier_product_gate_semantic_probe_v2",
    records_filename="universe_classifier_product_gate_semantic_probe_v2_records.jsonl",
    manifest_filename="universe_classifier_product_gate_semantic_probe_v2_manifest.json",
    raw_responses_filename="universe_classifier_product_gate_semantic_probe_v2_raw_responses.jsonl",
    manifest_contract="universe_classifier_product_gate_semantic_probe_manifest@0.2.0",
    manifest_schema="schemas/universe_classifier_product_gate_semantic_probe_manifest.v2.schema.json",
    authorization_contract="universe_classifier_product_gate_semantic_probe_authorization@0.2.0",
    authorization_schema="schemas/universe_classifier_product_gate_semantic_probe_authorization.v2.schema.json",
    run_root_name="universe-classifier-product-gate-semantic-probe-v2-runs",
    prompt_path="prompts/discovery/software_universe_classifier_pilot.v11.md",
    record_order="semantic_probe_v2_row_order",
    scope_noun="23-filing two-test semantic product-gate probe",
)


def run_product_gate_semantic_probe_v2(
    *, repo_root: str | Path, cohort_manifest_path: str | Path,
    coverage_manifest_path: str | Path, packet_manifest_path: str | Path,
    selection_path: str | Path, governance_root: str | Path,
    authorization_reference: str, authorization_sha256: str,
    output_dir: str | Path, run_id: str, clock: Callable[[], datetime],
    dry_run: bool = False, client_factory: Any = None,
    sleep: Callable[[float], None] | None = None,
) -> ScreenRunResult:
    """Run exactly the V11 two-test semantic probe under its own grant."""
    return _run_lineage_classifier_pilot(
        route=PRODUCT_GATE_SEMANTIC_PROBE_V2_ROUTE,
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


def require_product_gate_semantic_probe_run_v2(run_dir: str | Path) -> Path:
    """Refuse any V1 or unrelated run before reading its manifest contract."""
    return _require_pilot_run(run_dir, route=PRODUCT_GATE_SEMANTIC_PROBE_V2_ROUTE)
