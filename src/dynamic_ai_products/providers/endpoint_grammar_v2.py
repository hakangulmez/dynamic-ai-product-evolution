"""Exact two-operation endpoint grammar (ADR-043, E-M).

The released :func:`~dynamic_ai_products.providers.response_capture.assert_endpoint_allowed`
is left untouched: its docstring promises that query and fragment take no part in
the decision, and every E-L and E-R receipt was produced under that promise. E-M
needs the opposite rule, so it gets its own grammar rather than a mutated one.

Three measured facts drive the difference.

- A **prefix** allowlist entry admits far more than it looks like it does.
  Measured on the released matcher: a single ``/v1/projects`` entry admitted
  another publisher's ``:predict``, another location's ``:export``, and both of
  our own operations. Here matching is **exact equality** and prefix descent is
  gone.
- **Query and fragment are stripped before comparison** by the released
  normalizer, so a request carrying ``?alt=sse`` is admitted by a query-free
  entry. Here their presence is a refusal. This costs nothing: measured against
  ``google-genai==2.13.0``, only ``ListModels`` ever populates the SDK's
  ``_query``, so neither of our two operations produces a query string.
- The request URL is built by the **SDK** from base URL, api version, project and
  location -- not from the allowlist -- so a divergence between the two is
  structurally possible and the per-request check carries real weight.

This module imports ``urllib.parse`` only. It opens nothing and sends nothing.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from .errors import ProviderError

__all__ = [
    "OPERATION_LABELS",
    "assert_operation_url",
    "normalize_exact_endpoint",
    "require_operation_endpoints",
    "require_allowlist_equals_operations",
]

OPERATION_LABELS: tuple[str, ...] = ("count_tokens", "generate_content")

_OPERATION_SUFFIX: dict[str, str] = {
    "count_tokens": ":countTokens",
    "generate_content": ":generateContent",
}
_DEFAULT_HTTPS_PORT = 443


def _refuse() -> ProviderError:
    """One sanitized failure for every grammar violation.

    The reason code is deliberately the same for all of them: telling a caller
    *which* rule its URL broke would turn this boundary into an oracle.
    """
    return ProviderError("provider_response_unusable")


def normalize_exact_endpoint(url: object) -> tuple[str, str]:
    """Return ``(origin, path)`` for an exact operation URL, or refuse.

    Unlike the released normalizer this one **refuses** a query, a fragment or
    userinfo instead of discarding them, and it does not resolve ``.`` or ``..``:
    a dot segment in an operation URL is not something to tidy up, it is
    something to reject.
    """
    if not isinstance(url, str) or not url or url.strip() != url:
        raise _refuse()
    if any(character < "\x21" or character > "\x7e" for character in url):
        raise _refuse()
    split = urlsplit(url)
    if split.scheme != "https":
        raise _refuse()
    if split.query or split.fragment:
        raise _refuse()
    if split.username is not None or split.password is not None or "@" in (split.netloc or ""):
        raise _refuse()
    host = (split.hostname or "").lower()
    if not host or host != (split.hostname or "") or host.endswith("."):
        raise _refuse()
    try:
        port = split.port
    except ValueError as exc:
        raise _refuse() from exc
    if port not in (None, _DEFAULT_HTTPS_PORT):
        raise _refuse()
    path = split.path
    if not path.startswith("/") or "//" in path or path.endswith("/"):
        raise _refuse()
    if any(segment in ("", ".", "..") for segment in path.split("/")[1:]):
        raise _refuse()
    return f"https://{host}", path


def assert_operation_url(url: object, *, operation_label: str, expected: object) -> None:
    """Refuse unless ``url`` is exactly the endpoint declared for this operation.

    ``expected`` is the URL the active operation context declares, not a set to
    search. Membership in a two-entry allowlist cannot catch a crossed operation
    -- both entries are allowed -- so the check that matters is equality with the
    *one* endpoint this call is supposed to reach.
    """
    if operation_label not in _OPERATION_SUFFIX:
        raise _refuse()
    observed = normalize_exact_endpoint(url)
    declared = normalize_exact_endpoint(expected)
    if observed != declared:
        raise _refuse()
    suffix = _OPERATION_SUFFIX[operation_label]
    _, path = observed
    tail = path.rsplit("/", 1)[-1]
    if not tail.endswith(suffix) or tail == suffix:
        # The suffix must terminate a real model segment: a bare ":countTokens"
        # names no model, and a trailing "X" would be a different operation.
        raise _refuse()


def require_operation_endpoints(endpoints: object) -> dict[str, tuple[str, str]]:
    """Validate the two named endpoints of the v2 client contract.

    Both must parse, both must carry their own operation suffix, they must differ
    after normalization, and they must share one model base -- the two URLs may
    only differ in the operation.
    """
    if not isinstance(endpoints, dict) or set(endpoints) != set(OPERATION_LABELS):
        raise _refuse()
    normalized: dict[str, tuple[str, str]] = {}
    bases: set[tuple[str, str]] = set()
    for label in OPERATION_LABELS:
        url = endpoints[label]
        assert_operation_url(url, operation_label=label, expected=url)
        origin, path = normalize_exact_endpoint(url)
        normalized[label] = (origin, path)
        bases.add((origin, path[: -len(_OPERATION_SUFFIX[label])]))
    if len(set(normalized.values())) != len(OPERATION_LABELS):
        raise _refuse()
    if len(bases) != 1:
        raise _refuse()
    return normalized


def require_allowlist_equals_operations(allowlist: object, endpoints: object) -> None:
    """The authorization's allowlist is exactly the two named endpoints.

    Equality, not superset and not subset. Textual uniqueness is not enough:
    ``https://Example.COM:443/x`` and ``https://example.com/x`` are two spellings
    of one endpoint, so the comparison is on normalized pairs.
    """
    named = require_operation_endpoints(endpoints)
    if not isinstance(allowlist, (list, tuple)) or len(allowlist) != len(OPERATION_LABELS):
        raise _refuse()
    observed: set[tuple[str, str]] = set()
    for entry in allowlist:
        normalized = normalize_exact_endpoint(entry)
        if normalized in observed:
            raise _refuse()
        observed.add(normalized)
    if observed != set(named.values()):
        raise _refuse()
