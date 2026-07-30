"""Connector-side half of the two-key handshake (ADR-035).

The runner validates the governance chain and produces a verified digest; this
module only checks that the digest matches the one the connector was configured
for. Neither half alone authorizes a run: the runner proves the artifact is
valid, the connector proves it was built for that same artifact.

**Limit, stated plainly.** A caller inside this process that deliberately
fabricates both the digest and the request cap can satisfy both halves. That is
a ``noncanonical_experiment`` under SPEC-027, requires separate approval, and
may never enter an evaluation or production record. What is guaranteed is
detectability — a canonical run carries eight artifacts with the authorization
bound as the seventh manifest role — not prevention.
"""

from __future__ import annotations

import hmac
import re

from .errors import ProviderError
from .response_capture import normalize_endpoint

__all__ = [
    "SHA256_PATTERN",
    "require_authorization_digest",
    "require_endpoint_allowlist_match",
    "require_endpoint_allowlist_subset",
    "require_request_cap",
]

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def require_authorization_digest(expected: object, supplied: object) -> str:
    """Fail closed unless both digests are well formed and identical.

    Comparison is constant-time: a timing side channel on an authorization
    digest would let it be discovered a character at a time.
    """
    if not isinstance(expected, str) or not SHA256_PATTERN.fullmatch(expected):
        raise ProviderError("live_call_not_authorized")
    if not isinstance(supplied, str) or not SHA256_PATTERN.fullmatch(supplied):
        raise ProviderError("live_call_not_authorized")
    if not hmac.compare_digest(expected, supplied):
        raise ProviderError("live_call_not_authorized")
    return supplied


def require_request_cap(cap: object, *, policy_maximum: int) -> int:
    """The runner-supplied attempt cap. It may only lower the E-P policy."""
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
        raise ProviderError("live_call_not_authorized")
    if cap > policy_maximum:
        raise ProviderError("live_call_not_authorized")
    return cap


def _normalized_allowlist(entries: object) -> frozenset[tuple[str, str]]:
    """Normalize an endpoint allowlist to a comparable set, or refuse.

    Comparison must be semantic, not textual: ``https://Example.COM:443/v1`` and
    ``https://example.com/v1`` are the same endpoint, and a textual test would
    call two identical allowlists different. Normalization reuses the same rules
    the capture client applies per request, so there is one endpoint grammar
    rather than two.
    """
    if not isinstance(entries, (list, tuple)) or not entries:
        raise ProviderError("live_call_not_authorized")
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        try:
            normalized = normalize_endpoint(entry)
        except ProviderError as exc:
            # A malformed authorization entry is an authorization failure, not a
            # response failure.
            raise ProviderError("live_call_not_authorized") from exc
        if normalized in seen:
            # A duplicate means the two lists cannot be compared by size and
            # hides how many distinct endpoints were actually authorized.
            raise ProviderError("live_call_not_authorized")
        seen.add(normalized)
    return frozenset(seen)


def require_endpoint_allowlist_match(
    configured: object, supplied: object
) -> frozenset[tuple[str, str]]:
    """Third key: the authorization's allowlist must be the connector's own.

    Validating the allowlist as artifact content is not enough — a connector
    holding the right digest and cap could still carry a broader or different
    allowlist, and every per-request check would then be measured against the
    wrong set. Binding it here makes the authorized endpoints
    execution-affecting rather than merely recorded.
    """
    configured_set = _normalized_allowlist(configured)
    supplied_set = _normalized_allowlist(supplied)
    if configured_set != supplied_set:
        raise ProviderError("live_call_not_authorized")
    return configured_set


def require_endpoint_allowlist_subset(
    superset: object, subset: object
) -> frozenset[tuple[str, str]]:
    """The authorized endpoints may narrow the enablement, never widen it.

    A run authorization exists precisely so one run can use less than its
    enablement allows, so equality would be the wrong rule. Widening is the
    thing that must be impossible: a single endpoint present in the
    authorization but absent from the enablement means the run would reach
    somewhere the enablement never permitted.

    Normalization is the same grammar the capture client applies per request, so
    there is one endpoint grammar for the whole chain rather than one per layer.
    """
    superset_set = _normalized_allowlist(superset)
    subset_set = _normalized_allowlist(subset)
    if not subset_set <= superset_set:
        raise ProviderError("live_call_not_authorized")
    return subset_set
