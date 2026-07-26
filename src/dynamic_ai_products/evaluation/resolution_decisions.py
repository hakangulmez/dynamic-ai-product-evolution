"""Observation-target resolution decisions (P1, ADR-026 / ADR-027).

This module is the **canonical owner** of the adjudication layer that
``observation_target_binding`` consumes:

* ``EXTRACTION_EVALUATION_STAGES`` — the governed extraction-stage vocabulary;
* ``ObservationTargetResolutionProvenance`` and
  ``ObservationTargetResolutionDecision`` — the typed decision boundary;
* ``observation_target_resolution_decision_set@0.1.0`` — the **run-external**,
  hash-bound artifact an adjudicator authors and persists, plus its loader.

Ownership lives here, not in ``observation_target_binding``, so the dependency
runs one way only: this module never imports the binding module, while the
binding module imports these names and re-exports them under the same names for
backward compatibility. Moving the models changed no field, validator, or
generated JSON Schema — nested models are keyed in ``$defs`` by bare class name,
so ``observation_target_binding@0.1.0``'s governed contract hash is unchanged.

``ObservationTargetResolutionDecision`` is a **human/adjudicator judgement**; no
deterministic producer may synthesise it. The decision set therefore exists as an
artifact authored *before* a run: the adjudicator parses the prediction with the
governed semantic adapter, takes the exact parsed-content artifact SHA-256 with
``parsed_prediction_content_artifact_sha256`` (no run directory required), writes
the typed set write-once under the adjudication source root, and the runner later
re-derives the same parse and verifies every pin by exact equality. A raw dict or
hand-written JSON document is not a production authoring path — the typed
persistence API is.

Importing this module performs no filesystem access, hashing, clock read, or
network call; all loading and persistence is explicit.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import (
    Field,
    ValidationError as PydanticValidationError,
    model_validator,
)

from .contracts import canonical_contract_bytes, model_contract_hash
from .models import (
    ContractStampedModel,
    EvaluationStrictModel,
    _reject_explicit_null,
    _require_non_blank,
    _require_rfc3339_offset,
)
from .stage_evidence import GoldVerificationStatus
from ..universe.io_utils import sha256_bytes

__all__ = [
    "EXTRACTION_EVALUATION_STAGES",
    "LoadedObservationTargetResolutionDecisionSet",
    "ObservationTargetResolutionDecision",
    "ObservationTargetResolutionDecisionSet",
    "ObservationTargetResolutionDecisionSetError",
    "ObservationTargetResolutionProvenance",
    "load_observation_target_resolution_decision_set",
    "persist_observation_target_resolution_decision_set",
]

_CONTRACT_ID = "observation_target_resolution_decision_set"
_CONTRACT_VERSION = "0.1.0"
_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"
_HEX = {"min_length": 64, "max_length": 64, "pattern": _SHA256_HEX_PATTERN}

# The governed extraction-stage vocabulary. Single source of truth for every
# consumer (both semantic evaluators, output-manifest v0.2, and the decision-set
# contract below); a drift test reconciles it with the semantic adapter's
# implemented-stage vocabulary.
EXTRACTION_EVALUATION_STAGES: frozenset[str] = frozenset(
    {"capability_extraction", "task_extraction"}
)

# Omit-or-non-null optional properties: absence is legal, explicit JSON null is
# rejected rather than silently rewritten into absence. NOTE
# ``canonical_target_reference`` is deliberately NOT in this tuple: it is a
# required field whose JSON null is the mandated unresolved representation.
_PROVENANCE_OMIT_OR_NON_NULL = (
    "source_field_name",
    "source_field_value",
    "registry_entry_reference_id",
    "registry_entry_matched_alias",
    "unresolved_reason_code",
    "adjudication_reference",
)


# --- Public error ----------------------------------------------------------


class ObservationTargetResolutionDecisionSetError(Exception):
    """Sanitized decision-set failure with a stable machine-readable code.

    No raw content, absolute path, or raw Pydantic/OS text is placed in the
    message.
    """

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


# --- Small local validators ------------------------------------------------


def _require_unique_non_blank(values: tuple[str, ...], field_name: str) -> None:
    for value in values:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError(f"each {field_name} entry must be a non-blank unstripped string")
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain a duplicate entry")


def _is_safe_reference(value: Any) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if value.startswith("/") or "\\" in value or "\x00" in value:
        return False
    return all(part not in ("", ".", "..") for part in value.split("/"))


def _is_lower_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


# --- Public adjudication models --------------------------------------------


class ObservationTargetResolutionProvenance(EvaluationStrictModel):
    """How one observation-target decision was reached, plus its governance record."""

    # How the decision was reached.
    resolution_method: Literal[
        "stable_identity_field",
        "registry_alias",
        "parent_link_field",
        "declared_unresolved",
    ]
    source_field_name: str | None = None
    source_field_value: str | None = None
    registry_entry_reference_id: str | None = None
    registry_entry_matched_alias: str | None = None
    unresolved_reason_code: str | None = None
    # Governance: never omitted, never inferred, never clock-generated here.
    resolver_kind: Literal["deterministic_rule", "model_assisted", "human_adjudicated"]
    resolver_ids: tuple[str, ...]
    reviewer_ids: tuple[str, ...] = ()
    verification_status: GoldVerificationStatus
    verification_method: Literal[
        "dual_independent_adjudication",
        "solo_blinded_retest",
        "expert_second_review",
        "deterministic_rule_review",
    ]
    decision_timestamps: tuple[str, ...]
    change_reason: str
    adjudication_reference: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_explicit_null(cls, data: Any) -> Any:
        return _reject_explicit_null(
            data, _PROVENANCE_OMIT_OR_NON_NULL, "ObservationTargetResolutionProvenance"
        )

    @model_validator(mode="after")
    def _provenance_invariants(self) -> "ObservationTargetResolutionProvenance":
        method_fields = (
            self.source_field_name,
            self.source_field_value,
            self.registry_entry_reference_id,
            self.registry_entry_matched_alias,
        )
        if self.resolution_method == "declared_unresolved":
            if self.unresolved_reason_code is None:
                raise ValueError("declared_unresolved requires an unresolved_reason_code")
            _require_non_blank(self.unresolved_reason_code, "unresolved_reason_code")
            if any(value is not None for value in method_fields):
                raise ValueError(
                    "declared_unresolved must not carry any resolution/source field"
                )
        else:
            if self.unresolved_reason_code is not None:
                raise ValueError("a resolving method must not carry an unresolved_reason_code")
            if self.registry_entry_reference_id is None:
                raise ValueError("a resolving method requires a registry_entry_reference_id")
            _require_non_blank(self.registry_entry_reference_id, "registry_entry_reference_id")
            if self.resolution_method in ("stable_identity_field", "parent_link_field"):
                if self.source_field_name is None or self.source_field_value is None:
                    raise ValueError(
                        "a field-derived method requires source_field_name and "
                        "source_field_value"
                    )
                _require_non_blank(self.source_field_name, "source_field_name")
                _require_non_blank(self.source_field_value, "source_field_value")
            if self.resolution_method == "registry_alias":
                if self.registry_entry_matched_alias is None:
                    raise ValueError("registry_alias requires a registry_entry_matched_alias")
                _require_non_blank(
                    self.registry_entry_matched_alias, "registry_entry_matched_alias"
                )
        # Governance invariants.
        if not self.resolver_ids:
            raise ValueError("resolver_ids must not be empty")
        _require_unique_non_blank(self.resolver_ids, "resolver_ids")
        _require_unique_non_blank(self.reviewer_ids, "reviewer_ids")
        if set(self.resolver_ids) & set(self.reviewer_ids):
            raise ValueError("self_review_forbidden: resolver_ids and reviewer_ids must be disjoint")
        if self.verification_status == "verified" and not self.reviewer_ids:
            raise ValueError("a verified decision requires at least one reviewer id")
        if self.resolver_kind == "human_adjudicated":
            if not self.reviewer_ids:
                raise ValueError("a human-adjudicated decision requires at least one reviewer id")
            if self.adjudication_reference is None:
                raise ValueError(
                    "a human-adjudicated decision requires an adjudication_reference"
                )
        if (
            self.verification_method == "deterministic_rule_review"
            and self.resolver_kind != "deterministic_rule"
        ):
            raise ValueError(
                "deterministic_rule_review applies only to a deterministic_rule resolver"
            )
        if not self.decision_timestamps:
            raise ValueError("decision_timestamps must not be empty")
        for stamp in self.decision_timestamps:
            _require_rfc3339_offset(stamp, "decision_timestamps entry")
        _require_non_blank(self.change_reason, "change_reason")
        if self.adjudication_reference is not None and not _is_safe_reference(
            self.adjudication_reference
        ):
            raise ValueError("adjudication_reference must be a safe relative reference")
        return self


class ObservationTargetResolutionDecision(EvaluationStrictModel):
    """One adjudicated raw-observation -> canonical-target decision.

    ``canonical_target_reference`` is a **required** field, not an
    omit-or-non-null optional: a resolved decision carries a non-blank string, an
    unresolved decision carries JSON ``null``, and it is never omitted.
    """

    observation_id: str
    observation_kind: Literal["product", "capability", "task"]
    resolution_status: Literal["resolved", "unresolved"]
    canonical_target_reference: str | None
    parent_referenced: bool
    provenance: ObservationTargetResolutionProvenance

    @model_validator(mode="after")
    def _decision_invariants(self) -> "ObservationTargetResolutionDecision":
        _require_non_blank(self.observation_id, "observation_id")
        if self.resolution_status == "resolved":
            if self.canonical_target_reference is None:
                raise ValueError(
                    "a resolved decision requires a non-null canonical_target_reference"
                )
            _require_non_blank(self.canonical_target_reference, "canonical_target_reference")
            if self.provenance.resolution_method == "declared_unresolved":
                raise ValueError("a resolved decision must not declare an unresolved method")
        else:
            if self.canonical_target_reference is not None:
                raise ValueError(
                    "an unresolved decision requires canonical_target_reference to be null"
                )
            if self.provenance.resolution_method != "declared_unresolved":
                raise ValueError(
                    "an unresolved decision requires the declared_unresolved method"
                )
        return self

    @property
    def _identity(self) -> str:
        return self.observation_id


# --- Persisted run-external decision set ----------------------------------


class ObservationTargetResolutionDecisionSet(ContractStampedModel):
    # Docstring intentionally omitted so the generated JSON Schema (and thus the
    # governed model-contract hash) carries no description.
    _contract_id: ClassVar[str] = _CONTRACT_ID
    _contract_version: ClassVar[str] = _CONTRACT_VERSION

    decision_set_version: str
    case_id: str
    stage: str
    company_id: str
    prediction_record_id: str
    raw_artifact_reference: str
    raw_artifact_sha256: str = Field(**_HEX)
    parsed_prediction_content_sha256: str = Field(**_HEX)
    decisions: tuple[ObservationTargetResolutionDecision, ...]

    @model_validator(mode="after")
    def _set_invariants(self) -> "ObservationTargetResolutionDecisionSet":
        for name in (
            "decision_set_version", "case_id", "stage", "company_id", "prediction_record_id",
        ):
            _require_non_blank(getattr(self, name), name)
        if self.stage not in EXTRACTION_EVALUATION_STAGES:
            raise ValueError("stage must be a governed extraction evaluation stage")
        if not _is_safe_reference(self.raw_artifact_reference):
            raise ValueError("raw_artifact_reference must be a safe relative reference")
        if not self.decisions:
            raise ValueError("decisions must not be empty")
        ids = [decision.observation_id for decision in self.decisions]
        if ids != sorted(ids):
            raise ValueError("decisions must be sorted canonically by observation_id")
        if len(set(ids)) != len(ids):
            raise ValueError("decisions must not contain a duplicate observation_id")
        return self


class LoadedObservationTargetResolutionDecisionSet(EvaluationStrictModel):
    """A validated decision set plus its raw-byte binding material."""

    model: ObservationTargetResolutionDecisionSet
    version: str
    sha256: str
    artifact_reference: str


# --- Fail-closed revalidation ---------------------------------------------
#
# ``model_copy(update=...)`` and ``model_construct(...)`` bypass Pydantic
# validators, so an object can satisfy ``isinstance`` while carrying content that
# never passed the governed invariants. Every public API revalidates a supplied
# instance by dumping it and re-running full validation, then operates on the
# revalidated result. ``exclude_unset`` preserves omit-or-non-null semantics for
# optional properties; the required ``canonical_target_reference`` is always set,
# so an unresolved decision round-trips with its JSON null intact.


def _revalidate_set(
    model: ObservationTargetResolutionDecisionSet,
) -> ObservationTargetResolutionDecisionSet:
    if not isinstance(model, ObservationTargetResolutionDecisionSet):
        raise TypeError(
            "expected an ObservationTargetResolutionDecisionSet, got "
            f"{type(model).__name__}"
        )
    try:
        payload = model.model_dump(mode="json", exclude_unset=True)
    except Exception as exc:  # noqa: BLE001 - any serialization defect fails closed
        raise ObservationTargetResolutionDecisionSetError(
            "decision set could not be serialized for revalidation",
            reason_code="model_validation",
        ) from exc
    try:
        return ObservationTargetResolutionDecisionSet.model_validate(payload)
    except PydanticValidationError as exc:
        raise ObservationTargetResolutionDecisionSetError(
            "decision set failed fail-closed revalidation", reason_code="model_validation"
        ) from exc


def _revalidate_loaded_set(loaded: Any) -> ObservationTargetResolutionDecisionSet:
    """Internal consumer boundary: revalidate a loaded wrapper's inner set.

    Deliberately module-private — the binding producer is the only consumer, and
    this adds no package export. A wrapper produced through ``model_construct``
    or ``model_copy(update=...)`` can satisfy ``isinstance`` while carrying an
    inner model that never passed the **set-level** invariants (canonical
    decision ordering, ``observation_id`` uniqueness, the governed stage
    vocabulary, non-blank identities, safe raw-artifact reference) or a declared
    wrapper version that disagrees with the revalidated contract stamp. Both fail
    closed here: revalidating each decision individually is not a substitute for
    the set-level rules, which live on the set model alone.
    """
    inner = getattr(loaded, "model", None)
    if not isinstance(inner, ObservationTargetResolutionDecisionSet):
        raise ObservationTargetResolutionDecisionSetError(
            "the loaded wrapper does not carry an ObservationTargetResolutionDecisionSet",
            reason_code="model_validation",
        )
    validated = _revalidate_set(inner)
    if getattr(loaded, "version", None) != validated.contract.contract_version:
        raise ObservationTargetResolutionDecisionSetError(
            "the loaded wrapper version does not equal the revalidated contract version",
            reason_code="model_validation",
        )
    return validated


def _contract_metadata() -> dict[str, str]:
    return {
        "contract_id": _CONTRACT_ID,
        "contract_version": _CONTRACT_VERSION,
        "contract_hash": model_contract_hash(
            ObservationTargetResolutionDecisionSet, _CONTRACT_ID, _CONTRACT_VERSION
        ),
    }


# --- Roots / references / strict parse -------------------------------------


def _validate_source_root(source_root: str | Path) -> Path:
    if not isinstance(source_root, (str, Path)):
        raise ObservationTargetResolutionDecisionSetError(
            "source_root must be an explicit str or Path adjudication root",
            reason_code="invalid_source_root",
        )
    if isinstance(source_root, str) and source_root == "":
        raise ObservationTargetResolutionDecisionSetError(
            "source_root must not be an empty string", reason_code="invalid_source_root"
        )
    root = Path(source_root)
    if root.is_symlink():
        raise ObservationTargetResolutionDecisionSetError(
            "source_root must not be a symlink", reason_code="source_root_symlink"
        )
    if not root.exists() or not root.is_dir():
        raise ObservationTargetResolutionDecisionSetError(
            "adjudication source root does not exist or is not a directory",
            reason_code="invalid_source_root",
        )
    return root.resolve()


def _walk_parents(candidate: Path, root: Path) -> list[Path]:
    parts: list[Path] = []
    current = candidate
    while True:
        parts.append(current)
        if current == root or current.parent == current:
            break
        current = current.parent
    return parts


def _resolve_contained(reference: Any, resolved_root: Path, *, must_exist: bool) -> Path:
    """Resolve a safe relative reference inside the root, rejecting escapes."""
    if not _is_safe_reference(reference):
        raise ObservationTargetResolutionDecisionSetError(
            "the decision-set reference is not a safe relative reference",
            reason_code="unsafe_reference",
        )
    candidate = resolved_root / reference
    for part in _walk_parents(candidate, resolved_root):
        if part.is_symlink():
            raise ObservationTargetResolutionDecisionSetError(
                "a decision-set path component is a symlink",
                reason_code="artifact_symlink", artifact_reference=reference,
            )
    resolved = (
        candidate.resolve() if candidate.exists()
        else (candidate.parent.resolve() / candidate.name)
    )
    if not resolved.is_relative_to(resolved_root):
        raise ObservationTargetResolutionDecisionSetError(
            "the decision set resolves outside the adjudication source root",
            reason_code="path_escape", artifact_reference=reference,
        )
    if must_exist:
        if not resolved.exists():
            raise ObservationTargetResolutionDecisionSetError(
                "the decision set does not exist under the adjudication source root",
                reason_code="artifact_missing", artifact_reference=reference,
            )
        if not resolved.is_file():
            raise ObservationTargetResolutionDecisionSetError(
                "the decision set is not a regular file",
                reason_code="artifact_not_a_file", artifact_reference=reference,
            )
    return resolved


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise _DuplicateKeyControl()
        seen.add(key)
        result[key] = value
    return result


def _reject_non_finite_constant(_name: str) -> Any:
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


# --- Persistence -----------------------------------------------------------


def persist_observation_target_resolution_decision_set(
    model: ObservationTargetResolutionDecisionSet,
    *,
    source_root: str | Path,
    reference: str,
) -> LoadedObservationTargetResolutionDecisionSet:
    """Write canonical decision-set JSON (plus one terminal newline) write-once.

    The decision set is a **run-external** pre-run input, so — unlike the
    run-directory artifacts — it has no fixed subdirectory or filename: the
    adjudicator supplies a safe relative ``reference`` under ``source_root``. The
    reference's parent directory must already exist; no directory tree is created
    implicitly. This typed path is the only production authoring route; a
    hand-written JSON document is not one.
    """
    validated = _revalidate_set(model)
    resolved_root = _validate_source_root(source_root)
    dest = _resolve_contained(reference, resolved_root, must_exist=False)
    parent = dest.parent
    if parent.is_symlink():
        raise ObservationTargetResolutionDecisionSetError(
            "the decision-set parent directory is a symlink",
            reason_code="parent_directory_symlink", artifact_reference=reference,
        )
    if not parent.exists():
        raise ObservationTargetResolutionDecisionSetError(
            "the decision-set parent directory does not exist",
            reason_code="parent_directory_missing", artifact_reference=reference,
        )
    if not parent.is_dir():
        raise ObservationTargetResolutionDecisionSetError(
            "the decision-set parent path is not a directory",
            reason_code="parent_directory_not_a_directory", artifact_reference=reference,
        )
    if dest.is_symlink() or dest.exists():
        raise ObservationTargetResolutionDecisionSetError(
            "the decision set already exists; adjudication artifacts are write-once",
            reason_code="artifact_exists", artifact_reference=reference,
        )
    data = canonical_contract_bytes(validated.model_dump(mode="json", exclude_unset=True)) + b"\n"
    expected = sha256_bytes(data)
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise ObservationTargetResolutionDecisionSetError(
            "the decision set already exists; adjudication artifacts are write-once",
            reason_code="artifact_exists", artifact_reference=reference,
        ) from exc
    except OSError as exc:
        raise ObservationTargetResolutionDecisionSetError(
            "failed to create the decision set", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ObservationTargetResolutionDecisionSetError(
            "failed to write the decision set", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        observed = sha256_bytes(dest.read_bytes())
    except OSError as exc:
        raise ObservationTargetResolutionDecisionSetError(
            "failed to re-read the decision set for verification",
            reason_code="write_error", artifact_reference=reference,
        ) from exc
    if observed != expected:
        raise ObservationTargetResolutionDecisionSetError(
            "persisted decision set re-read to a different hash",
            reason_code="destination_hash_mismatch", artifact_reference=reference,
        )
    return LoadedObservationTargetResolutionDecisionSet(
        model=validated, version=validated.contract.contract_version,
        sha256=observed, artifact_reference=str(reference),
    )


# --- Loader ---------------------------------------------------------------


def load_observation_target_resolution_decision_set(
    path: str | Path, *, source_root: str | Path, expected_sha256: str | None = None
) -> LoadedObservationTargetResolutionDecisionSet:
    """Load, hash-bind, and strictly validate one run-external decision set."""
    resolved_root = _validate_source_root(source_root)
    if not isinstance(path, (str, Path)):
        raise ObservationTargetResolutionDecisionSetError(
            "path must be an explicit str or Path", reason_code="invalid_path"
        )
    reference = str(path)
    resolved = _resolve_contained(reference, resolved_root, must_exist=True)
    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        raise ObservationTargetResolutionDecisionSetError(
            "failed to read the decision set", reason_code="read_error",
            artifact_reference=reference,
        ) from exc
    observed = sha256_bytes(raw)
    if expected_sha256 is not None:
        if not _is_lower_sha256_hex(expected_sha256) or expected_sha256 != observed:
            raise ObservationTargetResolutionDecisionSetError(
                "decision-set raw-byte hash does not match the expected hash",
                reason_code="expected_hash_mismatch", artifact_reference=reference,
            )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ObservationTargetResolutionDecisionSetError(
            "the decision set is not valid UTF-8", reason_code="decode_error",
            artifact_reference=reference,
        ) from exc
    if text.startswith("\ufeff"):
        raise ObservationTargetResolutionDecisionSetError(
            "the decision set has a UTF-8 BOM", reason_code="bom",
            artifact_reference=reference,
        )
    try:
        payload = json.loads(
            text, object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except json.JSONDecodeError as exc:
        raise ObservationTargetResolutionDecisionSetError(
            "the decision set is not valid JSON", reason_code="json_error",
            artifact_reference=reference,
        ) from exc
    except _DuplicateKeyControl as exc:
        raise ObservationTargetResolutionDecisionSetError(
            "the decision set contains a duplicate JSON object key",
            reason_code="duplicate_key", artifact_reference=reference,
        ) from exc
    except _NonFiniteControl as exc:
        raise ObservationTargetResolutionDecisionSetError(
            "the decision set contains a non-JSON numeric constant",
            reason_code="non_finite", artifact_reference=reference,
        ) from exc
    if _has_non_finite(payload):
        raise ObservationTargetResolutionDecisionSetError(
            "the decision set contains a non-finite JSON number",
            reason_code="non_finite", artifact_reference=reference,
        )
    if not isinstance(payload, dict):
        raise ObservationTargetResolutionDecisionSetError(
            "the decision set top-level value must be a JSON object",
            reason_code="top_level_type", artifact_reference=reference,
        )
    try:
        model = ObservationTargetResolutionDecisionSet.model_validate(payload)
    except PydanticValidationError as exc:
        raise ObservationTargetResolutionDecisionSetError(
            "the decision set failed strict contract validation",
            reason_code="model_validation", artifact_reference=reference,
        ) from exc
    return LoadedObservationTargetResolutionDecisionSet(
        model=model, version=model.contract.contract_version,
        sha256=observed, artifact_reference=reference,
    )
