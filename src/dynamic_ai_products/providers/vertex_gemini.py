"""Vertex AI Gemini connector — default-deny in E-P (ADR-034).

**Default-deny remains the default.** With no authorization the connector is
exactly what E-P shipped: ``assert_run_permitted`` refuses before the
orchestrator opens a run root, so a refused run leaves zero artifacts, and
``complete`` refuses before reaching the SDK factory.

E-L adds the *authorized* path (ADR-035). It opens only on the two-key
handshake: the constructor holds the authorization digest this connector was
built for, and the runner supplies the digest it verified. Neither half alone
suffices. The SDK is imported lazily and solely by
:mod:`~dynamic_ai_products.providers.sdk_factory`, reached only after the
handshake passes.

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

from ..extraction.provider_adapter import CaptureSinkError, ProviderRequest, ProviderResponse
from .authorization import (
    require_authorization_digest,
    require_endpoint_allowlist_match,
    require_endpoint_allowlist_subset,
    require_request_cap,
)
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
    "RAW_CAPTURE_REPRESENTATION",
    "VertexGeminiProvider",
    "adapt_captured_bytes",
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
# The archival unit: the HTTP entity body after transfer Content-Encoding is
# undone. Recorded in the envelope's prompt_model_metadata so it is hash-bound
# through envelopes_sha256, not merely asserted in an ADR.
RAW_CAPTURE_REPRESENTATION = "post_content_encoding_entity_body"

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
    return adapt_captured_bytes(raw, prompt_sha256=prompt_sha256)


def adapt_captured_bytes(raw: Any, *, prompt_sha256: str) -> ProviderResponse:
    """Wrap captured entity-body bytes. Only real bytes are accepted."""
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
            "raw_capture_representation": RAW_CAPTURE_REPRESENTATION,
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
    call: Callable[[], Any],
    *,
    sleep: Callable[[float], None] | None = None,
    max_attempts: int | None = None,
) -> Any:
    """Run ``call`` under the declared retry policy, driven by ``tenacity``.

    ``tenacity`` is the single retry owner; the SDK's own layer is disabled with
    ``attempts=1`` so the two can never compound. The wait chain is fixed at
    1s then 2s with no jitter, so a run's retry timing is reproducible.

    ``max_attempts`` is the budget-derived cap. It can only lower
    ``RETRY_MAX_ATTEMPTS``; a caller cannot buy extra attempts with it.

    On exhaustion the raised :class:`ProviderError` carries ``attempt_count`` —
    the number of failed attempts, which is what ``extraction_run.error_count``
    records.
    """
    # The cap may only LOWER the E-P policy, never raise it.
    cap = RETRY_MAX_ATTEMPTS if max_attempts is None else min(max_attempts, RETRY_MAX_ATTEMPTS)
    if cap < 1:
        raise ProviderError("live_call_not_authorized")
    attempts = 0

    def attempt() -> Any:
        nonlocal attempts
        attempts += 1
        return call()

    options: dict[str, Any] = {
        "stop": stop_after_attempt(cap),
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
    except CaptureSinkError:
        # ADR-043 (E-M). A runner-owned persistence failure passes through
        # unchanged. Without this it would be translated to
        # ``provider_response_unusable`` -- a *valid* member of the released
        # provider-error enum -- and a filesystem failure would be published as a
        # provider failure with nothing to flag it. It is already non-retryable:
        # ``is_retryable`` returns False for it, so the loop has already stopped.
        raise
    except Exception as exc:  # noqa: BLE001 - the provider seam is total
        translated = translate_provider_exception(exc)
        raise ProviderError(translated.reason_code, attempt_count=attempts) from None


class VertexGeminiProvider:
    """Vertex Gemini provider, default-deny until the two-key handshake passes.

    ``expected_authorization_sha256`` and ``max_provider_requests`` are the
    connector's half of the handshake and are **explicit caller arguments** —
    neither is read from a file, an environment variable, or any ambient source.
    Both default to ``None``, so a connector built without them behaves exactly
    as E-P's did: it refuses.

    ``client_factory`` exists so the authorized path is testable offline. Its
    default is the real lazy SDK factory; tests inject a fake and no test in
    this repository builds a real ``genai.Client``, resolves ADC, or opens a
    socket.
    """

    def __init__(
        self,
        *,
        vertex_project: str,
        vertex_location: str = VERTEX_LOCATION,
        expected_authorization_sha256: str | None = None,
        max_provider_requests: int | None = None,
        endpoint_allowlist: tuple[str, ...] = (),
        client_factory: Any = None,
    ) -> None:
        # Validated eagerly and purely: a malformed project or location is a
        # configuration error, not a runtime surprise.
        self._contract = build_client_contract(
            vertex_project=vertex_project, vertex_location=vertex_location
        )
        self._vertex_project = vertex_project
        self._vertex_location = vertex_location
        self._expected_authorization_sha256 = expected_authorization_sha256
        self._max_provider_requests = max_provider_requests
        self._endpoint_allowlist = tuple(endpoint_allowlist)
        self._client_factory = client_factory
        self._activated_digest: str | None = None

    def assert_run_permitted(
        self,
        *,
        authorization_sha256: str | None = None,
        endpoint_allowlist: tuple[str, ...] | None = None,
        enablement_endpoint_allowlist: tuple[str, ...] | None = None,
    ) -> None:
        """Match the runner's verified digest **and** both endpoint allowlists.

        Called before the orchestrator creates anything and before any prompt
        load, meter call, SDK import, factory construction, or network, so a
        refusal leaves zero artifacts.

        The allowlists are the third key. Validating them as artifact content is
        not enough: a connector holding the right digest and cap could still
        carry a broader or different allowlist, and every per-request check would
        then be measured against the wrong set. Enforcement lives here because
        endpoint normalization is provider-side grammar and there must be exactly
        one of it.

        The permit granted here is **one-shot**: it authorizes exactly one
        :meth:`complete` call and is revoked at the start of every further
        handshake attempt.
        """
        # Revoke any prior permit before this attempt is judged. Otherwise a
        # failed handshake would leave an earlier success standing, and a
        # rejected authorization could still be spent.
        self._activated_digest = None
        if self._expected_authorization_sha256 is None:
            raise ProviderError("live_call_not_authorized")
        digest = require_authorization_digest(
            self._expected_authorization_sha256, authorization_sha256
        )
        # The cap is required for an authorized run: an uncapped run could
        # exceed the request budget the runner validated.
        require_request_cap(self._max_provider_requests, policy_maximum=RETRY_MAX_ATTEMPTS)
        # Three-level narrowing, in one grammar:
        #   enablement ⊇ authorization == connector
        # The authorization may use less than the enablement allows but never
        # more; the connector must be configured for exactly what was authorized.
        # Either step also rejects an empty, malformed, non-sequence, or
        # duplicate-bearing list on either side.
        require_endpoint_allowlist_subset(
            enablement_endpoint_allowlist, endpoint_allowlist
        )
        require_endpoint_allowlist_match(self._endpoint_allowlist, endpoint_allowlist)
        self._activated_digest = digest

    def revoke_run_permission(self) -> None:
        """Drop any live permit. Idempotent, and cannot fail.

        Clearing a field is the whole operation: no SDK import, no factory, no
        client, no credential, and no network. That is what lets the orchestrator
        call it unconditionally on every exit from the post-handshake region,
        including while an exception is already propagating.
        """
        self._activated_digest = None

    def client_contract(self) -> dict[str, Any]:
        """Return the declared contract. Pure; performs no I/O."""
        return dict(self._contract)

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        """Execute one authorized call, or refuse without touching the SDK.

        The permit is **consumed** here, before any factory, SDK, credential, or
        network work. One authorization buys one call: a success, a terminal
        provider error, a capture failure, and a factory failure all spend it
        alike, so none of them can be replayed into a second call.
        """
        activated = self._activated_digest
        self._activated_digest = None
        if activated is None:
            raise ProviderError("live_call_not_authorized")
        cap = require_request_cap(
            self._max_provider_requests, policy_maximum=RETRY_MAX_ATTEMPTS
        )
        if not isinstance(request, ProviderRequest):
            raise ProviderError("provider_response_unusable")
        config = build_request_config(request)
        factory = self._client_factory
        if factory is None:
            # Imported here, not at module scope: an unauthorized run never
            # reaches this line and therefore never pulls in the vendor SDK.
            from .sdk_factory import build_vertex_client

            factory = build_vertex_client
        with factory(
            vertex_project=self._vertex_project,
            vertex_location=self._vertex_location,
            endpoint_allowlist=self._endpoint_allowlist,
            http_options_kwargs=build_http_options_kwargs(),
        ) as (client, capture):

            def call() -> Any:
                return client.models.generate_content(
                    model=config["model"],
                    contents=request.rendered_contents,
                    config=config["config"],
                )

            execute_with_retry(call, max_attempts=cap)
            # The archived bytes are the captured entity body, never a re-encode
            # of the SDK's decoded text.
            return adapt_captured_bytes(
                capture.captured_bytes(), prompt_sha256=request.prompt_sha256
            )
