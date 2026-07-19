"""Slice 1A: deterministic canonical contract-hash tests."""

import json

import pytest
from pydantic import BaseModel

from dynamic_ai_products.evaluation.contracts import (
    ContractHashMismatchError,
    InvalidContractIdentityError,
    build_contract_envelope,
    canonical_contract_bytes,
    contract_hash,
    model_contract_hash,
    runtime_contract_provenance,
    verify_contract_hash,
)

SCHEMA = {"type": "object", "properties": {"b": {"type": "string"}, "a": {"type": "integer"}}}


def test_identical_envelopes_produce_identical_bytes_and_hashes() -> None:
    first = build_contract_envelope("case", "0.1.0", SCHEMA)
    second = build_contract_envelope("case", "0.1.0", json.loads(json.dumps(SCHEMA)))
    assert canonical_contract_bytes(first) == canonical_contract_bytes(second)
    assert contract_hash("case", "0.1.0", SCHEMA) == contract_hash("case", "0.1.0", SCHEMA)


def test_key_insertion_order_does_not_affect_hash() -> None:
    reordered = {"properties": {"a": {"type": "integer"}, "b": {"type": "string"}}, "type": "object"}
    assert contract_hash("case", "0.1.0", SCHEMA) == contract_hash("case", "0.1.0", reordered)


def test_unicode_is_encoded_deterministically() -> None:
    schema = {"description": "ünïcode – ölçüm"}
    payload = canonical_contract_bytes(build_contract_envelope("case", "0.1.0", schema))
    assert "ünïcode – ölçüm".encode("utf-8") in payload
    assert contract_hash("case", "0.1.0", schema) == contract_hash("case", "0.1.0", dict(schema))


def test_contract_id_changes_hash() -> None:
    assert contract_hash("case", "0.1.0", SCHEMA) != contract_hash("other", "0.1.0", SCHEMA)


def test_contract_version_changes_hash() -> None:
    assert contract_hash("case", "0.1.0", SCHEMA) != contract_hash("case", "0.2.0", SCHEMA)


def test_generated_schema_change_changes_hash() -> None:
    class ModelA(BaseModel):
        value: str

    class ModelB(BaseModel):
        value: str
        extra: int = 0

    assert model_contract_hash(ModelA, "case", "0.1.0") != model_contract_hash(
        ModelB, "case", "0.1.0"
    )


def test_verification_accepts_correct_hash() -> None:
    declared = contract_hash("case", "0.1.0", SCHEMA)
    verify_contract_hash(declared, "case", "0.1.0", SCHEMA)


def test_verification_rejects_mismatch() -> None:
    with pytest.raises(ContractHashMismatchError):
        verify_contract_hash("0" * 64, "case", "0.1.0", SCHEMA)


@pytest.mark.parametrize("contract_id,contract_version", [("", "0.1.0"), ("case", ""), ("  ", "0.1.0"), ("case", "  ")])
def test_empty_identity_is_rejected(contract_id: str, contract_version: str) -> None:
    with pytest.raises(InvalidContractIdentityError):
        contract_hash(contract_id, contract_version, SCHEMA)


def test_runtime_provenance_records_pydantic_version() -> None:
    import pydantic

    provenance = runtime_contract_provenance()
    assert provenance["pydantic_version"] == pydantic.VERSION
    assert provenance["python_version"]
