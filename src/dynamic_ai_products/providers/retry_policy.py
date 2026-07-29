"""Timeout and retry policy for the Vertex Gemini connector (ADR-034, E-P).

**One retry owner.** The SDK's own retry is disabled explicitly with
``HttpRetryOptions(attempts=1)`` — the field is never left unset, because the
released SDK defaults to five attempts and two overlapping retry layers would
collide and corrupt the ``error_count`` accounting.

Timeout values were resolved by the E-P0 gate against the installed
``google-genai==2.13.0`` source, network-free:

- ``google.genai.types.HttpOptions.timeout`` is ``Optional[int]``;
- its unit is **milliseconds** — proven behaviourally by
  ``_api_client.get_timeout_in_seconds()``, which divides by ``1000.0`` before
  handing the value to ``httpx``, not merely by the field description.
"""

from __future__ import annotations

__all__ = [
    "API_VERSION",
    "FALLBACK_POLICY",
    "RATE_LIMIT_POLICY_VERSION",
    "RETRY_DELAYS_SECONDS",
    "RETRY_JITTER",
    "RETRY_MAX_ATTEMPTS",
    "RETRY_OWNER",
    "RETRY_POLICY_VERSION",
    "RETRY_TRIGGER_STATUS_CODES",
    "RETRY_TRIGGER_TRANSPORT_TIMEOUT",
    "SDK_RETRY_ATTEMPTS",
    "TIMEOUT_DURATION",
    "TIMEOUT_SDK_PARAMETER",
    "TIMEOUT_UNIT",
    "delay_before_attempt",
    "should_retry",
]

RETRY_POLICY_VERSION = "extraction_provider_retry_policy_v1"
RATE_LIMIT_POLICY_VERSION = "extraction_provider_rate_limit_policy_v1"

# --- timeout (E-P0 verified) --------------------------------------------------

TIMEOUT_SDK_PARAMETER = "google.genai.types.HttpOptions.timeout"
TIMEOUT_DURATION = 300000
TIMEOUT_UNIT = "milliseconds"
API_VERSION = "v1"

# --- retry --------------------------------------------------------------------

# Explicit, never left to the SDK default of five.
SDK_RETRY_ATTEMPTS = 1
RETRY_OWNER = "tenacity"
RETRY_MAX_ATTEMPTS = 3
RETRY_DELAYS_SECONDS: tuple[int, ...] = (1, 2)
RETRY_JITTER = False
RETRY_TRIGGER_STATUS_CODES: tuple[int, ...] = (408, 429, 500, 502, 503, 504)
RETRY_TRIGGER_TRANSPORT_TIMEOUT = True
FALLBACK_POLICY = "none"


def should_retry(*, status_code: int | None = None, transport_timeout: bool = False) -> bool:
    """Only a declared transport-level failure is retryable.

    A retry never changes the provider, model, parameters, project, location,
    prompt, or input packet; it repeats the identical request.
    """
    if transport_timeout:
        return RETRY_TRIGGER_TRANSPORT_TIMEOUT
    if status_code is None:
        return False
    return status_code in RETRY_TRIGGER_STATUS_CODES


def delay_before_attempt(attempt: int) -> float:
    """Deterministic backoff, no jitter.

    ``attempt`` is 1-based. Attempt 1 is the original request and waits nothing;
    attempt 2 waits 1s and attempt 3 waits 2s.
    """
    if not isinstance(attempt, int) or attempt < 1:
        raise ValueError("attempt must be a positive integer")
    if attempt == 1:
        return 0.0
    index = attempt - 2
    if index >= len(RETRY_DELAYS_SECONDS):
        raise ValueError(
            f"attempt {attempt} exceeds the {RETRY_MAX_ATTEMPTS}-attempt policy"
        )
    return float(RETRY_DELAYS_SECONDS[index])
