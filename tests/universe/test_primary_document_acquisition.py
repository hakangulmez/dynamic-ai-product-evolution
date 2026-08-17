"""Two-hop primary-document acquisition tests (W2-C, ADR-092) — fully offline.

Every run replays local synthetic index pages and primary documents through
injected fixture transports into a temporary directory; nothing reads
``data/runs``, no network exists, and no model is called. These tests pin the
route, the governed bundle it emits, the directed provenance graph, and the
precise authority and failure semantics.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.ingestion.baseline_packet import (
    PacketBundleError,
    load_bundle,
    run_baseline_packet_build,
)
from dynamic_ai_products.sec_document_transport import (
    SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY,
)
from dynamic_ai_products.universe.document_acquisition import (
    DocumentTransportResponse,
)
from dynamic_ai_products.universe.filing_index_probe import (
    make_filing_index_fixture_replay_transport,
)
from dynamic_ai_products.universe.primary_document_acquisition import (
    ACQUISITION_MANIFEST_FILENAME,
    GROUND_TRUTH_BASES,
    BUNDLE_MANIFEST_FILENAME,
    FAILURE_RECEIPT_FILENAME,
    PrimaryDocumentPlanError,
    canonical_primary_document_url,
    href_form_of,
    load_request_plan,
    local_filename_for,
    make_primary_document_fixture_replay_transport,
    run_primary_document_acquisition,
)
from dynamic_ai_products.universe.io_utils import read_json

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "evals" / "fixtures" / "primary_documents"
FIXTURE_PLAN = FIXTURE_DIR / "request_plan.json"
CANARY_PLAN = ROOT / "configs" / "primary_document_canary_request_plan.json"
SHELL_PLAN = ROOT / "configs" / "shell_validation_canary_request_plan.json"
DECISION_LOG = ROOT / "docs" / "DECISION_LOG.md"
BUNDLE_SCHEMA = ROOT / "schemas" / "baseline_primary_document_bundle.schema.json"
ACQ_SCHEMA = ROOT / "schemas" / "primary_document_acquisition_manifest.schema.json"
ACQ_V2_SCHEMA = (
    ROOT / "schemas" / "primary_document_acquisition_manifest.v2.schema.json"
)
ACQ_V3_SCHEMA = (
    ROOT / "schemas" / "primary_document_acquisition_manifest.v3.schema.json"
)
PROJECT_CONFIG = ROOT / "configs" / "project.yaml"
CLI = ROOT / "pipelines" / "00_build_company_universe.py"
EXPECTED = read_json(FIXTURE_DIR / "expected_acquisition.json")

METADATA_CEILING = 8388608
DOCUMENT_CEILING = 268435456
FIXED_CLOCK = lambda: datetime(2026, 8, 16, 20, 0, 0, tzinfo=timezone.utc)  # noqa: E731


def _acquire(tmp_path: Path, run_id: str = "acq-test", plan: Path | None = None,
             **kwargs):
    plan_path = plan or FIXTURE_PLAN
    return run_primary_document_acquisition(
        repo_root=ROOT,
        request_plan_path=plan_path,
        output_dir=tmp_path / "out",
        run_id=run_id,
        metadata_transport=kwargs.pop(
            "metadata_transport",
            make_filing_index_fixture_replay_transport(
                FIXTURE_DIR, max_bytes=METADATA_CEILING
            ),
        ),
        primary_transport=kwargs.pop(
            "primary_transport",
            make_primary_document_fixture_replay_transport(
                FIXTURE_DIR, max_bytes=DOCUMENT_CEILING
            ),
        ),
        metadata_transport_max_bytes=kwargs.pop(
            "metadata_transport_max_bytes", METADATA_CEILING
        ),
        primary_transport_max_bytes=kwargs.pop(
            "primary_transport_max_bytes", DOCUMENT_CEILING
        ),
        clock=FIXED_CLOCK,
        **kwargs,
    )


def _plan_payload(path: Path = FIXTURE_PLAN) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_plan(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


# --- the two-hop route ------------------------------------------------------


def test_primary_url_is_derived_from_the_filing_directory():
    assert canonical_primary_document_url(
        "0000001750", "0001104659-22-081498", "air-20220531x10k.htm"
    ) == (
        "https://www.sec.gov/Archives/edgar/data/1750/"
        "000110465922081498/air-20220531x10k.htm"
    )


def test_no_derived_url_addresses_a_full_submission_or_a_viewer(tmp_path):
    result = _acquire(tmp_path)
    for item in result.acquired:
        assert not item.primary_url.endswith(f"{item.accession}.txt")
        assert "/ix?doc=" not in item.primary_url
        assert item.filing_index_url.endswith("-index.htm")


def test_href_form_is_measured_per_document(tmp_path):
    result = _acquire(tmp_path)
    forms = {a.accession: a.href_form for a in result.acquired}
    assert forms["0009200001-22-000001"] == "direct"
    assert forms["0009200002-22-000002"] == "viewer"
    manifest = read_json(result.acquisition_manifest_path)
    assert manifest["counts"]["href_forms"] == EXPECTED["counts"]["href_forms"]


def test_href_form_classifier():
    archive = "/Archives/edgar/data/1750/000110465922081498/a.htm"
    assert href_form_of(archive) == "direct"
    assert href_form_of(f"/ix?doc={archive}") == "viewer"
    assert href_form_of(f"https://www.sec.gov/ix?doc={archive}") == "viewer"
    assert href_form_of("/ixviewer?doc=" + archive) == "direct"


def test_viewer_link_still_yields_the_clean_primary(tmp_path):
    result = _acquire(tmp_path)
    viewer = next(a for a in result.acquired if a.href_form == "viewer")
    assert "iXBRL" not in viewer.selected_document
    assert viewer.primary_url.endswith(viewer.selected_document)


def test_request_accounting_is_two_per_accession(tmp_path):
    result = _acquire(tmp_path)
    counts = result.counts
    assert counts["filing_index_requests"] == counts["planned_accessions"]
    assert counts["primary_document_requests"] == counts["planned_accessions"]
    assert counts["total_requests"] == 2 * counts["planned_accessions"] == 6


# --- the governed bundle ----------------------------------------------------


def test_bundle_matches_gold_and_validates_against_the_committed_schema(tmp_path):
    result = _acquire(tmp_path)
    bundle = read_json(result.bundle_manifest_path)
    assert not list(
        Draft202012Validator(read_json(BUNDLE_SCHEMA)).iter_errors(bundle)
    )
    assert bundle["bundle_contract"] == "baseline_primary_document_bundle@0.1.0"
    entries = [
        {"cik": e["cik"], "accession": e["accession"], "form": e["form"],
         "local_filename": e["local_filename"],
         "selected_document": e["selected_document"]}
        for e in bundle["documents"]
    ]
    assert entries == EXPECTED["bundle_entries"]
    assert result.counts == EXPECTED["counts"]


def test_shared_accession_is_fetched_once_and_mapped_to_every_row(tmp_path):
    result = _acquire(tmp_path)
    bundle = read_json(result.bundle_manifest_path)
    shared = [e for e in bundle["documents"]
              if e["accession"] == "0009200003-22-000003"]
    assert len(shared) == 2
    assert {e["cik"] for e in shared} == {"0009200003", "0009200004"}
    # One download, one stored file, identical hashes across rows.
    assert len({e["local_filename"] for e in shared}) == 1
    assert len({e["source_sha256"] for e in shared}) == 1
    assert len(list(result.run_dir.glob("primary-*.html"))) == 3
    assert result.counts["shared_accessions"] == 1
    assert result.counts["bundle_entries"] == 4


def test_local_filename_convention_and_distinctness(tmp_path):
    result = _acquire(tmp_path)
    bundle = read_json(result.bundle_manifest_path)
    for entry in bundle["documents"]:
        assert entry["local_filename"] == local_filename_for(entry["accession"])
        assert entry["local_filename"].startswith("primary-")
        assert entry["local_filename"].endswith(".html")
        # Distinct facts: the stored name is never the SEC basename.
        assert entry["local_filename"] != entry["selected_document"]


def test_every_bundle_entry_carries_its_own_selection_provenance(tmp_path):
    result = _acquire(tmp_path)
    bundle = read_json(result.bundle_manifest_path)
    for entry in bundle["documents"]:
        assert entry["filing_index_url"].endswith("-index.htm")
        assert len(entry["filing_index_response_sha256"]) == 64
        assert entry["primary_url"].endswith(entry["selected_document"])
        assert entry["source_byte_length"] > 0


def test_bundle_round_trips_through_the_packet_builder(tmp_path):
    """The emitted bundle is consumed by build-baseline-packets unchanged."""
    result = _acquire(tmp_path)
    _, entries, _ = load_bundle(ROOT, result.run_dir)
    assert len(entries) == 4
    packets = run_baseline_packet_build(
        repo_root=ROOT, bundle_dir=result.run_dir,
        project_config_path=PROJECT_CONFIG,
        output_dir=tmp_path / "packets", run_id="round-trip",
        clock=FIXED_CLOCK,
    )
    assert packets.counts["packets_built"] == 4
    assert packets.counts["firms_excluded"] == 0
    assert all(packets.reconciliation.values())


# --- directed provenance ----------------------------------------------------


def test_bundle_names_its_run_but_never_hashes_the_acquisition_manifest(tmp_path):
    result = _acquire(tmp_path, run_id="provenance")
    bundle = read_json(result.bundle_manifest_path)
    provenance = bundle["provenance"]
    assert provenance["acquisition_run_id"] == "provenance"
    assert "acquisition_manifest_sha256" not in provenance
    assert sorted(provenance) == EXPECTED["bundle_provenance_keys"]


def test_output_hashes_cover_bundle_and_primaries_and_never_itself(tmp_path):
    result = _acquire(tmp_path)
    manifest = read_json(result.acquisition_manifest_path)
    hashes = manifest["output_hashes"]
    expected_names = {BUNDLE_MANIFEST_FILENAME} | {
        a.local_filename for a in result.acquired
    }
    assert set(hashes) == expected_names
    assert len(hashes) == len(result.acquired) + 1
    assert ACQUISITION_MANIFEST_FILENAME not in hashes
    assert "manifest_sha256" not in manifest
    # Each recorded hash is the real file's hash.
    for name, digest in hashes.items():
        assert sha256((result.run_dir / name).read_bytes()).hexdigest() == digest


def test_provenance_graph_has_no_cycle(tmp_path):
    """Nothing hashes an artifact that transitively hashes it back."""
    result = _acquire(tmp_path)
    bundle_bytes = result.bundle_manifest_path.read_bytes()
    manifest_bytes = result.acquisition_manifest_path.read_bytes()
    manifest = read_json(result.acquisition_manifest_path)
    # The manifest hashes the bundle...
    assert manifest["output_hashes"][BUNDLE_MANIFEST_FILENAME] == (
        sha256(bundle_bytes).hexdigest()
    )
    # ...and the bundle's own bytes contain no hash of the manifest.
    assert sha256(manifest_bytes).hexdigest() not in bundle_bytes.decode("utf-8")


def test_upstream_provenance_is_bound(tmp_path):
    result = _acquire(tmp_path)
    manifest = read_json(result.acquisition_manifest_path)
    bundle = read_json(result.bundle_manifest_path)
    plan = _plan_payload()
    for record in (manifest["carrier_provenance"], bundle["provenance"]):
        assert record["carrier_run_id"] == plan["provenance"]["carrier_run_id"]
        assert record["carrier_manifest_sha256"] == (
            plan["provenance"]["carrier_manifest_sha256"]
        )
        assert record["freeze_record_sha256"] == (
            plan["provenance"]["freeze_record_sha256"]
        )
    for record in (manifest["route_validation"], bundle["route_validation"]):
        assert record["probe_manifest_sha256"] == (
            plan["route_validation"]["probe_manifest_sha256"]
        )
        assert "never selection evidence" in record["note"]


# --- transport provenance ---------------------------------------------------


def test_one_active_transport_kind_and_two_hop_records(tmp_path):
    result = _acquire(tmp_path)
    manifest = read_json(result.acquisition_manifest_path)
    assert manifest["transport_kind"] == "fixture_replay"
    assert isinstance(manifest["transport_kind"], str)
    metadata, primary = manifest["metadata_hop"], manifest["primary_document_hop"]
    # Equal contracts, different plan-owned bounds.
    assert metadata["transport_contract_hash"] == primary["transport_contract_hash"]
    assert metadata["max_bytes"] == METADATA_CEILING
    assert primary["max_bytes"] == DOCUMENT_CEILING
    assert metadata["max_bytes"] != primary["max_bytes"]


def test_live_identity_writes_the_v3_manifest_with_its_contract(tmp_path):
    result = _acquire(
        tmp_path, run_id="live-shaped",
        transport_identity=SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY,
    )
    manifest = read_json(result.acquisition_manifest_path)
    assert manifest["transport_kind"] == "sec_live"
    assert manifest["transport_contract"]["transport_kind"] == "sec_live"
    assert manifest["metadata_hop"]["ceiling_enforcement"]["mechanism"] == (
        "streaming_chunk_bound"
    )
    assert manifest["schema_versions"] == {
        "primary_document_acquisition_manifest_v3": "0.3.0"
    }
    # v0.3 accepts it; both earlier contracts reject it.
    assert not list(
        Draft202012Validator(read_json(ACQ_V3_SCHEMA)).iter_errors(manifest)
    )
    assert list(Draft202012Validator(read_json(ACQ_V2_SCHEMA)).iter_errors(manifest))
    assert list(Draft202012Validator(read_json(ACQ_SCHEMA)).iter_errors(manifest))


# --- ADR-093: observational declared lengths -------------------------------


def _declaring_transports(index_declared, primary_declared):
    """Transports whose responses carry chosen declared Content-Lengths."""
    index_source = make_filing_index_fixture_replay_transport(
        FIXTURE_DIR, max_bytes=METADATA_CEILING
    )
    primary_source = make_primary_document_fixture_replay_transport(
        FIXTURE_DIR, max_bytes=DOCUMENT_CEILING
    )

    def metadata(url: str) -> DocumentTransportResponse:
        base = index_source(url)
        return DocumentTransportResponse(
            status_code=base.status_code, final_url=base.final_url,
            content=base.content, declared_content_length=index_declared,
            bytes_received=base.bytes_received,
        )

    def primary(url: str) -> DocumentTransportResponse:
        base = primary_source(url)
        return DocumentTransportResponse(
            status_code=base.status_code, final_url=base.final_url,
            content=base.content, declared_content_length=primary_declared,
            bytes_received=base.bytes_received,
        )

    return metadata, primary


def test_declared_lengths_are_propagated_independently_per_hop(tmp_path):
    metadata, primary = _declaring_transports(4321, 98765)
    result = _acquire(
        tmp_path, run_id="declared-both",
        metadata_transport=metadata, primary_transport=primary,
        transport_identity=SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY,
    )
    manifest = read_json(result.acquisition_manifest_path)
    for record in manifest["acquisitions"]:
        assert record["filing_index_declared_content_length"] == 4321
        assert record["primary_declared_content_length"] == 98765
        # Observational only: never the retained byte count.
        assert record["source_byte_length"] != 98765
    assert not list(
        Draft202012Validator(read_json(ACQ_V3_SCHEMA)).iter_errors(manifest)
    )


def test_declared_lengths_do_not_swap_between_hops(tmp_path):
    metadata, primary = _declaring_transports(11, 22)
    result = _acquire(
        tmp_path, run_id="declared-order",
        metadata_transport=metadata, primary_transport=primary,
        transport_identity=SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY,
    )
    for record in read_json(result.acquisition_manifest_path)["acquisitions"]:
        assert record["filing_index_declared_content_length"] == 11
        assert record["primary_declared_content_length"] == 22


def test_null_declared_lengths_are_preserved_for_both_fields(tmp_path):
    """An absent or malformed header yields None; nothing is reconstructed."""
    metadata, primary = _declaring_transports(None, None)
    result = _acquire(
        tmp_path, run_id="declared-null",
        metadata_transport=metadata, primary_transport=primary,
        transport_identity=SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY,
    )
    manifest = read_json(result.acquisition_manifest_path)
    for record in manifest["acquisitions"]:
        assert record["filing_index_declared_content_length"] is None
        assert record["primary_declared_content_length"] is None
    assert not list(
        Draft202012Validator(read_json(ACQ_V3_SCHEMA)).iter_errors(manifest)
    )


def test_one_null_and_one_present_are_both_kept(tmp_path):
    metadata, primary = _declaring_transports(None, 777)
    result = _acquire(
        tmp_path, run_id="declared-mixed",
        metadata_transport=metadata, primary_transport=primary,
        transport_identity=SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY,
    )
    for record in read_json(result.acquisition_manifest_path)["acquisitions"]:
        assert record["filing_index_declared_content_length"] is None
        assert record["primary_declared_content_length"] == 777


def test_fixture_v01_manifest_is_unchanged_and_carries_no_declared_fields(tmp_path):
    result = _acquire(tmp_path, run_id="fixture-unchanged")
    manifest = read_json(result.acquisition_manifest_path)
    assert manifest["transport_kind"] == "fixture_replay"
    assert manifest["schema_versions"] == {
        "primary_document_acquisition_manifest": "0.1.0"
    }
    for record in manifest["acquisitions"]:
        assert "filing_index_declared_content_length" not in record
        assert "primary_declared_content_length" not in record
    assert not list(
        Draft202012Validator(read_json(ACQ_SCHEMA)).iter_errors(manifest)
    )
    assert list(Draft202012Validator(read_json(ACQ_V3_SCHEMA)).iter_errors(manifest))


def test_a_v02_shaped_artifact_without_the_fields_stays_valid(tmp_path):
    """Historical validity: v0.2 still accepts artifacts written before v0.3."""
    result = _acquire(
        tmp_path, run_id="as-v2",
        transport_identity=SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY,
    )
    manifest = read_json(result.acquisition_manifest_path)
    historical = json.loads(json.dumps(manifest))
    for record in historical["acquisitions"]:
        del record["filing_index_declared_content_length"]
        del record["primary_declared_content_length"]
    historical["schema_versions"] = {
        "primary_document_acquisition_manifest_v2": "0.2.0"
    }
    assert not list(
        Draft202012Validator(read_json(ACQ_V2_SCHEMA)).iter_errors(historical)
    )


CANARY_B_MANIFEST = (
    ROOT / "data" / "runs" / "primary-document-canary"
    / "primary-document-canary-frame-v1-20260816"
    / "primary_document_acquisition_manifest.json"
)


@pytest.mark.skipif(
    not CANARY_B_MANIFEST.exists(),
    reason="completed Canary B artifact absent; historical validity not checkable",
)
def test_the_completed_canary_b_artifact_remains_valid_and_unmigrated():
    """The real v0.2 artifact is untouched and still validates as v0.2."""
    artifact = read_json(CANARY_B_MANIFEST)
    assert artifact["schema_versions"] == {
        "primary_document_acquisition_manifest_v2": "0.2.0"
    }
    assert all(
        "filing_index_declared_content_length" not in a
        and "primary_declared_content_length" not in a
        for a in artifact["acquisitions"]
    )
    assert not list(
        Draft202012Validator(read_json(ACQ_V2_SCHEMA)).iter_errors(artifact)
    )


def test_fixture_manifest_is_rejected_by_the_v2_schema(tmp_path):
    result = _acquire(tmp_path)
    manifest = read_json(result.acquisition_manifest_path)
    assert not list(
        Draft202012Validator(read_json(ACQ_SCHEMA)).iter_errors(manifest)
    )
    assert list(Draft202012Validator(read_json(ACQ_V2_SCHEMA)).iter_errors(manifest))


# --- authority and failure semantics ---------------------------------------


def _failing_primary_transport(fail_on_accession: str):
    """Serve two accessions, then fail the third at the primary hop."""
    good = make_primary_document_fixture_replay_transport(
        FIXTURE_DIR, max_bytes=DOCUMENT_CEILING
    )

    def transport(url: str) -> DocumentTransportResponse:
        nodash = fail_on_accession.replace("-", "")
        if nodash in url.replace("-", ""):
            return DocumentTransportResponse(
                status_code=404, final_url=url, content=b""
            )
        return good(url)

    return transport


def test_later_failure_writes_no_bundle_and_no_acquisition_manifest(tmp_path):
    result = _acquire(
        tmp_path, run_id="late-failure",
        primary_transport=_failing_primary_transport("0009200003-22-000003"),
    )
    assert result.failure is not None
    assert result.failure.attempted_hop == "primary_document"
    assert result.failure.reason_code == "primary_http_failure"
    assert not (result.run_dir / BUNDLE_MANIFEST_FILENAME).exists()
    assert not (result.run_dir / ACQUISITION_MANIFEST_FILENAME).exists()
    assert (result.run_dir / FAILURE_RECEIPT_FILENAME).is_file()


def test_retained_primaries_persist_and_are_named_but_non_authoritative(tmp_path):
    """Not 'nothing persisted': earlier files remain and are declared."""
    result = _acquire(
        tmp_path, run_id="retained",
        primary_transport=_failing_primary_transport("0009200003-22-000003"),
    )
    retained = sorted(p.name for p in result.run_dir.glob("primary-*.html"))
    assert len(retained) == 2, retained
    receipt = read_json(result.failure_receipt_path)
    assert sorted(receipt["retained_raw_filenames"]) == retained
    assert "non-authoritative" in receipt["retention_note"]
    assert receipt["accessions_completed_before_failure"] == [
        "0009200001-22-000001", "0009200002-22-000002",
    ]


def test_the_packet_builder_cannot_consume_a_failed_run(tmp_path):
    """Enforced by the bundle manifest's absence, which the builder requires."""
    result = _acquire(
        tmp_path, run_id="unconsumable",
        primary_transport=_failing_primary_transport("0009200003-22-000003"),
    )
    with pytest.raises(PacketBundleError, match="missing bundle_manifest.json"):
        load_bundle(ROOT, result.run_dir)


