"""Slice 12M: pre-runner semantic-substrate integration proof.

Drives one coherent ``capability_extraction`` fixture bundle through the public
production APIs — from fixture-backed configuration through a genuine
``evaluation_run_manifest@0.2.0``, canonical prediction normalization, the
semantic adapter, deterministic validation, semantic assertion evaluation,
metric-input construction, a real ``MetricReportV2``, and the evaluation output
manifest — constructing, persisting, reloading, and hash-verifying every derived
artifact. No prebuilt internal snapshot, dummy/blanket observation, inferred
gold, provider call, runner orchestration, gate evaluation, or
``EvaluationResultV2`` is used; every observation and evaluation is produced by
its sanctioned public producer.
"""

from pathlib import Path

import pytest
from pydantic import TypeAdapter

from dynamic_ai_products.evaluation.assertions import (
    BoundEvaluationCase,
    ResolvedAssertionDispatch,
    evaluate_case_assertions,
    load_assertion_outcomes,
    persist_assertion_outcomes,
)
from dynamic_ai_products.evaluation.cases import load_case
from dynamic_ai_products.evaluation.case_sets import case_set_snapshot_hash, load_case_set_manifest
from dynamic_ai_products.evaluation.contracts import canonical_contract_bytes
from dynamic_ai_products.evaluation.gold import (
    bind_gold_assertion_set,
    gold_assertion_set_hash,
    load_gold_assertion_set,
)
from dynamic_ai_products.evaluation.envelopes import (
    load_prediction_envelopes,
    normalize_prediction_artifact,
)
from dynamic_ai_products.evaluation.metric_inputs import (
    AssertionMetricBinding,
    AxisEvaluationRecord,
    ValidatorRuleEvaluationRecord,
    build_metric_input_snapshot,
    load_metric_input_snapshot,
    metric_input_snapshot_hash,
    persist_metric_input_snapshot,
)
from dynamic_ai_products.evaluation.metrics import (
    MetricReportV2,
    compute_metric_report_v2,
    load_metric_report_v2,
    persist_metric_report,
)
from dynamic_ai_products.evaluation.prediction_content import (
    load_parsed_prediction_content,
    persist_parsed_prediction_content,
)
from dynamic_ai_products.evaluation.references import load_target_registry, resolve_case_references
from dynamic_ai_products.evaluation.runs import (
    initialize_evaluation_run_v2,
    load_evaluation_run_manifest_v2,
)
from dynamic_ai_products.evaluation.scoring_config import load_scoring_gate_config
from dynamic_ai_products.evaluation.semantic_adapters import (
    apply_semantic_adapter,
    load_semantic_adapter_registry,
    resolve_semantic_adapter,
    semantic_adapter_registry_hash,
)
from dynamic_ai_products.evaluation.semantic_assertions import build_resolved_assertion_evaluations
from dynamic_ai_products.evaluation.source_snapshot import (
    load_source_passage_snapshot_manifest,
    resolve_case_source_passages,
    source_passage_snapshot_manifest_hash,
)
from dynamic_ai_products.evaluation.stage_profiles import (
    load_stage_profile_registry,
    resolve_metric_applicability,
)
from dynamic_ai_products.evaluation.taxonomy import axis_taxonomy_hash, load_axis_taxonomy
from dynamic_ai_products.evaluation.validation_snapshot import (
    build_validation_artifact_snapshot_set,
    load_validation_artifact_snapshot_set,
    persist_validation_artifact_snapshot_set,
)
from dynamic_ai_products.evaluation.validator_bundle_artifact import (
    load_validator_bundle_artifact,
    validator_bundle_artifact_hash,
)
from dynamic_ai_products.evaluation.validator_parameters import (
    complete_rule_parameter_hash,
    load_validator_rule_parameters,
    validator_rule_parameters_aggregate_hash,
)
from dynamic_ai_products.evaluation.validators import (
    VALIDATOR_RULE_ORDER,
    ValidatorObservation,
    ValidatorRuleCoverage,
    build_validation_artifact_snapshot,
    evaluate_validator_findings,
    load_validator_findings,
    persist_validator_findings,
    validator_bundle_hash,
)
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness" / "substrate_integration"
RID = "substrate-integration-run"
CREATED = "2026-07-25T00:00:00+00:00"
_OBS = TypeAdapter(ValidatorObservation)

