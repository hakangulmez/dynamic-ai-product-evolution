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


# --- ADR-057: the successor records who decided, and when -------------------


from dynamic_ai_products.extraction.validation import (  # noqa: E402
    DECISION_SET_CONTRACT_V2,
    KNOWN_DECISION_SET_CONTRACTS,
    build_validation_decision_set_v2,
)

DECIDED_BY = "Hakan Zeki Gulmez"
DECIDED_AT = "2026-08-05T13:00:00+02:00"


def _released_kwargs():
    """The same inputs the released builder is exercised with elsewhere."""
    collection = _collection(2)
    ids = [entry["candidate_id"] for entry in collection["entries"]]
    artifacts = {
        cid: {"reference": f"observations/product/{cid}.json", "sha256": RAW_SHA}
        for cid in ids
    }
    return {
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
        "accepted_candidate_ids": ids,
        "accepted_artifacts": artifacts,
    }


def _v2(**over):
    kwargs = {"decided_by": DECIDED_BY, "decided_at": DECIDED_AT, **_released_kwargs()}
    kwargs.update(over)
    return build_validation_decision_set_v2(**kwargs)


def test_the_released_contract_is_untouched_and_the_successor_sits_beside_it():
    from dynamic_ai_products.extraction.validation import DECISION_SET_CONTRACT_V3

    assert DECISION_SET_CONTRACT == "extraction_validation_decision_set@0.1.0"
    assert DECISION_SET_CONTRACT_V2 == "extraction_validation_decision_set@0.2.0"
    assert DECISION_SET_CONTRACT_V3 == "extraction_validation_decision_set@0.3.0"
    assert KNOWN_DECISION_SET_CONTRACTS == (
        DECISION_SET_CONTRACT,
        DECISION_SET_CONTRACT_V2,
        DECISION_SET_CONTRACT_V3,
    )


def test_the_successor_carries_the_human_and_declares_its_own_version():
    ds = _v2()
    assert ds["contract"] == DECISION_SET_CONTRACT_V2
    assert ds["schema_version"] == "0.2.0"
    assert ds["decided_by"] == DECIDED_BY
    assert ds["decided_at"] == DECIDED_AT


def test_the_successor_reuses_the_released_judgement_verbatim():
    """One definition of what a decision *is*.

    Every pin rule, the Snapshot A split, the accepted-artifact requirement and
    the counts are computed by the released builder; the successor adds two
    fields and nothing else. A second implementation could drift.
    """
    shared = _released_kwargs()
    released = build_validation_decision_set(**shared)
    successor = build_validation_decision_set_v2(
        decided_by=DECIDED_BY, decided_at=DECIDED_AT, **shared
    )
    added = {"decided_by", "decided_at"}
    assert set(successor) - set(released) == added
    for key in released:
        if key in ("contract", "schema_version"):
            continue
        assert successor[key] == released[key], key


@pytest.mark.parametrize("value", ["", "   ", None, 7])
def test_a_decision_set_without_a_named_human_is_refused(value):
    with pytest.raises(ExtractionError) as excinfo:
        _v2(decided_by=value)
    assert excinfo.value.reason_code == "validation_provenance_missing"


@pytest.mark.parametrize(
    "value",
    ["2026-08-05T13:00:00", "not-a-timestamp", "", None, 7],
    ids=["naive", "unparseable", "empty", "null", "int"],
)
def test_a_decision_instant_without_a_zone_is_refused(value):
    """Guessing a zone on the record of a human admission would invent provenance."""
    with pytest.raises(ExtractionError) as excinfo:
        _v2(decided_at=value)
    assert excinfo.value.reason_code == "validation_provenance_missing"


