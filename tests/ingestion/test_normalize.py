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


# --- ADR-066: section grouping over the pinned real document ----------------
#
# These read the raw filing this project actually ingested rather than a
# synthetic fixture. The whole point of the increment was that a synthetic
# document could not have shown what the real one does: the plan assumed
# ``<h1>``-``<h6>`` headings, and the real filing has none.

REAL_HTML = (
    Path(__file__).resolve().parents[2]
    / "data/raw/sec/CIK0001404655/0000950170-25-018873/hubs-20241231.htm"
)
REAL_SNAPSHOT = (
    Path(__file__).resolve().parents[2]
    / "data/runs/srcsnap-hubspot-fy2024-sec-v1/source_passages.jsonl"
)
REAL_SOURCE_ID = "CIK0001404655/sec_10k/2025-02-12/36257e638feb2059"
REAL_CONTENT_SHA = "36257e638feb2059e3bbc58461938d6ffc11dd280e12d7af0f06c5394bf40b12"

ITEM_1_SECTION_HEADINGS = (
    "Overview",
    "The HubSpot Approach",
    "Our Competitive Strengths",
    "Our Growth Strategy",
    "Our Customer Platform",
    "Our Services",
    "Our Customers",
    "Our Technology",
    "Marketing and Sales",
    "Governmental Regulations",
    "Human Capital Management",
    "Competition",
    "Intellectual Property",
    "Financial Information About Segments",
    "Available Information",
)

requires_raw = pytest.mark.skipif(
    not REAL_HTML.exists(),
    reason="the pinned raw filing is not present in this checkout",
)


