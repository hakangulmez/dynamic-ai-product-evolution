"""Provider-run provenance and the non-run record (ADR-033).

``extraction_run@0.1.0`` is adopted **unchanged**: it is strict with fifteen
properties and carries no provider-client-contract field. The client contract
is bound instead as a byte-referenced entry in the prediction manifest's
``source_artifacts``.

A pre-provider non-run writes **no** ``extraction_run``: that contract requires
``prompt_hash`` and ``source_manifest_hash`` and denotes a provider run, so
emitting one with a stopped status would assert a run that never began.
"""

from __future__ import annotations

import re
from typing import Any

from .errors import ExtractionError
from .raw_artifacts import canonical_json_bytes

__all__ = [
    "EXTRACTION_RUN_PROPERTIES",
    "STAGE_OUTPUT_SCHEMA",
    "STAGE_OUTPUT_SCHEMA_SHA256",
    "resolve_stage_schema_hash",
    "NON_RUN_CONTRACT",
    "NON_RUN_REASONS",
    "build_extraction_run",
    "build_non_run_record",
    "record_bytes",
]

NON_RUN_CONTRACT = "extraction_non_run_record@0.1.0"

NON_RUN_REASONS: tuple[str, ...] = (
    "zero_admissible_passages",
    "all_passages_temporally_invalid",
    "input_packet_empty_after_filters",
    "corpus_binding_unverified",
    "source_snapshot_unavailable",
)

