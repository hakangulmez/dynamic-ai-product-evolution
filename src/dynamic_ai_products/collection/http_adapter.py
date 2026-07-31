"""Generic single-send HTTP transport adapter (ADR-037, E-C-D).

**One send, one client, no policy.** This module is deliberately URL-policy
neutral: it does not know which URLs are allowed, follows no redirects, and
decides nothing about routes. It performs exactly one request and reports what
came back. Authorization, the frozen URL pairs, spacing and persistence all live
in :mod:`~dynamic_ai_products.collection.documentation_policy`, which is the only
production module permitted to import this one.

**Why a fresh client per send.** A reused ``httpx.Client`` accepts ``Set-Cookie``
from one response and automatically sends ``Cookie`` on the next — measured, not
assumed. One client per send makes cross-send cookie state impossible rather
than merely discouraged, so a redirect hop and a later evidence entry cannot
share a jar.

**Why ``trust_env=False`` is not the keylog guarantee.** It isolates proxies and
netrc, and it does **not** stop ``SSLKEYLOGFILE`` from creating a keylog file —
also measured. The refusal for that lives in the policy layer's preflight and is
rechecked here immediately before every client construction.

**Timeout semantics, stated honestly.** ``httpx.Timeout(30.0)`` resolves to four
independent phase deadlines (connect, read, write, pool), not one 30-second
total wall clock. No total ceiling is claimed, because none is implemented.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

import httpx

from .errors import CollectionError
from .publication import canonical_json_bytes

__all__ = [
    "ADAPTER_CONTRACT",
    "CHUNK_BYTES",
    "MAX_ENTITY_BYTES_PER_RESPONSE",
    "PHASE_TIMEOUT_SECONDS",
    "USER_AGENT",
    "AdapterResponse",
    "TransportSend",
    "adapter_contract_bytes",
    "send_once",
]

USER_AGENT = (
    "dynamic-ai-product-evolution documentation-evidence/0.1.0 "
    "(research; hakanzekigulmez@gmail.com)"
)
PHASE_TIMEOUT_SECONDS = 30.0
CHUNK_BYTES = 64 * 1024
MAX_ENTITY_BYTES_PER_RESPONSE = 8 * 1024 * 1024

# The declared, committed adapter contract. Its hash is an input to the attempt
# identity, so changing any value changes the attempt root.
ADAPTER_CONTRACT: dict[str, Any] = {
    "contract": "documentation_transport_client@0.1.0",
    "adapter_module": "dynamic_ai_products.collection.http_adapter",
    "adapter_version": "0.1.0",
    "user_agent": USER_AGENT,
    # Four phase deadlines, not one total. Named individually so no reader can
    # mistake this for a wall-clock ceiling.
    "connect_timeout_seconds": PHASE_TIMEOUT_SECONDS,
    "read_timeout_seconds": PHASE_TIMEOUT_SECONDS,
    "write_timeout_seconds": PHASE_TIMEOUT_SECONDS,
    "pool_timeout_seconds": PHASE_TIMEOUT_SECONDS,
    "total_wall_clock_deadline": None,
    "total_attempts": 1,
    "retry_policy": "none",
    "automatic_redirects_disabled": True,
    "trust_env": False,
    "tls_verify": True,
    "chunk_bytes": CHUNK_BYTES,
    "max_entity_bytes_per_response": MAX_ENTITY_BYTES_PER_RESPONSE,
    "client_lifecycle": "one_client_per_send",
}


@dataclass(frozen=True)
class AdapterResponse:
    """What one send returned. ``entity_bytes`` is None unless requested."""

    status: int
    location: str | None
    headers: Mapping[str, str]
    final_url: str
    entity_bytes: bytes | None
    decompressed_byte_count: int


class TransportSend(Protocol):
    """The internal seam. Offline tests substitute this; callers cannot."""

    def __call__(
        self,
        *,
        url: str,
        user_agent: str,
        timeout_seconds: float,
        max_entity_bytes: int,
        iterate_body: bool,
    ) -> AdapterResponse:  # pragma: no cover - structural only
        ...


def adapter_contract_bytes() -> bytes:
    """Canonical bytes of the declared contract, for hashing.

    Uses the repository convention -- sorted keys, compact separators, UTF-8 and
    exactly one trailing newline -- so this serializer cannot drift from the one
    every other collection artifact uses.
    """
    return canonical_json_bytes(ADAPTER_CONTRACT)


def require_no_tls_keylog() -> None:
    """Refuse while a TLS keylog destination is configured.

    Presence only: the value is never read, logged or interpolated. A keylog
    would write session secrets for every connection this process opens, and
    ``trust_env=False`` does not prevent it.
    """
    if "SSLKEYLOGFILE" in os.environ:
        raise CollectionError(
            "a TLS key log destination is configured in the environment; "
            "refusing to construct any client",
            reason_code="tls_keylog_environment_present",
        )


def send_once(
    *,
    url: str,
    user_agent: str = USER_AGENT,
    timeout_seconds: float = PHASE_TIMEOUT_SECONDS,
    max_entity_bytes: int = MAX_ENTITY_BYTES_PER_RESPONSE,
    iterate_body: bool,
) -> AdapterResponse:
    """Perform exactly one request with a fresh client, then close it.

    ``iterate_body=False`` is how a redirect hop is fetched: the status and
    headers are read and the response is closed **without consuming the body**,
    so a hostile multi-gigabyte redirect payload is never downloaded.
    """
    require_no_tls_keylog()

    timeout = httpx.Timeout(
        connect=timeout_seconds,
        read=timeout_seconds,
        write=timeout_seconds,
        pool=timeout_seconds,
    )
    headers = {"User-Agent": user_agent, "Accept": "text/html"}

    try:
        with httpx.Client(
            follow_redirects=False,
            trust_env=False,
            verify=True,
            timeout=timeout,
            headers=headers,
        ) as client:
            with client.stream("GET", url) as response:
                observed = str(response.request.url)
                if not observed or observed != url:
                    # Checked before status, Location or any byte is trusted: a
                    # transport that answered a different URL than the one
                    # authorized must not influence the route at all.
                    raise CollectionError(
                        "the transport answered a different request identity "
                        "than the one supplied",
                        reason_code="response_request_identity_mismatch",
                    )
                status = int(response.status_code)
                location = response.headers.get("location")
                response_headers = {k.lower(): v for k, v in response.headers.items()}

                if not iterate_body:
                    return AdapterResponse(
                        status=status,
                        location=location,
                        headers=response_headers,
                        final_url=observed,
                        entity_bytes=None,
                        decompressed_byte_count=0,
                    )

                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes(CHUNK_BYTES):
                    # Refuse BEFORE appending, so oversized bytes never become
                    # an authoritative object even transiently.
                    if total + len(chunk) > max_entity_bytes:
                        raise CollectionError(
                            "the decompressed entity body exceeds the "
                            "per-response limit",
                            reason_code="entity_too_large",
                        )
                    chunks.append(chunk)
                    total += len(chunk)
                payload = b"".join(chunks)
                return AdapterResponse(
                    status=status,
                    location=location,
                    headers=response_headers,
                    final_url=observed,
                    entity_bytes=payload,
                    decompressed_byte_count=total,
                )
    except CollectionError:
        raise
    except httpx.TimeoutException:
        raise CollectionError(
            "the request exceeded a declared phase timeout",
            reason_code="transport_timeout",
        ) from None
    except Exception:  # noqa: BLE001 - the transport seam is total
        # Sanitized: no upstream text, URL, header value or byte reaches here.
        raise CollectionError(
            "the request could not be completed", reason_code="transport_failed"
        ) from None
