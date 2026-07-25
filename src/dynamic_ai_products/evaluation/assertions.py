"""Assertion evaluation dispatch and identity checks (Slice 7).

Slice 7 matches one canonical ``PredictionEnvelope`` to exactly one
package-case (via ``input_packet_hash`` + ``stage`` over a complete bound
case-set), then produces one ``AssertionOutcome`` per assertion in the matched
case. Kind-specific semantic scoring is not implemented here: for each fully
resolved assertion the caller supplies a typed common-contract
``ResolvedAssertionEvaluation`` (Option A) whose four-value outcome is copied
unchanged; for each assertion with an unresolved reference the caller supplies
the existing Slice 4 ``ResolutionFinding`` and Slice 7 emits ``not_evaluated``.

Slice 7 never calls the Slice 4 resolver, never reads prediction source
artifacts, never reinterprets ``CaseMembership.input_packet_hash`` beyond the
package identity bridge, never assigns a run-level execution status or gate
verdict, and persists only ``AssertionOutcome`` records. No case-file hash
binding is claimed (no existing contract carries it).

Immutability here means refuse-to-overwrite directories, exclusive-create
files and read-back hash verification — not OS-level immutability.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError as PydanticValidationError,
)

from .case_sets import case_set_snapshot_hash
from .cases import InvalidEvaluationRootError
from .contracts import canonical_contract_bytes, model_contract_hash
from .models import (
    AssertionKind,
    AssertionOutcome,
    CaseMembership,
    CaseSetManifest,
    EvaluationCase,
    EvaluationStrictModel,
)
from .references import ResolutionFinding, ResolvedAssertionReferences
from .runs import LoadedEvaluationRunManifest, _load_run_manifest_any_supported_version
from ..universe.io_utils import sha256_bytes

_ASSERTIONS_DIR = "assertions"
_OUTCOMES_FILENAME = "assertion_outcomes.jsonl"
_OUTCOME_CONTRACT_ID = "assertion_outcome"
_OUTCOME_CONTRACT_VERSION = "0.1.0"

ResolvedAssertionOutcome = Literal[
    "satisfied", "unsatisfied", "indeterminate", "not_applicable"
]

BindingKind = Literal[
    "case_set_version_mismatch",
    "case_set_hash_mismatch",
    "bound_case_collection_mismatch",
    "membership_case_id_mismatch",
    "no_package_case_match",
    "ambiguous_package_case_match",
    "resolution_assertion_id_mismatch",
    "evaluation_case_id_mismatch",
    "evaluation_assertion_id_mismatch",
    "evaluation_kind_mismatch",
    "evaluation_semantic_version_mismatch",
    "evaluation_contract_hash_mismatch",
    "finding_case_id_mismatch",
    "finding_assertion_id_mismatch",
    "outcome_run_id_mismatch",
]


class _Slice7StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- Input models ---------------------------------------------------------


class BoundEvaluationCase(EvaluationStrictModel):
    """One loaded case bound to its case-set membership (case-ID only)."""

    case: EvaluationCase
    membership: CaseMembership


class ResolvedAssertionEvaluation(_Slice7StrictModel):
    """Common-contract handoff from a separately governed kind evaluator."""

    case_id: str
    assertion_id: str
    assertion_semantic_version: str | None = None
    assertion_contract_hash: str | None = None
    kind: AssertionKind
    outcome: ResolvedAssertionOutcome


class ResolvedAssertionDispatch(_Slice7StrictModel):
    """A fully resolved assertion with its caller-supplied evaluation."""

    status: Literal["resolved"]
    resolution: ResolvedAssertionReferences
    evaluation: ResolvedAssertionEvaluation


class UnresolvedAssertionDispatch(_Slice7StrictModel):
    """An assertion with an unresolved reference, carrying its finding."""

    status: Literal["unresolved"]
    finding: ResolutionFinding


AssertionDispatchInput = Annotated[
    ResolvedAssertionDispatch | UnresolvedAssertionDispatch,
    Field(discriminator="status"),
]


# --- Result / persistence models -----------------------------------------


class EvaluatedCaseAssertions(_Slice7StrictModel):
    """Non-persisted result of evaluating one package-case's assertions."""

    eval_run_id: str
    case_id: str
    prediction_record_id: str
    outcomes: tuple[AssertionOutcome, ...]
    resolution_findings: tuple[ResolutionFinding, ...]


