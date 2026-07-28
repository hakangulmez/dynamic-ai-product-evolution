"""Three-class request authority and response-derived redirect semantics."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from dynamic_ai_products.collection.errors import CollectionError  # noqa: E402
from dynamic_ai_products.collection.request_plan import validate_request_plan  # noqa: E402
from dynamic_ai_products.collection.transport import (  # noqa: E402
    CLIENT_CONTRACT,
    MAX_REDIRECT_HOPS,
    RATE_LIMIT_POLICY_VERSION,
    ROBOTS_POLICY_VERSION,
    client_contract_hash,
    follow_redirects,
    require_planned_request,
    require_planned_robots,
)
from collection_test_helpers import (  # noqa: E402
    ARCHIVE_HOST,
    IR_URL,
    PRODUCT_ARCHIVE,
    FakeTransport,
    ok,
    plan_payload,
    redirect,
)

PLAN = validate_request_plan(plan_payload())
LIVE_ENTRY = next(e for e in PLAN["entries"] if e["access_channel"] == "live")
ARCHIVE_ENTRY = next(
    e for e in PLAN["entries"] if e["archive_url"] == PRODUCT_ARCHIVE
)


# --- Class 1: independently initiated document requests ----------------------


def test_planned_url_is_authorized() -> None:
    assert require_planned_request(IR_URL, PLAN) == IR_URL


@pytest.mark.parametrize(
    "url",
    [
        "https://www.hubspot.com/pricing",
        "https://www.hubspot.com/products/marketing",  # original of an archive entry
        "https://evil.example/",
    ],
)
def test_undeclared_url_is_refused(url: str) -> None:
    with pytest.raises(CollectionError) as excinfo:
        require_planned_request(url, PLAN)
    assert excinfo.value.reason_code == "undeclared_url_refused"


# --- Class 2: robots requests -------------------------------------------------


def test_robots_permitted_only_for_a_planned_host() -> None:
    assert require_planned_robots("ir.hubspot.com", PLAN) == (
        "https://ir.hubspot.com/robots.txt"
    )
    assert require_planned_robots(ARCHIVE_HOST, PLAN) == (
        f"https://{ARCHIVE_HOST}/robots.txt"
    )


def test_robots_for_unplanned_host_is_refused() -> None:
    with pytest.raises(CollectionError) as excinfo:
        require_planned_robots("blog.hubspot.com", PLAN)
    assert excinfo.value.reason_code == "undeclared_url_refused"


# --- Class 3 positive: same-boundary redirects -------------------------------


def test_live_entry_redirect_within_apex_is_admitted() -> None:
    target = "https://ir.hubspot.com/financials/quarterly-results/"
    transport = FakeTransport(
        {IR_URL: redirect(target), target: ok(target, b"<html>ir</html>")}
    )
    outcome = follow_redirects(
        initial_url=IR_URL, entry=LIVE_ENTRY, transport=transport
    )
    assert outcome.status_code == 200
    assert outcome.final_url == target
    assert [h.url for h in outcome.redirect_hops] == [target]
    assert [h.status_code for h in outcome.redirect_hops] == [301]


def test_live_entry_redirect_to_another_subdomain_is_admitted() -> None:
    target = "https://www.hubspot.com/investors"
    transport = FakeTransport({IR_URL: redirect(target, 302), target: ok(target)})
    outcome = follow_redirects(
        initial_url=IR_URL, entry=LIVE_ENTRY, transport=transport
    )
    assert outcome.final_url == target
    assert len(outcome.redirect_hops) == 1


def test_archive_entry_redirect_within_archive_host_is_admitted() -> None:
    target = f"https://{ARCHIVE_HOST}/web/20250101id_/https://www.hubspot.com/products/marketing"
    transport = FakeTransport(
        {PRODUCT_ARCHIVE: redirect(target), target: ok(target)}
    )
    outcome = follow_redirects(
        initial_url=PRODUCT_ARCHIVE, entry=ARCHIVE_ENTRY, transport=transport
    )
    assert outcome.final_url == target
    assert len(outcome.redirect_hops) == 1


def test_multi_hop_chain_within_boundary_is_recorded_in_order() -> None:
    a = "https://www.hubspot.com/a"
    b = "https://www.hubspot.com/b"
    c = "https://www.hubspot.com/c"
    transport = FakeTransport(
        {IR_URL: redirect(a), a: redirect(b), b: redirect(c), c: ok(c)}
    )
    outcome = follow_redirects(
        initial_url=IR_URL, entry=LIVE_ENTRY, transport=transport
    )
    assert [h.url for h in outcome.redirect_hops] == [a, b, c]
    assert outcome.final_url == c


# --- Class 3 negative: cross-boundary hops -----------------------------------


def test_live_entry_hop_leaving_the_apex_is_refused() -> None:
    target = "https://cdn.example.net/asset"
    transport = FakeTransport({IR_URL: redirect(target)})
    with pytest.raises(CollectionError) as excinfo:
        follow_redirects(initial_url=IR_URL, entry=LIVE_ENTRY, transport=transport)
    assert excinfo.value.reason_code == "allowlist_violation"


def test_archive_entry_hop_leaving_the_archive_host_is_refused() -> None:
    target = "https://www.hubspot.com/products/marketing"
    transport = FakeTransport({PRODUCT_ARCHIVE: redirect(target)})
    with pytest.raises(CollectionError) as excinfo:
        follow_redirects(
            initial_url=PRODUCT_ARCHIVE, entry=ARCHIVE_ENTRY, transport=transport
        )
    assert excinfo.value.reason_code == "allowlist_violation"


def test_archive_entry_hop_to_a_different_archive_is_refused() -> None:
    target = "https://other.archive.example/web/2025/x"
    transport = FakeTransport({PRODUCT_ARCHIVE: redirect(target)})
    with pytest.raises(CollectionError) as excinfo:
        follow_redirects(
            initial_url=PRODUCT_ARCHIVE, entry=ARCHIVE_ENTRY, transport=transport
        )
    assert excinfo.value.reason_code == "allowlist_violation"


# --- Class 3 negative: loops and overlong chains -----------------------------


def test_redirect_loop_is_refused() -> None:
    a = "https://www.hubspot.com/a"
    transport = FakeTransport({IR_URL: redirect(a), a: redirect(IR_URL)})
    with pytest.raises(CollectionError) as excinfo:
        follow_redirects(initial_url=IR_URL, entry=LIVE_ENTRY, transport=transport)
    assert excinfo.value.reason_code == "redirect_chain_exceeded"


def test_self_loop_is_refused() -> None:
    transport = FakeTransport({IR_URL: redirect(IR_URL)})
    with pytest.raises(CollectionError) as excinfo:
        follow_redirects(initial_url=IR_URL, entry=LIVE_ENTRY, transport=transport)
    assert excinfo.value.reason_code == "redirect_chain_exceeded"


def test_chain_longer_than_the_bound_is_refused() -> None:
    urls = [f"https://www.hubspot.com/hop{i}" for i in range(MAX_REDIRECT_HOPS + 2)]
    responses = {IR_URL: redirect(urls[0])}
    for current, nxt in zip(urls, urls[1:]):
        responses[current] = redirect(nxt)
    transport = FakeTransport(responses)
    with pytest.raises(CollectionError) as excinfo:
        follow_redirects(initial_url=IR_URL, entry=LIVE_ENTRY, transport=transport)
    assert excinfo.value.reason_code == "redirect_chain_exceeded"


def test_exactly_the_bound_is_admitted() -> None:
    urls = [f"https://www.hubspot.com/hop{i}" for i in range(MAX_REDIRECT_HOPS)]
    responses = {IR_URL: redirect(urls[0])}
    for current, nxt in zip(urls, urls[1:]):
        responses[current] = redirect(nxt)
    responses[urls[-1]] = ok(urls[-1])
    outcome = follow_redirects(
        initial_url=IR_URL, entry=LIVE_ENTRY, transport=FakeTransport(responses)
    )
    assert len(outcome.redirect_hops) == MAX_REDIRECT_HOPS


# --- Terminal identity fails closed ------------------------------------------


def test_blank_terminal_final_url_is_refused() -> None:
    """`current` is never silently substituted for a missing final_url."""
    from dynamic_ai_products.collection.transport import TransportResponse

    transport = FakeTransport(
        {IR_URL: TransportResponse(status_code=200, final_url="", content=b"x")}
    )
    with pytest.raises(CollectionError) as excinfo:
        follow_redirects(initial_url=IR_URL, entry=LIVE_ENTRY, transport=transport)
    assert excinfo.value.reason_code == "terminal_url_mismatch"


def test_whitespace_terminal_final_url_is_refused() -> None:
    from dynamic_ai_products.collection.transport import TransportResponse

    transport = FakeTransport(
        {IR_URL: TransportResponse(status_code=200, final_url="   ", content=b"x")}
    )
    with pytest.raises(CollectionError) as excinfo:
        follow_redirects(initial_url=IR_URL, entry=LIVE_ENTRY, transport=transport)
    assert excinfo.value.reason_code == "terminal_url_mismatch"


def test_mismatched_terminal_final_url_is_refused() -> None:
    """A terminal response must name the URL we actually requested."""
    transport = FakeTransport({IR_URL: ok("https://www.hubspot.com/elsewhere")})
    with pytest.raises(CollectionError) as excinfo:
        follow_redirects(initial_url=IR_URL, entry=LIVE_ENTRY, transport=transport)
    assert excinfo.value.reason_code == "terminal_url_mismatch"


def test_off_boundary_terminal_final_url_is_refused() -> None:
    """A terminal URL outside the apex cannot slip in without a redirect hop."""
    transport = FakeTransport({IR_URL: ok("https://cdn.example.net/asset")})
    with pytest.raises(CollectionError) as excinfo:
        follow_redirects(initial_url=IR_URL, entry=LIVE_ENTRY, transport=transport)
    assert excinfo.value.reason_code == "terminal_url_mismatch"


def test_mismatched_terminal_url_after_a_redirect_is_refused() -> None:
    target = "https://www.hubspot.com/investors"
    transport = FakeTransport(
        {IR_URL: redirect(target), target: ok("https://www.hubspot.com/other")}
    )
    with pytest.raises(CollectionError) as excinfo:
        follow_redirects(initial_url=IR_URL, entry=LIVE_ENTRY, transport=transport)
    assert excinfo.value.reason_code == "terminal_url_mismatch"


def test_matching_terminal_url_is_admitted() -> None:
    transport = FakeTransport({IR_URL: ok(IR_URL)})
    outcome = follow_redirects(
        initial_url=IR_URL, entry=LIVE_ENTRY, transport=transport
    )
    assert outcome.final_url == IR_URL
    assert outcome.redirect_hops == ()


def test_redirect_without_location_is_refused() -> None:
    from dynamic_ai_products.collection.transport import TransportResponse

    transport = FakeTransport(
        {IR_URL: TransportResponse(status_code=301, final_url="", content=b"")}
    )
    with pytest.raises(CollectionError) as excinfo:
        follow_redirects(initial_url=IR_URL, entry=LIVE_ENTRY, transport=transport)
    assert excinfo.value.reason_code == "redirect_chain_exceeded"


# --- Cross-entry final-URL reuse ---------------------------------------------


def test_final_url_of_one_entry_never_authorizes_another_request() -> None:
    """A final URL is canonical for its own entry only."""
    discovered = "https://www.hubspot.com/investors"
    transport = FakeTransport(
        {IR_URL: redirect(discovered), discovered: ok(url=discovered)}
    )
    outcome = follow_redirects(
        initial_url=IR_URL, entry=LIVE_ENTRY, transport=transport
    )
    assert outcome.final_url == discovered
    # The discovered URL is not in the plan, so it can never be requested again.
    with pytest.raises(CollectionError) as excinfo:
        require_planned_request(outcome.final_url, PLAN)
    assert excinfo.value.reason_code == "undeclared_url_refused"


# --- Client identity ----------------------------------------------------------


def test_client_contract_is_declared_and_hashable() -> None:
    digest = client_contract_hash()
    assert len(digest) == 64 and digest == client_contract_hash()
    assert CLIENT_CONTRACT["max_redirect_hops"] == MAX_REDIRECT_HOPS
    assert CLIENT_CONTRACT["robots_policy_version"] == ROBOTS_POLICY_VERSION
    assert CLIENT_CONTRACT["rate_limit_policy_version"] == RATE_LIMIT_POLICY_VERSION
    for key in (
        "user_agent",
        "max_requests_per_second",
        "min_request_spacing_seconds",
        "max_retries_per_url",
        "archive_min_request_spacing_seconds",
    ):
        assert CLIENT_CONTRACT[key] not in (None, "")


def test_rate_limit_policy_declares_spacing_for_archives() -> None:
    assert (
        CLIENT_CONTRACT["archive_min_request_spacing_seconds"]
        >= CLIENT_CONTRACT["min_request_spacing_seconds"]
    )
