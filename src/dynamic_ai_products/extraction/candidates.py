"""Candidate collections as legal wrappers (ADR-033).

``product_observation@0.1.0`` and ``capability_observation@0.1.0`` are strict,
so ``candidate_id`` cannot be appended to an observation object. Each candidate
is a wrapper whose nested ``observation`` payload validates independently
against the unchanged released schema.

One parameterized contract carries both kinds, discriminated by
``observation_kind``, rather than two near-identical schemas that would drift.
"""

from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .availability_vocabulary import (
    resolve_status_label,
    validate_availability_vocabulary,
)
from .contents_renderer import (
    PARENT_REF_PATTERN,
    PASSAGE_REF_PATTERN,
    canonical_passage_order,
)
from .errors import ExtractionError
from .input_packet import hydrate_pinned_artifact
from .raw_artifacts import canonical_json_bytes, write_artifact

__all__ = [
    "CANDIDATE_COLLECTION_CONTRACT",
    "CANDIDATE_COLLECTION_REFERENCE",
    "OBSERVATION_KINDS",
    "STAGE_OBSERVATION_KIND",
    "assert_candidate_conformance",
    "build_candidate_collection",
    "candidate_id_for",
    "collection_bytes",
    "derive_identity_fields",
    "materialize_candidate_collection",
    "observation_kind_for_stage",
    "parse_model_observations",
    "resolve_evidence_refs",
    "resolve_parent_refs",
    "resolve_status_labels",
    "slugify_product_name",
]

CANDIDATE_COLLECTION_CONTRACT = "extraction_candidate_collection@0.1.0"
OBSERVATION_KINDS: tuple[str, ...] = ("product", "capability")

# ADR-061. Which observation kind a stage produces. Closed, and deliberately
# missing ``task_extraction``: a task is not an ``observation_kind`` and must not
# become one by inference. A stage absent here fails closed with its own reason
# code, following ``MATERIALIZATION_SUPPORTED_STAGES`` and
# ``STAGE_REQUIRED_PLACEHOLDERS``.
#
# This map exists because the runner had no way to say which kind it was
# collecting, so it silently used the default. A capability run would then have
# built a *product* collection: every capability observation fails the product
# schema, lands in ``rejected[]`` as ``schema_invalid``, and the collection looks
# valid at ``accepted=0`` while C1-C7 never run at all -- nothing survives the
# pre-schema check for them to gate.
STAGE_OBSERVATION_KIND: dict[str, str] = {
    "product_extraction": "product",
    "capability_extraction": "capability",
}

_STAGE_KIND_UNDECLARED = "stage_observation_kind_undeclared"


def observation_kind_for_stage(stage: str) -> str:
    """The kind a stage collects, or a refusal naming the stage.

    Never falls back to a default. Defaulting is exactly what turned a wrong
    kind into a silently empty collection.
    """
    kind = STAGE_OBSERVATION_KIND.get(stage)
    if kind is None:
        raise ExtractionError(
            f"stage {stage!r} declares no observation kind, so a candidate "
            "collection cannot be published for it",
            reason_code=_STAGE_KIND_UNDECLARED,
        )
    return kind

_SCHEMA_FOR_KIND = {
    "product": "product_observation.schema.json",
    "capability": "capability_observation.schema.json",
}


def candidate_id_for(raw_artifact_sha256: str, ordinal: int, observation: dict[str, Any]) -> str:
    """Bind identity to the raw artifact digest and the emission ordinal.

    Non-transferable across raw artifacts; disambiguates identical text.
    """
    material = (
        raw_artifact_sha256.encode("ascii")
        + b"\x00"
        + str(ordinal).encode("ascii")
        + b"\x00"
        + canonical_json_bytes(observation)
    )
    return sha256(material).hexdigest()[:32]


def _validator(schema_root: str | Path, kind: str) -> Draft202012Validator:
    schema_path = Path(schema_root) / _SCHEMA_FOR_KIND[kind]
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ExtractionError(
            f"released observation schema is unreadable: {schema_path}",
            reason_code="observation_schema_unavailable",
        ) from exc
    return Draft202012Validator(schema)


