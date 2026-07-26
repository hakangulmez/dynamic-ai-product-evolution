"""Semantic assertion evaluators (Slice 12H, SPEC-020/022/023 / ADR-024).

``build_resolved_assertion_evaluations`` is a pure, case-level semantic producer.
It consumes governed loaded inputs and returns a transient
``SemanticAssertionEvaluationResult`` carrying one committed
``ResolvedAssertionEvaluation`` (Slice-7 model) per resolved case-assertion, plus
deterministically accumulated sanitized Phase-A input-validity issues and the
IDs of assertions left not-evaluated. It never persists, never reads the
filesystem, never calls a resolver/provider/clock, and never modifies
``assertions.py``; the produced evaluations feed the unchanged dispatcher.

Phase A is an aggregate input-validity gate: binding/input defects are collected
in deterministic order and their affected assertions are marked not-evaluated
(``not_evaluated`` itself remains owned by the dispatcher / persisted outcome
contract). Phase B is per-assertion entity/field/evidence semantics (four-value
outcome). Phase C is the case-level aggregate deterministic-validation mapping
from the validation snapshot set's coverage and the run's validator findings.

No raw prediction text, quote, passage, gold expected value, absolute path,
OS/Pydantic text, or provider output ever enters an outcome or an issue.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import model_validator

from .assertions import ResolvedAssertionEvaluation
from .gold import BoundGoldAssertionSet, LoadedGoldAssertionSet
from .models import AssertionKind, EvaluationCase, EvaluationStrictModel, _require_non_blank
from .observation_target_binding import (
    EXTRACTION_EVALUATION_STAGES,
    LoadedObservationTargetBinding,
    observations_by_canonical_target,
    unresolved_observation_ids,
)
from .prediction_content import LoadedParsedPredictionContent
from .references import CaseResolution
from .source_snapshot import (
    LoadedSourcePassageSnapshotManifest,
    SourceSnapshotError,
    resolve_case_source_passages,
)
from .validation_snapshot import LoadedValidationArtifactSnapshotSet
from .validators import LoadedValidatorFindings

__all__ = [
    "SemanticAssertionEvaluationError",
    "SemanticAssertionEvaluationResult",
    "build_extraction_resolved_assertion_evaluations",
    "build_resolved_assertion_evaluations",
]

_POSITIVE_OPERATORS = frozenset({"equals", "in_set", "gte", "gt", "lte", "lt"})
_RULE_12 = "raw_output_and_repair_preservation"

# Closed, ASCII-only lexical grammars. ``str.isdigit`` admits non-ASCII digit
# forms; an explicit character class keeps the numeric grammar closed to the
# ASCII signed-integer and signed-decimal forms only (no locale-dependent
# parsing, no binary float).
_ASCII_INTEGER = re.compile(r"[+-]?[0-9]+")
_ASCII_NUMBER = re.compile(r"[+-]?(?:[0-9]+|[0-9]+\.[0-9]+)")


# --- Public error + result ------------------------------------------------


class SemanticAssertionEvaluationError(Exception):
    """Sanitized semantic-evaluation failure with a stable machine-readable code."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class _PhaseAIssue(EvaluationStrictModel):
    # Private (never exported): carries only safe identifiers/codes.
    issue_code: str
    scope: Literal["global", "assertion"]
    assertion_id: str | None = None

    @model_validator(mode="after")
    def _issue_invariants(self) -> "_PhaseAIssue":
        _require_non_blank(self.issue_code, "issue_code")
        if self.scope == "assertion":
            if self.assertion_id is None:
                raise ValueError("assertion-scoped issue requires an assertion_id")
            _require_non_blank(self.assertion_id, "assertion_id")
        elif self.assertion_id is not None:
            raise ValueError("global issue must not carry an assertion_id")
        return self


class SemanticAssertionEvaluationResult(EvaluationStrictModel):
    """Transient case-level semantic evaluation result (never persisted)."""

    case_id: str
    evaluations: tuple[ResolvedAssertionEvaluation, ...]
    input_validity_issues: tuple[_PhaseAIssue, ...]
    not_evaluated_assertion_ids: tuple[str, ...]


# --- Strict typed-value parsing (deterministic; never silently coerced) ---


