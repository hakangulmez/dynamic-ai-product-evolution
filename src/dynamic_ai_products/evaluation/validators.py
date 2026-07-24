"""Deterministic validator findings (Slice 8, SPEC-023 / ADR-018).

Slice 8 emits immutable ``ValidatorFinding`` records for the twelve SPEC-023
mechanical checks and persists them as write-once JSONL inside an existing
Slice 5 evaluation-run directory.

Validation target (locked decision, Option B): this module never opens or
parses prediction or source artifacts, never reads raw provider output, and
never calls a registry loader or the Slice 4 resolver. The caller supplies a
strict, frozen ``ValidationArtifactSnapshot`` of typed *primitive*
observations; each of the twelve rules is decided here by its own explicit
handler from those primitives. A caller cannot hand this module a verdict:
no observation carries ``passed``, ``valid``, ``outcome``, or an equivalent
result flag, so pass/fail is always computed, never copied.

Determinism: ``created_at`` is supplied by the snapshot and copied verbatim;
``finding_id`` is a SHA-256 over canonical identity material; the bundle hash
is computed from the bundle, never declared. No wall-clock, randomness,
process state, or filesystem metadata participates in any emitted value, so
the same bundle and snapshot always reproduce byte-identical findings.

Slice 8 assigns no execution status, no gate verdict, no blocking-severity
interpretation and no metric; those belong to Slices 9 and 10. Severity and
repairability come from the validator bundle, never from ``ScoringGateConfig``.

Immutability here means refuse-to-overwrite directories, exclusive-create
files and read-back hash verification — not OS-level immutability.
"""

from __future__ import annotations

import json
import math
import os
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError as PydanticValidationError,
    model_validator,
)

from .cases import InvalidEvaluationRootError
from .contracts import canonical_contract_bytes, model_contract_hash
from .models import (
    EvaluationRunManifest,
    FindingSeverity,
    ValidatorFinding,
)
from .prediction_content import EvaluationStage, LoadedParsedPredictionContent
from .runs import load_evaluation_run_manifest
from ..universe.io_utils import sha256_bytes

_FINDINGS_DIR = "findings"
_FINDINGS_FILENAME = "validator_findings.jsonl"
_FINDING_CONTRACT_ID = "validator_finding"
_FINDING_CONTRACT_VERSION = "0.1.0"
_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"

ValidatorRuleId = Literal[
    "output_json_schema_validity",
    "required_field_presence",
    "source_id_resolution",
    "passage_id_resolution",
    "evidence_quote_containment",
    "publication_date_cutoff",
    "product_capability_task_parent_resolution",
    "unique_ids_within_scope",
    "prohibited_legacy_fields_absent",
    "active_record_non_roadmap_evidence",
    "customer_task_outcome_and_evidence",
    "raw_output_and_repair_preservation",
]

VALIDATOR_RULE_ORDER: tuple[ValidatorRuleId, ...] = (
    "output_json_schema_validity",
    "required_field_presence",
    "source_id_resolution",
    "passage_id_resolution",
    "evidence_quote_containment",
    "publication_date_cutoff",
    "product_capability_task_parent_resolution",
    "unique_ids_within_scope",
    "prohibited_legacy_fields_absent",
    "active_record_non_roadmap_evidence",
    "customer_task_outcome_and_evidence",
    "raw_output_and_repair_preservation",
)

_RULE_POSITION: dict[str, int] = {
    rule_id: index for index, rule_id in enumerate(VALIDATOR_RULE_ORDER)
}


class _Slice8StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _require_non_blank(value: str, field_name: str) -> str:
    """Mirror the governed non-blank convention without importing a private."""
    if not value or value != value.strip():
        raise ValueError(
            f"{field_name} must be a non-empty string without leading or "
            "trailing whitespace"
        )
    return value


def _require_rfc3339(value: str, field_name: str) -> str:
    """Strict RFC3339 timestamp with an explicit offset; parsing only."""
    _require_non_blank(value, field_name)
    candidate = value
    if candidate.endswith(("z", "Z")):
        candidate = f"{candidate[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must carry an explicit RFC3339 UTC offset")
    if "T" not in value and "t" not in value:
        raise ValueError(f"{field_name} must use the RFC3339 date-time separator")
    return value


# --- Validator bundle -----------------------------------------------------


class ValidatorRuleConfig(_Slice8StrictModel):
    """Versioned configuration for one SPEC-023 rule."""

    rule_id: ValidatorRuleId
    severity: FindingSeverity
    rule_params_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    repairable: bool


class ValidatorBundle(_Slice8StrictModel):
    """Non-persisted validator bundle owning severity and repairability."""

    bundle_version: str
    rules: tuple[ValidatorRuleConfig, ...]

    @model_validator(mode="after")
    def _exact_canonical_rule_set(self) -> "ValidatorBundle":
        _require_non_blank(self.bundle_version, "bundle_version")
        observed = tuple(rule.rule_id for rule in self.rules)
        if len(observed) != len(set(observed)):
            raise ValueError("validator bundle declares a duplicate rule ID")
        if observed != VALIDATOR_RULE_ORDER:
            raise ValueError(
                "validator bundle rules must be exactly the twelve SPEC-023 rules "
                "in canonical order"
            )
        return self


def validator_bundle_hash(bundle: ValidatorBundle) -> str:
    """Deterministic SHA-256 over the bundle's governed identity material."""
    if not isinstance(bundle, ValidatorBundle):
        raise TypeError(
            f"validator_bundle_hash requires a ValidatorBundle, got {type(bundle).__name__}"
        )
    payload = {
        "bundle_version": bundle.bundle_version,
        "rules": [
            {
                "rule_id": rule.rule_id,
                "severity": rule.severity,
                "rule_params_hash": rule.rule_params_hash,
                "repairable": rule.repairable,
            }
            for rule in bundle.rules
        ],
    }
    return sha256_bytes(canonical_contract_bytes(payload))


# --- Observations ---------------------------------------------------------


class _ObservationBase(_Slice8StrictModel):
    observation_id: str
    entity_id: str | None = None

    @model_validator(mode="after")
    def _identifiers_non_blank(self) -> "_ObservationBase":
        _require_non_blank(self.observation_id, "observation_id")
        if self.entity_id is not None:
            _require_non_blank(self.entity_id, "entity_id")
        return self


class OutputJsonSchemaValidityObservation(_ObservationBase):
    rule_id: Literal["output_json_schema_validity"]
    parse_succeeded: bool
    schema_valid: bool
    schema_reference: str
    validation_errors: tuple[str, ...]


class RequiredFieldPresenceObservation(_ObservationBase):
    rule_id: Literal["required_field_presence"]
    required_fields: tuple[str, ...]
    present_fields: tuple[str, ...]


class SourceIdResolutionObservation(_ObservationBase):
    rule_id: Literal["source_id_resolution"]
    referenced_source_ids: tuple[str, ...]
    available_source_ids: tuple[str, ...]


class PassageIdResolutionObservation(_ObservationBase):
    rule_id: Literal["passage_id_resolution"]
    referenced_passage_ids: tuple[str, ...]
    available_passage_ids: tuple[str, ...]


