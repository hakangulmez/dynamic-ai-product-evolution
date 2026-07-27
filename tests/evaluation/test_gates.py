"""Slice 10: gate evaluation and EvaluationResultV2 assembly/persistence.

Pure assessors are exercised with real Slice 9 metric reports; persistence and
loading run under ``tmp_path`` on an initialized Slice 5 run directory. Slice 10
derives execution_status + gate_verdict and never mutates findings/metrics.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import gates as gate_mod
from dynamic_ai_products.evaluation import metrics as met
from dynamic_ai_products.evaluation.cases import InvalidEvaluationRootError
from dynamic_ai_products.evaluation.case_sets import load_case_set_manifest
from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.gates import (
    EvaluationIssue,
    EvaluationResultArtifactMissingError,
    EvaluationResultArtifactNotAFileError,
    EvaluationResultArtifactReadError,
    EvaluationResultBindingError,
    EvaluationResultDecodeError,
    EvaluationResultDestinationHashMismatchError,
    EvaluationResultExistsError,
    EvaluationResultJsonError,
    EvaluationResultModelValidationError,
    EvaluationResultSchemaValidationError,
    EvaluationResultTopLevelTypeError,
    EvaluationResultWriteError,
    GateApplicabilityBindingError,
    GateCaseSetBindingError,
    GateEvaluationError,
    GateFindingsBindingError,
    GateMetricReportBindingError,
    GateMetricSelectionError,
    GatePolicyError,
    GateRunBindingError,
    GateScoringConfigBindingError,
    LoadedEvaluationResult,
    PersistedEvaluationResult,
    assess_completed_evaluation,
    build_errored_evaluation,
    build_invalid_evaluation,
    load_evaluation_result,
    persist_evaluation_result,
)
from dynamic_ai_products.evaluation.metric_inputs import build_metric_input_snapshot
from dynamic_ai_products.evaluation.models import (
    AssertionOutcome,
    EvaluationResultV2,
    EvaluationRunManifest,
    EvaluationRunManifestV2,
    ValidatorFinding,
)
from dynamic_ai_products.evaluation.references import load_target_registry
from dynamic_ai_products.evaluation.runs import (
    RunArtifactNotAFileError,
    initialize_evaluation_run,
    initialize_evaluation_run_v2,
    load_evaluation_run_manifest,
)
from dynamic_ai_products.evaluation.stage_evidence import (
    LoadedStageMetricEvidenceSet,
    build_stage_metric_evidence_set,
    stage_metric_evidence_set_hash,
)
from dynamic_ai_products.evaluation.stage_profiles import (
    load_stage_profile_registry,
    resolve_metric_applicability,
    stage_profile_registry_hash,
)
from dynamic_ai_products.evaluation.scoring_config import (
    DiagnosticDefinition,
    GateDefinition,
    LoadedScoringGateConfig,
    ScoringGateConfig,
    load_scoring_gate_config,
)
from dynamic_ai_products.evaluation.validators import LoadedValidatorFindings
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness"
CASE_SET = load_case_set_manifest("valid_base_case_set_manifest.json", eval_root=FX / "case_sets")
REGISTRY = load_target_registry("valid_target_registry.json", eval_root=FX / "configs")
SCORING = load_scoring_gate_config("valid_scoring_gate_config.json", eval_root=FX / "configs")
SP_REG = load_stage_profile_registry("stage_profiles/stage_profile_registry.json", eval_root=FX)
SP_REG_HASH = stage_profile_registry_hash(SP_REG.registry)
RM_V2_HASH = model_contract_hash(EvaluationRunManifestV2, "evaluation_run_manifest", "0.2.0")
CREATED = "2026-07-24T00:00:00+00:00"
CID = "SYNTH-CASE-0001"
HEX = "a" * 64


def _v2_rm(*, eval_run_id, case_set_version, case_set_hash, scoring_version, scoring_hash,
           stage, entry_hash, ev_ver=None, ev_hash=None):
    payload = {
        "contract": {"contract_id": "evaluation_run_manifest", "contract_version": "0.2.0",
                     "contract_hash": RM_V2_HASH},
        "eval_run_id": eval_run_id, "prediction_run_id": "P", "prediction_run_manifest_hash": HEX,
        "case_set_version": case_set_version, "case_set_hash": case_set_hash,
        "registry_snapshot_hash": HEX, "validator_bundle_version": "vb",
        "validator_bundle_hash": "b" * 64,
        "scoring_gate_config_version": scoring_version, "scoring_gate_config_hash": scoring_hash,
        "code_commit": "c", "pydantic_runtime_version": "2", "evaluation_created_at": CREATED,
        "stage_profile_registry_version": SP_REG.version,
        "stage_profile_registry_hash": SP_REG_HASH,
        "selected_stage_profile_entry_hash": entry_hash,
        "semantic_adapter_registry_version": "sa-v1", "semantic_adapter_registry_hash": HEX,
        "selected_semantic_adapter_entry_hash": HEX,
        "source_passage_snapshot_version": "sp-v1", "source_passage_snapshot_hash": HEX,
        "gold_assertion_set_version": "g-v1", "gold_assertion_set_hash": HEX,
        "axis_taxonomy_version": "ax-v1", "axis_taxonomy_hash": HEX,
        "validator_rule_parameters_version": "vp-v1", "validator_rule_parameters_hash": HEX,
    }
    if ev_ver is not None:
        payload["stage_metric_evidence_set_version"] = ev_ver
        payload["stage_metric_evidence_set_hash"] = ev_hash
    return EvaluationRunManifestV2.model_validate(payload)


def _rm_from_snapshot(snap):
    b = snap.applicability_binding
    return _v2_rm(
        eval_run_id=snap.eval_run_id, case_set_version=snap.case_set_version,
        case_set_hash=snap.case_set_hash, scoring_version=snap.scoring_gate_config_version,
        scoring_hash=snap.scoring_gate_config_hash, stage=b.evaluation_stage,
        entry_hash=b.selected_stage_profile_entry_hash,
        ev_ver=b.stage_metric_evidence_set_version, ev_hash=b.stage_metric_evidence_set_hash)
AO_META = {"contract_id": "assertion_outcome", "contract_version": "0.1.0",
           "contract_hash": model_contract_hash(AssertionOutcome, "assertion_outcome", "0.1.0")}
VF_META = {"contract_id": "validator_finding", "contract_version": "0.1.0",
           "contract_hash": model_contract_hash(ValidatorFinding, "validator_finding", "0.1.0")}

AXIS_SEL = {"aggregation": "micro", "axis_role": "product", "measure": "precision",
            "scope": "conditional", "verification": "verified"}
UNSAFE_SEL = {"measure": "weighted_upper_confidence_bound", "scope": "overall"}


# --- Builders -------------------------------------------------------------


def _diag(mid, sl):
    return DiagnosticDefinition(reference_id=f"d-{mid}-{sl}", metric_id=mid, population_slice_id=sl,
                               slice_definitions=({"minimum_verified_support": 0},))


def _s9gate(mid, sl, sup=None, ci=None, thr=None):
    return GateDefinition(reference_id=f"c-{mid}-{sl}", metric_id=mid, population_slice_id=sl,
                          verified_support_requirement=sup or {"minimum_verified_support": 0},
                          ci_method_reference=ci, blocking_severity="synth-critical",
                          protected_regression_class_references=(),
                          slice_definitions=({"s": sl},), threshold=thr or {"x": 1})


def ao(outcome="satisfied"):
    return AssertionOutcome.model_validate({"contract": AO_META, "eval_run_id": "run1",
                                            "case_id": CID, "assertion_id": "A1",
                                            "assertion_semantic_version": "0.1.0", "outcome": outcome})


def vf(finding_id="f1", severity="error", run_id="run1"):
    return ValidatorFinding.model_validate({
        "contract": VF_META, "finding_id": finding_id, "validator": "source_id_resolution",
        "validator_bundle_version": "vb", "validator_bundle_hash": "b" * 64, "rule_params_hash": HEX,
        "severity": severity, "run_id": run_id, "artifact_id": "art1", "observed_value": "x",
        "expected_invariant": "y", "message": "m", "evidence": "e", "repairable": False,
        "created_at": "2026-07-20T00:00:00Z"})


def _stage_evidence(stage, *, unsafe_min, audited_missed, pop):
    """Build the stage-appropriate evidence set (screen/classification), or None."""
    entry = resolve_metric_applicability(SP_REG.registry, stage)
    kinds = entry.required_stage_evidence_kinds
    if not kinds:
        return None
    variants = []
    if "universe_classification_tier" in kinds:
        tier = met.TierContractObservation(
            record_id="t1", verification_status="verified", tier_rule_version="v",
            expected_tier="T", observed_tier="T", expected_reason_codes=("r",),
            observed_reason_codes=("r",), expected_rule_trace_hash="c" * 64,
            observed_rule_trace_hash="c" * 64, repeatability_output_hashes=("d" * 64, "d" * 64))
        variants.append({"kind": "universe_classification_tier",
                         "tier_contract_observations": [tier.model_dump(mode="json")]})
    if "universe_screen_operational" in kinds:
        ops = met.ScreenOperationalSummary(total_screened=10, screen_negative=4, screen_nonnegative=5,
                                           unresolved=1, downstream_review_count=3)
        variants.append({"kind": "universe_screen_operational",
                         "screen_operational_summary": ops.model_dump(mode="json")})
    if "universe_unsafe_exclusion_audit" in kinds:
        labels = tuple(met.UnsafeAuditLabel(record_id=f"a{i}", verification_status="verified",
                                            actually_eligible_or_boundary_relevant=v)
                       for i, v in enumerate(audited_missed))
        aud = met.UnsafeExclusionAuditSnapshot(
            audit_snapshot_hash="b" * 64, seed=1, sampling_design_id="d",
            strata=(met.UnsafeAuditStratum(stratum_id="s1", screen_negative_population_count=pop,
                                           audited_labels=labels),))
        variants.append({"kind": "universe_unsafe_exclusion_audit",
                         "unsafe_exclusion_audit": aud.model_dump(mode="json")})
    variants.sort(key=lambda v: v["kind"])
    evset = build_stage_metric_evidence_set(evaluation_stage=stage, set_version="se-v1",
                                            variants=tuple(variants))
    return LoadedStageMetricEvidenceSet(model=evset, version="se-v1", sha256="d" * 64,
                                        artifact_reference="stage_evidence/e.json")


def build_report(root, rm, *, stage="universe_classification", axis_min=0, unsafe_min=1,
                 audited_missed=(False,), pop=100):
    """Compute an in-memory stage-aware ``LoadedMetricReport`` (v0.2 metric path).

    ``rm`` (a v0.1 gate manifest) supplies the case-set / scoring / run identity;
    the v0.2 metric contract is built internally. Not persisted — the gate engine
    consumes the returned ``LoadedMetricReport`` directly. ``universe_classification``
    provides axis + tier families; ``universe_screen`` provides screen-operational
    + unsafe-exclusion.
    """
    entry = resolve_metric_applicability(SP_REG.registry, stage)
    ev = _stage_evidence(stage, unsafe_min=unsafe_min, audited_missed=audited_missed, pop=pop)
    ev_ver = ev.model.set_version if ev is not None else None
    ev_hash = stage_metric_evidence_set_hash(ev.model) if ev is not None else None
    local_rm = _v2_rm(
        eval_run_id="run1", case_set_version=rm.case_set_version, case_set_hash=rm.case_set_hash,
        scoring_version=rm.scoring_gate_config_version, scoring_hash=rm.scoring_gate_config_hash,
        stage=stage, entry_hash=entry.entry_hash, ev_ver=ev_ver, ev_hash=ev_hash)
    axis = met.AxisDefinition(axis_id="axis-1", axis_role="product", metric_type="abstention_allowed",
                              base_metric_type="multi_label", labels=("a", "b"))
    ex = (met.ValidatorRuleEvaluationRecord(artifact_id="art1", rule_id="source_id_resolution",
                                            evaluated_observation_count=5, failed_observation_count=1),)
    snap = build_metric_input_snapshot(
        evaluation_stage=stage, stage_profile_registry=SP_REG, run_manifest=local_rm,
        axis_definitions=(axis,),
        axis_records=(met.AxisEvaluationRecord(record_id="r1", case_id=CID, axis_id="axis-1",
            metric_scope="conditional", verification_status="verified",
            evidence_resolvability="resolvable", predicted_values=("a",), gold_values=("a",)),),
        assertion_bindings=(met.AssertionMetricBinding(case_id=CID, assertion_id="A1",
            assertion_kind="expected_entity", partition="dev", suites=("adversarial", "regression")),),
        validator_rule_evaluations=ex, stage_evidence=ev)
    scfg = ScoringGateConfig(config_version=rm.scoring_gate_config_version,
        blocking_severities=("synth-critical",), protected_regression_classes=(),
        gates=(_s9gate(met.METRIC_TIER_CONTRACT, "overall"),
               _s9gate(met.METRIC_UNSAFE_EXCLUSION, "overall", {"minimum_audited_per_stratum": unsafe_min},
                       "wilson_one_sided_stratified", {"confidence_level": 0.95}),
               _s9gate(met.METRIC_AXIS_MULTI_LABEL, "axis-1", {"minimum_verified_support": axis_min})),
        diagnostics=(_diag(met.METRIC_ASSERTION_OUTCOMES, "overall"),
                     _diag(met.METRIC_VALIDATOR_RULES, "overall"),
                     _diag(met.METRIC_VALIDATOR_SUMMARIES, "overall"),
                     _diag(met.METRIC_SCREEN_OPERATIONAL, "overall"),
                     _diag(met.METRIC_AXIS_ABSTENTION, "axis-1")))
    run_rm = _rm_from_snapshot(snap)
    lc = LoadedScoringGateConfig(config=scfg, version=run_rm.scoring_gate_config_version,
                                 sha256=run_rm.scoring_gate_config_hash, artifact_reference="x")
    rep = met.compute_metric_report(snap, assertion_outcomes=(ao(),), validator_findings=(vf(),),
                                    run_manifest=run_rm, case_set_manifest=CASE_SET, scoring_config=lc)
    return met.LoadedMetricReport(
        eval_run_id="run1", artifact_reference="run1/metrics/metric_report.json",
        sha256=sha256_bytes(met._canonical_report_bytes(rep)), report=rep)


def exec_gate(mid, sl, *, operator, value, sel, support, ci=None, confidence_level=None,
              blocking="synth-critical", ref=None):
    thr = {"operator": operator, "value": value}
    if confidence_level is not None:
        thr["confidence_level"] = confidence_level
    return GateDefinition(reference_id=ref or f"g-{mid}-{sl}", metric_id=mid, population_slice_id=sl,
                          verified_support_requirement=support, ci_method_reference=ci,
                          blocking_severity=blocking, protected_regression_class_references=(),
                          slice_definitions=({"dimensions": sel},), threshold=thr)


def exec_config(rm, gates, *, severities=("synth-critical",)):
    cfg = ScoringGateConfig(config_version=rm.scoring_gate_config_version,
                            blocking_severities=severities, protected_regression_classes=(),
                            gates=tuple(gates), diagnostics=())
    return LoadedScoringGateConfig(config=cfg, version=rm.scoring_gate_config_version,
                                   sha256=rm.scoring_gate_config_hash, artifact_reference="x")


def loaded_findings(*findings, run_id="run1", sha=None):
    return LoadedValidatorFindings(eval_run_id=run_id,
                                   artifact_reference="findings/validator_findings.jsonl",
                                   sha256=sha or "e" * 64, findings=tuple(findings))


@pytest.fixture
def ctx(tmp_path):
    initialize_evaluation_run(eval_root=tmp_path, eval_run_id="run1", prediction_run_id="P",
        prediction_run_manifest_hash="a" * 64, case_set=CASE_SET, registry=REGISTRY,
        validator_bundle_version="vb", validator_bundle_hash="b" * 64, scoring_config=SCORING,
        code_commit="c", config_snapshot_source_root=FX / "configs")
    rm = load_evaluation_run_manifest("run1", eval_root=tmp_path).manifest
    report = build_report(tmp_path, rm)
    return tmp_path, rm, report


def assess(ctx, *, gates, findings=None, stage="task_extraction", report=None):
    tmp_path, rm, rep = ctx
    return assess_completed_evaluation(
        stage=stage, run_manifest=rm, case_set_manifest=CASE_SET,
        scoring_config=exec_config(rm, gates), metric_report=report or rep,
        findings=findings if findings is not None else loaded_findings(vf()))


def screen_report(ctx, *, unsafe_min=1, audited_missed=(False,), pop=100):
    """A screen-stage metric report (screen-operational + unsafe-exclusion families)."""
    tmp_path, rm, _ = ctx
    return build_report(tmp_path, rm, stage="universe_screen", unsafe_min=unsafe_min,
                        audited_missed=audited_missed, pop=pop)


def build_report_v2(root, rm, *, stage="universe_classification", axis_min=0, unsafe_min=1,
                    audited_missed=(False,), pop=100):
    """Compute an in-memory ``_LoadedMetricReportV2`` (v0.2 report with an
    applicability ledger) — the exact wrapper type ``load_metric_report_v2``
    returns — via the public ``compute_metric_report_v2`` producer."""
    entry = resolve_metric_applicability(SP_REG.registry, stage)
    ev = _stage_evidence(stage, unsafe_min=unsafe_min, audited_missed=audited_missed, pop=pop)
    ev_ver = ev.model.set_version if ev is not None else None
    ev_hash = stage_metric_evidence_set_hash(ev.model) if ev is not None else None
    local_rm = _v2_rm(
        eval_run_id="run1", case_set_version=rm.case_set_version, case_set_hash=rm.case_set_hash,
        scoring_version=rm.scoring_gate_config_version, scoring_hash=rm.scoring_gate_config_hash,
        stage=stage, entry_hash=entry.entry_hash, ev_ver=ev_ver, ev_hash=ev_hash)
    axis = met.AxisDefinition(axis_id="axis-1", axis_role="product", metric_type="abstention_allowed",
                              base_metric_type="multi_label", labels=("a", "b"))
    ex = (met.ValidatorRuleEvaluationRecord(artifact_id="art1", rule_id="source_id_resolution",
                                            evaluated_observation_count=5, failed_observation_count=1),)
    snap = build_metric_input_snapshot(
        evaluation_stage=stage, stage_profile_registry=SP_REG, run_manifest=local_rm,
        axis_definitions=(axis,),
        axis_records=(met.AxisEvaluationRecord(record_id="r1", case_id=CID, axis_id="axis-1",
            metric_scope="conditional", verification_status="verified",
            evidence_resolvability="resolvable", predicted_values=("a",), gold_values=("a",)),),
        assertion_bindings=(met.AssertionMetricBinding(case_id=CID, assertion_id="A1",
            assertion_kind="expected_entity", partition="dev", suites=("adversarial", "regression")),),
        validator_rule_evaluations=ex, stage_evidence=ev)
    scfg = ScoringGateConfig(config_version=rm.scoring_gate_config_version,
        blocking_severities=("synth-critical",), protected_regression_classes=(),
        gates=(_s9gate(met.METRIC_TIER_CONTRACT, "overall"),
               _s9gate(met.METRIC_UNSAFE_EXCLUSION, "overall", {"minimum_audited_per_stratum": unsafe_min},
                       "wilson_one_sided_stratified", {"confidence_level": 0.95}),
               _s9gate(met.METRIC_AXIS_MULTI_LABEL, "axis-1", {"minimum_verified_support": axis_min})),
        diagnostics=(_diag(met.METRIC_ASSERTION_OUTCOMES, "overall"),
                     _diag(met.METRIC_VALIDATOR_RULES, "overall"),
                     _diag(met.METRIC_VALIDATOR_SUMMARIES, "overall"),
                     _diag(met.METRIC_SCREEN_OPERATIONAL, "overall"),
                     _diag(met.METRIC_AXIS_ABSTENTION, "axis-1")))
    run_rm = _rm_from_snapshot(snap)
    lc = LoadedScoringGateConfig(config=scfg, version=run_rm.scoring_gate_config_version,
                                 sha256=run_rm.scoring_gate_config_hash, artifact_reference="x")
    rep = met.compute_metric_report_v2(snap, assertion_outcomes=(ao(),), validator_findings=(vf(),),
        run_manifest=run_rm, case_set_manifest=CASE_SET, scoring_config=lc,
        stage_profile_registry=SP_REG)
    return met._LoadedMetricReportV2(
        eval_run_id="run1", artifact_reference="run1/metrics/metric_report.v2.json",
        sha256=sha256_bytes(rep.model_dump_json(exclude_unset=True).encode()), report=rep)


# --- Completed status and verdict -----------------------------------------


def test_completed_pass(ctx):
    # micro precision verified conditional == 1.0; GE 0.5 -> pass; unsafe upper<=0.99 -> pass
    r = assess(ctx, gates=[
        exec_gate(met.METRIC_AXIS_MULTI_LABEL, "axis-1", operator="greater_than_or_equal",
                  value=0.5, sel=AXIS_SEL, support={"minimum_verified_support": 0})])
    assert r.execution_status == "completed" and r.gate_verdict == "pass"
    assert r.metrics["gate_outcomes"][0]["outcome"] == "pass"
    assert r.metrics["critical_finding_ids"] == []
    assert "aggregate" not in r.metrics  # no aggregate score


def test_completed_fail_metric(ctx):
    # micro precision 1.0; LE 0.5 -> 1.0 <= 0.5 False -> fail
    r = assess(ctx, gates=[
        exec_gate(met.METRIC_AXIS_MULTI_LABEL, "axis-1", operator="less_than_or_equal",
                  value=0.5, sel=AXIS_SEL, support={"minimum_verified_support": 0})])
    assert r.execution_status == "completed" and r.gate_verdict == "fail"


def test_completed_fail_critical_finding(ctx):
    r = assess(ctx, gates=[
        exec_gate(met.METRIC_AXIS_MULTI_LABEL, "axis-1", operator="greater_than_or_equal",
                  value=0.5, sel=AXIS_SEL, support={"minimum_verified_support": 0})],
        findings=loaded_findings(vf(severity="critical")))
    assert r.gate_verdict == "fail"
    assert r.metrics["critical_finding_ids"] == ["f1"]


def test_fail_outranks_indeterminate(ctx):
    tmp_path, rm, _ = ctx
    # screen report: unsafe with min_audited=5 but 1 audited -> indeterminate gate;
    # a critical finding forces fail -> fail outranks indeterminate.
    report = build_report(tmp_path, rm, stage="universe_screen", unsafe_min=5,
                          audited_missed=(False,))
    r = assess_completed_evaluation(stage="universe_screen", run_manifest=rm,
        case_set_manifest=CASE_SET,
        scoring_config=exec_config(rm, [
            exec_gate(met.METRIC_UNSAFE_EXCLUSION, "overall", operator="less_than_or_equal",
                      value=0.99, sel=UNSAFE_SEL, support={"minimum_audited_per_stratum": 5},
                      confidence_level=0.95, ci="wilson_one_sided_stratified")]),
        metric_report=report, findings=loaded_findings(vf(severity="critical")))
    assert r.gate_verdict == "fail"  # critical fail + indeterminate gate -> fail


def test_completed_indeterminate_low_support(ctx):
    tmp_path, rm, _ = ctx
    report = build_report(tmp_path, rm, stage="universe_screen", unsafe_min=5,
                          audited_missed=(False,))
    r = assess_completed_evaluation(stage="universe_screen", run_manifest=rm,
        case_set_manifest=CASE_SET,
        scoring_config=exec_config(rm, [
            exec_gate(met.METRIC_UNSAFE_EXCLUSION, "overall", operator="less_than_or_equal",
                      value=0.99, sel=UNSAFE_SEL, support={"minimum_audited_per_stratum": 5},
                      confidence_level=0.95, ci="wilson_one_sided_stratified")]),
        metric_report=report, findings=loaded_findings(vf()))
    assert r.execution_status == "completed" and r.gate_verdict == "indeterminate"
    outcome = r.metrics["gate_outcomes"][0]
    assert outcome["outcome"] == "indeterminate" and outcome["observed_value"] is None
    assert outcome["reason_code"] == "insufficient_audit_evidence"


def test_completed_no_gates_no_critical_pass(ctx):
    r = assess(ctx, gates=[], findings=loaded_findings())
    assert r.execution_status == "completed" and r.gate_verdict == "pass"
    assert r.metrics["gate_outcomes"] == []


# --- Grammar and selection ------------------------------------------------


def test_synthetic_fixture_rejected_as_policy(ctx):
    tmp_path, rm, rep = ctx
    # The committed synthetic fixture uses synth_* keys and no dimensions selector.
    # SCORING.config_version != rm version -> scoring binding fails first; align to isolate policy.
    aligned = SCORING.config.model_copy(update={"config_version": rm.scoring_gate_config_version})
    wrapper = LoadedScoringGateConfig(config=aligned, version=rm.scoring_gate_config_version,
                                      sha256=rm.scoring_gate_config_hash, artifact_reference="x")
    with pytest.raises(GatePolicyError):
        assess_completed_evaluation(stage="s", run_manifest=rm, case_set_manifest=CASE_SET,
            scoring_config=wrapper, metric_report=rep, findings=loaded_findings(vf()))


def test_malformed_support_key(ctx):
    with pytest.raises(GatePolicyError):
        assess(ctx, gates=[exec_gate(met.METRIC_AXIS_MULTI_LABEL, "axis-1",
            operator="greater_than_or_equal", value=0.5, sel=AXIS_SEL,
            support={"wrong_key": 0})])


def test_malformed_threshold_key(ctx):
    tmp_path, rm, rep = ctx
    g = GateDefinition(reference_id="g", metric_id=met.METRIC_AXIS_MULTI_LABEL,
        population_slice_id="axis-1", verified_support_requirement={"minimum_verified_support": 0},
        ci_method_reference=None, blocking_severity="synth-critical",
        protected_regression_class_references=(), slice_definitions=({"dimensions": AXIS_SEL},),
        threshold={"operator": "less_than_or_equal", "value": 0.5, "extra": 1})
    with pytest.raises(GatePolicyError):
        assess(ctx, gates=[g])


def test_unsupported_operator(ctx):
    with pytest.raises(GatePolicyError):
        assess(ctx, gates=[exec_gate(met.METRIC_AXIS_MULTI_LABEL, "axis-1",
            operator="equals", value=0.5, sel=AXIS_SEL, support={"minimum_verified_support": 0})])


def test_bool_threshold_rejected(ctx):
    with pytest.raises(GatePolicyError):
        assess(ctx, gates=[exec_gate(met.METRIC_AXIS_MULTI_LABEL, "axis-1",
            operator="less_than_or_equal", value=True, sel=AXIS_SEL,
            support={"minimum_verified_support": 0})])


def test_blocking_severity_absent_from_config_list(ctx):
    with pytest.raises(GatePolicyError):
        assess(ctx, gates=[exec_gate(met.METRIC_AXIS_MULTI_LABEL, "axis-1",
            operator="greater_than_or_equal", value=0.5, sel=AXIS_SEL,
            support={"minimum_verified_support": 0}, blocking="not-declared")])


def test_zero_candidate_selection(ctx):
    bad = dict(AXIS_SEL, axis_role="capability")  # no gate_input datum for this axis_role
    with pytest.raises(GateMetricSelectionError):
        assess(ctx, gates=[exec_gate(met.METRIC_AXIS_MULTI_LABEL, "axis-1",
            operator="greater_than_or_equal", value=0.5, sel=bad,
            support={"minimum_verified_support": 0})])


def test_malformed_selector_outer_shape(ctx):
    tmp_path, rm, rep = ctx
    g = GateDefinition(reference_id="g", metric_id=met.METRIC_AXIS_MULTI_LABEL,
        population_slice_id="axis-1", verified_support_requirement={"minimum_verified_support": 0},
        ci_method_reference=None, blocking_severity="synth-critical",
        protected_regression_class_references=(), slice_definitions=({"nope": AXIS_SEL},),
        threshold={"operator": "greater_than_or_equal", "value": 0.5})
    with pytest.raises(GatePolicyError):
        assess(ctx, gates=[g])


def test_blank_selector_dimension(ctx):
    with pytest.raises(GatePolicyError):
        assess(ctx, gates=[exec_gate(met.METRIC_AXIS_MULTI_LABEL, "axis-1",
            operator="greater_than_or_equal", value=0.5, sel={"measure": ""},
            support={"minimum_verified_support": 0})])


def test_subset_matching_rejected(ctx):
    # A partial selector (subset of the datum dims) matches zero -> selection error
    with pytest.raises(GateMetricSelectionError):
        assess(ctx, gates=[exec_gate(met.METRIC_AXIS_MULTI_LABEL, "axis-1",
            operator="greater_than_or_equal", value=0.5,
            sel={"measure": "precision"}, support={"minimum_verified_support": 0})])


def test_provisional_selection_rejected(ctx):
    prov = dict(AXIS_SEL, verification="provisional")
    with pytest.raises(GateMetricSelectionError):
        assess(ctx, gates=[exec_gate(met.METRIC_AXIS_MULTI_LABEL, "axis-1",
            operator="greater_than_or_equal", value=0.5, sel=prov,
            support={"minimum_verified_support": 0})])


def test_no_verification_dimension_selection(ctx):
    # unsafe upper-bound datum has no verification dimension -> selector omits it
    r = assess(ctx, report=screen_report(ctx), gates=[exec_gate(met.METRIC_UNSAFE_EXCLUSION,
        "overall", operator="less_than_or_equal", value=0.99, sel=UNSAFE_SEL,
        support={"minimum_audited_per_stratum": 1}, confidence_level=0.95,
        ci="wilson_one_sided_stratified")])
    assert r.gate_verdict == "pass"


def test_support_minimum_mismatch_rejected(ctx):
    # datum support.minimum_verified_support == 0 (Slice 9 axis_min default); config says 3
    with pytest.raises(GateMetricSelectionError):
        assess(ctx, gates=[exec_gate(met.METRIC_AXIS_MULTI_LABEL, "axis-1",
            operator="greater_than_or_equal", value=0.5, sel=AXIS_SEL,
            support={"minimum_verified_support": 3})])


def test_two_gates_cannot_select_the_same_metric_datum(ctx):
    # Two distinct gates (distinct reference_id) with identical metric_id,
    # population_slice_id and dimensions selector both resolve to the single
    # valid gate-input datum. The second consumption trips the duplicate
    # selected-datum invariant -- not a duplicate reference id, malformed
    # policy, zero candidates, multiple candidates or a binding mismatch.
    g1 = exec_gate(met.METRIC_AXIS_MULTI_LABEL, "axis-1", operator="greater_than_or_equal",
                   value=0.5, sel=AXIS_SEL, support={"minimum_verified_support": 0}, ref="gate-A")
    g2 = exec_gate(met.METRIC_AXIS_MULTI_LABEL, "axis-1", operator="less_than_or_equal",
                   value=0.9, sel=AXIS_SEL, support={"minimum_verified_support": 0}, ref="gate-B")
    assert g1.reference_id != g2.reference_id
    with pytest.raises(GateMetricSelectionError) as exc:
        assess(ctx, gates=[g1, g2])
    # candidate_count is None only on the already-selected path (zero -> 0, multiple -> N).
    assert type(exc.value) is GateMetricSelectionError
    assert exc.value.candidate_count is None
    assert "already-selected" in str(exc.value)
    assert exc.value.gate_reference_id == "gate-B"


# --- Gate math ------------------------------------------------------------


def test_le_equality_passes(ctx):
    # precision 1.0; LE 1.0 -> equality passes
    r = assess(ctx, gates=[exec_gate(met.METRIC_AXIS_MULTI_LABEL, "axis-1",
        operator="less_than_or_equal", value=1.0, sel=AXIS_SEL,
        support={"minimum_verified_support": 0})])
    assert r.gate_verdict == "pass"


def test_ge_equality_passes(ctx):
    r = assess(ctx, gates=[exec_gate(met.METRIC_AXIS_MULTI_LABEL, "axis-1",
        operator="greater_than_or_equal", value=1.0, sel=AXIS_SEL,
        support={"minimum_verified_support": 0})])
    assert r.gate_verdict == "pass"


# --- Unsafe ---------------------------------------------------------------


def test_unsafe_computed_pass_value_equals_ci_upper(ctx):
    r = assess(ctx, report=screen_report(ctx), gates=[exec_gate(met.METRIC_UNSAFE_EXCLUSION,
        "overall", operator="less_than_or_equal", value=0.99, sel=UNSAFE_SEL,
        support={"minimum_audited_per_stratum": 1}, confidence_level=0.95,
        ci="wilson_one_sided_stratified")])
    o = r.metrics["gate_outcomes"][0]
    assert o["outcome"] == "pass" and o["observed_value"] == o["confidence_interval"]["upper"]


def test_unsafe_fail(ctx):
    r = assess(ctx, report=screen_report(ctx), gates=[exec_gate(met.METRIC_UNSAFE_EXCLUSION,
        "overall", operator="less_than_or_equal", value=0.1, sel=UNSAFE_SEL,
        support={"minimum_audited_per_stratum": 1}, confidence_level=0.95,
        ci="wilson_one_sided_stratified")])
    assert r.gate_verdict == "fail"


def test_unsafe_confidence_level_mismatch(ctx):
    with pytest.raises(GateMetricSelectionError):
        assess(ctx, gates=[exec_gate(met.METRIC_UNSAFE_EXCLUSION, "overall",
            operator="less_than_or_equal", value=0.99, sel=UNSAFE_SEL,
            support={"minimum_audited_per_stratum": 1}, confidence_level=0.9,
            ci="wilson_one_sided_stratified")])


def test_unsafe_missing_ci_method_reference(ctx):
    with pytest.raises(GatePolicyError):
        assess(ctx, gates=[exec_gate(met.METRIC_UNSAFE_EXCLUSION, "overall",
            operator="less_than_or_equal", value=0.99, sel=UNSAFE_SEL,
            support={"minimum_audited_per_stratum": 1}, confidence_level=0.95, ci=None)])


def test_unsafe_wrong_selector(ctx):
    with pytest.raises(GatePolicyError):
        assess(ctx, gates=[exec_gate(met.METRIC_UNSAFE_EXCLUSION, "overall",
            operator="less_than_or_equal", value=0.99, sel={"measure": "weighted_unsafe_exclusion_rate", "scope": "overall"},
            support={"minimum_audited_per_stratum": 1}, confidence_level=0.95,
            ci="wilson_one_sided_stratified")])


# --- Findings -------------------------------------------------------------


def test_findings_wrapper_run_mismatch(ctx):
    with pytest.raises(GateFindingsBindingError):
        assess(ctx, gates=[], findings=loaded_findings(vf(), run_id="other"))


def test_finding_run_mismatch(ctx):
    with pytest.raises(GateFindingsBindingError):
        assess(ctx, gates=[], findings=loaded_findings(vf(run_id="other")))


def test_duplicate_finding_id(ctx):
    with pytest.raises(GateFindingsBindingError):
        assess(ctx, gates=[], findings=loaded_findings(vf("f1"), vf("f1")))


def test_error_warning_info_findings_do_not_fail(ctx):
    r = assess(ctx, gates=[], findings=loaded_findings(vf("f1", "error"), vf("f2", "warning"),
                                                       vf("f3", "info")))
    assert r.gate_verdict == "pass" and r.metrics["critical_finding_ids"] == []


def test_critical_finding_ids_sorted_unique(ctx):
    r = assess(ctx, gates=[], findings=loaded_findings(vf("f3", "critical"), vf("f1", "critical"),
                                                       vf("f2", "error")))
    assert r.metrics["critical_finding_ids"] == ["f1", "f3"]


# --- Constructors and projection ------------------------------------------


def _construct_with_stage(ctx, stage):
    """Exercise the stage contract on each of the three public constructors."""
    tmp_path, rm, rep = ctx
    completed = assess(ctx, gates=[], stage=stage)
    invalid = build_invalid_evaluation(stage=stage, run_manifest=rm,
        issues=(EvaluationIssue(issue_code="artifact_missing", message="m"),))
    errored = build_errored_evaluation(stage=stage, run_manifest=rm,
        issues=(EvaluationIssue(issue_code="runtime_failure", message="m"),))
    return completed, invalid, errored


def test_stage_stored_verbatim(ctx):
    for r in _construct_with_stage(ctx, "task_extraction"):
        assert r.stage == "task_extraction"


def test_padded_nonblank_stage_accepted_and_preserved(ctx):
    # Leading/trailing whitespace is allowed when the stripped value is nonempty;
    # the original string is preserved exactly, with no stripping.
    for r in _construct_with_stage(ctx, "  padded stage  "):
        assert r.stage == "  padded stage  "


def test_empty_stage_rejected(ctx):
    tmp_path, rm, rep = ctx
    with pytest.raises(EvaluationResultModelValidationError):
        assess(ctx, gates=[], stage="")
    with pytest.raises(EvaluationResultModelValidationError):
        build_invalid_evaluation(stage="", run_manifest=rm,
            issues=(EvaluationIssue(issue_code="artifact_missing", message="m"),))
    with pytest.raises(EvaluationResultModelValidationError):
        build_errored_evaluation(stage="", run_manifest=rm,
            issues=(EvaluationIssue(issue_code="runtime_failure", message="m"),))


def test_whitespace_only_stage_rejected(ctx):
    tmp_path, rm, rep = ctx
    with pytest.raises(EvaluationResultModelValidationError):
        assess(ctx, gates=[], stage="   ")
    with pytest.raises(EvaluationResultModelValidationError):
        build_invalid_evaluation(stage="   ", run_manifest=rm,
            issues=(EvaluationIssue(issue_code="artifact_missing", message="m"),))
    with pytest.raises(EvaluationResultModelValidationError):
        build_errored_evaluation(stage="\t\n", run_manifest=rm,
            issues=(EvaluationIssue(issue_code="runtime_failure", message="m"),))


def test_non_string_stage_rejected(ctx):
    tmp_path, rm, rep = ctx
    with pytest.raises(EvaluationResultModelValidationError):
        assess(ctx, gates=[], stage=123)
    with pytest.raises(EvaluationResultModelValidationError):
        build_invalid_evaluation(stage=None, run_manifest=rm,
            issues=(EvaluationIssue(issue_code="artifact_missing", message="m"),))
    with pytest.raises(EvaluationResultModelValidationError):
        build_errored_evaluation(stage=object(), run_manifest=rm,
            issues=(EvaluationIssue(issue_code="runtime_failure", message="m"),))


def test_stage_error_is_caught_by_public_base_but_is_concrete(ctx):
    # GateEvaluationError is the abstract public parent; the concrete raised type
    # is EvaluationResultModelValidationError, which it catches by inheritance.
    assert issubclass(EvaluationResultModelValidationError, GateEvaluationError)
    with pytest.raises(GateEvaluationError) as exc:
        assess(ctx, gates=[], stage="   ")
    assert type(exc.value) is EvaluationResultModelValidationError
    assert exc.value.field_locations == ("stage",)


def test_dataset_version_from_run_manifest(ctx):
    tmp_path, rm, rep = ctx
    r = assess(ctx, gates=[])
    assert r.dataset_version == rm.case_set_version


def test_completed_omits_errors_created_at_notes(ctx):
    r = assess(ctx, gates=[])
    keys = set(r.model_dump(mode="json", exclude_unset=True))
    assert keys == {"eval_run_id", "stage", "dataset_version", "metrics", "execution_status",
                    "gate_verdict"}


def test_invalid_errors_present_and_sorted(ctx):
    tmp_path, rm, rep = ctx
    issues = (EvaluationIssue(issue_code="gate_policy_invalid", message="z"),
              EvaluationIssue(issue_code="artifact_missing", message="a", artifact_reference="x.json"))
    r = build_invalid_evaluation(stage="s", run_manifest=rm, issues=issues)
    assert r.execution_status == "invalid" and r.gate_verdict is None
    assert [e["issue_code"] for e in r.errors] == ["artifact_missing", "gate_policy_invalid"]


def test_errored_only_runtime_failure(ctx):
    tmp_path, rm, rep = ctx
    r = build_errored_evaluation(stage="s", run_manifest=rm,
                                 issues=(EvaluationIssue(issue_code="runtime_failure", message="x"),))
    assert r.execution_status == "errored" and r.gate_verdict is None
    with pytest.raises(EvaluationResultBindingError) as exc:
        build_errored_evaluation(stage="s", run_manifest=rm,
                                 issues=(EvaluationIssue(issue_code="artifact_missing", message="x"),))
    assert type(exc.value) is EvaluationResultBindingError


def test_invalid_rejects_non_governed_code(ctx):
    tmp_path, rm, rep = ctx
    with pytest.raises(EvaluationResultBindingError) as exc:
        build_invalid_evaluation(stage="s", run_manifest=rm,
                                 issues=(EvaluationIssue(issue_code="runtime_failure", message="x"),))
    assert type(exc.value) is EvaluationResultBindingError


def test_duplicate_issue_rejected(ctx):
    tmp_path, rm, rep = ctx
    dup = (EvaluationIssue(issue_code="gate_policy_invalid", message="m"),
           EvaluationIssue(issue_code="gate_policy_invalid", message="m"))
    with pytest.raises(EvaluationResultBindingError) as exc:
        build_invalid_evaluation(stage="s", run_manifest=rm, issues=dup)
    assert type(exc.value) is EvaluationResultBindingError


def test_issue_rejects_absolute_reference():
    with pytest.raises(Exception):
        EvaluationIssue(issue_code="artifact_missing", message="m", artifact_reference="/etc/x")
    with pytest.raises(Exception):
        EvaluationIssue(issue_code="artifact_missing", message="m", artifact_reference="../x")


def test_invalid_metric_report_hash_null_or_known(ctx):
    tmp_path, rm, rep = ctx
    r = build_invalid_evaluation(stage="s", run_manifest=rm,
                                 issues=(EvaluationIssue(issue_code="artifact_malformed", message="m"),))
    assert r.metrics["provenance"]["metric_report_sha256"] is None
    r2 = build_invalid_evaluation(stage="s", run_manifest=rm,
        issues=(EvaluationIssue(issue_code="artifact_malformed", message="m"),),
        metric_report_sha256="c" * 64)
    assert r2.metrics["provenance"]["metric_report_sha256"] == "c" * 64


def test_metrics_exact_three_keys_and_provenance_five(ctx):
    r = assess(ctx, gates=[])
    assert set(r.metrics) == {"provenance", "gate_outcomes", "critical_finding_ids"}
    assert set(r.metrics["provenance"]) == {"case_set_version", "case_set_hash",
        "scoring_gate_config_version", "scoring_gate_config_hash", "metric_report_sha256"}


# --- Binding --------------------------------------------------------------


def test_case_set_hash_binding(ctx):
    tmp_path, rm, rep = ctx
    tampered = CASE_SET.model_copy(update={"registry_snapshot_version": "tampered-v9"})
    with pytest.raises(GateCaseSetBindingError):
        assess_completed_evaluation(stage="s", run_manifest=rm, case_set_manifest=tampered,
            scoring_config=exec_config(rm, []), metric_report=rep, findings=loaded_findings(vf()))


def test_scoring_wrapper_version_binding(ctx):
    tmp_path, rm, rep = ctx
    cfg = ScoringGateConfig(config_version=rm.scoring_gate_config_version,
        blocking_severities=("synth-critical",), protected_regression_classes=(), gates=(), diagnostics=())
    bad = LoadedScoringGateConfig(config=cfg, version="wrong", sha256=rm.scoring_gate_config_hash,
                                  artifact_reference="x")
    with pytest.raises(GateScoringConfigBindingError):
        assess_completed_evaluation(stage="s", run_manifest=rm, case_set_manifest=CASE_SET,
            scoring_config=bad, metric_report=rep, findings=loaded_findings(vf()))


def test_scoring_hash_binding(ctx):
    tmp_path, rm, rep = ctx
    cfg = ScoringGateConfig(config_version=rm.scoring_gate_config_version,
        blocking_severities=("synth-critical",), protected_regression_classes=(), gates=(), diagnostics=())
    bad = LoadedScoringGateConfig(config=cfg, version=rm.scoring_gate_config_version, sha256="f" * 64,
                                  artifact_reference="x")
    with pytest.raises(GateScoringConfigBindingError):
        assess_completed_evaluation(stage="s", run_manifest=rm, case_set_manifest=CASE_SET,
            scoring_config=bad, metric_report=rep, findings=loaded_findings(vf()))


def test_metric_report_binding_mismatch(tmp_path):
    initialize_evaluation_run(eval_root=tmp_path, eval_run_id="run1", prediction_run_id="P",
        prediction_run_manifest_hash="a" * 64, case_set=CASE_SET, registry=REGISTRY,
        validator_bundle_version="vb", validator_bundle_hash="b" * 64, scoring_config=SCORING,
        code_commit="c", config_snapshot_source_root=FX / "configs")
    rm = load_evaluation_run_manifest("run1", eval_root=tmp_path).manifest
    rep = build_report(tmp_path, rm)
    bad_report = rep.model_copy(update={"report": rep.report.model_copy(update={"eval_run_id": "other"})})
    with pytest.raises(GateMetricReportBindingError):
        assess_completed_evaluation(stage="s", run_manifest=rm, case_set_manifest=CASE_SET,
            scoring_config=exec_config(rm, []), metric_report=bad_report, findings=loaded_findings(vf()))


def test_metric_report_wrapper_run_binding(ctx):
    # The loaded wrapper declares a run that disagrees with the run-manifest
    # anchor, while its inner report stays self-consistent -> run-identity error.
    tmp_path, rm, rep = ctx
    bad_wrapper = rep.model_copy(update={"eval_run_id": "other-run"})
    assert bad_wrapper.report.eval_run_id == rm.eval_run_id  # inner untouched
    with pytest.raises(GateRunBindingError):
        assess_completed_evaluation(stage="s", run_manifest=rm, case_set_manifest=CASE_SET,
            scoring_config=exec_config(rm, []), metric_report=bad_wrapper,
            findings=loaded_findings(vf()))


# --- Persistence / security -----------------------------------------------


def test_persist_and_load_roundtrip(ctx):
    tmp_path, rm, rep = ctx
    r = assess(ctx, gates=[])
    p = persist_evaluation_result(r, eval_root=tmp_path, eval_run_id="run1")
    assert isinstance(p, PersistedEvaluationResult)
    assert p.artifact_reference == "results/evaluation_result.json"
    dest = tmp_path / "run1" / "results" / "evaluation_result.json"
    assert sha256_bytes(dest.read_bytes()) == p.sha256
    lo = load_evaluation_result("run1", eval_root=tmp_path)
    assert isinstance(lo, LoadedEvaluationResult)
    assert lo.result.model_dump() == r.model_dump()


def test_persist_write_once(ctx):
    tmp_path, rm, rep = ctx
    r = assess(ctx, gates=[])
    persist_evaluation_result(r, eval_root=tmp_path, eval_run_id="run1")
    with pytest.raises(EvaluationResultExistsError):
        persist_evaluation_result(r, eval_root=tmp_path, eval_run_id="run1")


def test_persist_rejects_file_collision(ctx):
    tmp_path, rm, rep = ctx
    (tmp_path / "run1" / "results").write_bytes(b"x")
    with pytest.raises(EvaluationResultExistsError):
        persist_evaluation_result(assess(ctx, gates=[]), eval_root=tmp_path, eval_run_id="run1")


def test_persist_rejects_symlink(ctx):
    tmp_path, rm, rep = ctx
    target = tmp_path / "elsewhere"
    target.mkdir()
    (tmp_path / "run1" / "results").symlink_to(target)
    with pytest.raises(EvaluationResultExistsError):
        persist_evaluation_result(assess(ctx, gates=[]), eval_root=tmp_path, eval_run_id="run1")


def test_write_failure_preserves_directory(ctx, monkeypatch):
    tmp_path, rm, rep = ctx
    r = assess(ctx, gates=[])

    def boom(*a, **k):
        raise OSError("synthetic")

    monkeypatch.setattr(gate_mod.os, "open", boom)
    with pytest.raises(EvaluationResultWriteError):
        persist_evaluation_result(r, eval_root=tmp_path, eval_run_id="run1")
    monkeypatch.undo()
    d = tmp_path / "run1" / "results"
    assert d.is_dir() and list(d.iterdir()) == []


def test_load_read_failure_raises_artifact_read_error(ctx, monkeypatch):
    # A valid artifact exists (path/type checks pass); the actual read then fails.
    tmp_path, rm, rep = ctx
    persist_evaluation_result(assess(ctx, gates=[]), eval_root=tmp_path, eval_run_id="run1")
    real_read = Path.read_bytes

    def boom(self, *a, **k):
        if self.name == "evaluation_result.json":
            raise OSError("synthetic-read-failure-detail")
        return real_read(self, *a, **k)

    monkeypatch.setattr(Path, "read_bytes", boom)
    with pytest.raises(EvaluationResultArtifactReadError) as exc:
        load_evaluation_result("run1", eval_root=tmp_path)
    assert type(exc.value) is EvaluationResultArtifactReadError
    # Public error hides the raw OSError text and any absolute external path.
    assert "synthetic-read-failure-detail" not in str(exc.value)
    assert str(tmp_path) not in str(exc.value)
    assert exc.value.artifact_reference == "results/evaluation_result.json"


def test_persist_schema_validation_failure_before_write(ctx, monkeypatch):
    # Isolate committed-schema validation: a valid serialized result is rejected
    # by the schema before any directory/file is created.
    tmp_path, rm, rep = ctx
    r = assess(ctx, gates=[])
    monkeypatch.setattr(gate_mod, "load_schema",
                        lambda *a, **k: {"type": "object", "required": ["___never_present___"]})
    with pytest.raises(EvaluationResultSchemaValidationError) as exc:
        persist_evaluation_result(r, eval_root=tmp_path, eval_run_id="run1")
    assert type(exc.value) is EvaluationResultSchemaValidationError
    # No raw jsonschema exception escapes; the sanitized messages are captured.
    assert isinstance(exc.value.schema_messages, tuple) and exc.value.schema_messages
    # Schema check precedes creation: nothing was written.
    assert not (tmp_path / "run1" / "results").exists()


def test_persist_readback_hash_mismatch(ctx, monkeypatch):
    # After a successful exclusive write, the re-read hash differs -> mismatch.
    tmp_path, rm, rep = ctx
    r = assess(ctx, gates=[])
    real_sha = gate_mod.sha256_bytes
    state = {"n": 0}

    def drifting(data):
        state["n"] += 1
        return "0" * 64 if state["n"] >= 2 else real_sha(data)  # 1=expected, 2=read-back differs

    monkeypatch.setattr(gate_mod, "sha256_bytes", drifting)
    with pytest.raises(EvaluationResultDestinationHashMismatchError) as exc:
        persist_evaluation_result(r, eval_root=tmp_path, eval_run_id="run1")
    assert type(exc.value) is EvaluationResultDestinationHashMismatchError
    assert "synthetic" not in str(exc.value)  # no raw hashing/fs detail leaks
    # No retry/cleanup: the partial directory and written file remain in place.
    d = tmp_path / "run1" / "results"
    assert d.is_dir() and (d / "evaluation_result.json").is_file()


def test_invalid_and_errored_persist_load(ctx):
    tmp_path, rm, rep = ctx
    inv = build_invalid_evaluation(stage="s", run_manifest=rm,
        issues=(EvaluationIssue(issue_code="artifact_missing", message="m"),))
    persist_evaluation_result(inv, eval_root=tmp_path, eval_run_id="run1")
    lo = load_evaluation_result("run1", eval_root=tmp_path)
    assert lo.result.execution_status == "invalid" and lo.result.gate_verdict is None


def write_results_dir(tmp_path, data: bytes):
    d = tmp_path / "run1" / "results"
    d.mkdir(parents=True, exist_ok=False)
    (d / "evaluation_result.json").write_bytes(data)


def canonical(r):
    from dynamic_ai_products.evaluation.contracts import canonical_contract_bytes
    return canonical_contract_bytes(r.model_dump(mode="json", exclude_unset=True)) + b"\n"


def test_load_missing(ctx):
    tmp_path, rm, rep = ctx
    with pytest.raises(EvaluationResultArtifactMissingError):
        load_evaluation_result("run1", eval_root=tmp_path)


def test_load_rejects_non_utf8(ctx):
    tmp_path, rm, rep = ctx
    write_results_dir(tmp_path, b"\xff\xfe")
    with pytest.raises(EvaluationResultDecodeError):
        load_evaluation_result("run1", eval_root=tmp_path)


def test_load_rejects_bom(ctx):
    tmp_path, rm, rep = ctx
    write_results_dir(tmp_path, "\ufeff".encode("utf-8") + canonical(assess(ctx, gates=[])))
    with pytest.raises(EvaluationResultJsonError):
        load_evaluation_result("run1", eval_root=tmp_path)


def test_load_rejects_trailing_json(ctx):
    tmp_path, rm, rep = ctx
    write_results_dir(tmp_path, canonical(assess(ctx, gates=[])).rstrip(b"\n") + b" x")
    with pytest.raises(EvaluationResultJsonError):
        load_evaluation_result("run1", eval_root=tmp_path)


def test_load_rejects_duplicate_keys(ctx):
    tmp_path, rm, rep = ctx
    write_results_dir(tmp_path, b'{"a":1,"a":2}')
    with pytest.raises(EvaluationResultJsonError) as exc:
        load_evaluation_result("run1", eval_root=tmp_path)
    assert exc.value.duplicate_key == "a"


def test_load_rejects_non_object(ctx):
    tmp_path, rm, rep = ctx
    write_results_dir(tmp_path, b"[1,2]")
    with pytest.raises(EvaluationResultTopLevelTypeError):
        load_evaluation_result("run1", eval_root=tmp_path)


def test_load_rejects_model_invalid(ctx):
    tmp_path, rm, rep = ctx
    write_results_dir(tmp_path, b'{"unexpected":true}')
    with pytest.raises(EvaluationResultModelValidationError):
        load_evaluation_result("run1", eval_root=tmp_path)


def test_load_rejects_projection_tamper(ctx):
    tmp_path, rm, rep = ctx
    # Valid EvaluationResultV2 by the broad schema, but wrong dataset_version.
    from dynamic_ai_products.evaluation.contracts import canonical_contract_bytes
    r = assess(ctx, gates=[])
    payload = r.model_dump(mode="json", exclude_unset=True)
    payload["dataset_version"] = "not-the-case-set"
    write_results_dir(tmp_path, canonical_contract_bytes(payload) + b"\n")
    with pytest.raises(EvaluationResultBindingError):
        load_evaluation_result("run1", eval_root=tmp_path)


def test_load_rejects_non_file_artifact(ctx):
    tmp_path, rm, rep = ctx
    d = tmp_path / "run1" / "results" / "evaluation_result.json"
    d.mkdir(parents=True, exist_ok=False)  # a directory where the file is expected
    with pytest.raises(EvaluationResultArtifactNotAFileError):
        load_evaluation_result("run1", eval_root=tmp_path)


def test_load_rejects_symlinked_run_dir(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    initialize_evaluation_run(eval_root=real, eval_run_id="run1", prediction_run_id="P",
        prediction_run_manifest_hash="a" * 64, case_set=CASE_SET, registry=REGISTRY,
        validator_bundle_version="vb", validator_bundle_hash="b" * 64, scoring_config=SCORING,
        code_commit="c", config_snapshot_source_root=FX / "configs")
    (tmp_path / "run1").symlink_to(real / "run1")
    with pytest.raises(RunArtifactNotAFileError):
        load_evaluation_result("run1", eval_root=tmp_path)


def test_repeated_loads_equal_but_distinct(ctx):
    tmp_path, rm, rep = ctx
    persist_evaluation_result(assess(ctx, gates=[]), eval_root=tmp_path, eval_run_id="run1")
    a = load_evaluation_result("run1", eval_root=tmp_path)
    b = load_evaluation_result("run1", eval_root=tmp_path)
    assert a is not b and a.result is not b.result
    assert a.result.model_dump() == b.result.model_dump()


def test_invalid_eval_root_rejected():
    with pytest.raises(InvalidEvaluationRootError):
        load_evaluation_result("run1", eval_root="")


def test_deterministic_bytes(ctx):
    tmp_path, rm, rep = ctx
    a = assess(ctx, gates=[])
    b = assess(ctx, gates=[])
    assert canonical(a) == canonical(b)


# --- Boundaries, exports, hygiene -----------------------------------------


def test_pure_assessor_no_filesystem(ctx, monkeypatch):
    calls = []

    def spy(name, orig):
        def w(*a, **k):
            calls.append(name)
            return orig(*a, **k)
        return w

    monkeypatch.setattr(Path, "read_bytes", spy("rb", Path.read_bytes))
    monkeypatch.setattr(Path, "mkdir", spy("mk", Path.mkdir))
    monkeypatch.setattr(os, "open", spy("op", os.open))
    assess(ctx, gates=[exec_gate(met.METRIC_AXIS_MULTI_LABEL, "axis-1",
        operator="greater_than_or_equal", value=0.5, sel=AXIS_SEL,
        support={"minimum_verified_support": 0})])
    assert calls == []


def test_protected_contract_hashes_unchanged():
    from dynamic_ai_products.evaluation import models as mod
    from dynamic_ai_products.evaluation.envelopes import PredictionArtifactManifest
    from dynamic_ai_products.evaluation.metrics import MetricReport
    exp = {
        ("PredictionEnvelope", "prediction_envelope"): "5ac06fb78220c3f7369863cda32ee914a1d33ff01020fc01e57d9bd0ccbb18a3",
        ("AssertionOutcome", "assertion_outcome"): "4af3a9eb7c99e3e3ba088784b3395f4b6920fa1f8061f7bb1118af6bd2720bd6",
        ("EvaluationRunManifest", "evaluation_run_manifest"): "7f8909d8e7059952c933c8e30f43044178b3f8a21d4baaa77bfb5c786b38d6ee",
        ("ValidatorFinding", "validator_finding"): "96f63fee300d363a662f4f956bacccdca596acfb0f22bf7039aa1335b6d61292",
        ("FindingDisposition", "finding_disposition"): "1c08efdbd36682acf535cc688ae5c73e902e1659f30814b6a5bee46b2c9d873e",
    }
    for (name, cid), h in exp.items():
        assert model_contract_hash(getattr(mod, name), cid, "0.1.0") == h
    assert model_contract_hash(PredictionArtifactManifest, "prediction_artifact_manifest", "0.1.0") \
        == "4b164aea18fc99f9518854aca0fb98587eb71d81c972a477d48cb815ddc0dbe4"
    assert model_contract_hash(MetricReport, "metric_report", "0.1.0") \
        == "d9e3f6d7399af628b38754758a7cb580e57955ad695ee7d92fb56c67c4ceac39"


PUBLIC_FUNCTIONS = ("assess_completed_evaluation", "build_invalid_evaluation",
                    "build_errored_evaluation", "persist_evaluation_result", "load_evaluation_result")
PUBLIC_MODELS = ("GateOutcome", "EvaluationIssue", "PersistedEvaluationResult",
                 "LoadedEvaluationResult")
PUBLIC_ALIASES = ("GateOperator",)
PUBLIC_EXCEPTIONS = (
    "GateEvaluationError", "GatePolicyError", "GateMetricSelectionError", "GateRunBindingError",
    "GateCaseSetBindingError", "GateScoringConfigBindingError", "GateMetricReportBindingError",
    "GateFindingsBindingError", "EvaluationResultExistsError", "EvaluationResultArtifactMissingError",
    "EvaluationResultArtifactNotAFileError", "EvaluationResultArtifactReadError",
    "EvaluationResultDecodeError", "EvaluationResultJsonError", "EvaluationResultTopLevelTypeError",
    "EvaluationResultModelValidationError", "EvaluationResultSchemaValidationError",
    "EvaluationResultBindingError", "EvaluationResultWriteError",
    "EvaluationResultDestinationHashMismatchError",
)


def test_all_30_public_names_exported():
    names = PUBLIC_ALIASES + PUBLIC_MODELS + PUBLIC_FUNCTIONS + PUBLIC_EXCEPTIONS
    assert len(names) == 30
    for name in names:
        assert name in evaluation_pkg.__all__
        assert getattr(evaluation_pkg, name) is getattr(gate_mod, name)


def test_exception_hierarchy():
    for name in PUBLIC_EXCEPTIONS:
        cls = getattr(gate_mod, name)
        if name == "GateEvaluationError":
            assert cls.__bases__ == (Exception,)
        else:
            assert issubclass(cls, gate_mod.GateEvaluationError)


def test_no_direct_base_error_raise_in_production():
    # GateEvaluationError is the abstract public parent: it must have no direct
    # raise site in production source (only concrete subclasses may be raised).
    import ast
    tree = ast.parse((ROOT / "src" / "dynamic_ai_products" / "evaluation" / "gates.py").read_text())
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and node.exc is not None:
            call = node.exc
            target = call.func if isinstance(call, ast.Call) else call
            if isinstance(target, ast.Name) and target.id == "GateEvaluationError":
                offenders.append(node.lineno)
    assert offenders == [], f"direct GateEvaluationError raises at lines {offenders}"


def test_private_helpers_not_exported():
    for name in ("_parse_gate", "_select_datum", "_evaluate_gate", "_ExecutableGate",
                 "_DimensionSelector", "_validate_projection", "_DuplicateKeyControl"):
        assert name not in evaluation_pkg.__all__
        assert not hasattr(evaluation_pkg, name)


def test_package_import_no_io_or_hash():
    code = (
        "import sys, os\nsys.path.insert(0, 'src')\nimport hashlib\n"
        "from jsonschema import Draft202012Validator, FormatChecker\nimport pydantic\n"
        "import dynamic_ai_products, dynamic_ai_products.universe.models, dynamic_ai_products.universe.io_utils\n"
        "from pathlib import Path\nreads=[]; writes=[]\n"
        "orb, ort, omk, oop = Path.read_bytes, Path.read_text, Path.mkdir, os.open\n"
        "Path.read_bytes = lambda self,*a,**k:(reads.append(str(self)),orb(self,*a,**k))[1]\n"
        "Path.read_text = lambda self,*a,**k:(reads.append(str(self)),ort(self,*a,**k))[1]\n"
        "Path.mkdir = lambda self,*a,**k:(writes.append('m'),omk(self,*a,**k))[1]\n"
        "os.open = lambda *a,**k:(writes.append('o'),oop(*a,**k))[1]\n"
        "sha=[]; osha=hashlib.sha256\nhashlib.sha256=lambda *a,**k:(sha.append(1),osha(*a,**k))[1]\n"
        "import dynamic_ai_products.evaluation.gates\n"
        "Path.read_bytes,Path.read_text,Path.mkdir,os.open=orb,ort,omk,oop\nhashlib.sha256=osha\n"
        "bad=[p for p in reads if p.endswith('.json') or p.endswith('.jsonl') or '/schemas/' in p or '/evals/' in p]\n"
        "assert not bad and not writes and not sha, (bad, writes, len(sha))\nprint('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0 and "OK" in result.stdout, result.stderr


# --- Slice 12K: gate applicability binding ---------------------------------


def _v1_rm(rm2):
    """A v0.1 gate manifest sharing a v0.2 report's run/case-set/scoring identity."""
    return EvaluationRunManifest.model_validate({
        "contract": {"contract_id": "evaluation_run_manifest", "contract_version": "0.1.0",
                     "contract_hash": model_contract_hash(
                         EvaluationRunManifest, "evaluation_run_manifest", "0.1.0")},
        "eval_run_id": rm2.eval_run_id, "prediction_run_id": "P",
        "prediction_run_manifest_hash": HEX,
        "case_set_version": rm2.case_set_version, "case_set_hash": rm2.case_set_hash,
        "registry_snapshot_hash": HEX, "validator_bundle_version": "vb",
        "validator_bundle_hash": "b" * 64,
        "scoring_gate_config_version": rm2.scoring_gate_config_version,
        "scoring_gate_config_hash": rm2.scoring_gate_config_hash,
        "code_commit": "c", "pydantic_runtime_version": "2"})


