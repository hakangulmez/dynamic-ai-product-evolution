"""Slice 12H: semantic assertion evaluators (case-level aggregate)."""

import subprocess
import sys
from pathlib import Path

import pytest

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import semantic_assertions as sa_mod
from dynamic_ai_products.evaluation.assertions import ResolvedAssertionEvaluation
from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.gold import (
    BoundGoldAssertionSet,
    GoldAssertionSet,
    LoadedGoldAssertionSet,
    ResolvedGoldAssertion,
)
from dynamic_ai_products.evaluation.models import EvaluationCase, ValidatorFinding
from dynamic_ai_products.evaluation.prediction_content import (
    LoadedParsedPredictionContent,
    ParsedPredictionContent,
)
from dynamic_ai_products.evaluation.references import CaseResolution
from dynamic_ai_products.evaluation.semantic_assertions import (
    SemanticAssertionEvaluationError,
    SemanticAssertionEvaluationResult,
    build_resolved_assertion_evaluations,
)
from dynamic_ai_products.evaluation.source_snapshot import load_source_passage_snapshot_manifest
from dynamic_ai_products.evaluation.validation_snapshot import (
    LoadedValidationArtifactSnapshotSet,
    build_validation_artifact_snapshot_set,
)
from dynamic_ai_products.evaluation.validators import VALIDATOR_RULE_ORDER, ValidationArtifactSnapshot

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness"

RUN = "synth-run-12h"
STAGE = "capability_extraction"
CASE_ID = "SYNTH-CASE-12H"
ARTIFACT = "art-0001"
PSHA = "d" * 64
H = "a" * 64
CONTRACT_ID = "synth-contract"
CONTRACT_VERSION = "0.1.0"
CONTRACT_HASH = "1" * 64
CREATED = "2026-07-24T00:00:00+00:00"
GOLD_HASH = model_contract_hash(GoldAssertionSet, "gold_assertion_set", "0.1.0")
PARSED_HASH = model_contract_hash(ParsedPredictionContent, "parsed_prediction_content", "0.1.0")
FINDING_HASH = model_contract_hash(ValidatorFinding, "validator_finding", "0.1.0")

SOURCE = load_source_passage_snapshot_manifest(
    "source_snapshots/source_passage_snapshot_manifest.json", eval_root=FX
)

PROTECTED_HASHES = {
    ("validator_finding", "0.1.0"): "96f63fee300d363a662f4f956bacccdca596acfb0f22bf7039aa1335b6d61292",
    ("gold_assertion_set", "0.1.0"): "48bb5f185072ed004aa4fcfda30408ff710406ac42bc5ea611d3f5a1fb118cfe",
    ("axis_taxonomy", "0.1.0"): "d6072c16fe82b9e7e7f1f52db2d5f57fdc079ef473c3e8803b0fde2c3e356df3",
    ("validation_artifact_snapshot_set", "0.1.0"): "51643160bcc7a98b7dd7279c6109d51292d1cd7d3022420271010e3275e6d1a1",
}


# --- Input builders --------------------------------------------------------


def _prov():
    return {
        "gold_origin": "constructed", "verification_status": "verified",
        "verification_method": "construction_review", "annotator_ids": ["annot-1"],
        "reviewer_ids": ["rev-1"], "annotation_timestamps": ["2026-01-15T10:00:00+00:00"],
        "source_packet_hash": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
        "case_version": "v1", "change_reason": "initial",
    }


def _gold_entry(assertion_id, kind, canonical, *, semver="0.1.0", chash=None,
                field_payload=None, evidence_payload=None):
    e = {"case_id": CASE_ID, "assertion_id": assertion_id}
    if semver is not None:
        e["assertion_semantic_version"] = semver
    if chash is not None:
        e["assertion_contract_hash"] = chash
    e["assertion_kind"] = kind
    e["canonical_target_reference"] = canonical
    if field_payload is not None:
        e["field_value_payload"] = field_payload
    if evidence_payload is not None:
        e["evidence_provenance_payload"] = evidence_payload
    e["provenance"] = _prov()
    return e


def _gold_and_bound(entry_dicts, *, version="gold-v1", sha=H, contract_hash=CONTRACT_HASH):
    ordered = sorted(entry_dicts, key=lambda e: (
        e["case_id"], e["assertion_id"], e.get("assertion_semantic_version", ""),
        e.get("assertion_contract_hash", ""), e["canonical_target_reference"],
    ))
    model = GoldAssertionSet.model_validate({
        "contract": {"contract_id": "gold_assertion_set", "contract_version": "0.1.0",
                     "contract_hash": GOLD_HASH},
        "gold_set_version": version, "entries": ordered,
    })
    loaded = LoadedGoldAssertionSet(model=model, version=version, sha256=sha,
                                    artifact_reference="gold.json")
    bound_entries = tuple(
        ResolvedGoldAssertion(
            case_id=e["case_id"], assertion_id=e["assertion_id"],
            assertion_semantic_version=e.get("assertion_semantic_version"),
            assertion_contract_hash=e.get("assertion_contract_hash"),
            assertion_kind=e["assertion_kind"],
            canonical_target_reference=e["canonical_target_reference"],
            contract_id=CONTRACT_ID, contract_version=CONTRACT_VERSION,
            contract_hash=contract_hash,
        )
        for e in ordered
    )
    bound = BoundGoldAssertionSet(gold_set_version=version, sha256=sha, entries=bound_entries)
    return loaded, bound


def _parsed(*, entities=(), field_values=(), evidence=(),
            entity_complete=True, field_complete=True, evidence_complete=True,
            case_id=CASE_ID, stage=STAGE, sha=PSHA):
    content = ParsedPredictionContent.model_validate({
        "contract": {"contract_id": "parsed_prediction_content", "contract_version": "0.1.0",
                     "contract_hash": PARSED_HASH},
        "case_id": case_id, "stage": stage, "prediction_record_id": "pred-1",
        "input_packet_hash": H, "observation_cutoff": "2025-06-30",
        "raw_artifact_reference": "raw.json", "raw_artifact_sha256": "c" * 64,
        "raw_output_preserved": True, "repair_applied": False,
        "repair_record_references": [], "repair_record_hashes": [],
        "entity_collection": {
            "completeness": "complete" if entity_complete else "partial",
            "entities": list(entities),
        },
        "field_value_collection": {
            "completeness": "complete" if field_complete else "partial",
            "field_values": list(field_values),
        },
        "evidence_collection": {
            "completeness": "complete" if evidence_complete else "partial",
            "evidence": list(evidence),
        },
    })
    return LoadedParsedPredictionContent(content=content, sha256=sha, artifact_reference="p.json")


