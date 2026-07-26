"""Slice 12J: metric report v0.2 (``metric_report@0.2.0``) applicability ledger."""

from pathlib import Path

import pytest

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import metrics as met
from dynamic_ai_products.evaluation.case_sets import load_case_set_manifest
from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.metric_inputs import (
    AssertionMetricBinding,
    AxisDefinition,
    AxisEvaluationRecord,
    ValidatorRuleEvaluationRecord,
    build_metric_input_snapshot,
)
from dynamic_ai_products.evaluation.metrics import (
    MetricFamilyApplicabilityEntry,
    MetricReport,
    MetricReportV2,
    compute_metric_report,
    compute_metric_report_v2,
    load_metric_report_v2,
)
from dynamic_ai_products.evaluation.models import AssertionOutcome, ValidatorFinding
from dynamic_ai_products.evaluation.references import load_target_registry
from dynamic_ai_products.evaluation.runs import initialize_evaluation_run_v2
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

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness"
CASE_SET = load_case_set_manifest("valid_base_case_set_manifest.json", eval_root=FX / "case_sets")
REGISTRY = load_target_registry("valid_target_registry.json", eval_root=FX / "configs")
SCORING = load_scoring_gate_config("valid_scoring_gate_config.json", eval_root=FX / "configs")
SP_REG = load_stage_profile_registry("stage_profiles/stage_profile_registry.json", eval_root=FX)
CID = "SYNTH-CASE-0001"
HEX = "a" * 64
CREATED = "2026-07-25T00:00:00+00:00"
AO_META = {"contract_id": "assertion_outcome", "contract_version": "0.1.0",
           "contract_hash": model_contract_hash(AssertionOutcome, "assertion_outcome", "0.1.0")}
VF_META = {"contract_id": "validator_finding", "contract_version": "0.1.0",
           "contract_hash": model_contract_hash(ValidatorFinding, "validator_finding", "0.1.0")}

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


def ao(outcome="satisfied"):
    return AssertionOutcome.model_validate({"contract": AO_META, "eval_run_id": "run1",
        "case_id": CID, "assertion_id": "A1", "assertion_semantic_version": "0.1.0",
        "outcome": outcome})


def vf():
    return ValidatorFinding.model_validate({"contract": VF_META, "finding_id": "f1",
        "validator": "source_id_resolution", "validator_bundle_version": "vb",
        "validator_bundle_hash": "b" * 64, "rule_params_hash": HEX, "severity": "error",
        "run_id": "run1", "artifact_id": "art1", "observed_value": "x", "expected_invariant": "y",
        "message": "m", "evidence": "e", "repairable": False, "created_at": "2026-07-20T00:00:00Z"})


def _gate(mid, sl, sup=None):
    return GateDefinition(reference_id=f"g-{mid}-{sl}", metric_id=mid, population_slice_id=sl,
        verified_support_requirement=sup or {"minimum_verified_support": 0}, ci_method_reference=None,
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


def _init(eval_root, stage, ev, run_id="run1"):
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


def _snapshot(rm, stage, ev):
    axis = AxisDefinition(axis_id="axis-1", axis_role="product", metric_type="abstention_allowed",
                          base_metric_type="multi_label", labels=("a", "b"))
    records = (AxisEvaluationRecord(record_id="r1", case_id=CID, axis_id="axis-1",
        metric_scope="conditional", verification_status="verified",
        evidence_resolvability="resolvable", predicted_values=("a",), gold_values=("a",)),) \
        if stage != "universe_screen" else ()
    return build_metric_input_snapshot(
        evaluation_stage=stage, stage_profile_registry=SP_REG, run_manifest=rm,
        axis_definitions=(axis,) if stage != "universe_screen" else (),
        axis_records=records,
        assertion_bindings=(AssertionMetricBinding(case_id=CID, assertion_id="A1",
            assertion_kind="expected_entity", partition="dev", suites=("adversarial", "regression")),),
        validator_rule_evaluations=(ValidatorRuleEvaluationRecord(artifact_id="art1",
            rule_id="source_id_resolution", evaluated_observation_count=5,
            failed_observation_count=1),),
        stage_evidence=ev)


def _prep(tmp_path, stage="universe_classification"):
    ev = _evidence(stage)
    rm = _init(tmp_path, stage, ev)
    snap = _snapshot(rm, stage, ev)
    lc = LoadedScoringGateConfig(config=_config(rm.scoring_gate_config_version),
        version=rm.scoring_gate_config_version, sha256=rm.scoring_gate_config_hash,
        artifact_reference="x")
    return tmp_path, rm, snap, lc


def _compute(tmp_path, stage="universe_classification"):
    _, rm, snap, lc = _prep(tmp_path, stage)
    return compute_metric_report_v2(snap, assertion_outcomes=(ao(),), validator_findings=(vf(),),
        run_manifest=rm, case_set_manifest=CASE_SET, scoring_config=lc,
        stage_profile_registry=SP_REG)


# --- Contract hashes -------------------------------------------------------


def test_v0_1_hash_preserved():
    assert model_contract_hash(MetricReport, "metric_report", "0.1.0") == \
        "d9e3f6d7399af628b38754758a7cb580e57955ad695ee7d92fb56c67c4ceac39"


def test_v0_2_contract_stamp():
    r = MetricReportV2  # class exists
    h = model_contract_hash(r, "metric_report", "0.2.0")
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)
    assert h != model_contract_hash(MetricReport, "metric_report", "0.1.0")


