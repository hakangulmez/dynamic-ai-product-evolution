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
    CAPABILITY_REF_PATTERN,
    PARENT_REF_PATTERN,
    PASSAGE_REF_PATTERN,
    canonical_passage_order,
    focal_capability_order,
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
    "resolve_capability_refs",
    "resolve_evidence_refs",
    "resolve_parent_refs",
    "resolve_status_labels",
    "slugify_product_name",
]

CANDIDATE_COLLECTION_CONTRACT = "extraction_candidate_collection@0.1.0"
# ADR-068 (E-T1). A third kind, on the same proven shape: single-pass recall,
# then a human decision set. The order is the dependency order -- a capability
# needs a product, a task needs both.
OBSERVATION_KINDS: tuple[str, ...] = ("product", "capability", "task")

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
    # ADR-068. The @0.2.0 successor, which requires ``normalized_task``. The
    # released @0.1.0 schema has no slug field at all, so C3 -- the check that a
    # name can be slugged into an identity -- had nothing to read.
    "task": "task_observation_v2.schema.json",
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
# ADR-069 (E-T1 governance wiring). A fourth label family, same reason again:
# "cited a capability position the model was not shown" is its own fault,
# distinct from C9 (which judges the *resolved* id against Snapshot B) exactly
# as ``_REF_UNRESOLVABLE`` is distinct from C6.
_CAPABILITY_REF_UNRESOLVABLE = "candidate_conformance_capability_ref_unresolvable"
# The task stage's focal product is a pipeline input, never a model output
# (ADR-068): task discovery renders one product at a time, so the pipeline
# already knows which one this call is about. Same reason code string as
# ``contents_renderer._require_focal`` -- one fault, one name, whichever stage
# of the pipeline notices the caller omitted it.
_FOCAL_PRODUCT_REQUIRED = "focal_product_required"
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
# ADR-068 (E-T1). C9 is to a task what C7 is to a capability, one level on: it
# proves a human admitted every capability the task claims to be performed
# through. Separate from C7, which the task stage also runs against its product,
# because "named a product nobody validated" and "named a capability nobody
# validated" are different faults with different fixes.
_C9 = "candidate_conformance_capability_not_in_snapshot"
# C10. All cited capabilities must belong to the task's own product.
#
# Structurally unreachable today: task discovery renders one product at a time,
# so the model is never shown a second product's capabilities and cannot name
# one. That is exactly why it is here. "Impossible by construction" is the
# assumption ADR-053, ADR-058, ADR-061, ADR-062 and ADR-064 each watched become
# false when the construction changed, and this check costs one set comparison.
_C10 = "candidate_conformance_capability_parent_mismatch"
# C11. One capability, cited once.
#
# ``["C1", "C01"]`` is two labels and one capability; resolved, it produced the
# same id twice. ``task_observation_v2`` declares no ``uniqueItems`` and C9 asks
# only about membership, so a downstream reader counting
# ``len(capability_observation_ids)`` would have been told a task rests on two
# capabilities when it rests on one. Refused rather than deduplicated: silently
# collapsing the list would be a repair nobody logged, and the two rules this
# project keeps -- no silent repair, unknown over guess -- both point the same
# way. The check runs on the *resolved* ids, because the defect is invisible in
# the labels: ``C1`` and ``C01`` are different strings for one position.
_C11 = "candidate_conformance_capability_cited_twice"
# Not a conformance failure at all: the packet's own capability context is
# corrupt. Kept apart from C9 -- "the model cited a capability nobody
# validated" is a statement about the answer, this is a statement about the
# question, and an operator chasing the first would never find the second.
_CAPABILITY_CONTEXT_MALFORMED = "candidate_conformance_capability_context_malformed"


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
    if observation_kind == "task":
        # ADR-068. Keyed on the product, not on the capabilities.
        # ``capability_observation_ids`` is an array, so a capability-derived id
        # would depend on how many were cited and in what order -- two tasks of
        # one product could collide or not depending on a list's ordering.
        # ``product_observation_id`` is singular and schema-required, and the
        # collision scope falls out of the formula exactly as it does for a
        # capability: the id begins with its parent's.
        normalized = slugify_product_name(derived.get("task"))
        parent = derived.get("product_observation_id")
        derived["company_id"] = company_id
        derived["observation_cutoff"] = observation_cutoff
        derived["normalized_task"] = normalized
        derived["task_observation_id"] = (
            f"{parent}:{normalized}" if isinstance(parent, str) and parent else ""
        )
        return derived
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


