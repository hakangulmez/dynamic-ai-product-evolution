"""Deterministic axis evaluation records for the extraction stages (P3).

``build_extraction_axis_evaluation_records`` is a pure public producer. Given a
case, its loaded parsed-prediction content, a governed source snapshot, the axis
taxonomy, the loaded and bound gold assertion sets, a v0.2 run manifest, and the
observation-target binding, it returns the ``AxisDefinition`` and
``AxisEvaluationRecord`` values that ``build_metric_input_snapshot`` embeds. It
has no persisted artifact of its own: ``metric_input_snapshot@0.1.0`` already
hash-binds the values (ADR-027).

The module never touches the filesystem and never calls a clock, provider, or
model, and it derives nothing from wording. It does perform deterministic
in-memory source resolution: ``resolve_case_source_passages`` is a pure function
over the already-loaded snapshot and case, which is what makes evidence
resolvability derivable without any I/O. Three authorities are kept strictly
apart:

* the **binding** owns the predicted value — specifically the one validated
  owning-subject entry's own ``canonical_target_reference``. Axis labels are
  canonical target references, never raw observation IDs, and the binding is what
  makes an observation-shaped prediction comparable to them;
* the **bound gold set** owns gold values, restricted to ``expected_entity``
  entries of this case;
* the **loaded gold set** owns ``verification_status`` through each entry's
  provenance, because ``ResolvedGoldAssertion`` carries none.

Assertions are the atomic scoring unit, so records are keyed per gold assertion,
never per ``(axis, target)`` pair: two ``expected_entity`` assertions naming the
same canonical target stay two records with their own provenance and their own
denominator contribution.

Failures are an ordinary ``TypeError`` for a wrong argument type — including a
non-string ``evaluation_stage`` — and an ordinary ``ValueError`` for an
unsupported stage string and every content or coherence violation. This module
defines no error class. The governed helpers it calls (``axis_taxonomy_hash``,
``gold_assertion_set_hash``, ``source_passage_snapshot_manifest_hash``,
``resolve_case_source_passages``) revalidate fail-closed and raise their own error
classes carrying a ``reason_code`` and an artifact reference; each of those known
classes is caught narrowly and normalized into a stable, content-free
``ValueError`` raised ``from None``, so nothing crossing the P3 boundary carries a
``reason_code`` or leaks an artifact path. Callers and tests assert on the message.
"""

from __future__ import annotations

from typing import Any

from .contracts import canonical_contract_bytes
from .gold import (
    BoundGoldAssertionSet,
    GoldAssertionSetError,
    LoadedGoldAssertionSet,
    gold_assertion_set_hash,
)
from .metric_inputs import (
    UNKNOWN,
    AxisDefinition,
    AxisEvaluationRecord,
)
from .models import EvaluationCase, EvaluationRunManifestV2, EvaluationStrictModel
from .observation_target_binding import LoadedObservationTargetBinding
from .prediction_content import LoadedParsedPredictionContent
from .resolution_decisions import EXTRACTION_EVALUATION_STAGES
from .source_snapshot import (
    LoadedSourcePassageSnapshotManifest,
    SourceSnapshotError,
    resolve_case_source_passages,
    source_passage_snapshot_manifest_hash,
)
from .taxonomy import AxisTaxonomyError, LoadedAxisTaxonomy, axis_taxonomy_hash
from .validation_inputs import ExtractionEvaluationStage
from ..universe.io_utils import sha256_bytes

__all__ = [
    "ExtractionAxisEvaluationInputs",
    "build_extraction_axis_evaluation_records",
]

# Local mirror of the governed stage/subject-kind map. Mirrored rather than
# imported so the dependency runs one way; equality with the binding module's
# governed map is asserted by test, so a drift cannot pass silently.
_STAGE_SUBJECT_KIND: dict[str, str] = {
    "capability_extraction": "capability",
    "task_extraction": "task",
}

# Only a positive entity assertion yields a positive axis label. A
# forbidden_entity target must never become a gold value merely because it
# appears in an axis taxonomy, and field-value, evidence-provenance, and
# deterministic-validation assertions produce no canonical-label axis record.
_ELIGIBLE_ASSERTION_KIND = "expected_entity"

# Extraction records are conditional: end_to_end belongs to the screen path.
_METRIC_SCOPE = "conditional"


# --- Output ----------------------------------------------------------------