def _assertion(assertion_id, kind, *, semver="0.1.0", chash=None, targets=("T",),
               scoring=("gate-1",)):
    a = {"assertion_id": assertion_id, "kind": kind, "target_references": list(targets),
         "scoring_gate_config_references": list(scoring)}
    if semver is not None:
        a["semantic_version"] = semver
    if chash is not None:
        a["contract_hash"] = chash
    return a


def _assertion_spec(*args, **kwargs):
    return _case([_assertion(*args, **kwargs)]).assertions[0]


def _case(assertion_dicts, *, input_sources=(), input_passages=(), case_id=CASE_ID, stage=STAGE):
    return EvaluationCase.model_validate({
        "case_id": case_id, "stage": stage, "stage_context": {},
        "input_source_ids": list(input_sources), "input_passage_ids": list(input_passages),
        "assertions": assertion_dicts, "failure_tags": [], "notes": "n",
        "created_by": "c", "created_at": CREATED, "guideline_version": "g",
    })


def _resolved_assertion(spec, *, target_contract=None):
    contract = target_contract or (CONTRACT_ID, CONTRACT_VERSION, CONTRACT_HASH)
    return {
        "assertion_id": spec.assertion_id,
        "assertion_semantic_version": spec.semantic_version,
        "assertion_contract_hash": spec.contract_hash,
        "target_references": [
            {"requested_reference_id": t, "canonical_reference_id": t,
             "reference_kind": "target", "contract_id": contract[0],
             "contract_version": contract[1], "contract_hash": contract[2]}
            for t in spec.target_references
        ],
        "scoring_references": [
            {"requested_reference_id": s, "canonical_reference_id": s, "definition_kind": "gate"}
            for s in spec.scoring_gate_config_references
        ],
    }


def _resolution(case=None, *, assertions=None):
    if assertions is None:
        specs = case.assertions if case is not None else ()
        assertions = [_resolved_assertion(spec) for spec in specs]
    return CaseResolution.model_validate({
        "case_id": case.case_id if case is not None else CASE_ID,
        "target_registry_version": "reg-v1", "target_registry_sha256": H,
        "scoring_config_version": "sc-v1", "scoring_config_sha256": H,
        "assertions": assertions,
    })


def _passing_obs(psha=PSHA):
    return [
        {"rule_id": "output_json_schema_validity", "observation_id": "o1", "parse_succeeded": True,
         "schema_valid": True, "schema_reference": "s.json", "validation_errors": []},
        {"rule_id": "required_field_presence", "observation_id": "o2", "required_fields": ["a"],
         "present_fields": ["a"]},
        {"rule_id": "source_id_resolution", "observation_id": "o3", "referenced_source_ids": ["s1"],
         "available_source_ids": ["s1"]},
        {"rule_id": "passage_id_resolution", "observation_id": "o4", "referenced_passage_ids": ["p1"],
         "available_passage_ids": ["p1"]},
        {"rule_id": "evidence_quote_containment", "observation_id": "o5", "quote": "a",
         "passage_text": "abc", "passage_id": "p1"},
        {"rule_id": "publication_date_cutoff", "observation_id": "o6", "publication_date": "2020-01-01",
         "observation_cutoff_date": "2020-06-01", "source_id": "s1"},
        {"rule_id": "product_capability_task_parent_resolution", "observation_id": "o7",
         "child_id": "c1", "parent_id": "pp", "available_parent_ids": ["pp"]},
        {"rule_id": "unique_ids_within_scope", "observation_id": "o8", "scope_id": "sc",
         "record_ids": ["a", "b"]},
        {"rule_id": "prohibited_legacy_fields_absent", "observation_id": "o9",
         "present_field_names": ["x"], "prohibited_field_names": ["legacy"]},
        {"rule_id": "active_record_non_roadmap_evidence", "observation_id": "o10", "active": True,
         "evidence": [{"evidence_id": "e1", "is_future_roadmap": False}]},
        {"rule_id": "customer_task_outcome_and_evidence", "observation_id": "o11",
         "is_customer_facing_task": True, "customer_outcome": "did x", "evidence_ids": ["e1"]},
        {"rule_id": "raw_output_and_repair_preservation", "observation_id": "o12",
         "raw_output_reference": "raw.json", "raw_artifact_sha256": "e" * 64,
         "raw_output_preserved": True, "repair_applied": False, "repair_record_references": [],
         "repair_record_hashes": [], "parsed_content_sha256": psha},
    ]


def _snapshot(*, blocked_rule=None, psha=PSHA):
    obs = _passing_obs(psha)
    coverage = [{"rule_id": r, "coverage_state": "fully_evaluated", "candidate_count": 1,
                 "evaluated_observation_count": 1, "blocked_candidate_count": 0, "reason_counts": []}
                for r in VALIDATOR_RULE_ORDER]
    if blocked_rule is not None:
        obs = [o for o in obs if o["rule_id"] != blocked_rule]
        for c in coverage:
            if c["rule_id"] == blocked_rule:
                c.update({"coverage_state": "blocked_by_dependency", "candidate_count": 1,
                          "evaluated_observation_count": 0, "blocked_candidate_count": 1,
                          "reason_counts": [{"reason_code": "blocked_output_schema_invalid",
                                             "count": 1}]})
    return ValidationArtifactSnapshot.model_validate({
        "eval_run_id": RUN, "artifact_id": ARTIFACT, "stage": STAGE, "artifact_sha256": H,
        "parsed_prediction_content_sha256": psha, "created_at": CREATED, "case_id": CASE_ID,
        "observations": obs, "coverage": coverage,
    })


def _validation(*, snapshots=None, stage=STAGE):
    if snapshots is None:
        snapshots = (_snapshot(),)
    model = build_validation_artifact_snapshot_set(
        snapshot_set_version="vset-1", eval_run_id=RUN, evaluation_stage=stage, snapshots=snapshots)
    return LoadedValidationArtifactSnapshotSet(model=model, version="vset-1", sha256=H,
                                               artifact_reference="v.json")


def _finding(validator, *, artifact_id=ARTIFACT, case_id=CASE_ID, finding_id="f" * 64,
             run_id=RUN):
    payload = {
        "contract": {"contract_id": "validator_finding", "contract_version": "0.1.0",
                     "contract_hash": FINDING_HASH},
        "finding_id": finding_id, "validator": validator, "validator_bundle_version": "vb-1",
        "validator_bundle_hash": H, "rule_params_hash": H, "severity": "error", "run_id": run_id,
        "artifact_id": artifact_id, "observed_value": "x", "expected_invariant": "y",
        "message": "m", "evidence": "e", "repairable": False, "created_at": CREATED,
    }
    if case_id is not None:
        payload["case_id"] = case_id
    return ValidatorFinding.model_validate(payload)


