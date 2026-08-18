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
    assert len(evaluation_pkg.__all__) == 579
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
    # 575 = 561 + the fourteen ADR-043 paths: three schemas, five source
    # modules and six test modules. Superseding the ADR-042 note:
    # its module, its test file, and the published registry record.
    # 579 = 575 + the four newly tracked ADR-044 (G2) paths: the
    # prompt-qualification schema, its source module, its test module, and the
    # tracked change request the record pins by reference and digest.
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
    # 679 = 670 + the nine W2-B baseline-document acquisition paths
    # (ADR-089): the acquisition module, its v0.1 and v0.2 manifest
    # schemas, the committed 12-document canary request plan, the
    # synthetic document fixture bundle (plan, two submissions, gold),
    # and the acquisition test file. Documents only: no packet, no
    # screen, no classification.
    # 680 = 679 + the bounded document transport (ADR-089 revision):
    # ceiling enforcement moved from post-download to streaming, so the
    # policy module joins the tree. It imports no HTTP library; the one
    # httpx-originating send stays in sec_index_transport.py and the
    # repository-wide allowlist stays at three modules.
    # 689 = 680 + the nine W2-C filing-index metadata-probe paths
    # (ADR-090): the probe module, its v0.1 fixture and v0.2 sec_live
    # manifest schemas, the committed three-request probe plan, the
    # synthetic index-page fixture bundle (plan, two pages, gold), and the
    # probe test file. Metadata grammar only: no primary document is
    # acquired and no packet is built.
    # 702 = 689 + the thirteen W2-C-beta baseline-packet paths (ADR-091):
    # the packet builder, its three governed schemas (bundle input, packet
    # record, run manifest), the six-document synthetic bundle with its
    # manifest and gold, and the packet test file. Fixture-first and
    # offline: no acquisition, no screening, no classification.
    # 715 = 702 + the thirteen W2-C primary-document acquisition paths
    # (ADR-092): the two-hop acquisition module, its v0.1 fixture and v0.2
    # sec_live manifest schemas, the committed six-accession Canary B
    # request plan, the synthetic fixture bundle (plan, three index pages,
    # three primaries, gold), and the acquisition test file. It emits the
    # already-governed bundle; the packet builder is unchanged.
    # 716 = 715 + the v0.3 observational sec_live acquisition manifest
    # schema (ADR-093): live runs record each hop's parsed Content-Length
    # for byte planning. v0.1 and v0.2 are byte-unchanged and the completed
    # Canary B artifact remains a valid v0.2 record; nothing migrates.
    # 734 = 716 + the 18 Stage 00B-S shell-company paths (ADR-094):
    # the determination module, its record and run-manifest schemas, the
    # twelve-document synthetic bundle with its manifest and gold, and the
    # determination test file. Exactly one issuer fact is set; the five-flag
    # issuer_filters contract is untouched.
    # 735 = 734 + the committed shell-validation canary request plan
    # (ADR-094 pre-registration): one data file under the existing
    # primary_document_request_plan@0.1.0 contract. No new production code,
    # schema, registry entry or fixture; possessing it authorizes no request.
    # 737 = 735 + the two v0.2 shell-company determination schemas: the
    # record and run-manifest successors registering ixt:booleantrue and
    # ixt:fixed-true on XBRL Transformation Registry authority. The v0.1
    # files are retained byte-unchanged and stay the only validators for the
    # completed v0.1 canary artifacts; nothing migrates.
    # 751 = 737 + the 14 W3 acquisition-queue paths (ADR-095): the queue
    # module and its test file, four queue schemas, the two budgeted
    # acquisition-manifest successors (fixture v0.4 and sec_live v0.5), the
    # full and restricted-canary queue definitions, and four queue fixtures.
    # The historical v0.1, v0.2 and v0.3 manifest schemas are byte-unchanged.
    # 754 = 751 + the three ADR-096 selection fixtures: an index page whose
    # Document Format Files table declares the planned form for both an .htm
    # and a .pdf, plus both documents. Eligibility is decided before
    # cardinality, so a same-form PDF companion is not a rival candidate.
    # 775 = 754 + the 21 ADR-097 plain-text paths: the admission
    # module and its test file, five successor schemas (bundle v0.2, packet
    # v0.2, packet manifest v0.2, acquisition manifest v0.6, queue definition
    # v0.2), a text-admitting domestic queue definition, and the text fixture
    # set. Every predecessor schema and committed definition is unchanged.
    # 777 = 775 + the two PCT_Dev30_v0 cohort-manifest paths: the persisted
    # 30-firm roster registry (evals/registries/) and its guard-test module.
    # No schemas/ entry and no schema-registry change -- the manifest follows
    # the frame_v1_freeze.json pattern, a contract-declaring config validated
    # by tests. This addition authorizes no PCT extraction prompt, model
    # call, or Dev30 score; not tied to a numbered ADR because none was
    # authorized for this narrowly-scoped increment.
    # 782 = 777 + the five PCT_Dev30_v0 Item 1 locator paths: the locator
    # module and its package __init__, its unit-test module, the committed
    # 30-row locator ledger (bound to the cohort manifest by that file's own
    # SHA-256), and the ledger's guard-test module. No schemas/ entry and no
    # schema-registry change; the ledger follows the same contract-declaring,
    # test-validated config pattern as the cohort manifest itself. Dev30-only:
    # no Stage 00C source_id or sec-primary: identity is produced or accepted.
    assert declared == len(paths) == 782
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
