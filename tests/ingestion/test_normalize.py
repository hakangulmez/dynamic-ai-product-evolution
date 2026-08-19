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
        NORMALIZER_VERSION_V4,
    )

    assert KNOWN_NORMALIZER_VERSIONS == (
        "sec_html_item_span_v1",
        "sec_html_item_span_v2",
        "sec_html_item_span_v3",
        "sec_html_item_span_v4",
    )
    assert NORMALIZER_VERSION == "sec_html_item_span_v1"
    assert NORMALIZER_VERSION_V2 == "sec_html_item_span_v2"
    assert NORMALIZER_VERSION_V3 == "sec_html_item_span_v3"
    assert NORMALIZER_VERSION_V4 == "sec_html_item_span_v4"


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


# --- ADR-074: the detectors stop depending on one filing's markup ------------

# Synthetic, and deliberately so: the shapes below were measured across fifteen
# real filings, but no real filing HTML is committed here. Each fixture carries
# exactly one measured property and nothing incidental.

DIV_700_FIXTURE = (
    b'<div><span style="font-weight:700;">Our Platform</span></div>'
    b"<div>The platform does a number of things for customers.</div>"
    b"<div>4</div>"
    b'<div><span style="font-weight:700;">Our Customers</span></div>'
    b"<div>Customers are located in many countries.</div>"
)

PARAGRAPH_BOLD_FIXTURE = (
    b'<p><span style="font-weight:bold;">Our Platform</span></p>'
    b"<p>The platform does a number of things for customers.</p>"
)


def _fixture_passages(builder, fixture: bytes):
    return builder(fixture, source_id=SOURCE_ID, start_offset=0, end_offset=len(fixture))


def test_v4_reads_a_div_and_700_document_that_v3_cannot() -> None:
    """The measured defect, as a check.

    Fourteen of fifteen filings are ``</div>``-based with ``font-weight:700``.
    On every one of them both v3 detectors return ``False`` for every block --
    which reads as "no headings, no page numbers" and is instead "nothing was
    examined". The successor looks.
    """
    from dynamic_ai_products.ingestion.normalize import (
        build_passages_v3,
        build_passages_v4,
    )

    v3, ledger_v3 = _fixture_passages(build_passages_v3, DIV_700_FIXTURE)
    v4, ledger_v4 = _fixture_passages(build_passages_v4, DIV_700_FIXTURE)

    # v3 finds no heading, so the whole fixture collapses into one passage, and
    # finds no page number, so the bare "4" is concatenated into the prose.
    assert len(v3) == 1
    assert ledger_v3["dropped_blocks"] == []
    assert " 4 " in f" {v3[0]['text']} "

    # v4 finds both headings, opens a section at each, and drops the page number.
    assert len(v4) == 2
    assert v4[0]["text"].startswith("Our Platform")
    assert v4[1]["text"].startswith("Our Customers")
    assert [b["text"] for b in ledger_v4["dropped_blocks"]] == ["4"]
    assert " 4 " not in f" {v4[0]['text']} "


def test_v4_still_reads_the_paragraph_and_bold_shape() -> None:
    """Widening, not replacing: the one filing v3 worked on still works."""
    from dynamic_ai_products.ingestion.normalize import (
        build_passages_v3,
        build_passages_v4,
    )

    v3, _ = _fixture_passages(build_passages_v3, PARAGRAPH_BOLD_FIXTURE)
    v4, _ = _fixture_passages(build_passages_v4, PARAGRAPH_BOLD_FIXTURE)
    assert [p["text"] for p in v4] == [p["text"] for p in v3]


