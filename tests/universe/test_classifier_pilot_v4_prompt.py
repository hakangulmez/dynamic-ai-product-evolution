"""Tests for the product-first successor to the V3 software-universe gate."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from dynamic_ai_products.classifier_pilot_v3 import (
    PILOT_V3_AXES_SCHEMA,
    validate_pilot_v3_axes_output,
)
from dynamic_ai_products.lineage_classifier_pilot_v4 import PILOT_V4_ROUTE

ROOT = Path(__file__).resolve().parents[2]
AXES = Draft202012Validator(json.loads((ROOT / PILOT_V3_AXES_SCHEMA).read_text()))


def _output(product: str, centrality: str) -> dict:
    return {
        "customer_facing_digital_product": product,
        "software_centrality": centrality,
        "confidence": "medium",
        "passage_refs": ["P001"],
    }


def test_prompt_asks_for_a_separately_identifiable_customer_product_first():
    prompt = (ROOT / "prompts/discovery/software_universe_classifier_pilot.v3.md").read_text()
    assert "sells, licenses" in prompt
    assert "separately identifiable" in prompt
    assert prompt.index("Customer-facing digital product") < prompt.index("Software centrality")
    assert "product catalogue" not in prompt
    assert "later PCT" not in prompt


def test_prompt_draws_general_boundary_between_product_and_technology_use():
    prompt = " ".join((ROOT / "prompts/discovery/software_universe_classifier_pilot.v3.md").read_text().split())
    for phrase in ("digital sales channel or website", "third-party infrastructure", "embedded software"):
        assert phrase in prompt


def test_no_or_unknown_product_requires_unknown_centrality():
    assert not list(AXES.iter_errors(_output("NO", "UNKNOWN")))
    assert not list(AXES.iter_errors(_output("UNKNOWN", "UNKNOWN")))
    for product in ("NO", "UNKNOWN"):
        for centrality in ("CORE", "CO_ESSENTIAL", "ENABLING", "PERIPHERAL"):
            assert list(AXES.iter_errors(_output(product, centrality)))


def test_yes_product_retains_all_five_centrality_values():
    for centrality in ("CORE", "CO_ESSENTIAL", "ENABLING", "PERIPHERAL", "UNKNOWN"):
        assert not list(AXES.iter_errors(_output("YES", centrality)))


def test_validator_turns_no_enabling_response_into_review_uncertain():
    packet = {
        "cik": "0000000001", "accession": "0000000001-22-000001", "packet_sha256": "a" * 64,
        "passages": [{"passage_id": "p1", "text": "A physical product.", "byte_start": 0,
                      "byte_end": 19, "section": "item_1", "source_id": "source",
                      "text_hash": "b" * 64, "normalizer_version": "v1"}],
    }
    raw = json.dumps(_output("NO", "ENABLING"))
    try:
        validate_pilot_v3_axes_output(raw, packet, AXES)
    except Exception as exc:
        assert getattr(exc, "reason_code", None) == "pilot_axes_contract_violation"
    else:
        raise AssertionError("NO + ENABLING must be refused")


def test_v4_route_isolated_and_binds_only_the_product_first_contract():
    assert PILOT_V4_ROUTE.run_kind == "classifier_pilot_v4"
    assert PILOT_V4_ROUTE.prompt_path.endswith("software_universe_classifier_pilot.v3.md")
    assert PILOT_V4_ROUTE.axes_contract == "universe_classifier_pilot_axes_record@0.3.0"
    assert PILOT_V4_ROUTE.record_contract == "universe_classifier_pilot_record@0.3.0"
    assert PILOT_V4_ROUTE.manifest_contract == "universe_classifier_pilot_manifest@0.4.0"
