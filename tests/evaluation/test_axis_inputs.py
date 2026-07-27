"""Slice P3: deterministic axis evaluation-record producer.

Every case is driven from the committed substrate fixtures, so no axis value is
invented by the test: the axis taxonomy, the gold assertion set, the target
registry, the source snapshot, and the binding all come from real producer
output. Mutated variants are built with ``model_copy``.

Every failure assertion goes through ``pytest.raises(ValueError, match=...)`` on
the raised message; P3 defines no error class, so nothing here reads
``.reason_code`` or wraps an exception.
"""

from pathlib import Path

import pytest

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import axis_inputs as ai_mod
from dynamic_ai_products.evaluation import observation_target_binding as otb_mod
from dynamic_ai_products.evaluation.axis_inputs import (
    ExtractionAxisEvaluationInputs,
    build_extraction_axis_evaluation_records,
)
from dynamic_ai_products.evaluation.case_sets import load_case_set_manifest
from dynamic_ai_products.evaluation.cases import load_case
from dynamic_ai_products.evaluation.contracts import canonical_contract_bytes
from dynamic_ai_products.evaluation.envelopes import (
    load_prediction_envelopes,
    normalize_prediction_artifact,
)
from dynamic_ai_products.evaluation.gold import (
    GoldAssertionSetError,
    bind_gold_assertion_set,
    gold_assertion_set_hash,
    load_gold_assertion_set,
)
from dynamic_ai_products.evaluation.metric_inputs import UNKNOWN, build_metric_input_snapshot
from dynamic_ai_products.evaluation.observation_target_binding import (
    build_observation_target_binding,
    persist_observation_target_binding,
)
from dynamic_ai_products.evaluation.parent_observation_snapshot import (
    load_parent_observation_snapshot,
)
from dynamic_ai_products.evaluation.prediction_content import persist_parsed_prediction_content
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
    SourceSnapshotError,
    load_source_passage_snapshot_manifest,
    resolve_case_source_passages,
    source_passage_snapshot_manifest_hash,
)
from dynamic_ai_products.evaluation.stage_profiles import load_stage_profile_registry
from dynamic_ai_products.evaluation.taxonomy import (
    AxisTaxonomyError,
    axis_taxonomy_hash,
    load_axis_taxonomy,
)
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness" / "substrate_integration"

RID = "p3-axis-inputs-run"
CREATED = "2026-07-27T00:00:00+00:00"
COMPANY = "SYNTH-CO-0001"
CASE_ID = "SYNTH-CASE-FULL-0002"
CAP_OBS = "SYNTH-CAPABILITY-OBS-0001"
CANON_CAP = "SYNTH.PRODUCT.ALPHA.CAPABILITY"
CANON_PROD = "SYNTH.PRODUCT.ALPHA"
CANON_ROADMAP = "SYNTH.PRODUCT.ROADMAP_ONLY"
STAGE = "capability_extraction"
AXIS_ID = "overall"


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
            "resolver_kind": "deterministic_rule", "resolver_ids": ["p3-rule-v1"],
            "verification_status": "provisional",
            "verification_method": "deterministic_rule_review",
            "decision_timestamps": [CREATED], "change_reason": "P3 axis-record proof",
        },
    })


