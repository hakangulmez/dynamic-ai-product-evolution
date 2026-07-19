"""Phase 1 evaluation-harness package (Slice 1A scaffold).

Slice 1A provides the strict/frozen model foundation, deterministic
canonical contract hashing, and the evaluation-only static-schema registry.
Importing this package performs no filesystem reads and no schema
validation; all loading is explicit.
"""

from .contracts import (
    ContractError,
    ContractHashMismatchError,
    InvalidContractIdentityError,
    build_contract_envelope,
    canonical_contract_bytes,
    contract_hash,
    model_contract_hash,
    runtime_contract_provenance,
    verify_contract_hash,
)
from .models import (
    AssertionOutcome,
    AssertionSpec,
    CaseMembership,
    CaseSetManifest,
    ContractMetadata,
    EvaluationCase,
    EvaluationResultV2,
    EvaluationRunManifest,
    EvaluationStrictModel,
    FindingDisposition,
    MembershipEvent,
    PredictionEnvelope,
    ValidatorFinding,
)
from .schemas import (
    EVALUATION_SCHEMA_CONTRACTS,
    ReadOnlyContractError,
    SchemaContract,
    SchemaFileInvalidError,
    SchemaFileMissingError,
    SchemaHashMismatchError,
    SchemaMetaValidationError,
    SchemaRegistryError,
    UnknownContractError,
    load_schema,
)

__all__ = [
    "AssertionOutcome",
    "AssertionSpec",
    "CaseMembership",
    "CaseSetManifest",
    "ContractError",
    "ContractHashMismatchError",
    "ContractMetadata",
    "EVALUATION_SCHEMA_CONTRACTS",
    "EvaluationCase",
    "EvaluationResultV2",
    "EvaluationRunManifest",
    "EvaluationStrictModel",
    "FindingDisposition",
    "MembershipEvent",
    "PredictionEnvelope",
    "ValidatorFinding",
    "InvalidContractIdentityError",
    "ReadOnlyContractError",
    "SchemaContract",
    "SchemaFileInvalidError",
    "SchemaFileMissingError",
    "SchemaHashMismatchError",
    "SchemaMetaValidationError",
    "SchemaRegistryError",
    "UnknownContractError",
    "build_contract_envelope",
    "canonical_contract_bytes",
    "contract_hash",
    "load_schema",
    "model_contract_hash",
    "runtime_contract_provenance",
    "verify_contract_hash",
]
