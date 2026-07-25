"""Prediction normalization and canonical prediction envelopes (Slice 6).

Slice 6 converts manifest-bearing prediction artifacts into the existing
canonical ``PredictionEnvelope`` records (SPEC-022, ADR-012) and persists the
normalized envelopes as deterministic JSONL inside an existing Slice 5
evaluation-run directory. It also imports an ad hoc file into a
manifest-bearing prediction input snapshot whose manifest hash a later caller
can pin in an ``EvaluationRunManifest``.

The canonical envelope is a provenance/reference wrapper: stage-specific
prediction *content* stays in source artifacts named by
``PredictionEnvelope.source_references`` (declared and hash-bound by the
prediction artifact manifest, path-checked and hash-verified here, never
semantically parsed). Prediction content is never placed into
``prompt_model_metadata``. Slice 6 executes no assertions, computes no
metrics, and assigns no execution status or gate verdict; the existing
``PredictionEnvelope`` model is used unchanged.

No live model or provider adapter exists in Phase 1: provider-native parsing,
raw provider-response persistence, retries, token usage and refusal detection
are out of scope. Immutability here means refuse-to-overwrite directories,
exclusive-create files and read-back hash verification — not OS-level
immutability or cross-process guarantees.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError as PydanticValidationError,
    field_validator,
)

from .cases import InvalidEvaluationRootError
from .contracts import canonical_contract_bytes, model_contract_hash
from .models import ContractMetadata, PredictionEnvelope
from .runs import _load_run_manifest_any_supported_version
from ..universe.io_utils import sha256_bytes

_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"
_IDENTITY_PATTERN = r"^\S(.*\S)?$"

_MANIFEST_CONTRACT_ID = "prediction_artifact_manifest"
_MANIFEST_CONTRACT_VERSION = "0.1.0"

_PREDICTIONS_DIR = "predictions"
_NORMALIZED_FILENAME = "normalized_envelopes.jsonl"
_SNAPSHOT_MANIFEST_FILENAME = "prediction_run_manifest.json"
_SNAPSHOT_ENVELOPES_FILENAME = "envelopes.jsonl"
_SNAPSHOT_SOURCES_DIR = "sources"
_SNAPSHOT_SOURCE_FILENAME = "prediction_source.bin"

BindingKind = Literal[
    "prediction_run_id_mismatch",
    "prediction_manifest_hash_mismatch",
    "prediction_manifest_reference_mismatch",
    "undeclared_source_reference",
    "envelopes_reference_collision",
    "source_reference_collision",
]


def _is_safe_reference(value: Any) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if "\\" in value or "\x00" in value:
        return False
    p = Path(value)
    if p.is_absolute():
        return False
    parts = value.split("/")
    return all(part not in ("", ".", "..") for part in parts)


# --- Artifact-input models ------------------------------------------------


class _Slice6StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PredictionSourceArtifact(_Slice6StrictModel):
    """One declared, hash-bound source artifact for a prediction run."""

    reference: str
    sha256: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)

    @field_validator("reference")
    @classmethod
    def _safe_reference(cls, value: str) -> str:
        if not _is_safe_reference(value):
            raise ValueError(
                "source artifact reference must be a non-blank safe "
                "source-root-relative POSIX path"
            )
        return value


class _ContractStamped(_Slice6StrictModel):
    """Local contract-stamped base (mirrors models.ContractStampedModel).

    Reimplemented module-locally to avoid importing a non-exported base;
    identity/hash semantics are identical.
    """

    _contract_id: ClassVar[str]
    _contract_version: ClassVar[str] = "0.1.0"

    contract: ContractMetadata


class PredictionArtifactManifest(_ContractStamped):
    """Manifest describing a manifest-bearing prediction artifact."""

    _contract_id: ClassVar[str] = _MANIFEST_CONTRACT_ID

    prediction_run_id: str = Field(min_length=1, pattern=_IDENTITY_PATTERN)
    envelopes_reference: str
    envelopes_sha256: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    record_count: int = Field(ge=0)
    source_artifacts: tuple[PredictionSourceArtifact, ...]

    @field_validator("envelopes_reference")
    @classmethod
    def _safe_envelopes_reference(cls, value: str) -> str:
        if not _is_safe_reference(value):
            raise ValueError(
                "envelopes_reference must be a non-blank safe "
                "source-root-relative POSIX path"
            )
        return value


# --- Result models --------------------------------------------------------


class ImportedPredictionSnapshot(_Slice6StrictModel):
    snapshot_id: str
    snapshot_directory_reference: str
    manifest_reference: str
    manifest: PredictionArtifactManifest
    manifest_sha256: str
    envelopes_reference: str
    envelopes_sha256: str
    source_reference: str
    source_sha256: str
    envelope: PredictionEnvelope


class NormalizedPredictionRun(_Slice6StrictModel):
    eval_run_id: str
    prediction_run_id: str
    artifact_reference: str
    sha256: str
    source_manifest_reference: str
    source_manifest_sha256: str
    envelopes: tuple[PredictionEnvelope, ...]


class LoadedPredictionEnvelopes(_Slice6StrictModel):
    eval_run_id: str
    artifact_reference: str
    sha256: str
    envelopes: tuple[PredictionEnvelope, ...]


# --- Exceptions -----------------------------------------------------------


class EnvelopeError(Exception):
    """Base class for Slice 6 prediction failures; never raised directly."""

    def __init__(
        self,
        message: str,
        *,
        artifact_kind: str | None = None,
        artifact_reference: str | None = None,
        eval_run_id: str | None = None,
        snapshot_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.artifact_kind = artifact_kind
        self.artifact_reference = artifact_reference
        self.eval_run_id = eval_run_id
        self.snapshot_id = snapshot_id


class InvalidSnapshotIdError(EnvelopeError):
    """The supplied snapshot ID is not a usable single path component."""


class PredictionSnapshotExistsError(EnvelopeError):
    """The target snapshot directory path already exists in some form."""


class NormalizedPredictionExistsError(EnvelopeError):
    """The normalized predictions directory already exists in some form."""


class EnvelopePathEscapeError(EnvelopeError):
    """An artifact path resolves outside its authorized root."""


class EnvelopeArtifactMissingError(EnvelopeError):
    """A required artifact does not exist."""


class EnvelopeArtifactNotAFileError(EnvelopeError):
    """A required artifact exists but is not a regular file."""


class EnvelopeArtifactReadError(EnvelopeError):
    """Reading an artifact failed."""


class EnvelopeDecodeError(EnvelopeError):
    """An artifact's bytes are not valid UTF-8."""


