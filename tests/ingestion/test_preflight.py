"""Preflight orchestration: verdicts, bindings, stops, injected identity."""

from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

from dynamic_ai_products.ingestion import preflight as pf  # noqa: E402
from dynamic_ai_products.ingestion.errors import IngestionError  # noqa: E402
from ingestion_test_helpers import (  # noqa: E402
    COMPANY_ID,
    PRIMARY_DOCUMENT,
    preflight_kwargs,
)


def _manifest_schema() -> Draft202012Validator:
    schema = json.loads(
        Path("schemas/ingestion_preflight_manifest.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_happy_path_emits_one_verdict(tmp_path: Path) -> None:
    result = pf.run_ingestion_preflight(**preflight_kwargs(tmp_path))
    assert result.verdict == "ready_for_extraction"
    assert result.manifest["verdict"] == "ready_for_extraction"
    _manifest_schema().validate(result.manifest)


def test_manifest_binds_every_artifact_by_sha256(tmp_path: Path) -> None:
    result = pf.run_ingestion_preflight(**preflight_kwargs(tmp_path))
    bindings = result.manifest["artifact_bindings"]
    assert len(bindings) == 6, "the manifest binds the six artifacts it precedes"
    for key, digest in bindings.items():
        assert len(digest) == 64
    # Each binding matches the bytes actually published.
    published = {
        p.name: sha256(p.read_bytes()).hexdigest()
        for p in result.run_root.rglob("*")
        if p.is_file()
    }
    assert published["documents.parquet"] == bindings["normalized_documents"]
    assert published["passages.parquet"] == bindings["normalized_passages"]
    assert published["source_family_coverage.json"] == bindings["source_family_coverage"]


def test_manifest_asserts_no_prompt_and_no_model(tmp_path: Path) -> None:
    result = pf.run_ingestion_preflight(**preflight_kwargs(tmp_path))
    assert result.manifest["prompt_hash"] is None
    assert result.manifest["model_route"] is None
    assert result.manifest["retry_count"] == 0


def test_manifest_carries_the_transform_ledger(tmp_path: Path) -> None:
    result = pf.run_ingestion_preflight(**preflight_kwargs(tmp_path))
    ledger = result.manifest["transform_ledger"]
    assert ledger["normalizer_version"] == "sec_html_item_span_v1"
    assert ledger["transform_chain"] == [
        "markup_tag_removal",
        "html_entity_decoding",
        "whitespace_collapse",
    ]
    assert ledger["passages"], "the ledger maps passages to raw-byte offsets"


@pytest.mark.parametrize("field", ["code_commit", "run_created_at"])
def test_missing_injected_identity_fails_closed(tmp_path: Path, field: str) -> None:
    kwargs = dict(preflight_kwargs(tmp_path), **{field: "   "})
    with pytest.raises(IngestionError) as excinfo:
        pf.run_ingestion_preflight(**kwargs)
    assert excinfo.value.reason_code == "run_identity_invalid"


def test_hash_mismatch_stops_before_any_staging(tmp_path: Path) -> None:
    kwargs = preflight_kwargs(tmp_path)
    kwargs["receipt"]["retrievals"][2]["sha256"] = "f" * 64
    with pytest.raises(IngestionError) as excinfo:
        pf.run_ingestion_preflight(**kwargs)
    assert excinfo.value.reason_code == "raw_bytes_hash_mismatch"
    assert list(kwargs["runs_root"].iterdir()) == []


def test_temporally_invalid_filing_stops_before_any_staging(tmp_path: Path) -> None:
    kwargs = preflight_kwargs(tmp_path)
    kwargs["receipt"]["identity"]["filing_date"] = "2025-06-01"
    with pytest.raises(IngestionError) as excinfo:
        pf.run_ingestion_preflight(**kwargs)
    assert excinfo.value.reason_code == "temporally_invalid"
    assert list(kwargs["runs_root"].iterdir()) == []


def test_zero_evidence_stop_writes_nothing(tmp_path: Path) -> None:
    kwargs = preflight_kwargs(tmp_path)
    # A markup-only span normalizes to nothing, so no passage is admissible.
    kwargs["span_start_offset"] = 0
    kwargs["span_end_offset"] = len(b"<html><body>")
    with pytest.raises(IngestionError) as excinfo:
        pf.run_ingestion_preflight(**kwargs)
    assert excinfo.value.reason_code == "zero_evidence_stop"
    assert list(kwargs["runs_root"].iterdir()) == []


def test_zero_evidence_stop_report_is_report_only() -> None:
    report = pf.zero_evidence_stop_report(
        run_id="ing-" + "0" * 32, company_id=COMPANY_ID, reason="no admissible passages"
    )
    assert report["verdict"] == "stopped"
    assert report["published"] is False
    assert report["authoritative_manifest_written"] is False


def test_blank_stop_reason_is_refused() -> None:
    with pytest.raises(IngestionError) as excinfo:
        pf.zero_evidence_stop_report(
            run_id="ing-" + "0" * 32, company_id=COMPANY_ID, reason="  "
        )
    assert excinfo.value.reason_code == "stop_reason_blank"


def test_missing_primary_document_stops(tmp_path: Path) -> None:
    kwargs = dict(preflight_kwargs(tmp_path), primary_document="absent.htm")
    with pytest.raises(IngestionError) as excinfo:
        pf.run_ingestion_preflight(**kwargs)
    assert excinfo.value.reason_code == "receipt_unavailable"
    assert list(kwargs["runs_root"].iterdir()) == []


def test_coverage_artifact_records_not_attempted(tmp_path: Path) -> None:
    result = pf.run_ingestion_preflight(**preflight_kwargs(tmp_path))
    coverage = json.loads(
        (result.run_root / "manifests" / "source_family_coverage.json").read_text(
            encoding="utf-8"
        )
    )
    states = {
        e["source_family"]: e["coverage_state"] for e in coverage["required_families"]
    }
    assert states["sec_edgar"] == "available_and_retrieved"
    assert set(states.values()) == {"available_and_retrieved", "not_attempted"}
    assert coverage["optional_families"][0]["source_family"] == "newsroom"


def test_snapshot_records_declare_no_recollection(tmp_path: Path) -> None:
    result = pf.run_ingestion_preflight(**preflight_kwargs(tmp_path))
    lines = (
        (result.run_root / "manifests" / "snapshot_manifest.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    records = [json.loads(line) for line in lines]
    assert records
    assert all(record["recollected"] is False for record in records)
    assert all(record["document_filename"] for record in records)
    assert any(record["document_filename"] == PRIMARY_DOCUMENT for record in records)
