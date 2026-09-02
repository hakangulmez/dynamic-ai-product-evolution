"""Tests for the decision-free strict-CORE gold-review case-set builder."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products import classifier_product_gate_v9_gold_review as gold_review
from dynamic_ai_products.universe.lineage_screen import ScreenInputError

ROOT = Path(__file__).resolve().parents[2]


def _sha(text: str) -> str:
    return sha256(text.encode()).hexdigest()


def _record(index: int, *, product: str, centrality: str, confidence: str = "high") -> dict:
    cik = f"{9300000000 + index:010d}"
    return {
        "cik": cik,
        "accession": f"{cik}-25-000001",
        "source_id": f"sec-primary:{cik}",
        "packet_sha256": _sha(f"packet-{index}"),
        "record_kind": "classified",
        "axes": {
            "customer_facing_digital_product": product,
            "software_centrality": centrality,
            "confidence": confidence,
        },
    }


def _packet(record: dict, *, text: str) -> dict:
    return {
        "cik": record["cik"], "accession": record["accession"],
        "packet_sha256": record["packet_sha256"],
        "passages": [{
            "passage_id": f"passage-{record['cik']}", "byte_start": 0,
            "byte_end": len(text.encode()), "text": text, "text_hash": _sha(text),
        }],
    }


def _aggregate_row(record: dict) -> dict:
    return {
        "cik": record["cik"], "accession": record["accession"],
        "axes": record["axes"],
        "source_record_sha256": gold_review._source_record_sha256(record),
    }


def _payloads():
    core = _record(1, product="YES", centrality="CORE")
    coessential = _record(2, product="YES", centrality="CO_ESSENTIAL")
    enabling = _record(3, product="YES", centrality="ENABLING")
    unknown = _record(4, product="UNKNOWN", centrality="UNKNOWN", confidence="low")
    records = [core, coessential, enabling, unknown]
    packets = {
        (core["cik"], core["accession"]): _packet(core, text="Our SaaS software platform is sold to customers."),
        (coessential["cik"], coessential["accession"]): _packet(coessential, text="Our cloud software platform is licensed to customers."),
        (enabling["cik"], enabling["accession"]): _packet(enabling, text="Our physical product includes software."),
        (unknown["cik"], unknown["accession"]): _packet(unknown, text=">Item 1. Business. Omitted."),
    }
    return [_aggregate_row(core)], [_aggregate_row(coessential), _aggregate_row(enabling)], records, packets


def test_gold_review_schemas_are_valid() -> None:
    for relative in (gold_review.CASE_SCHEMA, gold_review.AUDIT_MAP_SCHEMA, gold_review.MANIFEST_SCHEMA):
        Draft202012Validator.check_schema(json.loads((ROOT / relative).read_text()))


def test_approved_queues_are_exact_and_enabling_is_deferred() -> None:
    core_rows, candidate_rows, records, packets = _payloads()
    cases, audit, counts = gold_review.build_gold_review_payloads(
        core_rows=core_rows, candidate_rows=candidate_rows,
        all_records=records, packets_by_key=packets)
    assert counts == {
        "review_cases": 3, "precision_model_core": 1,
        "recall_model_coessential": 1, "source_insufficient_unknown": 1,
    }
    assert [row["selection_track"] for row in audit] == [
        "source_insufficient_unknown", "precision_model_core", "recall_model_coessential"]
    assert [case["case_id"] for case in cases] != [row["case_id"] for row in audit]
    assert all("model_" not in key and "selection_track" not in key for case in cases for key in case)
    assert {(case["cik"], case["accession"]) for case in cases}.isdisjoint({
        (records[2]["cik"], records[2]["accession"])
    })


def test_cases_keep_only_packet_derived_item_one_text() -> None:
    core_rows, candidate_rows, records, packets = _payloads()
    cases, _audit, _counts = gold_review.build_gold_review_payloads(
        core_rows=core_rows, candidate_rows=candidate_rows,
        all_records=records, packets_by_key=packets)
    case = next(case for case in cases if case["source_availability"] == "sufficient_item1")
    assert case["item1_passages"] == [{
        "passage_ref": "P001", "passage_id": f"passage-{case['cik']}",
        "byte_start": 0, "byte_end": len(case["item1_passages"][0]["text"].encode()),
        "text": case["item1_passages"][0]["text"], "text_sha256": _sha(case["item1_passages"][0]["text"]),
    }]


@pytest.mark.parametrize("text", [">Item 1. Business", ">Item 1. Business 3", ">Item 1. Business. Omitted."])
def test_only_heading_or_omission_is_source_insufficient(text: str) -> None:
    core_rows, candidate_rows, records, packets = _payloads()
    unknown = records[-1]
    packets[(unknown["cik"], unknown["accession"])] = _packet(unknown, text=text)
    _cases, audit, counts = gold_review.build_gold_review_payloads(
        core_rows=core_rows, candidate_rows=candidate_rows,
        all_records=records, packets_by_key=packets)
    assert counts["source_insufficient_unknown"] == 1
    assert audit[0]["selection_track"] == "source_insufficient_unknown"


def test_substantive_unknown_refuses_instead_of_becoming_source_insufficient() -> None:
    core_rows, candidate_rows, records, packets = _payloads()
    unknown = records[-1]
    packets[(unknown["cik"], unknown["accession"])] = _packet(
        unknown, text="Item 1. Business. We provide a digital product to customers.")
    with pytest.raises(ScreenInputError, match="substantive Item 1 text"):
        gold_review.build_gold_review_payloads(
            core_rows=core_rows, candidate_rows=candidate_rows,
            all_records=records, packets_by_key=packets)


def test_coessential_queue_orders_strongest_direct_software_signal_first() -> None:
    core_rows, candidate_rows, records, packets = _payloads()
    extra = _record(5, product="YES", centrality="CO_ESSENTIAL")
    records.append(extra)
    packets[(extra["cik"], extra["accession"])] = _packet(
        extra, text="Our SaaS software-as-a-service software platform is sold to customers.")
    candidate_rows.append(_aggregate_row(extra))
    _cases, audit, _counts = gold_review.build_gold_review_payloads(
        core_rows=core_rows, candidate_rows=candidate_rows,
        all_records=records, packets_by_key=packets)
    coessential = [row for row in audit if row["selection_track"] == "recall_model_coessential"]
    assert [row["software_signal_score"] for row in coessential] == sorted(
        (row["software_signal_score"] for row in coessential), reverse=True)


def test_model_label_vocabulary_is_only_in_the_audit_map() -> None:
    core_rows, candidate_rows, records, packets = _payloads()
    cases, audit, _counts = gold_review.build_gold_review_payloads(
        core_rows=core_rows, candidate_rows=candidate_rows,
        all_records=records, packets_by_key=packets)
    assert {row["model_product_label"] for row in audit} == {"YES", "UNKNOWN"}
    assert {row["model_centrality"] for row in audit} == {"CORE", "CO_ESSENTIAL", "UNKNOWN"}
    assert all("STRICT_CORE" not in json.dumps(case) for case in cases)
