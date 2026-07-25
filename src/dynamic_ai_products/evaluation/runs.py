"""Immutable evaluation-run identity and artifact persistence (Slice 5).

Slice 5 owns caller-supplied run identity, refuse-to-overwrite run-directory
creation, deterministic ``EvaluationRunManifest`` persistence and loading, and
exact-byte scoring/gate-config snapshot copying with source and destination
hash verification. It executes no predictions, assertions, metrics, gates, or
comparisons, and persists no execution status or gate verdict — the run
manifest is identity/input binding only and is write-once.

Immutability scope (a frozen Pydantic model is not a filesystem-immutable
artifact): Slice 5 provides refuse-to-overwrite directory creation
(``mkdir(exist_ok=False)``), exclusive-create file writes, and read-back hash
verification. It does not chmod files read-only, set immutable filesystem
flags, take cross-process locks, or claim durability beyond atomic creation;
later mutation by unrelated processes or root is out of scope.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError as PydanticValidationError

from .cases import InvalidEvaluationRootError
from .case_sets import case_set_snapshot_hash
from .contracts import runtime_contract_provenance
from .models import (
    CaseSetManifest,
    EvaluationRunManifest,
    EvaluationRunManifestV2,
    model_contract_hash,
)
from .references import LoadedTargetRegistry
from .scoring_config import LoadedScoringGateConfig
from .stage_profiles import (
    LoadedStageProfileRegistry,
    resolve_metric_applicability,
    stage_profile_registry_hash,
)
from ..universe.io_utils import sha256_bytes

_MANIFEST_FILENAME = "evaluation_run_manifest.json"
_SNAPSHOTS_DIR = "snapshots"
_CONFIG_SNAPSHOT_FILENAME = "scoring_gate_config.json"
_RUN_MANIFEST_CONTRACT_ID = "evaluation_run_manifest"
_RUN_MANIFEST_CONTRACT_VERSION = "0.1.0"
_RUN_MANIFEST_CONTRACT_VERSION_V2 = "0.2.0"
# Governed historical v0.1 model-contract hash, recorded as a literal so v0.1
# validation never depends solely on a regenerated or renamed model schema
# (ADR-025). Private; never exported.
_EVALUATION_RUN_MANIFEST_V1_CONTRACT_HASH = (
    "7f8909d8e7059952c933c8e30f43044178b3f8a21d4baaa77bfb5c786b38d6ee"
)
# The wrappers carry a closed union of the two accepted manifest identities.
# The models are mutually exclusive (both ``extra="forbid"`` with disjoint
# required fields and version-bound contract stamps), so the union is
# discriminated by validation with no ambiguous fallback. The v0.1 reader still
# accepts and returns only v0.1 and the v0.2 reader only v0.2.

ConsistencyKind = Literal[
    "manifest_run_id_mismatch",
    "manifest_destination_hash_mismatch",
    "config_destination_hash_mismatch",
]


class _RunStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InitializedEvaluationRun(_RunStrictModel):
    """Immutable binding information for a freshly initialized run.

    ``manifest`` is the closed union of the historical v0.1 and current v0.2
    manifest models; the concrete inner class is preserved (v0.1 from
    ``initialize_evaluation_run``, v0.2 from ``initialize_evaluation_run_v2``).
    """

    eval_run_id: str
    run_directory_reference: str
    manifest_reference: str
    config_snapshot_reference: str
    manifest: EvaluationRunManifest | EvaluationRunManifestV2
    manifest_sha256: str
    config_snapshot_sha256: str


class LoadedEvaluationRunManifest(_RunStrictModel):
    """A validated run manifest plus its raw-byte binding material.

    ``manifest`` is the closed union of the historical v0.1 and current v0.2
    manifest models; the concrete inner class is preserved by whichever loader
    produced it.
    """

    manifest: EvaluationRunManifest | EvaluationRunManifestV2
    sha256: str
    artifact_reference: str


# --- Exceptions -----------------------------------------------------------


class RunPersistenceError(Exception):
    """Base class for run-persistence failures; never raised directly."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
    ) -> None:
        super().__init__(message)
        self.eval_run_id = eval_run_id
        self.artifact_reference = artifact_reference


class InvalidRunIdError(RunPersistenceError):
    """The supplied evaluation run ID is not a usable single path component."""


class RunDirectoryExistsError(RunPersistenceError):
    """The target run directory path already exists in some form."""


class RunPathEscapeError(RunPersistenceError):
    """A run artifact path resolves outside its evaluation root."""


class RunDestinationCollisionError(RunPersistenceError):
    """A destination artifact already exists during initialization."""


class RunWriteError(RunPersistenceError):
    """Writing a run artifact failed."""


