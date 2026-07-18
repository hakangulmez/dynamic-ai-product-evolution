"""Stage 00G boundary-review queue and append-only adjudication log.

Human adjudication never overwrites the raw screen, classification, or rule
trace. Resolution is a derived view over the original records plus the
append-only adjudication log.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from .io_utils import append_jsonl, read_jsonl
from .models import (
    AdjudicationRecord,
    BoundaryReviewCase,
    TierDecision,
    UniverseClassification,
)


class ReviewError(RuntimeError):
    pass


def build_review_case(
    decision: TierDecision,
    classification: UniverseClassification | None,
) -> BoundaryReviewCase:
    """Create one queue entry for a tier decision that needs manual review."""
    triggers = list(decision.review_reasons) or ["manual_review_required"]
    summary = None
    conflicting = []
    passage_ids: list[str] = []
    if classification is not None:
        summary = (
            f"archetypes={classification.customer_value_archetypes} "
            f"centrality={classification.software_centrality} "
            f"structure={classification.firm_structure} "
            f"materiality={classification.commercial_materiality} "
            f"advisory_tier={classification.candidate_tier}"
        )
        conflicting = list(classification.evidence)
        passage_ids = sorted({e.passage_id for e in classification.evidence})
        if classification.candidate_tier != decision.derived_tier:
            triggers.append("advisory_tier_conflicts_with_rule_tier")
    question = (
        f"Confirm or override the rule-derived tier {decision.derived_tier} for "
        f"{decision.company_id}; triggers: {', '.join(sorted(set(triggers)))}."
    )
    return BoundaryReviewCase(
        case_id=f"case-{decision.cik}",
        cik=decision.cik,
        company_id=decision.company_id,
        classification_id=decision.classification_id,
        trigger_reasons=sorted(set(triggers)),
        classifier_summary=summary,
        derived_tier=decision.derived_tier,
        conflicting_evidence=conflicting,
        source_passage_ids=passage_ids,
        suggested_review_question=question,
    )


class AdjudicationLog:
    """Append-only JSONL log. There is no update or delete operation."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, record: AdjudicationRecord) -> None:
        existing_ids = {r.adjudication_id for r in self.read_all()}
        if record.adjudication_id in existing_ids:
            raise ReviewError(
                f"Adjudication {record.adjudication_id} already exists; "
                "adjudications are append-only and immutable."
            )
        append_jsonl(self.path, record.model_dump(mode="json"))

    def read_all(self) -> list[AdjudicationRecord]:
        if not self.path.exists():
            return []
        try:
            return [AdjudicationRecord.model_validate(item) for item in read_jsonl(self.path)]
        except ValidationError as exc:
            raise ReviewError(f"Corrupt adjudication log {self.path}: {exc}") from exc


def resolve_queue(
    cases: list[BoundaryReviewCase],
    adjudications: list[AdjudicationRecord],
) -> tuple[list[BoundaryReviewCase], list[BoundaryReviewCase]]:
    """Return (resolved cases, still-open cases) without mutating raw outputs."""
    latest: dict[str, AdjudicationRecord] = {}
    for record in adjudications:
        latest[record.case_id] = record
    resolved: list[BoundaryReviewCase] = []
    open_cases: list[BoundaryReviewCase] = []
    for case in cases:
        if case.case_id in latest:
            resolved.append(case.model_copy(update={"status": "resolved"}))
        else:
            open_cases.append(case)
    return resolved, open_cases


def final_review_state(
    decision: TierDecision,
    adjudication: AdjudicationRecord | None,
) -> tuple[str, str]:
    """Derive (final tier, review status) from originals plus the log."""
    if adjudication is None:
        return decision.derived_tier, "unreviewed"
    if adjudication.decision == "ONTOLOGY_CHANGE_REQUIRED":
        return decision.derived_tier, "ontology_question"
    if adjudication.decision == "REMAIN_UNCERTAIN":
        return "UNCERTAIN", "ambiguous"
    if adjudication.final_candidate_tier != decision.derived_tier:
        return adjudication.final_candidate_tier, "overridden"
    return decision.derived_tier, "approved"
