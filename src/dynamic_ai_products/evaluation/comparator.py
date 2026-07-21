"""Immutable comparison and assertion-transition artifacts (Slice 11).

Governing: SPEC-024, ADR-020 (amending ADR-019's chained vocabularies). A
comparison is a first-class immutable artifact, separate from either source
evaluation run, carrying its own execution status and — for completed
comparisons only — a gate verdict, plus a deterministic logical output hash.

Locked semantics:
- The regression primitive is a comparable assertion-outcome transition; the
  cross-run match key is exactly ``(case_id, assertion_id)`` and contract
  compatibility (semantic version / contract hash / protected membership) is
  compared *after* matching so that ``changed_assertion_contract`` stays
  reachable.
- Protected-class membership is supplied per run as a caller-provided
  ``AssertionComparisonMetadata`` snapshot (hashed as a comparison input); the
  pure comparator never touches the filesystem, clock, randomness, UUIDs, or a
  schema loader, and never mutates a source artifact.
- Verdict precedence: any protected regression → fail; else structural
  indeterminate conditions → indeterminate; else pass. An unprotected
  regression alone can coexist with ``pass`` (it stays visible in the ledger).
  A source run's own gate verdict is comparison-neutral.
- Comparison-level invalidity (a non-completed source, a binding failure) is
  distinct from per-assertion noncomparability (a governed transition class on
  a completed comparison).

Immutability here means refuse-to-overwrite directories, exclusive-create
files, and read-back hash verification — not OS-level immutability.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError as PydanticValidationError,
    model_validator,
)

from .assertions import LoadedAssertionOutcomes
from .contracts import canonical_contract_bytes, model_contract_hash
from .gates import LoadedEvaluationResult
from .models import (
    AssertionOutcomeValue,
    ContractMetadata,
    EvaluationRunManifest,
    ExecutionStatus,
    GateVerdict,
)
from .runs import LoadedEvaluationRunManifest
from .scoring_config import LoadedScoringGateConfig
from ..universe.io_utils import sha256_bytes

# --- Constants ------------------------------------------------------------

_COMPARISON_CONTRACT_VERSION = "0.1.0"
_CASE_ASSERTION_MAPPING_VERSION = "0.1.0"
_FAILURE_TAXONOMY_VERSION = "0.1.0"

_METADATA_CONTRACT_ID = "assertion_comparison_metadata"
_TRANSITION_CONTRACT_ID = "assertion_transition"
_CASE_LEDGER_CONTRACT_ID = "case_ledger_entry"
_MANIFEST_CONTRACT_ID = "comparison_manifest"

_COMPARISONS_DIR = "comparisons"
_MANIFEST_FILENAME = "comparison_manifest.json"
_TRANSITIONS_FILENAME = "assertion_transitions.jsonl"
_CASE_LEDGER_FILENAME = "case_ledger.jsonl"

_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"

_INVALID_ISSUE_CODES = frozenset({
    "source_not_completed", "source_artifact_missing", "source_artifact_malformed",
    "source_binding_invalid", "metadata_invalid", "duplicate_identity",
    "comparison_input_invalid", "comparison_contract_invalid",
})
_ERRORED_ISSUE_CODES = frozenset({"runtime_failure"})

BaselineRole = Literal[
    "current_frozen_prompt", "accepted_release", "previous_candidate",
    "model_upgrade_baseline", "validator_bridge_baseline", "reproducibility_baseline",
]
ComparableTransitionClass = Literal[
    "unchanged", "regression", "improvement", "coverage_or_certainty_degradation",
]
NoncomparabilityClass = Literal[
    "changed_assertion_contract", "changed_gold", "changed_input_packet",
    "changed_validator_contract", "added_assertion", "removed_assertion",
    "noncomparable_contract",
]
CaseLedgerClass = Literal[
    "newly_failing", "newly_passing", "degraded_but_still_passing",
    "degraded_and_still_failing", "improved_but_still_failing", "unchanged_passing",
    "unchanged_failing", "indeterminate", "noncomparable", "added_case",
    "removed_case", "additional_protected_regression",
]
CaseStatus = Literal["passing", "failing", "indeterminate", "noncomparable", "missing"]

# Evidence rank for movement among {indeterminate, not_applicable, not_evaluated}.
_EVIDENCE_RANK = {"indeterminate": 3, "not_applicable": 2, "not_evaluated": 1}
_UNDETERMINED = ("indeterminate", "not_applicable", "not_evaluated")


# --- Strict-model foundation ----------------------------------------------


class _ComparisonStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ContractStamped(_ComparisonStrictModel):
    """Local contract-stamped base (mirrors models.ContractStampedModel)."""

    _contract_id: ClassVar[str]
    _contract_version: ClassVar[str] = "0.1.0"

    contract: ContractMetadata

    @model_validator(mode="after")
    def _verify_contract_stamp(self) -> "_ContractStamped":
        expected_id = getattr(type(self), "_contract_id", None)
        if expected_id is None:
            raise ValueError("contract-stamped subclasses must define _contract_id")
        if self.contract.contract_id != expected_id:
            raise ValueError(f"contract.contract_id must be {expected_id!r}")
        if self.contract.contract_version != self._contract_version:
            raise ValueError(f"contract.contract_version must be {self._contract_version!r}")
        expected_hash = model_contract_hash(type(self), expected_id, self._contract_version)
        if self.contract.contract_hash != expected_hash:
            raise ValueError("contract.contract_hash does not match the canonical contract hash")
        return self


def _require_non_blank(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(
            f"{field_name} must be a non-empty string without leading or trailing whitespace"
        )
    return value


def _is_lower_hex64(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _validate_run_id_grammar(value: str, field_name: str) -> str:
    _require_non_blank(value, field_name)
    if value in (".", ".."):
        raise ValueError(f"{field_name} {value!r} is not a valid path component")
    if "/" in value or "\\" in value or "\x00" in value:
        raise ValueError(f"{field_name} must be a single path component without separators or NUL")
    if Path(value).is_absolute() or len(Path(value).parts) != 1:
        raise ValueError(f"{field_name} {value!r} must be exactly one relative path component")
    return value


def _contract_stamp(contract_id: str, model: type) -> dict[str, str]:
    return {
        "contract_id": contract_id,
        "contract_version": _COMPARISON_CONTRACT_VERSION,
        "contract_hash": model_contract_hash(model, contract_id, _COMPARISON_CONTRACT_VERSION),
    }


# --- Public models --------------------------------------------------------


class AssertionComparisonMetadataEntry(_ComparisonStrictModel):
    """Per-assertion protected-class snapshot for one run."""

    case_id: str
    assertion_id: str
    assertion_semantic_version: str | None = None
    assertion_contract_hash: str | None = None
    protected_regression_classes: tuple[str, ...]

    @model_validator(mode="after")
    def _entry_invariants(self) -> "AssertionComparisonMetadataEntry":
        _require_non_blank(self.case_id, "case_id")
        _require_non_blank(self.assertion_id, "assertion_id")
        present = []
        if self.assertion_semantic_version is not None:
            _require_non_blank(self.assertion_semantic_version, "assertion_semantic_version")
            present.append("assertion_semantic_version")
        if self.assertion_contract_hash is not None:
            _require_non_blank(self.assertion_contract_hash, "assertion_contract_hash")
            present.append("assertion_contract_hash")
        if not present:
            raise ValueError(
                "at least one of assertion_semantic_version or assertion_contract_hash "
                "must be present and non-blank"
            )
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


class AssertionComparisonMetadata(_ContractStamped):
    """A run's caller-supplied protected-class snapshot over its assertions."""

    _contract_id: ClassVar[str] = _METADATA_CONTRACT_ID

    eval_run_id: str
    mapping_version: str
    failure_taxonomy_version: str
    entries: tuple[AssertionComparisonMetadataEntry, ...]

    @model_validator(mode="after")
    def _metadata_invariants(self) -> "AssertionComparisonMetadata":
        _validate_run_id_grammar(self.eval_run_id, "eval_run_id")
        _require_non_blank(self.mapping_version, "mapping_version")
        _require_non_blank(self.failure_taxonomy_version, "failure_taxonomy_version")
        identities = [e.identity for e in self.entries]
        if identities != sorted(identities):
            raise ValueError("entries must be sorted by (case_id, assertion_id)")
        if len(identities) != len(set(identities)):
            raise ValueError("entries must not contain a duplicate (case_id, assertion_id)")
        return self

    @property
    def by_identity(self) -> dict[tuple[str, str], AssertionComparisonMetadataEntry]:
        return {e.identity: e for e in self.entries}


