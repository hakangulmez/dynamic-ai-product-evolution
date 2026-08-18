"""Dev30-only Item 1 locator tests -- fully offline, synthetic fixtures only.

Nothing here reads the legacy THESIS_REPO checkout (see
tests/dev30/test_item1_locator_ledger.py for the skip-guarded regression that
does). No model is called and no network request is made.
"""

from __future__ import annotations

import hashlib

import pytest

from dynamic_ai_products.dev30.item1_locator import (
    ITEM_ONE_LOCATOR_VERSION,
    REASON_DUPLICATE_MARKER,
    REASON_MISSING_MARKER,
    REASON_REVERSED_OR_EMPTY_BOUNDARY,
    REASON_UTF8_DECODE_FAILED,
    Item1LocatorError,
    locate_item1_span,
)

# Deliberately independent of the module's own (private) marker constants:
# hardcoding the literal text here also verifies the module uses exactly
# this text, rather than merely being consistent with itself.
MARK1 = "### ITEM_1_START ###"
MARK1A = "### ITEM_1A_START ###"


def test_locator_version_is_the_fixed_literal():
    assert ITEM_ONE_LOCATOR_VERSION == "dev30-item1-marker-v1"


def test_exact_extraction_and_provenance_fields():
    text = (
        "Some preamble text.\n\n"
        f"{MARK1}\n"
        "Overview line one.\n"
        "Overview line two.\n"
        "\n"
        f"{MARK1A}\n"
        "Risk factors here.\n"
    )
    raw = text.encode("utf-8")
    expected_start = text.index(MARK1) + len(MARK1)
    expected_end = text.index(MARK1A)

    result = locate_item1_span(raw)

    assert result.item_one_char_start == expected_start
    assert result.item_one_char_end == expected_end
    assert result.span_text == text[expected_start:expected_end]
    expected_hash = hashlib.sha256(result.span_text.encode("utf-8")).hexdigest()
    assert result.source_text_hash == expected_hash
    assert result.legacy_source_id == f"legacy-item1:dev30-v0:{expected_hash}"


def test_boundary_newlines_are_preserved_not_stripped():
    text = f"{MARK1}\nOverview.\n\n{MARK1A}\n"
    result = locate_item1_span(text.encode("utf-8"))
    assert result.span_text.startswith("\n")
    assert result.span_text.endswith("\n")
    assert result.span_text == "\nOverview.\n\n"


def test_no_whitespace_collapse_or_normalization_within_span():
    text = (
        f"{MARK1}\n"
        "Line with trailing spaces.   \n"
        "\n\n"
        "Another line.\n"
        f"{MARK1A}\n"
    )
    raw = text.encode("utf-8")
    decoded = raw.decode("utf-8")
    start = decoded.index(MARK1) + len(MARK1)
    end = decoded.index(MARK1A)

    result = locate_item1_span(raw)

    # Exact equality against a direct, untransformed slice -- proves no
    # strip, whitespace collapse, line-ending conversion, or normalization
    # occurred anywhere in the path.
    assert result.span_text == decoded[start:end]
    assert "trailing spaces.   \n" in result.span_text
    assert "\n\n\n" in result.span_text


def test_utf8_decode_failure_is_refused():
    invalid = b"\x80\x81\x82 not valid utf-8"
    with pytest.raises(Item1LocatorError) as exc_info:
        locate_item1_span(invalid)
    assert exc_info.value.reason == REASON_UTF8_DECODE_FAILED


def test_missing_both_markers_is_refused():
    text = "No markers anywhere in this text."
    with pytest.raises(Item1LocatorError) as exc_info:
        locate_item1_span(text.encode("utf-8"))
    assert exc_info.value.reason == REASON_MISSING_MARKER


def test_missing_one_marker_is_refused():
    text = f"{MARK1}\nOverview only, no closing marker.\n"
    with pytest.raises(Item1LocatorError) as exc_info:
        locate_item1_span(text.encode("utf-8"))
    assert exc_info.value.reason == REASON_MISSING_MARKER


def test_duplicate_marker_is_refused():
    text = f"{MARK1}\nfirst\n{MARK1}\nsecond\n{MARK1A}\n"
    with pytest.raises(Item1LocatorError) as exc_info:
        locate_item1_span(text.encode("utf-8"))
    assert exc_info.value.reason == REASON_DUPLICATE_MARKER


def test_reversed_markers_is_refused():
    # ITEM_1A_START appears before ITEM_1_START in the text.
    text = f"{MARK1A}\ncontent\n{MARK1}\n"
    with pytest.raises(Item1LocatorError) as exc_info:
        locate_item1_span(text.encode("utf-8"))
    assert exc_info.value.reason == REASON_REVERSED_OR_EMPTY_BOUNDARY


def test_empty_boundary_is_refused():
    # Marker 1 immediately followed by marker 1A: zero characters between.
    text = MARK1 + MARK1A
    with pytest.raises(Item1LocatorError) as exc_info:
        locate_item1_span(text.encode("utf-8"))
    assert exc_info.value.reason == REASON_REVERSED_OR_EMPTY_BOUNDARY


def test_error_reason_is_one_of_exactly_four_values():
    with pytest.raises(ValueError):
        Item1LocatorError("not_a_real_reason", "message")


def test_never_produces_a_stage00c_style_identity():
    text = f"{MARK1}\nOverview.\n{MARK1A}\n"
    result = locate_item1_span(text.encode("utf-8"))
    assert not result.legacy_source_id.startswith("sec-primary:")
    assert result.legacy_source_id.startswith("legacy-item1:dev30-v0:")
    assert not hasattr(result, "source_id")
