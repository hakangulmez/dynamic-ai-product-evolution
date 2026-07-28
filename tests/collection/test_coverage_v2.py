"""Coverage v2: two dimensions, derived legacy bridge, no surviving not_attempted."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.collection.coverage_v2 import (
    COVERAGE_CONTRACT_V2,
    build_source_family_coverage_v2,
)
from dynamic_ai_products.collection.errors import CollectionError

COMPANY = "CIK0001404655"
CUTOFF = "2025-02-12"
PARENT = "aacc8cdb774f6cb28180d326c798f6b32b55c62a1f5cc7af2168f56c75df6bbb"


def _build(**overrides):
    kwargs = {
        "company_id": COMPANY,
        "observation_cutoff_date": CUTOFF,
        "content_family_states": {
            "official_ir": "available_and_retrieved",
            "product_pages": "available_and_retrieved",
            "developer_docs": "not_found",
        },
        "content_family_reasons": {"developer_docs": "no archived capture on or before cutoff"},
        "admitted_counts": {"official_ir": 1, "product_pages": 1},
        "channel_admitted": {"live": 1, "archive": 1},
        "channel_temporally_valid": {"live": 1, "archive": 1},
        "inherited_sec_edgar_state": "available_and_retrieved",
        "parent_manifest_sha256": PARENT,
    }
    kwargs.update(overrides)
    return build_source_family_coverage_v2(**kwargs)


def test_contract_and_schema() -> None:
    artifact = _build()
    assert artifact["contract"] == COVERAGE_CONTRACT_V2
    schema = json.loads(
        Path("schemas/source_family_coverage.v2.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(artifact)


def test_web_archives_is_not_a_content_family() -> None:
    families = {e["content_family"] for e in _build()["content_families"]}
    assert "web_archives" not in families
    assert families == {"official_ir", "product_pages", "developer_docs", "newsroom"}


def test_two_dimensions_are_recorded_separately() -> None:
    artifact = _build()
    assert {e["access_channel"] for e in artifact["access_channels"]} == {
        "live",
        "archive",
    }
    assert all("access_channel" not in e for e in artifact["content_families"])


def test_newsroom_is_optional() -> None:
    entry = next(
        e for e in _build()["content_families"] if e["content_family"] == "newsroom"
    )
    assert entry["membership"] == "optional"


def test_required_family_may_not_remain_not_attempted() -> None:
    with pytest.raises(CollectionError) as excinfo:
        _build(
            content_family_states={
                "official_ir": "not_attempted",
                "product_pages": "available_and_retrieved",
                "developer_docs": "not_found",
            }
        )
    assert excinfo.value.reason_code == "family_coverage_incomplete"


def test_missing_required_family_is_refused() -> None:
    with pytest.raises(CollectionError) as excinfo:
        _build(content_family_states={"official_ir": "available_and_retrieved"})
    assert excinfo.value.reason_code == "family_coverage_incomplete"


def test_unknown_family_is_refused() -> None:
    with pytest.raises(CollectionError) as excinfo:
        _build(
            content_family_states={
                "official_ir": "available_and_retrieved",
                "product_pages": "available_and_retrieved",
                "developer_docs": "not_found",
                "web_archives": "available_and_retrieved",
            }
        )
    assert excinfo.value.reason_code == "family_coverage_out_of_set"


def test_undeclared_state_is_refused() -> None:
    with pytest.raises(CollectionError) as excinfo:
        _build(
            content_family_states={
                "official_ir": "probably_fine",
                "product_pages": "available_and_retrieved",
                "developer_docs": "not_found",
            }
        )
    assert excinfo.value.reason_code == "coverage_state_unknown"


def test_missing_channel_count_is_refused() -> None:
    with pytest.raises(CollectionError) as excinfo:
        _build(channel_temporally_valid={"live": 1})
    assert excinfo.value.reason_code == "family_coverage_incomplete"


# --- Legacy bridge, both directions ------------------------------------------


def test_bridge_available_when_a_valid_archive_capture_exists() -> None:
    bridge = _build()["legacy_bridge"]
    assert bridge["source_family"] == "web_archives"
    assert bridge["membership"] == "required_legacy"
    assert bridge["coverage_state"] == "available_and_retrieved"
    assert bridge["derived_from"] == "access_channel=archive admitted, temporally_valid"
    assert bridge["temporally_valid_archive_count"] == 1


def test_bridge_failed_when_archives_admitted_but_none_valid() -> None:
    bridge = _build(
        channel_admitted={"live": 1, "archive": 2},
        channel_temporally_valid={"live": 1, "archive": 0},
    )["legacy_bridge"]
    assert bridge["coverage_state"] == "available_but_failed"
    assert bridge["reason_code"]


def test_bridge_not_found_when_no_archive_admitted() -> None:
    bridge = _build(
        channel_admitted={"live": 1, "archive": 0},
        channel_temporally_valid={"live": 1, "archive": 0},
    )["legacy_bridge"]
    assert bridge["coverage_state"] == "not_found"
    assert bridge["reason_code"]


def test_bridge_is_never_not_attempted() -> None:
    for admitted, valid in ((0, 0), (3, 0), (3, 3)):
        bridge = _build(
            channel_admitted={"live": 0, "archive": admitted},
            channel_temporally_valid={"live": 0, "archive": valid},
        )["legacy_bridge"]
        assert bridge["coverage_state"] != "not_attempted"


# --- Inheritance and immutability of the published artifact -------------------


def test_sec_edgar_is_inherited_and_pinned() -> None:
    inherited = _build()["inherited"][0]
    assert inherited["source_family"] == "sec_edgar"
    assert inherited["coverage_state"] == "available_and_retrieved"
    assert inherited["inherited_from_manifest_sha256"] == PARENT


def test_published_increment_b_coverage_artifact_is_untouched() -> None:
    published = Path(
        "data/runs/ing-783d01075ef04858a22ba5743395bb9c/manifests/"
        "source_family_coverage.json"
    )
    if not published.exists():  # pragma: no cover - published run may be absent
        pytest.skip("published Increment B run root not present")
    from hashlib import sha256

    assert (
        sha256(published.read_bytes()).hexdigest()
        == "c3df14067cc61ae6fa7a6a0cae0ce0699f316d6c94db8304686ace8f41f807ef"
    )
    payload = json.loads(published.read_text(encoding="utf-8"))
    assert payload["contract"] == "source_family_coverage@0.1.0"