def _findings(findings=()):
    from dynamic_ai_products.evaluation.validators import LoadedValidatorFindings
    return LoadedValidatorFindings(
        eval_run_id=RUN, artifact_reference=f"{RUN}/findings/validator_findings.jsonl",
        sha256=H, findings=tuple(findings))


def _build(case, gold, bound, parsed, *, validation=None, findings=None, source=SOURCE,
           resolution=None):
    return build_resolved_assertion_evaluations(
        case=case, resolution=resolution if resolution is not None else _resolution(case),
        parsed_content=parsed, gold=gold, bound_gold=bound,
        source_snapshot=source, validation_snapshots=validation or _validation(),
        validator_findings=findings or _findings(),
    )


def _outcomes(result):
    return {e.assertion_id: e.outcome for e in result.evaluations}


# --- Phase B: entity kinds -------------------------------------------------


def test_expected_entity_satisfied_and_unsatisfied():
    gold, bound = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1",))])
    present = _parsed(entities=[{"entity_kind": "product", "entity_ref": "E1"}])
    absent = _parsed(entities=[{"entity_kind": "product", "entity_ref": "OTHER"}])
    assert _outcomes(_build(case, gold, bound, present))["A1"] == "satisfied"
    assert _outcomes(_build(case, gold, bound, absent))["A1"] == "unsatisfied"


def test_expected_entity_multi_target_aggregation():
    gold, bound = _gold_and_bound([
        _gold_entry("A1", "expected_entity", "E1"), _gold_entry("A1", "expected_entity", "E2")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1", "E2"))])
    both = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"},
                             {"entity_kind": "k", "entity_ref": "E2"}])
    one = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"}])
    assert _outcomes(_build(case, gold, bound, both))["A1"] == "satisfied"
    assert _outcomes(_build(case, gold, bound, one))["A1"] == "unsatisfied"


def test_forbidden_entity_multi_target():
    gold, bound = _gold_and_bound([
        _gold_entry("A1", "forbidden_entity", "F1"), _gold_entry("A1", "forbidden_entity", "F2")])
    case = _case([_assertion("A1", "forbidden_entity", targets=("F1", "F2"))])
    clean = _parsed(entities=[{"entity_kind": "k", "entity_ref": "OK"}])
    dirty = _parsed(entities=[{"entity_kind": "k", "entity_ref": "F2"}])
    assert _outcomes(_build(case, gold, bound, clean))["A1"] == "satisfied"
    assert _outcomes(_build(case, gold, bound, dirty))["A1"] == "unsatisfied"


def test_entity_incomplete_collection_indeterminate():
    gold, bound = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1",))])
    parsed = _parsed(entities=[], entity_complete=False)
    assert _outcomes(_build(case, gold, bound, parsed))["A1"] == "indeterminate"


# --- Phase B: field_value --------------------------------------------------


def _fv(operator, value_type, expected):
    return {"field_path": "revenue", "operator": operator, "value_type": value_type,
            "expected_values": list(expected)}


def _field_case(operator, value_type, expected):
    gold, bound = _gold_and_bound([
        _gold_entry("A1", "field_value", "T", field_payload=_fv(operator, value_type, expected))])
    case = _case([_assertion("A1", "field_value")])
    return gold, bound, case


def _fv_parsed(actual):
    return _parsed(entities=[{"entity_kind": "k", "entity_ref": "T"}],
                   field_values=[{"entity_ref": "T", "field_name": "revenue",
                                  "field_value": actual}])


@pytest.mark.parametrize("op,vt,exp,actual,expected_outcome", [
    ("equals", "string", ["100"], "100", "satisfied"),
    ("equals", "string", ["100"], "101", "unsatisfied"),
    ("not_equals", "string", ["100"], "101", "satisfied"),
    ("not_equals", "string", ["100"], "100", "unsatisfied"),
    ("in_set", "integer", [1, 2, 3], "2", "satisfied"),
    ("not_in_set", "integer", [1, 2], "9", "satisfied"),
    ("gte", "integer", [10], "10", "satisfied"),
    ("gt", "number", [1.5], "2.0", "satisfied"),
    ("lte", "date", ["2025-01-01"], "2024-12-31", "satisfied"),
    ("lt", "date", ["2025-12-31"], "2025-01-01", "satisfied"),
    ("equals", "boolean", [True], "true", "satisfied"),
    ("equals", "boolean", [True], "false", "unsatisfied"),
])
def test_field_value_operators(op, vt, exp, actual, expected_outcome):
    gold, bound, case = _field_case(op, vt, exp)
    assert _outcomes(_build(case, gold, bound, _fv_parsed(actual)))["A1"] == expected_outcome


def test_field_value_malformed_actual_unsatisfied():
    gold, bound, case = _field_case("equals", "integer", [1])
    assert _outcomes(_build(case, gold, bound, _fv_parsed("notanint")))["A1"] == "unsatisfied"


def test_field_value_missing_field_unsatisfied():
    gold, bound, case = _field_case("equals", "string", ["100"])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "OTHER"}],
                     field_values=[{"entity_ref": "OTHER", "field_name": "revenue",
                                    "field_value": "100"}])
    assert _outcomes(_build(case, gold, bound, parsed))["A1"] == "unsatisfied"


def test_field_value_incomplete_collection_indeterminate():
    gold, bound, case = _field_case("equals", "string", ["100"])
    parsed = _parsed(field_values=[], field_complete=False)
    assert _outcomes(_build(case, gold, bound, parsed))["A1"] == "indeterminate"


# --- Phase B: evidence_provenance -----------------------------------------


def _ev_payload(mode="exact_passage", passage="synth-passage-0003"):
    p = {"expected_source_id": "synth-source-0002", "expected_publication_date": "2025-12-31",
         "match_mode": mode}
    if mode == "exact_passage":
        p["expected_passage_id"] = passage
    return p


def _ev_case(mode="exact_passage"):
    gold, bound = _gold_and_bound([
        _gold_entry("A1", "evidence_provenance", "T", evidence_payload=_ev_payload(mode))])
    return gold, bound, _case([_assertion("A1", "evidence_provenance")],
                              input_sources=("synth-source-0002",),
                              input_passages=("synth-passage-0003",))