class EnvelopeJsonError(EnvelopeError):
    """An artifact is not acceptable strict JSON/JSONL."""

    def __init__(
        self,
        message: str,
        *,
        artifact_kind: str | None = None,
        artifact_reference: str | None = None,
        eval_run_id: str | None = None,
        line_number: int | None = None,
        duplicate_key: str | None = None,
        constant_name: str | None = None,
    ) -> None:
        super().__init__(
            message, artifact_kind=artifact_kind, artifact_reference=artifact_reference,
            eval_run_id=eval_run_id,
        )
        self.line_number = line_number
        self.duplicate_key = duplicate_key
        self.constant_name = constant_name


class EnvelopeTopLevelTypeError(EnvelopeError):
    """A parsed document or line is not a JSON object."""

    def __init__(
        self,
        message: str,
        *,
        artifact_kind: str | None = None,
        artifact_reference: str | None = None,
        observed_type: str | None = None,
        line_number: int | None = None,
    ) -> None:
        super().__init__(
            message, artifact_kind=artifact_kind, artifact_reference=artifact_reference
        )
        self.observed_type = observed_type
        self.line_number = line_number


class EnvelopeModelValidationError(EnvelopeError):
    """A document or line failed model/contract validation."""

    def __init__(
        self,
        message: str,
        *,
        artifact_kind: str | None = None,
        artifact_reference: str | None = None,
        line_number: int | None = None,
        field_locations: tuple[str, ...] = (),
        error_types: tuple[str, ...] = (),
    ) -> None:
        super().__init__(
            message, artifact_kind=artifact_kind, artifact_reference=artifact_reference
        )
        self.line_number = line_number
        self.field_locations = field_locations
        self.error_types = error_types


class EnvelopeDuplicateRecordIdError(EnvelopeError):
    """Two prediction records share a prediction_record_id."""

    def __init__(
        self,
        message: str,
        *,
        artifact_kind: str | None = None,
        artifact_reference: str | None = None,
        duplicate_record_id: str | None = None,
        line_number: int | None = None,
    ) -> None:
        super().__init__(
            message, artifact_kind=artifact_kind, artifact_reference=artifact_reference
        )
        self.duplicate_record_id = duplicate_record_id
        self.line_number = line_number


class EnvelopeHashMismatchError(EnvelopeError):
    """A declared artifact hash does not match observed raw bytes."""

    def __init__(
        self,
        message: str,
        *,
        artifact_kind: str | None = None,
        artifact_reference: str | None = None,
        expected_sha256: str | None = None,
        observed_sha256: str | None = None,
    ) -> None:
        super().__init__(
            message, artifact_kind=artifact_kind, artifact_reference=artifact_reference
        )
        self.expected_sha256 = expected_sha256
        self.observed_sha256 = observed_sha256


class EnvelopeReferenceBindingError(EnvelopeError):
    """A reference-level binding constraint is violated."""

    def __init__(
        self,
        message: str,
        *,
        artifact_kind: str | None = None,
        artifact_reference: str | None = None,
        binding_kind: BindingKind | None = None,
        prediction_record_id: str | None = None,
    ) -> None:
        super().__init__(
            message, artifact_kind=artifact_kind, artifact_reference=artifact_reference
        )
        self.binding_kind = binding_kind
        self.prediction_record_id = prediction_record_id


class PredictionRunBindingError(EnvelopeError):
    """The prediction artifact does not bind to the pinned prediction run."""

    def __init__(
        self,
        message: str,
        *,
        artifact_kind: str | None = None,
        artifact_reference: str | None = None,
        eval_run_id: str | None = None,
        binding_kind: BindingKind | None = None,
        expected_sha256: str | None = None,
        observed_sha256: str | None = None,
    ) -> None:
        super().__init__(
            message, artifact_kind=artifact_kind, artifact_reference=artifact_reference,
            eval_run_id=eval_run_id,
        )
        self.binding_kind = binding_kind
        self.expected_sha256 = expected_sha256
        self.observed_sha256 = observed_sha256


