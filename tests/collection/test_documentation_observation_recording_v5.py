"""v0.5 observation recording and the send budget (ADR-041, E-C-D4).

Proves what no earlier contract could express: a three-send chain records the
first hop's absolute Location, the second hop's raw absolute-path reference and
the resolved third request URL, all as distinct fields; the full authorized
attempt emits exactly eight ordered calls; and every refusal keeps the facts that
were true at that moment. All assertions read the ordinal event queue, never a
URL comparison.
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
from dynamic_ai_products.collection.errors import CollectionError  # noqa: E402

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


SENTINEL_PATH = "/POISONED-OBSERVED-PATH"
SENTINEL_URL = "https://sentinel.test/POISONED"
LIVE_ATTEMPTS = {
    "docattempt-f88b54ac65e04d0766d749cb606bcee2",
    "docattempt-c4082dd835f2f5228669487f50ca2308",
    "docattempt-921cb253da290dc5dadadd5afc7244d6",
    # The governed v0.5 attempt that completed. A fresh id must still avoid it.
    "docattempt-ef3032c82e618c8ace8e33b26326d5c6",
}
V5_ATTEMPT = "docattempt-ef3032c82e618c8ace8e33b26326d5c6"


def through(n: int) -> list:
    return full_success_script()[:n]


# --- the full authorized attempt ----------------------------------------------


def test_full_success_emits_exactly_eight_ordered_calls(monkeypatch, tmp_path: Path):
    result, transport = run(monkeypatch, tmp_path, full_success_script())
    assert result.completion_status == "completed"
    transport.assert_exhausted()
    assert transport.ordinals == [1, 2, 3, 4, 5, 6, 7, 8]
    assert len(transport.calls) == 8
    assert not list(VALIDATOR.iter_errors(persisted(result)))


def test_the_declared_send_budget_matches_the_authorized_sequence():
    budget = dp5.POLICY_CONTRACT_V5["sends_by_route_kind"]
    total = sum(budget[e["route_kind"]] for e in dp5.FROZEN_EVIDENCE_ENTRIES_V5)
    assert total == dp5.POLICY_CONTRACT_V5["max_sends_per_attempt"] == 8
    assert budget["redirect_twice_relative_path"] == 3
    assert budget["redirect_once"] == 2


def test_a_three_send_entry_records_all_three_observations(monkeypatch, tmp_path: Path):
    result, _ = run(monkeypatch, tmp_path, full_success_script())
    entry = persisted(result)["entries"][0]
    assert entry["send1_observed_status"] == 301
    assert entry["send1_observed_location"] == E1["intermediate_url"]
    assert entry["send1_observed_location_disposition"] == "recorded"
    assert entry["send2_observed_status"] == 301
    assert entry["send2_observed_location"] == E1["second_hop_location"]
    assert entry["send2_observed_location_disposition"] == "recorded"
    assert entry["send3_request_url"] == E1["final_url"]
    assert entry["send3_observed_status"] == 200
    assert entry["retrieval_timestamp"] == STAMP


def test_the_resolved_third_url_is_the_frozen_final_not_an_observed_value(
    monkeypatch, tmp_path: Path
):
    """The join uses a fixed declared base; the observed path only has to match."""
    result, transport = run(monkeypatch, tmp_path, full_success_script())
    for index in (0, 1):
        entry = result.entries[index]
        frozen = dp5.FROZEN_EVIDENCE_ENTRIES_V5[index]
        assert entry["send3_request_url"] == frozen["final_url"]
        assert v5.resolve_absolute_path_reference(frozen["second_hop_location"]) == (
            frozen["final_url"]
        )
        # The third send went to the frozen final, once.
        assert transport.count_for(frozen["final_url"]) == 1


# --- refusals keep what was established ---------------------------------------


def test_a_second_hop_grammar_refusal_keeps_the_first_hop_facts(
    monkeypatch, tmp_path: Path
):
    result, transport = run(
        monkeypatch, tmp_path,
        through(1) + [hop(2, E1["intermediate_url"], "//evil.test" + SENTINEL_PATH)],
    )
    entry = first_failure(result)
    assert entry["failure_reason"] == "second_location_not_relative_path"
    assert entry["failure_phase"] == "send2_evaluation"
    # Everything established before the refusal survives it.
    assert entry["send1_observed_status"] == 301
    assert entry["send1_observed_location"] == E1["intermediate_url"]
    assert entry["send2_observed_status"] == 301
    assert entry["send2_observed_location"] == "//evil.test" + SENTINEL_PATH
    assert entry["send2_observed_location_disposition"] == "recorded"
    assert entry["retrieval_timestamp"] == STAMP
    assert entry["request_chain"] == [E1["requested_url"], E1["intermediate_url"]]
    # Nothing derived from the observed value was ever requested.
    assert transport.count_for("//evil.test" + SENTINEL_PATH) == 0
    assert transport.count_for("https://evil.test" + SENTINEL_PATH) == 0
    assert entry["send3_request_url"] is None
    assert not list(VALIDATOR.iter_errors(persisted(result)))


def test_a_mismatched_second_path_is_recorded_and_never_resolved(
    monkeypatch, tmp_path: Path
):
    result, transport = run(
        monkeypatch, tmp_path, through(1) + [hop(2, E1["intermediate_url"], SENTINEL_PATH)]
    )
    entry = first_failure(result)
    assert entry["failure_reason"] == "second_location_mismatch"
    assert entry["send2_observed_location"] == SENTINEL_PATH
    # The would-be resolution was never issued.
    assert transport.count_for("https://docs.cloud.google.com" + SENTINEL_PATH) == 0
    assert len(transport.calls) == 2
    assert entry["send3_request_url"] is None
    receipt = persisted(result)
    assert SENTINEL_PATH.encode() in (result.attempt_root / result.receipt_reference).read_bytes()
    assert receipt["entries"][0]["send2_observed_location"] == SENTINEL_PATH


@pytest.mark.parametrize(
    "location,disposition",
    [
        ("/a/b", "recorded"),
        (None, "absent"),
        ("", "absent"),
        ("   ", "absent"),
        ("x" * 2049, "rejected_oversize"),
        ("/a\x01b", "rejected_uncharacterizable"),
        ("/a\u00a0b", "rejected_uncharacterizable"),
        ("/a\nb", "rejected_uncharacterizable"),
    ],
)
def test_every_second_location_is_dispositioned_and_never_truncated(
    monkeypatch, tmp_path: Path, location, disposition
):
    result, transport = run(
        monkeypatch, tmp_path, through(1) + [hop(2, E1["intermediate_url"], location)]
    )
    entry = first_failure(result)
    assert entry["send2_observed_location_disposition"] == disposition
    if disposition == "recorded":
        assert entry["send2_observed_location"] == location
    else:
        assert entry["send2_observed_location"] is None, "never a truncated remnant"
    assert len(transport.calls) == 2
    assert not list(VALIDATOR.iter_errors(persisted(result)))


def test_a_preflight_refusal_makes_no_send_at_all(monkeypatch, tmp_path: Path):
    clock = iter([STAMP, STAMP, "not-an-instant"])
    result, transport = run(
        monkeypatch, tmp_path, full_success_script()[:6], clock=lambda: next(clock)
    )
    entry = result.entries[2]
    assert entry["failure_reason"] == "retrieval_clock_invalid"
    assert entry["failure_phase"] == "entry_preflight"
    assert entry["request_chain"] == []
    assert len(transport.calls) == 6
    for ordinal in ("send1", "send2", "send3"):
        assert entry[f"{ordinal}_observed_location_disposition"] == "no_response"


def test_a_keylog_between_sends_stops_and_preserves_earlier_entries(
    monkeypatch, tmp_path: Path
):
    """A keylog appearing mid-attempt stops it; earlier entries keep their facts."""
    from dynamic_ai_products.collection import http_adapter

    base = OrdinalTransport(full_success_script())

    def send(*, url, iterate_body, **kwargs):
        # The adapter rechecks at the top of every send, exactly as in production.
        if len(base.calls) == 4:  # E2's second hop is next
            monkeypatch.setenv("SSLKEYLOGFILE", str(tmp_path / "kl.txt"))
        http_adapter.require_no_tls_keylog()
        return base(url=url, iterate_body=iterate_body, **kwargs)

    monkeypatch.setattr(dp5, "_send_once", send)
    monkeypatch.setattr(dp5, "_sleep", lambda s: None)
    result = dp5.collect_documentation_evidence_v5(
        raw_root=tmp_path,
        receipt_schema_bytes=SCHEMA,
        code_commit=COMMIT,
        run_created_at=STAMP,
        retrieval_clock=lambda: STAMP,
    )
    assert result.completion_status == "stopped"
    assert [e["entry_status"] for e in result.entries] == [
        "succeeded", "failed", "not_attempted"
    ]
    failed = result.entries[1]
    assert failed["failure_reason"] == "tls_keylog_environment_present"
    assert failed["failure_phase"] in v5.REASON_PHASES_V5["tls_keylog_environment_present"]
    # E1 completed before the keylog appeared and keeps everything it established.
    assert result.entries[0]["send3_request_url"] == E1["final_url"]
    assert result.entries[0]["content_sha256"] is not None
    assert not list(VALIDATOR.iter_errors(persisted(result)))


# --- the exception surface ----------------------------------------------------


def test_the_refusal_carrier_holds_only_a_reason_and_a_phase():
    refusal = dp5._EntryRefusal("second_location_mismatch", "send2_evaluation")
    assert refusal.reason_code == "second_location_mismatch"
    assert refusal.phase == "send2_evaluation"
    assert refusal.args == ("second_location_mismatch",)
    assert SENTINEL_PATH not in str(refusal) and SENTINEL_PATH not in repr(refusal)
    assert set(vars(refusal)) == {"reason_code", "phase"}
    with pytest.raises(ValueError):
        dp5._EntryRefusal("not_a_reason", "send2_evaluation")
    with pytest.raises(ValueError):
        dp5._EntryRefusal("second_location_mismatch", "not_a_phase")


def test_a_one_hop_route_cannot_raise_a_second_hop_refusal():
    """The reason vocabulary is kind-scoped, and the builder enforces it."""
    assert "second_location_mismatch" not in v5.ROUTE_KIND_REASONS_V5["redirect_once"]


def test_the_adapter_context_retention_is_a_known_residual():
    """``from None`` clears __cause__ but Python keeps __context__.

    The adapter is unchanged by this increment, so the claim is only that no
    observed value reaches a *rendered* surface.
    """
    try:
        try:
            raise ValueError(SENTINEL_URL)
        except Exception:
            raise CollectionError("sanitized", reason_code="transport_failed") from None
    except CollectionError as exc:
        assert exc.__cause__ is None
        assert exc.__suppress_context__ is True
        assert SENTINEL_URL not in str(exc) and SENTINEL_URL not in repr(exc)
        assert SENTINEL_URL in str(exc.__context__), "the residual, recorded not hidden"


# --- provenance ---------------------------------------------------------------


def test_the_curl_derived_chain_is_recorded_only_in_the_adr_not_as_evidence():
    """E2/E3 chain data is design input; it is never mistaken for collector output.

    The historical form of this test asserted that no v0.5 receipt existed at
    all -- true while the routes were an untested hypothesis, and false since the
    governed attempt completed. What must hold permanently is narrower and more
    useful: the curl-derived chain lives in the decision log, and a governed
    receipt is a separate artifact that carries no trace of it.
    """
    log = (ROOT / "docs" / "DECISION_LOG.md").read_text(encoding="utf-8")
    adr = log[log.index("## ADR-041"):]
    lowered = adr.lower()
    assert "curl" in lowered
    assert "not governed raw evidence" in lowered or "not governed evidence" in lowered
    assert "webfetch" in lowered


def test_a_governed_v5_receipt_carries_no_trace_of_the_curl_observations():
    """Collector output and design input must not blend into one another.

    Skipped where the attempt tree is absent: ``data/raw/**`` is gitignored, so a
    fresh clone has no receipts and this would otherwise pass vacuously.
    """
    receipt_path = (
        ROOT / "data" / "raw" / "documentation" / "vertex_ai" / "attempts"
        / V5_ATTEMPT / "collection_receipt.json"
    )
    if not receipt_path.is_file():
        pytest.skip("the governed v0.5 attempt is not present in this checkout")

    raw = receipt_path.read_bytes()
    receipt = json.loads(raw.decode("utf-8"))
    assert receipt["contract"] == "documentation_collection_receipt@0.5.0"
    assert receipt["attempt_id"] == V5_ATTEMPT
    assert receipt["completion_status"] == "completed"
    assert [e["entry_status"] for e in receipt["entries"]] == ["succeeded"] * 3
    # The receipt is collector output alone: no curl or WebFetch artefact in it.
    lowered = raw.lower()
    assert b"curl" not in lowered
    assert b"webfetch" not in lowered
    assert b"web_fetch" not in lowered


def test_the_routes_module_marks_e1_governed_and_e2_e3_supplied():
    source = (SRC / "documentation_routes_v5.py").read_text(encoding="utf-8")
    assert "docattempt-921cb253da290dc5dadadd5afc7244d6" in source
    assert "curl" in source.lower()
    assert "not" in source.lower() and "governed raw evidence" in source.lower()


# --- attempt identity ---------------------------------------------------------


def test_the_v5_attempt_id_cannot_collide_with_any_live_attempt(
    monkeypatch, tmp_path: Path
):
    result, _ = run(monkeypatch, tmp_path, full_success_script())
    assert result.attempt_id not in LIVE_ATTEMPTS
    assert result.attempt_id.startswith("docattempt-")
    receipt = persisted(result)
    assert receipt["contract"] == "documentation_collection_receipt@0.5.0"
    assert receipt["schema_version"] == "0.5.0"


def test_the_attempt_identity_is_deterministic(monkeypatch, tmp_path: Path):
    first, _ = run(monkeypatch, tmp_path, full_success_script())
    second_root = tmp_path / "second"
    second_root.mkdir()
    second, _ = run(monkeypatch, second_root, full_success_script())
    assert first.attempt_id == second.attempt_id, "same inputs, same identity"
