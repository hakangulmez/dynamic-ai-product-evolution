"""Slice 1A: evaluation-only schema-registry tests.

Tamper scenarios copy schemas into ``tmp_path``; repository schema files are
never modified.
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from dynamic_ai_products.evaluation import schemas as registry
from dynamic_ai_products.evaluation.schemas import (
    EVALUATION_SCHEMA_CONTRACTS,
    ReadOnlyContractError,
    SchemaContract,
    SchemaFileInvalidError,
    SchemaFileMissingError,
    SchemaHashMismatchError,
    SchemaMetaValidationError,
    UnknownContractError,
    load_schema,
)

ROOT = Path(__file__).resolve().parents[2]


def _tmp_repo(tmp_path: Path) -> Path:
    """A minimal repo copy WITHOUT the active schema-version manifest."""
    (tmp_path / "schemas").mkdir()
    for contract in EVALUATION_SCHEMA_CONTRACTS:
        shutil.copy(ROOT / contract.relative_path, tmp_path / contract.relative_path)
    return tmp_path


def test_loads_both_read_write_schemas() -> None:
    case_schema = load_schema("evaluation_case", "0.1.0", purpose="write")
    result_schema = load_schema("evaluation_result", "0.2.0", purpose="write")
    assert case_schema["$id"] == "evaluation_case.schema.json"
    assert result_schema["$id"] == "evaluation_result.v2.schema.json"


def test_compatibility_read_of_universe_manifest_v2() -> None:
    schema = load_schema("universe_run_manifest", "0.2.0", purpose="read")
    assert schema["$id"] == "universe_run_manifest.v2.schema.json"


def test_unknown_contract_id_fails_closed() -> None:
    with pytest.raises(UnknownContractError):
        load_schema("unknown_contract", "0.1.0")


def test_unknown_contract_version_fails_closed() -> None:
    with pytest.raises(UnknownContractError):
        load_schema("evaluation_case", "9.9.9")


def test_write_against_compat_read_only_fails_closed() -> None:
    with pytest.raises(ReadOnlyContractError):
        load_schema("universe_run_manifest", "0.2.0", purpose="write")


def test_missing_schema_file_fails_closed(tmp_path: Path) -> None:
    repo = _tmp_repo(tmp_path)
    (repo / "schemas" / "evaluation_case.schema.json").unlink()
    with pytest.raises(SchemaFileMissingError):
        load_schema("evaluation_case", "0.1.0", repo_root=repo)


def test_tampered_schema_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    repo = _tmp_repo(tmp_path)
    target = repo / "schemas" / "evaluation_case.schema.json"
    tampered = json.loads(target.read_text())
    tampered["properties"]["injected_field"] = {"type": "string"}
    target.write_text(json.dumps(tampered))
    with pytest.raises(SchemaHashMismatchError):
        load_schema("evaluation_case", "0.1.0", repo_root=repo)


def _patched_contract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raw: bytes) -> Path:
    """Register a synthetic contract whose reviewed hash matches ``raw``."""
    (tmp_path / "schemas").mkdir(exist_ok=True)
    path = tmp_path / "schemas" / "synthetic.schema.json"
    path.write_bytes(raw)
    contract = SchemaContract(
        contract_id="synthetic",
        contract_version="0.0.1",
        relative_path="schemas/synthetic.schema.json",
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        mode="read_write",
    )
    monkeypatch.setattr(
        registry, "EVALUATION_SCHEMA_CONTRACTS", (*EVALUATION_SCHEMA_CONTRACTS, contract)
    )
    return tmp_path


def test_malformed_json_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _patched_contract(monkeypatch, tmp_path, b"{not valid json")
    with pytest.raises(SchemaFileInvalidError):
        load_schema("synthetic", "0.0.1", repo_root=repo)


def test_meta_validation_failure_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invalid_schema = json.dumps({"type": 12345}).encode("utf-8")
    repo = _patched_contract(monkeypatch, tmp_path, invalid_schema)
    with pytest.raises(SchemaMetaValidationError):
        load_schema("synthetic", "0.0.1", repo_root=repo)


def test_registry_never_consults_active_schema_version_manifest(tmp_path: Path) -> None:
    repo = _tmp_repo(tmp_path)
    assert not (repo / "schemas" / "schema_version_manifest.json").exists()
    for contract in EVALUATION_SCHEMA_CONTRACTS:
        schema = load_schema(contract.contract_id, contract.contract_version, repo_root=repo)
        assert schema["$id"]


def test_loaded_schema_is_immutable() -> None:
    schema = load_schema("evaluation_case", "0.1.0")
    with pytest.raises(TypeError):
        schema["injected"] = True  # type: ignore[index]


def test_schema_loads_are_isolated_from_caller_mutation() -> None:
    """Fresh parsing on each load guarantees isolation.

    The top-level ``MappingProxyType`` does not itself provide deep
    immutability: nested dictionaries and lists inside a returned schema
    remain mutable. Isolation is guaranteed instead by parsing a fresh,
    independent object on every ``load_schema`` call, with no shared mutable
    schema cache.
    """
    contract = next(
        c for c in EVALUATION_SCHEMA_CONTRACTS if c.contract_id == "evaluation_case"
    )
    expected_hash_before = contract.expected_sha256

    first = load_schema("evaluation_case", "0.1.0")
    first["required"].append("injected_required_field")
    first["properties"]["stage_context"]["injected"] = {"type": "string"}

    second = load_schema("evaluation_case", "0.1.0")
    assert "injected_required_field" not in second["required"]
    assert "injected" not in second["properties"]["stage_context"]

    third = load_schema("evaluation_case", "0.1.0")
    assert "injected_required_field" not in third["required"]

    assert contract.expected_sha256 == expected_hash_before
    assert EVALUATION_SCHEMA_CONTRACTS == registry.EVALUATION_SCHEMA_CONTRACTS
