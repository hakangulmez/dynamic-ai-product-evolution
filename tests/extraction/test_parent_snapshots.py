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


# --- ADR-033 over the real HubSpot chain ------------------------------------
#
# Every case above is synthetic, which is the right shape for refusals: a
# fixture can be malformed on purpose. But "the members are correct" is a claim
# about a real chain, and a fixture that agrees with the code by construction
# cannot check it. These read the persisted artifacts the pipeline actually
# produced -- Snapshot A from the product run, the capability decision set from
# the capability run, and the Snapshot B built from both.

REAL_ROOT = (
    Path(__file__).resolve().parents[2] / "data/runs/decisions-ext-smoke-cap-0005-0001"
)
REAL_PRODUCT_ROOT = (
    Path(__file__).resolve().parents[2] / "data/runs/decisions-ext-smoke-0006-0002"
)
REAL_SNAPSHOT_A = "snapshots/parent_observation_snapshot_a.json"
REAL_SNAPSHOT_B = "snapshots/parent_observation_snapshot_b.json"
REAL_DECISION_SET = "decisions/extraction_validation_decision_set.json"
REAL_SNAPSHOT_A_SHA = (
    "a238cad7c460aaa77b15418d736a1568108674493c09137c184f6ea390c6959b"
)

requires_real_chain = pytest.mark.skipif(
    not (REAL_ROOT / REAL_SNAPSHOT_B).exists(),
    reason="the persisted HubSpot capability chain is not present in this checkout",
)


def _real(relative: str) -> dict:
    return json.loads((REAL_ROOT / relative).read_text(encoding="utf-8"))


@requires_real_chain
def test_the_snapshot_a_copy_is_byte_identical_to_the_product_root_original():
    """Snapshot B needed one artifact_root, so Snapshot A was copied, not moved.

    ``build_snapshot_b`` resolves every pin against a single root, and the two
    inputs lived in two roots. The copy is what closed that, and the property
    that makes it a copy rather than a second version is asserted here: the
    same bytes, and therefore the same digest the decision set already pins.
    """
    from hashlib import sha256

    original = (REAL_PRODUCT_ROOT / REAL_SNAPSHOT_A).read_bytes()
    copy = (REAL_ROOT / REAL_SNAPSHOT_A).read_bytes()
    assert copy == original
    assert sha256(copy).hexdigest() == REAL_SNAPSHOT_A_SHA
    assert _real(REAL_DECISION_SET)["snapshot_a_sha256"] == REAL_SNAPSHOT_A_SHA


@requires_real_chain
def test_the_real_snapshot_b_carries_every_product_parent_and_every_accepted_capability():
    """The counts, and where each one comes from.

    Eleven products are Snapshot A's members carried forward; sixty-nine
    capabilities are exactly the accepted decisions of the capability set, so a
    silently dropped or duplicated member fails here rather than surfacing as a
    thin task stage later.
    """
    snapshot_a = _real(REAL_SNAPSHOT_A)
    decisions = _real(REAL_DECISION_SET)
    snapshot_b = _real(REAL_SNAPSHOT_B)

    products = [m for m in snapshot_b["members"] if m["role"] == "product_parent"]
    capabilities = [
        m for m in snapshot_b["members"] if m["role"] == "capability_parent"
    ]
    accepted = [d for d in decisions["decisions"] if d["decision"] == "accept"]

    assert len(products) == 11
    assert len(capabilities) == 69
    assert len(snapshot_b["members"]) == 80
    assert len(accepted) == decisions["accepted_count"] == 69

    # Products: carried byte-unchanged from A, as whole member records.
    assert products == snapshot_a["members"]

    # Capabilities: exactly the accepted set, by reference and by digest.
    assert {(m["reference"], m["sha256"]) for m in capabilities} == {
        (d["accepted_artifact_reference"], d["accepted_artifact_sha256"])
        for d in accepted
    }


@requires_real_chain
def test_every_snapshot_b_member_resolves_and_hashes_true_in_one_root():
    """All eighty, in the root Snapshot B lives in.

    This is what the task stage needs: ``derive_parent_context`` re-reads and
    hash-verifies every member against a single ``artifact_root``, so a member
    that resolves only somewhere else is a member the task packet cannot use.
    """
    from hashlib import sha256

    members = _real(REAL_SNAPSHOT_B)["members"]
    assert len(members) == 80
    for member in members:
        target = REAL_ROOT / member["reference"]
        assert target.is_file(), member["reference"]
        assert sha256(target.read_bytes()).hexdigest() == member["sha256"]


