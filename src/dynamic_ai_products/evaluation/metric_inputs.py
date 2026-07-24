"""Stamped active metric-input snapshot (Slice 12I, SPEC-020 / ADR-024).

``metric_input_snapshot@0.1.0`` is the first persisted, strict, frozen,
extra-forbid, model-contract-hash-governed metric-input contract. It carries the
run/case/scoring identity, the non-Universe metric-input member collections
(axis definitions/records, assertion bindings, validator-rule evaluations), and a
``MetricApplicabilityBinding`` that is the authoritative carrier of the
evaluation stage, the resolved stage-profile applicability, and — for Universe
stages only — the embedded ``StageMetricEvidenceSet`` (screen/tier/unsafe
payloads). Extraction stages carry no evidence binding fields at all.

This module is the owner of the re-homed public metric-input member models
(``AxisDefinition``, ``AxisEvaluationRecord``, ``AssertionMetricBinding``,
``ValidatorRuleEvaluationRecord``, ``MetricInputSnapshot``,
``metric_input_snapshot_hash``); ``metrics.py`` re-imports them for backward
compatibility, so every historical public symbol resolves to the same object.
It imports ``stage_evidence`` (leaf) and ``stage_profiles`` but never
``metrics``, so no import cycle is possible.

``build_metric_input_snapshot`` is the sole sanctioned active producer: it
requires an ``EvaluationRunManifestV2`` (v0.1 rejected), derives applicability
solely from the hash-bound stage-profile registry, and binds every identity and
the governed semantic-content evidence hash to the manifest. No default stage
and no applicability boolean exist.

Importing this module performs no filesystem access, hashing, environment
inspection, clock read, UUID generation, network, provider, or model call.
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
    AssertionKind,
    ContractStampedModel,
    EvaluationRunManifest,
    EvaluationRunManifestV2,
    EvaluationStrictModel,
    PartitionName,
    SuiteName,
    _reject_explicit_null,
    _require_non_blank,
)
from .stage_evidence import (
    GoldVerificationStatus,
    LoadedStageMetricEvidenceSet,
    StageMetricEvidenceKind,
    StageMetricEvidenceSet,
    stage_metric_evidence_set_hash,
)
from .stage_profiles import (
    LoadedStageProfileRegistry,
    MetricFamily,
    StageProfileError,
    resolve_metric_applicability,
    stage_profile_registry_hash,
)
from .validators import ValidatorRuleId
from ..universe.io_utils import sha256_bytes

__all__ = [
    "LoadedMetricInputSnapshot",
    "MetricApplicabilityBinding",
    "MetricInputSnapshotError",
    "PersistedMetricInputSnapshot",
    "build_metric_input_snapshot",
    "load_metric_input_snapshot",
    "persist_metric_input_snapshot",
]

_CONTRACT_ID = "metric_input_snapshot"
_CONTRACT_VERSION = "0.1.0"
_INPUTS_DIR = "metric_inputs"
_INPUTS_FILENAME = "metric_input_snapshot.json"
_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"

# --- Governed vocabularies and reserved values (re-homed from metrics.py) --

EvidenceResolvability = Literal["resolvable", "insufficient_evidence"]
AxisRole = Literal["product", "capability", "task", "other"]
AxisBaseMetricType = Literal[
    "multi_label", "nominal_single_label", "ordinal_single_label", "structured_set"
]
AxisMetricType = Literal[
    "multi_label",
    "nominal_single_label",
    "ordinal_single_label",
    "structured_set",
    "abstention_allowed",
]
MetricScope = Literal["conditional", "end_to_end"]

UNKNOWN = "UNKNOWN"
OTHER = "OTHER"
NOT_APPLICABLE = "NOT_APPLICABLE"
NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION = "NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION"

_RESERVED_VALUES = frozenset(
    {UNKNOWN, OTHER, NOT_APPLICABLE, NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION}
)


def _require_unique(values: tuple[str, ...], field_name: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicate values")


# --- Public error ----------------------------------------------------------


class MetricInputSnapshotError(Exception):
    """Sanitized metric-input-snapshot failure with a stable machine code.

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


# --- Re-homed public metric-input member models ---------------------------
# Verbatim from metrics.py; public model semantics unchanged (strict base config
# — extra-forbid + frozen — is identical to the previous ``_Slice9StrictModel``).


