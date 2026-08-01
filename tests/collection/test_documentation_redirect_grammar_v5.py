"""The v0.5 route grammar: two kinds, exact pairs, narrow relative hop (ADR-041).

E1 and E2 are ``redirect_twice_relative_path``: send one and send two accept only
301/308, send one's Location must be byte-exact against the frozen intermediate,
and send two's Location must be a bare absolute-path reference byte-exact against
the frozen raw path whose join to a fixed declared base reproduces the frozen
final. E3 is ``redirect_once``. Every send goes through the shared ordinal-only
double, so no assertion here infers a phase from URL equality.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

from documentation_v5_transport import (  # noqa: E402
    ExpectedCall,
    OrdinalTransport,
    hop,
    terminal,
)

from dynamic_ai_products.collection import documentation_policy_v5 as dp5  # noqa: E402
from dynamic_ai_products.collection import documentation_receipt_v5 as v5  # noqa: E402
from dynamic_ai_products.collection.http_adapter import AdapterResponse  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "dynamic_ai_products" / "collection"
SCHEMA = (ROOT / "schemas" / "documentation_collection_receipt.v5.schema.json").read_bytes()
VALIDATOR = Draft202012Validator(json.loads(SCHEMA.decode("utf-8")))
COMMIT = "fbdc13eadb9912872c23fa21149a68c65f59a00c"
STAMP = "2026-08-01T09:00:00Z"

E1, E2, E3 = dp5.FROZEN_EVIDENCE_ENTRIES_V5


def full_success_script() -> list[ExpectedCall]:
    """The complete authorized call sequence: 3 + 3 + 2 = eight sends."""
    return [
        hop(1, E1["requested_url"], E1["intermediate_url"]),
        hop(2, E1["intermediate_url"], E1["second_hop_location"]),
        terminal(3, E1["final_url"]),
        hop(4, E2["requested_url"], E2["intermediate_url"]),
        hop(5, E2["intermediate_url"], E2["second_hop_location"]),
        terminal(6, E2["final_url"]),
        hop(7, E3["requested_url"], E3["final_url"]),
        terminal(8, E3["final_url"]),
    ]


def run(monkeypatch, tmp_path, script, *, clock=None, sleeps=None, **over):
    transport = OrdinalTransport(script)
    monkeypatch.setattr(dp5, "_send_once", transport)
    monkeypatch.setattr(
        dp5, "_sleep", (lambda s: sleeps.append(s)) if sleeps is not None else (lambda s: None)
    )
    kwargs = {
        "raw_root": tmp_path,
        "receipt_schema_bytes": SCHEMA,
        "code_commit": COMMIT,
        "run_created_at": STAMP,
        "retrieval_clock": clock or (lambda: STAMP),
    }
    kwargs.update(over)
    return dp5.collect_documentation_evidence_v5(**kwargs), transport


def persisted(result) -> dict:
    return json.loads((result.attempt_root / result.receipt_reference).read_bytes())


def first_failure(result) -> dict:
    entry = next(e for e in result.entries if e["entry_status"] == "failed")
    kind, reason, phase = entry["route_kind"], entry["failure_reason"], entry["failure_phase"]
    assert reason in v5.ROUTE_KIND_REASONS_V5[kind], (kind, reason)
    assert phase in v5.ROUTE_KIND_PHASES_V5[kind], (kind, phase)
    assert phase in v5.REASON_PHASES_V5[reason], (reason, phase)
    return entry


def files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def through(n: int) -> list:
    """The first ``n`` sends of the fully authorized sequence."""
    return full_success_script()[:n]


# --- the frozen pairs ---------------------------------------------------------


def test_exactly_three_ordered_routes_with_declared_kinds():
    assert len(dp5.FROZEN_EVIDENCE_ENTRIES_V5) == 3
    assert [e["evidence_kind"] for e in dp5.FROZEN_EVIDENCE_ENTRIES_V5] == [
        "gemini_thinking", "count_tokens", "pricing_standard",
    ]
    assert [e["route_kind"] for e in dp5.FROZEN_EVIDENCE_ENTRIES_V5] == [
        "redirect_twice_relative_path", "redirect_twice_relative_path", "redirect_once",
    ]
    for entry in dp5.FROZEN_EVIDENCE_ENTRIES_V5:
        assert entry["requested_url"].startswith("https://")
        assert entry["final_url"].startswith("https://")
        assert entry["requested_url"] != entry["final_url"]


def test_the_public_api_has_no_url_parameter():
    import inspect

    parameters = inspect.signature(dp5.collect_documentation_evidence_v5).parameters
    assert "url" not in parameters and "urls" not in parameters


# --- the authorized chains ----------------------------------------------------


def test_all_three_authorized_chains_succeed(monkeypatch, tmp_path: Path):
    result, transport = run(monkeypatch, tmp_path, full_success_script())
    assert result.completion_status == "completed"
    transport.assert_exhausted()
    assert [flag for _, _, flag in transport.calls] == [
        False, False, True, False, False, True, False, True
    ]
    for entry in result.entries:
        assert entry["entry_status"] == "succeeded"
        assert entry["failure_phase"] is None
        if entry["route_kind"] == "redirect_once":
            assert entry["request_chain"] == [entry["requested_url"], entry["final_url"]]
            assert entry["send1_observed_location"] == entry["final_url"]
            assert entry["send2_observed_status"] == 200
            assert entry["send3_request_url"] is None
            assert entry["send3_observed_status"] is None
        else:
            assert entry["request_chain"] == [
                entry["requested_url"], entry["intermediate_url"], entry["final_url"]
            ]
            assert entry["send1_observed_location"] == entry["intermediate_url"]
            assert entry["send2_observed_location"] == entry["second_hop_location"]
            assert entry["send3_request_url"] == entry["final_url"]
            assert entry["send3_observed_status"] == 200
    assert not list(VALIDATOR.iter_errors(persisted(result)))


@pytest.mark.parametrize("status", [301, 308], ids=["301", "308"])
def test_both_permanent_redirect_statuses_are_accepted_on_both_hops(
    monkeypatch, tmp_path: Path, status
):
    script = full_success_script()
    script[0] = hop(1, E1["requested_url"], E1["intermediate_url"], status=status)
    script[1] = hop(2, E1["intermediate_url"], E1["second_hop_location"], status=status)
    result, _ = run(monkeypatch, tmp_path, script)
    assert result.completion_status == "completed"
    assert result.entries[0]["send1_observed_status"] == status
    assert result.entries[0]["send2_observed_status"] == status


# --- first-hop refusals -------------------------------------------------------


def test_an_early_two_hundred_on_the_first_hop_is_refused(monkeypatch, tmp_path: Path):
    result, transport = run(
        monkeypatch, tmp_path, [hop(1, E1["requested_url"], None, status=200)]
    )
    entry = first_failure(result)
    assert entry["failure_reason"] == "direct_terminal_not_permitted"
    assert entry["failure_phase"] == "send1_evaluation"
    assert len(transport.calls) == 1


@pytest.mark.parametrize("status", [302, 303, 307, 404, 500])
def test_a_wrong_first_hop_status_is_refused(monkeypatch, tmp_path: Path, status):
    result, transport = run(
        monkeypatch, tmp_path,
        [hop(1, E1["requested_url"], E1["intermediate_url"], status=status)],
    )
    assert first_failure(result)["failure_reason"] == "redirect_status_invalid"
    assert len(transport.calls) == 1


def test_a_missing_first_location_is_refused(monkeypatch, tmp_path: Path):
    result, _ = run(monkeypatch, tmp_path, [hop(1, E1["requested_url"], None)])
    entry = first_failure(result)
    assert entry["failure_reason"] == "redirect_location_missing"
    assert entry["send1_observed_location_disposition"] == "absent"


@pytest.mark.parametrize(
    "location",
    ["/x", "x", "//docs.cloud.google.com/x",
     "http://docs.cloud.google.com/vertex-ai/generative-ai/docs/thinking"],
    ids=["absolute-path", "relative", "protocol-relative", "scheme-downgrade"],
)
def test_a_non_absolute_first_location_is_refused(monkeypatch, tmp_path: Path, location):
    result, _ = run(monkeypatch, tmp_path, [hop(1, E1["requested_url"], location)])
    entry = first_failure(result)
    assert entry["failure_reason"] == "redirect_location_not_absolute"
    assert entry["send1_observed_location"] == location


def test_a_wrong_intermediate_is_refused_and_never_followed(monkeypatch, tmp_path: Path):
    decoy = E1["intermediate_url"] + "-decoy"
    result, transport = run(monkeypatch, tmp_path, [hop(1, E1["requested_url"], decoy)])
    entry = first_failure(result)
    assert entry["failure_reason"] == "redirect_location_mismatch"
    assert entry["failure_phase"] == "send1_evaluation"
    assert entry["send1_observed_location"] == decoy
    assert transport.count_for(decoy) == 0, "observed, never followed"
    assert len(transport.calls) == 1
    assert entry["request_chain"] == [E1["requested_url"]]


@pytest.mark.parametrize(
    "location",
    [E1["intermediate_url"] + "X",
     E1["intermediate_url"] + "?a=1",
     E1["intermediate_url"] + "#f",
     E1["intermediate_url"].replace("docs.cloud.google.com", "evil.test")],
    ids=["suffix", "query", "fragment", "other-host"],
)
def test_a_near_miss_intermediate_is_refused(monkeypatch, tmp_path: Path, location):
    result, transport = run(monkeypatch, tmp_path, [hop(1, E1["requested_url"], location)])
    assert first_failure(result)["failure_reason"] == "redirect_location_mismatch"
    assert transport.count_for(location) == 0


# --- second-hop refusals ------------------------------------------------------


def test_an_early_two_hundred_on_the_second_hop_is_refused(monkeypatch, tmp_path: Path):
    result, transport = run(
        monkeypatch, tmp_path,
        through(1) + [hop(2, E1["intermediate_url"], None, status=200)],
    )
    entry = first_failure(result)
    assert entry["failure_reason"] == "direct_terminal_not_permitted"
    assert entry["failure_phase"] == "send2_evaluation"
    assert len(transport.calls) == 2


@pytest.mark.parametrize("status", [302, 303, 307, 404, 500])
def test_a_wrong_second_hop_status_is_refused(monkeypatch, tmp_path: Path, status):
    result, transport = run(
        monkeypatch, tmp_path,
        through(1) + [hop(2, E1["intermediate_url"], E1["second_hop_location"], status=status)],
    )
    entry = first_failure(result)
    assert entry["failure_reason"] == "second_redirect_status_invalid"
    assert entry["failure_phase"] == "send2_evaluation"
    assert len(transport.calls) == 2


def test_a_missing_second_location_is_refused(monkeypatch, tmp_path: Path):
    result, _ = run(
        monkeypatch, tmp_path, through(1) + [hop(2, E1["intermediate_url"], None)]
    )
    entry = first_failure(result)
    assert entry["failure_reason"] == "second_location_missing"
    assert entry["send2_observed_location_disposition"] == "absent"


@pytest.mark.parametrize(
    "location",
    [
        "gemini-enterprise-agent-platform/models/thinking",
        "//docs.cloud.google.com/gemini-enterprise-agent-platform/models/thinking",
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/thinking",
        "/gemini-enterprise-agent-platform/models/thinking?a=1",
        "/gemini-enterprise-agent-platform/models/thinking#f",
        "/u@h/models/thinking",
        "/gemini-enterprise-agent-platform/../../etc/passwd",
        "/a:b/models/thinking",
        "\\gemini-enterprise-agent-platform\\models",
    ],
    ids=["no-leading-slash", "protocol-relative", "absolute-url", "query", "fragment",
         "userinfo", "path-traversal", "colon", "backslash"],
)
def test_a_second_location_outside_the_narrow_grammar_is_refused(
    monkeypatch, tmp_path: Path, location
):
    result, transport = run(
        monkeypatch, tmp_path, through(1) + [hop(2, E1["intermediate_url"], location)]
    )
    entry = first_failure(result)
    assert entry["failure_reason"] == "second_location_not_relative_path"
    assert entry["failure_phase"] == "send2_evaluation"
    assert len(transport.calls) == 2, "never a third send"
    assert entry["send3_request_url"] is None
    assert entry["request_chain"] == [E1["requested_url"], E1["intermediate_url"]]


@pytest.mark.parametrize(
    "location",
    ["/gemini-enterprise-agent-platform/models/thinkingX",
     "/gemini-enterprise-agent-platform/models/other",
     "/models/thinking"],
    ids=["suffix", "other-leaf", "shorter"],
)
def test_a_well_formed_but_wrong_second_path_is_refused(monkeypatch, tmp_path: Path, location):
    result, transport = run(
        monkeypatch, tmp_path, through(1) + [hop(2, E1["intermediate_url"], location)]
    )
    entry = first_failure(result)
    assert entry["failure_reason"] == "second_location_mismatch"
    assert entry["send2_observed_location"] == location
    # Recorded, never followed: the resolved decoy was never requested.
    assert transport.count_for("https://docs.cloud.google.com" + location) == 0
    assert len(transport.calls) == 2


def test_a_second_redirect_after_the_document_send_is_refused(monkeypatch, tmp_path: Path):
    result, transport = run(
        monkeypatch, tmp_path,
        through(2) + [terminal(3, E1["final_url"], status=301, location="https://elsewhere.test/x")],
    )
    entry = first_failure(result)
    assert entry["failure_reason"] == "redirect_chain_too_long"
    assert entry["failure_phase"] == "send3_evaluation"
    assert entry["send3_observed_location"] == "https://elsewhere.test/x"
    assert transport.count_for("https://elsewhere.test/x") == 0
    assert len(transport.calls) == 3


# --- terminal refusals --------------------------------------------------------


@pytest.mark.parametrize("status", [404, 500, 204])
def test_a_non_two_hundred_terminal_status_is_refused(monkeypatch, tmp_path: Path, status):
    result, _ = run(
        monkeypatch, tmp_path, through(2) + [terminal(3, E1["final_url"], status=status)]
    )
    entry = first_failure(result)
    assert entry["failure_reason"] == "terminal_status_invalid"
    assert entry["failure_phase"] == "send3_evaluation"


@pytest.mark.parametrize("content_type", ["application/json", "text/plain", "", "text/htmlx"])
def test_a_non_html_terminal_content_type_is_refused(monkeypatch, tmp_path: Path, content_type):
    result, _ = run(
        monkeypatch, tmp_path,
        through(2) + [terminal(3, E1["final_url"], headers={"content-type": content_type})],
    )
    assert first_failure(result)["failure_reason"] == "content_type_invalid"


def test_an_empty_terminal_body_is_refused(monkeypatch, tmp_path: Path):
    result, _ = run(
        monkeypatch, tmp_path, through(2) + [terminal(3, E1["final_url"], body=b"")]
    )
    assert first_failure(result)["failure_reason"] == "entity_empty"


@pytest.mark.parametrize("send", [1, 2, 3])
def test_a_mismatched_response_identity_is_refused_on_any_send(
    monkeypatch, tmp_path: Path, send
):
    script = through(send)
    call = script[send - 1]
    answered = AdapterResponse(
        call.outcome.status, call.outcome.location, call.outcome.headers,
        "https://other.test/x", call.outcome.entity_bytes,
        call.outcome.decompressed_byte_count,
    )
    script[send - 1] = ExpectedCall(call.ordinal, call.url, call.iterate_body, answered)
    result, _ = run(monkeypatch, tmp_path, script)
    entry = first_failure(result)
    assert entry["failure_reason"] == "response_request_identity_mismatch"
    assert entry["failure_phase"] == f"send{send}_evaluation"


# --- the one-hop route (E3) ---------------------------------------------------


def test_the_one_hop_route_issues_exactly_two_sends(monkeypatch, tmp_path: Path):
    result, transport = run(monkeypatch, tmp_path, full_success_script())
    entry = result.entries[2]
    assert entry["route_kind"] == "redirect_once"
    assert transport.count_for(E3["requested_url"]) == 1
    assert transport.count_for(E3["final_url"]) == 1
    assert entry["send3_request_url"] is None
    assert entry["send3_observed_location_disposition"] == "no_response"


def test_the_one_hop_route_refuses_a_wrong_final(monkeypatch, tmp_path: Path):
    decoy = E3["final_url"] + "-decoy"
    result, transport = run(
        monkeypatch, tmp_path, full_success_script()[:6] + [hop(7, E3["requested_url"], decoy)]
    )
    entry = result.entries[2]
    assert entry["failure_reason"] == "redirect_location_mismatch"
    assert entry["failure_phase"] == "send1_evaluation"
    assert transport.count_for(decoy) == 0
    assert len(transport.calls) == 7
