"""Stage 00C baseline packet tests (W2-C-beta, ADR-091) — fully offline.

Every run builds packets from the committed synthetic bundle into a temporary
directory; nothing reads ``data/runs``, no network exists, and no model is
called. These tests pin what a v0.1 packet contains, what it explicitly
records as missing, and what it refuses.
"""

from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.ingestion.baseline_packet import (
    DEFERRED_SECTIONS,
    ISSUER_STATUS_BASIS,
    PACKET_MANIFEST_FILENAME,
    PACKETS_FILENAME,
    FAILURES_FILENAME,
    PacketBundleError,
    canonical_packet_bytes,
    load_bundle,
    recompute_packet_sha256,
    run_baseline_packet_build,
    source_id_for,
)
from dynamic_ai_products.ingestion.errors import IngestionError
from dynamic_ai_products.ingestion.normalize import (
    END_BOUNDARY_PRIORITY,
    find_item_one_span,
    find_item_one_span_v2,
)
from dynamic_ai_products.universe.io_utils import read_json

ROOT = Path(__file__).resolve().parents[2]
BUNDLE_DIR = ROOT / "evals" / "fixtures" / "baseline_packets"
PROJECT_CONFIG = ROOT / "configs" / "project.yaml"
PACKET_SCHEMA = ROOT / "schemas" / "universe_baseline_packet.schema.json"
MANIFEST_SCHEMA = ROOT / "schemas" / "baseline_packet_manifest.schema.json"
BUNDLE_SCHEMA = ROOT / "schemas" / "baseline_primary_document_bundle.schema.json"
CLI = ROOT / "pipelines" / "00_build_company_universe.py"
EXPECTED = read_json(BUNDLE_DIR / "expected_packets.json")

FIXED_CLOCK = lambda: datetime(2026, 8, 16, 18, 0, 0, tzinfo=timezone.utc)  # noqa: E731


def _build(tmp_path: Path, run_id: str = "packets-test", bundle=None, **kwargs):
    return run_baseline_packet_build(
        repo_root=ROOT,
        bundle_dir=bundle or BUNDLE_DIR,
        project_config_path=PROJECT_CONFIG,
        output_dir=tmp_path / "out",
        run_id=run_id,
        clock=FIXED_CLOCK,
        **kwargs,
    )


def _copy_bundle(tmp_path: Path) -> Path:
    target = tmp_path / "bundle"
    shutil.copytree(BUNDLE_DIR, target)
    return target


def _bundle_payload(bundle_dir: Path) -> dict:
    return json.loads((bundle_dir / "bundle_manifest.json").read_text())


def _write_bundle(bundle_dir: Path, payload: dict) -> Path:
    (bundle_dir / "bundle_manifest.json").write_text(json.dumps(payload, indent=2))
    return bundle_dir


# --- end-boundary tiers -----------------------------------------------------


def test_boundary_priority_is_1a_then_1b_then_2():
    assert END_BOUNDARY_PRIORITY == (
        "item_1a_risk_factors",
        "item_1b_unresolved_staff_comments",
        "item_2_properties",
    )


@pytest.mark.parametrize(
    "filename,kind",
    [
        ("primary_10k_ixbrl.htm", "item_1a_risk_factors"),
        ("primary_10kt.htm", "item_1b_unresolved_staff_comments"),
        ("primary_item2_boundary.htm", "item_2_properties"),
    ],
)
def test_each_boundary_tier_is_selected_and_named(filename, kind):
    start, end, boundary = find_item_one_span_v2((BUNDLE_DIR / filename).read_bytes())
    assert boundary == kind
    assert 0 <= start < end


def test_absent_item_1a_is_not_a_failure():
    """The whole point of v2: no risk factors is a different shape, not a loss."""
    raw = (BUNDLE_DIR / "primary_10kt.htm").read_bytes()
    with pytest.raises(IngestionError) as v1:
        find_item_one_span(raw)
    assert v1.value.reason_code == "item_span_not_found"
    assert find_item_one_span_v2(raw)[2] == "item_1b_unresolved_staff_comments"