class AxisDefinition(EvaluationStrictModel):
    """One classification axis and the metric family it is scored with."""

    axis_id: str
    axis_role: AxisRole
    metric_type: AxisMetricType
    base_metric_type: AxisBaseMetricType | None = None
    labels: tuple[str, ...]
    ordinal_order: tuple[str, ...] = ()
    ordinal_weighting: Literal["linear", "quadratic"] | None = None

    @model_validator(mode="after")
    def _axis_invariants(self) -> "AxisDefinition":
        _require_non_blank(self.axis_id, "axis_id")
        if not self.labels:
            raise ValueError("axis must declare at least one label")
        for label in self.labels:
            _require_non_blank(label, "label")
        _require_unique(self.labels, "labels")
        for reserved in (UNKNOWN, NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION):
            if reserved in self.labels:
                raise ValueError(f"label {reserved!r} is reserved and may not appear in labels")
        effective = self.metric_type
        if self.metric_type == "abstention_allowed":
            if self.base_metric_type is None:
                raise ValueError("abstention_allowed axis requires a base_metric_type")
            effective = self.base_metric_type
        elif self.base_metric_type is not None:
            raise ValueError("non-abstention metric types require base_metric_type to be None")
        if effective == "ordinal_single_label":
            if not self.ordinal_order:
                raise ValueError("ordinal axis requires a non-empty ordinal_order")
            for value in self.ordinal_order:
                _require_non_blank(value, "ordinal_order value")
            _require_unique(self.ordinal_order, "ordinal_order")
            if set(self.ordinal_order) != set(self.labels):
                raise ValueError("ordinal_order must have exact identity with the label set")
            if self.ordinal_weighting is None:
                raise ValueError("ordinal axis requires linear or quadratic ordinal_weighting")
        else:
            if self.ordinal_order:
                raise ValueError("non-ordinal axis must not declare ordinal_order")
            if self.ordinal_weighting is not None:
                raise ValueError("non-ordinal axis must not declare ordinal_weighting")
        return self

    @property
    def effective_metric_type(self) -> str:
        if self.metric_type == "abstention_allowed":
            assert self.base_metric_type is not None
            return self.base_metric_type
        return self.metric_type

    @property
    def abstention_allowed(self) -> bool:
        return self.metric_type == "abstention_allowed"


class AxisEvaluationRecord(EvaluationStrictModel):
    """One predicted vs gold observation for one axis."""

    record_id: str
    case_id: str
    axis_id: str
    metric_scope: MetricScope
    verification_status: GoldVerificationStatus
    evidence_resolvability: EvidenceResolvability
    predicted_values: tuple[str, ...]
    gold_values: tuple[str, ...]

    @model_validator(mode="after")
    def _record_invariants(self) -> "AxisEvaluationRecord":
        _require_non_blank(self.record_id, "record_id")
        _require_non_blank(self.case_id, "case_id")
        _require_non_blank(self.axis_id, "axis_id")
        for value in self.predicted_values:
            _require_non_blank(value, "predicted value")
        for value in self.gold_values:
            _require_non_blank(value, "gold value")
        _require_unique(self.predicted_values, "predicted_values")
        _require_unique(self.gold_values, "gold_values")
        for forbidden in (UNKNOWN, NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION):
            if forbidden in self.gold_values:
                raise ValueError(f"gold_values must never contain {forbidden!r}")
        if self.evidence_resolvability == "resolvable" and not self.gold_values:
            raise ValueError("a resolvable record requires at least one gold value")
        return self

    @property
    def is_unknown(self) -> bool:
        return self.predicted_values == (UNKNOWN,)

    @property
    def is_screen_excluded(self) -> bool:
        return self.predicted_values == (NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION,)


class AssertionMetricBinding(EvaluationStrictModel):
    """Binds one assertion outcome identity to its case grouping context."""

    case_id: str
    assertion_id: str
    assertion_kind: AssertionKind
    partition: PartitionName
    suites: tuple[SuiteName, ...]

    @model_validator(mode="after")
    def _binding_invariants(self) -> "AssertionMetricBinding":
        _require_non_blank(self.case_id, "case_id")
        _require_non_blank(self.assertion_id, "assertion_id")
        _require_unique(self.suites, "suites")
        return self


class ValidatorRuleEvaluationRecord(EvaluationStrictModel):
    """Per-artifact, per-rule evaluated/failed observation counts."""

    artifact_id: str
    rule_id: ValidatorRuleId
    evaluated_observation_count: int
    failed_observation_count: int

    @model_validator(mode="after")
    def _execution_invariants(self) -> "ValidatorRuleEvaluationRecord":
        _require_non_blank(self.artifact_id, "artifact_id")
        if self.evaluated_observation_count < 0 or self.failed_observation_count < 0:
            raise ValueError("observation counts must be non-negative")
        if self.failed_observation_count > self.evaluated_observation_count:
            raise ValueError("failed observations cannot exceed evaluated observations")
        return self