def _parse_actual(value: str, value_type: str):
    if value_type == "string":
        return True, value
    if value_type == "boolean":
        if value in ("true", "false"):
            return True, value == "true"
        return False, None
    if value_type == "integer":
        # Closed ASCII grammar: optional sign then one or more ASCII digits.
        if _ASCII_INTEGER.fullmatch(value):
            return True, int(value)
        return False, None
    if value_type == "number":
        # Closed ASCII grammar: optional sign, ASCII digits, at most one
        # fractional part (non-empty both sides). Parsed exactly as Decimal.
        if _ASCII_NUMBER.fullmatch(value):
            try:
                return True, Decimal(value)
            except InvalidOperation:
                return False, None
        return False, None
    # date
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return False, None
    if parsed.isoformat() != value:
        return False, None
    return True, parsed


def _coerce_expected(value, value_type):
    if value_type == "date":
        return date.fromisoformat(value)
    if value_type == "number":
        # Exact: ``int`` converts without loss; a float expected value is taken
        # via its shortest round-trip string so no binary artefact is introduced.
        return Decimal(value) if isinstance(value, int) else Decimal(str(value))
    return value


def _operator_satisfies(operator: str, actual, expected: list) -> bool:
    if operator == "equals":
        return actual == expected[0]
    if operator == "not_equals":
        return actual != expected[0]
    if operator == "in_set":
        return actual in expected
    if operator == "not_in_set":
        return actual not in expected
    if operator == "gte":
        return actual >= expected[0]
    if operator == "gt":
        return actual > expected[0]
    if operator == "lte":
        return actual <= expected[0]
    return actual < expected[0]  # lt


# --- Phase B outcome functions --------------------------------------------


def _entity_outcome(kind: str, targets: set[str], content) -> str:
    collection = content.entity_collection
    if collection.completeness != "complete":
        return "indeterminate"
    present = {entity.entity_ref for entity in collection.entities}
    if kind == "expected_entity":
        return "satisfied" if all(t in present for t in targets) else "unsatisfied"
    return "satisfied" if all(t not in present for t in targets) else "unsatisfied"


def _field_value_outcome(entry, content) -> str:
    collection = content.field_value_collection
    if collection.completeness != "complete":
        return "indeterminate"
    payload = entry.field_value_payload
    matching = [
        fv for fv in collection.field_values
        if fv.entity_ref == entry.canonical_target_reference
        and fv.field_name == payload.field_path
    ]
    if not matching:
        return "unsatisfied"
    expected = [_coerce_expected(v, payload.value_type) for v in payload.expected_values]
    results = []
    for fv in matching:
        ok, actual = _parse_actual(fv.field_value, payload.value_type)
        results.append(ok and _operator_satisfies(payload.operator, actual, expected))
    if payload.operator in _POSITIVE_OPERATORS:
        return "satisfied" if any(results) else "unsatisfied"
    return "satisfied" if all(results) else "unsatisfied"


def _evidence_record_ok(evidence, payload, documents_by_id, passages_by_id) -> bool:
    if evidence.source_id != payload.expected_source_id:
        return False
    document = documents_by_id.get(payload.expected_source_id)
    if document is None or document.publication_date != payload.expected_publication_date:
        return False
    passage = passages_by_id.get(evidence.passage_id)
    if passage is None or passage.source_id != payload.expected_source_id:
        return False
    if payload.match_mode == "exact_passage" and evidence.passage_id != payload.expected_passage_id:
        return False
    if evidence.quote.strip() == "" or evidence.quote not in passage.text:
        return False
    return True


def _evidence_outcome(entry, content, documents_by_id, passages_by_id) -> str:
    collection = content.evidence_collection
    if collection.completeness != "complete":
        return "indeterminate"
    payload = entry.evidence_provenance_payload
    relevant = [
        ev for ev in collection.evidence
        if ev.entity_ref == entry.canonical_target_reference
    ]
    if not relevant:
        return "unsatisfied"
    for evidence in relevant:
        if not _evidence_record_ok(evidence, payload, documents_by_id, passages_by_id):
            return "unsatisfied"
    return "satisfied"


# --- Phase B outcome functions, binding-mediated (extraction stages) -------
#
# For an extraction stage a gold ``canonical_target_reference`` is NOT an
# ``entity_ref``: the two live in separate namespaces and only
# ``observation_target_binding@0.1.0`` maps between them. ``mapped`` is the
# resolved canonical -> mapped-observation index (many-to-one), ``unresolved`` the
# present unresolved observations. A missing resolved mapping is not
# automatically indeterminate: unresolved observations must actually be present
# for the outcome to be unknowable.


