"""Deterministic Rules 1-11 validator inputs for the extraction stages (P2).

``build_extraction_validation_inputs`` is a pure public producer. Given a case, a
loaded parsed-prediction content, the raw artifact bytes, the output-schema bytes,
a governed source snapshot, ``validator_rule_parameters@0.2.0``, its reconciled
bundle artifact, a v0.2 run manifest, the observation-target binding, and the
parent-observation snapshot, it returns the Rules 1-11 ``ValidatorObservation``
values and their ``ValidatorRuleCoverage`` records. It has no persisted artifact
of its own: the output is embedded in the persisted ``ValidationArtifactSnapshot``
through ``build_validation_artifact_snapshot``, which remains the sole producer of
Rule 12 (ADR-027).

The module never touches the filesystem, never calls a clock, resolver, provider,
or model, and derives nothing from wording. Two identity boundaries are kept
distinct: the **raw document** is the authority for Rules 1, 2, 7, 9, and 10's
record status, while the **parsed content** is the authority for cited sources,
passages, evidence, and declared entities. ``parsed_prediction_content``'s own
artifact hash is provenance only and never substitutes for the raw-byte binding.

Failures split in two, matching ``build_validation_artifact_snapshot``: a
``TypeError`` for a wrong argument type or an unsupported governed version, and a
``ValueError`` for a content or coherence violation. Neither is recoverable by
degrading a rule; a prediction defect is reported through the rule that owns it.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Literal

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from .contracts import canonical_contract_bytes
from .models import EvaluationCase, EvaluationRunManifestV2, EvaluationStrictModel
from .observation_target_binding import LoadedObservationTargetBinding
from .parent_observation_snapshot import (
    LoadedParentObservationSnapshot,
    verify_child_case_context,
)
from .prediction_content import LoadedParsedPredictionContent
from .resolution_decisions import EXTRACTION_EVALUATION_STAGES
from .source_snapshot import (
    LoadedSourcePassageSnapshotManifest,
    resolve_case_source_passages,
    source_passage_snapshot_manifest_hash,
)
from .validator_bundle_artifact import LoadedValidatorBundleArtifact
from .validator_parameters import (
    LoadedValidatorRuleParameters,
    ValidatorRuleParametersV2,
    complete_rule_parameter_hash,
    validator_rule_parameters_aggregate_hash,
)
from .validators import (
    VALIDATOR_RULE_ORDER,
    ValidatorObservation,
    ValidatorRuleCoverage,
)
from ..universe.io_utils import sha256_bytes

__all__ = [
    "ExtractionEvaluationStage",
    "ExtractionValidationInputs",
    "build_extraction_validation_inputs",
]

ExtractionEvaluationStage = Literal["capability_extraction", "task_extraction"]

_RULE_12 = "raw_output_and_repair_preservation"
_RULES_1_TO_11: tuple[str, ...] = tuple(r for r in VALIDATOR_RULE_ORDER if r != _RULE_12)
_RULE_POSITION: dict[str, int] = {r: i for i, r in enumerate(VALIDATOR_RULE_ORDER)}

# Local mirrors of the governed stage/role maps. Mirrored rather than imported so
# the dependency runs one way (this module consumes the binding; the binding knows
# nothing about validator inputs). Equality with the binding module's governed maps
# is asserted by test, so a drift cannot pass silently.
_STAGE_SUBJECT_KIND: dict[str, str] = {
    "capability_extraction": "capability",
    "task_extraction": "task",
}
_PARENT_ROLE_SNAPSHOT_FIELD: dict[str, str] = {
    "product": "product_parent_ids",
    "capability": "capability_parent_ids",
}
# Raw parent-link fields per stage: the child-id field, then the ordered
# (role, field, is_list) parent links the schema requires.
_STAGE_CHILD_ID_FIELD: dict[str, str] = {
    "capability_extraction": "capability_observation_id",
    "task_extraction": "task_observation_id",
}
_STAGE_PARENT_LINKS: dict[str, tuple[tuple[str, str, bool], ...]] = {
    "capability_extraction": (("product", "product_observation_id", False),),
    "task_extraction": (
        ("product", "product_observation_id", False),
        ("capability", "capability_observation_ids", True),
    ),
}

_BLOCKED_SCHEMA_INVALID = "blocked_output_schema_invalid"
_BLOCKED_PASSAGE_UNRESOLVED = "blocked_passage_unresolved"
_BLOCKED_SOURCE_UNRESOLVED = "blocked_source_unresolved"
_BLOCKED_REQUIRED_FIELD_MISSING = "blocked_required_field_missing"


# --- Output ----------------------------------------------------------------


class ExtractionValidationInputs(EvaluationStrictModel):
    """Rules 1-11 observations and coverage for one extraction artifact.

    Not a contract-stamped artifact: it is never persisted on its own, so it owns
    no governed model hash. The provenance fields record exactly the bindings the
    producer verified, so a caller can re-check them without re-deriving.
    """

    case_id: str
    evaluation_stage: ExtractionEvaluationStage
    prediction_record_id: str
    raw_artifact_sha256: str
    parsed_prediction_content_sha256: str
    output_schema_sha256: str
    output_schema_reference: str
    parameter_set_version: str
    parameter_set_aggregate_hash: str
    bundle_version: str
    bundle_hash: str
    observations: tuple[ValidatorObservation, ...]
    coverage: tuple[ValidatorRuleCoverage, ...]


# --- Coverage helpers ------------------------------------------------------


def _coverage(
    rule_id: str, *, candidate: int, evaluated: int, blocked: int, reason_code: str | None
) -> ValidatorRuleCoverage:
    """Build the one coverage record the four governed states allow.

    There is no representable "applicable with zero candidates" state, so a rule
    that reaches this helper always has at least one candidate.
    """
    if candidate < 1:
        raise ValueError(f"rule {rule_id!r} must have at least one candidate")
    if evaluated and blocked:
        state = "partially_evaluated"
    elif blocked:
        state = "blocked_by_dependency"
    else:
        state = "fully_evaluated"
    reasons: tuple[dict[str, Any], ...] = ()
    if blocked:
        if reason_code is None:
            raise ValueError(f"rule {rule_id!r} blocked without a governed reason code")
        reasons = ({"reason_code": reason_code, "count": blocked},)
    return ValidatorRuleCoverage.model_validate(
        {
            "rule_id": rule_id,
            "coverage_state": state,
            "candidate_count": candidate,
            "evaluated_observation_count": evaluated,
            "blocked_candidate_count": blocked,
            "reason_counts": list(reasons),
        }
    )


def _inapplicable_coverage(rule_id: str, reason_code: str) -> ValidatorRuleCoverage:
    return ValidatorRuleCoverage.model_validate(
        {
            "rule_id": rule_id,
            "coverage_state": "inapplicable",
            "candidate_count": 0,
            "evaluated_observation_count": 0,
            "blocked_candidate_count": 0,
            "reason_counts": [{"reason_code": reason_code, "count": 1}],
        }
    )


def _observation_id(rule_id: str, granularity_key: str) -> str:
    """Globally unique within a snapshot: the rule ordinal separates rules."""
    return f"{_RULE_POSITION[rule_id]:02d}-{rule_id}-{granularity_key}"


def _evidence_id(evidence: Any) -> str:
    """Canonical Rule-5/Rule-10 evidence identity.

    ``ParsedEvidenceCollection`` already enforces sorted, unique
    ``(entity_ref, source_id, passage_id, quote)`` identities, so the digest alone
    is collision-safe: no occurrence ordinal is needed or permitted.
    """
    return sha256_bytes(
        canonical_contract_bytes(
            [evidence.entity_ref, evidence.source_id, evidence.passage_id, evidence.quote]
        )
    )


# --- Argument and binding validation --------------------------------------


def _require_type(value: Any, expected: type, name: str) -> Any:
    if not isinstance(value, expected):
        raise TypeError(f"{name} must be a {expected.__name__}, got {type(value).__name__}")
    return value


def _selected_stage_entries(
    parameters: ValidatorRuleParametersV2, stage: str
) -> dict[str, Any]:
    """The stage parameter selected for each of the twelve rules."""
    selected: dict[str, Any] = {}
    for entry in parameters.entries:
        matches = [sp for sp in entry.stage_parameters if sp.stage == stage]
        if len(matches) != 1:
            raise ValueError(
                f"rule {entry.rule_id!r} does not select exactly one parameter at {stage!r}"
            )
        selected[entry.rule_id] = matches[0]
    return selected


def _reconcile_bundle(
    bundle: LoadedValidatorBundleArtifact, parameters: LoadedValidatorRuleParameters
) -> str:
    """Re-verify the bundle/parameter pair and return the aggregate hash."""
    aggregate = validator_rule_parameters_aggregate_hash(parameters.model)
    if bundle.model.parameter_set_version != parameters.model.parameter_set_version:
        raise ValueError(
            "validator bundle artifact parameter_set_version does not equal the "
            "loaded parameter set version"
        )
    if bundle.model.parameter_set_aggregate_hash != aggregate:
        raise ValueError(
            "validator bundle artifact parameter_set_aggregate_hash does not equal "
            "the loaded parameter aggregate hash"
        )
    entries_by_rule = {entry.rule_id: entry for entry in parameters.model.entries}
    for rule_entry in bundle.model.rule_entries:
        expected = complete_rule_parameter_hash(entries_by_rule[rule_entry.rule_id])
        if rule_entry.rule_params_hash != expected:
            raise ValueError(
                f"bundle rule_params_hash for {rule_entry.rule_id!r} does not equal the "
                "canonical per-rule parameter hash"
            )
    return aggregate


def _reconcile_run_manifest(
    run_manifest: EvaluationRunManifestV2,
    parameters: LoadedValidatorRuleParameters,
    bundle: LoadedValidatorBundleArtifact,
    aggregate: str,
) -> None:
    if run_manifest.validator_rule_parameters_version != parameters.model.parameter_set_version:
        raise ValueError(
            "run manifest validator_rule_parameters_version does not equal the loaded "
            "parameter set version"
        )
    if run_manifest.validator_rule_parameters_hash != aggregate:
        raise ValueError(
            "run manifest validator_rule_parameters_hash does not equal the loaded "
            "parameter aggregate hash"
        )
    if run_manifest.validator_bundle_version != bundle.model.bundle_version:
        raise ValueError(
            "run manifest validator_bundle_version does not equal the loaded bundle version"
        )
    if run_manifest.validator_bundle_hash != bundle.model.bundle_hash:
        raise ValueError(
            "run manifest validator_bundle_hash does not equal the loaded bundle hash"
        )


def _binding_subject(binding: LoadedObservationTargetBinding, stage: str) -> Any:
    subjects = [e for e in binding.model.entries if not e.parent_referenced]
    if len(subjects) != 1:
        raise ValueError("the binding must carry exactly one owning subject entry")
    subject = subjects[0]
    if subject.observation_kind != _STAGE_SUBJECT_KIND[stage]:
        raise ValueError("the binding subject kind does not match the stage subject kind")
    return subject


def _schema_validator(output_schema_bytes: bytes) -> Draft202012Validator:
    try:
        schema = json.loads(output_schema_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("output_schema_bytes is not a decodable JSON document") from exc
    if not isinstance(schema, dict):
        raise ValueError("output_schema_bytes must decode to a JSON object schema")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError("output_schema_bytes is not a valid Draft 2020-12 schema") from exc
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _available_parent_ids(
    required_roles: set[str], snapshot_roles: dict[str, frozenset[str]]
) -> tuple[str, ...]:
    """The all-roles-required intersection of the snapshot's role member sets.

    All required roles, not any. A parent literal that appears in both the product
    and capability raw links collapses to one ``(child_id, parent_id)`` candidate,
    and it is available only when the same literal is present in *both* snapshot
    role sets. A role-blind union would let such a candidate pass on one role while
    the other required parent link is genuinely unresolved, hiding a real defect.
    """
    if not required_roles:
        raise ValueError("a Rule-7 candidate must carry at least one required role")
    allowed: set[str] | None = None
    for role in sorted(required_roles):
        members = snapshot_roles[role]
        allowed = set(members) if allowed is None else allowed & members
    return tuple(sorted(allowed or ()))


def _json_pointer(parts: Any) -> str:
    tokens = []
    for part in parts:
        if isinstance(part, int):
            tokens.append(str(part))
        else:
            tokens.append(str(part).replace("~", "~0").replace("/", "~1"))
    return "".join("/" + token for token in tokens)


# --- Public producer -------------------------------------------------------


def build_extraction_validation_inputs(
    *,
    case: EvaluationCase,
    evaluation_stage: ExtractionEvaluationStage,
    parsed_prediction_content: LoadedParsedPredictionContent,
    raw_artifact_bytes: bytes,
    output_schema_bytes: bytes,
    source_snapshot: LoadedSourcePassageSnapshotManifest,
    rule_parameters: LoadedValidatorRuleParameters,
    validator_bundle_artifact: LoadedValidatorBundleArtifact,
    run_manifest: EvaluationRunManifestV2,
    observation_target_binding: LoadedObservationTargetBinding,
    parent_snapshot: LoadedParentObservationSnapshot | None,
) -> ExtractionValidationInputs:
    """Produce the Rules 1-11 validator observations and coverage for one artifact.

    Rule 12 is not produced here: ``build_validation_artifact_snapshot`` derives it
    from the loaded parsed content and rejects a caller-supplied Rule-12 record.
    """
    # --- 1. Types and governed versions -----------------------------------
    _require_type(case, EvaluationCase, "case")
    _require_type(
        parsed_prediction_content, LoadedParsedPredictionContent, "parsed_prediction_content"
    )
    _require_type(source_snapshot, LoadedSourcePassageSnapshotManifest, "source_snapshot")
    _require_type(rule_parameters, LoadedValidatorRuleParameters, "rule_parameters")
    _require_type(
        validator_bundle_artifact, LoadedValidatorBundleArtifact, "validator_bundle_artifact"
    )
    _require_type(run_manifest, EvaluationRunManifestV2, "run_manifest")
    _require_type(
        observation_target_binding, LoadedObservationTargetBinding, "observation_target_binding"
    )
    if not isinstance(raw_artifact_bytes, bytes):
        raise TypeError(
            f"raw_artifact_bytes must be bytes, got {type(raw_artifact_bytes).__name__}"
        )
    if not isinstance(output_schema_bytes, bytes):
        raise TypeError(
            f"output_schema_bytes must be bytes, got {type(output_schema_bytes).__name__}"
        )
    if evaluation_stage not in EXTRACTION_EVALUATION_STAGES:
        raise ValueError(
            "evaluation_stage must be a governed extraction evaluation stage"
        )
    if not isinstance(rule_parameters.model, ValidatorRuleParametersV2):
        raise TypeError(
            "rule_parameters must carry validator_rule_parameters@0.2.0; got "
            f"{type(rule_parameters.model).__name__} (parameters_version_unsupported)"
        )
    # The parent snapshot verifies the raw parent IDs, and both extraction schemas
    # require parent-link fields, so it is mandatory at both extraction stages.
    if parent_snapshot is None:
        raise ValueError(
            "parent_snapshot is required at an extraction stage: both extraction "
            "schemas require parent-link fields that must be verified"
        )
    _require_type(parent_snapshot, LoadedParentObservationSnapshot, "parent_snapshot")

    # --- 2. Bundle, run-manifest, and raw/parsed bindings -----------------
    aggregate = _reconcile_bundle(validator_bundle_artifact, rule_parameters)
    _reconcile_run_manifest(run_manifest, rule_parameters, validator_bundle_artifact, aggregate)

    content = parsed_prediction_content.content
    if sha256_bytes(raw_artifact_bytes) != content.raw_artifact_sha256:
        raise ValueError(
            "raw_artifact_bytes do not hash to the parsed content's raw_artifact_sha256"
        )
    if content.stage != evaluation_stage:
        raise ValueError("parsed content stage does not equal the requested evaluation stage")
    if content.case_id != case.case_id:
        raise ValueError("parsed content case_id does not equal the supplied case")
    if case.stage != evaluation_stage:
        raise ValueError("case stage does not equal the requested evaluation stage")

    # The source snapshot must be the exact one the run pinned. Successful
    # case-source resolution is not a substitute: a different snapshot can carry the
    # same source and passage IDs with different publication dates or passage text,
    # which would silently change Rule 5, Rule 6, and Rule 10 outcomes.
    if source_snapshot.version != run_manifest.source_passage_snapshot_version:
        raise ValueError(
            "source snapshot version does not equal the run manifest's "
            "source_passage_snapshot_version"
        )
    # The run manifest pins the snapshot's canonical *content* hash (identity 2),
    # not the loaded wrapper's raw persisted-byte SHA-256 (identity 3), so the
    # comparison must be made against the same identity the run recorded.
    if (
        source_passage_snapshot_manifest_hash(source_snapshot.manifest)
        != run_manifest.source_passage_snapshot_hash
    ):
        raise ValueError(
            "source snapshot content hash does not equal the run manifest's "
            "source_passage_snapshot_hash"
        )

    binding_model = observation_target_binding.model
    # A binding persisted for a different evaluation run must be rejected even when
    # its case, parsed-content hash, and every parameter and bundle pin match.
    if binding_model.eval_run_id != run_manifest.eval_run_id:
        raise ValueError("binding eval_run_id does not equal the run manifest's eval_run_id")
    if binding_model.stage != evaluation_stage:
        raise ValueError("binding stage does not equal the requested evaluation stage")
    if binding_model.case_id != case.case_id:
        raise ValueError("binding case_id does not equal the supplied case")
    if binding_model.raw_artifact_sha256 != content.raw_artifact_sha256:
        raise ValueError("binding raw_artifact_sha256 does not equal the parsed content's")
    if binding_model.parsed_prediction_content_sha256 != parsed_prediction_content.sha256:
        raise ValueError(
            "binding parsed_prediction_content_sha256 does not equal the loaded content hash"
        )
    if binding_model.prediction_record_id != content.prediction_record_id:
        raise ValueError("binding prediction_record_id does not equal the parsed content's")
    subject = _binding_subject(observation_target_binding, evaluation_stage)

    # The parent snapshot must be the exact one the binding was reconciled against,
    # and its validated case context must equal this child's, so Rule 7's role sets
    # and Rule 10's cutoff comparison cannot be verified against a foreign parent
    # population.
    if parent_snapshot.version != binding_model.parent_observation_snapshot_version:
        raise ValueError(
            "parent snapshot version does not equal the binding's "
            "parent_observation_snapshot_version"
        )
    if parent_snapshot.sha256 != binding_model.parent_observation_snapshot_sha256:
        raise ValueError(
            "parent snapshot sha256 does not equal the binding's "
            "parent_observation_snapshot_sha256"
        )
    verify_child_case_context(
        parent_snapshot,
        case_id=case.case_id,
        company_id=binding_model.company_id,
        observation_cutoff=content.observation_cutoff,
    )

    # --- 3. Selected stage parameters and the Rule-1 schema anchor --------
    selected = _selected_stage_entries(rule_parameters.model, evaluation_stage)
    rule1 = selected["output_json_schema_validity"]
    if rule1.applicability != "applicable" or rule1.payload.payload_kind != "rule1_static_schema":
        raise ValueError(
            "Rule 1 must select an applicable static-schema payload at an extraction stage"
        )
    # The expected schema digest comes only from the selected V2 parameter payload;
    # the module never consults a parallel anchor table.
    expected_schema_sha256 = rule1.payload.output_schema_sha256
    if sha256_bytes(output_schema_bytes) != expected_schema_sha256:
        raise ValueError(
            "output_schema_bytes do not hash to the selected Rule-1 payload's "
            "output_schema_sha256"
        )
    validator = _schema_validator(output_schema_bytes)

    # --- 4. Case-scoped source resolution ---------------------------------
    resolved = resolve_case_source_passages(source_snapshot, case)
    documents_by_id = {d.source_id: d for d in resolved.documents}
    passages_by_id = {p.passage_id: p for p in resolved.passages}
    available_source_ids = tuple(sorted(documents_by_id))
    available_passage_ids = tuple(sorted(passages_by_id))
    cutoff = date.fromisoformat(content.observation_cutoff)

    # --- 5. Raw document -------------------------------------------------
    parse_succeeded = True
    raw_object: dict[str, Any] | None = None
    validation_errors: list[str] = []
    try:
        decoded = json.loads(raw_artifact_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        parse_succeeded = False
        validation_errors.append(f": raw artifact is not decodable JSON ({type(exc).__name__})")
    else:
        if isinstance(decoded, dict):
            raw_object = decoded
        else:
            validation_errors.append(": raw artifact does not decode to a JSON object")
        for error in validator.iter_errors(decoded):
            validation_errors.append(f"{_json_pointer(error.absolute_path)}: {error.message}")
    schema_valid = parse_succeeded and raw_object is not None and not validation_errors
    validation_errors.sort()

    # A raw child-id mismatch is a fail-closed input defect, not a rule finding.
    # It is only checkable when the raw document actually carries the field; a
    # missing field is exactly what Rules 2 and 7 report.
    child_field = _STAGE_CHILD_ID_FIELD[evaluation_stage]
    raw_child_id = raw_object.get(child_field) if raw_object is not None else None
    if isinstance(raw_child_id, str) and raw_child_id != subject.observation_id:
        raise ValueError(
            "the binding subject observation_id does not equal the raw child observation id"
        )

    observations: list[dict[str, Any]] = []
    coverage: list[ValidatorRuleCoverage] = []

    # --- Rule 1: output JSON/schema validity (raw document) ---------------
    observations.append(
        {
            "rule_id": "output_json_schema_validity",
            "observation_id": _observation_id(
                "output_json_schema_validity", content.raw_artifact_sha256
            ),
            "parse_succeeded": parse_succeeded,
            "schema_valid": schema_valid,
            "schema_reference": rule1.payload.output_schema_reference,
            "validation_errors": tuple(validation_errors),
        }
    )
    coverage.append(
        _coverage(
            "output_json_schema_validity",
            candidate=1,
            evaluated=1,
            blocked=0,
            reason_code=None,
        )
    )

    def blocked_only(rule_id: str, reason_code: str) -> None:
        coverage.append(
            _coverage(rule_id, candidate=1, evaluated=0, blocked=1, reason_code=reason_code)
        )

    # --- Rule 2: required-field presence (raw document) -------------------
    rule2 = selected["required_field_presence"]
    required_fields = tuple(rule2.payload.required_fields)
    if not schema_valid:
        blocked_only("required_field_presence", _BLOCKED_SCHEMA_INVALID)
        rule2_satisfied = False
    else:
        present = tuple(sorted(name for name in required_fields if name in raw_object))
        observations.append(
            {
                "rule_id": "required_field_presence",
                "observation_id": _observation_id(
                    "required_field_presence", content.raw_artifact_sha256
                ),
                "required_fields": required_fields,
                "present_fields": present,
            }
        )
        coverage.append(
            _coverage(
                "required_field_presence", candidate=1, evaluated=1, blocked=0, reason_code=None
            )
        )
        rule2_satisfied = set(required_fields) <= set(present)

    # --- Rule 3: source-id resolution (distinct cited source) -------------
    evidence_entries = content.evidence_collection.evidence
    cited_source_ids = tuple(sorted({e.source_id for e in evidence_entries}))
    cited_passage_ids = tuple(sorted({e.passage_id for e in evidence_entries}))
    if not schema_valid:
        blocked_only("source_id_resolution", _BLOCKED_SCHEMA_INVALID)
    else:
        for source_id in cited_source_ids:
            observations.append(
                {
                    "rule_id": "source_id_resolution",
                    "observation_id": _observation_id("source_id_resolution", source_id),
                    "referenced_source_ids": (source_id,),
                    "available_source_ids": available_source_ids,
                }
            )
        coverage.append(
            _coverage(
                "source_id_resolution",
                candidate=len(cited_source_ids),
                evaluated=len(cited_source_ids),
                blocked=0,
                reason_code=None,
            )
        )

    # --- Rule 4: passage-id resolution (distinct cited passage) -----------
    if not schema_valid:
        blocked_only("passage_id_resolution", _BLOCKED_SCHEMA_INVALID)
    else:
        for passage_id in cited_passage_ids:
            observations.append(
                {
                    "rule_id": "passage_id_resolution",
                    "observation_id": _observation_id("passage_id_resolution", passage_id),
                    "referenced_passage_ids": (passage_id,),
                    "available_passage_ids": available_passage_ids,
                }
            )
        coverage.append(
            _coverage(
                "passage_id_resolution",
                candidate=len(cited_passage_ids),
                evaluated=len(cited_passage_ids),
                blocked=0,
                reason_code=None,
            )
        )

    # --- Rule 5: evidence quote containment (evidence entry) --------------
    if not schema_valid:
        blocked_only("evidence_quote_containment", _BLOCKED_SCHEMA_INVALID)
    else:
        evaluated = blocked = 0
        for evidence in evidence_entries:
            passage = passages_by_id.get(evidence.passage_id)
            if passage is None:
                blocked += 1
                continue
            evaluated += 1
            observations.append(
                {
                    "rule_id": "evidence_quote_containment",
                    "observation_id": _observation_id(
                        "evidence_quote_containment", _evidence_id(evidence)
                    ),
                    "entity_id": evidence.entity_ref,
                    "quote": evidence.quote,
                    "passage_text": passage.text,
                    "passage_id": evidence.passage_id,
                }
            )
        coverage.append(
            _coverage(
                "evidence_quote_containment",
                candidate=evaluated + blocked,
                evaluated=evaluated,
                blocked=blocked,
                reason_code=_BLOCKED_PASSAGE_UNRESOLVED,
            )
        )

    # --- Rule 6: publication-date cutoff (distinct cited source) ----------
    if not schema_valid:
        blocked_only("publication_date_cutoff", _BLOCKED_SCHEMA_INVALID)
    else:
        evaluated = blocked = 0
        for source_id in cited_source_ids:
            document = documents_by_id.get(source_id)
            if document is None:
                blocked += 1
                continue
            evaluated += 1
            observations.append(
                {
                    "rule_id": "publication_date_cutoff",
                    "observation_id": _observation_id("publication_date_cutoff", source_id),
                    "publication_date": document.publication_date,
                    "observation_cutoff_date": content.observation_cutoff,
                    "source_id": source_id,
                }
            )
        coverage.append(
            _coverage(
                "publication_date_cutoff",
                candidate=evaluated + blocked,
                evaluated=evaluated,
                blocked=blocked,
                reason_code=_BLOCKED_SOURCE_UNRESOLVED,
            )
        )

    # --- Rule 7: parent resolution (raw parent links) ---------------------
    # Derived from the raw document, never from binding parent entries: at
    # task_extraction the parsed entity space holds only the task observation, so a
    # task-stage binding cannot carry parent entries at all.
    rule7_id = "product_capability_task_parent_resolution"
    raw_links_present = False
    pair_roles: dict[tuple[str, str], set[str]] = {}
    if raw_object is not None and isinstance(raw_child_id, str):
        raw_links_present = True
        for role, field, is_list in _STAGE_PARENT_LINKS[evaluation_stage]:
            value = raw_object.get(field)
            if is_list:
                if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                    raw_links_present = False
                    break
                parents = value
            else:
                if not isinstance(value, str):
                    raw_links_present = False
                    break
                parents = [value]
            for parent_id in parents:
                pair_roles.setdefault((raw_child_id, parent_id), set()).add(role)
    if not schema_valid or not rule2_satisfied or not raw_links_present or not pair_roles:
        blocked_only(rule7_id, _BLOCKED_REQUIRED_FIELD_MISSING)
    else:
        snapshot_roles = {
            role: frozenset(getattr(parent_snapshot, field))
            for role, field in _PARENT_ROLE_SNAPSHOT_FIELD.items()
        }
        for child_id, parent_id in sorted(pair_roles):
            observations.append(
                {
                    "rule_id": rule7_id,
                    "observation_id": _observation_id(rule7_id, f"{child_id}~{parent_id}"),
                    "entity_id": child_id,
                    "child_id": child_id,
                    "parent_id": parent_id,
                    "available_parent_ids": _available_parent_ids(
                        pair_roles[(child_id, parent_id)], snapshot_roles
                    ),
                }
            )
        coverage.append(
            _coverage(
                rule7_id,
                candidate=len(pair_roles),
                evaluated=len(pair_roles),
                blocked=0,
                reason_code=None,
            )
        )

    # --- Rule 8: unique IDs within scope (declared scope) -----------------
    if not schema_valid:
        blocked_only("unique_ids_within_scope", _BLOCKED_SCHEMA_INVALID)
    else:
        record_ids = tuple(sorted(e.entity_ref for e in content.entity_collection.entities))
        observations.append(
            {
                "rule_id": "unique_ids_within_scope",
                "observation_id": _observation_id(
                    "unique_ids_within_scope", content.prediction_record_id
                ),
                "entity_id": content.prediction_record_id,
                "scope_id": content.prediction_record_id,
                "record_ids": record_ids,
            }
        )
        coverage.append(
            _coverage(
                "unique_ids_within_scope", candidate=1, evaluated=1, blocked=0, reason_code=None
            )
        )

    # --- Rule 9: prohibited legacy fields absent (raw document) -----------
    rule9 = selected["prohibited_legacy_fields_absent"]
    if not schema_valid:
        blocked_only("prohibited_legacy_fields_absent", _BLOCKED_SCHEMA_INVALID)
    else:
        observations.append(
            {
                "rule_id": "prohibited_legacy_fields_absent",
                "observation_id": _observation_id(
                    "prohibited_legacy_fields_absent", content.raw_artifact_sha256
                ),
                "present_field_names": tuple(sorted(raw_object)),
                "prohibited_field_names": tuple(rule9.payload.prohibited_field_names),
            }
        )
        coverage.append(
            _coverage(
                "prohibited_legacy_fields_absent",
                candidate=1,
                evaluated=1,
                blocked=0,
                reason_code=None,
            )
        )

    # --- Rule 10: active record needs non-roadmap evidence ----------------
    rule10_id = "active_record_non_roadmap_evidence"
    rule10 = selected[rule10_id]
    subject_evidence = tuple(
        e for e in evidence_entries if e.entity_ref == subject.observation_id
    )
    unresolved_subject_source = any(
        e.source_id not in documents_by_id for e in subject_evidence
    )
    if not schema_valid or not rule2_satisfied:
        # Dependency precedence: Rule 2 before Rule 3, matching canonical order.
        blocked_only(rule10_id, _BLOCKED_REQUIRED_FIELD_MISSING)
    elif unresolved_subject_source:
        # A prediction citation defect Rule 3 reports; Rule 10 states why it could
        # not be evaluated instead of aborting the producer.
        blocked_only(rule10_id, _BLOCKED_SOURCE_UNRESOLVED)
    else:
        raw_status = raw_object.get("availability_status")
        active_values = set(rule10.payload.active_status_values)
        roadmap_values = set(rule10.payload.roadmap_status_values)
        if not isinstance(raw_status, str) or raw_status not in (active_values | roadmap_values):
            raise ValueError(
                "the raw availability_status is not in the governed Rule-10 active or "
                "roadmap vocabulary; an unknown status is never treated as inactive"
            )
        classifications = [
            {
                "evidence_id": _evidence_id(e),
                "is_future_roadmap": (
                    date.fromisoformat(documents_by_id[e.source_id].publication_date) > cutoff
                ),
            }
            for e in subject_evidence
        ]
        observations.append(
            {
                "rule_id": rule10_id,
                "observation_id": _observation_id(rule10_id, subject.observation_id),
                "entity_id": subject.observation_id,
                "active": raw_status in active_values,
                "evidence": tuple(classifications),
            }
        )
        coverage.append(
            _coverage(rule10_id, candidate=1, evaluated=1, blocked=0, reason_code=None)
        )

    # --- Rule 11: inapplicable at both extraction stages ------------------
    rule11_id = "customer_task_outcome_and_evidence"
    rule11 = selected[rule11_id]
    if rule11.applicability != "inapplicable":
        raise ValueError(
            "Rule 11 must be inapplicable at an extraction stage under "
            "validator_rule_parameters@0.2.0"
        )
    coverage.append(_inapplicable_coverage(rule11_id, rule11.reason_code))

    # --- Assemble ---------------------------------------------------------
    observations.sort(
        key=lambda o: (_RULE_POSITION[o["rule_id"]], o["observation_id"])
    )
    coverage.sort(key=lambda c: _RULE_POSITION[c.rule_id])
    observed_rules = tuple(c.rule_id for c in coverage)
    if observed_rules != _RULES_1_TO_11:
        raise ValueError("coverage must carry exactly Rules 1-11 in canonical order")
    # Observations are handed over as canonical dicts and validated through the
    # governed discriminated union by the model itself, so a malformed rule payload
    # fails here rather than downstream.
    return ExtractionValidationInputs.model_validate(
        {
            "case_id": case.case_id,
            "evaluation_stage": evaluation_stage,
            "prediction_record_id": content.prediction_record_id,
            "raw_artifact_sha256": content.raw_artifact_sha256,
            "parsed_prediction_content_sha256": parsed_prediction_content.sha256,
            "output_schema_sha256": expected_schema_sha256,
            "output_schema_reference": rule1.payload.output_schema_reference,
            "parameter_set_version": rule_parameters.model.parameter_set_version,
            "parameter_set_aggregate_hash": aggregate,
            "bundle_version": validator_bundle_artifact.model.bundle_version,
            "bundle_hash": validator_bundle_artifact.model.bundle_hash,
            "observations": observations,
            "coverage": list(coverage),
        }
    )
