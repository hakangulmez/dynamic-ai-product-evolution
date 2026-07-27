"""Slice 13: single-case evaluation runner (plan contract, lifecycle, CLI).

``EvaluationRunPlan`` is the strict, fully pinned description of one
single-case evaluation: sixteen role-complete artifact references, each bound
to its source root and to the SHA-256 of its raw persisted bytes. The runner
verifies every pin against raw bytes, loads every input through its public
loader, and enforces single-case cardinality — all before any run directory
exists. Pre-manifest failures raise a private typed exception carrying exit
code 4 and sanitized issues; they return no summary and write nothing.

After the run manifest exists, every failure is converted into a persisted
terminal invalid/errored ``EvaluationResultV2`` plus machine/human reports.
Once validator findings exist, the v0.2 output manifest is built from every
successfully persisted optional artifact before the terminal result. The
``prediction_run_manifest`` plan entry's SHA-256 is the sole
``prediction_run_manifest_hash`` authority; the module-private static
schema-anchor table in ``validator_parameters`` is never consulted — the Rule-1
output-schema binding is verified only against the selected
``validator_rule_parameters@0.2.0`` stage payload.

The runner reads no clock, Git state, provider, or network endpoint; every
timestamp is the plan's ``evaluation_created_at``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError as PydanticValidationError, model_validator

from .assertions import (
    AssertionEvaluationError,
    BoundEvaluationCase,
    ResolvedAssertionDispatch,
    evaluate_case_assertions,
    load_assertion_outcomes,
    persist_assertion_outcomes,
)
from .axis_inputs import build_extraction_axis_evaluation_records
from .case_sets import CaseSetLoadError, load_case_set_manifest
from .cases import CaseLoadError, load_case
from .contracts import ContractError, canonical_contract_bytes, model_contract_hash
from .envelopes import (
    EnvelopeError,
    PredictionArtifactManifest,
    load_prediction_envelopes,
    normalize_prediction_artifact,
)
from .gates import (
    EvaluationIssue,
    GateEvaluationError,
    GateMetricSelectionError,
    GatePolicyError,
    LoadedEvaluationResult,
    assess_completed_evaluation,
    build_errored_evaluation,
    build_invalid_evaluation,
    load_evaluation_result,
    persist_evaluation_result,
)
from .gold import (
    GoldAssertionSetError,
    bind_gold_assertion_set,
    gold_assertion_set_hash,
    load_gold_assertion_set,
)
from .metric_inputs import (
    AssertionMetricBinding,
    MetricInputSnapshotError,
    ValidatorRuleEvaluationRecord,
    build_metric_input_snapshot,
    load_metric_input_snapshot,
    persist_metric_input_snapshot,
)
from .metrics import (
    MetricError,
    compute_metric_report_v2,
    load_metric_report_v2,
    persist_metric_report,
)
from .models import (
    EvaluationRunManifestV2,
    EvaluationStrictModel,
    PredictionEnvelope,
    _require_rfc3339_offset,
)
from .observation_target_binding import (
    ObservationTargetBindingError,
    build_observation_target_binding,
    load_observation_target_binding,
    persist_observation_target_binding,
)
from .output_manifest import (
    EvaluationOutputManifestError,
    LoadedEvaluationOutputManifestV2,
    build_evaluation_output_manifest_v2,
    load_evaluation_output_manifest_v2,
    persist_evaluation_output_manifest_v2,
)
from .parent_observation_snapshot import (
    ParentObservationSnapshotError,
    load_parent_observation_snapshot,
)
from .prediction_content import (
    ParsedPredictionContentError,
    load_parsed_prediction_content,
    persist_parsed_prediction_content,
)
from .references import (
    BlockingResolutionError,
    TargetRegistryLoadError,
    load_target_registry,
    resolve_case_references,
)
from .report import (
    _ReportWriteError,
    build_machine_report,
    persist_evaluation_reports,
    render_human_report,
)
from .resolution_decisions import (
    ObservationTargetResolutionDecisionSetError,
    load_observation_target_resolution_decision_set,
)
from .runs import (
    RunPersistenceError,
    initialize_evaluation_run_v2,
    load_evaluation_run_manifest_v2,
)
from .scoring_config import ScoringConfigLoadError, load_scoring_gate_config
from .semantic_adapters import (
    SemanticAdapterError,
    apply_semantic_adapter,
    load_semantic_adapter_registry,
    resolve_semantic_adapter,
    semantic_adapter_registry_hash,
)
from .semantic_assertions import (
    SemanticAssertionEvaluationError,
    build_extraction_resolved_assertion_evaluations,
)
from .source_snapshot import (
    SourceSnapshotError,
    load_source_passage_snapshot_manifest,
    source_passage_snapshot_manifest_hash,
)
from .stage_profiles import StageProfileError, load_stage_profile_registry
from .taxonomy import AxisTaxonomyError, axis_taxonomy_hash, load_axis_taxonomy
from .validation_inputs import ExtractionEvaluationStage, build_extraction_validation_inputs
from .validation_snapshot import (
    ValidationArtifactSnapshotSetError,
    build_validation_artifact_snapshot_set,
    load_validation_artifact_snapshot_set,
    persist_validation_artifact_snapshot_set,
)
from .validator_bundle_artifact import (
    ValidatorBundleArtifactError,
    load_validator_bundle_artifact,
)
from .validator_parameters import (
    ValidatorRuleParametersError,
    ValidatorRuleParametersV2,
    load_validator_rule_parameters_v2,
    validator_rule_parameters_aggregate_hash,
)
from .validators import (
    ValidatorError,
    build_validation_artifact_snapshot,
    evaluate_validator_findings,
    load_validator_findings,
    persist_validator_findings,
)
from ..universe.io_utils import sha256_bytes

__all__ = [
    "EvaluationRunPlan",
    "PlannedArtifactReference",
    "SingleCaseEvaluationRun",
    "run_single_case_evaluation",
]

_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"

# Closed governed role vocabulary, in canonical ascending order.
PlannedArtifactRole = Literal[
    "axis_taxonomy",
    "case",
    "case_set_manifest",
    "gold_assertion_set",
    "observation_target_resolution_decision_set",
    "output_schema",
    "parent_observation_snapshot",
    "prediction_run_manifest",
    "raw_prediction_artifact",
    "scoring_gate_config",
    "semantic_adapter_registry",
    "source_passage_snapshot_manifest",
    "stage_profile_registry",
    "target_registry",
    "validator_bundle_artifact",
    "validator_rule_parameters",
]

# Governed root membership per role (spec-fixed; validated on the plan).
_ROLE_ROOT: dict[str, str] = {
    "axis_taxonomy": "governed",
    "case": "governed",
    "case_set_manifest": "governed",
    "gold_assertion_set": "governed",
    "observation_target_resolution_decision_set": "adjudication",
    "output_schema": "governed",
    "parent_observation_snapshot": "governed",
    "prediction_run_manifest": "prediction",
    "raw_prediction_artifact": "prediction",
    "scoring_gate_config": "governed",
    "semantic_adapter_registry": "governed",
    "source_passage_snapshot_manifest": "governed",
    "stage_profile_registry": "governed",
    "target_registry": "governed",
    "validator_bundle_artifact": "governed",
    "validator_rule_parameters": "governed",
}

_ALL_ROLES: tuple[str, ...] = tuple(sorted(_ROLE_ROOT))

_RULE_1 = "output_json_schema_validity"
_MANIFEST_CONTRACT_ID = "prediction_artifact_manifest"
_MANIFEST_CONTRACT_VERSION = "0.1.0"

# Sanitized governed error classes: a post-manifest failure of one of these
# kinds is a content/binding invalidity, not a runtime fault.
_GOVERNED_INVALID_ERRORS: tuple[type[Exception], ...] = (
    AssertionEvaluationError,
    AxisTaxonomyError,
    BlockingResolutionError,
    CaseLoadError,
    CaseSetLoadError,
    ContractError,
    EnvelopeError,
    EvaluationOutputManifestError,
    GoldAssertionSetError,
    MetricError,
    MetricInputSnapshotError,
    ObservationTargetBindingError,
    ObservationTargetResolutionDecisionSetError,
    ParentObservationSnapshotError,
    ParsedPredictionContentError,
    RunPersistenceError,
    ScoringConfigLoadError,
    SemanticAdapterError,
    SemanticAssertionEvaluationError,
    SourceSnapshotError,
    StageProfileError,
    TargetRegistryLoadError,
    ValidationArtifactSnapshotSetError,
    ValidatorBundleArtifactError,
    ValidatorError,
    ValidatorRuleParametersError,
)

_REPORT_FAILURES: tuple[type[Exception], ...] = (
    _ReportWriteError,
    OSError,
    TypeError,
    ValueError,
)


class _PreManifestEvaluationError(Exception):
    """Private pre-manifest operational failure: exit code 4, no writes."""

    def __init__(self, issues: tuple[EvaluationIssue, ...]) -> None:
        message = issues[0].message if issues else "pre-manifest operational failure"
        super().__init__(message)
        self.issues = tuple(issues)
        self.exit_code = 4


def _fail(
    issue_code: str, message: str, artifact_reference: str | None = None
) -> None:
    raise _PreManifestEvaluationError(
        (
            EvaluationIssue(
                issue_code=issue_code,
                message=message,
                artifact_reference=artifact_reference,
            ),
        )
    )


def _is_safe_reference(value: Any) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if value.startswith("/") or "\\" in value or "\x00" in value or "\n" in value:
        return False
    return all(part not in ("", ".", "..") for part in value.split("/"))


def _require_non_blank(value: str, field_name: str) -> None:
    if not value or value != value.strip():
        raise ValueError(
            f"{field_name} must be a non-empty string without leading or trailing whitespace"
        )


class PlannedArtifactReference(EvaluationStrictModel):
    """One role-bound, root-bound, raw-byte-pinned planned input artifact."""

    artifact_role: PlannedArtifactRole
    artifact_root: Literal["governed", "prediction", "adjudication"]
    reference: str
    sha256: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)

    @model_validator(mode="after")
    def _reference_invariants(self) -> "PlannedArtifactReference":
        if not _is_safe_reference(self.reference):
            raise ValueError(
                "reference must be a safe relative POSIX reference without absolute, "
                "empty, dot, dot-dot, backslash, or NUL components"
            )
        expected_root = _ROLE_ROOT[self.artifact_role]
        if self.artifact_root != expected_root:
            raise ValueError(
                f"artifact_role {self.artifact_role!r} must bind artifact_root "
                f"{expected_root!r}, got {self.artifact_root!r}"
            )
        return self


class EvaluationRunPlan(EvaluationStrictModel):
    """Strict single-case evaluation plan: identity, roots, and 16 pinned roles."""

    eval_run_id: str
    evaluation_stage: ExtractionEvaluationStage
    prediction_run_id: str
    prediction_record_id: str
    company_id: str
    code_commit: str
    evaluation_created_at: str
    governed_artifact_root: str
    prediction_source_root: str
    adjudication_source_root: str
    artifact_references: tuple[PlannedArtifactReference, ...]

    @model_validator(mode="after")
    def _plan_invariants(self) -> "EvaluationRunPlan":
        for field_name in (
            "eval_run_id",
            "prediction_run_id",
            "prediction_record_id",
            "company_id",
            "code_commit",
            "governed_artifact_root",
            "prediction_source_root",
            "adjudication_source_root",
        ):
            _require_non_blank(getattr(self, field_name), field_name)
        run_id = self.eval_run_id
        if "/" in run_id or "\\" in run_id or "\x00" in run_id or run_id in (".", ".."):
            raise ValueError("eval_run_id must be a single safe path component")
        _require_rfc3339_offset(self.evaluation_created_at, "evaluation_created_at")
        roles = tuple(entry.artifact_role for entry in self.artifact_references)
        if len(roles) != len(_ALL_ROLES) or set(roles) != set(_ALL_ROLES):
            raise ValueError(
                "artifact_references must contain each of the sixteen governed roles "
                "exactly once"
            )
        if any(roles[i] >= roles[i + 1] for i in range(len(roles) - 1)):
            raise ValueError(
                "artifact_references must be strictly ascending by artifact_role; "
                "unsorted input is rejected, never sorted"
            )
        return self


class SingleCaseEvaluationRun(EvaluationStrictModel):
    """Terminal summary of one runner invocation; built only after read-back."""

    eval_run_id: str
    evaluation_stage: ExtractionEvaluationStage
    execution_status: Literal["completed", "invalid", "errored"]
    gate_verdict: Literal["pass", "fail", "indeterminate"] | None = None
    result_sha256: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
    output_manifest_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN
    )
    machine_report_reference: str | None = None
    human_report_reference: str | None = None
    exit_code: int = Field(ge=0, le=5)
    issues: tuple[EvaluationIssue, ...] = ()


class _PreManifestInputs:
    """Every verified pre-manifest input, keyed for the lifecycle steps."""

    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)


def _entry(plan: EvaluationRunPlan, role: str) -> PlannedArtifactReference:
    for entry in plan.artifact_references:
        if entry.artifact_role == role:
            return entry
    raise AssertionError(f"validated plan is missing role {role!r}")  # pragma: no cover


def _revalidated_plan(plan: EvaluationRunPlan) -> EvaluationRunPlan:
    if not isinstance(plan, EvaluationRunPlan):
        raise TypeError(
            f"plan must be an EvaluationRunPlan, got {type(plan).__name__}"
        )
    try:
        return EvaluationRunPlan.model_validate(
            plan.model_dump(mode="json", exclude_unset=True)
        )
    except PydanticValidationError:
        _fail("plan_invalid", "the plan failed fail-closed strict revalidation")
    raise AssertionError("unreachable")  # pragma: no cover


def _resolved_root(value: str, label: str) -> Path:
    root = Path(value)
    if not root.is_dir():
        _fail("artifact_missing", f"{label} does not resolve to an existing directory")
    return root.resolve()


def _read_verified_bytes(
    root: Path, reference: str, expected_sha256: str, role: str, label: str
) -> bytes:
    if not _is_safe_reference(reference):
        _fail(
            "artifact_path_escape",
            f"{role} reference is not a safe relative POSIX reference",
            None,
        )
    candidate = root / reference
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        _fail(
            "artifact_path_escape",
            f"{role} reference escapes the {label}",
            reference,
        )
    if candidate.is_symlink() or not resolved.is_file():
        _fail(
            "artifact_missing",
            f"{role} reference does not resolve to a regular file",
            reference,
        )
    try:
        data = resolved.read_bytes()
    except OSError:
        _fail(
            "artifact_read_error",
            f"failed to read the {role} raw bytes",
            reference,
        )
    if sha256_bytes(data) != expected_sha256:
        _fail(
            "artifact_pin_mismatch",
            f"{role} raw persisted bytes do not hash to the planned pin",
            reference,
        )
    return data


def _read_pinned_bytes(root: Path, entry: PlannedArtifactReference, label: str) -> bytes:
    return _read_verified_bytes(
        root, entry.reference, entry.sha256, entry.artifact_role, label
    )


def _strict_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _loaded(role: str, reference: str, loader: Any) -> Any:
    """Run one public loader inside the sanitized pre-manifest boundary."""
    try:
        return loader()
    except _PreManifestEvaluationError:
        raise
    except (
        _GOVERNED_INVALID_ERRORS + (PydanticValidationError, ValueError, TypeError, OSError)
    ) as exc:
        _fail(
            "artifact_malformed",
            f"{role} failed public loading ({type(exc).__name__})",
            reference,
        )
    raise AssertionError("unreachable")  # pragma: no cover


def _parse_prediction_manifest(
    manifest_bytes: bytes, reference: str
) -> PredictionArtifactManifest:
    try:
        payload = json.loads(
            manifest_bytes.decode("utf-8"), object_pairs_hook=_strict_json_pairs
        )
    except (UnicodeDecodeError, ValueError):
        _fail(
            "artifact_malformed",
            "prediction_run_manifest is not a strict JSON document",
            reference,
        )
    if not isinstance(payload, dict):
        _fail(
            "artifact_malformed",
            "prediction_run_manifest top-level value must be a JSON object",
            reference,
        )
    try:
        manifest = PredictionArtifactManifest.model_validate(payload)
    except PydanticValidationError:
        _fail(
            "artifact_malformed",
            "prediction_run_manifest failed strict contract validation",
            reference,
        )
        raise AssertionError("unreachable")  # pragma: no cover
    expected_hash = model_contract_hash(
        PredictionArtifactManifest, _MANIFEST_CONTRACT_ID, _MANIFEST_CONTRACT_VERSION
    )
    contract = manifest.contract
    if (
        contract.contract_id != _MANIFEST_CONTRACT_ID
        or contract.contract_version != _MANIFEST_CONTRACT_VERSION
        or contract.contract_hash != expected_hash
    ):
        _fail(
            "artifact_malformed",
            "prediction_run_manifest carries an unapproved contract stamp",
            reference,
        )
    return manifest


def _parse_prediction_envelopes(
    envelopes_bytes: bytes, reference: str
) -> tuple[PredictionEnvelope, ...]:
    try:
        text = envelopes_bytes.decode("utf-8")
    except UnicodeDecodeError:
        _fail("artifact_malformed", "prediction envelopes are not valid UTF-8", reference)
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    envelopes: list[PredictionEnvelope] = []
    for line in lines:
        try:
            payload = json.loads(line, object_pairs_hook=_strict_json_pairs)
            envelopes.append(PredictionEnvelope.model_validate(payload))
        except (ValueError, PydanticValidationError):
            _fail(
                "artifact_malformed",
                "a prediction envelope line failed strict contract validation",
                reference,
            )
    return tuple(envelopes)


def _execute_pre_manifest(plan: EvaluationRunPlan) -> _PreManifestInputs:
    """Steps 1-3: plan validation, raw-byte pins, public loading, cardinality.

    Runs the complete pre-manifest boundary without creating a run directory,
    initializing a run, invoking any persister, or writing anything.
    """
    plan = _revalidated_plan(plan)
    governed_root = _resolved_root(plan.governed_artifact_root, "governed_artifact_root")
    prediction_root = _resolved_root(plan.prediction_source_root, "prediction_source_root")
    adjudication_root = _resolved_root(
        plan.adjudication_source_root, "adjudication_source_root"
    )
    roots = {
        "governed": governed_root,
        "prediction": prediction_root,
        "adjudication": adjudication_root,
    }
    raw_bytes_by_role: dict[str, bytes] = {}
    for entry in plan.artifact_references:
        raw_bytes_by_role[entry.artifact_role] = _read_pinned_bytes(
            roots[entry.artifact_root], entry, f"{entry.artifact_root} root"
        )

    reg_entry = _entry(plan, "target_registry")
    cs_entry = _entry(plan, "case_set_manifest")
    sc_entry = _entry(plan, "scoring_gate_config")
    sp_entry = _entry(plan, "stage_profile_registry")
    adapters_entry = _entry(plan, "semantic_adapter_registry")
    gold_entry = _entry(plan, "gold_assertion_set")
    tax_entry = _entry(plan, "axis_taxonomy")
    snap_entry = _entry(plan, "source_passage_snapshot_manifest")
    params_entry = _entry(plan, "validator_rule_parameters")
    bundle_entry = _entry(plan, "validator_bundle_artifact")
    case_entry = _entry(plan, "case")
    parents_entry = _entry(plan, "parent_observation_snapshot")
    decisions_entry = _entry(plan, "observation_target_resolution_decision_set")
    manifest_entry = _entry(plan, "prediction_run_manifest")
    raw_entry = _entry(plan, "raw_prediction_artifact")
    schema_entry = _entry(plan, "output_schema")

    reg = _loaded(
        "target_registry",
        reg_entry.reference,
        lambda: load_target_registry(
            reg_entry.reference, eval_root=governed_root, expected_sha256=reg_entry.sha256
        ),
    )
    cs = _loaded(
        "case_set_manifest",
        cs_entry.reference,
        lambda: load_case_set_manifest(cs_entry.reference, eval_root=governed_root),
    )
    sc = _loaded(
        "scoring_gate_config",
        sc_entry.reference,
        lambda: load_scoring_gate_config(
            sc_entry.reference, eval_root=governed_root, expected_sha256=sc_entry.sha256
        ),
    )
    sp = _loaded(
        "stage_profile_registry",
        sp_entry.reference,
        lambda: load_stage_profile_registry(
            sp_entry.reference, eval_root=governed_root, expected_sha256=sp_entry.sha256
        ),
    )
    adapters = _loaded(
        "semantic_adapter_registry",
        adapters_entry.reference,
        lambda: load_semantic_adapter_registry(
            adapters_entry.reference,
            eval_root=governed_root,
            expected_sha256=adapters_entry.sha256,
        ),
    )
    gold = _loaded(
        "gold_assertion_set",
        gold_entry.reference,
        lambda: load_gold_assertion_set(
            gold_entry.reference, eval_root=governed_root, expected_sha256=gold_entry.sha256
        ),
    )
    tax = _loaded(
        "axis_taxonomy",
        tax_entry.reference,
        lambda: load_axis_taxonomy(
            tax_entry.reference, eval_root=governed_root, expected_sha256=tax_entry.sha256
        ),
    )
    snap = _loaded(
        "source_passage_snapshot_manifest",
        snap_entry.reference,
        lambda: load_source_passage_snapshot_manifest(
            snap_entry.reference, eval_root=governed_root, expected_sha256=snap_entry.sha256
        ),
    )
    params = _loaded(
        "validator_rule_parameters",
        params_entry.reference,
        lambda: load_validator_rule_parameters_v2(
            params_entry.reference,
            eval_root=governed_root,
            expected_sha256=params_entry.sha256,
        ),
    )
    if not isinstance(params.model, ValidatorRuleParametersV2):
        _fail(
            "artifact_malformed",
            "validator_rule_parameters must carry validator_rule_parameters@0.2.0",
            params_entry.reference,
        )
    bundle = _loaded(
        "validator_bundle_artifact",
        bundle_entry.reference,
        lambda: load_validator_bundle_artifact(
            bundle_entry.reference,
            eval_root=governed_root,
            rule_parameters=params,
            expected_sha256=bundle_entry.sha256,
        ),
    )
    case = _loaded(
        "case",
        case_entry.reference,
        lambda: load_case(case_entry.reference, eval_root=governed_root),
    )
    parents = _loaded(
        "parent_observation_snapshot",
        parents_entry.reference,
        lambda: load_parent_observation_snapshot(
            parents_entry.reference,
            source_root=governed_root,
            expected_sha256=parents_entry.sha256,
        ),
    )
    decisions = _loaded(
        "observation_target_resolution_decision_set",
        decisions_entry.reference,
        lambda: load_observation_target_resolution_decision_set(
            decisions_entry.reference,
            source_root=adjudication_root,
            expected_sha256=decisions_entry.sha256,
        ),
    )

    manifest = _parse_prediction_manifest(
        raw_bytes_by_role["prediction_run_manifest"], manifest_entry.reference
    )
    if manifest.prediction_run_id != plan.prediction_run_id:
        _fail(
            "prediction_binding_invalid",
            "prediction_run_manifest prediction_run_id does not equal the plan's",
            manifest_entry.reference,
        )
    if not any(
        source.reference == raw_entry.reference and source.sha256 == raw_entry.sha256
        for source in manifest.source_artifacts
    ):
        _fail(
            "prediction_binding_invalid",
            "raw_prediction_artifact is not declared hash-bound by the prediction manifest",
            raw_entry.reference,
        )
    envelopes_bytes = _read_verified_bytes(
        prediction_root,
        manifest.envelopes_reference,
        manifest.envelopes_sha256,
        "prediction envelopes",
        "prediction root",
    )
    envelopes = _parse_prediction_envelopes(envelopes_bytes, manifest.envelopes_reference)
    if manifest.record_count != len(envelopes):
        _fail(
            "prediction_binding_invalid",
            "prediction manifest record_count does not equal the envelope count",
            manifest_entry.reference,
        )

    # Single-case cardinality: singletons everywhere, never a selection.
    if len(envelopes) != 1:
        _fail(
            "cardinality_invalid",
            "the prediction artifact must carry exactly one prediction envelope",
            manifest.envelopes_reference,
        )
    if len(cs.entries) != 1:
        _fail(
            "cardinality_invalid",
            "the case-set manifest must carry exactly one case membership",
            cs_entry.reference,
        )
    envelope = envelopes[0]
    membership = cs.entries[0]
    if case.stage != plan.evaluation_stage:
        _fail(
            "cardinality_invalid",
            "the case stage does not equal the planned evaluation stage",
            case_entry.reference,
        )
    if envelope.stage != plan.evaluation_stage:
        _fail(
            "cardinality_invalid",
            "the prediction envelope stage does not equal the planned evaluation stage",
            manifest.envelopes_reference,
        )
    if membership.case_id != case.case_id:
        _fail(
            "cardinality_invalid",
            "the single case-set membership does not name the planned case",
            cs_entry.reference,
        )
    if membership.input_packet_hash != envelope.input_packet_hash:
        _fail(
            "cardinality_invalid",
            "no single case matches the envelope on (input_packet_hash, stage)",
            cs_entry.reference,
        )
    if envelope.prediction_record_id != plan.prediction_record_id:
        _fail(
            "prediction_binding_invalid",
            "the prediction envelope prediction_record_id does not equal the plan's",
            manifest.envelopes_reference,
        )

    decision_set = decisions.model
    if decision_set.case_id != case.case_id:
        _fail(
            "adjudication_binding_invalid",
            "the decision set case_id does not equal the planned case",
            decisions_entry.reference,
        )
    if decision_set.stage != plan.evaluation_stage:
        _fail(
            "adjudication_binding_invalid",
            "the decision set stage does not equal the planned evaluation stage",
            decisions_entry.reference,
        )
    if decision_set.company_id != plan.company_id:
        _fail(
            "adjudication_binding_invalid",
            "the decision set company_id does not equal the plan's",
            decisions_entry.reference,
        )
    if decision_set.prediction_record_id != plan.prediction_record_id:
        _fail(
            "adjudication_binding_invalid",
            "the decision set prediction_record_id does not equal the plan's",
            decisions_entry.reference,
        )
    if (
        decision_set.raw_artifact_reference != raw_entry.reference
        or decision_set.raw_artifact_sha256 != raw_entry.sha256
    ):
        _fail(
            "adjudication_binding_invalid",
            "the decision set raw-artifact identity does not equal the planned "
            "raw_prediction_artifact pin",
            decisions_entry.reference,
        )

    # Rule-1 output-schema binding: the selected V2 stage payload is the only
    # authority; the static anchor table is never consulted here.
    rule1_entries = [e for e in params.model.entries if e.rule_id == _RULE_1]
    if len(rule1_entries) != 1:
        _fail(
            "output_schema_binding_invalid",
            "validator_rule_parameters must carry exactly one Rule-1 entry",
            params_entry.reference,
        )
    stage_params = [
        sp_ for sp_ in rule1_entries[0].stage_parameters if sp_.stage == plan.evaluation_stage
    ]
    if len(stage_params) != 1:
        _fail(
            "output_schema_binding_invalid",
            "Rule 1 does not select exactly one parameter at the planned stage",
            params_entry.reference,
        )
    rule1 = stage_params[0]
    if rule1.applicability != "applicable" or rule1.payload.payload_kind != (
        "rule1_static_schema"
    ):
        _fail(
            "output_schema_binding_invalid",
            "Rule 1 must select an applicable static-schema payload at an extraction stage",
            params_entry.reference,
        )
    if schema_entry.reference != rule1.payload.output_schema_reference:
        _fail(
            "output_schema_binding_invalid",
            "the output_schema reference does not equal the selected Rule-1 payload's "
            "output_schema_reference",
            schema_entry.reference,
        )
    if schema_entry.sha256 != rule1.payload.output_schema_sha256:
        _fail(
            "output_schema_binding_invalid",
            "the output_schema pin does not equal the selected Rule-1 payload's "
            "output_schema_sha256",
            schema_entry.reference,
        )

    return _PreManifestInputs(
        plan=plan,
        governed_root=governed_root,
        prediction_root=prediction_root,
        adjudication_root=adjudication_root,
        reg=reg,
        cs=cs,
        sc=sc,
        sp=sp,
        adapters=adapters,
        gold=gold,
        tax=tax,
        snap=snap,
        params=params,
        bundle=bundle,
        case=case,
        parents=parents,
        decisions=decisions,
        prediction_manifest=manifest,
        membership=membership,
        prediction_manifest_entry=manifest_entry,
        raw_entry=raw_entry,
        raw_bytes=raw_bytes_by_role["raw_prediction_artifact"],
        schema_bytes=raw_bytes_by_role["output_schema"],
    )


def _classify_failure(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, GatePolicyError):
        return "invalid", "gate_policy_invalid"
    if isinstance(exc, GateMetricSelectionError):
        return "invalid", "metric_selection_invalid"
    if isinstance(exc, GateEvaluationError):
        return "invalid", "artifact_binding_invalid"
    if isinstance(exc, _GOVERNED_INVALID_ERRORS) or isinstance(exc, ValueError):
        return "invalid", "artifact_binding_invalid"
    return "errored", "runtime_failure"


def _invalid_issue_message(exc: BaseException) -> str:
    text = str(exc).strip()
    if not text:
        return f"governed invalidity ({type(exc).__name__})"
    return text[:500]


def _exit_code_for_completed(gate_verdict: str) -> int:
    return 0 if gate_verdict == "pass" else 1


def _finalize(
    loaded_result: LoadedEvaluationResult,
    manifest_wrapper: LoadedEvaluationOutputManifestV2 | None,
    *,
    plan: EvaluationRunPlan,
    eval_root: Path,
    base_exit_code: int,
    issues: tuple[EvaluationIssue, ...],
) -> SingleCaseEvaluationRun:
    """Build/render/persist reports and assemble the terminal summary."""
    machine_report = build_machine_report(loaded_result, manifest_wrapper)
    human_report = render_human_report(machine_report)
    exit_code = base_exit_code
    machine_reference: str | None = None
    human_reference: str | None = None
    summary_issues = issues
    try:
        persisted_reports = persist_evaluation_reports(
            machine_report,
            human_report,
            eval_root=eval_root,
            eval_run_id=plan.eval_run_id,
        )
    except _REPORT_FAILURES:
        # The terminal result stays byte-identical; existing report files are
        # never deleted, repaired, overwritten, or retried.
        exit_code = 5
        summary_issues = issues + (
            EvaluationIssue(
                issue_code="report_persistence_failed",
                message="report persistence failed after the terminal result became immutable",
            ),
        )
    else:
        machine_reference = persisted_reports.machine_report_reference
        human_reference = persisted_reports.human_report_reference
    result = loaded_result.result
    return SingleCaseEvaluationRun(
        eval_run_id=plan.eval_run_id,
        evaluation_stage=plan.evaluation_stage,
        execution_status=result.execution_status,
        gate_verdict=result.gate_verdict if result.execution_status == "completed" else None,
        result_sha256=loaded_result.sha256,
        output_manifest_sha256=(
            manifest_wrapper.sha256 if manifest_wrapper is not None else None
        ),
        machine_report_reference=machine_reference,
        human_report_reference=human_reference,
        exit_code=exit_code,
        issues=summary_issues,
    )


def _terminal_failure(
    exc: BaseException,
    *,
    plan: EvaluationRunPlan,
    eval_root: Path,
    run_manifest: EvaluationRunManifestV2,
    state: dict[str, Any],
    inputs: _PreManifestInputs,
) -> SingleCaseEvaluationRun:
    """Persist a terminal invalid/errored result plus reports after a failure."""
    status, issue_code = _classify_failure(exc)
    if status == "invalid":
        issues = [EvaluationIssue(issue_code=issue_code, message=_invalid_issue_message(exc))]
    else:
        issues = [
            EvaluationIssue(
                issue_code="runtime_failure",
                message=f"unhandled runtime failure ({type(exc).__name__})",
            )
        ]
    manifest_wrapper: LoadedEvaluationOutputManifestV2 | None = state.get("manifest")
    if manifest_wrapper is None and state.get("findings") is not None:
        # Findings exist: the output manifest is built from every successfully
        # persisted optional artifact before the terminal result. Omitting an
        # existing artifact is rejected by output_manifest.py itself.
        try:
            built = build_evaluation_output_manifest_v2(
                eval_root=eval_root,
                eval_run_id=plan.eval_run_id,
                stage_profile_registry=inputs.sp,
                validator_findings=state["findings"],
                parsed_prediction_content=state.get("parsed"),
                observation_target_binding=state.get("binding"),
                assertion_outcomes=state.get("outcomes"),
                validation_artifact_snapshot_set=state.get("vset"),
                metric_input_snapshot=state.get("mis"),
                metric_report=state.get("report"),
            )
            persist_evaluation_output_manifest_v2(
                built, eval_root=eval_root, eval_run_id=plan.eval_run_id
            )
            manifest_wrapper = load_evaluation_output_manifest_v2(
                plan.eval_run_id, eval_root=eval_root, stage_profile_registry=inputs.sp
            )
        except Exception as manifest_exc:
            status = "errored"
            issues = [
                EvaluationIssue(
                    issue_code="runtime_failure",
                    message=(
                        "terminal output-manifest persistence failed "
                        f"({type(manifest_exc).__name__}) after "
                        f"{type(exc).__name__}"
                    ),
                )
            ]
            manifest_wrapper = None
    metric_report_sha256 = (
        state["report"].sha256 if state.get("report") is not None else None
    )
    if status == "invalid":
        result = build_invalid_evaluation(
            stage=plan.evaluation_stage,
            run_manifest=run_manifest,
            issues=tuple(issues),
            metric_report_sha256=metric_report_sha256,
        )
        base_exit_code = 2
    else:
        result = build_errored_evaluation(
            stage=plan.evaluation_stage,
            run_manifest=run_manifest,
            issues=tuple(issues),
            metric_report_sha256=metric_report_sha256,
        )
        base_exit_code = 3
    persist_evaluation_result(result, eval_root=eval_root, eval_run_id=plan.eval_run_id)
    loaded_result = load_evaluation_result(plan.eval_run_id, eval_root=eval_root)
    return _finalize(
        loaded_result,
        manifest_wrapper,
        plan=plan,
        eval_root=eval_root,
        base_exit_code=base_exit_code,
        issues=tuple(issues),
    )


def run_single_case_evaluation(
    plan: EvaluationRunPlan, *, eval_root: str | Path
) -> SingleCaseEvaluationRun:
    """Execute one governed single-case evaluation end to end.

    Steps 1-3 (plan validation, raw-byte pin verification, public loading, and
    single-case cardinality) run before any run directory exists; their
    failures raise the private pre-manifest exception (exit code 4) and write
    nothing. Every later failure persists a terminal invalid/errored
    ``EvaluationResultV2`` plus machine/human reports. A summary is returned
    only after the terminal result has been persisted and reloaded.
    """
    inputs = _execute_pre_manifest(plan)
    plan = inputs.plan
    if not isinstance(eval_root, (str, Path)):
        raise TypeError(
            f"eval_root must be an explicit str or Path, got {type(eval_root).__name__}"
        )
    resolved_eval_root = Path(eval_root)
    stage = plan.evaluation_stage
    manifest_pin = inputs.prediction_manifest_entry.sha256

    adapter_entry = resolve_semantic_adapter(inputs.adapters.registry, stage)
    selected_adapter_hash = sha256_bytes(
        canonical_contract_bytes(adapter_entry.model_dump(mode="json"))
    )
    try:
        initialized = initialize_evaluation_run_v2(
            eval_root=resolved_eval_root,
            eval_run_id=plan.eval_run_id,
            prediction_run_id=plan.prediction_run_id,
            prediction_run_manifest_hash=manifest_pin,
            case_set=inputs.cs,
            registry=inputs.reg,
            validator_bundle_version=inputs.bundle.model.bundle_version,
            validator_bundle_hash=inputs.bundle.model.bundle_hash,
            scoring_config=inputs.sc,
            code_commit=plan.code_commit,
            config_snapshot_source_root=inputs.governed_root,
            evaluation_created_at=plan.evaluation_created_at,
            evaluation_stage=stage,
            stage_profile_registry=inputs.sp,
            semantic_adapter_registry_version=inputs.adapters.version,
            semantic_adapter_registry_hash=semantic_adapter_registry_hash(
                inputs.adapters.registry
            ),
            selected_semantic_adapter_entry_hash=selected_adapter_hash,
            source_passage_snapshot_version=inputs.snap.version,
            source_passage_snapshot_hash=source_passage_snapshot_manifest_hash(
                inputs.snap.manifest
            ),
            gold_assertion_set_version=inputs.gold.model.gold_set_version,
            gold_assertion_set_hash=gold_assertion_set_hash(inputs.gold.model),
            axis_taxonomy_version=inputs.tax.model.taxonomy_version,
            axis_taxonomy_hash=axis_taxonomy_hash(inputs.tax.model),
            validator_rule_parameters_version=inputs.params.model.parameter_set_version,
            validator_rule_parameters_hash=validator_rule_parameters_aggregate_hash(
                inputs.params.model
            ),
            stage_metric_evidence_set_version=None,
            stage_metric_evidence_set_hash=None,
        )
    except Exception as exc:
        # No run manifest was persisted by this invocation: the failure stays
        # on the pre-manifest raising path and no terminal result is fabricated.
        raise _PreManifestEvaluationError(
            (
                EvaluationIssue(
                    issue_code="run_initialization_failed",
                    message=(
                        "evaluation-run initialization failed before a run manifest "
                        f"was persisted ({type(exc).__name__})"
                    ),
                ),
            )
        ) from exc

    run_manifest: EvaluationRunManifestV2 = initialized.manifest
    state: dict[str, Any] = {}
    try:
        loaded_run = load_evaluation_run_manifest_v2(
            plan.eval_run_id, eval_root=resolved_eval_root
        )
        run_manifest = loaded_run.manifest

        # 5. Normalize the prediction artifact; reload envelopes; reverify the
        # prediction-manifest hash against the sole plan authority.
        normalized = normalize_prediction_artifact(
            inputs.prediction_manifest_entry.reference,
            source_root=inputs.prediction_root,
            eval_root=resolved_eval_root,
            eval_run_id=plan.eval_run_id,
        )
        if normalized.source_manifest_sha256 != manifest_pin:
            raise ValueError(
                "normalized prediction source_manifest_sha256 does not equal the "
                "planned prediction_run_manifest pin"
            )
        loaded_envelopes = load_prediction_envelopes(
            plan.eval_run_id, eval_root=resolved_eval_root
        )
        if len(loaded_envelopes.envelopes) != 1:
            raise ValueError(
                "the normalized prediction run must carry exactly one envelope"
            )
        envelope = loaded_envelopes.envelopes[0]

        # 6. Resolve case references.
        resolution = resolve_case_references(
            inputs.case, registry=inputs.reg, scoring_config=inputs.sc
        )

        # 7. Apply the semantic adapter; persist and reload parsed content.
        parsed_model = apply_semantic_adapter(
            inputs.adapters.registry,
            case=inputs.case,
            envelope=envelope,
            raw_artifact_reference=inputs.raw_entry.reference,
            raw_artifact_bytes=inputs.raw_bytes,
        )
        persisted_parsed = persist_parsed_prediction_content(
            parsed_model, eval_root=resolved_eval_root, eval_run_id=plan.eval_run_id
        )
        parsed = load_parsed_prediction_content(
            persisted_parsed.artifact_reference,
            eval_root=resolved_eval_root,
            expected_sha256=persisted_parsed.sha256,
        )
        state["parsed"] = parsed

        # 8. Observation-target binding from the loaded decision set and the
        # parent snapshot; persist and reload.
        binding_model = build_observation_target_binding(
            eval_run_id=plan.eval_run_id,
            case=inputs.case,
            company_id=plan.company_id,
            resolution=resolution,
            parsed_prediction_content=parsed,
            target_registry=inputs.reg,
            resolution_decision_set=inputs.decisions,
            parent_snapshot=inputs.parents,
        )
        persisted_binding = persist_observation_target_binding(
            binding_model, eval_root=resolved_eval_root, eval_run_id=plan.eval_run_id
        )
        binding = load_observation_target_binding(
            persisted_binding.artifact_reference,
            eval_root=resolved_eval_root,
            expected_sha256=persisted_binding.sha256,
        )
        state["binding"] = binding

        # 9. P2: Rules 1-11 validator inputs (verifies the output-schema
        # binding against the selected Rule-1 V2 payload again, on raw bytes).
        validation_inputs = build_extraction_validation_inputs(
            case=inputs.case,
            evaluation_stage=stage,
            parsed_prediction_content=parsed,
            raw_artifact_bytes=inputs.raw_bytes,
            output_schema_bytes=inputs.schema_bytes,
            source_snapshot=inputs.snap,
            rule_parameters=inputs.params,
            validator_bundle_artifact=inputs.bundle,
            run_manifest=run_manifest,
            observation_target_binding=binding,
            parent_snapshot=inputs.parents,
        )

        # 10. Validation snapshot (Rule 12 appended by the sanctioned builder);
        # snapshot set persisted and reloaded.
        validation_snapshot = build_validation_artifact_snapshot(
            parsed,
            eval_run_id=plan.eval_run_id,
            artifact_id=parsed.content.prediction_record_id,
            artifact_sha256=parsed.content.raw_artifact_sha256,
            created_at=plan.evaluation_created_at,
            case_id=inputs.case.case_id,
            observations=validation_inputs.observations,
            coverage=validation_inputs.coverage,
        )
        snapshot_set = build_validation_artifact_snapshot_set(
            snapshot_set_version=plan.eval_run_id,
            eval_run_id=plan.eval_run_id,
            evaluation_stage=stage,
            snapshots=(validation_snapshot,),
        )
        persisted_vset = persist_validation_artifact_snapshot_set(
            snapshot_set, eval_root=resolved_eval_root, eval_run_id=plan.eval_run_id
        )
        vset = load_validation_artifact_snapshot_set(
            persisted_vset.artifact_reference,
            eval_root=resolved_eval_root,
            expected_sha256=persisted_vset.sha256,
        )
        state["vset"] = vset

        # 11. Validator findings; persist and reload.
        evaluated_findings = evaluate_validator_findings(
            validation_snapshot,
            bundle=inputs.bundle.model.to_validator_bundle(),
            run_manifest=run_manifest,
            rule_parameters=inputs.params,
        )
        persisted_findings = persist_validator_findings(
            evaluated_findings.findings,
            eval_root=resolved_eval_root,
            eval_run_id=plan.eval_run_id,
        )
        state["findings"] = persisted_findings
        findings = load_validator_findings(plan.eval_run_id, eval_root=resolved_eval_root)

        # 12. Gold binding; semantic assertion evaluations; outcomes.
        bound_gold = bind_gold_assertion_set(
            inputs.gold,
            registry=inputs.reg,
            cases={inputs.case.case_id: inputs.case},
            resolutions={inputs.case.case_id: resolution},
        )
        semantic = build_extraction_resolved_assertion_evaluations(
            case=inputs.case,
            resolution=resolution,
            parsed_content=parsed,
            gold=inputs.gold,
            bound_gold=bound_gold,
            source_snapshot=inputs.snap,
            validation_snapshots=vset,
            validator_findings=findings,
            binding=binding,
        )
        references_by_id = {a.assertion_id: a for a in resolution.assertions}
        dispatches = tuple(
            ResolvedAssertionDispatch(
                status="resolved",
                resolution=references_by_id[evaluation.assertion_id],
                evaluation=evaluation,
            )
            for evaluation in semantic.evaluations
        )
        evaluated_case = evaluate_case_assertions(
            (BoundEvaluationCase(case=inputs.case, membership=inputs.membership),),
            case_set=inputs.cs,
            run_manifest=loaded_run,
            envelope=envelope,
            assertion_dispatches=dispatches,
        )
        persisted_outcomes = persist_assertion_outcomes(
            evaluated_case.outcomes,
            eval_root=resolved_eval_root,
            eval_run_id=plan.eval_run_id,
        )
        state["outcomes"] = persisted_outcomes
        outcomes = load_assertion_outcomes(plan.eval_run_id, eval_root=resolved_eval_root)

        # 13. P3 axis records; metric-input snapshot persisted and reloaded.
        axis_inputs_result = build_extraction_axis_evaluation_records(
            case=inputs.case,
            evaluation_stage=stage,
            parsed_prediction_content=parsed,
            source_snapshot=inputs.snap,
            axis_taxonomy=inputs.tax,
            gold=inputs.gold,
            bound_gold=bound_gold,
            run_manifest=run_manifest,
            observation_target_binding=binding,
        )
        assertion_bindings = tuple(
            AssertionMetricBinding(
                case_id=inputs.case.case_id,
                assertion_id=assertion.assertion_id,
                assertion_kind=assertion.kind,
                partition=inputs.membership.partition,
                suites=tuple(inputs.membership.suites),
            )
            for assertion in inputs.case.assertions
        )
        finding_counts: dict[tuple[str, str], int] = {}
        for finding in findings.findings:
            key = (finding.artifact_id, finding.validator)
            finding_counts[key] = finding_counts.get(key, 0) + 1
        rule_evaluations = tuple(
            ValidatorRuleEvaluationRecord(
                artifact_id=validation_snapshot.artifact_id,
                rule_id=coverage.rule_id,
                evaluated_observation_count=coverage.evaluated_observation_count,
                failed_observation_count=finding_counts.get(
                    (validation_snapshot.artifact_id, coverage.rule_id), 0
                ),
            )
            for coverage in validation_snapshot.coverage
            if coverage.evaluated_observation_count > 0
        )
        metric_inputs = build_metric_input_snapshot(
            evaluation_stage=stage,
            stage_profile_registry=inputs.sp,
            run_manifest=run_manifest,
            axis_definitions=axis_inputs_result.axis_definitions,
            axis_records=axis_inputs_result.axis_records,
            assertion_bindings=assertion_bindings,
            validator_rule_evaluations=rule_evaluations,
            stage_evidence=None,
        )
        persisted_metric_inputs = persist_metric_input_snapshot(
            metric_inputs, eval_root=resolved_eval_root, eval_run_id=plan.eval_run_id
        )
        state["mis"] = persisted_metric_inputs
        reloaded_metric_inputs = load_metric_input_snapshot(
            persisted_metric_inputs.artifact_reference,
            eval_root=resolved_eval_root,
            expected_sha256=persisted_metric_inputs.sha256,
        )

        # 14. metric_report@0.2.0 computed, persisted, and reloaded.
        metric_report = compute_metric_report_v2(
            reloaded_metric_inputs.model,
            assertion_outcomes=outcomes.outcomes,
            validator_findings=findings.findings,
            run_manifest=run_manifest,
            case_set_manifest=inputs.cs,
            scoring_config=inputs.sc,
            stage_profile_registry=inputs.sp,
        )
        persisted_report = persist_metric_report(
            metric_report,
            eval_root=resolved_eval_root,
            eval_run_id=plan.eval_run_id,
            stage_profile_registry=inputs.sp,
        )
        state["report"] = persisted_report
        reloaded_report = load_metric_report_v2(
            plan.eval_run_id, eval_root=resolved_eval_root, stage_profile_registry=inputs.sp
        )

        # 15. Output manifest v0.2: the stage is reverse-resolved from the run
        # manifest and stage-profile registry, never supplied.
        output_manifest = build_evaluation_output_manifest_v2(
            eval_root=resolved_eval_root,
            eval_run_id=plan.eval_run_id,
            stage_profile_registry=inputs.sp,
            validator_findings=persisted_findings,
            parsed_prediction_content=parsed,
            observation_target_binding=binding,
            assertion_outcomes=persisted_outcomes,
            validation_artifact_snapshot_set=vset,
            metric_input_snapshot=persisted_metric_inputs,
            metric_report=persisted_report,
        )
        persisted_manifest = persist_evaluation_output_manifest_v2(
            output_manifest, eval_root=resolved_eval_root, eval_run_id=plan.eval_run_id
        )
        manifest_wrapper = load_evaluation_output_manifest_v2(
            plan.eval_run_id, eval_root=resolved_eval_root, stage_profile_registry=inputs.sp
        )
        if manifest_wrapper.sha256 != persisted_manifest.sha256:
            raise ValueError(
                "the reloaded output manifest hash does not equal the persisted hash"
            )
        state["manifest"] = manifest_wrapper

        # 16. Terminal EvaluationResultV2 assessed, persisted, and reloaded.
        result = assess_completed_evaluation(
            stage=stage,
            run_manifest=run_manifest,
            case_set_manifest=inputs.cs,
            scoring_config=inputs.sc,
            metric_report=reloaded_report,
            findings=findings,
        )
        persist_evaluation_result(
            result, eval_root=resolved_eval_root, eval_run_id=plan.eval_run_id
        )
        loaded_result = load_evaluation_result(
            plan.eval_run_id, eval_root=resolved_eval_root
        )
    except Exception as exc:
        return _terminal_failure(
            exc,
            plan=plan,
            eval_root=resolved_eval_root,
            run_manifest=run_manifest,
            state=state,
            inputs=inputs,
        )

    # 17. Machine and human reports; terminal summary.
    return _finalize(
        loaded_result,
        state["manifest"],
        plan=plan,
        eval_root=resolved_eval_root,
        base_exit_code=_exit_code_for_completed(loaded_result.result.gate_verdict),
        issues=(),
    )


def _load_plan_document(path: str) -> EvaluationRunPlan:
    # The plan path is caller-environment specific (often absolute); it is never
    # placed into the sanitized issue material.
    try:
        raw = Path(path).read_bytes()
    except OSError:
        _fail("plan_invalid", "the plan document could not be read")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_json_pairs)
    except (UnicodeDecodeError, ValueError):
        _fail("plan_invalid", "the plan document is not a strict JSON object")
    if not isinstance(payload, dict):
        _fail("plan_invalid", "the plan document top-level value must be a JSON object")
    try:
        return EvaluationRunPlan.model_validate(payload)
    except PydanticValidationError:
        _fail("plan_invalid", "the plan document failed strict plan validation")
    raise AssertionError("unreachable")  # pragma: no cover


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m dynamic_ai_products.evaluation.runner",
        description="Governed single-case evaluation runner (Slice 13).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="execute one single-case evaluation")
    run_parser.add_argument("--plan", required=True, help="path to the JSON run plan")
    run_parser.add_argument("--eval-root", required=True, help="evaluation root directory")
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="execute only the pre-manifest boundary; write nothing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    try:
        plan = _load_plan_document(args.plan)
        if args.dry_run:
            _execute_pre_manifest(plan)
            payload = {
                "dry_run": True,
                "eval_run_id": plan.eval_run_id,
                "evaluation_stage": plan.evaluation_stage,
                "status": "pre_manifest_boundary_validated",
            }
            sys.stdout.write(canonical_contract_bytes(payload).decode("utf-8") + "\n")
            return 0
        summary = run_single_case_evaluation(plan, eval_root=args.eval_root)
    except _PreManifestEvaluationError as exc:
        for issue in exc.issues:
            sys.stderr.write(f"{issue.issue_code}: {issue.message}\n")
        return exc.exit_code
    sys.stdout.write(
        canonical_contract_bytes(summary.model_dump(mode="json", exclude_none=True)).decode(
            "utf-8"
        )
        + "\n"
    )
    return summary.exit_code


if __name__ == "__main__":  # pragma: no cover - exercised through the module CLI
    raise SystemExit(main())