def _validate_record_against_axis(record: AxisEvaluationRecord, axis: AxisDefinition) -> None:
    label_set = set(axis.labels)
    if OTHER in axis.labels:
        label_set.add(OTHER)
    if NOT_APPLICABLE in axis.labels:
        label_set.add(NOT_APPLICABLE)
    # Screen-exclusion sentinel handling.
    if record.metric_scope == "conditional" and record.is_screen_excluded:
        raise ValueError("conditional records reject the screen-exclusion sentinel")
    if NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION in record.predicted_values:
        if not record.is_screen_excluded:
            raise ValueError(
                "the screen-exclusion sentinel may only appear as the sole prediction"
            )
    # UNKNOWN handling.
    if UNKNOWN in record.predicted_values:
        if not record.is_unknown:
            raise ValueError("UNKNOWN may only appear as the sole prediction")
        if not axis.abstention_allowed:
            raise ValueError(f"axis {axis.axis_id!r} does not permit UNKNOWN predictions")
    effective = axis.effective_metric_type
    special = {UNKNOWN, NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION}
    is_single = effective in ("nominal_single_label", "ordinal_single_label")
    if is_single and not (record.is_unknown or record.is_screen_excluded):
        if len(record.predicted_values) != 1:
            raise ValueError("single-label axis requires exactly one predicted value")
    for value in record.predicted_values:
        if value in special:
            continue
        if value not in label_set:
            raise ValueError(f"predicted value {value!r} is outside the axis vocabulary")
    for value in record.gold_values:
        if value not in label_set:
            raise ValueError(f"gold value {value!r} is outside the axis vocabulary")


# --- Metric applicability binding -----------------------------------------


class MetricApplicabilityBinding(EvaluationStrictModel):
    """The authoritative stage + resolved-applicability + evidence carrier.

    For Universe stages all three evidence fields (version, hash, embedded set)
    are present together; for extraction stages all three are omitted together.
    Explicit null on any evidence field is rejected.
    """

    evaluation_stage: str
    stage_profile_registry_version: str
    stage_profile_registry_hash: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    selected_stage_profile_entry_hash: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    applicable_metric_families: tuple[MetricFamily, ...]
    required_stage_evidence_kinds: tuple[StageMetricEvidenceKind, ...]
    stage_metric_evidence_set_version: str | None = None
    stage_metric_evidence_set_hash: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    stage_metric_evidence_set: StageMetricEvidenceSet | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_explicit_null_evidence(cls, data: Any) -> Any:
        return _reject_explicit_null(
            data,
            (
                "stage_metric_evidence_set_version",
                "stage_metric_evidence_set_hash",
                "stage_metric_evidence_set",
            ),
            "MetricApplicabilityBinding",
        )

    @model_validator(mode="after")
    def _binding_invariants(self) -> "MetricApplicabilityBinding":
        _require_non_blank(self.evaluation_stage, "evaluation_stage")
        _require_non_blank(self.stage_profile_registry_version, "stage_profile_registry_version")
        families = list(self.applicable_metric_families)
        if families != sorted(families):
            raise ValueError("applicable_metric_families must be sorted")
        _require_unique(self.applicable_metric_families, "applicable_metric_families")
        if not families:
            raise ValueError("applicable_metric_families must be non-empty")
        kinds = list(self.required_stage_evidence_kinds)
        if kinds != sorted(kinds):
            raise ValueError("required_stage_evidence_kinds must be sorted")
        _require_unique(self.required_stage_evidence_kinds, "required_stage_evidence_kinds")
        requires = bool(kinds)
        present = (
            "stage_metric_evidence_set_version" in self.model_fields_set
            or "stage_metric_evidence_set_hash" in self.model_fields_set
            or "stage_metric_evidence_set" in self.model_fields_set
        )
        if requires:
            if (
                self.stage_metric_evidence_set_version is None
                or self.stage_metric_evidence_set_hash is None
                or self.stage_metric_evidence_set is None
            ):
                raise ValueError(
                    "a Universe stage requires the evidence version, hash, and embedded set together"
                )
            _require_non_blank(
                self.stage_metric_evidence_set_version, "stage_metric_evidence_set_version"
            )
            embedded = self.stage_metric_evidence_set
            if embedded.evaluation_stage != self.evaluation_stage:
                raise ValueError("embedded evidence stage must equal the binding stage")
            if embedded.set_version != self.stage_metric_evidence_set_version:
                raise ValueError("embedded evidence set_version must equal the binding version")
            if stage_metric_evidence_set_hash(embedded) != self.stage_metric_evidence_set_hash:
                raise ValueError(
                    "embedded evidence semantic-content hash must equal the binding hash"
                )
            if embedded.present_kinds != tuple(kinds):
                raise ValueError(
                    "embedded evidence variant kinds must equal required_stage_evidence_kinds"
                )
        else:
            if present:
                raise ValueError(
                    "an extraction stage must omit all stage-evidence fields together"
                )
        return self


