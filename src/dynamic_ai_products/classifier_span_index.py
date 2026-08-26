"""Deterministic sentence-span index for classifier evidence (ADR-132).

**Why this exists.** Through V2.4 the model returned the evidence quote as free
text, and three live calibrations showed what that costs: of ten diagnosed
quote failures, one dropped an invisible U+200B, four made small visible copy
errors, two spliced spans thousands of characters apart, one attributed a
correctly copied quote to the wrong passage, and one composed roughly 45% of
its own text. Five distinct failure classes, all of them downstream of the same
decision — letting a model type characters that are supposed to be a copy.

V2.5 removes the decision. The model selects a ``span_ref`` naming units this
module derived from the hash-bound packet, and the pipeline retrieves the text.
Four of the five classes become structurally unreachable; the fifth, selecting
the wrong span, still yields authentic packet text attached to a claim, which
is a judgement a human reviewer can make and not fabricated evidence.

**Rendering contract, not archival contract.** This module builds the menu the
model chooses from. It is deliberately *not* required to read a stored record:
each stored evidence item carries the resolved span's offsets into the
normalized passage text and a digest over the resolved text, so a later reader
re-derives the quote from the packet arithmetically. A regex and a Unicode
database are not dependencies a decade-old observation should carry.

**Losslessness is the safety property.** The units of a passage, joined by a
single space, reproduce that passage's normalized text exactly. The renderer
therefore inserts markers between spans of text it did not rewrite, and a test
asserts the identity over every passage of the real calibration corpus.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

__all__ = [
    "SPAN_INDEX_RELATIVE_PATH",
    "SPAN_REF_PATTERN",
    "PassageSpans",
    "ResolvedSpan",
    "SpanIndex",
    "SpanIndexError",
    "SpanIndexRules",
    "SpanSelectionError",
    "build_span_index",
    "load_span_index_rules",
    "normalize_passage_text",
    "render_passage_units",
    "segment_units",
    "verify_stored_span",
]

SPAN_INDEX_RELATIVE_PATH = "configs/universe_classifier_span_index_v1.yaml"

#: The only shape a model may return. Anchored, so nothing else parses.
SPAN_REF_PATTERN = r"^P[0-9]{3}:S[0-9]{3}(-S[0-9]{3})?$"
_SPAN_REF_RE = re.compile(SPAN_REF_PATTERN)


class SpanIndexError(ValueError):
    """The span-index config or a packet is unusable. Never repaired."""


class SpanSelectionError(ValueError):
    """A model selection is not a resolvable span.

    ``reason_code`` is one of the bounded codes the runner records:
    ``span_reference_unresolvable`` for anything structurally wrong, and
    ``span_exceeds_stored_bound`` for a well-formed span whose resolved text is
    longer than the contract stores. The second is kept separate because it is
    a different fact about the run: the model selected a real, contiguous span
    and the pipeline declined to store it, which is not a model error.
    """

    def __init__(self, reason_code: str, detail: str):
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail


@dataclass(frozen=True)
class SpanIndexRules:
    """The pinned segmentation contract, with the digest a grant binds."""

    version: str
    sha256: str
    pattern: str
    abbreviations: tuple[str, ...]
    ordinal_width: int
    max_units_per_passage: int
    max_resolved_characters: int


@dataclass(frozen=True)
class PassageSpans:
    """One passage's units and their offsets into its normalized text."""

    passage_ref: str
    passage_id: str
    normalized: str
    units: tuple[str, ...]
    #: ``(start, end)`` per unit, as offsets into ``normalized``.
    offsets: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class SpanIndex:
    """Every displayed passage of one packet, segmented under one rule set."""

    rules: SpanIndexRules
    passages: dict[str, PassageSpans]


@dataclass(frozen=True)
class ResolvedSpan:
    """What the pipeline stores for one model selection. The model wrote none of it."""

    span_ref: str
    passage_ref: str
    text: str
    start: int
    end: int
    sha256: str


def normalize_passage_text(text: str) -> str:
    """Collapse whitespace runs to a single space and strip.

    Identical to the normalization the classifier has always used for quote
    resolution, so V2.5 introduces no second notion of "the same text".
    """
    return " ".join(text.split())


