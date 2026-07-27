"""Slice P2: deterministic Rules 1-11 validator-input producer.

Every case is driven from the committed substrate fixtures plus the new governed
``validator_rule_parameters@0.2.0`` / ``validator_bundle_artifact`` pair, so no
rule value is invented by the test: sources, passages, evidence, entities, parent
links, and the availability status all come from real producer output.
"""

import json
from pathlib import Path

import pytest

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import validation_inputs as vi_mod
from dynamic_ai_products.evaluation import observation_target_binding as otb_mod
from dynamic_ai_products.evaluation.case_sets import (
    case_set_snapshot_hash,
    load_case_set_manifest,
)
from dynamic_ai_products.evaluation.cases import load_case
from dynamic_ai_products.evaluation.contracts import canonical_contract_bytes
from dynamic_ai_products.evaluation.observation_target_binding import (
    build_observation_target_binding,
    persist_observation_target_binding,
)
from dynamic_ai_products.evaluation.parent_observation_snapshot import (
    ParentObservationSnapshotError,
    load_parent_observation_snapshot,
)
from dynamic_ai_products.evaluation.prediction_content import (
    load_parsed_prediction_content,
    persist_parsed_prediction_content,
)
from dynamic_ai_products.evaluation.envelopes import (
    load_prediction_envelopes,
    normalize_prediction_artifact,
)
from dynamic_ai_products.evaluation.references import (
    load_target_registry,
    resolve_case_references,
)
from dynamic_ai_products.evaluation.resolution_decisions import (
    ObservationTargetResolutionDecision,
)
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
from dynamic_ai_products.evaluation.source_snapshot import (
    load_source_passage_snapshot_manifest,
    source_passage_snapshot_manifest_hash,
)
from dynamic_ai_products.evaluation.stage_profiles import load_stage_profile_registry
from dynamic_ai_products.evaluation.validation_inputs import (
    ExtractionValidationInputs,
    build_extraction_validation_inputs,
)
from dynamic_ai_products.evaluation.validator_bundle_artifact import (
    load_validator_bundle_artifact,
)
from dynamic_ai_products.evaluation.validator_parameters import (
    load_validator_rule_parameters,
    load_validator_rule_parameters_v2,
    validator_rule_parameters_aggregate_hash,
)
from dynamic_ai_products.evaluation.validators import (
    VALIDATOR_RULE_ORDER,
    build_validation_artifact_snapshot,
)
from dynamic_ai_products.evaluation.taxonomy import axis_taxonomy_hash, load_axis_taxonomy
from dynamic_ai_products.evaluation.gold import gold_assertion_set_hash, load_gold_assertion_set
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
EFX = ROOT / "evals" / "fixtures" / "evaluation_harness"
FX = EFX / "substrate_integration"
V2_PARAMS = "validator_parameters_v2/validator_rule_parameters.v2.json"
V2_BUNDLE = "validator_bundle_v2/validator_bundle_artifact.v2.json"

RID = "p2-validation-inputs-run"
CREATED = "2026-07-27T00:00:00+00:00"
COMPANY = "SYNTH-CO-0001"
CAP_OBS = "SYNTH-CAPABILITY-OBS-0001"
PROD_OBS = "SYNTH-PRODUCT-OBS-0001"
CANON_CAP = "SYNTH.PRODUCT.ALPHA.CAPABILITY"
CANON_PROD = "SYNTH.PRODUCT.ALPHA"
STAGE = "capability_extraction"
RULES_1_11 = tuple(r for r in VALIDATOR_RULE_ORDER if r != "raw_output_and_repair_preservation")


def _resolution_decision(observation_id, kind, canonical, *, parent):
    return ObservationTargetResolutionDecision.model_validate({
        "observation_id": observation_id, "observation_kind": kind,
        "resolution_status": "resolved", "canonical_target_reference": canonical,
        "parent_referenced": parent,
        "provenance": {
            "resolution_method": "stable_identity_field",
            "source_field_name": (
                "stable_capability_id" if kind == "capability" else "product_observation_id"),
            "source_field_value": canonical,
            "registry_entry_reference_id": canonical,
            "resolver_kind": "deterministic_rule", "resolver_ids": ["p2-rule-v1"],
            "verification_status": "provisional",
            "verification_method": "deterministic_rule_review",
            "decision_timestamps": [CREATED], "change_reason": "P2 validator-input proof",
        },
    })


