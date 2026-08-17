"""Filing-index metadata probe tests (W2-C-alpha, ADR-090) — fully offline.

Every run replays local synthetic index pages through the injected fixture
transport into a temporary directory; nothing reads ``data/runs``, no network
exists, and no model is called. These tests pin what the probe establishes —
a deterministic, type-bearing primary-document selection — and, just as
importantly, what it refuses.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.sec_document_transport import (
    SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY,
    STREAM_CHUNK_BYTES,
)
from dynamic_ai_products.universe.document_acquisition import (
    DocumentTransportResponse,
)
from dynamic_ai_products.universe.filing_index_probe import (
    ProbePlanError,
    canonical_filing_index_url,
    load_probe_plan,
    make_filing_index_fixture_replay_transport,
    parse_document_format_table,
    run_filing_index_probe,
    select_primary_document,
)
from dynamic_ai_products.universe.io_utils import read_json, sha256_file

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "evals" / "fixtures" / "filing_index_probe"
FIXTURE_PLAN = FIXTURE_DIR / "request_plan.json"
LIVE_PLAN = ROOT / "configs" / "filing_index_probe_plan.json"
SCHEMA_PATH = ROOT / "schemas" / "filing_index_probe_manifest.schema.json"
SCHEMA_V2_PATH = ROOT / "schemas" / "filing_index_probe_manifest.v2.schema.json"
CLI = ROOT / "pipelines" / "00_build_company_universe.py"
EXPECTED = read_json(FIXTURE_DIR / "expected_probe.json")

FIXED_CLOCK = lambda: datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)  # noqa: E731

HEADER_ROW = (
    "<tr><th>Seq</th><th>Description</th><th>Document</th>"
    "<th>Type</th><th>Size</th></tr>"
)


ARCHIVE_DIR = "/Archives/edgar/data/9000001/000900000122000001"


def _cell(doc, *, href=None, badge=False, text=None) -> str:
    """Render a Document cell: link target first, presentation second."""
    if href is None:
        link = f"{ARCHIVE_DIR}/{doc}"
    else:
        link = href
    shown = doc if text is None else text
    suffix = '&nbsp;<span class="ixbrl">iXBRL</span>' if badge else ""
    if link == "":
        return f"<td>{shown}{suffix}</td>"
    return f'<td><a href="{link}">{shown}</a>{suffix}</td>'


def _table(rows, *, summary="Document Format Files", heading=None,
           header=HEADER_ROW) -> str:
    body = "\n".join(
        f'<tr><td>{i+1}</td><td>{desc}</td>'
        f'{_cell(doc, **(extra[0] if extra else {}))}'
        f'<td>{typ}</td><td>100</td></tr>'
        for i, (desc, doc, typ, *extra) in enumerate(rows)
    )
    lead = f"<p>{heading}</p>" if heading else ""
    attr = f' summary="{summary}"' if summary else ""
    return f'{lead}<table class="tableFile"{attr}>{header}\n{body}</table>'


def _page(rows: list[tuple[str, str, str]], **kwargs) -> bytes:
    return f"<html><body>{_table(rows, **kwargs)}</body></html>".encode("utf-8")


def _plan_payload() -> dict:
    return json.loads(FIXTURE_PLAN.read_text(encoding="utf-8"))


def _write_plan(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _ceiling_of(plan: Path) -> int:
    return json.loads(plan.read_text(encoding="utf-8"))["max_metadata_bytes"]


def _probe(tmp_path: Path, plan: Path, run_id: str = "probe-test", **kwargs):
    ceiling = kwargs.pop("transport_max_bytes", _ceiling_of(plan))
    transport = kwargs.pop(
        "transport",
        make_filing_index_fixture_replay_transport(FIXTURE_DIR, max_bytes=ceiling),
    )
    return run_filing_index_probe(
        repo_root=ROOT,
        plan_path=plan,
        output_dir=tmp_path / "out",
        run_id=run_id,
        transport=transport,
        transport_max_bytes=ceiling,
        clock=FIXED_CLOCK,
        **kwargs,
    )


# --- URL grammar ------------------------------------------------------------


def test_canonical_index_url_grammar():
    assert canonical_filing_index_url("0000001750", "0001104659-22-081498") == (
        "https://www.sec.gov/Archives/edgar/data/1750/"
        "000110465922081498/0001104659-22-081498-index.htm"
    )
    assert canonical_filing_index_url("0000066600", "0001493152-22-010080") == (
        "https://www.sec.gov/Archives/edgar/data/66600/"
        "000149315222010080/0001493152-22-010080-index.htm"
    )


def test_no_derived_url_addresses_the_full_submission():
    for plan in (FIXTURE_PLAN, LIVE_PLAN):
        entries, _, _ = load_probe_plan(plan)
        for entry in entries:
            assert entry.url.endswith("-index.htm")
            assert not entry.url.endswith(f"{entry.accession}.txt")
            assert entry.url.startswith("https://www.sec.gov/Archives/")
        # index.json is a separately authorized fallback: never requested here.
        assert all("index.json" not in e.url for e in entries)


# --- table parsing and selection -------------------------------------------


def test_document_format_table_is_found_by_its_header_cells():
    rows = parse_document_format_table(
        (FIXTURE_DIR / "0009000001-22-000001-index.htm").read_bytes()
    )
    assert [r.document for r in rows][0] == "synth-20211231x10k.htm"
    assert len(rows) == EXPECTED["observations"][0]["candidate_count"]
    # The Data Files table on the same page must not be the one selected.
    assert all(r.document != "synth-20211231_htm.xml" for r in rows)


def test_selection_is_by_declared_type_not_filename():
    rows = parse_document_format_table(
        (FIXTURE_DIR / "0009000002-22-000002-index.htm").read_bytes()
    )
    selected, refusal = select_primary_document(rows, "10-KT")
    assert refusal is None
    # No ticker-and-date convention would have found this name.
    assert selected.document == "form10-kt.htm"


def test_zero_matches_refuse():
    rows = parse_document_format_table(_page([("EX-21", "ex21.htm", "EX-21")]))
    assert select_primary_document(rows, "10-K") == (None, "no_primary_candidate")


def test_multiple_matches_refuse():
    rows = parse_document_format_table(
        _page([("10-K", "a.htm", "10-K"), ("10-K", "b.htm", "10-K")])
    )
    assert select_primary_document(rows, "10-K") == (
        None, "ambiguous_primary_candidate",
    )


def test_non_html_sole_match_refuses():
    rows = parse_document_format_table(_page([("10-K", "primary.pdf", "10-K")]))
    assert select_primary_document(rows, "10-K") == (None, "non_html_primary")


def test_matching_form_rows_with_no_html_refuse_even_when_several():
    """Cardinality is evaluated among HTML candidates, so zero is not ambiguity."""
    rows = parse_document_format_table(
        _page([("10-K", "a.pdf", "10-K"), ("10-K", "b.txt", "10-K")])
    )
    assert select_primary_document(rows, "10-K") == (None, "non_html_primary")


# --- same-form non-HTML companions (ADR-096, measured on the failed shard) ---


def test_a_same_form_pdf_companion_does_not_make_a_filing_ambiguous():
    """The exact shape measured on accession 0000007332-22-000009.

    Its Document Format Files table declares Type 10-K for both
    ``swn-20211231.htm`` and ``swn20211231x10k.pdf``.
    """
    rows = parse_document_format_table(_page([
        ("10-K", "swn-20211231.htm", "10-K"),
        ("10-K", "swn20211231x10k.pdf", "10-K"),
    ]))
    selected, refusal = select_primary_document(rows, "10-K")
    assert refusal is None
    assert selected.document == "swn-20211231.htm"


def test_selection_does_not_depend_on_document_order():
    """Eligibility, not position: the PDF listed first changes nothing."""
    rows = parse_document_format_table(_page([
        ("10-K", "swn20211231x10k.pdf", "10-K"),
        ("10-K", "swn-20211231.htm", "10-K"),
    ]))
    selected, _ = select_primary_document(rows, "10-K")
    assert selected.document == "swn-20211231.htm"


def test_several_non_html_companions_still_leave_one_html_candidate():
    rows = parse_document_format_table(_page([
        ("10-K", "a.pdf", "10-K"), ("10-K", "a.htm", "10-K"),
        ("10-K", "a.txt", "10-K"), ("10-K", "a.xml", "10-K"),
    ]))
    selected, refusal = select_primary_document(rows, "10-K")
    assert refusal is None
    assert selected.document == "a.htm"


def test_two_html_rows_are_still_ambiguous_even_beside_a_pdf():
    """The correction narrows eligibility; it does not tie-break real ambiguity."""
    rows = parse_document_format_table(_page([
        ("10-K", "a.htm", "10-K"), ("10-K", "b.html", "10-K"),
        ("10-K", "a.pdf", "10-K"),
    ]))
    assert select_primary_document(rows, "10-K") == (
        None, "ambiguous_primary_candidate",
    )


def test_eligibility_ignores_size_description_and_sequence():
    """A larger, earlier, better-described PDF still loses to the HTML row."""
    page = (
        '<html><body><table summary="Document Format Files">'
        "<tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th>"
        "<th>Size</th></tr>"
        '<tr><td>1</td><td>COMPLETE ANNUAL REPORT</td>'
        '<td><a href="/Archives/edgar/data/1/2/big.pdf">big.pdf</a></td>'
        "<td>10-K</td><td>99999999</td></tr>"
        '<tr><td>7</td><td>x</td>'
        '<td><a href="/Archives/edgar/data/1/2/small.htm">small.htm</a></td>'
        "<td>10-K</td><td>1</td></tr>"
        "</table></body></html>"
    ).encode("utf-8")
    selected, refusal = select_primary_document(
        parse_document_format_table(page), "10-K")
    assert refusal is None
    assert selected.document == "small.htm"


def test_identified_table_without_document_and_type_headers_is_unparseable():
    page = (
        '<html><body><table summary="Document Format Files">'
        "<tr><th>Seq</th><th>Size</th></tr><tr><td>1</td><td>10</td></tr>"
        "</table></body></html>"
    ).encode("utf-8")
    with pytest.raises(ProbePlanError, match="no Document and Type columns"):
        parse_document_format_table(page)


def test_unidentified_table_is_refused_even_with_the_right_columns():
    """Column shape alone is not admissible identity."""
    page = _page([("10-K", "primary.htm", "10-K")], summary=None)
    with pytest.raises(ProbePlanError, match="not admissible identity"):
        parse_document_format_table(page)


def test_decoy_data_files_table_placed_first_is_never_selected():
    """Regression: the committed page 1 puts a decoy Data Files table first.

    It carries the same Document and Type columns and a plausible annual-form
    row, so a shape-only parser would select 'decoy-20211231x10k.htm'.
    """
    raw = (FIXTURE_DIR / "0009000001-22-000001-index.htm").read_bytes()
    assert b"decoy-20211231x10k.htm" in raw, "fixture lost its decoy row"
    assert b'summary="Data Files"' in raw
    rows = parse_document_format_table(raw)
    assert all("decoy" not in r.document for r in rows)
    selected, refusal = select_primary_document(rows, "10-K")
    assert refusal is None
    assert selected.document == EXPECTED["decoy_document_never_selected"].replace(
        "decoy-", "synth-"
    )
    assert selected.document == "synth-20211231x10k.htm"


def test_identity_may_come_from_an_associated_heading():
    """Committed page 2 carries no summary; its heading supplies identity."""
    raw = (FIXTURE_DIR / "0009000002-22-000002-index.htm").read_bytes()
    assert b'<table class="tableFile">' in raw
    rows = parse_document_format_table(raw)
    assert [r.document for r in rows][1] == "form10-kt.htm"


def test_two_tables_claiming_the_identity_are_refused():
    page = (
        "<html><body>"
        + _table([("10-K", "a.htm", "10-K")])
        + _table([("10-K", "b.htm", "10-K")])
        + "</body></html>"
    ).encode("utf-8")
    with pytest.raises(ProbePlanError, match="claim the"):
        parse_document_format_table(page)


# --- fixture round trip -----------------------------------------------------


def test_fixture_probe_matches_gold(tmp_path):
    result = _probe(tmp_path, FIXTURE_PLAN)
    assert result.failure is None
    manifest = read_json(result.manifest_path)
    assert manifest["counts"] == EXPECTED["counts"]
    assert manifest["max_metadata_bytes"] == EXPECTED["max_metadata_bytes"]
    assert all(manifest["reconciliation"].values())
    for got, want in zip(manifest["observations"], EXPECTED["observations"]):
        for key in ("accession", "form", "directory_cik", "url",
                    "selected_document", "expected_primary_document",
                    "ground_truth_match"):
            assert got[key] == want[key]
        assert len(got["candidates"]) == want["candidate_count"]


def test_fixture_manifest_validates_against_v01_and_is_rejected_by_v02(tmp_path):
    result = _probe(tmp_path, FIXTURE_PLAN)
    manifest = read_json(result.manifest_path)
    assert manifest["transport_kind"] == "fixture_replay"
    assert "transport_contract" not in manifest
    assert manifest["schema_versions"] == {"filing_index_probe_manifest": "0.1.0"}
    assert not list(
        Draft202012Validator(read_json(SCHEMA_PATH)).iter_errors(manifest)
    )
    assert list(
        Draft202012Validator(read_json(SCHEMA_V2_PATH)).iter_errors(manifest)
    ), "the fixture manifest must not satisfy the sec_live successor schema"


def test_live_identity_manifest_validates_against_v02_only(tmp_path):
    result = _probe(
        tmp_path, FIXTURE_PLAN, run_id="live-shaped",
        transport_identity=SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY,
    )
    manifest = read_json(result.manifest_path)
    assert manifest["transport_kind"] == "sec_live"
    assert manifest["transport_contract"]["transport_kind"] == "sec_live"
    assert manifest["schema_versions"] == {"filing_index_probe_manifest_v2": "0.2.0"}
    assert not list(
        Draft202012Validator(read_json(SCHEMA_V2_PATH)).iter_errors(manifest)
    )
    assert list(
        Draft202012Validator(read_json(SCHEMA_PATH)).iter_errors(manifest)
    ), "the sec_live manifest must not satisfy the fixture schema"


def test_manifest_records_ceiling_enforcement_per_transport(tmp_path):
    fixture = read_json(_probe(tmp_path, FIXTURE_PLAN).manifest_path)
    assert fixture["ceiling_enforcement"] == {
        "max_metadata_bytes": 8388608,
        "mechanism": "bounded_local_read",
        "content_length_preflight": True,
        "stream_chunk_bytes": None,
        "max_transport_bytes": 8388608,
    }
    live = read_json(
        _probe(
            tmp_path, FIXTURE_PLAN, run_id="live-ceiling",
            transport_identity=SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY,
        ).manifest_path
    )
    assert live["ceiling_enforcement"] == {
        "max_metadata_bytes": 8388608,
        "mechanism": "streaming_chunk_bound",
        "content_length_preflight": True,
        "stream_chunk_bytes": STREAM_CHUNK_BYTES,
        "max_transport_bytes": 8388608 + STREAM_CHUNK_BYTES,
    }


def test_manifest_records_response_provenance(tmp_path):
    manifest = read_json(_probe(tmp_path, FIXTURE_PLAN).manifest_path)
    for observation, name in zip(
        manifest["observations"],
        ("0009000001-22-000001-index.htm", "0009000002-22-000002-index.htm"),
    ):
        assert observation["response_sha256"] == sha256_file(FIXTURE_DIR / name)
        assert observation["response_byte_length"] == (
            (FIXTURE_DIR / name).stat().st_size
        )
        assert observation["final_url"] == observation["url"]


# --- ceiling ----------------------------------------------------------------


def test_missing_ceiling_field_is_refused(tmp_path):
    payload = _plan_payload()
    del payload["max_metadata_bytes"]
    with pytest.raises(ProbePlanError, match="max_metadata_bytes"):
        load_probe_plan(_write_plan(tmp_path / "p.json", payload))


@pytest.mark.parametrize("bad", [0, -1, "8388608", True, 1.5])
def test_nonpositive_or_nonint_ceiling_is_refused(tmp_path, bad):
    payload = _plan_payload()
    payload["max_metadata_bytes"] = bad
    with pytest.raises(ProbePlanError, match="explicit positive integer"):
        load_probe_plan(_write_plan(tmp_path / "p.json", payload))


def test_transport_ceiling_mismatch_is_refused_before_any_request(tmp_path):
    sent: list[str] = []

    def transport(url):
        sent.append(url)
        return DocumentTransportResponse(status_code=200, final_url=url, content=b"")

    with pytest.raises(ProbePlanError, match="does not equal the plan"):
        _probe(
            tmp_path, FIXTURE_PLAN, transport=transport, transport_max_bytes=1234,
        )
    assert sent == []
    assert not (tmp_path / "out").exists()


def test_oversized_response_is_refused_with_nothing_persisted(tmp_path):
    payload = _plan_payload()
    payload["max_metadata_bytes"] = 100  # below both fixture pages
    plan = _write_plan(tmp_path / "p.json", payload)
    result = _probe(tmp_path, plan)
    assert result.failure is not None
    assert result.failure.reason_code == "metadata_over_ceiling"
    assert result.manifest_path is None
    assert result.failure_receipt_path.is_file()


def test_fixture_transport_requires_an_explicit_positive_ceiling():
    for bad in (0, -1, "100", True):
        with pytest.raises(ProbePlanError):
            make_filing_index_fixture_replay_transport(FIXTURE_DIR, max_bytes=bad)


# --- fail-closed run outcomes ----------------------------------------------


def _static_transport(response: DocumentTransportResponse):
    return lambda url: response


def test_redirect_and_non_200_and_url_mismatch_fail_closed(tmp_path):
    ceiling = _ceiling_of(FIXTURE_PLAN)
    cases = {
        "redirect": DocumentTransportResponse(
            status_code=302, final_url="", content=b""),
        "notfound": DocumentTransportResponse(
            status_code=404, final_url="", content=b""),
        "mismatch": DocumentTransportResponse(
            status_code=200, final_url="https://www.sec.gov/other.htm",
            content=b"<html></html>"),
    }
    for name, response in cases.items():
        result = _probe(
            tmp_path, FIXTURE_PLAN, run_id=f"fail-{name}",
            transport=_static_transport(response), transport_max_bytes=ceiling,
        )
        assert result.failure is not None, name
        assert result.failure.reason_code == "metadata_http_failure", name
        assert result.manifest_path is None, name


def test_selection_refusals_reach_the_failure_receipt(tmp_path):
    ceiling = _ceiling_of(FIXTURE_PLAN)
    entries, _, _ = load_probe_plan(FIXTURE_PLAN)
    first_url = entries[0].url
    cases = {
        "no_primary_candidate": _page([("EX-21", "ex21.htm", "EX-21")]),
        "ambiguous_primary_candidate": _page(
            [("10-K", "a.htm", "10-K"), ("10-K", "b.htm", "10-K")]),
        "non_html_primary": _page([("10-K", "primary.pdf", "10-K")]),
    }
    for reason, page in cases.items():
        result = _probe(
            tmp_path, FIXTURE_PLAN, run_id=f"sel-{reason}",
            transport=_static_transport(
                DocumentTransportResponse(
                    status_code=200, final_url=first_url, content=page)
            ),
            transport_max_bytes=ceiling,
        )
        assert result.failure is not None, reason
        assert result.failure.reason_code == reason, reason
        assert result.manifest_path is None, reason
        assert result.failure_receipt_path.is_file(), reason


def test_unparseable_page_fails_closed(tmp_path):
    entries, _, _ = load_probe_plan(FIXTURE_PLAN)
    result = _probe(
        tmp_path, FIXTURE_PLAN, run_id="unparseable",
        transport=_static_transport(
            DocumentTransportResponse(
                status_code=200, final_url=entries[0].url,
                content=b"<html><body><p>no table here</p></body></html>")
        ),
    )
    assert result.failure.reason_code == "metadata_unparseable"
    assert result.manifest_path is None


def test_ground_truth_mismatch_fails_closed(tmp_path):
    payload = _plan_payload()
    payload["entries"][0]["expected_primary_document"] = "not-the-primary.htm"
    plan = _write_plan(tmp_path / "p.json", payload)
    result = _probe(tmp_path, plan, run_id="gtm")
    assert result.failure is not None
    assert result.failure.reason_code == "ground_truth_mismatch"
    assert result.manifest_path is None


# --- plan grammar -----------------------------------------------------------


def test_non_domestic_form_is_refused(tmp_path):
    payload = _plan_payload()
    payload["entries"][0]["form"] = "20-F"
    with pytest.raises(ProbePlanError, match="domestic-only"):
        load_probe_plan(_write_plan(tmp_path / "p.json", payload))


def test_repeated_accession_is_refused(tmp_path):
    payload = _plan_payload()
    payload["entries"].append(json.loads(json.dumps(payload["entries"][0])))
    with pytest.raises(ProbePlanError, match="repeated"):
        load_probe_plan(_write_plan(tmp_path / "p.json", payload))


def test_non_html_ground_truth_is_refused(tmp_path):
    payload = _plan_payload()
    payload["entries"][0]["expected_primary_document"] = "primary.pdf"
    with pytest.raises(ProbePlanError, match="HTML filename"):
        load_probe_plan(_write_plan(tmp_path / "p.json", payload))


def test_plan_base_url_cannot_redirect_requests(tmp_path):
    payload = _plan_payload()
    payload["base_url"] = "https://example.invalid/Archives/"
    with pytest.raises(ProbePlanError, match="base_url"):
        load_probe_plan(_write_plan(tmp_path / "p.json", payload))


# --- immutability -----------------------------------------------------------


def test_rerun_of_existing_run_id_is_refused(tmp_path):
    _probe(tmp_path, FIXTURE_PLAN, run_id="immutable")
    before = sorted(p.name for p in (tmp_path / "out" / "immutable").iterdir())
    with pytest.raises(FileExistsError):
        _probe(tmp_path, FIXTURE_PLAN, run_id="immutable")
    assert sorted(
        p.name for p in (tmp_path / "out" / "immutable").iterdir()
    ) == before


def test_dry_run_writes_nothing(tmp_path):
    result = _probe(tmp_path, FIXTURE_PLAN, dry_run=True)
    assert result.dry_run is True and result.run_dir is None
    assert len(result.entries) == 2
    assert not (tmp_path / "out").exists()


# --- committed live plan ----------------------------------------------------


def test_committed_live_plan_structure():
    entries, fields, _ = load_probe_plan(LIVE_PLAN)
    assert len(entries) == 3
    assert fields["max_metadata_bytes"] == 8388608
    assert [e.form for e in entries] == ["10-K", "10-K", "10-KT"]
    assert [e.expected_primary_document for e in entries] == [
        "air-20220531x10k.htm", "abt-20211231x10k.htm", "form10-kt.htm",
    ]
    assert [e.url for e in entries] == [
        "https://www.sec.gov/Archives/edgar/data/1750/"
        "000110465922081498/0001104659-22-081498-index.htm",
        "https://www.sec.gov/Archives/edgar/data/1800/"
        "000110465922025141/0001104659-22-025141-index.htm",
        "https://www.sec.gov/Archives/edgar/data/66600/"
        "000149315222010080/0001493152-22-010080-index.htm",
    ]


def test_committed_live_plan_pins_carrier_and_freeze_provenance():
    _, fields, _ = load_probe_plan(LIVE_PLAN)
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


def test_registry_carries_both_probe_schemas():
    registry = read_json(ROOT / "schemas" / "schema_version_manifest.json")
    assert registry["schemas"]["filing_index_probe_manifest"] == "0.1.0"
    assert registry["schemas"]["filing_index_probe_manifest_v2"] == "0.2.0"


# --- boundaries -------------------------------------------------------------


def test_module_has_no_network_dera_or_ingestion_dependency():
    source = (
        ROOT / "src" / "dynamic_ai_products" / "universe" / "filing_index_probe.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("import httpx", "requests", "frame_dera_validation",
                      "dera_acquisition", "ingestion"):
        assert forbidden not in source, forbidden


def test_index_json_is_never_requested(tmp_path):
    """The fallback is documented in prose but unreachable in behaviour.

    The module's docstring names ``index.json`` to record that it is a
    separately authorized fallback; what matters is that no code path can
    request it. Asserted against derived URLs and against every request the
    fixture run actually makes.
    """
    requested: list[str] = []

    def recording_transport(url):
        requested.append(url)
        return make_filing_index_fixture_replay_transport(
            FIXTURE_DIR, max_bytes=_ceiling_of(FIXTURE_PLAN)
        )(url)

    result = _probe(
        tmp_path, FIXTURE_PLAN, run_id="no-index-json",
        transport=recording_transport,
    )
    assert result.failure is None
    assert requested and all(url.endswith("-index.htm") for url in requested)
    assert all("index.json" not in url for url in requested)


def test_cli_probe_mode(tmp_path):
    import subprocess
    import sys

    completed = subprocess.run(
        [
            sys.executable, str(CLI),
            "--mode", "probe-filing-index",
            "--request-plan", str(FIXTURE_PLAN),
            "--replay-dir", str(FIXTURE_DIR),
            "--output-dir", str(tmp_path / "out"),
            "--run-id", "cli-probe",
        ],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["probes_resolved"] == 2
    assert payload["ground_truth_matches"] == 2
    assert payload["failure_reason_code"] is None


def test_cli_probe_mode_rejects_cross_mode_flags(tmp_path):
    import subprocess
    import sys

    completed = subprocess.run(
        [
            sys.executable, str(CLI),
            "--mode", "probe-filing-index",
            "--request-plan", str(FIXTURE_PLAN),
            "--replay-dir", str(FIXTURE_DIR),
            "--frame-manifest", str(FIXTURE_PLAN),
            "--output-dir", str(tmp_path / "out"),
            "--run-id", "cli-probe-bad",
        ],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode != 0
    assert "does not accept" in completed.stderr


# --- provenance-bound ground truth ------------------------------------------


def test_committed_live_plan_binds_ground_truth_to_local_sources():
    _, fields, _ = load_probe_plan(LIVE_PLAN)
    assert fields["provenance"]["canary_acquisition_manifest_sha256"] == (
        "9ada7a0d3e5b1311d046632f17350f492b4f6899d09811909f297a1713a6250d"
    )
    entries, _, _ = load_probe_plan(LIVE_PLAN)
    assert len({e.ground_truth_source_sha256 for e in entries}) == 3
    assert all(len(e.ground_truth_source_sha256) == 64 for e in entries)


PROVENANCE_HASH_KEYS = (
    "carrier_manifest_sha256",
    "freeze_record_sha256",
    "canary_acquisition_manifest_sha256",
)

MALFORMED_HASHES = (
    "A" * 64,                     # uppercase: not the canonical form
    "0" * 63,                     # one character short
    "0" * 65,                     # one character long
    "g" * 64,                     # right length, not hex
    "0" * 32 + "-" * 32,          # right length, punctuation
    " " + "0" * 63,               # leading whitespace
    12345,                        # not a string
    None,                         # null
    ["0" * 64],                   # wrong container
    {"sha256": "0" * 64},         # wrong container
)


@pytest.mark.parametrize("key", PROVENANCE_HASH_KEYS)
@pytest.mark.parametrize("bad", MALFORMED_HASHES)
def test_malformed_provenance_hash_is_refused_at_plan_load(tmp_path, key, bad):
    payload = _plan_payload()
    payload["provenance"][key] = bad
    with pytest.raises(ProbePlanError, match=key):
        load_probe_plan(_write_plan(tmp_path / "p.json", payload))


@pytest.mark.parametrize("key", PROVENANCE_HASH_KEYS)
def test_malformed_provenance_hash_makes_zero_requests(tmp_path, key):
    """The refusal is a preflight, not a post-hoc schema failure."""
    payload = _plan_payload()
    payload["provenance"][key] = "A" * 64  # uppercase: schema-shaped but not canonical
    plan = _write_plan(tmp_path / "p.json", payload)
    requested: list[str] = []

    def recording_transport(url):
        requested.append(url)
        return DocumentTransportResponse(status_code=200, final_url=url, content=b"")

    with pytest.raises(ProbePlanError, match=key):
        _probe(tmp_path, plan, run_id=f"pre-{key}", transport=recording_transport)
    assert requested == []
    assert not (tmp_path / "out").exists()


def test_canonical_provenance_hashes_are_accepted():
    for plan in (FIXTURE_PLAN, LIVE_PLAN):
        _, fields, _ = load_probe_plan(plan)
        for key in PROVENANCE_HASH_KEYS:
            value = fields["provenance"][key]
            assert len(value) == 64 and value == value.lower()
            assert all(c in "0123456789abcdef" for c in value)


def test_plan_without_canary_provenance_is_refused(tmp_path):
    payload = _plan_payload()
    del payload["provenance"]["canary_acquisition_manifest_sha256"]
    with pytest.raises(ProbePlanError, match="canary_acquisition_manifest_sha256"):
        load_probe_plan(_write_plan(tmp_path / "p.json", payload))


def test_entry_without_ground_truth_source_hash_is_refused(tmp_path):
    payload = _plan_payload()
    del payload["entries"][0]["ground_truth_source_sha256"]
    with pytest.raises(ProbePlanError, match="ground_truth_source_sha256"):
        load_probe_plan(_write_plan(tmp_path / "p.json", payload))


@pytest.mark.parametrize("bad", MALFORMED_HASHES)
def test_malformed_entry_source_hash_is_refused_at_plan_load(tmp_path, bad):
    payload = _plan_payload()
    payload["entries"][0]["ground_truth_source_sha256"] = bad
    with pytest.raises(ProbePlanError, match="ground_truth_source_sha256"):
        load_probe_plan(_write_plan(tmp_path / "p.json", payload))


def test_entry_source_hash_is_validated_not_normalized(tmp_path):
    """Uppercase and padded digests are rejected, never quietly repaired.

    Normalizing here would accept exactly the values the provenance hashes
    refuse, and would let a plan whose recorded evidence is non-canonical
    reach the network.
    """
    # A digest carrying hex letters, so .upper() is a real difference: the
    # fixture plan's all-zero placeholder would make an uppercase test vacuous.
    canonical = "abcdef" + "0" * 58
    assert canonical.upper() != canonical

    payload = _plan_payload()
    payload["entries"][0]["ground_truth_source_sha256"] = canonical
    entries, _, _ = load_probe_plan(_write_plan(tmp_path / "ok.json", payload))
    # Accepted and carried through byte-for-byte, with no repair applied.
    assert entries[0].ground_truth_source_sha256 == canonical

    for variant in (canonical.upper(), f" {canonical}", f"{canonical} ",
                    f"\t{canonical}\n", canonical.capitalize()):
        payload = _plan_payload()
        payload["entries"][0]["ground_truth_source_sha256"] = variant
        with pytest.raises(ProbePlanError, match="ground_truth_source_sha256"):
            load_probe_plan(_write_plan(tmp_path / "p.json", payload))


def test_uppercase_entry_source_hash_makes_zero_requests(tmp_path):
    payload = _plan_payload()
    payload["entries"][0]["ground_truth_source_sha256"] = "A" * 64
    plan = _write_plan(tmp_path / "p.json", payload)
    requested: list[str] = []

    def recording_transport(url):
        requested.append(url)
        return DocumentTransportResponse(status_code=200, final_url=url, content=b"")

    with pytest.raises(ProbePlanError, match="ground_truth_source_sha256"):
        _probe(tmp_path, plan, run_id="pre-entry-hash",
               transport=recording_transport)
    assert requested == []
    assert not (tmp_path / "out").exists()


CANARY_RUN = (
    ROOT / "data" / "runs" / "baseline-document-canary"
    / "baseline-doc-canary-frame-v1-20260816"
)


@pytest.mark.skipif(
    not (CANARY_RUN / "baseline_document_acquisition_manifest.json").exists(),
    reason="local submission-canary artifacts absent; ground truth not re-derivable",
)
def test_live_plan_ground_truth_is_rederivable_from_local_submissions():
    """Read-only: re-derive both the source hash and the primary filename.

    The plan asserts that a given full submission yields a given primary
    document. When the canary artifacts are present this recomputes both from
    the bytes — the source SHA-256, and the form-matched filename read out of
    the submission's DOCUMENT blocks — instead of trusting the assertion. The
    normal suite never depends on these gitignored artifacts.
    """
    import re

    entries, fields, _ = load_probe_plan(LIVE_PLAN)
    manifest_path = CANARY_RUN / "baseline_document_acquisition_manifest.json"
    assert sha256_file(manifest_path) == (
        fields["provenance"]["canary_acquisition_manifest_sha256"]
    ), "the plan cites a different canary acquisition manifest"

    document_block = re.compile(rb"<DOCUMENT>(.*?)</DOCUMENT>", re.S)
    type_field = re.compile(rb"<TYPE>([^\r\n<]+)")
    filename_field = re.compile(rb"<FILENAME>([^\r\n<]+)")

    for entry in entries:
        source = CANARY_RUN / f"{entry.accession}.txt"
        assert source.is_file(), source
        assert sha256_file(source) == entry.ground_truth_source_sha256, (
            f"{entry.accession}: the plan's ground_truth_source_sha256 does "
            "not match the local submission"
        )
        matches = []
        for block in document_block.findall(source.read_bytes()):
            declared, name = type_field.search(block), filename_field.search(block)
            if declared and name and declared.group(1).decode().strip() == entry.form:
                matches.append(name.group(1).decode().strip())
        assert matches == [entry.expected_primary_document], (
            f"{entry.accession}: submission yields {matches}, plan expects "
            f"{entry.expected_primary_document!r}"
        )


# --- non-tautological completeness ------------------------------------------


def test_planned_count_is_sourced_from_the_plan_not_the_observations(tmp_path):
    manifest = read_json(_probe(tmp_path, FIXTURE_PLAN).manifest_path)
    entries, _, _ = load_probe_plan(FIXTURE_PLAN)
    assert manifest["counts"]["planned_probes"] == len(entries) == 2
    assert (
        manifest["counts"]["planned_probes"]
        == manifest["counts"]["probes_resolved"]
        == manifest["counts"]["ground_truth_matches"]
    )
    assert manifest["reconciliation"][
        "planned = resolved = ground-truth matches"
    ] is True


def test_manifest_is_refused_when_the_completeness_identity_fails(tmp_path):
    """A short observation list can never be written as a complete run."""
    import dynamic_ai_products.universe.filing_index_probe as fip
    from dynamic_ai_products.universe.frame_acquisition import (
        FIXTURE_REPLAY_TRANSPORT_IDENTITY,
    )

    entries, fields, _ = load_probe_plan(FIXTURE_PLAN)
    one_observation = [
        fip.ProbeObservation(
            accession=entries[0].accession,
            form=entries[0].form,
            directory_cik=entries[0].directory_cik,
            url=entries[0].url,
            final_url=entries[0].url,
            status_code=200,
            response_byte_length=10,
            response_sha256="a" * 64,
            declared_content_length=10,
            candidates=[
                {"document": "x.htm", "document_type": "10-K", "reported_size": 1}
            ],
            selected_document=entries[0].expected_primary_document,
            expected_primary_document=entries[0].expected_primary_document,
            ground_truth_source_sha256=entries[0].ground_truth_source_sha256,
            ground_truth_match=True,
            retrieved_at=FIXED_CLOCK(),
        )
    ]
    # Two planned, one observed: the identity is false and no manifest exists.
    with pytest.raises(ValueError, match="reconciliation failed"):
        fip.build_probe_manifest(
            repo_root=ROOT,
            run_id="short",
            plan_sha256="b" * 64,
            fields=fields,
            planned_count=2,
            observations=one_observation,
            run_timestamp=FIXED_CLOCK(),
            transport_identity=FIXTURE_REPLAY_TRANSPORT_IDENTITY,
        )


# --- href-versus-rendered-text selection (ADR-090 canary finding) ------------


LIVE_PRIMARY = "air-20220531x10k.htm"
LIVE_DIR = "/Archives/edgar/data/1750/000110465922081498"


def test_ixbrl_badge_in_rendered_text_does_not_defeat_selection():
    """Reproduces the exact condition that failed the first live probe.

    The receipt recorded one 10-K row whose visible cell read
    'air-20220531x10k.htm iXBRL'. The filename must come from the link
    target, so the badge is presentation the selector never sees.
    """
    page = _page([
        ("10-K", LIVE_PRIMARY, "10-K",
         {"href": f"{LIVE_DIR}/{LIVE_PRIMARY}", "badge": True}),
    ])
    assert b"iXBRL" in page
    rows = parse_document_format_table(page)
    assert rows[0].document == LIVE_PRIMARY
    assert "iXBRL" not in rows[0].document
    selected, refusal = select_primary_document(rows, "10-K")
    assert refusal is None
    assert selected.document == LIVE_PRIMARY


def test_inline_xbrl_viewer_href_resolves_to_the_document():
    """SEC links iXBRL documents through /ix?doc=…; the path tail is 'ix'."""
    page = _page([
        ("10-K", LIVE_PRIMARY, "10-K",
         {"href": f"/ix?doc={LIVE_DIR}/{LIVE_PRIMARY}", "badge": True}),
    ])
    rows = parse_document_format_table(page)
    assert rows[0].document == LIVE_PRIMARY
    assert rows[0].href.startswith("/ix?doc=")
    assert select_primary_document(rows, "10-K")[0].document == LIVE_PRIMARY


def test_href_basename_helper_handles_both_link_shapes():
    from dynamic_ai_products.universe.filing_index_probe import (
        href_document_basename,
    )

    assert href_document_basename(f"{LIVE_DIR}/{LIVE_PRIMARY}") == LIVE_PRIMARY
    assert href_document_basename(
        f"/ix?doc={LIVE_DIR}/{LIVE_PRIMARY}"
    ) == LIVE_PRIMARY
    assert href_document_basename(
        f"https://www.sec.gov{LIVE_DIR}/{LIVE_PRIMARY}"
    ) == LIVE_PRIMARY
    for unusable in ("", "   ", "/", "#", None, 12345, "?doc="):
        assert href_document_basename(unusable) is None, unusable


def test_committed_fixture_carries_the_ixbrl_badge_and_viewer_link():
    """The live condition is permanently exercised by the committed gold."""
    raw = (FIXTURE_DIR / "0009000001-22-000001-index.htm").read_bytes()
    assert b"iXBRL" in raw and b"/ix?doc=" in raw
    rows = parse_document_format_table(raw)
    primary = [r for r in rows if r.document_type == "10-K"]
    assert len(primary) == 1
    assert primary[0].document == "synth-20211231x10k.htm"
    assert primary[0].href.startswith("/ix?doc=")


# --- negative: unusable link, and misleading rendered text ------------------


def test_document_cell_without_a_link_is_unparseable():
    page = _page([("10-K", "primary.htm", "10-K", {"href": ""})])
    with pytest.raises(ProbePlanError, match="no usable document link"):
        parse_document_format_table(page)


@pytest.mark.parametrize("href", ["#", "   ", "/", "?doc="])
def test_document_cell_with_an_unusable_href_is_unparseable(href):
    page = _page([("10-K", "primary.htm", "10-K", {"href": href})])
    with pytest.raises(ProbePlanError, match="no usable document link"):
        parse_document_format_table(page)


def test_html_looking_rendered_text_cannot_rescue_a_non_html_href():
    """The visible text says .htm; the link target is a PDF. The link wins."""
    page = _page([
        ("10-K", "primary.pdf", "10-K",
         {"href": f"{LIVE_DIR}/primary.pdf", "text": "primary.htm iXBRL"}),
    ])
    rows = parse_document_format_table(page)
    assert rows[0].document == "primary.pdf"
    assert select_primary_document(rows, "10-K") == (None, "non_html_primary")


def test_rendered_text_naming_another_document_is_ignored():
    page = _page([
        ("10-K", "real-10k.htm", "10-K",
         {"href": f"{LIVE_DIR}/real-10k.htm", "text": "decoy-10k.htm"}),
    ])
    rows = parse_document_format_table(page)
    assert rows[0].document == "real-10k.htm"


def test_badge_bearing_expected_filename_is_refused_at_plan_load(tmp_path):
    """Ground truth is a filename, so rendered text cannot enter the plan.

    A badge-bearing expectation is refused before any request, which is
    stricter than letting it reach a run-time ground_truth_mismatch.
    """
    payload = _plan_payload()
    payload["entries"][0]["expected_primary_document"] = (
        "synth-20211231x10k.htm iXBRL"
    )
    with pytest.raises(ProbePlanError, match="HTML filename"):
        load_probe_plan(_write_plan(tmp_path / "p.json", payload))


def test_ground_truth_compares_against_the_href_derived_basename(tmp_path):
    """The comparison operand is the link-derived name, not rendered text.

    A one-entry plan is served a page whose visible cell carries the iXBRL
    badge. The run succeeds only if the comparison used the clean href
    basename; comparing rendered text would raise ground_truth_mismatch.
    """
    payload = _plan_payload()
    payload["entries"] = payload["entries"][:1]
    plan = _write_plan(tmp_path / "one.json", payload)
    expected = payload["entries"][0]["expected_primary_document"]
    page = _page([
        ("10-K", expected, "10-K",
         {"href": f"/ix?doc={LIVE_DIR}/{expected}", "badge": True}),
    ])
    result = _probe(
        tmp_path, plan, run_id="href-ground-truth",
        transport=lambda url: DocumentTransportResponse(
            status_code=200, final_url=url, content=page
        ),
    )
    assert result.failure is None
    manifest = read_json(result.manifest_path)
    assert manifest["observations"][0]["selected_document"] == expected
    assert "iXBRL" not in manifest["observations"][0]["selected_document"]
    assert manifest["counts"] == {
        "planned_probes": 1, "probes_resolved": 1, "ground_truth_matches": 1
    }


# --- href parsing is structural, not substring matching ---------------------


def _basename(href):
    from dynamic_ai_products.universe.filing_index_probe import (
        href_document_basename,
    )

    return href_document_basename(href)


def test_query_doc_parameter_never_overrides_a_direct_archive_path():
    """A direct link's query is ignored; its parsed path decides."""
    assert _basename(f"{LIVE_DIR}/actual.htm?doc=wrong.htm") == "actual.htm"
    assert _basename(f"{LIVE_DIR}/actual.htm#doc=wrong.htm") == "actual.htm"
    assert _basename(
        f"{LIVE_DIR}/actual.htm?doc=wrong.htm&x=1#frag"
    ) == "actual.htm"


