"""P1: run-external adjudication decision set (``observation_target_resolution_decision_set@0.1.0``).

This module is the canonical owner of the adjudication layer. The decision set is a
**human/adjudicator judgement** authored before any run exists: the adjudicator
parses the prediction in memory, takes the exact parsed-content artifact SHA-256
through the public preparation helper, and persists the typed set write-once under
the adjudication source root. The runner later re-derives the same parse and
verifies every pin. A hand-written JSON document is not a production authoring
path — only the typed persistence API is.
"""

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
from dynamic_ai_products.evaluation.resolution_decisions import (
    EXTRACTION_EVALUATION_STAGES,
    LoadedObservationTargetResolutionDecisionSet,
    ObservationTargetResolutionDecision,
    ObservationTargetResolutionDecisionSet,
    ObservationTargetResolutionDecisionSetError,
    ObservationTargetResolutionProvenance,
    load_observation_target_resolution_decision_set,
    persist_observation_target_resolution_decision_set,
)
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]

CASE_ID = "SYNTH-CASE-FULL-0002"
STAGE = "capability_extraction"
COMPANY = "SYNTH-CO-0001"
CAP_OBS = "SYNTH-CAPABILITY-OBS-0001"
PROD_OBS = "SYNTH-PRODUCT-OBS-0001"
CANON_CAP = "SYNTH.PRODUCT.ALPHA.CAPABILITY"
CANON_PROD = "SYNTH.PRODUCT.ALPHA"
RAW_REF = "prediction_source.json"
RAW_SHA = "a" * 64
PARSED_SHA = "d" * 64
TS = "2026-07-26T00:00:00+00:00"
REF = "adjudications/set-0001.json"

SET_HASH = model_contract_hash(
    ObservationTargetResolutionDecisionSet,
    "observation_target_resolution_decision_set", "0.1.0")


# --- Builders ---------------------------------------------------------------


def prov(**ov):
    d = {"resolution_method": "stable_identity_field",
         "source_field_name": "stable_capability_id", "source_field_value": CANON_CAP,
         "registry_entry_reference_id": CANON_CAP, "resolver_kind": "deterministic_rule",
         "resolver_ids": ["rule-v1"], "verification_status": "provisional",
         "verification_method": "deterministic_rule_review",
         "decision_timestamps": [TS], "change_reason": "initial adjudication"}
    d.update(ov)
    return d


def decision(obs, kind, canonical, *, parent=False):
    return {"observation_id": obs, "observation_kind": kind, "resolution_status": "resolved",
            "canonical_target_reference": canonical, "parent_referenced": parent,
            "provenance": prov(source_field_value=canonical,
                               registry_entry_reference_id=canonical)}


def payload(**ov):
    d = {
        "contract": {"contract_id": "observation_target_resolution_decision_set",
                     "contract_version": "0.1.0", "contract_hash": SET_HASH},
        "decision_set_version": "adj-v1", "case_id": CASE_ID, "stage": STAGE,
        "company_id": COMPANY, "prediction_record_id": "pred-1",
        "raw_artifact_reference": RAW_REF, "raw_artifact_sha256": RAW_SHA,
        "parsed_prediction_content_sha256": PARSED_SHA,
        "decisions": [decision(CAP_OBS, "capability", CANON_CAP),
                      decision(PROD_OBS, "product", CANON_PROD, parent=True)],
    }
    d.update(ov)
    return d


def model(**ov):
    return ObservationTargetResolutionDecisionSet.model_validate(payload(**ov))


def _root(tmp_path):
    (tmp_path / "adjudications").mkdir(parents=True, exist_ok=True)
    return tmp_path


# --- Contract identity ------------------------------------------------------


def test_contract_stamp_and_strict_frozen():
    m = model()
    assert m.contract.contract_id == "observation_target_resolution_decision_set"
    assert m.contract.contract_version == "0.1.0"
    assert m.contract.contract_hash == SET_HASH
    assert [d.observation_id for d in m.decisions] == [CAP_OBS, PROD_OBS]
    with pytest.raises(Exception):
        m.case_id = "x"  # frozen
    with pytest.raises(PydanticValidationError):
        ObservationTargetResolutionDecisionSet.model_validate({**payload(), "extra": 1})


def test_stage_vocabulary_is_the_governed_extraction_set():
    assert EXTRACTION_EVALUATION_STAGES == frozenset(sa_mod._STAGE_ENTITY_KINDS)
    ObservationTargetResolutionDecisionSet.model_validate(payload(
        stage="task_extraction",
        decisions=[decision("SYNTH-TASK-OBS-0001", "task", "SYNTH.PRODUCT.CAPABILITY.TASK")]))
    with pytest.raises(PydanticValidationError):
        ObservationTargetResolutionDecisionSet.model_validate(
            payload(stage="universe_classification"))


