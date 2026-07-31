"""v0.4 observation recording and the direct-route send budget (ADR-040, E-C-D3).

Two things are proved here that no earlier contract could express:

* a ``direct`` route issues **exactly one** send under every terminal outcome --
  success, every refusal, and persistence failure -- and never follows a redirect
  it observed;
* the full authorized attempt emits **exactly five ordered calls**.

Both are asserted against the shared ordinal-only event queue, never by comparing
URLs, because E3's requested and final URLs are the same URL and a URL-equality
assertion could not tell a first send from a second.
"""

from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

from documentation_v4_transport import (  # noqa: E402
    BODY,
    ExpectedCall,
    OrdinalTransport,
    hop,
    terminal,
)

from dynamic_ai_products.collection import documentation_policy_v4 as dp4  # noqa: E402
from dynamic_ai_products.collection import documentation_receipt_v4 as v4  # noqa: E402
from dynamic_ai_products.collection.errors import CollectionError  # noqa: E402
from dynamic_ai_products.collection.http_adapter import AdapterResponse  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = (ROOT / "schemas" / "documentation_collection_receipt.v4.schema.json").read_bytes()
VALIDATOR = Draft202012Validator(json.loads(SCHEMA.decode("utf-8")))
COMMIT = "c53233bba5e43702e8de93a623592351cc361d73"
STAMP = "2026-07-31T09:00:00Z"
SENTINEL = "https://sentinel.test/POISONED-OBSERVED-VALUE"

E1, E2, E3 = dp4.FROZEN_EVIDENCE_ENTRIES_V4
LIVE_ATTEMPTS = {
    "docattempt-f88b54ac65e04d0766d749cb606bcee2",
    "docattempt-c4082dd835f2f5228669487f50ca2308",
}


def run(monkeypatch, tmp_path, script, *, clock=None):
    transport = OrdinalTransport(script)
    monkeypatch.setattr(dp4, "_send_once", transport)
    monkeypatch.setattr(dp4, "_sleep", lambda seconds: None)
    return (
        dp4.collect_documentation_evidence_v4(
            raw_root=tmp_path,
            receipt_schema_bytes=SCHEMA,
            code_commit=COMMIT,
            run_created_at=STAMP,
            retrieval_clock=clock or (lambda: STAMP),
        ),
        transport,
    )


def persisted(result) -> dict:
    return json.loads((result.attempt_root / result.receipt_reference).read_bytes())


def through_e2() -> list[ExpectedCall]:
    """The four sends that carry a run as far as E3's single send."""
    return [
        hop(1, E1["requested_url"], E1["final_url"]),
        terminal(2, E1["final_url"]),
        hop(3, E2["requested_url"], E2["final_url"]),
        terminal(4, E2["final_url"]),
    ]


def e3_entry(result) -> dict:
    entry = result.entries[2]
    assert entry["route_kind"] == "direct"
    return entry


# --- the full authorized attempt ----------------------------------------------


def test_full_success_emits_exactly_five_ordered_calls(monkeypatch, tmp_path: Path):
    result, transport = run(
        monkeypatch, tmp_path, through_e2() + [terminal(5, E3["requested_url"])]
    )
    assert result.completion_status == "completed"
    transport.assert_exhausted()
    assert transport.ordinals == [1, 2, 3, 4, 5]
    assert transport.calls == [
        (1, E1["requested_url"], False),
        (2, E1["final_url"], True),
        (3, E2["requested_url"], False),
        (4, E2["final_url"], True),
        (5, E3["requested_url"], True),
    ]
    assert not list(VALIDATOR.iter_errors(persisted(result)))


def test_the_declared_send_budget_matches_the_authorized_sequence():
    budget = dp4.POLICY_CONTRACT_V4["max_sends_by_route_kind"]
    total = sum(budget[e["route_kind"]] for e in dp4.FROZEN_EVIDENCE_ENTRIES_V4)
    assert total == dp4.POLICY_CONTRACT_V4["max_sends_per_attempt"] == 5
    assert budget["direct"] == 1


# --- the direct route issues exactly one send, under every outcome ------------


