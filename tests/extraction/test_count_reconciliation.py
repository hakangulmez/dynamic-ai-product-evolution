"""Pure derivation from archived bytes: parsing, reconciliation, and cost.

Nothing here touches a network, a clock, an SDK or a filesystem. The functions
under test are the ones that stand between a persisted response and the budget
decision, and their whole job is to refuse rather than to guess.
"""

from __future__ import annotations

import pytest

from dynamic_ai_products.collection.documentation_evidence_validation import PRICING_UNITS
from dynamic_ai_products.extraction.count_reconciliation import (
    INPUT_DENOMINATOR,
    INPUT_NUMERATOR,
    OUTPUT_DENOMINATOR,
    OUTPUT_NUMERATOR,
    parse_input_token_count,
    reconcile_count,
    reconcile_usage,
    reserve_cost_microdollars,
    usage_cost_microdollars,
)
from dynamic_ai_products.extraction.errors import ExtractionError


def reason(callable_, *args, **kwargs) -> str:
    with pytest.raises(ExtractionError) as caught:
        callable_(*args, **kwargs)
    return caught.value.reason_code


# --- pricing -----------------------------------------------------------------


def test_the_ratios_are_the_ones_the_evidence_record_verified():
    """One set of numbers, checked against the artifact that established them."""
    assert (INPUT_NUMERATOR, INPUT_DENOMINATOR) == (
        PRICING_UNITS["input_numerator"],
        PRICING_UNITS["input_denominator"],
    )
    assert (OUTPUT_NUMERATOR, OUTPUT_DENOMINATOR) == (
        PRICING_UNITS["output_numerator"],
        PRICING_UNITS["output_denominator"],
    )


def test_one_million_of_each_costs_two_dollars_eighty():
    assert usage_cost_microdollars(input_tokens=1_000_000, output_tokens=1_000_000) == 2_800_000


def test_each_side_is_rounded_up_independently():
    """Summing first and rounding once would be a different published rule."""
    assert usage_cost_microdollars(input_tokens=1, output_tokens=0) == 1
    assert usage_cost_microdollars(input_tokens=0, output_tokens=1) == 3
    assert usage_cost_microdollars(input_tokens=1, output_tokens=1) == 4


def test_no_declared_pricing_value_is_a_float():
    for value in (INPUT_NUMERATOR, INPUT_DENOMINATOR, OUTPUT_NUMERATOR, OUTPUT_DENOMINATOR):
        assert isinstance(value, int) and not isinstance(value, bool)


def test_the_reserve_is_a_ceiling_multiplied_by_the_generate_cap():
    per_attempt = usage_cost_microdollars(input_tokens=100_000, output_tokens=8192)
    for cap in (1, 2, 3):
        assert (
            reserve_cost_microdollars(
                measured_input_tokens=100_000, max_output_tokens=8192, generate_attempt_cap=cap
            )
            == cap * per_attempt
        )
    assert reason(
        reserve_cost_microdollars,
        measured_input_tokens=1,
        max_output_tokens=8192,
        generate_attempt_cap=0,
    ) == "budget_insufficient"


# --- parsing -----------------------------------------------------------------


def test_a_well_formed_count_body_parses():
    assert parse_input_token_count(b'{"totalTokens": 42}') == 42


@pytest.mark.parametrize(
    "body",
    [
        b'{"totalTokens": "42"}',
        b'{"totalTokens": 42.0}',
        b'{"totalTokens": true}',
        b'{"totalTokens": -1}',
        b'{"totalTokens": null}',
        b'{"other": 42}',
        b"[42]",
        b"{not json",
        b"",
        b"\xff\xfe",
    ],
)
def test_anything_that_is_not_a_non_negative_integer_total_is_refused(body):
    assert reason(parse_input_token_count, body) == "count_parse_failed"


def test_a_duplicate_member_is_refused_rather_than_silently_resolved():
    """``json.loads`` keeps the last of two identical names; here it is a refusal."""
    assert reason(parse_input_token_count, b'{"totalTokens":1,"totalTokens":2}') == (
        "count_parse_failed"
    )


