"""Governed, hash-bound evaluation-stage-profile registry (Slice 12A).

The stage-profile registry maps each supported evaluation stage to the metric
families that apply to it and the stage-evidence kinds it requires, so that
metric-family applicability is derived deterministically from a hash-bound
governed contract rather than from ad-hoc booleans (ADR-024). ADR-025 binds the
selected stage-profile entry identity independently of the whole-registry hash;
each entry therefore exposes a deterministic ``entry_hash`` over its own
canonical bytes.

Read-side plus pure validation and explicit persistence only. Importing this
module performs no filesystem access, hashing, environment inspection, clock
read, UUID generation, network, provider, or model call: every hash is computed
at validation or call time. The generated-model contract hash, the canonical
registry-content hash, the per-entry content hash, and the raw source/snapshot
byte SHA-256 are four distinct identities and are named separately throughout.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import (
    ValidationError as PydanticValidationError,
    model_validator,
)

from .contracts import canonical_contract_bytes
from .models import ContractStampedModel, EvaluationStrictModel, _require_non_blank
from ..universe.io_utils import sha256_bytes

__all__ = [
    "StageProfileRegistry",
    "StageProfileEntry",
    "MetricFamily",
    "LoadedStageProfileRegistry",
    "load_stage_profile_registry",
    "persist_stage_profile_registry_snapshot",
    "stage_profile_registry_hash",
    "resolve_metric_applicability",
    "StageProfileError",
    "StageProfileBindingError",
]

_CONTRACT_ID = "evaluation_stage_profile_registry"
_CONTRACT_VERSION = "0.1.0"
_SNAPSHOTS_DIR = "snapshots"
_SNAPSHOT_FILENAME = "stage_profile_registry.json"
_UNSUPPORTED_REASON_CODE = "unsupported_evaluation_stage"
_DUPLICATE_BINDING_REASON_CODE = "duplicate_profile_binding"
_INCONSISTENT_BINDING_REASON_CODE = "inconsistent_profile_binding"

MetricFamily = Literal[
    "axis_multi_label",
    "axis_structured_set",
    "axis_nominal_single_label",
    "axis_ordinal_single_label",
    "axis_abstention",
    "assertion_outcomes",
    "validator_rules",
    "validator_summaries",
    "tier_contract",
    "unsafe_exclusion",
    "screen_operational",
]

_StageEvidenceKind = Literal[
    "universe_screen_operational",
    "universe_classification_tier",
    "universe_unsafe_exclusion_audit",
]

_SupportStatus = Literal["working", "fixture_backed", "unsupported"]

# The canonical, sorted tuple of every governed metric family. A supported stage
# carries exactly one applicability reason code per inapplicable family, in this
# canonical order (Slice 12A correction 2). Derived from the closed ``MetricFamily``
# Literal so the two can never drift; the fail-closed guard rejects any drift.
_CANONICAL_METRIC_FAMILIES: tuple[str, ...] = tuple(sorted(get_args(MetricFamily)))
if len(_CANONICAL_METRIC_FAMILIES) != 11 or len(set(_CANONICAL_METRIC_FAMILIES)) != 11:
    raise RuntimeError(
        "MetricFamily must define exactly eleven distinct governed metric families"
    )


# --- Public errors --------------------------------------------------------


class StageProfileError(Exception):
    """Sanitized failure loading, persisting, or structurally binding a registry.

    Carries a stable machine-readable ``reason_code`` and an optional governed
    ``artifact_reference``. No raw document content, absolute path, or raw
    Pydantic/OS text is placed in the message.
    """

    def __init__(
        self, message: str, *, reason_code: str, artifact_reference: str | None = None
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.artifact_reference = artifact_reference


class StageProfileBindingError(StageProfileError):
    """A stage cannot be resolved to a governed, supported profile entry."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str,
        evaluation_stage: str | None = None,
        artifact_reference: str | None = None,
    ) -> None:
        super().__init__(message, reason_code=reason_code, artifact_reference=artifact_reference)
        self.evaluation_stage = evaluation_stage


# --- Private strict-parse control exceptions ------------------------------