class _Ctx:
    """Every governed input the producer takes, assembled from real fixtures."""

    def __init__(self, root, *, raw_bytes=None, run_id=RID, force_raw_hash=False):
        self.root = root
        self.reg = load_target_registry("target_registry.json", eval_root=FX)
        self.cs = load_case_set_manifest("case_set_manifest.json", eval_root=FX)
        self.sc = load_scoring_gate_config("scoring_gate_config.json", eval_root=FX)
        self.sp = load_stage_profile_registry("stage_profile_registry.json", eval_root=FX)
        self.adapters = load_semantic_adapter_registry(
            "semantic_adapter_registry.json", eval_root=FX)
        self.gold = load_gold_assertion_set("gold_assertion_set.json", eval_root=FX)
        self.tax = load_axis_taxonomy("axis_taxonomy.json", eval_root=FX)
        self.snap = load_source_passage_snapshot_manifest(
            "source_passage_snapshot_manifest.json", eval_root=FX)
        self.case = load_case("capability_case.json", eval_root=FX)
        self.params = load_validator_rule_parameters_v2(V2_PARAMS, eval_root=EFX)
        self.bundle = load_validator_bundle_artifact(
            V2_BUNDLE, eval_root=EFX, rule_parameters=self.params)
        self.aggregate = validator_rule_parameters_aggregate_hash(self.params.model)

        adapter_entry = resolve_semantic_adapter(self.adapters.registry, STAGE)
        sel_adapter_hash = sha256_bytes(
            canonical_contract_bytes(adapter_entry.model_dump(mode="json")))
        pman_hash = sha256_bytes((FX / "prediction_run_manifest.json").read_bytes())
        initialize_evaluation_run_v2(
            eval_root=root, eval_run_id=run_id, prediction_run_id="SYNTH-PRED-RUN-0001",
            prediction_run_manifest_hash=pman_hash, case_set=self.cs, registry=self.reg,
            validator_bundle_version=self.bundle.model.bundle_version,
            validator_bundle_hash=self.bundle.model.bundle_hash,
            scoring_config=self.sc, code_commit="p2-commit",
            config_snapshot_source_root=FX, evaluation_created_at=CREATED,
            evaluation_stage=STAGE, stage_profile_registry=self.sp,
            semantic_adapter_registry_version=self.adapters.version,
            semantic_adapter_registry_hash=semantic_adapter_registry_hash(self.adapters.registry),
            selected_semantic_adapter_entry_hash=sel_adapter_hash,
            source_passage_snapshot_version=self.snap.version,
            source_passage_snapshot_hash=source_passage_snapshot_manifest_hash(self.snap.manifest),
            gold_assertion_set_version=self.gold.model.gold_set_version,
            gold_assertion_set_hash=gold_assertion_set_hash(self.gold.model),
            axis_taxonomy_version=self.tax.model.taxonomy_version,
            axis_taxonomy_hash=axis_taxonomy_hash(self.tax.model),
            validator_rule_parameters_version=self.params.model.parameter_set_version,
            validator_rule_parameters_hash=self.aggregate,
            stage_metric_evidence_set_version=None, stage_metric_evidence_set_hash=None,
        )
        self.run_manifest = load_evaluation_run_manifest_v2(run_id, eval_root=root).manifest
        assert case_set_snapshot_hash(self.cs) == self.run_manifest.case_set_hash

        normalize_prediction_artifact(
            "prediction_run_manifest.json", source_root=FX, eval_root=root, eval_run_id=run_id)
        envelope = load_prediction_envelopes(run_id, eval_root=root).envelopes[0]
        fixture_bytes = (FX / "prediction_source.json").read_bytes()
        self.raw_bytes = fixture_bytes if raw_bytes is None else raw_bytes
        adapter_bytes = fixture_bytes if force_raw_hash else self.raw_bytes
        parsed = apply_semantic_adapter(
            self.adapters.registry, case=self.case, envelope=envelope,
            raw_artifact_reference="prediction_source.json", raw_artifact_bytes=adapter_bytes)
        if force_raw_hash:
            # A schema-invalid raw document never reaches the adapter, so bind the
            # parsed content to the invalid bytes explicitly. Everything else -
            # entities, evidence, cutoff - stays real producer output.
            parsed = type(parsed).model_validate({
                **parsed.model_dump(mode="json", exclude_unset=True),
                "raw_artifact_sha256": sha256_bytes(self.raw_bytes),
            })
        self.parsed = persist_parsed_prediction_content(
            parsed, eval_root=root, eval_run_id=run_id)
        load_parsed_prediction_content(
            self.parsed.artifact_reference, eval_root=root, expected_sha256=self.parsed.sha256)

        self.parents = load_parent_observation_snapshot(
            "parent_observation_snapshot.json", source_root=FX)
        resolution = resolve_case_references(
            self.case, registry=self.reg, scoring_config=self.sc)
        binding_model = build_observation_target_binding(
            eval_run_id=run_id, case=self.case, company_id=COMPANY, resolution=resolution,
            parsed_prediction_content=self.parsed, target_registry=self.reg,
            resolution_entries=tuple(
                _resolution_decision(
                    entity.entity_ref, entity.entity_kind,
                    CANON_CAP if entity.entity_kind == "capability" else CANON_PROD,
                    parent=entity.entity_kind != "capability")
                for entity in sorted(
                    self.parsed.content.entity_collection.entities,
                    key=lambda e: e.entity_ref)),
            parent_snapshot=self.parents)
        self.binding = persist_observation_target_binding(
            binding_model, eval_root=root, eval_run_id=run_id)

        self.schema_bytes = (ROOT / "schemas" / "capability_observation.schema.json").read_bytes()

    def kwargs(self, **over):
        base = dict(
            case=self.case, evaluation_stage=STAGE, parsed_prediction_content=self.parsed,
            raw_artifact_bytes=self.raw_bytes, output_schema_bytes=self.schema_bytes,
            source_snapshot=self.snap, rule_parameters=self.params,
            validator_bundle_artifact=self.bundle, run_manifest=self.run_manifest,
            observation_target_binding=self.binding, parent_snapshot=self.parents,
        )
        base.update(over)
        return base

    def build(self, **over):
        return build_extraction_validation_inputs(**self.kwargs(**over))


