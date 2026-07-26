"""Xe-bind: ``evaluation_output_manifest@0.2.0`` at the single terminal-manifest path.

v0.2 retains the six v0.1 hash fields verbatim and adds the reverse-resolved
``derived_evaluation_stage`` plus the conditional seventh
``observation_target_binding_sha256``. It shares the ONE canonical terminal path, so
a run can never hold two terminal manifests: version selection is a strict declared
contract-version peek, each public reader accepts only its own version, and either
persist collides with the preserved ``artifact_exists`` code. The stage is never
caller-supplied — it is recovered from the run manifest's selected stage-profile
entry hash, requiring exactly one match.
"""

import inspect
import json
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import output_manifest as om_mod
from dynamic_ai_products.evaluation.assertions import persist_assertion_outcomes
from dynamic_ai_products.evaluation.case_sets import load_case_set_manifest
from dynamic_ai_products.evaluation.contracts import canonical_contract_bytes, model_contract_hash
from dynamic_ai_products.evaluation.models import (
    AssertionOutcome,
    EvaluationCase,
    ValidatorFinding,
)
from dynamic_ai_products.evaluation.observation_target_binding import (
    ObservationTargetResolutionDecision,
    build_observation_target_binding,
    persist_observation_target_binding,
)
from dynamic_ai_products.evaluation.output_manifest import (
    EvaluationOutputManifest,
    EvaluationOutputManifestError,
    EvaluationOutputManifestV2,
    LoadedEvaluationOutputManifestV2,
    build_evaluation_output_manifest,
    build_evaluation_output_manifest_v2,
    load_evaluation_output_manifest,
    load_evaluation_output_manifest_v2,
    persist_evaluation_output_manifest,
    persist_evaluation_output_manifest_v2,
)
from dynamic_ai_products.evaluation.parent_observation_snapshot import (
    load_parent_observation_snapshot,
)
from dynamic_ai_products.evaluation.prediction_content import (
    ParsedPredictionContent,
    persist_parsed_prediction_content,
)
from dynamic_ai_products.evaluation.references import CaseResolution, load_target_registry
from dynamic_ai_products.evaluation.runs import (
    initialize_evaluation_run,
    initialize_evaluation_run_v2,
    load_evaluation_run_manifest,
    load_evaluation_run_manifest_v2,
)
from dynamic_ai_products.evaluation.scoring_config import load_scoring_gate_config
from dynamic_ai_products.evaluation.stage_evidence import (
    LoadedStageMetricEvidenceSet,
    build_stage_metric_evidence_set,
    stage_metric_evidence_set_hash,
)
from dynamic_ai_products.evaluation.stage_profiles import (
    StageProfileEntry,
    load_stage_profile_registry,
    resolve_metric_applicability,
)
from dynamic_ai_products.evaluation.validators import persist_validator_findings
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness"
SFX = FX / "substrate_integration"

CASE_SET = load_case_set_manifest("valid_base_case_set_manifest.json", eval_root=FX / "case_sets")
REGISTRY = load_target_registry("valid_target_registry.json", eval_root=FX / "configs")
SCORING = load_scoring_gate_config("valid_scoring_gate_config.json", eval_root=FX / "configs")
SP_REG = load_stage_profile_registry("stage_profiles/stage_profile_registry.json", eval_root=FX)
SUB_REGISTRY = load_target_registry("target_registry.json", eval_root=SFX)
SUB_SCORING = load_scoring_gate_config("scoring_gate_config.json", eval_root=SFX)
SNAP = load_parent_observation_snapshot("parent_observation_snapshot.json", source_root=SFX)

RUN = "run1"
HEX = "a" * 64
CREATED = "2026-07-25T00:00:00+00:00"
CASE_ID = "SYNTH-CASE-FULL-0002"
COMPANY = "SYNTH-CO-0001"
CUTOFF = "2025-12-31"
CAP_OBS = "SYNTH-CAPABILITY-OBS-0001"
PROD_OBS = "SYNTH-PRODUCT-OBS-0001"
CANON_CAP = "SYNTH.PRODUCT.ALPHA.CAPABILITY"
CANON_PROD = "SYNTH.PRODUCT.ALPHA"
TS = "2026-07-26T00:00:00+00:00"

AO_META = {"contract_id": "assertion_outcome", "contract_version": "0.1.0",
           "contract_hash": model_contract_hash(AssertionOutcome, "assertion_outcome", "0.1.0")}
VF_META = {"contract_id": "validator_finding", "contract_version": "0.1.0",
           "contract_hash": model_contract_hash(ValidatorFinding, "validator_finding", "0.1.0")}
PPC_META = {"contract_id": "parsed_prediction_content", "contract_version": "0.1.0",
            "contract_hash": model_contract_hash(
                ParsedPredictionContent, "parsed_prediction_content", "0.1.0")}


# --- Fixtures / builders ----------------------------------------------------


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


def _evidence(stage):
    """The applicable stage-evidence pin wrapper, or None for an extraction stage."""
    kinds = resolve_metric_applicability(SP_REG.registry, stage).required_stage_evidence_kinds
    if not kinds:
        return None
    evset = build_stage_metric_evidence_set(
        evaluation_stage=stage, set_version="se-v1",
        variants=tuple(_KIND_VARIANTS[k] for k in sorted(kinds)))
    return LoadedStageMetricEvidenceSet(
        model=evset, version="se-v1", sha256="d" * 64,
        artifact_reference="stage_evidence/e.json")


