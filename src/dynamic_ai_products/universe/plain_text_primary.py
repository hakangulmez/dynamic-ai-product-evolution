"""Structural admission of a plain-text primary document (ADR-097).

Governing documents:
- docs/DECISION_LOG.md ADR-090 (filing-index route), ADR-092 (two-hop
  acquisition), ADR-096 (eligibility before cardinality), ADR-097 (this design)

A domestic annual filing may be filed as plain text rather than HTML — measured
on accession ``0000074925-22-000002``, whose Document Format Files table
declares Type ``10-K`` for exactly one row, ``10k2021.txt``. The HTML route
correctly refused it with ``non_html_primary``: a ``.txt`` is not HTML and may
not be treated as though it were. This module decides, from the fetched bytes
alone, whether such a candidate is a **single standalone annual report** that
may be admitted as a separate ``plain_text`` representation.

**Admission is positive evidence, never the absence of a marker.** Two
disjoint shapes are admissible and nothing else:

``single_sgml_document``
    Exactly one ``<DOCUMENT>`` block, whose ``<TYPE>`` equals the planned form
    and whose ``<FILENAME>`` equals the document the filing index selected.

``bare_text``
    No ``<DOCUMENT>`` wrapper at all, but a line-start ``FORM 10-K`` or
    ``FORM 10-KT`` matching the planned form **and** a line-start ``Item 1``
    heading. A file is never admitted merely because it lacks a wrapper: a
    full-submission archive, a press release, or an exhibit would all qualify
    under such a rule.

Everything else is a recorded refusal. A multi-document SEC submission is the
common case this must never accept, because it bundles the annual report with
its exhibits and there is no evidence here about which block is the report.

This module performs no network access, reads no clock, and parses no
cover-page, DEI or XBRL fact. It lives in ``universe`` because acquisition
calls it and ``universe`` may not import ``ingestion``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

#: The two admissible shapes. Recorded verbatim into the governed bundle and
#: acquisition manifest, so a reader never has to re-derive why a text source
#: was admitted.
ADMISSION_SINGLE_SGML = "single_sgml_document"
ADMISSION_BARE_TEXT = "bare_text"
ADMISSIONS = (ADMISSION_SINGLE_SGML, ADMISSION_BARE_TEXT)

REASON_MULTI_DOCUMENT = "multi_document_submission"
REASON_EMBEDDED_AMBIGUOUS = "embedded_document_ambiguous"
REASON_TYPE_MISMATCH = "text_type_mismatch"
REASON_UNSUPPORTED_STRUCTURE = "unsupported_text_structure"

TEXT_SUFFIXES = (".txt",)

_DOCUMENT_RE = re.compile(rb"<DOCUMENT>", re.I)
_TYPE_RE = re.compile(rb"^\s*<TYPE>\s*([^\r\n<]+)", re.I | re.M)
_FILENAME_RE = re.compile(rb"^\s*<FILENAME>\s*([^\r\n<]+)", re.I | re.M)
#: Line-start only: a form named inside a sentence is not a cover page.
_FORM_LINE_RE = re.compile(rb"^[ \t]*FORM\s+(10-KT|10-K)\b", re.I | re.M)
#: Line-start Item 1, deliberately not Item 1A/1B. The separator set matches
#: the heading grammar the normalizer already uses.
_ITEM_ONE_LINE_RE = re.compile(
    rb"^[ \t]*Item\s{0,20}1\s{0,20}(?:[.:\-]|\xe2\x80\x93|\xe2\x80\x94)?"
    rb"\s{0,20}(?:Business\b|$)",
    re.I | re.M,
)


@dataclass(frozen=True)
class TextAdmission:
    """Why a text candidate was admitted, or the reason it was not.

    ``admitted`` is the single question callers ask; the remaining fields are
    the evidence that answer rests on, and are persisted verbatim.
    """

    admitted: bool
    admission: Optional[str]
    document_blocks: int
    declared_type: Optional[str]
    declared_filename: Optional[str]
    reason_code: Optional[str] = None
    detail: Optional[str] = None


def is_plain_text_document(name: str) -> bool:
    """Is this selected document a plain-text candidate by suffix?"""
    return name.lower().endswith(TEXT_SUFFIXES)


def _decoded(match: Optional[re.Match]) -> Optional[str]:
    if match is None:
        return None
    return match.group(1).decode("utf-8", "replace").strip() or None


def inspect_plain_text_primary(
    raw: bytes, *, form: str, selected_document: str
) -> TextAdmission:
    """Decide admission from the fetched bytes, deterministically.

    Never consults the filename beyond the ``<FILENAME>`` agreement check, and
    never guesses which of several documents is the annual report.
    """
    if not isinstance(raw, (bytes, bytearray)):
        raise TypeError("plain-text admission input must be raw bytes")
    raw = bytes(raw)
    blocks = len(_DOCUMENT_RE.findall(raw))
    declared_type = _decoded(_TYPE_RE.search(raw))
    declared_filename = _decoded(_FILENAME_RE.search(raw))

    def refuse(reason: str, detail: str) -> TextAdmission:
        return TextAdmission(
            admitted=False, admission=None, document_blocks=blocks,
            declared_type=declared_type, declared_filename=declared_filename,
            reason_code=reason, detail=detail,
        )

    if blocks > 1:
        # The common full-submission shape. Which block is the annual report
        # is not evidence this module has, so it never guesses.
        types = [
            m.group(1).decode("utf-8", "replace").strip()
            for m in _TYPE_RE.finditer(raw)
        ]
        matching = [t for t in types if t.upper() == form.upper()]
        if len(matching) > 1:
            return refuse(
                REASON_EMBEDDED_AMBIGUOUS,
                f"{blocks} <DOCUMENT> blocks, {len(matching)} of them declaring "
                f"type {form!r} ({matching}); no evidence names the annual "
                "report among them.",
            )
        return refuse(
            REASON_MULTI_DOCUMENT,
            f"{blocks} <DOCUMENT> blocks (types {types}); a multi-document SEC "
            "submission is not a standalone annual report.",
        )

    if blocks == 1:
        if declared_type is None:
            return refuse(
                REASON_UNSUPPORTED_STRUCTURE,
                "the single <DOCUMENT> block declares no <TYPE>.",
            )
        if declared_type.upper() != form.upper():
            return refuse(
                REASON_TYPE_MISMATCH,
                f"the single <DOCUMENT> block declares type {declared_type!r}, "
                f"not the planned form {form!r}.",
            )
        if declared_filename is None:
            return refuse(
                REASON_UNSUPPORTED_STRUCTURE,
                "the single <DOCUMENT> block declares no <FILENAME>.",
            )
        if declared_filename != selected_document:
            return refuse(
                REASON_UNSUPPORTED_STRUCTURE,
                f"the block declares filename {declared_filename!r} but the "
                f"filing index selected {selected_document!r}.",
            )
        return TextAdmission(
            admitted=True, admission=ADMISSION_SINGLE_SGML,
            document_blocks=1, declared_type=declared_type,
            declared_filename=declared_filename,
        )

    # blocks == 0: admitted only on positive evidence, never on absence.
    forms = {
        m.group(1).decode("utf-8", "replace").strip().upper()
        for m in _FORM_LINE_RE.finditer(raw)
    }
    if form.upper() not in forms:
        return refuse(
            REASON_UNSUPPORTED_STRUCTURE,
            f"no <DOCUMENT> wrapper and no line-start 'FORM {form}' cover-page "
            f"line (found {sorted(forms) or 'none'}); absence of a wrapper is "
            "not evidence of an annual report.",
        )
    if not _ITEM_ONE_LINE_RE.search(raw):
        return refuse(
            REASON_UNSUPPORTED_STRUCTURE,
            f"a line-start 'FORM {form}' line is present but no line-start "
            "Item 1 heading follows it.",
        )
    return TextAdmission(
        admitted=True, admission=ADMISSION_BARE_TEXT, document_blocks=0,
        declared_type=None, declared_filename=None,
    )
