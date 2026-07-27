"""Gate evaluation and status/verdict separation (Slice 10, SPEC-020 / ADR-019).

Slice 10 derives a run's ``execution_status`` and, for completed runs only, a
``gate_verdict`` by layered evaluation (validity → current-run critical
findings → current-run metric gates), and assembles/persists the committed
``EvaluationResultV2`` (``evaluation_result@0.2.0``) validated against
``schemas/evaluation_result.v2.schema.json`` through the committed registry.

Locked semantics:
- Three pure constructors — ``assess_completed_evaluation`` (all-or-nothing
  completed; raises typed errors on invalid input, never converts them into a
  status), ``build_invalid_evaluation`` and ``build_errored_evaluation`` — none
  of which touch the filesystem, clock, randomness, UUIDs, dispositions,
  exceptions, comparison/regression, or aggregate scoring.
- Gate policy is parsed strictly from the opaque ``ScoringGateConfig`` dicts;
  no threshold, operator, confidence level or support count is hardcoded.
- Metric selection is exact: (metric_id, population_slice_id, role=gate_input,
  complete dimension mapping) with exactly one candidate; a selected datum
  carrying a ``verification`` dimension must be ``verified`` (provisional is
  always rejected), with no hardcoded family list.
- Verdict precedence: any current critical finding → fail; else any metric gate
  fail → fail; else any metric gate indeterminate → indeterminate; else pass.
- Dispositions never enter gate arithmetic; no exception mechanism exists.

Immutability here means refuse-to-overwrite directories, exclusive-create files
and read-back hash verification — not OS-level immutability.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError as PydanticValidationError,
    model_validator,
)

from .case_sets import case_set_snapshot_hash
from .cases import InvalidEvaluationRootError
from .contracts import canonical_contract_bytes
from .metrics import (
    ConfidenceInterval,
    LoadedMetricReport,
    MetricDatum,
    MetricDimension,
    MetricReport,
    MetricReportV2,
    MetricSupport,
    _LoadedMetricReportV2,
)
from .models import (
    CaseSetManifest,
    EvaluationResultV2,
    EvaluationRunManifest,
    EvaluationRunManifestV2,
    GateVerdict,
)
from .runs import _load_run_manifest_any_supported_version
from .schemas import load_schema
from .scoring_config import GateDefinition, LoadedScoringGateConfig, ScoringGateConfig
from .validators import LoadedValidatorFindings
from ..universe.io_utils import sha256_bytes

_RESULTS_DIR = "results"
_RESULTS_FILENAME = "evaluation_result.json"
_ARTIFACT_REFERENCE = "results/evaluation_result.json"
_RESULT_CONTRACT_ID = "evaluation_result"
_RESULT_CONTRACT_VERSION = "0.2.0"
_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"
_UNSAFE_METRIC_ID = "unsafe_exclusion"
_UNSAFE_CI_METHOD = "wilson_one_sided_stratified"
_UNSAFE_MEASURE = "weighted_upper_confidence_bound"

GateOperator = Literal["less_than_or_equal", "greater_than_or_equal"]

_INVALID_ISSUE_CODES = frozenset({
    "artifact_missing", "artifact_malformed", "artifact_binding_invalid",
    "gate_policy_invalid", "metric_selection_invalid", "result_contract_invalid",
})
_ERRORED_ISSUE_CODES = frozenset({"runtime_failure"})


class _Slice10StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _require_non_blank(value: str, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(
            f"{field_name} must be a non-empty string without leading or trailing whitespace"
        )
    return value


def _require_finite_number(value: Any, field_name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a non-bool int or float")
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")
    return value


def _is_lower_hex64(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


# --- Public output models -------------------------------------------------


class GateOutcome(_Slice10StrictModel):
    """One evaluated metric gate outcome."""

    gate_reference_id: str
    metric_id: str
    population_slice_id: str
    dimensions: tuple[MetricDimension, ...]
    blocking_severity: str
    operator: GateOperator
    threshold_value: int | float
    observed_value: int | float | None = None
    outcome: GateVerdict
    support: MetricSupport
    confidence_interval: ConfidenceInterval | None = None
    reason_code: str | None = None

    @model_validator(mode="after")
    def _outcome_invariants(self) -> "GateOutcome":
        _require_non_blank(self.gate_reference_id, "gate_reference_id")
        _require_non_blank(self.metric_id, "metric_id")
        _require_non_blank(self.population_slice_id, "population_slice_id")
        _require_non_blank(self.blocking_severity, "blocking_severity")
        _require_finite_number(self.threshold_value, "threshold_value")
        keys = tuple(d.key for d in self.dimensions)
        pairs = [(d.key, d.value) for d in self.dimensions]
        if pairs != sorted(pairs):
            raise ValueError("dimensions must be sorted by (key, value)")
        if len(keys) != len(set(keys)):
            raise ValueError("dimensions must not contain a duplicate key")
        if self.observed_value is not None:
            _require_finite_number(self.observed_value, "observed_value")
        if self.outcome == "indeterminate":
            if self.observed_value is not None:
                raise ValueError("an indeterminate gate outcome must have observed_value None")
            if not self.reason_code or self.reason_code.strip() == "":
                raise ValueError("an indeterminate gate outcome requires a non-blank reason_code")
        else:
            if self.observed_value is None:
                raise ValueError("a pass/fail gate outcome requires an observed_value")
            if self.reason_code is not None:
                raise ValueError("a pass/fail gate outcome must not carry a reason_code")
        return self


class EvaluationIssue(_Slice10StrictModel):
    """One sanitized invalidity/runtime issue; never carries a raw exception."""

    issue_code: str
    message: str
    artifact_reference: str | None = None

    @model_validator(mode="after")
    def _issue_invariants(self) -> "EvaluationIssue":
        _require_non_blank(self.issue_code, "issue_code")
        _require_non_blank(self.message, "message")
        ref = self.artifact_reference
        if ref is not None:
            if ref == "" or ref != ref.strip():
                raise ValueError("artifact_reference must be non-blank")
            if ref.startswith("/") or "\\" in ref or "\x00" in ref or "\n" in ref:
                raise ValueError("artifact_reference must be a normalized relative logical reference")
            parts = ref.split("/")
            if any(p in (".", "..") for p in parts):
                raise ValueError("artifact_reference must not contain '.' or '..' components")
        return self


class PersistedEvaluationResult(_Slice10StrictModel):
    eval_run_id: str
    artifact_reference: Literal["results/evaluation_result.json"]
    sha256: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    result: EvaluationResultV2


class LoadedEvaluationResult(_Slice10StrictModel):
    eval_run_id: str
    artifact_reference: Literal["results/evaluation_result.json"]
    sha256: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    result: EvaluationResultV2


# --- Private executable-policy models -------------------------------------


class _DimensionSelector(_Slice10StrictModel):
    dimensions: tuple[tuple[str, str], ...]

    @model_validator(mode="after")
    def _selector_invariants(self) -> "_DimensionSelector":
        if not self.dimensions:
            raise ValueError("selector dimensions must be non-empty")
        keys = [k for k, _ in self.dimensions]
        for k, v in self.dimensions:
            _require_non_blank(k, "dimension key")
            _require_non_blank(v, "dimension value")
        if len(keys) != len(set(keys)):
            raise ValueError("selector dimensions must not contain a duplicate key")
        return self

    @property
    def as_mapping(self) -> dict[str, str]:
        return dict(self.dimensions)


class _ExecutableGate(_Slice10StrictModel):
    reference_id: str
    metric_id: str
    population_slice_id: str
    blocking_severity: str
    operator: GateOperator
    threshold_value: int | float
    minimum_support: int
    selector: _DimensionSelector
    is_unsafe: bool
    confidence_level: float | None = None


# --- Exceptions -----------------------------------------------------------


class GateEvaluationError(Exception):
    """Base class for Slice 10 gate failures; never raised directly."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
        gate_reference_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.eval_run_id = eval_run_id
        self.artifact_reference = artifact_reference
        self.gate_reference_id = gate_reference_id


