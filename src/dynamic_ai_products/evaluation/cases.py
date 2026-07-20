"""Evaluation-case loading and validation (Slice 2).

Read-side behavior only: resolve one case path under an explicit evaluation
root, read raw bytes, decode strict UTF-8, parse strict JSON (duplicate
object keys and non-finite numbers rejected), reject prohibited legacy
fields with structured errors, validate against the reviewed static schema
``evaluation_case@0.1.0`` through the evaluation-only registry, validate
with the ``EvaluationCase`` model, and return a fresh frozen instance.

No collection or directory loading, no persistence, no membership or
case-set behavior, no CLI, and no default evaluation root live here. The
resolved filesystem path is used only for containment and reading, never as
artifact identity; diagnostics use a deterministic root-relative POSIX
reference and never include file contents.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError

from .models import EvaluationCase
from .schemas import load_schema

_CASE_CONTRACT_ID = "evaluation_case"
_CASE_CONTRACT_VERSION = "0.1.0"

# Exact SPEC-022 "Removed from the contract" set. Top-level keys only; any
# other unknown property fails through the schema's additionalProperties.
_PROHIBITED_LEGACY_FIELDS: frozenset[str] = frozenset(
    {
        "split",
        "company_id",
        "observation_date",
        "expected_status",
        "expected_entities",
        "forbidden_entities",
    }
)


class CaseLoadError(Exception):
    """Base class for evaluation-case loading failures; never raised directly."""

    def __init__(self, message: str, *, artifact_reference: str | None = None) -> None:
        super().__init__(message)
        self.artifact_reference = artifact_reference


class InvalidEvaluationRootError(CaseLoadError):
    """The explicit evaluation root is unusable (type, empty, missing, not a dir)."""

    def __init__(
        self,
        message: str,
        *,
        supplied_root: str | None = None,
        observed_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.supplied_root = supplied_root
        self.observed_type = observed_type


class CasePathEscapeError(CaseLoadError):
    """The requested path resolves outside the evaluation root."""


class CaseArtifactNotFoundError(CaseLoadError):
    """The contained case path does not exist."""


class CaseArtifactNotAFileError(CaseLoadError):
    """The contained case path exists but is not a regular file."""


class CaseReadError(CaseLoadError):
    """Reading the case file bytes failed."""


class CaseDecodeError(CaseLoadError):
    """The case file bytes are not valid UTF-8."""


class CaseJsonError(CaseLoadError):
    """The case file text is not acceptable strict JSON."""

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


class CaseTopLevelTypeError(CaseLoadError):
    """The parsed JSON document is not a top-level object."""

    def __init__(
        self,
        message: str,
        *,
        artifact_reference: str | None = None,
        observed_type: str | None = None,
    ) -> None:
        super().__init__(message, artifact_reference=artifact_reference)
        self.observed_type = observed_type


class ProhibitedLegacyFieldError(CaseLoadError):
    """The case body carries top-level fields removed by SPEC-022."""

    def __init__(
        self,
        message: str,
        *,
        artifact_reference: str | None = None,
        field_names: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message, artifact_reference=artifact_reference)
        self.field_names = field_names


class CaseSchemaValidationError(CaseLoadError):
    """The document failed static-schema validation (or the runtime lacks
    an active date-time format checker, which fails closed here)."""

    def __init__(
        self,
        message: str,
        *,
        artifact_reference: str | None = None,
        json_pointer: str = "",
        validator_keyword: str = "",
        schema_path: str = "",
    ) -> None:
        super().__init__(message, artifact_reference=artifact_reference)
        self.json_pointer = json_pointer
        self.validator_keyword = validator_keyword
        self.schema_path = schema_path


class CaseModelValidationError(CaseLoadError):
    """The document passed the static schema but failed model validation."""

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
    """Private parser-control signal for a duplicate JSON object key."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


class _NonFiniteControl(Exception):
    """Private parser-control signal for a non-finite JSON number."""

    def __init__(self, constant_name: str) -> None:
        super().__init__(constant_name)
        self.constant_name = constant_name


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


def _json_pointer(parts: Iterable[Any]) -> str:
    """RFC 6901 pointer from jsonschema path components ('' at the root)."""
    tokens = []
    for part in parts:
        if isinstance(part, int):
            tokens.append(str(part))
        else:
            tokens.append(str(part).replace("~", "~0").replace("/", "~1"))
    return "".join("/" + token for token in tokens)


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


def _resolve_contained_case_path(
    case_path: str | Path, resolved_root: Path
) -> tuple[Path, str]:
    """Resolve the requested path and require containment inside the root.

    Returns the resolved path plus the deterministic root-relative POSIX
    diagnostic reference. Containment is component-aware
    (``Path.is_relative_to`` on resolved paths), never a string-prefix
    comparison, so ``<root>-escape`` siblings cannot pass. On escape, only
    the requested reference is reported — never the resolved outside target.
    """
    requested = Path(case_path)
    candidate = requested if requested.is_absolute() else resolved_root / requested
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise CasePathEscapeError(
            f"case path {str(case_path)!r} resolves outside the evaluation root",
            artifact_reference=str(case_path),
        )
    reference = resolved.relative_to(resolved_root).as_posix()
    if not resolved.exists():
        raise CaseArtifactNotFoundError(
            f"evaluation case {reference!r} does not exist under the evaluation root",
            artifact_reference=reference,
        )
    if not resolved.is_file():
        raise CaseArtifactNotAFileError(
            f"evaluation case {reference!r} is not a regular file",
            artifact_reference=reference,
        )
    return resolved, reference