class ComparisonRunReference(_ComparisonStrictModel):
    """One run's identity/hash material; may be partial for invalid/errored."""

    eval_run_id: str
    run_manifest_sha256: str | None = None
    result_sha256: str | None = None
    assertion_outcomes_sha256: str | None = None
    scoring_config_version: str | None = None
    scoring_config_sha256: str | None = None
    metadata_mapping_version: str | None = None
    metadata_failure_taxonomy_version: str | None = None
    metadata_hash: str | None = None
    source_code_commit: str | None = None
    execution_status: ExecutionStatus | None = None
    gate_verdict: GateVerdict | None = None
    stage: str | None = None

    _HASH_FIELDS: ClassVar[tuple[str, ...]] = (
        "run_manifest_sha256", "result_sha256", "assertion_outcomes_sha256",
        "scoring_config_sha256", "metadata_hash",
    )
    _NONBLANK_FIELDS: ClassVar[tuple[str, ...]] = (
        "scoring_config_version", "metadata_mapping_version",
        "metadata_failure_taxonomy_version", "source_code_commit", "stage",
    )
    _COMPLETED_FIELDS: ClassVar[tuple[str, ...]] = (
        "run_manifest_sha256", "result_sha256", "assertion_outcomes_sha256",
        "scoring_config_version", "scoring_config_sha256", "metadata_mapping_version",
        "metadata_failure_taxonomy_version", "metadata_hash", "source_code_commit",
        "execution_status", "gate_verdict", "stage",
    )

    @model_validator(mode="after")
    def _reference_invariants(self) -> "ComparisonRunReference":
        _validate_run_id_grammar(self.eval_run_id, "eval_run_id")
        for name in self._HASH_FIELDS:
            value = getattr(self, name)
            if value is not None and not _is_lower_hex64(value):
                raise ValueError(f"{name} must be a lowercase 64-hex digest when present")
        for name in self._NONBLANK_FIELDS:
            value = getattr(self, name)
            if value is not None:
                _require_non_blank(value, name)
        if self.execution_status == "completed":
            if self.gate_verdict is None:
                raise ValueError("a completed source reference requires a gate_verdict")
        elif self.execution_status in ("invalid", "errored"):
            if self.gate_verdict is not None:
                raise ValueError("an invalid/errored source reference must omit gate_verdict")
        else:  # execution_status is None
            if self.gate_verdict is not None:
                raise ValueError("gate_verdict requires a non-null execution_status")
        return self

    @property
    def is_complete(self) -> bool:
        return all(getattr(self, name) is not None for name in self._COMPLETED_FIELDS)


class AssertionTransition(_ContractStamped):
    """One matched/added/removed assertion transition record."""

    _contract_id: ClassVar[str] = _TRANSITION_CONTRACT_ID

    case_id: str
    assertion_id: str
    baseline_outcome: AssertionOutcomeValue | None = None
    candidate_outcome: AssertionOutcomeValue | None = None
    transition_class: ComparableTransitionClass | None = None
    noncomparability_class: NoncomparabilityClass | None = None
    baseline_assertion_semantic_version: str | None = None
    baseline_assertion_contract_hash: str | None = None
    candidate_assertion_semantic_version: str | None = None
    candidate_assertion_contract_hash: str | None = None
    baseline_protected_regression_classes: tuple[str, ...]
    candidate_protected_regression_classes: tuple[str, ...]
    is_protected_regression: bool
    new_failure_without_comparable_baseline: bool

    @model_validator(mode="after")
    def _transition_invariants(self) -> "AssertionTransition":
        _require_non_blank(self.case_id, "case_id")
        _require_non_blank(self.assertion_id, "assertion_id")
        if (self.transition_class is None) == (self.noncomparability_class is None):
            raise ValueError("exactly one of transition_class or noncomparability_class is required")
        for name in ("baseline_protected_regression_classes",
                     "candidate_protected_regression_classes"):
            classes = list(getattr(self, name))
            for cls in classes:
                _require_non_blank(cls, name)
            if classes != sorted(classes):
                raise ValueError(f"{name} must be sorted")
            if len(classes) != len(set(classes)):
                raise ValueError(f"{name} must be unique")
        baseline_present = (
            self.baseline_outcome is not None
            or self.baseline_assertion_semantic_version is not None
            or self.baseline_assertion_contract_hash is not None
        )
        candidate_present = (
            self.candidate_outcome is not None
            or self.candidate_assertion_semantic_version is not None
            or self.candidate_assertion_contract_hash is not None
        )
        if self.noncomparability_class == "added_assertion":
            if baseline_present or self.baseline_protected_regression_classes:
                raise ValueError("added_assertion must have a null baseline side")
            if self.candidate_outcome is None:
                raise ValueError("added_assertion must have a candidate outcome")
        elif self.noncomparability_class == "removed_assertion":
            if candidate_present or self.candidate_protected_regression_classes:
                raise ValueError("removed_assertion must have a null candidate side")
            if self.baseline_outcome is None:
                raise ValueError("removed_assertion must have a baseline outcome")
        else:
            if self.baseline_outcome is None or self.candidate_outcome is None:
                raise ValueError("a matched transition requires both outcomes present")
        expected_protected = (
            self.transition_class == "regression"
            and self.baseline_protected_regression_classes
            == self.candidate_protected_regression_classes
            and bool(self.baseline_protected_regression_classes)
        )
        if self.is_protected_regression != expected_protected:
            raise ValueError("is_protected_regression is inconsistent with its definition")
        if self.new_failure_without_comparable_baseline:
            ok = (
                self.noncomparability_class == "added_assertion"
                and self.candidate_outcome == "unsatisfied"
            ) or (
                self.transition_class == "coverage_or_certainty_degradation"
                and self.baseline_outcome in _UNDETERMINED
                and self.candidate_outcome == "unsatisfied"
            )
            if not ok:
                raise ValueError(
                    "new_failure_without_comparable_baseline set on a disallowed transition"
                )
        return self

    @property
    def identity(self) -> tuple[str, str]:
        return (self.case_id, self.assertion_id)


class CaseLedgerEntry(_ContractStamped):
    """One derived case-level classification with transition counts."""

    _contract_id: ClassVar[str] = _CASE_LEDGER_CONTRACT_ID

    case_id: str
    baseline_status: CaseStatus
    candidate_status: CaseStatus
    case_class: CaseLedgerClass
    regression_count: int
    improvement_count: int
    degradation_count: int
    noncomparable_count: int
    protected_regression_count: int
    added_assertion_count: int
    removed_assertion_count: int
    new_failure_count: int

    _COUNT_FIELDS: ClassVar[tuple[str, ...]] = (
        "regression_count", "improvement_count", "degradation_count", "noncomparable_count",
        "protected_regression_count", "added_assertion_count", "removed_assertion_count",
        "new_failure_count",
    )

    @model_validator(mode="after")
    def _case_invariants(self) -> "CaseLedgerEntry":
        _require_non_blank(self.case_id, "case_id")
        for name in self._COUNT_FIELDS:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative non-bool integer")
        return self


class ComparisonIssue(_ComparisonStrictModel):
    """One sanitized invalidity/runtime issue; never carries a raw exception."""

    issue_code: str
    message: str
    artifact_reference: str | None = None

    @model_validator(mode="after")
    def _issue_invariants(self) -> "ComparisonIssue":
        _require_non_blank(self.issue_code, "issue_code")
        _require_non_blank(self.message, "message")
        ref = self.artifact_reference
        if ref is not None:
            if ref == "" or ref != ref.strip():
                raise ValueError("artifact_reference must be non-blank")
            if ref.startswith("/") or "\\" in ref or "\x00" in ref or "\n" in ref:
                raise ValueError("artifact_reference must be a normalized relative logical reference")
            if len(ref) >= 2 and ref[1] == ":":
                raise ValueError("artifact_reference must not be a Windows absolute path")
            for part in ref.split("/"):
                if part in (".", "..") or part == "":
                    raise ValueError("artifact_reference must not contain '.', '..' or empty segments")
        return self

    @property
    def identity(self) -> tuple[str, str | None, str]:
        return (self.issue_code, self.artifact_reference, self.message)


class ComparisonManifest(_ContractStamped):
    """The comparison's own identity, source references, status and verdict."""

    _contract_id: ClassVar[str] = _MANIFEST_CONTRACT_ID

    comparison_id: str
    baseline_role: BaselineRole
    comparison_code_commit: str
    baseline: ComparisonRunReference
    candidate: ComparisonRunReference
    comparison_contract_version: str
    comparison_contract_hash: str
    case_assertion_mapping_version: str
    failure_taxonomy_version: str
    execution_status: ExecutionStatus
    gate_verdict: GateVerdict | None = None
    transition_ledger_sha256: str | None = None
    case_ledger_sha256: str | None = None
    transition_count: int | None = None
    case_count: int | None = None
    output_hash: str
    errors: tuple[ComparisonIssue, ...] | None = None

    @model_validator(mode="after")
    def _manifest_invariants(self) -> "ComparisonManifest":
        _validate_run_id_grammar(self.comparison_id, "comparison_id")
        _require_non_blank(self.comparison_code_commit, "comparison_code_commit")
        if self.baseline.eval_run_id == self.candidate.eval_run_id:
            raise ValueError("baseline and candidate eval_run_id must differ")
        if self.comparison_contract_version != _COMPARISON_CONTRACT_VERSION:
            raise ValueError(f"comparison_contract_version must be {_COMPARISON_CONTRACT_VERSION!r}")
        if self.case_assertion_mapping_version != _CASE_ASSERTION_MAPPING_VERSION:
            raise ValueError(
                f"case_assertion_mapping_version must be {_CASE_ASSERTION_MAPPING_VERSION!r}"
            )
        if self.failure_taxonomy_version != _FAILURE_TAXONOMY_VERSION:
            raise ValueError(f"failure_taxonomy_version must be {_FAILURE_TAXONOMY_VERSION!r}")
        expected_hash = model_contract_hash(
            ComparisonManifest, _MANIFEST_CONTRACT_ID, _COMPARISON_CONTRACT_VERSION
        )
        if self.comparison_contract_hash != expected_hash:
            raise ValueError("comparison_contract_hash must be the canonical model contract hash")
        for name in ("transition_ledger_sha256", "case_ledger_sha256"):
            value = getattr(self, name)
            if value is not None and not _is_lower_hex64(value):
                raise ValueError(f"{name} must be a lowercase 64-hex digest when present")
        for name in ("transition_count", "case_count"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)
                                      or value < 0):
                raise ValueError(f"{name} must be a non-negative non-bool integer when present")
        if not _is_lower_hex64(self.output_hash):
            raise ValueError("output_hash must be a lowercase 64-hex digest")
        if self.execution_status == "completed":
            if not (self.baseline.is_complete and self.candidate.is_complete):
                raise ValueError("a completed comparison requires complete source references")
            if self.baseline.execution_status != "completed" \
                    or self.candidate.execution_status != "completed":
                raise ValueError("a completed comparison requires both sources completed")
            if self.gate_verdict is None:
                raise ValueError("a completed comparison requires a gate_verdict")
            if self.transition_ledger_sha256 is None or self.case_ledger_sha256 is None \
                    or self.transition_count is None or self.case_count is None:
                raise ValueError("a completed comparison requires ledger hashes and counts")
            if self.errors is not None:
                raise ValueError("a completed comparison must omit errors")
        else:
            if self.gate_verdict is not None:
                raise ValueError("an invalid/errored comparison must omit gate_verdict")
            if self.transition_ledger_sha256 is not None or self.case_ledger_sha256 is not None \
                    or self.transition_count is not None or self.case_count is not None:
                raise ValueError("an invalid/errored comparison must omit ledger hashes and counts")
            if not self.errors:
                raise ValueError("an invalid/errored comparison requires issues")
            allowed = (_INVALID_ISSUE_CODES if self.execution_status == "invalid"
                       else _ERRORED_ISSUE_CODES)
            if any(i.issue_code not in allowed for i in self.errors):
                raise ValueError("an issue code is not permitted for this execution status")
            ordered = _sorted_issues(self.errors)
            if list(self.errors) != ordered:
                raise ValueError("errors must be deterministically sorted")
            identities = [i.identity for i in self.errors]
            if len(identities) != len(set(identities)):
                raise ValueError("errors must not contain a duplicate identity")
        return self