def _init_v2(eval_root, stage, run_id=RUN, registry=SP_REG):
    ev = _evidence(stage)
    if ev is not None:
        return initialize_evaluation_run_v2(
            eval_root=eval_root, eval_run_id=run_id, prediction_run_id="P",
            prediction_run_manifest_hash=HEX, case_set=CASE_SET, registry=REGISTRY,
            validator_bundle_version="vb", validator_bundle_hash="b" * 64,
            scoring_config=SCORING, code_commit="c",
            config_snapshot_source_root=FX / "configs", evaluation_created_at=CREATED,
            evaluation_stage=stage, stage_profile_registry=registry,
            semantic_adapter_registry_version="sa-v1", semantic_adapter_registry_hash=HEX,
            selected_semantic_adapter_entry_hash=HEX,
            source_passage_snapshot_version="sp-v1", source_passage_snapshot_hash=HEX,
            gold_assertion_set_version="g-v1", gold_assertion_set_hash=HEX,
            axis_taxonomy_version="ax-v1", axis_taxonomy_hash=HEX,
            validator_rule_parameters_version="vp-v1", validator_rule_parameters_hash=HEX,
            stage_metric_evidence_set_version=ev.model.set_version,
            stage_metric_evidence_set_hash=stage_metric_evidence_set_hash(ev.model),
        ).manifest
    return initialize_evaluation_run_v2(
        eval_root=eval_root, eval_run_id=run_id, prediction_run_id="P",
        prediction_run_manifest_hash=HEX, case_set=CASE_SET, registry=REGISTRY,
        validator_bundle_version="vb", validator_bundle_hash="b" * 64, scoring_config=SCORING,
        code_commit="c", config_snapshot_source_root=FX / "configs", evaluation_created_at=CREATED,
        evaluation_stage=stage, stage_profile_registry=registry,
        semantic_adapter_registry_version="sa-v1", semantic_adapter_registry_hash=HEX,
        selected_semantic_adapter_entry_hash=HEX,
        source_passage_snapshot_version="sp-v1", source_passage_snapshot_hash=HEX,
        gold_assertion_set_version="g-v1", gold_assertion_set_hash=HEX,
        axis_taxonomy_version="ax-v1", axis_taxonomy_hash=HEX,
        validator_rule_parameters_version="vp-v1", validator_rule_parameters_hash=HEX,
    ).manifest


def _findings(root, run_id=RUN):
    finding = ValidatorFinding.model_validate({
        "contract": VF_META, "finding_id": "f1", "validator": "source_id_resolution",
        "validator_bundle_version": "vb", "validator_bundle_hash": "b" * 64,
        "rule_params_hash": HEX, "severity": "error", "run_id": run_id, "artifact_id": "art1",
        "observed_value": "x", "expected_invariant": "y", "message": "m", "evidence": "e",
        "repairable": False, "created_at": CREATED})
    return persist_validator_findings((finding,), eval_root=root, eval_run_id=run_id)


def _outcomes(root, run_id=RUN):
    outcome = AssertionOutcome.model_validate({
        "contract": AO_META, "eval_run_id": run_id, "case_id": CASE_ID, "assertion_id": "A1",
        "assertion_semantic_version": "0.1.0", "outcome": "satisfied"})
    return persist_assertion_outcomes((outcome,), eval_root=root, eval_run_id=run_id)


def _parsed_model():
    return ParsedPredictionContent.model_validate({
        "contract": PPC_META, "case_id": CASE_ID, "stage": "capability_extraction",
        "prediction_record_id": "pred-1", "input_packet_hash": "c" * 64,
        "observation_cutoff": CUTOFF, "raw_artifact_reference": "prediction_source.json",
        "raw_artifact_sha256": "e" * 64, "raw_output_preserved": True, "repair_applied": False,
        "entity_collection": {"completeness": "complete", "entities": [
            {"entity_kind": "capability", "entity_ref": CAP_OBS},
            {"entity_kind": "product", "entity_ref": PROD_OBS}]},
        "field_value_collection": {"completeness": "complete", "field_values": []},
        "evidence_collection": {"completeness": "complete", "evidence": []},
    })


def _case():
    return EvaluationCase.model_validate({
        "case_id": CASE_ID, "stage": "capability_extraction",
        "stage_context": {"observation_window": {"start": "2025-01-01", "end": CUTOFF}},
        "input_source_ids": [], "input_passage_ids": [],
        "assertions": [{"assertion_id": "A1", "kind": "expected_entity",
                        "semantic_version": "0.1.0", "target_references": [CANON_CAP],
                        "scoring_gate_config_references": ["synth-scoring-gate-ref-0001"]}],
        "failure_tags": [], "notes": "n", "created_by": "c", "created_at": TS,
        "guideline_version": "draft-v0.1"})


def _prov(canonical):
    return {"resolution_method": "stable_identity_field",
            "source_field_name": "stable_capability_id", "source_field_value": canonical,
            "registry_entry_reference_id": canonical, "resolver_kind": "deterministic_rule",
            "resolver_ids": ["rule-v1"], "verification_status": "provisional",
            "verification_method": "deterministic_rule_review",
            "decision_timestamps": [TS], "change_reason": "initial binding"}


def _decision(obs, kind, canonical, parent):
    return ObservationTargetResolutionDecision.model_validate({
        "observation_id": obs, "observation_kind": kind, "resolution_status": "resolved",
        "canonical_target_reference": canonical, "parent_referenced": parent,
        "provenance": _prov(canonical)})


def _binding(root, parsed_wrapper, run_id=RUN):
    resolution = CaseResolution.model_validate({
        "case_id": CASE_ID, "target_registry_version": SUB_REGISTRY.version,
        "target_registry_sha256": SUB_REGISTRY.sha256,
        "scoring_config_version": SUB_SCORING.version,
        "scoring_config_sha256": SUB_SCORING.sha256, "assertions": []})
    model = build_observation_target_binding(
        eval_run_id=run_id, case=_case(), company_id=COMPANY, resolution=resolution,
        parsed_prediction_content=parsed_wrapper, target_registry=SUB_REGISTRY,
        resolution_entries=(
            _decision(CAP_OBS, "capability", CANON_CAP, False),
            _decision(PROD_OBS, "product", CANON_PROD, True)),
        parent_snapshot=SNAP)
    return persist_observation_target_binding(model, eval_root=root, eval_run_id=run_id)


