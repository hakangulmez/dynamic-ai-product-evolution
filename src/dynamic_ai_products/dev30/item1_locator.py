"""Dev30-only Item 1 span locator (dev30-item1-marker-v1).

Locates the Item 1 span inside one legacy Dev30 filing text and derives its
provenance fields. The rule is exact and was proven against all 30 committed
PCT_Dev30_v0 rows before this module was written: every span starts and ends
with a single boundary newline (the marker *text* is excluded, the adjacent
newline on each side is included), and every span's word count reproduces
the legacy corpus's own ``item1_words`` figure exactly. Nothing here strips,
collapses whitespace in, converts line endings within, or Unicode-normalizes
the decoded text before indexing or hashing it -- the slice is used exactly
as decoded.

This rule is Dev30-corpus-specific and is not proposed as, and must never be
generalized into, the Stage 00C SEC primary-document locator. Nothing here
constructs or accepts a Stage 00C ``source_id``
(``sec-primary:<cik>:<accession>:<selected_document>``); the identity this
module produces is ``legacy_source_id``
(``legacy-item1:dev30-v0:<source_text_hash>``), a distinct, content-addressed
namespace that is never interchangeable with it.

This module performs no I/O of its own: it operates on bytes the caller
already holds. It makes no network request and calls no model.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

__all__ = [
    "ITEM_ONE_LOCATOR_VERSION",
    "REASON_UTF8_DECODE_FAILED",
    "REASON_MISSING_MARKER",
    "REASON_DUPLICATE_MARKER",
    "REASON_REVERSED_OR_EMPTY_BOUNDARY",
    "Item1LocatorError",
    "LocatedItem1Span",
    "locate_item1_span",
]

#: Fixed code literal. A future rule change mints a new version string; this
#: one never changes meaning underneath itself.
ITEM_ONE_LOCATOR_VERSION = "dev30-item1-marker-v1"

_MARK_ITEM_1 = "### ITEM_1_START ###"
_MARK_ITEM_1A = "### ITEM_1A_START ###"

REASON_UTF8_DECODE_FAILED = "utf8_decode_failed"
REASON_MISSING_MARKER = "missing_marker"
REASON_DUPLICATE_MARKER = "duplicate_marker"
REASON_REVERSED_OR_EMPTY_BOUNDARY = "reversed_or_empty_boundary"

_REASONS = frozenset(
    {
        REASON_UTF8_DECODE_FAILED,
        REASON_MISSING_MARKER,
        REASON_DUPLICATE_MARKER,
        REASON_REVERSED_OR_EMPTY_BOUNDARY,
    }
)


class Item1LocatorError(Exception):
    """Refused to locate an Item 1 span. ``reason`` is one of the four
    module-level ``REASON_*`` constants -- never a fifth value, never a
    silently repaired fallback."""

    def __init__(self, reason: str, message: str):
        if reason not in _REASONS:
            raise ValueError(f"not a recognized locator reason code: {reason!r}")
        self.reason = reason
        super().__init__(message)


@dataclass(frozen=True)
class LocatedItem1Span:
    """The located span plus its four provenance fields.

    ``item_one_char_start``/``item_one_char_end`` are character offsets into
    the full decoded filing string (before slicing), not into the span
    itself. ``source_text_hash`` and the hash embedded in
    ``legacy_source_id`` are the same value, same input, same algorithm --
    never independently computed.
    """

    span_text: str
    item_one_char_start: int
    item_one_char_end: int
    source_text_hash: str
    legacy_source_id: str


def locate_item1_span(raw_bytes: bytes) -> LocatedItem1Span:
    """Locate the Item 1 span in one legacy Dev30 filing's raw bytes.

    Decodes with ``raw_bytes.decode("utf-8", errors="strict")`` only -- no
    text-mode API, no newline translation. Requires exactly one occurrence
    each of the two literal markers; requires the resulting boundary to be
    non-empty and correctly ordered. Refuses via :class:`Item1LocatorError`
    on any violation rather than guessing or falling back.
    """
    try:
        text = raw_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise Item1LocatorError(
            REASON_UTF8_DECODE_FAILED,
            f"raw bytes did not decode as strict UTF-8: {exc}",
        ) from exc

    count_1 = text.count(_MARK_ITEM_1)
    count_1a = text.count(_MARK_ITEM_1A)

    if count_1 == 0 or count_1a == 0:
        raise Item1LocatorError(
            REASON_MISSING_MARKER,
            f"expected one {_MARK_ITEM_1!r} and one {_MARK_ITEM_1A!r}; "
            f"found {count_1} and {count_1a}",
        )
    if count_1 > 1 or count_1a > 1:
        raise Item1LocatorError(
            REASON_DUPLICATE_MARKER,
            f"expected exactly one occurrence of each marker; "
            f"found {count_1} of {_MARK_ITEM_1!r} and {count_1a} of "
            f"{_MARK_ITEM_1A!r}",
        )

    start = text.index(_MARK_ITEM_1) + len(_MARK_ITEM_1)
    end = text.index(_MARK_ITEM_1A)
    if not (end > start):
        raise Item1LocatorError(
            REASON_REVERSED_OR_EMPTY_BOUNDARY,
            f"computed boundary is not a positive-length span: "
            f"start={start}, end={end}",
        )

    span_text = text[start:end]
    source_text_hash = hashlib.sha256(span_text.encode("utf-8")).hexdigest()
    legacy_source_id = f"legacy-item1:dev30-v0:{source_text_hash}"

    return LocatedItem1Span(
        span_text=span_text,
        item_one_char_start=start,
        item_one_char_end=end,
        source_text_hash=source_text_hash,
        legacy_source_id=legacy_source_id,
    )
