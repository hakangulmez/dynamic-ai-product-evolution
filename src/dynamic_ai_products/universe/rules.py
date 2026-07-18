"""Stage 00F deterministic tier derivation.

`configs/universe_sample_rules.yaml` is the single source of truth for sample
membership. The classifier's `candidate_tier` is advisory only; a rule trace
records every evaluated rule. Evaluation order:

    deterministic EXCLUDED -> UNCERTAIN conditions -> Tier A -> Tier B
    -> Tier C -> fallback UNCERTAIN

Per ADR-009 (rules 0.2.0), MIXED_NONSEPARABLE firms are not Tier B candidates;
they route to the Tier C boundary stratum or manual review.

Exclusions carry provenance (ADR-010): deterministic issuer exclusions are
definitive; screen-derived exclusions are provisional until the negative
audit completes; economic exclusions come from the full classification.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .io_utils import sha256_file
from .models import (
    RuleTraceEntry,
    TierDecision,
    UniverseClassification,
)


class SampleRules:
    """Versioned, hashed view of the sample-rule configuration."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.config = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        self.version: str = str(self.config["rules_version"])
        self.config_hash: str = sha256_file(self.path)

    @property
    def tier_a(self) -> dict:
        return self.config["tier_a_core"]

    @property
    def tier_b(self) -> dict:
        return self.config["tier_b_extension"]

    @property
    def tier_c(self) -> dict:
        return self.config["tier_c_boundary"]

    @property
    def exclusion_reason_codes(self) -> list[str]:
        return list(self.config["excluded"]["deterministic_reason_codes"])

    @property
    def uncertain_conditions(self) -> list[str]:
        return list(self.config["uncertain"]["conditions"])


def _trace(rule_id: str, result: str, detail: str | None = None) -> RuleTraceEntry:
    return RuleTraceEntry(rule_id=rule_id, result=result, detail=detail)


def derive_tier_for_exclusion(
    cik: str,
    company_id: str,
    reason_codes: list[str],
    rules: SampleRules,
    taxonomy_version: str,
    source_rule_id: str,
    provenance: str = "deterministic",
) -> TierDecision:
    """Tier decision for a firm excluded before or without classification."""
    unknown_codes = sorted(set(reason_codes) - set(rules.exclusion_reason_codes))
    if unknown_codes:
        raise ValueError(f"Reason codes not in the rule config: {unknown_codes}")
    return TierDecision(
        cik=cik,
        company_id=company_id,
        derived_tier="EXCLUDED",
        exclusion_provenance=provenance,  # type: ignore[arg-type]
        exclusion_reason_codes=reason_codes,  # type: ignore[arg-type]
        rule_trace=[
            _trace(source_rule_id, "pass", f"reason_codes={sorted(set(reason_codes))}")
        ],
        sample_rules_version=rules.version,
        sample_rules_hash=rules.config_hash,
        taxonomy_version=taxonomy_version,
    )


def derive_tier_for_uncertain(
    cik: str,
    company_id: str,
    conditions: list[str],
    rules: SampleRules,
    taxonomy_version: str,
    classification_id: str | None = None,
) -> TierDecision:
    """Tier decision for a firm that cannot be classified (e.g. packet failure)."""
    unknown = sorted(set(conditions) - set(rules.uncertain_conditions))
    if unknown:
        raise ValueError(f"Uncertain conditions not in the rule config: {unknown}")
    return TierDecision(
        cik=cik,
        company_id=company_id,
        classification_id=classification_id,
        derived_tier="UNCERTAIN",
        uncertain_conditions=conditions,
        rule_trace=[_trace(f"uncertain.{c}", "pass") for c in conditions],
        sample_rules_version=rules.version,
        sample_rules_hash=rules.config_hash,
        taxonomy_version=taxonomy_version,
    )