@pytest.mark.parametrize(
    "path",
    ["/ix/", "/notix", "/ixviewer", "/other/ix", "/IX/", "/ix/viewer"],
)
def test_only_the_exact_ix_path_is_the_viewer_endpoint(path):
    """A near-miss path is an ordinary link, and so fails the archive rule.

    Nothing resolves through the viewer parameter here: the value must never
    leak out of a path that is not exactly '/ix'.
    """
    viewer_target = f"{LIVE_DIR}/actual.htm"
    got = _basename(f"{path}?doc={viewer_target}")
    assert got != "actual.htm", path
    assert got is None, path


def test_the_exact_ix_endpoint_still_resolves():
    viewer_target = f"{LIVE_DIR}/actual.htm"
    assert _basename(f"/ix?doc={viewer_target}") == "actual.htm"
    assert _basename(f"https://www.sec.gov/ix?doc={viewer_target}") == (
        "actual.htm"
    )
    assert _basename(f"https://sec.gov/ix?doc={viewer_target}") == "actual.htm"


def test_trailing_slash_viewer_path_does_not_resolve_via_doc():
    """Direct regression: '/ix/' is not the viewer endpoint."""
    assert _basename(f"/ix/?doc={LIVE_DIR}/actual.htm") is None


# --- direct-archive-link contract ------------------------------------------


