from pathlib import Path

import pytest

from dynamic_ai_products.universe.models import UniverseClassification
from dynamic_ai_products.universe.rules import (
    SampleRules,
    derive_tier,
    derive_tier_for_exclusion,
    derive_tier_for_uncertain,
)

ROOT = Path(__file__).resolve().parents[2]
RULES = SampleRules(ROOT / "configs" / "universe_sample_rules.yaml")


def classification(**overrides) -> UniverseClassification:
    payload = {
        "classification_id": "ucls-test",
        "company_id": "CIK0001000001",
        "cik": "0001000001",
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
        "candidate_tier": "TIER_A_CORE",
        "evidence": [
            {"claim": "c", "source_id": "s", "passage_id": "p", "quote": "q"}
        ],
        "confidence": "high",
        "review_status": "unreviewed",
        "taxonomy_version": "0.1.0",
        "schema_version": "0.1.0",
    }
    payload.update(overrides)
    return UniverseClassification.model_validate(payload)


def test_clear_core_software_derives_tier_a_with_trace() -> None:
    decision = derive_tier(classification(), RULES)
    assert decision.derived_tier == "TIER_A_CORE"
    assert decision.needs_manual_review is False
    assert decision.sample_rules_version == str(RULES.config["rules_version"])
    assert len(decision.sample_rules_hash) == 64
    rule_ids = {t.rule_id for t in decision.rule_trace}
    assert "tier_a_core.allowed_software_centrality" in rule_ids


def test_co_essential_tier_a_routes_to_manual_review() -> None:
    decision = derive_tier(classification(software_centrality="CO_ESSENTIAL"), RULES)
    assert decision.derived_tier == "TIER_A_CORE"
    assert decision.needs_manual_review is True
    assert "software_centrality_is_CO_ESSENTIAL" in decision.review_reasons


def test_transaction_infrastructure_derives_tier_b() -> None:
    decision = derive_tier(
        classification(
            customer_value_archetypes=["TRANSACTION_INFRASTRUCTURE"],
            software_centrality="CO_ESSENTIAL",
            candidate_tier="TIER_B_EXTENSION",
        ),
        RULES,
    )
    assert decision.derived_tier == "TIER_B_EXTENSION"


def test_mixed_separable_firm_derives_tier_b_with_mapping_review() -> None:
    decision = derive_tier(
        classification(
            customer_value_archetypes=["FUNCTIONAL_SOFTWARE", "ECOMMERCE_RETAIL"],
            firm_structure="MIXED_SEPARABLE",
            commercial_materiality="MATERIAL",
            candidate_tier="TIER_B_EXTENSION",
        ),
        RULES,
    )
    assert decision.derived_tier == "TIER_B_EXTENSION"
    assert "outcome_analysis_requires_segment_mapping" in decision.review_reasons


def test_mixed_nonseparable_firm_is_never_tier_b() -> None:
    # ADR-009: material software inside a nonseparable structure cannot be
    # mapped to firm-level outcomes; it belongs in the Tier C boundary stratum.
    decision = derive_tier(
        classification(
            firm_structure="MIXED_NONSEPARABLE",
            software_centrality="CO_ESSENTIAL",
            commercial_materiality="MATERIAL",
            boundary_flags=["mixed_nonseparable_materiality"],
            candidate_tier="TIER_C_BOUNDARY",
        ),
        RULES,
    )
    assert decision.derived_tier == "TIER_C_BOUNDARY"
    assert decision.needs_manual_review is True
    rule_ids = {t.rule_id for t in decision.rule_trace}
    assert (
        "tier_c_boundary.also_include_if.mixed_nonseparable_without_clean_outcome_mapping"
        in rule_ids
    )


def test_exclusion_provenance_is_recorded() -> None:
    deterministic = derive_tier_for_exclusion(
        "0001000014", "CIK0001000014", ["FUND_OR_INVESTMENT_COMPANY"],
        RULES, "0.1.0", "issuer_filters",
    )
    assert deterministic.exclusion_provenance == "deterministic"
    screen = derive_tier_for_exclusion(
        "0001000020", "CIK0001000020", ["NO_CUSTOMER_FACING_DIGITAL_PRODUCT"],
        RULES, "0.1.0", "screen.likely_ineligible_pending_negative_audit",
        provenance="screen_derived",
    )
    assert screen.exclusion_provenance == "screen_derived"
    economic = derive_tier(
        classification(customer_facing_functional_product=False, candidate_tier="EXCLUDED"),
        RULES,
    )
    assert economic.exclusion_provenance == "economic_classification"