def _capability_observation_ids(packet: dict[str, Any]) -> dict[str, str]:
    """Accepted capability id -> the product it belongs to.

    Read from ``parent_context.capability_parents``, which the packet builder
    produced by re-reading and hash-verifying every Snapshot B member. Same
    source the ``C0N`` labels were assigned from, so a label cannot mean one
    capability in the instruction and another here.
    """
    context = packet.get("parent_context")
    parents = context.get("capability_parents") if isinstance(context, dict) else None
    if not isinstance(parents, list) or not parents:
        raise ExtractionError(
            "the task stage requires verified capability context",
            reason_code=_CAPABILITY_CONTEXT_MALFORMED,
        )
    out: dict[str, str] = {}
    for parent in parents:
        payload = parent.get("payload") if isinstance(parent, dict) else None
        if not isinstance(payload, dict):
            raise ExtractionError(
                "each parent capability must carry its verified payload",
                reason_code=_CAPABILITY_CONTEXT_MALFORMED,
            )
        # Defence in depth. ``focal_capability_order`` already refuses a member
        # with no identity, and this reads the same context -- but it reads
        # *all* capability parents, not only the focal product's, and it is the
        # universe C9 and C10 judge against. Coercing a missing id with ``str``
        # produced the literal ``"None"`` as a key, which would make C9 admit a
        # task citing nothing at all.
        observation_id = parent.get("observation_id")
        owner = payload.get("product_observation_id")
        for value, what in ((observation_id, "observation_id"),
                            (owner, "product_observation_id")):
            if not isinstance(value, str) or not value.strip():
                raise ExtractionError(
                    f"a verified capability carries no {what}",
                    reason_code=_CAPABILITY_CONTEXT_MALFORMED,
                )
        out[observation_id] = owner
    return out


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


def _require_focal_product(focal_product_observation_id: str | None) -> str:
    """The focal product id, or a refusal. Never inferred from the packet.

    Mirrors ``contents_renderer._require_focal`` -- same question, same reason
    code -- because the two are one design decision, not two: task discovery
    renders one product per call, so nothing downstream of the render can
    legitimately guess which product a given call was about either.
    """
    if not isinstance(focal_product_observation_id, str) or not focal_product_observation_id.strip():
        raise ExtractionError(
            "the task stage renders one product at a time and requires "
            "focal_product_observation_id",
            reason_code=_FOCAL_PRODUCT_REQUIRED,
        )
    return focal_product_observation_id


def resolve_capability_refs(
    observation: Any, *, packet: dict[str, Any], focal_product_observation_id: str | None
) -> Any:
    """Turn ``capability_refs: ["C1", "C3"]`` into the capability ids they name.

    The fourth label family, resolved the same way as the passage and parent
    ones. A capability's ``capability_observation_id`` runs 46 to 111
    characters on the pilot data (ADR-068), so the model is not asked to
    transcribe it; it copies the short ``C0N`` label the renderer assigned
    instead.

    **The same ordering the renderer labelled, not a second one.**
    :func:`~.contents_renderer.focal_capability_order` is the one function that
    decides what ``C0N`` names, for both the render and this resolution --
    exactly the discipline ``canonical_passage_order`` already keeps for
    ``P0N``. A resolver that re-derived the order here could agree with the
    renderer today and silently disagree the day the packet builder's own
    ordering changes.

    Scope is narrow, as with the other three resolvers: only a dict observation
    carrying ``capability_refs`` is touched, and the key is replaced by
    ``capability_observation_ids`` so the released schema -- which knows
    ``capability_observation_ids``, not ``capability_refs`` -- accepts the
    result.
    """
    if not isinstance(observation, dict) or "capability_refs" not in observation:
        return observation
    refs = observation["capability_refs"]
    if not isinstance(refs, list):
        raise ExtractionError(
            "capability_refs must be a list of C0N labels",
            reason_code=_CAPABILITY_REF_UNRESOLVABLE,
        )

    focal = _require_focal_product(focal_product_observation_id)
    ordered = focal_capability_order(packet, focal)
    capability_ids = [parent.get("observation_id") for parent in ordered]

    resolved_ids: list[Any] = []
    for label in refs:
        match = CAPABILITY_REF_PATTERN.fullmatch(label) if isinstance(label, str) else None
        if match is None:
            raise ExtractionError(
                f"capability_refs cites {label!r}, which is not a capability label",
                reason_code=_CAPABILITY_REF_UNRESOLVABLE,
            )
        ordinal = int(match.group(1))
        if not 1 <= ordinal <= len(capability_ids):
            raise ExtractionError(
                f"capability_refs cites {label!r}, but only {len(capability_ids)} "
                "capabilities were shown to the model",
                reason_code=_CAPABILITY_REF_UNRESOLVABLE,
            )
        resolved_ids.append(capability_ids[ordinal - 1])

    updated = {key: value for key, value in observation.items() if key != "capability_refs"}
    updated["capability_observation_ids"] = resolved_ids
    return updated