class EvidenceQuoteContainmentObservation(_ObservationBase):
    rule_id: Literal["evidence_quote_containment"]
    quote: str
    passage_text: str
    passage_id: str


class PublicationDateCutoffObservation(_ObservationBase):
    rule_id: Literal["publication_date_cutoff"]
    publication_date: date
    observation_cutoff_date: date
    source_id: str


class ProductCapabilityTaskParentResolutionObservation(_ObservationBase):
    rule_id: Literal["product_capability_task_parent_resolution"]
    child_id: str
    parent_id: str
    available_parent_ids: tuple[str, ...]


class UniqueIdsWithinScopeObservation(_ObservationBase):
    rule_id: Literal["unique_ids_within_scope"]
    scope_id: str
    record_ids: tuple[str, ...]


class ProhibitedLegacyFieldsAbsentObservation(_ObservationBase):
    rule_id: Literal["prohibited_legacy_fields_absent"]
    present_field_names: tuple[str, ...]
    prohibited_field_names: tuple[str, ...]


class EvidenceClassification(_Slice8StrictModel):
    evidence_id: str
    is_future_roadmap: bool


class ActiveRecordNonRoadmapEvidenceObservation(_ObservationBase):
    rule_id: Literal["active_record_non_roadmap_evidence"]
    active: bool
    evidence: tuple[EvidenceClassification, ...]


class CustomerTaskOutcomeAndEvidenceObservation(_ObservationBase):
    rule_id: Literal["customer_task_outcome_and_evidence"]
    is_customer_facing_task: bool
    customer_outcome: str | None = None
    evidence_ids: tuple[str, ...]