# --- Ledger structure ------------------------------------------------------


def test_ledger_is_eleven_canonical_families(tmp_path):
    rep = _compute(tmp_path)
    fams = tuple(e.metric_family for e in rep.applicability_ledger)
    assert fams == met._CANONICAL_METRIC_FAMILIES
    assert len(fams) == 11 and len(set(fams)) == 11
    assert rep.contract.contract_version == "0.2.0"
    assert rep.evaluation_stage == "universe_classification"


def test_applicable_and_inapplicable_reason_rules(tmp_path):
    rep = _compute(tmp_path)
    by_family = {e.metric_family: e for e in rep.applicability_ledger}
    # classification: tier applicable (no reason), screen/unsafe inapplicable (reason present).
    assert by_family["tier_contract"].applicability_state == "applicable"
    assert by_family["tier_contract"].reason_code is None
    for fam in ("screen_operational", "unsafe_exclusion"):
        e = by_family[fam]
        assert e.applicability_state == "inapplicable"
        assert e.reason_code and e.reason_code.strip()
        assert e.reason_code.startswith(f"{fam}_")


def test_no_datum_for_inapplicable_family(tmp_path):
    rep = _compute(tmp_path)
    applicable = {e.metric_family for e in rep.applicability_ledger
                  if e.applicability_state == "applicable"}
    assert "screen_operational" not in applicable and "unsafe_exclusion" not in applicable
    for d in rep.metrics:
        assert d.metric_id in applicable
    assert not any(d.metric_id in ("screen_operational", "unsafe_exclusion") for d in rep.metrics)


def test_computed_zero_and_indeterminate_remain_data_bearing(tmp_path):
    # A computed value (possibly 0) and an indeterminate datum both remain
    # MetricDatum entries within applicable families — distinct from inapplicable.
    rep = _compute(tmp_path, "universe_screen")
    statuses = {d.status for d in rep.metrics}
    assert "computed" in statuses
    # every datum is data-bearing (has a metric_id/status), never a ledger-only entry
    for d in rep.metrics:
        assert d.status in ("computed", "indeterminate")


def test_applicable_family_may_have_no_datum(tmp_path):
    # An applicable family with no eligible records still needs no datum; the
    # report validates and the ledger still marks it applicable.
    rep = _compute(tmp_path)
    emitted = {d.metric_id for d in rep.metrics}
    applicable = {e.metric_family for e in rep.applicability_ledger
                  if e.applicability_state == "applicable"}
    assert applicable - emitted  # at least one applicable family emitted no datum
    # Canonical (exclude_unset) serialization omits reason_code for applicable
    # families, so the report round-trips through its persisted form.
    assert MetricReportV2.model_validate(rep.model_dump(mode="json", exclude_unset=True))


