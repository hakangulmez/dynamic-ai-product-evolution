"""Slice 12D: semantic-adapter registry and stage adapters."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import semantic_adapters as sa_mod
from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.models import EvaluationCase, PredictionEnvelope
from dynamic_ai_products.evaluation.semantic_adapters import (
    EvaluationSemanticAdapterRegistry,
    LoadedEvaluationSemanticAdapterRegistry,
    SemanticAdapterError,
    SemanticAdapterRegistryEntry,
    apply_semantic_adapter,
    load_semantic_adapter_registry,
    persist_semantic_adapter_registry,
    resolve_semantic_adapter,
    semantic_adapter_registry_hash,
)
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness"
REG_REL = "semantic_adapters/semantic_adapter_registry.json"
MODEL_HASH = "757766e9f965a18cee4d86ff3490ba5f66076f75993339fc52b9ff72b3812c5c"
PARSED_HASH = "ffeae7ab54fa03948f4498a3ceb5a634b17444791fd91f94a57c086afedbda3e"
ENV_HASH = model_contract_hash(PredictionEnvelope, "prediction_envelope", "0.1.0")
H = "1" * 64


def registry():
    return load_semantic_adapter_registry(REG_REL, eval_root=FX).registry


def case(case_id="C", stage="capability_extraction", sources=("synth-source-0002",),
         passages=("synth-passage-0003",), end="2025-12-31", window=True):
    sc = {"observation_window": {"start": "2025-01-01", "end": end}} if window else {}
    return EvaluationCase.model_validate({
        "case_id": case_id, "stage": stage, "stage_context": sc,
        "input_source_ids": list(sources), "input_passage_ids": list(passages),
        "assertions": [{"assertion_id": "A1", "kind": "expected_entity", "semantic_version": "0.1.0",
                        "target_references": ["X"], "scoring_gate_config_references": ["g"]}],
        "failure_tags": [], "notes": "n", "created_by": "c",
        "created_at": "2026-01-01T00:00:00+00:00", "guideline_version": "v"})


def envelope(stage="capability_extraction", references=("parsed_content/capability_extraction_raw.json",)):
    return PredictionEnvelope.model_validate({
        "contract": {"contract_id": "prediction_envelope", "contract_version": "0.1.0",
                     "contract_hash": ENV_HASH},
        "prediction_record_id": "PR-1", "stage": stage, "source_references": list(references),
        "prompt_model_metadata": {}, "input_packet_hash": H,
        "prediction_run_manifest_reference": "m.json"})


CAP_REF = "parsed_content/capability_extraction_raw.json"
TASK_REF = "parsed_content/task_extraction_cutoff_probe.json"
CAP_BYTES = (FX / CAP_REF).read_bytes()
TASK_BYTES = (FX / TASK_REF).read_bytes()


# --- Registry contract + shape --------------------------------------------


def test_registry_contract_identity_and_hash():
    reg = registry()
    assert reg.contract.contract_id == "evaluation_semantic_adapter_registry"
    assert reg.contract.contract_version == "0.1.0"
    assert reg.contract.contract_hash == MODEL_HASH
    assert model_contract_hash(
        EvaluationSemanticAdapterRegistry, "evaluation_semantic_adapter_registry", "0.1.0") == MODEL_HASH


def test_registry_exactly_two_implemented_entries():
    reg = registry()
    assert [e.evaluation_stage for e in reg.entries] == ["capability_extraction", "task_extraction"]
    for e in reg.entries:
        assert e.support_status == "implemented"
        assert e.output_contract_id == "parsed_prediction_content"
        assert e.output_contract_version == "0.1.0"
        assert e.output_contract_hash == PARSED_HASH
    assert reg.by_stage["capability_extraction"].adapter_id == "capability_extraction_semantic_adapter"
    assert reg.by_stage["task_extraction"].adapter_id == "task_extraction_semantic_adapter"


def test_registry_strict_frozen_extra_forbid():
    reg = registry()
    with pytest.raises(PydanticValidationError):
        reg.registry_version = "x"
    with pytest.raises(PydanticValidationError):
        SemanticAdapterRegistryEntry.model_validate({
            "evaluation_stage": "capability_extraction", "adapter_id": "a", "adapter_version": "0.1.0",
            "output_contract_id": "parsed_prediction_content", "output_contract_version": "0.1.0",
            "output_contract_hash": PARSED_HASH, "support_status": "implemented", "extra": 1})


def test_selected_entry_hash_distinct_from_registry_hash():
    reg = registry()
    entry = resolve_semantic_adapter(reg, "capability_extraction")
    assert entry.entry_hash != semantic_adapter_registry_hash(reg)
    # deterministic
    assert entry.entry_hash == resolve_semantic_adapter(reg, "capability_extraction").entry_hash
    # registry content hash != model-contract hash and != raw-byte sha
    loaded = load_semantic_adapter_registry(REG_REL, eval_root=FX)
    assert semantic_adapter_registry_hash(reg) != loaded.sha256 != MODEL_HASH


def test_resolve_unknown_stage():
    with pytest.raises(SemanticAdapterError) as ei:
        resolve_semantic_adapter(registry(), "product_extraction")
    assert ei.value.reason_code == "unknown_evaluation_stage"


def test_duplicate_stage_rejected():
    doc = json.loads((FX / REG_REL).read_bytes())
    doc["entries"].append(copy.deepcopy(doc["entries"][0]))
    with pytest.raises(PydanticValidationError):
        EvaluationSemanticAdapterRegistry.model_validate(doc)


# --- apply: happy paths ---------------------------------------------------


def test_apply_capability_happy():
    reg = registry()
    content = apply_semantic_adapter(
        reg, case=case(stage="capability_extraction",
                       sources=("synth-source-0002",), passages=("synth-passage-0003",)),
        envelope=envelope("capability_extraction", (CAP_REF,)),
        raw_artifact_reference=CAP_REF, raw_artifact_bytes=CAP_BYTES)
    assert content.stage == "capability_extraction"
    assert content.prediction_record_id == "PR-1"
    assert content.input_packet_hash == H
    assert content.observation_cutoff == "2025-12-31"
    assert content.raw_artifact_reference == CAP_REF
    assert content.raw_artifact_sha256 == sha256_bytes(CAP_BYTES)
    assert content.raw_output_preserved is True
    assert content.repair_applied is False
    # The parsed entity_ref is the governed transform of the observation ID
    # (distinct from the dot-form canonical/stable semantic identity).
    assert [(e.entity_kind, e.entity_ref) for e in content.entity_collection.entities] == [
        ("capability", "SYNTH-CAPABILITY-OBS-0001"), ("product", "SYNTH-PRODUCT-OBS-0001")]
    # Field values are derived from the observation via the fixed capability
    # allowlist (scalar/enum only), each attributed to the capability owner. The
    # canonical/stable identity travels as a field value (separate namespace),
    # never as the matched entity_ref.
    assert [(f.entity_ref, f.field_name, f.field_value)
            for f in content.field_value_collection.field_values] == [
        ("SYNTH-CAPABILITY-OBS-0001", "availability_status", "ga"),
        ("SYNTH-CAPABILITY-OBS-0001", "capability", "Alpha capability"),
        ("SYNTH-CAPABILITY-OBS-0001", "confidence", "high"),
        ("SYNTH-CAPABILITY-OBS-0001", "stable_capability_id", "SYNTH.PRODUCT.ALPHA.CAPABILITY")]


def test_apply_capability_field_allowlist_skips_null_and_arrays():
    reg = registry()
    doc = json.loads(CAP_BYTES)
    doc["stable_capability_id"] = None        # nullable present-null → skipped
    doc["normalized_capability"] = "norm"     # allowlisted string → emitted
    doc["input_types"] = ["text"]             # array → never stringified / excluded
    doc["schema_version"] = "1.0.0"           # allowlisted string → emitted
    content = apply_semantic_adapter(
        reg, case=case(), envelope=envelope("capability_extraction", (CAP_REF,)),
        raw_artifact_reference=CAP_REF, raw_artifact_bytes=json.dumps(doc).encode())
    names = [f.field_name for f in content.field_value_collection.field_values]
    assert names == ["availability_status", "capability", "confidence",
                     "normalized_capability", "schema_version"]


def test_apply_task_preserves_before_equal_after():
    reg = registry()
    content = apply_semantic_adapter(
        reg, case=case(stage="task_extraction",
                       sources=("synth-source-0001", "synth-source-0002", "synth-source-0003"),
                       passages=("synth-passage-0001", "synth-passage-0003", "synth-passage-0004")),
        envelope=envelope("task_extraction", (TASK_REF,)),
        raw_artifact_reference=TASK_REF, raw_artifact_bytes=TASK_BYTES)
    assert content.observation_cutoff == "2025-12-31"
    assert sorted(e.quote for e in content.evidence_collection.evidence) == ["after", "before", "equal"]


# --- apply: stage / reference binding -------------------------------------


def test_apply_stage_mismatch():
    reg = registry()
    with pytest.raises(SemanticAdapterError) as ei:
        apply_semantic_adapter(reg, case=case(stage="capability_extraction"),
                               envelope=envelope("task_extraction", (CAP_REF,)),
                               raw_artifact_reference=CAP_REF, raw_artifact_bytes=CAP_BYTES)
    assert ei.value.reason_code == "stage_mismatch"


def test_apply_unimplemented_stage():
    reg = registry()
    with pytest.raises(SemanticAdapterError) as ei:
        apply_semantic_adapter(reg, case=case(stage="universe_screen"),
                               envelope=envelope("universe_screen", (CAP_REF,)),
                               raw_artifact_reference=CAP_REF, raw_artifact_bytes=CAP_BYTES)
    assert ei.value.reason_code == "unknown_evaluation_stage"


def test_apply_raw_reference_undeclared_and_collision():
    reg = registry()
    with pytest.raises(SemanticAdapterError) as u:
        apply_semantic_adapter(reg, case=case(), envelope=envelope("capability_extraction", ("other.json",)),
                               raw_artifact_reference=CAP_REF, raw_artifact_bytes=CAP_BYTES)
    assert u.value.reason_code == "raw_reference_undeclared"
    with pytest.raises(SemanticAdapterError) as c:
        apply_semantic_adapter(reg, case=case(),
                               envelope=envelope("capability_extraction", (CAP_REF, CAP_REF)),
                               raw_artifact_reference=CAP_REF, raw_artifact_bytes=CAP_BYTES)
    assert c.value.reason_code == "raw_reference_collision"


def test_apply_unsafe_raw_reference():
    reg = registry()
    with pytest.raises(SemanticAdapterError) as ei:
        apply_semantic_adapter(reg, case=case(), envelope=envelope("capability_extraction", ("../x",)),
                               raw_artifact_reference="../x", raw_artifact_bytes=CAP_BYTES)
    assert ei.value.reason_code == "unsafe_reference"


# --- apply: repair chain --------------------------------------------------


def test_apply_repair_chain_preserves_original_and_uses_final():
    reg = registry()
    content = apply_semantic_adapter(
        reg, case=case(stage="task_extraction",
                       sources=("synth-source-0001", "synth-source-0002", "synth-source-0003"),
                       passages=("synth-passage-0001", "synth-passage-0003", "synth-passage-0004")),
        envelope=envelope("task_extraction", (TASK_REF,)),
        raw_artifact_reference=TASK_REF, raw_artifact_bytes=b'{"broken"}',
        repair_records=(("repair/r1.json", b'{"still":"broken"}'), ("repair/r2.json", TASK_BYTES)))
    assert content.repair_applied is True
    assert content.raw_artifact_sha256 == sha256_bytes(b'{"broken"}')  # original preserved
    assert content.repair_record_references == ("repair/r1.json", "repair/r2.json")  # order kept
    assert content.repair_record_hashes == (
        sha256_bytes(b'{"still":"broken"}'), sha256_bytes(TASK_BYTES))
    assert sorted(e.quote for e in content.evidence_collection.evidence) == ["after", "before", "equal"]


def test_apply_repair_reference_collision():
    reg = registry()
    with pytest.raises(SemanticAdapterError) as ei:
        apply_semantic_adapter(reg, case=case(), envelope=envelope("capability_extraction", (CAP_REF,)),
                               raw_artifact_reference=CAP_REF, raw_artifact_bytes=b'{}',
                               repair_records=(("r.json", CAP_BYTES), ("r.json", CAP_BYTES)))
    assert ei.value.reason_code == "repair_reference_collision"


def test_apply_malformed_original_without_valid_repair():
    reg = registry()
    with pytest.raises(SemanticAdapterError) as ei:
        apply_semantic_adapter(reg, case=case(), envelope=envelope("capability_extraction", (CAP_REF,)),
                               raw_artifact_reference=CAP_REF, raw_artifact_bytes=b'{"not":"stage payload"}')
    assert ei.value.reason_code == "raw_artifact_malformed"


def test_apply_extra_field_rejected():
    reg = registry()
    bad = json.dumps({**json.loads(CAP_BYTES), "payload_cutoff": "2020-01-01"}).encode()
    with pytest.raises(SemanticAdapterError) as ei:
        apply_semantic_adapter(reg, case=case(), envelope=envelope("capability_extraction", (CAP_REF,)),
                               raw_artifact_reference=CAP_REF, raw_artifact_bytes=bad)
    assert ei.value.reason_code == "raw_artifact_malformed"


def test_apply_task_observation_rejected_by_capability_adapter():
    reg = registry()
    # A task-observation payload fed to the capability adapter violates the strict
    # capability-observation contract (missing capability_observation_id, extra
    # task-only fields) → malformed, not a distinct wrong-stage code.
    with pytest.raises(SemanticAdapterError) as ei:
        apply_semantic_adapter(reg, case=case(stage="capability_extraction"),
                               envelope=envelope("capability_extraction", (TASK_REF,)),
                               raw_artifact_reference=TASK_REF, raw_artifact_bytes=TASK_BYTES)
    assert ei.value.reason_code == "raw_artifact_malformed"


# --- apply: governed cutoff -----------------------------------------------


def test_apply_cutoff_missing_null_type_malformed():
    reg = registry()
    kw = dict(envelope=envelope("capability_extraction", (CAP_REF,)),
              raw_artifact_reference=CAP_REF, raw_artifact_bytes=CAP_BYTES)
    with pytest.raises(SemanticAdapterError) as m:
        apply_semantic_adapter(reg, case=case(window=False), **kw)
    assert m.value.reason_code == "observation_cutoff_missing"
    c_null = case()
    object.__setattr__(c_null, "stage_context", {"observation_window": {"end": None}})
    with pytest.raises(SemanticAdapterError) as n:
        apply_semantic_adapter(reg, case=c_null, **kw)
    assert n.value.reason_code == "observation_cutoff_null"
    c_type = case()
    object.__setattr__(c_type, "stage_context", {"observation_window": {"end": 20251231}})
    with pytest.raises(SemanticAdapterError) as t:
        apply_semantic_adapter(reg, case=c_type, **kw)
    assert t.value.reason_code == "observation_cutoff_type"
    with pytest.raises(SemanticAdapterError) as b:
        apply_semantic_adapter(reg, case=case(end="2025-13-99"), **kw)
    assert b.value.reason_code == "observation_cutoff_malformed"


def test_apply_ignores_raw_payload_cutoff():
    # The valid raw payload has no cutoff field; the governed case cutoff wins.
    reg = registry()
    content = apply_semantic_adapter(
        reg, case=case(end="2024-06-01"), envelope=envelope("capability_extraction", (CAP_REF,)),
        raw_artifact_reference=CAP_REF, raw_artifact_bytes=CAP_BYTES)
    assert content.observation_cutoff == "2024-06-01"


# --- Loader / persistence -------------------------------------------------


def test_load_happy_and_expected_sha(tmp_path):
    loaded = load_semantic_adapter_registry(REG_REL, eval_root=FX)
    assert isinstance(loaded, LoadedEvaluationSemanticAdapterRegistry)
    good = loaded.sha256
    load_semantic_adapter_registry(REG_REL, eval_root=FX, expected_sha256=good)
    with pytest.raises(SemanticAdapterError) as ei:
        load_semantic_adapter_registry(REG_REL, eval_root=FX, expected_sha256="a" * 64)
    assert ei.value.reason_code == "expected_hash_mismatch"


def test_persist_write_once_and_readback(tmp_path):
    reg = registry()
    (tmp_path / "run1").mkdir()
    persisted = persist_semantic_adapter_registry(reg, eval_root=tmp_path, eval_run_id="run1")
    dest = tmp_path / "run1" / "snapshots" / "semantic_adapter_registry.json"
    raw = dest.read_bytes()
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert persisted.sha256 == sha256_bytes(raw)
    with pytest.raises(SemanticAdapterError) as ei:
        persist_semantic_adapter_registry(reg, eval_root=tmp_path, eval_run_id="run1")
    assert ei.value.reason_code == "snapshot_exists"


def test_load_path_security(tmp_path):
    with pytest.raises(SemanticAdapterError) as ei:
        load_semantic_adapter_registry("../x.json", eval_root=tmp_path)
    assert ei.value.reason_code == "unsafe_reference"
    real = tmp_path / "r.json"
    real.write_text("{}")
    (tmp_path / "l.json").symlink_to(real)
    with pytest.raises(SemanticAdapterError) as s:
        load_semantic_adapter_registry("l.json", eval_root=tmp_path)
    assert s.value.reason_code == "artifact_symlink"


# --- Surface + import purity ----------------------------------------------


def test_module_surface():
    exported = {
        "EvaluationSemanticAdapterRegistry", "LoadedEvaluationSemanticAdapterRegistry",
        "SemanticAdapterError", "SemanticAdapterRegistryEntry", "apply_semantic_adapter",
        "load_semantic_adapter_registry", "persist_semantic_adapter_registry",
        "resolve_semantic_adapter", "semantic_adapter_registry_hash"}
    assert set(sa_mod.__all__) == exported
    for name in exported:
        assert name in evaluation_pkg.__all__
        assert getattr(evaluation_pkg, name) is getattr(sa_mod, name)


def test_import_no_io_no_hash_no_clock():
    code = "\n".join([
        "import sys, os, hashlib, importlib, time",
        "sys.path.insert(0, 'src')",
        "from jsonschema import Draft202012Validator, FormatChecker",
        "import pydantic",
        "import dynamic_ai_products, dynamic_ai_products.universe.models, dynamic_ai_products.universe.io_utils",
        "import dynamic_ai_products.evaluation",
        "sys.modules.pop('dynamic_ai_products.evaluation.semantic_adapters', None)",
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
        "importlib.import_module('dynamic_ai_products.evaluation.semantic_adapters')",
        "Path.read_bytes,Path.read_text,Path.mkdir,os.open,hashlib.sha256=orb,ort,omk,oop,osha",
        "time.time,time.monotonic=ot1,ot2",
        "assert reads==[], reads",
        "assert writes==[] and sha==[] and clock==[], (writes,len(sha),len(clock))",
        "print('OK')",
    ])
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr
