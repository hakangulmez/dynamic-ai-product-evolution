"""Xe-bind: observation-target binding (``observation_target_binding@0.1.0``).

The binding is the only artifact allowed to map the raw extraction
observation-identity namespace onto the canonical target-registry namespace. It is
hash-pinned to the exact parsed content and its raw artifact, pinned to the case's
own resolved registry identity, many-to-one by design, and — whenever any
observation is parent-referenced — verified against the committed
``parent_observation_snapshot@0.1.0``. Unresolved decisions are first-class: the
required ``canonical_target_reference`` is present as JSON ``null``, never omitted.
"""

import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import observation_target_binding as otb_mod
from dynamic_ai_products.evaluation import resolution_decisions as rd_mod
from dynamic_ai_products.evaluation import semantic_adapters as sa_mod
from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.models import EvaluationCase
from dynamic_ai_products.evaluation.observation_target_binding import (
    EXTRACTION_EVALUATION_STAGES,
    LoadedObservationTargetBinding,
    ObservationTargetBinding,
    ObservationTargetBindingError,
    ObservationTargetResolutionDecision,
    ObservationTargetResolutionProvenance,
    build_observation_target_binding,
    load_observation_target_binding,
    observations_by_canonical_target,
    persist_observation_target_binding,
    unresolved_observation_ids,
)
from dynamic_ai_products.evaluation.parent_observation_snapshot import (
    load_parent_observation_snapshot,
)
from dynamic_ai_products.evaluation.prediction_content import (
    LoadedParsedPredictionContent,
    ParsedPredictionContent,
)
from dynamic_ai_products.evaluation.references import (
    CaseResolution,
    LoadedTargetRegistry,
    load_target_registry,
    resolve_case_references,
)
from dynamic_ai_products.evaluation.scoring_config import load_scoring_gate_config
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness" / "substrate_integration"

REGISTRY = load_target_registry("target_registry.json", eval_root=FX)
SCORING = load_scoring_gate_config("scoring_gate_config.json", eval_root=FX)
SNAP = load_parent_observation_snapshot("parent_observation_snapshot.json", source_root=FX)

RUN = "xe-bind-run"
CASE_ID = "SYNTH-CASE-FULL-0002"
COMPANY = "SYNTH-CO-0001"
CUTOFF = "2025-12-31"
STAGE = "capability_extraction"

CAP_OBS = "SYNTH-CAPABILITY-OBS-0001"
PROD_OBS = "SYNTH-PRODUCT-OBS-0001"
CANON_CAP = "SYNTH.PRODUCT.ALPHA.CAPABILITY"
CANON_PROD = "SYNTH.PRODUCT.ALPHA"
CANON_TASK = "SYNTH.PRODUCT.CAPABILITY.TASK"
TASK_ALIAS = "SYNTH.ALIAS.TASK"

RAW_REF = "prediction_source.json"
RAW_SHA = "a" * 64
PPC_META = {
    "contract_id": "parsed_prediction_content", "contract_version": "0.1.0",
    "contract_hash": model_contract_hash(
        ParsedPredictionContent, "parsed_prediction_content", "0.1.0"),
}
BINDING_HASH = model_contract_hash(
    ObservationTargetBinding, "observation_target_binding", "0.1.0")
TS = "2026-07-26T00:00:00+00:00"


# --- Builders ---------------------------------------------------------------


def prov(**ov):
    d = {
        "resolution_method": "stable_identity_field",
        "source_field_name": "stable_capability_id",
        "source_field_value": CANON_CAP,
        "registry_entry_reference_id": CANON_CAP,
        "resolver_kind": "deterministic_rule",
        "resolver_ids": ["rule-v1"],
        "verification_status": "provisional",
        "verification_method": "deterministic_rule_review",
        "decision_timestamps": [TS],
        "change_reason": "initial binding",
    }
    d.update(ov)
    return {k: v for k, v in d.items() if v is not _OMIT}


class _Omit:
    pass


_OMIT = _Omit()


def unresolved_prov(**ov):
    return prov(
        resolution_method="declared_unresolved", unresolved_reason_code="no_registry_candidate",
        source_field_name=_OMIT, source_field_value=_OMIT,
        registry_entry_reference_id=_OMIT, **ov)


def decision(obs, kind, canonical, *, parent=False, provenance=None, status=None):
    payload = {
        "observation_id": obs, "observation_kind": kind,
        "resolution_status": status or ("resolved" if canonical is not None else "unresolved"),
        "canonical_target_reference": canonical, "parent_referenced": parent,
        "provenance": provenance if provenance is not None else (
            prov(source_field_value=canonical, registry_entry_reference_id=canonical)
            if canonical is not None else unresolved_prov()
        ),
    }
    return ObservationTargetResolutionDecision.model_validate(payload)


def parsed(*, entities=None, fields=None, evidence=None, case_id=CASE_ID, stage=STAGE,
           completeness="complete", sha="d" * 64):
    if entities is None:
        entities = [("capability", CAP_OBS), ("product", PROD_OBS)]
    content = ParsedPredictionContent.model_validate({
        "contract": PPC_META, "case_id": case_id, "stage": stage,
        "prediction_record_id": "pred-1", "input_packet_hash": "c" * 64,
        "observation_cutoff": CUTOFF, "raw_artifact_reference": RAW_REF,
        "raw_artifact_sha256": RAW_SHA, "raw_output_preserved": True, "repair_applied": False,
        "entity_collection": {
            "completeness": completeness,
            "entities": sorted(
                ({"entity_kind": k, "entity_ref": r} for k, r in entities),
                key=lambda d: (d["entity_kind"], d["entity_ref"])),
        },
        "field_value_collection": {"completeness": "complete", "field_values": fields or []},
        "evidence_collection": {"completeness": "complete", "evidence": evidence or []},
    })
    return LoadedParsedPredictionContent(
        content=content, sha256=sha, artifact_reference=f"{RUN}/snapshots/"
        "parsed_prediction_content.json")


def resolution(*, case_id=CASE_ID, version=None, sha=None):
    return CaseResolution.model_validate({
        "case_id": case_id,
        "target_registry_version": version or REGISTRY.version,
        "target_registry_sha256": sha or REGISTRY.sha256,
        "scoring_config_version": SCORING.version,
        "scoring_config_sha256": SCORING.sha256,
        "assertions": [],
    })


def build(*, entries=None, snapshot=SNAP, content=None, res=None, company=COMPANY,
          registry=REGISTRY, case=None):
    if entries is None:
        entries = (
            decision(CAP_OBS, "capability", CANON_CAP),
            decision(PROD_OBS, "product", CANON_PROD, parent=True),
        )
    return build_observation_target_binding(
        eval_run_id=RUN, case=case or _case(), company_id=company,
        resolution=res or resolution(),
        parsed_prediction_content=content or parsed(), target_registry=registry,
        resolution_entries=entries, parent_snapshot=snapshot)


def _case(stage=STAGE, case_id=CASE_ID):
    return EvaluationCase.model_validate({
        "case_id": case_id, "stage": stage,
        "stage_context": {"observation_window": {"start": "2025-01-01", "end": CUTOFF}},
        "input_source_ids": [], "input_passage_ids": [],
        "assertions": [{"assertion_id": "A1", "kind": "expected_entity",
                        "semantic_version": "0.1.0", "target_references": [CANON_CAP],
                        "scoring_gate_config_references": ["synth-scoring-gate-ref-0001"]}],
        "failure_tags": [], "notes": "n", "created_by": "c",
        "created_at": "2026-07-26T00:00:00+00:00", "guideline_version": "draft-v0.1",
    })


