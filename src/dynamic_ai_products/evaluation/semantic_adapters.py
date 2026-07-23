"""Governed semantic-adapter registry and stage adapters (Slice 12D).

``evaluation_semantic_adapter_registry@0.1.0`` is a strict, frozen, extra-forbid,
contract-stamped registry of stage adapters with a deterministic selected-entry
identity (``SemanticAdapterRegistryEntry.entry_hash``, distinct from the whole
registry content hash). ``apply_semantic_adapter`` is a pure dispatch that maps
a raw prediction artifact (plus an optional repair chain) into governed
``ParsedPredictionContent``; it reads the per-case observation cutoff only from
the governed pointer ``/stage_context/observation_window/end`` and never trusts a
prediction-supplied date or cutoff.

Read-side plus pure validation, dispatch, and explicit persistence only.
Importing this module performs no filesystem access, hashing, environment
inspection, clock read, UUID generation, network, provider, or model call. The
adapter performs no filesystem/network/provider/model/clock/UUID/randomness
access (hashing supplied bytes is permitted).
"""

from __future__ import annotations

import json
import math
import os
from datetime import date
from pathlib import Path
from typing import Any, ClassVar, Literal

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
    PredictionEnvelope,
    _require_non_blank,
    _SHA256_HEX_PATTERN,
)
from .prediction_content import EvaluationStage, ParsedPredictionContent
from ..universe.io_utils import sha256_bytes

__all__ = [
    "EvaluationSemanticAdapterRegistry",
    "LoadedEvaluationSemanticAdapterRegistry",
    "SemanticAdapterError",
    "SemanticAdapterRegistryEntry",
    "apply_semantic_adapter",
    "load_semantic_adapter_registry",
    "persist_semantic_adapter_registry",
    "resolve_semantic_adapter",
    "semantic_adapter_registry_hash",
]

_CONTRACT_ID = "evaluation_semantic_adapter_registry"
_CONTRACT_VERSION = "0.1.0"
_SNAPSHOTS_DIR = "snapshots"
_SNAPSHOT_FILENAME = "semantic_adapter_registry.json"

_HEX = {"min_length": 64, "max_length": 64, "pattern": _SHA256_HEX_PATTERN}
_SupportStatus = Literal["implemented", "governed_unimplemented"]

# Per-stage governed entity-kind vocabularies for the two implemented extraction
# adapters. A payload declaring a kind outside its stage's set is wrong-stage.
_CAPABILITY_ENTITY_KINDS = frozenset({"product", "capability"})
_TASK_ENTITY_KINDS = frozenset({"task"})
_STAGE_ENTITY_KINDS: dict[str, frozenset[str]] = {
    "capability_extraction": _CAPABILITY_ENTITY_KINDS,
    "task_extraction": _TASK_ENTITY_KINDS,
}


class SemanticAdapterError(Exception):
    """Sanitized semantic-adapter failure with a stable machine-readable code."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str,
        evaluation_stage: str | None = None,
        artifact_reference: str | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.evaluation_stage = evaluation_stage
        self.artifact_reference = artifact_reference


class _DuplicateKeyControl(Exception):
    def __init__(self) -> None:
        super().__init__("duplicate JSON object key")


class _NonFiniteControl(Exception):
    def __init__(self) -> None:
        super().__init__("non-JSON numeric constant")


# --- Registry models ------------------------------------------------------


class SemanticAdapterRegistryEntry(EvaluationStrictModel):
    # Docstring intentionally omitted so the generated JSON Schema (and the
    # governed registry model-contract hash) carries no description.
    evaluation_stage: EvaluationStage
    adapter_id: str
    adapter_version: str
    output_contract_id: str
    output_contract_version: str
    output_contract_hash: str = Field(**_HEX)
    support_status: _SupportStatus

    @model_validator(mode="after")
    def _entry_invariants(self) -> "SemanticAdapterRegistryEntry":
        _require_non_blank(self.adapter_id, "adapter_id")
        _require_non_blank(self.adapter_version, "adapter_version")
        _require_non_blank(self.output_contract_id, "output_contract_id")
        _require_non_blank(self.output_contract_version, "output_contract_version")
        return self

    @property
    def entry_hash(self) -> str:
        """Deterministic SHA-256 over this entry's canonical JSON bytes."""
        validated = _revalidate_entry(self)
        return sha256_bytes(
            canonical_contract_bytes(validated.model_dump(mode="json", exclude_unset=True))
        )