def _ev_parsed(source, passage, quote):
    return _parsed(entities=[{"entity_kind": "k", "entity_ref": "T"}],
                   evidence=[{"entity_ref": "T", "source_id": source, "passage_id": passage,
                              "quote": quote}])


def test_evidence_exact_passage_satisfied():
    gold, bound, case = _ev_case("exact_passage")
    parsed = _ev_parsed("synth-source-0002", "synth-passage-0003", "alpha")
    assert _outcomes(_build(case, gold, bound, parsed))["A1"] == "satisfied"


def test_evidence_same_source_document_satisfied():
    gold, bound = _gold_and_bound([
        _gold_entry("A1", "evidence_provenance", "T",
                    evidence_payload=_ev_payload("same_source_document"))])
    case = _case([_assertion("A1", "evidence_provenance")],
                 input_sources=("synth-source-0002",), input_passages=("synth-passage-0002",))
    parsed = _ev_parsed("synth-source-0002", "synth-passage-0002", "synthetic")
    assert _outcomes(_build(case, gold, bound, parsed))["A1"] == "satisfied"


@pytest.mark.parametrize("source,passage,quote", [
    ("synth-source-0999", "synth-passage-0003", "alpha"),   # unresolved/mismatched source
    ("synth-source-0002", "synth-passage-9999", "alpha"),   # unresolved passage
    ("synth-source-0002", "synth-passage-0003", "zzz"),     # non-contained quote
    ("synth-source-0002", "synth-passage-0003", "  "),      # blank quote
])
def test_evidence_defects_unsatisfied_without_invalidation(source, passage, quote):
    gold, bound, case = _ev_case("exact_passage")
    result = _build(case, gold, bound, _ev_parsed(source, passage, quote))
    assert _outcomes(result)["A1"] == "unsatisfied"
    assert result.input_validity_issues == ()  # no Phase-A invalidation


def test_evidence_publication_date_mismatch_unsatisfied():
    gold, bound = _gold_and_bound([
        _gold_entry("A1", "evidence_provenance", "T", evidence_payload={
            "expected_source_id": "synth-source-0002", "expected_passage_id": "synth-passage-0003",
            "expected_publication_date": "2020-01-01", "match_mode": "exact_passage"})])
    case = _case([_assertion("A1", "evidence_provenance")],
                 input_sources=("synth-source-0002",), input_passages=("synth-passage-0003",))
    parsed = _ev_parsed("synth-source-0002", "synth-passage-0003", "alpha")
    result = _build(case, gold, bound, parsed)
    assert _outcomes(result)["A1"] == "unsatisfied"
    assert result.input_validity_issues == ()


# --- Phase C: deterministic_validation ------------------------------------


def _det_case():
    return _case([_assertion("D1", "deterministic_validation", targets=("R",))])


def test_deterministic_satisfied():
    gold, bound = _gold_and_bound([_gold_entry("X", "expected_entity", "E1")])  # unrelated gold
    result = _build(_det_case(), gold, bound, _parsed())
    assert _outcomes(result)["D1"] == "satisfied"
    assert result.input_validity_issues == ()


def test_deterministic_finding_unsatisfied():
    gold, bound = _gold_and_bound([_gold_entry("X", "expected_entity", "E1")])
    findings = _findings([_finding("required_field_presence")])
    result = _build(_det_case(), gold, bound, _parsed(), findings=findings)
    assert _outcomes(result)["D1"] == "unsatisfied"


def test_deterministic_blocked_indeterminate():
    gold, bound = _gold_and_bound([_gold_entry("X", "expected_entity", "E1")])
    validation = _validation(snapshots=(_snapshot(blocked_rule="required_field_presence"),))
    result = _build(_det_case(), gold, bound, _parsed(), validation=validation)
    assert _outcomes(result)["D1"] == "indeterminate"


def test_deterministic_requires_no_gold():
    result = _build(_det_case(), *_gold_and_bound([_gold_entry('UNREL', 'expected_entity', 'E1')]), _parsed())
    assert _outcomes(result)["D1"] == "satisfied"
    assert result.not_evaluated_assertion_ids == ()


def test_deterministic_missing_binding_is_phase_a():
    gold, bound = _gold_and_bound([_gold_entry('UNREL', 'expected_entity', 'E1')])
    findings = _findings([_finding("required_field_presence", artifact_id="not-in-set")])
    result = _build(_det_case(), gold, bound, _parsed(), findings=findings)
    assert result.evaluations == ()
    codes = {i.issue_code for i in result.input_validity_issues}
    assert "finding_artifact_absent" in codes
    assert result.not_evaluated_assertion_ids == ("D1",)


# --- Phase A: bindings + no fabricated outcomes ---------------------------


def test_global_binding_defect_marks_all_not_evaluated():
    gold, bound = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")])
    case = _case([_assertion("A1", "expected_entity"), _assertion("A2", "expected_entity")])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"}], stage="task_extraction")
    result = _build(case, gold, bound, parsed)
    assert result.evaluations == ()
    assert result.not_evaluated_assertion_ids == ("A1", "A2")
    assert "parsed_content_stage_mismatch" in {i.issue_code for i in result.input_validity_issues}


def test_per_assertion_gold_missing_is_not_evaluated():
    gold, bound = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1",)),
                  _assertion("A2", "expected_entity")])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"}])
    result = _build(case, gold, bound, parsed)
    assert _outcomes(result) == {"A1": "satisfied"}
    assert result.not_evaluated_assertion_ids == ("A2",)
    issue = next(i for i in result.input_validity_issues if i.assertion_id == "A2")
    assert issue.issue_code == "gold_entry_missing"


def test_gold_kind_mismatch_and_identity_mismatch():
    gold, bound = _gold_and_bound([_gold_entry("A1", "forbidden_entity", "E1")])
    case = _case([_assertion("A1", "expected_entity")])
    result = _build(case, gold, bound, _parsed(entities=[]))
    assert result.not_evaluated_assertion_ids == ("A1",)
    assert {i.issue_code for i in result.input_validity_issues} == {"gold_kind_mismatch"}


