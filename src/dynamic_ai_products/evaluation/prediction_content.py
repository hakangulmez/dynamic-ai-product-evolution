"""Parsed prediction content — the governed derived output (Slice 12D).

``parsed_prediction_content@0.1.0`` is a strict, frozen, extra-forbid,
contract-stamped derived artifact carrying typed entity/field-value/evidence
collections, per-collection completeness, and the Rule-12 raw-output/repair
provenance. It is a derived output only: it is never a field of ``EvaluationCase``
and never a pre-execution input of ``EvaluationRunManifestV2``; its read-back
hash is bound later through the evaluation-output manifest.

Read-side plus pure validation and explicit persistence only. Importing this
module performs no filesystem access, hashing, environment inspection, clock
read, UUID generation, network, provider, or model call.
"""

from __future__ import annotations

import json
import math
import os
from datetime import date
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import (
    Field,
    ValidationError as PydanticValidationError,
    model_validator,
)

from .contracts import canonical_contract_bytes
from .models import (
    ContractStampedModel,
    EvaluationStrictModel,
    _require_non_blank,
    _SHA256_HEX_PATTERN,
)
from ..universe.io_utils import sha256_bytes

__all__ = [
    "LoadedParsedPredictionContent",
    "ParsedEntityCollection",
    "ParsedEvidenceCollection",
    "ParsedFieldValueCollection",
    "ParsedPredictionContent",
    "ParsedPredictionContentError",
    "load_parsed_prediction_content",
    "persist_parsed_prediction_content",
]

_CONTRACT_ID = "parsed_prediction_content"
_CONTRACT_VERSION = "0.1.0"
_SNAPSHOTS_DIR = "snapshots"
_SNAPSHOT_FILENAME = "parsed_prediction_content.json"

_HEX = {"min_length": 64, "max_length": 64, "pattern": _SHA256_HEX_PATTERN}

EvaluationStage = Literal[
    "capability_extraction",
    "task_extraction",
    "universe_screen",
    "universe_classification",
]
_Completeness = Literal["complete", "partial", "unavailable"]


class ParsedPredictionContentError(Exception):
    """Sanitized parsed-content failure with a stable machine-readable code."""

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


# --- Typed collection items (private, fully governed) ---------------------


class _ParsedEntity(EvaluationStrictModel):
    entity_kind: str
    entity_ref: str

    @model_validator(mode="after")
    def _invariants(self) -> "_ParsedEntity":
        _require_non_blank(self.entity_kind, "entity_kind")
        _require_non_blank(self.entity_ref, "entity_ref")
        return self

    @property
    def _identity(self) -> tuple[str, str]:
        return (self.entity_kind, self.entity_ref)


class _ParsedFieldValue(EvaluationStrictModel):
    entity_ref: str
    field_name: str
    field_value: str

    @model_validator(mode="after")
    def _invariants(self) -> "_ParsedFieldValue":
        _require_non_blank(self.entity_ref, "entity_ref")
        _require_non_blank(self.field_name, "field_name")
        return self

    @property
    def _identity(self) -> tuple[str, str, str]:
        return (self.entity_ref, self.field_name, self.field_value)


class _ParsedEvidence(EvaluationStrictModel):
    entity_ref: str
    source_id: str
    passage_id: str
    quote: str

    @model_validator(mode="after")
    def _invariants(self) -> "_ParsedEvidence":
        _require_non_blank(self.entity_ref, "entity_ref")
        _require_non_blank(self.source_id, "source_id")
        _require_non_blank(self.passage_id, "passage_id")
        return self

    @property
    def _identity(self) -> tuple[str, str, str, str]:
        return (self.entity_ref, self.source_id, self.passage_id, self.quote)


def _require_sorted_unique(items: tuple[Any, ...], label: str) -> None:
    identities = [item._identity for item in items]
    if identities != sorted(identities):
        raise ValueError(f"{label} must be sorted by its canonical identity")
    if len(identities) != len(set(identities)):
        raise ValueError(f"{label} must not contain a duplicate identity")


# --- Public collections ---------------------------------------------------


class ParsedEntityCollection(EvaluationStrictModel):
    completeness: _Completeness
    entities: tuple[_ParsedEntity, ...] = ()

    @model_validator(mode="after")
    def _invariants(self) -> "ParsedEntityCollection":
        _require_sorted_unique(self.entities, "entities")
        if self.completeness == "unavailable" and self.entities:
            raise ValueError("an unavailable entity collection must be empty")
        return self


class ParsedFieldValueCollection(EvaluationStrictModel):
    completeness: _Completeness
    field_values: tuple[_ParsedFieldValue, ...] = ()

    @model_validator(mode="after")
    def _invariants(self) -> "ParsedFieldValueCollection":
        _require_sorted_unique(self.field_values, "field_values")
        if self.completeness == "unavailable" and self.field_values:
            raise ValueError("an unavailable field-value collection must be empty")
        return self


