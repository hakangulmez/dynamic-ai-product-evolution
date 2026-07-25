"""Metric aggregation, axis-native evaluation, abstention, tier-contract, and
unsafe-exclusion audit metrics (Slice 9, SPEC-020 / ADR-013 / ADR-016 / ADR-017).

Slice 9 computes a deterministic ``MetricReport`` from a caller-supplied,
strict, frozen ``MetricInputSnapshot`` plus the immutable Slice 5–8 artifacts
(assertion outcomes, validator findings) and the Slice 4 scoring/gate
configuration. All input contracts are defined module-locally here; ``models.py``
is unchanged.

Locked decisions honored:
- Product/capability/task P/R come from explicit typed axis-evaluation records
  whose ``axis_role`` is product/capability/task — never from an assertion-kind
  × assertion-outcome confusion mapping (assertion outcomes are a separate
  diagnostic family).
- UNKNOWN / OTHER / NOT_APPLICABLE / NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION are
  four distinct governed values, never collapsed into each other or into an
  assertion outcome.
- ``verification_status`` is supplied per record; it is never inferred from
  dev/frozen_test, suite membership, or case-set lifecycle. Verified and
  provisional populations are reported separately; hard-gate eligibility is
  Slice 10 work.
- Validator denominators come from typed execution records, cross-checked
  against persisted findings; a finding is never used as a denominator.
- The deterministic tier engine is neither implemented nor imported; Slice 9
  only scores a caller-supplied tier-contract observation.
- Minimum-support and CI policy come only from the Slice 4 ``ScoringGateConfig``;
  nothing numeric is hardcoded. Slice 9 computes metric values and confidence
  intervals only; it applies no gate comparison, execution status, or verdict.

Immutability here means refuse-to-overwrite directories, exclusive-create files
and read-back hash verification — not OS-level immutability.
"""

from __future__ import annotations

import json
import math
import os
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, ClassVar, Literal, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError as PydanticValidationError,
    model_validator,
)

from .case_sets import case_set_snapshot_hash
from .cases import InvalidEvaluationRootError
from .contracts import canonical_contract_bytes, model_contract_hash
# Re-homed member models, vocabularies, and reserved values are imported here
# for backward-compatible re-export (``import X as X`` marks the intentional
# re-export so linters do not treat unused-internally names as dead imports).
from .metric_inputs import (
    AssertionMetricBinding as AssertionMetricBinding,
    AxisBaseMetricType as AxisBaseMetricType,
    AxisDefinition as AxisDefinition,
    AxisEvaluationRecord as AxisEvaluationRecord,
    AxisMetricType as AxisMetricType,
    AxisRole as AxisRole,
    EvidenceResolvability as EvidenceResolvability,
    MetricApplicabilityBinding as MetricApplicabilityBinding,
    MetricInputSnapshot as MetricInputSnapshot,
    MetricScope as MetricScope,
    NOT_APPLICABLE as NOT_APPLICABLE,
    NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION as NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION,
    OTHER as OTHER,
    UNKNOWN as UNKNOWN,
    ValidatorRuleEvaluationRecord as ValidatorRuleEvaluationRecord,
    metric_input_snapshot_hash as metric_input_snapshot_hash,
)
from .models import (
    AssertionOutcome,
    CaseMembership,
    CaseSetManifest,
    ContractMetadata,
    EvaluationRunManifest,
    EvaluationRunManifestV2,
    ValidatorFinding,
)
from .models import _reject_explicit_null
from .runs import load_evaluation_run_manifest_v2
from .scoring_config import LoadedScoringGateConfig, ScoringGateConfig
from .stage_profiles import (
    LoadedStageProfileRegistry,
    MetricFamily,
    StageProfileError,
    resolve_metric_applicability,
    stage_profile_registry_hash,
)
from .stage_evidence import (
    GoldVerificationStatus as GoldVerificationStatus,
    ScreenOperationalSummary as ScreenOperationalSummary,
    TierContractObservation as TierContractObservation,
    UnsafeAuditLabel as UnsafeAuditLabel,
    UnsafeAuditStratum as UnsafeAuditStratum,
    UnsafeExclusionAuditSnapshot as UnsafeExclusionAuditSnapshot,
)
from .validators import VALIDATOR_RULE_ORDER, ValidatorRuleId
from ..universe.io_utils import sha256_bytes

_METRICS_DIR = "metrics"
_METRICS_FILENAME = "metric_report.json"
_METRICS_V2_FILENAME = "metric_report.v2.json"
_REPORT_CONTRACT_ID = "metric_report"
_REPORT_CONTRACT_VERSION = "0.1.0"
_REPORT_V2_CONTRACT_VERSION = "0.2.0"

# The eleven governed metric families in canonical sorted order (derived from the
# closed ``MetricFamily`` literal so the ledger can never drift from the
# stage-profile universe).
_CANONICAL_METRIC_FAMILIES: tuple[str, ...] = tuple(sorted(get_args(MetricFamily)))
_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"
_UNSAFE_CI_METHOD = "wilson_one_sided_stratified"

# --- Governed vocabularies and constants ----------------------------------

# Governed metric-input vocabularies (GoldVerificationStatus, EvidenceResolvability,
# AxisRole, AxisBaseMetricType, AxisMetricType, MetricScope) and the reserved axis
# values (UNKNOWN, OTHER, NOT_APPLICABLE, NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION)
# are owned by ``metric_inputs``/``stage_evidence`` (Slice 12I re-homing) and
# imported above; ``metrics.py`` re-exports them for backward compatibility.
MetricComputationStatus = Literal["computed", "indeterminate"]
MetricConfigurationRole = Literal["gate_input", "diagnostic"]

# Governed metric-family identifiers (config metric_id must match one of these
# per (metric_id, population_slice_id) slice; the family selects the formula).
METRIC_AXIS_MULTI_LABEL = "axis_multi_label"
METRIC_AXIS_STRUCTURED_SET = "axis_structured_set"
METRIC_AXIS_NOMINAL = "axis_nominal_single_label"
METRIC_AXIS_ORDINAL = "axis_ordinal_single_label"
METRIC_AXIS_ABSTENTION = "axis_abstention"
METRIC_ASSERTION_OUTCOMES = "assertion_outcomes"
METRIC_VALIDATOR_RULES = "validator_rules"
METRIC_VALIDATOR_SUMMARIES = "validator_summaries"
METRIC_TIER_CONTRACT = "tier_contract"
METRIC_UNSAFE_EXCLUSION = "unsafe_exclusion"
METRIC_SCREEN_OPERATIONAL = "screen_operational"

_RESERVED_VALUES = frozenset(
    {UNKNOWN, OTHER, NOT_APPLICABLE, NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION}
)