# --- Set invariants ---------------------------------------------------------


def test_decisions_must_not_be_empty():
    with pytest.raises(PydanticValidationError):
        ObservationTargetResolutionDecisionSet.model_validate(payload(decisions=[]))


def test_decisions_must_be_sorted_and_unique():
    with pytest.raises(PydanticValidationError) as ei:
        ObservationTargetResolutionDecisionSet.model_validate(payload(decisions=[
            decision(PROD_OBS, "product", CANON_PROD, parent=True),
            decision(CAP_OBS, "capability", CANON_CAP)]))
    assert "sorted canonically" in str(ei.value)
    with pytest.raises(PydanticValidationError) as ej:
        ObservationTargetResolutionDecisionSet.model_validate(payload(decisions=[
            decision(CAP_OBS, "capability", CANON_CAP),
            decision(CAP_OBS, "capability", CANON_CAP)]))
    assert "duplicate observation_id" in str(ej.value)


@pytest.mark.parametrize("field", [
    "decision_set_version", "case_id", "stage", "company_id", "prediction_record_id"])
def test_blank_identity_fields_rejected(field):
    with pytest.raises(PydanticValidationError):
        ObservationTargetResolutionDecisionSet.model_validate(payload(**{field: "  "}))


def test_raw_artifact_reference_must_be_a_safe_relative_reference():
    for bad in ("../escape.json", "/abs.json", "", "a/../b.json"):
        with pytest.raises(PydanticValidationError):
            ObservationTargetResolutionDecisionSet.model_validate(
                payload(raw_artifact_reference=bad))


@pytest.mark.parametrize("field", ["raw_artifact_sha256", "parsed_prediction_content_sha256"])
def test_hash_pins_must_be_lowercase_64_hex(field):
    for bad in ("A" * 64, "a" * 63, "z" * 64):
        with pytest.raises(PydanticValidationError):
            ObservationTargetResolutionDecisionSet.model_validate(payload(**{field: bad}))


def test_unresolved_decision_keeps_its_required_null(tmp_path):
    root = _root(tmp_path)
    unresolved = {
        "observation_id": CAP_OBS, "observation_kind": "capability",
        "resolution_status": "unresolved", "canonical_target_reference": None,
        "parent_referenced": False,
        "provenance": {k: v for k, v in prov(
            resolution_method="declared_unresolved",
            unresolved_reason_code="no_registry_candidate").items()
            if k not in ("source_field_name", "source_field_value",
                         "registry_entry_reference_id")},
    }
    loaded = persist_observation_target_resolution_decision_set(
        model(decisions=[unresolved]), source_root=root, reference=REF)
    raw = json.loads((root / REF).read_text())
    entry = raw["decisions"][0]
    assert "canonical_target_reference" in entry
    assert entry["canonical_target_reference"] is None
    again = load_observation_target_resolution_decision_set(REF, source_root=root)
    assert again.model.decisions[0].canonical_target_reference is None
    assert again.sha256 == loaded.sha256


# --- Persistence ------------------------------------------------------------


def test_persist_is_write_once_canonical_and_read_back_verified(tmp_path):
    root = _root(tmp_path)
    loaded = persist_observation_target_resolution_decision_set(
        model(), source_root=root, reference=REF)
    assert isinstance(loaded, LoadedObservationTargetResolutionDecisionSet)
    assert loaded.artifact_reference == REF and loaded.version == "0.1.0"
    data = (root / REF).read_bytes()
    assert data.endswith(b"\n") and loaded.sha256 == sha256_bytes(data)
    with pytest.raises(ObservationTargetResolutionDecisionSetError) as ei:
        persist_observation_target_resolution_decision_set(
            model(), source_root=root, reference=REF)
    assert ei.value.reason_code == "artifact_exists"


def test_persist_requires_an_existing_parent_directory(tmp_path):
    with pytest.raises(ObservationTargetResolutionDecisionSetError) as ei:
        persist_observation_target_resolution_decision_set(
            model(), source_root=tmp_path, reference="missing/dir/set.json")
    assert ei.value.reason_code == "parent_directory_missing"


def test_persist_rejects_a_validator_bypassing_instance(tmp_path):
    root = _root(tmp_path)
    # ``model_copy(update=...)`` skips validators, so the object satisfies
    # ``isinstance`` while carrying content that never passed the invariants.
    bad = model().model_copy(update={"case_id": ""})
    with pytest.raises(ObservationTargetResolutionDecisionSetError) as ei:
        persist_observation_target_resolution_decision_set(
            bad, source_root=root, reference=REF)
    assert ei.value.reason_code == "model_validation"