def test_gold_binding_version_mismatch_is_phase_a():
    gold, _ = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")], version="gold-v1")
    _, bound = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")], version="gold-vOTHER")
    case = _case([_assertion("A1", "expected_entity")])
    result = _build(case, gold, bound, _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"}]))
    assert result.evaluations == ()
    assert "gold_binding_mismatch" in {i.issue_code for i in result.input_validity_issues}


def test_issue_order_is_deterministic():
    gold, bound = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")])
    case = _case([_assertion("A1", "expected_entity")])
    parsed = _parsed(entities=[], stage="task_extraction", case_id="OTHER")
    result = _build(case, gold, bound, parsed)
    codes = [i.issue_code for i in result.input_validity_issues]
    assert codes == sorted(codes)


# --- Phase A: CaseResolution reconciliation -------------------------------


def test_resolution_missing_all_assertions_leaves_them_unevaluated():
    gold, bound = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1",))])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"}])
    result = _build(case, gold, bound, parsed, resolution=_resolution(assertions=[]))
    assert result.evaluations == ()
    assert result.not_evaluated_assertion_ids == ("A1",)
    issue = next(i for i in result.input_validity_issues if i.assertion_id == "A1")
    assert issue.issue_code == "resolution_assertion_missing" and issue.scope == "assertion"


def test_resolution_missing_one_assertion_only_affects_it():
    gold, bound = _gold_and_bound([
        _gold_entry("A1", "expected_entity", "E1"), _gold_entry("A2", "expected_entity", "E2")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1",)),
                  _assertion("A2", "expected_entity", targets=("E2",))])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"},
                               {"entity_kind": "k", "entity_ref": "E2"}])
    only_a1 = [_resolved_assertion(case.assertions[0])]
    result = _build(case, gold, bound, parsed, resolution=_resolution(assertions=only_a1))
    assert _outcomes(result) == {"A1": "satisfied"}
    assert result.not_evaluated_assertion_ids == ("A2",)
    assert {i.issue_code for i in result.input_validity_issues} == {"resolution_assertion_missing"}


def test_resolution_duplicate_assertion_is_global():
    gold, bound = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1",))])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"}])
    dup = [_resolved_assertion(case.assertions[0]), _resolved_assertion(case.assertions[0])]
    result = _build(case, gold, bound, parsed, resolution=_resolution(assertions=dup))
    assert result.evaluations == ()
    assert result.not_evaluated_assertion_ids == ("A1",)
    assert "resolution_duplicate_assertion" in {i.issue_code for i in result.input_validity_issues}


def test_resolution_extra_assertion_is_global():
    gold, bound = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1",))])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"}])
    extra = _resolved_assertion(_assertion_spec("GHOST", "expected_entity", targets=("E1",)))
    res = _resolution(assertions=[_resolved_assertion(case.assertions[0]), extra])
    result = _build(case, gold, bound, parsed, resolution=res)
    assert result.evaluations == ()
    assert "resolution_extra_assertion" in {i.issue_code for i in result.input_validity_issues}


def test_resolution_identity_mismatch_leaves_assertion_unevaluated():
    gold, bound = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1",))])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"}])
    bad = _resolved_assertion(case.assertions[0])
    bad["assertion_contract_hash"] = "wrong-hash"
    result = _build(case, gold, bound, parsed, resolution=_resolution(assertions=[bad]))
    assert result.evaluations == ()
    assert result.not_evaluated_assertion_ids == ("A1",)
    assert {i.issue_code for i in result.input_validity_issues} == {"resolution_identity_mismatch"}


def test_resolution_target_mismatch_leaves_assertion_unevaluated():
    gold, bound = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1",))])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"}])
    bad = _resolved_assertion(case.assertions[0])
    bad["target_references"][0]["requested_reference_id"] = "DIFFERENT"
    result = _build(case, gold, bound, parsed, resolution=_resolution(assertions=[bad]))
    assert {i.issue_code for i in result.input_validity_issues} == {"resolution_target_mismatch"}


def test_bound_gold_contract_identity_must_match_resolution():
    # A fabricated bound set whose version/SHA/target strings match but whose
    # contract identity differs must be rejected, not silently accepted.
    gold, bound = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")],
                                  contract_hash="9" * 64)
    case = _case([_assertion("A1", "expected_entity", targets=("E1",))])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"}])
    result = _build(case, gold, bound, parsed)  # resolution uses the true CONTRACT_HASH
    assert result.evaluations == ()
    assert result.not_evaluated_assertion_ids == ("A1",)
    assert {i.issue_code for i in result.input_validity_issues} == {
        "gold_resolution_contract_mismatch"}


# --- Phase A: reference sequence identity (order + multiplicity) -----------


def test_resolution_target_sequence_dropped_repeat_is_mismatch():
    gold, bound = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1", "E1"))])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"}])
    bad = _resolved_assertion(case.assertions[0])
    bad["target_references"] = bad["target_references"][:1]  # ("E1","E1") -> ("E1",)
    result = _build(case, gold, bound, parsed, resolution=_resolution(assertions=[bad]))
    assert result.evaluations == ()
    assert {i.issue_code for i in result.input_validity_issues} == {"resolution_target_mismatch"}


def test_resolution_target_sequence_reorder_is_mismatch():
    gold, bound = _gold_and_bound([
        _gold_entry("A1", "expected_entity", "E1"), _gold_entry("A1", "expected_entity", "E2")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1", "E2"))])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"},
                               {"entity_kind": "k", "entity_ref": "E2"}])
    bad = _resolved_assertion(case.assertions[0])
    bad["target_references"] = list(reversed(bad["target_references"]))  # same members, reordered
    result = _build(case, gold, bound, parsed, resolution=_resolution(assertions=[bad]))
    assert result.evaluations == ()
    assert {i.issue_code for i in result.input_validity_issues} == {"resolution_target_mismatch"}


def test_resolution_scoring_sequence_dropped_repeat_is_mismatch():
    gold, bound = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1",), scoring=("g1", "g1"))])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"}])
    bad = _resolved_assertion(case.assertions[0])
    bad["scoring_references"] = bad["scoring_references"][:1]  # ("g1","g1") -> ("g1",)
    result = _build(case, gold, bound, parsed, resolution=_resolution(assertions=[bad]))
    assert result.evaluations == ()
    assert {i.issue_code for i in result.input_validity_issues} == {"resolution_scoring_mismatch"}


def test_resolution_scoring_sequence_reorder_is_mismatch():
    gold, bound = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1",), scoring=("g1", "g2"))])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"}])
    bad = _resolved_assertion(case.assertions[0])
    bad["scoring_references"] = list(reversed(bad["scoring_references"]))  # reordered
    result = _build(case, gold, bound, parsed, resolution=_resolution(assertions=[bad]))
    assert result.evaluations == ()
    assert {i.issue_code for i in result.input_validity_issues} == {"resolution_scoring_mismatch"}


# --- Phase A: duplicate case assertion IDs --------------------------------