def _binding_entity_outcome(kind: str, targets: set[str], content, mapped, unresolved) -> str:
    collection = content.entity_collection
    if collection.completeness != "complete":
        return "indeterminate"
    resolved_canonicals = set(mapped)
    if kind == "expected_entity":
        if targets <= resolved_canonicals:
            return "satisfied"
        return "indeterminate" if unresolved else "unsatisfied"
    # forbidden_entity
    if targets & resolved_canonicals:
        return "unsatisfied"
    return "indeterminate" if unresolved else "satisfied"


def _binding_field_value_outcome(entry, content, mapped, unresolved) -> str:
    collection = content.field_value_collection
    if collection.completeness != "complete":
        return "indeterminate"
    if unresolved:
        return "indeterminate"
    observations = set(mapped.get(entry.canonical_target_reference, ()))
    if not observations:
        return "unsatisfied"
    payload = entry.field_value_payload
    matching = [
        fv for fv in collection.field_values
        if fv.entity_ref in observations and fv.field_name == payload.field_path
    ]
    if not matching:
        return "unsatisfied"
    expected = [_coerce_expected(v, payload.value_type) for v in payload.expected_values]
    results = []
    for fv in matching:
        ok, actual = _parse_actual(fv.field_value, payload.value_type)
        results.append(ok and _operator_satisfies(payload.operator, actual, expected))
    if payload.operator in _POSITIVE_OPERATORS:
        return "satisfied" if any(results) else "unsatisfied"
    return "satisfied" if all(results) else "unsatisfied"


def _binding_evidence_outcome(
    entry, content, documents_by_id, passages_by_id, mapped, unresolved
) -> str:
    collection = content.evidence_collection
    if collection.completeness != "complete":
        return "indeterminate"
    if unresolved:
        return "indeterminate"
    observations = set(mapped.get(entry.canonical_target_reference, ()))
    if not observations:
        return "unsatisfied"
    payload = entry.evidence_provenance_payload
    relevant = [ev for ev in collection.evidence if ev.entity_ref in observations]
    if not relevant:
        return "unsatisfied"
    for evidence in relevant:
        if not _evidence_record_ok(evidence, payload, documents_by_id, passages_by_id):
            return "unsatisfied"
    return "satisfied"


def _deterministic_outcome(case_snapshots) -> str:
    states = [record.coverage_state for snap in case_snapshots for record in snap.coverage]
    if any(state in ("partially_evaluated", "blocked_by_dependency") for state in states):
        return "indeterminate"
    if states and all(state == "inapplicable" for state in states):
        return "not_applicable"
    return "satisfied"


# --- Producer -------------------------------------------------------------


def build_resolved_assertion_evaluations(
    *,
    case: EvaluationCase,
    resolution: CaseResolution,
    parsed_content: LoadedParsedPredictionContent,
    gold: LoadedGoldAssertionSet,
    bound_gold: BoundGoldAssertionSet,
    source_snapshot: LoadedSourcePassageSnapshotManifest,
    validation_snapshots: LoadedValidationArtifactSnapshotSet,
    validator_findings: LoadedValidatorFindings,
) -> SemanticAssertionEvaluationResult:
    """Evaluate one *non-extraction* case's assertions (Phases A/B/C).

    Stage-general and deliberately binding-free: a gold
    ``canonical_target_reference`` is compared directly against the parsed
    ``entity_ref`` namespace. An extraction-stage case is rejected — those
    namespaces are distinct there, and only
    :func:`build_extraction_resolved_assertion_evaluations` may bridge them.
    Behaviour for every non-extraction stage is unchanged.
    """
    if isinstance(case, EvaluationCase) and case.stage in EXTRACTION_EVALUATION_STAGES:
        raise SemanticAssertionEvaluationError(
            "an extraction-stage case requires the binding-aware extraction evaluator",
            reason_code="extraction_stage_requires_binding",
        )
    return _build_evaluations(
        case=case, resolution=resolution, parsed_content=parsed_content, gold=gold,
        bound_gold=bound_gold, source_snapshot=source_snapshot,
        validation_snapshots=validation_snapshots, validator_findings=validator_findings,
        binding=None,
    )