def _read_case_bytes(resolved: Path, reference: str) -> bytes:
    try:
        return resolved.read_bytes()
    except OSError as exc:
        raise CaseReadError(
            f"failed to read evaluation case {reference!r}",
            artifact_reference=reference,
        ) from exc


def _decode_strict_utf8(raw: bytes, reference: str) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CaseDecodeError(
            f"evaluation case {reference!r} is not valid UTF-8",
            artifact_reference=reference,
        ) from exc


def _assert_finite_numbers(payload: Any, reference: str) -> None:
    """Reject any non-finite float surviving parsing (numeric overflow)."""
    stack = [payload]
    while stack:
        value = stack.pop()
        if isinstance(value, float) and not math.isfinite(value):
            name = "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
            raise CaseJsonError(
                f"evaluation case {reference!r} contains a non-finite JSON "
                f"number ({name})",
                artifact_reference=reference,
                constant_name=name,
            )
        elif isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)


def _parse_strict_json(text: str, reference: str) -> Any:
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except json.JSONDecodeError as exc:
        raise CaseJsonError(
            f"evaluation case {reference!r} is not valid JSON: {exc.msg} "
            f"(line {exc.lineno} column {exc.colno})",
            artifact_reference=reference,
        ) from exc
    except _DuplicateKeyControl as exc:
        raise CaseJsonError(
            f"evaluation case {reference!r} contains a duplicate JSON object "
            f"key {exc.key!r}",
            artifact_reference=reference,
            duplicate_key=exc.key,
        ) from exc
    except _NonFiniteControl as exc:
        raise CaseJsonError(
            f"evaluation case {reference!r} contains the non-JSON constant "
            f"{exc.constant_name}",
            artifact_reference=reference,
            constant_name=exc.constant_name,
        ) from exc
    _assert_finite_numbers(payload, reference)
    return payload


def _require_top_level_object(payload: Any, reference: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise CaseTopLevelTypeError(
            f"evaluation case {reference!r} must be a top-level JSON object, "
            f"got {type(payload).__name__}",
            artifact_reference=reference,
            observed_type=type(payload).__name__,
        )
    return payload


def _reject_prohibited_legacy_fields(payload: dict[str, Any], reference: str) -> None:
    found = tuple(sorted(_PROHIBITED_LEGACY_FIELDS.intersection(payload)))
    if found:
        raise ProhibitedLegacyFieldError(
            f"evaluation case {reference!r} carries prohibited legacy "
            f"field(s) removed by SPEC-022: {', '.join(found)}",
            artifact_reference=reference,
            field_names=found,
        )


def _static_error_sort_key(error: JsonSchemaValidationError) -> tuple[str, str, str]:
    return (
        _json_pointer(error.absolute_path),
        _json_pointer(error.absolute_schema_path),
        str(error.validator),
    )


def _validate_against_static_schema(payload: dict[str, Any], reference: str) -> None:
    schema = load_schema(_CASE_CONTRACT_ID, _CASE_CONTRACT_VERSION, purpose="read")
    format_checker = FormatChecker()
    if "date-time" not in format_checker.checkers:
        raise CaseSchemaValidationError(
            "runtime lacks an active JSON Schema date-time format checker; "
            "failing closed instead of skipping created_at format validation",
            artifact_reference=reference,
            json_pointer="",
            validator_keyword="format",
            schema_path="",
        )
    validator = Draft202012Validator(dict(schema), format_checker=format_checker)
    errors = sorted(validator.iter_errors(payload), key=_static_error_sort_key)
    if errors:
        first = errors[0]
        pointer = _json_pointer(first.absolute_path)
        keyword = str(first.validator)
        raise CaseSchemaValidationError(
            f"evaluation case {reference!r} failed static-schema validation "
            f"at pointer {pointer!r} (validator {keyword!r})",
            artifact_reference=reference,
            json_pointer=pointer,
            validator_keyword=keyword,
            schema_path=_json_pointer(first.absolute_schema_path),
        ) from first


def _validate_with_model(payload: dict[str, Any], reference: str) -> EvaluationCase:
    try:
        return EvaluationCase.model_validate(payload)
    except PydanticValidationError as exc:
        pairs = sorted(
            ("/".join(str(part) for part in error["loc"]), error["type"])
            for error in exc.errors()
        )
        locations = tuple(location for location, _ in pairs)
        error_types = tuple(error_type for _, error_type in pairs)
        raise CaseModelValidationError(
            f"evaluation case {reference!r} failed model validation at "
            f"location(s): {', '.join(locations) or '<root>'}",
            artifact_reference=reference,
            field_locations=locations,
            error_types=error_types,
        ) from exc


def load_case(case_path: str | Path, *, eval_root: str | Path) -> EvaluationCase:
    """Load and validate one immutable evaluation-case file.

    ``eval_root`` is explicit and required: there is no working-directory,
    repository-root, environment, or ``evals/`` default. Relative paths are
    interpreted under the resolved root; absolute paths are accepted only
    when their resolved target stays inside the resolved root. Every
    successful call returns a fresh frozen ``EvaluationCase``. Registry
    failures (unknown contract, missing schema file, hash mismatch,
    meta-validation) propagate unchanged from ``load_schema``.
    """
    resolved_root = _validate_eval_root(eval_root)
    resolved, reference = _resolve_contained_case_path(case_path, resolved_root)
    raw = _read_case_bytes(resolved, reference)
    text = _decode_strict_utf8(raw, reference)
    parsed = _parse_strict_json(text, reference)
    payload = _require_top_level_object(parsed, reference)
    _reject_prohibited_legacy_fields(payload, reference)
    _validate_against_static_schema(payload, reference)
    return _validate_with_model(payload, reference)
