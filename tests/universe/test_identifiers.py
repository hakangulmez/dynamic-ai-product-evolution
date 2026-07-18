import pytest

from dynamic_ai_products.universe.identifiers import (
    IdentifierError,
    company_id_for_cik,
    normalize_accession,
    normalize_cik,
)


def test_cik_is_zero_padded_to_ten_digits() -> None:
    assert normalize_cik("1750") == "0000001750"
    assert normalize_cik(1750) == "0000001750"
    assert normalize_cik("0000001750") == "0000001750"


def test_equivalent_ciks_normalize_identically() -> None:
    assert normalize_cik("1000001") == normalize_cik("0001000001")


def test_invalid_cik_is_rejected() -> None:
    for bad in ("", "12A45", "0", "12345678901"):
        with pytest.raises(IdentifierError):
            normalize_cik(bad)


def test_accession_normalizes_with_and_without_dashes() -> None:
    canonical = "0001000001-22-000002"
    assert normalize_accession("000100000122000002") == canonical
    assert normalize_accession(canonical) == canonical


def test_invalid_accession_is_rejected() -> None:
    with pytest.raises(IdentifierError):
        normalize_accession("0001-22-01")


def test_company_id_derives_from_normalized_cik() -> None:
    assert company_id_for_cik("1000001") == "CIK0001000001"