def _extraction_run(tmp_path, *, with_parsed=True, with_binding=True, with_outcomes=False):
    _init_v2(tmp_path, "capability_extraction")
    findings = _findings(tmp_path)
    parsed = binding = outcomes = None
    if with_parsed:
        parsed = persist_parsed_prediction_content(
            _parsed_model(), eval_root=tmp_path, eval_run_id=RUN)
    if with_binding:
        binding = _binding(tmp_path, parsed)
    if with_outcomes:
        outcomes = _outcomes(tmp_path)
    return findings, parsed, binding, outcomes


# --- Contract identity ------------------------------------------------------


def test_v2_contract_hash_is_distinct_and_v1_is_unchanged():
    v1 = model_contract_hash(EvaluationOutputManifest, "evaluation_output_manifest", "0.1.0")
    v2 = model_contract_hash(EvaluationOutputManifestV2, "evaluation_output_manifest", "0.2.0")
    assert v1 == "2a58607da0a0d457bee99d6760d7ccb93a6e72ca2e255a82b7cb75e27f956e3e"
    assert v2 != v1
    assert set(EvaluationOutputManifest.model_fields) < set(EvaluationOutputManifestV2.model_fields)
    assert set(EvaluationOutputManifestV2.model_fields) - set(
        EvaluationOutputManifest.model_fields) == {
        "derived_evaluation_stage", "observation_target_binding_sha256"}


def test_builder_exposes_no_stage_parameter():
    params = inspect.signature(build_evaluation_output_manifest_v2).parameters
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in params.values())
    assert not any("stage" in n for n in params if n != "stage_profile_registry")
    assert params["loaded_run"].default is None


# --- One canonical terminal path -------------------------------------------


def test_v2_persists_to_the_single_canonical_path_and_never_a_v2_filename(tmp_path):
    findings, parsed, binding, _ = _extraction_run(tmp_path)
    model = build_evaluation_output_manifest_v2(
        eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings, parsed_prediction_content=parsed,
        observation_target_binding=binding)
    loaded = persist_evaluation_output_manifest_v2(model, eval_root=tmp_path, eval_run_id=RUN)
    out_dir = tmp_path / RUN / "output_manifest"
    assert [p.name for p in sorted(out_dir.iterdir())] == ["evaluation_output_manifest.json"]
    assert loaded.artifact_reference == f"{RUN}/output_manifest/evaluation_output_manifest.json"
    assert loaded.version == "0.2.0"
    assert loaded.sha256 == sha256_bytes(
        (out_dir / "evaluation_output_manifest.json").read_bytes())


def test_v1_then_v2_collides_with_artifact_exists(tmp_path):
    _init_v2(tmp_path, "universe_classification")
    findings = _findings(tmp_path)
    v1 = build_evaluation_output_manifest(
        eval_root=tmp_path, eval_run_id=RUN, validator_findings=findings)
    persist_evaluation_output_manifest(v1, eval_root=tmp_path, eval_run_id=RUN)
    v2 = build_evaluation_output_manifest_v2(
        eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings)
    with pytest.raises(EvaluationOutputManifestError) as ei:
        persist_evaluation_output_manifest_v2(v2, eval_root=tmp_path, eval_run_id=RUN)
    assert ei.value.reason_code == "artifact_exists"


def test_v2_then_v1_collides_with_artifact_exists(tmp_path):
    _init_v2(tmp_path, "universe_classification")
    findings = _findings(tmp_path)
    v2 = build_evaluation_output_manifest_v2(
        eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings)
    persist_evaluation_output_manifest_v2(v2, eval_root=tmp_path, eval_run_id=RUN)
    v1 = build_evaluation_output_manifest(
        eval_root=tmp_path, eval_run_id=RUN, validator_findings=findings)
    with pytest.raises(EvaluationOutputManifestError) as ei:
        persist_evaluation_output_manifest(v1, eval_root=tmp_path, eval_run_id=RUN)
    assert ei.value.reason_code == "artifact_exists"


def test_readers_reject_the_other_version(tmp_path):
    _init_v2(tmp_path, "universe_classification")
    findings = _findings(tmp_path)
    v2 = build_evaluation_output_manifest_v2(
        eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings)
    persist_evaluation_output_manifest_v2(v2, eval_root=tmp_path, eval_run_id=RUN)
    with pytest.raises(EvaluationOutputManifestError) as ei:
        load_evaluation_output_manifest(RUN, eval_root=tmp_path)
    assert ei.value.reason_code == "unsupported_contract_version"
    # And the mirror direction, in a fresh run holding only a v0.1 document.
    root2 = tmp_path / "root2"
    root2.mkdir()
    _init_v2(root2, "universe_classification")
    f2 = _findings(root2)
    v1 = build_evaluation_output_manifest(
        eval_root=root2, eval_run_id=RUN, validator_findings=f2)
    persist_evaluation_output_manifest(v1, eval_root=root2, eval_run_id=RUN)
    with pytest.raises(EvaluationOutputManifestError) as ej:
        load_evaluation_output_manifest_v2(
            RUN, eval_root=root2, stage_profile_registry=SP_REG)
    assert ej.value.reason_code == "unsupported_contract_version"


