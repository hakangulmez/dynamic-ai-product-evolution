"""Deterministic provider-contents materialization (ADR-036, E-R).

**Why this module exists.** Before E-R the run sent `contents=request.prompt_text`
and the packet payload was never transmitted at all, so a live call handed the
model a frozen template still carrying literal `{{company_name}}`,
`{{cutoff}}` and `{{passages_with_ids}}` markers — no company identity, no
observation cutoff and no passages. The packet was metered and persisted but not
sent. This module closes that gap.

**One representation, not two.** The renderer emits a single canonical UTF-8
text document. Those exact bytes are what the connector sends as `contents` and
what the run persists, so "what was archived" and "what was sent" are the same
object rather than two views that can drift.

**The frozen prompt keeps its own identity.** `prompt_sha256` remains the digest
of the raw template bytes; the rendered document carries a separate
`rendered_contents_sha256`. Substitution never rewrites a prompt file.

**Binding is a closed, stage-scoped map.** A placeholder the map does not name is
refused rather than left in place or guessed. Only ``product_extraction`` is
materializable in E-R. ``capability_extraction`` happens to carry no placeholders
and ``task_extraction`` carries four unbound ones, but neither difference matters:
both need governed parent materialization that E-S supplies, so **both** fail
closed with ``contents_placeholder_unbound``. Rendering a placeholder-free
capability prompt verbatim would send an instruction naming no products at all.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from .errors import ExtractionError

__all__ = [
    "MARKER_FRAGMENTS",
    "MATERIALIZATION_SUPPORTED_STAGES",
    "PASSAGE_REF_PATTERN",
    "PLACEHOLDER_PATTERN",
    "RENDERER_VERSION",
    "STAGE_PLACEHOLDER_BINDINGS",
    "canonical_passage_order",
    "passage_ref_label",
    "render_provider_contents",
]

RENDERER_VERSION = "extraction_contents_renderer_v1"

# Only lowercase ASCII words, so the scan cannot be fooled by a marker that
# merely looks similar. The pattern is used both to bind and to re-scan.
PLACEHOLDER_PATTERN = re.compile(r"\{\{([a-z_]+)\}\}")

# The lowercase pattern alone is not enough. ``{{UPPER}}``, ``{{ company_name }}``
# and ``{{foo-bar}}`` are all invisible to it, so a template carrying any of them
# would have shipped its markers to the model. After substitution the rule is
# therefore **total**: any residual literal brace pair fails closed, whether or
# not it looks like a placeholder this module could ever have bound.
MARKER_FRAGMENTS: tuple[str, ...] = ("{{", "}}")

# E-R materializes only the product stage. The capability and task stages need
# governed parent materialization that E-S supplies, so they fail closed here
# rather than rendering a prompt that cannot carry their parent context.
MATERIALIZATION_SUPPORTED_STAGES: tuple[str, ...] = ("product_extraction",)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_PASSAGE_SEPARATOR = "\n"


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExtractionError(
            f"{what} must be a non-blank string",
            reason_code="contents_context_invalid",
        )
    return value


def _bind_company_name(packet: dict[str, Any]) -> str:
    """The legal name, which only an ``@0.2.0`` packet carries.

    A ``@0.1.0`` packet has no name field at all, so rendering one is refused
    rather than filled with the CIK: a company identifier is not a legal name.
    """
    value = packet.get("legal_name")
    if value is None:
        raise ExtractionError(
            "the packet carries no legal_name; extraction_input_packet@0.2.0 with a "
            "hydrated company-identity pin is required to render this prompt",
            reason_code="company_identity_pin_required",
        )
    return _require_str(value, "legal_name")


def _bind_cutoff(packet: dict[str, Any]) -> str:
    return _require_str(packet.get("observation_cutoff_date"), "observation_cutoff_date")


# ADR-055. A short positional label per rendered passage.
#
# Measured twice, on two independent live calls: the model dropped eight
# characters from the middle of a 32-character ``passage_id`` and reproduced the
# identical corruption both times -- first eighteen characters right, last six
# right, ``d38ea749`` collapsed to ``82``. Copying a long opaque hex string is
# not something a language model does reliably, and ``source_id`` is 49
# characters of the same material. So the model is no longer asked to transcribe
# either: it cites a short label and the pipeline resolves it, which is the rule
# ``candidate_id`` and the ADR-054 identity fields already follow.
#
# Three digits are a floor, not a cap: a packet with more than 999 passages
# yields ``P1000``, which the grammar still accepts. Labels are one-based
# because they are read by a human and by a model, not used as an index.
PASSAGE_REF_PATTERN = re.compile(r"^P(\d{3,})$")


def passage_ref_label(ordinal: int) -> str:
    """The label for a one-based position in the canonical order."""
    return f"P{ordinal:03d}"


def canonical_passage_order(packet: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Every admissible passage, in the one order the renderer emits.

    **The single sorter.** Ordering is by ``(source_id, passage_id)`` so the same
    packet always renders the same bytes regardless of the order the passages
    arrived in -- which means a packet's own list order is *not* the render
    order. Measured on the pilot packet: 121 of 124 positions differ between the
    two. A resolver that indexed the packet's list would therefore attach almost
    every quote to the wrong passage, and nothing downstream would notice,
    because every position it named would be a real one.

    That failure is silent, so it is closed structurally: this function is the
    only place the order is decided, and both the renderer and the evidence
    resolver call it. Two ``sorted`` calls that happen to agree today would be a
    rule living in two places.
    """
    passages = packet.get("passages")
    if not isinstance(passages, list) or not passages:
        raise ExtractionError(
            "rendering requires at least one admissible passage",
            reason_code="contents_context_invalid",
        )
    rows: list[tuple[str, str, dict[str, Any]]] = []
    for passage in passages:
        if not isinstance(passage, dict):
            raise ExtractionError(
                "each passage must be a mapping", reason_code="contents_context_invalid"
            )
        passage_id = _require_str(passage.get("passage_id"), "passage_id")
        source_id = _require_str(passage.get("source_id"), "source_id")
        _require_str(passage.get("text"), "passage text")
        published = _require_str(passage.get("publication_date"), "publication_date")
        if not _DATE_RE.fullmatch(published):
            raise ExtractionError(
                "publication_date must be YYYY-MM-DD",
                reason_code="contents_context_invalid",
            )
        rows.append((source_id, passage_id, passage))

    if len({(source_id, passage_id) for source_id, passage_id, _ in rows}) != len(rows):
        raise ExtractionError(
            "passages must be unique by (source_id, passage_id)",
            reason_code="contents_context_invalid",
        )
    # Sorted on the identity pair only. The passage mapping never participates in
    # the comparison, so two passages can never be ordered by their text.
    return tuple(passage for _, _, passage in sorted(rows, key=lambda row: row[:2]))


