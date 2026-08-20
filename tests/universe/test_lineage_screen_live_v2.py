"""ADR-116 successor contract tests; no SDK client or network is constructed."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products.lineage_screen_live_v2 import firm_rollup_v2


ROOT = Path(__file__).resolve().parents[2]


def _record(kind: str) -> dict:
    common = {
        "record_contract": "universe_screen_record@0.2.0",
        "cik": "0000000001",
        "company_id": "0000000001",
        "accession": "0000000001-22-000001",
        "form": "10-K",
        "source_id": "sec-primary:0000000001:0000000001-22-000001:a.htm",
    }
    if kind == "screened_packet":
        return {
            **common,
            "record_kind": kind,
            "baseline_filing_date": "2022-12-31",
            "packet_sha256": "a" * 64,
            "screen_status": "LIKELY_INELIGIBLE",
            "prompt_sha256": "b" * 64,
            "model_route": {"provider": "p", "model_label": "m"},
            "raw_response_id": "r",
            "raw_response_sha256": "c" * 64,
            "screen_output": {},
            "failure_reason_code": None,
            "failure_detail": None,
        }
    if kind == "model_evidence_unverified":
        return {
            **common,
            "record_kind": kind,
            "baseline_filing_date": "2022-12-31",
            "packet_sha256": "a" * 64,
            "screen_status": None,
            "prompt_sha256": "b" * 64,
            "model_route": {"provider": "p", "model_label": "m"},
            "raw_response_id": "r",
            "raw_response_sha256": "c" * 64,
            "screen_output": None,
            "failure_reason_code": "quote_resolution_failure",
            "failure_detail": "quote was not a contiguous passage substring",
        }
    return {
        **common,
        "record_kind": "insufficient_evidence",
        "baseline_filing_date": None,
        "packet_sha256": None,
        "screen_status": None,
        "prompt_sha256": None,
        "model_route": None,
        "raw_response_id": None,
        "raw_response_sha256": None,
        "screen_output": None,
        "failure_reason_code": "missing_item_one",
        "failure_detail": "no match",
    }


def _errors(row: dict) -> list:
    schema = json.loads((ROOT / "schemas" / "universe_screen_record.v2.schema.json").read_text())
    return list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(row))


def test_v2_record_contract_distinguishes_no_packet_from_unverified_model_evidence():
    assert not _errors(_record("screened_packet"))
    assert not _errors(_record("insufficient_evidence"))
    assert not _errors(_record("model_evidence_unverified"))
    forged = _record("model_evidence_unverified")
    forged["screen_status"] = "LIKELY_INELIGIBLE"
    assert _errors(forged), "unverified evidence must not carry a negative status"


def test_unverified_model_evidence_blocks_firm_negative_rollup():
    negative = _record("screened_packet")
    unverified = _record("model_evidence_unverified")
    assert firm_rollup_v2([negative, unverified])[negative["cik"]] == "MODEL_EVIDENCE_UNVERIFIED"


def test_positive_or_boundary_evidence_stays_more_permissive_than_unverified():
    unverified = _record("model_evidence_unverified")
    boundary = _record("screened_packet")
    boundary["screen_status"] = "BOUNDARY_OR_UNCERTAIN"
    assert firm_rollup_v2([unverified, boundary])[unverified["cik"]] == "BOUNDARY_OR_UNCERTAIN"


def test_live_authorization_v2_requires_a_real_breaker_field():
    schema = json.loads(
        (ROOT / "schemas" / "universe_screen_live_authorization.v2.schema.json").read_text()
    )
    assert "max_model_evidence_unverified" in schema["required"]
    assert schema["properties"]["max_model_evidence_unverified"]["minimum"] == 0
