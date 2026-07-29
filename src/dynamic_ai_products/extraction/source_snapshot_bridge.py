"""Ingestion Parquet -> harness-loadable source-passage corpora (ADR-033).

The evaluation runner requires ``source_passage_snapshot_manifest@0.1.0`` with
JSONL document and passage corpora; the ingestion Parquet files are not that
role. This bridge transcodes them.

It holds the **single declared** ``extraction -> evaluation.source_snapshot``
import edge, reusing the released persister rather than duplicating a
serializer for a released contract (ADR-027 anti-drift).

**No timestamp is ever generated.** ``retrieval_timestamp``,
``publication_date``, ``snapshot_timestamp``, and ``temporal_validity`` are
copied verbatim from the ingestion rows, preserving the retrieval-versus-cutoff
gap the contamination tests exist to police.
"""

from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
from typing import Any

import pyarrow.parquet as pq

from ..evaluation.source_snapshot import (
    canonical_contract_bytes,
    SourceDocumentRecord,
    SourcePassageRecord,
    SourcePassageSnapshotManifest,
    persist_source_passage_snapshot_manifest,
    source_passage_snapshot_manifest_hash,
)
from .errors import ExtractionError
from .raw_artifacts import canonical_jsonl_bytes, require_pin, sha256_bytes, write_artifact

__all__ = [
    "DOCUMENTS_REFERENCE",
    "DOCUMENT_FIELDS",
    "PASSAGES_REFERENCE",
    "PASSAGE_FIELDS",
    "PERSISTER_OWNED_REFERENCE",
    "SOURCE_SNAPSHOT_MANIFEST_CONTRACT",
    "build_source_snapshot",
    "read_ingestion_corpus",
]

DOCUMENT_FIELDS: tuple[str, ...] = tuple(SourceDocumentRecord.model_fields)
PASSAGE_FIELDS: tuple[str, ...] = tuple(SourcePassageRecord.model_fields)

# Closed static pin for the released contract identity. The single allowed
# evaluation edge does not expose a contract hash, and importing
# evaluation.contracts would be a second edge, so the pin is held here and a
# drift test re-derives it from the released model.
SOURCE_SNAPSHOT_MANIFEST_CONTRACT: dict[str, str] = {
    "contract_id": "source_passage_snapshot_manifest",
    "contract_version": "0.1.0",
    "contract_hash": "c169be58c6df0370e5f51f276a528f452252e9796d19fb5e3a905cd34a3c21a5",
}