class RunDestinationHashMismatchError(RunPersistenceError):
    """A written run artifact re-read to a different hash."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
        expected_sha256: str | None = None,
        observed_sha256: str | None = None,
        consistency_kind: ConsistencyKind | None = None,
    ) -> None:
        super().__init__(message, eval_run_id=eval_run_id, artifact_reference=artifact_reference)
        self.expected_sha256 = expected_sha256
        self.observed_sha256 = observed_sha256
        self.consistency_kind = consistency_kind


class SnapshotSourceMissingError(RunPersistenceError):
    """The scoring/gate-config snapshot source does not exist."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        source_artifact_reference: str | None = None,
    ) -> None:
        super().__init__(message, eval_run_id=eval_run_id)
        self.source_artifact_reference = source_artifact_reference


class SnapshotSourceNotAFileError(RunPersistenceError):
    """The snapshot source exists but is not a regular file."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        source_artifact_reference: str | None = None,
    ) -> None:
        super().__init__(message, eval_run_id=eval_run_id)
        self.source_artifact_reference = source_artifact_reference


class SnapshotSourcePathEscapeError(RunPersistenceError):
    """The snapshot source path resolves outside its source root."""


class SnapshotReadError(RunPersistenceError):
    """Reading the snapshot source bytes failed."""


class SnapshotHashMismatchError(RunPersistenceError):
    """The snapshot source bytes do not match the loaded wrapper hash."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        source_artifact_reference: str | None = None,
        expected_sha256: str | None = None,
        observed_sha256: str | None = None,
    ) -> None:
        super().__init__(message, eval_run_id=eval_run_id)
        self.source_artifact_reference = source_artifact_reference
        self.expected_sha256 = expected_sha256
        self.observed_sha256 = observed_sha256


class RunArtifactNotFoundError(RunPersistenceError):
    """A run artifact to load does not exist."""


class RunArtifactNotAFileError(RunPersistenceError):
    """A run artifact to load exists but is not a regular file."""


class RunReadError(RunPersistenceError):
    """Reading a run artifact failed."""


class RunDecodeError(RunPersistenceError):
    """A run artifact's bytes are not valid UTF-8."""


class RunJsonError(RunPersistenceError):
    """A run artifact is not acceptable strict JSON."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
        duplicate_key: str | None = None,
        constant_name: str | None = None,
    ) -> None:
        super().__init__(message, eval_run_id=eval_run_id, artifact_reference=artifact_reference)
        self.duplicate_key = duplicate_key
        self.constant_name = constant_name


class RunTopLevelTypeError(RunPersistenceError):
    """A parsed run manifest document is not a JSON object."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
        observed_type: str | None = None,
    ) -> None:
        super().__init__(message, eval_run_id=eval_run_id, artifact_reference=artifact_reference)
        self.observed_type = observed_type


class RunManifestModelValidationError(RunPersistenceError):
    """A run manifest document failed model/contract validation."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
        field_locations: tuple[str, ...] = (),
        error_types: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message, eval_run_id=eval_run_id, artifact_reference=artifact_reference)
        self.field_locations = field_locations
        self.error_types = error_types


class RunManifestConsistencyError(RunPersistenceError):
    """A loaded run manifest is internally or referentially inconsistent."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
        consistency_kind: ConsistencyKind | None = None,
    ) -> None:
        super().__init__(message, eval_run_id=eval_run_id, artifact_reference=artifact_reference)
        self.consistency_kind = consistency_kind


class RunManifestSerializationError(RunPersistenceError):
    """The run manifest could not be serialized to deterministic JSON bytes."""


class RunManifestUnsupportedVersionError(RunManifestModelValidationError):
    """A run manifest declares a contract version the reader does not accept.

    A subclass of ``RunManifestModelValidationError`` (and thus of
    ``RunPersistenceError``) so a version-specific reader fails closed within
    the existing taxonomy before treating the document as the requested model.
    Module-private: not added to the package export surface.
    """

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
        observed_version: str | None = None,
        expected_version: str | None = None,
    ) -> None:
        super().__init__(message, eval_run_id=eval_run_id, artifact_reference=artifact_reference)
        self.observed_version = observed_version
        self.expected_version = expected_version