def test_in_tier_ambiguity_refuses():
    raw = (BUNDLE_DIR / "primary_ambiguous_headings.htm").read_bytes()
    with pytest.raises(IngestionError) as exc:
        find_item_one_span_v2(raw)
    assert exc.value.reason_code == "ambiguous_end_boundary"


def test_no_trustworthy_boundary_refuses():
    with pytest.raises(IngestionError) as exc:
        find_item_one_span_v2((BUNDLE_DIR / "primary_no_boundary.htm").read_bytes())
    assert exc.value.reason_code == "no_end_boundary"


def test_missing_item_one_refuses():
    with pytest.raises(IngestionError) as exc:
        find_item_one_span_v2((BUNDLE_DIR / "primary_missing_item1.htm").read_bytes())
    assert exc.value.reason_code == "item_span_not_found"


def test_cross_reference_is_never_a_boundary():
    """An inline 'see Part I, Item 1A' must not end the span."""
    raw = (
        b"<html><body><div>TABLE OF CONTENTS</div>"
        b"<div>Item 1. Business .......... 3</div>"
        b'<div style="font-weight:700">Item 1. Business</div>'
        b"<div>We describe our business. See Part I, Item 1A. Risk Factors "
        b"for more detail, which continues this sentence.</div>"
        b'<div style="font-weight:700">Item 1A. Risk Factors</div>'
        b"<div>Risks.</div></body></html>"
    )
    start, end, kind = find_item_one_span_v2(raw)
    assert kind == "item_1a_risk_factors"
    # The span must reach the real heading, not stop at the cross-reference.
    assert b"which continues this sentence" in raw[start:end]


def test_table_of_contents_never_supplies_the_body_heading():
    raw = (BUNDLE_DIR / "primary_10k_ixbrl.htm").read_bytes()
    start, _, _ = find_item_one_span_v2(raw)
    toc = raw.find(b"Item 1. Business .......... 3")
    assert toc != -1 and start > toc


def test_v1_is_unchanged_for_a_1a_document():
    raw = (BUNDLE_DIR / "primary_10k_ixbrl.htm").read_bytes()
    assert find_item_one_span(raw) == find_item_one_span_v2(raw)[:2]


# --- gold round trip --------------------------------------------------------


def test_build_matches_gold(tmp_path):
    result = _build(tmp_path)
    assert result.counts == EXPECTED["counts"]
    assert all(result.reconciliation.values())
    packets = sorted(result.packets, key=lambda p: p.accession)
    for got, want in zip(packets, EXPECTED["packets"]):
        assert got.accession == want["accession"]
        assert got.form == want["form"]
        assert got.end_boundary_kind == want["end_boundary_kind"]
        assert got.item_one_start == want["item_one_start"]
        assert got.item_one_end == want["item_one_end"]
        assert len(got.passages) == want["passage_count"]
        assert got.source_id == want["source_id"]
        assert got.packet_sha256 == want["packet_sha256"]
    failures = sorted(result.failures, key=lambda f: f.accession)
    assert [f.reason_code for f in failures] == [
        f["reason_code"] for f in EXPECTED["failures"]
    ]


def test_ten_kt_is_supported(tmp_path):
    result = _build(tmp_path)
    forms = {p.form for p in result.packets}
    assert "10-KT" in forms and "10-K" in forms


def test_packets_and_manifest_validate_against_their_schemas(tmp_path):
    result = _build(tmp_path)
    packet_validator = Draft202012Validator(read_json(PACKET_SCHEMA))
    for packet in result.packets:
        assert not list(
            packet_validator.iter_errors(packet.model_dump(mode="json"))
        )
    manifest = read_json(result.manifest_path)
    assert not list(
        Draft202012Validator(read_json(MANIFEST_SCHEMA)).iter_errors(manifest)
    )
    assert not list(
        Draft202012Validator(read_json(BUNDLE_SCHEMA)).iter_errors(
            _bundle_payload(BUNDLE_DIR)
        )
    )