class EnvelopeRecordCountMismatchError(EnvelopeError):
    """The manifest record_count differs from the descriptor record count."""

    def __init__(
        self,
        message: str,
        *,
        artifact_kind: str | None = None,
        artifact_reference: str | None = None,
        expected_count: int | None = None,
        observed_count: int | None = None,
    ) -> None:
        super().__init__(
            message, artifact_kind=artifact_kind, artifact_reference=artifact_reference
        )
        self.expected_count = expected_count
        self.observed_count = observed_count


class EnvelopeWriteError(EnvelopeError):
    """Writing a normalized/snapshot artifact failed."""


class EnvelopeDestinationHashMismatchError(EnvelopeError):
    """A written artifact re-read to a different hash."""

    def __init__(
        self,
        message: str,
        *,
        artifact_kind: str | None = None,
        artifact_reference: str | None = None,
        expected_sha256: str | None = None,
        observed_sha256: str | None = None,
    ) -> None:
        super().__init__(
            message, artifact_kind=artifact_kind, artifact_reference=artifact_reference
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


# --- Private root/path helpers (module-local; not shared) -----------------


def _validate_root(root: str | Path, label: str) -> Path:
    if not isinstance(root, (str, Path)):
        raise InvalidEvaluationRootError(
            f"{label} must be an explicit str or Path root",
            observed_type=type(root).__name__,
        )
    if isinstance(root, str) and root == "":
        raise InvalidEvaluationRootError(
            f"{label} must not be an empty string; supply the root explicitly",
            supplied_root="",
        )
    path = Path(root)
    if not path.exists():
        raise InvalidEvaluationRootError(
            f"{label} {str(root)!r} does not exist", supplied_root=str(root)
        )
    if not path.is_dir():
        raise InvalidEvaluationRootError(
            f"{label} {str(root)!r} is not a directory", supplied_root=str(root)
        )
    return path.resolve()


def _validate_component(value: Any, label: str, exc_cls, **exc_attrs: Any) -> str:
    if not isinstance(value, str):
        raise exc_cls(f"{label} must be a string, got {type(value).__name__}", **exc_attrs)
    if not value or value != value.strip():
        raise exc_cls(
            f"{label} must be a non-empty string without leading or trailing whitespace",
            **exc_attrs,
        )
    if value in (".", ".."):
        raise exc_cls(f"{label} {value!r} is not a valid path component", **exc_attrs)
    if "/" in value or "\\" in value or "\x00" in value:
        raise exc_cls(
            f"{label} must be a single path component without separators or NUL", **exc_attrs
        )
    if Path(value).is_absolute() or len(Path(value).parts) != 1:
        raise exc_cls(f"{label} {value!r} must be exactly one relative component", **exc_attrs)
    return value


def _resolve_and_read(
    root: Path, reference: str, *, artifact_kind: str, eval_run_id: str | None = None
) -> tuple[bytes, str, str]:
    """Resolve one safe reference under ``root``; return (bytes, sha256, ref).

    Containment is enforced on resolved paths before symlink classification;
    a contained (existing or dangling) final-component symlink is a non-file;
    only an ordinary absent non-symlink is missing.
    """
    raw = root / reference
    resolved = raw.resolve()
    if not resolved.is_relative_to(root):
        raise EnvelopePathEscapeError(
            f"{artifact_kind} reference resolves outside its authorized root",
            artifact_kind=artifact_kind, eval_run_id=eval_run_id,
        )
    safe_ref = resolved.relative_to(root).as_posix()
    if raw.is_symlink() or resolved.is_symlink():
        raise EnvelopeArtifactNotAFileError(
            f"{artifact_kind} {safe_ref!r} is not a regular file",
            artifact_kind=artifact_kind, artifact_reference=safe_ref, eval_run_id=eval_run_id,
        )
    if not resolved.exists():
        raise EnvelopeArtifactMissingError(
            f"{artifact_kind} {safe_ref!r} does not exist",
            artifact_kind=artifact_kind, artifact_reference=safe_ref, eval_run_id=eval_run_id,
        )
    if not resolved.is_file():
        raise EnvelopeArtifactNotAFileError(
            f"{artifact_kind} {safe_ref!r} is not a regular file",
            artifact_kind=artifact_kind, artifact_reference=safe_ref, eval_run_id=eval_run_id,
        )
    try:
        data = resolved.read_bytes()
    except OSError as exc:
        raise EnvelopeArtifactReadError(
            f"failed to read {artifact_kind} {safe_ref!r}",
            artifact_kind=artifact_kind, artifact_reference=safe_ref, eval_run_id=eval_run_id,
        ) from exc
    return data, sha256_bytes(data), safe_ref


def _decode(data: bytes, kind: str, reference: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EnvelopeDecodeError(
            f"{kind} {reference!r} is not valid UTF-8",
            artifact_kind=kind, artifact_reference=reference,
        ) from exc


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


def _assert_finite(payload: Any) -> str | None:
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


def _parse_json_value(text: str, kind: str, reference: str, line_number: int | None) -> Any:
    try:
        payload = json.loads(
            text, object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except json.JSONDecodeError as exc:
        raise EnvelopeJsonError(
            f"{kind} {reference!r} is not valid JSON: {exc.msg} "
            f"(line {exc.lineno} column {exc.colno})",
            artifact_kind=kind, artifact_reference=reference, line_number=line_number,
        ) from exc
    except _DuplicateKeyControl as exc:
        raise EnvelopeJsonError(
            f"{kind} {reference!r} contains a duplicate JSON object key {exc.key!r}",
            artifact_kind=kind, artifact_reference=reference,
            line_number=line_number, duplicate_key=exc.key,
        ) from exc
    except _NonFiniteControl as exc:
        raise EnvelopeJsonError(
            f"{kind} {reference!r} contains the non-JSON constant {exc.constant_name}",
            artifact_kind=kind, artifact_reference=reference,
            line_number=line_number, constant_name=exc.constant_name,
        ) from exc
    non_finite = _assert_finite(payload)
    if non_finite is not None:
        raise EnvelopeJsonError(
            f"{kind} {reference!r} contains a non-finite JSON number ({non_finite})",
            artifact_kind=kind, artifact_reference=reference,
            line_number=line_number, constant_name=non_finite,
        )
    return payload


def _require_object(payload: Any, kind: str, reference: str, line_number: int | None) -> dict:
    if not isinstance(payload, dict):
        raise EnvelopeTopLevelTypeError(
            f"{kind} {reference!r} must be a JSON object, got {type(payload).__name__}",
            artifact_kind=kind, artifact_reference=reference,
            observed_type=type(payload).__name__, line_number=line_number,
        )
    return payload


def _model_pairs(exc: PydanticValidationError) -> tuple[tuple[str, ...], tuple[str, ...]]:
    pairs = sorted(("/".join(str(p) for p in e["loc"]), e["type"]) for e in exc.errors())
    return tuple(loc for loc, _ in pairs), tuple(t for _, t in pairs)


def _validate_manifest_model(payload: dict, kind: str, reference: str) -> PredictionArtifactManifest:
    try:
        return PredictionArtifactManifest.model_validate(payload)
    except PydanticValidationError as exc:
        locs, types = _model_pairs(exc)
        raise EnvelopeModelValidationError(
            f"{kind} {reference!r} failed manifest model/contract validation",
            artifact_kind=kind, artifact_reference=reference,
            field_locations=locs, error_types=types,
        ) from exc


def _verify_manifest_contract(manifest: PredictionArtifactManifest, kind: str, reference: str) -> None:
    expected = model_contract_hash(
        PredictionArtifactManifest, _MANIFEST_CONTRACT_ID, _MANIFEST_CONTRACT_VERSION
    )
    c = manifest.contract
    if (
        c.contract_id != _MANIFEST_CONTRACT_ID
        or c.contract_version != _MANIFEST_CONTRACT_VERSION
        or c.contract_hash != expected
    ):
        raise EnvelopeModelValidationError(
            f"{kind} {reference!r} carries an incorrect prediction-artifact-manifest "
            "contract stamp",
            artifact_kind=kind, artifact_reference=reference,
            field_locations=("contract",), error_types=("contract_stamp_mismatch",),
        )


def _verify_envelope_contract(envelope: PredictionEnvelope) -> bool:
    expected = model_contract_hash(PredictionEnvelope, "prediction_envelope", "0.1.0")
    c = envelope.contract
    return (
        c.contract_id == "prediction_envelope"
        and c.contract_version == "0.1.0"
        and c.contract_hash == expected
    )


def _parse_envelope_jsonl(
    data: bytes, kind: str, reference: str, eval_run_id: str | None = None
) -> tuple[PredictionEnvelope, ...]:
    text = _decode(data, kind, reference)
    if text == "":
        return ()
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    envelopes: list[PredictionEnvelope] = []
    seen_ids: set[str] = set()
    for index, line in enumerate(lines):
        ln = index + 1
        if not line or not line.strip():
            raise EnvelopeJsonError(
                f"{kind} {reference!r} line {ln} is blank; envelope logs allow no blank lines",
                artifact_kind=kind, artifact_reference=reference, line_number=ln,
            )
        payload = _require_object(_parse_json_value(line, kind, reference, ln), kind, reference, ln)
        try:
            envelope = PredictionEnvelope.model_validate(payload)
        except PydanticValidationError as exc:
            locs, types = _model_pairs(exc)
            raise EnvelopeModelValidationError(
                f"{kind} {reference!r} line {ln} failed PredictionEnvelope validation",
                artifact_kind=kind, artifact_reference=reference,
                line_number=ln, field_locations=locs, error_types=types,
            ) from exc
        if envelope.prediction_record_id in seen_ids:
            raise EnvelopeDuplicateRecordIdError(
                f"{kind} {reference!r} repeats prediction_record_id "
                f"{envelope.prediction_record_id!r}",
                artifact_kind=kind, artifact_reference=reference,
                duplicate_record_id=envelope.prediction_record_id, line_number=ln,
            )
        seen_ids.add(envelope.prediction_record_id)
        envelopes.append(envelope)
    return tuple(envelopes)


def _canonical_envelope_line(envelope: PredictionEnvelope) -> bytes:
    payload = envelope.model_dump(mode="json", exclude_unset=True)
    return canonical_contract_bytes(payload)


def _serialize_envelopes_jsonl(envelopes: tuple[PredictionEnvelope, ...]) -> bytes:
    if not envelopes:
        return b""
    return b"".join(_canonical_envelope_line(e) + b"\n" for e in envelopes)


def _exclusive_write(path: Path, data: bytes, reference: str, *, kind: str) -> None:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise EnvelopeWriteError(
            f"{kind} artifact {reference!r} already exists; artifacts are write-once",
            artifact_kind=kind, artifact_reference=reference,
        ) from exc
    except OSError as exc:
        raise EnvelopeWriteError(
            f"failed to create {kind} artifact {reference!r}",
            artifact_kind=kind, artifact_reference=reference,
        ) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    except OSError as exc:
        raise EnvelopeWriteError(
            f"failed to write {kind} artifact {reference!r}",
            artifact_kind=kind, artifact_reference=reference,
        ) from exc


def _read_back_hash(path: Path, reference: str, *, kind: str) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise EnvelopeWriteError(
            f"failed to re-read {kind} artifact {reference!r} for verification",
            artifact_kind=kind, artifact_reference=reference,
        ) from exc


# --- Manifest-bearing artifact loading + binding --------------------------


def _load_prediction_artifact(
    prediction_manifest_path: str | Path, *, source_root: Path
) -> tuple[PredictionArtifactManifest, str, str, tuple[PredictionEnvelope, ...], str]:
    """Load and internally validate one manifest-bearing prediction artifact.

    Returns (manifest, manifest_reference, manifest_sha256, envelopes,
    envelopes_reference). Source-artifact bytes are not read here.
    """
    requested = Path(prediction_manifest_path)
    if requested.is_absolute():
        candidate = requested
    else:
        candidate = source_root / requested
    resolved = candidate.resolve()
    if not resolved.is_relative_to(source_root):
        raise EnvelopePathEscapeError(
            "prediction manifest resolves outside the source root",
            artifact_kind="prediction_manifest",
        )
    manifest_reference = resolved.relative_to(source_root).as_posix()
    raw = source_root / manifest_reference
    if raw.is_symlink() or resolved.is_symlink():
        raise EnvelopeArtifactNotAFileError(
            f"prediction manifest {manifest_reference!r} is not a regular file",
            artifact_kind="prediction_manifest", artifact_reference=manifest_reference,
        )
    if not resolved.exists():
        raise EnvelopeArtifactMissingError(
            f"prediction manifest {manifest_reference!r} does not exist",
            artifact_kind="prediction_manifest", artifact_reference=manifest_reference,
        )
    if not resolved.is_file():
        raise EnvelopeArtifactNotAFileError(
            f"prediction manifest {manifest_reference!r} is not a regular file",
            artifact_kind="prediction_manifest", artifact_reference=manifest_reference,
        )
    try:
        manifest_bytes = resolved.read_bytes()
    except OSError as exc:
        raise EnvelopeArtifactReadError(
            f"failed to read prediction manifest {manifest_reference!r}",
            artifact_kind="prediction_manifest", artifact_reference=manifest_reference,
        ) from exc
    manifest_sha256 = sha256_bytes(manifest_bytes)
    text = _decode(manifest_bytes, "prediction_manifest", manifest_reference)
    payload = _require_object(
        _parse_json_value(text, "prediction_manifest", manifest_reference, None),
        "prediction_manifest", manifest_reference, None,
    )
    manifest = _validate_manifest_model(payload, "prediction_manifest", manifest_reference)
    _verify_manifest_contract(manifest, "prediction_manifest", manifest_reference)

    source_refs = [s.reference for s in manifest.source_artifacts]
    seen: set[str] = set()
    for ref in source_refs:
        if ref in seen:
            raise EnvelopeReferenceBindingError(
                f"prediction manifest {manifest_reference!r} declares source reference "
                f"{ref!r} more than once",
                artifact_kind="prediction_manifest", artifact_reference=manifest_reference,
                binding_kind="source_reference_collision",
            )
        seen.add(ref)
    if manifest.envelopes_reference in seen:
        raise EnvelopeReferenceBindingError(
            f"prediction manifest {manifest_reference!r} envelopes_reference collides with "
            "a declared source artifact",
            artifact_kind="prediction_manifest", artifact_reference=manifest_reference,
            binding_kind="envelopes_reference_collision",
        )
    if manifest_reference in seen:
        raise EnvelopeReferenceBindingError(
            f"prediction manifest {manifest_reference!r} is declared as its own source artifact",
            artifact_kind="prediction_manifest", artifact_reference=manifest_reference,
            binding_kind="source_reference_collision",
        )

    env_bytes, env_sha, env_ref = _resolve_and_read(
        source_root, manifest.envelopes_reference, artifact_kind="envelope_descriptor"
    )
    if env_sha != manifest.envelopes_sha256:
        raise EnvelopeHashMismatchError(
            f"envelope descriptor {env_ref!r} raw hash does not match the manifest hash",
            artifact_kind="envelope_descriptor", artifact_reference=env_ref,
            expected_sha256=manifest.envelopes_sha256, observed_sha256=env_sha,
        )
    envelopes = _parse_envelope_jsonl(env_bytes, "envelope_descriptor", env_ref)
    if len(envelopes) != manifest.record_count:
        raise EnvelopeRecordCountMismatchError(
            f"envelope descriptor {env_ref!r} record count differs from the manifest",
            artifact_kind="envelope_descriptor", artifact_reference=env_ref,
            expected_count=manifest.record_count, observed_count=len(envelopes),
        )
    for envelope in envelopes:
        if envelope.prediction_run_manifest_reference != manifest_reference:
            raise EnvelopeReferenceBindingError(
                f"envelope {envelope.prediction_record_id!r} manifest reference does not equal "
                "the source manifest reference",
                artifact_kind="envelope_descriptor", artifact_reference=env_ref,
                binding_kind="prediction_manifest_reference_mismatch",
                prediction_record_id=envelope.prediction_record_id,
            )
        for src_ref in envelope.source_references:
            if src_ref not in seen:
                raise EnvelopeReferenceBindingError(
                    f"envelope {envelope.prediction_record_id!r} references undeclared source "
                    f"{src_ref!r}",
                    artifact_kind="envelope_descriptor", artifact_reference=env_ref,
                    binding_kind="undeclared_source_reference",
                    prediction_record_id=envelope.prediction_record_id,
                )
    return manifest, manifest_reference, manifest_sha256, envelopes, env_ref


# --- Public API -----------------------------------------------------------


def import_ad_hoc_prediction_file(
    source_path: str | Path,
    *,
    source_root: str | Path,
    snapshot_root: str | Path,
    snapshot_id: str,
    prediction_run_id: str,
    prediction_record_id: str,
    stage: str,
    prompt_model_metadata: dict[str, JsonValue],
    input_packet_hash: str,
) -> ImportedPredictionSnapshot:
    """Import one ad hoc file into a manifest-bearing prediction snapshot.

    The source file is copied byte-for-byte (never parsed or transformed); the
    caller supplies stage, prompt/model metadata and the input-packet hash. The
    returned manifest SHA-256 can be pinned as ``prediction_run_manifest_hash``
    when a Slice 5 run is later initialized.
    """
    resolved_source_root = _validate_root(source_root, "source_root")
    resolved_snapshot_root = _validate_root(snapshot_root, "snapshot_root")
    sid = _validate_component(snapshot_id, "snapshot_id", InvalidSnapshotIdError, snapshot_id=None)

    source_bytes, source_sha, _ = _resolve_and_read(
        resolved_source_root, _require_component_reference(source_path, resolved_source_root),
        artifact_kind="ad_hoc_source",
    )

    source_reference = f"{sid}/{_SNAPSHOT_SOURCES_DIR}/{_SNAPSHOT_SOURCE_FILENAME}"
    envelopes_reference = f"{sid}/{_SNAPSHOT_ENVELOPES_FILENAME}"
    manifest_reference = f"{sid}/{_SNAPSHOT_MANIFEST_FILENAME}"

    envelope_hash = model_contract_hash(PredictionEnvelope, "prediction_envelope", "0.1.0")
    try:
        envelope = PredictionEnvelope.model_validate(
            {
                "contract": {
                    "contract_id": "prediction_envelope",
                    "contract_version": "0.1.0",
                    "contract_hash": envelope_hash,
                },
                "prediction_record_id": prediction_record_id,
                "stage": stage,
                "source_references": [source_reference],
                "prompt_model_metadata": prompt_model_metadata,
                "input_packet_hash": input_packet_hash,
                "prediction_run_manifest_reference": manifest_reference,
            }
        )
    except PydanticValidationError as exc:
        locs, types = _model_pairs(exc)
        raise EnvelopeModelValidationError(
            "the generated prediction envelope failed validation for the supplied fields",
            artifact_kind="envelope_descriptor", field_locations=locs, error_types=types,
        ) from exc
    envelopes_bytes = _serialize_envelopes_jsonl((envelope,))
    envelopes_sha = sha256_bytes(envelopes_bytes)

    manifest_hash = model_contract_hash(
        PredictionArtifactManifest, _MANIFEST_CONTRACT_ID, _MANIFEST_CONTRACT_VERSION
    )
    manifest = PredictionArtifactManifest.model_validate(
        {
            "contract": {
                "contract_id": _MANIFEST_CONTRACT_ID,
                "contract_version": _MANIFEST_CONTRACT_VERSION,
                "contract_hash": manifest_hash,
            },
            "prediction_run_id": prediction_run_id,
            "envelopes_reference": envelopes_reference,
            "envelopes_sha256": envelopes_sha,
            "record_count": 1,
            "source_artifacts": [{"reference": source_reference, "sha256": source_sha}],
        }
    )
    manifest_bytes = canonical_contract_bytes(manifest.model_dump(mode="json", exclude_unset=True))
    manifest_sha = sha256_bytes(manifest_bytes)

    snapshot_dir = resolved_snapshot_root / sid
    if snapshot_dir.exists() or snapshot_dir.is_symlink():
        raise PredictionSnapshotExistsError(
            f"snapshot directory {sid!r} already exists; snapshots are immutable",
            snapshot_id=sid, artifact_reference=sid,
        )
    try:
        snapshot_dir.mkdir(exist_ok=False)
        (snapshot_dir / _SNAPSHOT_SOURCES_DIR).mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise PredictionSnapshotExistsError(
            f"snapshot directory {sid!r} already exists; snapshots are immutable",
            snapshot_id=sid, artifact_reference=sid,
        ) from exc
    except OSError as exc:
        raise EnvelopeWriteError(
            f"failed to create snapshot directory {sid!r}",
            artifact_kind="snapshot_directory", artifact_reference=sid, snapshot_id=sid,
        ) from exc

    src_dest = resolved_snapshot_root / source_reference
    _exclusive_write(src_dest, source_bytes, source_reference, kind="ad_hoc_source")
    if _read_back_hash(src_dest, source_reference, kind="ad_hoc_source") != source_sha:
        raise EnvelopeDestinationHashMismatchError(
            f"written source {source_reference!r} re-read to a different hash",
            artifact_kind="ad_hoc_source", artifact_reference=source_reference,
            expected_sha256=source_sha,
        )
    env_dest = resolved_snapshot_root / envelopes_reference
    _exclusive_write(env_dest, envelopes_bytes, envelopes_reference, kind="envelope_descriptor")
    if _read_back_hash(env_dest, envelopes_reference, kind="envelope_descriptor") != envelopes_sha:
        raise EnvelopeDestinationHashMismatchError(
            f"written envelope descriptor {envelopes_reference!r} re-read to a different hash",
            artifact_kind="envelope_descriptor", artifact_reference=envelopes_reference,
            expected_sha256=envelopes_sha,
        )
    man_dest = resolved_snapshot_root / manifest_reference
    _exclusive_write(man_dest, manifest_bytes, manifest_reference, kind="prediction_manifest")
    if _read_back_hash(man_dest, manifest_reference, kind="prediction_manifest") != manifest_sha:
        raise EnvelopeDestinationHashMismatchError(
            f"written prediction manifest {manifest_reference!r} re-read to a different hash",
            artifact_kind="prediction_manifest", artifact_reference=manifest_reference,
            expected_sha256=manifest_sha,
        )

    return ImportedPredictionSnapshot(
        snapshot_id=sid,
        snapshot_directory_reference=sid,
        manifest_reference=manifest_reference,
        manifest=manifest,
        manifest_sha256=manifest_sha,
        envelopes_reference=envelopes_reference,
        envelopes_sha256=envelopes_sha,
        source_reference=source_reference,
        source_sha256=source_sha,
        envelope=envelope,
    )


def _require_component_reference(source_path: str | Path, resolved_root: Path) -> str:
    """Resolve an ad hoc source path to a safe root-relative reference."""
    requested = Path(source_path)
    candidate = requested if requested.is_absolute() else resolved_root / requested
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise EnvelopePathEscapeError(
            "ad hoc source resolves outside the source root", artifact_kind="ad_hoc_source"
        )
    return resolved.relative_to(resolved_root).as_posix()


def normalize_prediction_artifact(
    prediction_manifest_path: str | Path,
    *,
    source_root: str | Path,
    eval_root: str | Path,
    eval_run_id: str,
) -> NormalizedPredictionRun:
    """Normalize a manifest-bearing prediction artifact into an existing run.

    Validates that the source manifest binds to the Slice 5 run manifest's
    pinned prediction run ID and manifest hash, verifies every declared source
    artifact, and persists deterministic normalized envelopes JSONL at the
    fixed path. The Slice 5 run manifest is never rewritten; source artifacts
    are verified but not copied into the run.
    """
    resolved_source_root = _validate_root(source_root, "source_root")
    resolved_eval_root = _validate_root(eval_root, "eval_root")
    loaded_run = _load_run_manifest_any_supported_version(eval_run_id, eval_root=resolved_eval_root)
    run_manifest = loaded_run.manifest

    manifest, manifest_reference, manifest_sha256, envelopes, _ = _load_prediction_artifact(
        prediction_manifest_path, source_root=resolved_source_root
    )

    if manifest_sha256 != run_manifest.prediction_run_manifest_hash:
        raise PredictionRunBindingError(
            "prediction manifest raw hash does not match the run manifest pin",
            artifact_kind="prediction_manifest", artifact_reference=manifest_reference,
            eval_run_id=run_manifest.eval_run_id, binding_kind="prediction_manifest_hash_mismatch",
            expected_sha256=run_manifest.prediction_run_manifest_hash, observed_sha256=manifest_sha256,
        )
    if manifest.prediction_run_id != run_manifest.prediction_run_id:
        raise PredictionRunBindingError(
            "prediction manifest run ID does not match the run manifest pin",
            artifact_kind="prediction_manifest", artifact_reference=manifest_reference,
            eval_run_id=run_manifest.eval_run_id, binding_kind="prediction_run_id_mismatch",
        )

    for source in manifest.source_artifacts:
        _, src_sha, src_ref = _resolve_and_read(
            resolved_source_root, source.reference, artifact_kind="prediction_source",
            eval_run_id=run_manifest.eval_run_id,
        )
        if src_sha != source.sha256:
            raise EnvelopeHashMismatchError(
                f"prediction source {src_ref!r} raw hash does not match the manifest hash",
                artifact_kind="prediction_source", artifact_reference=src_ref,
                expected_sha256=source.sha256, observed_sha256=src_sha,
            )

    predictions_dir = resolved_eval_root / eval_run_id / _PREDICTIONS_DIR
    artifact_reference = f"{eval_run_id}/{_PREDICTIONS_DIR}/{_NORMALIZED_FILENAME}"
    if predictions_dir.exists() or predictions_dir.is_symlink():
        raise NormalizedPredictionExistsError(
            f"normalized predictions directory {eval_run_id}/{_PREDICTIONS_DIR} already exists",
            artifact_kind="predictions_directory",
            artifact_reference=f"{eval_run_id}/{_PREDICTIONS_DIR}", eval_run_id=eval_run_id,
        )
    try:
        predictions_dir.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise NormalizedPredictionExistsError(
            f"normalized predictions directory {eval_run_id}/{_PREDICTIONS_DIR} already exists",
            artifact_kind="predictions_directory",
            artifact_reference=f"{eval_run_id}/{_PREDICTIONS_DIR}", eval_run_id=eval_run_id,
        ) from exc
    except OSError as exc:
        raise EnvelopeWriteError(
            f"failed to create normalized predictions directory for {eval_run_id!r}",
            artifact_kind="predictions_directory", eval_run_id=eval_run_id,
        ) from exc

    normalized_bytes = _serialize_envelopes_jsonl(envelopes)
    normalized_sha = sha256_bytes(normalized_bytes)
    dest = predictions_dir / _NORMALIZED_FILENAME
    _exclusive_write(dest, normalized_bytes, artifact_reference, kind="normalized_envelopes")
    if _read_back_hash(dest, artifact_reference, kind="normalized_envelopes") != normalized_sha:
        raise EnvelopeDestinationHashMismatchError(
            f"normalized envelopes {artifact_reference!r} re-read to a different hash",
            artifact_kind="normalized_envelopes", artifact_reference=artifact_reference,
            expected_sha256=normalized_sha,
        )

    return NormalizedPredictionRun(
        eval_run_id=eval_run_id,
        prediction_run_id=run_manifest.prediction_run_id,
        artifact_reference=artifact_reference,
        sha256=normalized_sha,
        source_manifest_reference=manifest_reference,
        source_manifest_sha256=manifest_sha256,
        envelopes=envelopes,
    )


def load_prediction_envelopes(
    eval_run_id: str, *, eval_root: str | Path
) -> LoadedPredictionEnvelopes:
    """Load normalized prediction envelopes from a fixed run-directory path.

    Validates the Slice 5 run manifest, rejects symlinked run/predictions
    directories and the normalized file, and re-reads the fixed
    ``predictions/normalized_envelopes.jsonl`` with the same strict JSONL
    rules. No source root is required and no source artifact is revalidated.
    """
    resolved_eval_root = _validate_root(eval_root, "eval_root")
    _load_run_manifest_any_supported_version(eval_run_id, eval_root=resolved_eval_root)
    run_dir = resolved_eval_root / eval_run_id
    predictions_dir = run_dir / _PREDICTIONS_DIR
    artifact_reference = f"{eval_run_id}/{_PREDICTIONS_DIR}/{_NORMALIZED_FILENAME}"
    dest = predictions_dir / _NORMALIZED_FILENAME
    if run_dir.is_symlink() or predictions_dir.is_symlink() or dest.is_symlink():
        raise EnvelopeArtifactNotAFileError(
            f"normalized envelopes {artifact_reference!r} or a parent is a symlink",
            artifact_kind="normalized_envelopes", artifact_reference=artifact_reference,
            eval_run_id=eval_run_id,
        )
    if not dest.exists():
        raise EnvelopeArtifactMissingError(
            f"normalized envelopes {artifact_reference!r} does not exist",
            artifact_kind="normalized_envelopes", artifact_reference=artifact_reference,
            eval_run_id=eval_run_id,
        )
    if not dest.is_file():
        raise EnvelopeArtifactNotAFileError(
            f"normalized envelopes {artifact_reference!r} is not a regular file",
            artifact_kind="normalized_envelopes", artifact_reference=artifact_reference,
            eval_run_id=eval_run_id,
        )
    try:
        raw = dest.read_bytes()
    except OSError as exc:
        raise EnvelopeArtifactReadError(
            f"failed to read normalized envelopes {artifact_reference!r}",
            artifact_kind="normalized_envelopes", artifact_reference=artifact_reference,
            eval_run_id=eval_run_id,
        ) from exc
    observed = sha256_bytes(raw)
    envelopes = _parse_envelope_jsonl(
        raw, "normalized_envelopes", artifact_reference, eval_run_id=eval_run_id
    )
    return LoadedPredictionEnvelopes(
        eval_run_id=eval_run_id, artifact_reference=artifact_reference,
        sha256=observed, envelopes=envelopes,
    )
