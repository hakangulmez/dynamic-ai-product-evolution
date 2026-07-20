"""Append-only finding dispositions (Slice 8, SPEC-022 / SPEC-023 / ADR-018).

A disposition is a human review event appended beside — never into — the
immutable validator findings of one evaluation run. Nothing in this module
alters, filters, replaces, suppresses, re-severities or removes a finding,
and nothing here produces an execution status, a gate verdict, or any gate
arithmetic: per ADR-018 those remain later-slice responsibilities operating
on the raw findings only.

Lifecycle scope (locked decision): only the two states derivable from the
records that actually exist today are implemented — ``open`` (no disposition
references the finding) and ``dispositioned`` (at least one does). The other
four SPEC-023 states (``remediation_pending``, ``resolved_by_rerun``,
``superseded``, ``unresolved``) require remediation, rerun-resolution and
supersession event models that SPEC-022 does not define; they are deliberately
not inferred here, and the public alias is named ``DispositionState`` rather
than a lifecycle name to keep that limitation explicit.

Appending uses a mandatory expected-previous hash, a single canonical payload
written with ``O_APPEND``, an fsync, and a full re-read proving the final
bytes equal ``previous_bytes + payload``. There is no rollback, truncation,
rewrite or atomic replacement: a failed append leaves the artifact exactly as
the failure left it, and an observable concurrent modification is reported as
a typed error rather than as success. Concurrent writers are unsupported in
Phase 1.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError as PydanticValidationError,
)

from .cases import InvalidEvaluationRootError
from .contracts import canonical_contract_bytes
from .models import FindingDisposition, ValidatorFinding
from .runs import load_evaluation_run_manifest
from .validators import load_validator_findings
from ..universe.io_utils import sha256_bytes

_DISPOSITIONS_DIR = "dispositions"
_DISPOSITIONS_FILENAME = "finding_dispositions.jsonl"
# SHA-256 of empty bytes, written as a literal so importing this module
# performs no hashing (the package import stays free of I/O, hashing and
# wall-clock access).
_EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_SHA256_HEX_CHARS = set("0123456789abcdef")

DispositionState = Literal["open", "dispositioned"]


class _Slice8StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- Result models --------------------------------------------------------


class LoadedFindingDispositions(_Slice8StrictModel):
    eval_run_id: str
    artifact_reference: str
    sha256: str
    dispositions: tuple[FindingDisposition, ...]


class AppendedFindingDispositions(_Slice8StrictModel):
    """Receipt proving what was appended and the resulting artifact bytes."""

    eval_run_id: str
    artifact_reference: str
    previous_sha256: str
    sha256: str
    appended_count: int
    appended: tuple[FindingDisposition, ...]


class DerivedDispositionState(_Slice8StrictModel):
    finding_id: str
    state: DispositionState
    disposition_count: int


# --- Exceptions -----------------------------------------------------------


class DispositionError(Exception):
    """Base class for Slice 8 disposition failures; never raised directly."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
        disposition_id: str | None = None,
        finding_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.eval_run_id = eval_run_id
        self.artifact_reference = artifact_reference
        self.disposition_id = disposition_id
        self.finding_id = finding_id


class EmptyDispositionAppendError(DispositionError):
    """An append batch contained no disposition records."""


class InvalidExpectedPreviousHashError(DispositionError):
    """The supplied expected-previous hash is not a lowercase SHA-256 hex."""


class DispositionPreviousHashMismatchError(DispositionError):
    """The artifact's current bytes do not match the expected-previous hash."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
        expected_sha256: str | None = None,
        observed_sha256: str | None = None,
    ) -> None:
        super().__init__(
            message, eval_run_id=eval_run_id, artifact_reference=artifact_reference
        )
        self.expected_sha256 = expected_sha256
        self.observed_sha256 = observed_sha256


class DispositionArtifactMissingError(DispositionError):
    """A required dispositions artifact does not exist."""


class DispositionArtifactNotAFileError(DispositionError):
    """A dispositions artifact or a parent is not a regular file/directory."""


class DispositionArtifactReadError(DispositionError):
    """Reading a dispositions artifact failed."""


class DispositionDecodeError(DispositionError):
    """A dispositions artifact's bytes are not valid UTF-8."""


