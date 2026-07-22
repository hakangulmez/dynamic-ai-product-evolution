"""Compatibility readers and bridge re-evaluation coordination (Slice 12).

Governing: SPEC-024, ADR-012, ADR-020.

Two independent capabilities, both greenfield and module-local:

1. Explicit-version historical readers for ``evaluation_result@0.1.0`` (the
   pre-ADR-019 ``decision``/``conditional_pass`` shape) and
   ``universe_run_manifest`` v1/v2 (identical shapes differing only by the
   ``eval_report_ids`` deprecation annotation). Readers validate against the
   pinned committed static schema (loaded module-locally by path + expected
   SHA-256, never through the frozen evaluation registry) and then a
   schema-exact strict typed model. Readers persist nothing and mutate no
   input.

2. A pure pairwise validator/scoring bridge coordinator. Given a predeclared
   ``BridgeRequest`` (a fixed ``validator_bridge_baseline`` role, one shared
   new contract, an authoritative assertion-contract snapshot, and two source
   prediction runs) and a trusted in-process ``BridgeSideExecutor``, it
   produces two ordinary bridge evaluation runs' verified comparator inputs so
   a later Slice 11 comparison can be run. The coordinator persists nothing;
   the future Slice 13 executor is the component that creates the ordinary
   Slice 5-10 runs.

Trust boundary (locked): ``BridgeSideExecutor`` is a trusted in-process
implementation component; arbitrary third-party/adversarial executors are
unsupported. The coordinator performs input anchoring against the predeclared
trusted shared contract / side request / assertion snapshot, cross-artifact
binding, structural validation, and wrapper-hash *self-consistency* where the
committed persistence encoding is reproducible. It does NOT independently
authenticate executor-produced result/outcome source files, because no
independent trusted output anchor exists. A ``BridgeSideComparisonBundle`` is a
detached, alias-isolated, deeply immutable, cross-bound *capture*; its
component *fingerprints* protect that capture from later mutation and are not
artifact-authenticity claims. Artifact SHA (the wrapper's own recorded
``sha256``) and bundle component fingerprint are distinct concepts over
distinct bytes and are named separately throughout.

Importing this module performs no filesystem access, schema loading, hashing,
clock, UUID, or randomness.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol, runtime_checkable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    ValidationError as PydanticValidationError,
    model_validator,
)

from .assertions import LoadedAssertionOutcomes
from .comparator import (
    AssertionComparisonMetadata,
    AssertionComparisonMetadataEntry,
    ComparisonInputPacketSnapshot,
)
from .contracts import canonical_contract_bytes, model_contract_hash
from .gates import LoadedEvaluationResult
from .references import CaseResolution
from .runs import LoadedEvaluationRunManifest
from .scoring_config import LoadedScoringGateConfig
from ..universe.io_utils import sha256_bytes

# --- Constants ------------------------------------------------------------

_BRIDGE_ROLE = "validator_bridge_baseline"
_METADATA_MAPPING_VERSION = "0.1.0"
_METADATA_FAILURE_TAXONOMY_VERSION = "0.1.0"
_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"

# (contract_id, contract_version) -> (relative schema path, expected SHA-256).
_HISTORICAL_ROUTES: dict[tuple[str, str], tuple[str, str]] = {
    ("evaluation_result", "0.1.0"): (
        "schemas/evaluation_result.schema.json",
        "2fae7b2305c041ed9062d272929bb67589aaf4f5ea0d7503fe4b56b87a480453",
    ),
    ("universe_run_manifest", "0.1.0"): (
        "schemas/universe_run_manifest.schema.json",
        "a28d920f06bfe3fb90ec13ad7fb69a9d6e2b30e3f711b326c5511609cc507c1b",
    ),
    ("universe_run_manifest", "0.2.0"): (
        "schemas/universe_run_manifest.v2.schema.json",
        "da54fe4079c2d0fa3f14266db52649add20b7762290360340bcceec58a9bc54b",
    ),
}


# --- Exceptions -----------------------------------------------------------


class CompatError(Exception):
    """Abstract base for Slice 12 compatibility failures; never raised directly."""


class CompatUnsupportedVersionError(CompatError):
    """The supplied contract version is not a governed compatibility route."""


class CompatSchemaRootError(CompatError):
    """The supplied schema root is missing, a symlink, or not a directory."""


class CompatSchemaMissingError(CompatError):
    """A pinned historical schema file does not exist."""


class CompatSchemaNotAFileError(CompatError):
    """A pinned historical schema path is a symlink or not a regular file."""


class CompatSchemaReadError(CompatError):
    """Reading a pinned historical schema failed."""


class CompatSchemaHashMismatchError(CompatError):
    """A pinned historical schema's bytes do not match the expected SHA-256."""


class CompatDecodeError(CompatError):
    """A payload's bytes are not valid UTF-8."""


class CompatJsonError(CompatError):
    """A payload is not acceptable strict JSON."""


class CompatTopLevelTypeError(CompatError):
    """A parsed payload is not a JSON object / has a non-string key or nonfinite."""


class CompatSchemaValidationError(CompatError):
    """A historical document failed static-schema or strict-model validation."""


class BridgeRequestError(CompatError):
    """A bridge request is structurally invalid or internally inconsistent."""


class BridgeSideBindingError(CompatError):
    """A raw side result does not bind its request/shared-contract/snapshot."""


class BridgeMetadataError(CompatError):
    """Assertion-comparison metadata cannot be derived from the predeclared snapshot."""


class BridgeSideExecutionError(CompatError):
    """A trusted side executor declared an execution failure for one side."""

    __slots__ = ("_failed_side",)

    def __init__(self, *, failed_side: Literal["baseline", "candidate"]) -> None:
        super().__init__("bridge side execution failure")
        object.__setattr__(self, "_failed_side", failed_side)

    @property
    def failed_side(self) -> Literal["baseline", "candidate"]:
        return self._failed_side


class BridgePartialFailureError(CompatError):
    """The candidate side failed after the baseline side completed and was captured.

    Carries the immutable baseline bundle and a finite sanitized failure kind.
    No raw executor exception object, message, traceback, path, or provider
    detail is retained; ``__cause__`` and ``__context__`` are ``None``. The
    declared attributes below are read-only. Absolute exception-instance
    immutability is not claimed: because ``BaseException`` provides a
    ``__dict__``, arbitrary new attributes can still be added to the instance.
    """

    __slots__ = ("_completed_baseline", "_failed_side", "_failure_kind")

    def __init__(
        self,
        *,
        completed_baseline: "BridgeSideComparisonBundle",
        failure_kind: Literal["execution_failure", "binding_failure", "metadata_failure"],
    ) -> None:
        super().__init__(f"bridge candidate {failure_kind}")
        object.__setattr__(self, "_completed_baseline", completed_baseline)
        object.__setattr__(self, "_failed_side", "candidate")
        object.__setattr__(self, "_failure_kind", failure_kind)

    @property
    def completed_baseline(self) -> "BridgeSideComparisonBundle":
        return self._completed_baseline

    @property
    def failed_side(self) -> Literal["candidate"]:
        return self._failed_side

    @property
    def failure_kind(self) -> Literal["execution_failure", "binding_failure", "metadata_failure"]:
        return self._failure_kind