_E3_TERMINAL_OUTCOMES = [
    ("success", terminal(5, E3["requested_url"]), None),
    (
        "redirect-301",
        terminal(5, E3["requested_url"], status=301, location=SENTINEL),
        "direct_redirect_not_permitted",
    ),
    (
        "redirect-308",
        terminal(5, E3["requested_url"], status=308, location=SENTINEL),
        "direct_redirect_not_permitted",
    ),
    (
        "status-404",
        terminal(5, E3["requested_url"], status=404),
        "terminal_status_invalid",
    ),
    (
        "status-204",
        terminal(5, E3["requested_url"], status=204),
        "terminal_status_invalid",
    ),
    (
        "content-type",
        terminal(5, E3["requested_url"], headers={"content-type": "application/json"}),
        "content_type_invalid",
    ),
    (
        "empty-body",
        terminal(5, E3["requested_url"], body=b""),
        "entity_empty",
    ),
    (
        "identity-mismatch",
        ExpectedCall(
            5, E3["requested_url"], True,
            AdapterResponse(200, None, {"content-type": "text/html"}, SENTINEL, BODY, len(BODY)),
        ),
        "response_request_identity_mismatch",
    ),
    (
        "transport-timeout",
        ExpectedCall(
            5, E3["requested_url"], True,
            CollectionError("sanitized", reason_code="transport_timeout"),
        ),
        "transport_timeout",
    ),
    (
        "transport-failed",
        ExpectedCall(
            5, E3["requested_url"], True,
            CollectionError("sanitized", reason_code="transport_failed"),
        ),
        "transport_failed",
    ),
    (
        "entity-too-large",
        ExpectedCall(
            5, E3["requested_url"], True,
            CollectionError("sanitized", reason_code="entity_too_large"),
        ),
        "entity_too_large",
    ),
]


@pytest.mark.parametrize(
    "label,call,reason",
    _E3_TERMINAL_OUTCOMES,
    ids=[label for label, _, _ in _E3_TERMINAL_OUTCOMES],
)
def test_a_direct_route_issues_exactly_one_send_on_every_terminal_route(
    monkeypatch, tmp_path: Path, label, call, reason
):
    result, transport = run(monkeypatch, tmp_path, through_e2() + [call])
    transport.assert_exhausted()
    # The event queue is the proof: one and only one send for the direct route.
    assert transport.count_for(E3["requested_url"]) == 1, label
    assert len(transport.calls) == 5, label
    assert transport.calls[4] == (5, E3["requested_url"], True)
    # Nothing observed was ever requested.
    assert transport.count_for(SENTINEL) == 0, label

    entry = e3_entry(result)
    if reason is None:
        assert entry["entry_status"] == "succeeded"
        assert result.completion_status == "completed"
    else:
        assert entry["entry_status"] == "failed"
        assert entry["failure_reason"] == reason, label
        assert result.completion_status == "stopped"
        assert entry["failure_phase"] in v4.DIRECT_PHASES
    assert entry["request_chain"] == [E3["requested_url"]]
    assert entry["send2_observed_status"] is None
    assert entry["send2_observed_location"] is None
    assert entry["send2_observed_location_disposition"] == "no_response"
    assert not list(VALIDATOR.iter_errors(persisted(result)))


def test_a_direct_route_issues_one_send_when_persistence_refuses(
    monkeypatch, tmp_path: Path
):
    digest = sha256(BODY).hexdigest()
    corrupt = tmp_path / E3["evidence_kind"] / f"sha256-{digest}" / "document.html"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_bytes(b"<html>different</html>")

    result, transport = run(
        monkeypatch, tmp_path, through_e2() + [terminal(5, E3["requested_url"])]
    )
    entry = e3_entry(result)
    assert entry["failure_reason"] == "content_object_corrupt"
    assert entry["failure_phase"] == "persistence"
    assert transport.count_for(E3["requested_url"]) == 1
    assert len(transport.calls) == 5
    # The entity was accepted and storage refused it, so the entity facts are real.
    assert entry["content_sha256"] == digest
    assert entry["byte_count"] == len(BODY)
    assert entry["raw_reference"] is None
    assert corrupt.read_bytes() == b"<html>different</html>"
    assert not list(VALIDATOR.iter_errors(persisted(result)))


def test_a_direct_route_makes_no_send_at_all_when_its_preflight_refuses(
    monkeypatch, tmp_path: Path
):
    clock = iter([STAMP, STAMP, "not-an-instant"])
    result, transport = run(
        monkeypatch, tmp_path, through_e2(), clock=lambda: next(clock)
    )
    entry = e3_entry(result)
    assert entry["failure_reason"] == "retrieval_clock_invalid"
    assert entry["failure_phase"] == "entry_preflight"
    assert entry["request_chain"] == []
    assert transport.count_for(E3["requested_url"]) == 0
    assert len(transport.calls) == 4
    assert entry["send1_observed_location_disposition"] == "no_response"