class _DuplicateKeyControl(Exception):
    """Internal signal for a duplicate JSON object key.

    The offending key is deliberately not stored on the exception or in its
    message, so untrusted document content cannot leak through a chained
    traceback; the stable ``duplicate_key`` reason code carries the diagnosis.
    """

    def __init__(self) -> None:
        super().__init__("duplicate JSON object key")


class _NonFiniteControl(Exception):
    """Internal signal for a non-JSON numeric constant.

    The constant name is deliberately not stored, mirroring
    ``_DuplicateKeyControl``; the stable ``non_finite`` reason code diagnoses it.
    """

    def __init__(self) -> None:
        super().__init__("non-JSON numeric constant")


# --- Models ---------------------------------------------------------------


class StageProfileEntry(EvaluationStrictModel):
    """One governed evaluation-stage profile entry (strict, frozen, extra-forbid)."""

    evaluation_stage: str
    support_status: _SupportStatus
    applicable_metric_families: tuple[MetricFamily, ...]
    required_stage_evidence_kinds: tuple[_StageEvidenceKind, ...]
    applicability_reason_codes: tuple[str, ...]

    @model_validator(mode="after")
    def _entry_invariants(self) -> "StageProfileEntry":
        _require_non_blank(self.evaluation_stage, "evaluation_stage")
        families = list(self.applicable_metric_families)
        if families != sorted(families):
            raise ValueError("applicable_metric_families must be sorted")
        if len(families) != len(set(families)):
            raise ValueError("applicable_metric_families must be unique")
        kinds = list(self.required_stage_evidence_kinds)
        if kinds != sorted(kinds):
            raise ValueError("required_stage_evidence_kinds must be sorted")
        if len(kinds) != len(set(kinds)):
            raise ValueError("required_stage_evidence_kinds must be unique")
        reasons = list(self.applicability_reason_codes)
        for reason in reasons:
            _require_non_blank(reason, "applicability_reason_code")
        if reasons != sorted(reasons):
            raise ValueError("applicability_reason_codes must be sorted")
        if len(reasons) != len(set(reasons)):
            raise ValueError("applicability_reason_codes must be unique")
        if self.support_status == "unsupported":
            if families:
                raise ValueError("an unsupported stage has no applicable metric families")
            if kinds:
                raise ValueError("an unsupported stage has no required stage-evidence kinds")
            if tuple(reasons) != (_UNSUPPORTED_REASON_CODE,):
                raise ValueError(
                    f"an unsupported stage must carry exactly the reason code "
                    f"{_UNSUPPORTED_REASON_CODE!r}"
                )
        else:
            if not families:
                raise ValueError(
                    "a supported stage must declare at least one applicable metric family"
                )
            applicable = set(families)
            inapplicable = tuple(
                family for family in _CANONICAL_METRIC_FAMILIES if family not in applicable
            )
            if len(reasons) != len(inapplicable):
                raise ValueError(
                    "a supported stage must carry exactly one applicability reason "
                    "code per inapplicable metric family"
                )
            for reason, family in zip(reasons, inapplicable):
                if not reason.startswith(f"{family}_"):
                    raise ValueError(
                        "each applicability reason code must identify its "
                        "corresponding inapplicable metric family, in canonical order"
                    )
            if self.support_status != "working" and kinds:
                raise ValueError(
                    "only a 'working' stage may require stage-evidence kinds"
                )
        return self

    @property
    def entry_hash(self) -> str:
        """Deterministic SHA-256 over this entry's canonical JSON bytes.

        The entry is revalidated fail-closed before hashing (Slice 12A
        correction 1): an instance produced by ``model_copy(update=...)`` or
        ``model_construct(...)`` that bypassed the entry invariants raises
        ``StageProfileBindingError`` rather than yielding a hash over
        structurally inconsistent content. Independent of the whole-registry
        hash; identical entry content yields the same value regardless of
        position or unrelated entries.
        """
        validated = _revalidate_entry(self)
        return sha256_bytes(
            canonical_contract_bytes(validated.model_dump(mode="json", exclude_unset=True))
        )