# --- Contract identity + happy path ----------------------------------------


def test_contract_stamp_and_strict_frozen():
    b = build()
    assert b.contract.contract_id == "observation_target_binding"
    assert b.contract.contract_version == "0.1.0"
    assert b.contract.contract_hash == BINDING_HASH
    assert b.stage == STAGE and b.case_id == CASE_ID and b.company_id == COMPANY
    assert b.raw_artifact_sha256 == RAW_SHA and b.raw_artifact_reference == RAW_REF
    assert b.parsed_prediction_content_sha256 == "d" * 64
    assert b.target_registry_version == REGISTRY.version
    assert b.target_registry_sha256 == REGISTRY.sha256
    assert b.parent_observation_snapshot_version == SNAP.version
    assert b.parent_observation_snapshot_sha256 == SNAP.sha256
    assert b.resolved_observation_count == 2 and b.unresolved_observation_count == 0
    assert [e.observation_id for e in b.entries] == sorted(
        [e.observation_id for e in b.entries])
    with pytest.raises(Exception):
        b.case_id = "x"  # frozen
    with pytest.raises(PydanticValidationError):
        ObservationTargetBinding.model_validate(
            {**b.model_dump(mode="json", exclude_unset=True), "extra": 1})


def test_namespace_separation_raw_ids_differ_from_canonical():
    # The core ADR-026 invariant: the raw observation ID is NOT the canonical
    # target reference; the binding is what relates them.
    b = build()
    by_obs = {e.observation_id: e.canonical_target_reference for e in b.entries}
    assert by_obs[CAP_OBS] == CANON_CAP and CAP_OBS != CANON_CAP
    assert by_obs[PROD_OBS] == CANON_PROD and PROD_OBS != CANON_PROD
    registry_ids = {e.reference_id for e in REGISTRY.registry.entries}
    assert not ({CAP_OBS, PROD_OBS} & registry_ids)


def test_decision_model_has_exactly_the_six_locked_fields():
    assert set(ObservationTargetResolutionDecision.model_fields) == {
        "observation_id", "observation_kind", "resolution_status",
        "canonical_target_reference", "parent_referenced", "provenance",
    }


def test_extraction_stage_vocabulary_matches_adapter_stages():
    # Single source of truth: drift between the binding's governed vocabulary and
    # the semantic adapter's implemented extraction stages is a defect.
    assert EXTRACTION_EVALUATION_STAGES == frozenset(sa_mod._STAGE_ENTITY_KINDS)


# --- Required-nullable vs omit-or-non-null null semantics -------------------


def test_unresolved_requires_present_null_and_roundtrips():
    d = decision(CAP_OBS, "capability", None)
    assert d.resolution_status == "unresolved"
    assert d.canonical_target_reference is None
    dumped = d.model_dump(mode="json", exclude_unset=True)
    assert "canonical_target_reference" in dumped
    assert dumped["canonical_target_reference"] is None
    # Fail-closed revalidation preserves the required null rather than dropping it.
    again = ObservationTargetResolutionDecision.model_validate(dumped)
    assert again == d


def test_unresolved_omitting_canonical_reference_is_rejected():
    payload = {
        "observation_id": CAP_OBS, "observation_kind": "capability",
        "resolution_status": "unresolved", "parent_referenced": False,
        "provenance": unresolved_prov(),
    }
    with pytest.raises(PydanticValidationError) as ei:
        ObservationTargetResolutionDecision.model_validate(payload)
    assert any(e["type"] == "missing" for e in ei.value.errors())
    assert ObservationTargetResolutionDecision.model_fields[
        "canonical_target_reference"].is_required()


def test_resolved_with_null_canonical_reference_is_rejected():
    with pytest.raises(PydanticValidationError):
        ObservationTargetResolutionDecision.model_validate({
            "observation_id": CAP_OBS, "observation_kind": "capability",
            "resolution_status": "resolved", "canonical_target_reference": None,
            "parent_referenced": False, "provenance": prov()})


@pytest.mark.parametrize("field", [
    "source_field_name", "source_field_value", "registry_entry_reference_id",
    "registry_entry_matched_alias", "unresolved_reason_code", "adjudication_reference",
])
def test_explicit_null_rejected_for_each_omit_or_non_null_provenance_field(field):
    payload = prov()
    payload[field] = None
    with pytest.raises(PydanticValidationError) as ei:
        ObservationTargetResolutionProvenance.model_validate(payload)
    assert "must not be explicit JSON null" in str(ei.value)


def test_canonical_reference_is_not_an_omit_or_non_null_field():
    # The required-null field must never be swept into the omit-or-non-null rule.
    # The provenance tuple lives with its model in the canonical owner module.
    assert "canonical_target_reference" not in rd_mod._PROVENANCE_OMIT_OR_NON_NULL
    assert "canonical_target_reference" not in otb_mod._BINDING_OMIT_OR_NON_NULL


@pytest.mark.parametrize(
    "field", ["parent_observation_snapshot_version", "parent_observation_snapshot_sha256"])
def test_explicit_null_rejected_for_paired_snapshot_pins(field):
    payload = build().model_dump(mode="json", exclude_unset=True)
    payload[field] = None
    with pytest.raises(PydanticValidationError) as ei:
        ObservationTargetBinding.model_validate(payload)
    assert "must not be explicit JSON null" in str(ei.value)


# --- Provenance governance invariants --------------------------------------


def test_verified_status_requires_a_reviewer():
    with pytest.raises(PydanticValidationError):
        ObservationTargetResolutionProvenance.model_validate(
            prov(verification_status="verified"))
    ObservationTargetResolutionProvenance.model_validate(
        prov(verification_status="verified", reviewer_ids=["rev-1"],
             verification_method="expert_second_review", resolver_kind="model_assisted"))


def test_human_adjudicated_requires_reviewer_and_adjudication_reference():
    with pytest.raises(PydanticValidationError):
        ObservationTargetResolutionProvenance.model_validate(
            prov(resolver_kind="human_adjudicated", reviewer_ids=["rev-1"],
                 verification_method="expert_second_review"))
    ObservationTargetResolutionProvenance.model_validate(
        prov(resolver_kind="human_adjudicated", reviewer_ids=["rev-1"],
             verification_method="expert_second_review",
             adjudication_reference="adjudications/a1.json"))


def test_deterministic_rule_review_restricted_to_deterministic_resolver():
    with pytest.raises(PydanticValidationError):
        ObservationTargetResolutionProvenance.model_validate(
            prov(resolver_kind="model_assisted"))


def test_self_review_forbidden():
    with pytest.raises(PydanticValidationError) as ei:
        ObservationTargetResolutionProvenance.model_validate(
            prov(resolver_ids=["a"], reviewer_ids=["a"], verification_status="verified",
                 verification_method="expert_second_review", resolver_kind="model_assisted"))
    assert "self_review_forbidden" in str(ei.value)


@pytest.mark.parametrize("bad", [
    {"resolver_ids": []},
    {"resolver_ids": ["a", "a"]},
    {"decision_timestamps": []},
    {"decision_timestamps": ["2026-07-26"]},
    {"decision_timestamps": ["2026-07-26T00:00:00"]},
    {"change_reason": "  "},
    {"adjudication_reference": "../escape.json"},
])
def test_governance_field_defects_rejected(bad):
    with pytest.raises(PydanticValidationError):
        ObservationTargetResolutionProvenance.model_validate(prov(**bad))


