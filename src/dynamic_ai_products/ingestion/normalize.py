"""Stage 04 document normalization (SPEC-006, ADR-031).

``sec_html_item_span_v1`` is deterministic, pure, and offline. It normalizes
only an anchor-bounded byte span of an already hash-locked raw document — not
a whole filing — and no model, network, or clock participates.

Provenance carriers, with no field added to either governed schema (both
declare ``additionalProperties: false``):

- which normalizer produced the text -> ``source_passage.normalizer_version``
- where the text came from           -> ``start_offset`` / ``end_offset``,
                                        absolute into the RAW document bytes
- identity of the raw document       -> ``source_document.content_hash``
- identity of the normalized text    -> ``source_passage.text_hash``
- the transform chain itself         -> ledger in the preflight manifest

The asymmetry is deliberate and declared: offsets address raw bytes while
``text_hash`` covers normalized text, so an emitted passage is not a
byte-identical slice of the raw document.
"""

from __future__ import annotations

import html
import re
from hashlib import sha256
from typing import Any

from .errors import IngestionError

__all__ = [
    "KNOWN_NORMALIZER_VERSIONS",
    "NORMALIZER_VERSION",
    "NORMALIZER_VERSION_V2",
    "NORMALIZER_VERSION_V3",
    "TRANSFORM_CHAIN",
    "build_passages",
    "build_passages_v2",
    "build_passages_v3",
    "is_heading_block",
    "is_page_number_block",
    "normalize_span",
    "normalize_span_v2",
    "normalize_span_v3",
    "passage_id_for",
]

NORMALIZER_VERSION = "sec_html_item_span_v1"

# ADR-066. The section-grouping successor. A separate function and a separate
# version rather than a mode flag on the first one: ``sec_html_item_span_v1``
# produced the passages behind Snapshot A and every chain that cites them, and
# a parameter with a default is how a released behaviour gets changed by
# accident. The two live side by side, exactly as ``run_extraction_stage`` and
# ``run_extraction_stage_v2`` do.
NORMALIZER_VERSION_V2 = "sec_html_item_span_v2"

# ADR-072. Section grouping made the printed page numbers *interior* to a
# section instead of splitting a sentence across two passages, which is what
# ADR-066 set out to fix. It did not remove them: joining "…include: email",
# "9" and "templates and tracking…" yields "…include: email 9 templates…", and
# that string reached eleven accepted capability observations and ten accepted
# task observations through Sales Hub. The successor drops the page-number
# block instead of concatenating it.
NORMALIZER_VERSION_V3 = "sec_html_item_span_v3"

# Every normalizer version this code has ever published, oldest first. A
# persisted passage records the version that produced it, so a reader has to
# recognise the historical ones as well as today's.
KNOWN_NORMALIZER_VERSIONS: tuple[str, ...] = (
    NORMALIZER_VERSION,
    NORMALIZER_VERSION_V2,
    NORMALIZER_VERSION_V3,
)

# Declared, ordered transform chain. Recorded verbatim in the ledger.
TRANSFORM_CHAIN: tuple[str, ...] = (
    "markup_tag_removal",
    "html_entity_decoding",
    "whitespace_collapse",
)

_TAG_RE = re.compile(rb"<[^>]*>")
_WS_RE = re.compile(r"\s+")
_BLOCK_SPLIT_RE = re.compile(rb"(?i)</(?:p|div|tr|li|h[1-6]|table|section)\s*>")


def passage_id_for(source_id: str, text_hash: str, occurrence_index: int) -> str:
    """Content-addressed, offset-independent passage identity.

    Stable when unrelated parts of the document change, as
    docs/architecture/CORPUS_ARCHITECTURE.md requires. ``occurrence_index``
    disambiguates identical text within one document.
    """
    material = f"{source_id}\x00{text_hash}\x00{occurrence_index}".encode("utf-8")
    return sha256(material).hexdigest()[:32]


def _normalize_fragment(fragment: bytes) -> str:
    stripped = _TAG_RE.sub(b" ", fragment)
    decoded = html.unescape(stripped.decode("utf-8", errors="strict"))
    return _WS_RE.sub(" ", decoded).strip()


def normalize_span(
    raw: bytes,
    *,
    start_offset: int,
    end_offset: int,
) -> list[dict[str, Any]]:
    """Normalize one raw byte span into ordered block records.

    Each record carries absolute raw-byte offsets into ``raw`` so the chain
    back to the immutable snapshot stays exact.
    """
    if not isinstance(raw, (bytes, bytearray)):
        raise IngestionError(
            "normalization input must be raw bytes",
            reason_code="normalize_input_invalid",
        )
    if not isinstance(start_offset, int) or not isinstance(end_offset, int):
        raise IngestionError(
            "span offsets must be integers",
            reason_code="normalize_span_invalid",
        )
    if start_offset < 0 or end_offset > len(raw) or start_offset >= end_offset:
        raise IngestionError(
            f"span [{start_offset}, {end_offset}) is out of bounds for "
            f"{len(raw)} raw bytes",
            reason_code="normalize_span_invalid",
        )

    span = bytes(raw[start_offset:end_offset])
    records: list[dict[str, Any]] = []
    cursor = 0
    for match in _BLOCK_SPLIT_RE.finditer(span):
        block_end = match.end()
        fragment = span[cursor:block_end]
        text = _normalize_fragment(fragment)
        if text:
            records.append(
                {
                    "text": text,
                    "start_offset": start_offset + cursor,
                    "end_offset": start_offset + block_end,
                }
            )
        cursor = block_end
    if cursor < len(span):
        fragment = span[cursor:]
        text = _normalize_fragment(fragment)
        if text:
            records.append(
                {
                    "text": text,
                    "start_offset": start_offset + cursor,
                    "end_offset": start_offset + len(span),
                }
            )
    return records


