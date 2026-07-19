"""Evaluation-only static-schema registry (Slice 1A).

This registry is the evaluation package's activation boundary from the build
plan: it binds evaluation contract IDs and versions to exact schema paths
and reviewed expected file hashes, and it fails closed on any unknown
contract, missing file, malformed JSON, hash mismatch, meta-validation
failure, or write attempt against a compatibility-read-only contract.

It never reads or modifies `schemas/schema_version_manifest.json`, never
touches Phase 0 writer or validation selection, and never imports the
Phase 0 freeze/runner writer path. The expected hashes are reviewed registry
constants, not values derived from the files being verified.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from ..universe.io_utils import sha256_bytes
from .models import EvaluationStrictModel

_REPO_ROOT = Path(__file__).resolve().parents[3]

ContractMode = Literal["read_write", "compat_read"]


class SchemaRegistryError(Exception):
    """Base error for evaluation schema-registry failures."""


class UnknownContractError(SchemaRegistryError):
    """Raised for an unknown contract ID or contract version."""


class SchemaFileMissingError(SchemaRegistryError):
    """Raised when the schema file for a known contract is absent."""


class SchemaFileInvalidError(SchemaRegistryError):
    """Raised when the schema file is not valid JSON."""


class SchemaHashMismatchError(SchemaRegistryError):
    """Raised when the schema file bytes do not match the reviewed hash."""


class SchemaMetaValidationError(SchemaRegistryError):
    """Raised when the schema is not a valid Draft 2020-12 schema."""


class ReadOnlyContractError(SchemaRegistryError):
    """Raised when a compatibility-read-only contract is selected for write."""


class SchemaContract(EvaluationStrictModel):
    """One reviewed binding of contract identity to a schema file."""

    contract_id: str
    contract_version: str
    relative_path: str
    expected_sha256: str
    mode: ContractMode


EVALUATION_SCHEMA_CONTRACTS: tuple[SchemaContract, ...] = (
    SchemaContract(
        contract_id="evaluation_case",
        contract_version="0.1.0",
        relative_path="schemas/evaluation_case.schema.json",
        expected_sha256="c148c75eeae22d94be0cf67089e600f97cf10c8b174f4c6591cea9e0a17de4e4",
        mode="read_write",
    ),
    SchemaContract(
        contract_id="evaluation_result",
        contract_version="0.2.0",
        relative_path="schemas/evaluation_result.v2.schema.json",
        expected_sha256="112413b962afc189894664b7116b7fa319ec7a367dc86ed6604f24c801f96e52",
        mode="read_write",
    ),
    SchemaContract(
        contract_id="universe_run_manifest",
        contract_version="0.2.0",
        relative_path="schemas/universe_run_manifest.v2.schema.json",
        expected_sha256="da54fe4079c2d0fa3f14266db52649add20b7762290360340bcceec58a9bc54b",
        mode="compat_read",
    ),
)


def _find_contract(contract_id: str, contract_version: str) -> SchemaContract:
    for contract in EVALUATION_SCHEMA_CONTRACTS:
        if contract.contract_id == contract_id and contract.contract_version == contract_version:
            return contract
    raise UnknownContractError(
        f"unknown evaluation schema contract {contract_id!r} version {contract_version!r}"
    )


def load_schema(
    contract_id: str,
    contract_version: str,
    *,
    purpose: Literal["read", "write"] = "read",
    repo_root: Path | None = None,
) -> Mapping[str, Any]:
    """Load, hash-verify, and meta-validate one registered schema.

    Returns an immutable mapping. Fails closed on unknown contract, write
    access to a compatibility-read-only contract, missing file, malformed
    JSON, file-hash mismatch, or Draft 2020-12 meta-validation failure.
    """
    contract = _find_contract(contract_id, contract_version)
    if purpose == "write" and contract.mode != "read_write":
        raise ReadOnlyContractError(
            f"contract {contract_id!r} version {contract_version!r} is "
            "compatibility-read-only and cannot be selected for writing"
        )
    root = Path(repo_root) if repo_root is not None else _REPO_ROOT
    path = root / contract.relative_path
    if not path.is_file():
        raise SchemaFileMissingError(f"schema file missing: {path}")
    raw = path.read_bytes()
    actual = sha256_bytes(raw)
    if actual != contract.expected_sha256:
        raise SchemaHashMismatchError(
            f"schema file {path} hash {actual} does not match reviewed "
            f"expected hash {contract.expected_sha256}"
        )
    try:
        schema = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchemaFileInvalidError(f"schema file {path} is not valid JSON: {exc}") from exc
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise SchemaMetaValidationError(
            f"schema file {path} failed Draft 2020-12 meta-validation: {exc.message}"
        ) from exc
    return MappingProxyType(schema)