def test_v4_admits_only_the_emphasis_forms_that_were_measured() -> None:
    """``600``/``800``/``900``, ``<b>`` and ``<strong>`` measured zero in 15/15.

    They are refused on purpose. ADR-074 records the zero counts so a filing
    that uses one is a known extension point rather than a rediscovery -- and
    this test is what would fail if someone widened the rule without measuring.
    """
    from dynamic_ai_products.ingestion.normalize import is_heading_block_v4

    assert is_heading_block_v4(b'<div><span style="font-weight:700;">H</span></div>')
    assert is_heading_block_v4(b'<div><span style="font-weight:bold;">H</span></div>')
    for refused in (
        b'<div><span style="font-weight:600;">H</span></div>',
        b'<div><span style="font-weight:800;">H</span></div>',
        b'<div><span style="font-weight:900;">H</span></div>',
        b"<div><b>H</b></div>",
        b"<div><strong>H</strong></div>",
    ):
        assert not is_heading_block_v4(refused), refused


def test_v4_still_requires_the_block_to_be_nothing_but_its_emphasis() -> None:
    """Equality, not presence -- v1's rule, carried through unchanged."""
    from dynamic_ai_products.ingestion.normalize import is_heading_block_v4

    assert not is_heading_block_v4(
        b'<div>A sentence with a <span style="font-weight:700;">bold</span> run.</div>'
    )
    assert not is_heading_block_v4(b"<div>Plain prose with no emphasis at all.</div>")


def test_v4_page_number_rule_keeps_its_discriminator() -> None:
    """Dropping the container gate must not turn a statistic into a page number."""
    from dynamic_ai_products.ingestion.normalize import is_page_number_block_v4

    assert is_page_number_block_v4(b"<div>7</div>")
    assert is_page_number_block_v4(b"<div>1,024</div>")
    assert not is_page_number_block_v4(b"<div>247,939 Customers in 135 countries</div>")
    assert not is_page_number_block_v4(b"<div>10.5</div>")


# --- ADR-074: locating Item 1 across four measured heading variations --------

ITEM_ONE_VARIATIONS = {
    "roman_numeral_and_period": (b"ITEM I. BUSINESS", b"ITEM IA. RISK FACTORS"),
    "digit_and_entities": (b"ITEM 1.&#160;&#160;BUSINESS", b"ITEM 1A. RISK FACTORS"),
    "digit_and_colon": (b"ITEM 1: Business", b"ITEM 1A: Risk Factors"),
    "digit_and_dash": (b"ITEM 1 - BUSINESS", b"Item&#160;1A. Risk Factors"),
}


def _document(opening: bytes, closing: bytes, body: bytes = b"Body prose here.") -> bytes:
    """A table of contents, then the body, in the shape every filing uses."""
    return (
        b"<div>Table of Contents</div>"
        b"<div>" + opening + b" 4 " + closing + b" 11</div>"
        b"<div>" + opening + b"</div>"
        b"<div>" + body + b"</div>"
        b"<div>" + closing + b"</div>"
        b"<div>Risk prose that must stay outside the span.</div>"
    )


@pytest.mark.parametrize("name", sorted(ITEM_ONE_VARIATIONS))
def test_the_item_one_finder_reads_every_measured_variation(name: str) -> None:
    from dynamic_ai_products.ingestion.normalize import (
        find_item_one_span,
        normalize_span,
    )

    opening, closing = ITEM_ONE_VARIATIONS[name]
    raw = _document(opening, closing)
    lo, hi = find_item_one_span(raw)
    text = " ".join(b["text"] for b in normalize_span(raw, start_offset=lo, end_offset=hi))
    assert "Body prose here." in text
    assert "Risk prose that must stay outside the span." not in text
    # The table-of-contents copy is not the body heading.
    assert "Table of Contents" not in text


