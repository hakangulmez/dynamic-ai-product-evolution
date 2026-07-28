"""Caller-supplied, hash-pinned web collection request plan (ADR-032).

The live collector may request only URLs declared here. The plan is a
run-external, write-once input prepared and approved before collection; the
collector never authors it.

Independent request authority comes from this artifact alone. Redirect hops are
response-derived continuations of an already-authorized request and are handled
in ``transport``; they never widen the plan.
"""

from __future__ import annotations

import json
import re
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

from .canonical_url import canonical_url
from .domains import host_of, is_official_origin
from .errors import CollectionError

__all__ = [
    "ACCESS_CHANNELS",
    "ARCHIVE_HOST_ALLOWLIST",
    "CONTENT_FAMILIES",
    "PLAN_CONTRACT",
    "REQUIRED_CONTENT_FAMILIES",
    "TEMPORAL_ROUTES",
    "admitted_urls",
    "entry_sort_key",
    "load_request_plan",
    "parse_wayback_capture",
    "robots_url_for",
    "safe_date_key",
    "validate_request_plan",
]

# The single closed Pilot 0 archive grammar. Archive authority is structural,
# never a substring match: only a well-formed Wayback capture on this host,
# whose embedded original URL canonicalizes to the entry's source_url, is
# admitted.
ARCHIVE_HOST_ALLOWLIST: frozenset[str] = frozenset({"web.archive.org"})

# /web/<timestamp><optional modifier>/<embedded original url>
_WAYBACK_PATH_RE = re.compile(r"^/web/(\d{4,14})([a-z]{2}_)?/(https?://.+)$")

PLAN_CONTRACT = "web_collection_request_plan@0.1.0"

CONTENT_FAMILIES: tuple[str, ...] = (
    "official_ir",
    "product_pages",
    "developer_docs",
    "newsroom",
)
REQUIRED_CONTENT_FAMILIES: tuple[str, ...] = (
    "official_ir",
    "product_pages",
    "developer_docs",
)
ACCESS_CHANNELS: tuple[str, ...] = ("live", "archive")
TEMPORAL_ROUTES: tuple[str, ...] = ("dated_document", "archive")

_ENTRY_FIELDS = frozenset(
    {
        "content_family",
        "access_channel",
        "source_url",
        "archive_url",
        "purpose",
        "expected_temporal_route",
        "evidence_target",
    }
)
_PLAN_FIELDS = frozenset({"contract", "company_id", "observation_cutoff_date", "entries"})

_DATE_KEY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_COMPANY_ID_RE = re.compile(r"^CIK[0-9]{10}$")


def safe_date_key(value: str) -> str:
    """Validate a date-key path segment.

    Never interpolate an unrestricted timestamp into a path. The key must be a
    strict ``YYYY-MM-DD`` real calendar date with no separator or traversal
    sequence.
    """
    if not isinstance(value, str) or not _DATE_KEY_RE.fullmatch(value):
        raise CollectionError(
            f"date key must match YYYY-MM-DD: {value!r}",
            reason_code="date_key_invalid",
        )
    if "/" in value or "\\" in value or ".." in value:
        raise CollectionError(
            f"date key contains a path separator or traversal: {value!r}",
            reason_code="date_key_invalid",
        )
    try:
        year, month, day = (int(part) for part in value.split("-"))
        date(year, month, day)
    except ValueError as exc:
        raise CollectionError(
            f"date key is not a real calendar date: {value!r}",
            reason_code="date_key_invalid",
        ) from exc
    return value