class DispositionJsonError(DispositionError):
    """A dispositions artifact is not acceptable strict JSONL."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
        line_number: int | None = None,
        duplicate_key: str | None = None,
        constant_name: str | None = None,
    ) -> None:
        super().__init__(
            message, eval_run_id=eval_run_id, artifact_reference=artifact_reference
        )
        self.line_number = line_number
        self.duplicate_key = duplicate_key
        self.constant_name = constant_name


class DispositionTopLevelTypeError(DispositionError):
    """A parsed disposition line is not a JSON object."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
        observed_type: str | None = None,
        line_number: int | None = None,
    ) -> None:
        super().__init__(
            message, eval_run_id=eval_run_id, artifact_reference=artifact_reference
        )
        self.observed_type = observed_type
        self.line_number = line_number


class DispositionModelValidationError(DispositionError):
    """A disposition line failed FindingDisposition model/contract validation."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
        line_number: int | None = None,
        field_locations: tuple[str, ...] = (),
        error_types: tuple[str, ...] = (),
    ) -> None:
        super().__init__(
            message, eval_run_id=eval_run_id, artifact_reference=artifact_reference
        )
        self.line_number = line_number
        self.field_locations = field_locations
        self.error_types = error_types


class DuplicateDispositionIdError(DispositionError):
    """Two dispositions share a disposition_id."""


class UnknownFindingReferenceError(DispositionError):
    """A disposition references a finding_id absent from the run's findings."""


class ProhibitedCriticalRiskAcceptanceError(DispositionError):
    """`accepted_nonblocking_risk` was applied to a critical finding."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        disposition_id: str | None = None,
        finding_id: str | None = None,
        severity: str | None = None,
    ) -> None:
        super().__init__(
            message, eval_run_id=eval_run_id, disposition_id=disposition_id,
            finding_id=finding_id,
        )
        self.severity = severity


class DispositionWriteError(DispositionError):
    """Writing to the dispositions artifact failed."""


class DispositionConcurrentModificationError(DispositionError):
    """The artifact changed observably around the append."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
        expected_sha256: str | None = None,
        observed_sha256: str | None = None,
    ) -> None:
        super().__init__(
            message, eval_run_id=eval_run_id, artifact_reference=artifact_reference
        )
        self.expected_sha256 = expected_sha256
        self.observed_sha256 = observed_sha256