class StageProfileRegistry(ContractStampedModel):
    """Immutable, contract-stamped governed stage-profile registry."""

    _contract_id = _CONTRACT_ID
    _contract_version = _CONTRACT_VERSION

    registry_version: str
    entries: tuple[StageProfileEntry, ...]

    @model_validator(mode="after")
    def _registry_invariants(self) -> "StageProfileRegistry":
        _require_non_blank(self.registry_version, "registry_version")
        if self.registry_version != self._contract_version:
            raise ValueError(
                f"registry_version must equal the governed registry contract version "
                f"{self._contract_version!r}"
            )
        stages = [entry.evaluation_stage for entry in self.entries]
        if stages != sorted(stages):
            raise ValueError("entries must be sorted canonically by evaluation_stage")
        if len(stages) != len(set(stages)):
            raise ValueError("entries must not contain a duplicate evaluation_stage")
        return self

    @property
    def by_stage(self) -> dict[str, StageProfileEntry]:
        """A fresh ordinary mapping of evaluation_stage to its entry."""
        return {entry.evaluation_stage: entry for entry in self.entries}


class LoadedStageProfileRegistry(EvaluationStrictModel):
    """A validated registry plus its raw-byte binding material."""

    registry: StageProfileRegistry
    version: str
    sha256: str
    artifact_reference: str


# --- Fail-closed revalidation of supplied instances -----------------------
#
# ``model_copy(update=...)`` and ``model_construct(...)`` bypass Pydantic
# validators, so an object can satisfy ``isinstance`` while carrying content
# that never passed the governed invariants. Every public API that hashes,
# resolves, or persists a supplied instance revalidates it first by dumping it
# and re-running full model validation, then operates on the revalidated result
# — never on the potentially tampered caller object. Failures surface as
# sanitized ``StageProfileBindingError`` with a stable reason code; no raw
# Pydantic error text or invalid payload content is exposed.


def _revalidate_entry(entry: StageProfileEntry) -> StageProfileEntry:
    """Return a fully revalidated copy of ``entry`` or fail closed."""
    if not isinstance(entry, StageProfileEntry):
        raise TypeError(
            f"expected a StageProfileEntry, got {type(entry).__name__}"
        )
    try:
        payload = entry.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 - any serialization defect fails closed
        raise StageProfileBindingError(
            "stage-profile entry could not be serialized for revalidation",
            reason_code=_INCONSISTENT_BINDING_REASON_CODE,
        ) from exc
    try:
        return StageProfileEntry.model_validate(payload)
    except PydanticValidationError as exc:
        raise StageProfileBindingError(
            "stage-profile entry failed fail-closed revalidation",
            reason_code=_INCONSISTENT_BINDING_REASON_CODE,
        ) from exc


def _revalidate_registry(registry: StageProfileRegistry) -> StageProfileRegistry:
    """Return a fully revalidated copy of ``registry`` and nested entries, or fail closed."""
    if not isinstance(registry, StageProfileRegistry):
        raise TypeError(
            f"expected a StageProfileRegistry, got {type(registry).__name__}"
        )
    try:
        payload = registry.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 - any serialization defect fails closed
        raise StageProfileBindingError(
            "stage-profile registry could not be serialized for revalidation",
            reason_code=_INCONSISTENT_BINDING_REASON_CODE,
        ) from exc
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if isinstance(entries, list):
        stages = [
            item.get("evaluation_stage")
            for item in entries
            if isinstance(item, dict)
        ]
        present = [stage for stage in stages if isinstance(stage, str)]
        if len(present) != len(set(present)):
            raise StageProfileBindingError(
                "stage-profile registry binds more than one profile to a stage",
                reason_code=_DUPLICATE_BINDING_REASON_CODE,
            )
    try:
        return StageProfileRegistry.model_validate(payload)
    except PydanticValidationError as exc:
        raise StageProfileBindingError(
            "stage-profile registry failed fail-closed revalidation",
            reason_code=_INCONSISTENT_BINDING_REASON_CODE,
        ) from exc


# --- Content hash ---------------------------------------------------------