# The released contract's exact property set. Nothing outside it may be emitted.
EXTRACTION_RUN_PROPERTIES: frozenset[str] = frozenset(
    {
        "run_id",
        "stage",
        "started_at",
        "completed_at",
        "status",
        "code_commit",
        "spec_version",
        "schema_hash",
        "prompt_hash",
        "source_manifest_hash",
        "model_provider",
        "model_name",
        "model_parameters",
        "fallbacks",
        "error_count",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# The authoritative output contract per stage: the released observation schema
# each stage's extracted records must validate against. schema_hash is the
# SHA-256 over that file's exact bytes, verified against the closed pin before
# extraction_run is built. Measured read-only from the committed files.
STAGE_OUTPUT_SCHEMA = {
    "product_extraction": "product_observation.schema.json",
    "capability_extraction": "capability_observation.schema.json",
    "task_extraction": "task_observation.schema.json",
}
STAGE_OUTPUT_SCHEMA_SHA256 = {
    "product_extraction": "2d2adcb0b24313c58ed27c51708e4e680e0d4c5abe099ae02788217c45cf1eae",
    "capability_extraction": "4ade397f3383ff756a1aa2ba5f98bdb99f76c002d5cf049d7e8dcd7abf493733",
    "task_extraction": "b135ab828a3b710f1c63f6a8bf473caa6e29c3a63a5330cb203b470f772e3b03",
}


def resolve_stage_schema_hash(stage: str, schema_root: str = "schemas") -> str:
    """Read the stage's released schema and verify it against the closed pin."""
    from pathlib import Path as _Path

    from .raw_artifacts import sha256_bytes

    if stage not in STAGE_OUTPUT_SCHEMA:
        raise ExtractionError(
            f"unknown extraction stage: {stage!r}", reason_code="packet_stage_invalid"
        )
    target = _Path(schema_root) / STAGE_OUTPUT_SCHEMA[stage]
    try:
        observed = sha256_bytes(target.read_bytes())
    except OSError as exc:
        raise ExtractionError(
            f"released output schema is unreadable: {target}",
            reason_code="schema_pin_mismatch",
        ) from exc
    expected = STAGE_OUTPUT_SCHEMA_SHA256[stage]
    if observed != expected:
        raise ExtractionError(
            f"released output schema does not match its pin: {target}",
            reason_code="schema_pin_mismatch",
            detail=f"expected {expected}, observed {observed}",
        )
    return observed


SPEC_VERSION_FOR_STAGE = {
    "product_extraction": "SPEC-008",
    "capability_extraction": "SPEC-009",
    "task_extraction": "SPEC-010",
}


def _require_injected(code_commit: str, run_created_at: str) -> None:
    for name, value in (("code_commit", code_commit), ("run_created_at", run_created_at)):
        if not isinstance(value, str) or not value.strip():
            raise ExtractionError(
                f"{name} must be injected by the caller; this package reads no clock "
                "and no VCS",
                reason_code="run_identity_invalid",
            )


def build_extraction_run(
    *,
    run_id: str,
    stage: str,
    started_at: str,
    completed_at: str,
    status: str,
    code_commit: str,
    schema_hash: str,
    prompt_hash: str,
    source_manifest_hash: str,
    model_provider: str | None = None,
    model_name: str | None = None,
    model_parameters: dict[str, Any] | None = None,
    fallbacks: list[Any] | None = None,
    error_count: int = 0,
) -> dict[str, Any]:
    """Build an ``extraction_run@0.1.0`` record without widening the contract."""
    _require_injected(code_commit, started_at)
    if stage not in SPEC_VERSION_FOR_STAGE:
        raise ExtractionError(
            f"unknown extraction stage: {stage!r}", reason_code="packet_stage_invalid"
        )
    for label, value in (
        ("schema_hash", schema_hash),
        ("prompt_hash", prompt_hash),
        ("source_manifest_hash", source_manifest_hash),
    ):
        if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
            raise ExtractionError(
                f"{label} must be 64 lowercase hex characters", reason_code="pin_invalid"
            )
    record = {
        "run_id": run_id,
        "stage": stage,
        "started_at": started_at,
        "completed_at": completed_at,
        "status": status,
        "code_commit": code_commit,
        "spec_version": SPEC_VERSION_FOR_STAGE[stage],
        "schema_hash": schema_hash,
        "prompt_hash": prompt_hash,
        "source_manifest_hash": source_manifest_hash,
        "model_provider": model_provider,
        "model_name": model_name,
        "model_parameters": dict(model_parameters or {}),
        "fallbacks": list(fallbacks or []),
        "error_count": int(error_count),
    }
    extra = sorted(set(record) - EXTRACTION_RUN_PROPERTIES)
    if extra:
        raise ExtractionError(
            f"extraction_run@0.1.0 may not be widened: {extra}",
            reason_code="contract_widened",
        )
    return record


def build_non_run_record(
    *,
    extraction_run_id: str,
    stage: str,
    company_id: str,
    observation_cutoff_date: str,
    code_commit: str,
    run_created_at: str,
    input_packet_reference: str,
    input_packet_sha256: str,
    coverage_artifact_reference: str,
    coverage_artifact_sha256: str,
    reason_code: str,
    filter_ledger: dict[str, Any],
) -> dict[str, Any]:
    """The sole newly published output on a pre-provider non-run route."""
    _require_injected(code_commit, run_created_at)
    if reason_code not in NON_RUN_REASONS:
        raise ExtractionError(
            f"undeclared non-run reason: {reason_code!r}",
            reason_code="non_run_reason_unknown",
        )
    for label, value in (
        ("input_packet_sha256", input_packet_sha256),
        ("coverage_artifact_sha256", coverage_artifact_sha256),
    ):
        if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
            raise ExtractionError(
                f"{label} must be 64 lowercase hex characters", reason_code="pin_invalid"
            )
    return {
        "contract": NON_RUN_CONTRACT,
        "schema_version": "0.1.0",
        "extraction_run_id": extraction_run_id,
        "stage": stage,
        "company_id": company_id,
        "observation_cutoff_date": observation_cutoff_date,
        "code_commit": code_commit,
        "run_created_at": run_created_at,
        "input_packet_reference": input_packet_reference,
        "input_packet_sha256": input_packet_sha256,
        "coverage_artifact_reference": coverage_artifact_reference,
        "coverage_artifact_sha256": coverage_artifact_sha256,
        "reason_code": reason_code,
        "filter_ledger": dict(filter_ledger),
        "provider_called": False,
        "harness_run": False,
    }


def record_bytes(record: dict[str, Any]) -> bytes:
    return canonical_json_bytes(record)