class ComparisonArtifact(_ComparisonStrictModel):
    """In-memory aggregate: manifest plus transition and case ledgers."""

    manifest: ComparisonManifest
    transitions: tuple[AssertionTransition, ...]
    case_ledger: tuple[CaseLedgerEntry, ...]

    @model_validator(mode="after")
    def _artifact_invariants(self) -> "ComparisonArtifact":
        if self.manifest.execution_status == "completed":
            t_identities = [t.identity for t in self.transitions]
            if t_identities != sorted(t_identities):
                raise ValueError("transitions must be sorted by (case_id, assertion_id)")
            if len(t_identities) != len(set(t_identities)):
                raise ValueError("transitions must not contain a duplicate identity")
            c_ids = [c.case_id for c in self.case_ledger]
            if c_ids != sorted(c_ids):
                raise ValueError("case_ledger must be sorted by case_id")
            if len(c_ids) != len(set(c_ids)):
                raise ValueError("case_ledger must not contain a duplicate case_id")
            if len(self.transitions) != self.manifest.transition_count:
                raise ValueError("transition count does not match the manifest")
            if len(self.case_ledger) != self.manifest.case_count:
                raise ValueError("case count does not match the manifest")
            if _ledger_sha(self.transitions) != self.manifest.transition_ledger_sha256:
                raise ValueError("transition ledger hash does not match the manifest")
            if _ledger_sha(self.case_ledger) != self.manifest.case_ledger_sha256:
                raise ValueError("case ledger hash does not match the manifest")
            expected_verdict = _derive_verdict(self.transitions, self.case_ledger)
            if self.manifest.gate_verdict != expected_verdict:
                raise ValueError("manifest gate_verdict does not match the recomputed verdict")
            if _logical_output_hash(self.manifest, self.transitions, self.case_ledger) \
                    != self.manifest.output_hash:
                raise ValueError("manifest output_hash does not match the recomputed hash")
        else:
            if self.transitions or self.case_ledger:
                raise ValueError("an invalid/errored artifact must have empty ledgers")
            if _logical_output_hash(self.manifest, (), ()) != self.manifest.output_hash:
                raise ValueError("manifest output_hash does not match the recomputed hash")
        return self


class PersistedComparison(_ComparisonStrictModel):
    comparison_id: str
    artifact_reference: str
    sha256: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    artifact: ComparisonArtifact

    @model_validator(mode="after")
    def _persisted_invariants(self) -> "PersistedComparison":
        _validate_persisted_reference(self.comparison_id, self.artifact_reference)
        if self.comparison_id != self.artifact.manifest.comparison_id:
            raise ValueError("wrapper comparison_id does not match the manifest")
        return self


class LoadedComparison(_ComparisonStrictModel):
    comparison_id: str
    artifact_reference: str
    sha256: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    artifact: ComparisonArtifact

    @model_validator(mode="after")
    def _loaded_invariants(self) -> "LoadedComparison":
        _validate_persisted_reference(self.comparison_id, self.artifact_reference)
        if self.comparison_id != self.artifact.manifest.comparison_id:
            raise ValueError("wrapper comparison_id does not match the manifest")
        return self


def _validate_persisted_reference(comparison_id: str, reference: str) -> None:
    expected = f"{_COMPARISONS_DIR}/{comparison_id}/{_MANIFEST_FILENAME}"
    if reference != expected:
        raise ValueError(f"artifact_reference must equal {expected!r}")
    if reference.startswith("/") or "\\" in reference or "\x00" in reference or "\n" in reference:
        raise ValueError("artifact_reference must be a normalized relative logical reference")
    for part in reference.split("/"):
        if part in (".", "..") or part == "":
            raise ValueError("artifact_reference must not contain '.', '..' or empty segments")


# --- Exceptions -----------------------------------------------------------


class ComparisonError(Exception):
    """Abstract base for Slice 11 comparison failures; never raised directly."""

    def __init__(
        self, message: str, *, comparison_id: str | None = None,
        eval_run_id: str | None = None, artifact_reference: str | None = None,
    ) -> None:
        super().__init__(message)
        self.comparison_id = comparison_id
        self.eval_run_id = eval_run_id
        self.artifact_reference = artifact_reference


class ComparisonValidityError(ComparisonError):
    """A completed comparison cannot be produced (e.g. a non-completed source)."""


class ComparisonBindingError(ComparisonError):
    """A source wrapper/manifest/result/config identity does not bind."""


class ComparisonMetadataError(ComparisonError):
    """A metadata snapshot fails coverage, content, or class validation."""


class ComparisonBindingMismatchError(ComparisonError):
    """A persisted aggregate's recomputed hash/count/reference disagrees."""


class ComparisonExistsError(ComparisonError):
    """The comparison output directory already exists in some form."""


class ComparisonArtifactMissingError(ComparisonError):
    """A required comparison artifact does not exist."""


class ComparisonArtifactNotAFileError(ComparisonError):
    """A comparison artifact or a parent is not a regular file/directory."""


class ComparisonArtifactReadError(ComparisonError):
    """Reading a comparison artifact failed."""


class ComparisonDecodeError(ComparisonError):
    """A comparison artifact's bytes are not valid UTF-8."""


class ComparisonJsonError(ComparisonError):
    """A comparison artifact is not acceptable strict JSON/JSONL."""

    def __init__(
        self, message: str, *, duplicate_key: str | None = None,
        constant_name: str | None = None, **kw: Any,
    ) -> None:
        super().__init__(message, **kw)
        self.duplicate_key = duplicate_key
        self.constant_name = constant_name


class ComparisonTopLevelTypeError(ComparisonError):
    """A parsed comparison document/line is not a JSON object."""


class ComparisonModelValidationError(ComparisonError):
    """A comparison document failed model validation."""

    def __init__(self, message: str, *, field_locations: tuple[str, ...] = (), **kw: Any) -> None:
        super().__init__(message, **kw)
        self.field_locations = field_locations


class ComparisonWriteError(ComparisonError):
    """Writing a comparison artifact failed."""


class ComparisonDestinationHashMismatchError(ComparisonError):
    """A written comparison artifact re-read to a different hash."""

    def __init__(
        self, message: str, *, expected_sha256: str | None = None,
        observed_sha256: str | None = None, **kw: Any,
    ) -> None:
        super().__init__(message, **kw)
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


# --- Canonical serialization + hashing ------------------------------------


def _canonical_line(record: BaseModel) -> bytes:
    return canonical_contract_bytes(record.model_dump(mode="json", exclude_unset=True))


def _ledger_bytes(records: tuple[BaseModel, ...]) -> bytes:
    return b"".join(_canonical_line(r) + b"\n" for r in records)


def _ledger_sha(records: tuple[BaseModel, ...]) -> str:
    return sha256_bytes(_ledger_bytes(records))


def _sorted_issues(issues: tuple[ComparisonIssue, ...]) -> list[ComparisonIssue]:
    return sorted(
        issues,
        key=lambda i: (i.issue_code, i.artifact_reference is not None,
                       i.artifact_reference or "", i.message),
    )


def _reference_hash_payload(ref: ComparisonRunReference) -> dict[str, Any]:
    return {
        "eval_run_id": ref.eval_run_id,
        "run_manifest_sha256": ref.run_manifest_sha256,
        "result_sha256": ref.result_sha256,
        "assertion_outcomes_sha256": ref.assertion_outcomes_sha256,
        "scoring_config_version": ref.scoring_config_version,
        "scoring_config_sha256": ref.scoring_config_sha256,
        "metadata_mapping_version": ref.metadata_mapping_version,
        "metadata_failure_taxonomy_version": ref.metadata_failure_taxonomy_version,
        "metadata_hash": ref.metadata_hash,
        "source_code_commit": ref.source_code_commit,
        "execution_status": ref.execution_status,
        "gate_verdict": ref.gate_verdict,
        "stage": ref.stage,
    }


