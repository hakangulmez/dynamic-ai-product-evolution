"""Evaluation-only static-schema registry and released-contract binding.

This registry is the evaluation package's activation boundary from the build
plan: it binds evaluation contract IDs and versions to exact schema paths
and reviewed expected file hashes, and it fails closed on any unknown
contract, missing file, malformed JSON, hash mismatch, meta-validation
failure, or write attempt against a compatibility-read-only contract.

Slice 14 adds ``RELEASED_EVALUATION_CONTRACTS``: the evaluation package's own
release binding of every governed contract identity — nine static-schema
bindings (path plus reviewed file-byte SHA-256) and thirty-four
generated-model identities (reviewed model-contract hash). It is a
release-review surface, never a runtime authority: ``load_schema``, the
module-local anchor tables, and every loader keep their existing authority
unchanged, and the regression suite enforces two-way agreement so drift
cannot pass silently.

The module never reads or modifies ``schemas/schema_version_manifest.json``,
never touches Phase 0 writer or validation selection, and never imports the
Phase 0 freeze/runner writer path. Every expected hash is a reviewed registry
constant written as a source literal, not a value derived from the files or
models being verified.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import Field, model_validator

from ..universe.io_utils import sha256_bytes
from .models import EvaluationStrictModel, _reject_explicit_null, _require_non_blank

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


_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"


def _is_safe_schema_reference(value: str) -> bool:
    if not value or value != value.strip():
        return False
    if value.startswith("/") or "\\" in value or "\x00" in value:
        return False
    if any(part in ("", ".", "..") for part in value.split("/")):
        return False
    return value.startswith("schemas/")


class ReleasedContractBinding(EvaluationStrictModel):
    """One reviewed released-contract identity (Slice 14 release binding).

    Deliberately a plain ``EvaluationStrictModel`` — never contract-stamped:
    the release binding is an in-code review surface, not a persisted governed
    artifact, and it must not mint a new generated-model identity.
    ``expected_sha256`` is the raw file-byte SHA-256 for a static-schema entry
    and the generated-model contract hash for a generated-model entry.
    ``relative_path`` is required for a static-schema entry and must be a safe
    ``schemas/`` reference; a generated-model entry must omit it entirely
    (explicit JSON null is rejected, never rewritten into absence).
    """

    contract_id: str
    contract_version: str
    kind: Literal["static_schema", "generated_model"]
    relative_path: str | None = None
    expected_sha256: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)

    @model_validator(mode="before")
    @classmethod
    def _no_explicit_null_path(cls, data: Any) -> Any:
        return _reject_explicit_null(data, ("relative_path",), "ReleasedContractBinding")

    @model_validator(mode="after")
    def _binding_invariants(self) -> "ReleasedContractBinding":
        _require_non_blank(self.contract_id, "contract_id")
        _require_non_blank(self.contract_version, "contract_version")
        if self.kind == "static_schema":
            if self.relative_path is None:
                raise ValueError("a static_schema entry requires relative_path")
            if not _is_safe_schema_reference(self.relative_path):
                raise ValueError(
                    "relative_path must be a non-blank safe 'schemas/' relative reference"
                )
        else:
            if "relative_path" in self.model_fields_set:
                raise ValueError(
                    "a generated_model entry must omit relative_path entirely"
                )
        return self


# The evaluation package's released contract set (Slice 14, build plan §14):
# every governed contract identity, sorted by (contract_id, contract_version).
# Reviewed source literals only — never derived from the files or models at
# import time. This tuple is a release-review surface; runtime authority stays
# with EVALUATION_SCHEMA_CONTRACTS, compat._HISTORICAL_ROUTES,
# validator_parameters._STAGE_STATIC_ANCHORS, and
# parent_observation_snapshot._ROLE_SCHEMA, whose agreement is test-enforced.
RELEASED_EVALUATION_CONTRACTS: tuple[ReleasedContractBinding, ...] = (
    ReleasedContractBinding(
        contract_id="assertion_comparison_metadata", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="6d1734afc9df3ae3d9fac1d4a5706a75e944a3b4afbbe785644afa251c67e3c4",
    ),
    ReleasedContractBinding(
        contract_id="assertion_outcome", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="4af3a9eb7c99e3e3ba088784b3395f4b6920fa1f8061f7bb1118af6bd2720bd6",
    ),
    ReleasedContractBinding(
        contract_id="assertion_transition", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="370581e355e5569c44e0a226e5e1a0a02d84db51fb9451c0b6a79761b9ee00b1",
    ),
    ReleasedContractBinding(
        contract_id="axis_taxonomy", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="d6072c16fe82b9e7e7f1f52db2d5f57fdc079ef473c3e8803b0fde2c3e356df3",
    ),
    ReleasedContractBinding(
        contract_id="capability_observation", contract_version="0.1.0",
        kind="static_schema",
        relative_path="schemas/capability_observation.schema.json",
        expected_sha256="4ade397f3383ff756a1aa2ba5f98bdb99f76c002d5cf049d7e8dcd7abf493733",
    ),
    ReleasedContractBinding(
        contract_id="case_ledger_entry", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="cea1a05ce83c847b3aac2163706b6d3b97ce31f1574972ad5b0dc1180c0421ce",
    ),
    ReleasedContractBinding(
        contract_id="case_set_manifest", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="0b464d786d5a8addb1305c21c2d93b01c834e8f398fd3b12be30d1fc49083bb5",
    ),
    ReleasedContractBinding(
        contract_id="company_universe_classification", contract_version="0.1.0",
        kind="static_schema",
        relative_path="schemas/company_universe_classification.schema.json",
        expected_sha256="1d47a80ee670f927e55d6af50550b1584aab022389471739a055a9e550552a22",
    ),
    ReleasedContractBinding(
        contract_id="comparison_manifest", contract_version="0.2.0",
        kind="generated_model",
        expected_sha256="6a1253b72664bff73e872d1230fb3d52772a438f55915406010e105b4f5d29a5",
    ),
    ReleasedContractBinding(
        contract_id="evaluation_case", contract_version="0.1.0",
        kind="static_schema",
        relative_path="schemas/evaluation_case.schema.json",
        expected_sha256="c148c75eeae22d94be0cf67089e600f97cf10c8b174f4c6591cea9e0a17de4e4",
    ),
    ReleasedContractBinding(
        contract_id="evaluation_output_manifest", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="2a58607da0a0d457bee99d6760d7ccb93a6e72ca2e255a82b7cb75e27f956e3e",
    ),
    ReleasedContractBinding(
        contract_id="evaluation_output_manifest", contract_version="0.2.0",
        kind="generated_model",
        expected_sha256="dc4bac543ee42a786d6f2c8395ca4401761ce1abea356e4006b7bdb6ae4eb850",
    ),
    ReleasedContractBinding(
        contract_id="evaluation_result", contract_version="0.1.0",
        kind="static_schema",
        relative_path="schemas/evaluation_result.schema.json",
        expected_sha256="2fae7b2305c041ed9062d272929bb67589aaf4f5ea0d7503fe4b56b87a480453",
    ),
    ReleasedContractBinding(
        contract_id="evaluation_result", contract_version="0.2.0",
        kind="static_schema",
        relative_path="schemas/evaluation_result.v2.schema.json",
        expected_sha256="112413b962afc189894664b7116b7fa319ec7a367dc86ed6604f24c801f96e52",
    ),
    ReleasedContractBinding(
        contract_id="evaluation_run_manifest", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="7f8909d8e7059952c933c8e30f43044178b3f8a21d4baaa77bfb5c786b38d6ee",
    ),
    ReleasedContractBinding(
        contract_id="evaluation_run_manifest", contract_version="0.2.0",
        kind="generated_model",
        expected_sha256="6918e96c0f9d2066e89eaf6a699c00b36e1e52e5b5c74ec0e926533eacaf84d6",
    ),
    ReleasedContractBinding(
        contract_id="evaluation_semantic_adapter_registry", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="757766e9f965a18cee4d86ff3490ba5f66076f75993339fc52b9ff72b3812c5c",
    ),
    ReleasedContractBinding(
        contract_id="evaluation_stage_profile_registry", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="cbd567cb0367cabe5f680957a8da29d9018ccd50512c91e0f9c393de2c7ee4dd",
    ),
    ReleasedContractBinding(
        contract_id="finding_disposition", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="1c08efdbd36682acf535cc688ae5c73e902e1659f30814b6a5bee46b2c9d873e",
    ),
    ReleasedContractBinding(
        contract_id="gold_assertion_set", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="48bb5f185072ed004aa4fcfda30408ff710406ac42bc5ea611d3f5a1fb118cfe",
    ),
    ReleasedContractBinding(
        contract_id="membership_event", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="f7e301d2a34cf2e180884d8fa0bfb6cf19a14c8154521713ca97d9a7f47fff94",
    ),
    ReleasedContractBinding(
        contract_id="metric_input_snapshot", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="1a208a74442b57b8519eb8e7cb923d235c260320c23f6cf65deeb133e64b8756",
    ),
    ReleasedContractBinding(
        contract_id="metric_report", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="d9e3f6d7399af628b38754758a7cb580e57955ad695ee7d92fb56c67c4ceac39",
    ),
    ReleasedContractBinding(
        contract_id="metric_report", contract_version="0.2.0",
        kind="generated_model",
        expected_sha256="68cd901cec08e2d4c5b1df4dfd4b785bffa0b9675140fa1304ae2aec5006c0a4",
    ),
    ReleasedContractBinding(
        contract_id="observation_target_binding", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="f3ec0e0f2db9185333c667a6d7a52bf64a3b2a21b65bf1cbd90fa582ed67acd2",
    ),
    ReleasedContractBinding(
        contract_id="observation_target_binding", contract_version="0.2.0",
        kind="generated_model",
        expected_sha256="658f2050a5ecf768ee8ee7384a8892bbe52209b122f4ca15f78d34ad31b924a1",
    ),
    ReleasedContractBinding(
        contract_id="observation_target_resolution_decision_set",
        contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="b445b113f3214beff79a6a89b12d69c56717c8e83b93756475ada6a037b129e6",
    ),
    ReleasedContractBinding(
        contract_id="parent_observation_snapshot", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="70b197b6154f87d4bcdb37e92e3e354b7ed5714987cb067149abfbfa37f606ea",
    ),
    ReleasedContractBinding(
        contract_id="parsed_prediction_content", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="ffeae7ab54fa03948f4498a3ceb5a634b17444791fd91f94a57c086afedbda3e",
    ),
    ReleasedContractBinding(
        contract_id="prediction_artifact_manifest", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="4b164aea18fc99f9518854aca0fb98587eb71d81c972a477d48cb815ddc0dbe4",
    ),
    ReleasedContractBinding(
        contract_id="prediction_envelope", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="5ac06fb78220c3f7369863cda32ee914a1d33ff01020fc01e57d9bd0ccbb18a3",
    ),
    ReleasedContractBinding(
        contract_id="product_observation", contract_version="0.1.0",
        kind="static_schema",
        relative_path="schemas/product_observation.schema.json",
        expected_sha256="2d2adcb0b24313c58ed27c51708e4e680e0d4c5abe099ae02788217c45cf1eae",
    ),
    ReleasedContractBinding(
        contract_id="source_passage_snapshot_manifest", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="c169be58c6df0370e5f51f276a528f452252e9796d19fb5e3a905cd34a3c21a5",
    ),
    ReleasedContractBinding(
        contract_id="stage_metric_evidence_set", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="2b2fe5d7e46f0ca0cbfc8e0acf98e9c2e8f57abb381b8f2ce5743416fc4574b1",
    ),
    ReleasedContractBinding(
        contract_id="task_observation", contract_version="0.1.0",
        kind="static_schema",
        relative_path="schemas/task_observation.schema.json",
        expected_sha256="b135ab828a3b710f1c63f6a8bf473caa6e29c3a63a5330cb203b470f772e3b03",
    ),
    ReleasedContractBinding(
        contract_id="universe_run_manifest", contract_version="0.1.0",
        kind="static_schema",
        relative_path="schemas/universe_run_manifest.schema.json",
        expected_sha256="a28d920f06bfe3fb90ec13ad7fb69a9d6e2b30e3f711b326c5511609cc507c1b",
    ),
    ReleasedContractBinding(
        contract_id="universe_run_manifest", contract_version="0.2.0",
        kind="static_schema",
        relative_path="schemas/universe_run_manifest.v2.schema.json",
        expected_sha256="da54fe4079c2d0fa3f14266db52649add20b7762290360340bcceec58a9bc54b",
    ),
    ReleasedContractBinding(
        contract_id="universe_screen_output", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="97703d752d1bdf6216a98c14923ba1c145e1c24aa70c2c8dd24e9160a6949c50",
    ),
    ReleasedContractBinding(
        contract_id="validation_artifact_snapshot_set", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="51643160bcc7a98b7dd7279c6109d51292d1cd7d3022420271010e3275e6d1a1",
    ),
    ReleasedContractBinding(
        contract_id="validator_bundle_artifact", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="474651b5eb59411dbd13e5a5a3ac3749d618e4dc5e8f39470d698c953524bc5c",
    ),
    ReleasedContractBinding(
        contract_id="validator_finding", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="96f63fee300d363a662f4f956bacccdca596acfb0f22bf7039aa1335b6d61292",
    ),
    ReleasedContractBinding(
        contract_id="validator_rule_parameters", contract_version="0.1.0",
        kind="generated_model",
        expected_sha256="f9c20ba936e1c0541c721ac6c3c34bec183b4b360dfa177516c57b0bd0945822",
    ),
    ReleasedContractBinding(
        contract_id="validator_rule_parameters", contract_version="0.2.0",
        kind="generated_model",
        expected_sha256="a15556e5935c3ba26a966aaac18f84267a3b3dbedca43c7a9bc360e49e00df08",
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