def load_span_index_rules(repo_root: str | Path) -> SpanIndexRules:
    """Load and validate the pinned span-index config."""
    path = Path(repo_root) / SPAN_INDEX_RELATIVE_PATH
    if not path.is_file():
        raise SpanIndexError(f"Span index config not found: {path}")
    raw = path.read_bytes()
    config = yaml.safe_load(raw.decode("utf-8"))
    if not isinstance(config, dict):
        raise SpanIndexError("The span index config is not a mapping.")
    version = config.get("span_index_version")
    if not isinstance(version, str) or not version:
        raise SpanIndexError("The span index config declares no version.")
    boundary = config.get("sentence_boundary")
    if not isinstance(boundary, dict) or not isinstance(boundary.get("pattern"), str):
        raise SpanIndexError("The span index config declares no boundary pattern.")
    abbreviations = config.get("abbreviations")
    if not isinstance(abbreviations, list) or not abbreviations:
        raise SpanIndexError("The span index config declares no abbreviation list.")
    ordinals = config.get("ordinals") or {}
    selection = config.get("selection") or {}
    width = ordinals.get("width")
    if width != 3:
        raise SpanIndexError(
            f"This module implements three-digit ordinals; the config asks for "
            f"{width!r}. A width change renumbers every span id and is a "
            "successor decision, not a config tweak."
        )
    try:
        compiled = re.compile(boundary["pattern"])
    except re.error as exc:
        raise SpanIndexError(f"The boundary pattern does not compile: {exc}") from exc
    # Every declared abbreviation must actually be suppressed by the pattern,
    # so the list cannot drift away from the regex that implements it.
    for abbreviation in abbreviations:
        # The lookbehind applies at the position after the terminator, so an
        # abbreviation is only suppressed if the pattern spells it with its own
        # period. Probing here is what caught that during ADR-132 implementation.
        probe = f"Alpha {abbreviation}. Beta gamma."
        if compiled.search(probe):
            raise SpanIndexError(
                f"The pattern splits after declared abbreviation {abbreviation!r}; "
                "the list and the pattern disagree."
            )
    return SpanIndexRules(
        version=version,
        sha256=hashlib.sha256(raw).hexdigest(),
        pattern=boundary["pattern"],
        abbreviations=tuple(abbreviations),
        ordinal_width=3,
        max_units_per_passage=int(ordinals.get("max_units_per_passage", 999)),
        max_resolved_characters=int(selection.get("max_resolved_characters", 2000)),
    )


def segment_units(text: str, rules: SpanIndexRules) -> tuple[str, tuple[str, ...]]:
    """Segment one passage. Returns the normalized text and its units.

    The units, joined by a single space, equal the normalized text exactly. A
    passage with no boundary is one unit; an empty passage has none.
    """
    normalized = normalize_passage_text(text)
    if not normalized:
        return "", ()
    units = tuple(part for part in re.split(rules.pattern, normalized) if part)
    if not units:
        units = (normalized,)
    if " ".join(units) != normalized:
        raise SpanIndexError(
            "Segmentation is not lossless for this passage; the units do not "
            "rejoin to the normalized text. Refusing rather than rendering a "
            "menu that misrepresents the source."
        )
    return normalized, units


def build_span_index(packet: dict, rules: SpanIndexRules) -> SpanIndex:
    """Segment every displayed passage of one packet under one rule set."""
    from .human_review_overlay import passage_refs

    refs = passage_refs(packet)
    by_id = {passage["passage_id"]: passage for passage in packet["passages"]}
    passages: dict[str, PassageSpans] = {}
    for ref in sorted(refs):
        passage = by_id[refs[ref]]
        normalized, units = segment_units(passage["text"], rules)
        if len(units) > rules.max_units_per_passage:
            raise SpanIndexError(
                f"Passage {ref} segments into {len(units)} units, above the "
                f"{rules.max_units_per_passage} a three-digit ordinal can name. "
                "Refusing rather than renumbering."
            )
        offsets, cursor = [], 0
        for unit in units:
            offsets.append((cursor, cursor + len(unit)))
            cursor += len(unit) + 1
        passages[ref] = PassageSpans(
            passage_ref=ref, passage_id=passage["passage_id"], normalized=normalized,
            units=units, offsets=tuple(offsets))
    return SpanIndex(rules=rules, passages=passages)


def render_passage_units(spans: PassageSpans) -> str:
    """Render one passage as numbered units.

    The source text appears exactly once. Markers are inserted between units the
    segmenter derived from that same text; nothing is duplicated or rewritten.
    """
    return "\n".join(f"[S{ordinal:03d}] {unit}"
                     for ordinal, unit in enumerate(spans.units, start=1))


