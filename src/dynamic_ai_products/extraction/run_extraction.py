"""Stage-dispatched extraction orchestration (ADR-033, E-A).

Builds and persists the stage input packet, then either takes the non-run route
(zero admissible passages) or drives an **injected** provider and emits the
prediction artifacts. No provider is constructed here: one must be supplied.

Non-run route publishes exactly two files — the packet as an upstream input
artifact and the non-run record as the sole newly published output — with no
raw prediction, envelope, prediction manifest, ``extraction_run``, or harness
run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import ExtractionError
from .input_packet import build_extraction_input_packet, packet_bytes
from .manifests import (
    build_extraction_run,
    build_non_run_record,
    record_bytes,
    resolve_stage_schema_hash,
)
from .prediction_manifest import build_prediction_artifact_manifest, manifest_bytes
from .provider_adapter import ProviderRequest, require_provider
from .prompts import load_prompt, prompts_for_stage
from .raw_artifacts import (
    build_prediction_envelope,
    canonical_jsonl_bytes,
    write_artifact,
    write_raw_prediction,
)

__all__ = ["ExtractionOutcome", "run_extraction_stage"]

PACKET_REFERENCE = "inputs/extraction_input_packet.json"
NON_RUN_REFERENCE = "manifests/extraction_non_run_record.json"
RAW_REFERENCE = "predictions/raw_prediction.json"
ENVELOPES_REFERENCE = "predictions/prediction_envelopes.jsonl"
PREDICTION_MANIFEST_REFERENCE = "predictions/prediction_run_manifest.json"
EXTRACTION_RUN_REFERENCE = "manifests/extraction_run.json"
PROMPT_REFERENCE = "inputs/resolved_prompt.md"


class ExtractionOutcome:
    """Either a published provider run or a published non-run."""

    def __init__(
        self,
        *,
        verdict: str,
        run_root: Path,
        packet: dict[str, Any],
        packet_sha256: str,
        artifacts: dict[str, str],
    ) -> None:
        self.verdict = verdict
        self.run_root = run_root
        self.packet = packet
        self.packet_sha256 = packet_sha256
        self.artifacts = artifacts


def run_extraction_stage(
    *,
    run_root: str | Path,
    repo_root: str | Path,
    stage: str,
    company_id: str,
    observation_cutoff_date: str,
    passages: list[dict[str, Any]],
    document_publication_dates: dict[str, str],
    coverage_artifact: dict[str, str],
    source_snapshot_manifest: dict[str, str],
    code_commit: str,
    run_created_at: str,
    extraction_run_id: str,
    prediction_run_id: str,
    schema_root: str = "schemas",
    provider: object = None,
    provider_client_contract: dict[str, str] | None = None,
    artifact_root: str | Path | None = None,
    snapshot_a_pin: dict[str, str] | None = None,
    snapshot_b_pin: dict[str, str] | None = None,
    product_decision_set_pin: dict[str, str] | None = None,
    capability_decision_set_pin: dict[str, str] | None = None,
) -> ExtractionOutcome:
    """Build the packet, then take the provider route or the non-run route."""
    packet = build_extraction_input_packet(
        stage=stage,
        company_id=company_id,
        observation_cutoff_date=observation_cutoff_date,
        passages=passages,
        document_publication_dates=document_publication_dates,
        coverage_artifact=coverage_artifact,
        source_snapshot_manifest=source_snapshot_manifest,
        artifact_root=artifact_root,
        snapshot_a_pin=snapshot_a_pin,
        snapshot_b_pin=snapshot_b_pin,
        product_decision_set_pin=product_decision_set_pin,
        capability_decision_set_pin=capability_decision_set_pin,
    )
    root = Path(run_root)
    if root.is_symlink() or root.exists():
        raise ExtractionError(
            f"run root already exists; runs are never overwritten: {root}",
            reason_code="run_root_exists",
        )
    root.mkdir(parents=True, exist_ok=False)

    # The packet is persisted write-once BEFORE either route branches.
    packet_sha = write_artifact(root, PACKET_REFERENCE, packet_bytes(packet))

    if not packet["passages"]:
        record = build_non_run_record(
            extraction_run_id=extraction_run_id,
            stage=stage,
            company_id=company_id,
            observation_cutoff_date=observation_cutoff_date,
            code_commit=code_commit,
            run_created_at=run_created_at,
            input_packet_reference=PACKET_REFERENCE,
            input_packet_sha256=packet_sha,
            coverage_artifact_reference=coverage_artifact["reference"],
            coverage_artifact_sha256=coverage_artifact["sha256"],
            reason_code="zero_admissible_passages",
            filter_ledger=packet["filter_ledger"],
        )
        non_run_sha = write_artifact(root, NON_RUN_REFERENCE, record_bytes(record))
        return ExtractionOutcome(
            verdict="no_run",
            run_root=root,
            packet=packet,
            packet_sha256=packet_sha,
            artifacts={
                PACKET_REFERENCE: packet_sha,
                NON_RUN_REFERENCE: non_run_sha,
            },
        )

    client = require_provider(provider)
    if not provider_client_contract:
        raise ExtractionError(
            "a provider-client contract artifact must be supplied",
            reason_code="source_artifact_missing",
        )

    prompt_id = prompts_for_stage(stage)[0]
    prompt = load_prompt(repo_root, prompt_id)
    prompt_sha = write_artifact(root, PROMPT_REFERENCE, prompt["text"].encode("utf-8"))

    response = client.complete(
        ProviderRequest(
            stage=stage,
            prompt_text=prompt["text"],
            prompt_sha256=prompt["prompt_hash"],
            input_packet_sha256=packet_sha,
            payload={"passages": packet["passages"]},
        )
    )
    raw_sha = write_raw_prediction(root, RAW_REFERENCE, response.raw_bytes)

    run_record = build_extraction_run(
        run_id=extraction_run_id,
        stage=stage,
        started_at=run_created_at,
        completed_at=run_created_at,
        status="completed",
        code_commit=code_commit,
        schema_hash=resolve_stage_schema_hash(stage, schema_root),
        prompt_hash=prompt["prompt_hash"],
        source_manifest_hash=source_snapshot_manifest["sha256"],
        model_provider=response.model_provider,
        model_name=response.model_name,
        model_parameters=response.model_parameters,
    )
    run_sha = write_artifact(root, EXTRACTION_RUN_REFERENCE, record_bytes(run_record))

    envelope = build_prediction_envelope(
        prediction_record_id=f"{prediction_run_id}-0",
        stage=stage,
        source_references=[RAW_REFERENCE, PROMPT_REFERENCE],
        prompt_model_metadata=response.prompt_model_metadata,
        input_packet_hash=packet_sha,
        prediction_run_manifest_reference=PREDICTION_MANIFEST_REFERENCE,
        input_packet_reference=PACKET_REFERENCE,
    )
    envelopes_bytes = canonical_jsonl_bytes([envelope])
    envelopes_sha = write_artifact(root, ENVELOPES_REFERENCE, envelopes_bytes)

    manifest = build_prediction_artifact_manifest(
        prediction_run_id=prediction_run_id,
        envelopes_reference=ENVELOPES_REFERENCE,
        envelopes_sha256=envelopes_sha,
        record_count=1,
        source_artifacts={
            "raw_prediction": {"reference": RAW_REFERENCE, "sha256": raw_sha},
            "extraction_input_packet": {"reference": PACKET_REFERENCE, "sha256": packet_sha},
            "coverage_artifact": dict(coverage_artifact),
            "resolved_prompt": {"reference": PROMPT_REFERENCE, "sha256": prompt_sha},
            "provider_client_contract": dict(provider_client_contract),
            "extraction_run": {"reference": EXTRACTION_RUN_REFERENCE, "sha256": run_sha},
        },
    )
    manifest_sha = write_artifact(
        root, PREDICTION_MANIFEST_REFERENCE, manifest_bytes(manifest)
    )
    return ExtractionOutcome(
        verdict="provider_run_complete",
        run_root=root,
        packet=packet,
        packet_sha256=packet_sha,
        artifacts={
            PACKET_REFERENCE: packet_sha,
            PROMPT_REFERENCE: prompt_sha,
            RAW_REFERENCE: raw_sha,
            EXTRACTION_RUN_REFERENCE: run_sha,
            ENVELOPES_REFERENCE: envelopes_sha,
            PREDICTION_MANIFEST_REFERENCE: manifest_sha,
        },
    )
