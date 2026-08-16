"""Live SEC EDGAR transport: every httpx-originating SEC send lives here.

Governing documents:
- specs/SPEC-003-sec-ingestion.md (rate limits, hashing, retry/error records)
- docs/source_playbooks/SEC_EDGAR.md (descriptive user agent, rate limits)
- docs/DECISION_LOG.md ADR-077 (W0 unblocks live index acquisition),
  ADR-089 (bounded streaming send for filing documents)

This module is the smallest live successor to the fixture-replay transport in
:mod:`dynamic_ai_products.universe.frame_acquisition`. It lives at the package
top level on purpose: the universe package imports neither ``collection`` nor
``ingestion`` and contains no network code, so the live transport is built
here and *injected into* the universe acquisition runner as a callable, with
its identity passed alongside as data (``SEC_LIVE_TRANSPORT_IDENTITY``).

It hosts **two** sends, and hosting both here is why the repository-wide
httpx allowlist stays at three modules: the whole-response
``_httpx_send`` used by index and DERA acquisition, and the streaming
``httpx_streaming_send`` used for filing documents, whose bodies are
unbounded in principle and must be size-bounded while downloading. The
document *policy* — ceiling enforcement, preflight, chunk bounding, resource
lifetime — lives in :mod:`dynamic_ai_products.sec_document_transport`, which
imports no HTTP library. Index and DERA behaviour, contract, and identity
below are unchanged by that addition.

Policy, all recorded in the contract below and embedded in every v0.2
manifest:

- a descriptive SEC-compliant user agent carrying a contact address;
- bounded rate limiting: at most one request per second, enforced by
  monotonic-clock spacing across sends;
- a bounded retry ladder with fixed backoff for retryable statuses and
  transport exceptions; anything non-retryable is returned to the runner,
  which classifies and fails closed;
- a hard per-request timeout;
- redirects are never followed — a redirect status is returned as-is and the
  runner refuses it (the Route A stance for static index files).

The network send, the sleeper, and the monotonic clock are all injectable, so
every test runs against a fake send and asserts spacing and backoff without a
socket or a real sleep. The default send is the only place in this module
that can originate a network request, and nothing in the test suite calls it.
"""

from __future__ import annotations

import json
import time
from hashlib import sha256
from typing import Callable

from .universe.frame_acquisition import (
    IndexTransportResponse,
    TRANSPORT_KIND_SEC_LIVE,
    TransportIdentity,
)

__all__ = [
    "HttpxStreamingResponse",
    "SEC_LIVE_TRANSPORT_CONTRACT",
    "SEC_LIVE_TRANSPORT_IDENTITY",
    "httpx_streaming_send",
    "live_transport_contract_hash",
    "make_sec_live_transport",
    "request_headers",
]

# The declared, committed live-transport contract. Changing any value changes
# the recorded transport identity of every subsequent live acquisition.
SEC_LIVE_TRANSPORT_CONTRACT: dict = {
    "transport_kind": TRANSPORT_KIND_SEC_LIVE,
    "transport_version": "0.1.0",
    "user_agent": (
        "dynamic-ai-product-evolution research hakanzekigulmez@gmail.com"
    ),
    "min_request_spacing_seconds": 1.0,
    "request_timeout_seconds": 30.0,
    "max_retries_per_url": 2,
    "retry_backoff_seconds": [5.0, 15.0],
    "retry_statuses": [429, 500, 502, 503, 504],
    "follows_redirects": False,
}

SEC_LIVE_TRANSPORT_IDENTITY = TransportIdentity(
    kind=TRANSPORT_KIND_SEC_LIVE,
    contract=SEC_LIVE_TRANSPORT_CONTRACT,
)


