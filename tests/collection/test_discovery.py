"""Stage 02 candidate enumeration from the request plan only."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

from dynamic_ai_products.collection.errors import CollectionError  # noqa: E402
from dynamic_ai_products.collection.discovery import (  # noqa: E402
    build_official_web_candidates,
    candidate_id_for,
)
from dynamic_ai_products.collection.request_plan import validate_request_plan  # noqa: E402
from collection_test_helpers import (  # noqa: E402
    ARCHIVE_HOST,
    COMPANY_ID,
    CUTOFF,
    PRODUCT_ARCHIVE,
    plan_payload,
)

PLAN = validate_request_plan(plan_payload())


def _rows():
    return build_official_web_candidates(
        company_id=COMPANY_ID, observation_cutoff_date=CUTOFF, plan=PLAN
    )


def test_one_candidate_per_plan_entry_in_plan_order() -> None:
    rows = _rows()
    assert len(rows) == len(PLAN["entries"])
    assert [r["content_family"] for r in rows] == [
        e["content_family"] for e in PLAN["entries"]
    ]


def test_rows_conform_to_schema() -> None:
    schema = json.loads(
        Path("schemas/official_web_candidate.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for row in _rows():
        validator.validate(row)


def test_discovery_source_is_always_the_request_plan() -> None:
    assert all(r["discovery_source"] == "request_plan" for r in _rows())


def test_source_url_is_canonicalized_and_apex_recorded() -> None:
    for row in _rows():
        assert row["source_url"].startswith("https://")
        assert "#" not in row["source_url"]
        assert row["official_apex"] == "hubspot.com"
        assert row["source_host"].endswith("hubspot.com")


def test_archive_rows_carry_archive_host_and_live_rows_do_not() -> None:
    rows = {r["access_channel"]: r for r in _rows()}
    assert rows["live"]["archive_url"] is None
    assert rows["live"]["archive_host"] is None
    archive_rows = [r for r in _rows() if r["access_channel"] == "archive"]
    assert archive_rows
    for row in archive_rows:
        assert row["archive_host"] == ARCHIVE_HOST
        assert row["archive_url"]


def test_candidate_id_is_deterministic_and_distinct() -> None:
    rows = _rows()
    ids = [r["candidate_id"] for r in rows]
    assert len(set(ids)) == len(ids)
    assert all(len(i) == 32 for i in ids)
    repeat = build_official_web_candidates(
        company_id=COMPANY_ID, observation_cutoff_date=CUTOFF, plan=PLAN
    )
    assert [r["candidate_id"] for r in repeat] == ids


def test_candidate_id_changes_with_the_requested_url() -> None:
    a = candidate_id_for(COMPANY_ID, "product_pages", "archive", PRODUCT_ARCHIVE)
    b = candidate_id_for(COMPANY_ID, "product_pages", "archive", PRODUCT_ARCHIVE + "x")
    assert a != b


def test_no_candidate_is_produced_outside_the_plan() -> None:
    urls = {r["archive_url"] or r["source_url"] for r in _rows()}
    planned = {
        (e["archive_url"] if e["access_channel"] == "archive" else e["source_url"])
        for e in PLAN["entries"]
    }
    assert urls == planned


# --- Plan context binding -----------------------------------------------------


def test_matching_context_positive_path_is_unchanged() -> None:
    rows = build_official_web_candidates(
        company_id=COMPANY_ID, observation_cutoff_date=CUTOFF, plan=PLAN
    )
    assert len(rows) == len(PLAN["entries"])
    assert {r["company_id"] for r in rows} == {COMPANY_ID}
    assert {r["observation_cutoff_date"] for r in rows} == {CUTOFF}


@pytest.mark.parametrize(
    "other_company",
    ["CIK0000320193", "CIK0001652044", "CIK9999999999"],
)
def test_mismatched_company_id_fails_closed(other_company: str) -> None:
    """A valid HubSpot plan may not emit candidates under another firm."""
    with pytest.raises(CollectionError) as excinfo:
        build_official_web_candidates(
            company_id=other_company, observation_cutoff_date=CUTOFF, plan=PLAN
        )
    assert excinfo.value.reason_code == "request_plan_context_mismatch"


@pytest.mark.parametrize("other_cutoff", ["2024-12-31", "2025-02-11", "2026-07-29"])
def test_mismatched_cutoff_fails_closed(other_cutoff: str) -> None:
    """A valid plan may not be replayed against a different observation year."""
    with pytest.raises(CollectionError) as excinfo:
        build_official_web_candidates(
            company_id=COMPANY_ID, observation_cutoff_date=other_cutoff, plan=PLAN
        )
    assert excinfo.value.reason_code == "request_plan_context_mismatch"


def test_discovery_revalidates_the_supplied_plan() -> None:
    """A tampered plan is rejected even when the context matches."""
    import copy

    tampered = copy.deepcopy(PLAN)
    tampered["entries"][1]["source_url"] = "https://ir.example.com/results"
    with pytest.raises(CollectionError) as excinfo:
        build_official_web_candidates(
            company_id=COMPANY_ID, observation_cutoff_date=CUTOFF, plan=tampered
        )
    assert excinfo.value.reason_code == "third_party_domain_excluded"


def test_discovery_rejects_a_plan_with_a_malformed_company_id() -> None:
    import copy

    tampered = copy.deepcopy(PLAN)
    tampered["company_id"] = "hubspot"
    with pytest.raises(CollectionError) as excinfo:
        build_official_web_candidates(
            company_id="hubspot", observation_cutoff_date=CUTOFF, plan=tampered
        )
    assert excinfo.value.reason_code == "request_plan_invalid"
