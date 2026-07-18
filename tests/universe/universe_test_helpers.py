"""Shared fixture builders for the universe sentinel tests."""

from dynamic_ai_products.universe.models import HistoricalAnnualFiler


def make_filer(**overrides) -> HistoricalAnnualFiler:
    payload = {
        "cik": "1000001",
        "canonical_name": "Fixture Operating Co",
        "accession_number": "0001000001-22-000001",
        "filing_date": "2022-09-15",
        "form": "10-K",
        "source_ids": ["fixture:src"],
        "issuer_status_flags": {
            "investment_company": False,
            "asset_backed_issuer": False,
            "non_operating_trust": False,
            "shell_company": False,
            "blank_check_precombination": False,
        },
    }
    payload.update(overrides)
    return HistoricalAnnualFiler.model_validate(payload)
