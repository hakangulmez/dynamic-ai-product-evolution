"""Slice 12D: source/passage snapshot manifest."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import source_snapshot as ss_mod
from dynamic_ai_products.evaluation.contracts import canonical_contract_bytes, model_contract_hash
from dynamic_ai_products.evaluation.models import EvaluationCase
from dynamic_ai_products.evaluation.source_snapshot import (
    LoadedSourcePassageSnapshotManifest,
    SourceDocumentRecord,
    SourcePassageRecord,
    SourcePassageSnapshotManifest,
    SourceSnapshotError,
    load_source_passage_snapshot_manifest,
    persist_source_passage_snapshot_manifest,
    resolve_case_source_passages,
    source_passage_snapshot_manifest_hash,
)
from dynamic_ai_products.universe.io_utils import sha256_bytes, sha256_text

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness"
MANIFEST_REL = "source_snapshots/source_passage_snapshot_manifest.json"
MODEL_HASH = "c169be58c6df0370e5f51f276a528f452252e9796d19fb5e3a905cd34a3c21a5"


def load():
    return load_source_passage_snapshot_manifest(MANIFEST_REL, eval_root=FX)


def _line(model):
    return canonical_contract_bytes(model.model_dump(mode="json", exclude_unset=True)) + b"\n"


def _doc(source_id, publication_date="2025-06-30", **ov):
    base = dict(
        source_id=source_id, company_id="SYNTH-CO-0001", source_type="official_filing",
        publication_date=publication_date, retrieval_timestamp="2026-01-05T00:00:00+00:00",
        content_hash=sha256_text(source_id), official_status="official",
    )
    base.update(ov)
    return base


def _passage(passage_id, source_id, text):
    return dict(passage_id=passage_id, source_id=source_id, text=text, text_hash=sha256_text(text))


def _write_snapshot(tmp_path, docs, passages, *, doc_bytes=None, passage_bytes=None,
                    doc_sha=None, passage_sha=None, aggregate=None, snapshot_version="0.1.0"):
    """Build a snapshot (corpora + manifest) under tmp_path; returns manifest ref."""
    (tmp_path / "source_snapshots").mkdir(exist_ok=True)
    db = doc_bytes if doc_bytes is not None else b"".join(
        _line(SourceDocumentRecord.model_validate(d)) for d in docs)
    pb = passage_bytes if passage_bytes is not None else b"".join(
        _line(SourcePassageRecord.model_validate(p)) for p in passages)
    (tmp_path / "source_snapshots" / "source_documents.jsonl").write_bytes(db)
    (tmp_path / "source_snapshots" / "source_passages.jsonl").write_bytes(pb)
    base = {
        "contract": {
            "contract_id": "source_passage_snapshot_manifest", "contract_version": "0.1.0",
            "contract_hash": MODEL_HASH,
        },
        "snapshot_version": snapshot_version,
        "source_documents_reference": "source_snapshots/source_documents.jsonl",
        "source_documents_sha256": doc_sha if doc_sha is not None else sha256_bytes(db),
        "source_document_count": len(docs),
        "source_passages_reference": "source_snapshots/source_passages.jsonl",
        "source_passages_sha256": passage_sha if passage_sha is not None else sha256_bytes(pb),
        "source_passage_count": len(passages),
    }
    agg = aggregate if aggregate is not None else sha256_bytes(canonical_contract_bytes(base))
    full = {**base, "aggregate_content_hash": agg}
    (tmp_path / "source_snapshots" / "source_passage_snapshot_manifest.json").write_bytes(
        json.dumps(full).encode("utf-8"))
    return MANIFEST_REL


def _default_docs():
    return [_doc("synth-source-0001"), _doc("synth-source-0002", "2025-12-31")]


def _default_passages():
    return [_passage("synth-passage-0001", "synth-source-0001", "before"),
            _passage("synth-passage-0002", "synth-source-0002", "equal alpha ships")]


# --- Contract identity + happy path ---------------------------------------


def test_contract_identity_and_hash():
    loaded = load()
    assert loaded.manifest.contract.contract_id == "source_passage_snapshot_manifest"
    assert loaded.manifest.contract.contract_version == "0.1.0"
    assert loaded.manifest.contract.contract_hash == MODEL_HASH
    assert model_contract_hash(
        SourcePassageSnapshotManifest, "source_passage_snapshot_manifest", "0.1.0") == MODEL_HASH


def test_load_happy_path():
    loaded = load()
    assert isinstance(loaded, LoadedSourcePassageSnapshotManifest)
    assert len(loaded.source_documents) == 3
    assert len(loaded.source_passages) == 4
    assert {d.source_id for d in loaded.source_documents} == {
        "synth-source-0001", "synth-source-0002", "synth-source-0003"}
    assert loaded.version == "0.1.0"


def test_models_strict_frozen_extra_forbid():
    loaded = load()
    with pytest.raises(PydanticValidationError):
        loaded.manifest.snapshot_version = "x"
    with pytest.raises(PydanticValidationError):
        SourceDocumentRecord.model_validate({**_doc("s"), "unexpected": 1})
    with pytest.raises(PydanticValidationError):
        SourcePassageRecord.model_validate({**_passage("p", "s", "t"), "unexpected": 1})


# --- Aggregate hash + five distinct identities ----------------------------


def test_aggregate_hash_self_excluding_and_manifest_hash():
    loaded = load()
    m = loaded.manifest
    payload = m.model_dump(mode="json", exclude_unset=True, exclude={"aggregate_content_hash"})
    assert m.aggregate_content_hash == sha256_bytes(canonical_contract_bytes(payload))
    assert source_passage_snapshot_manifest_hash(m) == m.aggregate_content_hash


def test_aggregate_hash_mismatch_rejected():
    doc = json.loads((FX / "source_snapshots" / "source_passage_snapshot_manifest.json").read_bytes())
    doc["aggregate_content_hash"] = "a" * 64
    with pytest.raises(PydanticValidationError):
        SourcePassageSnapshotManifest.model_validate(doc)


def test_five_distinct_hash_identities():
    loaded = load()
    m = loaded.manifest
    identities = {
        model_contract_hash(SourcePassageSnapshotManifest, "source_passage_snapshot_manifest", "0.1.0"),
        m.aggregate_content_hash,
        loaded.sha256,
        m.source_documents_sha256,
        m.source_passages_sha256,
    }
    assert len(identities) == 5


# --- Static-schema loading + record invariants ----------------------------


def test_static_schema_hash_mismatch_rejected(tmp_path, monkeypatch):
    _write_snapshot(tmp_path, _default_docs(), _default_passages())
    monkeypatch.setattr(ss_mod, "_SOURCE_DOCUMENT_SCHEMA_SHA256", "0" * 64)
    with pytest.raises(SourceSnapshotError) as ei:
        load_source_passage_snapshot_manifest(MANIFEST_REL, eval_root=tmp_path)
    assert ei.value.reason_code == "schema_hash_mismatch"


def test_bad_publication_date_format_rejected(tmp_path):
    docs = [_doc("synth-source-0001", "2025-13-99")]
    _write_snapshot(tmp_path, docs, [_passage("synth-passage-0001", "synth-source-0001", "x")])
    with pytest.raises(SourceSnapshotError) as ei:
        load_source_passage_snapshot_manifest(MANIFEST_REL, eval_root=tmp_path)
    assert ei.value.reason_code == "source_document_schema_invalid"


def test_document_explicit_null_matches_static_schema():
    # nullable field accepts null; non-null-optional field rejects null.
    SourceDocumentRecord.model_validate({**_doc("s"), "title": None})
    with pytest.raises(PydanticValidationError):
        SourceDocumentRecord.model_validate({**_doc("s"), "url": None})
    with pytest.raises(PydanticValidationError):
        SourceDocumentRecord.model_validate({**_doc("s"), "mime_type": None})
    SourcePassageRecord.model_validate({**_passage("p", "s", "t"), "start_offset": None})
    with pytest.raises(PydanticValidationError):
        SourcePassageRecord.model_validate({**_passage("p", "s", "t"), "normalizer_version": None})


def test_passage_text_hash_binding(tmp_path):
    bad = {"passage_id": "synth-passage-0001", "source_id": "synth-source-0001",
           "text": "before", "text_hash": "0" * 64}
    pb = (json.dumps(bad, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    _write_snapshot(tmp_path, [_doc("synth-source-0001")], [bad],
                    passage_bytes=pb, passage_sha=sha256_bytes(pb))
    with pytest.raises(SourceSnapshotError) as ei:
        load_source_passage_snapshot_manifest(MANIFEST_REL, eval_root=tmp_path)
    assert ei.value.reason_code == "model_validation"
    with pytest.raises(PydanticValidationError):
        SourcePassageRecord.model_validate(bad)


# --- Strict JSONL + integrity ---------------------------------------------


def test_jsonl_blank_line_rejected(tmp_path):
    docs_bytes = _line(SourceDocumentRecord.model_validate(_doc("synth-source-0001"))) + b"\n"
    _write_snapshot(tmp_path, [_doc("synth-source-0001")],
                    [_passage("synth-passage-0001", "synth-source-0001", "x")], doc_bytes=docs_bytes,
                    doc_sha=sha256_bytes(docs_bytes))
    with pytest.raises(SourceSnapshotError) as ei:
        load_source_passage_snapshot_manifest(MANIFEST_REL, eval_root=tmp_path)
    assert ei.value.reason_code == "jsonl_blank_line"


def test_duplicate_key_within_record(tmp_path):
    docs_bytes = b'{"source_id":"a","source_id":"b"}\n'
    _write_snapshot(tmp_path, [_doc("a")],
                    [_passage("p", "a", "x")], doc_bytes=docs_bytes, doc_sha=sha256_bytes(docs_bytes))
    with pytest.raises(SourceSnapshotError) as ei:
        load_source_passage_snapshot_manifest(MANIFEST_REL, eval_root=tmp_path)
    assert ei.value.reason_code == "duplicate_key"


def test_duplicate_source_and_passage_ids(tmp_path):
    _write_snapshot(tmp_path, [_doc("dup"), _doc("dup", "2025-12-31")],
                    [_passage("p", "dup", "x")])
    with pytest.raises(SourceSnapshotError) as ei:
        load_source_passage_snapshot_manifest(MANIFEST_REL, eval_root=tmp_path)
    assert ei.value.reason_code == "duplicate_source_id"
    _write_snapshot(tmp_path, [_doc("s")], [_passage("pdup", "s", "x"), _passage("pdup", "s", "y")])
    with pytest.raises(SourceSnapshotError) as ej:
        load_source_passage_snapshot_manifest(MANIFEST_REL, eval_root=tmp_path)
    assert ej.value.reason_code == "duplicate_passage_id"


def test_passage_source_integrity(tmp_path):
    _write_snapshot(tmp_path, [_doc("s")], [_passage("p", "other-source", "x")])
    with pytest.raises(SourceSnapshotError) as ei:
        load_source_passage_snapshot_manifest(MANIFEST_REL, eval_root=tmp_path)
    assert ei.value.reason_code == "passage_source_unresolved"


def test_record_count_mismatch(tmp_path):
    _write_snapshot(tmp_path, _default_docs(), _default_passages())
    p = tmp_path / "source_snapshots" / "source_passage_snapshot_manifest.json"
    doc = json.loads(p.read_bytes())
    doc["source_document_count"] = 99
    doc["aggregate_content_hash"] = sha256_bytes(canonical_contract_bytes(
        {k: v for k, v in doc.items() if k != "aggregate_content_hash"}))
    p.write_bytes(json.dumps(doc).encode())
    with pytest.raises(SourceSnapshotError) as ei:
        load_source_passage_snapshot_manifest(MANIFEST_REL, eval_root=tmp_path)
    assert ei.value.reason_code == "record_count_mismatch"


def test_corpus_hash_mismatch(tmp_path):
    _write_snapshot(tmp_path, _default_docs(), _default_passages(), doc_sha="a" * 64)
    with pytest.raises(SourceSnapshotError) as ei:
        load_source_passage_snapshot_manifest(MANIFEST_REL, eval_root=tmp_path)
    assert ei.value.reason_code == "corpus_hash_mismatch"


# --- Case resolution ------------------------------------------------------


def _case(case_id, stage, sources, passages):
    return EvaluationCase.model_validate({
        "case_id": case_id, "stage": stage,
        "stage_context": {"observation_window": {"start": "2025-01-01", "end": "2025-12-31"}},
        "input_source_ids": sources, "input_passage_ids": passages,
        "assertions": [{"assertion_id": "A1", "kind": "expected_entity", "semantic_version": "0.1.0",
                        "target_references": ["X"], "scoring_gate_config_references": ["g"]}],
        "failure_tags": [], "notes": "n", "created_by": "c",
        "created_at": "2026-01-01T00:00:00+00:00", "guideline_version": "v"})


def test_resolve_case_happy_and_sorted():
    loaded = load()
    case = _case("C", "capability_extraction", ["synth-source-0003", "synth-source-0002"],
                 ["synth-passage-0004", "synth-passage-0003"])
    resolved = resolve_case_source_passages(loaded, case)
    assert [d.source_id for d in resolved.documents] == ["synth-source-0002", "synth-source-0003"]
    assert [p.passage_id for p in resolved.passages] == ["synth-passage-0003", "synth-passage-0004"]


def test_resolve_case_missing_source_and_passage():
    loaded = load()
    with pytest.raises(SourceSnapshotError) as ei:
        resolve_case_source_passages(loaded, _case("C", "capability_extraction", ["nope"], []))
    assert ei.value.reason_code == "case_input_source_unresolved"
    with pytest.raises(SourceSnapshotError) as ej:
        resolve_case_source_passages(
            loaded, _case("C", "capability_extraction", ["synth-source-0002"], ["nope"]))
    assert ej.value.reason_code == "case_input_passage_unresolved"


def test_resolve_case_passage_source_closure():
    # passage-0001 belongs to source-0001, which the case does not declare.
    loaded = load()
    case = _case("C", "capability_extraction", ["synth-source-0002"], ["synth-passage-0001"])
    with pytest.raises(SourceSnapshotError) as ei:
        resolve_case_source_passages(loaded, case)
    assert ei.value.reason_code == "case_input_passage_unresolved"


def test_resolve_missing_publication_date(tmp_path):
    docs = [_doc("synth-source-0001", None)]
    _write_snapshot(tmp_path, docs, [_passage("synth-passage-0001", "synth-source-0001", "x")])
    loaded = load_source_passage_snapshot_manifest(MANIFEST_REL, eval_root=tmp_path)
    case = _case("C", "capability_extraction", ["synth-source-0001"], [])
    with pytest.raises(SourceSnapshotError) as ei:
        resolve_case_source_passages(loaded, case)
    assert ei.value.reason_code == "resolved_source_missing_publication_date"


# --- Path security --------------------------------------------------------


@pytest.mark.parametrize("bad", ["../outside.json", "/abs.json", "a\\b.json", "a\x00b.json", "./x.json"])
def test_unsafe_references_rejected(tmp_path, bad):
    with pytest.raises(SourceSnapshotError) as ei:
        load_source_passage_snapshot_manifest(bad, eval_root=tmp_path)
    assert ei.value.reason_code in ("unsafe_reference", "invalid_path")


def test_symlink_and_missing_and_nonfile(tmp_path):
    with pytest.raises(SourceSnapshotError) as m:
        load_source_passage_snapshot_manifest("nope.json", eval_root=tmp_path)
    assert m.value.reason_code == "artifact_missing"
    (tmp_path / "adir").mkdir()
    with pytest.raises(SourceSnapshotError) as d:
        load_source_passage_snapshot_manifest("adir", eval_root=tmp_path)
    assert d.value.reason_code == "artifact_not_a_file"
    real = tmp_path / "r.json"
    real.write_text("{}")
    (tmp_path / "link.json").symlink_to(real)
    with pytest.raises(SourceSnapshotError) as s:
        load_source_passage_snapshot_manifest("link.json", eval_root=tmp_path)
    assert s.value.reason_code == "artifact_symlink"


def test_eval_root_symlink_rejected(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(SourceSnapshotError) as ei:
        load_source_passage_snapshot_manifest(MANIFEST_REL, eval_root=link)
    assert ei.value.reason_code == "eval_root_symlink"


def test_expected_sha256_gate(tmp_path):
    _write_snapshot(tmp_path, _default_docs(), _default_passages())
    raw = (tmp_path / "source_snapshots" / "source_passage_snapshot_manifest.json").read_bytes()
    good = sha256_bytes(raw)
    load_source_passage_snapshot_manifest(MANIFEST_REL, eval_root=tmp_path, expected_sha256=good)
    with pytest.raises(SourceSnapshotError) as ei:
        load_source_passage_snapshot_manifest(MANIFEST_REL, eval_root=tmp_path, expected_sha256="a" * 64)
    assert ei.value.reason_code == "expected_hash_mismatch"


# --- Persistence ----------------------------------------------------------


def test_persist_write_once_and_readback(tmp_path):
    manifest = load().manifest
    (tmp_path / "run1").mkdir()
    persisted = persist_source_passage_snapshot_manifest(manifest, eval_root=tmp_path, eval_run_id="run1")
    dest = tmp_path / "run1" / "snapshots" / "source_passage_snapshot_manifest.json"
    data = dest.read_bytes()
    assert data.endswith(b"\n") and not data.endswith(b"\n\n")
    assert persisted.sha256 == sha256_bytes(data)
    with pytest.raises(SourceSnapshotError) as ei:
        persist_source_passage_snapshot_manifest(manifest, eval_root=tmp_path, eval_run_id="run1")
    assert ei.value.reason_code == "snapshot_exists"


def test_persist_requires_run_dir(tmp_path):
    with pytest.raises(SourceSnapshotError) as ei:
        persist_source_passage_snapshot_manifest(load().manifest, eval_root=tmp_path, eval_run_id="missing")
    assert ei.value.reason_code == "run_directory_missing"


def test_sanitized_errors_hide_paths_and_content(tmp_path):
    (tmp_path / "j.json").write_bytes(b'{"SECRET_TOKEN": not json')
    with pytest.raises(SourceSnapshotError) as ei:
        load_source_passage_snapshot_manifest("j.json", eval_root=tmp_path)
    msg = str(ei.value)
    assert str(tmp_path) not in msg and "SECRET_TOKEN" not in msg


# --- Surface + import purity ----------------------------------------------


def test_module_surface():
    exported = {
        "LoadedSourcePassageSnapshotManifest", "SourceDocumentRecord", "SourcePassageRecord",
        "SourcePassageSnapshotManifest", "SourceSnapshotError",
        "load_source_passage_snapshot_manifest", "persist_source_passage_snapshot_manifest",
        "resolve_case_source_passages", "source_passage_snapshot_manifest_hash"}
    assert set(ss_mod.__all__) == exported
    for name in exported:
        assert name in evaluation_pkg.__all__
        assert getattr(evaluation_pkg, name) is getattr(ss_mod, name)


def test_import_no_io_no_hash_no_clock():
    code = "\n".join([
        "import sys, os, hashlib, importlib, time",
        "sys.path.insert(0, 'src')",
        "from jsonschema import Draft202012Validator, FormatChecker",
        "import pydantic",
        "import dynamic_ai_products, dynamic_ai_products.universe.models, dynamic_ai_products.universe.io_utils",
        "import dynamic_ai_products.evaluation",
        "sys.modules.pop('dynamic_ai_products.evaluation.source_snapshot', None)",
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
        "importlib.import_module('dynamic_ai_products.evaluation.source_snapshot')",
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