def test_unresolved_method_forbids_resolution_fields_and_requires_reason():
    with pytest.raises(PydanticValidationError):
        ObservationTargetResolutionProvenance.model_validate(
            prov(resolution_method="declared_unresolved",
                 unresolved_reason_code="no_registry_candidate"))
    with pytest.raises(PydanticValidationError):
        ObservationTargetResolutionProvenance.model_validate(
            prov(resolution_method="declared_unresolved", source_field_name=_OMIT,
                 source_field_value=_OMIT, registry_entry_reference_id=_OMIT))


def test_resolving_method_forbids_unresolved_reason_code():
    with pytest.raises(PydanticValidationError):
        ObservationTargetResolutionProvenance.model_validate(
            prov(unresolved_reason_code="x"))


def test_model_construct_bypassed_decision_is_rejected():
    bad = ObservationTargetResolutionDecision.model_construct(
        observation_id="", observation_kind="capability", resolution_status="resolved",
        canonical_target_reference=None, parent_referenced=False,
        provenance=ObservationTargetResolutionProvenance.model_validate(prov()))
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(entries=(bad, decision(PROD_OBS, "product", CANON_PROD, parent=True)))
    assert ei.value.reason_code == "decision_validation"


def test_producer_never_reads_a_clock():
    src = (ROOT / "src" / "dynamic_ai_products" / "evaluation"
           / "observation_target_binding.py").read_text()
    for forbidden in ("datetime.now", "time.time", "utcnow", "Date.now", "monotonic"):
        assert forbidden not in src


# --- Case-resolution registry pin ------------------------------------------


def test_genuine_case_resolution_binds_cleanly():
    from dynamic_ai_products.evaluation.cases import load_case
    case = load_case("capability_case.json", eval_root=FX)
    real = resolve_case_references(case, registry=REGISTRY, scoring_config=SCORING)
    b = build(res=real, case=case)
    assert b.target_registry_version == real.target_registry_version
    assert b.target_registry_sha256 == real.target_registry_sha256


def test_resolution_wrong_type_is_type_error():
    with pytest.raises(TypeError):
        build_observation_target_binding(
            eval_run_id=RUN, case=_case(), company_id=COMPANY, resolution=object(),
            parsed_prediction_content=parsed(), target_registry=REGISTRY,
            resolution_entries=(), parent_snapshot=SNAP)


def test_resolution_case_id_mismatch():
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(res=resolution(case_id="OTHER"))
    assert ei.value.reason_code == "resolution_case_id_mismatch"


def test_resolution_registry_version_mismatch():
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(res=resolution(version="other-registry-v9"))
    assert ei.value.reason_code == "resolution_target_registry_version_mismatch"


def test_resolution_registry_sha_mismatch():
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(res=resolution(sha="f" * 64))
    assert ei.value.reason_code == "resolution_target_registry_sha256_mismatch"


def test_target_registry_wrapper_inconsistent():
    tampered = LoadedTargetRegistry(
        registry=REGISTRY.registry, version="not-the-registry-version",
        sha256=REGISTRY.sha256, artifact_reference=REGISTRY.artifact_reference)
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(registry=tampered, res=resolution(version="not-the-registry-version"))
    assert ei.value.reason_code == "target_registry_wrapper_inconsistent"


# --- Completeness bijection -------------------------------------------------


def test_missing_decision_for_a_parsed_observation():
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(entries=(decision(CAP_OBS, "capability", CANON_CAP),))
    assert ei.value.reason_code == "observation_unbound"


def test_extra_decision_not_in_parsed_content():
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(entries=(
            decision(CAP_OBS, "capability", CANON_CAP),
            decision(PROD_OBS, "product", CANON_PROD, parent=True),
            decision("SYNTH-GHOST-OBS-0009", "capability", CANON_CAP)))
    assert ei.value.reason_code == "observation_not_in_parsed_content"


def test_duplicate_observation_decision():
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(entries=(
            decision(CAP_OBS, "capability", CANON_CAP),
            decision(CAP_OBS, "capability", CANON_CAP),
            decision(PROD_OBS, "product", CANON_PROD, parent=True)))
    assert ei.value.reason_code == "duplicate_observation_decision"


def test_observation_kind_mismatch():
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(entries=(
            decision(CAP_OBS, "capability", CANON_CAP),
            decision(PROD_OBS, "capability", CANON_PROD, parent=True)))
    assert ei.value.reason_code == "observation_kind_mismatch"


def test_incomplete_parsed_entity_collection_rejected():
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(content=parsed(entities=[], completeness="unavailable"))
    assert ei.value.reason_code == "parsed_content_incomplete"


def test_non_extraction_stage_rejected():
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(case=_case(stage="universe_classification"),
              content=parsed(stage="universe_classification"))
    assert ei.value.reason_code == "non_extraction_stage"


def test_case_and_stage_disagreement_rejected():
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(content=parsed(case_id="OTHER"))
    assert ei.value.reason_code == "case_id_mismatch"
    with pytest.raises(ObservationTargetBindingError) as ej:
        build(content=parsed(stage="task_extraction"))
    assert ej.value.reason_code == "stage_mismatch"


# --- Many-to-one mapping ----------------------------------------------------


def test_many_to_one_mapping_is_accepted_and_indexed(tmp_path):
    # Two distinct raw observations legitimately resolving to ONE canonical target
    # must construct, persist, reload, and index both — never a collision failure.
    b = build(entries=(
        decision(CAP_OBS, "capability", CANON_CAP),
        decision(PROD_OBS, "product", CANON_CAP, parent=True)))
    index = observations_by_canonical_target(b)
    assert index == {CANON_CAP: (CAP_OBS, PROD_OBS)}
    assert b.resolved_observation_count == 2 and b.unresolved_observation_count == 0
    run = tmp_path / RUN
    run.mkdir(parents=True)
    loaded = persist_observation_target_binding(b, eval_root=tmp_path, eval_run_id=RUN)
    again = load_observation_target_binding(
        loaded.artifact_reference, eval_root=tmp_path, expected_sha256=loaded.sha256)
    assert observations_by_canonical_target(again.model) == {CANON_CAP: (CAP_OBS, PROD_OBS)}


def test_no_canonical_collision_rejection_exists():
    src = (ROOT / "src" / "dynamic_ai_products" / "evaluation"
           / "observation_target_binding.py").read_text()
    assert "canonical_target_reference_collision" not in src


# --- Registry resolution ----------------------------------------------------


def test_unknown_canonical_reference_rejected():
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(entries=(
            decision(CAP_OBS, "capability", "SYNTH.NOT.IN.REGISTRY"),
            decision(PROD_OBS, "product", CANON_PROD, parent=True)))
    assert ei.value.reason_code == "canonical_target_reference_unknown"


def test_alias_resolution_persists_the_canonical_reference_id():
    d = decision(CAP_OBS, "capability", CANON_TASK, provenance=prov(
        resolution_method="registry_alias", registry_entry_reference_id=CANON_TASK,
        registry_entry_matched_alias=TASK_ALIAS, source_field_name=_OMIT,
        source_field_value=_OMIT))
    b = build(entries=(d, decision(PROD_OBS, "product", CANON_PROD, parent=True)))
    entry = next(e for e in b.entries if e.observation_id == CAP_OBS)
    assert entry.canonical_target_reference == CANON_TASK
    assert entry.provenance.registry_entry_matched_alias == TASK_ALIAS


def test_alias_not_accepted_by_the_named_entry():
    d = decision(CAP_OBS, "capability", CANON_CAP, provenance=prov(
        resolution_method="registry_alias", registry_entry_reference_id=CANON_CAP,
        registry_entry_matched_alias="SYNTH.ALIAS.WRONG", source_field_name=_OMIT,
        source_field_value=_OMIT))
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(entries=(d, decision(PROD_OBS, "product", CANON_PROD, parent=True)))
    assert ei.value.reason_code == "canonical_target_reference_unknown"


