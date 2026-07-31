"""The frozen route grammar: exactly one hop, exact pairs (ADR-037, E-C-D).

All three frozen pairs differ, so the authorized route requires **exactly one**
recognized redirect hop — not "at most one". A direct 200 at the requested URL
is therefore not the authorized route and is refused, which is the case a
"maximum one hop" reading would have silently accepted.

Offline: every send goes through a stub; nothing is written outside ``tmp_path``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dynamic_ai_products.collection import documentation_policy as dp
from dynamic_ai_products.collection.http_adapter import AdapterResponse

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = (ROOT / "schemas" / "documentation_collection_receipt.schema.json").read_bytes()
BODY = b"<html><body>official claim</body></html>"
HTML = {"content-type": "text/html; charset=utf-8"}
COMMIT = "4bcbe2e059714f9a7592751a2a9d1d59d0293bfa"
STAMP = "2026-07-31T09:00:00Z"


def _entry(kind: str) -> dict[str, str]:
    return next(e for e in dp.FROZEN_EVIDENCE_ENTRIES if e["evidence_kind"] == kind)


def _run(monkeypatch, tmp_path: Path, send):
    monkeypatch.setattr(dp, "_send_once", send)
    monkeypatch.setattr(dp, "_sleep", lambda seconds: None)
    return dp.collect_documentation_evidence(
        raw_root=tmp_path,
        receipt_schema_bytes=SCHEMA,
        code_commit=COMMIT,
        run_created_at=STAMP,
        retrieval_clock=lambda: STAMP,
    )


def _happy(*, url, iterate_body, **kwargs):
    pair = next(
        e for e in dp.FROZEN_EVIDENCE_ENTRIES
        if url in (e["requested_url"], e["final_url"])
    )
    if url == pair["requested_url"]:
        return AdapterResponse(301, pair["final_url"], {}, url, None, 0)
    return AdapterResponse(200, None, HTML, url, BODY, len(BODY))


def _first_failure(result) -> dict:
    return next(e for e in result.entries if e["entry_status"] == "failed")


# --- the frozen pairs ---------------------------------------------------------


def test_exactly_three_ordered_pairs_are_frozen():
    assert len(dp.FROZEN_EVIDENCE_ENTRIES) == 3
    assert [e["evidence_kind"] for e in dp.FROZEN_EVIDENCE_ENTRIES] == [
        "gemini_thinking",
        "count_tokens",
        "pricing_standard",
    ]
    for entry in dp.FROZEN_EVIDENCE_ENTRIES:
        assert entry["requested_url"].startswith("https://")
        assert entry["final_url"].startswith("https://")
        assert "?" not in entry["requested_url"] and "#" not in entry["requested_url"]
        assert "?" not in entry["final_url"] and "#" not in entry["final_url"]
        # Every pair genuinely differs, which is why exactly one hop is required.
        assert entry["requested_url"] != entry["final_url"]


def test_the_public_api_has_no_url_parameter():
    import inspect

    parameters = inspect.signature(dp.collect_documentation_evidence).parameters
    assert "url" not in parameters
    assert "urls" not in parameters


def test_the_happy_route_is_one_hop_then_two_hundred(monkeypatch, tmp_path: Path):
    sends: list[tuple[str, bool]] = []

    def send(*, url, iterate_body, **kwargs):
        sends.append((url, iterate_body))
        return _happy(url=url, iterate_body=iterate_body, **kwargs)

    result = _run(monkeypatch, tmp_path, send)
    assert result.completion_status == "completed"
    assert len(sends) == 6, "three redirect hops plus three terminal documents"
    # Redirect hops never request a body.
    assert [flag for _, flag in sends] == [False, True, False, True, False, True]
    for entry in result.entries:
        assert entry["entry_status"] == "succeeded"
        assert entry["redirect_chain"] == [entry["requested_url"], entry["final_url"]]


# --- refusals -----------------------------------------------------------------


def test_a_direct_two_hundred_at_the_requested_url_is_refused(
    monkeypatch, tmp_path: Path
):
    """Not the authorized route: the frozen pair requires a hop."""

    def send(*, url, iterate_body, **kwargs):
        return AdapterResponse(200, None, HTML, url, BODY, len(BODY))

    result = _run(monkeypatch, tmp_path, send)
    assert result.completion_status == "stopped"
    assert _first_failure(result)["failure_reason"] == "direct_terminal_not_permitted"


@pytest.mark.parametrize("status", [302, 303, 307, 404, 500])
def test_a_non_permanent_or_error_initial_status_is_refused(
    monkeypatch, tmp_path: Path, status
):
    def send(*, url, iterate_body, **kwargs):
        pair = _entry("gemini_thinking")
        return AdapterResponse(status, pair["final_url"], {}, url, None, 0)

    result = _run(monkeypatch, tmp_path, send)
    assert _first_failure(result)["failure_reason"] == "redirect_status_invalid"


def test_a_missing_location_is_refused(monkeypatch, tmp_path: Path):
    def send(*, url, iterate_body, **kwargs):
        return AdapterResponse(301, None, {}, url, None, 0)

    result = _run(monkeypatch, tmp_path, send)
    assert _first_failure(result)["failure_reason"] == "redirect_location_missing"


@pytest.mark.parametrize(
    "location",
    [
        "/models/thinking",
        "models/thinking",
        "//docs.cloud.google.com/x",
        # A scheme downgrade is not an accepted absolute https Location, so it
        # is caught here rather than by the frozen-pair comparison.
        "http://docs.cloud.google.com/gemini-enterprise-agent-platform/models/thinking",
    ],
    ids=["absolute-path", "relative", "protocol-relative", "scheme-downgrade"],
)
def test_a_relative_or_downgraded_location_is_refused(
    monkeypatch, tmp_path: Path, location
):
    """Relative resolution is not implemented, so it cannot be ambiguous."""

    def send(*, url, iterate_body, **kwargs):
        return AdapterResponse(301, location, {}, url, None, 0)

    result = _run(monkeypatch, tmp_path, send)
    assert _first_failure(result)["failure_reason"] == "redirect_location_not_absolute"


@pytest.mark.parametrize(
    "location",
    [
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/other",
        "https://evil.test/gemini-enterprise-agent-platform/models/thinking",
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/thinking?a=1",
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/thinking#f",
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/thinkingX",
    ],
    ids=["other-path", "other-host", "query", "fragment", "suffix"],
)
def test_a_location_that_is_not_the_frozen_final_url_is_refused(
    monkeypatch, tmp_path: Path, location
):
    def send(*, url, iterate_body, **kwargs):
        return AdapterResponse(301, location, {}, url, None, 0)

    result = _run(monkeypatch, tmp_path, send)
    assert _first_failure(result)["failure_reason"] == "redirect_location_mismatch"


def test_a_second_redirect_at_the_final_url_is_refused(monkeypatch, tmp_path: Path):
    def send(*, url, iterate_body, **kwargs):
        pair = next(
            e for e in dp.FROZEN_EVIDENCE_ENTRIES
            if url in (e["requested_url"], e["final_url"])
        )
        if url == pair["requested_url"]:
            return AdapterResponse(301, pair["final_url"], {}, url, None, 0)
        return AdapterResponse(301, "https://elsewhere.test/x", {}, url, None, 0)

    result = _run(monkeypatch, tmp_path, send)
    assert _first_failure(result)["failure_reason"] == "redirect_chain_too_long"


@pytest.mark.parametrize("status", [404, 500, 204])
def test_a_non_two_hundred_terminal_status_is_refused(
    monkeypatch, tmp_path: Path, status
):
    def send(*, url, iterate_body, **kwargs):
        pair = next(
            e for e in dp.FROZEN_EVIDENCE_ENTRIES
            if url in (e["requested_url"], e["final_url"])
        )
        if url == pair["requested_url"]:
            return AdapterResponse(301, pair["final_url"], {}, url, None, 0)
        return AdapterResponse(status, None, HTML, url, BODY, len(BODY))

    result = _run(monkeypatch, tmp_path, send)
    assert _first_failure(result)["failure_reason"] == "terminal_status_invalid"


@pytest.mark.parametrize(
    "content_type",
    ["application/json", "text/plain", "", "text/htmlx"],
)
def test_a_non_html_terminal_content_type_is_refused(
    monkeypatch, tmp_path: Path, content_type
):
    def send(*, url, iterate_body, **kwargs):
        pair = next(
            e for e in dp.FROZEN_EVIDENCE_ENTRIES
            if url in (e["requested_url"], e["final_url"])
        )
        if url == pair["requested_url"]:
            return AdapterResponse(301, pair["final_url"], {}, url, None, 0)
        return AdapterResponse(
            200, None, {"content-type": content_type}, url, BODY, len(BODY)
        )

    result = _run(monkeypatch, tmp_path, send)
    assert _first_failure(result)["failure_reason"] == "content_type_invalid"


def test_an_empty_terminal_body_is_refused(monkeypatch, tmp_path: Path):
    def send(*, url, iterate_body, **kwargs):
        pair = next(
            e for e in dp.FROZEN_EVIDENCE_ENTRIES
            if url in (e["requested_url"], e["final_url"])
        )
        if url == pair["requested_url"]:
            return AdapterResponse(301, pair["final_url"], {}, url, None, 0)
        return AdapterResponse(200, None, HTML, url, b"", 0)

    result = _run(monkeypatch, tmp_path, send)
    assert _first_failure(result)["failure_reason"] == "entity_empty"


@pytest.mark.parametrize("phase", ["redirect", "terminal"])
def test_a_mismatched_response_identity_is_refused_on_either_send(
    monkeypatch, tmp_path: Path, phase
):
    def send(*, url, iterate_body, **kwargs):
        pair = next(
            e for e in dp.FROZEN_EVIDENCE_ENTRIES
            if url in (e["requested_url"], e["final_url"])
        )
        if url == pair["requested_url"]:
            answered = "https://other.test/x" if phase == "redirect" else url
            return AdapterResponse(301, pair["final_url"], {}, answered, None, 0)
        answered = "https://other.test/x" if phase == "terminal" else url
        return AdapterResponse(200, None, HTML, answered, BODY, len(BODY))

    result = _run(monkeypatch, tmp_path, send)
    assert (
        _first_failure(result)["failure_reason"] == "response_request_identity_mismatch"
    )
