"""Offline fixtures for the collection suites.

Every fixture lives under ``tmp_path`` or in memory. No test opens a socket,
reads ``data/``, reads a clock, or reads Git.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from dynamic_ai_products.collection.transport import TransportResponse

COMPANY_ID = "CIK0001404655"
CUTOFF = "2025-02-12"
CODE_COMMIT = "e64bb00527a7db1b99c0a7d2cccaf776856e0339"
RUN_CREATED_AT = "2026-07-28T12:00:00+00:00"

APEX = "hubspot.com"
ARCHIVE_HOST = "web.archive.org"

IR_URL = "https://ir.hubspot.com/financials/quarterly-results"
PRODUCT_URL = "https://www.hubspot.com/products/marketing"
DEVELOPER_URL = "https://developers.hubspot.com/docs/api/overview"
NEWSROOM_URL = "https://www.hubspot.com/company-news/launch"

PRODUCT_ARCHIVE = f"https://{ARCHIVE_HOST}/web/20250101000000/{PRODUCT_URL}"
DEVELOPER_ARCHIVE = f"https://{ARCHIVE_HOST}/web/20250110000000/{DEVELOPER_URL}"


def plan_payload(entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A canonical, valid request plan. Entries are already in canonical order."""
    if entries is None:
        entries = [
            {
                "content_family": "developer_docs",
                "access_channel": "archive",
                "source_url": DEVELOPER_URL,
                "archive_url": DEVELOPER_ARCHIVE,
                "purpose": "API surface for FY2024 capability evidence",
                "expected_temporal_route": "archive",
                "evidence_target": "snapshot_timestamp on or before 2025-02-12",
            },
            {
                "content_family": "official_ir",
                "access_channel": "live",
                "source_url": IR_URL,
                "archive_url": None,
                "purpose": "dated FY2024 earnings materials",
                "expected_temporal_route": "dated_document",
                "evidence_target": "publication_date on or before 2025-02-12",
            },
            {
                "content_family": "product_pages",
                "access_channel": "archive",
                "source_url": PRODUCT_URL,
                "archive_url": PRODUCT_ARCHIVE,
                "purpose": "customer-facing packaging as of FY2024",
                "expected_temporal_route": "archive",
                "evidence_target": "snapshot_timestamp on or before 2025-02-12",
            },
        ]
    return {
        "contract": "web_collection_request_plan@0.1.0",
        "company_id": COMPANY_ID,
        "observation_cutoff_date": CUTOFF,
        "entries": entries,
    }


def write_plan(tmp_path: Path, payload: dict[str, Any] | None = None) -> tuple[Path, str]:
    """Write a plan file and return its path plus SHA-256."""
    body = json.dumps(payload if payload is not None else plan_payload(), indent=2)
    target = tmp_path / "request_plan.json"
    target.write_text(body, encoding="utf-8")
    return target, sha256(target.read_bytes()).hexdigest()


class FakeTransport:
    """Injected transport. Records calls; never opens a socket."""

    def __init__(self, responses: dict[str, TransportResponse] | None = None) -> None:
        self.responses = dict(responses or {})
        self.calls: list[str] = []

    def __call__(self, url: str) -> TransportResponse:
        self.calls.append(url)
        if url in self.responses:
            return self.responses[url]
        return TransportResponse(status_code=200, final_url=url, content=b"<html/>")


def redirect(to: str, status: int = 301) -> TransportResponse:
    return TransportResponse(status_code=status, final_url="", content=b"", location=to)


def ok(url: str, body: bytes = b"<html>ok</html>") -> TransportResponse:
    """A terminal response whose final_url names the requested URL."""
    return TransportResponse(status_code=200, final_url=url, content=body)