def test_provenance_reference_must_equal_the_canonical_reference():
    d = decision(CAP_OBS, "capability", CANON_CAP,
                 provenance=prov(registry_entry_reference_id=CANON_PROD))
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(entries=(d, decision(PROD_OBS, "product", CANON_PROD, parent=True)))
    assert ei.value.reason_code == "provenance_reference_disagreement"


# --- Owning subject / parent shape -----------------------------------------


def test_owning_subject_must_be_exactly_one():
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(entries=(
            decision(CAP_OBS, "capability", CANON_CAP),
            decision(PROD_OBS, "product", CANON_PROD)))
    assert ei.value.reason_code == "owning_subject_ambiguous"
    with pytest.raises(ObservationTargetBindingError) as ej:
        build(entries=(
            decision(CAP_OBS, "capability", CANON_CAP, parent=True),
            decision(PROD_OBS, "product", CANON_PROD, parent=True)))
    assert ej.value.reason_code == "owning_subject_ambiguous"


def test_owning_subject_kind_must_match_the_stage():
    content = parsed(entities=[("product", PROD_OBS), ("capability", CAP_OBS)])
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(content=content, entries=(
            decision(PROD_OBS, "product", CANON_PROD),
            decision(CAP_OBS, "capability", CANON_CAP, parent=True)))
    assert ei.value.reason_code == "owning_subject_kind_mismatch"


def test_task_observation_may_not_be_a_parent_reference():
    content = parsed(entities=[("task", "SYNTH-TASK-OBS-0001"), ("capability", CAP_OBS)])
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(content=content, entries=(
            decision(CAP_OBS, "capability", CANON_CAP),
            decision("SYNTH-TASK-OBS-0001", "task", CANON_TASK, parent=True)))
    assert ei.value.reason_code == "parent_role_unsupported"


# --- Mandatory committed parent-snapshot verification ----------------------


def test_parent_snapshot_is_required_at_capability_stage():
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(snapshot=None)
    assert ei.value.reason_code == "parent_snapshot_required"


def test_parent_observation_absent_from_snapshot():
    content = parsed(entities=[("capability", CAP_OBS), ("product", "SYNTH-PRODUCT-OBS-0009")])
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(content=content, entries=(
            decision(CAP_OBS, "capability", CANON_CAP),
            decision("SYNTH-PRODUCT-OBS-0009", "product", CANON_PROD, parent=True)))
    assert ei.value.reason_code == "parent_observation_absent"


def test_parent_role_mismatch_when_present_under_another_role(tmp_path):
    # The verified product owner id declared as a CAPABILITY parent is a role
    # mismatch, not merely an absence.
    content = parsed(entities=[("capability", CAP_OBS), ("capability", PROD_OBS)])
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(content=content, entries=(
            decision(CAP_OBS, "capability", CANON_CAP),
            decision(PROD_OBS, "capability", CANON_PROD, parent=True)))
    assert ei.value.reason_code == "parent_role_mismatch"


def test_child_case_context_mismatch():
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(company="SYNTH-CO-OTHER")
    assert ei.value.reason_code == "case_context_mismatch"
    # A coherent case/resolution/parsed-content triple that simply is not the
    # snapshot's case still fails closed on the snapshot context.
    with pytest.raises(ObservationTargetBindingError) as ej:
        build(case=_case(case_id="OTHER-CASE"), content=parsed(case_id="OTHER-CASE"),
              res=resolution(case_id="OTHER-CASE"))
    assert ej.value.reason_code == "case_context_mismatch"


def test_parsed_company_id_disagreement():
    fields = [{"entity_ref": CAP_OBS, "field_name": "company_id", "field_value": "SYNTH-CO-OTHER"}]
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(content=parsed(fields=fields))
    assert ei.value.reason_code == "company_id_disagreement"


def test_blank_company_id_rejected():
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(company="  ")
    assert ei.value.reason_code == "invalid_company_id"


def test_snapshot_pins_are_paired():
    payload = build().model_dump(mode="json", exclude_unset=True)
    payload.pop("parent_observation_snapshot_sha256")
    with pytest.raises(PydanticValidationError):
        ObservationTargetBinding.model_validate(payload)


# --- Unresolved semantics ---------------------------------------------------


def test_unresolved_entries_are_counted_persisted_and_never_upgraded(tmp_path):
    b = build(entries=(
        decision(CAP_OBS, "capability", None),
        decision(PROD_OBS, "product", CANON_PROD, parent=True)))
    assert b.resolved_observation_count == 1 and b.unresolved_observation_count == 1
    assert unresolved_observation_ids(b) == (CAP_OBS,)
    assert observations_by_canonical_target(b) == {CANON_PROD: (PROD_OBS,)}
    run = tmp_path / RUN
    run.mkdir(parents=True)
    loaded = persist_observation_target_binding(b, eval_root=tmp_path, eval_run_id=RUN)
    raw = json.loads((tmp_path / RUN / "snapshots" / "observation_target_binding.json").read_text())
    entry = next(e for e in raw["entries"] if e["observation_id"] == CAP_OBS)
    assert "canonical_target_reference" in entry and entry["canonical_target_reference"] is None
    again = load_observation_target_binding(loaded.artifact_reference, eval_root=tmp_path)
    assert unresolved_observation_ids(again.model) == (CAP_OBS,)


def test_counts_must_equal_the_actual_partition():
    payload = build().model_dump(mode="json", exclude_unset=True)
    payload["resolved_observation_count"] = 1
    with pytest.raises(PydanticValidationError):
        ObservationTargetBinding.model_validate(payload)


def test_entries_must_be_sorted_and_unique():
    payload = build().model_dump(mode="json", exclude_unset=True)
    payload["entries"] = list(reversed(payload["entries"]))
    with pytest.raises(PydanticValidationError):
        ObservationTargetBinding.model_validate(payload)


# --- Persistence + loading --------------------------------------------------


def _run(tmp_path):
    (tmp_path / RUN).mkdir(parents=True)
    return tmp_path


def test_persist_is_write_once_and_hash_verified(tmp_path):
    root = _run(tmp_path)
    b = build()
    loaded = persist_observation_target_binding(b, eval_root=root, eval_run_id=RUN)
    assert isinstance(loaded, LoadedObservationTargetBinding)
    assert loaded.artifact_reference == f"{RUN}/snapshots/observation_target_binding.json"
    assert loaded.version == "0.1.0"
    dest = root / RUN / "snapshots" / "observation_target_binding.json"
    assert loaded.sha256 == sha256_bytes(dest.read_bytes())
    assert dest.read_bytes().endswith(b"\n")
    with pytest.raises(ObservationTargetBindingError) as ei:
        persist_observation_target_binding(b, eval_root=root, eval_run_id=RUN)
    assert ei.value.reason_code == "artifact_exists"


def test_persist_run_id_must_match(tmp_path):
    root = _run(tmp_path)
    (root / "other-run").mkdir()
    with pytest.raises(ObservationTargetBindingError) as ei:
        persist_observation_target_binding(build(), eval_root=root, eval_run_id="other-run")
    assert ei.value.reason_code == "persist_eval_run_id_mismatch"


