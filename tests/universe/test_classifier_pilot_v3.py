"""ADR-141 tests for the two-axis Item 1 universe-gate successor."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products.lineage_classifier_pilot_v1 import _require_pilot_run
from dynamic_ai_products.classifier_pilot_v2 import (
    PILOT_V2_AXES_CONTRACT,
    PILOT_V2_AXES_SCHEMA,
    PILOT_V2_RECORD_CONTRACT,
    PILOT_V2_RECORD_SCHEMA,
    validate_pilot_v2_axes_output,
)
from dynamic_ai_products.human_review_overlay import passage_refs
from dynamic_ai_products.lineage_classifier_pilot_v2 import require_pilot_run_v2
from dynamic_ai_products.lineage_classifier_pilot_v3 import (
    PILOT_V3_ROUTE,
    require_pilot_run_v3,
    run_lineage_classifier_pilot_v3,
)
from dynamic_ai_products.providers.client_contract_v2 import (
    CLIENT_CONTRACT_V2_ID,
    build_client_contract_v2,
    build_operation_endpoints,
)
from dynamic_ai_products.extraction.provider_adapter import client_contract_digest
from dynamic_ai_products.providers.retry_policy import RATE_LIMIT_POLICY_VERSION, RETRY_POLICY_VERSION
from dynamic_ai_products.providers.screen_count_retry_policy import (
    SCREEN_COUNT_MAX_ATTEMPTS_V2, SCREEN_COUNT_RETRY_POLICY_VERSION,
    SCREEN_EXTERNAL_REQUESTS_PER_ROW_V2,
)
from dynamic_ai_products.providers.screen_retry_policy import (
    SCREEN_GENERATE_MAX_ATTEMPTS, SCREEN_GENERATE_RETRY_POLICY_VERSION,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
_PilotFactory = importlib.import_module("test_classifier_pilot_v1_run")._PilotFactory
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


def CLOCK() -> datetime:
    return datetime(2026, 8, 30, tzinfo=UTC)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _packet() -> dict:
    texts = ["The company licenses a cloud platform to enterprise customers.",
             "Subscriptions are its principal source of revenue."]
    passages = [{"passage_id": f"id-{i}", "text": text,
                 "byte_start": i * 100, "byte_end": i * 100 + len(text),
                 "section": "item_1", "source_id": "source", "text_hash": _sha_text(text),
                 "normalizer_version": "v1"} for i, text in enumerate(texts)]
    return {"cik": "0000000001", "accession": "0000000001-22-000001",
            "company_id": "CIK0000000001", "source_id": "source",
            "baseline_cutoff": "2022-01-01", "packet_sha256": "a" * 64,
            "passages": passages}


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _axes(**over) -> dict:
    value = {"customer_facing_digital_product": "YES", "software_centrality": "CORE",
             "confidence": "high", "passage_refs": ["P001", "P002"]}
    value.update(over)
    return value


AXES = Draft202012Validator(json.loads((ROOT / PILOT_V2_AXES_SCHEMA).read_bytes()),
                              format_checker=FormatChecker())
RECORD = Draft202012Validator(json.loads((ROOT / PILOT_V2_RECORD_SCHEMA).read_bytes()),
                                format_checker=FormatChecker())


def _grant(tmp_path: Path) -> tuple[Path, str]:
    if not all(p.is_file() for p in (COVERAGE, COHORT, PACKETS, SELECTION)):
        pytest.skip("the ADR-138/139 artifacts are absent")
    root = tmp_path / "governance"
    root.mkdir()
    contract = build_client_contract_v2(vertex_project="fixture-project", vertex_location="us-central1")
    digest = client_contract_digest(contract)
    endpoints = sorted(build_operation_endpoints(vertex_project="fixture-project", vertex_location="us-central1").values())
    enablement = {"enablement_contract": "universe_screen_adapter_enablement@0.1.0", "enablement_id": "fixture", "enabled_by": "test", "effective_at": "2026-01-01T00:00:00+00:00", "expires_at": "2026-12-31T00:00:00+00:00", "deployment_environment_id": "fixture", "screen_stage": "universe_high_recall_screen", "provider_client_contract_reference": CLIENT_CONTRACT_V2_ID, "provider_client_contract_sha256": digest, "endpoint_allowlist": endpoints}
    enablement_path = root / "screen_adapter_enablement.json"
    enablement_path.write_text(json.dumps(enablement), encoding="utf-8")
    coverage = json.loads(COVERAGE.read_text())
    prompt = ROOT / "prompts/discovery/software_universe_classifier_pilot.v2.md"
    grant = {"authorization_contract": "universe_classifier_pilot_authorization@0.3.0", "authorization_id": "fixture-v3", "authorized_by": "test", "deployment_environment_id": "fixture", "rollout_state": "test", "effective_at": "2026-01-01T00:00:00+00:00", "expires_at": "2026-12-31T00:00:00+00:00", "run_kind": "classifier_pilot_v3", "promotable": False, "covers_full_cohort": False, "output_contract": PILOT_V2_RECORD_CONTRACT, "output_axes_contract": PILOT_V2_AXES_CONTRACT, "prompt_template_path": "prompts/discovery/software_universe_classifier_pilot.v2.md", "prompt_template_sha256": _sha(prompt), "cohort_id": "universe-classifier-candidate-cohort-v1-20260824", "cohort_manifest_sha256": _sha(COHORT), "coverage_cohort_id": coverage["coverage_cohort_id"], "coverage_cohort_manifest_sha256": _sha(COVERAGE), "coverage_cohort_records_sha256": coverage["output_hashes"]["universe_annual_coverage_cohort_records.jsonl"], "packet_manifest_sha256": _sha(PACKETS), "selection_artifact_path": str(SELECTION), "selection_artifact_sha256": _sha(SELECTION), "selection_kind": "classifier_pilot_v2", "provider_client_contract_reference": CLIENT_CONTRACT_V2_ID, "provider_client_contract_sha256": digest, "screen_adapter_enablement_reference": "screen_adapter_enablement.json", "screen_adapter_enablement_sha256": _sha(enablement_path), "vertex_project": "fixture-project", "vertex_location": "us-central1", "model_route": {"provider": contract["model_provider"], "model_label": contract["model_name"]}, "endpoint_allowlist": endpoints, "logical_row_cap": 10, "count_attempt_cap": 30, "provider_attempt_cap": 50, "budget_max_external_requests": 80, "count_attempts_per_row": SCREEN_COUNT_MAX_ATTEMPTS_V2, "generate_attempts_per_row": SCREEN_GENERATE_MAX_ATTEMPTS, "external_requests_per_row": SCREEN_EXTERNAL_REQUESTS_PER_ROW_V2, "retry_policy_version": RETRY_POLICY_VERSION, "rate_limit_policy_version": RATE_LIMIT_POLICY_VERSION, "screen_generate_retry_policy_version": SCREEN_GENERATE_RETRY_POLICY_VERSION, "screen_count_retry_policy_version": SCREEN_COUNT_RETRY_POLICY_VERSION, "budget_max_input_tokens": 1_000_000, "budget_max_output_tokens": 100_000, "budget_max_estimated_cost_micros": 1_000_000, "budget_max_wall_clock_seconds": 86_400}
    path = root / "authorization.json"
    path.write_text(json.dumps(grant), encoding="utf-8")
    return root, _sha(path)


def test_prompt_and_contract_ask_only_two_judgements_and_shared_addresses():
    prompt = (ROOT / "prompts/discovery/software_universe_classifier_pilot.v2.md").read_text()
    assert "two firm-level questions" in prompt
    assert "one separate reference per\nfield" in prompt
    assert "firm_structure" not in prompt and "commercial_materiality" not in prompt
    assert AXES.schema["required"] == ["customer_facing_digital_product", "software_centrality", "confidence", "passage_refs"]
    assert AXES.schema["properties"]["passage_refs"]["maxItems"] == 3


@pytest.mark.parametrize("field", ["quote", "evidence_text", "products", "tasks", "tier", "evidence"])
def test_model_cannot_emit_extraction_or_pipeline_fields(field):
    output = _axes(**{field: "x"})
    with pytest.raises(Exception) as exc:
        validate_pilot_v2_axes_output(json.dumps(output), _packet(), AXES)
    assert getattr(exc.value, "reason_code", None) in {"model_emitted_forbidden_field", "pilot_axes_contract_violation"}


def test_three_shared_references_validate_and_pipeline_resolves_them():
    packet = _packet()
    output = validate_pilot_v2_axes_output(json.dumps(_axes(passage_refs=["P001", "P002"])), packet, AXES)
    assert output["passage_refs"] == ["P001", "P002"]
    assert [e["passage_id"] for e in output["evidence"]] == [passage_refs(packet)["P001"], passage_refs(packet)["P002"]]
    assert all(e["provenance"] == "pipeline_derived" for e in output["evidence"])


@pytest.mark.parametrize("output", [
    _axes(customer_facing_digital_product="NO", software_centrality="CORE"),
    _axes(passage_refs=[]),
    _axes(passage_refs=["P001", "P001"]),
])
def test_incoherent_or_uncited_model_conclusions_are_refused(output):
    assert list(AXES.iter_errors(output))


def test_v3_cli_accepts_its_own_governance_flags():
    spec = importlib.util.spec_from_file_location("pilot_v3_cli", ROOT / "pipelines" / "00_build_company_universe.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    args = cli.build_parser().parse_args(["--mode", "classify-software-universe-pilot-v3", "--cohort-manifest", "/tmp/a", "--annual-coverage-cohort-manifest", "/tmp/b", "--packet-manifest", "/tmp/c", "--pilot-selection", "/tmp/d", "--governance-root", "/tmp/e", "--screen-authorization", "authorization.json", "--screen-authorization-sha256", "0" * 64, "--output-dir", "/tmp/out", "--run-id", "pilot-v3-fixture"])
    assert cli._reject_cross_mode_flags(args) is None


def test_v3_dry_run_and_fixture_run_are_isolated(tmp_path):
    governance, digest = _grant(tmp_path)
    output = tmp_path / "output"
    kwargs = dict(repo_root=ROOT, cohort_manifest_path=COHORT, coverage_manifest_path=COVERAGE, packet_manifest_path=PACKETS, selection_path=SELECTION, governance_root=governance, authorization_reference="authorization.json", authorization_sha256=digest, output_dir=output, run_id="pilot-v3-fixture", clock=CLOCK)
    dry = run_lineage_classifier_pilot_v3(**kwargs, dry_run=True)
    assert dry.status == "dry_run" and not output.exists()
    selected = json.loads(SELECTION.read_text())["rows"]
    response = json.dumps({"customer_facing_digital_product": "UNKNOWN", "software_centrality": "UNKNOWN", "confidence": "low", "passage_refs": []})
    result = run_lineage_classifier_pilot_v3(**kwargs, client_factory=_PilotFactory({r["cik"]: {"text": response} for r in selected}, []))
    assert result.status == "completed", result.receipt
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["manifest_contract"] == PILOT_V3_ROUTE.manifest_contract
    assert manifest["counts"]["classified"] == 10
    assert set(manifest["counts"]) >= {"by_customer_facing_digital_product", "by_software_centrality"}
    assert require_pilot_run_v3(result.run_dir) == result.manifest_path
    with pytest.raises(Exception, match="v2_manifest"):
        require_pilot_run_v2(result.run_dir)
    with pytest.raises(Exception, match="v1_manifest"):
        _require_pilot_run(result.run_dir, route=importlib.import_module("dynamic_ai_products.lineage_classifier_pilot_v1").PILOT_V1_ROUTE)
    records = [json.loads(line) for line in (result.run_dir / PILOT_V3_ROUTE.records_filename).read_text().splitlines()]
    assert all(not list(RECORD.iter_errors(record)) for record in records)
    assert all(record["axes"]["evidence"] == [] for record in records)
