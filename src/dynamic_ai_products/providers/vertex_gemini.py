"""Vertex AI Gemini connector — default-deny in E-P (ADR-034).

**This increment cannot make a live call, and that is a code path rather than a
claim.** Both public entry points refuse unconditionally:

- :meth:`VertexGeminiProvider.assert_run_permitted` raises before the
  orchestrator opens a run root, so a refused run leaves zero artifacts;
- :meth:`VertexGeminiProvider.complete` raises as its first statement.

No SDK is imported anywhere in this package. ``google.genai`` is reached only
by the optional compatibility test under ``tests/providers``. E-L introduces the
authorized execution path, the SDK factory, and the schema-bearing
authorization artifact; E-P defines none of them.

The internal seams below are pure and duck-typed so the whole adapter surface
is testable offline with a fake, without the SDK installed and without any
vendor exception class being imported. ``tenacity`` is the single retry owner;
the SDK's own retry layer is disabled explicitly so the two cannot compound.
"""

from __future__ import annotations

from typing import Any, Callable

from tenacity import (
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_chain,
    wait_fixed,
)

from ..extraction.provider_adapter import ProviderRequest, ProviderResponse
from .client_contract import MODEL_NAME, MODEL_PARAMETERS, VERTEX_LOCATION, build_client_contract
from .errors import ProviderError
from .retry_policy import (
    API_VERSION,
    RETRY_DELAYS_SECONDS,
    RETRY_MAX_ATTEMPTS,
    SDK_RETRY_ATTEMPTS,
    TIMEOUT_DURATION,
    should_retry,
)

__all__ = [
    "VertexGeminiProvider",
    "adapt_response",
    "build_http_options_kwargs",
    "build_request_config",
    "execute_with_retry",
    "is_retryable",
    "translate_provider_exception",
]

# Vendor exception classes are never imported. Classification is duck-typed on
# the exception's own attributes and class name, so nothing from the upstream
# object's text ever reaches a message or an artifact.
_ADC_ERROR_NAMES: dict[str, str] = {
    "DefaultCredentialsError": "adc_not_configured",
    "RefreshError": "adc_refresh_failed",
    "ReauthFailError": "adc_expired",
}
_STATUS_REASON: dict[int, str] = {
    403: "vertex_permission_denied",
    404: "vertex_model_not_found",
    408: "provider_timeout",
    429: "vertex_quota_exhausted",
    500: "vertex_unavailable",
    502: "vertex_unavailable",
    503: "vertex_unavailable",
    504: "vertex_unavailable",
}


def build_http_options_kwargs() -> dict[str, Any]:
    """The exact ``HttpOptions`` keyword arguments this connector declares.

    ``retry_options`` is always present with ``attempts=1``: the SDK defaults to
    five attempts, so leaving the field unset would silently enable a second
    retry layer.
    """
    return {
        "api_version": API_VERSION,
        "timeout": TIMEOUT_DURATION,
        "retry_options": {"attempts": SDK_RETRY_ATTEMPTS},
    }


def build_request_config(request: ProviderRequest) -> dict[str, Any]:
    """Map a stage request onto generation config. Pure; no SDK, no I/O."""
    if not isinstance(request, ProviderRequest):
        raise ProviderError("provider_response_unusable")
    return {
        "model": MODEL_NAME,
        "config": dict(MODEL_PARAMETERS),
        "http_options": build_http_options_kwargs(),
        "prompt_sha256": request.prompt_sha256,
        "input_packet_sha256": request.input_packet_sha256,
        "stage": request.stage,
    }