def test_internal_dispatcher_resolves_either_version_and_rejects_unknown(tmp_path):
    _init_v2(tmp_path, "universe_classification")
    findings = _findings(tmp_path)
    v2 = build_evaluation_output_manifest_v2(
        eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings)
    persist_evaluation_output_manifest_v2(v2, eval_root=tmp_path, eval_run_id=RUN)
    got = om_mod._load_evaluation_output_manifest_any_supported_version(
        RUN, eval_root=tmp_path, stage_profile_registry=SP_REG)
    assert isinstance(got, LoadedEvaluationOutputManifestV2)
    dest = tmp_path / RUN / "output_manifest" / "evaluation_output_manifest.json"
    payload = json.loads(dest.read_text())
    payload["contract"]["contract_version"] = "9.9.9"
    dest.write_text(json.dumps(payload))
    with pytest.raises(EvaluationOutputManifestError) as ei:
        om_mod._load_evaluation_output_manifest_any_supported_version(
            RUN, eval_root=tmp_path, stage_profile_registry=SP_REG)
    assert ei.value.reason_code == "unsupported_contract_version"
    assert "_load_evaluation_output_manifest_any_supported_version" not in om_mod.__all__


# --- Run-wrapper typing -----------------------------------------------------


def test_wrapper_with_v1_inner_manifest_is_rejected(tmp_path):
    root2 = tmp_path / "v1root"
    root2.mkdir()
    initialize_evaluation_run(
        eval_root=root2, eval_run_id=RUN, prediction_run_id="P",
        prediction_run_manifest_hash=HEX, case_set=CASE_SET, registry=REGISTRY,
        validator_bundle_version="vb", validator_bundle_hash="b" * 64, scoring_config=SCORING,
        code_commit="c", config_snapshot_source_root=FX / "configs")
    v1_wrapper = load_evaluation_run_manifest(RUN, eval_root=root2)
    _init_v2(tmp_path, "universe_classification")
    findings = _findings(tmp_path)
    with pytest.raises(EvaluationOutputManifestError) as ei:
        build_evaluation_output_manifest_v2(
            eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
            validator_findings=findings, loaded_run=v1_wrapper)
    assert ei.value.reason_code == "run_manifest_not_v2"


def test_supplied_and_internal_run_load_agree(tmp_path):
    _init_v2(tmp_path, "universe_classification")
    findings = _findings(tmp_path)
    supplied = build_evaluation_output_manifest_v2(
        eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings,
        loaded_run=load_evaluation_run_manifest_v2(RUN, eval_root=tmp_path))
    internal = build_evaluation_output_manifest_v2(
        eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings)
    assert supplied == internal


def test_non_wrapper_loaded_run_is_type_error(tmp_path):
    _init_v2(tmp_path, "universe_classification")
    findings = _findings(tmp_path)
    with pytest.raises(TypeError):
        build_evaluation_output_manifest_v2(
            eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
            validator_findings=findings, loaded_run=object())


# --- Stage derivation by reverse resolution --------------------------------


@pytest.mark.parametrize("stage", ["capability_extraction", "task_extraction",
                                  "universe_classification", "universe_screen"])
def test_stage_is_reverse_resolved_from_the_entry_hash(tmp_path, stage):
    root = tmp_path / stage
    root.mkdir()
    _init_v2(root, stage)
    findings = _findings(root)
    model = build_evaluation_output_manifest_v2(
        eval_root=root, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings)
    assert model.derived_evaluation_stage == stage


def test_registry_version_mismatch(tmp_path):
    _init_v2(tmp_path, "capability_extraction")
    findings = _findings(tmp_path)
    tampered = SP_REG.model_copy(update={
        "registry": SP_REG.registry.model_copy(update={"registry_version": "9.9.9"})})
    with pytest.raises(EvaluationOutputManifestError) as ei:
        build_evaluation_output_manifest_v2(
            eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=tampered,
            validator_findings=findings)
    assert ei.value.reason_code == "stage_profile_registry_version_mismatch"


def test_registry_content_hash_mismatch(tmp_path, monkeypatch):
    _init_v2(tmp_path, "capability_extraction")
    findings = _findings(tmp_path)
    monkeypatch.setattr(om_mod, "stage_profile_registry_hash", lambda registry: "b" * 64)
    with pytest.raises(EvaluationOutputManifestError) as ei:
        build_evaluation_output_manifest_v2(
            eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
            validator_findings=findings)
    assert ei.value.reason_code == "stage_profile_registry_hash_mismatch"


def test_selected_entry_unresolved(tmp_path):
    _init_v2(tmp_path, "capability_extraction")
    findings = _findings(tmp_path)
    # Rewrite the run manifest with a pin that matches no registry entry.
    dest = tmp_path / RUN / "evaluation_run_manifest.json"
    payload = json.loads(dest.read_text())
    payload["selected_stage_profile_entry_hash"] = "c" * 64
    dest.write_text(json.dumps(payload))
    with pytest.raises(EvaluationOutputManifestError) as ei:
        build_evaluation_output_manifest_v2(
            eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
            validator_findings=findings)
    assert ei.value.reason_code == "selected_stage_profile_entry_unresolved"


def test_selected_entry_ambiguous(tmp_path, monkeypatch):
    # With every entry hashing to one constant, the run pin matches more than one
    # entry; exactly-one-match is the fail-closed guarantee.
    monkeypatch.setattr(
        StageProfileEntry, "entry_hash", property(lambda self: "d" * 64), raising=True)
    _init_v2(tmp_path, "capability_extraction")
    findings = _findings(tmp_path)
    with pytest.raises(EvaluationOutputManifestError) as ei:
        build_evaluation_output_manifest_v2(
            eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
            validator_findings=findings)
    assert ei.value.reason_code == "selected_stage_profile_entry_ambiguous"


def test_selected_entry_unsupported(tmp_path):
    _init_v2(tmp_path, "capability_extraction")
    findings = _findings(tmp_path)
    unsupported = next(
        e for e in SP_REG.registry.entries if e.support_status == "unsupported")
    dest = tmp_path / RUN / "evaluation_run_manifest.json"
    payload = json.loads(dest.read_text())
    payload["selected_stage_profile_entry_hash"] = unsupported.entry_hash
    dest.write_text(json.dumps(payload))
    with pytest.raises(EvaluationOutputManifestError) as ei:
        build_evaluation_output_manifest_v2(
            eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
            validator_findings=findings)
    assert ei.value.reason_code == "selected_stage_profile_entry_unsupported"


