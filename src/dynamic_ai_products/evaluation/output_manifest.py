"""Evaluation output manifest (Slice 12L, SPEC-022 / SPEC-024 / ADR-024 / ADR-025).

``evaluation_output_manifest@0.1.0`` is a strict, frozen, extra-forbid,
model-contract-hash-governed manifest that binds the **read-back persisted-byte
SHA-256** of every *pre-runner* derived output of one evaluation run, forming a
complete audit chain over the pre-runner stage. It does not duplicate the v0.2
run manifest's semantic-input pins; it binds to those inputs solely through the
immutable v0.2 run identity (``evaluation_run_manifest@0.2.0`` for the same
``eval_run_id``).

Bound derived outputs (exactly six, all pre-runner): parsed prediction content,
assertion outcomes, the validation-artifact snapshot set, validator findings,
the metric-input snapshot, and the canonical ``metric_report@0.2.0`` report.
Validator findings is the sole required output; the other five are conditional
and are omitted from the serialized JSON when their artifact was not persisted
(the invalid-run path) — never represented as explicit JSON ``null``. When an
optional artifact is omitted its canonical file must not exist, so the audit
chain can never be silently incomplete.

Deliberately excluded: the ``EvaluationResultV2`` (that gate/evaluation-result
artifact belongs to the later runner/gate layer, not the pre-runner audit
chain), the frozen historical ``metric_report@0.1.0`` (rejected by the builder),
and the pre-execution stage-metric-evidence input (already pinned by
``evaluation_run_manifest@0.2.0``).

Read-side plus pure validation and explicit persistence only. Importing this
module performs no filesystem access, hashing, environment inspection, clock
read, UUID generation, network, provider, or model call. The builder and loader
both re-read each bound artifact's persisted bytes and reject a hash mismatch;
this is an audit binding, not merely a self-validating manifest.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Callable, ClassVar

from pydantic import (
    Field,
    ValidationError as PydanticValidationError,
    model_validator,
)

from .assertions import PersistedAssertionOutcomes
from .contracts import canonical_contract_bytes, model_contract_hash
from .metric_inputs import PersistedMetricInputSnapshot
from .metrics import MetricReportV2, PersistedMetricReport
from .models import (
    ContractStampedModel,
    EvaluationRunManifestV2,
    EvaluationStrictModel,
    _reject_explicit_null,
    _require_non_blank,
)
from .observation_target_binding import (
    EXTRACTION_EVALUATION_STAGES,
    LoadedObservationTargetBinding,
    ObservationTargetBindingError,
    load_observation_target_binding,
)
from .prediction_content import (
    LoadedParsedPredictionContent,
    ParsedPredictionContentError,
    load_parsed_prediction_content,
)
from .runs import LoadedEvaluationRunManifest, load_evaluation_run_manifest_v2
from .stage_profiles import (
    LoadedStageProfileRegistry,
    StageProfileError,
    resolve_metric_applicability,
    stage_profile_registry_hash,
)
from .validation_snapshot import LoadedValidationArtifactSnapshotSet
from .validators import PersistedValidatorFindings
from ..universe.io_utils import sha256_bytes

__all__ = [
    "EvaluationOutputManifest",
    "EvaluationOutputManifestError",
    "EvaluationOutputManifestV2",
    "LoadedEvaluationOutputManifest",
    "LoadedEvaluationOutputManifestV2",
    "build_evaluation_output_manifest",
    "build_evaluation_output_manifest_v2",
    "load_evaluation_output_manifest",
    "load_evaluation_output_manifest_v2",
    "persist_evaluation_output_manifest",
    "persist_evaluation_output_manifest_v2",
]

_CONTRACT_ID = "evaluation_output_manifest"
_CONTRACT_VERSION = "0.1.0"
_CONTRACT_VERSION_V2 = "0.2.0"
_OUTPUT_DIR = "output_manifest"
_OUTPUT_FILENAME = "evaluation_output_manifest.json"
_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"

# Canonical run-relative location (subdirectory, filename) of every bound derived
# output, keyed by the manifest hash field it feeds. The evaluation result is
# deliberately absent: it is a runner/gate-layer artifact, not pre-runner.
_ARTIFACT_LOCATION: dict[str, tuple[str, str]] = {
    "validator_findings_sha256": ("findings", "validator_findings.jsonl"),
    "parsed_prediction_content_sha256": ("snapshots", "parsed_prediction_content.json"),
    "assertion_outcomes_sha256": ("assertions", "assertion_outcomes.jsonl"),
    "validation_artifact_snapshot_set_sha256":
        ("snapshots", "validation_artifact_snapshot_set.json"),
    "metric_input_snapshot_sha256": ("metric_inputs", "metric_input_snapshot.json"),
    "metric_report_v2_sha256": ("metrics", "metric_report.v2.json"),
}

_OPTIONAL_HASH_FIELDS = (
    "parsed_prediction_content_sha256",
    "assertion_outcomes_sha256",
    "validation_artifact_snapshot_set_sha256",
    "metric_input_snapshot_sha256",
    "metric_report_v2_sha256",
)

# v0.2 adds exactly one conditional binding-artifact hash. The location and
# optional-field tables are **version-scoped**: v0.1 continues to iterate only its
# own six fields, so neither its generated schema, its governed contract hash, nor
# its omitted-artifact audit rule can shift.
_BINDING_HASH_FIELD = "observation_target_binding_sha256"
_ARTIFACT_LOCATION_V2: dict[str, tuple[str, str]] = {
    **_ARTIFACT_LOCATION,
    _BINDING_HASH_FIELD: ("snapshots", "observation_target_binding.json"),
}
_OPTIONAL_HASH_FIELDS_V2 = _OPTIONAL_HASH_FIELDS + (_BINDING_HASH_FIELD,)


# --- Public errors ---------------------------------------------------------


class EvaluationOutputManifestError(Exception):
    """Sanitized output-manifest failure with a stable machine-readable code.

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


# --- Model -----------------------------------------------------------------


class EvaluationOutputManifest(ContractStampedModel):
    # Docstring intentionally omitted so the generated JSON Schema (and thus the
    # governed model-contract hash) carries no description.
    _contract_id: ClassVar[str] = _CONTRACT_ID
    _contract_version: ClassVar[str] = _CONTRACT_VERSION

    eval_run_id: str
    # Sole required derived output (present for every persisted run, incl. invalid).
    validator_findings_sha256: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    # Conditional derived outputs: omitted when the artifact was not persisted.
    parsed_prediction_content_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    assertion_outcomes_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    validation_artifact_snapshot_set_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    metric_input_snapshot_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    metric_report_v2_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )

    @model_validator(mode="before")
    @classmethod
    def _no_explicit_null_optionals(cls, data: Any) -> Any:
        return _reject_explicit_null(data, _OPTIONAL_HASH_FIELDS, "EvaluationOutputManifest")

    @model_validator(mode="after")
    def _manifest_invariants(self) -> "EvaluationOutputManifest":
        _require_non_blank(self.eval_run_id, "eval_run_id")
        return self


class LoadedEvaluationOutputManifest(EvaluationStrictModel):
    """A validated output manifest plus its raw-byte binding material."""

    model: EvaluationOutputManifest
    version: str
    sha256: str
    artifact_reference: str


# --- Content hash + fail-closed revalidation ------------------------------


