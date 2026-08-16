"""Typed data models for the Stage 00 company-universe sentinel.

The pydantic models here are working representations. Canonical governance
lives in the JSON schemas under `schemas/`; records exported by the runner are
additionally validated against those schemas (see `classification.py` and
`freeze.py`). Unknown is always representable and never coerced.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .identifiers import company_id_for_cik, normalize_accession, normalize_cik
from . import taxonomy

Archetype = Literal[
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
]
Centrality = Literal["CORE", "CO_ESSENTIAL", "ENABLING", "PERIPHERAL", "UNKNOWN"]
Dependency = Literal[
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
]
FirmStructure = Literal[
    "PURE_PLAY",
    "SOFTWARE_DOMINANT",
    "MIXED_SEPARABLE",
    "MIXED_NONSEPARABLE",
    "SOFTWARE_PERIPHERAL",
    "UNKNOWN",
]
Materiality = Literal["DOMINANT", "MATERIAL", "MINOR", "UNKNOWN"]
ScreenStatus = Literal["LIKELY_ELIGIBLE", "LIKELY_INELIGIBLE", "BOUNDARY_OR_UNCERTAIN"]
Tier = Literal["TIER_A_CORE", "TIER_B_EXTENSION", "TIER_C_BOUNDARY", "EXCLUDED", "UNCERTAIN"]
Confidence = Literal["high", "medium", "low"]
ReviewStatus = Literal["unreviewed", "approved", "overridden", "ambiguous", "ontology_question"]
RuleResult = Literal["pass", "fail", "unknown", "not_applicable"]
ExclusionReason = Literal[
    "FUND_OR_INVESTMENT_COMPANY",
    "ASSET_BACKED_ISSUER",
    "TRUST_WITHOUT_OPERATING_BUSINESS",
    "SHELL_OR_PRECOMBINATION_SPAC",
    "NO_ELIGIBLE_ANNUAL_OPERATING_FILING",
    "DUPLICATE_ISSUER_RECORD",
    "NO_CUSTOMER_FACING_DIGITAL_PRODUCT",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceRef(StrictModel):
    """A claim tied to a dated source passage with a direct quote."""

    claim: str
    source_id: str
    passage_id: str
    quote: str


class IssuerStatusFlags(StrictModel):
    """Dated cover-page/registration status flags. None means unresolved."""

    investment_company: Optional[bool] = None
    asset_backed_issuer: Optional[bool] = None
    non_operating_trust: Optional[bool] = None
    shell_company: Optional[bool] = None
    blank_check_precombination: Optional[bool] = None


class HistoricalAnnualFiler(StrictModel):
    """One candidate row of the historical annual-filer frame."""

    cik: str
    canonical_name: str
    former_names: list[str] = Field(default_factory=list)
    accession_number: Optional[str] = None
    filing_date: Optional[date] = None
    fiscal_year_end: Optional[date] = None
    form: Optional[str] = None
    sic: Optional[str] = None
    exchange: Optional[str] = None
    ticker: Optional[str] = None
    source_ids: list[str] = Field(default_factory=list)
    issuer_status_flags: IssuerStatusFlags = Field(default_factory=IssuerStatusFlags)
    baseline_status: Literal[
        "baseline_candidate", "post_baseline_entrant", "no_eligible_filing", "unknown"
    ] = "unknown"
    notes: Optional[str] = None

    @field_validator("cik")
    @classmethod
    def _norm_cik(cls, value: str) -> str:
        return normalize_cik(value)

    @field_validator("accession_number")
    @classmethod
    def _norm_accession(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else normalize_accession(value)

    @property
    def company_id(self) -> str:
        return company_id_for_cik(self.cik)


class IssuerFilterDecision(StrictModel):
    """Deterministic issuer-cleaning decision with reason codes and evidence."""

    cik: str
    company_id: str
    decision: Literal["include", "exclude", "unknown"]
    reason_codes: list[ExclusionReason] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _exclusions_need_reasons_and_evidence(self) -> "IssuerFilterDecision":
        if self.decision == "exclude":
            if not self.reason_codes:
                raise ValueError("Exclusion requires at least one reason code.")
            if not self.evidence:
                raise ValueError("Exclusion requires evidence references.")
        return self


class EvidencePassage(StrictModel):
    """One temporally dated, addressable source passage."""

    passage_id: str
    source_id: str
    section: str
    publication_date: date
    text: str

    @field_validator("section")
    @classmethod
    def _known_section(cls, value: str) -> str:
        if value not in taxonomy.PACKET_SECTIONS:
            raise ValueError(f"Unknown packet section: {value}")
        return value


class TemporalLeakageError(ValueError):
    """A passage dated after the baseline cutoff was offered for a baseline packet."""


class BaselineEvidencePacket(StrictModel):
    """Compact baseline evidence packet for one candidate firm.

    Construction fails on any passage dated after the baseline cutoff:
    post-cutoff evidence may never support a baseline observation.
    """

    packet_id: str
    cik: str
    company_id: str
    baseline_cutoff: date
    baseline_accession: Optional[str] = None
    baseline_filing_date: Optional[date] = None
    passages: list[EvidencePassage] = Field(default_factory=list)
    missing_sections: list[str] = Field(default_factory=list)
    insufficient_evidence: bool = False

    @model_validator(mode="after")
    def _validate_temporal_and_missing(self) -> "BaselineEvidencePacket":
        for passage in self.passages:
            if passage.publication_date > self.baseline_cutoff:
                raise TemporalLeakageError(
                    f"Passage {passage.passage_id} dated {passage.publication_date} "
                    f"is after baseline cutoff {self.baseline_cutoff}."
                )
        present = {p.section for p in self.passages}
        expected_missing = sorted(set(taxonomy.PACKET_SECTIONS) - present)
        if sorted(self.missing_sections) != expected_missing:
            raise ValueError(
                "missing_sections must exactly list the absent packet sections; "
                f"expected {expected_missing}, got {sorted(self.missing_sections)}."
            )
        return self

    def find_quote(self, quote: str) -> Optional[EvidencePassage]:
        for passage in self.passages:
            if quote in passage.text:
                return passage
        return None


class SourcePassage(StrictModel):
    """One normalized passage addressed back to raw source bytes.

    Distinct from :class:`EvidencePassage`, which carries a publication date
    and no byte provenance. ``source_id`` is a stable identity for the
    document — ``sec-primary:<cik>:<accession>:<selected_document>`` — and
    deliberately never the raw SHA-256, so a passage identity survives a
    re-download of identical content and an unrelated edit elsewhere in the
    document. The raw hash is carried separately on the packet.
    """

    passage_id: str
    source_id: str
    section: str
    text: str
    text_hash: str
    byte_start: int
    byte_end: int
    normalizer_version: str

    @field_validator("section")
    @classmethod
    def _known_section(cls, value: str) -> str:
        if value not in taxonomy.PACKET_SECTIONS:
            raise ValueError(f"Unknown packet section: {value}")
        return value


class UniverseBaselinePacket(StrictModel):
    """A Stage 00C baseline evidence packet built from a primary document.

    Carries its own provenance: which document it was cut from, the hash of
    those bytes, how that document was selected, and which route-validation
    evidence exists — recorded separately, because a passing route probe
    proves a URL grammar, never that *this* firm's document was chosen
    correctly.

    ``packet_sha256`` is computed over the canonical JSON serialization of
    this record with the ``packet_sha256`` field itself omitted:
    ``json.dumps(payload, sort_keys=True, separators=(",", ":"),
    ensure_ascii=False).encode("utf-8")``.
    """

    packet_contract: str
    cik: str
    company_id: str
    stratum: str
    accession: str
    form: str
    baseline_filing_date: date
    baseline_cutoff: date
    baseline_cutoff_source: dict
    source_id: str
    source_sha256: str
    source_byte_length: int
    selection_provenance: dict
    route_validation: dict
    item_one_start: int
    item_one_end: int
    end_boundary_kind: str
    passages: list[SourcePassage] = Field(default_factory=list)
    issuer_status_flags: IssuerStatusFlags = Field(default_factory=IssuerStatusFlags)
    issuer_status_basis: str
    missing_sections: list[str] = Field(default_factory=list)
    parse_status: str
    normalization_ledger: dict
    packet_byte_size: int
    packet_sha256: str


class PacketBuildFailure(StrictModel):
    """A packet that could not be built. Recorded, never an exclusion."""

    cik: str
    company_id: str
    accession: str
    form: str
    source_id: str
    reason_code: str
    detail: str


class PacketFailure(StrictModel):
    """A packet that could not be constructed. Never silently dropped."""

    cik: str
    company_id: str
    reason_code: Literal["TEMPORAL_LEAKAGE", "NO_PASSAGES", "INVALID_PASSAGE"]
    detail: str


class ScreenEvidence(StrictModel):
    source_id: str
    passage_id: str
    quote: str
    supported_claim: str


class HighRecallScreenOutput(StrictModel):
    """Validated output of the high-recall screen (mock provider in Phase 0)."""

    cik: str
    company_id: str
    screen_status: ScreenStatus
    plausible_customer_facing_digital_product: Optional[bool] = None
    candidate_customer_value_archetypes: list[Archetype] = Field(default_factory=list)
    positive_evidence: list[ScreenEvidence] = Field(default_factory=list)
    negative_or_boundary_evidence: list[ScreenEvidence] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    confidence: Confidence

    @model_validator(mode="after")
    def _eligible_needs_evidence(self) -> "HighRecallScreenOutput":
        if self.screen_status == "LIKELY_ELIGIBLE" and not self.positive_evidence:
            raise ValueError("LIKELY_ELIGIBLE requires at least one positive evidence quote.")
        return self


class RuleTraceEntry(StrictModel):
    rule_id: str
    result: RuleResult
    detail: Optional[str] = None


class UniverseClassification(StrictModel):
    """Multi-axis classification record mirroring the canonical JSON schema."""

    classification_id: str
    company_id: str
    cik: str
    baseline_accession: Optional[str] = None
    baseline_filing_date: date
    baseline_cutoff: date
    customer_value_archetypes: list[Archetype] = Field(min_length=1)
    software_centrality: Centrality
    complementary_dependencies: list[Dependency] = Field(default_factory=list)
    firm_structure: FirmStructure
    commercial_materiality: Materiality
    customer_facing_functional_product: Optional[bool] = None
    operating_company: Optional[bool] = None
    economically_eligible: Optional[bool] = None
    data_eligible: Optional[bool] = None
    screen_status: Optional[ScreenStatus] = None
    candidate_tier: Tier
    boundary_flags: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    rule_trace: list[RuleTraceEntry] = Field(default_factory=list)
    confidence: Confidence
    review_status: ReviewStatus
    taxonomy_version: str
    sample_rules_version: Optional[str] = None
    schema_version: str


class TierDecision(StrictModel):
    """Deterministic sample-tier derivation output with a full rule trace."""

    cik: str
    company_id: str
    classification_id: Optional[str] = None
    derived_tier: Tier
    exclusion_provenance: Optional[
        Literal["deterministic", "screen_derived", "economic_classification"]
    ] = None
    exclusion_reason_codes: list[ExclusionReason] = Field(default_factory=list)
    uncertain_conditions: list[str] = Field(default_factory=list)
    needs_manual_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    rule_trace: list[RuleTraceEntry] = Field(default_factory=list)
    sample_rules_version: str
    sample_rules_hash: str
    taxonomy_version: str

    @model_validator(mode="after")
    def _trace_required(self) -> "TierDecision":
        if not self.rule_trace:
            raise ValueError("Every tier decision requires a machine-readable rule trace.")
        if self.derived_tier == "EXCLUDED" and not self.exclusion_reason_codes:
            raise ValueError("EXCLUDED requires at least one reason code.")
        if self.derived_tier == "EXCLUDED" and self.exclusion_provenance is None:
            raise ValueError(
                "EXCLUDED requires exclusion_provenance "
                "(deterministic, screen_derived, or economic_classification)."
            )
        return self


class BoundaryReviewCase(StrictModel):
    """One queued boundary-review case. The raw model output is never edited."""

    case_id: str
    cik: str
    company_id: str
    classification_id: Optional[str] = None
    trigger_reasons: list[str] = Field(min_length=1)
    classifier_summary: Optional[str] = None
    derived_tier: Optional[Tier] = None
    conflicting_evidence: list[EvidenceRef] = Field(default_factory=list)
    source_passage_ids: list[str] = Field(default_factory=list)
    suggested_review_question: str
    status: Literal["open", "resolved"] = "open"


class AdjudicationRecord(StrictModel):
    """Append-only human adjudication. Never overwrites the raw outputs."""

    adjudication_id: str
    case_id: str
    decision: Literal[
        "CONFIRM_CLASSIFIER",
        "OVERRIDE_CLASSIFIER",
        "CONFIRM_RULE_TIER",
        "OVERRIDE_RULE_TIER",
        "REMAIN_UNCERTAIN",
        "ONTOLOGY_CHANGE_REQUIRED",
    ]
    final_candidate_tier: Tier
    reason_codes: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    reviewer: str
    review_comment: str
    confidence: Confidence
    recorded_at: Optional[datetime] = None


class FirmYearEligibility(StrictModel):
    """One firm-year eligibility record mirroring the canonical schema."""

    firm_year_id: str
    company_id: str
    cik: str
    observation_date: date
    annual_accession: Optional[str] = None
    filing_form: str
    universe_version: Optional[str] = None
    universe_class_at_date: Optional[Tier] = None
    operating_status: Literal[
        "operating", "acquired", "merged", "bankrupt", "liquidated", "shell", "unknown"
    ]
    public_status: Literal[
        "listed", "delisted", "private_after_transaction", "reporting_only", "unknown"
    ]
    entry_type: Literal[
        "baseline_incumbent", "ipo", "direct_listing", "de_spac", "spin_off",
        "new_filer", "none", "unknown",
    ] = "unknown"
    exit_type: Literal[
        "acquisition", "merger", "delisting", "bankruptcy", "liquidation",
        "cessation_of_reporting", "none", "unknown",
    ] = "none"
    eligible_this_year: Optional[bool] = None
    primary_incumbent: bool
    dynamic_entrant: bool
    evidence_source_ids: list[str] = Field(default_factory=list)
    schema_version: str


class FirmLineage(StrictModel):
    """Dated lineage relation mirroring the canonical schema."""

    lineage_id: str
    company_id: str
    related_company_id: str
    relationship: Literal[
        "predecessor", "successor", "acquirer", "target", "spin_off_parent",
        "spin_off_child", "name_change", "ticker_change",
        "share_class_same_issuer", "other",
    ]
    effective_date: date
    end_date: Optional[date] = None
    evidence_source_id: str
    notes: Optional[str] = None
    schema_version: str