# --- Stamped metric-input snapshot ----------------------------------------


class MetricInputSnapshot(ContractStampedModel):
    # Docstring intentionally omitted so the generated JSON Schema (and thus the
    # governed model-contract hash) carries no description.
    _contract_id: ClassVar[str] = _CONTRACT_ID
    _contract_version: ClassVar[str] = _CONTRACT_VERSION

    eval_run_id: str
    case_set_version: str
    case_set_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    scoring_gate_config_version: str
    scoring_gate_config_hash: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    applicability_binding: MetricApplicabilityBinding
    axis_definitions: tuple[AxisDefinition, ...]
    axis_records: tuple[AxisEvaluationRecord, ...]
    assertion_bindings: tuple[AssertionMetricBinding, ...]
    validator_rule_evaluations: tuple[ValidatorRuleEvaluationRecord, ...]

    @model_validator(mode="after")
    def _snapshot_invariants(self) -> "MetricInputSnapshot":
        _require_non_blank(self.eval_run_id, "eval_run_id")
        _require_non_blank(self.case_set_version, "case_set_version")
        _require_non_blank(self.scoring_gate_config_version, "scoring_gate_config_version")
        axis_ids = tuple(a.axis_id for a in self.axis_definitions)
        _require_unique(axis_ids, "axis_id")
        known_axes = set(axis_ids)
        rec_ids = tuple(r.record_id for r in self.axis_records)
        _require_unique(rec_ids, "axis record_id")
        by_axis = {a.axis_id: a for a in self.axis_definitions}
        for record in self.axis_records:
            if record.axis_id not in known_axes:
                raise ValueError(f"axis record binds unknown axis {record.axis_id!r}")
            _validate_record_against_axis(record, by_axis[record.axis_id])
        binding_ids = tuple((b.case_id, b.assertion_id) for b in self.assertion_bindings)
        if len(set(binding_ids)) != len(binding_ids):
            raise ValueError("assertion bindings must have unique (case_id, assertion_id)")
        exec_ids = tuple((e.artifact_id, e.rule_id) for e in self.validator_rule_evaluations)
        if len(set(exec_ids)) != len(exec_ids):
            raise ValueError("validator executions must have unique (artifact_id, rule_id)")
        return self


class LoadedMetricInputSnapshot(EvaluationStrictModel):
    """A validated metric-input snapshot plus its raw-byte binding material."""

    model: MetricInputSnapshot
    version: str
    sha256: str
    artifact_reference: str


class PersistedMetricInputSnapshot(EvaluationStrictModel):
    """A persisted metric-input snapshot plus its raw-byte binding material."""

    model: MetricInputSnapshot
    version: str
    sha256: str
    artifact_reference: str


# --- Content hash + fail-closed revalidation ------------------------------


def _revalidate(model: MetricInputSnapshot) -> MetricInputSnapshot:
    if not isinstance(model, MetricInputSnapshot):
        raise TypeError(f"expected a MetricInputSnapshot, got {type(model).__name__}")
    try:
        payload = model.model_dump(mode="json", exclude_unset=True)
    except Exception as exc:  # noqa: BLE001 - any serialization defect fails closed
        raise MetricInputSnapshotError(
            "metric-input snapshot could not be serialized for revalidation",
            reason_code="model_validation",
        ) from exc
    try:
        return MetricInputSnapshot.model_validate(payload)
    except PydanticValidationError as exc:
        raise MetricInputSnapshotError(
            "metric-input snapshot failed fail-closed revalidation",
            reason_code="model_validation",
        ) from exc


def metric_input_snapshot_hash(snapshot: MetricInputSnapshot) -> str:
    """Deterministic canonical semantic-content SHA-256 over the snapshot."""
    validated = _revalidate(snapshot)
    return sha256_bytes(canonical_contract_bytes(validated.model_dump(mode="json", exclude_unset=True)))


# --- Sole sanctioned active producer --------------------------------------


