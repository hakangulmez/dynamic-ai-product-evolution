"""Stage 00 minimal one-firm Pilot Universe Packet: offline tests.

Every test uses an injected transport and temporary paths only. No network
access occurs, no ``data/raw`` file is created, and no tracked registry
packet is written. All locked raw/receipt/marker/anchor refusal paths are
covered.
"""

import hashlib
import json
from pathlib import Path

import pytest

from dynamic_ai_products.universe import pilot_packet as pp
from dynamic_ai_products.universe.pilot_packet import (
    AnchorSelection,
    ByteSliceSelection,
    PilotPacketError,
    TransportResponse,
    build_pilot_universe_packet,
    collect_pilot_sources,
    load_collection_receipt,
    materiality_stop_report,
)

URLS = [url for _, url, _ in pp.FROZEN_RETRIEVALS]
FILENAMES = {key: filename for key, _, filename in pp.FROZEN_RETRIEVALS}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- Synthetic persisted-evidence material ----------------------------------

SUBMISSIONS_PAYLOAD = {
    "cik": "0001404655",
    "name": "HUBSPOT INC",
    "tickers": ["HUBS"],
    "exchanges": ["NYSE"],
    "sic": "7372",
    "sicDescription": "Services-Prepackaged Software",
    "stateOfIncorporation": "NY",
    "fiscalYearEnd": "1231",
    "filings": {
        "recent": {
            "form": ["8-K", "10-K", "10-Q"],
            "accessionNumber": [
                "0000950170-25-018839",
                "0000950170-25-018873",
                "0000950170-24-122326",
            ],
            "filingDate": ["2025-02-12", "2025-02-12", "2024-11-06"],
            "reportDate": ["2025-02-12", "2024-12-31", "2024-09-30"],
        }
    },
}
SUBMISSIONS_BYTES = json.dumps(SUBMISSIONS_PAYLOAD).encode()
INDEX_BYTES = json.dumps(
    {"directory": {"item": [{"name": "hubs-20241231.htm"},
                            {"name": "0000950170-25-018873.txt"}]}}
).encode()

# A synthetic primary document with the locked structural anchors, an
# evidence sentence between them, HTML markup around them, a multibyte
# character, and an entity-encoded region (for normalization/entity-decode
# refusal tests).
DOC = (
    b"<html><body><p>preamble \xc3\xa9</p>"
    b'<div id="item_i_business">'
    b"<b>Item 1. Business</b>"
    b"<p>HubSpot provides a unified customer platform delivered as software, "
    b"including marketing, sales &amp; service products.</p>"
    b"</div>"
    b'<div id="item_1a_risk_factors">'
    b"<b>Item 1A. Risk Factors</b>"
    b"<p>risks</p></div></body></html>"
)
EVIDENCE_TEXT = (
    "HubSpot provides a unified customer platform delivered as software, "
    "including marketing, sales "
)


def _find(needle: bytes) -> tuple[int, int]:
    start = DOC.index(needle)
    return start, start + len(needle)


START_ANCHOR_OFFSETS = _find(pp.START_ANCHOR_BYTES)
END_ANCHOR_OFFSETS = _find(pp.END_ANCHOR_BYTES)
EVIDENCE_OFFSETS = _find(EVIDENCE_TEXT.encode())


def start_anchor(**over):
    fields = {
        "start_offset": START_ANCHOR_OFFSETS[0],
        "end_offset": START_ANCHOR_OFFSETS[1],
        "sha256": sha(pp.START_ANCHOR_BYTES),
    }
    fields.update(over)
    return AnchorSelection(**fields)


def end_anchor(**over):
    fields = {
        "start_offset": END_ANCHOR_OFFSETS[0],
        "end_offset": END_ANCHOR_OFFSETS[1],
        "sha256": sha(pp.END_ANCHOR_BYTES),
    }
    fields.update(over)
    return AnchorSelection(**fields)


