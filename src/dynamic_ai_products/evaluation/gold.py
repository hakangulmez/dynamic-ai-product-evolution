"""Assertion-owned gold expectation set (Slice 12E).

``gold_assertion_set@0.1.0`` is an assertion-owned artifact family keyed by case
ID, assertion ID, assertion semantic identity (semantic version and/or opaque
contract hash), and a resolved *canonical* target reference. Expected-entity and
forbidden-entity behavior derives from the assertion kind and the canonical
target reference; field-value and evidence-provenance expectations carry
kind-discriminated typed payloads. Accepted aliases remain solely
target-registry-owned with absolute precedence — a gold record stores canonical
target IDs only and never introduces a parallel expected/forbidden channel.

``bind_gold_assertion_set`` is pure and proves, per entry, the owning case, the
owning assertion, the assertion kind, the complete assertion semantic identity,
registry/resolution consistency, and that the canonical target is one the owning
assertion actually resolved. It never mutates the target registry.

Read-side plus pure validation and explicit persistence only. Importing this
module performs no filesystem access, hashing, environment inspection, clock
read, UUID generation, network, provider, or model call. Three hash identities
are kept separate: the generated model-contract hash (over the model schema),
the canonical content hash (newline-free canonical model bytes), and the raw
persisted-byte SHA-256 (canonical bytes plus one terminal newline).
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import (
    ValidationError as PydanticValidationError,
    model_validator,
)

from .contracts import canonical_contract_bytes
from .models import (
    AssertionKind,
    ContractStampedModel,
    EvaluationCase,
    EvaluationStrictModel,
    _reject_explicit_null,
    _require_identity_presence,
    _require_non_blank,
    _require_rfc3339_offset,
)
from .references import (
    CaseResolution,
    LoadedTargetRegistry,
)
from ..universe.io_utils import sha256_bytes

__all__ = [
    "BoundGoldAssertionSet",
    "GOLD_FIELD_VALUE_OPERATORS",
    "GoldAssertionSet",
    "GoldAssertionSetError",
    "GoldBindingError",
    "LoadedGoldAssertionSet",
    "ResolvedGoldAssertion",
    "bind_gold_assertion_set",
    "gold_assertion_set_hash",
    "load_gold_assertion_set",
    "persist_gold_assertion_set",
]

_CONTRACT_ID = "gold_assertion_set"
_CONTRACT_VERSION = "0.1.0"
_SNAPSHOTS_DIR = "snapshots"
_SNAPSHOT_FILENAME = "gold_assertion_set.json"

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_FIELD_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9_]+$")

GOLD_FIELD_VALUE_OPERATORS = frozenset(
    {"equals", "not_equals", "in_set", "not_in_set", "gte", "gt", "lte", "lt"}
)
_SET_OPERATORS = frozenset({"in_set", "not_in_set"})
_ORDERING_OPERATORS = frozenset({"gte", "gt", "lte", "lt"})

_GoldScalar = str | int | float | bool


# --- Public errors ---------------------------------------------------------


class GoldAssertionSetError(Exception):
    """Sanitized gold load/persist failure with a stable machine-readable code.

    No raw gold content, absolute path, or raw Pydantic/OS text is placed in the
    message.
    """

    def __init__(
        self, message: str, *, reason_code: str, artifact_reference: str | None = None
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.artifact_reference = artifact_reference


class GoldBindingError(Exception):
    """Sanitized assertion-owned gold binding failure with a stable code."""

    def __init__(
        self, message: str, *, reason_code: str, artifact_reference: str | None = None
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.artifact_reference = artifact_reference


# --- Private strict-parse control exceptions (content-free) ---------------


class _DuplicateKeyControl(Exception):
    def __init__(self) -> None:
        super().__init__("duplicate JSON object key")


class _NonFiniteControl(Exception):
    def __init__(self) -> None:
        super().__init__("non-JSON numeric constant")


# --- Payload / provenance / entry models (schema-feeding: no docstrings) ---


class _GoldFieldValuePayload(EvaluationStrictModel):
    field_path: str
    operator: Literal["equals", "not_equals", "in_set", "not_in_set", "gte", "gt", "lte", "lt"]
    value_type: Literal["string", "integer", "number", "boolean", "date"]
    expected_values: tuple[_GoldScalar, ...]

    @model_validator(mode="after")
    def _payload_invariants(self) -> "_GoldFieldValuePayload":
        _require_non_blank(self.field_path, "field_path")
        segments = self.field_path.split(".")
        for segment in segments:
            if _FIELD_PATH_SEGMENT.fullmatch(segment) is None:
                raise ValueError(
                    "field_path must be a dotted path of [A-Za-z0-9_] segments"
                )
        if self.operator in _SET_OPERATORS:
            if len(self.expected_values) < 1:
                raise ValueError("set-membership operators require at least one value")
        elif len(self.expected_values) != 1:
            raise ValueError("scalar operators require exactly one value")
        if self.operator in _ORDERING_OPERATORS and self.value_type not in (
            "integer",
            "number",
            "date",
        ):
            raise ValueError(
                "ordering operators require an integer, number, or date value_type"
            )
        seen: set[tuple[str, Any]] = set()
        for value in self.expected_values:
            _check_scalar_type(value, self.value_type)
            key = (type(value).__name__, value)
            if key in seen:
                raise ValueError("expected_values must not contain duplicates")
            seen.add(key)
        return self


class _GoldEvidenceProvenancePayload(EvaluationStrictModel):
    expected_source_id: str
    expected_passage_id: str | None = None
    expected_publication_date: str
    match_mode: Literal["exact_passage", "same_source_document"]

    @model_validator(mode="before")
    @classmethod
    def _no_explicit_null(cls, data: Any) -> Any:
        return _reject_explicit_null(
            data, ("expected_passage_id",), "_GoldEvidenceProvenancePayload"
        )

    @model_validator(mode="after")
    def _payload_invariants(self) -> "_GoldEvidenceProvenancePayload":
        _require_non_blank(self.expected_source_id, "expected_source_id")
        _require_canonical_iso_date(
            self.expected_publication_date, "expected_publication_date"
        )
        if self.match_mode == "exact_passage":
            if self.expected_passage_id is None:
                raise ValueError("exact_passage match requires expected_passage_id")
            _require_non_blank(self.expected_passage_id, "expected_passage_id")
        else:
            if self.expected_passage_id is not None:
                raise ValueError(
                    "same_source_document match must not carry expected_passage_id"
                )
        return self


class _GoldProvenance(EvaluationStrictModel):
    gold_origin: Literal["constructed", "human_annotated", "imported_reference"]
    verification_status: Literal["provisional", "verified"]
    verification_method: Literal[
        "dual_independent_adjudication",
        "solo_blinded_retest",
        "expert_second_review",
        "construction_review",
    ]
    annotator_ids: tuple[str, ...]
    reviewer_ids: tuple[str, ...] = ()
    annotation_timestamps: tuple[str, ...]
    adjudication_reference: str | None = None
    source_packet_hash: str
    case_version: str
    change_reason: str
    superseded_by: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_explicit_null(cls, data: Any) -> Any:
        return _reject_explicit_null(
            data, ("adjudication_reference", "superseded_by"), "_GoldProvenance"
        )

    @model_validator(mode="after")
    def _provenance_invariants(self) -> "_GoldProvenance":
        if not self.annotator_ids:
            raise ValueError("annotator_ids must not be empty")
        _require_unique_non_blank(self.annotator_ids, "annotator_ids")
        _require_unique_non_blank(self.reviewer_ids, "reviewer_ids")
        if not self.annotation_timestamps:
            raise ValueError("annotation_timestamps must not be empty")
        for timestamp in self.annotation_timestamps:
            _require_rfc3339_offset(timestamp, "annotation_timestamps entry")
        if _SHA256_HEX.fullmatch(self.source_packet_hash) is None:
            raise ValueError("source_packet_hash must be a lowercase SHA-256 hex digest")
        _require_non_blank(self.case_version, "case_version")
        _require_non_blank(self.change_reason, "change_reason")
        if self.adjudication_reference is not None:
            _require_non_blank(self.adjudication_reference, "adjudication_reference")
        if self.superseded_by is not None:
            _require_non_blank(self.superseded_by, "superseded_by")
        if (
            self.verification_method == "dual_independent_adjudication"
            and self.adjudication_reference is None
        ):
            raise ValueError(
                "dual_independent_adjudication requires an adjudication_reference"
            )
        return self


class _GoldAssertionEntry(EvaluationStrictModel):
    case_id: str
    assertion_id: str
    assertion_semantic_version: str | None = None
    assertion_contract_hash: str | None = None
    assertion_kind: AssertionKind
    canonical_target_reference: str
    field_value_payload: _GoldFieldValuePayload | None = None
    evidence_provenance_payload: _GoldEvidenceProvenancePayload | None = None
    provenance: _GoldProvenance

    @model_validator(mode="before")
    @classmethod
    def _no_explicit_null(cls, data: Any) -> Any:
        return _reject_explicit_null(
            data,
            (
                "assertion_semantic_version",
                "assertion_contract_hash",
                "field_value_payload",
                "evidence_provenance_payload",
            ),
            "_GoldAssertionEntry",
        )

    @model_validator(mode="after")
    def _entry_invariants(self) -> "_GoldAssertionEntry":
        _require_non_blank(self.case_id, "case_id")
        _require_non_blank(self.assertion_id, "assertion_id")
        _require_non_blank(self.canonical_target_reference, "canonical_target_reference")
        _require_identity_presence(
            self, ("assertion_semantic_version", "assertion_contract_hash")
        )
        kind = self.assertion_kind
        has_field = self.field_value_payload is not None
        has_evidence = self.evidence_provenance_payload is not None
        if kind == "field_value":
            if not has_field or has_evidence:
                raise ValueError(
                    "field_value gold requires exactly a field_value_payload"
                )
        elif kind == "evidence_provenance":
            if not has_evidence or has_field:
                raise ValueError(
                    "evidence_provenance gold requires exactly an evidence_provenance_payload"
                )
        elif kind in ("expected_entity", "forbidden_entity"):
            if has_field or has_evidence:
                raise ValueError(
                    "entity gold kinds must not carry a typed payload"
                )
        else:  # deterministic_validation
            raise ValueError(
                "deterministic_validation gold is not permitted in gold_assertion_set@0.1.0"
            )
        return self


class GoldAssertionSet(ContractStampedModel):
    # Docstring intentionally omitted: the generated JSON Schema (and thus the
    # governed model-contract hash) must not carry a description.
    _contract_id: ClassVar[str] = _CONTRACT_ID
    _contract_version: ClassVar[str] = _CONTRACT_VERSION

    gold_set_version: str
    entries: tuple[_GoldAssertionEntry, ...]

    @model_validator(mode="after")
    def _set_invariants(self) -> "GoldAssertionSet":
        _require_non_blank(self.gold_set_version, "gold_set_version")
        if not self.entries:
            raise ValueError("gold assertion set must declare at least one entry")
        for entry in self.entries:
            superseded = entry.provenance.superseded_by
            if superseded is not None and superseded == f"{entry.case_id}:{entry.assertion_id}":
                raise ValueError(
                    "provenance.superseded_by must not equal the entry's own canonical identity"
                )
        keys = [_entry_identity(entry) for entry in self.entries]
        for previous, current in zip(keys, keys[1:]):
            if current == previous:
                raise ValueError("gold entries must be unique by canonical identity")
            if current < previous:
                raise ValueError("gold entries must be in canonical ascending order")
        return self


# --- Binding result models -------------------------------------------------


class ResolvedGoldAssertion(EvaluationStrictModel):
    """One gold entry proven against its owning case, assertion, and resolution."""

    case_id: str
    assertion_id: str
    assertion_semantic_version: str | None
    assertion_contract_hash: str | None
    assertion_kind: AssertionKind
    canonical_target_reference: str
    contract_id: str
    contract_version: str
    contract_hash: str


class BoundGoldAssertionSet(EvaluationStrictModel):
    """A gold set whose every entry is bound to a resolved canonical target."""

    gold_set_version: str
    sha256: str
    entries: tuple[ResolvedGoldAssertion, ...]


# --- Small pure helpers ----------------------------------------------------


def _entry_identity(entry: _GoldAssertionEntry) -> tuple[str, str, str, str, str]:
    return (
        entry.case_id,
        entry.assertion_id,
        entry.assertion_semantic_version or "",
        entry.assertion_contract_hash or "",
        entry.canonical_target_reference,
    )


def _check_scalar_type(value: Any, value_type: str) -> None:
    if value_type == "string":
        if not isinstance(value, str):
            raise ValueError("value_type 'string' requires a string value")
    elif value_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("value_type 'integer' requires an integer value")
    elif value_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("value_type 'number' requires a numeric value")
    elif value_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError("value_type 'boolean' requires a boolean value")
    else:  # date
        if not isinstance(value, str):
            raise ValueError("value_type 'date' requires a canonical ISO date string")
        _require_canonical_iso_date(value, "expected_values date")


def _require_canonical_iso_date(value: str, field_name: str) -> None:
    _require_non_blank(value, field_name)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a canonical ISO-8601 date") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must be a canonical ISO-8601 date")


def _require_unique_non_blank(values: tuple[str, ...], field_name: str) -> None:
    seen: set[str] = set()
    for value in values:
        _require_non_blank(value, f"{field_name} entry")
        if value in seen:
            raise ValueError(f"{field_name} must not contain duplicates")
        seen.add(value)


# --- Content hash + fail-closed revalidation ------------------------------


def _revalidate(model: GoldAssertionSet) -> GoldAssertionSet:
    if not isinstance(model, GoldAssertionSet):
        raise TypeError(f"expected a GoldAssertionSet, got {type(model).__name__}")
    try:
        payload = model.model_dump(mode="json", exclude_unset=True)
    except Exception as exc:  # noqa: BLE001 - any serialization defect fails closed
        raise GoldAssertionSetError(
            "gold assertion set could not be serialized for revalidation",
            reason_code="model_validation",
        ) from exc
    try:
        return GoldAssertionSet.model_validate(payload)
    except PydanticValidationError as exc:
        raise GoldAssertionSetError(
            "gold assertion set failed fail-closed revalidation",
            reason_code="model_validation",
        ) from exc


def gold_assertion_set_hash(model: GoldAssertionSet) -> str:
    """The canonical content hash over newline-free canonical model bytes."""
    validated = _revalidate(model)
    payload = validated.model_dump(mode="json", exclude_unset=True)
    return sha256_bytes(canonical_contract_bytes(payload))


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
        raise GoldAssertionSetError(
            "eval_root must be an explicit str or Path evaluation root",
            reason_code="invalid_eval_root",
        )
    if isinstance(eval_root, str) and eval_root == "":
        raise GoldAssertionSetError(
            "eval_root must not be an empty string; supply the evaluation root explicitly",
            reason_code="invalid_eval_root",
        )
    root = Path(eval_root)
    if root.is_symlink():
        raise GoldAssertionSetError(
            "eval_root must not be a symlink", reason_code="eval_root_symlink"
        )
    if not root.exists():
        raise GoldAssertionSetError(
            "evaluation root does not exist", reason_code="invalid_eval_root"
        )
    if not root.is_dir():
        raise GoldAssertionSetError(
            "evaluation root is not a directory", reason_code="invalid_eval_root"
        )
    return root.resolve()


def _resolve_contained(reference: str | Path, resolved_root: Path) -> tuple[Path, str]:
    if not _is_safe_reference(reference if isinstance(reference, str) else str(reference)):
        if not isinstance(reference, (str, Path)):
            raise GoldAssertionSetError(
                "reference must be an explicit str or Path", reason_code="invalid_path"
            )
        raise GoldAssertionSetError(
            "reference is not a safe relative reference", reason_code="unsafe_reference"
        )
    candidate = resolved_root / Path(reference)
    if candidate.is_symlink():
        raise GoldAssertionSetError(
            "artifact path is a symlink", reason_code="artifact_symlink"
        )
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise GoldAssertionSetError(
            "artifact path resolves outside the evaluation root", reason_code="path_escape"
        )
    ref = resolved.relative_to(resolved_root).as_posix()
    if resolved.is_symlink():
        raise GoldAssertionSetError(
            "artifact is a symlink", reason_code="artifact_symlink", artifact_reference=ref
        )
    if not resolved.exists():
        raise GoldAssertionSetError(
            "artifact does not exist under the evaluation root",
            reason_code="artifact_missing",
            artifact_reference=ref,
        )
    if not resolved.is_file():
        raise GoldAssertionSetError(
            "artifact is not a regular file",
            reason_code="artifact_not_a_file",
            artifact_reference=ref,
        )
    return resolved, ref


def _validate_run_id(eval_run_id: Any) -> str:
    if not isinstance(eval_run_id, str):
        raise GoldAssertionSetError(
            f"eval_run_id must be a string, got {type(eval_run_id).__name__}",
            reason_code="invalid_eval_run_id",
        )
    if not eval_run_id or eval_run_id != eval_run_id.strip():
        raise GoldAssertionSetError(
            "eval_run_id must be a non-empty string without leading or trailing whitespace",
            reason_code="invalid_eval_run_id",
        )
    if eval_run_id in (".", ".."):
        raise GoldAssertionSetError(
            "eval_run_id is not a valid path component", reason_code="invalid_eval_run_id"
        )
    if "/" in eval_run_id or "\\" in eval_run_id or "\x00" in eval_run_id:
        raise GoldAssertionSetError(
            "eval_run_id must be a single path component without separators or NUL",
            reason_code="invalid_eval_run_id",
        )
    if Path(eval_run_id).is_absolute() or len(Path(eval_run_id).parts) != 1:
        raise GoldAssertionSetError(
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
        raise GoldAssertionSetError(
            "artifact is not valid JSON", reason_code="json_error", artifact_reference=reference
        ) from exc
    except _DuplicateKeyControl as exc:
        raise GoldAssertionSetError(
            "artifact contains a duplicate JSON object key",
            reason_code="duplicate_key",
            artifact_reference=reference,
        ) from exc
    except _NonFiniteControl as exc:
        raise GoldAssertionSetError(
            "artifact contains a non-JSON numeric constant",
            reason_code="non_finite",
            artifact_reference=reference,
        ) from exc
    if _has_non_finite(payload):
        raise GoldAssertionSetError(
            "artifact contains a non-finite JSON number",
            reason_code="non_finite",
            artifact_reference=reference,
        )
    if not isinstance(payload, dict):
        raise GoldAssertionSetError(
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
        raise GoldAssertionSetError(
            "failed to read the artifact", reason_code="read_error", artifact_reference=ref
        ) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GoldAssertionSetError(
            "artifact is not valid UTF-8", reason_code="decode_error", artifact_reference=ref
        ) from exc
    return raw, text, ref


# --- Loader ---------------------------------------------------------------


def load_gold_assertion_set(
    path: str | Path,
    *,
    eval_root: str | Path,
    expected_sha256: str | None = None,
) -> LoadedGoldAssertionSet:
    """Load, hash-bind, and strictly validate a gold assertion set.

    Reads the gold JSON (contained under ``eval_root``, symlink-rejected),
    parses it strictly (duplicate keys, non-finite numbers, and non-object
    top-levels rejected), and validates the ``gold_assertion_set@0.1.0``
    contract. All failures are sanitized ``GoldAssertionSetError``.
    """
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
            raise GoldAssertionSetError(
                "gold assertion set raw-byte hash does not match the expected hash",
                reason_code="expected_hash_mismatch",
                artifact_reference=reference,
            )
    payload = _strict_json_object(text, reference)
    try:
        model = GoldAssertionSet.model_validate(payload)
    except PydanticValidationError as exc:
        raise GoldAssertionSetError(
            "gold assertion set failed strict contract validation",
            reason_code="model_validation",
            artifact_reference=reference,
        ) from exc
    return LoadedGoldAssertionSet(
        model=model,
        version=model.gold_set_version,
        sha256=observed,
        artifact_reference=reference,
    )


class LoadedGoldAssertionSet(EvaluationStrictModel):
    """A validated gold assertion set plus its raw-byte binding material."""

    model: GoldAssertionSet
    version: str
    sha256: str
    artifact_reference: str


# --- Assertion-owned binding ----------------------------------------------


def bind_gold_assertion_set(
    gold: LoadedGoldAssertionSet,
    *,
    registry: LoadedTargetRegistry,
    cases: Mapping[str, EvaluationCase],
    resolutions: Mapping[str, CaseResolution],
) -> BoundGoldAssertionSet:
    """Prove every gold entry against its owning case, assertion, and resolution.

    Pure: reads only the loaded gold set, the loaded target registry, the cases,
    and their resolutions; mutates nothing. Each entry must match an existing
    case and assertion, the same assertion kind, the complete assertion semantic
    identity (semantic version and/or opaque contract hash, verbatim), and a
    canonical target the owning assertion actually resolved. Aliases stored in
    gold fail closed.
    """
    if not isinstance(gold, LoadedGoldAssertionSet):
        raise TypeError(f"gold must be a LoadedGoldAssertionSet, got {type(gold).__name__}")
    if not isinstance(registry, LoadedTargetRegistry):
        raise TypeError(
            f"registry must be a LoadedTargetRegistry, got {type(registry).__name__}"
        )
    if not isinstance(cases, Mapping):
        raise TypeError(f"cases must be a Mapping, got {type(cases).__name__}")
    if not isinstance(resolutions, Mapping):
        raise TypeError(f"resolutions must be a Mapping, got {type(resolutions).__name__}")

    canonical_ids = {entry.reference_id for entry in registry.registry.entries}
    alias_ids: set[str] = set()
    for entry in registry.registry.entries:
        alias_ids.update(entry.aliases)

    resolved_entries: list[ResolvedGoldAssertion] = []
    for entry in gold.model.entries:
        case = cases.get(entry.case_id)
        if case is None:
            raise GoldBindingError(
                "gold entry references a case absent from the provided cases",
                reason_code="unresolvable_gold_case",
                artifact_reference=gold.artifact_reference,
            )
        spec = next(
            (a for a in case.assertions if a.assertion_id == entry.assertion_id), None
        )
        if spec is None:
            raise GoldBindingError(
                "gold entry references an assertion absent from its owning case",
                reason_code="unresolvable_gold_assertion",
                artifact_reference=gold.artifact_reference,
            )
        if spec.kind != entry.assertion_kind:
            raise GoldBindingError(
                "gold entry assertion_kind does not match the owning assertion",
                reason_code="gold_assertion_kind_mismatch",
                artifact_reference=gold.artifact_reference,
            )
        if (
            entry.assertion_semantic_version != spec.semantic_version
            or entry.assertion_contract_hash != spec.contract_hash
        ):
            raise GoldBindingError(
                "gold entry semantic identity does not match the owning assertion",
                reason_code="gold_assertion_identity_mismatch",
                artifact_reference=gold.artifact_reference,
            )
        resolution = resolutions.get(entry.case_id)
        if resolution is None:
            raise GoldBindingError(
                "gold entry references a case with no provided resolution",
                reason_code="unresolvable_gold_resolution",
                artifact_reference=gold.artifact_reference,
            )
        if (
            resolution.target_registry_version != registry.version
            or resolution.target_registry_sha256 != registry.sha256
        ):
            raise GoldBindingError(
                "case resolution was not built against the provided target registry",
                reason_code="registry_resolution_mismatch",
                artifact_reference=gold.artifact_reference,
            )
        resolved_assertion = next(
            (r for r in resolution.assertions if r.assertion_id == entry.assertion_id),
            None,
        )
        if resolved_assertion is None:
            raise GoldBindingError(
                "gold entry assertion has no resolved references in the resolution",
                reason_code="unresolvable_gold_resolution",
                artifact_reference=gold.artifact_reference,
            )
        if entry.canonical_target_reference in alias_ids and entry.canonical_target_reference not in canonical_ids:
            raise GoldBindingError(
                "gold entry stores a target-registry alias; gold must store canonical IDs",
                reason_code="gold_reference_is_alias",
                artifact_reference=gold.artifact_reference,
            )
        match = next(
            (
                rt
                for rt in resolved_assertion.target_references
                if rt.canonical_reference_id == entry.canonical_target_reference
            ),
            None,
        )
        if match is None:
            raise GoldBindingError(
                "gold canonical target is not among the assertion's resolved targets",
                reason_code="gold_target_not_resolved_for_assertion",
                artifact_reference=gold.artifact_reference,
            )
        resolved_entries.append(
            ResolvedGoldAssertion(
                case_id=entry.case_id,
                assertion_id=entry.assertion_id,
                assertion_semantic_version=entry.assertion_semantic_version,
                assertion_contract_hash=entry.assertion_contract_hash,
                assertion_kind=entry.assertion_kind,
                canonical_target_reference=entry.canonical_target_reference,
                contract_id=match.contract_id,
                contract_version=match.contract_version,
                contract_hash=match.contract_hash,
            )
        )
    return BoundGoldAssertionSet(
        gold_set_version=gold.model.gold_set_version,
        sha256=gold.sha256,
        entries=tuple(resolved_entries),
    )


# --- Snapshot persistence -------------------------------------------------


def persist_gold_assertion_set(
    model: GoldAssertionSet,
    *,
    eval_root: str | Path,
    eval_run_id: str,
) -> LoadedGoldAssertionSet:
    """Write the canonical gold JSON (plus one terminal newline) write-once.

    Destination: ``<eval_root>/<eval_run_id>/snapshots/gold_assertion_set.json``.
    """
    validated = _revalidate(model)
    resolved_root = _validate_eval_root(eval_root)
    run_id = _validate_run_id(eval_run_id)
    run_dir = resolved_root / run_id
    if run_dir.is_symlink():
        raise GoldAssertionSetError(
            "run directory is a symlink", reason_code="run_directory_symlink"
        )
    if not run_dir.exists():
        raise GoldAssertionSetError(
            "run directory does not exist under the evaluation root",
            reason_code="run_directory_missing",
            artifact_reference=run_id,
        )
    if not run_dir.is_dir():
        raise GoldAssertionSetError(
            "run directory is not a directory",
            reason_code="run_directory_not_a_directory",
            artifact_reference=run_id,
        )
    snapshots_dir = run_dir / _SNAPSHOTS_DIR
    if snapshots_dir.is_symlink():
        raise GoldAssertionSetError(
            "run snapshots directory is a symlink",
            reason_code="snapshots_directory_symlink",
        )
    if snapshots_dir.exists():
        if not snapshots_dir.is_dir():
            raise GoldAssertionSetError(
                "run snapshots path is not a directory",
                reason_code="snapshots_directory_not_a_directory",
            )
    else:
        try:
            snapshots_dir.mkdir(exist_ok=False)
        except OSError as exc:
            raise GoldAssertionSetError(
                "failed to create the run snapshots directory",
                reason_code="write_error",
                artifact_reference=f"{run_id}/{_SNAPSHOTS_DIR}",
            ) from exc
    reference = f"{run_id}/{_SNAPSHOTS_DIR}/{_SNAPSHOT_FILENAME}"
    dest = snapshots_dir / _SNAPSHOT_FILENAME
    if dest.is_symlink() or dest.exists():
        raise GoldAssertionSetError(
            "snapshot already exists; snapshots are write-once",
            reason_code="snapshot_exists",
            artifact_reference=reference,
        )
    data = canonical_contract_bytes(validated.model_dump(mode="json", exclude_unset=True)) + b"\n"
    expected = sha256_bytes(data)
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise GoldAssertionSetError(
            "snapshot already exists; snapshots are write-once",
            reason_code="snapshot_exists",
            artifact_reference=reference,
        ) from exc
    except OSError as exc:
        raise GoldAssertionSetError(
            "failed to create the snapshot", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise GoldAssertionSetError(
            "failed to write the snapshot", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        observed = sha256_bytes(dest.read_bytes())
    except OSError as exc:
        raise GoldAssertionSetError(
            "failed to re-read the snapshot for verification",
            reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    if observed != expected:
        raise GoldAssertionSetError(
            "persisted snapshot re-read to a different hash",
            reason_code="destination_hash_mismatch",
            artifact_reference=reference,
        )
    return LoadedGoldAssertionSet(
        model=validated,
        version=validated.gold_set_version,
        sha256=observed,
        artifact_reference=reference,
    )
