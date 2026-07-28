"""Deterministic Parquet emission (ADR-031).

Rows are sorted by an explicit declared key, columns are fixed by an explicit
pyarrow schema, and writer options are pinned. Bytes are produced in memory,
hashed, and only then handed to the write-once primitive, so the recorded
SHA-256 always covers the exact emitted bytes.

Reproduction bound, stated honestly: the digest pins what was emitted and
detects any drift, but byte-identical *reproduction* holds only under the same
writer library, version, and options. That is why the writer metadata fields
are mandatory rather than optional.
"""

from __future__ import annotations

import io
from typing import Any, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from .errors import IngestionError

__all__ = [
    "PARQUET_COMPRESSION",
    "PARQUET_FORMAT_VERSION",
    "SEC_SOURCE_CANDIDATE_SCHEMA",
    "SOURCE_DOCUMENT_SCHEMA",
    "SOURCE_PASSAGE_SCHEMA",
    "table_bytes",
    "writer_metadata",
]

PARQUET_FORMAT_VERSION = "2.6"
PARQUET_COMPRESSION = "zstd"

# Column order equals the governing schema's property order exactly.
SOURCE_DOCUMENT_SCHEMA = pa.schema(
    [
        ("source_id", pa.string()),
        ("company_id", pa.string()),
        ("source_type", pa.string()),
        ("title", pa.string()),
        ("url", pa.string()),
        ("archive_url", pa.string()),
        ("publication_date", pa.string()),
        ("retrieval_timestamp", pa.string()),
        ("snapshot_timestamp", pa.string()),
        ("content_hash", pa.string()),
        ("mime_type", pa.string()),
        ("official_status", pa.string()),
        ("temporal_validity", pa.string()),
        ("access_status", pa.string()),
        ("schema_version", pa.string()),
    ]
)

SOURCE_PASSAGE_SCHEMA = pa.schema(
    [
        ("passage_id", pa.string()),
        ("source_id", pa.string()),
        ("heading_path", pa.list_(pa.string())),
        ("text", pa.string()),
        ("text_hash", pa.string()),
        ("start_offset", pa.int64()),
        ("end_offset", pa.int64()),
        ("page", pa.int64()),
        ("normalizer_version", pa.string()),
    ]
)

SEC_SOURCE_CANDIDATE_SCHEMA = pa.schema(
    [
        ("candidate_id", pa.string()),
        ("company_id", pa.string()),
        ("source_family", pa.string()),
        ("source_type", pa.string()),
        ("form", pa.string()),
        ("accession", pa.string()),
        ("document_filename", pa.string()),
        ("publication_date", pa.string()),
        ("period_of_report", pa.string()),
        ("observation_cutoff_date", pa.string()),
        ("requested_url", pa.string()),
        ("final_url", pa.string()),
        ("content_sha256", pa.string()),
        ("byte_count", pa.int64()),
        ("retrieval_timestamp", pa.string()),
        ("temporal_validity", pa.string()),
        ("official_status", pa.string()),
        ("coverage_state", pa.string()),
        ("schema_version", pa.string()),
    ]
)

# Declared row-order keys, by artifact.
ROW_ORDER_KEYS: dict[str, tuple[str, ...]] = {
    "sec_source_candidates": (
        "source_family",
        "source_type",
        "accession",
        "document_filename",
    ),
    "normalized_documents": ("source_id",),
    "normalized_passages": ("source_id", "start_offset", "end_offset", "passage_id"),
}


def _sort_key(row: dict[str, Any], keys: Sequence[str]) -> tuple:
    out: list[tuple[int, Any]] = []
    for key in keys:
        value = row.get(key)
        # None sorts first and deterministically, without comparing None to str.
        out.append((0, "") if value is None else (1, value))
    return tuple(out)


def writer_metadata(*, artifact: str, row_count: int, sha256_hex: str) -> dict[str, Any]:
    """Mandatory writer provenance recorded alongside every Parquet artifact."""
    if artifact not in ROW_ORDER_KEYS:
        raise IngestionError(
            f"unknown parquet artifact: {artifact}",
            reason_code="parquet_artifact_unknown",
        )
    return {
        "writer_library": "pyarrow",
        "writer_version": pa.__version__,
        "parquet_format_version": PARQUET_FORMAT_VERSION,
        "compression": PARQUET_COMPRESSION,
        "row_order_key": list(ROW_ORDER_KEYS[artifact]),
        "column_order": list(_schema_for(artifact).names),
        "row_count": row_count,
        "sha256": sha256_hex,
    }


def _schema_for(artifact: str) -> pa.Schema:
    return {
        "sec_source_candidates": SEC_SOURCE_CANDIDATE_SCHEMA,
        "normalized_documents": SOURCE_DOCUMENT_SCHEMA,
        "normalized_passages": SOURCE_PASSAGE_SCHEMA,
    }[artifact]


def table_bytes(artifact: str, rows: Sequence[dict[str, Any]]) -> bytes:
    """Serialize rows to deterministic Parquet bytes.

    Rows are sorted by the declared key before serialization, so input order
    cannot influence the emitted bytes.
    """
    if artifact not in ROW_ORDER_KEYS:
        raise IngestionError(
            f"unknown parquet artifact: {artifact}",
            reason_code="parquet_artifact_unknown",
        )
    schema = _schema_for(artifact)
    keys = ROW_ORDER_KEYS[artifact]

    for row in rows:
        unknown = sorted(set(row) - set(schema.names))
        if unknown:
            raise IngestionError(
                f"{artifact} row carries columns outside the governed schema: {unknown}",
                reason_code="parquet_column_unknown",
            )

    ordered = sorted(rows, key=lambda row: _sort_key(row, keys))
    columns = {name: [row.get(name) for row in ordered] for name in schema.names}
    table = pa.Table.from_pydict(columns, schema=schema)

    sink = io.BytesIO()
    pq.write_table(
        table,
        sink,
        version=PARQUET_FORMAT_VERSION,
        compression=PARQUET_COMPRESSION,
        write_statistics=False,
        use_dictionary=False,
    )
    return sink.getvalue()
