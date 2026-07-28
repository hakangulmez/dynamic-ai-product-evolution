"""Stage 03 raw storage: write-once, content addressing, safe path segments."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.collection.errors import CollectionError
from dynamic_ai_products.collection.web_snapshot import (
    ALLOWED_EXTENSIONS,
    build_snapshot_record,
    historical_validity_for,
    raw_storage_path,
    store_raw_bytes,
)

COMPANY = "CIK0001404655"
BODY = b"<html>page</html>"
DIGEST = sha256(BODY).hexdigest()
CUTOFF = "2025-02-12"


def _store(tmp_path: Path, **overrides):
    kwargs = {
        "raw_root": tmp_path / "raw",
        "company_id": COMPANY,
        "content_family": "product_pages",
        "date_key": "2025-01-01",
        "content_sha256": DIGEST,
        "extension": "html",
        "data": BODY,
    }
    kwargs.update(overrides)
    return store_raw_bytes(**kwargs)


def test_path_segments_are_all_validated(tmp_path: Path) -> None:
    path = raw_storage_path(
        raw_root=tmp_path,
        company_id=COMPANY,
        content_family="developer_docs",
        date_key="2025-02-12",
        content_sha256=DIGEST,
        extension="html",
    )
    assert path.parts[-5:] == (
        "web",
        COMPANY,
        "developer_docs",
        "2025-02-12",
        f"{DIGEST}.html",
    )


@pytest.mark.parametrize(
    "bad,code",
    [
        ({"company_id": "hubspot"}, "date_key_invalid"),
        ({"content_family": "press"}, "request_plan_invalid"),
        ({"content_sha256": "xyz"}, "content_hash_mismatch"),
        ({"extension": "exe"}, "date_key_invalid"),
        ({"date_key": "2026-07-28T13:38:49+00:00"}, "date_key_invalid"),
        ({"date_key": "../etc"}, "date_key_invalid"),
    ],
)
def test_invalid_path_segment_is_refused(tmp_path: Path, bad: dict, code: str) -> None:
    kwargs = {
        "raw_root": tmp_path,
        "company_id": COMPANY,
        "content_family": "product_pages",
        "date_key": "2025-01-01",
        "content_sha256": DIGEST,
        "extension": "html",
    }
    kwargs.update(bad)
    with pytest.raises(CollectionError) as excinfo:
        raw_storage_path(**kwargs)
    assert excinfo.value.reason_code == code


def test_extensions_are_a_closed_allowlist() -> None:
    assert ALLOWED_EXTENSIONS == ("html", "pdf", "json", "txt")


def test_store_writes_once_and_verifies(tmp_path: Path) -> None:
    path = _store(tmp_path)
    assert path.read_bytes() == BODY
    assert sha256(path.read_bytes()).hexdigest() == DIGEST


def test_second_store_refuses_and_leaves_bytes(tmp_path: Path) -> None:
    path = _store(tmp_path)
    with pytest.raises(CollectionError) as excinfo:
        _store(tmp_path)
    assert excinfo.value.reason_code == "destination_exists"
    assert path.read_bytes() == BODY


def test_declared_hash_mismatch_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CollectionError) as excinfo:
        _store(tmp_path, content_sha256="a" * 64)
    assert excinfo.value.reason_code in {"content_hash_mismatch"}


# --- Historical validity ------------------------------------------------------


def test_dated_document_uses_publication_date() -> None:
    assert (
        historical_validity_for(
            access_channel="live",
            temporal_route="dated_document",
            publication_date="2025-02-12",
            snapshot_timestamp=None,
            observation_cutoff_date=CUTOFF,
        )
        == "valid"
    )
    assert (
        historical_validity_for(
            access_channel="live",
            temporal_route="dated_document",
            publication_date="2025-02-13",
            snapshot_timestamp=None,
            observation_cutoff_date=CUTOFF,
        )
        == "invalid"
    )


def test_archive_route_uses_snapshot_timestamp() -> None:
    assert (
        historical_validity_for(
            access_channel="archive",
            temporal_route="archive",
            publication_date=None,
            snapshot_timestamp="2025-01-05T00:00:00+00:00",
            observation_cutoff_date=CUTOFF,
        )
        == "valid"
    )
    assert (
        historical_validity_for(
            access_channel="archive",
            temporal_route="archive",
            publication_date=None,
            snapshot_timestamp="2026-07-28T00:00:00+00:00",
            observation_cutoff_date=CUTOFF,
        )
        == "invalid"
    )


def test_missing_date_is_uncertain_not_guessed() -> None:
    assert (
        historical_validity_for(
            access_channel="archive",
            temporal_route="archive",
            publication_date=None,
            snapshot_timestamp=None,
            observation_cutoff_date=CUTOFF,
        )
        == "uncertain"
    )


def test_archive_route_requires_archive_channel() -> None:
    with pytest.raises(CollectionError) as excinfo:
        historical_validity_for(
            access_channel="live",
            temporal_route="archive",
            publication_date=None,
            snapshot_timestamp="2025-01-01T00:00:00+00:00",
            observation_cutoff_date=CUTOFF,
        )
    assert excinfo.value.reason_code == "temporal_route_inconsistent"


def test_snapshot_record_conforms_to_schema() -> None:
    record = build_snapshot_record(
        company_id=COMPANY,
        candidate_id="0" * 32,
        content_family="product_pages",
        access_channel="archive",
        source_url="https://www.hubspot.com/products/marketing",
        archive_url="https://web.archive.example/web/2025/x",
        archive_host="web.archive.example",
        requested_url="https://web.archive.example/web/2025/x",
        final_url="https://web.archive.example/web/2025/x",
        redirect_hops=[],
        http_status=200,
        retry_count=0,
        byte_count=len(BODY),
        content_sha256=DIGEST,
        retrieval_timestamp="2026-07-28T12:00:00+00:00",
        publication_date=None,
        snapshot_timestamp="2025-01-01T00:00:00+00:00",
        historical_validity="valid",
        raw_path="data/raw/web/x",
    )
    schema = json.loads(
        Path("schemas/web_snapshot_manifest.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(record)
    assert record["recollected"] is False