class GatePolicyError(GateEvaluationError):
    """An executable gate policy is malformed or inconsistent."""


class GateMetricSelectionError(GateEvaluationError):
    """A gate selects zero, multiple, or an inconsistent MetricDatum."""

    def __init__(self, message: str, *, candidate_count: int | None = None, **kw: Any) -> None:
        super().__init__(message, **kw)
        self.candidate_count = candidate_count


class GateRunBindingError(GateEvaluationError):
    """Run identity does not bind consistently."""


class GateCaseSetBindingError(GateEvaluationError):
    """Case-set version/hash does not bind to the run manifest."""


class GateScoringConfigBindingError(GateEvaluationError):
    """Scoring-config wrapper/inner/version/hash does not bind."""


class GateMetricReportBindingError(GateEvaluationError):
    """Metric-report identity does not bind to the run/case-set/config."""


class GateApplicabilityBindingError(GateEvaluationError):
    """A gate targets a metric family the v0.2 report marks inapplicable.

    Raised before datum selection, support checks, outcome generation, or verdict
    derivation — it is a binding error, never a ``GateMetricSelectionError``, an
    ``indeterminate`` outcome, or a pass/fail verdict. Carries safe, machine-
    readable metadata (family, applicability state, governed ledger reason code)
    with no raw source text or evidence content.
    """

    def __init__(
        self, message: str, *, metric_family: str | None = None,
        applicability_state: str | None = None, reason_code: str | None = None, **kw: Any,
    ) -> None:
        super().__init__(message, **kw)
        self.metric_family = metric_family
        self.applicability_state = applicability_state
        self.reason_code = reason_code


class GateFindingsBindingError(GateEvaluationError):
    """Validator-finding identity does not bind to the run."""


class EvaluationResultExistsError(GateEvaluationError):
    """The results output directory already exists in some form."""


class EvaluationResultArtifactMissingError(GateEvaluationError):
    """A required result artifact does not exist."""


class EvaluationResultArtifactNotAFileError(GateEvaluationError):
    """A result artifact or a parent is not a regular file/directory."""


class EvaluationResultArtifactReadError(GateEvaluationError):
    """Reading a result artifact failed."""


class EvaluationResultDecodeError(GateEvaluationError):
    """A result artifact's bytes are not valid UTF-8."""


class EvaluationResultJsonError(GateEvaluationError):
    """A result artifact is not acceptable strict JSON."""

    def __init__(
        self, message: str, *, duplicate_key: str | None = None,
        constant_name: str | None = None, **kw: Any,
    ) -> None:
        super().__init__(message, **kw)
        self.duplicate_key = duplicate_key
        self.constant_name = constant_name


class EvaluationResultTopLevelTypeError(GateEvaluationError):
    """A parsed result is not a JSON object."""

    def __init__(self, message: str, *, observed_type: str | None = None, **kw: Any) -> None:
        super().__init__(message, **kw)
        self.observed_type = observed_type


class EvaluationResultModelValidationError(GateEvaluationError):
    """A result failed EvaluationResultV2 model validation."""

    def __init__(
        self, message: str, *, field_locations: tuple[str, ...] = (),
        error_types: tuple[str, ...] = (), **kw: Any,
    ) -> None:
        super().__init__(message, **kw)
        self.field_locations = field_locations
        self.error_types = error_types


class EvaluationResultSchemaValidationError(GateEvaluationError):
    """A serialized result failed evaluation_result@0.2.0 schema validation."""

    def __init__(self, message: str, *, schema_messages: tuple[str, ...] = (), **kw: Any) -> None:
        super().__init__(message, **kw)
        self.schema_messages = schema_messages


class EvaluationResultBindingError(GateEvaluationError):
    """A result's run/dataset/provenance/projection identity does not bind."""


class EvaluationResultWriteError(GateEvaluationError):
    """Writing a result artifact failed."""


class EvaluationResultDestinationHashMismatchError(GateEvaluationError):
    """A written result artifact re-read to a different hash."""

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


# --- Policy parsing -------------------------------------------------------