def _logical_output_hash(
    manifest: ComparisonManifest,
    transitions: tuple[AssertionTransition, ...],
    case_ledger: tuple[CaseLedgerEntry, ...],
) -> str:
    completed = manifest.execution_status == "completed"
    payload = {
        "baseline_role": manifest.baseline_role,
        "comparison_code_commit": manifest.comparison_code_commit,
        "baseline": _reference_hash_payload(manifest.baseline),
        "candidate": _reference_hash_payload(manifest.candidate),
        "comparison_contract_version": manifest.comparison_contract_version,
        "comparison_contract_hash": manifest.comparison_contract_hash,
        "case_assertion_mapping_version": manifest.case_assertion_mapping_version,
        "failure_taxonomy_version": manifest.failure_taxonomy_version,
        "transition_ledger_sha256": _ledger_sha(transitions) if completed else None,
        "case_ledger_sha256": _ledger_sha(case_ledger) if completed else None,
        "transition_count": len(transitions) if completed else None,
        "case_count": len(case_ledger) if completed else None,
        "execution_status": manifest.execution_status,
        "gate_verdict": manifest.gate_verdict,
        "issues": [
            {"issue_code": i.issue_code, "message": i.message,
             "artifact_reference": i.artifact_reference}
            for i in _sorted_issues(manifest.errors or ())
        ],
    }
    return sha256_bytes(canonical_contract_bytes(payload))


def _metadata_hash(metadata: AssertionComparisonMetadata) -> str:
    return sha256_bytes(canonical_contract_bytes(metadata.model_dump(mode="json", exclude_unset=True)))


# --- Source binding -------------------------------------------------------


def _bind_source(
    *, side: str, comparison_id: str, manifest: LoadedEvaluationRunManifest,
    result: LoadedEvaluationResult, outcomes: LoadedAssertionOutcomes,
    scoring_config: LoadedScoringGateConfig, metadata: AssertionComparisonMetadata,
) -> ComparisonRunReference:
    for name, obj, typ in (
        (f"{side}_manifest", manifest, LoadedEvaluationRunManifest),
        (f"{side}_result", result, LoadedEvaluationResult),
        (f"{side}_outcomes", outcomes, LoadedAssertionOutcomes),
        (f"{side}_scoring_config", scoring_config, LoadedScoringGateConfig),
        (f"{side}_metadata", metadata, AssertionComparisonMetadata),
    ):
        if not isinstance(obj, typ):
            raise TypeError(f"{name} must be a {typ.__name__}, got {type(obj).__name__}")
    m = manifest.manifest
    run_id = m.eval_run_id
    if not _is_lower_hex64(manifest.sha256):
        raise ComparisonBindingError(f"{side} run manifest sha256 is not a lowercase 64-hex digest",
                                     comparison_id=comparison_id, eval_run_id=run_id)
    # Result binding + Slice 10 projection.
    r = result.result
    if result.eval_run_id != run_id or r.eval_run_id != run_id:
        raise ComparisonBindingError(f"{side} result eval_run_id does not bind to the run manifest",
                                     comparison_id=comparison_id, eval_run_id=run_id)
    if r.dataset_version != m.case_set_version:
        raise ComparisonBindingError(f"{side} result dataset_version does not equal case_set_version",
                                     comparison_id=comparison_id, eval_run_id=run_id)
    if r.execution_status != "completed":
        raise ComparisonValidityError(f"{side} source result is not completed",
                                      comparison_id=comparison_id, eval_run_id=run_id)
    if r.gate_verdict is None:
        raise ComparisonBindingError(f"{side} completed source result has no gate_verdict",
                                     comparison_id=comparison_id, eval_run_id=run_id)
    if not _is_lower_hex64(result.sha256):
        raise ComparisonBindingError(f"{side} result sha256 is not a lowercase 64-hex digest",
                                     comparison_id=comparison_id, eval_run_id=run_id)
    metrics = r.metrics
    if set(metrics) != {"provenance", "gate_outcomes", "critical_finding_ids"}:
        raise ComparisonBindingError(f"{side} result metrics lacks the locked three-key projection",
                                     comparison_id=comparison_id, eval_run_id=run_id)
    prov = metrics["provenance"]
    if not isinstance(prov, dict) or set(prov) != {
        "case_set_version", "case_set_hash", "scoring_gate_config_version",
        "scoring_gate_config_hash", "metric_report_sha256",
    }:
        raise ComparisonBindingError(f"{side} result provenance lacks the locked five keys",
                                     comparison_id=comparison_id, eval_run_id=run_id)
    if prov["case_set_version"] != m.case_set_version or prov["case_set_hash"] != m.case_set_hash \
            or prov["scoring_gate_config_version"] != m.scoring_gate_config_version \
            or prov["scoring_gate_config_hash"] != m.scoring_gate_config_hash:
        raise ComparisonBindingError(f"{side} result provenance does not bind the run manifest",
                                     comparison_id=comparison_id, eval_run_id=run_id)
    if not _is_lower_hex64(prov["metric_report_sha256"]):
        raise ComparisonBindingError(f"{side} completed result has no valid metric_report_sha256",
                                     comparison_id=comparison_id, eval_run_id=run_id)
    # Assertion-outcome binding.
    if outcomes.eval_run_id != run_id:
        raise ComparisonBindingError(f"{side} assertion-outcomes wrapper run id does not bind",
                                     comparison_id=comparison_id, eval_run_id=run_id)
    if not _is_lower_hex64(outcomes.sha256):
        raise ComparisonBindingError(f"{side} assertion-outcomes sha256 is not lowercase 64-hex",
                                     comparison_id=comparison_id, eval_run_id=run_id)
    seen: set[tuple[str, str]] = set()
    for o in outcomes.outcomes:
        if o.eval_run_id != run_id:
            raise ComparisonBindingError(f"{side} assertion outcome run id does not bind",
                                         comparison_id=comparison_id, eval_run_id=run_id)
        key = (o.case_id, o.assertion_id)
        if key in seen:
            raise ComparisonBindingError(
                f"{side} assertion outcomes contain a duplicate (case_id, assertion_id)",
                comparison_id=comparison_id, eval_run_id=run_id)
        seen.add(key)
    # Scoring-config binding (independent per source).
    if scoring_config.version != scoring_config.config.config_version \
            or scoring_config.version != m.scoring_gate_config_version:
        raise ComparisonBindingError(f"{side} scoring-config version does not bind the run manifest",
                                     comparison_id=comparison_id, eval_run_id=run_id)
    if scoring_config.sha256 != m.scoring_gate_config_hash:
        raise ComparisonBindingError(f"{side} scoring-config hash does not bind the run manifest",
                                     comparison_id=comparison_id, eval_run_id=run_id)
    if not _is_lower_hex64(scoring_config.sha256):
        raise ComparisonBindingError(f"{side} scoring-config sha256 is not lowercase 64-hex",
                                     comparison_id=comparison_id, eval_run_id=run_id)
    # Metadata binding.
    _bind_metadata(side=side, comparison_id=comparison_id, run_id=run_id, outcomes=outcomes,
                   scoring_config=scoring_config, metadata=metadata)
    return ComparisonRunReference(
        eval_run_id=run_id, run_manifest_sha256=manifest.sha256, result_sha256=result.sha256,
        assertion_outcomes_sha256=outcomes.sha256, scoring_config_version=scoring_config.version,
        scoring_config_sha256=scoring_config.sha256, metadata_mapping_version=metadata.mapping_version,
        metadata_failure_taxonomy_version=metadata.failure_taxonomy_version,
        metadata_hash=_metadata_hash(metadata), source_code_commit=m.code_commit,
        execution_status=r.execution_status, gate_verdict=r.gate_verdict, stage=r.stage,
    )


def _bind_metadata(
    *, side: str, comparison_id: str, run_id: str, outcomes: LoadedAssertionOutcomes,
    scoring_config: LoadedScoringGateConfig, metadata: AssertionComparisonMetadata,
) -> None:
    if metadata.eval_run_id != run_id:
        raise ComparisonMetadataError(f"{side} metadata run id does not bind the run manifest",
                                      comparison_id=comparison_id, eval_run_id=run_id)
    outcome_by_id = {(o.case_id, o.assertion_id): o for o in outcomes.outcomes}
    meta_by_id = metadata.by_identity
    if set(meta_by_id) != set(outcome_by_id):
        raise ComparisonMetadataError(
            f"{side} metadata identities do not exactly cover the assertion outcomes",
            comparison_id=comparison_id, eval_run_id=run_id)
    declared = set(scoring_config.config.protected_regression_classes)
    for identity, entry in meta_by_id.items():
        o = outcome_by_id[identity]
        if entry.assertion_semantic_version != o.assertion_semantic_version \
                or entry.assertion_contract_hash != o.assertion_contract_hash:
            raise ComparisonMetadataError(
                f"{side} metadata entry does not match its own run's assertion outcome",
                comparison_id=comparison_id, eval_run_id=run_id)
        for cls in entry.protected_regression_classes:
            if cls not in declared:
                raise ComparisonMetadataError(
                    f"{side} metadata references protected class {cls!r} not declared by the "
                    "scoring configuration", comparison_id=comparison_id, eval_run_id=run_id)


# --- Matching + classification --------------------------------------------


def _axes(semver: str | None, chash: str | None) -> frozenset[str]:
    axes = set()
    if semver is not None:
        axes.add("semver")
    if chash is not None:
        axes.add("chash")
    return frozenset(axes)