def live_transport_contract_hash() -> str:
    """SHA-256 over the canonical live transport contract."""
    payload = json.dumps(
        SEC_LIVE_TRANSPORT_CONTRACT,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def request_headers() -> dict[str, str]:
    """Headers every live request carries; the user agent names a contact."""
    return {
        "User-Agent": SEC_LIVE_TRANSPORT_CONTRACT["user_agent"],
        "Accept-Encoding": "gzip, deflate",
    }


def _httpx_send(url: str) -> IndexTransportResponse:
    """The one real network send. Fresh client per request, no redirects.

    A fresh client per send makes cross-send cookie state impossible; the
    timeout and headers come from the committed contract. Never called by the
    test suite.
    """
    import httpx

    with httpx.Client(
        follow_redirects=False,
        timeout=SEC_LIVE_TRANSPORT_CONTRACT["request_timeout_seconds"],
        headers=request_headers(),
    ) as client:
        response = client.get(url)
    return IndexTransportResponse(
        status_code=response.status_code,
        final_url=str(response.url),
        content=response.content,
        location=response.headers.get("location"),
    )


class HttpxStreamingResponse:
    """A live response whose client and body stream stay open until closed.

    The client and the stream context are entered manually and held on the
    instance: returning an iterator from an exited ``with`` block would hand
    back either an already-closed stream or a leaked connection. ``close()``
    unwinds both and is idempotent, so the caller can close it in a
    ``finally`` on every path without tracking whether it already did.
    """

    def __init__(self, client, context, response) -> None:
        self._client = client
        self._context = context
        self._response = response
        self._closed = False
        self.status_code = response.status_code
        self.final_url = str(response.url)
        self.headers = dict(response.headers)

    def iter_chunks(self, chunk_bytes: int):
        return self._response.iter_bytes(chunk_size=chunk_bytes)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._context.__exit__(None, None, None)
        finally:
            self._client.close()

    def __enter__(self) -> "HttpxStreamingResponse":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def httpx_streaming_send(url: str) -> HttpxStreamingResponse:
    """The one real streaming network send, for filing documents.

    Headers arrive before the body, so the caller can refuse an oversized
    declared ``Content-Length`` without consuming a single body chunk. The
    returned response owns live resources and must be closed by the caller.
    Never called by the test suite.
    """
    import httpx

    client = httpx.Client(
        follow_redirects=False,
        timeout=SEC_LIVE_TRANSPORT_CONTRACT["request_timeout_seconds"],
        headers=request_headers(),
    )
    try:
        context = client.stream("GET", url)
        response = context.__enter__()
    except BaseException:
        client.close()
        raise
    return HttpxStreamingResponse(client, context, response)


def make_sec_live_transport(
    *,
    send: Callable[[str], IndexTransportResponse] | None = None,
    sleeper: Callable[[float], None] | None = None,
    monotonic: Callable[[], float] | None = None,
) -> Callable[[str], IndexTransportResponse]:
    """Wrap a send with the committed spacing and bounded-retry policy.

    ``send`` defaults to the real httpx single-send; tests inject a fake.
    ``sleeper`` and ``monotonic`` default to ``time.sleep`` / ``time.monotonic``
    and are injected in tests so spacing and backoff are asserted, not slept.

    Retry policy: a status in ``retry_statuses``, or an exception from the
    send, is retried up to ``max_retries_per_url`` times with the fixed
    backoff ladder. Any other response — including redirects, which are never
    followed — is returned as-is for the runner to classify. If every attempt
    raised, the last exception propagates and the runner records it as a
    ``transport_exception`` failure.
    """
    send_fn = send or _httpx_send
    sleep_fn = sleeper or time.sleep
    monotonic_fn = monotonic or time.monotonic
    spacing = float(SEC_LIVE_TRANSPORT_CONTRACT["min_request_spacing_seconds"])
    max_retries = int(SEC_LIVE_TRANSPORT_CONTRACT["max_retries_per_url"])
    backoff = [float(x) for x in SEC_LIVE_TRANSPORT_CONTRACT["retry_backoff_seconds"]]
    retry_statuses = frozenset(SEC_LIVE_TRANSPORT_CONTRACT["retry_statuses"])
    if len(backoff) < max_retries:
        raise ValueError(
            "retry_backoff_seconds must carry one delay per permitted retry."
        )
    last_send_at: list[float | None] = [None]

    def transport(url: str) -> IndexTransportResponse:
        last_error: Exception | None = None
        for attempt in range(1 + max_retries):
            previous = last_send_at[0]
            if previous is not None:
                remaining = spacing - (monotonic_fn() - previous)
                if remaining > 0:
                    sleep_fn(remaining)
            last_send_at[0] = monotonic_fn()
            try:
                response = send_fn(url)
            except Exception as exc:  # noqa: BLE001 - bounded, then propagated
                last_error = exc
                if attempt < max_retries:
                    sleep_fn(backoff[attempt])
                    continue
                raise
            if response.status_code in retry_statuses and attempt < max_retries:
                sleep_fn(backoff[attempt])
                continue
            return response
        raise last_error if last_error else RuntimeError("unreachable")

    return transport
