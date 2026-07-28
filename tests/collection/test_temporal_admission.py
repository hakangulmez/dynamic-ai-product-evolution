"""Temporal admission: publication_date vs snapshot_timestamp; never retrieval."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from dynamic_ai_products.collection.errors import CollectionError  # noqa: E402
from dynamic_ai_products.collection.request_plan import validate_request_plan  # noqa: E402
from dynamic_ai_products.collection.web_snapshot import (  # noqa: E402
    historical_validity_for,
)
from collection_test_helpers import CUTOFF, plan_payload  # noqa: E402

# Any live retrieval now happens ~17.5 months after the FY2024 cutoff.
RETRIEVAL_NOW = "2026-07-28T13:38:49+00:00"


def test_retrieval_timestamp_postdates_the_cutoff_by_design() -> None:
    assert RETRIEVAL_NOW[:10] > CUTOFF


def test_retrieval_timestamp_is_never_a_temporal_input() -> None:
    """A document dated before the cutoff stays valid however late we fetch it."""
    assert (
        historical_validity_for(
            access_channel="live",
            temporal_route="dated_document",
            publication_date="2024-11-06",
            snapshot_timestamp=None,
            observation_cutoff_date=CUTOFF,
        )
        == "valid"
    )


def test_live_page_without_a_publication_date_is_uncertain_not_valid() -> None:
    assert (
        historical_validity_for(
            access_channel="live",
            temporal_route="dated_document",
            publication_date=None,
            snapshot_timestamp=None,
            observation_cutoff_date=CUTOFF,
        )
        == "uncertain"
    )


@pytest.mark.parametrize(
    "snapshot,expected",
    [
        ("2025-02-12T23:59:59+00:00", "valid"),
        ("2025-02-11T00:00:00+00:00", "valid"),
        ("2025-02-13T00:00:00+00:00", "invalid"),
        (RETRIEVAL_NOW, "invalid"),
    ],
)
def test_snapshot_after_cutoff_is_rejected(snapshot: str, expected: str) -> None:
    assert (
        historical_validity_for(
            access_channel="archive",
            temporal_route="archive",
            publication_date=None,
            snapshot_timestamp=snapshot,
            observation_cutoff_date=CUTOFF,
        )
        == expected
    )


def test_archived_dated_document_is_admitted_on_publication_date() -> None:
    """An archived capture of a dated document uses the dated_document route."""
    payload = plan_payload()
    payload["entries"][0]["expected_temporal_route"] = "dated_document"
    plan = validate_request_plan(payload)
    entry = plan["entries"][0]
    assert entry["access_channel"] == "archive"
    assert (
        historical_validity_for(
            access_channel=entry["access_channel"],
            temporal_route=entry["expected_temporal_route"],
            publication_date="2024-12-01",
            snapshot_timestamp=RETRIEVAL_NOW,
            observation_cutoff_date=CUTOFF,
        )
        == "valid"
    )


def test_live_entry_cannot_declare_the_archive_route() -> None:
    payload = plan_payload()
    payload["entries"][1]["expected_temporal_route"] = "archive"
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "temporal_route_inconsistent"


def test_no_module_compares_retrieval_timestamp_to_a_cutoff() -> None:
    directory = Path("src/dynamic_ai_products/collection")
    for path in sorted(directory.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                rendered = ast.dump(node)
                if "retrieval_timestamp" in rendered and "cutoff" in rendered:
                    pytest.fail(
                        f"{path.name}: retrieval_timestamp must never be a temporal input"
                    )