@pytest.fixture
def ctx(tmp_path):
    return _Ctx(tmp_path)


def _cov(result):
    return {c.rule_id: c for c in result.coverage}


def _obs(result, rule_id):
    return [o for o in result.observations if o.rule_id == rule_id]


# --- Positive path ---------------------------------------------------------


def test_produces_rules_1_to_11_in_canonical_order(ctx):
    result = ctx.build()
    assert isinstance(result, ExtractionValidationInputs)
    assert tuple(c.rule_id for c in result.coverage) == RULES_1_11
    assert all(o.rule_id != "raw_output_and_repair_preservation" for o in result.observations)


def test_observation_ids_globally_unique_and_rule_ordered(ctx):
    result = ctx.build()
    ids = [o.observation_id for o in result.observations]
    assert len(set(ids)) == len(ids)
    order = [VALIDATOR_RULE_ORDER.index(o.rule_id) for o in result.observations]
    assert order == sorted(order)


def test_coverage_counts_match_observation_counts(ctx):
    result = ctx.build()
    cov = _cov(result)
    for rule_id in RULES_1_11:
        assert cov[rule_id].evaluated_observation_count == len(_obs(result, rule_id))


def test_provenance_fields_bind_the_verified_inputs(ctx):
    result = ctx.build()
    assert result.case_id == ctx.case.case_id
    assert result.raw_artifact_sha256 == sha256_bytes(ctx.raw_bytes)
    assert result.parsed_prediction_content_sha256 == ctx.parsed.sha256
    assert result.output_schema_sha256 == sha256_bytes(ctx.schema_bytes)
    assert result.parameter_set_version == ctx.params.model.parameter_set_version
    assert result.parameter_set_aggregate_hash == ctx.aggregate
    assert result.bundle_version == ctx.bundle.model.bundle_version
    assert result.bundle_hash == ctx.bundle.model.bundle_hash


def test_rule1_valid_raw_document_passes(ctx):
    result = ctx.build()
    rule1 = _obs(result, "output_json_schema_validity")[0]
    assert rule1.parse_succeeded is True
    assert rule1.schema_valid is True
    assert rule1.validation_errors == ()
    assert rule1.schema_reference == "schemas/capability_observation.schema.json"