class _DuplicateKeyControl(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


class _NonFiniteControl(Exception):
    def __init__(self) -> None:
        super().__init__("nonfinite")


# --- Deeply immutable JSON representation (private) ------------------------


class _FrozenMap(Mapping):
    """A read-only mapping backed by a sorted tuple of (key, value) pairs."""

    __slots__ = ("_pairs",)

    def __init__(self, pairs: tuple[tuple[str, Any], ...]) -> None:
        object.__setattr__(self, "_pairs", pairs)

    def __getitem__(self, key: str) -> Any:
        for existing_key, value in self._pairs:
            if existing_key == key:
                return value
        raise KeyError(key)

    def __iter__(self):
        return (key for key, _ in self._pairs)

    def __len__(self) -> int:
        return len(self._pairs)

    def __hash__(self) -> int:
        return hash(self._pairs)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _FrozenMap) and self._pairs == other._pairs

    def __repr__(self) -> str:
        return f"_FrozenMap({dict(self._pairs)!r})"


def _freeze_json(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number is not permitted")
        return value
    if isinstance(value, Mapping):
        pairs = []
        for key, sub in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            pairs.append((key, _freeze_json(sub)))
        return _FrozenMap(tuple(sorted(pairs, key=lambda kv: kv[0])))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    raise ValueError(f"value of type {type(value).__name__} is not valid JSON")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, _FrozenMap):
        return {key: _thaw_json(sub) for key, sub in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _freeze_object(value: Any) -> _FrozenMap:
    if not isinstance(value, Mapping):
        raise ValueError("value must be a JSON object")
    return _freeze_json(value)


def _freeze_array(value: Any) -> tuple[Any, ...]:
    if isinstance(value, Mapping) or isinstance(value, (str, bytes)):
        raise ValueError("value must be a JSON array")
    if not isinstance(value, (list, tuple)):
        raise ValueError("value must be a JSON array")
    return tuple(_freeze_json(item) for item in value)


def _freeze_str_map(value: Any) -> _FrozenMap:
    if not isinstance(value, Mapping):
        raise ValueError("value must be a JSON object")
    pairs = []
    for key, sub in value.items():
        if not isinstance(key, str):
            raise ValueError("object keys must be strings")
        if not isinstance(sub, str):
            raise ValueError("object values must be strings")
        pairs.append((key, sub))
    return _FrozenMap(tuple(sorted(pairs, key=lambda kv: kv[0])))


def _freeze_int_map(value: Any) -> _FrozenMap:
    if not isinstance(value, Mapping):
        raise ValueError("value must be a JSON object")
    pairs = []
    for key, sub in value.items():
        if not isinstance(key, str):
            raise ValueError("object keys must be strings")
        if isinstance(sub, bool) or not isinstance(sub, int) or sub < 0:
            raise ValueError("object values must be non-negative non-bool integers")
        pairs.append((key, sub))
    return _FrozenMap(tuple(sorted(pairs, key=lambda kv: kv[0])))


_FrozenJsonObject = Annotated[
    Any, BeforeValidator(_freeze_object), PlainSerializer(_thaw_json, when_used="json")
]
_FrozenJsonArray = Annotated[
    Any, BeforeValidator(_freeze_array), PlainSerializer(_thaw_json, when_used="json")
]
_FrozenStrMap = Annotated[
    Any, BeforeValidator(_freeze_str_map), PlainSerializer(_thaw_json, when_used="json")
]
_FrozenIntMap = Annotated[
    Any, BeforeValidator(_freeze_int_map), PlainSerializer(_thaw_json, when_used="json")
]


# --- Strict base + helpers ------------------------------------------------


class _CompatStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)