def _public_v2_loaded(tmp_path, stage="universe_classification"):
    """Produce, persist, and re-load a v0.2 report through the PUBLIC v0.2 APIs."""
    ev = _stage_evidence(stage, unsafe_min=1, audited_missed=(False,), pop=100)
    ev_ver = ev.model.set_version if ev is not None else None
    ev_hash = stage_metric_evidence_set_hash(ev.model) if ev is not None else None
    rm2 = initialize_evaluation_run_v2(
        eval_root=tmp_path, eval_run_id="run1", prediction_run_id="P",
        prediction_run_manifest_hash="a" * 64, case_set=CASE_SET, registry=REGISTRY,
        validator_bundle_version="vb", validator_bundle_hash="b" * 64, scoring_config=SCORING,
        code_commit="c", config_snapshot_source_root=FX / "configs", evaluation_created_at=CREATED,
        evaluation_stage=stage, stage_profile_registry=SP_REG,
        semantic_adapter_registry_version="sa-v1", semantic_adapter_registry_hash=HEX,
        selected_semantic_adapter_entry_hash=HEX,
        source_passage_snapshot_version="sp-v1", source_passage_snapshot_hash=HEX,
        gold_assertion_set_version="g-v1", gold_assertion_set_hash=HEX,
        axis_taxonomy_version="ax-v1", axis_taxonomy_hash=HEX,
        validator_rule_parameters_version="vp-v1", validator_rule_parameters_hash=HEX,
        stage_metric_evidence_set_version=ev_ver, stage_metric_evidence_set_hash=ev_hash).manifest
    axis = met.AxisDefinition(axis_id="axis-1", axis_role="product", metric_type="abstention_allowed",
                              base_metric_type="multi_label", labels=("a", "b"))
    ex = (met.ValidatorRuleEvaluationRecord(artifact_id="art1", rule_id="source_id_resolution",
                                            evaluated_observation_count=5, failed_observation_count=1),)
    snap = build_metric_input_snapshot(
        evaluation_stage=stage, stage_profile_registry=SP_REG, run_manifest=rm2,
        axis_definitions=(axis,),
        axis_records=(met.AxisEvaluationRecord(record_id="r1", case_id=CID, axis_id="axis-1",
            metric_scope="conditional", verification_status="verified",
            evidence_resolvability="resolvable", predicted_values=("a",), gold_values=("a",)),),
        assertion_bindings=(met.AssertionMetricBinding(case_id=CID, assertion_id="A1",
            assertion_kind="expected_entity", partition="dev", suites=("adversarial", "regression")),),
        validator_rule_evaluations=ex, stage_evidence=ev)
    scfg = ScoringGateConfig(config_version=rm2.scoring_gate_config_version,
        blocking_severities=("synth-critical",), protected_regression_classes=(),
        gates=(_s9gate(met.METRIC_TIER_CONTRACT, "overall"),
               _s9gate(met.METRIC_AXIS_MULTI_LABEL, "axis-1", {"minimum_verified_support": 0})),
        diagnostics=(_diag(met.METRIC_ASSERTION_OUTCOMES, "overall"),
                     _diag(met.METRIC_VALIDATOR_RULES, "overall"),
                     _diag(met.METRIC_VALIDATOR_SUMMARIES, "overall"),
                     _diag(met.METRIC_AXIS_ABSTENTION, "axis-1")))
    lc = LoadedScoringGateConfig(config=scfg, version=rm2.scoring_gate_config_version,
                                 sha256=rm2.scoring_gate_config_hash, artifact_reference="x")
    v2 = met.compute_metric_report_v2(snap, assertion_outcomes=(ao(),), validator_findings=(vf(),),
        run_manifest=rm2, case_set_manifest=CASE_SET, scoring_config=lc,
        stage_profile_registry=SP_REG)
    met.persist_metric_report(v2, eval_root=tmp_path, eval_run_id="run1", stage_profile_registry=SP_REG)
    return met.load_metric_report_v2("run1", eval_root=tmp_path, stage_profile_registry=SP_REG), rm2


