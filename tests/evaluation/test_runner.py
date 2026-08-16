"""Slice 13: single-case evaluation runner and terminal reports.

Two genuine end-to-end chains anchor the suite: a ``capability_extraction``
chain over the committed substrate-integration bytes (terminal
``completed``/``pass``, exit 0, ``observation_target_binding@0.1.0``), and a
``task_extraction`` chain over a temporary root built from existing raw task
material (terminal ``completed``/``fail``, exit 1, one critical
``publication_date_cutoff`` finding, ``observation_target_binding@0.2.0`` whose
required parent-snapshot pins equal the plan's pinned snapshot identity). Every
derived artifact is produced, persisted, reloaded, and hash-verified through
its sanctioned public producer — no prebuilt terminal or derived object and no
``model_construct`` stand-in appears on any positive path.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import report as report_mod
from dynamic_ai_products.evaluation import runner as runner_mod
from dynamic_ai_products.evaluation.cases import load_case
from dynamic_ai_products.evaluation.contracts import (
    canonical_contract_bytes,
    model_contract_hash,
)
from dynamic_ai_products.evaluation.envelopes import PredictionArtifactManifest
from dynamic_ai_products.evaluation.gates import load_evaluation_result
from dynamic_ai_products.evaluation.gold import GoldAssertionSet
from dynamic_ai_products.evaluation.models import CaseSetManifest, PredictionEnvelope
from dynamic_ai_products.evaluation.observation_target_binding import (
    load_observation_target_binding,
)
from dynamic_ai_products.evaluation.output_manifest import (
    load_evaluation_output_manifest_v2,
)
from dynamic_ai_products.evaluation.parent_observation_snapshot import (
    ParentObservationSnapshot,
    load_parent_observation_snapshot,
)
from dynamic_ai_products.evaluation.prediction_content import (
    load_parsed_prediction_content,
    parsed_prediction_content_artifact_sha256,
)
from dynamic_ai_products.evaluation.report import (
    MachineEvaluationReport,
    build_machine_report,
    persist_evaluation_reports,
    render_human_report,
)
from dynamic_ai_products.evaluation.resolution_decisions import (
    ObservationTargetResolutionDecisionSet,
    persist_observation_target_resolution_decision_set,
)
from dynamic_ai_products.evaluation.runner import (
    EvaluationRunPlan,
    PlannedArtifactReference,
    SingleCaseEvaluationRun,
    run_single_case_evaluation,
)
from dynamic_ai_products.evaluation.runs import load_evaluation_run_manifest_v2
from dynamic_ai_products.evaluation.semantic_adapters import (
    apply_semantic_adapter,
    load_semantic_adapter_registry,
)
from dynamic_ai_products.evaluation.source_snapshot import (
    load_source_passage_snapshot_manifest,
)
from dynamic_ai_products.evaluation.stage_profiles import load_stage_profile_registry
from dynamic_ai_products.evaluation.taxonomy import AxisTaxonomy
from dynamic_ai_products.evaluation.validation_inputs import (
    build_extraction_validation_inputs,
)
from dynamic_ai_products.evaluation.validator_bundle_artifact import (
    load_validator_bundle_artifact,
)
from dynamic_ai_products.evaluation.validator_parameters import (
    load_validator_rule_parameters_v2,
)
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
EFX = ROOT / "evals" / "fixtures" / "evaluation_harness"
FX = EFX / "substrate_integration"
CREATED = "2026-07-27T00:00:00+00:00"
COMPANY = "SYNTH-CO-0001"
CAP_STAGE = "capability_extraction"
TASK_STAGE = "task_extraction"
TASK_CASE_ID = "SYNTH-CASE-TASK-0001"
TASK_OBS = "SYNTH-TASK-OBS-0001"
CANON_TASK = "SYNTH.PRODUCT.CAPABILITY.TASK"
CANON_CAP = "SYNTH.PRODUCT.ALPHA.CAPABILITY"
CANON_PROD = "SYNTH.PRODUCT.ALPHA"
TASK_RAW_REF = "task_prediction_source.json"

_CAP_GOVERNED_COPIES = (
    "target_registry.json",
    "case_set_manifest.json",
    "stage_profile_registry.json",
    "semantic_adapter_registry.json",
    "gold_assertion_set.json",
    "axis_taxonomy.json",
    "source_passage_snapshot_manifest.json",
    "source_documents.jsonl",
    "source_passages.jsonl",
    "capability_case.json",
    "parent_observation_snapshot.json",
)

_NINE_EXPORTS = (
    "EvaluationRunPlan",
    "MachineEvaluationReport",
    "PersistedEvaluationReports",
    "PlannedArtifactReference",
    "SingleCaseEvaluationRun",
    "build_machine_report",
    "persist_evaluation_reports",
    "render_human_report",
    "run_single_case_evaluation",
)


def _stamp(model_cls, contract_id):
    return {"contract_id": contract_id, "contract_version": "0.1.0",
            "contract_hash": model_contract_hash(model_cls, contract_id, "0.1.0")}


def _canonical_file(payload) -> bytes:
    return canonical_contract_bytes(payload) + b"\n"


def _write_scoring_config(governed, *, keep_synthetic_gate):
    cfg = json.loads((FX / "scoring_gate_config.json").read_bytes())
    if not keep_synthetic_gate:
        # The committed synthetic gate grammar is rejected by the gate engine by
        # design; the chain variant keeps its reference resolvable as a
        # diagnostic and runs with zero gates.
        moved = {"reference_id": "synth-scoring-gate-ref-0001",
                 "metric_id": "synth-metric-precision",
                 "population_slice_id": "synth-slice-global",
                 "slice_definitions": [{"minimum_verified_support": 0}]}
        cfg["gates"] = []
        cfg["diagnostics"] = [moved] + cfg["diagnostics"]
    (governed / "scoring_gate_config.json").write_bytes(
        json.dumps(cfg, indent=2).encode() + b"\n")


def _mk_roots(base):
    governed = base / "governed"
    prediction = base / "prediction"
    adjudication = base / "adjudication"
    eval_root = base / "eval_root"
    (governed / "members").mkdir(parents=True)
    (governed / "schemas").mkdir()
    prediction.mkdir()
    adjudication.mkdir()
    eval_root.mkdir()
    shutil.copyfile(
        EFX / "validator_parameters_v2/validator_rule_parameters.v2.json",
        governed / "validator_rule_parameters.v2.json")
    shutil.copyfile(
        EFX / "validator_bundle_v2/validator_bundle_artifact.v2.json",
        governed / "validator_bundle_artifact.v2.json")
    return governed, prediction, adjudication, eval_root


def build_capability_roots(base, *, keep_synthetic_gate=False):
    governed, prediction, adjudication, eval_root = _mk_roots(base)
    for name in _CAP_GOVERNED_COPIES:
        shutil.copyfile(FX / name, governed / name)
    shutil.copyfile(FX / "members/product_parent.json",
                    governed / "members/product_parent.json")
    shutil.copyfile(ROOT / "schemas/capability_observation.schema.json",
                    governed / "schemas/capability_observation.schema.json")
    _write_scoring_config(governed, keep_synthetic_gate=keep_synthetic_gate)
    for name in ("prediction_run_manifest.json", "prediction_envelopes.jsonl",
                 "prediction_source.json"):
        shutil.copyfile(FX / name, prediction / name)
    _write_decision_set(
        governed, prediction, adjudication, case_reference="capability_case.json",
        stage=CAP_STAGE, raw_reference="prediction_source.json",
        decisions=lambda: [
            _decision("SYNTH-CAPABILITY-OBS-0001", "capability", CANON_CAP,
                      parent=False),
            _decision("SYNTH-PRODUCT-OBS-0001", "product", CANON_PROD, parent=True)])
    return governed, prediction, adjudication, eval_root


def _decision(observation_id, kind, canonical, *, parent):
    return {
        "observation_id": observation_id, "observation_kind": kind,
        "resolution_status": "resolved", "canonical_target_reference": canonical,
        "parent_referenced": parent,
        "provenance": {
            "resolution_method": "stable_identity_field",
            "source_field_name": "stable_identity", "source_field_value": canonical,
            "registry_entry_reference_id": canonical,
            "resolver_kind": "deterministic_rule", "resolver_ids": ["runner-rule-v1"],
            "verification_status": "provisional",
            "verification_method": "deterministic_rule_review",
            "decision_timestamps": [CREATED], "change_reason": "runner chain proof"}}


def _write_decision_set(governed, prediction, adjudication, *, case_reference,
                        stage, raw_reference, decisions):
    case = load_case(case_reference, eval_root=governed)
    adapters = load_semantic_adapter_registry(
        "semantic_adapter_registry.json", eval_root=governed)
    line = (prediction / "prediction_envelopes.jsonl").read_text().splitlines()[0]
    envelope = PredictionEnvelope.model_validate(json.loads(line))
    raw = (prediction / raw_reference).read_bytes()
    parsed = apply_semantic_adapter(
        adapters.registry, case=case, envelope=envelope,
        raw_artifact_reference=raw_reference, raw_artifact_bytes=raw)
    decision_set = ObservationTargetResolutionDecisionSet.model_validate({
        "contract": _stamp(ObservationTargetResolutionDecisionSet,
                           "observation_target_resolution_decision_set"),
        "decision_set_version": "runner-decisions-v1",
        "case_id": case.case_id, "stage": stage, "company_id": COMPANY,
        "prediction_record_id": envelope.prediction_record_id,
        "raw_artifact_reference": raw_reference,
        "raw_artifact_sha256": sha256_bytes(raw),
        "parsed_prediction_content_sha256":
            parsed_prediction_content_artifact_sha256(parsed),
        "decisions": decisions()})
    persist_observation_target_resolution_decision_set(
        decision_set, source_root=adjudication, reference="decision_set.json")


def build_task_roots(base):
    governed, prediction, adjudication, eval_root = _mk_roots(base)
    for name in ("target_registry.json", "stage_profile_registry.json",
                 "semantic_adapter_registry.json",
                 "source_passage_snapshot_manifest.json",
                 "source_documents.jsonl", "source_passages.jsonl"):
        shutil.copyfile(FX / name, governed / name)
    shutil.copyfile(ROOT / "schemas/task_observation.schema.json",
                    governed / "schemas/task_observation.schema.json")
    _write_scoring_config(governed, keep_synthetic_gate=False)

    (governed / "task_case.json").write_bytes(_canonical_file({
        "case_id": TASK_CASE_ID, "stage": TASK_STAGE,
        "stage_context": {"observation_window": {"start": "2025-01-01",
                                                 "end": "2025-12-31"}},
        "input_source_ids": ["synth-source-0001", "synth-source-0002",
                             "synth-source-0003"],
        "input_passage_ids": ["synth-passage-0001", "synth-passage-0003",
                              "synth-passage-0004"],
        "assertions": [{"assertion_id": f"{TASK_CASE_ID}-A1",
                        "kind": "expected_entity", "semantic_version": "0.1.0",
                        "target_references": [CANON_TASK],
                        "scoring_gate_config_references":
                            ["synth-scoring-gate-ref-0001"]}],
        "failure_tags": ["synthetic_task_chain"],
        "notes": "Synthetic task-extraction case for the Slice 13 runner chain.",
        "created_by": "synthetic-researcher",
        "created_at": "2026-07-27T08:00:00+00:00",
        "guideline_version": "draft-v0.1"}))

    # Raw task document: the existing committed probe raw material, with the
    # company identity aligned to the substrate company.
    probe = json.loads(
        (EFX / "parsed_content" / "task_extraction_cutoff_probe.json").read_bytes())
    probe["company_id"] = COMPANY
    raw_bytes = canonical_contract_bytes(probe)
    (prediction / TASK_RAW_REF).write_bytes(raw_bytes)

    envelope_payload = {
        "contract": _stamp(PredictionEnvelope, "prediction_envelope"),
        "prediction_record_id": "SYNTH-PRED-TASK-0001", "stage": TASK_STAGE,
        "source_references": [TASK_RAW_REF],
        "prompt_model_metadata": {"synthetic_model_label": "synth-model-v0"},
        "input_packet_hash": "2" * 64,
        "prediction_run_manifest_reference": "prediction_run_manifest.json"}
    envelopes_bytes = json.dumps(envelope_payload, sort_keys=True).encode() + b"\n"
    (prediction / "prediction_envelopes.jsonl").write_bytes(envelopes_bytes)
    (prediction / "prediction_run_manifest.json").write_bytes(_canonical_file({
        "contract": _stamp(PredictionArtifactManifest, "prediction_artifact_manifest"),
        "prediction_run_id": "SYNTH-PRED-RUN-TASK-0001",
        "envelopes_reference": "prediction_envelopes.jsonl",
        "envelopes_sha256": sha256_bytes(envelopes_bytes),
        "record_count": 1,
        "source_artifacts": [{"reference": TASK_RAW_REF,
                              "sha256": sha256_bytes(raw_bytes)}]}))

    registry_sha = sha256_bytes((governed / "target_registry.json").read_bytes())
    (governed / "case_set_manifest.json").write_bytes(_canonical_file({
        "contract": _stamp(CaseSetManifest, "case_set_manifest"),
        "case_set_version": "synth-task-case-set-v1", "lifecycle": "draft",
        "registry_snapshot_version": "synth-target-registry-v1",
        "registry_snapshot_hash": registry_sha,
        "entries": [{"case_id": TASK_CASE_ID, "partition": "dev",
                     "suites": ["regression"], "input_packet_hash": "2" * 64}]}))

    (governed / "gold_assertion_set.json").write_bytes(_canonical_file({
        "contract": _stamp(GoldAssertionSet, "gold_assertion_set"),
        "gold_set_version": "synth-task-gold-v1",
        "entries": [{
            "case_id": TASK_CASE_ID, "assertion_id": f"{TASK_CASE_ID}-A1",
            "assertion_semantic_version": "0.1.0",
            "assertion_kind": "expected_entity",
            "canonical_target_reference": CANON_TASK,
            "provenance": {
                "gold_origin": "constructed", "verification_status": "verified",
                "verification_method": "construction_review",
                "annotator_ids": ["synthetic-annotator-0001"],
                "reviewer_ids": ["synthetic-reviewer-0001"],
                "annotation_timestamps": ["2026-01-15T10:00:00+00:00"],
                "source_packet_hash": "abcdef0123456789" * 4,
                "case_version": "synth-case-v1",
                "change_reason": "initial synthetic construction"}}]}))

    (governed / "axis_taxonomy.json").write_bytes(_canonical_file({
        "contract": _stamp(AxisTaxonomy, "axis_taxonomy"),
        "taxonomy_version": "synth-task-axis-taxonomy-v1",
        "axes": [{"axis_id": "overall", "axis_role": "task",
                  "metric_type": "nominal_single_label",
                  "labels": [CANON_TASK, "SYNTH.PRODUCT.OTHER.TASK"]}]}))

    shutil.copyfile(FX / "members/product_parent.json",
                    governed / "members/product_parent.json")
    capability_member = (
        EFX / "parsed_content" / "capability_extraction_raw.json").read_bytes()
    (governed / "members" / "capability_parent.json").write_bytes(capability_member)
    product_member = (governed / "members" / "product_parent.json").read_bytes()
    (governed / "parent_observation_snapshot.json").write_bytes(_canonical_file({
        "contract": _stamp(ParentObservationSnapshot, "parent_observation_snapshot"),
        "snapshot_version": "synth-task-parent-snapshot-v1",
        "case_id": TASK_CASE_ID, "company_id": COMPANY,
        "observation_cutoff": "2025-12-31",
        "members": [
            {"role": "capability_parent",
             "reference": "members/capability_parent.json",
             "sha256": sha256_bytes(capability_member)},
            {"role": "product_parent", "reference": "members/product_parent.json",
             "sha256": sha256_bytes(product_member)}]}))
    _write_decision_set(
        governed, prediction, adjudication, case_reference="task_case.json",
        stage=TASK_STAGE, raw_reference=TASK_RAW_REF,
        decisions=lambda: [_decision(TASK_OBS, "task", CANON_TASK, parent=False)])
    return governed, prediction, adjudication, eval_root


def _pin(root, reference):
    return sha256_bytes((root / reference).read_bytes())


def _plan_payload(governed, prediction, adjudication, *, run_id, stage,
                  case_reference, raw_reference, prediction_run_id,
                  prediction_record_id, output_schema_reference):
    entries = [
        ("axis_taxonomy", "governed", governed, "axis_taxonomy.json"),
        ("case", "governed", governed, case_reference),
        ("case_set_manifest", "governed", governed, "case_set_manifest.json"),
        ("gold_assertion_set", "governed", governed, "gold_assertion_set.json"),
        ("observation_target_resolution_decision_set", "adjudication", adjudication,
         "decision_set.json"),
        ("output_schema", "governed", governed, output_schema_reference),
        ("parent_observation_snapshot", "governed", governed,
         "parent_observation_snapshot.json"),
        ("prediction_run_manifest", "prediction", prediction,
         "prediction_run_manifest.json"),
        ("raw_prediction_artifact", "prediction", prediction, raw_reference),
        ("scoring_gate_config", "governed", governed, "scoring_gate_config.json"),
        ("semantic_adapter_registry", "governed", governed,
         "semantic_adapter_registry.json"),
        ("source_passage_snapshot_manifest", "governed", governed,
         "source_passage_snapshot_manifest.json"),
        ("stage_profile_registry", "governed", governed,
         "stage_profile_registry.json"),
        ("target_registry", "governed", governed, "target_registry.json"),
        ("validator_bundle_artifact", "governed", governed,
         "validator_bundle_artifact.v2.json"),
        ("validator_rule_parameters", "governed", governed,
         "validator_rule_parameters.v2.json"),
    ]
    return {
        "eval_run_id": run_id, "evaluation_stage": stage,
        "prediction_run_id": prediction_run_id,
        "prediction_record_id": prediction_record_id,
        "company_id": COMPANY, "code_commit": "runner-chain-commit",
        "evaluation_created_at": CREATED,
        "governed_artifact_root": str(governed),
        "prediction_source_root": str(prediction),
        "adjudication_source_root": str(adjudication),
        "artifact_references": [
            {"artifact_role": role, "artifact_root": root_kind,
             "reference": reference, "sha256": _pin(root, reference)}
            for role, root_kind, root, reference in entries]}


def capability_plan_payload(governed, prediction, adjudication,
                            run_id="runner-cap-e2e"):
    return _plan_payload(
        governed, prediction, adjudication, run_id=run_id, stage=CAP_STAGE,
        case_reference="capability_case.json", raw_reference="prediction_source.json",
        prediction_run_id="SYNTH-PRED-RUN-0001",
        prediction_record_id="SYNTH-PRED-0001",
        output_schema_reference="schemas/capability_observation.schema.json")


def task_plan_payload(governed, prediction, adjudication, run_id="runner-task-e2e"):
    return _plan_payload(
        governed, prediction, adjudication, run_id=run_id, stage=TASK_STAGE,
        case_reference="task_case.json", raw_reference=TASK_RAW_REF,
        prediction_run_id="SYNTH-PRED-RUN-TASK-0001",
        prediction_record_id="SYNTH-PRED-TASK-0001",
        output_schema_reference="schemas/task_observation.schema.json")


class _Chain:
    def __init__(self, governed, prediction, adjudication, eval_root, plan, summary):
        self.governed = governed
        self.prediction = prediction
        self.adjudication = adjudication
        self.eval_root = eval_root
        self.plan = plan
        self.summary = summary
        self.run_dir = eval_root / plan.eval_run_id


@pytest.fixture(scope="module")
def cap_chain(tmp_path_factory):
    base = tmp_path_factory.mktemp("runner-cap")
    governed, prediction, adjudication, eval_root = build_capability_roots(base)
    plan = EvaluationRunPlan.model_validate(
        capability_plan_payload(governed, prediction, adjudication))
    summary = run_single_case_evaluation(plan, eval_root=eval_root)
    return _Chain(governed, prediction, adjudication, eval_root, plan, summary)


@pytest.fixture(scope="module")
def task_chain(tmp_path_factory):
    base = tmp_path_factory.mktemp("runner-task")
    governed, prediction, adjudication, eval_root = build_task_roots(base)
    plan = EvaluationRunPlan.model_validate(
        task_plan_payload(governed, prediction, adjudication))
    summary = run_single_case_evaluation(plan, eval_root=eval_root)
    return _Chain(governed, prediction, adjudication, eval_root, plan, summary)


def _entry(plan, role):
    return next(e for e in plan.artifact_references if e.artifact_role == role)


# --- Capability chain (exit 0) ---------------------------------------------


def test_capability_chain_completes_pass_exit_0(cap_chain):
    s = cap_chain.summary
    assert isinstance(s, SingleCaseEvaluationRun)
    assert s.execution_status == "completed"
    assert s.gate_verdict == "pass"
    assert s.exit_code == 0
    assert s.issues == ()
    assert s.machine_report_reference == "reports/machine_evaluation_report.json"
    assert s.human_report_reference == "reports/human_evaluation_report.md"


def test_capability_run_persists_the_complete_artifact_chain(cap_chain):
    run = cap_chain.run_dir
    for rel in ("evaluation_run_manifest.json", "predictions/normalized_envelopes.jsonl",
                "snapshots/parsed_prediction_content.json",
                "snapshots/observation_target_binding.json",
                "snapshots/validation_artifact_snapshot_set.json",
                "findings/validator_findings.jsonl",
                "assertions/assertion_outcomes.jsonl",
                "metric_inputs/metric_input_snapshot.json",
                "metrics/metric_report.v2.json",
                "output_manifest/evaluation_output_manifest.json",
                "results/evaluation_result.json",
                "reports/machine_evaluation_report.json",
                "reports/human_evaluation_report.md"):
        assert (run / rel).is_file(), rel
    binding = json.loads((run / "snapshots/observation_target_binding.json").read_text())
    assert binding["contract"]["contract_version"] == "0.1.0"


def test_capability_summary_mirrors_read_back_hashes(cap_chain):
    s = cap_chain.summary
    run = cap_chain.run_dir
    assert s.result_sha256 == sha256_bytes(
        (run / "results/evaluation_result.json").read_bytes())
    assert s.output_manifest_sha256 == sha256_bytes(
        (run / "output_manifest/evaluation_output_manifest.json").read_bytes())


def test_capability_rerun_same_run_id_is_write_once(cap_chain):
    before = (cap_chain.run_dir / "results/evaluation_result.json").read_bytes()
    with pytest.raises(runner_mod._PreManifestEvaluationError) as ei:
        run_single_case_evaluation(cap_chain.plan, eval_root=cap_chain.eval_root)
    assert ei.value.exit_code == 4
    assert ei.value.issues[0].issue_code == "run_initialization_failed"
    assert (cap_chain.run_dir / "results/evaluation_result.json").read_bytes() == before


def test_capability_deterministic_rerun_and_fresh_run_id(tmp_path):
    governed, prediction, adjudication, eval_root_a = build_capability_roots(tmp_path)
    eval_root_b = tmp_path / "eval_root_b"
    eval_root_c = tmp_path / "eval_root_c"
    eval_root_b.mkdir()
    eval_root_c.mkdir()
    plan = EvaluationRunPlan.model_validate(
        capability_plan_payload(governed, prediction, adjudication))
    first = run_single_case_evaluation(plan, eval_root=eval_root_a)
    second = run_single_case_evaluation(plan, eval_root=eval_root_b)
    # Full determinism: identical plan in a fresh root -> identical summary,
    # including every read-back hash.
    assert first == second
    fresh = EvaluationRunPlan.model_validate(capability_plan_payload(
        governed, prediction, adjudication, run_id="runner-cap-fresh"))
    third = run_single_case_evaluation(fresh, eval_root=eval_root_c)
    assert third.execution_status == first.execution_status
    assert third.gate_verdict == first.gate_verdict
    assert third.exit_code == first.exit_code


# --- Task chain (exit 1, v0.2 binding) --------------------------------------


def test_task_chain_completes_fail_exit_1(task_chain):
    s = task_chain.summary
    assert s.execution_status == "completed"
    assert s.gate_verdict == "fail"
    assert s.exit_code == 1
    assert s.issues == ()
    findings = [json.loads(line) for line in (
        task_chain.run_dir / "findings/validator_findings.jsonl"
    ).read_text().splitlines() if line.strip()]
    assert [(f["validator"], f["severity"]) for f in findings] == [
        ("publication_date_cutoff", "critical")]
    result = load_evaluation_result(
        task_chain.plan.eval_run_id, eval_root=task_chain.eval_root).result
    assert result.metrics["critical_finding_ids"] == [findings[0]["finding_id"]]
    outcomes = [json.loads(line) for line in (
        task_chain.run_dir / "assertions/assertion_outcomes.jsonl"
    ).read_text().splitlines() if line.strip()]
    assert [(o["assertion_id"], o["outcome"]) for o in outcomes] == [
        (f"{TASK_CASE_ID}-A1", "satisfied")]
    snapshot = json.loads(
        (task_chain.run_dir / "metric_inputs/metric_input_snapshot.json").read_text())
    assert len(snapshot["axis_records"]) == 1


def test_task_binding_is_v2_with_the_plan_pinned_snapshot(task_chain):
    # The REAL successor path end-to-end: the runner's task builder persisted a
    # v0.2 binding; reload it through the loader and the output-manifest hash.
    manifest = load_evaluation_output_manifest_v2(
        task_chain.plan.eval_run_id, eval_root=task_chain.eval_root,
        stage_profile_registry=load_stage_profile_registry(
            "stage_profile_registry.json", eval_root=task_chain.governed))
    assert manifest.model.derived_evaluation_stage == TASK_STAGE
    binding = load_observation_target_binding(
        f"{task_chain.plan.eval_run_id}/snapshots/observation_target_binding.json",
        eval_root=task_chain.eval_root,
        expected_sha256=manifest.model.observation_target_binding_sha256)
    assert binding.version == "0.2.0"
    assert type(binding.model).__name__ == "ObservationTargetBindingV2"
    parents_entry = _entry(task_chain.plan, "parent_observation_snapshot")
    assert binding.model.parent_observation_snapshot_sha256 == parents_entry.sha256
    parents = load_parent_observation_snapshot(
        parents_entry.reference, source_root=task_chain.governed)
    assert binding.model.parent_observation_snapshot_version == parents.version


def test_task_post_run_snapshot_substitution_is_detectable(task_chain, tmp_path):
    # Runner-level tamper: replay P2 from the reloaded run artifacts with a
    # context-matching foreign snapshot; the durable v0.2 pins reject it.
    run_id = task_chain.plan.eval_run_id
    governed = task_chain.governed
    manifest = load_evaluation_output_manifest_v2(
        run_id, eval_root=task_chain.eval_root,
        stage_profile_registry=load_stage_profile_registry(
            "stage_profile_registry.json", eval_root=governed))
    binding = load_observation_target_binding(
        f"{run_id}/snapshots/observation_target_binding.json",
        eval_root=task_chain.eval_root,
        expected_sha256=manifest.model.observation_target_binding_sha256)
    parsed = load_parsed_prediction_content(
        f"{run_id}/snapshots/parsed_prediction_content.json",
        eval_root=task_chain.eval_root,
        expected_sha256=manifest.model.parsed_prediction_content_sha256)
    run_manifest = load_evaluation_run_manifest_v2(
        run_id, eval_root=task_chain.eval_root).manifest
    params = load_validator_rule_parameters_v2(
        "validator_rule_parameters.v2.json", eval_root=governed)
    bundle = load_validator_bundle_artifact(
        "validator_bundle_artifact.v2.json", eval_root=governed,
        rule_parameters=params)
    snap = load_source_passage_snapshot_manifest(
        "source_passage_snapshot_manifest.json", eval_root=governed)
    case = load_case("task_case.json", eval_root=governed)
    raw_bytes = (task_chain.prediction / TASK_RAW_REF).read_bytes()
    schema_bytes = (governed / "schemas/task_observation.schema.json").read_bytes()
    # Context-matching foreign snapshot: identical model content, different
    # persisted bytes (re-serialized), so only the pin equality can reject it.
    payload = json.loads((governed / "parent_observation_snapshot.json").read_text())
    foreign_dir = tmp_path / "foreign_parents"
    shutil.copytree(governed / "members", foreign_dir / "members")
    (foreign_dir / "parent_observation_snapshot.json").write_bytes(
        json.dumps(payload, indent=2).encode() + b"\n")
    foreign = load_parent_observation_snapshot(
        "parent_observation_snapshot.json", source_root=foreign_dir)
    assert foreign.version == binding.model.parent_observation_snapshot_version
    assert foreign.sha256 != binding.model.parent_observation_snapshot_sha256
    with pytest.raises(ValueError, match="parent snapshot sha256"):
        build_extraction_validation_inputs(
            case=case, evaluation_stage=TASK_STAGE, parsed_prediction_content=parsed,
            raw_artifact_bytes=raw_bytes, output_schema_bytes=schema_bytes,
            source_snapshot=snap, rule_parameters=params,
            validator_bundle_artifact=bundle, run_manifest=run_manifest,
            observation_target_binding=binding, parent_snapshot=foreign)


def test_task_post_run_binding_byte_tamper_is_detectable(task_chain, tmp_path):
    tampered_root = tmp_path / "tampered"
    shutil.copytree(task_chain.eval_root, tampered_root)
    run_id = task_chain.plan.eval_run_id
    dest = tampered_root / run_id / "snapshots" / "observation_target_binding.json"
    doc = json.loads(dest.read_text())
    doc["parent_observation_snapshot_sha256"] = "0" * 64
    dest.write_bytes((json.dumps(doc) + "\n").encode())
    manifest = load_evaluation_output_manifest_v2(
        run_id, eval_root=task_chain.eval_root,
        stage_profile_registry=load_stage_profile_registry(
            "stage_profile_registry.json", eval_root=task_chain.governed))
    with pytest.raises(Exception) as ei:
        load_observation_target_binding(
            f"{run_id}/snapshots/observation_target_binding.json",
            eval_root=tampered_root,
            expected_sha256=manifest.model.observation_target_binding_sha256)
    assert getattr(ei.value, "reason_code", None) == "expected_hash_mismatch"


# --- Strict plan invariants -------------------------------------------------


def _mutated_cap_payload(cap_chain, mutate):
    payload = capability_plan_payload(
        cap_chain.governed, cap_chain.prediction, cap_chain.adjudication,
        run_id="runner-plan-invariants")
    mutate(payload)
    return payload


@pytest.mark.parametrize("mutate,match", [
    (lambda p: p["artifact_references"].reverse(), "strictly ascending"),
    (lambda p: p["artifact_references"].pop(), "sixteen governed roles"),
    (lambda p: p["artifact_references"].append(p["artifact_references"][0]),
     "sixteen governed roles|strictly ascending"),
    (lambda p: p["artifact_references"][1].update(artifact_root="prediction"),
     "must bind artifact_root"),
    (lambda p: p["artifact_references"][0].update(reference="../escape.json"),
     "safe relative POSIX reference"),
    (lambda p: p["artifact_references"][0].update(sha256="G" * 64), "pattern"),
    (lambda p: p.update(evaluation_created_at="2026-07-27T00:00:00"), "RFC3339"),
    (lambda p: p.update(company_id="  "), "company_id"),
    (lambda p: p.update(eval_run_id="a/b"), "single safe path component"),
    (lambda p: p.update(evaluation_stage="universe_screen"), "evaluation_stage"),
])
def test_plan_invariant_failures(cap_chain, mutate, match):
    with pytest.raises(PydanticValidationError, match=match):
        EvaluationRunPlan.model_validate(_mutated_cap_payload(cap_chain, mutate))


def test_tampered_plan_fails_closed_revalidation(cap_chain, tmp_path):
    plan = EvaluationRunPlan.model_validate(
        _mutated_cap_payload(cap_chain, lambda p: None))
    tampered = plan.model_construct(**{**dict(plan), "company_id": ""})
    empty_root = tmp_path / "untouched"
    empty_root.mkdir()
    with pytest.raises(runner_mod._PreManifestEvaluationError) as ei:
        run_single_case_evaluation(tampered, eval_root=empty_root)
    assert ei.value.exit_code == 4
    assert ei.value.issues[0].issue_code == "plan_invalid"
    assert list(empty_root.iterdir()) == []


def test_non_plan_argument_is_a_type_error(tmp_path):
    with pytest.raises(TypeError, match="EvaluationRunPlan"):
        run_single_case_evaluation({"eval_run_id": "x"}, eval_root=tmp_path)


# --- Pre-manifest boundary: pins, Rule-1 binding, cardinality (exit 4) ------


def _fresh_cap(tmp_path, **root_kwargs):
    governed, prediction, adjudication, eval_root = build_capability_roots(
        tmp_path, **root_kwargs)
    return governed, prediction, adjudication, eval_root


def _expect_exit_4(plan_payload, eval_root, issue_code):
    plan = EvaluationRunPlan.model_validate(plan_payload)
    with pytest.raises(runner_mod._PreManifestEvaluationError) as ei:
        run_single_case_evaluation(plan, eval_root=eval_root)
    assert ei.value.exit_code == 4
    assert ei.value.issues[0].issue_code == issue_code
    assert list(eval_root.iterdir()) == []
    return ei.value


def test_pin_mismatch_is_pre_manifest_exit_4_no_writes(tmp_path):
    governed, prediction, adjudication, eval_root = _fresh_cap(tmp_path)
    payload = capability_plan_payload(governed, prediction, adjudication)
    (governed / "axis_taxonomy.json").write_bytes(
        (governed / "axis_taxonomy.json").read_bytes() + b"\n")
    _expect_exit_4(payload, eval_root, "artifact_pin_mismatch")


def test_missing_artifact_is_pre_manifest_exit_4(tmp_path):
    governed, prediction, adjudication, eval_root = _fresh_cap(tmp_path)
    payload = capability_plan_payload(governed, prediction, adjudication)
    (governed / "gold_assertion_set.json").unlink()
    _expect_exit_4(payload, eval_root, "artifact_missing")


def test_output_schema_rule1_mismatch_before_p2(tmp_path):
    governed, prediction, adjudication, eval_root = _fresh_cap(tmp_path)
    # A real, correctly pinned schema file whose identity disagrees with the
    # selected Rule-1 payload for the capability stage.
    shutil.copyfile(ROOT / "schemas/task_observation.schema.json",
                    governed / "schemas/task_observation.schema.json")
    payload = capability_plan_payload(governed, prediction, adjudication)
    for entry in payload["artifact_references"]:
        if entry["artifact_role"] == "output_schema":
            entry["reference"] = "schemas/task_observation.schema.json"
            entry["sha256"] = _pin(governed, "schemas/task_observation.schema.json")
    _expect_exit_4(payload, eval_root, "output_schema_binding_invalid")


def test_cardinality_two_memberships_rejected_before_directory(tmp_path):
    governed, prediction, adjudication, eval_root = _fresh_cap(tmp_path)
    manifest = json.loads((governed / "case_set_manifest.json").read_bytes())
    manifest["entries"].append(
        {**manifest["entries"][0], "case_id": "SYNTH-CASE-OTHER"})
    (governed / "case_set_manifest.json").write_bytes(_canonical_file(manifest))
    payload = capability_plan_payload(governed, prediction, adjudication)
    _expect_exit_4(payload, eval_root, "cardinality_invalid")


def test_cardinality_two_envelopes_rejected_before_directory(tmp_path):
    governed, prediction, adjudication, eval_root = _fresh_cap(tmp_path)
    lines = (prediction / "prediction_envelopes.jsonl").read_text().splitlines()
    second = json.loads(lines[0])
    second["prediction_record_id"] = "SYNTH-PRED-0002"
    doubled = (lines[0] + "\n" + json.dumps(second, sort_keys=True) + "\n").encode()
    (prediction / "prediction_envelopes.jsonl").write_bytes(doubled)
    manifest = json.loads((prediction / "prediction_run_manifest.json").read_bytes())
    manifest["envelopes_sha256"] = sha256_bytes(doubled)
    manifest["record_count"] = 2
    (prediction / "prediction_run_manifest.json").write_bytes(_canonical_file(manifest))
    payload = capability_plan_payload(governed, prediction, adjudication)
    _expect_exit_4(payload, eval_root, "cardinality_invalid")


def test_cardinality_stage_mismatch_rejected(tmp_path):
    governed, prediction, adjudication, eval_root = _fresh_cap(tmp_path)
    payload = capability_plan_payload(governed, prediction, adjudication)
    payload["evaluation_stage"] = TASK_STAGE
    # The task stage selects the task Rule-1 payload, so the output-schema
    # binding trips first — rebind it to isolate the cardinality check.
    shutil.copyfile(ROOT / "schemas/task_observation.schema.json",
                    governed / "schemas/task_observation.schema.json")
    for entry in payload["artifact_references"]:
        if entry["artifact_role"] == "output_schema":
            entry["reference"] = "schemas/task_observation.schema.json"
            entry["sha256"] = _pin(governed, "schemas/task_observation.schema.json")
    _expect_exit_4(payload, eval_root, "cardinality_invalid")


def test_prediction_record_binding_rejected(tmp_path):
    governed, prediction, adjudication, eval_root = _fresh_cap(tmp_path)
    payload = capability_plan_payload(governed, prediction, adjudication)
    payload["prediction_record_id"] = "SYNTH-PRED-OTHER"
    _expect_exit_4(payload, eval_root, "prediction_binding_invalid")


def test_decision_set_company_binding_rejected(tmp_path):
    governed, prediction, adjudication, eval_root = _fresh_cap(tmp_path)
    payload = capability_plan_payload(governed, prediction, adjudication)
    payload["company_id"] = "SYNTH-CO-OTHER"
    _expect_exit_4(payload, eval_root, "adjudication_binding_invalid")


# --- Dry-run and CLI --------------------------------------------------------


def _plan_file(tmp_path, payload):
    plan_path = tmp_path / "plan.json"
    plan_path.write_bytes(json.dumps(payload, indent=2).encode())
    return str(plan_path)


def test_dry_run_success_writes_nothing(tmp_path, capsys):
    governed, prediction, adjudication, eval_root = _fresh_cap(tmp_path)
    plan_path = _plan_file(
        tmp_path, capability_plan_payload(governed, prediction, adjudication))
    code = runner_mod.main(
        ["run", "--plan", plan_path, "--eval-root", str(eval_root), "--dry-run"])
    assert code == 0
    assert list(eval_root.iterdir()) == []
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert out["eval_run_id"] == "runner-cap-e2e"


def test_dry_run_failure_exits_4_and_writes_nothing(tmp_path, capsys):
    governed, prediction, adjudication, eval_root = _fresh_cap(tmp_path)
    payload = capability_plan_payload(governed, prediction, adjudication)
    (governed / "axis_taxonomy.json").write_bytes(b"{}")
    plan_path = _plan_file(tmp_path, payload)
    code = runner_mod.main(
        ["run", "--plan", plan_path, "--eval-root", str(eval_root), "--dry-run"])
    assert code == 4
    assert list(eval_root.iterdir()) == []
    assert "artifact_pin_mismatch" in capsys.readouterr().err


def test_unreadable_plan_document_exits_4(tmp_path, capsys):
    code = runner_mod.main(
        ["run", "--plan", str(tmp_path / "missing.json"),
         "--eval-root", str(tmp_path)])
    assert code == 4
    assert "plan_invalid" in capsys.readouterr().err


def test_cli_module_runs_the_chain_in_a_subprocess(tmp_path):
    governed, prediction, adjudication, eval_root = _fresh_cap(tmp_path)
    plan_path = _plan_file(
        tmp_path, capability_plan_payload(governed, prediction, adjudication))
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    dry = subprocess.run(
        [sys.executable, "-m", "dynamic_ai_products.evaluation.runner", "run",
         "--plan", plan_path, "--eval-root", str(eval_root), "--dry-run"],
        capture_output=True, text=True, env=env, cwd=ROOT)
    assert dry.returncode == 0, dry.stderr
    assert list(eval_root.iterdir()) == []
    full = subprocess.run(
        [sys.executable, "-m", "dynamic_ai_products.evaluation.runner", "run",
         "--plan", plan_path, "--eval-root", str(eval_root)],
        capture_output=True, text=True, env=env, cwd=ROOT)
    assert full.returncode == 0, full.stderr
    summary = json.loads(full.stdout)
    assert summary["execution_status"] == "completed"
    assert summary["gate_verdict"] == "pass"
    assert summary["exit_code"] == 0


# --- Post-manifest failure branches (exit codes 2, 3, 5) --------------------


def test_gate_policy_failure_persists_invalid_result_exit_2(tmp_path):
    # The committed synthetic gate grammar reaches step 16 and is rejected as
    # policy; the terminal invalid result and both reports are persisted, and
    # the already-persisted output manifest is preserved.
    governed, prediction, adjudication, eval_root = _fresh_cap(
        tmp_path, keep_synthetic_gate=True)
    plan = EvaluationRunPlan.model_validate(
        capability_plan_payload(governed, prediction, adjudication))
    summary = run_single_case_evaluation(plan, eval_root=eval_root)
    assert summary.execution_status == "invalid"
    assert summary.gate_verdict is None
    assert summary.exit_code == 2
    assert summary.issues[0].issue_code == "gate_policy_invalid"
    run = eval_root / plan.eval_run_id
    assert (run / "output_manifest/evaluation_output_manifest.json").is_file()
    assert (run / "reports/machine_evaluation_report.json").is_file()
    result = load_evaluation_result(plan.eval_run_id, eval_root=eval_root).result
    assert result.execution_status == "invalid"
    assert result.gate_verdict is None
    assert result.errors[0]["issue_code"] == "gate_policy_invalid"


def test_runtime_failure_after_findings_persists_errored_exit_3(
        tmp_path, monkeypatch):
    governed, prediction, adjudication, eval_root = _fresh_cap(tmp_path)
    plan = EvaluationRunPlan.model_validate(
        capability_plan_payload(governed, prediction, adjudication))

    def boom(*args, **kwargs):
        raise RuntimeError("synthetic-provider-detail")

    monkeypatch.setattr(runner_mod, "compute_metric_report_v2", boom)
    summary = run_single_case_evaluation(plan, eval_root=eval_root)
    assert summary.execution_status == "errored"
    assert summary.exit_code == 3
    assert summary.issues[0].issue_code == "runtime_failure"
    assert "synthetic-provider-detail" not in summary.issues[0].message
    run = eval_root / plan.eval_run_id
    manifest = json.loads(
        (run / "output_manifest/evaluation_output_manifest.json").read_text())
    # Every successfully persisted optional artifact is bound; the never-
    # persisted metric report is omitted, not fabricated.
    assert "metric_input_snapshot_sha256" in manifest
    assert "metric_report_v2_sha256" not in manifest


def test_failure_after_manifest_before_findings_writes_no_findings(
        tmp_path, monkeypatch):
    governed, prediction, adjudication, eval_root = _fresh_cap(tmp_path)
    plan = EvaluationRunPlan.model_validate(
        capability_plan_payload(governed, prediction, adjudication))

    def boom(*args, **kwargs):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(runner_mod, "evaluate_validator_findings", boom)
    summary = run_single_case_evaluation(plan, eval_root=eval_root)
    assert summary.execution_status == "errored"
    assert summary.exit_code == 3
    assert summary.output_manifest_sha256 is None
    run = eval_root / plan.eval_run_id
    assert not (run / "findings").exists()  # never fake empty findings
    assert not (run / "output_manifest").exists()
    assert (run / "results/evaluation_result.json").is_file()
    assert (run / "reports/machine_evaluation_report.json").is_file()


def test_invalid_content_failure_before_findings_exit_2(tmp_path, monkeypatch):
    governed, prediction, adjudication, eval_root = _fresh_cap(tmp_path)
    plan = EvaluationRunPlan.model_validate(
        capability_plan_payload(governed, prediction, adjudication))

    def boom(*args, **kwargs):
        raise ValueError("a governed content violation")

    monkeypatch.setattr(runner_mod, "build_extraction_validation_inputs", boom)
    summary = run_single_case_evaluation(plan, eval_root=eval_root)
    assert summary.execution_status == "invalid"
    assert summary.exit_code == 2
    assert summary.issues[0].issue_code == "artifact_binding_invalid"
    run = eval_root / plan.eval_run_id
    assert not (run / "findings").exists()
    assert not (run / "output_manifest").exists()


def test_failure_after_findings_binds_every_persisted_artifact(
        tmp_path, monkeypatch):
    governed, prediction, adjudication, eval_root = _fresh_cap(tmp_path)
    plan = EvaluationRunPlan.model_validate(
        capability_plan_payload(governed, prediction, adjudication))

    def boom(*args, **kwargs):
        raise ValueError("semantic evaluation violation")

    monkeypatch.setattr(
        runner_mod, "build_extraction_resolved_assertion_evaluations", boom)
    summary = run_single_case_evaluation(plan, eval_root=eval_root)
    assert summary.execution_status == "invalid"
    assert summary.exit_code == 2
    assert summary.output_manifest_sha256 is not None
    run = eval_root / plan.eval_run_id
    manifest = json.loads(
        (run / "output_manifest/evaluation_output_manifest.json").read_text())
    for present in ("validator_findings_sha256", "parsed_prediction_content_sha256",
                    "observation_target_binding_sha256",
                    "validation_artifact_snapshot_set_sha256"):
        assert present in manifest, present
    for absent in ("assertion_outcomes_sha256", "metric_input_snapshot_sha256",
                   "metric_report_v2_sha256"):
        assert absent not in manifest, absent


def test_report_persistence_failure_exits_5_and_preserves_result(
        tmp_path, monkeypatch):
    governed, prediction, adjudication, eval_root = _fresh_cap(tmp_path)
    plan = EvaluationRunPlan.model_validate(
        capability_plan_payload(governed, prediction, adjudication))

    def boom(*args, **kwargs):
        raise report_mod._ReportWriteError("synthetic report failure")

    monkeypatch.setattr(runner_mod, "persist_evaluation_reports", boom)
    summary = run_single_case_evaluation(plan, eval_root=eval_root)
    assert summary.exit_code == 5
    assert summary.execution_status == "completed"
    assert summary.gate_verdict == "pass"
    assert summary.machine_report_reference is None
    assert summary.human_report_reference is None
    assert summary.issues[-1].issue_code == "report_persistence_failed"
    run = eval_root / plan.eval_run_id
    assert summary.result_sha256 == sha256_bytes(
        (run / "results/evaluation_result.json").read_bytes())


# --- Report contract ---------------------------------------------------------


def _cap_loaded(cap_chain):
    result = load_evaluation_result(
        cap_chain.plan.eval_run_id, eval_root=cap_chain.eval_root)
    manifest = load_evaluation_output_manifest_v2(
        cap_chain.plan.eval_run_id, eval_root=cap_chain.eval_root,
        stage_profile_registry=load_stage_profile_registry(
            "stage_profile_registry.json", eval_root=cap_chain.governed))
    return result, manifest


def test_machine_report_accepts_only_reloaded_wrappers(cap_chain):
    result, manifest = _cap_loaded(cap_chain)
    report = build_machine_report(result, manifest)
    assert report.eval_run_id == result.eval_run_id
    assert report.result_sha256 == result.sha256
    assert report.output_manifest_sha256 == manifest.sha256
    for bad in ({"eval_run_id": "x"}, result.result, cap_chain.summary,
                result.sha256, manifest.model):
        with pytest.raises(TypeError):
            build_machine_report(bad, manifest)
    with pytest.raises(TypeError):
        build_machine_report(result, manifest.model)
    with pytest.raises(TypeError):
        render_human_report(result)


def test_machine_report_rejects_a_foreign_manifest(cap_chain, task_chain):
    result, _ = _cap_loaded(cap_chain)
    foreign_manifest = load_evaluation_output_manifest_v2(
        task_chain.plan.eval_run_id, eval_root=task_chain.eval_root,
        stage_profile_registry=load_stage_profile_registry(
            "stage_profile_registry.json", eval_root=task_chain.governed))
    with pytest.raises(ValueError, match="eval_run_id"):
        build_machine_report(result, foreign_manifest)


def test_persisted_machine_report_bytes_are_canonical(cap_chain):
    raw = (cap_chain.run_dir / "reports/machine_evaluation_report.json").read_bytes()
    payload = json.loads(raw)
    model = MachineEvaluationReport.model_validate(payload)
    assert raw == canonical_contract_bytes(
        model.model_dump(mode="json", exclude_unset=True)) + b"\n"
    assert None not in payload.values()  # optional fields are omit-or-non-null
    assert payload["result_sha256"] == cap_chain.summary.result_sha256
    assert payload["output_manifest_sha256"] == cap_chain.summary.output_manifest_sha256


def test_machine_report_without_manifest_omits_optional_fields(cap_chain):
    result, _ = _cap_loaded(cap_chain)
    report = build_machine_report(result, None)
    dumped = report.model_dump(mode="json", exclude_unset=True)
    assert "output_manifest_reference" not in dumped
    assert "output_manifest_sha256" not in dumped
    with pytest.raises(PydanticValidationError, match="explicit JSON null"):
        MachineEvaluationReport.model_validate(
            {**dumped, "output_manifest_reference": None,
             "output_manifest_sha256": None})
    with pytest.raises(PydanticValidationError, match="supplied together"):
        MachineEvaluationReport.model_validate(
            {**dumped, "output_manifest_sha256": "a" * 64})


def test_human_report_render_is_deterministic(cap_chain):
    result, manifest = _cap_loaded(cap_chain)
    report = build_machine_report(result, manifest)
    text = render_human_report(report)
    assert text == render_human_report(report)
    persisted = (cap_chain.run_dir / "reports/human_evaluation_report.md").read_text()
    assert persisted == text
    assert "- Gate verdict: pass" in text
    assert text.endswith("\n")


def test_report_persistence_is_write_once(cap_chain):
    result, manifest = _cap_loaded(cap_chain)
    report = build_machine_report(result, manifest)
    with pytest.raises(report_mod._ReportWriteError, match="write-once"):
        persist_evaluation_reports(
            report, render_human_report(report),
            eval_root=cap_chain.eval_root, eval_run_id=cap_chain.plan.eval_run_id)


def test_report_partial_write_never_repairs_or_retries(cap_chain, tmp_path):
    result, manifest = _cap_loaded(cap_chain)
    report = build_machine_report(result, manifest)
    human = render_human_report(report)
    run_dir = tmp_path / cap_chain.plan.eval_run_id
    (run_dir / "reports").mkdir(parents=True)
    blocker = run_dir / "reports" / "human_evaluation_report.md"
    blocker.write_bytes(b"pre-existing\n")
    with pytest.raises(report_mod._ReportWriteError, match="write-once"):
        persist_evaluation_reports(
            report, human, eval_root=tmp_path,
            eval_run_id=cap_chain.plan.eval_run_id)
    machine_path = run_dir / "reports" / "machine_evaluation_report.json"
    assert machine_path.is_file()  # first file landed before the collision
    assert blocker.read_bytes() == b"pre-existing\n"  # never repaired
    with pytest.raises(report_mod._ReportWriteError, match="write-once"):
        persist_evaluation_reports(
            report, human, eval_root=tmp_path,
            eval_run_id=cap_chain.plan.eval_run_id)  # never retried over files


def test_persist_reports_rejects_bad_inputs(cap_chain, tmp_path):
    result, manifest = _cap_loaded(cap_chain)
    report = build_machine_report(result, manifest)
    (tmp_path / cap_chain.plan.eval_run_id).mkdir()
    with pytest.raises(TypeError):
        persist_evaluation_reports(
            {"x": 1}, "text", eval_root=tmp_path,
            eval_run_id=cap_chain.plan.eval_run_id)
    with pytest.raises(TypeError):
        persist_evaluation_reports(
            report, b"bytes", eval_root=tmp_path,
            eval_run_id=cap_chain.plan.eval_run_id)
    with pytest.raises(ValueError, match="non-empty"):
        persist_evaluation_reports(
            report, "   ", eval_root=tmp_path,
            eval_run_id=cap_chain.plan.eval_run_id)
    with pytest.raises(ValueError, match="strictly UTF-8"):
        persist_evaluation_reports(
            report, "bad \udc80 surrogate", eval_root=tmp_path,
            eval_run_id=cap_chain.plan.eval_run_id)
    with pytest.raises(ValueError, match="eval_run_id"):
        persist_evaluation_reports(
            report, "text", eval_root=tmp_path, eval_run_id="other-run")


def test_report_hashes_never_enter_governed_artifacts(cap_chain):
    run = cap_chain.run_dir
    machine_sha = sha256_bytes(
        (run / "reports/machine_evaluation_report.json").read_bytes())
    human_sha = sha256_bytes(
        (run / "reports/human_evaluation_report.md").read_bytes())
    for governed_rel in ("evaluation_run_manifest.json",
                         "output_manifest/evaluation_output_manifest.json",
                         "results/evaluation_result.json"):
        text = (run / governed_rel).read_text()
        assert machine_sha not in text, governed_rel
        assert human_sha not in text, governed_rel


# --- Hygiene and public surface ---------------------------------------------


def test_runner_and_report_read_no_clock_git_provider_or_network():
    for module_path in (Path(runner_mod.__file__), Path(report_mod.__file__)):
        source = module_path.read_text()
        for forbidden in ("datetime", "time.time", "utcnow", "subprocess",
                          "requests", "urllib", "socket", "random",
                          "_STAGE_STATIC_ANCHORS"):
            assert forbidden not in source, (module_path.name, forbidden)


def test_public_surface_exactly_nine_new_names():
    for name in _NINE_EXPORTS:
        assert name in evaluation_pkg.__all__, name
        assert evaluation_pkg.__all__.count(name) == 1
    assert "PlannedArtifactRole" not in evaluation_pkg.__all__
    assert "PlannedArtifactRole" not in runner_mod.__all__  # internal alias only
    assert len(evaluation_pkg.__all__) == 579
    assert evaluation_pkg.__all__ == sorted(evaluation_pkg.__all__)
    assert len(set(evaluation_pkg.__all__)) == len(evaluation_pkg.__all__)
    assert isinstance(PlannedArtifactReference.model_fields, dict)


def test_repo_manifest_lists_the_three_new_paths_once():
    import re
    text = (ROOT / "REPO_MANIFEST.md").read_text(encoding="utf-8")
    declared = int(re.search(r"listed:\s*\*\*(\d+)\*\*", text).group(1))
    paths = re.findall(r"^- `([^`]+)`$", text, flags=re.MULTILINE)
    # 575 = 561 + the fourteen ADR-043 paths: three schemas, five source
    # modules and six test modules.
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
    assert declared == len(paths) == 715
    for path in ("src/dynamic_ai_products/evaluation/runner.py",
                 "src/dynamic_ai_products/evaluation/report.py",
                 "tests/evaluation/test_runner.py"):
        assert paths.count(path) == 1, path
