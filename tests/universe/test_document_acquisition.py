"""Baseline filing-document acquisition tests (W2-B, ADR-089) — fully offline.

Every run replays local synthetic documents through the injected fixture
transport into a temporary directory; nothing reads ``data/runs``, no network
exists, and no model is called. These tests pin the corrected URL contract:
``sec_filename`` validates and provides provenance, and the requested URL is
derived in the SEC filing-directory form.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import dynamic_ai_products.universe.document_acquisition as da
from dynamic_ai_products.universe.document_acquisition import (
    DocumentPlanError,
    canonical_document_url,
    load_document_request_plan,
    make_document_fixture_replay_transport,
    run_document_acquisition,
    validate_document_request_plan,
)
from dynamic_ai_products.sec_document_transport import (
    SEC_LIVE_DOCUMENT_TRANSPORT_CONTRACT,
    SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY,
    STREAM_CHUNK_BYTES,
    header_value,
    make_sec_live_document_transport,
    parse_content_length,
)
from dynamic_ai_products.sec_index_transport import (
    HttpxStreamingResponse,
    SEC_LIVE_TRANSPORT_IDENTITY,
)
from dynamic_ai_products.universe.io_utils import read_json, sha256_file

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "evals" / "fixtures" / "baseline_documents"
FIXTURE_PLAN = FIXTURE_DIR / "request_plan.json"
CANARY_PLAN = ROOT / "configs" / "baseline_doc_canary_request_plan.json"
SCHEMA_PATH = (
    ROOT / "schemas" / "baseline_document_acquisition_manifest.schema.json"
)
SCHEMA_V2_PATH = (
    ROOT / "schemas" / "baseline_document_acquisition_manifest.v2.schema.json"
)
CLI = ROOT / "pipelines" / "00_build_company_universe.py"
EXPECTED = read_json(FIXTURE_DIR / "expected_acquisition.json")

FIXED_CLOCK = lambda: datetime(2026, 8, 16, 9, 0, 0, tzinfo=timezone.utc)  # noqa: E731


def _plan_payload() -> dict:
    return json.loads(FIXTURE_PLAN.read_text(encoding="utf-8"))


def _write_plan(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _ceiling_of(plan: Path) -> int:
    return json.loads(plan.read_text(encoding="utf-8"))["max_document_bytes"]


def _acquire(tmp_path: Path, plan: Path, run_id: str = "docs-test", **kwargs):
    ceiling = kwargs.pop("transport_max_bytes", _ceiling_of(plan))
    transport = kwargs.pop(
        "transport",
        make_document_fixture_replay_transport(FIXTURE_DIR, max_bytes=ceiling),
    )
    return run_document_acquisition(
        repo_root=ROOT,
        request_plan_path=plan,
        output_dir=tmp_path / "out",
        run_id=run_id,
        transport=transport,
        transport_max_bytes=ceiling,
        clock=FIXED_CLOCK,
        **kwargs,
    )


# --- URL derivation ---------------------------------------------------------


def test_canonical_url_strips_zeros_and_uses_filing_directory():
    assert canonical_document_url("0001999999", "0001999999-22-000001") == (
        "https://www.sec.gov/Archives/edgar/data/1999999/"
        "000199999922000001/0001999999-22-000001.txt"
    )
    # Real frozen-frame case: AAR CORP's baseline 10-K.
    assert canonical_document_url("0000001750", "0001104659-22-081498") == (
        "https://www.sec.gov/Archives/edgar/data/1750/"
        "000110465922081498/0001104659-22-081498.txt"
    )


def test_url_is_never_the_sec_filename_concatenation():
    # The old (wrong) form would have been base + sec_filename. The derived
    # URL must differ from it and must carry the accession directory.
    payload = _plan_payload()
    entries, _ = validate_document_request_plan(payload)
    for entry in entries:
        for row in entry.carrier_rows:
            assert entry.url != f"https://www.sec.gov/Archives/{row.sec_filename}"
        assert f"/{entry.accession.replace('-', '')}/" in entry.url


# --- sec_filename validation: three separate refusals -----------------------


def test_malformed_sec_filename_shape_is_refused(tmp_path):
    payload = _plan_payload()
    payload["documents"][0]["carrier_rows"][0]["sec_filename"] = (
        "edgar/data/1999999/0001999999-22-000001.htm"
    )
    with pytest.raises(DocumentPlanError, match="full-index shape"):
        load_document_request_plan(_write_plan(tmp_path / "p.json", payload))


def test_sec_filename_cik_mismatch_is_refused(tmp_path):
    payload = _plan_payload()
    payload["documents"][0]["carrier_rows"][0]["sec_filename"] = (
        "edgar/data/1234567/0001999999-22-000001.txt"
    )
    with pytest.raises(DocumentPlanError, match="not the row CIK"):
        load_document_request_plan(_write_plan(tmp_path / "p.json", payload))


def test_sec_filename_accession_mismatch_is_refused(tmp_path):
    payload = _plan_payload()
    payload["documents"][0]["carrier_rows"][0]["sec_filename"] = (
        "edgar/data/1999999/0001999999-22-000009.txt"
    )
    with pytest.raises(DocumentPlanError, match="not the entry accession"):
        load_document_request_plan(_write_plan(tmp_path / "p.json", payload))


# --- shared accessions, dedup, directory choice -----------------------------


def test_shared_group_uses_lowest_cik_directory_not_agent_prefix(tmp_path):
    entries, _, _ = load_document_request_plan(FIXTURE_PLAN)
    shared = [e for e in entries if e.kind == "shared"][0]
    # The accession prefix is 2777777 (a filing agent); the directory must be
    # the lowest sharing CIK, 1888888.
    assert shared.accession.startswith("0002777777")
    assert shared.directory_cik == "0001888888"
    assert "/edgar/data/1888888/" in shared.url
    assert "/edgar/data/2777777/" not in shared.url


def test_wrong_directory_cik_is_refused(tmp_path):
    payload = _plan_payload()
    payload["documents"][1]["directory_cik"] = "0001999998"  # not the lowest
    with pytest.raises(DocumentPlanError, match="not the lowest mapped CIK"):
        load_document_request_plan(_write_plan(tmp_path / "p.json", payload))


def test_repeated_accession_across_entries_is_refused(tmp_path):
    payload = _plan_payload()
    payload["documents"].append(json.loads(json.dumps(payload["documents"][0])))
    with pytest.raises(DocumentPlanError, match="more than one entry"):
        load_document_request_plan(_write_plan(tmp_path / "p.json", payload))


def test_kind_and_row_count_must_agree(tmp_path):
    payload = _plan_payload()
    payload["documents"][1]["kind"] = "regular"
    with pytest.raises(DocumentPlanError, match="regular document maps exactly one"):
        load_document_request_plan(_write_plan(tmp_path / "p.json", payload))

    payload = _plan_payload()
    payload["documents"][0]["kind"] = "shared"
    with pytest.raises(DocumentPlanError, match="shared document maps more than one"):
        load_document_request_plan(_write_plan(tmp_path / "p.json", payload))


# --- acquisition round trip -------------------------------------------------


def test_fixture_acquisition_matches_gold(tmp_path):
    result = _acquire(tmp_path, FIXTURE_PLAN)
    assert result.failure is None
    manifest = read_json(result.manifest_path)
    assert manifest["counts"] == EXPECTED["counts"]
    assert manifest["max_document_bytes"] == EXPECTED["max_document_bytes"]
    assert manifest["firm_document_mapping"] == EXPECTED["firm_document_mapping"]
    for got, want in zip(manifest["documents"], EXPECTED["documents"]):
        for key, value in want.items():
            assert got[key] == value
    # Raw bytes are preserved verbatim and hashed.
    for want in EXPECTED["documents"]:
        written = result.run_dir / want["document_filename"]
        assert sha256_file(written) == want["document_sha256"]
        assert written.read_bytes() == (
            FIXTURE_DIR / want["document_filename"]
        ).read_bytes()


def test_manifest_validates_against_canonical_schema(tmp_path):
    result = _acquire(tmp_path, FIXTURE_PLAN)
    manifest = read_json(result.manifest_path)
    schema = read_json(SCHEMA_PATH)
    assert not list(Draft202012Validator(schema).iter_errors(manifest))
    assert manifest["transport_kind"] == "fixture_replay"
    assert manifest["schema_versions"] == {
        "baseline_document_acquisition_manifest": "0.1.0"
    }


def test_shared_document_requested_once_and_mapped_to_every_row(tmp_path):
    result = _acquire(tmp_path, FIXTURE_PLAN)
    manifest = read_json(result.manifest_path)
    shared = [d for d in manifest["documents"] if d["kind"] == "shared"][0]
    assert shared["mapped_carrier_rows"] == 2
    mapped = [
        m for m in manifest["firm_document_mapping"]
        if m["accession"] == shared["accession"]
    ]
    assert [m["cik"] for m in mapped] == ["0001888888", "0001999998"]
    # One document file on disk for the shared accession, not one per filer.
    assert len(list(result.run_dir.glob("*.txt"))) == 2


# --- ceiling, failures, immutability ---------------------------------------


def test_document_over_plan_ceiling_is_refused(tmp_path):
    payload = _plan_payload()
    payload["max_document_bytes"] = 100  # below both fixture documents
    plan = _write_plan(tmp_path / "p.json", payload)
    result = _acquire(tmp_path, plan)
    assert result.failure is not None
    assert result.failure.reason_code == "document_over_ceiling"
    assert result.manifest_path is None
    # Nothing was persisted for the refused document.
    assert not list(result.run_dir.glob("*.txt"))
    assert result.failure_receipt_path.is_file()


def test_missing_ceiling_field_is_refused(tmp_path):
    payload = _plan_payload()
    del payload["max_document_bytes"]
    with pytest.raises(DocumentPlanError, match="max_document_bytes"):
        load_document_request_plan(_write_plan(tmp_path / "p.json", payload))


def test_nonpositive_ceiling_is_refused(tmp_path):
    payload = _plan_payload()
    payload["max_document_bytes"] = 0
    with pytest.raises(DocumentPlanError, match="explicit positive integer"):
        load_document_request_plan(_write_plan(tmp_path / "p.json", payload))


def test_missing_document_fails_closed_with_receipt(tmp_path):
    payload = _plan_payload()
    payload["documents"][0]["accession"] = "0001999999-22-000099"
    payload["documents"][0]["carrier_rows"][0]["sec_filename"] = (
        "edgar/data/1999999/0001999999-22-000099.txt"
    )
    plan = _write_plan(tmp_path / "p.json", payload)
    result = _acquire(tmp_path, plan)
    assert result.failure is not None
    assert result.failure.reason_code == "unexpected_http_status"
    assert result.manifest_path is None
    receipt = read_json(result.failure_receipt_path)
    assert receipt["documents_acquired_before_failure"] == []
    assert receipt["attempted_url"].endswith("0001999999-22-000099.txt")


def test_entrant_cohort_plan_is_refused(tmp_path):
    payload = _plan_payload()
    payload["cohort"] = "post_baseline_entrants"
    with pytest.raises(DocumentPlanError, match="baseline_candidates"):
        load_document_request_plan(_write_plan(tmp_path / "p.json", payload))


def test_plan_base_url_cannot_redirect_requests(tmp_path):
    payload = _plan_payload()
    payload["base_url"] = "https://example.invalid/Archives/"
    with pytest.raises(DocumentPlanError, match="base_url"):
        load_document_request_plan(_write_plan(tmp_path / "p.json", payload))


def test_rerun_of_existing_run_id_is_refused(tmp_path):
    _acquire(tmp_path, FIXTURE_PLAN, run_id="immutable-docs")
    before = sorted(p.name for p in (tmp_path / "out" / "immutable-docs").iterdir())
    with pytest.raises(FileExistsError):
        _acquire(tmp_path, FIXTURE_PLAN, run_id="immutable-docs")
    assert sorted(
        p.name for p in (tmp_path / "out" / "immutable-docs").iterdir()
    ) == before


def test_dry_run_writes_nothing(tmp_path):
    result = _acquire(tmp_path, FIXTURE_PLAN, dry_run=True)
    assert result.dry_run is True
    assert result.run_dir is None
    assert len(result.entries) == 2
    assert not (tmp_path / "out").exists()


# --- sec_live successor contract --------------------------------------------


def test_sec_live_identity_writes_the_v2_manifest(tmp_path):
    result = _acquire(
        tmp_path, FIXTURE_PLAN, run_id="live-shaped",
        transport_identity=SEC_LIVE_TRANSPORT_IDENTITY,
    )
    manifest = read_json(result.manifest_path)
    assert manifest["transport_kind"] == "sec_live"
    assert manifest["transport_contract"]["transport_kind"] == "sec_live"
    assert manifest["schema_versions"] == {
        "baseline_document_acquisition_manifest_v2": "0.2.0"
    }
    schema = read_json(SCHEMA_V2_PATH)
    assert not list(Draft202012Validator(schema).iter_errors(manifest))


# --- committed canary plan --------------------------------------------------


def test_committed_canary_plan_structure():
    entries, fields, _ = load_document_request_plan(CANARY_PLAN)
    assert len(entries) == 12
    assert sum(len(e.carrier_rows) for e in entries) == 16
    assert fields["max_document_bytes"] == 268435456
    assert fields["cohort"] == "baseline_candidates"
    by_form: dict[str, list] = {}
    for entry in entries:
        by_form.setdefault(entry.form, []).append(entry)
    assert sorted(by_form) == ["10-K", "10-KT", "20-F", "40-F"]
    expected_kinds = {
        "10-K": {"regular": 2, "shared": 1},
        "10-KT": {"regular": 3, "shared": 0},  # no shared 10-KT group exists
        "20-F": {"regular": 2, "shared": 1},
        "40-F": {"regular": 2, "shared": 1},
    }
    for form, wanted in expected_kinds.items():
        got = {
            kind: sum(1 for e in by_form[form] if e.kind == kind)
            for kind in ("regular", "shared")
        }
        assert got == wanted, form


def test_committed_canary_plan_pins_carrier_provenance():
    _, fields, _ = load_document_request_plan(CANARY_PLAN)
    provenance = fields["provenance"]
    assert provenance["carrier_run_id"] == (
        "universe-baseline-carrier-frame-v1-20260816"
    )
    assert provenance["carrier_manifest_sha256"] == (
        "50a2582f9a255c4402151aa4d963ce5d7bd7c952b8e4a5e77f4a7e7ce454521f"
    )
    assert provenance["freeze_record_sha256"] == sha256_file(
        ROOT / "configs" / "frame_v1_freeze.json"
    )


def test_committed_canary_exercises_both_directory_cases():
    entries, _, _ = load_document_request_plan(CANARY_PLAN)
    shared = {e.form: e for e in entries if e.kind == "shared"}
    # 10-K: the accession prefix is a filing agent, not any sharing filer.
    ten_k = shared["10-K"]
    assert ten_k.accession.startswith("0001437749")
    assert ten_k.directory_cik == "0000003146"
    assert "/edgar/data/3146/" in ten_k.url
    assert all(r.cik != "0001437749" for r in ten_k.carrier_rows)
    # 40-F: the prefix IS a sharing filer, but not the lowest CIK.
    forty_f = shared["40-F"]
    assert forty_f.accession.startswith("0001232384")
    assert any(r.cik == "0001232384" for r in forty_f.carrier_rows)
    assert forty_f.directory_cik == "0000099070"
    assert "/edgar/data/99070/" in forty_f.url


@pytest.mark.skipif(
    not (
        ROOT / "data" / "runs" / "universe-baseline-carrier"
        / "universe-baseline-carrier-frame-v1-20260816"
        / "universe_baseline_carrier.jsonl"
    ).exists(),
    reason="local carrier run absent; canary membership not re-derivable",
)
def test_canary_membership_matches_the_local_carrier_run():
    # Read-only: every planned row must exist in the carrier as a baseline
    # candidate with that exact accession, and no shared group may be partial.
    carrier = (
        ROOT / "data" / "runs" / "universe-baseline-carrier"
        / "universe-baseline-carrier-frame-v1-20260816"
        / "universe_baseline_carrier.jsonl"
    )
    rows = {}
    for line in carrier.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["baseline_status"] == "baseline_candidate":
            rows[(row["stratum"], row["cik"])] = row["baseline_accession"]
    entries, _, _ = load_document_request_plan(CANARY_PLAN)
    accession_rows: dict[str, set] = {}
    for key, accession in rows.items():
        accession_rows.setdefault(accession, set()).add(key)
    for entry in entries:
        planned = {(r.stratum, r.cik) for r in entry.carrier_rows}
        for key in planned:
            assert rows.get(key) == entry.accession, key
        assert planned == accession_rows[entry.accession], entry.accession


# --- boundaries -------------------------------------------------------------


def test_module_has_no_dera_or_network_dependency():
    source = (
        ROOT / "src" / "dynamic_ai_products" / "universe"
        / "document_acquisition.py"
    ).read_text(encoding="utf-8")
    assert "frame_dera_validation" not in source
    assert "dera_acquisition" not in source
    assert "import httpx" not in source
    assert "requests" not in source


def test_cli_acquire_docs_mode(tmp_path):
    import subprocess
    import sys

    completed = subprocess.run(
        [
            sys.executable, str(CLI),
            "--mode", "acquire-docs",
            "--request-plan", str(FIXTURE_PLAN),
            "--replay-dir", str(FIXTURE_DIR),
            "--output-dir", str(tmp_path / "out"),
            "--run-id", "cli-docs",
        ],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["documents_acquired"] == 2
    assert payload["mapped_carrier_rows"] == 3
    assert payload["failure_reason_code"] is None


def test_cli_acquire_docs_rejects_cross_mode_flags(tmp_path):
    import subprocess
    import sys

    completed = subprocess.run(
        [
            sys.executable, str(CLI),
            "--mode", "acquire-docs",
            "--request-plan", str(FIXTURE_PLAN),
            "--replay-dir", str(FIXTURE_DIR),
            "--frame-manifest", str(FIXTURE_PLAN),
            "--output-dir", str(tmp_path / "out"),
            "--run-id", "cli-docs-bad",
        ],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode != 0
    assert "does not accept" in completed.stderr


# --- bounded streaming transport: lifetime ----------------------------------

STREAM_URL = (
    "https://www.sec.gov/Archives/edgar/data/1999999/"
    "000199999922000001/0001999999-22-000001.txt"
)


class FakeStream:
    """A streaming response whose resources are explicitly tracked."""

    def __init__(self, *, status_code=200, headers=None, chunks=(),
                 final_url=STREAM_URL, raise_on_iter=None):
        self.status_code = status_code
        self.final_url = final_url
        self.headers = dict(headers or {})
        self._chunks = list(chunks)
        self._raise = raise_on_iter
        self.close_calls = 0
        self.chunks_consumed = 0
        self.exhausted = False

    def iter_chunks(self, chunk_bytes):
        if self._raise is not None:
            raise self._raise
        for chunk in self._chunks:
            self.chunks_consumed += 1
            yield chunk
        self.exhausted = True

    def close(self):
        self.close_calls += 1

    @property
    def closed(self):
        return self.close_calls > 0


def _live_transport(max_bytes, streams):
    """Build the bounded transport over a scripted list of fake streams."""
    queue = list(streams)
    sent = []

    def stream_send(url):
        stream = queue[len(sent)]
        sent.append(stream)
        if isinstance(stream, Exception):
            raise stream
        return stream

    transport = make_sec_live_document_transport(
        max_bytes=max_bytes,
        stream_send=stream_send,
        sleeper=lambda seconds: None,
        monotonic=lambda: 0.0,
    )
    return transport, sent


def test_stream_closed_on_successful_acquisition():
    stream = FakeStream(chunks=[b"abc", b"def"])
    transport, _ = _live_transport(1000, [stream])
    response = transport(STREAM_URL)
    assert response.content == b"abcdef"
    assert response.ceiling_refusal is None
    assert stream.close_calls == 1


def test_stream_closed_on_content_length_preflight_refusal():
    stream = FakeStream(headers={"Content-Length": "5000"}, chunks=[b"x" * 10])
    transport, _ = _live_transport(100, [stream])
    response = transport(STREAM_URL)
    assert response.ceiling_refusal == "content_length_preflight"
    assert response.declared_content_length == 5000
    assert stream.chunks_consumed == 0  # no body chunk was ever consumed
    assert response.bytes_received == 0
    assert response.content == b""
    assert stream.close_calls == 1


def test_stream_closed_on_chunk_limit_refusal():
    stream = FakeStream(chunks=[b"x" * 64] * 10)
    transport, _ = _live_transport(100, [stream])
    response = transport(STREAM_URL)
    assert response.ceiling_refusal == "stream_exceeded"
    assert stream.close_calls == 1
    assert not stream.exhausted  # abandoned, not drained


def test_stream_closed_on_redirect_and_body_never_consumed():
    stream = FakeStream(
        status_code=302, headers={"Location": "https://example.invalid/x"},
        chunks=[b"body"],
    )
    transport, _ = _live_transport(1000, [stream])
    response = transport(STREAM_URL)
    assert response.status_code == 302
    assert response.location == "https://example.invalid/x"
    assert stream.chunks_consumed == 0
    assert stream.close_calls == 1


def test_stream_closed_on_non_200():
    stream = FakeStream(status_code=404, chunks=[b"nope"])
    transport, _ = _live_transport(1000, [stream])
    response = transport(STREAM_URL)
    assert response.status_code == 404
    assert stream.chunks_consumed == 0
    assert stream.close_calls == 1


def test_terminal_url_mismatch_is_refused_before_any_body_chunk():
    # A 200 served from another URL must not have its body read: the runner
    # is going to refuse the mismatch, so reading up to the ceiling first
    # would be pure waste. The mismatching URL is returned unchanged so the
    # runner's classification is unaffected.
    stream = FakeStream(
        final_url="https://www.sec.gov/elsewhere.txt",
        chunks=[b"x" * 64] * 100,
    )
    transport, _ = _live_transport(1000, [stream])
    response = transport(STREAM_URL)
    assert response.status_code == 200
    assert response.final_url == "https://www.sec.gov/elsewhere.txt"
    assert response.content == b""
    assert response.ceiling_refusal is None
    assert response.bytes_received == 0
    assert stream.chunks_consumed == 0
    assert stream.close_calls == 1


def test_runner_refuses_a_mismatching_terminal_url_with_no_body_read(tmp_path):
    ceiling = _ceiling_of(FIXTURE_PLAN)
    streams: list[FakeStream] = []

    def stream_send(url):
        stream = FakeStream(
            final_url="https://www.sec.gov/Archives/elsewhere.txt",
            headers={"content-length": "64"},
            chunks=[b"x" * 64],
        )
        streams.append(stream)
        return stream

    transport = make_sec_live_document_transport(
        max_bytes=ceiling, stream_send=stream_send,
        sleeper=lambda s: None, monotonic=lambda: 0.0,
    )
    result = _acquire(
        tmp_path, FIXTURE_PLAN, run_id="url-mismatch",
        transport=transport,
        transport_identity=SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY,
    )
    assert result.failure is not None
    assert result.failure.reason_code == "terminal_url_mismatch"
    assert result.manifest_path is None
    assert not list(result.run_dir.glob("*.txt"))
    assert result.failure_receipt_path.is_file()
    assert len(streams) == 1
    assert streams[0].chunks_consumed == 0
    assert streams[0].close_calls == 1


def test_stream_closed_when_body_iteration_raises():
    stream = FakeStream(raise_on_iter=OSError("connection reset"))
    transport, _ = _live_transport(1000, [stream])
    with pytest.raises(OSError):
        transport(STREAM_URL)
    assert stream.close_calls == 1


def test_every_retry_transition_closes_its_stream():
    first = FakeStream(status_code=503, chunks=[b"retry me"])
    second = FakeStream(chunks=[b"ok"])
    transport, sent = _live_transport(1000, [first, second])
    response = transport(STREAM_URL)
    assert response.content == b"ok"
    assert len(sent) == 2
    assert first.close_calls == 1 and second.close_calls == 1
    assert first.chunks_consumed == 0  # a retried body is never consumed


def test_exhausted_retries_close_every_stream_and_return_last():
    streams = [FakeStream(status_code=503) for _ in range(3)]
    transport, sent = _live_transport(1000, streams)
    response = transport(STREAM_URL)
    assert response.status_code == 503
    assert len(sent) == 3
    assert all(s.close_calls == 1 for s in streams)


def test_send_exception_then_success_closes_only_real_streams():
    good = FakeStream(chunks=[b"ok"])
    transport, sent = _live_transport(1000, [OSError("dns"), good])
    response = transport(STREAM_URL)
    assert response.content == b"ok"
    assert len(sent) == 2
    assert good.close_calls == 1


def test_httpx_streaming_response_close_is_idempotent():
    # Exercises the real wrapper with fake resources: no httpx involved.
    class FakeCtx:
        def __init__(self):
            self.exits = 0

        def __exit__(self, *exc):
            self.exits += 1

    class FakeClient:
        def __init__(self):
            self.closes = 0

        def close(self):
            self.closes += 1

    class FakeResponse:
        status_code = 200
        url = STREAM_URL
        headers = {"Content-Length": "3"}

        def __init__(self):
            self.chunk_sizes = []

        def iter_bytes(self, chunk_size):
            self.chunk_sizes.append(chunk_size)
            return iter([b"abc"])

    client, ctx, raw = FakeClient(), FakeCtx(), FakeResponse()
    wrapper = HttpxStreamingResponse(client, ctx, raw)
    assert wrapper.status_code == 200
    assert wrapper.final_url == STREAM_URL
    assert list(wrapper.iter_chunks(4096)) == [b"abc"]
    assert raw.chunk_sizes == [4096]
    wrapper.close()
    wrapper.close()
    wrapper.close()
    assert ctx.exits == 1 and client.closes == 1
    # Context-manager form delegates to the same idempotent close.
    with HttpxStreamingResponse(FakeClient(), FakeCtx(), FakeResponse()) as second:
        pass
    assert second._closed is True


# --- bounded streaming transport: memory contract ---------------------------


def test_content_length_lookup_is_case_insensitive():
    for header in ("Content-Length", "content-length", "CoNtEnT-LeNgTh"):
        stream = FakeStream(headers={header: "5000"}, chunks=[b"x" * 10])
        transport, _ = _live_transport(100, [stream])
        response = transport(STREAM_URL)
        assert response.ceiling_refusal == "content_length_preflight", header
        assert response.declared_content_length == 5000, header
        assert stream.chunks_consumed == 0, header
        assert stream.close_calls == 1, header


def test_header_value_helper_folds_case():
    assert header_value({"content-length": "7"}, "Content-Length") == "7"
    assert header_value({"CONTENT-LENGTH": "7"}, "content-length") == "7"
    assert header_value({"other": "7"}, "content-length") is None


def test_body_of_exactly_max_bytes_is_accepted():
    stream = FakeStream(chunks=[b"x" * 50, b"y" * 50])
    transport, _ = _live_transport(100, [stream])
    response = transport(STREAM_URL)
    assert response.ceiling_refusal is None
    assert len(response.content) == 100
    assert response.bytes_received == 100


def test_one_byte_over_max_bytes_is_refused_and_nothing_retained():
    stream = FakeStream(chunks=[b"x" * 100, b"y"])
    transport, _ = _live_transport(100, [stream])
    response = transport(STREAM_URL)
    assert response.ceiling_refusal == "stream_exceeded"
    assert response.content == b""
    assert response.bytes_received == 101


def test_streamed_refusal_receives_at_most_one_chunk_beyond_the_ceiling():
    # No Content-Length at all: enforcement rests entirely on the chunk loop.
    chunk = b"x" * 64
    stream = FakeStream(chunks=[chunk] * 100)
    transport, _ = _live_transport(100, [stream])
    response = transport(STREAM_URL)
    assert response.ceiling_refusal == "stream_exceeded"
    assert response.declared_content_length is None
    assert response.content == b""
    # The retained buffer never exceeded the ceiling, and the transport
    # received at most one chunk more than the ceiling.
    assert response.bytes_received <= 100 + len(chunk)
    assert response.bytes_received <= 100 + STREAM_CHUNK_BYTES
    assert stream.chunks_consumed == 2  # abandoned as soon as it crossed
    assert not stream.exhausted


@pytest.mark.parametrize("raw", ["abc", "-5", "", "  ", "1.5", "12x"])
def test_malformed_content_length_is_treated_as_absent(raw):
    assert parse_content_length(raw) is None
    # It neither crashes nor bypasses streaming enforcement: a body that fits
    # is accepted, and an oversized one is still refused by the chunk loop.
    fits = FakeStream(headers={"Content-Length": raw}, chunks=[b"x" * 10])
    transport, _ = _live_transport(100, [fits])
    accepted = transport(STREAM_URL)
    assert accepted.ceiling_refusal is None
    assert accepted.declared_content_length is None
    assert len(accepted.content) == 10

    oversized = FakeStream(headers={"Content-Length": raw}, chunks=[b"x" * 200])
    transport, _ = _live_transport(100, [oversized])
    refused = transport(STREAM_URL)
    assert refused.ceiling_refusal == "stream_exceeded"
    assert refused.content == b""
    assert oversized.close_calls == 1


def test_absent_content_length_parses_to_none():
    assert parse_content_length(None) is None


def test_lying_small_content_length_is_still_refused_by_streaming():
    stream = FakeStream(headers={"Content-Length": "10"}, chunks=[b"x" * 500])
    transport, _ = _live_transport(100, [stream])
    response = transport(STREAM_URL)
    assert response.declared_content_length == 10
    assert response.ceiling_refusal == "stream_exceeded"
    assert response.content == b""


def test_content_length_equal_to_ceiling_is_accepted():
    stream = FakeStream(headers={"Content-Length": "100"}, chunks=[b"x" * 100])
    transport, _ = _live_transport(100, [stream])
    response = transport(STREAM_URL)
    assert response.ceiling_refusal is None
    assert len(response.content) == 100


def test_ceiling_refusal_is_never_retried():
    stream = FakeStream(headers={"Content-Length": "5000"})
    transport, sent = _live_transport(100, [stream])
    response = transport(STREAM_URL)
    assert response.ceiling_refusal == "content_length_preflight"
    assert len(sent) == 1  # terminal: no retry ladder


def test_document_transport_requires_an_explicit_positive_ceiling():
    for bad in (0, -1, None, True, "100"):
        with pytest.raises(ValueError):
            make_sec_live_document_transport(max_bytes=bad)


# --- identities and manifest enforcement record -----------------------------


def test_document_identity_is_separate_from_the_index_identity():
    assert (
        SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY.contract_hash()
        != SEC_LIVE_TRANSPORT_IDENTITY.contract_hash()
    )
    contract = SEC_LIVE_DOCUMENT_TRANSPORT_CONTRACT
    assert contract["streaming"] is True
    assert contract["stream_chunk_bytes"] == STREAM_CHUNK_BYTES
    assert contract["content_length_lookup"] == "case_insensitive"
    assert contract["malformed_content_length"] == "treated_as_absent"
    assert "max_document_bytes" not in contract  # plan-owned, per-run


def test_manifest_records_fixture_ceiling_enforcement(tmp_path):
    result = _acquire(tmp_path, FIXTURE_PLAN)
    manifest = read_json(result.manifest_path)
    assert manifest["ceiling_enforcement"] == {
        "max_document_bytes": 268435456,
        "mechanism": "bounded_local_read",
        "content_length_preflight": True,
        "stream_chunk_bytes": None,
        "max_transport_bytes": 268435456,
    }
    assert manifest["documents"][0]["declared_content_length"] == 722


def test_manifest_records_streaming_ceiling_enforcement(tmp_path):
    ceiling = _ceiling_of(FIXTURE_PLAN)
    streams = {
        "0001999999-22-000001": (FIXTURE_DIR / "0001999999-22-000001.txt").read_bytes(),
        "0002777777-22-000005": (FIXTURE_DIR / "0002777777-22-000005.txt").read_bytes(),
    }

    def stream_send(url):
        accession = url.rsplit("/", 1)[-1][: -len(".txt")]
        body = streams[accession]
        return FakeStream(
            headers={"content-length": str(len(body))},
            chunks=[body],
            final_url=url,
        )

    transport = make_sec_live_document_transport(
        max_bytes=ceiling, stream_send=stream_send,
        sleeper=lambda s: None, monotonic=lambda: 0.0,
    )
    result = _acquire(
        tmp_path, FIXTURE_PLAN, run_id="streamed",
        transport=transport,
        transport_identity=SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY,
    )
    manifest = read_json(result.manifest_path)
    assert manifest["ceiling_enforcement"] == {
        "max_document_bytes": ceiling,
        "mechanism": "streaming_chunk_bound",
        "content_length_preflight": True,
        "stream_chunk_bytes": STREAM_CHUNK_BYTES,
        "max_transport_bytes": ceiling + STREAM_CHUNK_BYTES,
    }
    schema = read_json(SCHEMA_V2_PATH)
    assert not list(Draft202012Validator(schema).iter_errors(manifest))
    assert manifest["documents"][0]["declared_content_length"] == 722


def test_runner_refuses_a_transport_bound_to_another_ceiling(tmp_path):
    with pytest.raises(DocumentPlanError, match="does not equal the plan"):
        _acquire(tmp_path, FIXTURE_PLAN, transport_max_bytes=1234)
    assert not (tmp_path / "out").exists()


def test_streamed_ceiling_refusal_reaches_the_failure_receipt(tmp_path):
    ceiling = _ceiling_of(FIXTURE_PLAN)

    def stream_send(url):
        return FakeStream(
            headers={"content-length": str(ceiling + 1)}, final_url=url
        )

    transport = make_sec_live_document_transport(
        max_bytes=ceiling, stream_send=stream_send,
        sleeper=lambda s: None, monotonic=lambda: 0.0,
    )
    result = _acquire(
        tmp_path, FIXTURE_PLAN, run_id="streamed-refusal",
        transport=transport,
        transport_identity=SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY,
    )
    assert result.manifest_path is None
    assert result.failure.reason_code == "document_over_ceiling"
    assert "content_length_preflight" in result.failure.detail
    assert not list(result.run_dir.glob("*.txt"))
    assert result.failure_receipt_path.is_file()
