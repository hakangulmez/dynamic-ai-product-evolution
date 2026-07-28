"""Canonical run manifests and the transform/provenance ledger (ADR-031).

Every manifest records the SPEC-002/003/006 run fields. ``prompt_hash`` and
``model_route`` are asserted null: no prompt and no model participate in this
stage block.
"""

from __future__ import annotations

from typing import Any

from .errors import IngestionError
from .publication import PUBLICATION_MODEL

__all__ = [
    "build_ingestion_preflight_manifest",
    "build_sec_discovery_manifest",
]

SPEC_VERSIONS = {
    "stage_01": "SPEC-002",
    "stage_02": "SPEC-004",
    "stage_03": ["SPEC-005", "SPEC-003"],
    "stage_04": "SPEC-006",
}


def _require_injected(code_commit: str, run_created_at: str) -> None:
    for name, value in (("code_commit", code_commit), ("run_created_at", run_created_at)):
        if not isinstance(value, str) or not value.strip():
            raise IngestionError(
                f"{name} must be injected by the caller; this package reads no "
                "clock and no VCS",
                reason_code="run_identity_invalid",
            )


def build_sec_discovery_manifest(
    *,
    code_commit: str,
    run_created_at: str,
    company_id: str,
    observation_cutoff_date: str,
    candidate_count: int,
    source_manifest_hash: str,
    exclusions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    _require_injected(code_commit, run_created_at)
    return {
        "contract": "sec_source_candidates@0.1.0",
        "schema_version": "0.1.0",
        "spec_version": SPEC_VERSIONS["stage_01"],
        "code_commit": code_commit,
        "run_created_at": run_created_at,
        "company_id": company_id,
        "observation_cutoff_date": observation_cutoff_date,
        "candidate_count": candidate_count,
        "source_manifest_hash": source_manifest_hash,
        "retry_count": 0,
        "prompt_hash": None,
        "model_route": None,
        "exclusions": list(exclusions or []),
    }


def build_ingestion_preflight_manifest(
    *,
    run_id: str,
    code_commit: str,
    run_created_at: str,
    company_id: str,
    observation_cutoff_date: str,
    artifact_bindings: dict[str, str],
    parquet_writer_metadata: dict[str, Any],
    transform_ledger: dict[str, Any],
    collection_receipt_sha256: str,
    packet_sha256: str,
    verdict: str,
) -> dict[str, Any]:
    """The run-root audit artifact binding every Stage 01-04 output."""
    _require_injected(code_commit, run_created_at)
    if verdict not in {"ready_for_extraction", "stopped"}:
        raise IngestionError(
            f"unknown preflight verdict: {verdict}",
            reason_code="verdict_invalid",
        )
    return {
        "contract": "ingestion_preflight_manifest@0.1.0",
        "schema_version": "0.1.0",
        "spec_versions": SPEC_VERSIONS,
        "run_id": run_id,
        "code_commit": code_commit,
        "run_created_at": run_created_at,
        "company_id": company_id,
        "observation_cutoff_date": observation_cutoff_date,
        "publication_model": PUBLICATION_MODEL,
        "artifact_bindings": dict(sorted(artifact_bindings.items())),
        "parquet_writer_metadata": parquet_writer_metadata,
        "transform_ledger": transform_ledger,
        "collection_receipt_sha256": collection_receipt_sha256,
        "packet_sha256": packet_sha256,
        "retry_count": 0,
        "prompt_hash": None,
        "model_route": None,
        "verdict": verdict,
    }
