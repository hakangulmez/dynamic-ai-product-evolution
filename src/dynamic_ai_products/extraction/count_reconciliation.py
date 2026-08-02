"""Pure derivation from archived provider bytes (ADR-043, E-M).

Nothing here reaches a network, a clock, an SDK or a filesystem. Every function
takes bytes that have already been written write-once and hash-verified, and
returns a number or refuses. That ordering is the point: a value derived from a
response may not influence the budget or the next request until the response it
came from is durable.

**What the reconciliation does and does not prove.** The independent parser reads
the archived entity body; the SDK witness is the value the SDK produced from the
same body. Agreement therefore proves three things — the archived bytes are the
bytes the SDK parsed, our derivation and the SDK's agree, and nothing mutated
between capture and parse. It does **not** provide two independent observations
of what the server said, and this module does not claim that it does.

**Pricing is exact integer arithmetic.** The canonical unit is microdollar per
token: $0.30 per 1M tokens is 3/10, $2.50 per 1M is 5/2, and each side is rounded
up independently because that is what the declared rule says. Floats are excluded
by construction: ``ceil(a * n / d)`` is float division that loses precision above
2**53. All four values are bound to the verified selections of
``documentation_evidence_validation@0.1.0``.
"""

from __future__ import annotations

import json
from typing import Any

from .errors import ExtractionError

__all__ = [
    "INPUT_DENOMINATOR",
    "INPUT_NUMERATOR",
    "OUTPUT_DENOMINATOR",
    "OUTPUT_NUMERATOR",
    "parse_input_token_count",
    "reconcile_count",
    "reconcile_usage",
    "reserve_cost_microdollars",
    "usage_cost_microdollars",
]

# Verified pricing ratios. Identical to the frozen values in
# documentation_evidence_validation@0.1.0; a drift test compares the two.
INPUT_NUMERATOR = 3
INPUT_DENOMINATOR = 10
OUTPUT_NUMERATOR = 5
OUTPUT_DENOMINATOR = 2

_RAW_TOTAL_TOKENS_KEY = "totalTokens"
_USAGE_KEY = "usageMetadata"
_PROMPT_TOKENS_KEY = "promptTokenCount"
_CANDIDATE_TOKENS_KEY = "candidatesTokenCount"
_THOUGHTS_TOKENS_KEY = "thoughtsTokenCount"


def _refuse(message: str, reason_code: str) -> None:
    raise ExtractionError(message, reason_code=reason_code)