def _revalidate_stage_evidence(loaded: LoadedStageMetricEvidenceSet) -> StageMetricEvidenceSet:
    """Fail-closed revalidation of a supplied evidence wrapper's embedded model.

    A ``model_construct``/``model_copy``-bypassed wrapper can carry an arbitrary
    object in ``model``; every serialization, validation, or structural defect is
    converted into a sanitized ``MetricInputSnapshotError`` under a single stable
    reason code before any evidence-model field is read. No raw object, Pydantic,
    filesystem, or validation text is exposed.
    """
    model = getattr(loaded, "model", None)
    if not isinstance(model, StageMetricEvidenceSet):
        raise MetricInputSnapshotError(
            "stage evidence wrapper does not carry a stage metric evidence set",
            reason_code="evidence_model_invalid",
        )
    try:
        payload = model.model_dump(mode="json", exclude_unset=True)
    except Exception as exc:  # noqa: BLE001 - any serialization defect fails closed
        raise MetricInputSnapshotError(
            "stage evidence could not be serialized for revalidation",
            reason_code="evidence_model_invalid",
        ) from exc
    try:
        return StageMetricEvidenceSet.model_validate(payload)
    except PydanticValidationError as exc:
        raise MetricInputSnapshotError(
            "stage evidence failed fail-closed revalidation",
            reason_code="evidence_model_invalid",
        ) from exc


def build_metric_input_snapshot(
    *,
    evaluation_stage: str,
    stage_profile_registry: LoadedStageProfileRegistry,
    run_manifest: EvaluationRunManifestV2,
    axis_definitions: tuple[AxisDefinition, ...] = (),
    axis_records: tuple[AxisEvaluationRecord, ...] = (),
    assertion_bindings: tuple[AssertionMetricBinding, ...] = (),
    validator_rule_evaluations: tuple[ValidatorRuleEvaluationRecord, ...] = (),
    stage_evidence: LoadedStageMetricEvidenceSet | None = None,
) -> MetricInputSnapshot:
    """Build the stamped ``metric_input_snapshot@0.1.0`` (only active producer)."""
    if isinstance(run_manifest, EvaluationRunManifest) and not isinstance(
        run_manifest, EvaluationRunManifestV2
    ):
        raise MetricInputSnapshotError(
            "the active metric path requires an evaluation_run_manifest v0.2",
            reason_code="run_manifest_version",
        )
    if not isinstance(run_manifest, EvaluationRunManifestV2):
        raise TypeError(
            f"run_manifest must be an EvaluationRunManifestV2, got {type(run_manifest).__name__}"
        )
    if not isinstance(stage_profile_registry, LoadedStageProfileRegistry):
        raise TypeError(
            f"stage_profile_registry must be a LoadedStageProfileRegistry, got "
            f"{type(stage_profile_registry).__name__}"
        )
    if stage_evidence is not None and not isinstance(stage_evidence, LoadedStageMetricEvidenceSet):
        raise TypeError(
            f"stage_evidence must be a LoadedStageMetricEvidenceSet, got "
            f"{type(stage_evidence).__name__}"
        )

    # Resolve the selected stage-profile entry through the governed Slice 12A
    # boundary (fail-closed revalidation inside). Unknown/unsupported/duplicate
    # or structurally inconsistent registries never resolve.
    try:
        entry = resolve_metric_applicability(stage_profile_registry.registry, evaluation_stage)
    except StageProfileError as exc:
        raise MetricInputSnapshotError(
            "the evaluation stage does not resolve to a supported stage-profile entry",
            reason_code="stage_resolution",
        ) from exc

    # Bind registry identity and selected-entry hash to the manifest.
    if stage_profile_registry.version != run_manifest.stage_profile_registry_version:
        raise MetricInputSnapshotError(
            "stage-profile registry version does not match the run manifest",
            reason_code="stage_profile_registry_version_mismatch",
        )
    if stage_profile_registry_hash(stage_profile_registry.registry) != (
        run_manifest.stage_profile_registry_hash
    ):
        raise MetricInputSnapshotError(
            "stage-profile registry content hash does not match the run manifest",
            reason_code="stage_profile_registry_hash_mismatch",
        )
    if entry.entry_hash != run_manifest.selected_stage_profile_entry_hash:
        raise MetricInputSnapshotError(
            "selected stage-profile entry hash does not match the run manifest",
            reason_code="selected_entry_hash_mismatch",
        )

    requires = bool(entry.required_stage_evidence_kinds)
    if requires and stage_evidence is None:
        raise MetricInputSnapshotError(
            "a Universe stage requires a stage metric evidence set",
            reason_code="evidence_required",
        )
    if not requires and stage_evidence is not None:
        raise MetricInputSnapshotError(
            "an extraction stage must not carry a stage metric evidence set",
            reason_code="evidence_forbidden",
        )

    binding_fields: dict[str, Any] = {
        "evaluation_stage": evaluation_stage,
        "stage_profile_registry_version": stage_profile_registry.version,
        "stage_profile_registry_hash": run_manifest.stage_profile_registry_hash,
        "selected_stage_profile_entry_hash": entry.entry_hash,
        "applicable_metric_families": tuple(entry.applicable_metric_families),
        "required_stage_evidence_kinds": tuple(entry.required_stage_evidence_kinds),
    }

    if requires:
        # Fail-closed revalidation before reading any evidence-model field.
        evidence_model = _revalidate_stage_evidence(stage_evidence)
        if evidence_model.evaluation_stage != evaluation_stage:
            raise MetricInputSnapshotError(
                "stage evidence stage does not match the resolved stage",
                reason_code="evidence_stage_mismatch",
            )
        if evidence_model.present_kinds != tuple(entry.required_stage_evidence_kinds):
            raise MetricInputSnapshotError(
                "stage evidence variant kinds do not match the required kinds",
                reason_code="evidence_kinds_mismatch",
            )
        if evidence_model.set_version != run_manifest.stage_metric_evidence_set_version:
            raise MetricInputSnapshotError(
                "stage evidence set version does not match the run manifest",
                reason_code="evidence_version_mismatch",
            )
        # Governed semantic-content hash, never the raw persisted-byte sha256.
        content_hash = stage_metric_evidence_set_hash(evidence_model)
        if content_hash != run_manifest.stage_metric_evidence_set_hash:
            raise MetricInputSnapshotError(
                "stage evidence semantic-content hash does not match the run manifest",
                reason_code="evidence_hash_mismatch",
            )
        binding_fields["stage_metric_evidence_set_version"] = evidence_model.set_version
        binding_fields["stage_metric_evidence_set_hash"] = content_hash
        binding_fields["stage_metric_evidence_set"] = evidence_model

    stamp_hash = model_contract_hash(MetricInputSnapshot, _CONTRACT_ID, _CONTRACT_VERSION)
    try:
        return MetricInputSnapshot(
            contract={
                "contract_id": _CONTRACT_ID,
                "contract_version": _CONTRACT_VERSION,
                "contract_hash": stamp_hash,
            },
            eval_run_id=run_manifest.eval_run_id,
            case_set_version=run_manifest.case_set_version,
            case_set_hash=run_manifest.case_set_hash,
            scoring_gate_config_version=run_manifest.scoring_gate_config_version,
            scoring_gate_config_hash=run_manifest.scoring_gate_config_hash,
            applicability_binding=MetricApplicabilityBinding.model_validate(binding_fields),
            axis_definitions=tuple(axis_definitions),
            axis_records=tuple(axis_records),
            assertion_bindings=tuple(assertion_bindings),
            validator_rule_evaluations=tuple(validator_rule_evaluations),
        )
    except PydanticValidationError as exc:
        raise MetricInputSnapshotError(
            "metric-input snapshot failed strict contract validation",
            reason_code="model_validation",
        ) from exc