def build_candidate_collection(
    *,
    observation_kind: str,
    raw_artifact_reference: str,
    raw_artifact_sha256: str,
    observations: list[Any],
    schema_root: str | Path = "schemas",
) -> dict[str, Any]:
    """Wrap deterministic, schema-valid candidates. Rejects are counted, not dropped."""
    if observation_kind not in OBSERVATION_KINDS:
        raise ExtractionError(
            f"unknown observation_kind: {observation_kind!r}",
            reason_code="observation_kind_invalid",
        )
    validator = _validator(schema_root, observation_kind)
    entries: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for ordinal, observation in enumerate(observations):
        if not isinstance(observation, dict):
            rejected.append({"ordinal": ordinal, "reason": "not_an_object"})
            continue
        errors = sorted(validator.iter_errors(observation), key=lambda e: list(e.path))
        if errors:
            rejected.append(
                {
                    "ordinal": ordinal,
                    "reason": "schema_invalid",
                    "detail": errors[0].message,
                }
            )
            continue
        entries.append(
            {
                "candidate_id": candidate_id_for(raw_artifact_sha256, ordinal, observation),
                "ordinal": ordinal,
                "observation_kind": observation_kind,
                "observation": observation,
            }
        )
    entries.sort(key=lambda entry: entry["ordinal"])
    return {
        "contract": CANDIDATE_COLLECTION_CONTRACT,
        "schema_version": "0.1.0",
        "observation_kind": observation_kind,
        "raw_artifact_reference": raw_artifact_reference,
        "raw_artifact_sha256": raw_artifact_sha256,
        "entries": entries,
        "rejected": rejected,
        "accepted_candidate_count": len(entries),
        "rejected_candidate_count": len(rejected),
    }


def collection_bytes(collection: dict[str, Any]) -> bytes:
    return canonical_json_bytes(collection)


# --- G6-M: derivation, parse gates, and the C1-C6 conformance gate -----------
#
# Three layers with deliberately separate ownership, because collapsing them
# would destroy the released ``rejected[]`` contract:
#
#   parse gates      -- the envelope is unusable at all; nothing downstream runs
#   pre-schema check -- who is a candidate; non-objects and schema failures are
#                       left for ``build_candidate_collection`` to record
#   C1-C6            -- collection-level, atomic; a violation refuses the whole
#                       materialization and is NEVER written as ``schema_invalid``
#
# ``rejected.reason`` is a released enum closed to ``not_an_object`` and
# ``schema_invalid``. A conformance failure is therefore not representable inside
# a collection and must not be made to look like one.

CANDIDATE_COLLECTION_REFERENCE = "collection/extraction_candidate_collection.json"

_SLUG_GRAMMAR = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

_PARSE_ENVELOPE = "candidate_parse_envelope_unusable"
_PARSE_JSON = "candidate_parse_json_invalid"
_PARSE_NOT_A_LIST = "candidate_parse_not_a_list"

_C1 = "candidate_conformance_company_mismatch"
_C2 = "candidate_conformance_cutoff_mismatch"
_C3 = "candidate_conformance_normalized_name_invalid"
_C4 = "candidate_conformance_observation_id_mismatch"
_C5 = "candidate_conformance_status_not_governed"
_C6 = "candidate_conformance_evidence_pair_unknown"
_COLLISION = "candidate_conformance_observation_id_collision"
# ADR-055. Deliberately not folded into _C6. A citation naming a passage that
# does not exist and a label the pipeline cannot resolve are different faults:
# the first says the model invented an identifier, the second says it named a
# position outside what it was shown. One is a transcription failure, the other
# a counting failure, and an operator needs to know which.
_REF_UNRESOLVABLE = "candidate_conformance_evidence_ref_unresolvable"
# ADR-060. A third label family, and a third reason code, for the same reason
# the second one was separate: "named a product position it was not shown" is a
# different fault from "cited a passage that does not exist".
_PARENT_REF_UNRESOLVABLE = "candidate_conformance_parent_ref_unresolvable"
# C7 has no product-side counterpart. A product observation has no parent; a
# capability that names one outside this run's Snapshot A would be attributed to
# something the human never admitted.
_C7 = "candidate_conformance_parent_not_in_snapshot"
# C8. Separate from C6 for the same reason ADR-055 kept its label codes separate:
# these are different failure classes and an operator needs to know which. C6
# says the *identifier* is not real -- the model named a passage this run never
# held. C8 says the identifier is real but the *words* are not in it. A spliced
# quote passes C6 with room to spare: measured on ext-smoke-0006, one evidence
# entry of thirty-four quoted two passages 895 characters apart in the source
# under the first one's id, and every gate admitted it.
_C8 = "candidate_conformance_evidence_quote_uncontained"


