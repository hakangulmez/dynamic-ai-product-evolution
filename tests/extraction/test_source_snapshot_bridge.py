"""The ingestion-Parquet to harness-corpora bridge (ADR-033).

This module holds the **single** declared ``extraction -> evaluation`` import
edge, reusing the released persister instead of duplicating a serializer for a
released contract (ADR-027 anti-drift).

**No timestamp is ever generated.** ``retrieval_timestamp``,
``publication_date``, ``snapshot_timestamp``, and ``temporal_validity`` are
copied verbatim, preserving the retrieval-versus-cutoff gap the contamination
tests exist to police.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dynamic_ai_products.evaluation.source_snapshot import (
    SourcePassageSnapshotManifest,
    canonical_contract_bytes,
    load_source_passage_snapshot_manifest,
)
from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.raw_artifacts import sha256_bytes
from dynamic_ai_products.extraction.source_snapshot_bridge import (
    DOCUMENTS_REFERENCE,
    DOCUMENT_FIELDS,
    PASSAGES_REFERENCE,
    PASSAGE_FIELDS,
    PERSISTER_OWNED_REFERENCE,
    SOURCE_SNAPSHOT_MANIFEST_CONTRACT,
    build_source_snapshot,
    read_ingestion_corpus,
)

# The committed Increment B run retrieved long after the FY2024 cutoff. That
# gap is evidence, not noise: it must survive transcoding byte-unchanged.
RETRIEVAL = "2026-07-26T09:14:07Z"
PUBLICATION = "2024-02-14"

DOCUMENT = {
    "source_id": "sec-0000",
    "company_id": "CIK0001404655",
    "source_type": "sec_filing",
    "title": "Annual Report",
    "archive_url": None,
    "publication_date": PUBLICATION,
    "retrieval_timestamp": RETRIEVAL,
    "snapshot_timestamp": None,
    "content_hash": "a" * 64,
    "mime_type": "text/html",
    "official_status": "official",
    "temporal_validity": "valid",
    "access_status": "ok",
    "schema_version": "0.1.0",
}
PASSAGE_TEXT = "The product includes an assistant."
PASSAGE = {
    "passage_id": "sec-0000-p0001",
    "source_id": "sec-0000",
    "heading_path": ["Item 1", "Business"],
    "text": PASSAGE_TEXT,
    "text_hash": sha256(PASSAGE_TEXT.encode("utf-8")).hexdigest(),
    "start_offset": 0,
    "end_offset": 34,
    "page": None,
    "normalizer_version": "sec_html_item_span_v1",
}


def _write_parquet(target: Path, rows: list[dict]) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), target)
    return sha256_bytes(target.read_bytes())


def _published_run(tmp_path: Path, documents=None, passages=None) -> tuple[Path, str, str]:
    run_root = tmp_path / "ing-run"
    documents_sha = _write_parquet(
        run_root / "normalized" / "documents.parquet", documents or [DOCUMENT]
    )
    passages_sha = _write_parquet(
        run_root / "normalized" / "passages.parquet", passages or [PASSAGE]
    )
    return run_root, documents_sha, passages_sha


def _publish(tmp_path: Path, **overrides) -> dict:
    eval_root = tmp_path / "eval"
    eval_root.mkdir(parents=True, exist_ok=True)
    kwargs = {
        "documents": [DOCUMENT],
        "passages": [PASSAGE],
        "snapshot_version": "0.1.0",
        "eval_root": str(eval_root),
        "staging_run_id": ".staging-run",
        "final_run_id": "snap-run",
    }
    kwargs.update(overrides)
    return build_source_snapshot(**kwargs)


# --- reading the published ingestion corpus -----------------------------------


def test_the_field_tuples_come_from_the_released_models():
    assert DOCUMENT_FIELDS[0] == "source_id" and len(DOCUMENT_FIELDS) == 15
    assert PASSAGE_FIELDS[0] == "passage_id" and len(PASSAGE_FIELDS) == 9


def test_a_verified_corpus_is_read_back(tmp_path: Path):
    run_root, documents_sha, passages_sha = _published_run(tmp_path)
    documents, passages = read_ingestion_corpus(
        run_root=run_root, documents_sha256=documents_sha, passages_sha256=passages_sha
    )
    assert documents[0]["source_id"] == "sec-0000"
    assert passages[0]["passage_id"] == "sec-0000-p0001"


@pytest.mark.parametrize("which", ["documents", "passages"])
def test_a_corpus_that_does_not_match_its_binding_is_refused(tmp_path: Path, which):
    run_root, documents_sha, passages_sha = _published_run(tmp_path)
    overrides = {"documents_sha256": documents_sha, "passages_sha256": passages_sha}
    overrides[f"{which}_sha256"] = "0" * 64
    with pytest.raises(ExtractionError) as excinfo:
        read_ingestion_corpus(run_root=run_root, **overrides)
    assert excinfo.value.reason_code == "corpus_binding_unverified"


def test_a_missing_corpus_is_refused(tmp_path: Path):
    with pytest.raises(ExtractionError) as excinfo:
        read_ingestion_corpus(
            run_root=tmp_path / "absent",
            documents_sha256="0" * 64,
            passages_sha256="1" * 64,
        )
    assert excinfo.value.reason_code == "corpus_binding_unverified"


# --- transcoding preserves every temporal field verbatim ----------------------


def test_no_timestamp_is_generated_and_the_retrieval_gap_survives(tmp_path: Path):
    result = _publish(tmp_path)
    documents_path = Path(result["run_root"]) / DOCUMENTS_REFERENCE
    record = json.loads(documents_path.read_text().splitlines()[0])
    assert record["retrieval_timestamp"] == RETRIEVAL
    assert record["publication_date"] == PUBLICATION
    assert record["snapshot_timestamp"] is None
    assert record["temporal_validity"] == "valid"
    assert record["retrieval_timestamp"] > record["publication_date"]


def test_every_released_field_is_reconciled(tmp_path: Path):
    result = _publish(tmp_path)
    root = Path(result["run_root"])
    document = json.loads((root / DOCUMENTS_REFERENCE).read_text().splitlines()[0])
    passage = json.loads((root / PASSAGES_REFERENCE).read_text().splitlines()[0])
    assert set(document) == set(DOCUMENT.keys())
    assert set(document) <= set(DOCUMENT_FIELDS)
    assert set(passage) == set(PASSAGE.keys())
    assert set(passage) <= set(PASSAGE_FIELDS)
    assert passage["heading_path"] == ["Item 1", "Business"]
    # Copied verbatim, never re-derived.
    assert document["content_hash"] == DOCUMENT["content_hash"]
    assert passage["text_hash"] == PASSAGE["text_hash"]


def test_an_absent_optional_column_is_omitted_not_turned_into_a_null(tmp_path: Path):
    """The released records reject explicit null for some omittable keys.

    Selecting with ``row.get`` would materialise a null for every absent
    column and make an ordinary ingestion row unrepresentable.
    """
    assert "url" not in DOCUMENT
    result = _publish(tmp_path)
    document = json.loads(
        (Path(result["run_root"]) / DOCUMENTS_REFERENCE).read_text().splitlines()[0]
    )
    assert "url" not in document  # omitted, not emitted as an explicit null


@pytest.mark.parametrize(
    "field", ["url", "mime_type", "temporal_validity", "access_status", "schema_version"]
)
def test_a_genuine_explicit_null_is_refused_never_laundered_into_absence(
    tmp_path: Path, field
):
    with pytest.raises(Exception) as excinfo:
        _publish(tmp_path, documents=[{**DOCUMENT, field: None}])
    assert "must not be explicit JSON null" in str(excinfo.value)


def test_counts_are_reported_from_the_transcoded_records(tmp_path: Path):
    result = _publish(
        tmp_path,
        documents=[DOCUMENT, {**DOCUMENT, "source_id": "sec-0001"}],
        passages=[PASSAGE, {**PASSAGE, "passage_id": "sec-0000-p0002", "start_offset": 40}],
    )
    assert result["source_document_count"] == 2
    assert result["source_passage_count"] == 2
    assert result["manifest"]["source_document_count"] == 2


def test_corpora_are_deterministically_ordered(tmp_path: Path):
    forward = _publish(
        tmp_path / "a",
        documents=[DOCUMENT, {**DOCUMENT, "source_id": "sec-0001"}],
    )
    reverse = _publish(
        tmp_path / "b",
        documents=[{**DOCUMENT, "source_id": "sec-0001"}, DOCUMENT],
    )
    assert (Path(forward["run_root"]) / DOCUMENTS_REFERENCE).read_bytes() == (
        Path(reverse["run_root"]) / DOCUMENTS_REFERENCE
    ).read_bytes()


# --- the published manifest ---------------------------------------------------


def test_the_manifest_is_loader_compatible(tmp_path: Path):
    """References resolve against the eval root, not the run directory."""
    result = _publish(tmp_path)
    eval_root = Path(result["run_root"]).parent
    loaded = load_source_passage_snapshot_manifest(
        result["artifact_reference"],
        eval_root=eval_root,
        expected_sha256=result["sha256"],
    )
    assert loaded.manifest.snapshot_version == "0.1.0"
    assert loaded.manifest.source_documents_reference == "snap-run/source_documents.jsonl"
    assert loaded.manifest.source_passages_reference == "snap-run/source_passages.jsonl"


def test_the_aggregate_hash_is_the_released_self_excluding_digest(tmp_path: Path):
    """Not a digest of the corpora bytes and not of the persisted file."""
    result = _publish(tmp_path)
    manifest = SourcePassageSnapshotManifest.model_validate(result["manifest"])
    payload = manifest.model_dump(
        exclude_unset=True, exclude={"aggregate_content_hash"}
    )
    assert manifest.aggregate_content_hash == sha256_bytes(
        canonical_contract_bytes(payload)
    )


def test_the_contract_stamp_comes_from_the_closed_pin(tmp_path: Path):
    result = _publish(tmp_path)
    assert result["manifest"]["contract"] == SOURCE_SNAPSHOT_MANIFEST_CONTRACT


def test_the_reported_digest_is_of_the_published_bytes(tmp_path: Path):
    result = _publish(tmp_path)
    published = Path(result["run_root"]) / PERSISTER_OWNED_REFERENCE
    assert published.is_file()
    assert result["sha256"] == sha256_bytes(published.read_bytes())
    assert result["artifact_reference"] == f"snap-run/{PERSISTER_OWNED_REFERENCE}"


def test_publication_is_atomic_and_leaves_no_staging_directory(tmp_path: Path):
    result = _publish(tmp_path)
    eval_root = Path(result["run_root"]).parent
    assert [p.name for p in eval_root.iterdir()] == ["snap-run"]


# --- refusals ------------------------------------------------------------------


@pytest.mark.parametrize(
    "identifier", ["", "  ", "a/b", "../escape", "/abs", "C:x", "a\\b"]
)
def test_an_unsafe_run_identifier_is_refused(tmp_path: Path, identifier):
    with pytest.raises(ExtractionError) as excinfo:
        _publish(tmp_path, final_run_id=identifier)
    assert excinfo.value.reason_code == "run_identifier_unsafe"


def test_staging_and_final_identifiers_must_differ(tmp_path: Path):
    with pytest.raises(ExtractionError) as excinfo:
        _publish(tmp_path, staging_run_id="same", final_run_id="same")
    assert excinfo.value.reason_code == "run_identifier_unsafe"


def test_an_absent_eval_root_is_refused(tmp_path: Path):
    with pytest.raises(ExtractionError) as excinfo:
        build_source_snapshot(
            documents=[DOCUMENT],
            passages=[PASSAGE],
            snapshot_version="0.1.0",
            eval_root=str(tmp_path / "absent"),
            staging_run_id=".staging",
            final_run_id="snap",
        )
    assert excinfo.value.reason_code == "eval_root_invalid"


def test_an_existing_run_root_is_never_overwritten(tmp_path: Path):
    _publish(tmp_path)
    with pytest.raises(ExtractionError) as excinfo:
        _publish(tmp_path, staging_run_id=".staging-second")
    assert excinfo.value.reason_code == "run_root_exists"


def test_an_existing_staging_root_is_refused(tmp_path: Path):
    eval_root = tmp_path / "eval"
    eval_root.mkdir()
    (eval_root / ".staging-run").mkdir()
    with pytest.raises(ExtractionError) as excinfo:
        _publish(tmp_path)
    assert excinfo.value.reason_code == "staging_root_exists"


def test_no_caller_supplied_reference_or_contract_metadata_is_accepted(tmp_path: Path):
    with pytest.raises(ExtractionError) as excinfo:
        _publish(tmp_path, documents_reference="wherever.jsonl")
    assert excinfo.value.reason_code == "contract_metadata_forbidden"

    with pytest.raises(ExtractionError) as excinfo:
        _publish(tmp_path, contract_metadata={"contract_hash": "f" * 64})
    assert excinfo.value.reason_code == "contract_metadata_forbidden"


def test_a_row_that_violates_the_released_record_shape_is_refused(tmp_path: Path):
    with pytest.raises(Exception) as excinfo:
        _publish(tmp_path, documents=[{**DOCUMENT, "official_status": "invented"}])
    assert not isinstance(excinfo.value, ExtractionError)
