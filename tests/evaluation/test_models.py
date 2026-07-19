"""Slice 1A: strict/frozen model foundation tests."""

import pytest
from pydantic import ValidationError

from dynamic_ai_products.evaluation.models import ContractMetadata, EvaluationStrictModel


class _Example(EvaluationStrictModel):
    name: str


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _Example(name="ok", unexpected="boom")


def test_instances_are_frozen() -> None:
    instance = _Example(name="ok")
    with pytest.raises(ValidationError):
        instance.name = "changed"


def test_contract_metadata_round_trip() -> None:
    meta = ContractMetadata(
        contract_id="evaluation_case",
        contract_version="0.1.0",
        contract_hash="a" * 64,
    )
    assert meta.contract_id == "evaluation_case"
    assert meta.model_dump() == {
        "contract_id": "evaluation_case",
        "contract_version": "0.1.0",
        "contract_hash": "a" * 64,
    }


@pytest.mark.parametrize("field", ["contract_id", "contract_version", "contract_hash"])
def test_contract_metadata_rejects_empty_fields(field: str) -> None:
    payload = {
        "contract_id": "evaluation_case",
        "contract_version": "0.1.0",
        "contract_hash": "a" * 64,
    }
    payload[field] = ""
    with pytest.raises(ValidationError):
        ContractMetadata(**payload)


@pytest.mark.parametrize("field", ["contract_id", "contract_version"])
@pytest.mark.parametrize(
    "bad_value",
    [" ", "   ", "\t", " case", "case ", " 0.1.0", "0.1.0 "],
    ids=["space", "spaces", "tab", "leading", "trailing", "leading-version", "trailing-version"],
)
def test_identity_whitespace_is_rejected(field: str, bad_value: str) -> None:
    payload = {
        "contract_id": "evaluation_case",
        "contract_version": "0.1.0",
        "contract_hash": "a" * 64,
    }
    payload[field] = bad_value
    with pytest.raises(ValidationError):
        ContractMetadata(**payload)


@pytest.mark.parametrize(
    "bad_hash",
    ["", "a" * 63, "a" * 65, "g" * 64, "A" * 64, ("a" * 63) + "Z"],
    ids=["empty", "short", "long", "non-hex", "uppercase", "mixed-invalid"],
)
def test_malformed_contract_hash_is_rejected(bad_hash: str) -> None:
    with pytest.raises(ValidationError):
        ContractMetadata(
            contract_id="evaluation_case",
            contract_version="0.1.0",
            contract_hash=bad_hash,
        )


def test_valid_lowercase_sha256_hash_is_accepted() -> None:
    digest = "0123456789abcdef" * 4
    meta = ContractMetadata(
        contract_id="evaluation case",
        contract_version="0.1.0",
        contract_hash=digest,
    )
    assert meta.contract_hash == digest


def test_valid_identities_are_preserved_exactly() -> None:
    meta = ContractMetadata(
        contract_id="Evaluation Case",
        contract_version="0.1.0-Draft",
        contract_hash="b" * 64,
    )
    assert meta.contract_id == "Evaluation Case"
    assert meta.contract_version == "0.1.0-Draft"
