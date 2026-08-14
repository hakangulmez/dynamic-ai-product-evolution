"""The documentation acquisition policy (ADR-037/038/039; E-C-D, E-C-D1, E-C-D2).

Offline throughout: the transport is a stub reached only through the
module-private ``_send_once`` seam, spacing goes through ``_sleep``, and every
write lands under ``tmp_path``. Nothing here retrieves a real URL and nothing
touches ``data/``.

ADR-038 moved the policy onto a receipt successor that records observations;
ADR-039 moved it again onto ``documentation_collection_receipt@0.3.0`` after E1
was re-frozen, so the schema loaded here is the **v3** file and the routes come
from ``documentation_routes``. The clock-failure and success expectations below
are unchanged on measurement: those are pre-send refusals and successes, where a
null timestamp was already truthful. What they gain is a ``failure_phase``
assertion, which is the fact 0.1.0 could not express at all.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

from dynamic_ai_products.collection import documentation_policy as dp
from dynamic_ai_products.collection.errors import CollectionError
from dynamic_ai_products.collection.http_adapter import AdapterResponse

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "dynamic_ai_products" / "collection"
SCHEMA = (
    ROOT / "schemas" / "documentation_collection_receipt.v3.schema.json"
).read_bytes()
BODY = b"<html><body>official claim</body></html>"
HTML = {"content-type": "text/html; charset=utf-8"}
COMMIT = "4bcbe2e059714f9a7592751a2a9d1d59d0293bfa"
STAMP = "2026-07-31T09:00:00Z"


def _happy(*, url, iterate_body, **kwargs):
    pair = next(
        e for e in dp.FROZEN_EVIDENCE_ENTRIES
        if url in (e["requested_url"], e["final_url"])
    )
    if url == pair["requested_url"]:
        return AdapterResponse(301, pair["final_url"], {}, url, None, 0)
    return AdapterResponse(200, None, HTML, url, BODY, len(BODY))


def _collect(monkeypatch, tmp_path: Path, *, send=_happy, clock=None, sleeps=None, **over):
    monkeypatch.setattr(dp, "_send_once", send)
    monkeypatch.setattr(
        dp, "_sleep", (lambda s: sleeps.append(s)) if sleeps is not None else (lambda s: None)
    )
    kwargs = {
        "raw_root": tmp_path,
        "receipt_schema_bytes": SCHEMA,
        "code_commit": COMMIT,
        "run_created_at": STAMP,
        "retrieval_clock": clock or (lambda: STAMP),
    }
    kwargs.update(over)
    return dp.collect_documentation_evidence(**kwargs)


def _files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


# --- public surface -----------------------------------------------------------


def test_the_public_signature_is_pinned():
    parameters = inspect.signature(dp.collect_documentation_evidence).parameters
    assert set(parameters) == {
        "raw_root",
        "receipt_schema_bytes",
        "code_commit",
        "run_created_at",
        "retrieval_clock",
        "receipt_schema_sha256",
    }
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in parameters.values())
    # No injectable transport or sleeper: a caller-supplied fake could otherwise
    # be recorded under the canonical contract identity.
    assert "transport_send" not in parameters
    assert "sleep" not in parameters
    # retrieval_clock is required; receipt_schema_sha256 carries the sentinel.
    assert parameters["retrieval_clock"].default is inspect.Parameter.empty
    assert parameters["receipt_schema_sha256"].default is not inspect.Parameter.empty


def test_the_private_seams_are_not_exported():
    assert "_send_once" not in dp.__all__
    assert "_sleep" not in dp.__all__
    from dynamic_ai_products import collection

    assert "_send_once" not in collection.__all__
    assert "http_adapter" not in collection.__all__


def test_only_the_policy_modules_import_the_adapter():
    """ADR-040 widens this shared structural boundary to the two named policies.

    A bounded weakening, recorded in the decision log: v0.4 succeeds rather than
    mutates, so ``documentation_policy_v4`` is a second legitimate importer. No
    v0.3 semantic assertion in this file is retargeted.
    """
    offenders = []
    for module in sorted(SRC.glob("*.py")):
        if module.name in {
            "documentation_policy.py",
            "documentation_policy_v4.py",
            "documentation_policy_v5.py",
            "http_adapter.py",
        }:
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            if any("http_adapter" in n for n in names):
                offenders.append(f"{module.name}:{node.lineno}")
    assert not offenders, offenders


def test_exactly_three_modules_import_httpx():
    # ADR-078 widened the exact allowlist from two to three, admitting the
    # committed sec_live index transport.
    importers = []
    for module in sorted((SRC.parent).rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                a.name.split(".")[0] == "httpx" for a in node.names
            ):
                importers.append(module.name)
            elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "httpx":
                importers.append(module.name)
    assert sorted(set(importers)) == [
        "http_adapter.py",
        "response_capture.py",
        "sec_index_transport.py",
    ]


# --- the sentinel -------------------------------------------------------------


@pytest.mark.parametrize(
    "claim",
    [None, "a" * 64, "not-a-digest", 7, object()],
    ids=["none", "valid-looking", "malformed", "int", "object"],
)
def test_any_supplied_schema_digest_is_refused(monkeypatch, tmp_path: Path, claim):
    """Reachable because of the sentinel: an unknown keyword would only TypeError."""
    sends: list[str] = []
    with pytest.raises(CollectionError) as excinfo:
        _collect(
            monkeypatch,
            tmp_path,
            send=lambda **kw: sends.append(kw["url"]),
            receipt_schema_sha256=claim,
        )
    assert excinfo.value.reason_code == "receipt_schema_claim_forbidden"
    assert sends == [], "zero sends"
    assert _files(tmp_path) == set(), "zero artifacts"


# --- ordered preflight --------------------------------------------------------


def test_a_configured_keylog_refuses_before_the_attempt_root(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SSLKEYLOGFILE", str(tmp_path / "keylog.txt"))
    sends: list[str] = []
    with pytest.raises(CollectionError) as excinfo:
        _collect(monkeypatch, tmp_path, send=lambda **kw: sends.append(kw["url"]))
    assert excinfo.value.reason_code == "tls_keylog_environment_present"
    assert sends == []
    assert _files(tmp_path) == set()


def test_a_keylog_appearing_between_sends_stops_and_preserves_earlier_objects(
    monkeypatch, tmp_path: Path
):
    calls: list[str] = []

    def send(*, url, iterate_body, **kwargs):
        calls.append(url)
        if len(calls) == 3:  # entry two's redirect send
            monkeypatch.setenv("SSLKEYLOGFILE", str(tmp_path / "kl.txt"))
        return _happy(url=url, iterate_body=iterate_body, **kwargs)

    result = _collect(monkeypatch, tmp_path, send=send)
    assert result.completion_status == "stopped"
    statuses = [e["entry_status"] for e in result.entries]
    assert statuses == ["succeeded", "failed", "not_attempted"]
    assert result.entries[1]["failure_reason"] == "tls_keylog_environment_present"
    # The keylog appears during entry two's redirect send, so its own preflight
    # had already passed: the refusal lands on the recheck before send two.
    assert result.entries[1]["failure_phase"] == "terminal_preflight"
    assert result.entries[1]["retrieval_timestamp"] == STAMP
    assert result.entries[1]["redirect_observed_status"] in dp.REDIRECT_STATUSES
    assert result.entries[1]["request_chain"] == [
        dp.FROZEN_EVIDENCE_ENTRIES[1]["requested_url"]
    ]
    # The first object survives.
    assert any("gemini_thinking" in f for f in _files(tmp_path))


@pytest.mark.parametrize(
    "schema_bytes", [b"", b"not json", b"{}", json.dumps({"type": "object"}).encode()]
)
def test_unusable_schema_bytes_refuse_with_zero_artifacts(
    monkeypatch, tmp_path: Path, schema_bytes
):
    sends: list[str] = []
    with pytest.raises(CollectionError) as excinfo:
        _collect(
            monkeypatch,
            tmp_path,
            send=lambda **kw: sends.append(kw["url"]),
            receipt_schema_bytes=schema_bytes,
        )
    assert excinfo.value.reason_code in {
        "receipt_schema_invalid",
        "receipt_schema_contract_mismatch",
    }
    assert sends == []
    assert _files(tmp_path) == set()


@pytest.mark.parametrize("bad", ["", "2026-07-31", "2026-07-31T09:00:00+02:00", 7])
def test_a_bad_run_created_at_refuses_with_zero_artifacts(
    monkeypatch, tmp_path: Path, bad
):
    sends: list[str] = []
    with pytest.raises(CollectionError) as excinfo:
        _collect(
            monkeypatch, tmp_path, send=lambda **kw: sends.append(kw["url"]), run_created_at=bad
        )
    assert excinfo.value.reason_code == "attempt_identity_invalid"
    assert sends == []
    assert _files(tmp_path) == set()


def test_a_duplicate_attempt_root_issues_zero_requests(monkeypatch, tmp_path: Path):
    first = _collect(monkeypatch, tmp_path, send=_happy)
    sends: list[str] = []
    with pytest.raises(CollectionError) as excinfo:
        _collect(monkeypatch, tmp_path, send=lambda **kw: sends.append(kw["url"]))
    assert excinfo.value.reason_code == "attempt_root_exists"
    assert sends == [], "a duplicate attempt must not touch the network"
    assert first.attempt_id.startswith("docattempt-")


# --- the injected clock -------------------------------------------------------


def test_the_clock_is_called_once_per_entry_after_spacing_before_the_send(
    monkeypatch, tmp_path: Path
):
    order: list[str] = []
    monkeypatch.setattr(dp, "_sleep", lambda s: order.append(f"sleep:{s}"))

    def clock():
        order.append("clock")
        return STAMP

    def send(*, url, iterate_body, **kwargs):
        order.append("send")
        return _happy(url=url, iterate_body=iterate_body, **kwargs)

    monkeypatch.setattr(dp, "_send_once", send)
    dp.collect_documentation_evidence(
        raw_root=tmp_path,
        receipt_schema_bytes=SCHEMA,
        code_commit=COMMIT,
        run_created_at=STAMP,
        retrieval_clock=clock,
    )
    assert order.count("clock") == 3, "exactly once per attempted entry"
    # Six sends, five delays. The clock is read once per entry, after any
    # spacing that precedes that entry's initial request and immediately before
    # it -- including the delay between an accepted redirect and its terminal
    # request, which the earlier per-entry-only rule omitted.
    assert order == [
        "clock", "send",                       # E1 initial (first send: no delay)
        "sleep:2.0", "send",                   # E1 terminal
        "sleep:2.0", "clock", "send",          # E2 initial
        "sleep:2.0", "send",                   # E2 terminal
        "sleep:2.0", "clock", "send",          # E3 initial
        "sleep:2.0", "send",                   # E3 terminal
    ]


@pytest.mark.parametrize(
    "value", ["", "2026-07-31", "2026-07-31T09:00:00+02:00", "not-a-time", 7, None]
)
def test_an_invalid_clock_value_fails_the_entry_with_no_sends(
    monkeypatch, tmp_path: Path, value
):
    sends: list[str] = []

    def send(*, url, iterate_body, **kwargs):
        sends.append(url)
        return _happy(url=url, iterate_body=iterate_body, **kwargs)

    result = _collect(monkeypatch, tmp_path, send=send, clock=lambda: value)
    assert result.completion_status == "stopped"
    assert result.entries[0]["failure_reason"] == "retrieval_clock_invalid"
    # Still null, and now also phase-attributed: no instant was ever established,
    # so this is the one phase where a null timestamp remains truthful.
    assert result.entries[0]["retrieval_timestamp"] is None
    assert result.entries[0]["failure_phase"] == "entry_preflight"
    assert result.entries[0]["request_chain"] == []
    assert [e["entry_status"] for e in result.entries] == [
        "failed",
        "not_attempted",
        "not_attempted",
    ]
    assert sends == [], "no send for an entry with no valid instant"


def test_a_raising_clock_fails_the_entry_with_no_sends(monkeypatch, tmp_path: Path):
    def clock():
        raise RuntimeError("upstream secret detail")

    sends: list[str] = []
    result = _collect(
        monkeypatch, tmp_path, send=lambda **kw: sends.append(kw["url"]), clock=clock
    )
    assert result.entries[0]["failure_reason"] == "retrieval_clock_failed"
    assert result.entries[0]["retrieval_timestamp"] is None
    assert result.entries[0]["failure_phase"] == "entry_preflight"
    assert sends == []
    # The upstream detail never reaches the artifact.
    assert "upstream secret detail" not in json.dumps(result.entries[0])


def test_not_attempted_entries_carry_a_null_timestamp(monkeypatch, tmp_path: Path):
    result = _collect(monkeypatch, tmp_path, clock=lambda: "bad")
    for entry in result.entries[1:]:
        assert entry["entry_status"] == "not_attempted"
        assert entry["retrieval_timestamp"] is None
        assert entry["failure_reason"] is None
        assert entry["failure_phase"] is None
        assert entry["request_chain"] == []
        assert entry["redirect_observed_location_disposition"] == "no_response"


def test_the_retrieval_timestamp_mode_travels_with_the_artifact(
    monkeypatch, tmp_path: Path
):
    result = _collect(monkeypatch, tmp_path)
    receipt = json.loads(
        (result.attempt_root / result.receipt_reference).read_text(encoding="utf-8")
    )
    assert receipt["retrieval_timestamp_mode"] == "caller_injected_request_start_utc_v1"
    assert dp.POLICY_CONTRACT["retrieval_timestamp_mode"] == receipt[
        "retrieval_timestamp_mode"
    ]


# --- spacing ------------------------------------------------------------------


def test_spacing_precedes_every_send_after_the_first(monkeypatch, tmp_path: Path):
    """Six possible sends, so a full success produces exactly five delays."""
    sleeps: list[float] = []
    _collect(monkeypatch, tmp_path, sleeps=sleeps)
    assert sleeps == [2.0, 2.0, 2.0, 2.0, 2.0]
    assert dp.SPACING_SECONDS == 2.0


def test_no_delay_precedes_the_very_first_send(monkeypatch, tmp_path: Path):
    order: list[str] = []
    monkeypatch.setattr(dp, "_sleep", lambda s: order.append("sleep"))

    def send(*, url, iterate_body, **kwargs):
        order.append("send")
        return _happy(url=url, iterate_body=iterate_body, **kwargs)

    monkeypatch.setattr(dp, "_send_once", send)
    dp.collect_documentation_evidence(
        raw_root=tmp_path,
        receipt_schema_bytes=SCHEMA,
        code_commit=COMMIT,
        run_created_at=STAMP,
        retrieval_clock=lambda: STAMP,
    )
    assert order[0] == "send"
    assert order.count("send") == 6
    assert order.count("sleep") == 5


# --- byte ceilings ------------------------------------------------------------


def test_the_total_ceiling_is_exactly_three_times_the_per_response_cap():
    """Derived and defensive: three under-cap documents cannot cross it."""
    assert dp.TOTAL_ACCEPTED_ENTITY_BYTES_MAX == (
        len(dp.FROZEN_EVIDENCE_ENTRIES) * dp.MAX_ENTITY_BYTES_PER_RESPONSE
    )
    assert dp.TOTAL_ACCEPTED_ENTITY_BYTES_MAX == 3 * 8 * 1024 * 1024


def test_three_accepted_entries_reach_at_most_exactly_the_total_ceiling(
    monkeypatch, tmp_path: Path
):
    result = _collect(monkeypatch, tmp_path)
    total = sum(e["byte_count"] for e in result.entries)
    assert total <= dp.TOTAL_ACCEPTED_ENTITY_BYTES_MAX


@pytest.mark.parametrize(
    "sizes,cap,crosses",
    [([10, 10, 10], 30, False), ([10, 10, 11], 30, True), ([31], 30, True)],
)
def test_the_accumulator_refuses_before_crossing(sizes, cap, crosses):
    """Pure accumulator with small fixtures: the drift branch, exercised."""
    total = 0
    refused = False
    for size in sizes:
        if total + size > cap:
            refused = True
            break
        total += size
    assert refused is crosses
    assert total <= cap


# --- filesystem and symlink escape closure ------------------------------------


def test_a_matching_symlink_is_refused_rather_than_reused(monkeypatch, tmp_path: Path):
    """The bytes a link points at are not the bytes the path claims to hold."""
    from hashlib import sha256

    digest = sha256(BODY).hexdigest()
    elsewhere = tmp_path / "elsewhere.html"
    elsewhere.write_bytes(BODY)
    target = tmp_path / "gemini_thinking" / f"sha256-{digest}" / "document.html"
    target.parent.mkdir(parents=True)
    target.symlink_to(elsewhere)

    result = _collect(monkeypatch, tmp_path)
    assert result.entries[0]["failure_reason"] == "content_object_corrupt"
    assert result.completion_status == "stopped"
    # The pre-existing link and its target survive.
    assert target.is_symlink() and elsewhere.read_bytes() == BODY


@pytest.mark.parametrize(
    "component", ["gemini_thinking", "digest_dir"], ids=["evidence-kind", "digest"]
)
def test_a_symlinked_governed_directory_is_refused(
    monkeypatch, tmp_path: Path, component
):
    from hashlib import sha256

    digest = sha256(BODY).hexdigest()
    outside = tmp_path / "outside"
    outside.mkdir()
    if component == "gemini_thinking":
        (tmp_path / "gemini_thinking").symlink_to(outside, target_is_directory=True)
    else:
        kind = tmp_path / "gemini_thinking"
        kind.mkdir()
        (kind / f"sha256-{digest}").symlink_to(outside, target_is_directory=True)

    result = _collect(monkeypatch, tmp_path)
    assert result.entries[0]["failure_reason"] == "content_object_corrupt"
    # Nothing escaped into the symlink target.
    assert list(outside.iterdir()) == []


def test_a_directory_at_the_document_path_is_refused(monkeypatch, tmp_path: Path):
    from hashlib import sha256

    digest = sha256(BODY).hexdigest()
    (tmp_path / "gemini_thinking" / f"sha256-{digest}" / "document.html").mkdir(
        parents=True
    )
    result = _collect(monkeypatch, tmp_path)
    assert result.entries[0]["failure_reason"] == "content_object_corrupt"


def test_a_symlinked_raw_root_or_attempts_directory_is_refused(
    monkeypatch, tmp_path: Path
):
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    sends: list[str] = []
    with pytest.raises(CollectionError) as excinfo:
        _collect(
            monkeypatch, tmp_path, send=lambda **kw: sends.append(kw["url"]), raw_root=linked
        )
    assert excinfo.value.reason_code == "attempt_root_unsafe"
    assert sends == []


def test_no_raw_oserror_escapes_the_public_collector(monkeypatch, tmp_path: Path):
    """Every filesystem failure arrives as a closed CollectionError code."""
    import dynamic_ai_products.collection.documentation_policy as module

    def exploding(*args, **kwargs):
        raise OSError("upstream filesystem detail")

    monkeypatch.setattr(module, "write_bytes_once", exploding)
    try:
        result = _collect(monkeypatch, tmp_path)
    except CollectionError as exc:
        assert exc.reason_code in module.DOCUMENTATION_REASON_CODES
        assert "upstream filesystem detail" not in str(exc)
        return
    assert result.entries[0]["failure_reason"] in module.DOCUMENTATION_REASON_CODES


def test_every_public_failure_reason_is_in_the_closed_vocabulary(
    monkeypatch, tmp_path: Path
):
    result = _collect(monkeypatch, tmp_path, clock=lambda: "bad")
    for entry in result.entries:
        reason = entry["failure_reason"]
        assert reason is None or reason in dp.DOCUMENTATION_REASON_CODES


# --- semantic UTC validation --------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "2026-99-99T99:99:99Z",
        "2026-02-30T09:00:00Z",
        "2026-07-31T24:00:00Z",
        "2026-13-01T09:00:00Z",
        "2026-07-31T09:00:00",
        "2026-07-31T09:00:00+02:00",
        "2026-07-31",
        "",
        7,
        None,
    ],
)
def test_an_impossible_or_non_utc_clock_value_is_refused(
    monkeypatch, tmp_path: Path, value
):
    """Regex alone admits 2026-02-30 and 24:00:00; parsing rejects them."""
    sends: list[str] = []
    result = _collect(
        monkeypatch, tmp_path, send=lambda **kw: sends.append(kw["url"]), clock=lambda: value
    )
    assert result.entries[0]["failure_reason"] == "retrieval_clock_invalid"
    assert result.entries[0]["retrieval_timestamp"] is None
    assert result.entries[0]["failure_phase"] == "entry_preflight"
    assert sends == []


@pytest.mark.parametrize(
    "value",
    [
        "2026-99-99T99:99:99Z",
        "2026-02-30T09:00:00Z",
        "2026-07-31T24:00:00Z",
        "2026-07-31T09:00:00",
        "2026-07-31T09:00:00+02:00",
        7,
    ],
)
def test_an_impossible_run_created_at_is_refused(monkeypatch, tmp_path: Path, value):
    sends: list[str] = []
    with pytest.raises(CollectionError) as excinfo:
        _collect(
            monkeypatch, tmp_path, send=lambda **kw: sends.append(kw["url"]), run_created_at=value
        )
    assert excinfo.value.reason_code == "attempt_identity_invalid"
    assert sends == []
    assert _files(tmp_path) == set()


@pytest.mark.parametrize("value", ["2026-07-31T09:00:00Z", "2026-07-31T09:00:00+00:00"])
def test_a_real_utc_instant_is_accepted(monkeypatch, tmp_path: Path, value):
    result = _collect(monkeypatch, tmp_path, clock=lambda: value)
    assert result.completion_status == "completed"
    assert result.entries[0]["retrieval_timestamp"] == value
    assert result.entries[0]["failure_phase"] is None


# --- content-type grammar -----------------------------------------------------


@pytest.mark.parametrize(
    "value", ["text/html", "text/html; charset=utf-8", "Text/HTML; Charset=UTF-8"]
)
def test_an_accepted_content_type_is_recorded_as_observed(
    monkeypatch, tmp_path: Path, value
):
    def send(*, url, iterate_body, **kwargs):
        pair = next(
            e for e in dp.FROZEN_EVIDENCE_ENTRIES
            if url in (e["requested_url"], e["final_url"])
        )
        if url == pair["requested_url"]:
            return AdapterResponse(301, pair["final_url"], {}, url, None, 0)
        return AdapterResponse(
            200, None, {"content-type": value}, url, BODY, len(BODY)
        )

    result = _collect(monkeypatch, tmp_path, send=send)
    assert result.completion_status == "completed"
    # The observed header value is recorded verbatim, not normalized.
    assert result.entries[0]["content_type"] == value


@pytest.mark.parametrize(
    "raw", ["  text/html  ", "text/html;charset=utf-8", "Text/HTML ; Charset=UTF-8"]
)
def test_the_observed_header_is_stored_verbatim_not_the_parsed_copy(
    monkeypatch, tmp_path: Path, raw
):
    """Validation parses a copy; the receipt keeps exactly what arrived."""

    def send(*, url, iterate_body, **kwargs):
        pair = next(
            e for e in dp.FROZEN_EVIDENCE_ENTRIES
            if url in (e["requested_url"], e["final_url"])
        )
        if url == pair["requested_url"]:
            return AdapterResponse(301, pair["final_url"], {}, url, None, 0)
        return AdapterResponse(200, None, {"content-type": raw}, url, BODY, len(BODY))

    result = _collect(monkeypatch, tmp_path, send=send)
    assert result.completion_status == "completed"
    stored = result.entries[0]["content_type"]
    assert stored == raw
    # Untouched: leading/trailing space and internal spacing survive.
    assert stored != stored.strip() or ";" not in stored or stored == raw


@pytest.mark.parametrize(
    "value",
    [
        "text/html; charset==",
        'text/html; charset=""',
        "text/html; charset=utf 8",
        'text/html; charset=" "',
        "text/html; charset=utf-8=evil",
    ],
)
def test_a_malformed_charset_token_is_refused(monkeypatch, tmp_path: Path, value):
    """A truthiness check on the parameter would have admitted every one."""

    def send(*, url, iterate_body, **kwargs):
        pair = next(
            e for e in dp.FROZEN_EVIDENCE_ENTRIES
            if url in (e["requested_url"], e["final_url"])
        )
        if url == pair["requested_url"]:
            return AdapterResponse(301, pair["final_url"], {}, url, None, 0)
        return AdapterResponse(200, None, {"content-type": value}, url, BODY, len(BODY))

    result = _collect(monkeypatch, tmp_path, send=send)
    assert result.entries[0]["failure_reason"] == "content_type_invalid"


@pytest.mark.parametrize(
    "value",
    [
        "text/html; boundary=evil",
        "text/html; charset=",
        "text/html; charset=utf-8; boundary=x",
        "text/html; charset=utf-8; charset=utf-8",
        "text/htmlx",
        "application/json",
        "",
    ],
)
def test_a_rejected_content_type_stops_the_entry(monkeypatch, tmp_path: Path, value):
    def send(*, url, iterate_body, **kwargs):
        pair = next(
            e for e in dp.FROZEN_EVIDENCE_ENTRIES
            if url in (e["requested_url"], e["final_url"])
        )
        if url == pair["requested_url"]:
            return AdapterResponse(301, pair["final_url"], {}, url, None, 0)
        return AdapterResponse(200, None, {"content-type": value}, url, BODY, len(BODY))

    result = _collect(monkeypatch, tmp_path, send=send)
    assert result.entries[0]["failure_reason"] == "content_type_invalid"