def build_extraction_resolved_assertion_evaluations(
    *,
    case: EvaluationCase,
    resolution: CaseResolution,
    parsed_content: LoadedParsedPredictionContent,
    gold: LoadedGoldAssertionSet,
    bound_gold: BoundGoldAssertionSet,
    source_snapshot: LoadedSourcePassageSnapshotManifest,
    validation_snapshots: LoadedValidationArtifactSnapshotSet,
    validator_findings: LoadedValidatorFindings,
    binding: LoadedObservationTargetBinding,
) -> SemanticAssertionEvaluationResult:
    """Evaluate one *extraction* case's assertions through the observation-target binding.

    Mutually exclusive with :func:`build_resolved_assertion_evaluations`: a
    non-extraction stage is rejected here, and an extraction stage is rejected
    there. Every gold canonical target is mapped through the binding to its
    (possibly several) raw observation IDs before entity/field/evidence semantics
    run; unresolved observations make an otherwise-unprovable outcome
    ``indeterminate`` rather than ``unsatisfied``.
    """
    if not isinstance(binding, LoadedObservationTargetBinding):
        raise TypeError(
            f"binding must be a LoadedObservationTargetBinding, got {type(binding).__name__}"
        )
    if isinstance(case, EvaluationCase) and case.stage not in EXTRACTION_EVALUATION_STAGES:
        raise SemanticAssertionEvaluationError(
            "a non-extraction-stage case must use the stage-general evaluator",
            reason_code="non_extraction_stage_rejected",
        )
    return _build_evaluations(
        case=case, resolution=resolution, parsed_content=parsed_content, gold=gold,
        bound_gold=bound_gold, source_snapshot=source_snapshot,
        validation_snapshots=validation_snapshots, validator_findings=validator_findings,
        binding=binding,
    )