# --- Safe references / roots / strict parse -------------------------------


def _is_safe_reference(value: Any) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if "\\" in value or "\x00" in value:
        return False
    if Path(value).is_absolute():
        return False
    return all(part not in ("", ".", "..") for part in value.split("/"))


def _validate_eval_root(eval_root: str | Path) -> Path:
    if not isinstance(eval_root, (str, Path)):
        raise MetricInputSnapshotError(
            "eval_root must be an explicit str or Path evaluation root",
            reason_code="invalid_eval_root",
        )
    if isinstance(eval_root, str) and eval_root == "":
        raise MetricInputSnapshotError(
            "eval_root must not be an empty string; supply the evaluation root explicitly",
            reason_code="invalid_eval_root",
        )
    root = Path(eval_root)
    if root.is_symlink():
        raise MetricInputSnapshotError(
            "eval_root must not be a symlink", reason_code="eval_root_symlink"
        )
    if not root.exists():
        raise MetricInputSnapshotError(
            "evaluation root does not exist", reason_code="invalid_eval_root"
        )
    if not root.is_dir():
        raise MetricInputSnapshotError(
            "evaluation root is not a directory", reason_code="invalid_eval_root"
        )
    return root.resolve()


def _resolve_contained(reference: str | Path, resolved_root: Path) -> tuple[Path, str]:
    if not _is_safe_reference(reference if isinstance(reference, str) else str(reference)):
        if not isinstance(reference, (str, Path)):
            raise MetricInputSnapshotError(
                "reference must be an explicit str or Path", reason_code="invalid_path"
            )
        raise MetricInputSnapshotError(
            "reference is not a safe relative reference", reason_code="unsafe_reference"
        )
    candidate = resolved_root / Path(reference)
    if candidate.is_symlink():
        raise MetricInputSnapshotError(
            "artifact path is a symlink", reason_code="artifact_symlink"
        )
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise MetricInputSnapshotError(
            "artifact path resolves outside the evaluation root", reason_code="path_escape"
        )
    ref = resolved.relative_to(resolved_root).as_posix()
    if resolved.is_symlink():
        raise MetricInputSnapshotError(
            "artifact is a symlink", reason_code="artifact_symlink", artifact_reference=ref
        )
    if not resolved.exists():
        raise MetricInputSnapshotError(
            "artifact does not exist under the evaluation root",
            reason_code="artifact_missing",
            artifact_reference=ref,
        )
    if not resolved.is_file():
        raise MetricInputSnapshotError(
            "artifact is not a regular file",
            reason_code="artifact_not_a_file",
            artifact_reference=ref,
        )
    return resolved, ref