def slugify_product_name(product_name: Any) -> str:
    """Lowercase, single-hyphen-joined, trimmed. Deterministic and total.

    Total on purpose: a name this cannot slug yields the empty string rather
    than an exception, so the judgement stays with C3 and the grammar has one
    owner. A function that raised here would put the same rule in two places.

    ASCII-only by construction. ``product_name`` is model-emitted text and a
    Unicode fold would make two visually distinct names collide silently, which
    is the opposite of what an identity component should do.
    """
    if not isinstance(product_name, str):
        return ""
    return _NON_ALNUM.sub("-", product_name.lower()).strip("-")


def derive_identity_fields(
    observation: Any,
    *,
    company_id: str | None = None,
    observation_cutoff: str | None = None,
    observation_kind: str = "product",
) -> Any:
    """Overwrite the three identity fields with derived values (ADR-054, R-D).

    **Not a repair.** ``candidate_id`` has always been derived rather than
    requested, for the reason that applies here too: an identifier a model
    invents cannot be recomputed, so it cannot be checked, and a field that
    cannot be checked is not provenance. These three follow the same rule.
    ``company_id`` and ``observation_cutoff`` come from the packet the run was
    actually built from; ``normalized_name`` and ``product_observation_id`` are
    computed from it and the model's ``product_name``.

    Whatever the model emitted in these three fields is discarded, so the prompt
    does not have to change and the qualification chain it is pinned to stays
    untouched.

    Non-dict items pass through unchanged: they are not observations, and
    ``build_candidate_collection`` owns saying so.

    **Runs before schema validation, deliberately.** ``product_observation_id``
    is schema-required; deriving it afterwards would mean an observation that
    omitted it was recorded as ``schema_invalid`` for a field the pipeline was
    always going to supply.

    **Parameterized, not duplicated (ADR-060).** Five of the seven pipeline steps
    are already kind-agnostic; a parallel capability path would copy those five
    and give the same rule two homes. The capability branch differs only in
    which fields it reads and writes::

        product     -> {company_id}:{observation_cutoff}:{slug(product_name)}
        capability  -> {product_observation_id}:{slug(capability)}

    The capability form takes its parent from the observation, so
    :func:`resolve_parent_refs` must have run first -- the parent id is a
    *component* of the child id, not a sibling field.
    """
    if not isinstance(observation, dict):
        return observation
    if observation_kind not in OBSERVATION_KINDS:
        raise ExtractionError(
            f"unknown observation_kind: {observation_kind!r}",
            reason_code="observation_kind_invalid",
        )
    derived = dict(observation)
    if observation_kind == "capability":
        normalized = slugify_product_name(derived.get("capability"))
        parent = derived.get("product_observation_id")
        derived["normalized_capability"] = normalized
        derived["capability_observation_id"] = (
            f"{parent}:{normalized}" if isinstance(parent, str) and parent else ""
        )
        return derived
    normalized = slugify_product_name(derived.get("product_name"))
    derived["company_id"] = company_id
    derived["observation_cutoff"] = observation_cutoff
    derived["normalized_name"] = normalized
    derived["product_observation_id"] = f"{company_id}:{observation_cutoff}:{normalized}"
    return derived


def _parent_observation_ids(packet: dict[str, Any]) -> tuple[str, ...]:
    """The validated parents, in the one order the renderer labelled them.

    Read from ``parent_context.product_parents``, which the packet builder
    produced by re-reading and hash-verifying every Snapshot A member. That is
    the same sequence ADR-058's ``A0N`` labels were assigned from, so a label
    cannot mean one product in the instruction and another here.
    """
    context = packet.get("parent_context")
    parents = context.get("product_parents") if isinstance(context, dict) else None
    if not isinstance(parents, list) or not parents:
        raise ExtractionError(
            "the capability stage requires verified parent context",
            reason_code=_PARENT_REF_UNRESOLVABLE,
        )
    ids: list[str] = []
    for parent in parents:
        observation_id = parent.get("observation_id") if isinstance(parent, dict) else None
        if not isinstance(observation_id, str) or not observation_id:
            raise ExtractionError(
                "a verified parent carries no observation_id",
                reason_code=_PARENT_REF_UNRESOLVABLE,
            )
        ids.append(observation_id)
    return tuple(ids)


