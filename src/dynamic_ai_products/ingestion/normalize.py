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
    "NORMALIZER_VERSION",
    "TRANSFORM_CHAIN",
    "build_passages",
    "normalize_span",
    "passage_id_for",
]

NORMALIZER_VERSION = "sec_html_item_span_v1"

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