# --- Producer fail-closed rejections ---------------------------------------


def _bad(tmp_path, **manifest_overrides):
    _, rm, snap, lc = _prep(tmp_path)
    rm2 = rm.model_copy(update=manifest_overrides)
    return snap, rm2, lc


def test_rejects_manifest_registry_version_mismatch(tmp_path):
    snap, rm2, lc = _bad(tmp_path, stage_profile_registry_version="WRONG")
    with pytest.raises(met.SnapshotBindingError):
        compute_metric_report_v2(snap, assertion_outcomes=(ao(),), validator_findings=(vf(),),
            run_manifest=rm2, case_set_manifest=CASE_SET, scoring_config=lc,
            stage_profile_registry=SP_REG)


def test_rejects_manifest_registry_hash_mismatch(tmp_path):
    snap, rm2, lc = _bad(tmp_path, stage_profile_registry_hash="f" * 64)
    with pytest.raises(met.SnapshotBindingError):
        compute_metric_report_v2(snap, assertion_outcomes=(ao(),), validator_findings=(vf(),),
            run_manifest=rm2, case_set_manifest=CASE_SET, scoring_config=lc,
            stage_profile_registry=SP_REG)


def test_rejects_manifest_selected_entry_hash_mismatch(tmp_path):
    snap, rm2, lc = _bad(tmp_path, selected_stage_profile_entry_hash="f" * 64)
    with pytest.raises(met.SnapshotBindingError):
        compute_metric_report_v2(snap, assertion_outcomes=(ao(),), validator_findings=(vf(),),
            run_manifest=rm2, case_set_manifest=CASE_SET, scoring_config=lc,
            stage_profile_registry=SP_REG)


def test_rejects_v1_manifest(tmp_path):
    _, rm, snap, lc = _prep(tmp_path)
    # v0.1 producer path rejected: compute_metric_report_v2 requires v0.2.
    with pytest.raises(TypeError):
        compute_metric_report_v2(snap, assertion_outcomes=(ao(),), validator_findings=(vf(),),
            run_manifest=object(), case_set_manifest=CASE_SET, scoring_config=lc,
            stage_profile_registry=SP_REG)


def test_rejects_non_registry(tmp_path):
    _, rm, snap, lc = _prep(tmp_path)
    with pytest.raises(TypeError):
        compute_metric_report_v2(snap, assertion_outcomes=(ao(),), validator_findings=(vf(),),
            run_manifest=rm, case_set_manifest=CASE_SET, scoring_config=lc,
            stage_profile_registry=object())


def test_rejects_forged_swapped_reason(tmp_path):
    # The ledger reasons come from the resolved entry; a caller cannot forge or
    # swap them. A MetricReportV2 whose ledger reason is blanked/misassigned fails.
    rep = _compute(tmp_path)
    dumped = rep.model_dump(mode="json", exclude_unset=True)
    # forge: give an applicable family a reason_code (must be omitted for applicable)
    for e in dumped["applicability_ledger"]:
        if e["metric_family"] == "tier_contract":
            e["reason_code"] = "forged_reason"
    with pytest.raises(ValueError):
        MetricReportV2.model_validate(dumped)


# --- Persistence / reader --------------------------------------------------


def _v2(tmp_path):
    _, rm, snap, lc = _prep(tmp_path)
    return rm, compute_metric_report_v2(snap, assertion_outcomes=(ao(),),
        validator_findings=(vf(),), run_manifest=rm, case_set_manifest=CASE_SET,
        scoring_config=lc, stage_profile_registry=SP_REG)


def test_public_persist_v2_round_trips_through_public_load(tmp_path):
    # The single public persistence path handles v0.2 with a registry; the public
    # reader round-trips it (no private-only writer).
    _, rep = _v2(tmp_path)
    persisted = met.persist_metric_report(rep, eval_root=tmp_path, eval_run_id="run1",
                                          stage_profile_registry=SP_REG)
    assert isinstance(persisted, met.PersistedMetricReport)
    loaded = load_metric_report_v2("run1", eval_root=tmp_path, stage_profile_registry=SP_REG)
    assert loaded.sha256 == persisted.sha256
    assert loaded.report.contract.contract_version == "0.2.0"
    assert loaded.report.applicability_ledger == rep.applicability_ledger


