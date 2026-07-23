"""Typed data models for the Phase 1 evaluation harness (Slices 1A and 1B).

Slice 1A provides the strict/frozen base and the contract-metadata model.
Slice 1B adds the approved persisted-artifact data contracts. Data contracts
only: no loaders, writers, runners, validators, metrics, gates, comparison
behavior, or persistence behavior live here.

Presence/null semantics follow the static schemas: optional-but-non-null
properties reject explicit JSON null while remaining omittable, and absence
is tracked through ``model_fields_set``. Sequence fields use tuples
internally and serialize to JSON arrays. ``frozen=True`` gives top-level
attribute immutability only; dictionary-valued JSON content remains mutable
in Python, and artifact immutability is enforced by write-once persistence
plus fresh validation in the owning behavior slices.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from .contracts import model_contract_hash

# Non-empty, no leading or trailing whitespace; internal spaces stay legal.
# Values are validated as-is and never stripped, lowercased, or rewritten.
_IDENTITY_PATTERN = r"^\S(.*\S)?$"
# Canonical lowercase SHA-256 hex digest; uppercase is rejected, not folded.
_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"

PartitionName = Literal["dev", "frozen_test"]
SuiteName = Literal["adversarial", "regression", "smoke", "boundary", "schema_validation"]
AssertionKind = Literal[
    "expected_entity",
    "forbidden_entity",
    "field_value",
    "evidence_provenance",
    "deterministic_validation",
]
ExecutionStatus = Literal["completed", "invalid", "errored"]
GateVerdict = Literal["pass", "fail", "indeterminate"]
AssertionOutcomeValue = Literal[
    "satisfied", "unsatisfied", "indeterminate", "not_applicable", "not_evaluated"
]
FindingSeverity = Literal["critical", "error", "warning", "info"]
DispositionType = Literal[
    "confirmed_defect",
    "suspected_validator_false_positive",
    "confirmed_validator_false_positive",
    "source_snapshot_defect",
    "prediction_artifact_defect",
    "gold_or_case_defect",
    "policy_or_rule_mismatch",
    "accepted_nonblocking_risk",
    "duplicate_finding",
    "needs_investigation",
]


def _reject_explicit_null(data: Any, keys: tuple[str, ...], model_name: str) -> Any:
    """Reject optional-but-non-null properties supplied as explicit null.

    Absence stays legal and is never conflated with null; the null is
    rejected rather than silently rewritten into absence.
    """
    if isinstance(data, dict):
        for key in keys:
            if key in data and data[key] is None:
                raise ValueError(
                    f"{model_name}.{key} must not be explicit JSON null; "
                    "omit the property instead"
                )
    return data


def _require_identity_presence(model: BaseModel, keys: tuple[str, ...]) -> None:
    """At least one identity key must be present, valid, and unstripped."""
    supplied = [key for key in keys if key in model.model_fields_set]
    if not supplied:
        raise ValueError(f"at least one of {keys} must be present")
    for key in supplied:
        value = getattr(model, key)
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError(
                f"{key} must be a non-empty string without leading or "
                "trailing whitespace"
            )


def _require_non_blank(value: str, field_name: str) -> None:
    """Reject empty, whitespace-only, and edge-whitespace values as-is.

    The value is compared, never stripped, normalized, or rewritten;
    internal spaces remain legal.
    """
    if not value or value != value.strip():
        raise ValueError(
            f"{field_name} must be a non-empty string without leading or "
            "trailing whitespace"
        )


# Strict RFC3339 date-time in extended format: full-date, `T`/`t`, HH:MM:SS with
# required seconds, optional fractional seconds, and a `Z`/`z` or exact ±HH:MM
# offset (no offset seconds). This lexical gate rejects the basic ISO format,
# ISO week/ordinal dates, reduced-precision times, and offsets carrying seconds
# or fractions — none of which ``datetime.fromisoformat`` rejects on its own.
_RFC3339_LEXICAL = re.compile(
    r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})"
)


def _require_rfc3339_offset(value: str, field_name: str) -> str:
    """Strict RFC3339 date-time with seconds and an explicit offset.

    Slice 12B-local mirror of the protected ``validators._require_rfc3339``
    intent (that private helper is neither imported nor modified). A private
    lexical check fixes the accepted shape; ``datetime.fromisoformat`` then does
    value-range validation (calendar/time). The caller's exact accepted
    representation is returned verbatim: a trailing ``Z``/``z`` is expanded only
    to *parse* the offset and is never normalized to ``+00:00``, no offset is
    rewritten, no clock is read, and nothing is inferred from any other source.
    """
    _require_non_blank(value, field_name)
    if _RFC3339_LEXICAL.fullmatch(value) is None:
        raise ValueError(
            f"{field_name} must be an RFC3339 extended date-time with seconds and "
            "an explicit Z or ±HH:MM offset"
        )
    candidate = value
    if candidate.endswith(("z", "Z")):
        candidate = f"{candidate[:-1]}+00:00"
    try:
        datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid RFC3339 timestamp") from exc
    return value


class EvaluationStrictModel(BaseModel):
    """Strict, immutable base for all evaluation-harness models.

    Unknown fields are rejected and instances are frozen, mirroring the
    `universe.models.StrictModel` pattern with the immutability required by
    the evaluation-harness build plan.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class ContractMetadata(EvaluationStrictModel):
    """Identity and hash of one versioned artifact contract."""

    contract_id: str = Field(min_length=1, pattern=_IDENTITY_PATTERN)
    contract_version: str = Field(min_length=1, pattern=_IDENTITY_PATTERN)
    contract_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)


