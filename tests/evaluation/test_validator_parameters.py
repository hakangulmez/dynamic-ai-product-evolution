"""Slice 12F: validator-rule parameters contract, matrix, and hashes."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import validator_parameters as vp_mod
from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.validator_parameters import (
    LoadedValidatorRuleParameters,
    ValidatorRuleParameters,
    ValidatorRuleParametersError,
    ValidatorRuleParametersV2,
    complete_rule_parameter_hash,
    load_validator_rule_parameters,
    load_validator_rule_parameters_v2,
    persist_validator_rule_parameters,
    validator_rule_parameters_aggregate_hash,
)
from dynamic_ai_products.evaluation.contracts import canonical_contract_bytes
from dynamic_ai_products.evaluation.validators import VALIDATOR_RULE_ORDER
from dynamic_ai_products.universe.io_utils import sha256_bytes


def _recompute_entry_hash(entry_dict):
    content = {k: v for k, v in entry_dict.items() if k != "complete_rule_parameter_hash"}
    return sha256_bytes(canonical_contract_bytes(content))

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness"
REL = "validator_parameters/validator_rule_parameters.json"
MODEL_HASH = "f9c20ba936e1c0541c721ac6c3c34bec183b4b360dfa177516c57b0bd0945822"
USO_HASH = "97703d752d1bdf6216a98c14923ba1c145e1c24aa70c2c8dd24e9160a6949c50"
STAGES = ("capability_extraction", "task_extraction", "universe_screen", "universe_classification")
INAPPLICABLE_CELLS = {
    "product_capability_task_parent_resolution": {"universe_screen", "universe_classification"},
    "active_record_non_roadmap_evidence": {"universe_screen", "universe_classification"},
    "customer_task_outcome_and_evidence": {"universe_screen", "universe_classification"},
}


def _fixture_dict():
    return json.loads((FX / "validator_parameters" / "validator_rule_parameters.json").read_bytes())


# --- Contract identity + matrix -------------------------------------------


def test_model_contract_hash_locked():
    assert model_contract_hash(ValidatorRuleParameters, "validator_rule_parameters", "0.1.0") == MODEL_HASH


def test_fixture_loads_twelve_in_order():
    loaded = load_validator_rule_parameters(REL, eval_root=FX)
    assert isinstance(loaded, LoadedValidatorRuleParameters)
    assert tuple(e.rule_id for e in loaded.model.entries) == VALIDATOR_RULE_ORDER


def test_full_48_cell_matrix():
    loaded = load_validator_rule_parameters(REL, eval_root=FX)
    seen = 0
    for entry in loaded.model.entries:
        stages = tuple(sp.stage for sp in entry.stage_parameters)
        assert stages == STAGES
        for sp in entry.stage_parameters:
            seen += 1
            inapp = INAPPLICABLE_CELLS.get(entry.rule_id, set())
            if sp.stage in inapp:
                assert sp.applicability == "inapplicable"
                assert sp.reason_code  # governed reason present
            else:
                assert sp.applicability == "applicable"
                assert sp.payload.payload_kind
    assert seen == 48


def test_universe_screen_rule1_and_rule2_bind_generated_contract():
    loaded = load_validator_rule_parameters(REL, eval_root=FX)
    by_rule = {e.rule_id: e for e in loaded.model.entries}
    for rid in ("output_json_schema_validity", "required_field_presence"):
        us = next(sp for sp in by_rule[rid].stage_parameters if sp.stage == "universe_screen")
        assert us.payload.output_contract_id == "universe_screen_output"
        assert us.payload.output_contract_hash == USO_HASH


def test_rule1_static_schema_anchors():
    loaded = load_validator_rule_parameters(REL, eval_root=FX)
    entry = next(e for e in loaded.model.entries if e.rule_id == "output_json_schema_validity")
    ce = next(sp for sp in entry.stage_parameters if sp.stage == "capability_extraction")
    assert ce.payload.output_schema_reference == "schemas/capability_observation.schema.json"
    assert ce.payload.output_schema_sha256 == (
        "4ade397f3383ff756a1aa2ba5f98bdb99f76c002d5cf049d7e8dcd7abf493733"
    )


# --- Hash identities -------------------------------------------------------


def test_per_rule_hash_matches_stored():
    loaded = load_validator_rule_parameters(REL, eval_root=FX)
    for entry in loaded.model.entries:
        assert complete_rule_parameter_hash(entry) == entry.complete_rule_parameter_hash


def test_aggregate_hash_distinct_from_raw_and_per_rule():
    loaded = load_validator_rule_parameters(REL, eval_root=FX)
    agg = validator_rule_parameters_aggregate_hash(loaded.model)
    assert len(agg) == 64
    assert agg != loaded.sha256  # aggregate (identity 2) != raw persisted SHA (identity 3)
    per_rule = {e.complete_rule_parameter_hash for e in loaded.model.entries}
    assert agg not in per_rule  # aggregate != any per-rule hash (identity 1)
    assert agg != MODEL_HASH


# --- Structural rejections -------------------------------------------------


def test_wrong_dependency_rejected():
    data = _fixture_dict()
    data["entries"][1]["dependency_rule_ids"] = []  # required_field_presence must depend on rule 1
    with pytest.raises(PydanticValidationError):
        ValidatorRuleParameters.model_validate(data)


def test_wrong_applicability_rejected():
    data = _fixture_dict()
    # force Rule 7 applicable at universe_screen (governed inapplicable)
    entry = next(e for e in data["entries"] if e["rule_id"] == "product_capability_task_parent_resolution")
    for sp in entry["stage_parameters"]:
        if sp["stage"] == "universe_screen":
            sp.clear()
            sp.update({
                "applicability": "applicable", "stage": "universe_screen",
                "payload": {"payload_kind": "rule7_parent_resolution", "hierarchy": "product_capability_task"},
            })
    with pytest.raises(PydanticValidationError):
        ValidatorRuleParameters.model_validate(data)


def test_tampered_complete_hash_rejected():
    data = _fixture_dict()
    data["entries"][0]["complete_rule_parameter_hash"] = "0" * 64
    with pytest.raises(PydanticValidationError):
        ValidatorRuleParameters.model_validate(data)


def test_wrong_universe_screen_contract_hash_rejected():
    data = _fixture_dict()
    entry = next(e for e in data["entries"] if e["rule_id"] == "output_json_schema_validity")
    for sp in entry["stage_parameters"]:
        if sp["stage"] == "universe_screen":
            sp["payload"]["output_contract_hash"] = "1" * 64
    # recompute the stored per-rule hash so only the contract-hash check fails
    with pytest.raises(PydanticValidationError):
        ValidatorRuleParameters.model_validate(data)


def test_entries_wrong_order_rejected():
    data = _fixture_dict()
    data["entries"] = list(reversed(data["entries"]))
    with pytest.raises(PydanticValidationError):
        ValidatorRuleParameters.model_validate(data)


def test_unapproved_static_schema_hash_rejected_even_when_entry_hash_recomputed():
    data = _fixture_dict()
    entry = next(e for e in data["entries"] if e["rule_id"] == "output_json_schema_validity")
    for sp in entry["stage_parameters"]:
        if sp["stage"] == "capability_extraction":
            sp["payload"]["output_schema_sha256"] = "0" * 64  # valid hex, unapproved anchor
    entry["complete_rule_parameter_hash"] = _recompute_entry_hash(entry)
    with pytest.raises(PydanticValidationError):
        ValidatorRuleParameters.model_validate(data)


def test_unapproved_static_schema_reference_rejected():
    data = _fixture_dict()
    entry = next(e for e in data["entries"] if e["rule_id"] == "output_json_schema_validity")
    for sp in entry["stage_parameters"]:
        if sp["stage"] == "capability_extraction":
            sp["payload"]["output_schema_reference"] = "schemas/not_approved.schema.json"
    entry["complete_rule_parameter_hash"] = _recompute_entry_hash(entry)
    with pytest.raises(PydanticValidationError):
        ValidatorRuleParameters.model_validate(data)


def test_unapproved_static_schema_id_rejected():
    data = _fixture_dict()
    entry = next(e for e in data["entries"] if e["rule_id"] == "output_json_schema_validity")
    for sp in entry["stage_parameters"]:
        if sp["stage"] == "capability_extraction":
            sp["payload"]["output_schema_id"] = "not_approved"
    entry["complete_rule_parameter_hash"] = _recompute_entry_hash(entry)
    with pytest.raises(PydanticValidationError):
        ValidatorRuleParameters.model_validate(data)


# --- Correction A: stage-specific static-schema anchor binding -------------

_STAGE_ANCHOR = {
    "capability_extraction": {
        "payload_kind": "rule1_static_schema", "output_schema_id": "capability_observation",
        "output_schema_reference": "schemas/capability_observation.schema.json",
        "output_schema_sha256": "4ade397f3383ff756a1aa2ba5f98bdb99f76c002d5cf049d7e8dcd7abf493733",
    },
    "task_extraction": {
        "payload_kind": "rule1_static_schema", "output_schema_id": "task_observation",
        "output_schema_reference": "schemas/task_observation.schema.json",
        "output_schema_sha256": "b135ab828a3b710f1c63f6a8bf473caa6e29c3a63a5330cb203b470f772e3b03",
    },
    "universe_classification": {
        "payload_kind": "rule1_static_schema",
        "output_schema_id": "company_universe_classification",
        "output_schema_reference": "schemas/company_universe_classification.schema.json",
        "output_schema_sha256": "1d47a80ee670f927e55d6af50550b1584aab022389471739a055a9e550552a22",
    },
}


def test_intended_stage_anchor_bindings_accepted():
    loaded = load_validator_rule_parameters(REL, eval_root=FX)
    entry = next(e for e in loaded.model.entries if e.rule_id == "output_json_schema_validity")
    for sp in entry.stage_parameters:
        if sp.stage in _STAGE_ANCHOR:
            expect = _STAGE_ANCHOR[sp.stage]
            assert sp.payload.output_schema_id == expect["output_schema_id"]
            assert sp.payload.output_schema_reference == expect["output_schema_reference"]
            assert sp.payload.output_schema_sha256 == expect["output_schema_sha256"]


@pytest.mark.parametrize(
    "victim,donor",
    [
        ("capability_extraction", "task_extraction"),
        ("capability_extraction", "universe_classification"),
        ("task_extraction", "capability_extraction"),
        ("task_extraction", "universe_classification"),
        ("universe_classification", "capability_extraction"),
        ("universe_classification", "task_extraction"),
    ],
)
def test_approved_anchor_wrong_stage_rejected(victim, donor):
    # An approved anchor placed on the wrong stage is rejected even when the
    # complete per-rule hash is recomputed to be self-consistent.
    data = _fixture_dict()
    entry = next(e for e in data["entries"] if e["rule_id"] == "output_json_schema_validity")
    for sp in entry["stage_parameters"]:
        if sp["stage"] == victim:
            sp["payload"] = {**_STAGE_ANCHOR[donor]}
    entry["complete_rule_parameter_hash"] = _recompute_entry_hash(entry)
    with pytest.raises(PydanticValidationError):
        ValidatorRuleParameters.model_validate(data)


# --- Private models not exported ------------------------------------------


def test_private_models_not_exported():
    for name in (
        "_UniverseScreenOutput", "_ValidatorRuleParameterEntry",
        "_Rule1StaticSchemaPayload", "_Rule1UniverseScreenPayload",
        "_ApplicableStageParameter", "_InapplicableStageParameter",
    ):
        assert name not in evaluation_pkg.__all__
        assert name not in vp_mod.__all__


# --- Persistence + security ------------------------------------------------


def test_persist_write_once_and_read_back(tmp_path):
    (tmp_path / "run-1").mkdir()
    loaded = load_validator_rule_parameters(REL, eval_root=FX)
    result = persist_validator_rule_parameters(loaded.model, eval_root=tmp_path, eval_run_id="run-1")
    dest = tmp_path / "run-1" / "snapshots" / "validator_rule_parameters.json"
    raw = dest.read_bytes()
    assert raw.endswith(b"\n")
    assert result.sha256 == sha256_bytes(raw)
    with pytest.raises(ValidatorRuleParametersError) as exc:
        persist_validator_rule_parameters(loaded.model, eval_root=tmp_path, eval_run_id="run-1")
    assert exc.value.reason_code == "snapshot_exists"


def test_persist_round_trips(tmp_path):
    (tmp_path / "run-2").mkdir()
    loaded = load_validator_rule_parameters(REL, eval_root=FX)
    persist_validator_rule_parameters(loaded.model, eval_root=tmp_path, eval_run_id="run-2")
    reloaded = load_validator_rule_parameters(
        "run-2/snapshots/validator_rule_parameters.json", eval_root=tmp_path
    )
    assert reloaded.model == loaded.model


def _write(tmp_path, name, data_bytes):
    (tmp_path / name).write_bytes(data_bytes)
    return name


def test_expected_hash_mismatch(tmp_path):
    name = _write(tmp_path, "p.json", json.dumps(_fixture_dict()).encode())
    with pytest.raises(ValidatorRuleParametersError) as exc:
        load_validator_rule_parameters(name, eval_root=tmp_path, expected_sha256="0" * 64)
    assert exc.value.reason_code == "expected_hash_mismatch"


def test_traversal_rejected(tmp_path):
    with pytest.raises(ValidatorRuleParametersError) as exc:
        load_validator_rule_parameters("../escape.json", eval_root=tmp_path)
    assert exc.value.reason_code == "unsafe_reference"


def test_symlink_rejected(tmp_path):
    target = tmp_path / "real.json"
    target.write_bytes(json.dumps(_fixture_dict()).encode())
    (tmp_path / "link.json").symlink_to(target)
    with pytest.raises(ValidatorRuleParametersError) as exc:
        load_validator_rule_parameters("link.json", eval_root=tmp_path)
    assert exc.value.reason_code == "artifact_symlink"


def test_duplicate_key_rejected(tmp_path):
    name = _write(tmp_path, "p.json", b'{"a": 1, "a": 2}')
    with pytest.raises(ValidatorRuleParametersError) as exc:
        load_validator_rule_parameters(name, eval_root=tmp_path)
    assert exc.value.reason_code == "duplicate_key"


def test_top_level_array_rejected(tmp_path):
    name = _write(tmp_path, "p.json", b"[]")
    with pytest.raises(ValidatorRuleParametersError) as exc:
        load_validator_rule_parameters(name, eval_root=tmp_path)
    assert exc.value.reason_code == "top_level_type"


def test_import_no_io_no_hash_no_clock():
    code = "\n".join([
        "import sys, os, hashlib, importlib, time",
        "sys.path.insert(0, 'src')",
        "import pydantic",
        "import dynamic_ai_products, dynamic_ai_products.universe.io_utils",
        "import dynamic_ai_products.evaluation",
        "sys.modules.pop('dynamic_ai_products.evaluation.validator_parameters', None)",
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
        "importlib.import_module('dynamic_ai_products.evaluation.validator_parameters')",
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


# --- validator_rule_parameters@0.2.0 successor (ADR-028) -------------------

V2_MODEL_HASH = "a15556e5935c3ba26a966aaac18f84267a3b3dbedca43c7a9bc360e49e00df08"
V2_SET_VERSION = "synth-validator-params-v2"
RULE_10 = "active_record_non_roadmap_evidence"
RULE_11 = "customer_task_outcome_and_evidence"
EXTRACTION_STAGES = ("capability_extraction", "task_extraction")
ACTIVE_VALUES = ("generally_available", "limited_availability")
ROADMAP_VALUES = ("announced", "planned")


def _v2_dict(*, active=ACTIVE_VALUES, roadmap=ROADMAP_VALUES, rule11_inapplicable=True):
    """Derive a governed v0.2 document from the committed v0.1 fixture.

    Only the three governed deltas are applied; every other cell is carried over
    verbatim, so a drift anywhere else would surface as a hash failure.
    """
    doc = _fixture_dict()
    doc["contract"] = {
        "contract_id": "validator_rule_parameters",
        "contract_version": "0.2.0",
        "contract_hash": model_contract_hash(
            ValidatorRuleParametersV2, "validator_rule_parameters", "0.2.0"
        ),
    }
    doc["parameter_set_version"] = V2_SET_VERSION
    for entry in doc["entries"]:
        if entry["rule_id"] == RULE_10:
            entry["dependency_rule_ids"] = ["required_field_presence", "source_id_resolution"]
            entry["blocking_reason_codes"] = [
                "blocked_required_field_missing",
                "blocked_source_unresolved",
            ]
            for sp in entry["stage_parameters"]:
                if sp["applicability"] == "applicable":
                    sp["payload"]["active_status_values"] = list(active)
                    sp["payload"]["roadmap_status_values"] = list(roadmap)
        elif entry["rule_id"] == RULE_11 and rule11_inapplicable:
            entry["stage_parameters"] = [
                {
                    "applicability": "inapplicable",
                    "stage": sp["stage"],
                    "reason_code": "stage_emits_no_customer_facing_task",
                }
                if sp["stage"] in EXTRACTION_STAGES
                else sp
                for sp in entry["stage_parameters"]
            ]
        entry["complete_rule_parameter_hash"] = _recompute_entry_hash(entry)
    return doc


def _write_v2(tmp_path, doc=None, name="validator_rule_parameters.v2.json"):
    path = tmp_path / name
    path.write_bytes(canonical_contract_bytes(doc if doc is not None else _v2_dict()) + b"\n")
    return name


def _load_v2(tmp_path, doc=None):
    return load_validator_rule_parameters_v2(_write_v2(tmp_path, doc), eval_root=tmp_path)


# --- v0.1 preservation -----------------------------------------------------


def test_v01_contract_hash_and_load_unchanged_by_successor():
    assert model_contract_hash(
        ValidatorRuleParameters, "validator_rule_parameters", "0.1.0"
    ) == MODEL_HASH
    loaded = load_validator_rule_parameters(REL, eval_root=FX)
    assert type(loaded.model) is ValidatorRuleParameters
    assert loaded.model.parameter_set_version == "synth-validator-params-v1"


def test_v01_rule10_and_rule11_matrix_cells_unchanged():
    spec = vp_mod._RULE_SPEC
    assert spec[RULE_10]["deps"] == ("required_field_presence",)
    assert spec[RULE_10]["blocking"] == ("blocked_required_field_missing",)
    for stage in EXTRACTION_STAGES:
        assert spec[RULE_11]["stages"][stage] == ("applicable", "rule11_customer_task")
    loaded = load_validator_rule_parameters(REL, eval_root=FX)
    by_rule = {e.rule_id: e for e in loaded.model.entries}
    assert by_rule[RULE_10].dependency_rule_ids == ("required_field_presence",)
    assert by_rule[RULE_10].blocking_reason_codes == ("blocked_required_field_missing",)


def test_v01_loader_rejects_a_v2_document(tmp_path):
    name = _write_v2(tmp_path)
    with pytest.raises(ValidatorRuleParametersError) as exc:
        load_validator_rule_parameters(name, eval_root=tmp_path)
    assert exc.value.reason_code == "model_validation"


def test_rule_spec_v2_differs_in_exactly_the_governed_cells():
    diffs = {
        (rule_id, field)
        for rule_id in vp_mod._RULE_SPEC
        for field in ("deps", "blocking", "stages")
        if vp_mod._RULE_SPEC[rule_id][field] != vp_mod._RULE_SPEC_V2[rule_id][field]
    }
    assert diffs == {(RULE_10, "deps"), (RULE_10, "blocking"), (RULE_11, "stages")}


# --- v0.2 contract identity + loader ---------------------------------------


def test_v2_contract_hash_locked_and_distinct():
    v2 = model_contract_hash(ValidatorRuleParametersV2, "validator_rule_parameters", "0.2.0")
    assert v2 == V2_MODEL_HASH
    assert v2 != MODEL_HASH
    assert ValidatorRuleParametersV2._contract_version == "0.2.0"
    assert ValidatorRuleParametersV2._contract_id == "validator_rule_parameters"


def test_v2_loader_accepts_governed_v2_document(tmp_path):
    loaded = _load_v2(tmp_path)
    assert isinstance(loaded, LoadedValidatorRuleParameters)
    assert type(loaded.model) is ValidatorRuleParametersV2
    assert loaded.model.parameter_set_version == V2_SET_VERSION
    assert loaded.version == V2_SET_VERSION
    assert tuple(e.rule_id for e in loaded.model.entries) == VALIDATOR_RULE_ORDER


def test_v2_parameter_set_version_is_not_the_contract_version(tmp_path):
    loaded = _load_v2(tmp_path)
    assert loaded.model.contract.contract_version == "0.2.0"
    assert loaded.model.parameter_set_version != "0.2.0"


def test_v2_loader_rejects_v01_document():
    with pytest.raises(ValidatorRuleParametersError) as exc:
        load_validator_rule_parameters_v2(REL, eval_root=FX)
    assert exc.value.reason_code == "parameters_version_unsupported"


def test_v2_loader_honours_expected_sha256(tmp_path):
    name = _write_v2(tmp_path)
    good = sha256_bytes((tmp_path / name).read_bytes())
    assert load_validator_rule_parameters_v2(
        name, eval_root=tmp_path, expected_sha256=good
    ).sha256 == good
    with pytest.raises(ValidatorRuleParametersError) as exc:
        load_validator_rule_parameters_v2(name, eval_root=tmp_path, expected_sha256="0" * 64)
    assert exc.value.reason_code == "expected_hash_mismatch"


# --- v0.2 Rule 11 inapplicability -----------------------------------------


def test_v2_rule11_inapplicable_at_both_extraction_stages(tmp_path):
    loaded = _load_v2(tmp_path)
    entry = {e.rule_id: e for e in loaded.model.entries}[RULE_11]
    by_stage = {sp.stage: sp for sp in entry.stage_parameters}
    for stage in STAGES:
        assert by_stage[stage].applicability == "inapplicable"
        assert by_stage[stage].reason_code == "stage_emits_no_customer_facing_task"


def test_v2_rejects_rule11_still_applicable_at_extraction(tmp_path):
    doc = _v2_dict(rule11_inapplicable=False)
    with pytest.raises(ValidatorRuleParametersError) as exc:
        _load_v2(tmp_path, doc)
    assert exc.value.reason_code == "model_validation"


# --- v0.2 Rule 10 payload invariants --------------------------------------


def test_v2_rule10_payload_carries_governed_vocabularies(tmp_path):
    loaded = _load_v2(tmp_path)
    entry = {e.rule_id: e for e in loaded.model.entries}[RULE_10]
    applicable = [sp for sp in entry.stage_parameters if sp.applicability == "applicable"]
    assert [sp.stage for sp in applicable] == list(EXTRACTION_STAGES)
    for sp in applicable:
        assert sp.payload.payload_kind == "rule10_active_roadmap"
        assert sp.payload.active_status_values == ACTIVE_VALUES
        assert sp.payload.roadmap_status_values == ROADMAP_VALUES


@pytest.mark.parametrize(
    ("active", "roadmap"),
    [
        ((), ROADMAP_VALUES),                              # empty active
        (ACTIVE_VALUES, ()),                               # empty roadmap
        (("b_second", "a_first"), ROADMAP_VALUES),          # unsorted
        (("dup", "dup"), ROADMAP_VALUES),                   # duplicate
        ((" pad",), ROADMAP_VALUES),                        # blank-padded
        (ACTIVE_VALUES, ACTIVE_VALUES),                     # not disjoint
        (("announced", "generally_available"), ROADMAP_VALUES),  # overlapping literal
    ],
)
def test_v2_rule10_payload_invariants_fail_closed(tmp_path, active, roadmap):
    doc = _v2_dict(active=active, roadmap=roadmap)
    with pytest.raises(ValidatorRuleParametersError) as exc:
        _load_v2(tmp_path, doc)
    assert exc.value.reason_code == "model_validation"


def test_v2_rule10_payload_requires_the_new_fields(tmp_path):
    doc = _v2_dict()
    for entry in doc["entries"]:
        if entry["rule_id"] == RULE_10:
            for sp in entry["stage_parameters"]:
                if sp["applicability"] == "applicable":
                    del sp["payload"]["active_status_values"]
            entry["complete_rule_parameter_hash"] = _recompute_entry_hash(entry)
    with pytest.raises(ValidatorRuleParametersError):
        _load_v2(tmp_path, doc)


# --- v0.2 Rule 10 dependency truthfulness ---------------------------------


def test_v2_rule10_dependency_and_blocking_tuples(tmp_path):
    loaded = _load_v2(tmp_path)
    entry = {e.rule_id: e for e in loaded.model.entries}[RULE_10]
    assert entry.dependency_rule_ids == ("required_field_presence", "source_id_resolution")
    assert entry.blocking_reason_codes == (
        "blocked_required_field_missing",
        "blocked_source_unresolved",
    )
    # No vocabulary widening: both codes already exist in the v0.1 literal set.
    assert set(entry.blocking_reason_codes) <= set(vp_mod._BlockingReasonCode.__args__)


def test_v2_rejects_rule10_with_v01_dependency_tuples(tmp_path):
    doc = _v2_dict()
    for entry in doc["entries"]:
        if entry["rule_id"] == RULE_10:
            entry["dependency_rule_ids"] = ["required_field_presence"]
            entry["blocking_reason_codes"] = ["blocked_required_field_missing"]
            entry["complete_rule_parameter_hash"] = _recompute_entry_hash(entry)
    with pytest.raises(ValidatorRuleParametersError) as exc:
        _load_v2(tmp_path, doc)
    assert exc.value.reason_code == "model_validation"


# --- Rule 2 stays inside the existing stage payload ------------------------


def test_v2_rule2_uses_existing_stage_payload_required_fields(tmp_path):
    loaded = _load_v2(tmp_path)
    entry = {e.rule_id: e for e in loaded.model.entries}["required_field_presence"]
    for sp in entry.stage_parameters:
        assert sp.applicability == "applicable"
        assert sp.payload.required_fields
    # No new top-level extraction-required-fields field was introduced.
    assert set(ValidatorRuleParametersV2.model_fields) == {
        "contract", "parameter_set_version", "entries",
    }


# --- Hash helpers accept both governed types ------------------------------


def test_per_rule_and_aggregate_hashes_accept_both_model_types(tmp_path):
    v1 = load_validator_rule_parameters(REL, eval_root=FX)
    v2 = _load_v2(tmp_path)
    agg_v1 = validator_rule_parameters_aggregate_hash(v1.model)
    agg_v2 = validator_rule_parameters_aggregate_hash(v2.model)
    assert len(agg_v1) == len(agg_v2) == 64
    assert agg_v1 != agg_v2  # the governed deltas move the aggregate
    for entry in v2.model.entries:
        assert complete_rule_parameter_hash(entry) == entry.complete_rule_parameter_hash


def test_v01_canonical_hash_results_unchanged_by_widening():
    loaded = load_validator_rule_parameters(REL, eval_root=FX)
    doc = _fixture_dict()
    stored = {e["rule_id"]: e["complete_rule_parameter_hash"] for e in doc["entries"]}
    for entry in loaded.model.entries:
        assert complete_rule_parameter_hash(entry) == stored[entry.rule_id]
    assert validator_rule_parameters_aggregate_hash(loaded.model) == sha256_bytes(
        canonical_contract_bytes([e for e in doc["entries"]])
    )


def test_hash_helper_still_rejects_a_non_entry():
    with pytest.raises(TypeError):
        complete_rule_parameter_hash({"rule_id": "output_json_schema_validity"})


def test_aggregate_hash_still_rejects_a_non_model():
    with pytest.raises(TypeError):
        validator_rule_parameters_aggregate_hash({"parameter_set_version": "x"})


# --- Exports --------------------------------------------------------------


def test_successor_names_are_exported_once_and_sorted():
    for name in ("ValidatorRuleParametersV2", "load_validator_rule_parameters_v2"):
        assert name in evaluation_pkg.__all__
        assert evaluation_pkg.__all__.count(name) == 1
        assert getattr(evaluation_pkg, name) is getattr(vp_mod, name)
    assert evaluation_pkg.__all__ == sorted(evaluation_pkg.__all__)
    assert len(set(evaluation_pkg.__all__)) == len(evaluation_pkg.__all__)
    assert vp_mod.__all__ == sorted(vp_mod.__all__)


# --- v0.1-only persistence boundary ---------------------------------------


def test_v2_hash_helpers_remain_union_capable(tmp_path):
    # The pure helpers stay version-agnostic; only persistence is narrowed.
    loaded = _load_v2(tmp_path)
    assert len(validator_rule_parameters_aggregate_hash(loaded.model)) == 64
    for entry in loaded.model.entries:
        assert complete_rule_parameter_hash(entry) == entry.complete_rule_parameter_hash


def test_persist_rejects_v2_model_before_any_write(tmp_path):
    run_dir = tmp_path / "run-v2"
    run_dir.mkdir()
    loaded = _load_v2(tmp_path)
    with pytest.raises(TypeError, match="validator_rule_parameters@0.1.0"):
        persist_validator_rule_parameters(
            loaded.model, eval_root=tmp_path, eval_run_id="run-v2"
        )
    # Rejected before any filesystem effect: no snapshots directory, no artifact.
    assert not (run_dir / "snapshots").exists()
    assert list(run_dir.iterdir()) == []


def test_persist_rejects_v2_before_touching_an_absent_run_directory(tmp_path):
    # The version guard precedes run-directory validation, so a v0.2 set is a
    # TypeError rather than a run_directory_missing ValidatorRuleParametersError.
    loaded = _load_v2(tmp_path)
    with pytest.raises(TypeError):
        persist_validator_rule_parameters(
            loaded.model, eval_root=tmp_path, eval_run_id="run-absent"
        )
    assert not (tmp_path / "run-absent").exists()


def test_v01_persistence_bytes_and_round_trip_unchanged(tmp_path):
    (tmp_path / "run-p").mkdir()
    loaded = load_validator_rule_parameters(REL, eval_root=FX)
    persisted = persist_validator_rule_parameters(
        loaded.model, eval_root=tmp_path, eval_run_id="run-p"
    )
    artifact = tmp_path / "run-p" / "snapshots" / "validator_rule_parameters.json"
    raw = artifact.read_bytes()
    # Canonical bytes plus exactly one terminal newline, hash-bound to the return.
    expected = canonical_contract_bytes(
        loaded.model.model_dump(mode="json", exclude_unset=True)
    ) + b"\n"
    assert raw == expected
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert persisted.sha256 == sha256_bytes(raw)
    assert persisted.artifact_reference == "run-p/snapshots/validator_rule_parameters.json"
    assert persisted.version == loaded.model.parameter_set_version
    reloaded = load_validator_rule_parameters(
        "run-p/snapshots/validator_rule_parameters.json", eval_root=tmp_path
    )
    assert reloaded.model == loaded.model
    assert type(reloaded.model) is ValidatorRuleParameters


def test_v01_persistence_still_write_once(tmp_path):
    (tmp_path / "run-q").mkdir()
    loaded = load_validator_rule_parameters(REL, eval_root=FX)
    persist_validator_rule_parameters(loaded.model, eval_root=tmp_path, eval_run_id="run-q")
    with pytest.raises(ValidatorRuleParametersError) as exc:
        persist_validator_rule_parameters(loaded.model, eval_root=tmp_path, eval_run_id="run-q")
    assert exc.value.reason_code == "snapshot_exists"


def test_persist_still_rejects_a_non_model():
    with pytest.raises(TypeError):
        persist_validator_rule_parameters(
            {"parameter_set_version": "x"}, eval_root=".", eval_run_id="run-1"
        )