def resolve_parent_refs(observation: Any, *, packet: dict[str, Any]) -> Any:
    """Turn ``parent_ref: "A01"`` into the product observation it names.

    The third label family, resolved the same way as the first two.
    ``product_observation_id`` is 44 characters of colon-joined slug; asking a
    model to transcribe it is the failure ADR-055 and ADR-056 each measured, so
    it is not asked. The label resolves against the same ordered parent context
    the renderer labelled, so there is no second mapping to keep in step.

    Scope is narrow, as with evidence: only a dict observation carrying
    ``parent_ref`` is touched, and the key is removed once resolved so the
    released schema -- which is ``additionalProperties: false`` and knows no
    ``parent_ref`` -- accepts the result.
    """
    if not isinstance(observation, dict) or "parent_ref" not in observation:
        return observation
    label = observation["parent_ref"]
    match = PARENT_REF_PATTERN.fullmatch(label) if isinstance(label, str) else None
    if match is None:
        raise ExtractionError(
            f"parent_ref {label!r} is not a validated-product label",
            reason_code=_PARENT_REF_UNRESOLVABLE,
        )
    parents = _parent_observation_ids(packet)
    ordinal = int(match.group(1))
    if not 1 <= ordinal <= len(parents):
        raise ExtractionError(
            f"parent_ref cites {label!r}, but only {len(parents)} validated "
            "products were shown to the model",
            reason_code=_PARENT_REF_UNRESOLVABLE,
        )
    resolved = {key: value for key, value in observation.items() if key != "parent_ref"}
    resolved["product_observation_id"] = parents[ordinal - 1]
    return resolved


def resolve_evidence_refs(observation: Any, *, packet: dict[str, Any]) -> Any:
    """Turn each ``{"ref", "quote"}`` citation into the real identity pair.

    The same move as :func:`derive_identity_fields`, for the same measured
    reason: a model asked to copy a 32-character opaque hex string does not do
    it reliably. Here it copies a three-digit label instead, and the pair it
    stands for is read from the packet through
    :func:`~.contents_renderer.canonical_passage_order` -- the *same* function
    that decided what the model saw, so the label cannot mean one passage at
    render time and another here.

    **The schema is untouched.** Resolution happens before validation and the
    result carries exactly ``{source_id, passage_id, quote}``, so
    ``product_observation.schema.json`` stays valid unchanged.

    Scope is narrow on purpose. Only a dict observation whose ``evidence`` is a
    list is considered, and inside it only entries that are dicts carrying
    ``ref``. Anything else passes through untouched for
    ``build_candidate_collection`` to record as ``not_an_object`` or
    ``schema_invalid`` -- the released ``rejected[]`` contract is not widened by
    this step.

    An entry that *does* carry a ``ref`` the packet cannot resolve is a refusal,
    not a pass-through. The model followed the format and named a position that
    does not exist; leaving that to schema validation would report it as a
    missing ``source_id``, which is true but says nothing about what went wrong.
    """
    if not isinstance(observation, dict):
        return observation
    evidence = observation.get("evidence")
    if not isinstance(evidence, list):
        return observation
    if not any(isinstance(entry, dict) and "ref" in entry for entry in evidence):
        return observation

    ordered = canonical_passage_order(packet)
    resolved_entries: list[Any] = []
    for entry in evidence:
        if not isinstance(entry, dict) or "ref" not in entry:
            resolved_entries.append(entry)
            continue
        label = entry["ref"]
        match = (
            PASSAGE_REF_PATTERN.fullmatch(label) if isinstance(label, str) else None
        )
        if match is None:
            raise ExtractionError(
                f"evidence cites {label!r}, which is not a passage label",
                reason_code=_REF_UNRESOLVABLE,
            )
        ordinal = int(match.group(1))
        if not 1 <= ordinal <= len(ordered):
            raise ExtractionError(
                f"evidence cites {label!r}, but only {len(ordered)} passages were "
                "shown to the model",
                reason_code=_REF_UNRESOLVABLE,
            )
        passage = ordered[ordinal - 1]
        resolved = {
            key: value for key, value in entry.items() if key != "ref"
        }
        resolved["source_id"] = passage["source_id"]
        resolved["passage_id"] = passage["passage_id"]
        resolved_entries.append(resolved)

    updated = dict(observation)
    updated["evidence"] = resolved_entries
    return updated