def test_the_successor_validates_against_its_own_schema_and_not_the_released_one():
    v2_schema = json.loads(
        (SCHEMAS / "extraction_validation_decision_set_v2.schema.json").read_text()
    )
    v1_schema = json.loads(
        (SCHEMAS / "extraction_validation_decision_set.schema.json").read_text()
    )
    ds = _v2()
    Draft202012Validator(v2_schema).validate(ds)
    assert not Draft202012Validator(v1_schema).is_valid(ds)


def test_the_released_document_is_still_refused_by_the_successor_schema():
    """Two-way closed: neither loader accepts the other's declared contract."""
    v2_schema = json.loads(
        (SCHEMAS / "extraction_validation_decision_set_v2.schema.json").read_text()
    )
    assert not Draft202012Validator(v2_schema).is_valid(
        build_validation_decision_set(**_released_kwargs())
    )


def test_the_snapshot_step_accepts_both_contracts_and_nothing_else():
    """ADR-053's lesson applied: a const would have frozen the artifact.

    ``parent_snapshots`` gates the decision set it reconciles a snapshot
    against. Pinned to one literal, it would have refused every successor.
    """
    from dynamic_ai_products.extraction import parent_snapshots as ps

    source = Path(ps.__file__).read_text(encoding="utf-8")
    assert "KNOWN_DECISION_SET_CONTRACTS" in source
    assert '_DECISION_SET_CONTRACT = "extraction_validation_decision_set@0.1.0"' not in source
    assert ps.KNOWN_DECISION_SET_CONTRACTS is KNOWN_DECISION_SET_CONTRACTS


# --- ADR-071: the third kind, and the Snapshot B pin ------------------------
#
# The @0.1.0 and @0.2.0 builders were written when only two kinds could reach a
# decision set. Their snapshot rule was `if capability: pin A / else: pin
# nothing`, and `task` -- whose parents are the accepted *capabilities*, i.e.
# Snapshot B -- fell into the `else` and was told it must not pin a snapshot at
# all. This section fixes the class, not the instance: the rule becomes a closed
# map with a fail-closed resolver, and the contract that can express three kinds
# declares that it can.

from dynamic_ai_products.extraction.candidates import (  # noqa: E402
    OBSERVATION_KINDS,
    derive_identity_fields,
)
from dynamic_ai_products.extraction.validation import (  # noqa: E402
    DECISION_SET_CONTRACT_V3,
    DECISION_SET_KINDS_BY_CONTRACT,
    SNAPSHOT_AXIS_BY_KIND,
    build_validation_decision_set_v3,
)

SNAPSHOT_B_SHA = "f" * 64
TASK_PRODUCT = "CIK0001404655:2024-12-31:payments"
TASK_CAPABILITY = f"{TASK_PRODUCT}:accept-electronic-funds-transfers"


def _task(index: int) -> dict:
    return derive_identity_fields(
        {
            "task_observation_id": "ignored-by-derivation",
            "company_id": "CIK0001404655",
            "observation_cutoff": "2024-12-31",
            "product_observation_id": TASK_PRODUCT,
            "capability_observation_ids": [TASK_CAPABILITY],
            "task": f"Accept a customer card payment number {index}",
            "customer_need": "collect money from a buyer without extra tooling",
            "availability_status": "general_availability",
            "evidence": [
                {"source_id": "sec-1", "passage_id": "p-1", "quote": "the task exists"}
            ],
            "confidence": "high",
        },
        company_id="CIK0001404655",
        observation_cutoff="2024-12-31",
        observation_kind="task",
    )


def _capability(index: int) -> dict:
    return derive_identity_fields(
        {
            "capability_observation_id": "ignored-by-derivation",
            "product_observation_id": TASK_PRODUCT,
            "capability": f"Accept electronic funds transfers number {index}",
            "availability_status": "generally_available",
            "evidence": [
                {"source_id": "sec-1", "passage_id": "p-1", "quote": "the capability exists"}
            ],
            "confidence": "high",
        },
        company_id="CIK0001404655",
        observation_cutoff="2024-12-31",
        observation_kind="capability",
    )


