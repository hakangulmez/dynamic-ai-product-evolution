"""Stage 00B deterministic issuer cleaning.

Every exclusion carries a structured reason code and dated evidence. Records
are flagged, never deleted. Unresolved status yields `unknown`, not a guess.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from .models import EvidenceRef, HistoricalAnnualFiler, IssuerFilterDecision

_FLAG_RULES: tuple[tuple[str, str, str], ...] = (
    # (flag attribute, reason code, rule id)
    ("investment_company", "FUND_OR_INVESTMENT_COMPANY", "issuer.fund_or_investment_company"),
    ("asset_backed_issuer", "ASSET_BACKED_ISSUER", "issuer.asset_backed"),
    ("non_operating_trust", "TRUST_WITHOUT_OPERATING_BUSINESS", "issuer.non_operating_trust"),
    ("shell_company", "SHELL_OR_PRECOMBINATION_SPAC", "issuer.shell_company"),
    ("blank_check_precombination", "SHELL_OR_PRECOMBINATION_SPAC", "issuer.blank_check"),
)


def _cover_page_evidence(filer: HistoricalAnnualFiler, claim: str) -> EvidenceRef:
    source_id = filer.source_ids[0] if filer.source_ids else f"fixture:{filer.cik}"
    return EvidenceRef(
        claim=claim,
        source_id=source_id,
        passage_id=f"{filer.cik}-cover",
        quote=claim,
    )


def evaluate_form_scope(
    filer: HistoricalAnnualFiler, form_scope: list[str]
) -> Optional[IssuerFilterDecision]:
    if filer.form in form_scope:
        return None
    return IssuerFilterDecision(
        cik=filer.cik,
        company_id=filer.company_id,
        decision="exclude",
        reason_codes=["NO_ELIGIBLE_ANNUAL_OPERATING_FILING"],
        rule_ids=["issuer.form_scope"],
        evidence=[
            _cover_page_evidence(
                filer,
                f"Filing form {filer.form!r} is outside the eligible scope {form_scope}.",
            )
        ],
    )


def evaluate_issuer_flags(filer: HistoricalAnnualFiler) -> IssuerFilterDecision:
    """Apply cover-page status flags. None flags produce an unknown decision."""
    reasons: list[str] = []
    rule_ids: list[str] = []
    evidence: list[EvidenceRef] = []
    unresolved: list[str] = []

    for attribute, reason, rule_id in _FLAG_RULES:
        value = getattr(filer.issuer_status_flags, attribute)
        if value is True:
            if reason not in reasons:
                reasons.append(reason)
            rule_ids.append(rule_id)
            evidence.append(
                _cover_page_evidence(filer, f"Cover-page status {attribute} is affirmative.")
            )
        elif value is None:
            unresolved.append(attribute)

    if reasons:
        return IssuerFilterDecision(
            cik=filer.cik,
            company_id=filer.company_id,
            decision="exclude",
            reason_codes=reasons,  # type: ignore[arg-type]
            rule_ids=rule_ids,
            evidence=evidence,
        )
    if unresolved:
        return IssuerFilterDecision(
            cik=filer.cik,
            company_id=filer.company_id,
            decision="unknown",
            rule_ids=[f"issuer.unresolved:{name}" for name in unresolved],
            notes=f"Unresolved issuer status flags: {', '.join(unresolved)}. Route to review.",
        )
    return IssuerFilterDecision(
        cik=filer.cik,
        company_id=filer.company_id,
        decision="include",
        rule_ids=["issuer.flags_clear"],
    )


def deduplicate_by_cik(
    filers: list[HistoricalAnnualFiler],
) -> tuple[list[HistoricalAnnualFiler], list[IssuerFilterDecision]]:
    """Keep one baseline record per CIK; flag the rest as duplicates.

    The retained record is the one with the latest filing date (ties broken by
    accession order). Nothing is deleted: every duplicate produces a decision.
    """
    by_cik: dict[str, list[HistoricalAnnualFiler]] = {}
    for filer in filers:
        by_cik.setdefault(filer.cik, []).append(filer)

    kept: list[HistoricalAnnualFiler] = []
    duplicate_decisions: list[IssuerFilterDecision] = []
    for cik in sorted(by_cik):
        group = sorted(
            by_cik[cik],
            key=lambda f: (f.filing_date or date.min, f.accession_number or ""),
            reverse=True,
        )
        kept.append(group[0])
        for duplicate in group[1:]:
            duplicate_decisions.append(
                IssuerFilterDecision(
                    cik=duplicate.cik,
                    company_id=duplicate.company_id,
                    decision="exclude",
                    reason_codes=["DUPLICATE_ISSUER_RECORD"],
                    rule_ids=["issuer.duplicate_cik"],
                    evidence=[
                        _cover_page_evidence(
                            duplicate,
                            "Duplicate issuer record for CIK "
                            f"{duplicate.cik} (ticker {duplicate.ticker!r}); "
                            f"retained accession {group[0].accession_number!r}.",
                        )
                    ],
                )
            )
    return kept, duplicate_decisions


def run_issuer_filters(
    filers: list[HistoricalAnnualFiler], form_scope: list[str]
) -> tuple[list[HistoricalAnnualFiler], list[IssuerFilterDecision]]:
    """Return (candidates passing all deterministic filters, all decisions)."""
    kept, decisions = deduplicate_by_cik(filers)
    passing: list[HistoricalAnnualFiler] = []
    for filer in kept:
        form_decision = evaluate_form_scope(filer, form_scope)
        if form_decision is not None:
            decisions.append(form_decision)
            continue
        flag_decision = evaluate_issuer_flags(filer)
        decisions.append(flag_decision)
        if flag_decision.decision == "include":
            passing.append(filer)
    return passing, decisions
