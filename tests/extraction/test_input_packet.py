"""Stage scoping, admissibility, and pin hydration for the input packet.

Snapshot and decision-set **content is never caller-supplied**: callers pass
identity pins, and this module re-reads the bytes and verifies them first.
There is no document parameter through which a forged payload could enter.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.input_packet import (
    CORPUS_SCOPE_SEC_ONLY,
    hydrate_pinned_artifact,
    PACKET_CONTRACT,
    STAGES,
    build_extraction_input_packet,
    hydrate_decision_set,
    hydrate_snapshot,
    packet_bytes,
)
from dynamic_ai_products.extraction.raw_artifacts import write_artifact

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"
CUTOFF = "2024-12-31"
COMPANY = "CIK0001404655"
COVERAGE = {"reference": "coverage/source_family_coverage.json", "sha256": "d" * 64}
SOURCE_MANIFEST = {
    "reference": "snapshots/source_passage_snapshot_manifest.json",
    "sha256": "e" * 64,
}
DATES = {"sec-1": "2024-02-14", "sec-late": "2025-06-01"}


def _passage(passage_id: str, text: str, source_id: str = "sec-1", start: int = 0):
    return {
        "passage_id": passage_id,
        "source_id": source_id,
        "text": text,
        "start_offset": start,
        "end_offset": start + len(text),
    }


def _packet(**overrides):
    kwargs = {
        "stage": "product_extraction",
        "company_id": COMPANY,
        "observation_cutoff_date": CUTOFF,
        "passages": [_passage("p-1", "a capability exists")],
        "document_publication_dates": DATES,
        "coverage_artifact": dict(COVERAGE),
        "source_snapshot_manifest": dict(SOURCE_MANIFEST),
    }
    kwargs.update(overrides)
    return build_extraction_input_packet(**kwargs)


def _persist(root: Path, reference: str, payload: dict) -> dict:
    digest = write_artifact(root, reference, json.dumps(payload).encode("utf-8"))
    return {"reference": reference, "sha256": digest}


# --- shape and scope carriers -------------------------------------------------


def test_declared_stages_and_scope():
    assert STAGES == ("product_extraction", "capability_extraction", "task_extraction")
    assert PACKET_CONTRACT == "extraction_input_packet@0.1.0"
    assert CORPUS_SCOPE_SEC_ONLY == "sec_only_partial"


def test_the_packet_carries_corpus_scope_and_the_coverage_pin():
    """Exactly two scope carriers exist; there is no third scope artifact."""
    packet = _packet()
    assert packet["corpus_scope"] == "sec_only_partial"
    assert packet["coverage_artifact"] == COVERAGE
    assert packet["source_snapshot_manifest"] == SOURCE_MANIFEST


def test_a_product_packet_conforms_to_its_released_schema():
    schema = json.loads((SCHEMAS / "extraction_input_packet.schema.json").read_text())
    Draft202012Validator(schema).validate(_packet())


def test_serialization_is_deterministic():
    assert packet_bytes(_packet()) == packet_bytes(_packet())
    assert packet_bytes(_packet()).endswith(b"\n")


# --- context validation -------------------------------------------------------


def test_an_unknown_stage_is_refused():
    with pytest.raises(ExtractionError) as excinfo:
        _packet(stage="marketing_extraction")
    assert excinfo.value.reason_code == "packet_stage_invalid"


@pytest.mark.parametrize("company", ["HUBS", "CIK123", "cik0001404655", ""])
def test_a_malformed_company_id_is_refused(company):
    with pytest.raises(ExtractionError) as excinfo:
        _packet(company_id=company)
    assert excinfo.value.reason_code == "packet_context_invalid"


@pytest.mark.parametrize("cutoff", ["2024/12/31", "20241231", "December 2024", ""])
def test_a_malformed_cutoff_is_refused(cutoff):
    with pytest.raises(ExtractionError) as excinfo:
        _packet(observation_cutoff_date=cutoff)
    assert excinfo.value.reason_code == "packet_context_invalid"


@pytest.mark.parametrize("field", ["coverage_artifact", "source_snapshot_manifest"])
def test_a_malformed_pin_digest_is_refused(field):
    with pytest.raises(ExtractionError) as excinfo:
        _packet(**{field: {"reference": "x.json", "sha256": "nope"}})
    assert excinfo.value.reason_code == "pin_invalid"


def test_no_undeclared_input_may_reach_the_packet():
    """Parent ids are derived, never supplied."""
    with pytest.raises(ExtractionError) as excinfo:
        _packet(product_parents=[{"observation_id": "prod-1"}])
    assert excinfo.value.reason_code == "parent_id_not_in_snapshot"


# --- admissibility ------------------------------------------------------------


def test_a_single_character_passage_is_admissible():
    """There is no length threshold; the committed corpus contains such rows."""
    packet = _packet(passages=[_passage("p-1", "7")])
    assert [p["passage_id"] for p in packet["passages"]] == ["p-1"]
    assert packet["filter_ledger"]["blank_drop_count"] == 0


@pytest.mark.parametrize("text", ["", "   ", "\n\t ", None, 7])
def test_blank_or_non_string_text_is_dropped_with_a_reason(text):
    packet = _packet(passages=[_passage("p-1", "kept"), {**_passage("p-2", "x"), "text": text}])
    assert [p["passage_id"] for p in packet["passages"]] == ["p-1"]
    assert packet["filter_ledger"]["blank_drops"] == [
        {"passage_id": "p-2", "reason": "blank_text"}
    ]


def test_a_passage_published_after_the_cutoff_is_dropped():
    packet = _packet(
        passages=[_passage("p-1", "kept"), _passage("p-2", "late", source_id="sec-late")]
    )
    assert [p["passage_id"] for p in packet["passages"]] == ["p-1"]
    assert packet["filter_ledger"]["temporal_drops"] == [
        {"passage_id": "p-2", "reason": "temporally_invalid"}
    ]


def test_a_passage_published_exactly_on_the_cutoff_is_admissible():
    packet = _packet(
        passages=[_passage("p-1", "same day", source_id="sec-edge")],
        document_publication_dates={"sec-edge": CUTOFF},
    )
    assert len(packet["passages"]) == 1


def test_a_passage_with_no_known_publication_date_is_dropped():
    packet = _packet(passages=[_passage("p-1", "orphan", source_id="unknown-doc")])
    assert packet["passages"] == []
    assert packet["filter_ledger"]["temporal_drop_count"] == 1


def test_the_filter_ledger_accounts_for_every_input_passage():
    packet = _packet(
        passages=[
            _passage("p-1", "kept", start=1),
            _passage("p-2", "", start=2),
            _passage("p-3", "late", source_id="sec-late", start=3),
        ]
    )
    ledger = packet["filter_ledger"]
    assert ledger["input_passage_count"] == 3
    assert ledger["blank_drop_count"] + ledger["temporal_drop_count"] + ledger[
        "surviving_count"
    ] == 3


def test_admissible_passages_are_deterministically_ordered():
    passages = [
        _passage("p-3", "c", start=30),
        _passage("p-1", "a", start=10),
        _passage("p-2", "b", start=20),
    ]
    assert [p["passage_id"] for p in _packet(passages=passages)["passages"]] == [
        "p-1",
        "p-2",
        "p-3",
    ]
    assert [p["passage_id"] for p in _packet(passages=passages[::-1])["passages"]] == [
        "p-1",
        "p-2",
        "p-3",
    ]


# --- hydration is the only channel -------------------------------------------


def test_a_pinned_snapshot_is_read_from_disk_and_verified(tmp_path: Path):
    payload = {"snapshot_version": "a-1", "members": []}
    pin = _persist(tmp_path, "snapshots/a.json", payload)
    loaded = hydrate_snapshot(tmp_path, {**pin, "snapshot_version": "a-1"})
    assert loaded == payload


def test_a_snapshot_whose_bytes_drifted_is_refused(tmp_path: Path):
    pin = _persist(tmp_path, "snapshots/a.json", {"snapshot_version": "a-1"})
    with pytest.raises(ExtractionError) as excinfo:
        hydrate_snapshot(tmp_path, {**pin, "sha256": "0" * 64, "snapshot_version": "a-1"})
    assert excinfo.value.reason_code == "snapshot_pin_sha_mismatch"


@pytest.mark.parametrize(
    "reference",
    ["../escape.json", "/etc/passwd", "C:/windows/a.json", "a\\b.json", "", "  "],
)
def test_an_unsafe_snapshot_reference_is_refused(tmp_path: Path, reference):
    with pytest.raises(ExtractionError) as excinfo:
        hydrate_snapshot(
            tmp_path,
            {"reference": reference, "sha256": "0" * 64, "snapshot_version": "a-1"},
        )
    assert excinfo.value.reason_code == "snapshot_reference_unsafe"


def test_a_drive_qualified_reference_cannot_masquerade_as_relative(tmp_path: Path):
    """"C:/x" is not absolute on POSIX and would resolve inside the root."""
    inside = tmp_path / "C:"
    inside.mkdir()
    pin = _persist(tmp_path, "C:/a.json", {"snapshot_version": "a-1"})
    with pytest.raises(ExtractionError) as excinfo:
        hydrate_snapshot(tmp_path, {**pin, "snapshot_version": "a-1"})
    assert excinfo.value.reason_code == "snapshot_reference_unsafe"


def test_a_symlinked_reference_is_refused(tmp_path: Path):
    outside = tmp_path.parent / "outside.json"
    outside.write_bytes(b"{}")
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "snapshots" / "a.json").symlink_to(outside)
    with pytest.raises(ExtractionError) as excinfo:
        hydrate_snapshot(
            tmp_path,
            {
                "reference": "snapshots/a.json",
                "sha256": "0" * 64,
                "snapshot_version": "a-1",
            },
        )
    assert excinfo.value.reason_code == "snapshot_reference_unsafe"


@pytest.mark.parametrize("pinned", [None, "", "   ", 7, {"v": 1}])
def test_a_versionless_snapshot_cannot_authenticate_itself(tmp_path: Path, pinned):
    """None on both sides would compare equal without this guard."""
    pin = _persist(tmp_path, "snapshots/a.json", {"members": []})
    with pytest.raises(ExtractionError) as excinfo:
        hydrate_snapshot(tmp_path, {**pin, "snapshot_version": pinned})
    assert excinfo.value.reason_code == "snapshot_pin_version_mismatch"


def test_a_snapshot_version_mismatch_is_refused(tmp_path: Path):
    pin = _persist(tmp_path, "snapshots/a.json", {"snapshot_version": "a-1"})
    with pytest.raises(ExtractionError) as excinfo:
        hydrate_snapshot(tmp_path, {**pin, "snapshot_version": "b-1"})
    assert excinfo.value.reason_code == "snapshot_pin_version_mismatch"


def test_non_json_and_non_object_payloads_are_refused(tmp_path: Path):
    digest = write_artifact(tmp_path, "decisions/bad.json", b"not json")
    with pytest.raises(ExtractionError) as excinfo:
        hydrate_decision_set(tmp_path, {"reference": "decisions/bad.json", "sha256": digest})
    assert excinfo.value.reason_code == "decision_set_pin_sha_mismatch"

    digest = write_artifact(tmp_path, "decisions/list.json", b"[1,2]")
    with pytest.raises(ExtractionError) as excinfo:
        hydrate_decision_set(tmp_path, {"reference": "decisions/list.json", "sha256": digest})
    assert excinfo.value.reason_code == "decision_set_pin_sha_mismatch"


def test_a_missing_artifact_is_refused(tmp_path: Path):
    with pytest.raises(ExtractionError) as excinfo:
        hydrate_decision_set(
            tmp_path, {"reference": "decisions/absent.json", "sha256": "0" * 64}
        )
    assert excinfo.value.reason_code == "decision_set_pin_sha_mismatch"


@pytest.mark.parametrize("pin", [None, "a string", 7, []])
def test_a_non_mapping_pin_is_refused(tmp_path: Path, pin):
    with pytest.raises(ExtractionError) as excinfo:
        hydrate_decision_set(tmp_path, pin)
    assert excinfo.value.reason_code == "decision_set_reference_unsafe"


# --- stage scoping ------------------------------------------------------------


def test_the_product_stage_forbids_parent_context():
    for field in (
        "snapshot_a_pin",
        "snapshot_b_pin",
        "product_decision_set_pin",
        "capability_decision_set_pin",
    ):
        with pytest.raises(ExtractionError) as excinfo:
            _packet(**{field: {"reference": "x.json", "sha256": "0" * 64}})
        assert excinfo.value.reason_code == "parent_context_forbidden", field


def test_a_product_packet_carries_no_parent_context_or_provenance():
    packet = _packet()
    assert packet["parent_context"] is None
    assert packet["product_validation_provenance"] is None
    assert packet["capability_validation_provenance"] is None


def test_the_capability_stage_requires_the_snapshot_a_identity():
    with pytest.raises(ExtractionError) as excinfo:
        _packet(stage="capability_extraction")
    assert excinfo.value.reason_code == "parent_context_missing"


def test_the_capability_stage_requires_product_validation_provenance():
    with pytest.raises(ExtractionError) as excinfo:
        _packet(
            stage="capability_extraction",
            snapshot_a_pin={"reference": "a.json", "sha256": "0" * 64},
        )
    assert excinfo.value.reason_code == "validation_provenance_missing"


@pytest.mark.parametrize("field", ["snapshot_b_pin", "capability_decision_set_pin"])
def test_the_capability_stage_refuses_task_stage_inputs(field):
    with pytest.raises(ExtractionError) as excinfo:
        _packet(
            stage="capability_extraction",
            snapshot_a_pin={"reference": "a.json", "sha256": "0" * 64},
            **{field: {"reference": "b.json", "sha256": "1" * 64}},
        )
    assert excinfo.value.reason_code == "parent_context_wrong_snapshot"


def test_the_task_stage_requires_both_snapshots_and_both_provenances():
    with pytest.raises(ExtractionError) as excinfo:
        _packet(stage="task_extraction")
    assert excinfo.value.reason_code == "parent_context_missing"

    with pytest.raises(ExtractionError) as excinfo:
        _packet(
            stage="task_extraction",
            snapshot_b_pin={"reference": "b.json", "sha256": "1" * 64},
        )
    assert excinfo.value.reason_code == "parent_context_missing"


@pytest.mark.parametrize(
    "pin_b",
    [
        {"reference": "a.json", "sha256": "1" * 64, "snapshot_version": "b-1"},
        {"reference": "b.json", "sha256": "0" * 64, "snapshot_version": "b-1"},
        {"reference": "b.json", "sha256": "1" * 64, "snapshot_version": "a-1"},
    ],
)
def test_snapshot_a_and_b_must_be_distinct_pinned_identities(pin_b):
    with pytest.raises(ExtractionError) as excinfo:
        _packet(
            stage="task_extraction",
            snapshot_a_pin={
                "reference": "a.json",
                "sha256": "0" * 64,
                "snapshot_version": "a-1",
            },
            snapshot_b_pin=pin_b,
        )
    assert excinfo.value.reason_code == "parent_context_wrong_snapshot"


# --- the public governance hydrator (ADR-035) ---------------------------------


def test_the_public_hydrator_shares_the_containment_and_hash_discipline(tmp_path: Path):
    """Governance artifacts are read through exactly this loader, so no second
    set of containment rules can drift from these."""
    pin = _persist(tmp_path, "governance/authorization.json", {"a": 1})
    loaded = hydrate_pinned_artifact(
        tmp_path,
        pin,
        what="live call authorization",
        unsafe_code="authorization_chain_broken",
        sha_code="authorization_chain_broken",
    )
    assert loaded == {"a": 1}


@pytest.mark.parametrize(
    "reference",
    ["../escape.json", "/etc/passwd", "C:/x.json", "a\\b.json", "", "  "],
)
def test_the_public_hydrator_refuses_an_unsafe_reference(tmp_path: Path, reference):
    with pytest.raises(ExtractionError) as excinfo:
        hydrate_pinned_artifact(
            tmp_path,
            {"reference": reference, "sha256": "0" * 64},
            what="live call authorization",
            unsafe_code="authorization_chain_broken",
            sha_code="authorization_chain_broken",
        )
    assert excinfo.value.reason_code == "authorization_chain_broken"


def test_the_public_hydrator_refuses_a_drifted_digest(tmp_path: Path):
    pin = _persist(tmp_path, "governance/authorization.json", {"a": 1})
    with pytest.raises(ExtractionError) as excinfo:
        hydrate_pinned_artifact(
            tmp_path,
            {**pin, "sha256": "0" * 64},
            what="live call authorization",
            unsafe_code="authorization_chain_broken",
            sha_code="authorization_chain_broken",
        )
    assert excinfo.value.reason_code == "authorization_chain_broken"


def test_the_public_hydrator_refuses_a_symlink(tmp_path: Path):
    outside = tmp_path.parent / "outside-governance.json"
    outside.write_bytes(b"{}")
    (tmp_path / "governance").mkdir()
    (tmp_path / "governance" / "authorization.json").symlink_to(outside)
    with pytest.raises(ExtractionError) as excinfo:
        hydrate_pinned_artifact(
            tmp_path,
            {"reference": "governance/authorization.json", "sha256": "0" * 64},
            what="live call authorization",
            unsafe_code="authorization_chain_broken",
            sha_code="authorization_chain_broken",
        )
    assert excinfo.value.reason_code == "authorization_chain_broken"