class EvaluationSemanticAdapterRegistry(ContractStampedModel):
    # Docstring intentionally omitted so the generated JSON Schema (and the
    # governed model-contract hash) carries no description.
    _contract_id: ClassVar[str] = _CONTRACT_ID
    _contract_version: ClassVar[str] = _CONTRACT_VERSION

    registry_version: str
    entries: tuple[SemanticAdapterRegistryEntry, ...]

    @model_validator(mode="after")
    def _registry_invariants(self) -> "EvaluationSemanticAdapterRegistry":
        _require_non_blank(self.registry_version, "registry_version")
        stages = [e.evaluation_stage for e in self.entries]
        if stages != sorted(stages):
            raise ValueError("entries must be sorted canonically by evaluation_stage")
        if len(stages) != len(set(stages)):
            raise ValueError("entries must not contain a duplicate evaluation_stage")
        adapters = [e.adapter_id for e in self.entries]
        if len(adapters) != len(set(adapters)):
            raise ValueError("entries must not contain a duplicate adapter_id")
        return self

    @property
    def by_stage(self) -> dict[str, SemanticAdapterRegistryEntry]:
        return {e.evaluation_stage: e for e in self.entries}


class LoadedEvaluationSemanticAdapterRegistry(EvaluationStrictModel):
    """A validated registry plus its raw-byte binding material."""

    registry: EvaluationSemanticAdapterRegistry
    version: str
    sha256: str
    artifact_reference: str


# --- Fail-closed revalidation ---------------------------------------------


def _revalidate_entry(entry: SemanticAdapterRegistryEntry) -> SemanticAdapterRegistryEntry:
    if not isinstance(entry, SemanticAdapterRegistryEntry):
        raise TypeError(
            f"expected a SemanticAdapterRegistryEntry, got {type(entry).__name__}"
        )
    try:
        payload = entry.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        raise SemanticAdapterError(
            "semantic-adapter entry could not be serialized for revalidation",
            reason_code="inconsistent_registry_binding",
        ) from exc
    try:
        return SemanticAdapterRegistryEntry.model_validate(payload)
    except PydanticValidationError as exc:
        raise SemanticAdapterError(
            "semantic-adapter entry failed fail-closed revalidation",
            reason_code="inconsistent_registry_binding",
        ) from exc


def _revalidate_registry(
    registry: EvaluationSemanticAdapterRegistry,
) -> EvaluationSemanticAdapterRegistry:
    if not isinstance(registry, EvaluationSemanticAdapterRegistry):
        raise TypeError(
            f"expected an EvaluationSemanticAdapterRegistry, got {type(registry).__name__}"
        )
    try:
        payload = registry.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        raise SemanticAdapterError(
            "semantic-adapter registry could not be serialized for revalidation",
            reason_code="inconsistent_registry_binding",
        ) from exc
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if isinstance(entries, list):
        stages = [e.get("evaluation_stage") for e in entries if isinstance(e, dict)]
        present = [s for s in stages if isinstance(s, str)]
        if len(present) != len(set(present)):
            raise SemanticAdapterError(
                "semantic-adapter registry binds more than one adapter to a stage",
                reason_code="duplicate_stage",
            )
    try:
        return EvaluationSemanticAdapterRegistry.model_validate(payload)
    except PydanticValidationError as exc:
        raise SemanticAdapterError(
            "semantic-adapter registry failed fail-closed revalidation",
            reason_code="inconsistent_registry_binding",
        ) from exc


def semantic_adapter_registry_hash(registry: EvaluationSemanticAdapterRegistry) -> str:
    """Canonical semantic-content SHA-256 of the registry (no trailing newline)."""
    validated = _revalidate_registry(registry)
    return sha256_bytes(
        canonical_contract_bytes(validated.model_dump(mode="json", exclude_unset=True))
    )


