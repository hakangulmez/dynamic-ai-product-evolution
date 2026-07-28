"""Deterministic URL canonicalization ``canonical_url_v1`` (ADR-032).

Lowercase scheme and host, strip default ports, drop the fragment, drop a
declared tracking-parameter list, preserve path case and meaningful query
parameters. Versioned so every canonicalization decision is auditable.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlunsplit

from .domains import split_url
from .errors import CollectionError

__all__ = [
    "CANONICALIZATION_VERSION",
    "TRACKING_PARAMETERS",
    "canonical_url",
    "duplicate_clusters",
]

CANONICALIZATION_VERSION = "canonical_url_v1"

# Declared, closed list. Anything not named here is a meaningful parameter.
TRACKING_PARAMETERS: tuple[str, ...] = (
    "fbclid",
    "gclid",
    "hsa_acc",
    "hsa_cam",
    "hsa_grp",
    "hsCtaTracking",
    "mkt_tok",
    "msclkid",
    "ref",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
)

_DEFAULT_PORTS = {"http": 80, "https": 443}


def canonical_url(url: str) -> str:
    """Return the ``canonical_url_v1`` form of ``url``."""
    # split_url sanitizes every malformed-URL failure (invalid port, bad
    # scheme, credentials) into CollectionError; no ValueError escapes.
    parts, scheme, host, port = split_url(url)

    netloc = host
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        netloc = f"{host}:{port}"

    # Path case is preserved; only an empty path is normalized to "/".
    path = parts.path or "/"

    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in TRACKING_PARAMETERS
    ]
    query = urlencode(sorted(kept), doseq=True)

    # The fragment is always dropped.
    return urlunsplit((scheme, netloc, path, query, ""))


def duplicate_clusters(records: list[dict]) -> dict[str, list[dict]]:
    """Group records by exact ``content_sha256``.

    Exact-hash equality only. Near-duplicate similarity is SPEC-007 and stays
    out of scope for this increment.
    """
    clusters: dict[str, list[dict]] = {}
    for record in records:
        digest = record.get("content_sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise CollectionError(
                "record carries no usable content_sha256",
                reason_code="content_hash_mismatch",
            )
        clusters.setdefault(digest, []).append(record)
    return clusters