def test_persist_rejects_a_wrong_type(tmp_path):
    with pytest.raises(TypeError):
        persist_observation_target_resolution_decision_set(
            object(), source_root=_root(tmp_path), reference=REF)


@pytest.mark.parametrize("reference,code", [
    ("../escape.json", "unsafe_reference"),
    ("/abs.json", "unsafe_reference"),
    ("", "unsafe_reference"),
])
def test_persist_reference_protections(tmp_path, reference, code):
    with pytest.raises(ObservationTargetResolutionDecisionSetError) as ei:
        persist_observation_target_resolution_decision_set(
            model(), source_root=_root(tmp_path), reference=reference)
    assert ei.value.reason_code == code


# --- Loader -----------------------------------------------------------------


def test_load_round_trip_and_expected_hash(tmp_path):
    root = _root(tmp_path)
    loaded = persist_observation_target_resolution_decision_set(
        model(), source_root=root, reference=REF)
    again = load_observation_target_resolution_decision_set(
        REF, source_root=root, expected_sha256=loaded.sha256)
    assert again.model == loaded.model and again.sha256 == loaded.sha256
    with pytest.raises(ObservationTargetResolutionDecisionSetError) as ei:
        load_observation_target_resolution_decision_set(
            REF, source_root=root, expected_sha256="0" * 64)
    assert ei.value.reason_code == "expected_hash_mismatch"


@pytest.mark.parametrize("reference,code", [
    ("../escape.json", "unsafe_reference"),
    ("adjudications/nope.json", "artifact_missing"),
    ("adjudications", "artifact_not_a_file"),
])
def test_loader_reference_protections(tmp_path, reference, code):
    with pytest.raises(ObservationTargetResolutionDecisionSetError) as ei:
        load_observation_target_resolution_decision_set(reference, source_root=_root(tmp_path))
    assert ei.value.reason_code == code


def test_loader_rejects_symlink(tmp_path):
    root = _root(tmp_path)
    loaded = persist_observation_target_resolution_decision_set(
        model(), source_root=root, reference=REF)
    dest = root / REF
    external = root / "external.json"
    external.write_bytes(dest.read_bytes())
    dest.unlink()
    dest.symlink_to(external)
    with pytest.raises(ObservationTargetResolutionDecisionSetError) as ei:
        load_observation_target_resolution_decision_set(
            loaded.artifact_reference, source_root=root)
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
    root = _root(tmp_path)
    (root / REF).write_bytes(body)
    with pytest.raises(ObservationTargetResolutionDecisionSetError) as ei:
        load_observation_target_resolution_decision_set(REF, source_root=root)
    assert ei.value.reason_code == code


def test_loader_rejects_a_hand_written_contract_invalid_document(tmp_path):
    root = _root(tmp_path)
    bad = payload(stage="universe_classification")
    (root / REF).write_bytes((json.dumps(bad) + "\n").encode())
    with pytest.raises(ObservationTargetResolutionDecisionSetError) as ei:
        load_observation_target_resolution_decision_set(REF, source_root=root)
    assert ei.value.reason_code == "model_validation"


@pytest.mark.parametrize("source_root,code", [
    ("", "invalid_source_root"),
    (b"bytes", "invalid_source_root"),
])
def test_source_root_protections(source_root, code):
    with pytest.raises(ObservationTargetResolutionDecisionSetError) as ei:
        load_observation_target_resolution_decision_set(REF, source_root=source_root)
    assert ei.value.reason_code == code


def test_missing_source_root_is_rejected(tmp_path):
    with pytest.raises(ObservationTargetResolutionDecisionSetError) as ei:
        load_observation_target_resolution_decision_set(
            REF, source_root=tmp_path / "absent")
    assert ei.value.reason_code == "invalid_source_root"


# --- Sanitization + public surface -----------------------------------------


def test_errors_leak_no_content_or_absolute_path(tmp_path):
    root = _root(tmp_path)
    bad = payload(case_id="SECRET-CASE", stage="universe_classification")
    (root / REF).write_bytes((json.dumps(bad) + "\n").encode())
    with pytest.raises(ObservationTargetResolutionDecisionSetError) as ei:
        load_observation_target_resolution_decision_set(REF, source_root=root)
    text = str(ei.value)
    assert "SECRET-CASE" not in text and str(tmp_path) not in text


def test_public_surface_exported():
    for name in rd_mod.__all__:
        assert name in evaluation_pkg.__all__
        assert getattr(evaluation_pkg, name) is getattr(rd_mod, name)
    for private in ("_revalidate_set", "_PROVENANCE_OMIT_OR_NON_NULL", "_DuplicateKeyControl",
                    "_resolve_contained"):
        assert private not in evaluation_pkg.__all__