class DispositionDestinationHashMismatchError(DispositionError):
    """Final bytes are not exactly previous bytes plus the appended payload."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
        expected_sha256: str | None = None,
        observed_sha256: str | None = None,
    ) -> None:
        super().__init__(
            message, eval_run_id=eval_run_id, artifact_reference=artifact_reference
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


# --- Shared helpers -------------------------------------------------------


def _validate_root(root: str | Path) -> Path:
    if not isinstance(root, (str, Path)):
        raise InvalidEvaluationRootError(
            "eval_root must be an explicit str or Path root", observed_type=type(root).__name__
        )
    if isinstance(root, str) and root == "":
        raise InvalidEvaluationRootError(
            "eval_root must not be an empty string; supply the root explicitly", supplied_root=""
        )
    path = Path(root)
    if not path.exists():
        raise InvalidEvaluationRootError(
            f"eval_root {str(root)!r} does not exist", supplied_root=str(root)
        )
    if not path.is_dir():
        raise InvalidEvaluationRootError(
            f"eval_root {str(root)!r} is not a directory", supplied_root=str(root)
        )
    return path.resolve()


def _canonical_disposition_line(disposition: FindingDisposition) -> bytes:
    return canonical_contract_bytes(disposition.model_dump(mode="json", exclude_unset=True))


def _serialize_dispositions(dispositions: tuple[FindingDisposition, ...]) -> bytes:
    return b"".join(_canonical_disposition_line(d) + b"\n" for d in dispositions)


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


def _first_non_finite(payload: Any) -> str | None:
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


def _parse_dispositions_jsonl(
    text: str, *, eval_run_id: str, reference: str
) -> tuple[FindingDisposition, ...]:
    if text == "":
        return ()
    records: list[FindingDisposition] = []
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    for index, line in enumerate(lines):
        ln = index + 1
        if not line or not line.strip():
            raise DispositionJsonError(
                f"dispositions artifact {reference!r} line {ln} is blank",
                eval_run_id=eval_run_id, artifact_reference=reference, line_number=ln,
            )
        try:
            payload = json.loads(
                line,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_non_finite_constant,
            )
        except json.JSONDecodeError as exc:
            raise DispositionJsonError(
                f"dispositions artifact {reference!r} line {ln} is not valid JSON: {exc.msg}",
                eval_run_id=eval_run_id, artifact_reference=reference, line_number=ln,
            ) from exc
        except _DuplicateKeyControl as exc:
            raise DispositionJsonError(
                f"dispositions artifact {reference!r} line {ln} has duplicate key {exc.key!r}",
                eval_run_id=eval_run_id, artifact_reference=reference,
                line_number=ln, duplicate_key=exc.key,
            ) from exc
        except _NonFiniteControl as exc:
            raise DispositionJsonError(
                f"dispositions artifact {reference!r} line {ln} has non-JSON constant "
                f"{exc.constant_name}",
                eval_run_id=eval_run_id, artifact_reference=reference,
                line_number=ln, constant_name=exc.constant_name,
            ) from exc
        non_finite = _first_non_finite(payload)
        if non_finite is not None:
            raise DispositionJsonError(
                f"dispositions artifact {reference!r} line {ln} has non-finite number "
                f"({non_finite})",
                eval_run_id=eval_run_id, artifact_reference=reference,
                line_number=ln, constant_name=non_finite,
            )
        if not isinstance(payload, dict):
            raise DispositionTopLevelTypeError(
                f"dispositions artifact {reference!r} line {ln} is not a JSON object",
                eval_run_id=eval_run_id, artifact_reference=reference,
                observed_type=type(payload).__name__, line_number=ln,
            )
        try:
            records.append(FindingDisposition.model_validate(payload))
        except PydanticValidationError as exc:
            pairs = sorted(
                ("/".join(str(p) for p in e["loc"]), e["type"]) for e in exc.errors()
            )
            raise DispositionModelValidationError(
                f"dispositions artifact {reference!r} line {ln} failed FindingDisposition "
                "validation",
                eval_run_id=eval_run_id, artifact_reference=reference, line_number=ln,
                field_locations=tuple(loc for loc, _ in pairs),
                error_types=tuple(t for _, t in pairs),
            ) from exc
    return tuple(records)


def _require_unique_disposition_ids(
    dispositions: tuple[FindingDisposition, ...], eval_run_id: str, reference: str | None
) -> None:
    seen: set[str] = set()
    for disposition in dispositions:
        if disposition.disposition_id in seen:
            raise DuplicateDispositionIdError(
                f"duplicate disposition_id {disposition.disposition_id!r}",
                eval_run_id=eval_run_id, artifact_reference=reference,
                disposition_id=disposition.disposition_id,
            )
        seen.add(disposition.disposition_id)


def _classify_existing(
    dest: Path, run_dir: Path, dispositions_dir: Path, reference: str, eval_run_id: str
) -> bytes:
    """Return current artifact bytes, or b"" when the artifact is absent."""
    if run_dir.is_symlink() or dispositions_dir.is_symlink() or dest.is_symlink():
        raise DispositionArtifactNotAFileError(
            f"dispositions artifact {reference!r} or a parent is a symlink",
            eval_run_id=eval_run_id, artifact_reference=reference,
        )
    if dispositions_dir.exists() and not dispositions_dir.is_dir():
        raise DispositionArtifactNotAFileError(
            f"dispositions path {eval_run_id}/{_DISPOSITIONS_DIR} is not a directory",
            eval_run_id=eval_run_id, artifact_reference=reference,
        )
    if not dest.exists():
        return b""
    if not dest.is_file():
        raise DispositionArtifactNotAFileError(
            f"dispositions artifact {reference!r} is not a regular file",
            eval_run_id=eval_run_id, artifact_reference=reference,
        )
    try:
        return dest.read_bytes()
    except OSError as exc:
        raise DispositionArtifactReadError(
            f"failed to read dispositions artifact {reference!r}",
            eval_run_id=eval_run_id, artifact_reference=reference,
        ) from exc


# --- Public API -----------------------------------------------------------


def append_finding_dispositions(
    dispositions: tuple[FindingDisposition, ...],
    *,
    eval_root: str | Path,
    eval_run_id: str,
    expected_previous_sha256: str,
) -> AppendedFindingDispositions:
    """Append a disposition batch, proving prior bytes survive untouched.

    The caller must supply the expected current hash of the artifact (the
    SHA-256 of empty bytes for the first append). Prior bytes are verified
    before the append and proven to remain an exact prefix afterwards.
    """
    if not dispositions:
        raise EmptyDispositionAppendError(
            "an append batch must contain at least one disposition",
            eval_run_id=eval_run_id,
        )
    if (
        not isinstance(expected_previous_sha256, str)
        or len(expected_previous_sha256) != 64
        or not set(expected_previous_sha256) <= _SHA256_HEX_CHARS
    ):
        raise InvalidExpectedPreviousHashError(
            "expected_previous_sha256 must be a lowercase 64-character SHA-256 hex digest",
            eval_run_id=eval_run_id,
        )

    resolved_root = _validate_root(eval_root)
    loaded_run = load_evaluation_run_manifest(eval_run_id, eval_root=resolved_root)
    run_id = loaded_run.manifest.eval_run_id

    # Findings are loaded read-only: they bound which finding IDs may be
    # referenced and which severities forbid risk acceptance. They are never
    # rewritten, filtered or re-severitied here.
    findings = load_validator_findings(eval_run_id, eval_root=resolved_root).findings
    severity_by_finding: dict[str, str] = {f.finding_id: f.severity for f in findings}

    run_dir = resolved_root / eval_run_id
    dispositions_dir = run_dir / _DISPOSITIONS_DIR
    dest = dispositions_dir / _DISPOSITIONS_FILENAME
    reference = f"{eval_run_id}/{_DISPOSITIONS_DIR}/{_DISPOSITIONS_FILENAME}"

    previous_bytes = _classify_existing(dest, run_dir, dispositions_dir, reference, run_id)
    previous_hash = sha256_bytes(previous_bytes)
    if previous_hash != expected_previous_sha256:
        raise DispositionPreviousHashMismatchError(
            f"dispositions artifact {reference!r} does not match the expected previous hash",
            eval_run_id=run_id, artifact_reference=reference,
            expected_sha256=expected_previous_sha256, observed_sha256=previous_hash,
        )
    existing = _parse_dispositions_jsonl(
        previous_bytes.decode("utf-8", errors="strict") if previous_bytes else "",
        eval_run_id=run_id, reference=reference,
    )

    _require_unique_disposition_ids(dispositions, run_id, None)
    existing_ids = {d.disposition_id for d in existing}
    for disposition in dispositions:
        if disposition.disposition_id in existing_ids:
            raise DuplicateDispositionIdError(
                f"disposition_id {disposition.disposition_id!r} already exists in the artifact",
                eval_run_id=run_id, artifact_reference=reference,
                disposition_id=disposition.disposition_id,
            )
        if disposition.finding_id not in severity_by_finding:
            raise UnknownFindingReferenceError(
                f"disposition {disposition.disposition_id!r} references unknown finding "
                f"{disposition.finding_id!r}",
                eval_run_id=run_id, artifact_reference=reference,
                disposition_id=disposition.disposition_id, finding_id=disposition.finding_id,
            )
        if (
            disposition.disposition == "accepted_nonblocking_risk"
            and severity_by_finding[disposition.finding_id] == "critical"
        ):
            raise ProhibitedCriticalRiskAcceptanceError(
                "accepted_nonblocking_risk must never be applied to a critical finding",
                eval_run_id=run_id, disposition_id=disposition.disposition_id,
                finding_id=disposition.finding_id, severity="critical",
            )

    payload = _serialize_dispositions(dispositions)

    if not dispositions_dir.exists():
        try:
            dispositions_dir.mkdir(exist_ok=False)
        except OSError as exc:
            raise DispositionWriteError(
                f"failed to create dispositions directory for {eval_run_id!r}",
                eval_run_id=run_id, artifact_reference=reference,
            ) from exc

    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    except OSError as exc:
        raise DispositionWriteError(
            f"failed to open dispositions artifact {reference!r} for append",
            eval_run_id=run_id, artifact_reference=reference,
        ) from exc
    try:
        with os.fdopen(fd, "ab") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        # No rollback, truncation or cleanup: the artifact is left exactly as
        # the failure left it, and the failure is reported rather than hidden.
        raise DispositionWriteError(
            f"failed to append to dispositions artifact {reference!r}",
            eval_run_id=run_id, artifact_reference=reference,
        ) from exc

    try:
        final_bytes = dest.read_bytes()
    except OSError as exc:
        raise DispositionArtifactReadError(
            f"failed to re-read dispositions artifact {reference!r} after append",
            eval_run_id=run_id, artifact_reference=reference,
        ) from exc
    expected_final = previous_bytes + payload
    if final_bytes != expected_final:
        if not final_bytes.startswith(previous_bytes):
            raise DispositionConcurrentModificationError(
                f"dispositions artifact {reference!r} no longer begins with the verified "
                "previous bytes; a concurrent modification is observable",
                eval_run_id=run_id, artifact_reference=reference,
                expected_sha256=sha256_bytes(expected_final),
                observed_sha256=sha256_bytes(final_bytes),
            )
        raise DispositionDestinationHashMismatchError(
            f"dispositions artifact {reference!r} final bytes are not exactly the previous "
            "bytes plus the appended payload",
            eval_run_id=run_id, artifact_reference=reference,
            expected_sha256=sha256_bytes(expected_final),
            observed_sha256=sha256_bytes(final_bytes),
        )

    return AppendedFindingDispositions(
        eval_run_id=eval_run_id,
        artifact_reference=reference,
        previous_sha256=previous_hash,
        sha256=sha256_bytes(final_bytes),
        appended_count=len(dispositions),
        appended=dispositions,
    )


def load_finding_dispositions(
    eval_run_id: str, *, eval_root: str | Path
) -> LoadedFindingDispositions:
    """Load the append-only disposition log from the fixed run-directory path."""
    resolved_root = _validate_root(eval_root)
    load_evaluation_run_manifest(eval_run_id, eval_root=resolved_root)
    run_dir = resolved_root / eval_run_id
    dispositions_dir = run_dir / _DISPOSITIONS_DIR
    dest = dispositions_dir / _DISPOSITIONS_FILENAME
    reference = f"{eval_run_id}/{_DISPOSITIONS_DIR}/{_DISPOSITIONS_FILENAME}"
    if run_dir.is_symlink() or dispositions_dir.is_symlink() or dest.is_symlink():
        raise DispositionArtifactNotAFileError(
            f"dispositions artifact {reference!r} or a parent is a symlink",
            eval_run_id=eval_run_id, artifact_reference=reference,
        )
    if not dest.exists():
        raise DispositionArtifactMissingError(
            f"dispositions artifact {reference!r} does not exist",
            eval_run_id=eval_run_id, artifact_reference=reference,
        )
    if not dest.is_file():
        raise DispositionArtifactNotAFileError(
            f"dispositions artifact {reference!r} is not a regular file",
            eval_run_id=eval_run_id, artifact_reference=reference,
        )
    try:
        raw = dest.read_bytes()
    except OSError as exc:
        raise DispositionArtifactReadError(
            f"failed to read dispositions artifact {reference!r}",
            eval_run_id=eval_run_id, artifact_reference=reference,
        ) from exc
    observed = sha256_bytes(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DispositionDecodeError(
            f"dispositions artifact {reference!r} is not valid UTF-8",
            eval_run_id=eval_run_id, artifact_reference=reference,
        ) from exc
    records = _parse_dispositions_jsonl(text, eval_run_id=eval_run_id, reference=reference)
    _require_unique_disposition_ids(records, eval_run_id, reference)
    return LoadedFindingDispositions(
        eval_run_id=eval_run_id, artifact_reference=reference, sha256=observed,
        dispositions=records,
    )


def derive_disposition_states(
    findings: tuple[ValidatorFinding, ...],
    dispositions: tuple[FindingDisposition, ...],
) -> tuple[DerivedDispositionState, ...]:
    """Derive per-finding disposition coverage in the findings' own order.

    Only ``open`` and ``dispositioned`` are derivable from the governed
    records that exist today; no other SPEC-023 lifecycle state is inferred,
    and no disposition alters the finding it references.
    """
    counts: dict[str, int] = {}
    for disposition in dispositions:
        counts[disposition.finding_id] = counts.get(disposition.finding_id, 0) + 1
    states: list[DerivedDispositionState] = []
    for finding in findings:
        count = counts.get(finding.finding_id, 0)
        states.append(
            DerivedDispositionState(
                finding_id=finding.finding_id,
                state="dispositioned" if count else "open",
                disposition_count=count,
            )
        )
    return tuple(states)


EMPTY_DISPOSITION_LOG_SHA256 = _EMPTY_SHA256
"""SHA-256 of empty bytes — the expected previous hash for a first append."""
