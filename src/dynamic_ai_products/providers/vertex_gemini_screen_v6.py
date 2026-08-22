"""Screen connector that survives an empty successful count body (ADR-120).

ADR-119 made an empty `generateContent` body survivable and deliberately
scoped that to the generation call. The very next full-cohort attempt stopped
on the other half: `countTokens` returned once with no usable body, the
bounded count retry never engaged because a returned call raises nothing, and
the terminal check fired outside the loop. The fix was correct and incomplete.

This successor closes the counterpart and nothing else:

* an empty count body is detected before any persistence or parse, classified
  `empty_count_body`, and retried through the **unchanged** ADR-118 count
  schedule — three total attempts at 15s and 30s;
* ADR-119's generate behaviour is preserved exactly, by inheritance rather
  than restatement: `complete_v8` is not overridden here;
* an empty count body never invokes the generation for that attempt. The
  measurement is a precondition, so `count_tokens` raises before the adapter
  can reach `complete_v8`;
* nothing else becomes retryable. A malformed, blocked, truncated, part-less
  or invalid-JSON response, a capture-persistence failure, a governance or
  budget refusal, a quote or evidence failure — all keep their meaning,
  because none of them is an empty body.

**The released error enum stays closed.** Exhaustion is reported as
`provider_response_unusable`, the enum's own term for an outcome that could
not be used; the operation-specific state lives in the ledger event
(`empty_count_body`, with a null reference and null hash) and in the runner's
receipt. Nothing empty is ever hashed or stored as a normal capture.
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
)
from .vertex_gemini import translate_provider_exception
from .vertex_gemini_screen_v4 import is_count_retryable
from .vertex_gemini_screen_v5 import (
    EMPTY_GENERATE_BODY_REASON,
    VertexGeminiScreenV5,
)
from .vertex_gemini_v2 import (
    COUNT_OPERATION,
    GENERATE_OPERATION,
    _witness_total_tokens,
    build_count_request_config,
)

__all__ = [
    "EMPTY_COUNT_BODY_REASON",
    "SCREEN_CONNECTOR_V6_ID",
    "EmptyCountBody",
    "VertexGeminiScreenV6",
    "execute_with_empty_count_retry",
    "is_count_retryable_v6",
]

SCREEN_CONNECTOR_V6_ID = "vertex_gemini_screen_v6"

#: The attempt-level classification written into the capture ledger. Like its
#: generate counterpart it is not a ProviderError code: that enum is closed.
EMPTY_COUNT_BODY_REASON = "empty_count_body"

_EMPTY_DISPOSITION = "empty_entity_body_not_persisted"


class EmptyCountBody(Exception):
    """One returned countTokens whose entity body was empty.

    Raised inside the retry loop so the bounded count schedule can answer it,
    and never allowed to escape: the loop either succeeds on a later attempt
    or converts exhaustion into a ``ProviderError``.
    """

    reason_code = EMPTY_COUNT_BODY_REASON


def is_count_retryable_v6(exc: BaseException) -> bool:
    """The ADR-118 count predicate, plus this one narrowly defined anomaly."""
    if isinstance(exc, EmptyCountBody):
        return True
    return is_count_retryable(exc)


def execute_with_empty_count_retry(
    call: Callable[[], Any],
    *,
    sleep: Callable[[float], None] | None = None,
    max_attempts: int | None = None,
) -> Any:
    """Run ``call`` under the unchanged ADR-118 count schedule.

    Three total attempts with fixed 15s and 30s waits and no jitter. The only
    difference from its predecessor is the predicate: an empty body is
    retryable here.
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
        "retry": retry_if_exception(is_count_retryable_v6),
        "reraise": True,
    }
    if sleep is not None:
        options["sleep"] = sleep
    try:
        return Retrying(**options)(attempt)
    except CaptureSinkError:
        raise
    except EmptyCountBody:
        raise ProviderError(
            "provider_response_unusable", attempt_count=attempts
        ) from None
    except Exception as exc:  # noqa: BLE001 - the provider seam is total
        translated = translate_provider_exception(exc)
        raise ProviderError(translated.reason_code, attempt_count=attempts) from None


class VertexGeminiScreenV6(VertexGeminiScreenV5):
    """The screen's retry owner for both operations and both empty bodies.

    ``last_empty_count_bodies`` reports how many attempts of the most recent
    measurement returned nothing, so the runner accounts for them rather than
    inferring anything from a missing file.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.last_empty_count_bodies = 0

    @staticmethod
    def _drain_to_sink(
        *,
        capture: Any,
        operation_label: str,
        ordinal: int,
        sink: Any,
        sdk_call_outcome: str,
        provider_reason_code: str | None,
    ) -> CaptureRecord:
        """Classify an empty body by the operation that produced it.

        Both classifications happen before the sink is asked to write
        anything: an empty body is never hashed, never stored, and never
        treated as a response, whichever call returned it.
        """
        raw = capture.drain(operation_label, ordinal)
        outcome = capture.send_outcome(operation_label, ordinal)
        if sdk_call_outcome == "returned" and not raw:
            provider_reason_code = {
                GENERATE_OPERATION: EMPTY_GENERATE_BODY_REASON,
                COUNT_OPERATION: EMPTY_COUNT_BODY_REASON,
            }.get(operation_label, "provider_response_unusable")
        return sink(
            operation_label=operation_label,
            attempt_ordinal=ordinal,
            raw_bytes=raw,
            send_outcome=outcome,
            sdk_call_outcome=sdk_call_outcome,
            provider_reason_code=provider_reason_code,
        )

    def count_tokens(
        self, request: ProviderRequest, *, sink: Any
    ) -> tuple[CaptureRecord, int | None]:
        """Up to three ``countTokens`` sends, an empty body among the reasons.

        Structurally the ADR-118 method with one substitution: after each
        attempt is drained to the sink, a measurement that returned no body
        raises the retryable sentinel from inside the loop. The generation is
        never reached on such an attempt, because this method raises before
        returning a record.
        """
        self._spend(COUNT_OPERATION)
        if not isinstance(request, ProviderRequest):
            raise ProviderError("provider_response_unusable")
        config = build_count_request_config(request)
        records: list[CaptureRecord] = []
        self.last_count_attempts = 0
        self.last_empty_count_bodies = 0
        with self._open() as (client, capture):
            with capture.operation(COUNT_OPERATION):

                def call() -> Any:
                    return client.models.count_tokens(
                        model=config["model"],
                        contents=request.rendered_contents,
                        config=config["config"],
                    )

                def attempt() -> Any:
                    response = self._attempt(
                        capture=capture,
                        operation_label=COUNT_OPERATION,
                        call=call,
                        sink=sink,
                        records=records,
                    )
                    if records[-1].capture_disposition == _EMPTY_DISPOSITION:
                        # Returned, but with nothing in it. The input was not
                        # measured, so the generation must not proceed.
                        self.last_empty_count_bodies += 1
                        raise EmptyCountBody()
                    return response

                try:
                    response = execute_with_empty_count_retry(
                        attempt, sleep=self._sleep
                    )
                except CaptureSinkError:
                    raise
                except ProviderError:
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