def test_expected_sha_mismatch(tmp_path):
    root = _run(tmp_path)
    loaded = persist_observation_target_binding(build(), eval_root=root, eval_run_id=RUN)
    with pytest.raises(ObservationTargetBindingError) as ei:
        load_observation_target_binding(
            loaded.artifact_reference, eval_root=root, expected_sha256="0" * 64)
    assert ei.value.reason_code == "expected_hash_mismatch"


@pytest.mark.parametrize("ref,code", [
    ("../escape.json", "unsafe_reference"),
    ("missing/nope.json", "artifact_missing"),
])
def test_loader_reference_protections(tmp_path, ref, code):
    root = _run(tmp_path)
    with pytest.raises(ObservationTargetBindingError) as ei:
        load_observation_target_binding(ref, eval_root=root)
    assert ei.value.reason_code == code


def test_loader_rejects_symlink(tmp_path):
    root = _run(tmp_path)
    loaded = persist_observation_target_binding(build(), eval_root=root, eval_run_id=RUN)
    dest = root / RUN / "snapshots" / "observation_target_binding.json"
    external = root / "external.json"
    external.write_bytes(dest.read_bytes())
    dest.unlink()
    dest.symlink_to(external)
    with pytest.raises(ObservationTargetBindingError) as ei:
        load_observation_target_binding(loaded.artifact_reference, eval_root=root)
    assert ei.value.reason_code == "artifact_symlink"


@pytest.mark.parametrize("body,code", [
    (b"{", "json_error"),
    (b'{"a": 1, "a": 2}', "duplicate_key"),
    (b'{"a": NaN}', "non_finite"),
    (b"[]", "top_level_type"),
    (b"\xff\xfe", "decode_error"),
    (b'\xef\xbb\xbf{"a": 1}', "bom"),
])
def test_loader_strict_parse(tmp_path, body, code):
    root = _run(tmp_path)
    (root / RUN / "snapshots").mkdir(parents=True)
    dest = root / RUN / "snapshots" / "observation_target_binding.json"
    dest.write_bytes(body)
    with pytest.raises(ObservationTargetBindingError) as ei:
        load_observation_target_binding(f"{RUN}/snapshots/observation_target_binding.json",
                                        eval_root=root)
    assert ei.value.reason_code == code


def test_loader_rejects_contract_invalid_document(tmp_path):
    root = _run(tmp_path)
    (root / RUN / "snapshots").mkdir(parents=True)
    payload = build().model_dump(mode="json", exclude_unset=True)
    payload["stage"] = "universe_screen"
    (root / RUN / "snapshots" / "observation_target_binding.json").write_bytes(
        (json.dumps(payload) + "\n").encode())
    with pytest.raises(ObservationTargetBindingError) as ei:
        load_observation_target_binding(f"{RUN}/snapshots/observation_target_binding.json",
                                        eval_root=root)
    assert ei.value.reason_code == "model_validation"


# --- Sanitization + public surface -----------------------------------------


def test_errors_leak_no_content_or_absolute_path(tmp_path):
    with pytest.raises(ObservationTargetBindingError) as ei:
        build(content=parsed(case_id="SECRET-CASE"))
    text = str(ei.value)
    assert "SECRET-CASE" not in text and str(tmp_path) not in text
    assert ei.value.reason_code == "case_id_mismatch"


def test_public_surface_exported():
    for name in otb_mod.__all__:
        assert name in evaluation_pkg.__all__
        assert getattr(evaluation_pkg, name) is getattr(otb_mod, name)
    for private in ("_revalidate_decision", "_STAGE_SUBJECT_KIND", "_DuplicateKeyControl",
                    "_PARENT_KIND_FIELD"):
        assert private not in evaluation_pkg.__all__


def test_producer_signature_is_keyword_only_and_pins_resolution():
    params = inspect.signature(build_observation_target_binding).parameters
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in params.values())
    assert "resolution" in params and "parent_snapshot" in params
    assert params["parent_snapshot"].default is None


def test_import_performs_no_io_or_hash():
    code = "\n".join([
        # Third-party lazy machinery is warmed BEFORE the spies so only our
        # module's own import behaviour is measured.
        "import sys, os, hashlib, importlib",
        "sys.path.insert(0, 'src')",
        "from jsonschema import Draft202012Validator, FormatChecker",
        "import pydantic",
        "import dynamic_ai_products, dynamic_ai_products.universe.io_utils",
        "import dynamic_ai_products.evaluation",
        "sys.modules.pop('dynamic_ai_products.evaluation.observation_target_binding', None)",
        "from pathlib import Path",
        "reads=[]; sha=[]",
        "orb, ort, osha = Path.read_bytes, Path.read_text, hashlib.sha256",
        "Path.read_bytes=lambda self,*a,**k:(reads.append(str(self)),orb(self,*a,**k))[1]",
        "Path.read_text=lambda self,*a,**k:(reads.append(str(self)),ort(self,*a,**k))[1]",
        "hashlib.sha256=lambda *a,**k:(sha.append(1),osha(*a,**k))[1]",
        "importlib.import_module('dynamic_ai_products.evaluation.observation_target_binding')",
        "Path.read_bytes, Path.read_text, hashlib.sha256 = orb, ort, osha",
        "bad=[p for p in reads if p.endswith('.json')]",
        "assert not bad, bad",
        "assert not sha, len(sha)",
        "print('OK')",
    ])
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr


def test_module_dependency_boundaries():
    # ADR-026 dependency matrix: the binding is a leaf below both consumers, so it
    # must not import output_manifest, semantic_assertions, runs, stage_profiles,
    # or metric_inputs. A cycle here would make the import order load-bearing.
    src = (ROOT / "src" / "dynamic_ai_products" / "evaluation"
           / "observation_target_binding.py").read_text()
    for forbidden in ("from .output_manifest", "from .semantic_assertions", "from .runs",
                      "from .stage_profiles", "from .metric_inputs"):
        assert forbidden not in src, forbidden
    for required in ("from .prediction_content", "from .references",
                     "from .parent_observation_snapshot"):
        assert required in src, required


# --- Parent-snapshot pins are coupled to the entry set (model-level) --------
#
# The producer already refuses to build a parent-referenced binding without the
# committed snapshot, but the persisted model must enforce the same coupling so a
# hand-written or reloaded document cannot bypass it.


def test_parent_referenced_entries_require_both_pins():
    payload = build().model_dump(mode="json", exclude_unset=True)
    assert any(e["parent_referenced"] for e in payload["entries"])
    payload.pop("parent_observation_snapshot_version")
    payload.pop("parent_observation_snapshot_sha256")
    with pytest.raises(PydanticValidationError) as ei:
        ObservationTargetBinding.model_validate(payload)
    assert "parent_snapshot_pins_required" in str(ei.value)


def _parent_free_payload(**ov):
    """A single-subject task-stage binding: no parent reference, so no pins."""
    payload = {
        "contract": {"contract_id": "observation_target_binding", "contract_version": "0.1.0",
                     "contract_hash": BINDING_HASH},
        "eval_run_id": RUN, "case_id": CASE_ID, "company_id": COMPANY,
        "stage": "task_extraction", "prediction_record_id": "pred-1",
        "raw_artifact_reference": RAW_REF, "raw_artifact_sha256": RAW_SHA,
        "parsed_prediction_content_sha256": "d" * 64,
        "parsed_prediction_content_artifact_reference":
            f"{RUN}/snapshots/parsed_prediction_content.json",
        "target_registry_version": REGISTRY.version,
        "target_registry_sha256": REGISTRY.sha256,
        "resolved_observation_count": 1, "unresolved_observation_count": 0,
        "entries": [decision("SYNTH-TASK-OBS-0001", "task", CANON_TASK).model_dump(
            mode="json", exclude_unset=True)],
    }
    payload.update(ov)
    return payload