def test_bundle_without_acquisition_manifest_is_accepted_by_the_builder(tmp_path):
    """The honest asymmetry, stated rather than enforced.

    A bundle manifest without an acquisition manifest is an incomplete
    acquisition-run record under operational policy, but the committed packet
    builder requires only the bundle and is not extended to refuse it.
    """
    result = _acquire(tmp_path, run_id="bundle-only")
    (result.run_dir / ACQUISITION_MANIFEST_FILENAME).unlink()
    _, entries, _ = load_bundle(ROOT, result.run_dir)
    assert len(entries) == 4  # accepted by the builder's contract
    # ...while this increment's own run-record check flags it as incomplete.
    assert not (result.run_dir / ACQUISITION_MANIFEST_FILENAME).exists()


def test_failure_receipt_records_the_active_kind_and_both_hops(tmp_path):
    result = _acquire(
        tmp_path, run_id="receipt-shape",
        primary_transport=_failing_primary_transport("0009200001-22-000001"),
    )
    receipt = read_json(result.failure_receipt_path)
    assert receipt["transport_kind"] == "fixture_replay"
    assert receipt["metadata_hop"]["max_bytes"] == METADATA_CEILING
    assert receipt["primary_document_hop"]["max_bytes"] == DOCUMENT_CEILING
    assert receipt["metadata_hop"]["transport_contract_hash"] == (
        receipt["primary_document_hop"]["transport_contract_hash"]
    )
    assert receipt["attempted_hop"] == "primary_document"
    assert receipt["retained_raw_filenames"] == []


