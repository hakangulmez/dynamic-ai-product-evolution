"""Scoring/gate configuration loading and structural validation (Slice 4).

Read-side plus pure validation only: load one immutable scoring/gate
configuration under an explicit evaluation root with the strict parsing
discipline of the earlier slices, compute raw-byte binding material, and
validate the configuration's structural and definitional consistency.

Numeric thresholds, support requirements, and slice definitions are opaque
JSON objects preserved verbatim as validated model data; Slice 4 supplies no
policy default and evaluates no metric, gate, threshold, or verdict. Reference
IDs identify gates and diagnostics; metric IDs and population/slice IDs may
repeat legitimately.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError as PydanticValidationError,
    field_validator,
)

from .cases import InvalidEvaluationRootError
from .references import (
    BlockingResolutionError,
    RULE_IDS,
    ResolutionFailureKind,
    ResolutionFinding,
)
from ..universe.io_utils import sha256_bytes

_IDENTITY_PATTERN = r"^\S(.*\S)?$"


class _Slice4ConfigModel(BaseModel):
    """Strict, immutable base for all Slice 4 scoring-config models."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _blocking(
    failure_kind: ResolutionFailureKind, message: str, **attrs: Any
) -> BlockingResolutionError:
    return BlockingResolutionError(
        ResolutionFinding(
            failure_kind=failure_kind,
            rule_id=RULE_IDS[failure_kind],
            message=message,
            **attrs,
        )
    )


def _require_finite(value: Any) -> None:
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, float) and not math.isfinite(current):
            raise ValueError("numeric values must be finite")
        elif isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, (list, tuple)):
            stack.extend(current)


def _require_nonempty_object(value: Any) -> dict[str, JsonValue]:
    if not isinstance(value, dict) or not value:
        raise ValueError("must be a non-empty JSON object")
    _require_finite(value)
    return value


# --- Scoring/gate configuration artifact models --------------------------