def _inapplicable_gate():
    # unsafe_exclusion is inapplicable for universe_classification.
    return exec_gate(met.METRIC_UNSAFE_EXCLUSION, "overall", operator="less_than_or_equal",
                     value=0.99, sel=UNSAFE_SEL, support={"minimum_audited_per_stratum": 1},
                     confidence_level=0.95, ci="wilson_one_sided_stratified")


def test_v2_public_path_inapplicable_family_raises_binding_error(tmp_path):
    # A v0.2 report loaded through the public v0.2 path, gate on an inapplicable
    # family -> GateApplicabilityBindingError.
    loaded, rm2 = _public_v2_loaded(tmp_path)
    v1 = _v1_rm(rm2)
    with pytest.raises(GateApplicabilityBindingError):
        assess_completed_evaluation(stage="s", run_manifest=v1, case_set_manifest=CASE_SET,
            scoring_config=exec_config(v1, [_inapplicable_gate()]), metric_report=loaded,
            findings=loaded_findings(vf()))


def test_v2_applicability_error_metadata(ctx):
    tmp_path, rm, _ = ctx
    report = build_report_v2(tmp_path, rm)  # classification
    with pytest.raises(GateApplicabilityBindingError) as exc:
        assess(ctx, gates=[_inapplicable_gate()], report=report)
    e = exc.value
    assert e.metric_family == met.METRIC_UNSAFE_EXCLUSION
    assert e.applicability_state == "inapplicable"
    assert e.reason_code and e.reason_code.startswith("unsafe_exclusion_")
    assert e.eval_run_id == "run1"
    assert e.artifact_reference == "run1/metrics/metric_report.v2.json"
    assert e.gate_reference_id == "g-unsafe_exclusion-overall"