def test_metadata_hop_failure_is_attributed_to_hop_one(tmp_path):
    def missing_index(url: str) -> DocumentTransportResponse:
        return DocumentTransportResponse(status_code=404, final_url=url, content=b"")

    result = _acquire(tmp_path, run_id="hop1", metadata_transport=missing_index)
    assert result.failure.attempted_hop == "filing_index"
    assert result.failure.reason_code == "metadata_http_failure"
    assert not (result.run_dir / BUNDLE_MANIFEST_FILENAME).exists()


# --- ceilings and plan grammar ---------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [("metadata_transport_max_bytes", 1234), ("primary_transport_max_bytes", 1234)],
)
def test_transport_ceiling_mismatch_refuses_before_any_request(tmp_path, field, value):
    sent: list[str] = []

    def recording(url: str) -> DocumentTransportResponse:
        sent.append(url)
        return DocumentTransportResponse(status_code=200, final_url=url, content=b"")

    with pytest.raises(PrimaryDocumentPlanError, match="does not equal the plan"):
        _acquire(tmp_path, metadata_transport=recording, primary_transport=recording,
                 **{field: value})
    assert sent == []
    assert not (tmp_path / "out").exists()


def test_index_page_over_ceiling_refuses(tmp_path):
    tight = make_filing_index_fixture_replay_transport(FIXTURE_DIR, max_bytes=100)
    payload = _plan_payload()
    payload["max_metadata_bytes"] = 100
    plan = _write_plan(tmp_path / "p.json", payload)
    result = _acquire(tmp_path, run_id="meta-ceiling", plan=plan,
                      metadata_transport=tight, metadata_transport_max_bytes=100)
    assert result.failure.reason_code == "metadata_over_ceiling"
    assert result.failure.attempted_hop == "filing_index"


