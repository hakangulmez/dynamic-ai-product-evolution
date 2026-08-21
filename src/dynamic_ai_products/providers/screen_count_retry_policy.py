"""Count-attempt retry policy for the universe high-recall screen (ADR-118).

**Screen-only, additive, and narrower than the generate policy.** ADR-117 gave
``generateContent`` five attempts at 15s/30s/60s/120s and deliberately left
``countTokens`` as a single un-retried send. A live full-cohort run then died
on exactly that: one 300-second transport timeout measuring the input of row
3,940 discarded 3,939 completed rows. The measurement call is idempotent — it
sends the same rendered prompt and reads a token count — so a bounded retry of
it invents no new evidence and changes no model output.

**What this policy is.** Three total ``countTokens`` attempts per logical row —
the original send plus two retries — with fixed waits of 15s and 30s, no
jitter. It is deliberately shorter than the generate chain: a count failure
costs one cheap call rather than a generation, and the row cannot proceed
without it, so waiting four minutes to measure an input buys little.

**What it is not.** The retry *triggers* are not restated here.
:func:`screen_count_should_retry` **is** the committed
:func:`~dynamic_ai_products.providers.retry_policy.should_retry` object, so the
retryable set stays exactly 408, 429, 500, 502, 503, 504 and a transport
timeout. A validation, capture, governance, binding, schema, quote, budget or
any other terminal failure is outside the predicate by construction.

``countTokens`` must still succeed before ``generateContent`` begins: this
policy bounds how many times the measurement may be attempted, never whether
the generation may proceed without one.
"""

from __future__ import annotations

from .retry_policy import (
    RETRY_TRIGGER_STATUS_CODES,
    RETRY_TRIGGER_TRANSPORT_TIMEOUT,
    should_retry,
)
from .screen_retry_policy import SCREEN_GENERATE_MAX_ATTEMPTS

__all__ = [
    "SCREEN_COUNT_MAX_ATTEMPTS_V2",
    "SCREEN_COUNT_RETRY_DELAYS_SECONDS",
    "SCREEN_COUNT_RETRY_POLICY_VERSION",
    "SCREEN_COUNT_RETRY_TRIGGER_STATUS_CODES",
    "SCREEN_COUNT_RETRY_TRIGGER_TRANSPORT_TIMEOUT",
    "SCREEN_EXTERNAL_REQUESTS_PER_ROW_V2",
    "screen_count_attempt_cap",
    "screen_count_delay_before_attempt",
    "screen_count_should_retry",
    "screen_external_request_cap_v2",
]

#: Named in the continuation authorization and recorded in its manifest, so a
#: grant minted for the un-retried count cannot be executed by this route.
SCREEN_COUNT_RETRY_POLICY_VERSION = "universe_screen_count_retry_policy_v1"

#: Three **total** attempts per logical row: the original send plus two retries.
SCREEN_COUNT_MAX_ATTEMPTS_V2 = 3

#: The two waits between those three attempts, in order, in seconds.
SCREEN_COUNT_RETRY_DELAYS_SECONDS: tuple[int, ...] = (15, 30)

#: The structural per-row external maximum once both chains are bounded:
#: three count attempts plus the unchanged five generate attempts.
SCREEN_EXTERNAL_REQUESTS_PER_ROW_V2 = (
    SCREEN_COUNT_MAX_ATTEMPTS_V2 + SCREEN_GENERATE_MAX_ATTEMPTS
)

#: Re-exported, not restated: the same objects the committed policy declares.
SCREEN_COUNT_RETRY_TRIGGER_STATUS_CODES = RETRY_TRIGGER_STATUS_CODES
SCREEN_COUNT_RETRY_TRIGGER_TRANSPORT_TIMEOUT = RETRY_TRIGGER_TRANSPORT_TIMEOUT

#: The same predicate object as the committed policy's. Identity, not a copy.
screen_count_should_retry = should_retry


def screen_count_delay_before_attempt(attempt: int) -> float:
    """Deterministic backoff, no jitter. ``attempt`` is 1-based.

    Attempt 1 is the original measurement and waits nothing; attempts 2 and 3
    wait 15s and 30s. A fourth attempt does not exist under this policy.
    """
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise ValueError("attempt must be a positive integer")
    if attempt == 1:
        return 0.0
    index = attempt - 2
    if index >= len(SCREEN_COUNT_RETRY_DELAYS_SECONDS):
        raise ValueError(
            f"attempt {attempt} exceeds the {SCREEN_COUNT_MAX_ATTEMPTS_V2}-attempt "
            "screen count policy"
        )
    return float(SCREEN_COUNT_RETRY_DELAYS_SECONDS[index])


def _positive(rows: object) -> int:
    if not isinstance(rows, int) or isinstance(rows, bool) or rows < 1:
        raise ValueError("row count must be a positive integer")
    return rows


def screen_count_attempt_cap(rows: int) -> int:
    """The run's countTokens ceiling: one row times three attempts."""
    return _positive(rows) * SCREEN_COUNT_MAX_ATTEMPTS_V2


def screen_external_request_cap_v2(rows: int) -> int:
    """The run's external-send ceiling: one row times eight."""
    return _positive(rows) * SCREEN_EXTERNAL_REQUESTS_PER_ROW_V2