class ParsedEvidenceCollection(EvaluationStrictModel):
    completeness: _Completeness
    evidence: tuple[_ParsedEvidence, ...] = ()

    @model_validator(mode="after")
    def _invariants(self) -> "ParsedEvidenceCollection":
        _require_sorted_unique(self.evidence, "evidence")
        if self.completeness == "unavailable" and self.evidence:
            raise ValueError("an unavailable evidence collection must be empty")
        return self


class ParsedPredictionContent(ContractStampedModel):
    # Docstring intentionally omitted so the generated JSON Schema (and the
    # governed model-contract hash) carries no description.
    _contract_id: ClassVar[str] = _CONTRACT_ID
    _contract_version: ClassVar[str] = _CONTRACT_VERSION

    case_id: str
    stage: EvaluationStage
    prediction_record_id: str
    input_packet_hash: str = Field(**_HEX)
    observation_cutoff: str
    raw_artifact_reference: str
    raw_artifact_sha256: str = Field(**_HEX)
    raw_output_preserved: bool
    repair_applied: bool
    repair_record_references: tuple[str, ...] = ()
    repair_record_hashes: tuple[str, ...] = ()
    entity_collection: ParsedEntityCollection
    field_value_collection: ParsedFieldValueCollection
    evidence_collection: ParsedEvidenceCollection

    @model_validator(mode="after")
    def _content_invariants(self) -> "ParsedPredictionContent":
        _require_non_blank(self.case_id, "case_id")
        _require_non_blank(self.prediction_record_id, "prediction_record_id")
        _require_non_blank(self.observation_cutoff, "observation_cutoff")
        # observation_cutoff is a canonical ISO full date (YYYY-MM-DD); a
        # non-canonical or malformed date is rejected. This behavioral rule does
        # not alter the field declaration or generated schema.
        try:
            parsed_cutoff = date.fromisoformat(self.observation_cutoff)
        except ValueError as exc:
            raise ValueError("observation_cutoff must be an ISO full date") from exc
        if parsed_cutoff.isoformat() != self.observation_cutoff:
            raise ValueError("observation_cutoff must be a canonical ISO full date")
        # raw_artifact_reference must satisfy the safe-relative-reference policy.
        if not _is_safe_reference(self.raw_artifact_reference):
            raise ValueError("raw_artifact_reference must be a safe relative reference")
        # Repair provenance pairing.
        refs = self.repair_record_references
        hashes = self.repair_record_hashes
        if not self.repair_applied:
            if refs or hashes:
                raise ValueError("repair_applied is False so both repair tuples must be empty")
        else:
            if len(refs) != len(hashes) or len(refs) == 0:
                raise ValueError(
                    "repair_applied requires equal non-zero repair reference/hash lengths"
                )
        if len(refs) != len(set(refs)):
            raise ValueError("repair_record_references must be unique")
        for ref in refs:
            if not _is_safe_reference(ref):
                raise ValueError("repair_record_references must be safe relative references")
        for digest in hashes:
            if not _is_lower_sha256_hex(digest):
                raise ValueError("repair_record_hashes must be lowercase 64-hex SHA-256")
        # Internal entity-reference integrity.
        entity_refs = {entity.entity_ref for entity in self.entity_collection.entities}
        for field_value in self.field_value_collection.field_values:
            if field_value.entity_ref not in entity_refs:
                raise ValueError(
                    "field_entity_unresolved: a field value references an unknown entity"
                )
        for evidence in self.evidence_collection.evidence:
            if evidence.entity_ref not in entity_refs:
                raise ValueError(
                    "evidence_entity_unresolved: an evidence item references an unknown entity"
                )
        return self


class LoadedParsedPredictionContent(EvaluationStrictModel):
    """Validated parsed content plus its raw-byte binding material."""

    content: ParsedPredictionContent
    sha256: str
    artifact_reference: str


# --- Safe references / roots / strict parse -------------------------------


def _is_safe_reference(value: Any) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if "\\" in value or "\x00" in value:
        return False
    if Path(value).is_absolute():
        return False
    return all(part not in ("", ".", "..") for part in value.split("/"))


def _is_lower_sha256_hex(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        c in "0123456789abcdef" for c in value
    )


