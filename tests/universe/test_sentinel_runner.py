import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from dynamic_ai_products.universe import taxonomy
from dynamic_ai_products.universe.io_utils import read_json, read_jsonl, sha256_file
from dynamic_ai_products.universe.runner import FixtureError, run_universe_sentinel

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "evals" / "fixtures" / "universe_sentinel"
RULES_PATH = ROOT / "configs" / "universe_sample_rules.yaml"
CLI = ROOT / "pipelines" / "00_build_company_universe.py"
EXPECTED = read_json(FIXTURE_DIR / "expected_tiers.json")


@pytest.fixture(scope="module")
def sentinel_run(tmp_path_factory: pytest.TempPathFactory):
    output_dir = tmp_path_factory.mktemp("universe-runs")
    result = run_universe_sentinel(
        repo_root=ROOT,
        rules_path=RULES_PATH,
        input_dir=FIXTURE_DIR,
        output_dir=output_dir,
        run_id="pytest-sentinel",
        seed=42,
        provider="mock",
    )
    return result


def test_code_taxonomy_matches_config() -> None:
    config = taxonomy.load_taxonomy_config(ROOT)
    assert list(taxonomy.CUSTOMER_VALUE_ARCHETYPES) == config["customer_value_archetypes"]
    assert list(taxonomy.SOFTWARE_CENTRALITY) == config["software_centrality"]
    assert list(taxonomy.COMPLEMENTARY_DEPENDENCIES) == config["complementary_dependencies"]
    assert list(taxonomy.FIRM_STRUCTURE) == config["firm_structure"]
    assert list(taxonomy.COMMERCIAL_MATERIALITY) == config["commercial_materiality"]
    assert list(taxonomy.SCREEN_STATUS) == config["screen_status"]
    assert list(taxonomy.CANDIDATE_TIERS) == config["candidate_tiers"]
    rules = yaml.safe_load(RULES_PATH.read_text())
    assert list(taxonomy.DETERMINISTIC_EXCLUSION_REASON_CODES) == (
        rules["excluded"]["deterministic_reason_codes"]
    )


def test_fixture_run_matches_gold_tiers(sentinel_run) -> None:
    assert sentinel_run.tier_by_cik == EXPECTED["expected_final_tiers"]
    for key, value in EXPECTED["expected_counts"].items():
        assert sentinel_run.counts[key] == value, key
    assert sentinel_run.hard_gate_failures == []
    assert sentinel_run.freeze_status == "frozen"
    assert sentinel_run.universe_version == "UNIVERSE_v0.0-sentinel-fixture"


def test_temporal_leakage_case_is_blocked_and_uncertain(sentinel_run) -> None:
    failures = read_jsonl(sentinel_run.run_dir / "packet_failures.jsonl")
    assert [f["reason_code"] for f in failures] == ["TEMPORAL_LEAKAGE"]
    assert failures[0]["cik"] == "0001000016"
    assert sentinel_run.tier_by_cik["0001000016"] == "UNCERTAIN"
    # The leaked passage never reaches screens or classifications.
    for name in ("universe_screen_predictions.jsonl", "universe_classifications_raw.jsonl"):
        assert all(r["cik"] != "0001000016" for r in read_jsonl(sentinel_run.run_dir / name))


def test_insufficient_evidence_stays_uncertain(sentinel_run) -> None:
    assert sentinel_run.tier_by_cik["0001000015"] == "UNCERTAIN"


def test_exited_incumbent_is_retained_with_lineage(sentinel_run) -> None:
    assert sentinel_run.tier_by_cik["0001000018"] == "TIER_A_CORE"
    lineage = read_jsonl(sentinel_run.run_dir / "firm_lineage.jsonl")
    relations = {(l["company_id"], l["relationship"]) for l in lineage}
    assert ("CIK0001000018", "target") in relations
    assert ("CIK0001000017", "name_change") in relations
    assert ("CIK0001000001", "share_class_same_issuer") in relations


