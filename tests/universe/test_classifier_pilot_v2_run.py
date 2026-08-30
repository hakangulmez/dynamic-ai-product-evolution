"""ADR-140 route-isolation tests for the annual-coverage-backed pilot run."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dynamic_ai_products.extraction.provider_adapter import client_contract_digest
from dynamic_ai_products.lineage_classifier_pilot_v2 import (
    PILOT_V2_ROUTE,
    require_pilot_run_v2,
    run_lineage_classifier_pilot_v2,
)
from dynamic_ai_products.lineage_classifier_pilot_v1 import require_pilot_run
from dynamic_ai_products.providers.client_contract_v2 import (
    CLIENT_CONTRACT_V2_ID,
    build_client_contract_v2,
    build_operation_endpoints,
)
from dynamic_ai_products.providers.retry_policy import (
    RATE_LIMIT_POLICY_VERSION,
    RETRY_POLICY_VERSION,
)
from dynamic_ai_products.providers.screen_count_retry_policy import (
    SCREEN_COUNT_MAX_ATTEMPTS_V2,
    SCREEN_COUNT_RETRY_POLICY_VERSION,
    SCREEN_EXTERNAL_REQUESTS_PER_ROW_V2,
)
from dynamic_ai_products.providers.screen_retry_policy import (
    SCREEN_GENERATE_MAX_ATTEMPTS,
    SCREEN_GENERATE_RETRY_POLICY_VERSION,
)


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))

from test_classifier_pilot_v1_run import _PilotFactory  # noqa: E402

COVERAGE = ROOT / ("data/runs/universe-annual-coverage-cohorts/"
                   "universe-annual-coverage-cohort-v1-20260829/"
                   "universe_annual_coverage_cohort_manifest.json")
COHORT = ROOT / ("data/runs/universe-classifier-candidate-cohorts/"
                 "universe-classifier-candidate-cohort-v1-20260824/"
                 "universe_classifier_candidate_cohort_manifest.json")
PACKETS = ROOT / ("data/runs/baseline-packets/"
                  "baseline-packets-domestic-text-lineage-v5-20260819/"
                  "baseline_packet_manifest.json")
SELECTION = ROOT / ("data/runs/universe-classifier-pilot-selections-v2/"
                    "universe-classifier-pilot-selection-v2-20260830/"
                    "universe_classifier_pilot_v2_selection.json")
CLOCK = lambda: datetime(2026, 8, 30, tzinfo=timezone.utc)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _grant(tmp_path: Path) -> tuple[Path, str]:
    if not all(path.is_file() for path in (COVERAGE, COHORT, PACKETS, SELECTION)):
        pytest.skip("the governed ADR-138/139 data inputs are absent")
    root = tmp_path / "governance"
    root.mkdir()
    contract = build_client_contract_v2(vertex_project="fixture-project",
                                        vertex_location="us-central1")
    digest = client_contract_digest(contract)
    endpoints = sorted(build_operation_endpoints(
        vertex_project="fixture-project", vertex_location="us-central1").values())
    enablement = {
        "enablement_contract": "universe_screen_adapter_enablement@0.1.0",
        "enablement_id": "fixture", "enabled_by": "test",
        "effective_at": "2026-01-01T00:00:00+00:00",
        "expires_at": "2026-12-31T00:00:00+00:00",
        "deployment_environment_id": "fixture",
        "screen_stage": "universe_high_recall_screen",
        "provider_client_contract_reference": CLIENT_CONTRACT_V2_ID,
        "provider_client_contract_sha256": digest,
        "endpoint_allowlist": endpoints,
    }
    enablement_path = root / "screen_adapter_enablement.json"
    enablement_path.write_text(json.dumps(enablement), encoding="utf-8")
    coverage = json.loads(COVERAGE.read_text())
    authorization = {
        "authorization_contract": "universe_classifier_pilot_authorization@0.2.0",
        "authorization_id": "fixture-v2", "authorized_by": "test",
        "deployment_environment_id": "fixture", "rollout_state": "test",
        "effective_at": "2026-01-01T00:00:00+00:00",
        "expires_at": "2026-12-31T00:00:00+00:00",
        "run_kind": "classifier_pilot_v2", "promotable": False,
        "covers_full_cohort": False,
        "output_contract": "universe_classifier_pilot_record@0.1.0",
        "output_axes_contract": "universe_classifier_pilot_axes_record@0.1.0",
        "prompt_template_path": "prompts/discovery/software_universe_classifier_pilot.v1.md",
        "prompt_template_sha256": _sha(ROOT / "prompts/discovery/software_universe_classifier_pilot.v1.md"),
        "cohort_id": "universe-classifier-candidate-cohort-v1-20260824",
        "cohort_manifest_sha256": _sha(COHORT),
        "coverage_cohort_id": coverage["coverage_cohort_id"],
        "coverage_cohort_manifest_sha256": _sha(COVERAGE),
        "coverage_cohort_records_sha256": coverage["output_hashes"]["universe_annual_coverage_cohort_records.jsonl"],
        "packet_manifest_sha256": _sha(PACKETS),
        "selection_artifact_path": str(SELECTION), "selection_artifact_sha256": _sha(SELECTION),
        "selection_kind": "classifier_pilot_v2",
        "provider_client_contract_reference": CLIENT_CONTRACT_V2_ID,
        "provider_client_contract_sha256": digest,
        "screen_adapter_enablement_reference": "screen_adapter_enablement.json",
        "screen_adapter_enablement_sha256": _sha(enablement_path),
        "vertex_project": "fixture-project", "vertex_location": "us-central1",
        "model_route": {"provider": contract["model_provider"], "model_label": contract["model_name"]},
        "endpoint_allowlist": endpoints, "logical_row_cap": 10,
        "count_attempt_cap": 30, "provider_attempt_cap": 50,
        "budget_max_external_requests": 80,
        "count_attempts_per_row": SCREEN_COUNT_MAX_ATTEMPTS_V2,
        "generate_attempts_per_row": SCREEN_GENERATE_MAX_ATTEMPTS,
        "external_requests_per_row": SCREEN_EXTERNAL_REQUESTS_PER_ROW_V2,
        "retry_policy_version": RETRY_POLICY_VERSION,
        "rate_limit_policy_version": RATE_LIMIT_POLICY_VERSION,
        "screen_generate_retry_policy_version": SCREEN_GENERATE_RETRY_POLICY_VERSION,
        "screen_count_retry_policy_version": SCREEN_COUNT_RETRY_POLICY_VERSION,
        "budget_max_input_tokens": 1_000_000,
        "budget_max_output_tokens": 100_000,
        "budget_max_estimated_cost_micros": 1_000_000,
        "budget_max_wall_clock_seconds": 86_400,
    }
    path = root / "authorization.json"
    path.write_text(json.dumps(authorization), encoding="utf-8")
    return root, _sha(path)


def test_v2_dry_run_hydrates_only_annual_coverage_selection(tmp_path):
    governance, digest = _grant(tmp_path)
    output = tmp_path / "outputs"
    result = run_lineage_classifier_pilot_v2(
        repo_root=ROOT, cohort_manifest_path=COHORT, coverage_manifest_path=COVERAGE,
        packet_manifest_path=PACKETS, selection_path=SELECTION,
        governance_root=governance, authorization_reference="authorization.json",
        authorization_sha256=digest, output_dir=output, run_id="pilot-v2-fixture",
        clock=CLOCK, dry_run=True)
    assert result.status == "dry_run"
    assert result.request_accounting == {
        "selected_rows": 10, "model_called_rows": 10, "logical_row_cap": 10,
        "count_attempt_cap": 30, "provider_attempt_cap": 50,
        "external_request_cap": 80,
    }
    assert not output.exists()


def test_v2_route_uses_its_own_contract_and_filenames():
    assert PILOT_V2_ROUTE.selection_source == "annual_coverage"
    assert PILOT_V2_ROUTE.selection_kind == "classifier_pilot_v2"
    assert PILOT_V2_ROUTE.records_filename == "universe_classifier_pilot_v2_records.jsonl"
    assert PILOT_V2_ROUTE.manifest_contract == "universe_classifier_pilot_manifest@0.2.0"


def test_v2_fixture_execution_writes_only_a_v2_manifest(tmp_path):
    """The annual-coverage route settles under its own contract and loader."""
    governance, digest = _grant(tmp_path)
    selected = json.loads(SELECTION.read_text(encoding="utf-8"))["rows"]
    axes = json.dumps({
        "customer_facing_functional_product": "UNKNOWN",
        "software_centrality": "UNKNOWN",
        "firm_structure": "UNKNOWN",
        "commercial_materiality": "UNKNOWN",
        "confidence": "low",
        "evidence": [],
    })
    factory = _PilotFactory({row["cik"]: {"text": axes} for row in selected}, [])
    output = tmp_path / "outputs"
    result = run_lineage_classifier_pilot_v2(
        repo_root=ROOT, cohort_manifest_path=COHORT, coverage_manifest_path=COVERAGE,
        packet_manifest_path=PACKETS, selection_path=SELECTION,
        governance_root=governance, authorization_reference="authorization.json",
        authorization_sha256=digest, output_dir=output, run_id="pilot-v2-fixture",
        clock=CLOCK, client_factory=factory)

    assert result.status == "completed", result.receipt
    assert result.manifest_path.name == PILOT_V2_ROUTE.manifest_filename
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_contract"] == PILOT_V2_ROUTE.manifest_contract
    assert manifest["sources"]["coverage"]["manifest_sha256"] == _sha(COVERAGE)
    assert set(manifest["output_hashes"]) == {
        "universe_classifier_pilot_v2_records.jsonl",
        "universe_classifier_pilot_v2_raw_responses.jsonl",
        "universe_screen_capture_ledger.jsonl",
    }
    assert require_pilot_run_v2(result.run_dir) == result.manifest_path
    with pytest.raises(Exception, match="v1_manifest"):
        require_pilot_run(result.run_dir)
