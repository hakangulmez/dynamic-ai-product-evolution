"""Stage metric evidence set (Slice 12I, SPEC-020 / ADR-024).

``stage_metric_evidence_set@0.1.0`` is a strict, frozen, extra-forbid,
model-contract-hash-governed set that binds one Universe evaluation stage's
metric evidence as a canonically ordered tuple of *private* discriminated
variants. Each variant wraps one of the three public Universe payload families
(screen-operational summary, tier-contract observation set, unsafe-exclusion
audit snapshot). Extraction stages carry no such artifact; only Universe stages
produce one.

This module is the leaf owner of the five Universe payload families, re-homed
verbatim from ``metrics.py`` (public model semantics unchanged; ``metrics.py``
re-imports them for backward compatibility). It imports only ``models``,
``contracts``, and ``io_utils`` so it can never participate in an import cycle
with ``metric_inputs`` or ``metrics``.

Read-side plus pure validation and explicit persistence only. Importing this
module performs no filesystem access, hashing, environment inspection, clock
read, UUID generation, network, provider, or model call. Three hash identities
are kept separate: the generated model-contract hash (over the model schema),
the canonical semantic-content hash (newline-free canonical model bytes,
``stage_metric_evidence_set_hash``), and the raw persisted-byte SHA-256
(``LoadedStageMetricEvidenceSet.sha256``; canonical bytes plus one terminal
newline). The persisted-byte value is never substituted for the governed
semantic-content hash.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal, Union

from pydantic import (
    Field,
    ValidationError as PydanticValidationError,
    model_validator,
)

from .contracts import canonical_contract_bytes, model_contract_hash
from .models import ContractStampedModel, EvaluationStrictModel, _require_non_blank
from ..universe.io_utils import sha256_bytes

__all__ = [
    "LoadedStageMetricEvidenceSet",
    "StageEvidenceBindingError",
    "StageEvidenceError",
    "StageMetricEvidenceKind",
    "StageMetricEvidenceSet",
    "load_stage_metric_evidence_set",
    "persist_stage_metric_evidence_set",
    "stage_metric_evidence_set_hash",
]

_CONTRACT_ID = "stage_metric_evidence_set"
_CONTRACT_VERSION = "0.1.0"
_EVIDENCE_DIR = "stage_evidence"
_EVIDENCE_FILENAME = "stage_metric_evidence_set.json"
_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"

# The three governed Universe stage-evidence kinds, in canonical (sorted) order.
StageMetricEvidenceKind = Literal[
    "universe_classification_tier",
    "universe_screen_operational",
    "universe_unsafe_exclusion_audit",
]

# Governed gold verification vocabulary (re-homed from metrics.py; identical).
GoldVerificationStatus = Literal["provisional", "verified"]


def _require_unique(values: tuple[str, ...], field_name: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicate values")


# --- Public errors ---------------------------------------------------------


class StageEvidenceError(Exception):
    """Sanitized stage-evidence failure with a stable machine-readable code.

    No raw content, absolute path, or raw Pydantic/OS text is placed in the
    message.
    """

    def __init__(
        self, message: str, *, reason_code: str, artifact_reference: str | None = None
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.artifact_reference = artifact_reference


class StageEvidenceBindingError(Exception):
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


# --- Re-homed public Universe payload families ----------------------------
# Verbatim from metrics.py; public model semantics unchanged (the only change is
# the strict base class, whose config — extra-forbid + frozen — is identical to
# the previous ``_Slice9StrictModel``, so each model's generated JSON Schema is
# byte-identical).


class UnsafeAuditLabel(EvaluationStrictModel):
    record_id: str
    verification_status: Literal["verified"]
    actually_eligible_or_boundary_relevant: bool

    @model_validator(mode="after")
    def _label_invariants(self) -> "UnsafeAuditLabel":
        _require_non_blank(self.record_id, "record_id")
        return self


class UnsafeAuditStratum(EvaluationStrictModel):
    stratum_id: str
    screen_negative_population_count: int
    audited_labels: tuple[UnsafeAuditLabel, ...]

    @model_validator(mode="after")
    def _stratum_invariants(self) -> "UnsafeAuditStratum":
        _require_non_blank(self.stratum_id, "stratum_id")
        if self.screen_negative_population_count <= 0:
            raise ValueError("screen_negative_population_count must be positive")
        if len(self.audited_labels) > self.screen_negative_population_count:
            raise ValueError("audited count cannot exceed the stratum population")
        return self


class UnsafeExclusionAuditSnapshot(EvaluationStrictModel):
    audit_snapshot_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    seed: int
    sampling_design_id: str
    strata: tuple[UnsafeAuditStratum, ...]

    @model_validator(mode="after")
    def _audit_invariants(self) -> "UnsafeExclusionAuditSnapshot":
        _require_non_blank(self.sampling_design_id, "sampling_design_id")
        if not self.strata:
            raise ValueError("audit snapshot requires at least one stratum")
        stratum_ids = tuple(s.stratum_id for s in self.strata)
        _require_unique(stratum_ids, "stratum_id")
        record_ids: list[str] = []
        for stratum in self.strata:
            for label in stratum.audited_labels:
                record_ids.append(label.record_id)
        _require_unique(tuple(record_ids), "audit record_id")
        return self


class TierContractObservation(EvaluationStrictModel):
    """One deterministic tier-contract observation (expected vs observed)."""

    record_id: str
    verification_status: GoldVerificationStatus
    tier_rule_version: str
    expected_tier: str
    observed_tier: str
    expected_reason_codes: tuple[str, ...]
    observed_reason_codes: tuple[str, ...]
    expected_rule_trace_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    observed_rule_trace_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    repeatability_output_hashes: tuple[str, ...]

    @model_validator(mode="after")
    def _tier_invariants(self) -> "TierContractObservation":
        _require_non_blank(self.record_id, "record_id")
        _require_non_blank(self.tier_rule_version, "tier_rule_version")
        _require_non_blank(self.expected_tier, "expected_tier")
        _require_non_blank(self.observed_tier, "observed_tier")
        for code in (*self.expected_reason_codes, *self.observed_reason_codes):
            _require_non_blank(code, "reason code")
        _require_unique(self.expected_reason_codes, "expected_reason_codes")
        _require_unique(self.observed_reason_codes, "observed_reason_codes")
        if len(self.repeatability_output_hashes) < 2:
            raise ValueError("at least two repeatability output hashes are required")
        for h in self.repeatability_output_hashes:
            if len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
                raise ValueError("repeatability output hashes must be lowercase 64-hex")
        return self

    @property
    def repeatability_ok(self) -> bool:
        return len(set(self.repeatability_output_hashes)) == 1

    @property
    def exact_contract_ok(self) -> bool:
        return (
            self.expected_tier == self.observed_tier
            and self.expected_reason_codes == self.observed_reason_codes
            and self.expected_rule_trace_hash == self.observed_rule_trace_hash
            and self.repeatability_ok
        )


class ScreenOperationalSummary(EvaluationStrictModel):
    total_screened: int
    screen_negative: int
    screen_nonnegative: int
    unresolved: int
    downstream_review_count: int

    @model_validator(mode="after")
    def _operational_invariants(self) -> "ScreenOperationalSummary":
        for name in (
            "total_screened", "screen_negative", "screen_nonnegative",
            "unresolved", "downstream_review_count",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.screen_negative + self.screen_nonnegative + self.unresolved != self.total_screened:
            raise ValueError(
                "screen_negative + screen_nonnegative + unresolved must equal total_screened"
            )
        return self


# --- Private discriminated Universe evidence variants ---------------------
# Module-private (never exported). Each variant carries its discriminator kind
# plus exactly one payload family.


class _ClassificationTierEvidence(EvaluationStrictModel):
    kind: Literal["universe_classification_tier"]
    tier_contract_observations: tuple[TierContractObservation, ...]

    @model_validator(mode="after")
    def _tier_evidence_invariants(self) -> "_ClassificationTierEvidence":
        if not self.tier_contract_observations:
            raise ValueError("tier evidence requires at least one observation")
        record_ids = tuple(o.record_id for o in self.tier_contract_observations)
        _require_unique(record_ids, "tier observation record_id")
        return self


class _ScreenOperationalEvidence(EvaluationStrictModel):
    kind: Literal["universe_screen_operational"]
    screen_operational_summary: ScreenOperationalSummary


class _UnsafeExclusionAuditEvidence(EvaluationStrictModel):
    kind: Literal["universe_unsafe_exclusion_audit"]
    unsafe_exclusion_audit: UnsafeExclusionAuditSnapshot


_UniverseEvidenceVariant = Annotated[
    Union[
        _ClassificationTierEvidence,
        _ScreenOperationalEvidence,
        _UnsafeExclusionAuditEvidence,
    ],
    Field(discriminator="kind"),
]


# --- Stage-scoped evidence set --------------------------------------------


class StageMetricEvidenceSet(ContractStampedModel):
    # Docstring intentionally omitted so the generated JSON Schema (and thus the
    # governed model-contract hash) carries no description.
    _contract_id: ClassVar[str] = _CONTRACT_ID
    _contract_version: ClassVar[str] = _CONTRACT_VERSION

    evaluation_stage: str
    set_version: str
    variants: tuple[_UniverseEvidenceVariant, ...]

    @model_validator(mode="after")
    def _set_invariants(self) -> "StageMetricEvidenceSet":
        _require_non_blank(self.evaluation_stage, "evaluation_stage")
        _require_non_blank(self.set_version, "set_version")
        if not self.variants:
            raise ValueError("stage metric evidence set must be non-empty")
        kinds = tuple(v.kind for v in self.variants)
        if list(kinds) != sorted(kinds):
            raise ValueError("variants must be in canonical ascending kind order")
        _require_unique(kinds, "variant kind")
        return self

    @property
    def present_kinds(self) -> tuple[str, ...]:
        """The canonical tuple of present variant kinds."""
        return tuple(v.kind for v in self.variants)


class LoadedStageMetricEvidenceSet(EvaluationStrictModel):
    """A validated stage-evidence set plus its raw-byte binding material."""

    model: StageMetricEvidenceSet
    version: str
    sha256: str
    artifact_reference: str


# --- Sanctioned constructor (module-level; not a package export) -----------


def build_stage_metric_evidence_set(
    *,
    evaluation_stage: str,
    set_version: str,
    variants: tuple[dict[str, Any], ...],
) -> StageMetricEvidenceSet:
    """Construct a contract-stamped stage-evidence set (test/fixture path).

    Owns its contract stamp: the contract ID, version, and generated
    model-contract hash are computed here, never caller-supplied. ``variants``
    are discriminated payload dicts (each with a ``kind`` field).
    """
    stamp_hash = model_contract_hash(StageMetricEvidenceSet, _CONTRACT_ID, _CONTRACT_VERSION)
    return StageMetricEvidenceSet.model_validate({
        "contract": {
            "contract_id": _CONTRACT_ID,
            "contract_version": _CONTRACT_VERSION,
            "contract_hash": stamp_hash,
        },
        "evaluation_stage": evaluation_stage,
        "set_version": set_version,
        "variants": list(variants),
    })


# --- Content hash + fail-closed revalidation ------------------------------


def _revalidate(model: StageMetricEvidenceSet) -> StageMetricEvidenceSet:
    if not isinstance(model, StageMetricEvidenceSet):
        raise TypeError(f"expected a StageMetricEvidenceSet, got {type(model).__name__}")
    try:
        payload = model.model_dump(mode="json", exclude_unset=True)
    except Exception as exc:  # noqa: BLE001 - any serialization defect fails closed
        raise StageEvidenceError(
            "stage metric evidence set could not be serialized for revalidation",
            reason_code="model_validation",
        ) from exc
    try:
        return StageMetricEvidenceSet.model_validate(payload)
    except PydanticValidationError as exc:
        raise StageEvidenceError(
            "stage metric evidence set failed fail-closed revalidation",
            reason_code="model_validation",
        ) from exc


def stage_metric_evidence_set_hash(model: StageMetricEvidenceSet) -> str:
    """The governed canonical semantic-content hash over newline-free bytes.

    Distinct from ``LoadedStageMetricEvidenceSet.sha256`` (raw persisted bytes).
    The model is revalidated fail-closed before hashing.
    """
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
        raise StageEvidenceError(
            "eval_root must be an explicit str or Path evaluation root",
            reason_code="invalid_eval_root",
        )
    if isinstance(eval_root, str) and eval_root == "":
        raise StageEvidenceError(
            "eval_root must not be an empty string; supply the evaluation root explicitly",
            reason_code="invalid_eval_root",
        )
    root = Path(eval_root)
    if root.is_symlink():
        raise StageEvidenceError("eval_root must not be a symlink", reason_code="eval_root_symlink")
    if not root.exists():
        raise StageEvidenceError("evaluation root does not exist", reason_code="invalid_eval_root")
    if not root.is_dir():
        raise StageEvidenceError(
            "evaluation root is not a directory", reason_code="invalid_eval_root"
        )
    return root.resolve()


def _resolve_contained(reference: str | Path, resolved_root: Path) -> tuple[Path, str]:
    if not _is_safe_reference(reference if isinstance(reference, str) else str(reference)):
        if not isinstance(reference, (str, Path)):
            raise StageEvidenceError(
                "reference must be an explicit str or Path", reason_code="invalid_path"
            )
        raise StageEvidenceError(
            "reference is not a safe relative reference", reason_code="unsafe_reference"
        )
    candidate = resolved_root / Path(reference)
    if candidate.is_symlink():
        raise StageEvidenceError("artifact path is a symlink", reason_code="artifact_symlink")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise StageEvidenceError(
            "artifact path resolves outside the evaluation root", reason_code="path_escape"
        )
    ref = resolved.relative_to(resolved_root).as_posix()
    if resolved.is_symlink():
        raise StageEvidenceError(
            "artifact is a symlink", reason_code="artifact_symlink", artifact_reference=ref
        )
    if not resolved.exists():
        raise StageEvidenceError(
            "artifact does not exist under the evaluation root",
            reason_code="artifact_missing",
            artifact_reference=ref,
        )
    if not resolved.is_file():
        raise StageEvidenceError(
            "artifact is not a regular file",
            reason_code="artifact_not_a_file",
            artifact_reference=ref,
        )
    return resolved, ref


def _validate_run_id(eval_run_id: Any) -> str:
    if not isinstance(eval_run_id, str):
        raise StageEvidenceError(
            f"eval_run_id must be a string, got {type(eval_run_id).__name__}",
            reason_code="invalid_eval_run_id",
        )
    if not eval_run_id or eval_run_id != eval_run_id.strip():
        raise StageEvidenceError(
            "eval_run_id must be a non-empty string without leading or trailing whitespace",
            reason_code="invalid_eval_run_id",
        )
    if eval_run_id in (".", ".."):
        raise StageEvidenceError(
            "eval_run_id is not a valid path component", reason_code="invalid_eval_run_id"
        )
    if "/" in eval_run_id or "\\" in eval_run_id or "\x00" in eval_run_id:
        raise StageEvidenceError(
            "eval_run_id must be a single path component without separators or NUL",
            reason_code="invalid_eval_run_id",
        )
    if Path(eval_run_id).is_absolute() or len(Path(eval_run_id).parts) != 1:
        raise StageEvidenceError(
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
        raise StageEvidenceError(
            "artifact is not valid JSON", reason_code="json_error", artifact_reference=reference
        ) from exc
    except _DuplicateKeyControl as exc:
        raise StageEvidenceError(
            "artifact contains a duplicate JSON object key",
            reason_code="duplicate_key",
            artifact_reference=reference,
        ) from exc
    except _NonFiniteControl as exc:
        raise StageEvidenceError(
            "artifact contains a non-JSON numeric constant",
            reason_code="non_finite",
            artifact_reference=reference,
        ) from exc
    if _has_non_finite(payload):
        raise StageEvidenceError(
            "artifact contains a non-finite JSON number",
            reason_code="non_finite",
            artifact_reference=reference,
        )
    if not isinstance(payload, dict):
        raise StageEvidenceError(
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
        raise StageEvidenceError(
            "failed to read the artifact", reason_code="read_error", artifact_reference=ref
        ) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StageEvidenceError(
            "artifact is not valid UTF-8", reason_code="decode_error", artifact_reference=ref
        ) from exc
    return raw, text, ref


# --- Loader ---------------------------------------------------------------


def load_stage_metric_evidence_set(
    path: str | Path,
    *,
    eval_root: str | Path,
    expected_sha256: str | None = None,
) -> LoadedStageMetricEvidenceSet:
    """Load, hash-bind, and strictly validate a stage metric evidence set."""
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
            raise StageEvidenceError(
                "stage metric evidence set raw-byte hash does not match the expected hash",
                reason_code="expected_hash_mismatch",
                artifact_reference=reference,
            )
    payload = _strict_json_object(text, reference)
    try:
        model = StageMetricEvidenceSet.model_validate(payload)
    except PydanticValidationError as exc:
        raise StageEvidenceError(
            "stage metric evidence set failed strict contract validation",
            reason_code="model_validation",
            artifact_reference=reference,
        ) from exc
    return LoadedStageMetricEvidenceSet(
        model=model,
        version=model.set_version,
        sha256=observed,
        artifact_reference=reference,
    )


# --- Persistence ----------------------------------------------------------


def persist_stage_metric_evidence_set(
    model: StageMetricEvidenceSet,
    *,
    eval_root: str | Path,
    eval_run_id: str,
) -> LoadedStageMetricEvidenceSet:
    """Write the canonical set JSON (plus one terminal newline) write-once.

    Destination:
    ``<eval_root>/<eval_run_id>/stage_evidence/stage_metric_evidence_set.json``.
    The returned ``sha256`` binds the persisted bytes (with the newline); the
    governed semantic-content hash is ``stage_metric_evidence_set_hash``.
    """
    validated = _revalidate(model)
    run_id = _validate_run_id(eval_run_id)
    resolved_root = _validate_eval_root(eval_root)
    run_dir = resolved_root / run_id
    if run_dir.is_symlink():
        raise StageEvidenceError("run directory is a symlink", reason_code="run_directory_symlink")
    if not run_dir.exists():
        raise StageEvidenceError(
            "run directory does not exist under the evaluation root",
            reason_code="run_directory_missing",
            artifact_reference=run_id,
        )
    if not run_dir.is_dir():
        raise StageEvidenceError(
            "run directory is not a directory",
            reason_code="run_directory_not_a_directory",
            artifact_reference=run_id,
        )
    evidence_dir = run_dir / _EVIDENCE_DIR
    if evidence_dir.is_symlink():
        raise StageEvidenceError(
            "run stage-evidence directory is a symlink",
            reason_code="evidence_directory_symlink",
        )
    if evidence_dir.exists():
        if not evidence_dir.is_dir():
            raise StageEvidenceError(
                "run stage-evidence path is not a directory",
                reason_code="evidence_directory_not_a_directory",
            )
    else:
        try:
            evidence_dir.mkdir(exist_ok=False)
        except OSError as exc:
            raise StageEvidenceError(
                "failed to create the run stage-evidence directory",
                reason_code="write_error",
                artifact_reference=f"{run_id}/{_EVIDENCE_DIR}",
            ) from exc
    reference = f"{run_id}/{_EVIDENCE_DIR}/{_EVIDENCE_FILENAME}"
    dest = evidence_dir / _EVIDENCE_FILENAME
    if dest.is_symlink() or dest.exists():
        raise StageEvidenceError(
            "stage metric evidence set already exists; artifacts are write-once",
            reason_code="artifact_exists",
            artifact_reference=reference,
        )
    data = canonical_contract_bytes(validated.model_dump(mode="json", exclude_unset=True)) + b"\n"
    expected = sha256_bytes(data)
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise StageEvidenceError(
            "stage metric evidence set already exists; artifacts are write-once",
            reason_code="artifact_exists",
            artifact_reference=reference,
        ) from exc
    except OSError as exc:
        raise StageEvidenceError(
            "failed to create the stage metric evidence set",
            reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise StageEvidenceError(
            "failed to write the stage metric evidence set",
            reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        observed = sha256_bytes(dest.read_bytes())
    except OSError as exc:
        raise StageEvidenceError(
            "failed to re-read the stage metric evidence set for verification",
            reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    if observed != expected:
        raise StageEvidenceError(
            "persisted stage metric evidence set re-read to a different hash",
            reason_code="destination_hash_mismatch",
            artifact_reference=reference,
        )
    return LoadedStageMetricEvidenceSet(
        model=validated,
        version=validated.set_version,
        sha256=observed,
        artifact_reference=reference,
    )
