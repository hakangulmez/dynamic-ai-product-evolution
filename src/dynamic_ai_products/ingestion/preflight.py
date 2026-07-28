"""Stage 01-04 ingestion preflight orchestration (ADR-031).

Builds every artifact inside a run-scoped staging root and publishes the whole
run with one atomic rename. Only a successfully published
``ingestion_preflight_manifest`` is authoritative.

Fail-closed outcomes report and never write: on a stop, no run root is
published, so no authoritative manifest exists. Extraction and harness
reachability is structural — this module imports no Stage 05 module, no
provider client, and no harness entry point.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .adoption import (
    adopt_sec_snapshots,
    build_sec_candidates,
    build_source_document,
    verify_raw_bytes,
)
from .errors import IngestionError
from .family_coverage import REQUIRED_FAMILIES, build_source_family_coverage
from .manifests import build_ingestion_preflight_manifest, build_sec_discovery_manifest
from .normalize import NORMALIZER_VERSION, build_passages
from .parquet_io import table_bytes, writer_metadata
from .publication import (
    RUN_ROOT_TEMPLATES,
    canonical_json_bytes,
    canonical_jsonl_bytes,
    derive_run_id,
    materialize_template,
    open_staging_root,
    publish_run_root,
    stage_artifact,
)

__all__ = ["PreflightResult", "run_ingestion_preflight", "zero_evidence_stop_report"]

_RUN_ROOT_PREFIX = "data/runs/{run_id}/"


class PreflightResult:
    """Outcome of a preflight run: a published run root or a typed stop."""

    def __init__(
        self,
        *,
        run_id: str,
        verdict: str,
        run_root: Path | None,
        artifact_bindings: dict[str, str],
        manifest: dict[str, Any],
    ) -> None:
        self.run_id = run_id
        self.verdict = verdict
        self.run_root = run_root
        self.artifact_bindings = artifact_bindings
        self.manifest = manifest


def zero_evidence_stop_report(
    *, run_id: str, company_id: str, reason: str
) -> dict[str, Any]:
    """The fail-closed no-evidence outcome: report, never write."""
    if not isinstance(reason, str) or not reason.strip():
        raise IngestionError(
            "a zero-evidence stop requires a non-blank reason",
            reason_code="stop_reason_blank",
        )
    return {
        "contract": "ingestion_preflight_stop@0.1.0",
        "run_id": run_id,
        "company_id": company_id,
        "verdict": "stopped",
        "reason_code": "zero_evidence_stop",
        "stop_reason": reason,
        "published": False,
        "authoritative_manifest_written": False,
    }


def _relative(template_key: str, run_id: str) -> str:
    """Run-root-relative path for a staged artifact."""
    materialized = materialize_template(RUN_ROOT_TEMPLATES[template_key], run_id)
    prefix = _RUN_ROOT_PREFIX.replace("{run_id}", run_id)
    if not materialized.startswith(prefix):
        raise IngestionError(
            f"template {template_key} does not resolve under the run root",
            reason_code="template_invalid",
        )
    return materialized[len(prefix) :]


def run_ingestion_preflight(
    *,
    runs_root: str | Path,
    raw_directory: str | Path,
    receipt: dict[str, Any],
    receipt_sha256: str,
    packet_sha256: str,
    company_id: str,
    observation_cutoff_date: str,
    primary_document: str,
    span_start_offset: int,
    span_end_offset: int,
    code_commit: str,
    run_created_at: str,
) -> PreflightResult:
    """Execute Stage 01-04 and publish one immutable run root.

    Every input is injected. This function reads no network, no clock, and no
    VCS, and never writes outside ``runs_root``.
    """
    run_id = derive_run_id(
        code_commit=code_commit,
        run_created_at=run_created_at,
        company_id=company_id,
        observation_cutoff_date=observation_cutoff_date,
        collection_receipt_sha256=receipt_sha256,
        packet_sha256=packet_sha256,
        normalizer_version=NORMALIZER_VERSION,
    )

    # --- Validation before any staging directory exists ---------------------
    verified = verify_raw_bytes(raw_directory, receipt)
    candidates = build_sec_candidates(
        company_id=company_id,
        receipt=receipt,
        observation_cutoff_date=observation_cutoff_date,
    )
    document = build_source_document(
        company_id=company_id,
        receipt=receipt,
        observation_cutoff_date=observation_cutoff_date,
        primary_document=primary_document,
    )
    raw_primary = verified.get("primary_document")
    if raw_primary is None:
        raise IngestionError(
            "the receipt carries no primary document",
            reason_code="receipt_unavailable",
        )

    passages, ledger = build_passages(
        raw_primary,
        source_id=document["source_id"],
        start_offset=span_start_offset,
        end_offset=span_end_offset,
    )
    if not passages:
        raise IngestionError(
            "normalization produced no admissible passages",
            reason_code="zero_evidence_stop",
            stop_reason=(
                "the anchor-bounded span yielded zero passages; no artifact is "
                "written and no run root is published"
            ),
        )

    coverage = build_source_family_coverage(
        company_id=company_id,
        observation_cutoff_date=observation_cutoff_date,
        required_states={
            family: (
                "available_and_retrieved" if family == "sec_edgar" else "not_attempted"
            )
            for family in REQUIRED_FAMILIES
        },
    )
    snapshots = adopt_sec_snapshots(
        company_id=company_id,
        receipt=receipt,
        receipt_sha256=receipt_sha256,
        raw_directory=raw_directory,
    )

    candidate_bytes = table_bytes("sec_source_candidates", candidates)
    document_bytes = table_bytes("normalized_documents", [document])
    passage_bytes = table_bytes("normalized_passages", passages)

    # --- Staging, then one atomic publication -------------------------------
    staging = open_staging_root(runs_root, run_id)
    bindings: dict[str, str] = {}

    bindings["sec_source_candidates"] = stage_artifact(
        staging, _relative("sec_source_candidates", run_id), candidate_bytes
    )
    bindings["normalized_documents"] = stage_artifact(
        staging, _relative("normalized_documents", run_id), document_bytes
    )
    bindings["normalized_passages"] = stage_artifact(
        staging, _relative("normalized_passages", run_id), passage_bytes
    )
    bindings["source_family_coverage"] = stage_artifact(
        staging,
        _relative("source_family_coverage", run_id),
        canonical_json_bytes(coverage),
    )
    bindings["snapshot_manifest"] = stage_artifact(
        staging, _relative("snapshot_manifest", run_id), canonical_jsonl_bytes(snapshots)
    )
    discovery_manifest = build_sec_discovery_manifest(
        code_commit=code_commit,
        run_created_at=run_created_at,
        company_id=company_id,
        observation_cutoff_date=observation_cutoff_date,
        candidate_count=len(candidates),
        source_manifest_hash=receipt_sha256,
    )
    bindings["sec_discovery_manifest"] = stage_artifact(
        staging,
        _relative("sec_discovery_manifest", run_id),
        canonical_json_bytes(discovery_manifest),
    )

    parquet_metadata = {
        "sec_source_candidates": writer_metadata(
            artifact="sec_source_candidates",
            row_count=len(candidates),
            sha256_hex=bindings["sec_source_candidates"],
        ),
        "normalized_documents": writer_metadata(
            artifact="normalized_documents",
            row_count=1,
            sha256_hex=bindings["normalized_documents"],
        ),
        "normalized_passages": writer_metadata(
            artifact="normalized_passages",
            row_count=len(passages),
            sha256_hex=bindings["normalized_passages"],
        ),
    }

    manifest = build_ingestion_preflight_manifest(
        run_id=run_id,
        code_commit=code_commit,
        run_created_at=run_created_at,
        company_id=company_id,
        observation_cutoff_date=observation_cutoff_date,
        artifact_bindings=bindings,
        parquet_writer_metadata=parquet_metadata,
        transform_ledger=ledger,
        collection_receipt_sha256=receipt_sha256,
        packet_sha256=packet_sha256,
        verdict="ready_for_extraction",
    )
    manifest_hash = stage_artifact(
        staging,
        _relative("ingestion_preflight_manifest", run_id),
        canonical_json_bytes(manifest),
    )
    bindings["ingestion_preflight_manifest"] = manifest_hash

    run_root = publish_run_root(runs_root, run_id)
    return PreflightResult(
        run_id=run_id,
        verdict="ready_for_extraction",
        run_root=run_root,
        artifact_bindings=bindings,
        manifest=manifest,
    )
