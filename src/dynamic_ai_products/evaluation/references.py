"""Target/gold reference registry loading and case-reference resolution (Slice 4).

Read-side plus pure validation only: load one immutable target/gold registry
under an explicit evaluation root with the strict parsing discipline of the
earlier slices, compute raw-byte binding material, and resolve the target and
scoring-configuration references declared by an ``EvaluationCase`` against a
loaded registry and a loaded scoring/gate configuration.

Per the approved Slice 4 decisions (Option 1): an assertion's own
``semantic_version`` / ``contract_hash`` describe the embedded assertion
contract's identity and are preserved verbatim; they are never resolved
against, matched to, or compared with the target registry's entity contracts.
Only ``target_references`` (canonical IDs and accepted aliases) drive target
lookup. No metric, gate, verdict, execution-status, or assertion-outcome
artifact is produced here.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError as PydanticValidationError

from .cases import InvalidEvaluationRootError
from .models import EvaluationCase
from ..universe.io_utils import sha256_bytes

_IDENTITY_PATTERN = r"^\S(.*\S)?$"
_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"

ResolutionFailureKind = Literal[
    "registry_artifact_missing",
    "config_artifact_missing",
    "unknown_contract_version",
    "snapshot_hash_mismatch",
    "duplicate_reference_id",
    "conflicting_reference_definition",
    "unresolvable_target_reference",
    "unresolvable_scoring_gate_config_reference",
]

RULE_IDS: dict[str, str] = {
    "registry_artifact_missing": "slice4.registry_artifact_missing",
    "config_artifact_missing": "slice4.config_artifact_missing",
    "unknown_contract_version": "slice4.unknown_contract_version",
    "snapshot_hash_mismatch": "slice4.snapshot_hash_mismatch",
    "duplicate_reference_id": "slice4.duplicate_reference_id",
    "conflicting_reference_definition": "slice4.conflicting_reference_definition",
    "unresolvable_target_reference": "slice4.unresolvable_target_reference",
    "unresolvable_scoring_gate_config_reference": (
        "slice4.unresolvable_scoring_gate_config_reference"
    ),
}


class _Slice4StrictModel(BaseModel):
    """Strict, immutable base for all Slice 4 reference models."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ResolutionFinding(_Slice4StrictModel):
    """Immutable, deterministic material describing one blocking failure.

    Carries no severity, run ID, or validator-bundle identity (Slice 4 has no
    run context); persisted ``ValidatorFinding`` construction is deferred to a
    run-context slice. Hashes are artifact identities and are safe to include;
    raw documents and offending input values never appear.
    """

    failure_kind: ResolutionFailureKind
    rule_id: str
    message: str
    artifact_reference: str | None = None
    reference_id: str | None = None
    case_id: str | None = None
    assertion_id: str | None = None
    expected_sha256: str | None = None
    observed_sha256: str | None = None


class BlockingResolutionError(Exception):
    """A validity-blocking Slice 4 resolution failure carrying one finding."""

    def __init__(self, finding: ResolutionFinding) -> None:
        super().__init__(finding.message)
        self.finding = finding
        self.failure_kind = finding.failure_kind
        self.rule_id = finding.rule_id
        self.artifact_reference = finding.artifact_reference
        self.reference_id = finding.reference_id
        self.case_id = finding.case_id
        self.assertion_id = finding.assertion_id
        self.expected_sha256 = finding.expected_sha256
        self.observed_sha256 = finding.observed_sha256


def _blocking(
    failure_kind: ResolutionFailureKind,
    message: str,
    **attrs: Any,
) -> BlockingResolutionError:
    return BlockingResolutionError(
        ResolutionFinding(
            failure_kind=failure_kind,
            rule_id=RULE_IDS[failure_kind],
            message=message,
            **attrs,
        )
    )


# --- Target registry artifact models -------------------------------------


class RegistryContractDefinition(_Slice4StrictModel):
    """One contract identity used by target/gold registry entries."""

    contract_id: str = Field(pattern=_IDENTITY_PATTERN)
    contract_version: str = Field(pattern=_IDENTITY_PATTERN)
    contract_hash: str = Field(pattern=_SHA256_HEX_PATTERN)