def test_v2_applicability_precedes_selection_error(ctx):
    tmp_path, rm, _ = ctx
    report = build_report_v2(tmp_path, rm)
    # The inapplicable-family gate would otherwise reach _select_datum and raise a
    # zero-candidate GateMetricSelectionError; the binding error must win first.
    with pytest.raises(GateApplicabilityBindingError) as exc:
        assess(ctx, gates=[_inapplicable_gate()], report=report)
    assert not isinstance(exc.value, GateMetricSelectionError)
    assert not hasattr(exc.value, "candidate_count")


def test_v2_applicable_family_gate_evaluates_normally(ctx):
    tmp_path, rm, _ = ctx
    report = build_report_v2(tmp_path, rm)  # axis_multi_label applicable
    r = assess(ctx, report=report, gates=[
        exec_gate(met.METRIC_AXIS_MULTI_LABEL, "axis-1", operator="greater_than_or_equal",
                  value=0.5, sel=AXIS_SEL, support={"minimum_verified_support": 0})])
    assert r.execution_status == "completed" and r.gate_verdict == "pass"


def test_v1_report_inapplicable_family_keeps_legacy_selection_error(ctx):
    # A legacy v0.1 report has no ledger: an unsafe gate on a classification report
    # finds no datum and raises the existing GateMetricSelectionError, NOT the new
    # applicability binding error.
    tmp_path, rm, rep = ctx  # rep is a v0.1 classification LoadedMetricReport
    with pytest.raises(GateMetricSelectionError) as exc:
        assess(ctx, gates=[_inapplicable_gate()])
    assert not isinstance(exc.value, GateApplicabilityBindingError)
    assert exc.value.candidate_count == 0