def _is_lower_sha256_hex(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _is_safe_reference(value: object) -> bool:
    """Local mirror of the governed safe-relative-reference policy.

    Mirrors ``prediction_content``'s parsed-content reference policy without
    importing or re-exporting a private parser helper: a reference must be a
    non-blank, edge-whitespace-free, relative POSIX path with no backslash, NUL,
    empty, ``.`` or ``..`` segment.
    """
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if "\\" in value or "\x00" in value:
        return False
    if Path(value).is_absolute():
        return False
    return all(part not in ("", ".", "..") for part in value.split("/"))


class RawOutputAndRepairPreservationObservation(_ObservationBase):
    rule_id: Literal["raw_output_and_repair_preservation"]
    raw_output_reference: str | None = None
    raw_artifact_sha256: str | None = None
    raw_output_preserved: bool
    repair_applied: bool
    repair_record_references: tuple[str, ...]
    repair_record_hashes: tuple[str, ...] = ()
    parsed_content_sha256: str | None = None

    @model_validator(mode="after")
    def _hash_provenance(self) -> "RawOutputAndRepairPreservationObservation":
        if self.raw_artifact_sha256 is not None and not _is_lower_sha256_hex(
            self.raw_artifact_sha256
        ):
            raise ValueError("raw_artifact_sha256 must be a lowercase 64-hex SHA-256")
        for digest in self.repair_record_hashes:
            if not isinstance(digest, str) or not _is_lower_sha256_hex(digest):
                raise ValueError("repair_record_hashes entries must be lowercase 64-hex SHA-256")
        # Provenance references must satisfy the governed safe-relative policy
        # (valid hashes alone are not sufficient) and repair references must be
        # deterministic and unique.
        if self.raw_output_reference is not None and not _is_safe_reference(
            self.raw_output_reference
        ):
            raise ValueError("raw_output_reference must be a safe relative reference")
        for reference in self.repair_record_references:
            if not _is_safe_reference(reference):
                raise ValueError(
                    "repair_record_references entries must be non-blank safe relative references"
                )
        if len(set(self.repair_record_references)) != len(self.repair_record_references):
            raise ValueError("repair_record_references must be unique")
        return self


ValidatorObservation = Annotated[
    OutputJsonSchemaValidityObservation
    | RequiredFieldPresenceObservation
    | SourceIdResolutionObservation
    | PassageIdResolutionObservation
    | EvidenceQuoteContainmentObservation
    | PublicationDateCutoffObservation
    | ProductCapabilityTaskParentResolutionObservation
    | UniqueIdsWithinScopeObservation
    | ProhibitedLegacyFieldsAbsentObservation
    | ActiveRecordNonRoadmapEvidenceObservation
    | CustomerTaskOutcomeAndEvidenceObservation
    | RawOutputAndRepairPreservationObservation,
    Field(discriminator="rule_id"),
]


# --- Coverage records (Slice 12F) -----------------------------------------

ValidatorRuleCoverageState = Literal[
    "fully_evaluated",
    "partially_evaluated",
    "inapplicable",
    "blocked_by_dependency",
]

_RULE_12 = "raw_output_and_repair_preservation"

# Governed matrix reduction (SPEC-023 / ADR-024): the only rules that may be
# inapplicable, and only at the two universe stages. Extraction stages have no
# inapplicable rule. This is the direct-construction gate; evaluate additionally
# binds each coverage record to the loaded parameters' exact stage entry.
_STAGE_OPTIONAL_INAPPLICABLE: dict[str, frozenset[str]] = {
    "universe_screen": frozenset(
        {
            "product_capability_task_parent_resolution",
            "active_record_non_roadmap_evidence",
            "customer_task_outcome_and_evidence",
        }
    ),
    "universe_classification": frozenset(
        {
            "product_capability_task_parent_resolution",
            "active_record_non_roadmap_evidence",
            "customer_task_outcome_and_evidence",
        }
    ),
}


class ValidatorRuleCoverageReasonCount(_Slice8StrictModel):
    reason_code: str
    count: int

    @model_validator(mode="after")
    def _reason_invariants(self) -> "ValidatorRuleCoverageReasonCount":
        _require_non_blank(self.reason_code, "reason_code")
        if self.count < 1:
            raise ValueError("reason count must be a positive integer")
        return self


class ValidatorRuleCoverage(_Slice8StrictModel):
    rule_id: ValidatorRuleId
    coverage_state: ValidatorRuleCoverageState
    candidate_count: int
    evaluated_observation_count: int
    blocked_candidate_count: int
    reason_counts: tuple[ValidatorRuleCoverageReasonCount, ...] = ()

    @model_validator(mode="after")
    def _coverage_invariants(self) -> "ValidatorRuleCoverage":
        for name in (
            "candidate_count",
            "evaluated_observation_count",
            "blocked_candidate_count",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if (
            self.evaluated_observation_count + self.blocked_candidate_count
            > self.candidate_count
        ):
            raise ValueError("evaluated + blocked must not exceed candidate_count")
        codes = [rc.reason_code for rc in self.reason_counts]
        if codes != sorted(codes):
            raise ValueError("reason_counts must be in ascending reason_code order")
        if len(set(codes)) != len(codes):
            raise ValueError("reason_counts must have unique reason_code")
        total = sum(rc.count for rc in self.reason_counts)
        state = self.coverage_state
        if state == "fully_evaluated":
            if not (
                self.candidate_count >= 1
                and self.evaluated_observation_count == self.candidate_count
                and self.blocked_candidate_count == 0
                and not self.reason_counts
            ):
                raise ValueError(
                    "fully_evaluated requires evaluated==candidate>=1, blocked==0, no reasons"
                )
        elif state == "partially_evaluated":
            if not (
                0 < self.evaluated_observation_count < self.candidate_count
                and self.blocked_candidate_count >= 1
                and self.evaluated_observation_count + self.blocked_candidate_count
                == self.candidate_count
                and self.reason_counts
                and total == self.blocked_candidate_count
            ):
                raise ValueError("partially_evaluated coverage invariants violated")
        elif state == "blocked_by_dependency":
            if not (
                self.candidate_count >= 1
                and self.evaluated_observation_count == 0
                and self.blocked_candidate_count == self.candidate_count
                and self.reason_counts
                and total == self.blocked_candidate_count
            ):
                raise ValueError("blocked_by_dependency coverage invariants violated")
        else:  # inapplicable
            if not (
                self.candidate_count == 0
                and self.evaluated_observation_count == 0
                and self.blocked_candidate_count == 0
                and len(self.reason_counts) == 1
                and self.reason_counts[0].count == 1
            ):
                raise ValueError(
                    "inapplicable requires zero counts and exactly one reason with count 1"
                )
        return self


class ValidationArtifactSnapshot(_Slice8StrictModel):
    """Caller-supplied normalized primitives for one artifact under validation."""

    eval_run_id: str
    artifact_id: str
    stage: EvaluationStage
    artifact_sha256: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    parsed_prediction_content_sha256: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    created_at: str
    case_id: str | None = None
    observations: tuple[ValidatorObservation, ...]
    coverage: tuple[ValidatorRuleCoverage, ...]

    @model_validator(mode="after")
    def _snapshot_invariants(self) -> "ValidationArtifactSnapshot":
        _require_non_blank(self.eval_run_id, "eval_run_id")
        _require_non_blank(self.artifact_id, "artifact_id")
        _require_rfc3339(self.created_at, "created_at")
        if self.case_id is not None:
            _require_non_blank(self.case_id, "case_id")
        allowed_inapplicable = _STAGE_OPTIONAL_INAPPLICABLE.get(self.stage, frozenset())
        for record in self.coverage:
            if (
                record.coverage_state == "inapplicable"
                and record.rule_id not in allowed_inapplicable
            ):
                raise ValueError(
                    f"rule {record.rule_id!r} may not be inapplicable at stage {self.stage!r}"
                )
        seen: set[str] = set()
        for observation in self.observations:
            if observation.observation_id in seen:
                raise ValueError(
                    f"duplicate observation_id {observation.observation_id!r} in snapshot"
                )
            seen.add(observation.observation_id)
        coverage_rules = tuple(record.rule_id for record in self.coverage)
        if coverage_rules != VALIDATOR_RULE_ORDER:
            raise ValueError(
                "coverage must carry exactly the twelve rules in canonical order"
            )
        obs_by_rule = Counter(observation.rule_id for observation in self.observations)
        for record in self.coverage:
            if obs_by_rule.get(record.rule_id, 0) != record.evaluated_observation_count:
                raise ValueError(
                    f"observation count for {record.rule_id!r} does not equal "
                    "evaluated_observation_count"
                )
        rule12 = next(r for r in self.coverage if r.rule_id == _RULE_12)
        if not (
            rule12.coverage_state == "fully_evaluated"
            and rule12.candidate_count == 1
            and rule12.evaluated_observation_count == 1
            and rule12.blocked_candidate_count == 0
            and not rule12.reason_counts
        ):
            raise ValueError(
                "Rule 12 coverage must be fully_evaluated with counts 1/1/0 and no reasons"
            )
        rule12_obs = [o for o in self.observations if o.rule_id == _RULE_12]
        if len(rule12_obs) != 1:
            raise ValueError("snapshot must carry exactly one Rule 12 observation")
        if rule12_obs[0].parsed_content_sha256 != self.parsed_prediction_content_sha256:
            raise ValueError(
                "Rule 12 observation parsed_content_sha256 must equal the snapshot's "
                "parsed_prediction_content_sha256"
            )
        return self


# --- Result model ---------------------------------------------------------


class EvaluatedValidatorFindings(_Slice8StrictModel):
    eval_run_id: str
    artifact_id: str
    artifact_sha256: str
    validator_bundle_version: str
    validator_bundle_hash: str
    findings: tuple[ValidatorFinding, ...]


class PersistedValidatorFindings(_Slice8StrictModel):
    eval_run_id: str
    artifact_reference: str
    sha256: str
    findings: tuple[ValidatorFinding, ...]


class LoadedValidatorFindings(_Slice8StrictModel):
    eval_run_id: str
    artifact_reference: str
    sha256: str
    findings: tuple[ValidatorFinding, ...]


# --- Exceptions -----------------------------------------------------------


class ValidatorError(Exception):
    """Base class for Slice 8 validator failures; never raised directly."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_id: str | None = None,
        artifact_reference: str | None = None,
        rule_id: str | None = None,
        observation_id: str | None = None,
        finding_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.eval_run_id = eval_run_id
        self.artifact_id = artifact_id
        self.artifact_reference = artifact_reference
        self.rule_id = rule_id
        self.observation_id = observation_id
        self.finding_id = finding_id


class ValidatorBundleBindingError(ValidatorError):
    """Bundle version or computed hash does not match the run manifest."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        binding_kind: str | None = None,
    ) -> None:
        super().__init__(message, eval_run_id=eval_run_id)
        self.binding_kind = binding_kind


class SnapshotRunBindingError(ValidatorError):
    """The snapshot's eval_run_id does not match the run manifest."""


class ValidatorFindingsExistError(ValidatorError):
    """The findings output directory already exists in some form."""


class ValidatorArtifactMissingError(ValidatorError):
    """A required findings artifact does not exist."""


class ValidatorArtifactNotAFileError(ValidatorError):
    """A required findings artifact is not a regular file."""


class ValidatorArtifactReadError(ValidatorError):
    """Reading a findings artifact failed."""


class ValidatorDecodeError(ValidatorError):
    """A findings artifact's bytes are not valid UTF-8."""


class ValidatorJsonError(ValidatorError):
    """A findings artifact is not acceptable strict JSONL."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
        line_number: int | None = None,
        duplicate_key: str | None = None,
        constant_name: str | None = None,
    ) -> None:
        super().__init__(
            message, eval_run_id=eval_run_id, artifact_reference=artifact_reference
        )
        self.line_number = line_number
        self.duplicate_key = duplicate_key
        self.constant_name = constant_name


class ValidatorTopLevelTypeError(ValidatorError):
    """A parsed findings line is not a JSON object."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
        observed_type: str | None = None,
        line_number: int | None = None,
    ) -> None:
        super().__init__(
            message, eval_run_id=eval_run_id, artifact_reference=artifact_reference
        )
        self.observed_type = observed_type
        self.line_number = line_number


