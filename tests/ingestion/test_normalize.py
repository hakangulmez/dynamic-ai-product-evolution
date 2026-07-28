"""Stage 04 normalization: span bounds, raw-byte provenance, ID stability."""

from __future__ import annotations

import sys
from hashlib import sha256
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from dynamic_ai_products.ingestion.errors import IngestionError  # noqa: E402
from dynamic_ai_products.ingestion.normalize import (  # noqa: E402
    NORMALIZER_VERSION,
    TRANSFORM_CHAIN,
    build_passages,
    normalize_span,
    passage_id_for,
)
from ingestion_test_helpers import (  # noqa: E402
    PRIMARY_HTML,
    span_offsets,
)

SOURCE_ID = "CIK0009999999/sec_10k/2025-02-12/abcdef0123456789"


def test_span_bounds_are_respected_exactly() -> None:
    start, end = span_offsets()
    blocks = normalize_span(PRIMARY_HTML, start_offset=start, end_offset=end)
    assert blocks
    assert all(start <= b["start_offset"] < b["end_offset"] <= end for b in blocks)
    # Content outside the span never appears.
    joined = " ".join(b["text"] for b in blocks)
    assert "front matter that is outside the span" not in joined
    assert "tail content outside the span" not in joined


def test_offsets_are_absolute_into_raw_bytes() -> None:
    start, end = span_offsets()
    passages, _ = build_passages(
        PRIMARY_HTML, source_id=SOURCE_ID, start_offset=start, end_offset=end
    )
    for passage in passages:
        fragment = PRIMARY_HTML[passage["start_offset"] : passage["end_offset"]]
        # Re-slicing the RAW document at the recorded offsets reproduces the
        # source of the normalized text.
        assert fragment
        assert b"<" in fragment or passage["text"].encode("utf-8") in fragment


def test_normalizer_version_on_every_passage() -> None:
    start, end = span_offsets()
    passages, ledger = build_passages(
        PRIMARY_HTML, source_id=SOURCE_ID, start_offset=start, end_offset=end
    )
    assert all(p["normalizer_version"] == NORMALIZER_VERSION for p in passages)
    assert ledger["normalizer_version"] == NORMALIZER_VERSION
    assert ledger["transform_chain"] == list(TRANSFORM_CHAIN)


def test_entities_are_decoded_and_whitespace_collapsed() -> None:
    start, end = span_offsets()
    passages, _ = build_passages(
        PRIMARY_HTML, source_id=SOURCE_ID, start_offset=start, end_offset=end
    )
    joined = " ".join(p["text"] for p in passages)
    assert "&nbsp;" not in joined
    assert "  " not in joined


def test_text_hash_covers_normalized_text_not_raw_bytes() -> None:
    start, end = span_offsets()
    passages, _ = build_passages(
        PRIMARY_HTML, source_id=SOURCE_ID, start_offset=start, end_offset=end
    )
    for passage in passages:
        assert passage["text_hash"] == sha256(
            passage["text"].encode("utf-8")
        ).hexdigest()
        raw_slice = PRIMARY_HTML[passage["start_offset"] : passage["end_offset"]]
        # Declared asymmetry: a passage is not a byte-identical raw slice.
        assert passage["text_hash"] != sha256(raw_slice).hexdigest()


def test_passage_ids_are_stable_under_unrelated_region_change() -> None:
    start, end = span_offsets()
    baseline, _ = build_passages(
        PRIMARY_HTML, source_id=SOURCE_ID, start_offset=start, end_offset=end
    )

    # Change a region entirely outside the span; every offset shifts.
    prefix = b"<div>a much longer unrelated preamble inserted before</div>"
    shifted_raw = PRIMARY_HTML.replace(
        b"<div>front matter that is outside the span</div>", prefix
    )
    shifted_start, shifted_end = span_offsets(shifted_raw)
    shifted, _ = build_passages(
        shifted_raw,
        source_id=SOURCE_ID,
        start_offset=shifted_start,
        end_offset=shifted_end,
    )

    assert shifted_start != start, "the fixture must actually shift offsets"
    assert [p["passage_id"] for p in shifted] == [p["passage_id"] for p in baseline]
    assert [p["start_offset"] for p in shifted] != [
        p["start_offset"] for p in baseline
    ]


def test_identical_text_gets_distinct_ids_by_occurrence() -> None:
    first = passage_id_for(SOURCE_ID, "a" * 64, 0)
    second = passage_id_for(SOURCE_ID, "a" * 64, 1)
    assert first != second


def test_ledger_accounts_for_dropped_bytes() -> None:
    start, end = span_offsets()
    _, ledger = build_passages(
        PRIMARY_HTML, source_id=SOURCE_ID, start_offset=start, end_offset=end
    )
    assert ledger["input_byte_count"] == end - start
    assert ledger["dropped_byte_count"] >= 0
    assert (
        ledger["normalized_byte_count"] + ledger["dropped_byte_count"]
        == ledger["input_byte_count"]
    )


def test_zero_passage_span_yields_no_passages() -> None:
    raw = b"<p>   </p>"
    passages, _ = build_passages(
        raw, source_id=SOURCE_ID, start_offset=0, end_offset=len(raw)
    )
    assert passages == []


@pytest.mark.parametrize(
    "start,end",
    [(-1, 10), (0, 10_000), (10, 10), (20, 5)],
)
def test_out_of_bounds_span_fails_closed(start: int, end: int) -> None:
    with pytest.raises(IngestionError) as excinfo:
        normalize_span(PRIMARY_HTML, start_offset=start, end_offset=end)
    assert excinfo.value.reason_code == "normalize_span_invalid"
