"""Observation-target binding (Xe-bind, SPEC-020/022 / ADR-024 / ADR-025 / ADR-026).

``observation_target_binding@0.1.0`` is the **only** artifact permitted to map the
raw extraction observation-identity namespace onto the canonical target-registry
namespace. Three namespaces stay separate:

* raw observation IDs — the prediction source, ``ParsedPredictionContent``
  ``entity_ref`` values, and parent-observation-snapshot member owner IDs;
* canonical target references — ``TargetRegistry`` ``reference_id`` values, gold
  ``canonical_target_reference``, case assertion ``target_references``, and axis
  labels;
* this binding — the bridge, produced *after* parsing and pinned by hash to the
  exact ``ParsedPredictionContent`` bytes and its raw artifact.

The mapping is **many-to-one**: two distinct raw observations may legitimately
resolve to the same canonical target, and that stays representable rather than
failing construction. ``observation_id`` remains unique (one decision per parsed
entity — a completeness bijection).

Adjudication crosses the public boundary as strict typed models, never dicts:
``ObservationTargetResolutionDecision`` carries the decision and its
``ObservationTargetResolutionProvenance`` carries both *how* the decision was
reached and the governance record (resolver/reviewer identity, verification
status, decision timestamps, change reason). The producer revalidates every
supplied decision fail-closed, reconciles it against the parsed content, the
case's own ``CaseResolution`` registry pins, and — for a parent-referenced
observation — the committed ``parent_observation_snapshot@0.1.0``, then builds
the persisted model.

Unresolved decisions are first-class: ``canonical_target_reference`` is a
*required* field that is present as JSON ``null`` exactly when
``resolution_status == "unresolved"``. It is never omitted, and it is never
silently upgraded to a resolved reference.

Importing this module performs no filesystem access, hashing, clock read, or
network call; all loading and persistence is explicit.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import (
    Field,
    ValidationError as PydanticValidationError,
    model_validator,
)

from .contracts import canonical_contract_bytes, model_contract_hash
from .models import (
    ContractStampedModel,
    EvaluationCase,
    EvaluationStrictModel,
    _reject_explicit_null,
    _require_non_blank,
    _require_rfc3339_offset,
)
from .parent_observation_snapshot import (
    LoadedParentObservationSnapshot,
    ParentObservationSnapshotError,
    verify_child_case_context,
)
from .prediction_content import LoadedParsedPredictionContent, ParsedPredictionContent
from .references import CaseResolution, LoadedTargetRegistry
from .stage_evidence import GoldVerificationStatus
from ..universe.io_utils import sha256_bytes

__all__ = [
    "EXTRACTION_EVALUATION_STAGES",
    "LoadedObservationTargetBinding",
    "ObservationTargetBinding",
    "ObservationTargetBindingError",
    "ObservationTargetResolutionDecision",
    "ObservationTargetResolutionProvenance",
    "build_observation_target_binding",
    "load_observation_target_binding",
    "observations_by_canonical_target",
    "persist_observation_target_binding",
    "unresolved_observation_ids",
]

_CONTRACT_ID = "observation_target_binding"
_CONTRACT_VERSION = "0.1.0"
_SNAPSHOTS_DIR = "snapshots"
_SNAPSHOT_FILENAME = "observation_target_binding.json"
_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"
_HEX = {"min_length": 64, "max_length": 64, "pattern": _SHA256_HEX_PATTERN}

# The governed extraction-stage vocabulary. Single source of truth for every
# consumer (both semantic evaluators and output-manifest v0.2); a drift test
# reconciles it with the semantic adapter's implemented-stage vocabulary.
EXTRACTION_EVALUATION_STAGES: frozenset[str] = frozenset(
    {"capability_extraction", "task_extraction"}
)

# The owning-subject entity kind of each extraction stage. Every other bound
# observation is a parent reference.
_STAGE_SUBJECT_KIND: dict[str, str] = {
    "capability_extraction": "capability",
    "task_extraction": "task",
}

# Parent-referenced observation kind -> the snapshot's verified owner-id set.
_PARENT_KIND_FIELD: dict[str, str] = {
    "product": "product_parent_ids",
    "capability": "capability_parent_ids",
}

# Omit-or-non-null optional properties: absence is legal, explicit JSON null is
# rejected rather than silently rewritten into absence. NOTE
# ``canonical_target_reference`` is deliberately NOT in any of these tuples: it is
# a required field whose JSON null is the mandated unresolved representation.
_PROVENANCE_OMIT_OR_NON_NULL = (
    "source_field_name",
    "source_field_value",
    "registry_entry_reference_id",
    "registry_entry_matched_alias",
    "unresolved_reason_code",
    "adjudication_reference",
)
_BINDING_OMIT_OR_NON_NULL = (
    "parent_observation_snapshot_version",
    "parent_observation_snapshot_sha256",
)


# --- Public error ----------------------------------------------------------


class ObservationTargetBindingError(Exception):
    """Sanitized binding failure with a stable machine-readable code.

    No raw content, absolute path, or raw Pydantic/OS text is placed in the
    message.
    """

    def __init__(
        self, message: str, *, reason_code: str, artifact_reference: str | None = None
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.artifact_reference = artifact_reference


class _DuplicateKeyControl(Exception):
    def __init__(self) -> None:
        super().__init__("duplicate JSON object key")


class _NonFiniteControl(Exception):
    def __init__(self) -> None:
        super().__init__("non-JSON numeric constant")


# --- Small local validators ------------------------------------------------


def _require_unique_non_blank(values: tuple[str, ...], field_name: str) -> None:
    for value in values:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError(f"each {field_name} entry must be a non-blank unstripped string")
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain a duplicate entry")


def _is_safe_reference(value: Any) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if value.startswith("/") or "\\" in value or "\x00" in value:
        return False
    return all(part not in ("", ".", "..") for part in value.split("/"))


def _is_lower_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


# --- Public adjudication models --------------------------------------------


class ObservationTargetResolutionProvenance(EvaluationStrictModel):
    """How one observation-target decision was reached, plus its governance record."""

    # How the decision was reached.
    resolution_method: Literal[
        "stable_identity_field",
        "registry_alias",
        "parent_link_field",
        "declared_unresolved",
    ]
    source_field_name: str | None = None
    source_field_value: str | None = None
    registry_entry_reference_id: str | None = None
    registry_entry_matched_alias: str | None = None
    unresolved_reason_code: str | None = None
    # Governance: never omitted, never inferred, never clock-generated here.
    resolver_kind: Literal["deterministic_rule", "model_assisted", "human_adjudicated"]
    resolver_ids: tuple[str, ...]
    reviewer_ids: tuple[str, ...] = ()
    verification_status: GoldVerificationStatus
    verification_method: Literal[
        "dual_independent_adjudication",
        "solo_blinded_retest",
        "expert_second_review",
        "deterministic_rule_review",
    ]
    decision_timestamps: tuple[str, ...]
    change_reason: str
    adjudication_reference: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_explicit_null(cls, data: Any) -> Any:
        return _reject_explicit_null(
            data, _PROVENANCE_OMIT_OR_NON_NULL, "ObservationTargetResolutionProvenance"
        )

    @model_validator(mode="after")
    def _provenance_invariants(self) -> "ObservationTargetResolutionProvenance":
        method_fields = (
            self.source_field_name,
            self.source_field_value,
            self.registry_entry_reference_id,
            self.registry_entry_matched_alias,
        )
        if self.resolution_method == "declared_unresolved":
            if self.unresolved_reason_code is None:
                raise ValueError("declared_unresolved requires an unresolved_reason_code")
            _require_non_blank(self.unresolved_reason_code, "unresolved_reason_code")
            if any(value is not None for value in method_fields):
                raise ValueError(
                    "declared_unresolved must not carry any resolution/source field"
                )
        else:
            if self.unresolved_reason_code is not None:
                raise ValueError("a resolving method must not carry an unresolved_reason_code")
            if self.registry_entry_reference_id is None:
                raise ValueError("a resolving method requires a registry_entry_reference_id")
            _require_non_blank(self.registry_entry_reference_id, "registry_entry_reference_id")
            if self.resolution_method in ("stable_identity_field", "parent_link_field"):
                if self.source_field_name is None or self.source_field_value is None:
                    raise ValueError(
                        "a field-derived method requires source_field_name and "
                        "source_field_value"
                    )
                _require_non_blank(self.source_field_name, "source_field_name")
                _require_non_blank(self.source_field_value, "source_field_value")
            if self.resolution_method == "registry_alias":
                if self.registry_entry_matched_alias is None:
                    raise ValueError("registry_alias requires a registry_entry_matched_alias")
                _require_non_blank(
                    self.registry_entry_matched_alias, "registry_entry_matched_alias"
                )
        # Governance invariants.
        if not self.resolver_ids:
            raise ValueError("resolver_ids must not be empty")
        _require_unique_non_blank(self.resolver_ids, "resolver_ids")
        _require_unique_non_blank(self.reviewer_ids, "reviewer_ids")
        if set(self.resolver_ids) & set(self.reviewer_ids):
            raise ValueError("self_review_forbidden: resolver_ids and reviewer_ids must be disjoint")
        if self.verification_status == "verified" and not self.reviewer_ids:
            raise ValueError("a verified decision requires at least one reviewer id")
        if self.resolver_kind == "human_adjudicated":
            if not self.reviewer_ids:
                raise ValueError("a human-adjudicated decision requires at least one reviewer id")
            if self.adjudication_reference is None:
                raise ValueError(
                    "a human-adjudicated decision requires an adjudication_reference"
                )
        if (
            self.verification_method == "deterministic_rule_review"
            and self.resolver_kind != "deterministic_rule"
        ):
            raise ValueError(
                "deterministic_rule_review applies only to a deterministic_rule resolver"
            )
        if not self.decision_timestamps:
            raise ValueError("decision_timestamps must not be empty")
        for stamp in self.decision_timestamps:
            _require_rfc3339_offset(stamp, "decision_timestamps entry")
        _require_non_blank(self.change_reason, "change_reason")
        if self.adjudication_reference is not None and not _is_safe_reference(
            self.adjudication_reference
        ):
            raise ValueError("adjudication_reference must be a safe relative reference")
        return self


class ObservationTargetResolutionDecision(EvaluationStrictModel):
    """One adjudicated raw-observation -> canonical-target decision.

    ``canonical_target_reference`` is a **required** field, not an
    omit-or-non-null optional: a resolved decision carries a non-blank string, an
    unresolved decision carries JSON ``null``, and it is never omitted.
    """

    observation_id: str
    observation_kind: Literal["product", "capability", "task"]
    resolution_status: Literal["resolved", "unresolved"]
    canonical_target_reference: str | None
    parent_referenced: bool
    provenance: ObservationTargetResolutionProvenance

    @model_validator(mode="after")
    def _decision_invariants(self) -> "ObservationTargetResolutionDecision":
        _require_non_blank(self.observation_id, "observation_id")
        if self.resolution_status == "resolved":
            if self.canonical_target_reference is None:
                raise ValueError(
                    "a resolved decision requires a non-null canonical_target_reference"
                )
            _require_non_blank(self.canonical_target_reference, "canonical_target_reference")
            if self.provenance.resolution_method == "declared_unresolved":
                raise ValueError("a resolved decision must not declare an unresolved method")
        else:
            if self.canonical_target_reference is not None:
                raise ValueError(
                    "an unresolved decision requires canonical_target_reference to be null"
                )
            if self.provenance.resolution_method != "declared_unresolved":
                raise ValueError(
                    "an unresolved decision requires the declared_unresolved method"
                )
        return self

    @property
    def _identity(self) -> str:
        return self.observation_id


# --- Persisted model -------------------------------------------------------


class ObservationTargetBinding(ContractStampedModel):
    # Docstring intentionally omitted so the generated JSON Schema (and thus the
    # governed model-contract hash) carries no description.
    _contract_id: ClassVar[str] = _CONTRACT_ID
    _contract_version: ClassVar[str] = _CONTRACT_VERSION

    eval_run_id: str
    case_id: str
    company_id: str
    stage: str
    prediction_record_id: str
    raw_artifact_reference: str
    raw_artifact_sha256: str = Field(**_HEX)
    parsed_prediction_content_sha256: str = Field(**_HEX)
    parsed_prediction_content_artifact_reference: str
    target_registry_version: str
    target_registry_sha256: str = Field(**_HEX)
    # Paired parent-snapshot pins, coupled to the entry set by model validation:
    # present together exactly when some entry is parent-referenced, absent
    # together otherwise. Explicit null is rejected in either case.
    parent_observation_snapshot_version: str | None = None
    parent_observation_snapshot_sha256: str | None = Field(default=None, **_HEX)
    resolved_observation_count: int = Field(ge=0)
    unresolved_observation_count: int = Field(ge=0)
    entries: tuple[ObservationTargetResolutionDecision, ...]

    @model_validator(mode="before")
    @classmethod
    def _no_explicit_null_pins(cls, data: Any) -> Any:
        return _reject_explicit_null(data, _BINDING_OMIT_OR_NON_NULL, "ObservationTargetBinding")

    @model_validator(mode="after")
    def _binding_invariants(self) -> "ObservationTargetBinding":
        for name in (
            "eval_run_id", "case_id", "company_id", "stage", "prediction_record_id",
            "parsed_prediction_content_artifact_reference", "target_registry_version",
        ):
            _require_non_blank(getattr(self, name), name)
        if self.stage not in EXTRACTION_EVALUATION_STAGES:
            raise ValueError("stage must be a governed extraction evaluation stage")
        for name in ("raw_artifact_reference", "parsed_prediction_content_artifact_reference"):
            if not _is_safe_reference(getattr(self, name)):
                raise ValueError(f"{name} must be a safe relative reference")
        pins = (
            self.parent_observation_snapshot_version,
            self.parent_observation_snapshot_sha256,
        )
        if (pins[0] is None) != (pins[1] is None):
            raise ValueError("the parent-snapshot version/hash pins are present together or absent")
        if pins[0] is not None:
            _require_non_blank(pins[0], "parent_observation_snapshot_version")
        if not self.entries:
            raise ValueError("entries must not be empty")
        ids = [entry.observation_id for entry in self.entries]
        if ids != sorted(ids):
            raise ValueError("entries must be sorted canonically by observation_id")
        if len(set(ids)) != len(ids):
            raise ValueError("entries must not contain a duplicate observation_id")
        resolved = sum(1 for e in self.entries if e.resolution_status == "resolved")
        unresolved = len(self.entries) - resolved
        if self.resolved_observation_count != resolved:
            raise ValueError("resolved_observation_count must equal the resolved entry count")
        if self.unresolved_observation_count != unresolved:
            raise ValueError("unresolved_observation_count must equal the unresolved entry count")
        # A parent-referenced observation is never the owning subject; exactly one
        # subject exists and its kind is the stage's subject kind.
        subjects = [e for e in self.entries if not e.parent_referenced]
        if len(subjects) != 1:
            raise ValueError("exactly one entry must be the owning subject")
        if subjects[0].observation_kind != _STAGE_SUBJECT_KIND[self.stage]:
            raise ValueError("the owning subject kind must match the stage subject kind")
        # The parent-snapshot pins are coupled to the entry set, not merely paired
        # with each other: a parent-referenced observation is unverifiable without
        # the snapshot it was checked against, and a parent-free binding must not
        # claim a snapshot it never needed. Enforced here so a hand-written or
        # reloaded document cannot bypass the producer's check.
        has_parent_references = any(entry.parent_referenced for entry in self.entries)
        if has_parent_references and pins[0] is None:
            raise ValueError(
                "parent_snapshot_pins_required: a parent-referenced entry requires both "
                "parent_observation_snapshot_version and parent_observation_snapshot_sha256"
            )
        if not has_parent_references and pins[0] is not None:
            raise ValueError(
                "parent_snapshot_pins_forbidden: a binding with no parent-referenced entry "
                "must omit both parent-snapshot pins"
            )
        for entry in self.entries:
            if entry.parent_referenced and entry.observation_kind not in _PARENT_KIND_FIELD:
                raise ValueError("a task observation must not be a parent reference")
        return self


class LoadedObservationTargetBinding(EvaluationStrictModel):
    """A validated binding plus its raw-byte binding material."""

    model: ObservationTargetBinding
    version: str
    sha256: str
    artifact_reference: str


# --- Fail-closed revalidation ---------------------------------------------
#
# ``model_copy(update=...)`` and ``model_construct(...)`` bypass Pydantic
# validators, so an object can satisfy ``isinstance`` while carrying content that
# never passed the governed invariants. Every public API revalidates a supplied
# instance by dumping it and re-running full validation, then operates on the
# revalidated result. ``exclude_unset`` preserves omit-or-non-null semantics for
# optional properties; the required ``canonical_target_reference`` is always set,
# so an unresolved decision round-trips with its JSON null intact.


def _revalidate_decision(
    decision: ObservationTargetResolutionDecision,
) -> ObservationTargetResolutionDecision:
    if not isinstance(decision, ObservationTargetResolutionDecision):
        raise TypeError(
            "each resolution entry must be an ObservationTargetResolutionDecision, "
            f"got {type(decision).__name__}"
        )
    try:
        payload = decision.model_dump(mode="json", exclude_unset=True)
    except Exception as exc:  # noqa: BLE001 - any serialization defect fails closed
        raise ObservationTargetBindingError(
            "a resolution decision could not be serialized for revalidation",
            reason_code="decision_validation",
        ) from exc
    try:
        return ObservationTargetResolutionDecision.model_validate(payload)
    except PydanticValidationError as exc:
        raise ObservationTargetBindingError(
            "a resolution decision failed fail-closed revalidation",
            reason_code="decision_validation",
        ) from exc


def _revalidate_binding(binding: ObservationTargetBinding) -> ObservationTargetBinding:
    if not isinstance(binding, ObservationTargetBinding):
        raise TypeError(f"expected an ObservationTargetBinding, got {type(binding).__name__}")
    try:
        payload = binding.model_dump(mode="json", exclude_unset=True)
    except Exception as exc:  # noqa: BLE001 - any serialization defect fails closed
        raise ObservationTargetBindingError(
            "binding could not be serialized for revalidation", reason_code="model_validation"
        ) from exc
    try:
        return ObservationTargetBinding.model_validate(payload)
    except PydanticValidationError as exc:
        raise ObservationTargetBindingError(
            "binding failed fail-closed revalidation", reason_code="model_validation"
        ) from exc


def _revalidate_parsed(content: ParsedPredictionContent) -> ParsedPredictionContent:
    if not isinstance(content, ParsedPredictionContent):
        raise TypeError(f"expected a ParsedPredictionContent, got {type(content).__name__}")
    try:
        payload = content.model_dump(mode="json", exclude_unset=True)
        return ParsedPredictionContent.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 - any defect fails closed
        raise ObservationTargetBindingError(
            "parsed content failed fail-closed revalidation",
            reason_code="parsed_content_validation",
        ) from exc


def _contract_metadata() -> dict[str, str]:
    return {
        "contract_id": _CONTRACT_ID,
        "contract_version": _CONTRACT_VERSION,
        "contract_hash": model_contract_hash(
            ObservationTargetBinding, _CONTRACT_ID, _CONTRACT_VERSION
        ),
    }


# --- Pure accessors --------------------------------------------------------


def observations_by_canonical_target(
    binding: ObservationTargetBinding,
) -> dict[str, tuple[str, ...]]:
    """Map each resolved canonical target to its ascending mapped observation IDs.

    The mapping is many-to-one, so a canonical target may carry more than one
    observation ID. Unresolved entries never appear.
    """
    validated = _revalidate_binding(binding)
    index: dict[str, list[str]] = {}
    for entry in validated.entries:
        canonical = entry.canonical_target_reference
        if entry.resolution_status != "resolved" or canonical is None:
            continue
        index.setdefault(canonical, []).append(entry.observation_id)
    return {key: tuple(sorted(value)) for key, value in sorted(index.items())}


def unresolved_observation_ids(binding: ObservationTargetBinding) -> tuple[str, ...]:
    """The ascending observation IDs of every present unresolved decision."""
    validated = _revalidate_binding(binding)
    return tuple(
        sorted(e.observation_id for e in validated.entries if e.resolution_status == "unresolved")
    )


# --- Producer --------------------------------------------------------------


def build_observation_target_binding(
    *,
    eval_run_id: str,
    case: EvaluationCase,
    company_id: str,
    resolution: CaseResolution,
    parsed_prediction_content: LoadedParsedPredictionContent,
    target_registry: LoadedTargetRegistry,
    resolution_entries: tuple[ObservationTargetResolutionDecision, ...],
    parent_snapshot: LoadedParentObservationSnapshot | None = None,
) -> ObservationTargetBinding:
    """Reconcile adjudicated decisions into an ``observation_target_binding@0.1.0``.

    Pure with respect to network/clock/provider state; hashing supplied bytes and
    reading the supplied wrappers' already-verified material is permitted. Every
    supplied decision is revalidated fail-closed, then reconciled against: the
    parsed content's entity space (a one-to-one completeness bijection on
    ``observation_id``), the case's own ``CaseResolution`` target-registry pins,
    the registry's canonical references and accepted aliases, the stage's
    owning-subject shape, and — whenever any observation is parent-referenced —
    the committed parent-observation snapshot's verified owner sets and
    case/company/cutoff context.

    The mapping may be many-to-one. Unresolved decisions are preserved verbatim,
    counted, and never upgraded. The snapshot proves parent existence, role, and
    context only; it never establishes canonical target identity.
    """
    run_id = _validate_run_id(eval_run_id)
    if not isinstance(case, EvaluationCase):
        raise TypeError(f"case must be an EvaluationCase, got {type(case).__name__}")
    if not isinstance(resolution, CaseResolution):
        raise TypeError(f"resolution must be a CaseResolution, got {type(resolution).__name__}")
    if not isinstance(parsed_prediction_content, LoadedParsedPredictionContent):
        raise TypeError(
            "parsed_prediction_content must be a LoadedParsedPredictionContent, got "
            f"{type(parsed_prediction_content).__name__}"
        )
    if not isinstance(target_registry, LoadedTargetRegistry):
        raise TypeError(
            f"target_registry must be a LoadedTargetRegistry, got {type(target_registry).__name__}"
        )
    if not isinstance(resolution_entries, tuple):
        raise TypeError("resolution_entries must be a tuple of decisions")
    if parent_snapshot is not None and not isinstance(
        parent_snapshot, LoadedParentObservationSnapshot
    ):
        raise TypeError(
            "parent_snapshot must be a LoadedParentObservationSnapshot, got "
            f"{type(parent_snapshot).__name__}"
        )
    if not isinstance(company_id, str) or not company_id or company_id != company_id.strip():
        raise ObservationTargetBindingError(
            "company_id must be a non-blank unstripped string", reason_code="invalid_company_id"
        )

    content = _revalidate_parsed(parsed_prediction_content.content)

    # --- Case/parsed-content agreement + stage governance ---
    if content.case_id != case.case_id:
        raise ObservationTargetBindingError(
            "parsed content case_id does not equal the case", reason_code="case_id_mismatch"
        )
    if content.stage != case.stage:
        raise ObservationTargetBindingError(
            "parsed content stage does not equal the case stage", reason_code="stage_mismatch"
        )
    if content.stage not in EXTRACTION_EVALUATION_STAGES:
        raise ObservationTargetBindingError(
            "a binding exists only for a governed extraction stage",
            reason_code="non_extraction_stage",
        )
    stage = content.stage

    # --- The case's own resolved registry pin (checked before persistence) ---
    if resolution.case_id != case.case_id:
        raise ObservationTargetBindingError(
            "case resolution case_id does not equal the case",
            reason_code="resolution_case_id_mismatch",
        )
    if target_registry.version != target_registry.registry.registry_version:
        raise ObservationTargetBindingError(
            "the loaded target-registry wrapper version disagrees with its registry",
            reason_code="target_registry_wrapper_inconsistent",
        )
    if resolution.target_registry_version != target_registry.version:
        raise ObservationTargetBindingError(
            "case resolution target_registry_version does not equal the supplied registry",
            reason_code="resolution_target_registry_version_mismatch",
        )
    if resolution.target_registry_sha256 != target_registry.sha256:
        raise ObservationTargetBindingError(
            "case resolution target_registry_sha256 does not equal the supplied registry",
            reason_code="resolution_target_registry_sha256_mismatch",
        )

    # --- The entity space must be complete for a bijection to exist ---
    if content.entity_collection.completeness != "complete":
        raise ObservationTargetBindingError(
            "a binding requires a complete parsed entity collection",
            reason_code="parsed_content_incomplete",
        )

    decisions = tuple(_revalidate_decision(entry) for entry in resolution_entries)
    if not decisions:
        raise ObservationTargetBindingError(
            "resolution_entries must not be empty", reason_code="observation_unbound"
        )

    # --- Completeness bijection against the parsed entity space ---
    parsed_kinds: dict[str, str] = {}
    for entity in content.entity_collection.entities:
        parsed_kinds[entity.entity_ref] = entity.entity_kind
    decided_ids = [d.observation_id for d in decisions]
    if len(set(decided_ids)) != len(decided_ids):
        raise ObservationTargetBindingError(
            "resolution_entries contain a duplicate observation_id",
            reason_code="duplicate_observation_decision",
        )
    for decision in decisions:
        if decision.observation_id not in parsed_kinds:
            raise ObservationTargetBindingError(
                "a decision references an observation absent from the parsed entity space",
                reason_code="observation_not_in_parsed_content",
            )
        if parsed_kinds[decision.observation_id] != decision.observation_kind:
            raise ObservationTargetBindingError(
                "a decision observation_kind does not equal the parsed entity kind",
                reason_code="observation_kind_mismatch",
            )
    if set(decided_ids) != set(parsed_kinds):
        raise ObservationTargetBindingError(
            "every parsed observation requires exactly one resolution decision",
            reason_code="observation_unbound",
        )

    # --- Canonical references resolve in the registry (many-to-one allowed) ---
    by_reference_id = {e.reference_id: e for e in target_registry.registry.entries}
    for decision in decisions:
        if decision.resolution_status != "resolved":
            continue
        canonical = decision.canonical_target_reference
        provenance = decision.provenance
        if provenance.registry_entry_reference_id != canonical:
            raise ObservationTargetBindingError(
                "decision provenance registry_entry_reference_id does not equal the "
                "canonical_target_reference",
                reason_code="provenance_reference_disagreement",
            )
        entry = by_reference_id.get(canonical)
        if entry is None:
            raise ObservationTargetBindingError(
                "a resolved canonical_target_reference is absent from the target registry",
                reason_code="canonical_target_reference_unknown",
            )
        if provenance.resolution_method == "registry_alias":
            if provenance.registry_entry_matched_alias not in entry.aliases:
                raise ObservationTargetBindingError(
                    "the matched alias is not an accepted alias of the canonical entry",
                    reason_code="canonical_target_reference_unknown",
                )

    # --- Owning-subject / parent-reference shape ---
    subjects = [d for d in decisions if not d.parent_referenced]
    if len(subjects) != 1:
        raise ObservationTargetBindingError(
            "exactly one decision must be the owning subject",
            reason_code="owning_subject_ambiguous",
        )
    if subjects[0].observation_kind != _STAGE_SUBJECT_KIND[stage]:
        raise ObservationTargetBindingError(
            "the owning subject kind does not match the stage subject kind",
            reason_code="owning_subject_kind_mismatch",
        )
    parents = [d for d in decisions if d.parent_referenced]
    for parent in parents:
        if parent.observation_kind not in _PARENT_KIND_FIELD:
            raise ObservationTargetBindingError(
                "a task observation must not be declared as a parent reference",
                reason_code="parent_role_unsupported",
            )

    # --- Mandatory committed parent-snapshot verification ---
    snapshot_version: str | None = None
    snapshot_sha256: str | None = None
    if parents:
        if parent_snapshot is None:
            raise ObservationTargetBindingError(
                "a parent-referenced observation requires the committed parent-observation "
                "snapshot",
                reason_code="parent_snapshot_required",
            )
        try:
            verify_child_case_context(
                parent_snapshot,
                case_id=case.case_id,
                company_id=company_id,
                observation_cutoff=content.observation_cutoff,
            )
        except ParentObservationSnapshotError as exc:
            raise ObservationTargetBindingError(
                "the parent-observation snapshot context does not equal the child case context",
                reason_code="case_context_mismatch",
                artifact_reference=parent_snapshot.artifact_reference,
            ) from exc
        owner_sets = {
            kind: set(getattr(parent_snapshot, field))
            for kind, field in _PARENT_KIND_FIELD.items()
        }
        for parent in parents:
            own_kind = parent.observation_kind
            if parent.observation_id not in owner_sets[own_kind]:
                other = {
                    kind for kind, ids in owner_sets.items()
                    if kind != own_kind and parent.observation_id in ids
                }
                raise ObservationTargetBindingError(
                    "a parent-referenced observation is present under a different snapshot role"
                    if other else
                    "a parent-referenced observation is absent from the parent snapshot",
                    reason_code="parent_role_mismatch" if other else "parent_observation_absent",
                    artifact_reference=parent_snapshot.artifact_reference,
                )
        snapshot_version = parent_snapshot.version
        snapshot_sha256 = parent_snapshot.sha256
    # A parsed content that carries its own company identity must agree with the
    # supplied claim (the task-stage observation contract carries ``company_id``).
    for field_value in content.field_value_collection.field_values:
        if field_value.field_name == "company_id" and field_value.field_value != company_id:
            raise ObservationTargetBindingError(
                "parsed content company_id disagrees with the supplied company_id",
                reason_code="company_id_disagreement",
            )

    resolved_count = sum(1 for d in decisions if d.resolution_status == "resolved")
    document: dict[str, Any] = {
        "contract": _contract_metadata(),
        "eval_run_id": run_id,
        "case_id": case.case_id,
        "company_id": company_id,
        "stage": stage,
        "prediction_record_id": content.prediction_record_id,
        "raw_artifact_reference": content.raw_artifact_reference,
        "raw_artifact_sha256": content.raw_artifact_sha256,
        "parsed_prediction_content_sha256": parsed_prediction_content.sha256,
        "parsed_prediction_content_artifact_reference":
            parsed_prediction_content.artifact_reference,
        "target_registry_version": resolution.target_registry_version,
        "target_registry_sha256": resolution.target_registry_sha256,
        "resolved_observation_count": resolved_count,
        "unresolved_observation_count": len(decisions) - resolved_count,
        "entries": [
            d.model_dump(mode="json", exclude_unset=True)
            for d in sorted(decisions, key=lambda d: d.observation_id)
        ],
    }
    if snapshot_version is not None:
        document["parent_observation_snapshot_version"] = snapshot_version
        document["parent_observation_snapshot_sha256"] = snapshot_sha256
    try:
        return ObservationTargetBinding.model_validate(document)
    except PydanticValidationError as exc:
        raise ObservationTargetBindingError(
            "the assembled binding failed contract validation", reason_code="model_validation"
        ) from exc


# --- Roots / references / strict parse -------------------------------------


def _validate_run_id(eval_run_id: Any) -> str:
    if not isinstance(eval_run_id, str):
        raise ObservationTargetBindingError(
            f"eval_run_id must be a string, got {type(eval_run_id).__name__}",
            reason_code="invalid_eval_run_id",
        )
    if not eval_run_id or eval_run_id != eval_run_id.strip():
        raise ObservationTargetBindingError(
            "eval_run_id must be a non-empty string without leading or trailing whitespace",
            reason_code="invalid_eval_run_id",
        )
    if eval_run_id in (".", ".."):
        raise ObservationTargetBindingError(
            "eval_run_id is not a valid path component", reason_code="invalid_eval_run_id"
        )
    if "/" in eval_run_id or "\\" in eval_run_id or "\x00" in eval_run_id:
        raise ObservationTargetBindingError(
            "eval_run_id must be a single path component without separators or NUL",
            reason_code="invalid_eval_run_id",
        )
    if Path(eval_run_id).is_absolute() or len(Path(eval_run_id).parts) != 1:
        raise ObservationTargetBindingError(
            "eval_run_id must be exactly one relative path component",
            reason_code="invalid_eval_run_id",
        )
    return eval_run_id


def _validate_eval_root(eval_root: str | Path) -> Path:
    if not isinstance(eval_root, (str, Path)):
        raise ObservationTargetBindingError(
            "eval_root must be an explicit str or Path evaluation root",
            reason_code="invalid_eval_root",
        )
    if isinstance(eval_root, str) and eval_root == "":
        raise ObservationTargetBindingError(
            "eval_root must not be an empty string", reason_code="invalid_eval_root"
        )
    root = Path(eval_root)
    if root.is_symlink():
        raise ObservationTargetBindingError(
            "eval_root must not be a symlink", reason_code="eval_root_symlink"
        )
    if not root.exists() or not root.is_dir():
        raise ObservationTargetBindingError(
            "evaluation root does not exist or is not a directory",
            reason_code="invalid_eval_root",
        )
    return root.resolve()


def _resolve_contained(reference: str, resolved_root: Path) -> tuple[Path, str]:
    if not _is_safe_reference(reference):
        raise ObservationTargetBindingError(
            "the binding reference is not a safe relative reference",
            reason_code="unsafe_reference", artifact_reference=str(reference),
        )
    candidate = resolved_root / reference
    parts: list[Path] = []
    cur = candidate
    while True:
        parts.append(cur)
        if cur == resolved_root or cur.parent == cur:
            break
        cur = cur.parent
    for part in parts:
        if part.is_symlink():
            raise ObservationTargetBindingError(
                "a binding path component is a symlink",
                reason_code="artifact_symlink", artifact_reference=reference,
            )
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ObservationTargetBindingError(
            "the binding resolves outside the evaluation root",
            reason_code="path_escape", artifact_reference=reference,
        )
    if not resolved.exists():
        raise ObservationTargetBindingError(
            "the binding does not exist under the evaluation root",
            reason_code="artifact_missing", artifact_reference=reference,
        )
    if not resolved.is_file():
        raise ObservationTargetBindingError(
            "the binding is not a regular file",
            reason_code="artifact_not_a_file", artifact_reference=reference,
        )
    return resolved, reference


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise _DuplicateKeyControl()
        seen.add(key)
        result[key] = value
    return result


def _reject_non_finite_constant(_name: str) -> Any:
    raise _NonFiniteControl()


def _has_non_finite(payload: Any) -> bool:
    stack = [payload]
    while stack:
        value = stack.pop()
        if isinstance(value, float) and not math.isfinite(value):
            return True
        elif isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return False


# --- Persistence -----------------------------------------------------------


def persist_observation_target_binding(
    binding: ObservationTargetBinding, *, eval_root: str | Path, eval_run_id: str
) -> LoadedObservationTargetBinding:
    """Write canonical binding JSON (plus one terminal newline) write-once.

    Destination:
    ``<eval_root>/<eval_run_id>/snapshots/observation_target_binding.json``.
    """
    validated = _revalidate_binding(binding)
    resolved_root = _validate_eval_root(eval_root)
    run_id = _validate_run_id(eval_run_id)
    if validated.eval_run_id != run_id:
        raise ObservationTargetBindingError(
            "the binding's eval_run_id does not equal the explicit persistence eval_run_id",
            reason_code="persist_eval_run_id_mismatch",
        )
    run_dir = resolved_root / run_id
    if run_dir.is_symlink():
        raise ObservationTargetBindingError(
            "run directory is a symlink", reason_code="run_directory_symlink"
        )
    if not run_dir.exists():
        raise ObservationTargetBindingError(
            "run directory does not exist under the evaluation root",
            reason_code="run_directory_missing", artifact_reference=run_id,
        )
    if not run_dir.is_dir():
        raise ObservationTargetBindingError(
            "run directory is not a directory",
            reason_code="run_directory_not_a_directory", artifact_reference=run_id,
        )
    snapshots_dir = run_dir / _SNAPSHOTS_DIR
    if snapshots_dir.is_symlink():
        raise ObservationTargetBindingError(
            "run snapshots directory is a symlink", reason_code="snapshots_directory_symlink"
        )
    if snapshots_dir.exists():
        if not snapshots_dir.is_dir():
            raise ObservationTargetBindingError(
                "run snapshots path is not a directory",
                reason_code="snapshots_directory_not_a_directory",
            )
    else:
        try:
            snapshots_dir.mkdir(exist_ok=False)
        except OSError as exc:
            raise ObservationTargetBindingError(
                "failed to create the run snapshots directory", reason_code="write_error",
                artifact_reference=f"{run_id}/{_SNAPSHOTS_DIR}",
            ) from exc
    reference = f"{run_id}/{_SNAPSHOTS_DIR}/{_SNAPSHOT_FILENAME}"
    dest = snapshots_dir / _SNAPSHOT_FILENAME
    if dest.is_symlink() or dest.exists():
        raise ObservationTargetBindingError(
            "the binding already exists; snapshots are write-once",
            reason_code="artifact_exists", artifact_reference=reference,
        )
    data = canonical_contract_bytes(validated.model_dump(mode="json", exclude_unset=True)) + b"\n"
    expected = sha256_bytes(data)
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise ObservationTargetBindingError(
            "the binding already exists; snapshots are write-once",
            reason_code="artifact_exists", artifact_reference=reference,
        ) from exc
    except OSError as exc:
        raise ObservationTargetBindingError(
            "failed to create the binding", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ObservationTargetBindingError(
            "failed to write the binding", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        observed = sha256_bytes(dest.read_bytes())
    except OSError as exc:
        raise ObservationTargetBindingError(
            "failed to re-read the binding for verification", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    if observed != expected:
        raise ObservationTargetBindingError(
            "persisted binding re-read to a different hash",
            reason_code="destination_hash_mismatch", artifact_reference=reference,
        )
    return LoadedObservationTargetBinding(
        model=validated, version=validated.contract.contract_version,
        sha256=observed, artifact_reference=reference,
    )


# --- Loader ---------------------------------------------------------------


def load_observation_target_binding(
    path: str | Path, *, eval_root: str | Path, expected_sha256: str | None = None
) -> LoadedObservationTargetBinding:
    """Load, hash-bind, and strictly validate one persisted binding."""
    resolved_root = _validate_eval_root(eval_root)
    if not isinstance(path, (str, Path)):
        raise ObservationTargetBindingError(
            "path must be an explicit str or Path", reason_code="invalid_path"
        )
    resolved, reference = _resolve_contained(str(path), resolved_root)
    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        raise ObservationTargetBindingError(
            "failed to read the binding", reason_code="read_error",
            artifact_reference=reference,
        ) from exc
    observed = sha256_bytes(raw)
    if expected_sha256 is not None:
        if not _is_lower_sha256_hex(expected_sha256) or expected_sha256 != observed:
            raise ObservationTargetBindingError(
                "binding raw-byte hash does not match the expected hash",
                reason_code="expected_hash_mismatch", artifact_reference=reference,
            )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ObservationTargetBindingError(
            "the binding is not valid UTF-8", reason_code="decode_error",
            artifact_reference=reference,
        ) from exc
    if text.startswith("\ufeff"):
        raise ObservationTargetBindingError(
            "the binding has a UTF-8 BOM", reason_code="bom", artifact_reference=reference
        )
    try:
        payload = json.loads(
            text, object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except json.JSONDecodeError as exc:
        raise ObservationTargetBindingError(
            "the binding is not valid JSON", reason_code="json_error",
            artifact_reference=reference,
        ) from exc
    except _DuplicateKeyControl as exc:
        raise ObservationTargetBindingError(
            "the binding contains a duplicate JSON object key",
            reason_code="duplicate_key", artifact_reference=reference,
        ) from exc
    except _NonFiniteControl as exc:
        raise ObservationTargetBindingError(
            "the binding contains a non-JSON numeric constant",
            reason_code="non_finite", artifact_reference=reference,
        ) from exc
    if _has_non_finite(payload):
        raise ObservationTargetBindingError(
            "the binding contains a non-finite JSON number",
            reason_code="non_finite", artifact_reference=reference,
        )
    if not isinstance(payload, dict):
        raise ObservationTargetBindingError(
            "the binding top-level value must be a JSON object",
            reason_code="top_level_type", artifact_reference=reference,
        )
    try:
        model = ObservationTargetBinding.model_validate(payload)
    except PydanticValidationError as exc:
        raise ObservationTargetBindingError(
            "the binding failed strict contract validation",
            reason_code="model_validation", artifact_reference=reference,
        ) from exc
    return LoadedObservationTargetBinding(
        model=model, version=model.contract.contract_version,
        sha256=observed, artifact_reference=reference,
    )