def _run_level_class(
    bm: EvaluationRunManifest, cm: EvaluationRunManifest,
    bref: ComparisonRunReference, cref: ComparisonRunReference,
    bmeta: AssertionComparisonMetadata, cmeta: AssertionComparisonMetadata,
    b_entry: AssertionComparisonMetadataEntry, c_entry: AssertionComparisonMetadataEntry,
    b_out: Any, c_out: Any,
) -> NoncomparabilityClass | None:
    """First-applicable run/assertion-level noncomparability class, or None."""
    if bm.case_set_version != cm.case_set_version or bm.case_set_hash != cm.case_set_hash:
        return "changed_gold"
    if bm.prediction_run_manifest_hash != cm.prediction_run_manifest_hash:
        return "changed_input_packet"
    if bm.validator_bundle_version != cm.validator_bundle_version \
            or bm.validator_bundle_hash != cm.validator_bundle_hash:
        return "changed_validator_contract"
    # Assertion contract compatibility.
    b_axes = _axes(b_out.assertion_semantic_version, b_out.assertion_contract_hash)
    c_axes = _axes(c_out.assertion_semantic_version, c_out.assertion_contract_hash)
    shared = b_axes & c_axes
    if "semver" in shared and \
            b_out.assertion_semantic_version != c_out.assertion_semantic_version:
        return "changed_assertion_contract"
    if "chash" in shared and \
            b_out.assertion_contract_hash != c_out.assertion_contract_hash:
        return "changed_assertion_contract"
    if b_axes != c_axes:
        return "noncomparable_contract"
    if b_entry.protected_regression_classes != c_entry.protected_regression_classes:
        return "changed_assertion_contract"
    # Remaining run-level comparability axes.
    if bm.registry_snapshot_hash != cm.registry_snapshot_hash \
            or bm.scoring_gate_config_version != cm.scoring_gate_config_version \
            or bm.scoring_gate_config_hash != cm.scoring_gate_config_hash \
            or bm.code_commit != cm.code_commit \
            or bm.pydantic_runtime_version != cm.pydantic_runtime_version \
            or bref.stage != cref.stage \
            or bmeta.mapping_version != cmeta.mapping_version \
            or bmeta.failure_taxonomy_version != cmeta.failure_taxonomy_version:
        return "noncomparable_contract"
    return None


def _classify_outcomes(
    baseline: AssertionOutcomeValue, candidate: AssertionOutcomeValue,
) -> tuple[ComparableTransitionClass, bool]:
    """Return (transition_class, new_failure_flag) for a compatible pair."""
    if baseline == candidate:
        return "unchanged", False
    if baseline == "satisfied":
        if candidate == "unsatisfied":
            return "regression", False
        return "coverage_or_certainty_degradation", False
    if candidate == "satisfied":
        return "improvement", False
    if baseline == "unsatisfied":
        # candidate in {indeterminate, not_applicable, not_evaluated}
        return "improvement", False
    if candidate == "unsatisfied":
        # baseline in {indeterminate, not_applicable, not_evaluated}
        return "coverage_or_certainty_degradation", True
    # Both in {indeterminate, not_applicable, not_evaluated}, unequal.
    if _EVIDENCE_RANK[candidate] > _EVIDENCE_RANK[baseline]:
        return "improvement", False
    return "coverage_or_certainty_degradation", False


def _build_transitions(
    *, bm: EvaluationRunManifest, cm: EvaluationRunManifest,
    bref: ComparisonRunReference, cref: ComparisonRunReference,
    b_outcomes: LoadedAssertionOutcomes, c_outcomes: LoadedAssertionOutcomes,
    bmeta: AssertionComparisonMetadata, cmeta: AssertionComparisonMetadata,
) -> tuple[AssertionTransition, ...]:
    b_by = {(o.case_id, o.assertion_id): o for o in b_outcomes.outcomes}
    c_by = {(o.case_id, o.assertion_id): o for o in c_outcomes.outcomes}
    b_meta = bmeta.by_identity
    c_meta = cmeta.by_identity
    stamp = _contract_stamp(_TRANSITION_CONTRACT_ID, AssertionTransition)
    transitions: list[AssertionTransition] = []
    for identity in sorted(set(b_by) | set(c_by)):
        case_id, assertion_id = identity
        base = dict(contract=stamp, case_id=case_id, assertion_id=assertion_id)
        if identity in b_by and identity not in c_by:  # removed
            b_out = b_by[identity]
            transitions.append(AssertionTransition.model_validate({
                **base, "baseline_outcome": b_out.outcome, "candidate_outcome": None,
                "transition_class": None, "noncomparability_class": "removed_assertion",
                "baseline_assertion_semantic_version": b_out.assertion_semantic_version,
                "baseline_assertion_contract_hash": b_out.assertion_contract_hash,
                "candidate_assertion_semantic_version": None,
                "candidate_assertion_contract_hash": None,
                "baseline_protected_regression_classes": b_meta[identity].protected_regression_classes,
                "candidate_protected_regression_classes": (),
                "is_protected_regression": False,
                "new_failure_without_comparable_baseline": False,
            }))
            continue
        if identity in c_by and identity not in b_by:  # added
            c_out = c_by[identity]
            new_failure = c_out.outcome == "unsatisfied"
            transitions.append(AssertionTransition.model_validate({
                **base, "baseline_outcome": None, "candidate_outcome": c_out.outcome,
                "transition_class": None, "noncomparability_class": "added_assertion",
                "baseline_assertion_semantic_version": None,
                "baseline_assertion_contract_hash": None,
                "candidate_assertion_semantic_version": c_out.assertion_semantic_version,
                "candidate_assertion_contract_hash": c_out.assertion_contract_hash,
                "baseline_protected_regression_classes": (),
                "candidate_protected_regression_classes": c_meta[identity].protected_regression_classes,
                "is_protected_regression": False,
                "new_failure_without_comparable_baseline": new_failure,
            }))
            continue
        # Matched.
        b_out, c_out = b_by[identity], c_by[identity]
        b_entry, c_entry = b_meta[identity], c_meta[identity]
        nonc = _run_level_class(bm, cm, bref, cref, bmeta, cmeta, b_entry, c_entry, b_out, c_out)
        common = {
            **base, "baseline_outcome": b_out.outcome, "candidate_outcome": c_out.outcome,
            "baseline_assertion_semantic_version": b_out.assertion_semantic_version,
            "baseline_assertion_contract_hash": b_out.assertion_contract_hash,
            "candidate_assertion_semantic_version": c_out.assertion_semantic_version,
            "candidate_assertion_contract_hash": c_out.assertion_contract_hash,
            "baseline_protected_regression_classes": b_entry.protected_regression_classes,
            "candidate_protected_regression_classes": c_entry.protected_regression_classes,
        }
        if nonc is not None:
            transitions.append(AssertionTransition.model_validate({
                **common, "transition_class": None, "noncomparability_class": nonc,
                "is_protected_regression": False,
                "new_failure_without_comparable_baseline": False,
            }))
            continue
        cls, new_failure = _classify_outcomes(b_out.outcome, c_out.outcome)
        is_protected = (
            cls == "regression"
            and b_entry.protected_regression_classes == c_entry.protected_regression_classes
            and bool(b_entry.protected_regression_classes)
        )
        transitions.append(AssertionTransition.model_validate({
            **common, "transition_class": cls, "noncomparability_class": None,
            "is_protected_regression": is_protected,
            "new_failure_without_comparable_baseline": new_failure,
        }))
    return tuple(transitions)


# --- Case ledger ----------------------------------------------------------


def _case_status(outcomes: list[Any] | None) -> CaseStatus:
    if outcomes is None:
        return "missing"
    values = {o.outcome for o in outcomes}
    if "unsatisfied" in values:
        return "failing"
    if "satisfied" in values:
        return "passing"
    if "indeterminate" in values or "not_evaluated" in values:
        return "indeterminate"
    return "noncomparable"


def _build_case_ledger(
    *, transitions: tuple[AssertionTransition, ...],
    b_outcomes: LoadedAssertionOutcomes, c_outcomes: LoadedAssertionOutcomes,
) -> tuple[CaseLedgerEntry, ...]:
    b_cases: dict[str, list[Any]] = {}
    c_cases: dict[str, list[Any]] = {}
    for o in b_outcomes.outcomes:
        b_cases.setdefault(o.case_id, []).append(o)
    for o in c_outcomes.outcomes:
        c_cases.setdefault(o.case_id, []).append(o)
    trans_by_case: dict[str, list[AssertionTransition]] = {}
    for t in transitions:
        trans_by_case.setdefault(t.case_id, []).append(t)
    stamp = _contract_stamp(_CASE_LEDGER_CONTRACT_ID, CaseLedgerEntry)
    entries: list[CaseLedgerEntry] = []
    for case_id in sorted(set(b_cases) | set(c_cases)):
        b_status = _case_status(b_cases.get(case_id))
        c_status = _case_status(c_cases.get(case_id))
        case_trans = trans_by_case.get(case_id, [])
        counts = _case_counts(case_trans)
        compatible = [t for t in case_trans if t.transition_class is not None]
        case_class = _classify_case(b_status, c_status, case_trans, compatible)
        entries.append(CaseLedgerEntry.model_validate({
            "contract": stamp, "case_id": case_id, "baseline_status": b_status,
            "candidate_status": c_status, "case_class": case_class, **counts,
        }))
    return tuple(entries)


def _case_counts(case_trans: list[AssertionTransition]) -> dict[str, int]:
    return {
        "regression_count": sum(1 for t in case_trans if t.transition_class == "regression"),
        "improvement_count": sum(1 for t in case_trans if t.transition_class == "improvement"),
        "degradation_count": sum(
            1 for t in case_trans if t.transition_class == "coverage_or_certainty_degradation"),
        "noncomparable_count": sum(1 for t in case_trans if t.noncomparability_class is not None),
        "protected_regression_count": sum(1 for t in case_trans if t.is_protected_regression),
        "added_assertion_count": sum(
            1 for t in case_trans if t.noncomparability_class == "added_assertion"),
        "removed_assertion_count": sum(
            1 for t in case_trans if t.noncomparability_class == "removed_assertion"),
        "new_failure_count": sum(
            1 for t in case_trans if t.new_failure_without_comparable_baseline),
    }


