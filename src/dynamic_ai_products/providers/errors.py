"""Neutral provider failure boundary (ADR-034, E-P).

``ProviderError`` carries a **closed** ``reason_code`` and a **fixed** sanitized
message chosen from that code. There is no free-text parameter, so an upstream
exception message, response body, header, token, or credential has no channel
into this exception — that is a structural property, not a redaction pass.

The orchestrator in ``extraction`` translates this at the seam by reading the
duck-typed ``reason_code`` and ``attempt_count`` attributes; it never imports
this module, because the only permitted ``providers -> extraction`` edge runs
in the other direction and covers ``provider_adapter`` alone.
"""

from __future__ import annotations

__all__ = [
    "PROVIDER_REASON_CODES",
    "ProviderError",
    "TERMINAL_REASON_CODES",
]

# The pre-run refusal. It never reaches the terminal provider-error artifact
# because no provider attempt has begun when it is raised.
_PRE_RUN_REASON = "live_call_not_authorized"

# Terminal reason codes: a provider attempt began and ended without a usable
# response. These are exactly the values the released
# extraction_provider_error_record@0.1.0 enum accepts.
TERMINAL_REASON_CODES: tuple[str, ...] = (
    "provider_timeout",
    "vertex_quota_exhausted",
    "vertex_unavailable",
    "vertex_permission_denied",
    "vertex_model_not_found",
    "vertex_project_invalid",
    "vertex_location_invalid",
    "adc_not_configured",
    "adc_refresh_failed",
    "adc_expired",
    "provider_response_unusable",
)

PROVIDER_REASON_CODES: tuple[str, ...] = (_PRE_RUN_REASON,) + TERMINAL_REASON_CODES

# One fixed sentence per code. Nothing is interpolated from an upstream object.
_MESSAGES: dict[str, str] = {
    "live_call_not_authorized": (
        "a live provider call is not authorized in this increment"
    ),
    "provider_timeout": "the provider request exceeded its configured deadline",
    "vertex_quota_exhausted": "the provider reported a quota or rate limit",
    "vertex_unavailable": "the provider reported a server-side failure",
    "vertex_permission_denied": "the provider denied the request",
    "vertex_model_not_found": "the configured model was not found",
    "vertex_project_invalid": "the configured project was rejected",
    "vertex_location_invalid": "the configured location was rejected",
    "adc_not_configured": (
        "application default credentials are not configured; run "
        "'gcloud auth application-default login' outside this process"
    ),
    "adc_refresh_failed": "application default credentials could not be refreshed",
    "adc_expired": "application default credentials have expired",
    "provider_response_unusable": "the provider outcome could not be used",
}


class ProviderError(Exception):
    """A sanitized provider failure.

    ``attempt_count`` is the number of provider attempts that were made. It is
    ``0`` for a pre-run refusal, because no attempt began.
    """

    def __init__(self, reason_code: str, *, attempt_count: int = 0) -> None:
        if reason_code not in _MESSAGES:
            raise ValueError(f"undeclared provider reason code: {reason_code!r}")
        if not isinstance(attempt_count, int) or attempt_count < 0:
            raise ValueError("attempt_count must be a non-negative integer")
        super().__init__(_MESSAGES[reason_code])
        self.reason_code = reason_code
        self.attempt_count = attempt_count

    @property
    def is_terminal(self) -> bool:
        return self.reason_code in TERMINAL_REASON_CODES
