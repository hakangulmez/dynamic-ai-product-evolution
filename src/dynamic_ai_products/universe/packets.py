"""Stage 00C baseline evidence-packet construction from local fixtures.

A packet is only built from passages dated on or before the baseline cutoff.
A post-cutoff passage is a construction failure, recorded and never repaired.
"""

from __future__ import annotations

from datetime import date

from pydantic import ValidationError

from . import taxonomy
from .models import (
    BaselineEvidencePacket,
    EvidencePassage,
    HistoricalAnnualFiler,
    PacketFailure,
    TemporalLeakageError,
)

# Sections whose absence marks the packet as evidence-insufficient for
# economic classification (cover page alone cannot establish a product).
_SUFFICIENCY_SECTIONS = {"ITEM1_OVERVIEW", "PRODUCTS_SERVICES"}


def build_packet(
    filer: HistoricalAnnualFiler,
    raw_passages: list[dict],
    baseline_cutoff: date,
) -> BaselineEvidencePacket | PacketFailure:
    """Build and validate one packet; return a PacketFailure on any violation."""
    if not raw_passages:
        return PacketFailure(
            cik=filer.cik,
            company_id=filer.company_id,
            reason_code="NO_PASSAGES",
            detail="No baseline passages supplied for this candidate.",
        )
    try:
        passages = [EvidencePassage.model_validate(item) for item in raw_passages]
    except ValidationError as exc:
        return PacketFailure(
            cik=filer.cik,
            company_id=filer.company_id,
            reason_code="INVALID_PASSAGE",
            detail=str(exc),
        )

    leaked = [p for p in passages if p.publication_date > baseline_cutoff]
    if leaked:
        return PacketFailure(
            cik=filer.cik,
            company_id=filer.company_id,
            reason_code="TEMPORAL_LEAKAGE",
            detail="; ".join(
                f"Passage {p.passage_id} dated {p.publication_date} is after "
                f"baseline cutoff {baseline_cutoff}."
                for p in leaked
            ),
        )

    present = {p.section for p in passages}
    missing = sorted(set(taxonomy.PACKET_SECTIONS) - present)
    insufficient = bool(_SUFFICIENCY_SECTIONS & set(missing))
    try:
        return BaselineEvidencePacket(
            packet_id=f"packet-{filer.cik}",
            cik=filer.cik,
            company_id=filer.company_id,
            baseline_cutoff=baseline_cutoff,
            baseline_accession=filer.accession_number,
            baseline_filing_date=filer.filing_date,
            passages=passages,
            missing_sections=missing,
            insufficient_evidence=insufficient,
        )
    except (TemporalLeakageError, ValidationError) as exc:
        return PacketFailure(
            cik=filer.cik,
            company_id=filer.company_id,
            reason_code="INVALID_PASSAGE",
            detail=str(exc),
        )


def validate_quotes_resolve(
    packet: BaselineEvidencePacket, quotes: list[str]
) -> list[str]:
    """Return the quotes that do NOT resolve to any packet passage."""
    return [quote for quote in quotes if packet.find_quote(quote) is None]
