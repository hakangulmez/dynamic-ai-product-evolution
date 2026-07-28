"""Committed, versioned collection transport and the request-authority gate.

ADR-030 recorded that Pilot 0's SEC bytes were collected by a pre-refactor,
uncommitted client, leaving no committed executable collection-client identity.
This module closes that gap: the client contract is declared here, hashed, and
recorded in every manifest and in the run identity.

Three request classes exist, and nothing else may issue an HTTP request:

1. an **independently initiated document request**, permitted only for an exact
   request-plan entry;
2. a **robots request**, permitted only as the deterministic robots URL for a
   host named by a plan entry;
3. a **redirect hop**, which is NOT an independently initiated candidate
   request but a response-derived continuation of one already-authorized
   request, bounded by the rules in :func:`follow_redirects`.

No crawling, link following, sitemap expansion, or cross-entry final-URL reuse
is possible: a final URL is canonical for its own planned entry only and never
becomes authority for another request.

The transport itself is injected. This module performs no network I/O of its
own, so the offline test suite never opens a socket.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Callable

from .domains import OFFICIAL_APEX, host_of, is_official_origin
from .errors import CollectionError
from .request_plan import admitted_urls, planned_hosts, robots_url_for

__all__ = [
    "CLIENT_CONTRACT",
    "MAX_REDIRECT_HOPS",
    "RATE_LIMIT_POLICY_VERSION",
    "ROBOTS_POLICY_VERSION",
    "RedirectHop",
    "RequestOutcome",
    "TransportResponse",
    "client_contract_hash",
    "follow_redirects",
    "require_planned_request",
    "require_planned_robots",
]

MAX_REDIRECT_HOPS = 5
ROBOTS_POLICY_VERSION = "robots_policy_v1"
RATE_LIMIT_POLICY_VERSION = "rate_limit_policy_v1"

# The declared, committed client contract. Its hash is an input to the run
# identity, so changing any of these values changes the run root.
CLIENT_CONTRACT: dict[str, Any] = {
    "client": "dynamic_ai_products.collection.transport",
    "client_version": "0.1.0",
    "user_agent": (
        "dynamic-ai-product-evolution research hakanzekigulmez@gmail.com"
    ),
    "max_redirect_hops": MAX_REDIRECT_HOPS,
    "max_requests_per_second": 1.0,
    "min_request_spacing_seconds": 1.0,
    "max_retries_per_url": 1,
    "archive_min_request_spacing_seconds": 2.0,
    "robots_policy_version": ROBOTS_POLICY_VERSION,
    "rate_limit_policy_version": RATE_LIMIT_POLICY_VERSION,
}


def client_contract_hash() -> str:
    """SHA-256 over the canonical client contract."""
    import json

    payload = json.dumps(
        CLIENT_CONTRACT, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return sha256(payload).hexdigest()


@dataclass(frozen=True)
class TransportResponse:
    """One HTTP response as seen by the collector."""

    status_code: int
    final_url: str
    content: bytes
    location: str | None = None


@dataclass(frozen=True)
class RedirectHop:
    """One response-derived continuation of an already-authorized request."""

    url: str
    status_code: int


@dataclass(frozen=True)
class RequestOutcome:
    """The result of one authorized request plus its recorded chain."""

    initial_url: str
    final_url: str
    status_code: int
    content: bytes
    redirect_hops: tuple[RedirectHop, ...] = field(default=())


_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


def require_planned_request(url: str, plan: dict[str, Any]) -> str:
    """Authorize an independently initiated document request.

    Only an exact request-plan URL may be requested. Anything else is refused
    before any transport call.
    """
    if url not in admitted_urls(plan):
        raise CollectionError(
            f"url is not declared in the request plan: {url}",
            reason_code="undeclared_url_refused",
        )
    return url


def require_planned_robots(host: str, plan: dict[str, Any]) -> str:
    """Authorize the deterministic robots URL for a plan-named host."""
    normalized = host.lower()
    if normalized not in planned_hosts(plan):
        raise CollectionError(
            f"robots requested for a host outside the plan: {host}",
            reason_code="undeclared_url_refused",
        )
    return robots_url_for(normalized)


def _hop_within_boundary(url: str, *, access_channel: str, archive_host: str | None) -> bool:
    if access_channel == "live":
        return is_official_origin(url, OFFICIAL_APEX)
    return host_of(url) == (archive_host or "")


def follow_redirects(
    *,
    initial_url: str,
    entry: dict[str, Any],
    transport: Callable[[str], TransportResponse],
) -> RequestOutcome:
    """Issue one authorized request and follow its response-derived hops.

    A redirect hop is permitted only when it follows an HTTP redirect response
    for this request, stays inside the official apex (live entries) or this
    entry's declared archive host (archive entries), keeps the chain within
    ``MAX_REDIRECT_HOPS``, contains no loop, and is recorded.

    The resulting final URL is canonical for THIS entry only. It is returned,
    never cached as authority, and can never satisfy another entry's request.
    """
    access_channel = entry["access_channel"]
    archive_host = (
        host_of(entry["archive_url"]) if access_channel == "archive" else None
    )

    current = initial_url
    seen = [current]
    hops: list[RedirectHop] = []

    for _ in range(MAX_REDIRECT_HOPS + 1):
        response = transport(current)
        if response.status_code not in _REDIRECT_STATUSES:
            # Terminal identity fails closed: the response must name the URL we
            # actually requested. Substituting `current` for a blank or
            # mismatched final_url would silently invent provenance.
            if not response.final_url or not response.final_url.strip():
                raise CollectionError(
                    f"terminal response carries no final_url for {current}",
                    reason_code="terminal_url_mismatch",
                )
            if response.final_url != current:
                raise CollectionError(
                    f"terminal final_url does not match the requested url: "
                    f"requested {current}, reported {response.final_url}",
                    reason_code="terminal_url_mismatch",
                )
            return RequestOutcome(
                initial_url=initial_url,
                final_url=response.final_url,
                status_code=response.status_code,
                content=response.content,
                redirect_hops=tuple(hops),
            )

        nxt = response.location
        if not nxt:
            raise CollectionError(
                f"redirect response without a location for {current}",
                reason_code="redirect_chain_exceeded",
            )
        if len(hops) >= MAX_REDIRECT_HOPS:
            raise CollectionError(
                f"redirect chain exceeded {MAX_REDIRECT_HOPS} hops for {initial_url}",
                reason_code="redirect_chain_exceeded",
            )
        if nxt in seen:
            raise CollectionError(
                f"redirect loop detected for {initial_url}",
                reason_code="redirect_chain_exceeded",
            )
        if not _hop_within_boundary(
            nxt, access_channel=access_channel, archive_host=archive_host
        ):
            raise CollectionError(
                f"redirect hop leaves the permitted boundary: {nxt}",
                reason_code="allowlist_violation",
            )
        hops.append(RedirectHop(url=nxt, status_code=response.status_code))
        seen.append(nxt)
        current = nxt

    raise CollectionError(
        f"redirect chain exceeded {MAX_REDIRECT_HOPS} hops for {initial_url}",
        reason_code="redirect_chain_exceeded",
    )
