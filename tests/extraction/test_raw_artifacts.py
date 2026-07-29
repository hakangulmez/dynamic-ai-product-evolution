"""Canonical serialization, write-once persistence, and raw preservation.

Raw provider bytes are preserved literally and never repaired in place
(CLAUDE.md rule 9). The canonical serializers must stay byte-identical to the
ingestion and collection serializers; extraction may not import those packages,
so equality is pinned by a cross-package test rather than a shared import.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dynamic_ai_products.collection import publication as collection_publication
from dynamic_ai_products.ingestion import publication as ingestion_publication
from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.raw_artifacts import (
    PREDICTION_ENVELOPE_CONTRACT,
    build_prediction_envelope,
    canonical_json_bytes,
    canonical_jsonl_bytes,
    reject_contract_metadata,
    sha256_bytes,
    write_artifact,
    write_raw_prediction,
)


def test_canonical_json_is_sorted_compact_and_newline_terminated():
    payload = {"b": 1, "a": {"d": 2, "c": 3}}
    assert canonical_json_bytes(payload) == b'{"a":{"c":3,"d":2},"b":1}\n'


def test_canonical_json_preserves_non_ascii_without_escaping():
    assert canonical_json_bytes({"k": "é"}) == '{"k":"é"}\n'.encode("utf-8")


def test_canonical_jsonl_emits_one_record_per_line():
    assert canonical_jsonl_bytes([{"b": 1}, {"a": 2}]) == b'{"b":1}\n{"a":2}\n'


def test_canonical_jsonl_of_nothing_is_empty_not_a_blank_line():
    assert canonical_jsonl_bytes([]) == b""


def test_three_package_serializers_agree_byte_for_byte():
    """ADR-027 anti-drift: three canonical serializers, one byte sequence.

    Extraction may not import ingestion or collection, so equality is pinned
    here instead of by a shared import.
    """
    payload = {"z": [1, {"y": "x"}], "a": None, "m": "é"}
    mine = canonical_json_bytes(payload)
    assert mine == collection_publication.canonical_json_bytes(payload)
    assert mine == ingestion_publication.canonical_json_bytes(payload)

    records = [{"b": 1}, {"a": "é"}]
    lines = canonical_jsonl_bytes(records)
    assert lines == collection_publication.canonical_jsonl_bytes(records)
    assert lines == ingestion_publication.canonical_jsonl_bytes(records)


def test_sha256_bytes_matches_the_documented_digest():
    assert sha256_bytes(b"") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_write_artifact_returns_the_verified_digest_and_persists_exact_bytes(tmp_path):
    data = b'{"a":1}\n'
    digest = write_artifact(tmp_path, "nested/dir/a.json", data)
    assert digest == sha256_bytes(data)
    assert (tmp_path / "nested" / "dir" / "a.json").read_bytes() == data


def test_write_artifact_refuses_a_second_write(tmp_path):
    write_artifact(tmp_path, "a.json", b"1")
    with pytest.raises(ExtractionError) as excinfo:
        write_artifact(tmp_path, "a.json", b"2")
    assert excinfo.value.reason_code == "destination_exists"


def test_raw_prediction_bytes_are_never_normalized(tmp_path):
    """Malformed provider output is preserved literally, not repaired."""
    raw = b'  {"trailing": "junk"} \n\n not json at all '
    digest = write_raw_prediction(tmp_path, "predictions/raw.json", raw)
    assert (tmp_path / "predictions" / "raw.json").read_bytes() == raw
    assert digest == sha256_bytes(raw)


def test_raw_prediction_accepts_bytearray_and_stores_bytes(tmp_path):
    write_raw_prediction(tmp_path, "raw.bin", bytearray(b"\x00\xff"))
    assert (tmp_path / "raw.bin").read_bytes() == b"\x00\xff"


@pytest.mark.parametrize("payload", ["a string", None, 7, {"a": 1}])
def test_raw_prediction_refuses_anything_that_is_not_bytes(tmp_path, payload):
    with pytest.raises(ExtractionError) as excinfo:
        write_raw_prediction(tmp_path, "raw.json", payload)
    assert excinfo.value.reason_code == "raw_artifact_invalid"


def test_caller_supplied_contract_metadata_is_refused():
    with pytest.raises(ExtractionError) as excinfo:
        reject_contract_metadata({"contract_metadata": {"contract_hash": "x"}})
    assert excinfo.value.reason_code == "contract_metadata_forbidden"


def test_a_contract_key_smuggled_through_a_mapping_is_refused():
    with pytest.raises(ExtractionError) as excinfo:
        reject_contract_metadata({}, {"contract": {"contract_hash": "x"}})
    assert excinfo.value.reason_code == "contract_metadata_forbidden"


def test_clean_mappings_pass_through():
    reject_contract_metadata({}, {"model_name": "x"}, None, "not-a-mapping")


def _envelope(**overrides):
    kwargs = {
        "prediction_record_id": "run-0",
        "stage": "product_extraction",
        "source_references": ["predictions/raw_prediction.json"],
        "prompt_model_metadata": {"model_name": "fake"},
        "input_packet_hash": "a" * 64,
        "prediction_run_manifest_reference": "predictions/prediction_run_manifest.json",
        "input_packet_reference": "inputs/extraction_input_packet.json",
    }
    kwargs.update(overrides)
    return build_prediction_envelope(**kwargs)


def test_envelope_contract_comes_only_from_the_closed_pin():
    envelope = _envelope()
    assert envelope["contract"] == PREDICTION_ENVELOPE_CONTRACT
    assert envelope["contract"] is not PREDICTION_ENVELOPE_CONTRACT


def test_envelope_always_references_the_stage_input_packet():
    """Corpus scope and inherited coverage reach the harness through the packet."""
    envelope = _envelope()
    assert "inputs/extraction_input_packet.json" in envelope["source_references"]
    assert envelope["source_references"] == sorted(envelope["source_references"])


def test_a_packet_reference_already_present_is_not_duplicated():
    envelope = _envelope(
        source_references=[
            "inputs/extraction_input_packet.json",
            "predictions/raw_prediction.json",
        ]
    )
    assert envelope["source_references"].count("inputs/extraction_input_packet.json") == 1


def test_an_envelope_without_a_packet_reference_is_refused():
    with pytest.raises(ExtractionError) as excinfo:
        _envelope(input_packet_reference="")
    assert excinfo.value.reason_code == "envelope_missing_input_packet"


def test_no_caller_channel_can_override_the_envelope_contract_stamp():
    with pytest.raises(ExtractionError) as excinfo:
        _envelope(contract_metadata={"contract_hash": "f" * 64})
    assert excinfo.value.reason_code == "contract_metadata_forbidden"

    with pytest.raises(ExtractionError) as excinfo:
        _envelope(prompt_model_metadata={"contract": {"contract_hash": "f" * 64}})
    assert excinfo.value.reason_code == "contract_metadata_forbidden"


def test_envelope_serializes_deterministically(tmp_path: Path):
    first = canonical_json_bytes(_envelope())
    second = canonical_json_bytes(_envelope())
    assert first == second
    assert json.loads(first.decode("utf-8"))["stage"] == "product_extraction"