def _uncertain_conditions_for(record: UniverseClassification) -> list[str]:
    conditions: list[str] = []
    if record.customer_facing_functional_product is None:
        conditions.append("insufficient_baseline_evidence")
    if record.operating_company is None:
        conditions.append("unresolved_operating_status")
    if record.contradictions:
        conditions.append("contradictory_axis_classification")
    if record.commercial_materiality == "UNKNOWN":
        conditions.append("unresolved_materiality")
    if record.software_centrality == "UNKNOWN" and "insufficient_baseline_evidence" not in conditions:
        conditions.append("insufficient_baseline_evidence")
    return conditions


def derive_tier(
    record: UniverseClassification,
    rules: SampleRules,
    deterministic_exclusion_codes: list[str] | None = None,
) -> TierDecision:
    """Derive the sample tier for one classified firm from the rule config only."""
    trace: list[RuleTraceEntry] = []
    review_reasons: list[str] = []

    # 1. Deterministic exclusions dominate everything.
    codes = list(deterministic_exclusion_codes or [])
    if record.customer_facing_functional_product is False:
        codes.append("NO_CUSTOMER_FACING_DIGITAL_PRODUCT")
        trace.append(
            _trace(
                "excluded.no_customer_facing_digital_product",
                "pass",
                "Classification found no customer-facing digital product.",
            )
        )
    if codes:
        base = derive_tier_for_exclusion(
            record.cik,
            record.company_id,
            sorted(set(codes)),
            rules,
            record.taxonomy_version,
            "excluded.deterministic_reason_codes",
            provenance="economic_classification",
        )
        return base.model_copy(
            update={
                "classification_id": record.classification_id,
                "rule_trace": trace + base.rule_trace,
            }
        )

    # 2. Uncertain conditions from the versioned config.
    uncertain = _uncertain_conditions_for(record)
    if uncertain:
        decision = derive_tier_for_uncertain(
            record.cik,
            record.company_id,
            uncertain,
            rules,
            record.taxonomy_version,
            classification_id=record.classification_id,
        )
        return decision.model_copy(update={"rule_trace": trace + decision.rule_trace})

    archetypes = set(record.customer_value_archetypes)

    # 3. Tier A.
    a = rules.tier_a
    a_checks: list[tuple[str, bool, str]] = [
        ("tier_a_core.operating_company_required", record.operating_company is True,
         f"operating_company={record.operating_company}"),
        ("tier_a_core.baseline_annual_filing_required", record.baseline_filing_date is not None,
         f"baseline_filing_date={record.baseline_filing_date}"),
        ("tier_a_core.customer_facing_functional_product_required",
         record.customer_facing_functional_product is True,
         f"customer_facing_functional_product={record.customer_facing_functional_product}"),
        ("tier_a_core.allowed_archetypes", bool(archetypes & set(a["allowed_archetypes"])),
         f"archetypes={sorted(archetypes)}"),
        ("tier_a_core.allowed_software_centrality",
         record.software_centrality in a["allowed_software_centrality"],
         f"software_centrality={record.software_centrality}"),
        ("tier_a_core.allowed_firm_structure",
         record.firm_structure in a["allowed_firm_structure"],
         f"firm_structure={record.firm_structure}"),
        ("tier_a_core.allowed_materiality",
         record.commercial_materiality in a["allowed_materiality"],
         f"commercial_materiality={record.commercial_materiality}"),
    ]
    a_pass = True
    for rule_id, ok, detail in a_checks:
        trace.append(_trace(rule_id, "pass" if ok else "fail", detail))
        a_pass = a_pass and ok

    if a_pass:
        for trigger in a.get("manual_review_if", []):
            hit = False
            if trigger == "software_centrality_is_CO_ESSENTIAL":
                hit = record.software_centrality == "CO_ESSENTIAL"
            elif trigger == "multiple_material_archetypes":
                hit = len(archetypes) > 1
            elif trigger == "contradictory_materiality_evidence":
                hit = bool(record.contradictions)
            elif trigger == "boundary_flag_present":
                hit = bool(record.boundary_flags)
            trace.append(
                _trace(f"tier_a_core.manual_review_if.{trigger}", "pass" if hit else "not_applicable")
            )
            if hit:
                review_reasons.append(trigger)
        return TierDecision(
            cik=record.cik,
            company_id=record.company_id,
            classification_id=record.classification_id,
            derived_tier="TIER_A_CORE",
            needs_manual_review=bool(review_reasons),
            review_reasons=review_reasons,
            rule_trace=trace,
            sample_rules_version=rules.version,
            sample_rules_hash=rules.config_hash,
            taxonomy_version=record.taxonomy_version,
        )

    # 4. Tier B. Peripheral-software firms fall through to Tier C
    #    (tier_c_boundary.also_include_if.software_centrality_is_PERIPHERAL).
    b = rules.tier_b
    b_ok = (
        bool(archetypes & set(b["candidate_archetypes"]))
        and record.firm_structure in b["candidate_firm_structure"]
        and record.software_centrality != "PERIPHERAL"
        and record.customer_facing_functional_product is True
    )
    trace.append(
        _trace(
            "tier_b_extension.candidate_match",
            "pass" if b_ok else "fail",
            f"archetypes={sorted(archetypes)} structure={record.firm_structure} "
            f"centrality={record.software_centrality}",
        )
    )
    if b_ok:
        if (
            b.get("outcome_analysis_requires_segment_mapping")
            and record.firm_structure == "MIXED_SEPARABLE"
        ):
            review_reasons.append("outcome_analysis_requires_segment_mapping")
        if record.boundary_flags:
            review_reasons.append("boundary_flag_present")
        return TierDecision(
            cik=record.cik,
            company_id=record.company_id,
            classification_id=record.classification_id,
            derived_tier="TIER_B_EXTENSION",
            needs_manual_review=bool(review_reasons),
            review_reasons=review_reasons,
            rule_trace=trace,
            sample_rules_version=rules.version,
            sample_rules_hash=rules.config_hash,
            taxonomy_version=record.taxonomy_version,
        )

    # 5. Tier C.
    c = rules.tier_c
    c_conditions = {
        "tier_c_boundary.default_archetypes": bool(archetypes & set(c["default_archetypes"])),
        "tier_c_boundary.also_include_if.software_centrality_is_ENABLING":
            record.software_centrality == "ENABLING",
        "tier_c_boundary.also_include_if.software_centrality_is_PERIPHERAL":
            record.software_centrality == "PERIPHERAL",
        "tier_c_boundary.also_include_if.firm_structure_is_SOFTWARE_PERIPHERAL":
            record.firm_structure == "SOFTWARE_PERIPHERAL",
        "tier_c_boundary.also_include_if.mixed_nonseparable_without_clean_outcome_mapping":
            record.firm_structure == "MIXED_NONSEPARABLE",
    }
    c_ok = False
    for rule_id, hit in c_conditions.items():
        trace.append(_trace(rule_id, "pass" if hit else "not_applicable"))
        c_ok = c_ok or hit
    if c_ok:
        return TierDecision(
            cik=record.cik,
            company_id=record.company_id,
            classification_id=record.classification_id,
            derived_tier="TIER_C_BOUNDARY",
            needs_manual_review=bool(record.boundary_flags),
            review_reasons=["boundary_flag_present"] if record.boundary_flags else [],
            rule_trace=trace,
            sample_rules_version=rules.version,
            sample_rules_hash=rules.config_hash,
            taxonomy_version=record.taxonomy_version,
        )

    # 6. Fallback: no rule matched — uncertain, never a silent exclusion.
    trace.append(
        _trace(
            "uncertain.contradictory_axis_classification",
            "pass",
            "No tier rule matched the stored axes; routing to review.",
        )
    )
    return TierDecision(
        cik=record.cik,
        company_id=record.company_id,
        classification_id=record.classification_id,
        derived_tier="UNCERTAIN",
        uncertain_conditions=["contradictory_axis_classification"],
        needs_manual_review=True,
        review_reasons=["no_tier_rule_matched"],
        rule_trace=trace,
        sample_rules_version=rules.version,
        sample_rules_hash=rules.config_hash,
        taxonomy_version=record.taxonomy_version,
    )