def resolve_semantic_adapter(
    registry: EvaluationSemanticAdapterRegistry, evaluation_stage: str
) -> SemanticAdapterRegistryEntry:
    """Resolve exactly one governed adapter entry by stage (pure, fail-closed)."""
    if not isinstance(evaluation_stage, str):
        raise TypeError(
            f"evaluation_stage must be a string, got {type(evaluation_stage).__name__}"
        )
    validated = _revalidate_registry(registry)
    matches = [e for e in validated.entries if e.evaluation_stage == evaluation_stage]
    if not matches:
        raise SemanticAdapterError(
            "requested evaluation stage is not present in the adapter registry",
            reason_code="unknown_evaluation_stage",
            evaluation_stage=evaluation_stage,
        )
    return matches[0]


# --- Raw extraction payload (strict, extra-forbid) ------------------------


class _RawEntity(EvaluationStrictModel):
    entity_kind: str
    entity_ref: str


class _RawFieldValue(EvaluationStrictModel):
    entity_ref: str
    field_name: str
    field_value: str


class _RawEvidence(EvaluationStrictModel):
    entity_ref: str
    source_id: str
    passage_id: str
    quote: str


class _RawExtractionPayload(EvaluationStrictModel):
    predicted_entities: tuple[_RawEntity, ...]
    predicted_fields: tuple[_RawFieldValue, ...]
    cited_evidence: tuple[_RawEvidence, ...]


def _build_collections(
    payload: _RawExtractionPayload, evaluation_stage: str
) -> dict[str, Any]:
    allowed = _STAGE_ENTITY_KINDS[evaluation_stage]
    for entity in payload.predicted_entities:
        if entity.entity_kind not in allowed:
            raise SemanticAdapterError(
                "raw payload declares an entity kind not permitted for the stage",
                reason_code="wrong_stage_payload",
                evaluation_stage=evaluation_stage,
            )
    entities = sorted(
        ({"entity_kind": e.entity_kind, "entity_ref": e.entity_ref}
         for e in payload.predicted_entities),
        key=lambda d: (d["entity_kind"], d["entity_ref"]),
    )
    field_values = sorted(
        ({"entity_ref": f.entity_ref, "field_name": f.field_name, "field_value": f.field_value}
         for f in payload.predicted_fields),
        key=lambda d: (d["entity_ref"], d["field_name"], d["field_value"]),
    )
    evidence = sorted(
        ({"entity_ref": v.entity_ref, "source_id": v.source_id,
          "passage_id": v.passage_id, "quote": v.quote} for v in payload.cited_evidence),
        key=lambda d: (d["entity_ref"], d["source_id"], d["passage_id"], d["quote"]),
    )
    return {
        "entity_collection": {"completeness": "complete", "entities": entities},
        "field_value_collection": {"completeness": "complete", "field_values": field_values},
        "evidence_collection": {"completeness": "complete", "evidence": evidence},
    }


# --- Cutoff extraction (governed pointer only) ----------------------------


def _observation_cutoff(case: EvaluationCase) -> str:
    stage_context = case.stage_context
    window = stage_context.get("observation_window") if isinstance(stage_context, dict) else None
    if not isinstance(window, dict) or "end" not in window:
        raise SemanticAdapterError(
            "case observation window end is missing",
            reason_code="observation_cutoff_missing",
        )
    end = window["end"]
    if end is None:
        raise SemanticAdapterError(
            "case observation window end is explicit null",
            reason_code="observation_cutoff_null",
        )
    if not isinstance(end, str):
        raise SemanticAdapterError(
            "case observation window end is not a string",
            reason_code="observation_cutoff_type",
        )
    try:
        parsed = date.fromisoformat(end)
    except ValueError as exc:
        raise SemanticAdapterError(
            "case observation window end is not a valid ISO date",
            reason_code="observation_cutoff_malformed",
        ) from exc
    if parsed.isoformat() != end:
        raise SemanticAdapterError(
            "case observation window end is not a canonical ISO date",
            reason_code="observation_cutoff_malformed",
        )
    return end


# --- Strict JSON helpers --------------------------------------------------


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