@requires_real_chain
def test_the_product_members_were_copied_rather_than_repointed():
    """How the eighty came to be in one root, and what was *not* done to get there.

    Snapshot B carries A's member records byte-unchanged, so its eleven product
    pins name ``observations/product/...`` -- written against the *product*
    decision root. Copying Snapshot A made the snapshot readable here; it did
    not bring the observations the snapshot points at, and for a while sixty-nine
    members resolved and eleven did not.

    That gap was closed by copying those eleven files, not by rewriting a single
    reference or digest. The distinction is the point, and it is what this
    asserts: each copy is byte-identical to the original, each original is still
    in place and unchanged, and Snapshot B's own bytes were never touched.
    """
    from hashlib import sha256

    product_members = [
        m for m in _real(REAL_SNAPSHOT_B)["members"] if m["role"] == "product_parent"
    ]
    assert len(product_members) == 11

    for member in product_members:
        original = REAL_PRODUCT_ROOT / member["reference"]
        copy = REAL_ROOT / member["reference"]
        assert original.is_file(), member["reference"]
        assert copy.is_file(), member["reference"]
        assert copy.read_bytes() == original.read_bytes()
        assert sha256(copy.read_bytes()).hexdigest() == member["sha256"]

    # The pins are Snapshot A's, unaltered -- nothing was repointed to make the
    # copies resolve.
    assert product_members == _real(REAL_SNAPSHOT_A)["members"]


@requires_real_chain
def test_a_root_holding_only_the_capability_observations_leaves_eleven_unresolved(
    tmp_path,
):
    """The gap that existed, kept as an assertion rather than a memory.

    Reconstructed here instead of relied on: a root with Snapshot B and the
    capability observations but *not* the product ones is exactly what the
    capability decision root was before the copy, and eleven members do not
    resolve in it. Written this way the fact survives the fix -- deleting the
    copies is no longer needed to demonstrate it, and a future change that made
    the product references root-relative would fail here rather than quietly
    make this test vacuous.
    """
    from hashlib import sha256

    snapshot_b = _real(REAL_SNAPSHOT_B)
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "snapshots/parent_observation_snapshot_b.json").write_bytes(
        (REAL_ROOT / REAL_SNAPSHOT_B).read_bytes()
    )
    (tmp_path / "observations/capability").mkdir(parents=True)
    for member in snapshot_b["members"]:
        if member["role"] == "capability_parent":
            (tmp_path / member["reference"]).write_bytes(
                (REAL_ROOT / member["reference"]).read_bytes()
            )

    unresolved = [
        m for m in snapshot_b["members"] if not (tmp_path / m["reference"]).is_file()
    ]
    assert [m["role"] for m in unresolved] == ["product_parent"] * 11

    resolved = [m for m in snapshot_b["members"] if (tmp_path / m["reference"]).is_file()]
    assert len(resolved) == 69
    for member in resolved:
        assert (
            sha256((tmp_path / member["reference"]).read_bytes()).hexdigest()
            == member["sha256"]
        )


@requires_real_chain
def test_the_real_snapshot_b_keeps_a_s_context_and_takes_its_own_identity():
    """Same case, same company, same cutoff -- a different snapshot."""
    snapshot_a = _real(REAL_SNAPSHOT_A)
    snapshot_b = _real(REAL_SNAPSHOT_B)

    assert snapshot_b["contract"] == snapshot_a["contract"] == PARENT_SNAPSHOT_CONTRACT
    for field in ("case_id", "company_id", "observation_cutoff"):
        assert snapshot_b[field] == snapshot_a[field], field
    assert snapshot_b["snapshot_version"] == "capability-snapshot-b-hubspot-cap-0005-v1"
    assert snapshot_b["snapshot_version"] != snapshot_a["snapshot_version"]


@requires_real_chain
def test_the_real_snapshot_b_is_reproducible_from_its_two_pins():
    """The persisted bytes are what the builder produces, not an edited copy."""
    from hashlib import sha256

    decisions_bytes = (REAL_ROOT / REAL_DECISION_SET).read_bytes()
    rebuilt = build_snapshot_b(
        artifact_root=str(REAL_ROOT),
        snapshot_a_pin={
            "reference": REAL_SNAPSHOT_A,
            "sha256": REAL_SNAPSHOT_A_SHA,
            "snapshot_version": "product-snapshot-a-hubspot-0006-v1",
        },
        capability_decision_set_pin={
            "reference": REAL_DECISION_SET,
            "sha256": sha256(decisions_bytes).hexdigest(),
            "decision_set_version": "capability-validation-hubspot-cap-0005-v1",
        },
        snapshot_version="capability-snapshot-b-hubspot-cap-0005-v1",
    )
    assert snapshot_bytes(rebuilt) == (REAL_ROOT / REAL_SNAPSHOT_B).read_bytes()


