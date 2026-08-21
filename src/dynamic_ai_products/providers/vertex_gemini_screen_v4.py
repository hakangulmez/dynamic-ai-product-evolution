"""Screen connector with a bounded countTokens retry (ADR-118).

A narrow successor of
:class:`~dynamic_ai_products.providers.vertex_gemini_screen_v3.VertexGeminiScreenV3`
that changes exactly one thing and inherits the rest: ``count_tokens`` may now
spend up to three attempts with fixed 15s and 30s waits, where the V3 connector
spends exactly one.

**What is inherited, deliberately.** ``complete_v8`` is not overridden, so the
ADR-117 generate policy — five attempts at 15s/30s/60s/120s — applies here
byte-for-byte, and the V3 module keeps its bytes. ``assert_run_permitted``,
``_attempt`` and ``_drain_to_sink`` are inherited too, so the handshake rules
and the per-attempt capture-before-next-send rule are the same code, not a
restatement: each count attempt's body reaches the runner's sink before the
loop may wait or re-send.

**Why the measurement call may be retried at all.** ``countTokens`` is
idempotent — the same rendered prompt in, a token count out. Re-sending it
invents no evidence, changes no model output and cannot alter a screen result.
It remains a precondition: the generation still does not begin until a count
has succeeded.

This module imports no ``google`` package and opens no socket.
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
    CaptureRecord,
    CaptureSinkError,
    ProviderRequest,
)
from .errors import ProviderError
from .screen_count_retry_policy import (
    SCREEN_COUNT_MAX_ATTEMPTS_V2,
    SCREEN_COUNT_RETRY_DELAYS_SECONDS,
    screen_count_should_retry,
)
from .vertex_gemini import _status_of, translate_provider_exception
from .vertex_gemini_screen_v3 import VertexGeminiScreenV3
from .vertex_gemini_v2 import (
    COUNT_OPERATION,
    _witness_total_tokens,
    build_count_request_config,
)

__all__ = [
    "SCREEN_CONNECTOR_V4_ID",
    "VertexGeminiScreenV4",
    "execute_with_count_retry",
    "is_count_retryable",
]

#: Recorded in the continuation manifest. The wire protocol is still v8 and the
#: client contract is still the v2 one; what this names is the retry owner.
SCREEN_CONNECTOR_V4_ID = "vertex_gemini_screen_v4"


def is_count_retryable(exc: BaseException) -> bool:
    """Only a declared transient transport failure of an ordinary exception.

    The declaration is the committed policy's, reached through
    :data:`~dynamic_ai_products.providers.screen_count_retry_policy.screen_count_should_retry`,
    which is that policy's own predicate object. A validation, capture,
    governance, binding, schema, quote or budget failure is outside it.
    """
    if not isinstance(exc, Exception):
        return False
    translated = translate_provider_exception(exc)
    return screen_count_should_retry(
        status_code=_status_of(exc),
        transport_timeout=translated.reason_code == "provider_timeout",
    )


def execute_with_count_retry(
    call: Callable[[], Any],
    *,
    sleep: Callable[[float], None] | None = None,
    max_attempts: int | None = None,
) -> Any:
    """Run ``call`` under the screen count policy, driven by ``tenacity``.

    Three total attempts with a fixed 15s/30s chain and no jitter.
    ``max_attempts`` may only *lower* the policy ceiling.
    """
    cap = (
        SCREEN_COUNT_MAX_ATTEMPTS_V2
        if max_attempts is None
        else min(max_attempts, SCREEN_COUNT_MAX_ATTEMPTS_V2)
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
            *(wait_fixed(delay) for delay in SCREEN_COUNT_RETRY_DELAYS_SECONDS)
        ),
        "retry": retry_if_exception(is_count_retryable),
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


class VertexGeminiScreenV4(VertexGeminiScreenV3):
    """The screen's retry owner for both operations.

    ``last_count_attempts`` reports what the most recent measurement actually
    cost, so the runner can account for count sends without inferring them.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.last_count_attempts = 0

    def count_tokens(
        self, request: ProviderRequest, *, sink: Any
    ) -> tuple[CaptureRecord, int | None]:
        """Up to three ``countTokens`` sends. No number is interpreted here.

        Structurally the V2 method with one substitution — the retry wrapper —
        so the permit spend, the config build, the per-attempt sink call and
        the terminal-capture check all keep their order and their meaning.
        """
        self._spend(COUNT_OPERATION)
        if not isinstance(request, ProviderRequest):
            raise ProviderError("provider_response_unusable")
        config = build_count_request_config(request)
        records: list[CaptureRecord] = []
        self.last_count_attempts = 0
        with self._open() as (client, capture):
            with capture.operation(COUNT_OPERATION):

                def call() -> Any:
                    return client.models.count_tokens(
                        model=config["model"],
                        contents=request.rendered_contents,
                        config=config["config"],
                    )

                def attempt() -> Any:
                    return self._attempt(
                        capture=capture,
                        operation_label=COUNT_OPERATION,
                        call=call,
                        sink=sink,
                        records=records,
                    )

                try:
                    response = execute_with_count_retry(attempt, sleep=self._sleep)
                except CaptureSinkError:
                    raise
                except ProviderError:
                    # Already carries the provider's own reason and its count.
                    self.last_count_attempts = len(records)
                    raise
                except Exception as exc:  # noqa: BLE001 - the seam is total
                    translated = translate_provider_exception(exc)
                    self.last_count_attempts = len(records)
                    raise ProviderError(
                        translated.reason_code, attempt_count=len(records)
                    ) from None
        self.last_count_attempts = len(records)
        record = records[-1]
        if record.capture_disposition != "raw_persisted":
            raise ProviderError("provider_response_unusable", attempt_count=len(records))
        return record, _witness_total_tokens(response)