def _parse_effective_payload(raw: bytes, *, kind: str) -> _RawExtractionPayload:
    decode_code = f"{kind}_decode"
    malformed_code = f"{kind}_malformed"
    top_level_code = f"{kind}_top_level_type"
    json_code = f"{kind}_json"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SemanticAdapterError("raw payload is not valid UTF-8", reason_code=decode_code) from exc
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except json.JSONDecodeError as exc:
        raise SemanticAdapterError("raw payload is not valid JSON", reason_code=json_code) from exc
    except _DuplicateKeyControl as exc:
        raise SemanticAdapterError(
            "raw payload contains a duplicate JSON object key", reason_code=json_code
        ) from exc
    except _NonFiniteControl as exc:
        raise SemanticAdapterError(
            "raw payload contains a non-JSON numeric constant", reason_code=json_code
        ) from exc
    if _has_non_finite(payload):
        raise SemanticAdapterError(
            "raw payload contains a non-finite JSON number", reason_code=json_code
        )
    if not isinstance(payload, dict):
        raise SemanticAdapterError(
            "raw payload top-level value must be a JSON object", reason_code=top_level_code
        )
    try:
        return _RawExtractionPayload.model_validate(payload)
    except PydanticValidationError as exc:
        raise SemanticAdapterError(
            "raw payload does not match the strict stage payload contract",
            reason_code=malformed_code,
        ) from exc


def _is_safe_reference(value: Any) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if "\\" in value or "\x00" in value:
        return False
    if Path(value).is_absolute():
        return False
    return all(part not in ("", ".", "..") for part in value.split("/"))


# --- Public adapter dispatch ----------------------------------------------