def _build_evaluations(
    *,
    case: EvaluationCase,
    resolution: CaseResolution,
    parsed_content: LoadedParsedPredictionContent,
    gold: LoadedGoldAssertionSet,
    bound_gold: BoundGoldAssertionSet,
    source_snapshot: LoadedSourcePassageSnapshotManifest,
    validation_snapshots: LoadedValidationArtifactSnapshotSet,
    validator_findings: LoadedValidatorFindings,
    binding: LoadedObservationTargetBinding | None,
) -> SemanticAssertionEvaluationResult:
    """Shared Phase A/B/C body; ``binding is None`` is the stage-general path."""
    if not isinstance(case, EvaluationCase):
        raise TypeError(f"case must be an EvaluationCase, got {type(case).__name__}")
    if not isinstance(resolution, CaseResolution):
        raise TypeError(f"resolution must be a CaseResolution, got {type(resolution).__name__}")
    if not isinstance(parsed_content, LoadedParsedPredictionContent):
        raise TypeError(
            f"parsed_content must be a LoadedParsedPredictionContent, got "
            f"{type(parsed_content).__name__}"
        )
    if not isinstance(gold, LoadedGoldAssertionSet):
        raise TypeError(f"gold must be a LoadedGoldAssertionSet, got {type(gold).__name__}")
    if not isinstance(bound_gold, BoundGoldAssertionSet):
        raise TypeError(
            f"bound_gold must be a BoundGoldAssertionSet, got {type(bound_gold).__name__}"
        )
    if not isinstance(source_snapshot, LoadedSourcePassageSnapshotManifest):
        raise TypeError(
            f"source_snapshot must be a LoadedSourcePassageSnapshotManifest, got "
            f"{type(source_snapshot).__name__}"
        )
    if not isinstance(validation_snapshots, LoadedValidationArtifactSnapshotSet):
        raise TypeError(
            f"validation_snapshots must be a LoadedValidationArtifactSnapshotSet, got "
            f"{type(validation_snapshots).__name__}"
        )
    if not isinstance(validator_findings, LoadedValidatorFindings):
        raise TypeError(
            f"validator_findings must be a LoadedValidatorFindings, got "
            f"{type(validator_findings).__name__}"
        )

    content = parsed_content.content
    vmodel = validation_snapshots.model
    snapshots_by_artifact = {snap.artifact_id: snap for snap in vmodel.snapshots}
    case_snapshots = [snap for snap in vmodel.snapshots if snap.case_id == case.case_id]

    # --- Phase A: aggregate global input-validity gate (all categories) ---
    global_issues: list[str] = []

    def add_global(code: str) -> None:
        if code not in global_issues:
            global_issues.append(code)

    if resolution.case_id != case.case_id:
        add_global("case_resolution_case_id_mismatch")
    if content.case_id != case.case_id:
        add_global("parsed_content_case_mismatch")
    if content.stage != case.stage:
        add_global("parsed_content_stage_mismatch")
    if vmodel.evaluation_stage != case.stage:
        add_global("validation_set_stage_mismatch")
    if validator_findings.eval_run_id != vmodel.eval_run_id:
        add_global("findings_run_id_mismatch")
    if not case_snapshots:
        add_global("no_case_validation_snapshot")
    # Every case snapshot (not merely one) must bind the parsed-content SHA.
    if any(
        snap.parsed_prediction_content_sha256 != parsed_content.sha256
        for snap in case_snapshots
    ):
        add_global("case_snapshot_parsed_content_mismatch")
    # Binding-vs-input reconciliation (extraction path only). Defence in depth:
    # the producer already pinned these at construction time, so a disagreement
    # here means the binding does not belong to this case/content/registry.
    if binding is not None:
        bmodel = binding.model
        if bmodel.case_id != case.case_id:
            add_global("binding_case_mismatch")
        if bmodel.stage != case.stage:
            add_global("binding_stage_mismatch")
        if bmodel.parsed_prediction_content_sha256 != parsed_content.sha256:
            add_global("binding_parsed_content_mismatch")
        if (
            bmodel.target_registry_version != resolution.target_registry_version
            or bmodel.target_registry_sha256 != resolution.target_registry_sha256
        ):
            add_global("binding_target_registry_mismatch")
    # Every finding's own run_id must equal the wrapper's eval_run_id (which, in
    # turn, must equal the snapshot set's run — checked above).
    if any(f.run_id != validator_findings.eval_run_id for f in validator_findings.findings):
        add_global("finding_run_id_mismatch")
    # Each finding's artifact must resolve to exactly one snapshot in the set.
    artifact_counts = Counter(snap.artifact_id for snap in vmodel.snapshots)
    if any(artifact_counts.get(f.artifact_id, 0) != 1 for f in validator_findings.findings):
        add_global("finding_artifact_absent")
    # A finding's case_id must equal its snapshot's case_id exactly, including
    # absence: a null finding.case_id on a case-bound snapshot is inconsistent.
    for finding in validator_findings.findings:
        snap = snapshots_by_artifact.get(finding.artifact_id)
        if snap is not None and finding.case_id != snap.case_id:
            add_global("finding_case_id_inconsistent")
            break
    if (
        bound_gold.gold_set_version != gold.model.gold_set_version
        or bound_gold.sha256 != gold.sha256
    ):
        add_global("gold_binding_mismatch")
    # The case's assertion IDs must be unique (the committed schema permits
    # duplicates; assertions.py rejects them before dispatch, so semantic
    # evaluation fails closed at the same boundary). Distinct gold records under
    # one unique assertion ID (multi-target) are unaffected.
    case_assertion_id_list = [spec.assertion_id for spec in case.assertions]
    case_assertion_ids = set(case_assertion_id_list)
    if len(case_assertion_id_list) != len(case_assertion_ids):
        add_global("case_duplicate_assertion_id")
    # Resolution assertion-set reconciliation (global: duplicate / extra).
    resolution_by_aid: dict[str, list] = {}
    for resolved in resolution.assertions:
        resolution_by_aid.setdefault(resolved.assertion_id, []).append(resolved)
    if any(len(entries) > 1 for entries in resolution_by_aid.values()):
        add_global("resolution_duplicate_assertion")
    if any(aid not in case_assertion_ids for aid in resolution_by_aid):
        add_global("resolution_extra_assertion")
    try:
        resolved_sources = resolve_case_source_passages(source_snapshot, case)
    except SourceSnapshotError:
        resolved_sources = None
        add_global("source_input_resolution_defect")
    # Coverage/finding consistency across the case snapshots.
    finding_rule_counts = Counter(
        (f.artifact_id, f.validator) for f in validator_findings.findings
    )
    for finding in validator_findings.findings:
        snap = snapshots_by_artifact.get(finding.artifact_id)
        if snap is None or snap.case_id != case.case_id:
            continue
        record = {rec.rule_id: rec for rec in snap.coverage}.get(finding.validator)
        if record is None or record.coverage_state in ("inapplicable", "blocked_by_dependency"):
            add_global("coverage_finding_inconsistent")
            break
    for (artifact_id, rule_id), count in finding_rule_counts.items():
        snap = snapshots_by_artifact.get(artifact_id)
        if snap is None or snap.case_id != case.case_id:
            continue
        record = {rec.rule_id: rec for rec in snap.coverage}.get(rule_id)
        if record is None or count > record.evaluated_observation_count:
            add_global("finding_count_exceeds_evaluated")
            break

    # --- Phase A: per-assertion input-validity (resolution + gold) ---
    gold_by_key: dict[tuple[str, str], list] = {}
    for entry in gold.model.entries:
        gold_by_key.setdefault((entry.case_id, entry.assertion_id), []).append(entry)
    bound_by_key: dict[tuple[str, str], list] = {}
    for entry in bound_gold.entries:
        bound_by_key.setdefault((entry.case_id, entry.assertion_id), []).append(entry)

    run_gold_check = "gold_binding_mismatch" not in global_issues
    assertion_problem: dict[str, str] = {}

    for spec in case.assertions:
        aid = spec.assertion_id
        resolved_entries = resolution_by_aid.get(aid, [])
        if not resolved_entries:
            assertion_problem[aid] = "resolution_assertion_missing"
            continue
        resolved = resolved_entries[0]
        if (
            resolved.assertion_semantic_version != spec.semantic_version
            or resolved.assertion_contract_hash != spec.contract_hash
        ):
            assertion_problem[aid] = "resolution_identity_mismatch"
            continue
        # Exact sequence identity: order and multiplicity must match (the
        # committed schema does not declare uniqueItems, so a dropped, extra, or
        # reordered reference is a reachable, distinct binding defect).
        if tuple(rt.requested_reference_id for rt in resolved.target_references) != tuple(
            spec.target_references
        ):
            assertion_problem[aid] = "resolution_target_mismatch"
            continue
        if tuple(sr.requested_reference_id for sr in resolved.scoring_references) != tuple(
            spec.scoring_gate_config_references
        ):
            assertion_problem[aid] = "resolution_scoring_mismatch"
            continue
        # Internal consistency (ADR-024): a repeated requested reference must
        # resolve to an identical definition each time; a conflicting duplicate
        # definition is an invalidity, not something to silently pick one of.
        target_defs: dict[str, tuple] = {}
        target_conflict = False
        for rt in resolved.target_references:
            definition = (
                rt.canonical_reference_id, rt.reference_kind,
                rt.contract_id, rt.contract_version, rt.contract_hash,
            )
            if target_defs.setdefault(rt.requested_reference_id, definition) != definition:
                target_conflict = True
                break
        if target_conflict:
            assertion_problem[aid] = "resolution_target_definition_conflict"
            continue
        scoring_defs: dict[str, tuple] = {}
        scoring_conflict = False
        for sr in resolved.scoring_references:
            definition = (sr.canonical_reference_id, sr.definition_kind)
            if scoring_defs.setdefault(sr.requested_reference_id, definition) != definition:
                scoring_conflict = True
                break
        if scoring_conflict:
            assertion_problem[aid] = "resolution_scoring_definition_conflict"
            continue
        if spec.kind != "deterministic_validation" and run_gold_check:
            code = _gold_problem_code(
                spec,
                gold_by_key.get((case.case_id, aid), []),
                bound_by_key.get((case.case_id, aid), []),
                resolved,
            )
            if code is not None:
                assertion_problem[aid] = code

    # --- Assemble (Phase A short-circuits Phase B/C for affected assertions) ---
    issue_pairs: list[tuple[str, str | None]] = [(code, None) for code in global_issues]
    issue_pairs.extend((code, aid) for aid, code in assertion_problem.items())
    issues = tuple(
        _PhaseAIssue(
            issue_code=code, scope="global" if aid is None else "assertion", assertion_id=aid
        )
        for code, aid in sorted(issue_pairs, key=lambda p: (p[0], p[1] or ""))
    )

    if global_issues:
        return SemanticAssertionEvaluationResult(
            case_id=case.case_id,
            evaluations=(),
            input_validity_issues=issues,
            not_evaluated_assertion_ids=tuple(sorted(case_assertion_ids)),
        )

    documents_by_id = {doc.source_id: doc for doc in (resolved_sources.documents if resolved_sources else ())}
    passages_by_id = {p.passage_id: p for p in (resolved_sources.passages if resolved_sources else ())}
    relevant_finding = any(
        finding.artifact_id in {snap.artifact_id for snap in case_snapshots}
        for finding in validator_findings.findings
    )

    # Extraction path: resolve the canonical -> observation index once. The
    # index is many-to-one and never includes an unresolved observation.
    mapped = None if binding is None else observations_by_canonical_target(binding.model)
    unresolved = () if binding is None else unresolved_observation_ids(binding.model)

    evaluations: list[ResolvedAssertionEvaluation] = []
    for spec in case.assertions:
        aid = spec.assertion_id
        if aid in assertion_problem:
            continue
        kind: AssertionKind = spec.kind
        if kind == "deterministic_validation":
            outcome = "unsatisfied" if relevant_finding else _deterministic_outcome(case_snapshots)
        elif kind in ("expected_entity", "forbidden_entity"):
            targets = {e.canonical_target_reference for e in gold_by_key[(case.case_id, aid)]}
            outcome = (
                _entity_outcome(kind, targets, content) if mapped is None
                else _binding_entity_outcome(kind, targets, content, mapped, unresolved)
            )
        elif kind == "field_value":
            entry = gold_by_key[(case.case_id, aid)][0]
            outcome = (
                _field_value_outcome(entry, content) if mapped is None
                else _binding_field_value_outcome(entry, content, mapped, unresolved)
            )
        else:  # evidence_provenance
            entry = gold_by_key[(case.case_id, aid)][0]
            outcome = (
                _evidence_outcome(entry, content, documents_by_id, passages_by_id)
                if mapped is None
                else _binding_evidence_outcome(
                    entry, content, documents_by_id, passages_by_id, mapped, unresolved
                )
            )
        evaluations.append(_evaluation(case.case_id, spec, outcome))

    return SemanticAssertionEvaluationResult(
        case_id=case.case_id,
        evaluations=tuple(evaluations),
        input_validity_issues=issues,
        not_evaluated_assertion_ids=tuple(sorted(assertion_problem)),
    )