def _status_of(exc: BaseException) -> int | None:
    for attribute in ("code", "status_code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def translate_provider_exception(exc: BaseException) -> ProviderError:
    """Classify an upstream failure without reading any of its text."""
    if isinstance(exc, ProviderError):
        return exc
    name = type(exc).__name__
    if name in _ADC_ERROR_NAMES:
        return ProviderError(_ADC_ERROR_NAMES[name])
    if "Timeout" in name:
        return ProviderError("provider_timeout")
    status = _status_of(exc)
    if status is not None and status in _STATUS_REASON:
        return ProviderError(_STATUS_REASON[status])
    return ProviderError("provider_response_unusable")


def adapt_response(sdk_response: Any, *, prompt_sha256: str) -> ProviderResponse:
    """Adapt a duck-typed SDK response into the extraction payload type.

    **Only a genuine bytes field is accepted.** There is no encode, no ``str``
    coercion, and no re-serialization: manufacturing bytes from a decoded
    ``text`` attribute would invent a raw artifact the provider never sent, and
    the whole point of raw-before-parse is that the archived bytes are the ones
    that arrived. Designing the real SDK response-byte capture surface belongs
    to E-L; E-P refuses rather than guesses.
    """
    raw = getattr(sdk_response, "raw_bytes", None)
    if not isinstance(raw, (bytes, bytearray)):
        raise ProviderError("provider_response_unusable")
    return ProviderResponse(
        raw_bytes=bytes(raw),
        model_provider="google_vertex_ai",
        model_name=MODEL_NAME,
        model_parameters=dict(MODEL_PARAMETERS),
        prompt_model_metadata={
            "model_name": MODEL_NAME,
            "prompt_sha256": prompt_sha256,
            "api_version": API_VERSION,
        },
    )


def is_retryable(exc: BaseException) -> bool:
    """Only a declared transport-level failure of an ordinary exception.

    ``KeyboardInterrupt`` and ``SystemExit`` derive from ``BaseException``, not
    ``Exception``: they are the operator stopping the run, and retrying through
    them would swallow the interrupt. They are never retryable and propagate.
    """
    if not isinstance(exc, Exception):
        return False
    translated = translate_provider_exception(exc)
    return should_retry(
        status_code=_status_of(exc),
        transport_timeout=translated.reason_code == "provider_timeout",
    )


def execute_with_retry(
    call: Callable[[], Any], *, sleep: Callable[[float], None] | None = None
) -> Any:
    """Run ``call`` under the declared retry policy, driven by ``tenacity``.

    ``tenacity`` is the single retry owner; the SDK's own layer is disabled with
    ``attempts=1`` so the two can never compound. The wait chain is fixed at
    1s then 2s with no jitter, so a run's retry timing is reproducible.

    On exhaustion the raised :class:`ProviderError` carries ``attempt_count`` —
    the number of failed attempts, which is what ``extraction_run.error_count``
    records.
    """
    attempts = 0

    def attempt() -> Any:
        nonlocal attempts
        attempts += 1
        return call()

    options: dict[str, Any] = {
        "stop": stop_after_attempt(RETRY_MAX_ATTEMPTS),
        "wait": wait_chain(*(wait_fixed(delay) for delay in RETRY_DELAYS_SECONDS)),
        "retry": retry_if_exception(is_retryable),
        # The original failure is re-raised rather than wrapped in RetryError,
        # so classification below sees the provider's own exception.
        "reraise": True,
    }
    if sleep is not None:
        options["sleep"] = sleep
    try:
        return Retrying(**options)(attempt)
    except Exception as exc:  # noqa: BLE001 - the provider seam is total
        translated = translate_provider_exception(exc)
        raise ProviderError(translated.reason_code, attempt_count=attempts) from None


class VertexGeminiProvider:
    """Default-deny Vertex Gemini provider.

    Satisfies ``ExtractionProvider`` but performs no call in this increment.
    """

    def __init__(
        self, *, vertex_project: str, vertex_location: str = VERTEX_LOCATION
    ) -> None:
        # Validated eagerly and purely: a malformed project or location is a
        # configuration error, not a runtime surprise.
        self._contract = build_client_contract(
            vertex_project=vertex_project, vertex_location=vertex_location
        )

    def assert_run_permitted(self) -> None:
        """Refuse before the orchestrator creates anything on disk."""
        raise ProviderError("live_call_not_authorized")

    def client_contract(self) -> dict[str, Any]:
        """Return the declared contract. Pure; performs no I/O."""
        return dict(self._contract)

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        """Refuse unconditionally. E-P reaches no SDK, client, or credential."""
        raise ProviderError("live_call_not_authorized")