def parse_wayback_capture(archive_url: str) -> tuple[str, str]:
    """Parse a Wayback capture URL into ``(timestamp, embedded_original_url)``.

    Structural, not textual. The host must be exactly an allowlisted archive
    host, the path must match the Wayback capture grammar, and the embedded
    original must itself be a well-formed absolute http(s) URL.

    A query or fragment on the capture belongs to the embedded original — a
    genuine capture of ``…/x?a=b`` is spelled ``/web/<ts>/https://host/x?a=b``
    — so it is reattached to the embedded URL rather than banned. A *spoofed*
    query is caught where it matters: the reconstructed original must
    canonicalize to exactly the entry's ``source_url``.
    """
    from .domains import split_url

    parts, _, host, _ = split_url(archive_url)
    if host not in ARCHIVE_HOST_ALLOWLIST:
        raise CollectionError(
            f"archive host is not allowlisted: {host}",
            reason_code="archive_host_not_allowed",
        )
    match = _WAYBACK_PATH_RE.match(parts.path)
    if match is None:
        raise CollectionError(
            f"not a well-formed wayback capture: {archive_url}",
            reason_code="archive_capture_malformed",
        )
    timestamp, _modifier, embedded = match.groups()
    if parts.query:
        embedded = f"{embedded}?{parts.query}"
    if parts.fragment:
        embedded = f"{embedded}#{parts.fragment}"
    # The embedded original must itself be a valid absolute URL.
    split_url(embedded)
    return timestamp, embedded


def entry_sort_key(entry: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(entry.get("content_family", "")),
        str(entry.get("access_channel", "")),
        str(entry.get("source_url", "")),
        str(entry.get("archive_url") or ""),
    )


def _validate_entry(entry: Any, index: int) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise CollectionError(
            f"plan entry {index} is not an object", reason_code="request_plan_invalid"
        )
    unknown = sorted(set(entry) - _ENTRY_FIELDS)
    if unknown:
        raise CollectionError(
            f"plan entry {index} carries undeclared fields: {unknown}",
            reason_code="request_plan_invalid",
        )
    missing = sorted(_ENTRY_FIELDS - set(entry) - {"archive_url"})
    if missing:
        raise CollectionError(
            f"plan entry {index} is missing required fields: {missing}",
            reason_code="request_plan_invalid",
        )

    family = entry["content_family"]
    channel = entry["access_channel"]
    route = entry["expected_temporal_route"]
    if family not in CONTENT_FAMILIES:
        raise CollectionError(
            f"plan entry {index} has an unknown content_family: {family!r}",
            reason_code="request_plan_invalid",
        )
    if channel not in ACCESS_CHANNELS:
        raise CollectionError(
            f"plan entry {index} has an unknown access_channel: {channel!r}",
            reason_code="request_plan_invalid",
        )
    if route not in TEMPORAL_ROUTES:
        raise CollectionError(
            f"plan entry {index} has an unknown expected_temporal_route: {route!r}",
            reason_code="request_plan_invalid",
        )

    for field in ("purpose", "evidence_target"):
        value = entry[field]
        if not isinstance(value, str) or not value.strip():
            raise CollectionError(
                f"plan entry {index} requires a non-blank {field}",
                reason_code="request_plan_invalid",
            )

    source_url = entry["source_url"]
    if not is_official_origin(source_url):
        raise CollectionError(
            f"plan entry {index} source_url is outside the official apex: {source_url}",
            reason_code="third_party_domain_excluded",
        )

    archive_url = entry.get("archive_url")
    if channel == "archive":
        if not isinstance(archive_url, str) or not archive_url.strip():
            raise CollectionError(
                f"plan entry {index} with access_channel=archive requires an archive_url",
                reason_code="request_plan_invalid",
            )
        if is_official_origin(archive_url):
            raise CollectionError(
                f"plan entry {index} archive host must not be the official origin",
                reason_code="archive_host_as_origin",
            )
        # Structural archive authority: parse the capture and require its
        # embedded original to canonicalize to exactly this entry's source_url.
        _timestamp, embedded_original = parse_wayback_capture(archive_url)
        if canonical_url(embedded_original) != canonical_url(source_url):
            raise CollectionError(
                f"plan entry {index} capture embeds a different original URL",
                reason_code="archive_original_host_mismatch",
                detail=(
                    f"embedded {canonical_url(embedded_original)} != "
                    f"source {canonical_url(source_url)}"
                ),
            )
    else:
        if archive_url is not None:
            raise CollectionError(
                f"plan entry {index} with access_channel=live must not carry archive_url",
                reason_code="request_plan_invalid",
            )
        # A live fetch can only ever be admitted on publication_date.
        if route != "dated_document":
            raise CollectionError(
                f"plan entry {index}: live entries require the dated_document route",
                reason_code="temporal_route_inconsistent",
            )

    normalized = {field: entry.get(field) for field in sorted(_ENTRY_FIELDS)}
    return normalized