def test_entrant_cohort_is_separated(sentinel_run) -> None:
    assert "0001000019" not in sentinel_run.tier_by_cik
    firm_years = {r["cik"]: r for r in read_jsonl(sentinel_run.run_dir / "firm_year_eligibility.jsonl")}
    entrant = firm_years["0001000019"]
    assert entrant["dynamic_entrant"] is True
    assert entrant["primary_incumbent"] is False
    assert entrant["entry_type"] == "ipo"
    assert entrant["universe_class_at_date"] is None
    incumbent = firm_years["0001000001"]
    assert incumbent["entry_type"] == "baseline_incumbent"
    assert incumbent["dynamic_entrant"] is False


def test_duplicate_share_class_consolidates_to_one_company(sentinel_run) -> None:
    companies = read_jsonl(sentinel_run.run_dir / "companies.jsonl")
    ciks = [c["cik"] for c in companies]
    assert len(ciks) == len(set(ciks)) == 24
    decisions = read_jsonl(sentinel_run.run_dir / "issuer_filter_decisions.jsonl")
    duplicate = [d for d in decisions if "DUPLICATE_ISSUER_RECORD" in d.get("reason_codes", [])]
    assert len(duplicate) == 1 and duplicate[0]["cik"] == "0001000001"


def test_adjudication_is_append_only_and_separated_from_raw(sentinel_run) -> None:
    raw = {r["cik"]: r for r in read_jsonl(sentinel_run.run_dir / "universe_classifications_raw.jsonl")}
    processed = {r["cik"]: r for r in read_jsonl(sentinel_run.run_dir / "company_universe_classifications.jsonl")}
    tier_decisions = {r["cik"]: r for r in read_jsonl(sentinel_run.run_dir / "tier_decisions.jsonl")}
    # AGT: mixed nonseparable derives Tier C per ADR-009; adjudication confirms.
    assert tier_decisions["0001000012"]["derived_tier"] == (
        EXPECTED["rule_derived_tier_before_adjudication"]["0001000012"]
    )
    assert processed["0001000012"]["candidate_tier"] == "TIER_C_BOUNDARY"
    assert processed["0001000012"]["review_status"] == "approved"
    # The raw classifier record is untouched by review.
    assert raw["0001000012"]["review_status"] == "unreviewed"
    adjudications = read_jsonl(sentinel_run.run_dir / "adjudications.jsonl")
    assert {a["case_id"] for a in adjudications} == {
        "case-0001000003", "case-0001000011", "case-0001000012",
    }


def test_exclusion_provenance_separates_screen_from_deterministic(sentinel_run) -> None:
    tier_decisions = {r["cik"]: r for r in read_jsonl(sentinel_run.run_dir / "tier_decisions.jsonl")}
    # Deterministic issuer exclusions: SPAC shell and fund.
    for cik in ("0001000013", "0001000014"):
        assert tier_decisions[cik]["exclusion_provenance"] == "deterministic"
    # Screen negatives are provisional screen-derived exclusions with a
    # rule trace pointing at the pending negative audit.
    for cik in ("0001000020", "0001000022", "0001000023", "0001000024"):
        decision = tier_decisions[cik]
        assert decision["exclusion_provenance"] == "screen_derived"
        rule_ids = {t["rule_id"] for t in decision["rule_trace"]}
        assert "screen.likely_ineligible_pending_negative_audit" in rule_ids
    assert sentinel_run.counts["excluded_deterministic"] == 2
    assert sentinel_run.counts["excluded_screen_derived_provisional"] == 4
    assert sentinel_run.counts["negative_audit_completed"] == 6
    assert sentinel_run.counts["negative_audit_pending"] == 0