def test_the_end_anchor_does_not_lock_onto_an_inline_cross_reference() -> None:
    """One filing carries seven ``see Part I, Item 1A Risk Factors`` phrases.

    Taking the first of them cuts that filing's Item 1 from 104,132 bytes to
    58,046 -- a silent 44% loss. The end anchor must open a block.
    """
    from dynamic_ai_products.ingestion.normalize import (
        find_item_one_span,
        normalize_span,
    )

    raw = (
        b"<div>Table of Contents</div>"
        b"<div>Item 1. Business 4 Item 1A. Risk Factors 11</div>"
        b"<div>Item 1. Business</div>"
        b"<div>Opening prose.</div>"
        b"<div>For more, see Part I, Item 1A Risk Factors in this Form 10-K.</div>"
        b"<div>Closing prose that must survive.</div>"
        b"<div>Item 1A. Risk Factors</div>"
        b"<div>Risk prose that must stay outside the span.</div>"
    )
    lo, hi = find_item_one_span(raw)
    text = " ".join(b["text"] for b in normalize_span(raw, start_offset=lo, end_offset=hi))
    assert "Opening prose." in text
    assert "Closing prose that must survive." in text
    assert "Risk prose that must stay outside the span." not in text


def test_the_item_one_finder_prefers_an_anchor_when_the_filing_carries_one() -> None:
    from dynamic_ai_products.ingestion.normalize import find_item_one_span

    raw = (
        b'<div id="item_i_business"><span>ITEM I. BUSINESS</span></div>'
        b"<div>Body prose here.</div>"
        b'<div id="item_1a_risk_factors"><span>ITEM 1A. RISK FACTORS</span></div>'
    )
    lo, hi = find_item_one_span(raw)
    assert raw[lo : lo + 1] == b">"
    assert raw[hi:].startswith(b'id="item_1a_risk_factors"')


def test_the_item_one_finder_refuses_rather_than_guessing() -> None:
    from dynamic_ai_products.ingestion.normalize import find_item_one_span

    with pytest.raises(IngestionError) as excinfo:
        find_item_one_span(b"<div>A filing with no Item 1 heading at all.</div>")
    assert excinfo.value.reason_code == "item_span_not_found"


@requires_raw
def test_the_finder_reproduces_the_pinned_span_exactly() -> None:
    """The anchor path must return the span the committed corpus was built from.

    A span one tag wider would move every offset in the HubSpot chain.
    """
    from dynamic_ai_products.ingestion.normalize import find_item_one_span

    raw, lo, hi, _ = _real_span()
    assert find_item_one_span(raw) == (lo, hi)


@requires_raw
def test_v4_reproduces_the_committed_v3_corpus_apart_from_its_version() -> None:
    """No regression on the document v3 was written for.

    Same 16 sections, same offsets, same text, same nine dropped blocks. The
    only field that differs is the one that must.
    """
    from dynamic_ai_products.ingestion.normalize import build_passages_v4

    _, _, _, _, v3, ledger_v3 = _v3()
    raw, lo, hi, _ = _real_span()
    v4, ledger_v4 = build_passages_v4(
        raw, source_id=REAL_SOURCE_ID, start_offset=lo, end_offset=hi
    )
    assert len(v4) == 16
    strip = lambda ps: [  # noqa: E731
        {k: v for k, v in p.items() if k != "normalizer_version"} for p in ps
    ]
    assert strip(v4) == strip(v3)
    assert {p["normalizer_version"] for p in v4} == {"sec_html_item_span_v4"}
    assert ledger_v4["dropped_blocks"] == ledger_v3["dropped_blocks"]
    assert len(ledger_v4["dropped_blocks"]) == 9