def resolve_status_labels(observation: Any) -> Any:
    """Turn the ``availability_status`` label into the status it names.

    The third application of one rule (ADR-054, ADR-055, this): a value the
    model cannot be trusted to transcribe is not requested from it. Here the
    string is short but internally repetitive -- ``broadly_deployed_or_default``
    came back once as ``broadly_deployed_or_or_default`` -- and unlike a passage
    reference the set is fixed, code-owned and packet-independent, so the label
    resolves against :data:`CANONICAL_AVAILABILITY_STATUS_VALUES` directly.

    Runs before schema validation and before C5, because ``availability_status``
    is schema-required and C5 judges the resolved token, never the label.

    Non-dict items and observations without the field pass through: they belong
    to ``build_candidate_collection`` and the released ``rejected[]`` contract.
    """
    if not isinstance(observation, dict) or "availability_status" not in observation:
        return observation
    updated = dict(observation)
    updated["availability_status"] = resolve_status_label(
        observation["availability_status"]
    )
    return updated


def parse_model_observations(raw_prediction: Any) -> list[Any]:
    """The envelope gates. Either a usable list of items, or a refusal.

    These precede everything: an envelope that did not terminate normally, or
    carries no single text part, says nothing about candidates at all. Treating
    a truncated response as "zero candidates" would record an absence that was
    never observed.
    """
    if not isinstance(raw_prediction, dict):
        raise ExtractionError(
            "the raw prediction envelope must be a mapping", reason_code=_PARSE_ENVELOPE
        )
    candidates = raw_prediction.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise ExtractionError(
            "the envelope must carry exactly one candidate", reason_code=_PARSE_ENVELOPE
        )
    candidate = candidates[0]
    if not isinstance(candidate, dict) or candidate.get("finishReason") != "STOP":
        raise ExtractionError(
            "the candidate did not finish normally; a truncated response is not "
            "an empty result",
            reason_code=_PARSE_ENVELOPE,
        )
    parts = (candidate.get("content") or {}).get("parts")
    if not isinstance(parts, list) or len(parts) != 1:
        raise ExtractionError(
            "the candidate must carry exactly one part", reason_code=_PARSE_ENVELOPE
        )
    text = parts[0].get("text") if isinstance(parts[0], dict) else None
    if not isinstance(text, str) or not text.strip():
        raise ExtractionError(
            "the candidate part carries no text", reason_code=_PARSE_ENVELOPE
        )
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExtractionError(
            f"the model output is not valid JSON: {exc}", reason_code=_PARSE_JSON
        ) from exc
    if not isinstance(parsed, list):
        raise ExtractionError(
            "the model output must be a JSON array", reason_code=_PARSE_NOT_A_LIST
        )
    return parsed