def test_wrong_registry_type_is_type_error(tmp_path):
    _init_v2(tmp_path, "capability_extraction")
    findings = _findings(tmp_path)
    with pytest.raises(TypeError):
        build_evaluation_output_manifest_v2(
            eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=object(),
            validator_findings=findings)


# --- Binding stage conditional ---------------------------------------------


def test_binding_permitted_and_bound_at_extraction(tmp_path):
    findings, parsed, binding, _ = _extraction_run(tmp_path)
    model = build_evaluation_output_manifest_v2(
        eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings, parsed_prediction_content=parsed,
        observation_target_binding=binding)
    assert model.derived_evaluation_stage == "capability_extraction"
    assert model.observation_target_binding_sha256 == binding.sha256
    loaded = persist_evaluation_output_manifest_v2(model, eval_root=tmp_path, eval_run_id=RUN)
    again = load_evaluation_output_manifest_v2(
        RUN, eval_root=tmp_path, stage_profile_registry=SP_REG, expected_sha256=loaded.sha256)
    assert again.model == model


def test_binding_rejected_for_non_extraction_stage(tmp_path):
    # A real binding (only constructible for an extraction stage) offered to a
    # genuine Universe run is refused on the derived stage, before any file read.
    ex_root = tmp_path / "ex"
    ex_root.mkdir()
    _, parsed, binding, _ = _extraction_run(ex_root)
    uni_root = tmp_path / "uni"
    uni_root.mkdir()
    _init_v2(uni_root, "universe_classification")
    uni_findings = _findings(uni_root)
    with pytest.raises(EvaluationOutputManifestError) as ei:
        build_evaluation_output_manifest_v2(
            eval_root=uni_root, eval_run_id=RUN, stage_profile_registry=SP_REG,
            validator_findings=uni_findings, parsed_prediction_content=parsed,
            observation_target_binding=binding)
    assert ei.value.reason_code == "binding_not_permitted_for_stage"


def test_binding_on_disk_rejected_for_non_extraction_run(tmp_path):
    # A Universe run may not even carry the binding artifact on disk: an omitted
    # optional that exists means the audit chain is silently incomplete.
    ex_root = tmp_path / "ex"
    ex_root.mkdir()
    _extraction_run(ex_root)
    uni_root = tmp_path / "uni"
    uni_root.mkdir()
    _init_v2(uni_root, "universe_classification")
    findings = _findings(uni_root)
    dest = uni_root / RUN / "snapshots"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "observation_target_binding.json").write_bytes(
        (ex_root / RUN / "snapshots" / "observation_target_binding.json").read_bytes())
    with pytest.raises(EvaluationOutputManifestError) as ei:
        build_evaluation_output_manifest_v2(
            eval_root=uni_root, eval_run_id=RUN, stage_profile_registry=SP_REG,
            validator_findings=findings)
    assert ei.value.reason_code == "unexpected_artifact"


def test_model_rejects_binding_on_non_extraction_stage():
    payload = {
        "contract": {"contract_id": "evaluation_output_manifest", "contract_version": "0.2.0",
                     "contract_hash": model_contract_hash(
                         EvaluationOutputManifestV2, "evaluation_output_manifest", "0.2.0")},
        "eval_run_id": RUN, "derived_evaluation_stage": "universe_classification",
        "validator_findings_sha256": HEX, "parsed_prediction_content_sha256": "b" * 64,
        "observation_target_binding_sha256": "c" * 64,
    }
    with pytest.raises(PydanticValidationError) as ei:
        EvaluationOutputManifestV2.model_validate(payload)
    assert "binding_not_permitted_for_stage" in str(ei.value)


# --- Extraction outcomes require the binding (§8.3) ------------------------


def _v2_payload(**ov):
    payload = {
        "contract": {"contract_id": "evaluation_output_manifest", "contract_version": "0.2.0",
                     "contract_hash": model_contract_hash(
                         EvaluationOutputManifestV2, "evaluation_output_manifest", "0.2.0")},
        "eval_run_id": RUN, "derived_evaluation_stage": "capability_extraction",
        "validator_findings_sha256": HEX,
    }
    payload.update(ov)
    return payload


def test_builder_rejects_extraction_outcomes_without_binding(tmp_path):
    findings, parsed, _, _ = _extraction_run(tmp_path, with_binding=False)
    outcomes = _outcomes(tmp_path)
    with pytest.raises(EvaluationOutputManifestError) as ei:
        build_evaluation_output_manifest_v2(
            eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
            validator_findings=findings, parsed_prediction_content=parsed,
            assertion_outcomes=outcomes)
    assert ei.value.reason_code == "extraction_outcomes_require_binding"


def test_model_rejects_extraction_outcomes_without_binding():
    with pytest.raises(PydanticValidationError) as ei:
        EvaluationOutputManifestV2.model_validate(_v2_payload(
            parsed_prediction_content_sha256="b" * 64, assertion_outcomes_sha256="c" * 64))
    assert "extraction_outcomes_require_binding" in str(ei.value)


def _write_manifest(tmp_path, payload):
    out_dir = tmp_path / RUN / "output_manifest"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "evaluation_output_manifest.json").write_bytes(
        canonical_contract_bytes(payload) + b"\n")


