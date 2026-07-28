"""Stage 01/03 adoption: hash re-verification, immutability, temporal rule."""

from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

from dynamic_ai_products.ingestion.adoption import (  # noqa: E402
    adopt_sec_snapshots,
    build_sec_candidates,
    build_source_document,
    temporal_validity_for,
    verify_raw_bytes,
)
from dynamic_ai_products.ingestion.errors import IngestionError  # noqa: E402
from ingestion_test_helpers import (  # noqa: E402
    COMPANY_ID,
    CUTOFF,
    PRIMARY_DOCUMENT,
    build_raw_fixture,
)


def test_verify_raw_bytes_accepts_matching_hashes(tmp_path: Path) -> None:
    raw_directory, receipt, _ = build_raw_fixture(tmp_path)
    verified = verify_raw_bytes(raw_directory, receipt)
    assert set(verified) == {"submissions", "filing_index", "primary_document"}


def test_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    raw_directory, receipt, _ = build_raw_fixture(tmp_path)
    receipt["retrievals"][2]["sha256"] = "f" * 64
    with pytest.raises(IngestionError) as excinfo:
        verify_raw_bytes(raw_directory, receipt)
    assert excinfo.value.reason_code == "raw_bytes_hash_mismatch"


def test_missing_raw_file_fails_closed(tmp_path: Path) -> None:
    raw_directory, receipt, _ = build_raw_fixture(tmp_path)
    (raw_directory / PRIMARY_DOCUMENT).unlink()
    with pytest.raises(IngestionError) as excinfo:
        verify_raw_bytes(raw_directory, receipt)
    assert excinfo.value.reason_code == "receipt_unavailable"


def test_empty_receipt_fails_closed(tmp_path: Path) -> None:
    raw_directory, _, _ = build_raw_fixture(tmp_path)
    with pytest.raises(IngestionError) as excinfo:
        verify_raw_bytes(raw_directory, {"retrievals": []})
    assert excinfo.value.reason_code == "receipt_unavailable"


def test_raw_files_are_never_mutated(tmp_path: Path) -> None:
    raw_directory, receipt, receipt_sha256 = build_raw_fixture(tmp_path)
    before = {
        p.name: sha256(p.read_bytes()).hexdigest()
        for p in sorted(raw_directory.iterdir())
    }
    verify_raw_bytes(raw_directory, receipt)
    build_sec_candidates(
        company_id=COMPANY_ID, receipt=receipt, observation_cutoff_date=CUTOFF
    )
    adopt_sec_snapshots(
        company_id=COMPANY_ID,
        receipt=receipt,
        receipt_sha256=receipt_sha256,
        raw_directory=raw_directory,
    )
    after = {
        p.name: sha256(p.read_bytes()).hexdigest()
        for p in sorted(raw_directory.iterdir())
    }
    assert before == after
    assert set(before) == {"submissions.json", "filing-index.json", PRIMARY_DOCUMENT}


# --- SPEC-003 acceptance ------------------------------------------------------


def test_hash_coverage_is_total(tmp_path: Path) -> None:
    _, receipt, _ = build_raw_fixture(tmp_path)
    rows = build_sec_candidates(
        company_id=COMPANY_ID, receipt=receipt, observation_cutoff_date=CUTOFF
    )
    assert len(rows) == len(receipt["retrievals"])
    assert all(len(row["content_sha256"]) == 64 for row in rows)


def test_retry_and_error_fields_are_complete(tmp_path: Path) -> None:
    raw_directory, receipt, receipt_sha256 = build_raw_fixture(tmp_path)
    records = adopt_sec_snapshots(
        company_id=COMPANY_ID,
        receipt=receipt,
        receipt_sha256=receipt_sha256,
        raw_directory=raw_directory,
    )
    schema = json.loads(
        Path("schemas/snapshot_manifest.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for record in records:
        validator.validate(record)
        assert record["retry_count"] == 0
        assert record["recollected"] is False
        assert record["adoption_mode"] == "existing_raw_bytes_reverified"


def test_candidate_rows_conform_to_schema(tmp_path: Path) -> None:
    _, receipt, _ = build_raw_fixture(tmp_path)
    rows = build_sec_candidates(
        company_id=COMPANY_ID, receipt=receipt, observation_cutoff_date=CUTOFF
    )
    schema = json.loads(
        Path("schemas/sec_source_candidate.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for row in rows:
        validator.validate(row)


# --- Temporal policy ----------------------------------------------------------


def test_publication_date_equal_to_cutoff_is_valid() -> None:
    assert temporal_validity_for("2025-02-12", "2025-02-12") == "valid"


def test_publication_date_after_cutoff_is_invalid() -> None:
    assert temporal_validity_for("2025-02-13", "2025-02-12") == "invalid"


def test_filing_after_cutoff_fails_closed(tmp_path: Path) -> None:
    _, receipt, _ = build_raw_fixture(tmp_path)
    receipt["identity"]["filing_date"] = "2025-03-01"
    with pytest.raises(IngestionError) as excinfo:
        build_sec_candidates(
            company_id=COMPANY_ID, receipt=receipt, observation_cutoff_date=CUTOFF
        )
    assert excinfo.value.reason_code == "temporally_invalid"


def test_source_document_carries_raw_content_hash(tmp_path: Path) -> None:
    _, receipt, _ = build_raw_fixture(tmp_path)
    document = build_source_document(
        company_id=COMPANY_ID,
        receipt=receipt,
        observation_cutoff_date=CUTOFF,
        primary_document=PRIMARY_DOCUMENT,
    )
    schema = json.loads(
        Path("schemas/source_document.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(document)
    assert document["temporal_validity"] == "valid"
    assert document["content_hash"] == receipt["retrievals"][2]["sha256"]


def test_missing_primary_document_fails_closed(tmp_path: Path) -> None:
    _, receipt, _ = build_raw_fixture(tmp_path)
    with pytest.raises(IngestionError) as excinfo:
        build_source_document(
            company_id=COMPANY_ID,
            receipt=receipt,
            observation_cutoff_date=CUTOFF,
            primary_document="absent.htm",
        )
    assert excinfo.value.reason_code == "receipt_unavailable"