@requires_real_chain
def test_the_real_snapshot_b_satisfies_the_released_evaluation_contract():
    ParentObservationSnapshot.model_validate(_real(REAL_SNAPSHOT_B))


# --- ADR-068 (E-T1): all four task pins resolve in one root -----------------

REAL_PRODUCT_DECISIONS = "decisions/product_extraction_validation_decision_set.json"
REAL_CAPABILITY_DECISIONS = "decisions/extraction_validation_decision_set.json"
REAL_SNAPSHOT_B_FILE = "snapshots/parent_observation_snapshot_b.json"


@requires_real_chain
def test_the_product_decision_set_was_copied_under_a_non_colliding_name():
    """The fourth pin, and why it could not keep its own filename.

    Snapshot A could be copied to the path its pin already named. The product
    decision set could not: ``decisions/extraction_validation_decision_set.json``
    in this root is the *capability* set, and one path cannot hold two
    documents. So the copy takes a distinct name -- which the packet builder
    accepts, because a decision-set reference is supplied by its pin and is not
    forced to a canonical constant anywhere in the code.
    """
    from hashlib import sha256

    original = REAL_PRODUCT_ROOT / REAL_CAPABILITY_DECISIONS
    copy = REAL_ROOT / REAL_PRODUCT_DECISIONS
    assert copy.is_file()
    assert copy.read_bytes() == original.read_bytes()
    assert sha256(copy.read_bytes()).hexdigest() == sha256(original.read_bytes()).hexdigest()
    assert json.loads(copy.read_text())["observation_kind"] == "product"

    # The capability set that already owned the canonical name is untouched.
    beside = REAL_ROOT / REAL_CAPABILITY_DECISIONS
    assert json.loads(beside.read_text())["observation_kind"] == "capability"
    assert beside.read_bytes() != copy.read_bytes()


@requires_real_chain
def test_all_four_task_pins_resolve_and_hash_true_in_one_root():
    """What the task stage actually needs, asserted as one property.

    ``build_extraction_input_packet`` hydrates Snapshot A, Snapshot B and both
    decision sets against a single ``artifact_root`` and refuses any reference
    that escapes it. Four files, one root, each read and hash-verified.
    """
    from hashlib import sha256

    pins = {
        "snapshot_a": REAL_SNAPSHOT_A,
        "snapshot_b": REAL_SNAPSHOT_B_FILE,
        "capability_decision_set": REAL_CAPABILITY_DECISIONS,
        "product_decision_set": REAL_PRODUCT_DECISIONS,
    }
    digests = {}
    for name, reference in pins.items():
        target = REAL_ROOT / reference
        assert target.is_file(), name
        digests[name] = sha256(target.read_bytes()).hexdigest()

    # Four distinct documents, not one file counted four times.
    assert len(set(digests.values())) == 4
    assert digests["snapshot_a"] == REAL_SNAPSHOT_A_SHA

    # And each is the document its name claims.
    assert json.loads((REAL_ROOT / pins["snapshot_a"]).read_text())[
        "snapshot_version"
    ] == "product-snapshot-a-hubspot-0006-v1"
    assert json.loads((REAL_ROOT / pins["snapshot_b"]).read_text())[
        "snapshot_version"
    ] == "capability-snapshot-b-hubspot-cap-0005-v1"
    assert json.loads((REAL_ROOT / pins["capability_decision_set"]).read_text())[
        "decision_set_version"
    ] == "capability-validation-hubspot-cap-0005-v1"
    assert json.loads((REAL_ROOT / pins["product_decision_set"]).read_text())[
        "decision_set_version"
    ] == "product-validation-hubspot-0006-v1"


@requires_real_chain
def test_the_task_packet_builds_from_that_root_alone():
    """End to end: the five equalities of ``reconcile_snapshot_b`` pass.

    This is the check the four copies exist for. Before them the builder refused
    with ``snapshot_a_product_members_mismatch`` -- the product decision set was
    simply not in the root it was resolved against.
    """
    from tests.extraction.test_contents_renderer import _real_task_packet

    packet = _real_task_packet()
    assert packet["contract"] == "extraction_input_packet@0.2.0"
    assert len(packet["parent_context"]["product_parents"]) == 11
    assert len(packet["parent_context"]["capability_parents"]) == 69
    assert packet["parent_context"]["snapshot"]["snapshot_version"] == (
        "capability-snapshot-b-hubspot-cap-0005-v1"
    )
