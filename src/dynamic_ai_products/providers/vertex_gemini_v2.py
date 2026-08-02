"""Vertex AI Gemini connector, protocol v8 (ADR-043, E-M).

Successor of :mod:`~dynamic_ai_products.providers.vertex_gemini`, which keeps
publishing the single-operation contract it was built for. This connector walks
two operations — ``countTokens`` then ``generateContent`` — and the ordering
between them is the whole point: nothing derived from a response is used before
the response's own bytes are durably written and hash-verified.

**Why the runner owns the sink instead of the retry loop.** An earlier shape had
this connector finish every retry under ``tenacity`` and hand the runner a bundle
of captures afterwards. That makes the "a persistence failure permits no further
send" rule unenforceable: by the time the failure is visible, the later sends have
already happened. Here the runner's sink is called after each attempt and
**before** the next one, so the loop stops while there is still a loop to stop.
The sink's failure type passes through the retry wrapper unchanged, and it is
already non-retryable under the declared policy.

**Why plain dicts.** Every config handed to the SDK is a plain mapping. The SDK
coerces them itself, and the resulting request body is byte-identical to the one
built from typed objects — measured against ``google-genai==2.13.0``. That keeps
``sdk_factory`` the only module under ``src/`` that imports ``google.*``, and this
module imports neither ``google`` nor ``httpx``.

**What this connector never does.** It interprets no number. ``count_tokens``
returns the raw capture record and the SDK's own witness value; deriving the token
count from the archived bytes, and reconciling the two, belongs to the runner.
"""

from __future__ import annotations

from typing import Any, Callable

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
from .client_contract import MODEL_NAME, MODEL_PARAMETERS, VERTEX_LOCATION
from .client_contract_v2 import (
    GENERATION_CONFIG_PROJECTION,
    THINKING_CONFIG,
    build_client_contract_v2,
    build_operation_endpoints,
)
from .endpoint_grammar_v2 import (
    require_allowlist_equals_operations,
    require_operation_endpoints,
)
from .errors import ProviderError
from .retry_policy import RETRY_MAX_ATTEMPTS, TIMEOUT_DURATION
from .vertex_gemini import (
    RAW_CAPTURE_REPRESENTATION,
    build_http_options_kwargs,
    execute_with_retry,
    translate_provider_exception,
)

__all__ = [
    "COUNT_OPERATION",
    "GENERATE_OPERATION",
    "VertexGeminiProviderV2",
    "build_count_request_config",
    "build_generate_request_config",
    "build_generation_projection",
]

COUNT_OPERATION = "count_tokens"
GENERATE_OPERATION = "generate_content"


def build_generation_projection() -> dict[str, Any]:
    """The six-field generation config both operations share.

    Built from one function so the two calls cannot diverge: measuring the input
    of one configuration and then billing another would make the measurement
    describe a request that was never sent. The field order follows the canonical
    projection declared by the client contract.
    """
    source: dict[str, Any] = dict(MODEL_PARAMETERS)
    source["thinking_config"] = dict(THINKING_CONFIG)
    projection: dict[str, Any] = {}
    for name in GENERATION_CONFIG_PROJECTION:
        if name not in source:
            raise ProviderError("provider_response_unusable")
        projection[name] = source[name]
    return projection


def build_generate_request_config(request: ProviderRequest) -> dict[str, Any]:
    """Map a stage request onto the generation call. Pure; no SDK, no I/O.

    ``system_instruction`` and ``tools`` are not omitted by accident: there is no
    channel that could supply them. :class:`ProviderRequest` has no such field,
    and the config is assembled here from closed constants only.
    """
    if not isinstance(request, ProviderRequest):
        raise ProviderError("provider_response_unusable")
    config = build_generation_projection()
    config["http_options"] = dict(build_http_options_kwargs())
    return {
        "model": MODEL_NAME,
        "config": config,
        "prompt_sha256": request.prompt_sha256,
        "input_packet_sha256": request.input_packet_sha256,
        "stage": request.stage,
    }


def build_count_request_config(request: ProviderRequest) -> dict[str, Any]:
    """Map a stage request onto the token-count call. Pure; no SDK, no I/O.

    The count call carries the same six-field projection as the generation call,
    nested under ``generation_config`` where the SDK expects it, plus its own
    per-call timeout. Its ``http_options`` sets ``timeout`` and nothing else: the
    SDK merges per-call options field by field, so a field left unset falls back
    to the client's — which is how the capture client and the disabled SDK retry
    layer survive the merge.
    """
    if not isinstance(request, ProviderRequest):
        raise ProviderError("provider_response_unusable")
    return {
        "model": MODEL_NAME,
        "config": {
            "generation_config": build_generation_projection(),
            "http_options": {"timeout": TIMEOUT_DURATION},
        },
        "prompt_sha256": request.prompt_sha256,
        "input_packet_sha256": request.input_packet_sha256,
        "stage": request.stage,
    }