class ExtractionAxisEvaluationInputs(EvaluationStrictModel):
    """Axis definitions and records for one extraction artifact.

    Not a contract-stamped artifact: it is never persisted on its own, so it owns
    no governed model hash. The provenance fields record exactly the bindings the
    producer verified, so a caller can re-check them without re-deriving.
    """

    case_id: str
    evaluation_stage: ExtractionEvaluationStage
    prediction_record_id: str
    parsed_prediction_content_sha256: str
    subject_observation_id: str
    subject_canonical_target_reference: str | None
    axis_taxonomy_version: str
    axis_taxonomy_hash: str
    gold_assertion_set_version: str
    gold_assertion_set_hash: str
    axis_definitions: tuple[AxisDefinition, ...]
    axis_records: tuple[AxisEvaluationRecord, ...]


# --- Helpers ---------------------------------------------------------------


def _require_type(value: Any, expected: type, name: str) -> Any:
    if not isinstance(value, expected):
        raise TypeError(f"{name} must be a {expected.__name__}, got {type(value).__name__}")
    return value


def _gold_identity(entry: Any) -> tuple[Any, ...]:
    """The full six-part gold assertion identity.

    ``assertion_kind`` participates, so a bound entry can never be reconciled
    against a loaded entry of a different kind. Nullable parts are compared
    as-is: ``None`` and ``""`` stay distinct.
    """
    return (
        entry.case_id,
        entry.assertion_id,
        entry.assertion_semantic_version,
        entry.assertion_contract_hash,
        entry.assertion_kind,
        entry.canonical_target_reference,
    )


def _record_id(identity: tuple[Any, ...], axis_id: str) -> str:
    """``axis~<axis_id>~<full sha256>`` over the gold identity plus the axis.

    The digest is untruncated: the whole point of assertion-owned identity is
    that distinct assertions never merge, so no truncation risk is accepted.
    """
    digest = sha256_bytes(canonical_contract_bytes([*identity, axis_id]))
    return f"axis~{axis_id}~{digest}"


def _binding_subject(binding: LoadedObservationTargetBinding, stage: str) -> Any:
    subjects = [e for e in binding.model.entries if not e.parent_referenced]
    if len(subjects) != 1:
        raise ValueError("the binding must carry exactly one owning subject entry")
    subject = subjects[0]
    if subject.observation_kind != _STAGE_SUBJECT_KIND[stage]:
        raise ValueError("the binding subject kind does not match the stage subject kind")
    return subject


# --- Public producer -------------------------------------------------------