def _classify_case(
    b_status: CaseStatus, c_status: CaseStatus,
    case_trans: list[AssertionTransition], compatible: list[AssertionTransition],
) -> CaseLedgerClass:
    if b_status == "missing":
        return "added_case"
    if c_status == "missing":
        return "removed_case"
    if b_status == "noncomparable" or c_status == "noncomparable" or not compatible:
        return "noncomparable"
    has_protected = any(t.is_protected_regression for t in case_trans)
    has_regression = any(t.transition_class == "regression" for t in case_trans)
    has_degradation = any(
        t.transition_class == "coverage_or_certainty_degradation" for t in case_trans)
    has_noncomparable = any(t.noncomparability_class is not None for t in case_trans)
    has_new_failure = any(t.new_failure_without_comparable_baseline for t in case_trans)
    has_improvement = any(t.transition_class == "improvement" for t in case_trans)
    degraded = has_degradation or has_noncomparable or has_new_failure
    if b_status == "failing" and c_status == "failing" and has_protected:
        return "additional_protected_regression"
    if b_status == "passing" and c_status == "failing":
        return "newly_failing"
    if b_status == "failing" and c_status == "passing":
        return "newly_passing"
    if b_status == "passing" and c_status == "passing" and degraded:
        return "degraded_but_still_passing"
    if b_status == "failing" and c_status == "failing" and (has_regression or degraded):
        return "degraded_and_still_failing"
    if b_status == "failing" and c_status == "failing" and has_improvement:
        return "improved_but_still_failing"
    if b_status == "indeterminate" or c_status == "indeterminate":
        return "indeterminate"
    if b_status == "passing" and c_status == "passing":
        return "unchanged_passing"
    if b_status == "failing" and c_status == "failing":
        return "unchanged_failing"
    return "indeterminate"


# --- Verdict --------------------------------------------------------------


def _derive_verdict(
    transitions: tuple[AssertionTransition, ...], case_ledger: tuple[CaseLedgerEntry, ...],
) -> GateVerdict:
    if any(t.is_protected_regression for t in transitions):
        return "fail"
    compatible = [t for t in transitions if t.transition_class is not None]
    indeterminate = (
        not compatible
        or any(t.noncomparability_class is not None for t in transitions)
        or any(t.transition_class == "coverage_or_certainty_degradation" for t in transitions)
        or any(t.new_failure_without_comparable_baseline for t in transitions)
        or any(c.baseline_status == "indeterminate" or c.candidate_status == "indeterminate"
               or c.case_class == "indeterminate" for c in case_ledger)
    )
    return "indeterminate" if indeterminate else "pass"


# --- Public constructors --------------------------------------------------


def assess_comparison(
    *,
    comparison_id: str,
    baseline_role: BaselineRole,
    comparison_code_commit: str,
    baseline_manifest: LoadedEvaluationRunManifest,
    candidate_manifest: LoadedEvaluationRunManifest,
    baseline_result: LoadedEvaluationResult,
    candidate_result: LoadedEvaluationResult,
    baseline_outcomes: LoadedAssertionOutcomes,
    candidate_outcomes: LoadedAssertionOutcomes,
    baseline_scoring_config: LoadedScoringGateConfig,
    candidate_scoring_config: LoadedScoringGateConfig,
    baseline_metadata: AssertionComparisonMetadata,
    candidate_metadata: AssertionComparisonMetadata,
) -> ComparisonArtifact:
    """Assess a completed comparison. Pure; raises typed errors on invalid input."""
    cid = _require_comparison_id(comparison_id)
    _require_baseline_role(baseline_role)
    _require_non_blank_arg(comparison_code_commit, "comparison_code_commit")
    if baseline_manifest.__class__ is LoadedEvaluationRunManifest \
            and candidate_manifest.__class__ is LoadedEvaluationRunManifest:
        if baseline_manifest.manifest.eval_run_id == candidate_manifest.manifest.eval_run_id:
            raise ComparisonValidityError("baseline and candidate eval_run_id must differ",
                                          comparison_id=cid)
    bref = _bind_source(
        side="baseline", comparison_id=cid, manifest=baseline_manifest, result=baseline_result,
        outcomes=baseline_outcomes, scoring_config=baseline_scoring_config,
        metadata=baseline_metadata)
    cref = _bind_source(
        side="candidate", comparison_id=cid, manifest=candidate_manifest, result=candidate_result,
        outcomes=candidate_outcomes, scoring_config=candidate_scoring_config,
        metadata=candidate_metadata)
    transitions = _build_transitions(
        bm=baseline_manifest.manifest, cm=candidate_manifest.manifest, bref=bref, cref=cref,
        b_outcomes=baseline_outcomes, c_outcomes=candidate_outcomes,
        bmeta=baseline_metadata, cmeta=candidate_metadata)
    case_ledger = _build_case_ledger(
        transitions=transitions, b_outcomes=baseline_outcomes, c_outcomes=candidate_outcomes)
    verdict = _derive_verdict(transitions, case_ledger)
    manifest = _build_manifest(
        cid=cid, baseline_role=baseline_role, comparison_code_commit=comparison_code_commit,
        baseline=bref, candidate=cref, execution_status="completed", gate_verdict=verdict,
        transitions=transitions, case_ledger=case_ledger, errors=None)
    return ComparisonArtifact(manifest=manifest, transitions=transitions, case_ledger=case_ledger)


def build_invalid_comparison(
    *,
    comparison_id: str,
    baseline_role: BaselineRole,
    comparison_code_commit: str,
    baseline_reference: ComparisonRunReference,
    candidate_reference: ComparisonRunReference,
    issues: tuple[ComparisonIssue, ...],
) -> ComparisonArtifact:
    """Construct an invalid comparison from partial-capable references."""
    return _build_terminal(
        "invalid", _INVALID_ISSUE_CODES, comparison_id=comparison_id, baseline_role=baseline_role,
        comparison_code_commit=comparison_code_commit, baseline_reference=baseline_reference,
        candidate_reference=candidate_reference, issues=issues)


def build_errored_comparison(
    *,
    comparison_id: str,
    baseline_role: BaselineRole,
    comparison_code_commit: str,
    baseline_reference: ComparisonRunReference,
    candidate_reference: ComparisonRunReference,
    issues: tuple[ComparisonIssue, ...],
) -> ComparisonArtifact:
    """Construct an errored comparison (runtime_failure only)."""
    return _build_terminal(
        "errored", _ERRORED_ISSUE_CODES, comparison_id=comparison_id, baseline_role=baseline_role,
        comparison_code_commit=comparison_code_commit, baseline_reference=baseline_reference,
        candidate_reference=candidate_reference, issues=issues)


def _build_terminal(
    status: str, allowed: frozenset[str], *, comparison_id: str, baseline_role: str,
    comparison_code_commit: str, baseline_reference: ComparisonRunReference,
    candidate_reference: ComparisonRunReference, issues: tuple[ComparisonIssue, ...],
) -> ComparisonArtifact:
    cid = _require_comparison_id(comparison_id)
    _require_baseline_role(baseline_role)
    _require_non_blank_arg(comparison_code_commit, "comparison_code_commit")
    for name, ref in (("baseline_reference", baseline_reference),
                      ("candidate_reference", candidate_reference)):
        if not isinstance(ref, ComparisonRunReference):
            raise TypeError(f"{name} must be a ComparisonRunReference, got {type(ref).__name__}")
    if baseline_reference.eval_run_id == candidate_reference.eval_run_id:
        raise ComparisonValidityError("baseline and candidate eval_run_id must differ",
                                      comparison_id=cid)
    if not issues:
        raise ComparisonValidityError(f"a {status} comparison requires at least one issue",
                                      comparison_id=cid)
    seen: set[tuple[str, str | None, str]] = set()
    for issue in issues:
        if not isinstance(issue, ComparisonIssue):
            raise TypeError("issues must be ComparisonIssue instances")
        if issue.issue_code not in allowed:
            raise ComparisonValidityError(
                f"issue_code {issue.issue_code!r} is not permitted for a {status} comparison",
                comparison_id=cid)
        if issue.identity in seen:
            raise ComparisonValidityError("duplicate issue identity", comparison_id=cid)
        seen.add(issue.identity)
    ordered = tuple(_sorted_issues(issues))
    manifest = _build_manifest(
        cid=cid, baseline_role=baseline_role, comparison_code_commit=comparison_code_commit,
        baseline=baseline_reference, candidate=candidate_reference, execution_status=status,
        gate_verdict=None, transitions=(), case_ledger=(), errors=ordered)
    return ComparisonArtifact(manifest=manifest, transitions=(), case_ledger=())


def _build_manifest(
    *, cid: str, baseline_role: str, comparison_code_commit: str,
    baseline: ComparisonRunReference, candidate: ComparisonRunReference,
    execution_status: str, gate_verdict: GateVerdict | None,
    transitions: tuple[AssertionTransition, ...], case_ledger: tuple[CaseLedgerEntry, ...],
    errors: tuple[ComparisonIssue, ...] | None,
) -> ComparisonManifest:
    completed = execution_status == "completed"
    stamp = _contract_stamp(_MANIFEST_CONTRACT_ID, ComparisonManifest)
    partial = {
        "contract": stamp, "comparison_id": cid, "baseline_role": baseline_role,
        "comparison_code_commit": comparison_code_commit, "baseline": baseline,
        "candidate": candidate, "comparison_contract_version": _COMPARISON_CONTRACT_VERSION,
        "comparison_contract_hash": stamp["contract_hash"],
        "case_assertion_mapping_version": _CASE_ASSERTION_MAPPING_VERSION,
        "failure_taxonomy_version": _FAILURE_TAXONOMY_VERSION,
        "execution_status": execution_status, "gate_verdict": gate_verdict,
        "transition_ledger_sha256": _ledger_sha(transitions) if completed else None,
        "case_ledger_sha256": _ledger_sha(case_ledger) if completed else None,
        "transition_count": len(transitions) if completed else None,
        "case_count": len(case_ledger) if completed else None,
        "errors": errors,
    }
    # output_hash needs a manifest-shaped object; build a preliminary manifest with a
    # placeholder hash is not possible (frozen + validated), so compute directly.
    output_hash = _output_hash_from_parts(partial, transitions, case_ledger)
    return ComparisonManifest.model_validate({**partial, "output_hash": output_hash})