def test_rule2_present_fields_come_from_raw_top_level_keys(ctx):
    result = ctx.build()
    rule2 = _obs(result, "required_field_presence")[0]
    raw = json.loads(ctx.raw_bytes)
    assert set(rule2.required_fields) <= set(raw)
    assert rule2.present_fields == tuple(sorted(rule2.required_fields))
    assert "capability_observation_id" in rule2.required_fields


def test_rule9_uses_raw_top_level_field_names(ctx):
    result = ctx.build()
    rule9 = _obs(result, "prohibited_legacy_fields_absent")[0]
    assert rule9.present_field_names == tuple(sorted(json.loads(ctx.raw_bytes)))
    assert not set(rule9.present_field_names) & set(rule9.prohibited_field_names)


def test_rules_3_4_6_derive_from_cited_evidence(ctx):
    result = ctx.build()
    evidence = ctx.parsed.content.evidence_collection.evidence
    assert len(_obs(result, "source_id_resolution")) == len({e.source_id for e in evidence})
    assert len(_obs(result, "passage_id_resolution")) == len({e.passage_id for e in evidence})
    assert len(_obs(result, "publication_date_cutoff")) == len({e.source_id for e in evidence})


def test_rule5_identity_is_the_canonical_evidence_tuple_hash(ctx):
    result = ctx.build()
    evidence = ctx.parsed.content.evidence_collection.evidence
    expected = {
        sha256_bytes(canonical_contract_bytes([e.entity_ref, e.source_id, e.passage_id, e.quote]))
        for e in evidence
    }
    got = {o.observation_id.split("-", 2)[2] for o in _obs(result, "evidence_quote_containment")}
    assert got == expected
    # No occurrence-ordinal suffix: the parsed collection already enforces uniqueness.
    assert all("#" not in o.observation_id for o in result.observations)


def test_rule8_scope_is_the_prediction_record(ctx):
    result = ctx.build()
    rule8 = _obs(result, "unique_ids_within_scope")[0]
    assert rule8.scope_id == ctx.parsed.content.prediction_record_id
    assert rule8.record_ids == tuple(
        sorted(e.entity_ref for e in ctx.parsed.content.entity_collection.entities))


def test_rule11_is_inapplicable_with_the_governed_reason(ctx):
    cov = _cov(ctx.build())["customer_task_outcome_and_evidence"]
    assert cov.coverage_state == "inapplicable"
    assert (cov.candidate_count, cov.evaluated_observation_count, cov.blocked_candidate_count) \
        == (0, 0, 0)
    assert tuple((r.reason_code, r.count) for r in cov.reason_counts) == (
        ("stage_emits_no_customer_facing_task", 1),)


def test_only_the_four_governed_coverage_states_appear(ctx):
    states = {c.coverage_state for c in ctx.build().coverage}
    assert states <= {
        "fully_evaluated", "partially_evaluated", "inapplicable", "blocked_by_dependency"}


# --- Rule 7: raw parent links ---------------------------------------------


def test_rule7_capability_yields_one_raw_product_parent_candidate(ctx):
    result = ctx.build()
    obs = _obs(result, "product_capability_task_parent_resolution")
    assert len(obs) == 1
    raw = json.loads(ctx.raw_bytes)
    assert obs[0].child_id == raw["capability_observation_id"]
    assert obs[0].parent_id == raw["product_observation_id"]
    assert obs[0].available_parent_ids == tuple(sorted(ctx.parents.product_parent_ids))
    assert obs[0].parent_id in obs[0].available_parent_ids



def _mutated(tmp_path, run_id, mutate, *, force_raw_hash=False):
    """A full context rebuilt end-to-end from a mutated raw document."""
    raw = json.loads((FX / "prediction_source.json").read_bytes())
    mutate(raw)
    return _Ctx(tmp_path, raw_bytes=canonical_contract_bytes(raw), run_id=run_id,
                force_raw_hash=force_raw_hash)


