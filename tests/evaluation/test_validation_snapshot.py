"""Slice 12G: validation-artifact snapshot set."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import validation_snapshot as vs_mod
from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.validators import VALIDATOR_RULE_ORDER, ValidationArtifactSnapshot
from dynamic_ai_products.evaluation.validation_snapshot import (
    LoadedValidationArtifactSnapshotSet,
    ValidationArtifactSnapshotSet,
    ValidationArtifactSnapshotSetBindingError,
    ValidationArtifactSnapshotSetError,
    build_validation_artifact_snapshot_set,
    load_validation_artifact_snapshot_set,
    persist_validation_artifact_snapshot_set,
    validation_artifact_snapshot_set_hash,
)
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness"
REL = "validation/validation_artifact_snapshot_set.json"
MODEL_HASH = "51643160bcc7a98b7dd7279c6109d51292d1cd7d3022420271010e3275e6d1a1"
RUN = "synth-eval-run-12g"
CREATED = "2026-07-24T00:00:00+00:00"
REGISTRY_SHA = "10e0cfa69a345583832327a4085e7e5c50e527385e03a420170ef3924c92e01c"

PROTECTED_HASHES = {
    ("validator_finding", "0.1.0"): "96f63fee300d363a662f4f956bacccdca596acfb0f22bf7039aa1335b6d61292",
    ("validator_rule_parameters", "0.1.0"): "f9c20ba936e1c0541c721ac6c3c34bec183b4b360dfa177516c57b0bd0945822",
    ("validator_bundle_artifact", "0.1.0"): "474651b5eb59411dbd13e5a5a3ac3749d618e4dc5e8f39470d698c953524bc5c",
    ("gold_assertion_set", "0.1.0"): "48bb5f185072ed004aa4fcfda30408ff710406ac42bc5ea611d3f5a1fb118cfe",
    ("axis_taxonomy", "0.1.0"): "d6072c16fe82b9e7e7f1f52db2d5f57fdc079ef473c3e8803b0fde2c3e356df3",
    ("parsed_prediction_content", "0.1.0"): "ffeae7ab54fa03948f4498a3ceb5a634b17444791fd91f94a57c086afedbda3e",
}


def _passing_obs(parsed_sha):
    obs = [
        {"rule_id": "output_json_schema_validity", "observation_id": "o1", "parse_succeeded": True,
         "schema_valid": True, "schema_reference": "s.json", "validation_errors": []},
        {"rule_id": "required_field_presence", "observation_id": "o2", "required_fields": ["a", "b"],
         "present_fields": ["a", "b", "c"]},
        {"rule_id": "source_id_resolution", "observation_id": "o3", "referenced_source_ids": ["s1"],
         "available_source_ids": ["s1", "s2"]},
        {"rule_id": "passage_id_resolution", "observation_id": "o4", "referenced_passage_ids": ["p1"],
         "available_passage_ids": ["p1"]},
        {"rule_id": "evidence_quote_containment", "observation_id": "o5", "quote": "alpha",
         "passage_text": "the alpha beta", "passage_id": "p1"},
        {"rule_id": "publication_date_cutoff", "observation_id": "o6", "publication_date": "2020-01-01",
         "observation_cutoff_date": "2020-06-01", "source_id": "s1"},
        {"rule_id": "product_capability_task_parent_resolution", "observation_id": "o7",
         "child_id": "c1", "parent_id": "pp", "available_parent_ids": ["pp", "qq"]},
        {"rule_id": "unique_ids_within_scope", "observation_id": "o8", "scope_id": "sc",
         "record_ids": ["a", "b", "c"]},
        {"rule_id": "prohibited_legacy_fields_absent", "observation_id": "o9",
         "present_field_names": ["x", "y"], "prohibited_field_names": ["legacy"]},
        {"rule_id": "active_record_non_roadmap_evidence", "observation_id": "o10", "active": True,
         "evidence": [{"evidence_id": "e1", "is_future_roadmap": True},
                      {"evidence_id": "e2", "is_future_roadmap": False}]},
        {"rule_id": "customer_task_outcome_and_evidence", "observation_id": "o11",
         "is_customer_facing_task": True, "customer_outcome": "did the thing", "evidence_ids": ["e1"]},
        {"rule_id": "raw_output_and_repair_preservation", "observation_id": "o12",
         "raw_output_reference": "raw.json", "raw_artifact_sha256": "e" * 64,
         "raw_output_preserved": True, "repair_applied": False, "repair_record_references": [],
         "repair_record_hashes": [], "parsed_content_sha256": parsed_sha},
    ]
    return obs


def _coverage():
    return [{"rule_id": r, "coverage_state": "fully_evaluated", "candidate_count": 1,
             "evaluated_observation_count": 1, "blocked_candidate_count": 0, "reason_counts": []}
            for r in VALIDATOR_RULE_ORDER]


def _snapshot(artifact_id, art_sha, parsed_sha, *, stage="capability_extraction", run=RUN):
    return ValidationArtifactSnapshot.model_validate({
        "eval_run_id": run, "artifact_id": artifact_id, "stage": stage,
        "artifact_sha256": art_sha, "parsed_prediction_content_sha256": parsed_sha,
        "created_at": CREATED, "case_id": "SYNTH-CASE-0001",
        "observations": _passing_obs(parsed_sha), "coverage": _coverage(),
    })


def _set(*, snapshots=None, version="synth-validation-snapshot-set-v1", run=RUN,
         stage="capability_extraction"):
    if snapshots is None:
        snapshots = (_snapshot("art-0001", "a" * 64, "c" * 64),
                     _snapshot("art-0002", "b" * 64, "d" * 64))
    return build_validation_artifact_snapshot_set(
        snapshot_set_version=version, eval_run_id=run,
        evaluation_stage=stage, snapshots=snapshots,
    )


def _fixture_dict():
    return json.loads((FX / "validation" / "validation_artifact_snapshot_set.json").read_bytes())


# --- Contract identity + surface ------------------------------------------


def test_model_contract_hash_locked():
    assert model_contract_hash(
        ValidationArtifactSnapshotSet, "validation_artifact_snapshot_set", "0.1.0"
    ) == MODEL_HASH


def test_public_surface():
    assert set(vs_mod.__all__) == {
        "LoadedValidationArtifactSnapshotSet", "ValidationArtifactSnapshotSet",
        "ValidationArtifactSnapshotSetBindingError", "ValidationArtifactSnapshotSetError",
        "build_validation_artifact_snapshot_set", "load_validation_artifact_snapshot_set",
        "persist_validation_artifact_snapshot_set", "validation_artifact_snapshot_set_hash",
    }


def test_fixture_loads_and_round_trips():
    loaded = load_validation_artifact_snapshot_set(REL, eval_root=FX)
    assert isinstance(loaded, LoadedValidationArtifactSnapshotSet)
    assert loaded.model.evaluation_stage == "capability_extraction"
    assert len(loaded.model.snapshots) == 2
    reparsed = ValidationArtifactSnapshotSet.model_validate(
        json.loads(loaded.model.model_dump_json())
    )
    assert reparsed == loaded.model


def test_strict_frozen_extra_forbid():
    loaded = load_validation_artifact_snapshot_set(REL, eval_root=FX)
    with pytest.raises(PydanticValidationError):
        loaded.model.eval_run_id = "mutated"  # type: ignore[misc]
    bad = _fixture_dict()
    bad["unexpected"] = 1
    with pytest.raises(PydanticValidationError):
        ValidationArtifactSnapshotSet.model_validate(bad)


def test_builder_type_guard():
    with pytest.raises(TypeError):
        build_validation_artifact_snapshot_set(
            snapshot_set_version="v", eval_run_id=RUN,
            evaluation_stage="capability_extraction", snapshots=(object(),),
        )


def test_builder_generates_contract_stamp():
    model = _set()
    assert model.contract.contract_id == "validation_artifact_snapshot_set"
    assert model.contract.contract_version == "0.1.0"
    assert model.contract.contract_hash == MODEL_HASH == model_contract_hash(
        ValidationArtifactSnapshotSet, "validation_artifact_snapshot_set", "0.1.0"
    )


# --- Content hash identities ----------------------------------------------


def test_content_hash_deterministic_and_distinct():
    model = _set()
    h1 = validation_artifact_snapshot_set_hash(model)
    h2 = validation_artifact_snapshot_set_hash(model)
    assert h1 == h2 and len(h1) == 64
    raw_sha = sha256_bytes((FX / "validation" / "validation_artifact_snapshot_set.json").read_bytes())
    assert h1 != raw_sha        # content hash (no newline) != raw-byte sha
    assert h1 != MODEL_HASH     # content hash != model-contract hash


# --- Set-level invariants --------------------------------------------------


def test_empty_set_rejected():
    with pytest.raises(PydanticValidationError):
        _set(snapshots=())


def test_duplicate_artifact_id_rejected():
    dup = (_snapshot("art-0001", "a" * 64, "c" * 64), _snapshot("art-0001", "b" * 64, "d" * 64))
    with pytest.raises(PydanticValidationError):
        _set(snapshots=dup)


def test_wrong_ordering_rejected():
    rev = (_snapshot("art-0002", "b" * 64, "d" * 64), _snapshot("art-0001", "a" * 64, "c" * 64))
    with pytest.raises(PydanticValidationError):
        _set(snapshots=rev)


def test_cross_run_snapshot_rejected():
    snaps = (_snapshot("art-0001", "a" * 64, "c" * 64),
             _snapshot("art-0002", "b" * 64, "d" * 64, run="other-run"))
    with pytest.raises(PydanticValidationError):
        _set(snapshots=snaps)


def test_mixed_stage_snapshot_rejected():
    snaps = (_snapshot("art-0001", "a" * 64, "c" * 64),
             _snapshot("art-0002", "b" * 64, "d" * 64, stage="task_extraction"))
    with pytest.raises(PydanticValidationError):
        _set(snapshots=snaps)


def test_snapshot_set_version_internal_newline_rejected():
    with pytest.raises(PydanticValidationError):
        _set(version="line1\nline2")


def test_snapshot_set_version_valid_accepted():
    model = _set(version="valid-set-version-1")
    assert model.snapshot_set_version == "valid-set-version-1"


def test_per_element_coverage_retained():
    loaded = load_validation_artifact_snapshot_set(REL, eval_root=FX)
    for snapshot in loaded.model.snapshots:
        assert tuple(c.rule_id for c in snapshot.coverage) == VALIDATOR_RULE_ORDER
        rule12 = next(o for o in snapshot.observations
                      if o.rule_id == "raw_output_and_repair_preservation")
        assert rule12.parsed_content_sha256 == snapshot.parsed_prediction_content_sha256


def test_rule12_parsed_binding_enforced_at_element():
    # An element whose Rule-12 parsed_content_sha256 disagrees is rejected by the
    # reused ValidationArtifactSnapshot model, before it can enter the set.
    obs = _passing_obs("c" * 64)
    obs[-1]["parsed_content_sha256"] = "f" * 64
    with pytest.raises(PydanticValidationError):
        ValidationArtifactSnapshot.model_validate({
            "eval_run_id": RUN, "artifact_id": "art-0001", "stage": "capability_extraction",
            "artifact_sha256": "a" * 64, "parsed_prediction_content_sha256": "c" * 64,
            "created_at": CREATED, "case_id": "SYNTH-CASE-0001",
            "observations": obs, "coverage": _coverage(),
        })


# --- Persistence -----------------------------------------------------------


def test_persist_eval_run_id_mismatch_before_write(tmp_path):
    (tmp_path / "other-run").mkdir()
    model = _set()  # model.eval_run_id == RUN
    with pytest.raises(ValidationArtifactSnapshotSetBindingError) as exc:
        persist_validation_artifact_snapshot_set(model, eval_root=tmp_path, eval_run_id="other-run")
    assert exc.value.binding_kind == "persist_eval_run_id_mismatch"
    # No snapshot directory or artifact was created.
    assert not (tmp_path / "other-run" / "snapshots").exists()


def test_persist_invalid_eval_run_id_is_artifact_error(tmp_path):
    # A syntactically invalid explicit run ID is a Family-B artifact error, not a
    # binding error, and precedes any filesystem mutation.
    model = _set()
    with pytest.raises(ValidationArtifactSnapshotSetError) as exc:
        persist_validation_artifact_snapshot_set(model, eval_root=tmp_path, eval_run_id="bad/id")
    assert exc.value.reason_code == "invalid_eval_run_id"


def test_persist_write_once_read_back_and_lf(tmp_path):
    (tmp_path / RUN).mkdir()
    model = _set()
    result = persist_validation_artifact_snapshot_set(model, eval_root=tmp_path, eval_run_id=RUN)
    dest = tmp_path / RUN / "snapshots" / "validation_artifact_snapshot_set.json"
    raw = dest.read_bytes()
    assert raw.endswith(b"\n")
    assert result.sha256 == sha256_bytes(raw)
    assert validation_artifact_snapshot_set_hash(model) != result.sha256
    with pytest.raises(ValidationArtifactSnapshotSetError) as exc:
        persist_validation_artifact_snapshot_set(model, eval_root=tmp_path, eval_run_id=RUN)
    assert exc.value.reason_code == "snapshot_exists"


def test_persist_round_trips(tmp_path):
    (tmp_path / RUN).mkdir()
    model = _set()
    persist_validation_artifact_snapshot_set(model, eval_root=tmp_path, eval_run_id=RUN)
    reloaded = load_validation_artifact_snapshot_set(
        f"{RUN}/snapshots/validation_artifact_snapshot_set.json", eval_root=tmp_path
    )
    assert reloaded.model == model


def test_persist_write_failure(tmp_path, monkeypatch):
    (tmp_path / RUN).mkdir()
    model = _set()

    def boom(*a, **k):
        raise OSError("synthetic write failure")

    monkeypatch.setattr(vs_mod.os, "open", boom)
    with pytest.raises(ValidationArtifactSnapshotSetError) as exc:
        persist_validation_artifact_snapshot_set(model, eval_root=tmp_path, eval_run_id=RUN)
    assert exc.value.reason_code == "write_error"


def test_persist_destination_hash_mismatch(tmp_path, monkeypatch):
    (tmp_path / RUN).mkdir()
    model = _set()
    orig = Path.read_bytes

    def tampered(self):
        if self.name == "validation_artifact_snapshot_set.json":
            return b"tampered"
        return orig(self)

    monkeypatch.setattr(Path, "read_bytes", tampered)
    with pytest.raises(ValidationArtifactSnapshotSetError) as exc:
        persist_validation_artifact_snapshot_set(model, eval_root=tmp_path, eval_run_id=RUN)
    assert exc.value.reason_code == "destination_hash_mismatch"


# --- Loader security / strict parse ---------------------------------------


def _write(tmp_path, name, data_bytes):
    (tmp_path / name).write_bytes(data_bytes)
    return name


def test_expected_hash_mismatch(tmp_path):
    name = _write(tmp_path, "v.json", json.dumps(_fixture_dict()).encode())
    with pytest.raises(ValidationArtifactSnapshotSetError) as exc:
        load_validation_artifact_snapshot_set(name, eval_root=tmp_path, expected_sha256="0" * 64)
    assert exc.value.reason_code == "expected_hash_mismatch"


def test_traversal_rejected(tmp_path):
    with pytest.raises(ValidationArtifactSnapshotSetError) as exc:
        load_validation_artifact_snapshot_set("../escape.json", eval_root=tmp_path)
    assert exc.value.reason_code == "unsafe_reference"


def test_absolute_rejected(tmp_path):
    with pytest.raises(ValidationArtifactSnapshotSetError) as exc:
        load_validation_artifact_snapshot_set("/etc/hosts", eval_root=tmp_path)
    assert exc.value.reason_code == "unsafe_reference"


def test_symlink_artifact_rejected(tmp_path):
    target = tmp_path / "real.json"
    target.write_bytes(json.dumps(_fixture_dict()).encode())
    (tmp_path / "link.json").symlink_to(target)
    with pytest.raises(ValidationArtifactSnapshotSetError) as exc:
        load_validation_artifact_snapshot_set("link.json", eval_root=tmp_path)
    assert exc.value.reason_code == "artifact_symlink"


def test_missing_artifact_rejected(tmp_path):
    with pytest.raises(ValidationArtifactSnapshotSetError) as exc:
        load_validation_artifact_snapshot_set("absent.json", eval_root=tmp_path)
    assert exc.value.reason_code == "artifact_missing"


def test_eval_root_symlink_rejected(tmp_path):
    real = tmp_path / "real_root"
    real.mkdir()
    (tmp_path / "link_root").symlink_to(real)
    with pytest.raises(ValidationArtifactSnapshotSetError) as exc:
        load_validation_artifact_snapshot_set("v.json", eval_root=tmp_path / "link_root")
    assert exc.value.reason_code == "eval_root_symlink"


def test_duplicate_key_rejected(tmp_path):
    name = _write(tmp_path, "v.json", b'{"a": 1, "a": 2}')
    with pytest.raises(ValidationArtifactSnapshotSetError) as exc:
        load_validation_artifact_snapshot_set(name, eval_root=tmp_path)
    assert exc.value.reason_code == "duplicate_key"


def test_non_finite_rejected(tmp_path):
    name = _write(tmp_path, "v.json", b'{"x": NaN}')
    with pytest.raises(ValidationArtifactSnapshotSetError) as exc:
        load_validation_artifact_snapshot_set(name, eval_root=tmp_path)
    assert exc.value.reason_code == "non_finite"


def test_top_level_array_rejected(tmp_path):
    name = _write(tmp_path, "v.json", b"[]")
    with pytest.raises(ValidationArtifactSnapshotSetError) as exc:
        load_validation_artifact_snapshot_set(name, eval_root=tmp_path)
    assert exc.value.reason_code == "top_level_type"


def test_model_validation_error(tmp_path):
    name = _write(tmp_path, "v.json", b'{"snapshot_set_version": "v"}')
    with pytest.raises(ValidationArtifactSnapshotSetError) as exc:
        load_validation_artifact_snapshot_set(name, eval_root=tmp_path)
    assert exc.value.reason_code == "model_validation"


# --- Protected invariants + parity ----------------------------------------


def test_protected_contract_hashes():
    from dynamic_ai_products.evaluation.gold import GoldAssertionSet
    from dynamic_ai_products.evaluation.models import ValidatorFinding
    from dynamic_ai_products.evaluation.prediction_content import ParsedPredictionContent
    from dynamic_ai_products.evaluation.taxonomy import AxisTaxonomy
    from dynamic_ai_products.evaluation.validator_bundle_artifact import ValidatorBundleArtifact
    from dynamic_ai_products.evaluation.validator_parameters import ValidatorRuleParameters

    mapping = {
        ("validator_finding", "0.1.0"): ValidatorFinding,
        ("validator_rule_parameters", "0.1.0"): ValidatorRuleParameters,
        ("validator_bundle_artifact", "0.1.0"): ValidatorBundleArtifact,
        ("gold_assertion_set", "0.1.0"): GoldAssertionSet,
        ("axis_taxonomy", "0.1.0"): AxisTaxonomy,
        ("parsed_prediction_content", "0.1.0"): ParsedPredictionContent,
    }
    for (cid, ver), cls in mapping.items():
        assert model_contract_hash(cls, cid, ver) == PROTECTED_HASHES[(cid, ver)]


def test_target_registry_byte_identity():
    observed = sha256_bytes((FX / "configs" / "valid_target_registry.json").read_bytes())
    assert observed == REGISTRY_SHA


def test_package_export_parity():
    assert len(evaluation_pkg.__all__) == 502
    assert evaluation_pkg.__all__ == sorted(evaluation_pkg.__all__)
    assert len(set(evaluation_pkg.__all__)) == len(evaluation_pkg.__all__)
    for name in vs_mod.__all__:
        assert name in evaluation_pkg.__all__


def test_manifest_parity():
    import re
    lines = (ROOT / "REPO_MANIFEST.md").read_text().splitlines()
    paths = [re.match(r"- `([^`]+)`", ln).group(1) for ln in lines if re.match(r"- `[^`]+`\s*$", ln)]
    assert len(paths) == 354
    assert len(set(paths)) == len(paths)
    section = [p for p in paths if p.startswith(("evals/fixtures/evaluation_harness/",
                                                 "src/dynamic_ai_products/evaluation/",
                                                 "tests/evaluation/"))]
    assert section == sorted(section)
    for p in (
        "evals/fixtures/evaluation_harness/validation/validation_artifact_snapshot_set.json",
        "src/dynamic_ai_products/evaluation/validation_snapshot.py",
        "tests/evaluation/test_validation_snapshot.py",
    ):
        assert paths.count(p) == 1


# --- Import purity ---------------------------------------------------------


def test_import_no_io_no_hash_no_clock():
    code = "\n".join([
        "import sys, os, hashlib, importlib, time",
        "sys.path.insert(0, 'src')",
        "import pydantic",
        "import dynamic_ai_products, dynamic_ai_products.universe.io_utils",
        "import dynamic_ai_products.evaluation",
        "sys.modules.pop('dynamic_ai_products.evaluation.validation_snapshot', None)",
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
        "importlib.import_module('dynamic_ai_products.evaluation.validation_snapshot')",
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
