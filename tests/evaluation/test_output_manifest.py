"""Slice 12L (corrected): evaluation output manifest (``evaluation_output_manifest@0.1.0``).

The output manifest binds the read-back persisted-byte SHA-256 of the six
*pre-runner* derived outputs of one evaluation run. Validator findings is the
sole required output; the other five are conditional and omitted (never JSON
``null``) when not persisted. The evaluation result belongs to the later
runner/gate layer and is deliberately absent. Every bound artifact is created
and persisted through its real production API; both the builder and the loader
re-read each bound artifact's bytes and reject a hash mismatch, an unexpected
omitted artifact, or a missing one — this is an audit binding.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import metrics as met
from dynamic_ai_products.evaluation import output_manifest as om_mod
from dynamic_ai_products.evaluation.assertions import (
    load_assertion_outcomes,
    persist_assertion_outcomes,
)
from dynamic_ai_products.evaluation.case_sets import load_case_set_manifest
from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.metric_inputs import (
    AssertionMetricBinding,
    AxisDefinition,
    AxisEvaluationRecord,
    ValidatorRuleEvaluationRecord,
    build_metric_input_snapshot,
    persist_metric_input_snapshot,
)
from dynamic_ai_products.evaluation.metrics import (
    MetricReport,
    MetricReportV2,
    PersistedMetricReport,
    compute_metric_report,
    compute_metric_report_v2,
    persist_metric_report,
)
from dynamic_ai_products.evaluation.models import AssertionOutcome, ValidatorFinding
from dynamic_ai_products.evaluation.output_manifest import (
    EvaluationOutputManifest,
    EvaluationOutputManifestError,
    LoadedEvaluationOutputManifest,
    build_evaluation_output_manifest,
    load_evaluation_output_manifest,
    persist_evaluation_output_manifest,
)
from dynamic_ai_products.evaluation.prediction_content import (
    ParsedPredictionContent,
    persist_parsed_prediction_content,
)
from dynamic_ai_products.evaluation.references import load_target_registry
from dynamic_ai_products.evaluation.runs import (
    initialize_evaluation_run,
    initialize_evaluation_run_v2,
)
from dynamic_ai_products.evaluation.scoring_config import (
    DiagnosticDefinition,
    GateDefinition,
    LoadedScoringGateConfig,
    ScoringGateConfig,
    load_scoring_gate_config,
)
from dynamic_ai_products.evaluation.stage_evidence import (
    LoadedStageMetricEvidenceSet,
    build_stage_metric_evidence_set,
    stage_metric_evidence_set_hash,
)
from dynamic_ai_products.evaluation.stage_profiles import (
    load_stage_profile_registry,
    resolve_metric_applicability,
)
from dynamic_ai_products.evaluation.validation_snapshot import (
    ValidationArtifactSnapshot,
    build_validation_artifact_snapshot_set,
    persist_validation_artifact_snapshot_set,
)
from dynamic_ai_products.evaluation.validators import (
    VALIDATOR_RULE_ORDER,
    load_validator_findings,
    persist_validator_findings,
)
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness"
CASE_SET = load_case_set_manifest("valid_base_case_set_manifest.json", eval_root=FX / "case_sets")
REGISTRY = load_target_registry("valid_target_registry.json", eval_root=FX / "configs")
SCORING = load_scoring_gate_config("valid_scoring_gate_config.json", eval_root=FX / "configs")
SP_REG = load_stage_profile_registry("stage_profiles/stage_profile_registry.json", eval_root=FX)

MODEL_HASH = "2a58607da0a0d457bee99d6760d7ccb93a6e72ca2e255a82b7cb75e27f956e3e"
CID = "SYNTH-CASE-0001"
HEX = "a" * 64
CREATED = "2026-07-25T00:00:00+00:00"
STAGE = "universe_classification"

AO_META = {"contract_id": "assertion_outcome", "contract_version": "0.1.0",
           "contract_hash": model_contract_hash(AssertionOutcome, "assertion_outcome", "0.1.0")}
VF_META = {"contract_id": "validator_finding", "contract_version": "0.1.0",
           "contract_hash": model_contract_hash(ValidatorFinding, "validator_finding", "0.1.0")}
PPC_META = {"contract_id": "parsed_prediction_content", "contract_version": "0.1.0",
            "contract_hash": model_contract_hash(
                ParsedPredictionContent, "parsed_prediction_content", "0.1.0")}

# The six canonical run-relative artifact locations, hardcoded here to
# independently pin the contract (never the module-private mapping).
LOC = {
    "validator_findings_sha256": ("findings", "validator_findings.jsonl"),
    "parsed_prediction_content_sha256": ("snapshots", "parsed_prediction_content.json"),
    "assertion_outcomes_sha256": ("assertions", "assertion_outcomes.jsonl"),
    "validation_artifact_snapshot_set_sha256":
        ("snapshots", "validation_artifact_snapshot_set.json"),
    "metric_input_snapshot_sha256": ("metric_inputs", "metric_input_snapshot.json"),
    "metric_report_v2_sha256": ("metrics", "metric_report.v2.json"),
}

SCREEN = {"kind": "universe_screen_operational", "screen_operational_summary": {
    "total_screened": 10, "screen_negative": 4, "screen_nonnegative": 5,
    "unresolved": 1, "downstream_review_count": 3}}
UNSAFE = {"kind": "universe_unsafe_exclusion_audit", "unsafe_exclusion_audit": {
    "audit_snapshot_hash": "b" * 64, "seed": 1, "sampling_design_id": "d",
    "strata": [{"stratum_id": "s1", "screen_negative_population_count": 100, "audited_labels": [
        {"record_id": "a0", "verification_status": "verified",
         "actually_eligible_or_boundary_relevant": False}]}]}}
TIER = {"kind": "universe_classification_tier", "tier_contract_observations": [{
    "record_id": "t1", "verification_status": "verified", "tier_rule_version": "v",
    "expected_tier": "T", "observed_tier": "T", "expected_reason_codes": ["r"],
    "observed_reason_codes": ["r"], "expected_rule_trace_hash": "c" * 64,
    "observed_rule_trace_hash": "c" * 64, "repeatability_output_hashes": ["d" * 64, "d" * 64]}]}
_KIND_VARIANTS = {"universe_classification_tier": TIER,
                  "universe_screen_operational": SCREEN,
                  "universe_unsafe_exclusion_audit": UNSAFE}


# --- Derived-input builders ------------------------------------------------


def ao(run_id="run1", outcome="satisfied"):
    return AssertionOutcome.model_validate({"contract": AO_META, "eval_run_id": run_id,
        "case_id": CID, "assertion_id": "A1", "assertion_semantic_version": "0.1.0",
        "outcome": outcome})


def vf(run_id="run1"):
    return ValidatorFinding.model_validate({"contract": VF_META, "finding_id": "f1",
        "validator": "source_id_resolution", "validator_bundle_version": "vb",
        "validator_bundle_hash": "b" * 64, "rule_params_hash": HEX, "severity": "error",
        "run_id": run_id, "artifact_id": "art1", "observed_value": "x", "expected_invariant": "y",
        "message": "m", "evidence": "e", "repairable": False, "created_at": "2026-07-20T00:00:00Z"})


def _gate(mid, sl):
    return GateDefinition(reference_id=f"g-{mid}-{sl}", metric_id=mid, population_slice_id=sl,
        verified_support_requirement={"minimum_verified_support": 0}, ci_method_reference=None,
        blocking_severity="synth-critical", protected_regression_class_references=(),
        slice_definitions=({"s": sl},), threshold={"x": 1})


def _diag(mid, sl):
    return DiagnosticDefinition(reference_id=f"d-{mid}-{sl}", metric_id=mid, population_slice_id=sl,
        slice_definitions=({"minimum_verified_support": 0},))


def _config(version):
    unsafe = GateDefinition(reference_id="g-unsafe-overall", metric_id=met.METRIC_UNSAFE_EXCLUSION,
        population_slice_id="overall", verified_support_requirement={"minimum_audited_per_stratum": 1},
        ci_method_reference="wilson_one_sided_stratified", blocking_severity="synth-critical",
        protected_regression_class_references=(), slice_definitions=({"s": "overall"},),
        threshold={"confidence_level": 0.95})
    return ScoringGateConfig(config_version=version, blocking_severities=("synth-critical",),
        protected_regression_classes=(),
        gates=(_gate(met.METRIC_AXIS_MULTI_LABEL, "axis-1"), _gate(met.METRIC_TIER_CONTRACT, "overall"),
               unsafe),
        diagnostics=(_diag(met.METRIC_ASSERTION_OUTCOMES, "overall"),
                     _diag(met.METRIC_VALIDATOR_RULES, "overall"),
                     _diag(met.METRIC_VALIDATOR_SUMMARIES, "overall"),
                     _diag(met.METRIC_SCREEN_OPERATIONAL, "overall"),
                     _diag(met.METRIC_AXIS_ABSTENTION, "axis-1")))


def _evidence(stage):
    entry = resolve_metric_applicability(SP_REG.registry, stage)
    kinds = entry.required_stage_evidence_kinds
    if not kinds:
        return None
    variants = tuple(_KIND_VARIANTS[k] for k in sorted(kinds))
    evset = build_stage_metric_evidence_set(evaluation_stage=stage, set_version="se-v1",
                                            variants=variants)
    return LoadedStageMetricEvidenceSet(model=evset, version="se-v1", sha256="d" * 64,
                                        artifact_reference="stage_evidence/e.json")


def _init_v2(eval_root, stage, ev, run_id="run1"):
    kw = {}
    if ev is not None:
        kw["stage_metric_evidence_set_version"] = ev.model.set_version
        kw["stage_metric_evidence_set_hash"] = stage_metric_evidence_set_hash(ev.model)
    return initialize_evaluation_run_v2(
        eval_root=eval_root, eval_run_id=run_id, prediction_run_id="P",
        prediction_run_manifest_hash="a" * 64, case_set=CASE_SET, registry=REGISTRY,
        validator_bundle_version="vb", validator_bundle_hash="b" * 64, scoring_config=SCORING,
        code_commit="c", config_snapshot_source_root=FX / "configs", evaluation_created_at=CREATED,
        evaluation_stage=stage, stage_profile_registry=SP_REG,
        semantic_adapter_registry_version="sa-v1", semantic_adapter_registry_hash=HEX,
        selected_semantic_adapter_entry_hash=HEX,
        source_passage_snapshot_version="sp-v1", source_passage_snapshot_hash=HEX,
        gold_assertion_set_version="g-v1", gold_assertion_set_hash=HEX,
        axis_taxonomy_version="ax-v1", axis_taxonomy_hash=HEX,
        validator_rule_parameters_version="vp-v1", validator_rule_parameters_hash=HEX, **kw,
    ).manifest


def _init_v1(eval_root, run_id="run1"):
    return initialize_evaluation_run(
        eval_root=eval_root, eval_run_id=run_id, prediction_run_id="SYNTH-PRED-RUN-0001",
        prediction_run_manifest_hash="a" * 64, case_set=CASE_SET, registry=REGISTRY,
        validator_bundle_version="vb", validator_bundle_hash="b" * 64, scoring_config=SCORING,
        code_commit="c", config_snapshot_source_root=FX / "configs",
    ).manifest


def _snapshot(rm, stage, ev):
    axis = AxisDefinition(axis_id="axis-1", axis_role="product", metric_type="abstention_allowed",
                          base_metric_type="multi_label", labels=("a", "b"))
    records = (AxisEvaluationRecord(record_id="r1", case_id=CID, axis_id="axis-1",
        metric_scope="conditional", verification_status="verified",
        evidence_resolvability="resolvable", predicted_values=("a",), gold_values=("a",)),)
    return build_metric_input_snapshot(
        evaluation_stage=stage, stage_profile_registry=SP_REG, run_manifest=rm,
        axis_definitions=(axis,), axis_records=records,
        assertion_bindings=(AssertionMetricBinding(case_id=CID, assertion_id="A1",
            assertion_kind="expected_entity", partition="dev", suites=("adversarial", "regression")),),
        validator_rule_evaluations=(ValidatorRuleEvaluationRecord(artifact_id="art1",
            rule_id="source_id_resolution", evaluated_observation_count=5,
            failed_observation_count=1),),
        stage_evidence=ev)


def _parsed():
    return ParsedPredictionContent.model_validate({
        "contract": PPC_META, "case_id": CID, "stage": STAGE, "prediction_record_id": "PR-1",
        "input_packet_hash": HEX, "observation_cutoff": "2025-12-31",
        "raw_artifact_reference": "parsed_content/raw.json", "raw_artifact_sha256": HEX,
        "raw_output_preserved": True, "repair_applied": False,
        "repair_record_references": [], "repair_record_hashes": [],
        "entity_collection": {"completeness": "complete", "entities": [
            {"entity_kind": "product", "entity_ref": "P.A"}]},
        "field_value_collection": {"completeness": "complete", "field_values": [
            {"entity_ref": "P.A", "field_name": "maturity", "field_value": "ga"}]},
        "evidence_collection": {"completeness": "complete", "evidence": [
            {"entity_ref": "P.A", "source_id": "s1", "passage_id": "p1", "quote": "q"}]},
    })


def _passing_obs(parsed_sha):
    return [
        {"rule_id": "output_json_schema_validity", "observation_id": "o1", "parse_succeeded": True,
         "schema_valid": True, "schema_reference": "s.json", "validation_errors": []},
        {"rule_id": "required_field_presence", "observation_id": "o2", "required_fields": ["a", "b"],
         "present_fields": ["a", "b", "c"]},
        {"rule_id": "source_id_resolution", "observation_id": "o3", "referenced_source_ids": ["s1"],
         "available_source_ids": ["s1", "s2"]},
        {"rule_id": "passage_id_resolution", "observation_id": "o4", "referenced_passage_ids": ["p1"],
         "available_passage_ids": ["p1"]},
        {"rule_id": "evidence_quote_containment", "observation_id": "o5", "quote": "alpha",
         "passage_text": "the alpha beta", "passage_id": "p1"},
        {"rule_id": "publication_date_cutoff", "observation_id": "o6", "publication_date": "2020-01-01",
         "observation_cutoff_date": "2020-06-01", "source_id": "s1"},
        {"rule_id": "product_capability_task_parent_resolution", "observation_id": "o7",
         "child_id": "c1", "parent_id": "pp", "available_parent_ids": ["pp", "qq"]},
        {"rule_id": "unique_ids_within_scope", "observation_id": "o8", "scope_id": "sc",
         "record_ids": ["a", "b", "c"]},
        {"rule_id": "prohibited_legacy_fields_absent", "observation_id": "o9",
         "present_field_names": ["x", "y"], "prohibited_field_names": ["legacy"]},
        {"rule_id": "active_record_non_roadmap_evidence", "observation_id": "o10", "active": True,
         "evidence": [{"evidence_id": "e1", "is_future_roadmap": True},
                      {"evidence_id": "e2", "is_future_roadmap": False}]},
        {"rule_id": "customer_task_outcome_and_evidence", "observation_id": "o11",
         "is_customer_facing_task": True, "customer_outcome": "did the thing", "evidence_ids": ["e1"]},
        {"rule_id": "raw_output_and_repair_preservation", "observation_id": "o12",
         "raw_output_reference": "raw.json", "raw_artifact_sha256": "e" * 64,
         "raw_output_preserved": True, "repair_applied": False, "repair_record_references": [],
         "repair_record_hashes": [], "parsed_content_sha256": parsed_sha},
    ]


def _vsnap(run_id, artifact_id, art_sha, parsed_sha):
    return ValidationArtifactSnapshot.model_validate({
        "eval_run_id": run_id, "artifact_id": artifact_id, "stage": STAGE,
        "artifact_sha256": art_sha, "parsed_prediction_content_sha256": parsed_sha,
        "created_at": CREATED, "case_id": CID,
        "observations": _passing_obs(parsed_sha),
        "coverage": [{"rule_id": r, "coverage_state": "fully_evaluated", "candidate_count": 1,
                      "evaluated_observation_count": 1, "blocked_candidate_count": 0,
                      "reason_counts": []} for r in VALIDATOR_RULE_ORDER],
    })


def _vset(run_id="run1"):
    return build_validation_artifact_snapshot_set(
        snapshot_set_version="synth-vset-v1", eval_run_id=run_id, evaluation_stage=STAGE,
        snapshots=(_vsnap(run_id, "art-0001", "a" * 64, "c" * 64),
                   _vsnap(run_id, "art-0002", "b" * 64, "d" * 64)))


# --- Real-producer scaffolding (v0.2 run) ----------------------------------

ALL_SIX = ("validator_findings", "parsed", "assertions", "validation", "metric_input", "metric_report")


def _v2_run(tmp_path, run_id="run1"):
    ev = _evidence(STAGE)
    rm = _init_v2(tmp_path, STAGE, ev, run_id=run_id)
    lc = LoadedScoringGateConfig(config=_config(rm.scoring_gate_config_version),
        version=rm.scoring_gate_config_version, sha256=rm.scoring_gate_config_hash,
        artifact_reference="x")
    snap = _snapshot(rm, STAGE, ev)
    report_v2 = compute_metric_report_v2(snap, assertion_outcomes=(ao(run_id),),
        validator_findings=(vf(run_id),), run_manifest=rm, case_set_manifest=CASE_SET,
        scoring_config=lc, stage_profile_registry=SP_REG)
    return rm, lc, snap, report_v2


def _persist(tmp_path, which, snap, report_v2, run_id="run1"):
    """Persist the requested pre-runner artifacts through their real APIs."""
    w = {}
    w["validator_findings"] = persist_validator_findings((vf(run_id),),
        eval_root=tmp_path, eval_run_id=run_id)
    if "parsed" in which:
        w["parsed_prediction_content"] = persist_parsed_prediction_content(_parsed(),
            eval_root=tmp_path, eval_run_id=run_id)
    if "assertions" in which:
        w["assertion_outcomes"] = persist_assertion_outcomes((ao(run_id),),
            eval_root=tmp_path, eval_run_id=run_id)
    if "validation" in which:
        w["validation_artifact_snapshot_set"] = persist_validation_artifact_snapshot_set(
            _vset(run_id), eval_root=tmp_path, eval_run_id=run_id)
    if "metric_input" in which:
        w["metric_input_snapshot"] = persist_metric_input_snapshot(snap,
            eval_root=tmp_path, eval_run_id=run_id)
    if "metric_report" in which:
        w["metric_report"] = persist_metric_report(report_v2, eval_root=tmp_path,
            eval_run_id=run_id, stage_profile_registry=SP_REG)
    return w


def _scaffold(tmp_path, which=ALL_SIX, run_id="run1"):
    rm, lc, snap, report_v2 = _v2_run(tmp_path, run_id)
    w = _persist(tmp_path, which, snap, report_v2, run_id)
    return rm, lc, snap, report_v2, w


def _build(tmp_path, w, *, run_id="run1", **overrides):
    kw = {"eval_root": tmp_path, "eval_run_id": run_id,
          "validator_findings": w["validator_findings"]}
    for k in ("parsed_prediction_content", "assertion_outcomes",
              "validation_artifact_snapshot_set", "metric_input_snapshot", "metric_report"):
        if k in w:
            kw[k] = w[k]
    kw.update(overrides)
    return build_evaluation_output_manifest(**kw)


# --- v0.1 / v0.2 persistence compatibility ---------------------------------


def test_v1_assertion_and_validator_persist_load_unchanged(tmp_path):
    _init_v1(tmp_path, "run1")
    pv = persist_validator_findings((vf("run1"),), eval_root=tmp_path, eval_run_id="run1")
    pa = persist_assertion_outcomes((ao("run1"),), eval_root=tmp_path, eval_run_id="run1")
    assert pv.artifact_reference == "run1/findings/validator_findings.jsonl"
    assert pa.artifact_reference == "run1/assertions/assertion_outcomes.jsonl"
    lv = load_validator_findings("run1", eval_root=tmp_path)
    la = load_assertion_outcomes("run1", eval_root=tmp_path)
    assert lv.findings[0].run_id == "run1"
    assert la.outcomes[0].eval_run_id == "run1"


def test_v2_assertion_and_validator_persist_load(tmp_path):
    _init_v2(tmp_path, STAGE, _evidence(STAGE), "run1")
    pv = persist_validator_findings((vf("run1"),), eval_root=tmp_path, eval_run_id="run1")
    pa = persist_assertion_outcomes((ao("run1"),), eval_root=tmp_path, eval_run_id="run1")
    assert pv.sha256 == load_validator_findings("run1", eval_root=tmp_path).sha256
    assert pa.sha256 == load_assertion_outcomes("run1", eval_root=tmp_path).sha256


# --- Contract identity -----------------------------------------------------


def test_model_contract_stamp_and_hash(tmp_path):
    _, _, _, _, w = _scaffold(tmp_path, which=("validator_findings",))
    m = _build(tmp_path, w)
    assert m.contract.contract_id == "evaluation_output_manifest"
    assert m.contract.contract_version == "0.1.0"
    assert m.contract.contract_hash == MODEL_HASH
    assert model_contract_hash(
        EvaluationOutputManifest, "evaluation_output_manifest", "0.1.0") == MODEL_HASH


def test_strict_frozen_and_extra_forbid(tmp_path):
    _, _, _, _, w = _scaffold(tmp_path, which=("validator_findings",))
    m = _build(tmp_path, w)
    with pytest.raises(PydanticValidationError):
        m.eval_run_id = "other"
    with pytest.raises(PydanticValidationError):
        EvaluationOutputManifest.model_validate(
            {**m.model_dump(mode="json", exclude_unset=True), "unexpected": 1})


def test_no_evaluation_result_surface():
    import inspect
    # No evaluation-result field, builder input, canonical location, or optional.
    assert "evaluation_result_sha256" not in EvaluationOutputManifest.model_fields
    params = inspect.signature(build_evaluation_output_manifest).parameters
    assert "evaluation_result" not in params
    assert not any("evaluation_result" in field for field in om_mod._ARTIFACT_LOCATION)
    assert not any("evaluation_result" in field for field in om_mod._OPTIONAL_HASH_FIELDS)
    # No runner/gate-layer dependency is imported (only the docstring names it, to
    # explain the exclusion — module import machinery holds no such symbol).
    assert not hasattr(om_mod, "PersistedEvaluationResult")
    assert not hasattr(om_mod, "EvaluationResultV2")
    assert "from .gates" not in "".join(
        ln for ln in inspect.getsource(om_mod).splitlines() if ln.startswith("from "))


# --- Real six-artifact chain -----------------------------------------------


def test_all_six_outputs_completed_run(tmp_path):
    _, _, _, _, w = _scaffold(tmp_path)
    m = _build(tmp_path, w)
    dumped = m.model_dump(mode="json", exclude_unset=True)
    assert set(LOC).issubset(dumped)
    for field, (subdir, filename) in LOC.items():
        expected = sha256_bytes((tmp_path / "run1" / subdir / filename).read_bytes())
        assert dumped[field] == expected
    loaded = persist_evaluation_output_manifest(m, eval_root=tmp_path, eval_run_id="run1")
    assert isinstance(loaded, LoadedEvaluationOutputManifest)
    reloaded = load_evaluation_output_manifest("run1", eval_root=tmp_path)
    assert reloaded.model == m
    assert reloaded.sha256 == loaded.sha256


def test_invalid_run_minimal_chain_omits_conditionals(tmp_path):
    _, _, _, _, w = _scaffold(tmp_path, which=("validator_findings",))
    m = _build(tmp_path, w)
    dumped = m.model_dump(mode="json", exclude_unset=True)
    assert "validator_findings_sha256" in dumped
    for field in om_mod._OPTIONAL_HASH_FIELDS:
        assert field not in dumped
    persist_evaluation_output_manifest(m, eval_root=tmp_path, eval_run_id="run1")
    assert load_evaluation_output_manifest("run1", eval_root=tmp_path).model == m


# --- Optional field discipline ---------------------------------------------


def test_optional_omitted_never_null_in_json(tmp_path):
    _, _, _, _, w = _scaffold(tmp_path, which=("validator_findings", "assertions"))
    m = _build(tmp_path, w)
    dumped = m.model_dump(mode="json", exclude_unset=True)
    assert "assertion_outcomes_sha256" in dumped
    assert not any(v is None for v in dumped.values())
    for field in om_mod._OPTIONAL_HASH_FIELDS:
        if field != "assertion_outcomes_sha256":
            assert field not in dumped


def test_explicit_null_optional_rejected(tmp_path):
    _, _, _, _, w = _scaffold(tmp_path, which=("validator_findings",))
    base = _build(tmp_path, w).model_dump(mode="json", exclude_unset=True)
    with pytest.raises(PydanticValidationError):
        EvaluationOutputManifest.model_validate({**base, "metric_report_v2_sha256": None})


# --- Metric report version gate --------------------------------------------


def test_metric_report_v2_accepted(tmp_path):
    _, _, _, _, w = _scaffold(tmp_path, which=("validator_findings", "metric_report"))
    m = _build(tmp_path, w)
    assert m.metric_report_v2_sha256 is not None
    assert isinstance(w["metric_report"].report, MetricReportV2)


def test_metric_report_v1_rejected(tmp_path):
    rm, lc, snap, report_v2, w = _scaffold(tmp_path, which=("validator_findings", "metric_report"))
    v1 = compute_metric_report(snap, assertion_outcomes=(ao(),), validator_findings=(vf(),),
        run_manifest=rm, case_set_manifest=CASE_SET, scoring_config=lc)
    assert isinstance(v1, MetricReport) and not isinstance(v1, MetricReportV2)
    bad = PersistedMetricReport(eval_run_id="run1",
        artifact_reference="run1/metrics/metric_report.v2.json",
        sha256=w["metric_report"].sha256, report=v1)
    with pytest.raises(EvaluationOutputManifestError) as ei:
        _build(tmp_path, w, metric_report=bad)
    assert ei.value.reason_code == "metric_report_version"


# --- Wrapper validation: type / reference / run-binding / hash -------------


def test_builder_rejects_wrong_wrapper_type(tmp_path):
    _, _, _, _, w = _scaffold(tmp_path, which=("validator_findings", "assertions"))
    with pytest.raises(EvaluationOutputManifestError) as ei:
        _build(tmp_path, w, validator_findings=w["assertion_outcomes"])
    assert ei.value.reason_code == "wrapper_type"


def test_builder_rejects_non_canonical_reference(tmp_path):
    _, _, _, _, w = _scaffold(tmp_path, which=("validator_findings",))
    bad = w["validator_findings"].model_copy(update={"artifact_reference": "run1/elsewhere.jsonl"})
    with pytest.raises(EvaluationOutputManifestError) as ei:
        _build(tmp_path, w, validator_findings=bad)
    assert ei.value.reason_code == "wrapper_reference"


def test_builder_rejects_wrapper_run_binding_mismatch(tmp_path):
    _, _, _, _, w = _scaffold(tmp_path, which=("validator_findings",))
    other = w["validator_findings"].model_copy(update={"eval_run_id": "other"})
    with pytest.raises(EvaluationOutputManifestError) as ei:
        _build(tmp_path, w, validator_findings=other)
    assert ei.value.reason_code == "wrapper_run_binding"


def test_builder_rejects_wrapped_model_run_binding_mismatch(tmp_path):
    _, _, snap, _, w = _scaffold(tmp_path, which=("validator_findings", "metric_input"))
    wrapper = w["metric_input_snapshot"]
    other_model = wrapper.model.model_copy(update={"eval_run_id": "other"})
    bad = wrapper.model_copy(update={"model": other_model})
    with pytest.raises(EvaluationOutputManifestError) as ei:
        _build(tmp_path, w, metric_input_snapshot=bad)
    assert ei.value.reason_code == "wrapper_run_binding"


def test_builder_rejects_wrapper_sha_mismatch(tmp_path):
    _, _, _, _, w = _scaffold(tmp_path, which=("validator_findings",))
    tampered = w["validator_findings"].model_copy(update={"sha256": "f" * 64})
    with pytest.raises(EvaluationOutputManifestError) as ei:
        _build(tmp_path, w, validator_findings=tampered)
    assert ei.value.reason_code == "artifact_hash_mismatch"
    assert ei.value.artifact_reference == "run1/findings/validator_findings.jsonl"


def test_builder_rejects_missing_persisted_artifact(tmp_path):
    _, _, _, _, w = _scaffold(tmp_path, which=("validator_findings",))
    (tmp_path / "run1" / "findings" / "validator_findings.jsonl").unlink()
    with pytest.raises(EvaluationOutputManifestError) as ei:
        _build(tmp_path, w)
    assert ei.value.reason_code == "artifact_missing"


def test_build_rejects_missing_run_manifest(tmp_path):
    _, _, _, _, w = _scaffold(tmp_path, which=("validator_findings",))
    with pytest.raises(Exception):
        build_evaluation_output_manifest(eval_root=tmp_path, eval_run_id="absent-run",
            validator_findings=w["validator_findings"])


# --- Completeness: omitted optional must not exist -------------------------


def test_builder_rejects_unexpected_omitted_artifact(tmp_path):
    # assertion outcomes are persisted but not supplied to the builder.
    _, _, _, _, w = _scaffold(tmp_path, which=("validator_findings", "assertions"))
    with pytest.raises(EvaluationOutputManifestError) as ei:
        build_evaluation_output_manifest(eval_root=tmp_path, eval_run_id="run1",
            validator_findings=w["validator_findings"])
    assert ei.value.reason_code == "unexpected_artifact"
    assert ei.value.artifact_reference == "run1/assertions/assertion_outcomes.jsonl"


def test_loader_rejects_unexpected_added_artifact(tmp_path):
    rm, lc, snap, report_v2, w = _scaffold(tmp_path, which=("validator_findings",))
    m = _build(tmp_path, w)
    persist_evaluation_output_manifest(m, eval_root=tmp_path, eval_run_id="run1")
    # A pre-runner artifact appears after the manifest was written.
    persist_assertion_outcomes((ao(),), eval_root=tmp_path, eval_run_id="run1")
    with pytest.raises(EvaluationOutputManifestError) as ei:
        load_evaluation_output_manifest("run1", eval_root=tmp_path)
    assert ei.value.reason_code == "unexpected_artifact"


# --- Persistence: write-once, round-trip, expected-hash --------------------


def test_persist_write_once(tmp_path):
    _, _, _, _, w = _scaffold(tmp_path, which=("validator_findings",))
    m = _build(tmp_path, w)
    persist_evaluation_output_manifest(m, eval_root=tmp_path, eval_run_id="run1")
    with pytest.raises(EvaluationOutputManifestError) as ei:
        persist_evaluation_output_manifest(m, eval_root=tmp_path, eval_run_id="run1")
    assert ei.value.reason_code == "artifact_exists"


def test_load_expected_hash_roundtrip_and_mismatch(tmp_path):
    _, _, _, _, w = _scaffold(tmp_path, which=("validator_findings",))
    m = _build(tmp_path, w)
    loaded = persist_evaluation_output_manifest(m, eval_root=tmp_path, eval_run_id="run1")
    ok = load_evaluation_output_manifest("run1", eval_root=tmp_path, expected_sha256=loaded.sha256)
    assert ok.model == m
    with pytest.raises(EvaluationOutputManifestError) as ei:
        load_evaluation_output_manifest("run1", eval_root=tmp_path, expected_sha256="a" * 64)
    assert ei.value.reason_code == "expected_hash_mismatch"


def test_persist_rejects_eval_run_id_mismatch(tmp_path):
    _, _, _, _, w = _scaffold(tmp_path, which=("validator_findings",))
    m = _build(tmp_path, w)
    with pytest.raises(EvaluationOutputManifestError) as ei:
        persist_evaluation_output_manifest(m, eval_root=tmp_path, eval_run_id="other")
    assert ei.value.reason_code == "persist_eval_run_id_mismatch"


# --- Loader audit re-verification ------------------------------------------


def test_loader_rejects_post_persistence_tamper(tmp_path):
    _, _, _, _, w = _scaffold(tmp_path)
    m = _build(tmp_path, w)
    persist_evaluation_output_manifest(m, eval_root=tmp_path, eval_run_id="run1")
    target = tmp_path / "run1" / "metrics" / "metric_report.v2.json"
    target.write_bytes(target.read_bytes() + b"tamper")
    with pytest.raises(EvaluationOutputManifestError) as ei:
        load_evaluation_output_manifest("run1", eval_root=tmp_path)
    assert ei.value.reason_code == "artifact_hash_mismatch"
    assert ei.value.artifact_reference == "run1/metrics/metric_report.v2.json"


def test_loader_rejects_deleted_bound_artifact(tmp_path):
    _, _, _, _, w = _scaffold(tmp_path)
    m = _build(tmp_path, w)
    persist_evaluation_output_manifest(m, eval_root=tmp_path, eval_run_id="run1")
    (tmp_path / "run1" / "assertions" / "assertion_outcomes.jsonl").unlink()
    with pytest.raises(EvaluationOutputManifestError) as ei:
        load_evaluation_output_manifest("run1", eval_root=tmp_path)
    assert ei.value.reason_code == "artifact_missing"


# --- Loader strict-JSON / security -----------------------------------------


def _manifest_path(tmp_path):
    return tmp_path / "run1" / "output_manifest" / "evaluation_output_manifest.json"


def _persisted(tmp_path):
    _, _, _, _, w = _scaffold(tmp_path, which=("validator_findings",))
    m = _build(tmp_path, w)
    persist_evaluation_output_manifest(m, eval_root=tmp_path, eval_run_id="run1")
    return _manifest_path(tmp_path)


def test_loader_rejects_bom(tmp_path):
    p = _persisted(tmp_path)
    p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())
    with pytest.raises(EvaluationOutputManifestError) as ei:
        load_evaluation_output_manifest("run1", eval_root=tmp_path)
    assert ei.value.reason_code == "bom"


def test_loader_rejects_duplicate_key(tmp_path):
    p = _persisted(tmp_path)
    text = p.read_text().rstrip("\n")
    p.write_text(text[:-1] + ', "eval_run_id": "x"}')
    with pytest.raises(EvaluationOutputManifestError) as ei:
        load_evaluation_output_manifest("run1", eval_root=tmp_path)
    assert ei.value.reason_code == "duplicate_key"


def test_loader_rejects_top_level_array(tmp_path):
    p = _persisted(tmp_path)
    p.write_text("[]")
    with pytest.raises(EvaluationOutputManifestError) as ei:
        load_evaluation_output_manifest("run1", eval_root=tmp_path)
    assert ei.value.reason_code == "top_level_type"


def test_loader_rejects_symlinked_manifest(tmp_path):
    p = _persisted(tmp_path)
    real = p.read_bytes()
    p.unlink()
    external = tmp_path / "external.json"
    external.write_bytes(real)
    p.symlink_to(external)
    with pytest.raises(EvaluationOutputManifestError) as ei:
        load_evaluation_output_manifest("run1", eval_root=tmp_path)
    assert ei.value.reason_code == "artifact_symlink"


def test_loader_rejects_missing_manifest(tmp_path):
    _scaffold(tmp_path, which=("validator_findings",))
    with pytest.raises(EvaluationOutputManifestError) as ei:
        load_evaluation_output_manifest("run1", eval_root=tmp_path)
    assert ei.value.reason_code == "artifact_missing"


def test_invalid_eval_run_id_and_root(tmp_path):
    with pytest.raises(EvaluationOutputManifestError) as ei:
        load_evaluation_output_manifest("../escape", eval_root=tmp_path)
    assert ei.value.reason_code == "invalid_eval_run_id"
    with pytest.raises(EvaluationOutputManifestError) as ej:
        load_evaluation_output_manifest("run1", eval_root=tmp_path / "does-not-exist")
    assert ej.value.reason_code == "invalid_eval_root"


# --- Import purity ---------------------------------------------------------


def test_import_no_io_no_hash_no_clock():
    code = "\n".join([
        "import sys, os, hashlib, importlib, time",
        "sys.path.insert(0, 'src')",
        "from jsonschema import Draft202012Validator, FormatChecker",
        "import pydantic",
        "import dynamic_ai_products, dynamic_ai_products.universe.models, dynamic_ai_products.universe.io_utils",
        "import dynamic_ai_products.evaluation",
        "sys.modules.pop('dynamic_ai_products.evaluation.output_manifest', None)",
        "from pathlib import Path",
        "reads=[]; writes=[]; sha=[]; clock=[]",
        "orb,ort,omk,oop,osha=Path.read_bytes,Path.read_text,Path.mkdir,os.open,hashlib.sha256",
        "ot1,ot2=time.time,time.monotonic",
        "Path.read_bytes=lambda self,*a,**k:(reads.append(str(self)),orb(self,*a,**k))[1]",
        "Path.read_text=lambda self,*a,**k:(reads.append(str(self)),ort(self,*a,**k))[1]",
        "Path.mkdir=lambda self,*a,**k:(writes.append(str(self)),omk(self,*a,**k))[1]",
        "os.open=lambda *a,**k:(writes.append('o'),oop(*a,**k))[1]",
        "hashlib.sha256=lambda *a,**k:(sha.append(1),osha(*a,**k))[1]",
        "time.time=lambda *a,**k:(clock.append(1),ot1())[1]",
        "time.monotonic=lambda *a,**k:(clock.append(1),ot2())[1]",
        "importlib.import_module('dynamic_ai_products.evaluation.output_manifest')",
        "Path.read_bytes,Path.read_text,Path.mkdir,os.open,hashlib.sha256=orb,ort,omk,oop,osha",
        "time.time,time.monotonic=ot1,ot2",
        "assert reads==[], reads",
        "assert writes==[] and sha==[] and clock==[], (writes,len(sha),len(clock))",
        "print('OK')",
    ])
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr


# --- Package export + manifest parity + protected hashes -------------------


def test_six_new_exports_present():
    for name in ("EvaluationOutputManifest", "LoadedEvaluationOutputManifest",
                 "EvaluationOutputManifestError", "build_evaluation_output_manifest",
                 "persist_evaluation_output_manifest", "load_evaluation_output_manifest"):
        assert name in evaluation_pkg.__all__
        assert getattr(evaluation_pkg, name) is getattr(om_mod, name)


def test_export_list_sorted_unique_and_count():
    # 562 = 560 + ValidatorRuleParametersV2 + load_validator_rule_parameters_v2 (ADR-028).
    assert len(evaluation_pkg.__all__) == 579
    assert evaluation_pkg.__all__ == sorted(evaluation_pkg.__all__)
    assert len(set(evaluation_pkg.__all__)) == len(evaluation_pkg.__all__)


def test_repo_manifest_count_and_paths():
    text = (ROOT / "REPO_MANIFEST.md").read_text()
    # 394 = 390 + the P2 producer, its test, and the two v0.2 fixtures (ADR-028).
    # 575 = 561 + the fourteen ADR-043 paths: three schemas, five source
    # modules and six test modules.
    # 579 = 575 + the four ADR-044 paths: the prompt-qualification schema, its
    # source module, its test module, and the tracked change request the record
    # pins by reference and digest.
    # 583 = 579 + the four ADR-045 (G2b) test modules: the v1 retirement test
    # and the three v2 modules the 178 migrated cases moved into.
    # 585 = 583 + the two ADR-047 (G3-2) paths: the canonical budget-session
    # producer and its test module.
    # 587 = 585 + the two ADR-048 (G3-3) paths: the canonical routing-contract
    # producer and its tests.
    # 589 = 587 + the two ADR-049 (G4-1) paths: the canonical governance
    # materializer and its tests.
    # 590 = 589 + the ADR-050 (G4-3) path: the G3 live smoke runbook,
    # which carries the governance-root convention and the retention policy.
    # 593 = 590 + the three ADR-052 (G6-V) paths: the product-candidate
    # availability vocabulary schema, its producer, and its test module.
    # 595 = 593 + the two ADR-053 (G6-P) paths: the schema-bound successor
    # prompt and the offline prompt-vocabulary binding test module.
    # 596 = 595 + the ADR-053 (G6-P) change request CR-0002, the tracked
    # document the successor prompt's qualification record pins.
    # 597 = 596 + the ADR-054 (G6-M) path: the candidate-conformance test
    # module for the derived identity fields and the C1-C6 gate.
    # 599 = 597 + the two ADR-055 paths: the label-citing successor prompt
    # and the change request its qualification record pins.
    # 601 = 599 + the two ADR-056 paths: the label-emitting successor prompt
    # and the change request its qualification record pins.
    # 602 = 601 + the ADR-057 path: the extraction_validation_decision_set
    # successor schema, which carries who decided and when.
    # 604 = 602 + the two ADR-059 paths: the schema-bound capability prompt
    # and the change request its qualification record pins.
    # 606 = 604 + the two ADR-064 paths: the unpadded-label capability
    # successor prompt and the change request its qualification record pins.
    # 608 = 606 + the two ADR-065 paths: the quote-bounding capability
    # successor prompt and the change request its qualification record pins.
    # 609 = 608 + the one ADR-067 path: the extraction_provider_client_contract
    # successor schema, which declares the raised output ceiling.
    # 610 = 609 + the one ADR-068 path: the task_observation successor
    # schema, which adds the normalized_task slug C3 reads.
    # 612 = 610 + the two ADR-069 paths: the schema-bound task successor
    # prompt and the change request its qualification record pins.
    # 613 = 612 + the one ADR-071 path: the extraction_validation_decision_set
    # successor schema, which carries the task kind and the Snapshot B pin.
    # 620 = 613 + the seven ADR-073 (CR-0009) paths: the schema-bound
    # consolidation prompt, its two output schemas, the packet successor
    # that carries candidate_context, the consolidation module, and the
    # change request its qualification record pins.
    # 626 = 620 + CR-0010 and the five draft-reading paths: three readings,
    # the instruction one of them was made under, and the README that records
    # why none of them is a gold record.
    # 627 = 626 + the HubSpot FY2024 adjudication record, the first
    # instance of the artefact SPEC-022 requires gold provenance to
    # reference and for which no schema exists.
    # 630 = 627 + three paths: CR-0011, which records six measured
    # AI-mechanism probes, eliminates five of them and closes at `revise`;
    # the first target registry, which gives that adjudication's decisions
    # the stable identities SPEC-022 requires because textual labels are not
    # identifiers; and the thesis execution plan that sequences the
    # FRAME_v1 -> UNIVERSE_v1 -> SAMPLE_v1 -> PCT_v1 artefact chain.
    # 638 = 630 + the eight FRAME fixture-increment paths (ADR-075): the
    # frame builder module, its manifest schema, the synthetic full-index
    # fixture bundle (manifest, three master.idx quarters, expected-frame
    # gold), and the frame-builder test file.
    # 642 = 638 + the four fixture-replay acquisition paths (ADR-076): the
    # acquisition module, its manifest schema, the declared request-plan
    # fixture, and the acquisition test file.
    # 646 = 642 + the four live-binding paths (ADR-078): the sec_live
    # transport module, the v0.2 successor manifest schema, the canonical
    # one-quarter canary request plan, and the mocked-transport live-binding
    # test file.
    # 647 = 646 + the canonical full-range request plan (ADR-078): 26
    # contiguous quarters covering the frozen FRAME filing window (ADR-077);
    # possessing the plan does not authorize a live request.
    # 654 = 647 + the seven DERA validation paths (ADR-081): the validation
    # module, its manifest schema, the synthetic FSDS SUB fixture bundle
    # (manifest, two sub TSVs, expected-validation gold), and the validation
    # test file.
    # 662 = 654 + the eight DERA acquisition paths (ADR-082): the acquisition
    # module, its v0.1 and v0.2 manifest schemas, the canonical one-release
    # canary request plan, the synthetic archive fixture bundle (plan, two
    # ZIPs), and the acquisition test file.
    # 663 = 662 + the canonical full-range DERA request plan (ADR-083): 26
    # releases covering the frozen FRAME window at the canary-verified URL
    # template; possessing the plan does not authorize a live request.
    # 664 = 663 + the committed DERA validation adjudication file (ADR-085):
    # three evidence-backed replaced-submission records; unadjudicated
    # contradictions still gate.
    # 666 = 664 + the FRAME_v1 freeze record and its guard-test file
    # (ADR-087): the freeze pins the released frame artifact and its
    # gate-passing validation evidence; data/runs stays unmodified.
    # 670 = 666 + the four W2-A baseline-carrier paths (ADR-088): the
    # Stage 00B carrier module, its manifest schema, the carrier test
    # file, and the fixture carrier gold. No exclusions are decided at
    # that stage.
    assert "Total tracked/scaffold files listed: **670**" in text
    assert "`src/dynamic_ai_products/evaluation/output_manifest.py`" in text
    assert "`tests/evaluation/test_output_manifest.py`" in text
    assert "`src/dynamic_ai_products/evaluation/validation_inputs.py`" in text
    assert "`tests/evaluation/test_validation_inputs.py`" in text
    assert (
        "`evals/fixtures/evaluation_harness/validator_parameters_v2/"
        "validator_rule_parameters.v2.json`"
    ) in text
    assert (
        "`evals/fixtures/evaluation_harness/validator_bundle_v2/"
        "validator_bundle_artifact.v2.json`"
    ) in text


def test_protected_contract_hashes_unchanged():
    assert model_contract_hash(MetricReport, "metric_report", "0.1.0") == \
        "d9e3f6d7399af628b38754758a7cb580e57955ad695ee7d92fb56c67c4ceac39"
    assert model_contract_hash(MetricReportV2, "metric_report", "0.2.0") == \
        "68cd901cec08e2d4c5b1df4dfd4b785bffa0b9675140fa1304ae2aec5006c0a4"
    assert model_contract_hash(ParsedPredictionContent, "parsed_prediction_content", "0.1.0") == \
        "ffeae7ab54fa03948f4498a3ceb5a634b17444791fd91f94a57c086afedbda3e"
    assert model_contract_hash(ValidatorFinding, "validator_finding", "0.1.0") == \
        "96f63fee300d363a662f4f956bacccdca596acfb0f22bf7039aa1335b6d61292"


# --- ADR-050 (G4-3): tracked governance documents carry no operator values ---
#
# These live here, in a module about the evaluation output manifest, because this
# file already holds the repository-document guards -- the REPO_MANIFEST count
# assertion above reads the same ROOT. They are a continuation of that family
# rather than a new one, and the scanner is a private helper of this module: no
# production code and no extra test file exist for it.
#
# What is deliberately NOT done here: a scan for the Vertex project-identifier
# grammar. Measured, that grammar matches twenty out of twenty ordinary English
# words -- "governance", "retention", "operator-managed", "runbook" -- and 203
# distinct words in a single existing operations document. A prose-wide grammar
# scan would be noise, not a guard. The four checks below are structural instead.

_GOVERNANCE_DOCS = (
    ROOT / "docs" / "operations" / "G3_LIVE_SMOKE_RUNBOOK.md",
    ROOT / "docs" / "DECISION_LOG.md",
)

# A value is acceptable in a project position only if it is an explicit
# placeholder or one of the synthetic projects the test suite already uses.
_PLACEHOLDER = re.compile(r"^(<[^>]*>|\{[^}]*\}|PROJECT|_+|x+|\.\.\.|…)$", re.IGNORECASE)
_SYNTHETIC_PROJECTS = frozenset(
    {"my-research-project", "p-example", "another-real-project", "placeholder-project-xx"}
)

# (a) a real endpoint URL names the project between "projects/" and the next "/".
_ENDPOINT = re.compile(r"projects/([^/\s`\"']+)/")
# (b) the field itself, however it is spelled in a template.
_PROJECT_FIELD = re.compile(r"vertex_project\s*[:=]\s*([^\s,)`\"']+)")
# (c) a real absolute local path. Relative repository paths are untouched.
_ABSOLUTE_LOCAL = re.compile(r"(?<![\w/])(?:/Users/|/home/|/Volumes/)\S+")
# (d) a concrete storage location: bucket URI, drive letter, or host:/path. The
# policy words themselves -- "operator-managed encrypted backup" -- match nothing
# here, which is the whole point: the shape of a location is caught, not the
# vocabulary of a policy.
_LOCATION = re.compile(r"(?<![\w])(?:s3://|gs://|az://|[A-Za-z]:\\|[\w.-]+:/[^/\s])\S*")


def _scan_project_values(pattern, text):
    """Every capture that is neither a placeholder nor a known synthetic value."""
    found = []
    for match in pattern.finditer(text):
        value = match.group(1).strip("\"'")
        if _PLACEHOLDER.match(value) or value in _SYNTHETIC_PROJECTS:
            continue
        found.append(value)
    return found


def _scan_matches(pattern, text):
    return [match.group(0) for match in pattern.finditer(text)]


def test_tracked_governance_docs_carry_no_real_endpoint_url():
    for document in _GOVERNANCE_DOCS:
        found = _scan_project_values(_ENDPOINT, document.read_text(encoding="utf-8"))
        assert found == [], f"{document.name}: {found}"


def test_tracked_governance_docs_carry_only_placeholder_project_fields():
    for document in _GOVERNANCE_DOCS:
        found = _scan_project_values(_PROJECT_FIELD, document.read_text(encoding="utf-8"))
        assert found == [], f"{document.name}: {found}"


def test_tracked_governance_docs_carry_no_absolute_local_path():
    for document in _GOVERNANCE_DOCS:
        found = _scan_matches(_ABSOLUTE_LOCAL, document.read_text(encoding="utf-8"))
        assert found == [], f"{document.name}: {found}"


def test_tracked_governance_docs_name_no_backup_or_ledger_location():
    """The policy may be described; the location may not be named."""
    for document in _GOVERNANCE_DOCS:
        text = document.read_text(encoding="utf-8")
        found = _scan_matches(_LOCATION, text)
        assert found == [], f"{document.name}: {found}"
    runbook = _GOVERNANCE_DOCS[0].read_text(encoding="utf-8")
    # The policy vocabulary must survive the scan, or the guard would be pushing
    # the documentation to say less than it should.
    assert "operator-managed encrypted backup" in runbook


@pytest.mark.parametrize(
    ("planted", "scanner"),
    [
        pytest.param(
            "https://us-central1-aiplatform.googleapis.com/v1/projects/acme-prod-1234/locations/x",
            "endpoint",
            id="real-endpoint-url",
        ),
        pytest.param("vertex_project: acme-prod-1234", "field", id="real-project-field"),
        pytest.param("backup: /Users/someone/vault/gov", "absolute", id="absolute-local-path"),
        pytest.param("backup: gs://some-bucket/gov", "location", id="bucket-location"),
        pytest.param(r"backup: C:\vault\gov", "location", id="drive-letter-location"),
    ],
)
def test_the_leak_scan_rejects_a_planted_violation(planted, scanner):
    """Sensitivity. Four checks returning zero prove nothing on their own.

    A scanner whose patterns had rotted would report a clean document forever.
    Each planted string is the violation its own check exists to catch.
    """
    # The drive-letter case is the one that would survive a "looks fine" regex.
    # An earlier revision required two literal backslashes, so a real
    # single-backslash Windows path went unnoticed; the sensitivity proof for
    # that specific regression lives in the test below, not only in a
    # NEVERMATCH mutation.
    if scanner == "endpoint":
        assert _scan_project_values(_ENDPOINT, planted) == ["acme-prod-1234"]
    elif scanner == "field":
        assert _scan_project_values(_PROJECT_FIELD, planted) == ["acme-prod-1234"]
    elif scanner == "absolute":
        assert len(_scan_matches(_ABSOLUTE_LOCAL, planted)) == 1
    else:
        assert len(_scan_matches(_LOCATION, planted)) == 1


def test_the_location_scan_still_catches_a_single_backslash_windows_path():
    """A named regression, not a generic mutation.

    The first version of ``_LOCATION`` spelled the drive-letter branch with two
    literal backslashes. That pattern matches ``C:\\\\vault`` -- an escaped
    form nobody writes in prose -- and silently misses the real thing,
    ``C:\\vault``. A NEVERMATCH mutation would not have found this: the regex
    was present, compiled, and wrong.

    Reverting only the drive-letter branch must make the planted case stop
    matching, which is what pins the fix.
    """
    planted = r"backup: C:\vault\gov"
    assert planted.count("\\") == 2, "the planted path must use single backslashes"
    assert len(_scan_matches(_LOCATION, planted)) == 1

    broken = re.compile(
        r"(?<![\w])(?:s3://|gs://|az://|[A-Za-z]:\\\\|[\w.-]+:/[^/\s])\S*"
    )
    assert broken.search(planted) is None, "the old pattern must miss it"
    # The other three branches are unaffected by the drive-letter spelling, so a
    # regression there is genuinely isolated to Windows paths.
    for unaffected in ("backup: gs://b/g", "backup: s3://b/g"):
        assert len(_scan_matches(broken, unaffected)) == 1
