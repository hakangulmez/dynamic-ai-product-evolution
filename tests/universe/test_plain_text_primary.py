"""Plain-text primary admission and its successors (ADR-097) — fully offline.

Every run replays local synthetic documents through injected fixture
transports into a temporary directory; nothing fetches, no model is called,
and no test reads or writes ``data/runs``.

These pin the three things the text route rests on: admission is positive
evidence decided before any byte is retained, the Item 1 finder works on lines
rather than markup, and the admission evidence is written once at acquisition
and **forwarded** rather than re-derived downstream.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.ingestion.baseline_packet import (
    BUNDLE_CONTRACT,
    BUNDLE_CONTRACT_V2,
    PACKET_CONTRACT,
    PACKET_CONTRACT_V2,
    build_packet,
    load_bundle,
    run_baseline_packet_build,
)
from dynamic_ai_products.ingestion.normalize import (
    IngestionError,
    find_item_one_span_text,
)
from dynamic_ai_products.universe.filing_index_probe import (
    make_filing_index_fixture_replay_transport,
    parse_document_format_table,
    select_primary_document,
)
from dynamic_ai_products.universe.io_utils import read_json
from dynamic_ai_products.sec_document_transport import (
    SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY,
)
from dynamic_ai_products.universe.acquisition_queue import (
    ShardPlan,
    _bind_shard_manifest,
    canonical_plan_bytes,
)
from dynamic_ai_products.universe.plain_text_primary import (
    ADMISSION_BARE_TEXT,
    ADMISSION_SINGLE_SGML,
    REASON_EMBEDDED_AMBIGUOUS,
    REASON_MULTI_DOCUMENT,
    REASON_TYPE_MISMATCH,
    REASON_UNSUPPORTED_STRUCTURE,
    inspect_plain_text_primary,
    is_plain_text_document,
)
from dynamic_ai_products.universe.primary_document_acquisition import (
    ACQUISITION_MANIFEST_FILENAME,
    BUNDLE_MANIFEST_FILENAME,
    FAILURE_RECEIPT_FILENAME,
    PLAN_CONTRACT_V3,
    PrimaryDocumentPlanError,
    load_request_plan,
    local_filename_for,
    make_primary_document_fixture_replay_transport,
    run_primary_document_acquisition,
)

ROOT = Path(__file__).resolve().parents[2]
TEXT_FIXTURES = ROOT / "evals" / "fixtures" / "plain_text_primary"
REPLAY = ROOT / "evals" / "fixtures" / "primary_documents"
EXPECTED = read_json(TEXT_FIXTURES / "expected_packets.json")

BUNDLE_V1_SCHEMA = ROOT / "schemas" / "baseline_primary_document_bundle.schema.json"
BUNDLE_V2_SCHEMA = (
    ROOT / "schemas" / "baseline_primary_document_bundle.v2.schema.json"
)
PACKET_V1_SCHEMA = ROOT / "schemas" / "universe_baseline_packet.schema.json"
PACKET_V2_SCHEMA = ROOT / "schemas" / "universe_baseline_packet.v2.schema.json"
ACQ_V5_SCHEMA = (
    ROOT / "schemas" / "primary_document_acquisition_manifest.v5.schema.json"
)
ACQ_V6_SCHEMA = (
    ROOT / "schemas" / "primary_document_acquisition_manifest.v6.schema.json"
)

METADATA_CEILING = 8388608
DOCUMENT_CEILING = 268435456
TEXT_ACCESSION = "0009200009-22-000009"
CLOCK = lambda: datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc)  # noqa: E731


def _errs(schema_path: Path, payload: dict) -> list:
    return list(Draft202012Validator(read_json(schema_path)).iter_errors(payload))


def _text_plan(tmp_path: Path, **overrides) -> Path:
    payload = json.loads((REPLAY / "request_plan.json").read_text())
    payload.update({
        "plan_contract": PLAN_CONTRACT_V3,
        "max_retained_bytes": 10_000_000,
        "admit_plain_text": True,
        "documents": [{
            "accession": TEXT_ACCESSION, "form": "10-K",
            "directory_cik": "0009200009",
            "carrier_rows": [{"stratum": "domestic", "cik": "0009200009",
                              "baseline_filing_date": "2022-03-01"}],
        }],
    })
    payload.update(overrides)
    path = tmp_path / "text-plan.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


def _acquire(tmp_path: Path, plan: Path, run_id: str = "text-acq", recorder=None):
    index = make_filing_index_fixture_replay_transport(
        REPLAY, max_bytes=METADATA_CEILING)
    primary = make_primary_document_fixture_replay_transport(
        REPLAY, max_bytes=DOCUMENT_CEILING)
    if recorder is not None:
        index_inner, primary_inner = index, primary

        def index(url):  # noqa: F811
            recorder.append(url)
            return index_inner(url)

        def primary(url):  # noqa: F811
            recorder.append(url)
            return primary_inner(url)

    return run_primary_document_acquisition(
        repo_root=ROOT, request_plan_path=plan, output_dir=tmp_path / "out",
        run_id=run_id, metadata_transport=index, primary_transport=primary,
        metadata_transport_max_bytes=METADATA_CEILING,
        primary_transport_max_bytes=DOCUMENT_CEILING, clock=CLOCK,
    )


# --- structural admission ------------------------------------------------------


def test_the_observed_shape_is_admitted_as_a_single_sgml_document():
    raw = (TEXT_FIXTURES / "text-10k-item1a.txt").read_bytes()
    result = inspect_plain_text_primary(
        raw, form="10-K", selected_document="10k2021.txt")
    assert result.admitted is True
    assert result.admission == ADMISSION_SINGLE_SGML
    assert result.document_blocks == 1
    assert result.declared_type == "10-K"
    assert result.declared_filename == "10k2021.txt"


def test_a_multi_document_submission_is_refused():
    raw = (TEXT_FIXTURES / "text-multi-document-submission.txt").read_bytes()
    result = inspect_plain_text_primary(
        raw, form="10-K", selected_document="10k2021.txt")
    assert result.admitted is False
    assert result.reason_code == REASON_MULTI_DOCUMENT
    assert result.document_blocks == 2
    assert "not a standalone annual report" in result.detail


def test_two_blocks_declaring_the_form_are_ambiguous_not_merely_multiple():
    raw = (
        b"<DOCUMENT>\n<TYPE>10-K\n<FILENAME>a.txt\n<TEXT>\nx\n</TEXT>\n</DOCUMENT>\n"
        b"<DOCUMENT>\n<TYPE>10-K\n<FILENAME>b.txt\n<TEXT>\ny\n</TEXT>\n</DOCUMENT>\n"
    )
    result = inspect_plain_text_primary(raw, form="10-K", selected_document="a.txt")
    assert result.reason_code == REASON_EMBEDDED_AMBIGUOUS
    assert "no evidence names the annual report" in result.detail


def test_a_single_block_of_the_wrong_type_is_refused():
    raw = b"<DOCUMENT>\n<TYPE>EX-21.1\n<FILENAME>a.txt\n<TEXT>\nx\n</TEXT>\n</DOCUMENT>\n"
    result = inspect_plain_text_primary(raw, form="10-K", selected_document="a.txt")
    assert result.reason_code == REASON_TYPE_MISMATCH
    assert result.declared_type == "EX-21.1"


def test_a_block_naming_another_file_is_refused():
    raw = b"<DOCUMENT>\n<TYPE>10-K\n<FILENAME>other.txt\n<TEXT>\nx\n</TEXT>\n</DOCUMENT>\n"
    result = inspect_plain_text_primary(raw, form="10-K", selected_document="a.txt")
    assert result.reason_code == REASON_UNSUPPORTED_STRUCTURE


def test_bare_text_is_admitted_only_on_positive_evidence():
    raw = (TEXT_FIXTURES / "text-bare-no-wrapper.txt").read_bytes()
    result = inspect_plain_text_primary(
        raw, form="10-K", selected_document="bare2021.txt")
    assert result.admitted is True
    assert result.admission == ADMISSION_BARE_TEXT
    assert result.document_blocks == 0
    assert result.declared_type is None and result.declared_filename is None


@pytest.mark.parametrize("raw,missing", [
    (b"Some newsletter text.\n\nItem 1. Business.\n\nWe do things.\n", "FORM line"),
    (b"FORM 10-K\n\nA cover page and nothing else follows.\n", "Item 1"),
    (b"see FORM 10-K for details\n\nItem 1. Business.\n\nx\n", "line-start FORM"),
])
def test_absence_of_a_wrapper_admits_nothing_by_itself(raw, missing):
    result = inspect_plain_text_primary(
        raw, form="10-K", selected_document="a.txt")
    assert result.admitted is False, missing
    assert result.reason_code == REASON_UNSUPPORTED_STRUCTURE


def test_the_form_line_must_match_the_planned_form():
    raw = b"FORM 10-KT\n\nItem 1. Business.\n\nx\n"
    assert not inspect_plain_text_primary(
        raw, form="10-K", selected_document="a.txt").admitted
    assert inspect_plain_text_primary(
        raw, form="10-KT", selected_document="a.txt").admitted


def test_is_plain_text_document():
    assert is_plain_text_document("10k2021.txt")
    assert is_plain_text_document("A.TXT")
    assert not is_plain_text_document("a.htm")


# --- the text span finder ------------------------------------------------------


@pytest.mark.parametrize("name,kind", [
    ("text-10k-item1a.txt", "item_1a_risk_factors"),
    ("text-10kt-item1b.txt", "item_1b_unresolved_staff_comments"),
    ("text-item2-fallback.txt", "item_2_properties"),
])
def test_end_boundary_priority_is_preserved_for_text(name, kind):
    raw = (TEXT_FIXTURES / name).read_bytes()
    start, end, boundary = find_item_one_span_text(raw)
    assert boundary == kind
    assert start < end
    assert b"Item 1." in raw[start:end]


def test_an_inline_item_1a_reference_is_not_a_boundary():
    """The measured HTML failure mode, reproduced in text form."""
    raw = (TEXT_FIXTURES / "text-inline-1a-reference.txt").read_bytes()
    start, end, boundary = find_item_one_span_text(raw)
    assert boundary == "item_2_properties"
    span = raw[start:end]
    assert b"See Item 1A. Risk Factors" in span, "the span must not be truncated"


def test_duplicate_line_start_boundaries_refuse():
    raw = (TEXT_FIXTURES / "text-duplicate-boundaries.txt").read_bytes()
    with pytest.raises(IngestionError) as raised:
        find_item_one_span_text(raw)
    assert raised.value.reason_code == "ambiguous_end_boundary"


def test_a_text_document_without_item_one_refuses():
    raw = (TEXT_FIXTURES / "text-no-item-one.txt").read_bytes()
    with pytest.raises(IngestionError) as raised:
        find_item_one_span_text(raw)
    assert raised.value.reason_code == "item_span_not_found"


def test_toc_only_records_the_preserved_adr_091_limitation():
    """Measured, not asserted: a contents entry with nothing later to prefer.

    The last-qualifying-match rule defeats a table of contents only when a
    real body heading follows it. When the contents entry is the only
    qualifying match, the finder takes it and the span is degenerate. That is
    the ADR-091 limitation carried forward, not a new refusal.
    """
    raw = (TEXT_FIXTURES / "text-toc-only.txt").read_bytes()
    start, end, boundary = find_item_one_span_text(raw)
    assert boundary == "item_1a_risk_factors"
    span = raw[start:end]
    assert b"....." in span, "the span is the contents line, not a body section"
    assert len(span) < 120, "a degenerate span, recorded rather than refused"


def test_the_html_finders_are_untouched():
    import inspect

    from dynamic_ai_products.ingestion import normalize

    for name in ("find_item_one_span", "find_item_one_span_v2"):
        source = inspect.getsource(getattr(normalize, name))
        assert "_starts_a_text_line" not in source
        assert "_starts_a_block" in source


# --- selection -----------------------------------------------------------------


def test_the_text_row_is_selected_only_when_the_plan_admits_it():
    raw = (REPLAY / f"{TEXT_ACCESSION}-index.htm").read_bytes()
    rows = parse_document_format_table(raw)
    assert select_primary_document(rows, "10-K") == (None, "non_html_primary")
    selected, refusal = select_primary_document(
        rows, "10-K", admit_plain_text=True)
    assert refusal is None
    assert selected.document == "10k2021.txt"


def test_a_v02_plan_may_not_declare_admit_plain_text(tmp_path):
    plan = _text_plan(tmp_path, plan_contract="primary_document_request_plan@0.2.0")
    with pytest.raises(PrimaryDocumentPlanError, match="is a .*0.3.0 field"):
        load_request_plan(plan)


def test_a_v03_plan_must_declare_admit_plain_text_true(tmp_path):
    for value in (None, False, "true", 1):
        payload = json.loads(_text_plan(tmp_path).read_text())
        if value is None:
            payload.pop("admit_plain_text")
        else:
            payload["admit_plain_text"] = value
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(payload, indent=2))
        with pytest.raises(PrimaryDocumentPlanError, match="exactly"):
            load_request_plan(path)


def test_a_v03_plan_still_requires_its_budget(tmp_path):
    payload = json.loads(_text_plan(tmp_path).read_text())
    del payload["max_retained_bytes"]
    path = tmp_path / "nobudget.json"
    path.write_text(json.dumps(payload, indent=2))
    with pytest.raises(PrimaryDocumentPlanError, match="requires max_retained_bytes"):
        load_request_plan(path)


def test_the_stored_name_tracks_the_representation():
    assert local_filename_for("0009200009-22-000009") == (
        "primary-000920000922000009.html")
    assert local_filename_for("0009200009-22-000009", "plain_text") == (
        "primary-000920000922000009.txt")


# --- acquisition end to end ----------------------------------------------------


def test_text_acquisition_stores_raw_bytes_unconverted(tmp_path):
    requested: list[str] = []
    result = _acquire(tmp_path, _text_plan(tmp_path), recorder=requested)
    assert len(requested) == 2
    assert requested[1].endswith("10k2021.txt")
    stored = sorted(p.name for p in result.run_dir.iterdir()
                    if p.suffix in (".txt", ".html"))
    assert stored == ["primary-000920000922000009.txt"]
    on_disk = (result.run_dir / stored[0]).read_bytes()
    assert on_disk == (REPLAY / "10k2021.txt").read_bytes(), "bytes unconverted"
    assert sha256(on_disk).hexdigest() == result.acquired[0].source_sha256


def test_text_acquisition_writes_the_v2_bundle_and_v6_manifest(tmp_path):
    result = _acquire(tmp_path, _text_plan(tmp_path))
    bundle = read_json(result.run_dir / BUNDLE_MANIFEST_FILENAME)
    manifest = read_json(result.run_dir / ACQUISITION_MANIFEST_FILENAME)
    assert bundle["bundle_contract"] == BUNDLE_CONTRACT_V2
    assert manifest["emitted_bundle_contract"] == BUNDLE_CONTRACT_V2
    assert manifest["plan_contract"] == PLAN_CONTRACT_V3
    assert set(manifest["schema_versions"]) == {
        "primary_document_acquisition_manifest_v6"
    }
    assert _errs(BUNDLE_V2_SCHEMA, bundle) == []
    assert _errs(BUNDLE_V1_SCHEMA, bundle), "a v0.2 bundle is not a v0.1 one"
    assert _errs(ACQ_V6_SCHEMA, manifest) == []
    assert _errs(ACQ_V5_SCHEMA, manifest), "a v0.6 manifest is not a v0.5 one"


def test_admission_evidence_is_written_to_both_records(tmp_path):
    result = _acquire(tmp_path, _text_plan(tmp_path))
    document = read_json(result.run_dir / BUNDLE_MANIFEST_FILENAME)["documents"][0]
    acquisition = read_json(
        result.run_dir / ACQUISITION_MANIFEST_FILENAME)["acquisitions"][0]
    for field in ("representation", "admission", "document_blocks",
                  "declared_type", "declared_filename"):
        assert document[field] == acquisition[field], field
    assert document["representation"] == "plain_text"
    assert document["admission"] == ADMISSION_SINGLE_SGML
    assert document["document_blocks"] == 1


def test_a_structurally_rejected_text_file_is_never_retained(tmp_path):
    """Admission runs before write_bytes_once, so nothing lands on disk."""
    replay = tmp_path / "replay"
    replay.mkdir()
    for name in (f"{TEXT_ACCESSION}-index.htm",):
        (replay / name).write_bytes((REPLAY / name).read_bytes())
    (replay / "10k2021.txt").write_bytes(
        (TEXT_FIXTURES / "text-multi-document-submission.txt").read_bytes())
    plan = _text_plan(tmp_path)
    result = run_primary_document_acquisition(
        repo_root=ROOT, request_plan_path=plan, output_dir=tmp_path / "out",
        run_id="rejected",
        metadata_transport=make_filing_index_fixture_replay_transport(
            replay, max_bytes=METADATA_CEILING),
        primary_transport=make_primary_document_fixture_replay_transport(
            replay, max_bytes=DOCUMENT_CEILING),
        metadata_transport_max_bytes=METADATA_CEILING,
        primary_transport_max_bytes=DOCUMENT_CEILING, clock=CLOCK,
    )
    assert not (result.run_dir / BUNDLE_MANIFEST_FILENAME).exists()
    assert not (result.run_dir / ACQUISITION_MANIFEST_FILENAME).exists()
    receipt = read_json(result.run_dir / FAILURE_RECEIPT_FILENAME)
    assert receipt["reason_code"] == REASON_MULTI_DOCUMENT
    assert receipt["retained_raw_filenames"] == []
    assert not list(result.run_dir.glob("primary-*")), "no byte was retained"


def test_the_html_route_still_emits_v01_artifacts(tmp_path):
    """The committed HTML fixture plan is untouched by any of this."""
    result = run_primary_document_acquisition(
        repo_root=ROOT, request_plan_path=REPLAY / "request_plan.json",
        output_dir=tmp_path / "out", run_id="html",
        metadata_transport=make_filing_index_fixture_replay_transport(
            REPLAY, max_bytes=METADATA_CEILING),
        primary_transport=make_primary_document_fixture_replay_transport(
            REPLAY, max_bytes=DOCUMENT_CEILING),
        metadata_transport_max_bytes=METADATA_CEILING,
        primary_transport_max_bytes=DOCUMENT_CEILING, clock=CLOCK,
    )
    bundle = read_json(result.run_dir / BUNDLE_MANIFEST_FILENAME)
    assert bundle["bundle_contract"] == BUNDLE_CONTRACT
    assert _errs(BUNDLE_V1_SCHEMA, bundle) == []
    assert _errs(BUNDLE_V2_SCHEMA, bundle), "a v0.1 bundle is not a v0.2 one"
    for document in bundle["documents"]:
        assert "representation" not in document
        assert document["local_filename"].endswith(".html")


# --- a v0.3 plan is a v0.3 shard, text or not ---------------------------------


def _html_only_v3_plan(tmp_path: Path) -> tuple[Path, dict]:
    """A v0.3 plan over the committed HTML fixture accessions only.

    Written with the queue's canonical serialization so the file hash equals
    the hash a regenerated shard plan would have, which is what binding
    compares.
    """
    payload = json.loads((REPLAY / "request_plan.json").read_text())
    payload.update({
        "plan_contract": PLAN_CONTRACT_V3,
        "max_retained_bytes": 10_000_000,
        "admit_plain_text": True,
    })
    path = tmp_path / "html-only-v3.plan.json"
    path.write_bytes(canonical_plan_bytes(payload))
    return path, payload


def test_an_html_only_v3_run_still_emits_the_v3_generation(tmp_path):
    """The defect: content must not decide the generation, the plan does."""
    plan, _ = _html_only_v3_plan(tmp_path)
    result = _acquire(tmp_path, plan, run_id="html-only-v3")
    bundle = read_json(result.run_dir / BUNDLE_MANIFEST_FILENAME)
    manifest = read_json(result.run_dir / ACQUISITION_MANIFEST_FILENAME)
    assert all(a.representation == "html" for a in result.acquired)
    assert bundle["bundle_contract"] == BUNDLE_CONTRACT_V2
    assert manifest["emitted_bundle_contract"] == BUNDLE_CONTRACT_V2
    assert set(manifest["schema_versions"]) == {
        "primary_document_acquisition_manifest_v6"
    }
    assert _errs(BUNDLE_V2_SCHEMA, bundle) == []
    assert _errs(BUNDLE_V1_SCHEMA, bundle), "v0.1 must reject a v0.3 bundle"
    assert _errs(ACQ_V6_SCHEMA, manifest) == []
    assert _errs(ACQ_V5_SCHEMA, manifest), "v0.5 must reject a v0.3 manifest"


def test_html_rows_of_a_v3_bundle_carry_the_null_evidence_semantics(tmp_path):
    plan, _ = _html_only_v3_plan(tmp_path)
    result = _acquire(tmp_path, plan, run_id="html-null")
    bundle = read_json(result.run_dir / BUNDLE_MANIFEST_FILENAME)
    manifest = read_json(result.run_dir / ACQUISITION_MANIFEST_FILENAME)
    for record in bundle["documents"] + manifest["acquisitions"]:
        assert record["representation"] == "html"
        for field in ("admission", "document_blocks", "declared_type",
                      "declared_filename"):
            assert field in record, field
            assert record[field] is None, field
        assert record["local_filename"].endswith(".html")


def test_html_packets_from_a_v3_bundle_are_v02_with_null_text_structure(tmp_path):
    plan, _ = _html_only_v3_plan(tmp_path)
    acquired = _acquire(tmp_path, plan, run_id="html-packets-v3")
    built = run_baseline_packet_build(
        repo_root=ROOT, bundle_dir=acquired.run_dir,
        output_dir=tmp_path / "pk", run_id="v3-html-packets",
        project_config_path=ROOT / "configs" / "project.yaml",
        clock=CLOCK, dry_run=True,
    )
    assert built.packets, "an html-only v0.3 bundle must still build packets"
    for packet in built.packets:
        record = packet.model_dump(mode="json")
        assert record["packet_contract"] == PACKET_CONTRACT_V2
        assert record["representation"] == "html"
        assert record["text_structure"] is None
        assert _errs(PACKET_V2_SCHEMA, record) == []
        assert _errs(PACKET_V1_SCHEMA, record), "v0.1 must reject a v0.2 packet"


# --- queue binding selects by plan contract, not transport ---------------------


def _shard_for(plan_payload: dict, accessions: tuple[str, ...], rows: int):
    return ShardPlan(
        shard_index=0, accessions=accessions, carrier_rows=rows,
        planned_requests=2 * len(accessions),
        max_retained_bytes=plan_payload["max_retained_bytes"],
        payload=plan_payload,
    )


@pytest.mark.parametrize("identity,label", [
    (None, "fixture_replay"),
    (SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY, "sec_live"),
])
def test_a_v3_shard_binds_under_either_transport(tmp_path, identity, label):
    """The second defect: binding chose v0.5/v0.4 from transport_kind alone."""
    plan, payload = _html_only_v3_plan(tmp_path)
    result = run_primary_document_acquisition(
        repo_root=ROOT, request_plan_path=plan, output_dir=tmp_path / label,
        run_id=f"bind-{label}",
        metadata_transport=make_filing_index_fixture_replay_transport(
            REPLAY, max_bytes=METADATA_CEILING),
        primary_transport=make_primary_document_fixture_replay_transport(
            REPLAY, max_bytes=DOCUMENT_CEILING),
        metadata_transport_max_bytes=METADATA_CEILING,
        primary_transport_max_bytes=DOCUMENT_CEILING, clock=CLOCK,
        transport_identity=identity,
    )
    manifest = read_json(result.run_dir / ACQUISITION_MANIFEST_FILENAME)
    assert manifest["transport_kind"] == label
    assert manifest["plan_contract"] == PLAN_CONTRACT_V3
    accessions = tuple(sorted(d["accession"] for d in payload["documents"]))
    rows = manifest["counts"]["bundle_entries"]
    bound = _bind_shard_manifest(
        ROOT, result.run_dir, _shard_for(payload, accessions, rows))
    assert bound["plan_sha256"] == manifest["plan_sha256"]


def test_a_text_bearing_v3_shard_binds(tmp_path):
    payload = json.loads(_text_plan(tmp_path).read_text())
    plan = tmp_path / "text.plan.json"
    plan.write_bytes(canonical_plan_bytes(payload))
    result = _acquire(tmp_path, plan, run_id="bind-text")
    manifest = read_json(result.run_dir / ACQUISITION_MANIFEST_FILENAME)
    assert manifest["acquisitions"][0]["representation"] == "plain_text"
    bound = _bind_shard_manifest(
        ROOT, result.run_dir,
        _shard_for(payload, (TEXT_ACCESSION,), manifest["counts"]["bundle_entries"]))
    assert bound["emitted_bundle_contract"] == BUNDLE_CONTRACT_V2


def test_a_v2_plan_shard_still_binds_under_the_v2_generation(tmp_path):
    """The existing generation is untouched by the correction."""
    payload = json.loads((REPLAY / "request_plan.json").read_text())
    payload.update({"plan_contract": "primary_document_request_plan@0.2.0",
                    "max_retained_bytes": 10_000_000})
    plan = tmp_path / "v2.plan.json"
    plan.write_bytes(canonical_plan_bytes(payload))
    result = _acquire(tmp_path, plan, run_id="bind-v2")
    manifest = read_json(result.run_dir / ACQUISITION_MANIFEST_FILENAME)
    assert manifest["plan_contract"] == "primary_document_request_plan@0.2.0"
    assert set(manifest["schema_versions"]) == {
        "primary_document_acquisition_manifest_v4"
    }
    assert "emitted_bundle_contract" not in manifest
    assert _errs(ACQ_V6_SCHEMA, manifest), "v0.6 must reject a v0.2 manifest"
    accessions = tuple(sorted(d["accession"] for d in payload["documents"]))
    bound = _bind_shard_manifest(
        ROOT, result.run_dir,
        _shard_for(payload, accessions, manifest["counts"]["bundle_entries"]))
    assert bound["plan_contract"] == "primary_document_request_plan@0.2.0"
    bundle = read_json(result.run_dir / BUNDLE_MANIFEST_FILENAME)
    assert bundle["bundle_contract"] == BUNDLE_CONTRACT
    assert all("representation" not in d for d in bundle["documents"])


# --- packets: forwarded, never reinterpreted -----------------------------------


def _build(tmp_path: Path, run_id: str = "text-packets"):
    return run_baseline_packet_build(
        repo_root=ROOT, bundle_dir=TEXT_FIXTURES, output_dir=tmp_path / "p",
        run_id=run_id, project_config_path=ROOT / "configs" / "project.yaml",
        clock=CLOCK, dry_run=True,
    )


def test_text_packets_match_gold(tmp_path):
    result = _build(tmp_path)
    assert result.counts == EXPECTED["counts"]
    got = [
        {"cik": p.cik, "form": p.form, "packet_contract": p.packet_contract,
         "representation": p.representation, "text_structure": p.text_structure,
         "end_boundary_kind": p.end_boundary_kind, "source_id": p.source_id,
         "passages": len(p.passages)}
        for p in result.packets
    ]
    assert got == EXPECTED["packets"]
    assert [{"cik": f.cik, "reason_code": f.reason_code}
            for f in result.failures] == EXPECTED["failures"]


def test_every_text_packet_carries_exactly_one_passage(tmp_path):
    """Recorded, not fixed here: the normalizer is reused unchanged."""
    for packet in _build(tmp_path).packets:
        assert len(packet.passages) == 1, packet.cik


def test_text_packets_are_v02_and_validate_only_there(tmp_path):
    for packet in _build(tmp_path).packets:
        record = packet.model_dump(mode="json")
        assert record["packet_contract"] == PACKET_CONTRACT_V2
        assert _errs(PACKET_V2_SCHEMA, record) == []
        assert _errs(PACKET_V1_SCHEMA, record), "a v0.2 packet is not a v0.1 one"


def test_text_structure_is_forwarded_from_the_bundle_not_reparsed(tmp_path):
    """The decisive test: evidence that disagrees with the bytes still wins.

    A packet that re-derived structure from the raw text would report what the
    document says. It must report what the governed bundle says, because the
    bundle is the acquisition-time record of why the source was admitted.
    """
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    for path in TEXT_FIXTURES.iterdir():
        (bundle_dir / path.name).write_bytes(path.read_bytes())
    manifest = json.loads((bundle_dir / "bundle_manifest.json").read_text())
    document = manifest["documents"][0]
    document.update({"admission": "bare_text", "document_blocks": 0,
                     "declared_type": None, "declared_filename": None})
    (bundle_dir / "bundle_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n")
    _, entries, _ = load_bundle(ROOT, bundle_dir)
    entry = next(e for e in entries if e["cik"] == document["cik"])
    packet = build_packet(
        entry, baseline_cutoff=date(2022, 12, 31),
        baseline_cutoff_source=read_json(
            TEXT_FIXTURES / "expected_packets.json").get("cutoff", {}) or {
                "path": "configs/project.yaml", "key": "x",
                "project_config_sha256": "0" * 64},
        route_validation=manifest["route_validation"],
        packet_contract=PACKET_CONTRACT_V2,
    )
    # The bytes say single_sgml_document with one block; the bundle says
    # otherwise, and the bundle is what the packet forwards.
    assert packet.text_structure["admission"] == "bare_text"
    assert packet.text_structure["document_blocks"] == 0
    assert packet.text_structure["declared_type"] is None


def test_the_packet_builder_never_imports_the_admission_module():
    """Re-deciding admission downstream would create a second, drifting record."""
    import ast

    path = ROOT / "src" / "dynamic_ai_products" / "ingestion" / "baseline_packet.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any("plain_text_primary" in name for name in imported)


def test_an_html_packet_has_a_null_text_structure(tmp_path):
    """The schema conditional, exercised on a real build."""
    result = run_baseline_packet_build(
        repo_root=ROOT,
        bundle_dir=ROOT / "evals" / "fixtures" / "baseline_packets",
        output_dir=tmp_path / "h", run_id="html-packets",
        project_config_path=ROOT / "configs" / "project.yaml",
        clock=CLOCK, dry_run=True,
    )
    for packet in result.packets:
        record = packet.model_dump(mode="json")
        assert record["packet_contract"] == PACKET_CONTRACT
        assert "text_structure" not in record, "a v0.1 packet omits the field"
        assert "representation" not in record


def test_a_v02_packet_with_a_non_null_text_structure_for_html_is_refused():
    record = {"packet_contract": PACKET_CONTRACT_V2, "representation": "html",
              "text_structure": {"admission": "bare_text", "document_blocks": 0,
                                 "declared_type": None, "declared_filename": None}}
    errors = _errs(PACKET_V2_SCHEMA, record)
    assert any("text_structure" in str(e.json_path) for e in errors)


def test_the_bundle_loader_accepts_both_generations(tmp_path):
    manifest, entries, _ = load_bundle(ROOT, TEXT_FIXTURES)
    assert manifest["bundle_contract"] == BUNDLE_CONTRACT_V2
    assert all(e["representation"] == "plain_text" for e in entries)
    html_manifest, html_entries, _ = load_bundle(
        ROOT, ROOT / "evals" / "fixtures" / "baseline_packets")
    assert html_manifest["bundle_contract"] == BUNDLE_CONTRACT
    assert all("representation" not in e for e in html_entries)


# --- predecessors are untouched -------------------------------------------------


@pytest.mark.parametrize("name", [
    "baseline_primary_document_bundle.schema.json",
    "universe_baseline_packet.schema.json",
    "baseline_packet_manifest.schema.json",
    "acquisition_queue_definition.schema.json",
    "primary_document_acquisition_manifest.schema.json",
    "primary_document_acquisition_manifest.v2.schema.json",
    "primary_document_acquisition_manifest.v3.schema.json",
    "primary_document_acquisition_manifest.v4.schema.json",
    "primary_document_acquisition_manifest.v5.schema.json",
])
def test_predecessor_schemas_admit_no_text(name):
    """None of them was widened: the successors carry the change."""
    text = (ROOT / "schemas" / name).read_text()
    assert "plain_text" not in text
    assert "txt" not in text or "acquisition_queue" in name


def test_the_registry_carries_every_successor():
    registry = read_json(
        ROOT / "schemas" / "schema_version_manifest.json")["schemas"]
    assert registry["baseline_primary_document_bundle"] == "0.1.0"
    assert registry["baseline_primary_document_bundle_v2"] == "0.2.0"
    assert registry["universe_baseline_packet"] == "0.1.0"
    assert registry["universe_baseline_packet_v2"] == "0.2.0"
    assert registry["baseline_packet_manifest"] == "0.1.0"
    assert registry["baseline_packet_manifest_v2"] == "0.2.0"
    assert registry["primary_document_acquisition_manifest_v6"] == "0.6.0"
    assert registry["acquisition_queue_definition"] == "0.1.0"
    assert registry["acquisition_queue_definition_v2"] == "0.2.0"
