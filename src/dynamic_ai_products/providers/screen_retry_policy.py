"""Generate-attempt retry policy for the universe high-recall screen (ADR-117).

**Screen-only, and additive.** ``providers/retry_policy.py`` keeps publishing
the committed extraction policy — three generate attempts, 1s then 2s — with
its bytes unchanged, and every extraction caller keeps receiving exactly that.
This module is a second, narrower policy read by one screen connector only.
Nothing here widens the generic policy; the two coexist and never merge.

**What differs, and only this.** The number of generate attempts per logical
packet (five, not three) and the waits between them (15s, 30s, 60s, 120s, not
1s and 2s). The retry *triggers* are not restated: :func:`screen_should_retry`
**is** the committed :func:`~dynamic_ai_products.providers.retry_policy.should_retry`
object, so the declared transient conditions — 408, 429, 500, 502, 503, 504 and
a transport timeout — remain the only retryable failures, and a validation,
capture, governance, budget or evidence failure is never retried by
construction rather than by convention.

**Why long waits.** A 429 is the provider declaring a quota or rate limit. The
1s/2s chain re-sends inside the same rate-limit window and buys three refusals
where a single logical packet was wanted; 15/30/60/120 crosses a per-minute
window before the last attempt. The waits are fixed and jitter-free so a run's
retry timing stays reproducible and its worst case is arithmetic, not an
estimate: one packet spends at most four waits totalling 225 seconds.

``countTokens`` is deliberately absent from the retry surface:
:data:`SCREEN_COUNT_MAX_ATTEMPTS` is one, and the connector's count operation
carries no loop at all, so a generate retry can never re-measure the input.
"""

from __future__ import annotations

from .retry_policy import (
    RETRY_TRIGGER_STATUS_CODES,
    RETRY_TRIGGER_TRANSPORT_TIMEOUT,
    should_retry,
)

__all__ = [
    "SCREEN_COUNT_MAX_ATTEMPTS",
    "SCREEN_EXTERNAL_REQUESTS_PER_ROW",
    "SCREEN_GENERATE_MAX_ATTEMPTS",
    "SCREEN_GENERATE_RETRY_DELAYS_SECONDS",
    "SCREEN_GENERATE_RETRY_POLICY_VERSION",
    "SCREEN_RETRY_JITTER",
    "SCREEN_RETRY_OWNER",
    "SCREEN_RETRY_TRIGGER_STATUS_CODES",
    "SCREEN_RETRY_TRIGGER_TRANSPORT_TIMEOUT",
    "screen_delay_before_attempt",
    "screen_external_request_cap",
    "screen_generate_attempt_cap",
    "screen_should_retry",
]

#: Named in the screen authorization and recorded in the run manifest, so a
#: run minted for the generic three-attempt policy cannot be executed here.
SCREEN_GENERATE_RETRY_POLICY_VERSION = "universe_screen_generate_retry_policy_v1"

SCREEN_RETRY_OWNER = "tenacity"
SCREEN_RETRY_JITTER = False

#: Five **total** attempts per logical packet: the original send plus four
#: retries. Not "five retries".
SCREEN_GENERATE_MAX_ATTEMPTS = 5

#: The four waits between those five attempts, in order, in seconds.
SCREEN_GENERATE_RETRY_DELAYS_SECONDS: tuple[int, ...] = (15, 30, 60, 120)

#: countTokens measures the input once per row and is never retried.
SCREEN_COUNT_MAX_ATTEMPTS = 1

#: The structural per-row external maximum: one count send plus the generate
#: ceiling. Every external-request arithmetic in the screen derives from here.
SCREEN_EXTERNAL_REQUESTS_PER_ROW = (
    SCREEN_COUNT_MAX_ATTEMPTS + SCREEN_GENERATE_MAX_ATTEMPTS
)

#: Re-exported, not restated: the same tuple object the committed policy
#: declares. A new retryable condition can only be added by changing that
#: policy, never by editing the screen's own module.
SCREEN_RETRY_TRIGGER_STATUS_CODES = RETRY_TRIGGER_STATUS_CODES
SCREEN_RETRY_TRIGGER_TRANSPORT_TIMEOUT = RETRY_TRIGGER_TRANSPORT_TIMEOUT

#: The same predicate object as the committed policy's. Identity, not a copy.
screen_should_retry = should_retry


def screen_delay_before_attempt(attempt: int) -> float:
    """Deterministic backoff, no jitter. ``attempt`` is 1-based.

    Attempt 1 is the original request and waits nothing; attempts 2 through 5
    wait 15s, 30s, 60s and 120s. A sixth attempt does not exist under this
    policy and asking for its delay is an error rather than a repeat of the
    last wait.
    """
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise ValueError("attempt must be a positive integer")
    if attempt == 1:
        return 0.0
    index = attempt - 2
    if index >= len(SCREEN_GENERATE_RETRY_DELAYS_SECONDS):
        raise ValueError(
            f"attempt {attempt} exceeds the {SCREEN_GENERATE_MAX_ATTEMPTS}-attempt "
            "screen generate policy"
        )
    return float(SCREEN_GENERATE_RETRY_DELAYS_SECONDS[index])


def _positive(logical_request_cap: object) -> int:
    if (
        not isinstance(logical_request_cap, int)
        or isinstance(logical_request_cap, bool)
        or logical_request_cap < 1
    ):
        raise ValueError("logical_request_cap must be a positive integer")
    return logical_request_cap


def screen_generate_attempt_cap(logical_request_cap: int) -> int:
    """The run's provider-attempt ceiling: one logical packet times five."""
    return _positive(logical_request_cap) * SCREEN_GENERATE_MAX_ATTEMPTS


def screen_external_request_cap(logical_request_cap: int) -> int:
    """The run's external-send ceiling: one logical packet times six."""
    return _positive(logical_request_cap) * SCREEN_EXTERNAL_REQUESTS_PER_ROW