def test_direct_link_must_address_the_sec_archive():
    assert _basename(f"{LIVE_DIR}/actual.htm") == "actual.htm"
    assert _basename(f"https://www.sec.gov{LIVE_DIR}/actual.htm") == "actual.htm"
    assert _basename(f"https://sec.gov{LIVE_DIR}/actual.htm") == "actual.htm"


@pytest.mark.parametrize(
    "href",
    [
        "https://example.invalid/Archives/edgar/data/1750/x/actual.htm",
        "https://evil.example.com/Archives/actual.htm",
        "http://sec.gov.example.invalid/Archives/actual.htm",
    ],
)
def test_direct_link_on_another_host_is_refused(href):
    """An external host is refused even with an archive-shaped path."""
    assert _basename(href) is None


@pytest.mark.parametrize(
    "href",
    [
        "/cgi-bin/actual.htm",
        "https://www.sec.gov/cgi-bin/browse-edgar/actual.htm",
        "/other/actual.htm",
        "/actual.htm",
    ],
)
def test_direct_link_outside_the_archive_is_refused(href):
    """An SEC-host path outside /Archives/ is not a filing document."""
    assert _basename(href) is None


def test_offsite_link_is_refused_even_when_its_basename_is_the_expected_name():
    """The basename matching ground truth cannot rescue a bad source."""
    for href in (
        f"https://example.invalid{LIVE_DIR}/{LIVE_PRIMARY}",
        f"https://www.sec.gov/cgi-bin/{LIVE_PRIMARY}",
    ):
        assert _basename(href) is None, href


