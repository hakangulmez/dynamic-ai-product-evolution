"""Screen connector that survives an empty successful generate body (ADR-119).

A live continuation run stopped after a ``generateContent`` call **returned**
with an empty entity body. Neither retry policy could help: ADR-117's long
backoff answers a raised transient failure, ADR-118's bounded count retry
answers the measurement call, and an HTTP-successful empty response raises
nothing at all. The capture layer refused to persist it — hashing nothing would
publish a valid-looking digest for content that never existed — and the run
stopped fail-closed on the first occurrence.

This successor changes exactly that one condition and inherits everything else:

* an empty generate body is detected **before** any persistence or parsing is
  attempted, classified as ``empty_generate_body``, and retried through the
  unchanged ADR-117 schedule — five total generate attempts at 15s, 30s, 60s
  and 120s;
* every other outcome keeps its meaning. A malformed, blocked, truncated,
  part-less, non-text or invalid-JSON response is still terminal on its first
  occurrence, because those are answers rather than absences of one;
* ``count_tokens`` is inherited from the ADR-118 connector, so the bounded
  three-attempt measurement retry is the same code, and an empty body never
  retries the count.

**Why the closed error enum is not extended.** ``ProviderError`` carries a
closed ``reason_code`` pinned to the released ``extraction_provider_error_record``
enum, and widening it would change a released contract. The exhaustion is
therefore reported as ``provider_response_unusable`` — literally "the provider
outcome could not be used" — while the *distinct* classification lives where
this successor owns the contract: each attempt's ledger event carries
``provider_reason_code = "empty_generate_body"`` with a null raw reference and
null hash, and the runner reads those events to write a truthful terminal
reason. The attempted external call stays auditable without inventing a digest.
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
from .authorization import require_request_cap
from .client_contract_v2 import MODEL_PARAMETERS_V2
from .errors import ProviderError
from .screen_retry_policy import (
    SCREEN_GENERATE_MAX_ATTEMPTS,
    SCREEN_GENERATE_RETRY_DELAYS_SECONDS,
)
from .vertex_gemini import RAW_CAPTURE_REPRESENTATION, translate_provider_exception
from .vertex_gemini_screen_v3 import is_screen_retryable
from .vertex_gemini_screen_v4 import VertexGeminiScreenV4
from .vertex_gemini_v2 import GENERATE_OPERATION, build_generate_request_config

__all__ = [
    "EMPTY_GENERATE_BODY_REASON",
    "SCREEN_CONNECTOR_V5_ID",
    "EmptyGenerateBody",
    "VertexGeminiScreenV5",
    "execute_with_empty_body_retry",
    "is_screen_retryable_v5",
]

SCREEN_CONNECTOR_V5_ID = "vertex_gemini_screen_v5"

#: The attempt-level classification written into the capture ledger. It is not
#: a ProviderError code: that enum is closed and released.
EMPTY_GENERATE_BODY_REASON = "empty_generate_body"

#: The disposition the shared sink assigns when a returned call carried no body.
_EMPTY_DISPOSITION = "empty_entity_body_not_persisted"


class EmptyGenerateBody(Exception):
    """One returned generateContent whose entity body was empty.

    Raised inside the retry loop so the schedule can answer it, and never
    allowed to escape: the loop either succeeds on a later attempt or converts
    exhaustion into a ``ProviderError``.
    """

    reason_code = EMPTY_GENERATE_BODY_REASON


def is_screen_retryable_v5(exc: BaseException) -> bool:
    """The ADR-117 predicate, plus this one narrowly defined anomaly.

    Nothing else is added. A validation, capture, governance, binding, schema,
    quote, budget or evidence failure is outside both halves of this test, and
    a malformed or blocked response never reaches it because such a response is
    not empty.
    """
    if isinstance(exc, EmptyGenerateBody):
        return True
    return is_screen_retryable(exc)


def execute_with_empty_body_retry(
    call: Callable[[], Any],
    *,
    sleep: Callable[[float], None] | None = None,
    max_attempts: int | None = None,
) -> Any:
    """Run ``call`` under the unchanged ADR-117 generate schedule.

    Five total attempts with fixed 15s/30s/60s/120s waits and no jitter. The
    only difference from its predecessor is the predicate: an empty body is
    retryable here. Exhaustion on empty bodies is reported as
    ``provider_response_unusable``, the closed enum's term for an outcome that
    could not be used.
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
        "retry": retry_if_exception(is_screen_retryable_v5),
        "reraise": True,
    }
    if sleep is not None:
        options["sleep"] = sleep
    try:
        return Retrying(**options)(attempt)
    except CaptureSinkError:
        raise
    except EmptyGenerateBody:
        # Every permitted attempt returned nothing. The closed enum has one
        # honest term for this, and the ledger carries the specific one.
        raise ProviderError(
            "provider_response_unusable", attempt_count=attempts
        ) from None
    except Exception as exc:  # noqa: BLE001 - the provider seam is total
        translated = translate_provider_exception(exc)
        raise ProviderError(translated.reason_code, attempt_count=attempts) from None


