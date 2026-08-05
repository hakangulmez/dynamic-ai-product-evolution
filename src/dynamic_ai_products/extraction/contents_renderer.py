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
refused rather than left in place or guessed.

**Two stages materialize (ADR-058, E-S1).** ``product_extraction`` has since
E-R. ``capability_extraction`` joins it now, because the thing it was waiting
for exists: a human-validated Snapshot A, reconciled by the packet builder and
handed here as ``parent_context.product_parents``. Before that there was no
governed parent context to render, and rendering the placeholder-free capability
prompt verbatim would have sent an instruction naming no products at all.

``task_extraction`` still fails closed with ``contents_placeholder_unbound``: it
needs Snapshot B, which does not exist yet. Its map stays empty, and the
materialization gate refuses it before any binding is consulted — so an empty map
never means "render verbatim".
"""

from __future__ import annotations

import re
from typing import Any, Callable

from .errors import ExtractionError

__all__ = [
    "MARKER_FRAGMENTS",
    "MATERIALIZATION_SUPPORTED_STAGES",
    "PARENT_REF_PATTERN",
    "PASSAGE_REF_PATTERN",
    "PLACEHOLDER_PATTERN",
    "RENDERER_VERSION",
    "STAGE_PLACEHOLDER_BINDINGS",
    "STAGE_REQUIRED_PLACEHOLDERS",
    "canonical_passage_order",
    "parent_ref_label",
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

# E-S1 adds the capability stage. It became materializable the moment a real
# Snapshot A existed: the packet builder already reconciles A and hands the
# renderer ``parent_context.product_parents``, so there is now governed parent
# context to render. ``task_extraction`` still fails closed -- it needs Snapshot
# B, which does not exist yet.
MATERIALIZATION_SUPPORTED_STAGES: tuple[str, ...] = (
    "product_extraction",
    "capability_extraction",
)

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


# ADR-058 (E-S1). The parent-product label, one per validated product.
#
# ``A`` for Snapshot A, so a reader never confuses it with a passage ``P``
# label. Same rule as ADR-055: the model is shown what it needs to reason with
# and is never asked to transcribe a long identifier -- here
# ``product_observation_id``, which is 44 characters of colon-joined slug.
PARENT_REF_PATTERN = re.compile(r"^A(\d{2,})$")


def parent_ref_label(ordinal: int) -> str:
    """The label for a one-based position in the parent-product order."""
    return f"A{ordinal:02d}"


def _bind_validated_products(packet: dict[str, Any]) -> str:
    """The human-validated products, labelled, in the packet's own order.

    **No second sorter.** ``parent_context.product_parents`` is already ordered
    by ``derive_parent_context`` -- ascending ``(observation_id, reference)`` --
    and every entry there was re-read and hash-verified against a Snapshot A
    member before it arrived. This function labels that sequence and renders it;
    it does not choose an order, exactly as ``_bind_passages_with_ids`` defers to
    ``canonical_passage_order``.

    **A deliberate subset, not the payload.** Three fields per product:
    ``product_name``, and ``product_family``/``entity_type`` when present. What
    is left out matters more than what is kept:

    - ``evidence`` -- measured at 64% of the full payload, and it is the *same*
      text the model already receives under ``{{passages_with_ids}}``. Showing it
      twice under two different labels invites the model to quote from the block
      that carries no ``P0NN`` ref, reopening the citation defect ADR-055 closed.
    - ``product_observation_id`` -- 44 characters whose transcription is the
      exact thing the ``A0N`` label exists to avoid.
    - ``availability_status`` -- a capability judges its own availability from
      evidence. Showing the parent's would bias that judgement rather than
      inform it.

    Measured on the pilot Snapshot A: 1,197 characters instead of 14,528.
    """
    context = packet.get("parent_context")
    if not isinstance(context, dict):
        raise ExtractionError(
            "the capability stage requires parent context",
            reason_code="contents_context_invalid",
        )
    parents = context.get("product_parents")
    if not isinstance(parents, list) or not parents:
        raise ExtractionError(
            "rendering requires at least one validated product",
            reason_code="contents_context_invalid",
        )
    blocks: list[str] = []
    for ordinal, parent in enumerate(parents, start=1):
        if not isinstance(parent, dict) or not isinstance(parent.get("payload"), dict):
            raise ExtractionError(
                "each parent product must carry its verified payload",
                reason_code="contents_context_invalid",
            )
        payload = parent["payload"]
        name = _require_str(payload.get("product_name"), "product_name")
        header = f"[ref: {parent_ref_label(ordinal)}]"
        for field in ("product_family", "entity_type"):
            value = payload.get(field)
            if value is not None:
                header += f" [{field}: {_require_str(value, field)}]"
        blocks.append(f"{header}\n{name}")
    return _PASSAGE_SEPARATOR.join(blocks)


# Closed, stage-scoped binding map. A stage absent from this map cannot render,
# and a placeholder absent from its stage's entry is refused.
STAGE_PLACEHOLDER_BINDINGS: dict[str, dict[str, Callable[[dict[str, Any]], str]]] = {
    "product_extraction": {
        "company_name": _bind_company_name,
        "cutoff": _bind_cutoff,
        "passages_with_ids": _bind_passages_with_ids,
    },
    # ADR-058 (E-S1). The capability stage binds the same three the product
    # stage does, plus the validated products it attributes capabilities to.
    # ``validated_products`` is deliberately not offered to the product stage:
    # that stage has no parents, and a placeholder a stage cannot legitimately
    # fill has no business in its map.
    "capability_extraction": {
        "company_name": _bind_company_name,
        "cutoff": _bind_cutoff,
        "passages_with_ids": _bind_passages_with_ids,
        "validated_products": _bind_validated_products,
    },
    # Still empty and still not materializable: the
    # MATERIALIZATION_SUPPORTED_STAGES gate refuses this stage before any binding
    # is consulted, so the empty map never means "render verbatim". The task
    # stage needs Snapshot B, which does not exist yet.
    "task_extraction": {},
}

# ADR-058. Placeholders a stage's prompt **must** use, not merely may.
#
# Found by running the change: enabling the capability stage removed the gate
# that had been stopping a placeholder-free capability prompt, and a live run
# then reached the provider carrying an instruction that named no products at
# all. That was the exact hazard the old E-R docstring warned about; making the
# stage materializable is what took the accidental guard away.
#
# So the guard is made deliberate and narrow. Parent context is the *reason*
# this stage became materializable: ``capability_observation@0.1.0`` requires
# ``product_observation_id``, so a capability extracted without its parents is
# attributable to nothing. A prompt that ignores them cannot produce a
# conforming record, and a paid call that cannot conform should not be made.
#
# The product stage requires nothing here: its three placeholders are used by
# its prompt, but none of them is load-bearing in this way.
STAGE_REQUIRED_PLACEHOLDERS: dict[str, tuple[str, ...]] = {
    "capability_extraction": ("validated_products",),
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
    missing = sorted(set(STAGE_REQUIRED_PLACEHOLDERS.get(stage, ())) - set(requested))
    if missing:
        raise ExtractionError(
            f"stage {stage!r} requires a prompt that uses {missing}",
            reason_code="contents_placeholder_required",
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
