"""Validation-driven snapshot reconciliation: the five equalities (ADR-033).

Hash-verifying a snapshot proves it **intact, not authorized**. Every snapshot
is reconciled against the decision sets that authorized it before any parent
context is derived.

Stage 06 requires two equalities; Stage 07 requires five:

- **E1** Snapshot A's ``product_parent`` members equal the accepted product
  artifacts in the *product* decision set;
- **E2** the capability decision set's pinned Snapshot A equals the loaded A;
- **E3** Snapshot B's ``product_parent`` members equal A's byte-for-byte;
- **E4** Snapshot B's ``capability_parent`` members equal the accepted
  capability artifacts;
- **E5** every referenced member artifact re-reads to its recorded SHA-256.

Stage 07 re-runs E1 on purpose: E2-E5 are internal to the A/B/capability
triple, so a self-consistent forged A satisfies all four.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.input_packet import (
    build_extraction_input_packet,
    derive_parent_context,
    reconcile_snapshot_a,
    reconcile_snapshot_b,
)
from dynamic_ai_products.extraction.raw_artifacts import write_artifact

CUTOFF = "2024-12-31"
COMPANY = "CIK0001404655"
COVERAGE = {"reference": "coverage/source_family_coverage.json", "sha256": "d" * 64}
SOURCE_MANIFEST = {"reference": "snapshots/manifest.json", "sha256": "e" * 64}
DATES = {"sec-1": "2024-02-14"}
PASSAGES = [
    {
        "passage_id": "p-1",
        "source_id": "sec-1",
        "text": "the product ships an assistant",
        "start_offset": 0,
        "end_offset": 30,
    }
]


def _write(root: Path, reference: str, payload) -> dict:
    digest = write_artifact(root, reference, json.dumps(payload).encode("utf-8"))
    return {"reference": reference, "sha256": digest}


class Chain:
    """A complete, mutually consistent A/B chain persisted under one root."""

    def __init__(self, root: Path, *, capability_count: int = 1) -> None:
        self.root = root
        self.products = [
            _write(
                root,
                f"observations/product/p{i}.json",
                {"product_observation_id": f"prod-{i}", "product_name": f"P{i}"},
            )
            for i in range(2)
        ]
        self.capabilities = [
            _write(
                root,
                f"observations/capability/c{i}.json",
                {"capability_observation_id": f"cap-{i}", "capability": f"C{i}"},
            )
            for i in range(capability_count)
        ]
        self.product_decisions_pin = _write(
            root, "decisions/product.json", self._decision_set("product", self.products)
        )
        self.snapshot_a = {
            "contract": "parent_observation_snapshot@0.1.0",
            "snapshot_version": "a-1",
            "case_id": "case-1",
            "company_id": COMPANY,
            "observation_cutoff": CUTOFF,
            "members": self._members("product_parent", self.products),
        }
        self.snapshot_a_pin = self._publish("snapshots/a.json", self.snapshot_a, "a-1")
        self.capability_decisions_pin = _write(
            root,
            "decisions/capability.json",
            self._decision_set(
                "capability",
                self.capabilities,
                snapshot_a_reference=self.snapshot_a_pin["reference"],
                snapshot_a_sha256=self.snapshot_a_pin["sha256"],
            ),
        )
        self.snapshot_b = {
            "contract": "parent_observation_snapshot@0.1.0",
            "snapshot_version": "b-1",
            "case_id": "case-1",
            "company_id": COMPANY,
            "observation_cutoff": CUTOFF,
            "members": sorted(
                self._members("product_parent", self.products)
                + self._members("capability_parent", self.capabilities),
                key=lambda m: (m["role"], m["reference"]),
            ),
        }
        self.snapshot_b_pin = self._publish("snapshots/b.json", self.snapshot_b, "b-1")

    # -- construction helpers --
    @staticmethod
    def _members(role: str, pins: list[dict]) -> list[dict]:
        return sorted(
            ({"role": role, **pin} for pin in pins),
            key=lambda m: (m["role"], m["reference"]),
        )

    @staticmethod
    def _decision_set(kind: str, pins: list[dict], **extra) -> dict:
        payload = {
            "contract": "extraction_validation_decision_set@0.1.0",
            "observation_kind": kind,
            "raw_artifact_sha256": "9" * 64,
            "candidate_collection_sha256": "8" * 64,
            "decisions": [
                {
                    "candidate_id": pin["sha256"][:32],
                    "decision": "accept",
                    "reason": "",
                    "accepted_artifact_reference": pin["reference"],
                    "accepted_artifact_sha256": pin["sha256"],
                }
                for pin in pins
            ],
        }
        payload.update(extra)
        return payload

    def _publish(self, reference: str, payload: dict, version: str) -> dict:
        pin = _write(self.root, reference, payload)
        pin["snapshot_version"] = version
        return pin

    def republish(self, reference: str, payload: dict, version: str) -> dict:
        return self._publish(reference, payload, version)

    # -- packet builders --
    def capability_packet(self, **overrides):
        kwargs = {
            "stage": "capability_extraction",
            "company_id": COMPANY,
            "observation_cutoff_date": CUTOFF,
            "passages": list(PASSAGES),
            "document_publication_dates": dict(DATES),
            "coverage_artifact": dict(COVERAGE),
            "source_snapshot_manifest": dict(SOURCE_MANIFEST),
            "artifact_root": str(self.root),
            "snapshot_a_pin": self.snapshot_a_pin,
            "product_decision_set_pin": self.product_decisions_pin,
        }
        kwargs.update(overrides)
        return build_extraction_input_packet(**kwargs)

    def task_packet(self, **overrides):
        kwargs = {
            "stage": "task_extraction",
            "company_id": COMPANY,
            "observation_cutoff_date": CUTOFF,
            "passages": list(PASSAGES),
            "document_publication_dates": dict(DATES),
            "coverage_artifact": dict(COVERAGE),
            "source_snapshot_manifest": dict(SOURCE_MANIFEST),
            "artifact_root": str(self.root),
            "snapshot_a_pin": self.snapshot_a_pin,
            "snapshot_b_pin": self.snapshot_b_pin,
            "product_decision_set_pin": self.product_decisions_pin,
            "capability_decision_set_pin": self.capability_decisions_pin,
        }
        kwargs.update(overrides)
        return build_extraction_input_packet(**kwargs)


# --- routing is by pinned identity, never by member shape ---------------------


@pytest.mark.parametrize(
    "stage,consumed_snapshot_version",
    [
        ("capability_extraction", "a-1"),
        ("task_extraction", "b-1"),
    ],
)
def test_each_stage_consumes_its_own_snapshot(tmp_path: Path, stage, consumed_snapshot_version):
    """Stage 06 consumes Snapshot A; Stage 07 consumes Snapshot B."""
    chain = Chain(tmp_path)
    packet = (
        chain.capability_packet()
        if stage == "capability_extraction"
        else chain.task_packet()
    )
    assert packet["stage"] == stage
    assert packet["parent_context"]["snapshot"]["snapshot_version"] == (
        consumed_snapshot_version
    )


def test_a_zero_capability_snapshot_b_is_a_valid_snapshot_b(tmp_path: Path):
    """Role presence can never discriminate A from B: a legal B may carry none."""
    chain = Chain(tmp_path, capability_count=0)
    assert [m["role"] for m in chain.snapshot_b["members"]] == [
        "product_parent",
        "product_parent",
    ]
    packet = chain.task_packet()
    assert packet["parent_context"]["capability_parents"] == []
    assert len(packet["parent_context"]["product_parents"]) == 2
    assert packet["parent_context"]["snapshot"]["snapshot_version"] == "b-1"


def test_snapshot_b_cannot_be_substituted_for_snapshot_a(tmp_path: Path):
    """A capability member proves the supplied snapshot is not an A.

    E1 alone cannot catch this: B carries A's product members byte-for-byte by
    construction (E3), so the product-triple comparison succeeds. Only the
    product-only rule refuses it.
    """
    chain = Chain(tmp_path)
    with pytest.raises(ExtractionError) as excinfo:
        chain.capability_packet(snapshot_a_pin=chain.snapshot_b_pin)
    assert excinfo.value.reason_code == "parent_context_wrong_snapshot"


def test_a_zero_capability_snapshot_b_is_still_not_refused_for_its_shape(tmp_path: Path):
    """Absence never proves identity: this B is refused by E1, not by shape.

    With zero accepted capabilities, B's member list is identical to A's, so no
    shape rule can distinguish them. Substituting it for A therefore reaches the
    same product-triple comparison A would - and passes it, because the members
    genuinely are the accepted product artifacts. The guard is deliberately
    one-directional and this case documents its limit.
    """
    chain = Chain(tmp_path, capability_count=0)
    packet = chain.capability_packet(snapshot_a_pin=chain.snapshot_b_pin)
    assert packet["parent_context"]["snapshot"]["snapshot_version"] == "b-1"


def test_a_snapshot_a_forged_with_a_capability_member_is_refused(tmp_path: Path):
    chain = Chain(tmp_path)
    forged = dict(chain.snapshot_a)
    forged["members"] = sorted(
        chain.snapshot_a["members"]
        + [{"role": "capability_parent", **chain.capabilities[0]}],
        key=lambda m: (m["role"], m["reference"]),
    )
    pin = chain.republish("snapshots/a_with_capability.json", forged, "a-1")
    with pytest.raises(ExtractionError) as excinfo:
        chain.capability_packet(snapshot_a_pin=pin)
    assert excinfo.value.reason_code == "parent_context_wrong_snapshot"


# --- Stage 06: E1 + E5 --------------------------------------------------------


def test_the_capability_stage_derives_parents_only_from_verified_members(tmp_path: Path):
    chain = Chain(tmp_path)
    packet = chain.capability_packet()
    parents = packet["parent_context"]["product_parents"]
    assert [p["observation_id"] for p in parents] == ["prod-0", "prod-1"]
    for parent, pin in zip(parents, chain.products):
        assert parent["reference"] == pin["reference"]
        assert parent["sha256"] == pin["sha256"]
    assert packet["product_validation_provenance"]["reference"] == (
        chain.product_decisions_pin["reference"]
    )
    assert packet["capability_validation_provenance"] is None


def test_e1_an_extra_member_not_accepted_by_a_human_is_refused(tmp_path: Path):
    chain = Chain(tmp_path)
    smuggled = _write(tmp_path, "observations/product/x.json", {"product_observation_id": "x"})
    forged = dict(chain.snapshot_a)
    forged["members"] = sorted(
        chain.snapshot_a["members"] + [{"role": "product_parent", **smuggled}],
        key=lambda m: (m["role"], m["reference"]),
    )
    pin = chain.republish("snapshots/a_forged.json", forged, "a-1")
    with pytest.raises(ExtractionError) as excinfo:
        chain.capability_packet(snapshot_a_pin=pin)
    assert excinfo.value.reason_code == "snapshot_a_product_members_mismatch"


def test_e1_a_missing_accepted_member_is_refused(tmp_path: Path):
    chain = Chain(tmp_path)
    forged = dict(chain.snapshot_a)
    forged["members"] = chain.snapshot_a["members"][:1]
    pin = chain.republish("snapshots/a_short.json", forged, "a-1")
    with pytest.raises(ExtractionError) as excinfo:
        chain.capability_packet(snapshot_a_pin=pin)
    assert excinfo.value.reason_code == "snapshot_a_product_members_mismatch"


def test_e5_a_member_artifact_whose_bytes_changed_is_refused(tmp_path: Path):
    chain = Chain(tmp_path)
    forged = dict(chain.snapshot_a)
    forged["members"] = [
        {**m, "sha256": "0" * 64} for m in chain.snapshot_a["members"]
    ]
    decisions = Chain._decision_set(
        "product", [{"reference": m["reference"], "sha256": "0" * 64} for m in forged["members"]]
    )
    decisions_pin = _write(tmp_path, "decisions/product_drift.json", decisions)
    pin = chain.republish("snapshots/a_drift.json", forged, "a-1")
    with pytest.raises(ExtractionError) as excinfo:
        chain.capability_packet(
            snapshot_a_pin=pin, product_decision_set_pin=decisions_pin
        )
    assert excinfo.value.reason_code == "parent_member_hash_mismatch"


def test_reconcile_snapshot_a_returns_the_verified_members(tmp_path: Path):
    chain = Chain(tmp_path)
    members = reconcile_snapshot_a(
        artifact_root=tmp_path,
        snapshot_a=chain.snapshot_a,
        product_decision_set=json.loads(
            (tmp_path / chain.product_decisions_pin["reference"]).read_text()
        ),
    )
    assert [m["reference"] for m in members] == [p["reference"] for p in chain.products]


# --- Stage 07: all five -------------------------------------------------------


def test_the_task_stage_derives_both_parent_roles(tmp_path: Path):
    chain = Chain(tmp_path)
    context = chain.task_packet()["parent_context"]
    assert [p["observation_id"] for p in context["product_parents"]] == [
        "prod-0",
        "prod-1",
    ]
    assert [p["observation_id"] for p in context["capability_parents"]] == ["cap-0"]
    assert context["snapshot"] == chain.snapshot_b_pin


def test_the_task_packet_carries_both_validation_provenances(tmp_path: Path):
    packet = Chain(tmp_path).task_packet()
    assert packet["product_validation_provenance"]["sha256"]
    assert packet["capability_validation_provenance"]["sha256"]
    assert packet["capability_validation_provenance"]["raw_artifact_sha256"] == "9" * 64


def test_e2_a_capability_set_pinning_a_different_snapshot_a_is_refused(tmp_path: Path):
    chain = Chain(tmp_path)
    foreign = Chain._decision_set(
        "capability",
        chain.capabilities,
        snapshot_a_reference="snapshots/other.json",
        snapshot_a_sha256="7" * 64,
    )
    pin = _write(tmp_path, "decisions/capability_foreign.json", foreign)
    with pytest.raises(ExtractionError) as excinfo:
        chain.task_packet(capability_decision_set_pin=pin)
    assert excinfo.value.reason_code == "capability_decision_snapshot_a_mismatch"


def test_e3_snapshot_b_must_carry_a_product_members_byte_for_byte(tmp_path: Path):
    chain = Chain(tmp_path)
    forged = dict(chain.snapshot_b)
    forged["members"] = [
        m for m in chain.snapshot_b["members"] if m["role"] == "capability_parent"
    ] + chain.snapshot_a["members"][:1]
    forged["members"].sort(key=lambda m: (m["role"], m["reference"]))
    pin = chain.republish("snapshots/b_dropped.json", forged, "b-1")
    with pytest.raises(ExtractionError) as excinfo:
        chain.task_packet(snapshot_b_pin=pin)
    assert excinfo.value.reason_code == "snapshot_b_product_carryover_mismatch"


def test_e4_snapshot_b_capability_members_must_equal_the_accepted_set(tmp_path: Path):
    chain = Chain(tmp_path)
    smuggled = _write(
        tmp_path, "observations/capability/x.json", {"capability_observation_id": "x"}
    )
    forged = dict(chain.snapshot_b)
    forged["members"] = sorted(
        chain.snapshot_b["members"] + [{"role": "capability_parent", **smuggled}],
        key=lambda m: (m["role"], m["reference"]),
    )
    pin = chain.republish("snapshots/b_extra.json", forged, "b-1")
    with pytest.raises(ExtractionError) as excinfo:
        chain.task_packet(snapshot_b_pin=pin)
    assert excinfo.value.reason_code == "snapshot_b_capability_members_mismatch"


def test_stage_07_re_runs_e1_and_defeats_a_self_consistent_forged_a(tmp_path: Path):
    """E2-E5 are triple-internal, so only E1 reaches the human product judgement.

    The forgery below is *completely* self-consistent: a forged A, a B built
    from that forged A's product members plus genuinely accepted capabilities,
    and a capability decision set pinning the forged A. E2, E3, E4, and E5 all
    pass. Only E1 detects it.
    """
    chain = Chain(tmp_path)
    smuggled = _write(
        tmp_path, "observations/product/smuggled.json", {"product_observation_id": "ghost"}
    )
    forged_a = dict(chain.snapshot_a)
    forged_a["members"] = sorted(
        chain.snapshot_a["members"] + [{"role": "product_parent", **smuggled}],
        key=lambda m: (m["role"], m["reference"]),
    )
    forged_a_pin = chain.republish("snapshots/a_ghost.json", forged_a, "a-1")

    capability_pin = _write(
        tmp_path,
        "decisions/capability_ghost.json",
        Chain._decision_set(
            "capability",
            chain.capabilities,
            snapshot_a_reference=forged_a_pin["reference"],
            snapshot_a_sha256=forged_a_pin["sha256"],
        ),
    )
    forged_b = dict(chain.snapshot_b)
    forged_b["members"] = sorted(
        forged_a["members"]
        + [m for m in chain.snapshot_b["members"] if m["role"] == "capability_parent"],
        key=lambda m: (m["role"], m["reference"]),
    )
    forged_b_pin = chain.republish("snapshots/b_ghost.json", forged_b, "b-1")

    # E2-E5 hold for this triple. Prove it, then show E1 still refuses.
    loaded_a = json.loads((tmp_path / forged_a_pin["reference"]).read_text())
    loaded_b = json.loads((tmp_path / forged_b_pin["reference"]).read_text())
    capability_decisions = json.loads((tmp_path / capability_pin["reference"]).read_text())
    assert capability_decisions["snapshot_a_sha256"] == forged_a_pin["sha256"]  # E2
    assert [m for m in loaded_b["members"] if m["role"] == "product_parent"] == (
        loaded_a["members"]
    )  # E3

    with pytest.raises(ExtractionError) as excinfo:
        chain.task_packet(
            snapshot_a_pin=forged_a_pin,
            snapshot_b_pin=forged_b_pin,
            capability_decision_set_pin=capability_pin,
        )
    assert excinfo.value.reason_code == "snapshot_a_product_members_mismatch"


def test_reconcile_snapshot_b_returns_b_members_when_all_five_hold(tmp_path: Path):
    chain = Chain(tmp_path)
    members = reconcile_snapshot_b(
        artifact_root=tmp_path,
        snapshot_a=chain.snapshot_a,
        snapshot_a_pin=chain.snapshot_a_pin,
        snapshot_b=chain.snapshot_b,
        product_decision_set=json.loads(
            (tmp_path / chain.product_decisions_pin["reference"]).read_text()
        ),
        capability_decision_set=json.loads(
            (tmp_path / chain.capability_decisions_pin["reference"]).read_text()
        ),
    )
    assert len(members) == 3


# --- derived parent context ---------------------------------------------------


def test_parents_carry_the_observation_id_reference_and_digest(tmp_path: Path):
    chain = Chain(tmp_path)
    parents = derive_parent_context(
        artifact_root=tmp_path,
        members=chain.snapshot_b["members"],
        role="capability_parent",
    )
    assert parents == [
        {
            "observation_id": "cap-0",
            "reference": chain.capabilities[0]["reference"],
            "sha256": chain.capabilities[0]["sha256"],
            "payload": {"capability_observation_id": "cap-0", "capability": "C0"},
        }
    ]


def test_an_observation_without_its_id_field_is_refused(tmp_path: Path):
    pin = _write(tmp_path, "observations/product/anon.json", {"product_name": "no id"})
    with pytest.raises(ExtractionError) as excinfo:
        derive_parent_context(
            artifact_root=tmp_path,
            members=[{"role": "product_parent", **pin}],
            role="product_parent",
        )
    assert excinfo.value.reason_code == "parent_id_not_in_snapshot"


def test_derivation_re_verifies_the_member_digest(tmp_path: Path):
    pin = _write(tmp_path, "observations/product/p.json", {"product_observation_id": "p"})
    with pytest.raises(ExtractionError) as excinfo:
        derive_parent_context(
            artifact_root=tmp_path,
            members=[{"role": "product_parent", "reference": pin["reference"], "sha256": "0" * 64}],
            role="product_parent",
        )
    assert excinfo.value.reason_code == "parent_member_hash_mismatch"


def test_derived_parents_are_deterministically_ordered(tmp_path: Path):
    chain = Chain(tmp_path)
    forward = derive_parent_context(
        artifact_root=tmp_path,
        members=chain.snapshot_a["members"],
        role="product_parent",
    )
    reverse = derive_parent_context(
        artifact_root=tmp_path,
        members=list(reversed(chain.snapshot_a["members"])),
        role="product_parent",
    )
    assert forward == reverse
