"""Candidate collections as legal wrappers (ADR-033).

``product_observation@0.1.0`` and ``capability_observation@0.1.0`` are strict,
so ``candidate_id`` cannot be appended to an observation. Each candidate is a
wrapper whose nested ``observation`` validates independently against the
unchanged released schema.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.extraction.candidates import (
    CANDIDATE_COLLECTION_CONTRACT,
    OBSERVATION_KINDS,
    build_candidate_collection,
    candidate_id_for,
    collection_bytes,
)
from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.raw_artifacts import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"
RAW_SHA = "a" * 64


def _product(index: int = 0) -> dict:
    return {
        "product_observation_id": f"prod-{index}",
        "company_id": "CIK0001404655",
        "observation_cutoff": "2024-12-31",
        "product_name": f"Product {index}",
        "availability_status": "generally_available",
        "evidence": [
            {"source_id": "sec-1", "passage_id": "p-1", "quote": "the product exists"}
        ],
        "confidence": "high",
    }


def _capability(index: int = 0) -> dict:
    return {
        "capability_observation_id": f"cap-{index}",
        "product_observation_id": "prod-0",
        "capability": f"Capability {index}",
        "availability_status": "generally_available",
        "evidence": [
            {"source_id": "sec-1", "passage_id": "p-1", "quote": "the capability exists"}
        ],
        "confidence": "medium",
    }


def _build(observations, kind="product"):
    return build_candidate_collection(
        observation_kind=kind,
        raw_artifact_reference="predictions/raw_prediction.json",
        raw_artifact_sha256=RAW_SHA,
        observations=observations,
        schema_root=SCHEMAS,
    )


def test_declared_kinds():
    assert OBSERVATION_KINDS == ("product", "capability")
    assert CANDIDATE_COLLECTION_CONTRACT == "extraction_candidate_collection@0.1.0"


def test_entries_are_wrappers_and_the_observation_is_left_untouched():
    observation = _product()
    collection = _build([observation])
    entry = collection["entries"][0]
    assert sorted(entry) == ["candidate_id", "observation", "observation_kind", "ordinal"]
    assert entry["observation"] == observation
    assert "candidate_id" not in entry["observation"]


def test_the_nested_observation_still_validates_against_the_released_schema():
    schema = json.loads((SCHEMAS / "product_observation.schema.json").read_text())
    validator = Draft202012Validator(schema)
    collection = _build([_product(0), _product(1)])
    for entry in collection["entries"]:
        validator.validate(entry["observation"])


def test_candidate_id_binds_the_raw_digest_and_the_ordinal():
    observation = _product()
    expected = sha256(
        RAW_SHA.encode("ascii")
        + b"\x00"
        + b"3"
        + b"\x00"
        + canonical_json_bytes(observation)
    ).hexdigest()[:32]
    assert candidate_id_for(RAW_SHA, 3, observation) == expected


def test_an_identity_is_non_transferable_across_raw_artifacts():
    observation = _product()
    assert candidate_id_for("a" * 64, 0, observation) != candidate_id_for(
        "b" * 64, 0, observation
    )


def test_identical_observations_at_different_ordinals_stay_distinct():
    collection = _build([_product(), _product()])
    ids = [entry["candidate_id"] for entry in collection["entries"]]
    assert len(set(ids)) == 2


def test_canonical_order_is_ascending_ordinal():
    collection = _build([_product(i) for i in range(4)])
    assert [entry["ordinal"] for entry in collection["entries"]] == [0, 1, 2, 3]


def test_invalid_candidates_are_counted_and_explained_never_silently_dropped():
    collection = _build([_product(0), {"product_name": "no ids"}, "not an object"])
    assert collection["accepted_candidate_count"] == 1
    assert collection["rejected_candidate_count"] == 2
    reasons = {entry["reason"] for entry in collection["rejected"]}
    assert reasons == {"schema_invalid", "not_an_object"}
    assert [entry["ordinal"] for entry in collection["rejected"]] == [1, 2]


def test_rejection_detail_reports_the_first_schema_error():
    collection = _build([{"product_name": "incomplete"}])
    assert collection["rejected"][0]["detail"]


def test_capability_candidates_validate_against_their_own_released_schema():
    collection = _build([_capability(0)], kind="capability")
    assert collection["accepted_candidate_count"] == 1
    assert collection["entries"][0]["observation_kind"] == "capability"


def test_a_product_observation_is_not_accepted_as_a_capability():
    collection = _build([_product()], kind="capability")
    assert collection["accepted_candidate_count"] == 0
    assert collection["rejected"][0]["reason"] == "schema_invalid"


def test_an_unknown_observation_kind_is_refused():
    with pytest.raises(ExtractionError) as excinfo:
        _build([_product()], kind="task")
    assert excinfo.value.reason_code == "observation_kind_invalid"


def test_a_missing_released_schema_is_refused(tmp_path: Path):
    with pytest.raises(ExtractionError) as excinfo:
        build_candidate_collection(
            observation_kind="product",
            raw_artifact_reference="r",
            raw_artifact_sha256=RAW_SHA,
            observations=[_product()],
            schema_root=tmp_path,
        )
    assert excinfo.value.reason_code == "observation_schema_unavailable"


def test_an_empty_collection_is_legal_and_fully_counted():
    collection = _build([])
    assert collection["entries"] == []
    assert collection["accepted_candidate_count"] == 0
    assert collection["rejected_candidate_count"] == 0


def test_the_collection_conforms_to_its_released_schema():
    schema = json.loads(
        (SCHEMAS / "extraction_candidate_collection.schema.json").read_text()
    )
    collection = _build([_product(0), {"bad": True}])
    Draft202012Validator(schema).validate(collection)


def test_serialization_is_deterministic():
    first = collection_bytes(_build([_product(0), _product(1)]))
    second = collection_bytes(_build([_product(0), _product(1)]))
    assert first == second
    assert first.endswith(b"\n")