def test_run_writes_packets_failures_and_manifest(tmp_path):
    result = _build(tmp_path)
    for name in (PACKETS_FILENAME, FAILURES_FILENAME, PACKET_MANIFEST_FILENAME):
        assert (result.run_dir / name).is_file(), name
    manifest = read_json(result.manifest_path)
    assert set(manifest["output_hashes"]) == {PACKETS_FILENAME, FAILURES_FILENAME}


# --- explicit missingness, never inference ----------------------------------


def test_only_item_one_passages_are_emitted(tmp_path):
    result = _build(tmp_path)
    for packet in result.packets:
        assert {p.section for p in packet.passages} == {"ITEM1_OVERVIEW"}


def test_cover_page_and_deferred_sections_are_explicitly_missing(tmp_path):
    result = _build(tmp_path)
    for packet in result.packets:
        assert "COVER_PAGE" in packet.missing_sections
        for section in DEFERRED_SECTIONS:
            assert section in packet.missing_sections
        assert packet.issuer_status_basis == ISSUER_STATUS_BASIS


def test_no_issuer_flag_is_asserted_from_silence(tmp_path):
    """Absence of a cover page yields unknown, never false."""
    result = _build(tmp_path)
    for packet in result.packets:
        flags = packet.issuer_status_flags.model_dump()
        assert set(flags.values()) == {None}, flags
        assert False not in flags.values()


def test_cover_page_absence_is_not_a_packet_failure(tmp_path):
    result = _build(tmp_path)
    assert result.counts["packets_built"] == 3
    assert all(
        f.reason_code != "cover_page_unavailable" for f in result.failures
    )


def test_no_firm_is_ever_excluded(tmp_path):
    result = _build(tmp_path)
    assert result.counts["firms_excluded"] == 0
    assert (
        result.counts["planned_documents"]
        == result.counts["packets_built"] + result.counts["packet_failures"]
    )


# --- provenance separation --------------------------------------------------


def test_route_validation_is_labelled_and_distinct_from_selection(tmp_path):
    result = _build(tmp_path)
    for packet in result.packets:
        route = packet.route_validation
        assert "never selection evidence" in route["note"]
        assert route["covered_accessions"] == 3
        selection = packet.selection_provenance
        assert set(selection) == {
            "filing_index_url", "filing_index_response_sha256",
            "selected_document", "primary_url",
        }
        # The two evidence kinds share no hash.
        assert (
            selection["filing_index_response_sha256"]
            != route["probe_manifest_sha256"]
        )


def test_source_id_is_stable_identity_not_the_raw_hash(tmp_path):
    result = _build(tmp_path)
    for packet in result.packets:
        assert packet.source_id == source_id_for(
            packet.cik, packet.accession,
            packet.selection_provenance["selected_document"],
        )
        assert packet.source_sha256 not in packet.source_id
        for passage in packet.passages:
            assert passage.source_id == packet.source_id


def test_passage_identity_survives_an_unrelated_edit(tmp_path):
    """Because source_id is not the raw hash, an edit elsewhere is harmless."""
    bundle = _copy_bundle(tmp_path)
    before = {
        p.accession: [x.passage_id for x in p.passages]
        for p in _build(tmp_path, run_id="before", bundle=bundle).packets
    }
    target = bundle / "primary_10k_ixbrl.htm"
    raw = target.read_bytes()
    edited = raw.replace(
        b"<div>SYNTHETIC ANNUAL REPORT",
        b"<div>SYNTHETIC ANNUAL REPORT (revised cover line)",
    )
    assert edited != raw
    target.write_bytes(edited)
    payload = _bundle_payload(bundle)
    from hashlib import sha256

    for entry in payload["documents"]:
        if entry["local_filename"] == "primary_10k_ixbrl.htm":
            entry["source_sha256"] = sha256(edited).hexdigest()
            entry["source_byte_length"] = len(edited)
    _write_bundle(bundle, payload)
    after = {
        p.accession: [x.passage_id for x in p.passages]
        for p in _build(tmp_path, run_id="after", bundle=bundle).packets
    }
    assert after == before