class _Slice9StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _require_non_blank(value: str, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(
            f"{field_name} must be a non-empty string without leading or trailing whitespace"
        )
    return value


def _require_unique(values: tuple[str, ...], field_name: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicate values")


# --- Metric output models -------------------------------------------------


class MetricDimension(_Slice9StrictModel):
    key: str
    value: str

    @model_validator(mode="after")
    def _dimension_invariants(self) -> "MetricDimension":
        _require_non_blank(self.key, "key")
        _require_non_blank(self.value, "value")
        return self


class ConfidenceInterval(_Slice9StrictModel):
    method: str
    confidence_level: float
    lower: float
    upper: float

    @model_validator(mode="after")
    def _ci_invariants(self) -> "ConfidenceInterval":
        _require_non_blank(self.method, "method")
        for name in ("confidence_level", "lower", "upper"):
            value = getattr(self, name)
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        return self


class MetricSupport(_Slice9StrictModel):
    verified_support: int
    provisional_support: int
    total_support: int
    applicable_denominator: int
    minimum_verified_support: int

    @model_validator(mode="after")
    def _support_invariants(self) -> "MetricSupport":
        for name in (
            "verified_support", "provisional_support", "total_support",
            "applicable_denominator", "minimum_verified_support",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        return self


class MetricDatum(_Slice9StrictModel):
    metric_id: str
    population_slice_id: str
    configuration_role: MetricConfigurationRole
    status: MetricComputationStatus
    value: int | float | None = None
    numerator: int | float | None = None
    denominator: int | float | None = None
    support: MetricSupport
    dimensions: tuple[MetricDimension, ...]
    confidence_interval: ConfidenceInterval | None = None
    reason_code: str | None = None

    @model_validator(mode="after")
    def _datum_invariants(self) -> "MetricDatum":
        _require_non_blank(self.metric_id, "metric_id")
        _require_non_blank(self.population_slice_id, "population_slice_id")
        for name in ("value", "numerator", "denominator"):
            v = getattr(self, name)
            if isinstance(v, float) and not math.isfinite(v):
                raise ValueError(f"{name} must be finite")
        keys = tuple(d.key for d in self.dimensions)
        if list(keys) != sorted(keys):
            raise ValueError("dimensions must be sorted by key")
        _require_unique(keys, "dimension keys")
        if self.status == "indeterminate":
            if self.value is not None:
                raise ValueError("an indeterminate metric must have value None")
            if not self.reason_code or self.reason_code.strip() == "":
                raise ValueError("an indeterminate metric requires a non-blank reason_code")
        else:
            if self.value is None:
                raise ValueError("a computed metric requires a value")
        return self


class _ContractStamped(_Slice9StrictModel):
    """Local contract-stamped base (mirrors models.ContractStampedModel)."""

    _contract_id: ClassVar[str]
    _contract_version: ClassVar[str] = "0.1.0"

    contract: ContractMetadata

    @model_validator(mode="after")
    def _verify_contract_stamp(self) -> "_ContractStamped":
        expected_id = getattr(type(self), "_contract_id", None)
        if expected_id is None:
            raise ValueError("contract-stamped subclasses must define _contract_id")
        if self.contract.contract_id != expected_id:
            raise ValueError(f"contract.contract_id must be {expected_id!r}")
        if self.contract.contract_version != self._contract_version:
            raise ValueError(f"contract.contract_version must be {self._contract_version!r}")
        expected_hash = model_contract_hash(type(self), expected_id, self._contract_version)
        if self.contract.contract_hash != expected_hash:
            raise ValueError("contract.contract_hash does not match the canonical contract hash")
        return self


class MetricReport(_ContractStamped):
    """Persisted deterministic metric report (metric_report@0.1.0)."""

    _contract_id: ClassVar[str] = _REPORT_CONTRACT_ID

    eval_run_id: str
    case_set_version: str
    case_set_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    scoring_gate_config_version: str
    scoring_gate_config_hash: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    metric_input_snapshot_hash: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    metrics: tuple[MetricDatum, ...]

    @model_validator(mode="after")
    def _report_invariants(self) -> "MetricReport":
        seen: set[tuple[str, str, tuple[tuple[str, str], ...]]] = set()
        for datum in self.metrics:
            key = (
                datum.metric_id,
                datum.population_slice_id,
                tuple((d.key, d.value) for d in datum.dimensions),
            )
            if key in seen:
                raise ValueError("duplicate metric identity (metric_id, slice, dimensions)")
            seen.add(key)
        return self


class PersistedMetricReport(_Slice9StrictModel):
    eval_run_id: str
    artifact_reference: str
    sha256: str
    # The public persistence wrapper represents either report version; its v0.1
    # behavior and bytes are unchanged.
    report: "MetricReport | MetricReportV2"


class LoadedMetricReport(_Slice9StrictModel):
    eval_run_id: str
    artifact_reference: str
    sha256: str
    report: MetricReport


# --- Metric report v0.2 (applicability ledger) ----------------------------


class MetricFamilyApplicabilityEntry(_Slice9StrictModel):
    """One governed metric family's applicability state in the v0.2 ledger."""

    metric_family: MetricFamily
    applicability_state: Literal["applicable", "inapplicable"]
    reason_code: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_explicit_null_reason(cls, data: Any) -> Any:
        return _reject_explicit_null(data, ("reason_code",), "MetricFamilyApplicabilityEntry")

    @model_validator(mode="after")
    def _entry_invariants(self) -> "MetricFamilyApplicabilityEntry":
        if self.applicability_state == "inapplicable":
            if self.reason_code is None:
                raise ValueError("an inapplicable family requires a reason_code")
            _require_non_blank(self.reason_code, "reason_code")
        else:
            if self.reason_code is not None:
                raise ValueError("an applicable family must omit reason_code")
        return self


class MetricReportV2(_ContractStamped):
    # Docstring intentionally omitted so the generated JSON Schema (and thus the
    # governed model-contract hash) carries no description.
    _contract_id: ClassVar[str] = _REPORT_CONTRACT_ID
    _contract_version: ClassVar[str] = _REPORT_V2_CONTRACT_VERSION

    eval_run_id: str
    case_set_version: str
    case_set_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    scoring_gate_config_version: str
    scoring_gate_config_hash: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    metric_input_snapshot_hash: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    evaluation_stage: str
    stage_profile_registry_version: str
    stage_profile_registry_hash: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    selected_stage_profile_entry_hash: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    applicability_ledger: tuple[MetricFamilyApplicabilityEntry, ...]
    metrics: tuple[MetricDatum, ...]

    @model_validator(mode="after")
    def _report_v2_invariants(self) -> "MetricReportV2":
        _require_non_blank(self.eval_run_id, "eval_run_id")
        _require_non_blank(self.evaluation_stage, "evaluation_stage")
        _require_non_blank(self.stage_profile_registry_version, "stage_profile_registry_version")
        families = tuple(e.metric_family for e in self.applicability_ledger)
        if families != _CANONICAL_METRIC_FAMILIES:
            raise ValueError(
                "applicability_ledger must list exactly the eleven governed families "
                "in canonical sorted order"
            )
        applicable = {
            e.metric_family for e in self.applicability_ledger
            if e.applicability_state == "applicable"
        }
        seen: set[tuple[str, str, tuple[tuple[str, str], ...]]] = set()
        for datum in self.metrics:
            if datum.metric_id not in applicable:
                raise ValueError(
                    "every MetricDatum must belong to an applicable metric family"
                )
            key = (
                datum.metric_id,
                datum.population_slice_id,
                tuple((d.key, d.value) for d in datum.dimensions),
            )
            if key in seen:
                raise ValueError("duplicate metric identity (metric_id, slice, dimensions)")
            seen.add(key)
        return self


class _LoadedMetricReportV2(_Slice9StrictModel):
    eval_run_id: str
    artifact_reference: str
    sha256: str
    report: MetricReportV2


# ``PersistedMetricReport`` forward-references ``MetricReportV2`` (defined above);
# resolve that reference now that the class exists. The public wrapper carries
# either report version.
PersistedMetricReport.model_rebuild()


# --- Exceptions -----------------------------------------------------------


class MetricError(Exception):
    """Base class for Slice 9 metric failures; never raised directly."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
        metric_id: str | None = None,
        population_slice_id: str | None = None,
        case_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.eval_run_id = eval_run_id
        self.artifact_reference = artifact_reference
        self.metric_id = metric_id
        self.population_slice_id = population_slice_id
        self.case_id = case_id


class SnapshotBindingError(MetricError):
    """Snapshot run/case-set/config identity does not match its inputs."""

    def __init__(self, message: str, *, binding_kind: str | None = None, **kw: Any) -> None:
        super().__init__(message, **kw)
        self.binding_kind = binding_kind


class AssertionBindingMismatchError(MetricError):
    """Assertion bindings do not match the supplied assertion outcomes."""


class ValidatorExecutionMismatchError(MetricError):
    """Validator execution records do not reconcile with persisted findings."""


class MetricPolicyError(MetricError):
    """A metric-policy definition is missing, duplicated, or malformed."""

    def __init__(self, message: str, *, policy_kind: str | None = None, **kw: Any) -> None:
        super().__init__(message, **kw)
        self.policy_kind = policy_kind


class UnsafeAuditPolicyError(MetricError):
    """The unsafe-exclusion CI policy is missing or malformed."""


class MetricReportExistsError(MetricError):
    """The metrics output directory already exists in some form."""


class MetricArtifactMissingError(MetricError):
    """A required metrics artifact does not exist."""


class MetricArtifactNotAFileError(MetricError):
    """A metrics artifact or a parent is not a regular file/directory."""


class MetricArtifactReadError(MetricError):
    """Reading a metrics artifact failed."""


class MetricDecodeError(MetricError):
    """A metrics artifact's bytes are not valid UTF-8."""


class MetricJsonError(MetricError):
    """A metrics artifact is not acceptable strict JSON."""

    def __init__(
        self, message: str, *, duplicate_key: str | None = None,
        constant_name: str | None = None, **kw: Any,
    ) -> None:
        super().__init__(message, **kw)
        self.duplicate_key = duplicate_key
        self.constant_name = constant_name


class MetricTopLevelTypeError(MetricError):
    """A parsed metric report is not a JSON object."""

    def __init__(self, message: str, *, observed_type: str | None = None, **kw: Any) -> None:
        super().__init__(message, **kw)
        self.observed_type = observed_type


class MetricModelValidationError(MetricError):
    """A metric report failed MetricReport model/contract validation."""

    def __init__(
        self, message: str, *, field_locations: tuple[str, ...] = (),
        error_types: tuple[str, ...] = (), **kw: Any,
    ) -> None:
        super().__init__(message, **kw)
        self.field_locations = field_locations
        self.error_types = error_types


class MetricReportBindingError(MetricError):
    """A loaded report's run/case-set/config identity does not match."""


class OutcomeRunBindingError(MetricError):
    """An assertion outcome's eval_run_id does not match the run manifest."""


class FindingRunBindingError(MetricError):
    """A validator finding's run_id does not match the run manifest."""


class CaseMembershipBindingError(MetricError):
    """A record/binding case is absent from, or disagrees with, the case set."""

    def __init__(self, message: str, *, binding_kind: str | None = None,
                 case_id: str | None = None, **kw: Any) -> None:
        super().__init__(message, case_id=case_id, **kw)
        self.binding_kind = binding_kind


class MetricWriteError(MetricError):
    """Writing a metrics artifact failed."""


class MetricDestinationHashMismatchError(MetricError):
    """A written metrics artifact re-read to a different hash."""

    def __init__(
        self, message: str, *, expected_sha256: str | None = None,
        observed_sha256: str | None = None, **kw: Any,
    ) -> None:
        super().__init__(message, **kw)
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


# --- Configuration policy resolution --------------------------------------


def _require_int(value: Any, *, minimum: int, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MetricPolicyError(f"{what} must be an integer", policy_kind="invalid_support")
    if value < minimum:
        raise MetricPolicyError(f"{what} must be >= {minimum}", policy_kind="invalid_support")
    return value


def _resolve_slice_policy(
    config: ScoringGateConfig, metric_id: str, slice_id: str
) -> tuple[MetricConfigurationRole, int]:
    gates = [g for g in config.gates if g.metric_id == metric_id and g.population_slice_id == slice_id]
    diags = [
        d for d in config.diagnostics
        if d.metric_id == metric_id and d.population_slice_id == slice_id
    ]
    if len(gates) > 1 or len(diags) > 1 or (gates and diags):
        raise MetricPolicyError(
            f"duplicate metric policy for ({metric_id!r}, {slice_id!r})",
            policy_kind="duplicate", metric_id=metric_id, population_slice_id=slice_id,
        )
    if gates:
        minimum = _require_int(
            gates[0].verified_support_requirement.get("minimum_verified_support"),
            minimum=0, what="minimum_verified_support",
        )
        return "gate_input", minimum
    if diags:
        entries = [s for s in diags[0].slice_definitions if "minimum_verified_support" in s]
        if len(entries) != 1:
            raise MetricPolicyError(
                "a diagnostic definition must carry minimum_verified_support in exactly one "
                "slice_definitions entry",
                policy_kind="malformed", metric_id=metric_id, population_slice_id=slice_id,
            )
        minimum = _require_int(
            entries[0]["minimum_verified_support"], minimum=0, what="minimum_verified_support"
        )
        return "diagnostic", minimum
    raise MetricPolicyError(
        f"no metric policy declared for ({metric_id!r}, {slice_id!r})",
        policy_kind="missing", metric_id=metric_id, population_slice_id=slice_id,
    )


def _resolve_unsafe_policy(
    config: ScoringGateConfig, slice_id: str
) -> tuple[int, float]:
    gates = [
        g for g in config.gates
        if g.metric_id == METRIC_UNSAFE_EXCLUSION and g.population_slice_id == slice_id
    ]
    if not gates:
        raise UnsafeAuditPolicyError(
            f"no unsafe-exclusion gate policy for slice {slice_id!r}",
            metric_id=METRIC_UNSAFE_EXCLUSION, population_slice_id=slice_id,
        )
    if len(gates) > 1:
        raise UnsafeAuditPolicyError(
            f"duplicate unsafe-exclusion gate policy for slice {slice_id!r}",
            metric_id=METRIC_UNSAFE_EXCLUSION, population_slice_id=slice_id,
        )
    gate = gates[0]
    minimum = _require_int(
        gate.verified_support_requirement.get("minimum_audited_per_stratum"),
        minimum=1, what="minimum_audited_per_stratum",
    )
    if gate.ci_method_reference != _UNSAFE_CI_METHOD:
        raise UnsafeAuditPolicyError(
            f"unsafe-exclusion ci_method_reference must be {_UNSAFE_CI_METHOD!r}"
        )
    level = gate.threshold.get("confidence_level")
    if isinstance(level, bool) or not isinstance(level, (int, float)):
        raise UnsafeAuditPolicyError("confidence_level must be a finite float")
    level = float(level)
    if not math.isfinite(level) or not (0.5 < level < 1.0):
        raise UnsafeAuditPolicyError("confidence_level must be strictly between 0.5 and 1.0")
    return minimum, level


# --- Formula helpers ------------------------------------------------------


def _ratio(num: float, den: float) -> tuple[MetricComputationStatus, float | None, str | None]:
    if den == 0:
        return "indeterminate", None, "zero_denominator"
    return "computed", num / den, None


def _prf(tp: int, fp: int, fn: int) -> tuple[
    tuple[MetricComputationStatus, float | None, str | None], ...
]:
    return (_ratio(tp, tp + fp), _ratio(tp, tp + fn), _f1(tp, fp, fn))


def _f1(tp: int, fp: int, fn: int) -> tuple[MetricComputationStatus, float | None, str | None]:
    denom = 2 * tp + fp + fn
    if denom == 0:
        return "indeterminate", None, "zero_denominator"
    return "computed", (2 * tp) / denom, None


def _dims(**kw: str) -> tuple[MetricDimension, ...]:
    return tuple(
        MetricDimension(key=k, value=v) for k, v in sorted(kw.items())
    )


def _wilson_upper(missed: int, n: int, z: float) -> float:
    """One-sided Wilson score upper confidence bound for a binomial proportion."""
    p = missed / n
    z2 = z * z
    center = p + z2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return (center + margin) / (1 + z2 / n)


# --- Support helper -------------------------------------------------------


def _support(
    verified: int, provisional: int, applicable_denominator: int, minimum: int
) -> MetricSupport:
    return MetricSupport(
        verified_support=verified,
        provisional_support=provisional,
        total_support=verified + provisional,
        applicable_denominator=applicable_denominator,
        minimum_verified_support=minimum,
    )


def _gated(
    relevant_support: int, minimum: int,
    ratio: tuple[MetricComputationStatus, float | None, str | None],
) -> tuple[MetricComputationStatus, float | None, str | None]:
    if relevant_support < minimum:
        return "indeterminate", None, "insufficient_evaluation_evidence"
    return ratio


# --- Metric computation ---------------------------------------------------


def _answered(record: AxisEvaluationRecord) -> bool:
    return not record.is_unknown and not record.is_screen_excluded


def _pred_elements(record: AxisEvaluationRecord) -> set[str]:
    """Predicted elements; a terminal (UNKNOWN / screen-exclusion) has none."""
    return set(record.predicted_values) if _answered(record) else set()


def _average(values: list[float | None]) -> tuple[MetricComputationStatus, float | None, str | None]:
    if not values or any(v is None for v in values):
        return "indeterminate", None, "zero_denominator"
    finite = [v for v in values if v is not None]
    return "computed", sum(finite) / len(finite), None


def _push(out: list[MetricDatum], metric_id: str, slice_id: str, role: MetricConfigurationRole,
          dims: tuple[MetricDimension, ...], ratio: tuple[MetricComputationStatus, float | None,
          str | None], support: MetricSupport, *, relevant: int, minimum: int,
          numerator: int | float | None = None, denominator: int | float | None = None) -> None:
    st, val, reason = _gated(relevant, minimum, ratio)
    out.append(MetricDatum(
        metric_id=metric_id, population_slice_id=slice_id, configuration_role=role,
        status=st, value=val, numerator=numerator, denominator=denominator, support=support,
        dimensions=dims, reason_code=reason,
    ))


def _push_count(out: list[MetricDatum], metric_id: str, slice_id: str,
                role: MetricConfigurationRole, dims: tuple[MetricDimension, ...],
                count: int, support: MetricSupport) -> None:
    out.append(MetricDatum(
        metric_id=metric_id, population_slice_id=slice_id, configuration_role=role,
        status="computed", value=count, numerator=count, denominator=None, support=support,
        dimensions=dims, reason_code=None,
    ))


def _ml_confusion(
    records: tuple[AxisEvaluationRecord, ...], labels: tuple[str, ...]
) -> dict[str, tuple[int, int, int]]:
    """Per-label (tp, fp, fn); terminals contribute FN via their empty prediction set."""
    conf = {label: [0, 0, 0] for label in labels}
    for record in records:
        gold = set(record.gold_values)
        pred = _pred_elements(record)
        for label in labels:
            in_pred, in_gold = label in pred, label in gold
            if in_pred and in_gold:
                conf[label][0] += 1
            elif in_pred and not in_gold:
                conf[label][1] += 1
            elif not in_pred and in_gold:
                conf[label][2] += 1
    return {k: (v[0], v[1], v[2]) for k, v in conf.items()}


def _axis_scope_partition(
    records: tuple[AxisEvaluationRecord, ...], view: str, scope: str
) -> tuple[tuple[AxisEvaluationRecord, ...], tuple[AxisEvaluationRecord, ...], int]:
    """Return (eval_records, resolvable, support_denom) for one view+scope.

    Conditional uses only answered resolvable records; end-to-end uses every
    resolvable record so UNKNOWN and screen-exclusion never leave the denominator.
    """
    pop = tuple(r for r in records if r.verification_status == view and r.metric_scope == scope)
    resolvable = tuple(r for r in pop if r.evidence_resolvability == "resolvable")
    answered_resolvable = tuple(r for r in resolvable if _answered(r))
    eval_records = answered_resolvable if scope == "conditional" else resolvable
    return eval_records, resolvable, len(eval_records)


def _compute_axis_metrics(
    axis: AxisDefinition, records: tuple[AxisEvaluationRecord, ...],
    config: ScoringGateConfig, out: list[MetricDatum]
) -> None:
    effective = axis.effective_metric_type
    metric_id = {
        "multi_label": METRIC_AXIS_MULTI_LABEL,
        "structured_set": METRIC_AXIS_STRUCTURED_SET,
        "nominal_single_label": METRIC_AXIS_NOMINAL,
        "ordinal_single_label": METRIC_AXIS_ORDINAL,
    }[effective]
    role, minimum = _resolve_slice_policy(config, metric_id, axis.axis_id)
    emitter = {
        "multi_label": _emit_multi_label,
        "structured_set": _emit_structured_set,
        "nominal_single_label": _emit_nominal,
        "ordinal_single_label": _emit_ordinal,
    }[effective]
    for view in ("verified", "provisional"):
        datum_role: MetricConfigurationRole = role if view == "verified" else "diagnostic"
        for scope in ("conditional", "end_to_end"):
            eval_records, _resolvable, denom = _axis_scope_partition(records, view, scope)
            verified_n = denom if view == "verified" else 0
            prov_n = denom if view == "provisional" else 0
            support = _support(verified_n, prov_n, denom, minimum)
            base_dims = {"axis_role": axis.axis_role, "scope": scope, "verification": view}
            emitter(axis, eval_records, metric_id, datum_role, minimum, support, denom,
                    base_dims, out)


def _emit_multi_label(
    axis: AxisDefinition, eval_records: tuple[AxisEvaluationRecord, ...], metric_id: str,
    role: MetricConfigurationRole, minimum: int, support: MetricSupport, relevant: int,
    base_dims: dict[str, str], out: list[MetricDatum]
) -> None:
    conf = _ml_confusion(eval_records, axis.labels)
    micro_tp = sum(c[0] for c in conf.values())
    micro_fp = sum(c[1] for c in conf.values())
    micro_fn = sum(c[2] for c in conf.values())
    for label in axis.labels:
        tp, fp, fn = conf[label]
        for measure, r in zip(("precision", "recall", "f1"), _prf(tp, fp, fn)):
            _push(out, metric_id, axis.axis_id, role,
                  _dims(aggregation="per_label", label=label, measure=measure, **base_dims),
                  r, support, relevant=relevant, minimum=minimum)
    for measure, r in zip(("precision", "recall", "f1"), _prf(micro_tp, micro_fp, micro_fn)):
        _push(out, metric_id, axis.axis_id, role,
              _dims(aggregation="micro", measure=measure, **base_dims),
              r, support, relevant=relevant, minimum=minimum)
    for measure, r in _macro_prf(conf, axis.labels).items():
        _push(out, metric_id, axis.axis_id, role,
              _dims(aggregation="macro", measure=measure, **base_dims),
              r, support, relevant=relevant, minimum=minimum)
    exact = sum(1 for r in eval_records if _pred_elements(r) == set(r.gold_values))
    _push(out, metric_id, axis.axis_id, "diagnostic",
          _dims(aggregation="exact_set", measure="agreement", **base_dims),
          _ratio(exact, relevant), support, relevant=relevant, minimum=minimum,
          numerator=exact, denominator=relevant)


def _emit_structured_set(
    axis: AxisDefinition, eval_records: tuple[AxisEvaluationRecord, ...], metric_id: str,
    role: MetricConfigurationRole, minimum: int, support: MetricSupport, relevant: int,
    base_dims: dict[str, str], out: list[MetricDatum]
) -> None:
    # Element-level micro over all elements.
    tp = fp = fn = 0
    per_p: list[float | None] = []
    per_r: list[float | None] = []
    per_f: list[float | None] = []
    for record in eval_records:
        gold = set(record.gold_values)
        pred = _pred_elements(record)
        inter = len(pred & gold)
        tp += inter
        fp += len(pred - gold)
        fn += len(gold - pred)
        per_p.append(inter / len(pred) if pred else None)
        per_r.append(inter / len(gold) if gold else None)
        per_f.append((2 * inter) / (len(pred) + len(gold)) if (len(pred) + len(gold)) else None)
    for measure, r in zip(("precision", "recall", "f1"), _prf(tp, fp, fn)):
        _push(out, metric_id, axis.axis_id, role,
              _dims(aggregation="element_micro", measure=measure, **base_dims),
              r, support, relevant=relevant, minimum=minimum)
    for measure, values in (("precision", per_p), ("recall", per_r), ("f1", per_f)):
        _push(out, metric_id, axis.axis_id, role,
              _dims(aggregation="set_average", measure=measure, **base_dims),
              _average(values), support, relevant=relevant, minimum=minimum)
    exact = sum(1 for record in eval_records if _pred_elements(record) == set(record.gold_values))
    _push(out, metric_id, axis.axis_id, "diagnostic",
          _dims(aggregation="exact_set", measure="agreement", **base_dims),
          _ratio(exact, relevant), support, relevant=relevant, minimum=minimum,
          numerator=exact, denominator=relevant)


def _macro_prf(
    conf: dict[str, tuple[int, int, int]], labels: tuple[str, ...]
) -> dict[str, tuple[MetricComputationStatus, float | None, str | None]]:
    result: dict[str, tuple[MetricComputationStatus, float | None, str | None]] = {}
    for idx, measure in enumerate(("precision", "recall", "f1")):
        vals: list[float] = []
        undefined = False
        for label in labels:
            r = _prf(*conf[label])[idx]
            if r[0] == "computed":
                vals.append(r[1])  # type: ignore[arg-type]
            else:
                undefined = True
        if undefined or not vals:
            result[measure] = ("indeterminate", None, "zero_denominator")
        else:
            result[measure] = ("computed", sum(vals) / len(vals), None)
    return result


def _emit_nominal(
    axis: AxisDefinition, eval_records: tuple[AxisEvaluationRecord, ...], metric_id: str,
    role: MetricConfigurationRole, minimum: int, support: MetricSupport, relevant: int,
    base_dims: dict[str, str], out: list[MetricDatum]
) -> None:
    labels = axis.labels
    conf: Counter[tuple[str, str]] = Counter()
    for r in eval_records:
        # A terminal prediction lands in its terminal column (end-to-end only).
        conf[(r.gold_values[0], r.predicted_values[0])] += 1
    # Prediction columns: declared labels, plus observed terminal columns in a
    # deterministic order (UNKNOWN then screen-exclusion).
    observed = {p for (_g, p) in conf}
    terminal_cols = tuple(
        t for t in (UNKNOWN, NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION) if t in observed
    )
    columns = tuple(labels) + terminal_cols
    for gold in labels:
        for predicted in columns:
            _push_count(out, metric_id, axis.axis_id, role,
                        _dims(aggregation="confusion_matrix", gold=gold, predicted=predicted,
                              **base_dims),
                        conf[(gold, predicted)], support)
    per_class: dict[str, tuple[int, int, int]] = {}
    for label in labels:
        tp = conf[(label, label)]
        # A terminal prediction is never a declared class, so it adds only to
        # the FN of its gold class, never to any class's TP/FP.
        fp = sum(conf[(g, label)] for g in labels if g != label)
        fn = sum(conf[(label, p)] for p in columns if p != label)
        per_class[label] = (tp, fp, fn)
        for measure, rr in zip(("precision", "recall", "f1"), _prf(tp, fp, fn)):
            _push(out, metric_id, axis.axis_id, role,
                  _dims(aggregation="per_class", label=label, measure=measure, **base_dims),
                  rr, support, relevant=relevant, minimum=minimum)
    _push(out, metric_id, axis.axis_id, role,
          _dims(aggregation="macro", measure="f1", **base_dims),
          _macro_prf(per_class, labels)["f1"], support, relevant=relevant, minimum=minimum)
    correct = sum(conf[(label, label)] for label in labels)
    _push(out, metric_id, axis.axis_id, role,
          _dims(aggregation="overall", measure="exact_accuracy", **base_dims),
          _ratio(correct, relevant), support, relevant=relevant, minimum=minimum,
          numerator=correct, denominator=relevant)
    recalls = [tp / (tp + fn) for label in labels for (tp, _fp, fn) in (per_class[label],)
               if tp + fn > 0]
    bal = ("computed", sum(recalls) / len(recalls), None) if recalls \
        else ("indeterminate", None, "zero_denominator")
    _push(out, metric_id, axis.axis_id, role,
          _dims(aggregation="overall", measure="balanced_accuracy", **base_dims),
          bal, support, relevant=relevant, minimum=minimum)


def _emit_ordinal(
    axis: AxisDefinition, eval_records: tuple[AxisEvaluationRecord, ...], metric_id: str,
    role: MetricConfigurationRole, minimum: int, support: MetricSupport, relevant: int,
    base_dims: dict[str, str], out: list[MetricDatum]
) -> None:
    order = axis.ordinal_order
    rank = {label: i for i, label in enumerate(order)}
    k = len(order)
    exact = sum(1 for r in eval_records if r.predicted_values[0] == r.gold_values[0])
    _push(out, metric_id, axis.axis_id, role,
          _dims(aggregation="overall", measure="exact_agreement", **base_dims),
          _ratio(exact, relevant), support, relevant=relevant, minimum=minimum,
          numerator=exact, denominator=relevant)
    # Ordinal distance and kappa need an ordinal position; a terminal outcome has
    # none, so an end-to-end population containing one is a nonordinal outcome.
    terminal_present = any(not _answered(r) for r in eval_records)
    if terminal_present:
        nonordinal: tuple[MetricComputationStatus, float | None, str | None] = (
            "indeterminate", None, "nonordinal_terminal_outcome"
        )
        _push(out, metric_id, axis.axis_id, role,
              _dims(aggregation="overall", measure="mean_absolute_ordinal_distance", **base_dims),
              nonordinal, support, relevant=relevant, minimum=minimum)
        _push(out, metric_id, axis.axis_id, role,
              _dims(aggregation="overall", measure="weighted_kappa", **base_dims),
              nonordinal, support, relevant=relevant, minimum=minimum)
        return
    if eval_records:
        mae = sum(abs(rank[r.predicted_values[0]] - rank[r.gold_values[0]])
                  for r in eval_records) / len(eval_records)
        mae_r: tuple[MetricComputationStatus, float | None, str | None] = ("computed", mae, None)
    else:
        mae_r = ("indeterminate", None, "zero_denominator")
    _push(out, metric_id, axis.axis_id, role,
          _dims(aggregation="overall", measure="mean_absolute_ordinal_distance", **base_dims),
          mae_r, support, relevant=relevant, minimum=minimum)
    _push(out, metric_id, axis.axis_id, role,
          _dims(aggregation="overall", measure="weighted_kappa", **base_dims),
          _weighted_kappa(eval_records, order, rank, k, axis.ordinal_weighting),
          support, relevant=relevant, minimum=minimum)


def _weighted_kappa(
    records: tuple[AxisEvaluationRecord, ...], order: tuple[str, ...], rank: dict[str, int],
    k: int, weighting: str | None
) -> tuple[MetricComputationStatus, float | None, str | None]:
    n = len(records)
    if n == 0 or k <= 1:
        return "indeterminate", None, "zero_denominator"

    def w(i: int, j: int) -> float:
        d = abs(i - j) / (k - 1)
        return d * d if weighting == "quadratic" else d

    gold_counts = Counter(rank[r.gold_values[0]] for r in records)
    pred_counts = Counter(rank[r.predicted_values[0]] for r in records)
    obs = Counter((rank[r.gold_values[0]], rank[r.predicted_values[0]]) for r in records)
    observed_dis = sum(w(i, j) * c for (i, j), c in obs.items()) / n
    expected_dis = sum(
        w(i, j) * (gold_counts[i] / n) * (pred_counts[j] / n)
        for i in range(k) for j in range(k)
    )
    if expected_dis == 0:
        if observed_dis == 0:
            return "computed", 1.0, None
        return "indeterminate", None, "zero_expected_disagreement"
    return "computed", 1 - observed_dis / expected_dis, None


def _compute_abstention_metrics(
    axis: AxisDefinition, records: tuple[AxisEvaluationRecord, ...],
    config: ScoringGateConfig, out: list[MetricDatum]
) -> None:
    role, minimum = _resolve_slice_policy(config, METRIC_AXIS_ABSTENTION, axis.axis_id)
    for view in ("verified", "provisional"):
        pop = tuple(r for r in records if r.verification_status == view)
        for scope in ("conditional", "end_to_end"):
            scoped = tuple(r for r in pop if r.metric_scope == scope)
            datum_role: MetricConfigurationRole = role if view == "verified" else "diagnostic"
            resolvable = tuple(r for r in scoped if r.evidence_resolvability == "resolvable")
            insufficient = tuple(
                r for r in scoped if r.evidence_resolvability == "insufficient_evidence"
            )
            eligible = scoped
            answered_eligible = tuple(r for r in eligible if _answered(r))
            answered_resolvable = tuple(r for r in resolvable if _answered(r))
            incorrect_answered = tuple(
                r for r in answered_resolvable if set(r.predicted_values) != set(r.gold_values)
            )
            # screen-excluded with resolvable gold count as incorrect terminal in end_to_end.
            screen_excl_incorrect = tuple(
                r for r in resolvable if r.is_screen_excluded
            ) if scope == "end_to_end" else ()
            unknown_resolvable = tuple(r for r in resolvable if r.is_unknown)
            unknown_insufficient = tuple(r for r in insufficient if r.is_unknown)
            support = _support(len(eligible), 0, len(eligible), minimum) if view == "verified" \
                else _support(0, len(eligible), len(eligible), minimum)
            base_dims = {"axis_role": axis.axis_role, "scope": scope, "verification": view}

            def add(measure: str, num: int, den: int, gate_support: int) -> None:
                st, val, reason = _gated(gate_support, minimum, _ratio(num, den))
                out.append(MetricDatum(
                    metric_id=METRIC_AXIS_ABSTENTION, population_slice_id=axis.axis_id,
                    configuration_role=datum_role, status=st, value=val, numerator=num,
                    denominator=den, support=support,
                    dimensions=_dims(measure=measure, **base_dims), reason_code=reason,
                ))

            add("coverage", len(answered_eligible), len(eligible), len(eligible))
            incorrect_selective = len(incorrect_answered)
            add("selective_risk", incorrect_selective, len(answered_resolvable),
                len(answered_resolvable))
            add("false_confidence", len(incorrect_answered) + len(screen_excl_incorrect),
                len(resolvable), len(resolvable))
            add("unnecessary_abstention", len(unknown_resolvable), len(resolvable),
                len(resolvable))
            add("correct_abstention", len(unknown_insufficient), len(insufficient),
                len(insufficient))


def _compute_assertion_diagnostics(
    snapshot: MetricInputSnapshot, outcomes: tuple[AssertionOutcome, ...],
    config: ScoringGateConfig, out: list[MetricDatum]
) -> None:
    bindings = {(b.case_id, b.assertion_id): b for b in snapshot.assertion_bindings}
    outcome_ids = {(o.case_id, o.assertion_id) for o in outcomes}
    if len(outcome_ids) != len(outcomes):
        raise AssertionBindingMismatchError("duplicate assertion outcome identity")
    if set(bindings) != outcome_ids:
        raise AssertionBindingMismatchError(
            "assertion bindings must correspond one-to-one to assertion outcomes"
        )
    role, minimum = _resolve_slice_policy(config, METRIC_ASSERTION_OUTCOMES, "overall")
    total = len(outcomes)
    by_outcome: Counter[str] = Counter(o.outcome for o in outcomes)
    # Deterministic, fully-observed denominator: verified_support = observed total.
    support = _support(total, 0, total, minimum)
    for value in ("satisfied", "unsatisfied", "indeterminate", "not_applicable", "not_evaluated"):
        num = by_outcome.get(value, 0)
        _push(out, METRIC_ASSERTION_OUTCOMES, "overall", role,
              _dims(grouping="outcome", outcome=value), _ratio(num, total), support,
              relevant=total, minimum=minimum, numerator=num, denominator=total)
    # Grouped counts by kind / partition / suite (count-only diagnostics).
    kind_of = {(b.case_id, b.assertion_id): b.assertion_kind for b in snapshot.assertion_bindings}
    part_of = {(b.case_id, b.assertion_id): b.partition for b in snapshot.assertion_bindings}
    by_kind: Counter[tuple[str, str]] = Counter()
    by_part: Counter[tuple[str, str]] = Counter()
    by_suite: Counter[tuple[str, str]] = Counter()
    suites_of = {(b.case_id, b.assertion_id): b.suites for b in snapshot.assertion_bindings}
    for o in outcomes:
        key = (o.case_id, o.assertion_id)
        by_kind[(kind_of[key], o.outcome)] += 1
        by_part[(part_of[key], o.outcome)] += 1
        for suite in suites_of[key]:
            by_suite[(suite, o.outcome)] += 1
    for grouping, counter in (("kind", by_kind), ("partition", by_part), ("suite", by_suite)):
        for (group_value, outcome_value), num in sorted(counter.items()):
            out.append(MetricDatum(
                metric_id=METRIC_ASSERTION_OUTCOMES, population_slice_id="overall",
                configuration_role=role, status="computed", value=num, numerator=num,
                denominator=None, support=support,
                dimensions=_dims(grouping=grouping, group=group_value, outcome=outcome_value),
                reason_code=None,
            ))


def _compute_validator_metrics(
    snapshot: MetricInputSnapshot, findings: tuple[ValidatorFinding, ...],
    config: ScoringGateConfig, out: list[MetricDatum]
) -> None:
    executions = snapshot.validator_rule_evaluations
    # Cross-check: failed counts equal matching finding counts; every finding has a record.
    finding_counts: Counter[tuple[str, str]] = Counter(
        (f.artifact_id, f.validator) for f in findings
    )
    exec_index = {(e.artifact_id, e.rule_id): e for e in executions}
    for key, count in finding_counts.items():
        if key not in exec_index:
            raise ValidatorExecutionMismatchError(
                f"finding for artifact/rule {key!r} has no execution record"
            )
        if exec_index[key].failed_observation_count != count:
            raise ValidatorExecutionMismatchError(
                f"failed count for {key!r} does not match persisted findings"
            )
    for e in executions:
        expected = finding_counts.get((e.artifact_id, e.rule_id), 0)
        if e.failed_observation_count != expected:
            raise ValidatorExecutionMismatchError(
                f"execution record {(e.artifact_id, e.rule_id)!r} claims {e.failed_observation_count} "
                f"failures but {expected} findings are present"
            )
    role, minimum = _resolve_slice_policy(config, METRIC_VALIDATOR_RULES, "overall")
    per_rule_eval: Counter[str] = Counter()
    per_rule_fail: Counter[str] = Counter()
    for e in executions:
        per_rule_eval[e.rule_id] += e.evaluated_observation_count
        per_rule_fail[e.rule_id] += e.failed_observation_count
    for rule in VALIDATOR_RULE_ORDER:
        ev = per_rule_eval.get(rule, 0)
        fa = per_rule_fail.get(rule, 0)
        # Support denominator for this rule is that rule's evaluated count only.
        support = _support(ev, 0, ev, minimum)
        for measure, num in (("failure_count", fa), ("evaluated_count", ev)):
            _push_count(out, METRIC_VALIDATOR_RULES, "overall", role,
                        _dims(measure=measure, rule=rule), num, support)
        _push(out, METRIC_VALIDATOR_RULES, "overall", role,
              _dims(measure="failure_rate", rule=rule), _ratio(fa, ev), support,
              relevant=ev, minimum=minimum, numerator=fa, denominator=ev)
        _push(out, METRIC_VALIDATOR_RULES, "overall", role,
              _dims(measure="pass_rate", rule=rule), _ratio(ev - fa, ev), support,
              relevant=ev, minimum=minimum, numerator=ev - fa, denominator=ev)
    _compute_validator_summaries(per_rule_eval, per_rule_fail, config, out)


_SCHEMA_RULES: tuple[ValidatorRuleId, ...] = ("output_json_schema_validity",)
_EVIDENCE_RULES: tuple[ValidatorRuleId, ...] = (
    "source_id_resolution", "passage_id_resolution", "evidence_quote_containment",
)
_UNSUPPORTED_RULES: tuple[ValidatorRuleId, ...] = (
    "active_record_non_roadmap_evidence", "customer_task_outcome_and_evidence",
)
_TEMPORAL_RULES: tuple[ValidatorRuleId, ...] = ("publication_date_cutoff",)
_DUPLICATE_RULES: tuple[ValidatorRuleId, ...] = ("unique_ids_within_scope",)


def _compute_validator_summaries(
    per_rule_eval: Counter[str], per_rule_fail: Counter[str],
    config: ScoringGateConfig, out: list[MetricDatum]
) -> None:
    role, minimum = _resolve_slice_policy(config, METRIC_VALIDATOR_SUMMARIES, "overall")

    def add_rate(measure: str, rules: tuple[ValidatorRuleId, ...], *, pass_rate: bool) -> None:
        # Support denominator is the combined evaluated count of exactly this group.
        ev = sum(per_rule_eval.get(r, 0) for r in rules)
        fa = sum(per_rule_fail.get(r, 0) for r in rules)
        num = ev - fa if pass_rate else fa
        support = _support(ev, 0, ev, minimum)
        _push(out, METRIC_VALIDATOR_SUMMARIES, "overall", role, _dims(measure=measure),
              _ratio(num, ev), support, relevant=ev, minimum=minimum, numerator=num, denominator=ev)

    add_rate("schema_validity_rate", _SCHEMA_RULES, pass_rate=True)
    add_rate("evidence_validity_rate", _EVIDENCE_RULES, pass_rate=True)
    add_rate("unsupported_claim_rate", _UNSUPPORTED_RULES, pass_rate=False)
    add_rate("duplicate_rate", _DUPLICATE_RULES, pass_rate=False)
    temporal_eval = sum(per_rule_eval.get(r, 0) for r in _TEMPORAL_RULES)
    temporal = sum(per_rule_fail.get(r, 0) for r in _TEMPORAL_RULES)
    _push_count(out, METRIC_VALIDATOR_SUMMARIES, "overall", role,
                _dims(measure="temporal_leakage_count"), temporal,
                _support(temporal_eval, 0, temporal_eval, minimum))


def _compute_tier_metrics(
    obs: tuple[TierContractObservation, ...], config: ScoringGateConfig, out: list[MetricDatum]
) -> None:
    role, minimum = _resolve_slice_policy(config, METRIC_TIER_CONTRACT, "overall")
    for view in ("verified", "provisional"):
        pop = tuple(o for o in obs if o.verification_status == view)
        n = len(pop)
        datum_role: MetricConfigurationRole = role if view == "verified" else "diagnostic"
        support = _support(n if view == "verified" else 0, 0 if view == "verified" else n, n,
                           minimum)
        exact = sum(1 for o in pop if o.exact_contract_ok)
        tier_mm = sum(1 for o in pop if o.expected_tier != o.observed_tier)
        reason_mm = sum(1 for o in pop if o.expected_reason_codes != o.observed_reason_codes)
        trace_mm = sum(1 for o in pop if o.expected_rule_trace_hash != o.observed_rule_trace_hash)
        repeat_fail = sum(1 for o in pop if not o.repeatability_ok)
        base = {"verification": view}
        st, val, reason = _gated(n, minimum, _ratio(exact, n))
        out.append(MetricDatum(
            metric_id=METRIC_TIER_CONTRACT, population_slice_id="overall",
            configuration_role=datum_role, status=st, value=val, numerator=exact, denominator=n,
            support=support, dimensions=_dims(measure="exact_contract_match_rate", **base),
            reason_code=reason,
        ))
        for measure, num in (
            ("exact_contract_match_count", exact), ("tier_mismatch_count", tier_mm),
            ("reason_code_mismatch_count", reason_mm), ("rule_trace_mismatch_count", trace_mm),
            ("repeatability_failure_count", repeat_fail),
        ):
            out.append(MetricDatum(
                metric_id=METRIC_TIER_CONTRACT, population_slice_id="overall",
                configuration_role=datum_role, status="computed", value=num, numerator=num,
                denominator=None, support=support, dimensions=_dims(measure=measure, **base),
                reason_code=None,
            ))


def _compute_unsafe_exclusion(
    audit: UnsafeExclusionAuditSnapshot, config: ScoringGateConfig, out: list[MetricDatum]
) -> None:
    minimum, level = _resolve_unsafe_policy(config, "overall")
    z = statistics.NormalDist().inv_cdf(level)
    total_pop = sum(s.screen_negative_population_count for s in audit.strata)
    support = _support(sum(len(s.audited_labels) for s in audit.strata), 0, total_pop, minimum)
    any_insufficient = False
    weighted_rate_num = 0.0
    weighted_upper_num = 0.0
    est_missed = 0.0
    for stratum in audit.strata:
        n = len(stratum.audited_labels)
        missed = sum(1 for lab in stratum.audited_labels if lab.actually_eligible_or_boundary_relevant)
        nh = stratum.screen_negative_population_count
        base = {"stratum": stratum.stratum_id}
        if n < minimum:
            any_insufficient = True
            out.append(MetricDatum(
                metric_id=METRIC_UNSAFE_EXCLUSION, population_slice_id="overall",
                configuration_role="gate_input", status="indeterminate", value=None,
                numerator=missed, denominator=n, support=support,
                dimensions=_dims(measure="stratum_missed_rate", **base),
                reason_code="insufficient_audit_evidence",
            ))
            out.append(MetricDatum(
                metric_id=METRIC_UNSAFE_EXCLUSION, population_slice_id="overall",
                configuration_role="diagnostic", status="computed", value=missed,
                numerator=missed, denominator=n, support=support,
                dimensions=_dims(measure="stratum_missed_count", **base), reason_code=None,
            ))
            continue
        p = missed / n
        upper = _wilson_upper(missed, n, z)
        weighted_rate_num += nh * p
        weighted_upper_num += nh * upper
        est_missed += nh * p
        ci = ConfidenceInterval(method=_UNSAFE_CI_METHOD, confidence_level=level, lower=0.0,
                                upper=upper)
        out.append(MetricDatum(
            metric_id=METRIC_UNSAFE_EXCLUSION, population_slice_id="overall",
            configuration_role="gate_input", status="computed", value=p, numerator=missed,
            denominator=n, support=support, confidence_interval=ci,
            dimensions=_dims(measure="stratum_missed_rate", **base), reason_code=None,
        ))
        out.append(MetricDatum(
            metric_id=METRIC_UNSAFE_EXCLUSION, population_slice_id="overall",
            configuration_role="diagnostic", status="computed", value=missed, numerator=missed,
            denominator=n, support=support, dimensions=_dims(measure="stratum_missed_count",
            **base), reason_code=None,
        ))
    overall_dims = {"scope": "overall"}
    if any_insufficient:
        for measure in ("weighted_unsafe_exclusion_rate", "estimated_absolute_missed",
                        "weighted_upper_confidence_bound"):
            out.append(MetricDatum(
                metric_id=METRIC_UNSAFE_EXCLUSION, population_slice_id="overall",
                configuration_role="gate_input", status="indeterminate", value=None,
                support=support, dimensions=_dims(measure=measure, **overall_dims),
                reason_code="insufficient_audit_evidence",
            ))
    else:
        rate = weighted_rate_num / total_pop
        upper = weighted_upper_num / total_pop
        ci = ConfidenceInterval(method=_UNSAFE_CI_METHOD, confidence_level=level, lower=0.0,
                                upper=upper)
        out.append(MetricDatum(
            metric_id=METRIC_UNSAFE_EXCLUSION, population_slice_id="overall",
            configuration_role="gate_input", status="computed", value=rate, numerator=None,
            denominator=total_pop, support=support, confidence_interval=ci,
            dimensions=_dims(measure="weighted_unsafe_exclusion_rate", **overall_dims),
            reason_code=None,
        ))
        out.append(MetricDatum(
            metric_id=METRIC_UNSAFE_EXCLUSION, population_slice_id="overall",
            configuration_role="diagnostic", status="computed", value=est_missed, support=support,
            dimensions=_dims(measure="estimated_absolute_missed", **overall_dims),
            reason_code=None,
        ))
        out.append(MetricDatum(
            metric_id=METRIC_UNSAFE_EXCLUSION, population_slice_id="overall",
            configuration_role="gate_input", status="computed", value=upper, support=support,
            confidence_interval=ci,
            dimensions=_dims(measure="weighted_upper_confidence_bound", **overall_dims),
            reason_code=None,
        ))


def _compute_operational(
    s: ScreenOperationalSummary, config: ScoringGateConfig, out: list[MetricDatum]
) -> None:
    role, minimum = _resolve_slice_policy(config, METRIC_SCREEN_OPERATIONAL, "overall")
    # Deterministic, fully-observed denominator: verified_support = total screened.
    support = _support(s.total_screened, 0, s.total_screened, minimum)

    def add_rate(measure: str, num: int) -> None:
        _push(out, METRIC_SCREEN_OPERATIONAL, "overall", role, _dims(measure=measure),
              _ratio(num, s.total_screened), support, relevant=s.total_screened, minimum=minimum,
              numerator=num, denominator=s.total_screened)

    add_rate("pass_through_rate", s.screen_nonnegative)
    add_rate("unresolved_share", s.unresolved)
    add_rate("screen_negative_share", s.screen_negative)
    _push_count(out, METRIC_SCREEN_OPERATIONAL, "overall", role,
                _dims(measure="downstream_review_volume"), s.downstream_review_count, support)
    _push_count(out, METRIC_SCREEN_OPERATIONAL, "overall", role,
                _dims(measure="total_screened"), s.total_screened, support)


def _sort_key(datum: MetricDatum) -> tuple:
    return (
        datum.metric_id,
        datum.population_slice_id,
        tuple((d.key, d.value) for d in datum.dimensions),
    )


def _report_contract_metadata() -> dict[str, str]:
    return {
        "contract_id": _REPORT_CONTRACT_ID,
        "contract_version": _REPORT_CONTRACT_VERSION,
        "contract_hash": model_contract_hash(
            MetricReport, _REPORT_CONTRACT_ID, _REPORT_CONTRACT_VERSION
        ),
    }


def _report_v2_contract_metadata() -> dict[str, str]:
    return {
        "contract_id": _REPORT_CONTRACT_ID,
        "contract_version": _REPORT_V2_CONTRACT_VERSION,
        "contract_hash": model_contract_hash(
            MetricReportV2, _REPORT_CONTRACT_ID, _REPORT_V2_CONTRACT_VERSION
        ),
    }


_AXIS_FAMILY_BY_TYPE = {
    "multi_label": METRIC_AXIS_MULTI_LABEL,
    "structured_set": METRIC_AXIS_STRUCTURED_SET,
    "nominal_single_label": METRIC_AXIS_NOMINAL,
    "ordinal_single_label": METRIC_AXIS_ORDINAL,
}


def _axis_metric_id(axis: AxisDefinition) -> str:
    """The governed metric-family id an axis is scored under."""
    return _AXIS_FAMILY_BY_TYPE[axis.effective_metric_type]


def _extract_stage_evidence(
    binding: MetricApplicabilityBinding,
) -> tuple[
    tuple[TierContractObservation, ...] | None,
    UnsafeExclusionAuditSnapshot | None,
    ScreenOperationalSummary | None,
]:
    """Extract the tier/unsafe/screen payloads from the embedded evidence set."""
    tier_obs: tuple[TierContractObservation, ...] | None = None
    unsafe_audit: UnsafeExclusionAuditSnapshot | None = None
    screen_summary: ScreenOperationalSummary | None = None
    evidence = binding.stage_metric_evidence_set
    if evidence is not None:
        for variant in evidence.variants:
            if variant.kind == "universe_classification_tier":
                tier_obs = variant.tier_contract_observations
            elif variant.kind == "universe_unsafe_exclusion_audit":
                unsafe_audit = variant.unsafe_exclusion_audit
            elif variant.kind == "universe_screen_operational":
                screen_summary = variant.screen_operational_summary
    return tier_obs, unsafe_audit, screen_summary


def compute_metric_report(
    snapshot: MetricInputSnapshot,
    *,
    assertion_outcomes: tuple[AssertionOutcome, ...],
    validator_findings: tuple[ValidatorFinding, ...],
    run_manifest: EvaluationRunManifestV2,
    case_set_manifest: CaseSetManifest,
    scoring_config: LoadedScoringGateConfig,
) -> MetricReport:
    """Compute a deterministic ``MetricReport``. Pure: no I/O, no clock, no gate.

    ``scoring_config`` is the Slice 4 ``LoadedScoringGateConfig`` wrapper so its
    exact persisted-artifact SHA-256 can be bound to the run manifest; the
    supplied ``case_set_manifest`` is bound by its canonical snapshot hash (the
    hash the run manifest itself records). Both are already in memory, so this
    function performs no filesystem access.
    """
    if not isinstance(snapshot, MetricInputSnapshot):
        raise TypeError(f"snapshot must be a MetricInputSnapshot, got {type(snapshot).__name__}")
    # The active metric path is evaluation_run_manifest v0.2; v0.1 is rejected as
    # a binding error (its stage-evidence and applicability pins do not exist).
    if isinstance(run_manifest, EvaluationRunManifest) and not isinstance(
        run_manifest, EvaluationRunManifestV2
    ):
        raise SnapshotBindingError(
            "compute_metric_report requires an evaluation_run_manifest v0.2",
            binding_kind="run_manifest_version", eval_run_id=run_manifest.eval_run_id)
    if not isinstance(run_manifest, EvaluationRunManifestV2):
        raise TypeError(
            f"run_manifest must be an EvaluationRunManifestV2, got {type(run_manifest).__name__}")
    if not isinstance(case_set_manifest, CaseSetManifest):
        raise TypeError(
            f"case_set_manifest must be a CaseSetManifest, got {type(case_set_manifest).__name__}")
    if not isinstance(scoring_config, LoadedScoringGateConfig):
        raise TypeError(
            f"scoring_config must be a LoadedScoringGateConfig, got {type(scoring_config).__name__}")

    m = run_manifest
    config = scoring_config.config
    if snapshot.eval_run_id != m.eval_run_id:
        raise SnapshotBindingError("snapshot eval_run_id does not match the run manifest",
                                   binding_kind="eval_run_id", eval_run_id=m.eval_run_id)
    if snapshot.case_set_version != m.case_set_version or snapshot.case_set_hash != m.case_set_hash:
        raise SnapshotBindingError("snapshot case-set identity does not match the run manifest",
                                   binding_kind="case_set", eval_run_id=m.eval_run_id)
    if (snapshot.scoring_gate_config_version != m.scoring_gate_config_version
            or snapshot.scoring_gate_config_hash != m.scoring_gate_config_hash):
        raise SnapshotBindingError("snapshot scoring-config identity does not match the manifest",
                                   binding_kind="scoring_config", eval_run_id=m.eval_run_id)
    # Bind the supplied artifacts to the exact hashes the run manifest records:
    # the case-set by its canonical snapshot hash, the scoring config by its raw
    # persisted-artifact SHA-256 carried on the loaded wrapper.
    if case_set_manifest.case_set_version != m.case_set_version:
        raise SnapshotBindingError("case-set manifest version does not match the run manifest",
                                   binding_kind="case_set_manifest_version", eval_run_id=m.eval_run_id)
    if case_set_snapshot_hash(case_set_manifest) != m.case_set_hash:
        raise SnapshotBindingError("case-set manifest snapshot hash does not match the manifest",
                                   binding_kind="case_set_manifest_hash", eval_run_id=m.eval_run_id)
    if config.config_version != m.scoring_gate_config_version:
        raise SnapshotBindingError("scoring config version does not match the run manifest",
                                   binding_kind="scoring_config_version", eval_run_id=m.eval_run_id)
    # The loaded wrapper's own version field must agree with its inner config
    # version; a governed public input cannot carry inconsistent identities.
    if scoring_config.version != config.config_version:
        raise SnapshotBindingError("scoring config wrapper version does not match its inner "
                                   "config version",
                                   binding_kind="scoring_config_wrapper_version",
                                   eval_run_id=m.eval_run_id)
    if scoring_config.sha256 != m.scoring_gate_config_hash:
        raise SnapshotBindingError("scoring config artifact hash does not match the manifest",
                                   binding_kind="scoring_config_hash", eval_run_id=m.eval_run_id)

    # Re-verify the snapshot's applicability binding against the v0.2 manifest
    # pins (stage-profile registry identity, selected-entry identity, and the
    # paired stage-evidence identity). The embedded evidence's own stage/version/
    # content-hash/kinds were bound to these pins when the snapshot was built.
    app_binding = snapshot.applicability_binding
    if app_binding.stage_profile_registry_version != m.stage_profile_registry_version:
        raise SnapshotBindingError(
            "snapshot stage-profile registry version does not match the manifest",
            binding_kind="stage_profile_registry_version", eval_run_id=m.eval_run_id)
    if app_binding.stage_profile_registry_hash != m.stage_profile_registry_hash:
        raise SnapshotBindingError(
            "snapshot stage-profile registry hash does not match the manifest",
            binding_kind="stage_profile_registry_hash", eval_run_id=m.eval_run_id)
    if app_binding.selected_stage_profile_entry_hash != m.selected_stage_profile_entry_hash:
        raise SnapshotBindingError(
            "snapshot selected stage-profile entry hash does not match the manifest",
            binding_kind="selected_stage_profile_entry_hash", eval_run_id=m.eval_run_id)
    if app_binding.stage_metric_evidence_set_version != m.stage_metric_evidence_set_version:
        raise SnapshotBindingError(
            "snapshot stage-evidence version does not match the manifest",
            binding_kind="stage_metric_evidence_set_version", eval_run_id=m.eval_run_id)
    if app_binding.stage_metric_evidence_set_hash != m.stage_metric_evidence_set_hash:
        raise SnapshotBindingError(
            "snapshot stage-evidence hash does not match the manifest",
            binding_kind="stage_metric_evidence_set_hash", eval_run_id=m.eval_run_id)

    # Run and case-set binding for every supplied record (§9).
    for outcome in assertion_outcomes:
        if outcome.eval_run_id != m.eval_run_id:
            raise OutcomeRunBindingError("an assertion outcome eval_run_id does not match the run",
                                         eval_run_id=m.eval_run_id)
    for finding in validator_findings:
        if finding.run_id != m.eval_run_id:
            raise FindingRunBindingError("a validator finding run_id does not match the run",
                                         eval_run_id=m.eval_run_id)
    membership: dict[str, CaseMembership] = {e.case_id: e for e in case_set_manifest.entries}
    for record in snapshot.axis_records:
        if record.case_id not in membership:
            raise CaseMembershipBindingError(
                f"axis record case {record.case_id!r} is absent from the case set",
                binding_kind="unknown_case", case_id=record.case_id)
    for binding in snapshot.assertion_bindings:
        entry = membership.get(binding.case_id)
        if entry is None:
            raise CaseMembershipBindingError(
                f"assertion binding case {binding.case_id!r} is absent from the case set",
                binding_kind="unknown_case", case_id=binding.case_id)
        if binding.partition != entry.partition:
            raise CaseMembershipBindingError(
                f"assertion binding partition for case {binding.case_id!r} disagrees with the "
                "authoritative case membership",
                binding_kind="partition_mismatch", case_id=binding.case_id)
        if binding.suites != entry.suites:
            raise CaseMembershipBindingError(
                f"assertion binding suites for case {binding.case_id!r} disagree with the "
                "authoritative case membership",
                binding_kind="suites_mismatch", case_id=binding.case_id)

    # Stage dispatch: compute only families the resolved stage profile marks
    # applicable (ADR-024). Universe payloads are read only from the embedded
    # stage-evidence set; extraction stages carry none.
    applicable = set(app_binding.applicable_metric_families)
    tier_obs, unsafe_audit, screen_summary = _extract_stage_evidence(app_binding)

    out: list[MetricDatum] = []
    by_axis: dict[str, list[AxisEvaluationRecord]] = {a.axis_id: [] for a in snapshot.axis_definitions}
    for record in snapshot.axis_records:
        by_axis[record.axis_id].append(record)
    for axis in snapshot.axis_definitions:
        records = tuple(by_axis[axis.axis_id])
        if _axis_metric_id(axis) in applicable:
            _compute_axis_metrics(axis, records, config, out)
        if METRIC_AXIS_ABSTENTION in applicable:
            _compute_abstention_metrics(axis, records, config, out)
    if METRIC_ASSERTION_OUTCOMES in applicable:
        _compute_assertion_diagnostics(snapshot, assertion_outcomes, config, out)
    if METRIC_VALIDATOR_RULES in applicable or METRIC_VALIDATOR_SUMMARIES in applicable:
        _compute_validator_metrics(snapshot, validator_findings, config, out)
    if METRIC_TIER_CONTRACT in applicable and tier_obs is not None:
        _compute_tier_metrics(tier_obs, config, out)
    if METRIC_UNSAFE_EXCLUSION in applicable and unsafe_audit is not None:
        _compute_unsafe_exclusion(unsafe_audit, config, out)
    if METRIC_SCREEN_OPERATIONAL in applicable and screen_summary is not None:
        _compute_operational(screen_summary, config, out)

    # Strict guarantee: no MetricDatum for an inapplicable metric family, whatever
    # the per-family emitter granularity.
    out = [d for d in out if d.metric_id in applicable]
    out.sort(key=_sort_key)
    return MetricReport.model_validate({
        "contract": _report_contract_metadata(),
        "eval_run_id": m.eval_run_id,
        "case_set_version": m.case_set_version,
        "case_set_hash": m.case_set_hash,
        "scoring_gate_config_version": m.scoring_gate_config_version,
        "scoring_gate_config_hash": m.scoring_gate_config_hash,
        "metric_input_snapshot_hash": metric_input_snapshot_hash(snapshot),
        "metrics": [d.model_dump(mode="json", exclude_unset=False) for d in out],
    })


def _build_applicability_ledger(entry) -> list[dict[str, str]]:
    """Derive the canonical eleven-family ledger from a resolved stage-profile
    entry: applicable families carry no reason; each inapplicable family takes
    its reason code from ``applicability_reason_codes`` paired positionally with
    the canonical complement of applicable families."""
    applicable = set(entry.applicable_metric_families)
    complement = tuple(f for f in _CANONICAL_METRIC_FAMILIES if f not in applicable)
    reasons = entry.applicability_reason_codes
    if len(reasons) != len(complement):
        raise SnapshotBindingError(
            "stage-profile entry reason codes do not pair with the inapplicable families",
            binding_kind="applicability_reason_arity")
    reason_by_family = dict(zip(complement, reasons))
    ledger: list[dict[str, str]] = []
    for family in _CANONICAL_METRIC_FAMILIES:
        if family in applicable:
            ledger.append({"metric_family": family, "applicability_state": "applicable"})
        else:
            ledger.append({
                "metric_family": family, "applicability_state": "inapplicable",
                "reason_code": reason_by_family[family],
            })
    return ledger


def _verify_v2_report_against_registry(
    report: "MetricReportV2",
    m: EvaluationRunManifestV2,
    stage_profile_registry: LoadedStageProfileRegistry,
) -> None:
    """Fail closed unless a v0.2 report's stage, registry identity, selected entry,
    applicable-family set, every ledger state, and every inapplicable reason code
    are exactly what the supplied hash-bound stage-profile registry resolves —
    not merely the run-manifest pins. Structural validity is not sufficient: the
    ledger is rebuilt from the resolved entry and compared entry-for-entry so a
    nonblank but forged/swapped reason code is rejected."""
    if not isinstance(stage_profile_registry, LoadedStageProfileRegistry):
        raise TypeError(
            f"stage_profile_registry must be a LoadedStageProfileRegistry, got "
            f"{type(stage_profile_registry).__name__}")
    try:
        entry = resolve_metric_applicability(
            stage_profile_registry.registry, report.evaluation_stage)
    except StageProfileError as exc:
        raise MetricReportBindingError(
            "report evaluation stage does not resolve to a supported profile entry",
            eval_run_id=m.eval_run_id) from exc
    registry_version = stage_profile_registry.version
    registry_hash = stage_profile_registry_hash(stage_profile_registry.registry)
    # Stage is bound to the manifest transitively: the manifest carries no literal
    # stage field, so the resolved entry hash must equal the manifest's selected
    # entry pin AND the resolved entry's stage must equal the report stage.
    if entry.evaluation_stage != report.evaluation_stage:
        raise MetricReportBindingError("resolved stage does not match the report stage",
                                       eval_run_id=m.eval_run_id)
    if not (registry_version == report.stage_profile_registry_version
            == m.stage_profile_registry_version):
        raise MetricReportBindingError("stage-profile registry version disagreement",
                                       eval_run_id=m.eval_run_id)
    if not (registry_hash == report.stage_profile_registry_hash
            == m.stage_profile_registry_hash):
        raise MetricReportBindingError("stage-profile registry content-hash disagreement",
                                       eval_run_id=m.eval_run_id)
    if not (entry.entry_hash == report.selected_stage_profile_entry_hash
            == m.selected_stage_profile_entry_hash):
        raise MetricReportBindingError("selected stage-profile entry hash disagreement",
                                       eval_run_id=m.eval_run_id)
    ledger_applicable = tuple(
        e.metric_family for e in report.applicability_ledger
        if e.applicability_state == "applicable")
    if tuple(entry.applicable_metric_families) != ledger_applicable:
        raise MetricReportBindingError("ledger applicable-family set disagreement",
                                       eval_run_id=m.eval_run_id)
    expected = tuple(
        MetricFamilyApplicabilityEntry.model_validate(d)
        for d in _build_applicability_ledger(entry))
    if report.applicability_ledger != expected:
        raise MetricReportBindingError(
            "applicability ledger does not match the registry-derived ledger "
            "(state or reason code mismatch)", eval_run_id=m.eval_run_id)


def compute_metric_report_v2(
    snapshot: MetricInputSnapshot,
    *,
    assertion_outcomes: tuple[AssertionOutcome, ...],
    validator_findings: tuple[ValidatorFinding, ...],
    run_manifest: EvaluationRunManifestV2,
    case_set_manifest: CaseSetManifest,
    scoring_config: LoadedScoringGateConfig,
    stage_profile_registry: LoadedStageProfileRegistry,
) -> MetricReportV2:
    """Compute a deterministic ``metric_report@0.2.0`` with the applicability
    ledger. Pure: no I/O, no clock, no gate. Resolves the snapshot's stage
    through the supplied registry and fails closed unless the registry identity,
    selected entry, stage, applicable-family set, required evidence kinds, and the
    v0.2 run-manifest pins all agree; every inapplicable reason is derived from
    the resolved ``StageProfileEntry`` — never caller-supplied."""
    if not isinstance(snapshot, MetricInputSnapshot):
        raise TypeError(f"snapshot must be a MetricInputSnapshot, got {type(snapshot).__name__}")
    if not isinstance(run_manifest, EvaluationRunManifestV2):
        raise TypeError(
            f"run_manifest must be an EvaluationRunManifestV2, got {type(run_manifest).__name__}")
    if not isinstance(stage_profile_registry, LoadedStageProfileRegistry):
        raise TypeError(
            f"stage_profile_registry must be a LoadedStageProfileRegistry, got "
            f"{type(stage_profile_registry).__name__}")

    binding = snapshot.applicability_binding
    m = run_manifest
    try:
        entry = resolve_metric_applicability(stage_profile_registry.registry, binding.evaluation_stage)
    except StageProfileError as exc:
        raise SnapshotBindingError(
            "snapshot evaluation stage does not resolve to a supported profile entry",
            binding_kind="stage_resolution", eval_run_id=m.eval_run_id) from exc

    registry_version = stage_profile_registry.version
    registry_hash = stage_profile_registry_hash(stage_profile_registry.registry)
    if not (registry_version == binding.stage_profile_registry_version
            == m.stage_profile_registry_version):
        raise SnapshotBindingError("stage-profile registry version disagreement",
                                   binding_kind="stage_profile_registry_version",
                                   eval_run_id=m.eval_run_id)
    if not (registry_hash == binding.stage_profile_registry_hash
            == m.stage_profile_registry_hash):
        raise SnapshotBindingError("stage-profile registry content-hash disagreement",
                                   binding_kind="stage_profile_registry_hash",
                                   eval_run_id=m.eval_run_id)
    if not (entry.entry_hash == binding.selected_stage_profile_entry_hash
            == m.selected_stage_profile_entry_hash):
        raise SnapshotBindingError("selected stage-profile entry hash disagreement",
                                   binding_kind="selected_stage_profile_entry_hash",
                                   eval_run_id=m.eval_run_id)
    if entry.evaluation_stage != binding.evaluation_stage:
        raise SnapshotBindingError("resolved stage does not match the snapshot binding",
                                   binding_kind="evaluation_stage", eval_run_id=m.eval_run_id)
    if tuple(entry.applicable_metric_families) != tuple(binding.applicable_metric_families):
        raise SnapshotBindingError("applicable metric-family set disagreement",
                                   binding_kind="applicable_metric_families",
                                   eval_run_id=m.eval_run_id)
    if tuple(entry.required_stage_evidence_kinds) != tuple(binding.required_stage_evidence_kinds):
        raise SnapshotBindingError("required stage-evidence kinds disagreement",
                                   binding_kind="required_stage_evidence_kinds",
                                   eval_run_id=m.eval_run_id)

    # Only after every registry/binding check passes is the v0.1 producer reused
    # for the metric data; it performs its own snapshot/manifest binding checks.
    base = compute_metric_report(
        snapshot, assertion_outcomes=assertion_outcomes, validator_findings=validator_findings,
        run_manifest=run_manifest, case_set_manifest=case_set_manifest, scoring_config=scoring_config)

    applicable = set(entry.applicable_metric_families)
    # Independent enforcement of the no-inapplicable-datum rule.
    for datum in base.metrics:
        if datum.metric_id not in applicable:
            raise SnapshotBindingError(
                "a computed MetricDatum belongs to an inapplicable metric family",
                binding_kind="inapplicable_datum", eval_run_id=m.eval_run_id)

    return MetricReportV2.model_validate({
        "contract": _report_v2_contract_metadata(),
        "eval_run_id": base.eval_run_id,
        "case_set_version": base.case_set_version,
        "case_set_hash": base.case_set_hash,
        "scoring_gate_config_version": base.scoring_gate_config_version,
        "scoring_gate_config_hash": base.scoring_gate_config_hash,
        "metric_input_snapshot_hash": base.metric_input_snapshot_hash,
        "evaluation_stage": binding.evaluation_stage,
        "stage_profile_registry_version": registry_version,
        "stage_profile_registry_hash": registry_hash,
        "selected_stage_profile_entry_hash": entry.entry_hash,
        "applicability_ledger": _build_applicability_ledger(entry),
        "metrics": [d.model_dump(mode="json", exclude_unset=False) for d in base.metrics],
    })


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
        raise InvalidEvaluationRootError(f"eval_root {str(root)!r} does not exist",
                                         supplied_root=str(root))
    if not path.is_dir():
        raise InvalidEvaluationRootError(f"eval_root {str(root)!r} is not a directory",
                                         supplied_root=str(root))
    return path.resolve()


def _canonical_report_bytes(report: MetricReport) -> bytes:
    return canonical_contract_bytes(report.model_dump(mode="json", exclude_unset=False))


def _write_metric_artifact_once(dest: Path, data: bytes, *, eval_run_id: str,
                                reference: str) -> str:
    """Exclusive-create write of ``data`` to ``dest`` with read-back verification."""
    expected = sha256_bytes(data)
    if dest.is_symlink():
        raise MetricReportExistsError(f"metrics artifact {reference!r} already exists; write-once",
                                      eval_run_id=eval_run_id, artifact_reference=reference)
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise MetricReportExistsError(f"metrics artifact {reference!r} already exists; write-once",
                                      eval_run_id=eval_run_id, artifact_reference=reference) from exc
    except OSError as exc:
        raise MetricWriteError(f"failed to create metrics artifact {reference!r}",
                               eval_run_id=eval_run_id, artifact_reference=reference) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise MetricWriteError(f"failed to write metrics artifact {reference!r}",
                               eval_run_id=eval_run_id, artifact_reference=reference) from exc
    try:
        observed = sha256_bytes(dest.read_bytes())
    except OSError as exc:
        raise MetricWriteError(f"failed to re-read metrics artifact {reference!r} for verification",
                               eval_run_id=eval_run_id, artifact_reference=reference) from exc
    if observed != expected:
        raise MetricDestinationHashMismatchError(
            f"written metrics artifact {reference!r} re-read to a different hash",
            eval_run_id=eval_run_id, artifact_reference=reference,
            expected_sha256=expected, observed_sha256=observed,
        )
    return expected


def persist_metric_report(
    report: "MetricReport | MetricReportV2", *, eval_root: str | Path, eval_run_id: str,
    stage_profile_registry: LoadedStageProfileRegistry | None = None,
) -> PersistedMetricReport:
    """Persist a metric report as write-once JSON in the Slice 5 run dir.

    This is the single public persistence path for both report versions. The v0.1
    behavior, bytes, artifact path (``metrics/metric_report.json``), write-once
    semantics, and return wrapper are unchanged and require **no** registry. A
    ``MetricReportV2`` is written to the distinct ``metrics/metric_report.v2.json``
    artifact and **requires** a ``LoadedStageProfileRegistry`` against which its
    stage, registry identity, selected entry, applicable-family set, ledger
    states, and every inapplicable reason code are verified before any bytes are
    written; it returns the same public ``PersistedMetricReport`` wrapper.
    """
    is_v2 = isinstance(report, MetricReportV2)
    if not is_v2 and not isinstance(report, MetricReport):
        raise TypeError(
            f"report must be a MetricReport or MetricReportV2, got {type(report).__name__}")
    resolved_root = _validate_root(eval_root)
    loaded = load_evaluation_run_manifest_v2(eval_run_id, eval_root=resolved_root)
    m = loaded.manifest
    if report.eval_run_id != m.eval_run_id:
        raise MetricReportBindingError("report eval_run_id does not match the run manifest",
                                       eval_run_id=m.eval_run_id)
    if report.case_set_version != m.case_set_version or report.case_set_hash != m.case_set_hash:
        raise MetricReportBindingError("report case-set identity does not match the run manifest",
                                       eval_run_id=m.eval_run_id)
    if (report.scoring_gate_config_version != m.scoring_gate_config_version
            or report.scoring_gate_config_hash != m.scoring_gate_config_hash):
        raise MetricReportBindingError("report scoring-config identity does not match the manifest",
                                       eval_run_id=m.eval_run_id)

    metrics_dir = resolved_root / eval_run_id / _METRICS_DIR

    if is_v2:
        if stage_profile_registry is None:
            raise MetricReportBindingError(
                "persisting a v0.2 metric report requires a stage-profile registry",
                eval_run_id=m.eval_run_id)
        _verify_v2_report_against_registry(report, m, stage_profile_registry)
        reference = f"{eval_run_id}/{_METRICS_DIR}/{_METRICS_V2_FILENAME}"
        if metrics_dir.is_symlink():
            raise MetricReportExistsError(
                f"metrics directory {eval_run_id}/{_METRICS_DIR} is a symlink",
                eval_run_id=eval_run_id, artifact_reference=f"{eval_run_id}/{_METRICS_DIR}")
        if not metrics_dir.exists():
            try:
                metrics_dir.mkdir(exist_ok=False)
            except OSError as exc:
                raise MetricWriteError(f"failed to create metrics directory for {eval_run_id!r}",
                                       eval_run_id=eval_run_id) from exc
        elif not metrics_dir.is_dir():
            raise MetricReportExistsError(
                f"metrics path {eval_run_id}/{_METRICS_DIR} is not a directory",
                eval_run_id=eval_run_id, artifact_reference=f"{eval_run_id}/{_METRICS_DIR}")
        data = canonical_contract_bytes(report.model_dump(mode="json", exclude_unset=True)) + b"\n"
        dest = metrics_dir / _METRICS_V2_FILENAME
        expected = _write_metric_artifact_once(dest, data, eval_run_id=eval_run_id,
                                               reference=reference)
        return PersistedMetricReport(eval_run_id=eval_run_id, artifact_reference=reference,
                                     sha256=expected, report=report)

    # --- v0.1 path (unchanged: fresh metrics dir required, distinct filename) ---
    reference = f"{eval_run_id}/{_METRICS_DIR}/{_METRICS_FILENAME}"
    if metrics_dir.exists() or metrics_dir.is_symlink():
        raise MetricReportExistsError(f"metrics directory {eval_run_id}/{_METRICS_DIR} already exists",
                                      eval_run_id=eval_run_id,
                                      artifact_reference=f"{eval_run_id}/{_METRICS_DIR}")
    try:
        metrics_dir.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise MetricReportExistsError(f"metrics directory {eval_run_id}/{_METRICS_DIR} already exists",
                                      eval_run_id=eval_run_id,
                                      artifact_reference=f"{eval_run_id}/{_METRICS_DIR}") from exc
    except OSError as exc:
        raise MetricWriteError(f"failed to create metrics directory for {eval_run_id!r}",
                               eval_run_id=eval_run_id) from exc
    data = _canonical_report_bytes(report) + b"\n"
    dest = metrics_dir / _METRICS_FILENAME
    expected = _write_metric_artifact_once(dest, data, eval_run_id=eval_run_id, reference=reference)
    return PersistedMetricReport(eval_run_id=eval_run_id, artifact_reference=reference,
                                 sha256=expected, report=report)


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


def load_metric_report(eval_run_id: str, *, eval_root: str | Path) -> LoadedMetricReport:
    """Load a metric report from the fixed run-directory path."""
    resolved_root = _validate_root(eval_root)
    loaded_run = load_evaluation_run_manifest_v2(eval_run_id, eval_root=resolved_root)
    m = loaded_run.manifest
    run_dir = resolved_root / eval_run_id
    metrics_dir = run_dir / _METRICS_DIR
    reference = f"{eval_run_id}/{_METRICS_DIR}/{_METRICS_FILENAME}"
    dest = metrics_dir / _METRICS_FILENAME
    if run_dir.is_symlink() or metrics_dir.is_symlink() or dest.is_symlink():
        raise MetricArtifactNotAFileError(f"metrics artifact {reference!r} or a parent is a symlink",
                                          eval_run_id=eval_run_id, artifact_reference=reference)
    if not dest.exists():
        raise MetricArtifactMissingError(f"metrics artifact {reference!r} does not exist",
                                         eval_run_id=eval_run_id, artifact_reference=reference)
    if not dest.is_file():
        raise MetricArtifactNotAFileError(f"metrics artifact {reference!r} is not a regular file",
                                          eval_run_id=eval_run_id, artifact_reference=reference)
    try:
        raw = dest.read_bytes()
    except OSError as exc:
        raise MetricArtifactReadError(f"failed to read metrics artifact {reference!r}",
                                      eval_run_id=eval_run_id, artifact_reference=reference) from exc
    observed = sha256_bytes(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MetricDecodeError(f"metrics artifact {reference!r} is not valid UTF-8",
                                eval_run_id=eval_run_id, artifact_reference=reference) from exc
    if text.startswith("\ufeff"):
        raise MetricJsonError(f"metrics artifact {reference!r} has a UTF-8 BOM",
                              eval_run_id=eval_run_id, artifact_reference=reference)
    try:
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_keys,
                             parse_constant=_reject_non_finite_constant)
    except json.JSONDecodeError as exc:
        raise MetricJsonError(f"metrics artifact {reference!r} is not valid JSON: {exc.msg}",
                              eval_run_id=eval_run_id, artifact_reference=reference) from exc
    except _DuplicateKeyControl as exc:
        raise MetricJsonError(f"metrics artifact {reference!r} has duplicate key {exc.key!r}",
                              eval_run_id=eval_run_id, artifact_reference=reference,
                              duplicate_key=exc.key) from exc
    except _NonFiniteControl as exc:
        raise MetricJsonError(f"metrics artifact {reference!r} has non-JSON constant "
                              f"{exc.constant_name}", eval_run_id=eval_run_id,
                              artifact_reference=reference, constant_name=exc.constant_name) from exc
    non_finite = _first_non_finite(payload)
    if non_finite is not None:
        raise MetricJsonError(f"metrics artifact {reference!r} has non-finite number ({non_finite})",
                              eval_run_id=eval_run_id, artifact_reference=reference,
                              constant_name=non_finite)
    if not isinstance(payload, dict):
        raise MetricTopLevelTypeError(f"metrics artifact {reference!r} is not a JSON object",
                                      eval_run_id=eval_run_id, artifact_reference=reference,
                                      observed_type=type(payload).__name__)
    try:
        report = MetricReport.model_validate(payload)
    except PydanticValidationError as exc:
        pairs = sorted(("/".join(str(p) for p in e["loc"]), e["type"]) for e in exc.errors())
        raise MetricModelValidationError(
            f"metrics artifact {reference!r} failed MetricReport validation",
            eval_run_id=eval_run_id, artifact_reference=reference,
            field_locations=tuple(loc for loc, _ in pairs),
            error_types=tuple(t for _, t in pairs),
        ) from exc
    if report.eval_run_id != m.eval_run_id:
        raise MetricReportBindingError(f"metrics artifact {reference!r} records a different run",
                                       eval_run_id=eval_run_id, artifact_reference=reference)
    if report.case_set_version != m.case_set_version or report.case_set_hash != m.case_set_hash:
        raise MetricReportBindingError(f"metrics artifact {reference!r} case-set identity mismatch",
                                       eval_run_id=eval_run_id, artifact_reference=reference)
    if (report.scoring_gate_config_version != m.scoring_gate_config_version
            or report.scoring_gate_config_hash != m.scoring_gate_config_hash):
        raise MetricReportBindingError(f"metrics artifact {reference!r} scoring-config mismatch",
                                       eval_run_id=eval_run_id, artifact_reference=reference)
    return LoadedMetricReport(eval_run_id=eval_run_id, artifact_reference=reference,
                              sha256=observed, report=report)


# --- Metric report v0.2 persistence / reader ------------------------------


def load_metric_report_v2(
    eval_run_id: str, *, eval_root: str | Path,
    stage_profile_registry: LoadedStageProfileRegistry,
) -> "_LoadedMetricReportV2":
    """Load a ``metric_report@0.2.0`` report; accepts only v0.2 (a v0.1 artifact
    is rejected, never silently upgraded). Applies the same strict JSON / symlink
    / hash / read-back protections as the v0.1 reader, revalidates the v0.2 run,
    stage-profile, and report identity bindings against the run manifest, and then
    verifies the report against the supplied hash-bound stage-profile registry so a
    tampered but structurally valid ledger reason or stage mismatch fails closed."""
    resolved_root = _validate_root(eval_root)
    loaded_run = load_evaluation_run_manifest_v2(eval_run_id, eval_root=resolved_root)
    m = loaded_run.manifest
    run_dir = resolved_root / eval_run_id
    metrics_dir = run_dir / _METRICS_DIR
    reference = f"{eval_run_id}/{_METRICS_DIR}/{_METRICS_V2_FILENAME}"
    dest = metrics_dir / _METRICS_V2_FILENAME
    if run_dir.is_symlink() or metrics_dir.is_symlink() or dest.is_symlink():
        raise MetricArtifactNotAFileError(f"metrics artifact {reference!r} or a parent is a symlink",
                                          eval_run_id=eval_run_id, artifact_reference=reference)
    if not dest.exists():
        raise MetricArtifactMissingError(f"metrics artifact {reference!r} does not exist",
                                         eval_run_id=eval_run_id, artifact_reference=reference)
    if not dest.is_file():
        raise MetricArtifactNotAFileError(f"metrics artifact {reference!r} is not a regular file",
                                          eval_run_id=eval_run_id, artifact_reference=reference)
    try:
        raw = dest.read_bytes()
    except OSError as exc:
        raise MetricArtifactReadError(f"failed to read metrics artifact {reference!r}",
                                      eval_run_id=eval_run_id, artifact_reference=reference) from exc
    observed = sha256_bytes(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MetricDecodeError(f"metrics artifact {reference!r} is not valid UTF-8",
                                eval_run_id=eval_run_id, artifact_reference=reference) from exc
    if text.startswith("\ufeff"):
        raise MetricJsonError(f"metrics artifact {reference!r} has a UTF-8 BOM",
                              eval_run_id=eval_run_id, artifact_reference=reference)
    try:
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_keys,
                             parse_constant=_reject_non_finite_constant)
    except json.JSONDecodeError as exc:
        raise MetricJsonError(f"metrics artifact {reference!r} is not valid JSON: {exc.msg}",
                              eval_run_id=eval_run_id, artifact_reference=reference) from exc
    except _DuplicateKeyControl as exc:
        raise MetricJsonError(f"metrics artifact {reference!r} has duplicate key {exc.key!r}",
                              eval_run_id=eval_run_id, artifact_reference=reference,
                              duplicate_key=exc.key) from exc
    except _NonFiniteControl as exc:
        raise MetricJsonError(f"metrics artifact {reference!r} has non-JSON constant "
                              f"{exc.constant_name}", eval_run_id=eval_run_id,
                              artifact_reference=reference, constant_name=exc.constant_name) from exc
    non_finite = _first_non_finite(payload)
    if non_finite is not None:
        raise MetricJsonError(f"metrics artifact {reference!r} has non-finite number ({non_finite})",
                              eval_run_id=eval_run_id, artifact_reference=reference,
                              constant_name=non_finite)
    if not isinstance(payload, dict):
        raise MetricTopLevelTypeError(f"metrics artifact {reference!r} is not a JSON object",
                                      eval_run_id=eval_run_id, artifact_reference=reference,
                                      observed_type=type(payload).__name__)
    try:
        report = MetricReportV2.model_validate(payload)
    except PydanticValidationError as exc:
        pairs = sorted(("/".join(str(p) for p in e["loc"]), e["type"]) for e in exc.errors())
        raise MetricModelValidationError(
            f"metrics artifact {reference!r} failed MetricReportV2 validation",
            eval_run_id=eval_run_id, artifact_reference=reference,
            field_locations=tuple(loc for loc, _ in pairs),
            error_types=tuple(t for _, t in pairs),
        ) from exc
    if report.eval_run_id != m.eval_run_id:
        raise MetricReportBindingError(f"metrics artifact {reference!r} records a different run",
                                       eval_run_id=eval_run_id, artifact_reference=reference)
    if report.case_set_version != m.case_set_version or report.case_set_hash != m.case_set_hash:
        raise MetricReportBindingError(f"metrics artifact {reference!r} case-set identity mismatch",
                                       eval_run_id=eval_run_id, artifact_reference=reference)
    if (report.scoring_gate_config_version != m.scoring_gate_config_version
            or report.scoring_gate_config_hash != m.scoring_gate_config_hash):
        raise MetricReportBindingError(f"metrics artifact {reference!r} scoring-config mismatch",
                                       eval_run_id=eval_run_id, artifact_reference=reference)
    if (report.stage_profile_registry_version != m.stage_profile_registry_version
            or report.stage_profile_registry_hash != m.stage_profile_registry_hash
            or report.selected_stage_profile_entry_hash != m.selected_stage_profile_entry_hash):
        raise MetricReportBindingError(f"metrics artifact {reference!r} stage-profile pin mismatch",
                                       eval_run_id=eval_run_id, artifact_reference=reference)
    # Registry-truthful verification: resolve the report stage through the supplied
    # hash-bound registry and reject a tampered stage or ledger reason even when the
    # on-disk artifact is structurally valid and matches the manifest pins.
    _verify_v2_report_against_registry(report, m, stage_profile_registry)
    return _LoadedMetricReportV2(eval_run_id=eval_run_id, artifact_reference=reference,
                                 sha256=observed, report=report)