def evidence(**over):
    fields = {
        "start_offset": EVIDENCE_OFFSETS[0], "end_offset": EVIDENCE_OFFSETS[1],
        "sha256": sha(DOC[EVIDENCE_OFFSETS[0]:EVIDENCE_OFFSETS[1]]),
        "text": EVIDENCE_TEXT,
    }
    fields.update(over)
    return ByteSliceSelection(**fields)


# --- Injected transport ------------------------------------------------------


class FakeTransport:
    """Scripted transport recording every request; no network ever."""

    def __init__(self, responses=None):
        default = {
            URLS[0]: TransportResponse(200, URLS[0], SUBMISSIONS_BYTES),
            URLS[1]: TransportResponse(200, URLS[1], INDEX_BYTES),
            URLS[2]: TransportResponse(200, URLS[2], DOC),
        }
        if responses:
            default.update(responses)
        self.responses = default
        self.requests: list[tuple[str, str]] = []

    def __call__(self, url, headers):
        self.requests.append((url, headers.get("User-Agent", "")))
        response = self.responses[url]
        if isinstance(response, list):
            return response.pop(0)
        return response


class FakeSleeper:
    def __init__(self):
        self.delays: list[float] = []

    def __call__(self, seconds):
        self.delays.append(seconds)


def collect(tmp_path, transport=None, sleeper=None):
    transport = transport if transport is not None else FakeTransport()
    sleeper = sleeper if sleeper is not None else FakeSleeper()
    outcome = collect_pilot_sources(
        raw_root=tmp_path, transport=transport, sleeper=sleeper,
        clock=lambda: "2026-07-27T12:00:00+00:00")
    return outcome, transport, sleeper


def build(tmp_path, **over):
    kwargs = dict(
        raw_root=tmp_path, packet_path=tmp_path / "registry" / "packet.json",
        start_anchor=start_anchor(), end_anchor=end_anchor(), evidence=evidence(),
        selection_note="Item 1 describes the customer platform as software.")
    kwargs.update(over)
    return build_pilot_universe_packet(**kwargs)


# --- Collection: happy path, spacing, UA, receipt round-trip -----------------


def test_collect_happy_path_writes_three_files_and_receipt(tmp_path):
    outcome, transport, sleeper = collect(tmp_path)
    assert [u for u, _ in transport.requests] == URLS  # frozen order, exactly 3
    assert all(agent == pp.USER_AGENT for _, agent in transport.requests)
    assert sleeper.delays == [1.0, 1.0]  # spacing between the three requests
    raw = outcome.raw_directory
    assert raw == tmp_path / "sec" / "CIK0001404655" / "0000950170-25-018873"
    assert (raw / "submissions.json").read_bytes() == SUBMISSIONS_BYTES
    assert (raw / "filing-index.json").read_bytes() == INDEX_BYTES
    assert (raw / "hubs-20241231.htm").read_bytes() == DOC
    assert outcome.file_sha256 == {
        "submissions": sha(SUBMISSIONS_BYTES),
        "filing_index": sha(INDEX_BYTES),
        "primary_document": sha(DOC),
    }
    receipt_bytes = outcome.receipt_path.read_bytes()
    assert sha(receipt_bytes) == outcome.receipt_sha256
    receipt, loaded_sha = load_collection_receipt(tmp_path)
    assert loaded_sha == outcome.receipt_sha256
    assert receipt["completion_status"] == "complete"
    assert receipt["identity"]["accession"] == pp.PILOT_ACCESSION
    for entry, url in zip(receipt["retrievals"], URLS):
        assert entry["requested_url"] == entry["final_url"] == url
        assert entry["http_status"] == 200
        assert entry["retry_count"] == 0
        assert entry["retrieval_timestamp"] == "2026-07-27T12:00:00+00:00"
        assert "failure_reason" not in entry