def test_a_boolean_cannot_masquerade_as_a_count():
    """``True == 1`` in Python, so the check is on type, not on value."""
    assert reason(parse_input_token_count, b'{"totalTokens": true}') == "count_parse_failed"


# --- reconciliation ----------------------------------------------------------


def test_agreement_returns_the_measured_count():
    assert reconcile_count(parsed=42, sdk_witness=42) == 42


def test_disagreement_is_its_own_reason_and_not_a_parse_failure():
    assert reason(reconcile_count, parsed=42, sdk_witness=41) == "count_reconciliation_mismatch"


def test_a_missing_or_ill_typed_witness_is_refused():
    for witness in (None, "42", 42.0, True, -1):
        assert reason(reconcile_count, parsed=42, sdk_witness=witness) == (
            "count_reconciliation_mismatch"
        )


# --- post-generation usage ---------------------------------------------------


def usage(body: bytes, admitted: int = 10):
    return reconcile_usage(raw_bytes=body, admitted_input_tokens=admitted)


def test_matching_prompt_count_with_no_thoughts_is_verified():
    result = usage(b'{"usageMetadata":{"promptTokenCount":10,"candidatesTokenCount":5}}')
    assert result["measurement_status"] == "verified"
    assert result["actual_cost_microdollars"] == usage_cost_microdollars(
        input_tokens=10, output_tokens=5
    )


def test_a_strict_zero_thoughts_count_is_still_verified():
    result = usage(
        b'{"usageMetadata":{"promptTokenCount":10,"candidatesTokenCount":5,'
        b'"thoughtsTokenCount":0}}'
    )
    assert result["measurement_status"] == "verified"


def test_an_absent_usage_block_is_unknown_and_not_invalid():
    """The run completed; the measurement did not. Those are different facts."""
    result = usage(b'{"candidates":[]}')
    assert result["measurement_status"] == "unknown"
    assert "actual_cost_microdollars" not in result


def test_an_absent_prompt_count_is_unknown():
    assert usage(b'{"usageMetadata":{"candidatesTokenCount":5}}')["measurement_status"] == (
        "unknown"
    )


@pytest.mark.parametrize(
    "body, expected_reason",
    [
        (b'{"usageMetadata":{"promptTokenCount":9}}', "prompt_count_mismatch"),
        (b'{"usageMetadata":{"promptTokenCount":10,"thoughtsTokenCount":3}}', "thoughts_present"),
        (b'{"usageMetadata":{"promptTokenCount":"10"}}', "usage_malformed"),
        (b'{"usageMetadata":"not-an-object"}', "usage_malformed"),
        (b'{"usageMetadata":{"promptTokenCount":10,"candidatesTokenCount":-1}}', "usage_malformed"),
        (b"{not json", "usage_body_unparsable"),
    ],
)
def test_every_disagreement_is_invalid_with_its_own_reason(body, expected_reason):
    result = usage(body)
    assert result["measurement_status"] == "invalid"
    assert result["usage_reason"] == expected_reason
    assert "actual_cost_microdollars" not in result


def test_a_nonzero_thoughts_count_contradicts_the_budget_that_was_sent():
    """``thinking_budget`` was zero, so a billed thought count means the request
    that was billed is not the request that was declared."""
    assert usage(b'{"usageMetadata":{"promptTokenCount":10,"thoughtsTokenCount":1}}')[
        "usage_reason"
    ] == "thoughts_present"


def test_an_actual_cost_is_produced_only_from_verified_usage():
    verified = usage(b'{"usageMetadata":{"promptTokenCount":10,"candidatesTokenCount":5}}')
    assert "actual_cost_microdollars" in verified
    for body in (b'{"candidates":[]}', b'{"usageMetadata":{"promptTokenCount":9}}'):
        assert "actual_cost_microdollars" not in usage(body)