def test_applicability_error_public_wrappers_private():
    assert "GateApplicabilityBindingError" in evaluation_pkg.__all__
    assert issubclass(GateApplicabilityBindingError, GateEvaluationError)
    # v0.2 loaded wrapper stays module-private.
    assert "_LoadedMetricReportV2" not in evaluation_pkg.__all__


# --- ADR-027: run-manifest v0.1 | v0.2 gate dispatch -----------------------
#
# The gate layer accepts either governed run-manifest version across its whole
# build/persist/load path, reading only the five fields the versions share. Every
# v0.1 path, behaviour, and error code is preserved.


def _v2_rm_matching(rm, *, stage="universe_classification"):
    """A v0.2 manifest sharing another manifest's run/case-set/scoring identity."""
    entry = resolve_metric_applicability(SP_REG.registry, stage)
    ev = _stage_evidence(stage, unsafe_min=1, audited_missed=(False,), pop=100)
    return _v2_rm(
        eval_run_id=rm.eval_run_id, case_set_version=rm.case_set_version,
        case_set_hash=rm.case_set_hash, scoring_version=rm.scoring_gate_config_version,
        scoring_hash=rm.scoring_gate_config_hash, stage=stage, entry_hash=entry.entry_hash,
        ev_ver=ev.model.set_version if ev is not None else None,
        ev_hash=stage_metric_evidence_set_hash(ev.model) if ev is not None else None)


