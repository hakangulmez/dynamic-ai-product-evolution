"""Governed classification-axis taxonomy (Slice 12E).

``axis_taxonomy@0.1.0`` is a strict, frozen, extra-forbid, model-hash-governed
set of classification axes. Each axis reuses the protected committed
``metrics.AxisDefinition`` verbatim (axis role, metric type, abstention base
type, labels, ordinal order/weighting, and reserved-value semantics are enforced
by that contract and are never re-implemented here). Axes are non-empty, unique
by ``axis_id``, and sorted by ``axis_id``.

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
    ValidationError as PydanticValidationError,
    model_validator,
)

from .contracts import canonical_contract_bytes
from .metrics import AxisDefinition
from .models import (
    ContractStampedModel,
    EvaluationStrictModel,
    _require_non_blank,
)
from ..universe.io_utils import sha256_bytes

__all__ = [
    "AxisTaxonomy",
    "AxisTaxonomyError",
    "LoadedAxisTaxonomy",
    "axis_taxonomy_hash",
    "load_axis_taxonomy",
    "persist_axis_taxonomy",
]

_CONTRACT_ID = "axis_taxonomy"
_CONTRACT_VERSION = "0.1.0"
_SNAPSHOTS_DIR = "snapshots"
_SNAPSHOT_FILENAME = "axis_taxonomy.json"


# --- Public error ----------------------------------------------------------


class AxisTaxonomyError(Exception):
    """Sanitized axis-taxonomy failure with a stable machine-readable code.

    No raw taxonomy content, absolute path, or raw Pydantic/OS text is placed in
    the message.
    """

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


# --- Model ----------------------------------------------------------------


class AxisTaxonomy(ContractStampedModel):
    # Docstring intentionally omitted: the generated JSON Schema (and thus the
    # governed model-contract hash) must not carry a description.
    _contract_id: ClassVar[str] = _CONTRACT_ID
    _contract_version: ClassVar[str] = _CONTRACT_VERSION

    taxonomy_version: str
    axes: tuple[AxisDefinition, ...]

    @model_validator(mode="after")
    def _taxonomy_invariants(self) -> "AxisTaxonomy":
        _require_non_blank(self.taxonomy_version, "taxonomy_version")
        if not self.axes:
            raise ValueError("axis taxonomy must declare at least one axis")
        axis_ids = [axis.axis_id for axis in self.axes]
        for previous, current in zip(axis_ids, axis_ids[1:]):
            if current == previous:
                raise ValueError("axis_id must be unique")
            if current < previous:
                raise ValueError("axes must be sorted by axis_id")
        return self


class LoadedAxisTaxonomy(EvaluationStrictModel):
    """A validated axis taxonomy plus its raw-byte binding material."""

    model: AxisTaxonomy
    version: str
    sha256: str
    artifact_reference: str


# --- Content hash + fail-closed revalidation ------------------------------


def _revalidate(model: AxisTaxonomy) -> AxisTaxonomy:
    if not isinstance(model, AxisTaxonomy):
        raise TypeError(f"expected an AxisTaxonomy, got {type(model).__name__}")
    try:
        payload = model.model_dump(mode="json", exclude_unset=True)
    except Exception as exc:  # noqa: BLE001 - any serialization defect fails closed
        raise AxisTaxonomyError(
            "axis taxonomy could not be serialized for revalidation",
            reason_code="model_validation",
        ) from exc
    try:
        return AxisTaxonomy.model_validate(payload)
    except PydanticValidationError as exc:
        raise AxisTaxonomyError(
            "axis taxonomy failed fail-closed revalidation",
            reason_code="model_validation",
        ) from exc


def axis_taxonomy_hash(model: AxisTaxonomy) -> str:
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
        raise AxisTaxonomyError(
            "eval_root must be an explicit str or Path evaluation root",
            reason_code="invalid_eval_root",
        )
    if isinstance(eval_root, str) and eval_root == "":
        raise AxisTaxonomyError(
            "eval_root must not be an empty string; supply the evaluation root explicitly",
            reason_code="invalid_eval_root",
        )
    root = Path(eval_root)
    if root.is_symlink():
        raise AxisTaxonomyError(
            "eval_root must not be a symlink", reason_code="eval_root_symlink"
        )
    if not root.exists():
        raise AxisTaxonomyError(
            "evaluation root does not exist", reason_code="invalid_eval_root"
        )
    if not root.is_dir():
        raise AxisTaxonomyError(
            "evaluation root is not a directory", reason_code="invalid_eval_root"
        )
    return root.resolve()


def _resolve_contained(reference: str | Path, resolved_root: Path) -> tuple[Path, str]:
    if not _is_safe_reference(reference if isinstance(reference, str) else str(reference)):
        if not isinstance(reference, (str, Path)):
            raise AxisTaxonomyError(
                "reference must be an explicit str or Path", reason_code="invalid_path"
            )
        raise AxisTaxonomyError(
            "reference is not a safe relative reference", reason_code="unsafe_reference"
        )
    candidate = resolved_root / Path(reference)
    if candidate.is_symlink():
        raise AxisTaxonomyError(
            "artifact path is a symlink", reason_code="artifact_symlink"
        )
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise AxisTaxonomyError(
            "artifact path resolves outside the evaluation root", reason_code="path_escape"
        )
    ref = resolved.relative_to(resolved_root).as_posix()
    if resolved.is_symlink():
        raise AxisTaxonomyError(
            "artifact is a symlink", reason_code="artifact_symlink", artifact_reference=ref
        )
    if not resolved.exists():
        raise AxisTaxonomyError(
            "artifact does not exist under the evaluation root",
            reason_code="artifact_missing",
            artifact_reference=ref,
        )
    if not resolved.is_file():
        raise AxisTaxonomyError(
            "artifact is not a regular file",
            reason_code="artifact_not_a_file",
            artifact_reference=ref,
        )
    return resolved, ref


def _validate_run_id(eval_run_id: Any) -> str:
    if not isinstance(eval_run_id, str):
        raise AxisTaxonomyError(
            f"eval_run_id must be a string, got {type(eval_run_id).__name__}",
            reason_code="invalid_eval_run_id",
        )
    if not eval_run_id or eval_run_id != eval_run_id.strip():
        raise AxisTaxonomyError(
            "eval_run_id must be a non-empty string without leading or trailing whitespace",
            reason_code="invalid_eval_run_id",
        )
    if eval_run_id in (".", ".."):
        raise AxisTaxonomyError(
            "eval_run_id is not a valid path component", reason_code="invalid_eval_run_id"
        )
    if "/" in eval_run_id or "\\" in eval_run_id or "\x00" in eval_run_id:
        raise AxisTaxonomyError(
            "eval_run_id must be a single path component without separators or NUL",
            reason_code="invalid_eval_run_id",
        )
    if Path(eval_run_id).is_absolute() or len(Path(eval_run_id).parts) != 1:
        raise AxisTaxonomyError(
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
        raise AxisTaxonomyError(
            "artifact is not valid JSON", reason_code="json_error", artifact_reference=reference
        ) from exc
    except _DuplicateKeyControl as exc:
        raise AxisTaxonomyError(
            "artifact contains a duplicate JSON object key",
            reason_code="duplicate_key",
            artifact_reference=reference,
        ) from exc
    except _NonFiniteControl as exc:
        raise AxisTaxonomyError(
            "artifact contains a non-JSON numeric constant",
            reason_code="non_finite",
            artifact_reference=reference,
        ) from exc
    if _has_non_finite(payload):
        raise AxisTaxonomyError(
            "artifact contains a non-finite JSON number",
            reason_code="non_finite",
            artifact_reference=reference,
        )
    if not isinstance(payload, dict):
        raise AxisTaxonomyError(
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
        raise AxisTaxonomyError(
            "failed to read the artifact", reason_code="read_error", artifact_reference=ref
        ) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AxisTaxonomyError(
            "artifact is not valid UTF-8", reason_code="decode_error", artifact_reference=ref
        ) from exc
    return raw, text, ref


# --- Loader ---------------------------------------------------------------


def load_axis_taxonomy(
    path: str | Path,
    *,
    eval_root: str | Path,
    expected_sha256: str | None = None,
) -> LoadedAxisTaxonomy:
    """Load, hash-bind, and strictly validate an axis taxonomy.

    Reads the taxonomy JSON (contained under ``eval_root``, symlink-rejected),
    parses it strictly (duplicate keys, non-finite numbers, and non-object
    top-levels rejected), and validates the ``axis_taxonomy@0.1.0`` contract.
    All failures are sanitized ``AxisTaxonomyError``.
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
            raise AxisTaxonomyError(
                "axis taxonomy raw-byte hash does not match the expected hash",
                reason_code="expected_hash_mismatch",
                artifact_reference=reference,
            )
    payload = _strict_json_object(text, reference)
    try:
        model = AxisTaxonomy.model_validate(payload)
    except PydanticValidationError as exc:
        raise AxisTaxonomyError(
            "axis taxonomy failed strict contract validation",
            reason_code="model_validation",
            artifact_reference=reference,
        ) from exc
    return LoadedAxisTaxonomy(
        model=model,
        version=model.taxonomy_version,
        sha256=observed,
        artifact_reference=reference,
    )


