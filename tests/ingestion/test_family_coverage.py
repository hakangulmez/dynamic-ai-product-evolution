"""Stage 02 source-family coverage: required set, not_attempted, newsroom."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.ingestion.errors import IngestionError
from dynamic_ai_products.ingestion.family_coverage import (
    COVERAGE_STATES,
    OPTIONAL_FAMILIES,
    REQUIRED_FAMILIES,
    build_source_family_coverage,
)

CUTOFF = "2025-02-12"
COMPANY = "CIK0009999999"

PILOT_STATES = {
    "sec_edgar": "available_and_retrieved",
    "official_ir": "not_attempted",
    "product_pages": "not_attempted",
    "developer_docs": "not_attempted",
    "web_archives": "not_attempted",
}


def _build(**overrides):
    kwargs = {
        "company_id": COMPANY,
        "observation_cutoff_date": CUTOFF,
        "required_states": dict(PILOT_STATES),
    }
    kwargs.update(overrides)
    return build_source_family_coverage(**kwargs)


def test_required_set_is_exactly_the_five_packet_families() -> None:
    packet = json.loads(
        Path("data/registry/pilot_universe_packet_CIK0001404655.json").read_text(
            encoding="utf-8"
        )
    )
    assert sorted(REQUIRED_FAMILIES) == sorted(packet["source_packet_families"])
    assert len(REQUIRED_FAMILIES) == 5


def test_not_attempted_is_a_governed_state() -> None:
    assert "not_attempted" in COVERAGE_STATES
    artifact = _build()
    states = {e["source_family"]: e["coverage_state"] for e in artifact["required_families"]}
    assert states["sec_edgar"] == "available_and_retrieved"
    assert states["official_ir"] == "not_attempted"


def test_all_five_required_families_present() -> None:
    artifact = _build()
    families = {entry["source_family"] for entry in artifact["required_families"]}
    assert families == set(REQUIRED_FAMILIES)
    assert all(e["membership"] == "required" for e in artifact["required_families"])


def test_missing_required_family_fails_closed() -> None:
    partial = dict(PILOT_STATES)
    partial.pop("web_archives")
    with pytest.raises(IngestionError) as excinfo:
        _build(required_states=partial)
    assert excinfo.value.reason_code == "family_coverage_incomplete"


def test_newsroom_is_recorded_as_out_of_required_set() -> None:
    artifact = _build()
    optional = {e["source_family"]: e for e in artifact["optional_families"]}
    assert "newsroom" in optional
    assert optional["newsroom"]["membership"] == "out_of_required_set"
    assert optional["newsroom"]["coverage_state"] == "not_attempted"
    assert "newsroom" not in {e["source_family"] for e in artifact["required_families"]}
    assert OPTIONAL_FAMILIES == ("newsroom",)


def test_undeclared_coverage_state_is_refused() -> None:
    bad = dict(PILOT_STATES)
    bad["sec_edgar"] = "probably_fine"
    with pytest.raises(IngestionError) as excinfo:
        _build(required_states=bad)
    assert excinfo.value.reason_code == "coverage_state_unknown"


def test_family_outside_required_set_is_refused() -> None:
    bad = dict(PILOT_STATES)
    bad["newsroom"] = "not_attempted"
    with pytest.raises(IngestionError) as excinfo:
        _build(required_states=bad)
    assert excinfo.value.reason_code == "family_coverage_out_of_set"


def test_artifact_conforms_to_its_schema() -> None:
    schema = json.loads(
        Path("schemas/source_family_coverage.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_build())
