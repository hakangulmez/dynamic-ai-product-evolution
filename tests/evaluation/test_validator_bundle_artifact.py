"""Slice 12F: validator-bundle artifact reconciliation and persistence."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import validator_bundle_artifact as vb_mod
from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.validator_bundle_artifact import (
    LoadedValidatorBundleArtifact,
    ValidatorBundleArtifact,
    ValidatorBundleArtifactError,
    build_validator_bundle_artifact,
    load_validator_bundle_artifact,
    persist_validator_bundle_artifact,
    validator_bundle_artifact_hash,
)
from dynamic_ai_products.evaluation.validator_parameters import (
    complete_rule_parameter_hash,
    load_validator_rule_parameters,
    validator_rule_parameters_aggregate_hash,
)
from dynamic_ai_products.evaluation.validators import (
    VALIDATOR_RULE_ORDER,
    ValidatorBundle,
    ValidatorRuleConfig,
    validator_bundle_hash,
)
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness"
REL = "validator_bundle/validator_bundle_artifact.json"
MODEL_HASH = "474651b5eb59411dbd13e5a5a3ac3749d618e4dc5e8f39470d698c953524bc5c"

PARAMS = load_validator_rule_parameters(
    "validator_parameters/validator_rule_parameters.json", eval_root=FX
)
ENTRIES = {e.rule_id: e for e in PARAMS.model.entries}
SEVERITIES = {rid: "critical" for rid in VALIDATOR_RULE_ORDER}
REPAIRABLES = {rid: False for rid in VALIDATOR_RULE_ORDER}


def load_bundle(path, *, eval_root, expected_sha256=None):
    return load_validator_bundle_artifact(
        path, eval_root=eval_root, rule_parameters=PARAMS, expected_sha256=expected_sha256
    )


def _fixture_dict():
    return json.loads((FX / "validator_bundle" / "validator_bundle_artifact.json").read_bytes())


def _recompute_bundle_hash(rule_entries):
    rules = tuple(
        ValidatorRuleConfig(
            rule_id=e["rule_id"], severity=e["severity"],
            rule_params_hash=e["rule_params_hash"], repairable=e["repairable"],
        )
        for e in rule_entries
    )
    return validator_bundle_hash(
        ValidatorBundle(bundle_version=_fixture_dict()["bundle_version"], rules=rules)
    )


# --- Contract identity + reconciliation -----------------------------------


def test_model_contract_hash_locked():
    assert model_contract_hash(ValidatorBundleArtifact, "validator_bundle_artifact", "0.1.0") == MODEL_HASH


def test_fixture_loads_twelve_in_order():
    loaded = load_bundle(REL, eval_root=FX)
    assert isinstance(loaded, LoadedValidatorBundleArtifact)
    assert tuple(e.rule_id for e in loaded.model.rule_entries) == VALIDATOR_RULE_ORDER


def test_reconciliation_rule_params_hashes():
    loaded = load_bundle(REL, eval_root=FX)
    for entry in loaded.model.rule_entries:
        assert entry.rule_params_hash == complete_rule_parameter_hash(ENTRIES[entry.rule_id])
    assert loaded.model.parameter_set_aggregate_hash == (
        validator_rule_parameters_aggregate_hash(PARAMS.model)
    )


def test_load_requires_rule_parameters_type():
    with pytest.raises(TypeError):
        load_validator_bundle_artifact(REL, eval_root=FX, rule_parameters=object())


def test_build_produces_reconciled_artifact():
    artifact = build_validator_bundle_artifact(
        PARAMS, bundle_version="synth-validator-bundle-v1",
        severities=SEVERITIES, repairables=REPAIRABLES,
    )
    loaded = load_bundle(REL, eval_root=FX)
    assert artifact == loaded.model


# --- Correction D: coordinated tampering caught at the load boundary -------


def _write_tampered(tmp_path, mutate, name="b.json"):
    data = _fixture_dict()
    mutate(data)
    (tmp_path / name).write_bytes((json.dumps(data) + "\n").encode())
    return name


def test_parameter_version_mismatch_rejected(tmp_path):
    def mut(d):
        d["parameter_set_version"] = "other-params-version"
    name = _write_tampered(tmp_path, mut)
    with pytest.raises(ValidatorBundleArtifactError) as exc:
        load_bundle(name, eval_root=tmp_path)
    assert exc.value.reason_code == "parameter_set_version_mismatch"


def test_parameter_aggregate_hash_mismatch_rejected(tmp_path):
    def mut(d):
        d["parameter_set_aggregate_hash"] = "0" * 64
    name = _write_tampered(tmp_path, mut)
    with pytest.raises(ValidatorBundleArtifactError) as exc:
        load_bundle(name, eval_root=tmp_path)
    assert exc.value.reason_code == "parameter_set_hash_mismatch"


def test_rule_params_hash_mismatch_with_recomputed_bundle_hash_rejected(tmp_path):
    # Self-consistent bundle_hash (recomputed) but rule_params_hash disagrees with params.
    def mut(d):
        d["rule_entries"][0]["rule_params_hash"] = "1" * 64
        d["bundle_hash"] = _recompute_bundle_hash(d["rule_entries"])
    name = _write_tampered(tmp_path, mut)
    with pytest.raises(ValidatorBundleArtifactError) as exc:
        load_bundle(name, eval_root=tmp_path)
    assert exc.value.reason_code == "rule_params_hash_mismatch"


# --- Model self-consistency ------------------------------------------------


def test_tampered_bundle_hash_rejected():
    data = _fixture_dict()
    data["bundle_hash"] = "0" * 64
    with pytest.raises(PydanticValidationError):
        ValidatorBundleArtifact.model_validate(data)


def test_entries_wrong_order_rejected():
    data = _fixture_dict()
    data["rule_entries"] = list(reversed(data["rule_entries"]))
    with pytest.raises(PydanticValidationError):
        ValidatorBundleArtifact.model_validate(data)


def test_content_hash_distinct():
    loaded = load_bundle(REL, eval_root=FX)
    h = validator_bundle_artifact_hash(loaded.model)
    assert len(h) == 64
    assert h != loaded.sha256
    assert h != MODEL_HASH


def test_private_entry_not_exported():
    assert "_BundleArtifactRuleEntry" not in evaluation_pkg.__all__
    assert "_BundleArtifactRuleEntry" not in vb_mod.__all__


# --- Persistence + security ------------------------------------------------


def test_persist_write_once_and_read_back(tmp_path):
    (tmp_path / "run-1").mkdir()
    loaded = load_bundle(REL, eval_root=FX)
    result = persist_validator_bundle_artifact(
        loaded.model, eval_root=tmp_path, eval_run_id="run-1", rule_parameters=PARAMS
    )
    dest = tmp_path / "run-1" / "snapshots" / "validator_bundle_artifact.json"
    raw = dest.read_bytes()
    assert raw.endswith(b"\n")
    assert result.sha256 == sha256_bytes(raw)
    with pytest.raises(ValidatorBundleArtifactError) as exc:
        persist_validator_bundle_artifact(
            loaded.model, eval_root=tmp_path, eval_run_id="run-1", rule_parameters=PARAMS
        )
    assert exc.value.reason_code == "snapshot_exists"


def test_persist_round_trips(tmp_path):
    (tmp_path / "run-2").mkdir()
    loaded = load_bundle(REL, eval_root=FX)
    persist_validator_bundle_artifact(
        loaded.model, eval_root=tmp_path, eval_run_id="run-2", rule_parameters=PARAMS
    )
    reloaded = load_bundle("run-2/snapshots/validator_bundle_artifact.json", eval_root=tmp_path)
    assert reloaded.model == loaded.model


def test_persist_requires_rule_parameters_type(tmp_path):
    (tmp_path / "run-x").mkdir()
    loaded = load_bundle(REL, eval_root=FX)
    with pytest.raises(TypeError):
        persist_validator_bundle_artifact(
            loaded.model, eval_root=tmp_path, eval_run_id="run-x", rule_parameters=object()
        )


def test_poisoned_bundle_not_written(tmp_path):
    # Self-consistent recomputed bundle_hash but rule_params_hash disagrees with params.
    data = _fixture_dict()
    data["rule_entries"][0]["rule_params_hash"] = "1" * 64
    data["bundle_hash"] = _recompute_bundle_hash(data["rule_entries"])
    poisoned = ValidatorBundleArtifact.model_validate(data)
    (tmp_path / "run-1").mkdir()
    with pytest.raises(ValidatorBundleArtifactError) as exc:
        persist_validator_bundle_artifact(
            poisoned, eval_root=tmp_path, eval_run_id="run-1", rule_parameters=PARAMS
        )
    assert exc.value.reason_code == "rule_params_hash_mismatch"
    # No snapshot directory or artifact file was created.
    assert not (tmp_path / "run-1" / "snapshots").exists()


def _write(tmp_path, name, data_bytes):
    (tmp_path / name).write_bytes(data_bytes)
    return name


def test_expected_hash_mismatch(tmp_path):
    name = _write(tmp_path, "b.json", json.dumps(_fixture_dict()).encode())
    with pytest.raises(ValidatorBundleArtifactError) as exc:
        load_bundle(name, eval_root=tmp_path, expected_sha256="0" * 64)
    assert exc.value.reason_code == "expected_hash_mismatch"


def test_traversal_rejected(tmp_path):
    with pytest.raises(ValidatorBundleArtifactError) as exc:
        load_bundle("../escape.json", eval_root=tmp_path)
    assert exc.value.reason_code == "unsafe_reference"


def test_symlink_rejected(tmp_path):
    target = tmp_path / "real.json"
    target.write_bytes(json.dumps(_fixture_dict()).encode())
    (tmp_path / "link.json").symlink_to(target)
    with pytest.raises(ValidatorBundleArtifactError) as exc:
        load_bundle("link.json", eval_root=tmp_path)
    assert exc.value.reason_code == "artifact_symlink"


def test_duplicate_key_rejected(tmp_path):
    name = _write(tmp_path, "b.json", b'{"a": 1, "a": 2}')
    with pytest.raises(ValidatorBundleArtifactError) as exc:
        load_bundle(name, eval_root=tmp_path)
    assert exc.value.reason_code == "duplicate_key"


def test_top_level_array_rejected(tmp_path):
    name = _write(tmp_path, "b.json", b"[]")
    with pytest.raises(ValidatorBundleArtifactError) as exc:
        load_bundle(name, eval_root=tmp_path)
    assert exc.value.reason_code == "top_level_type"


def test_import_no_io_no_hash_no_clock():
    code = "\n".join([
        "import sys, os, hashlib, importlib, time",
        "sys.path.insert(0, 'src')",
        "import pydantic",
        "import dynamic_ai_products, dynamic_ai_products.universe.io_utils",
        "import dynamic_ai_products.evaluation",
        "sys.modules.pop('dynamic_ai_products.evaluation.validator_bundle_artifact', None)",
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
        "importlib.import_module('dynamic_ai_products.evaluation.validator_bundle_artifact')",
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


# --- Correction B: public canonical bundle conversion --------------------


def test_to_validator_bundle_canonical_order_and_hash():
    loaded = load_bundle(REL, eval_root=FX)
    bundle = loaded.model.to_validator_bundle()
    assert isinstance(bundle, ValidatorBundle)
    assert tuple(r.rule_id for r in bundle.rules) == VALIDATOR_RULE_ORDER
    assert validator_bundle_hash(bundle) == loaded.model.bundle_hash
    # Each rule preserves ID, severity, complete rule-parameter hash, repairability.
    for entry, rule in zip(loaded.model.rule_entries, bundle.rules):
        assert rule.rule_id == entry.rule_id
        assert rule.severity == entry.severity
        assert rule.rule_params_hash == entry.rule_params_hash
        assert rule.repairable == entry.repairable


def test_to_validator_bundle_returns_fresh_usable_value():
    loaded = load_bundle(REL, eval_root=FX)
    first = loaded.model.to_validator_bundle()
    second = loaded.model.to_validator_bundle()
    assert first is not second          # a fresh value each call
    assert first == second              # equal by value
    # The fresh value is usable: its hash reconciles to the artifact.
    assert validator_bundle_hash(first) == loaded.model.bundle_hash


def test_model_contract_hash_preserved_with_conversion_method():
    # Adding the to_validator_bundle() method must not change the schema-derived
    # model-contract hash.
    assert model_contract_hash(
        ValidatorBundleArtifact, "validator_bundle_artifact", "0.1.0") == MODEL_HASH
    # The public conversion is a model method, not a new package export.
    assert "to_validator_bundle" not in evaluation_pkg.__all__