def test_case_duplicate_assertion_id_is_globally_invalid():
    # The committed model permits duplicate assertion_id; semantic evaluation
    # must fail closed (as assertions.py does), producing no completed evaluations.
    gold, bound = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1",)),
                  _assertion("A1", "expected_entity", targets=("E1",))])
    assert [a.assertion_id for a in case.assertions] == ["A1", "A1"]  # the model allows it
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"}])
    res = _resolution(assertions=[_resolved_assertion(case.assertions[0])])  # one coherent A1
    result = _build(case, gold, bound, parsed, resolution=res)
    assert result.evaluations == ()
    assert "case_duplicate_assertion_id" in {i.issue_code for i in result.input_validity_issues}
    assert result.not_evaluated_assertion_ids == ("A1",)


# --- Phase A: conflicting repeated resolved-reference definitions ----------


def test_resolution_target_definition_conflict_is_assertion_scoped():
    gold, bound = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1", "E1"))])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"}])
    bad = _resolved_assertion(case.assertions[0])
    # Same requested "E1" twice, but the second resolves differently.
    bad["target_references"][1]["canonical_reference_id"] = "OTHER"
    bad["target_references"][1]["contract_hash"] = "7" * 64
    result = _build(case, gold, bound, parsed, resolution=_resolution(assertions=[bad]))
    assert result.evaluations == ()
    assert {i.issue_code for i in result.input_validity_issues} == {
        "resolution_target_definition_conflict"}


def test_resolution_scoring_definition_conflict_is_assertion_scoped():
    gold, bound = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1",), scoring=("g1", "g1"))])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"}])
    bad = _resolved_assertion(case.assertions[0])
    # Same requested "g1" twice, but the second resolves to a different kind.
    bad["scoring_references"][1]["definition_kind"] = "diagnostic"
    result = _build(case, gold, bound, parsed, resolution=_resolution(assertions=[bad]))
    assert result.evaluations == ()
    assert {i.issue_code for i in result.input_validity_issues} == {
        "resolution_scoring_definition_conflict"}


def test_resolution_duplicate_reference_identical_definition_is_valid():
    # Repeated requested IDs whose resolved definitions are identical are valid.
    gold, bound = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1", "E1"), scoring=("g1", "g1"))])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"}])
    result = _build(case, gold, bound, parsed)  # default resolution: identical repeated defs
    assert _outcomes(result)["A1"] == "satisfied"
    assert result.input_validity_issues == ()


# --- Phase A: complete bound-gold identity reconciliation -----------------


def _bound(*entries, version="gold-v1", sha=H):
    return BoundGoldAssertionSet(gold_set_version=version, sha256=sha, entries=tuple(entries))


def _bound_entry(assertion_id, kind, canonical, *, case_id=CASE_ID, semver="0.1.0", chash=None,
                 contract_hash=CONTRACT_HASH):
    return ResolvedGoldAssertion(
        case_id=case_id, assertion_id=assertion_id, assertion_semantic_version=semver,
        assertion_contract_hash=chash, assertion_kind=kind, canonical_target_reference=canonical,
        contract_id=CONTRACT_ID, contract_version=CONTRACT_VERSION, contract_hash=contract_hash)


def _expected_e1_case_parsed():
    gold, _ = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1",))])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"}])
    return gold, case, parsed


def test_bound_gold_kind_differs_is_rejected():
    gold, case, parsed = _expected_e1_case_parsed()
    bound = _bound(_bound_entry("A1", "forbidden_entity", "E1"))  # loaded gold is expected_entity
    result = _build(case, gold, bound, parsed)
    assert result.evaluations == ()
    assert {i.issue_code for i in result.input_validity_issues} == {"gold_bound_mismatch"}


def test_bound_gold_semantic_version_differs_is_rejected():
    gold, case, parsed = _expected_e1_case_parsed()
    bound = _bound(_bound_entry("A1", "expected_entity", "E1", semver="9.9.9"))
    result = _build(case, gold, bound, parsed)
    assert result.evaluations == ()
    assert {i.issue_code for i in result.input_validity_issues} == {"gold_bound_mismatch"}


def test_bound_gold_contract_hash_identity_differs_is_rejected():
    gold, case, parsed = _expected_e1_case_parsed()
    bound = _bound(_bound_entry("A1", "expected_entity", "E1", chash="different-id"))
    result = _build(case, gold, bound, parsed)
    assert result.evaluations == ()
    assert {i.issue_code for i in result.input_validity_issues} == {"gold_bound_mismatch"}


def test_bound_gold_case_identity_differs_though_target_coincides():
    gold, case, parsed = _expected_e1_case_parsed()
    # Same target string "E1", but the bound entry is bound to a different case.
    bound = _bound(_bound_entry("A1", "expected_entity", "E1", case_id="OTHER-CASE"))
    result = _build(case, gold, bound, parsed)
    assert result.evaluations == ()
    assert {i.issue_code for i in result.input_validity_issues} == {"gold_bound_mismatch"}


def test_bound_gold_duplicate_entry_is_rejected():
    gold, case, parsed = _expected_e1_case_parsed()
    bound = _bound(_bound_entry("A1", "expected_entity", "E1"),
                   _bound_entry("A1", "expected_entity", "E1"))  # duplicate of the single gold entry
    result = _build(case, gold, bound, parsed)
    assert result.evaluations == ()
    assert {i.issue_code for i in result.input_validity_issues} == {"gold_bound_mismatch"}


def test_bound_gold_missing_entry_is_rejected():
    gold, _ = _gold_and_bound([
        _gold_entry("A1", "expected_entity", "E1"), _gold_entry("A1", "expected_entity", "E2")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1", "E2"))])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"},
                               {"entity_kind": "k", "entity_ref": "E2"}])
    bound = _bound(_bound_entry("A1", "expected_entity", "E1"))  # E2 entry missing
    result = _build(case, gold, bound, parsed)
    assert result.evaluations == ()
    assert {i.issue_code for i in result.input_validity_issues} == {"gold_bound_mismatch"}


# --- Phase A: genuinely aggregate (global + assertion together) -----------


def test_global_and_assertion_issues_reported_together():
    # Independent global defect (parsed stage mismatch) AND an assertion-scoped
    # gold defect (A2 has no gold) are both reported in one deterministic order.
    gold, bound = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1",)),
                  _assertion("A2", "expected_entity", targets=("E2",))])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"}], stage="task_extraction")
    result = _build(case, gold, bound, parsed)
    assert result.evaluations == ()  # a global defect invalidates every assertion
    pairs = {(i.issue_code, i.scope, i.assertion_id) for i in result.input_validity_issues}
    # BOTH the global stage defect AND the assertion-scoped missing-gold defect.
    assert ("parsed_content_stage_mismatch", "global", None) in pairs
    assert ("gold_entry_missing", "assertion", "A2") in pairs
    assert result.input_validity_issues == tuple(
        sorted(result.input_validity_issues,
               key=lambda i: (i.issue_code, i.assertion_id or "")))
    assert result.not_evaluated_assertion_ids == ("A1", "A2")


# --- Phase C: validation-snapshot / finding consistency -------------------


def test_case_snapshot_parsed_content_mismatch_is_phase_a():
    gold, bound = _gold_and_bound([_gold_entry("X", "expected_entity", "E1")])
    # An internally consistent snapshot that binds a DIFFERENT parsed prediction
    # than the one under evaluation must not contribute coverage.
    validation = _validation(snapshots=(_snapshot(psha="b" * 64),))
    result = _build(_det_case(), gold, bound, _parsed(sha=PSHA), validation=validation)
    assert result.evaluations == ()
    assert "case_snapshot_parsed_content_mismatch" in {
        i.issue_code for i in result.input_validity_issues}


def test_finding_for_blocked_coverage_is_inconsistent():
    gold, bound = _gold_and_bound([_gold_entry("X", "expected_entity", "E1")])
    validation = _validation(snapshots=(_snapshot(blocked_rule="required_field_presence"),))
    findings = _findings([_finding("required_field_presence")])
    result = _build(_det_case(), gold, bound, _parsed(), validation=validation, findings=findings)
    assert result.evaluations == ()
    assert "coverage_finding_inconsistent" in {i.issue_code for i in result.input_validity_issues}


def test_finding_count_cannot_exceed_evaluated_observations():
    gold, bound = _gold_and_bound([_gold_entry("X", "expected_entity", "E1")])
    # Two findings for a rule whose snapshot evaluated only one observation.
    findings = _findings([_finding("required_field_presence", finding_id="a" * 63 + "1"),
                          _finding("required_field_presence", finding_id="a" * 63 + "2")])
    result = _build(_det_case(), gold, bound, _parsed(), findings=findings)
    assert result.evaluations == ()
    assert "finding_count_exceeds_evaluated" in {
        i.issue_code for i in result.input_validity_issues}


def test_finding_inner_run_id_mismatch_is_phase_a():
    gold, bound = _gold_and_bound([_gold_entry("X", "expected_entity", "E1")])
    # Wrapper eval_run_id is RUN, but the finding's own run_id disagrees.
    findings = _findings([_finding("required_field_presence", run_id="synth-run-OTHER")])
    result = _build(_det_case(), gold, bound, _parsed(), findings=findings)
    assert result.evaluations == ()
    assert "finding_run_id_mismatch" in {i.issue_code for i in result.input_validity_issues}


def test_finding_missing_case_id_on_case_bound_snapshot_is_phase_a():
    gold, bound = _gold_and_bound([_gold_entry("X", "expected_entity", "E1")])
    # The snapshot is case-bound; a null finding.case_id is inconsistent with it.
    findings = _findings([_finding("required_field_presence", case_id=None)])
    result = _build(_det_case(), gold, bound, _parsed(), findings=findings)
    assert result.evaluations == ()
    assert "finding_case_id_inconsistent" in {i.issue_code for i in result.input_validity_issues}


def test_finding_wrong_non_null_case_id_is_phase_a():
    gold, bound = _gold_and_bound([_gold_entry("X", "expected_entity", "E1")])
    findings = _findings([_finding("required_field_presence", case_id="OTHER-CASE")])
    result = _build(_det_case(), gold, bound, _parsed(), findings=findings)
    assert result.evaluations == ()
    assert "finding_case_id_inconsistent" in {i.issue_code for i in result.input_validity_issues}


def test_coherent_finding_makes_deterministic_unsatisfied():
    # A fully coherent finding (correct run_id, artifact, case_id) still drives
    # the case-level deterministic assertion to unsatisfied — no Phase-A issue.
    gold, bound = _gold_and_bound([_gold_entry("X", "expected_entity", "E1")])
    findings = _findings([_finding("required_field_presence")])
    result = _build(_det_case(), gold, bound, _parsed(), findings=findings)
    assert result.input_validity_issues == ()
    assert _outcomes(result)["D1"] == "unsatisfied"


# --- Phase B: numeric precision + evidence packet boundary ----------------


def test_field_value_number_precision_beyond_float():
    # 2**53 vs 2**53 + 1: distinct integers that a binary float cannot separate.
    gold, bound, case = _field_case("equals", "number", [9007199254740992])
    parsed = _fv_parsed("9007199254740993")
    assert _outcomes(_build(case, gold, bound, parsed))["A1"] == "unsatisfied"


def test_field_value_unicode_digits_rejected_integer_and_number():
    # "٥" (Arabic-Indic five) is str.isdigit()-true but not ASCII; the closed
    # ASCII grammar must reject it for both integer and number value types.
    for vt in ("integer", "number"):
        gold, bound, case = _field_case("equals", vt, [5])
        assert _outcomes(_build(case, gold, bound, _fv_parsed("٥")))["A1"] == "unsatisfied"
    # Ordinary ASCII signed / decimal forms retain their locked behavior.
    g, b, c = _field_case("equals", "integer", [5])
    assert _outcomes(_build(c, g, b, _fv_parsed("+5")))["A1"] == "satisfied"
    g, b, c = _field_case("equals", "number", [1.5])
    assert _outcomes(_build(c, g, b, _fv_parsed("1.5")))["A1"] == "satisfied"


def test_field_value_multi_actual_positive_any_negative_all():
    gold, bound, case = _field_case("equals", "integer", [5])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "T"}],
                     field_values=[{"entity_ref": "T", "field_name": "revenue", "field_value": "5"},
                                   {"entity_ref": "T", "field_name": "revenue", "field_value": "6"}])
    # equals is a positive operator: any matching field value satisfies.
    assert _outcomes(_build(case, gold, bound, parsed))["A1"] == "satisfied"
    gold2, bound2, case2 = _field_case("not_equals", "integer", [5])
    parsed2 = _parsed(entities=[{"entity_kind": "k", "entity_ref": "T"}],
                      field_values=[{"entity_ref": "T", "field_name": "revenue", "field_value": "5"},
                                    {"entity_ref": "T", "field_name": "revenue", "field_value": "6"}])
    # not_equals is negative: every field value must differ, so one match fails.
    assert _outcomes(_build(case2, gold2, bound2, parsed2))["A1"] == "unsatisfied"


