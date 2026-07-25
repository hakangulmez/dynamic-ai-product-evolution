"""Slice 9: metric aggregation, axis-native evaluation, abstention, tier
contract, and unsafe-exclusion audit metrics.

Pure ``compute_metric_report`` is exercised with in-memory contracts;
persistence/loading run under ``tmp_path`` on an initialized Slice 5 run
directory. Slice 9 emits no execution status, gate verdict, or gate comparison.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import metrics as met
from dynamic_ai_products.evaluation.cases import InvalidEvaluationRootError
from dynamic_ai_products.evaluation.case_sets import load_case_set_manifest
from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.metrics import (
    NOT_APPLICABLE,
    NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION,
    OTHER,
    UNKNOWN,
    AssertionMetricBinding,
    AxisDefinition,
    AxisEvaluationRecord,
    LoadedMetricReport,
    METRIC_ASSERTION_OUTCOMES,
    METRIC_AXIS_ABSTENTION,
    METRIC_AXIS_MULTI_LABEL,
    METRIC_AXIS_NOMINAL,
    METRIC_AXIS_ORDINAL,
    METRIC_AXIS_STRUCTURED_SET,
    METRIC_SCREEN_OPERATIONAL,
    METRIC_TIER_CONTRACT,
    METRIC_UNSAFE_EXCLUSION,
    METRIC_VALIDATOR_RULES,
    METRIC_VALIDATOR_SUMMARIES,
    MetricReport,
    PersistedMetricReport,
    ScreenOperationalSummary,
    TierContractObservation,
    UnsafeAuditLabel,
    UnsafeAuditStratum,
    UnsafeExclusionAuditSnapshot,
    ValidatorRuleEvaluationRecord,
    AssertionBindingMismatchError,
    CaseMembershipBindingError,
    FindingRunBindingError,
    OutcomeRunBindingError,
    MetricArtifactMissingError,
    MetricArtifactNotAFileError,
    MetricDecodeError,
    MetricJsonError,
    MetricModelValidationError,
    MetricPolicyError,
    MetricReportBindingError,
    MetricReportExistsError,
    MetricTopLevelTypeError,
    MetricWriteError,
    SnapshotBindingError,
    UnsafeAuditPolicyError,
    ValidatorExecutionMismatchError,
    compute_metric_report,
    load_metric_report,
    metric_input_snapshot_hash,
    persist_metric_report,
)
from dynamic_ai_products.evaluation.metric_inputs import (
    MetricInputSnapshotError,
    build_metric_input_snapshot,
)
from dynamic_ai_products.evaluation.models import (
    AssertionOutcome,
    EvaluationRunManifestV2,
    ValidatorFinding,
)
from dynamic_ai_products.evaluation.references import load_target_registry
from dynamic_ai_products.evaluation.runs import (
    RunArtifactNotAFileError,
    initialize_evaluation_run_v2,
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
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness"

CASE_SET = load_case_set_manifest("valid_base_case_set_manifest.json", eval_root=FX / "case_sets")
REGISTRY = load_target_registry("valid_target_registry.json", eval_root=FX / "configs")
SCORING_LOADED = load_scoring_gate_config("valid_scoring_gate_config.json", eval_root=FX / "configs")
SP_REG = load_stage_profile_registry(
    "stage_profiles/stage_profile_registry.json", eval_root=FX)
SP_REG_HASH = stage_profile_registry_hash(SP_REG.registry)
RM_V2_HASH = model_contract_hash(EvaluationRunManifestV2, "evaluation_run_manifest", "0.2.0")
CREATED = "2026-07-24T00:00:00+00:00"
HEX = "a" * 64
AX = "axis-1"
# The authoritative case-set fixture's first membership; records and bindings
# must reference real case IDs with matching partition/suites (§9 binding).
CID = "SYNTH-CASE-0001"
PART = "dev"
SUITES = ("adversarial", "regression")
AO_META = {"contract_id": "assertion_outcome", "contract_version": "0.1.0",
           "contract_hash": model_contract_hash(AssertionOutcome, "assertion_outcome", "0.1.0")}
VF_META = {"contract_id": "validator_finding", "contract_version": "0.1.0",
           "contract_hash": model_contract_hash(ValidatorFinding, "validator_finding", "0.1.0")}


# --- Config / run builders ------------------------------------------------


def _gate(mid, sl, *, support=None, ci=None, thr=None):
    return GateDefinition(
        reference_id=f"g-{mid}-{sl}", metric_id=mid, population_slice_id=sl,
        verified_support_requirement=support or {"minimum_verified_support": 0},
        ci_method_reference=ci, blocking_severity="synth-critical",
        protected_regression_class_references=(), slice_definitions=({"s": sl},),
        threshold=thr or {"x": 1},
    )


def _diag(mid, sl, *, minimum=0):
    return DiagnosticDefinition(
        reference_id=f"d-{mid}-{sl}", metric_id=mid, population_slice_id=sl,
        slice_definitions=({"minimum_verified_support": minimum},),
    )


def build_config(config_version, *, axis_ids=(AX,), axis_metric_id=METRIC_AXIS_MULTI_LABEL,
                 axis_minimum=0, unsafe_min=1, confidence=0.95, validator_minimum=0,
                 assertion_minimum=0, operational_minimum=0, abstention_axes=None):
    gates = [
        _gate(METRIC_TIER_CONTRACT, "overall"),
        _gate(METRIC_UNSAFE_EXCLUSION, "overall",
              support={"minimum_audited_per_stratum": unsafe_min},
              ci="wilson_one_sided_stratified", thr={"confidence_level": confidence}),
    ]
    diags = [
        _diag(METRIC_ASSERTION_OUTCOMES, "overall", minimum=assertion_minimum),
        _diag(METRIC_VALIDATOR_RULES, "overall", minimum=validator_minimum),
        _diag(METRIC_VALIDATOR_SUMMARIES, "overall", minimum=validator_minimum),
        _diag(METRIC_SCREEN_OPERATIONAL, "overall", minimum=operational_minimum),
    ]
    for a in axis_ids:
        gates.append(_gate(axis_metric_id, a, support={"minimum_verified_support": axis_minimum}))
        # Coverage/abstention metrics are computed for every axis, so every axis
        # needs an abstention policy.
        diags.append(_diag(METRIC_AXIS_ABSTENTION, a))
    return ScoringGateConfig(
        config_version=config_version, blocking_severities=("synth-critical",),
        protected_regression_classes=(), gates=tuple(gates), diagnostics=tuple(diags),
    )


def loaded(config, rm):
    """Wrap a config as the Slice 4 LoadedScoringGateConfig bound to the run manifest."""
    return LoadedScoringGateConfig(
        config=config, version=rm.scoring_gate_config_version,
        sha256=rm.scoring_gate_config_hash, artifact_reference="metrics/config.json",
    )


def init_run(eval_root, run_id="run1"):
    # A v0.2 extraction run (no stage evidence); used only for its case-set /
    # scoring identity and to provide a persisted run directory.
    return initialize_evaluation_run_v2(
        eval_root=eval_root, eval_run_id=run_id, prediction_run_id="P",
        prediction_run_manifest_hash="a" * 64, case_set=CASE_SET, registry=REGISTRY,
        validator_bundle_version="vb", validator_bundle_hash="b" * 64,
        scoring_config=SCORING_LOADED, code_commit="c", config_snapshot_source_root=FX / "configs",
        evaluation_created_at=CREATED, evaluation_stage="capability_extraction",
        stage_profile_registry=SP_REG,
        semantic_adapter_registry_version="sa-v1", semantic_adapter_registry_hash=HEX,
        selected_semantic_adapter_entry_hash=HEX,
        source_passage_snapshot_version="sp-v1", source_passage_snapshot_hash=HEX,
        gold_assertion_set_version="g-v1", gold_assertion_set_hash=HEX,
        axis_taxonomy_version="ax-v1", axis_taxonomy_hash=HEX,
        validator_rule_parameters_version="vp-v1", validator_rule_parameters_hash=HEX,
    ).manifest


def _v2_rm(*, eval_run_id, case_set_version, case_set_hash, scoring_version, scoring_hash,
           stage, entry_hash, ev_ver=None, ev_hash=None):
    """A minimal valid v0.2 manifest carrying the stage/applicability pins that
    ``compute_metric_report`` checks; unchecked fields are placeholders."""
    payload = {
        "contract": {"contract_id": "evaluation_run_manifest", "contract_version": "0.2.0",
                     "contract_hash": RM_V2_HASH},
        "eval_run_id": eval_run_id, "prediction_run_id": "P",
        "prediction_run_manifest_hash": HEX,
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


def _build_evidence(stage, tiers, aud, ops):
    entry = resolve_metric_applicability(SP_REG.registry, stage)
    kinds = entry.required_stage_evidence_kinds
    if not kinds:
        return None
    variants = []
    if "universe_classification_tier" in kinds:
        obs = tiers if tiers is not None else (tier_obs(),)
        variants.append({"kind": "universe_classification_tier",
                         "tier_contract_observations": [o.model_dump(mode="json") for o in obs]})
    if "universe_screen_operational" in kinds:
        s = ops if ops is not None else op_summary()
        variants.append({"kind": "universe_screen_operational",
                         "screen_operational_summary": s.model_dump(mode="json")})
    if "universe_unsafe_exclusion_audit" in kinds:
        a = aud if aud is not None else audit_snapshot()
        variants.append({"kind": "universe_unsafe_exclusion_audit",
                         "unsafe_exclusion_audit": a.model_dump(mode="json")})
    variants.sort(key=lambda v: v["kind"])
    evset = build_stage_metric_evidence_set(
        evaluation_stage=stage, set_version="se-v1", variants=tuple(variants))
    return LoadedStageMetricEvidenceSet(
        model=evset, version="se-v1", sha256="d" * 64, artifact_reference="stage_evidence/e.json")


def _rm_from_snapshot(snap):
    b = snap.applicability_binding
    return _v2_rm(
        eval_run_id=snap.eval_run_id, case_set_version=snap.case_set_version,
        case_set_hash=snap.case_set_hash, scoring_version=snap.scoring_gate_config_version,
        scoring_hash=snap.scoring_gate_config_hash, stage=b.evaluation_stage,
        entry_hash=b.selected_stage_profile_entry_hash,
        ev_ver=b.stage_metric_evidence_set_version, ev_hash=b.stage_metric_evidence_set_hash)


def ao(case_id=CID, assertion_id="A1", outcome="satisfied"):
    return AssertionOutcome.model_validate({
        "contract": AO_META, "eval_run_id": "run1", "case_id": case_id,
        "assertion_id": assertion_id, "assertion_semantic_version": "0.1.0", "outcome": outcome,
    })


def vf(finding_id="f1", validator="source_id_resolution", artifact_id="art1"):
    return ValidatorFinding.model_validate({
        "contract": VF_META, "finding_id": finding_id, "validator": validator,
        "validator_bundle_version": "vb", "validator_bundle_hash": "b" * 64,
        "rule_params_hash": HEX, "severity": "error", "run_id": "run1", "artifact_id": artifact_id,
        "observed_value": "x", "expected_invariant": "y", "message": "m", "evidence": "e",
        "repairable": False, "created_at": "2026-07-20T00:00:00Z",
    })


def audit(*, missed=1, n=2, pop=100, stratum="s1"):
    labels = tuple(
        UnsafeAuditLabel(record_id=f"{stratum}-l{i}", verification_status="verified",
                         actually_eligible_or_boundary_relevant=(i < missed))
        for i in range(n)
    )
    return UnsafeAuditStratum(stratum_id=stratum, screen_negative_population_count=pop,
                              audited_labels=labels)


def audit_snapshot(strata=None):
    return UnsafeExclusionAuditSnapshot(
        audit_snapshot_hash="b" * 64, seed=7, sampling_design_id="d1",
        strata=strata or (audit(),),
    )


def op_summary():
    return ScreenOperationalSummary(total_screened=10, screen_negative=4, screen_nonnegative=5,
                                    unresolved=1, downstream_review_count=3)


def tier_obs(record_id="t1", *, exact=True, verification="verified"):
    if exact:
        return TierContractObservation(
            record_id=record_id, verification_status=verification, tier_rule_version="v1",
            expected_tier="T1", observed_tier="T1", expected_reason_codes=("rc",),
            observed_reason_codes=("rc",), expected_rule_trace_hash="c" * 64,
            observed_rule_trace_hash="c" * 64, repeatability_output_hashes=("d" * 64, "d" * 64),
        )
    return TierContractObservation(
        record_id=record_id, verification_status=verification, tier_rule_version="v1",
        expected_tier="T1", observed_tier="T2", expected_reason_codes=("rc",),
        observed_reason_codes=("other",), expected_rule_trace_hash="c" * 64,
        observed_rule_trace_hash="e" * 64, repeatability_output_hashes=("d" * 64, "f" * 64),
    )


def make_axis(metric_type="abstention_allowed", base="multi_label", labels=("a", "b"),
              role="product", ordinal_order=(), weighting=None):
    return AxisDefinition(axis_id=AX, axis_role=role, metric_type=metric_type,
                          base_metric_type=base, labels=labels, ordinal_order=ordinal_order,
                          ordinal_weighting=weighting)


def rec(rid, pred, gold, *, ver="verified", res="resolvable", scope="conditional", case=CID):
    return AxisEvaluationRecord(record_id=rid, case_id=case, axis_id=AX, metric_scope=scope,
                                verification_status=ver, evidence_resolvability=res,
                                predicted_values=pred, gold_values=gold)


def make_snapshot(rm, *, stage=None, axes=None, records=(), bindings=None,
                  execs=None, tiers=None, aud=None, ops=None):
    """Build a stamped, stage-aware ``metric_input_snapshot@0.1.0`` (v0.2 path).

    When ``stage`` is unspecified it is inferred: supplying ``aud`` or ``ops``
    selects ``universe_screen`` (screen-operational + unsafe-exclusion families);
    otherwise ``universe_classification`` (axis + tier families).
    """
    if stage is None:
        stage = "universe_screen" if (aud is not None or ops is not None) \
            else "universe_classification"
    entry = resolve_metric_applicability(SP_REG.registry, stage)
    ev = _build_evidence(stage, tiers, aud, ops)
    ev_ver = ev.model.set_version if ev is not None else None
    ev_hash = stage_metric_evidence_set_hash(ev.model) if ev is not None else None
    local_rm = _v2_rm(
        eval_run_id=rm.eval_run_id, case_set_version=rm.case_set_version,
        case_set_hash=rm.case_set_hash, scoring_version=rm.scoring_gate_config_version,
        scoring_hash=rm.scoring_gate_config_hash, stage=stage, entry_hash=entry.entry_hash,
        ev_ver=ev_ver, ev_hash=ev_hash)
    return build_metric_input_snapshot(
        evaluation_stage=stage, stage_profile_registry=SP_REG, run_manifest=local_rm,
        axis_definitions=axes if axes is not None else (make_axis(),),
        axis_records=tuple(records),
        assertion_bindings=bindings if bindings is not None else (
            AssertionMetricBinding(case_id=CID, assertion_id="A1", assertion_kind="expected_entity",
                                   partition=PART, suites=SUITES),),
        validator_rule_evaluations=execs if execs is not None else (
            ValidatorRuleEvaluationRecord(artifact_id="art1", rule_id="source_id_resolution",
                                          evaluated_observation_count=5, failed_observation_count=1),),
        stage_evidence=ev,
    )


@pytest.fixture
def ctx(tmp_path):
    rm = init_run(tmp_path)
    config = build_config(rm.scoring_gate_config_version)
    return tmp_path, rm, config


def compute(ctx, *, snapshot=None, outcomes=None, findings=None, config=None):
    tmp_path, rm, cfg = ctx
    snap = snapshot if snapshot is not None else make_snapshot(rm)
    run_rm = _rm_from_snapshot(snap)
    return compute_metric_report(
        snap,
        assertion_outcomes=outcomes if outcomes is not None else (ao(),),
        validator_findings=findings if findings is not None else (vf(),),
        run_manifest=run_rm, case_set_manifest=CASE_SET,
        scoring_config=loaded(config if config is not None else cfg, run_rm),
    )


def find(report, metric_id, **dims):
    result = []
    for d in report.metrics:
        if d.metric_id != metric_id:
            continue
        dd = {x.key: x.value for x in d.dimensions}
        if all(dd.get(k) == v for k, v in dims.items()):
            result.append(d)
    return result


def one(report, metric_id, **dims):
    matches = find(report, metric_id, **dims)
    assert len(matches) == 1, f"expected exactly one {metric_id} {dims}, got {len(matches)}"
    return matches[0]


# --- Models and special values --------------------------------------------


def test_special_values_distinct():
    assert len({UNKNOWN, OTHER, NOT_APPLICABLE, NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION}) == 4


def test_axis_definition_frozen_and_strict():
    a = make_axis()
    with pytest.raises(Exception):
        a.axis_id = "x"
    with pytest.raises(Exception):
        AxisDefinition(axis_id=AX, axis_role="product", metric_type="multi_label",
                       labels=("a",), extra="no")


def test_axis_rejects_reserved_labels():
    with pytest.raises(ValueError):
        make_axis(metric_type="multi_label", base=None, labels=("a", UNKNOWN))
    with pytest.raises(ValueError):
        make_axis(metric_type="multi_label", base=None,
                  labels=("a", NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION))


def test_axis_abstention_requires_base():
    with pytest.raises(ValueError):
        AxisDefinition(axis_id=AX, axis_role="product", metric_type="abstention_allowed",
                       base_metric_type=None, labels=("a", "b"))


def test_axis_non_abstention_rejects_base():
    with pytest.raises(ValueError):
        AxisDefinition(axis_id=AX, axis_role="product", metric_type="multi_label",
                       base_metric_type="multi_label", labels=("a", "b"))


def test_ordinal_axis_requires_matching_order_and_weighting():
    with pytest.raises(ValueError):
        AxisDefinition(axis_id=AX, axis_role="other", metric_type="ordinal_single_label",
                       labels=("low", "high"), ordinal_order=("low",), ordinal_weighting="linear")
    with pytest.raises(ValueError):
        AxisDefinition(axis_id=AX, axis_role="other", metric_type="ordinal_single_label",
                       labels=("low", "high"), ordinal_order=("low", "high"), ordinal_weighting=None)


def test_non_ordinal_rejects_ordinal_fields():
    with pytest.raises(ValueError):
        AxisDefinition(axis_id=AX, axis_role="product", metric_type="multi_label",
                       labels=("a", "b"), ordinal_order=("a", "b"))


def test_record_single_label_cardinality(ctx):
    _, rm, _ = ctx
    axis = make_axis(metric_type="nominal_single_label", base=None, labels=("a", "b"), role="other")
    with pytest.raises((ValueError, MetricInputSnapshotError)):
        make_snapshot(rm, axes=(axis,), records=(rec("r", ("a", "b"), ("a",)),))


def test_record_unknown_rejected_on_non_abstention(ctx):
    _, rm, _ = ctx
    axis = make_axis(metric_type="multi_label", base=None, labels=("a", "b"))
    with pytest.raises((ValueError, MetricInputSnapshotError)):
        make_snapshot(rm, axes=(axis,), records=(rec("r", (UNKNOWN,), ("a",)),))


def test_gold_never_contains_unknown_or_screen(ctx):
    _, rm, _ = ctx
    with pytest.raises(ValueError):
        make_snapshot(rm, records=(rec("r", ("a",), (UNKNOWN,)),))
    with pytest.raises(ValueError):
        make_snapshot(rm, records=(rec("r", ("a",), (NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION,)),))


def test_resolvable_requires_gold(ctx):
    _, rm, _ = ctx
    with pytest.raises(ValueError):
        make_snapshot(rm, records=(rec("r", ("a",), (), res="resolvable"),))


def test_conditional_rejects_screen_sentinel(ctx):
    _, rm, _ = ctx
    with pytest.raises((ValueError, MetricInputSnapshotError)):
        make_snapshot(rm, records=(rec("r", (NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION,), ("a",),
                                        scope="conditional"),))


def test_duplicate_record_id_rejected(ctx):
    _, rm, _ = ctx
    with pytest.raises((ValueError, MetricInputSnapshotError)):
        make_snapshot(rm, records=(rec("r", ("a",), ("a",)), rec("r", ("b",), ("b",))))


def test_value_outside_vocabulary_rejected(ctx):
    _, rm, _ = ctx
    with pytest.raises((ValueError, MetricInputSnapshotError)):
        make_snapshot(rm, records=(rec("r", ("z",), ("a",)),))


# --- Axis metrics: multi-label / structured-set / roles -------------------


def test_multi_label_per_label_micro_macro_exact(ctx):
    _, rm, _ = ctx
    records = (rec("r1", ("a",), ("a",)), rec("r2", ("a", "b"), ("b",)))
    rep = compute(ctx, snapshot=make_snapshot(rm, records=records))
    # label a: r1 tp, r2 fp -> precision .5 recall 1
    p = one(rep, METRIC_AXIS_MULTI_LABEL, aggregation="per_label", label="a", measure="precision",
            verification="verified", scope="conditional")
    assert p.value == 0.5
    r = one(rep, METRIC_AXIS_MULTI_LABEL, aggregation="per_label", label="a", measure="recall",
            verification="verified", scope="conditional")
    assert r.value == 1.0
    micro_p = one(rep, METRIC_AXIS_MULTI_LABEL, aggregation="micro", measure="precision",
                  verification="verified", scope="conditional")
    # tp=2 (a in r1, b in r2), fp=1 (a in r2) -> 2/3
    assert abs(micro_p.value - 2 / 3) < 1e-9
    ex = one(rep, METRIC_AXIS_MULTI_LABEL, aggregation="exact_set", measure="agreement",
             verification="verified", scope="conditional")
    assert ex.value == 0.5 and ex.configuration_role == "diagnostic"


def test_product_capability_task_roles_from_axis_role(ctx):
    _, rm, _ = ctx
    axes = tuple(
        AxisDefinition(axis_id=f"ax-{role}", axis_role=role, metric_type="multi_label",
                       base_metric_type=None, labels=("a",))
        for role in ("product", "capability", "task")
    )
    records = tuple(
        AxisEvaluationRecord(record_id=f"r-{role}", case_id=CID, axis_id=f"ax-{role}",
                             metric_scope="conditional", verification_status="verified",
                             evidence_resolvability="resolvable", predicted_values=("a",),
                             gold_values=("a",))
        for role in ("product", "capability", "task")
    )
    config = build_config(rm.scoring_gate_config_version,
                          axis_ids=("ax-product", "ax-capability", "ax-task"),
                          abstention_axes=())
    rep = compute(ctx, snapshot=make_snapshot(rm, axes=axes, records=records), config=config)
    for role in ("product", "capability", "task"):
        m = one(rep, METRIC_AXIS_MULTI_LABEL, axis_role=role, aggregation="micro",
                measure="f1", verification="verified", scope="conditional")
        assert m.value == 1.0


def test_structured_set_axis(ctx):
    _, rm, _ = ctx
    axis = make_axis(metric_type="structured_set", base=None, labels=("a", "b", "c"))
    records = (rec("r1", ("a", "b"), ("a", "c")),)
    config = build_config(rm.scoring_gate_config_version, axis_metric_id=METRIC_AXIS_STRUCTURED_SET,
                          abstention_axes=())
    rep = compute(ctx, snapshot=make_snapshot(rm, axes=(axis,), records=records), config=config)
    micro_p = one(rep, METRIC_AXIS_STRUCTURED_SET, aggregation="element_micro", measure="precision",
                  verification="verified", scope="conditional")
    assert micro_p.value == 0.5  # tp=a(1), fp=b(1)
    # structured-set emits per-record set averages, not multi-label per-label/macro
    assert find(rep, METRIC_AXIS_STRUCTURED_SET, aggregation="set_average", measure="f1",
                verification="verified", scope="conditional")
    assert not find(rep, METRIC_AXIS_STRUCTURED_SET, aggregation="per_label")
    assert not find(rep, METRIC_AXIS_STRUCTURED_SET, aggregation="macro")


def test_nominal_confusion_and_balanced_accuracy(ctx):
    _, rm, _ = ctx
    axis = make_axis(metric_type="nominal_single_label", base=None, labels=("x", "y"), role="other")
    records = (rec("r1", ("x",), ("x",)), rec("r2", ("y",), ("x",)), rec("r3", ("y",), ("y",)))
    config = build_config(rm.scoring_gate_config_version, axis_metric_id=METRIC_AXIS_NOMINAL,
                          abstention_axes=())
    rep = compute(ctx, snapshot=make_snapshot(rm, axes=(axis,), records=records), config=config)
    acc = one(rep, METRIC_AXIS_NOMINAL, aggregation="overall", measure="exact_accuracy",
              verification="verified", scope="conditional")
    assert abs(acc.value - 2 / 3) < 1e-9
    bal = one(rep, METRIC_AXIS_NOMINAL, aggregation="overall", measure="balanced_accuracy",
              verification="verified", scope="conditional")
    # recall x = 1/2, recall y = 1/1 -> 0.75
    assert bal.value == 0.75


def test_ordinal_mae_and_kappa_linear_quadratic(ctx):
    _, rm, _ = ctx
    order = ("low", "mid", "high")
    for weighting in ("linear", "quadratic"):
        axis = AxisDefinition(axis_id=AX, axis_role="other", metric_type="ordinal_single_label",
                              labels=order, ordinal_order=order, ordinal_weighting=weighting)
        records = (rec("r1", ("low",), ("low",)), rec("r2", ("low",), ("high",)),
                   rec("r3", ("mid",), ("mid",)))
        config = build_config(rm.scoring_gate_config_version, axis_metric_id=METRIC_AXIS_ORDINAL,
                              abstention_axes=())
        rep = compute(ctx, snapshot=make_snapshot(rm, axes=(axis,), records=records), config=config)
        mae = one(rep, METRIC_AXIS_ORDINAL, aggregation="overall",
                  measure="mean_absolute_ordinal_distance", verification="verified",
                  scope="conditional")
        assert abs(mae.value - (0 + 2 + 0) / 3) < 1e-9
        kappa = one(rep, METRIC_AXIS_ORDINAL, aggregation="overall", measure="weighted_kappa",
                    verification="verified", scope="conditional")
        assert kappa.status == "computed"


def test_kappa_zero_expected_disagreement(ctx):
    _, rm, _ = ctx
    order = ("low", "high")
    axis = AxisDefinition(axis_id=AX, axis_role="other", metric_type="ordinal_single_label",
                          labels=order, ordinal_order=order, ordinal_weighting="linear")
    # all gold and pred identical single class -> expected disagreement 0, observed 0 -> kappa 1
    records = (rec("r1", ("low",), ("low",)), rec("r2", ("low",), ("low",)))
    config = build_config(rm.scoring_gate_config_version, axis_metric_id=METRIC_AXIS_ORDINAL,
                          abstention_axes=())
    rep = compute(ctx, snapshot=make_snapshot(rm, axes=(axis,), records=records), config=config)
    kappa = one(rep, METRIC_AXIS_ORDINAL, aggregation="overall", measure="weighted_kappa",
                verification="verified", scope="conditional")
    assert kappa.value == 1.0
    # A systematic off-by-one disagreement has non-zero expected disagreement and
    # yields a computed (finite) kappa; the zero-expected/observed>0 branch is
    # defensively unreachable via valid records (expected==0 forces observed==0).
    records2 = (rec("r1", ("high",), ("low",)), rec("r2", ("high",), ("low",)))
    rep2 = compute(ctx, snapshot=make_snapshot(rm, axes=(axis,), records=records2), config=config)
    kappa2 = one(rep2, METRIC_AXIS_ORDINAL, aggregation="overall", measure="weighted_kappa",
                 verification="verified", scope="conditional")
    assert kappa2.status == "computed" and kappa2.value == 0.0


def test_weighted_kappa_zero_expected_helper():
    """The zero-expected/observed>0 defensive branch, exercised directly."""
    from dynamic_ai_products.evaluation.metrics import _weighted_kappa
    st, val, reason = _weighted_kappa((), ("a", "b"), {"a": 0, "b": 1}, 2, "linear")
    assert st == "indeterminate" and reason == "zero_denominator"


def test_zero_denominator_indeterminate(ctx):
    _, rm, _ = ctx
    # no verified records -> per-label metrics have zero denominator
    rep = compute(ctx, snapshot=make_snapshot(rm, records=()))
    m = one(rep, METRIC_AXIS_MULTI_LABEL, aggregation="micro", measure="precision",
            verification="verified", scope="conditional")
    assert m.status == "indeterminate" and m.reason_code == "zero_denominator"


def test_deterministic_ordering_and_bytes(ctx):
    _, rm, _ = ctx
    snap = make_snapshot(rm, records=(rec("r1", ("a",), ("a",)),))
    a = compute(ctx, snapshot=snap)
    b = compute(ctx, snapshot=snap)
    assert a.metrics == b.metrics
    assert a is not b
    assert met._canonical_report_bytes(a) == met._canonical_report_bytes(b)
    keys = [met._sort_key(d) for d in a.metrics]
    assert keys == sorted(keys)


# --- Abstention -----------------------------------------------------------


def test_abstention_family_values(ctx):
    _, rm, _ = ctx
    records = (
        rec("r1", ("a",), ("a",)), rec("r2", ("a",), ("b",)),
        rec("r3", (UNKNOWN,), ("b",)), rec("r4", (UNKNOWN,), (), res="insufficient_evidence"),
    )
    rep = compute(ctx, snapshot=make_snapshot(rm, records=records))
    cov = one(rep, METRIC_AXIS_ABSTENTION, measure="coverage", verification="verified",
              scope="conditional")
    assert cov.value == 0.5  # 2 answered / 4 eligible
    sr = one(rep, METRIC_AXIS_ABSTENTION, measure="selective_risk", verification="verified",
             scope="conditional")
    assert sr.value == 0.5  # 1 incorrect / 2 answered-resolvable
    fc = one(rep, METRIC_AXIS_ABSTENTION, measure="false_confidence", verification="verified",
             scope="conditional")
    assert abs(fc.value - 1 / 3) < 1e-9  # 1 incorrect / 3 resolvable
    ua = one(rep, METRIC_AXIS_ABSTENTION, measure="unnecessary_abstention", verification="verified",
             scope="conditional")
    assert abs(ua.value - 1 / 3) < 1e-9  # 1 UNKNOWN-resolvable / 3 resolvable
    ca = one(rep, METRIC_AXIS_ABSTENTION, measure="correct_abstention", verification="verified",
             scope="conditional")
    assert ca.value == 1.0  # 1 UNKNOWN-insufficient / 1 insufficient


def test_other_and_not_applicable_are_answered(ctx):
    _, rm, _ = ctx
    axis = make_axis(labels=("a", OTHER, NOT_APPLICABLE))
    records = (rec("r1", (OTHER,), (OTHER,)), rec("r2", (NOT_APPLICABLE,), (NOT_APPLICABLE,)))
    rep = compute(ctx, snapshot=make_snapshot(rm, axes=(axis,), records=records))
    cov = one(rep, METRIC_AXIS_ABSTENTION, measure="coverage", verification="verified",
              scope="conditional")
    assert cov.value == 1.0  # OTHER/NOT_APPLICABLE are answered, not abstention


def test_screen_exclusion_in_end_to_end_denominator(ctx):
    _, rm, _ = ctx
    records = (
        rec("r1", ("a",), ("a",), scope="end_to_end"),
        rec("r2", (NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION,), ("b",), scope="end_to_end"),
    )
    rep = compute(ctx, snapshot=make_snapshot(rm, records=records))
    cov = one(rep, METRIC_AXIS_ABSTENTION, measure="coverage", verification="verified",
              scope="end_to_end")
    assert cov.value == 0.5  # 1 answered / 2 eligible (screen-excluded retained)
    fc = one(rep, METRIC_AXIS_ABSTENTION, measure="false_confidence", verification="verified",
             scope="end_to_end")
    # screen-excluded r2 with resolvable gold counts as incorrect: 1 / 2 resolvable
    assert fc.value == 0.5


def test_conditional_and_end_to_end_differ(ctx):
    _, rm, _ = ctx
    records = (rec("r1", ("a",), ("a",), scope="conditional"),
              rec("r2", ("a",), ("a",), scope="end_to_end"))
    rep = compute(ctx, snapshot=make_snapshot(rm, records=records))
    cond = find(rep, METRIC_AXIS_ABSTENTION, scope="conditional", verification="verified")
    e2e = find(rep, METRIC_AXIS_ABSTENTION, scope="end_to_end", verification="verified")
    assert cond and e2e and cond != e2e


# --- Verified/provisional and support -------------------------------------


def test_verified_and_provisional_reported_separately(ctx):
    _, rm, _ = ctx
    records = (rec("r1", ("a",), ("a",), ver="verified"),
              rec("r2", ("a",), ("a",), ver="provisional"))
    rep = compute(ctx, snapshot=make_snapshot(rm, records=records))
    v = find(rep, METRIC_AXIS_MULTI_LABEL, verification="verified")
    p = find(rep, METRIC_AXIS_MULTI_LABEL, verification="provisional")
    assert v and p
    # provisional metrics are always diagnostic role
    assert all(d.configuration_role == "diagnostic" for d in p)


def test_low_support_yields_insufficient_evaluation_evidence(ctx):
    _, rm, _ = ctx
    config = build_config(rm.scoring_gate_config_version, axis_minimum=5)
    rep = compute(ctx, snapshot=make_snapshot(rm, records=(rec("r1", ("a",), ("a",)),)),
                  config=config)
    m = one(rep, METRIC_AXIS_MULTI_LABEL, aggregation="micro", measure="precision",
            verification="verified", scope="conditional")
    assert m.status == "indeterminate" and m.reason_code == "insufficient_evaluation_evidence"
    # counts/support still reported
    assert m.support.minimum_verified_support == 5


def test_missing_metric_policy_rejected(ctx):
    _, rm, _ = ctx
    # config missing the axis policy
    config = build_config(rm.scoring_gate_config_version, axis_ids=(), abstention_axes=())
    with pytest.raises(MetricPolicyError):
        compute(ctx, snapshot=make_snapshot(rm, records=(rec("r1", ("a",), ("a",)),)), config=config)


def test_malformed_support_policy_rejected(ctx):
    _, rm, _ = ctx
    bad_gate = _gate(METRIC_TIER_CONTRACT, "overall", support={"minimum_verified_support": -1})
    config = build_config(rm.scoring_gate_config_version)
    config = config.model_copy(update={
        "gates": tuple(g for g in config.gates if g.metric_id != METRIC_TIER_CONTRACT) + (bad_gate,)
    })
    with pytest.raises(MetricPolicyError):
        compute(ctx, config=config)


# --- Assertion diagnostics ------------------------------------------------


def test_assertion_outcome_diagnostics_all_five(ctx):
    _, rm, _ = ctx
    bindings = tuple(
        AssertionMetricBinding(case_id=CID, assertion_id=f"A{i}", assertion_kind="expected_entity",
                               partition=PART, suites=SUITES)
        for i in range(5)
    )
    values = ("satisfied", "unsatisfied", "indeterminate", "not_applicable", "not_evaluated")
    outcomes = tuple(ao(case_id=CID, assertion_id=f"A{i}", outcome=v) for i, v in enumerate(values))
    rep = compute(ctx, snapshot=make_snapshot(rm, bindings=bindings), outcomes=outcomes)
    for v in values:
        m = one(rep, METRIC_ASSERTION_OUTCOMES, grouping="outcome", outcome=v)
        assert m.numerator == 1 and abs(m.value - 0.2) < 1e-9


def test_assertion_binding_mismatch(ctx):
    _, rm, _ = ctx
    # binding present but outcome missing
    bindings = (AssertionMetricBinding(case_id=CID, assertion_id="A1",
                                       assertion_kind="expected_entity", partition=PART,
                                       suites=SUITES),
                AssertionMetricBinding(case_id=CID, assertion_id="A2",
                                       assertion_kind="expected_entity", partition=PART,
                                       suites=SUITES))
    with pytest.raises(AssertionBindingMismatchError):
        compute(ctx, snapshot=make_snapshot(rm, bindings=bindings), outcomes=(ao(),))


# --- Validator metrics ----------------------------------------------------


def test_validator_denominator_and_rates(ctx):
    _, rm, _ = ctx
    execs = (ValidatorRuleEvaluationRecord(artifact_id="art1", rule_id="source_id_resolution",
                                           evaluated_observation_count=4, failed_observation_count=1),)
    rep = compute(ctx, snapshot=make_snapshot(rm, execs=execs), findings=(vf(),))
    fr = one(rep, METRIC_VALIDATOR_RULES, measure="failure_rate", rule="source_id_resolution")
    assert fr.value == 0.25 and fr.denominator == 4  # denominator from executions, not findings
    pr = one(rep, METRIC_VALIDATOR_RULES, measure="pass_rate", rule="source_id_resolution")
    assert pr.value == 0.75


def test_validator_summary_mappings(ctx):
    _, rm, _ = ctx
    execs = (
        ValidatorRuleEvaluationRecord(artifact_id="a", rule_id="output_json_schema_validity",
                                      evaluated_observation_count=2, failed_observation_count=0),
        ValidatorRuleEvaluationRecord(artifact_id="a", rule_id="publication_date_cutoff",
                                      evaluated_observation_count=2, failed_observation_count=1),
    )
    findings = (vf(finding_id="f1", validator="publication_date_cutoff", artifact_id="a"),)
    rep = compute(ctx, snapshot=make_snapshot(rm, execs=execs), findings=findings)
    schema = one(rep, METRIC_VALIDATOR_SUMMARIES, measure="schema_validity_rate")
    assert schema.value == 1.0
    temporal = one(rep, METRIC_VALIDATOR_SUMMARIES, measure="temporal_leakage_count")
    assert temporal.value == 1


def test_validator_finding_without_execution_rejected(ctx):
    _, rm, _ = ctx
    execs = ()
    with pytest.raises(ValidatorExecutionMismatchError):
        compute(ctx, snapshot=make_snapshot(rm, execs=execs), findings=(vf(),))


def test_validator_failed_count_mismatch_rejected(ctx):
    _, rm, _ = ctx
    execs = (ValidatorRuleEvaluationRecord(artifact_id="art1", rule_id="source_id_resolution",
                                           evaluated_observation_count=5, failed_observation_count=2),)
    with pytest.raises(ValidatorExecutionMismatchError):
        compute(ctx, snapshot=make_snapshot(rm, execs=execs), findings=(vf(),))


def test_validator_impossible_counts_rejected():
    with pytest.raises(ValueError):
        ValidatorRuleEvaluationRecord(artifact_id="a", rule_id="source_id_resolution",
                                      evaluated_observation_count=1, failed_observation_count=2)


# --- Tier contract --------------------------------------------------------


def test_tier_exact_and_mismatch(ctx):
    _, rm, _ = ctx
    tiers = (tier_obs("t1", exact=True), tier_obs("t2", exact=False))
    rep = compute(ctx, snapshot=make_snapshot(rm, tiers=tiers))
    rate = one(rep, METRIC_TIER_CONTRACT, measure="exact_contract_match_rate",
               verification="verified")
    assert rate.value == 0.5
    tm = one(rep, METRIC_TIER_CONTRACT, measure="tier_mismatch_count", verification="verified")
    assert tm.value == 1
    rf = one(rep, METRIC_TIER_CONTRACT, measure="repeatability_failure_count",
             verification="verified")
    assert rf.value == 1


def test_tier_requires_two_repeatability_hashes():
    with pytest.raises(ValueError):
        TierContractObservation(record_id="t", verification_status="verified",
                                tier_rule_version="v", expected_tier="A", observed_tier="A",
                                expected_reason_codes=(), observed_reason_codes=(),
                                expected_rule_trace_hash="c" * 64, observed_rule_trace_hash="c" * 64,
                                repeatability_output_hashes=("d" * 64,))


# --- Unsafe exclusion -----------------------------------------------------


def test_unsafe_single_stratum_weighted_rate_and_wilson(ctx):
    _, rm, _ = ctx
    aud = audit_snapshot((audit(missed=1, n=2, pop=100, stratum="s1"),))
    rep = compute(ctx, snapshot=make_snapshot(rm, aud=aud))
    rate = one(rep, METRIC_UNSAFE_EXCLUSION, measure="weighted_unsafe_exclusion_rate",
               scope="overall")
    assert rate.value == 0.5 and rate.configuration_role == "gate_input"
    assert rate.confidence_interval is not None
    assert rate.confidence_interval.method == "wilson_one_sided_stratified"
    ub = one(rep, METRIC_UNSAFE_EXCLUSION, measure="weighted_upper_confidence_bound",
             scope="overall")
    assert 0.5 < ub.value < 1.0  # upper bound above the point estimate
    missed = one(rep, METRIC_UNSAFE_EXCLUSION, measure="estimated_absolute_missed", scope="overall")
    assert missed.value == 50.0  # 100 * 0.5


def test_unsafe_multiple_strata(ctx):
    _, rm, _ = ctx
    aud = audit_snapshot((audit(missed=1, n=4, pop=100, stratum="s1"),
                          audit(missed=0, n=4, pop=100, stratum="s2")))
    rep = compute(ctx, snapshot=make_snapshot(rm, aud=aud))
    rate = one(rep, METRIC_UNSAFE_EXCLUSION, measure="weighted_unsafe_exclusion_rate",
               scope="overall")
    # (100*0.25 + 100*0.0)/200 = 0.125
    assert rate.value == 0.125


def test_unsafe_low_support_stratum_makes_overall_indeterminate(ctx):
    _, rm, _ = ctx
    config = build_config(rm.scoring_gate_config_version, unsafe_min=5)
    aud = audit_snapshot((audit(missed=1, n=2, pop=100, stratum="s1"),))
    rep = compute(ctx, snapshot=make_snapshot(rm, aud=aud), config=config)
    rate = one(rep, METRIC_UNSAFE_EXCLUSION, measure="weighted_unsafe_exclusion_rate",
               scope="overall")
    assert rate.status == "indeterminate" and rate.reason_code == "insufficient_audit_evidence"
    # per-stratum diagnostic count retained
    cnt = one(rep, METRIC_UNSAFE_EXCLUSION, measure="stratum_missed_count", stratum="s1")
    assert cnt.value == 1


def test_unsafe_missing_ci_policy_rejected(ctx):
    _, rm, _ = ctx
    config = build_config(rm.scoring_gate_config_version)
    # drop the unsafe gate
    config = config.model_copy(update={
        "gates": tuple(g for g in config.gates if g.metric_id != METRIC_UNSAFE_EXCLUSION)
    })
    with pytest.raises(UnsafeAuditPolicyError):
        compute(ctx, snapshot=make_snapshot(rm, stage="universe_screen"), config=config)


def test_unsafe_bad_confidence_level_rejected(ctx):
    _, rm, _ = ctx
    config = build_config(rm.scoring_gate_config_version, confidence=0.4)
    with pytest.raises(UnsafeAuditPolicyError):
        compute(ctx, snapshot=make_snapshot(rm, stage="universe_screen"), config=config)


def test_unsafe_audit_labels_must_be_verified():
    with pytest.raises(ValueError):
        UnsafeAuditLabel(record_id="r", verification_status="provisional",
                         actually_eligible_or_boundary_relevant=True)


def test_unsafe_audited_cannot_exceed_population():
    with pytest.raises(ValueError):
        UnsafeAuditStratum(stratum_id="s", screen_negative_population_count=1,
                           audited_labels=(
                               UnsafeAuditLabel(record_id="a", verification_status="verified",
                                                actually_eligible_or_boundary_relevant=False),
                               UnsafeAuditLabel(record_id="b", verification_status="verified",
                                                actually_eligible_or_boundary_relevant=False)))


# --- Operational diagnostics ----------------------------------------------


def test_operational_diagnostics(ctx):
    _, rm, _ = ctx
    rep = compute(ctx, snapshot=make_snapshot(rm, stage="universe_screen"))
    pt = one(rep, METRIC_SCREEN_OPERATIONAL, measure="pass_through_rate")
    assert pt.value == 0.5  # 5 / 10
    ur = one(rep, METRIC_SCREEN_OPERATIONAL, measure="unresolved_share")
    assert ur.value == 0.1  # 1 / 10


def test_operational_count_conservation_enforced():
    with pytest.raises(ValueError):
        ScreenOperationalSummary(total_screened=10, screen_negative=4, screen_nonnegative=4,
                                 unresolved=1, downstream_review_count=0)


# --- Stage-aware family dispatch (Slice 12I) ------------------------------


def test_dispatch_extraction_only_axis_assertion_validator(ctx):
    _, rm, _ = ctx
    rep = compute(ctx, snapshot=make_snapshot(rm, stage="capability_extraction"))
    fams = {d.metric_id for d in rep.metrics}
    assert METRIC_TIER_CONTRACT not in fams
    assert METRIC_UNSAFE_EXCLUSION not in fams
    assert METRIC_SCREEN_OPERATIONAL not in fams
    assert METRIC_AXIS_MULTI_LABEL in fams  # axis applicable
    assert METRIC_ASSERTION_OUTCOMES in fams and METRIC_VALIDATOR_RULES in fams


def test_dispatch_classification_adds_tier(ctx):
    _, rm, _ = ctx
    rep = compute(ctx, snapshot=make_snapshot(rm, stage="universe_classification"))
    fams = {d.metric_id for d in rep.metrics}
    assert METRIC_TIER_CONTRACT in fams and METRIC_AXIS_MULTI_LABEL in fams
    assert METRIC_UNSAFE_EXCLUSION not in fams and METRIC_SCREEN_OPERATIONAL not in fams


def test_dispatch_screen_has_screen_and_unsafe_no_axis(ctx):
    _, rm, _ = ctx
    rep = compute(ctx, snapshot=make_snapshot(rm, stage="universe_screen"))
    fams = {d.metric_id for d in rep.metrics}
    assert METRIC_SCREEN_OPERATIONAL in fams and METRIC_UNSAFE_EXCLUSION in fams
    assert METRIC_TIER_CONTRACT not in fams
    assert not any(f.startswith("axis_") for f in fams)


# --- Snapshot hash and binding --------------------------------------------


def test_snapshot_hash_deterministic(ctx):
    _, rm, _ = ctx
    s = make_snapshot(rm)
    assert metric_input_snapshot_hash(s) == metric_input_snapshot_hash(s)
    assert len(metric_input_snapshot_hash(s)) == 64


def test_snapshot_run_binding_mismatch(ctx):
    _, rm, cfg = ctx
    bad = make_snapshot(rm).model_copy(update={"eval_run_id": "other"})
    with pytest.raises(SnapshotBindingError):
        compute_metric_report(bad, assertion_outcomes=(ao(),), validator_findings=(vf(),),
                              run_manifest=rm, case_set_manifest=CASE_SET,
                              scoring_config=loaded(cfg, rm))


# --- Pure-function boundary -----------------------------------------------


def test_compute_touches_no_filesystem(ctx, monkeypatch):
    calls = []

    def spy(name, orig):
        def wrapper(*a, **k):
            calls.append(name)
            return orig(*a, **k)
        return wrapper

    monkeypatch.setattr(Path, "read_bytes", spy("read_bytes", Path.read_bytes))
    monkeypatch.setattr(Path, "write_bytes", spy("write_bytes", Path.write_bytes))
    monkeypatch.setattr(Path, "mkdir", spy("mkdir", Path.mkdir))
    monkeypatch.setattr(os, "open", spy("os.open", os.open))
    compute(ctx)
    assert calls == []


def test_report_has_no_status_or_verdict(ctx):
    rep = compute(ctx)
    fields = set(type(rep).model_fields)
    assert "execution_status" not in fields and "gate_verdict" not in fields
    assert fields == {
        "contract", "eval_run_id", "case_set_version", "case_set_hash",
        "scoring_gate_config_version", "scoring_gate_config_hash",
        "metric_input_snapshot_hash", "metrics",
    }


# --- Persistence ----------------------------------------------------------


def test_persist_and_load_roundtrip(ctx):
    tmp_path, rm, _ = ctx
    rep = compute(ctx)
    persisted = persist_metric_report(rep, eval_root=tmp_path, eval_run_id="run1")
    assert isinstance(persisted, PersistedMetricReport)
    assert persisted.artifact_reference == "run1/metrics/metric_report.json"
    dest = tmp_path / "run1" / "metrics" / "metric_report.json"
    assert sha256_bytes(dest.read_bytes()) == persisted.sha256
    loaded = load_metric_report("run1", eval_root=tmp_path)
    assert isinstance(loaded, LoadedMetricReport)
    assert loaded.report.model_dump() == rep.model_dump()


def test_persist_is_write_once(ctx):
    tmp_path, rm, _ = ctx
    rep = compute(ctx)
    persist_metric_report(rep, eval_root=tmp_path, eval_run_id="run1")
    with pytest.raises(MetricReportExistsError):
        persist_metric_report(rep, eval_root=tmp_path, eval_run_id="run1")


def test_persist_rejects_file_collision(ctx):
    tmp_path, rm, _ = ctx
    (tmp_path / "run1" / "metrics").write_bytes(b"occupied")
    with pytest.raises(MetricReportExistsError):
        persist_metric_report(compute(ctx), eval_root=tmp_path, eval_run_id="run1")
    assert (tmp_path / "run1" / "metrics").read_bytes() == b"occupied"


def test_persist_rejects_symlink(ctx):
    tmp_path, rm, _ = ctx
    target = tmp_path / "elsewhere"
    target.mkdir()
    (tmp_path / "run1" / "metrics").symlink_to(target)
    with pytest.raises(MetricReportExistsError):
        persist_metric_report(compute(ctx), eval_root=tmp_path, eval_run_id="run1")


def test_persist_rejects_dangling_symlink(ctx):
    tmp_path, rm, _ = ctx
    (tmp_path / "run1" / "metrics").symlink_to(tmp_path / "nope")
    with pytest.raises(MetricReportExistsError):
        persist_metric_report(compute(ctx), eval_root=tmp_path, eval_run_id="run1")


def test_write_failure_preserves_directory(ctx, monkeypatch):
    tmp_path, rm, _ = ctx
    rep = compute(ctx)

    def boom(*a, **k):
        raise OSError("synthetic")

    monkeypatch.setattr(met.os, "open", boom)
    with pytest.raises(MetricWriteError):
        persist_metric_report(rep, eval_root=tmp_path, eval_run_id="run1")
    monkeypatch.undo()
    d = tmp_path / "run1" / "metrics"
    assert d.is_dir() and list(d.iterdir()) == []
    with pytest.raises(MetricReportExistsError):
        persist_metric_report(rep, eval_root=tmp_path, eval_run_id="run1")


def test_persist_rejects_report_binding_mismatch(ctx):
    tmp_path, rm, _ = ctx
    rep = compute(ctx).model_copy(update={"eval_run_id": "other"})
    with pytest.raises(MetricReportBindingError):
        persist_metric_report(rep, eval_root=tmp_path, eval_run_id="run1")


def write_metrics_dir(tmp_path, data: bytes):
    d = tmp_path / "run1" / "metrics"
    d.mkdir(parents=True, exist_ok=False)
    (d / "metric_report.json").write_bytes(data)


def test_load_missing(ctx):
    tmp_path, rm, _ = ctx
    with pytest.raises(MetricArtifactMissingError):
        load_metric_report("run1", eval_root=tmp_path)


def test_load_rejects_non_utf8(ctx):
    tmp_path, rm, _ = ctx
    write_metrics_dir(tmp_path, b"\xff\xfe")
    with pytest.raises(MetricDecodeError):
        load_metric_report("run1", eval_root=tmp_path)


def test_load_rejects_bom(ctx):
    tmp_path, rm, _ = ctx
    rep = compute(ctx)
    write_metrics_dir(tmp_path, "\ufeff".encode("utf-8") + met._canonical_report_bytes(rep))
    with pytest.raises(MetricJsonError):
        load_metric_report("run1", eval_root=tmp_path)


def test_load_rejects_trailing_data(ctx):
    tmp_path, rm, _ = ctx
    rep = compute(ctx)
    write_metrics_dir(tmp_path, met._canonical_report_bytes(rep) + b" trailing")
    with pytest.raises(MetricJsonError):
        load_metric_report("run1", eval_root=tmp_path)


def test_load_rejects_duplicate_keys(ctx):
    tmp_path, rm, _ = ctx
    write_metrics_dir(tmp_path, b'{"a":1,"a":2}')
    with pytest.raises(MetricJsonError) as exc:
        load_metric_report("run1", eval_root=tmp_path)
    assert exc.value.duplicate_key == "a"


def test_load_rejects_non_object(ctx):
    tmp_path, rm, _ = ctx
    write_metrics_dir(tmp_path, b"[1,2]")
    with pytest.raises(MetricTopLevelTypeError):
        load_metric_report("run1", eval_root=tmp_path)


def test_load_rejects_model_invalid(ctx):
    tmp_path, rm, _ = ctx
    write_metrics_dir(tmp_path, b'{"unexpected":true}')
    with pytest.raises(MetricModelValidationError):
        load_metric_report("run1", eval_root=tmp_path)


def test_load_rejects_symlinked_run_dir(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    init_run(real, "run1")
    (tmp_path / "run1").symlink_to(real / "run1")
    with pytest.raises(RunArtifactNotAFileError):
        load_metric_report("run1", eval_root=tmp_path)


def test_load_rejects_symlinked_metrics_dir(ctx):
    tmp_path, rm, _ = ctx
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "metric_report.json").write_bytes(b"{}")
    (tmp_path / "run1" / "metrics").symlink_to(outside)
    with pytest.raises(MetricArtifactNotAFileError):
        load_metric_report("run1", eval_root=tmp_path)


def test_repeated_loads_equal_but_distinct(ctx):
    tmp_path, rm, _ = ctx
    persist_metric_report(compute(ctx), eval_root=tmp_path, eval_run_id="run1")
    a = load_metric_report("run1", eval_root=tmp_path)
    b = load_metric_report("run1", eval_root=tmp_path)
    assert a is not b and a.report is not b.report
    assert a.report.model_dump() == b.report.model_dump()


def test_invalid_eval_root_rejected():
    with pytest.raises(InvalidEvaluationRootError):
        load_metric_report("run1", eval_root="")


# --- Duplicate metric identity --------------------------------------------


def test_report_rejects_duplicate_metric_identity():
    from dynamic_ai_products.evaluation.metrics import MetricDatum, MetricDimension, MetricSupport
    support = MetricSupport(verified_support=0, provisional_support=0, total_support=0,
                            applicable_denominator=0, minimum_verified_support=0)
    d = MetricDatum(metric_id="m", population_slice_id="s", configuration_role="diagnostic",
                    status="computed", value=1, support=support,
                    dimensions=(MetricDimension(key="k", value="v"),))
    meta = {"contract_id": "metric_report", "contract_version": "0.1.0",
            "contract_hash": model_contract_hash(MetricReport, "metric_report", "0.1.0")}
    with pytest.raises(ValueError):
        MetricReport.model_validate({
            "contract": meta, "eval_run_id": "r", "case_set_version": "v", "case_set_hash": "a" * 64,
            "scoring_gate_config_version": "cv", "scoring_gate_config_hash": "b" * 64,
            "metric_input_snapshot_hash": "c" * 64,
            "metrics": [d.model_dump(mode="json"), d.model_dump(mode="json")],
        })


# --- Revision defects: structured-set / scope / nominal / ordinal ---------


def test_structured_set_per_record_averages(ctx):
    _, rm, _ = ctx
    axis = make_axis(metric_type="structured_set", base=None, labels=("a", "b", "c", "d"))
    # r1: pred {a,b} gold {a,c} -> inter1, p=1/2, r=1/2, f1=2/4
    # r2: pred {a} gold {a}    -> p=1, r=1, f1=1
    records = (rec("r1", ("a", "b"), ("a", "c")), rec("r2", ("a",), ("a",)))
    config = build_config(rm.scoring_gate_config_version, axis_metric_id=METRIC_AXIS_STRUCTURED_SET)
    rep = compute(ctx, snapshot=make_snapshot(rm, axes=(axis,), records=records), config=config)
    avg_p = one(rep, METRIC_AXIS_STRUCTURED_SET, aggregation="set_average", measure="precision",
                verification="verified", scope="conditional")
    assert avg_p.value == 0.75  # (0.5 + 1.0)/2
    avg_f1 = one(rep, METRIC_AXIS_STRUCTURED_SET, aggregation="set_average", measure="f1",
                 verification="verified", scope="conditional")
    assert avg_f1.value == 0.75  # (0.5 + 1.0)/2


def test_structured_set_terminal_precision_indeterminate(ctx):
    _, rm, _ = ctx
    axis = make_axis(metric_type="abstention_allowed", base="structured_set", labels=("a", "b"))
    # end-to-end UNKNOWN record has |pred|=0 -> per-record precision undefined -> avg indeterminate
    records = (rec("r1", (UNKNOWN,), ("a",), scope="end_to_end"),)
    config = build_config(rm.scoring_gate_config_version, axis_metric_id=METRIC_AXIS_STRUCTURED_SET)
    rep = compute(ctx, snapshot=make_snapshot(rm, axes=(axis,), records=records), config=config)
    avg_p = one(rep, METRIC_AXIS_STRUCTURED_SET, aggregation="set_average", measure="precision",
                verification="verified", scope="end_to_end")
    assert avg_p.status == "indeterminate" and avg_p.reason_code == "zero_denominator"
    avg_r = one(rep, METRIC_AXIS_STRUCTURED_SET, aggregation="set_average", measure="recall",
                verification="verified", scope="end_to_end")
    assert avg_r.status == "computed" and avg_r.value == 0.0  # recall defined (gold nonempty)


def test_conditional_and_end_to_end_support_differ_with_unknown(ctx):
    _, rm, _ = ctx
    records = (
        rec("r1", ("a",), ("a",), scope="conditional"),
        rec("r2", ("a",), ("a",), scope="end_to_end"),
        rec("r3", (UNKNOWN,), ("b",), scope="end_to_end"),
    )
    rep = compute(ctx, snapshot=make_snapshot(rm, records=records))
    cond = one(rep, METRIC_AXIS_MULTI_LABEL, aggregation="micro", measure="recall",
               verification="verified", scope="conditional")
    e2e = one(rep, METRIC_AXIS_MULTI_LABEL, aggregation="micro", measure="recall",
              verification="verified", scope="end_to_end")
    assert cond.support.applicable_denominator == 1        # answered resolvable
    assert e2e.support.applicable_denominator == 2         # all resolvable (UNKNOWN retained)
    assert cond.value == 1.0                               # 1 tp / 1 gold
    assert e2e.value == 0.5                                # 1 tp / 2 gold (UNKNOWN -> FN)


def test_nominal_confusion_cells_and_terminal(ctx):
    _, rm, _ = ctx
    axis = make_axis(metric_type="abstention_allowed", base="nominal_single_label",
                     labels=("x", "y"), role="other")
    records = (
        rec("r1", ("x",), ("x",), scope="end_to_end"),
        rec("r2", (UNKNOWN,), ("y",), scope="end_to_end"),
    )
    config = build_config(rm.scoring_gate_config_version, axis_metric_id=METRIC_AXIS_NOMINAL)
    rep = compute(ctx, snapshot=make_snapshot(rm, axes=(axis,), records=records), config=config)
    # confusion cell (gold=y, predicted=UNKNOWN) == 1
    cell = one(rep, METRIC_AXIS_NOMINAL, aggregation="confusion_matrix", gold="y",
               predicted=UNKNOWN, verification="verified", scope="end_to_end")
    assert cell.value == 1
    # zero-count declared cell still emitted
    zero_cell = one(rep, METRIC_AXIS_NOMINAL, aggregation="confusion_matrix", gold="x",
                    predicted="y", verification="verified", scope="end_to_end")
    assert zero_cell.value == 0
    # terminal contributes FN to gold y (recall y = 0/1), not a class precision for UNKNOWN
    rec_y = one(rep, METRIC_AXIS_NOMINAL, aggregation="per_class", label="y", measure="recall",
                verification="verified", scope="end_to_end")
    assert rec_y.value == 0.0
    # exact accuracy end-to-end: 1 correct / 2 resolvable
    acc = one(rep, METRIC_AXIS_NOMINAL, aggregation="overall", measure="exact_accuracy",
              verification="verified", scope="end_to_end")
    assert acc.value == 0.5


def test_ordinal_end_to_end_terminal_nonordinal(ctx):
    _, rm, _ = ctx
    order = ("low", "high")
    axis = AxisDefinition(axis_id=AX, axis_role="other", metric_type="abstention_allowed",
                          base_metric_type="ordinal_single_label", labels=order,
                          ordinal_order=order, ordinal_weighting="linear")
    config = build_config(rm.scoring_gate_config_version, axis_metric_id=METRIC_AXIS_ORDINAL)
    for terminal in (UNKNOWN, NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION):
        records = (
            rec("r1", ("low",), ("low",), scope="end_to_end"),
            rec("r2", (terminal,), ("high",), scope="end_to_end"),
        )
        rep = compute(ctx, snapshot=make_snapshot(rm, axes=(axis,), records=records), config=config)
        mae = one(rep, METRIC_AXIS_ORDINAL, aggregation="overall",
                  measure="mean_absolute_ordinal_distance", verification="verified",
                  scope="end_to_end")
        assert mae.status == "indeterminate" and mae.reason_code == "nonordinal_terminal_outcome"
        kappa = one(rep, METRIC_AXIS_ORDINAL, aggregation="overall", measure="weighted_kappa",
                    verification="verified", scope="end_to_end")
        assert kappa.reason_code == "nonordinal_terminal_outcome"
        # exact agreement still computed over all resolvable (terminal incorrect)
        exact = one(rep, METRIC_AXIS_ORDINAL, aggregation="overall", measure="exact_agreement",
                    verification="verified", scope="end_to_end")
        assert exact.value == 0.5


def test_coverage_family_emitted_for_non_abstention_axis(ctx):
    _, rm, _ = ctx
    axis = make_axis(metric_type="nominal_single_label", base=None, labels=("x", "y"), role="other")
    records = (rec("r1", ("x",), ("x",)), rec("r2", ("y",), ("x",)))
    config = build_config(rm.scoring_gate_config_version, axis_metric_id=METRIC_AXIS_NOMINAL)
    rep = compute(ctx, snapshot=make_snapshot(rm, axes=(axis,), records=records), config=config)
    cov = one(rep, METRIC_AXIS_ABSTENTION, measure="coverage", verification="verified",
              scope="conditional")
    assert cov.value == 1.0  # no abstention possible; all answered
    sr = one(rep, METRIC_AXIS_ABSTENTION, measure="selective_risk", verification="verified",
             scope="conditional")
    assert sr.value == 0.5  # r2 wrong (pred y, gold x)
    ua = one(rep, METRIC_AXIS_ABSTENTION, measure="unnecessary_abstention", verification="verified",
             scope="conditional")
    assert ua.numerator == 0  # no UNKNOWN on a non-abstention axis


# --- Revision defects: minimum support, run/case binding, artifact hash ----


def test_low_support_validator_rule(ctx):
    _, rm, _ = ctx
    config = build_config(rm.scoring_gate_config_version, validator_minimum=100)
    execs = (ValidatorRuleEvaluationRecord(artifact_id="a", rule_id="source_id_resolution",
                                           evaluated_observation_count=4, failed_observation_count=1),)
    rep = compute(ctx, snapshot=make_snapshot(rm, execs=execs),
                  findings=(vf(artifact_id="a"),), config=config)
    fr = one(rep, METRIC_VALIDATOR_RULES, measure="failure_rate", rule="source_id_resolution")
    assert fr.status == "indeterminate" and fr.reason_code == "insufficient_evaluation_evidence"
    # count stays computed
    fc = one(rep, METRIC_VALIDATOR_RULES, measure="failure_count", rule="source_id_resolution")
    assert fc.status == "computed" and fc.value == 1


def test_low_support_validator_summary(ctx):
    _, rm, _ = ctx
    config = build_config(rm.scoring_gate_config_version, validator_minimum=100)
    execs = (ValidatorRuleEvaluationRecord(artifact_id="a", rule_id="output_json_schema_validity",
                                           evaluated_observation_count=2, failed_observation_count=0),)
    rep = compute(ctx, snapshot=make_snapshot(rm, execs=execs), findings=(), config=config)
    schema = one(rep, METRIC_VALIDATOR_SUMMARIES, measure="schema_validity_rate")
    assert schema.status == "indeterminate" and schema.reason_code == "insufficient_evaluation_evidence"


def test_low_support_assertion_proportion(ctx):
    _, rm, _ = ctx
    config = build_config(rm.scoring_gate_config_version, assertion_minimum=100)
    rep = compute(ctx, config=config)
    m = one(rep, METRIC_ASSERTION_OUTCOMES, grouping="outcome", outcome="satisfied")
    assert m.status == "indeterminate" and m.reason_code == "insufficient_evaluation_evidence"


def test_low_support_operational_rate(ctx):
    _, rm, _ = ctx
    config = build_config(rm.scoring_gate_config_version, operational_minimum=100)
    rep = compute(ctx, snapshot=make_snapshot(rm, stage="universe_screen"), config=config)
    pt = one(rep, METRIC_SCREEN_OPERATIONAL, measure="pass_through_rate")
    assert pt.status == "indeterminate" and pt.reason_code == "insufficient_evaluation_evidence"


def test_validator_summary_support_is_group_only(ctx):
    _, rm, _ = ctx
    # A large unrelated-rule eval count must not lift the schema group's support.
    config = build_config(rm.scoring_gate_config_version, validator_minimum=5)
    execs = (
        ValidatorRuleEvaluationRecord(artifact_id="a", rule_id="output_json_schema_validity",
                                      evaluated_observation_count=2, failed_observation_count=0),
        ValidatorRuleEvaluationRecord(artifact_id="a", rule_id="unique_ids_within_scope",
                                      evaluated_observation_count=50, failed_observation_count=0),
    )
    rep = compute(ctx, snapshot=make_snapshot(rm, execs=execs), findings=(), config=config)
    schema = one(rep, METRIC_VALIDATOR_SUMMARIES, measure="schema_validity_rate")
    # schema group evaluated=2 < 5 -> indeterminate despite the 50 unrelated evaluations
    assert schema.status == "indeterminate"


def test_outcome_run_binding_mismatch(ctx):
    _, rm, cfg = ctx
    bad = AssertionOutcome.model_validate({
        "contract": AO_META, "eval_run_id": "other", "case_id": CID, "assertion_id": "A1",
        "assertion_semantic_version": "0.1.0", "outcome": "satisfied"})
    with pytest.raises(OutcomeRunBindingError):
        compute(ctx, outcomes=(bad,))


def test_finding_run_binding_mismatch(ctx):
    _, rm, _ = ctx
    bad = ValidatorFinding.model_validate({
        "contract": VF_META, "finding_id": "f1", "validator": "source_id_resolution",
        "validator_bundle_version": "vb", "validator_bundle_hash": "b" * 64, "rule_params_hash": HEX,
        "severity": "error", "run_id": "other", "artifact_id": "art1", "observed_value": "x",
        "expected_invariant": "y", "message": "m", "evidence": "e", "repairable": False,
        "created_at": "2026-07-20T00:00:00Z"})
    execs = (ValidatorRuleEvaluationRecord(artifact_id="art1", rule_id="source_id_resolution",
                                           evaluated_observation_count=1, failed_observation_count=1),)
    with pytest.raises(FindingRunBindingError):
        compute(ctx, snapshot=make_snapshot(rm, execs=execs), findings=(bad,))


def test_axis_record_unknown_case_rejected(ctx):
    _, rm, _ = ctx
    with pytest.raises(CaseMembershipBindingError) as exc:
        compute(ctx, snapshot=make_snapshot(rm, records=(rec("r1", ("a",), ("a",), case="NOPE"),)))
    assert exc.value.binding_kind == "unknown_case"


def test_binding_partition_mismatch_rejected(ctx):
    _, rm, _ = ctx
    bindings = (AssertionMetricBinding(case_id=CID, assertion_id="A1",
                                       assertion_kind="expected_entity", partition="frozen_test",
                                       suites=SUITES),)
    with pytest.raises(CaseMembershipBindingError) as exc:
        compute(ctx, snapshot=make_snapshot(rm, bindings=bindings))
    assert exc.value.binding_kind == "partition_mismatch"


def test_binding_suites_mismatch_rejected(ctx):
    _, rm, _ = ctx
    bindings = (AssertionMetricBinding(case_id=CID, assertion_id="A1",
                                       assertion_kind="expected_entity", partition=PART,
                                       suites=("adversarial",)),)
    with pytest.raises(CaseMembershipBindingError) as exc:
        compute(ctx, snapshot=make_snapshot(rm, bindings=bindings))
    assert exc.value.binding_kind == "suites_mismatch"


def test_scoring_config_artifact_hash_binding(ctx):
    _, rm, cfg = ctx
    bad = LoadedScoringGateConfig(config=cfg, version=rm.scoring_gate_config_version,
                                  sha256="f" * 64, artifact_reference="x")
    with pytest.raises(SnapshotBindingError) as exc:
        compute_metric_report(make_snapshot(rm), assertion_outcomes=(ao(),),
                              validator_findings=(vf(),), run_manifest=rm,
                              case_set_manifest=CASE_SET, scoring_config=bad)
    assert exc.value.binding_kind == "scoring_config_hash"


def test_case_set_manifest_hash_binding(ctx):
    _, rm, cfg = ctx
    # Same version, tampered content -> different canonical snapshot hash.
    tampered = CASE_SET.model_copy(update={"registry_snapshot_version": "tampered-v9"})
    with pytest.raises(SnapshotBindingError) as exc:
        compute_metric_report(make_snapshot(rm), assertion_outcomes=(ao(),),
                              validator_findings=(vf(),), run_manifest=rm,
                              case_set_manifest=tampered, scoring_config=loaded(cfg, rm))
    assert exc.value.binding_kind == "case_set_manifest_hash"


def test_scoring_config_version_binding(ctx):
    _, rm, cfg = ctx
    bad_config = cfg.model_copy(update={"config_version": "different-inner"})
    # Wrapper version stays the manifest version, so the inner-version guard fires first.
    wrapper = LoadedScoringGateConfig(config=bad_config, version=rm.scoring_gate_config_version,
                                      sha256=rm.scoring_gate_config_hash, artifact_reference="x")
    with pytest.raises(SnapshotBindingError) as exc:
        compute_metric_report(make_snapshot(rm), assertion_outcomes=(ao(),),
                              validator_findings=(vf(),), run_manifest=rm,
                              case_set_manifest=CASE_SET, scoring_config=wrapper)
    assert exc.value.binding_kind == "scoring_config_version"


def test_scoring_config_wrapper_version_binding(ctx):
    _, rm, cfg = ctx
    # Inner config version and SHA correct, but the wrapper's own version disagrees.
    wrapper = LoadedScoringGateConfig(config=cfg, version="wrong-wrapper-version",
                                      sha256=rm.scoring_gate_config_hash, artifact_reference="x")
    with pytest.raises(SnapshotBindingError) as exc:
        compute_metric_report(make_snapshot(rm), assertion_outcomes=(ao(),),
                              validator_findings=(vf(),), run_manifest=rm,
                              case_set_manifest=CASE_SET, scoring_config=wrapper)
    assert exc.value.binding_kind == "scoring_config_wrapper_version"


def test_case_set_manifest_version_binding(ctx):
    _, rm, cfg = ctx
    tampered = CASE_SET.model_copy(update={"case_set_version": "different-version"})
    with pytest.raises(SnapshotBindingError) as exc:
        compute_metric_report(make_snapshot(rm), assertion_outcomes=(ao(),),
                              validator_findings=(vf(),), run_manifest=rm,
                              case_set_manifest=tampered, scoring_config=loaded(cfg, rm))
    assert exc.value.binding_kind == "case_set_manifest_version"


def test_duplicate_outcome_identity_rejected(ctx):
    _, rm, _ = ctx
    with pytest.raises(AssertionBindingMismatchError):
        compute(ctx, outcomes=(ao(), ao()))  # two outcomes with the same (case_id, assertion_id)


def test_balanced_accuracy_excludes_gold_absent_class(ctx):
    _, rm, _ = ctx
    # Axis declares three classes; gold uses only x and y, so z has no support.
    axis = make_axis(metric_type="nominal_single_label", base=None, labels=("x", "y", "z"),
                     role="other")
    records = (rec("r1", ("x",), ("x",)), rec("r2", ("z",), ("y",)))
    config = build_config(rm.scoring_gate_config_version, axis_metric_id=METRIC_AXIS_NOMINAL)
    rep = compute(ctx, snapshot=make_snapshot(rm, axes=(axis,), records=records), config=config)
    bal = one(rep, METRIC_AXIS_NOMINAL, aggregation="overall", measure="balanced_accuracy",
              verification="verified", scope="conditional")
    # recall x = 1/1, recall y = 0/1, class z (no gold support) excluded -> (1+0)/2 = 0.5
    assert bal.status == "computed" and bal.value == 0.5
    assert bal.configuration_role == "gate_input"
    assert bal.support.verified_support == 2 and bal.support.provisional_support == 0
    assert bal.support.applicable_denominator == 2 and bal.support.total_support == 2
    assert {d.key: d.value for d in bal.dimensions} == {
        "aggregation": "overall", "axis_role": "other", "measure": "balanced_accuracy",
        "scope": "conditional", "verification": "verified"}
    # Provisional view has no records -> no class has support -> indeterminate.
    prov = one(rep, METRIC_AXIS_NOMINAL, aggregation="overall", measure="balanced_accuracy",
               verification="provisional", scope="conditional")
    assert prov.status == "indeterminate" and prov.value is None
    assert prov.reason_code == "zero_denominator"
    assert prov.configuration_role == "diagnostic"
    assert prov.support.provisional_support == 0 and prov.support.applicable_denominator == 0


def test_nominal_screen_exclusion_confusion_cell_and_fn(ctx):
    _, rm, _ = ctx
    axis = make_axis(metric_type="nominal_single_label", base=None, labels=("x", "y"), role="other")
    records = (
        # A conditional answered record proves the terminal is excluded from conditional.
        rec("c0", ("x",), ("x",), scope="conditional"),
        rec("r1", ("x",), ("x",), scope="end_to_end"),
        rec("r2", (NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION,), ("y",), scope="end_to_end"),
    )
    config = build_config(rm.scoring_gate_config_version, axis_metric_id=METRIC_AXIS_NOMINAL)
    rep = compute(ctx, snapshot=make_snapshot(rm, axes=(axis,), records=records), config=config)
    # End-to-end: a confusion column for the screen-exclusion terminal is emitted.
    cell = one(rep, METRIC_AXIS_NOMINAL, aggregation="confusion_matrix", gold="y",
               predicted=NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION, verification="verified",
               scope="end_to_end")
    assert cell.value == 1
    # The terminal contributes FN to gold class y and is never a declared class.
    rec_y = one(rep, METRIC_AXIS_NOMINAL, aggregation="per_class", label="y", measure="recall",
                verification="verified", scope="end_to_end")
    assert rec_y.value == 0.0
    assert not find(rep, METRIC_AXIS_NOMINAL, aggregation="per_class",
                    label=NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION)
    assert not find(rep, METRIC_AXIS_NOMINAL, aggregation="per_class",
                    measure="precision", label=NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION)
    # Exact accuracy retains the terminal in the denominator and counts it incorrect.
    acc = one(rep, METRIC_AXIS_NOMINAL, aggregation="overall", measure="exact_accuracy",
              verification="verified", scope="end_to_end")
    assert acc.numerator == 1 and acc.denominator == 2 and acc.value == 0.5
    assert acc.support.applicable_denominator == 2
    # Conditional view contains only the answered record and no terminal column at all.
    cond_acc = one(rep, METRIC_AXIS_NOMINAL, aggregation="overall", measure="exact_accuracy",
                   verification="verified", scope="conditional")
    assert cond_acc.numerator == 1 and cond_acc.denominator == 1  # only c0
    assert not find(rep, METRIC_AXIS_NOMINAL, aggregation="confusion_matrix",
                    predicted=NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION, scope="conditional")


@pytest.mark.parametrize("terminal", [UNKNOWN, NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION])
def test_multi_label_exact_set_terminal_and_conditional(ctx, terminal):
    _, rm, _ = ctx
    # Multi-label abstention axis permits UNKNOWN; end-to-end retains terminals,
    # conditional excludes them.
    axis = make_axis(metric_type="abstention_allowed", base="multi_label", labels=("a", "b"))
    records = (
        rec("c0", ("a",), ("a",), scope="conditional"),          # conditional answered-correct
        rec("r1", ("a",), ("a",), scope="end_to_end"),           # end-to-end answered-correct
        rec("r2", (terminal,), ("b",), scope="end_to_end"),      # end-to-end terminal (incorrect)
    )
    config = build_config(rm.scoring_gate_config_version)
    rep = compute(ctx, snapshot=make_snapshot(rm, axes=(axis,), records=records), config=config)
    e2e = one(rep, METRIC_AXIS_MULTI_LABEL, aggregation="exact_set", measure="agreement",
              verification="verified", scope="end_to_end")
    assert e2e.numerator == 1 and e2e.denominator == 2 and e2e.value == 0.5  # terminal retained
    assert e2e.support.applicable_denominator == 2
    cond = one(rep, METRIC_AXIS_MULTI_LABEL, aggregation="exact_set", measure="agreement",
               verification="verified", scope="conditional")
    assert cond.numerator == 1 and cond.denominator == 1  # only c0; terminal excluded


@pytest.mark.parametrize("terminal", [UNKNOWN, NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION])
def test_structured_set_exact_set_terminal_and_conditional(ctx, terminal):
    _, rm, _ = ctx
    axis = make_axis(metric_type="abstention_allowed", base="structured_set", labels=("a", "b"))
    records = (
        rec("c0", ("a",), ("a",), scope="conditional"),
        rec("r1", ("a",), ("a",), scope="end_to_end"),
        rec("r2", (terminal,), ("b",), scope="end_to_end"),
    )
    config = build_config(rm.scoring_gate_config_version, axis_metric_id=METRIC_AXIS_STRUCTURED_SET)
    rep = compute(ctx, snapshot=make_snapshot(rm, axes=(axis,), records=records), config=config)
    e2e = one(rep, METRIC_AXIS_STRUCTURED_SET, aggregation="exact_set", measure="agreement",
              verification="verified", scope="end_to_end")
    assert e2e.numerator == 1 and e2e.denominator == 2 and e2e.value == 0.5
    assert e2e.support.applicable_denominator == 2
    cond = one(rep, METRIC_AXIS_STRUCTURED_SET, aggregation="exact_set", measure="agreement",
               verification="verified", scope="conditional")
    assert cond.numerator == 1 and cond.denominator == 1


def test_scoring_config_artifact_reference_harmless(ctx):
    _, rm, cfg = ctx
    ordinary = compute(ctx)
    unusual = LoadedScoringGateConfig(
        config=cfg, version=rm.scoring_gate_config_version, sha256=rm.scoring_gate_config_hash,
        artifact_reference="../unusual/but harmless reference #!.json")
    snap = make_snapshot(rm)
    weird = compute_metric_report(snap, assertion_outcomes=(ao(),),
                                  validator_findings=(vf(),), run_manifest=_rm_from_snapshot(snap),
                                  case_set_manifest=CASE_SET, scoring_config=unusual)
    # The artifact_reference does not participate in computation: identical report.
    assert weird.model_dump() == ordinary.model_dump()
    assert met._canonical_report_bytes(weird) == met._canonical_report_bytes(ordinary)


# --- Boundaries, exports, hygiene -----------------------------------------


def test_metric_report_contract_hash_stable():
    assert model_contract_hash(MetricReport, "metric_report", "0.1.0") == (
        "d9e3f6d7399af628b38754758a7cb580e57955ad695ee7d92fb56c67c4ceac39"
    )


def test_v0_1_producer_returns_v0_1_report_unchanged(ctx):
    # The frozen v0.1 producer/model are untouched by Slice 12J: compute_metric_report
    # still returns a metric_report@0.1.0 with no applicability ledger.
    rep = compute(ctx)
    assert rep.contract.contract_version == "0.1.0"
    assert not hasattr(rep, "applicability_ledger")
    # The v0.2 private loaded/persisted wrappers are not package exports.
    assert "_LoadedMetricReportV2" not in evaluation_pkg.__all__
    assert "_PersistedMetricReportV2" not in evaluation_pkg.__all__


PROTECTED_HASHES = {
    ("PredictionEnvelope", "prediction_envelope"): "5ac06fb78220c3f7369863cda32ee914a1d33ff01020fc01e57d9bd0ccbb18a3",
    ("AssertionOutcome", "assertion_outcome"): "4af3a9eb7c99e3e3ba088784b3395f4b6920fa1f8061f7bb1118af6bd2720bd6",
    ("EvaluationRunManifest", "evaluation_run_manifest"): "7f8909d8e7059952c933c8e30f43044178b3f8a21d4baaa77bfb5c786b38d6ee",
    ("ValidatorFinding", "validator_finding"): "96f63fee300d363a662f4f956bacccdca596acfb0f22bf7039aa1335b6d61292",
    ("FindingDisposition", "finding_disposition"): "1c08efdbd36682acf535cc688ae5c73e902e1659f30814b6a5bee46b2c9d873e",
}


def test_protected_contract_hashes_unchanged():
    from dynamic_ai_products.evaluation import models as mod
    from dynamic_ai_products.evaluation.envelopes import PredictionArtifactManifest
    for (name, cid), expected in PROTECTED_HASHES.items():
        cls = getattr(mod, name)
        assert model_contract_hash(cls, cid, "0.1.0") == expected
    assert model_contract_hash(PredictionArtifactManifest, "prediction_artifact_manifest",
                               "0.1.0") == "4b164aea18fc99f9518854aca0fb98587eb71d81c972a477d48cb815ddc0dbe4"


PUBLIC_FUNCTIONS = (
    "compute_metric_report", "persist_metric_report", "load_metric_report",
    "metric_input_snapshot_hash",
    # Slice 12J v0.2 producer/reader.
    "compute_metric_report_v2", "load_metric_report_v2",
)
PUBLIC_MODELS = (
    "AxisDefinition", "AxisEvaluationRecord", "AssertionMetricBinding",
    "ValidatorRuleEvaluationRecord", "TierContractObservation", "UnsafeAuditLabel",
    "UnsafeAuditStratum", "UnsafeExclusionAuditSnapshot", "ScreenOperationalSummary",
    "MetricInputSnapshot", "MetricDimension", "ConfidenceInterval", "MetricSupport",
    "MetricDatum", "MetricReport", "PersistedMetricReport", "LoadedMetricReport",
    # Slice 12J v0.2 models.
    "MetricReportV2", "MetricFamilyApplicabilityEntry",
)
PUBLIC_EXCEPTIONS = (
    "MetricError", "SnapshotBindingError", "AssertionBindingMismatchError",
    "OutcomeRunBindingError", "FindingRunBindingError", "CaseMembershipBindingError",
    "ValidatorExecutionMismatchError", "MetricPolicyError", "UnsafeAuditPolicyError",
    "MetricReportExistsError", "MetricArtifactMissingError", "MetricArtifactNotAFileError",
    "MetricArtifactReadError", "MetricDecodeError", "MetricJsonError", "MetricTopLevelTypeError",
    "MetricModelValidationError", "MetricReportBindingError", "MetricWriteError",
    "MetricDestinationHashMismatchError",
)


def test_public_symbols_exported():
    for name in PUBLIC_FUNCTIONS + PUBLIC_MODELS + PUBLIC_EXCEPTIONS:
        assert name in evaluation_pkg.__all__
        assert getattr(evaluation_pkg, name) is getattr(met, name)


def test_governed_constants_exported():
    for name in ("UNKNOWN", "OTHER", "NOT_APPLICABLE", "NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION"):
        assert name in evaluation_pkg.__all__


def test_exception_hierarchy():
    for name in PUBLIC_EXCEPTIONS:
        cls = getattr(met, name)
        if name == "MetricError":
            assert cls.__bases__ == (Exception,)
        else:
            assert issubclass(cls, met.MetricError)


def test_private_helpers_not_exported():
    for name in ("_canonical_report_bytes", "_wilson_upper", "_resolve_slice_policy",
                 "_multi_label_confusion", "_DuplicateKeyControl"):
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
        "import dynamic_ai_products.evaluation.metrics\n"
        "Path.read_bytes,Path.read_text,Path.mkdir,os.open=orb,ort,omk,oop\nhashlib.sha256=osha\n"
        "bad=[p for p in reads if p.endswith('.json') or p.endswith('.jsonl') or '/schemas/' in p or '/evals/' in p]\n"
        "assert not bad and not writes and not sha, (bad, writes, len(sha))\nprint('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0 and "OK" in result.stdout, result.stderr