def test_primary_document_over_ceiling_refuses(tmp_path):
    tight = make_primary_document_fixture_replay_transport(FIXTURE_DIR, max_bytes=100)
    payload = _plan_payload()
    payload["max_document_bytes"] = 100
    plan = _write_plan(tmp_path / "p.json", payload)
    result = _acquire(tmp_path, run_id="doc-ceiling", plan=plan,
                      primary_transport=tight, primary_transport_max_bytes=100)
    assert result.failure.reason_code == "primary_over_ceiling"
    assert result.failure.attempted_hop == "primary_document"
    assert not (result.run_dir / BUNDLE_MANIFEST_FILENAME).exists()


@pytest.mark.parametrize("key", ["max_metadata_bytes", "max_document_bytes"])
def test_missing_or_invalid_ceiling_is_refused(tmp_path, key):
    payload = _plan_payload()
    del payload[key]
    with pytest.raises(PrimaryDocumentPlanError, match=key):
        load_request_plan(_write_plan(tmp_path / "p.json", payload))
    payload = _plan_payload()
    payload[key] = 0
    with pytest.raises(PrimaryDocumentPlanError, match="explicit positive integer"):
        load_request_plan(_write_plan(tmp_path / "p2.json", payload))


def test_fpi_form_is_refused_naming_the_preserved_cohort(tmp_path):
    payload = _plan_payload()
    payload["documents"][0]["form"] = "20-F"
    with pytest.raises(PrimaryDocumentPlanError, match="preserved"):
        load_request_plan(_write_plan(tmp_path / "p.json", payload))


def test_repeated_accession_is_refused(tmp_path):
    payload = _plan_payload()
    payload["documents"].append(json.loads(json.dumps(payload["documents"][0])))
    with pytest.raises(PrimaryDocumentPlanError, match="more than once"):
        load_request_plan(_write_plan(tmp_path / "p.json", payload))


def test_ground_truth_mismatch_refuses(tmp_path):
    payload = _plan_payload()
    payload["documents"][0]["expected_primary_document"] = "not-the-primary.htm"
    plan = _write_plan(tmp_path / "p.json", payload)
    result = _acquire(tmp_path, run_id="gtm", plan=plan)
    assert result.failure.reason_code == "ground_truth_mismatch"
    assert result.failure.attempted_hop == "filing_index"


def test_ground_truth_source_hash_mismatch_refuses(tmp_path):
    payload = _plan_payload()
    payload["documents"][0]["ground_truth_source_sha256"] = "a" * 64
    plan = _write_plan(tmp_path / "p.json", payload)
    result = _acquire(tmp_path, run_id="gtsh", plan=plan)
    assert result.failure.reason_code == "ground_truth_mismatch"
    assert result.failure.attempted_hop == "primary_document"


# --- immutability -----------------------------------------------------------


def test_rerun_of_an_existing_run_id_is_refused(tmp_path):
    _acquire(tmp_path, run_id="immutable")
    before = sorted(p.name for p in (tmp_path / "out" / "immutable").iterdir())
    with pytest.raises(FileExistsError):
        _acquire(tmp_path, run_id="immutable")
    assert sorted(
        p.name for p in (tmp_path / "out" / "immutable").iterdir()
    ) == before


def test_dry_run_writes_nothing(tmp_path):
    result = _acquire(tmp_path, run_id="dry", dry_run=True)
    assert result.run_dir is None and result.bundle_manifest_path is None
    assert len(result.planned) == 3
    assert not (tmp_path / "out").exists()


# --- committed canary plan --------------------------------------------------


def test_committed_canary_plan_shape():
    planned, fields, _ = load_request_plan(CANARY_PLAN)
    assert len(planned) == 6
    assert sum(len(p.carrier_rows) for p in planned) == 8
    assert fields["max_metadata_bytes"] == 8388608
    assert fields["max_document_bytes"] == 268435456
    forms = [p.form for p in planned]
    assert forms.count("10-KT") == 3, "Canary B must include real 10-KT filings"
    shared = [p for p in planned if len(p.carrier_rows) > 1]
    assert len(shared) == 1 and len(shared[0].carrier_rows) == 3


def test_committed_canary_plan_binds_upstream_evidence():
    _, fields, _ = load_request_plan(CANARY_PLAN)
    assert fields["provenance"]["carrier_run_id"] == (
        "universe-baseline-carrier-frame-v1-20260816"
    )
    assert fields["provenance"]["carrier_manifest_sha256"] == (
        "50a2582f9a255c4402151aa4d963ce5d7bd7c952b8e4a5e77f4a7e7ce454521f"
    )
    assert fields["route_validation"]["probe_run_id"] == (
        "filing-index-probe-frame-v1-20260816-r2"
    )
    assert fields["route_validation"]["probe_manifest_sha256"] == (
        "7aa16a0ee076800634f4185ba9af47588f084fc9d0ed7a754cbeca81f258e270"
    )
    assert "never selection evidence" in fields["route_validation"]["note"]


def test_committed_canary_plan_records_filenames_but_not_source_hashes():
    """Only filename ground truth exists: no standalone primary was downloaded."""
    planned, _, _ = load_request_plan(CANARY_PLAN)
    assert all(p.expected_primary_document is not None for p in planned)
    assert all(p.ground_truth_source_sha256 is None for p in planned)


def test_committed_canary_directory_ciks_are_the_lowest_row_cik():
    planned, _, _ = load_request_plan(CANARY_PLAN)
    for entry in planned:
        assert entry.directory_cik == min(r.cik for r in entry.carrier_rows)
    shared = next(p for p in planned if len(p.carrier_rows) > 1)
    assert shared.directory_cik == "0000003146"
    assert {r.cik for r in shared.carrier_rows} == {
        "0000003146", "0000057183", "0001126956"
    }


# --- directory-CIK rule -----------------------------------------------------


def test_wrong_directory_cik_on_a_shared_accession_is_refused(tmp_path):
    """The plausible alternative — a non-lowest sharing CIK — is refused."""
    payload = _plan_payload()
    shared = next(d for d in payload["documents"] if len(d["carrier_rows"]) > 1)
    assert shared["directory_cik"] == "0009200003"
    shared["directory_cik"] = "0009200004"  # a real sharing filer, not the lowest
    with pytest.raises(PrimaryDocumentPlanError, match="not the lowest"):
        load_request_plan(_write_plan(tmp_path / "p.json", payload))


def test_wrong_directory_cik_on_a_regular_accession_is_refused(tmp_path):
    payload = _plan_payload()
    regular = payload["documents"][0]
    assert len(regular["carrier_rows"]) == 1
    regular["directory_cik"] = "0009999999"
    with pytest.raises(PrimaryDocumentPlanError, match="not the lowest"):
        load_request_plan(_write_plan(tmp_path / "p.json", payload))


def test_directory_cik_is_refused_before_any_url_is_derived(tmp_path):
    payload = _plan_payload()
    payload["documents"][0]["directory_cik"] = "0009999999"
    plan = _write_plan(tmp_path / "p.json", payload)
    sent: list[str] = []

    def recording(url: str) -> DocumentTransportResponse:
        sent.append(url)
        return DocumentTransportResponse(status_code=200, final_url=url, content=b"")

    with pytest.raises(PrimaryDocumentPlanError, match="not the lowest"):
        _acquire(tmp_path, plan=plan, metadata_transport=recording,
                 primary_transport=recording)
    assert sent == []
    assert not (tmp_path / "out").exists()


def test_correct_shared_directory_cik_yields_the_canonical_urls(tmp_path):
    planned, _, _ = load_request_plan(FIXTURE_PLAN)
    shared = next(p for p in planned if len(p.carrier_rows) > 1)
    assert shared.directory_cik == "0009200003"
    assert shared.filing_index_url == (
        "https://www.sec.gov/Archives/edgar/data/9200003/"
        "000920000322000003/0009200003-22-000003-index.htm"
    )
    result = _acquire(tmp_path, run_id="shared-urls")
    acquired = next(a for a in result.acquired if a.accession == shared.accession)
    assert acquired.primary_url == (
        "https://www.sec.gov/Archives/edgar/data/9200003/"
        "000920000322000003/shared-10k.htm"
    )


# --- ground-truth basis -----------------------------------------------------


def test_all_three_ground_truth_bases_are_exercised(tmp_path):
    result = _acquire(tmp_path)
    by_accession = {a.accession: a.ground_truth_basis for a in result.acquired}
    assert by_accession["0009200001-22-000001"] == (
        "expected_filename_and_source_sha256"
    )
    assert by_accession["0009200002-22-000002"] == "expected_filename_only"
    assert by_accession["0009200003-22-000003"] == "none"
    assert set(by_accession.values()) == set(GROUND_TRUTH_BASES)
    manifest = read_json(result.acquisition_manifest_path)
    assert {a["ground_truth_basis"] for a in manifest["acquisitions"]} == set(
        GROUND_TRUTH_BASES
    )
    assert all(
        "ground_truth_verified" not in a for a in manifest["acquisitions"]
    )


def test_ground_truth_basis_matches_the_gold(tmp_path):
    result = _acquire(tmp_path)
    got = [
        {"accession": a.accession, "ground_truth_basis": a.ground_truth_basis}
        for a in sorted(result.acquired, key=lambda x: x.accession)
    ]
    assert got == [
        {"accession": a["accession"], "ground_truth_basis": a["ground_truth_basis"]}
        for a in EXPECTED["acquisitions"]
    ]


def test_canary_b_claims_only_filename_ground_truth():
    """It must not claim source-byte truth it does not have."""
    planned, _, _ = load_request_plan(CANARY_PLAN)
    assert len(planned) == 6
    for entry in planned:
        assert entry.expected_primary_document is not None
        assert entry.ground_truth_source_sha256 is None
    # Every entry would therefore be recorded as filename-only.
    assert all(
        (
            "expected_filename_and_source_sha256"
            if p.ground_truth_source_sha256 is not None
            else "expected_filename_only"
            if p.expected_primary_document is not None
            else "none"
        )
        == "expected_filename_only"
        for p in planned
    )


def test_source_hash_without_expected_filename_is_refused(tmp_path):
    """The three bases stay exhaustive: a hash alone names nothing to check."""
    payload = _plan_payload()
    entry = payload["documents"][2]
    assert "expected_primary_document" not in entry
    entry["ground_truth_source_sha256"] = "a" * 64
    with pytest.raises(PrimaryDocumentPlanError,
                       match="requires expected_primary_document"):
        load_request_plan(_write_plan(tmp_path / "p.json", payload))


CARRIER_RUN = (
    ROOT / "data" / "runs" / "universe-baseline-carrier"
    / "universe-baseline-carrier-frame-v1-20260816"
    / "universe_baseline_carrier.jsonl"
)


def _local_baseline_candidates() -> tuple[dict[tuple[str, str], dict], dict[str, set[str]]]:
    """Read the frozen carrier read-only, indexed by row and by accession."""
    candidates: dict[tuple[str, str], dict] = {}
    by_accession: dict[str, set[str]] = {}
    for line in CARRIER_RUN.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["baseline_status"] != "baseline_candidate":
            continue
        if row["stratum"] != "domestic":
            continue
        key = (row["cik"], row["baseline_accession"])
        candidates[key] = row
        by_accession.setdefault(row["baseline_accession"], set()).add(row["cik"])
    return candidates, by_accession


@pytest.mark.skipif(
    not CARRIER_RUN.exists(),
    reason="local carrier run absent; Canary B rows not re-derivable",
)
def test_canary_b_rows_match_the_local_carrier_exactly():
    """Read-only: every planned row is a real baseline candidate.

    Also proves each directory_cik is the minimum CIK of the *complete*
    accession group in the carrier, not merely of the rows the plan lists.
    """
    candidates, by_accession = _local_baseline_candidates()
    planned, _, _ = load_request_plan(CANARY_PLAN)
    for entry in planned:
        for planned_row in entry.carrier_rows:
            row = candidates.get((planned_row.cik, entry.accession))
            assert row is not None, (planned_row.cik, entry.accession)
            assert row["baseline_form"] == entry.form
            assert row["stratum"] == planned_row.stratum == "domestic"
            assert row["baseline_filing_date"] == planned_row.baseline_filing_date
        # The plan lists the complete group, and the directory is its minimum.
        group = by_accession[entry.accession]
        assert {r.cik for r in entry.carrier_rows} == group, entry.accession
        assert entry.directory_cik == min(group), entry.accession


def test_committed_canary_plan_request_accounting():
    planned, _, _ = load_request_plan(CANARY_PLAN)
    assert 2 * len(planned) == 12
    assert len({p.accession for p in planned}) == 6


# --- the four-way contract matrix (plan v0.1/v0.2 x fixture/sec_live) -------


ACQ_V4_SCHEMA = (
    ROOT / "schemas" / "primary_document_acquisition_manifest.v4.schema.json"
)
ACQ_V5_SCHEMA = (
    ROOT / "schemas" / "primary_document_acquisition_manifest.v5.schema.json"
)


def _budgeted_payload(budget: int) -> dict:
    payload = _plan_payload()
    payload["plan_contract"] = "primary_document_request_plan@0.2.0"
    payload["max_retained_bytes"] = budget
    return payload


def _errs(schema_path: Path, payload: dict) -> list:
    return list(Draft202012Validator(read_json(schema_path)).iter_errors(payload))


def test_historical_schemas_are_byte_unchanged():
    """v0.1, v0.2 and v0.3 keep their own contract; nothing was widened."""
    for path, contract in (
        (ACQ_SCHEMA, "primary_document_request_plan@0.1.0"),
        (ACQ_V2_SCHEMA, "primary_document_request_plan@0.1.0"),
        (ACQ_V3_SCHEMA, "primary_document_request_plan@0.1.0"),
    ):
        schema = read_json(path)
        assert schema["properties"]["plan_contract"]["const"] == contract
        assert "retained_byte_budget" not in schema["properties"]
        assert schema["additionalProperties"] is False


def test_v4_and_v5_declare_plan_v02_and_require_the_budget_fields():
    for path, key in ((ACQ_V4_SCHEMA, "primary_document_acquisition_manifest_v4"),
                      (ACQ_V5_SCHEMA, "primary_document_acquisition_manifest_v5")):
        schema = read_json(path)
        assert schema["properties"]["plan_contract"]["const"] == (
            "primary_document_request_plan@0.2.0"
        )
        for field in ("retained_byte_budget", "retained_bytes_total",
                      "budget_enforcement"):
            assert field in schema["required"], (path.name, field)
        assert schema["properties"]["schema_versions"]["required"] == [key]
        assert schema["additionalProperties"] is False
    # The successors differ by transport lineage, not only by the budget.
    assert "transport_contract" in read_json(ACQ_V5_SCHEMA)["required"]
    assert "transport_contract" not in read_json(ACQ_V4_SCHEMA)["required"]


