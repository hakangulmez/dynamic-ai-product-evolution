"""Bounded live SEC filing-document transport (W2-B; canary-gated).

Governing documents:
- docs/DECISION_LOG.md ADR-089 (baseline document acquisition, this design)
- docs/source_playbooks/SEC_EDGAR.md (descriptive user agent, rate limits)

A complete-submission text file carries exhibits and inline XBRL and has no
trustworthy a-priori size, so the per-document ceiling must bound the
*download*, not merely the write. This module holds that policy. It contains
no network code and imports no HTTP library: the one httpx-originating send
lives in :mod:`dynamic_ai_products.sec_index_transport`, which stays the
single repository-wide httpx importer, and is injected here (or replaced by a
fake in tests) through the ``StreamingResponse`` seam below.

Enforcement contract, with ``stream_chunk_bytes = 65536``:

- a parseable ``Content-Length`` strictly greater than ``max_bytes`` refuses
  before a single body chunk is consumed. The header lookup is explicitly
  case-insensitive; a generic mapping is never assumed to fold case;
- an absent, empty, non-numeric, or negative ``Content-Length`` is treated as
  *absent* — never fatal, never a bypass. A malformed header is not evidence
  of size, and the streaming check below is authoritative;
- chunks are consumed with a running count; the first chunk that *would*
  cross ``max_bytes`` is never appended (not even a partial slice) and the
  stream is closed and refused immediately;
- the retained accepted body is therefore always ``<= max_bytes``, while
  transport-level received bytes may reach ``max_bytes + stream_chunk_bytes``
  because one chunk may straddle the limit. That upper bound is part of the
  contract, recorded in the manifest, and asserted in tests;
- a ceiling refusal is terminal and never retried. Spacing and the bounded
  retry ladder still govern retryable statuses and send exceptions;
- a non-200 status and a terminal-URL mismatch are both refused *before* any
  body chunk is read. The runner classifies them, so consuming a body that
  is about to be discarded would be pure waste.

Resource lifetime: ``stream_send`` returns a response whose underlying client
and body stream stay open until ``close()`` is called. This transport closes
it in a ``finally`` on every path — accepted response, preflight refusal,
chunk-limit refusal, redirect, terminal-URL mismatch, non-200, send
exception, and every retry transition. ``close()`` is idempotent.

The document transport identity is **separate** from the index transport
identity: it declares the streaming policy above, so its canonical contract
hash necessarily differs. The committed index/DERA contract is untouched, and
no acquisition that used it changes. ``max_bytes`` is plan-owned and per-run,
so it is deliberately not part of the contract and does not perturb the hash.
"""

from __future__ import annotations

import time
from typing import Callable, Iterator, Mapping, Optional, Protocol

from .sec_index_transport import (
    SEC_LIVE_TRANSPORT_CONTRACT,
    httpx_streaming_send,
)
from .universe.document_acquisition import DocumentTransportResponse
from .universe.frame_acquisition import (
    TRANSPORT_KIND_SEC_LIVE,
    TransportIdentity,
)

__all__ = [
    "SEC_LIVE_DOCUMENT_TRANSPORT_CONTRACT",
    "SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY",
    "STREAM_CHUNK_BYTES",
    "StreamingResponse",
    "header_value",
    "make_sec_live_document_transport",
    "parse_content_length",
]

STREAM_CHUNK_BYTES = 65536


class StreamingResponse(Protocol):
    """A response whose body is still unread and whose resources are open.

    Implementations keep the underlying client and stream alive until
    ``close()``; returning a naked iterator from an exited context manager
    would either be already closed or leak the connection, so the seam is
    defined in terms of an explicit, idempotent ``close()``.
    """

    status_code: int
    final_url: str
    headers: Mapping[str, str]

    def iter_chunks(self, chunk_bytes: int) -> Iterator[bytes]:
        ...

    def close(self) -> None:
        ...


# Shared policy values come from the committed index contract so the two
# cannot drift; the streaming fields are additions, never edits to it.
SEC_LIVE_DOCUMENT_TRANSPORT_CONTRACT: dict = {
    "transport_kind": TRANSPORT_KIND_SEC_LIVE,
    "transport_version": "0.1.0-document",
    "user_agent": SEC_LIVE_TRANSPORT_CONTRACT["user_agent"],
    "min_request_spacing_seconds": SEC_LIVE_TRANSPORT_CONTRACT[
        "min_request_spacing_seconds"
    ],
    "request_timeout_seconds": SEC_LIVE_TRANSPORT_CONTRACT[
        "request_timeout_seconds"
    ],
    "max_retries_per_url": SEC_LIVE_TRANSPORT_CONTRACT["max_retries_per_url"],
    "retry_backoff_seconds": list(
        SEC_LIVE_TRANSPORT_CONTRACT["retry_backoff_seconds"]
    ),
    "retry_statuses": list(SEC_LIVE_TRANSPORT_CONTRACT["retry_statuses"]),
    "follows_redirects": False,
    "streaming": True,
    "stream_chunk_bytes": STREAM_CHUNK_BYTES,
    "enforces_max_document_bytes": True,
    "content_length_preflight": True,
    "content_length_lookup": "case_insensitive",
    "malformed_content_length": "treated_as_absent",
    "max_transport_bytes_rule": "max_document_bytes + stream_chunk_bytes",
    "ceiling_refusal_retried": False,
}

SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY = TransportIdentity(
    kind=TRANSPORT_KIND_SEC_LIVE,
    contract=SEC_LIVE_DOCUMENT_TRANSPORT_CONTRACT,
)