def test_collect_refuses_existing_raw_destination_without_requests(tmp_path):
    raw = tmp_path / "sec" / "CIK0001404655" / "0000950170-25-018873"
    raw.mkdir(parents=True)
    (raw / "submissions.json").write_bytes(b"already here")
    transport = FakeTransport()
    with pytest.raises(PilotPacketError) as excinfo:
        collect(tmp_path, transport=transport)
    assert excinfo.value.reason_code == "destination_exists"
    assert transport.requests == []  # never re-requests an existing destination
    assert (raw / "submissions.json").read_bytes() == b"already here"


def test_collect_receipt_is_write_once(tmp_path):
    raw = tmp_path / "sec" / "CIK0001404655" / "0000950170-25-018873"
    raw.mkdir(parents=True)
    (raw / "collection_receipt.json").write_bytes(b"{}")
    transport = FakeTransport()
    with pytest.raises(PilotPacketError) as excinfo:
        collect(tmp_path, transport=transport)
    assert excinfo.value.reason_code == "receipt_exists"
    assert transport.requests == []
    assert (raw / "collection_receipt.json").read_bytes() == b"{}"


def test_collect_redirect_is_a_fail_closed_stop(tmp_path):
    transport = FakeTransport({URLS[1]: TransportResponse(301, URLS[1], b"")})
    with pytest.raises(PilotPacketError) as excinfo:
        collect(tmp_path, transport=transport)
    assert excinfo.value.reason_code == "retrieval_stop"
    assert excinfo.value.stop_reason == "redirect_response"
    # The redirect target is never followed and URL 3 is never requested.
    assert [u for u, _ in transport.requests] == [URLS[0], URLS[1]]
    receipt, _ = load_collection_receipt(tmp_path)
    assert receipt["completion_status"] == "stopped"
    assert receipt["stop_reason"] == "redirect_response"
    reasons = [e.get("failure_reason") for e in receipt["retrievals"]]
    assert reasons == [None, "redirect_response", "not_attempted"]


def test_collect_final_url_mismatch_is_a_fail_closed_stop(tmp_path):
    other = "https://www.sec.gov/other/location.json"
    transport = FakeTransport(
        {URLS[1]: TransportResponse(200, other, INDEX_BYTES)})
    with pytest.raises(PilotPacketError) as excinfo:
        collect(tmp_path, transport=transport)
    assert excinfo.value.stop_reason == "final_url_mismatch"
    assert [u for u, _ in transport.requests] == [URLS[0], URLS[1]]
    raw = tmp_path / "sec" / "CIK0001404655" / "0000950170-25-018873"
    assert not (raw / "filing-index.json").exists()
    assert (raw / "submissions.json").exists()  # earlier success preserved


def test_collect_bounded_retry_then_success_and_then_stop(tmp_path):
    transport = FakeTransport({URLS[0]: [
        TransportResponse(500, URLS[0], b""),
        TransportResponse(200, URLS[0], SUBMISSIONS_BYTES),
    ]})
    outcome, transport, sleeper = collect(tmp_path, transport=transport)
    receipt, _ = load_collection_receipt(tmp_path)
    assert receipt["retrievals"][0]["retry_count"] == 1
    assert receipt["completion_status"] == "complete"

    transport2 = FakeTransport({URLS[0]: [
        TransportResponse(503, URLS[0], b""),
        TransportResponse(503, URLS[0], b""),
    ]})
    with pytest.raises(PilotPacketError) as excinfo:
        collect(tmp_path / "second", transport=transport2)
    assert excinfo.value.stop_reason == "http_error"
    assert [u for u, _ in transport2.requests] == [URLS[0], URLS[0]]


def test_collect_transport_error_stop_records_receipt(tmp_path):
    class Boom:
        def __init__(self):
            self.requests = []

        def __call__(self, url, headers):
            self.requests.append((url, headers))
            raise ConnectionError("synthetic")

    transport = Boom()
    with pytest.raises(PilotPacketError) as excinfo:
        collect_pilot_sources(
            raw_root=tmp_path, transport=transport, sleeper=FakeSleeper(),
            clock=lambda: "2026-07-27T12:00:00+00:00")
    assert excinfo.value.stop_reason == "transport_error"
    receipt, _ = load_collection_receipt(tmp_path)
    assert receipt["retrievals"][0]["failure_reason"] == "transport_error"
    assert receipt["retrievals"][1]["failure_reason"] == "not_attempted"