def test_count_reconciliation_identities_hold(sentinel_run) -> None:
    counts = sentinel_run.counts
    assert counts["filer_records"] == counts["unique_firms"] + counts["duplicate_records"]
    assert counts["unique_firms"] == counts["baseline_firms"] + counts["post_baseline_entrants"]
    assert counts["baseline_firms"] == (
        counts["tier_a"] + counts["tier_b"] + counts["tier_c"]
        + counts["excluded"] + counts["uncertain"]
    )
    assert counts["excluded"] == (
        counts["excluded_deterministic"]
        + counts["excluded_screen_derived_provisional"]
        + counts["excluded_economic_classification"]
    )
    summary = read_json(sentinel_run.run_dir / "run_summary.json")
    manifest = read_json(sentinel_run.manifest_path)
    assert summary["counts"] == manifest["counts"]
    assert "count_reconciliation" in summary


def test_manifest_is_schema_valid_with_content_hashes(sentinel_run) -> None:
    from jsonschema import Draft202012Validator

    manifest = read_json(sentinel_run.manifest_path)
    schema = read_json(ROOT / "schemas" / "universe_run_manifest.schema.json")
    Draft202012Validator(schema).validate(manifest)
    assert manifest["hard_gate_status"] == "pass"
    assert manifest["manual_review_complete"] is True
    assert manifest["negative_audit_seed"] == 42
    assert manifest["taxonomy_version"] == "0.1.0"
    assert manifest["sample_rules_version"] == "0.2.0"
    assert manifest["source_manifest_hash"] is not None
    assert len(manifest["screen_prompt_hash"]) == 64
    for filename, digest in manifest["output_hashes"].items():
        assert sha256_file(sentinel_run.run_dir / filename) == digest
    assert manifest["candidate_frame_hash"] == sha256_file(FIXTURE_DIR / "filer_frame.json")


def test_negative_audit_is_reproducible_across_runs(sentinel_run, tmp_path: Path) -> None:
    rerun = run_universe_sentinel(
        repo_root=ROOT,
        rules_path=RULES_PATH,
        input_dir=FIXTURE_DIR,
        output_dir=tmp_path,
        run_id="pytest-sentinel-rerun",
        seed=42,
        provider="mock",
    )
    first = read_jsonl(sentinel_run.run_dir / "negative_audit_sample.jsonl")
    second = read_jsonl(rerun.run_dir / "negative_audit_sample.jsonl")
    assert first == second
    assert {r["cik"] for r in first} == {
        "0001000013", "0001000014", "0001000020", "0001000022", "0001000023", "0001000024",
    }


def test_run_directory_is_immutable(sentinel_run) -> None:
    with pytest.raises(FileExistsError):
        run_universe_sentinel(
            repo_root=ROOT,
            rules_path=RULES_PATH,
            input_dir=FIXTURE_DIR,
            output_dir=sentinel_run.run_dir.parent,
            run_id=sentinel_run.run_id,
            seed=42,
            provider="mock",
        )


def test_freeze_is_blocked_when_adjudications_are_missing(tmp_path: Path) -> None:
    bundle = tmp_path / "fixture-no-adjudication"
    shutil.copytree(FIXTURE_DIR, bundle)
    (bundle / "adjudications.json").write_text("[]\n", encoding="utf-8")
    result = run_universe_sentinel(
        repo_root=ROOT,
        rules_path=RULES_PATH,
        input_dir=bundle,
        output_dir=tmp_path / "runs",
        run_id="pytest-blocked",
        seed=42,
        provider="mock",
    )
    assert result.freeze_status == "blocked"
    assert result.universe_version == "unreleased"
    assert result.counts["review_cases_open"] == 3
    assert any("unresolved" in reason for reason in result.freeze_blockers)
    manifest = read_json(result.run_dir / "company_universe_manifest.json")
    assert manifest["hard_gate_status"] == "fail"
    assert manifest["manual_review_complete"] is False