def _bump_version(m, version):
    """Same concrete model class, disagreeing declared contract version."""
    return m.model_copy(
        update={"contract": m.contract.model_copy(update={"contract_version": version})})


def test_v2_assess_completed_accepts_a_v2_manifest(tmp_path):
    loaded, rm2 = _public_v2_loaded(tmp_path)
    assert type(rm2) is EvaluationRunManifestV2
    assert isinstance(loaded.report, met.MetricReportV2)
    result = assess_completed_evaluation(
        stage="task_extraction", run_manifest=rm2, case_set_manifest=CASE_SET,
        scoring_config=exec_config(rm2, ()), metric_report=loaded,
        findings=loaded_findings())
    assert result.execution_status == "completed"
    assert result.gate_verdict == "pass"
    assert result.eval_run_id == rm2.eval_run_id
    assert result.dataset_version == rm2.case_set_version


def test_v2_build_invalid_and_errored_accept_a_v2_manifest(tmp_path):
    _loaded, rm2 = _public_v2_loaded(tmp_path)
    invalid = build_invalid_evaluation(
        stage="task_extraction", run_manifest=rm2,
        issues=(EvaluationIssue(issue_code="artifact_missing", message="m"),))
    assert invalid.execution_status == "invalid"
    assert invalid.gate_verdict is None
    assert invalid.dataset_version == rm2.case_set_version
    errored = build_errored_evaluation(
        stage="task_extraction", run_manifest=rm2,
        issues=(EvaluationIssue(issue_code="runtime_failure", message="m"),))
    assert errored.execution_status == "errored"