def test_fixture_v02_run_validates_against_v4_and_is_rejected_by_v01(tmp_path):
    plan = _write_plan(tmp_path / "p.json", _budgeted_payload(10_000_000))
    result = _acquire(tmp_path, plan=plan)
    manifest = read_json(result.run_dir / ACQUISITION_MANIFEST_FILENAME)
    assert manifest["plan_contract"] == "primary_document_request_plan@0.2.0"
    assert set(manifest["schema_versions"]) == {
        "primary_document_acquisition_manifest_v4"
    }
    assert manifest["retained_byte_budget"] == 10_000_000
    assert manifest["retained_bytes_total"] == sum(
        a["source_byte_length"] for a in manifest["acquisitions"]
    )
    assert _errs(ACQ_V4_SCHEMA, manifest) == []
    assert _errs(ACQ_SCHEMA, manifest), "a v0.2 fixture manifest is not a v0.1 one"
    assert _errs(ACQ_V5_SCHEMA, manifest), "fixture and sec_live must not mix"


def test_fixture_v01_run_still_validates_against_the_unchanged_v01(tmp_path):
    result = _acquire(tmp_path)
    manifest = read_json(result.run_dir / ACQUISITION_MANIFEST_FILENAME)
    assert manifest["plan_contract"] == "primary_document_request_plan@0.1.0"
    assert set(manifest["schema_versions"]) == {
        "primary_document_acquisition_manifest"
    }
    assert "retained_byte_budget" not in manifest
    assert _errs(ACQ_SCHEMA, manifest) == []
    assert _errs(ACQ_V4_SCHEMA, manifest), "v0.1 must not validate as v0.4"


def test_live_v02_run_validates_against_v5_and_is_rejected_by_v3(tmp_path):
    plan = _write_plan(tmp_path / "p.json", _budgeted_payload(10_000_000))
    result = _acquire(tmp_path, plan=plan,
                      transport_identity=SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY)
    manifest = read_json(result.run_dir / ACQUISITION_MANIFEST_FILENAME)
    assert manifest["transport_kind"] == "sec_live"
    assert set(manifest["schema_versions"]) == {
        "primary_document_acquisition_manifest_v5"
    }
    assert _errs(ACQ_V5_SCHEMA, manifest) == []
    assert _errs(ACQ_V3_SCHEMA, manifest), "a v0.2 live manifest is not a v0.3 one"
    assert _errs(ACQ_V4_SCHEMA, manifest), "sec_live and fixture must not mix"


def test_live_v01_run_still_validates_against_the_unchanged_v3(tmp_path):
    result = _acquire(tmp_path, transport_identity=SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY)
    manifest = read_json(result.run_dir / ACQUISITION_MANIFEST_FILENAME)
    assert set(manifest["schema_versions"]) == {
        "primary_document_acquisition_manifest_v3"
    }
    assert _errs(ACQ_V3_SCHEMA, manifest) == []
    assert _errs(ACQ_V5_SCHEMA, manifest), "v0.3 must not validate as v0.5"


def test_budget_refusal_writes_no_authoritative_manifest(tmp_path):
    """Checked against retained bytes, and the refused document is not written."""
    plan = _write_plan(tmp_path / "p.json", _budgeted_payload(1))
    result = _acquire(tmp_path, plan=plan)
    assert not (result.run_dir / ACQUISITION_MANIFEST_FILENAME).exists()
    assert not (result.run_dir / BUNDLE_MANIFEST_FILENAME).exists()
    receipt = read_json(result.run_dir / FAILURE_RECEIPT_FILENAME)
    assert receipt["reason_code"] == "shard_retained_byte_budget_exhausted"
    assert receipt["retained_raw_filenames"] == []
    assert not list(result.run_dir.glob("primary-*.html"))
    assert "max_retained_bytes 1" in receipt["detail"]


def test_budget_is_not_read_from_content_length(tmp_path):
    """A declared length far below the body must not buy extra headroom."""
    payload = _budgeted_payload(600)
    plan = _write_plan(tmp_path / "p.json", payload)

    def lying_primary(url: str):
        real = make_primary_document_fixture_replay_transport(
            FIXTURE_DIR, max_bytes=268435456)(url)
        return DocumentTransportResponse(
            status_code=real.status_code, final_url=real.final_url,
            content=real.content, declared_content_length=1,
            bytes_received=real.bytes_received,
        )

    result = _acquire(tmp_path, plan=plan, primary_transport=lying_primary)
    receipt = read_json(result.run_dir / FAILURE_RECEIPT_FILENAME)
    assert receipt["reason_code"] == "shard_retained_byte_budget_exhausted"


def test_plan_v01_may_not_declare_a_budget(tmp_path):
    payload = _plan_payload()
    payload["max_retained_bytes"] = 1000
    with pytest.raises(PrimaryDocumentPlanError, match="0.2.0 field"):
        load_request_plan(_write_plan(tmp_path / "p.json", payload))


def test_plan_v02_must_declare_a_budget(tmp_path):
    payload = _plan_payload()
    payload["plan_contract"] = "primary_document_request_plan@0.2.0"
    with pytest.raises(PrimaryDocumentPlanError, match="requires max_retained_bytes"):
        load_request_plan(_write_plan(tmp_path / "p.json", payload))


@pytest.mark.parametrize("value", [0, -1, "1000", 1.5, True])
def test_budget_must_be_a_positive_integer(tmp_path, value):
    payload = _budgeted_payload(1)
    payload["max_retained_bytes"] = value
    with pytest.raises(PrimaryDocumentPlanError, match="positive integer"):
        load_request_plan(_write_plan(tmp_path / "p.json", payload))


def test_an_unknown_plan_contract_is_refused(tmp_path):
    payload = _plan_payload()
    payload["plan_contract"] = "primary_document_request_plan@9.9.9"
    with pytest.raises(PrimaryDocumentPlanError, match="must declare one of"):
        load_request_plan(_write_plan(tmp_path / "p.json", payload))


def test_both_committed_v01_plans_are_unchanged_and_still_load():
    for path in (CANARY_PLAN, SHELL_PLAN):
        _, fields, _ = load_request_plan(path)
        assert fields["plan_contract"] == "primary_document_request_plan@0.1.0"
        assert fields["max_retained_bytes"] is None


# --- committed shell-validation canary plan (planned, never executed) -------


def test_shell_validation_plan_cohort_and_request_accounting():
    planned, fields, _ = load_request_plan(SHELL_PLAN)
    assert len(planned) == 12
    assert len({p.accession for p in planned}) == 12
    assert sum(len(p.carrier_rows) for p in planned) == 23
    assert 2 * len(planned) == 24
    assert fields["max_metadata_bytes"] == 8388608
    assert fields["max_document_bytes"] == 268435456


