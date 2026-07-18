from datetime import date
from pathlib import Path

import pytest

from dynamic_ai_products.universe.classification import (
    ClassificationFailure,
    load_schema_validator,
    validate_classification,
)
from dynamic_ai_products.universe.models import BaselineEvidencePacket, EvidencePassage
from dynamic_ai_products.universe.screening import (
    PROMPT_RELATIVE_PATH,
    ScreenProviderError,
    render_screen_prompt,
    validate_screen_output,
)

from universe_test_helpers import make_filer

ROOT = Path(__file__).resolve().parents[2]
CUTOFF = date(2022, 12, 31)


def make_packet() -> BaselineEvidencePacket:
    passages = [
        EvidencePassage(
            passage_id="p1",
            source_id="fixture:src",
            section="ITEM1_OVERVIEW",
            publication_date=date(2022, 9, 15),
            text="Our editing software creates and validates customer documents.",
        )
    ]
    missing = sorted(
        {"COVER_PAGE", "PRODUCTS_SERVICES", "CUSTOMERS", "SEGMENTS_MATERIALITY", "TECHNOLOGY_DELIVERY"}
    )
    return BaselineEvidencePacket(
        packet_id="packet-test",
        cik="0001000001",
        company_id="CIK0001000001",
        baseline_cutoff=CUTOFF,
        baseline_filing_date=date(2022, 9, 15),
        passages=passages,
        missing_sections=missing,
        insufficient_evidence=True,
    )


def test_prompt_renders_all_placeholders() -> None:
    template = (ROOT / PROMPT_RELATIVE_PATH).read_text(encoding="utf-8")
    rendered = render_screen_prompt(template, make_filer(), make_packet())
    assert "{{" not in rendered
    assert "2022-12-31" in rendered
    assert "Our editing software creates and validates customer documents." in rendered


def test_eligible_screen_requires_resolvable_quote() -> None:
    good = {
        "screen_status": "LIKELY_ELIGIBLE",
        "plausible_customer_facing_digital_product": True,
        "candidate_customer_value_archetypes": ["FUNCTIONAL_SOFTWARE"],
        "positive_evidence": [
            {
                "source_id": "fixture:src",
                "passage_id": "p1",
                "quote": "Our editing software creates and validates customer documents.",
                "supported_claim": "Software produces the outcome.",
            }
        ],
        "negative_or_boundary_evidence": [],
        "missing_evidence": [],
        "confidence": "high",
    }
    output = validate_screen_output(good, make_filer(), make_packet())
    assert output.screen_status == "LIKELY_ELIGIBLE"

    fabricated = {**good, "positive_evidence": [{**good["positive_evidence"][0], "quote": "A quote that is not in the packet."}]}
    with pytest.raises(ScreenProviderError):
        validate_screen_output(fabricated, make_filer(), make_packet())

    evidence_free = {**good, "positive_evidence": []}
    with pytest.raises(ScreenProviderError):
        validate_screen_output(evidence_free, make_filer(), make_packet())


def test_unknown_over_guess_is_preserved_in_screen_output() -> None:
    uncertain = {
        "screen_status": "BOUNDARY_OR_UNCERTAIN",
        "plausible_customer_facing_digital_product": None,
        "candidate_customer_value_archetypes": [],
        "positive_evidence": [],
        "negative_or_boundary_evidence": [],
        "missing_evidence": ["Concrete product passages."],
        "confidence": "low",
    }
    output = validate_screen_output(uncertain, make_filer(), make_packet())
    assert output.plausible_customer_facing_digital_product is None


def base_classification() -> dict:
    return {
        "classification_id": "ucls-test",
        "company_id": "CIK0001000001",
        "cik": "0001000001",
        "baseline_accession": "0001000001-22-000001",
        "baseline_filing_date": "2022-09-15",
        "baseline_cutoff": "2022-12-31",
        "customer_value_archetypes": ["FUNCTIONAL_SOFTWARE"],
        "software_centrality": "CORE",
        "complementary_dependencies": [],
        "firm_structure": "PURE_PLAY",
        "commercial_materiality": "DOMINANT",
        "customer_facing_functional_product": True,
        "operating_company": True,
        "economically_eligible": True,
        "data_eligible": True,
        "screen_status": "LIKELY_ELIGIBLE",
        "candidate_tier": "TIER_A_CORE",
        "boundary_flags": [],
        "contradictions": [],
        "evidence": [
            {
                "claim": "Software produces the outcome.",
                "source_id": "fixture:src",
                "passage_id": "p1",
                "quote": "Our editing software creates and validates customer documents.",
            }
        ],
        "rule_trace": [],
        "confidence": "high",
        "review_status": "unreviewed",
        "taxonomy_version": "0.1.0",
        "sample_rules_version": None,
        "schema_version": "0.1.0",
    }


def test_valid_classification_passes_schema_and_packet_checks() -> None:
    validator = load_schema_validator(ROOT)
    record = validate_classification(base_classification(), make_filer(), make_packet(), validator)
    assert record.candidate_tier == "TIER_A_CORE"


def test_taxonomy_enum_violation_is_rejected_not_repaired() -> None:
    validator = load_schema_validator(ROOT)
    bad = {**base_classification(), "software_centrality": "SUPER_CORE"}
    with pytest.raises(ClassificationFailure):
        validate_classification(bad, make_filer(), make_packet(), validator)


def test_axis_claims_without_evidence_are_rejected() -> None:
    validator = load_schema_validator(ROOT)
    bad = {**base_classification(), "evidence": []}
    with pytest.raises(ClassificationFailure):
        validate_classification(bad, make_filer(), make_packet(), validator)


def test_fabricated_classification_quote_is_rejected() -> None:
    validator = load_schema_validator(ROOT)
    record = base_classification()
    record["evidence"][0]["quote"] = "This quote is not in any packet passage."
    with pytest.raises(ClassificationFailure):
        validate_classification(record, make_filer(), make_packet(), validator)