def stage_profile_registry_hash(registry: StageProfileRegistry) -> str:
    """Canonical semantic-content SHA-256 of a registry (no trailing newline).

    The registry and its nested entries are revalidated fail-closed before
    hashing (Slice 12A correction 1); a validator-bypassing instance raises
    ``StageProfileBindingError`` rather than yielding a hash over inconsistent
    content.
    """
    if not isinstance(registry, StageProfileRegistry):
        raise TypeError(
            f"stage_profile_registry_hash requires a StageProfileRegistry, "
            f"got {type(registry).__name__}"
        )
    validated = _revalidate_registry(registry)
    return sha256_bytes(
        canonical_contract_bytes(validated.model_dump(mode="json", exclude_unset=True))
    )


# --- Resolution -----------------------------------------------------------


def resolve_metric_applicability(
    registry: StageProfileRegistry, evaluation_stage: str
) -> StageProfileEntry:
    """Resolve exactly one governed, supported profile entry by stage (pure).

    The registry and its nested entries are revalidated fail-closed before
    resolution (Slice 12A correction 1), so a validator-bypassing registry never
    resolves to an entry. Never mutates or normalizes the caller's input; never
    treats an unknown or unsupported stage as an extraction stage.
    """
    if not isinstance(registry, StageProfileRegistry):
        raise TypeError(
            f"registry must be a StageProfileRegistry, got {type(registry).__name__}"
        )
    if not isinstance(evaluation_stage, str):
        raise TypeError(
            f"evaluation_stage must be a string, got {type(evaluation_stage).__name__}"
        )
    validated = _revalidate_registry(registry)
    matches = [e for e in validated.entries if e.evaluation_stage == evaluation_stage]
    if len(matches) > 1:
        raise StageProfileBindingError(
            "evaluation stage resolves to more than one profile entry",
            reason_code=_DUPLICATE_BINDING_REASON_CODE,
            evaluation_stage=evaluation_stage,
        )
    if not matches:
        raise StageProfileBindingError(
            "requested evaluation stage is not present in the stage-profile registry",
            reason_code="unknown_evaluation_stage",
            evaluation_stage=evaluation_stage,
        )
    entry = matches[0]
    if entry.support_status == "unsupported":
        raise StageProfileBindingError(
            "requested evaluation stage is governed but not supported for evaluation",
            reason_code=_UNSUPPORTED_REASON_CODE,
            evaluation_stage=evaluation_stage,
        )
    return entry


# --- Loader ---------------------------------------------------------------


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


def _validate_eval_root(eval_root: str | Path) -> Path:
    if not isinstance(eval_root, (str, Path)):
        raise StageProfileError(
            "eval_root must be an explicit str or Path evaluation root",
            reason_code="invalid_eval_root",
        )
    if isinstance(eval_root, str) and eval_root == "":
        raise StageProfileError(
            "eval_root must not be an empty string; supply the evaluation root explicitly",
            reason_code="invalid_eval_root",
        )
    root = Path(eval_root)
    if root.is_symlink():
        raise StageProfileError(
            "eval_root must not be a symlink", reason_code="eval_root_symlink"
        )
    if not root.exists():
        raise StageProfileError(
            "evaluation root does not exist", reason_code="invalid_eval_root"
        )
    if not root.is_dir():
        raise StageProfileError(
            "evaluation root is not a directory", reason_code="invalid_eval_root"
        )
    return root.resolve()


def _resolve_contained(artifact_path: str | Path, resolved_root: Path) -> tuple[Path, str]:
    if not isinstance(artifact_path, (str, Path)):
        raise StageProfileError(
            "registry path must be an explicit str or Path", reason_code="invalid_path"
        )
    requested = Path(artifact_path)
    candidate = requested if requested.is_absolute() else resolved_root / requested
    if candidate.is_symlink():
        raise StageProfileError(
            "stage-profile registry path is a symlink", reason_code="artifact_symlink"
        )
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise StageProfileError(
            "stage-profile registry path resolves outside the evaluation root",
            reason_code="path_escape",
        )
    reference = resolved.relative_to(resolved_root).as_posix()
    if resolved.is_symlink():
        raise StageProfileError(
            "stage-profile registry artifact is a symlink",
            reason_code="artifact_symlink",
            artifact_reference=reference,
        )
    if not resolved.exists():
        raise StageProfileError(
            "stage-profile registry does not exist under the evaluation root",
            reason_code="artifact_missing",
            artifact_reference=reference,
        )
    if not resolved.is_file():
        raise StageProfileError(
            "stage-profile registry is not a regular file",
            reason_code="artifact_not_a_file",
            artifact_reference=reference,
        )
    return resolved, reference