def test_frozen_allowlist_is_exactly_the_locked_three():
    assert URLS == [
        "https://data.sec.gov/submissions/CIK0001404655.json",
        "https://www.sec.gov/Archives/edgar/data/1404655/000095017025018873/"
        "index.json",
        "https://www.sec.gov/Archives/edgar/data/1404655/000095017025018873/"
        "hubs-20241231.htm",
    ]
    assert pp._ALLOWED_URLS == frozenset(URLS)


# --- Receipt loading refusals ------------------------------------------------


def test_receipt_missing_refused(tmp_path):
    with pytest.raises(PilotPacketError) as excinfo:
        load_collection_receipt(tmp_path)
    assert excinfo.value.reason_code == "receipt_missing"


def _receipt_path(tmp_path) -> Path:
    return (tmp_path / "sec" / "CIK0001404655" / "0000950170-25-018873"
            / "collection_receipt.json")


def test_receipt_malformed_refused(tmp_path):
    collect(tmp_path)
    _receipt_path(tmp_path).write_bytes(b"{not json")
    with pytest.raises(PilotPacketError) as excinfo:
        load_collection_receipt(tmp_path)
    assert excinfo.value.reason_code == "receipt_invalid"


def test_receipt_wrong_url_set_refused(tmp_path):
    collect(tmp_path)
    receipt, _ = load_collection_receipt(tmp_path)
    receipt["retrievals"] = receipt["retrievals"][:2]
    _receipt_path(tmp_path).write_bytes(json.dumps(receipt).encode())
    with pytest.raises(PilotPacketError) as excinfo:
        load_collection_receipt(tmp_path)
    assert excinfo.value.reason_code == "receipt_invalid"


# --- Packet build: happy path and receipt-anchored refusals ------------------


def test_build_happy_path_round_trip_and_write_once(tmp_path):
    outcome, _, _ = collect(tmp_path)
    packet = build(tmp_path)
    assert packet["company_id"] == "CIK0001404655"  # derived, not asserted
    assert packet["legal_name"] == "HUBSPOT INC"
    assert packet["collection_receipt_sha256"] == outcome.receipt_sha256
    assert packet["filing"]["accession"] == pp.PILOT_ACCESSION
    assert packet["filing"]["primary_document_sha256"] == sha(DOC)
    assert packet["observation_cutoff_date"] == "2025-02-12"
    assert packet["fiscal_year_end_date"] == "2024-12-31"
    assert packet["materiality_evidence"]["evidence"]["text"] == EVIDENCE_TEXT
    assert packet["materiality_evidence"]["evidence_text_encoding"] == (
        "utf-8-strict-text-slice-v1")
    recorded_start = packet["materiality_evidence"]["start_anchor"]
    assert recorded_start["anchor_bytes"] == 'id="item_i_business"'
    assert recorded_start["start_offset"] == START_ANCHOR_OFFSETS[0]
    assert recorded_start["end_offset"] == START_ANCHOR_OFFSETS[1]
    assert recorded_start["sha256"] == sha(pp.START_ANCHOR_BYTES)
    recorded_end = packet["materiality_evidence"]["end_anchor"]
    assert recorded_end["anchor_bytes"] == 'id="item_1a_risk_factors"'
    assert recorded_end["start_offset"] == END_ANCHOR_OFFSETS[0]
    assert recorded_end["end_offset"] == END_ANCHOR_OFFSETS[1]
    assert recorded_end["sha256"] == sha(pp.END_ANCHOR_BYTES)
    assert packet["retrieval_provenance"][0]["sha256"] == sha(SUBMISSIONS_BYTES)
    assert packet["eligibility"]["verdict"] == "admitted_pilot_only_route_a"
    written = (tmp_path / "registry" / "packet.json").read_bytes()
    assert json.loads(written) == packet
    with pytest.raises(PilotPacketError) as excinfo:
        build(tmp_path)
    assert excinfo.value.reason_code == "packet_exists"