def test_parent_free_binding_must_omit_both_pins():
    with pytest.raises(PydanticValidationError) as ei:
        ObservationTargetBinding.model_validate(_parent_free_payload(
            parent_observation_snapshot_version=SNAP.version,
            parent_observation_snapshot_sha256=SNAP.sha256))
    assert "parent_snapshot_pins_forbidden" in str(ei.value)


def test_parent_free_task_binding_without_pins_is_accepted():
    model = ObservationTargetBinding.model_validate(_parent_free_payload())
    assert model.stage == "task_extraction"
    assert model.parent_observation_snapshot_version is None
    assert model.parent_observation_snapshot_sha256 is None
    assert observations_by_canonical_target(model) == {CANON_TASK: ("SYNTH-TASK-OBS-0001",)}


def test_valid_parent_binding_with_both_pins_is_accepted():
    model = build()
    assert any(e.parent_referenced for e in model.entries)
    assert model.parent_observation_snapshot_version == SNAP.version
    assert model.parent_observation_snapshot_sha256 == SNAP.sha256
    # And it survives a persisted round trip through full model validation.
    assert ObservationTargetBinding.model_validate(
        model.model_dump(mode="json", exclude_unset=True)) == model


def test_pin_coupling_survives_a_reload(tmp_path):
    root = _run(tmp_path)
    loaded = persist_observation_target_binding(build(), eval_root=root, eval_run_id=RUN)
    dest = root / RUN / "snapshots" / "observation_target_binding.json"
    payload = json.loads(dest.read_text())
    payload.pop("parent_observation_snapshot_version")
    payload.pop("parent_observation_snapshot_sha256")
    dest.write_bytes((json.dumps(payload) + "\n").encode())
    with pytest.raises(ObservationTargetBindingError) as ei:
        load_observation_target_binding(loaded.artifact_reference, eval_root=root)
    assert ei.value.reason_code == "model_validation"


# --- P1: adjudication ownership, re-export identity, decision-set channel ---
#
# The adjudication layer moved to ``resolution_decisions`` so the dependency runs
# one way only. The binding module re-exports the same objects, so every existing
# import path and the tuple-based API keep working unchanged.


def test_moved_models_are_identical_through_every_import_path():
    for name in ("EXTRACTION_EVALUATION_STAGES", "ObservationTargetResolutionDecision",
                 "ObservationTargetResolutionProvenance"):
        canonical = getattr(rd_mod, name)
        assert getattr(otb_mod, name) is canonical
        assert getattr(evaluation_pkg, name) is canonical


def test_binding_module_does_not_own_the_moved_models():
    # Ownership, not merely visibility: the classes are defined in the new module.
    assert ObservationTargetResolutionDecision.__module__.endswith("resolution_decisions")
    assert ObservationTargetResolutionProvenance.__module__.endswith("resolution_decisions")


def test_either_import_order_works_and_yields_one_object():
    for first, second in (("resolution_decisions", "observation_target_binding"),
                          ("observation_target_binding", "resolution_decisions")):
        code = "\n".join([
            "import sys",
            "sys.path.insert(0, 'src')",
            f"import dynamic_ai_products.evaluation.{first} as a",
            f"import dynamic_ai_products.evaluation.{second} as b",
            "d = getattr(a, 'ObservationTargetResolutionDecision', None) or "
            "getattr(b, 'ObservationTargetResolutionDecision')",
            "assert a.__name__ != b.__name__",
            "assert getattr(a, 'ObservationTargetResolutionDecision', d) is d",
            "assert getattr(b, 'ObservationTargetResolutionDecision', d) is d",
            "print('OK')",
        ])
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
        assert r.returncode == 0 and "OK" in r.stdout, (first, second, r.stderr)


def test_resolution_decisions_never_imports_the_binding_module():
    src = (ROOT / "src" / "dynamic_ai_products" / "evaluation"
           / "resolution_decisions.py").read_text()
    assert "observation_target_binding" not in src.replace(
        "``observation_target_binding@0.1.0``", "").replace(
        "``observation_target_binding``", "")


def _decision_set(tmp_path, content_sha, *, reference="adjudications/set-0001.json", **ov):
    payload = {
        "contract": {"contract_id": "observation_target_resolution_decision_set",
                     "contract_version": "0.1.0",
                     "contract_hash": model_contract_hash(
                         rd_mod.ObservationTargetResolutionDecisionSet,
                         "observation_target_resolution_decision_set", "0.1.0")},
        "decision_set_version": "adj-v1", "case_id": CASE_ID, "stage": STAGE,
        "company_id": COMPANY, "prediction_record_id": "pred-1",
        "raw_artifact_reference": RAW_REF, "raw_artifact_sha256": RAW_SHA,
        "parsed_prediction_content_sha256": content_sha,
        "decisions": [
            decision(CAP_OBS, "capability", CANON_CAP).model_dump(
                mode="json", exclude_unset=True),
            decision(PROD_OBS, "product", CANON_PROD, parent=True).model_dump(
                mode="json", exclude_unset=True),
        ],
    }
    payload.update(ov)
    model = rd_mod.ObservationTargetResolutionDecisionSet.model_validate(payload)
    (tmp_path / "adjudications").mkdir(parents=True, exist_ok=True)
    return rd_mod.persist_observation_target_resolution_decision_set(
        model, source_root=tmp_path, reference=reference)


def test_loaded_decision_set_builds_the_same_binding_as_the_tuple_path(tmp_path):
    content = parsed()
    loaded_set = _decision_set(tmp_path, content.sha256)
    from_set = build_observation_target_binding(
        eval_run_id=RUN, case=_case(), company_id=COMPANY, resolution=resolution(),
        parsed_prediction_content=content, target_registry=REGISTRY,
        resolution_decision_set=loaded_set, parent_snapshot=SNAP)
    from_tuple = build(content=content)
    assert from_set == from_tuple


def test_adjudication_channels_are_mutually_exclusive(tmp_path):
    content = parsed()
    loaded_set = _decision_set(tmp_path, content.sha256)
    entries = (decision(CAP_OBS, "capability", CANON_CAP),
               decision(PROD_OBS, "product", CANON_PROD, parent=True))
    with pytest.raises(ObservationTargetBindingError) as both:
        build_observation_target_binding(
            eval_run_id=RUN, case=_case(), company_id=COMPANY, resolution=resolution(),
            parsed_prediction_content=content, target_registry=REGISTRY,
            resolution_entries=entries, resolution_decision_set=loaded_set,
            parent_snapshot=SNAP)
    assert both.value.reason_code == "adjudication_channel_ambiguous"
    with pytest.raises(ObservationTargetBindingError) as neither:
        build_observation_target_binding(
            eval_run_id=RUN, case=_case(), company_id=COMPANY, resolution=resolution(),
            parsed_prediction_content=content, target_registry=REGISTRY,
            parent_snapshot=SNAP)
    assert neither.value.reason_code == "adjudication_channel_ambiguous"


def test_decision_set_wrong_wrapper_type_is_type_error():
    with pytest.raises(TypeError):
        build_observation_target_binding(
            eval_run_id=RUN, case=_case(), company_id=COMPANY, resolution=resolution(),
            parsed_prediction_content=parsed(), target_registry=REGISTRY,
            resolution_decision_set=object(), parent_snapshot=SNAP)