def test_v2_persist_and_load_round_trip(tmp_path):
    """Persistence and loading both bind to a v0.2 run directory on disk."""
    _loaded, rm2 = _public_v2_loaded(tmp_path)
    result = build_invalid_evaluation(
        stage="task_extraction", run_manifest=rm2,
        issues=(EvaluationIssue(issue_code="artifact_missing", message="m"),))
    persisted = persist_evaluation_result(result, eval_root=tmp_path, eval_run_id=rm2.eval_run_id)
    assert persisted.artifact_reference == "results/evaluation_result.json"
    reloaded = load_evaluation_result(rm2.eval_run_id, eval_root=tmp_path)
    assert reloaded.result == result
    assert reloaded.sha256 == persisted.sha256
    assert reloaded.result.dataset_version == rm2.case_set_version


def test_v2_projection_mismatch_rejected_on_persist(tmp_path):
    _loaded, rm2 = _public_v2_loaded(tmp_path)
    result = build_invalid_evaluation(
        stage="task_extraction", run_manifest=rm2,
        issues=(EvaluationIssue(issue_code="artifact_missing", message="m"),))
    tampered = result.model_copy(update={"dataset_version": "not-the-case-set-version"})
    with pytest.raises(EvaluationResultBindingError, match="dataset_version"):
        persist_evaluation_result(tampered, eval_root=tmp_path, eval_run_id=rm2.eval_run_id)