def build_extraction_axis_evaluation_records(
    *,
    case: EvaluationCase,
    evaluation_stage: ExtractionEvaluationStage,
    parsed_prediction_content: LoadedParsedPredictionContent,
    source_snapshot: LoadedSourcePassageSnapshotManifest,
    axis_taxonomy: LoadedAxisTaxonomy,
    gold: LoadedGoldAssertionSet,
    bound_gold: BoundGoldAssertionSet,
    run_manifest: EvaluationRunManifestV2,
    observation_target_binding: LoadedObservationTargetBinding,
) -> ExtractionAxisEvaluationInputs:
    """Produce the axis definitions and per-assertion axis records for one artifact."""
    # --- 1. Types and governed versions -----------------------------------
    _require_type(case, EvaluationCase, "case")
    _require_type(
        parsed_prediction_content, LoadedParsedPredictionContent, "parsed_prediction_content"
    )
    _require_type(source_snapshot, LoadedSourcePassageSnapshotManifest, "source_snapshot")
    _require_type(axis_taxonomy, LoadedAxisTaxonomy, "axis_taxonomy")
    _require_type(gold, LoadedGoldAssertionSet, "gold")
    _require_type(bound_gold, BoundGoldAssertionSet, "bound_gold")
    _require_type(run_manifest, EvaluationRunManifestV2, "run_manifest")
    _require_type(
        observation_target_binding, LoadedObservationTargetBinding, "observation_target_binding"
    )
    # A non-string stage is a wrong argument *type*; an unrecognised string is a
    # content violation. Membership is only meaningful once the type is known.
    if not isinstance(evaluation_stage, str):
        raise TypeError(
            f"evaluation_stage must be a str, got {type(evaluation_stage).__name__}"
        )
    if evaluation_stage not in EXTRACTION_EVALUATION_STAGES:
        raise ValueError("evaluation_stage must be a governed extraction evaluation stage")

    content = parsed_prediction_content.content
    binding_model = observation_target_binding.model

    # --- 2. Cross-artifact pins, in the governed order --------------------
    # 1
    if binding_model.eval_run_id != run_manifest.eval_run_id:
        raise ValueError("binding eval_run_id does not equal the run manifest's eval_run_id")
    # 2 - raw persisted-byte SHA-256. The binding's canonical references are only
    # meaningful relative to the target-registry snapshot they were resolved
    # against, so a binding built under a different registry must be rejected even
    # when every other pin matches. The run manifest pins no registry *version*,
    # so no version comparison is possible here and none is invented.
    if binding_model.target_registry_sha256 != run_manifest.registry_snapshot_hash:
        raise ValueError(
            "binding target_registry_sha256 does not equal the run manifest's "
            "registry_snapshot_hash"
        )
    # 3, 4 - taxonomy: scalar version, then the canonical content hash.
    if axis_taxonomy.version != run_manifest.axis_taxonomy_version:
        raise ValueError(
            "axis taxonomy version does not equal the run manifest's axis_taxonomy_version"
        )
    # The canonical hash helpers revalidate fail-closed and raise their own
    # governed error classes, which carry a reason_code and an artifact reference.
    # P3 exposes only TypeError and ordinary ValueError, so each known governed
    # failure is normalized here into a stable, content-free message. `from None`
    # drops the upstream exception so no reason_code or reference can leak.
    try:
        taxonomy_hash = axis_taxonomy_hash(axis_taxonomy.model)
    except AxisTaxonomyError:
        raise ValueError("the supplied axis taxonomy failed governed revalidation") from None
    if taxonomy_hash != run_manifest.axis_taxonomy_hash:
        raise ValueError(
            "axis taxonomy content hash does not equal the run manifest's axis_taxonomy_hash"
        )
    # 5, 6 - gold: scalar version, then the canonical content hash.
    if gold.model.gold_set_version != run_manifest.gold_assertion_set_version:
        raise ValueError(
            "gold set version does not equal the run manifest's gold_assertion_set_version"
        )
    try:
        gold_hash = gold_assertion_set_hash(gold.model)
    except GoldAssertionSetError:
        raise ValueError("the supplied gold assertion set failed governed revalidation") from None
    if gold_hash != run_manifest.gold_assertion_set_hash:
        raise ValueError(
            "gold set content hash does not equal the run manifest's gold_assertion_set_hash"
        )
    # 7, 8 - the bound set must derive from exactly these gold bytes.
    if bound_gold.gold_set_version != gold.model.gold_set_version:
        raise ValueError("bound gold set version does not equal the loaded gold set version")
    if bound_gold.sha256 != gold.sha256:
        raise ValueError("bound gold sha256 does not equal the loaded gold set's raw-byte sha256")
    # 9, 10 - source snapshot: scalar version, then the canonical content hash the
    # run recorded (never the loaded wrapper's raw persisted-byte sha256).
    if source_snapshot.version != run_manifest.source_passage_snapshot_version:
        raise ValueError(
            "source snapshot version does not equal the run manifest's "
            "source_passage_snapshot_version"
        )
    try:
        source_content_hash = source_passage_snapshot_manifest_hash(source_snapshot.manifest)
    except SourceSnapshotError:
        raise ValueError("the supplied source snapshot failed governed revalidation") from None
    if source_content_hash != run_manifest.source_passage_snapshot_hash:
        raise ValueError(
            "source snapshot content hash does not equal the run manifest's "
            "source_passage_snapshot_hash"
        )
    # 11, 12 - raw persisted-byte binding material.
    if binding_model.parsed_prediction_content_sha256 != parsed_prediction_content.sha256:
        raise ValueError(
            "binding parsed_prediction_content_sha256 does not equal the loaded content hash"
        )
    if binding_model.raw_artifact_sha256 != content.raw_artifact_sha256:
        raise ValueError("binding raw_artifact_sha256 does not equal the parsed content's")
    # 13 - case and stage coherence across all three carriers.
    if not (binding_model.case_id == case.case_id == content.case_id):
        raise ValueError("case_id does not agree across the case, parsed content, and binding")
    if not (
        binding_model.stage == case.stage == content.stage == evaluation_stage
    ):
        raise ValueError("stage does not agree across the case, parsed content, and binding")

    # --- 3. Owning subject ------------------------------------------------
    # The predicted canonical value comes directly from the one validated owning
    # subject entry. observations_by_canonical_target is a reverse index
    # (canonical -> observation IDs) and is deliberately not used here.
    subject = _binding_subject(observation_target_binding, evaluation_stage)
    subject_canonical = (
        subject.canonical_target_reference
        if subject.resolution_status == "resolved"
        else None
    )

    # --- 4. Taxonomy ------------------------------------------------------
    axes = tuple(axis_taxonomy.model.axes)
    axis_ids = [axis.axis_id for axis in axes]
    if len(set(axis_ids)) != len(axis_ids):
        raise ValueError("axis taxonomy must not declare a duplicate axis_id")

    # --- 5. Case-scoped source resolution + evidence resolvability --------
    try:
        resolved = resolve_case_source_passages(source_snapshot, case)
    except SourceSnapshotError:
        raise ValueError(
            "the case's declared sources and passages do not resolve against the "
            "supplied source snapshot"
        ) from None
    resolved_passage_ids = {passage.passage_id for passage in resolved.passages}
    subject_evidence = tuple(
        e for e in content.evidence_collection.evidence if e.entity_ref == subject.observation_id
    )
    evidence_resolvability = (
        "resolvable"
        if subject_evidence
        and all(e.passage_id in resolved_passage_ids for e in subject_evidence)
        else "insufficient_evidence"
    )

    # --- 6. Eligible gold entries ----------------------------------------
    eligible = [
        entry
        for entry in bound_gold.entries
        if entry.case_id == case.case_id
        and entry.assertion_kind == _ELIGIBLE_ASSERTION_KIND
    ]
    seen_identities: set[tuple[Any, ...]] = set()
    for entry in eligible:
        identity = _gold_identity(entry)
        if identity in seen_identities:
            raise ValueError(
                "two eligible bound gold entries share the same assertion identity; "
                "distinct assertions must never be collapsed"
            )
        seen_identities.add(identity)

    # Provenance lives only on the loaded gold set; reconcile on the full
    # six-part identity so an assertion_kind mismatch can never slip through.
    loaded_by_identity: dict[tuple[Any, ...], list[Any]] = {}
    for entry in gold.model.entries:
        loaded_by_identity.setdefault(_gold_identity(entry), []).append(entry)

    # --- 7. Records -------------------------------------------------------
    records: list[dict[str, Any]] = []
    for axis in axes:
        labels = set(axis.labels)
        matching = [e for e in eligible if e.canonical_target_reference in labels]
        if not matching:
            # An axis with no eligible gold entry emits zero records and keeps its
            # definition; that is legal and is not signalled by a sentinel.
            continue
        if subject_canonical is None:
            if not axis.abstention_allowed:
                raise ValueError(
                    f"axis {axis.axis_id!r} has an eligible gold record but the owning "
                    "subject is unresolved and the axis does not permit UNKNOWN"
                )
            predicted = (UNKNOWN,)
        else:
            if subject_canonical not in labels:
                raise ValueError(
                    f"the resolved subject canonical target is outside axis "
                    f"{axis.axis_id!r} vocabulary, which has an eligible gold record"
                )
            predicted = (subject_canonical,)
        for entry in matching:
            identity = _gold_identity(entry)
            matches = loaded_by_identity.get(identity, ())
            if len(matches) != 1:
                raise ValueError(
                    "a bound gold entry does not reconcile to exactly one loaded gold "
                    "entry on the full assertion identity"
                )
            records.append(
                {
                    "record_id": _record_id(identity, axis.axis_id),
                    "case_id": case.case_id,
                    "axis_id": axis.axis_id,
                    "metric_scope": _METRIC_SCOPE,
                    "verification_status": matches[0].provenance.verification_status,
                    "evidence_resolvability": evidence_resolvability,
                    "predicted_values": predicted,
                    "gold_values": (entry.canonical_target_reference,),
                }
            )

    records.sort(key=lambda r: (r["axis_id"], r["record_id"]))

    # --- 8. Assemble ------------------------------------------------------
    # Records are validated through the committed AxisEvaluationRecord model, so a
    # malformed value fails here rather than downstream.
    return ExtractionAxisEvaluationInputs.model_validate(
        {
            "case_id": case.case_id,
            "evaluation_stage": evaluation_stage,
            "prediction_record_id": content.prediction_record_id,
            "parsed_prediction_content_sha256": parsed_prediction_content.sha256,
            "subject_observation_id": subject.observation_id,
            "subject_canonical_target_reference": subject_canonical,
            "axis_taxonomy_version": axis_taxonomy.version,
            "axis_taxonomy_hash": taxonomy_hash,
            "gold_assertion_set_version": gold.model.gold_set_version,
            "gold_assertion_set_hash": gold_hash,
            "axis_definitions": list(axes),
            "axis_records": records,
        }
    )