# --- hashes and determinism -------------------------------------------------


def test_packet_sha256_excludes_itself_and_is_reproducible(tmp_path):
    result = _build(tmp_path)
    for packet in result.packets:
        record = packet.model_dump(mode="json")
        assert recompute_packet_sha256(record) == packet.packet_sha256
        assert b"packet_sha256" not in canonical_packet_bytes(record)
        # Key order must not matter.
        shuffled = dict(reversed(list(record.items())))
        assert recompute_packet_sha256(shuffled) == packet.packet_sha256


def test_packet_byte_size_excludes_both_self_referential_fields(tmp_path):
    result = _build(tmp_path)
    for packet in result.packets:
        record = packet.model_dump(mode="json")
        assert packet.packet_byte_size == len(
            canonical_packet_bytes(
                record, omit=("packet_sha256", "packet_byte_size")
            )
        )


def test_two_runs_are_byte_identical(tmp_path):
    first = _build(tmp_path, run_id="det-1")
    second = _build(tmp_path, run_id="det-2")
    assert (first.run_dir / PACKETS_FILENAME).read_bytes() == (
        second.run_dir / PACKETS_FILENAME
    ).read_bytes()
    assert read_json(first.manifest_path)["output_hashes"] == (
        read_json(second.manifest_path)["output_hashes"]
    )


def test_reconciliation_identities(tmp_path):
    result = _build(tmp_path)
    assert all(result.reconciliation.values())
    for packet in result.packets:
        ledger = packet.normalization_ledger
        assert ledger["input_byte_count"] == (
            ledger["normalized_byte_count"] + ledger["dropped_byte_count"]
        )
        for passage in packet.passages:
            assert packet.item_one_start <= passage.byte_start
            assert passage.byte_end <= packet.item_one_end
    manifest = read_json(result.manifest_path)
    assert sum(manifest["counts"]["packets_by_end_boundary"].values()) == (
        manifest["counts"]["packets_built"]
    )


# --- input integrity refuses the run ---------------------------------------


def test_tampered_document_changing_length_refuses(tmp_path):
    """Appended bytes are caught by the length check, before the hash."""
    bundle = _copy_bundle(tmp_path)
    target = bundle / "primary_10k_ixbrl.htm"
    target.write_bytes(target.read_bytes() + b"<!-- tampered -->")
    with pytest.raises(PacketBundleError, match="byte-length mismatch"):
        _build(tmp_path, run_id="tampered", bundle=bundle)
    assert not (tmp_path / "out").exists()


def test_tampered_document_preserving_length_refuses(tmp_path):
    """A same-length edit passes the length check and fails on the hash."""
    bundle = _copy_bundle(tmp_path)
    target = bundle / "primary_10k_ixbrl.htm"
    raw = target.read_bytes()
    edited = raw.replace(b"SYNTHETIC ANNUAL", b"SYNTHETIC ANNUAM", 1)
    assert edited != raw and len(edited) == len(raw)
    target.write_bytes(edited)
    with pytest.raises(PacketBundleError, match="hash mismatch"):
        _build(tmp_path, run_id="same-length", bundle=bundle)
    assert not (tmp_path / "out").exists()


def test_correct_hash_with_wrong_declared_length_refuses(tmp_path):
    """The declared length is verified independently and never repaired."""
    bundle = _copy_bundle(tmp_path)
    payload = _bundle_payload(bundle)
    entry = payload["documents"][0]
    actual = (bundle / entry["local_filename"]).stat().st_size
    assert entry["source_byte_length"] == actual
    entry["source_byte_length"] = actual + 17  # hash still correct
    _write_bundle(bundle, payload)
    with pytest.raises(PacketBundleError, match="byte-length mismatch"):
        _build(tmp_path, run_id="bad-length", bundle=bundle)
    assert not (tmp_path / "out").exists()
    # The bundle was not rewritten to match what was observed.
    assert _bundle_payload(bundle)["documents"][0]["source_byte_length"] == (
        actual + 17
    )