def _validate_eval_root(eval_root: str | Path) -> Path:
    if not isinstance(eval_root, (str, Path)):
        raise ParsedPredictionContentError(
            "eval_root must be an explicit str or Path evaluation root",
            reason_code="invalid_eval_root",
        )
    if isinstance(eval_root, str) and eval_root == "":
        raise ParsedPredictionContentError(
            "eval_root must not be an empty string", reason_code="invalid_eval_root"
        )
    root = Path(eval_root)
    if root.is_symlink():
        raise ParsedPredictionContentError(
            "eval_root must not be a symlink", reason_code="eval_root_symlink"
        )
    if not root.exists():
        raise ParsedPredictionContentError(
            "evaluation root does not exist", reason_code="invalid_eval_root"
        )
    if not root.is_dir():
        raise ParsedPredictionContentError(
            "evaluation root is not a directory", reason_code="invalid_eval_root"
        )
    return root.resolve()


def _resolve_contained(reference: str | Path, resolved_root: Path) -> tuple[Path, str]:
    if not isinstance(reference, (str, Path)):
        raise ParsedPredictionContentError(
            "reference must be an explicit str or Path", reason_code="invalid_path"
        )
    if not _is_safe_reference(str(reference)):
        raise ParsedPredictionContentError(
            "reference is not a safe relative reference", reason_code="unsafe_reference"
        )
    candidate = resolved_root / Path(reference)
    if candidate.is_symlink():
        raise ParsedPredictionContentError(
            "artifact path is a symlink", reason_code="artifact_symlink"
        )
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ParsedPredictionContentError(
            "artifact path resolves outside the evaluation root", reason_code="path_escape"
        )
    ref = resolved.relative_to(resolved_root).as_posix()
    if resolved.is_symlink():
        raise ParsedPredictionContentError(
            "artifact is a symlink", reason_code="artifact_symlink", artifact_reference=ref
        )
    if not resolved.exists():
        raise ParsedPredictionContentError(
            "artifact does not exist under the evaluation root",
            reason_code="artifact_missing",
            artifact_reference=ref,
        )
    if not resolved.is_file():
        raise ParsedPredictionContentError(
            "artifact is not a regular file",
            reason_code="artifact_not_a_file",
            artifact_reference=ref,
        )
    return resolved, ref