def test_viewer_target_on_another_host_is_refused():
    assert _basename(
        f"/ix?doc=https://example.invalid{LIVE_DIR}/{LIVE_PRIMARY}"
    ) is None


@pytest.mark.parametrize(
    "href",
    [
        "https://example.invalid/Archives/edgar/data/1750/x/air.htm",
        "https://www.sec.gov/cgi-bin/air.htm",
        "/ix/?doc=/Archives/edgar/data/1750/x/air.htm",
    ],
)
def test_table_level_refusal_for_out_of_contract_links(href):
    """Parser-level refusals surface as metadata_unparseable, never a pick."""
    page = _page([("10-K", "air.htm", "10-K", {"href": href})])
    with pytest.raises(ProbePlanError, match="no usable document link"):
        parse_document_format_table(page)


@pytest.mark.parametrize(
    "href",
    [
        "javascript:actual.htm",
        "javascript:void(0)",
        "JavaScript:actual.htm",
        "data:text/html,actual.htm",
        "mailto:someone@example.invalid/actual.htm",
    ],
)
def test_unsupported_schemes_are_refused(href):
    assert _basename(href) is None


@pytest.mark.parametrize(
    "query",
    [
        "",                                    # /ix with no doc at all
        "doc=",                                # blank
        "doc=%20",                             # whitespace only
        "doc=a.htm&doc=b.htm",                 # duplicated, ambiguous
        "doc=/notarchive/actual.htm",          # outside the archive
        "doc=javascript:actual.htm",           # unsupported target scheme
        "other=/Archives/x/actual.htm",        # wrong parameter name
    ],
)
def test_viewer_link_refuses_unusable_doc_parameters(query):
    assert _basename(f"/ix?{query}") is None