def test_build_refuses_missing_receipt(tmp_path):
    with pytest.raises(PilotPacketError) as excinfo:
        build(tmp_path)
    assert excinfo.value.reason_code == "receipt_missing"


def test_build_refuses_stopped_receipt(tmp_path):
    transport = FakeTransport({URLS[2]: TransportResponse(301, URLS[2], b"")})
    with pytest.raises(PilotPacketError):
        collect(tmp_path, transport=transport)
    with pytest.raises(PilotPacketError) as excinfo:
        build(tmp_path)
    assert excinfo.value.reason_code == "receipt_incomplete"


def test_build_refuses_tampered_receipt_hash(tmp_path):
    collect(tmp_path)
    receipt, _ = load_collection_receipt(tmp_path)
    receipt["retrievals"][2]["sha256"] = "0" * 64
    _receipt_path(tmp_path).write_bytes(json.dumps(receipt).encode())
    with pytest.raises(PilotPacketError) as excinfo:
        build(tmp_path)
    assert excinfo.value.reason_code == "receipt_hash_mismatch"


def test_build_refuses_tampered_raw_bytes(tmp_path):
    collect(tmp_path)
    raw = tmp_path / "sec" / "CIK0001404655" / "0000950170-25-018873"
    (raw / "hubs-20241231.htm").write_bytes(DOC + b"tamper")
    with pytest.raises(PilotPacketError) as excinfo:
        build(tmp_path)
    assert excinfo.value.reason_code == "receipt_hash_mismatch"


def _collect_with_submissions(tmp_path, payload):
    data = json.dumps(payload).encode()
    transport = FakeTransport({URLS[0]: TransportResponse(200, URLS[0], data)})
    collect(tmp_path, transport=transport)


def test_build_refuses_bad_cik(tmp_path):
    _collect_with_submissions(
        tmp_path, {**SUBMISSIONS_PAYLOAD, "cik": "0009999999"})
    with pytest.raises(PilotPacketError) as excinfo:
        build(tmp_path)
    assert excinfo.value.reason_code == "cik_mismatch"


def test_build_refuses_missing_accession(tmp_path):
    bad = json.loads(json.dumps(SUBMISSIONS_PAYLOAD))
    bad["filings"]["recent"]["accessionNumber"][1] = "0000000000-00-000000"
    _collect_with_submissions(tmp_path, bad)
    with pytest.raises(PilotPacketError) as excinfo:
        build(tmp_path)
    assert excinfo.value.reason_code == "filing_missing"


def test_build_refuses_wrong_cutoff(tmp_path):
    bad = json.loads(json.dumps(SUBMISSIONS_PAYLOAD))
    bad["filings"]["recent"]["filingDate"][1] = "2025-02-13"
    _collect_with_submissions(tmp_path, bad)
    with pytest.raises(PilotPacketError) as excinfo:
        build(tmp_path)
    assert excinfo.value.reason_code == "cutoff_mismatch"


def test_build_refuses_index_without_primary_document(tmp_path):
    bad_index = json.dumps({"directory": {"item": [{"name": "other.htm"}]}}).encode()
    transport = FakeTransport({URLS[1]: TransportResponse(200, URLS[1], bad_index)})
    collect(tmp_path, transport=transport)
    with pytest.raises(PilotPacketError) as excinfo:
        build(tmp_path)
    assert excinfo.value.reason_code == "index_invalid"


# --- Structural-anchor refusals ----------------------------------------------


def test_start_anchor_wrong_bytes_refused(tmp_path):
    # Offsets pointing at other document bytes: the slice does not equal the
    # locked structural-anchor bytes.
    collect(tmp_path)
    length = len(pp.START_ANCHOR_BYTES)
    with pytest.raises(PilotPacketError) as excinfo:
        build(tmp_path, start_anchor=start_anchor(
            start_offset=0, end_offset=length,
            sha256=sha(DOC[0:length])))
    assert excinfo.value.reason_code == "anchor_invalid"


