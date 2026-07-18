from pathlib import Path

import pytest

from dynamic_ai_products.universe.audit import draw_negative_audit_sample
from dynamic_ai_products.universe.models import AdjudicationRecord, TierDecision
from dynamic_ai_products.universe.review import (
    AdjudicationLog,
    ReviewError,
    build_review_case,
    final_review_state,
    resolve_queue,
)
from dynamic_ai_products.universe.rules import SampleRules, derive_tier

from test_tier_rules import classification

ROOT = Path(__file__).resolve().parents[2]
RULES = SampleRules(ROOT / "configs" / "universe_sample_rules.yaml")


def make_decision() -> TierDecision:
    return derive_tier(classification(software_centrality="CO_ESSENTIAL"), RULES)


def make_adjudication(**overrides) -> AdjudicationRecord:
    payload = {
        "adjudication_id": "adj-1",
        "case_id": "case-0001000001",
        "decision": "CONFIRM_RULE_TIER",
        "final_candidate_tier": "TIER_A_CORE",
        "reason_codes": ["confirmed"],
        "evidence": [],
        "reviewer": "tester",
        "review_comment": "ok",
        "confidence": "high",
    }
    payload.update(overrides)
    return AdjudicationRecord.model_validate(payload)


def test_review_case_captures_triggers_and_question() -> None:
    decision = make_decision()
    case = build_review_case(decision, classification(software_centrality="CO_ESSENTIAL"))
    assert case.case_id == "case-0001000001"
    assert "software_centrality_is_CO_ESSENTIAL" in case.trigger_reasons
    assert case.suggested_review_question
    assert case.status == "open"


def test_adjudication_log_is_append_only(tmp_path: Path) -> None:
    log = AdjudicationLog(tmp_path / "adjudications.jsonl")
    log.append(make_adjudication())
    with pytest.raises(ReviewError):
        log.append(make_adjudication())  # same adjudication_id cannot be rewritten
    log.append(make_adjudication(adjudication_id="adj-2"))
    assert [r.adjudication_id for r in log.read_all()] == ["adj-1", "adj-2"]


def test_resolution_never_mutates_raw_decision() -> None:
    decision = make_decision()
    case = build_review_case(decision, None)
    resolved, open_cases = resolve_queue([case], [make_adjudication()])
    assert len(resolved) == 1 and not open_cases
    assert resolved[0].status == "resolved"
    assert decision.derived_tier == "TIER_A_CORE"  # original untouched

    final_tier, status = final_review_state(decision, make_adjudication())
    assert (final_tier, status) == ("TIER_A_CORE", "approved")

    override = make_adjudication(
        decision="OVERRIDE_RULE_TIER", final_candidate_tier="TIER_C_BOUNDARY"
    )
    final_tier, status = final_review_state(decision, override)
    assert (final_tier, status) == ("TIER_C_BOUNDARY", "overridden")
    assert decision.derived_tier == "TIER_A_CORE"  # still untouched


def test_unadjudicated_case_stays_open() -> None:
    case = build_review_case(make_decision(), None)
    resolved, open_cases = resolve_queue([case], [])
    assert not resolved and len(open_cases) == 1


NEGATIVES = [
    {"cik": "0001", "sic": "3312", "candidate_customer_value_archetypes": [], "exclusion_reason": "screen_likely_ineligible", "confidence": "high"},
    {"cik": "0002", "sic": "3316", "candidate_customer_value_archetypes": [], "exclusion_reason": "screen_likely_ineligible", "confidence": "high"},
    {"cik": "0003", "sic": "6022", "candidate_customer_value_archetypes": [], "exclusion_reason": "screen_likely_ineligible", "confidence": "medium"},
    {"cik": "0004", "sic": "6722", "candidate_customer_value_archetypes": [], "exclusion_reason": "FUND_OR_INVESTMENT_COMPANY", "confidence": "high"},
    {"cik": "0005", "sic": "6770", "candidate_customer_value_archetypes": [], "exclusion_reason": "SHELL_OR_PRECOMBINATION_SPAC", "confidence": "high"},
]


def test_negative_audit_sample_is_reproducible_from_seed() -> None:
    first = draw_negative_audit_sample(NEGATIVES, seed=42)
    second = draw_negative_audit_sample(list(reversed(NEGATIVES)), seed=42)
    assert first == second  # input order must not matter
    third = draw_negative_audit_sample(NEGATIVES, seed=43)
    assert first != third or [r["cik"] for r in first] == [r["cik"] for r in third]
    assert all("stratum" in record and record["audit_seed"] == 42 for record in first)


def test_negative_audit_covers_every_stratum() -> None:
    sample = draw_negative_audit_sample(NEGATIVES, seed=7)
    strata = {tuple(record["stratum"]) for record in sample}
    assert len(strata) == 4  # 33-group merges two firms; the rest are singleton strata
