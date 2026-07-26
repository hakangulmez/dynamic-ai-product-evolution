"""Xe0: parent-observation snapshot (`parent_observation_snapshot@0.1.0`).

The snapshot is the sole governed source of Rule-7 `available_parent_ids`:
availability derives only from parent records that OWN an identity, never from a
child's parent-reference field. The loader fail-closes on every ownership /
coherence violation (P2-nonblank ids, canonical ISO cutoff, member SHA/schema,
product context equality, capability-context inheritance via a verified product
parent).
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.parent_observation_snapshot import (
    LoadedParentObservationSnapshot,
    ParentObservationSnapshot,
    ParentObservationSnapshotError,
    load_parent_observation_snapshot,
    verify_child_case_context,
)
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
MODEL_HASH = model_contract_hash(
    ParentObservationSnapshot, "parent_observation_snapshot", "0.1.0")
CUTOFF = "2026-06-30"


def _product(**ov):
    d = {"product_observation_id": "PROD-1", "company_id": "CO-1", "observation_cutoff": CUTOFF,
         "product_name": "Alpha", "availability_status": "ga",
         "evidence": [{"source_id": "s1", "passage_id": "p1", "quote": "q"}], "confidence": "high"}
    d.update(ov)
    return d


def _capability(**ov):
    d = {"capability_observation_id": "CAP-1", "product_observation_id": "PROD-1", "capability": "c",
         "availability_status": "ga",
         "evidence": [{"source_id": "s1", "passage_id": "p1", "quote": "q"}], "confidence": "high"}
    d.update(ov)
    return d


def _write(root, rel, obj):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(obj, indent=1) + "\n").encode("utf-8")
    p.write_bytes(data)
    return sha256_bytes(data)


def _build(root, *, product=None, capability=None, members=None, **snap_ov):
    psha = _write(root, "members/prod.json", product if product is not None else _product())
    csha = _write(root, "members/cap.json", capability if capability is not None else _capability())
    if members is None:
        # Canonical (role, reference) ascending: capability_parent < product_parent.
        members = [
            {"role": "capability_parent", "reference": "members/cap.json", "sha256": csha},
            {"role": "product_parent", "reference": "members/prod.json", "sha256": psha},
        ]
    snap = {"contract": {"contract_id": "parent_observation_snapshot",
                         "contract_version": "0.1.0", "contract_hash": MODEL_HASH},
            "snapshot_version": "pv1", "case_id": "CASE-1", "company_id": "CO-1",
            "observation_cutoff": CUTOFF, "members": members}
    snap.update(snap_ov)
    _write(root, "snap.json", snap)
    return snap


def _load(root):
    return load_parent_observation_snapshot("snap.json", source_root=root)


# --- Contract identity + happy path ---------------------------------------


def test_model_contract_hash_and_strict(tmp_path):
    _build(tmp_path)
    loaded = _load(tmp_path)
    assert isinstance(loaded, LoadedParentObservationSnapshot)
    assert loaded.model.contract.contract_id == "parent_observation_snapshot"
    assert loaded.model.contract.contract_hash == MODEL_HASH
    assert loaded.product_parent_ids == ("PROD-1",)
    assert loaded.capability_parent_ids == ("CAP-1",)
    with pytest.raises(Exception):
        loaded.model.case_id = "x"  # frozen


def test_expected_sha_roundtrip_and_mismatch(tmp_path):
    _build(tmp_path)
    ok = _load(tmp_path)
    assert load_parent_observation_snapshot(
        "snap.json", source_root=tmp_path, expected_sha256=ok.sha256).sha256 == ok.sha256
    with pytest.raises(ParentObservationSnapshotError) as ei:
        load_parent_observation_snapshot("snap.json", source_root=tmp_path, expected_sha256="a" * 64)
    assert ei.value.reason_code == "expected_hash_mismatch"


# --- Availability derives only from parent-owning records ------------------


def test_availability_never_from_child_reference(tmp_path):
    # A capability whose product_observation_id points at PROD-X (not owned by any
    # product parent) must fail-closed — the child reference never creates PROD-X.
    _build(tmp_path, capability=_capability(product_observation_id="PROD-X"))
    with pytest.raises(ParentObservationSnapshotError) as ei:
        _load(tmp_path)
    assert ei.value.reason_code == "capability_context_unverified"
    # And PROD-X never appears as an available product parent.
    _build(tmp_path)
    assert "PROD-X" not in _load(tmp_path).product_parent_ids


# --- Fail-closed ownership + coherence invariants --------------------------


def test_blank_owner_id_fails(tmp_path):
    _build(tmp_path, product=_product(product_observation_id="   "))
    with pytest.raises(ParentObservationSnapshotError) as ei:
        _load(tmp_path)
    assert ei.value.reason_code == "owner_id_blank"


def test_product_context_must_equal_snapshot(tmp_path):
    _build(tmp_path, product=_product(company_id="CO-2"))
    with pytest.raises(ParentObservationSnapshotError) as ei:
        _load(tmp_path)
    assert ei.value.reason_code == "product_context_mismatch"
    _build(tmp_path, product=_product(observation_cutoff="2025-01-01"))
    with pytest.raises(ParentObservationSnapshotError) as ej:
        _load(tmp_path)
    assert ej.value.reason_code == "product_context_mismatch"


def test_member_hash_mismatch_fails(tmp_path):
    snap = _build(tmp_path)
    snap["members"][0]["sha256"] = "b" * 64
    _write(tmp_path, "snap.json", snap)
    with pytest.raises(ParentObservationSnapshotError) as ei:
        _load(tmp_path)
    assert ei.value.reason_code == "member_hash_mismatch"


def test_member_schema_invalid_fails(tmp_path):
    # Drop a required schema field from the product member (SHA re-synced).
    bad = _product()
    del bad["product_name"]
    _build(tmp_path, product=bad)
    with pytest.raises(ParentObservationSnapshotError) as ei:
        _load(tmp_path)
    assert ei.value.reason_code == "member_schema_invalid"


def test_snapshot_cutoff_must_be_canonical_iso(tmp_path):
    _build(tmp_path, observation_cutoff="2026-6-30")
    with pytest.raises(ParentObservationSnapshotError) as ei:
        _load(tmp_path)
    assert ei.value.reason_code == "model_validation"


def test_snapshot_blank_context_fails(tmp_path):
    _build(tmp_path, company_id="  ")
    with pytest.raises(ParentObservationSnapshotError) as ei:
        _load(tmp_path)
    assert ei.value.reason_code == "model_validation"


def test_duplicate_member_rejected_by_model(tmp_path):
    # Duplicate (role, reference) is rejected at model validation.
    psha = _write(tmp_path, "members/prod.json", _product())
    members = [
        {"role": "product_parent", "reference": "members/prod.json", "sha256": psha},
        {"role": "product_parent", "reference": "members/prod.json", "sha256": psha},
    ]
    _build(tmp_path, members=members)
    with pytest.raises(ParentObservationSnapshotError) as ei:
        _load(tmp_path)
    assert ei.value.reason_code == "model_validation"


def test_unsorted_members_rejected_by_model(tmp_path):
    psha = _write(tmp_path, "members/prod.json", _product())
    p2 = _product(product_observation_id="PROD-2")
    p2sha = _write(tmp_path, "members/prod2.json", p2)
    members = [  # out of canonical (role, reference) order
        {"role": "product_parent", "reference": "members/prod2.json", "sha256": p2sha},
        {"role": "product_parent", "reference": "members/prod.json", "sha256": psha},
    ]
    _build(tmp_path, members=members)
    with pytest.raises(ParentObservationSnapshotError) as ei:
        _load(tmp_path)
    assert ei.value.reason_code == "model_validation"


def test_reference_under_two_roles_rejected(tmp_path):
    # A single reference must not appear under two roles (no role/schema ambiguity).
    sha = _write(tmp_path, "members/x.json", _product())
    members = [
        {"role": "capability_parent", "reference": "members/x.json", "sha256": sha},
        {"role": "product_parent", "reference": "members/x.json", "sha256": sha},
    ]
    _build(tmp_path, members=members)
    with pytest.raises(ParentObservationSnapshotError) as ei:
        _load(tmp_path)
    assert ei.value.reason_code == "model_validation"


def test_duplicate_owner_across_distinct_refs(tmp_path):
    # Two distinct product members owning the same product_observation_id fail-closed.
    psha = _write(tmp_path, "members/prod.json", _product())
    p2sha = _write(tmp_path, "members/prod2.json", _product())  # same PROD-1 id
    members = [
        {"role": "product_parent", "reference": "members/prod.json", "sha256": psha},
        {"role": "product_parent", "reference": "members/prod2.json", "sha256": p2sha},
    ]
    _build(tmp_path, members=members)
    with pytest.raises(ParentObservationSnapshotError) as ei:
        _load(tmp_path)
    assert ei.value.reason_code == "duplicate_owner"


def test_schema_anchor_mismatch_fails(tmp_path, monkeypatch):
    # If the committed schema bytes do not match the approved anchor hash, fail-closed.
    import dynamic_ai_products.evaluation.parent_observation_snapshot as pos
    pos._VALIDATOR_CACHE.clear()
    patched = dict(pos._ROLE_SCHEMA)
    path, _sha, owner = patched["product_parent"]
    patched["product_parent"] = (path, "f" * 64, owner)  # wrong anchor
    monkeypatch.setattr(pos, "_ROLE_SCHEMA", patched)
    _build(tmp_path)
    with pytest.raises(ParentObservationSnapshotError) as ei:
        _load(tmp_path)
    assert ei.value.reason_code == "schema_anchor_mismatch"
    pos._VALIDATOR_CACHE.clear()


def test_missing_member_artifact_fails_closed(tmp_path):
    # A model-valid snapshot whose member reference does not exist under source_root
    # must raise a fail-closed ParentObservationSnapshotError, never a TypeError.
    psha = _write(tmp_path, "members/prod.json", _product())
    members = [{"role": "product_parent", "reference": "members/missing.json", "sha256": psha}]
    _build(tmp_path, members=members)
    with pytest.raises(ParentObservationSnapshotError) as ei:
        _load(tmp_path)
    assert ei.value.reason_code == "artifact_missing"


def test_source_root_path_containment(tmp_path):
    # A member reference is a safe, contained relative reference; escapes are rejected.
    sha = _write(tmp_path, "members/prod.json", _product())
    members = [{"role": "product_parent", "reference": "../escape.json", "sha256": sha}]
    _build(tmp_path, members=members)
    with pytest.raises(ParentObservationSnapshotError) as ei:
        _load(tmp_path)
    # Rejected at model validation (unsafe reference) before any escape read.
    assert ei.value.reason_code == "model_validation"


# --- Child case-context binding --------------------------------------------


def test_verify_child_case_context(tmp_path):
    loaded = _build(tmp_path) and _load(tmp_path)
    verify_child_case_context(loaded, case_id="CASE-1", company_id="CO-1", observation_cutoff=CUTOFF)
    for bad in (("OTHER", "CO-1", CUTOFF), ("CASE-1", "CO-2", CUTOFF), ("CASE-1", "CO-1", "2025-01-01")):
        with pytest.raises(ParentObservationSnapshotError) as ei:
            verify_child_case_context(loaded, case_id=bad[0], company_id=bad[1], observation_cutoff=bad[2])
        assert ei.value.reason_code == "case_context_mismatch"


# --- Security + purity -----------------------------------------------------


def test_symlinked_reference_rejected(tmp_path):
    _build(tmp_path)
    external = tmp_path / "external.json"
    external.write_bytes((tmp_path / "members" / "prod.json").read_bytes())
    (tmp_path / "members" / "prod.json").unlink()
    (tmp_path / "members" / "prod.json").symlink_to(external)
    with pytest.raises(ParentObservationSnapshotError) as ei:
        _load(tmp_path)
    assert ei.value.reason_code in ("reference_symlink", "member_hash_mismatch")


def test_import_no_io_no_hash_no_clock():
    code = "\n".join([
        "import sys, os, hashlib, importlib, time",
        "sys.path.insert(0, 'src')",
        "from jsonschema import Draft202012Validator, FormatChecker",
        "import pydantic",
        "import dynamic_ai_products, dynamic_ai_products.universe.io_utils",
        "import dynamic_ai_products.evaluation",
        "sys.modules.pop('dynamic_ai_products.evaluation.parent_observation_snapshot', None)",
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
        "importlib.import_module('dynamic_ai_products.evaluation.parent_observation_snapshot')",
        "Path.read_bytes,Path.read_text,Path.mkdir,os.open,hashlib.sha256=orb,ort,omk,oop,osha",
        "time.time,time.monotonic=ot1,ot2",
        "assert reads==[], reads",
        "assert writes==[] and sha==[] and clock==[], (writes,len(sha),len(clock))",
        "print('OK')",
    ])
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr
