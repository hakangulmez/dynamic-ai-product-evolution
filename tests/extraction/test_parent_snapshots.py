"""Snapshot A and Snapshot B construction, refusals, and carry-over (ADR-033).

Both instances share ``parent_observation_snapshot@0.1.0``; the contract
version never changes. They differ only in members, ``snapshot_version``, and
SHA-256. Inputs are **identity pins only**, so a forged payload has no channel
into the chain, and every emitted snapshot must satisfy locally the invariants
the released ``ParentObservationSnapshot`` would enforce.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dynamic_ai_products.evaluation.parent_observation_snapshot import (
    ParentObservationSnapshot,
)
from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.parent_snapshots import (
    PARENT_SNAPSHOT_CONTRACT,
    build_snapshot_a,
    build_snapshot_b,
    snapshot_bytes,
)
from dynamic_ai_products.extraction.raw_artifacts import write_artifact

DECISION_SET_CONTRACT = "extraction_validation_decision_set@0.1.0"
CUTOFF = "2024-12-31"


def _accept(reference: str, digest: str) -> dict:
    return {
        "candidate_id": digest[:32],
        "decision": "accept",
        "reason": "",
        "accepted_artifact_reference": reference,
        "accepted_artifact_sha256": digest,
    }


def _decision_set(kind: str, accepted: list[tuple[str, str]], **extra) -> dict:
    payload = {
        "contract": DECISION_SET_CONTRACT,
        "schema_version": "0.1.0",
        "observation_kind": kind,
        "decisions": [_accept(ref, sha) for ref, sha in accepted],
    }
    payload.update(extra)
    return payload


def _persist(root: Path, reference: str, payload: dict) -> dict:
    digest = write_artifact(root, reference, json.dumps(payload).encode("utf-8"))
    return {"reference": reference, "sha256": digest}


def _product_set(root: Path, accepted, reference="decisions/product.json") -> dict:
    return _persist(root, reference, _decision_set("product", accepted))


def _capability_set(root: Path, accepted, snapshot_a_pin, reference="decisions/cap.json"):
    return _persist(
        root,
        reference,
        _decision_set(
            "capability",
            accepted,
            snapshot_a_reference=snapshot_a_pin["reference"],
            snapshot_a_sha256=snapshot_a_pin["sha256"],
        ),
    )


def _snapshot_a(root: Path, accepted, **overrides) -> dict:
    kwargs = {
        "artifact_root": str(root),
        "product_decision_set_pin": _product_set(root, accepted),
        "snapshot_version": "a-1",
        "case_id": "case-1",
        "company_id": "CIK0001404655",
        "observation_cutoff": CUTOFF,
    }
    kwargs.update(overrides)
    return build_snapshot_a(**kwargs)


def _publish_a(root: Path, snapshot: dict, reference="snapshots/a.json") -> dict:
    pin = _persist(root, reference, snapshot)
    pin["snapshot_version"] = snapshot["snapshot_version"]
    return pin


PRODUCTS = [("observations/product/p1.json", "1" * 64)]
CAPABILITIES = [("observations/capability/c1.json", "2" * 64)]


# --- Snapshot A ---------------------------------------------------------------


def test_snapshot_a_members_are_exactly_the_accepted_product_artifacts(tmp_path: Path):
    snapshot = _snapshot_a(tmp_path, PRODUCTS)
    assert snapshot["members"] == [
        {
            "role": "product_parent",
            "reference": "observations/product/p1.json",
            "sha256": "1" * 64,
        }
    ]
    assert snapshot["contract"] == PARENT_SNAPSHOT_CONTRACT


def test_a_built_snapshot_validates_against_the_released_model(tmp_path: Path):
    ParentObservationSnapshot.model_validate(_snapshot_a(tmp_path, PRODUCTS))


def test_snapshot_a_refuses_an_empty_accepted_product_set(tmp_path: Path):
    """The released model rejects empty members; refuse before emitting."""
    with pytest.raises(ExtractionError) as excinfo:
        _snapshot_a(tmp_path, [])
    assert excinfo.value.reason_code == "snapshot_invalid"


def test_a_capability_decision_set_cannot_author_snapshot_a(tmp_path: Path):
    pin = _persist(tmp_path, "decisions/cap.json", _decision_set("capability", PRODUCTS))
    with pytest.raises(ExtractionError) as excinfo:
        _snapshot_a(tmp_path, PRODUCTS, product_decision_set_pin=pin)
    assert excinfo.value.reason_code == "observation_kind_invalid"


def test_a_decision_set_without_its_released_contract_is_refused(tmp_path: Path):
    payload = _decision_set("product", PRODUCTS)
    payload["contract"] = "something_else@0.1.0"
    pin = _persist(tmp_path, "decisions/forged.json", payload)
    with pytest.raises(ExtractionError) as excinfo:
        _snapshot_a(tmp_path, PRODUCTS, product_decision_set_pin=pin)
    assert excinfo.value.reason_code == "validation_provenance_missing"


def test_caller_supplied_contract_metadata_is_refused(tmp_path: Path):
    with pytest.raises(ExtractionError) as excinfo:
        _snapshot_a(tmp_path, PRODUCTS, contract_metadata={"contract_hash": "f" * 64})
    assert excinfo.value.reason_code == "contract_metadata_forbidden"


# --- Refusal cases required by the emitted-snapshot invariants ----------------


@pytest.mark.parametrize(
    "cutoff", ["2024-12-32", "20241231", "2024-12-31T00:00:00", "31-12-2024", "", "  "]
)
def test_a_non_canonical_observation_cutoff_is_refused(tmp_path: Path, cutoff):
    with pytest.raises(ExtractionError) as excinfo:
        _snapshot_a(tmp_path, PRODUCTS, observation_cutoff=cutoff)
    assert excinfo.value.reason_code == "snapshot_invalid"
    assert not (tmp_path / "snapshots").exists()


@pytest.mark.parametrize(
    "reference",
    [
        "../escape.json",
        "/etc/passwd",
        "C:/windows/x.json",
        "a\\b.json",
        ".",
        "a//b.json",
        "a/",
        "/a",
        "a/./b.json",
        "a/../b.json",
        "  ",
    ],
)
def test_an_unsafe_accepted_artifact_reference_is_refused(tmp_path: Path, reference):
    with pytest.raises(ExtractionError) as excinfo:
        _snapshot_a(tmp_path, [(reference, "1" * 64)])
    assert excinfo.value.reason_code == "snapshot_invalid"


def test_an_ordinary_nested_reference_remains_valid(tmp_path: Path):
    snapshot = _snapshot_a(tmp_path, [("a/b.json", "1" * 64)])
    assert snapshot["members"][0]["reference"] == "a/b.json"


@pytest.mark.parametrize("digest", ["short", "F" * 64, "g" * 64, None, 64 * "1" + "1"])
def test_a_malformed_accepted_digest_is_refused(tmp_path: Path, digest):
    payload = _decision_set("product", [])
    payload["decisions"] = [
        {
            "candidate_id": "0" * 32,
            "decision": "accept",
            "reason": "",
            "accepted_artifact_reference": "observations/p.json",
            "accepted_artifact_sha256": digest,
        }
    ]
    pin = _persist(tmp_path, "decisions/bad.json", payload)
    with pytest.raises(ExtractionError) as excinfo:
        _snapshot_a(tmp_path, [], product_decision_set_pin=pin)
    assert excinfo.value.reason_code == "validation_provenance_missing"


def test_the_same_reference_under_two_roles_is_refused(tmp_path: Path):
    """A shared reference would make one artifact two different parents."""
    shared = "observations/shared.json"
    snapshot_a = _snapshot_a(tmp_path, [(shared, "1" * 64)])
    pin_a = _publish_a(tmp_path, snapshot_a)
    capability_pin = _capability_set(tmp_path, [(shared, "2" * 64)], pin_a)
    with pytest.raises(ExtractionError) as excinfo:
        build_snapshot_b(
            artifact_root=str(tmp_path),
            snapshot_a_pin=pin_a,
            capability_decision_set_pin=capability_pin,
            snapshot_version="b-1",
        )
    assert excinfo.value.reason_code == "snapshot_invalid"


def test_a_duplicated_accepted_reference_is_refused(tmp_path: Path):
    pin = _persist(
        tmp_path,
        "decisions/dupe.json",
        _decision_set(
            "product",
            [("observations/p.json", "1" * 64), ("observations/p.json", "1" * 64)],
        ),
    )
    with pytest.raises(ExtractionError) as excinfo:
        _snapshot_a(tmp_path, [], product_decision_set_pin=pin)
    assert excinfo.value.reason_code == "snapshot_invalid"


# --- Snapshot B ---------------------------------------------------------------


def test_snapshot_b_carries_snapshot_a_product_members_byte_unchanged(tmp_path: Path):
    snapshot_a = _snapshot_a(tmp_path, PRODUCTS)
    pin_a = _publish_a(tmp_path, snapshot_a)
    snapshot_b = build_snapshot_b(
        artifact_root=str(tmp_path),
        snapshot_a_pin=pin_a,
        capability_decision_set_pin=_capability_set(tmp_path, CAPABILITIES, pin_a),
        snapshot_version="b-1",
    )
    products = [m for m in snapshot_b["members"] if m["role"] == "product_parent"]
    assert products == snapshot_a["members"]
    assert [m["role"] for m in snapshot_b["members"]] == [
        "capability_parent",
        "product_parent",
    ]


def test_snapshot_b_inherits_a_context_fields_without_coercion(tmp_path: Path):
    snapshot_a = _snapshot_a(tmp_path, PRODUCTS)
    pin_a = _publish_a(tmp_path, snapshot_a)
    snapshot_b = build_snapshot_b(
        artifact_root=str(tmp_path),
        snapshot_a_pin=pin_a,
        capability_decision_set_pin=_capability_set(tmp_path, CAPABILITIES, pin_a),
        snapshot_version="b-1",
    )
    for field in ("case_id", "company_id", "observation_cutoff"):
        assert snapshot_b[field] == snapshot_a[field]
    assert snapshot_b["snapshot_version"] == "b-1"
    ParentObservationSnapshot.model_validate(snapshot_b)


def test_a_zero_capability_snapshot_b_is_legal(tmp_path: Path):
    """Role presence can never discriminate A from B; identity does."""
    snapshot_a = _snapshot_a(tmp_path, PRODUCTS)
    pin_a = _publish_a(tmp_path, snapshot_a)
    snapshot_b = build_snapshot_b(
        artifact_root=str(tmp_path),
        snapshot_a_pin=pin_a,
        capability_decision_set_pin=_capability_set(tmp_path, [], pin_a),
        snapshot_version="b-1",
    )
    assert snapshot_b["members"] == snapshot_a["members"]
    assert snapshot_b["snapshot_version"] != snapshot_a["snapshot_version"]
    assert snapshot_bytes(snapshot_b) != snapshot_bytes(snapshot_a)
    ParentObservationSnapshot.model_validate(snapshot_b)


def test_snapshot_b_must_have_a_distinct_version(tmp_path: Path):
    snapshot_a = _snapshot_a(tmp_path, PRODUCTS)
    pin_a = _publish_a(tmp_path, snapshot_a)
    with pytest.raises(ExtractionError) as excinfo:
        build_snapshot_b(
            artifact_root=str(tmp_path),
            snapshot_a_pin=pin_a,
            capability_decision_set_pin=_capability_set(tmp_path, CAPABILITIES, pin_a),
            snapshot_version="a-1",
        )
    assert excinfo.value.reason_code == "parent_context_wrong_snapshot"


def test_a_capability_set_pinning_another_snapshot_a_is_refused(tmp_path: Path):
    pin_a = _publish_a(tmp_path, _snapshot_a(tmp_path, PRODUCTS))
    foreign = {"reference": "snapshots/other.json", "sha256": "9" * 64}
    with pytest.raises(ExtractionError) as excinfo:
        build_snapshot_b(
            artifact_root=str(tmp_path),
            snapshot_a_pin=pin_a,
            capability_decision_set_pin=_capability_set(tmp_path, CAPABILITIES, foreign),
            snapshot_version="b-1",
        )
    assert excinfo.value.reason_code == "capability_decision_snapshot_a_mismatch"


def test_a_snapshot_a_carrying_a_capability_parent_is_refused(tmp_path: Path):
    """Snapshot A is product-only; a capability member there is a forgery."""
    forged = _snapshot_a(tmp_path, PRODUCTS)
    forged["members"] = [
        {
            "role": "capability_parent",
            "reference": "observations/capability/c1.json",
            "sha256": "2" * 64,
        }
    ]
    pin_a = _publish_a(tmp_path, forged, reference="snapshots/forged.json")
    with pytest.raises(ExtractionError) as excinfo:
        build_snapshot_b(
            artifact_root=str(tmp_path),
            snapshot_a_pin=pin_a,
            capability_decision_set_pin=_capability_set(tmp_path, CAPABILITIES, pin_a),
            snapshot_version="b-1",
        )
    assert excinfo.value.reason_code == "snapshot_invalid"


def test_an_unknown_role_in_snapshot_a_is_never_silently_omitted(tmp_path: Path):
    forged = _snapshot_a(tmp_path, PRODUCTS)
    forged["members"] = forged["members"] + [
        {"role": "task_parent", "reference": "observations/t.json", "sha256": "3" * 64}
    ]
    pin_a = _publish_a(tmp_path, forged, reference="snapshots/unknown_role.json")
    with pytest.raises(ExtractionError) as excinfo:
        build_snapshot_b(
            artifact_root=str(tmp_path),
            snapshot_a_pin=pin_a,
            capability_decision_set_pin=_capability_set(tmp_path, CAPABILITIES, pin_a),
            snapshot_version="b-1",
        )
    assert excinfo.value.reason_code == "snapshot_invalid"


@pytest.mark.parametrize(
    "mutation",
    [
        {"contract": "parent_observation_snapshot@0.1.0"},
        {"contract": None},
        {"case_id": ""},
        {"company_id": 7},
        {"observation_cutoff": "not-a-date"},
        {"members": []},
        {"members": "not-a-list"},
    ],
)
def test_a_malformed_snapshot_a_is_refused_before_carry_over(tmp_path: Path, mutation):
    forged = _snapshot_a(tmp_path, PRODUCTS)
    forged.update(mutation)
    pin_a = _publish_a(tmp_path, forged, reference="snapshots/mutated.json")
    with pytest.raises(ExtractionError) as excinfo:
        build_snapshot_b(
            artifact_root=str(tmp_path),
            snapshot_a_pin=pin_a,
            capability_decision_set_pin=_capability_set(tmp_path, CAPABILITIES, pin_a),
            snapshot_version="b-1",
        )
    assert excinfo.value.reason_code == "snapshot_invalid"


def test_out_of_order_snapshot_a_members_are_refused(tmp_path: Path):
    forged = _snapshot_a(
        tmp_path,
        [("observations/a.json", "1" * 64), ("observations/b.json", "2" * 64)],
    )
    forged["members"] = list(reversed(forged["members"]))
    pin_a = _publish_a(tmp_path, forged, reference="snapshots/unordered.json")
    with pytest.raises(ExtractionError) as excinfo:
        build_snapshot_b(
            artifact_root=str(tmp_path),
            snapshot_a_pin=pin_a,
            capability_decision_set_pin=_capability_set(tmp_path, CAPABILITIES, pin_a),
            snapshot_version="b-1",
        )
    assert excinfo.value.reason_code == "snapshot_member_order_invalid"


def test_a_snapshot_a_whose_bytes_drifted_is_refused(tmp_path: Path):
    pin_a = _publish_a(tmp_path, _snapshot_a(tmp_path, PRODUCTS))
    pin_a = {**pin_a, "sha256": "0" * 64}
    with pytest.raises(ExtractionError) as excinfo:
        build_snapshot_b(
            artifact_root=str(tmp_path),
            snapshot_a_pin=pin_a,
            capability_decision_set_pin=_capability_set(tmp_path, CAPABILITIES, pin_a),
            snapshot_version="b-1",
        )
    assert excinfo.value.reason_code == "snapshot_pin_sha_mismatch"


def test_serialization_is_deterministic(tmp_path: Path):
    snapshot = _snapshot_a(tmp_path, PRODUCTS)
    assert snapshot_bytes(snapshot) == snapshot_bytes(snapshot)
    assert snapshot_bytes(snapshot).endswith(b"\n")