class VertexGeminiScreenV5(VertexGeminiScreenV4):
    """The screen's retry owner for both operations and for the empty body.

    ``last_empty_generate_bodies`` reports how many attempts of the most recent
    generation returned nothing, so the runner can account for them without
    inferring anything from the absence of a file.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.last_empty_generate_bodies = 0

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
        """Persist one attempt's body, classifying an empty generation exactly.

        The empty check happens here, before the sink is asked to write
        anything and before any parse: an empty body is never hashed, never
        stored, and never treated as a response. Its ledger event carries a
        null reference and a null hash with the specific reason, which is what
        keeps an attempted external call auditable without inventing evidence.
        """
        raw = capture.drain(operation_label, ordinal)
        outcome = capture.send_outcome(operation_label, ordinal)
        if sdk_call_outcome == "returned" and not raw:
            provider_reason_code = (
                EMPTY_GENERATE_BODY_REASON
                if operation_label == GENERATE_OPERATION
                else "provider_response_unusable"
            )
        return sink(
            operation_label=operation_label,
            attempt_ordinal=ordinal,
            raw_bytes=raw,
            send_outcome=outcome,
            sdk_call_outcome=sdk_call_outcome,
            provider_reason_code=provider_reason_code,
        )

    def complete_v8(
        self, request: ProviderRequest, *, admission: BudgetAdmission, sink: Any
    ) -> tuple[ProviderResponse, tuple[CaptureRecord, ...]]:
        """The authorized generation, with an empty body treated as absence.

        Structurally the ADR-117 method with one substitution: after each
        attempt is drained to the sink, a generation that returned no body
        raises the retryable sentinel from inside the loop, so the existing
        schedule answers it. Every other ordering — digest recomputation,
        admission spend before any factory work, per-attempt sink call,
        terminal-capture check — is unchanged.
        """
        self._spend(GENERATE_OPERATION)
        if not isinstance(request, ProviderRequest):
            raise ProviderError("provider_response_unusable")
        if not isinstance(admission, BudgetAdmission):
            raise ProviderError("live_call_not_authorized")
        expected_digest = provider_request_digest(
            request,
            provider_client_contract_sha256=client_contract_digest(self._contract),
            protocol_version=PROVIDER_PROTOCOL_VERSION_V8,
        )
        if admission.provider_request_digest != expected_digest:
            raise ProviderError("live_call_not_authorized")
        try:
            admission.spend()
        except Exception:  # noqa: BLE001 - a spent admission is simply a refusal
            raise ProviderError("live_call_not_authorized") from None
        cap = require_request_cap(
            admission.generate_attempt_cap, policy_maximum=SCREEN_GENERATE_MAX_ATTEMPTS
        )
        config = build_generate_request_config(request)
        records: list[CaptureRecord] = []
        self.last_empty_generate_bodies = 0
        with self._open() as (client, capture):
            with capture.operation(GENERATE_OPERATION):

                def call() -> Any:
                    return client.models.generate_content(
                        model=config["model"],
                        contents=request.rendered_contents,
                        config=config["config"],
                    )

                def attempt() -> Any:
                    response = self._attempt(
                        capture=capture,
                        operation_label=GENERATE_OPERATION,
                        call=call,
                        sink=sink,
                        records=records,
                    )
                    if records[-1].capture_disposition == _EMPTY_DISPOSITION:
                        # Returned, but with nothing in it. Absence of an
                        # answer, not an unusable answer.
                        self.last_empty_generate_bodies += 1
                        raise EmptyGenerateBody()
                    return response

                execute_with_empty_body_retry(
                    attempt, max_attempts=cap, sleep=self._sleep
                )
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