class _Ctx:
    """Every governed input the producer takes, assembled from real fixtures."""

    def __init__(self, root, *, run_id=RID):
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

        adapter_entry = resolve_semantic_adapter(self.adapters.registry, STAGE)
        sel_adapter_hash = sha256_bytes(
            canonical_contract_bytes(adapter_entry.model_dump(mode="json")))
        pman_hash = sha256_bytes((FX / "prediction_run_manifest.json").read_bytes())
        initialize_evaluation_run_v2(
            eval_root=root, eval_run_id=run_id, prediction_run_id="SYNTH-PRED-RUN-0001",
            prediction_run_manifest_hash=pman_hash, case_set=self.cs, registry=self.reg,
            validator_bundle_version="vb-1", validator_bundle_hash="b" * 64,
            scoring_config=self.sc, code_commit="p3-commit",
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
            validator_rule_parameters_version="vp-v1", validator_rule_parameters_hash="a" * 64,
            stage_metric_evidence_set_version=None, stage_metric_evidence_set_hash=None,
        )
        self.run_manifest = load_evaluation_run_manifest_v2(run_id, eval_root=root).manifest

        normalize_prediction_artifact(
            "prediction_run_manifest.json", source_root=FX, eval_root=root, eval_run_id=run_id)
        envelope = load_prediction_envelopes(run_id, eval_root=root).envelopes[0]
        raw_bytes = (FX / "prediction_source.json").read_bytes()
        parsed = apply_semantic_adapter(
            self.adapters.registry, case=self.case, envelope=envelope,
            raw_artifact_reference="prediction_source.json", raw_artifact_bytes=raw_bytes)
        self.parsed = persist_parsed_prediction_content(
            parsed, eval_root=root, eval_run_id=run_id)

        self.parents = load_parent_observation_snapshot(
            "parent_observation_snapshot.json", source_root=FX)
        self.resolution = resolve_case_references(
            self.case, registry=self.reg, scoring_config=self.sc)
        binding_model = build_observation_target_binding(
            eval_run_id=run_id, case=self.case, company_id=COMPANY, resolution=self.resolution,
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
        self.bound_gold = bind_gold_assertion_set(
            self.gold, registry=self.reg, cases={self.case.case_id: self.case},
            resolutions={self.case.case_id: self.resolution})

    def kwargs(self, **over):
        base = dict(
            case=self.case, evaluation_stage=STAGE, parsed_prediction_content=self.parsed,
            source_snapshot=self.snap, axis_taxonomy=self.tax, gold=self.gold,
            bound_gold=self.bound_gold, run_manifest=self.run_manifest,
            observation_target_binding=self.binding,
        )
        base.update(over)
        return base

    def build(self, **over):
        return build_extraction_axis_evaluation_records(**self.kwargs(**over))

    def taxonomy_with_labels(self, labels, **axis_over):
        """A taxonomy variant plus a run manifest re-pinned to it."""
        axis = self.tax.model.axes[0].model_copy(update={"labels": tuple(labels), **axis_over})
        model = self.tax.model.model_copy(update={"axes": (axis,)})
        tax = self.tax.model_copy(update={"model": model})
        manifest = self.run_manifest.model_copy(
            update={"axis_taxonomy_hash": axis_taxonomy_hash(model)})
        return tax, manifest


@pytest.fixture
def ctx(tmp_path):
    return _Ctx(tmp_path)


def _records(result):
    return list(result.axis_records)


# --- Positive path ---------------------------------------------------------


def test_positive_path(ctx):
    result = ctx.build()
    assert isinstance(result, ExtractionAxisEvaluationInputs)
    records = _records(result)
    # The committed axis lists exactly one gold-matching label.
    assert len(records) == 1
    record = records[0]
    assert record.case_id == CASE_ID
    assert record.axis_id == AXIS_ID
    assert record.metric_scope == "conditional"
    assert record.predicted_values == (CANON_CAP,)
    assert record.gold_values == (CANON_CAP,)
    assert record.verification_status == "verified"
    assert record.evidence_resolvability == "resolvable"


def test_predicted_value_is_the_subject_canonical_not_the_raw_observation_id(ctx):
    result = ctx.build()
    assert result.subject_observation_id == CAP_OBS
    assert result.subject_canonical_target_reference == CANON_CAP
    assert result.axis_records[0].predicted_values == (CANON_CAP,)
    assert CAP_OBS not in result.axis_records[0].predicted_values


def test_producer_never_uses_the_reverse_canonical_index(ctx):
    """The subject's canonical value is read from its own entry.

    ``observations_by_canonical_target`` maps canonical -> observation IDs, the
    opposite direction, and must not be consulted.
    """
    source = Path(ai_mod.__file__).read_text()
    assert "observations_by_canonical_target(" not in source
    subject = next(e for e in ctx.binding.model.entries if not e.parent_referenced)
    assert ctx.build().subject_canonical_target_reference == subject.canonical_target_reference


def test_record_id_grammar(ctx):
    record = ctx.build().axis_records[0]
    entry = next(
        e for e in ctx.bound_gold.entries
        if e.assertion_kind == "expected_entity" and e.canonical_target_reference == CANON_CAP)
    digest = sha256_bytes(canonical_contract_bytes([
        entry.case_id, entry.assertion_id, entry.assertion_semantic_version,
        entry.assertion_contract_hash, entry.assertion_kind,
        entry.canonical_target_reference, AXIS_ID,
    ]))
    assert record.record_id == f"axis~{AXIS_ID}~{digest}"
    assert len(digest) == 64  # untruncated


def test_definitions_carry_every_axis_and_ordering_is_canonical(ctx):
    result = ctx.build()
    assert tuple(a.axis_id for a in result.axis_definitions) == tuple(
        a.axis_id for a in ctx.tax.model.axes)
    keys = [(r.axis_id, r.record_id) for r in result.axis_records]
    assert keys == sorted(keys)


def test_provenance_fields_bind_verified_inputs(ctx):
    result = ctx.build()
    assert result.axis_taxonomy_version == ctx.tax.version
    assert result.axis_taxonomy_hash == axis_taxonomy_hash(ctx.tax.model)
    assert result.gold_assertion_set_version == ctx.gold.model.gold_set_version
    assert result.gold_assertion_set_hash == gold_assertion_set_hash(ctx.gold.model)
    assert result.parsed_prediction_content_sha256 == ctx.parsed.sha256
    assert result.prediction_record_id == ctx.parsed.content.prediction_record_id


def test_output_feeds_the_metric_input_snapshot(ctx):
    result = ctx.build()
    snapshot = build_metric_input_snapshot(
        evaluation_stage=STAGE, stage_profile_registry=ctx.sp,
        run_manifest=ctx.run_manifest, axis_definitions=result.axis_definitions,
        axis_records=result.axis_records)
    assert snapshot.axis_records == result.axis_records
    assert snapshot.axis_definitions == result.axis_definitions


def test_happy_path_registry_pin_equality(ctx):
    assert ctx.binding.model.target_registry_sha256 == ctx.run_manifest.registry_snapshot_hash
    assert ctx.build().case_id == CASE_ID


# --- Cross-artifact pins ---------------------------------------------------


def test_pin_1_binding_from_another_run(ctx):
    foreign = ctx.binding.model.model_copy(update={"eval_run_id": "other-run"})
    with pytest.raises(ValueError, match="binding eval_run_id"):
        ctx.build(observation_target_binding=ctx.binding.model_copy(update={"model": foreign}))


def test_pin_2_target_registry_snapshot_mismatch(ctx):
    """A binding resolved under a different target-registry snapshot is rejected.

    Every other field is preserved, so no other pin can account for the failure.
    """
    bad_model = ctx.binding.model.model_copy(update={"target_registry_sha256": "0" * 64})
    bad = ctx.binding.model_copy(update={"model": bad_model})
    assert bad.model.eval_run_id == ctx.run_manifest.eval_run_id
    assert bad.model.case_id == ctx.case.case_id
    assert bad.model.stage == STAGE
    assert bad.model.parsed_prediction_content_sha256 == ctx.parsed.sha256
    assert bad.model.raw_artifact_sha256 == ctx.parsed.content.raw_artifact_sha256
    assert bad.model.entries == ctx.binding.model.entries
    with pytest.raises(ValueError, match="target_registry_sha256"):
        ctx.build(observation_target_binding=bad)


def test_no_target_registry_version_comparison_exists(ctx):
    """The run manifest pins the registry raw-byte hash, not a registry version."""
    fields = set(type(ctx.run_manifest).model_fields)
    assert "registry_snapshot_hash" in fields
    assert "target_registry_version" not in fields
    assert "registry_version" not in fields
    # The binding does carry one, with no counterpart to compare against.
    assert ctx.binding.model.target_registry_version == ctx.reg.version
    assert ctx.run_manifest.registry_snapshot_hash == ctx.reg.sha256


def test_pin_3_taxonomy_version_mismatch(ctx):
    bad = ctx.run_manifest.model_copy(update={"axis_taxonomy_version": "ax-other"})
    with pytest.raises(ValueError, match="axis taxonomy version"):
        ctx.build(run_manifest=bad)


def test_pin_4_taxonomy_content_hash_mismatch(ctx):
    bad = ctx.run_manifest.model_copy(update={"axis_taxonomy_hash": "0" * 64})
    with pytest.raises(ValueError, match="axis taxonomy content hash"):
        ctx.build(run_manifest=bad)


def test_pin_5_gold_version_mismatch(ctx):
    bad = ctx.run_manifest.model_copy(update={"gold_assertion_set_version": "g-other"})
    with pytest.raises(ValueError, match="gold set version"):
        ctx.build(run_manifest=bad)


def test_pin_6_gold_content_hash_mismatch_and_identity_distinction(ctx):
    bad = ctx.run_manifest.model_copy(update={"gold_assertion_set_hash": "0" * 64})
    with pytest.raises(ValueError, match="gold set content hash"):
        ctx.build(run_manifest=bad)
    # Content hash and raw-byte hash are different identities.
    assert gold_assertion_set_hash(ctx.gold.model) == ctx.run_manifest.gold_assertion_set_hash
    assert ctx.gold.sha256 != ctx.run_manifest.gold_assertion_set_hash


def test_pin_7_bound_gold_version_mismatch(ctx):
    bad = ctx.bound_gold.model_copy(update={"gold_set_version": "g-other"})
    with pytest.raises(ValueError, match="bound gold set version"):
        ctx.build(bound_gold=bad)


def test_pin_8_bound_gold_raw_byte_mismatch(ctx):
    bad = ctx.bound_gold.model_copy(update={"sha256": "0" * 64})
    with pytest.raises(ValueError, match="bound gold sha256"):
        ctx.build(bound_gold=bad)


def test_pin_9_source_snapshot_version_mismatch(ctx):
    bad = ctx.snap.model_copy(update={"version": "sp-other"})
    with pytest.raises(ValueError, match="source snapshot version"):
        ctx.build(source_snapshot=bad)


def test_pin_10_source_snapshot_content_hash_mismatch(ctx):
    bad = ctx.run_manifest.model_copy(update={"source_passage_snapshot_hash": "0" * 64})
    with pytest.raises(ValueError, match="source snapshot content hash"):
        ctx.build(run_manifest=bad)


def test_pin_11_parsed_content_sha_mismatch(ctx):
    bad_model = ctx.binding.model.model_copy(
        update={"parsed_prediction_content_sha256": "0" * 64})
    with pytest.raises(ValueError, match="parsed_prediction_content_sha256"):
        ctx.build(observation_target_binding=ctx.binding.model_copy(update={"model": bad_model}))


def test_pin_12_raw_artifact_sha_mismatch(ctx):
    bad_model = ctx.binding.model.model_copy(update={"raw_artifact_sha256": "0" * 64})
    with pytest.raises(ValueError, match="raw_artifact_sha256"):
        ctx.build(observation_target_binding=ctx.binding.model_copy(update={"model": bad_model}))


def test_pin_13_case_and_stage_coherence(ctx):
    bad_model = ctx.binding.model.model_copy(update={"case_id": "SYNTH-CASE-OTHER"})
    with pytest.raises(ValueError, match="case_id does not agree"):
        ctx.build(observation_target_binding=ctx.binding.model_copy(update={"model": bad_model}))
    with pytest.raises(ValueError, match="governed extraction evaluation stage"):
        ctx.build(evaluation_stage="universe_screen")
    with pytest.raises(ValueError, match="stage does not agree"):
        ctx.build(evaluation_stage="task_extraction")


def test_argument_type_errors(ctx):
    with pytest.raises(TypeError, match="case must be a EvaluationCase"):
        ctx.build(case={"case_id": CASE_ID})
    with pytest.raises(TypeError, match="axis_taxonomy must be a LoadedAxisTaxonomy"):
        ctx.build(axis_taxonomy=object())
    with pytest.raises(TypeError, match="bound_gold must be a BoundGoldAssertionSet"):
        ctx.build(bound_gold=object())


# --- Gold eligibility ------------------------------------------------------


def test_forbidden_entity_label_produces_no_record(ctx):
    """A forbidden_entity target is a negative assertion, never a positive label."""
    tax, manifest = ctx.taxonomy_with_labels([CANON_ROADMAP, "SYNTH.PRODUCT.OTHER.CAPABILITY"])
    assert any(
        e.assertion_kind == "forbidden_entity" and e.canonical_target_reference == CANON_ROADMAP
        for e in ctx.bound_gold.entries)
    result = ctx.build(axis_taxonomy=tax, run_manifest=manifest)
    assert result.axis_records == ()
    assert len(result.axis_definitions) == 1  # definition retained


def test_gold_entry_for_another_case_produces_no_record(ctx):
    others = tuple(
        e.model_copy(update={"case_id": "SYNTH-CASE-OTHER"}) for e in ctx.bound_gold.entries)
    bad = ctx.bound_gold.model_copy(update={"entries": others})
    result = ctx.build(bound_gold=bad)
    assert result.axis_records == ()


# --- Assertion-owned identity ---------------------------------------------


def _identity_sort_key(entry):
    """Mirrors gold._entry_identity's ordering key for GoldAssertionSet sorting."""
    return (
        entry.case_id,
        entry.assertion_id,
        entry.assertion_semantic_version or "",
        entry.assertion_contract_hash or "",
        entry.canonical_target_reference,
    )


def _second_assertion_on_same_target(ctx, second_id="SYNTH-CASE-FULL-0002-A1B"):
    """A gold/bound pair holding two expected_entity assertions on one target.

    The two entries share case ID, canonical target, kind, semantic version and
    contract hash, and differ *only* in assertion_id - which is exactly the
    condition under which distinct assertions must not collapse.
    """
    loaded_src = next(
        e for e in ctx.gold.model.entries
        if e.assertion_kind == "expected_entity" and e.canonical_target_reference == CANON_CAP)
    loaded_twin = loaded_src.model_copy(update={"assertion_id": second_id})
    entries = tuple(sorted((*ctx.gold.model.entries, loaded_twin), key=_identity_sort_key))
    gold_model = ctx.gold.model.model_copy(update={"entries": entries})
    gold = ctx.gold.model_copy(update={"model": gold_model})
    manifest = ctx.run_manifest.model_copy(
        update={"gold_assertion_set_hash": gold_assertion_set_hash(gold_model)})

    bound_src = next(
        e for e in ctx.bound_gold.entries
        if e.assertion_kind == "expected_entity" and e.canonical_target_reference == CANON_CAP)
    bound_twin = bound_src.model_copy(update={"assertion_id": second_id})
    bound = ctx.bound_gold.model_copy(
        update={"entries": (*ctx.bound_gold.entries, bound_twin)})
    return gold, bound, manifest, bound_src, bound_twin


def test_two_expected_entity_assertions_stay_two_records(ctx):
    """Distinct assertion IDs never collapse, even on one canonical target.

    Both entries name the same canonical target on the same axis and differ only
    in assertion_id, so a (axis, target) key would merge them and erase one
    assertion's provenance and denominator contribution.
    """
    gold, bound, manifest, bound_src, bound_twin = _second_assertion_on_same_target(ctx)
    assert bound_src.assertion_id != bound_twin.assertion_id
    assert bound_src.canonical_target_reference == bound_twin.canonical_target_reference
    assert bound_src.assertion_kind == bound_twin.assertion_kind == "expected_entity"
    assert bound_src.case_id == bound_twin.case_id == CASE_ID
    assert bound_src.assertion_semantic_version == bound_twin.assertion_semantic_version
    assert bound_src.assertion_contract_hash == bound_twin.assertion_contract_hash

    result = ctx.build(gold=gold, bound_gold=bound, run_manifest=manifest)
    records = [r for r in result.axis_records if r.axis_id == AXIS_ID]
    # Two records, not one: the pair was not collapsed.
    assert len(records) == 2
    assert len({r.record_id for r in records}) == 2
    # Both reconciled to their own loaded gold entry, so both carry provenance.
    assert all(r.verification_status == "verified" for r in records)
    assert all(r.gold_values == (CANON_CAP,) for r in records)
    assert all(r.predicted_values == (CANON_CAP,) for r in records)
    # The record IDs differ solely because the assertion identity differs.
    expected = {
        _record_id_for(e, AXIS_ID) for e in (bound_src, bound_twin)
    }
    assert {r.record_id for r in records} == expected


def _record_id_for(entry, axis_id):
    digest = sha256_bytes(canonical_contract_bytes([
        entry.case_id, entry.assertion_id, entry.assertion_semantic_version,
        entry.assertion_contract_hash, entry.assertion_kind,
        entry.canonical_target_reference, axis_id,
    ]))
    return f"axis~{axis_id}~{digest}"


def test_two_gold_targets_on_one_axis_also_stay_separate(ctx):
    """The prior per-target behaviour is retained as a distinct case."""
    tax, manifest = ctx.taxonomy_with_labels([CANON_CAP, CANON_PROD])
    result = ctx.build(axis_taxonomy=tax, run_manifest=manifest)
    assert len(result.axis_records) == 2
    assert {r.gold_values[0] for r in result.axis_records} == {CANON_CAP, CANON_PROD}
    assert all(r.predicted_values == (CANON_CAP,) for r in result.axis_records)


def test_duplicate_bound_gold_identity_fails_closed(ctx):
    entry = next(
        e for e in ctx.bound_gold.entries
        if e.assertion_kind == "expected_entity" and e.canonical_target_reference == CANON_CAP)
    bad = ctx.bound_gold.model_copy(update={"entries": (*ctx.bound_gold.entries, entry)})
    with pytest.raises(ValueError, match="same assertion identity"):
        ctx.build(bound_gold=bad)


def test_assertion_kind_mismatch_is_not_reconciled(ctx):
    """A bound entry whose kind disagrees with the loaded set cannot reconcile."""
    entries = tuple(
        e.model_copy(update={"assertion_kind": "expected_entity"})
        if e.assertion_kind == "forbidden_entity" else e
        for e in ctx.bound_gold.entries)
    bad = ctx.bound_gold.model_copy(update={"entries": entries})
    tax, manifest = ctx.taxonomy_with_labels([CANON_CAP, CANON_ROADMAP])
    with pytest.raises(ValueError, match="exactly one loaded gold entry"):
        ctx.build(bound_gold=bad, axis_taxonomy=tax, run_manifest=manifest)


def test_unreconcilable_bound_entry_fails_closed(ctx):
    entries = tuple(
        e.model_copy(update={"assertion_id": "SYNTH-CASE-FULL-0002-A9"})
        if e.canonical_target_reference == CANON_CAP else e
        for e in ctx.bound_gold.entries)
    bad = ctx.bound_gold.model_copy(update={"entries": entries})
    with pytest.raises(ValueError, match="exactly one loaded gold entry"):
        ctx.build(bound_gold=bad)


# --- Axis vocabulary -------------------------------------------------------


def test_axis_without_eligible_gold_emits_no_record_but_keeps_its_definition(ctx):
    tax, manifest = ctx.taxonomy_with_labels(["SYNTH.PRODUCT.UNRELATED"])
    result = ctx.build(axis_taxonomy=tax, run_manifest=manifest)
    assert result.axis_records == ()
    assert len(result.axis_definitions) == 1
    snapshot = build_metric_input_snapshot(
        evaluation_stage=STAGE, stage_profile_registry=ctx.sp, run_manifest=manifest,
        axis_definitions=result.axis_definitions, axis_records=result.axis_records)
    assert snapshot.axis_records == ()


def test_resolved_subject_outside_axis_vocabulary_fails_closed(ctx):
    """Eligible gold plus an out-of-vocabulary subject must not silently skip."""
    tax, manifest = ctx.taxonomy_with_labels([CANON_PROD, "SYNTH.PRODUCT.OTHER.CAPABILITY"])
    with pytest.raises(ValueError, match="outside axis"):
        ctx.build(axis_taxonomy=tax, run_manifest=manifest)


# --- Source / evidence unresolvability -------------------------------------


def test_unresolved_cited_passage_yields_insufficient_evidence(ctx):
    """Subject-cited passage outside the case-resolved set => insufficient_evidence.

    The mutation is on the parsed content's citation, not on the snapshot: the
    case's own declared passages must still resolve, so only the prediction's
    citation is unresolvable.
    """
    evidence = ctx.parsed.content.evidence_collection.evidence
    moved = tuple(
        e.model_copy(update={"passage_id": "SYNTH-PASSAGE-NOT-IN-CASE"}) for e in evidence)
    collection = ctx.parsed.content.evidence_collection.model_copy(update={"evidence": moved})
    content = ctx.parsed.content.model_copy(update={"evidence_collection": collection})
    parsed = ctx.parsed.model_copy(update={"content": content})
    result = ctx.build(parsed_prediction_content=parsed)
    assert result.axis_records[0].evidence_resolvability == "insufficient_evidence"
    # The positive path really did resolve, so the two states are distinguishable.
    assert ctx.build().axis_records[0].evidence_resolvability == "resolvable"


def test_subject_without_evidence_is_insufficient_evidence(ctx):
    collection = ctx.parsed.content.evidence_collection.model_copy(update={"evidence": ()})
    content = ctx.parsed.content.model_copy(update={"evidence_collection": collection})
    parsed = ctx.parsed.model_copy(update={"content": content})
    result = ctx.build(parsed_prediction_content=parsed)
    assert result.axis_records[0].evidence_resolvability == "insufficient_evidence"


# --- Extraction binding ----------------------------------------------------


def test_parent_referenced_entry_never_becomes_the_subject(ctx):
    tax, manifest = ctx.taxonomy_with_labels([CANON_PROD])
    # CANON_PROD is the parent entry's canonical target and an axis label, yet it
    # must not be predicted; the subject is out of vocabulary, so this fails.
    with pytest.raises(ValueError, match="outside axis"):
        ctx.build(axis_taxonomy=tax, run_manifest=manifest)
    subject = next(e for e in ctx.binding.model.entries if not e.parent_referenced)
    assert subject.canonical_target_reference == CANON_CAP


def test_unresolved_subject_on_abstention_axis_predicts_unknown(ctx):
    entries = tuple(
        e.model_copy(update={
            "resolution_status": "unresolved", "canonical_target_reference": None,
            "provenance": e.provenance.model_copy(
                update={"resolution_method": "declared_unresolved"}),
        }) if not e.parent_referenced else e
        for e in ctx.binding.model.entries)
    bad_model = ctx.binding.model.model_copy(update={"entries": entries})
    binding = ctx.binding.model_copy(update={"model": bad_model})
    tax, manifest = ctx.taxonomy_with_labels(
        [CANON_CAP], metric_type="abstention_allowed",
        base_metric_type="nominal_single_label")
    result = ctx.build(
        observation_target_binding=binding, axis_taxonomy=tax, run_manifest=manifest)
    assert result.subject_canonical_target_reference is None
    assert result.axis_records[0].predicted_values == (UNKNOWN,)


def test_unresolved_subject_on_non_abstention_axis_fails_closed(ctx):
    entries = tuple(
        e.model_copy(update={
            "resolution_status": "unresolved", "canonical_target_reference": None,
            "provenance": e.provenance.model_copy(
                update={"resolution_method": "declared_unresolved"}),
        }) if not e.parent_referenced else e
        for e in ctx.binding.model.entries)
    bad_model = ctx.binding.model.model_copy(update={"entries": entries})
    binding = ctx.binding.model_copy(update={"model": bad_model})
    with pytest.raises(ValueError, match="does not permit UNKNOWN"):
        ctx.build(observation_target_binding=binding)


def test_binding_without_exactly_one_subject_fails_closed(ctx):
    entries = tuple(
        e.model_copy(update={"parent_referenced": True}) for e in ctx.binding.model.entries)
    bad_model = ctx.binding.model.model_copy(update={"entries": entries})
    with pytest.raises(ValueError, match="exactly one owning subject"):
        ctx.build(observation_target_binding=ctx.binding.model_copy(update={"model": bad_model}))


# --- Error boundary --------------------------------------------------------


def test_non_string_stage_is_a_type_error(ctx):
    """A non-string stage is a wrong argument type, not a content violation."""
    with pytest.raises(TypeError, match="evaluation_stage must be a str"):
        ctx.build(evaluation_stage=123)
    with pytest.raises(TypeError, match="evaluation_stage must be a str"):
        ctx.build(evaluation_stage=None)


def test_unsupported_stage_string_stays_a_value_error(ctx):
    with pytest.raises(ValueError, match="governed extraction evaluation stage") as exc:
        ctx.build(evaluation_stage="universe_screen")
    assert type(exc.value) is ValueError
    assert not hasattr(exc.value, "reason_code")


def _assert_plain_value_error(exc_info):
    """Ordinary ValueError, no reason_code, no upstream class, no chained cause."""
    assert type(exc_info.value) is ValueError
    assert not hasattr(exc_info.value, "reason_code")
    assert not isinstance(exc_info.value, (SourceSnapshotError, AxisTaxonomyError,
                                           GoldAssertionSetError))
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True


def test_case_passage_absent_from_snapshot_is_a_plain_value_error(ctx):
    """An unresolvable case-declared passage must not surface SourceSnapshotError."""
    passages = tuple(
        p.model_copy(update={"passage_id": f"{p.passage_id}-renamed"})
        for p in ctx.snap.source_passages)
    bad = ctx.snap.model_copy(update={"source_passages": passages})
    # Sanity: the underlying helper really does raise its governed error here.
    with pytest.raises(SourceSnapshotError):
        resolve_case_source_passages(bad, ctx.case)
    with pytest.raises(ValueError, match="do not resolve against") as exc:
        ctx.build(source_snapshot=bad)
    _assert_plain_value_error(exc)


def test_malformed_taxonomy_is_a_plain_value_error(ctx):
    """A taxonomy that fails governed revalidation surfaces as ordinary ValueError."""
    axes = ctx.tax.model.axes
    bad_model = ctx.tax.model.model_construct(
        **{**ctx.tax.model.__dict__, "axes": (*axes, *axes)})  # duplicate axis_id
    bad = ctx.tax.model_copy(update={"model": bad_model})
    with pytest.raises(AxisTaxonomyError):
        axis_taxonomy_hash(bad_model)
    with pytest.raises(ValueError, match="axis taxonomy failed governed revalidation") as exc:
        ctx.build(axis_taxonomy=bad)
    _assert_plain_value_error(exc)


def test_malformed_gold_is_a_plain_value_error(ctx):
    """A gold set that fails governed revalidation surfaces as ordinary ValueError."""
    entries = ctx.gold.model.entries
    bad_model = ctx.gold.model.model_construct(
        **{**ctx.gold.model.__dict__, "entries": tuple(reversed(entries))})  # unsorted
    bad = ctx.gold.model_copy(update={"model": bad_model})
    with pytest.raises(GoldAssertionSetError):
        gold_assertion_set_hash(bad_model)
    with pytest.raises(ValueError, match="gold assertion set failed governed revalidation") as exc:
        ctx.build(gold=bad)
    _assert_plain_value_error(exc)


def test_only_the_known_governed_error_classes_are_caught():
    """The producer must not catch broadly."""
    source = Path(ai_mod.__file__).read_text()
    assert "except Exception" not in source
    assert "except BaseException" not in source
    assert "except:" not in source
    for known in ("except AxisTaxonomyError", "except GoldAssertionSetError",
                  "except SourceSnapshotError"):
        assert known in source


# --- Boundary --------------------------------------------------------------


def test_producer_persists_nothing_and_defines_no_contract(ctx, tmp_path):
    """No file appears anywhere under the run root as a result of producing records."""
    before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    ctx.build()
    after = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    assert before == after
    source = Path(ai_mod.__file__).read_text()
    for forbidden in ("ContractStampedModel", "_contract_id", "persist_", "def load_"):
        assert forbidden not in source, forbidden
    assert not hasattr(ai_mod, "ExtractionAxisEvaluationInputsError")


def test_local_stage_mirror_matches_the_binding_module():
    assert ai_mod._STAGE_SUBJECT_KIND == otb_mod._STAGE_SUBJECT_KIND


# --- Public surface --------------------------------------------------------


def test_public_surface():
    for name in ("ExtractionAxisEvaluationInputs", "build_extraction_axis_evaluation_records"):
        assert name in evaluation_pkg.__all__
        assert evaluation_pkg.__all__.count(name) == 1
        assert getattr(evaluation_pkg, name) is getattr(ai_mod, name)
    assert len(evaluation_pkg.__all__) == 579
    assert evaluation_pkg.__all__ == sorted(evaluation_pkg.__all__)
    assert len(set(evaluation_pkg.__all__)) == len(evaluation_pkg.__all__)