def _real_span() -> tuple[bytes, int, int, list[dict]]:
    import json

    raw = REAL_HTML.read_bytes()
    committed = [
        json.loads(line)
        for line in REAL_SNAPSHOT.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    lo = min(p["start_offset"] for p in committed)
    hi = max(p["end_offset"] for p in committed)
    return raw, lo, hi, committed


@requires_raw
def test_the_pinned_raw_document_is_the_one_the_snapshot_names() -> None:
    """Every assertion below is about this document and no other."""
    assert sha256(REAL_HTML.read_bytes()).hexdigest() == REAL_CONTENT_SHA


@requires_raw
def test_the_document_has_no_heading_tags_at_all() -> None:
    """The measurement that discarded the original design.

    If a future filing does carry ``<hN>`` tags this fails, which is the right
    outcome: the bold-span rule was adopted *because* this one does not, and
    that reasoning should be re-examined rather than inherited.
    """
    import re

    assert re.search(rb"(?i)<h[1-6]\b", REAL_HTML.read_bytes()) is None


@requires_raw
def test_v1_still_produces_the_committed_snapshot_byte_for_byte() -> None:
    """The regression that matters most: Snapshot A's corpus cannot move.

    Not a count check -- every field of every one of the 124 passages, compared
    against the committed file.
    """
    raw, lo, hi, committed = _real_span()
    passages, ledger = build_passages(
        raw, source_id=REAL_SOURCE_ID, start_offset=lo, end_offset=hi
    )
    assert passages == committed
    assert len(passages) == 124
    assert ledger["normalizer_version"] == "sec_html_item_span_v1"


@requires_raw
def test_v2_groups_the_span_into_the_fifteen_sections_plus_the_item_title() -> None:
    from dynamic_ai_products.ingestion.normalize import build_passages_v2

    raw, lo, hi, _ = _real_span()
    passages, ledger = build_passages_v2(
        raw, source_id=REAL_SOURCE_ID, start_offset=lo, end_offset=hi
    )
    assert ledger["normalizer_version"] == "sec_html_item_span_v2"
    assert len(passages) == 16
    # The item title is not a heading under the rule and is not folded into a
    # section it does not belong to: it is the record before the first heading.
    assert passages[0]["text"] == "> ITEM I. BUSINESS"
    for passage, heading in zip(passages[1:], ITEM_1_SECTION_HEADINGS):
        assert passage["text"].startswith(heading), heading
    assert len(passages) - 1 == len(ITEM_1_SECTION_HEADINGS)


@requires_raw
def test_v2_finds_exactly_the_fifteen_headings_and_no_others() -> None:
    """Equality, not presence: a paragraph merely containing bold text is not a
    heading, and this asserts there are none of those either."""
    from dynamic_ai_products.ingestion.normalize import is_heading_block, normalize_span

    raw, lo, hi, _ = _real_span()
    blocks = normalize_span(raw, start_offset=lo, end_offset=hi)
    headings = [
        block["text"]
        for block in blocks
        if is_heading_block(raw[block["start_offset"] : block["end_offset"]])
    ]
    assert tuple(headings) == ITEM_1_SECTION_HEADINGS


@requires_raw
@pytest.mark.parametrize("page_number", ["8", "9", "12", "14"])
def test_a_page_number_is_now_interior_to_a_section(page_number: str) -> None:
    """The defect this increment exists to remove.

    Under v1 each of these was its own passage, sitting between the two halves
    of a sentence and splitting it. Interior means the sentence is whole again:
    the number is inside one passage's text and is neither its start nor its end.
    """
    from dynamic_ai_products.ingestion.normalize import build_passages_v2

    raw, lo, hi, committed = _real_span()

    standalone = [p for p in committed if p["text"].strip() == page_number]
    assert standalone, f"v1 did not emit {page_number!r} as its own passage"

    passages, _ = build_passages_v2(
        raw, source_id=REAL_SOURCE_ID, start_offset=lo, end_offset=hi
    )
    holders = [p for p in passages if f" {page_number} " in p["text"]]
    assert len(holders) == 1, page_number
    holder = holders[0]
    assert holder["text"].strip() != page_number
    assert not holder["text"].startswith(page_number)
    assert not holder["text"].endswith(page_number)


@requires_raw
def test_v2_drops_no_text_and_adds_only_the_joins() -> None:
    """Grouping is concatenation, not re-normalization.

    Every v1 passage's text appears verbatim inside exactly one v2 section, and
    the only characters v2 adds are the single spaces joining them.
    """
    from dynamic_ai_products.ingestion.normalize import build_passages_v2

    raw, lo, hi, committed = _real_span()
    passages, _ = build_passages_v2(
        raw, source_id=REAL_SOURCE_ID, start_offset=lo, end_offset=hi
    )
    joined = " ".join(p["text"] for p in passages)
    for block in committed:
        assert block["text"] in joined
    assert sum(len(p["text"]) for p in passages) == (
        sum(len(b["text"]) for b in committed) + len(committed) - len(passages)
    )


def test_every_normalizer_version_is_declared() -> None:
    from dynamic_ai_products.ingestion.normalize import (
        KNOWN_NORMALIZER_VERSIONS,
        NORMALIZER_VERSION_V2,
        NORMALIZER_VERSION_V3,
    )

    assert KNOWN_NORMALIZER_VERSIONS == (
        "sec_html_item_span_v1",
        "sec_html_item_span_v2",
        "sec_html_item_span_v3",
    )
    assert NORMALIZER_VERSION == "sec_html_item_span_v1"
    assert NORMALIZER_VERSION_V2 == "sec_html_item_span_v2"
    assert NORMALIZER_VERSION_V3 == "sec_html_item_span_v3"


def test_a_paragraph_containing_bold_text_is_not_a_heading() -> None:
    """Presence would match this; equality does not."""
    from dynamic_ai_products.ingestion.normalize import is_heading_block

    assert not is_heading_block(
        b'<p>We offer <span style="font-weight:bold;">Sales Hub</span> to teams.</p>'
    )
    assert is_heading_block(
        b'<p><span style="font-weight:bold;">Our Services</span></p>'
    )


def test_a_bold_block_that_is_not_a_paragraph_is_not_a_heading() -> None:
    """The rule was verified on paragraphs and declines to generalize."""
    from dynamic_ai_products.ingestion.normalize import is_heading_block

    assert not is_heading_block(
        b'<div><span style="font-weight:bold;">Our Services</span></div>'
    )


# --- ADR-072: the page-number block is dropped, not concatenated -------------

PAGE_NUMBERS = ("7", "8", "9", "10", "11", "12", "13", "14", "15")


def _v3():
    from dynamic_ai_products.ingestion.normalize import build_passages_v3

    raw, lo, hi, committed = _real_span()
    passages, ledger = build_passages_v3(
        raw, source_id=REAL_SOURCE_ID, start_offset=lo, end_offset=hi
    )
    return raw, lo, hi, committed, passages, ledger


def _v2():
    from dynamic_ai_products.ingestion.normalize import build_passages_v2

    raw, lo, hi, _ = _real_span()
    return build_passages_v2(raw, source_id=REAL_SOURCE_ID, start_offset=lo, end_offset=hi)


@requires_raw
def test_v1_and_v2_are_untouched_by_the_successor() -> None:
    """Successor, not edit: neither released corpus may move.

    v1 is asserted field-for-field against its committed file elsewhere; this
    adds the same guarantee for v2, which produced Snapshot B, the 69 accepted
    capability observations and every task run that cites them.
    """
    import json

    v2_committed = [
        json.loads(line)
        for line in (
            Path(__file__).resolve().parents[2]
            / "data/runs/srcsnap-hubspot-fy2024-sec-v2/source_passages.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    passages, ledger = _v2()
    assert passages == v2_committed
    assert len(passages) == 16
    assert ledger["normalizer_version"] == "sec_html_item_span_v2"
    assert "dropped_blocks" not in ledger


@requires_raw
def test_v3_keeps_the_sixteen_sections_and_their_spans() -> None:
    """Design decision (a): a dropped block's bytes stay inside the span.

    Every v3 offset equals v2's, so a diff between the corpora is exactly the
    set of sections whose *text* changed -- including "Our Customers", whose
    trailing block is page 10 and is the only case where this is a choice.
    """
    _, _, _, _, v3, _ = _v3()
    v2, _ = _v2()
    assert len(v3) == 16
    assert [(p["start_offset"], p["end_offset"]) for p in v3] == [
        (p["start_offset"], p["end_offset"]) for p in v2
    ]
    our_customers = next(p for p in v3 if p["text"].startswith("Our Customers"))
    assert not our_customers["text"].rstrip().endswith("10")


@requires_raw
def test_v3_changes_eight_sections_and_leaves_eight_identical() -> None:
    _, _, _, _, v3, _ = _v3()
    v2, _ = _v2()
    changed = [i for i, (a, b) in enumerate(zip(v2, v3)) if a["text"] != b["text"]]
    same = [i for i, (a, b) in enumerate(zip(v2, v3)) if a["text"] == b["text"]]
    assert len(changed) == 8, changed
    assert len(same) == 8, same
    for i in changed:
        assert v3[i]["text_hash"] != v2[i]["text_hash"]
        assert v3[i]["passage_id"] != v2[i]["passage_id"]
    for i in same:
        assert v3[i]["text_hash"] == v2[i]["text_hash"]
        # Same text, same source_id, same occurrence -> the id is content
        # addressed, so it must also be the same.
        assert v3[i]["passage_id"] == v2[i]["passage_id"]


@requires_raw
def test_the_sales_hub_section_no_longer_carries_a_page_number() -> None:
    """The contamination this increment exists to remove.

    "…Features include: email 9 templates and tracking…" reached eleven accepted
    capability observations and ten accepted task observations. The fix is not a
    rewrite of that sentence: the whole block "9" is gone, so the words on
    either side simply meet.
    """
    _, _, _, _, v3, _ = _v3()
    v2, _ = _v2()
    dirty = "Features include: email 9 templates and tracking"
    clean = "Features include: email templates and tracking"
    assert any(dirty in p["text"] for p in v2)
    assert not any(dirty in p["text"] for p in v3)
    assert sum(clean in p["text"] for p in v3) == 1


@requires_raw
def test_the_ledger_enumerates_exactly_the_nine_dropped_blocks() -> None:
    """The auditable half of the widened invariant.

    ADR-066 could promise "concatenation only". This cannot, so the removal is
    named instead: nine records, each carrying the block's offsets and its exact
    text. A removal that is counted is not a silent repair.
    """
    raw, _, _, _, _, ledger = _v3()
    dropped = ledger["dropped_blocks"]
    assert len(dropped) == 9
    assert tuple(d["text"] for d in dropped) == PAGE_NUMBERS
    for entry in dropped:
        assert entry["start_offset"] < entry["end_offset"]
        fragment = raw[entry["start_offset"] : entry["end_offset"]]
        assert entry["text"] in fragment.decode("utf-8", "replace")
    # Monotonic in the document, as printed page numbers are.
    offsets = [d["start_offset"] for d in dropped]
    assert offsets == sorted(offsets)


@requires_raw
def test_v3_drops_only_whole_blocks_and_rewrites_nothing() -> None:
    """The widened invariant, stated as a check.

    Every v1 block's text either appears verbatim inside a v3 section or is
    listed in ``dropped_blocks``. Nothing is edited inside a surviving block,
    and the only characters added are the joins.
    """
    _, _, _, committed, v3, ledger = _v3()
    joined = " ".join(p["text"] for p in v3)
    # Matched by offset, not by text: a block is dropped because of where it is,
    # and two blocks could in principle share a string.
    dropped_spans = {
        (d["start_offset"], d["end_offset"]) for d in ledger["dropped_blocks"]
    }
    survivors = [
        b for b in committed
        if (b["start_offset"], b["end_offset"]) not in dropped_spans
    ]
    assert len(survivors) == len(committed) - 9
    for block in survivors:
        assert block["text"] in joined, block["text"][:60]


@requires_raw
def test_v3_shrinks_the_corpus_by_exactly_the_measured_amount() -> None:
    """40,739 -> 40,715: fifteen digits plus the nine joins that no longer run."""
    _, _, _, _, v3, _ = _v3()
    v2, _ = _v2()
    assert sum(len(p["text"]) for p in v2) == 40_739
    assert sum(len(p["text"]) for p in v3) == 40_715


@requires_raw
def test_the_rule_touches_no_real_figure_in_the_document() -> None:
    """Zero false positives, asserted rather than asserted-once-in-a-report.

    Every statistic in this filing sits inside a sentence, so it is never the
    whole of its block. This fails the moment that stops being true.
    """
    from dynamic_ai_products.ingestion.normalize import (
        is_page_number_block,
        normalize_span,
    )

    raw, lo, hi, _ = _real_span()
    blocks = normalize_span(raw, start_offset=lo, end_offset=hi)
    matched = [
        block["text"]
        for block in blocks
        if is_page_number_block(raw[block["start_offset"] : block["end_offset"]])
    ]
    assert tuple(matched) == PAGE_NUMBERS
    carries_a_figure = [
        block["text"]
        for block in blocks
        if block["text"] not in PAGE_NUMBERS and any(c.isdigit() for c in block["text"])
    ]
    assert len(carries_a_figure) == 18
    for text in carries_a_figure:
        assert text not in PAGE_NUMBERS


def test_a_block_that_merely_contains_a_number_is_not_a_page_number() -> None:
    """Containment would match a headcount; being the whole block does not."""
    from dynamic_ai_products.ingestion.normalize import is_page_number_block

    assert is_page_number_block(b"<p><span>9</span></p>")
    assert is_page_number_block(b"<p><span>247,939</span></p>")
    assert not is_page_number_block(
        b"<p>we had 247,939 Customers in more than 135 countries.</p>"
    )
    assert not is_page_number_block(b"<p><span>10.5</span></p>")
    assert not is_page_number_block(b"<p><span>Page 9</span></p>")


def test_a_bare_number_that_is_not_a_paragraph_is_not_a_page_number() -> None:
    """Same restriction as the heading rule, same refusal to generalize."""
    from dynamic_ai_products.ingestion.normalize import is_page_number_block

    assert not is_page_number_block(b"<div><span>9</span></div>")
    assert not is_page_number_block(b"<td>9</td>")
