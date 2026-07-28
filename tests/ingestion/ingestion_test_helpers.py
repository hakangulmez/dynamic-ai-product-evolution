"""Synthetic offline fixtures for the ingestion suites.

Every fixture lives under ``tmp_path``. No test reads ``data/``, the network,
a clock, or Git.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

COMPANY_ID = "CIK0009999999"
ACCESSION = "0000000000-25-000001"
CUTOFF = "2025-02-12"
FILING_DATE = "2025-02-12"
PERIOD = "2024-12-31"
PRIMARY_DOCUMENT = "test-20241231.htm"
CODE_COMMIT = "0" * 40
RUN_CREATED_AT = "2026-07-28T00:00:00+00:00"
PACKET_SHA256 = "b" * 64

START_ANCHOR = b'id="item_i_business"'
END_ANCHOR = b'id="item_1a_risk_factors"'

PRIMARY_HTML = (
    b"<html><body>"
    b"<div>front matter that is outside the span</div>"
    b'<div id="item_i_business">Item&nbsp;1. Business</div>'
    b"<p>We provide a customer platform that helps businesses connect "
    b"and grow better.</p>"
    b"<p>Our platform includes marketing, sales, and service software.</p>"
    b'<div id="item_1a_risk_factors">Item 1A. Risk Factors</div>'
    b"<p>tail content outside the span</p>"
    b"</body></html>"
)

SUBMISSIONS = b'{"cik":"9999999","name":"TEST INC"}'
FILING_INDEX = b'{"directory":{"item":[{"name":"test-20241231.htm"}]}}'


def span_offsets(raw: bytes = PRIMARY_HTML) -> tuple[int, int]:
    """Anchor-bounded span: start anchor through the start of the end anchor."""
    return raw.index(START_ANCHOR), raw.index(END_ANCHOR)


def build_raw_fixture(tmp_path: Path) -> tuple[Path, dict[str, Any], str]:
    """Create a synthetic raw directory plus a matching collection receipt."""
    raw_directory = tmp_path / "raw" / "sec" / COMPANY_ID / ACCESSION
    raw_directory.mkdir(parents=True)

    files = {
        "submissions.json": SUBMISSIONS,
        "filing-index.json": FILING_INDEX,
        PRIMARY_DOCUMENT: PRIMARY_HTML,
    }
    for name, payload in files.items():
        (raw_directory / name).write_bytes(payload)

    base = f"https://example.invalid/{ACCESSION}"
    receipt = {
        "receipt_version": "collection_receipt_v1",
        "completion_status": "complete",
        "identity": {
            "cik": "0009999999",
            "accession": ACCESSION,
            "form": "10-K",
            "filing_date": FILING_DATE,
            "period_of_report": PERIOD,
        },
        "retrievals": [
            {
                "key": "submissions",
                "requested_url": f"{base}/submissions.json",
                "final_url": f"{base}/submissions.json",
                "http_status": 200,
                "retry_count": 0,
                "byte_count": len(SUBMISSIONS),
                "sha256": sha256(SUBMISSIONS).hexdigest(),
                # Deliberately AFTER the cutoff: retrieval time is provenance
                # only and must never drive temporal eligibility.
                "retrieval_timestamp": "2026-07-27T16:44:23+00:00",
            },
            {
                "key": "filing_index",
                "requested_url": f"{base}/filing-index.json",
                "final_url": f"{base}/filing-index.json",
                "http_status": 200,
                "retry_count": 0,
                "byte_count": len(FILING_INDEX),
                "sha256": sha256(FILING_INDEX).hexdigest(),
                "retrieval_timestamp": "2026-07-27T16:44:24+00:00",
            },
            {
                "key": "primary_document",
                "requested_url": f"{base}/{PRIMARY_DOCUMENT}",
                "final_url": f"{base}/{PRIMARY_DOCUMENT}",
                "http_status": 200,
                "retry_count": 0,
                "byte_count": len(PRIMARY_HTML),
                "sha256": sha256(PRIMARY_HTML).hexdigest(),
                "retrieval_timestamp": "2026-07-27T16:44:26+00:00",
            },
        ],
    }
    receipt_sha256 = sha256(repr(sorted(receipt.items())).encode("utf-8")).hexdigest()
    return raw_directory, receipt, receipt_sha256


def preflight_kwargs(tmp_path: Path) -> dict[str, Any]:
    raw_directory, receipt, receipt_sha256 = build_raw_fixture(tmp_path)
    start, end = span_offsets()
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    return {
        "runs_root": runs_root,
        "raw_directory": raw_directory,
        "receipt": receipt,
        "receipt_sha256": receipt_sha256,
        "packet_sha256": PACKET_SHA256,
        "company_id": COMPANY_ID,
        "observation_cutoff_date": CUTOFF,
        "primary_document": PRIMARY_DOCUMENT,
        "span_start_offset": start,
        "span_end_offset": end,
        "code_commit": CODE_COMMIT,
        "run_created_at": RUN_CREATED_AT,
    }