def test_start_anchor_tampered_hash_refused(tmp_path):
    collect(tmp_path)
    with pytest.raises(PilotPacketError) as excinfo:
        build(tmp_path, start_anchor=start_anchor(sha256="0" * 64))
    assert excinfo.value.reason_code == "anchor_invalid"


def test_start_anchor_out_of_range_offsets_refused(tmp_path):
    collect(tmp_path)
    for bad in (start_anchor(start_offset=-1),
                start_anchor(end_offset=len(DOC) + 5),
                start_anchor(start_offset=START_ANCHOR_OFFSETS[1],
                             end_offset=START_ANCHOR_OFFSETS[0])):
        with pytest.raises(PilotPacketError) as excinfo:
            build(tmp_path, start_anchor=bad)
        assert excinfo.value.reason_code == "anchor_invalid"


def test_end_anchor_wrong_bytes_refused(tmp_path):
    # The end anchor offsets pointed at the START anchor's bytes: byte
    # equality with the locked END anchor bytes must refuse.
    collect(tmp_path)
    with pytest.raises(PilotPacketError) as excinfo:
        build(tmp_path, end_anchor=end_anchor(
            start_offset=START_ANCHOR_OFFSETS[0],
            end_offset=START_ANCHOR_OFFSETS[1],
            sha256=sha(pp.START_ANCHOR_BYTES)))
    assert excinfo.value.reason_code == "anchor_invalid"


def test_end_anchor_tampered_hash_refused(tmp_path):
    collect(tmp_path)
    with pytest.raises(PilotPacketError) as excinfo:
        build(tmp_path, end_anchor=end_anchor(sha256="0" * 64))
    assert excinfo.value.reason_code == "anchor_invalid"


REVERSED_DOC = (
    b"<html><body>"
    b'<div id="item_1a_risk_factors"><p>early risks text</p></div>'
    b'<div id="item_i_business"><p>late business text</p></div>'
    b"</body></html>"
)


def _reversed_slice(needle: bytes) -> tuple[int, int]:
    start = REVERSED_DOC.index(needle)
    return start, start + len(needle)


def test_anchor_order_invalid_is_the_precise_refusal():
    # Both anchors are byte-exact locked anchors in the document; the end
    # anchor is physically BEFORE the start anchor, so only the ordering
    # branch can refuse — and it must, precisely.
    s_start, s_end = _reversed_slice(pp.START_ANCHOR_BYTES)
    e_start, e_end = _reversed_slice(pp.END_ANCHOR_BYTES)
    assert e_start < s_start  # reversed by construction
    start = AnchorSelection(
        start_offset=s_start, end_offset=s_end,
        sha256=sha(pp.START_ANCHOR_BYTES))
    end = AnchorSelection(
        start_offset=e_start, end_offset=e_end,
        sha256=sha(pp.END_ANCHOR_BYTES))
    ev_start, ev_end = _reversed_slice(b"early risks text")
    ev = ByteSliceSelection(
        start_offset=ev_start, end_offset=ev_end,
        sha256=sha(REVERSED_DOC[ev_start:ev_end]), text="early risks text")
    with pytest.raises(PilotPacketError) as excinfo:
        pp._validate_anchors_and_evidence(REVERSED_DOC, start, end, ev)
    assert excinfo.value.reason_code == "anchor_order_invalid"


def test_evidence_outside_markers_refused(tmp_path):
    collect(tmp_path)
    outside = DOC.index(b"risks")
    with pytest.raises(PilotPacketError) as excinfo:
        build(tmp_path, evidence=evidence(
            start_offset=outside, end_offset=outside + len(b"risks"),
            sha256=sha(DOC[outside:outside + len(b"risks")]), text="risks"))
    assert excinfo.value.reason_code == "evidence_out_of_bounds"


