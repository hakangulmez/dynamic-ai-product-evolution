"""Deterministic Parquet emission: row order, columns, writer metadata."""

from __future__ import annotations

import random
from hashlib import sha256

import pytest

from dynamic_ai_products.ingestion.errors import IngestionError
from dynamic_ai_products.ingestion.parquet_io import (
    PARQUET_COMPRESSION,
    PARQUET_FORMAT_VERSION,
    ROW_ORDER_KEYS,
    SOURCE_PASSAGE_SCHEMA,
    table_bytes,
    writer_metadata,
)


def _passage(index: int) -> dict:
    text = f"passage {index}"
    return {
        "passage_id": f"{index:032d}",
        "source_id": "src-a" if index % 2 else "src-b",
        "heading_path": [],
        "text": text,
        "text_hash": sha256(text.encode()).hexdigest(),
        "start_offset": 1000 - index,
        "end_offset": 1100 - index,
        "page": None,
        "normalizer_version": "sec_html_item_span_v1",
    }


ROWS = [_passage(i) for i in range(12)]


def test_shuffled_input_produces_identical_bytes() -> None:
    baseline = table_bytes("normalized_passages", ROWS)
    for seed in (1, 2, 3):
        shuffled = list(ROWS)
        random.Random(seed).shuffle(shuffled)
        assert table_bytes("normalized_passages", shuffled) == baseline


def test_repeated_serialization_is_byte_identical() -> None:
    assert table_bytes("normalized_passages", ROWS) == table_bytes(
        "normalized_passages", ROWS
    )


def test_row_order_follows_the_declared_key() -> None:
    import io

    import pyarrow.parquet as pq

    data = table_bytes("normalized_passages", ROWS)
    table = pq.read_table(io.BytesIO(data))
    observed = list(
        zip(
            table.column("source_id").to_pylist(),
            table.column("start_offset").to_pylist(),
            table.column("end_offset").to_pylist(),
            table.column("passage_id").to_pylist(),
        )
    )
    assert observed == sorted(observed)
    assert ROW_ORDER_KEYS["normalized_passages"] == (
        "source_id",
        "start_offset",
        "end_offset",
        "passage_id",
    )


def test_column_set_and_order_match_the_governed_schema() -> None:
    import io

    import pyarrow.parquet as pq

    table = pq.read_table(io.BytesIO(table_bytes("normalized_passages", ROWS)))
    assert table.schema.names == SOURCE_PASSAGE_SCHEMA.names
    # Column order equals the source_passage schema property order exactly.
    assert SOURCE_PASSAGE_SCHEMA.names == [
        "passage_id",
        "source_id",
        "heading_path",
        "text",
        "text_hash",
        "start_offset",
        "end_offset",
        "page",
        "normalizer_version",
    ]


def test_writer_metadata_is_fully_populated() -> None:
    data = table_bytes("normalized_passages", ROWS)
    digest = sha256(data).hexdigest()
    meta = writer_metadata(
        artifact="normalized_passages", row_count=len(ROWS), sha256_hex=digest
    )
    for field in (
        "writer_library",
        "writer_version",
        "parquet_format_version",
        "compression",
        "row_order_key",
        "column_order",
        "row_count",
        "sha256",
    ):
        assert meta[field] not in (None, "", [])
    assert meta["parquet_format_version"] == PARQUET_FORMAT_VERSION
    assert meta["compression"] == PARQUET_COMPRESSION
    assert meta["row_count"] == len(ROWS)


def test_recorded_hash_covers_the_exact_emitted_bytes() -> None:
    data = table_bytes("normalized_passages", ROWS)
    meta = writer_metadata(
        artifact="normalized_passages",
        row_count=len(ROWS),
        sha256_hex=sha256(data).hexdigest(),
    )
    assert meta["sha256"] == sha256(data).hexdigest()


def test_unknown_column_is_refused() -> None:
    rows = [dict(ROWS[0], smuggled="value")]
    with pytest.raises(IngestionError) as excinfo:
        table_bytes("normalized_passages", rows)
    assert excinfo.value.reason_code == "parquet_column_unknown"


def test_unknown_artifact_is_refused() -> None:
    with pytest.raises(IngestionError) as excinfo:
        table_bytes("not_an_artifact", [])
    assert excinfo.value.reason_code == "parquet_artifact_unknown"