def _require_int(value: Any, *, minimum: int, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GatePolicyError(f"{what} must be an integer")
    if value < minimum:
        raise GatePolicyError(f"{what} must be >= {minimum}")
    return value


def _parse_operator(threshold: dict[str, Any], *, allowed: tuple[str, ...]) -> GateOperator:
    op = threshold.get("operator")
    if op not in allowed:
        raise GatePolicyError(f"gate operator must be one of {allowed!r}")
    return op  # type: ignore[return-value]


def _parse_gate(gate: GateDefinition, config: ScoringGateConfig) -> _ExecutableGate:
    if gate.blocking_severity not in set(config.blocking_severities):
        raise GatePolicyError(
            f"gate {gate.reference_id!r} blocking_severity {gate.blocking_severity!r} is not a "
            "declared blocking severity", gate_reference_id=gate.reference_id,
        )
    is_unsafe = gate.metric_id == _UNSAFE_METRIC_ID
    # Support grammar.
    support = gate.verified_support_requirement
    if is_unsafe:
        if set(support) != {"minimum_audited_per_stratum"}:
            raise GatePolicyError(
                "unsafe gate verified_support_requirement must be exactly "
                "{minimum_audited_per_stratum}", gate_reference_id=gate.reference_id,
            )
        minimum_support = _require_int(
            support["minimum_audited_per_stratum"], minimum=1, what="minimum_audited_per_stratum"
        )
    else:
        if set(support) != {"minimum_verified_support"}:
            raise GatePolicyError(
                "ordinary gate verified_support_requirement must be exactly "
                "{minimum_verified_support}", gate_reference_id=gate.reference_id,
            )
        minimum_support = _require_int(
            support["minimum_verified_support"], minimum=0, what="minimum_verified_support"
        )
    # Threshold grammar.
    thr = gate.threshold
    confidence_level: float | None = None
    if is_unsafe:
        if set(thr) != {"operator", "value", "confidence_level"}:
            raise GatePolicyError(
                "unsafe gate threshold must be exactly {operator, value, confidence_level}",
                gate_reference_id=gate.reference_id,
            )
        operator = _parse_operator(thr, allowed=("less_than_or_equal",))
        level = thr["confidence_level"]
        if isinstance(level, bool) or not isinstance(level, float) or not math.isfinite(level) \
                or not (0.5 < level < 1.0):
            raise GatePolicyError(
                "unsafe gate confidence_level must be a finite float strictly between 0.5 and 1.0",
                gate_reference_id=gate.reference_id,
            )
        confidence_level = level
        if gate.ci_method_reference != _UNSAFE_CI_METHOD:
            raise GatePolicyError(
                f"unsafe gate ci_method_reference must be {_UNSAFE_CI_METHOD!r}",
                gate_reference_id=gate.reference_id,
            )
    else:
        if set(thr) != {"operator", "value"}:
            raise GatePolicyError(
                "ordinary gate threshold must be exactly {operator, value}",
                gate_reference_id=gate.reference_id,
            )
        operator = _parse_operator(thr, allowed=("less_than_or_equal", "greater_than_or_equal"))
    value = thr["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise GatePolicyError("gate threshold value must be a finite non-bool number",
                              gate_reference_id=gate.reference_id)
    # Selector grammar.
    if len(gate.slice_definitions) != 1:
        raise GatePolicyError("a gate must declare exactly one slice_definitions entry",
                              gate_reference_id=gate.reference_id)
    entry = gate.slice_definitions[0]
    if set(entry) != {"dimensions"}:
        raise GatePolicyError("a gate slice_definitions entry must have exactly the 'dimensions' key",
                              gate_reference_id=gate.reference_id)
    dims_obj = entry["dimensions"]
    if not isinstance(dims_obj, dict) or not dims_obj:
        raise GatePolicyError("gate selector dimensions must be a non-empty object",
                              gate_reference_id=gate.reference_id)
    for k, v in dims_obj.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise GatePolicyError("gate selector dimensions must be a string-to-string mapping",
                                  gate_reference_id=gate.reference_id)
    try:
        selector = _DimensionSelector(dimensions=tuple(sorted(dims_obj.items())))
    except (PydanticValidationError, ValueError) as exc:
        raise GatePolicyError(f"gate {gate.reference_id!r} has an invalid selector",
                              gate_reference_id=gate.reference_id) from exc
    if is_unsafe:
        expected = {"measure": _UNSAFE_MEASURE, "scope": "overall"}
        if gate.population_slice_id != "overall" or selector.as_mapping != expected:
            raise GatePolicyError(
                "unsafe gate must select population_slice_id 'overall' with dimensions "
                f"{expected!r}", gate_reference_id=gate.reference_id,
            )
    return _ExecutableGate(
        reference_id=gate.reference_id, metric_id=gate.metric_id,
        population_slice_id=gate.population_slice_id, blocking_severity=gate.blocking_severity,
        operator=operator, threshold_value=value, minimum_support=minimum_support,
        selector=selector, is_unsafe=is_unsafe, confidence_level=confidence_level,
    )


# --- Datum selection + evaluation -----------------------------------------


def _datum_dims(datum: MetricDatum) -> dict[str, str]:
    return {d.key: d.value for d in datum.dimensions}


def _select_datum(
    gate: _ExecutableGate, report: "MetricReport | MetricReportV2"
) -> MetricDatum:
    want = gate.selector.as_mapping
    candidates = [
        d for d in report.metrics
        if d.metric_id == gate.metric_id
        and d.population_slice_id == gate.population_slice_id
        and d.configuration_role == "gate_input"
        and _datum_dims(d) == want
    ]
    if len(candidates) == 0:
        raise GateMetricSelectionError(
            f"gate {gate.reference_id!r} selects no gate-input MetricDatum",
            candidate_count=0, gate_reference_id=gate.reference_id,
        )
    if len(candidates) > 1:
        raise GateMetricSelectionError(
            f"gate {gate.reference_id!r} selects multiple MetricData",
            candidate_count=len(candidates), gate_reference_id=gate.reference_id,
        )
    datum = candidates[0]
    dims = _datum_dims(datum)
    if "verification" in dims and dims["verification"] != "verified":
        raise GateMetricSelectionError(
            f"gate {gate.reference_id!r} selected a non-verified datum",
            gate_reference_id=gate.reference_id,
        )
    return datum


def _evaluate_gate(gate: _ExecutableGate, datum: MetricDatum) -> GateOutcome:
    # Support consistency.
    if datum.support.minimum_verified_support != gate.minimum_support:
        raise GateMetricSelectionError(
            f"gate {gate.reference_id!r} datum minimum support does not equal the configured "
            "minimum", gate_reference_id=gate.reference_id,
        )
    if gate.is_unsafe:
        return _evaluate_unsafe_gate(gate, datum)
    return _evaluate_ordinary_gate(gate, datum)


def _base_outcome_kwargs(gate: _ExecutableGate, datum: MetricDatum) -> dict[str, Any]:
    return {
        "gate_reference_id": gate.reference_id,
        "metric_id": gate.metric_id,
        "population_slice_id": gate.population_slice_id,
        "dimensions": datum.dimensions,
        "blocking_severity": gate.blocking_severity,
        "operator": gate.operator,
        "threshold_value": gate.threshold_value,
        "support": datum.support,
    }


def _evaluate_ordinary_gate(gate: _ExecutableGate, datum: MetricDatum) -> GateOutcome:
    if datum.status == "indeterminate":
        if datum.value is not None:
            raise GateMetricSelectionError(
                f"gate {gate.reference_id!r} indeterminate datum carries a value",
                gate_reference_id=gate.reference_id,
            )
        if not datum.reason_code:
            raise GateMetricSelectionError(
                f"gate {gate.reference_id!r} indeterminate datum lacks a reason code",
                gate_reference_id=gate.reference_id,
            )
        if datum.reason_code == "insufficient_evaluation_evidence" \
                and datum.support.verified_support >= gate.minimum_support:
            raise GateMetricSelectionError(
                f"gate {gate.reference_id!r} claims insufficient evidence with sufficient support",
                gate_reference_id=gate.reference_id,
            )
        return GateOutcome(**_base_outcome_kwargs(gate, datum), observed_value=None,
                           outcome="indeterminate", confidence_interval=datum.confidence_interval,
                           reason_code=datum.reason_code)
    # Computed.
    if datum.value is None or isinstance(datum.value, bool) or not isinstance(datum.value, (int, float)) \
            or not math.isfinite(datum.value):
        raise GateMetricSelectionError(
            f"gate {gate.reference_id!r} computed datum has a non-finite/non-numeric value",
            gate_reference_id=gate.reference_id,
        )
    if datum.reason_code is not None:
        raise GateMetricSelectionError(
            f"gate {gate.reference_id!r} computed datum carries a reason code",
            gate_reference_id=gate.reference_id,
        )
    if datum.support.verified_support < gate.minimum_support:
        raise GateMetricSelectionError(
            f"gate {gate.reference_id!r} computed datum has verified support below the minimum",
            gate_reference_id=gate.reference_id,
        )
    passed = (datum.value <= gate.threshold_value) if gate.operator == "less_than_or_equal" \
        else (datum.value >= gate.threshold_value)
    return GateOutcome(**_base_outcome_kwargs(gate, datum), observed_value=datum.value,
                       outcome="pass" if passed else "fail",
                       confidence_interval=datum.confidence_interval, reason_code=None)


def _evaluate_unsafe_gate(gate: _ExecutableGate, datum: MetricDatum) -> GateOutcome:
    ci = datum.confidence_interval
    if datum.status == "indeterminate":
        if datum.value is not None or not datum.reason_code:
            raise GateMetricSelectionError(
                f"gate {gate.reference_id!r} unsafe indeterminate datum is malformed",
                gate_reference_id=gate.reference_id,
            )
        if ci is not None and (ci.method != _UNSAFE_CI_METHOD or ci.confidence_level != gate.confidence_level):
            raise GateMetricSelectionError(
                f"gate {gate.reference_id!r} unsafe datum CI is inconsistent with policy",
                gate_reference_id=gate.reference_id,
            )
        return GateOutcome(**_base_outcome_kwargs(gate, datum), observed_value=None,
                           outcome="indeterminate", confidence_interval=ci,
                           reason_code=datum.reason_code)
    # Computed unsafe datum.
    if ci is None:
        raise GateMetricSelectionError(
            f"gate {gate.reference_id!r} computed unsafe datum lacks a confidence interval",
            gate_reference_id=gate.reference_id,
        )
    if datum.value is None or isinstance(datum.value, bool) or not isinstance(datum.value, (int, float)) \
            or not math.isfinite(datum.value):
        raise GateMetricSelectionError(
            f"gate {gate.reference_id!r} unsafe datum value is non-finite/non-numeric",
            gate_reference_id=gate.reference_id,
        )
    if datum.value != ci.upper:
        raise GateMetricSelectionError(
            f"gate {gate.reference_id!r} unsafe datum value does not equal its CI upper bound",
            gate_reference_id=gate.reference_id,
        )
    if ci.method != _UNSAFE_CI_METHOD:
        raise GateMetricSelectionError(
            f"gate {gate.reference_id!r} unsafe datum CI method is not {_UNSAFE_CI_METHOD!r}",
            gate_reference_id=gate.reference_id,
        )
    if ci.confidence_level != gate.confidence_level:
        raise GateMetricSelectionError(
            f"gate {gate.reference_id!r} unsafe datum confidence level does not match policy",
            gate_reference_id=gate.reference_id,
        )
    passed = datum.value <= gate.threshold_value  # operator is fixed to less_than_or_equal
    return GateOutcome(**_base_outcome_kwargs(gate, datum), observed_value=datum.value,
                       outcome="pass" if passed else "fail", confidence_interval=ci,
                       reason_code=None)


def _derive_verdict(critical_finding_ids: tuple[str, ...],
                    outcomes: tuple[GateOutcome, ...]) -> GateVerdict:
    if critical_finding_ids:
        return "fail"
    if any(o.outcome == "fail" for o in outcomes):
        return "fail"
    if any(o.outcome == "indeterminate" for o in outcomes):
        return "indeterminate"
    return "pass"


# --- Run-manifest version dispatch (ADR-027) ------------------------------
#
# The gate layer accepts either governed run-manifest version across its whole
# build/persist/load path. It reads only the five fields v0.1 and v0.2 share --
# eval_run_id, case_set_version, case_set_hash, scoring_gate_config_version, and
# scoring_gate_config_hash -- so the projection, EvaluationResultV2, and
# evaluation_result.v2.schema.json are untouched and every v0.1 path, behaviour,
# and error code is preserved exactly.

_AnyRunManifest = EvaluationRunManifest | EvaluationRunManifestV2
_RUN_MANIFEST_MODEL_VERSIONS: dict[type, str] = {
    EvaluationRunManifest: "0.1.0",
    EvaluationRunManifestV2: "0.2.0",
}
# Stable message identifiers. The general gate error classes carry no
# reason_code field, so these ride their existing classes verbatim in the
# message and callers match on the identifier.
_RUN_MANIFEST_VERSION_INCONSISTENT = "run_manifest_version_inconsistent"
_METRIC_REPORT_VERSION_MISMATCH = "metric_report_version_mismatch"


def _require_supported_run_manifest(name: str, run_manifest: Any) -> _AnyRunManifest:
    """Accept exactly one of the two governed manifest classes.

    The concrete class must be an exact key of ``_RUN_MANIFEST_MODEL_VERSIONS`` --
    the same table the declared-version check indexes -- so acceptance and lookup
    cannot diverge. ``isinstance`` would admit a subclass that has no exact key and
    would surface as an uncontrolled ``KeyError`` instead of this boundary.
    """
    if type(run_manifest) not in _RUN_MANIFEST_MODEL_VERSIONS:
        raise TypeError(
            f"{name} must be an EvaluationRunManifest or EvaluationRunManifestV2, "
            f"got {type(run_manifest).__name__}"
        )
    return run_manifest


def _require_run_manifest_version_consistency(m: _AnyRunManifest) -> None:
    """The concrete model class and the declared contract version must agree.

    ``model_copy(update=...)`` and ``model_construct`` can produce an instance
    whose declared ``contract.contract_version`` disagrees with its own class, so
    the gate layer refuses to read shared fields off such an object.
    """
    expected = _RUN_MANIFEST_MODEL_VERSIONS[type(m)]
    if m.contract.contract_version != expected:
        raise GateRunBindingError(
            f"{_RUN_MANIFEST_VERSION_INCONSISTENT}: run manifest model "
            f"{type(m).__name__} declares contract version "
            f"{m.contract.contract_version!r}, expected {expected!r}",
            eval_run_id=m.eval_run_id,
        )


def _require_metric_report_version_for_run(
    loaded: "LoadedMetricReport | _LoadedMetricReportV2", m: _AnyRunManifest
) -> None:
    """A v0.2 run may bind only metric_report@0.2.0.

    A v0.1 run keeps accepting either report version, exactly as before.
    """
    if isinstance(m, EvaluationRunManifestV2) and not isinstance(loaded.report, MetricReportV2):
        raise GateMetricReportBindingError(
            f"{_METRIC_REPORT_VERSION_MISMATCH}: an evaluation_run_manifest@0.2.0 run "
            "may bind only metric_report@0.2.0",
            eval_run_id=m.eval_run_id,
            artifact_reference=loaded.artifact_reference,
        )


# --- Binding checks -------------------------------------------------------


def _bind_scoring_config(config: LoadedScoringGateConfig, m: _AnyRunManifest) -> None:
    inner = config.config
    if inner.config_version != m.scoring_gate_config_version:
        raise GateScoringConfigBindingError("scoring config version does not match the run manifest",
                                            eval_run_id=m.eval_run_id)
    if config.version != inner.config_version:
        raise GateScoringConfigBindingError("scoring config wrapper version does not match its inner "
                                            "config version", eval_run_id=m.eval_run_id)
    if config.sha256 != m.scoring_gate_config_hash:
        raise GateScoringConfigBindingError("scoring config artifact hash does not match the manifest",
                                            eval_run_id=m.eval_run_id)


def _bind_case_set(case_set: CaseSetManifest, m: _AnyRunManifest) -> None:
    if case_set.case_set_version != m.case_set_version:
        raise GateCaseSetBindingError("case-set manifest version does not match the run manifest",
                                      eval_run_id=m.eval_run_id)
    if case_set_snapshot_hash(case_set) != m.case_set_hash:
        raise GateCaseSetBindingError("case-set manifest snapshot hash does not match the manifest",
                                      eval_run_id=m.eval_run_id)


def _bind_metric_report(loaded: LoadedMetricReport, m: _AnyRunManifest) -> None:
    report = loaded.report
    # Run-identity anchor: the loaded wrapper declares which run the artifact
    # belongs to; that declared run must equal the run-manifest anchor. This
    # wrapper-level identity is distinct from the inner report's own eval_run_id
    # (which the metric-report binding below checks) and is not enforced by the
    # LoadedMetricReport model itself.
    if loaded.eval_run_id != m.eval_run_id:
        raise GateRunBindingError(
            "metric report wrapper eval_run_id does not bind to the run manifest",
            eval_run_id=m.eval_run_id)
    if report.eval_run_id != m.eval_run_id:
        raise GateMetricReportBindingError("metric report eval_run_id does not match the run",
                                           eval_run_id=m.eval_run_id)
    if report.case_set_version != m.case_set_version or report.case_set_hash != m.case_set_hash:
        raise GateMetricReportBindingError("metric report case-set identity does not match the run",
                                           eval_run_id=m.eval_run_id)
    if report.scoring_gate_config_version != m.scoring_gate_config_version \
            or report.scoring_gate_config_hash != m.scoring_gate_config_hash:
        raise GateMetricReportBindingError("metric report scoring-config identity does not match",
                                           eval_run_id=m.eval_run_id)
    if not _is_lower_hex64(loaded.sha256):
        raise GateMetricReportBindingError("metric report sha256 is not a lowercase 64-hex digest",
                                           eval_run_id=m.eval_run_id)


def _bind_findings(findings: LoadedValidatorFindings, m: _AnyRunManifest) -> tuple[str, ...]:
    if findings.eval_run_id != m.eval_run_id:
        raise GateFindingsBindingError("findings wrapper eval_run_id does not match the run",
                                       eval_run_id=m.eval_run_id)
    seen: set[str] = set()
    critical: list[str] = []
    for f in findings.findings:
        if f.run_id != m.eval_run_id:
            raise GateFindingsBindingError("a finding run_id does not match the run",
                                           eval_run_id=m.eval_run_id)
        if f.finding_id in seen:
            raise GateFindingsBindingError(f"duplicate finding_id {f.finding_id!r}",
                                           eval_run_id=m.eval_run_id)
        seen.add(f.finding_id)
        if f.severity == "critical":
            critical.append(f.finding_id)
    return tuple(sorted(set(critical)))


# --- Result assembly ------------------------------------------------------


def _provenance(m: _AnyRunManifest, metric_report_sha256: str | None) -> dict[str, Any]:
    return {
        "case_set_version": m.case_set_version,
        "case_set_hash": m.case_set_hash,
        "scoring_gate_config_version": m.scoring_gate_config_version,
        "scoring_gate_config_hash": m.scoring_gate_config_hash,
        "metric_report_sha256": metric_report_sha256,
    }


def _validate_stage(stage: str) -> str:
    # Locked contract: strict string whose stripped form is non-empty. The
    # original value (including any surrounding whitespace) is preserved exactly
    # once accepted; no normalization or stripping is performed.
    if not isinstance(stage, str) or not stage.strip():
        raise EvaluationResultModelValidationError(
            "stage must be a non-empty string once surrounding whitespace is stripped",
            field_locations=("stage",), error_types=("stage_invalid",),
        )
    return stage


def assess_completed_evaluation(
    *,
    stage: str,
    run_manifest: _AnyRunManifest,
    case_set_manifest: CaseSetManifest,
    scoring_config: LoadedScoringGateConfig,
    metric_report: "LoadedMetricReport | _LoadedMetricReportV2",
    findings: LoadedValidatorFindings,
) -> EvaluationResultV2:
    """Assess a completed evaluation. Pure; raises typed errors on invalid input.

    ``metric_report`` is the v0.1 ``LoadedMetricReport`` or the v0.2 wrapper
    returned by ``load_metric_report_v2``; only a v0.2 report (whose inner report
    is a ``MetricReportV2``) carries the applicability ledger that gates a
    metric-family binding check.
    """
    _require_supported_run_manifest("run_manifest", run_manifest)
    for name, obj, typ in (
        ("case_set_manifest", case_set_manifest, CaseSetManifest),
        ("scoring_config", scoring_config, LoadedScoringGateConfig),
        ("findings", findings, LoadedValidatorFindings),
    ):
        if not isinstance(obj, typ):
            raise TypeError(f"{name} must be a {typ.__name__}, got {type(obj).__name__}")
    if not isinstance(metric_report, (LoadedMetricReport, _LoadedMetricReportV2)):
        raise TypeError(
            f"metric_report must be a LoadedMetricReport or the v0.2 loaded wrapper, "
            f"got {type(metric_report).__name__}")
    stage = _validate_stage(stage)
    m = run_manifest
    _require_run_manifest_version_consistency(m)
    _require_metric_report_version_for_run(metric_report, m)
    _bind_case_set(case_set_manifest, m)
    _bind_scoring_config(scoring_config, m)
    _bind_metric_report(metric_report, m)
    critical_ids = _bind_findings(findings, m)

    # v0.2 only: the applicability ledger's inapplicable families (with their
    # governed reason codes). None for a v0.1 report, which has no ledger, so the
    # legacy gate path is preserved exactly.
    inapplicable_reasons: dict[str, str] | None = None
    if isinstance(metric_report.report, MetricReportV2):
        inapplicable_reasons = {
            e.metric_family: e.reason_code
            for e in metric_report.report.applicability_ledger
            if e.applicability_state == "inapplicable"
        }

    gates = tuple(_parse_gate(g, scoring_config.config) for g in scoring_config.config.gates)
    outcomes: list[GateOutcome] = []
    seen_refs: set[str] = set()
    seen_datum: set[tuple[str, str, tuple[tuple[str, str], ...]]] = set()
    for gate in gates:
        if gate.reference_id in seen_refs:
            raise GatePolicyError(f"duplicate gate reference id {gate.reference_id!r}",
                                  gate_reference_id=gate.reference_id)
        seen_refs.add(gate.reference_id)
        # A gate targeting an inapplicable metric family is a binding error raised
        # strictly before datum selection, support checks, outcomes, or verdict.
        if inapplicable_reasons is not None and gate.metric_id in inapplicable_reasons:
            raise GateApplicabilityBindingError(
                f"gate {gate.reference_id!r} targets an inapplicable metric family",
                eval_run_id=m.eval_run_id,
                artifact_reference=metric_report.artifact_reference,
                gate_reference_id=gate.reference_id, metric_family=gate.metric_id,
                applicability_state="inapplicable",
                reason_code=inapplicable_reasons[gate.metric_id])
        datum = _select_datum(gate, metric_report.report)
        identity = (datum.metric_id, datum.population_slice_id,
                    tuple((d.key, d.value) for d in datum.dimensions))
        if identity in seen_datum:
            raise GateMetricSelectionError(
                f"gate {gate.reference_id!r} selects an already-selected MetricDatum",
                gate_reference_id=gate.reference_id,
            )
        seen_datum.add(identity)
        outcomes.append(_evaluate_gate(gate, datum))
    outcomes.sort(key=lambda o: o.gate_reference_id)
    verdict = _derive_verdict(critical_ids, tuple(outcomes))
    metrics = {
        "provenance": _provenance(m, metric_report.sha256),
        "gate_outcomes": [o.model_dump(mode="json") for o in outcomes],
        "critical_finding_ids": list(critical_ids),
    }
    return EvaluationResultV2.model_validate({
        "eval_run_id": m.eval_run_id, "stage": stage, "dataset_version": m.case_set_version,
        "metrics": metrics, "execution_status": "completed", "gate_verdict": verdict,
    })


def _build_terminal(status: str, allowed_codes: frozenset[str], *, stage: str,
                    run_manifest: _AnyRunManifest, issues: tuple[EvaluationIssue, ...],
                    metric_report_sha256: str | None) -> EvaluationResultV2:
    _require_supported_run_manifest("run_manifest", run_manifest)
    _require_run_manifest_version_consistency(run_manifest)
    stage = _validate_stage(stage)
    run_id = run_manifest.eval_run_id
    if not issues:
        raise EvaluationResultBindingError(f"a {status} result requires at least one issue",
                                           eval_run_id=run_id)
    identities: set[tuple[str, str | None, str]] = set()
    for issue in issues:
        if not isinstance(issue, EvaluationIssue):
            raise TypeError("issues must be EvaluationIssue instances")
        if issue.issue_code not in allowed_codes:
            raise EvaluationResultBindingError(
                f"issue_code {issue.issue_code!r} is not permitted for a {status} result",
                eval_run_id=run_id)
        key = (issue.issue_code, issue.artifact_reference, issue.message)
        if key in identities:
            raise EvaluationResultBindingError("duplicate issue identity", eval_run_id=run_id)
        identities.add(key)
    if metric_report_sha256 is not None and not _is_lower_hex64(metric_report_sha256):
        raise EvaluationResultBindingError(
            "metric_report_sha256 must be a lowercase 64-hex digest or None", eval_run_id=run_id)
    ordered = sorted(
        issues, key=lambda i: (i.issue_code, (i.artifact_reference is not None,
                                              i.artifact_reference or ""), i.message)
    )
    m = run_manifest
    metrics = {
        "provenance": _provenance(m, metric_report_sha256),
        "gate_outcomes": [],
        "critical_finding_ids": [],
    }
    return EvaluationResultV2.model_validate({
        "eval_run_id": m.eval_run_id, "stage": stage, "dataset_version": m.case_set_version,
        "metrics": metrics, "execution_status": status,
        "errors": [i.model_dump(mode="json") for i in ordered],
    })


def build_invalid_evaluation(
    *, stage: str, run_manifest: _AnyRunManifest,
    issues: tuple[EvaluationIssue, ...], metric_report_sha256: str | None = None,
) -> EvaluationResultV2:
    """Construct an invalid EvaluationResultV2 from a valid in-memory run manifest."""
    return _build_terminal("invalid", _INVALID_ISSUE_CODES, stage=stage,
                           run_manifest=run_manifest, issues=issues,
                           metric_report_sha256=metric_report_sha256)


def build_errored_evaluation(
    *, stage: str, run_manifest: _AnyRunManifest,
    issues: tuple[EvaluationIssue, ...], metric_report_sha256: str | None = None,
) -> EvaluationResultV2:
    """Construct an errored EvaluationResultV2 from a valid in-memory run manifest."""
    return _build_terminal("errored", _ERRORED_ISSUE_CODES, stage=stage,
                           run_manifest=run_manifest, issues=issues,
                           metric_report_sha256=metric_report_sha256)


# --- Internal projection validation ---------------------------------------


def _validate_projection(result: EvaluationResultV2, m: _AnyRunManifest,
                         *, reference: str | None, eval_run_id: str) -> None:
    if result.eval_run_id != m.eval_run_id:
        raise EvaluationResultBindingError("result eval_run_id does not match the run manifest",
                                           eval_run_id=eval_run_id, artifact_reference=reference)
    if result.dataset_version != m.case_set_version:
        raise EvaluationResultBindingError("result dataset_version does not equal the case-set "
                                           "version", eval_run_id=eval_run_id,
                                           artifact_reference=reference)
    metrics = result.metrics
    if set(metrics) != {"provenance", "gate_outcomes", "critical_finding_ids"}:
        raise EvaluationResultBindingError("result metrics must have exactly the three locked keys",
                                           eval_run_id=eval_run_id, artifact_reference=reference)
    prov = metrics["provenance"]
    if not isinstance(prov, dict) or set(prov) != {
        "case_set_version", "case_set_hash", "scoring_gate_config_version",
        "scoring_gate_config_hash", "metric_report_sha256",
    }:
        raise EvaluationResultBindingError("result provenance must have exactly the five locked keys",
                                           eval_run_id=eval_run_id, artifact_reference=reference)
    if prov["case_set_version"] != m.case_set_version or prov["case_set_hash"] != m.case_set_hash \
            or prov["scoring_gate_config_version"] != m.scoring_gate_config_version \
            or prov["scoring_gate_config_hash"] != m.scoring_gate_config_hash:
        raise EvaluationResultBindingError("result provenance does not match the run manifest",
                                           eval_run_id=eval_run_id, artifact_reference=reference)
    outcomes_raw = metrics["gate_outcomes"]
    crit_raw = metrics["critical_finding_ids"]
    if not isinstance(outcomes_raw, list) or not isinstance(crit_raw, list):
        raise EvaluationResultBindingError("gate_outcomes and critical_finding_ids must be lists",
                                           eval_run_id=eval_run_id, artifact_reference=reference)
    try:
        outcomes = tuple(GateOutcome.model_validate(o) for o in outcomes_raw)
    except PydanticValidationError as exc:
        raise EvaluationResultBindingError("a gate outcome entry is invalid", eval_run_id=eval_run_id,
                                           artifact_reference=reference) from exc
    if [o.gate_reference_id for o in outcomes] != sorted(o.gate_reference_id for o in outcomes):
        raise EvaluationResultBindingError("gate outcomes must be sorted by reference id",
                                           eval_run_id=eval_run_id, artifact_reference=reference)
    ref_ids = [o.gate_reference_id for o in outcomes]
    if len(ref_ids) != len(set(ref_ids)):
        raise EvaluationResultBindingError("duplicate gate reference id", eval_run_id=eval_run_id,
                                           artifact_reference=reference)
    datum_ids = [(o.metric_id, o.population_slice_id, tuple((d.key, d.value) for d in o.dimensions))
                 for o in outcomes]
    if len(datum_ids) != len(set(datum_ids)):
        raise EvaluationResultBindingError("duplicate selected datum identity",
                                           eval_run_id=eval_run_id, artifact_reference=reference)
    if not all(isinstance(c, str) and c for c in crit_raw):
        raise EvaluationResultBindingError("critical_finding_ids must be non-blank strings",
                                           eval_run_id=eval_run_id, artifact_reference=reference)
    if crit_raw != sorted(set(crit_raw)):
        raise EvaluationResultBindingError("critical_finding_ids must be sorted and unique",
                                           eval_run_id=eval_run_id, artifact_reference=reference)
    prov_hash = prov["metric_report_sha256"]
    if result.execution_status == "completed":
        if "errors" in result.model_fields_set:
            raise EvaluationResultBindingError("a completed result must omit errors",
                                               eval_run_id=eval_run_id, artifact_reference=reference)
        if not _is_lower_hex64(prov_hash):
            raise EvaluationResultBindingError("a completed result requires a hex metric-report hash",
                                               eval_run_id=eval_run_id, artifact_reference=reference)
        if result.gate_verdict != _derive_verdict(tuple(crit_raw), outcomes):
            raise EvaluationResultBindingError("stored gate_verdict does not match the recomputed "
                                               "verdict", eval_run_id=eval_run_id,
                                               artifact_reference=reference)
    else:
        if result.gate_verdict is not None:
            raise EvaluationResultBindingError("a non-completed result must omit gate_verdict",
                                               eval_run_id=eval_run_id, artifact_reference=reference)
        if outcomes or crit_raw:
            raise EvaluationResultBindingError("a non-completed result must have empty gate outcomes "
                                               "and critical IDs", eval_run_id=eval_run_id,
                                               artifact_reference=reference)
        if prov_hash is not None and not _is_lower_hex64(prov_hash):
            raise EvaluationResultBindingError("metric_report_sha256 must be null or a hex digest",
                                               eval_run_id=eval_run_id, artifact_reference=reference)
        errors = result.errors
        if not errors:
            raise EvaluationResultBindingError("a non-completed result requires issues",
                                               eval_run_id=eval_run_id, artifact_reference=reference)
        allowed = _INVALID_ISSUE_CODES if result.execution_status == "invalid" else _ERRORED_ISSUE_CODES
        try:
            issues = tuple(EvaluationIssue.model_validate(e) for e in errors)
        except PydanticValidationError as exc:
            raise EvaluationResultBindingError("an issue entry is invalid", eval_run_id=eval_run_id,
                                               artifact_reference=reference) from exc
        if any(i.issue_code not in allowed for i in issues):
            raise EvaluationResultBindingError("an issue code is not permitted for this status",
                                               eval_run_id=eval_run_id, artifact_reference=reference)


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


def _serialized(result: EvaluationResultV2) -> dict[str, Any]:
    return result.model_dump(mode="json", exclude_unset=True)


def _schema_validate(payload: dict[str, Any], *, eval_run_id: str,
                     reference: str | None) -> None:
    schema = dict(load_schema(_RESULT_CONTRACT_ID, _RESULT_CONTRACT_VERSION, purpose="write"))
    messages = tuple(sorted(e.message for e in Draft202012Validator(schema).iter_errors(payload)))
    if messages:
        raise EvaluationResultSchemaValidationError(
            "serialized evaluation result failed schema validation", schema_messages=messages,
            eval_run_id=eval_run_id, artifact_reference=reference,
        )


def persist_evaluation_result(
    result: EvaluationResultV2, *, eval_root: str | Path, eval_run_id: str,
) -> PersistedEvaluationResult:
    """Persist an evaluation result as write-once JSON in the run dir."""
    if not isinstance(result, EvaluationResultV2):
        raise TypeError(f"result must be an EvaluationResultV2, got {type(result).__name__}")
    resolved_root = _validate_root(eval_root)
    loaded = _load_run_manifest_any_supported_version(eval_run_id, eval_root=resolved_root)
    m = loaded.manifest
    _require_run_manifest_version_consistency(m)
    reference = _ARTIFACT_REFERENCE
    if result.eval_run_id != m.eval_run_id:
        raise EvaluationResultBindingError("result eval_run_id does not match the run manifest",
                                           eval_run_id=m.eval_run_id, artifact_reference=reference)
    _validate_projection(result, m, reference=reference, eval_run_id=m.eval_run_id)
    payload = _serialized(result)
    _schema_validate(payload, eval_run_id=m.eval_run_id, reference=reference)
    data = canonical_contract_bytes(payload) + b"\n"
    expected = sha256_bytes(data)

    results_dir = resolved_root / eval_run_id / _RESULTS_DIR
    if results_dir.exists() or results_dir.is_symlink():
        raise EvaluationResultExistsError(f"results directory {eval_run_id}/{_RESULTS_DIR} already "
                                          "exists", eval_run_id=eval_run_id,
                                          artifact_reference=f"{eval_run_id}/{_RESULTS_DIR}")
    try:
        results_dir.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise EvaluationResultExistsError(f"results directory {eval_run_id}/{_RESULTS_DIR} already "
                                          "exists", eval_run_id=eval_run_id,
                                          artifact_reference=f"{eval_run_id}/{_RESULTS_DIR}") from exc
    except OSError as exc:
        raise EvaluationResultWriteError(f"failed to create results directory for {eval_run_id!r}",
                                         eval_run_id=eval_run_id) from exc
    dest = results_dir / _RESULTS_FILENAME
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise EvaluationResultExistsError(f"result artifact {reference!r} already exists; write-once",
                                          eval_run_id=eval_run_id, artifact_reference=reference) from exc
    except OSError as exc:
        raise EvaluationResultWriteError(f"failed to create result artifact {reference!r}",
                                         eval_run_id=eval_run_id, artifact_reference=reference) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise EvaluationResultWriteError(f"failed to write result artifact {reference!r}",
                                         eval_run_id=eval_run_id, artifact_reference=reference) from exc
    try:
        observed = sha256_bytes(dest.read_bytes())
    except OSError as exc:
        raise EvaluationResultWriteError(f"failed to re-read result artifact {reference!r}",
                                         eval_run_id=eval_run_id, artifact_reference=reference) from exc
    if observed != expected:
        raise EvaluationResultDestinationHashMismatchError(
            f"written result artifact {reference!r} re-read to a different hash",
            eval_run_id=eval_run_id, artifact_reference=reference,
            expected_sha256=expected, observed_sha256=observed,
        )
    return PersistedEvaluationResult(eval_run_id=eval_run_id, artifact_reference=_ARTIFACT_REFERENCE,
                                     sha256=expected, result=result)


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


def load_evaluation_result(
    eval_run_id: str, *, eval_root: str | Path,
) -> LoadedEvaluationResult:
    """Load an evaluation result from the fixed run-directory path."""
    resolved_root = _validate_root(eval_root)
    loaded_run = _load_run_manifest_any_supported_version(eval_run_id, eval_root=resolved_root)
    m = loaded_run.manifest
    _require_run_manifest_version_consistency(m)
    run_dir = resolved_root / eval_run_id
    results_dir = run_dir / _RESULTS_DIR
    reference = _ARTIFACT_REFERENCE
    dest = results_dir / _RESULTS_FILENAME
    if run_dir.is_symlink() or results_dir.is_symlink() or dest.is_symlink():
        raise EvaluationResultArtifactNotAFileError(f"result artifact {reference!r} or a parent is a "
                                                    "symlink", eval_run_id=eval_run_id,
                                                    artifact_reference=reference)
    if not dest.exists():
        raise EvaluationResultArtifactMissingError(f"result artifact {reference!r} does not exist",
                                                   eval_run_id=eval_run_id,
                                                   artifact_reference=reference)
    if not dest.is_file():
        raise EvaluationResultArtifactNotAFileError(f"result artifact {reference!r} is not a regular "
                                                    "file", eval_run_id=eval_run_id,
                                                    artifact_reference=reference)
    try:
        raw = dest.read_bytes()
    except OSError as exc:
        raise EvaluationResultArtifactReadError(f"failed to read result artifact {reference!r}",
                                                eval_run_id=eval_run_id,
                                                artifact_reference=reference) from exc
    observed = sha256_bytes(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvaluationResultDecodeError(f"result artifact {reference!r} is not valid UTF-8",
                                          eval_run_id=eval_run_id,
                                          artifact_reference=reference) from exc
    if text.startswith("\ufeff"):
        raise EvaluationResultJsonError(f"result artifact {reference!r} has a UTF-8 BOM",
                                        eval_run_id=eval_run_id, artifact_reference=reference)
    try:
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_keys,
                             parse_constant=_reject_non_finite_constant)
    except json.JSONDecodeError as exc:
        raise EvaluationResultJsonError(f"result artifact {reference!r} is not valid JSON: {exc.msg}",
                                        eval_run_id=eval_run_id, artifact_reference=reference) from exc
    except _DuplicateKeyControl as exc:
        raise EvaluationResultJsonError(f"result artifact {reference!r} has duplicate key {exc.key!r}",
                                        eval_run_id=eval_run_id, artifact_reference=reference,
                                        duplicate_key=exc.key) from exc
    except _NonFiniteControl as exc:
        raise EvaluationResultJsonError(f"result artifact {reference!r} has non-JSON constant "
                                        f"{exc.constant_name}", eval_run_id=eval_run_id,
                                        artifact_reference=reference,
                                        constant_name=exc.constant_name) from exc
    non_finite = _first_non_finite(payload)
    if non_finite is not None:
        raise EvaluationResultJsonError(f"result artifact {reference!r} has non-finite number "
                                        f"({non_finite})", eval_run_id=eval_run_id,
                                        artifact_reference=reference, constant_name=non_finite)
    if not isinstance(payload, dict):
        raise EvaluationResultTopLevelTypeError(f"result artifact {reference!r} is not a JSON object",
                                                eval_run_id=eval_run_id, artifact_reference=reference,
                                                observed_type=type(payload).__name__)
    try:
        result = EvaluationResultV2.model_validate(payload)
    except PydanticValidationError as exc:
        pairs = sorted(("/".join(str(p) for p in e["loc"]), e["type"]) for e in exc.errors())
        raise EvaluationResultModelValidationError(
            f"result artifact {reference!r} failed EvaluationResultV2 validation",
            eval_run_id=eval_run_id, artifact_reference=reference,
            field_locations=tuple(loc for loc, _ in pairs),
            error_types=tuple(t for _, t in pairs),
        ) from exc
    _schema_validate(payload, eval_run_id=eval_run_id, reference=reference)
    _validate_projection(result, m, reference=reference, eval_run_id=eval_run_id)
    return LoadedEvaluationResult(eval_run_id=eval_run_id, artifact_reference=_ARTIFACT_REFERENCE,
                                  sha256=observed, result=result)
