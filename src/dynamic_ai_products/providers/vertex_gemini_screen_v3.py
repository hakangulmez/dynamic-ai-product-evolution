"""Screen-only Vertex connector with the long 429 backoff (ADR-117).

A narrow successor of :class:`~dynamic_ai_products.providers.vertex_gemini_v2.VertexGeminiProviderV2`
that changes exactly two things and inherits everything else:

* ``assert_run_permitted`` admits an attempt cap up to the screen policy's five
  rather than the committed extraction policy's three; the three-list endpoint
  equality and the authorization-digest check are the same rules, restated only
  because the ceiling they pass to ``require_request_cap`` differs;
* ``complete_v8`` drives the screen's own wait chain (15s, 30s, 60s, 120s).

**What is inherited, deliberately.** ``count_tokens`` is not overridden: the
V2 implementation performs exactly one send and carries no retry loop, so a
generate retry can never re-measure the input. ``_attempt`` and
``_drain_to_sink`` are not overridden either, which is what keeps the
per-attempt rule true here: the sink is called with each attempt's body before
the retry wrapper is allowed to wait or re-send, so a persistence failure stops
the loop while there is still a loop to stop.

**Why the SDK layer still cannot compound.** Nothing here touches
``HttpRetryOptions(attempts=1)``: the request configs come from the unchanged
V2 builders, so this connector remains the single retry owner and the vendor
SDK still performs no retry of its own.

This module imports no ``google`` package and opens no socket; the lazy factory
it inherits is reached only after a passed handshake.
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

from ..extraction.provider_adapter import (
    PROVIDER_PROTOCOL_VERSION_V8,
    BudgetAdmission,
    CaptureRecord,
    CaptureSinkError,
    ProviderRequest,
    ProviderResponse,
    client_contract_digest,
    provider_request_digest,
)
from .authorization import require_authorization_digest, require_request_cap
from .client_contract_v2 import MODEL_PARAMETERS_V2
from .endpoint_grammar_v2 import require_allowlist_equals_operations
from .errors import ProviderError
from .screen_retry_policy import (
    SCREEN_GENERATE_MAX_ATTEMPTS,
    SCREEN_GENERATE_RETRY_DELAYS_SECONDS,
    screen_should_retry,
)
from .vertex_gemini import (
    RAW_CAPTURE_REPRESENTATION,
    translate_provider_exception,
    _status_of,
)
from .vertex_gemini_v2 import (
    COUNT_OPERATION,
    GENERATE_OPERATION,
    VertexGeminiProviderV2,
    build_generate_request_config,
)

__all__ = [
    "SCREEN_CONNECTOR_ID",
    "VertexGeminiScreenV3",
    "execute_with_screen_retry",
    "is_screen_retryable",
]

#: Recorded in the screen run manifest. The wire protocol is still v8 and the
#: client contract is still the v2 one; what this names is the retry owner.
SCREEN_CONNECTOR_ID = "vertex_gemini_screen_v3"


def is_screen_retryable(exc: BaseException) -> bool:
    """Only a declared transient transport failure of an ordinary exception.

    The declaration is the committed policy's, reached through
    :data:`~dynamic_ai_products.providers.screen_retry_policy.screen_should_retry`,
    which is that policy's own predicate object. A validation failure, a
    capture-persistence failure, a governance refusal, a budget refusal and an
    evidence failure are all outside it and are therefore never retried.

    ``KeyboardInterrupt`` and ``SystemExit`` derive from ``BaseException``, not
    ``Exception``: they are the operator stopping the run and always propagate.
    """
    if not isinstance(exc, Exception):
        return False
    translated = translate_provider_exception(exc)
    return screen_should_retry(
        status_code=_status_of(exc),
        transport_timeout=translated.reason_code == "provider_timeout",
    )


def execute_with_screen_retry(
    call: Callable[[], Any],
    *,
    sleep: Callable[[float], None] | None = None,
    max_attempts: int | None = None,
) -> Any:
    """Run ``call`` under the screen generate policy, driven by ``tenacity``.

    Five total attempts with a fixed 15s/30s/60s/120s chain and no jitter.
    ``max_attempts`` is the admission-derived cap and may only *lower* the
    policy ceiling; a caller cannot buy a sixth attempt with it.

    On exhaustion the raised :class:`ProviderError` carries ``attempt_count``,
    and its reason code is the provider's own — a run that exhausts five 429s
    reports ``vertex_quota_exhausted`` rather than a generic failure.
    """
    cap = (
        SCREEN_GENERATE_MAX_ATTEMPTS
        if max_attempts is None
        else min(max_attempts, SCREEN_GENERATE_MAX_ATTEMPTS)
    )
    if cap < 1:
        raise ProviderError("live_call_not_authorized")
    attempts = 0

    def attempt() -> Any:
        nonlocal attempts
        attempts += 1
        return call()

    options: dict[str, Any] = {
        "stop": stop_after_attempt(cap),
        "wait": wait_chain(
            *(wait_fixed(delay) for delay in SCREEN_GENERATE_RETRY_DELAYS_SECONDS)
        ),
        "retry": retry_if_exception(is_screen_retryable),
        # The original failure is re-raised rather than wrapped in RetryError,
        # so the classification below sees the provider's own exception.
        "reraise": True,
    }
    if sleep is not None:
        options["sleep"] = sleep
    try:
        return Retrying(**options)(attempt)
    except CaptureSinkError:
        # A runner-owned persistence failure passes through unchanged; it is
        # already non-retryable, so the loop has already stopped.
        raise
    except Exception as exc:  # noqa: BLE001 - the provider seam is total
        translated = translate_provider_exception(exc)
        raise ProviderError(translated.reason_code, attempt_count=attempts) from None


class VertexGeminiScreenV3(VertexGeminiProviderV2):
    """The screen's retry owner. Default-deny until the same handshake passes.

    ``sleep`` exists so the wait chain is observable offline: tests inject a
    recorder and no test in this repository waits 225 seconds. Its default is
    ``None``, which lets ``tenacity`` use its own sleep — the only behaviour a
    live run ever sees.
    """

    def __init__(self, *, sleep: Callable[[float], None] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._sleep = sleep

    def assert_run_permitted(
        self,
        *,
        authorization_sha256: str | None = None,
        endpoint_allowlist: tuple[str, ...] | None = None,
        enablement_endpoint_allowlist: tuple[str, ...] | None = None,
    ) -> None:
        """Grant one labelled permit per operation, or refuse leaving nothing.

        The same three-list equality and the same digest check as the V2
        connector. Only the ceiling handed to ``require_request_cap`` differs:
        this connector may be built for five generate attempts, and the V2
        connector may not.
        """
        self._permits.clear()
        if self._expected_authorization_sha256 is None:
            raise ProviderError("live_call_not_authorized")
        require_authorization_digest(
            self._expected_authorization_sha256, authorization_sha256
        )
        require_request_cap(
            self._max_provider_requests, policy_maximum=SCREEN_GENERATE_MAX_ATTEMPTS
        )
        for candidate in (
            self._endpoint_allowlist,
            endpoint_allowlist,
            enablement_endpoint_allowlist,
        ):
            try:
                require_allowlist_equals_operations(candidate, self._operation_endpoints)
            except ProviderError as exc:
                # One reason for every layer: naming which list failed would
                # tell a caller how far its guess got.
                raise ProviderError("live_call_not_authorized") from exc
        self._permits.update({COUNT_OPERATION, GENERATE_OPERATION})

    def complete_v8(
        self, request: ProviderRequest, *, admission: BudgetAdmission, sink: Any
    ) -> tuple[ProviderResponse, tuple[CaptureRecord, ...]]:
        """The authorized generation call under the screen's long backoff.

        Structurally the V2 method with one substitution — the wait chain — so
        the digest recomputation, the admission spend before any factory or
        credential work, the per-attempt sink call and the terminal-capture
        check all keep their order.
        """
        self._spend(GENERATE_OPERATION)
        if not isinstance(request, ProviderRequest):
            raise ProviderError("provider_response_unusable")
        if not isinstance(admission, BudgetAdmission):
            raise ProviderError("live_call_not_authorized")
        # Recomputed from the request in hand and this connector's own declared
        # contract, never read back from the admission.
        expected_digest = provider_request_digest(
            request,
            provider_client_contract_sha256=client_contract_digest(self._contract),
            protocol_version=PROVIDER_PROTOCOL_VERSION_V8,
        )
        if admission.provider_request_digest != expected_digest:
            raise ProviderError("live_call_not_authorized")
        # Spent before any factory, SDK, credential or network work begins.
        try:
            admission.spend()
        except Exception:  # noqa: BLE001 - a spent admission is simply a refusal
            raise ProviderError("live_call_not_authorized") from None
        cap = require_request_cap(
            admission.generate_attempt_cap, policy_maximum=SCREEN_GENERATE_MAX_ATTEMPTS
        )
        config = build_generate_request_config(request)
        records: list[CaptureRecord] = []
        with self._open() as (client, capture):
            with capture.operation(GENERATE_OPERATION):

                def call() -> Any:
                    return client.models.generate_content(
                        model=config["model"],
                        contents=request.rendered_contents,
                        config=config["config"],
                    )

                def attempt() -> Any:
                    return self._attempt(
                        capture=capture,
                        operation_label=GENERATE_OPERATION,
                        call=call,
                        sink=sink,
                        records=records,
                    )

                execute_with_screen_retry(attempt, max_attempts=cap, sleep=self._sleep)
                terminal = records[-1]
                if terminal.capture_disposition != "raw_persisted":
                    raise ProviderError(
                        "provider_response_unusable", attempt_count=len(records)
                    )
                response = ProviderResponse(
                    raw_bytes=b"",
                    model_provider=self._contract["model_provider"],
                    model_name=self._contract["model_name"],
                    model_parameters=dict(MODEL_PARAMETERS_V2),
                    prompt_model_metadata={
                        "model_name": self._contract["model_name"],
                        "prompt_sha256": request.prompt_sha256,
                        "api_version": self._contract["api_version"],
                        "raw_capture_representation": RAW_CAPTURE_REPRESENTATION,
                        "raw_prediction_reference": terminal.raw_reference,
                        "raw_prediction_sha256": terminal.raw_sha256,
                    },
                )
        return response, tuple(records)