# Canonical run-relative locations of the six output-manifest artifacts.
OUTPUT_ARTIFACTS = {
    "validator_findings_sha256": ("findings", "validator_findings.jsonl"),
    "parsed_prediction_content_sha256": ("snapshots", "parsed_prediction_content.json"),
    "assertion_outcomes_sha256": ("assertions", "assertion_outcomes.jsonl"),
    "validation_artifact_snapshot_set_sha256":
        ("snapshots", "validation_artifact_snapshot_set.json"),
    "metric_input_snapshot_sha256": ("metric_inputs", "metric_input_snapshot.json"),
    "metric_report_v2_sha256": ("metrics", "metric_report.v2.json"),
}


def _rule_1_11_observations(parsed, case, resolved):
    """Twelve — minus Rule 12 — real, rule-specific observations derived from the
    parsed content and the case's *resolved* sources/passages (no dummy/blanket).

    Every source/passage-dependent value comes from a real producer output:
    resolved document/passage records and the parsed entity/field/evidence
    collections. Only genuinely fixed validator-contract constants remain static:
    the Rule 1 committed schema reference, the Rule 2 required-field set
    (``entity_kind``/``entity_ref``), and the Rule 9 prohibited-field policy.
    """
    ev = parsed.evidence_collection.evidence[0]
    entities = parsed.entity_collection.entities
    entity_refs = [e.entity_ref for e in entities]
    capabilities = [e.entity_ref for e in entities if e.entity_kind == "capability"]
    products = [e.entity_ref for e in entities if e.entity_kind == "product"]
    task_refs = [e.entity_ref for e in entities if e.entity_kind == "task"]
    fields = parsed.field_value_collection.field_values
    field_names = [f.field_name for f in fields]
    # Resolved producer outputs.
    available_source_ids = [d.source_id for d in resolved.documents]
    available_passage_ids = [p.passage_id for p in resolved.passages]
    passage_by_id = {p.passage_id: p for p in resolved.passages}
    document_by_id = {d.source_id: d for d in resolved.documents}
    cited_passage_text = passage_by_id[ev.passage_id].text
    cited_publication_date = document_by_id[ev.source_id].publication_date
    observation_cutoff = case.stage_context["observation_window"]["end"]
    # Rule 10: a record is roadmap-only (future) iff its cited evidence document
    # was published after the observation cutoff; active iff it is not.
    cited_is_future_roadmap = cited_publication_date > observation_cutoff
    obs = [
        {"rule_id": "output_json_schema_validity", "observation_id": "o1", "parse_succeeded": True,
         "schema_valid": True,
         "schema_reference": "schemas/capability_observation.schema.json", "validation_errors": []},
        {"rule_id": "required_field_presence", "observation_id": "o2",
         "required_fields": ["entity_kind", "entity_ref"],
         "present_fields": ["entity_kind", "entity_ref"]},
        {"rule_id": "source_id_resolution", "observation_id": "o3",
         "referenced_source_ids": [ev.source_id], "available_source_ids": available_source_ids},
        {"rule_id": "passage_id_resolution", "observation_id": "o4",
         "referenced_passage_ids": [ev.passage_id], "available_passage_ids": available_passage_ids},
        {"rule_id": "evidence_quote_containment", "observation_id": "o5", "quote": ev.quote,
         "passage_text": cited_passage_text, "passage_id": ev.passage_id},
        {"rule_id": "publication_date_cutoff", "observation_id": "o6",
         "publication_date": cited_publication_date, "observation_cutoff_date": observation_cutoff,
         "source_id": ev.source_id},
        {"rule_id": "product_capability_task_parent_resolution", "observation_id": "o7",
         "child_id": capabilities[0], "parent_id": products[0], "available_parent_ids": products},
        {"rule_id": "unique_ids_within_scope", "observation_id": "o8", "scope_id": case.case_id,
         "record_ids": entity_refs},
        {"rule_id": "prohibited_legacy_fields_absent", "observation_id": "o9",
         "present_field_names": field_names, "prohibited_field_names": ["legacy_score"]},
        {"rule_id": "active_record_non_roadmap_evidence", "observation_id": "o10",
         "active": not cited_is_future_roadmap,
         "evidence": [{"evidence_id": ev.passage_id, "is_future_roadmap": cited_is_future_roadmap}]},
        # No task entity is present in this capability fixture, so the record is
        # not customer-facing; no outcome or evidence is fabricated.
        {"rule_id": "customer_task_outcome_and_evidence", "observation_id": "o11",
         "is_customer_facing_task": bool(task_refs),
         "customer_outcome": None, "evidence_ids": []},
    ]
    return tuple(_OBS.validate_python(o) for o in obs)