def assert_candidate_conformance(
    observations: list[Any],
    *,
    packet: dict[str, Any],
    vocabulary: dict[str, Any],
    schema_root: str | Path = "schemas",
    observation_kind: str = "product",
) -> None:
    """C1 through C8, atomic at the **collection** level.

    Applied only to items that already pass a pure pre-schema check, so a
    non-object or a schema failure reaches ``build_candidate_collection`` and is
    recorded in ``rejected[]`` exactly as the released contract says. Any
    conformance violation, on any item, refuses the entire materialization: no
    partial collection is written and nothing is silently dropped.

    C5 asks one question and no more: is the status in
    ``admitted_status_values``? Not whether it is active, not whether it is
    roadmap. ``unknown`` is admitted, enters the collection, and its disposition
    is a human decision made later.

    C6 and C8 are the two halves of one evidence question and stay separate on
    purpose: C6 proves the cited pair is a passage of this run, C8 proves the
    quoted words are in that passage. Until C8 existed only the first half was
    asked, and a quote assembled from two passages satisfied it.
    """
    if observation_kind not in OBSERVATION_KINDS:
        raise ExtractionError(
            f"unknown observation_kind: {observation_kind!r}",
            reason_code="observation_kind_invalid",
        )
    capability = observation_kind == "capability"
    company_id = packet["company_id"]
    cutoff = packet["observation_cutoff_date"]
    admitted = set(vocabulary["admitted_status_values"])
    # One structure for both evidence gates, read once. C6 asks whether a pair is
    # a key; C8 asks what that key maps to. Two passes over the same passages
    # would be two chances to disagree about which run's corpus is authoritative.
    universe = {
        (p.get("source_id"), p.get("passage_id")): p.get("text")
        for p in packet.get("passages", [])
        if isinstance(p, dict)
    }
    validator = _validator(schema_root, observation_kind)
    # C7's universe. Read once, from the same verified parent context the labels
    # were assigned from.
    parents = set(_parent_observation_ids(packet)) if capability else set()

    seen: dict[str, str] = {}
    for ordinal, observation in enumerate(observations):
        if not isinstance(observation, dict):
            continue
        if any(validator.iter_errors(observation)):
            continue

        if capability:
            # C7 replaces C1 and C2 rather than sitting beside them. A
            # capability record carries no company_id and no observation_cutoff
            # -- measured: neither is in ``capability_observation@0.1.0``. Both
            # facts reach it through the parent, whose id *is*
            # ``{company_id}:{cutoff}:{slug}``, so proving the parent is a member
            # of this run's Snapshot A proves the company and the cutoff too,
            # and proves something neither C1 nor C2 could: that a human
            # admitted this parent.
            parent = observation.get("product_observation_id")
            if parent not in parents:
                raise ExtractionError(
                    f"C7: observation {ordinal} attributes a capability to "
                    f"{parent!r}, which is not a validated product of this run",
                    reason_code=_C7,
                )
        else:
            if observation.get("company_id") != company_id:
                raise ExtractionError(
                    f"C1: observation {ordinal} declares another company",
                    reason_code=_C1,
                )
            if observation.get("observation_cutoff") != cutoff:
                raise ExtractionError(
                    f"C2: observation {ordinal} declares another cutoff",
                    reason_code=_C2,
                )

        slug_field = "normalized_capability" if capability else "normalized_name"
        source_field = "capability" if capability else "product_name"
        id_field = "capability_observation_id" if capability else "product_observation_id"
        normalized = observation.get(slug_field)
        if not isinstance(normalized, str) or not _SLUG_GRAMMAR.fullmatch(normalized):
            raise ExtractionError(
                f"C3: observation {ordinal} has no usable {slug_field} "
                f"({normalized!r}); its {source_field} cannot be slugged",
                reason_code=_C3,
            )
        expected_id = (
            f"{observation.get('product_observation_id')}:{normalized}"
            if capability
            else f"{company_id}:{cutoff}:{normalized}"
        )
        if observation.get(id_field) != expected_id:
            raise ExtractionError(
                f"C4: observation {ordinal} carries an id that is not its "
                "derived identity",
                reason_code=_C4,
            )
        if expected_id in seen:
            # Scoped per parent by construction, not by a second mechanism: a
            # capability id begins with its parent's id, so two products may
            # legitimately offer the same capability and only a genuine
            # within-parent clash collides.
            raise ExtractionError(
                f"C4: observations {seen[expected_id]} and {ordinal} slug to one "
                f"identity ({expected_id!r}); two distinct records cannot share "
                "an observation id",
                reason_code=_COLLISION,
            )
        seen[expected_id] = str(ordinal)
        status = observation.get("availability_status")
        if status not in admitted:
            raise ExtractionError(
                f"C5: observation {ordinal} declares a status outside the "
                f"governed vocabulary: {status!r}",
                reason_code=_C5,
            )
        for entry in observation.get("evidence") or ():
            pair = (entry.get("source_id"), entry.get("passage_id"))
            if pair not in universe:
                raise ExtractionError(
                    f"C6: observation {ordinal} cites a passage that is not in "
                    "the packet this run was built from",
                    reason_code=_C6,
                )
            # C8 runs only once C6 has proved the pair resolves, so the text
            # below is this run's own corpus. A blank quote fails rather than
            # passing by the empty-string-is-a-substring accident.
            quote = entry.get("quote")
            text = universe[pair]
            if (
                not isinstance(quote, str)
                or not quote.strip()
                or not isinstance(text, str)
                or quote not in text
            ):
                # Neither the quote nor the passage text appears here: a refusal
                # names what failed, not the contents that failed it.
                raise ExtractionError(
                    f"C8: observation {ordinal} quotes words that do not occur "
                    f"verbatim in the passage it cites ({pair[0]!r}, {pair[1]!r})",
                    reason_code=_C8,
                )


