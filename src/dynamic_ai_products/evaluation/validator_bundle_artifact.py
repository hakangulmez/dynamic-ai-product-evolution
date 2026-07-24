"""Validator-bundle artifact (Slice 12F, SPEC-023 / ADR-024).

``validator_bundle_artifact@0.1.0`` is the persisted, contract-stamped
counterpart of the non-persisted ``ValidatorBundle``. It is generated as a
reconciled pair from ``validator_rule_parameters@0.1.0``: each rule's
``rule_params_hash`` equals that rule's ``complete_rule_parameter_hash`` and the
artifact's ``bundle_hash`` equals ``validator_bundle_hash`` of the reconstructed
bundle. It also records the parameter-set version and the aggregate
parameter-set hash (the v0.2 run-manifest pin).

Read-side plus pure validation and explicit persistence only. Importing this
module performs no filesystem access, hashing, environment inspection, clock
read, UUID generation, network, provider, or model call.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar

from pydantic import (
    Field,
    ValidationError as PydanticValidationError,
    model_validator,
)

from .contracts import canonical_contract_bytes, model_contract_hash
from .models import ContractStampedModel, EvaluationStrictModel, FindingSeverity, _require_non_blank
from .validator_parameters import (
    LoadedValidatorRuleParameters,
    complete_rule_parameter_hash,
    validator_rule_parameters_aggregate_hash,
)
from .validators import (
    VALIDATOR_RULE_ORDER,
    ValidatorBundle,
    ValidatorRuleConfig,
    ValidatorRuleId,
    validator_bundle_hash,
)
from ..universe.io_utils import sha256_bytes

__all__ = [
    "LoadedValidatorBundleArtifact",
    "ValidatorBundleArtifact",
    "ValidatorBundleArtifactError",
    "build_validator_bundle_artifact",
    "load_validator_bundle_artifact",
    "persist_validator_bundle_artifact",
    "validator_bundle_artifact_hash",
]

_CONTRACT_ID = "validator_bundle_artifact"
_CONTRACT_VERSION = "0.1.0"
_SNAPSHOTS_DIR = "snapshots"
_SNAPSHOT_FILENAME = "validator_bundle_artifact.json"
_SHA256_HEX = {"min_length": 64, "max_length": 64, "pattern": r"^[0-9a-f]{64}$"}


class ValidatorBundleArtifactError(Exception):
    """Sanitized validator-bundle-artifact failure with a stable code."""

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


# --- Model ----------------------------------------------------------------


class _BundleArtifactRuleEntry(EvaluationStrictModel):
    rule_id: ValidatorRuleId
    severity: FindingSeverity
    rule_params_hash: str = Field(**_SHA256_HEX)
    repairable: bool


class ValidatorBundleArtifact(ContractStampedModel):
    # Docstring intentionally omitted so the generated JSON Schema (and thus the
    # governed model-contract hash) carries no description.
    _contract_id: ClassVar[str] = _CONTRACT_ID
    _contract_version: ClassVar[str] = _CONTRACT_VERSION

    bundle_version: str
    rule_entries: tuple[_BundleArtifactRuleEntry, ...]
    parameter_set_version: str
    parameter_set_aggregate_hash: str = Field(**_SHA256_HEX)
    bundle_hash: str = Field(**_SHA256_HEX)

    @model_validator(mode="after")
    def _artifact_invariants(self) -> "ValidatorBundleArtifact":
        _require_non_blank(self.bundle_version, "bundle_version")
        _require_non_blank(self.parameter_set_version, "parameter_set_version")
        observed = tuple(entry.rule_id for entry in self.rule_entries)
        if observed != VALIDATOR_RULE_ORDER:
            raise ValueError(
                "rule_entries must be exactly the twelve rules in canonical order"
            )
        reconstructed = ValidatorBundle(
            bundle_version=self.bundle_version,
            rules=tuple(
                ValidatorRuleConfig(
                    rule_id=entry.rule_id,
                    severity=entry.severity,
                    rule_params_hash=entry.rule_params_hash,
                    repairable=entry.repairable,
                )
                for entry in self.rule_entries
            ),
        )
        if validator_bundle_hash(reconstructed) != self.bundle_hash:
            raise ValueError(
                "bundle_hash does not match validator_bundle_hash of the reconstructed bundle"
            )
        return self


class LoadedValidatorBundleArtifact(EvaluationStrictModel):
    """A validated bundle artifact plus its raw-byte binding material."""

    model: ValidatorBundleArtifact
    version: str
    sha256: str
    artifact_reference: str


# --- Reconciled build ------------------------------------------------------


def build_validator_bundle_artifact(
    parameters: LoadedValidatorRuleParameters,
    *,
    bundle_version: str,
    severities: Mapping[str, FindingSeverity],
    repairables: Mapping[str, bool],
) -> ValidatorBundleArtifact:
    """Generate the reconciled bundle artifact from loaded rule parameters.

    Each rule's ``rule_params_hash`` is set to that rule's
    ``complete_rule_parameter_hash``; ``bundle_hash`` is the
    ``validator_bundle_hash`` of the reconstructed ``ValidatorBundle``; and
    ``parameter_set_aggregate_hash`` is the aggregate parameter-set hash.
    """
    if not isinstance(parameters, LoadedValidatorRuleParameters):
        raise TypeError(
            f"parameters must be a LoadedValidatorRuleParameters, got "
            f"{type(parameters).__name__}"
        )
    entries_by_rule = {entry.rule_id: entry for entry in parameters.model.entries}
    rule_entries = []
    rules = []
    for rule_id in VALIDATOR_RULE_ORDER:
        if rule_id not in severities:
            raise ValueError(f"missing severity for rule {rule_id!r}")
        if rule_id not in repairables:
            raise ValueError(f"missing repairable flag for rule {rule_id!r}")
        params_hash = complete_rule_parameter_hash(entries_by_rule[rule_id])
        rule_entries.append(
            _BundleArtifactRuleEntry(
                rule_id=rule_id,
                severity=severities[rule_id],
                rule_params_hash=params_hash,
                repairable=repairables[rule_id],
            )
        )
        rules.append(
            ValidatorRuleConfig(
                rule_id=rule_id,
                severity=severities[rule_id],
                rule_params_hash=params_hash,
                repairable=repairables[rule_id],
            )
        )
    bundle = ValidatorBundle(bundle_version=bundle_version, rules=tuple(rules))
    aggregate = validator_rule_parameters_aggregate_hash(parameters.model)
    stamp_hash = model_contract_hash(ValidatorBundleArtifact, _CONTRACT_ID, _CONTRACT_VERSION)
    return ValidatorBundleArtifact(
        contract={
            "contract_id": _CONTRACT_ID,
            "contract_version": _CONTRACT_VERSION,
            "contract_hash": stamp_hash,
        },
        bundle_version=bundle_version,
        rule_entries=tuple(rule_entries),
        parameter_set_version=parameters.model.parameter_set_version,
        parameter_set_aggregate_hash=aggregate,
        bundle_hash=validator_bundle_hash(bundle),
    )


# --- Content hash + fail-closed revalidation ------------------------------


def _revalidate(model: ValidatorBundleArtifact) -> ValidatorBundleArtifact:
    if not isinstance(model, ValidatorBundleArtifact):
        raise TypeError(f"expected a ValidatorBundleArtifact, got {type(model).__name__}")
    try:
        payload = model.model_dump(mode="json", exclude_unset=True)
    except Exception as exc:  # noqa: BLE001 - any serialization defect fails closed
        raise ValidatorBundleArtifactError(
            "validator bundle artifact could not be serialized for revalidation",
            reason_code="model_validation",
        ) from exc
    try:
        return ValidatorBundleArtifact.model_validate(payload)
    except PydanticValidationError as exc:
        raise ValidatorBundleArtifactError(
            "validator bundle artifact failed fail-closed revalidation",
            reason_code="model_validation",
        ) from exc


def validator_bundle_artifact_hash(model: ValidatorBundleArtifact) -> str:
    """The canonical content hash over newline-free canonical model bytes."""
    validated = _revalidate(model)
    payload = validated.model_dump(mode="json", exclude_unset=True)
    return sha256_bytes(canonical_contract_bytes(payload))


def _reconcile_with_parameters(
    model: ValidatorBundleArtifact,
    rule_parameters: LoadedValidatorRuleParameters,
    *,
    reference: str | None = None,
) -> None:
    """Reject a bundle artifact that does not reconcile with the loaded parameters.

    A self-consistent recomputed ``bundle_hash`` is insufficient: the version,
    the aggregate parameter hash, and every per-rule ``rule_params_hash`` must
    equal the loaded parameter set (fail-closed).
    """
    if not isinstance(rule_parameters, LoadedValidatorRuleParameters):
        raise TypeError(
            f"rule_parameters must be a LoadedValidatorRuleParameters, got "
            f"{type(rule_parameters).__name__}"
        )
    if model.parameter_set_version != rule_parameters.model.parameter_set_version:
        raise ValidatorBundleArtifactError(
            "bundle artifact parameter_set_version does not match the loaded parameters",
            reason_code="parameter_set_version_mismatch",
            artifact_reference=reference,
        )
    if model.parameter_set_aggregate_hash != validator_rule_parameters_aggregate_hash(
        rule_parameters.model
    ):
        raise ValidatorBundleArtifactError(
            "bundle artifact parameter_set_aggregate_hash does not match the loaded parameters",
            reason_code="parameter_set_hash_mismatch",
            artifact_reference=reference,
        )
    entries_by_rule = {e.rule_id: e for e in rule_parameters.model.entries}
    for entry in model.rule_entries:
        if entry.rule_params_hash != complete_rule_parameter_hash(entries_by_rule[entry.rule_id]):
            raise ValidatorBundleArtifactError(
                "bundle artifact rule_params_hash does not equal the complete per-rule hash",
                reason_code="rule_params_hash_mismatch",
                artifact_reference=reference,
            )


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
        raise ValidatorBundleArtifactError(
            "eval_root must be an explicit str or Path evaluation root",
            reason_code="invalid_eval_root",
        )
    if isinstance(eval_root, str) and eval_root == "":
        raise ValidatorBundleArtifactError(
            "eval_root must not be an empty string; supply the evaluation root explicitly",
            reason_code="invalid_eval_root",
        )
    root = Path(eval_root)
    if root.is_symlink():
        raise ValidatorBundleArtifactError(
            "eval_root must not be a symlink", reason_code="eval_root_symlink"
        )
    if not root.exists():
        raise ValidatorBundleArtifactError(
            "evaluation root does not exist", reason_code="invalid_eval_root"
        )
    if not root.is_dir():
        raise ValidatorBundleArtifactError(
            "evaluation root is not a directory", reason_code="invalid_eval_root"
        )
    return root.resolve()


def _resolve_contained(reference: str | Path, resolved_root: Path) -> tuple[Path, str]:
    if not _is_safe_reference(reference if isinstance(reference, str) else str(reference)):
        if not isinstance(reference, (str, Path)):
            raise ValidatorBundleArtifactError(
                "reference must be an explicit str or Path", reason_code="invalid_path"
            )
        raise ValidatorBundleArtifactError(
            "reference is not a safe relative reference", reason_code="unsafe_reference"
        )
    candidate = resolved_root / Path(reference)
    if candidate.is_symlink():
        raise ValidatorBundleArtifactError(
            "artifact path is a symlink", reason_code="artifact_symlink"
        )
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValidatorBundleArtifactError(
            "artifact path resolves outside the evaluation root", reason_code="path_escape"
        )
    ref = resolved.relative_to(resolved_root).as_posix()
    if resolved.is_symlink():
        raise ValidatorBundleArtifactError(
            "artifact is a symlink", reason_code="artifact_symlink", artifact_reference=ref
        )
    if not resolved.exists():
        raise ValidatorBundleArtifactError(
            "artifact does not exist under the evaluation root",
            reason_code="artifact_missing",
            artifact_reference=ref,
        )
    if not resolved.is_file():
        raise ValidatorBundleArtifactError(
            "artifact is not a regular file",
            reason_code="artifact_not_a_file",
            artifact_reference=ref,
        )
    return resolved, ref


def _validate_run_id(eval_run_id: Any) -> str:
    if not isinstance(eval_run_id, str):
        raise ValidatorBundleArtifactError(
            f"eval_run_id must be a string, got {type(eval_run_id).__name__}",
            reason_code="invalid_eval_run_id",
        )
    if not eval_run_id or eval_run_id != eval_run_id.strip():
        raise ValidatorBundleArtifactError(
            "eval_run_id must be a non-empty string without leading or trailing whitespace",
            reason_code="invalid_eval_run_id",
        )
    if eval_run_id in (".", ".."):
        raise ValidatorBundleArtifactError(
            "eval_run_id is not a valid path component", reason_code="invalid_eval_run_id"
        )
    if "/" in eval_run_id or "\\" in eval_run_id or "\x00" in eval_run_id:
        raise ValidatorBundleArtifactError(
            "eval_run_id must be a single path component without separators or NUL",
            reason_code="invalid_eval_run_id",
        )
    if Path(eval_run_id).is_absolute() or len(Path(eval_run_id).parts) != 1:
        raise ValidatorBundleArtifactError(
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
        raise ValidatorBundleArtifactError(
            "artifact is not valid JSON", reason_code="json_error", artifact_reference=reference
        ) from exc
    except _DuplicateKeyControl as exc:
        raise ValidatorBundleArtifactError(
            "artifact contains a duplicate JSON object key",
            reason_code="duplicate_key",
            artifact_reference=reference,
        ) from exc
    except _NonFiniteControl as exc:
        raise ValidatorBundleArtifactError(
            "artifact contains a non-JSON numeric constant",
            reason_code="non_finite",
            artifact_reference=reference,
        ) from exc
    if _has_non_finite(payload):
        raise ValidatorBundleArtifactError(
            "artifact contains a non-finite JSON number",
            reason_code="non_finite",
            artifact_reference=reference,
        )
    if not isinstance(payload, dict):
        raise ValidatorBundleArtifactError(
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
        raise ValidatorBundleArtifactError(
            "failed to read the artifact", reason_code="read_error", artifact_reference=ref
        ) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidatorBundleArtifactError(
            "artifact is not valid UTF-8", reason_code="decode_error", artifact_reference=ref
        ) from exc
    return raw, text, ref


# --- Loader ---------------------------------------------------------------


def load_validator_bundle_artifact(
    path: str | Path,
    *,
    eval_root: str | Path,
    rule_parameters: LoadedValidatorRuleParameters,
    expected_sha256: str | None = None,
) -> LoadedValidatorBundleArtifact:
    """Load, hash-bind, strictly validate, and reconcile a validator-bundle artifact.

    Reconciliation is not a self-consistent recomputed ``bundle_hash`` alone: the
    loaded validator-rule-parameters input is required and the artifact is
    rejected unless its ``parameter_set_version`` and ``parameter_set_aggregate_hash``
    equal the loaded set's version and canonical aggregate hash and every rule
    entry's ``rule_params_hash`` equals the corresponding complete per-rule hash.
    """
    if not isinstance(rule_parameters, LoadedValidatorRuleParameters):
        raise TypeError(
            f"rule_parameters must be a LoadedValidatorRuleParameters, got "
            f"{type(rule_parameters).__name__}"
        )
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
            raise ValidatorBundleArtifactError(
                "validator bundle artifact raw-byte hash does not match the expected hash",
                reason_code="expected_hash_mismatch",
                artifact_reference=reference,
            )
    payload = _strict_json_object(text, reference)
    try:
        model = ValidatorBundleArtifact.model_validate(payload)
    except PydanticValidationError as exc:
        raise ValidatorBundleArtifactError(
            "validator bundle artifact failed strict contract validation",
            reason_code="model_validation",
            artifact_reference=reference,
        ) from exc
    _reconcile_with_parameters(model, rule_parameters, reference=reference)
    return LoadedValidatorBundleArtifact(
        model=model,
        version=model.bundle_version,
        sha256=observed,
        artifact_reference=reference,
    )


# --- Snapshot persistence -------------------------------------------------


def persist_validator_bundle_artifact(
    model: ValidatorBundleArtifact,
    *,
    eval_root: str | Path,
    eval_run_id: str,
    rule_parameters: LoadedValidatorRuleParameters,
) -> LoadedValidatorBundleArtifact:
    """Write the canonical bundle-artifact JSON (plus one terminal newline) write-once.

    The loaded validator-rule-parameters input is required and the artifact is
    reconciled against it (version, aggregate hash, and every per-rule hash)
    before any directory or file is created, so a self-consistent but
    parameter-mismatched artifact never reaches the write-once path.
    """
    validated = _revalidate(model)
    _reconcile_with_parameters(validated, rule_parameters)
    resolved_root = _validate_eval_root(eval_root)
    run_id = _validate_run_id(eval_run_id)
    run_dir = resolved_root / run_id
    if run_dir.is_symlink():
        raise ValidatorBundleArtifactError(
            "run directory is a symlink", reason_code="run_directory_symlink"
        )
    if not run_dir.exists():
        raise ValidatorBundleArtifactError(
            "run directory does not exist under the evaluation root",
            reason_code="run_directory_missing",
            artifact_reference=run_id,
        )
    if not run_dir.is_dir():
        raise ValidatorBundleArtifactError(
            "run directory is not a directory",
            reason_code="run_directory_not_a_directory",
            artifact_reference=run_id,
        )
    snapshots_dir = run_dir / _SNAPSHOTS_DIR
    if snapshots_dir.is_symlink():
        raise ValidatorBundleArtifactError(
            "run snapshots directory is a symlink",
            reason_code="snapshots_directory_symlink",
        )
    if snapshots_dir.exists():
        if not snapshots_dir.is_dir():
            raise ValidatorBundleArtifactError(
                "run snapshots path is not a directory",
                reason_code="snapshots_directory_not_a_directory",
            )
    else:
        try:
            snapshots_dir.mkdir(exist_ok=False)
        except OSError as exc:
            raise ValidatorBundleArtifactError(
                "failed to create the run snapshots directory",
                reason_code="write_error",
                artifact_reference=f"{run_id}/{_SNAPSHOTS_DIR}",
            ) from exc
    reference = f"{run_id}/{_SNAPSHOTS_DIR}/{_SNAPSHOT_FILENAME}"
    dest = snapshots_dir / _SNAPSHOT_FILENAME
    if dest.is_symlink() or dest.exists():
        raise ValidatorBundleArtifactError(
            "snapshot already exists; snapshots are write-once",
            reason_code="snapshot_exists",
            artifact_reference=reference,
        )
    data = canonical_contract_bytes(validated.model_dump(mode="json", exclude_unset=True)) + b"\n"
    expected = sha256_bytes(data)
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise ValidatorBundleArtifactError(
            "snapshot already exists; snapshots are write-once",
            reason_code="snapshot_exists",
            artifact_reference=reference,
        ) from exc
    except OSError as exc:
        raise ValidatorBundleArtifactError(
            "failed to create the snapshot", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ValidatorBundleArtifactError(
            "failed to write the snapshot", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        observed = sha256_bytes(dest.read_bytes())
    except OSError as exc:
        raise ValidatorBundleArtifactError(
            "failed to re-read the snapshot for verification",
            reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    if observed != expected:
        raise ValidatorBundleArtifactError(
            "persisted snapshot re-read to a different hash",
            reason_code="destination_hash_mismatch",
            artifact_reference=reference,
        )
    return LoadedValidatorBundleArtifact(
        model=validated,
        version=validated.bundle_version,
        sha256=observed,
        artifact_reference=reference,
    )