def _output_hash_from_parts(
    partial: dict[str, Any], transitions: tuple[AssertionTransition, ...],
    case_ledger: tuple[CaseLedgerEntry, ...],
) -> str:
    completed = partial["execution_status"] == "completed"
    payload = {
        "baseline_role": partial["baseline_role"],
        "comparison_code_commit": partial["comparison_code_commit"],
        "baseline": _reference_hash_payload(partial["baseline"]),
        "candidate": _reference_hash_payload(partial["candidate"]),
        "comparison_contract_version": partial["comparison_contract_version"],
        "comparison_contract_hash": partial["comparison_contract_hash"],
        "case_assertion_mapping_version": partial["case_assertion_mapping_version"],
        "failure_taxonomy_version": partial["failure_taxonomy_version"],
        "transition_ledger_sha256": _ledger_sha(transitions) if completed else None,
        "case_ledger_sha256": _ledger_sha(case_ledger) if completed else None,
        "transition_count": len(transitions) if completed else None,
        "case_count": len(case_ledger) if completed else None,
        "execution_status": partial["execution_status"],
        "gate_verdict": partial["gate_verdict"],
        "issues": [
            {"issue_code": i.issue_code, "message": i.message,
             "artifact_reference": i.artifact_reference}
            for i in _sorted_issues(partial["errors"] or ())
        ],
    }
    return sha256_bytes(canonical_contract_bytes(payload))


def _require_comparison_id(comparison_id: str) -> str:
    if not isinstance(comparison_id, str):
        raise ComparisonValidityError(
            f"comparison_id must be a string, got {type(comparison_id).__name__}")
    try:
        return _validate_run_id_grammar(comparison_id, "comparison_id")
    except ValueError as exc:
        raise ComparisonValidityError(str(exc)) from exc


def _require_baseline_role(role: Any) -> str:
    valid = {
        "current_frozen_prompt", "accepted_release", "previous_candidate",
        "model_upgrade_baseline", "validator_bridge_baseline", "reproducibility_baseline",
    }
    if role not in valid:
        raise ComparisonValidityError(f"baseline_role {role!r} is not a governed role")
    return role


def _require_non_blank_arg(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ComparisonValidityError(
            f"{name} must be a non-empty string without leading or trailing whitespace")
    return value


# --- Persistence ----------------------------------------------------------


def _validate_root(root: str | Path) -> Path:
    if not isinstance(root, (str, Path)):
        raise ComparisonValidityError(
            f"eval_root must be an explicit str or Path root, got {type(root).__name__}")
    if isinstance(root, str) and root == "":
        raise ComparisonValidityError("eval_root must not be an empty string")
    path = Path(root)
    if not path.exists():
        raise ComparisonValidityError(f"eval_root {str(root)!r} does not exist")
    if not path.is_dir():
        raise ComparisonValidityError(f"eval_root {str(root)!r} is not a directory")
    return path.resolve()


def _reverify_aggregate(artifact: ComparisonArtifact) -> None:
    """Recompute ledgers/hashes/verdict and compare with the manifest before write."""
    m = artifact.manifest
    if m.execution_status == "completed":
        if len(artifact.transitions) != m.transition_count \
                or len(artifact.case_ledger) != m.case_count:
            raise ComparisonBindingMismatchError("ledger counts disagree with the manifest",
                                                 comparison_id=m.comparison_id)
        if _ledger_sha(artifact.transitions) != m.transition_ledger_sha256 \
                or _ledger_sha(artifact.case_ledger) != m.case_ledger_sha256:
            raise ComparisonBindingMismatchError("ledger hashes disagree with the manifest",
                                                 comparison_id=m.comparison_id)
        if _derive_verdict(artifact.transitions, artifact.case_ledger) != m.gate_verdict:
            raise ComparisonBindingMismatchError("recomputed verdict disagrees with the manifest",
                                                 comparison_id=m.comparison_id)
        if _logical_output_hash(m, artifact.transitions, artifact.case_ledger) != m.output_hash:
            raise ComparisonBindingMismatchError("recomputed output hash disagrees with the manifest",
                                                 comparison_id=m.comparison_id)
    else:
        if artifact.transitions or artifact.case_ledger:
            raise ComparisonBindingMismatchError(
                "an invalid/errored artifact must have empty ledgers", comparison_id=m.comparison_id)
        if _logical_output_hash(m, (), ()) != m.output_hash:
            raise ComparisonBindingMismatchError("recomputed output hash disagrees with the manifest",
                                                 comparison_id=m.comparison_id)


def _write_file(path: Path, data: bytes, *, comparison_id: str, reference: str) -> str:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    except FileExistsError as exc:
        raise ComparisonExistsError(f"comparison artifact {reference!r} already exists; write-once",
                                    comparison_id=comparison_id, artifact_reference=reference) from exc
    except OSError as exc:
        raise ComparisonWriteError(f"failed to create comparison artifact {reference!r}",
                                   comparison_id=comparison_id, artifact_reference=reference) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ComparisonWriteError(f"failed to write comparison artifact {reference!r}",
                                   comparison_id=comparison_id, artifact_reference=reference) from exc
    try:
        observed = sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise ComparisonWriteError(f"failed to re-read comparison artifact {reference!r}",
                                   comparison_id=comparison_id, artifact_reference=reference) from exc
    expected = sha256_bytes(data)
    if observed != expected:
        raise ComparisonDestinationHashMismatchError(
            f"written comparison artifact {reference!r} re-read to a different hash",
            comparison_id=comparison_id, artifact_reference=reference,
            expected_sha256=expected, observed_sha256=observed)
    return expected


def persist_comparison(
    artifact: ComparisonArtifact, *, eval_root: str | Path,
) -> PersistedComparison:
    """Persist a comparison artifact as write-once files under eval_root."""
    if not isinstance(artifact, ComparisonArtifact):
        raise TypeError(f"artifact must be a ComparisonArtifact, got {type(artifact).__name__}")
    resolved_root = _validate_root(eval_root)
    _reverify_aggregate(artifact)
    m = artifact.manifest
    comparison_id = m.comparison_id
    completed = m.execution_status == "completed"
    manifest_bytes = canonical_contract_bytes(m.model_dump(mode="json", exclude_unset=True)) + b"\n"
    transitions_bytes = _ledger_bytes(artifact.transitions)
    case_bytes = _ledger_bytes(artifact.case_ledger)

    parent = resolved_root / _COMPARISONS_DIR
    if parent.is_symlink():
        raise ComparisonExistsError(f"{_COMPARISONS_DIR} parent is a symlink",
                                    comparison_id=comparison_id, artifact_reference=_COMPARISONS_DIR)
    if parent.exists():
        if not parent.is_dir():
            raise ComparisonExistsError(f"{_COMPARISONS_DIR} parent is not a directory",
                                        comparison_id=comparison_id,
                                        artifact_reference=_COMPARISONS_DIR)
    else:
        try:
            parent.mkdir(exist_ok=True)
        except FileExistsError as exc:
            # A race created the node as a non-directory (exist_ok=True only raises then).
            raise ComparisonExistsError(f"{_COMPARISONS_DIR} parent is not a directory",
                                        comparison_id=comparison_id,
                                        artifact_reference=_COMPARISONS_DIR) from exc
        except OSError as exc:
            raise ComparisonWriteError(f"failed to create the {_COMPARISONS_DIR} parent",
                                       comparison_id=comparison_id) from exc
        if parent.is_symlink() or not parent.is_dir():
            raise ComparisonExistsError(f"{_COMPARISONS_DIR} parent is not a real directory",
                                        comparison_id=comparison_id,
                                        artifact_reference=_COMPARISONS_DIR)

    comparison_dir = parent / comparison_id
    dir_ref = f"{_COMPARISONS_DIR}/{comparison_id}"
    if comparison_dir.exists() or comparison_dir.is_symlink():
        raise ComparisonExistsError(f"comparison directory {dir_ref} already exists",
                                    comparison_id=comparison_id, artifact_reference=dir_ref)
    try:
        comparison_dir.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise ComparisonExistsError(f"comparison directory {dir_ref} already exists",
                                    comparison_id=comparison_id, artifact_reference=dir_ref) from exc
    except OSError as exc:
        raise ComparisonWriteError(f"failed to create comparison directory {dir_ref}",
                                   comparison_id=comparison_id, artifact_reference=dir_ref) from exc

    reference = f"{_COMPARISONS_DIR}/{comparison_id}/{_MANIFEST_FILENAME}"
    if completed:
        _write_file(comparison_dir / _TRANSITIONS_FILENAME, transitions_bytes,
                    comparison_id=comparison_id,
                    reference=f"{dir_ref}/{_TRANSITIONS_FILENAME}")
        _write_file(comparison_dir / _CASE_LEDGER_FILENAME, case_bytes,
                    comparison_id=comparison_id, reference=f"{dir_ref}/{_CASE_LEDGER_FILENAME}")
    manifest_sha = _write_file(comparison_dir / _MANIFEST_FILENAME, manifest_bytes,
                               comparison_id=comparison_id, reference=reference)
    return PersistedComparison(comparison_id=comparison_id, artifact_reference=reference,
                               sha256=manifest_sha, artifact=artifact)


# --- Loader ---------------------------------------------------------------


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


def _parse_json_object(raw: bytes, *, comparison_id: str, reference: str) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ComparisonDecodeError(f"comparison artifact {reference!r} is not valid UTF-8",
                                    comparison_id=comparison_id, artifact_reference=reference) from exc
    if text.startswith("\ufeff"):
        raise ComparisonJsonError(f"comparison artifact {reference!r} has a UTF-8 BOM",
                                  comparison_id=comparison_id, artifact_reference=reference)
    try:
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_keys,
                             parse_constant=_reject_non_finite_constant)
    except json.JSONDecodeError as exc:
        raise ComparisonJsonError(f"comparison artifact {reference!r} is not valid JSON: {exc.msg}",
                                  comparison_id=comparison_id, artifact_reference=reference) from exc
    except _DuplicateKeyControl as exc:
        raise ComparisonJsonError(f"comparison artifact {reference!r} has duplicate key {exc.key!r}",
                                  comparison_id=comparison_id, artifact_reference=reference,
                                  duplicate_key=exc.key) from exc
    except _NonFiniteControl as exc:
        raise ComparisonJsonError(
            f"comparison artifact {reference!r} has non-JSON constant {exc.constant_name}",
            comparison_id=comparison_id, artifact_reference=reference,
            constant_name=exc.constant_name) from exc
    non_finite = _first_non_finite(payload)
    if non_finite is not None:
        raise ComparisonJsonError(f"comparison artifact {reference!r} has non-finite number "
                                  f"({non_finite})", comparison_id=comparison_id,
                                  artifact_reference=reference, constant_name=non_finite)
    if not isinstance(payload, dict):
        raise ComparisonTopLevelTypeError(f"comparison artifact {reference!r} is not a JSON object",
                                          comparison_id=comparison_id, artifact_reference=reference)
    return payload