def test_rule7_role_intersection_is_all_roles_required():
    roles = {"product": frozenset({"P1", "SHARED"}),
             "capability": frozenset({"C1", "SHARED"})}
    assert vi_mod._available_parent_ids({"product"}, roles) == ("P1", "SHARED")
    assert vi_mod._available_parent_ids({"capability"}, roles) == ("C1", "SHARED")
    # A cross-role collision passes only when present in BOTH required role sets.
    assert vi_mod._available_parent_ids({"product", "capability"}, roles) == ("SHARED",)
    both = vi_mod._available_parent_ids({"product", "capability"}, roles)
    assert "P1" not in both and "C1" not in both  # never a role-blind union
    with pytest.raises(ValueError, match="at least one required role"):
        vi_mod._available_parent_ids(set(), roles)


def test_rule7_capability_parent_is_verified_against_the_snapshot_role(ctx):
    """At capability_extraction the raw product parent must resolve in the product role.

    An unknown raw product parent is unreachable end-to-end here: the binding
    builder itself rejects a parent-referenced observation absent from the parent
    snapshot, so a governed binding cannot carry one. The role-set semantics are
    covered directly by ``test_rule7_role_intersection_is_all_roles_required``;
    the un-verified raw-only path exists at task_extraction, whose capability
    parents are never binding entries, and no task substrate fixture exists.
    """
    obs = _obs(ctx.build(), "product_capability_task_parent_resolution")[0]
    assert obs.available_parent_ids == tuple(sorted(ctx.parents.product_parent_ids))
    assert obs.parent_id in obs.available_parent_ids
    assert obs.available_parent_ids != tuple(sorted(ctx.parents.capability_parent_ids))


def test_rule10_unknown_availability_status_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="governed Rule-10 active or roadmap vocabulary"):
        _mutated(tmp_path, "p2-r10-status",
                 lambda raw: raw.update({"availability_status": "not-a-governed-status"})).build()


def test_rule10_roadmap_status_yields_inactive_record(tmp_path):
    ctx = _mutated(tmp_path, "p2-r10-roadmap",
                   lambda raw: raw.update({"availability_status": "announced"}))
    result = ctx.build()
    obs = _obs(result, "active_record_non_roadmap_evidence")[0]
    assert obs.active is False
    assert _cov(result)["active_record_non_roadmap_evidence"].coverage_state == "fully_evaluated"


def _unresolve_first_source(raw):
    raw["evidence"][0]["source_id"] = "SYNTH-SRC-NOT-IN-CASE"


def test_subject_owned_unresolved_source_blocks_rule10_not_the_producer(tmp_path):
    ctx = _mutated(tmp_path, "p2-src-unresolved", _unresolve_first_source)
    result = ctx.build()
    cov = _cov(result)
    # Rule 3 still reports the citation defect as a real, evaluated observation.
    rule3 = _obs(result, "source_id_resolution")
    assert any("SYNTH-SRC-NOT-IN-CASE" in o.referenced_source_ids for o in rule3)
    bad = next(o for o in rule3 if "SYNTH-SRC-NOT-IN-CASE" in o.referenced_source_ids)
    assert "SYNTH-SRC-NOT-IN-CASE" not in bad.available_source_ids
    # Rule 10 truthfully states why it could not be evaluated.
    r10 = cov["active_record_non_roadmap_evidence"]
    assert r10.coverage_state == "blocked_by_dependency"
    assert (r10.candidate_count, r10.evaluated_observation_count, r10.blocked_candidate_count) \
        == (1, 0, 1)
    assert tuple((x.reason_code, x.count) for x in r10.reason_counts) == (
        ("blocked_source_unresolved", 1),)
    assert _obs(result, "active_record_non_roadmap_evidence") == []
    # Rule 6 blocks that one source; Rule 3 stays fully evaluated.
    assert cov["publication_date_cutoff"].blocked_candidate_count >= 1
    assert cov["source_id_resolution"].coverage_state == "fully_evaluated"