def _evaluation(case_id: str, spec, outcome: str) -> ResolvedAssertionEvaluation:
    return ResolvedAssertionEvaluation(
        case_id=case_id,
        assertion_id=spec.assertion_id,
        assertion_semantic_version=spec.semantic_version,
        assertion_contract_hash=spec.contract_hash,
        kind=spec.kind,
        outcome=outcome,
    )


def _gold_problem_code(spec, entries, bound_entries, resolved) -> str | None:
    kind = spec.kind
    if not entries:
        return "gold_entry_missing"
    if any(entry.assertion_kind != kind for entry in entries):
        return "gold_kind_mismatch"
    if any(
        entry.assertion_semantic_version != spec.semantic_version
        or entry.assertion_contract_hash != spec.contract_hash
        for entry in entries
    ):
        return "gold_identity_mismatch"
    if kind in ("field_value", "evidence_provenance") and len(entries) != 1:
        return "gold_entry_duplicate"
    # Deterministic multiset reconciliation over the COMPLETE shared assertion
    # identity (not merely the target string): a fabricated bound set whose
    # version/SHA/target coincide but whose kind or semantic identity differs
    # must be rejected. (Registry contract identity is reconciled separately
    # below against the resolved reference; provenance is not carried by the
    # bound set and is not compared.)
    def _ident(e):
        return (
            e.case_id, e.assertion_id, e.assertion_semantic_version,
            e.assertion_contract_hash, e.assertion_kind, e.canonical_target_reference,
        )

    if Counter(_ident(e) for e in entries) != Counter(_ident(b) for b in bound_entries):
        return "gold_bound_mismatch"
    # Reconcile each bound-gold entry against the resolved canonical target and
    # its contract identity. A fabricated bound set whose target strings merely
    # coincide (but whose contract identity does not match the independently
    # resolved reference) must be rejected, not accepted.
    resolved_by_canonical = {
        ref.canonical_reference_id: ref for ref in resolved.target_references
    }
    for bound in bound_entries:
        ref = resolved_by_canonical.get(bound.canonical_target_reference)
        if ref is None:
            return "gold_resolution_target_absent"
        if (
            bound.contract_id != ref.contract_id
            or bound.contract_version != ref.contract_version
            or bound.contract_hash != ref.contract_hash
        ):
            return "gold_resolution_contract_mismatch"
    return None