def header_value(headers: Mapping[str, str], name: str) -> Optional[str]:
    """Case-insensitive header lookup.

    HTTP header names are case-insensitive, but a plain ``dict`` is not, and
    a fake or adapted mapping may preserve whatever casing the server sent.
    This never assumes the mapping folds case on its own.
    """
    target = name.lower()
    for key, value in headers.items():
        if str(key).lower() == target:
            return value
    return None


def parse_content_length(raw: Optional[str]) -> Optional[int]:
    """Return a usable declared length, or ``None`` when unusable.

    Absent, empty, non-numeric, and negative values all yield ``None`` — the
    header is treated as absent rather than fatal, and streaming enforcement
    remains authoritative.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        value = int(text)
    except ValueError:
        return None
    return None if value < 0 else value


def _consume(
    stream: StreamingResponse,
    requested_url: str,
    max_bytes: int,
    chunk_bytes: int,
) -> DocumentTransportResponse:
    """Read at most ``max_bytes`` of body, refusing the moment it is crossed."""
    status = stream.status_code
    location = header_value(stream.headers, "location")
    declared = parse_content_length(
        header_value(stream.headers, "content-length")
    )
    if status != 200:
        # A redirect or error body is never consumed.
        return DocumentTransportResponse(
            status_code=status,
            final_url=stream.final_url,
            content=b"",
            location=location,
            declared_content_length=declared,
            bytes_received=0,
        )
    if stream.final_url != requested_url:
        # A body served from a URL other than the one requested is never
        # consumed: the runner refuses the terminal-URL mismatch, so reading
        # up to the ceiling first would be pure waste. The mismatching URL is
        # returned unchanged so that classification is unaffected.
        return DocumentTransportResponse(
            status_code=status,
            final_url=stream.final_url,
            content=b"",
            location=location,
            declared_content_length=declared,
            bytes_received=0,
        )
    if declared is not None and declared > max_bytes:
        return DocumentTransportResponse(
            status_code=status,
            final_url=stream.final_url,
            content=b"",
            location=location,
            declared_content_length=declared,
            bytes_received=0,
            ceiling_refusal="content_length_preflight",
        )
    buffer = bytearray()
    received = 0
    for chunk in stream.iter_chunks(chunk_bytes):
        received += len(chunk)
        if len(buffer) + len(chunk) > max_bytes:
            # The crossing chunk is never appended, not even partially, and
            # everything read so far is discarded.
            return DocumentTransportResponse(
                status_code=status,
                final_url=stream.final_url,
                content=b"",
                location=location,
                declared_content_length=declared,
                bytes_received=received,
                ceiling_refusal="stream_exceeded",
            )
        buffer.extend(chunk)
    return DocumentTransportResponse(
        status_code=status,
        final_url=stream.final_url,
        content=bytes(buffer),
        location=location,
        declared_content_length=declared,
        bytes_received=received,
    )


def make_sec_live_document_transport(
    *,
    max_bytes: int,
    stream_send: Callable[[str], StreamingResponse] | None = None,
    sleeper: Callable[[float], None] | None = None,
    monotonic: Callable[[], float] | None = None,
) -> Callable[[str], DocumentTransportResponse]:
    """Wrap a streaming send with the committed spacing, retry, and ceiling.

    ``max_bytes`` is the plan-declared per-document ceiling; the runner
    cross-checks that the value bound here equals the plan's, so a transport
    built with a different bound fails the run closed instead of quietly
    downloading past it.
    """
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ValueError(
            "max_bytes must be an explicit positive integer; the document "
            "ceiling is plan-owned and never defaulted."
        )
    send_fn = stream_send or httpx_streaming_send
    sleep_fn = sleeper or time.sleep
    monotonic_fn = monotonic or time.monotonic
    contract = SEC_LIVE_DOCUMENT_TRANSPORT_CONTRACT
    spacing = float(contract["min_request_spacing_seconds"])
    max_retries = int(contract["max_retries_per_url"])
    backoff = [float(x) for x in contract["retry_backoff_seconds"]]
    retry_statuses = frozenset(contract["retry_statuses"])
    chunk_bytes = int(contract["stream_chunk_bytes"])
    if len(backoff) < max_retries:
        raise ValueError(
            "retry_backoff_seconds must carry one delay per permitted retry."
        )
    last_send_at: list[float | None] = [None]

    def transport(url: str) -> DocumentTransportResponse:
        last_error: Exception | None = None
        for attempt in range(1 + max_retries):
            previous = last_send_at[0]
            if previous is not None:
                remaining = spacing - (monotonic_fn() - previous)
                if remaining > 0:
                    sleep_fn(remaining)
            last_send_at[0] = monotonic_fn()
            try:
                stream = send_fn(url)
            except Exception as exc:  # noqa: BLE001 - bounded, then propagated
                last_error = exc
                if attempt < max_retries:
                    sleep_fn(backoff[attempt])
                    continue
                raise
            outcome: DocumentTransportResponse | None = None
            try:
                if (
                    stream.status_code in retry_statuses
                    and attempt < max_retries
                ):
                    outcome = None  # retry; the body is never consumed
                else:
                    outcome = _consume(stream, url, max_bytes, chunk_bytes)
            finally:
                # Every path closes: accepted, refused, redirect, non-200,
                # a raising body iterator, and each retry transition.
                stream.close()
            if outcome is not None:
                return outcome
            sleep_fn(backoff[attempt])
        raise last_error if last_error else RuntimeError("unreachable")

    return transport
