"""Canonical taxonomy constants for the company universe.

These constants mirror `configs/universe_taxonomy.yaml` and the enums in
`schemas/company_universe_classification.schema.json`. A test asserts that the
code constants and the config file stay identical; the YAML file remains the
governance source of truth and must not be edited from code.
"""

from __future__ import annotations

from pathlib import Path

import yaml

CUSTOMER_VALUE_ARCHETYPES = (
    "FUNCTIONAL_SOFTWARE",
    "ADAPTIVE_DIGITAL_SERVICE",
    "DATA_ANALYTICS_PRODUCT",
    "TRANSACTION_INFRASTRUCTURE",
    "MARKETPLACE_COORDINATION",
    "CONTENT_CATALOG",
    "ATTENTION_SOCIAL_PLATFORM",
    "INTERACTIVE_ENTERTAINMENT",
    "HARDWARE_SOFTWARE_SYSTEM",
    "HUMAN_MANAGED_SERVICE",
    "ECOMMERCE_RETAIL",
    "PHYSICAL_SERVICE_NETWORK",
    "OTHER",
)

SOFTWARE_CENTRALITY = ("CORE", "CO_ESSENTIAL", "ENABLING", "PERIPHERAL", "UNKNOWN")

COMPLEMENTARY_DEPENDENCIES = (
    "NONE_OR_STANDARD_COMPUTE",
    "CUSTOMER_DATA",
    "FIRM_PROPRIETARY_DATA",
    "LICENSED_DATA",
    "LICENSED_CONTENT",
    "NETWORK_OR_INSTALLED_BASE",
    "REGULATED_TRANSACTION_RAIL",
    "EXECUTION_PERMISSIONS",
    "HARDWARE_OR_DEVICE",
    "PHYSICAL_SUPPLY_NETWORK",
    "LIVE_HUMAN_LABOR",
    "SPECIALIZED_NON_LLM_ENGINE",
    "OTHER",
)

FIRM_STRUCTURE = (
    "PURE_PLAY",
    "SOFTWARE_DOMINANT",
    "MIXED_SEPARABLE",
    "MIXED_NONSEPARABLE",
    "SOFTWARE_PERIPHERAL",
    "UNKNOWN",
)

COMMERCIAL_MATERIALITY = ("DOMINANT", "MATERIAL", "MINOR", "UNKNOWN")

SCREEN_STATUS = ("LIKELY_ELIGIBLE", "LIKELY_INELIGIBLE", "BOUNDARY_OR_UNCERTAIN")

CANDIDATE_TIERS = (
    "TIER_A_CORE",
    "TIER_B_EXTENSION",
    "TIER_C_BOUNDARY",
    "EXCLUDED",
    "UNCERTAIN",
)

CONFIDENCE = ("high", "medium", "low")

REVIEW_STATUS = ("unreviewed", "approved", "overridden", "ambiguous", "ontology_question")

DETERMINISTIC_EXCLUSION_REASON_CODES = (
    "FUND_OR_INVESTMENT_COMPANY",
    "ASSET_BACKED_ISSUER",
    "TRUST_WITHOUT_OPERATING_BUSINESS",
    "SHELL_OR_PRECOMBINATION_SPAC",
    "NO_ELIGIBLE_ANNUAL_OPERATING_FILING",
    "DUPLICATE_ISSUER_RECORD",
    "NO_CUSTOMER_FACING_DIGITAL_PRODUCT",
)

ADJUDICATION_DECISIONS = (
    "CONFIRM_CLASSIFIER",
    "OVERRIDE_CLASSIFIER",
    "CONFIRM_RULE_TIER",
    "OVERRIDE_RULE_TIER",
    "REMAIN_UNCERTAIN",
    "ONTOLOGY_CHANGE_REQUIRED",
)

PACKET_SECTIONS = (
    "COVER_PAGE",
    "ITEM1_OVERVIEW",
    "PRODUCTS_SERVICES",
    "CUSTOMERS",
    "SEGMENTS_MATERIALITY",
    "TECHNOLOGY_DELIVERY",
)


def load_taxonomy_config(repo_root: str | Path) -> dict:
    path = Path(repo_root) / "configs" / "universe_taxonomy.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))