def test_loader_rejects_a_handwritten_manifest_without_binding(tmp_path):
    findings, parsed, binding, outcomes = _extraction_run(tmp_path, with_outcomes=True)
    model = build_evaluation_output_manifest_v2(
        eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings, parsed_prediction_content=parsed,
        observation_target_binding=binding, assertion_outcomes=outcomes)
    persisted = model.model_dump(mode="json", exclude_unset=True)
    persisted.pop("observation_target_binding_sha256")
    _write_manifest(tmp_path, persisted)
    with pytest.raises(EvaluationOutputManifestError) as ei:
        load_evaluation_output_manifest_v2(
            RUN, eval_root=tmp_path, stage_profile_registry=SP_REG)
    # The strict model is the first fail-closed boundary for this combination; the
    # loader's own conditional is defence in depth behind it. It must never load.
    assert ei.value.reason_code == "model_validation"


def test_loader_rejects_a_forged_derived_stage(tmp_path):
    # A persisted stage that disagrees with the independently re-derived stage is
    # rejected: the loader never trusts the recorded value.
    findings, parsed, binding, outcomes = _extraction_run(tmp_path, with_outcomes=True)
    model = build_evaluation_output_manifest_v2(
        eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings, parsed_prediction_content=parsed,
        observation_target_binding=binding, assertion_outcomes=outcomes)
    persisted = model.model_dump(mode="json", exclude_unset=True)
    persisted["derived_evaluation_stage"] = "task_extraction"
    _write_manifest(tmp_path, persisted)
    with pytest.raises(EvaluationOutputManifestError) as ei:
        load_evaluation_output_manifest_v2(
            RUN, eval_root=tmp_path, stage_profile_registry=SP_REG)
    assert ei.value.reason_code == "derived_stage_mismatch"


def test_extraction_outcomes_with_binding_accepted(tmp_path):
    findings, parsed, binding, outcomes = _extraction_run(tmp_path, with_outcomes=True)
    model = build_evaluation_output_manifest_v2(
        eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings, parsed_prediction_content=parsed,
        observation_target_binding=binding, assertion_outcomes=outcomes)
    assert model.assertion_outcomes_sha256 == outcomes.sha256
    assert model.observation_target_binding_sha256 == binding.sha256
    persist_evaluation_output_manifest_v2(model, eval_root=tmp_path, eval_run_id=RUN)
    again = load_evaluation_output_manifest_v2(
        RUN, eval_root=tmp_path, stage_profile_registry=SP_REG)
    assert again.model.observation_target_binding_sha256 == binding.sha256


def test_findings_only_invalid_path_remains_valid_at_extraction(tmp_path):
    _init_v2(tmp_path, "capability_extraction")
    findings = _findings(tmp_path)
    model = build_evaluation_output_manifest_v2(
        eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings)
    assert model.observation_target_binding_sha256 is None
    assert model.parsed_prediction_content_sha256 is None
    dumped = model.model_dump(mode="json", exclude_unset=True)
    assert "observation_target_binding_sha256" not in dumped
    persist_evaluation_output_manifest_v2(model, eval_root=tmp_path, eval_run_id=RUN)
    again = load_evaluation_output_manifest_v2(
        RUN, eval_root=tmp_path, stage_profile_registry=SP_REG)
    assert again.model.validator_findings_sha256 == findings.sha256


def test_extraction_binding_without_outcomes_accepted(tmp_path):
    findings, parsed, binding, _ = _extraction_run(tmp_path)
    model = build_evaluation_output_manifest_v2(
        eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings, parsed_prediction_content=parsed,
        observation_target_binding=binding)
    assert model.assertion_outcomes_sha256 is None
    assert model.observation_target_binding_sha256 == binding.sha256


def test_binding_requires_parsed_content(tmp_path):
    findings, parsed, binding, _ = _extraction_run(tmp_path)
    with pytest.raises(EvaluationOutputManifestError) as ei:
        build_evaluation_output_manifest_v2(
            eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
            validator_findings=findings, observation_target_binding=binding)
    assert ei.value.reason_code == "binding_without_parsed_content"


def test_omitted_binding_must_not_exist_on_disk(tmp_path):
    findings, parsed, binding, _ = _extraction_run(tmp_path)
    with pytest.raises(EvaluationOutputManifestError) as ei:
        build_evaluation_output_manifest_v2(
            eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
            validator_findings=findings, parsed_prediction_content=parsed)
    assert ei.value.reason_code == "unexpected_artifact"


def test_binding_parsed_content_mismatch(tmp_path):
    findings, parsed, binding, _ = _extraction_run(tmp_path)
    forged = parsed.model_copy(update={"sha256": "f" * 64})
    with pytest.raises(EvaluationOutputManifestError) as ei:
        build_evaluation_output_manifest_v2(
            eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
            validator_findings=findings, parsed_prediction_content=forged,
            observation_target_binding=binding)
    assert ei.value.reason_code == "artifact_hash_mismatch"


def test_binding_run_id_mismatch(tmp_path):
    findings, parsed, binding, _ = _extraction_run(tmp_path)
    forged_model = binding.model.model_copy(update={"eval_run_id": "other-run"})
    forged = binding.model_copy(update={"model": forged_model})
    with pytest.raises(EvaluationOutputManifestError) as ei:
        build_evaluation_output_manifest_v2(
            eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
            validator_findings=findings, parsed_prediction_content=parsed,
            observation_target_binding=forged)
    assert ei.value.reason_code == "wrapper_run_binding"


# --- Preserved v0.1 field behaviour ----------------------------------------


def test_v1_six_fields_behave_identically_in_v2(tmp_path):
    findings, parsed, binding, outcomes = _extraction_run(tmp_path, with_outcomes=True)
    model = build_evaluation_output_manifest_v2(
        eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings, parsed_prediction_content=parsed,
        observation_target_binding=binding, assertion_outcomes=outcomes)
    assert model.validator_findings_sha256 == findings.sha256
    assert model.parsed_prediction_content_sha256 == parsed.sha256
    assert model.assertion_outcomes_sha256 == outcomes.sha256
    for absent in ("validation_artifact_snapshot_set_sha256", "metric_input_snapshot_sha256",
                   "metric_report_v2_sha256"):
        assert getattr(model, absent) is None