@requires_raw
def test_v1_v2_and_v3_are_byte_identical_after_the_successor_lands() -> None:
    """Successor, not edit. The concrete reason: the HubSpot chain is hash-pinned
    to v3's output -- srcsnap-v3, ext-smoke-0009, cap-0006 and every task run and
    decision set that cites them. A byte moved here invalidates all of it.
    """
    import json

    from dynamic_ai_products.ingestion.normalize import (
        build_passages_v2,
        build_passages_v3,
    )

    raw, lo, hi, committed_v1 = _real_span()
    root = Path(__file__).resolve().parents[2] / "data/runs"

    def committed(version: str) -> list[dict]:
        return [
            json.loads(line)
            for line in (
                root / f"srcsnap-hubspot-fy2024-sec-{version}/source_passages.jsonl"
            ).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    v1, _ = build_passages(raw, source_id=REAL_SOURCE_ID, start_offset=lo, end_offset=hi)
    v2, _ = build_passages_v2(raw, source_id=REAL_SOURCE_ID, start_offset=lo, end_offset=hi)
    v3, _ = build_passages_v3(raw, source_id=REAL_SOURCE_ID, start_offset=lo, end_offset=hi)
    assert v1 == committed_v1
    assert v2 == committed("v2")
    assert v3 == committed("v3")


# --- ADR-104: the combined-heading successor, S2 only -------------------------
#
# find_item_one_span_v3 admits exactly one new start shape — the combined
# "Items 1 and 2. Business and Properties" heading — behind a fallback that
# fires only when v2 raises item_span_not_found. Everything else about v2 is
# preserved verbatim, and these tests pin both halves: the recovery and the
# preservation.


def _locator_v3():
    from dynamic_ai_products.ingestion.normalize import find_item_one_span_v3
    return find_item_one_span_v3


def _locator_v2():
    from dynamic_ai_products.ingestion.normalize import find_item_one_span_v2
    return find_item_one_span_v2


def _combined_doc(heading: bytes, boundary: bytes) -> bytes:
    return (
        b"<html><p>Table of contents mentions " + heading + b" here.</p>"
        b"<p>Some front matter.</p>"
        b"<p>" + heading + b"</p>"
        b"<p>We drill, gather and process. Our properties are described "
        b"together with our business, as the heading says.</p>"
        b"<p>" + boundary + b"</p>"
        b"<p>Content after the boundary.</p></html>"
    )


def test_v3_recovers_the_combined_heading_and_v2_still_refuses() -> None:
    from dynamic_ai_products.ingestion.errors import IngestionError

    raw = _combined_doc(b"Items 1 and 2. Business and Properties",
                        b"Item 1A. Risk Factors")
    with pytest.raises(IngestionError) as v2_exc:
        _locator_v2()(raw)
    assert v2_exc.value.reason_code == "item_span_not_found"
    start, end, kind = _locator_v3()(raw)
    assert kind == "item_1a_risk_factors"
    body = raw[start:end]
    assert b"We drill, gather and process" in body
    assert b"Risk Factors" not in body
    # The TOC occurrence did not supply the start: the body heading did.
    assert body.count(b"Items 1 and 2") == 1


@pytest.mark.parametrize("spelling", [
    b"Items 1 and 2. Business and Properties",
    b"Items 1. and 2. Business and Properties",
    b"Items 1 & 2 - Business and Properties",
    b"ITEMS 1 AND 2. BUSINESS AND PROPERTIES",
])
def test_v3_admits_exactly_the_measured_spellings(spelling) -> None:
    start, end, kind = _locator_v3()(_combined_doc(spelling, b"Item 1A. Risk Factors"))
    assert kind == "item_1a_risk_factors"
    assert end > start


def test_v3_is_not_a_general_wording_expansion() -> None:
    """S1 is not implemented: the worded plain heading still fails."""
    from dynamic_ai_products.ingestion.errors import IngestionError

    raw = _combined_doc(b"Item 1. Description of Business",
                        b"Item 1A. Risk Factors")
    with pytest.raises(IngestionError) as caught:
        _locator_v3()(raw)
    assert caught.value.reason_code == "item_span_not_found"


def test_v3_never_ends_a_combined_section_at_item_two() -> None:
    """A later Item 2 token cannot truncate the merged section."""
    from dynamic_ai_products.ingestion.errors import IngestionError

    # Item 2 present after the combined heading, 1A also present later: the
    # span must end at 1A and contain the Item 2 heading whole.
    raw = (
        b"<html><p>Items 1 and 2. Business and Properties</p>"
        b"<p>Business narrative.</p>"
        b"<p>Item 2. Properties</p>"
        b"<p>Our properties, inside the merged section.</p>"
        b"<p>Item 1A. Risk Factors</p><p>Risks.</p></html>"
    )
    start, end, kind = _locator_v3()(raw)
    assert kind == "item_1a_risk_factors"
    assert b"Item 2. Properties" in raw[start:end]
    assert b"inside the merged section" in raw[start:end]

    # Only Item 2 after the combined heading: fail closed, never truncate.
    raw = (
        b"<html><p>Items 1 and 2. Business and Properties</p>"
        b"<p>Business narrative.</p>"
        b"<p>Item 2. Properties</p><p>Properties text.</p></html>"
    )
    with pytest.raises(IngestionError) as caught:
        _locator_v3()(raw)
    assert caught.value.reason_code == "no_end_boundary"


def test_v3_combined_with_only_item_three_stays_no_end_boundary() -> None:
    """The Item 3 tier is deliberately absent."""
    from dynamic_ai_products.ingestion.errors import IngestionError

    raw = (
        b"<html><p>Items 1 and 2. Business and Properties</p>"
        b"<p>Business narrative.</p>"
        b"<p>Item 3. Legal Proceedings</p><p>None.</p></html>"
    )
    with pytest.raises(IngestionError) as caught:
        _locator_v3()(raw)
    assert caught.value.reason_code == "no_end_boundary"


def test_v3_refuses_an_inline_combined_cross_reference() -> None:
    """The block guard is not relaxed: mid-prose mentions supply nothing."""
    from dynamic_ai_products.ingestion.errors import IngestionError

    raw = (
        b"<html><p>As described under Items 1 and 2. Business and Properties "
        b"of this report, we operate wells.</p>"
        b"<p>Item 1A. Risk Factors</p><p>Risks.</p></html>"
    )
    with pytest.raises(IngestionError) as caught:
        _locator_v3()(raw)
    assert caught.value.reason_code == "item_span_not_found"


def test_v3_keeps_v2_single_candidate_ambiguity_on_the_retry() -> None:
    from dynamic_ai_products.ingestion.errors import IngestionError

    raw = (
        b"<html><p>Items 1 and 2. Business and Properties</p>"
        b"<p>Business narrative.</p>"
        b"<p>Item 1A. Risk Factors</p><p>Risks.</p>"
        b"<p>Item 1A. Risk Factors</p><p>More risks.</p></html>"
    )
    with pytest.raises(IngestionError) as caught:
        _locator_v3()(raw)
    assert caught.value.reason_code == "ambiguous_end_boundary"


def test_v3_returns_the_exact_v2_result_on_success() -> None:
    from dynamic_ai_products.ingestion.normalize import find_item_one_span_v2

    raw = (
        b"<html><p>Item 1. Business</p><p>Ordinary narrative.</p>"
        b"<p>Item 1A. Risk Factors</p><p>Risks.</p></html>"
    )
    assert _locator_v3()(raw) == find_item_one_span_v2(raw)


def test_v3_reraises_v2_ambiguous_and_no_end_unchanged() -> None:
    from dynamic_ai_products.ingestion.errors import IngestionError

    ambiguous = (
        b"<html><p>Item 1. Business</p><p>Narrative.</p>"
        b"<p>Item 1A. Risk Factors</p><p>Risks.</p>"
        b"<p>Item 1A. Risk Factors</p><p>Again.</p></html>"
    )
    no_end = (
        b"<html><p>Item 1. Business</p><p>Narrative with no boundary.</p>"
        b"</html>"
    )
    for raw in (ambiguous, no_end):
        with pytest.raises(IngestionError) as v2_exc:
            _locator_v2()(raw)
        with pytest.raises(IngestionError) as v3_exc:
            _locator_v3()(raw)
        assert v3_exc.value.reason_code == v2_exc.value.reason_code
        assert str(v3_exc.value) == str(v2_exc.value)


def test_v3_propagates_non_locator_errors_identically() -> None:
    from dynamic_ai_products.ingestion.errors import IngestionError

    for function in (_locator_v2(), _locator_v3()):
        with pytest.raises(IngestionError) as caught:
            function("not bytes")  # type: ignore[arg-type]
        assert caught.value.reason_code == "normalize_input_invalid"