def test_evidence_hash_and_text_mismatch_refused(tmp_path):
    collect(tmp_path)
    with pytest.raises(PilotPacketError) as excinfo:
        build(tmp_path, evidence=evidence(sha256="0" * 64))
    assert excinfo.value.reason_code == "evidence_invalid"
    with pytest.raises(PilotPacketError) as excinfo:
        build(tmp_path, evidence=evidence(text=EVIDENCE_TEXT + "x"))
    assert excinfo.value.reason_code == "evidence_invalid"


def test_evidence_invalid_utf8_slice_refused(tmp_path):
    # Offsets that split the multibyte character in the preamble.
    collect(tmp_path)
    split = DOC.index(b"\xc3\xa9") + 1
    with pytest.raises(PilotPacketError) as excinfo:
        build(tmp_path, evidence=evidence(
            start_offset=split - 4, end_offset=split,
            sha256=sha(DOC[split - 4:split]), text="x"))
    assert excinfo.value.reason_code == "evidence_invalid"


def test_evidence_entity_decode_or_normalization_mismatch_refused(tmp_path):
    # The raw bytes contain "sales &amp; service"; recording the entity-decoded
    # or whitespace-normalized rendering must be refused (byte-exact rule).
    collect(tmp_path)
    region = b"sales &amp; service"
    start = DOC.index(region)
    end = start + len(region)
    for rendered in ("sales & service", "sales  &amp;  service"):
        with pytest.raises(PilotPacketError) as excinfo:
            build(tmp_path, evidence=evidence(
                start_offset=start, end_offset=end, sha256=sha(DOC[start:end]),
                text=rendered))
        assert excinfo.value.reason_code == "evidence_invalid"


def test_blank_selection_note_refused(tmp_path):
    collect(tmp_path)
    with pytest.raises(PilotPacketError) as excinfo:
        build(tmp_path, selection_note="   ")
    assert excinfo.value.reason_code == "selection_note_blank"


# --- Strict successful-receipt revalidation ---------------------------------


def _tampered_build(tmp_path, mutate):
    collect(tmp_path)
    path = _receipt_path(tmp_path)
    receipt = json.loads(path.read_bytes())
    mutate(receipt)
    path.write_bytes(json.dumps(receipt).encode())
    with pytest.raises(PilotPacketError) as excinfo:
        build(tmp_path)
    return excinfo.value


@pytest.mark.parametrize("mutate,expected_code", [
    (lambda r: r["retrievals"][0].pop("key"), "receipt_invalid"),
    (lambda r: r["retrievals"][0].__setitem__("key", "wrong_key"),
     "receipt_invalid"),
    (lambda r: r["identity"].__setitem__("cik", "0009999999"), "receipt_invalid"),
    (lambda r: r["identity"].__setitem__("form", "10-Q"), "receipt_invalid"),
    (lambda r: r["identity"].__setitem__("filing_date", "2025-02-13"),
     "receipt_invalid"),
    (lambda r: r["identity"].__setitem__("period_of_report", "2023-12-31"),
     "receipt_invalid"),
    (lambda r: r["identity"].pop("form"), "receipt_invalid"),
    (lambda r: r["retrievals"][1].__setitem__(
        "final_url", "https://www.sec.gov/other/location.json"), "receipt_invalid"),
    (lambda r: r["retrievals"][1].pop("final_url"), "receipt_invalid"),
    (lambda r: r["retrievals"][1].__setitem__("http_status", 301),
     "receipt_invalid"),
    (lambda r: r["retrievals"][1].__setitem__("http_status", "200"),
     "receipt_invalid"),
    (lambda r: r["retrievals"][2].pop("retrieval_timestamp"), "receipt_invalid"),
    (lambda r: r["retrievals"][2].__setitem__(
        "retrieval_timestamp", "2026-07-27T12:00:00"), "receipt_invalid"),
    (lambda r: r["retrievals"][0].__setitem__("byte_count", -1),
     "receipt_invalid"),
    (lambda r: r["retrievals"][0].__setitem__("byte_count", "12"),
     "receipt_invalid"),
    (lambda r: r["retrievals"][0].__setitem__("retry_count", 2),
     "receipt_invalid"),
    (lambda r: r["retrievals"][0].__setitem__("retry_count", "0"),
     "receipt_invalid"),
    (lambda r: r["retrievals"][0].__setitem__("retry_count", True),
     "receipt_invalid"),
    (lambda r: r["retrievals"][0].pop("sha256"), "receipt_invalid"),
    (lambda r: r["retrievals"][0].__setitem__("sha256", "A" * 64),
     "receipt_invalid"),
    (lambda r: r["retrievals"][0].__setitem__(
        "failure_reason", "late_annotation"), "receipt_incomplete"),
    (lambda r: r.__setitem__("completion_status", "stopped"),
     "receipt_incomplete"),
])
def test_successful_receipt_tampering_is_refused_sanitized(
        tmp_path, mutate, expected_code):
    error = _tampered_build(tmp_path, mutate)
    assert error.reason_code == expected_code  # never KeyError/TypeError