def test_marketplace_and_peripheral_cases_derive_tier_c() -> None:
    marketplace = derive_tier(
        classification(
            customer_value_archetypes=["MARKETPLACE_COORDINATION"],
            software_centrality="ENABLING",
            candidate_tier="TIER_C_BOUNDARY",
        ),
        RULES,
    )
    assert marketplace.derived_tier == "TIER_C_BOUNDARY"

    peripheral_service = derive_tier(
        classification(
            customer_value_archetypes=["HUMAN_MANAGED_SERVICE"],
            software_centrality="PERIPHERAL",
            firm_structure="SOFTWARE_PERIPHERAL",
            commercial_materiality="MINOR",
            candidate_tier="TIER_C_BOUNDARY",
        ),
        RULES,
    )
    assert peripheral_service.derived_tier == "TIER_C_BOUNDARY"


def test_no_customer_facing_product_is_excluded_with_reason() -> None:
    decision = derive_tier(
        classification(customer_facing_functional_product=False, candidate_tier="EXCLUDED"),
        RULES,
    )
    assert decision.derived_tier == "EXCLUDED"
    assert "NO_CUSTOMER_FACING_DIGITAL_PRODUCT" in decision.exclusion_reason_codes


def test_unknown_axes_remain_uncertain_never_coerced() -> None:
    decision = derive_tier(
        classification(
            customer_value_archetypes=["OTHER"],
            software_centrality="UNKNOWN",
            firm_structure="UNKNOWN",
            commercial_materiality="UNKNOWN",
            customer_facing_functional_product=None,
            candidate_tier="UNCERTAIN",
            confidence="low",
        ),
        RULES,
    )
    assert decision.derived_tier == "UNCERTAIN"
    assert "insufficient_baseline_evidence" in decision.uncertain_conditions
    assert "unresolved_materiality" in decision.uncertain_conditions


def test_contradictions_route_to_uncertain() -> None:
    decision = derive_tier(
        classification(contradictions=["archetype conflicts with centrality"]),
        RULES,
    )
    assert decision.derived_tier == "UNCERTAIN"
    assert "contradictory_axis_classification" in decision.uncertain_conditions


def test_advisory_candidate_tier_does_not_drive_derivation() -> None:
    # The classifier proposes Tier A, but the axes only support Tier C.
    decision = derive_tier(
        classification(
            customer_value_archetypes=["CONTENT_CATALOG"],
            software_centrality="ENABLING",
            candidate_tier="TIER_A_CORE",
        ),
        RULES,
    )
    assert decision.derived_tier == "TIER_C_BOUNDARY"


def test_deterministic_exclusion_helper_validates_reason_codes() -> None:
    decision = derive_tier_for_exclusion(
        "0001000013", "CIK0001000013", ["SHELL_OR_PRECOMBINATION_SPAC"],
        RULES, "0.1.0", "issuer_filters",
    )
    assert decision.derived_tier == "EXCLUDED"
    with pytest.raises(ValueError):
        derive_tier_for_exclusion(
            "0001000013", "CIK0001000013", ["NOT_A_REASON"], RULES, "0.1.0", "x"
        )


def test_uncertain_helper_validates_conditions() -> None:
    decision = derive_tier_for_uncertain(
        "0001000016", "CIK0001000016", ["insufficient_baseline_evidence"], RULES, "0.1.0"
    )
    assert decision.derived_tier == "UNCERTAIN"
    with pytest.raises(ValueError):
        derive_tier_for_uncertain(
            "0001000016", "CIK0001000016", ["not_a_condition"], RULES, "0.1.0"
        )


def test_every_decision_records_config_version_and_hash() -> None:
    decision = derive_tier(classification(), RULES)
    assert decision.sample_rules_version == str(RULES.config["rules_version"])
    assert decision.sample_rules_hash == RULES.config_hash