def test_schema_invalid_raw_fails_rule1_and_blocks_dependents(tmp_path):
    ctx = _mutated(tmp_path, "p2-schema-invalid",
                   lambda raw: raw.pop("confidence"), force_raw_hash=True)
    result = ctx.build()
    cov = _cov(result)
    rule1 = _obs(result, "output_json_schema_validity")[0]
    assert rule1.parse_succeeded is True
    assert rule1.schema_valid is False
    assert rule1.validation_errors  # real jsonschema errors, deterministically sorted
    assert list(rule1.validation_errors) == sorted(rule1.validation_errors)
    assert cov["output_json_schema_validity"].coverage_state == "fully_evaluated"
    expected = {
        "required_field_presence": "blocked_output_schema_invalid",
        "source_id_resolution": "blocked_output_schema_invalid",
        "passage_id_resolution": "blocked_output_schema_invalid",
        "evidence_quote_containment": "blocked_output_schema_invalid",
        "publication_date_cutoff": "blocked_output_schema_invalid",
        "unique_ids_within_scope": "blocked_output_schema_invalid",
        "prohibited_legacy_fields_absent": "blocked_output_schema_invalid",
        "product_capability_task_parent_resolution": "blocked_required_field_missing",
        "active_record_non_roadmap_evidence": "blocked_required_field_missing",
    }
    for rule_id, reason in expected.items():
        record = cov[rule_id]
        assert record.coverage_state == "blocked_by_dependency", rule_id
        assert (record.candidate_count, record.evaluated_observation_count,
                record.blocked_candidate_count) == (1, 0, 1), rule_id
        assert tuple((x.reason_code, x.count) for x in record.reason_counts) == ((reason, 1),), \
            rule_id
        assert _obs(result, rule_id) == []
    assert cov["customer_task_outcome_and_evidence"].coverage_state == "inapplicable"
    # Still a complete, snapshot-constructible coverage vector.
    snapshot = build_validation_artifact_snapshot(
        ctx.parsed, eval_run_id="p2-schema-invalid", artifact_id="art-1",
        artifact_sha256=ctx.parsed.content.raw_artifact_sha256, created_at=CREATED,
        case_id=ctx.case.case_id, observations=result.observations, coverage=result.coverage)
    assert tuple(c.rule_id for c in snapshot.coverage) == VALIDATOR_RULE_ORDER


def test_undecodable_raw_fails_parse_and_blocks_dependents(tmp_path):
    ctx = _Ctx(tmp_path, raw_bytes=b"{not json", run_id="p2-undecodable",
               force_raw_hash=True)
    result = ctx.build()
    rule1 = _obs(result, "output_json_schema_validity")[0]
    assert rule1.parse_succeeded is False
    assert rule1.schema_valid is False
    assert _cov(result)["required_field_presence"].coverage_state == "blocked_by_dependency"


# --- Rule 10 --------------------------------------------------------------


def test_rule10_active_status_and_evidence_dates(ctx):
    result = ctx.build()
    obs = _obs(result, "active_record_non_roadmap_evidence")
    assert len(obs) == 1
    assert obs[0].entity_id == CAP_OBS
    assert obs[0].active is True  # fixture availability_status "ga" is a governed active value
    assert obs[0].evidence  # subject-owned evidence classified
    assert any(c.is_future_roadmap is False for c in obs[0].evidence)
    assert _cov(result)["active_record_non_roadmap_evidence"].coverage_state == "fully_evaluated"


def test_rule10_excludes_evidence_not_owned_by_the_subject(ctx):
    result = ctx.build()
    obs = _obs(result, "active_record_non_roadmap_evidence")[0]
    owned = [e for e in ctx.parsed.content.evidence_collection.evidence
             if e.entity_ref == CAP_OBS]
    assert len(obs.evidence) == len(owned)


def test_rule6_and_rule10_are_separate_observations(ctx):
    result = ctx.build()
    assert _obs(result, "publication_date_cutoff")
    assert _obs(result, "active_record_non_roadmap_evidence")
    ids = {o.observation_id for o in result.observations}
    assert len(ids) == len(result.observations)


# --- Reconciliation and binding failures ----------------------------------


def test_v01_parameters_rejected(ctx):
    v1 = load_validator_rule_parameters(
        "validator_rule_parameters.json", eval_root=FX)
    with pytest.raises(TypeError, match="parameters_version_unsupported"):
        ctx.build(rule_parameters=v1)


def test_missing_parent_snapshot_fails_closed(ctx):
    with pytest.raises(ValueError, match="parent_snapshot is required"):
        ctx.build(parent_snapshot=None)


def test_raw_byte_hash_mismatch_fails_closed(ctx):
    with pytest.raises(ValueError, match="raw_artifact_bytes do not hash"):
        ctx.build(raw_artifact_bytes=b"{}")