def test_receipt_byte_count_mismatch_with_intact_sha_is_refused(tmp_path):
    # A well-typed but wrong byte_count (SHA-256 left untouched) must refuse:
    # the persisted raw length is compared against the receipt, not type-checked.
    collect(tmp_path)
    path = _receipt_path(tmp_path)
    receipt = json.loads(path.read_bytes())
    entry = receipt["retrievals"][0]
    assert entry["sha256"] == sha(SUBMISSIONS_BYTES)  # hash stays intact
    entry["byte_count"] = len(SUBMISSIONS_BYTES) + 7  # different nonneg integer
    path.write_bytes(json.dumps(receipt).encode())
    with pytest.raises(PilotPacketError) as excinfo:
        build(tmp_path)
    assert excinfo.value.reason_code == "receipt_content_mismatch"


# --- Zero-evidence stop path -------------------------------------------------


def test_no_valid_anchor_is_a_stop_not_a_packet(tmp_path):
    outcome, _, _ = collect(tmp_path)
    raw_before = {
        path.name: path.read_bytes()
        for path in outcome.raw_directory.iterdir()
    }
    # A nonempty, hash-verified document for which no valid anchor is supplied.
    with pytest.raises(PilotPacketError):
        build(tmp_path, evidence=evidence(sha256="0" * 64))
    report = materiality_stop_report(
        tmp_path, "no source-supported materiality fragment could be selected")
    assert report["outcome"] == "materiality_evidence_stop"
    assert report["packet_created"] is False
    assert report["decision_log_entry_created"] is False
    assert report["collection_receipt_sha256"] == outcome.receipt_sha256
    assert not (tmp_path / "registry" / "packet.json").exists()
    raw_after = {
        path.name: path.read_bytes()
        for path in outcome.raw_directory.iterdir()
    }
    assert raw_after == raw_before  # raw files and receipt preserved untouched


def test_stop_report_requires_nonblank_reason(tmp_path):
    collect(tmp_path)
    with pytest.raises(PilotPacketError):
        materiality_stop_report(tmp_path, "  ")


# --- Sentinel network guard ---------------------------------------------------


def test_module_carries_no_network_client_and_requires_injected_transport(tmp_path):
    source = Path(pp.__file__).read_text()
    for forbidden in ("import requests", "import httpx", "import urllib",
                      "import socket"):
        assert forbidden not in source
    # Library-only module: no CLI entry point exists (injection-only design).
    assert not hasattr(pp, "main")
    assert '__main__' not in source
    with pytest.raises(PilotPacketError) as excinfo:
        collect_pilot_sources(
            raw_root=tmp_path, transport=None, sleeper=FakeSleeper(),
            clock=lambda: "2026-07-27T12:00:00+00:00")
    assert excinfo.value.reason_code == "transport_required"
    raw = tmp_path / "sec" / "CIK0001404655" / "0000950170-25-018873"
    assert not any(raw.glob("*"))  # nothing written before the refusal