def test_v2_optional_explicit_null_rejected():
    with pytest.raises(PydanticValidationError) as ei:
        EvaluationOutputManifestV2.model_validate(
            _v2_payload(observation_target_binding_sha256=None))
    assert "must not be explicit JSON null" in str(ei.value)


def test_public_surface_exported():
    for name in om_mod.__all__:
        assert name in evaluation_pkg.__all__
        assert getattr(evaluation_pkg, name) is getattr(om_mod, name)
    assert "_ARTIFACT_LOCATION_V2" not in evaluation_pkg.__all__
    assert "_derive_evaluation_stage" not in evaluation_pkg.__all__


# --- Remaining v0.2 loader / model coverage --------------------------------


@pytest.mark.parametrize("field", [
    "parsed_prediction_content_sha256", "observation_target_binding_sha256",
    "assertion_outcomes_sha256", "validation_artifact_snapshot_set_sha256",
    "metric_input_snapshot_sha256", "metric_report_v2_sha256",
])
def test_explicit_null_rejected_for_every_v2_optional_hash_field(field):
    with pytest.raises(PydanticValidationError) as ei:
        EvaluationOutputManifestV2.model_validate(_v2_payload(**{field: None}))
    assert "must not be explicit JSON null" in str(ei.value)


def test_binding_permitted_at_both_extraction_stages():
    for stage in ("capability_extraction", "task_extraction"):
        model = EvaluationOutputManifestV2.model_validate(_v2_payload(
            derived_evaluation_stage=stage,
            parsed_prediction_content_sha256="b" * 64,
            observation_target_binding_sha256="c" * 64,
            assertion_outcomes_sha256="d" * 64))
        assert model.observation_target_binding_sha256 == "c" * 64


def test_dispatcher_rejects_an_absent_declared_version(tmp_path):
    _init_v2(tmp_path, "universe_classification")
    findings = _findings(tmp_path)
    model = build_evaluation_output_manifest_v2(
        eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings)
    persist_evaluation_output_manifest_v2(model, eval_root=tmp_path, eval_run_id=RUN)
    dest = tmp_path / RUN / "output_manifest" / "evaluation_output_manifest.json"
    payload = json.loads(dest.read_text())
    payload.pop("contract")
    dest.write_text(json.dumps(payload))
    with pytest.raises(EvaluationOutputManifestError) as ei:
        om_mod._load_evaluation_output_manifest_any_supported_version(
            RUN, eval_root=tmp_path, stage_profile_registry=SP_REG)
    assert ei.value.reason_code == "unsupported_contract_version"


def test_dispatcher_requires_the_registry_for_a_v2_document(tmp_path):
    _init_v2(tmp_path, "universe_classification")
    findings = _findings(tmp_path)
    model = build_evaluation_output_manifest_v2(
        eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings)
    persist_evaluation_output_manifest_v2(model, eval_root=tmp_path, eval_run_id=RUN)
    with pytest.raises(EvaluationOutputManifestError) as ei:
        om_mod._load_evaluation_output_manifest_any_supported_version(RUN, eval_root=tmp_path)
    assert ei.value.reason_code == "stage_profile_registry_required"


def _persisted_v2(tmp_path):
    _init_v2(tmp_path, "capability_extraction")
    findings = _findings(tmp_path)
    model = build_evaluation_output_manifest_v2(
        eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings)
    return persist_evaluation_output_manifest_v2(model, eval_root=tmp_path, eval_run_id=RUN)


def test_loader_expected_hash_mismatch(tmp_path):
    _persisted_v2(tmp_path)
    with pytest.raises(EvaluationOutputManifestError) as ei:
        load_evaluation_output_manifest_v2(
            RUN, eval_root=tmp_path, stage_profile_registry=SP_REG, expected_sha256="0" * 64)
    assert ei.value.reason_code == "expected_hash_mismatch"


def test_loader_rejects_symlinked_manifest(tmp_path):
    _persisted_v2(tmp_path)
    dest = tmp_path / RUN / "output_manifest" / "evaluation_output_manifest.json"
    external = tmp_path / "external.json"
    external.write_bytes(dest.read_bytes())
    dest.unlink()
    dest.symlink_to(external)
    with pytest.raises(EvaluationOutputManifestError) as ei:
        load_evaluation_output_manifest_v2(
            RUN, eval_root=tmp_path, stage_profile_registry=SP_REG)
    assert ei.value.reason_code == "artifact_symlink"


def test_loader_missing_manifest(tmp_path):
    _init_v2(tmp_path, "capability_extraction")
    with pytest.raises(EvaluationOutputManifestError) as ei:
        load_evaluation_output_manifest_v2(
            RUN, eval_root=tmp_path, stage_profile_registry=SP_REG)
    assert ei.value.reason_code == "artifact_missing"


def test_loader_detects_a_mutated_bound_artifact(tmp_path):
    findings, parsed, binding, _ = _extraction_run(tmp_path)
    model = build_evaluation_output_manifest_v2(
        eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings, parsed_prediction_content=parsed,
        observation_target_binding=binding)
    persist_evaluation_output_manifest_v2(model, eval_root=tmp_path, eval_run_id=RUN)
    target = tmp_path / RUN / "snapshots" / "observation_target_binding.json"
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(EvaluationOutputManifestError) as ei:
        load_evaluation_output_manifest_v2(
            RUN, eval_root=tmp_path, stage_profile_registry=SP_REG)
    assert ei.value.reason_code == "artifact_hash_mismatch"