class TargetReferenceDefinition(_Slice4StrictModel):
    """One canonical target/gold reference entry."""

    reference_id: str = Field(pattern=_IDENTITY_PATTERN)
    reference_kind: Literal["target", "gold"]
    contract_id: str = Field(pattern=_IDENTITY_PATTERN)
    contract_version: str = Field(pattern=_IDENTITY_PATTERN)
    aliases: tuple[str, ...]
    description: str | None = None

    @classmethod
    def _validate_aliases(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for alias in value:
            if not isinstance(alias, str) or not alias or alias != alias.strip():
                raise ValueError("each alias must be a non-blank string")
        return value


class TargetRegistry(_Slice4StrictModel):
    """Immutable versioned target/gold reference registry."""

    registry_version: str = Field(pattern=_IDENTITY_PATTERN)
    contracts: tuple[RegistryContractDefinition, ...]
    entries: tuple[TargetReferenceDefinition, ...]


class LoadedTargetRegistry(_Slice4StrictModel):
    """A validated registry plus its raw-byte binding material."""

    registry: TargetRegistry
    version: str
    sha256: str
    artifact_reference: str


# --- Resolver result models ----------------------------------------------


class ResolvedTargetReference(_Slice4StrictModel):
    requested_reference_id: str
    canonical_reference_id: str
    reference_kind: Literal["target", "gold"]
    contract_id: str
    contract_version: str
    contract_hash: str


class ResolvedScoringReference(_Slice4StrictModel):
    requested_reference_id: str
    canonical_reference_id: str
    definition_kind: Literal["gate", "diagnostic"]


class ResolvedAssertionReferences(_Slice4StrictModel):
    assertion_id: str
    assertion_semantic_version: str | None
    assertion_contract_hash: str | None
    target_references: tuple[ResolvedTargetReference, ...]
    scoring_references: tuple[ResolvedScoringReference, ...]


class CaseResolution(_Slice4StrictModel):
    case_id: str
    target_registry_version: str
    target_registry_sha256: str
    scoring_config_version: str
    scoring_config_sha256: str
    assertions: tuple[ResolvedAssertionReferences, ...]


# --- Loader exceptions ----------------------------------------------------


class TargetRegistryLoadError(Exception):
    """Base class for target-registry parse/path failures; never raised directly."""

    def __init__(self, message: str, *, artifact_reference: str | None = None) -> None:
        super().__init__(message)
        self.artifact_reference = artifact_reference


class TargetRegistryArtifactNotAFileError(TargetRegistryLoadError):
    """The contained registry path exists but is not a regular file."""


class TargetRegistryPathEscapeError(TargetRegistryLoadError):
    """The requested registry path resolves outside the evaluation root."""


class TargetRegistryReadError(TargetRegistryLoadError):
    """Reading the registry bytes failed."""


class TargetRegistryDecodeError(TargetRegistryLoadError):
    """The registry bytes are not valid UTF-8."""


class TargetRegistryJsonError(TargetRegistryLoadError):
    """The registry text is not acceptable strict JSON."""

    def __init__(
        self,
        message: str,
        *,
        artifact_reference: str | None = None,
        duplicate_key: str | None = None,
        constant_name: str | None = None,
    ) -> None:
        super().__init__(message, artifact_reference=artifact_reference)
        self.duplicate_key = duplicate_key
        self.constant_name = constant_name


class TargetRegistryTopLevelTypeError(TargetRegistryLoadError):
    """The parsed registry document is not a JSON object."""

    def __init__(
        self,
        message: str,
        *,
        artifact_reference: str | None = None,
        observed_type: str | None = None,
    ) -> None:
        super().__init__(message, artifact_reference=artifact_reference)
        self.observed_type = observed_type


class TargetRegistryModelValidationError(TargetRegistryLoadError):
    """The registry document failed model validation."""

    def __init__(
        self,
        message: str,
        *,
        artifact_reference: str | None = None,
        field_locations: tuple[str, ...] = (),
        error_types: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message, artifact_reference=artifact_reference)
        self.field_locations = field_locations
        self.error_types = error_types


class _DuplicateKeyControl(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


class _NonFiniteControl(Exception):
    def __init__(self, constant_name: str) -> None:
        super().__init__(constant_name)
        self.constant_name = constant_name


# --- Private strict-loading helpers (module-local; not shared) ------------


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


def _validate_eval_root(eval_root: str | Path) -> Path:
    if not isinstance(eval_root, (str, Path)):
        raise InvalidEvaluationRootError(
            "eval_root must be an explicit str or Path evaluation root",
            observed_type=type(eval_root).__name__,
        )
    if isinstance(eval_root, str) and eval_root == "":
        raise InvalidEvaluationRootError(
            "eval_root must not be an empty string; supply the evaluation root explicitly",
            supplied_root="",
        )
    root = Path(eval_root)
    if not root.exists():
        raise InvalidEvaluationRootError(
            f"evaluation root {str(eval_root)!r} does not exist",
            supplied_root=str(eval_root),
        )
    if not root.is_dir():
        raise InvalidEvaluationRootError(
            f"evaluation root {str(eval_root)!r} is not a directory",
            supplied_root=str(eval_root),
        )
    return root.resolve()


def _resolve_contained(artifact_path: str | Path, resolved_root: Path) -> tuple[Path, str]:
    requested = Path(artifact_path)
    candidate = requested if requested.is_absolute() else resolved_root / requested
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise TargetRegistryPathEscapeError(
            f"target-registry path {str(artifact_path)!r} resolves outside the "
            "evaluation root",
            artifact_reference=str(artifact_path),
        )
    reference = resolved.relative_to(resolved_root).as_posix()
    if not resolved.exists():
        raise _blocking(
            "registry_artifact_missing",
            f"target registry {reference!r} does not exist under the evaluation root",
            artifact_reference=reference,
        )
    if not resolved.is_file():
        raise TargetRegistryArtifactNotAFileError(
            f"target registry {reference!r} is not a regular file",
            artifact_reference=reference,
        )
    return resolved, reference


def _read_bytes(resolved: Path, reference: str) -> bytes:
    try:
        return resolved.read_bytes()
    except OSError as exc:
        raise TargetRegistryReadError(
            f"failed to read target registry {reference!r}",
            artifact_reference=reference,
        ) from exc


def _decode(raw: bytes, reference: str) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TargetRegistryDecodeError(
            f"target registry {reference!r} is not valid UTF-8",
            artifact_reference=reference,
        ) from exc


def _assert_finite(payload: Any, reference: str) -> None:
    stack = [payload]
    while stack:
        value = stack.pop()
        if isinstance(value, float) and not math.isfinite(value):
            name = "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
            raise TargetRegistryJsonError(
                f"target registry {reference!r} contains a non-finite JSON number ({name})",
                artifact_reference=reference,
                constant_name=name,
            )
        elif isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)


def _parse_json(text: str, reference: str) -> Any:
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except json.JSONDecodeError as exc:
        raise TargetRegistryJsonError(
            f"target registry {reference!r} is not valid JSON: {exc.msg} "
            f"(line {exc.lineno} column {exc.colno})",
            artifact_reference=reference,
        ) from exc
    except _DuplicateKeyControl as exc:
        raise TargetRegistryJsonError(
            f"target registry {reference!r} contains a duplicate JSON object key {exc.key!r}",
            artifact_reference=reference,
            duplicate_key=exc.key,
        ) from exc
    except _NonFiniteControl as exc:
        raise TargetRegistryJsonError(
            f"target registry {reference!r} contains the non-JSON constant {exc.constant_name}",
            artifact_reference=reference,
            constant_name=exc.constant_name,
        ) from exc
    _assert_finite(payload, reference)
    return payload


def _require_object(payload: Any, reference: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TargetRegistryTopLevelTypeError(
            f"target registry {reference!r} must be a top-level JSON object, "
            f"got {type(payload).__name__}",
            artifact_reference=reference,
            observed_type=type(payload).__name__,
        )
    return payload


def _validate_model(payload: dict[str, Any], reference: str) -> TargetRegistry:
    try:
        return TargetRegistry.model_validate(payload)
    except PydanticValidationError as exc:
        pairs = sorted(
            ("/".join(str(part) for part in error["loc"]), error["type"])
            for error in exc.errors()
        )
        raise TargetRegistryModelValidationError(
            f"target registry {reference!r} failed model validation at location(s): "
            f"{', '.join(loc for loc, _ in pairs) or '<root>'}",
            artifact_reference=reference,
            field_locations=tuple(loc for loc, _ in pairs),
            error_types=tuple(t for _, t in pairs),
        ) from exc


def _verify_expected_hash(
    expected_sha256: str | None, observed: str, reference: str
) -> None:
    if expected_sha256 is None:
        return
    valid = (
        isinstance(expected_sha256, str)
        and len(expected_sha256) == 64
        and all(c in "0123456789abcdef" for c in expected_sha256)
    )
    if not valid or expected_sha256 != observed:
        raise _blocking(
            "snapshot_hash_mismatch",
            f"target registry {reference!r} raw-byte hash does not match the "
            "expected snapshot hash",
            artifact_reference=reference,
            expected_sha256=expected_sha256 if valid else None,
            observed_sha256=observed,
        )


def _validate_registry_semantics(registry: TargetRegistry, reference: str) -> None:
    # Aliases per-entry non-blank (structural safety not covered by the base model).
    for entry in registry.entries:
        TargetReferenceDefinition._validate_aliases(entry.aliases)
    # Contract identities unique (in artifact order).
    contract_index: dict[tuple[str, str], str] = {}
    for contract in registry.contracts:
        key = (contract.contract_id, contract.contract_version)
        if key in contract_index:
            raise _blocking(
                "conflicting_reference_definition",
                f"target registry {reference!r} declares contract "
                f"{contract.contract_id!r} version {contract.contract_version!r} "
                "more than once",
                artifact_reference=reference,
            )
        contract_index[key] = contract.contract_hash
    # Canonical reference IDs unique (in artifact order).
    canonical_ids: set[str] = set()
    for entry in registry.entries:
        if entry.reference_id in canonical_ids:
            raise _blocking(
                "duplicate_reference_id",
                f"target registry {reference!r} declares reference "
                f"{entry.reference_id!r} more than once",
                artifact_reference=reference,
                reference_id=entry.reference_id,
            )
        canonical_ids.add(entry.reference_id)
    # Entry contracts resolve + one shared alias/canonical namespace.
    alias_owner: dict[str, str] = {}
    for entry in registry.entries:
        if (entry.contract_id, entry.contract_version) not in contract_index:
            raise _blocking(
                "unknown_contract_version",
                f"target registry {reference!r} entry {entry.reference_id!r} "
                f"references undeclared contract {entry.contract_id!r} version "
                f"{entry.contract_version!r}",
                artifact_reference=reference,
                reference_id=entry.reference_id,
            )
        seen_here: set[str] = set()
        for alias in entry.aliases:
            if alias in seen_here or alias in canonical_ids or (
                alias in alias_owner and alias_owner[alias] != entry.reference_id
            ):
                raise _blocking(
                    "conflicting_reference_definition",
                    f"target registry {reference!r} alias {alias!r} conflicts "
                    "within the canonical/alias namespace",
                    artifact_reference=reference,
                    reference_id=entry.reference_id,
                )
            seen_here.add(alias)
            alias_owner[alias] = entry.reference_id


def load_target_registry(
    registry_path: str | Path,
    *,
    eval_root: str | Path,
    expected_sha256: str | None = None,
) -> LoadedTargetRegistry:
    """Load, hash, validate and semantically check one target/gold registry.

    ``eval_root`` is explicit and required. A missing artifact is the governed
    blocking failure ``registry_artifact_missing``. The returned SHA-256 is
    computed over the exact raw bytes, never parsed or canonicalized JSON.
    """
    resolved_root = _validate_eval_root(eval_root)
    resolved, reference = _resolve_contained(registry_path, resolved_root)
    raw = _read_bytes(resolved, reference)
    observed = sha256_bytes(raw)
    _verify_expected_hash(expected_sha256, observed, reference)
    text = _decode(raw, reference)
    payload = _require_object(_parse_json(text, reference), reference)
    registry = _validate_model(payload, reference)
    _validate_registry_semantics(registry, reference)
    return LoadedTargetRegistry(
        registry=registry,
        version=registry.registry_version,
        sha256=observed,
        artifact_reference=reference,
    )


def _registry_lookups(
    registry: TargetRegistry,
) -> tuple[dict[str, TargetReferenceDefinition], dict[str, str], dict[tuple[str, str], str]]:
    by_canonical: dict[str, TargetReferenceDefinition] = {}
    name_to_canonical: dict[str, str] = {}
    for entry in registry.entries:
        by_canonical[entry.reference_id] = entry
        name_to_canonical[entry.reference_id] = entry.reference_id
    for entry in registry.entries:
        for alias in entry.aliases:
            name_to_canonical[alias] = entry.reference_id
    contract_hashes = {
        (c.contract_id, c.contract_version): c.contract_hash for c in registry.contracts
    }
    return by_canonical, name_to_canonical, contract_hashes


def resolve_case_references(
    case: EvaluationCase,
    *,
    registry: LoadedTargetRegistry,
    scoring_config: Any,
) -> CaseResolution:
    """Resolve one case's target and scoring references against loaded artifacts.

    Assertion identities (``semantic_version`` / ``contract_hash``) are copied
    verbatim and never resolved against the registry (Option 1). Only
    ``target_references`` drive target lookup via canonical IDs and accepted
    aliases. Successful resolution proves that references and identities
    resolve; it does not evaluate any assertion expectation, and no outcome,
    metric, gate verdict, or execution status is produced.
    """
    from .scoring_config import LoadedScoringGateConfig  # local: avoid import cycle

    if not isinstance(case, EvaluationCase):
        raise TypeError(
            f"resolve_case_references requires an EvaluationCase, got {type(case).__name__}"
        )
    if not isinstance(registry, LoadedTargetRegistry):
        raise TypeError(
            f"registry must be a LoadedTargetRegistry, got {type(registry).__name__}"
        )
    if not isinstance(scoring_config, LoadedScoringGateConfig):
        raise TypeError(
            f"scoring_config must be a LoadedScoringGateConfig, got "
            f"{type(scoring_config).__name__}"
        )

    by_canonical, name_to_canonical, contract_hashes = _registry_lookups(registry.registry)
    gate_ids = {gate.reference_id for gate in scoring_config.config.gates}
    diagnostic_ids = {d.reference_id for d in scoring_config.config.diagnostics}

    resolved_assertions: list[ResolvedAssertionReferences] = []
    for assertion in case.assertions:
        targets: list[ResolvedTargetReference] = []
        for requested in assertion.target_references:
            canonical = name_to_canonical.get(requested)
            if canonical is None:
                raise _blocking(
                    "unresolvable_target_reference",
                    f"assertion {assertion.assertion_id!r} target reference "
                    f"{requested!r} does not resolve in the target registry",
                    artifact_reference=registry.artifact_reference,
                    reference_id=requested,
                    case_id=case.case_id,
                    assertion_id=assertion.assertion_id,
                )
            entry = by_canonical[canonical]
            targets.append(
                ResolvedTargetReference(
                    requested_reference_id=requested,
                    canonical_reference_id=canonical,
                    reference_kind=entry.reference_kind,
                    contract_id=entry.contract_id,
                    contract_version=entry.contract_version,
                    contract_hash=contract_hashes[(entry.contract_id, entry.contract_version)],
                )
            )
        scorings: list[ResolvedScoringReference] = []
        for requested in assertion.scoring_gate_config_references:
            if requested in gate_ids:
                definition_kind: Literal["gate", "diagnostic"] = "gate"
            elif requested in diagnostic_ids:
                definition_kind = "diagnostic"
            else:
                raise _blocking(
                    "unresolvable_scoring_gate_config_reference",
                    f"assertion {assertion.assertion_id!r} scoring reference "
                    f"{requested!r} does not resolve in the scoring/gate configuration",
                    artifact_reference=scoring_config.artifact_reference,
                    reference_id=requested,
                    case_id=case.case_id,
                    assertion_id=assertion.assertion_id,
                )
            scorings.append(
                ResolvedScoringReference(
                    requested_reference_id=requested,
                    canonical_reference_id=requested,
                    definition_kind=definition_kind,
                )
            )
        resolved_assertions.append(
            ResolvedAssertionReferences(
                assertion_id=assertion.assertion_id,
                assertion_semantic_version=assertion.semantic_version,
                assertion_contract_hash=assertion.contract_hash,
                target_references=tuple(targets),
                scoring_references=tuple(scorings),
            )
        )
    return CaseResolution(
        case_id=case.case_id,
        target_registry_version=registry.version,
        target_registry_sha256=registry.sha256,
        scoring_config_version=scoring_config.version,
        scoring_config_sha256=scoring_config.sha256,
        assertions=tuple(resolved_assertions),
    )