def _verify_expected_hash(expected_sha256: str | None, observed: str, reference: str) -> None:
    if expected_sha256 is None:
        return
    valid = (
        isinstance(expected_sha256, str)
        and len(expected_sha256) == 64
        and all(c in "0123456789abcdef" for c in expected_sha256)
    )
    if not valid or expected_sha256 != observed:
        raise StageProfileError(
            "stage-profile registry raw-byte hash does not match the expected hash",
            reason_code="snapshot_hash_mismatch",
            artifact_reference=reference,
        )


def load_stage_profile_registry(
    path: str | Path,
    *,
    eval_root: str | Path,
    expected_sha256: str | None = None,
) -> LoadedStageProfileRegistry:
    """Load, hash-bind, and structurally validate one stage-profile registry.

    ``eval_root`` is explicit and required. The returned SHA-256 is computed over
    the exact raw bytes, never parsed or canonicalized JSON. All failures are
    sanitized ``StageProfileError``/``StageProfileBindingError``; no raw document
    content is placed in exception text.
    """
    resolved_root = _validate_eval_root(eval_root)
    resolved, reference = _resolve_contained(path, resolved_root)
    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        raise StageProfileError(
            "failed to read the stage-profile registry",
            reason_code="read_error",
            artifact_reference=reference,
        ) from exc
    observed = sha256_bytes(raw)
    _verify_expected_hash(expected_sha256, observed, reference)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StageProfileError(
            "stage-profile registry is not valid UTF-8",
            reason_code="decode_error",
            artifact_reference=reference,
        ) from exc
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except json.JSONDecodeError as exc:
        raise StageProfileError(
            "stage-profile registry is not valid JSON",
            reason_code="json_error",
            artifact_reference=reference,
        ) from exc
    except _DuplicateKeyControl as exc:
        raise StageProfileError(
            "stage-profile registry contains a duplicate JSON object key",
            reason_code="duplicate_key",
            artifact_reference=reference,
        ) from exc
    except _NonFiniteControl as exc:
        raise StageProfileError(
            "stage-profile registry contains a non-JSON numeric constant",
            reason_code="non_finite",
            artifact_reference=reference,
        ) from exc
    if _has_non_finite(payload):
        raise StageProfileError(
            "stage-profile registry contains a non-finite JSON number",
            reason_code="non_finite",
            artifact_reference=reference,
        )
    if not isinstance(payload, dict):
        raise StageProfileError(
            "stage-profile registry top-level value must be a JSON object",
            reason_code="top_level_type",
            artifact_reference=reference,
        )
    try:
        registry = StageProfileRegistry.model_validate(payload)
    except PydanticValidationError as exc:
        raise StageProfileError(
            "stage-profile registry failed strict contract validation",
            reason_code="model_validation",
            artifact_reference=reference,
        ) from exc
    return LoadedStageProfileRegistry(
        registry=registry,
        version=registry.registry_version,
        sha256=observed,
        artifact_reference=reference,
    )


# --- Snapshot persistence -------------------------------------------------