def _kind_collection(kind: str, count: int = 2) -> dict:
    """A collection whose entries actually admit, for each of the three kinds."""
    make = {"product": _product, "capability": _capability, "task": _task}[kind]
    collection = build_candidate_collection(
        observation_kind=kind,
        raw_artifact_reference="predictions/raw_prediction.json",
        raw_artifact_sha256=RAW_SHA,
        observations=[make(i) for i in range(count)],
        schema_root=SCHEMAS,
    )
    assert len(collection["entries"]) == count, (kind, collection["rejected"])
    return collection


def _kwargs_for(kind: str, collection: dict) -> dict:
    ids = [entry["candidate_id"] for entry in collection["entries"]]
    kwargs = dict(_released_kwargs())
    kwargs.update(
        observation_kind=kind,
        collection=collection,
        accepted_candidate_ids=ids,
        accepted_artifacts={
            cid: {"reference": f"observations/{kind}/{cid}.json", "sha256": RAW_SHA}
            for cid in ids
        },
    )
    return kwargs


def _v3(kind: str = "task", *, collection=None, **over):
    if collection is None:
        collection = _kind_collection(kind, 2)
    kwargs = {"decided_by": DECIDED_BY, "decided_at": DECIDED_AT}
    kwargs.update(_kwargs_for(kind, collection))
    if kind == "capability":
        kwargs.update(
            snapshot_a_reference="snapshots/a.json", snapshot_a_sha256=SNAPSHOT_A_SHA
        )
    if kind == "task":
        kwargs.update(
            snapshot_b_reference="snapshots/b.json", snapshot_b_sha256=SNAPSHOT_B_SHA
        )
    kwargs.update(over)
    return build_validation_decision_set_v3(**kwargs)


def _v3_refuses(**over) -> ExtractionError:
    with pytest.raises(ExtractionError) as excinfo:
        _v3(**over)
    return excinfo.value


# --- the rule itself: closed, exhaustive, and owned once ---------------------


def test_every_observation_kind_declares_its_snapshot_rule():
    """The guard for the defect class, not for this instance.

    Five earlier defects (ADR-053, -058, -061, -062, -064) were the same shape:
    a branch written when one kind existed, silently wrong once a second
    appeared. A kind that reaches a decision set without an entry here would
    inherit whichever arm happened to be last. This test fails the moment a
    fourth kind is added without a decision about its parent snapshot.
    """
    assert set(SNAPSHOT_AXIS_BY_KIND) == set(OBSERVATION_KINDS)
    assert SNAPSHOT_AXIS_BY_KIND == {"product": None, "capability": "a", "task": "b"}


def test_an_unmapped_kind_fails_closed_instead_of_defaulting(monkeypatch):
    """Removing the entry must refuse, not silently behave like a product."""
    from dynamic_ai_products.extraction import validation as v

    monkeypatch.delitem(v.SNAPSHOT_AXIS_BY_KIND, "task")
    assert _v3_refuses().reason_code == "decision_set_snapshot_rule_missing"


def test_an_unknown_target_contract_fails_closed():
    collection = _collection(2)
    with pytest.raises(ExtractionError) as excinfo:
        build_validation_decision_set(
            **_kwargs_for("product", collection),
            target_contract="extraction_validation_decision_set@9.9.9",
        )
    assert excinfo.value.reason_code == "decision_set_contract_unknown"


# --- what each contract can express -----------------------------------------


