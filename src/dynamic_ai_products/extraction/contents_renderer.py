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

**Three stages materialize (ADR-058, E-S1; ADR-068, E-T1).**
``product_extraction`` has since E-R. ``capability_extraction`` joined at
E-S1, because the thing it was waiting for existed: a human-validated
Snapshot A, reconciled by the packet builder and handed here as
``parent_context.product_parents``. ``task_extraction`` joins at E-T1 for the
same reason one stage on — Snapshot B is now persisted and reconciled, so the
packet builder hands this renderer both ``product_parents`` and
``capability_parents``.

The task stage renders one product at a time — ``focal_product_observation_id``
is a required keyword argument for it, never inferred from the packet — so a
render with no focal product still fails closed, now with
``focal_product_required`` rather than ``contents_placeholder_unbound``.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from .errors import ExtractionError

__all__ = [
    "MARKER_FRAGMENTS",
    "CANDIDATE_REF_PATTERN",
    "CAPABILITY_REF_PATTERN",
    "MATERIALIZATION_SUPPORTED_STAGES",
    "PARENT_REF_PATTERN",
    "PASSAGE_REF_PATTERN",
    "PLACEHOLDER_PATTERN",
    "RENDERER_VERSION",
    "STAGE_PASSAGE_REF_STYLE",
    "STAGE_PLACEHOLDER_BINDINGS",
    "STAGE_REQUIRED_PLACEHOLDERS",
    "candidate_ref_label",
    "candidate_ref_order",
    "canonical_passage_order",
    "capability_ref_label",
    "focal_capability_order",
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
    # ADR-068 (E-T1). The task stage joins for the same reason the capability
    # stage did in ADR-058: the thing it was waiting for exists. Snapshot B is
    # persisted and reconciled, so the packet builder hands this renderer both
    # ``product_parents`` and ``capability_parents``.
    "task_extraction",
    # ADR-073 (CR-0009). The consolidation stage renders, for the same reason
    # the other three do: its input exists and is hash-bound. Note what it is
    # **not** added to -- ``STAGE_OBSERVATION_KIND`` and the candidate-collection
    # publication path -- because it produces decisions about observations, not
    # observations. ``observation_kind_for_stage`` refuses it, which is correct.
    "product_consolidation",
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


def _bind_company_name(packet: dict[str, Any], stage: str, focal: str | None) -> str:
    """The legal name, which only an ``@0.2.0`` packet carries.

    A ``@0.1.0`` packet has no name field at all, so rendering one is refused
    rather than filled with the CIK: a company identifier is not a legal name.

    ADR-064. Every binder takes the rendering stage, and most ignore it. The
    uniform signature is the point: the stage reaches a binder from the render
    call, so it is always the stage actually being rendered. Binding the stage
    into the map instead -- one pre-parameterized callable per entry -- would put
    a per-stage constant somewhere a new stage could be added by copying, which
    is the defect ADR-053, ADR-058, ADR-061 and ADR-062 each found once.
    """
    value = packet.get("legal_name")
    if value is None:
        raise ExtractionError(
            "the packet carries no legal_name; extraction_input_packet@0.2.0 with a "
            "hydrated company-identity pin is required to render this prompt",
            reason_code="company_identity_pin_required",
        )
    return _require_str(value, "legal_name")


def _bind_cutoff(packet: dict[str, Any], stage: str, focal: str | None) -> str:
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
# Labels are one-based because they are read by a human and by a model, not used
# as an index.
#
# ADR-064. The grammar accepts any run of digits, not three or more. Measured on
# the widening: every label the ``\d{3,}`` grammar accepted is still accepted,
# and every one of them still resolves to the same ordinal -- ``int("025")`` is
# 25 either way -- so no historical citation changes meaning. What the widening
# adds is ``P25`` and ``P1``, which is what a model writes when it reads a
# zero-padded number and re-emits it naturally.
PASSAGE_REF_PATTERN = re.compile(r"^P(\d+)$")

# ADR-064. How each stage's prompt *renders* the label. The grammar above is
# shared and permissive; this is the narrow question of what the model is shown.
#
# Not global, and the reason is a live artifact rather than a preference: the
# product stage runs `product_discovery_schema_v4`, whose own text says the label
# is "the letter `P` followed by at least three digits". That prompt is qualified,
# its digest is pinned in every product prompt-qualification record, and changing
# the renderer under it would put the rendered labels out of step with the
# instruction the model is reading. So the style moves per stage, with the prompt
# it belongs to.
#
# Closed and fail-closed, the ADR-062 shape. ``task_extraction`` is absent
# because it has no qualified prompt; when it gets one, its style is chosen on
# purpose. A default here is exactly what would let a new stage silently inherit
# a padding convention its prompt never described.
STAGE_PASSAGE_REF_STYLE: dict[str, str] = {
    "product_extraction": "P{:03d}",
    "capability_extraction": "P{:d}",
    # ADR-068. Unpadded, for the reason ADR-064 measured: shown a zero-padded
    # number, the model re-emits it in its own natural form. The task stage is
    # new, so it starts where that measurement ended rather than repeating it.
    "task_extraction": "P{:d}",
    # ADR-073. Unpadded, same reason. This stage's prompt is new, so it is
    # written against the unpadded form rather than inheriting the product
    # stage's three-digit style from the corpus it happens to share.
    "product_consolidation": "P{:d}",
}

_STAGE_REF_STYLE_UNDECLARED = "passage_ref_label_style_undeclared"


def passage_ref_label(ordinal: int, *, stage: str) -> str:
    """The label for a one-based position in the canonical order, per stage.

    Keyword-only and mandatory: a positional default would be the stage-agnostic
    constant this replaced.
    """
    style = STAGE_PASSAGE_REF_STYLE.get(stage)
    if style is None:
        raise ExtractionError(
            f"stage {stage!r} declares no passage-label style, so a passage "
            "cannot be labelled for it",
            reason_code=_STAGE_REF_STYLE_UNDECLARED,
        )
    return style.format(ordinal)


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


def _bind_passages_with_ids(packet: dict[str, Any], stage: str, focal: str | None) -> str:
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
        f"[ref: {passage_ref_label(ordinal, stage=stage)}] "
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


def _bind_validated_products(packet: dict[str, Any], stage: str, focal: str | None) -> str:
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


# ADR-068 (E-T1), then ADR-069. The capability label, one per capability of the
# focal product.
#
# ``C`` for capability, beside ``A`` for Snapshot A and ``P`` for passage. Same
# rule as ADR-055 and ADR-060: the model is shown what it needs to reason with
# and is never asked to transcribe a long identifier. Measured here:
# ``capability_observation_id`` runs 46 to 111 characters on the pilot data,
# which is worse than the 44-character ``product_observation_id`` that ADR-060
# replaced with ``A0N``.
#
# Unpadded from the start (ADR-069), applying ADR-064's measurement pre-emptively
# rather than repeating it: shown a zero-padded ``P025``, the model wrote
# ``P25`` -- on two independent live turns, identically. Every product's
# capability count passes through ``C1``-``C9``, so a padded ``C0N`` would carry
# that same risk on every one of the nine task-discovery calls, not on an
# occasional one. The pattern accepts two-or-more digits too, so a
# capability_observation_id resolved against an already-persisted ``"C01"``
# still parses correctly -- ``int("01") == int("1")`` -- but the label this
# module emits going forward is always unpadded.
CAPABILITY_REF_PATTERN = re.compile(r"^C(\d+)$")


def capability_ref_label(ordinal: int) -> str:
    """The label for a one-based position in the focal product's capabilities."""
    return f"C{ordinal}"


# ADR-073 (CR-0009). The consolidation stage's own label family.
#
# **Not ``C``.** ``C`` belongs to ``focal_capability_order`` and means "a
# capability of the focal product". Giving one letter a second meaning is
# exactly the failure ``canonical_passage_order`` exists to prevent: a label
# that names one thing when the document is rendered and a different thing when
# the model's answer is resolved. ``A``, ``P`` and ``S`` are taken for the same
# reason, so the candidate family is ``D`` -- discovery candidate.
#
# Unpadded, per ADR-064: the correct answer should be what the model writes
# naturally. The ``A`` family stayed padded because a released prompt cannot be
# edited; a new family does not inherit that debt.
CANDIDATE_REF_PATTERN = re.compile(r"^D(\d+)$")


def candidate_ref_label(ordinal: int) -> str:
    """The label for a one-based position in the candidate collection."""
    return f"D{ordinal}"


def candidate_ref_order(packet: dict[str, Any]) -> list[dict[str, Any]]:
    """The one ordering that decides what each ``D0N`` label names.

    **Public and shared**, for the reason ``focal_capability_order`` is: this
    decision has two consumers -- ``_bind_product_candidates`` assigns the
    labels the model sees, and ``resolve_candidate_refs`` resolves the labels
    the model wrote back. Two independent orderings that happened to agree would
    be the ``canonical_passage_order`` lesson repeated, silently.

    **No second sorter.** ``candidate_context.candidates`` is already in the
    collection's own ``ordinal`` order, fixed when the collection was built and
    hash-verified on the way into the packet.
    """
    context = packet.get("candidate_context")
    if not isinstance(context, dict):
        raise ExtractionError(
            "the consolidation stage requires candidate context",
            reason_code="contents_context_invalid",
        )
    candidates = context.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ExtractionError(
            "candidate context carries no candidates",
            reason_code="contents_context_invalid",
        )
    for entry in candidates:
        if not isinstance(entry, dict) or not isinstance(entry.get("payload"), dict):
            raise ExtractionError(
                "every candidate entry needs an object payload",
                reason_code="contents_context_invalid",
            )
        if not isinstance(entry.get("candidate_id"), str) or not entry["candidate_id"]:
            raise ExtractionError(
                "every candidate entry needs a candidate_id",
                reason_code="contents_context_invalid",
            )
    return list(candidates)


def _require_focal(focal: str | None) -> str:
    """The focal product id, or a refusal. Never inferred from the packet.

    A packet carries every validated product; picking one here would be a guess
    about which run this is. The caller names it, and a task render without one
    fails rather than silently choosing.
    """
    if not isinstance(focal, str) or not focal.strip():
        raise ExtractionError(
            "the task stage renders one product at a time and requires "
            "focal_product_observation_id",
            reason_code="focal_product_required",
        )
    return focal


def focal_capability_order(packet: dict[str, Any], focal: str) -> tuple[dict[str, Any], ...]:
    """The accepted capabilities of one product, in the packet's own order.

    **No second sorter**, exactly as ``_bind_validated_products`` and
    ``canonical_passage_order``: ``parent_context.capability_parents`` is
    already ordered by ``derive_parent_context``, and every entry there was
    re-read and hash-verified against a Snapshot B member before it arrived.

    **Public and shared, unlike ``_bind_validated_products``.** This function
    decides what ordinal position each ``C0N`` label names, and that decision
    has two consumers: ``_bind_capabilities`` assigns the labels the model
    sees, and :func:`~.candidates.resolve_capability_refs` resolves the labels
    the model wrote back. Two independent orderings that happened to agree
    would be the ``canonical_passage_order`` lesson repeated -- a label meaning
    one capability at render time and a different one at resolution time,
    silently.
    """
    context = packet.get("parent_context")
    if not isinstance(context, dict):
        raise ExtractionError(
            "the task stage requires parent context",
            reason_code="contents_context_invalid",
        )
    parents = context.get("capability_parents")
    if not isinstance(parents, list) or not parents:
        raise ExtractionError(
            "rendering requires at least one validated capability",
            reason_code="contents_context_invalid",
        )
    focal_capabilities = []
    for parent in parents:
        if not isinstance(parent, dict) or not isinstance(parent.get("payload"), dict):
            raise ExtractionError(
                "each parent capability must carry its verified payload",
                reason_code="contents_context_invalid",
            )
        # The ordinal a ``C0N`` label names is only as trustworthy as the
        # identity at that position. ``_parent_observation_ids`` has always
        # required this of an ``A0N`` parent; measured, this function did not,
        # and a member missing ``observation_id`` resolved to ``None`` --
        # reaching the released schema as a null and being recorded as an
        # ordinary ``schema_invalid`` candidate. A corrupted packet must not be
        # reportable as a bad model answer.
        observation_id = parent.get("observation_id")
        if not isinstance(observation_id, str) or not observation_id.strip():
            raise ExtractionError(
                "a verified capability carries no observation_id",
                reason_code="contents_context_invalid",
            )
        if parent["payload"].get("product_observation_id") == focal:
            focal_capabilities.append(parent)
    if not focal_capabilities:
        raise ExtractionError(
            "the focal product has no validated capability to render",
            reason_code="contents_context_invalid",
        )
    return tuple(focal_capabilities)


def _focal_product_payload(packet: dict[str, Any], focal: str) -> dict[str, Any]:
    context = packet.get("parent_context")
    if not isinstance(context, dict):
        raise ExtractionError(
            "the task stage requires parent context",
            reason_code="contents_context_invalid",
        )
    for parent in context.get("product_parents") or ():
        if isinstance(parent, dict) and parent.get("observation_id") == focal:
            payload = parent.get("payload")
            if not isinstance(payload, dict):
                raise ExtractionError(
                    "the focal product must carry its verified payload",
                    reason_code="contents_context_invalid",
                )
            return payload
    raise ExtractionError(
        "the focal product is not a validated product of this run",
        reason_code="contents_context_invalid",
    )


def _bind_product(packet: dict[str, Any], stage: str, focal: str | None) -> str:
    """The one product this run is about, by name.

    Singular by design (ADR-068): task discovery runs per product, so the model
    sees one product and that product's capabilities. It never sees a second
    product's ``C0N``, which is what keeps the capability stage's measured
    failure -- everything piling onto one section -- from recurring here.
    """
    return _require_str(
        _focal_product_payload(packet, _require_focal(focal)).get("product_name"),
        "product_name",
    )


def _bind_product_candidates(
    packet: dict[str, Any], stage: str, focal: str | None
) -> str:
    """The discovery candidates, labelled, in the collection's own order.

    **A deliberate subset**, following the measurement behind
    ``_bind_validated_products``. Three fields per candidate: ``product_name``,
    ``entity_type`` and ``availability_status``. What is left out matters more:

    - ``evidence`` -- the model already receives that text under
      ``{{passages_with_ids}}``. Showing it twice under a block that carries no
      ``P0N`` ref invites a quote from the unlabelled copy, reopening the
      citation defect ADR-055 closed.
    - ``product_observation_id`` and ``normalized_name`` -- long opaque strings
      whose transcription is the exact thing the ``D0N`` label exists to avoid.
    - ``target_customers`` and ``confidence`` -- not inputs to a consolidation
      judgement.

    ``availability_status`` **is** shown here, unlike at the capability stage
    where it was withheld to keep a parent's status from biasing a child's. Here
    it is not context, it is the subject: "unsupported roadmap" is one of the
    five exclusion grounds and it is read directly off the status.
    """
    blocks: list[str] = []
    for ordinal, entry in enumerate(candidate_ref_order(packet), start=1):
        payload = entry["payload"]
        header = f"[ref: {candidate_ref_label(ordinal)}]"
        entity_type = payload.get("entity_type")
        if isinstance(entity_type, str) and entity_type:
            header += f" [entity_type: {entity_type}]"
        status = payload.get("availability_status")
        if isinstance(status, str) and status:
            header += f" [availability_status: {status}]"
        blocks.append(
            f"{header}\n{_require_str(payload.get('product_name'), 'product_name')}"
        )
    return "\n\n".join(blocks)


def _bind_capabilities(packet: dict[str, Any], stage: str, focal: str | None) -> str:
    """The focal product's capabilities, each with the evidence it was accepted on.

    Two label families, both already proven, and no opaque identifier in either:

    - ``C0N`` names a capability. Its ``capability_observation_id`` is 46-111
      characters and is resolved downstream, never transcribed.
    - ``P0N`` names the passage a quote came from, resolved through the same
      ``canonical_passage_order`` the other two stages use.

    The passage block is appended here rather than bound separately because
    ``task_discovery_recall`` has no ``{{passages}}`` marker: measured, its
    template carries exactly ``company``, ``cutoff``, ``product`` and
    ``capabilities``. Evidence is part of what a capability *is* at this stage.
    """
    focal = _require_focal(focal)
    ordered = canonical_passage_order(packet)
    label_of = {
        (passage["source_id"], passage["passage_id"]): passage_ref_label(
            ordinal, stage=stage
        )
        for ordinal, passage in enumerate(ordered, start=1)
    }

    blocks: list[str] = []
    cited: dict[str, dict[str, Any]] = {}
    for ordinal, parent in enumerate(focal_capability_order(packet, focal), start=1):
        payload = parent["payload"]
        lines = [
            f"[ref: {capability_ref_label(ordinal)}]",
            _require_str(payload.get("capability"), "capability"),
        ]
        for entry in payload.get("evidence") or ():
            pair = (entry.get("source_id"), entry.get("passage_id"))
            label = label_of.get(pair)
            if label is None:
                raise ExtractionError(
                    "a capability cites a passage this packet does not carry",
                    reason_code="contents_context_invalid",
                )
            cited[label] = ordered[int(label[1:]) - 1]
            lines.append(f"  evidence [ref: {label}]: {entry.get('quote')}")
        blocks.append("\n".join(lines))

    passages = [
        f"[ref: {label}] "
        f"[passage_id: {passage['passage_id']}] "
        f"[source_id: {passage['source_id']}] "
        f"[publication_date: {passage['publication_date']}]\n{passage['text']}"
        for label, passage in sorted(cited.items(), key=lambda kv: int(kv[0][1:]))
    ]
    return "\n".join(blocks) + "\n\nSOURCE PASSAGES:\n" + _PASSAGE_SEPARATOR.join(passages)


# Closed, stage-scoped binding map. A stage absent from this map cannot render,
# and a placeholder absent from its stage's entry is refused.
STAGE_PLACEHOLDER_BINDINGS: dict[str, dict[str, Callable[[dict[str, Any], str, "str | None"], str]]] = {
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
    # ADR-068 (E-T1). Four bindings, and the placeholder names are the frozen
    # prompt's own: ``task_discovery_recall`` says ``{{company}}``, not
    # ``{{company_name}}``, and carries no ``{{passages}}`` at all. The map
    # follows the prompt rather than the other two stages' vocabulary.
    "task_extraction": {
        "company": _bind_company_name,
        "cutoff": _bind_cutoff,
        "product": _bind_product,
        "capabilities": _bind_capabilities,
    },
    # ADR-073 (CR-0009). The consolidation stage reads the discovery stage's
    # output. It binds the product stage's three placeholders unchanged -- the
    # passages are the same passages, ordered by the same
    # ``canonical_passage_order`` -- plus the candidates it is judging.
    "product_consolidation": {
        "company_name": _bind_company_name,
        "cutoff": _bind_cutoff,
        "passages_with_ids": _bind_passages_with_ids,
        "product_candidates": _bind_product_candidates,
    },
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
    # ADR-068. Same reason, one stage on: a task is attributed to a product and
    # to the capabilities it is performed through, and ``task_observation``
    # requires both. A prompt that named neither could not produce a conforming
    # record, and a paid call that cannot conform should not be made.
    "task_extraction": ("product", "capabilities"),
    # ADR-073. Same reason, one stage on: a consolidation decision names a
    # candidate, so a prompt that never shows the candidates cannot produce a
    # conforming decision and a paid call that cannot conform should not be
    # made.
    "product_consolidation": ("product_candidates",),
}


def render_provider_contents(
    *,
    stage: str,
    prompt_text: str,
    packet: dict[str, Any],
    focal_product_observation_id: str | None = None,
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
    resolved = {
        name: bindings[name](packet, stage, focal_product_observation_id)
        for name in sorted(set(requested))
    }
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