def materialize_candidate_collection(
    *,
    raw_prediction: Any,
    packet: dict[str, Any],
    raw_artifact_reference: str,
    raw_artifact_sha256: str,
    collection_root: str | Path,
    vocabulary_root: str | Path,
    vocabulary_pin: dict[str, str],
    repo_root: str | Path,
    schema_root: str | Path = "schemas",
    observation_kind: str = "product",
) -> dict[str, str]:
    """Parse, derive, gate, build, validate, write once. Returns the pin.

    ``observation_kind`` defaults to ``product``, so every existing caller and
    every published run is unaffected.

    The vocabulary is hydrated through the shared containment-and-digest loader
    and re-validated by its own loader, so the set C5 uses is the artifact's and
    never a constant in this module.

    **Known limitation, recorded rather than implied:** the vocabulary pin is a
    parameter here. The design's D1-D6 derivation -- recovering it from the run
    root's persisted authorization -- requires ``live_call_authorization@0.3.0``,
    which is deferred. Until then a caller could point this at a different
    vocabulary, and only review would catch it.
    """
    vocabulary = validate_availability_vocabulary(
        hydrate_pinned_artifact(
            vocabulary_root,
            vocabulary_pin,
            what="availability vocabulary",
            unsafe_code="vocabulary_pin_unresolved",
            sha_code="vocabulary_pin_unresolved",
        ),
        repo_root=repo_root,
    )

    observations = parse_model_observations(raw_prediction)
    # Every resolution runs before any schema check, and the order is a
    # dependency chain, not a preference: reference resolution supplies
    # ``source_id``/``passage_id``, parent resolution supplies
    # ``product_observation_id``, and the capability identity is *derived from*
    # that parent id -- so derivation must come last. All of them are
    # schema-required fields the model was never asked for.
    derived = [
        derive_identity_fields(
            resolve_status_labels(
                resolve_evidence_refs(
                    resolve_parent_refs(observation, packet=packet), packet=packet
                )
            ),
            company_id=packet["company_id"],
            observation_cutoff=packet["observation_cutoff_date"],
            observation_kind=observation_kind,
        )
        for observation in observations
    ]
    assert_candidate_conformance(
        derived,
        packet=packet,
        vocabulary=vocabulary,
        schema_root=schema_root,
        observation_kind=observation_kind,
    )

    collection = build_candidate_collection(
        observation_kind=observation_kind,
        raw_artifact_reference=raw_artifact_reference,
        raw_artifact_sha256=raw_artifact_sha256,
        observations=derived,
        schema_root=schema_root,
    )

    schema_path = Path(schema_root) / "extraction_candidate_collection.schema.json"
    errors = sorted(
        Draft202012Validator(
            json.loads(schema_path.read_text(encoding="utf-8"))
        ).iter_errors(collection),
        key=lambda e: list(e.path),
    )
    if errors:
        raise ExtractionError(
            f"the assembled collection does not satisfy its own contract: "
            f"{errors[0].message}",
            reason_code="candidate_collection_invalid",
        )
    if (
        len(collection["entries"]) != collection["accepted_candidate_count"]
        or len(collection["rejected"]) != collection["rejected_candidate_count"]
    ):
        raise ExtractionError(
            "the collection's declared counts disagree with its own lists",
            reason_code="candidate_collection_invalid",
        )

    digest = write_artifact(
        collection_root, CANDIDATE_COLLECTION_REFERENCE, collection_bytes(collection)
    )
    pin = {"reference": CANDIDATE_COLLECTION_REFERENCE, "sha256": digest}
    hydrate_pinned_artifact(
        collection_root,
        pin,
        what="candidate collection",
        unsafe_code="candidate_collection_invalid",
        sha_code="candidate_collection_invalid",
    )
    return pin
