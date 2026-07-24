"""Validator-rule parameters (Slice 12F, SPEC-023 / ADR-024).

``validator_rule_parameters@0.1.0`` is the versioned, stage-specific policy for
the twelve SPEC-023 validator rules: exactly one entry per rule in
``VALIDATOR_RULE_ORDER``, each owning canonically ordered ``dependency_rule_ids``
and ``blocking_reason_codes`` and exactly four ``stage_parameters`` (one per
``EvaluationStage``) as a discriminated applicable/inapplicable union. The
complete per-rule hash binds the rule ID, dependencies, blocking reasons, and
all four stage entries while excluding its own field, and equals the bundle's
``ValidatorRuleConfig.rule_params_hash``; an aggregate parameter-set hash binds
the twelve entries in canonical order and equals the v0.2 run-manifest pin.

The ``universe_screen`` static-output contract ``universe_screen_output@0.1.0``
is a module-private ``ContractStampedModel`` whose canonical generated
model-contract hash is bound (fail-closed) by the applicable universe_screen
Rule 1 and Rule 2 payloads. It is never a public export, static schema, or
schema-manifest entry.

Read-side plus pure validation and explicit persistence only. Importing this
module performs no filesystem access, hashing, environment inspection, clock
read, UUID generation, network, provider, or model call. Three hash identities
are kept separate: the generated model-contract hash (over the model schema),
the canonical aggregate/per-entry content hashes (newline-free canonical bytes),
and the raw persisted-byte SHA-256 (canonical bytes plus one terminal newline).
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    Field,
    ValidationError as PydanticValidationError,
    model_validator,
)

from .contracts import canonical_contract_bytes, model_contract_hash
from .models import ContractStampedModel, EvaluationStrictModel, _require_non_blank
from .prediction_content import EvaluationStage
from .validators import VALIDATOR_RULE_ORDER, ValidatorRuleId
from ..universe.io_utils import sha256_bytes

__all__ = [
    "LoadedValidatorRuleParameters",
    "ValidatorRuleParameters",
    "ValidatorRuleParametersError",
    "complete_rule_parameter_hash",
    "load_validator_rule_parameters",
    "persist_validator_rule_parameters",
    "validator_rule_parameters_aggregate_hash",
]

_CONTRACT_ID = "validator_rule_parameters"
_CONTRACT_VERSION = "0.1.0"
_SNAPSHOTS_DIR = "snapshots"
_SNAPSHOT_FILENAME = "validator_rule_parameters.json"
_SHA256_HEX = {"min_length": 64, "max_length": 64, "pattern": r"^[0-9a-f]{64}$"}

_STAGE_ORDER: tuple[EvaluationStage, ...] = (
    "capability_extraction",
    "task_extraction",
    "universe_screen",
    "universe_classification",
)

_BlockingReasonCode = Literal[
    "blocked_output_schema_invalid",
    "blocked_passage_unresolved",
    "blocked_source_unresolved",
    "blocked_required_field_missing",
]
_InapplicableReasonCode = Literal[
    "stage_has_no_product_capability_task_hierarchy",
    "stage_has_no_active_deployment_record",
    "stage_emits_no_customer_facing_task",
]


# --- Public error ----------------------------------------------------------


class ValidatorRuleParametersError(Exception):
    """Sanitized validator-rule-parameters failure with a stable code."""

    def __init__(
        self, message: str, *, reason_code: str, artifact_reference: str | None = None
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.artifact_reference = artifact_reference


class _DuplicateKeyControl(Exception):
    def __init__(self) -> None:
        super().__init__("duplicate JSON object key")


class _NonFiniteControl(Exception):
    def __init__(self) -> None:
        super().__init__("non-JSON numeric constant")


# --- universe_screen_output@0.1.0 (module-private, generated-hash-bound) ---


class _UniverseScreenOutput(ContractStampedModel):
    # Docstring intentionally omitted so the generated JSON Schema (and thus the
    # governed model-contract hash) carries no description.
    _contract_id: ClassVar[str] = "universe_screen_output"
    _contract_version: ClassVar[str] = "0.1.0"

    prediction_record_id: str
    company_id: str
    in_universe: bool
    screen_status: Literal["likely_eligible", "likely_ineligible", "uncertain"]
    positive_evidence_ids: tuple[str, ...] = ()
    negative_evidence_ids: tuple[str, ...] = ()
    missing_evidence_fields: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _screen_invariants(self) -> "_UniverseScreenOutput":
        _require_non_blank(self.prediction_record_id, "prediction_record_id")
        _require_non_blank(self.company_id, "company_id")
        _require_sorted_unique_nonblank(self.positive_evidence_ids, "positive_evidence_ids")
        _require_sorted_unique_nonblank(self.negative_evidence_ids, "negative_evidence_ids")
        _require_sorted_unique_nonblank(self.missing_evidence_fields, "missing_evidence_fields")
        if set(self.positive_evidence_ids) & set(self.negative_evidence_ids):
            raise ValueError(
                "positive_evidence_ids and negative_evidence_ids must be disjoint"
            )
        return self


def _universe_screen_output_contract_hash() -> str:
    return model_contract_hash(_UniverseScreenOutput, "universe_screen_output", "0.1.0")


# --- Small pure helpers ----------------------------------------------------


def _require_sorted_unique_nonblank(values: tuple[str, ...], field_name: str) -> None:
    for value in values:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError(f"{field_name} entries must be non-blank strings")
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicates")
    if list(values) != sorted(values):
        raise ValueError(f"{field_name} must be in ascending order")


# --- Rule-specific typed payloads (module-private, discriminated) ----------


# Exact committed Rule-1 static-schema anchors (SPEC-023), bound to the stage
# each anchor governs. An applicable static-schema Rule 1 payload must bind the
# approved (id, reference, sha256) triple for its own stage; an otherwise
# approved triple assigned to the wrong stage is rejected even if the rule-entry
# hash is recomputed to be self-consistent. universe_screen has no static-schema
# payload (it binds the adapter output contract instead).
_STAGE_STATIC_ANCHORS: dict[str, tuple[str, str, str]] = {
    "capability_extraction": (
        "capability_observation",
        "schemas/capability_observation.schema.json",
        "4ade397f3383ff756a1aa2ba5f98bdb99f76c002d5cf049d7e8dcd7abf493733",
    ),
    "task_extraction": (
        "task_observation",
        "schemas/task_observation.schema.json",
        "b135ab828a3b710f1c63f6a8bf473caa6e29c3a63a5330cb203b470f772e3b03",
    ),
    "universe_classification": (
        "company_universe_classification",
        "schemas/company_universe_classification.schema.json",
        "1d47a80ee670f927e55d6af50550b1584aab022389471739a055a9e550552a22",
    ),
}
_APPROVED_STATIC_SCHEMAS: frozenset[tuple[str, str, str]] = frozenset(
    _STAGE_STATIC_ANCHORS.values()
)


class _Rule1StaticSchemaPayload(EvaluationStrictModel):
    payload_kind: Literal["rule1_static_schema"]
    output_schema_id: str
    output_schema_reference: str
    output_schema_sha256: str = Field(**_SHA256_HEX)

    @model_validator(mode="after")
    def _invariants(self) -> "_Rule1StaticSchemaPayload":
        _require_non_blank(self.output_schema_id, "output_schema_id")
        if not _is_safe_reference(self.output_schema_reference):
            raise ValueError("output_schema_reference must be a safe relative reference")
        triple = (self.output_schema_id, self.output_schema_reference, self.output_schema_sha256)
        if triple not in _APPROVED_STATIC_SCHEMAS:
            raise ValueError(
                "static-schema payload must bind an approved (id, reference, sha256) anchor"
            )
        return self


class _Rule1UniverseScreenPayload(EvaluationStrictModel):
    payload_kind: Literal["rule1_universe_screen"]
    output_contract_id: Literal["universe_screen_output"]
    output_contract_version: Literal["0.1.0"]
    output_contract_hash: str = Field(**_SHA256_HEX)

    @model_validator(mode="after")
    def _invariants(self) -> "_Rule1UniverseScreenPayload":
        if self.output_contract_hash != _universe_screen_output_contract_hash():
            raise ValueError(
                "output_contract_hash does not match the generated "
                "universe_screen_output@0.1.0 contract hash"
            )
        return self


class _Rule2RequiredFieldsPayload(EvaluationStrictModel):
    payload_kind: Literal["rule2_required_fields"]
    required_fields: tuple[str, ...]

    @model_validator(mode="after")
    def _invariants(self) -> "_Rule2RequiredFieldsPayload":
        if not self.required_fields:
            raise ValueError("required_fields must not be empty")
        _require_sorted_unique_nonblank(self.required_fields, "required_fields")
        return self


class _Rule2UniverseScreenPayload(EvaluationStrictModel):
    payload_kind: Literal["rule2_universe_screen"]
    output_contract_id: Literal["universe_screen_output"]
    output_contract_version: Literal["0.1.0"]
    output_contract_hash: str = Field(**_SHA256_HEX)
    required_fields: tuple[str, ...]

    @model_validator(mode="after")
    def _invariants(self) -> "_Rule2UniverseScreenPayload":
        if self.output_contract_hash != _universe_screen_output_contract_hash():
            raise ValueError(
                "output_contract_hash does not match the generated "
                "universe_screen_output@0.1.0 contract hash"
            )
        if not self.required_fields:
            raise ValueError("required_fields must not be empty")
        _require_sorted_unique_nonblank(self.required_fields, "required_fields")
        return self


class _Rule3SourceResolutionPayload(EvaluationStrictModel):
    payload_kind: Literal["rule3_source_resolution"]
    resolution_domain: Literal["source_id"]


class _Rule4PassageResolutionPayload(EvaluationStrictModel):
    payload_kind: Literal["rule4_passage_resolution"]
    resolution_domain: Literal["passage_id"]


class _Rule5QuoteContainmentPayload(EvaluationStrictModel):
    payload_kind: Literal["rule5_quote_containment"]
    match_mode: Literal["verbatim_substring"]


class _Rule6PublicationCutoffPayload(EvaluationStrictModel):
    payload_kind: Literal["rule6_publication_cutoff"]
    comparison: Literal["publication_le_cutoff"]


class _Rule7ParentResolutionPayload(EvaluationStrictModel):
    payload_kind: Literal["rule7_parent_resolution"]
    hierarchy: Literal["product_capability_task"]


class _Rule8UniqueIdsPayload(EvaluationStrictModel):
    payload_kind: Literal["rule8_unique_ids"]
    scope: Literal["declared_record_scope"]


class _Rule9ProhibitedLegacyPayload(EvaluationStrictModel):
    payload_kind: Literal["rule9_prohibited_legacy"]
    prohibited_field_names: tuple[str, ...]

    @model_validator(mode="after")
    def _invariants(self) -> "_Rule9ProhibitedLegacyPayload":
        if not self.prohibited_field_names:
            raise ValueError("prohibited_field_names must not be empty")
        _require_sorted_unique_nonblank(self.prohibited_field_names, "prohibited_field_names")
        return self


class _Rule10ActiveRoadmapPayload(EvaluationStrictModel):
    payload_kind: Literal["rule10_active_roadmap"]
    policy: Literal["active_requires_nonroadmap_evidence"]


class _Rule11CustomerTaskPayload(EvaluationStrictModel):
    payload_kind: Literal["rule11_customer_task"]
    policy: Literal["customer_task_requires_outcome_and_evidence"]


class _Rule12RawPreservationPayload(EvaluationStrictModel):
    payload_kind: Literal["rule12_raw_preservation"]
    policy: Literal["raw_output_and_repair_preserved"]


_RulePayload = Annotated[
    _Rule1StaticSchemaPayload
    | _Rule1UniverseScreenPayload
    | _Rule2RequiredFieldsPayload
    | _Rule2UniverseScreenPayload
    | _Rule3SourceResolutionPayload
    | _Rule4PassageResolutionPayload
    | _Rule5QuoteContainmentPayload
    | _Rule6PublicationCutoffPayload
    | _Rule7ParentResolutionPayload
    | _Rule8UniqueIdsPayload
    | _Rule9ProhibitedLegacyPayload
    | _Rule10ActiveRoadmapPayload
    | _Rule11CustomerTaskPayload
    | _Rule12RawPreservationPayload,
    Field(discriminator="payload_kind"),
]


# --- Stage-parameter discriminated union -----------------------------------


class _ApplicableStageParameter(EvaluationStrictModel):
    applicability: Literal["applicable"]
    stage: EvaluationStage
    payload: _RulePayload


class _InapplicableStageParameter(EvaluationStrictModel):
    applicability: Literal["inapplicable"]
    stage: EvaluationStage
    reason_code: _InapplicableReasonCode


_StageParameterEntry = Annotated[
    _ApplicableStageParameter | _InapplicableStageParameter,
    Field(discriminator="applicability"),
]


# --- Governed 12-rule x 4-stage matrix -------------------------------------
# For each rule: dependency_rule_ids, blocking_reason_codes, and per-stage a
# ("applicable", payload_kind) or ("inapplicable", reason_code) pair.

_RULE_SPEC: dict[str, dict[str, Any]] = {
    "output_json_schema_validity": {
        "deps": (),
        "blocking": (),
        "stages": {
            "capability_extraction": ("applicable", "rule1_static_schema"),
            "task_extraction": ("applicable", "rule1_static_schema"),
            "universe_screen": ("applicable", "rule1_universe_screen"),
            "universe_classification": ("applicable", "rule1_static_schema"),
        },
    },
    "required_field_presence": {
        "deps": ("output_json_schema_validity",),
        "blocking": ("blocked_output_schema_invalid",),
        "stages": {
            "capability_extraction": ("applicable", "rule2_required_fields"),
            "task_extraction": ("applicable", "rule2_required_fields"),
            "universe_screen": ("applicable", "rule2_universe_screen"),
            "universe_classification": ("applicable", "rule2_required_fields"),
        },
    },
    "source_id_resolution": {
        "deps": ("output_json_schema_validity",),
        "blocking": ("blocked_output_schema_invalid",),
        "stages": {s: ("applicable", "rule3_source_resolution") for s in _STAGE_ORDER},
    },
    "passage_id_resolution": {
        "deps": ("output_json_schema_validity",),
        "blocking": ("blocked_output_schema_invalid",),
        "stages": {s: ("applicable", "rule4_passage_resolution") for s in _STAGE_ORDER},
    },
    "evidence_quote_containment": {
        "deps": ("passage_id_resolution",),
        "blocking": ("blocked_passage_unresolved",),
        "stages": {s: ("applicable", "rule5_quote_containment") for s in _STAGE_ORDER},
    },
    "publication_date_cutoff": {
        "deps": ("source_id_resolution",),
        "blocking": ("blocked_source_unresolved",),
        "stages": {s: ("applicable", "rule6_publication_cutoff") for s in _STAGE_ORDER},
    },
    "product_capability_task_parent_resolution": {
        "deps": ("required_field_presence",),
        "blocking": ("blocked_required_field_missing",),
        "stages": {
            "capability_extraction": ("applicable", "rule7_parent_resolution"),
            "task_extraction": ("applicable", "rule7_parent_resolution"),
            "universe_screen": ("inapplicable", "stage_has_no_product_capability_task_hierarchy"),
            "universe_classification": (
                "inapplicable",
                "stage_has_no_product_capability_task_hierarchy",
            ),
        },
    },
    "unique_ids_within_scope": {
        "deps": ("output_json_schema_validity",),
        "blocking": ("blocked_output_schema_invalid",),
        "stages": {s: ("applicable", "rule8_unique_ids") for s in _STAGE_ORDER},
    },
    "prohibited_legacy_fields_absent": {
        "deps": ("output_json_schema_validity",),
        "blocking": ("blocked_output_schema_invalid",),
        "stages": {s: ("applicable", "rule9_prohibited_legacy") for s in _STAGE_ORDER},
    },
    "active_record_non_roadmap_evidence": {
        "deps": ("required_field_presence",),
        "blocking": ("blocked_required_field_missing",),
        "stages": {
            "capability_extraction": ("applicable", "rule10_active_roadmap"),
            "task_extraction": ("applicable", "rule10_active_roadmap"),
            "universe_screen": ("inapplicable", "stage_has_no_active_deployment_record"),
            "universe_classification": (
                "inapplicable",
                "stage_has_no_active_deployment_record",
            ),
        },
    },
    "customer_task_outcome_and_evidence": {
        "deps": ("required_field_presence",),
        "blocking": ("blocked_required_field_missing",),
        "stages": {
            "capability_extraction": ("applicable", "rule11_customer_task"),
            "task_extraction": ("applicable", "rule11_customer_task"),
            "universe_screen": ("inapplicable", "stage_emits_no_customer_facing_task"),
            "universe_classification": (
                "inapplicable",
                "stage_emits_no_customer_facing_task",
            ),
        },
    },
    "raw_output_and_repair_preservation": {
        "deps": (),
        "blocking": (),
        "stages": {s: ("applicable", "rule12_raw_preservation") for s in _STAGE_ORDER},
    },
}


# --- Entry + set contract --------------------------------------------------


class _ValidatorRuleParameterEntry(EvaluationStrictModel):
    rule_id: ValidatorRuleId
    dependency_rule_ids: tuple[ValidatorRuleId, ...]
    blocking_reason_codes: tuple[_BlockingReasonCode, ...]
    stage_parameters: tuple[_StageParameterEntry, ...]
    complete_rule_parameter_hash: str = Field(**_SHA256_HEX)

    @model_validator(mode="after")
    def _entry_invariants(self) -> "_ValidatorRuleParameterEntry":
        spec = _RULE_SPEC[self.rule_id]
        # Dependencies: exactly the governed set, canonical order, no self.
        if self.dependency_rule_ids != spec["deps"]:
            raise ValueError(
                f"dependency_rule_ids for {self.rule_id!r} must equal the governed set"
            )
        if self.rule_id in self.dependency_rule_ids:
            raise ValueError("a rule may not depend on itself")
        # Blocking reasons: exactly the governed set, canonical order.
        if self.blocking_reason_codes != spec["blocking"]:
            raise ValueError(
                f"blocking_reason_codes for {self.rule_id!r} must equal the governed set"
            )
        # Exactly four stage entries in canonical stage order.
        observed_stages = tuple(sp.stage for sp in self.stage_parameters)
        if observed_stages != _STAGE_ORDER:
            raise ValueError(
                "stage_parameters must cover the four stages in canonical order"
            )
        for sp in self.stage_parameters:
            expected_kind, expected_value = spec["stages"][sp.stage]
            if expected_kind == "applicable":
                if sp.applicability != "applicable":
                    raise ValueError(
                        f"{self.rule_id!r} at {sp.stage!r} must be applicable"
                    )
                if sp.payload.payload_kind != expected_value:
                    raise ValueError(
                        f"{self.rule_id!r} at {sp.stage!r} must carry payload "
                        f"{expected_value!r}"
                    )
                if sp.payload.payload_kind == "rule1_static_schema":
                    triple = (
                        sp.payload.output_schema_id,
                        sp.payload.output_schema_reference,
                        sp.payload.output_schema_sha256,
                    )
                    if triple != _STAGE_STATIC_ANCHORS.get(sp.stage):
                        raise ValueError(
                            f"static-schema anchor at {sp.stage!r} must equal the approved "
                            "stage-specific anchor"
                        )
            else:
                if sp.applicability != "inapplicable":
                    raise ValueError(
                        f"{self.rule_id!r} at {sp.stage!r} must be inapplicable"
                    )
                if sp.reason_code != expected_value:
                    raise ValueError(
                        f"{self.rule_id!r} inapplicable reason at {sp.stage!r} must be "
                        f"{expected_value!r}"
                    )
        # Complete per-rule hash binds everything except its own field.
        expected_hash = _complete_rule_parameter_hash_from_dump(self)
        if self.complete_rule_parameter_hash != expected_hash:
            raise ValueError(
                "complete_rule_parameter_hash does not match the canonical per-rule hash"
            )
        return self


def _complete_rule_parameter_hash_from_dump(entry: _ValidatorRuleParameterEntry) -> str:
    payload = entry.model_dump(mode="json", exclude={"complete_rule_parameter_hash"})
    return sha256_bytes(canonical_contract_bytes(payload))


def complete_rule_parameter_hash(entry: Any) -> str:
    """The canonical per-rule hash binding a rule entry, excluding its own field."""
    if not isinstance(entry, _ValidatorRuleParameterEntry):
        raise TypeError(
            f"complete_rule_parameter_hash requires a rule parameter entry, "
            f"got {type(entry).__name__}"
        )
    return _complete_rule_parameter_hash_from_dump(entry)


class ValidatorRuleParameters(ContractStampedModel):
    # Docstring intentionally omitted so the generated JSON Schema (and thus the
    # governed model-contract hash) carries no description.
    _contract_id: ClassVar[str] = _CONTRACT_ID
    _contract_version: ClassVar[str] = _CONTRACT_VERSION

    parameter_set_version: str
    entries: tuple[_ValidatorRuleParameterEntry, ...]

    @model_validator(mode="after")
    def _set_invariants(self) -> "ValidatorRuleParameters":
        _require_non_blank(self.parameter_set_version, "parameter_set_version")
        observed = tuple(entry.rule_id for entry in self.entries)
        if observed != VALIDATOR_RULE_ORDER:
            raise ValueError(
                "entries must be exactly the twelve rules in canonical order"
            )
        return self


class LoadedValidatorRuleParameters(EvaluationStrictModel):
    """A validated parameter set plus its raw-byte binding material."""

    model: ValidatorRuleParameters
    version: str
    sha256: str
    artifact_reference: str


# --- Aggregate hash + fail-closed revalidation ----------------------------


def _revalidate(model: ValidatorRuleParameters) -> ValidatorRuleParameters:
    if not isinstance(model, ValidatorRuleParameters):
        raise TypeError(f"expected a ValidatorRuleParameters, got {type(model).__name__}")
    try:
        payload = model.model_dump(mode="json", exclude_unset=True)
    except Exception as exc:  # noqa: BLE001 - any serialization defect fails closed
        raise ValidatorRuleParametersError(
            "validator rule parameters could not be serialized for revalidation",
            reason_code="model_validation",
        ) from exc
    try:
        return ValidatorRuleParameters.model_validate(payload)
    except PydanticValidationError as exc:
        raise ValidatorRuleParametersError(
            "validator rule parameters failed fail-closed revalidation",
            reason_code="model_validation",
        ) from exc


def validator_rule_parameters_aggregate_hash(model: ValidatorRuleParameters) -> str:
    """Canonical aggregate hash over the twelve ordered entries (the v0.2 pin)."""
    validated = _revalidate(model)
    payload = [entry.model_dump(mode="json") for entry in validated.entries]
    return sha256_bytes(canonical_contract_bytes(payload))


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
        raise ValidatorRuleParametersError(
            "eval_root must be an explicit str or Path evaluation root",
            reason_code="invalid_eval_root",
        )
    if isinstance(eval_root, str) and eval_root == "":
        raise ValidatorRuleParametersError(
            "eval_root must not be an empty string; supply the evaluation root explicitly",
            reason_code="invalid_eval_root",
        )
    root = Path(eval_root)
    if root.is_symlink():
        raise ValidatorRuleParametersError(
            "eval_root must not be a symlink", reason_code="eval_root_symlink"
        )
    if not root.exists():
        raise ValidatorRuleParametersError(
            "evaluation root does not exist", reason_code="invalid_eval_root"
        )
    if not root.is_dir():
        raise ValidatorRuleParametersError(
            "evaluation root is not a directory", reason_code="invalid_eval_root"
        )
    return root.resolve()


def _resolve_contained(reference: str | Path, resolved_root: Path) -> tuple[Path, str]:
    if not _is_safe_reference(reference if isinstance(reference, str) else str(reference)):
        if not isinstance(reference, (str, Path)):
            raise ValidatorRuleParametersError(
                "reference must be an explicit str or Path", reason_code="invalid_path"
            )
        raise ValidatorRuleParametersError(
            "reference is not a safe relative reference", reason_code="unsafe_reference"
        )
    candidate = resolved_root / Path(reference)
    if candidate.is_symlink():
        raise ValidatorRuleParametersError(
            "artifact path is a symlink", reason_code="artifact_symlink"
        )
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValidatorRuleParametersError(
            "artifact path resolves outside the evaluation root", reason_code="path_escape"
        )
    ref = resolved.relative_to(resolved_root).as_posix()
    if resolved.is_symlink():
        raise ValidatorRuleParametersError(
            "artifact is a symlink", reason_code="artifact_symlink", artifact_reference=ref
        )
    if not resolved.exists():
        raise ValidatorRuleParametersError(
            "artifact does not exist under the evaluation root",
            reason_code="artifact_missing",
            artifact_reference=ref,
        )
    if not resolved.is_file():
        raise ValidatorRuleParametersError(
            "artifact is not a regular file",
            reason_code="artifact_not_a_file",
            artifact_reference=ref,
        )
    return resolved, ref


def _validate_run_id(eval_run_id: Any) -> str:
    if not isinstance(eval_run_id, str):
        raise ValidatorRuleParametersError(
            f"eval_run_id must be a string, got {type(eval_run_id).__name__}",
            reason_code="invalid_eval_run_id",
        )
    if not eval_run_id or eval_run_id != eval_run_id.strip():
        raise ValidatorRuleParametersError(
            "eval_run_id must be a non-empty string without leading or trailing whitespace",
            reason_code="invalid_eval_run_id",
        )
    if eval_run_id in (".", ".."):
        raise ValidatorRuleParametersError(
            "eval_run_id is not a valid path component", reason_code="invalid_eval_run_id"
        )
    if "/" in eval_run_id or "\\" in eval_run_id or "\x00" in eval_run_id:
        raise ValidatorRuleParametersError(
            "eval_run_id must be a single path component without separators or NUL",
            reason_code="invalid_eval_run_id",
        )
    if Path(eval_run_id).is_absolute() or len(Path(eval_run_id).parts) != 1:
        raise ValidatorRuleParametersError(
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
        raise ValidatorRuleParametersError(
            "artifact is not valid JSON", reason_code="json_error", artifact_reference=reference
        ) from exc
    except _DuplicateKeyControl as exc:
        raise ValidatorRuleParametersError(
            "artifact contains a duplicate JSON object key",
            reason_code="duplicate_key",
            artifact_reference=reference,
        ) from exc
    except _NonFiniteControl as exc:
        raise ValidatorRuleParametersError(
            "artifact contains a non-JSON numeric constant",
            reason_code="non_finite",
            artifact_reference=reference,
        ) from exc
    if _has_non_finite(payload):
        raise ValidatorRuleParametersError(
            "artifact contains a non-finite JSON number",
            reason_code="non_finite",
            artifact_reference=reference,
        )
    if not isinstance(payload, dict):
        raise ValidatorRuleParametersError(
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
        raise ValidatorRuleParametersError(
            "failed to read the artifact", reason_code="read_error", artifact_reference=ref
        ) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidatorRuleParametersError(
            "artifact is not valid UTF-8", reason_code="decode_error", artifact_reference=ref
        ) from exc
    return raw, text, ref


# --- Loader ---------------------------------------------------------------


def load_validator_rule_parameters(
    path: str | Path,
    *,
    eval_root: str | Path,
    expected_sha256: str | None = None,
) -> LoadedValidatorRuleParameters:
    """Load, hash-bind, and strictly validate a validator-rule-parameters set."""
    resolved_root = _validate_eval_root(eval_root)
    raw, text, reference = _read_contained(str(path), resolved_root)
    observed = sha256_bytes(raw)
    if expected_sha256 is not None:
        valid = (
            isinstance(expected_sha256, str)
            and len(expected_sha256) == 64
            and all(c in "0123456789abcdef" for c in expected_sha256)
        )
        if not valid or expected_sha256 != observed:
            raise ValidatorRuleParametersError(
                "validator rule parameters raw-byte hash does not match the expected hash",
                reason_code="expected_hash_mismatch",
                artifact_reference=reference,
            )
    payload = _strict_json_object(text, reference)
    try:
        model = ValidatorRuleParameters.model_validate(payload)
    except PydanticValidationError as exc:
        raise ValidatorRuleParametersError(
            "validator rule parameters failed strict contract validation",
            reason_code="model_validation",
            artifact_reference=reference,
        ) from exc
    return LoadedValidatorRuleParameters(
        model=model,
        version=model.parameter_set_version,
        sha256=observed,
        artifact_reference=reference,
    )


# --- Snapshot persistence -------------------------------------------------


def persist_validator_rule_parameters(
    model: ValidatorRuleParameters,
    *,
    eval_root: str | Path,
    eval_run_id: str,
) -> LoadedValidatorRuleParameters:
    """Write the canonical parameters JSON (plus one terminal newline) write-once."""
    validated = _revalidate(model)
    resolved_root = _validate_eval_root(eval_root)
    run_id = _validate_run_id(eval_run_id)
    run_dir = resolved_root / run_id
    if run_dir.is_symlink():
        raise ValidatorRuleParametersError(
            "run directory is a symlink", reason_code="run_directory_symlink"
        )
    if not run_dir.exists():
        raise ValidatorRuleParametersError(
            "run directory does not exist under the evaluation root",
            reason_code="run_directory_missing",
            artifact_reference=run_id,
        )
    if not run_dir.is_dir():
        raise ValidatorRuleParametersError(
            "run directory is not a directory",
            reason_code="run_directory_not_a_directory",
            artifact_reference=run_id,
        )
    snapshots_dir = run_dir / _SNAPSHOTS_DIR
    if snapshots_dir.is_symlink():
        raise ValidatorRuleParametersError(
            "run snapshots directory is a symlink",
            reason_code="snapshots_directory_symlink",
        )
    if snapshots_dir.exists():
        if not snapshots_dir.is_dir():
            raise ValidatorRuleParametersError(
                "run snapshots path is not a directory",
                reason_code="snapshots_directory_not_a_directory",
            )
    else:
        try:
            snapshots_dir.mkdir(exist_ok=False)
        except OSError as exc:
            raise ValidatorRuleParametersError(
                "failed to create the run snapshots directory",
                reason_code="write_error",
                artifact_reference=f"{run_id}/{_SNAPSHOTS_DIR}",
            ) from exc
    reference = f"{run_id}/{_SNAPSHOTS_DIR}/{_SNAPSHOT_FILENAME}"
    dest = snapshots_dir / _SNAPSHOT_FILENAME
    if dest.is_symlink() or dest.exists():
        raise ValidatorRuleParametersError(
            "snapshot already exists; snapshots are write-once",
            reason_code="snapshot_exists",
            artifact_reference=reference,
        )
    data = canonical_contract_bytes(validated.model_dump(mode="json", exclude_unset=True)) + b"\n"
    expected = sha256_bytes(data)
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise ValidatorRuleParametersError(
            "snapshot already exists; snapshots are write-once",
            reason_code="snapshot_exists",
            artifact_reference=reference,
        ) from exc
    except OSError as exc:
        raise ValidatorRuleParametersError(
            "failed to create the snapshot", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ValidatorRuleParametersError(
            "failed to write the snapshot", reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    try:
        observed = sha256_bytes(dest.read_bytes())
    except OSError as exc:
        raise ValidatorRuleParametersError(
            "failed to re-read the snapshot for verification",
            reason_code="write_error",
            artifact_reference=reference,
        ) from exc
    if observed != expected:
        raise ValidatorRuleParametersError(
            "persisted snapshot re-read to a different hash",
            reason_code="destination_hash_mismatch",
            artifact_reference=reference,
        )
    return LoadedValidatorRuleParameters(
        model=validated,
        version=validated.parameter_set_version,
        sha256=observed,
        artifact_reference=reference,
    )
