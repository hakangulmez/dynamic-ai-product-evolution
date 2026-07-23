"""Governed source/passage snapshot manifest (Slice 12D).

``source_passage_snapshot_manifest@0.1.0`` binds a source-document corpus and a
source-passage corpus (each a JSONL file) by relative reference, raw-byte
SHA-256, and record count, and carries a self-excluding aggregate content hash
that is the authoritative ``source_passage_snapshot_hash`` pinned by
``EvaluationRunManifestV2``. The two corpora reuse the committed Phase-0
``source_document``/``source_passage`` static schemas, validated at call time by
a module-private pinned loader (this module never touches
``evaluation.schemas`` or its registry).

Read-side plus pure validation and explicit persistence only. Importing this
module performs no filesystem access, hashing, environment inspection, clock
read, UUID generation, network, provider, or model call. Five distinct hash
identities are kept separate: the generated model-contract hash (over the model
schema), the self-excluding aggregate content hash, the raw persisted
manifest-byte SHA-256, the raw document-JSONL byte SHA-256, and the raw
passage-JSONL byte SHA-256.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, ClassVar, Literal

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from pydantic import (
    Field,
    ValidationError as PydanticValidationError,
    model_validator,
)

from .contracts import canonical_contract_bytes
from .models import (
    ContractStampedModel,
    EvaluationCase,
    EvaluationStrictModel,
    _reject_explicit_null,
    _require_non_blank,
    _SHA256_HEX_PATTERN,
)
from ..universe.io_utils import sha256_bytes, sha256_text

__all__ = [
    "LoadedSourcePassageSnapshotManifest",
    "SourceDocumentRecord",
    "SourcePassageRecord",
    "SourcePassageSnapshotManifest",
    "SourceSnapshotError",
    "load_source_passage_snapshot_manifest",
    "persist_source_passage_snapshot_manifest",
    "resolve_case_source_passages",
    "source_passage_snapshot_manifest_hash",
]

_CONTRACT_ID = "source_passage_snapshot_manifest"
_CONTRACT_VERSION = "0.1.0"
_SNAPSHOTS_DIR = "snapshots"
_SNAPSHOT_FILENAME = "source_passage_snapshot_manifest.json"

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCHEMA_DIRNAME = "schemas"
_SOURCE_DOCUMENT_SCHEMA_REF = "schemas/source_document.schema.json"
_SOURCE_DOCUMENT_SCHEMA_SHA256 = (
    "87284b60ed7385ae1b459467f7c3be37f949bb3ac1dc90df2571bccc85efbe1d"
)
_SOURCE_PASSAGE_SCHEMA_REF = "schemas/source_passage.schema.json"
_SOURCE_PASSAGE_SCHEMA_SHA256 = (
    "1e53b69838367c75b829660ede160bc44ddbadc2c00da046134cfb50b4bccb3e"
)

_HEX = {"min_length": 64, "max_length": 64, "pattern": _SHA256_HEX_PATTERN}


# --- Public error ----------------------------------------------------------


class SourceSnapshotError(Exception):
    """Sanitized source-snapshot failure with a stable machine-readable code.

    No raw document content, absolute path, or raw Pydantic/OS text is placed
    in the message.
    """

    def __init__(
        self, message: str, *, reason_code: str, artifact_reference: str | None = None
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.artifact_reference = artifact_reference


# --- Private strict-parse control exceptions (content-free) ---------------


class _DuplicateKeyControl(Exception):
    def __init__(self) -> None:
        super().__init__("duplicate JSON object key")


class _NonFiniteControl(Exception):
    def __init__(self) -> None:
        super().__init__("non-JSON numeric constant")


# --- Models ---------------------------------------------------------------

_OfficialStatus = Literal["official", "official_archive", "rejected", "uncertain"]
_TemporalValidity = Literal["valid", "invalid", "uncertain"]


class SourceDocumentRecord(EvaluationStrictModel):
    """One source-document record mirroring ``source_document.schema.json``."""

    source_id: str
    company_id: str
    source_type: str
    title: str | None = None
    url: str | None = None
    archive_url: str | None = None
    publication_date: str | None
    retrieval_timestamp: str
    snapshot_timestamp: str | None = None
    content_hash: str
    mime_type: str | None = None
    official_status: _OfficialStatus
    temporal_validity: _TemporalValidity | None = None
    access_status: str | None = None
    schema_version: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_explicit_null_optional_non_null(cls, data: Any) -> Any:
        return _reject_explicit_null(
            data,
            ("url", "mime_type", "temporal_validity", "access_status", "schema_version"),
            "SourceDocumentRecord",
        )

    @model_validator(mode="after")
    def _record_invariants(self) -> "SourceDocumentRecord":
        _require_non_blank(self.source_id, "source_id")
        _require_non_blank(self.company_id, "company_id")
        _require_non_blank(self.source_type, "source_type")
        _require_non_blank(self.retrieval_timestamp, "retrieval_timestamp")
        _require_non_blank(self.content_hash, "content_hash")
        for name in ("url", "mime_type", "access_status", "schema_version"):
            value = getattr(self, name)
            if value is not None:
                _require_non_blank(value, name)
        return self


class SourcePassageRecord(EvaluationStrictModel):
    """One source-passage record mirroring ``source_passage.schema.json``."""

    passage_id: str
    source_id: str
    heading_path: tuple[str, ...] = ()
    text: str
    text_hash: str
    start_offset: int | None = None
    end_offset: int | None = None
    page: int | None = None
    normalizer_version: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_explicit_null_optional_non_null(cls, data: Any) -> Any:
        return _reject_explicit_null(
            data, ("heading_path", "normalizer_version"), "SourcePassageRecord"
        )

    @model_validator(mode="after")
    def _record_invariants(self) -> "SourcePassageRecord":
        _require_non_blank(self.passage_id, "passage_id")
        _require_non_blank(self.source_id, "source_id")
        _require_non_blank(self.text_hash, "text_hash")
        for segment in self.heading_path:
            _require_non_blank(segment, "heading_path segment")
        if self.normalizer_version is not None:
            _require_non_blank(self.normalizer_version, "normalizer_version")
        if self.text_hash != sha256_text(self.text):
            raise ValueError("text_hash must equal the SHA-256 of text")
        return self


class SourcePassageSnapshotManifest(ContractStampedModel):
    # Docstring intentionally omitted: the generated JSON Schema (and thus the
    # governed model-contract hash) must not carry a description.
    _contract_id: ClassVar[str] = _CONTRACT_ID
    _contract_version: ClassVar[str] = _CONTRACT_VERSION

    snapshot_version: str
    source_documents_reference: str
    source_documents_sha256: str = Field(**_HEX)
    source_document_count: int
    source_passages_reference: str
    source_passages_sha256: str = Field(**_HEX)
    source_passage_count: int
    aggregate_content_hash: str = Field(**_HEX)

    @model_validator(mode="after")
    def _manifest_invariants(self) -> "SourcePassageSnapshotManifest":
        _require_non_blank(self.snapshot_version, "snapshot_version")
        if not _is_safe_reference(self.source_documents_reference):
            raise ValueError("source_documents_reference is not a safe relative reference")
        if not _is_safe_reference(self.source_passages_reference):
            raise ValueError("source_passages_reference is not a safe relative reference")
        if self.source_document_count < 0 or self.source_passage_count < 0:
            raise ValueError("record counts must be non-negative")
        expected = _aggregate_content_hash(self)
        if self.aggregate_content_hash != expected:
            raise ValueError(
                "aggregate_content_hash does not match the self-excluding canonical hash"
            )
        return self


class LoadedSourcePassageSnapshotManifest(EvaluationStrictModel):
    """A validated snapshot manifest plus its resolved corpora and binding material."""

    manifest: SourcePassageSnapshotManifest
    source_documents: tuple[SourceDocumentRecord, ...]
    source_passages: tuple[SourcePassageRecord, ...]
    version: str
    sha256: str
    artifact_reference: str


class _ResolvedCaseSources(EvaluationStrictModel):
    documents: tuple[SourceDocumentRecord, ...]
    passages: tuple[SourcePassageRecord, ...]


# --- Aggregate hash + fail-closed revalidation ----------------------------


def _aggregate_content_hash(manifest: SourcePassageSnapshotManifest) -> str:
    payload = manifest.model_dump(
        mode="json", exclude_unset=True, exclude={"aggregate_content_hash"}
    )
    return sha256_bytes(canonical_contract_bytes(payload))


def _revalidate_manifest(
    manifest: SourcePassageSnapshotManifest,
) -> SourcePassageSnapshotManifest:
    if not isinstance(manifest, SourcePassageSnapshotManifest):
        raise TypeError(
            f"expected a SourcePassageSnapshotManifest, got {type(manifest).__name__}"
        )
    try:
        payload = manifest.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 - any serialization defect fails closed
        raise SourceSnapshotError(
            "source-snapshot manifest could not be serialized for revalidation",
            reason_code="model_validation",
        ) from exc
    try:
        return SourcePassageSnapshotManifest.model_validate(payload)
    except PydanticValidationError as exc:
        raise SourceSnapshotError(
            "source-snapshot manifest failed fail-closed revalidation",
            reason_code="model_validation",
        ) from exc


def source_passage_snapshot_manifest_hash(manifest: SourcePassageSnapshotManifest) -> str:
    """The authoritative aggregate content hash (fail-closed; never recursive)."""
    validated = _revalidate_manifest(manifest)
    return validated.aggregate_content_hash


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
        raise SourceSnapshotError(
            "eval_root must be an explicit str or Path evaluation root",
            reason_code="invalid_eval_root",
        )
    if isinstance(eval_root, str) and eval_root == "":
        raise SourceSnapshotError(
            "eval_root must not be an empty string; supply the evaluation root explicitly",
            reason_code="invalid_eval_root",
        )
    root = Path(eval_root)
    if root.is_symlink():
        raise SourceSnapshotError(
            "eval_root must not be a symlink", reason_code="eval_root_symlink"
        )
    if not root.exists():
        raise SourceSnapshotError(
            "evaluation root does not exist", reason_code="invalid_eval_root"
        )
    if not root.is_dir():
        raise SourceSnapshotError(
            "evaluation root is not a directory", reason_code="invalid_eval_root"
        )
    return root.resolve()


def _resolve_contained(reference: str | Path, resolved_root: Path) -> tuple[Path, str]:
    if not _is_safe_reference(reference if isinstance(reference, str) else str(reference)):
        if not isinstance(reference, (str, Path)):
            raise SourceSnapshotError(
                "reference must be an explicit str or Path", reason_code="invalid_path"
            )
        raise SourceSnapshotError(
            "reference is not a safe relative reference", reason_code="unsafe_reference"
        )
    candidate = resolved_root / Path(reference)
    if candidate.is_symlink():
        raise SourceSnapshotError(
            "artifact path is a symlink", reason_code="artifact_symlink"
        )
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise SourceSnapshotError(
            "artifact path resolves outside the evaluation root", reason_code="path_escape"
        )
    ref = resolved.relative_to(resolved_root).as_posix()
    if resolved.is_symlink():
        raise SourceSnapshotError(
            "artifact is a symlink", reason_code="artifact_symlink", artifact_reference=ref
        )
    if not resolved.exists():
        raise SourceSnapshotError(
            "artifact does not exist under the evaluation root",
            reason_code="artifact_missing",
            artifact_reference=ref,
        )
    if not resolved.is_file():
        raise SourceSnapshotError(
            "artifact is not a regular file",
            reason_code="artifact_not_a_file",
            artifact_reference=ref,
        )
    return resolved, ref


def _validate_run_id(eval_run_id: Any) -> str:
    if not isinstance(eval_run_id, str):
        raise SourceSnapshotError(
            f"eval_run_id must be a string, got {type(eval_run_id).__name__}",
            reason_code="invalid_eval_run_id",
        )
    if not eval_run_id or eval_run_id != eval_run_id.strip():
        raise SourceSnapshotError(
            "eval_run_id must be a non-empty string without leading or trailing whitespace",
            reason_code="invalid_eval_run_id",
        )
    if eval_run_id in (".", ".."):
        raise SourceSnapshotError(
            "eval_run_id is not a valid path component", reason_code="invalid_eval_run_id"
        )
    if "/" in eval_run_id or "\\" in eval_run_id or "\x00" in eval_run_id:
        raise SourceSnapshotError(
            "eval_run_id must be a single path component without separators or NUL",
            reason_code="invalid_eval_run_id",
        )
    if Path(eval_run_id).is_absolute() or len(Path(eval_run_id).parts) != 1:
        raise SourceSnapshotError(
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
        raise SourceSnapshotError(
            "artifact is not valid JSON", reason_code="json_error", artifact_reference=reference
        ) from exc
    except _DuplicateKeyControl as exc:
        raise SourceSnapshotError(
            "artifact contains a duplicate JSON object key",
            reason_code="duplicate_key",
            artifact_reference=reference,
        ) from exc
    except _NonFiniteControl as exc:
        raise SourceSnapshotError(
            "artifact contains a non-JSON numeric constant",
            reason_code="non_finite",
            artifact_reference=reference,
        ) from exc
    if _has_non_finite(payload):
        raise SourceSnapshotError(
            "artifact contains a non-finite JSON number",
            reason_code="non_finite",
            artifact_reference=reference,
        )
    if not isinstance(payload, dict):
        raise SourceSnapshotError(
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
        raise SourceSnapshotError(
            "failed to read the artifact", reason_code="read_error", artifact_reference=ref
        ) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceSnapshotError(
            "artifact is not valid UTF-8", reason_code="decode_error", artifact_reference=ref
        ) from exc
    return raw, text, ref


# --- Pinned static-schema loader (call-time only) -------------------------


def _load_static_record_validator(
    schema_ref: str, expected_sha256: str, *, repo_root: Path
) -> Draft202012Validator:
    schema_root = (repo_root / _SCHEMA_DIRNAME).resolve()
    candidate = repo_root / schema_ref
    if candidate.is_symlink():
        raise SourceSnapshotError(
            "static schema reference is a symlink", reason_code="schema_reference_unsafe"
        )
    resolved = candidate.resolve()
    if not resolved.is_relative_to(schema_root) or resolved.is_symlink():
        raise SourceSnapshotError(
            "static schema reference is unsafe", reason_code="schema_reference_unsafe"
        )
    if not resolved.is_file():
        raise SourceSnapshotError(
            "static schema file is missing", reason_code="schema_missing"
        )
    raw = resolved.read_bytes()
    if sha256_bytes(raw) != expected_sha256:
        raise SourceSnapshotError(
            "static schema file hash does not match the reviewed value",
            reason_code="schema_hash_mismatch",
        )
    try:
        schema = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceSnapshotError(
            "static schema file is not valid JSON", reason_code="schema_malformed"
        ) from exc
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise SourceSnapshotError(
            "static schema failed Draft 2020-12 meta-validation",
            reason_code="schema_meta_invalid",
        ) from exc
    checker = FormatChecker()
    return Draft202012Validator(schema, format_checker=checker)


def _parse_corpus_jsonl(
    text: str,
    reference: str,
    *,
    validator: Draft202012Validator,
    model: type[EvaluationStrictModel],
    schema_reason: str,
) -> list[Any]:
    if text == "":
        return []
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    records: list[Any] = []
    for index, line in enumerate(lines):
        if not line or not line.strip():
            raise SourceSnapshotError(
                "corpus JSONL contains a blank line",
                reason_code="jsonl_blank_line",
                artifact_reference=reference,
            )
        record = _strict_json_object(line, reference)
        errors = sorted(e.message for e in validator.iter_errors(record))
        if errors:
            raise SourceSnapshotError(
                "corpus record failed static-schema validation",
                reason_code=schema_reason,
                artifact_reference=reference,
            )
        try:
            records.append(model.model_validate(record))
        except PydanticValidationError as exc:
            raise SourceSnapshotError(
                "corpus record failed typed model validation",
                reason_code="model_validation",
                artifact_reference=reference,
            ) from exc
    return records


# --- Loader ---------------------------------------------------------------


def load_source_passage_snapshot_manifest(
    path: str | Path,
    *,
    eval_root: str | Path,
    expected_sha256: str | None = None,
    repo_root: str | Path | None = None,
) -> LoadedSourcePassageSnapshotManifest:
    """Load, hash-bind, and structurally validate a source/passage snapshot.

    Reads the manifest JSON plus both JSONL corpora (contained under
    ``eval_root``, symlink-rejected), validates each record against the pinned
    committed static schema and its typed model, binds each corpus raw-byte
    SHA-256 to the manifest, and enforces unique IDs, passage-to-source
    referential integrity, record counts, and the self-excluding aggregate
    hash. All failures are sanitized ``SourceSnapshotError``.
    """
    resolved_root = _validate_eval_root(eval_root)
    schema_repo_root = (
        _validate_eval_root(repo_root) if repo_root is not None else _REPO_ROOT
    )
    raw, text, reference = _read_contained(str(path), resolved_root)
    observed = sha256_bytes(raw)
    if expected_sha256 is not None:
        valid = (
            isinstance(expected_sha256, str)
            and len(expected_sha256) == 64
            and all(c in "0123456789abcdef" for c in expected_sha256)
        )
        if not valid or expected_sha256 != observed:
            raise SourceSnapshotError(
                "snapshot manifest raw-byte hash does not match the expected hash",
                reason_code="expected_hash_mismatch",
                artifact_reference=reference,
            )
    payload = _strict_json_object(text, reference)
    try:
        manifest = SourcePassageSnapshotManifest.model_validate(payload)
    except PydanticValidationError as exc:
        raise SourceSnapshotError(
            "snapshot manifest failed strict contract validation",
            reason_code="model_validation",
            artifact_reference=reference,
        ) from exc

    doc_validator = _load_static_record_validator(
        _SOURCE_DOCUMENT_SCHEMA_REF, _SOURCE_DOCUMENT_SCHEMA_SHA256, repo_root=schema_repo_root
    )
    passage_validator = _load_static_record_validator(
        _SOURCE_PASSAGE_SCHEMA_REF, _SOURCE_PASSAGE_SCHEMA_SHA256, repo_root=schema_repo_root
    )

    doc_raw, doc_text, doc_ref = _read_contained(
        manifest.source_documents_reference, resolved_root
    )
    if sha256_bytes(doc_raw) != manifest.source_documents_sha256:
        raise SourceSnapshotError(
            "source-documents corpus hash does not bind the manifest",
            reason_code="corpus_hash_mismatch",
            artifact_reference=doc_ref,
        )
    documents = _parse_corpus_jsonl(
        doc_text, doc_ref, validator=doc_validator, model=SourceDocumentRecord,
        schema_reason="source_document_schema_invalid",
    )
    passage_raw, passage_text, passage_ref = _read_contained(
        manifest.source_passages_reference, resolved_root
    )
    if sha256_bytes(passage_raw) != manifest.source_passages_sha256:
        raise SourceSnapshotError(
            "source-passages corpus hash does not bind the manifest",
            reason_code="corpus_hash_mismatch",
            artifact_reference=passage_ref,
        )
    passages = _parse_corpus_jsonl(
        passage_text, passage_ref, validator=passage_validator, model=SourcePassageRecord,
        schema_reason="source_passage_schema_invalid",
    )

    if len(documents) != manifest.source_document_count:
        raise SourceSnapshotError(
            "source-document count does not equal the manifest count",
            reason_code="record_count_mismatch",
            artifact_reference=doc_ref,
        )
    if len(passages) != manifest.source_passage_count:
        raise SourceSnapshotError(
            "source-passage count does not equal the manifest count",
            reason_code="record_count_mismatch",
            artifact_reference=passage_ref,
        )

    source_ids: set[str] = set()
    for document in documents:
        if document.source_id in source_ids:
            raise SourceSnapshotError(
                "duplicate source_id in the source-documents corpus",
                reason_code="duplicate_source_id",
                artifact_reference=doc_ref,
            )
        source_ids.add(document.source_id)
    passage_ids: set[str] = set()
    for passage in passages:
        if passage.passage_id in passage_ids:
            raise SourceSnapshotError(
                "duplicate passage_id in the source-passages corpus",
                reason_code="duplicate_passage_id",
                artifact_reference=passage_ref,
            )
        passage_ids.add(passage.passage_id)
        if passage.source_id not in source_ids:
            raise SourceSnapshotError(
                "source-passage references a source_id absent from the documents corpus",
                reason_code="passage_source_unresolved",
                artifact_reference=passage_ref,
            )

    return LoadedSourcePassageSnapshotManifest(
        manifest=manifest,
        source_documents=tuple(documents),
        source_passages=tuple(passages),
        version=manifest.snapshot_version,
        sha256=observed,
        artifact_reference=reference,
    )


# --- Case resolution ------------------------------------------------------


def resolve_case_source_passages(
    loaded: LoadedSourcePassageSnapshotManifest, case: EvaluationCase
) -> _ResolvedCaseSources:
    """Resolve a case's declared input sources/passages against the snapshot.

    A case-declared input source or passage absent from the governed snapshot is
    an input/snapshot binding defect (this API fails); it is never a prediction
    citation defect. A resolved required source whose ``publication_date`` is
    null invalidates the snapshot/run. Every resolved passage's ``source_id``
    must be one of the case's own ``input_source_ids``.
    """
    if not isinstance(loaded, LoadedSourcePassageSnapshotManifest):
        raise TypeError(
            f"loaded must be a LoadedSourcePassageSnapshotManifest, got {type(loaded).__name__}"
        )
    if not isinstance(case, EvaluationCase):
        raise TypeError(f"case must be an EvaluationCase, got {type(case).__name__}")
    documents_by_id = {d.source_id: d for d in loaded.source_documents}
    passages_by_id = {p.passage_id: p for p in loaded.source_passages}
    case_source_ids = set(case.input_source_ids)

    resolved_documents: list[SourceDocumentRecord] = []
    for source_id in case.input_source_ids:
        document = documents_by_id.get(source_id)
        if document is None:
            raise SourceSnapshotError(
                "case input source is not present in the snapshot",
                reason_code="case_input_source_unresolved",
                artifact_reference=loaded.artifact_reference,
            )
        if document.publication_date is None:
            raise SourceSnapshotError(
                "a resolved case input source has no governed publication date",
                reason_code="resolved_source_missing_publication_date",
                artifact_reference=loaded.artifact_reference,
            )
        resolved_documents.append(document)

    resolved_passages: list[SourcePassageRecord] = []
    for passage_id in case.input_passage_ids:
        passage = passages_by_id.get(passage_id)
        if passage is None:
            raise SourceSnapshotError(
                "case input passage is not present in the snapshot",
                reason_code="case_input_passage_unresolved",
                artifact_reference=loaded.artifact_reference,
            )
        if passage.source_id not in case_source_ids:
            raise SourceSnapshotError(
                "a resolved case passage's source_id is not declared by the case",
                reason_code="case_input_passage_unresolved",
                artifact_reference=loaded.artifact_reference,
            )
        resolved_passages.append(passage)

    resolved_documents.sort(key=lambda d: d.source_id)
    resolved_passages.sort(key=lambda p: p.passage_id)
    return _ResolvedCaseSources(
        documents=tuple(resolved_documents), passages=tuple(resolved_passages)
    )


# --- Snapshot persistence -------------------------------------------------


def persist_source_passage_snapshot_manifest(
    manifest: SourcePassageSnapshotManifest,
    *,
    eval_root: str | Path,
    eval_run_id: str,
) -> LoadedSourcePassageSnapshotManifest:
    """Write the canonical manifest JSON (plus one terminal newline) write-once.

    Destination:
    ``<eval_root>/<eval_run_id>/snapshots/source_passage_snapshot_manifest.json``.
    Only the revalidated manifest is serialized; corpora are not copied here.
    """
    validated = _revalidate_manifest(manifest)
    resolved_root = _validate_eval_root(eval_root)
    run_id = _validate_run_id(eval_run_id)
    run_dir = resolved_root / run_id
    if run_dir.is_symlink():
        raise SourceSnapshotError(
            "run directory is a symlink", reason_code="run_directory_symlink"
        )
    if not run_dir.exists():
        raise SourceSnapshotError(
            "run directory does not exist under the evaluation root",
            reason_code="run_directory_missing",
            artifact_reference=run_id,
        )
    if not run_dir.is_dir():
        raise SourceSnapshotError(
            "run directory is not a directory",
            reason_code="run_directory_not_a_directory",
            artifact_reference=run_id,
        )
    snapshots_dir = run_dir / _SNAPSHOTS_DIR
    if snapshots_dir.is_symlink():
        raise SourceSnapshotError(
            "run snapshots directory is a symlink",
            reason_code="snapshots_directory_symlink",
        )
    if snapshots_dir.exists():
        if not snapshots_dir.is_dir():
            raise SourceSnapshotError(
                "run snapshots path is not a directory",
                reason_code="snapshots_directory_not_a_directory",
            )
    else:
        try:
            snapshots_dir.mkdir(exist_ok=False)
        except OSError as exc:
            raise SourceSnapshotError(
                "failed to create the run snapshots directory",
                reason_code="write_error",
                artifact_reference=f"{run_id}/{_SNAPSHOTS_DIR}",
            ) from exc
    reference = f"{run_id}/{_SNAPSHOTS_DIR}/{_SNAPSHOT_FILENAME}"
    dest = snapshots_dir / _SNAPSHOT_FILENAME
    if dest.is_symlink() or dest.exists():
        raise SourceSnapshotError(
            "snapshot already exists; snapshots are write-once",
            reason_code="snapshot_exists",
            artifact_reference=reference,
        )
    data = canonical_contract_bytes(validated.model_dump(mode="json", exclude_unset=True)) + b"\n"
    expected = sha256_bytes(data)
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise SourceSnapshotError(
            "snapshot already exists; snapshots are write-once",
            reason_code="snapshot_exists",
            artifact_reference=reference,
        ) from exc
    except OSError as exc:
        raise SourceSnapshotError(
            "failed to create the snapshot", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise SourceSnapshotError(
            "failed to write the snapshot", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        observed = sha256_bytes(dest.read_bytes())
    except OSError as exc:
        raise SourceSnapshotError(
            "failed to re-read the snapshot for verification",
            reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    if observed != expected:
        raise SourceSnapshotError(
            "persisted snapshot re-read to a different hash",
            reason_code="destination_hash_mismatch",
            artifact_reference=reference,
        )
    return LoadedSourcePassageSnapshotManifest(
        manifest=validated,
        source_documents=(),
        source_passages=(),
        version=validated.snapshot_version,
        sha256=observed,
        artifact_reference=reference,
    )