def _validate_run_id(eval_run_id: Any) -> str:
    if not isinstance(eval_run_id, str):
        raise MetricInputSnapshotError(
            f"eval_run_id must be a string, got {type(eval_run_id).__name__}",
            reason_code="invalid_eval_run_id",
        )
    if not eval_run_id or eval_run_id != eval_run_id.strip():
        raise MetricInputSnapshotError(
            "eval_run_id must be a non-empty string without leading or trailing whitespace",
            reason_code="invalid_eval_run_id",
        )
    if eval_run_id in (".", ".."):
        raise MetricInputSnapshotError(
            "eval_run_id is not a valid path component", reason_code="invalid_eval_run_id"
        )
    if "/" in eval_run_id or "\\" in eval_run_id or "\x00" in eval_run_id:
        raise MetricInputSnapshotError(
            "eval_run_id must be a single path component without separators or NUL",
            reason_code="invalid_eval_run_id",
        )
    if Path(eval_run_id).is_absolute() or len(Path(eval_run_id).parts) != 1:
        raise MetricInputSnapshotError(
            "eval_run_id must be exactly one relative path component",
            reason_code="invalid_eval_run_id",
        )
    return eval_run_id


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise _DuplicateKeyControl()
        seen.add(key)
        result[key] = value
    return result


def _reject_non_finite_constant(name: str) -> Any:
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


def _strict_json_object(text: str, reference: str) -> dict[str, Any]:
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except json.JSONDecodeError as exc:
        raise MetricInputSnapshotError(
            "artifact is not valid JSON", reason_code="json_error", artifact_reference=reference
        ) from exc
    except _DuplicateKeyControl as exc:
        raise MetricInputSnapshotError(
            "artifact contains a duplicate JSON object key",
            reason_code="duplicate_key",
            artifact_reference=reference,
        ) from exc
    except _NonFiniteControl as exc:
        raise MetricInputSnapshotError(
            "artifact contains a non-JSON numeric constant",
            reason_code="non_finite",
            artifact_reference=reference,
        ) from exc
    if _has_non_finite(payload):
        raise MetricInputSnapshotError(
            "artifact contains a non-finite JSON number",
            reason_code="non_finite",
            artifact_reference=reference,
        )
    if not isinstance(payload, dict):
        raise MetricInputSnapshotError(
            "artifact top-level value must be a JSON object",
            reason_code="top_level_type",
            artifact_reference=reference,
        )
    return payload


def _read_contained(reference: str, resolved_root: Path) -> tuple[bytes, str, str]:
    resolved, ref = _resolve_contained(reference, resolved_root)
    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        raise MetricInputSnapshotError(
            "failed to read the artifact", reason_code="read_error", artifact_reference=ref
        ) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MetricInputSnapshotError(
            "artifact is not valid UTF-8", reason_code="decode_error", artifact_reference=ref
        ) from exc
    return raw, text, ref


# --- Loader ---------------------------------------------------------------


