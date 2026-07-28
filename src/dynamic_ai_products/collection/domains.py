"""SEC-derived official-domain trust boundary (ADR-032, lock v4 section 2).

The frozen boundary is the registrable apex ``hubspot.com``, confirmed present
in the already-committed, hash-pinned SEC bytes. A URL is an official-origin
candidate iff its host is exactly the apex or a strict subdomain of it;
subdomains need not appear literally in the SEC bytes.

Archive hosts are transport-only exceptions. An archive may serve a capture of
an allowed original URL, but it can never become a canonical source origin.
"""

from __future__ import annotations

from hashlib import sha256
from urllib.parse import urlsplit

from .errors import CollectionError

__all__ = [
    "OFFICIAL_APEX",
    "SEC_DERIVATION_PINS",
    "derive_official_apex",
    "host_of",
    "is_official_origin",
    "require_official_origin",
    "split_url",
]

OFFICIAL_APEX = "hubspot.com"

# The committed SEC bytes that anchor the derivation (ADR-030 / ADR-031).
SEC_DERIVATION_PINS: dict[str, str] = {
    "submissions": "6d2add25a7753cefa486d224c862f15b7b81a28707562a73848983587fdb8b19",
    "filing_index": "c6876565db97200958b4b30f2fcfe9da214d86836643f84d30fcb1fd93699880",
    "primary_document": (
        "36257e638feb2059e3bbc58461938d6ffc11dd280e12d7af0f06c5394bf40b12"
    ),
}


def _verify_pin(name: str, payload: bytes, supplied_sha256: str) -> None:
    """Hash-verify one raw SEC input against its supplied and committed pin."""
    if not isinstance(payload, (bytes, bytearray)):
        raise CollectionError(
            f"apex derivation requires raw {name} bytes",
            reason_code="apex_derivation_failed",
        )
    observed = sha256(bytes(payload)).hexdigest()
    if observed != supplied_sha256:
        raise CollectionError(
            f"{name} bytes do not match the supplied pin",
            reason_code="apex_derivation_failed",
            detail=f"expected {supplied_sha256}, observed {observed}",
        )
    if observed != SEC_DERIVATION_PINS[name]:
        raise CollectionError(
            f"{name} pin is not the committed Pilot 0 pin",
            reason_code="apex_derivation_failed",
        )


def derive_official_apex(
    *,
    submissions_bytes: bytes,
    submissions_sha256: str,
    filing_index_bytes: bytes,
    filing_index_sha256: str,
    primary_document_bytes: bytes,
    primary_document_sha256: str,
) -> str:
    """Confirm the apex against all three pinned SEC raw inputs.

    Every one of the committed SEC bytes is bound before the apex literal is
    tested, so the trust boundary rests on the whole hash-verified filing
    triple rather than on a single document. No search engine, no third-party
    directory, no live lookup participates.
    """
    _verify_pin("submissions", submissions_bytes, submissions_sha256)
    _verify_pin("filing_index", filing_index_bytes, filing_index_sha256)
    _verify_pin("primary_document", primary_document_bytes, primary_document_sha256)

    if OFFICIAL_APEX.encode("ascii") not in bytes(primary_document_bytes):
        raise CollectionError(
            f"apex {OFFICIAL_APEX!r} does not occur in the filing bytes",
            reason_code="apex_derivation_failed",
        )
    return OFFICIAL_APEX


def split_url(url: str):
    """urlsplit with every malformed-URL failure sanitized.

    ``urlsplit`` defers validation: an invalid port raises ``ValueError`` only
    when ``.port`` or ``.hostname`` is read. Credentials are rejected outright
    so a userinfo segment can never smuggle a host past the apex check.
    """
    if not isinstance(url, str) or not url.strip():
        raise CollectionError("url must be a non-empty string", reason_code="url_invalid")
    try:
        parts = urlsplit(url.strip())
        scheme = parts.scheme.lower()
        host = parts.hostname
        port = parts.port
        username = parts.username
        password = parts.password
    except ValueError as exc:
        raise CollectionError(
            f"malformed url: {url}", reason_code="url_invalid"
        ) from exc
    if scheme not in {"http", "https"}:
        raise CollectionError(f"unsupported scheme in {url}", reason_code="url_invalid")
    if username is not None or password is not None:
        raise CollectionError(
            f"url must not carry credentials: {url}", reason_code="url_invalid"
        )
    if not host:
        raise CollectionError(f"url has no host: {url}", reason_code="url_invalid")
    return parts, scheme, host.lower(), port


def host_of(url: str) -> str:
    """Lowercase hostname of a URL, without port or credentials."""
    _, _, host, _ = split_url(url)
    return host


def is_official_origin(url: str, apex: str = OFFICIAL_APEX) -> bool:
    """True iff the host is the apex itself or a strict subdomain of it."""
    host = host_of(url)
    return host == apex or host.endswith("." + apex)


def require_official_origin(url: str, apex: str = OFFICIAL_APEX) -> str:
    if not is_official_origin(url, apex):
        raise CollectionError(
            f"host outside the official apex boundary: {url}",
            reason_code="third_party_domain_excluded",
        )
    return url