def test_registry_with_a_validator_bypassing_entry_fails_closed(tmp_path, monkeypatch):
    from dynamic_ai_products.evaluation.stage_profiles import StageProfileError as SPError

    _init_v2(tmp_path, "capability_extraction")
    findings = _findings(tmp_path)

    def _raise(self):
        raise SPError("bypassed entry", reason_code="inconsistent_binding")

    monkeypatch.setattr(StageProfileEntry, "entry_hash", property(_raise), raising=True)
    with pytest.raises(EvaluationOutputManifestError) as ei:
        build_evaluation_output_manifest_v2(
            eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
            validator_findings=findings)
    assert ei.value.reason_code == "stage_profile_registry_invalid"


# --- Raw-artifact coherence at the v0.2 boundary ---------------------------
#
# A binding whose parsed-content hash matches but whose raw provenance points at a
# different artifact would silently break the audit chain back to the model output.
# The builder rejects it, and the loader re-loads both artifacts and re-checks, so a
# merely hash-consistent binding cannot load.


@pytest.mark.parametrize("mutation", [
    {"raw_artifact_reference": "some_other_source.json"},
    {"raw_artifact_sha256": "9" * 64},
])
def test_builder_rejects_binding_raw_artifact_mismatch(tmp_path, mutation):
    findings, parsed, binding, _ = _extraction_run(tmp_path)
    forged_model = binding.model.model_copy(update=mutation)
    forged = binding.model_copy(update={"model": forged_model})
    with pytest.raises(EvaluationOutputManifestError) as ei:
        build_evaluation_output_manifest_v2(
            eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
            validator_findings=findings, parsed_prediction_content=parsed,
            observation_target_binding=forged)
    assert ei.value.reason_code == "binding_raw_artifact_mismatch"


def _repin_binding(tmp_path, mutation):
    """Mutate the persisted binding, then re-pin the manifest to its new hash.

    The result is byte-consistent with what the manifest records — the only defect
    left is semantic, which is exactly what the loader must still catch.
    """
    binding_path = tmp_path / RUN / "snapshots" / "observation_target_binding.json"
    payload = json.loads(binding_path.read_text())
    payload.update(mutation)
    binding_path.write_bytes((json.dumps(payload, sort_keys=True) + "\n").encode())
    new_sha = sha256_bytes(binding_path.read_bytes())
    manifest_path = tmp_path / RUN / "output_manifest" / "evaluation_output_manifest.json"
    recorded = json.loads(manifest_path.read_text())
    recorded["observation_target_binding_sha256"] = new_sha
    manifest_path.write_bytes(canonical_contract_bytes(recorded) + b"\n")
    return new_sha


@pytest.mark.parametrize("mutation", [
    {"raw_artifact_reference": "some_other_source.json"},
    {"raw_artifact_sha256": "9" * 64},
])
def test_loader_rejects_hash_consistent_but_mismatched_raw_artifact(tmp_path, mutation):
    findings, parsed, binding, _ = _extraction_run(tmp_path)
    model = build_evaluation_output_manifest_v2(
        eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings, parsed_prediction_content=parsed,
        observation_target_binding=binding)
    persist_evaluation_output_manifest_v2(model, eval_root=tmp_path, eval_run_id=RUN)
    _repin_binding(tmp_path, mutation)
    with pytest.raises(EvaluationOutputManifestError) as ei:
        load_evaluation_output_manifest_v2(
            RUN, eval_root=tmp_path, stage_profile_registry=SP_REG)
    assert ei.value.reason_code == "binding_raw_artifact_mismatch"
    assert ei.value.artifact_reference == f"{RUN}/snapshots/observation_target_binding.json"


def test_loader_rejects_a_re_pinned_binding_from_another_run(tmp_path):
    findings, parsed, binding, _ = _extraction_run(tmp_path)
    model = build_evaluation_output_manifest_v2(
        eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings, parsed_prediction_content=parsed,
        observation_target_binding=binding)
    persist_evaluation_output_manifest_v2(model, eval_root=tmp_path, eval_run_id=RUN)
    _repin_binding(tmp_path, {"eval_run_id": "some-other-run"})
    with pytest.raises(EvaluationOutputManifestError) as ei:
        load_evaluation_output_manifest_v2(
            RUN, eval_root=tmp_path, stage_profile_registry=SP_REG)
    assert ei.value.reason_code == "binding_run_binding"


def test_loader_rejects_a_re_pinned_binding_for_another_parsed_content(tmp_path):
    findings, parsed, binding, _ = _extraction_run(tmp_path)
    model = build_evaluation_output_manifest_v2(
        eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings, parsed_prediction_content=parsed,
        observation_target_binding=binding)
    persist_evaluation_output_manifest_v2(model, eval_root=tmp_path, eval_run_id=RUN)
    _repin_binding(tmp_path, {"parsed_prediction_content_sha256": "8" * 64})
    with pytest.raises(EvaluationOutputManifestError) as ei:
        load_evaluation_output_manifest_v2(
            RUN, eval_root=tmp_path, stage_profile_registry=SP_REG)
    assert ei.value.reason_code == "binding_parsed_content_mismatch"


def test_loader_accepts_a_coherent_binding_chain(tmp_path):
    findings, parsed, binding, _ = _extraction_run(tmp_path)
    model = build_evaluation_output_manifest_v2(
        eval_root=tmp_path, eval_run_id=RUN, stage_profile_registry=SP_REG,
        validator_findings=findings, parsed_prediction_content=parsed,
        observation_target_binding=binding)
    persist_evaluation_output_manifest_v2(model, eval_root=tmp_path, eval_run_id=RUN)
    again = load_evaluation_output_manifest_v2(
        RUN, eval_root=tmp_path, stage_profile_registry=SP_REG)
    assert again.model == model
    assert binding.model.raw_artifact_reference == parsed.content.raw_artifact_reference
    assert binding.model.raw_artifact_sha256 == parsed.content.raw_artifact_sha256
