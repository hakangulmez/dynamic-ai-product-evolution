"""Slice 12E: assertion-owned gold assertion set."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import gold as gold_mod
from dynamic_ai_products.evaluation.cases import load_case
from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.gold import (
    BoundGoldAssertionSet,
    GOLD_FIELD_VALUE_OPERATORS,
    GoldAssertionSet,
    GoldAssertionSetError,
    GoldBindingError,
    LoadedGoldAssertionSet,
    ResolvedGoldAssertion,
    bind_gold_assertion_set,
    gold_assertion_set_hash,
    load_gold_assertion_set,
    persist_gold_assertion_set,
)
from dynamic_ai_products.evaluation.references import (
    load_target_registry,
    resolve_case_references,
)
from dynamic_ai_products.evaluation.scoring_config import load_scoring_gate_config
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness"
GOLD_REL = "gold/gold_assertion_set.json"
MODEL_HASH = "48bb5f185072ed004aa4fcfda30408ff710406ac42bc5ea611d3f5a1fb118cfe"
CONTRACT_STAMP = {
    "contract_id": "gold_assertion_set",
    "contract_version": "0.1.0",
    "contract_hash": MODEL_HASH,
}
REGISTRY_SHA = "10e0cfa69a345583832327a4085e7e5c50e527385e03a420170ef3924c92e01c"

# The twelve protected model-contract hashes that Slice 12E must not disturb.
PROTECTED_HASHES = {
    ("evaluation_run_manifest", "0.1.0"): "7f8909d8e7059952c933c8e30f43044178b3f8a21d4baaa77bfb5c786b38d6ee",
    ("evaluation_run_manifest", "0.2.0"): "6918e96c0f9d2066e89eaf6a699c00b36e1e52e5b5c74ec0e926533eacaf84d6",
    ("prediction_envelope", "0.1.0"): "5ac06fb78220c3f7369863cda32ee914a1d33ff01020fc01e57d9bd0ccbb18a3",
    ("assertion_outcome", "0.1.0"): "4af3a9eb7c99e3e3ba088784b3395f4b6920fa1f8061f7bb1118af6bd2720bd6",
    ("case_set_manifest", "0.1.0"): "0b464d786d5a8addb1305c21c2d93b01c834e8f398fd3b12be30d1fc49083bb5",
    ("validator_finding", "0.1.0"): "96f63fee300d363a662f4f956bacccdca596acfb0f22bf7039aa1335b6d61292",
    ("metric_report", "0.1.0"): "d9e3f6d7399af628b38754758a7cb580e57955ad695ee7d92fb56c67c4ceac39",
    ("comparison_manifest", "0.2.0"): "6a1253b72664bff73e872d1230fb3d52772a438f55915406010e105b4f5d29a5",
    ("evaluation_stage_profile_registry", "0.1.0"): "cbd567cb0367cabe5f680957a8da29d9018ccd50512c91e0f9c393de2c7ee4dd",
    ("source_passage_snapshot_manifest", "0.1.0"): "c169be58c6df0370e5f51f276a528f452252e9796d19fb5e3a905cd34a3c21a5",
    ("parsed_prediction_content", "0.1.0"): "ffeae7ab54fa03948f4498a3ceb5a634b17444791fd91f94a57c086afedbda3e",
    ("evaluation_semantic_adapter_registry", "0.1.0"): "757766e9f965a18cee4d86ff3490ba5f66076f75993339fc52b9ff72b3812c5c",
}


def _prov(**ov):
    base = {
        "gold_origin": "constructed",
        "verification_status": "verified",
        "verification_method": "construction_review",
        "annotator_ids": ["synthetic-annotator-0001"],
        "reviewer_ids": ["synthetic-reviewer-0001"],
        "annotation_timestamps": ["2026-01-15T10:00:00+00:00"],
        "source_packet_hash": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
        "case_version": "synth-case-v1",
        "change_reason": "initial synthetic construction",
    }
    base.update(ov)
    return base


def _entry(case_id, assertion_id, kind, canon, *, semver=None, chash=None, **ov):
    e = {"case_id": case_id, "assertion_id": assertion_id}
    if semver is not None:
        e["assertion_semantic_version"] = semver
    if chash is not None:
        e["assertion_contract_hash"] = chash
    e["assertion_kind"] = kind
    e["canonical_target_reference"] = canon
    e["provenance"] = _prov()
    e.update(ov)
    return e


def _set(entries, version="synth-gold-set-v1"):
    return {"contract": dict(CONTRACT_STAMP), "gold_set_version": version, "entries": entries}


def _loaded(gold_dict, *, sha256="0" * 64, reference="gold/g.json"):
    model = GoldAssertionSet.model_validate(gold_dict)
    return LoadedGoldAssertionSet(
        model=model, version=model.gold_set_version, sha256=sha256, artifact_reference=reference
    )


def _fixture_dict():
    return json.loads((FX / "gold" / "gold_assertion_set.json").read_bytes())


# --- Bindings (real registry + cases + resolutions) -----------------------


def _bindings():
    registry = load_target_registry("valid_target_registry.json", eval_root=FX / "configs")
    scoring = load_scoring_gate_config("valid_scoring_gate_config.json", eval_root=FX / "configs")
    full = load_case("valid_full_case.json", eval_root=FX / "cases")
    mini = load_case("valid_minimal_case.json", eval_root=FX / "cases")
    cases = {full.case_id: full, mini.case_id: mini}
    resolutions = {
        full.case_id: resolve_case_references(full, registry=registry, scoring_config=scoring),
        mini.case_id: resolve_case_references(mini, registry=registry, scoring_config=scoring),
    }
    return registry, cases, resolutions


# --- Contract identity + surface ------------------------------------------


def test_model_contract_hash_locked():
    assert model_contract_hash(GoldAssertionSet, "gold_assertion_set", "0.1.0") == MODEL_HASH


def test_public_surface():
    assert set(gold_mod.__all__) == {
        "BoundGoldAssertionSet",
        "GOLD_FIELD_VALUE_OPERATORS",
        "GoldAssertionSet",
        "GoldAssertionSetError",
        "GoldBindingError",
        "LoadedGoldAssertionSet",
        "ResolvedGoldAssertion",
        "bind_gold_assertion_set",
        "gold_assertion_set_hash",
        "load_gold_assertion_set",
        "persist_gold_assertion_set",
    }
    assert GOLD_FIELD_VALUE_OPERATORS == frozenset(
        {"equals", "not_equals", "in_set", "not_in_set", "gte", "gt", "lte", "lt"}
    )


def test_operator_vocabulary_no_private_leak():
    assert "_GoldAssertionEntry" not in evaluation_pkg.__all__
    assert "_GoldFieldValuePayload" not in evaluation_pkg.__all__
    assert "_GoldProvenance" not in evaluation_pkg.__all__


def test_fixture_loads_and_stamps():
    loaded = load_gold_assertion_set(GOLD_REL, eval_root=FX)
    assert isinstance(loaded, LoadedGoldAssertionSet)
    assert len(loaded.model.entries) == 4
    assert loaded.version == "synth-gold-set-v1"
    assert loaded.model.contract.contract_hash == MODEL_HASH


def test_strict_frozen_extra_forbid():
    loaded = load_gold_assertion_set(GOLD_REL, eval_root=FX)
    with pytest.raises(PydanticValidationError):
        loaded.model.gold_set_version = "mutated"  # type: ignore[misc]
    bad = _fixture_dict()
    bad["unexpected"] = 1
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(bad)


# --- Assertion-owned binding ----------------------------------------------


def test_binding_positive():
    registry, cases, resolutions = _bindings()
    loaded = load_gold_assertion_set(GOLD_REL, eval_root=FX)
    bound = bind_gold_assertion_set(
        loaded, registry=registry, cases=cases, resolutions=resolutions
    )
    assert isinstance(bound, BoundGoldAssertionSet)
    assert len(bound.entries) == 4
    assert all(isinstance(e, ResolvedGoldAssertion) for e in bound.entries)
    by_target = {e.canonical_target_reference: e for e in bound.entries}
    # opaque contract identity bound exactly to the gold-contract target
    roadmap = by_target["SYNTH.PRODUCT.ROADMAP_ONLY"]
    assert roadmap.assertion_contract_hash == "synthetic-opaque-assertion-contract-identity-0002"
    assert roadmap.contract_id == "synth-gold-contract"
    alpha = by_target["SYNTH.PRODUCT.ALPHA"]
    assert alpha.contract_id == "synth-product-contract"


def test_binding_unresolvable_case():
    registry, cases, resolutions = _bindings()
    loaded = _loaded(_set([_entry("NO-SUCH-CASE", "A", "expected_entity",
                                  "SYNTH.PRODUCT.CAPABILITY.TASK", semver="0.1.0")]))
    with pytest.raises(GoldBindingError) as exc:
        bind_gold_assertion_set(loaded, registry=registry, cases=cases, resolutions=resolutions)
    assert exc.value.reason_code == "unresolvable_gold_case"


def test_binding_unresolvable_assertion():
    registry, cases, resolutions = _bindings()
    loaded = _loaded(_set([_entry("SYNTH-CASE-MIN-0001", "NO-SUCH-A", "expected_entity",
                                  "SYNTH.PRODUCT.CAPABILITY.TASK", semver="0.1.0")]))
    with pytest.raises(GoldBindingError) as exc:
        bind_gold_assertion_set(loaded, registry=registry, cases=cases, resolutions=resolutions)
    assert exc.value.reason_code == "unresolvable_gold_assertion"


def test_binding_kind_mismatch():
    registry, cases, resolutions = _bindings()
    loaded = _loaded(_set([_entry("SYNTH-CASE-MIN-0001", "SYNTH-CASE-MIN-0001-A1",
                                  "forbidden_entity", "SYNTH.PRODUCT.CAPABILITY.TASK",
                                  semver="0.1.0")]))
    with pytest.raises(GoldBindingError) as exc:
        bind_gold_assertion_set(loaded, registry=registry, cases=cases, resolutions=resolutions)
    assert exc.value.reason_code == "gold_assertion_kind_mismatch"


def test_binding_identity_mismatch_semver():
    registry, cases, resolutions = _bindings()
    loaded = _loaded(_set([_entry("SYNTH-CASE-MIN-0001", "SYNTH-CASE-MIN-0001-A1",
                                  "expected_entity", "SYNTH.PRODUCT.CAPABILITY.TASK",
                                  semver="9.9.9")]))
    with pytest.raises(GoldBindingError) as exc:
        bind_gold_assertion_set(loaded, registry=registry, cases=cases, resolutions=resolutions)
    assert exc.value.reason_code == "gold_assertion_identity_mismatch"


def test_binding_identity_mismatch_spurious_chash():
    # The owning assertion is semver-only; a gold contract_hash it lacks is a mismatch.
    registry, cases, resolutions = _bindings()
    loaded = _loaded(_set([_entry("SYNTH-CASE-MIN-0001", "SYNTH-CASE-MIN-0001-A1",
                                  "expected_entity", "SYNTH.PRODUCT.CAPABILITY.TASK",
                                  semver="0.1.0", chash="unexpected-extra-identity")]))
    with pytest.raises(GoldBindingError) as exc:
        bind_gold_assertion_set(loaded, registry=registry, cases=cases, resolutions=resolutions)
    assert exc.value.reason_code == "gold_assertion_identity_mismatch"


def test_binding_opaque_contract_hash_binds_exactly():
    registry, cases, resolutions = _bindings()
    loaded = _loaded(_set([_entry("SYNTH-CASE-FULL-0002", "SYNTH-CASE-FULL-0002-A2",
                                  "forbidden_entity", "SYNTH.PRODUCT.ROADMAP_ONLY",
                                  chash="synthetic-opaque-assertion-contract-identity-0002")]))
    bound = bind_gold_assertion_set(loaded, registry=registry, cases=cases, resolutions=resolutions)
    assert bound.entries[0].assertion_contract_hash == (
        "synthetic-opaque-assertion-contract-identity-0002"
    )


def test_binding_unresolvable_resolution():
    registry, cases, resolutions = _bindings()
    partial = {k: v for k, v in resolutions.items() if k != "SYNTH-CASE-MIN-0001"}
    loaded = _loaded(_set([_entry("SYNTH-CASE-MIN-0001", "SYNTH-CASE-MIN-0001-A1",
                                  "expected_entity", "SYNTH.PRODUCT.CAPABILITY.TASK",
                                  semver="0.1.0")]))
    with pytest.raises(GoldBindingError) as exc:
        bind_gold_assertion_set(loaded, registry=registry, cases=cases, resolutions=partial)
    assert exc.value.reason_code == "unresolvable_gold_resolution"


def test_binding_registry_resolution_mismatch():
    registry, cases, resolutions = _bindings()
    tampered = resolutions["SYNTH-CASE-MIN-0001"].model_copy(
        update={"target_registry_sha256": "f" * 64}
    )
    res = dict(resolutions)
    res["SYNTH-CASE-MIN-0001"] = tampered
    loaded = _loaded(_set([_entry("SYNTH-CASE-MIN-0001", "SYNTH-CASE-MIN-0001-A1",
                                  "expected_entity", "SYNTH.PRODUCT.CAPABILITY.TASK",
                                  semver="0.1.0")]))
    with pytest.raises(GoldBindingError) as exc:
        bind_gold_assertion_set(loaded, registry=registry, cases=cases, resolutions=res)
    assert exc.value.reason_code == "registry_resolution_mismatch"


def test_binding_alias_rejected():
    registry, cases, resolutions = _bindings()
    loaded = _loaded(_set([_entry("SYNTH-CASE-MIN-0001", "SYNTH-CASE-MIN-0001-A1",
                                  "expected_entity", "SYNTH.ALIAS.TASK", semver="0.1.0")]))
    with pytest.raises(GoldBindingError) as exc:
        bind_gold_assertion_set(loaded, registry=registry, cases=cases, resolutions=resolutions)
    assert exc.value.reason_code == "gold_reference_is_alias"


def test_binding_canonical_not_resolved_for_assertion():
    registry, cases, resolutions = _bindings()
    # a real canonical, but not one this assertion resolves
    loaded = _loaded(_set([_entry("SYNTH-CASE-MIN-0001", "SYNTH-CASE-MIN-0001-A1",
                                  "expected_entity", "SYNTH.PRODUCT.ALPHA", semver="0.1.0")]))
    with pytest.raises(GoldBindingError) as exc:
        bind_gold_assertion_set(loaded, registry=registry, cases=cases, resolutions=resolutions)
    assert exc.value.reason_code == "gold_target_not_resolved_for_assertion"


def test_binding_type_guards():
    registry, cases, resolutions = _bindings()
    loaded = load_gold_assertion_set(GOLD_REL, eval_root=FX)
    with pytest.raises(TypeError):
        bind_gold_assertion_set(loaded.model, registry=registry, cases=cases, resolutions=resolutions)
    with pytest.raises(TypeError):
        bind_gold_assertion_set(loaded, registry=object(), cases=cases, resolutions=resolutions)


# --- Assertion identity semantics -----------------------------------------


def test_opaque_contract_hash_accepted_not_sha():
    entry = _entry("C", "A", "expected_entity", "T", chash="not-a-sha-256-value")
    model = GoldAssertionSet.model_validate(_set([entry]))
    assert model.entries[0].assertion_contract_hash == "not-a-sha-256-value"


def test_identity_presence_required():
    entry = _entry("C", "A", "expected_entity", "T")  # neither identity
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


def test_explicit_null_identity_rejected():
    entry = _entry("C", "A", "expected_entity", "T", semver="0.1.0")
    entry["assertion_contract_hash"] = None
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


# --- Payload / kind coherence ---------------------------------------------


def _fv_payload(**ov):
    base = {
        "field_path": "prediction.field",
        "operator": "equals",
        "value_type": "string",
        "expected_values": ["x"],
    }
    base.update(ov)
    return base


def _ev_payload(**ov):
    base = {
        "expected_source_id": "SRC-1",
        "expected_passage_id": "PSG-1",
        "expected_publication_date": "2025-06-30",
        "match_mode": "exact_passage",
    }
    base.update(ov)
    return base


def test_field_value_requires_payload():
    entry = _entry("C", "A", "field_value", "T", semver="0.1.0")
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


def test_field_value_with_payload_ok():
    entry = _entry("C", "A", "field_value", "T", semver="0.1.0", field_value_payload=_fv_payload())
    model = GoldAssertionSet.model_validate(_set([entry]))
    assert model.entries[0].field_value_payload is not None


def test_field_value_with_evidence_payload_rejected():
    entry = _entry("C", "A", "field_value", "T", semver="0.1.0",
                   field_value_payload=_fv_payload(), evidence_provenance_payload=_ev_payload())
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


def test_evidence_requires_payload():
    entry = _entry("C", "A", "evidence_provenance", "T", semver="0.1.0")
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


def test_evidence_with_payload_ok():
    entry = _entry("C", "A", "evidence_provenance", "T", semver="0.1.0",
                   evidence_provenance_payload=_ev_payload())
    model = GoldAssertionSet.model_validate(_set([entry]))
    assert model.entries[0].evidence_provenance_payload is not None


def test_expected_entity_with_payload_rejected():
    entry = _entry("C", "A", "expected_entity", "T", semver="0.1.0",
                   field_value_payload=_fv_payload())
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


def test_deterministic_validation_rejected():
    entry = _entry("C", "A", "deterministic_validation", "T", semver="0.1.0")
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


# --- Operator / value-shape rules -----------------------------------------


@pytest.mark.parametrize(
    "operator,value_type,values",
    [
        ("equals", "string", ["a"]),
        ("not_equals", "integer", [3]),
        ("in_set", "string", ["a", "b"]),
        ("not_in_set", "number", [1.5, 2.5]),
        ("gte", "integer", [10]),
        ("gt", "number", [1.0]),
        ("lte", "date", ["2025-01-01"]),
        ("lt", "date", ["2025-12-31"]),
    ],
)
def test_field_value_valid_shapes(operator, value_type, values):
    entry = _entry("C", "A", "field_value", "T", semver="0.1.0",
                   field_value_payload=_fv_payload(operator=operator, value_type=value_type,
                                                   expected_values=values))
    GoldAssertionSet.model_validate(_set([entry]))


def test_operator_not_in_literal_rejected():
    entry = _entry("C", "A", "field_value", "T", semver="0.1.0",
                   field_value_payload=_fv_payload(operator="matches_regex"))
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


@pytest.mark.parametrize("value_type", ["string", "boolean"])
def test_ordering_on_non_ordered_type_rejected(value_type):
    values = ["a"] if value_type == "string" else [True]
    entry = _entry("C", "A", "field_value", "T", semver="0.1.0",
                   field_value_payload=_fv_payload(operator="gte", value_type=value_type,
                                                   expected_values=values))
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


def test_scalar_operator_arity_rejected():
    entry = _entry("C", "A", "field_value", "T", semver="0.1.0",
                   field_value_payload=_fv_payload(operator="equals", expected_values=["a", "b"]))
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


def test_set_operator_empty_rejected():
    entry = _entry("C", "A", "field_value", "T", semver="0.1.0",
                   field_value_payload=_fv_payload(operator="in_set", expected_values=[]))
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


def test_set_operator_duplicate_rejected():
    entry = _entry("C", "A", "field_value", "T", semver="0.1.0",
                   field_value_payload=_fv_payload(operator="in_set",
                                                   expected_values=["a", "a"]))
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


def test_value_type_mismatch_bool_for_integer():
    entry = _entry("C", "A", "field_value", "T", semver="0.1.0",
                   field_value_payload=_fv_payload(operator="equals", value_type="integer",
                                                   expected_values=[True]))
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


def test_value_type_non_canonical_date_rejected():
    entry = _entry("C", "A", "field_value", "T", semver="0.1.0",
                   field_value_payload=_fv_payload(operator="equals", value_type="date",
                                                   expected_values=["2025-6-30"]))
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


@pytest.mark.parametrize("path", ["", " x", "a..b", "a.b ", "a-b"])
def test_field_path_rejected(path):
    entry = _entry("C", "A", "field_value", "T", semver="0.1.0",
                   field_value_payload=_fv_payload(field_path=path))
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


# --- Evidence provenance payload ------------------------------------------


def test_evidence_exact_passage_requires_passage_id():
    payload = _ev_payload(match_mode="exact_passage")
    del payload["expected_passage_id"]
    entry = _entry("C", "A", "evidence_provenance", "T", semver="0.1.0",
                   evidence_provenance_payload=payload)
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


def test_evidence_same_document_forbids_passage_id():
    payload = _ev_payload(match_mode="same_source_document")
    entry = _entry("C", "A", "evidence_provenance", "T", semver="0.1.0",
                   evidence_provenance_payload=payload)
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


def test_evidence_same_document_ok():
    payload = _ev_payload(match_mode="same_source_document")
    del payload["expected_passage_id"]
    entry = _entry("C", "A", "evidence_provenance", "T", semver="0.1.0",
                   evidence_provenance_payload=payload)
    GoldAssertionSet.model_validate(_set([entry]))


def test_evidence_non_canonical_date_rejected():
    payload = _ev_payload(expected_publication_date="2025/06/30")
    entry = _entry("C", "A", "evidence_provenance", "T", semver="0.1.0",
                   evidence_provenance_payload=payload)
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


# --- Provenance -----------------------------------------------------------


def test_provenance_bad_origin_rejected():
    entry = _entry("C", "A", "expected_entity", "T", semver="0.1.0",
                   provenance=_prov(gold_origin="fabricated"))
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


def test_provenance_empty_annotators_rejected():
    entry = _entry("C", "A", "expected_entity", "T", semver="0.1.0",
                   provenance=_prov(annotator_ids=[]))
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


def test_provenance_duplicate_annotators_rejected():
    entry = _entry("C", "A", "expected_entity", "T", semver="0.1.0",
                   provenance=_prov(annotator_ids=["a", "a"]))
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


def test_provenance_non_rfc3339_timestamp_rejected():
    entry = _entry("C", "A", "expected_entity", "T", semver="0.1.0",
                   provenance=_prov(annotation_timestamps=["2026-01-15"]))
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


def test_provenance_bad_source_packet_hash_rejected():
    entry = _entry("C", "A", "expected_entity", "T", semver="0.1.0",
                   provenance=_prov(source_packet_hash="not-hex"))
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


def test_provenance_dual_adjudication_requires_reference():
    entry = _entry("C", "A", "expected_entity", "T", semver="0.1.0",
                   provenance=_prov(verification_method="dual_independent_adjudication"))
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


def test_provenance_dual_adjudication_with_reference_ok():
    entry = _entry("C", "A", "expected_entity", "T", semver="0.1.0",
                   provenance=_prov(verification_method="dual_independent_adjudication",
                                    adjudication_reference="ADJ-0001"))
    GoldAssertionSet.model_validate(_set([entry]))


def test_superseded_by_self_identity_rejected():
    entry = _entry(
        "SYNTH-CASE-FULL-0002", "SYNTH-CASE-FULL-0002-A1", "expected_entity", "T",
        semver="0.1.0",
        provenance=_prov(superseded_by="SYNTH-CASE-FULL-0002:SYNTH-CASE-FULL-0002-A1"),
    )
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([entry]))


def test_superseded_by_non_self_ok():
    entry = _entry(
        "SYNTH-CASE-FULL-0002", "SYNTH-CASE-FULL-0002-A1", "expected_entity", "T",
        semver="0.1.0",
        provenance=_prov(superseded_by="SYNTH-CASE-FULL-0002:SYNTH-CASE-FULL-0002-A2"),
    )
    GoldAssertionSet.model_validate(_set([entry]))


# --- Set-level invariants --------------------------------------------------


def test_empty_entries_rejected():
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([]))


def test_out_of_order_entries_rejected():
    data = _fixture_dict()
    data["entries"] = list(reversed(data["entries"]))
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(data)


def test_duplicate_identity_rejected():
    e = _entry("C", "A", "expected_entity", "T", semver="0.1.0")
    with pytest.raises(PydanticValidationError):
        GoldAssertionSet.model_validate(_set([copy.deepcopy(e), copy.deepcopy(e)]))


# --- Hash identities -------------------------------------------------------


def test_content_hash_deterministic_and_distinct():
    loaded = load_gold_assertion_set(GOLD_REL, eval_root=FX)
    h1 = gold_assertion_set_hash(loaded.model)
    h2 = gold_assertion_set_hash(loaded.model)
    assert h1 == h2 and len(h1) == 64
    raw_sha = sha256_bytes((FX / "gold" / "gold_assertion_set.json").read_bytes())
    assert h1 != raw_sha  # content hash (no newline) != raw-byte sha
    assert h1 != MODEL_HASH  # content hash != model-contract hash


# --- Persistence -----------------------------------------------------------


def test_persist_write_once_and_read_back(tmp_path):
    (tmp_path / "run-1").mkdir()
    loaded = load_gold_assertion_set(GOLD_REL, eval_root=FX)
    result = persist_gold_assertion_set(loaded.model, eval_root=tmp_path, eval_run_id="run-1")
    dest = tmp_path / "run-1" / "snapshots" / "gold_assertion_set.json"
    raw = dest.read_bytes()
    assert raw.endswith(b"\n")
    assert result.sha256 == sha256_bytes(raw)
    # content hash (no newline) differs from the raw persisted-byte sha
    assert gold_assertion_set_hash(loaded.model) != result.sha256
    with pytest.raises(GoldAssertionSetError) as exc:
        persist_gold_assertion_set(loaded.model, eval_root=tmp_path, eval_run_id="run-1")
    assert exc.value.reason_code == "snapshot_exists"


def test_persist_round_trips(tmp_path):
    (tmp_path / "run-2").mkdir()
    loaded = load_gold_assertion_set(GOLD_REL, eval_root=FX)
    persist_gold_assertion_set(loaded.model, eval_root=tmp_path, eval_run_id="run-2")
    reloaded = load_gold_assertion_set(
        "run-2/snapshots/gold_assertion_set.json", eval_root=tmp_path
    )
    assert reloaded.model == loaded.model


# --- Path / strict-parse security -----------------------------------------


def _write(tmp_path, name, data_bytes):
    p = tmp_path / name
    p.write_bytes(data_bytes)
    return name


def test_expected_hash_mismatch(tmp_path):
    name = _write(tmp_path, "g.json", json.dumps(_fixture_dict()).encode())
    with pytest.raises(GoldAssertionSetError) as exc:
        load_gold_assertion_set(name, eval_root=tmp_path, expected_sha256="0" * 64)
    assert exc.value.reason_code == "expected_hash_mismatch"


def test_traversal_reference_rejected(tmp_path):
    with pytest.raises(GoldAssertionSetError) as exc:
        load_gold_assertion_set("../escape.json", eval_root=tmp_path)
    assert exc.value.reason_code == "unsafe_reference"


def test_absolute_reference_rejected(tmp_path):
    with pytest.raises(GoldAssertionSetError) as exc:
        load_gold_assertion_set("/etc/hosts", eval_root=tmp_path)
    assert exc.value.reason_code == "unsafe_reference"


def test_symlink_artifact_rejected(tmp_path):
    target = tmp_path / "real.json"
    target.write_bytes(json.dumps(_fixture_dict()).encode())
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(GoldAssertionSetError) as exc:
        load_gold_assertion_set("link.json", eval_root=tmp_path)
    assert exc.value.reason_code == "artifact_symlink"


def test_missing_artifact_rejected(tmp_path):
    with pytest.raises(GoldAssertionSetError) as exc:
        load_gold_assertion_set("absent.json", eval_root=tmp_path)
    assert exc.value.reason_code == "artifact_missing"


def test_eval_root_symlink_rejected(tmp_path):
    real = tmp_path / "real_root"
    real.mkdir()
    link = tmp_path / "link_root"
    link.symlink_to(real)
    with pytest.raises(GoldAssertionSetError) as exc:
        load_gold_assertion_set("g.json", eval_root=link)
    assert exc.value.reason_code == "eval_root_symlink"


def test_duplicate_key_rejected(tmp_path):
    name = _write(tmp_path, "g.json", b'{"a": 1, "a": 2}')
    with pytest.raises(GoldAssertionSetError) as exc:
        load_gold_assertion_set(name, eval_root=tmp_path)
    assert exc.value.reason_code == "duplicate_key"


def test_non_finite_rejected(tmp_path):
    name = _write(tmp_path, "g.json", b'{"x": NaN}')
    with pytest.raises(GoldAssertionSetError) as exc:
        load_gold_assertion_set(name, eval_root=tmp_path)
    assert exc.value.reason_code == "non_finite"


def test_top_level_array_rejected(tmp_path):
    name = _write(tmp_path, "g.json", b"[]")
    with pytest.raises(GoldAssertionSetError) as exc:
        load_gold_assertion_set(name, eval_root=tmp_path)
    assert exc.value.reason_code == "top_level_type"


def test_model_validation_error(tmp_path):
    name = _write(tmp_path, "g.json", b'{"gold_set_version": "v"}')
    with pytest.raises(GoldAssertionSetError) as exc:
        load_gold_assertion_set(name, eval_root=tmp_path)
    assert exc.value.reason_code == "model_validation"


# --- Protected invariants --------------------------------------------------


def test_target_registry_byte_identity():
    observed = sha256_bytes((FX / "configs" / "valid_target_registry.json").read_bytes())
    assert observed == REGISTRY_SHA


def test_protected_contract_hashes():
    from dynamic_ai_products.evaluation import models as m
    from dynamic_ai_products.evaluation.comparator import ComparisonManifest
    from dynamic_ai_products.evaluation.metrics import MetricReport
    from dynamic_ai_products.evaluation.stage_profiles import StageProfileRegistry
    from dynamic_ai_products.evaluation.source_snapshot import SourcePassageSnapshotManifest
    from dynamic_ai_products.evaluation.prediction_content import ParsedPredictionContent
    from dynamic_ai_products.evaluation.semantic_adapters import EvaluationSemanticAdapterRegistry

    mapping = {
        ("evaluation_run_manifest", "0.1.0"): m.EvaluationRunManifest,
        ("evaluation_run_manifest", "0.2.0"): m.EvaluationRunManifestV2,
        ("prediction_envelope", "0.1.0"): m.PredictionEnvelope,
        ("assertion_outcome", "0.1.0"): m.AssertionOutcome,
        ("case_set_manifest", "0.1.0"): m.CaseSetManifest,
        ("validator_finding", "0.1.0"): m.ValidatorFinding,
        ("metric_report", "0.1.0"): MetricReport,
        ("comparison_manifest", "0.2.0"): ComparisonManifest,
        ("evaluation_stage_profile_registry", "0.1.0"): StageProfileRegistry,
        ("source_passage_snapshot_manifest", "0.1.0"): SourcePassageSnapshotManifest,
        ("parsed_prediction_content", "0.1.0"): ParsedPredictionContent,
        ("evaluation_semantic_adapter_registry", "0.1.0"): EvaluationSemanticAdapterRegistry,
    }
    for (cid, ver), cls in mapping.items():
        assert model_contract_hash(cls, cid, ver) == PROTECTED_HASHES[(cid, ver)]


# --- Import purity ---------------------------------------------------------


def test_import_no_io_no_hash_no_clock():
    code = "\n".join([
        "import sys, os, hashlib, importlib, time",
        "sys.path.insert(0, 'src')",
        "import pydantic",
        "import dynamic_ai_products, dynamic_ai_products.universe.io_utils",
        "import dynamic_ai_products.evaluation",
        "sys.modules.pop('dynamic_ai_products.evaluation.gold', None)",
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
        "importlib.import_module('dynamic_ai_products.evaluation.gold')",
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
