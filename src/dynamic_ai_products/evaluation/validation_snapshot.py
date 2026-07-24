"""Validation-artifact snapshot set (Slice 12G, SPEC-023 / ADR-024).

``validation_artifact_snapshot_set@0.1.0`` is a strict, frozen, extra-forbid,
model-contract-hash-governed set that wraps the committed per-artifact
``ValidationArtifactSnapshot`` primitives for one single-stage evaluation run.
It binds only already-normalized snapshot primitives plus its own run/stage
identity: every element shares the set's ``eval_run_id`` and
``evaluation_stage``, ``artifact_id`` values are unique, and elements are in
strict ascending ``artifact_id`` order. Each element retains its twelve
canonical ``ValidatorRuleCoverage`` records and its Rule-12 parsed-content-SHA
binding (enforced by the reused ``ValidationArtifactSnapshot`` model); this slice
does not verify per-element hashes against external artifact bytes.

Cross-artifact and run-manifest reconciliation (validator parameters/bundle,
source snapshot, parsed-content file bytes, gold, semantic adapters, and the
v0.2 run-manifest pins) is deliberately out of scope; it belongs to Slice 12M,
and semantic-assertion consumption belongs to Slice 12H.

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
from pathlib import Path
from typing import Any, ClassVar

from pydantic import (
    Field,
    ValidationError as PydanticValidationError,
    model_validator,
)

from .contracts import canonical_contract_bytes, model_contract_hash
from .models import (
    ContractStampedModel,
    EvaluationStrictModel,
    _IDENTITY_PATTERN,
    _require_non_blank,
)
from .prediction_content import EvaluationStage
from .validators import ValidationArtifactSnapshot
from ..universe.io_utils import sha256_bytes

__all__ = [
    "LoadedValidationArtifactSnapshotSet",
    "ValidationArtifactSnapshotSet",
    "ValidationArtifactSnapshotSetBindingError",
    "ValidationArtifactSnapshotSetError",
    "build_validation_artifact_snapshot_set",
    "load_validation_artifact_snapshot_set",
    "persist_validation_artifact_snapshot_set",
    "validation_artifact_snapshot_set_hash",
]

_CONTRACT_ID = "validation_artifact_snapshot_set"
_CONTRACT_VERSION = "0.1.0"
_SNAPSHOTS_DIR = "snapshots"
_SNAPSHOT_FILENAME = "validation_artifact_snapshot_set.json"


# --- Public errors ---------------------------------------------------------


class ValidationArtifactSnapshotSetError(Exception):
    """Sanitized validation-snapshot-set failure with a stable machine code.

    No raw content, absolute path, or raw Pydantic/OS text is placed in the
    message.
    """

    def __init__(
        self, message: str, *, reason_code: str, artifact_reference: str | None = None
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.artifact_reference = artifact_reference


class ValidationArtifactSnapshotSetBindingError(Exception):
    """Sanitized binding failure between a set and an explicit run identity."""

    def __init__(self, message: str, *, binding_kind: str) -> None:
        super().__init__(message)
        self.binding_kind = binding_kind


class _DuplicateKeyControl(Exception):
    def __init__(self) -> None:
        super().__init__("duplicate JSON object key")


class _NonFiniteControl(Exception):
    def __init__(self) -> None:
        super().__init__("non-JSON numeric constant")


# --- Model -----------------------------------------------------------------


class ValidationArtifactSnapshotSet(ContractStampedModel):
    # Docstring intentionally omitted so the generated JSON Schema (and thus the
    # governed model-contract hash) carries no description.
    _contract_id: ClassVar[str] = _CONTRACT_ID
    _contract_version: ClassVar[str] = _CONTRACT_VERSION

    snapshot_set_version: str = Field(pattern=_IDENTITY_PATTERN)
    eval_run_id: str
    evaluation_stage: EvaluationStage
    snapshots: tuple[ValidationArtifactSnapshot, ...]

    @model_validator(mode="after")
    def _set_invariants(self) -> "ValidationArtifactSnapshotSet":
        _require_non_blank(self.snapshot_set_version, "snapshot_set_version")
        _require_non_blank(self.eval_run_id, "eval_run_id")
        if not self.snapshots:
            raise ValueError("validation-artifact snapshot set must be non-empty")
        artifact_ids = [snapshot.artifact_id for snapshot in self.snapshots]
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("artifact_id values must be unique within the set")
        for previous, current in zip(artifact_ids, artifact_ids[1:]):
            if current <= previous:
                raise ValueError("snapshots must be in strict ascending artifact_id order")
        for snapshot in self.snapshots:
            if snapshot.eval_run_id != self.eval_run_id:
                raise ValueError(
                    "every snapshot's eval_run_id must equal the set eval_run_id"
                )
            if snapshot.stage != self.evaluation_stage:
                raise ValueError(
                    "every snapshot's stage must equal the set evaluation_stage"
                )
        return self


class LoadedValidationArtifactSnapshotSet(EvaluationStrictModel):
    """A validated snapshot set plus its raw-byte binding material."""

    model: ValidationArtifactSnapshotSet
    version: str
    sha256: str
    artifact_reference: str


# --- Sanctioned constructor ------------------------------------------------


def build_validation_artifact_snapshot_set(
    *,
    snapshot_set_version: str,
    eval_run_id: str,
    evaluation_stage: str,
    snapshots: tuple[ValidationArtifactSnapshot, ...],
) -> ValidationArtifactSnapshotSet:
    """The sanctioned public constructor for a validation-artifact snapshot set.

    Owns its contract stamp: the contract ID, version, and generated
    model-contract hash are computed here (mirroring
    ``build_validator_bundle_artifact``), never caller-supplied. Direct
    low-level Pydantic construction remains possible; this is the construction
    path exercised by tests and fixture generation.
    """
    for index, snapshot in enumerate(snapshots):
        if not isinstance(snapshot, ValidationArtifactSnapshot):
            raise TypeError(
                f"snapshots[{index}] must be a ValidationArtifactSnapshot, got "
                f"{type(snapshot).__name__}"
            )
    stamp_hash = model_contract_hash(
        ValidationArtifactSnapshotSet, _CONTRACT_ID, _CONTRACT_VERSION
    )
    return ValidationArtifactSnapshotSet(
        contract={
            "contract_id": _CONTRACT_ID,
            "contract_version": _CONTRACT_VERSION,
            "contract_hash": stamp_hash,
        },
        snapshot_set_version=snapshot_set_version,
        eval_run_id=eval_run_id,
        evaluation_stage=evaluation_stage,
        snapshots=tuple(snapshots),
    )


# --- Content hash + fail-closed revalidation ------------------------------


def _revalidate(model: ValidationArtifactSnapshotSet) -> ValidationArtifactSnapshotSet:
    if not isinstance(model, ValidationArtifactSnapshotSet):
        raise TypeError(
            f"expected a ValidationArtifactSnapshotSet, got {type(model).__name__}"
        )
    try:
        payload = model.model_dump(mode="json", exclude_unset=True)
    except Exception as exc:  # noqa: BLE001 - any serialization defect fails closed
        raise ValidationArtifactSnapshotSetError(
            "validation-artifact snapshot set could not be serialized for revalidation",
            reason_code="model_validation",
        ) from exc
    try:
        return ValidationArtifactSnapshotSet.model_validate(payload)
    except PydanticValidationError as exc:
        raise ValidationArtifactSnapshotSetError(
            "validation-artifact snapshot set failed fail-closed revalidation",
            reason_code="model_validation",
        ) from exc


def validation_artifact_snapshot_set_hash(model: ValidationArtifactSnapshotSet) -> str:
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
        raise ValidationArtifactSnapshotSetError(
            "eval_root must be an explicit str or Path evaluation root",
            reason_code="invalid_eval_root",
        )
    if isinstance(eval_root, str) and eval_root == "":
        raise ValidationArtifactSnapshotSetError(
            "eval_root must not be an empty string; supply the evaluation root explicitly",
            reason_code="invalid_eval_root",
        )
    root = Path(eval_root)
    if root.is_symlink():
        raise ValidationArtifactSnapshotSetError(
            "eval_root must not be a symlink", reason_code="eval_root_symlink"
        )
    if not root.exists():
        raise ValidationArtifactSnapshotSetError(
            "evaluation root does not exist", reason_code="invalid_eval_root"
        )
    if not root.is_dir():
        raise ValidationArtifactSnapshotSetError(
            "evaluation root is not a directory", reason_code="invalid_eval_root"
        )
    return root.resolve()


def _resolve_contained(reference: str | Path, resolved_root: Path) -> tuple[Path, str]:
    if not _is_safe_reference(reference if isinstance(reference, str) else str(reference)):
        if not isinstance(reference, (str, Path)):
            raise ValidationArtifactSnapshotSetError(
                "reference must be an explicit str or Path", reason_code="invalid_path"
            )
        raise ValidationArtifactSnapshotSetError(
            "reference is not a safe relative reference", reason_code="unsafe_reference"
        )
    candidate = resolved_root / Path(reference)
    if candidate.is_symlink():
        raise ValidationArtifactSnapshotSetError(
            "artifact path is a symlink", reason_code="artifact_symlink"
        )
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValidationArtifactSnapshotSetError(
            "artifact path resolves outside the evaluation root", reason_code="path_escape"
        )
    ref = resolved.relative_to(resolved_root).as_posix()
    if resolved.is_symlink():
        raise ValidationArtifactSnapshotSetError(
            "artifact is a symlink", reason_code="artifact_symlink", artifact_reference=ref
        )
    if not resolved.exists():
        raise ValidationArtifactSnapshotSetError(
            "artifact does not exist under the evaluation root",
            reason_code="artifact_missing",
            artifact_reference=ref,
        )
    if not resolved.is_file():
        raise ValidationArtifactSnapshotSetError(
            "artifact is not a regular file",
            reason_code="artifact_not_a_file",
            artifact_reference=ref,
        )
    return resolved, ref


def _validate_run_id(eval_run_id: Any) -> str:
    if not isinstance(eval_run_id, str):
        raise ValidationArtifactSnapshotSetError(
            f"eval_run_id must be a string, got {type(eval_run_id).__name__}",
            reason_code="invalid_eval_run_id",
        )
    if not eval_run_id or eval_run_id != eval_run_id.strip():
        raise ValidationArtifactSnapshotSetError(
            "eval_run_id must be a non-empty string without leading or trailing whitespace",
            reason_code="invalid_eval_run_id",
        )
    if eval_run_id in (".", ".."):
        raise ValidationArtifactSnapshotSetError(
            "eval_run_id is not a valid path component", reason_code="invalid_eval_run_id"
        )
    if "/" in eval_run_id or "\\" in eval_run_id or "\x00" in eval_run_id:
        raise ValidationArtifactSnapshotSetError(
            "eval_run_id must be a single path component without separators or NUL",
            reason_code="invalid_eval_run_id",
        )
    if Path(eval_run_id).is_absolute() or len(Path(eval_run_id).parts) != 1:
        raise ValidationArtifactSnapshotSetError(
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
        raise ValidationArtifactSnapshotSetError(
            "artifact is not valid JSON", reason_code="json_error", artifact_reference=reference
        ) from exc
    except _DuplicateKeyControl as exc:
        raise ValidationArtifactSnapshotSetError(
            "artifact contains a duplicate JSON object key",
            reason_code="duplicate_key",
            artifact_reference=reference,
        ) from exc
    except _NonFiniteControl as exc:
        raise ValidationArtifactSnapshotSetError(
            "artifact contains a non-JSON numeric constant",
            reason_code="non_finite",
            artifact_reference=reference,
        ) from exc
    if _has_non_finite(payload):
        raise ValidationArtifactSnapshotSetError(
            "artifact contains a non-finite JSON number",
            reason_code="non_finite",
            artifact_reference=reference,
        )
    if not isinstance(payload, dict):
        raise ValidationArtifactSnapshotSetError(
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
        raise ValidationArtifactSnapshotSetError(
            "failed to read the artifact", reason_code="read_error", artifact_reference=ref
        ) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationArtifactSnapshotSetError(
            "artifact is not valid UTF-8", reason_code="decode_error", artifact_reference=ref
        ) from exc
    return raw, text, ref


# --- Loader ---------------------------------------------------------------


def load_validation_artifact_snapshot_set(
    path: str | Path,
    *,
    eval_root: str | Path,
    expected_sha256: str | None = None,
) -> LoadedValidationArtifactSnapshotSet:
    """Load, hash-bind, and strictly validate a validation-artifact snapshot set."""
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
            raise ValidationArtifactSnapshotSetError(
                "validation-artifact snapshot set raw-byte hash does not match the expected hash",
                reason_code="expected_hash_mismatch",
                artifact_reference=reference,
            )
    payload = _strict_json_object(text, reference)
    try:
        model = ValidationArtifactSnapshotSet.model_validate(payload)
    except PydanticValidationError as exc:
        raise ValidationArtifactSnapshotSetError(
            "validation-artifact snapshot set failed strict contract validation",
            reason_code="model_validation",
            artifact_reference=reference,
        ) from exc
    return LoadedValidationArtifactSnapshotSet(
        model=model,
        version=model.snapshot_set_version,
        sha256=observed,
        artifact_reference=reference,
    )


# --- Snapshot persistence -------------------------------------------------


def persist_validation_artifact_snapshot_set(
    model: ValidationArtifactSnapshotSet,
    *,
    eval_root: str | Path,
    eval_run_id: str,
) -> LoadedValidationArtifactSnapshotSet:
    """Write the canonical set JSON (plus one terminal newline) write-once.

    The model is revalidated, then its ``eval_run_id`` must equal the explicit
    ``eval_run_id`` (raising ``ValidationArtifactSnapshotSetBindingError`` before
    any filesystem mutation otherwise). Destination:
    ``<eval_root>/<eval_run_id>/snapshots/validation_artifact_snapshot_set.json``.
    """
    validated = _revalidate(model)
    # Family-B run-ID validation runs before the binding comparison, so a
    # syntactically invalid explicit run ID is an invalid_eval_run_id artifact
    # error (not a binding error); both precede any filesystem mutation.
    run_id = _validate_run_id(eval_run_id)
    if validated.eval_run_id != run_id:
        raise ValidationArtifactSnapshotSetBindingError(
            "the model's eval_run_id does not equal the explicit persistence eval_run_id",
            binding_kind="persist_eval_run_id_mismatch",
        )
    resolved_root = _validate_eval_root(eval_root)
    run_dir = resolved_root / run_id
    if run_dir.is_symlink():
        raise ValidationArtifactSnapshotSetError(
            "run directory is a symlink", reason_code="run_directory_symlink"
        )
    if not run_dir.exists():
        raise ValidationArtifactSnapshotSetError(
            "run directory does not exist under the evaluation root",
            reason_code="run_directory_missing",
            artifact_reference=run_id,
        )
    if not run_dir.is_dir():
        raise ValidationArtifactSnapshotSetError(
            "run directory is not a directory",
            reason_code="run_directory_not_a_directory",
            artifact_reference=run_id,
        )
    snapshots_dir = run_dir / _SNAPSHOTS_DIR
    if snapshots_dir.is_symlink():
        raise ValidationArtifactSnapshotSetError(
            "run snapshots directory is a symlink",
            reason_code="snapshots_directory_symlink",
        )
    if snapshots_dir.exists():
        if not snapshots_dir.is_dir():
            raise ValidationArtifactSnapshotSetError(
                "run snapshots path is not a directory",
                reason_code="snapshots_directory_not_a_directory",
            )
    else:
        try:
            snapshots_dir.mkdir(exist_ok=False)
        except OSError as exc:
            raise ValidationArtifactSnapshotSetError(
                "failed to create the run snapshots directory",
                reason_code="write_error",
                artifact_reference=f"{run_id}/{_SNAPSHOTS_DIR}",
            ) from exc
    reference = f"{run_id}/{_SNAPSHOTS_DIR}/{_SNAPSHOT_FILENAME}"
    dest = snapshots_dir / _SNAPSHOT_FILENAME
    if dest.is_symlink() or dest.exists():
        raise ValidationArtifactSnapshotSetError(
            "snapshot already exists; snapshots are write-once",
            reason_code="snapshot_exists",
            artifact_reference=reference,
        )
    data = canonical_contract_bytes(validated.model_dump(mode="json", exclude_unset=True)) + b"\n"
    expected = sha256_bytes(data)
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise ValidationArtifactSnapshotSetError(
            "snapshot already exists; snapshots are write-once",
            reason_code="snapshot_exists",
            artifact_reference=reference,
        ) from exc
    except OSError as exc:
        raise ValidationArtifactSnapshotSetError(
            "failed to create the snapshot", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ValidationArtifactSnapshotSetError(
            "failed to write the snapshot", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        observed = sha256_bytes(dest.read_bytes())
    except OSError as exc:
        raise ValidationArtifactSnapshotSetError(
            "failed to re-read the snapshot for verification",
            reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    if observed != expected:
        raise ValidationArtifactSnapshotSetError(
            "persisted snapshot re-read to a different hash",
            reason_code="destination_hash_mismatch",
            artifact_reference=reference,
        )
    return LoadedValidationArtifactSnapshotSet(
        model=validated,
        version=validated.snapshot_set_version,
        sha256=observed,
        artifact_reference=reference,
    )