class ContractStampedModel(EvaluationStrictModel):
    """Internal shared base for generated-schema persisted artifacts.

    Each subclass declares its approved ``_contract_id`` and carries one
    nested ``contract`` field. Validation fails closed unless the supplied
    contract metadata matches the subclass's approved contract ID, the
    approved contract version, and the canonical generated-model contract
    hash. Hashes are computed at validation time, never at import time.
    """

    _contract_id: ClassVar[str]
    _contract_version: ClassVar[str] = "0.1.0"

    contract: ContractMetadata

    @model_validator(mode="after")
    def _verify_contract_stamp(self) -> "ContractStampedModel":
        expected_id = getattr(type(self), "_contract_id", None)
        if expected_id is None:
            raise ValueError("ContractStampedModel subclasses must define _contract_id")
        if self.contract.contract_id != expected_id:
            raise ValueError(
                f"contract.contract_id must be {expected_id!r}, "
                f"got {self.contract.contract_id!r}"
            )
        if self.contract.contract_version != self._contract_version:
            raise ValueError(
                f"contract.contract_version must be {self._contract_version!r}, "
                f"got {self.contract.contract_version!r}"
            )
        expected_hash = model_contract_hash(type(self), expected_id, self._contract_version)
        if self.contract.contract_hash != expected_hash:
            raise ValueError(
                f"contract.contract_hash does not match the canonical generated "
                f"contract hash for {expected_id!r} version {self._contract_version!r}"
            )
        return self


class AssertionSpec(EvaluationStrictModel):
    """Embedded assertion contract (SPEC-022); no independent versioning."""

    assertion_id: str
    kind: AssertionKind
    semantic_version: str | None = None
    contract_hash: str | None = None
    target_references: tuple[str, ...] = Field(min_length=1)
    scoring_gate_config_references: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _no_explicit_null_identity(cls, data: Any) -> Any:
        return _reject_explicit_null(
            data, ("semantic_version", "contract_hash"), "AssertionSpec"
        )

    @model_validator(mode="after")
    def _identity_presence(self) -> "AssertionSpec":
        _require_identity_presence(self, ("semantic_version", "contract_hash"))
        return self


class EvaluationCase(EvaluationStrictModel):
    """Static-schema-backed evaluation case (evaluation_case@0.1.0)."""

    case_id: str
    stage: str
    stage_context: dict[str, JsonValue]
    input_source_ids: tuple[str, ...]
    input_passage_ids: tuple[str, ...]
    assertions: tuple[AssertionSpec, ...] = Field(min_length=1)
    failure_tags: tuple[str, ...]
    notes: str
    created_by: str
    created_at: str
    guideline_version: str


class CaseMembership(EvaluationStrictModel):
    """Embedded case-set membership entry; no independent versioning."""

    case_id: str
    partition: PartitionName
    suites: tuple[SuiteName, ...]
    input_packet_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)


class CaseSetManifest(ContractStampedModel):
    """Versioned case-set manifest owning partition/suite membership."""

    _contract_id: ClassVar[str] = "case_set_manifest"

    case_set_version: str
    lifecycle: Literal["draft", "frozen"]
    registry_snapshot_version: str
    registry_snapshot_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    entries: tuple[CaseMembership, ...]

    @model_validator(mode="after")
    def _unique_case_ids(self) -> "CaseSetManifest":
        seen: set[str] = set()
        for entry in self.entries:
            if entry.case_id in seen:
                raise ValueError(
                    f"duplicate case membership for case_id {entry.case_id!r}; "
                    "exactly one entry per case is allowed"
                )
            seen.add(entry.case_id)
        return self


