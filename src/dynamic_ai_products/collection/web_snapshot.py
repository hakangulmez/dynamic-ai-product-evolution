"""Stage 03 immutable raw storage and snapshot metadata (SPEC-005, ADR-032).

Raw bytes are written write-once through the shared provenance primitive and
addressed by a path whose every segment is a closed vocabulary or a strict
pattern. No unrestricted timestamp is ever interpolated into a path segment.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..provenance import WriteOnceError, write_bytes_once
from .errors import CollectionError, translate_write_once_error
from .request_plan import CONTENT_FAMILIES, safe_date_key

__all__ = [
    "ALLOWED_EXTENSIONS",
    "SNAPSHOT_CONTRACT",
    "build_snapshot_record",
    "historical_validity_for",
    "raw_storage_path",
    "store_raw_bytes",
]

SNAPSHOT_CONTRACT = "web_snapshot_manifest@0.1.0"
SCHEMA_VERSION = "0.1.0"

ALLOWED_EXTENSIONS: tuple[str, ...] = ("html", "pdf", "json", "txt")

_COMPANY_ID_RE = re.compile(r"^CIK\d{10}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def raw_storage_path(
    *,
    raw_root: str | Path,
    company_id: str,
    content_family: str,
    date_key: str,
    content_sha256: str,
    extension: str,
) -> Path:
    """Build the content-addressed raw path with every segment validated."""
    if not _COMPANY_ID_RE.fullmatch(company_id):
        raise CollectionError(
            f"company_id must match ^CIK\\d{{10}}$: {company_id!r}",
            reason_code="date_key_invalid",
        )
    if content_family not in CONTENT_FAMILIES:
        raise CollectionError(
            f"unknown content_family: {content_family!r}",
            reason_code="request_plan_invalid",
        )
    if not _SHA256_RE.fullmatch(content_sha256):
        raise CollectionError(
            f"content_sha256 must be 64 lowercase hex chars: {content_sha256!r}",
            reason_code="content_hash_mismatch",
        )
    if extension not in ALLOWED_EXTENSIONS:
        raise CollectionError(
            f"extension outside the allowlist: {extension!r}",
            reason_code="date_key_invalid",
        )
    key = safe_date_key(date_key)
    return (
        Path(raw_root)
        / "web"
        / company_id
        / content_family
        / key
        / f"{content_sha256}.{extension}"
    )


def store_raw_bytes(
    *,
    raw_root: str | Path,
    company_id: str,
    content_family: str,
    date_key: str,
    content_sha256: str,
    extension: str,
    data: bytes,
) -> Path:
    """Write raw bytes exactly once. Never overwrites, never recollects."""
    destination = raw_storage_path(
        raw_root=raw_root,
        company_id=company_id,
        content_family=content_family,
        date_key=date_key,
        content_sha256=content_sha256,
        extension=extension,
    )
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CollectionError(
            f"failed to create raw directory for {destination}",
            reason_code="write_error",
        ) from exc
    try:
        observed = write_bytes_once(destination, data, what=f"raw {content_family}")
    except WriteOnceError as exc:
        raise translate_write_once_error(exc) from exc
    if observed != content_sha256:
        raise CollectionError(
            "persisted raw bytes do not match the declared content hash",
            reason_code="content_hash_mismatch",
        )
    return destination


def historical_validity_for(
    *,
    access_channel: str,
    temporal_route: str,
    publication_date: str | None,
    snapshot_timestamp: str | None,
    observation_cutoff_date: str,
) -> str:
    """Historical validity flag required by SPEC-005 for every snapshot.

    publication_date governs the dated-document route; snapshot_timestamp
    governs the archive route. retrieval_timestamp is never an input.
    """
    if temporal_route == "dated_document":
        if not publication_date:
            return "uncertain"
        return "valid" if publication_date <= observation_cutoff_date else "invalid"
    if access_channel != "archive":
        raise CollectionError(
            "the archive route requires access_channel=archive",
            reason_code="temporal_route_inconsistent",
        )
    if not snapshot_timestamp:
        return "uncertain"
    return "valid" if snapshot_timestamp[:10] <= observation_cutoff_date else "invalid"


def build_snapshot_record(
    *,
    company_id: str,
    candidate_id: str,
    content_family: str,
    access_channel: str,
    source_url: str,
    archive_url: str | None,
    archive_host: str | None,
    requested_url: str,
    final_url: str,
    redirect_hops: list[dict[str, Any]],
    http_status: int,
    retry_count: int,
    byte_count: int,
    content_sha256: str,
    retrieval_timestamp: str,
    publication_date: str | None,
    snapshot_timestamp: str | None,
    historical_validity: str,
    raw_path: str,
) -> dict[str, Any]:
    return {
        "contract": SNAPSHOT_CONTRACT,
        "schema_version": SCHEMA_VERSION,
        "company_id": company_id,
        "candidate_id": candidate_id,
        "content_family": content_family,
        "access_channel": access_channel,
        "source_url": source_url,
        "archive_url": archive_url,
        "archive_host": archive_host,
        "requested_url": requested_url,
        "final_url": final_url,
        "redirect_hops": list(redirect_hops),
        "http_status": http_status,
        "retry_count": retry_count,
        "byte_count": byte_count,
        "content_sha256": content_sha256,
        "retrieval_timestamp": retrieval_timestamp,
        "publication_date": publication_date,
        "snapshot_timestamp": snapshot_timestamp,
        "historical_validity": historical_validity,
        "raw_path": raw_path,
        "recollected": False,
    }