class PersistedAssertionOutcomes(_Slice7StrictModel):
    eval_run_id: str
    artifact_reference: str
    sha256: str
    outcomes: tuple[AssertionOutcome, ...]


class LoadedAssertionOutcomes(_Slice7StrictModel):
    eval_run_id: str
    artifact_reference: str
    sha256: str
    outcomes: tuple[AssertionOutcome, ...]


# --- Exceptions -----------------------------------------------------------


class AssertionEvaluationError(Exception):
    """Base class for Slice 7 failures; never raised directly."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        case_id: str | None = None,
        assertion_id: str | None = None,
        prediction_record_id: str | None = None,
        binding_kind: BindingKind | None = None,
        artifact_reference: str | None = None,
    ) -> None:
        super().__init__(message)
        self.eval_run_id = eval_run_id
        self.case_id = case_id
        self.assertion_id = assertion_id
        self.prediction_record_id = prediction_record_id
        self.binding_kind = binding_kind
        self.artifact_reference = artifact_reference


class AssertionCaseSetBindingError(AssertionEvaluationError):
    """The supplied case set does not bind to the run manifest."""


class AssertionBoundCaseError(AssertionEvaluationError):
    """The bound-case collection is incomplete, extra or inconsistent."""

    def __init__(
        self,
        message: str,
        *,
        binding_kind: BindingKind | None = None,
        case_id: str | None = None,
        duplicate_case_id: str | None = None,
        duplicate_identity: str | None = None,
    ) -> None:
        super().__init__(message, binding_kind=binding_kind, case_id=case_id)
        self.duplicate_case_id = duplicate_case_id
        self.duplicate_identity = duplicate_identity


class AssertionEnvelopeMatchError(AssertionEvaluationError):
    """Zero or multiple package-cases match the envelope composite."""

    def __init__(
        self,
        message: str,
        *,
        binding_kind: BindingKind | None = None,
        prediction_record_id: str | None = None,
        match_count: int | None = None,
    ) -> None:
        super().__init__(
            message, binding_kind=binding_kind, prediction_record_id=prediction_record_id
        )
        self.match_count = match_count


class DuplicateAssertionIdError(AssertionEvaluationError):
    """A case declares the same assertion_id more than once."""

    def __init__(
        self, message: str, *, case_id: str | None = None, duplicate_assertion_id: str | None = None
    ) -> None:
        super().__init__(message, case_id=case_id)
        self.duplicate_assertion_id = duplicate_assertion_id


class AssertionDispatchBindingError(AssertionEvaluationError):
    """A dispatch input's identity does not match its assertion."""


class DuplicateAssertionDispatchError(AssertionEvaluationError):
    """Two dispatch inputs target the same assertion."""

    def __init__(
        self, message: str, *, case_id: str | None = None, duplicate_assertion_id: str | None = None
    ) -> None:
        super().__init__(message, case_id=case_id)
        self.duplicate_assertion_id = duplicate_assertion_id


class MissingAssertionDispatchError(AssertionEvaluationError):
    """An assertion in the case has no dispatch input."""


class UnexpectedAssertionDispatchError(AssertionEvaluationError):
    """A dispatch input targets an assertion not in the case."""


class UnsupportedAssertionKindError(AssertionEvaluationError):
    """An assertion kind has no governed handler."""


class AssertionOutcomeExistsError(AssertionEvaluationError):
    """The assertions output directory already exists in some form."""