def _witness_total_tokens(sdk_response: Any) -> int | None:
    """Read the SDK's own token count. A second witness, never the authority."""
    value = getattr(sdk_response, "total_tokens", None)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


class VertexGeminiProviderV2:
    """Two-operation Vertex connector, default-deny until the handshake passes.

    The handshake is unchanged from E-L and still runs before the orchestrator
    creates anything: ``enablement ⊇ authorization == connector``. What changes is
    what a passed handshake buys — an operation-labelled permit, spent once by
    ``count_tokens`` and once by ``complete_v8``, rather than a single call.
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
        self._contract = build_client_contract_v2(
            vertex_project=vertex_project, vertex_location=vertex_location
        )
        self._operation_endpoints = build_operation_endpoints(
            vertex_project=vertex_project, vertex_location=vertex_location
        )
        require_operation_endpoints(self._operation_endpoints)
        self._vertex_project = vertex_project
        self._vertex_location = vertex_location
        self._expected_authorization_sha256 = expected_authorization_sha256
        self._max_provider_requests = max_provider_requests
        self._endpoint_allowlist = tuple(endpoint_allowlist)
        self._client_factory = client_factory
        self._permits: set[str] = set()

    # --- governance ----------------------------------------------------------

    def assert_run_permitted(
        self,
        *,
        authorization_sha256: str | None = None,
        endpoint_allowlist: tuple[str, ...] | None = None,
        enablement_endpoint_allowlist: tuple[str, ...] | None = None,
    ) -> None:
        """Grant one labelled permit per operation, or refuse leaving nothing.

        **All three lists must be exactly this connector's two operation URLs.**
        The released v1 helpers cannot express that. They normalize with
        ``normalize_endpoint``, which *discards* query and fragment before
        comparing -- measured -- so an allowlist entry carrying ``?alt=sse``
        compares equal to one without it and would be admitted. They also read
        ``enablement`` as a superset, which is right when a run may use less than
        its enablement allows; a two-operation run may not. It needs both
        operations and nothing else, from every layer.

        This governs **artifact admission**, before any permit exists. The
        per-request equality check inside the capture client is the second layer
        and stays: this one decides whether the endpoints declared by governance
        are the right ones, that one decides whether the URL actually being sent
        is the one its operation declared.
        """
        self._permits.clear()
        if self._expected_authorization_sha256 is None:
            raise ProviderError("live_call_not_authorized")
        require_authorization_digest(
            self._expected_authorization_sha256, authorization_sha256
        )
        require_request_cap(self._max_provider_requests, policy_maximum=RETRY_MAX_ATTEMPTS)
        for candidate in (
            self._endpoint_allowlist,
            endpoint_allowlist,
            enablement_endpoint_allowlist,
        ):
            try:
                require_allowlist_equals_operations(candidate, self._operation_endpoints)
            except ProviderError as exc:
                # One reason for every layer: naming which list failed would tell
                # a caller how far its guess got.
                raise ProviderError("live_call_not_authorized") from exc
        self._permits.update({COUNT_OPERATION, GENERATE_OPERATION})

    def revoke_run_permission(self) -> None:
        """Drop every live permit. Idempotent, and cannot fail."""
        self._permits.clear()

    def client_contract(self) -> dict[str, Any]:
        """Return the declared v2 contract. Pure; performs no I/O."""
        return dict(self._contract)

    def _spend(self, operation_label: str) -> None:
        if operation_label not in self._permits:
            raise ProviderError("live_call_not_authorized")
        self._permits.discard(operation_label)

    # --- one attempt, one sink call ------------------------------------------

    def _attempt(
        self,
        *,
        capture: Any,
        operation_label: str,
        call: Callable[[], Any],
        sink: Any,
        records: list[CaptureRecord],
    ) -> Any:
        """Run one send, then persist its body before anything else happens.

        There is no ``finally``: the success path needs the sink's return value,
        and a sink failure raised out of a ``finally`` would *replace* a provider
        failure that was already propagating. Both branches call the sink exactly
        once, and the exception branch re-raises the **original** so ``tenacity``
        classifies what really happened.
        """
        ordinal = capture.next_ordinal(operation_label)
        try:
            response = call()
        except BaseException as exc:
            provider_reason = (
                translate_provider_exception(exc).reason_code
                if isinstance(exc, Exception)
                else None
            )
            records.append(
                self._drain_to_sink(
                    capture=capture,
                    operation_label=operation_label,
                    ordinal=ordinal,
                    sink=sink,
                    sdk_call_outcome="raised",
                    provider_reason_code=provider_reason,
                )
            )
            raise
        records.append(
            self._drain_to_sink(
                capture=capture,
                operation_label=operation_label,
                ordinal=ordinal,
                sink=sink,
                sdk_call_outcome="returned",
                provider_reason_code=None,
            )
        )
        return response

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
        raw = capture.drain(operation_label, ordinal)
        outcome = capture.send_outcome(operation_label, ordinal)
        if sdk_call_outcome == "returned" and not raw:
            # A returned call whose entity body was empty is unusable, and an
            # empty body is never written: sha256 of nothing is a valid-looking
            # digest for content that never existed.
            provider_reason_code = "provider_response_unusable"
        return sink(
            operation_label=operation_label,
            attempt_ordinal=ordinal,
            raw_bytes=raw,
            send_outcome=outcome,
            sdk_call_outcome=sdk_call_outcome,
            provider_reason_code=provider_reason_code,
        )

    # --- operations ----------------------------------------------------------

    def count_tokens(
        self, request: ProviderRequest, *, sink: Any
    ) -> tuple[CaptureRecord, int | None]:
        """One ``countTokens`` send. No retry, and no number is interpreted."""
        self._spend(COUNT_OPERATION)
        if not isinstance(request, ProviderRequest):
            raise ProviderError("provider_response_unusable")
        config = build_count_request_config(request)
        records: list[CaptureRecord] = []
        with self._open() as (client, capture):
            with capture.operation(COUNT_OPERATION):

                def call() -> Any:
                    return client.models.count_tokens(
                        model=config["model"],
                        contents=request.rendered_contents,
                        config=config["config"],
                    )

                try:
                    response = self._attempt(
                        capture=capture,
                        operation_label=COUNT_OPERATION,
                        call=call,
                        sink=sink,
                        records=records,
                    )
                except CaptureSinkError:
                    raise
                except Exception as exc:  # noqa: BLE001 - the provider seam is total
                    translated = translate_provider_exception(exc)
                    raise ProviderError(translated.reason_code, attempt_count=1) from None
        record = records[0]
        if record.capture_disposition != "raw_persisted":
            raise ProviderError("provider_response_unusable", attempt_count=1)
        return record, _witness_total_tokens(response)

    def complete_v8(
        self, request: ProviderRequest, *, admission: BudgetAdmission, sink: Any
    ) -> tuple[ProviderResponse, tuple[CaptureRecord, ...]]:
        """Execute the authorized generation call under a verified admission."""
        self._spend(GENERATE_OPERATION)
        if not isinstance(request, ProviderRequest):
            raise ProviderError("provider_response_unusable")
        if not isinstance(admission, BudgetAdmission):
            raise ProviderError("live_call_not_authorized")
        # Recomputed here from the request in hand, this connector's **own**
        # declared contract, and the protocol it speaks -- not read back from the
        # admission. An admission minted for another stage, another prompt,
        # another packet, another contract or another protocol version is refused
        # before the factory, the client, the credentials or any send.
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
            admission.generate_attempt_cap, policy_maximum=RETRY_MAX_ATTEMPTS
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

                execute_with_retry(attempt, max_attempts=cap)
                terminal = records[-1]
                if terminal.capture_disposition != "raw_persisted":
                    raise ProviderError(
                        "provider_response_unusable", attempt_count=len(records)
                    )
                response = ProviderResponse(
                    raw_bytes=b"",
                    model_provider=self._contract["model_provider"],
                    model_name=self._contract["model_name"],
                    model_parameters=dict(MODEL_PARAMETERS),
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

    def _open(self) -> Any:
        factory = self._client_factory
        if factory is None:
            # Imported here, not at module scope: an unauthorized run never
            # reaches this line and therefore never pulls in the vendor SDK.
            from .sdk_factory import build_vertex_client

            factory = build_vertex_client
        return factory(
            vertex_project=self._vertex_project,
            vertex_location=self._vertex_location,
            endpoint_allowlist=self._endpoint_allowlist,
            http_options_kwargs=build_http_options_kwargs(),
            operation_endpoints=dict(self._operation_endpoints),
        )
