"""The v0.4 route grammar: two kinds, exact pairs (ADR-040, E-C-D3).

E1 and E2 are ``redirect_once``: their two URLs differ, so the authorized route
requires **exactly one** recognized hop, not "at most one". E3 is ``direct``: its
two URLs are the same URL, one send is issued, an initial 200 is the only success
path, and a redirect is recorded then refused without being followed.

Every send goes through the shared ordinal-only double, so no assertion here can
infer a phase from URL equality -- which matters precisely because E3's requested
and final URLs are identical.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

from documentation_v4_transport import (  # noqa: E402
    ExpectedCall,
    OrdinalTransport,
    hop,
    terminal,
)

from dynamic_ai_products.collection import documentation_policy_v4 as dp4  # noqa: E402
from dynamic_ai_products.collection import documentation_receipt_v4 as v4  # noqa: E402
from dynamic_ai_products.collection.http_adapter import AdapterResponse  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = (ROOT / "schemas" / "documentation_collection_receipt.v4.schema.json").read_bytes()
VALIDATOR = Draft202012Validator(json.loads(SCHEMA.decode("utf-8")))
COMMIT = "c53233bba5e43702e8de93a623592351cc361d73"
STAMP = "2026-07-31T09:00:00Z"

E1, E2, E3 = dp4.FROZEN_EVIDENCE_ENTRIES_V4
_E1_FINAL = E1["final_url"]
_E1_HOST = _E1_FINAL.split("/")[2]


def run(monkeypatch, tmp_path, script):
    transport = OrdinalTransport(script)
    monkeypatch.setattr(dp4, "_send_once", transport)
    monkeypatch.setattr(dp4, "_sleep", lambda seconds: None)
    return (
        dp4.collect_documentation_evidence_v4(
            raw_root=tmp_path,
            receipt_schema_bytes=SCHEMA,
            code_commit=COMMIT,
            run_created_at=STAMP,
            retrieval_clock=lambda: STAMP,
        ),
        transport,
    )


def first_failure(result) -> dict:
    """The failing entry, with the v0.4 truthfulness invariants enforced."""
    entry = next(e for e in result.entries if e["entry_status"] == "failed")
    kind, reason, phase = entry["route_kind"], entry["failure_reason"], entry["failure_phase"]
    assert reason in v4.ROUTE_KIND_REASONS[kind], (kind, reason)
    assert phase in v4.ROUTE_KIND_PHASES[kind], (kind, phase)
    assert phase in v4.REASON_PHASES[reason], (reason, phase)
    permitted = [[], [entry["requested_url"]]]
    if kind == "redirect_once":
        permitted.append([entry["requested_url"], entry["final_url"]])
    assert entry["request_chain"] in permitted
    return entry


def persisted(result) -> dict:
    return json.loads((result.attempt_root / result.receipt_reference).read_bytes())


# --- the frozen pairs ---------------------------------------------------------


def test_exactly_three_ordered_pairs_with_declared_kinds():
    assert len(dp4.FROZEN_EVIDENCE_ENTRIES_V4) == 3
    assert [e["evidence_kind"] for e in dp4.FROZEN_EVIDENCE_ENTRIES_V4] == [
        "gemini_thinking", "count_tokens", "pricing_standard",
    ]
    assert [e["route_kind"] for e in dp4.FROZEN_EVIDENCE_ENTRIES_V4] == [
        "redirect_once", "redirect_once", "direct",
    ]
    for entry in dp4.FROZEN_EVIDENCE_ENTRIES_V4:
        assert entry["requested_url"].startswith("https://")
        assert entry["final_url"].startswith("https://")
        for field in ("requested_url", "final_url"):
            assert "?" not in entry[field] and "#" not in entry[field]
        # The kind states the relationship; nothing is inferred from it.
        same = entry["requested_url"] == entry["final_url"]
        assert same is (entry["route_kind"] == "direct")


def test_the_public_api_has_no_url_parameter():
    import inspect

    parameters = inspect.signature(dp4.collect_documentation_evidence_v4).parameters
    assert "url" not in parameters and "urls" not in parameters


# --- the authorized routes ----------------------------------------------------


def test_the_authorized_sequence_is_hop_hop_direct(monkeypatch, tmp_path: Path):
    result, transport = run(
        monkeypatch,
        tmp_path,
        [
            hop(1, E1["requested_url"], E1["final_url"]),
            terminal(2, E1["final_url"]),
            hop(3, E2["requested_url"], E2["final_url"]),
            terminal(4, E2["final_url"]),
            terminal(5, E3["requested_url"]),
        ],
    )
    assert result.completion_status == "completed"
    transport.assert_exhausted()
    # Body iteration is requested only for the document-bearing sends.
    assert [flag for _, _, flag in transport.calls] == [False, True, False, True, True]
    for entry in result.entries:
        assert entry["entry_status"] == "succeeded"
        assert entry["failure_phase"] is None
        if entry["route_kind"] == "direct":
            assert entry["request_chain"] == [entry["requested_url"]]
            assert entry["send1_observed_status"] == 200
            assert entry["send2_observed_status"] is None
            assert entry["send2_observed_location_disposition"] == "no_response"
        else:
            assert entry["request_chain"] == [entry["requested_url"], entry["final_url"]]
            assert entry["send1_observed_status"] == 301
            assert entry["send1_observed_location"] == entry["final_url"]
            assert entry["send2_observed_status"] == 200
    assert not list(VALIDATOR.iter_errors(persisted(result)))


@pytest.mark.parametrize("status", [301, 308], ids=["301", "308"])
def test_both_permanent_redirect_statuses_are_accepted(monkeypatch, tmp_path: Path, status):
    result, _ = run(
        monkeypatch,
        tmp_path,
        [
            hop(1, E1["requested_url"], E1["final_url"], status=status),
            terminal(2, E1["final_url"]),
            hop(3, E2["requested_url"], E2["final_url"], status=status),
            terminal(4, E2["final_url"]),
            terminal(5, E3["requested_url"]),
        ],
    )
    assert result.completion_status == "completed"
    assert result.entries[0]["send1_observed_status"] == status


# --- redirect_once refusals (E1) ----------------------------------------------


def test_a_direct_two_hundred_on_a_hop_route_is_refused(monkeypatch, tmp_path: Path):
    """Not the authorized route: E1's frozen pair requires a hop.

    Scripted as a hop-shaped send answering 200, because a redirect_once route's
    first send never asks for a body -- the fake enforces that.
    """
    result, transport = run(
        monkeypatch, tmp_path, [hop(1, E1["requested_url"], None, status=200)]
    )
    assert result.completion_status == "stopped"
    assert first_failure(result)["failure_reason"] == "direct_terminal_not_permitted"
    assert first_failure(result)["failure_phase"] == "send1_evaluation"
    assert len(transport.calls) == 1


@pytest.mark.parametrize("status", [302, 303, 307, 404, 500])
def test_a_non_permanent_or_error_hop_status_is_refused(monkeypatch, tmp_path: Path, status):
    result, transport = run(
        monkeypatch,
        tmp_path,
        [hop(1, E1["requested_url"], E1["final_url"], status=status)],
    )
    assert first_failure(result)["failure_reason"] == "redirect_status_invalid"
    assert len(transport.calls) == 1


def test_a_missing_location_is_refused(monkeypatch, tmp_path: Path):
    result, _ = run(monkeypatch, tmp_path, [hop(1, E1["requested_url"], None)])
    entry = first_failure(result)
    assert entry["failure_reason"] == "redirect_location_missing"
    assert entry["send1_observed_location_disposition"] == "absent"


@pytest.mark.parametrize(
    "location",
    [
        "/models/thinking",
        "models/thinking",
        "//docs.cloud.google.com/x",
        _E1_FINAL.replace("https://", "http://"),
    ],
    ids=["absolute-path", "relative", "protocol-relative", "scheme-downgrade"],
)
def test_a_relative_or_downgraded_location_is_refused(monkeypatch, tmp_path: Path, location):
    result, _ = run(monkeypatch, tmp_path, [hop(1, E1["requested_url"], location)])
    entry = first_failure(result)
    assert entry["failure_reason"] == "redirect_location_not_absolute"
    # Refused as a route, yet still recorded as an observation.
    assert entry["send1_observed_location"] == location


@pytest.mark.parametrize(
    "location",
    [
        _E1_FINAL.rsplit("/", 1)[0] + "/other",
        _E1_FINAL.replace(_E1_HOST, "evil.test"),
        _E1_FINAL + "?a=1",
        _E1_FINAL + "#f",
        _E1_FINAL + "X",
    ],
    ids=["other-path", "other-host", "query", "fragment", "suffix"],
)
def test_a_location_that_is_not_the_frozen_final_is_refused(
    monkeypatch, tmp_path: Path, location
):
    result, transport = run(monkeypatch, tmp_path, [hop(1, E1["requested_url"], location)])
    entry = first_failure(result)
    assert entry["failure_reason"] == "redirect_location_mismatch"
    assert entry["send1_observed_location"] == location
    # Observed, never followed: the decoy was never requested.
    assert transport.count_for(location) == 0
    assert len(transport.calls) == 1


def test_a_second_redirect_on_a_hop_route_is_refused(monkeypatch, tmp_path: Path):
    result, transport = run(
        monkeypatch,
        tmp_path,
        [
            hop(1, E1["requested_url"], E1["final_url"]),
            terminal(2, E1["final_url"], status=301, location="https://elsewhere.test/x"),
        ],
    )
    entry = first_failure(result)
    assert entry["failure_reason"] == "redirect_chain_too_long"
    assert entry["failure_phase"] == "send2_evaluation"
    assert entry["send2_observed_location"] == "https://elsewhere.test/x"
    assert transport.count_for("https://elsewhere.test/x") == 0, "never followed"
    assert len(transport.calls) == 2


@pytest.mark.parametrize("status", [404, 500, 204])
def test_a_non_two_hundred_terminal_status_is_refused(monkeypatch, tmp_path: Path, status):
    result, _ = run(
        monkeypatch,
        tmp_path,
        [
            hop(1, E1["requested_url"], E1["final_url"]),
            terminal(2, E1["final_url"], status=status),
        ],
    )
    entry = first_failure(result)
    assert entry["failure_reason"] == "terminal_status_invalid"
    assert entry["failure_phase"] == "send2_evaluation"


@pytest.mark.parametrize("content_type", ["application/json", "text/plain", "", "text/htmlx"])
def test_a_non_html_terminal_content_type_is_refused(monkeypatch, tmp_path: Path, content_type):
    result, _ = run(
        monkeypatch,
        tmp_path,
        [
            hop(1, E1["requested_url"], E1["final_url"]),
            terminal(2, E1["final_url"], headers={"content-type": content_type}),
        ],
    )
    assert first_failure(result)["failure_reason"] == "content_type_invalid"


def test_an_empty_terminal_body_is_refused(monkeypatch, tmp_path: Path):
    result, _ = run(
        monkeypatch,
        tmp_path,
        [
            hop(1, E1["requested_url"], E1["final_url"]),
            terminal(2, E1["final_url"], body=b""),
        ],
    )
    assert first_failure(result)["failure_reason"] == "entity_empty"


@pytest.mark.parametrize("send", [1, 2], ids=["hop", "terminal"])
def test_a_mismatched_response_identity_is_refused_on_either_send(
    monkeypatch, tmp_path: Path, send
):
    script = [
        hop(1, E1["requested_url"], E1["final_url"]),
        terminal(2, E1["final_url"]),
    ]
    call = script[send - 1]
    answered = AdapterResponse(
        call.outcome.status,
        call.outcome.location,
        call.outcome.headers,
        "https://other.test/x",
        call.outcome.entity_bytes,
        call.outcome.decompressed_byte_count,
    )
    script[send - 1] = ExpectedCall(call.ordinal, call.url, call.iterate_body, answered)
    result, _ = run(monkeypatch, tmp_path, script[:send])
    entry = first_failure(result)
    assert entry["failure_reason"] == "response_request_identity_mismatch"
    assert entry["failure_phase"] == f"send{send}_evaluation"


# --- the direct route (E3) ----------------------------------------------------


def _through_e2() -> list[ExpectedCall]:
    return [
        hop(1, E1["requested_url"], E1["final_url"]),
        terminal(2, E1["final_url"]),
        hop(3, E2["requested_url"], E2["final_url"]),
        terminal(4, E2["final_url"]),
    ]


def test_a_direct_route_succeeds_on_an_initial_two_hundred(monkeypatch, tmp_path: Path):
    result, transport = run(
        monkeypatch, tmp_path, _through_e2() + [terminal(5, E3["requested_url"])]
    )
    assert result.completion_status == "completed"
    entry = result.entries[2]
    assert entry["route_kind"] == "direct"
    assert entry["entry_status"] == "succeeded"
    assert entry["request_chain"] == [E3["requested_url"]]
    # Exactly one send for the direct route, and it consumed the body.
    assert transport.count_for(E3["requested_url"]) == 1
    assert transport.calls[-1] == (5, E3["requested_url"], True)


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308], ids=lambda s: str(s))
def test_a_direct_route_records_a_redirect_and_refuses_without_following(
    monkeypatch, tmp_path: Path, status
):
    decoy = E3["requested_url"] + "-moved"
    result, transport = run(
        monkeypatch,
        tmp_path,
        _through_e2()
        + [terminal(5, E3["requested_url"], status=status, location=decoy)],
    )
    assert result.completion_status == "stopped"
    entry = result.entries[2]
    assert entry["failure_reason"] == "direct_redirect_not_permitted"
    assert entry["failure_phase"] == "send1_evaluation"
    assert entry["send1_observed_status"] == status
    assert entry["send1_observed_location"] == decoy
    assert entry["send1_observed_location_disposition"] == "recorded"
    # Recorded, never followed, and never a second send.
    assert transport.count_for(decoy) == 0
    assert transport.count_for(E3["requested_url"]) == 1
    assert entry["request_chain"] == [E3["requested_url"]]
    assert not list(VALIDATOR.iter_errors(persisted(result)))


def test_a_direct_route_never_reaches_a_hop_only_reason(monkeypatch, tmp_path: Path):
    """The reasons that describe a hop are absent from the direct vocabulary."""
    for reason in (
        "direct_terminal_not_permitted", "redirect_status_invalid",
        "redirect_location_missing", "redirect_location_not_absolute",
        "redirect_location_mismatch", "redirect_chain_too_long",
    ):
        assert reason not in v4.ROUTE_KIND_REASONS["direct"]