# --- Declared-version / concrete-class inconsistency ----------------------


def test_v2_class_declaring_v01_version_is_rejected(tmp_path):
    _loaded, rm2 = _public_v2_loaded(tmp_path)
    bad = _bump_version(rm2, "0.1.0")
    assert type(bad) is EvaluationRunManifestV2
    with pytest.raises(GateRunBindingError, match="run_manifest_version_inconsistent"):
        build_invalid_evaluation(
            stage="task_extraction", run_manifest=bad,
            issues=(EvaluationIssue(issue_code="artifact_missing", message="m"),))


def test_v01_class_declaring_v2_version_is_rejected(ctx):
    """The mirror case: a v0.1 model declaring 0.2.0."""
    _tmp, rm, _report = ctx
    bad = _bump_version(rm, "0.2.0")
    assert type(bad) is EvaluationRunManifest
    with pytest.raises(GateRunBindingError, match="run_manifest_version_inconsistent"):
        build_errored_evaluation(
            stage="task_extraction", run_manifest=bad,
            issues=(EvaluationIssue(issue_code="runtime_failure", message="m"),))


def test_inconsistent_version_rejected_by_assess(tmp_path):
    loaded, rm2 = _public_v2_loaded(tmp_path)
    bad = _bump_version(rm2, "0.1.0")
    with pytest.raises(GateRunBindingError, match="run_manifest_version_inconsistent"):
        assess_completed_evaluation(
            stage="task_extraction", run_manifest=bad, case_set_manifest=CASE_SET,
            scoring_config=exec_config(rm2, ()), metric_report=loaded,
            findings=loaded_findings())


def test_unsupported_run_manifest_type_is_a_type_error():
    with pytest.raises(TypeError, match="EvaluationRunManifest or EvaluationRunManifestV2"):
        build_invalid_evaluation(
            stage="task_extraction", run_manifest={"eval_run_id": "run1"},
            issues=(EvaluationIssue(issue_code="artifact_missing", message="m"),))


class _SubclassedRunManifestV2(EvaluationRunManifestV2):
    """A concrete subclass of a governed manifest, used only by the test below."""


def test_manifest_subclass_is_rejected_by_the_controlled_type_error(tmp_path):
    """A subclass must not reach the version table.

    ``isinstance`` would accept it while ``_RUN_MANIFEST_MODEL_VERSIONS`` has no
    exact key for it, which would surface as an uncontrolled ``KeyError`` instead
    of the locked fail-closed boundary.
    """
    _loaded, rm2 = _public_v2_loaded(tmp_path)
    # A subclass has its own generated contract hash, so it cannot be built through
    # model_validate. model_construct is the real bypass vector this boundary must
    # contain: it yields a subclass instance that satisfies isinstance.
    sub = _SubclassedRunManifestV2.model_construct(
        **{name: getattr(rm2, name) for name in type(rm2).model_fields})
    assert isinstance(sub, EvaluationRunManifestV2)          # passes isinstance
    assert type(sub) is not EvaluationRunManifestV2          # but is not an exact key
    assert type(sub) not in gate_mod._RUN_MANIFEST_MODEL_VERSIONS
    issues = (EvaluationIssue(issue_code="artifact_missing", message="m"),)
    with pytest.raises(TypeError, match="EvaluationRunManifest or EvaluationRunManifestV2"):
        build_invalid_evaluation(stage="task_extraction", run_manifest=sub, issues=issues)
    # Specifically not a KeyError, and the same holds for the assess path.
    try:
        build_invalid_evaluation(stage="task_extraction", run_manifest=sub, issues=issues)
    except KeyError:  # pragma: no cover - would be the regression
        raise AssertionError("subclass reached the version table and raised KeyError") from None
    except TypeError:
        pass
    with pytest.raises(TypeError, match="EvaluationRunManifest or EvaluationRunManifestV2"):
        assess_completed_evaluation(
            stage="task_extraction", run_manifest=sub, case_set_manifest=CASE_SET,
            scoring_config=exec_config(rm2, ()), metric_report=_loaded,
            findings=loaded_findings())


def test_acceptance_table_and_version_table_are_the_same_authority():
    """Acceptance and version lookup must be driven by one table."""
    assert set(gate_mod._RUN_MANIFEST_MODEL_VERSIONS) == {
        EvaluationRunManifest, EvaluationRunManifestV2}
    assert gate_mod._RUN_MANIFEST_MODEL_VERSIONS[EvaluationRunManifest] == "0.1.0"
    assert gate_mod._RUN_MANIFEST_MODEL_VERSIONS[EvaluationRunManifestV2] == "0.2.0"


# --- Metric-report version gating ----------------------------------------


def test_v2_run_rejects_a_v01_metric_report(ctx):
    """A v0.2 run may bind only metric_report@0.2.0."""
    _tmp, rm, v1_report = ctx
    assert not isinstance(v1_report.report, met.MetricReportV2)
    v2_rm = _v2_rm_matching(rm)
    with pytest.raises(GateMetricReportBindingError, match="metric_report_version_mismatch"):
        assess_completed_evaluation(
            stage="task_extraction", run_manifest=v2_rm, case_set_manifest=CASE_SET,
            scoring_config=exec_config(v2_rm, ()), metric_report=v1_report,
            findings=loaded_findings())


def test_v2_run_accepts_a_v2_metric_report(tmp_path):
    loaded, rm2 = _public_v2_loaded(tmp_path)
    out = assess_completed_evaluation(
        stage="task_extraction", run_manifest=rm2, case_set_manifest=CASE_SET,
        scoring_config=exec_config(rm2, ()), metric_report=loaded,
        findings=loaded_findings())
    assert out.execution_status == "completed"


def test_v01_run_still_accepts_a_v01_report(ctx):
    """v0.1 behaviour is unchanged for a v0.1 report."""
    assert assess(ctx, gates=()).execution_status == "completed"


def test_v01_run_still_accepts_a_v2_report(tmp_path):
    """v0.1 keeps accepting either report version: no new restriction."""
    loaded, rm2 = _public_v2_loaded(tmp_path)
    v1 = _v1_rm(rm2)
    assert type(v1) is EvaluationRunManifest
    out = assess_completed_evaluation(
        stage="task_extraction", run_manifest=v1, case_set_manifest=CASE_SET,
        scoring_config=exec_config(v1, ()), metric_report=loaded,
        findings=loaded_findings())
    assert out.execution_status == "completed"


# --- Shared-field discipline and contract stability ----------------------


def test_gate_layer_reads_only_the_five_shared_fields():
    """The five fields the gate layer may read exist in both governed versions."""
    shared = ("eval_run_id", "case_set_version", "case_set_hash",
              "scoring_gate_config_version", "scoring_gate_config_hash")
    for model in (EvaluationRunManifest, EvaluationRunManifestV2):
        for field in shared:
            assert field in model.model_fields, (model.__name__, field)


def test_evaluation_result_contract_and_private_wrapper_unchanged():
    assert model_contract_hash(EvaluationResultV2, "evaluation_result", "0.2.0") == \
        "1f741b59e3b741560064409a59b43b3343b85efc9a6a4336c557a5a748c00105"
    assert "_LoadedMetricReportV2" not in evaluation_pkg.__all__
    assert len(evaluation_pkg.__all__) == 579