def _read_regular_file(path: Path, *, comparison_id: str, reference: str) -> bytes:
    if path.is_symlink():
        raise ComparisonArtifactNotAFileError(f"comparison artifact {reference!r} is a symlink",
                                              comparison_id=comparison_id,
                                              artifact_reference=reference)
    if not path.exists():
        raise ComparisonArtifactMissingError(f"comparison artifact {reference!r} does not exist",
                                             comparison_id=comparison_id,
                                             artifact_reference=reference)
    if not path.is_file():
        raise ComparisonArtifactNotAFileError(f"comparison artifact {reference!r} is not a file",
                                              comparison_id=comparison_id,
                                              artifact_reference=reference)
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ComparisonArtifactReadError(f"failed to read comparison artifact {reference!r}",
                                          comparison_id=comparison_id,
                                          artifact_reference=reference) from exc


def _load_ledger(
    path: Path, model: type, *, comparison_id: str, reference: str,
) -> tuple[Any, ...]:
    raw = _read_regular_file(path, comparison_id=comparison_id, reference=reference)
    if raw == b"":
        return ()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ComparisonDecodeError(f"comparison ledger {reference!r} is not valid UTF-8",
                                    comparison_id=comparison_id, artifact_reference=reference) from exc
    if text.startswith("\ufeff"):
        raise ComparisonJsonError(f"comparison ledger {reference!r} has a UTF-8 BOM",
                                  comparison_id=comparison_id, artifact_reference=reference)
    if not text.endswith("\n"):
        raise ComparisonJsonError(f"comparison ledger {reference!r} must end with a newline",
                                  comparison_id=comparison_id, artifact_reference=reference)
    lines = text[:-1].split("\n")
    records: list[Any] = []
    for line in lines:
        if line == "":
            raise ComparisonJsonError(f"comparison ledger {reference!r} has a blank line",
                                      comparison_id=comparison_id, artifact_reference=reference)
        try:
            obj = json.loads(line, object_pairs_hook=_reject_duplicate_keys,
                             parse_constant=_reject_non_finite_constant)
        except json.JSONDecodeError as exc:
            raise ComparisonJsonError(f"comparison ledger {reference!r} has an invalid line: "
                                      f"{exc.msg}", comparison_id=comparison_id,
                                      artifact_reference=reference) from exc
        except _DuplicateKeyControl as exc:
            raise ComparisonJsonError(f"comparison ledger {reference!r} has duplicate key {exc.key!r}",
                                      comparison_id=comparison_id, artifact_reference=reference,
                                      duplicate_key=exc.key) from exc
        except _NonFiniteControl as exc:
            raise ComparisonJsonError(
                f"comparison ledger {reference!r} has a non-JSON constant {exc.constant_name}",
                comparison_id=comparison_id, artifact_reference=reference,
                constant_name=exc.constant_name) from exc
        if _first_non_finite(obj) is not None:
            raise ComparisonJsonError(f"comparison ledger {reference!r} has a non-finite number",
                                      comparison_id=comparison_id, artifact_reference=reference)
        if not isinstance(obj, dict):
            raise ComparisonTopLevelTypeError(f"comparison ledger {reference!r} line is not an object",
                                              comparison_id=comparison_id,
                                              artifact_reference=reference)
        try:
            records.append(model.model_validate(obj))
        except PydanticValidationError as exc:
            raise ComparisonModelValidationError(
                f"comparison ledger {reference!r} failed model validation",
                comparison_id=comparison_id, artifact_reference=reference,
                field_locations=_error_locations(exc)) from exc
    result = tuple(records)
    if _ledger_bytes(result) != raw:
        raise ComparisonBindingMismatchError(
            f"comparison ledger {reference!r} is not canonically serialized",
            comparison_id=comparison_id, artifact_reference=reference)
    return result


def _error_locations(exc: PydanticValidationError) -> tuple[str, ...]:
    return tuple(sorted("/".join(str(p) for p in e["loc"]) for e in exc.errors()))


def load_comparison(comparison_id: str, *, eval_root: str | Path) -> LoadedComparison:
    """Load a comparison artifact from its fixed comparison-scoped directory."""
    cid = _require_comparison_id(comparison_id)
    resolved_root = _validate_root(eval_root)
    parent = resolved_root / _COMPARISONS_DIR
    comparison_dir = parent / cid
    reference = f"{_COMPARISONS_DIR}/{cid}/{_MANIFEST_FILENAME}"
    if parent.is_symlink() or comparison_dir.is_symlink():
        raise ComparisonArtifactNotAFileError(f"comparison directory for {cid!r} or its parent is a "
                                              "symlink", comparison_id=cid,
                                              artifact_reference=f"{_COMPARISONS_DIR}/{cid}")
    if not comparison_dir.exists():
        raise ComparisonArtifactMissingError(f"comparison directory for {cid!r} does not exist",
                                             comparison_id=cid,
                                             artifact_reference=f"{_COMPARISONS_DIR}/{cid}")
    if not comparison_dir.is_dir():
        raise ComparisonArtifactNotAFileError(f"comparison directory for {cid!r} is not a directory",
                                              comparison_id=cid,
                                              artifact_reference=f"{_COMPARISONS_DIR}/{cid}")
    manifest_path = comparison_dir / _MANIFEST_FILENAME
    raw = _read_regular_file(manifest_path, comparison_id=cid, reference=reference)
    manifest_sha = sha256_bytes(raw)
    payload = _parse_json_object(raw, comparison_id=cid, reference=reference)
    try:
        manifest = ComparisonManifest.model_validate(payload)
    except PydanticValidationError as exc:
        raise ComparisonModelValidationError(
            f"comparison manifest {reference!r} failed model validation", comparison_id=cid,
            artifact_reference=reference, field_locations=_error_locations(exc)) from exc
    if manifest.comparison_id != cid:
        raise ComparisonBindingMismatchError("manifest comparison_id does not match the directory",
                                             comparison_id=cid, artifact_reference=reference)
    transitions_path = comparison_dir / _TRANSITIONS_FILENAME
    case_path = comparison_dir / _CASE_LEDGER_FILENAME
    if manifest.execution_status == "completed":
        transitions = _load_ledger(transitions_path, AssertionTransition, comparison_id=cid,
                                   reference=f"{_COMPARISONS_DIR}/{cid}/{_TRANSITIONS_FILENAME}")
        case_ledger = _load_ledger(case_path, CaseLedgerEntry, comparison_id=cid,
                                   reference=f"{_COMPARISONS_DIR}/{cid}/{_CASE_LEDGER_FILENAME}")
    else:
        for extra_path, extra_name in ((transitions_path, _TRANSITIONS_FILENAME),
                                       (case_path, _CASE_LEDGER_FILENAME)):
            if extra_path.exists() or extra_path.is_symlink():
                raise ComparisonBindingMismatchError(
                    f"an invalid/errored comparison must not carry {extra_name}", comparison_id=cid,
                    artifact_reference=f"{_COMPARISONS_DIR}/{cid}/{extra_name}")
        transitions, case_ledger = (), ()
    try:
        artifact = ComparisonArtifact(manifest=manifest, transitions=transitions,
                                      case_ledger=case_ledger)
    except PydanticValidationError as exc:
        raise ComparisonBindingMismatchError(
            f"comparison artifact {reference!r} failed aggregate validation", comparison_id=cid,
            artifact_reference=reference, ) from exc
    return LoadedComparison(comparison_id=cid, artifact_reference=reference, sha256=manifest_sha,
                            artifact=artifact)