# --- path and identity safety ----------------------------------------------


@pytest.mark.parametrize(
    "unsafe",
    [
        "../primary_10k_ixbrl.htm",
        "../../etc/passwd",
        "/etc/passwd",
        "/absolute/primary.htm",
        "sub/primary.htm",
        "sub\\primary.htm",
        ".",
        "..",
        "~/primary.htm",
        "C:\\primary.htm",
        "",
        "   ",
        " primary.htm",
    ],
)
@pytest.mark.parametrize("field", ["local_filename", "selected_document"])
def test_unsafe_bundle_filename_is_refused(tmp_path, field, unsafe):
    bundle = _copy_bundle(tmp_path / f"{field}-{abs(hash(unsafe))}")
    payload = _bundle_payload(bundle)
    payload["documents"][0][field] = unsafe
    _write_bundle(bundle, payload)
    with pytest.raises(PacketBundleError):
        load_bundle(ROOT, bundle)


def test_traversal_filename_is_refused_before_any_file_is_read(tmp_path):
    """A traversal target that exists must still never be opened."""
    bundle = _copy_bundle(tmp_path)
    outside = tmp_path / "outside.htm"
    outside.write_bytes(b"<html>should never be read</html>")
    payload = _bundle_payload(bundle)
    payload["documents"][0]["local_filename"] = "../outside.htm"
    _write_bundle(bundle, payload)
    with pytest.raises(PacketBundleError) as exc:
        load_bundle(ROOT, bundle)
    message = str(exc.value)
    assert "outside.htm" in message
    # Refused on the name, not after reading and hashing the file.
    assert "hash mismatch" not in message and "byte-length" not in message


def test_local_filename_and_selected_document_may_differ(tmp_path):
    """They are distinct facts; equality is never required."""
    bundle = _copy_bundle(tmp_path)
    payload = _bundle_payload(bundle)
    entry = payload["documents"][0]
    assert entry["local_filename"] == entry["selected_document"]
    entry["selected_document"] = "air-20220531x10k.htm"  # SEC's name
    _write_bundle(bundle, payload)
    _, entries, _ = load_bundle(ROOT, bundle)
    first = entries[0]
    assert first["local_filename"] != first["selected_document"]
    result = _build(tmp_path, run_id="distinct-names", bundle=bundle)
    packet = next(p for p in result.packets if p.accession == entry["accession"])
    # Identity follows the selected document, not the local storage name.
    assert packet.source_id.endswith("air-20220531x10k.htm")


def test_tampered_bundle_hash_refuses(tmp_path):
    bundle = _copy_bundle(tmp_path)
    payload = _bundle_payload(bundle)
    payload["documents"][0]["source_sha256"] = "a" * 64
    _write_bundle(bundle, payload)
    with pytest.raises(PacketBundleError, match="hash mismatch"):
        _build(tmp_path, run_id="bad-hash", bundle=bundle)


def test_entry_missing_selection_provenance_refuses(tmp_path):
    for field in ("filing_index_response_sha256", "primary_url",
                  "selected_document", "filing_index_url"):
        bundle = _copy_bundle(tmp_path / field)
        payload = _bundle_payload(bundle)
        del payload["documents"][0][field]
        _write_bundle(bundle, payload)
        with pytest.raises(PacketBundleError, match="violates baseline_primary_document_bundle"):
            load_bundle(ROOT, bundle)


def test_fpi_form_is_refused_with_the_preserved_message(tmp_path):
    bundle = _copy_bundle(tmp_path)
    payload = _bundle_payload(bundle)
    payload["documents"][0]["form"] = "20-F"
    _write_bundle(bundle, payload)
    with pytest.raises(PacketBundleError, match="violates baseline_primary_document_bundle"):
        load_bundle(ROOT, bundle)