def test_freeze_is_blocked_when_negative_audit_incomplete(tmp_path: Path) -> None:
    bundle = tmp_path / "fixture-no-audit"
    shutil.copytree(FIXTURE_DIR, bundle)
    (bundle / "negative_audit_results.json").write_text("[]\n", encoding="utf-8")
    result = run_universe_sentinel(
        repo_root=ROOT,
        rules_path=RULES_PATH,
        input_dir=bundle,
        output_dir=tmp_path / "runs",
        run_id="pytest-audit-blocked",
        seed=42,
        provider="mock",
    )
    assert result.freeze_status == "blocked"
    assert result.universe_version == "unreleased"
    assert any("negative audit is not complete" in r for r in result.freeze_blockers)
    assert result.counts["negative_audit_pending"] == 6
    manifest = read_json(result.run_dir / "company_universe_manifest.json")
    assert manifest["hard_gate_status"] == "fail"


def test_missing_baseline_cutoff_stops_the_run(tmp_path: Path) -> None:
    bundle = tmp_path / "fixture-no-cutoff"
    shutil.copytree(FIXTURE_DIR, bundle)
    manifest = json.loads((bundle / "fixture_manifest.json").read_text(encoding="utf-8"))
    del manifest["baseline_cutoff"]
    (bundle / "fixture_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(FixtureError):
        run_universe_sentinel(
            repo_root=ROOT,
            rules_path=RULES_PATH,
            input_dir=bundle,
            output_dir=tmp_path / "runs",
            run_id="pytest-no-cutoff",
            seed=42,
            provider="mock",
        )


def test_path_traversal_run_id_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FixtureError):
        run_universe_sentinel(
            repo_root=ROOT,
            rules_path=RULES_PATH,
            input_dir=FIXTURE_DIR,
            output_dir=tmp_path,
            run_id="../escape",
            seed=42,
            provider="mock",
        )


def test_non_mock_provider_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FixtureError):
        run_universe_sentinel(
            repo_root=ROOT,
            rules_path=RULES_PATH,
            input_dir=FIXTURE_DIR,
            output_dir=tmp_path,
            run_id="pytest-provider",
            seed=42,
            provider="real-llm",
        )


def test_cli_dry_run_writes_nothing_and_exits_zero(tmp_path: Path) -> None:
    output_dir = tmp_path / "cli-dry"
    completed = subprocess.run(
        [
            sys.executable, str(CLI),
            "--config", str(RULES_PATH),
            "--input", str(FIXTURE_DIR),
            "--output-dir", str(output_dir),
            "--run-id", "cli-dry-run",
            "--seed", "42",
            "--provider", "mock",
            "--dry-run",
        ],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["dry_run"] is True and payload["run_dir"] is None
    assert not output_dir.exists()


def test_cli_fixture_execution_produces_expected_outputs(tmp_path: Path) -> None:
    output_dir = tmp_path / "cli-full"
    completed = subprocess.run(
        [
            sys.executable, str(CLI),
            "--config", str(RULES_PATH),
            "--input", str(FIXTURE_DIR),
            "--output-dir", str(output_dir),
            "--run-id", "cli-full-run",
            "--seed", "42",
            "--provider", "mock",
        ],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["freeze_status"] == "frozen"
    run_dir = Path(payload["run_dir"])
    assert (run_dir / "company_universe_manifest.json").exists()
    summary = read_json(run_dir / "run_summary.json")
    assert summary["tier_by_cik"] == EXPECTED["expected_final_tiers"]


def test_cli_reports_clear_error_on_missing_input(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable, str(CLI),
            "--config", str(RULES_PATH),
            "--input", str(tmp_path / "does-not-exist"),
            "--output-dir", str(tmp_path),
            "--run-id", "cli-missing",
        ],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert completed.returncode == 2
    assert "not found" in completed.stderr


def test_universe_package_requires_no_network_and_no_legacy_terms() -> None:
    package_dir = ROOT / "src" / "dynamic_ai_products" / "universe"
    forbidden_imports = ("import requests", "import httpx", "import urllib", "import socket")
    legacy_markers = ("pds_", "gss_", "aes_", "drs_", "des_", "rho_score", "delta_score")
    for path in package_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for marker in (*forbidden_imports, *legacy_markers):
            assert marker not in text, f"{path.name} contains forbidden marker {marker!r}"