def test_the_released_contracts_cannot_express_a_task_decision_set():
    """Not merely unvalidated -- unrepresentable.

    @0.1.0 and @0.2.0 have no snapshot_b field, so a task decision set built
    under them could not record the Snapshot B it was judged against. Refused
    at the door rather than emitted in a shape no schema accepts.
    """
    assert DECISION_SET_KINDS_BY_CONTRACT[DECISION_SET_CONTRACT] == (
        "product",
        "capability",
    )
    assert DECISION_SET_KINDS_BY_CONTRACT[DECISION_SET_CONTRACT_V2] == (
        "product",
        "capability",
    )
    assert DECISION_SET_KINDS_BY_CONTRACT[DECISION_SET_CONTRACT_V3] == (
        "product",
        "capability",
        "task",
    )
    collection = _kind_collection("task", 1)
    for build in (
        lambda: build_validation_decision_set(**_kwargs_for("task", collection)),
        lambda: build_validation_decision_set_v2(
            decided_by=DECIDED_BY,
            decided_at=DECIDED_AT,
            **_kwargs_for("task", collection),
        ),
    ):
        with pytest.raises(ExtractionError) as excinfo:
            build()
        assert excinfo.value.reason_code == "observation_kind_invalid"


def test_an_unknown_kind_is_still_refused_before_the_contract_gate():
    collection = _collection(1)
    with pytest.raises(ExtractionError) as excinfo:
        build_validation_decision_set(
            **{**_kwargs_for("product", collection), "observation_kind": "wildlife"}
        )
    assert excinfo.value.reason_code == "observation_kind_invalid"


# --- the three-way snapshot split -------------------------------------------


def test_a_task_decision_set_must_pin_snapshot_b():
    assert (
        _v3_refuses(snapshot_b_reference=None, snapshot_b_sha256=None).reason_code
        == "task_decision_snapshot_b_mismatch"
    )
    assert (
        _v3_refuses(snapshot_b_sha256="not-a-digest").reason_code
        == "task_decision_snapshot_b_mismatch"
    )


def test_a_task_decision_set_must_not_pin_snapshot_a():
    """A task cites Snapshot A only transitively, through Snapshot B."""
    assert (
        _v3_refuses(
            snapshot_a_reference="snapshots/a.json", snapshot_a_sha256=SNAPSHOT_A_SHA
        ).reason_code
        == "capability_decision_snapshot_a_mismatch"
    )


def test_a_capability_decision_set_must_not_pin_snapshot_b():
    assert (
        _v3_refuses(
            kind="capability",
            snapshot_b_reference="snapshots/b.json",
            snapshot_b_sha256=SNAPSHOT_B_SHA,
        ).reason_code
        == "task_decision_snapshot_b_mismatch"
    )


def test_a_product_decision_set_must_pin_neither_snapshot():
    assert (
        _v3_refuses(
            kind="product",
            snapshot_a_reference="snapshots/a.json",
            snapshot_a_sha256=SNAPSHOT_A_SHA,
        ).reason_code
        == "capability_decision_snapshot_a_mismatch"
    )
    assert (
        _v3_refuses(
            kind="product",
            snapshot_b_reference="snapshots/b.json",
            snapshot_b_sha256=SNAPSHOT_B_SHA,
        ).reason_code
        == "task_decision_snapshot_b_mismatch"
    )


def test_a_capability_decision_set_still_must_pin_snapshot_a_under_the_successor():
    assert (
        _v3_refuses(
            kind="capability", snapshot_a_reference=None, snapshot_a_sha256=None
        ).reason_code
        == "capability_decision_snapshot_a_mismatch"
    )


# --- the successor's own shape ----------------------------------------------


def test_the_task_successor_declares_its_version_and_records_its_snapshot_b_pin():
    ds = _v3()
    assert ds["contract"] == DECISION_SET_CONTRACT_V3
    assert ds["schema_version"] == "0.3.0"
    assert ds["observation_kind"] == "task"
    assert ds["snapshot_b_reference"] == "snapshots/b.json"
    assert ds["snapshot_b_sha256"] == SNAPSHOT_B_SHA
    assert ds["snapshot_a_reference"] is None
    assert ds["snapshot_a_sha256"] is None
    assert ds["decided_by"] == DECIDED_BY
    assert ds["decided_at"] == DECIDED_AT


