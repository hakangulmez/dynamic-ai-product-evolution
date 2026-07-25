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
from .models import ContractStampedModel, EvaluationStrictModel, _reject_explicit_null, _require_non_blank
from .prediction_content import LoadedParsedPredictionContent
from .runs import load_evaluation_run_manifest_v2
from .validation_snapshot import LoadedValidationArtifactSnapshotSet
from .validators import PersistedValidatorFindings
from ..universe.io_utils import sha256_bytes

__all__ = [
    "EvaluationOutputManifest",
    "EvaluationOutputManifestError",
    "LoadedEvaluationOutputManifest",
    "build_evaluation_output_manifest",
    "load_evaluation_output_manifest",
    "persist_evaluation_output_manifest",
]

_CONTRACT_ID = "evaluation_output_manifest"
_CONTRACT_VERSION = "0.1.0"
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


def _canonical_reference(run_id: str, field: str) -> str:
    subdir, filename = _ARTIFACT_LOCATION[field]
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


def _observed_artifact_hash(resolved_root: Path, run_id: str, field: str) -> str:
    subdir, filename = _ARTIFACT_LOCATION[field]
    resolved = _resolve_run_artifact(resolved_root, run_id, subdir, filename)
    reference = f"{run_id}/{subdir}/{filename}"
    try:
        return sha256_bytes(resolved.read_bytes())
    except OSError as exc:
        raise EvaluationOutputManifestError(
            "failed to read a bound artifact", reason_code="read_error",
            artifact_reference=reference,
        ) from exc


def _reject_if_artifact_present(resolved_root: Path, run_id: str, field: str) -> None:
    """Reject an optional derived artifact that exists on disk but is omitted.

    A canonical artifact file that is present (or a symlink) while its hash field
    is absent from the manifest means the audit chain is silently incomplete.
    """
    subdir, filename = _ARTIFACT_LOCATION[field]
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
