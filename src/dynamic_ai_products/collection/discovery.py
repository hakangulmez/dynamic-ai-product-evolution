"""Stage 02 official-web candidate enumeration (SPEC-004, ADR-032).

Candidates are enumerated from the approved request plan only. There is no
crawl, no search-engine expansion, no sitemap traversal, and no link following:
the plan is the sole source of candidate URLs.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from .canonical_url import CANONICALIZATION_VERSION, canonical_url
from .domains import OFFICIAL_APEX, host_of
from .errors import CollectionError
from .request_plan import CONTENT_FAMILIES, validate_request_plan

__all__ = ["CANDIDATE_CONTRACT", "build_official_web_candidates", "candidate_id_for"]

CANDIDATE_CONTRACT = "official_web_candidate@0.1.0"
SCHEMA_VERSION = "0.1.0"


def candidate_id_for(
    company_id: str, content_family: str, access_channel: str, request_url: str
) -> str:
    material = f"{company_id}\x00{content_family}\x00{access_channel}\x00{request_url}"
    return sha256(material.encode("utf-8")).hexdigest()[:32]


def build_official_web_candidates(
    *,
    company_id: str,
    observation_cutoff_date: str,
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """One candidate row per request-plan entry, in canonical plan order.

    The plan is revalidated here rather than trusted, and the supplied
    company/cutoff context must equal the plan's own. Without this a valid
    plan for one firm-year could be replayed to emit candidates under a
    different firm or a different observation cutoff.
    """
    validated = validate_request_plan(plan)
    if company_id != validated["company_id"]:
        raise CollectionError(
            "discovery company_id does not match the request plan",
            reason_code="request_plan_context_mismatch",
            detail=f"supplied {company_id!r} != plan {validated['company_id']!r}",
        )
    if observation_cutoff_date != validated["observation_cutoff_date"]:
        raise CollectionError(
            "discovery observation_cutoff_date does not match the request plan",
            reason_code="request_plan_context_mismatch",
            detail=(
                f"supplied {observation_cutoff_date!r} != "
                f"plan {validated['observation_cutoff_date']!r}"
            ),
        )

    rows: list[dict[str, Any]] = []
    for entry in validated["entries"]:
        family = entry["content_family"]
        if family not in CONTENT_FAMILIES:
            raise CollectionError(
                f"unknown content_family in plan: {family!r}",
                reason_code="request_plan_invalid",
            )
        channel = entry["access_channel"]
        source_url = canonical_url(entry["source_url"])
        archive_url = entry.get("archive_url")
        request_url = archive_url if channel == "archive" else source_url
        rows.append(
            {
                "contract": CANDIDATE_CONTRACT,
                "schema_version": SCHEMA_VERSION,
                "candidate_id": candidate_id_for(
                    company_id, family, channel, request_url
                ),
                "company_id": company_id,
                "content_family": family,
                "access_channel": channel,
                "source_url": source_url,
                "source_host": host_of(source_url),
                "archive_url": archive_url,
                "archive_host": host_of(archive_url) if archive_url else None,
                "official_apex": OFFICIAL_APEX,
                "expected_temporal_route": entry["expected_temporal_route"],
                "purpose": entry["purpose"],
                "evidence_target": entry["evidence_target"],
                "observation_cutoff_date": observation_cutoff_date,
                "canonicalization_version": CANONICALIZATION_VERSION,
                "discovery_source": "request_plan",
            }
        )
    return rows
