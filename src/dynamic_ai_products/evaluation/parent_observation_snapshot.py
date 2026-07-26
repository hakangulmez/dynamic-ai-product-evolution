"""Parent-observation snapshot (Xe0, extraction-only Rule-7 parent-availability input).

``parent_observation_snapshot@0.1.0`` is a strict, frozen, extra-forbid,
model-contract-hash-governed **pre-run input** that enumerates the authoritative
parent observation records (products, and capabilities for task runs) against
which Rule-7 (``product_capability_task_parent_resolution``) resolves declared
parent links. It exists precisely so that ``available_parent_ids`` is derived
**only** from records that *own* a parent identity — never from a child
record's own parent-reference fields.

Provenance is established through the existing prediction-artifact-manifest
chain (the snapshot file and its member artifacts are declared as
``source_artifacts`` with SHA-256, covered by the run manifest's
``prediction_run_manifest_hash`` pin); this contract introduces **no** new
run-manifest field or pin. The loader re-reads every member artifact, verifies
its SHA-256, validates it against its role's committed observation schema, and
enforces the fail-closed ownership + coherence invariants below. A child case's
``(case_id, company_id, observation_cutoff)`` context must equal this snapshot's
*validated* context (see :func:`verify_child_case_context`).

Importing this module performs no filesystem access, hashing, clock read, or
schema I/O; all loading is explicit.
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from typing import Any, ClassVar, Literal

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from pydantic import (
    Field,
    ValidationError as PydanticValidationError,
    model_validator,
)

from .contracts import model_contract_hash
from .models import ContractStampedModel, EvaluationStrictModel, _require_non_blank
from ..universe.io_utils import sha256_bytes

__all__ = [
    "LoadedParentObservationSnapshot",
    "ParentObservationSnapshot",
    "ParentObservationSnapshotError",
    "load_parent_observation_snapshot",
    "verify_child_case_context",
]

_CONTRACT_ID = "parent_observation_snapshot"
_CONTRACT_VERSION = "0.1.0"
_SHA256_HEX = r"^[0-9a-f]{64}$"

# Role → (committed observation schema relative path, expected immutable schema
# SHA-256 anchor, P2-nonblank owner-identity field). The schema anchor is
# hash-verified so no substitute schema file can stand in for the committed one.
_ROLE_SCHEMA: dict[str, tuple[str, str, str]] = {
    "product_parent": (
        "schemas/product_observation.schema.json",
        "2d2adcb0b24313c58ed27c51708e4e680e0d4c5abe099ae02788217c45cf1eae",
        "product_observation_id",
    ),
    "capability_parent": (
        "schemas/capability_observation.schema.json",
        "4ade397f3383ff756a1aa2ba5f98bdb99f76c002d5cf049d7e8dcd7abf493733",
        "capability_observation_id",
    ),
}


class ParentObservationSnapshotError(Exception):
    """Sanitized parent-snapshot failure with a stable machine-readable code.

    No raw content, absolute path, or raw jsonschema/OS text is placed in the
    message.
    """

    def __init__(
        self, message: str, *, reason_code: str, artifact_reference: str | None = None
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.artifact_reference = artifact_reference


class _DuplicateKeyControl(Exception):
    def __init__(self, key: str) -> None:
        super().__init__("duplicate JSON object key")
        self.key = key


class _NonFiniteControl(Exception):
    def __init__(self) -> None:
        super().__init__("non-JSON numeric constant")


# --- Model -----------------------------------------------------------------


class _ParentMember(EvaluationStrictModel):
    role: Literal["product_parent", "capability_parent"]
    reference: str
    sha256: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX)

    @model_validator(mode="after")
    def _member_invariants(self) -> "_ParentMember":
        if not _is_safe_reference(self.reference):
            raise ValueError("member reference must be a safe relative reference")
        return self


class ParentObservationSnapshot(ContractStampedModel):
    # Docstring intentionally omitted so the generated JSON Schema (and thus the
    # governed model-contract hash) carries no description.
    _contract_id: ClassVar[str] = _CONTRACT_ID
    _contract_version: ClassVar[str] = _CONTRACT_VERSION

    snapshot_version: str
    case_id: str
    company_id: str
    observation_cutoff: str
    members: tuple[_ParentMember, ...]

    @model_validator(mode="after")
    def _snapshot_invariants(self) -> "ParentObservationSnapshot":
        _require_non_blank(self.snapshot_version, "snapshot_version")
        # P2: case_id + company_id present and non-blank.
        _require_non_blank(self.case_id, "case_id")
        _require_non_blank(self.company_id, "company_id")
        # observation_cutoff must be a canonical ISO full-date (YYYY-MM-DD).
        if not _is_canonical_iso_date(self.observation_cutoff):
            raise ValueError("observation_cutoff must be a canonical ISO full-date (YYYY-MM-DD)")
        if not self.members:
            raise ValueError("members must not be empty")
        # Canonical strict-ascending (role, reference) order; unique (role, reference).
        keys = [(m.role, m.reference) for m in self.members]
        if keys != sorted(keys):
            raise ValueError("members must be in canonical ascending (role, reference) order")
        if len(set(keys)) != len(keys):
            raise ValueError("members must be unique by (role, reference)")
        # A reference may not appear under two different roles (no role/schema ambiguity).
        refs = [m.reference for m in self.members]
        if len(set(refs)) != len(refs):
            raise ValueError("a member reference must not appear under more than one role")
        return self


class LoadedParentObservationSnapshot(EvaluationStrictModel):
    """A validated parent-observation snapshot plus its resolved availability sets.

    ``product_parent_ids`` and ``capability_parent_ids`` are the P2-nonblank,
    context-coherent, owner-verified identities of each role — the only source
    for Rule-7 ``available_parent_ids``.
    """

    model: ParentObservationSnapshot
    version: str
    sha256: str
    artifact_reference: str
    product_parent_ids: tuple[str, ...]
    capability_parent_ids: tuple[str, ...]


# --- Helpers ---------------------------------------------------------------


def _is_safe_reference(value: Any) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if value.startswith("/") or "\\" in value or "\x00" in value:
        return False
    parts = value.split("/")
    return all(part not in ("", ".", "..") for part in parts)


def _is_canonical_iso_date(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-":
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _contract_metadata() -> dict[str, str]:
    return {
        "contract_id": _CONTRACT_ID,
        "contract_version": _CONTRACT_VERSION,
        "contract_hash": model_contract_hash(
            ParentObservationSnapshot, _CONTRACT_ID, _CONTRACT_VERSION
        ),
    }


def _validate_source_root(source_root: str | Path) -> Path:
    if not isinstance(source_root, (str, Path)):
        raise ParentObservationSnapshotError(
            "source_root must be an explicit str or Path prediction-source root",
            reason_code="invalid_source_root",
        )
    if isinstance(source_root, str) and source_root == "":
        raise ParentObservationSnapshotError(
            "source_root must not be an empty string", reason_code="invalid_source_root"
        )
    root = Path(source_root)
    if root.is_symlink():
        raise ParentObservationSnapshotError(
            "source_root must not be a symlink", reason_code="source_root_symlink"
        )
    if not root.exists() or not root.is_dir():
        raise ParentObservationSnapshotError(
            "source root does not exist or is not a directory",
            reason_code="invalid_source_root",
        )
    return root.resolve()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise _DuplicateKeyControl(key)
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


def _resolve_contained(reference: str, resolved_root: Path) -> Path:
    if not _is_safe_reference(reference):
        raise ParentObservationSnapshotError(
            "a reference is not a safe relative reference",
            reason_code="unsafe_reference", artifact_reference=reference,
        )
    candidate = resolved_root / reference
    for part in _walk_parents(candidate, resolved_root):
        if part.is_symlink():
            raise ParentObservationSnapshotError(
                "a reference path component is a symlink",
                reason_code="reference_symlink", artifact_reference=reference,
            )
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ParentObservationSnapshotError(
            "a reference resolves outside the source root",
            reason_code="path_escape", artifact_reference=reference,
        )
    if not resolved.exists():
        raise ParentObservationSnapshotError(
            "a referenced artifact does not exist",
            reason_code="artifact_missing", artifact_reference=reference,
        )
    if not resolved.is_file():
        raise ParentObservationSnapshotError(
            "a referenced artifact is not a regular file",
            reason_code="artifact_not_a_file", artifact_reference=reference,
        )
    return resolved


def _walk_parents(candidate: Path, root: Path) -> list[Path]:
    parts: list[Path] = []
    cur = candidate
    while True:
        parts.append(cur)
        if cur == root or cur.parent == cur:
            break
        cur = cur.parent
    return parts


def _strict_json_object(text: str, reference: str) -> dict[str, Any]:
    try:
        payload = json.loads(
            text, object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except json.JSONDecodeError as exc:
        raise ParentObservationSnapshotError(
            "artifact is not valid JSON", reason_code="json_error", artifact_reference=reference
        ) from exc
    except _DuplicateKeyControl as exc:
        raise ParentObservationSnapshotError(
            "artifact contains a duplicate JSON object key",
            reason_code="duplicate_key", artifact_reference=reference,
        ) from exc
    except _NonFiniteControl as exc:
        raise ParentObservationSnapshotError(
            "artifact contains a non-JSON numeric constant",
            reason_code="non_finite", artifact_reference=reference,
        ) from exc
    if _has_non_finite(payload):
        raise ParentObservationSnapshotError(
            "artifact contains a non-finite JSON number",
            reason_code="non_finite", artifact_reference=reference,
        )
    if not isinstance(payload, dict):
        raise ParentObservationSnapshotError(
            "artifact top-level value must be a JSON object",
            reason_code="top_level_type", artifact_reference=reference,
        )
    return payload


def _read_json_object(path: Path, reference: str) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ParentObservationSnapshotError(
            "failed to read a referenced artifact", reason_code="read_error",
            artifact_reference=reference,
        ) from exc
    observed = sha256_bytes(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParentObservationSnapshotError(
            "a referenced artifact is not valid UTF-8", reason_code="decode_error",
            artifact_reference=reference,
        ) from exc
    if text.startswith("\ufeff"):
        raise ParentObservationSnapshotError(
            "a referenced artifact has a UTF-8 BOM", reason_code="bom",
            artifact_reference=reference,
        )
    return _strict_json_object(text, reference), observed


_VALIDATOR_CACHE: dict[str, Draft202012Validator] = {}


def _member_schema_validator(
    schema_path: str, expected_sha256: str, reference: str
) -> Draft202012Validator:
    if schema_path in _VALIDATOR_CACHE:
        return _VALIDATOR_CACHE[schema_path]
    # The committed extraction schemas are resolved from the package/repo root
    # (independent of source_root), discovered at load time — never at import.
    schema_file = _repo_root() / schema_path
    try:
        raw = schema_file.read_bytes()
    except OSError as exc:
        raise ParentObservationSnapshotError(
            "the committed observation schema could not be read",
            reason_code="schema_load_error", artifact_reference=reference,
        ) from exc
    # Hash-verify the schema bytes against the approved static anchor before use;
    # a schema file that does not match the committed anchor never substitutes.
    if sha256_bytes(raw) != expected_sha256:
        raise ParentObservationSnapshotError(
            "the committed observation schema bytes do not match the approved anchor hash",
            reason_code="schema_anchor_mismatch", artifact_reference=reference,
        )
    try:
        schema = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ParentObservationSnapshotError(
            "the committed observation schema is not valid JSON",
            reason_code="schema_load_error", artifact_reference=reference,
        ) from exc
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ParentObservationSnapshotError(
            "the committed observation schema failed meta-validation",
            reason_code="schema_meta_invalid", artifact_reference=reference,
        ) from exc
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    _VALIDATOR_CACHE[schema_path] = validator
    return validator


def _repo_root() -> Path:
    cur = Path(__file__).resolve()
    while cur.parent != cur:
        if (cur / "schemas" / "product_observation.schema.json").is_file():
            return cur
        cur = cur.parent
    raise ParentObservationSnapshotError(
        "committed observation schemas directory not found", reason_code="schema_load_error"
    )


# --- Loader ---------------------------------------------------------------


def load_parent_observation_snapshot(
    path: str | Path, *, source_root: str | Path, expected_sha256: str | None = None
) -> LoadedParentObservationSnapshot:
    """Load a parent-observation snapshot and fail-closed on any ownership or
    coherence violation.

    ``source_root`` is the prediction-source root (the snapshot is a pre-run
    input declared in the prediction manifest's ``source_artifacts`` chain); this
    loader has no run-directory / evaluation-root semantics.

    Enforced invariants: strict JSON + safe-reference + symlink/escape rejection;
    contract-stamp validation; canonical ascending, ``(role, reference)``-unique,
    reference-unique members; P2-nonblank ``case_id``/``company_id``; canonical
    ISO ``observation_cutoff``; every member re-read + SHA-256-verified +
    validated against its role's committed observation schema (whose bytes are
    hash-verified against the approved static anchor and meta-validated); each
    owner id P2-nonblank and unique per role; every ``product_parent`` payload's
    ``company_id``/``observation_cutoff`` equal to the snapshot context; every
    ``capability_parent`` payload's ``product_observation_id`` resolving to a
    verified, nonblank ``product_parent`` owner id in the same snapshot.
    """
    resolved_root = _validate_source_root(source_root)
    if not isinstance(path, (str, Path)):
        raise ParentObservationSnapshotError(
            "path must be an explicit str or Path", reason_code="invalid_path"
        )
    reference = str(path)
    resolved = _resolve_contained(reference, resolved_root)
    payload, observed = _read_json_object(resolved, reference)
    if expected_sha256 is not None:
        valid = (
            isinstance(expected_sha256, str) and len(expected_sha256) == 64
            and all(c in "0123456789abcdef" for c in expected_sha256)
        )
        if not valid or expected_sha256 != observed:
            raise ParentObservationSnapshotError(
                "snapshot raw-byte hash does not match the expected hash",
                reason_code="expected_hash_mismatch", artifact_reference=reference,
            )
    try:
        model = ParentObservationSnapshot.model_validate(payload)
    except PydanticValidationError as exc:
        raise ParentObservationSnapshotError(
            "snapshot failed strict contract validation",
            reason_code="model_validation", artifact_reference=reference,
        ) from exc

    product_ids: list[str] = []
    capability_specs: list[tuple[str, str]] = []  # (capability_owner_id, referenced_product_id)
    for member in model.members:
        schema_path, schema_sha, owner_field = _ROLE_SCHEMA[member.role]
        member_resolved = _resolve_contained(member.reference, resolved_root)
        member_payload, member_observed = _read_json_object(member_resolved, member.reference)
        if member_observed != member.sha256:
            raise ParentObservationSnapshotError(
                "a member artifact SHA-256 does not match its declared hash",
                reason_code="member_hash_mismatch", artifact_reference=member.reference,
            )
        validator = _member_schema_validator(schema_path, schema_sha, member.reference)
        if next(iter(validator.iter_errors(member_payload)), None) is not None:
            raise ParentObservationSnapshotError(
                "a member artifact does not conform to its role's observation schema",
                reason_code="member_schema_invalid", artifact_reference=member.reference,
            )
        owner_id = member_payload.get(owner_field)
        if not isinstance(owner_id, str) or not owner_id or owner_id != owner_id.strip():
            raise ParentObservationSnapshotError(
                "a member owner identity is absent or blank",
                reason_code="owner_id_blank", artifact_reference=member.reference,
            )
        if member.role == "product_parent":
            if member_payload.get("company_id") != model.company_id:
                raise ParentObservationSnapshotError(
                    "a product-parent company_id does not equal the snapshot context",
                    reason_code="product_context_mismatch", artifact_reference=member.reference,
                )
            if member_payload.get("observation_cutoff") != model.observation_cutoff:
                raise ParentObservationSnapshotError(
                    "a product-parent observation_cutoff does not equal the snapshot context",
                    reason_code="product_context_mismatch", artifact_reference=member.reference,
                )
            product_ids.append(owner_id)
        else:  # capability_parent
            referenced_product = member_payload.get("product_observation_id")
            if not isinstance(referenced_product, str) or not referenced_product \
                    or referenced_product != referenced_product.strip():
                raise ParentObservationSnapshotError(
                    "a capability-parent product_observation_id is absent or blank",
                    reason_code="capability_product_blank", artifact_reference=member.reference,
                )
            capability_specs.append((owner_id, referenced_product))

    if len(product_ids) != len(set(product_ids)):
        raise ParentObservationSnapshotError(
            "duplicate product-parent owner id", reason_code="duplicate_owner", artifact_reference=reference
        )
    product_set = set(product_ids)
    capability_ids: list[str] = []
    for cap_owner, referenced_product in capability_specs:
        # Capability inherits its (company_id, cutoff) context via a verified product parent.
        if referenced_product not in product_set:
            raise ParentObservationSnapshotError(
                "a capability-parent product_observation_id does not resolve to a "
                "verified product parent in the same snapshot",
                reason_code="capability_context_unverified", artifact_reference=reference,
            )
        capability_ids.append(cap_owner)
    if len(capability_ids) != len(set(capability_ids)):
        raise ParentObservationSnapshotError(
            "duplicate capability-parent owner id", reason_code="duplicate_owner",
            artifact_reference=reference,
        )

    return LoadedParentObservationSnapshot(
        model=model, version=model.snapshot_version, sha256=observed, artifact_reference=reference,
        product_parent_ids=tuple(sorted(product_set)),
        capability_parent_ids=tuple(sorted(capability_ids)),
    )


def verify_child_case_context(
    loaded: LoadedParentObservationSnapshot,
    *,
    case_id: str,
    company_id: str,
    observation_cutoff: str,
) -> None:
    """Fail-closed unless the child case's ``(case_id, company_id,
    observation_cutoff)`` equals this snapshot's *validated* context.

    The snapshot context is already product/capability-chain-verified by
    :func:`load_parent_observation_snapshot`, so equality here binds the child
    to a genuinely coherent parent population — not to unverified assertions.
    """
    if not isinstance(loaded, LoadedParentObservationSnapshot):
        raise TypeError(
            f"loaded must be a LoadedParentObservationSnapshot, got {type(loaded).__name__}"
        )
    m = loaded.model
    if case_id != m.case_id or company_id != m.company_id \
            or observation_cutoff != m.observation_cutoff:
        raise ParentObservationSnapshotError(
            "child case context does not equal the validated snapshot context",
            reason_code="case_context_mismatch", artifact_reference=loaded.artifact_reference,
        )