class _DuplicateKeyControl(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


class _NonFiniteControl(Exception):
    def __init__(self, constant_name: str) -> None:
        super().__init__(constant_name)
        self.constant_name = constant_name


# --- Private helpers (module-local; not shared) --------------------------


def _validate_eval_root(root: str | Path, label: str) -> Path:
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


def _validate_run_id(eval_run_id: Any) -> str:
    if not isinstance(eval_run_id, str):
        raise InvalidRunIdError(
            f"eval_run_id must be a string, got {type(eval_run_id).__name__}"
        )
    if not eval_run_id or eval_run_id != eval_run_id.strip():
        raise InvalidRunIdError(
            "eval_run_id must be a non-empty string without leading or trailing whitespace",
            eval_run_id=eval_run_id if eval_run_id.strip() else None,
        )
    if eval_run_id in (".", ".."):
        raise InvalidRunIdError(f"eval_run_id {eval_run_id!r} is not a valid path component")
    if "/" in eval_run_id or "\\" in eval_run_id or "\x00" in eval_run_id:
        raise InvalidRunIdError(
            "eval_run_id must be a single path component without separators or NUL"
        )
    if Path(eval_run_id).is_absolute() or len(Path(eval_run_id).parts) != 1:
        raise InvalidRunIdError(
            f"eval_run_id {eval_run_id!r} must be exactly one relative path component"
        )
    return eval_run_id


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


def _canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _exclusive_write(path: Path, data: bytes, eval_run_id: str, reference: str) -> None:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise RunDestinationCollisionError(
            f"run artifact {reference!r} already exists; runs are write-once",
            eval_run_id=eval_run_id,
            artifact_reference=reference,
        ) from exc
    except OSError as exc:
        raise RunWriteError(
            f"failed to create run artifact {reference!r}",
            eval_run_id=eval_run_id,
            artifact_reference=reference,
        ) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    except OSError as exc:
        raise RunWriteError(
            f"failed to write run artifact {reference!r}",
            eval_run_id=eval_run_id,
            artifact_reference=reference,
        ) from exc


def _read_back_hash(path: Path, eval_run_id: str, reference: str) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise RunWriteError(
            f"failed to re-read run artifact {reference!r} for verification",
            eval_run_id=eval_run_id,
            artifact_reference=reference,
        ) from exc


def _serialize_manifest(
    manifest: EvaluationRunManifest | EvaluationRunManifestV2, eval_run_id: str
) -> bytes:
    try:
        payload = manifest.model_dump(mode="json", exclude_unset=True)
        return _canonical_bytes(payload)
    except (ValueError, TypeError) as exc:
        raise RunManifestSerializationError(
            "failed to serialize the run manifest to deterministic JSON bytes",
            eval_run_id=eval_run_id,
        ) from exc


def initialize_evaluation_run(
    *,
    eval_root: str | Path,
    eval_run_id: str,
    prediction_run_id: str,
    prediction_run_manifest_hash: str,
    case_set: CaseSetManifest,
    registry: LoadedTargetRegistry,
    validator_bundle_version: str,
    validator_bundle_hash: str,
    scoring_config: LoadedScoringGateConfig,
    code_commit: str,
    config_snapshot_source_root: str | Path,
) -> InitializedEvaluationRun:
    """Create an immutable evaluation-run directory and persist its manifest.

    All source and model failures are raised before the final run directory is
    created, so a failed initialization never leaves a run directory unless a
    write or hash failure occurred after creation (in which case the partial
    directory is preserved for audit, never cleaned up or repaired). The run
    manifest is write-once and carries no execution status or gate verdict.
    """
    if not isinstance(case_set, CaseSetManifest):
        raise TypeError(f"case_set must be a CaseSetManifest, got {type(case_set).__name__}")
    if not isinstance(registry, LoadedTargetRegistry):
        raise TypeError(
            f"registry must be a LoadedTargetRegistry, got {type(registry).__name__}"
        )
    if not isinstance(scoring_config, LoadedScoringGateConfig):
        raise TypeError(
            f"scoring_config must be a LoadedScoringGateConfig, got "
            f"{type(scoring_config).__name__}"
        )

    resolved_eval_root = _validate_eval_root(eval_root, "eval_root")
    resolved_source_root = _validate_eval_root(
        config_snapshot_source_root, "config_snapshot_source_root"
    )
    run_id = _validate_run_id(eval_run_id)

    # Construct + validate the manifest in memory (before any directory exists).
    case_set_hash = case_set_snapshot_hash(case_set)
    contract_hash = model_contract_hash(
        EvaluationRunManifest, _RUN_MANIFEST_CONTRACT_ID, _RUN_MANIFEST_CONTRACT_VERSION
    )
    try:
        manifest = EvaluationRunManifest.model_validate(
            {
                "contract": {
                    "contract_id": _RUN_MANIFEST_CONTRACT_ID,
                    "contract_version": _RUN_MANIFEST_CONTRACT_VERSION,
                    "contract_hash": contract_hash,
                },
                "eval_run_id": run_id,
                "prediction_run_id": prediction_run_id,
                "prediction_run_manifest_hash": prediction_run_manifest_hash,
                "case_set_version": case_set.case_set_version,
                "case_set_hash": case_set_hash,
                "registry_snapshot_hash": registry.sha256,
                "validator_bundle_version": validator_bundle_version,
                "validator_bundle_hash": validator_bundle_hash,
                "scoring_gate_config_version": scoring_config.version,
                "scoring_gate_config_hash": scoring_config.sha256,
                "code_commit": code_commit,
                "pydantic_runtime_version": runtime_contract_provenance()["pydantic_version"],
            }
        )
    except PydanticValidationError as exc:
        pairs = sorted(
            ("/".join(str(p) for p in e["loc"]), e["type"]) for e in exc.errors()
        )
        raise RunManifestModelValidationError(
            "the run manifest failed model validation for the supplied bindings",
            eval_run_id=run_id,
            field_locations=tuple(loc for loc, _ in pairs),
            error_types=tuple(t for _, t in pairs),
        ) from exc
    manifest_bytes = _serialize_manifest(manifest, run_id)
    return _persist_initialized_run(
        resolved_eval_root=resolved_eval_root,
        resolved_source_root=resolved_source_root,
        run_id=run_id,
        scoring_config=scoring_config,
        manifest=manifest,
        manifest_bytes=manifest_bytes,
    )


def _persist_initialized_run(
    *,
    resolved_eval_root: Path,
    resolved_source_root: Path,
    run_id: str,
    scoring_config: LoadedScoringGateConfig,
    manifest: EvaluationRunManifest | EvaluationRunManifestV2,
    manifest_bytes: bytes,
) -> InitializedEvaluationRun:
    """Verify the config-snapshot source, then write the run write-once.

    Shared, version-agnostic persistence for both ``initialize_evaluation_run``
    (v0.1) and ``initialize_evaluation_run_v2`` (v0.2). The caller has already
    validated the manifest and serialized its canonical bytes; this function
    performs no per-version logic and preserves the exact v0.1 sequencing,
    error classification, and partial-write semantics.
    """
    # Resolve, read and verify the config snapshot source (before creation).
    # Resolved-path containment runs first so an escaping symlink is rejected as
    # an escape rather than downgraded to a non-file. A final-component symlink
    # that stays inside the source root is then a non-file regardless of whether
    # its target exists (a dangling contained symlink is not classified as a
    # missing artifact); only an ordinary absent non-symlink is "missing".
    raw_candidate = resolved_source_root / scoring_config.artifact_reference
    source_path = raw_candidate.resolve()
    if not source_path.is_relative_to(resolved_source_root):
        raise SnapshotSourcePathEscapeError(
            "scoring-config snapshot source resolves outside its source root",
            eval_run_id=run_id,
        )
    source_reference = source_path.relative_to(resolved_source_root).as_posix()
    if raw_candidate.is_symlink() or source_path.is_symlink():
        raise SnapshotSourceNotAFileError(
            f"scoring-config snapshot source {source_reference!r} is not a regular file",
            eval_run_id=run_id,
            source_artifact_reference=source_reference,
        )
    if not source_path.exists():
        raise SnapshotSourceMissingError(
            f"scoring-config snapshot source {source_reference!r} does not exist",
            eval_run_id=run_id,
            source_artifact_reference=source_reference,
        )
    if not source_path.is_file():
        raise SnapshotSourceNotAFileError(
            f"scoring-config snapshot source {source_reference!r} is not a regular file",
            eval_run_id=run_id,
            source_artifact_reference=source_reference,
        )
    try:
        source_bytes = source_path.read_bytes()
    except OSError as exc:
        raise SnapshotReadError(
            f"failed to read scoring-config snapshot source {source_reference!r}",
            eval_run_id=run_id,
            artifact_reference=source_reference,
        ) from exc
    source_hash = sha256_bytes(source_bytes)
    if source_hash != scoring_config.sha256:
        raise SnapshotHashMismatchError(
            f"scoring-config snapshot source {source_reference!r} changed since it was loaded",
            eval_run_id=run_id,
            source_artifact_reference=source_reference,
            expected_sha256=scoring_config.sha256,
            observed_sha256=source_hash,
        )

    # Only now touch the filesystem output tree.
    run_dir = resolved_eval_root / run_id
    run_reference = run_id
    if run_dir.exists() or run_dir.is_symlink():
        raise RunDirectoryExistsError(
            f"run directory {run_reference!r} already exists; runs are immutable, "
            "choose a new eval_run_id",
            eval_run_id=run_id,
            artifact_reference=run_reference,
        )
    try:
        run_dir.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise RunDirectoryExistsError(
            f"run directory {run_reference!r} already exists; runs are immutable, "
            "choose a new eval_run_id",
            eval_run_id=run_id,
            artifact_reference=run_reference,
        ) from exc
    except OSError as exc:
        raise RunWriteError(
            f"failed to create run directory {run_reference!r}",
            eval_run_id=run_id,
            artifact_reference=run_reference,
        ) from exc

    snapshots_dir = run_dir / _SNAPSHOTS_DIR
    try:
        snapshots_dir.mkdir(exist_ok=False)
    except OSError as exc:
        raise RunWriteError(
            f"failed to create run snapshots directory under {run_reference!r}",
            eval_run_id=run_id,
            artifact_reference=f"{run_reference}/{_SNAPSHOTS_DIR}",
        ) from exc

    config_reference = f"{run_id}/{_SNAPSHOTS_DIR}/{_CONFIG_SNAPSHOT_FILENAME}"
    config_dest = snapshots_dir / _CONFIG_SNAPSHOT_FILENAME
    _exclusive_write(config_dest, source_bytes, run_id, config_reference)
    config_dest_hash = _read_back_hash(config_dest, run_id, config_reference)
    if config_dest_hash != source_hash:
        raise RunDestinationHashMismatchError(
            f"written config snapshot {config_reference!r} re-read to a different hash",
            eval_run_id=run_id,
            artifact_reference=config_reference,
            expected_sha256=source_hash,
            observed_sha256=config_dest_hash,
            consistency_kind="config_destination_hash_mismatch",
        )

    manifest_reference = f"{run_id}/{_MANIFEST_FILENAME}"
    manifest_dest = run_dir / _MANIFEST_FILENAME
    manifest_sha256 = sha256_bytes(manifest_bytes)
    _exclusive_write(manifest_dest, manifest_bytes, run_id, manifest_reference)
    manifest_dest_hash = _read_back_hash(manifest_dest, run_id, manifest_reference)
    if manifest_dest_hash != manifest_sha256:
        raise RunDestinationHashMismatchError(
            f"written run manifest {manifest_reference!r} re-read to a different hash",
            eval_run_id=run_id,
            artifact_reference=manifest_reference,
            expected_sha256=manifest_sha256,
            observed_sha256=manifest_dest_hash,
            consistency_kind="manifest_destination_hash_mismatch",
        )

    return InitializedEvaluationRun(
        eval_run_id=run_id,
        run_directory_reference=run_reference,
        manifest_reference=manifest_reference,
        config_snapshot_reference=config_reference,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        config_snapshot_sha256=config_dest_hash,
    )


def initialize_evaluation_run_v2(
    *,
    eval_root: str | Path,
    eval_run_id: str,
    prediction_run_id: str,
    prediction_run_manifest_hash: str,
    case_set: CaseSetManifest,
    registry: LoadedTargetRegistry,
    validator_bundle_version: str,
    validator_bundle_hash: str,
    scoring_config: LoadedScoringGateConfig,
    code_commit: str,
    config_snapshot_source_root: str | Path,
    evaluation_created_at: str,
    evaluation_stage: str,
    stage_profile_registry: LoadedStageProfileRegistry,
    semantic_adapter_registry_version: str,
    semantic_adapter_registry_hash: str,
    selected_semantic_adapter_entry_hash: str,
    source_passage_snapshot_version: str,
    source_passage_snapshot_hash: str,
    gold_assertion_set_version: str,
    gold_assertion_set_hash: str,
    axis_taxonomy_version: str,
    axis_taxonomy_hash: str,
    validator_rule_parameters_version: str,
    validator_rule_parameters_hash: str,
    stage_metric_evidence_set_version: str | None = None,
    stage_metric_evidence_set_hash: str | None = None,
) -> InitializedEvaluationRun:
    """Create an immutable evaluation-run directory and persist a v0.2 manifest.

    New Phase-1 production initialization (Slice 13's runner) must use this
    function, not the v0.1 ``initialize_evaluation_run`` (retained only for
    historical compatibility and existing plumbing tests). The stage-profile
    registry version, semantic-content hash, and selected-entry hash are derived
    through the governed Slice 12A public APIs; ``evaluation_stage`` is a
    transient resolver input and is never persisted as a manifest field. The
    manifest is fully validated before any directory is created, and the
    resolver, hashing, and applicable-stage-evidence rule are all applied before
    filesystem mutation. Persistence guarantees are identical to v0.1.
    """
    if not isinstance(case_set, CaseSetManifest):
        raise TypeError(f"case_set must be a CaseSetManifest, got {type(case_set).__name__}")
    if not isinstance(registry, LoadedTargetRegistry):
        raise TypeError(
            f"registry must be a LoadedTargetRegistry, got {type(registry).__name__}"
        )
    if not isinstance(scoring_config, LoadedScoringGateConfig):
        raise TypeError(
            f"scoring_config must be a LoadedScoringGateConfig, got "
            f"{type(scoring_config).__name__}"
        )
    if not isinstance(stage_profile_registry, LoadedStageProfileRegistry):
        raise TypeError(
            f"stage_profile_registry must be a LoadedStageProfileRegistry, got "
            f"{type(stage_profile_registry).__name__}"
        )

    resolved_eval_root = _validate_eval_root(eval_root, "eval_root")
    resolved_source_root = _validate_eval_root(
        config_snapshot_source_root, "config_snapshot_source_root"
    )
    run_id = _validate_run_id(eval_run_id)

    # Resolve the selected stage-profile entry through the governed Slice 12A
    # boundary before any filesystem mutation. Unknown, unsupported, duplicate,
    # or structurally inconsistent profiles fail closed as StageProfileError.
    selected_entry = resolve_metric_applicability(
        stage_profile_registry.registry, evaluation_stage
    )
    stage_profile_version = stage_profile_registry.registry.registry_version
    stage_profile_content_hash = stage_profile_registry_hash(stage_profile_registry.registry)
    selected_entry_hash = selected_entry.entry_hash
    requires_stage_evidence = bool(selected_entry.required_stage_evidence_kinds)

    # Applicable-stage-evidence presence is derived only from the resolved entry
    # (no caller boolean): Universe stages require it, extraction stages omit it.
    evidence_supplied = (
        stage_metric_evidence_set_version is not None
        or stage_metric_evidence_set_hash is not None
    )
    if requires_stage_evidence and not (
        stage_metric_evidence_set_version is not None
        and stage_metric_evidence_set_hash is not None
    ):
        raise RunManifestModelValidationError(
            "the resolved stage requires both stage_metric_evidence_set_version and "
            "stage_metric_evidence_set_hash",
            eval_run_id=run_id,
        )
    if not requires_stage_evidence and evidence_supplied:
        raise RunManifestModelValidationError(
            "an extraction stage must omit stage_metric_evidence_set_version and "
            "stage_metric_evidence_set_hash",
            eval_run_id=run_id,
        )

    case_set_hash = case_set_snapshot_hash(case_set)
    contract_hash = model_contract_hash(
        EvaluationRunManifestV2, _RUN_MANIFEST_CONTRACT_ID, _RUN_MANIFEST_CONTRACT_VERSION_V2
    )
    payload: dict[str, Any] = {
        "contract": {
            "contract_id": _RUN_MANIFEST_CONTRACT_ID,
            "contract_version": _RUN_MANIFEST_CONTRACT_VERSION_V2,
            "contract_hash": contract_hash,
        },
        "eval_run_id": run_id,
        "prediction_run_id": prediction_run_id,
        "prediction_run_manifest_hash": prediction_run_manifest_hash,
        "case_set_version": case_set.case_set_version,
        "case_set_hash": case_set_hash,
        "registry_snapshot_hash": registry.sha256,
        "validator_bundle_version": validator_bundle_version,
        "validator_bundle_hash": validator_bundle_hash,
        "scoring_gate_config_version": scoring_config.version,
        "scoring_gate_config_hash": scoring_config.sha256,
        "code_commit": code_commit,
        "pydantic_runtime_version": runtime_contract_provenance()["pydantic_version"],
        "evaluation_created_at": evaluation_created_at,
        "stage_profile_registry_version": stage_profile_version,
        "stage_profile_registry_hash": stage_profile_content_hash,
        "selected_stage_profile_entry_hash": selected_entry_hash,
        "semantic_adapter_registry_version": semantic_adapter_registry_version,
        "semantic_adapter_registry_hash": semantic_adapter_registry_hash,
        "selected_semantic_adapter_entry_hash": selected_semantic_adapter_entry_hash,
        "source_passage_snapshot_version": source_passage_snapshot_version,
        "source_passage_snapshot_hash": source_passage_snapshot_hash,
        "gold_assertion_set_version": gold_assertion_set_version,
        "gold_assertion_set_hash": gold_assertion_set_hash,
        "axis_taxonomy_version": axis_taxonomy_version,
        "axis_taxonomy_hash": axis_taxonomy_hash,
        "validator_rule_parameters_version": validator_rule_parameters_version,
        "validator_rule_parameters_hash": validator_rule_parameters_hash,
    }
    if requires_stage_evidence:
        payload["stage_metric_evidence_set_version"] = stage_metric_evidence_set_version
        payload["stage_metric_evidence_set_hash"] = stage_metric_evidence_set_hash
    try:
        manifest = EvaluationRunManifestV2.model_validate(payload)
    except PydanticValidationError as exc:
        pairs = sorted(
            ("/".join(str(p) for p in e["loc"]), e["type"]) for e in exc.errors()
        )
        raise RunManifestModelValidationError(
            "the run manifest failed model validation for the supplied bindings",
            eval_run_id=run_id,
            field_locations=tuple(loc for loc, _ in pairs),
            error_types=tuple(t for _, t in pairs),
        ) from exc
    # v0.2 persists canonical JSON followed by exactly one terminal LF byte
    # (v0.1 persists canonical bytes with no terminal newline). The bound
    # SHA-256 covers the complete raw bytes including that LF.
    manifest_bytes = _serialize_manifest(manifest, run_id) + b"\n"
    return _persist_initialized_run(
        resolved_eval_root=resolved_eval_root,
        resolved_source_root=resolved_source_root,
        run_id=run_id,
        scoring_config=scoring_config,
        manifest=manifest,
        manifest_bytes=manifest_bytes,
    )


def _read_run_manifest_payload(
    eval_run_id: str, eval_root: str | Path
) -> tuple[dict[str, Any], str, str, str]:
    """Shared strict read + parse for both version-specific loaders.

    Returns ``(payload, observed_sha256, manifest_reference, run_id)`` for a
    validated top-level JSON object. Preserves the exact path/run-id/symlink
    protections, duplicate-key and non-finite rejection, and top-level-type
    rejection; performs no model validation or version discrimination.
    """
    resolved_eval_root = _validate_eval_root(eval_root, "eval_root")
    run_id = _validate_run_id(eval_run_id)
    run_dir = resolved_eval_root / run_id
    manifest_reference = f"{run_id}/{_MANIFEST_FILENAME}"
    manifest_path = run_dir / _MANIFEST_FILENAME
    if run_dir.is_symlink() or manifest_path.is_symlink():
        raise RunArtifactNotAFileError(
            f"run manifest {manifest_reference!r} or its directory is a symlink",
            eval_run_id=run_id,
            artifact_reference=manifest_reference,
        )
    if not manifest_path.exists():
        raise RunArtifactNotFoundError(
            f"run manifest {manifest_reference!r} does not exist",
            eval_run_id=run_id,
            artifact_reference=manifest_reference,
        )
    if not manifest_path.is_file():
        raise RunArtifactNotAFileError(
            f"run manifest {manifest_reference!r} is not a regular file",
            eval_run_id=run_id,
            artifact_reference=manifest_reference,
        )
    try:
        raw = manifest_path.read_bytes()
    except OSError as exc:
        raise RunReadError(
            f"failed to read run manifest {manifest_reference!r}",
            eval_run_id=run_id,
            artifact_reference=manifest_reference,
        ) from exc
    observed = sha256_bytes(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RunDecodeError(
            f"run manifest {manifest_reference!r} is not valid UTF-8",
            eval_run_id=run_id,
            artifact_reference=manifest_reference,
        ) from exc
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except json.JSONDecodeError as exc:
        raise RunJsonError(
            f"run manifest {manifest_reference!r} is not valid JSON: {exc.msg} "
            f"(line {exc.lineno} column {exc.colno})",
            eval_run_id=run_id,
            artifact_reference=manifest_reference,
        ) from exc
    except _DuplicateKeyControl as exc:
        raise RunJsonError(
            f"run manifest {manifest_reference!r} contains a duplicate JSON object key "
            f"{exc.key!r}",
            eval_run_id=run_id,
            artifact_reference=manifest_reference,
            duplicate_key=exc.key,
        ) from exc
    except _NonFiniteControl as exc:
        raise RunJsonError(
            f"run manifest {manifest_reference!r} contains the non-JSON constant "
            f"{exc.constant_name}",
            eval_run_id=run_id,
            artifact_reference=manifest_reference,
            constant_name=exc.constant_name,
        ) from exc
    non_finite = _assert_finite(payload)
    if non_finite is not None:
        raise RunJsonError(
            f"run manifest {manifest_reference!r} contains a non-finite JSON number "
            f"({non_finite})",
            eval_run_id=run_id,
            artifact_reference=manifest_reference,
            constant_name=non_finite,
        )
    if not isinstance(payload, dict):
        raise RunTopLevelTypeError(
            f"run manifest {manifest_reference!r} must be a top-level JSON object, "
            f"got {type(payload).__name__}",
            eval_run_id=run_id,
            artifact_reference=manifest_reference,
            observed_type=type(payload).__name__,
        )
    return payload, observed, manifest_reference, run_id


def _payload_contract_version(payload: dict[str, Any]) -> str | None:
    """The declared ``contract.contract_version`` string, or None if absent/malformed."""
    contract = payload.get("contract")
    if isinstance(contract, dict):
        version = contract.get("contract_version")
        if isinstance(version, str):
            return version
    return None


def load_evaluation_run_manifest(
    eval_run_id: str, *, eval_root: str | Path
) -> LoadedEvaluationRunManifest:
    """Load one historical **v0.1** run manifest from its fixed location.

    This is the explicit v0.1 historical reader: it accepts only
    ``evaluation_run_manifest@0.1.0`` and fails closed on any other declared
    contract version (a v0.2 document is rejected before it is ever treated as
    v0.1). Symlink run directories and manifest files are rejected. The
    generated contract stamp is verified and additionally bound to the governed
    historical hash constant, and the manifest's own ``eval_run_id`` must equal
    the requested one. No execution status is inferred and nothing is rewritten.
    """
    payload, observed, manifest_reference, run_id = _read_run_manifest_payload(
        eval_run_id, eval_root
    )
    declared = _payload_contract_version(payload)
    if declared is not None and declared != _RUN_MANIFEST_CONTRACT_VERSION:
        raise RunManifestUnsupportedVersionError(
            f"run manifest {manifest_reference!r} is not an "
            f"{_RUN_MANIFEST_CONTRACT_ID}@{_RUN_MANIFEST_CONTRACT_VERSION} document",
            eval_run_id=run_id,
            artifact_reference=manifest_reference,
            observed_version=declared,
            expected_version=_RUN_MANIFEST_CONTRACT_VERSION,
        )
    try:
        manifest = EvaluationRunManifest.model_validate(payload)
    except PydanticValidationError as exc:
        pairs = sorted(
            ("/".join(str(p) for p in e["loc"]), e["type"]) for e in exc.errors()
        )
        raise RunManifestModelValidationError(
            f"run manifest {manifest_reference!r} failed model/contract validation",
            eval_run_id=run_id,
            artifact_reference=manifest_reference,
            field_locations=tuple(loc for loc, _ in pairs),
            error_types=tuple(t for _, t in pairs),
        ) from exc
    if manifest.contract.contract_hash != _EVALUATION_RUN_MANIFEST_V1_CONTRACT_HASH:
        raise RunManifestModelValidationError(
            f"run manifest {manifest_reference!r} contract hash does not match the "
            "governed historical v0.1 constant",
            eval_run_id=run_id,
            artifact_reference=manifest_reference,
        )
    if manifest.eval_run_id != run_id:
        raise RunManifestConsistencyError(
            f"run manifest {manifest_reference!r} records a different eval_run_id "
            "than the requested run",
            eval_run_id=run_id,
            artifact_reference=manifest_reference,
            consistency_kind="manifest_run_id_mismatch",
        )
    return LoadedEvaluationRunManifest(
        manifest=manifest, sha256=observed, artifact_reference=manifest_reference
    )


def load_evaluation_run_manifest_v2(
    eval_run_id: str, *, eval_root: str | Path
) -> LoadedEvaluationRunManifest:
    """Load one current **v0.2** run manifest from its fixed location.

    Explicit v0.2 reader: it accepts only ``evaluation_run_manifest@0.2.0`` and
    fails closed on any other declared version (a v0.1 document is rejected
    before it is ever treated as v0.2). It reuses the identical strict read,
    path, symlink, duplicate-key, non-finite, and top-level-type protections,
    binds the exact raw persisted-byte SHA-256, verifies the ``eval_run_id``
    match, and rewrites nothing. The returned wrapper preserves the concrete
    ``EvaluationRunManifestV2`` inner model. Neither loader falls back to the
    other version.
    """
    payload, observed, manifest_reference, run_id = _read_run_manifest_payload(
        eval_run_id, eval_root
    )
    declared = _payload_contract_version(payload)
    if declared is not None and declared != _RUN_MANIFEST_CONTRACT_VERSION_V2:
        raise RunManifestUnsupportedVersionError(
            f"run manifest {manifest_reference!r} is not an "
            f"{_RUN_MANIFEST_CONTRACT_ID}@{_RUN_MANIFEST_CONTRACT_VERSION_V2} document",
            eval_run_id=run_id,
            artifact_reference=manifest_reference,
            observed_version=declared,
            expected_version=_RUN_MANIFEST_CONTRACT_VERSION_V2,
        )
    try:
        manifest = EvaluationRunManifestV2.model_validate(payload)
    except PydanticValidationError as exc:
        pairs = sorted(
            ("/".join(str(p) for p in e["loc"]), e["type"]) for e in exc.errors()
        )
        raise RunManifestModelValidationError(
            f"run manifest {manifest_reference!r} failed model/contract validation",
            eval_run_id=run_id,
            artifact_reference=manifest_reference,
            field_locations=tuple(loc for loc, _ in pairs),
            error_types=tuple(t for _, t in pairs),
        ) from exc
    if manifest.eval_run_id != run_id:
        raise RunManifestConsistencyError(
            f"run manifest {manifest_reference!r} records a different eval_run_id "
            "than the requested run",
            eval_run_id=run_id,
            artifact_reference=manifest_reference,
            consistency_kind="manifest_run_id_mismatch",
        )
    return LoadedEvaluationRunManifest(
        manifest=manifest, sha256=observed, artifact_reference=manifest_reference
    )


def _load_run_manifest_any_supported_version(
    eval_run_id: str, *, eval_root: str | Path
) -> LoadedEvaluationRunManifest:
    """Internal artifact-I/O helper: load a run manifest of *either* supported
    version by inspecting the persisted contract version and dispatching to the
    matching explicit reader.

    This is not a public reader and is deliberately not exported. The two public
    readers (:func:`load_evaluation_run_manifest`,
    :func:`load_evaluation_run_manifest_v2`) remain strictly single-version and
    never fall back. This helper exists solely so that internal derived-artifact
    persistence and loading can bind to a run directory regardless of whether it
    holds a historical v0.1 or a current v0.2 run manifest. An unsupported or
    absent declared contract version continues to fail through the established
    :class:`RunManifestUnsupportedVersionError` vocabulary.
    """
    payload, _observed, manifest_reference, run_id = _read_run_manifest_payload(
        eval_run_id, eval_root
    )
    declared = _payload_contract_version(payload)
    if declared == _RUN_MANIFEST_CONTRACT_VERSION:
        return load_evaluation_run_manifest(eval_run_id, eval_root=eval_root)
    if declared == _RUN_MANIFEST_CONTRACT_VERSION_V2:
        return load_evaluation_run_manifest_v2(eval_run_id, eval_root=eval_root)
    raise RunManifestUnsupportedVersionError(
        f"run manifest {manifest_reference!r} declares an unsupported "
        f"{_RUN_MANIFEST_CONTRACT_ID} contract version",
        eval_run_id=run_id,
        artifact_reference=manifest_reference,
        observed_version=declared,
        expected_version=(
            f"{_RUN_MANIFEST_CONTRACT_VERSION} | {_RUN_MANIFEST_CONTRACT_VERSION_V2}"
        ),
    )