def apply_semantic_adapter(
    registry: EvaluationSemanticAdapterRegistry,
    *,
    case: EvaluationCase,
    envelope: PredictionEnvelope,
    raw_artifact_reference: str,
    raw_artifact_bytes: bytes,
    repair_records: tuple[tuple[str, bytes], ...] = (),
) -> ParsedPredictionContent:
    """Deterministically parse a raw prediction artifact into governed content.

    Pure with respect to filesystem/network/clock/provider/model state; hashing
    supplied bytes is permitted. The evaluation stage is derived only from the
    matching ``case.stage == envelope.stage``; the original raw-artifact identity
    is preserved even when a repair chain is supplied; the observation cutoff is
    read only from ``/stage_context/observation_window/end``.
    """
    _revalidate_registry(registry)
    if not isinstance(case, EvaluationCase):
        raise TypeError(f"case must be an EvaluationCase, got {type(case).__name__}")
    if not isinstance(envelope, PredictionEnvelope):
        raise TypeError(f"envelope must be a PredictionEnvelope, got {type(envelope).__name__}")
    if not isinstance(raw_artifact_bytes, (bytes, bytearray)):
        raise TypeError("raw_artifact_bytes must be bytes")
    # Fail-closed revalidate case + envelope. ``exclude_unset`` preserves the
    # committed optional-but-non-null identity semantics (an omitted optional
    # field must not round-trip as an explicit null).
    try:
        case = EvaluationCase.model_validate(case.model_dump(mode="json", exclude_unset=True))
        envelope = PredictionEnvelope.model_validate(
            envelope.model_dump(mode="json", exclude_unset=True)
        )
    except PydanticValidationError as exc:
        raise SemanticAdapterError(
            "case or envelope failed fail-closed revalidation", reason_code="model_validation"
        ) from exc

    if case.stage != envelope.stage:
        raise SemanticAdapterError(
            "case stage does not match envelope stage",
            reason_code="stage_mismatch", evaluation_stage=case.stage,
        )
    evaluation_stage = case.stage
    entry = resolve_semantic_adapter(registry, evaluation_stage)
    if entry.support_status != "implemented" or evaluation_stage not in _STAGE_ENTITY_KINDS:
        raise SemanticAdapterError(
            "requested evaluation stage has no implemented semantic adapter",
            reason_code="adapter_stage_unimplemented", evaluation_stage=evaluation_stage,
        )

    if not _is_safe_reference(raw_artifact_reference):
        raise SemanticAdapterError(
            "raw_artifact_reference is not a safe relative reference",
            reason_code="unsafe_reference",
        )
    occurrences = sum(1 for r in envelope.source_references if r == raw_artifact_reference)
    if occurrences == 0:
        raise SemanticAdapterError(
            "raw_artifact_reference is not declared by the envelope",
            reason_code="raw_reference_undeclared",
        )
    if occurrences > 1:
        raise SemanticAdapterError(
            "raw_artifact_reference occurs more than once in the envelope",
            reason_code="raw_reference_collision",
        )

    raw_artifact_sha256 = sha256_bytes(bytes(raw_artifact_bytes))
    repair_refs: list[str] = []
    repair_hashes: list[str] = []
    effective = bytes(raw_artifact_bytes)
    if repair_records:
        seen_refs: set[str] = set()
        for ref, payload_bytes in repair_records:
            if not _is_safe_reference(ref):
                raise SemanticAdapterError(
                    "repair reference is not a safe relative reference",
                    reason_code="unsafe_reference",
                )
            if ref in seen_refs:
                raise SemanticAdapterError(
                    "repair references must be unique", reason_code="repair_reference_collision"
                )
            if not isinstance(payload_bytes, (bytes, bytearray)):
                raise TypeError("repair record bytes must be bytes")
            seen_refs.add(ref)
            repair_refs.append(ref)
            repair_hashes.append(sha256_bytes(bytes(payload_bytes)))
        effective = bytes(repair_records[-1][1])
        payload_kind = "repair_artifact"
    else:
        payload_kind = "raw_artifact"

    payload = _parse_effective_payload(effective, kind=payload_kind)
    observation_cutoff = _observation_cutoff(case)
    collections = _build_collections(payload, evaluation_stage)

    document = {
        "contract": {
            "contract_id": entry.output_contract_id,
            "contract_version": entry.output_contract_version,
            "contract_hash": entry.output_contract_hash,
        },
        "case_id": case.case_id,
        "stage": evaluation_stage,
        "prediction_record_id": envelope.prediction_record_id,
        "input_packet_hash": envelope.input_packet_hash,
        "observation_cutoff": observation_cutoff,
        "raw_artifact_reference": raw_artifact_reference,
        "raw_artifact_sha256": raw_artifact_sha256,
        "raw_output_preserved": True,
        "repair_applied": bool(repair_records),
        "repair_record_references": repair_refs,
        "repair_record_hashes": repair_hashes,
        **collections,
    }
    try:
        return ParsedPredictionContent.model_validate(document)
    except PydanticValidationError as exc:
        message = str(exc)
        if "field_entity_unresolved" in message:
            raise SemanticAdapterError(
                "a field value references an unknown entity",
                reason_code="field_entity_unresolved", evaluation_stage=evaluation_stage,
            ) from exc
        if "evidence_entity_unresolved" in message:
            raise SemanticAdapterError(
                "an evidence item references an unknown entity",
                reason_code="evidence_entity_unresolved", evaluation_stage=evaluation_stage,
            ) from exc
        raise SemanticAdapterError(
            "assembled parsed content failed contract validation",
            reason_code=f"{payload_kind}_malformed", evaluation_stage=evaluation_stage,
        ) from exc


# --- Loader / persistence -------------------------------------------------


def _validate_eval_root(eval_root: str | Path) -> Path:
    if not isinstance(eval_root, (str, Path)):
        raise SemanticAdapterError(
            "eval_root must be an explicit str or Path evaluation root",
            reason_code="invalid_eval_root",
        )
    if isinstance(eval_root, str) and eval_root == "":
        raise SemanticAdapterError(
            "eval_root must not be an empty string", reason_code="invalid_eval_root"
        )
    root = Path(eval_root)
    if root.is_symlink():
        raise SemanticAdapterError(
            "eval_root must not be a symlink", reason_code="eval_root_symlink"
        )
    if not root.exists():
        raise SemanticAdapterError(
            "evaluation root does not exist", reason_code="invalid_eval_root"
        )
    if not root.is_dir():
        raise SemanticAdapterError(
            "evaluation root is not a directory", reason_code="invalid_eval_root"
        )
    return root.resolve()


