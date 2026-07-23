"""Slice 12E: governed classification-axis taxonomy."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from dynamic_ai_products.evaluation import metrics as metrics_mod
from dynamic_ai_products.evaluation import taxonomy as taxonomy_mod
from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.taxonomy import (
    AxisTaxonomy,
    AxisTaxonomyError,
    LoadedAxisTaxonomy,
    axis_taxonomy_hash,
    load_axis_taxonomy,
    persist_axis_taxonomy,
)
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness"
AXIS_REL = "taxonomy/axis_taxonomy.json"
MODEL_HASH = "d6072c16fe82b9e7e7f1f52db2d5f57fdc079ef473c3e8803b0fde2c3e356df3"
CONTRACT_STAMP = {
    "contract_id": "axis_taxonomy",
    "contract_version": "0.1.0",
    "contract_hash": MODEL_HASH,
}


def _fixture_dict():
    return json.loads((FX / "taxonomy" / "axis_taxonomy.json").read_bytes())


def _tax(axes, version="synth-axis-taxonomy-v1"):
    return {"contract": dict(CONTRACT_STAMP), "taxonomy_version": version, "axes": axes}


def _axis(axis_id, role, mt, labels, **ov):
    a = {"axis_id": axis_id, "axis_role": role, "metric_type": mt, "labels": labels}
    a.update(ov)
    return a


# --- Contract identity + surface ------------------------------------------


def test_model_contract_hash_locked():
    assert model_contract_hash(AxisTaxonomy, "axis_taxonomy", "0.1.0") == MODEL_HASH


def test_public_surface():
    assert set(taxonomy_mod.__all__) == {
        "AxisTaxonomy",
        "AxisTaxonomyError",
        "LoadedAxisTaxonomy",
        "axis_taxonomy_hash",
        "load_axis_taxonomy",
        "persist_axis_taxonomy",
    }


def test_reuses_protected_axis_definition_verbatim():
    # The taxonomy embeds the committed metrics.AxisDefinition itself, not a copy.
    assert taxonomy_mod.AxisDefinition is metrics_mod.AxisDefinition


def test_fixture_loads_and_stamps():
    loaded = load_axis_taxonomy(AXIS_REL, eval_root=FX)
    assert isinstance(loaded, LoadedAxisTaxonomy)
    assert len(loaded.model.axes) == 5
    assert loaded.version == "synth-axis-taxonomy-v1"
    assert loaded.model.contract.contract_hash == MODEL_HASH
    # covers every metric family
    assert {a.metric_type for a in loaded.model.axes} == {
        "multi_label", "nominal_single_label", "ordinal_single_label",
        "structured_set", "abstention_allowed",
    }


def test_strict_frozen_extra_forbid():
    loaded = load_axis_taxonomy(AXIS_REL, eval_root=FX)
    with pytest.raises(PydanticValidationError):
        loaded.model.taxonomy_version = "mutated"  # type: ignore[misc]
    bad = _fixture_dict()
    bad["unexpected"] = 1
    with pytest.raises(PydanticValidationError):
        AxisTaxonomy.model_validate(bad)


# --- AxisDefinition-equivalent invariants (enforced by the reused contract) -


def test_ordinal_order_must_equal_labels():
    axis = _axis("ax", "task", "ordinal_single_label", ["low", "high"],
                 ordinal_order=["low"], ordinal_weighting="linear")
    with pytest.raises(PydanticValidationError):
        AxisTaxonomy.model_validate(_tax([axis]))


def test_ordinal_requires_weighting():
    axis = _axis("ax", "task", "ordinal_single_label", ["low", "high"],
                 ordinal_order=["low", "high"])
    with pytest.raises(PydanticValidationError):
        AxisTaxonomy.model_validate(_tax([axis]))


def test_abstention_requires_base():
    axis = _axis("ax", "task", "abstention_allowed", ["a", "b"])
    with pytest.raises(PydanticValidationError):
        AxisTaxonomy.model_validate(_tax([axis]))


def test_non_abstention_forbids_base():
    axis = _axis("ax", "task", "multi_label", ["a", "b"],
                 base_metric_type="nominal_single_label")
    with pytest.raises(PydanticValidationError):
        AxisTaxonomy.model_validate(_tax([axis]))


def test_reserved_label_rejected():
    axis = _axis("ax", "task", "multi_label", ["UNKNOWN", "b"])
    with pytest.raises(PydanticValidationError):
        AxisTaxonomy.model_validate(_tax([axis]))


def test_non_ordinal_declares_ordinal_fields_rejected():
    axis = _axis("ax", "task", "multi_label", ["a", "b"], ordinal_order=["a", "b"])
    with pytest.raises(PydanticValidationError):
        AxisTaxonomy.model_validate(_tax([axis]))


# --- Set-level invariants --------------------------------------------------


def test_empty_axes_rejected():
    with pytest.raises(PydanticValidationError):
        AxisTaxonomy.model_validate(_tax([]))


def test_duplicate_axis_id_rejected():
    axis = _axis("dup", "task", "multi_label", ["a", "b"])
    with pytest.raises(PydanticValidationError):
        AxisTaxonomy.model_validate(_tax([copy.deepcopy(axis), copy.deepcopy(axis)]))


def test_out_of_order_axes_rejected():
    data = _fixture_dict()
    data["axes"] = list(reversed(data["axes"]))
    with pytest.raises(PydanticValidationError):
        AxisTaxonomy.model_validate(data)


def test_blank_taxonomy_version_rejected():
    data = _fixture_dict()
    data["taxonomy_version"] = " "
    with pytest.raises(PydanticValidationError):
        AxisTaxonomy.model_validate(data)


# --- Hash identities -------------------------------------------------------


def test_content_hash_deterministic_and_distinct():
    loaded = load_axis_taxonomy(AXIS_REL, eval_root=FX)
    h1 = axis_taxonomy_hash(loaded.model)
    h2 = axis_taxonomy_hash(loaded.model)
    assert h1 == h2 and len(h1) == 64
    raw_sha = sha256_bytes((FX / "taxonomy" / "axis_taxonomy.json").read_bytes())
    assert h1 != raw_sha
    assert h1 != MODEL_HASH


# --- Persistence -----------------------------------------------------------


def test_persist_write_once_and_read_back(tmp_path):
    (tmp_path / "run-1").mkdir()
    loaded = load_axis_taxonomy(AXIS_REL, eval_root=FX)
    result = persist_axis_taxonomy(loaded.model, eval_root=tmp_path, eval_run_id="run-1")
    dest = tmp_path / "run-1" / "snapshots" / "axis_taxonomy.json"
    raw = dest.read_bytes()
    assert raw.endswith(b"\n")
    assert result.sha256 == sha256_bytes(raw)
    assert axis_taxonomy_hash(loaded.model) != result.sha256
    with pytest.raises(AxisTaxonomyError) as exc:
        persist_axis_taxonomy(loaded.model, eval_root=tmp_path, eval_run_id="run-1")
    assert exc.value.reason_code == "snapshot_exists"


def test_persist_round_trips(tmp_path):
    (tmp_path / "run-2").mkdir()
    loaded = load_axis_taxonomy(AXIS_REL, eval_root=FX)
    persist_axis_taxonomy(loaded.model, eval_root=tmp_path, eval_run_id="run-2")
    reloaded = load_axis_taxonomy("run-2/snapshots/axis_taxonomy.json", eval_root=tmp_path)
    assert reloaded.model == loaded.model


# --- Path / strict-parse security -----------------------------------------


def _write(tmp_path, name, data_bytes):
    p = tmp_path / name
    p.write_bytes(data_bytes)
    return name


def test_expected_hash_mismatch(tmp_path):
    name = _write(tmp_path, "a.json", json.dumps(_fixture_dict()).encode())
    with pytest.raises(AxisTaxonomyError) as exc:
        load_axis_taxonomy(name, eval_root=tmp_path, expected_sha256="0" * 64)
    assert exc.value.reason_code == "expected_hash_mismatch"


def test_traversal_rejected(tmp_path):
    with pytest.raises(AxisTaxonomyError) as exc:
        load_axis_taxonomy("../escape.json", eval_root=tmp_path)
    assert exc.value.reason_code == "unsafe_reference"


def test_symlink_artifact_rejected(tmp_path):
    target = tmp_path / "real.json"
    target.write_bytes(json.dumps(_fixture_dict()).encode())
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(AxisTaxonomyError) as exc:
        load_axis_taxonomy("link.json", eval_root=tmp_path)
    assert exc.value.reason_code == "artifact_symlink"


def test_missing_artifact_rejected(tmp_path):
    with pytest.raises(AxisTaxonomyError) as exc:
        load_axis_taxonomy("absent.json", eval_root=tmp_path)
    assert exc.value.reason_code == "artifact_missing"


def test_eval_root_symlink_rejected(tmp_path):
    real = tmp_path / "real_root"
    real.mkdir()
    link = tmp_path / "link_root"
    link.symlink_to(real)
    with pytest.raises(AxisTaxonomyError) as exc:
        load_axis_taxonomy("a.json", eval_root=link)
    assert exc.value.reason_code == "eval_root_symlink"


def test_duplicate_key_rejected(tmp_path):
    name = _write(tmp_path, "a.json", b'{"a": 1, "a": 2}')
    with pytest.raises(AxisTaxonomyError) as exc:
        load_axis_taxonomy(name, eval_root=tmp_path)
    assert exc.value.reason_code == "duplicate_key"


def test_non_finite_rejected(tmp_path):
    name = _write(tmp_path, "a.json", b'{"x": Infinity}')
    with pytest.raises(AxisTaxonomyError) as exc:
        load_axis_taxonomy(name, eval_root=tmp_path)
    assert exc.value.reason_code == "non_finite"


def test_top_level_array_rejected(tmp_path):
    name = _write(tmp_path, "a.json", b"[]")
    with pytest.raises(AxisTaxonomyError) as exc:
        load_axis_taxonomy(name, eval_root=tmp_path)
    assert exc.value.reason_code == "top_level_type"


def test_model_validation_error(tmp_path):
    name = _write(tmp_path, "a.json", b'{"taxonomy_version": "v"}')
    with pytest.raises(AxisTaxonomyError) as exc:
        load_axis_taxonomy(name, eval_root=tmp_path)
    assert exc.value.reason_code == "model_validation"


# --- Import purity ---------------------------------------------------------


def test_import_no_io_no_hash_no_clock():
    code = "\n".join([
        "import sys, os, hashlib, importlib, time",
        "sys.path.insert(0, 'src')",
        "import pydantic",
        "import dynamic_ai_products, dynamic_ai_products.universe.io_utils",
        "import dynamic_ai_products.evaluation",
        "sys.modules.pop('dynamic_ai_products.evaluation.taxonomy', None)",
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
        "importlib.import_module('dynamic_ai_products.evaluation.taxonomy')",
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