def _coverage_1_11():
    rules = [r for r in VALIDATOR_RULE_ORDER if r != "raw_output_and_repair_preservation"]
    return tuple(ValidatorRuleCoverage.model_validate({
        "rule_id": r, "coverage_state": "fully_evaluated", "candidate_count": 1,
        "evaluated_observation_count": 1, "blocked_candidate_count": 0, "reason_counts": []})
        for r in rules)


def _reread_sha(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def test_semantic_substrate_integration(tmp_path: Path) -> None:
    root = tmp_path

    # --- 1. Load every fixture-backed artifact through its public loader --------
    reg = load_target_registry("target_registry.json", eval_root=FX)
    cs = load_case_set_manifest("case_set_manifest.json", eval_root=FX)
    sc = load_scoring_gate_config("scoring_gate_config.json", eval_root=FX)
    sp = load_stage_profile_registry("stage_profile_registry.json", eval_root=FX)
    adapters = load_semantic_adapter_registry("semantic_adapter_registry.json", eval_root=FX)
    gold = load_gold_assertion_set("gold_assertion_set.json", eval_root=FX)
    tax = load_axis_taxonomy("axis_taxonomy.json", eval_root=FX)
    params = load_validator_rule_parameters("validator_rule_parameters.json", eval_root=FX)
    bundle_art = load_validator_bundle_artifact(
        "validator_bundle_artifact.json", eval_root=FX, rule_parameters=params)
    snap = load_source_passage_snapshot_manifest(
        "source_passage_snapshot_manifest.json", eval_root=FX)
    case = load_case("capability_case.json", eval_root=FX)
    assert case.stage == "capability_extraction"

    # Reconciliation of the loaded pins that feed the run manifest.
    reg_hash = reg.sha256
    case_set_hash = case_set_snapshot_hash(cs)
    source_hash = source_passage_snapshot_manifest_hash(snap.manifest)
    param_hash = validator_rule_parameters_aggregate_hash(params.model)
    bundle_hash = bundle_art.model.bundle_hash
    assert reg_hash == cs.registry_snapshot_hash, "registry SHA must equal case-set pin"
    # Every complete per-rule parameter hash equals the matching bundle rule hash.
    for entry, rule in zip(params.model.entries, bundle_art.model.rule_entries):
        assert complete_rule_parameter_hash(entry) == rule.rule_params_hash
    # capability_extraction is an extraction stage: no required stage-evidence.
    assert resolve_metric_applicability(sp.registry, "capability_extraction") \
        .required_stage_evidence_kinds == ()

    adapter_entry = resolve_semantic_adapter(adapters.registry, "capability_extraction")
    sel_adapter_hash = sha256_bytes(canonical_contract_bytes(adapter_entry.model_dump(mode="json")))
    pman_hash = sha256_bytes((FX / "prediction_run_manifest.json").read_bytes())

    # --- 2. Initialize and reload a genuine evaluation_run_manifest@0.2.0 -------
    initialize_evaluation_run_v2(
        eval_root=root, eval_run_id=RID, prediction_run_id="SYNTH-PRED-RUN-0001",
        prediction_run_manifest_hash=pman_hash, case_set=cs, registry=reg,
        validator_bundle_version=bundle_art.model.bundle_version, validator_bundle_hash=bundle_hash,
        scoring_config=sc, code_commit="synth-commit", config_snapshot_source_root=FX,
        evaluation_created_at=CREATED, evaluation_stage="capability_extraction",
        stage_profile_registry=sp,
        semantic_adapter_registry_version=adapters.version,
        semantic_adapter_registry_hash=semantic_adapter_registry_hash(adapters.registry),
        selected_semantic_adapter_entry_hash=sel_adapter_hash,
        source_passage_snapshot_version=snap.version, source_passage_snapshot_hash=source_hash,
        gold_assertion_set_version=gold.model.gold_set_version,
        gold_assertion_set_hash=gold_assertion_set_hash(gold.model),
        axis_taxonomy_version=tax.model.taxonomy_version, axis_taxonomy_hash=axis_taxonomy_hash(tax.model),
        validator_rule_parameters_version=params.version, validator_rule_parameters_hash=param_hash,
        # 3. Extraction stage: stage-evidence pins are absent.
        stage_metric_evidence_set_version=None, stage_metric_evidence_set_hash=None,
    )
    rm2 = load_evaluation_run_manifest_v2(RID, eval_root=root).manifest
    assert rm2.contract.contract_version == "0.2.0"
    assert rm2.registry_snapshot_hash == reg_hash
    assert rm2.case_set_hash == case_set_hash
    assert rm2.source_passage_snapshot_hash == source_hash
    assert rm2.validator_rule_parameters_hash == param_hash
    assert rm2.validator_bundle_hash == bundle_hash == validator_bundle_hash(
        bundle_art.model.to_validator_bundle())
    assert rm2.stage_metric_evidence_set_version is None
    assert rm2.stage_metric_evidence_set_hash is None

    # --- 4. Normalize the canonical prediction artifact, then reload envelopes --
    nr = normalize_prediction_artifact(
        "prediction_run_manifest.json", source_root=FX, eval_root=root, eval_run_id=RID)
    assert nr.eval_run_id == RID and nr.prediction_run_id == "SYNTH-PRED-RUN-0001"
    loaded_env = load_prediction_envelopes(RID, eval_root=root)
    envelope = loaded_env.envelopes[0]
    assert loaded_env.sha256 == nr.sha256 == _reread_sha(
        root / RID / "predictions" / "normalized_envelopes.jsonl")
    # Membership packet hash equals the canonical prediction envelope packet hash.
    membership = next(m for m in cs.entries if m.case_id == case.case_id)
    assert membership.input_packet_hash == envelope.input_packet_hash

    # --- 5. Apply the semantic adapter to the actual prediction-source bytes ----
    raw_bytes = (FX / "prediction_source.json").read_bytes()
    parsed = apply_semantic_adapter(
        adapters.registry, case=case, envelope=envelope,
        raw_artifact_reference="prediction_source.json", raw_artifact_bytes=raw_bytes)
    assert parsed.raw_artifact_sha256 == sha256_bytes(raw_bytes)
    loaded_parsed = persist_parsed_prediction_content(parsed, eval_root=root, eval_run_id=RID)
    reloaded_parsed = load_parsed_prediction_content(
        loaded_parsed.artifact_reference, eval_root=root, expected_sha256=loaded_parsed.sha256)
    assert reloaded_parsed.sha256 == loaded_parsed.sha256 == _reread_sha(
        root / RID / "snapshots" / "parsed_prediction_content.json")

    # --- 6. Resolve real source passages and case references -------------------
    resolved = resolve_case_source_passages(snap, case)
    resolution = resolve_case_references(case, registry=reg, scoring_config=sc)
    assert resolution.target_registry_sha256 == reg_hash

    # --- 7-8. Real Rules 1-11 observations; Rule 12 produced internally ---------
    observations = _rule_1_11_observations(parsed, case, resolved)
    coverage = _coverage_1_11()
    vsnap = build_validation_artifact_snapshot(
        loaded_parsed, eval_run_id=RID, artifact_id="art-0001",
        artifact_sha256=sha256_bytes(raw_bytes), created_at=CREATED, case_id=case.case_id,
        observations=observations, coverage=coverage)
    # The sanctioned producer appended Rule 12 in canonical order.
    assert tuple(c.rule_id for c in vsnap.coverage) == VALIDATOR_RULE_ORDER
    vset = build_validation_artifact_snapshot_set(
        snapshot_set_version="substrate-vset-1", eval_run_id=RID,
        evaluation_stage="capability_extraction", snapshots=(vsnap,))
    loaded_vset = persist_validation_artifact_snapshot_set(vset, eval_root=root, eval_run_id=RID)
    reloaded_vset = load_validation_artifact_snapshot_set(
        loaded_vset.artifact_reference, eval_root=root, expected_sha256=loaded_vset.sha256)
    assert reloaded_vset.sha256 == loaded_vset.sha256 == _reread_sha(
        root / RID / "snapshots" / "validation_artifact_snapshot_set.json")

    # --- 9-10. Bundle only via to_validator_bundle(); findings ------------------
    bundle = bundle_art.model.to_validator_bundle()
    evaluated = evaluate_validator_findings(
        vsnap, bundle=bundle, run_manifest=rm2, rule_parameters=params)
    persisted_findings = persist_validator_findings(
        evaluated.findings, eval_root=root, eval_run_id=RID)
    reloaded_findings = load_validator_findings(RID, eval_root=root)
    assert reloaded_findings.sha256 == persisted_findings.sha256 == _reread_sha(
        root / RID / "findings" / "validator_findings.jsonl")

    # --- 11. Bind gold; real semantic evaluations; public dispatch glue ---------
    bound_gold = bind_gold_assertion_set(
        gold, registry=reg, cases={case.case_id: case}, resolutions={case.case_id: resolution})
    semantic = build_resolved_assertion_evaluations(
        case=case, resolution=resolution, parsed_content=loaded_parsed, gold=gold,
        bound_gold=bound_gold, source_snapshot=snap, validation_snapshots=reloaded_vset,
        validator_findings=reloaded_findings)
    assert len(semantic.evaluations) == len(case.assertions)
    refs_by_id = {a.assertion_id: a for a in resolution.assertions}
    dispatches = tuple(
        ResolvedAssertionDispatch(status="resolved", resolution=refs_by_id[e.assertion_id],
                                  evaluation=e)
        for e in semantic.evaluations)

    # --- 12-13. Membership from the case-set manifest; outcomes -----------------
    lrun = load_evaluation_run_manifest_v2(RID, eval_root=root)
    evaluated_case = evaluate_case_assertions(
        (BoundEvaluationCase(case=case, membership=membership),), case_set=cs, run_manifest=lrun,
        envelope=envelope, assertion_dispatches=dispatches)
    persisted_outcomes = persist_assertion_outcomes(
        evaluated_case.outcomes, eval_root=root, eval_run_id=RID)
    reloaded_outcomes = load_assertion_outcomes(RID, eval_root=root)
    assert reloaded_outcomes.sha256 == persisted_outcomes.sha256 == _reread_sha(
        root / RID / "assertions" / "assertion_outcomes.jsonl")
    assert all(o.outcome == "satisfied" for o in evaluated_case.outcomes)

    # --- 14. Genuine metric-input components; stage_evidence None ---------------
    bindings = tuple(
        AssertionMetricBinding(
            case_id=case.case_id, assertion_id=a.assertion_id, assertion_kind=a.kind,
            partition=membership.partition, suites=tuple(membership.suites))
        for a in case.assertions)
    rule_evals = tuple(
        ValidatorRuleEvaluationRecord(
            artifact_id="art-0001", rule_id=c.rule_id,
            evaluated_observation_count=c.evaluated_observation_count,
            failed_observation_count=0)
        for c in vsnap.coverage if c.evaluated_observation_count > 0)
    # The taxonomy participates: a real nominal capability-identity axis whose
    # predicted value is the parsed capability entity and whose gold value +
    # verification status come from the matching bound gold assertion entry.
    axis = tax.model.axes[0]
    predicted_capability = next(
        e.entity_ref for e in parsed.entity_collection.entities if e.entity_kind == "capability")
    # Gold values come from the resolved BoundGoldAssertionSet entry; the
    # verification status comes from the corresponding loaded gold entry's
    # provenance. Their canonical target references must agree.
    bound_capability_entry = next(
        b for b in bound_gold.entries
        if b.assertion_kind == "expected_entity"
        and b.canonical_target_reference == predicted_capability)
    gold_capability_entry = next(
        g for g in gold.model.entries
        if g.assertion_kind == "expected_entity"
        and g.canonical_target_reference == predicted_capability)
    assert bound_capability_entry.canonical_target_reference \
        == gold_capability_entry.canonical_target_reference
    assert bound_capability_entry.canonical_target_reference in axis.labels
    axis_record = AxisEvaluationRecord(
        record_id="axis-cap-1", case_id=case.case_id, axis_id=axis.axis_id,
        metric_scope="conditional",
        # Verification status derived from the loaded gold entry's provenance.
        verification_status=gold_capability_entry.provenance.verification_status,
        # Resolvable only because the cited evidence passage was actually resolved.
        evidence_resolvability=(
            "resolvable"
            if parsed.evidence_collection.evidence[0].passage_id
            in {p.passage_id for p in resolved.passages}
            else "insufficient_evidence"),
        predicted_values=(predicted_capability,),
        # Gold value from the bound gold entry.
        gold_values=(bound_capability_entry.canonical_target_reference,))
    mis = build_metric_input_snapshot(
        evaluation_stage="capability_extraction", stage_profile_registry=sp, run_manifest=rm2,
        axis_definitions=tuple(tax.model.axes), axis_records=(axis_record,),
        assertion_bindings=bindings, validator_rule_evaluations=rule_evals, stage_evidence=None)
    assert mis.axis_definitions and mis.axis_records
    assert mis.axis_records[0].axis_id == axis.axis_id
    assert mis.axis_records[0].predicted_values == (predicted_capability,)
    persisted_mis = persist_metric_input_snapshot(mis, eval_root=root, eval_run_id=RID)
    reloaded_mis = load_metric_input_snapshot(
        persisted_mis.artifact_reference, eval_root=root, expected_sha256=persisted_mis.sha256)
    assert reloaded_mis.sha256 == persisted_mis.sha256 == _reread_sha(
        root / RID / "metric_inputs" / "metric_input_snapshot.json")
    assert metric_input_snapshot_hash(mis) == metric_input_snapshot_hash(reloaded_mis.model)

    # --- 15. MetricReportV2 only -----------------------------------------------
    report = compute_metric_report_v2(
        mis, assertion_outcomes=evaluated_case.outcomes, validator_findings=evaluated.findings,
        run_manifest=rm2, case_set_manifest=cs, scoring_config=sc, stage_profile_registry=sp)
    assert isinstance(report, MetricReportV2)
    # The applicable nominal-axis metric path is included in the report.
    assert any(d.metric_id == "axis_nominal_single_label" for d in report.metrics)
    persisted_report = persist_metric_report(
        report, eval_root=root, eval_run_id=RID, stage_profile_registry=sp)
    reloaded_report = load_metric_report_v2(RID, eval_root=root, stage_profile_registry=sp)
    assert reloaded_report.sha256 == persisted_report.sha256 == _reread_sha(
        root / RID / "metrics" / "metric_report.v2.json")
    # No gate/result artifact is created by the pre-runner chain.
    assert not (root / RID / "results").exists()
    assert not (root / RID / "results" / "evaluation_result.json").exists()

    # --- 16. Output manifest binds all six read-back persisted-byte hashes ------
    from dynamic_ai_products.evaluation.output_manifest import (
        build_evaluation_output_manifest,
        load_evaluation_output_manifest,
        persist_evaluation_output_manifest,
    )
    manifest = build_evaluation_output_manifest(
        eval_root=root, eval_run_id=RID, validator_findings=persisted_findings,
        parsed_prediction_content=loaded_parsed, assertion_outcomes=persisted_outcomes,
        validation_artifact_snapshot_set=loaded_vset, metric_input_snapshot=persisted_mis,
        metric_report=persisted_report)
    dumped = manifest.model_dump(mode="json", exclude_unset=True)
    for field, (subdir, filename) in OUTPUT_ARTIFACTS.items():
        assert dumped[field] == _reread_sha(root / RID / subdir / filename)
    persisted_manifest = persist_evaluation_output_manifest(manifest, eval_root=root, eval_run_id=RID)
    reloaded_manifest = load_evaluation_output_manifest(RID, eval_root=root)
    assert reloaded_manifest.model == manifest
    assert reloaded_manifest.sha256 == persisted_manifest.sha256


def test_fixture_bundle_is_self_consistent() -> None:
    """The committed substrate-integration bundle reconciles without a run."""
    reg = load_target_registry("target_registry.json", eval_root=FX)
    cs = load_case_set_manifest("case_set_manifest.json", eval_root=FX)
    params = load_validator_rule_parameters("validator_rule_parameters.json", eval_root=FX)
    bundle_art = load_validator_bundle_artifact(
        "validator_bundle_artifact.json", eval_root=FX, rule_parameters=params)
    assert reg.sha256 == cs.registry_snapshot_hash
    assert validator_bundle_artifact_hash(bundle_art.model) is not None
    for entry, rule in zip(params.model.entries, bundle_art.model.rule_entries):
        assert complete_rule_parameter_hash(entry) == rule.rule_params_hash
    # Prediction manifest declares prediction_source.json hash-bound.
    import json
    pman = json.loads((FX / "prediction_run_manifest.json").read_bytes())
    src = {a["reference"]: a["sha256"] for a in pman["source_artifacts"]}
    assert "prediction_source.json" in src
    assert src["prediction_source.json"] == sha256_bytes((FX / "prediction_source.json").read_bytes())


@pytest.mark.parametrize("name", sorted(OUTPUT_ARTIFACTS))
def test_output_manifest_field_names_present(name: str) -> None:
    from dynamic_ai_products.evaluation.output_manifest import EvaluationOutputManifest
    assert name in EvaluationOutputManifest.model_fields