def validate_request_plan(payload: Any) -> dict[str, Any]:
    """Strictly validate a request plan and return its normalized form."""
    if not isinstance(payload, dict):
        raise CollectionError("request plan must be an object", reason_code="request_plan_invalid")
    unknown = sorted(set(payload) - _PLAN_FIELDS)
    if unknown:
        raise CollectionError(
            f"request plan carries undeclared fields: {unknown}",
            reason_code="request_plan_invalid",
        )
    missing = sorted(_PLAN_FIELDS - set(payload))
    if missing:
        raise CollectionError(
            f"request plan is missing required fields: {missing}",
            reason_code="request_plan_invalid",
        )
    if payload["contract"] != PLAN_CONTRACT:
        raise CollectionError(
            f"unsupported request-plan contract: {payload['contract']!r}",
            reason_code="request_plan_invalid",
        )

    # Top-level identity and date are enforced here, not merely described by
    # the schema: the loader is the runtime authority for the plan contract.
    company_id = payload["company_id"]
    if not isinstance(company_id, str) or not _COMPANY_ID_RE.fullmatch(company_id):
        raise CollectionError(
            "request plan company_id must match ^CIK[0-9]{10}$",
            reason_code="request_plan_invalid",
        )
    cutoff = payload["observation_cutoff_date"]
    if not isinstance(cutoff, str):
        raise CollectionError(
            "request plan observation_cutoff_date must be a real YYYY-MM-DD date",
            reason_code="request_plan_invalid",
        )
    try:
        safe_date_key(cutoff)
    except CollectionError as exc:
        raise CollectionError(
            "request plan observation_cutoff_date must be a real YYYY-MM-DD date",
            reason_code="request_plan_invalid",
        ) from exc

    entries = payload["entries"]
    if not isinstance(entries, list) or not entries:
        raise CollectionError(
            "request plan carries no entries", reason_code="request_plan_invalid"
        )

    validated = [_validate_entry(entry, index) for index, entry in enumerate(entries)]

    keys = [entry_sort_key(entry) for entry in validated]
    if keys != sorted(keys):
        raise CollectionError(
            "request-plan entries are not in canonical order",
            reason_code="plan_ordering_invalid",
        )
    identity = [(e["source_url"], e["access_channel"], e.get("archive_url") or "") for e in validated]
    if len(set(identity)) != len(identity):
        raise CollectionError(
            "request plan contains duplicate entries",
            reason_code="plan_duplicate_entry",
        )

    return {
        "contract": payload["contract"],
        "company_id": payload["company_id"],
        "observation_cutoff_date": payload["observation_cutoff_date"],
        "entries": validated,
    }


def load_request_plan(path: str | Path) -> tuple[dict[str, Any], str]:
    """Load, strictly validate, and hash a request plan. Returns (plan, sha256)."""
    target = Path(path)
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise CollectionError(
            f"request plan is unreadable: {target}", reason_code="request_plan_invalid"
        ) from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CollectionError(
            "request plan is not valid UTF-8 JSON", reason_code="request_plan_invalid"
        ) from exc
    return validate_request_plan(payload), sha256(raw).hexdigest()


def admitted_urls(plan: dict[str, Any]) -> frozenset[str]:
    """The exact set of URLs an independently initiated request may target."""
    urls: set[str] = set()
    for entry in plan["entries"]:
        if entry["access_channel"] == "archive":
            urls.add(entry["archive_url"])
        else:
            urls.add(entry["source_url"])
    return frozenset(urls)


def robots_url_for(host: str) -> str:
    """The deterministic robots URL for a host named by the plan."""
    if not isinstance(host, str) or not host.strip():
        raise CollectionError("robots host must be non-blank", reason_code="url_invalid")
    return f"https://{host.lower()}/robots.txt"


def planned_hosts(plan: dict[str, Any]) -> frozenset[str]:
    """Every host named by the plan, across both origin and archive roles."""
    hosts: set[str] = set()
    for entry in plan["entries"]:
        hosts.add(host_of(entry["source_url"]))
        if entry.get("archive_url"):
            hosts.add(host_of(entry["archive_url"]))
    return frozenset(hosts)