def test_duplicate_document_refuses(tmp_path):
    bundle = _copy_bundle(tmp_path)
    payload = _bundle_payload(bundle)
    payload["documents"].append(json.loads(json.dumps(payload["documents"][0])))
    _write_bundle(bundle, payload)
    with pytest.raises(PacketBundleError, match="duplicate document"):
        load_bundle(ROOT, bundle)


def test_missing_document_file_refuses(tmp_path):
    bundle = _copy_bundle(tmp_path)
    (bundle / "primary_10kt.htm").unlink()
    with pytest.raises(PacketBundleError, match="document missing"):
        load_bundle(ROOT, bundle)


def test_rerun_of_an_existing_run_id_is_refused(tmp_path):
    _build(tmp_path, run_id="immutable")
    before = sorted(p.name for p in (tmp_path / "out" / "immutable").iterdir())
    with pytest.raises(FileExistsError):
        _build(tmp_path, run_id="immutable")
    assert sorted(
        p.name for p in (tmp_path / "out" / "immutable").iterdir()
    ) == before


def test_dry_run_writes_nothing(tmp_path):
    result = _build(tmp_path, run_id="dry", dry_run=True)
    assert result.run_dir is None and result.manifest_path is None
    assert result.counts == EXPECTED["counts"]
    assert not (tmp_path / "out").exists()


# --- temporal ---------------------------------------------------------------


def test_post_cutoff_filing_is_a_recorded_failure(tmp_path):
    bundle = _copy_bundle(tmp_path)
    payload = _bundle_payload(bundle)
    payload["documents"][0]["baseline_filing_date"] = "2026-01-31"
    _write_bundle(bundle, payload)
    result = _build(tmp_path, run_id="temporal", bundle=bundle)
    reasons = {f.reason_code for f in result.failures}
    assert "temporal_mismatch" in reasons
    assert result.counts["firms_excluded"] == 0


def test_cutoff_is_read_from_the_frozen_project_config(tmp_path):
    result = _build(tmp_path)
    manifest = read_json(result.manifest_path)
    assert manifest["baseline_cutoff"] == "2022-11-29"
    assert manifest["baseline_cutoff_source"]["key"] == "universe.baseline_cutoff"
    for packet in result.packets:
        assert packet.baseline_cutoff == date(2022, 11, 29)
        assert packet.baseline_filing_date <= packet.baseline_cutoff


# --- boundaries -------------------------------------------------------------


def test_module_performs_no_network_and_names_no_url():
    source = (
        ROOT / "src" / "dynamic_ai_products" / "ingestion" / "baseline_packet.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("import httpx", "requests", "urllib", "socket",
                      "http://", "https://", "sec.gov"):
        assert forbidden not in source, forbidden


def test_cli_build_baseline_packets_mode(tmp_path):
    import subprocess
    import sys

    completed = subprocess.run(
        [
            sys.executable, str(CLI),
            "--mode", "build-baseline-packets",
            "--bundle-dir", str(BUNDLE_DIR),
            "--config", str(PROJECT_CONFIG),
            "--output-dir", str(tmp_path / "out"),
            "--run-id", "cli-packets",
        ],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["counts"] == EXPECTED["counts"]
    assert all(payload["reconciliation"].values())


def test_cli_rejects_cross_mode_flags(tmp_path):
    import subprocess
    import sys

    completed = subprocess.run(
        [
            sys.executable, str(CLI),
            "--mode", "build-baseline-packets",
            "--bundle-dir", str(BUNDLE_DIR),
            "--config", str(PROJECT_CONFIG),
            "--dera-dir", str(tmp_path),
            "--output-dir", str(tmp_path / "out"),
            "--run-id", "cli-packets-bad",
        ],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode != 0
    assert "does not accept" in completed.stderr