def test_the_task_successor_reuses_the_released_judgement_verbatim():
    """One definition of what a decision *is*, down the whole chain.

    v3 delegates to v2, which delegates to the released builder. The three
    contracts therefore cannot drift on the counts, the pins or the
    accepted-artifact requirement; v3 adds exactly the two Snapshot B fields.
    """
    collection = _collection(2, kind="capability")
    shared = _kwargs_for("capability", collection)
    shared.update(
        snapshot_a_reference="snapshots/a.json", snapshot_a_sha256=SNAPSHOT_A_SHA
    )
    released = build_validation_decision_set_v2(
        decided_by=DECIDED_BY, decided_at=DECIDED_AT, **shared
    )
    successor = build_validation_decision_set_v3(
        decided_by=DECIDED_BY, decided_at=DECIDED_AT, **shared
    )
    assert set(successor) - set(released) == {
        "snapshot_b_reference",
        "snapshot_b_sha256",
    }
    for key in released:
        if key in ("contract", "schema_version"):
            continue
        assert successor[key] == released[key], key


def test_the_task_successor_serialization_is_deterministic():
    collection = _kind_collection("task", 2)
    assert decision_set_bytes(_v3(collection=collection)) == decision_set_bytes(
        _v3(collection=collection)
    )


# --- schema conformance, and the two-way closure ----------------------------


def _v3_schema() -> dict:
    return json.loads(
        (SCHEMAS / "extraction_validation_decision_set_v3.schema.json").read_text()
    )


@pytest.mark.parametrize("kind", ["product", "capability", "task"])
def test_every_kind_validates_against_the_successor_schema(kind):
    Draft202012Validator(_v3_schema()).validate(_v3(kind=kind))


def test_the_successor_document_is_refused_by_both_released_schemas():
    ds = _v3()
    for name in (
        "extraction_validation_decision_set.schema.json",
        "extraction_validation_decision_set_v2.schema.json",
    ):
        schema = json.loads((SCHEMAS / name).read_text())
        assert not Draft202012Validator(schema).is_valid(ds), name


def test_the_released_documents_are_refused_by_the_successor_schema():
    """Three-way closed: no loader accepts another contract's declared version."""
    validator = Draft202012Validator(_v3_schema())
    assert not validator.is_valid(build_validation_decision_set(**_released_kwargs()))
    assert not validator.is_valid(_v2())


def test_the_schema_refuses_a_task_document_that_pins_the_wrong_snapshot():
    """The schema carries the rule too; the builder is not its only owner."""
    validator = Draft202012Validator(_v3_schema())
    ds = _v3()
    assert validator.is_valid(ds)

    without_b = {**ds, "snapshot_b_reference": None, "snapshot_b_sha256": None}
    assert not validator.is_valid(without_b)

    with_a = {
        **ds,
        "snapshot_a_reference": "snapshots/a.json",
        "snapshot_a_sha256": SNAPSHOT_A_SHA,
    }
    assert not validator.is_valid(with_a)

    capability = _v3(kind="capability")
    assert validator.is_valid(capability)
    assert not validator.is_valid(
        {
            **capability,
            "snapshot_b_reference": "snapshots/b.json",
            "snapshot_b_sha256": SNAPSHOT_B_SHA,
        }
    )


def test_the_released_schemas_are_byte_identical():
    """Successor-not-mutate: @0.1.0 and @0.2.0 still declare two kinds only."""
    for name, version in (
        ("extraction_validation_decision_set.schema.json", "0.1.0"),
        ("extraction_validation_decision_set_v2.schema.json", "0.2.0"),
    ):
        schema = json.loads((SCHEMAS / name).read_text())
        assert schema["properties"]["observation_kind"]["enum"] == [
            "product",
            "capability",
        ], name
        assert "snapshot_b_reference" not in schema["properties"], name
        assert schema["properties"]["schema_version"]["const"] == version, name