def _revalidate(model: EvaluationOutputManifest) -> EvaluationOutputManifest:
    if not isinstance(model, EvaluationOutputManifest):
        raise TypeError(f"expected an EvaluationOutputManifest, got {type(model).__name__}")
    try:
        payload = model.model_dump(mode="json", exclude_unset=True)
    except Exception as exc:  # noqa: BLE001 - any serialization defect fails closed
        raise EvaluationOutputManifestError(
            "output manifest could not be serialized for revalidation",
            reason_code="model_validation",
        ) from exc
    try:
        return EvaluationOutputManifest.model_validate(payload)
    except PydanticValidationError as exc:
        raise EvaluationOutputManifestError(
            "output manifest failed fail-closed revalidation", reason_code="model_validation"
        ) from exc


def _contract_metadata() -> dict[str, str]:
    return {
        "contract_id": _CONTRACT_ID,
        "contract_version": _CONTRACT_VERSION,
        "contract_hash": model_contract_hash(
            EvaluationOutputManifest, _CONTRACT_ID, _CONTRACT_VERSION
        ),
    }


# --- Safe references / roots / strict parse -------------------------------


def _validate_run_id(eval_run_id: Any) -> str:
    if not isinstance(eval_run_id, str):
        raise EvaluationOutputManifestError(
            f"eval_run_id must be a string, got {type(eval_run_id).__name__}",
            reason_code="invalid_eval_run_id",
        )
    if not eval_run_id or eval_run_id != eval_run_id.strip():
        raise EvaluationOutputManifestError(
            "eval_run_id must be a non-empty string without leading or trailing whitespace",
            reason_code="invalid_eval_run_id",
        )
    if eval_run_id in (".", ".."):
        raise EvaluationOutputManifestError(
            "eval_run_id is not a valid path component", reason_code="invalid_eval_run_id"
        )
    if "/" in eval_run_id or "\\" in eval_run_id or "\x00" in eval_run_id:
        raise EvaluationOutputManifestError(
            "eval_run_id must be a single path component without separators or NUL",
            reason_code="invalid_eval_run_id",
        )
    if Path(eval_run_id).is_absolute() or len(Path(eval_run_id).parts) != 1:
        raise EvaluationOutputManifestError(
            "eval_run_id must be exactly one relative path component",
            reason_code="invalid_eval_run_id",
        )
    return eval_run_id


def _validate_eval_root(eval_root: str | Path) -> Path:
    if not isinstance(eval_root, (str, Path)):
        raise EvaluationOutputManifestError(
            "eval_root must be an explicit str or Path evaluation root",
            reason_code="invalid_eval_root",
        )
    if isinstance(eval_root, str) and eval_root == "":
        raise EvaluationOutputManifestError(
            "eval_root must not be an empty string; supply the evaluation root explicitly",
            reason_code="invalid_eval_root",
        )
    root = Path(eval_root)
    if root.is_symlink():
        raise EvaluationOutputManifestError(
            "eval_root must not be a symlink", reason_code="eval_root_symlink"
        )
    if not root.exists():
        raise EvaluationOutputManifestError(
            "evaluation root does not exist", reason_code="invalid_eval_root"
        )
    if not root.is_dir():
        raise EvaluationOutputManifestError(
            "evaluation root is not a directory", reason_code="invalid_eval_root"
        )
    return root.resolve()


def _canonical_reference(
    run_id: str, field: str, locations: dict[str, tuple[str, str]] = _ARTIFACT_LOCATION
) -> str:
    subdir, filename = locations[field]
    return f"{run_id}/{subdir}/{filename}"


def _resolve_run_artifact(resolved_root: Path, run_id: str, subdir: str, filename: str) -> Path:
    """Resolve a canonical run artifact path, rejecting symlinks/escape/non-file."""
    reference = f"{run_id}/{subdir}/{filename}"
    candidate = resolved_root / run_id / subdir / filename
    for part in (resolved_root / run_id, resolved_root / run_id / subdir, candidate):
        if part.is_symlink():
            raise EvaluationOutputManifestError(
                "a bound artifact path component is a symlink",
                reason_code="artifact_symlink", artifact_reference=reference,
            )
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise EvaluationOutputManifestError(
            "a bound artifact path resolves outside the evaluation root",
            reason_code="path_escape", artifact_reference=reference,
        )
    if not resolved.exists():
        raise EvaluationOutputManifestError(
            "a bound artifact does not exist under the evaluation root",
            reason_code="artifact_missing", artifact_reference=reference,
        )
    if not resolved.is_file():
        raise EvaluationOutputManifestError(
            "a bound artifact is not a regular file",
            reason_code="artifact_not_a_file", artifact_reference=reference,
        )
    return resolved


def _observed_artifact_hash(
    resolved_root: Path, run_id: str, field: str,
    locations: dict[str, tuple[str, str]] = _ARTIFACT_LOCATION,
) -> str:
    subdir, filename = locations[field]
    resolved = _resolve_run_artifact(resolved_root, run_id, subdir, filename)
    reference = f"{run_id}/{subdir}/{filename}"
    try:
        return sha256_bytes(resolved.read_bytes())
    except OSError as exc:
        raise EvaluationOutputManifestError(
            "failed to read a bound artifact", reason_code="read_error",
            artifact_reference=reference,
        ) from exc


def _reject_if_artifact_present(
    resolved_root: Path, run_id: str, field: str,
    locations: dict[str, tuple[str, str]] = _ARTIFACT_LOCATION,
) -> None:
    """Reject an optional derived artifact that exists on disk but is omitted.

    A canonical artifact file that is present (or a symlink) while its hash field
    is absent from the manifest means the audit chain is silently incomplete.
    """
    subdir, filename = locations[field]
    reference = f"{run_id}/{subdir}/{filename}"
    candidate = resolved_root / run_id / subdir / filename
    if candidate.is_symlink() or candidate.exists():
        raise EvaluationOutputManifestError(
            "an optional derived artifact exists but is omitted from the output manifest",
            reason_code="unexpected_artifact", artifact_reference=reference,
        )


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
            text, object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except json.JSONDecodeError as exc:
        raise EvaluationOutputManifestError(
            "artifact is not valid JSON", reason_code="json_error", artifact_reference=reference
        ) from exc
    except _DuplicateKeyControl as exc:
        raise EvaluationOutputManifestError(
            "artifact contains a duplicate JSON object key",
            reason_code="duplicate_key", artifact_reference=reference,
        ) from exc
    except _NonFiniteControl as exc:
        raise EvaluationOutputManifestError(
            "artifact contains a non-JSON numeric constant",
            reason_code="non_finite", artifact_reference=reference,
        ) from exc
    if _has_non_finite(payload):
        raise EvaluationOutputManifestError(
            "artifact contains a non-finite JSON number",
            reason_code="non_finite", artifact_reference=reference,
        )
    if not isinstance(payload, dict):
        raise EvaluationOutputManifestError(
            "artifact top-level value must be a JSON object",
            reason_code="top_level_type", artifact_reference=reference,
        )
    return payload


# --- Builder ---------------------------------------------------------------