def test_moved_models_have_one_identity_across_paths():
    for name in ("EXTRACTION_EVALUATION_STAGES", "ObservationTargetResolutionDecision",
                 "ObservationTargetResolutionProvenance"):
        canonical = getattr(rd_mod, name)
        assert getattr(otb_mod, name) is canonical
        assert getattr(evaluation_pkg, name) is canonical


def test_this_module_owns_the_moved_models():
    assert ObservationTargetResolutionDecision.__module__.endswith("resolution_decisions")
    assert ObservationTargetResolutionProvenance.__module__.endswith("resolution_decisions")


def test_import_performs_no_io_or_hash():
    code = "\n".join([
        "import sys, os, hashlib, importlib",
        "sys.path.insert(0, 'src')",
        "from jsonschema import Draft202012Validator, FormatChecker",
        "import pydantic",
        "import dynamic_ai_products, dynamic_ai_products.universe.io_utils",
        "import dynamic_ai_products.evaluation",
        "sys.modules.pop('dynamic_ai_products.evaluation.resolution_decisions', None)",
        "from pathlib import Path",
        "reads=[]; sha=[]",
        "orb, ort, osha = Path.read_bytes, Path.read_text, hashlib.sha256",
        "Path.read_bytes=lambda self,*a,**k:(reads.append(str(self)),orb(self,*a,**k))[1]",
        "Path.read_text=lambda self,*a,**k:(reads.append(str(self)),ort(self,*a,**k))[1]",
        "hashlib.sha256=lambda *a,**k:(sha.append(1),osha(*a,**k))[1]",
        "importlib.import_module('dynamic_ai_products.evaluation.resolution_decisions')",
        "Path.read_bytes, Path.read_text, hashlib.sha256 = orb, ort, osha",
        "bad=[p for p in reads if p.endswith('.json')]",
        "assert not bad, bad",
        "assert not sha, len(sha)",
        "print('OK')",
    ])
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr


def test_module_never_reads_a_clock():
    src = (ROOT / "src" / "dynamic_ai_products" / "evaluation"
           / "resolution_decisions.py").read_text()
    for forbidden in ("datetime.now", "time.time", "utcnow", "monotonic"):
        assert forbidden not in src


# --- Internal consumer boundary (module-private, no package export) ---------


def test_revalidate_loaded_set_returns_a_revalidated_model(tmp_path):
    root = _root(tmp_path)
    loaded = persist_observation_target_resolution_decision_set(
        model(), source_root=root, reference=REF)
    validated = rd_mod._revalidate_loaded_set(loaded)
    assert validated == loaded.model
    assert validated is not loaded.model  # a fresh, revalidated instance


@pytest.mark.parametrize("update", [
    {"decision_set_version": ""},
    {"stage": "universe_screen"},
    {"prediction_record_id": "  "},
])
def test_revalidate_loaded_set_rejects_a_bypassed_inner_model(tmp_path, update):
    root = _root(tmp_path)
    loaded = persist_observation_target_resolution_decision_set(
        model(), source_root=root, reference=REF)
    forged = loaded.model_copy(update={"model": loaded.model.model_copy(update=update)})
    with pytest.raises(ObservationTargetResolutionDecisionSetError) as ei:
        rd_mod._revalidate_loaded_set(forged)
    assert ei.value.reason_code == "model_validation"


def test_revalidate_loaded_set_rejects_a_version_mismatch(tmp_path):
    root = _root(tmp_path)
    loaded = persist_observation_target_resolution_decision_set(
        model(), source_root=root, reference=REF)
    with pytest.raises(ObservationTargetResolutionDecisionSetError) as ei:
        rd_mod._revalidate_loaded_set(loaded.model_copy(update={"version": "0.9.9"}))
    assert ei.value.reason_code == "model_validation"


@pytest.mark.parametrize("bad", [object(), None, {"decisions": []}])
def test_revalidate_loaded_set_rejects_a_wrong_inner_model(bad):
    forged = LoadedObservationTargetResolutionDecisionSet.model_construct(
        model=bad, version="0.1.0", sha256="d" * 64, artifact_reference=REF)
    with pytest.raises(ObservationTargetResolutionDecisionSetError) as ei:
        rd_mod._revalidate_loaded_set(forged)
    assert ei.value.reason_code == "model_validation"


def test_consumer_boundary_is_not_exported():
    assert "_revalidate_loaded_set" not in rd_mod.__all__
    assert "_revalidate_loaded_set" not in evaluation_pkg.__all__
    assert not hasattr(evaluation_pkg, "_revalidate_loaded_set")