def _resolve_contained(reference: str | Path, resolved_root: Path) -> tuple[Path, str]:
    if not isinstance(reference, (str, Path)):
        raise SemanticAdapterError(
            "reference must be an explicit str or Path", reason_code="invalid_path"
        )
    if not _is_safe_reference(str(reference)):
        raise SemanticAdapterError(
            "reference is not a safe relative reference", reason_code="unsafe_reference"
        )
    candidate = resolved_root / Path(reference)
    if candidate.is_symlink():
        raise SemanticAdapterError("artifact path is a symlink", reason_code="artifact_symlink")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise SemanticAdapterError(
            "artifact path resolves outside the evaluation root", reason_code="path_escape"
        )
    ref = resolved.relative_to(resolved_root).as_posix()
    if resolved.is_symlink():
        raise SemanticAdapterError(
            "artifact is a symlink", reason_code="artifact_symlink", artifact_reference=ref
        )
    if not resolved.exists():
        raise SemanticAdapterError(
            "artifact does not exist under the evaluation root",
            reason_code="artifact_missing", artifact_reference=ref,
        )
    if not resolved.is_file():
        raise SemanticAdapterError(
            "artifact is not a regular file",
            reason_code="artifact_not_a_file", artifact_reference=ref,
        )
    return resolved, ref


def _validate_run_id(eval_run_id: Any) -> str:
    if not isinstance(eval_run_id, str):
        raise SemanticAdapterError(
            f"eval_run_id must be a string, got {type(eval_run_id).__name__}",
            reason_code="invalid_eval_run_id",
        )
    if not eval_run_id or eval_run_id != eval_run_id.strip():
        raise SemanticAdapterError(
            "eval_run_id must be a non-empty single path component",
            reason_code="invalid_eval_run_id",
        )
    if eval_run_id in (".", ".."):
        raise SemanticAdapterError(
            "eval_run_id is not a valid path component", reason_code="invalid_eval_run_id"
        )
    if "/" in eval_run_id or "\\" in eval_run_id or "\x00" in eval_run_id:
        raise SemanticAdapterError(
            "eval_run_id must be a single path component without separators or NUL",
            reason_code="invalid_eval_run_id",
        )
    if Path(eval_run_id).is_absolute() or len(Path(eval_run_id).parts) != 1:
        raise SemanticAdapterError(
            "eval_run_id must be exactly one relative path component",
            reason_code="invalid_eval_run_id",
        )
    return eval_run_id