def test_schema_byte_hash_mismatch_fails_closed(ctx):
    other = (ROOT / "schemas" / "task_observation.schema.json").read_bytes()
    with pytest.raises(ValueError, match="output_schema_bytes do not hash"):
        ctx.build(output_schema_bytes=other)


def test_run_manifest_parameter_pin_mismatch_fails_closed(ctx):
    bad = ctx.run_manifest.model_copy(update={"validator_rule_parameters_hash": "0" * 64})
    with pytest.raises(ValueError, match="validator_rule_parameters_hash"):
        ctx.build(run_manifest=bad)


def test_run_manifest_bundle_pin_mismatch_fails_closed(ctx):
    bad = ctx.run_manifest.model_copy(update={"validator_bundle_hash": "0" * 64})
    with pytest.raises(ValueError, match="validator_bundle_hash"):
        ctx.build(run_manifest=bad)


def test_bundle_aggregate_mismatch_fails_closed(ctx):
    bad_model = ctx.bundle.model.model_copy(
        update={"parameter_set_aggregate_hash": "0" * 64})
    bad = ctx.bundle.model_copy(update={"model": bad_model})
    with pytest.raises(ValueError, match="parameter_set_aggregate_hash"):
        ctx.build(validator_bundle_artifact=bad)


def test_wrong_stage_rejected(ctx):
    with pytest.raises(ValueError, match="governed extraction evaluation stage"):
        ctx.build(evaluation_stage="universe_screen")
    with pytest.raises(ValueError, match="parsed content stage"):
        ctx.build(evaluation_stage="task_extraction")


def test_argument_type_errors(ctx):
    with pytest.raises(TypeError, match="raw_artifact_bytes must be bytes"):
        ctx.build(raw_artifact_bytes="{}")
    with pytest.raises(TypeError, match="output_schema_bytes must be bytes"):
        ctx.build(output_schema_bytes="{}")
    with pytest.raises(TypeError, match="case must be a EvaluationCase"):
        ctx.build(case={"case_id": "x"})


# --- Cross-artifact coherence ---------------------------------------------


def test_binding_from_another_run_is_rejected(ctx):
    """Every other pin matching must not rescue a foreign binding."""
    foreign = ctx.binding.model.model_copy(update={"eval_run_id": "some-other-run"})
    wrapper = ctx.binding.model_copy(update={"model": foreign})
    assert wrapper.model.case_id == ctx.case.case_id
    assert wrapper.model.parsed_prediction_content_sha256 == ctx.parsed.sha256
    assert wrapper.model.raw_artifact_sha256 == ctx.parsed.content.raw_artifact_sha256
    with pytest.raises(ValueError, match="binding eval_run_id"):
        ctx.build(observation_target_binding=wrapper)


def test_source_snapshot_version_mismatch_is_rejected(ctx):
    bad = ctx.snap.model_copy(update={"version": "sp-not-the-pinned-version"})
    with pytest.raises(ValueError, match="source snapshot version"):
        ctx.build(source_snapshot=bad)


def test_source_snapshot_content_hash_mismatch_is_rejected(ctx):
    """Only the content pin catches a swapped snapshot.

    A different snapshot can carry the same source and passage IDs with different
    publication dates or passage text, so case-source resolution would still
    succeed while Rule 5, Rule 6, and Rule 10 outcomes silently change. The check
    compares the snapshot's canonical content hash - the identity the run recorded
    - so any content difference is rejected. Mutating the recorded pin exercises
    that comparison without fabricating an invalid snapshot.
    """
    bad_manifest = ctx.run_manifest.model_copy(
        update={"source_passage_snapshot_hash": "0" * 64})
    with pytest.raises(ValueError, match="source snapshot content hash"):
        ctx.build(run_manifest=bad_manifest)
    # The governed pair really is content-hash bound, not raw-byte bound.
    assert source_passage_snapshot_manifest_hash(ctx.snap.manifest) == \
        ctx.run_manifest.source_passage_snapshot_hash
    assert ctx.snap.sha256 != ctx.run_manifest.source_passage_snapshot_hash


def test_parent_snapshot_version_mismatch_is_rejected(ctx):
    bad = ctx.parents.model_copy(update={"version": "pos-not-the-pinned-version"})
    with pytest.raises(ValueError, match="parent snapshot version"):
        ctx.build(parent_snapshot=bad)


