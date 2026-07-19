"""Deterministic canonical contract hashing (Slice 1A).

The contract hash of an artifact contract is the SHA-256 of the canonical
UTF-8 JSON serialization of an envelope containing the stable contract ID,
the explicit contract version, and the generated JSON Schema. The canonical
form uses recursively sorted object keys, compact separators, and no
platform-dependent formatting, so the hash is independent of dictionary
insertion order and pretty-printing. Phase 0 hash helpers are reused for the
digest and are not modified.
"""

from __future__ import annotations

import json
from importlib.metadata import version as _dist_version
from platform import python_version
from typing import Any, Mapping

from pydantic import BaseModel

from ..universe.io_utils import sha256_bytes


class ContractError(Exception):
    """Base error for contract-identity and contract-hash failures."""


class InvalidContractIdentityError(ContractError):
    """Raised when a contract ID or contract version is empty or blank."""


class ContractHashMismatchError(ContractError):
    """Raised when a declared contract hash does not match the computed one."""


def _require_identity(contract_id: str, contract_version: str) -> None:
    if not isinstance(contract_id, str) or not contract_id.strip():
        raise InvalidContractIdentityError("contract_id must be a non-empty string")
    if not isinstance(contract_version, str) or not contract_version.strip():
        raise InvalidContractIdentityError("contract_version must be a non-empty string")


def build_contract_envelope(
    contract_id: str,
    contract_version: str,
    json_schema: Mapping[str, Any],
) -> dict[str, Any]:
    """Assemble the hash envelope for one contract."""
    _require_identity(contract_id, contract_version)
    return {
        "contract_id": contract_id,
        "contract_version": contract_version,
        "json_schema": dict(json_schema),
    }


def canonical_contract_bytes(envelope: Mapping[str, Any]) -> bytes:
    """Serialize an envelope as canonical UTF-8 JSON bytes."""
    return json.dumps(
        envelope,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def contract_hash(
    contract_id: str,
    contract_version: str,
    json_schema: Mapping[str, Any],
) -> str:
    """Compute the deterministic SHA-256 contract hash for one contract."""
    envelope = build_contract_envelope(contract_id, contract_version, json_schema)
    return sha256_bytes(canonical_contract_bytes(envelope))


def model_contract_hash(
    model_cls: type[BaseModel],
    contract_id: str,
    contract_version: str,
) -> str:
    """Compute the contract hash of a Pydantic model's generated schema."""
    return contract_hash(contract_id, contract_version, model_cls.model_json_schema())


def verify_contract_hash(
    declared_hash: str,
    contract_id: str,
    contract_version: str,
    json_schema: Mapping[str, Any],
) -> None:
    """Fail closed when the declared hash does not match the computed hash."""
    computed = contract_hash(contract_id, contract_version, json_schema)
    if declared_hash != computed:
        raise ContractHashMismatchError(
            f"declared contract hash {declared_hash!r} does not match computed "
            f"{computed!r} for {contract_id!r} version {contract_version!r}"
        )


def runtime_contract_provenance() -> dict[str, str]:
    """Runtime provenance for diagnosing schema-generation drift."""
    return {
        "pydantic_version": _dist_version("pydantic"),
        "python_version": python_version(),
    }
