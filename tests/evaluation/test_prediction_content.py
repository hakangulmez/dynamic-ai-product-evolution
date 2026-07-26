"""Slice 12D: parsed prediction content (derived output)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import prediction_content as pc_mod
from dynamic_ai_products.evaluation.contracts import canonical_contract_bytes, model_contract_hash
from dynamic_ai_products.evaluation.prediction_content import (
    LoadedParsedPredictionContent,
    ParsedEntityCollection,
    ParsedEvidenceCollection,
    ParsedFieldValueCollection,
    ParsedPredictionContent,
    ParsedPredictionContentError,
    load_parsed_prediction_content,
    parsed_prediction_content_artifact_bytes,
    parsed_prediction_content_artifact_sha256,
    persist_parsed_prediction_content,
)
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
MODEL_HASH = "ffeae7ab54fa03948f4498a3ceb5a634b17444791fd91f94a57c086afedbda3e"
H = "a" * 64


def stamp():
    return {"contract_id": "parsed_prediction_content", "contract_version": "0.1.0",
            "contract_hash": MODEL_HASH}


def base_doc(**ov):
    doc = {
        "contract": stamp(),
        "case_id": "C1", "stage": "capability_extraction", "prediction_record_id": "PR-1",
        "input_packet_hash": H, "observation_cutoff": "2025-12-31",
        "raw_artifact_reference": "parsed_content/raw.json", "raw_artifact_sha256": H,
        "raw_output_preserved": True, "repair_applied": False,
        "repair_record_references": [], "repair_record_hashes": [],
        "entity_collection": {"completeness": "complete", "entities": [
            {"entity_kind": "product", "entity_ref": "P.A"}]},
        "field_value_collection": {"completeness": "complete", "field_values": [
            {"entity_ref": "P.A", "field_name": "maturity", "field_value": "ga"}]},
        "evidence_collection": {"completeness": "complete", "evidence": [
            {"entity_ref": "P.A", "source_id": "s1", "passage_id": "p1", "quote": "q"}]},
    }
    doc.update(ov)
    return doc


def content(**ov):
    return ParsedPredictionContent.model_validate(base_doc(**ov))


# --- Contract identity ----------------------------------------------------


def test_contract_identity_and_hash():
    c = content()
    assert c.contract.contract_id == "parsed_prediction_content"
    assert c.contract.contract_version == "0.1.0"
    assert c.contract.contract_hash == MODEL_HASH
    assert model_contract_hash(ParsedPredictionContent, "parsed_prediction_content", "0.1.0") == MODEL_HASH


def test_strict_frozen_extra_forbid():
    c = content()
    with pytest.raises(PydanticValidationError):
        c.case_id = "x"
    with pytest.raises(PydanticValidationError):
        ParsedPredictionContent.model_validate({**base_doc(), "unexpected": 1})


def test_exact_stage_literal():
    for stage in ("capability_extraction", "task_extraction", "universe_screen", "universe_classification"):
        content(stage=stage)
    with pytest.raises(PydanticValidationError):
        content(stage="not_a_stage")


def test_all_fields_reject_explicit_null():
    for field in ("case_id", "stage", "prediction_record_id", "input_packet_hash",
                  "observation_cutoff", "raw_artifact_reference", "raw_artifact_sha256",
                  "raw_output_preserved", "repair_applied", "entity_collection"):
        with pytest.raises(PydanticValidationError):
            ParsedPredictionContent.model_validate({**base_doc(), field: None})


# --- Collection completeness + identity ----------------------------------


def test_completeness_unavailable_requires_empty():
    ParsedEntityCollection.model_validate({"completeness": "unavailable", "entities": []})
    with pytest.raises(PydanticValidationError):
        ParsedEntityCollection.model_validate({"completeness": "unavailable", "entities": [
            {"entity_kind": "product", "entity_ref": "P"}]})
    # complete/partial may be empty or non-empty
    ParsedFieldValueCollection.model_validate({"completeness": "partial", "field_values": []})
    ParsedEvidenceCollection.model_validate({"completeness": "complete", "evidence": []})


def test_collections_sorted_and_unique():
    unsorted = base_doc(entity_collection={"completeness": "complete", "entities": [
        {"entity_kind": "product", "entity_ref": "P.B"},
        {"entity_kind": "product", "entity_ref": "P.A"}]})
    with pytest.raises(PydanticValidationError):
        ParsedPredictionContent.model_validate(unsorted)
    dup = base_doc(entity_collection={"completeness": "complete", "entities": [
        {"entity_kind": "product", "entity_ref": "P.A"},
        {"entity_kind": "product", "entity_ref": "P.A"}]})
    with pytest.raises(PydanticValidationError):
        ParsedPredictionContent.model_validate(dup)


def test_field_and_evidence_entity_integrity():
    with pytest.raises(PydanticValidationError) as ei:
        ParsedPredictionContent.model_validate(base_doc(field_value_collection={
            "completeness": "complete", "field_values": [
                {"entity_ref": "UNKNOWN", "field_name": "f", "field_value": "v"}]}))
    assert "field_entity_unresolved" in str(ei.value)
    with pytest.raises(PydanticValidationError) as ej:
        ParsedPredictionContent.model_validate(base_doc(evidence_collection={
            "completeness": "complete", "evidence": [
                {"entity_ref": "UNKNOWN", "source_id": "s", "passage_id": "p", "quote": "q"}]}))
    assert "evidence_entity_unresolved" in str(ej.value)


# --- observation_cutoff + raw_artifact_reference behavioral validation ----


@pytest.mark.parametrize("bad", [
    "2025-13-99", "2025-1-1", "2025/12/31", "2025-12-31T00:00:00Z", "", " 2025-12-31",
    "2025-12-31 ", "not-a-date",
])
def test_observation_cutoff_rejects_noncanonical_and_malformed(bad):
    with pytest.raises(PydanticValidationError):
        content(observation_cutoff=bad)


def test_observation_cutoff_accepts_canonical_full_date():
    assert content(observation_cutoff="2025-12-31").observation_cutoff == "2025-12-31"
    assert content(observation_cutoff="2026-01-01").observation_cutoff == "2026-01-01"


@pytest.mark.parametrize("bad", [
    "/abs.json", "../x.json", "./x.json", "a\\b.json", "a\x00b.json", " x.json", "x.json ", "",
    "a//b.json",
])
def test_raw_artifact_reference_safe_reference_policy(bad):
    with pytest.raises(PydanticValidationError):
        content(raw_artifact_reference=bad)


def test_raw_artifact_reference_valid_relative_retained():
    c = content(raw_artifact_reference="parsed_content/raw.json")
    assert c.raw_artifact_reference == "parsed_content/raw.json"


def test_load_fails_closed_on_invalid_cutoff_and_reference(tmp_path):
    invalid_docs = [
        base_doc(observation_cutoff="2025-13-99"),
        base_doc(observation_cutoff="2025-1-1"),
        base_doc(raw_artifact_reference="../x.json"),
        base_doc(raw_artifact_reference="/abs.json"),
    ]
    for index, doc in enumerate(invalid_docs):
        ref = _write(tmp_path, json.dumps(doc).encode(), run=f"bad{index}")
        with pytest.raises(ParsedPredictionContentError) as ei:
            load_parsed_prediction_content(ref, eval_root=tmp_path)
        assert ei.value.reason_code == "model_validation"


def test_empty_field_value_and_quote_still_permitted():
    content(field_value_collection={"completeness": "complete", "field_values": [
        {"entity_ref": "P.A", "field_name": "f", "field_value": ""}]})
    content(evidence_collection={"completeness": "complete", "evidence": [
        {"entity_ref": "P.A", "source_id": "s", "passage_id": "p", "quote": ""}]})


# --- Raw-output / repair invariants ---------------------------------------


def test_no_repair_requires_empty_tuples():
    content(repair_applied=False, repair_record_references=[], repair_record_hashes=[])
    with pytest.raises(PydanticValidationError):
        content(repair_applied=False, repair_record_references=["r1"], repair_record_hashes=[H])


def test_repair_applied_pairing_and_alignment():
    content(repair_applied=True, repair_record_references=["r1", "r2"], repair_record_hashes=[H, "b" * 64])
    with pytest.raises(PydanticValidationError):  # unequal length
        content(repair_applied=True, repair_record_references=["r1"], repair_record_hashes=[H, H])
    with pytest.raises(PydanticValidationError):  # empty despite applied
        content(repair_applied=True, repair_record_references=[], repair_record_hashes=[])
    with pytest.raises(PydanticValidationError):  # duplicate reference
        content(repair_applied=True, repair_record_references=["r1", "r1"], repair_record_hashes=[H, H])
    with pytest.raises(PydanticValidationError):  # unsafe reference
        content(repair_applied=True, repair_record_references=["../x"], repair_record_hashes=[H])
    with pytest.raises(PydanticValidationError):  # non-hex hash
        content(repair_applied=True, repair_record_references=["r1"], repair_record_hashes=["nothex"])


def test_raw_output_preserved_false_is_structurally_valid():
    c = content(raw_output_preserved=False)
    assert c.raw_output_preserved is False


def test_hash_fields_lowercase_64_hex():
    for field in ("input_packet_hash", "raw_artifact_sha256"):
        for bad in ("A" * 64, "a" * 63, "g" * 64):
            with pytest.raises(PydanticValidationError):
                content(**{field: bad})


# --- Persistence + load ---------------------------------------------------


def test_persist_canonical_one_newline_and_readback(tmp_path):
    c = content()
    (tmp_path / "run1").mkdir()
    persisted = persist_parsed_prediction_content(c, eval_root=tmp_path, eval_run_id="run1")
    dest = tmp_path / "run1" / "snapshots" / "parsed_prediction_content.json"
    raw = dest.read_bytes()
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert raw[:-1] == canonical_contract_bytes(c.model_dump(mode="json", exclude_unset=True))
    assert persisted.sha256 == sha256_bytes(raw)
    reloaded = load_parsed_prediction_content("run1/snapshots/parsed_prediction_content.json", eval_root=tmp_path)
    assert reloaded.sha256 == sha256_bytes(raw)
    assert reloaded.content == c
    assert isinstance(reloaded, LoadedParsedPredictionContent)


def test_persist_write_once(tmp_path):
    c = content()
    (tmp_path / "run1").mkdir()
    persist_parsed_prediction_content(c, eval_root=tmp_path, eval_run_id="run1")
    with pytest.raises(ParsedPredictionContentError) as ei:
        persist_parsed_prediction_content(c, eval_root=tmp_path, eval_run_id="run1")
    assert ei.value.reason_code == "snapshot_exists"


def _write(tmp_path, content_bytes, run="run1"):
    d = tmp_path / run / "snapshots"
    d.mkdir(parents=True, exist_ok=True)
    (d / "parsed_prediction_content.json").write_bytes(content_bytes)
    return f"{run}/snapshots/parsed_prediction_content.json"


def test_load_failures(tmp_path):
    ref = _write(tmp_path, b"{not json")
    with pytest.raises(ParsedPredictionContentError) as j:
        load_parsed_prediction_content(ref, eval_root=tmp_path)
    assert j.value.reason_code == "json_error"
    ref = _write(tmp_path, b'{"x": NaN}', run="r2")
    with pytest.raises(ParsedPredictionContentError) as n:
        load_parsed_prediction_content(ref, eval_root=tmp_path)
    assert n.value.reason_code == "non_finite"
    ref = _write(tmp_path, b"[1,2]", run="r3")
    with pytest.raises(ParsedPredictionContentError) as t:
        load_parsed_prediction_content(ref, eval_root=tmp_path)
    assert t.value.reason_code == "top_level_type"
    ref = _write(tmp_path, b'{"a":1,"a":2}', run="r4")
    with pytest.raises(ParsedPredictionContentError) as d:
        load_parsed_prediction_content(ref, eval_root=tmp_path)
    assert d.value.reason_code == "duplicate_key"
    ref = _write(tmp_path, json.dumps(base_doc()).encode(), run="r5")
    with pytest.raises(ParsedPredictionContentError) as h:
        load_parsed_prediction_content(ref, eval_root=tmp_path, expected_sha256="a" * 64)
    assert h.value.reason_code == "expected_hash_mismatch"


def test_load_contract_invalid(tmp_path):
    bad = base_doc(contract={"contract_id": "parsed_prediction_content",
                             "contract_version": "0.1.0", "contract_hash": "0" * 64})
    ref = _write(tmp_path, json.dumps(bad).encode())
    with pytest.raises(ParsedPredictionContentError) as ei:
        load_parsed_prediction_content(ref, eval_root=tmp_path)
    assert ei.value.reason_code == "model_validation"


# --- Surface + import purity ----------------------------------------------


def test_module_surface():
    exported = {
        "LoadedParsedPredictionContent", "ParsedEntityCollection", "ParsedEvidenceCollection",
        "ParsedFieldValueCollection", "ParsedPredictionContent", "ParsedPredictionContentError",
        "load_parsed_prediction_content", "persist_parsed_prediction_content",
        # P1: the public artifact-bytes/SHA preparation boundary.
        "parsed_prediction_content_artifact_bytes",
        "parsed_prediction_content_artifact_sha256"}
    assert set(pc_mod.__all__) == exported
    for name in exported:
        assert name in evaluation_pkg.__all__
        assert getattr(evaluation_pkg, name) is getattr(pc_mod, name)
    # private item models are not exported
    for private in ("_ParsedEntity", "_ParsedFieldValue", "_ParsedEvidence"):
        assert private not in evaluation_pkg.__all__


def test_import_no_io_no_hash_no_clock():
    code = "\n".join([
        "import sys, os, hashlib, importlib, time",
        "sys.path.insert(0, 'src')",
        "from jsonschema import Draft202012Validator, FormatChecker",
        "import pydantic",
        "import dynamic_ai_products, dynamic_ai_products.universe.models, dynamic_ai_products.universe.io_utils",
        "import dynamic_ai_products.evaluation",
        "sys.modules.pop('dynamic_ai_products.evaluation.prediction_content', None)",
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
        "importlib.import_module('dynamic_ai_products.evaluation.prediction_content')",
        "Path.read_bytes,Path.read_text,Path.mkdir,os.open,hashlib.sha256=orb,ort,omk,oop,osha",
        "time.time,time.monotonic=ot1,ot2",
        "assert reads==[], reads",
        "assert writes==[] and sha==[] and clock==[], (writes,len(sha),len(clock))",
        "print('OK')",
    ])
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr


# --- P1: public artifact bytes/SHA preparation boundary ---------------------
#
# An adjudicator must be able to obtain the exact persisted-artifact SHA-256
# BEFORE any run directory exists, so a resolution-decision set can be pinned to
# one specific parse. The helper and the persister therefore share a single byte
# producer; if they ever diverged, every extraction run would fail its
# decision-set binding check.


def _omitting_content():
    """Content whose defaulted repair tuples were never set.

    This shape is what exposes serialization drift: a single-stage
    ``exclude_unset`` dump omits the defaulted fields, while the persist path
    revalidates first (marking every field set) and therefore includes them.
    Adapter-produced content always sets them, so a real fixture cannot reveal
    the difference — this synthetic shape is required for the test to have teeth.
    """
    doc = base_doc()
    del doc["repair_record_references"]
    del doc["repair_record_hashes"]
    c = ParsedPredictionContent.model_validate(doc)
    assert "repair_record_references" not in c.model_fields_set
    return c


def test_helper_sha_equals_persisted_and_reread_sha(tmp_path):
    for c in (content(), _omitting_content()):
        root = tmp_path / ("full" if c is not None and
                           "repair_record_references" in c.model_fields_set else "omitting")
        (root / "run1").mkdir(parents=True)
        helper_sha = parsed_prediction_content_artifact_sha256(c)
        persisted = persist_parsed_prediction_content(c, eval_root=root, eval_run_id="run1")
        disk = root / "run1" / "snapshots" / "parsed_prediction_content.json"
        assert helper_sha == persisted.sha256 == sha256_bytes(disk.read_bytes())
        assert parsed_prediction_content_artifact_bytes(c) == disk.read_bytes()
        reloaded = load_parsed_prediction_content(
            persisted.artifact_reference, eval_root=root, expected_sha256=helper_sha)
        assert reloaded.sha256 == helper_sha


def test_single_stage_exclude_unset_dump_would_drift():
    # Regression guard for the two-stage rule: the naive shortcut is NOT equal.
    c = _omitting_content()
    naive = canonical_contract_bytes(c.model_dump(mode="json", exclude_unset=True)) + b"\n"
    exact = parsed_prediction_content_artifact_bytes(c)
    assert naive != exact
    assert sha256_bytes(naive) != parsed_prediction_content_artifact_sha256(c)
    # The defaulted tuples are present in the persisted artifact, absent in the naive dump.
    assert b"repair_record_references" in exact
    assert b"repair_record_references" not in naive


def test_artifact_bytes_end_with_exactly_one_terminal_newline():
    for c in (content(), _omitting_content()):
        data = parsed_prediction_content_artifact_bytes(c)
        assert data.endswith(b"\n") and not data.endswith(b"\n\n")


@pytest.mark.parametrize("override", [
    {"repair_record_references": [], "repair_record_hashes": []},
    {"raw_artifact_reference": "parsed_content/other.json"},
])
def test_helper_is_deterministic_and_content_sensitive(override):
    base = parsed_prediction_content_artifact_sha256(content())
    other = parsed_prediction_content_artifact_sha256(content(**override))
    assert parsed_prediction_content_artifact_sha256(content()) == base
    if override.get("raw_artifact_reference"):
        assert other != base
    else:
        assert other == base  # explicit default equals the persisted shape


def test_helper_revalidates_fail_closed():
    bad = content().model_copy(update={"case_id": ""})
    with pytest.raises(ParsedPredictionContentError) as ei:
        parsed_prediction_content_artifact_sha256(bad)
    assert ei.value.reason_code == "model_validation"
    with pytest.raises(TypeError):
        parsed_prediction_content_artifact_bytes(object())


def test_helper_touches_no_filesystem_and_no_clock():
    src = (ROOT / "src" / "dynamic_ai_products" / "evaluation"
           / "prediction_content.py").read_text()
    for forbidden in ("datetime.now", "time.time", "utcnow", "monotonic"):
        assert forbidden not in src
    # One byte producer only: the persist path must not re-derive the rule.
    assert src.count('exclude_unset=True)) + b"\\n"') == 1