def build_passages(
    raw: bytes,
    *,
    source_id: str,
    start_offset: int,
    end_offset: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build ``source_passage`` records plus the transform/provenance ledger."""
    blocks = normalize_span(raw, start_offset=start_offset, end_offset=end_offset)

    seen: dict[str, int] = {}
    passages: list[dict[str, Any]] = []
    normalized_bytes = 0
    for block in blocks:
        text = block["text"]
        text_hash = sha256(text.encode("utf-8")).hexdigest()
        occurrence = seen.get(text_hash, 0)
        seen[text_hash] = occurrence + 1
        normalized_bytes += len(text.encode("utf-8"))
        passages.append(
            {
                "passage_id": passage_id_for(source_id, text_hash, occurrence),
                "source_id": source_id,
                "heading_path": [],
                "text": text,
                "text_hash": text_hash,
                "start_offset": block["start_offset"],
                "end_offset": block["end_offset"],
                "page": None,
                "normalizer_version": NORMALIZER_VERSION,
            }
        )

    span_bytes = end_offset - start_offset
    ledger = {
        "normalizer_version": NORMALIZER_VERSION,
        "transform_chain": list(TRANSFORM_CHAIN),
        "input_span": {"start_offset": start_offset, "end_offset": end_offset},
        "input_byte_count": span_bytes,
        "normalized_byte_count": normalized_bytes,
        "dropped_byte_count": span_bytes - normalized_bytes,
        "text_provenance_note": (
            "offsets address raw document bytes; text_hash covers normalized "
            "text, so a passage is not a byte-identical raw slice"
        ),
        "passages": [
            {
                "passage_id": passage["passage_id"],
                "start_offset": passage["start_offset"],
                "end_offset": passage["end_offset"],
                "text_hash": passage["text_hash"],
            }
            for passage in passages
        ],
    }
    return passages, ledger


# --- ADR-066: section grouping ----------------------------------------------

# A bold run inside one block. The rule below compares what a block *says* with
# what its bold runs say, so this pattern only has to find them.
_BOLD_SPAN_RE = re.compile(rb"(?is)<span[^>]*font-weight:\s*bold[^>]*>(.*?)</span>")
_PARAGRAPH_CLOSE_RE = re.compile(rb"(?i)</p\s*>\s*$")


def is_heading_block(fragment: bytes) -> bool:
    """Is this block a section heading?

    **Measured, not assumed.** The plan behind this was to split on ``</h1>``
    through ``</h6>``. The document has **none**: zero ``<hN>`` tags in
    4,764,421 bytes. Its section headings are ordinary paragraphs whose entire
    content sits inside bold ``<span>`` runs, which is what this asks.

    The test is equality, not presence: a block is a heading when its whole
    normalized text is exactly its bold runs' normalized text. Presence would
    match any paragraph containing a bold phrase; equality matches only a block
    that is *nothing but* its bold text. Measured over Item 1 of the pinned
    HubSpot 10-K, that is 15 blocks and no others -- the fifteen section
    headings, zero false positives.

    Restricted to blocks closing with ``</p>`` because that is what was
    verified. Measured: allowing every block type finds the same fifteen here,
    so the restriction costs nothing today and refuses to generalize from one
    document.
    """
    if not _PARAGRAPH_CLOSE_RE.search(fragment):
        return False
    bold = b" ".join(_BOLD_SPAN_RE.findall(fragment))
    if not bold.strip():
        return False
    return _normalize_fragment(fragment) == _normalize_fragment(bold)


def normalize_span_v2(
    raw: bytes,
    *,
    start_offset: int,
    end_offset: int,
) -> list[dict[str, Any]]:
    """Normalize one raw byte span into ordered **section** records.

    Same block boundaries and same transform chain as
    :func:`normalize_span` -- this reuses it rather than re-deriving them, so
    the two normalizers cannot disagree about where a block ends or what its
    text is. What differs is only what becomes a record: a heading opens a new
    section and every block up to the next heading joins it.

    **Why.** Under v1 a page number sitting between two halves of a sentence
    became its own passage and split the sentence across two of them. Measured
    on the pinned document: four such splits, and a model that reassembled one
    of them produced a quote that C8 (ADR-063) refuses. Grouping makes the
    interruption interior to a section, so the sentence is never divided.

    **Content before the first heading gets its own record**, rather than being
    dropped or folded into the first section. In the pinned document that is the
    item title, which is not itself a heading here: the anchored span begins
    inside its opening ``<p>`` tag, so the block's text carries a leading ``>``
    that its bold runs do not. Nothing is invented to special-case it -- the
    same "a record ends where the next heading begins" rule produces it.
    """
    blocks = normalize_span(raw, start_offset=start_offset, end_offset=end_offset)
    if not blocks:
        return []

    # The heading test needs the raw bytes, which ``normalize_span`` does not
    # return. Re-slicing from the offsets it *did* return keeps one owner of the
    # boundaries: this cannot see a block the first function did not emit.
    sections: list[dict[str, Any]] = []
    for block in blocks:
        fragment = bytes(raw[block["start_offset"] : block["end_offset"]])
        if is_heading_block(fragment) or not sections:
            sections.append(
                {
                    "text": block["text"],
                    "start_offset": block["start_offset"],
                    "end_offset": block["end_offset"],
                }
            )
            continue
        current = sections[-1]
        current["text"] = f"{current['text']} {block['text']}"
        current["end_offset"] = block["end_offset"]
    return sections


def build_passages_v2(
    raw: bytes,
    *,
    source_id: str,
    start_offset: int,
    end_offset: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """``build_passages`` over section records instead of block records.

    Identical in every other respect, including ``passage_id`` derivation: the
    id is content-addressed, so a section and a block with the same text would
    share one -- which is correct, and does not arise here because no section
    equals a single block except the ones that genuinely stand alone.
    """
    blocks = normalize_span_v2(raw, start_offset=start_offset, end_offset=end_offset)

    seen: dict[str, int] = {}
    passages: list[dict[str, Any]] = []
    normalized_bytes = 0
    for block in blocks:
        text = block["text"]
        text_hash = sha256(text.encode("utf-8")).hexdigest()
        occurrence = seen.get(text_hash, 0)
        seen[text_hash] = occurrence + 1
        normalized_bytes += len(text.encode("utf-8"))
        passages.append(
            {
                "passage_id": passage_id_for(source_id, text_hash, occurrence),
                "source_id": source_id,
                "heading_path": [],
                "text": text,
                "text_hash": text_hash,
                "start_offset": block["start_offset"],
                "end_offset": block["end_offset"],
                "page": None,
                "normalizer_version": NORMALIZER_VERSION_V2,
            }
        )

    span_bytes = end_offset - start_offset
    ledger = {
        "normalizer_version": NORMALIZER_VERSION_V2,
        "transform_chain": list(TRANSFORM_CHAIN),
        "input_span": {"start_offset": start_offset, "end_offset": end_offset},
        "input_byte_count": span_bytes,
        "normalized_byte_count": normalized_bytes,
        "dropped_byte_count": span_bytes - normalized_bytes,
        "text_provenance_note": (
            "offsets address raw document bytes; text_hash covers normalized "
            "text, so a passage is not a byte-identical raw slice"
        ),
        "passages": [
            {
                "passage_id": passage["passage_id"],
                "start_offset": passage["start_offset"],
                "end_offset": passage["end_offset"],
                "text_hash": passage["text_hash"],
            }
            for passage in passages
        ],
    }
    return passages, ledger


# --- ADR-072: page-number blocks are dropped, not concatenated ---------------

# A block whose entire normalized text is one bare number. Thousands separators
# are allowed so a five-figure page number would still match; a decimal point is
# not, because a bare "10.5" is not how a page is printed.
_PAGE_NUMBER_RE = re.compile(r"^\d[\d,]*$")


def is_page_number_block(fragment: bytes) -> bool:
    """Is this block nothing but a printed page number?

    **The discriminator is that the block is the number, not that it contains
    one.** Measured over the pinned document's Item 1: 124 blocks, of which 9
    match -- the consecutive page numbers 7 through 15 -- and 0 others. The 18
    blocks that do carry figures ("between 2 and 2,000 employees", "247,939
    Customers in more than 135 countries", "20 issued U.S. Patents") match
    nothing here, because a statistic is always part of a sentence and therefore
    never the whole of its block. That is why this is a structural test and not
    a regex hunting for digits inside prose: the latter cannot tell a page
    number from a headcount, and this does not have to.

    ADR-066 prototyped a different test -- digits-only block whose predecessor
    does not end in a full stop -- and reported it caught "4 of 4". Re-measured
    here, that rule fires on 4 of these 9. It was never separating page numbers
    from data (it was already gated on digits-only); it was separating the
    *sentence-splitting* page numbers from the ones that happen to fall on a
    sentence boundary. Under v1 that distinction mattered, because the remedy
    was to merge two passages and a needless merge would have moved a
    passage_id. Under section grouping all nine are interior to a section and
    all nine are equally noise, so the successor treats them alike.

    Restricted to blocks closing with ``</p>`` for the reason ``is_heading_block``
    is: all nine already close that way, so the restriction costs nothing here
    and declines to generalize from one document.
    """
    if not _PARAGRAPH_CLOSE_RE.search(fragment):
        return False
    return bool(_PAGE_NUMBER_RE.fullmatch(_normalize_fragment(fragment)))


def normalize_span_v3(
    raw: bytes,
    *,
    start_offset: int,
    end_offset: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``normalize_span_v2`` with page-number blocks dropped from the join.

    Returns ``(sections, dropped)``. Block boundaries and the heading rule are
    v2's, reused rather than re-derived, so the three normalizers cannot
    disagree about where a block ends or which block opens a section.

    **The deletion is whole-block, never intra-block.** "…include: email 9
    templates…" becomes "…include: email templates…" because a block vanished,
    not because a sentence was edited. No character inside a surviving block is
    rewritten, and no character is added except the joining spaces -- so the one
    thing a reader must be able to trust about a passage, that its words are the
    document's words, still holds.

    **This deliberately widens ADR-066's invariant.** That one read: every v1
    passage's text appears verbatim inside exactly one v2 section, and the only
    characters added are the joining spaces. It cannot survive a rule that
    removes anything. The replacement, which ``build_passages_v3`` makes
    checkable by enumerating what it dropped: every v1 passage's text either
    appears verbatim inside exactly one v3 section **or** is listed in the
    ledger's ``dropped_blocks`` with its offsets and its text. A removal that is
    counted and named is not a silent repair.

    **Section spans are v2's, unchanged.** A dropped block's bytes stay inside
    the span even when the block is the section's last -- which happens once,
    for "Our Customers", whose trailing block is page 10. The alternative was to
    pull ``end_offset`` back to the last surviving block, and it was rejected:
    the ledger already declares that offsets address raw bytes while
    ``text_hash`` covers normalized text and the two are not a byte-identical
    slice (tags and whitespace are dropped inside every span already). Keeping
    the spans makes all 16 v3 offsets equal to v2's, so a diff between the two
    corpora is exactly the set of sections whose *text* changed.
    """
    blocks = normalize_span(raw, start_offset=start_offset, end_offset=end_offset)
    if not blocks:
        return [], []

    sections: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for block in blocks:
        fragment = bytes(raw[block["start_offset"] : block["end_offset"]])
        if is_heading_block(fragment) or not sections:
            sections.append(
                {
                    "text": block["text"],
                    "start_offset": block["start_offset"],
                    "end_offset": block["end_offset"],
                }
            )
            continue
        current = sections[-1]
        # The span grows whether or not the text does: see the docstring.
        current["end_offset"] = block["end_offset"]
        if is_page_number_block(fragment):
            dropped.append(
                {
                    "start_offset": block["start_offset"],
                    "end_offset": block["end_offset"],
                    "text": block["text"],
                }
            )
            continue
        current["text"] = f"{current['text']} {block['text']}"
    return sections, dropped


def build_passages_v3(
    raw: bytes,
    *,
    source_id: str,
    start_offset: int,
    end_offset: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """``build_passages_v2`` over v3 sections, with the drops recorded.

    The ledger gains ``dropped_blocks``: one entry per removed block, carrying
    its offsets and its exact text. It is the auditable half of the widened
    invariant -- without it the corpus would be quietly shorter than its source
    and no reader could tell what left.
    """
    sections, dropped = normalize_span_v3(
        raw, start_offset=start_offset, end_offset=end_offset
    )

    seen: dict[str, int] = {}
    passages: list[dict[str, Any]] = []
    normalized_bytes = 0
    for section in sections:
        text = section["text"]
        text_hash = sha256(text.encode("utf-8")).hexdigest()
        occurrence = seen.get(text_hash, 0)
        seen[text_hash] = occurrence + 1
        normalized_bytes += len(text.encode("utf-8"))
        passages.append(
            {
                "passage_id": passage_id_for(source_id, text_hash, occurrence),
                "source_id": source_id,
                "heading_path": [],
                "text": text,
                "text_hash": text_hash,
                "start_offset": section["start_offset"],
                "end_offset": section["end_offset"],
                "page": None,
                "normalizer_version": NORMALIZER_VERSION_V3,
            }
        )

    span_bytes = end_offset - start_offset
    ledger = {
        "normalizer_version": NORMALIZER_VERSION_V3,
        "transform_chain": list(TRANSFORM_CHAIN),
        "input_span": {"start_offset": start_offset, "end_offset": end_offset},
        "input_byte_count": span_bytes,
        "normalized_byte_count": normalized_bytes,
        "dropped_byte_count": span_bytes - normalized_bytes,
        "text_provenance_note": (
            "offsets address raw document bytes; text_hash covers normalized "
            "text, so a passage is not a byte-identical raw slice"
        ),
        "dropped_blocks": dropped,
        "passages": [
            {
                "passage_id": passage["passage_id"],
                "start_offset": passage["start_offset"],
                "end_offset": passage["end_offset"],
                "text_hash": passage["text_hash"],
            }
            for passage in passages
        ],
    }
    return passages, ledger