def persist_stage_profile_registry_snapshot(
    registry: StageProfileRegistry,
    *,
    eval_root: str | Path,
    eval_run_id: str,
) -> LoadedStageProfileRegistry:
    """Write the canonical registry JSON (plus one terminal newline) write-once.

    Destination: ``<eval_root>/<eval_run_id>/snapshots/stage_profile_registry.json``.
    The returned ``sha256`` binds the persisted bytes (with the newline); the
    canonical semantic-content hash is ``stage_profile_registry_hash`` (no
    newline).
    """
    if not isinstance(registry, StageProfileRegistry):
        raise TypeError(
            f"registry must be a StageProfileRegistry, got {type(registry).__name__}"
        )
    # Fail-closed revalidation happens before any filesystem inspection or
    # mutation (Slice 12A correction 1): a rejected registry leaves no snapshots
    # directory or destination artifact behind, and only the revalidated
    # registry — never the potentially tampered caller object — is serialized.
    validated = _revalidate_registry(registry)
    resolved_root = _validate_eval_root(eval_root)
    run_id = _validate_run_id(eval_run_id)
    run_dir = resolved_root / run_id
    if run_dir.is_symlink():
        raise StageProfileError(
            "run directory is a symlink", reason_code="run_directory_symlink"
        )
    if not run_dir.exists():
        raise StageProfileError(
            "run directory does not exist under the evaluation root",
            reason_code="run_directory_missing",
            artifact_reference=run_id,
        )
    if not run_dir.is_dir():
        raise StageProfileError(
            "run directory is not a directory",
            reason_code="run_directory_not_a_directory",
            artifact_reference=run_id,
        )
    snapshots_dir = run_dir / _SNAPSHOTS_DIR
    if snapshots_dir.is_symlink():
        raise StageProfileError(
            "run snapshots directory is a symlink", reason_code="snapshots_directory_symlink"
        )
    if snapshots_dir.exists():
        if not snapshots_dir.is_dir():
            raise StageProfileError(
                "run snapshots path is not a directory",
                reason_code="snapshots_directory_not_a_directory",
            )
    else:
        try:
            snapshots_dir.mkdir(exist_ok=False)
        except OSError as exc:
            raise StageProfileError(
                "failed to create the run snapshots directory",
                reason_code="write_error",
                artifact_reference=f"{run_id}/{_SNAPSHOTS_DIR}",
            ) from exc
    reference = f"{run_id}/{_SNAPSHOTS_DIR}/{_SNAPSHOT_FILENAME}"
    dest = snapshots_dir / _SNAPSHOT_FILENAME
    if dest.is_symlink() or dest.exists():
        raise StageProfileError(
            "stage-profile registry snapshot already exists; snapshots are write-once",
            reason_code="snapshot_exists",
            artifact_reference=reference,
        )
    data = canonical_contract_bytes(validated.model_dump(mode="json", exclude_unset=True)) + b"\n"
    expected = sha256_bytes(data)
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise StageProfileError(
            "stage-profile registry snapshot already exists; snapshots are write-once",
            reason_code="snapshot_exists",
            artifact_reference=reference,
        ) from exc
    except OSError as exc:
        raise StageProfileError(
            "failed to create the stage-profile registry snapshot",
            reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise StageProfileError(
            "failed to write the stage-profile registry snapshot",
            reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        observed = sha256_bytes(dest.read_bytes())
    except OSError as exc:
        raise StageProfileError(
            "failed to re-read the stage-profile registry snapshot for verification",
            reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    if observed != expected:
        raise StageProfileError(
            "persisted stage-profile registry snapshot re-read to a different hash",
            reason_code="destination_hash_mismatch",
            artifact_reference=reference,
        )
    return LoadedStageProfileRegistry(
        registry=validated,
        version=validated.registry_version,
        sha256=observed,
        artifact_reference=reference,
    )


def _validate_run_id(eval_run_id: Any) -> str:
    if not isinstance(eval_run_id, str):
        raise StageProfileError(
            f"eval_run_id must be a string, got {type(eval_run_id).__name__}",
            reason_code="invalid_eval_run_id",
        )
    if not eval_run_id or eval_run_id != eval_run_id.strip():
        raise StageProfileError(
            "eval_run_id must be a non-empty string without leading or trailing whitespace",
            reason_code="invalid_eval_run_id",
        )
    if eval_run_id in (".", ".."):
        raise StageProfileError(
            "eval_run_id is not a valid path component", reason_code="invalid_eval_run_id"
        )
    if "/" in eval_run_id or "\\" in eval_run_id or "\x00" in eval_run_id:
        raise StageProfileError(
            "eval_run_id must be a single path component without separators or NUL",
            reason_code="invalid_eval_run_id",
        )
    if Path(eval_run_id).is_absolute() or len(Path(eval_run_id).parts) != 1:
        raise StageProfileError(
            "eval_run_id must be exactly one relative path component",
            reason_code="invalid_eval_run_id",
        )
    return eval_run_id
