"""Slice 8 + Slice 12F: deterministic validator findings, coverage, and the
coverage-aware v0.2 production path.

Findings production is pure and now requires an ``EvaluationRunManifestV2`` plus
a ``LoadedValidatorRuleParameters`` whose version and aggregate hash equal the
v0.2 pin; a v0.1 manifest is rejected. Rule 12 is derived from loaded parsed
content through the sole sanctioned producer.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError as PydanticValidationError

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import validators as val_mod
from dynamic_ai_products.evaluation.case_sets import load_case_set_manifest
from dynamic_ai_products.evaluation.cases import InvalidEvaluationRootError
from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.models import EvaluationRunManifestV2, ValidatorFinding
from dynamic_ai_products.evaluation.prediction_content import (
    LoadedParsedPredictionContent,
    ParsedPredictionContent,
)
from dynamic_ai_products.evaluation.references import load_target_registry
from dynamic_ai_products.evaluation.runs import (
    RunArtifactNotAFileError,
    initialize_evaluation_run,
    load_evaluation_run_manifest,
)
from dynamic_ai_products.evaluation.scoring_config import load_scoring_gate_config
from dynamic_ai_products.evaluation.validator_parameters import (
    complete_rule_parameter_hash,
    load_validator_rule_parameters,
    validator_rule_parameters_aggregate_hash,
)
from dynamic_ai_products.evaluation.validators import (
    VALIDATOR_RULE_ORDER,
    DuplicateValidatorFindingError,
    LoadedValidatorFindings,
    PersistedValidatorFindings,
    SnapshotRunBindingError,
    ValidationArtifactSnapshot,
    ValidatorArtifactMissingError,
    ValidatorArtifactNotAFileError,
    ValidatorBundle,
    ValidatorBundleBindingError,
    ValidatorDecodeError,
    ValidatorError,
    ValidatorFindingRunBindingError,
    ValidatorFindingsExistError,
    ValidatorJsonError,
    ValidatorModelValidationError,
    ValidatorObservation,
    ValidatorRuleConfig,
    ValidatorRuleCoverage,
    ValidatorRuleCoverageReasonCount,
    ValidatorTopLevelTypeError,
    ValidatorWriteError,
    build_validation_artifact_snapshot,
    evaluate_validator_findings,
    load_validator_findings,
    persist_validator_findings,
    validator_bundle_hash,
)
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness"

SCORING = load_scoring_gate_config("valid_scoring_gate_config.json", eval_root=FX / "configs")
REGISTRY = load_target_registry("valid_target_registry.json", eval_root=FX / "configs")
CASE_SET = load_case_set_manifest("valid_base_case_set_manifest.json", eval_root=FX / "case_sets")
PARAMS = load_validator_rule_parameters(
    "validator_parameters/validator_rule_parameters.json", eval_root=FX
)
AGG = validator_rule_parameters_aggregate_hash(PARAMS.model)
ENTRIES = {e.rule_id: e for e in PARAMS.model.entries}

H = "a" * 64
CREATED_AT = "2026-07-20T00:00:00Z"
PSHA = "d" * 64
PARSED_HASH = model_contract_hash(
    ParsedPredictionContent, "parsed_prediction_content", "0.1.0"
)
V2_HASH = "6918e96c0f9d2066e89eaf6a699c00b36e1e52e5b5c74ec0e926533eacaf84d6"


# --- Reconciled bundle + v2 manifest --------------------------------------


def reconciled_bundle(version="vb-1"):
    rules = tuple(
        ValidatorRuleConfig(
            rule_id=rid,
            severity="error",
            rule_params_hash=complete_rule_parameter_hash(ENTRIES[rid]),
            repairable=False,
        )
        for rid in VALIDATOR_RULE_ORDER
    )
    return ValidatorBundle(bundle_version=version, rules=rules)


def _v2_doc(**over):
    doc = {
        "contract": {
            "contract_id": "evaluation_run_manifest",
            "contract_version": "0.2.0",
            "contract_hash": V2_HASH,
        },
        "eval_run_id": "run1",
        "prediction_run_id": "p",
        "prediction_run_manifest_hash": H,
        "case_set_version": "v",
        "case_set_hash": H,
        "registry_snapshot_hash": H,
        "validator_bundle_version": "vb-1",
        "validator_bundle_hash": validator_bundle_hash(reconciled_bundle()),
        "scoring_gate_config_version": "sc",
        "scoring_gate_config_hash": H,
        "code_commit": "commit",
        "pydantic_runtime_version": "2.13.4",
        "evaluation_created_at": "2026-07-23T12:00:00Z",
        "stage_profile_registry_version": "0.1.0",
        "stage_profile_registry_hash": H,
        "selected_stage_profile_entry_hash": H,
        "semantic_adapter_registry_version": "0.1.0",
        "semantic_adapter_registry_hash": H,
        "selected_semantic_adapter_entry_hash": H,
        "source_passage_snapshot_version": "0.1.0",
        "source_passage_snapshot_hash": H,
        "gold_assertion_set_version": "0.1.0",
        "gold_assertion_set_hash": H,
        "axis_taxonomy_version": "0.1.0",
        "axis_taxonomy_hash": H,
        "validator_rule_parameters_version": PARAMS.version,
        "validator_rule_parameters_hash": AGG,
    }
    doc.update(over)
    return doc


def v2_manifest(**over):
    return EvaluationRunManifestV2.model_validate(_v2_doc(**over))


def v1_manifest(tmp_path, run_id="run1"):
    initialize_evaluation_run(
        eval_root=tmp_path, eval_run_id=run_id, prediction_run_id="P",
        prediction_run_manifest_hash=H, case_set=CASE_SET, registry=REGISTRY,
        validator_bundle_version="vb-1",
        validator_bundle_hash=validator_bundle_hash(reconciled_bundle()),
        scoring_config=SCORING, code_commit="c", config_snapshot_source_root=FX / "configs",
    )
    return load_evaluation_run_manifest(run_id, eval_root=tmp_path).manifest


# --- Coverage + snapshot builders -----------------------------------------


def full_coverage():
    return [
        {
            "rule_id": rid,
            "coverage_state": "fully_evaluated",
            "candidate_count": 1,
            "evaluated_observation_count": 1,
            "blocked_candidate_count": 0,
            "reason_counts": [],
        }
        for rid in VALIDATOR_RULE_ORDER
    ]


def _passing_observations():
    return {
        "output_json_schema_validity": {
            "rule_id": "output_json_schema_validity", "observation_id": "o1",
            "parse_succeeded": True, "schema_valid": True, "schema_reference": "s.json",
            "validation_errors": (),
        },
        "required_field_presence": {
            "rule_id": "required_field_presence", "observation_id": "o2",
            "required_fields": ("a", "b"), "present_fields": ("a", "b", "c"),
        },
        "source_id_resolution": {
            "rule_id": "source_id_resolution", "observation_id": "o3",
            "referenced_source_ids": ("s1",), "available_source_ids": ("s1", "s2"),
        },
        "passage_id_resolution": {
            "rule_id": "passage_id_resolution", "observation_id": "o4",
            "referenced_passage_ids": ("p1",), "available_passage_ids": ("p1",),
        },
        "evidence_quote_containment": {
            "rule_id": "evidence_quote_containment", "observation_id": "o5",
            "quote": "alpha", "passage_text": "the alpha beta", "passage_id": "p1",
        },
        "publication_date_cutoff": {
            "rule_id": "publication_date_cutoff", "observation_id": "o6",
            "publication_date": "2020-01-01", "observation_cutoff_date": "2020-06-01",
            "source_id": "s1",
        },
        "product_capability_task_parent_resolution": {
            "rule_id": "product_capability_task_parent_resolution", "observation_id": "o7",
            "child_id": "c1", "parent_id": "pp", "available_parent_ids": ("pp", "qq"),
        },
        "unique_ids_within_scope": {
            "rule_id": "unique_ids_within_scope", "observation_id": "o8",
            "scope_id": "sc", "record_ids": ("a", "b", "c"),
        },
        "prohibited_legacy_fields_absent": {
            "rule_id": "prohibited_legacy_fields_absent", "observation_id": "o9",
            "present_field_names": ("x", "y"), "prohibited_field_names": ("legacy",),
        },
        "active_record_non_roadmap_evidence": {
            "rule_id": "active_record_non_roadmap_evidence", "observation_id": "o10",
            "active": True,
            "evidence": (
                {"evidence_id": "e1", "is_future_roadmap": True},
                {"evidence_id": "e2", "is_future_roadmap": False},
            ),
        },
        "customer_task_outcome_and_evidence": {
            "rule_id": "customer_task_outcome_and_evidence", "observation_id": "o11",
            "is_customer_facing_task": True, "customer_outcome": "did the thing",
            "evidence_ids": ("e1",),
        },
        "raw_output_and_repair_preservation": {
            "rule_id": "raw_output_and_repair_preservation", "observation_id": "o12",
            "raw_output_reference": "raw.json", "raw_artifact_sha256": "c" * 64,
            "raw_output_preserved": True, "repair_applied": True,
            "repair_record_references": ("repair-1",), "repair_record_hashes": ("e" * 64,),
            "parsed_content_sha256": PSHA,
        },
    }


_FAILING = {
    "output_json_schema_validity": {"parse_succeeded": True, "schema_valid": False},
    "required_field_presence": {"required_fields": ("a", "z"), "present_fields": ("a",)},
    "source_id_resolution": {"referenced_source_ids": ("missing",), "available_source_ids": ()},
    "passage_id_resolution": {"referenced_passage_ids": ("missing",), "available_passage_ids": ()},
    "evidence_quote_containment": {"quote": "zzz", "passage_text": "abc", "passage_id": "p1"},
    "publication_date_cutoff": {
        "publication_date": "2021-01-01", "observation_cutoff_date": "2020-06-01",
    },
    "product_capability_task_parent_resolution": {
        "parent_id": "absent", "available_parent_ids": ("pp",),
    },
    "unique_ids_within_scope": {"record_ids": ("a", "a", "b")},
    "prohibited_legacy_fields_absent": {
        "present_field_names": ("legacy", "x"), "prohibited_field_names": ("legacy",),
    },
    "active_record_non_roadmap_evidence": {
        "active": True, "evidence": ({"evidence_id": "e1", "is_future_roadmap": True},),
    },
    "customer_task_outcome_and_evidence": {
        "is_customer_facing_task": True, "customer_outcome": None, "evidence_ids": (),
    },
    "raw_output_and_repair_preservation": {
        "raw_output_reference": None, "raw_artifact_sha256": None,
        "repair_applied": True, "repair_record_references": (), "repair_record_hashes": (),
    },
}


def snapshot(*, failing=(), run_id="run1", artifact_id="art-1", case_id="SYNTH-CASE-0001",
             created_at=CREATED_AT, observations=None, coverage=None, entity_ids=None,
             parsed_sha=PSHA, stage="capability_extraction"):
    if observations is None:
        base = _passing_observations()
        for rid in failing:
            base[rid] = {**base[rid], **_FAILING[rid]}
        if entity_ids:
            for rid, eid in entity_ids.items():
                base[rid] = {**base[rid], "entity_id": eid}
        observations = tuple(base[rid] for rid in VALIDATOR_RULE_ORDER)
    return ValidationArtifactSnapshot.model_validate(
        {
            "eval_run_id": run_id, "artifact_id": artifact_id, "stage": stage,
            "artifact_sha256": "b" * 64,
            "parsed_prediction_content_sha256": parsed_sha, "created_at": created_at,
            "case_id": case_id, "observations": list(observations),
            "coverage": coverage if coverage is not None else full_coverage(),
        }
    )


def loaded_parsed(*, prediction_record_id="pred-1", raw_ref="raw.json", raw_sha="c" * 64,
                  preserved=True, repair_applied=True, repair_refs=("repair-1",),
                  repair_hashes=("e" * 64,), sha=PSHA, stage="capability_extraction"):
    content = ParsedPredictionContent.model_validate(
        {
            "contract": {
                "contract_id": "parsed_prediction_content",
                "contract_version": "0.1.0", "contract_hash": PARSED_HASH,
            },
            "case_id": "SYNTH-CASE-0001", "stage": stage,
            "prediction_record_id": prediction_record_id, "input_packet_hash": H,
            "observation_cutoff": "2025-06-30", "raw_artifact_reference": raw_ref,
            "raw_artifact_sha256": raw_sha, "raw_output_preserved": preserved,
            "repair_applied": repair_applied,
            "repair_record_references": list(repair_refs),
            "repair_record_hashes": list(repair_hashes),
            "entity_collection": {"completeness": "unavailable"},
            "field_value_collection": {"completeness": "unavailable"},
            "evidence_collection": {"completeness": "unavailable"},
        }
    )
    return LoadedParsedPredictionContent(
        content=content, sha256=sha, artifact_reference="parsed.json"
    )


_OBS_ADAPTER = TypeAdapter(ValidatorObservation)


def obs_models_1_11():
    base = _passing_observations()
    return tuple(_OBS_ADAPTER.validate_python(base[r]) for r in VALIDATOR_RULE_ORDER[:-1])


def cov_models_1_11():
    return tuple(
        ValidatorRuleCoverage(rule_id=r, coverage_state="fully_evaluated",
                              candidate_count=1, evaluated_observation_count=1,
                              blocked_candidate_count=0)
        for r in VALIDATOR_RULE_ORDER[:-1]
    )


def evaluate(snap, *, bundle=None, manifest=None, params=PARAMS):
    return evaluate_validator_findings(
        snap, bundle=bundle or reconciled_bundle(),
        run_manifest=manifest or v2_manifest(), rule_parameters=params,
    )


def init_run(tmp_path, run_id="run1"):
    """Initialize the on-disk committed v0.1 run directory (persistence layout)."""
    v1_manifest(tmp_path, run_id)


def evaluated(tmp_path, failing=("source_id_resolution", "unique_ids_within_scope")):
    return evaluate(snapshot(failing=failing))


def _single_failing(rule_id, override):
    obs = _passing_observations()
    obs[rule_id] = {**obs[rule_id], **override}
    return evaluate(snapshot(observations=tuple(obs[r] for r in VALIDATOR_RULE_ORDER)))


def write_findings_dir(tmp_path, data, run_id="run1"):
    d = tmp_path / run_id / "findings"
    d.mkdir(parents=True, exist_ok=False)
    (d / "validator_findings.jsonl").write_bytes(data)


def finding_line(tmp_path):
    return val_mod._canonical_finding_line(evaluated(tmp_path).findings[0]) + b"\n"


# --- Bundle contract ------------------------------------------------------


def test_bundle_exact_rule_set_and_order():
    assert tuple(r.rule_id for r in reconciled_bundle().rules) == VALIDATOR_RULE_ORDER


def test_bundle_rejects_missing_rule():
    rules = tuple(
        ValidatorRuleConfig(rule_id=r, severity="error", rule_params_hash=H, repairable=False)
        for r in VALIDATOR_RULE_ORDER[:-1]
    )
    with pytest.raises(PydanticValidationError):
        ValidatorBundle(bundle_version="v", rules=rules)


def test_bundle_hash_deterministic_and_sensitive():
    assert validator_bundle_hash(reconciled_bundle()) == validator_bundle_hash(reconciled_bundle())
    # Sensitive to a changed bundle version...
    assert validator_bundle_hash(reconciled_bundle("x")) != validator_bundle_hash(reconciled_bundle())
    # ...and to a same-version policy change such as a severity change.
    severity_changed = ValidatorBundle(
        bundle_version="vb-1",
        rules=tuple(
            ValidatorRuleConfig(
                rule_id=rid,
                severity="critical" if rid == "source_id_resolution" else "error",
                rule_params_hash=complete_rule_parameter_hash(ENTRIES[rid]), repairable=False,
            )
            for rid in VALIDATOR_RULE_ORDER
        ),
    )
    assert validator_bundle_hash(severity_changed) != validator_bundle_hash(reconciled_bundle())


# --- Observation / snapshot validation ------------------------------------


def test_observation_no_verdict_field_accepted():
    snap = snapshot()
    assert len(snap.observations) == 12
    assert len(snap.coverage) == 12


def test_snapshot_requires_coverage():
    obs = list(_passing_observations().values())
    with pytest.raises(PydanticValidationError):
        ValidationArtifactSnapshot.model_validate({
            "eval_run_id": "run1", "artifact_id": "a", "stage": "capability_extraction",
            "artifact_sha256": "b" * 64,
            "parsed_prediction_content_sha256": PSHA, "created_at": CREATED_AT,
            "observations": obs,
        })


def test_snapshot_rejects_duplicate_observation_id():
    obs = _passing_observations()
    obs["required_field_presence"]["observation_id"] = "o1"
    with pytest.raises(PydanticValidationError):
        snapshot(observations=tuple(obs[r] for r in VALIDATOR_RULE_ORDER))


def test_snapshot_rejects_non_rfc3339_created_at():
    with pytest.raises(PydanticValidationError):
        snapshot(created_at="2026-07-20")


def test_snapshot_observation_count_must_equal_evaluated():
    cov = full_coverage()
    idx = VALIDATOR_RULE_ORDER.index("evidence_quote_containment")
    # blocked_by_dependency has evaluated==0 while the observation is still present
    cov[idx] = {
        "rule_id": "evidence_quote_containment", "coverage_state": "blocked_by_dependency",
        "candidate_count": 1, "evaluated_observation_count": 0, "blocked_candidate_count": 1,
        "reason_counts": [{"reason_code": "blocked_passage_unresolved", "count": 1}],
    }
    with pytest.raises(PydanticValidationError):
        snapshot(coverage=cov)  # obs count 1 != evaluated 0


# --- Correction A: stage-bound coverage -----------------------------------


def test_capability_extraction_rejects_rule7_inapplicable():
    cov = full_coverage()
    idx = VALIDATOR_RULE_ORDER.index("product_capability_task_parent_resolution")
    cov[idx] = {
        "rule_id": "product_capability_task_parent_resolution", "coverage_state": "inapplicable",
        "candidate_count": 0, "evaluated_observation_count": 0, "blocked_candidate_count": 0,
        "reason_counts": [{"reason_code": "stage_has_no_product_capability_task_hierarchy", "count": 1}],
    }
    obs = _passing_observations()
    del obs["product_capability_task_parent_resolution"]  # inapplicable -> no observation
    ordered = tuple(
        obs[r] for r in VALIDATOR_RULE_ORDER if r != "product_capability_task_parent_resolution"
    )
    with pytest.raises(PydanticValidationError):
        snapshot(stage="capability_extraction", coverage=cov, observations=ordered)


_UNIVERSE_INAPPLICABLE = {
    "product_capability_task_parent_resolution": "stage_has_no_product_capability_task_hierarchy",
    "active_record_non_roadmap_evidence": "stage_has_no_active_deployment_record",
    "customer_task_outcome_and_evidence": "stage_emits_no_customer_facing_task",
}


def _universe_snapshot(**over):
    obs = _passing_observations()
    for rid in _UNIVERSE_INAPPLICABLE:
        del obs[rid]
    ordered = tuple(obs[r] for r in VALIDATOR_RULE_ORDER if r not in _UNIVERSE_INAPPLICABLE)
    coverage = []
    for rid in VALIDATOR_RULE_ORDER:
        if rid in _UNIVERSE_INAPPLICABLE:
            coverage.append({
                "rule_id": rid, "coverage_state": "inapplicable", "candidate_count": 0,
                "evaluated_observation_count": 0, "blocked_candidate_count": 0,
                "reason_counts": [{"reason_code": _UNIVERSE_INAPPLICABLE[rid], "count": 1}],
            })
        else:
            coverage.append({
                "rule_id": rid, "coverage_state": "fully_evaluated", "candidate_count": 1,
                "evaluated_observation_count": 1, "blocked_candidate_count": 0, "reason_counts": [],
            })
    return snapshot(stage="universe_screen", observations=ordered, coverage=coverage, **over)


def test_universe_stage_rule7_inapplicable_accepted():
    # Selected-stage evaluation accepts the governed universe-stage inapplicability.
    snap = _universe_snapshot()
    assert snap.stage == "universe_screen"
    result = evaluate(snap)
    assert result.findings == ()


def test_evaluate_wrong_inapplicable_reason_rejected():
    # Rule 7 inapplicable at universe_screen but with a reason belonging only to Rule 10
    cov = full_coverage()
    idx = VALIDATOR_RULE_ORDER.index("product_capability_task_parent_resolution")
    cov[idx] = {
        "rule_id": "product_capability_task_parent_resolution", "coverage_state": "inapplicable",
        "candidate_count": 0, "evaluated_observation_count": 0, "blocked_candidate_count": 0,
        "reason_counts": [{"reason_code": "stage_has_no_active_deployment_record", "count": 1}],
    }
    obs = _passing_observations()
    del obs["product_capability_task_parent_resolution"]
    ordered = tuple(
        obs[r] for r in VALIDATOR_RULE_ORDER if r != "product_capability_task_parent_resolution"
    )
    snap = snapshot(stage="universe_screen", coverage=cov, observations=ordered)
    with pytest.raises(ValidatorBundleBindingError) as exc:
        evaluate(snap)
    assert exc.value.binding_kind == "coverage_reason_code_unknown"


def test_partial_coverage_unaccounted_candidate_rejected():
    with pytest.raises(PydanticValidationError):
        ValidatorRuleCoverage(
            rule_id="evidence_quote_containment", coverage_state="partially_evaluated",
            candidate_count=5, evaluated_observation_count=3, blocked_candidate_count=1,
            reason_counts=(ValidatorRuleCoverageReasonCount(
                reason_code="blocked_passage_unresolved", count=1),),
        )  # evaluated(3)+blocked(1) != candidate(5)


# --- Correction B: Rule 12 real hash provenance ---------------------------


def test_rule12_malformed_raw_sha_rejected():
    obs = _passing_observations()
    obs["raw_output_and_repair_preservation"]["raw_artifact_sha256"] = "NOTHEX"
    with pytest.raises(PydanticValidationError):
        snapshot(observations=tuple(obs[r] for r in VALIDATOR_RULE_ORDER))


def test_rule12_malformed_repair_hash_rejected():
    obs = _passing_observations()
    obs["raw_output_and_repair_preservation"]["repair_record_hashes"] = ("ABCD",)
    with pytest.raises(PydanticValidationError):
        snapshot(observations=tuple(obs[r] for r in VALIDATOR_RULE_ORDER))


def test_rule12_raw_output_preserved_required():
    obs = _passing_observations()
    del obs["raw_output_and_repair_preservation"]["raw_output_preserved"]
    with pytest.raises(PydanticValidationError):
        snapshot(observations=tuple(obs[r] for r in VALIDATOR_RULE_ORDER))


def test_rule12_valid_paired_provenance_evaluates_clean():
    result = evaluate(snapshot())
    assert all(f.validator != "raw_output_and_repair_preservation" for f in result.findings)


def test_snapshot_rule12_coverage_must_be_fully_evaluated():
    cov = full_coverage()
    cov[-1]["evaluated_observation_count"] = 1
    cov[-1]["candidate_count"] = 2  # Rule 12 must be exactly 1/1/0
    with pytest.raises(PydanticValidationError):
        snapshot(coverage=cov)


def test_snapshot_rule12_parsed_sha_binding():
    obs = _passing_observations()
    obs["raw_output_and_repair_preservation"]["parsed_content_sha256"] = "f" * 64
    with pytest.raises(PydanticValidationError):
        snapshot(observations=tuple(obs[r] for r in VALIDATOR_RULE_ORDER))


# --- Coverage model invariants --------------------------------------------


def test_coverage_fully_evaluated_ok():
    ValidatorRuleCoverage(
        rule_id="source_id_resolution", coverage_state="fully_evaluated",
        candidate_count=3, evaluated_observation_count=3, blocked_candidate_count=0,
    )


def test_coverage_partial_requires_blocked_reason_sum():
    ValidatorRuleCoverage(
        rule_id="evidence_quote_containment", coverage_state="partially_evaluated",
        candidate_count=5, evaluated_observation_count=3, blocked_candidate_count=2,
        reason_counts=(ValidatorRuleCoverageReasonCount(reason_code="blocked_passage_unresolved", count=2),),
    )
    with pytest.raises(PydanticValidationError):  # sum(1) != blocked(2)
        ValidatorRuleCoverage(
            rule_id="evidence_quote_containment", coverage_state="partially_evaluated",
            candidate_count=5, evaluated_observation_count=3, blocked_candidate_count=2,
            reason_counts=(ValidatorRuleCoverageReasonCount(reason_code="blocked_passage_unresolved", count=1),),
        )


def test_coverage_blocked_by_dependency_ok():
    ValidatorRuleCoverage(
        rule_id="evidence_quote_containment", coverage_state="blocked_by_dependency",
        candidate_count=4, evaluated_observation_count=0, blocked_candidate_count=4,
        reason_counts=(ValidatorRuleCoverageReasonCount(reason_code="blocked_passage_unresolved", count=4),),
    )


def test_coverage_inapplicable_ok_and_bad():
    ValidatorRuleCoverage(
        rule_id="product_capability_task_parent_resolution", coverage_state="inapplicable",
        candidate_count=0, evaluated_observation_count=0, blocked_candidate_count=0,
        reason_counts=(ValidatorRuleCoverageReasonCount(
            reason_code="stage_has_no_product_capability_task_hierarchy", count=1),),
    )
    with pytest.raises(PydanticValidationError):  # inapplicable with candidates
        ValidatorRuleCoverage(
            rule_id="product_capability_task_parent_resolution", coverage_state="inapplicable",
            candidate_count=2, evaluated_observation_count=0, blocked_candidate_count=0,
            reason_counts=(ValidatorRuleCoverageReasonCount(
                reason_code="stage_has_no_product_capability_task_hierarchy", count=1),),
        )


def test_coverage_reason_counts_sorted_unique_positive():
    with pytest.raises(PydanticValidationError):  # non-positive count
        ValidatorRuleCoverageReasonCount(reason_code="blocked_source_unresolved", count=0)
    with pytest.raises(PydanticValidationError):  # unsorted
        ValidatorRuleCoverage(
            rule_id="publication_date_cutoff", coverage_state="partially_evaluated",
            candidate_count=4, evaluated_observation_count=2, blocked_candidate_count=2,
            reason_counts=(
                ValidatorRuleCoverageReasonCount(reason_code="zzz", count=1),
                ValidatorRuleCoverageReasonCount(reason_code="aaa", count=1),
            ),
        )


# --- Sanctioned producer ---------------------------------------------------


def test_producer_appends_rule12_and_binds_parsed_sha():
    # Non-default stage: the produced snapshot's stage is derived only from the
    # loaded parsed content's stage.
    loaded = loaded_parsed(stage="task_extraction")
    snap = build_validation_artifact_snapshot(
        loaded, eval_run_id="run1", artifact_id="a", artifact_sha256="b" * 64,
        created_at=CREATED_AT, case_id="SYNTH-CASE-0001",
        observations=obs_models_1_11(), coverage=cov_models_1_11(),
    )
    assert snap.stage == loaded.content.stage == "task_extraction"
    assert snap.parsed_prediction_content_sha256 == loaded.sha256
    r12 = [o for o in snap.observations if o.rule_id == "raw_output_and_repair_preservation"]
    assert len(r12) == 1 and r12[0].parsed_content_sha256 == loaded.sha256
    assert r12[0].raw_artifact_sha256 == loaded.content.raw_artifact_sha256


def test_producer_rejects_caller_rule12_observation():
    obs_all = tuple(
        _OBS_ADAPTER.validate_python(_passing_observations()[r]) for r in VALIDATOR_RULE_ORDER
    )
    with pytest.raises(ValueError):
        build_validation_artifact_snapshot(
            loaded_parsed(), eval_run_id="run1", artifact_id="a", artifact_sha256="b" * 64,
            created_at=CREATED_AT, observations=obs_all, coverage=cov_models_1_11(),
        )


def test_producer_rejects_caller_rule12_coverage():
    bad_cov = cov_models_1_11() + (ValidatorRuleCoverage(
        rule_id="raw_output_and_repair_preservation", coverage_state="fully_evaluated",
        candidate_count=1, evaluated_observation_count=1, blocked_candidate_count=0),)
    with pytest.raises(ValueError):
        build_validation_artifact_snapshot(
            loaded_parsed(), eval_run_id="run1", artifact_id="a", artifact_sha256="b" * 64,
            created_at=CREATED_AT, observations=obs_models_1_11(), coverage=bad_cov,
        )


def test_producer_type_guard():
    with pytest.raises(TypeError):
        build_validation_artifact_snapshot(
            object(), eval_run_id="run1", artifact_id="a", artifact_sha256="b" * 64,
            created_at=CREATED_AT, observations=(), coverage=(),
        )


# --- Evaluate: v1/v2 boundary + parameter binding -------------------------


def test_v1_manifest_rejected(tmp_path):
    manifest = v1_manifest(tmp_path)
    with pytest.raises(ValidatorBundleBindingError) as exc:
        evaluate(snapshot(), manifest=manifest)
    assert exc.value.binding_kind == "run_manifest_version_unsupported"


def test_parameter_version_mismatch():
    manifest = v2_manifest(validator_rule_parameters_version="other")
    with pytest.raises(ValidatorBundleBindingError) as exc:
        evaluate(snapshot(), manifest=manifest)
    assert exc.value.binding_kind == "parameter_set_version_mismatch"


def test_parameter_hash_mismatch():
    manifest = v2_manifest(validator_rule_parameters_hash="f" * 64)
    with pytest.raises(ValidatorBundleBindingError) as exc:
        evaluate(snapshot(), manifest=manifest)
    assert exc.value.binding_kind == "parameter_set_hash_mismatch"


def test_rule_params_hash_mismatch():
    rules = tuple(
        ValidatorRuleConfig(rule_id=rid, severity="error", rule_params_hash=H, repairable=False)
        for rid in VALIDATOR_RULE_ORDER
    )
    bad_bundle = ValidatorBundle(bundle_version="vb-1", rules=rules)
    manifest = v2_manifest(validator_bundle_hash=validator_bundle_hash(bad_bundle))
    with pytest.raises(ValidatorBundleBindingError) as exc:
        evaluate(snapshot(), bundle=bad_bundle, manifest=manifest)
    assert exc.value.binding_kind == "rule_params_hash_mismatch"


def test_coverage_reason_code_unknown():
    cov = full_coverage()
    cov[4]["coverage_state"] = "partially_evaluated"
    cov[4]["candidate_count"] = 2
    cov[4]["evaluated_observation_count"] = 1
    cov[4]["blocked_candidate_count"] = 1
    cov[4]["reason_counts"] = [{"reason_code": "not_a_governed_reason", "count": 1}]
    # rule index 4 = evidence_quote_containment; give it 1 observation
    with pytest.raises(ValidatorBundleBindingError) as exc:
        evaluate(snapshot(coverage=cov))
    assert exc.value.binding_kind == "coverage_reason_code_unknown"


def test_bundle_version_mismatch():
    manifest = v2_manifest(validator_bundle_version="other")
    with pytest.raises(ValidatorBundleBindingError) as exc:
        evaluate(snapshot(), manifest=manifest)
    assert exc.value.binding_kind == "bundle_version_mismatch"


def test_rule_parameters_type_guard():
    with pytest.raises(TypeError):
        evaluate_validator_findings(
            snapshot(), bundle=reconciled_bundle(), run_manifest=v2_manifest(),
            rule_parameters=object(),
        )


# --- Finding production ----------------------------------------------------


def test_clean_snapshot_yields_no_findings():
    result = evaluate(snapshot())
    assert result.findings == ()


def test_each_rule_fails_when_violated():
    for rid in VALIDATOR_RULE_ORDER:
        result = evaluate(snapshot(failing=(rid,)))
        assert len(result.findings) == 1, rid
        assert result.findings[0].validator == rid, rid


def test_findings_deterministic_and_distinct():
    s = snapshot(failing=("source_id_resolution", "passage_id_resolution"))
    a = evaluate(s)
    b = evaluate(s)
    assert a.findings == b.findings
    assert a.findings[0] is not b.findings[0]
    assert val_mod._canonical_finding_line(a.findings[0]) == val_mod._canonical_finding_line(
        b.findings[0]
    )


def test_finding_id_is_deterministic_hex():
    result = evaluate(snapshot(failing=("passage_id_resolution",)))
    fid = result.findings[0].finding_id
    assert len(fid) == 64 and all(c in "0123456789abcdef" for c in fid)


def test_created_at_copied_from_snapshot():
    result = evaluate(snapshot(failing=("unique_ids_within_scope",), created_at=CREATED_AT))
    assert result.findings[0].created_at == CREATED_AT


def test_rule12_failure_when_raw_missing():
    result = evaluate(snapshot(failing=("raw_output_and_repair_preservation",)))
    assert any(f.validator == "raw_output_and_repair_preservation" for f in result.findings)


def test_no_raw_text_leakage_in_quote_finding():
    result = evaluate(snapshot(failing=("evidence_quote_containment",)))
    finding = next(f for f in result.findings if f.validator == "evidence_quote_containment")
    assert "zzz" not in finding.evidence and "zzz" not in finding.observed_value


# --- Persistence + load ----------------------------------------------------


def test_persist_and_load_roundtrip(tmp_path):
    v1_manifest(tmp_path)  # initialize the run directory
    result = evaluate(snapshot(failing=("source_id_resolution",)))
    persisted = persist_validator_findings(result.findings, eval_root=tmp_path, eval_run_id="run1")
    assert persisted.sha256 == sha256_bytes((tmp_path / persisted.artifact_reference).read_bytes())
    loaded = load_validator_findings("run1", eval_root=tmp_path)
    assert [f.finding_id for f in loaded.findings] == [f.finding_id for f in result.findings]


def test_persist_is_write_once(tmp_path):
    v1_manifest(tmp_path)
    result = evaluate(snapshot(failing=("source_id_resolution",)))
    persist_validator_findings(result.findings, eval_root=tmp_path, eval_run_id="run1")
    with pytest.raises(ValidatorFindingsExistError):
        persist_validator_findings(result.findings, eval_root=tmp_path, eval_run_id="run1")


# --- Protected + surface ---------------------------------------------------


def test_validator_finding_contract_hash_preserved():
    assert model_contract_hash(ValidatorFinding, "validator_finding", "0.1.0") == (
        "96f63fee300d363a662f4f956bacccdca596acfb0f22bf7039aa1335b6d61292"
    )


def test_private_rule12_producer_not_exported():
    assert "_build_rule12_validation_observation" not in evaluation_pkg.__all__
    assert "build_validation_artifact_snapshot" in evaluation_pkg.__all__
    assert hasattr(val_mod, "_build_rule12_validation_observation")


# --- Import purity ---------------------------------------------------------


def test_import_no_io_no_hash_no_clock():
    code = "\n".join([
        "import sys, os, hashlib, importlib, time",
        "sys.path.insert(0, 'src')",
        "import pydantic",
        "import dynamic_ai_products, dynamic_ai_products.universe.io_utils",
        "import dynamic_ai_products.evaluation",
        "sys.modules.pop('dynamic_ai_products.evaluation.validators', None)",
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
        "importlib.import_module('dynamic_ai_products.evaluation.validators')",
        "Path.read_bytes,Path.read_text,Path.mkdir,os.open,hashlib.sha256=orb,ort,omk,oop,osha",
        "time.time,time.monotonic=ot1,ot2",
        "assert reads==[], reads",
        "assert writes==[], writes",
        "assert sha==[], len(sha)",
        "assert clock==[], len(clock)",
        "print('OK')",
    ])
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr


# --- Restored Slice 8 semantics (ported to the v0.2 contract) --------------


def test_bundle_rejects_duplicate_rule():
    rules = tuple(
        ValidatorRuleConfig(rule_id=r, severity="error", rule_params_hash="a" * 64, repairable=False)
        for r in VALIDATOR_RULE_ORDER[:-1]
    ) + (
        ValidatorRuleConfig(
            rule_id=VALIDATOR_RULE_ORDER[0], severity="error", rule_params_hash="a" * 64,
            repairable=False,
        ),
    )
    with pytest.raises(PydanticValidationError):
        ValidatorBundle(bundle_version="vb-1", rules=rules)


def test_bundle_rejects_wrong_order():
    reordered = (VALIDATOR_RULE_ORDER[1], VALIDATOR_RULE_ORDER[0]) + VALIDATOR_RULE_ORDER[2:]
    rules = tuple(
        ValidatorRuleConfig(rule_id=r, severity="error", rule_params_hash="a" * 64, repairable=False)
        for r in reordered
    )
    with pytest.raises(PydanticValidationError):
        ValidatorBundle(bundle_version="vb-1", rules=rules)


def test_rule_params_hash_must_be_hex():
    with pytest.raises(PydanticValidationError):
        ValidatorRuleConfig(
            rule_id="source_id_resolution", severity="error",
            rule_params_hash="NOTHEX", repairable=False,
        )


# --- Handler pass paths ----------------------------------------------------


def test_non_active_record_passes_roadmap_rule():
    result = _single_failing(
        "active_record_non_roadmap_evidence",
        {"active": False, "evidence": ({"evidence_id": "e1", "is_future_roadmap": True},)},
    )
    assert result.findings == ()


def test_non_customer_task_passes_outcome_rule():
    result = _single_failing(
        "customer_task_outcome_and_evidence",
        {"is_customer_facing_task": False, "customer_outcome": None, "evidence_ids": ()},
    )
    assert result.findings == ()


def test_no_repair_applied_needs_no_repair_record():
    result = _single_failing(
        "raw_output_and_repair_preservation",
        {"repair_applied": False, "repair_record_references": (), "repair_record_hashes": ()},
    )
    assert result.findings == ()


# --- Blank-value semantics --------------------------------------------------


@pytest.mark.parametrize("quote", ["", "   ", "\t"])
def test_blank_quote_does_not_pass_by_substring_accident(quote):
    result = _single_failing(
        "evidence_quote_containment",
        {"quote": quote, "passage_text": "the alpha beta", "passage_id": "p1"},
    )
    assert len(result.findings) == 1
    assert result.findings[0].validator == "evidence_quote_containment"


def test_nonblank_quote_substring_still_passes():
    result = _single_failing(
        "evidence_quote_containment",
        {"quote": "alpha", "passage_text": "the alpha beta", "passage_id": "p1"},
    )
    assert result.findings == ()


@pytest.mark.parametrize("evidence_ids", [("",), ("   ",), ("", "  ")])
def test_blank_evidence_id_is_not_supporting_evidence(evidence_ids):
    result = _single_failing(
        "customer_task_outcome_and_evidence",
        {"is_customer_facing_task": True, "customer_outcome": "did x", "evidence_ids": evidence_ids},
    )
    assert len(result.findings) == 1
    assert result.findings[0].validator == "customer_task_outcome_and_evidence"


@pytest.mark.parametrize("repair_refs", [("",), ("   ",)])
def test_blank_repair_record_reference_does_not_satisfy(repair_refs):
    # Correction B strengthens this: a blank repair reference is now rejected at
    # observation construction (stronger than a handler finding), so the unsafe
    # provenance never reaches evaluation.
    with pytest.raises(PydanticValidationError):
        _single_failing(
            "raw_output_and_repair_preservation",
            {"repair_applied": True, "repair_record_references": repair_refs,
             "repair_record_hashes": ("e" * 64,)},
        )


def test_nonblank_evidence_and_repair_still_pass():
    assert evaluate(snapshot()).findings == ()


# --- Severity stamping + binding -------------------------------------------


@pytest.mark.parametrize("severity", ["critical", "error", "warning", "info"])
def test_all_four_severities_stamped_from_bundle(severity):
    rules = tuple(
        ValidatorRuleConfig(
            rule_id=rid,
            severity=severity if rid == "source_id_resolution" else "error",
            rule_params_hash=complete_rule_parameter_hash(ENTRIES[rid]),
            repairable=(rid == "source_id_resolution"),
        )
        for rid in VALIDATOR_RULE_ORDER
    )
    b = ValidatorBundle(bundle_version="vb-1", rules=rules)
    manifest = v2_manifest(validator_bundle_hash=validator_bundle_hash(b))
    result = evaluate(snapshot(failing=("source_id_resolution",)), bundle=b, manifest=manifest)
    assert result.findings[0].severity == severity
    assert result.findings[0].repairable is True


def test_bundle_hash_mismatch():
    changed = tuple(
        ValidatorRuleConfig(
            rule_id=rid,
            severity="critical" if rid == "passage_id_resolution" else "error",
            rule_params_hash=complete_rule_parameter_hash(ENTRIES[rid]), repairable=False,
        )
        for rid in VALIDATOR_RULE_ORDER
    )
    b = ValidatorBundle(bundle_version="vb-1", rules=changed)
    with pytest.raises(ValidatorBundleBindingError) as exc:
        evaluate(snapshot(), bundle=b)  # manifest pins the default reconciled bundle hash
    assert exc.value.binding_kind == "bundle_hash_mismatch"


def test_snapshot_run_mismatch():
    with pytest.raises(SnapshotRunBindingError):
        evaluate(snapshot(run_id="other-run"))


# --- Snapshot invariants ---------------------------------------------------


def test_snapshot_rejects_bad_artifact_hash():
    with pytest.raises(PydanticValidationError):
        ValidationArtifactSnapshot.model_validate({
            "eval_run_id": "run1", "artifact_id": "a", "stage": "capability_extraction",
            "artifact_sha256": "NOTHEX", "parsed_prediction_content_sha256": PSHA,
            "created_at": CREATED_AT, "observations": [
                _passing_observations()[r] for r in VALIDATOR_RULE_ORDER],
            "coverage": full_coverage(),
        })


def test_observation_verdict_field_rejected():
    obs = _passing_observations()
    obs["source_id_resolution"] = {**obs["source_id_resolution"], "passed": True}
    with pytest.raises(PydanticValidationError):
        snapshot(observations=tuple(obs[r] for r in VALIDATOR_RULE_ORDER))


# --- Ordering + determinism + leakage --------------------------------------


def test_finding_order_is_canonical_rule_then_observation_id():
    failing = ("unique_ids_within_scope", "source_id_resolution", "passage_id_resolution")
    result = evaluate(snapshot(failing=failing))
    order = [f.validator for f in result.findings]
    assert order == ["source_id_resolution", "passage_id_resolution", "unique_ids_within_scope"]


def test_entity_id_stamped_when_present():
    result = evaluate(snapshot(failing=("source_id_resolution",),
                               entity_ids={"source_id_resolution": "ENT-1"}))
    assert result.findings[0].entity_id == "ENT-1"


def test_no_customer_outcome_text_leakage():
    result = _single_failing(
        "customer_task_outcome_and_evidence",
        {"is_customer_facing_task": True, "customer_outcome": "SECRET_OUTCOME", "evidence_ids": ()},
    )
    f = result.findings[0]
    blob = " ".join([f.observed_value, f.expected_invariant, f.message, f.evidence])
    assert "SECRET_OUTCOME" not in blob


# --- Purity + result shape -------------------------------------------------


def test_evaluate_touches_no_filesystem(monkeypatch):
    calls = []

    def spy(name, orig):
        def wrapper(*a, **k):
            calls.append(name)
            return orig(*a, **k)
        return wrapper

    monkeypatch.setattr(Path, "read_bytes", spy("read_bytes", Path.read_bytes))
    monkeypatch.setattr(Path, "read_text", spy("read_text", Path.read_text))
    monkeypatch.setattr(Path, "write_bytes", spy("write_bytes", Path.write_bytes))
    monkeypatch.setattr(Path, "mkdir", spy("mkdir", Path.mkdir))
    monkeypatch.setattr(os, "open", spy("os.open", os.open))
    evaluate(snapshot(failing=("source_id_resolution",)))
    assert calls == []


def test_result_has_no_status_or_verdict():
    result = evaluate(snapshot(failing=("source_id_resolution",)))
    fields = set(type(result).model_fields)
    assert "execution_status" not in fields and "gate_verdict" not in fields
    assert fields == {
        "eval_run_id", "artifact_id", "artifact_sha256",
        "validator_bundle_version", "validator_bundle_hash", "findings",
    }


# --- Persistence -----------------------------------------------------------


def test_persist_and_load_roundtrip_full(tmp_path):
    init_run(tmp_path)
    ev = evaluated(tmp_path)
    persisted = persist_validator_findings(ev.findings, eval_root=tmp_path, eval_run_id="run1")
    assert isinstance(persisted, PersistedValidatorFindings)
    assert persisted.artifact_reference == "run1/findings/validator_findings.jsonl"
    loaded = load_validator_findings("run1", eval_root=tmp_path)
    assert isinstance(loaded, LoadedValidatorFindings)
    assert loaded.sha256 == persisted.sha256
    assert [f.model_dump() for f in loaded.findings] == [f.model_dump() for f in ev.findings]


def test_persist_empty_findings(tmp_path):
    init_run(tmp_path)
    persisted = persist_validator_findings((), eval_root=tmp_path, eval_run_id="run1")
    dest = tmp_path / "run1" / "findings" / "validator_findings.jsonl"
    assert dest.read_bytes() == b"" and persisted.sha256 == sha256_bytes(b"")
    assert load_validator_findings("run1", eval_root=tmp_path).findings == ()


def test_persist_rejects_existing_file_collision(tmp_path):
    init_run(tmp_path)
    (tmp_path / "run1" / "findings").write_bytes(b"occupied")
    with pytest.raises(ValidatorFindingsExistError):
        persist_validator_findings((), eval_root=tmp_path, eval_run_id="run1")
    assert (tmp_path / "run1" / "findings").read_bytes() == b"occupied"


def test_persist_rejects_existing_directory(tmp_path):
    init_run(tmp_path)
    (tmp_path / "run1" / "findings").mkdir()
    with pytest.raises(ValidatorFindingsExistError):
        persist_validator_findings((), eval_root=tmp_path, eval_run_id="run1")


def test_persist_rejects_symlink(tmp_path):
    init_run(tmp_path)
    target = tmp_path / "elsewhere"
    target.mkdir()
    (tmp_path / "run1" / "findings").symlink_to(target)
    with pytest.raises(ValidatorFindingsExistError):
        persist_validator_findings((), eval_root=tmp_path, eval_run_id="run1")


def test_persist_rejects_dangling_symlink(tmp_path):
    init_run(tmp_path)
    (tmp_path / "run1" / "findings").symlink_to(tmp_path / "nope")
    with pytest.raises(ValidatorFindingsExistError):
        persist_validator_findings((), eval_root=tmp_path, eval_run_id="run1")


def test_write_failure_after_dir_create_preserves_directory(tmp_path, monkeypatch):
    init_run(tmp_path)
    ev = evaluated(tmp_path)

    def boom(*a, **k):
        raise OSError("synthetic write failure")

    monkeypatch.setattr(val_mod.os, "open", boom)
    with pytest.raises(ValidatorWriteError):
        persist_validator_findings(ev.findings, eval_root=tmp_path, eval_run_id="run1")
    monkeypatch.undo()
    d = tmp_path / "run1" / "findings"
    assert d.is_dir() and list(d.iterdir()) == []
    with pytest.raises(ValidatorFindingsExistError):
        persist_validator_findings(ev.findings, eval_root=tmp_path, eval_run_id="run1")


def test_persist_rejects_run_binding(tmp_path):
    init_run(tmp_path)
    ev = evaluated(tmp_path)
    tampered = ev.findings[0].model_copy(update={"run_id": "other"})
    with pytest.raises(ValidatorFindingRunBindingError):
        persist_validator_findings((tampered,), eval_root=tmp_path, eval_run_id="run1")


def test_persist_rejects_duplicate_finding_id(tmp_path):
    init_run(tmp_path)
    ev = evaluated(tmp_path)
    with pytest.raises(DuplicateValidatorFindingError):
        persist_validator_findings((ev.findings[0], ev.findings[0]), eval_root=tmp_path, eval_run_id="run1")


# --- Loader strictness -----------------------------------------------------


def test_load_missing(tmp_path):
    init_run(tmp_path)
    with pytest.raises(ValidatorArtifactMissingError):
        load_validator_findings("run1", eval_root=tmp_path)


def test_load_rejects_non_utf8(tmp_path):
    init_run(tmp_path)
    write_findings_dir(tmp_path, b"\xff\xfe")
    with pytest.raises(ValidatorDecodeError):
        load_validator_findings("run1", eval_root=tmp_path)


def test_load_rejects_bom(tmp_path):
    init_run(tmp_path)
    write_findings_dir(tmp_path, b"\xef\xbb\xbf" + finding_line(tmp_path))
    with pytest.raises(ValidatorJsonError):
        load_validator_findings("run1", eval_root=tmp_path)


def test_load_rejects_blank_line(tmp_path):
    init_run(tmp_path)
    line = finding_line(tmp_path)
    write_findings_dir(tmp_path, line + b"\n" + line)
    with pytest.raises(ValidatorJsonError):
        load_validator_findings("run1", eval_root=tmp_path)


def test_load_rejects_trailing_data(tmp_path):
    init_run(tmp_path)
    ev = evaluated(tmp_path)
    write_findings_dir(tmp_path, val_mod._canonical_finding_line(ev.findings[0]) + b" x\n")
    with pytest.raises(ValidatorJsonError):
        load_validator_findings("run1", eval_root=tmp_path)


def test_load_rejects_duplicate_keys(tmp_path):
    init_run(tmp_path)
    write_findings_dir(tmp_path, b'{"a":1,"a":2}\n')
    with pytest.raises(ValidatorJsonError) as exc:
        load_validator_findings("run1", eval_root=tmp_path)
    assert exc.value.duplicate_key == "a"


@pytest.mark.parametrize("constant", [b"NaN", b"Infinity", b"-Infinity"])
def test_load_rejects_non_finite(tmp_path, constant):
    init_run(tmp_path)
    write_findings_dir(tmp_path, b'{"x":' + constant + b"}\n")
    with pytest.raises(ValidatorJsonError):
        load_validator_findings("run1", eval_root=tmp_path)


def test_load_rejects_non_object(tmp_path):
    init_run(tmp_path)
    write_findings_dir(tmp_path, b"[1,2]\n")
    with pytest.raises(ValidatorTopLevelTypeError):
        load_validator_findings("run1", eval_root=tmp_path)


def test_load_rejects_model_invalid(tmp_path):
    init_run(tmp_path)
    write_findings_dir(tmp_path, b'{"unexpected":true}\n')
    with pytest.raises(ValidatorModelValidationError):
        load_validator_findings("run1", eval_root=tmp_path)


def test_load_rejects_run_binding(tmp_path):
    init_run(tmp_path)
    ev = evaluated(tmp_path)
    tampered = ev.findings[0].model_copy(update={"run_id": "other"})
    write_findings_dir(tmp_path, val_mod._canonical_finding_line(tampered) + b"\n")
    with pytest.raises(ValidatorFindingRunBindingError):
        load_validator_findings("run1", eval_root=tmp_path)


def test_load_rejects_symlinked_artifact(tmp_path):
    init_run(tmp_path)
    d = tmp_path / "run1" / "findings"
    d.mkdir(parents=True, exist_ok=False)
    target = tmp_path / "outside.jsonl"
    target.write_bytes(b"")
    (d / "validator_findings.jsonl").symlink_to(target)
    with pytest.raises(ValidatorArtifactNotAFileError):
        load_validator_findings("run1", eval_root=tmp_path)


def test_load_rejects_symlinked_run_dir(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    init_run(real, "run1")
    (tmp_path / "run1").symlink_to(real / "run1")
    with pytest.raises(RunArtifactNotAFileError):
        load_validator_findings("run1", eval_root=tmp_path)


def test_repeated_loads_equal_but_distinct(tmp_path):
    init_run(tmp_path)
    ev = evaluated(tmp_path)
    persist_validator_findings(ev.findings, eval_root=tmp_path, eval_run_id="run1")
    a = load_validator_findings("run1", eval_root=tmp_path)
    b = load_validator_findings("run1", eval_root=tmp_path)
    assert a is not b and a.findings[0] is not b.findings[0]
    assert [f.model_dump() for f in a.findings] == [f.model_dump() for f in b.findings]


def test_invalid_eval_root_rejected():
    with pytest.raises(InvalidEvaluationRootError):
        load_validator_findings("run1", eval_root="")


# --- Exports + hygiene -----------------------------------------------------

_PUBLIC = (
    "evaluate_validator_findings", "persist_validator_findings", "load_validator_findings",
    "validator_bundle_hash", "build_validation_artifact_snapshot",
    "ValidatorRuleConfig", "ValidatorBundle", "ValidationArtifactSnapshot",
    "ValidatorRuleCoverage", "ValidatorRuleCoverageReasonCount",
    "ValidatorRuleId", "VALIDATOR_RULE_ORDER", "ValidatorObservation",
    "EvaluatedValidatorFindings", "PersistedValidatorFindings", "LoadedValidatorFindings",
    "EvidenceClassification",
)
_PUBLIC_EXC = (
    "ValidatorError", "ValidatorBundleBindingError", "SnapshotRunBindingError",
    "ValidatorFindingsExistError", "ValidatorArtifactMissingError",
    "ValidatorArtifactNotAFileError", "ValidatorArtifactReadError", "ValidatorDecodeError",
    "ValidatorJsonError", "ValidatorTopLevelTypeError", "ValidatorModelValidationError",
    "DuplicateValidatorFindingError", "ValidatorFindingRunBindingError", "ValidatorWriteError",
    "ValidatorDestinationHashMismatchError",
)


def test_public_symbols_exported():
    for name in _PUBLIC + _PUBLIC_EXC:
        assert name in evaluation_pkg.__all__
        assert getattr(evaluation_pkg, name) is getattr(val_mod, name)


def test_observation_models_exported():
    for name in (
        "OutputJsonSchemaValidityObservation", "RequiredFieldPresenceObservation",
        "SourceIdResolutionObservation", "PassageIdResolutionObservation",
        "EvidenceQuoteContainmentObservation", "PublicationDateCutoffObservation",
        "ProductCapabilityTaskParentResolutionObservation", "UniqueIdsWithinScopeObservation",
        "ProhibitedLegacyFieldsAbsentObservation", "ActiveRecordNonRoadmapEvidenceObservation",
        "CustomerTaskOutcomeAndEvidenceObservation", "RawOutputAndRepairPreservationObservation",
    ):
        assert name in evaluation_pkg.__all__


def test_exception_hierarchy():
    for name in _PUBLIC_EXC:
        cls = getattr(val_mod, name)
        if name == "ValidatorError":
            assert cls.__bases__ == (Exception,)
        else:
            assert issubclass(cls, ValidatorError)


def test_private_helpers_not_exported():
    for name in ("_canonical_finding_line", "_parse_findings_jsonl", "_dispatch_rule",
                 "_finding_identity_bytes", "_build_rule12_validation_observation",
                 "_DuplicateKeyControl"):
        assert name not in evaluation_pkg.__all__
        assert not hasattr(evaluation_pkg, name)


def test_no_path_escape_error_class():
    assert not hasattr(val_mod, "ValidatorPathEscapeError")


def test_finding_contract_hash_unchanged():
    assert model_contract_hash(ValidatorFinding, "validator_finding", "0.1.0") == (
        "96f63fee300d363a662f4f956bacccdca596acfb0f22bf7039aa1335b6d61292"
    )


# --- Correction A: truthful dependency coverage ---------------------------


def _blocked_dependent_snapshot(*, rule1_fails):
    """capability_extraction: Rule 2 blocked_by_dependency, Rule 1 clean or failing."""
    obs = _passing_observations()
    if rule1_fails:
        obs["output_json_schema_validity"] = {
            **obs["output_json_schema_validity"], "parse_succeeded": False, "schema_valid": False,
        }
    del obs["required_field_presence"]  # blocked -> no observation
    ordered = tuple(obs[r] for r in VALIDATOR_RULE_ORDER if r != "required_field_presence")
    coverage = []
    for rid in VALIDATOR_RULE_ORDER:
        if rid == "required_field_presence":
            coverage.append({
                "rule_id": rid, "coverage_state": "blocked_by_dependency", "candidate_count": 1,
                "evaluated_observation_count": 0, "blocked_candidate_count": 1,
                "reason_counts": [{"reason_code": "blocked_output_schema_invalid", "count": 1}],
            })
        else:
            coverage.append({
                "rule_id": rid, "coverage_state": "fully_evaluated", "candidate_count": 1,
                "evaluated_observation_count": 1, "blocked_candidate_count": 0, "reason_counts": [],
            })
    return snapshot(observations=ordered, coverage=coverage)


def test_clean_dependency_block_rejected():
    with pytest.raises(ValidatorBundleBindingError) as exc:
        evaluate(_blocked_dependent_snapshot(rule1_fails=False))
    assert exc.value.binding_kind == "coverage_dependency_not_failing"


def test_failing_dependency_blocks_dependent():
    result = evaluate(_blocked_dependent_snapshot(rule1_fails=True))
    validators = [f.validator for f in result.findings]
    assert "output_json_schema_validity" in validators  # dependency finding retained
    assert "required_field_presence" not in validators  # dependent legitimately omitted


def test_partial_block_requires_failing_dependency():
    # evidence_quote_containment (dep: passage_id_resolution) partial with a clean dependency.
    obs = _passing_observations()
    ordered = tuple(obs[r] for r in VALIDATOR_RULE_ORDER)
    coverage = []
    for rid in VALIDATOR_RULE_ORDER:
        if rid == "evidence_quote_containment":
            coverage.append({
                "rule_id": rid, "coverage_state": "partially_evaluated", "candidate_count": 2,
                "evaluated_observation_count": 1, "blocked_candidate_count": 1,
                "reason_counts": [{"reason_code": "blocked_passage_unresolved", "count": 1}],
            })
        else:
            coverage.append({
                "rule_id": rid, "coverage_state": "fully_evaluated", "candidate_count": 1,
                "evaluated_observation_count": 1, "blocked_candidate_count": 0, "reason_counts": [],
            })
    with pytest.raises(ValidatorBundleBindingError) as exc:
        evaluate(snapshot(observations=ordered, coverage=coverage))
    assert exc.value.binding_kind == "coverage_dependency_not_failing"


def test_fully_evaluated_coverage_unaffected():
    assert evaluate(snapshot()).findings == ()


def _blocked_required_field_snapshot(*, rule1_fails, unrelated_fail=None):
    """Rule 2 (required_field_presence) blocked_by_dependency; its declared
    dependency is Rule 1 (output_json_schema_validity)."""
    obs = _passing_observations()
    if rule1_fails:
        obs["output_json_schema_validity"] = {
            **obs["output_json_schema_validity"], "parse_succeeded": False, "schema_valid": False,
        }
    if unrelated_fail is not None:
        obs[unrelated_fail] = {**obs[unrelated_fail], **_FAILING[unrelated_fail]}
    del obs["required_field_presence"]
    ordered = tuple(obs[r] for r in VALIDATOR_RULE_ORDER if r != "required_field_presence")
    coverage = []
    for rid in VALIDATOR_RULE_ORDER:
        if rid == "required_field_presence":
            coverage.append({
                "rule_id": rid, "coverage_state": "blocked_by_dependency", "candidate_count": 1,
                "evaluated_observation_count": 0, "blocked_candidate_count": 1,
                "reason_counts": [{"reason_code": "blocked_output_schema_invalid", "count": 1}],
            })
        else:
            coverage.append({
                "rule_id": rid, "coverage_state": "fully_evaluated", "candidate_count": 1,
                "evaluated_observation_count": 1, "blocked_candidate_count": 0, "reason_counts": [],
            })
    return snapshot(observations=ordered, coverage=coverage)


def test_unrelated_failure_does_not_justify_block():
    # An unrelated failing rule (source_id_resolution) must not justify blocking
    # required_field_presence, whose actual declared dependency (Rule 1) is clean.
    with pytest.raises(ValidatorBundleBindingError) as exc:
        evaluate(_blocked_required_field_snapshot(rule1_fails=False,
                                                  unrelated_fail="source_id_resolution"))
    assert exc.value.binding_kind == "coverage_dependency_not_failing"


def test_actual_declared_dependency_failure_permits_block():
    result = evaluate(_blocked_required_field_snapshot(rule1_fails=True))
    validators = [f.validator for f in result.findings]
    assert "output_json_schema_validity" in validators
    assert "required_field_presence" not in validators


def test_no_dependency_rule_cannot_claim_blocked():
    # A rule with no declared dependency (Rule 1) must not claim blocked
    # candidates; the structural dependency-absent guard runs before stage/reason
    # governance so the correct binding_kind is reported.
    obs = _passing_observations()
    del obs["output_json_schema_validity"]
    ordered = tuple(obs[r] for r in VALIDATOR_RULE_ORDER if r != "output_json_schema_validity")
    coverage = []
    for rid in VALIDATOR_RULE_ORDER:
        if rid == "output_json_schema_validity":
            coverage.append({
                "rule_id": rid, "coverage_state": "blocked_by_dependency", "candidate_count": 1,
                "evaluated_observation_count": 0, "blocked_candidate_count": 1,
                "reason_counts": [{"reason_code": "blocked_output_schema_invalid", "count": 1}],
            })
        else:
            coverage.append({
                "rule_id": rid, "coverage_state": "fully_evaluated", "candidate_count": 1,
                "evaluated_observation_count": 1, "blocked_candidate_count": 0, "reason_counts": [],
            })
    with pytest.raises(ValidatorBundleBindingError) as exc:
        evaluate(snapshot(observations=ordered, coverage=coverage))
    assert exc.value.binding_kind == "coverage_dependency_absent"


def test_capability_omitting_required_observation_rejected():
    obs = _passing_observations()
    del obs["required_field_presence"]
    ordered = tuple(obs[r] for r in VALIDATOR_RULE_ORDER if r != "required_field_presence")
    # coverage still claims required_field_presence fully_evaluated -> obs count mismatch.
    with pytest.raises(PydanticValidationError):
        snapshot(observations=ordered, coverage=full_coverage())


# --- Correction B: Rule 12 direct provenance safety -----------------------


def _rule12_override(override):
    obs = _passing_observations()
    obs["raw_output_and_repair_preservation"] = {
        **obs["raw_output_and_repair_preservation"], **override,
    }
    return tuple(obs[r] for r in VALIDATOR_RULE_ORDER)


_UNSAFE_REFERENCES = [
    "../outside/raw.json",   # traversal
    "/absolute/raw.json",    # absolute path
    "back\\slash.json",      # backslash
    "nul\x00byte.json",      # NUL
]


@pytest.mark.parametrize("bad", _UNSAFE_REFERENCES)
def test_rule12_unsafe_raw_reference_rejected(bad):
    with pytest.raises(PydanticValidationError):
        snapshot(observations=_rule12_override({"raw_output_reference": bad}))


@pytest.mark.parametrize("bad", _UNSAFE_REFERENCES)
def test_rule12_unsafe_repair_reference_rejected(bad):
    with pytest.raises(PydanticValidationError):
        snapshot(observations=_rule12_override(
            {"repair_applied": True, "repair_record_references": (bad,),
             "repair_record_hashes": ("e" * 64,)}
        ))


def test_rule12_duplicate_repair_references_rejected():
    with pytest.raises(PydanticValidationError):
        snapshot(observations=_rule12_override(
            {"repair_applied": True, "repair_record_references": ("r", "r"),
             "repair_record_hashes": ("e" * 64, "f" * 64)}
        ))


def test_rule12_valid_paired_provenance_accepted():
    snap = snapshot(observations=_rule12_override(
        {"repair_applied": True, "repair_record_references": ("repairs/r1.json", "repairs/r2.json"),
         "repair_record_hashes": ("e" * 64, "f" * 64)}
    ))
    assert evaluate(snap).findings == ()