class ValidatorModelValidationError(ValidatorError):
    """A findings line failed ValidatorFinding model/contract validation."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
        line_number: int | None = None,
        field_locations: tuple[str, ...] = (),
        error_types: tuple[str, ...] = (),
    ) -> None:
        super().__init__(
            message, eval_run_id=eval_run_id, artifact_reference=artifact_reference
        )
        self.line_number = line_number
        self.field_locations = field_locations
        self.error_types = error_types


class DuplicateValidatorFindingError(ValidatorError):
    """Two findings share a finding_id."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
        finding_id: str | None = None,
        line_number: int | None = None,
    ) -> None:
        super().__init__(
            message, eval_run_id=eval_run_id, artifact_reference=artifact_reference,
            finding_id=finding_id,
        )
        self.line_number = line_number


class ValidatorFindingRunBindingError(ValidatorError):
    """A finding's run_id does not match the requested evaluation run."""


class ValidatorWriteError(ValidatorError):
    """Writing a findings artifact failed."""


class ValidatorDestinationHashMismatchError(ValidatorError):
    """A written findings artifact re-read to a different hash."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
        expected_sha256: str | None = None,
        observed_sha256: str | None = None,
    ) -> None:
        super().__init__(
            message, eval_run_id=eval_run_id, artifact_reference=artifact_reference
        )
        self.expected_sha256 = expected_sha256
        self.observed_sha256 = observed_sha256


class _DuplicateKeyControl(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


class _NonFiniteControl(Exception):
    def __init__(self, constant_name: str) -> None:
        super().__init__(constant_name)
        self.constant_name = constant_name


# --- Rule handlers --------------------------------------------------------
#
# Each handler decides its rule from the observation's typed primitives and
# returns None when the invariant holds, or a deterministic
# (observed_value, expected_invariant, message, evidence) tuple when it is
# violated. No handler receives or returns a caller-supplied verdict, and no
# handler emits raw quote, passage, outcome or provider text.

_RuleOutcome = tuple[str, str, str, str] | None


def _count_phrase(label: str, value: int) -> str:
    return f"{label}={value}"


def _handle_output_json_schema_validity(
    observation: OutputJsonSchemaValidityObservation,
) -> _RuleOutcome:
    if observation.parse_succeeded and observation.schema_valid:
        return None
    return (
        f"parse_succeeded={observation.parse_succeeded};"
        f"schema_valid={observation.schema_valid};"
        f"{_count_phrase('validation_error_count', len(observation.validation_errors))}",
        "artifact JSON must parse and validate against its declared schema",
        "artifact output failed JSON parsing or schema validation",
        f"schema_reference={observation.schema_reference}",
    )


def _handle_required_field_presence(
    observation: RequiredFieldPresenceObservation,
) -> _RuleOutcome:
    present = set(observation.present_fields)
    missing = tuple(f for f in observation.required_fields if f not in present)
    if not missing:
        return None
    return (
        _count_phrase("missing_required_field_count", len(missing)),
        "every declared required field must be present",
        "artifact omits one or more required fields",
        f"missing_required_fields={','.join(sorted(missing))}",
    )


def _handle_source_id_resolution(observation: SourceIdResolutionObservation) -> _RuleOutcome:
    available = set(observation.available_source_ids)
    unresolved = tuple(s for s in observation.referenced_source_ids if s not in available)
    if not unresolved:
        return None
    return (
        _count_phrase("unresolved_source_id_count", len(unresolved)),
        "every referenced source ID must resolve in the pinned registry snapshot",
        "artifact references one or more unresolvable source IDs",
        f"unresolved_source_ids={','.join(sorted(unresolved))}",
    )


def _handle_passage_id_resolution(observation: PassageIdResolutionObservation) -> _RuleOutcome:
    available = set(observation.available_passage_ids)
    unresolved = tuple(p for p in observation.referenced_passage_ids if p not in available)
    if not unresolved:
        return None
    return (
        _count_phrase("unresolved_passage_id_count", len(unresolved)),
        "every referenced passage ID must resolve in the pinned registry snapshot",
        "artifact references one or more unresolvable passage IDs",
        f"unresolved_passage_ids={','.join(sorted(unresolved))}",
    )


def _handle_evidence_quote_containment(
    observation: EvidenceQuoteContainmentObservation,
) -> _RuleOutcome:
    # A blank quote is not real evidence: it must fail rather than pass by the
    # empty-string-is-a-substring accident.
    quote_present = observation.quote.strip() != ""
    if quote_present and observation.quote in observation.passage_text:
        return None
    # Raw quote and passage text never leave this function: only lengths,
    # hashes and the passage ID describe the failure.
    return (
        f"quote_present={quote_present};"
        f"quote_length={len(observation.quote)};"
        f"passage_length={len(observation.passage_text)};"
        f"quote_sha256={sha256_bytes(observation.quote.encode('utf-8'))}",
        "the evidence quote must be non-blank and occur verbatim in the cited passage",
        "evidence quote is blank or does not occur in the cited passage",
        f"passage_id={observation.passage_id};"
        f"passage_sha256={sha256_bytes(observation.passage_text.encode('utf-8'))}",
    )


def _handle_publication_date_cutoff(
    observation: PublicationDateCutoffObservation,
) -> _RuleOutcome:
    if observation.publication_date <= observation.observation_cutoff_date:
        return None
    return (
        f"publication_date={observation.publication_date.isoformat()};"
        f"observation_cutoff_date={observation.observation_cutoff_date.isoformat()}",
        "publication_date must not be later than observation_cutoff_date",
        "source publication date is later than the observation cutoff",
        f"source_id={observation.source_id}",
    )


def _handle_product_capability_task_parent_resolution(
    observation: ProductCapabilityTaskParentResolutionObservation,
) -> _RuleOutcome:
    if observation.parent_id in observation.available_parent_ids:
        return None
    return (
        f"parent_id={observation.parent_id};"
        f"{_count_phrase('available_parent_count', len(observation.available_parent_ids))}",
        "each product-capability-task child must resolve to an available parent",
        "product-capability-task parent link does not resolve",
        f"child_id={observation.child_id}",
    )


def _handle_unique_ids_within_scope(
    observation: UniqueIdsWithinScopeObservation,
) -> _RuleOutcome:
    seen: set[str] = set()
    duplicates: list[str] = []
    for record_id in observation.record_ids:
        if record_id in seen and record_id not in duplicates:
            duplicates.append(record_id)
        seen.add(record_id)
    if not duplicates:
        return None
    return (
        f"{_count_phrase('record_id_count', len(observation.record_ids))};"
        f"{_count_phrase('distinct_record_id_count', len(seen))}",
        "record IDs must be unique within the declared scope",
        "duplicate record IDs occur within the declared scope",
        f"scope_id={observation.scope_id};"
        f"duplicate_record_ids={','.join(sorted(duplicates))}",
    )


def _handle_prohibited_legacy_fields_absent(
    observation: ProhibitedLegacyFieldsAbsentObservation,
) -> _RuleOutcome:
    present = set(observation.present_field_names)
    offending = tuple(f for f in observation.prohibited_field_names if f in present)
    if not offending:
        return None
    return (
        _count_phrase("prohibited_field_count", len(offending)),
        "no prohibited legacy field may be present",
        "artifact contains one or more prohibited legacy fields",
        f"prohibited_fields_present={','.join(sorted(offending))}",
    )


def _handle_active_record_non_roadmap_evidence(
    observation: ActiveRecordNonRoadmapEvidenceObservation,
) -> _RuleOutcome:
    if not observation.active:
        return None
    if any(not item.is_future_roadmap for item in observation.evidence):
        return None
    return (
        f"active={observation.active};"
        f"{_count_phrase('evidence_count', len(observation.evidence))};"
        f"{_count_phrase('non_roadmap_evidence_count', 0)}",
        "an active record must carry at least one non-roadmap evidence item",
        "active record is supported only by future-roadmap evidence",
        f"evidence_ids={','.join(sorted(i.evidence_id for i in observation.evidence))}",
    )


def _handle_customer_task_outcome_and_evidence(
    observation: CustomerTaskOutcomeAndEvidenceObservation,
) -> _RuleOutcome:
    if not observation.is_customer_facing_task:
        return None
    outcome = observation.customer_outcome
    outcome_present = outcome is not None and outcome.strip() != ""
    # A blank evidence ID does not count as supporting evidence.
    nonblank_evidence = tuple(e for e in observation.evidence_ids if e.strip() != "")
    if outcome_present and nonblank_evidence:
        return None
    # The customer-outcome text itself is never emitted.
    return (
        f"customer_outcome_present={outcome_present};"
        f"{_count_phrase('evidence_id_count', len(observation.evidence_ids))};"
        f"{_count_phrase('nonblank_evidence_id_count', len(nonblank_evidence))}",
        "a customer-facing task must have a non-blank customer outcome and non-blank evidence",
        "customer-facing task lacks a customer outcome or supporting evidence",
        f"evidence_ids={','.join(sorted(nonblank_evidence))}",
    )


def _handle_raw_output_and_repair_preservation(
    observation: RawOutputAndRepairPreservationObservation,
) -> _RuleOutcome:
    reference = observation.raw_output_reference
    raw_present = reference is not None and reference.strip() != ""
    sha = observation.raw_artifact_sha256
    sha_present = sha is not None and sha.strip() != ""
    # A blank repair-record reference does not count as a preserved repair record.
    nonblank_repairs = tuple(r for r in observation.repair_record_references if r.strip() != "")
    # Repair reference/hash provenance must pair exactly when a repair was applied.
    if observation.repair_applied:
        repair_ok = (
            len(observation.repair_record_references) == len(observation.repair_record_hashes)
            and len(nonblank_repairs) == len(observation.repair_record_references)
            and len(nonblank_repairs) >= 1
        )
    else:
        repair_ok = (
            not observation.repair_record_references and not observation.repair_record_hashes
        )
    if raw_present and sha_present and observation.raw_output_preserved and repair_ok:
        return None
    return (
        f"raw_output_reference_present={raw_present};"
        f"raw_artifact_sha256_present={sha_present};"
        f"raw_output_preserved={observation.raw_output_preserved};"
        f"repair_applied={observation.repair_applied};"
        f"{_count_phrase('repair_record_count', len(observation.repair_record_references))};"
        f"{_count_phrase('repair_record_hash_count', len(observation.repair_record_hashes))};"
        f"{_count_phrase('nonblank_repair_record_count', len(nonblank_repairs))}",
        "raw model output must be preserved with its hash and any repair must carry paired "
        "non-blank reference and hash records",
        "raw output reference/hash or required repair reference/hash provenance is missing",
        f"repair_record_references={','.join(sorted(nonblank_repairs))}",
    )


def _dispatch_rule(observation: Any) -> _RuleOutcome:
    """Explicit static dispatch: one named handler per SPEC-023 rule."""
    match observation.rule_id:
        case "output_json_schema_validity":
            return _handle_output_json_schema_validity(observation)
        case "required_field_presence":
            return _handle_required_field_presence(observation)
        case "source_id_resolution":
            return _handle_source_id_resolution(observation)
        case "passage_id_resolution":
            return _handle_passage_id_resolution(observation)
        case "evidence_quote_containment":
            return _handle_evidence_quote_containment(observation)
        case "publication_date_cutoff":
            return _handle_publication_date_cutoff(observation)
        case "product_capability_task_parent_resolution":
            return _handle_product_capability_task_parent_resolution(observation)
        case "unique_ids_within_scope":
            return _handle_unique_ids_within_scope(observation)
        case "prohibited_legacy_fields_absent":
            return _handle_prohibited_legacy_fields_absent(observation)
        case "active_record_non_roadmap_evidence":
            return _handle_active_record_non_roadmap_evidence(observation)
        case "customer_task_outcome_and_evidence":
            return _handle_customer_task_outcome_and_evidence(observation)
        case "raw_output_and_repair_preservation":
            return _handle_raw_output_and_repair_preservation(observation)
    # Unreachable: the discriminated union restricts rule_id to the twelve
    # governed literals. Defensive only; never part of the public surface.
    raise RuntimeError(  # pragma: no cover
        f"unhandled validator rule id {observation.rule_id!r}"
    )


# --- Deterministic identity ----------------------------------------------


def _finding_identity_bytes(
    *,
    eval_run_id: str,
    artifact_id: str,
    artifact_sha256: str,
    case_id: str | None,
    entity_id: str | None,
    observation_id: str,
    rule_id: str,
    bundle_hash: str,
    rule_params_hash: str,
) -> bytes:
    return canonical_contract_bytes(
        {
            "artifact_id": artifact_id,
            "artifact_sha256": artifact_sha256,
            "case_id": case_id,
            "entity_id": entity_id,
            "eval_run_id": eval_run_id,
            "observation_id": observation_id,
            "rule_id": rule_id,
            "rule_params_hash": rule_params_hash,
            "validator_bundle_hash": bundle_hash,
        }
    )


def _finding_contract_metadata() -> dict[str, str]:
    return {
        "contract_id": _FINDING_CONTRACT_ID,
        "contract_version": _FINDING_CONTRACT_VERSION,
        "contract_hash": model_contract_hash(
            ValidatorFinding, _FINDING_CONTRACT_ID, _FINDING_CONTRACT_VERSION
        ),
    }


# --- Pure evaluation ------------------------------------------------------


def _build_rule12_validation_observation(
    loaded: LoadedParsedPredictionContent,
) -> tuple[RawOutputAndRepairPreservationObservation, ValidatorRuleCoverage]:
    """Derive the single Rule 12 observation and its coverage from parsed content.

    Module-private: the sanctioned public entry point is
    ``build_validation_artifact_snapshot``. Both the observation's
    ``parsed_content_sha256`` and the snapshot's
    ``parsed_prediction_content_sha256`` are derived from the same
    ``LoadedParsedPredictionContent.sha256``.
    """
    if not isinstance(loaded, LoadedParsedPredictionContent):
        raise TypeError(
            f"loaded must be a LoadedParsedPredictionContent, got {type(loaded).__name__}"
        )
    content = loaded.content
    observation = RawOutputAndRepairPreservationObservation(
        observation_id=f"rule12:{content.prediction_record_id}",
        rule_id="raw_output_and_repair_preservation",
        raw_output_reference=content.raw_artifact_reference,
        raw_artifact_sha256=content.raw_artifact_sha256,
        raw_output_preserved=content.raw_output_preserved,
        repair_applied=content.repair_applied,
        repair_record_references=content.repair_record_references,
        repair_record_hashes=content.repair_record_hashes,
        parsed_content_sha256=loaded.sha256,
    )
    coverage = ValidatorRuleCoverage(
        rule_id="raw_output_and_repair_preservation",
        coverage_state="fully_evaluated",
        candidate_count=1,
        evaluated_observation_count=1,
        blocked_candidate_count=0,
        reason_counts=(),
    )
    return observation, coverage


def build_validation_artifact_snapshot(
    loaded: LoadedParsedPredictionContent,
    *,
    eval_run_id: str,
    artifact_id: str,
    artifact_sha256: str,
    created_at: str,
    case_id: str | None = None,
    observations: tuple[ValidatorObservation, ...],
    coverage: tuple[ValidatorRuleCoverage, ...],
) -> ValidationArtifactSnapshot:
    """The sole sanctioned public producer of a full validation-artifact snapshot.

    Accepts caller-supplied Rules 1-11 observations and coverage only; rejects a
    caller-supplied Rule 12 observation or Rule 12 coverage record. Rule 12 is
    obtained exclusively through ``_build_rule12_validation_observation(loaded)``
    and appended in canonical order, and ``parsed_prediction_content_sha256`` is
    bound to ``loaded.sha256``. Direct low-level model construction remains
    possible but is not the integration path.
    """
    if not isinstance(loaded, LoadedParsedPredictionContent):
        raise TypeError(
            f"loaded must be a LoadedParsedPredictionContent, got {type(loaded).__name__}"
        )
    for observation in observations:
        if observation.rule_id == _RULE_12:
            raise ValueError(
                "caller-supplied observations must cover Rules 1-11 only; "
                "Rule 12 is produced internally"
            )
    for record in coverage:
        if record.rule_id == _RULE_12:
            raise ValueError(
                "caller-supplied coverage must cover Rules 1-11 only; "
                "Rule 12 is produced internally"
            )
    rule12_observation, rule12_coverage = _build_rule12_validation_observation(loaded)
    return ValidationArtifactSnapshot(
        eval_run_id=eval_run_id,
        artifact_id=artifact_id,
        stage=loaded.content.stage,
        artifact_sha256=artifact_sha256,
        parsed_prediction_content_sha256=loaded.sha256,
        created_at=created_at,
        case_id=case_id,
        observations=tuple(observations) + (rule12_observation,),
        coverage=tuple(coverage) + (rule12_coverage,),
    )


def evaluate_validator_findings(
    snapshot: ValidationArtifactSnapshot,
    *,
    bundle: ValidatorBundle,
    run_manifest: EvaluationRunManifest,
    rule_parameters: Any,
) -> EvaluatedValidatorFindings:
    """Run the twelve SPEC-023 rules over one normalized artifact snapshot.

    Pure: no filesystem access, no source or registry read, no resolver call,
    no wall-clock read. Coverage-aware production requires an
    ``EvaluationRunManifestV2`` and a ``LoadedValidatorRuleParameters`` whose
    version and aggregate hash equal the v0.2 pin; a v0.1 manifest fails with the
    ``run_manifest_version_unsupported`` binding kind before any finding is
    produced. Emits one immutable ``ValidatorFinding`` per failed observation,
    ordered by canonical rule order then ``observation_id``.
    """
    from .models import EvaluationRunManifestV2
    from .validator_parameters import (
        LoadedValidatorRuleParameters,
        complete_rule_parameter_hash,
        validator_rule_parameters_aggregate_hash,
    )

    if not isinstance(snapshot, ValidationArtifactSnapshot):
        raise TypeError(
            f"snapshot must be a ValidationArtifactSnapshot, got {type(snapshot).__name__}"
        )
    if not isinstance(bundle, ValidatorBundle):
        raise TypeError(f"bundle must be a ValidatorBundle, got {type(bundle).__name__}")
    if not isinstance(run_manifest, EvaluationRunManifestV2):
        raise ValidatorBundleBindingError(
            "coverage-aware deterministic validation requires evaluation_run_manifest v0.2",
            eval_run_id=getattr(run_manifest, "eval_run_id", None),
            binding_kind="run_manifest_version_unsupported",
        )
    if not isinstance(rule_parameters, LoadedValidatorRuleParameters):
        raise TypeError(
            f"rule_parameters must be a LoadedValidatorRuleParameters, got "
            f"{type(rule_parameters).__name__}"
        )

    # The bundle model already guarantees exactly the twelve rules in
    # canonical order, so this mapping always has all twelve keys.
    rule_by_id = {rule.rule_id: rule for rule in bundle.rules}
    entries_by_rule = {entry.rule_id: entry for entry in rule_parameters.model.entries}

    if rule_parameters.version != run_manifest.validator_rule_parameters_version:
        raise ValidatorBundleBindingError(
            "validator rule parameters version does not match the run manifest pin",
            eval_run_id=run_manifest.eval_run_id,
            binding_kind="parameter_set_version_mismatch",
        )
    if (
        validator_rule_parameters_aggregate_hash(rule_parameters.model)
        != run_manifest.validator_rule_parameters_hash
    ):
        raise ValidatorBundleBindingError(
            "validator rule parameters aggregate hash does not match the run manifest pin",
            eval_run_id=run_manifest.eval_run_id,
            binding_kind="parameter_set_hash_mismatch",
        )
    for rule in bundle.rules:
        if rule.rule_params_hash != complete_rule_parameter_hash(entries_by_rule[rule.rule_id]):
            raise ValidatorBundleBindingError(
                "bundle rule_params_hash does not equal the complete per-rule parameter hash",
                eval_run_id=run_manifest.eval_run_id,
                binding_kind="rule_params_hash_mismatch",
            )
    for record in snapshot.coverage:
        entry = entries_by_rule[record.rule_id]
        selected = next(sp for sp in entry.stage_parameters if sp.stage == snapshot.stage)
        # Structural dependency-absent guard first: a rule that declares no
        # dependency can never have blocked candidates, regardless of stage
        # applicability or the (necessarily empty) governed reason set. This must
        # precede reason governance so the correct binding_kind is reported.
        if record.blocked_candidate_count > 0 and not entry.dependency_rule_ids:
            raise ValidatorBundleBindingError(
                "blocked coverage requires the rule to declare a dependency",
                eval_run_id=run_manifest.eval_run_id,
                binding_kind="coverage_dependency_absent",
            )
        if selected.applicability == "inapplicable":
            if record.coverage_state != "inapplicable":
                raise ValidatorBundleBindingError(
                    "an inapplicable stage parameter permits only inapplicable coverage",
                    eval_run_id=run_manifest.eval_run_id,
                    binding_kind="coverage_inapplicable_stage_state",
                )
            for reason in record.reason_counts:
                if reason.reason_code != selected.reason_code:
                    raise ValidatorBundleBindingError(
                        "coverage inapplicable reason does not equal the selected stage reason",
                        eval_run_id=run_manifest.eval_run_id,
                        binding_kind="coverage_reason_code_unknown",
                    )
        else:
            if record.coverage_state == "inapplicable":
                raise ValidatorBundleBindingError(
                    "an applicable stage parameter rejects inapplicable coverage",
                    eval_run_id=run_manifest.eval_run_id,
                    binding_kind="coverage_applicable_stage_inapplicable",
                )
            governed = set(entry.blocking_reason_codes)
            for reason in record.reason_counts:
                if reason.reason_code not in governed:
                    raise ValidatorBundleBindingError(
                        "coverage reason code is not governed by the rule parameters",
                        eval_run_id=run_manifest.eval_run_id,
                        binding_kind="coverage_reason_code_unknown",
                    )
        # Truthful dependency blocking: a rule with blocked candidates (its
        # dependency non-empty by the guard above) is only legitimate when at
        # least one declared dependency actually fails in this snapshot under the
        # same pure dispatch. A clean dependency can never justify omitting the
        # rule's observation.
        if record.blocked_candidate_count > 0:
            dependency_failed = any(
                observation.rule_id in entry.dependency_rule_ids
                and _dispatch_rule(observation) is not None
                for observation in snapshot.observations
            )
            if not dependency_failed:
                raise ValidatorBundleBindingError(
                    "blocked coverage requires a declared dependency to actually fail",
                    eval_run_id=run_manifest.eval_run_id,
                    binding_kind="coverage_dependency_not_failing",
                )

    if bundle.bundle_version != run_manifest.validator_bundle_version:
        raise ValidatorBundleBindingError(
            "validator bundle version does not match the run manifest",
            eval_run_id=run_manifest.eval_run_id,
            binding_kind="bundle_version_mismatch",
        )
    computed_hash = validator_bundle_hash(bundle)
    if computed_hash != run_manifest.validator_bundle_hash:
        raise ValidatorBundleBindingError(
            "computed validator bundle hash does not match the run manifest",
            eval_run_id=run_manifest.eval_run_id,
            binding_kind="bundle_hash_mismatch",
        )
    if snapshot.eval_run_id != run_manifest.eval_run_id:
        raise SnapshotRunBindingError(
            "snapshot eval_run_id does not match the run manifest",
            eval_run_id=run_manifest.eval_run_id,
            artifact_id=snapshot.artifact_id,
        )

    ordered = sorted(
        snapshot.observations,
        key=lambda o: (_RULE_POSITION[o.rule_id], o.observation_id),
    )
    metadata = _finding_contract_metadata()
    findings: list[ValidatorFinding] = []
    for observation in ordered:
        outcome = _dispatch_rule(observation)
        if outcome is None:
            continue
        observed_value, expected_invariant, message, evidence = outcome
        rule = rule_by_id[observation.rule_id]
        finding_id = sha256_bytes(
            _finding_identity_bytes(
                eval_run_id=snapshot.eval_run_id,
                artifact_id=snapshot.artifact_id,
                artifact_sha256=snapshot.artifact_sha256,
                case_id=snapshot.case_id,
                entity_id=observation.entity_id,
                observation_id=observation.observation_id,
                rule_id=observation.rule_id,
                bundle_hash=computed_hash,
                rule_params_hash=rule.rule_params_hash,
            )
        )
        payload: dict[str, Any] = {
            "contract": metadata,
            "finding_id": finding_id,
            "validator": observation.rule_id,
            "validator_bundle_version": bundle.bundle_version,
            "validator_bundle_hash": computed_hash,
            "rule_params_hash": rule.rule_params_hash,
            "severity": rule.severity,
            "run_id": snapshot.eval_run_id,
            "artifact_id": snapshot.artifact_id,
            "observed_value": observed_value,
            "expected_invariant": expected_invariant,
            "message": message,
            "evidence": evidence,
            "repairable": rule.repairable,
            "created_at": snapshot.created_at,
        }
        if snapshot.case_id is not None:
            payload["case_id"] = snapshot.case_id
        if observation.entity_id is not None:
            payload["entity_id"] = observation.entity_id
        findings.append(ValidatorFinding.model_validate(payload))

    return EvaluatedValidatorFindings(
        eval_run_id=snapshot.eval_run_id,
        artifact_id=snapshot.artifact_id,
        artifact_sha256=snapshot.artifact_sha256,
        validator_bundle_version=bundle.bundle_version,
        validator_bundle_hash=computed_hash,
        findings=tuple(findings),
    )


# --- Persistence ----------------------------------------------------------


def _validate_root(root: str | Path) -> Path:
    if not isinstance(root, (str, Path)):
        raise InvalidEvaluationRootError(
            "eval_root must be an explicit str or Path root", observed_type=type(root).__name__
        )
    if isinstance(root, str) and root == "":
        raise InvalidEvaluationRootError(
            "eval_root must not be an empty string; supply the root explicitly", supplied_root=""
        )
    path = Path(root)
    if not path.exists():
        raise InvalidEvaluationRootError(
            f"eval_root {str(root)!r} does not exist", supplied_root=str(root)
        )
    if not path.is_dir():
        raise InvalidEvaluationRootError(
            f"eval_root {str(root)!r} is not a directory", supplied_root=str(root)
        )
    return path.resolve()


def _canonical_finding_line(finding: ValidatorFinding) -> bytes:
    """Canonical single-record bytes, without the record separator."""
    return canonical_contract_bytes(finding.model_dump(mode="json", exclude_unset=True))


def _serialize_findings(findings: tuple[ValidatorFinding, ...]) -> bytes:
    if not findings:
        return b""
    return b"".join(_canonical_finding_line(f) + b"\n" for f in findings)


def _require_unique_finding_ids(
    findings: tuple[ValidatorFinding, ...], eval_run_id: str, reference: str | None
) -> None:
    seen: set[str] = set()
    for index, finding in enumerate(findings):
        if finding.finding_id in seen:
            raise DuplicateValidatorFindingError(
                f"duplicate finding_id {finding.finding_id!r}",
                eval_run_id=eval_run_id, artifact_reference=reference,
                finding_id=finding.finding_id,
                line_number=(index + 1) if reference else None,
            )
        seen.add(finding.finding_id)


def persist_validator_findings(
    findings: tuple[ValidatorFinding, ...],
    *,
    eval_root: str | Path,
    eval_run_id: str,
) -> PersistedValidatorFindings:
    """Persist validator findings as write-once, immutable JSONL."""
    resolved_root = _validate_root(eval_root)
    loaded = load_evaluation_run_manifest(eval_run_id, eval_root=resolved_root)
    run_id = loaded.manifest.eval_run_id
    for finding in findings:
        if finding.run_id != run_id:
            raise ValidatorFindingRunBindingError(
                "a finding's run_id does not match the run manifest",
                eval_run_id=run_id, finding_id=finding.finding_id,
            )
    _require_unique_finding_ids(findings, run_id, None)

    findings_dir = resolved_root / eval_run_id / _FINDINGS_DIR
    reference = f"{eval_run_id}/{_FINDINGS_DIR}/{_FINDINGS_FILENAME}"
    if findings_dir.exists() or findings_dir.is_symlink():
        raise ValidatorFindingsExistError(
            f"findings directory {eval_run_id}/{_FINDINGS_DIR} already exists",
            eval_run_id=eval_run_id, artifact_reference=f"{eval_run_id}/{_FINDINGS_DIR}",
        )
    try:
        findings_dir.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise ValidatorFindingsExistError(
            f"findings directory {eval_run_id}/{_FINDINGS_DIR} already exists",
            eval_run_id=eval_run_id, artifact_reference=f"{eval_run_id}/{_FINDINGS_DIR}",
        ) from exc
    except OSError as exc:
        raise ValidatorWriteError(
            f"failed to create findings directory for {eval_run_id!r}", eval_run_id=eval_run_id
        ) from exc

    data = _serialize_findings(findings)
    expected = sha256_bytes(data)
    dest = findings_dir / _FINDINGS_FILENAME
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise ValidatorFindingsExistError(
            f"findings artifact {reference!r} already exists; findings are write-once",
            eval_run_id=eval_run_id, artifact_reference=reference,
        ) from exc
    except OSError as exc:
        raise ValidatorWriteError(
            f"failed to create findings artifact {reference!r}",
            eval_run_id=eval_run_id, artifact_reference=reference,
        ) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ValidatorWriteError(
            f"failed to write findings artifact {reference!r}",
            eval_run_id=eval_run_id, artifact_reference=reference,
        ) from exc
    try:
        observed = sha256_bytes(dest.read_bytes())
    except OSError as exc:
        raise ValidatorWriteError(
            f"failed to re-read findings artifact {reference!r} for verification",
            eval_run_id=eval_run_id, artifact_reference=reference,
        ) from exc
    if observed != expected:
        raise ValidatorDestinationHashMismatchError(
            f"written findings artifact {reference!r} re-read to a different hash",
            eval_run_id=eval_run_id, artifact_reference=reference,
            expected_sha256=expected, observed_sha256=observed,
        )
    return PersistedValidatorFindings(
        eval_run_id=eval_run_id, artifact_reference=reference, sha256=expected, findings=findings
    )


# --- Loader ---------------------------------------------------------------


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise _DuplicateKeyControl(key)
        seen.add(key)
        result[key] = value
    return result


def _reject_non_finite_constant(name: str) -> Any:
    raise _NonFiniteControl(name)


def _first_non_finite(payload: Any) -> str | None:
    stack = [payload]
    while stack:
        value = stack.pop()
        if isinstance(value, float) and not math.isfinite(value):
            return "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
        elif isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return None


def _parse_findings_jsonl(
    text: str, *, eval_run_id: str, reference: str
) -> tuple[ValidatorFinding, ...]:
    """Strict JSONL parsing shared by the findings loader."""
    findings: list[ValidatorFinding] = []
    if text == "":
        return ()
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    for index, line in enumerate(lines):
        ln = index + 1
        if not line or not line.strip():
            raise ValidatorJsonError(
                f"findings artifact {reference!r} line {ln} is blank",
                eval_run_id=eval_run_id, artifact_reference=reference, line_number=ln,
            )
        try:
            payload = json.loads(
                line,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_non_finite_constant,
            )
        except json.JSONDecodeError as exc:
            raise ValidatorJsonError(
                f"findings artifact {reference!r} line {ln} is not valid JSON: {exc.msg}",
                eval_run_id=eval_run_id, artifact_reference=reference, line_number=ln,
            ) from exc
        except _DuplicateKeyControl as exc:
            raise ValidatorJsonError(
                f"findings artifact {reference!r} line {ln} has duplicate key {exc.key!r}",
                eval_run_id=eval_run_id, artifact_reference=reference,
                line_number=ln, duplicate_key=exc.key,
            ) from exc
        except _NonFiniteControl as exc:
            raise ValidatorJsonError(
                f"findings artifact {reference!r} line {ln} has non-JSON constant "
                f"{exc.constant_name}",
                eval_run_id=eval_run_id, artifact_reference=reference,
                line_number=ln, constant_name=exc.constant_name,
            ) from exc
        non_finite = _first_non_finite(payload)
        if non_finite is not None:
            raise ValidatorJsonError(
                f"findings artifact {reference!r} line {ln} has non-finite number "
                f"({non_finite})",
                eval_run_id=eval_run_id, artifact_reference=reference,
                line_number=ln, constant_name=non_finite,
            )
        if not isinstance(payload, dict):
            raise ValidatorTopLevelTypeError(
                f"findings artifact {reference!r} line {ln} is not a JSON object",
                eval_run_id=eval_run_id, artifact_reference=reference,
                observed_type=type(payload).__name__, line_number=ln,
            )
        try:
            finding = ValidatorFinding.model_validate(payload)
        except PydanticValidationError as exc:
            pairs = sorted(
                ("/".join(str(p) for p in e["loc"]), e["type"]) for e in exc.errors()
            )
            raise ValidatorModelValidationError(
                f"findings artifact {reference!r} line {ln} failed ValidatorFinding validation",
                eval_run_id=eval_run_id, artifact_reference=reference, line_number=ln,
                field_locations=tuple(loc for loc, _ in pairs),
                error_types=tuple(t for _, t in pairs),
            ) from exc
        if finding.run_id != eval_run_id:
            raise ValidatorFindingRunBindingError(
                f"findings artifact {reference!r} line {ln} records a different run_id",
                eval_run_id=eval_run_id, artifact_reference=reference,
                finding_id=finding.finding_id,
            )
        findings.append(finding)
    return tuple(findings)


def load_validator_findings(
    eval_run_id: str, *, eval_root: str | Path
) -> LoadedValidatorFindings:
    """Load immutable validator findings from the fixed run-directory path."""
    resolved_root = _validate_root(eval_root)
    load_evaluation_run_manifest(eval_run_id, eval_root=resolved_root)
    run_dir = resolved_root / eval_run_id
    findings_dir = run_dir / _FINDINGS_DIR
    reference = f"{eval_run_id}/{_FINDINGS_DIR}/{_FINDINGS_FILENAME}"
    dest = findings_dir / _FINDINGS_FILENAME
    if run_dir.is_symlink() or findings_dir.is_symlink() or dest.is_symlink():
        raise ValidatorArtifactNotAFileError(
            f"findings artifact {reference!r} or a parent is a symlink",
            eval_run_id=eval_run_id, artifact_reference=reference,
        )
    if not dest.exists():
        raise ValidatorArtifactMissingError(
            f"findings artifact {reference!r} does not exist",
            eval_run_id=eval_run_id, artifact_reference=reference,
        )
    if not dest.is_file():
        raise ValidatorArtifactNotAFileError(
            f"findings artifact {reference!r} is not a regular file",
            eval_run_id=eval_run_id, artifact_reference=reference,
        )
    try:
        raw = dest.read_bytes()
    except OSError as exc:
        raise ValidatorArtifactReadError(
            f"failed to read findings artifact {reference!r}",
            eval_run_id=eval_run_id, artifact_reference=reference,
        ) from exc
    observed = sha256_bytes(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidatorDecodeError(
            f"findings artifact {reference!r} is not valid UTF-8",
            eval_run_id=eval_run_id, artifact_reference=reference,
        ) from exc
    findings = _parse_findings_jsonl(text, eval_run_id=eval_run_id, reference=reference)
    _require_unique_finding_ids(findings, eval_run_id, reference)
    return LoadedValidatorFindings(
        eval_run_id=eval_run_id, artifact_reference=reference, sha256=observed, findings=findings
    )