class GateDefinition(_Slice4ConfigModel):
    """One blocking gate definition; opaque numeric structures are preserved."""

    reference_id: str = Field(pattern=_IDENTITY_PATTERN)
    metric_id: str = Field(pattern=_IDENTITY_PATTERN)
    population_slice_id: str = Field(pattern=_IDENTITY_PATTERN)
    verified_support_requirement: dict[str, JsonValue]
    ci_method_reference: str | None = None
    blocking_severity: str = Field(pattern=_IDENTITY_PATTERN)
    protected_regression_class_references: tuple[str, ...]
    slice_definitions: tuple[dict[str, JsonValue], ...]
    threshold: dict[str, JsonValue]

    @field_validator("verified_support_requirement", "threshold")
    @classmethod
    def _nonempty(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return _require_nonempty_object(value)

    @field_validator("slice_definitions")
    @classmethod
    def _nonempty_slices(
        cls, value: tuple[dict[str, JsonValue], ...]
    ) -> tuple[dict[str, JsonValue], ...]:
        for definition in value:
            _require_nonempty_object(definition)
        return value


class DiagnosticDefinition(_Slice4ConfigModel):
    """One diagnostic (non-gating) definition."""

    reference_id: str = Field(pattern=_IDENTITY_PATTERN)
    metric_id: str = Field(pattern=_IDENTITY_PATTERN)
    population_slice_id: str = Field(pattern=_IDENTITY_PATTERN)
    slice_definitions: tuple[dict[str, JsonValue], ...]

    @field_validator("slice_definitions")
    @classmethod
    def _nonempty_slices(
        cls, value: tuple[dict[str, JsonValue], ...]
    ) -> tuple[dict[str, JsonValue], ...]:
        for definition in value:
            _require_nonempty_object(definition)
        return value


class ScoringGateConfig(_Slice4ConfigModel):
    """Immutable versioned scoring/gate configuration."""

    config_version: str = Field(pattern=_IDENTITY_PATTERN)
    blocking_severities: tuple[str, ...]
    protected_regression_classes: tuple[str, ...]
    gates: tuple[GateDefinition, ...]
    diagnostics: tuple[DiagnosticDefinition, ...]


class LoadedScoringGateConfig(_Slice4ConfigModel):
    """A validated configuration plus its raw-byte binding material."""

    config: ScoringGateConfig
    version: str
    sha256: str
    artifact_reference: str


# --- Loader exceptions ----------------------------------------------------


class ScoringConfigLoadError(Exception):
    """Base class for scoring-config parse/path failures; never raised directly."""

    def __init__(self, message: str, *, artifact_reference: str | None = None) -> None:
        super().__init__(message)
        self.artifact_reference = artifact_reference


class ScoringConfigArtifactNotAFileError(ScoringConfigLoadError):
    """The contained config path exists but is not a regular file."""


class ScoringConfigPathEscapeError(ScoringConfigLoadError):
    """The requested config path resolves outside the evaluation root."""


class ScoringConfigReadError(ScoringConfigLoadError):
    """Reading the config bytes failed."""


class ScoringConfigDecodeError(ScoringConfigLoadError):
    """The config bytes are not valid UTF-8."""


class ScoringConfigJsonError(ScoringConfigLoadError):
    """The config text is not acceptable strict JSON."""

    def __init__(
        self,
        message: str,
        *,
        artifact_reference: str | None = None,
        duplicate_key: str | None = None,
        constant_name: str | None = None,
    ) -> None:
        super().__init__(message, artifact_reference=artifact_reference)
        self.duplicate_key = duplicate_key
        self.constant_name = constant_name


class ScoringConfigTopLevelTypeError(ScoringConfigLoadError):
    """The parsed config document is not a JSON object."""

    def __init__(
        self,
        message: str,
        *,
        artifact_reference: str | None = None,
        observed_type: str | None = None,
    ) -> None:
        super().__init__(message, artifact_reference=artifact_reference)
        self.observed_type = observed_type


class ScoringConfigModelValidationError(ScoringConfigLoadError):
    """The config document failed model validation."""

    def __init__(
        self,
        message: str,
        *,
        artifact_reference: str | None = None,
        field_locations: tuple[str, ...] = (),
        error_types: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message, artifact_reference=artifact_reference)
        self.field_locations = field_locations
        self.error_types = error_types


class _DuplicateKeyControl(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


class _NonFiniteControl(Exception):
    def __init__(self, constant_name: str) -> None:
        super().__init__(constant_name)
        self.constant_name = constant_name


# --- Private strict-loading helpers (module-local; not shared) ------------


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


def _validate_eval_root(eval_root: str | Path) -> Path:
    if not isinstance(eval_root, (str, Path)):
        raise InvalidEvaluationRootError(
            "eval_root must be an explicit str or Path evaluation root",
            observed_type=type(eval_root).__name__,
        )
    if isinstance(eval_root, str) and eval_root == "":
        raise InvalidEvaluationRootError(
            "eval_root must not be an empty string; supply the evaluation root explicitly",
            supplied_root="",
        )
    root = Path(eval_root)
    if not root.exists():
        raise InvalidEvaluationRootError(
            f"evaluation root {str(eval_root)!r} does not exist",
            supplied_root=str(eval_root),
        )
    if not root.is_dir():
        raise InvalidEvaluationRootError(
            f"evaluation root {str(eval_root)!r} is not a directory",
            supplied_root=str(eval_root),
        )
    return root.resolve()


def _resolve_contained(artifact_path: str | Path, resolved_root: Path) -> tuple[Path, str]:
    requested = Path(artifact_path)
    candidate = requested if requested.is_absolute() else resolved_root / requested
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ScoringConfigPathEscapeError(
            f"scoring-config path {str(artifact_path)!r} resolves outside the "
            "evaluation root",
            artifact_reference=str(artifact_path),
        )
    reference = resolved.relative_to(resolved_root).as_posix()
    if not resolved.exists():
        raise _blocking(
            "config_artifact_missing",
            f"scoring/gate configuration {reference!r} does not exist under the "
            "evaluation root",
            artifact_reference=reference,
        )
    if not resolved.is_file():
        raise ScoringConfigArtifactNotAFileError(
            f"scoring/gate configuration {reference!r} is not a regular file",
            artifact_reference=reference,
        )
    return resolved, reference


def _read_bytes(resolved: Path, reference: str) -> bytes:
    try:
        return resolved.read_bytes()
    except OSError as exc:
        raise ScoringConfigReadError(
            f"failed to read scoring/gate configuration {reference!r}",
            artifact_reference=reference,
        ) from exc


def _decode(raw: bytes, reference: str) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScoringConfigDecodeError(
            f"scoring/gate configuration {reference!r} is not valid UTF-8",
            artifact_reference=reference,
        ) from exc


def _assert_finite(payload: Any, reference: str) -> None:
    stack = [payload]
    while stack:
        value = stack.pop()
        if isinstance(value, float) and not math.isfinite(value):
            name = "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
            raise ScoringConfigJsonError(
                f"scoring/gate configuration {reference!r} contains a non-finite "
                f"JSON number ({name})",
                artifact_reference=reference,
                constant_name=name,
            )
        elif isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)


def _parse_json(text: str, reference: str) -> Any:
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except json.JSONDecodeError as exc:
        raise ScoringConfigJsonError(
            f"scoring/gate configuration {reference!r} is not valid JSON: "
            f"{exc.msg} (line {exc.lineno} column {exc.colno})",
            artifact_reference=reference,
        ) from exc
    except _DuplicateKeyControl as exc:
        raise ScoringConfigJsonError(
            f"scoring/gate configuration {reference!r} contains a duplicate JSON "
            f"object key {exc.key!r}",
            artifact_reference=reference,
            duplicate_key=exc.key,
        ) from exc
    except _NonFiniteControl as exc:
        raise ScoringConfigJsonError(
            f"scoring/gate configuration {reference!r} contains the non-JSON "
            f"constant {exc.constant_name}",
            artifact_reference=reference,
            constant_name=exc.constant_name,
        ) from exc
    _assert_finite(payload, reference)
    return payload


def _require_object(payload: Any, reference: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ScoringConfigTopLevelTypeError(
            f"scoring/gate configuration {reference!r} must be a top-level JSON "
            f"object, got {type(payload).__name__}",
            artifact_reference=reference,
            observed_type=type(payload).__name__,
        )
    return payload


def _validate_model(payload: dict[str, Any], reference: str) -> ScoringGateConfig:
    try:
        return ScoringGateConfig.model_validate(payload)
    except PydanticValidationError as exc:
        pairs = sorted(
            ("/".join(str(part) for part in error["loc"]), error["type"])
            for error in exc.errors()
        )
        raise ScoringConfigModelValidationError(
            f"scoring/gate configuration {reference!r} failed model validation at "
            f"location(s): {', '.join(loc for loc, _ in pairs) or '<root>'}",
            artifact_reference=reference,
            field_locations=tuple(loc for loc, _ in pairs),
            error_types=tuple(t for _, t in pairs),
        ) from exc


def _first_duplicate(values: tuple[str, ...]) -> str | None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            return value
        seen.add(value)
    return None


def _verify_expected_hash(expected_sha256: str | None, observed: str, reference: str) -> None:
    if expected_sha256 is None:
        return
    valid = (
        isinstance(expected_sha256, str)
        and len(expected_sha256) == 64
        and all(c in "0123456789abcdef" for c in expected_sha256)
    )
    if not valid or expected_sha256 != observed:
        raise _blocking(
            "snapshot_hash_mismatch",
            f"scoring/gate configuration {reference!r} raw-byte hash does not "
            "match the expected snapshot hash",
            artifact_reference=reference,
            expected_sha256=expected_sha256 if valid else None,
            observed_sha256=observed,
        )


def _validate_config_semantics(config: ScoringGateConfig, reference: str) -> None:
    duplicate = _first_duplicate(config.blocking_severities)
    if duplicate is not None:
        raise _blocking(
            "conflicting_reference_definition",
            f"scoring/gate configuration {reference!r} declares blocking severity "
            f"{duplicate!r} more than once",
            artifact_reference=reference,
        )
    duplicate = _first_duplicate(config.protected_regression_classes)
    if duplicate is not None:
        raise _blocking(
            "conflicting_reference_definition",
            f"scoring/gate configuration {reference!r} declares protected regression "
            f"class {duplicate!r} more than once",
            artifact_reference=reference,
        )
    severities = set(config.blocking_severities)
    classes = set(config.protected_regression_classes)
    gate_ids: set[str] = set()
    for gate in config.gates:
        if gate.reference_id in gate_ids:
            raise _blocking(
                "duplicate_reference_id",
                f"scoring/gate configuration {reference!r} declares gate "
                f"{gate.reference_id!r} more than once",
                artifact_reference=reference,
                reference_id=gate.reference_id,
            )
        gate_ids.add(gate.reference_id)
        if gate.blocking_severity not in severities:
            raise _blocking(
                "conflicting_reference_definition",
                f"gate {gate.reference_id!r} references undeclared blocking severity "
                f"{gate.blocking_severity!r}",
                artifact_reference=reference,
                reference_id=gate.reference_id,
            )
        within = _first_duplicate(gate.protected_regression_class_references)
        if within is not None:
            raise _blocking(
                "conflicting_reference_definition",
                f"gate {gate.reference_id!r} lists protected-class reference "
                f"{within!r} more than once",
                artifact_reference=reference,
                reference_id=gate.reference_id,
            )
        for class_ref in gate.protected_regression_class_references:
            if class_ref not in classes:
                raise _blocking(
                    "conflicting_reference_definition",
                    f"gate {gate.reference_id!r} references undeclared protected "
                    f"regression class {class_ref!r}",
                    artifact_reference=reference,
                    reference_id=gate.reference_id,
                )
    diagnostic_ids: set[str] = set()
    for diagnostic in config.diagnostics:
        if diagnostic.reference_id in diagnostic_ids:
            raise _blocking(
                "duplicate_reference_id",
                f"scoring/gate configuration {reference!r} declares diagnostic "
                f"{diagnostic.reference_id!r} more than once",
                artifact_reference=reference,
                reference_id=diagnostic.reference_id,
            )
        diagnostic_ids.add(diagnostic.reference_id)
    cross = gate_ids & diagnostic_ids
    if cross:
        offending = next(
            g.reference_id for g in config.gates if g.reference_id in cross
        )
        raise _blocking(
            "conflicting_reference_definition",
            f"scoring/gate configuration {reference!r} reference {offending!r} "
            "appears as both a gate and a diagnostic",
            artifact_reference=reference,
            reference_id=offending,
        )


def load_scoring_gate_config(
    config_path: str | Path,
    *,
    eval_root: str | Path,
    expected_sha256: str | None = None,
) -> LoadedScoringGateConfig:
    """Load, hash, validate and semantically check one scoring/gate configuration.

    ``eval_root`` is explicit and required. A missing artifact is the governed
    blocking failure ``config_artifact_missing``. The returned SHA-256 is
    computed over the exact raw bytes, never parsed or canonicalized JSON. No
    threshold, support, or slice value is interpreted; opaque objects are
    preserved verbatim.
    """
    resolved_root = _validate_eval_root(eval_root)
    resolved, reference = _resolve_contained(config_path, resolved_root)
    raw = _read_bytes(resolved, reference)
    observed = sha256_bytes(raw)
    _verify_expected_hash(expected_sha256, observed, reference)
    text = _decode(raw, reference)
    payload = _require_object(_parse_json(text, reference), reference)
    config = _validate_model(payload, reference)
    _validate_config_semantics(config, reference)
    return LoadedScoringGateConfig(
        config=config,
        version=config.config_version,
        sha256=observed,
        artifact_reference=reference,
    )