def build_evaluation_output_manifest(
    *,
    eval_root: str | Path,
    eval_run_id: str,
    validator_findings: PersistedValidatorFindings,
    parsed_prediction_content: LoadedParsedPredictionContent | None = None,
    assertion_outcomes: PersistedAssertionOutcomes | None = None,
    validation_artifact_snapshot_set: LoadedValidationArtifactSnapshotSet | None = None,
    metric_input_snapshot: PersistedMetricInputSnapshot | None = None,
    metric_report: PersistedMetricReport | None = None,
) -> EvaluationOutputManifest:
    """Build an ``evaluation_output_manifest@0.1.0`` by re-reading each supplied
    pre-runner derived artifact's persisted bytes and binding the observed
    SHA-256.

    For each supplied wrapper the builder requires the exact wrapper type, its
    exact canonical ``artifact_reference``, a matching ``eval_run_id`` (on the
    wrapper or its wrapped model where that identity exists), and equality of the
    declared and re-read observed SHA-256. The observed hash — never the
    unverified caller value — is placed in the model. Validator findings is the
    sole required output. Any optional output that is omitted must not exist on
    disk, so the audit chain is never silently incomplete. The metric report must
    be ``metric_report@0.2.0``; a v0.1 report is rejected. Run identity is bound
    solely through ``evaluation_run_manifest@0.2.0`` for ``eval_run_id``.
    """
    resolved_root = _validate_eval_root(eval_root)
    run_id = _validate_run_id(eval_run_id)
    # Bind to the immutable v0.2 run identity (loads and validates the manifest).
    manifest = load_evaluation_run_manifest_v2(run_id, eval_root=resolved_root).manifest
    if manifest.eval_run_id != run_id:
        raise EvaluationOutputManifestError(
            "run manifest eval_run_id does not match the requested run",
            reason_code="run_binding",
        )

    fields: dict[str, str] = {"eval_run_id": run_id}

    def _bind(
        field: str, wrapper: Any, expected_type: type,
        *, run_id_of: Callable[[Any], str | None],
    ) -> None:
        if not isinstance(wrapper, expected_type):
            raise EvaluationOutputManifestError(
                f"{field} wrapper must be a {expected_type.__name__}",
                reason_code="wrapper_type",
            )
        canonical_ref = _canonical_reference(run_id, field)
        if getattr(wrapper, "artifact_reference") != canonical_ref:
            raise EvaluationOutputManifestError(
                "a supplied artifact wrapper does not carry its canonical reference",
                reason_code="wrapper_reference", artifact_reference=canonical_ref,
            )
        bound_run_id = run_id_of(wrapper)
        if bound_run_id is not None and bound_run_id != run_id:
            raise EvaluationOutputManifestError(
                "a supplied artifact wrapper binds a different eval_run_id",
                reason_code="wrapper_run_binding",
            )
        declared = getattr(wrapper, "sha256")
        observed = _observed_artifact_hash(resolved_root, run_id, field)
        if declared != observed:
            raise EvaluationOutputManifestError(
                "a supplied wrapper SHA-256 does not match the persisted artifact bytes",
                reason_code="artifact_hash_mismatch", artifact_reference=canonical_ref,
            )
        fields[field] = observed

    # Required output.
    _bind("validator_findings_sha256", validator_findings, PersistedValidatorFindings,
          run_id_of=lambda w: w.eval_run_id)

    # Conditional outputs: bound only when supplied.
    if parsed_prediction_content is not None:
        # Parsed prediction content carries no run identity on the wrapper or the
        # wrapped model; bind through location and hash only.
        _bind("parsed_prediction_content_sha256", parsed_prediction_content,
              LoadedParsedPredictionContent, run_id_of=lambda w: None)
    if assertion_outcomes is not None:
        _bind("assertion_outcomes_sha256", assertion_outcomes, PersistedAssertionOutcomes,
              run_id_of=lambda w: w.eval_run_id)
    if validation_artifact_snapshot_set is not None:
        _bind("validation_artifact_snapshot_set_sha256", validation_artifact_snapshot_set,
              LoadedValidationArtifactSnapshotSet, run_id_of=lambda w: w.model.eval_run_id)
    if metric_input_snapshot is not None:
        _bind("metric_input_snapshot_sha256", metric_input_snapshot,
              PersistedMetricInputSnapshot, run_id_of=lambda w: w.model.eval_run_id)
    if metric_report is not None:
        if not isinstance(metric_report, PersistedMetricReport):
            raise EvaluationOutputManifestError(
                "metric_report wrapper must be a PersistedMetricReport",
                reason_code="wrapper_type")
        if not isinstance(metric_report.report, MetricReportV2):
            raise EvaluationOutputManifestError(
                "the output chain binds only the canonical metric_report@0.2.0",
                reason_code="metric_report_version")
        _bind("metric_report_v2_sha256", metric_report, PersistedMetricReport,
              run_id_of=lambda w: w.eval_run_id)

    # An omitted optional artifact must not exist: no silently incomplete chain.
    for field in _OPTIONAL_HASH_FIELDS:
        if field not in fields:
            _reject_if_artifact_present(resolved_root, run_id, field)

    return EvaluationOutputManifest.model_validate({"contract": _contract_metadata(), **fields})


# --- Persistence -----------------------------------------------------------


