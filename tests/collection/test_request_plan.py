"""Request-plan validation: the collector's only URL authority."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

from dynamic_ai_products.collection.errors import CollectionError  # noqa: E402
from dynamic_ai_products.collection.request_plan import (  # noqa: E402
    ARCHIVE_HOST_ALLOWLIST,
    admitted_urls,
    entry_sort_key,
    load_request_plan,
    parse_wayback_capture,
    planned_hosts,
    robots_url_for,
    safe_date_key,
    validate_request_plan,
)
from collection_test_helpers import (  # noqa: E402
    ARCHIVE_HOST,
    COMPANY_ID,
    CUTOFF,
    DEVELOPER_ARCHIVE,
    IR_URL,
    PRODUCT_ARCHIVE,
    PRODUCT_URL,
    plan_payload,
    write_plan,
)


def test_valid_plan_round_trips(tmp_path: Path) -> None:
    path, digest = write_plan(tmp_path)
    plan, observed = load_request_plan(path)
    assert observed == digest
    assert len(plan["entries"]) == 3


def test_plan_conforms_to_schema() -> None:
    schema = json.loads(
        Path("schemas/web_collection_request_plan.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(plan_payload())


# --- Undeclared URL refusal ---------------------------------------------------


def test_admitted_urls_is_exactly_the_declared_set() -> None:
    plan = validate_request_plan(plan_payload())
    assert admitted_urls(plan) == frozenset(
        {DEVELOPER_ARCHIVE, IR_URL, PRODUCT_ARCHIVE}
    )
    # The archived entries' ORIGINAL urls are never independently requestable.
    assert PRODUCT_URL not in admitted_urls(plan)


def test_unrelated_url_is_not_admitted() -> None:
    plan = validate_request_plan(plan_payload())
    assert "https://www.hubspot.com/pricing" not in admitted_urls(plan)


# --- Host and channel consistency --------------------------------------------


def test_archive_entry_requires_archive_url() -> None:
    payload = plan_payload()
    payload["entries"][0]["archive_url"] = None
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "request_plan_invalid"


def test_live_entry_forbids_archive_url() -> None:
    payload = plan_payload()
    payload["entries"][1]["archive_url"] = PRODUCT_ARCHIVE
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "request_plan_invalid"


# --- Closed Wayback archive grammar (structural, never substring) ------------


def test_only_web_archive_org_is_allowlisted() -> None:
    assert ARCHIVE_HOST_ALLOWLIST == frozenset({"web.archive.org"})


def test_wayback_capture_parses_to_timestamp_and_embedded_original() -> None:
    stamp, original = parse_wayback_capture(PRODUCT_ARCHIVE)
    assert stamp == "20250101000000"
    assert original == PRODUCT_URL


def test_wayback_modifier_suffix_is_accepted() -> None:
    url = f"https://web.archive.org/web/20250101000000id_/{PRODUCT_URL}"
    stamp, original = parse_wayback_capture(url)
    assert stamp == "20250101000000"
    assert original == PRODUCT_URL


@pytest.mark.parametrize(
    "archive_url",
    [
        f"https://other.archive.example/web/20250101000000/{PRODUCT_URL}",
        f"https://web.archive.org.evil.example/web/20250101000000/{PRODUCT_URL}",
        f"https://archive.today/web/20250101000000/{PRODUCT_URL}",
    ],
)
def test_arbitrary_archive_host_is_refused(archive_url: str) -> None:
    with pytest.raises(CollectionError) as excinfo:
        parse_wayback_capture(archive_url)
    assert excinfo.value.reason_code == "archive_host_not_allowed"


@pytest.mark.parametrize(
    "archive_url",
    [
        "https://web.archive.org/web/2025/elsewhere",  # embedded is not a URL
        "https://web.archive.org/web/20250101000000/",  # no embedded URL
        "https://web.archive.org/20250101000000/https://www.hubspot.com/x",  # no /web/
        "https://web.archive.org/web/notatimestamp/https://www.hubspot.com/x",
        "https://web.archive.org/",  # no capture path at all
        "https://web.archive.org/web/20250101000000/ftp://www.hubspot.com/x",
    ],
)
def test_malformed_capture_is_refused(archive_url: str) -> None:
    with pytest.raises(CollectionError) as excinfo:
        parse_wayback_capture(archive_url)
    assert excinfo.value.reason_code == "archive_capture_malformed"


def test_query_only_wrapper_without_a_capture_path_is_malformed() -> None:
    with pytest.raises(CollectionError) as excinfo:
        parse_wayback_capture(f"https://web.archive.org/?url={PRODUCT_URL}")
    assert excinfo.value.reason_code == "archive_capture_malformed"


def test_capture_query_is_reattached_to_the_embedded_original() -> None:
    """A genuine capture of a query URL keeps the query on the original."""
    _stamp, original = parse_wayback_capture(
        f"https://web.archive.org/web/20250101000000/{PRODUCT_URL}?a=b"
    )
    assert original == f"{PRODUCT_URL}?a=b"


def test_spoofed_query_is_refused_by_canonical_equality() -> None:
    payload = plan_payload()
    payload["entries"][2]["archive_url"] = (
        f"https://web.archive.org/web/20250101000000/{PRODUCT_URL}?spoof=1"
    )
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "archive_original_host_mismatch"


def test_capture_embedding_a_different_original_is_refused() -> None:
    payload = plan_payload()
    payload["entries"][2]["archive_url"] = (
        "https://web.archive.org/web/20250101000000/https://www.hubspot.com/pricing"
    )
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "archive_original_host_mismatch"


def test_capture_embedding_a_third_party_original_is_refused() -> None:
    payload = plan_payload()
    payload["entries"][2]["archive_url"] = (
        "https://web.archive.org/web/20250101000000/https://evil.example/marketing"
    )
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "archive_original_host_mismatch"


def test_substring_containment_alone_no_longer_admits_a_capture() -> None:
    """The old rule accepted any archive URL merely containing the host text."""
    payload = plan_payload()
    payload["entries"][2]["archive_url"] = (
        "https://web.archive.org/web/20250101000000/"
        "https://evil.example/marketing?ref=www.hubspot.com"
    )
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "archive_original_host_mismatch"


def test_embedded_original_is_compared_canonically() -> None:
    """Canonical equality, so a tracking parameter does not break a match."""
    payload = plan_payload()
    payload["entries"][2]["archive_url"] = (
        f"https://web.archive.org/web/20250101000000/{PRODUCT_URL}?utm_source=x"
    )
    plan = validate_request_plan(payload)
    assert plan["entries"][2]["archive_url"].endswith("?utm_source=x")


def test_archive_host_may_not_be_the_official_origin() -> None:
    payload = plan_payload()
    payload["entries"][0]["archive_url"] = (
        "https://www.hubspot.com/mirror/developers.hubspot.com/docs"
    )
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "archive_host_as_origin"


def test_source_url_outside_apex_is_refused() -> None:
    payload = plan_payload()
    payload["entries"][1]["source_url"] = "https://ir.example.com/results"
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "third_party_domain_excluded"


# --- Enum and route validity --------------------------------------------------


def test_unknown_content_family_is_refused() -> None:
    payload = plan_payload()
    payload["entries"][0]["content_family"] = "press_coverage"
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "request_plan_invalid"


def test_unknown_access_channel_is_refused() -> None:
    payload = plan_payload()
    payload["entries"][0]["access_channel"] = "cached"
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "request_plan_invalid"


def test_live_entry_must_use_the_dated_document_route() -> None:
    payload = plan_payload()
    payload["entries"][1]["expected_temporal_route"] = "archive"
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "temporal_route_inconsistent"


def test_archive_entry_may_use_either_route() -> None:
    payload = plan_payload()
    payload["entries"][0]["expected_temporal_route"] = "dated_document"
    plan = validate_request_plan(payload)
    assert plan["entries"][0]["expected_temporal_route"] == "dated_document"


@pytest.mark.parametrize("field", ["purpose", "evidence_target"])
def test_blank_declared_field_is_refused(field: str) -> None:
    payload = plan_payload()
    payload["entries"][0][field] = "   "
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "request_plan_invalid"


# --- Ordering, duplicates, strictness ----------------------------------------


def test_out_of_order_entries_are_refused() -> None:
    payload = plan_payload()
    payload["entries"] = list(reversed(payload["entries"]))
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "plan_ordering_invalid"


def test_canonical_order_is_the_sorted_key_order() -> None:
    plan = validate_request_plan(plan_payload())
    keys = [entry_sort_key(e) for e in plan["entries"]]
    assert keys == sorted(keys)


def test_duplicate_entry_is_refused() -> None:
    payload = plan_payload()
    payload["entries"].append(dict(payload["entries"][2]))
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "plan_duplicate_entry"


def test_extra_field_is_refused() -> None:
    payload = plan_payload()
    payload["entries"][0]["smuggled"] = "value"
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "request_plan_invalid"


def test_extra_top_level_field_is_refused() -> None:
    payload = plan_payload()
    payload["extra"] = 1
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "request_plan_invalid"


def test_empty_plan_is_refused() -> None:
    payload = plan_payload()
    payload["entries"] = []
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "request_plan_invalid"


def test_wrong_contract_is_refused() -> None:
    payload = plan_payload()
    payload["contract"] = "web_collection_request_plan@0.2.0"
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "request_plan_invalid"


# --- Robots URL ---------------------------------------------------------------


def test_planned_hosts_cover_origin_and_archive_roles() -> None:
    plan = validate_request_plan(plan_payload())
    hosts = planned_hosts(plan)
    assert "ir.hubspot.com" in hosts
    assert ARCHIVE_HOST in hosts


def test_robots_url_is_deterministic() -> None:
    assert robots_url_for("WWW.HubSpot.com") == "https://www.hubspot.com/robots.txt"


# --- Safe date key ------------------------------------------------------------


def test_valid_date_key_accepted() -> None:
    assert safe_date_key("2025-02-12") == "2025-02-12"


@pytest.mark.parametrize(
    "value",
    [
        "2026-07-28T13:38:49+00:00",
        "2025-2-12",
        "../2025-02-12",
        "2025/02/12",
        "2025-02-30",
        "2025-13-01",
        "",
        "latest",
    ],
)
def test_unsafe_date_key_is_refused(value: str) -> None:
    with pytest.raises(CollectionError) as excinfo:
        safe_date_key(value)
    assert excinfo.value.reason_code == "date_key_invalid"


# --- Top-level identity and date are enforced by the loader --------------------


@pytest.mark.parametrize(
    "company_id",
    [
        "CIK1404655",          # too short
        "CIK00014046555",      # too long
        "cik0001404655",       # lowercase prefix
        "0001404655",          # no prefix
        "CIK000140465X",       # non-digit
        " CIK0001404655",      # leading space
        "CIK0001404655 ",      # trailing space
        "",
    ],
)
def test_malformed_company_id_is_refused(company_id: str) -> None:
    payload = plan_payload()
    payload["company_id"] = company_id
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "request_plan_invalid"


@pytest.mark.parametrize("company_id", [None, 1404655, ["CIK0001404655"], {}])
def test_non_string_company_id_is_refused(company_id) -> None:
    payload = plan_payload()
    payload["company_id"] = company_id
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "request_plan_invalid"


@pytest.mark.parametrize(
    "cutoff",
    [
        "2025-02-30",                 # not a real calendar date
        "2025-13-01",                 # impossible month
        "2025-2-12",                  # unpadded
        "2026-07-28T13:38:49+00:00",  # timestamp, not a date key
        "../2025-02-12",              # traversal
        "2025/02/12",                 # separators
        "latest",
        "",
    ],
)
def test_malformed_cutoff_is_refused(cutoff: str) -> None:
    payload = plan_payload()
    payload["observation_cutoff_date"] = cutoff
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "request_plan_invalid"


@pytest.mark.parametrize("cutoff", [None, 20250212, ["2025-02-12"]])
def test_non_string_cutoff_is_refused(cutoff) -> None:
    payload = plan_payload()
    payload["observation_cutoff_date"] = cutoff
    with pytest.raises(CollectionError) as excinfo:
        validate_request_plan(payload)
    assert excinfo.value.reason_code == "request_plan_invalid"


def test_valid_context_is_returned_unchanged() -> None:
    plan = validate_request_plan(plan_payload())
    assert plan["company_id"] == COMPANY_ID
    assert plan["observation_cutoff_date"] == CUTOFF


def test_validation_is_idempotent() -> None:
    once = validate_request_plan(plan_payload())
    assert validate_request_plan(once) == once
