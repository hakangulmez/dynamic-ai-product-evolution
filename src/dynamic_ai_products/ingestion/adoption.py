"""Stage 01 SEC discovery and Stage 03 snapshot adoption (SPEC-002, SPEC-003,
SPEC-005; ADR-031).

Adoption-only: the raw bytes already exist and are never recollected. This
module opens raw files read-only, re-verifies every byte against the immutable
collection receipt, and never writes into ``data/raw``. It contains no URL, no
transport, no clock, and no model.

Temporal rule: eligibility compares ``publication_date`` against the
observation cutoff. ``retrieval_timestamp`` is provenance only and is never a
temporal-eligibility input — for this packet it postdates the cutoff by
seventeen months and would invalidate the filing if wrongly compared.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from .errors import IngestionError

__all__ = [
    "SEC_FAMILY",
    "adopt_sec_snapshots",
    "build_sec_candidates",
    "temporal_validity_for",
    "verify_raw_bytes",
]

SEC_FAMILY = "sec_edgar"
SOURCE_TYPE_10K = "sec_10k"
SCHEMA_VERSION = "0.1.0"


def temporal_validity_for(publication_date: str, observation_cutoff_date: str) -> str:
    """Temporal policy: a source supports an observation when pub <= cutoff."""
    if not publication_date or not observation_cutoff_date:
        return "uncertain"
    return "valid" if publication_date <= observation_cutoff_date else "invalid"


def verify_raw_bytes(raw_directory: str | Path, receipt: dict[str, Any]) -> dict[str, bytes]:
    """Read every receipted raw file read-only and re-verify its SHA-256.

    Returns the verified bytes keyed by receipt key. Any mismatch is a
    fail-closed stop; nothing is repaired and nothing is written.
    """
    directory = Path(raw_directory)
    retrievals = receipt.get("retrievals")
    if not isinstance(retrievals, list) or not retrievals:
        raise IngestionError(
            "collection receipt carries no retrievals",
            reason_code="receipt_unavailable",
        )

    filenames = {
        "submissions": "submissions.json",
        "filing_index": "filing-index.json",
        "primary_document": None,  # resolved from the receipt's final URL
    }

    verified: dict[str, bytes] = {}
    for entry in retrievals:
        key = entry.get("key")
        expected = entry.get("sha256")
        if not isinstance(key, str) or not isinstance(expected, str):
            raise IngestionError(
                "collection receipt entry is malformed",
                reason_code="receipt_unavailable",
            )
        name = filenames.get(key)
        if name is None:
            final_url = entry.get("final_url", "")
            name = final_url.rsplit("/", 1)[-1]
        path = directory / name
        if not path.is_file():
            raise IngestionError(
                f"receipted raw file is missing: {name}",
                reason_code="receipt_unavailable",
            )
        data = path.read_bytes()
        observed = sha256(data).hexdigest()
        if observed != expected:
            raise IngestionError(
                f"raw bytes do not match the receipt for {name}",
                reason_code="raw_bytes_hash_mismatch",
                detail=f"expected {expected}, observed {observed}",
            )
        verified[key] = data
    return verified


def build_sec_candidates(
    *,
    company_id: str,
    receipt: dict[str, Any],
    observation_cutoff_date: str,
) -> list[dict[str, Any]]:
    """Stage 01 candidate frame, derived by adoption from the receipt."""
    identity = receipt.get("identity")
    if not isinstance(identity, dict):
        raise IngestionError(
            "collection receipt carries no identity block",
            reason_code="receipt_unavailable",
        )
    filing_date = identity.get("filing_date")
    validity = temporal_validity_for(filing_date, observation_cutoff_date)
    if validity != "valid":
        raise IngestionError(
            f"filing date {filing_date} is not valid for cutoff "
            f"{observation_cutoff_date}",
            reason_code="temporally_invalid",
        )

    rows: list[dict[str, Any]] = []
    for entry in receipt.get("retrievals", []):
        final_url = entry.get("final_url", "")
        filename = final_url.rsplit("/", 1)[-1]
        candidate_id = sha256(
            f"{company_id}\x00{identity.get('accession')}\x00{filename}".encode("utf-8")
        ).hexdigest()[:32]
        rows.append(
            {
                "candidate_id": candidate_id,
                "company_id": company_id,
                "source_family": SEC_FAMILY,
                "source_type": SOURCE_TYPE_10K,
                "form": identity.get("form"),
                "accession": identity.get("accession"),
                "document_filename": filename,
                "publication_date": filing_date,
                "period_of_report": identity.get("period_of_report"),
                "observation_cutoff_date": observation_cutoff_date,
                "requested_url": entry.get("requested_url"),
                "final_url": final_url,
                "content_sha256": entry.get("sha256"),
                "byte_count": entry.get("byte_count"),
                "retrieval_timestamp": entry.get("retrieval_timestamp"),
                "temporal_validity": validity,
                "official_status": "official",
                "coverage_state": "available_and_retrieved",
                "schema_version": SCHEMA_VERSION,
            }
        )
    return rows


def adopt_sec_snapshots(
    *,
    company_id: str,
    receipt: dict[str, Any],
    receipt_sha256: str,
    raw_directory: str | Path,
) -> list[dict[str, Any]]:
    """Stage 03 adoption records for already-persisted raw bytes.

    No snapshot bytes are created: the records attest that the existing
    immutable raw files were re-verified against the receipt.
    """
    identity = receipt.get("identity", {})
    records: list[dict[str, Any]] = []
    for entry in receipt.get("retrievals", []):
        final_url = entry.get("final_url", "")
        records.append(
            {
                "contract": "snapshot_manifest@0.1.0",
                "schema_version": SCHEMA_VERSION,
                "company_id": company_id,
                "accession": identity.get("accession"),
                "retrieval_key": entry.get("key"),
                "document_filename": final_url.rsplit("/", 1)[-1],
                "requested_url": entry.get("requested_url"),
                "final_url": final_url,
                "http_status": entry.get("http_status"),
                "retry_count": entry.get("retry_count"),
                "byte_count": entry.get("byte_count"),
                "content_sha256": entry.get("sha256"),
                "retrieval_timestamp": entry.get("retrieval_timestamp"),
                "raw_directory": str(raw_directory),
                "collection_receipt_sha256": receipt_sha256,
                "adoption_mode": "existing_raw_bytes_reverified",
                "recollected": False,
            }
        )
    return records


def build_source_document(
    *,
    company_id: str,
    receipt: dict[str, Any],
    observation_cutoff_date: str,
    primary_document: str,
) -> dict[str, Any]:
    """The Stage 04 ``source_document`` record for the primary filing document."""
    identity = receipt.get("identity", {})
    entry = None
    for candidate in receipt.get("retrievals", []):
        if candidate.get("final_url", "").endswith(primary_document):
            entry = candidate
            break
    if entry is None:
        raise IngestionError(
            f"primary document {primary_document} is absent from the receipt",
            reason_code="receipt_unavailable",
        )

    filing_date = identity.get("filing_date")
    content_hash = entry.get("sha256")
    source_id = (
        f"{company_id}/{SOURCE_TYPE_10K}/{filing_date}/{str(content_hash)[:16]}"
    )
    return {
        "source_id": source_id,
        "company_id": company_id,
        "source_type": SOURCE_TYPE_10K,
        "title": None,
        "url": entry.get("final_url"),
        "archive_url": None,
        "publication_date": filing_date,
        "retrieval_timestamp": entry.get("retrieval_timestamp"),
        "snapshot_timestamp": None,
        "content_hash": content_hash,
        "mime_type": "text/html",
        "official_status": "official",
        "temporal_validity": temporal_validity_for(
            filing_date, observation_cutoff_date
        ),
        "access_status": "retrieved",
        "schema_version": SCHEMA_VERSION,
    }