def _require_non_blank(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(
            f"{field_name} must be a non-empty string without leading or trailing whitespace"
        )
    return value


def _is_lower_hex64(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _reject_null(data: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(data, Mapping):
        for key in keys:
            if key in data and data[key] is None:
                raise ValueError(f"{key} must not be explicit JSON null; omit the property instead")
    return data


# --- Historical evaluation-result models ----------------------------------


class HistoricalEvaluationResultV1(_CompatStrictModel):
    """The pre-ADR-019 ``evaluation_result@0.1.0`` document, read-only."""

    eval_run_id: str
    stage: str
    dataset_version: str
    metrics: _FrozenJsonObject
    decision: Literal["pass", "conditional_pass", "fail"]
    errors: _FrozenJsonArray | None = None
    reviewer_notes: str | None = None
    created_at: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_forbidden_null(cls, data: Any) -> Any:
        return _reject_null(data, ("errors", "created_at"))


class LoadedHistoricalEvaluationResult(_CompatStrictModel):
    contract_version: Literal["0.1.0"]
    document: HistoricalEvaluationResultV1
    source_sha256: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    schema_sha256: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)

    def to_mapping(self) -> dict[str, Any]:
        """Return a fresh ordinary mapping of the historical document."""
        return self.document.model_dump(mode="json", exclude_unset=True)


# --- Historical universe-run-manifest models ------------------------------


class UniverseRunManifestDocument(_CompatStrictModel):
    """Shared ``universe_run_manifest`` document model (v1 and v2)."""

    run_id: str
    universe_version: str
    baseline_cutoff: str
    form_scope: tuple[str, ...]
    candidate_frame_hash: str
    taxonomy_version: str
    sample_rules_version: str
    schema_versions: _FrozenStrMap
    run_timestamp: str
    counts: _FrozenIntMap
    hard_gate_status: Literal["pass", "fail", "not_run"]
    output_hashes: _FrozenStrMap
    source_manifest_hash: str | None = None
    code_revision: str | None = None
    packet_builder_version: str | None = None
    screen_prompt_hash: str | None = None
    classification_prompt_hash: str | None = None
    model_routes: tuple[str, ...] | None = None
    negative_audit_seed: int | None = None
    eval_report_ids: tuple[str, ...] | None = None
    manual_review_complete: bool | None = None
    limitations: tuple[str, ...] | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_forbidden_null(cls, data: Any) -> Any:
        return _reject_null(
            data, ("model_routes", "eval_report_ids", "manual_review_complete", "limitations")
        )

    @model_validator(mode="after")
    def _strict_seed(self) -> "UniverseRunManifestDocument":
        if self.negative_audit_seed is not None and isinstance(self.negative_audit_seed, bool):
            raise ValueError("negative_audit_seed must not be a boolean")
        return self


class LoadedUniverseRunManifest(_CompatStrictModel):
    contract_version: Literal["0.1.0", "0.2.0"]
    document: UniverseRunManifestDocument
    source_sha256: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    schema_sha256: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)

    def to_mapping(self) -> dict[str, Any]:
        return self.document.model_dump(mode="json", exclude_unset=True)


# --- Strict payload parsing + pinned schema loading -----------------------


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


def _require_string_keys(payload: Any) -> None:
    stack = [payload]
    while stack:
        value = stack.pop()
        if isinstance(value, Mapping):
            for key, sub in value.items():
                if not isinstance(key, str):
                    raise CompatTopLevelTypeError("payload object keys must be strings")
                stack.append(sub)
        elif isinstance(value, (list, tuple)):
            stack.extend(value)


def _mapping_has_non_finite(payload: Any) -> bool:
    stack = [payload]
    while stack:
        value = stack.pop()
        if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
            continue
        if isinstance(value, float):
            if not math.isfinite(value):
                return True
        elif isinstance(value, Mapping):
            stack.extend(value.values())
        elif isinstance(value, (list, tuple)):
            stack.extend(value)
    return False


def _parse_payload(payload: bytes | str | Mapping[str, object]) -> tuple[dict[str, Any], str]:
    """Return (top-level object, source_sha256). Never mutates a Mapping input."""
    if isinstance(payload, Mapping):
        _require_string_keys(payload)
        if _mapping_has_non_finite(payload):
            raise CompatJsonError("payload contains a non-finite number")
        frozen = _freeze_json(payload)  # deep copy into immutable representation
        obj = _thaw_json(frozen)
        if not isinstance(obj, dict):
            raise CompatTopLevelTypeError("payload must be a JSON object")
        source_sha = sha256_bytes(canonical_contract_bytes(obj))
        return obj, source_sha
    if isinstance(payload, (bytes, str)):
        raw = payload if isinstance(payload, bytes) else payload.encode("utf-8")
        source_sha = sha256_bytes(raw)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CompatDecodeError("payload is not valid UTF-8") from exc
        if text.startswith("\ufeff"):
            raise CompatJsonError("payload has a UTF-8 BOM")
        try:
            obj = json.loads(
                text,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_non_finite_constant,
            )
        except json.JSONDecodeError as exc:
            raise CompatJsonError(f"payload is not valid JSON: {exc.msg}") from exc
        except _DuplicateKeyControl as exc:
            raise CompatJsonError(f"payload has duplicate key {exc.key!r}") from exc
        except _NonFiniteControl as exc:
            raise CompatJsonError("payload has a non-JSON constant") from exc
        if _has_non_finite(obj):
            raise CompatJsonError("payload has a non-finite number")
        if not isinstance(obj, dict):
            raise CompatTopLevelTypeError("payload must be a JSON object")
        return obj, source_sha
    raise CompatTopLevelTypeError(
        f"payload must be bytes, str, or a Mapping, got {type(payload).__name__}"
    )


def _validate_schema_root(schema_root: str | Path) -> Path:
    if not isinstance(schema_root, (str, Path)):
        raise CompatSchemaRootError("schema_root must be an explicit str or Path")
    if isinstance(schema_root, str) and schema_root == "":
        raise CompatSchemaRootError("schema_root must not be an empty string")
    path = Path(schema_root)
    if path.is_symlink():
        raise CompatSchemaRootError("schema_root must not be a symlink")
    if not path.exists():
        raise CompatSchemaRootError("schema_root does not exist")
    if not path.is_dir():
        raise CompatSchemaRootError("schema_root is not a directory")
    return path.resolve()


def _load_pinned_schema(
    contract_id: str, contract_version: str, schema_root: str | Path
) -> tuple[dict[str, Any], str]:
    route = _HISTORICAL_ROUTES.get((contract_id, contract_version))
    if route is None:
        raise CompatUnsupportedVersionError(
            f"{contract_id}@{contract_version} is not a governed compatibility route"
        )
    relative_path, expected_sha = route
    root = _validate_schema_root(schema_root)
    schema_path = root / relative_path
    if schema_path.is_symlink():
        raise CompatSchemaNotAFileError(f"pinned schema {relative_path!r} is a symlink")
    if not schema_path.exists():
        raise CompatSchemaMissingError(f"pinned schema {relative_path!r} does not exist")
    if not schema_path.is_file():
        raise CompatSchemaNotAFileError(f"pinned schema {relative_path!r} is not a regular file")
    try:
        raw = schema_path.read_bytes()
    except OSError as exc:
        raise CompatSchemaReadError(f"failed to read pinned schema {relative_path!r}") from exc
    observed = sha256_bytes(raw)
    if observed != expected_sha:
        raise CompatSchemaHashMismatchError(
            f"pinned schema {relative_path!r} does not match its expected SHA-256"
        )
    try:
        schema = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompatSchemaValidationError(f"pinned schema {relative_path!r} is not valid JSON") from exc
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise CompatSchemaValidationError(
            f"pinned schema {relative_path!r} failed meta-validation: {exc.message}"
        ) from exc
    return schema, observed


def _schema_validate(schema: dict[str, Any], payload: dict[str, Any]) -> None:
    messages = tuple(sorted(e.message for e in Draft202012Validator(schema).iter_errors(payload)))
    if messages:
        raise CompatSchemaValidationError("historical document failed schema validation")


# --- Public historical readers --------------------------------------------


def read_evaluation_result_v1(
    payload: bytes | str | Mapping[str, object],
    *,
    contract_version: Literal["0.1.0"],
    schema_root: str | Path,
) -> LoadedHistoricalEvaluationResult:
    """Read a historical ``evaluation_result@0.1.0`` document (read-only)."""
    if contract_version != "0.1.0":
        raise CompatUnsupportedVersionError(
            f"evaluation_result compatibility route {contract_version!r} is not supported"
        )
    schema, schema_sha = _load_pinned_schema("evaluation_result", contract_version, schema_root)
    obj, source_sha = _parse_payload(payload)
    _schema_validate(schema, obj)
    # Strict typed construction is defensive: the pinned schema already governs
    # validity, so this cannot fail in practice; a raw Pydantic failure is
    # converted to the sanitized typed error outside the handler (no chaining,
    # so __cause__ and __context__ are both None).
    document = None
    ok = False
    try:
        document = HistoricalEvaluationResultV1.model_validate(obj)
        ok = True
    except PydanticValidationError:
        ok = False
    if not ok:
        raise CompatSchemaValidationError(
            "historical evaluation-result document failed strict validation"
        )
    return LoadedHistoricalEvaluationResult(
        contract_version="0.1.0", document=document, source_sha256=source_sha,
        schema_sha256=schema_sha,
    )


def read_universe_run_manifest(
    payload: bytes | str | Mapping[str, object],
    *,
    contract_version: Literal["0.1.0", "0.2.0"],
    schema_root: str | Path,
) -> LoadedUniverseRunManifest:
    """Read a historical ``universe_run_manifest`` document (v1 or v2, read-only)."""
    if contract_version not in ("0.1.0", "0.2.0"):
        raise CompatUnsupportedVersionError(
            f"universe_run_manifest compatibility route {contract_version!r} is not supported"
        )
    schema, schema_sha = _load_pinned_schema("universe_run_manifest", contract_version, schema_root)
    obj, source_sha = _parse_payload(payload)
    _schema_validate(schema, obj)
    document = None
    ok = False
    try:
        document = UniverseRunManifestDocument.model_validate(obj)
        ok = True
    except PydanticValidationError:
        ok = False
    if not ok:
        raise CompatSchemaValidationError(
            "historical universe document failed strict validation"
        )
    return LoadedUniverseRunManifest(
        contract_version=contract_version, document=document, source_sha256=source_sha,
        schema_sha256=schema_sha,
    )


# --- Bridge assertion-contract snapshot -----------------------------------


class BridgeAssertionContractEntry(_CompatStrictModel):
    """One authoritative pre-execution assertion contract entry."""

    case_id: str
    assertion_id: str
    assertion_semantic_version: str | None = None
    assertion_contract_hash: str | None = None
    protected_regression_classes: tuple[str, ...]

    @model_validator(mode="after")
    def _entry_invariants(self) -> "BridgeAssertionContractEntry":
        _require_non_blank(self.case_id, "case_id")
        _require_non_blank(self.assertion_id, "assertion_id")
        present = self.assertion_semantic_version is not None or self.assertion_contract_hash is not None
        if not present:
            raise ValueError(
                "at least one of assertion_semantic_version or assertion_contract_hash is required"
            )
        if self.assertion_semantic_version is not None:
            _require_non_blank(self.assertion_semantic_version, "assertion_semantic_version")
        if self.assertion_contract_hash is not None:
            _require_non_blank(self.assertion_contract_hash, "assertion_contract_hash")
        for cls in self.protected_regression_classes:
            _require_non_blank(cls, "protected_regression_class")
        classes = list(self.protected_regression_classes)
        if classes != sorted(classes):
            raise ValueError("protected_regression_classes must be sorted")
        if len(classes) != len(set(classes)):
            raise ValueError("protected_regression_classes must be unique")
        return self

    @property
    def identity(self) -> tuple[str, str]:
        return (self.case_id, self.assertion_id)


class BridgeAssertionContractSnapshot(_CompatStrictModel):
    """The authoritative predeclared assertion-contract snapshot for a bridge."""

    entries: tuple[BridgeAssertionContractEntry, ...]
    scoring_config_version: str
    scoring_config_sha256: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    mapping_version: Literal["0.1.0"]
    failure_taxonomy_version: Literal["0.1.0"]

    @model_validator(mode="after")
    def _snapshot_invariants(self) -> "BridgeAssertionContractSnapshot":
        _require_non_blank(self.scoring_config_version, "scoring_config_version")
        identities = [e.identity for e in self.entries]
        if identities != sorted(identities):
            raise ValueError("entries must be sorted by (case_id, assertion_id)")
        if len(identities) != len(set(identities)):
            raise ValueError("entries must not contain a duplicate identity")
        return self

    @property
    def by_identity(self) -> dict[tuple[str, str], BridgeAssertionContractEntry]:
        return {e.identity: e for e in self.entries}


def build_bridge_assertion_contract_snapshot(
    *,
    resolutions: tuple[CaseResolution, ...],
    scoring_config: LoadedScoringGateConfig,
) -> BridgeAssertionContractSnapshot:
    """Derive the authoritative assertion-contract snapshot (pure; caller-supplied)."""
    if not isinstance(scoring_config, LoadedScoringGateConfig):
        raise TypeError(
            f"scoring_config must be a LoadedScoringGateConfig, got {type(scoring_config).__name__}"
        )
    gates_by_ref = {g.reference_id: g for g in scoring_config.config.gates}
    declared = set(scoring_config.config.protected_regression_classes)
    entries: list[BridgeAssertionContractEntry] = []
    seen: set[tuple[str, str]] = set()
    for resolution in resolutions:
        if not isinstance(resolution, CaseResolution):
            raise TypeError(f"resolutions must be CaseResolution instances, got {type(resolution).__name__}")
        for assertion in resolution.assertions:
            identity = (resolution.case_id, assertion.assertion_id)
            if identity in seen:
                raise BridgeMetadataError(
                    f"duplicate assertion identity {identity!r} in resolutions"
                )
            seen.add(identity)
            protected: set[str] = set()
            for reference in assertion.scoring_references:
                if reference.definition_kind == "diagnostic":
                    continue
                gate = gates_by_ref.get(reference.canonical_reference_id)
                if gate is None:
                    raise BridgeMetadataError(
                        f"assertion {identity!r} references gate "
                        f"{reference.canonical_reference_id!r} that does not resolve"
                    )
                for cls in gate.protected_regression_class_references:
                    if cls not in declared:
                        raise BridgeMetadataError(
                            f"assertion {identity!r} references protected class {cls!r} "
                            "not declared by the scoring configuration"
                        )
                    protected.add(cls)
            entries.append(BridgeAssertionContractEntry(
                case_id=resolution.case_id, assertion_id=assertion.assertion_id,
                assertion_semantic_version=assertion.assertion_semantic_version,
                assertion_contract_hash=assertion.assertion_contract_hash,
                protected_regression_classes=tuple(sorted(protected)),
            ))
    entries.sort(key=lambda e: e.identity)
    return BridgeAssertionContractSnapshot(
        entries=tuple(entries), scoring_config_version=scoring_config.version,
        scoring_config_sha256=scoring_config.sha256, mapping_version=_METADATA_MAPPING_VERSION,
        failure_taxonomy_version=_METADATA_FAILURE_TAXONOMY_VERSION,
    )


# --- Bridge request models ------------------------------------------------


class BridgeSharedContract(_CompatStrictModel):
    """The single new contract under which both bridge sides are re-evaluated."""

    stage: str
    case_set_version: str
    case_set_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    registry_snapshot_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    validator_bundle_version: str
    validator_bundle_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    scoring_gate_config_version: str
    scoring_gate_config_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    code_commit: str
    pydantic_runtime_version: str

    @model_validator(mode="after")
    def _shared_invariants(self) -> "BridgeSharedContract":
        for name in ("stage", "case_set_version", "validator_bundle_version",
                     "scoring_gate_config_version", "code_commit", "pydantic_runtime_version"):
            _require_non_blank(getattr(self, name), name)
        return self


class BridgeSideRequest(_CompatStrictModel):
    """One directional source-to-target side of a bridge request."""

    side: Literal["baseline", "candidate"]
    source_prediction_run_id: str
    source_prediction_run_manifest_hash: str = Field(
        min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    target_bridge_eval_run_id: str

    @model_validator(mode="after")
    def _side_invariants(self) -> "BridgeSideRequest":
        _require_non_blank(self.source_prediction_run_id, "source_prediction_run_id")
        _require_non_blank(self.target_bridge_eval_run_id, "target_bridge_eval_run_id")
        return self


class BridgeRequest(_CompatStrictModel):
    """A predeclared pairwise validator/scoring bridge request."""

    baseline_role: Literal["validator_bridge_baseline"]
    shared_contract: BridgeSharedContract
    assertion_contract_snapshot: BridgeAssertionContractSnapshot
    input_packet_snapshot: ComparisonInputPacketSnapshot
    baseline: BridgeSideRequest
    candidate: BridgeSideRequest

    @model_validator(mode="after")
    def _request_invariants(self) -> "BridgeRequest":
        if self.baseline.side != "baseline":
            raise ValueError("baseline side request must have side 'baseline'")
        if self.candidate.side != "candidate":
            raise ValueError("candidate side request must have side 'candidate'")
        if self.baseline.source_prediction_run_id == self.candidate.source_prediction_run_id:
            raise ValueError("baseline and candidate source prediction run IDs must differ")
        if self.baseline.target_bridge_eval_run_id == self.candidate.target_bridge_eval_run_id:
            raise ValueError("baseline and candidate target bridge eval-run IDs must differ")
        snap = self.assertion_contract_snapshot
        if snap.scoring_config_version != self.shared_contract.scoring_gate_config_version:
            raise ValueError("snapshot scoring_config_version does not bind the shared contract")
        if snap.scoring_config_sha256 != self.shared_contract.scoring_gate_config_hash:
            raise ValueError("snapshot scoring_config_sha256 does not bind the shared contract")
        ips = self.input_packet_snapshot
        if ips.case_set_version != self.shared_contract.case_set_version:
            raise ValueError("input_packet_snapshot case_set_version does not bind the shared contract")
        if ips.case_set_hash != self.shared_contract.case_set_hash:
            raise ValueError("input_packet_snapshot case_set_hash does not bind the shared contract")
        if ips.registry_snapshot_hash != self.shared_contract.registry_snapshot_hash:
            raise ValueError(
                "input_packet_snapshot registry_snapshot_hash does not bind the shared contract")
        return self


# --- Raw executor model + Protocol ----------------------------------------


class BridgeSideExecutionResult(_CompatStrictModel):
    """Ephemeral raw output of one trusted side executor (not deeply immutable)."""

    side: Literal["baseline", "candidate"]
    run_manifest: LoadedEvaluationRunManifest
    result: LoadedEvaluationResult
    outcomes: LoadedAssertionOutcomes
    scoring_config: LoadedScoringGateConfig


@runtime_checkable
class BridgeSideExecutor(Protocol):
    """A trusted in-process component that produces one ordinary bridge run."""

    def __call__(
        self,
        *,
        side_request: BridgeSideRequest,
        shared_contract: BridgeSharedContract,
    ) -> BridgeSideExecutionResult:
        ...


# --- Artifact-SHA consistency helpers (private) ---------------------------


def _manifest_artifact_sha(loaded: LoadedEvaluationRunManifest) -> str:
    payload = loaded.manifest.model_dump(mode="json", exclude_unset=True)
    return sha256_bytes(canonical_contract_bytes(payload))


def _result_artifact_sha(loaded: LoadedEvaluationResult) -> str:
    payload = loaded.result.model_dump(mode="json", exclude_unset=True)
    return sha256_bytes(canonical_contract_bytes(payload) + b"\n")


def _outcomes_artifact_sha(loaded: LoadedAssertionOutcomes) -> str:
    data = b"".join(
        canonical_contract_bytes(o.model_dump(mode="json", exclude_unset=True)) + b"\n"
        for o in loaded.outcomes
    )
    return sha256_bytes(data)


# --- Side binding ---------------------------------------------------------


def _revalidate(obj: BaseModel) -> BaseModel:
    """Reconstruct from a plain dump so model_copy(update=...) cannot bypass validators.

    Uses ``exclude_unset=True`` so genuinely-absent optional fields are not
    re-emitted as explicit null (which committed models reject); a
    ``model_copy(update=...)`` marks the tampered field as set, so it is still
    present in the dump and re-validation still catches the tamper.
    """
    return type(obj).model_validate(obj.model_dump(mode="python", exclude_unset=True))


def _bind_side(raw: BridgeSideExecutionResult, *, request: BridgeRequest) -> None:
    if not isinstance(raw, BridgeSideExecutionResult):
        raise BridgeSideBindingError("executor did not return a BridgeSideExecutionResult")
    raw = _revalidate(raw)  # type: ignore[assignment]
    side_request = request.baseline if raw.side == "baseline" else request.candidate
    sc = request.shared_contract
    snap = request.assertion_contract_snapshot
    target = side_request.target_bridge_eval_run_id
    m = raw.run_manifest.manifest
    # Run manifest.
    if not _is_lower_hex64(raw.run_manifest.sha256):
        raise BridgeSideBindingError("run-manifest wrapper sha256 is not lowercase 64-hex")
    if m.eval_run_id != target:
        raise BridgeSideBindingError("run-manifest eval_run_id does not bind the target run id")
    if m.prediction_run_id != side_request.source_prediction_run_id:
        raise BridgeSideBindingError("run-manifest prediction_run_id does not bind the source")
    if m.prediction_run_manifest_hash != side_request.source_prediction_run_manifest_hash:
        raise BridgeSideBindingError("run-manifest prediction manifest hash does not bind the source")
    if m.case_set_version != sc.case_set_version or m.case_set_hash != sc.case_set_hash:
        raise BridgeSideBindingError("run-manifest case-set identity does not bind the shared contract")
    if m.registry_snapshot_hash != sc.registry_snapshot_hash:
        raise BridgeSideBindingError("run-manifest registry snapshot hash does not bind")
    if m.validator_bundle_version != sc.validator_bundle_version \
            or m.validator_bundle_hash != sc.validator_bundle_hash:
        raise BridgeSideBindingError("run-manifest validator bundle does not bind")
    if m.scoring_gate_config_version != sc.scoring_gate_config_version \
            or m.scoring_gate_config_hash != sc.scoring_gate_config_hash:
        raise BridgeSideBindingError("run-manifest scoring config does not bind")
    if m.code_commit != sc.code_commit:
        raise BridgeSideBindingError("run-manifest code_commit does not bind the shared contract")
    if m.pydantic_runtime_version != sc.pydantic_runtime_version:
        raise BridgeSideBindingError("run-manifest runtime version does not bind the shared contract")
    if _manifest_artifact_sha(raw.run_manifest) != raw.run_manifest.sha256:
        raise BridgeSideBindingError("run-manifest wrapper sha256 is not self-consistent")
    # Evaluation result.
    r = raw.result.result
    if not _is_lower_hex64(raw.result.sha256):
        raise BridgeSideBindingError("result wrapper sha256 is not lowercase 64-hex")
    if raw.result.eval_run_id != target or r.eval_run_id != target:
        raise BridgeSideBindingError("result eval_run_id does not bind the target run id")
    if r.dataset_version != m.case_set_version:
        raise BridgeSideBindingError("result dataset_version does not bind the case-set version")
    if r.stage != sc.stage:
        raise BridgeSideBindingError("result stage does not bind the shared contract stage")
    if r.execution_status != "completed":
        raise BridgeSideBindingError("bridge run result is not completed")
    if r.gate_verdict is None:
        raise BridgeSideBindingError("completed bridge run result has no gate verdict")
    metrics = r.metrics
    if set(metrics) != {"provenance", "gate_outcomes", "critical_finding_ids"}:
        raise BridgeSideBindingError("result metrics lacks the locked three-key projection")
    prov = metrics["provenance"]
    if not isinstance(prov, dict) or set(prov) != {
        "case_set_version", "case_set_hash", "scoring_gate_config_version",
        "scoring_gate_config_hash", "metric_report_sha256",
    }:
        raise BridgeSideBindingError("result provenance lacks the locked five keys")
    if prov["case_set_version"] != m.case_set_version or prov["case_set_hash"] != m.case_set_hash \
            or prov["scoring_gate_config_version"] != m.scoring_gate_config_version \
            or prov["scoring_gate_config_hash"] != m.scoring_gate_config_hash:
        raise BridgeSideBindingError("result provenance does not bind the run manifest")
    if _result_artifact_sha(raw.result) != raw.result.sha256:
        raise BridgeSideBindingError("result wrapper sha256 is not self-consistent")
    # Assertion outcomes.
    if not _is_lower_hex64(raw.outcomes.sha256):
        raise BridgeSideBindingError("outcomes wrapper sha256 is not lowercase 64-hex")
    if raw.outcomes.eval_run_id != target:
        raise BridgeSideBindingError("outcomes wrapper eval_run_id does not bind the target run id")
    seen_out: set[tuple[str, str]] = set()
    for o in raw.outcomes.outcomes:
        if o.eval_run_id != target:
            raise BridgeSideBindingError("assertion outcome eval_run_id does not bind the target run id")
        key = (o.case_id, o.assertion_id)
        if key in seen_out:
            raise BridgeSideBindingError("assertion outcomes contain a duplicate identity")
        seen_out.add(key)
    if _outcomes_artifact_sha(raw.outcomes) != raw.outcomes.sha256:
        raise BridgeSideBindingError("outcomes wrapper sha256 is not self-consistent")
    # Scoring config (trusted executor-loaded raw JSON source bytes; not recomputed).
    if raw.scoring_config.version != raw.scoring_config.config.config_version:
        raise BridgeSideBindingError("scoring-config wrapper version does not bind its inner config")
    if raw.scoring_config.version != m.scoring_gate_config_version \
            or raw.scoring_config.version != sc.scoring_gate_config_version \
            or raw.scoring_config.version != snap.scoring_config_version:
        raise BridgeSideBindingError("scoring-config version does not bind the run/shared/snapshot")
    if raw.scoring_config.sha256 != m.scoring_gate_config_hash \
            or raw.scoring_config.sha256 != sc.scoring_gate_config_hash \
            or raw.scoring_config.sha256 != snap.scoring_config_sha256:
        raise BridgeSideBindingError("scoring-config hash does not bind the run/shared/snapshot")
    if not _is_lower_hex64(raw.scoring_config.sha256):
        raise BridgeSideBindingError("scoring-config wrapper sha256 is not lowercase 64-hex")


# --- Metadata derivation --------------------------------------------------


def derive_bridge_side_metadata(
    *,
    target_eval_run_id: str,
    snapshot: BridgeAssertionContractSnapshot,
    scoring_config: LoadedScoringGateConfig,
    outcomes: LoadedAssertionOutcomes,
) -> AssertionComparisonMetadata:
    """Derive one side's Slice 11 metadata from the predeclared snapshot (pure)."""
    if not isinstance(snapshot, BridgeAssertionContractSnapshot):
        raise TypeError("snapshot must be a BridgeAssertionContractSnapshot")
    if not isinstance(scoring_config, LoadedScoringGateConfig):
        raise TypeError("scoring_config must be a LoadedScoringGateConfig")
    if not isinstance(outcomes, LoadedAssertionOutcomes):
        raise TypeError("outcomes must be a LoadedAssertionOutcomes")
    if scoring_config.version != snapshot.scoring_config_version \
            or scoring_config.sha256 != snapshot.scoring_config_sha256:
        raise BridgeMetadataError("scoring config does not bind the assertion snapshot")
    declared = set(scoring_config.config.protected_regression_classes)
    by_id = snapshot.by_identity
    for entry in snapshot.entries:
        for cls in entry.protected_regression_classes:
            if cls not in declared:
                raise BridgeMetadataError(
                    f"snapshot protected class {cls!r} is not declared by the scoring config"
                )
    if outcomes.eval_run_id != target_eval_run_id:
        raise BridgeMetadataError("outcomes wrapper eval_run_id does not bind the target run id")
    entries: list[AssertionComparisonMetadataEntry] = []
    for o in outcomes.outcomes:
        if o.eval_run_id != target_eval_run_id:
            raise BridgeMetadataError("assertion outcome eval_run_id does not bind the target run id")
        identity = (o.case_id, o.assertion_id)
        snap_entry = by_id.get(identity)
        if snap_entry is None:
            raise BridgeMetadataError(
                f"outcome identity {identity!r} is not present in the assertion snapshot"
            )
        if o.assertion_semantic_version != snap_entry.assertion_semantic_version \
                or o.assertion_contract_hash != snap_entry.assertion_contract_hash:
            raise BridgeMetadataError(
                f"outcome identity {identity!r} version/hash does not match the snapshot entry"
            )
        entries.append(AssertionComparisonMetadataEntry(
            case_id=o.case_id, assertion_id=o.assertion_id,
            assertion_semantic_version=snap_entry.assertion_semantic_version,
            assertion_contract_hash=snap_entry.assertion_contract_hash,
            protected_regression_classes=snap_entry.protected_regression_classes,
        ))
    identities = [e.identity for e in entries]
    if len(identities) != len(set(identities)):
        raise BridgeMetadataError("derived metadata contains a duplicate assertion identity")
    entries.sort(key=lambda e: e.identity)
    stamp = _metadata_stamp()
    return AssertionComparisonMetadata.model_validate({
        "contract": stamp, "eval_run_id": target_eval_run_id,
        "mapping_version": snapshot.mapping_version,
        "failure_taxonomy_version": snapshot.failure_taxonomy_version,
        "entries": tuple(entries),
    })


def _metadata_stamp() -> dict[str, str]:
    return {
        "contract_id": "assertion_comparison_metadata",
        "contract_version": "0.1.0",
        "contract_hash": model_contract_hash(
            AssertionComparisonMetadata, "assertion_comparison_metadata", "0.1.0"
        ),
    }


# --- Canonical captured bundle + materialization --------------------------


def _snapshot_component(obj: BaseModel) -> tuple[bytes, str]:
    payload = canonical_contract_bytes(obj.model_dump(mode="json", exclude_unset=True))
    return payload, sha256_bytes(payload)


class BridgeSideComparisonBundle(_CompatStrictModel):
    """A detached, alias-isolated, deeply immutable, cross-bound capture of one side.

    Not independently source-authenticated: fingerprints protect the captured
    canonical snapshots from later mutation.
    """

    request: BridgeRequest
    side: Literal["baseline", "candidate"]
    manifest_payload: bytes
    manifest_fingerprint: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    result_payload: bytes
    result_fingerprint: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    outcomes_payload: bytes
    outcomes_fingerprint: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    scoring_config_payload: bytes
    scoring_config_fingerprint: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    metadata_payload: bytes
    metadata_fingerprint: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)

    @model_validator(mode="after")
    def _bundle_invariants(self) -> "BridgeSideComparisonBundle":
        for payload, fingerprint in (
            (self.manifest_payload, self.manifest_fingerprint),
            (self.result_payload, self.result_fingerprint),
            (self.outcomes_payload, self.outcomes_fingerprint),
            (self.scoring_config_payload, self.scoring_config_fingerprint),
            (self.metadata_payload, self.metadata_fingerprint),
        ):
            if sha256_bytes(payload) != fingerprint:
                raise ValueError("bundle component fingerprint does not match its payload")
        side_request = self.request.baseline if self.side == "baseline" else self.request.candidate
        run_manifest = _reconstruct(self.manifest_payload, LoadedEvaluationRunManifest)
        result = _reconstruct(self.result_payload, LoadedEvaluationResult)
        outcomes = _reconstruct(self.outcomes_payload, LoadedAssertionOutcomes)
        scoring_config = _reconstruct(self.scoring_config_payload, LoadedScoringGateConfig)
        metadata = _reconstruct(self.metadata_payload, AssertionComparisonMetadata)
        raw = BridgeSideExecutionResult(
            side=self.side, run_manifest=run_manifest, result=result, outcomes=outcomes,
            scoring_config=scoring_config,
        )
        try:
            _bind_side(raw, request=self.request)
            derived = derive_bridge_side_metadata(
                target_eval_run_id=side_request.target_bridge_eval_run_id,
                snapshot=self.request.assertion_contract_snapshot,
                scoring_config=scoring_config, outcomes=outcomes,
            )
        except (BridgeSideBindingError, BridgeMetadataError) as exc:
            raise ValueError(str(exc)) from exc
        if derived.model_dump() != metadata.model_dump():
            raise ValueError("bundle metadata does not match the coordinator-derived metadata")
        return self


def _reconstruct(payload: bytes, cls: type) -> Any:
    try:
        obj = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("bundle payload is not valid JSON") from exc
    try:
        return cls.model_validate(obj)
    except PydanticValidationError as exc:
        raise ValueError(f"bundle payload failed {cls.__name__} validation") from exc


def _build_bundle(
    raw: BridgeSideExecutionResult, *, request: BridgeRequest,
) -> BridgeSideComparisonBundle:
    _bind_side(raw, request=request)
    side_request = request.baseline if raw.side == "baseline" else request.candidate
    metadata = derive_bridge_side_metadata(
        target_eval_run_id=side_request.target_bridge_eval_run_id,
        snapshot=request.assertion_contract_snapshot,
        scoring_config=raw.scoring_config, outcomes=raw.outcomes,
    )
    m_payload, m_fp = _snapshot_component(raw.run_manifest)
    r_payload, r_fp = _snapshot_component(raw.result)
    o_payload, o_fp = _snapshot_component(raw.outcomes)
    s_payload, s_fp = _snapshot_component(raw.scoring_config)
    d_payload, d_fp = _snapshot_component(metadata)
    return BridgeSideComparisonBundle(
        request=request, side=raw.side,
        manifest_payload=m_payload, manifest_fingerprint=m_fp,
        result_payload=r_payload, result_fingerprint=r_fp,
        outcomes_payload=o_payload, outcomes_fingerprint=o_fp,
        scoring_config_payload=s_payload, scoring_config_fingerprint=s_fp,
        metadata_payload=d_payload, metadata_fingerprint=d_fp,
    )


class BridgeSideComparatorInputs(_CompatStrictModel):
    """Fresh disposable per-side comparator inputs (NOT transitively immutable)."""

    run_manifest: LoadedEvaluationRunManifest
    result: LoadedEvaluationResult
    outcomes: LoadedAssertionOutcomes
    scoring_config: LoadedScoringGateConfig
    metadata: AssertionComparisonMetadata


def materialize_bridge_comparison_inputs(
    bundle: BridgeSideComparisonBundle,
) -> BridgeSideComparatorInputs:
    """Reconstruct fresh, equal-but-distinct comparator inputs from a bundle."""
    if not isinstance(bundle, BridgeSideComparisonBundle):
        raise TypeError(f"bundle must be a BridgeSideComparisonBundle, got {type(bundle).__name__}")
    bundle = _revalidate(bundle)  # type: ignore[assignment]
    run_manifest = _reconstruct(bundle.manifest_payload, LoadedEvaluationRunManifest)
    result = _reconstruct(bundle.result_payload, LoadedEvaluationResult)
    outcomes = _reconstruct(bundle.outcomes_payload, LoadedAssertionOutcomes)
    scoring_config = _reconstruct(bundle.scoring_config_payload, LoadedScoringGateConfig)
    metadata = _reconstruct(bundle.metadata_payload, AssertionComparisonMetadata)
    return BridgeSideComparatorInputs(
        run_manifest=run_manifest, result=result, outcomes=outcomes,
        scoring_config=scoring_config, metadata=metadata,
    )


# --- Pair result ----------------------------------------------------------


class BridgeReevaluationResult(_CompatStrictModel):
    """A completed pairwise bridge re-evaluation (deeply immutable)."""

    request: BridgeRequest
    baseline_role: Literal["validator_bridge_baseline"]
    baseline: BridgeSideComparisonBundle
    candidate: BridgeSideComparisonBundle

    @model_validator(mode="after")
    def _pair_invariants(self) -> "BridgeReevaluationResult":
        if self.baseline_role != self.request.baseline_role:
            raise ValueError("baseline_role does not match the request role")
        if self.baseline.request.model_dump() != self.request.model_dump():
            raise ValueError("baseline bundle request does not match the result request")
        if self.candidate.request.model_dump() != self.request.model_dump():
            raise ValueError("candidate bundle request does not match the result request")
        if self.baseline.side != "baseline":
            raise ValueError("baseline bundle must have side 'baseline'")
        if self.candidate.side != "candidate":
            raise ValueError("candidate bundle must have side 'candidate'")
        return self


# --- Pair coordinator -----------------------------------------------------


def reevaluate_bridge_pair(
    request: BridgeRequest,
    *,
    executor: BridgeSideExecutor,
) -> BridgeReevaluationResult:
    """Coordinate a baseline-then-candidate bridge pair (pure; executor is impure)."""
    if not isinstance(request, BridgeRequest):
        raise BridgeRequestError(f"request must be a BridgeRequest, got {type(request).__name__}")
    request = _revalidate(request)  # type: ignore[assignment]

    # --- baseline side ---
    baseline_failed_execution = False
    baseline_wrong_side = False
    try:
        raw_baseline = executor(side_request=request.baseline, shared_contract=request.shared_contract)
    except BridgeSideExecutionError as exc:
        baseline_wrong_side = exc.failed_side != "baseline"
        baseline_failed_execution = True
    if baseline_failed_execution:
        if baseline_wrong_side:
            raise BridgeSideBindingError("executor reported a side that does not match baseline")
        raise BridgeSideExecutionError(failed_side="baseline")
    baseline_bundle = _build_bundle(raw_baseline, request=request)
    del raw_baseline

    # --- candidate side ---
    # Every candidate-side partial failure only records a sanitized failure kind
    # inside its handler; the single public partial-failure error is raised once,
    # after leaving all handlers, so __cause__ and __context__ are both None.
    candidate_failure_kind: Literal["execution_failure", "binding_failure", "metadata_failure"] | None
    candidate_failure_kind = None
    candidate_bundle = None
    try:
        raw_candidate = executor(
            side_request=request.candidate, shared_contract=request.shared_contract
        )
    except BridgeSideExecutionError as exc:
        candidate_failure_kind = ("binding_failure" if exc.failed_side != "candidate"
                                  else "execution_failure")
    if candidate_failure_kind is None:
        try:
            _bind_side(raw_candidate, request=request)
        except BridgeSideBindingError:
            candidate_failure_kind = "binding_failure"
    if candidate_failure_kind is None:
        try:
            candidate_bundle = _build_bundle(raw_candidate, request=request)
        except BridgeMetadataError:
            candidate_failure_kind = "metadata_failure"
    if candidate_failure_kind is not None:
        raise BridgePartialFailureError(
            completed_baseline=baseline_bundle, failure_kind=candidate_failure_kind
        )
    return BridgeReevaluationResult(
        request=request, baseline_role=_BRIDGE_ROLE,
        baseline=baseline_bundle, candidate=candidate_bundle,
    )


# --- Comparison handoff ---------------------------------------------------


class BridgeComparisonArguments(_CompatStrictModel):
    """A fresh disposable object carrying the exact assess_comparison arguments."""

    comparison_id: str
    baseline_role: Literal["validator_bridge_baseline"]
    comparison_code_commit: str
    baseline_manifest: LoadedEvaluationRunManifest
    candidate_manifest: LoadedEvaluationRunManifest
    baseline_result: LoadedEvaluationResult
    candidate_result: LoadedEvaluationResult
    baseline_outcomes: LoadedAssertionOutcomes
    candidate_outcomes: LoadedAssertionOutcomes
    baseline_scoring_config: LoadedScoringGateConfig
    candidate_scoring_config: LoadedScoringGateConfig
    baseline_metadata: AssertionComparisonMetadata
    candidate_metadata: AssertionComparisonMetadata
    baseline_input_packets: ComparisonInputPacketSnapshot
    candidate_input_packets: ComparisonInputPacketSnapshot

    @model_validator(mode="after")
    def _arguments_invariants(self) -> "BridgeComparisonArguments":
        _require_non_blank(self.comparison_id, "comparison_id")
        _require_non_blank(self.comparison_code_commit, "comparison_code_commit")
        b_id = self.baseline_manifest.manifest.eval_run_id
        c_id = self.candidate_manifest.manifest.eval_run_id
        if b_id == c_id:
            raise ValueError("baseline and candidate run IDs must differ")
        if self.baseline_input_packets.model_dump() != self.candidate_input_packets.model_dump():
            raise ValueError("baseline and candidate input-packet snapshots must be value-equal")
        for side, manifest, result, outcomes, scoring, metadata, packets in (
            ("baseline", self.baseline_manifest, self.baseline_result, self.baseline_outcomes,
             self.baseline_scoring_config, self.baseline_metadata, self.baseline_input_packets),
            ("candidate", self.candidate_manifest, self.candidate_result, self.candidate_outcomes,
             self.candidate_scoring_config, self.candidate_metadata, self.candidate_input_packets),
        ):
            run_id = manifest.manifest.eval_run_id
            if result.result.eval_run_id != run_id or result.eval_run_id != run_id:
                raise ValueError(f"{side} result does not bind its manifest run id")
            if outcomes.eval_run_id != run_id:
                raise ValueError(f"{side} outcomes do not bind its manifest run id")
            if metadata.eval_run_id != run_id:
                raise ValueError(f"{side} metadata does not bind its manifest run id")
            if result.result.execution_status != "completed" or result.result.gate_verdict is None:
                raise ValueError(f"{side} result is not a completed run with a verdict")
            if scoring.version != manifest.manifest.scoring_gate_config_version \
                    or scoring.sha256 != manifest.manifest.scoring_gate_config_hash:
                raise ValueError(f"{side} scoring config does not bind its manifest")
            if packets.case_set_version != manifest.manifest.case_set_version \
                    or packets.case_set_hash != manifest.manifest.case_set_hash \
                    or packets.registry_snapshot_hash != manifest.manifest.registry_snapshot_hash:
                raise ValueError(f"{side} input-packet snapshot does not bind its manifest")
            outcome_ids = {(o.case_id, o.assertion_id) for o in outcomes.outcomes}
            meta_ids = {e.identity for e in metadata.entries}
            if outcome_ids != meta_ids:
                raise ValueError(f"{side} metadata coverage does not match outcomes")
        return self

    def to_assess_kwargs(self) -> dict[str, object]:
        """Return a fresh mapping of the 15 assess_comparison keyword arguments."""
        return {
            "comparison_id": self.comparison_id,
            "baseline_role": self.baseline_role,
            "comparison_code_commit": self.comparison_code_commit,
            "baseline_manifest": self.baseline_manifest,
            "candidate_manifest": self.candidate_manifest,
            "baseline_result": self.baseline_result,
            "candidate_result": self.candidate_result,
            "baseline_outcomes": self.baseline_outcomes,
            "candidate_outcomes": self.candidate_outcomes,
            "baseline_scoring_config": self.baseline_scoring_config,
            "candidate_scoring_config": self.candidate_scoring_config,
            "baseline_metadata": self.baseline_metadata,
            "candidate_metadata": self.candidate_metadata,
            "baseline_input_packets": self.baseline_input_packets,
            "candidate_input_packets": self.candidate_input_packets,
        }


def build_bridge_comparison_arguments(
    result: BridgeReevaluationResult,
    *,
    comparison_id: str,
    comparison_code_commit: str,
) -> BridgeComparisonArguments:
    """Materialize fresh Slice 11 comparison arguments from a bridge result."""
    if not isinstance(result, BridgeReevaluationResult):
        raise TypeError(
            f"result must be a BridgeReevaluationResult, got {type(result).__name__}"
        )
    result = _revalidate(result)  # type: ignore[assignment]
    baseline = materialize_bridge_comparison_inputs(result.baseline)
    candidate = materialize_bridge_comparison_inputs(result.candidate)
    # Both sides re-evaluate over the one governed new case set, so the single
    # predeclared shared snapshot binds both baseline and candidate.
    shared_packets = result.request.input_packet_snapshot
    return BridgeComparisonArguments(
        comparison_id=comparison_id, baseline_role=result.baseline_role,
        comparison_code_commit=comparison_code_commit,
        baseline_manifest=baseline.run_manifest, candidate_manifest=candidate.run_manifest,
        baseline_result=baseline.result, candidate_result=candidate.result,
        baseline_outcomes=baseline.outcomes, candidate_outcomes=candidate.outcomes,
        baseline_scoring_config=baseline.scoring_config,
        candidate_scoring_config=candidate.scoring_config,
        baseline_metadata=baseline.metadata, candidate_metadata=candidate.metadata,
        baseline_input_packets=shared_packets, candidate_input_packets=shared_packets,
    )
