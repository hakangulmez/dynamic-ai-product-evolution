"""Slice 12I: stamped active metric-input snapshot (``metric_input_snapshot@0.1.0``)."""

from pathlib import Path

import pytest

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import metric_inputs as mi
from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.metric_inputs import (
    AxisDefinition,
    AxisEvaluationRecord,
    LoadedMetricInputSnapshot,
    MetricApplicabilityBinding,
    MetricInputSnapshot,
    MetricInputSnapshotError,
    build_metric_input_snapshot,
    load_metric_input_snapshot,
    metric_input_snapshot_hash,
    persist_metric_input_snapshot,
)
from dynamic_ai_products.evaluation.models import (
    EvaluationRunManifest,
    EvaluationRunManifestV2,
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

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness"
SP_REG = load_stage_profile_registry("stage_profiles/stage_profile_registry.json", eval_root=FX)
SP_HASH = stage_profile_registry_hash(SP_REG.registry)
RM_V2_HASH = model_contract_hash(EvaluationRunManifestV2, "evaluation_run_manifest", "0.2.0")
RM_V1_HASH = model_contract_hash(EvaluationRunManifest, "evaluation_run_manifest", "0.1.0")
H = "a" * 64
CREATED = "2026-07-24T00:00:00+00:00"

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

_KIND_VARIANTS = {
    "universe_classification_tier": TIER,
    "universe_screen_operational": SCREEN,
    "universe_unsafe_exclusion_audit": UNSAFE,
}


def _evidence(stage, *, set_version="se-v1"):
    entry = resolve_metric_applicability(SP_REG.registry, stage)
    kinds = entry.required_stage_evidence_kinds
    if not kinds:
        return None
    variants = tuple(_KIND_VARIANTS[k] for k in sorted(kinds))
    evset = build_stage_metric_evidence_set(
        evaluation_stage=stage, set_version=set_version, variants=variants)
    return LoadedStageMetricEvidenceSet(
        model=evset, version=set_version, sha256="d" * 64, artifact_reference="x")


def _v2(stage, entry, *, ev=None, case_ver="cs-v1", case_hash=H, sc_ver="sc-v1", sc_hash=H,
        reg_ver=None, reg_hash=None, entry_hash=None):
    payload = {
        "contract": {"contract_id": "evaluation_run_manifest", "contract_version": "0.2.0",
                     "contract_hash": RM_V2_HASH},
        "eval_run_id": "run1", "prediction_run_id": "P", "prediction_run_manifest_hash": H,
        "case_set_version": case_ver, "case_set_hash": case_hash, "registry_snapshot_hash": H,
        "validator_bundle_version": "vb", "validator_bundle_hash": "b" * 64,
        "scoring_gate_config_version": sc_ver, "scoring_gate_config_hash": sc_hash,
        "code_commit": "c", "pydantic_runtime_version": "2", "evaluation_created_at": CREATED,
        "stage_profile_registry_version": reg_ver or SP_REG.version,
        "stage_profile_registry_hash": reg_hash or SP_HASH,
        "selected_stage_profile_entry_hash": entry_hash or entry.entry_hash,
        "semantic_adapter_registry_version": "sa", "semantic_adapter_registry_hash": H,
        "selected_semantic_adapter_entry_hash": H,
        "source_passage_snapshot_version": "sp", "source_passage_snapshot_hash": H,
        "gold_assertion_set_version": "g", "gold_assertion_set_hash": H,
        "axis_taxonomy_version": "ax", "axis_taxonomy_hash": H,
        "validator_rule_parameters_version": "vp", "validator_rule_parameters_hash": H,
    }
    if ev is not None:
        payload["stage_metric_evidence_set_version"] = ev.model.set_version
        payload["stage_metric_evidence_set_hash"] = stage_metric_evidence_set_hash(ev.model)
    return EvaluationRunManifestV2.model_validate(payload)


def _build(stage, **kw):
    entry = resolve_metric_applicability(SP_REG.registry, stage)
    ev = _evidence(stage)
    rm = _v2(stage, entry, ev=ev, **kw)
    return build_metric_input_snapshot(
        evaluation_stage=stage, stage_profile_registry=SP_REG, run_manifest=rm, stage_evidence=ev)


# --- Happy path per stage --------------------------------------------------


def test_extraction_snapshot_no_evidence():
    snap = _build("capability_extraction")
    b = snap.applicability_binding
    assert b.evaluation_stage == "capability_extraction"
    assert b.stage_metric_evidence_set is None
    assert b.stage_metric_evidence_set_version is None and b.stage_metric_evidence_set_hash is None
    assert "tier_contract" not in b.applicable_metric_families


def test_classification_snapshot_embeds_tier():
    snap = _build("universe_classification")
    b = snap.applicability_binding
    assert "tier_contract" in b.applicable_metric_families
    assert b.stage_metric_evidence_set is not None
    assert b.stage_metric_evidence_set.present_kinds == ("universe_classification_tier",)


def test_screen_snapshot_embeds_screen_and_unsafe():
    snap = _build("universe_screen")
    b = snap.applicability_binding
    assert b.stage_metric_evidence_set.present_kinds == (
        "universe_screen_operational", "universe_unsafe_exclusion_audit")
    assert "screen_operational" in b.applicable_metric_families
    assert not any(f.startswith("axis_") for f in b.applicable_metric_families)


def test_stamped_contract_and_hash():
    snap = _build("universe_screen")
    assert snap.contract.contract_id == "metric_input_snapshot"
    assert snap.contract.contract_hash == model_contract_hash(
        MetricInputSnapshot, "metric_input_snapshot", "0.1.0")
    assert metric_input_snapshot_hash(snap) == metric_input_snapshot_hash(snap)


# --- Builder rejections ----------------------------------------------------


def test_rejects_v1_manifest():
    v1 = EvaluationRunManifest.model_validate({
        "contract": {"contract_id": "evaluation_run_manifest", "contract_version": "0.1.0",
                     "contract_hash": RM_V1_HASH},
        "eval_run_id": "run1", "prediction_run_id": "P", "prediction_run_manifest_hash": H,
        "case_set_version": "cs-v1", "case_set_hash": H, "registry_snapshot_hash": H,
        "validator_bundle_version": "vb", "validator_bundle_hash": "b" * 64,
        "scoring_gate_config_version": "sc-v1", "scoring_gate_config_hash": H,
        "code_commit": "c", "pydantic_runtime_version": "2"})
    with pytest.raises(MetricInputSnapshotError) as e:
        build_metric_input_snapshot(evaluation_stage="capability_extraction",
                                    stage_profile_registry=SP_REG, run_manifest=v1)
    assert e.value.reason_code == "run_manifest_version"


def test_rejects_unknown_stage():
    entry = resolve_metric_applicability(SP_REG.registry, "capability_extraction")
    rm = _v2("capability_extraction", entry)
    with pytest.raises(MetricInputSnapshotError) as e:
        build_metric_input_snapshot(evaluation_stage="no_such_stage",
                                    stage_profile_registry=SP_REG, run_manifest=rm)
    assert e.value.reason_code == "stage_resolution"


def test_rejects_unsupported_stage():
    entry = resolve_metric_applicability(SP_REG.registry, "capability_extraction")
    rm = _v2("capability_extraction", entry)
    with pytest.raises(MetricInputSnapshotError):
        build_metric_input_snapshot(evaluation_stage="product_extraction",
                                    stage_profile_registry=SP_REG, run_manifest=rm)


def test_rejects_registry_version_mismatch():
    entry = resolve_metric_applicability(SP_REG.registry, "capability_extraction")
    rm = _v2("capability_extraction", entry, reg_ver="WRONG")
    with pytest.raises(MetricInputSnapshotError) as e:
        build_metric_input_snapshot(evaluation_stage="capability_extraction",
                                    stage_profile_registry=SP_REG, run_manifest=rm)
    assert e.value.reason_code == "stage_profile_registry_version_mismatch"


def test_rejects_registry_hash_mismatch():
    entry = resolve_metric_applicability(SP_REG.registry, "capability_extraction")
    rm = _v2("capability_extraction", entry, reg_hash="f" * 64)
    with pytest.raises(MetricInputSnapshotError) as e:
        build_metric_input_snapshot(evaluation_stage="capability_extraction",
                                    stage_profile_registry=SP_REG, run_manifest=rm)
    assert e.value.reason_code == "stage_profile_registry_hash_mismatch"


def test_rejects_selected_entry_hash_mismatch():
    entry = resolve_metric_applicability(SP_REG.registry, "capability_extraction")
    rm = _v2("capability_extraction", entry, entry_hash="f" * 64)
    with pytest.raises(MetricInputSnapshotError) as e:
        build_metric_input_snapshot(evaluation_stage="capability_extraction",
                                    stage_profile_registry=SP_REG, run_manifest=rm)
    assert e.value.reason_code == "selected_entry_hash_mismatch"


def test_rejects_universe_stage_without_evidence():
    entry = resolve_metric_applicability(SP_REG.registry, "universe_screen")
    ev = _evidence("universe_screen")
    rm = _v2("universe_screen", entry, ev=ev)
    with pytest.raises(MetricInputSnapshotError) as e:
        build_metric_input_snapshot(evaluation_stage="universe_screen",
                                    stage_profile_registry=SP_REG, run_manifest=rm)
    assert e.value.reason_code == "evidence_required"


def test_rejects_extraction_stage_with_evidence():
    entry = resolve_metric_applicability(SP_REG.registry, "capability_extraction")
    rm = _v2("capability_extraction", entry)
    ev = _evidence("universe_screen")
    with pytest.raises(MetricInputSnapshotError) as e:
        build_metric_input_snapshot(evaluation_stage="capability_extraction",
                                    stage_profile_registry=SP_REG, run_manifest=rm, stage_evidence=ev)
    assert e.value.reason_code == "evidence_forbidden"


def test_rejects_evidence_version_mismatch():
    entry = resolve_metric_applicability(SP_REG.registry, "universe_screen")
    ev = _evidence("universe_screen")
    rm = _v2("universe_screen", entry, ev=ev)
    other = _evidence("universe_screen", set_version="OTHER-VER")
    with pytest.raises(MetricInputSnapshotError) as e:
        build_metric_input_snapshot(evaluation_stage="universe_screen",
                                    stage_profile_registry=SP_REG, run_manifest=rm, stage_evidence=other)
    assert e.value.reason_code == "evidence_version_mismatch"


def test_rejects_evidence_hash_mismatch_no_raw_hash_substitution():
    entry = resolve_metric_applicability(SP_REG.registry, "universe_screen")
    ev = _evidence("universe_screen")
    # Manifest pins the correct semantic-content hash; supplying an evidence set
    # whose content differs (even if its raw sha256 field is arbitrary) is rejected.
    rm = _v2("universe_screen", entry, ev=ev)
    tampered_model = build_stage_metric_evidence_set(
        evaluation_stage="universe_screen", set_version="se-v1", variants=(SCREEN,))
    tampered = LoadedStageMetricEvidenceSet(
        model=tampered_model, version="se-v1", sha256=stage_metric_evidence_set_hash(ev.model),
        artifact_reference="x")
    with pytest.raises(MetricInputSnapshotError) as e:
        build_metric_input_snapshot(evaluation_stage="universe_screen",
                                    stage_profile_registry=SP_REG, run_manifest=rm, stage_evidence=tampered)
    assert e.value.reason_code in ("evidence_kinds_mismatch", "evidence_hash_mismatch")


def test_rejects_validator_bypassed_evidence_wrapper():
    # A model_construct-bypassed wrapper carrying an arbitrary object must be
    # rejected fail-closed as a sanitized MetricInputSnapshotError, never a raw
    # AttributeError from reading .evaluation_stage on the untrusted member.
    entry = resolve_metric_applicability(SP_REG.registry, "universe_screen")
    ev = _evidence("universe_screen")
    rm = _v2("universe_screen", entry, ev=ev)
    bypassed = LoadedStageMetricEvidenceSet.model_construct(
        model=object(), version="se-v1", sha256="d" * 64, artifact_reference="x")
    with pytest.raises(MetricInputSnapshotError) as e:
        build_metric_input_snapshot(evaluation_stage="universe_screen",
                                    stage_profile_registry=SP_REG, run_manifest=rm,
                                    stage_evidence=bypassed)
    assert e.value.reason_code == "evidence_model_invalid"


def test_rejects_evidence_stage_mismatch():
    entry = resolve_metric_applicability(SP_REG.registry, "universe_screen")
    ev = _evidence("universe_screen")
    rm = _v2("universe_screen", entry, ev=ev)
    wrong_stage = LoadedStageMetricEvidenceSet(
        model=build_stage_metric_evidence_set(evaluation_stage="universe_classification",
                                              set_version="se-v1", variants=(SCREEN, UNSAFE)),
        version="se-v1", sha256="d" * 64, artifact_reference="x")
    with pytest.raises(MetricInputSnapshotError) as e:
        build_metric_input_snapshot(evaluation_stage="universe_screen",
                                    stage_profile_registry=SP_REG, run_manifest=rm, stage_evidence=wrong_stage)
    assert e.value.reason_code in ("evidence_stage_mismatch", "evidence_hash_mismatch")


# --- MetricApplicabilityBinding invariants --------------------------------


def test_binding_extraction_explicit_null_rejected():
    with pytest.raises(ValueError):
        MetricApplicabilityBinding.model_validate({
            "evaluation_stage": "capability_extraction",
            "stage_profile_registry_version": "0.1.0", "stage_profile_registry_hash": H,
            "selected_stage_profile_entry_hash": H,
            "applicable_metric_families": ["assertion_outcomes"],
            "required_stage_evidence_kinds": [],
            "stage_metric_evidence_set_version": None})


def test_binding_universe_requires_all_three_together():
    entry = resolve_metric_applicability(SP_REG.registry, "universe_screen")
    ev = _evidence("universe_screen")
    # Version + hash but no embedded set -> rejected.
    with pytest.raises(ValueError):
        MetricApplicabilityBinding.model_validate({
            "evaluation_stage": "universe_screen",
            "stage_profile_registry_version": "0.1.0", "stage_profile_registry_hash": H,
            "selected_stage_profile_entry_hash": entry.entry_hash,
            "applicable_metric_families": list(entry.applicable_metric_families),
            "required_stage_evidence_kinds": list(entry.required_stage_evidence_kinds),
            "stage_metric_evidence_set_version": "se-v1",
            "stage_metric_evidence_set_hash": stage_metric_evidence_set_hash(ev.model)})


# --- Persistence -----------------------------------------------------------


def test_persist_round_trip(tmp_path):
    (tmp_path / "run1").mkdir()
    snap = _build("universe_screen")
    persisted = persist_metric_input_snapshot(snap, eval_root=tmp_path, eval_run_id="run1")
    reloaded = load_metric_input_snapshot(persisted.artifact_reference, eval_root=tmp_path)
    assert isinstance(reloaded, LoadedMetricInputSnapshot)
    assert reloaded.sha256 == persisted.sha256
    assert reloaded.model.applicability_binding.evaluation_stage == "universe_screen"


def test_wrapper_version_is_contract_version_not_stage(tmp_path):
    # The wrapper ``version`` is the governed artifact contract version
    # (metric_input_snapshot@0.1.0), never the evaluation stage.
    (tmp_path / "run1").mkdir()
    snap = _build("universe_screen")
    persisted = persist_metric_input_snapshot(snap, eval_root=tmp_path, eval_run_id="run1")
    assert persisted.version == "0.1.0"
    loaded = load_metric_input_snapshot(persisted.artifact_reference, eval_root=tmp_path)
    assert loaded.version == "0.1.0"
    # And it is distinct from the applicability-binding stage.
    assert loaded.model.applicability_binding.evaluation_stage == "universe_screen"


def test_persist_write_once(tmp_path):
    (tmp_path / "run1").mkdir()
    snap = _build("universe_screen")
    persist_metric_input_snapshot(snap, eval_root=tmp_path, eval_run_id="run1")
    with pytest.raises(MetricInputSnapshotError) as e:
        persist_metric_input_snapshot(snap, eval_root=tmp_path, eval_run_id="run1")
    assert e.value.reason_code == "artifact_exists"


def test_persist_rejects_eval_run_id_mismatch(tmp_path):
    (tmp_path / "other").mkdir()
    snap = _build("universe_screen")  # eval_run_id "run1"
    with pytest.raises(MetricInputSnapshotError) as e:
        persist_metric_input_snapshot(snap, eval_root=tmp_path, eval_run_id="other")
    assert e.value.reason_code == "persist_eval_run_id_mismatch"


# --- Public surface --------------------------------------------------------


def test_public_surface():
    assert set(mi.__all__) == {
        "LoadedMetricInputSnapshot", "MetricApplicabilityBinding", "MetricInputSnapshotError",
        "PersistedMetricInputSnapshot", "build_metric_input_snapshot",
        "load_metric_input_snapshot", "persist_metric_input_snapshot",
    }
    for name in mi.__all__:
        assert name in evaluation_pkg.__all__
    # Re-homed member models are reachable and identical objects.
    assert evaluation_pkg.MetricInputSnapshot is MetricInputSnapshot
    assert evaluation_pkg.AxisDefinition is AxisDefinition
    assert evaluation_pkg.AxisEvaluationRecord is AxisEvaluationRecord