def load_metric_input_snapshot(
    path: str | Path,
    *,
    eval_root: str | Path,
    expected_sha256: str | None = None,
) -> LoadedMetricInputSnapshot:
    """Load, hash-bind, and strictly validate a metric-input snapshot."""
    resolved_root = _validate_eval_root(eval_root)
    raw, text, reference = _read_contained(str(path), resolved_root)
    observed = sha256_bytes(raw)
    if expected_sha256 is not None:
        valid = (
            isinstance(expected_sha256, str)
            and len(expected_sha256) == 64
            and all(c in "0123456789abcdef" for c in expected_sha256)
        )
        if not valid or expected_sha256 != observed:
            raise MetricInputSnapshotError(
                "metric-input snapshot raw-byte hash does not match the expected hash",
                reason_code="expected_hash_mismatch",
                artifact_reference=reference,
            )
    payload = _strict_json_object(text, reference)
    try:
        model = MetricInputSnapshot.model_validate(payload)
    except PydanticValidationError as exc:
        raise MetricInputSnapshotError(
            "metric-input snapshot failed strict contract validation",
            reason_code="model_validation",
            artifact_reference=reference,
        ) from exc
    return LoadedMetricInputSnapshot(
        model=model,
        version=model.contract.contract_version,
        sha256=observed,
        artifact_reference=reference,
    )


# --- Persistence ----------------------------------------------------------


def persist_metric_input_snapshot(
    snapshot: MetricInputSnapshot,
    *,
    eval_root: str | Path,
    eval_run_id: str,
) -> PersistedMetricInputSnapshot:
    """Write the canonical snapshot JSON (plus one terminal newline) write-once.

    Destination:
    ``<eval_root>/<eval_run_id>/metric_inputs/metric_input_snapshot.json``.
    """
    validated = _revalidate(snapshot)
    run_id = _validate_run_id(eval_run_id)
    if validated.eval_run_id != run_id:
        raise MetricInputSnapshotError(
            "the snapshot's eval_run_id does not equal the explicit persistence eval_run_id",
            reason_code="persist_eval_run_id_mismatch",
        )
    resolved_root = _validate_eval_root(eval_root)
    run_dir = resolved_root / run_id
    if run_dir.is_symlink():
        raise MetricInputSnapshotError(
            "run directory is a symlink", reason_code="run_directory_symlink"
        )
    if not run_dir.exists():
        raise MetricInputSnapshotError(
            "run directory does not exist under the evaluation root",
            reason_code="run_directory_missing",
            artifact_reference=run_id,
        )
    if not run_dir.is_dir():
        raise MetricInputSnapshotError(
            "run directory is not a directory",
            reason_code="run_directory_not_a_directory",
            artifact_reference=run_id,
        )
    inputs_dir = run_dir / _INPUTS_DIR
    if inputs_dir.is_symlink():
        raise MetricInputSnapshotError(
            "run metric-inputs directory is a symlink",
            reason_code="inputs_directory_symlink",
        )
    if inputs_dir.exists():
        if not inputs_dir.is_dir():
            raise MetricInputSnapshotError(
                "run metric-inputs path is not a directory",
                reason_code="inputs_directory_not_a_directory",
            )
    else:
        try:
            inputs_dir.mkdir(exist_ok=False)
        except OSError as exc:
            raise MetricInputSnapshotError(
                "failed to create the run metric-inputs directory",
                reason_code="write_error",
                artifact_reference=f"{run_id}/{_INPUTS_DIR}",
            ) from exc
    reference = f"{run_id}/{_INPUTS_DIR}/{_INPUTS_FILENAME}"
    dest = inputs_dir / _INPUTS_FILENAME
    if dest.is_symlink() or dest.exists():
        raise MetricInputSnapshotError(
            "metric-input snapshot already exists; artifacts are write-once",
            reason_code="artifact_exists",
            artifact_reference=reference,
        )
    data = canonical_contract_bytes(validated.model_dump(mode="json", exclude_unset=True)) + b"\n"
    expected = sha256_bytes(data)
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise MetricInputSnapshotError(
            "metric-input snapshot already exists; artifacts are write-once",
            reason_code="artifact_exists",
            artifact_reference=reference,
        ) from exc
    except OSError as exc:
        raise MetricInputSnapshotError(
            "failed to create the metric-input snapshot",
            reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise MetricInputSnapshotError(
            "failed to write the metric-input snapshot",
            reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        observed = sha256_bytes(dest.read_bytes())
    except OSError as exc:
        raise MetricInputSnapshotError(
            "failed to re-read the metric-input snapshot for verification",
            reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    if observed != expected:
        raise MetricInputSnapshotError(
            "persisted metric-input snapshot re-read to a different hash",
            reason_code="destination_hash_mismatch",
            artifact_reference=reference,
        )
    return PersistedMetricInputSnapshot(
        model=validated,
        version=validated.contract.contract_version,
        sha256=observed,
        artifact_reference=reference,
    )
