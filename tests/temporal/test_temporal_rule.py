from datetime import date

def eligible(publication_date: date, cutoff: date) -> bool:
    return publication_date <= cutoff

def test_future_source_is_ineligible() -> None:
    assert not eligible(date(2025, 1, 1), date(2024, 12, 31))

def test_same_day_source_is_eligible() -> None:
    assert eligible(date(2024, 12, 31), date(2024, 12, 31))
