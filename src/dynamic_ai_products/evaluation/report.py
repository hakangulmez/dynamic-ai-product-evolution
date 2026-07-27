"""Slice 13: terminal evaluation reports (machine build, human render, persist).

``build_machine_report`` projects one reloaded terminal ``EvaluationResultV2``
wrapper (plus, optionally, the reloaded v0.2 output-manifest wrapper) into a
strict, non-contract-stamped ``MachineEvaluationReport`` whose identities mirror
the reloaded wrappers exactly. ``render_human_report`` derives deterministic
UTF-8 Markdown from the machine report alone — it reads no clock, Git state,
filesystem path, network endpoint, provider, or other artifact.
``persist_evaluation_reports`` is the only function here that touches the
filesystem: it writes both report files write-once (``O_EXCL``), re-reads their
raw persisted bytes, and returns the read-back hashes. Report hashes never
enter any governed artifact.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from .contracts import canonical_contract_bytes
from .gates import LoadedEvaluationResult
from .models import EvaluationResultV2, EvaluationStrictModel, _reject_explicit_null
from .output_manifest import LoadedEvaluationOutputManifestV2
from ..universe.io_utils import sha256_bytes

__all__ = [
    "MachineEvaluationReport",
    "PersistedEvaluationReports",
    "build_machine_report",
    "persist_evaluation_reports",
    "render_human_report",
]

_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"
_REPORTS_DIR = "reports"
_MACHINE_REPORT_FILENAME = "machine_evaluation_report.json"
_HUMAN_REPORT_FILENAME = "human_evaluation_report.md"
_MACHINE_REPORT_REFERENCE = f"{_REPORTS_DIR}/{_MACHINE_REPORT_FILENAME}"
_HUMAN_REPORT_REFERENCE = f"{_REPORTS_DIR}/{_HUMAN_REPORT_FILENAME}"


class _ReportWriteError(Exception):
    """Private sanitized report-persistence failure (never exported)."""

    def __init__(self, message: str, *, artifact_reference: str | None = None) -> None:
        super().__init__(message)
        self.artifact_reference = artifact_reference


def _require_non_blank(value: str, field_name: str) -> None:
    if not value or value != value.strip():
        raise ValueError(
            f"{field_name} must be a non-empty string without leading or trailing whitespace"
        )


class MachineEvaluationReport(EvaluationStrictModel):
    """Strict machine-readable terminal report; not contract-stamped.

    Identity fields mirror the reloaded result wrapper exactly; the optional
    output-manifest fields are omit-or-non-null and mirror the reloaded v0.2
    output-manifest wrapper exactly when supplied.
    """

    eval_run_id: str
    result_reference: Literal["results/evaluation_result.json"]
    result_sha256: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    evaluation_result: EvaluationResultV2
    output_manifest_reference: str | None = None
    output_manifest_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )

    @model_validator(mode="before")
    @classmethod
    def _no_explicit_null_optionals(cls, data: Any) -> Any:
        return _reject_explicit_null(
            data,
            ("output_manifest_reference", "output_manifest_sha256"),
            "MachineEvaluationReport",
        )

    @model_validator(mode="after")
    def _report_invariants(self) -> "MachineEvaluationReport":
        _require_non_blank(self.eval_run_id, "eval_run_id")
        if self.eval_run_id != self.evaluation_result.eval_run_id:
            raise ValueError(
                "eval_run_id must equal the embedded evaluation result's eval_run_id"
            )
        reference_present = "output_manifest_reference" in self.model_fields_set
        sha_present = "output_manifest_sha256" in self.model_fields_set
        if reference_present != sha_present:
            raise ValueError(
                "output_manifest_reference and output_manifest_sha256 must be supplied "
                "together or omitted together"
            )
        if reference_present:
            reference = self.output_manifest_reference
            _require_non_blank(reference, "output_manifest_reference")
            if reference.startswith("/") or "\\" in reference or "\x00" in reference:
                raise ValueError(
                    "output_manifest_reference must be a normalized relative reference"
                )
            if any(part in ("", ".", "..") for part in reference.split("/")):
                raise ValueError(
                    "output_manifest_reference must not contain empty, '.' or '..' components"
                )
        return self


class PersistedEvaluationReports(EvaluationStrictModel):
    """Strict, non-contract-stamped read-back identities of both report files."""

    eval_run_id: str
    machine_report_reference: Literal["reports/machine_evaluation_report.json"]
    machine_report_sha256: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    human_report_reference: Literal["reports/human_evaluation_report.md"]
    human_report_sha256: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )


def build_machine_report(
    result: LoadedEvaluationResult,
    output_manifest: LoadedEvaluationOutputManifestV2 | None,
) -> MachineEvaluationReport:
    """Project the reloaded terminal wrappers into a machine report.

    Only the exact reloaded wrapper types are accepted; raw dicts,
    caller-supplied result models, arbitrary hashes, metric reports, findings,
    gate verdicts, issue tuples, and runner summaries are rejected. The result
    identity mirrors ``result`` exactly; when ``output_manifest`` is supplied
    its run identity must agree and its reference and SHA are mirrored exactly.
    """
    if type(result) is not LoadedEvaluationResult:
        raise TypeError(
            f"result must be a LoadedEvaluationResult, got {type(result).__name__}"
        )
    if output_manifest is not None and type(output_manifest) is not (
        LoadedEvaluationOutputManifestV2
    ):
        raise TypeError(
            "output_manifest must be a LoadedEvaluationOutputManifestV2 or None, got "
            f"{type(output_manifest).__name__}"
        )
    kwargs: dict[str, Any] = {
        "eval_run_id": result.eval_run_id,
        "result_reference": result.artifact_reference,
        "result_sha256": result.sha256,
        "evaluation_result": result.result,
    }
    if output_manifest is not None:
        if output_manifest.model.eval_run_id != result.eval_run_id:
            raise ValueError(
                "output manifest eval_run_id does not equal the result wrapper's eval_run_id"
            )
        kwargs["output_manifest_reference"] = output_manifest.artifact_reference
        kwargs["output_manifest_sha256"] = output_manifest.sha256
    return MachineEvaluationReport(**kwargs)


def _rendered_verdict(result: EvaluationResultV2) -> str:
    if "gate_verdict" in result.model_fields_set and result.gate_verdict is not None:
        return result.gate_verdict
    return "not applicable"


def render_human_report(report: MachineEvaluationReport) -> str:
    """Render deterministic UTF-8 Markdown derived only from the machine report."""
    if type(report) is not MachineEvaluationReport:
        raise TypeError(
            f"report must be a MachineEvaluationReport, got {type(report).__name__}"
        )
    result = report.evaluation_result
    lines: list[str] = [
        f"# Evaluation report: {report.eval_run_id}",
        "",
        f"- Stage: {result.stage}",
        f"- Execution status: {result.execution_status}",
        f"- Gate verdict: {_rendered_verdict(result)}",
        f"- Dataset version: {result.dataset_version}",
        f"- Result artifact: `{report.result_reference}` (sha256 `{report.result_sha256}`)",
    ]
    if report.output_manifest_reference is not None:
        lines.append(
            f"- Output manifest: `{report.output_manifest_reference}` "
            f"(sha256 `{report.output_manifest_sha256}`)"
        )
    else:
        lines.append("- Output manifest: not persisted")
    gate_outcomes = result.metrics.get("gate_outcomes")
    lines.extend(("", "## Gate outcomes", ""))
    if isinstance(gate_outcomes, list) and gate_outcomes:
        for outcome in gate_outcomes:
            if isinstance(outcome, dict):
                lines.append(
                    f"- `{outcome.get('gate_reference_id')}`: {outcome.get('outcome')}"
                )
    else:
        lines.append("None recorded.")
    critical = result.metrics.get("critical_finding_ids")
    lines.extend(("", "## Critical findings", ""))
    if isinstance(critical, list) and critical:
        lines.extend(f"- `{finding_id}`" for finding_id in critical)
    else:
        lines.append("None recorded.")
    lines.extend(("", "## Issues", ""))
    if result.errors:
        for issue in result.errors:
            if isinstance(issue, dict):
                lines.append(f"- `{issue.get('issue_code')}`: {issue.get('message')}")
    else:
        lines.append("None recorded.")
    return "\n".join(lines) + "\n"


def _read_back_sha256(path: Path, reference: str) -> str:
    """Private read-back helper: hash the exact persisted raw bytes."""
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise _ReportWriteError(
            f"failed to re-read persisted report {reference!r} for verification",
            artifact_reference=reference,
        ) from exc


def _write_report_file(path: Path, data: bytes, reference: str) -> str:
    if path.is_symlink() or path.exists():
        raise _ReportWriteError(
            f"report {reference!r} already exists; report files are write-once",
            artifact_reference=reference,
        )
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise _ReportWriteError(
            f"report {reference!r} already exists; report files are write-once",
            artifact_reference=reference,
        ) from exc
    except OSError as exc:
        raise _ReportWriteError(
            f"failed to create report {reference!r}", artifact_reference=reference
        ) from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise _ReportWriteError(
            f"failed to write report {reference!r}", artifact_reference=reference
        ) from exc
    observed = _read_back_sha256(path, reference)
    if observed != sha256_bytes(data):
        raise _ReportWriteError(
            f"persisted report {reference!r} re-read to a different hash",
            artifact_reference=reference,
        )
    return observed


def persist_evaluation_reports(
    machine_report: MachineEvaluationReport,
    human_report: str,
    *,
    eval_root: str | Path,
    eval_run_id: str,
) -> PersistedEvaluationReports:
    """Write both report files write-once and return their read-back identities.

    The machine report is serialized as
    ``canonical_contract_bytes(model_dump(mode="json", exclude_unset=True))``
    plus one terminal LF byte; the human report is written as its strict UTF-8
    encoding, unmodified. Existing report files are never deleted, repaired,
    overwritten, or retried.
    """
    if type(machine_report) is not MachineEvaluationReport:
        raise TypeError(
            "machine_report must be a MachineEvaluationReport, got "
            f"{type(machine_report).__name__}"
        )
    if not isinstance(human_report, str):
        raise TypeError(
            f"human_report must be a str, got {type(human_report).__name__}"
        )
    if not human_report or not human_report.strip():
        raise ValueError("human_report must be non-empty text")
    try:
        human_bytes = human_report.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError("human_report must be strictly UTF-8 encodable") from exc
    if not isinstance(eval_run_id, str):
        raise TypeError(f"eval_run_id must be a str, got {type(eval_run_id).__name__}")
    _require_non_blank(eval_run_id, "eval_run_id")
    if machine_report.eval_run_id != eval_run_id:
        raise ValueError(
            "machine_report eval_run_id does not equal the explicit persistence eval_run_id"
        )
    if not isinstance(eval_root, (str, Path)):
        raise TypeError(
            f"eval_root must be an explicit str or Path, got {type(eval_root).__name__}"
        )
    run_directory = Path(eval_root) / eval_run_id
    if run_directory.is_symlink() or not run_directory.is_dir():
        raise _ReportWriteError(
            "run directory does not exist under the evaluation root",
            artifact_reference=eval_run_id,
        )
    reports_directory = run_directory / _REPORTS_DIR
    if reports_directory.is_symlink():
        raise _ReportWriteError(
            "run reports directory is a symlink", artifact_reference=_REPORTS_DIR
        )
    if reports_directory.exists():
        if not reports_directory.is_dir():
            raise _ReportWriteError(
                "run reports path is not a directory", artifact_reference=_REPORTS_DIR
            )
    else:
        try:
            reports_directory.mkdir(exist_ok=False)
        except OSError as exc:
            raise _ReportWriteError(
                "failed to create the run reports directory",
                artifact_reference=_REPORTS_DIR,
            ) from exc
    machine_bytes = (
        canonical_contract_bytes(machine_report.model_dump(mode="json", exclude_unset=True))
        + b"\n"
    )
    machine_sha256 = _write_report_file(
        reports_directory / _MACHINE_REPORT_FILENAME, machine_bytes, _MACHINE_REPORT_REFERENCE
    )
    human_sha256 = _write_report_file(
        reports_directory / _HUMAN_REPORT_FILENAME, human_bytes, _HUMAN_REPORT_REFERENCE
    )
    return PersistedEvaluationReports(
        eval_run_id=eval_run_id,
        machine_report_reference=_MACHINE_REPORT_REFERENCE,
        machine_report_sha256=machine_sha256,
        human_report_reference=_HUMAN_REPORT_REFERENCE,
        human_report_sha256=human_sha256,
    )