@pytest.mark.parametrize("override", [
    {"case_id": "OTHER-CASE"},
    {"stage": "task_extraction"},
    {"company_id": "SYNTH-CO-OTHER"},
    {"prediction_record_id": "pred-9"},
    {"raw_artifact_reference": "other_source.json"},
    {"raw_artifact_sha256": "9" * 64},
])
def test_decision_set_binding_mismatch_on_each_pin(tmp_path, override):
    content = parsed()
    loaded_set = _decision_set(tmp_path, content.sha256, **override)
    with pytest.raises(ObservationTargetBindingError) as ei:
        build_observation_target_binding(
            eval_run_id=RUN, case=_case(), company_id=COMPANY, resolution=resolution(),
            parsed_prediction_content=content, target_registry=REGISTRY,
            resolution_decision_set=loaded_set, parent_snapshot=SNAP)
    assert ei.value.reason_code == "decision_set_binding_mismatch"
    assert ei.value.artifact_reference == "adjudications/set-0001.json"


def test_decision_set_parsed_hash_off_by_one_byte_is_rejected(tmp_path):
    content = parsed()
    wrong = ("0" if content.sha256[0] != "0" else "1") + content.sha256[1:]
    loaded_set = _decision_set(tmp_path, wrong)
    with pytest.raises(ObservationTargetBindingError) as ei:
        build_observation_target_binding(
            eval_run_id=RUN, case=_case(), company_id=COMPANY, resolution=resolution(),
            parsed_prediction_content=content, target_registry=REGISTRY,
            resolution_decision_set=loaded_set, parent_snapshot=SNAP)
    assert ei.value.reason_code == "decision_set_binding_mismatch"


# --- Set-level fail-closed revalidation of the loaded decision set ----------
#
# A wrapper built through model_copy/model_construct satisfies isinstance while
# carrying content that never passed the SET-level invariants (ordering,
# uniqueness, stage vocabulary, non-blank identities) or a declared version that
# disagrees with the revalidated stamp. Per-decision revalidation cannot see any
# of that, so the builder must reject the wrapper outright.


def _bind_with_set(loaded_set, content):
    return build_observation_target_binding(
        eval_run_id=RUN, case=_case(), company_id=COMPANY, resolution=resolution(),
        parsed_prediction_content=content, target_registry=REGISTRY,
        resolution_decision_set=loaded_set, parent_snapshot=SNAP)


@pytest.mark.parametrize("update", [
    {"decision_set_version": ""},
    {"stage": "universe_classification"},
    {"case_id": "   "},
    {"raw_artifact_reference": "../escape.json"},
])
def test_validator_bypassed_inner_set_is_rejected(tmp_path, update):
    content = parsed()
    loaded_set = _decision_set(tmp_path, content.sha256)
    forged = loaded_set.model_copy(update={"model": loaded_set.model.model_copy(update=update)})
    with pytest.raises(ObservationTargetBindingError) as ei:
        _bind_with_set(forged, content)
    assert ei.value.reason_code == "decision_set_invalid"
    assert ei.value.artifact_reference == "adjudications/set-0001.json"


def test_bypassed_decision_ordering_is_rejected_at_set_level(tmp_path):
    # Each decision individually is valid; only the SET rule (canonical ordering)
    # is violated, which per-decision revalidation cannot detect.
    content = parsed()
    loaded_set = _decision_set(tmp_path, content.sha256)
    reversed_decisions = tuple(reversed(loaded_set.model.decisions))
    forged = loaded_set.model_copy(update={
        "model": loaded_set.model.model_copy(update={"decisions": reversed_decisions})})
    with pytest.raises(ObservationTargetBindingError) as ei:
        _bind_with_set(forged, content)
    assert ei.value.reason_code == "decision_set_invalid"


def test_wrapper_version_disagreeing_with_the_stamp_is_rejected(tmp_path):
    content = parsed()
    loaded_set = _decision_set(tmp_path, content.sha256)
    forged = loaded_set.model_copy(update={"version": "9.9.9"})
    with pytest.raises(ObservationTargetBindingError) as ei:
        _bind_with_set(forged, content)
    assert ei.value.reason_code == "decision_set_invalid"


def test_model_construct_wrapper_with_a_wrong_inner_model_is_rejected(tmp_path):
    content = parsed()
    forged = rd_mod.LoadedObservationTargetResolutionDecisionSet.model_construct(
        model=object(), version="0.1.0", sha256="d" * 64,
        artifact_reference="adjudications/set-0001.json")
    with pytest.raises(ObservationTargetBindingError) as ei:
        _bind_with_set(forged, content)
    assert ei.value.reason_code == "decision_set_invalid"


def test_decision_set_rejection_leaks_no_raw_pydantic_or_content(tmp_path):
    content = parsed()
    loaded_set = _decision_set(tmp_path, content.sha256)
    forged = loaded_set.model_copy(update={
        "model": loaded_set.model.model_copy(update={"case_id": "SECRET-CASE"})})
    with pytest.raises(ObservationTargetBindingError) as ei:
        _bind_with_set(forged, content)
    # case_id is a set-level pin, so this is caught as a binding mismatch, not a
    # revalidation failure — either way no raw text escapes.
    assert ei.value.reason_code in ("decision_set_invalid", "decision_set_binding_mismatch")
    text = str(ei.value)
    assert "SECRET-CASE" not in text
    assert "ValidationError" not in text and "pydantic" not in text.lower()


def test_genuine_loader_set_and_tuple_path_both_still_pass(tmp_path):
    # Regression: the happy path through the real loader is unchanged, and it
    # yields the same binding as the in-process tuple channel.
    content = parsed()
    persisted = _decision_set(tmp_path, content.sha256)
    from_loader = rd_mod.load_observation_target_resolution_decision_set(
        persisted.artifact_reference, source_root=tmp_path,
        expected_sha256=persisted.sha256)
    assert _bind_with_set(from_loader, content) == build(content=content)


# --- observation_target_binding@0.2.0 task-stage successor (ADR-029) --------


TASK_OBS = "SYNTH-TASK-OBS-0001"
BINDING_HASH_V2 = model_contract_hash(
    otb_mod.ObservationTargetBindingV2, "observation_target_binding", "0.2.0")


def task_parsed(**over):
    return parsed(entities=[("task", TASK_OBS)], stage="task_extraction", **over)


def build_task(*, snapshot=SNAP, content=None, entries=None):
    if entries is None:
        entries = (decision(TASK_OBS, "task", CANON_TASK),)
    return build_observation_target_binding(
        eval_run_id=RUN, case=_case(stage="task_extraction"), company_id=COMPANY,
        resolution=resolution(), parsed_prediction_content=content or task_parsed(),
        target_registry=REGISTRY, resolution_entries=entries, parent_snapshot=snapshot)


def test_protected_v01_contract_hash_unchanged():
    # Frozen literal: the capability contract identity must never drift.
    assert BINDING_HASH == \
        "f3ec0e0f2db9185333c667a6d7a52bf64a3b2a21b65bf1cbd90fa582ed67acd2"


def test_v2_contract_stamp_hash_and_required_pins():
    b = build_task()
    assert type(b) is otb_mod.ObservationTargetBindingV2
    assert b.contract.contract_id == "observation_target_binding"
    assert b.contract.contract_version == "0.2.0"
    assert b.contract.contract_hash == BINDING_HASH_V2
    assert BINDING_HASH_V2 == \
        "658f2050a5ecf768ee8ee7384a8892bbe52209b122f4ca15f78d34ad31b924a1"
    assert BINDING_HASH_V2 != BINDING_HASH
    # The pins are REQUIRED fields carrying the exact supplied snapshot identity.
    assert b.parent_observation_snapshot_version == SNAP.version
    assert b.parent_observation_snapshot_sha256 == SNAP.sha256
    assert otb_mod.ObservationTargetBindingV2.model_fields[
        "parent_observation_snapshot_version"].is_required()
    assert otb_mod.ObservationTargetBindingV2.model_fields[
        "parent_observation_snapshot_sha256"].is_required()