class MembershipEvent(ContractStampedModel):
    """Append-only case-set membership-change event (SPEC-022)."""

    _contract_id: ClassVar[str] = "membership_event"

    previous_case_set_version: str
    new_case_set_version: str
    case_id: str
    old_partition: PartitionName | None = None
    new_partition: PartitionName | None = None
    added_suites: tuple[SuiteName, ...]
    removed_suites: tuple[SuiteName, ...]
    reason_code: str
    change_reference: str | None = None
    actor: str
    timestamp: str

    @model_validator(mode="after")
    def _timestamp_non_blank(self) -> "MembershipEvent":
        _require_non_blank(self.timestamp, "timestamp")
        return self


class EvaluationRunManifest(ContractStampedModel):
    """Immutable evaluation-run manifest pinning all contract inputs."""

    _contract_id: ClassVar[str] = "evaluation_run_manifest"

    eval_run_id: str
    prediction_run_id: str
    prediction_run_manifest_hash: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    case_set_version: str
    case_set_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    registry_snapshot_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    validator_bundle_version: str
    validator_bundle_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    scoring_gate_config_version: str
    scoring_gate_config_hash: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    code_commit: str
    pydantic_runtime_version: str


class EvaluationRunManifestV2(ContractStampedModel):
    """Immutable evaluation-run manifest v0.2 (ADR-025).

    A strict superset of :class:`EvaluationRunManifest`: the twelve v0.1 fields
    are retained unchanged (``registry_snapshot_hash`` remains the distinct,
    non-overloaded target-registry snapshot hash) and the governed Phase-1
    semantic-substrate identities are added. The applicable stage-evidence pin
    is paired and omitted for extraction stages (never serialized as null).
    ``evaluation_created_at`` is caller-supplied, validated as RFC3339 with an
    explicit offset, and preserved verbatim. Every hash is a lowercase 64-hex
    SHA-256; every identity/version string is non-blank and unnormalized.
    """

    _contract_id: ClassVar[str] = "evaluation_run_manifest"
    _contract_version: ClassVar[str] = "0.2.0"

    # Retained v0.1 fields (identical names, types, and order).
    eval_run_id: str
    prediction_run_id: str
    prediction_run_manifest_hash: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    case_set_version: str
    case_set_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    registry_snapshot_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    validator_bundle_version: str
    validator_bundle_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    scoring_gate_config_version: str
    scoring_gate_config_hash: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    code_commit: str
    pydantic_runtime_version: str
    # New v0.2 required semantic pins (ADR-025).
    evaluation_created_at: str
    stage_profile_registry_version: str
    stage_profile_registry_hash: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    selected_stage_profile_entry_hash: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    semantic_adapter_registry_version: str
    semantic_adapter_registry_hash: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    selected_semantic_adapter_entry_hash: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    source_passage_snapshot_version: str
    source_passage_snapshot_hash: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    gold_assertion_set_version: str
    gold_assertion_set_hash: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    axis_taxonomy_version: str
    axis_taxonomy_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    validator_rule_parameters_version: str
    validator_rule_parameters_hash: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    # New v0.2 paired optional applicable-stage-evidence pin. Present together
    # for Universe stages, omitted together for extraction stages; explicit null
    # is rejected and absent properties never serialize.
    stage_metric_evidence_set_version: str | None = None
    stage_metric_evidence_set_hash: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )

    @model_validator(mode="before")
    @classmethod
    def _no_explicit_null_stage_evidence(cls, data: Any) -> Any:
        return _reject_explicit_null(
            data,
            ("stage_metric_evidence_set_version", "stage_metric_evidence_set_hash"),
            "EvaluationRunManifestV2",
        )

    @model_validator(mode="after")
    def _v2_invariants(self) -> "EvaluationRunManifestV2":
        for field_name in (
            "eval_run_id",
            "prediction_run_id",
            "case_set_version",
            "validator_bundle_version",
            "scoring_gate_config_version",
            "code_commit",
            "pydantic_runtime_version",
            "stage_profile_registry_version",
            "semantic_adapter_registry_version",
            "source_passage_snapshot_version",
            "gold_assertion_set_version",
            "axis_taxonomy_version",
            "validator_rule_parameters_version",
        ):
            _require_non_blank(getattr(self, field_name), field_name)
        _require_rfc3339_offset(self.evaluation_created_at, "evaluation_created_at")
        version_present = "stage_metric_evidence_set_version" in self.model_fields_set
        hash_present = "stage_metric_evidence_set_hash" in self.model_fields_set
        if version_present != hash_present:
            raise ValueError(
                "stage_metric_evidence_set_version and stage_metric_evidence_set_hash "
                "must be supplied together or omitted together"
            )
        if version_present:
            _require_non_blank(
                self.stage_metric_evidence_set_version, "stage_metric_evidence_set_version"
            )
        return self