def _require_non_negative_int(value: Any, *, reason_code: str) -> int:
    """Accept a genuine non-negative ``int`` and nothing that merely looks like one.

    ``bool`` is excluded explicitly: ``True == 1`` and ``False == 0`` in Python,
    so a boolean would pass an equality check against a token count. A float is
    excluded for the same class of reason: ``3 == 3.0``.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _refuse("a token count must be a non-negative integer", reason_code)
    return int(value)


def _loads_no_duplicates(raw_bytes: Any, *, reason_code: str) -> Any:
    """Decode JSON, refusing duplicate member names.

    ``json.loads`` silently keeps the last of two identical member names, so a
    body carrying ``totalTokens`` twice would parse to whichever the server put
    second. Here it is a refusal.
    """
    if not isinstance(raw_bytes, (bytes, bytearray)) or not raw_bytes:
        _refuse("the archived response body must be non-empty bytes", reason_code)
    try:
        text = bytes(raw_bytes).decode("utf-8")
    except UnicodeDecodeError:
        _refuse("the archived response body is not valid UTF-8", reason_code)

    def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: dict[str, Any] = {}
        for key, value in pairs:
            if key in seen:
                _refuse("the archived response body carries a duplicate member", reason_code)
            seen[key] = value
        return seen

    try:
        return json.loads(text, object_pairs_hook=_pairs)
    except ValueError:
        _refuse("the archived response body is not valid JSON", reason_code)


def parse_input_token_count(raw_bytes: bytes) -> int:
    """Derive the input token count from the archived ``countTokens`` body.

    Pure: no SDK object is consulted. The member name read here is the **wire**
    name; the SDK exposes the same value under a snake_case attribute, which is
    what makes the two derivations distinguishable code paths over one artifact.
    """
    document = _loads_no_duplicates(raw_bytes, reason_code="count_parse_failed")
    if not isinstance(document, dict):
        _refuse("the archived count response is not a JSON object", "count_parse_failed")
    if _RAW_TOTAL_TOKENS_KEY not in document:
        _refuse("the archived count response declares no total", "count_parse_failed")
    return _require_non_negative_int(
        document[_RAW_TOTAL_TOKENS_KEY], reason_code="count_parse_failed"
    )


def reconcile_count(*, parsed: int, sdk_witness: Any) -> int:
    """Refuse unless the archived-byte derivation and the SDK witness agree."""
    witness = _require_non_negative_int(
        sdk_witness, reason_code="count_reconciliation_mismatch"
    )
    parsed_value = _require_non_negative_int(parsed, reason_code="count_parse_failed")
    if parsed_value != witness:
        _refuse(
            "the archived count and the provider's own witness disagree",
            "count_reconciliation_mismatch",
        )
    return parsed_value


def _ceil_div(numerator: int, denominator: int) -> int:
    """Exact integer ceiling. ``ceil(a / b)`` in floats would lose precision."""
    return (numerator + denominator - 1) // denominator


def usage_cost_microdollars(*, input_tokens: int, output_tokens: int) -> int:
    """Cost of one call in microdollar, each side rounded up independently.

    Summing first and rounding once would be a different rule than the one the
    published table states.
    """
    tokens_in = _require_non_negative_int(input_tokens, reason_code="usage_invalid")
    tokens_out = _require_non_negative_int(output_tokens, reason_code="usage_invalid")
    return _ceil_div(tokens_in * INPUT_NUMERATOR, INPUT_DENOMINATOR) + _ceil_div(
        tokens_out * OUTPUT_NUMERATOR, OUTPUT_DENOMINATOR
    )


def reserve_cost_microdollars(
    *, measured_input_tokens: int, max_output_tokens: int, generate_attempt_cap: int
) -> int:
    """The pre-call ceiling, multiplied by the generate cap.

    ``countTokens`` measures the **input** only; there is no measurement of the
    output, only the declared ``max_output_tokens`` bound, so this is a ceiling
    and never an estimate. A retry re-sends the same input, so a run that may
    attempt three times must be able to pay three times.
    """
    cap = _require_non_negative_int(generate_attempt_cap, reason_code="budget_insufficient")
    if cap < 1:
        _refuse("a generate attempt cap of zero authorizes nothing", "budget_insufficient")
    per_attempt = usage_cost_microdollars(
        input_tokens=measured_input_tokens, output_tokens=max_output_tokens
    )
    return cap * per_attempt


def reconcile_usage(*, raw_bytes: bytes, admitted_input_tokens: int) -> dict[str, Any]:
    """Reconcile the generation response's usage block after the fact.

    Three outcomes, and only three. ``verified`` when the reported prompt count
    equals the admitted count and, under a zero thinking budget, the thoughts
    count is absent or a strict zero. ``unknown`` when the usage block or the
    prompt count is simply not there — the run completed, the measurement did
    not. ``invalid`` when usage is malformed, the prompt count disagrees, or a
    non-zero thoughts count contradicts the budget that was sent.

    The archived bytes survive every outcome. A disagreement is a reason to
    refuse a claim, never a reason to destroy the evidence for it.
    """
    admitted = _require_non_negative_int(admitted_input_tokens, reason_code="usage_invalid")
    try:
        document = _loads_no_duplicates(raw_bytes, reason_code="usage_invalid")
    except ExtractionError:
        return {"measurement_status": "invalid", "usage_reason": "usage_body_unparsable"}
    if not isinstance(document, dict):
        return {"measurement_status": "invalid", "usage_reason": "usage_body_unparsable"}
    if _USAGE_KEY not in document:
        return {"measurement_status": "unknown", "usage_reason": "usage_absent"}
    usage = document[_USAGE_KEY]
    if not isinstance(usage, dict):
        return {"measurement_status": "invalid", "usage_reason": "usage_malformed"}
    if _PROMPT_TOKENS_KEY not in usage:
        return {"measurement_status": "unknown", "usage_reason": "prompt_count_absent"}
    prompt = usage[_PROMPT_TOKENS_KEY]
    if isinstance(prompt, bool) or not isinstance(prompt, int) or prompt < 0:
        return {"measurement_status": "invalid", "usage_reason": "usage_malformed"}
    if prompt != admitted:
        return {"measurement_status": "invalid", "usage_reason": "prompt_count_mismatch"}
    thoughts = usage.get(_THOUGHTS_TOKENS_KEY)
    if thoughts is not None:
        if isinstance(thoughts, bool) or not isinstance(thoughts, int) or thoughts < 0:
            return {"measurement_status": "invalid", "usage_reason": "usage_malformed"}
        if thoughts != 0:
            # thinking_budget was sent as zero. A non-zero thoughts count means
            # the request that was billed is not the request that was declared.
            return {"measurement_status": "invalid", "usage_reason": "thoughts_present"}
    candidates = usage.get(_CANDIDATE_TOKENS_KEY, 0)
    if isinstance(candidates, bool) or not isinstance(candidates, int) or candidates < 0:
        return {"measurement_status": "invalid", "usage_reason": "usage_malformed"}
    billed_output = candidates + (thoughts or 0)
    return {
        "measurement_status": "verified",
        "usage_reason": "usage_verified",
        "prompt_token_count": prompt,
        "billed_output_tokens": billed_output,
        "actual_cost_microdollars": usage_cost_microdollars(
            input_tokens=prompt, output_tokens=billed_output
        ),
    }