# --- Snapshot persistence -------------------------------------------------


def persist_axis_taxonomy(
    model: AxisTaxonomy,
    *,
    eval_root: str | Path,
    eval_run_id: str,
) -> LoadedAxisTaxonomy:
    """Write the canonical taxonomy JSON (plus one terminal newline) write-once.

    Destination: ``<eval_root>/<eval_run_id>/snapshots/axis_taxonomy.json``.
    """
    validated = _revalidate(model)
    resolved_root = _validate_eval_root(eval_root)
    run_id = _validate_run_id(eval_run_id)
    run_dir = resolved_root / run_id
    if run_dir.is_symlink():
        raise AxisTaxonomyError(
            "run directory is a symlink", reason_code="run_directory_symlink"
        )
    if not run_dir.exists():
        raise AxisTaxonomyError(
            "run directory does not exist under the evaluation root",
            reason_code="run_directory_missing",
            artifact_reference=run_id,
        )
    if not run_dir.is_dir():
        raise AxisTaxonomyError(
            "run directory is not a directory",
            reason_code="run_directory_not_a_directory",
            artifact_reference=run_id,
        )
    snapshots_dir = run_dir / _SNAPSHOTS_DIR
    if snapshots_dir.is_symlink():
        raise AxisTaxonomyError(
            "run snapshots directory is a symlink",
            reason_code="snapshots_directory_symlink",
        )
    if snapshots_dir.exists():
        if not snapshots_dir.is_dir():
            raise AxisTaxonomyError(
                "run snapshots path is not a directory",
                reason_code="snapshots_directory_not_a_directory",
            )
    else:
        try:
            snapshots_dir.mkdir(exist_ok=False)
        except OSError as exc:
            raise AxisTaxonomyError(
                "failed to create the run snapshots directory",
                reason_code="write_error",
                artifact_reference=f"{run_id}/{_SNAPSHOTS_DIR}",
            ) from exc
    reference = f"{run_id}/{_SNAPSHOTS_DIR}/{_SNAPSHOT_FILENAME}"
    dest = snapshots_dir / _SNAPSHOT_FILENAME
    if dest.is_symlink() or dest.exists():
        raise AxisTaxonomyError(
            "snapshot already exists; snapshots are write-once",
            reason_code="snapshot_exists",
            artifact_reference=reference,
        )
    data = canonical_contract_bytes(validated.model_dump(mode="json", exclude_unset=True)) + b"\n"
    expected = sha256_bytes(data)
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise AxisTaxonomyError(
            "snapshot already exists; snapshots are write-once",
            reason_code="snapshot_exists",
            artifact_reference=reference,
        ) from exc
    except OSError as exc:
        raise AxisTaxonomyError(
            "failed to create the snapshot", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise AxisTaxonomyError(
            "failed to write the snapshot", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        observed = sha256_bytes(dest.read_bytes())
    except OSError as exc:
        raise AxisTaxonomyError(
            "failed to re-read the snapshot for verification",
            reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    if observed != expected:
        raise AxisTaxonomyError(
            "persisted snapshot re-read to a different hash",
            reason_code="destination_hash_mismatch",
            artifact_reference=reference,
        )
    return LoadedAxisTaxonomy(
        model=validated,
        version=validated.taxonomy_version,
        sha256=observed,
        artifact_reference=reference,
    )