def _parse(span_ref: str) -> tuple[str, int, int]:
    if not isinstance(span_ref, str) or not _SPAN_REF_RE.match(span_ref):
        raise SpanSelectionError(
            "span_reference_unresolvable",
            f"{span_ref!r} is not a span reference of the form Pnnn:Snnn or "
            "Pnnn:Snnn-Snnn.")
    passage_ref, ordinals = span_ref.split(":", 1)
    parts = ordinals.split("-")
    first = int(parts[0][1:])
    last = int(parts[1][1:]) if len(parts) == 2 else first
    return passage_ref, first, last


def resolve_span(span_ref: str, passage_ref: str, index: SpanIndex) -> ResolvedSpan:
    """Resolve one model selection to exact packet text, or refuse it.

    ``passage_ref`` is the model's own redundant field. It is checked against
    the span reference's own prefix rather than ignored: an item whose two
    references disagree is a different defect from one that names a passage the
    packet does not display, and a reader deserves to be told which.
    """
    named, first, last = _parse(span_ref)
    if passage_ref != named:
        raise SpanSelectionError(
            "span_reference_unresolvable",
            f"Evidence names passage_ref {passage_ref!r} but span_ref {span_ref!r} "
            "cites a different passage; the two disagree.")
    spans = index.passages.get(named)
    if spans is None:
        raise SpanSelectionError(
            "span_reference_unresolvable",
            f"{span_ref} cites {named}, which this packet does not display.")
    if first < 1 or last < 1:
        raise SpanSelectionError(
            "span_reference_unresolvable",
            f"{span_ref} names ordinal 0; units are numbered from 1.")
    if last < first:
        raise SpanSelectionError(
            "span_reference_unresolvable",
            f"{span_ref} runs backwards; a span is a contiguous run in reading order.")
    if last > len(spans.units):
        raise SpanSelectionError(
            "span_reference_unresolvable",
            f"{span_ref} names unit S{last:03d}, but {named} holds "
            f"{len(spans.units)} unit(s).")
    start = spans.offsets[first - 1][0]
    end = spans.offsets[last - 1][1]
    text = spans.normalized[start:end]
    if not (0 <= start < end <= len(spans.normalized)):
        raise SpanSelectionError(
            "span_reference_unresolvable",
            f"{span_ref} resolves to offsets outside its passage.")
    expected = " ".join(spans.units[first - 1:last])
    if text != expected:
        raise SpanSelectionError(
            "span_reference_unresolvable",
            f"{span_ref} does not round-trip: the text at its offsets is not the "
            "run of units it names.")
    if len(text) > index.rules.max_resolved_characters:
        raise SpanSelectionError(
            "span_exceeds_stored_bound",
            f"{span_ref} resolves to {len(text)} characters, above the "
            f"{index.rules.max_resolved_characters} the record contract stores. "
            "The span is real and contiguous; it is refused rather than "
            "truncated, because a truncated quote is not the span the model "
            "selected.")
    return ResolvedSpan(
        span_ref=span_ref, passage_ref=named, text=text, start=start, end=end,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())


def verify_stored_span(item: dict, packet: dict) -> bool:
    """Re-derive one stored evidence item from the packet alone.

    This is the archival proof, and it deliberately takes a **packet**, not a
    :class:`SpanIndex`. It needs no config, no rule set and no regex: it maps the
    stored ``passage_ref`` through the deterministic reference mapping,
    normalizes that one raw passage with the established whitespace rule, and
    then checks three things — that the offsets are in range, that the text at
    them is exactly ``resolved_quote``, and that its digest is ``span_sha256``.

    ``span_ref`` is not parsed here, and that is the point. The reference was the
    model's selection and was validated when the response arrived; what survives
    into the archive as proof is the offsets and the digest. An earlier revision
    of this module verified through a rebuilt span index, which quietly made
    every stored row depend on the very segmenter it was supposed to outlive.
    """
    from .human_review_overlay import passage_refs

    refs = passage_refs(packet)
    passage_id = refs.get(item.get("passage_ref"))
    if passage_id is None:
        return False
    passage = next((p for p in packet["passages"]
                    if p["passage_id"] == passage_id), None)
    if passage is None:
        return False
    normalized = normalize_passage_text(passage["text"])
    start, end = item.get("span_start"), item.get("span_end")
    if isinstance(start, bool) or isinstance(end, bool):
        return False
    if not isinstance(start, int) or not isinstance(end, int):
        return False
    if not (0 <= start < end <= len(normalized)):
        return False
    text = normalized[start:end]
    if text != item.get("resolved_quote"):
        return False
    return hashlib.sha256(text.encode("utf-8")).hexdigest() == item.get("span_sha256")