def test_shell_validation_plan_shared_groups_and_forms():
    planned, _, _ = load_request_plan(SHELL_PLAN)
    shared = sorted(len(p.carrier_rows) for p in planned if len(p.carrier_rows) > 1)
    assert shared == [3, 4, 7]
    forms = [p.form for p in planned]
    assert forms.count("10-KT") == 1
    assert forms.count("10-K") == 11
    # The three combined filings supply 14 of the 23 rows for 6 of 24 requests.
    assert sum(shared) == 14


def test_shell_validation_plan_asserts_ground_truth_for_spire_alone():
    """Eleven accessions assert neither field; none is invented."""
    planned, _, _ = load_request_plan(SHELL_PLAN)
    with_truth = [p for p in planned if p.expected_primary_document is not None]
    assert len(with_truth) == 1
    spire = with_truth[0]
    assert spire.accession == "0001437749-22-027522"
    assert spire.expected_primary_document == "spre20220930_10k.htm"
    assert spire.ground_truth_source_sha256 == (
        "5ade73ed9050f0c5dec5c7f08a7b128511f5a4b5b71d2100ae56a78b099cbc21"
    )
    for entry in planned:
        if entry is spire:
            continue
        assert entry.expected_primary_document is None
        assert entry.ground_truth_source_sha256 is None


def test_shell_validation_plan_binds_the_same_upstream_evidence():
    _, fields, _ = load_request_plan(SHELL_PLAN)
    _, canary_fields, _ = load_request_plan(CANARY_PLAN)
    assert fields["provenance"] == canary_fields["provenance"]
    assert fields["route_validation"] == canary_fields["route_validation"]
    assert "never selection evidence" in fields["route_validation"]["note"]


def test_shell_validation_plan_does_not_authorize_a_request():
    payload = read_json(SHELL_PLAN)
    assert "does not authorize a live request" in payload["description"]


@pytest.mark.skipif(
    not CARRIER_RUN.exists(),
    reason="local carrier run absent; planned rows not re-derivable",
)
def test_shell_validation_rows_match_the_local_carrier_exactly():
    """Read-only: every planned row is a real domestic baseline candidate.

    Reuses the Canary-B rederivation: each listed group must be the *complete*
    carrier group for its accession, and each directory_cik the group minimum.
    """
    candidates, by_accession = _local_baseline_candidates()
    planned, _, _ = load_request_plan(SHELL_PLAN)
    for entry in planned:
        for planned_row in entry.carrier_rows:
            row = candidates.get((planned_row.cik, entry.accession))
            assert row is not None, (planned_row.cik, entry.accession)
            assert row["baseline_form"] == entry.form
            assert row["stratum"] == planned_row.stratum == "domestic"
            assert row["baseline_filing_date"] == planned_row.baseline_filing_date
        group = by_accession[entry.accession]
        assert {r.cik for r in entry.carrier_rows} == group, entry.accession
        assert entry.directory_cik == min(group), entry.accession


# --- ADR-094 pre-registration ------------------------------------------------


def _adr_094_preregistration() -> str:
    text = DECISION_LOG.read_text(encoding="utf-8")
    start = text.index("### Planned shell-validation canary")
    return text[start:text.index("## Open decisions", start)]


def _adr_094_prose() -> str:
    """The same section with runs of whitespace collapsed.

    Phrase assertions must survive markdown line wrapping, which is a
    formatting choice and not part of what the entry claims.
    """
    return " ".join(_adr_094_preregistration().split())


def test_adr_094_preregistration_covers_every_planned_row():
    """The stored register is row-level and matches the committed plan."""
    section = _adr_094_preregistration()
    planned, _, _ = load_request_plan(SHELL_PLAN)
    rows = [
        line for line in section.splitlines()
        if line.startswith("| ") and "| 00" in line
    ]
    assert len(rows) == 23
    registered = {
        (cells[2].strip(), cells[3].strip())
        for cells in (line.split("|") for line in rows)
    }
    assert registered == {
        (row.cik, entry.accession)
        for entry in planned for row in entry.carrier_rows
    }
    verdicts = [line.split("|")[4].strip() for line in rows]
    assert verdicts.count("true") == 4
    assert verdicts.count("false") == 5
    assert verdicts.count("unknown") == 12
    assert verdicts.count("no_prediction") == 2
    assert len(verdicts) == 4 + 5 + 12 + 2 == 23


def test_adr_094_preregistration_states_its_totals_and_status():
    prose = _adr_094_prose()
    assert "4 + 5 + 12 + 2 = 23" in prose
    assert "9 + 1 + 2" in prose
    assert "not gold data and not an executed run" in prose
    assert "pre-registration category, not a determination outcome" in prose
    # The three layers are named and kept apart.
    for layer in ("*Observed labels*", "*Hypotheses*", "*Predictions*"):
        assert layer in prose
    # #11 is retained in this same canary rather than replaced or split off.
    assert "0001888524-22-003211" in prose
    assert "retained inside this same canary" in prose


def test_adr_094_records_the_corrected_h1_falsification_rule():
    prose = _adr_094_prose()
    assert "H1 falsification rule" in prose
    assert "is **consistent** with H1" in prose
    assert "two or more carrier rows of the same accession return determinate" in prose
    assert "without the required CIK-binding evidence" in prose
    # The superseded reading must not reappear.
    assert "would contradict H1" not in prose


# --- boundaries -------------------------------------------------------------


def test_module_has_no_network_or_dera_dependency():
    """Checked against imports, not substrings.

    The module legitimately contains the word "requests" in count fields such
    as ``total_requests``, so the guard reads the import graph instead.
    """
    import ast

    path = (
        ROOT / "src" / "dynamic_ai_products" / "universe"
        / "primary_document_acquisition.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    roots = {name.split(".")[0] for name in imported}
    assert "httpx" not in roots
    assert "requests" not in roots
    assert "socket" not in roots
    assert not any("dera" in name for name in imported), sorted(imported)


def test_cli_acquire_primary_docs_mode(tmp_path):
    import subprocess
    import sys

    completed = subprocess.run(
        [
            sys.executable, str(CLI),
            "--mode", "acquire-primary-docs",
            "--request-plan", str(FIXTURE_PLAN),
            "--replay-dir", str(FIXTURE_DIR),
            "--output-dir", str(tmp_path / "out"),
            "--run-id", "cli-primary",
        ],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["counts"] == EXPECTED["counts"]
    assert payload["bundle_manifest_path"].endswith(BUNDLE_MANIFEST_FILENAME)


def test_cli_rejects_cross_mode_flags(tmp_path):
    import subprocess
    import sys

    completed = subprocess.run(
        [
            sys.executable, str(CLI),
            "--mode", "acquire-primary-docs",
            "--request-plan", str(FIXTURE_PLAN),
            "--replay-dir", str(FIXTURE_DIR),
            "--dera-dir", str(tmp_path),
            "--output-dir", str(tmp_path / "out"),
            "--run-id", "cli-primary-bad",
        ],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode != 0
    assert "does not accept" in completed.stderr