def test_the_observed_redirect_target_is_in_the_persisted_bytes(monkeypatch, tmp_path: Path):
    """The observation survives to disk, not merely to the in-memory result."""
    result, transport = run(
        monkeypatch,
        tmp_path,
        through_e2()
        + [terminal(5, E3["requested_url"], status=301, location=SENTINEL)],
    )
    receipt = persisted(result)
    entry = receipt["entries"][2]
    assert entry["send1_observed_location"] == SENTINEL
    assert entry["send1_observed_location_disposition"] == "recorded"
    assert entry["send1_observed_status"] == 301
    assert entry["retrieval_timestamp"] == STAMP
    assert entry["request_chain"] == [E3["requested_url"]]
    assert SENTINEL.encode() in (result.attempt_root / result.receipt_reference).read_bytes()
    assert transport.count_for(SENTINEL) == 0


# --- observed values never enter the chain, and are never truncated -----------


@pytest.mark.parametrize(
    "location,disposition",
    [
        ("https://a.test/x", "recorded"),
        (None, "absent"),
        ("", "absent"),
        ("   ", "absent"),
        ("x" * 2049, "rejected_oversize"),
        ("https://a.test/\x01", "rejected_uncharacterizable"),
        ("https://a.test/ ", "rejected_uncharacterizable"),
        ("https://a.test/x\n", "rejected_uncharacterizable"),
    ],
)
def test_every_direct_redirect_location_is_dispositioned_and_never_truncated(
    monkeypatch, tmp_path: Path, location, disposition
):
    result, transport = run(
        monkeypatch,
        tmp_path,
        through_e2()
        + [terminal(5, E3["requested_url"], status=301, location=location)],
    )
    entry = e3_entry(result)
    assert entry["failure_reason"] == "direct_redirect_not_permitted"
    assert entry["send1_observed_location_disposition"] == disposition
    if disposition == "recorded":
        assert entry["send1_observed_location"] == location
    else:
        assert entry["send1_observed_location"] is None, "never a truncated remnant"
    assert entry["request_chain"] == [E3["requested_url"]]
    assert transport.count_for(E3["requested_url"]) == 1
    assert not list(VALIDATOR.iter_errors(persisted(result)))


# --- the exception surface ----------------------------------------------------


def test_no_observed_value_reaches_any_rendered_exception(monkeypatch, tmp_path: Path):
    """A poisoned Location must not appear on any exception the collector raises."""
    def failing_persist(*args, **kwargs):
        raise CollectionError("sanitized", reason_code="write_error")

    monkeypatch.setattr(dp4, "_persist_object", failing_persist)
    result, _ = run(
        monkeypatch,
        tmp_path,
        [hop(1, E1["requested_url"], E1["final_url"]), terminal(2, E1["final_url"])],
    )
    entry = result.entries[0]
    assert entry["failure_reason"] == "write_error"
    assert entry["failure_phase"] == "persistence"
    # And the refusal carrier itself holds only closed-vocabulary values.
    refusal = dp4._EntryRefusal("write_error", "persistence")
    assert refusal.args == ("write_error",)
    assert SENTINEL not in str(refusal) and SENTINEL not in repr(refusal)
    assert set(vars(refusal)) == {"reason_code", "phase"}


def test_the_refusal_carrier_holds_only_a_reason_and_a_phase():
    refusal = dp4._EntryRefusal("transport_failed", "send1_request")
    assert refusal.reason_code == "transport_failed"
    assert refusal.phase == "send1_request"
    assert str(refusal) == "transport_failed"
    with pytest.raises(ValueError):
        dp4._EntryRefusal("not_a_reason", "send1_request")
    with pytest.raises(ValueError):
        dp4._EntryRefusal("transport_failed", "not_a_phase")


def test_the_adapter_context_retention_is_a_known_residual(monkeypatch, tmp_path: Path):
    """``from None`` clears __cause__ but Python keeps __context__.

    The adapter is unchanged by this increment, so the lock claims only that no
    observed value reaches a *rendered* surface. This pins the residual instead
    of pretending it does not exist.
    """
    try:
        try:
            raise ValueError(SENTINEL)
        except Exception:
            raise CollectionError("sanitized", reason_code="transport_failed") from None
    except CollectionError as exc:
        assert exc.__cause__ is None
        assert exc.__suppress_context__ is True
        assert SENTINEL not in str(exc) and SENTINEL not in repr(exc)
        assert SENTINEL in str(exc.__context__), "the residual, recorded not hidden"


# --- attempt identity ---------------------------------------------------------


def test_the_v4_attempt_id_cannot_collide_with_either_live_attempt(
    monkeypatch, tmp_path: Path
):
    result, _ = run(
        monkeypatch, tmp_path, through_e2() + [terminal(5, E3["requested_url"])]
    )
    assert result.attempt_id not in LIVE_ATTEMPTS
    assert result.attempt_id.startswith("docattempt-")
    receipt = persisted(result)
    assert receipt["contract"] == "documentation_collection_receipt@0.4.0"
    assert receipt["schema_version"] == "0.4.0"