def _validate_run_id(eval_run_id: Any) -> str:
    if not isinstance(eval_run_id, str):
        raise ParsedPredictionContentError(
            f"eval_run_id must be a string, got {type(eval_run_id).__name__}",
            reason_code="invalid_eval_run_id",
        )
    if not eval_run_id or eval_run_id != eval_run_id.strip():
        raise ParsedPredictionContentError(
            "eval_run_id must be a non-empty single path component",
            reason_code="invalid_eval_run_id",
        )
    if eval_run_id in (".", ".."):
        raise ParsedPredictionContentError(
            "eval_run_id is not a valid path component", reason_code="invalid_eval_run_id"
        )
    if "/" in eval_run_id or "\\" in eval_run_id or "\x00" in eval_run_id:
        raise ParsedPredictionContentError(
            "eval_run_id must be a single path component without separators or NUL",
            reason_code="invalid_eval_run_id",
        )
    if Path(eval_run_id).is_absolute() or len(Path(eval_run_id).parts) != 1:
        raise ParsedPredictionContentError(
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


def _revalidate_content(content: ParsedPredictionContent) -> ParsedPredictionContent:
    if not isinstance(content, ParsedPredictionContent):
        raise TypeError(
            f"expected a ParsedPredictionContent, got {type(content).__name__}"
        )
    try:
        payload = content.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 - any serialization defect fails closed
        raise ParsedPredictionContentError(
            "parsed content could not be serialized for revalidation",
            reason_code="model_validation",
        ) from exc
    try:
        return ParsedPredictionContent.model_validate(payload)
    except PydanticValidationError as exc:
        raise ParsedPredictionContentError(
            "parsed content failed fail-closed revalidation", reason_code="model_validation"
        ) from exc


# --- Loader ---------------------------------------------------------------


def load_parsed_prediction_content(
    path: str | Path,
    *,
    eval_root: str | Path,
    expected_sha256: str | None = None,
) -> LoadedParsedPredictionContent:
    """Load, hash-bind, and strictly validate one parsed-prediction-content file.

    Unloadable, malformed, hash-mismatched, or contract-invalid content fails
    closed as a sanitized ``ParsedPredictionContentError`` (which invalidates a
    run before any validation snapshot). The returned ``sha256`` is the exact
    raw-byte hash.
    """
    resolved_root = _validate_eval_root(eval_root)
    resolved, reference = _resolve_contained(str(path), resolved_root)
    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        raise ParsedPredictionContentError(
            "failed to read the parsed content", reason_code="read_error",
            artifact_reference=reference,
        ) from exc
    observed = sha256_bytes(raw)
    if expected_sha256 is not None:
        if not _is_lower_sha256_hex(expected_sha256) or expected_sha256 != observed:
            raise ParsedPredictionContentError(
                "parsed content raw-byte hash does not match the expected hash",
                reason_code="expected_hash_mismatch",
                artifact_reference=reference,
            )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParsedPredictionContentError(
            "parsed content is not valid UTF-8", reason_code="decode_error",
            artifact_reference=reference,
        ) from exc
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except json.JSONDecodeError as exc:
        raise ParsedPredictionContentError(
            "parsed content is not valid JSON", reason_code="json_error",
            artifact_reference=reference,
        ) from exc
    except _DuplicateKeyControl as exc:
        raise ParsedPredictionContentError(
            "parsed content contains a duplicate JSON object key",
            reason_code="duplicate_key", artifact_reference=reference,
        ) from exc
    except _NonFiniteControl as exc:
        raise ParsedPredictionContentError(
            "parsed content contains a non-JSON numeric constant",
            reason_code="non_finite", artifact_reference=reference,
        ) from exc
    if _has_non_finite(payload):
        raise ParsedPredictionContentError(
            "parsed content contains a non-finite JSON number",
            reason_code="non_finite", artifact_reference=reference,
        )
    if not isinstance(payload, dict):
        raise ParsedPredictionContentError(
            "parsed content top-level value must be a JSON object",
            reason_code="top_level_type", artifact_reference=reference,
        )
    try:
        content = ParsedPredictionContent.model_validate(payload)
    except PydanticValidationError as exc:
        raise ParsedPredictionContentError(
            "parsed content failed strict contract validation",
            reason_code="model_validation", artifact_reference=reference,
        ) from exc
    return LoadedParsedPredictionContent(
        content=content, sha256=observed, artifact_reference=reference
    )


# --- Persistence ----------------------------------------------------------


def persist_parsed_prediction_content(
    content: ParsedPredictionContent,
    *,
    eval_root: str | Path,
    eval_run_id: str,
) -> LoadedParsedPredictionContent:
    """Write canonical parsed-content JSON (plus one terminal newline) write-once.

    Destination:
    ``<eval_root>/<eval_run_id>/snapshots/parsed_prediction_content.json``.
    """
    validated = _revalidate_content(content)
    resolved_root = _validate_eval_root(eval_root)
    run_id = _validate_run_id(eval_run_id)
    run_dir = resolved_root / run_id
    if run_dir.is_symlink():
        raise ParsedPredictionContentError(
            "run directory is a symlink", reason_code="run_directory_symlink"
        )
    if not run_dir.exists():
        raise ParsedPredictionContentError(
            "run directory does not exist under the evaluation root",
            reason_code="run_directory_missing", artifact_reference=run_id,
        )
    if not run_dir.is_dir():
        raise ParsedPredictionContentError(
            "run directory is not a directory",
            reason_code="run_directory_not_a_directory", artifact_reference=run_id,
        )
    snapshots_dir = run_dir / _SNAPSHOTS_DIR
    if snapshots_dir.is_symlink():
        raise ParsedPredictionContentError(
            "run snapshots directory is a symlink", reason_code="snapshots_directory_symlink"
        )
    if snapshots_dir.exists():
        if not snapshots_dir.is_dir():
            raise ParsedPredictionContentError(
                "run snapshots path is not a directory",
                reason_code="snapshots_directory_not_a_directory",
            )
    else:
        try:
            snapshots_dir.mkdir(exist_ok=False)
        except OSError as exc:
            raise ParsedPredictionContentError(
                "failed to create the run snapshots directory",
                reason_code="write_error",
                artifact_reference=f"{run_id}/{_SNAPSHOTS_DIR}",
            ) from exc
    reference = f"{run_id}/{_SNAPSHOTS_DIR}/{_SNAPSHOT_FILENAME}"
    dest = snapshots_dir / _SNAPSHOT_FILENAME
    if dest.is_symlink() or dest.exists():
        raise ParsedPredictionContentError(
            "parsed content already exists; snapshots are write-once",
            reason_code="snapshot_exists", artifact_reference=reference,
        )
    data = canonical_contract_bytes(validated.model_dump(mode="json", exclude_unset=True)) + b"\n"
    expected = sha256_bytes(data)
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise ParsedPredictionContentError(
            "parsed content already exists; snapshots are write-once",
            reason_code="snapshot_exists", artifact_reference=reference,
        ) from exc
    except OSError as exc:
        raise ParsedPredictionContentError(
            "failed to create the parsed content", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ParsedPredictionContentError(
            "failed to write the parsed content", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        observed = sha256_bytes(dest.read_bytes())
    except OSError as exc:
        raise ParsedPredictionContentError(
            "failed to re-read the parsed content for verification",
            reason_code="write_error", artifact_reference=reference,
        ) from exc
    if observed != expected:
        raise ParsedPredictionContentError(
            "persisted parsed content re-read to a different hash",
            reason_code="destination_hash_mismatch", artifact_reference=reference,
        )
    return LoadedParsedPredictionContent(
        content=validated, sha256=observed, artifact_reference=reference
    )