def test_capability_builder_still_emits_v01_byte_identically():
    b = build()
    assert type(b) is ObservationTargetBinding
    assert b.contract.contract_version == "0.1.0"
    assert b.contract.contract_hash == BINDING_HASH
    # v0.1 keeps its invariant pair untouched: pins present iff parents exist.
    from dynamic_ai_products.evaluation.contracts import canonical_contract_bytes
    dumped = canonical_contract_bytes(b.model_dump(mode="json", exclude_unset=True))
    assert b'"contract_version":"0.1.0"' in dumped
    assert BINDING_HASH.encode() in dumped


def test_task_builder_requires_the_parent_snapshot():
    with pytest.raises(ObservationTargetBindingError) as ei:
        build_task(snapshot=None)
    assert ei.value.reason_code == "parent_snapshot_required"


def test_task_builder_verifies_case_context_against_the_snapshot():
    bad_model = SNAP.model.model_copy(update={"case_id": "SYNTH-CASE-OTHER"})
    bad = SNAP.model_copy(update={"model": bad_model})
    with pytest.raises(ObservationTargetBindingError) as ei:
        build_task(snapshot=bad)
    assert ei.value.reason_code == "case_context_mismatch"


def test_v2_rejects_capability_stage():
    payload = build_task().model_dump(mode="json", exclude_unset=True)
    payload["stage"] = "capability_extraction"
    with pytest.raises(PydanticValidationError) as ei:
        otb_mod.ObservationTargetBindingV2.model_validate(payload)
    assert "binds only the task_extraction stage" in str(ei.value)


@pytest.mark.parametrize(
    "field", ["parent_observation_snapshot_version", "parent_observation_snapshot_sha256"])
def test_v2_pins_cannot_be_omitted_or_null(field):
    payload = build_task().model_dump(mode="json", exclude_unset=True)
    missing = {k: v for k, v in payload.items() if k != field}
    with pytest.raises(PydanticValidationError) as omitted:
        otb_mod.ObservationTargetBindingV2.model_validate(missing)
    assert any(e["type"] == "missing" for e in omitted.value.errors())
    with pytest.raises(PydanticValidationError):
        otb_mod.ObservationTargetBindingV2.model_validate({**payload, field: None})


def test_v01_task_document_without_pins_stays_valid_v01():
    # v0.1 semantics are untouched: a pin-less task-stage v0.1 document remains a
    # valid v0.1 artifact. P2's parent-pin equality rejects it downstream
    # (covered in test_validation_inputs), so nothing weakens silently.
    b = build_task()
    payload = b.model_dump(mode="json", exclude_unset=True)
    payload.pop("parent_observation_snapshot_version")
    payload.pop("parent_observation_snapshot_sha256")
    payload["contract"] = {
        "contract_id": "observation_target_binding", "contract_version": "0.1.0",
        "contract_hash": BINDING_HASH}
    v1 = ObservationTargetBinding.model_validate(payload)
    assert type(v1) is ObservationTargetBinding
    assert v1.parent_observation_snapshot_version is None
    # And a v0.1 stamp carrying pins with no parent entry stays forbidden.
    with pytest.raises(PydanticValidationError) as ei:
        ObservationTargetBinding.model_validate({
            **b.model_dump(mode="json", exclude_unset=True),
            "contract": payload["contract"]})
    assert "parent_snapshot_pins_forbidden" in str(ei.value)


def test_v2_persist_load_revalidate_roundtrip(tmp_path):
    # The REAL successor path: task builder -> v0.2 persist -> v0.2 load ->
    # fail-closed v0.2 revalidation, with no model_construct stand-ins.
    root = _run(tmp_path)
    b = build_task()
    persisted = persist_observation_target_binding(b, eval_root=root, eval_run_id=RUN)
    assert isinstance(persisted, LoadedObservationTargetBinding)
    assert persisted.version == "0.2.0"
    dest = root / RUN / "snapshots" / "observation_target_binding.json"
    assert persisted.sha256 == sha256_bytes(dest.read_bytes())
    reloaded = load_observation_target_binding(
        persisted.artifact_reference, eval_root=root, expected_sha256=persisted.sha256)
    assert type(reloaded.model) is otb_mod.ObservationTargetBindingV2
    assert reloaded.version == "0.2.0"
    assert reloaded.model == b
    assert reloaded.model.parent_observation_snapshot_sha256 == SNAP.sha256
    # The reloaded v0.2 model passes fail-closed revalidation in the accessors.
    mapped = observations_by_canonical_target(reloaded.model)
    assert mapped == {CANON_TASK: (TASK_OBS,)}
    assert unresolved_observation_ids(reloaded.model) == ()
    # Write-once holds for the successor exactly as for v0.1.
    with pytest.raises(ObservationTargetBindingError) as ei:
        persist_observation_target_binding(b, eval_root=root, eval_run_id=RUN)
    assert ei.value.reason_code == "artifact_exists"


def test_v2_wrapper_union_accepts_both_versions(tmp_path):
    root = _run(tmp_path)
    v2 = persist_observation_target_binding(build_task(), eval_root=root, eval_run_id=RUN)
    assert isinstance(v2.model, otb_mod.ObservationTargetBindingV2)
    wrapped = LoadedObservationTargetBinding(
        model=build(), version="0.1.0", sha256="d" * 64, artifact_reference="x/y.json")
    assert isinstance(wrapped.model, ObservationTargetBinding)


def test_v2_construct_tamper_fails_closed_everywhere(tmp_path):
    root = _run(tmp_path)
    b = build_task()
    tampered = b.model_construct(**{**dict(b), "stage": "capability_extraction"})
    with pytest.raises(ObservationTargetBindingError) as by_accessor:
        observations_by_canonical_target(tampered)
    assert by_accessor.value.reason_code == "model_validation"
    with pytest.raises(ObservationTargetBindingError) as by_persist:
        persist_observation_target_binding(tampered, eval_root=root, eval_run_id=RUN)
    assert by_persist.value.reason_code == "model_validation"
    blanked = b.model_construct(**{**dict(b), "parent_observation_snapshot_version": " "})
    with pytest.raises(ObservationTargetBindingError):
        observations_by_canonical_target(blanked)


def test_v2_persisted_byte_tamper_detected(tmp_path):
    root = _run(tmp_path)
    persisted = persist_observation_target_binding(
        build_task(), eval_root=root, eval_run_id=RUN)
    dest = root / RUN / "snapshots" / "observation_target_binding.json"
    doc = json.loads(dest.read_text())
    doc["parent_observation_snapshot_sha256"] = "0" * 64
    dest.write_bytes((json.dumps(doc) + "\n").encode())
    with pytest.raises(ObservationTargetBindingError) as ei:
        load_observation_target_binding(
            persisted.artifact_reference, eval_root=root,
            expected_sha256=persisted.sha256)
    assert ei.value.reason_code == "expected_hash_mismatch"


def test_v2_export_and_count():
    assert "ObservationTargetBindingV2" in evaluation_pkg.__all__
    assert evaluation_pkg.__all__.count("ObservationTargetBindingV2") == 1
    assert evaluation_pkg.ObservationTargetBindingV2 is otb_mod.ObservationTargetBindingV2
    assert len(evaluation_pkg.__all__) == 577