def load_semantic_adapter_registry(
    path: str | Path,
    *,
    eval_root: str | Path,
    expected_sha256: str | None = None,
) -> LoadedEvaluationSemanticAdapterRegistry:
    """Load, hash-bind, and strictly validate one semantic-adapter registry."""
    resolved_root = _validate_eval_root(eval_root)
    resolved, reference = _resolve_contained(str(path), resolved_root)
    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        raise SemanticAdapterError(
            "failed to read the adapter registry", reason_code="read_error",
            artifact_reference=reference,
        ) from exc
    observed = sha256_bytes(raw)
    if expected_sha256 is not None:
        valid = (
            isinstance(expected_sha256, str) and len(expected_sha256) == 64
            and all(c in "0123456789abcdef" for c in expected_sha256)
        )
        if not valid or expected_sha256 != observed:
            raise SemanticAdapterError(
                "adapter registry raw-byte hash does not match the expected hash",
                reason_code="expected_hash_mismatch", artifact_reference=reference,
            )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SemanticAdapterError(
            "adapter registry is not valid UTF-8", reason_code="decode_error",
            artifact_reference=reference,
        ) from exc
    try:
        payload = json.loads(
            text, object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except json.JSONDecodeError as exc:
        raise SemanticAdapterError(
            "adapter registry is not valid JSON", reason_code="json_error",
            artifact_reference=reference,
        ) from exc
    except _DuplicateKeyControl as exc:
        raise SemanticAdapterError(
            "adapter registry contains a duplicate JSON object key",
            reason_code="duplicate_key", artifact_reference=reference,
        ) from exc
    except _NonFiniteControl as exc:
        raise SemanticAdapterError(
            "adapter registry contains a non-JSON numeric constant",
            reason_code="non_finite", artifact_reference=reference,
        ) from exc
    if _has_non_finite(payload):
        raise SemanticAdapterError(
            "adapter registry contains a non-finite JSON number",
            reason_code="non_finite", artifact_reference=reference,
        )
    if not isinstance(payload, dict):
        raise SemanticAdapterError(
            "adapter registry top-level value must be a JSON object",
            reason_code="top_level_type", artifact_reference=reference,
        )
    try:
        registry = EvaluationSemanticAdapterRegistry.model_validate(payload)
    except PydanticValidationError as exc:
        raise SemanticAdapterError(
            "adapter registry failed strict contract validation",
            reason_code="model_validation", artifact_reference=reference,
        ) from exc
    return LoadedEvaluationSemanticAdapterRegistry(
        registry=registry, version=registry.registry_version, sha256=observed,
        artifact_reference=reference,
    )


def persist_semantic_adapter_registry(
    registry: EvaluationSemanticAdapterRegistry,
    *,
    eval_root: str | Path,
    eval_run_id: str,
) -> LoadedEvaluationSemanticAdapterRegistry:
    """Write the canonical registry JSON (plus one terminal newline) write-once."""
    validated = _revalidate_registry(registry)
    resolved_root = _validate_eval_root(eval_root)
    run_id = _validate_run_id(eval_run_id)
    run_dir = resolved_root / run_id
    if run_dir.is_symlink():
        raise SemanticAdapterError(
            "run directory is a symlink", reason_code="run_directory_symlink"
        )
    if not run_dir.exists():
        raise SemanticAdapterError(
            "run directory does not exist under the evaluation root",
            reason_code="run_directory_missing", artifact_reference=run_id,
        )
    if not run_dir.is_dir():
        raise SemanticAdapterError(
            "run directory is not a directory",
            reason_code="run_directory_not_a_directory", artifact_reference=run_id,
        )
    snapshots_dir = run_dir / _SNAPSHOTS_DIR
    if snapshots_dir.is_symlink():
        raise SemanticAdapterError(
            "run snapshots directory is a symlink", reason_code="snapshots_directory_symlink"
        )
    if snapshots_dir.exists():
        if not snapshots_dir.is_dir():
            raise SemanticAdapterError(
                "run snapshots path is not a directory",
                reason_code="snapshots_directory_not_a_directory",
            )
    else:
        try:
            snapshots_dir.mkdir(exist_ok=False)
        except OSError as exc:
            raise SemanticAdapterError(
                "failed to create the run snapshots directory", reason_code="write_error",
                artifact_reference=f"{run_id}/{_SNAPSHOTS_DIR}",
            ) from exc
    reference = f"{run_id}/{_SNAPSHOTS_DIR}/{_SNAPSHOT_FILENAME}"
    dest = snapshots_dir / _SNAPSHOT_FILENAME
    if dest.is_symlink() or dest.exists():
        raise SemanticAdapterError(
            "adapter registry already exists; snapshots are write-once",
            reason_code="snapshot_exists", artifact_reference=reference,
        )
    data = canonical_contract_bytes(validated.model_dump(mode="json", exclude_unset=True)) + b"\n"
    expected = sha256_bytes(data)
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise SemanticAdapterError(
            "adapter registry already exists; snapshots are write-once",
            reason_code="snapshot_exists", artifact_reference=reference,
        ) from exc
    except OSError as exc:
        raise SemanticAdapterError(
            "failed to create the adapter registry snapshot", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise SemanticAdapterError(
            "failed to write the adapter registry snapshot", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        observed = sha256_bytes(dest.read_bytes())
    except OSError as exc:
        raise SemanticAdapterError(
            "failed to re-read the adapter registry snapshot for verification",
            reason_code="write_error", artifact_reference=reference,
        ) from exc
    if observed != expected:
        raise SemanticAdapterError(
            "persisted adapter registry snapshot re-read to a different hash",
            reason_code="destination_hash_mismatch", artifact_reference=reference,
        )
    return LoadedEvaluationSemanticAdapterRegistry(
        registry=validated, version=validated.registry_version, sha256=observed,
        artifact_reference=reference,
    )