def read_ingestion_corpus(
    *,
    run_root: str | Path,
    documents_sha256: str,
    passages_sha256: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read and hash-verify the published ingestion Parquet corpora."""
    root = Path(run_root)
    out: list[list[dict[str, Any]]] = []
    for relative, expected in (
        ("normalized/documents.parquet", documents_sha256),
        ("normalized/passages.parquet", passages_sha256),
    ):
        target = root / relative
        try:
            raw = target.read_bytes()
        except OSError as exc:
            raise ExtractionError(
                f"ingestion corpus is unreadable: {relative}",
                reason_code="corpus_binding_unverified",
            ) from exc
        observed = sha256_bytes(raw)
        if observed != expected:
            raise ExtractionError(
                f"ingestion corpus does not match its published binding: {relative}",
                reason_code="corpus_binding_unverified",
                detail=f"expected {expected}, observed {observed}",
            )
        out.append(pq.read_table(target).to_pylist())
    return out[0], out[1]


DOCUMENTS_REFERENCE = "source_documents.jsonl"
PASSAGES_REFERENCE = "source_passages.jsonl"
PERSISTER_OWNED_REFERENCE = "snapshots/source_passage_snapshot_manifest.json"


def _safe_identifier(value: Any, what: str) -> str:
    """A run identifier must be a single safe relative path segment."""
    if not isinstance(value, str) or not value.strip():
        raise ExtractionError(
            f"{what} must be a non-blank string", reason_code="run_identifier_unsafe"
        )
    if (
        value.startswith("/")
        or "\\" in value
        or "/" in value
        or PureWindowsPath(value).drive
        or ".." in Path(value).parts
        or Path(value).is_absolute()
    ):
        raise ExtractionError(
            f"{what} must be a single safe relative segment: {value!r}",
            reason_code="run_identifier_unsafe",
        )
    return value


def build_source_snapshot(
    *,
    documents: list[dict[str, Any]],
    passages: list[dict[str, Any]],
    snapshot_version: str,
    eval_root: str | Path,
    staging_run_id: str,
    final_run_id: str,
    **forbidden: Any,
) -> dict[str, Any]:
    """Transcode to JSONL corpora and publish atomically.

    Corpus filenames are fixed canonical constants: no caller-controlled
    reference parameter exists. Every loader-relevant field is copied verbatim;
    nothing is synthesised and no timestamp is generated.
    """
    if forbidden:
        raise ExtractionError(
            f"unsupported inputs: {sorted(forbidden)}; corpus references are fixed "
            "canonical filenames and contract metadata comes from the closed pin",
            reason_code="contract_metadata_forbidden",
        )
    staging_id = _safe_identifier(staging_run_id, "staging_run_id")
    final_id = _safe_identifier(final_run_id, "final_run_id")
    if staging_id == final_id:
        raise ExtractionError(
            "staging and final run identifiers must differ",
            reason_code="run_identifier_unsafe",
        )
    root = Path(eval_root)
    if root.is_symlink() or not root.is_dir():
        raise ExtractionError(
            f"eval_root must be an existing non-symlink directory: {root}",
            reason_code="eval_root_invalid",
        )
    staging_dir = root / staging_id
    final_dir = root / final_id
    for directory, code in ((staging_dir, "staging_root_exists"), (final_dir, "run_root_exists")):
        if directory.is_symlink() or directory.exists():
            raise ExtractionError(
                f"refusing to publish over an existing path: {directory}",
                reason_code=code,
            )

    # Absence and explicit null are DIFFERENT to the released records: several
    # optional properties are omittable but reject an explicit null. Selecting
    # with row.get() would materialise a null for every absent column and make
    # every ordinary ingestion row unrepresentable; rewriting a null into
    # absence would launder it. Copy only the keys the row actually carries and
    # let the released model refuse a genuine null.
    # ``exclude_unset`` mirrors the row's own presence exactly, and ``mode=json``
    # emits JSON-native types. A plain model_dump() would materialise a null for
    # every unset optional, which the released static schemas reject, making the
    # transcoded corpus unloadable by the very harness this bridge feeds.
    doc_records = []
    for row in documents:
        payload = {field: row[field] for field in DOCUMENT_FIELDS if field in row}
        doc_records.append(
            SourceDocumentRecord.model_validate(payload).model_dump(
                mode="json", exclude_unset=True
            )
        )
    passage_records = []
    for row in passages:
        payload = {field: row[field] for field in PASSAGE_FIELDS if field in row}
        heading = payload.get("heading_path")
        if isinstance(heading, (list, tuple)):
            payload["heading_path"] = tuple(heading)
        passage_records.append(
            SourcePassageRecord.model_validate(payload).model_dump(
                mode="json", exclude_unset=True
            )
        )

    doc_records.sort(key=lambda r: str(r["source_id"]))
    passage_records.sort(
        key=lambda r: (
            str(r["source_id"]),
            int(r.get("start_offset") or 0),
            int(r.get("end_offset") or 0),
            str(r["passage_id"]),
        )
    )

    documents_bytes = canonical_jsonl_bytes(doc_records)
    passages_bytes = canonical_jsonl_bytes(passage_records)

    # Staging is created exclusively; the persister requires its run directory
    # to pre-exist, and every corpus byte goes through the write-once primitive.
    try:
        staging_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise ExtractionError(
            f"staging root already exists: {staging_dir}",
            reason_code="staging_root_exists",
        ) from exc
    documents_sha = write_artifact(staging_dir, DOCUMENTS_REFERENCE, documents_bytes)
    passages_sha = write_artifact(staging_dir, PASSAGES_REFERENCE, passages_bytes)

    # The persister owns this path exclusively; the bridge never creates it.
    if (staging_dir / PERSISTER_OWNED_REFERENCE).exists():
        raise ExtractionError(
            "the persister-owned manifest path must not pre-exist",
            reason_code="publication_failed",
        )

    # aggregate_content_hash is the released model's SELF-EXCLUDING canonical
    # hash of the manifest document - not a digest of the corpora bytes and not
    # of the persisted file. Build the base payload without the field, hash it
    # with the released serializer reached through the one permitted edge, then
    # append and validate. No local serializer, no newline-terminated bytes, no
    # private helper, no model_construct.
    base_payload = {
        "contract": require_pin(
            SOURCE_SNAPSHOT_MANIFEST_CONTRACT,
            contract_id="source_passage_snapshot_manifest",
            contract_version="0.1.0",
        ),
        "snapshot_version": snapshot_version,
        "source_documents_reference": f"{final_id}/{DOCUMENTS_REFERENCE}",
        "source_documents_sha256": documents_sha,
        "source_document_count": len(doc_records),
        "source_passages_reference": f"{final_id}/{PASSAGES_REFERENCE}",
        "source_passages_sha256": passages_sha,
        "source_passage_count": len(passage_records),
    }
    aggregate = sha256_bytes(canonical_contract_bytes(base_payload))
    manifest = SourcePassageSnapshotManifest.model_validate(
        {**base_payload, "aggregate_content_hash": aggregate}
    )
    # The persister owns and writes its artifact inside staging. Its returned
    # artifact_reference is staging-qualified and the rename below invalidates
    # it, so it is deliberately not bound, retained, or reported.
    persist_source_passage_snapshot_manifest(
        manifest, eval_root=eval_root, eval_run_id=staging_id
    )

    # Atomic publication: staging becomes the final run root in one rename.
    try:
        os.rename(staging_dir, final_dir)
        descriptor = os.open(final_dir.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ExtractionError(
            f"failed to publish the source-snapshot run root: {final_dir}",
            reason_code="publication_failed",
            detail="staging is preserved for inspection and never auto-removed",
        ) from exc

    # Digest the artifact as published, not as staged.
    published_manifest = final_dir / PERSISTER_OWNED_REFERENCE
    try:
        published_sha = sha256_bytes(published_manifest.read_bytes())
    except OSError as exc:
        raise ExtractionError(
            f"published manifest is unreadable: {published_manifest}",
            reason_code="publication_failed",
        ) from exc

    return {
        "manifest": manifest.model_dump(),
        "manifest_hash": source_passage_snapshot_manifest_hash(manifest),
        "artifact_reference": f"{final_id}/{PERSISTER_OWNED_REFERENCE}",
        "sha256": published_sha,
        "run_root": str(final_dir),
        "documents_reference": f"{final_id}/{DOCUMENTS_REFERENCE}",
        "passages_reference": f"{final_id}/{PASSAGES_REFERENCE}",
        "source_document_count": len(doc_records),
        "source_passage_count": len(passage_records),
    }