def _inject_focal_product(
    observation: Any, *, observation_kind: str, focal_product_observation_id: str | None
) -> Any:
    """Set ``product_observation_id`` to the pipeline's own focal id.

    Task-kind only, and unconditional once it applies -- this is not resolving
    a label the model wrote, it is supplying a value the model was never asked
    for at all (ADR-069). Task discovery renders one product at a time, so the
    pipeline already knows the answer before the call is made; asking the model
    to name its own parent would reopen exactly the transcription risk
    ``parent_ref`` exists to avoid at the capability stage, for no reason, since
    here the pipeline does not even need to trust a label -- it knows.
    """
    if observation_kind != "task" or not isinstance(observation, dict):
        return observation
    updated = dict(observation)
    updated["product_observation_id"] = _require_focal_product(focal_product_observation_id)
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
    """C1 through C11, atomic at the **collection** level.

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
    task = observation_kind == "task"
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
    parents = set(_parent_observation_ids(packet)) if capability or task else set()
    # C9/C10's universe. Read once, from the same verified parent context the
    # ``C0N`` labels were assigned from.
    capability_owner = _capability_observation_ids(packet) if task else {}

    seen: dict[str, str] = {}
    for ordinal, observation in enumerate(observations):
        if not isinstance(observation, dict):
            continue
        if any(validator.iter_errors(observation)):
            continue

        if task:
            # C7 applies to the task's product exactly as it does to a
            # capability's: a human must have admitted the parent.
            parent = observation.get("product_observation_id")
            if parent not in parents:
                raise ExtractionError(
                    f"C7: observation {ordinal} attributes a task to {parent!r}, "
                    "which is not a validated product of this run",
                    reason_code=_C7,
                )
            cited = observation.get("capability_observation_ids")
            if not isinstance(cited, list) or not cited:
                raise ExtractionError(
                    f"C9: observation {ordinal} cites no capability; a task is "
                    "performed through at least one",
                    reason_code=_C9,
                )
            if len(set(cited)) != len(cited):
                duplicated = sorted({c for c in cited if cited.count(c) > 1})
                raise ExtractionError(
                    f"C11: observation {ordinal} cites the same capability more "
                    f"than once: {duplicated}",
                    reason_code=_C11,
                )
            for capability_id in cited:
                if capability_id not in capability_owner:
                    raise ExtractionError(
                        f"C9: observation {ordinal} cites {capability_id!r}, which "
                        "is not a validated capability of this run",
                        reason_code=_C9,
                    )
                if capability_owner[capability_id] != parent:
                    raise ExtractionError(
                        f"C10: observation {ordinal} cites a capability of another "
                        f"product; the task is attributed to {parent!r}",
                        reason_code=_C10,
                    )
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
        elif capability:
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

        slug_field, source_field, id_field = {
            "product": ("normalized_name", "product_name", "product_observation_id"),
            "capability": (
                "normalized_capability",
                "capability",
                "capability_observation_id",
            ),
            "task": ("normalized_task", "task", "task_observation_id"),
        }[observation_kind]
        normalized = observation.get(slug_field)
        if not isinstance(normalized, str) or not _SLUG_GRAMMAR.fullmatch(normalized):
            raise ExtractionError(
                f"C3: observation {ordinal} has no usable {slug_field} "
                f"({normalized!r}); its {source_field} cannot be slugged",
                reason_code=_C3,
            )
        expected_id = (
            f"{observation.get('product_observation_id')}:{normalized}"
            if capability or task
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
    focal_product_observation_id: str | None = None,
) -> dict[str, str]:
    """Parse, derive, gate, build, validate, write once. Returns the pin.

    ``observation_kind`` defaults to ``product``, so every existing caller and
    every published run is unaffected. ``focal_product_observation_id`` is
    unused by both existing kinds and defaults to ``None`` for the same reason.

    The vocabulary is hydrated through the shared containment-and-digest loader
    and re-validated by its own loader, so the set C5 uses is the artifact's and
    never a constant in this module.

    **Known limitation, recorded rather than implied:** the vocabulary pin is a
    parameter here. The design's D1-D6 derivation -- recovering it from the run
    root's persisted authorization -- requires ``live_call_authorization@0.3.0``,
    which is deferred. Until then a caller could point this at a different
    vocabulary, and only review would catch it.
    """
    # ADR-069. Checked before parsing, exactly as the renderer refuses a
    # focal-less task render before consulting any binding: a task run that
    # cannot name its own product should not spend the cost of parsing the
    # model's output first.
    if observation_kind == "task":
        _require_focal_product(focal_product_observation_id)

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
    # ``product_observation_id``, capability-ref resolution and focal injection
    # supply ``capability_observation_ids``/``product_observation_id`` for the
    # task kind, and the task identity is *derived from* that parent id -- so
    # derivation must come last. All of them are schema-required fields the
    # model was never asked for.
    derived = [
        derive_identity_fields(
            resolve_status_labels(
                _inject_focal_product(
                    resolve_capability_refs(
                        resolve_evidence_refs(
                            resolve_parent_refs(observation, packet=packet), packet=packet
                        ),
                        packet=packet,
                        focal_product_observation_id=focal_product_observation_id,
                    ),
                    observation_kind=observation_kind,
                    focal_product_observation_id=focal_product_observation_id,
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