def _bind_passages_with_ids(packet: dict[str, Any]) -> str:
    """Every admissible passage, in canonical order with explicit delimiters.

    Offsets are deliberately omitted: they are provenance the manifest already
    binds, and they would only spend input tokens.

    ``publication_date`` is required and appears in every header. A dated quote is
    what makes a claim checkable against the observation cutoff (CLAUDE.md rule
    5), and the value is the **authoritative** one the packet builder copied from
    ``document_publication_dates``, never a date a caller attached to a passage.

    ``passage_id`` and ``source_id`` stay in the header even though the model is
    no longer asked to copy them: a rendered document is an audit artifact, and a
    human reading it must be able to reach the underlying passage without
    recomputing the label.
    """
    blocks = [
        f"[ref: {passage_ref_label(ordinal)}] "
        f"[passage_id: {passage['passage_id']}] "
        f"[source_id: {passage['source_id']}] "
        f"[publication_date: {passage['publication_date']}]\n{passage['text']}"
        for ordinal, passage in enumerate(canonical_passage_order(packet), start=1)
    ]
    return _PASSAGE_SEPARATOR.join(blocks)


# Closed, stage-scoped binding map. A stage absent from this map cannot render,
# and a placeholder absent from its stage's entry is refused.
STAGE_PLACEHOLDER_BINDINGS: dict[str, dict[str, Callable[[dict[str, Any]], str]]] = {
    "product_extraction": {
        "company_name": _bind_company_name,
        "cutoff": _bind_cutoff,
        "passages_with_ids": _bind_passages_with_ids,
    },
    # Both entries are empty and neither stage is materializable: the
    # MATERIALIZATION_SUPPORTED_STAGES gate above refuses them before any binding
    # is consulted, so an empty map here never means "render verbatim". The
    # capability prompt carries no markers and task_discovery_recall carries four;
    # that difference is irrelevant, because both need the governed parent
    # materialization E-S supplies.
    "capability_extraction": {},
    "task_extraction": {},
}


def render_provider_contents(
    *, stage: str, prompt_text: str, packet: dict[str, Any]
) -> str:
    """Materialize the exact document the provider will receive.

    Pure: no clock, no network, no filesystem, no prompt-file write. Refuses
    before the caller has created anything, so an unresolvable prompt costs no
    artifact.
    """
    if stage not in STAGE_PLACEHOLDER_BINDINGS:
        raise ExtractionError(
            f"no contents binding is declared for stage {stage!r}",
            reason_code="contents_stage_unsupported",
        )
    if stage not in MATERIALIZATION_SUPPORTED_STAGES:
        # A placeholder-free prompt is not the same as a materializable one: the
        # capability and task stages need parent context that no binding here can
        # supply, so rendering them verbatim would send an instruction with no
        # products and no capabilities. E-C and E-D stay blocked until E-S.
        raise ExtractionError(
            f"stage {stage!r} has no governed parent materialization until E-S",
            reason_code="contents_placeholder_unbound",
        )
    if not isinstance(prompt_text, str) or not prompt_text.strip():
        raise ExtractionError(
            "prompt text must be a non-blank string", reason_code="prompt_invalid"
        )
    if not isinstance(packet, dict):
        raise ExtractionError(
            "the packet must be a mapping", reason_code="contents_context_invalid"
        )

    bindings = STAGE_PLACEHOLDER_BINDINGS[stage]
    requested = [match.group(1) for match in PLACEHOLDER_PATTERN.finditer(prompt_text)]
    unbound = sorted({name for name in requested if name not in bindings})
    if unbound:
        raise ExtractionError(
            f"prompt requires placeholders this stage does not bind: {unbound}",
            reason_code="contents_placeholder_unbound",
        )

    # Values are resolved once each, so a placeholder repeated in the template
    # cannot render two different substitutions.
    resolved = {name: bindings[name](packet) for name in sorted(set(requested))}
    rendered = PLACEHOLDER_PATTERN.sub(lambda m: resolved[m.group(1)], prompt_text)

    # Fail closed on anything the substitution left behind, including a marker
    # introduced by a substituted value itself. The check is on the literal brace
    # fragments rather than the lowercase pattern, so an uppercase, spaced,
    # hyphenated or unmatched marker cannot slip through unrecognized.
    present = [fragment for fragment in MARKER_FRAGMENTS if fragment in rendered]
    if present:
        raise ExtractionError(
            f"rendered contents still carry literal markers: {present}",
            reason_code="contents_placeholder_unresolved",
        )
    if not rendered.strip():
        raise ExtractionError(
            "rendered contents are blank", reason_code="contents_context_invalid"
        )
    return rendered