def test_v1_persist_unchanged_needs_no_registry(tmp_path):
    _, rm, snap, lc = _prep(tmp_path)
    v1 = compute_metric_report(snap, assertion_outcomes=(ao(),), validator_findings=(vf(),),
        run_manifest=rm, case_set_manifest=CASE_SET, scoring_config=lc)
    # v0.1 call shape unchanged: no registry required.
    persisted = met.persist_metric_report(v1, eval_root=tmp_path, eval_run_id="run1")
    assert persisted.report.contract.contract_version == "0.1.0"
    assert met.load_metric_report("run1", eval_root=tmp_path).report.contract.contract_version == "0.1.0"


def test_v2_persist_write_once(tmp_path):
    _, rep = _v2(tmp_path)
    met.persist_metric_report(rep, eval_root=tmp_path, eval_run_id="run1", stage_profile_registry=SP_REG)
    with pytest.raises(met.MetricReportExistsError):
        met.persist_metric_report(rep, eval_root=tmp_path, eval_run_id="run1",
                                  stage_profile_registry=SP_REG)


def test_v2_persist_rejects_missing_registry(tmp_path):
    _, rep = _v2(tmp_path)
    with pytest.raises(met.MetricReportBindingError):
        met.persist_metric_report(rep, eval_root=tmp_path, eval_run_id="run1")


def test_v2_persist_rejects_wrong_registry(tmp_path):
    _, rep = _v2(tmp_path)
    # A registry whose selected entries hash differently is not the report's owner.
    wrong = load_stage_profile_registry("stage_profiles/stage_profile_registry.json",
                                        eval_root=FX)
    object.__setattr__(wrong, "version", "wrong-registry-version")
    with pytest.raises(met.MetricReportBindingError):
        met.persist_metric_report(rep, eval_root=tmp_path, eval_run_id="run1",
                                  stage_profile_registry=wrong)


def test_v2_persist_rejects_forged_reason(tmp_path):
    # A structurally valid report whose nonblank inapplicable reason was forged is
    # rejected against the registry-derived ledger (structural validity insufficient).
    _, rep = _v2(tmp_path)
    dumped = rep.model_dump(mode="json", exclude_unset=True)
    for e in dumped["applicability_ledger"]:
        if e["metric_family"] == "screen_operational":
            e["reason_code"] = "screen_operational_forged_but_nonblank"
    forged = MetricReportV2.model_validate(dumped)  # still structurally valid
    with pytest.raises(met.MetricReportBindingError):
        met.persist_metric_report(forged, eval_root=tmp_path, eval_run_id="run1",
                                  stage_profile_registry=SP_REG)


def test_v2_reader_rejects_missing_registry_arg():
    with pytest.raises(TypeError):
        load_metric_report_v2("run1", eval_root=".")  # stage_profile_registry required


def test_v2_reader_missing_artifact(tmp_path):
    _prep(tmp_path)  # run dir exists, but no v2 report persisted
    with pytest.raises(met.MetricArtifactMissingError):
        load_metric_report_v2("run1", eval_root=tmp_path, stage_profile_registry=SP_REG)


def test_v2_loader_rejects_tampered_ledger_reason(tmp_path):
    # Persist a valid v0.2 report, then tamper a nonblank inapplicable reason on
    # disk (still structurally valid). The registry-truthful reader rejects it.
    _, rep = _v2(tmp_path)
    persisted = met.persist_metric_report(rep, eval_root=tmp_path, eval_run_id="run1",
                                          stage_profile_registry=SP_REG)
    dest = tmp_path / persisted.artifact_reference
    import json
    payload = json.loads(dest.read_text())
    for e in payload["applicability_ledger"]:
        if e["metric_family"] == "unsafe_exclusion":
            e["reason_code"] = "unsafe_exclusion_tampered_nonblank"
    dest.write_text(json.dumps(payload))
    with pytest.raises(met.MetricReportBindingError):
        load_metric_report_v2("run1", eval_root=tmp_path, stage_profile_registry=SP_REG)