class PredictionEnvelope(ContractStampedModel):
    """Canonical prediction envelope (SPEC-022)."""

    _contract_id: ClassVar[str] = "prediction_envelope"

    prediction_record_id: str
    stage: str
    source_references: tuple[str, ...]
    prompt_model_metadata: dict[str, JsonValue]
    input_packet_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    prediction_run_manifest_reference: str


class AssertionOutcome(ContractStampedModel):
    """Per-assertion run artifact using the approved outcome vocabulary."""

    _contract_id: ClassVar[str] = "assertion_outcome"

    eval_run_id: str
    case_id: str
    assertion_id: str
    assertion_semantic_version: str | None = None
    assertion_contract_hash: str | None = None
    outcome: AssertionOutcomeValue

    @model_validator(mode="before")
    @classmethod
    def _no_explicit_null_identity(cls, data: Any) -> Any:
        return _reject_explicit_null(
            data,
            ("assertion_semantic_version", "assertion_contract_hash"),
            "AssertionOutcome",
        )

    @model_validator(mode="after")
    def _identity_presence(self) -> "AssertionOutcome":
        _require_identity_presence(
            self, ("assertion_semantic_version", "assertion_contract_hash")
        )
        return self


class ValidatorFinding(ContractStampedModel):
    """Immutable deterministic validator finding (SPEC-023)."""

    _contract_id: ClassVar[str] = "validator_finding"

    finding_id: str
    validator: str
    validator_bundle_version: str
    validator_bundle_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    rule_params_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    severity: FindingSeverity
    run_id: str
    case_id: str | None = None
    entity_id: str | None = None
    artifact_id: str
    observed_value: str
    expected_invariant: str
    message: str
    evidence: str
    repairable: bool
    created_at: str

    @model_validator(mode="after")
    def _created_at_non_blank(self) -> "ValidatorFinding":
        _require_non_blank(self.created_at, "created_at")
        return self


class FindingDisposition(ContractStampedModel):
    """Append-only human disposition on a validator finding (ADR-018)."""

    _contract_id: ClassVar[str] = "finding_disposition"

    disposition_id: str
    finding_id: str
    disposition: DispositionType
    reviewer: str
    timestamp: str
    rationale: str
    linked_evidence: tuple[str, ...]
    proposed_resolution_path: str
    linked_replacement_reference: str | None = None

    @model_validator(mode="after")
    def _timestamp_non_blank(self) -> "FindingDisposition":
        _require_non_blank(self.timestamp, "timestamp")
        return self


class EvaluationResultV2(EvaluationStrictModel):
    """Static-schema-backed evaluation result (evaluation_result@0.2.0).

    ``gate_verdict`` presence is conditional: a completed run must supply it
    and an invalid/errored run must omit the property entirely. Explicit
    JSON null is rejected for ``gate_verdict``, ``errors``, and
    ``created_at``; ``reviewer_notes`` may legitimately be null.
    """

    eval_run_id: str
    stage: str
    dataset_version: str
    metrics: dict[str, JsonValue]
    errors: tuple[JsonValue, ...] | None = None
    execution_status: ExecutionStatus
    gate_verdict: GateVerdict | None = None
    reviewer_notes: str | None = None
    created_at: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_explicit_null(cls, data: Any) -> Any:
        return _reject_explicit_null(
            data, ("gate_verdict", "errors", "created_at"), "EvaluationResultV2"
        )

    @model_validator(mode="after")
    def _verdict_presence(self) -> "EvaluationResultV2":
        supplied = "gate_verdict" in self.model_fields_set
        if self.execution_status == "completed" and not supplied:
            raise ValueError("a completed run requires a supplied gate_verdict")
        if self.execution_status != "completed" and supplied:
            raise ValueError(
                "an invalid or errored run must not carry the gate_verdict property"
            )
        return self
