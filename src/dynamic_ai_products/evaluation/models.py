"""Shared model foundations for the Phase 1 evaluation harness (Slice 1A).

Only the strict/frozen base and the minimal contract-metadata model required
by `contracts.py` and `schemas.py` live here. The broader persisted-artifact
models (evaluation cases, run manifests, findings, and so on) arrive in later
slices with their own reviewed field maps.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# Non-empty, no leading or trailing whitespace; internal spaces stay legal.
# Values are validated as-is and never stripped, lowercased, or rewritten.
_IDENTITY_PATTERN = r"^\S(.*\S)?$"
# Canonical lowercase SHA-256 hex digest; uppercase is rejected, not folded.
_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"


class EvaluationStrictModel(BaseModel):
    """Strict, immutable base for all evaluation-harness models.

    Unknown fields are rejected and instances are frozen, mirroring the
    `universe.models.StrictModel` pattern with the immutability required by
    the evaluation-harness build plan.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class ContractMetadata(EvaluationStrictModel):
    """Identity and hash of one versioned artifact contract."""

    contract_id: str = Field(min_length=1, pattern=_IDENTITY_PATTERN)
    contract_version: str = Field(min_length=1, pattern=_IDENTITY_PATTERN)
    contract_hash: str = Field(min_length=64, max_length=64, pattern=_SHA256_HEX_PATTERN)
