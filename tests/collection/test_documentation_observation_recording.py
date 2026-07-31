"""E-C-D1 defect closure: observations survive a refusal (ADR-038).

Under ``documentation_collection_receipt@0.1.0`` a failed entry was rebuilt from
the frozen constants alone, so the request-start instant, the observed status,
the observed ``Location`` and the partial request chain were discarded. The live
attempt ``docattempt-f88b54ac…`` retained only the sanitized classification
``redirect_location_mismatch`` and no field-level observation at all.

Every test here is offline: the transport is reached only through the
module-private ``_send_once`` seam (or, for the one adapter-internal test, a
stubbed ``httpx.Client`` factory), spacing goes through ``_sleep``, and every
write lands under ``tmp_path``. No URL is retrieved and nothing touches ``data/``.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.collection import documentation_policy as dp
from dynamic_ai_products.collection import documentation_receipt_v2 as v2
from dynamic_ai_products.collection import http_adapter
from dynamic_ai_products.collection.errors import CollectionError
from dynamic_ai_products.collection.http_adapter import AdapterResponse

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "dynamic_ai_products" / "collection"
SCHEMA = (ROOT / "schemas" / "documentation_collection_receipt.v2.schema.json").read_bytes()
BODY = b"<html><body>official claim</body></html>"
HTML = {"content-type": "text/html; charset=utf-8"}
COMMIT = "4d285669820ad610643be29d4ff790e94d61c90d"
STAMP = "2026-07-31T09:00:00Z"
LIVE_V1_ATTEMPT = "docattempt-f88b54ac65e04d0766d749cb606bcee2"

# A decoy that is a well-formed absolute https URL and is NOT any frozen final,
# which is precisely the shape the live attempt actually met.
DECOY = "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/thinking-v2"

VALIDATOR = Draft202012Validator(v2.expected_receipt_schema_v2())


def _entry(index: int) -> dict[str, str]:
    return dp.FROZEN_EVIDENCE_ENTRIES[index]


def _run(monkeypatch, tmp_path: Path, send, *, clock=None):
    monkeypatch.setattr(dp, "_send_once", send)
    monkeypatch.setattr(dp, "_sleep", lambda seconds: None)
    return dp.collect_documentation_evidence(
        raw_root=tmp_path,
        receipt_schema_bytes=SCHEMA,
        code_commit=COMMIT,
        run_created_at=STAMP,
        retrieval_clock=clock or (lambda: STAMP),
    )


def _persisted(result) -> dict:
    return json.loads((result.attempt_root / result.receipt_reference).read_text("utf-8"))


def _redirect_with(location, *, status: int = 301, record=None):
    """A stub whose first send returns `location`; records every requested URL."""

    def send(*, url, iterate_body, **kwargs):
        if record is not None:
            record.append(url)
        return AdapterResponse(status, location, {}, url, None, 0)

    return send


# --- the defect, closed -------------------------------------------------------


def test_a_mismatched_location_is_recorded_and_never_followed(monkeypatch, tmp_path: Path):
    sends: list[str] = []
    result = _run(monkeypatch, tmp_path, _redirect_with(DECOY, record=sends))

    assert result.completion_status == "stopped"
    entry = result.entries[0]
    assert entry["entry_status"] == "failed"
    assert entry["failure_reason"] == "redirect_location_mismatch"
    assert entry["failure_phase"] == "redirect_evaluation"
    assert entry["redirect_observed_status"] == 301
    assert entry["redirect_observed_location"] == DECOY
    assert entry["redirect_observed_location_disposition"] == "recorded"
    assert entry["retrieval_timestamp"] == STAMP
    assert entry["request_chain"] == [_entry(0)["requested_url"]]

    # Recorded, and never requested: exactly one send, to the frozen URL.
    assert sends == [_entry(0)["requested_url"]]
    assert DECOY not in sends


def test_the_observation_is_in_the_persisted_bytes_not_only_in_memory(
    monkeypatch, tmp_path: Path
):
    """The U0-class assertion: prove the receipt on disk carries the observation."""
    result = _run(monkeypatch, tmp_path, _redirect_with(DECOY))
    raw = (result.attempt_root / result.receipt_reference).read_bytes()
    assert DECOY.encode("utf-8") in raw

    receipt = json.loads(raw.decode("utf-8"))
    assert not list(VALIDATOR.iter_errors(receipt))
    entry = receipt["entries"][0]
    assert entry["redirect_observed_location"] == DECOY
    assert entry["redirect_observed_status"] == 301
    assert entry["retrieval_timestamp"] == STAMP
    assert entry["failure_phase"] == "redirect_evaluation"
    assert receipt["contract"] == "documentation_collection_receipt@0.2.0"


def test_the_v0_1_0_shape_would_have_discarded_all_of_it():
    """Names exactly what 0.1.0 lost, so the regression cannot be undone quietly."""
    from dynamic_ai_products.collection.documentation_receipt import (
        expected_receipt_schema as expected_v1,
    )

    v1_entry = expected_v1()["properties"]["entries"]["prefixItems"][0]
    failed_branch = next(
        branch["then"]["properties"]
        for branch in v1_entry["allOf"]
        if branch["if"]["properties"]["entry_status"]["const"] == "failed"
    )
    assert failed_branch["redirect_chain"] == {"const": []}
    assert failed_branch["http_status"] == {"const": None}
    assert failed_branch["retrieval_timestamp"] == {"const": None}
    assert "observed_location" not in json.dumps(v1_entry)


# --- the decoy can never enter the request chain ------------------------------


@pytest.mark.parametrize(
    "location,disposition",
    [
        (DECOY, "recorded"),
        ("https://evil.test/elsewhere", "recorded"),
        ("/models/thinking", "recorded"),
        ("models/thinking", "recorded"),
        ("//docs.cloud.google.com/x", "recorded"),
        ("http://docs.cloud.google.com/x", "recorded"),
        ("https://a.test/" + "x" * 4096, "rejected_oversize"),
        ("https://a.test/\r\nSet-Cookie: pwned", "rejected_uncharacterizable"),
        ("https://a.test/\x00", "rejected_uncharacterizable"),
        ("https://a.test/\xe9", "rejected_uncharacterizable"),
        ("https://a.test/x, https://b.test/y", "recorded"),
        ("", "absent"),
        (None, "absent"),
    ],
    ids=[
        "near-miss", "other-host", "absolute-path", "relative", "protocol-relative",
        "scheme-downgrade", "oversize", "crlf", "nul", "latin1", "joined-duplicates",
        "empty", "missing",
    ],
)
def test_no_observed_location_variant_ever_enters_the_request_chain(
    monkeypatch, tmp_path: Path, location, disposition
):
    sends: list[str] = []
    result = _run(monkeypatch, tmp_path, _redirect_with(location, record=sends))

    entry = result.entries[0]
    assert entry["entry_status"] == "failed"
    assert entry["redirect_observed_location_disposition"] == disposition
    # The chain holds only the frozen URL this collector actually requested.
    assert entry["request_chain"] == [_entry(0)["requested_url"]]
    assert sends == [_entry(0)["requested_url"]]
    if location:
        assert location not in sends
    # And it is nowhere in any other entry either.
    for other in result.entries[1:]:
        assert other["request_chain"] == []
    assert not list(VALIDATOR.iter_errors(_persisted(result)))


@pytest.mark.parametrize(
    "location,reason",
    [
        (None, "redirect_location_missing"),
        ("", "redirect_location_missing"),
        ("/models/thinking", "redirect_location_not_absolute"),
        ("models/thinking", "redirect_location_not_absolute"),
        ("//docs.cloud.google.com/x", "redirect_location_not_absolute"),
        ("http://docs.cloud.google.com/x", "redirect_location_not_absolute"),
        (DECOY, "redirect_location_mismatch"),
        ("https://a.test/x, https://b.test/y", "redirect_location_mismatch"),
    ],
)
def test_the_location_behaviour_matrix(monkeypatch, tmp_path: Path, location, reason):
    result = _run(monkeypatch, tmp_path, _redirect_with(location))
    entry = result.entries[0]
    assert entry["failure_reason"] == reason
    assert entry["failure_phase"] == "redirect_evaluation"
    # Whatever the authorization outcome, the status observation survives.
    assert entry["redirect_observed_status"] == 301


def test_an_untranscribable_location_is_null_never_truncated(monkeypatch, tmp_path: Path):
    oversize = "https://a.test/" + "x" * 4096
    result = _run(monkeypatch, tmp_path, _redirect_with(oversize))
    entry = result.entries[0]
    assert entry["redirect_observed_location"] is None
    assert entry["redirect_observed_location_disposition"] == "rejected_oversize"
    raw = (result.attempt_root / result.receipt_reference).read_bytes()
    assert oversize[: v2.LOCATION_MAX_LENGTH].encode() not in raw, "no truncated artifact"


# --- dispositions distinguish the three kinds of nothing ----------------------


def test_no_response_absent_and_refused_are_distinct(monkeypatch, tmp_path: Path):
    # (a) no response at all: the clock fails before any send.
    def raising_clock():
        raise RuntimeError("upstream secret detail")

    result = _run(monkeypatch, tmp_path, _redirect_with(DECOY), clock=raising_clock)
    entry = result.entries[0]
    assert entry["failure_phase"] == "entry_preflight"
    assert entry["redirect_observed_location_disposition"] == "no_response"

    # (b) a response that carried no Location.
    result = _run(monkeypatch, tmp_path / "b", _redirect_with(None))
    assert result.entries[0]["redirect_observed_location_disposition"] == "absent"

    # (c) a response whose Location could not be transcribed.
    result = _run(monkeypatch, tmp_path / "c", _redirect_with("https://a.test/\x00"))
    assert (
        result.entries[0]["redirect_observed_location_disposition"]
        == "rejected_uncharacterizable"
    )


# --- pre-send failures stay null ----------------------------------------------


@pytest.mark.parametrize("value", ["", "2026-07-31", "2026-02-30T09:00:00Z", 7, None])
def test_a_pre_send_failure_records_no_observation(monkeypatch, tmp_path: Path, value):
    sends: list[str] = []
    result = _run(
        monkeypatch, tmp_path, _redirect_with(DECOY, record=sends), clock=lambda: value
    )
    entry = result.entries[0]
    assert entry["failure_reason"] == "retrieval_clock_invalid"
    assert entry["failure_phase"] == "entry_preflight"
    assert entry["request_chain"] == []
    assert entry["retrieval_timestamp"] is None
    for field in (
        "redirect_observed_status", "redirect_observed_location",
        "terminal_observed_status", "terminal_observed_location",
    ):
        assert entry[field] is None, field
    assert entry["redirect_observed_location_disposition"] == "no_response"
    assert sends == []


def test_not_attempted_entries_record_no_observation(monkeypatch, tmp_path: Path):
    result = _run(monkeypatch, tmp_path, _redirect_with(DECOY))
    for entry in result.entries[1:]:
        assert entry["entry_status"] == "not_attempted"
        assert entry["failure_reason"] is None and entry["failure_phase"] is None
        assert entry["request_chain"] == []
        assert entry["redirect_observed_location_disposition"] == "no_response"
        assert entry["terminal_observed_location_disposition"] == "no_response"


# --- later phases record what they had ----------------------------------------


def test_a_second_hop_records_the_terminal_location_and_is_not_followed(
    monkeypatch, tmp_path: Path
):
    sends: list[str] = []
    second = "https://elsewhere.test/again"

    def send(*, url, iterate_body, **kwargs):
        sends.append(url)
        pair = _entry(0)
        if url == pair["requested_url"]:
            return AdapterResponse(301, pair["final_url"], {}, url, None, 0)
        return AdapterResponse(308, second, {}, url, None, 0)

    result = _run(monkeypatch, tmp_path, send)
    entry = result.entries[0]
    assert entry["failure_reason"] == "redirect_chain_too_long"
    assert entry["failure_phase"] == "terminal_evaluation"
    assert entry["terminal_observed_status"] == 308
    assert entry["terminal_observed_location"] == second
    assert entry["terminal_observed_location_disposition"] == "recorded"
    assert entry["request_chain"] == [_entry(0)["requested_url"], _entry(0)["final_url"]]
    assert second not in sends
    assert not list(VALIDATOR.iter_errors(_persisted(result)))


@pytest.mark.parametrize(
    "status,reason", [(404, "terminal_status_invalid"), (204, "terminal_status_invalid")]
)
def test_a_terminal_refusal_retains_both_observations(
    monkeypatch, tmp_path: Path, status, reason
):
    def send(*, url, iterate_body, **kwargs):
        pair = _entry(0)
        if url == pair["requested_url"]:
            return AdapterResponse(301, pair["final_url"], {}, url, None, 0)
        return AdapterResponse(status, None, HTML, url, BODY, len(BODY))

    result = _run(monkeypatch, tmp_path, send)
    entry = result.entries[0]
    assert entry["failure_reason"] == reason
    assert entry["failure_phase"] == "terminal_evaluation"
    assert entry["redirect_observed_status"] == 301
    assert entry["redirect_observed_location"] == _entry(0)["final_url"]
    assert entry["terminal_observed_status"] == status
    assert entry["retrieval_timestamp"] == STAMP


def test_a_persistence_failure_records_the_accepted_entity(monkeypatch, tmp_path: Path):
    from hashlib import sha256

    digest = sha256(BODY).hexdigest()
    (tmp_path / "gemini_thinking" / f"sha256-{digest}" / "document.html").mkdir(parents=True)

    def send(*, url, iterate_body, **kwargs):
        pair = _entry(0)
        if url == pair["requested_url"]:
            return AdapterResponse(301, pair["final_url"], {}, url, None, 0)
        return AdapterResponse(200, None, HTML, url, BODY, len(BODY))

    result = _run(monkeypatch, tmp_path, send)
    entry = result.entries[0]
    assert entry["failure_reason"] == "content_object_corrupt"
    assert entry["failure_phase"] == "persistence"
    assert entry["byte_count"] == len(BODY)
    assert entry["content_sha256"] == digest
    assert entry["content_type"] == HTML["content-type"]
    # The entity was real; no object exists.
    assert entry["raw_reference"] is None and entry["object_disposition"] is None
    assert not list(VALIDATOR.iter_errors(_persisted(result)))


def test_a_success_records_the_accepted_redirect_observation(monkeypatch, tmp_path: Path):
    def send(*, url, iterate_body, **kwargs):
        pair = next(
            e for e in dp.FROZEN_EVIDENCE_ENTRIES
            if url in (e["requested_url"], e["final_url"])
        )
        if url == pair["requested_url"]:
            return AdapterResponse(308, pair["final_url"], {}, url, None, 0)
        return AdapterResponse(200, None, HTML, url, BODY, len(BODY))

    result = _run(monkeypatch, tmp_path, send)
    assert result.completion_status == "completed"
    for index, entry in enumerate(result.entries):
        assert entry["entry_status"] == "succeeded"
        assert entry["failure_phase"] is None
        assert entry["redirect_observed_status"] == 308
        assert entry["redirect_observed_location"] == _entry(index)["final_url"]
        assert entry["terminal_observed_status"] == 200
        assert entry["request_chain"] == [
            _entry(index)["requested_url"], _entry(index)["final_url"]
        ]
    assert not list(VALIDATOR.iter_errors(_persisted(result)))


# --- every entry-recordable reason is reachable with a declared phase ---------


def test_every_recorded_failure_names_a_phase_its_reason_permits(
    monkeypatch, tmp_path: Path
):
    scenarios = [
        (_redirect_with(DECOY), {}),
        (_redirect_with(None), {}),
        (_redirect_with("/x"), {}),
        (_redirect_with(DECOY, status=302), {}),
        (_redirect_with(DECOY, status=200), {}),
        (_redirect_with(DECOY), {"clock": lambda: "bad"}),
    ]
    for index, (send, extra) in enumerate(scenarios):
        result = _run(monkeypatch, tmp_path / f"s{index}", send, **extra)
        entry = result.entries[0]
        reason, phase = entry["failure_reason"], entry["failure_phase"]
        assert reason in v2.REASON_PHASES, reason
        assert phase in v2.REASON_PHASES[reason], (reason, phase)


# --- the adapter-side keylog recheck ------------------------------------------
#
# ``send_once`` performs its own ``require_no_tls_keylog()`` at the top, after
# the policy's precheck for that phase has already passed. A keylog appearing in
# between is refused there, with the send initiated and no response received.
# ``REASON_PHASES`` originally excluded ``redirect_request``/``terminal_request``
# for that reason, so the builder refused the entry and the attempt was left with
# an empty root and no terminal receipt at all -- a reachable path that could not
# be published. These tests pin the corrected behaviour.


@pytest.mark.parametrize(
    "trip_on_send,phase,chain_length",
    [(1, "redirect_request", 1), (2, "terminal_request", 2)],
    ids=["first-send", "second-send"],
)
def test_an_adapter_side_keylog_publishes_a_truthful_stopped_receipt(
    monkeypatch, tmp_path: Path, trip_on_send, phase, chain_length
):
    sends: list[str] = []

    def send(*, url, iterate_body, **kwargs):
        sends.append(url)
        if len(sends) == trip_on_send:
            # The keylog appears after the policy precheck for this phase; the
            # adapter's own recheck is what catches it, exactly as in production.
            monkeypatch.setenv("SSLKEYLOGFILE", str(tmp_path / "keylog.txt"))
            http_adapter.require_no_tls_keylog()
        pair = _entry(0)
        if url == pair["requested_url"]:
            return AdapterResponse(301, pair["final_url"], {}, url, None, 0)
        return AdapterResponse(200, None, HTML, url, BODY, len(BODY))

    result = _run(monkeypatch, tmp_path, send)

    # The regression: a terminal receipt exists at all.
    receipt_path = result.attempt_root / result.receipt_reference
    assert receipt_path.is_file(), "the attempt must not be left without a receipt"
    assert result.completion_status == "stopped"

    entry = result.entries[0]
    assert entry["failure_reason"] == "tls_keylog_environment_present"
    assert entry["failure_phase"] == phase
    assert phase in v2.REASON_PHASES["tls_keylog_environment_present"]
    assert entry["request_chain"] == [
        _entry(0)["requested_url"], _entry(0)["final_url"]
    ][:chain_length]
    # No response was received for the refused send.
    if phase == "redirect_request":
        assert entry["redirect_observed_status"] is None
        assert entry["redirect_observed_location_disposition"] == "no_response"
    else:
        assert entry["redirect_observed_status"] == 301
        assert entry["terminal_observed_status"] is None
        assert entry["terminal_observed_location_disposition"] == "no_response"
    assert entry["retrieval_timestamp"] == STAMP

    # No later request, and the receipt is schema-valid on disk.
    assert len(sends) == trip_on_send, "the attempt stops at the refusing send"
    assert not list(VALIDATOR.iter_errors(_persisted(result)))
    assert [e["entry_status"] for e in result.entries] == [
        "failed", "not_attempted", "not_attempted",
    ]


def test_the_keylog_reason_covers_every_point_it_can_be_raised():
    """Two policy prechecks and two adapter rechecks: four reachable phases."""
    assert set(v2.REASON_PHASES["tls_keylog_environment_present"]) == {
        "entry_preflight", "redirect_request", "terminal_preflight", "terminal_request",
    }


# --- the exception surface ----------------------------------------------------


SENTINEL = "SENTINEL-OBSERVED-VALUE-9f3a"


def test_an_entry_refusal_carries_only_closed_vocabulary(monkeypatch, tmp_path: Path):
    poisoned = f"https://a.test/{SENTINEL}"
    observation = dp._Observation()
    monkeypatch.setattr(dp, "_send_once", _redirect_with(poisoned))
    monkeypatch.setattr(dp, "_sleep", lambda seconds: None)

    with pytest.raises(dp._EntryRefusal) as excinfo:
        dp._attempt_entry(
            _entry(0),
            retrieval_clock=lambda: STAMP,
            accepted_total=0,
            spacer=lambda: None,
            observation=observation,
        )
    refusal = excinfo.value
    assert refusal.reason_code == "redirect_location_mismatch"
    assert refusal.phase == "redirect_evaluation"
    assert refusal.args == ("redirect_location_mismatch",)
    for surface in (str(refusal), repr(refusal), str(refusal.args)):
        assert SENTINEL not in surface
    assert refusal.__cause__ is None
    # The accumulator -- not the exception -- is what carries the observation.
    assert observation.redirect_location == poisoned


def test_an_entry_refusal_refuses_an_undeclared_reason_or_phase():
    with pytest.raises(ValueError):
        dp._EntryRefusal("not_a_reason", "redirect_evaluation")
    with pytest.raises(ValueError):
        dp._EntryRefusal("redirect_location_mismatch", "not_a_phase")
    with pytest.raises(ValueError):
        dp._EntryRefusal("attempt_root_exists", "entry_preflight")


def test_no_observed_value_reaches_a_public_collection_error(monkeypatch, tmp_path: Path):
    """Every attempt-level failure is sanitized, whatever the transport returned."""
    poisoned_headers = {"content-type": f"text/{SENTINEL}", "location": SENTINEL}

    def send(*, url, iterate_body, **kwargs):
        return AdapterResponse(301, f"https://a.test/{SENTINEL}", poisoned_headers, url, None, 0)

    monkeypatch.setattr(dp, "_send_once", send)
    monkeypatch.setattr(dp, "_sleep", lambda seconds: None)
    with pytest.raises(CollectionError) as excinfo:
        dp.collect_documentation_evidence(
            raw_root=tmp_path,
            receipt_schema_bytes=b"{}",
            code_commit=COMMIT,
            run_created_at=STAMP,
            retrieval_clock=lambda: STAMP,
        )
    exc = excinfo.value
    for surface in (str(exc), repr(exc), str(exc.args), str(exc.detail), str(exc.stop_reason)):
        assert SENTINEL not in surface
    assert exc.reason_code in dp.DOCUMENTATION_REASON_CODES


def test_the_adapter_implicit_context_retention_is_a_known_residual(monkeypatch):
    """A stated limitation of leaving http_adapter.py unchanged (ADR-038).

    ``raise ... from None`` clears ``__cause__`` and suppresses display, but
    CPython still retains the upstream object in ``__context__``. The adapter is
    outside this increment's path set, so that retention is documented rather
    than claimed away. What matters is that it never reaches a rendered surface
    or a governed artifact -- which is what this test pins.
    """

    class _Poisoned(RuntimeError):
        pass

    def exploding_client(*args, **kwargs):
        raise _Poisoned(SENTINEL)

    monkeypatch.setattr(http_adapter.httpx, "Client", exploding_client)
    with pytest.raises(CollectionError) as excinfo:
        http_adapter.send_once(url="https://a.test/x", iterate_body=False)

    exc = excinfo.value
    # The guarantee that is claimed:
    assert exc.reason_code == "transport_failed"
    assert exc.__cause__ is None
    assert exc.__suppress_context__ is True
    for surface in (str(exc), repr(exc), str(exc.args), str(exc.detail)):
        assert SENTINEL not in surface
    # The residual that is documented, not claimed away. If a future adapter
    # change removes it, this fails loudly and the limitation is re-decided.
    assert isinstance(exc.__context__, _Poisoned)
    assert SENTINEL in str(exc.__context__)


def test_no_governed_artifact_ever_serializes_an_exception_context(
    monkeypatch, tmp_path: Path
):
    """Whatever __context__ holds, the receipt is built from the accumulator."""

    def send(*, url, iterate_body, **kwargs):
        raise CollectionError("the request could not be completed", reason_code="transport_failed")

    result = _run(monkeypatch, tmp_path, send)
    raw = (result.attempt_root / result.receipt_reference).read_bytes()
    assert b"__context__" not in raw and b"Traceback" not in raw
    entry = result.entries[0]
    assert entry["failure_reason"] == "transport_failed"
    assert entry["failure_phase"] == "redirect_request"
    assert entry["request_chain"] == [_entry(0)["requested_url"]]
    assert entry["redirect_observed_status"] is None
    assert entry["redirect_observed_location_disposition"] == "no_response"


# --- static shape of the raise sites ------------------------------------------


def _policy_tree() -> ast.Module:
    return ast.parse((SRC / "documentation_policy.py").read_text(encoding="utf-8"))


def _raises(name: str) -> list[ast.Call]:
    calls = []
    for node in ast.walk(_policy_tree()):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            func = node.exc.func
            label = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if label == name:
                calls.append(node.exc)
    return calls


def test_every_collection_error_message_is_a_constant():
    """A message is free text: the one place an observed value could hide."""
    calls = _raises("CollectionError")
    assert calls, "the policy must still raise CollectionError"
    for call in calls:
        assert call.args, ast.dump(call)
        # Adjacent string literals are folded into one Constant by the parser,
        # so implicit concatenation is covered by this check.
        assert isinstance(call.args[0], ast.Constant), ast.dump(call.args[0])
        assert isinstance(call.args[0].value, str)


def _assignments(name: str) -> list[ast.expr]:
    """Every value assigned to `name` anywhere in the policy module."""
    values = []
    for node in ast.walk(_policy_tree()):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    values.append(node.value)
    return values


def _reason_constants(node: ast.expr) -> list[str]:
    """Resolve a reason_code expression to the literal codes it can produce.

    Fails the caller by returning an empty list for any shape that cannot be
    resolved, so an unresolvable expression is never silently accepted.
    """
    if isinstance(node, ast.Constant):
        return [node.value] if isinstance(node.value, str) else []
    if isinstance(node, ast.IfExp):
        return _reason_constants(node.body) + _reason_constants(node.orelse)
    if isinstance(node, ast.Name):
        resolved: list[str] = []
        for value in _assignments(node.id):
            resolved.extend(_reason_constants(value))
        return resolved
    return []


def test_dynamic_reason_codes_stay_in_the_closed_vocabulary():
    """A validated closed-vocabulary code may be propagated; free text may not.

    ``_persist_object`` legitimately selects its code with a conditional and
    forwards it through a local, so a Constant-only call shape would be an
    impossible requirement. What is enforced instead is the property that
    actually matters: every code the expression can produce is a member of the
    closed vocabulary.
    """
    for call in _raises("CollectionError"):
        keyword = next((k for k in call.keywords if k.arg == "reason_code"), None)
        assert keyword is not None, ast.dump(call)
        codes = _reason_constants(keyword.value)
        assert codes, f"unresolvable reason_code shape: {ast.dump(keyword.value)}"
        for code in codes:
            assert code in dp.DOCUMENTATION_REASON_CODES, code


def test_the_resolver_rejects_an_unresolvable_reason_shape():
    """The guard is proven against what it exists to catch."""
    assert _reason_constants(ast.parse("f'{value}'", mode="eval").body) == []
    assert _reason_constants(ast.parse("str(observed)", mode="eval").body) == []
    assert _reason_constants(ast.parse("'write_error'", mode="eval").body) == ["write_error"]


def test_every_entry_refusal_names_a_declared_reason_and_phase():
    from dynamic_ai_products.collection.documentation_receipt import (
        ENTRY_RECORDABLE_REASONS,
    )

    calls = _raises("_EntryRefusal")
    assert calls, "entry-level refusals must travel on the private carrier"
    for call in calls:
        assert len(call.args) == 2, ast.dump(call)
        reason, phase = call.args
        if isinstance(reason, ast.Constant):
            assert reason.value in ENTRY_RECORDABLE_REASONS, reason.value
        else:
            # Only a code already validated by the raising CollectionError may
            # be forwarded, never a free-text value.
            assert isinstance(reason, ast.Attribute), ast.dump(reason)
            assert reason.attr == "reason_code", ast.dump(reason)
        assert isinstance(phase, ast.Constant), ast.dump(phase)
        assert phase.value in v2.FAILURE_PHASES, phase.value


def test_no_f_string_or_concatenation_reaches_a_raise_site():
    for name in ("CollectionError", "_EntryRefusal"):
        for call in _raises(name):
            for node in [*call.args, *(k.value for k in call.keywords)]:
                assert not isinstance(node, ast.JoinedStr), ast.dump(node)
                assert not isinstance(node, ast.BinOp), ast.dump(node)


# --- attempt identity ---------------------------------------------------------


def test_the_v2_attempt_id_cannot_collide_with_the_live_v1_attempt(
    monkeypatch, tmp_path: Path
):
    """The receipt contract id and the policy digest both changed, so the live
    0.1.0 attempt root is structurally unreachable from this collector."""
    result = _run(monkeypatch, tmp_path, _redirect_with(DECOY))
    assert result.attempt_id != LIVE_V1_ATTEMPT
    assert result.attempt_id.startswith("docattempt-")
    assert dp.POLICY_CONTRACT["contract"] == "documentation_acquisition_policy@0.2.0"
    assert v2.RECEIPT_CONTRACT_V2 == "documentation_collection_receipt@0.2.0"


def test_the_policy_declares_the_observation_semantics():
    contract = dp.POLICY_CONTRACT
    assert contract["observed_location_followed"] is False
    assert contract["observed_location_truncated"] is False
    assert contract["observed_location_max_length"] == 2048
    assert contract["failure_phases"] == list(v2.FAILURE_PHASES)


# --- nothing escapes into the repository --------------------------------------


def test_this_module_writes_nothing_under_data(monkeypatch, tmp_path: Path):
    before = sorted(p.as_posix() for p in Path("data").rglob("*") if p.is_file())
    _run(monkeypatch, tmp_path, _redirect_with(DECOY))
    after = sorted(p.as_posix() for p in Path("data").rglob("*") if p.is_file())
    assert before == after