class AssertionPathEscapeError(AssertionEvaluationError):
    """An assertions artifact path resolves outside the evaluation root."""


class AssertionArtifactMissingError(AssertionEvaluationError):
    """A required assertions artifact does not exist."""


class AssertionArtifactNotAFileError(AssertionEvaluationError):
    """A required assertions artifact is not a regular file."""


class AssertionArtifactReadError(AssertionEvaluationError):
    """Reading an assertions artifact failed."""


class AssertionDecodeError(AssertionEvaluationError):
    """An assertions artifact's bytes are not valid UTF-8."""


class AssertionJsonError(AssertionEvaluationError):
    """An assertions artifact is not acceptable strict JSONL."""

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


class AssertionTopLevelTypeError(AssertionEvaluationError):
    """A parsed outcome line is not a JSON object."""

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


class AssertionModelValidationError(AssertionEvaluationError):
    """An outcome line failed AssertionOutcome model/contract validation."""

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


class DuplicateAssertionOutcomeError(AssertionEvaluationError):
    """Two outcomes share a (case_id, assertion_id) identity."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
        case_id: str | None = None,
        assertion_id: str | None = None,
        line_number: int | None = None,
    ) -> None:
        super().__init__(
            message, eval_run_id=eval_run_id, artifact_reference=artifact_reference,
            case_id=case_id, assertion_id=assertion_id,
        )
        self.line_number = line_number


class AssertionRunBindingError(AssertionEvaluationError):
    """An outcome eval_run_id does not match the requested/loaded run."""

    def __init__(
        self,
        message: str,
        *,
        eval_run_id: str | None = None,
        artifact_reference: str | None = None,
        binding_kind: BindingKind | None = None,
    ) -> None:
        super().__init__(
            message, eval_run_id=eval_run_id, artifact_reference=artifact_reference,
            binding_kind=binding_kind,
        )


class AssertionWriteError(AssertionEvaluationError):
    """Writing an assertions artifact failed."""


class AssertionDestinationHashMismatchError(AssertionEvaluationError):
    """A written assertions artifact re-read to a different hash."""

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


# --- Pure evaluation ------------------------------------------------------


def _require_unique_assertion_ids(case: EvaluationCase) -> None:
    seen: set[str] = set()
    for spec in case.assertions:
        if spec.assertion_id in seen:
            raise DuplicateAssertionIdError(
                f"case {case.case_id!r} declares assertion {spec.assertion_id!r} more than once",
                case_id=case.case_id, duplicate_assertion_id=spec.assertion_id,
            )
        seen.add(spec.assertion_id)


def _verify_bound_collection(
    bound_cases: tuple[BoundEvaluationCase, ...], case_set: CaseSetManifest
) -> dict[str, BoundEvaluationCase]:
    by_case_id: dict[str, BoundEvaluationCase] = {}
    for bound in bound_cases:
        if bound.case.case_id != bound.membership.case_id:
            raise AssertionBoundCaseError(
                "bound case's case ID does not equal its membership case ID",
                binding_kind="membership_case_id_mismatch", case_id=bound.case.case_id,
            )
        if bound.case.case_id in by_case_id:
            raise AssertionBoundCaseError(
                f"bound case {bound.case.case_id!r} is supplied more than once",
                binding_kind="bound_case_collection_mismatch",
                duplicate_case_id=bound.case.case_id,
            )
        by_case_id[bound.case.case_id] = bound
    authoritative: dict[str, CaseMembership] = {}
    for entry in case_set.entries:
        if entry.case_id in authoritative:
            raise AssertionBoundCaseError(
                f"case-set membership {entry.case_id!r} appears more than once",
                binding_kind="bound_case_collection_mismatch", duplicate_identity=entry.case_id,
            )
        authoritative[entry.case_id] = entry
    if set(by_case_id) != set(authoritative):
        raise AssertionBoundCaseError(
            "the bound-case collection does not correspond exactly to the case-set memberships",
            binding_kind="bound_case_collection_mismatch",
        )
    # The case-set manifest is the authoritative membership record: a supplied
    # membership must equal its manifest entry as a complete object, so an
    # altered packet hash, partition or suite set cannot enter evaluation
    # behind an unchanged case ID.
    for case_id, bound in by_case_id.items():
        if bound.membership != authoritative[case_id]:
            raise AssertionBoundCaseError(
                f"supplied membership for case {case_id!r} does not equal the "
                "authoritative case-set manifest entry",
                binding_kind="bound_case_collection_mismatch", case_id=case_id,
            )
    return by_case_id


def _dispatch_expected_entity(spec: Any, ev: ResolvedAssertionEvaluation) -> ResolvedAssertionOutcome:
    return ev.outcome


def _dispatch_forbidden_entity(spec: Any, ev: ResolvedAssertionEvaluation) -> ResolvedAssertionOutcome:
    return ev.outcome


def _dispatch_field_value(spec: Any, ev: ResolvedAssertionEvaluation) -> ResolvedAssertionOutcome:
    return ev.outcome


def _dispatch_evidence_provenance(spec: Any, ev: ResolvedAssertionEvaluation) -> ResolvedAssertionOutcome:
    return ev.outcome


def _dispatch_deterministic_validation(spec: Any, ev: ResolvedAssertionEvaluation) -> ResolvedAssertionOutcome:
    return ev.outcome


_KIND_HANDLERS: dict[str, Any] = {
    "expected_entity": _dispatch_expected_entity,
    "forbidden_entity": _dispatch_forbidden_entity,
    "field_value": _dispatch_field_value,
    "evidence_provenance": _dispatch_evidence_provenance,
    "deterministic_validation": _dispatch_deterministic_validation,
}


def _outcome_contract_metadata() -> dict[str, str]:
    return {
        "contract_id": _OUTCOME_CONTRACT_ID,
        "contract_version": _OUTCOME_CONTRACT_VERSION,
        "contract_hash": model_contract_hash(
            AssertionOutcome, _OUTCOME_CONTRACT_ID, _OUTCOME_CONTRACT_VERSION
        ),
    }


def evaluate_case_assertions(
    bound_cases: tuple[BoundEvaluationCase, ...],
    *,
    case_set: CaseSetManifest,
    run_manifest: LoadedEvaluationRunManifest,
    envelope,
    assertion_dispatches: tuple[AssertionDispatchInput, ...],
) -> EvaluatedCaseAssertions:
    """Evaluate one package-case's assertions from a caller-supplied partition.

    The envelope is matched to exactly one bound case by
    ``input_packet_hash`` + ``stage``; every assertion in that case must have
    exactly one dispatch input (resolved with a common-contract evaluation, or
    unresolved with its Slice 4 finding). No filesystem access, no Slice 4
    resolver call, and no source-artifact read occur here.
    """
    manifest = run_manifest.manifest
    if not isinstance(case_set, CaseSetManifest):
        raise TypeError(f"case_set must be a CaseSetManifest, got {type(case_set).__name__}")

    if case_set.case_set_version != manifest.case_set_version:
        raise AssertionCaseSetBindingError(
            "supplied case-set version does not match the run manifest",
            binding_kind="case_set_version_mismatch", eval_run_id=manifest.eval_run_id,
        )
    if case_set_snapshot_hash(case_set) != manifest.case_set_hash:
        raise AssertionCaseSetBindingError(
            "supplied case-set snapshot hash does not match the run manifest",
            binding_kind="case_set_hash_mismatch", eval_run_id=manifest.eval_run_id,
        )

    by_case_id = _verify_bound_collection(bound_cases, case_set)
    for bound in by_case_id.values():
        _require_unique_assertion_ids(bound.case)

    matches = [
        bound for bound in by_case_id.values()
        if envelope.input_packet_hash == bound.membership.input_packet_hash
        and envelope.stage == bound.case.stage
    ]
    if len(matches) == 0:
        raise AssertionEnvelopeMatchError(
            "no package-case matches the envelope input-packet hash and stage",
            binding_kind="no_package_case_match",
            prediction_record_id=envelope.prediction_record_id, match_count=0,
        )
    if len(matches) > 1:
        raise AssertionEnvelopeMatchError(
            "multiple package-cases match the envelope input-packet hash and stage",
            binding_kind="ambiguous_package_case_match",
            prediction_record_id=envelope.prediction_record_id, match_count=len(matches),
        )
    bound = matches[0]
    case = bound.case
    case_assertion_ids = [s.assertion_id for s in case.assertions]
    spec_by_id = {s.assertion_id: s for s in case.assertions}

    # Validate + index the dispatch partition by assertion identity.
    dispatch_by_id: dict[str, AssertionDispatchInput] = {}
    for dispatch in assertion_dispatches:
        if dispatch.status == "resolved":
            aid = dispatch.resolution.assertion_id
            aid_eval = dispatch.evaluation.assertion_id
            if dispatch.evaluation.case_id != case.case_id:
                raise AssertionDispatchBindingError(
                    "resolved evaluation case ID does not match the matched case",
                    binding_kind="evaluation_case_id_mismatch",
                    case_id=case.case_id, assertion_id=aid_eval,
                )
            # The resolver's assertion identity is the binding key: it must
            # target an assertion the matched case actually declares.
            if aid not in spec_by_id:
                raise UnexpectedAssertionDispatchError(
                    f"resolved dispatch targets assertion {aid!r} not present in the case",
                    binding_kind="resolution_assertion_id_mismatch",
                    case_id=case.case_id, assertion_id=aid,
                )
            if aid_eval != aid:
                raise AssertionDispatchBindingError(
                    "resolved evaluation targets a different assertion than the resolver",
                    binding_kind="evaluation_assertion_id_mismatch",
                    case_id=case.case_id, assertion_id=aid_eval,
                )
            key = aid
        else:
            if dispatch.finding.case_id != case.case_id:
                raise AssertionDispatchBindingError(
                    "unresolved finding case ID does not match the matched case",
                    binding_kind="finding_case_id_mismatch", case_id=case.case_id,
                )
            key = dispatch.finding.assertion_id
            if key not in spec_by_id:
                raise UnexpectedAssertionDispatchError(
                    f"unresolved finding targets assertion {key!r} not present in the case",
                    binding_kind="finding_assertion_id_mismatch",
                    case_id=case.case_id, assertion_id=key,
                )
        if key in dispatch_by_id:
            raise DuplicateAssertionDispatchError(
                f"assertion {key!r} has more than one dispatch input",
                case_id=case.case_id, duplicate_assertion_id=key,
            )
        dispatch_by_id[key] = dispatch

    for aid in case_assertion_ids:
        if aid not in dispatch_by_id:
            raise MissingAssertionDispatchError(
                f"assertion {aid!r} has no dispatch input",
                case_id=case.case_id, assertion_id=aid,
            )

    metadata = _outcome_contract_metadata()
    outcomes: list[AssertionOutcome] = []
    findings: list[ResolutionFinding] = []
    for spec in case.assertions:
        dispatch = dispatch_by_id[spec.assertion_id]
        if dispatch.status == "unresolved":
            findings.append(dispatch.finding)
            outcome_value: str = "not_evaluated"
        else:
            ev = dispatch.evaluation
            if ev.assertion_semantic_version != spec.semantic_version:
                raise AssertionDispatchBindingError(
                    f"resolved evaluation semantic version does not match assertion "
                    f"{spec.assertion_id!r}",
                    binding_kind="evaluation_semantic_version_mismatch",
                    case_id=case.case_id, assertion_id=spec.assertion_id,
                )
            if ev.assertion_contract_hash != spec.contract_hash:
                raise AssertionDispatchBindingError(
                    f"resolved evaluation contract hash does not match assertion "
                    f"{spec.assertion_id!r}",
                    binding_kind="evaluation_contract_hash_mismatch",
                    case_id=case.case_id, assertion_id=spec.assertion_id,
                )
            if ev.kind != spec.kind:
                raise AssertionDispatchBindingError(
                    f"resolved evaluation kind does not match assertion {spec.assertion_id!r}",
                    binding_kind="evaluation_kind_mismatch",
                    case_id=case.case_id, assertion_id=spec.assertion_id,
                )
            handler = _KIND_HANDLERS.get(spec.kind)
            if handler is None:
                raise UnsupportedAssertionKindError(
                    f"assertion {spec.assertion_id!r} has unsupported kind {spec.kind!r}",
                    case_id=case.case_id, assertion_id=spec.assertion_id,
                )
            outcome_value = handler(spec, ev)
        payload: dict[str, Any] = {
            "contract": metadata,
            "eval_run_id": manifest.eval_run_id,
            "case_id": case.case_id,
            "assertion_id": spec.assertion_id,
            "outcome": outcome_value,
        }
        # Mirror the assertion's own identity presence: carry only the
        # supplied identity fields; explicit null is rejected downstream.
        if spec.semantic_version is not None:
            payload["assertion_semantic_version"] = spec.semantic_version
        if spec.contract_hash is not None:
            payload["assertion_contract_hash"] = spec.contract_hash
        outcomes.append(AssertionOutcome.model_validate(payload))

    return EvaluatedCaseAssertions(
        eval_run_id=manifest.eval_run_id,
        case_id=case.case_id,
        prediction_record_id=envelope.prediction_record_id,
        outcomes=tuple(outcomes),
        resolution_findings=tuple(findings),
    )


# --- Persistence ----------------------------------------------------------


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
        raise InvalidEvaluationRootError(f"eval_root {str(root)!r} does not exist", supplied_root=str(root))
    if not path.is_dir():
        raise InvalidEvaluationRootError(f"eval_root {str(root)!r} is not a directory", supplied_root=str(root))
    return path.resolve()


def _canonical_outcome_line(outcome: AssertionOutcome) -> bytes:
    return canonical_contract_bytes(outcome.model_dump(mode="json", exclude_unset=True))


def _serialize_outcomes(outcomes: tuple[AssertionOutcome, ...]) -> bytes:
    if not outcomes:
        return b""
    return b"".join(_canonical_outcome_line(o) + b"\n" for o in outcomes)


def _exclusive_write(path: Path, data: bytes, reference: str, eval_run_id: str) -> None:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise AssertionOutcomeExistsError(
            f"assertions artifact {reference!r} already exists; artifacts are write-once",
            eval_run_id=eval_run_id, artifact_reference=reference,
        ) from exc
    except OSError as exc:
        raise AssertionWriteError(
            f"failed to create assertions artifact {reference!r}",
            eval_run_id=eval_run_id, artifact_reference=reference,
        ) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    except OSError as exc:
        raise AssertionWriteError(
            f"failed to write assertions artifact {reference!r}",
            eval_run_id=eval_run_id, artifact_reference=reference,
        ) from exc


def _require_unique_outcome_identities(
    outcomes: tuple[AssertionOutcome, ...], eval_run_id: str, reference: str | None
) -> None:
    seen: set[tuple[str, str]] = set()
    for index, outcome in enumerate(outcomes):
        key = (outcome.case_id, outcome.assertion_id)
        if key in seen:
            raise DuplicateAssertionOutcomeError(
                f"duplicate outcome identity ({outcome.case_id!r}, {outcome.assertion_id!r})",
                eval_run_id=eval_run_id, artifact_reference=reference,
                case_id=outcome.case_id, assertion_id=outcome.assertion_id,
                line_number=(index + 1) if reference else None,
            )
        seen.add(key)


def persist_assertion_outcomes(
    outcomes: tuple[AssertionOutcome, ...],
    *,
    eval_root: str | Path,
    eval_run_id: str,
) -> PersistedAssertionOutcomes:
    """Persist assertion outcomes as write-once JSONL in the Slice 5 run dir."""
    resolved_root = _validate_root(eval_root)
    loaded = _load_run_manifest_any_supported_version(eval_run_id, eval_root=resolved_root)
    run_id = loaded.manifest.eval_run_id
    for outcome in outcomes:
        if outcome.eval_run_id != run_id:
            raise AssertionRunBindingError(
                "an outcome eval_run_id does not match the run manifest",
                eval_run_id=run_id, binding_kind="outcome_run_id_mismatch",
            )
    _require_unique_outcome_identities(outcomes, run_id, None)

    assertions_dir = resolved_root / eval_run_id / _ASSERTIONS_DIR
    reference = f"{eval_run_id}/{_ASSERTIONS_DIR}/{_OUTCOMES_FILENAME}"
    if assertions_dir.exists() or assertions_dir.is_symlink():
        raise AssertionOutcomeExistsError(
            f"assertions directory {eval_run_id}/{_ASSERTIONS_DIR} already exists",
            eval_run_id=eval_run_id, artifact_reference=f"{eval_run_id}/{_ASSERTIONS_DIR}",
        )
    try:
        assertions_dir.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise AssertionOutcomeExistsError(
            f"assertions directory {eval_run_id}/{_ASSERTIONS_DIR} already exists",
            eval_run_id=eval_run_id, artifact_reference=f"{eval_run_id}/{_ASSERTIONS_DIR}",
        ) from exc
    except OSError as exc:
        raise AssertionWriteError(
            f"failed to create assertions directory for {eval_run_id!r}",
            eval_run_id=eval_run_id,
        ) from exc

    data = _serialize_outcomes(outcomes)
    observed = sha256_bytes(data)
    dest = assertions_dir / _OUTCOMES_FILENAME
    _exclusive_write(dest, data, reference, eval_run_id)
    try:
        reread = sha256_bytes(dest.read_bytes())
    except OSError as exc:
        raise AssertionWriteError(
            f"failed to re-read assertions artifact {reference!r} for verification",
            eval_run_id=eval_run_id, artifact_reference=reference,
        ) from exc
    if reread != observed:
        raise AssertionDestinationHashMismatchError(
            f"written assertions artifact {reference!r} re-read to a different hash",
            eval_run_id=eval_run_id, artifact_reference=reference,
            expected_sha256=observed, observed_sha256=reread,
        )
    return PersistedAssertionOutcomes(
        eval_run_id=eval_run_id, artifact_reference=reference, sha256=observed, outcomes=outcomes
    )


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


def _assert_finite(payload: Any) -> str | None:
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


def load_assertion_outcomes(
    eval_run_id: str, *, eval_root: str | Path
) -> LoadedAssertionOutcomes:
    """Load assertion outcomes from the fixed run-directory JSONL path."""
    resolved_root = _validate_root(eval_root)
    _load_run_manifest_any_supported_version(eval_run_id, eval_root=resolved_root)
    run_dir = resolved_root / eval_run_id
    assertions_dir = run_dir / _ASSERTIONS_DIR
    reference = f"{eval_run_id}/{_ASSERTIONS_DIR}/{_OUTCOMES_FILENAME}"
    dest = assertions_dir / _OUTCOMES_FILENAME
    if run_dir.is_symlink() or assertions_dir.is_symlink() or dest.is_symlink():
        raise AssertionArtifactNotAFileError(
            f"assertions artifact {reference!r} or a parent is a symlink",
            eval_run_id=eval_run_id, artifact_reference=reference,
        )
    if not dest.exists():
        raise AssertionArtifactMissingError(
            f"assertions artifact {reference!r} does not exist",
            eval_run_id=eval_run_id, artifact_reference=reference,
        )
    if not dest.is_file():
        raise AssertionArtifactNotAFileError(
            f"assertions artifact {reference!r} is not a regular file",
            eval_run_id=eval_run_id, artifact_reference=reference,
        )
    try:
        raw = dest.read_bytes()
    except OSError as exc:
        raise AssertionArtifactReadError(
            f"failed to read assertions artifact {reference!r}",
            eval_run_id=eval_run_id, artifact_reference=reference,
        ) from exc
    observed = sha256_bytes(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AssertionDecodeError(
            f"assertions artifact {reference!r} is not valid UTF-8",
            eval_run_id=eval_run_id, artifact_reference=reference,
        ) from exc
    outcomes: list[AssertionOutcome] = []
    if text != "":
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        for index, line in enumerate(lines):
            ln = index + 1
            if not line or not line.strip():
                raise AssertionJsonError(
                    f"assertions artifact {reference!r} line {ln} is blank",
                    eval_run_id=eval_run_id, artifact_reference=reference, line_number=ln,
                )
            try:
                payload = json.loads(
                    line, object_pairs_hook=_reject_duplicate_keys,
                    parse_constant=_reject_non_finite_constant,
                )
            except json.JSONDecodeError as exc:
                raise AssertionJsonError(
                    f"assertions artifact {reference!r} line {ln} is not valid JSON: {exc.msg}",
                    eval_run_id=eval_run_id, artifact_reference=reference, line_number=ln,
                ) from exc
            except _DuplicateKeyControl as exc:
                raise AssertionJsonError(
                    f"assertions artifact {reference!r} line {ln} has duplicate key {exc.key!r}",
                    eval_run_id=eval_run_id, artifact_reference=reference,
                    line_number=ln, duplicate_key=exc.key,
                ) from exc
            except _NonFiniteControl as exc:
                raise AssertionJsonError(
                    f"assertions artifact {reference!r} line {ln} has non-JSON constant {exc.constant_name}",
                    eval_run_id=eval_run_id, artifact_reference=reference,
                    line_number=ln, constant_name=exc.constant_name,
                ) from exc
            non_finite = _assert_finite(payload)
            if non_finite is not None:
                raise AssertionJsonError(
                    f"assertions artifact {reference!r} line {ln} has non-finite number ({non_finite})",
                    eval_run_id=eval_run_id, artifact_reference=reference,
                    line_number=ln, constant_name=non_finite,
                )
            if not isinstance(payload, dict):
                raise AssertionTopLevelTypeError(
                    f"assertions artifact {reference!r} line {ln} is not a JSON object",
                    eval_run_id=eval_run_id, artifact_reference=reference,
                    observed_type=type(payload).__name__, line_number=ln,
                )
            try:
                outcome = AssertionOutcome.model_validate(payload)
            except PydanticValidationError as exc:
                pairs = sorted(
                    ("/".join(str(p) for p in e["loc"]), e["type"]) for e in exc.errors()
                )
                raise AssertionModelValidationError(
                    f"assertions artifact {reference!r} line {ln} failed AssertionOutcome validation",
                    eval_run_id=eval_run_id, artifact_reference=reference, line_number=ln,
                    field_locations=tuple(loc for loc, _ in pairs),
                    error_types=tuple(t for _, t in pairs),
                ) from exc
            if outcome.eval_run_id != eval_run_id:
                raise AssertionRunBindingError(
                    f"assertions artifact {reference!r} line {ln} records a different eval_run_id",
                    eval_run_id=eval_run_id, artifact_reference=reference,
                    binding_kind="outcome_run_id_mismatch",
                )
            outcomes.append(outcome)
    _require_unique_outcome_identities(tuple(outcomes), eval_run_id, reference)
    return LoadedAssertionOutcomes(
        eval_run_id=eval_run_id, artifact_reference=reference, sha256=observed,
        outcomes=tuple(outcomes),
    )