def test_evidence_packet_boundary_excludes_unsupplied_passage():
    # Case supplies only synth-passage-0002; citing synth-passage-0003 (which
    # exists globally under the same source) must NOT satisfy the assertion.
    gold, bound = _gold_and_bound([
        _gold_entry("A1", "evidence_provenance", "T",
                    evidence_payload=_ev_payload("same_source_document"))])
    case = _case([_assertion("A1", "evidence_provenance")],
                 input_sources=("synth-source-0002",), input_passages=("synth-passage-0002",))
    parsed = _ev_parsed("synth-source-0002", "synth-passage-0003", "alpha")
    result = _build(case, gold, bound, parsed)
    assert _outcomes(result)["A1"] == "unsatisfied"
    assert result.input_validity_issues == ()  # completed-prediction defect, not Phase A


# --- Identity copy + ordering + dispatch feed -----------------------------


def test_semantic_identity_copied_verbatim():
    gold, bound = _gold_and_bound([
        _gold_entry("A1", "expected_entity", "E1", semver=None, chash="opaque-id")])
    case = _case([_assertion("A1", "expected_entity", semver=None, chash="opaque-id",
                             targets=("E1",))])
    ev = _build(case, gold, bound, _parsed(
        entities=[{"entity_kind": "k", "entity_ref": "E1"}])).evaluations[0]
    assert ev.assertion_semantic_version is None
    assert ev.assertion_contract_hash == "opaque-id"


def test_evaluations_in_case_order_and_feed_dispatcher():
    gold, bound = _gold_and_bound([
        _gold_entry("A1", "expected_entity", "E1"), _gold_entry("A2", "forbidden_entity", "F1")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1",)),
                  _assertion("A2", "forbidden_entity", targets=("F1",))])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"}])
    result = _build(case, gold, bound, parsed)
    assert [e.assertion_id for e in result.evaluations] == ["A1", "A2"]
    # Every evaluation is a committed ResolvedAssertionEvaluation the dispatcher accepts.
    for e in result.evaluations:
        assert isinstance(e, ResolvedAssertionEvaluation)
        assert e.outcome in ("satisfied", "unsatisfied", "indeterminate", "not_applicable")


def test_result_is_frozen_strict():
    result = _build(_det_case(), *_gold_and_bound([_gold_entry('UNREL', 'expected_entity', 'E1')]), _parsed())
    with pytest.raises(Exception):
        result.case_id = "mutated"  # type: ignore[misc]


# --- Determinism, purity, leakage, protected ------------------------------


def test_output_deterministic():
    gold, bound = _gold_and_bound([_gold_entry("A1", "expected_entity", "E1")])
    case = _case([_assertion("A1", "expected_entity", targets=("E1",))])
    parsed = _parsed(entities=[{"entity_kind": "k", "entity_ref": "E1"}])
    a = _build(case, gold, bound, parsed)
    b = _build(case, gold, bound, parsed)
    assert a == b


def test_no_sensitive_value_leakage():
    gold, bound, case = _ev_case("exact_passage")
    parsed = _ev_parsed("synth-source-0002", "synth-passage-0003", "SECRET_QUOTE")
    result = _build(case, gold, bound, parsed)
    blob = repr(result.model_dump())
    assert "SECRET_QUOTE" not in blob


def test_type_guards():
    with pytest.raises(TypeError):
        build_resolved_assertion_evaluations(
            case=object(), resolution=_resolution(), parsed_content=_parsed(),
            gold=_gold_and_bound([_gold_entry('UNREL', 'expected_entity', 'E1')])[0], bound_gold=_gold_and_bound([_gold_entry('UNREL', 'expected_entity', 'E1')])[1],
            source_snapshot=SOURCE, validation_snapshots=_validation(),
            validator_findings=_findings())


def test_public_surface():
    assert set(sa_mod.__all__) == {
        "SemanticAssertionEvaluationError", "SemanticAssertionEvaluationResult",
        "build_resolved_assertion_evaluations",
    }
    assert "_PhaseAIssue" not in evaluation_pkg.__all__
    assert isinstance(SemanticAssertionEvaluationError("x", reason_code="c"),
                      SemanticAssertionEvaluationError)
    assert issubclass(SemanticAssertionEvaluationResult, object)


def test_protected_contract_hashes():
    from dynamic_ai_products.evaluation.gold import GoldAssertionSet
    from dynamic_ai_products.evaluation.models import ValidatorFinding
    from dynamic_ai_products.evaluation.taxonomy import AxisTaxonomy
    from dynamic_ai_products.evaluation.validation_snapshot import ValidationArtifactSnapshotSet
    mapping = {
        ("validator_finding", "0.1.0"): ValidatorFinding,
        ("gold_assertion_set", "0.1.0"): GoldAssertionSet,
        ("axis_taxonomy", "0.1.0"): AxisTaxonomy,
        ("validation_artifact_snapshot_set", "0.1.0"): ValidationArtifactSnapshotSet,
    }
    for (cid, ver), cls in mapping.items():
        assert model_contract_hash(cls, cid, ver) == PROTECTED_HASHES[(cid, ver)]


def test_package_export_parity():
    # Durable: sorted + unique + the three Slice-12H names present (no frozen
    # package-wide count that a future slice would have to churn).
    assert evaluation_pkg.__all__ == sorted(evaluation_pkg.__all__)
    assert len(set(evaluation_pkg.__all__)) == len(evaluation_pkg.__all__)
    for name in sa_mod.__all__:
        assert name in evaluation_pkg.__all__


def test_manifest_parity():
    import re
    lines = (ROOT / "REPO_MANIFEST.md").read_text().splitlines()
    declared = int(re.search(r"listed:\s*\*\*(\d+)\*\*",
                             "\n".join(lines)).group(1))
    paths = [re.match(r"- `([^`]+)`", ln).group(1) for ln in lines if re.match(r"- `[^`]+`\s*$", ln)]
    # Durable: the declared total equals the actual unique listed-path count.
    assert len(set(paths)) == len(paths)
    assert declared == len(paths)
    for p in ("src/dynamic_ai_products/evaluation/semantic_assertions.py",
              "tests/evaluation/test_semantic_assertions.py"):
        assert paths.count(p) == 1


def test_import_no_io_no_hash_no_clock():
    code = "\n".join([
        "import sys, os, hashlib, importlib, time",
        "sys.path.insert(0, 'src')",
        "import pydantic",
        "import dynamic_ai_products, dynamic_ai_products.universe.io_utils",
        "import dynamic_ai_products.evaluation",
        "sys.modules.pop('dynamic_ai_products.evaluation.semantic_assertions', None)",
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
        "importlib.import_module('dynamic_ai_products.evaluation.semantic_assertions')",
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
