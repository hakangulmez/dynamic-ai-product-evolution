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
    "NORMALIZER_VERSION_V4",
    "TRANSFORM_CHAIN",
    "build_passages",
    "build_passages_v2",
    "build_passages_v3",
    "build_passages_v4",
    "find_item_one_span",
    "is_heading_block",
    "is_heading_block_v4",
    "is_page_number_block",
    "is_page_number_block_v4",
    "normalize_span",
    "normalize_span_v2",
    "normalize_span_v3",
    "normalize_span_v4",
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

# ADR-074. v1 through v3 were measured on one filing and both their detectors
# were gated on ``</p>``. Measured across fifteen large multi-product US 10-K
# filers, that gate holds in **one** of them: fourteen are ``</div>``-based with
# ``font-weight:700``, and in all fourteen ``is_heading_block`` and
# ``is_page_number_block`` return zero for every block -- not because the
# documents lack headings or page numbers, but because neither detector ever
# looked. v1's own docstring predicted this and declined to generalize; the
# second document proved it right. The successor drops the container gate and
# admits ``700`` beside ``bold``.
NORMALIZER_VERSION_V4 = "sec_html_item_span_v4"

# Every normalizer version this code has ever published, oldest first. A
# persisted passage records the version that produced it, so a reader has to
# recognise the historical ones as well as today's.
KNOWN_NORMALIZER_VERSIONS: tuple[str, ...] = (
    NORMALIZER_VERSION,
    NORMALIZER_VERSION_V2,
    NORMALIZER_VERSION_V3,
    NORMALIZER_VERSION_V4,
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


# --- ADR-074: the detectors stop depending on one filing's markup ------------

# The emphasis forms this admits are **exactly the ones measured**. Across the
# fifteen filings: ``font-weight:bold`` appears in 1, ``font-weight:700`` in 14,
# and ``600``/``800``/``900``, ``<b>`` and ``<strong>`` in **none**. Adding an
# unmeasured form would be the speculation this project keeps refusing; the zero
# counts are recorded in ADR-074 so a filing that uses one is a known extension
# point rather than a rediscovery.
_EMPHASIS_SPAN_RE = re.compile(
    rb"(?is)<span[^>]*font-weight:\s*(?:bold|700)[^>]*>(.*?)</span>"
)


def is_heading_block_v4(fragment: bytes) -> bool:
    """``is_heading_block`` without the container gate and with ``700``.

    Two changes, both measured, and nothing else:

    - **The ``</p>`` requirement is gone.** ``_BLOCK_SPLIT_RE`` already accepts
      ``p|div|tr|li|h1-6|table|section`` and produced 75-240 blocks in every one
      of the fifteen filings, so what failed was never the splitting. v1's own
      docstring had measured that allowing every block type ``finds the same
      fifteen here`` -- the gate bought nothing even on the document it was
      written for, and cost everything on the other fourteen.
    - **``font-weight:700`` is admitted beside ``bold``.** They are the same
      declaration written two ways; the CSS keyword ``bold`` *is* 700.

    The test is still equality, not presence, for v1's reason: a block is a
    heading when its whole normalized text is its emphasized text, so a
    paragraph that merely contains a bold phrase does not match.

    **No regression, measured:** on the pinned HubSpot Item 1 this returns the
    same 15 blocks as ``is_heading_block``, at the same indices.
    """
    emphasized = b" ".join(_EMPHASIS_SPAN_RE.findall(fragment))
    if not emphasized.strip():
        return False
    return _normalize_fragment(fragment) == _normalize_fragment(emphasized)


def is_page_number_block_v4(fragment: bytes) -> bool:
    """``is_page_number_block`` without the container gate.

    The same defect, in the same place. ADR-072 restricted this to ``</p>``
    because all nine of the pinned document's page numbers closed that way and
    the restriction was free there. It is not free anywhere else: in fourteen of
    fifteen filings it returns ``False`` for every block, which reads as "this
    filing prints no page numbers" and is instead "nothing was examined".

    **No regression, measured:** on the pinned HubSpot Item 1 this drops the
    same 9 blocks as ``is_page_number_block``, at the same indices.
    """
    return bool(_PAGE_NUMBER_RE.fullmatch(_normalize_fragment(fragment)))


def normalize_span_v4(
    raw: bytes,
    *,
    start_offset: int,
    end_offset: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``normalize_span_v3`` with the v4 detectors.

    Section grouping, the drop-don't-concatenate rule and the span-keeping rule
    are v3's, called rather than re-derived. Only the two predicates change, so
    the four normalizers cannot disagree about where a block ends.
    """
    blocks = normalize_span(raw, start_offset=start_offset, end_offset=end_offset)
    if not blocks:
        return [], []

    sections: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for block in blocks:
        fragment = bytes(raw[block["start_offset"] : block["end_offset"]])
        if is_heading_block_v4(fragment) or not sections:
            sections.append(
                {
                    "text": block["text"],
                    "start_offset": block["start_offset"],
                    "end_offset": block["end_offset"],
                }
            )
            continue
        current = sections[-1]
        current["end_offset"] = block["end_offset"]
        if is_page_number_block_v4(fragment):
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


def build_passages_v4(
    raw: bytes,
    *,
    source_id: str,
    start_offset: int,
    end_offset: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """``build_passages_v3`` over v4 sections. Same ledger shape, new version."""
    sections, dropped = normalize_span_v4(
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
                "normalizer_version": NORMALIZER_VERSION_V4,
            }
        )

    span_bytes = end_offset - start_offset
    ledger = {
        "normalizer_version": NORMALIZER_VERSION_V4,
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


# --- ADR-074: locating Item 1 without depending on one filing's anchors ------

# Anchor ids, when a filing carries them. Measured: 1 of 15 filings does.
_ITEM_ANCHOR_RE = re.compile(rb'(?i)id="([^"]*item[^"]*)"')
_ITEM_ONE_ANCHOR = re.compile(r"(?i)item[_\-]?(?:1|i)(?:[_\-]business)?")
_ITEM_ONE_A_ANCHOR = re.compile(r"(?i)item[_\-]?1a(?:[_\-]risk.*)?")

# Heading text, when it does not. Four variations were measured across the
# fifteen filings and all four are admitted here:
#   separator   ``.``  ``:``  ``-``  (and the unicode dashes)
#   numeral     ``1``  or the Roman ``I``
#   entities    ``&#160;`` and friends, which must be resolved before matching
#   spacing     tag boundaries insert runs of whitespace between the words
_ITEM_SEPARATOR = r"[\.\:\-‐-―]?"
_ITEM_ONE_TEXT_RE = re.compile(
    (r"(?i)Item\s{0,20}(?:1|I)\s{0,20}" + _ITEM_SEPARATOR + r"\s{0,20}Business").encode()
)
_ITEM_ONE_A_TEXT_RE = re.compile(
    (r"(?i)Item\s{0,20}(?:1A|IA)\s{0,20}" + _ITEM_SEPARATOR + r"\s{0,20}Risk").encode()
)
_ENTITY_RE = re.compile(rb"&[#a-zA-Z0-9]{1,8};")
_ITEM_SPAN_NOT_FOUND = "item_span_not_found"

# --- ADR-091: an end boundary that is not only Item 1A ------------------------
#
# ``find_item_one_span`` ends the span at Item 1A and nothing else, which makes
# a filing that omits risk factors unreadable rather than differently shaped.
# The successor below keeps that behaviour as its first tier and falls back
# through the two items that can legitimately follow Item 1, in filing order.
# The v1 function above is unchanged: its callers must not shift.
_ITEM_ONE_B_TEXT_RE = re.compile(
    (r"(?i)Item\s{0,20}(?:1B|IB)\s{0,20}" + _ITEM_SEPARATOR
     + r"\s{0,20}Unresolved").encode()
)
_ITEM_TWO_TEXT_RE = re.compile(
    (r"(?i)Item\s{0,20}(?:2|II)\s{0,20}" + _ITEM_SEPARATOR
     + r"\s{0,20}Propert").encode()
)
_ITEM_ONE_B_ANCHOR = re.compile(r"(?i)item[_\-]?1b(?:[_\-]unresolved.*)?")
_ITEM_TWO_ANCHOR = re.compile(r"(?i)item[_\-]?(?:2|ii)(?:[_\-]propert.*)?")

BOUNDARY_ITEM_1A = "item_1a_risk_factors"
BOUNDARY_ITEM_1B = "item_1b_unresolved_staff_comments"
BOUNDARY_ITEM_2 = "item_2_properties"

#: End-boundary tiers in filing order. The first tier with exactly one
#: trustworthy candidate after the body heading wins.
END_BOUNDARY_PRIORITY: tuple[str, ...] = (
    BOUNDARY_ITEM_1A,
    BOUNDARY_ITEM_1B,
    BOUNDARY_ITEM_2,
)

_BOUNDARY_TEXT_RES = {
    BOUNDARY_ITEM_1A: _ITEM_ONE_A_TEXT_RE,
    BOUNDARY_ITEM_1B: _ITEM_ONE_B_TEXT_RE,
    BOUNDARY_ITEM_2: _ITEM_TWO_TEXT_RE,
}
_BOUNDARY_ANCHOR_RES = {
    BOUNDARY_ITEM_1A: _ITEM_ONE_A_ANCHOR,
    BOUNDARY_ITEM_1B: _ITEM_ONE_B_ANCHOR,
    BOUNDARY_ITEM_2: _ITEM_TWO_ANCHOR,
}
_AMBIGUOUS_END_BOUNDARY = "ambiguous_end_boundary"
_NO_END_BOUNDARY = "no_end_boundary"


def _text_offset_map(raw: bytes) -> tuple[bytes, list[int]]:
    """Tag- and entity-free text, plus each byte's raw offset.

    Markup and entities each collapse to one space, so a heading split across
    tags reads as ordinary words while every surviving byte still knows where it
    came from. The map is what lets a match in the text stream become a raw-byte
    span without a second, drifting notion of position.
    """
    text = bytearray()
    offsets: list[int] = []
    index = 0
    inside_tag = False
    while index < len(raw):
        byte = raw[index]
        if byte == 0x3C:  # "<"
            inside_tag = True
            index += 1
            continue
        if byte == 0x3E:  # ">"
            inside_tag = False
            text.append(0x20)
            offsets.append(index)
            index += 1
            continue
        if inside_tag:
            index += 1
            continue
        if byte == 0x26:  # "&"
            entity = _ENTITY_RE.match(raw, index)
            if entity is not None:
                text.append(0x20)
                offsets.append(index)
                index = entity.end()
                continue
        text.append(byte)
        offsets.append(index)
        index += 1
    return bytes(text), offsets


def _starts_a_block(raw: bytes, position: int) -> bool:
    """Does this match open a block, or sit inside a sentence?

    Everything between the preceding block close and the match must be markup or
    whitespace. This is what separates a section heading from a cross-reference:
    one filing carries seven inline ``see Part I, Item 1A Risk Factors`` phrases,
    and taking the first of them as the end anchor cuts the span from 104,132
    bytes to 58,046 -- a silent 44% loss of the section being extracted.
    """
    window_start = max(0, position - 4000)
    closes = list(_BLOCK_SPLIT_RE.finditer(raw, window_start, position))
    cursor = closes[-1].end() if closes else window_start
    between = _TAG_RE.sub(b"", raw[cursor:position])
    return _ENTITY_RE.sub(b" ", between).strip() == b""


def find_item_one_span(raw: bytes) -> tuple[int, int]:
    """Locate Item 1's byte span, by anchor when there is one and by heading
    text when there is not.

    Returns ``(start_offset, end_offset)`` suitable for any ``build_passages*``.

    **Anchors first, so the pinned chain keeps its exact span.** One of the
    fifteen measured filings carries ``id="item_i_business"`` and
    ``id="item_1a_risk_factors"``; that path is tried first and reproduces the
    span the HubSpot corpus was built from.

    **Then heading text.** The body heading is the *last* qualifying match
    rather than the first, because every filing lists Item 1 in its table of
    contents before printing it; and both ends must open a block, for the
    cross-reference reason in :func:`_starts_a_block`.

    Raises :class:`IngestionError` with ``item_span_not_found`` rather than
    guessing. A span this stage cannot locate is not one it should approximate.
    """
    if not isinstance(raw, (bytes, bytearray)):
        raise IngestionError(
            "normalization input must be raw bytes",
            reason_code="normalize_input_invalid",
        )
    raw = bytes(raw)

    anchors = [
        (match.group(1).decode("utf-8", errors="replace"), match.start())
        for match in _ITEM_ANCHOR_RE.finditer(raw)
    ]
    ones = [pos for name, pos in anchors if _ITEM_ONE_ANCHOR.fullmatch(name)]
    one_as = [pos for name, pos in anchors if _ITEM_ONE_A_ANCHOR.fullmatch(name)]
    if len(ones) == 1 and len(one_as) == 1 and ones[0] < one_as[0]:
        # The span opens at the ``>`` that closes the anchor's own tag and ends
        # where the next anchor's attribute begins, which is the convention the
        # pinned corpus was built with. Reproduced here rather than re-chosen:
        # a span one tag wider would move every offset in that chain.
        opening = raw.find(b">", ones[0])
        if opening < 0 or opening >= one_as[0]:
            raise IngestionError(
                "the Item 1 anchor is not closed before Item 1A",
                reason_code=_ITEM_SPAN_NOT_FOUND,
            )
        return opening, one_as[0]

    text, offsets = _text_offset_map(raw)
    starts = [
        offsets[m.start()]
        for m in _ITEM_ONE_TEXT_RE.finditer(text)
        if _starts_a_block(raw, offsets[m.start()])
    ]
    ends = [
        offsets[m.start()]
        for m in _ITEM_ONE_A_TEXT_RE.finditer(text)
        if _starts_a_block(raw, offsets[m.start()])
    ]
    if not starts or not ends:
        raise IngestionError(
            "no Item 1 heading pair was found in this document",
            reason_code=_ITEM_SPAN_NOT_FOUND,
        )
    body_start = max(starts)
    after = [end for end in ends if end > body_start]
    if not after:
        raise IngestionError(
            "the Item 1 heading is not followed by an Item 1A heading",
            reason_code=_ITEM_SPAN_NOT_FOUND,
        )

    # Back off to the enclosing tag boundaries so neither end cuts a tag.
    start_offset = raw.rfind(b">", 0, body_start)
    end_offset = raw.rfind(b"<", 0, min(after))
    if start_offset < 0 or end_offset <= start_offset:
        raise IngestionError(
            "the located Item 1 span is empty or inverted",
            reason_code=_ITEM_SPAN_NOT_FOUND,
        )
    return start_offset, end_offset


def find_item_one_span_v2(raw: bytes) -> tuple[int, int, str]:
    """Locate Item 1's byte span and name the boundary that ended it.

    ``find_item_one_span`` ends only at Item 1A, so a filing that omits risk
    factors — smaller reporting companies may — cannot be read at all. This
    successor keeps Item 1A as the first tier and then falls back in filing
    order, returning ``(start_offset, end_offset, end_boundary_kind)`` where
    the kind is one of :data:`END_BOUNDARY_PRIORITY`.

    Trustworthiness is not loosened to buy that reach. A candidate counts only
    if it **opens a block** (:func:`_starts_a_block`, the cross-reference
    guard) and lies **after the body heading**, and the body heading is the
    *last* qualifying Item 1 match, so a table of contents cannot supply it.
    Within a tier, two surviving candidates are **ambiguous and refuse** rather
    than silently taking the earlier one: unlike v1's ``min()``, a second
    block-opening Item 1A after the body is evidence the document is not
    shaped as assumed.

    Raises :class:`IngestionError` with ``item_span_not_found`` when Item 1
    itself cannot be located, ``ambiguous_end_boundary`` when a tier is
    ambiguous, and ``no_end_boundary`` when no tier yields a candidate.
    """
    if not isinstance(raw, (bytes, bytearray)):
        raise IngestionError(
            "normalization input must be raw bytes",
            reason_code="normalize_input_invalid",
        )
    raw = bytes(raw)

    # --- anchor path, when the filing carries ids --------------------------
    anchors = [
        (match.group(1).decode("utf-8", errors="replace"), match.start())
        for match in _ITEM_ANCHOR_RE.finditer(raw)
    ]
    ones = [pos for name, pos in anchors if _ITEM_ONE_ANCHOR.fullmatch(name)]
    if len(ones) == 1:
        for kind in END_BOUNDARY_PRIORITY:
            pattern = _BOUNDARY_ANCHOR_RES[kind]
            ends = [pos for name, pos in anchors if pattern.fullmatch(name)]
            after = [pos for pos in ends if pos > ones[0]]
            if not after:
                continue
            if len(after) > 1:
                raise IngestionError(
                    f"{len(after)} {kind} anchors follow Item 1",
                    reason_code=_AMBIGUOUS_END_BOUNDARY,
                )
            opening = raw.find(b">", ones[0])
            if opening < 0 or opening >= after[0]:
                raise IngestionError(
                    "the Item 1 anchor is not closed before its end boundary",
                    reason_code=_ITEM_SPAN_NOT_FOUND,
                )
            return opening, after[0], kind

    # --- heading-text path -------------------------------------------------
    text, offsets = _text_offset_map(raw)
    starts = [
        offsets[m.start()]
        for m in _ITEM_ONE_TEXT_RE.finditer(text)
        if _starts_a_block(raw, offsets[m.start()])
    ]
    if not starts:
        raise IngestionError(
            "no Item 1 heading was found in this document",
            reason_code=_ITEM_SPAN_NOT_FOUND,
        )
    body_start = max(starts)

    for kind in END_BOUNDARY_PRIORITY:
        candidates = [
            offsets[m.start()]
            for m in _BOUNDARY_TEXT_RES[kind].finditer(text)
            if _starts_a_block(raw, offsets[m.start()])
        ]
        after = [end for end in candidates if end > body_start]
        if not after:
            continue
        if len(after) > 1:
            raise IngestionError(
                f"{len(after)} block-opening {kind} headings follow Item 1; "
                "the end boundary is ambiguous",
                reason_code=_AMBIGUOUS_END_BOUNDARY,
            )
        start_offset = raw.rfind(b">", 0, body_start)
        end_offset = raw.rfind(b"<", 0, after[0])
        if start_offset < 0 or end_offset <= start_offset:
            raise IngestionError(
                "the located Item 1 span is empty or inverted",
                reason_code=_ITEM_SPAN_NOT_FOUND,
            )
        return start_offset, end_offset, kind

    raise IngestionError(
        "Item 1 is present but no trustworthy Item 1A, Item 1B or Item 2 "
        "boundary follows it",
        reason_code=_NO_END_BOUNDARY,
    )