def persist_evaluation_output_manifest(
    model: EvaluationOutputManifest, *, eval_root: str | Path, eval_run_id: str
) -> LoadedEvaluationOutputManifest:
    """Write the canonical output manifest (plus one terminal newline) write-once.

    Destination:
    ``<eval_root>/<eval_run_id>/output_manifest/evaluation_output_manifest.json``.
    Binds run identity through ``evaluation_run_manifest@0.2.0``; it does not
    duplicate run-manifest semantic pins.
    """
    validated = _revalidate(model)
    run_id = _validate_run_id(eval_run_id)
    if validated.eval_run_id != run_id:
        raise EvaluationOutputManifestError(
            "the model's eval_run_id does not equal the explicit persistence eval_run_id",
            reason_code="persist_eval_run_id_mismatch",
        )
    resolved_root = _validate_eval_root(eval_root)
    # Bind to the immutable v0.2 run identity before writing.
    run_manifest = load_evaluation_run_manifest_v2(run_id, eval_root=resolved_root).manifest
    if run_manifest.eval_run_id != run_id:
        raise EvaluationOutputManifestError(
            "run manifest eval_run_id does not match the requested run",
            reason_code="run_binding",
        )
    run_dir = resolved_root / run_id
    if run_dir.is_symlink():
        raise EvaluationOutputManifestError(
            "run directory is a symlink", reason_code="run_directory_symlink"
        )
    if not run_dir.exists():
        raise EvaluationOutputManifestError(
            "run directory does not exist under the evaluation root",
            reason_code="run_directory_missing", artifact_reference=run_id,
        )
    if not run_dir.is_dir():
        raise EvaluationOutputManifestError(
            "run directory is not a directory",
            reason_code="run_directory_not_a_directory", artifact_reference=run_id,
        )
    output_dir = run_dir / _OUTPUT_DIR
    if output_dir.is_symlink():
        raise EvaluationOutputManifestError(
            "run output-manifest directory is a symlink",
            reason_code="output_directory_symlink",
        )
    if output_dir.exists():
        if not output_dir.is_dir():
            raise EvaluationOutputManifestError(
                "run output-manifest path is not a directory",
                reason_code="output_directory_not_a_directory",
            )
    else:
        try:
            output_dir.mkdir(exist_ok=False)
        except OSError as exc:
            raise EvaluationOutputManifestError(
                "failed to create the run output-manifest directory",
                reason_code="write_error", artifact_reference=f"{run_id}/{_OUTPUT_DIR}",
            ) from exc
    reference = f"{run_id}/{_OUTPUT_DIR}/{_OUTPUT_FILENAME}"
    dest = output_dir / _OUTPUT_FILENAME
    if dest.is_symlink() or dest.exists():
        raise EvaluationOutputManifestError(
            "output manifest already exists; artifacts are write-once",
            reason_code="artifact_exists", artifact_reference=reference,
        )
    data = canonical_contract_bytes(validated.model_dump(mode="json", exclude_unset=True)) + b"\n"
    expected = sha256_bytes(data)
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise EvaluationOutputManifestError(
            "output manifest already exists; artifacts are write-once",
            reason_code="artifact_exists", artifact_reference=reference,
        ) from exc
    except OSError as exc:
        raise EvaluationOutputManifestError(
            "failed to create the output manifest", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise EvaluationOutputManifestError(
            "failed to write the output manifest", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        observed = sha256_bytes(dest.read_bytes())
    except OSError as exc:
        raise EvaluationOutputManifestError(
            "failed to re-read the output manifest for verification",
            reason_code="write_error", artifact_reference=reference,
        ) from exc
    if observed != expected:
        raise EvaluationOutputManifestError(
            "persisted output manifest re-read to a different hash",
            reason_code="destination_hash_mismatch", artifact_reference=reference,
        )
    return LoadedEvaluationOutputManifest(
        model=validated, version=validated.contract.contract_version,
        sha256=observed, artifact_reference=reference,
    )


# --- Loader ---------------------------------------------------------------


def load_evaluation_output_manifest(
    eval_run_id: str, *, eval_root: str | Path, expected_sha256: str | None = None
) -> LoadedEvaluationOutputManifest:
    """Load an output manifest and re-verify the audit chain.

    Applies the strict-JSON / symlink / path / expected-hash protections, binds
    the run identity through ``evaluation_run_manifest@0.2.0``, then re-reads
    every present bound artifact at its canonical location and rejects a hash
    mismatch, and finally rejects any optional artifact that exists on disk but
    is omitted from the manifest. This is an audit binding, not merely a
    self-validating manifest.
    """
    resolved_root = _validate_eval_root(eval_root)
    run_id = _validate_run_id(eval_run_id)
    reference = f"{run_id}/{_OUTPUT_DIR}/{_OUTPUT_FILENAME}"
    run_dir = resolved_root / run_id
    output_dir = run_dir / _OUTPUT_DIR
    dest = output_dir / _OUTPUT_FILENAME
    if run_dir.is_symlink() or output_dir.is_symlink() or dest.is_symlink():
        raise EvaluationOutputManifestError(
            "output manifest or a parent is a symlink",
            reason_code="artifact_symlink", artifact_reference=reference,
        )
    resolved = dest.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise EvaluationOutputManifestError(
            "output manifest resolves outside the evaluation root",
            reason_code="path_escape", artifact_reference=reference,
        )
    if not dest.exists():
        raise EvaluationOutputManifestError(
            "output manifest does not exist under the evaluation root",
            reason_code="artifact_missing", artifact_reference=reference,
        )
    if not dest.is_file():
        raise EvaluationOutputManifestError(
            "output manifest is not a regular file",
            reason_code="artifact_not_a_file", artifact_reference=reference,
        )
    try:
        raw = dest.read_bytes()
    except OSError as exc:
        raise EvaluationOutputManifestError(
            "failed to read the output manifest", reason_code="read_error",
            artifact_reference=reference,
        ) from exc
    observed = sha256_bytes(raw)
    if expected_sha256 is not None:
        valid = (
            isinstance(expected_sha256, str) and len(expected_sha256) == 64
            and all(c in "0123456789abcdef" for c in expected_sha256)
        )
        if not valid or expected_sha256 != observed:
            raise EvaluationOutputManifestError(
                "output manifest raw-byte hash does not match the expected hash",
                reason_code="expected_hash_mismatch", artifact_reference=reference,
            )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvaluationOutputManifestError(
            "output manifest is not valid UTF-8", reason_code="decode_error",
            artifact_reference=reference,
        ) from exc
    if text.startswith("\ufeff"):
        raise EvaluationOutputManifestError(
            "output manifest has a UTF-8 BOM", reason_code="bom", artifact_reference=reference
        )
    payload = _strict_json_object(text, reference)
    # Strict single-version reader: a v0.2 document at this same canonical path is
    # rejected by declared version, never coerced or partially validated.
    declared = _payload_contract_version(payload)
    if declared is not None and declared != _CONTRACT_VERSION:
        raise EvaluationOutputManifestError(
            "output manifest is not an evaluation_output_manifest@0.1.0 document",
            reason_code="unsupported_contract_version", artifact_reference=reference,
        )
    try:
        model = EvaluationOutputManifest.model_validate(payload)
    except PydanticValidationError as exc:
        raise EvaluationOutputManifestError(
            "output manifest failed strict contract validation",
            reason_code="model_validation", artifact_reference=reference,
        ) from exc
    # Run-identity binding.
    run_manifest = load_evaluation_run_manifest_v2(run_id, eval_root=resolved_root).manifest
    if model.eval_run_id != run_manifest.eval_run_id or model.eval_run_id != run_id:
        raise EvaluationOutputManifestError(
            "output manifest eval_run_id does not bind to the run",
            reason_code="run_binding", artifact_reference=reference,
        )
    # Audit re-verification: every present bound artifact must still hash to its
    # recorded value; every omitted optional artifact must not exist on disk.
    dumped = model.model_dump(mode="json", exclude_unset=True)
    for field in _ARTIFACT_LOCATION:
        recorded = dumped.get(field)
        if recorded is None:
            _reject_if_artifact_present(resolved_root, run_id, field)
            continue
        if _observed_artifact_hash(resolved_root, run_id, field) != recorded:
            raise EvaluationOutputManifestError(
                "a bound artifact no longer matches its recorded read-back hash",
                reason_code="artifact_hash_mismatch",
                artifact_reference=_canonical_reference(run_id, field),
            )
    return LoadedEvaluationOutputManifest(
        model=model, version=model.contract.contract_version,
        sha256=observed, artifact_reference=reference,
    )


# =========================================================================
# evaluation_output_manifest@0.2.0
# =========================================================================
#
# v0.2 is a strict superset of v0.1: the six v0.1 hash fields are retained
# verbatim, and two derived fields are added — the reverse-resolved
# ``derived_evaluation_stage`` and the conditional seventh
# ``observation_target_binding_sha256``. It occupies the SAME single canonical
# terminal-manifest path, so one run can never hold two terminal manifests;
# version selection is a strict declared-contract-version peek and each public
# reader accepts only its own version.


def _payload_contract_version(payload: dict[str, Any]) -> str | None:
    """The declared ``contract.contract_version`` string, or None if absent/malformed."""
    contract = payload.get("contract")
    if isinstance(contract, dict):
        version = contract.get("contract_version")
        if isinstance(version, str):
            return version
    return None


class EvaluationOutputManifestV2(ContractStampedModel):
    # Docstring intentionally omitted so the generated JSON Schema (and thus the
    # governed model-contract hash) carries no description.
    _contract_id: ClassVar[str] = _CONTRACT_ID
    _contract_version: ClassVar[str] = _CONTRACT_VERSION_V2

    eval_run_id: str
    # Reverse-resolved from the v0.2 run manifest's selected stage-profile entry
    # hash; never caller-supplied (no builder parameter exists).
    derived_evaluation_stage: str
    # Sole required derived output (present for every persisted run, incl. invalid).
    validator_findings_sha256: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    # Conditional derived outputs: omitted when the artifact was not persisted.
    parsed_prediction_content_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    observation_target_binding_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    assertion_outcomes_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    validation_artifact_snapshot_set_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    metric_input_snapshot_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    metric_report_v2_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )

    @model_validator(mode="before")
    @classmethod
    def _no_explicit_null_optionals(cls, data: Any) -> Any:
        return _reject_explicit_null(
            data, _OPTIONAL_HASH_FIELDS_V2, "EvaluationOutputManifestV2"
        )

    @model_validator(mode="after")
    def _manifest_invariants(self) -> "EvaluationOutputManifestV2":
        _require_non_blank(self.eval_run_id, "eval_run_id")
        _require_non_blank(self.derived_evaluation_stage, "derived_evaluation_stage")
        extraction = self.derived_evaluation_stage in EXTRACTION_EVALUATION_STAGES
        if not extraction and self.observation_target_binding_sha256 is not None:
            raise ValueError(
                "binding_not_permitted_for_stage: a non-extraction stage must omit "
                "observation_target_binding_sha256"
            )
        # Extraction assertion outcomes are only interpretable through the binding
        # that maps raw observation IDs onto canonical target references.
        if (
            extraction
            and self.assertion_outcomes_sha256 is not None
            and self.observation_target_binding_sha256 is None
        ):
            raise ValueError(
                "extraction_outcomes_require_binding: supplied extraction assertion "
                "outcomes require observation_target_binding_sha256"
            )
        # A binding is meaningless without the parsed content it is hash-bound to.
        if (
            self.observation_target_binding_sha256 is not None
            and self.parsed_prediction_content_sha256 is None
        ):
            raise ValueError(
                "binding_without_parsed_content: a bound binding requires parsed content"
            )
        return self


class LoadedEvaluationOutputManifestV2(EvaluationStrictModel):
    """A validated v0.2 output manifest plus its raw-byte binding material."""

    model: EvaluationOutputManifestV2
    version: str
    sha256: str
    artifact_reference: str


def _revalidate_v2(model: EvaluationOutputManifestV2) -> EvaluationOutputManifestV2:
    if not isinstance(model, EvaluationOutputManifestV2):
        raise TypeError(f"expected an EvaluationOutputManifestV2, got {type(model).__name__}")
    try:
        payload = model.model_dump(mode="json", exclude_unset=True)
    except Exception as exc:  # noqa: BLE001 - any serialization defect fails closed
        raise EvaluationOutputManifestError(
            "output manifest could not be serialized for revalidation",
            reason_code="model_validation",
        ) from exc
    try:
        return EvaluationOutputManifestV2.model_validate(payload)
    except PydanticValidationError as exc:
        raise EvaluationOutputManifestError(
            "output manifest failed fail-closed revalidation", reason_code="model_validation"
        ) from exc


def _contract_metadata_v2() -> dict[str, str]:
    return {
        "contract_id": _CONTRACT_ID,
        "contract_version": _CONTRACT_VERSION_V2,
        "contract_hash": model_contract_hash(
            EvaluationOutputManifestV2, _CONTRACT_ID, _CONTRACT_VERSION_V2
        ),
    }


def _verified_v2_manifest(
    loaded_run: LoadedEvaluationRunManifest | None, run_id: str, resolved_root: Path
) -> EvaluationRunManifestV2:
    """Return the verified inner v0.2 run manifest, loading it when not supplied.

    ``load_evaluation_run_manifest_v2`` returns ``LoadedEvaluationRunManifest``
    whose ``manifest`` field is the closed v0.1|v0.2 union, so the concrete v0.2
    class is required explicitly rather than assumed.
    """
    if loaded_run is None:
        loaded_run = load_evaluation_run_manifest_v2(run_id, eval_root=resolved_root)
    if not isinstance(loaded_run, LoadedEvaluationRunManifest):
        raise TypeError(
            "loaded_run must be a LoadedEvaluationRunManifest, got "
            f"{type(loaded_run).__name__}"
        )
    manifest = loaded_run.manifest
    if not isinstance(manifest, EvaluationRunManifestV2):
        raise EvaluationOutputManifestError(
            "the supplied run wrapper does not carry an evaluation_run_manifest@0.2.0",
            reason_code="run_manifest_not_v2",
        )
    if manifest.eval_run_id != run_id:
        raise EvaluationOutputManifestError(
            "run manifest eval_run_id does not match the requested run",
            reason_code="run_binding",
        )
    return manifest


def _derive_evaluation_stage(
    manifest: EvaluationRunManifestV2, stage_profile_registry: LoadedStageProfileRegistry
) -> str:
    """Reverse-resolve the run's evaluation stage from its selected-entry hash.

    ``evaluation_run_manifest@0.2.0`` deliberately does not persist
    ``evaluation_stage``; it pins the selected stage-profile entry hash. The stage
    is therefore recovered by matching that pin against the supplied registry and
    requiring **exactly one** match — zero and multiple are distinct fail-closed
    outcomes, and no structural-uniqueness argument is relied upon.
    """
    if not isinstance(stage_profile_registry, LoadedStageProfileRegistry):
        raise TypeError(
            "stage_profile_registry must be a LoadedStageProfileRegistry, got "
            f"{type(stage_profile_registry).__name__}"
        )
    registry = stage_profile_registry.registry
    if registry.registry_version != manifest.stage_profile_registry_version:
        raise EvaluationOutputManifestError(
            "the supplied stage-profile registry version does not equal the run pin",
            reason_code="stage_profile_registry_version_mismatch",
        )
    try:
        content_hash = stage_profile_registry_hash(registry)
    except StageProfileError as exc:
        raise EvaluationOutputManifestError(
            "the supplied stage-profile registry failed fail-closed validation",
            reason_code="stage_profile_registry_invalid",
        ) from exc
    if content_hash != manifest.stage_profile_registry_hash:
        raise EvaluationOutputManifestError(
            "the supplied stage-profile registry content hash does not equal the run pin",
            reason_code="stage_profile_registry_hash_mismatch",
        )
    pin = manifest.selected_stage_profile_entry_hash
    matches = []
    for entry in registry.entries:
        try:
            observed = entry.entry_hash
        except StageProfileError as exc:
            raise EvaluationOutputManifestError(
                "a stage-profile entry failed fail-closed validation",
                reason_code="stage_profile_registry_invalid",
            ) from exc
        if observed == pin:
            matches.append(entry)
    if not matches:
        raise EvaluationOutputManifestError(
            "the run's selected stage-profile entry hash matches no registry entry",
            reason_code="selected_stage_profile_entry_unresolved",
        )
    if len(matches) > 1:
        raise EvaluationOutputManifestError(
            "the run's selected stage-profile entry hash matches more than one registry entry",
            reason_code="selected_stage_profile_entry_ambiguous",
        )
    entry = matches[0]
    # Forward/reverse agreement: the recovered stage must resolve, through the
    # governed resolver, back to the very same selected entry.
    try:
        forward = resolve_metric_applicability(registry, entry.evaluation_stage)
        forward_hash = forward.entry_hash
    except StageProfileError as exc:
        raise EvaluationOutputManifestError(
            "the recovered evaluation stage does not forward-resolve to a supported entry",
            reason_code="selected_stage_profile_entry_unsupported",
        ) from exc
    if forward_hash != pin:
        raise EvaluationOutputManifestError(
            "the recovered evaluation stage forward-resolves to a different entry",
            reason_code="selected_stage_profile_entry_unsupported",
        )
    return entry.evaluation_stage


def _require_binding_raw_artifact_coherence(
    binding_model: Any, parsed: LoadedParsedPredictionContent
) -> None:
    """Fail closed unless the binding and parsed content share one raw artifact."""
    content = parsed.content
    if (
        binding_model.raw_artifact_reference != content.raw_artifact_reference
        or binding_model.raw_artifact_sha256 != content.raw_artifact_sha256
    ):
        raise EvaluationOutputManifestError(
            "the binding raw-artifact identity does not equal the parsed content's",
            reason_code="binding_raw_artifact_mismatch",
        )


def build_evaluation_output_manifest_v2(
    *,
    eval_root: str | Path,
    eval_run_id: str,
    stage_profile_registry: LoadedStageProfileRegistry,
    validator_findings: PersistedValidatorFindings,
    loaded_run: LoadedEvaluationRunManifest | None = None,
    parsed_prediction_content: LoadedParsedPredictionContent | None = None,
    observation_target_binding: LoadedObservationTargetBinding | None = None,
    assertion_outcomes: PersistedAssertionOutcomes | None = None,
    validation_artifact_snapshot_set: LoadedValidationArtifactSnapshotSet | None = None,
    metric_input_snapshot: PersistedMetricInputSnapshot | None = None,
    metric_report: PersistedMetricReport | None = None,
) -> EvaluationOutputManifestV2:
    """Build an ``evaluation_output_manifest@0.2.0`` by re-reading persisted bytes.

    Identical binding discipline to v0.1 (exact wrapper type, canonical
    ``artifact_reference``, run-identity agreement, declared-vs-re-read hash
    equality, omitted-optional-must-not-exist), plus: the evaluation stage is
    **derived** by reverse-resolving the v0.2 run manifest's selected
    stage-profile entry hash against ``stage_profile_registry`` — there is no
    stage parameter, so a caller-supplied stage cannot be trusted or even
    expressed. The seventh binding hash is permitted only for a derived
    extraction stage, and supplied extraction assertion outcomes require it.
    """
    resolved_root = _validate_eval_root(eval_root)
    run_id = _validate_run_id(eval_run_id)
    manifest = _verified_v2_manifest(loaded_run, run_id, resolved_root)
    derived_stage = _derive_evaluation_stage(manifest, stage_profile_registry)
    extraction = derived_stage in EXTRACTION_EVALUATION_STAGES

    if observation_target_binding is not None and not extraction:
        raise EvaluationOutputManifestError(
            "a non-extraction run must not bind an observation-target binding",
            reason_code="binding_not_permitted_for_stage",
        )
    if (
        extraction
        and assertion_outcomes is not None
        and observation_target_binding is None
    ):
        raise EvaluationOutputManifestError(
            "supplied extraction assertion outcomes require the observation-target binding",
            reason_code="extraction_outcomes_require_binding",
        )
    if observation_target_binding is not None and parsed_prediction_content is None:
        raise EvaluationOutputManifestError(
            "a bound observation-target binding requires the parsed prediction content",
            reason_code="binding_without_parsed_content",
        )

    fields: dict[str, str] = {
        "eval_run_id": run_id, "derived_evaluation_stage": derived_stage,
    }

    def _bind(
        field: str, wrapper: Any, expected_type: type,
        *, run_id_of: Callable[[Any], str | None],
    ) -> None:
        if not isinstance(wrapper, expected_type):
            raise EvaluationOutputManifestError(
                f"{field} wrapper must be a {expected_type.__name__}",
                reason_code="wrapper_type",
            )
        canonical_ref = _canonical_reference(run_id, field, _ARTIFACT_LOCATION_V2)
        if getattr(wrapper, "artifact_reference") != canonical_ref:
            raise EvaluationOutputManifestError(
                "a supplied artifact wrapper does not carry its canonical reference",
                reason_code="wrapper_reference", artifact_reference=canonical_ref,
            )
        bound_run_id = run_id_of(wrapper)
        if bound_run_id is not None and bound_run_id != run_id:
            raise EvaluationOutputManifestError(
                "a supplied artifact wrapper binds a different eval_run_id",
                reason_code="wrapper_run_binding",
            )
        declared = getattr(wrapper, "sha256")
        observed = _observed_artifact_hash(
            resolved_root, run_id, field, _ARTIFACT_LOCATION_V2
        )
        if declared != observed:
            raise EvaluationOutputManifestError(
                "a supplied wrapper SHA-256 does not match the persisted artifact bytes",
                reason_code="artifact_hash_mismatch", artifact_reference=canonical_ref,
            )
        fields[field] = observed

    # Required output.
    _bind("validator_findings_sha256", validator_findings, PersistedValidatorFindings,
          run_id_of=lambda w: w.eval_run_id)

    # Conditional outputs: bound only when supplied.
    if parsed_prediction_content is not None:
        _bind("parsed_prediction_content_sha256", parsed_prediction_content,
              LoadedParsedPredictionContent, run_id_of=lambda w: None)
    if observation_target_binding is not None:
        _bind(_BINDING_HASH_FIELD, observation_target_binding,
              LoadedObservationTargetBinding, run_id_of=lambda w: w.model.eval_run_id)
        bmodel = observation_target_binding.model
        if bmodel.stage != derived_stage:
            raise EvaluationOutputManifestError(
                "the binding stage does not equal the derived evaluation stage",
                reason_code="binding_stage_mismatch",
            )
        if (
            bmodel.parsed_prediction_content_sha256
            != fields["parsed_prediction_content_sha256"]
        ):
            raise EvaluationOutputManifestError(
                "the binding is not pinned to this run's parsed prediction content",
                reason_code="binding_parsed_content_mismatch",
            )
        # Raw-artifact coherence: the binding must be pinned to the SAME raw
        # prediction artifact the parsed content was derived from. A binding whose
        # parsed-content hash matches but whose raw provenance points elsewhere
        # would silently break the audit chain back to the model output.
        _require_binding_raw_artifact_coherence(bmodel, parsed_prediction_content)
    if assertion_outcomes is not None:
        _bind("assertion_outcomes_sha256", assertion_outcomes, PersistedAssertionOutcomes,
              run_id_of=lambda w: w.eval_run_id)
    if validation_artifact_snapshot_set is not None:
        _bind("validation_artifact_snapshot_set_sha256", validation_artifact_snapshot_set,
              LoadedValidationArtifactSnapshotSet, run_id_of=lambda w: w.model.eval_run_id)
    if metric_input_snapshot is not None:
        _bind("metric_input_snapshot_sha256", metric_input_snapshot,
              PersistedMetricInputSnapshot, run_id_of=lambda w: w.model.eval_run_id)
    if metric_report is not None:
        if not isinstance(metric_report, PersistedMetricReport):
            raise EvaluationOutputManifestError(
                "metric_report wrapper must be a PersistedMetricReport",
                reason_code="wrapper_type")
        if not isinstance(metric_report.report, MetricReportV2):
            raise EvaluationOutputManifestError(
                "the output chain binds only the canonical metric_report@0.2.0",
                reason_code="metric_report_version")
        _bind("metric_report_v2_sha256", metric_report, PersistedMetricReport,
              run_id_of=lambda w: w.eval_run_id)

    # An omitted optional artifact must not exist: no silently incomplete chain.
    for field in _OPTIONAL_HASH_FIELDS_V2:
        if field not in fields:
            _reject_if_artifact_present(resolved_root, run_id, field, _ARTIFACT_LOCATION_V2)

    try:
        return EvaluationOutputManifestV2.model_validate(
            {"contract": _contract_metadata_v2(), **fields}
        )
    except PydanticValidationError as exc:
        raise EvaluationOutputManifestError(
            "the assembled v0.2 output manifest failed contract validation",
            reason_code="model_validation",
        ) from exc


def persist_evaluation_output_manifest_v2(
    model: EvaluationOutputManifestV2, *, eval_root: str | Path, eval_run_id: str
) -> LoadedEvaluationOutputManifestV2:
    """Write the canonical v0.2 output manifest (plus one terminal newline) write-once.

    Destination is the single terminal-manifest path
    ``<eval_root>/<eval_run_id>/output_manifest/evaluation_output_manifest.json``.
    A run that already holds a terminal manifest of *either* version collides with
    the preserved ``artifact_exists`` reason code.
    """
    validated = _revalidate_v2(model)
    run_id = _validate_run_id(eval_run_id)
    if validated.eval_run_id != run_id:
        raise EvaluationOutputManifestError(
            "the model's eval_run_id does not equal the explicit persistence eval_run_id",
            reason_code="persist_eval_run_id_mismatch",
        )
    resolved_root = _validate_eval_root(eval_root)
    _verified_v2_manifest(None, run_id, resolved_root)
    run_dir = resolved_root / run_id
    if run_dir.is_symlink():
        raise EvaluationOutputManifestError(
            "run directory is a symlink", reason_code="run_directory_symlink"
        )
    if not run_dir.exists():
        raise EvaluationOutputManifestError(
            "run directory does not exist under the evaluation root",
            reason_code="run_directory_missing", artifact_reference=run_id,
        )
    if not run_dir.is_dir():
        raise EvaluationOutputManifestError(
            "run directory is not a directory",
            reason_code="run_directory_not_a_directory", artifact_reference=run_id,
        )
    output_dir = run_dir / _OUTPUT_DIR
    if output_dir.is_symlink():
        raise EvaluationOutputManifestError(
            "run output-manifest directory is a symlink",
            reason_code="output_directory_symlink",
        )
    if output_dir.exists():
        if not output_dir.is_dir():
            raise EvaluationOutputManifestError(
                "run output-manifest path is not a directory",
                reason_code="output_directory_not_a_directory",
            )
    else:
        try:
            output_dir.mkdir(exist_ok=False)
        except OSError as exc:
            raise EvaluationOutputManifestError(
                "failed to create the run output-manifest directory",
                reason_code="write_error", artifact_reference=f"{run_id}/{_OUTPUT_DIR}",
            ) from exc
    reference = f"{run_id}/{_OUTPUT_DIR}/{_OUTPUT_FILENAME}"
    dest = output_dir / _OUTPUT_FILENAME
    if dest.is_symlink() or dest.exists():
        raise EvaluationOutputManifestError(
            "output manifest already exists; artifacts are write-once",
            reason_code="artifact_exists", artifact_reference=reference,
        )
    data = canonical_contract_bytes(validated.model_dump(mode="json", exclude_unset=True)) + b"\n"
    expected = sha256_bytes(data)
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise EvaluationOutputManifestError(
            "output manifest already exists; artifacts are write-once",
            reason_code="artifact_exists", artifact_reference=reference,
        ) from exc
    except OSError as exc:
        raise EvaluationOutputManifestError(
            "failed to create the output manifest", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise EvaluationOutputManifestError(
            "failed to write the output manifest", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        observed = sha256_bytes(dest.read_bytes())
    except OSError as exc:
        raise EvaluationOutputManifestError(
            "failed to re-read the output manifest for verification",
            reason_code="write_error", artifact_reference=reference,
        ) from exc
    if observed != expected:
        raise EvaluationOutputManifestError(
            "persisted output manifest re-read to a different hash",
            reason_code="destination_hash_mismatch", artifact_reference=reference,
        )
    return LoadedEvaluationOutputManifestV2(
        model=validated, version=validated.contract.contract_version,
        sha256=observed, artifact_reference=reference,
    )


def load_evaluation_output_manifest_v2(
    eval_run_id: str,
    *,
    eval_root: str | Path,
    stage_profile_registry: LoadedStageProfileRegistry,
    expected_sha256: str | None = None,
) -> LoadedEvaluationOutputManifestV2:
    """Load a v0.2 output manifest and re-verify the whole audit chain.

    Explicit v0.2 reader: a v0.1 document at the same canonical path is rejected
    by declared version. Beyond the v0.1 protections it re-derives the evaluation
    stage from the run manifest plus the supplied registry, rejects a persisted
    ``derived_evaluation_stage`` that disagrees, and re-checks the stage/outcome
    binding conditional against the persisted document — so a manifest written by
    an older or patched path cannot load.
    """
    resolved_root = _validate_eval_root(eval_root)
    run_id = _validate_run_id(eval_run_id)
    reference = f"{run_id}/{_OUTPUT_DIR}/{_OUTPUT_FILENAME}"
    run_dir = resolved_root / run_id
    output_dir = run_dir / _OUTPUT_DIR
    dest = output_dir / _OUTPUT_FILENAME
    if run_dir.is_symlink() or output_dir.is_symlink() or dest.is_symlink():
        raise EvaluationOutputManifestError(
            "output manifest or a parent is a symlink",
            reason_code="artifact_symlink", artifact_reference=reference,
        )
    resolved = dest.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise EvaluationOutputManifestError(
            "output manifest resolves outside the evaluation root",
            reason_code="path_escape", artifact_reference=reference,
        )
    if not dest.exists():
        raise EvaluationOutputManifestError(
            "output manifest does not exist under the evaluation root",
            reason_code="artifact_missing", artifact_reference=reference,
        )
    if not dest.is_file():
        raise EvaluationOutputManifestError(
            "output manifest is not a regular file",
            reason_code="artifact_not_a_file", artifact_reference=reference,
        )
    try:
        raw = dest.read_bytes()
    except OSError as exc:
        raise EvaluationOutputManifestError(
            "failed to read the output manifest", reason_code="read_error",
            artifact_reference=reference,
        ) from exc
    observed = sha256_bytes(raw)
    if expected_sha256 is not None:
        valid = (
            isinstance(expected_sha256, str) and len(expected_sha256) == 64
            and all(c in "0123456789abcdef" for c in expected_sha256)
        )
        if not valid or expected_sha256 != observed:
            raise EvaluationOutputManifestError(
                "output manifest raw-byte hash does not match the expected hash",
                reason_code="expected_hash_mismatch", artifact_reference=reference,
            )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvaluationOutputManifestError(
            "output manifest is not valid UTF-8", reason_code="decode_error",
            artifact_reference=reference,
        ) from exc
    if text.startswith("\ufeff"):
        raise EvaluationOutputManifestError(
            "output manifest has a UTF-8 BOM", reason_code="bom", artifact_reference=reference
        )
    payload = _strict_json_object(text, reference)
    declared = _payload_contract_version(payload)
    if declared is not None and declared != _CONTRACT_VERSION_V2:
        raise EvaluationOutputManifestError(
            "output manifest is not an evaluation_output_manifest@0.2.0 document",
            reason_code="unsupported_contract_version", artifact_reference=reference,
        )
    try:
        model = EvaluationOutputManifestV2.model_validate(payload)
    except PydanticValidationError as exc:
        raise EvaluationOutputManifestError(
            "output manifest failed strict contract validation",
            reason_code="model_validation", artifact_reference=reference,
        ) from exc
    # Run-identity binding + independent stage re-derivation.
    manifest = _verified_v2_manifest(None, run_id, resolved_root)
    if model.eval_run_id != manifest.eval_run_id or model.eval_run_id != run_id:
        raise EvaluationOutputManifestError(
            "output manifest eval_run_id does not bind to the run",
            reason_code="run_binding", artifact_reference=reference,
        )
    derived_stage = _derive_evaluation_stage(manifest, stage_profile_registry)
    if model.derived_evaluation_stage != derived_stage:
        raise EvaluationOutputManifestError(
            "the persisted derived_evaluation_stage does not equal the re-derived stage",
            reason_code="derived_stage_mismatch", artifact_reference=reference,
        )
    dumped = model.model_dump(mode="json", exclude_unset=True)
    extraction = derived_stage in EXTRACTION_EVALUATION_STAGES
    if not extraction and dumped.get(_BINDING_HASH_FIELD) is not None:
        raise EvaluationOutputManifestError(
            "a non-extraction run must not record an observation-target binding",
            reason_code="binding_not_permitted_for_stage", artifact_reference=reference,
        )
    if (
        extraction
        and dumped.get("assertion_outcomes_sha256") is not None
        and dumped.get(_BINDING_HASH_FIELD) is None
    ):
        raise EvaluationOutputManifestError(
            "recorded extraction assertion outcomes require the observation-target binding",
            reason_code="extraction_outcomes_require_binding", artifact_reference=reference,
        )
    # Audit re-verification over the v0.2 location table.
    for field in _ARTIFACT_LOCATION_V2:
        recorded = dumped.get(field)
        if recorded is None:
            _reject_if_artifact_present(resolved_root, run_id, field, _ARTIFACT_LOCATION_V2)
            continue
        if _observed_artifact_hash(
            resolved_root, run_id, field, _ARTIFACT_LOCATION_V2
        ) != recorded:
            raise EvaluationOutputManifestError(
                "a bound artifact no longer matches its recorded read-back hash",
                reason_code="artifact_hash_mismatch",
                artifact_reference=_canonical_reference(run_id, field, _ARTIFACT_LOCATION_V2),
            )
    # Semantic re-verification of the binding chain. Matching read-back hashes only
    # prove the recorded bytes are intact; they do not prove the binding belongs to
    # this run, this stage, this parsed content, or this raw artifact. Both
    # artifacts are therefore re-loaded through their governed public loaders and
    # reconciled, so a hash-consistent but semantically mismatched binding cannot
    # load.
    if dumped.get(_BINDING_HASH_FIELD) is not None:
        binding_reference = _canonical_reference(
            run_id, _BINDING_HASH_FIELD, _ARTIFACT_LOCATION_V2
        )
        parsed_reference = _canonical_reference(
            run_id, "parsed_prediction_content_sha256", _ARTIFACT_LOCATION_V2
        )
        try:
            loaded_binding = load_observation_target_binding(
                binding_reference, eval_root=resolved_root,
                expected_sha256=dumped[_BINDING_HASH_FIELD],
            )
        except ObservationTargetBindingError as exc:
            raise EvaluationOutputManifestError(
                "the bound observation-target binding failed its governed load",
                reason_code="binding_load_failed", artifact_reference=binding_reference,
            ) from exc
        try:
            loaded_parsed = load_parsed_prediction_content(
                parsed_reference, eval_root=resolved_root,
                expected_sha256=dumped["parsed_prediction_content_sha256"],
            )
        except ParsedPredictionContentError as exc:
            raise EvaluationOutputManifestError(
                "the bound parsed prediction content failed its governed load",
                reason_code="parsed_content_load_failed", artifact_reference=parsed_reference,
            ) from exc
        bmodel = loaded_binding.model
        if bmodel.eval_run_id != run_id:
            raise EvaluationOutputManifestError(
                "the bound binding records a different eval_run_id",
                reason_code="binding_run_binding", artifact_reference=binding_reference,
            )
        if bmodel.stage != derived_stage:
            raise EvaluationOutputManifestError(
                "the bound binding stage does not equal the re-derived evaluation stage",
                reason_code="binding_stage_mismatch", artifact_reference=binding_reference,
            )
        if bmodel.parsed_prediction_content_sha256 != loaded_parsed.sha256:
            raise EvaluationOutputManifestError(
                "the bound binding is not pinned to this run's parsed prediction content",
                reason_code="binding_parsed_content_mismatch",
                artifact_reference=binding_reference,
            )
        try:
            _require_binding_raw_artifact_coherence(bmodel, loaded_parsed)
        except EvaluationOutputManifestError as exc:
            raise EvaluationOutputManifestError(
                str(exc), reason_code=exc.reason_code, artifact_reference=binding_reference
            ) from exc
    return LoadedEvaluationOutputManifestV2(
        model=model, version=model.contract.contract_version,
        sha256=observed, artifact_reference=reference,
    )


def _load_evaluation_output_manifest_any_supported_version(
    eval_run_id: str,
    *,
    eval_root: str | Path,
    stage_profile_registry: LoadedStageProfileRegistry | None = None,
) -> LoadedEvaluationOutputManifest | LoadedEvaluationOutputManifestV2:
    """Internal artifact-I/O helper: load the terminal manifest of either version.

    Not exported and not a public reader: the two public readers stay strictly
    single-version and never fall back. This helper exists so internal tooling can
    bind to a run directory regardless of which terminal-manifest version it
    holds. A v0.2 document requires ``stage_profile_registry`` for its stage
    re-derivation.
    """
    resolved_root = _validate_eval_root(eval_root)
    run_id = _validate_run_id(eval_run_id)
    reference = f"{run_id}/{_OUTPUT_DIR}/{_OUTPUT_FILENAME}"
    dest = resolved_root / run_id / _OUTPUT_DIR / _OUTPUT_FILENAME
    if dest.is_symlink():
        raise EvaluationOutputManifestError(
            "output manifest is a symlink", reason_code="artifact_symlink",
            artifact_reference=reference,
        )
    if not dest.exists():
        raise EvaluationOutputManifestError(
            "output manifest does not exist under the evaluation root",
            reason_code="artifact_missing", artifact_reference=reference,
        )
    try:
        text = dest.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise EvaluationOutputManifestError(
            "failed to read the output manifest", reason_code="read_error",
            artifact_reference=reference,
        ) from exc
    declared = _payload_contract_version(_strict_json_object(text, reference))
    if declared == _CONTRACT_VERSION:
        return load_evaluation_output_manifest(run_id, eval_root=resolved_root)
    if declared == _CONTRACT_VERSION_V2:
        if stage_profile_registry is None:
            raise EvaluationOutputManifestError(
                "a v0.2 output manifest requires the stage-profile registry",
                reason_code="stage_profile_registry_required", artifact_reference=reference,
            )
        return load_evaluation_output_manifest_v2(
            run_id, eval_root=resolved_root, stage_profile_registry=stage_profile_registry
        )
    raise EvaluationOutputManifestError(
        "output manifest declares an unsupported evaluation_output_manifest version",
        reason_code="unsupported_contract_version", artifact_reference=reference,
    )