def test_viewer_and_direct_forms_both_survive_in_the_document_table():
    """Both link shapes still select correctly through the real parser."""
    for href in (f"{LIVE_DIR}/{LIVE_PRIMARY}",
                 f"/ix?doc={LIVE_DIR}/{LIVE_PRIMARY}",
                 f"https://www.sec.gov{LIVE_DIR}/{LIVE_PRIMARY}"):
        rows = parse_document_format_table(
            _page([("10-K", LIVE_PRIMARY, "10-K", {"href": href, "badge": True})])
        )
        assert rows[0].document == LIVE_PRIMARY, href
        assert select_primary_document(rows, "10-K")[0].document == LIVE_PRIMARY


def test_javascript_href_row_is_unparseable_not_silently_named():
    page = _page([("10-K", "actual.htm", "10-K",
                   {"href": "javascript:actual.htm"})])
    with pytest.raises(ProbePlanError, match="no usable document link"):
        parse_document_format_table(page)


def test_viewer_row_with_duplicate_doc_parameters_is_unparseable():
    page = _page([("10-K", LIVE_PRIMARY, "10-K",
                   {"href": f"/ix?doc={LIVE_DIR}/a.htm&doc={LIVE_DIR}/b.htm"})])
    with pytest.raises(ProbePlanError, match="no usable document link"):
        parse_document_format_table(page)