def test_parent_snapshot_sha_mismatch_is_rejected(ctx):
    bad = ctx.parents.model_copy(update={"sha256": "0" * 64})
    with pytest.raises(ValueError, match="parent snapshot sha256"):
        ctx.build(parent_snapshot=bad)


@pytest.mark.parametrize("field", ["case_id", "company_id", "observation_cutoff"])
def test_parent_snapshot_case_context_mismatch_is_rejected(ctx, field):
    """The pins can match while the validated parent context does not."""
    replacement = {"case_id": "SYNTH-CASE-OTHER", "company_id": "SYNTH-CO-OTHER",
                   "observation_cutoff": "2019-01-01"}[field]
    model = ctx.parents.model.model_copy(update={field: replacement})
    bad = ctx.parents.model_copy(update={"model": model})
    # Version and SHA pins still agree, so only the context check can catch this.
    assert bad.version == ctx.binding.model.parent_observation_snapshot_version
    assert bad.sha256 == ctx.binding.model.parent_observation_snapshot_sha256
    with pytest.raises(ParentObservationSnapshotError) as exc:
        ctx.build(parent_snapshot=bad)
    assert exc.value.reason_code == "case_context_mismatch"


def test_coherent_pins_are_asserted_by_the_positive_path(ctx):
    assert ctx.binding.model.eval_run_id == ctx.run_manifest.eval_run_id
    assert ctx.snap.version == ctx.run_manifest.source_passage_snapshot_version
    assert source_passage_snapshot_manifest_hash(ctx.snap.manifest) == \
        ctx.run_manifest.source_passage_snapshot_hash
    assert ctx.parents.version == ctx.binding.model.parent_observation_snapshot_version
    assert ctx.parents.sha256 == ctx.binding.model.parent_observation_snapshot_sha256
    assert ctx.build().case_id == ctx.case.case_id


# --- Rule-12 boundary -----------------------------------------------------


def test_output_feeds_the_snapshot_builder_which_owns_rule_12(ctx):
    result = ctx.build()
    snapshot = build_validation_artifact_snapshot(
        ctx.parsed, eval_run_id=RID, artifact_id="art-1",
        artifact_sha256=ctx.parsed.content.raw_artifact_sha256,
        created_at=CREATED, case_id=ctx.case.case_id,
        observations=result.observations, coverage=result.coverage,
    )
    assert tuple(c.rule_id for c in snapshot.coverage) == VALIDATOR_RULE_ORDER
    rule12 = [o for o in snapshot.observations
              if o.rule_id == "raw_output_and_repair_preservation"]
    assert len(rule12) == 1
    assert rule12[0].raw_artifact_sha256 == ctx.parsed.content.raw_artifact_sha256


def test_producer_never_emits_rule_12(ctx):
    result = ctx.build()
    assert all(c.rule_id != "raw_output_and_repair_preservation" for c in result.coverage)


# --- Local mirrors must not drift ----------------------------------------


def test_local_stage_and_role_mirrors_match_the_binding_module(ctx):
    assert vi_mod._STAGE_SUBJECT_KIND == otb_mod._STAGE_SUBJECT_KIND
    assert vi_mod._PARENT_ROLE_SNAPSHOT_FIELD == otb_mod._PARENT_KIND_FIELD


# --- Public surface ------------------------------------------------------


def test_public_surface():
    for name in ("ExtractionEvaluationStage", "ExtractionValidationInputs",
                 "build_extraction_validation_inputs"):
        assert name in evaluation_pkg.__all__
        assert evaluation_pkg.__all__.count(name) == 1
    assert len(evaluation_pkg.__all__) == 567
    assert evaluation_pkg.__all__ == sorted(evaluation_pkg.__all__)
    assert len(set(evaluation_pkg.__all__)) == len(evaluation_pkg.__all__)


def test_extraction_stage_alias_matches_the_governed_tuple():
    from typing import get_args

    from dynamic_ai_products.evaluation.resolution_decisions import (
        EXTRACTION_EVALUATION_STAGES,
    )
    assert set(get_args(vi_mod.ExtractionEvaluationStage)) == set(EXTRACTION_EVALUATION_STAGES)