def test_v2_loader_rejects_stage_mismatch(tmp_path):
    # Tamper the on-disk report evaluation_stage to another supported stage; the
    # resolved entry hash no longer matches the manifest pin -> rejected.
    _, rep = _v2(tmp_path)  # classification
    persisted = met.persist_metric_report(rep, eval_root=tmp_path, eval_run_id="run1",
                                          stage_profile_registry=SP_REG)
    dest = tmp_path / persisted.artifact_reference
    import json
    payload = json.loads(dest.read_text())
    payload["evaluation_stage"] = "universe_screen"
    dest.write_text(json.dumps(payload))
    with pytest.raises(met.MetricReportBindingError):
        load_metric_report_v2("run1", eval_root=tmp_path, stage_profile_registry=SP_REG)


def test_v2_report_does_not_validate_as_v1(tmp_path):
    _, rep = _v2(tmp_path)
    # A v0.2 payload must not silently validate as v0.1 MetricReport.
    with pytest.raises(Exception):
        MetricReport.model_validate(rep.model_dump(mode="json"))


def test_v1_and_v2_are_separate_artifacts(tmp_path):
    # A v0.1 report and a v0.2 report coexist under one run dir at distinct paths.
    _, rm, snap, lc = _prep(tmp_path)
    v1 = compute_metric_report(snap, assertion_outcomes=(ao(),), validator_findings=(vf(),),
        run_manifest=rm, case_set_manifest=CASE_SET, scoring_config=lc)
    met.persist_metric_report(v1, eval_root=tmp_path, eval_run_id="run1")
    v2 = compute_metric_report_v2(snap, assertion_outcomes=(ao(),), validator_findings=(vf(),),
        run_manifest=rm, case_set_manifest=CASE_SET, scoring_config=lc, stage_profile_registry=SP_REG)
    met.persist_metric_report(v2, eval_root=tmp_path, eval_run_id="run1", stage_profile_registry=SP_REG)
    assert met.load_metric_report("run1", eval_root=tmp_path).report.contract.contract_version == "0.1.0"
    assert load_metric_report_v2("run1", eval_root=tmp_path,
                                 stage_profile_registry=SP_REG).report.contract.contract_version == "0.2.0"


# --- Public surface --------------------------------------------------------


def test_public_surface():
    for name in ("MetricFamilyApplicabilityEntry", "MetricReportV2",
                 "compute_metric_report_v2", "load_metric_report_v2"):
        assert name in evaluation_pkg.__all__
    assert len(evaluation_pkg.__all__) == 562
    assert evaluation_pkg.__all__ == sorted(evaluation_pkg.__all__)
    assert len(set(evaluation_pkg.__all__)) == len(evaluation_pkg.__all__)
    # v0.2 loaded/persisted wrappers stay module-private.
    assert "_LoadedMetricReportV2" not in evaluation_pkg.__all__
    assert "_PersistedMetricReportV2" not in evaluation_pkg.__all__


def test_manifest_count():
    import re
    txt = (ROOT / "REPO_MANIFEST.md").read_text().splitlines()
    declared = int(re.search(r"listed:\s*\*\*(\d+)\*\*", "\n".join(txt)).group(1))
    paths = [re.match(r"- `([^`]+)`", ln).group(1) for ln in txt if re.match(r"- `[^`]+`\s*$", ln)]
    assert declared == len(paths) == 390
    assert paths.count("tests/evaluation/test_metric_report_v2.py") == 1


def test_ledger_entry_reason_rules_direct():
    # Applicable must omit reason; inapplicable requires nonblank reason.
    MetricFamilyApplicabilityEntry(metric_family="tier_contract", applicability_state="applicable")
    MetricFamilyApplicabilityEntry(metric_family="tier_contract",
                                   applicability_state="inapplicable", reason_code="tier_contract_x")
    with pytest.raises(ValueError):
        MetricFamilyApplicabilityEntry(metric_family="tier_contract",
                                       applicability_state="applicable", reason_code="x")
    with pytest.raises(ValueError):
        MetricFamilyApplicabilityEntry(metric_family="tier_contract",
                                       applicability_state="inapplicable")
