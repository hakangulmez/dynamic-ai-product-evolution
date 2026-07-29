"""Human validation decision sets and accepted-observation artifacts (ADR-033).

A decision set is a human judgement: no deterministic producer and no provider
may synthesise one. Every accepted candidate is persisted as its own write-once
artifact and named by reference and SHA-256, which is what makes a snapshot's
expected member set derivable rather than asserted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.extraction.candidates import build_candidate_collection
from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.raw_artifacts import sha256_bytes
from dynamic_ai_products.extraction.validation import (
    DECISION_SET_CONTRACT,
    DECISIONS,
    build_validation_decision_set,
    decision_set_bytes,
    persist_accepted_observations,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"
RAW_SHA = "a" * 64
COLLECTION_SHA = "b" * 64
PACKET_SHA = "c" * 64
COVERAGE_SHA = "d" * 64
SNAPSHOT_A_SHA = "e" * 64


def _product(index: int) -> dict:
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


def _collection(count: int = 2, kind: str = "product") -> dict:
    observations = [_product(i) for i in range(count)]
    return build_candidate_collection(
        observation_kind=kind,
        raw_artifact_reference="predictions/raw_prediction.json",
        raw_artifact_sha256=RAW_SHA,
        observations=observations,
        schema_root=SCHEMAS,
    )


def _decision_set(collection, accepted, artifacts, **overrides):
    kwargs = {
        "observation_kind": "product",
        "decision_set_version": "v1",
        "raw_artifact_reference": "predictions/raw_prediction.json",
        "raw_artifact_sha256": RAW_SHA,
        "candidate_collection_reference": "candidates/collection.json",
        "candidate_collection_sha256": COLLECTION_SHA,
        "input_packet_reference": "inputs/extraction_input_packet.json",
        "input_packet_sha256": PACKET_SHA,
        "coverage_artifact_reference": "coverage/source_family_coverage.json",
        "coverage_artifact_sha256": COVERAGE_SHA,
        "collection": collection,
        "accepted_candidate_ids": accepted,
        "accepted_artifacts": artifacts,
    }
    kwargs.update(overrides)
    return build_validation_decision_set(**kwargs)


def test_declared_constants():
    assert DECISION_SET_CONTRACT == "extraction_validation_decision_set@0.1.0"
    assert DECISIONS == ("accept", "reject")


def test_each_accepted_observation_is_persisted_as_its_own_artifact(tmp_path: Path):
    collection = _collection(2)
    ids = [entry["candidate_id"] for entry in collection["entries"]]
    artifacts = persist_accepted_observations(
        artifact_root=str(tmp_path),
        relative_dir="observations/product",
        collection=collection,
        accepted_candidate_ids=ids,
    )
    assert sorted(artifacts) == sorted(ids)
    for candidate_id, pin in artifacts.items():
        target = tmp_path / pin["reference"]
        assert target.is_file()
        assert sha256_bytes(target.read_bytes()) == pin["sha256"]
        assert json.loads(target.read_text())["product_observation_id"]
        assert pin["reference"] == f"observations/product/{candidate_id}.json"


def test_persisted_observations_are_write_once(tmp_path: Path):
    collection = _collection(1)
    ids = [collection["entries"][0]["candidate_id"]]
    kwargs = {
        "artifact_root": str(tmp_path),
        "relative_dir": "observations/product",
        "collection": collection,
        "accepted_candidate_ids": ids,
    }
    persist_accepted_observations(**kwargs)
    with pytest.raises(ExtractionError) as excinfo:
        persist_accepted_observations(**kwargs)
    assert excinfo.value.reason_code == "destination_exists"


def test_an_unknown_candidate_id_cannot_be_accepted(tmp_path: Path):
    with pytest.raises(ExtractionError) as excinfo:
        persist_accepted_observations(
            artifact_root=str(tmp_path),
            relative_dir="observations/product",
            collection=_collection(1),
            accepted_candidate_ids=["0" * 32],
        )
    assert excinfo.value.reason_code == "candidate_id_unknown"


def test_every_candidate_receives_exactly_one_decision(tmp_path: Path):
    collection = _collection(3)
    ids = [entry["candidate_id"] for entry in collection["entries"]]
    artifacts = persist_accepted_observations(
        artifact_root=str(tmp_path),
        relative_dir="observations/product",
        collection=collection,
        accepted_candidate_ids=ids[:1],
    )
    decision_set = _decision_set(collection, ids[:1], artifacts)
    assert len(decision_set["decisions"]) == 3
    assert decision_set["accepted_count"] == 1
    assert decision_set["rejected_count"] == 2
    assert [d["candidate_id"] for d in decision_set["decisions"]] == ids


def test_an_accepted_decision_names_its_persisted_artifact(tmp_path: Path):
    collection = _collection(1)
    ids = [collection["entries"][0]["candidate_id"]]
    artifacts = persist_accepted_observations(
        artifact_root=str(tmp_path),
        relative_dir="observations/product",
        collection=collection,
        accepted_candidate_ids=ids,
    )
    decision = _decision_set(collection, ids, artifacts)["decisions"][0]
    assert decision["decision"] == "accept"
    assert decision["accepted_artifact_reference"] == artifacts[ids[0]]["reference"]
    assert decision["accepted_artifact_sha256"] == artifacts[ids[0]]["sha256"]


def test_a_rejected_decision_names_no_artifact(tmp_path: Path):
    collection = _collection(1)
    decision = _decision_set(collection, [], {})["decisions"][0]
    assert decision["decision"] == "reject"
    assert decision["accepted_artifact_reference"] is None
    assert decision["accepted_artifact_sha256"] is None
    assert decision["reason"] == "rejected_by_human_review"


def test_an_acceptance_without_a_persisted_artifact_is_refused():
    collection = _collection(1)
    ids = [collection["entries"][0]["candidate_id"]]
    with pytest.raises(ExtractionError) as excinfo:
        _decision_set(collection, ids, {})
    assert excinfo.value.reason_code == "validation_provenance_missing"


def test_a_collection_from_a_different_raw_artifact_is_refused():
    with pytest.raises(ExtractionError) as excinfo:
        _decision_set(_collection(1), [], {}, raw_artifact_sha256="f" * 64)
    assert excinfo.value.reason_code == "raw_artifact_pin_mismatch"


def test_a_kind_mismatch_between_collection_and_decision_set_is_refused():
    with pytest.raises(ExtractionError) as excinfo:
        _decision_set(_collection(1), [], {}, observation_kind="capability")
    assert excinfo.value.reason_code == "observation_kind_invalid"


@pytest.mark.parametrize(
    "field",
    [
        "raw_artifact_sha256",
        "candidate_collection_sha256",
        "input_packet_sha256",
        "coverage_artifact_sha256",
    ],
)
def test_every_pin_must_be_a_well_formed_digest(field):
    collection = _collection(1)
    overrides = {field: "not-a-digest"}
    if field == "raw_artifact_sha256":
        collection = build_candidate_collection(
            observation_kind="product",
            raw_artifact_reference="r",
            raw_artifact_sha256="not-a-digest",
            observations=[_product(0)],
            schema_root=SCHEMAS,
        )
    with pytest.raises(ExtractionError) as excinfo:
        _decision_set(collection, [], {}, **overrides)
    assert excinfo.value.reason_code == "pin_invalid"


def test_a_capability_decision_set_must_pin_snapshot_a():
    collection = _collection(1, kind="capability")
    with pytest.raises(ExtractionError) as excinfo:
        _decision_set(collection, [], {}, observation_kind="capability")
    assert excinfo.value.reason_code == "capability_decision_snapshot_a_mismatch"


def test_a_product_decision_set_must_not_pin_snapshot_a():
    with pytest.raises(ExtractionError) as excinfo:
        _decision_set(
            _collection(1),
            [],
            {},
            snapshot_a_reference="snapshots/a.json",
            snapshot_a_sha256=SNAPSHOT_A_SHA,
        )
    assert excinfo.value.reason_code == "capability_decision_snapshot_a_mismatch"


def test_a_capability_decision_set_records_its_snapshot_a_pin():
    collection = build_candidate_collection(
        observation_kind="capability",
        raw_artifact_reference="predictions/raw_prediction.json",
        raw_artifact_sha256=RAW_SHA,
        observations=[],
        schema_root=SCHEMAS,
    )
    decision_set = _decision_set(
        collection,
        [],
        {},
        observation_kind="capability",
        snapshot_a_reference="snapshots/a.json",
        snapshot_a_sha256=SNAPSHOT_A_SHA,
    )
    assert decision_set["snapshot_a_reference"] == "snapshots/a.json"
    assert decision_set["snapshot_a_sha256"] == SNAPSHOT_A_SHA


def test_the_decision_set_conforms_to_its_released_schema(tmp_path: Path):
    schema = json.loads(
        (SCHEMAS / "extraction_validation_decision_set.schema.json").read_text()
    )
    collection = _collection(2)
    ids = [entry["candidate_id"] for entry in collection["entries"]]
    artifacts = persist_accepted_observations(
        artifact_root=str(tmp_path),
        relative_dir="observations/product",
        collection=collection,
        accepted_candidate_ids=ids[:1],
    )
    Draft202012Validator(schema).validate(_decision_set(collection, ids[:1], artifacts))


def test_serialization_is_deterministic():
    collection = _collection(2)
    assert decision_set_bytes(_decision_set(collection, [], {})) == decision_set_bytes(
        _decision_set(collection, [], {})
    )
