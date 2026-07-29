"""Stage-dispatched extraction orchestration (ADR-033, ADR-034).

**Every deterministic input is resolved before anything is created on disk.**
The packet is built in memory; the provider, its client contract, the resolved
prompt, and the stage output-schema pin are all validated while the run root
still does not exist. Only once all of them pass is ``mkdir`` called. A refused
run therefore leaves zero artifacts and there is nothing to roll back — the
guarantee is "never created", not "cleaned up afterwards".

That ordering also stops a wasted provider call: before this, the stage schema
pin was verified *after* ``complete()`` had already run and the raw bytes had
already been written, so a fully deterministic, pre-call-knowable mismatch
could only surface once the call had been paid for.

Three published shapes, each with an exact artifact count:

- **pre-run refusal** — 0 artifacts, no run root;
- **non-run** (zero admissible passages) — 2 artifacts, and no provider,
  prompt, or schema preflight is performed at all;
- **terminal provider failure** — 5 artifacts: packet, prompt, client
  contract, an errored ``extraction_run``, and the provider-error record.

No provider is constructed here: one must be injected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import ExtractionError
from .input_packet import build_extraction_input_packet, packet_bytes
from .manifests import (
    PROVIDER_ERROR_REASONS,
    build_extraction_run,
    build_non_run_record,
    build_provider_error_record,
    record_bytes,
    resolve_stage_schema_hash,
    validate_provider_client_contract,
)
from .prediction_manifest import build_prediction_artifact_manifest, manifest_bytes
from .prompts import load_prompt, prompts_for_stage
from .provider_adapter import ProviderRequest, require_provider
from .raw_artifacts import (
    build_prediction_envelope,
    canonical_json_bytes,
    canonical_jsonl_bytes,
    write_artifact,
    write_raw_prediction,
)

__all__ = ["ExtractionOutcome", "run_extraction_stage"]

PACKET_REFERENCE = "inputs/extraction_input_packet.json"
PROMPT_REFERENCE = "inputs/resolved_prompt.md"
CLIENT_CONTRACT_REFERENCE = "inputs/provider_client_contract.json"
NON_RUN_REFERENCE = "manifests/extraction_non_run_record.json"
EXTRACTION_RUN_REFERENCE = "manifests/extraction_run.json"
PROVIDER_ERROR_REFERENCE = "manifests/extraction_provider_error_record.json"
RAW_REFERENCE = "predictions/raw_prediction.json"
ENVELOPES_REFERENCE = "predictions/prediction_envelopes.jsonl"
PREDICTION_MANIFEST_REFERENCE = "predictions/prediction_run_manifest.json"

# Distinguishes "not supplied" from an explicitly supplied ``None``. Both a pin
# and a ``None`` are caller-channel violations, so ``None`` cannot be the
# default sentinel.
_PIN_UNSET = object()


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


def _require_absent_run_root(root: Path) -> None:
    if root.is_symlink() or root.exists():
        raise ExtractionError(
            f"run root already exists; runs are never overwritten: {root}",
            reason_code="run_root_exists",
        )


def _assert_run_permitted(client: object) -> None:
    """Ask the injected provider whether a run may proceed at all.

    Called before the run root exists. The provider's own exception type is
    never imported: only the duck-typed ``reason_code`` is read, so no upstream
    text can reach the boundary.
    """
    try:
        client.assert_run_permitted()
    except Exception as exc:  # noqa: BLE001 - the provider seam is total
        reason = getattr(exc, "reason_code", None)
        raise ExtractionError(
            "the injected provider refused this run",
            reason_code=reason if isinstance(reason, str) and reason else "provider_refused",
        ) from None


def _client_contract_of(client: object) -> dict[str, Any]:
    try:
        contract = client.client_contract()
    except Exception as exc:  # noqa: BLE001 - the provider seam is total
        reason = getattr(exc, "reason_code", None)
        raise ExtractionError(
            "the injected provider could not supply a client contract",
            reason_code=(
                reason if isinstance(reason, str) and reason else "client_contract_invalid"
            ),
        ) from None
    return validate_provider_client_contract(contract)


def _terminal_failure(exc: BaseException) -> tuple[str, int]:
    """Read the sanitized terminal identity from a provider failure.

    An undeclared or missing reason collapses to ``provider_response_unusable``
    rather than widening the released enum, and never to a message string.
    """
    reason = getattr(exc, "reason_code", None)
    if not isinstance(reason, str) or reason not in PROVIDER_ERROR_REASONS:
        reason = "provider_response_unusable"
    attempts = getattr(exc, "attempt_count", None)
    if not isinstance(attempts, int) or attempts < 1:
        attempts = 1
    return reason, attempts


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
    provider_client_contract: object = _PIN_UNSET,
    artifact_root: str | Path | None = None,
    snapshot_a_pin: dict[str, str] | None = None,
    snapshot_b_pin: dict[str, str] | None = None,
    product_decision_set_pin: dict[str, str] | None = None,
    capability_decision_set_pin: dict[str, str] | None = None,
) -> ExtractionOutcome:
    """Resolve every deterministic input, then take one of the three routes."""
    # [A] The caller-supplied contract-pin channel is closed. Checked before the
    # route branch, so passing a pin fails identically on either route and the
    # rule has no exception.
    if provider_client_contract is not _PIN_UNSET:
        raise ExtractionError(
            "the provider-client contract is produced by the injected provider "
            "and written here; a caller-supplied pin is not accepted",
            reason_code="contract_pin_forbidden",
        )

    # [B] In memory only. Nothing is persisted yet.
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

    if not packet["passages"]:
        # Non-run route. No provider, prompt, or schema preflight happens here:
        # no provider will be called, so requiring one would be theatre.
        _require_absent_run_root(root)
        root.mkdir(parents=True, exist_ok=False)
        packet_sha = write_artifact(root, PACKET_REFERENCE, packet_bytes(packet))
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

    # --- pre-run gate: [C] through [H], all side-effect free -----------------
    client = require_provider(provider)          # [C]
    _assert_run_permitted(client)                # [D]
    contract = _client_contract_of(client)       # [E]
    contract_payload = canonical_json_bytes(contract)
    prompt_id = prompts_for_stage(stage)[0]      # [F]
    prompt = load_prompt(repo_root, prompt_id)
    prompt_payload = prompt["text"].encode("utf-8")
    schema_hash = resolve_stage_schema_hash(stage, schema_root)  # [G]
    _require_absent_run_root(root)               # [H]

    # [I] First filesystem effect of this route.
    root.mkdir(parents=True, exist_ok=False)
    packet_sha = write_artifact(root, PACKET_REFERENCE, packet_bytes(packet))
    prompt_sha = write_artifact(root, PROMPT_REFERENCE, prompt_payload)
    contract_sha = write_artifact(root, CLIENT_CONTRACT_REFERENCE, contract_payload)

    try:
        response = client.complete(
            ProviderRequest(
                stage=stage,
                prompt_text=prompt["text"],
                prompt_sha256=prompt["prompt_hash"],
                input_packet_sha256=packet_sha,
                payload={"passages": packet["passages"]},
            )
        )
    except Exception as exc:  # noqa: BLE001 - the provider seam is total
        reason, attempts = _terminal_failure(exc)
        run_record = build_extraction_run(
            run_id=extraction_run_id,
            stage=stage,
            started_at=run_created_at,
            completed_at=run_created_at,
            status="errored",
            code_commit=code_commit,
            schema_hash=schema_hash,
            prompt_hash=prompt["prompt_hash"],
            source_manifest_hash=source_snapshot_manifest["sha256"],
            error_count=attempts,
        )
        run_sha = write_artifact(root, EXTRACTION_RUN_REFERENCE, record_bytes(run_record))
        error_record = build_provider_error_record(
            extraction_run_id=extraction_run_id,
            stage=stage,
            company_id=company_id,
            code_commit=code_commit,
            input_packet_reference=PACKET_REFERENCE,
            input_packet_sha256=packet_sha,
            resolved_prompt_reference=PROMPT_REFERENCE,
            resolved_prompt_sha256=prompt_sha,
            provider_client_contract_reference=CLIENT_CONTRACT_REFERENCE,
            provider_client_contract_sha256=contract_sha,
            extraction_run_reference=EXTRACTION_RUN_REFERENCE,
            extraction_run_sha256=run_sha,
            reason_code=reason,
            attempt_count=attempts,
        )
        write_artifact(root, PROVIDER_ERROR_REFERENCE, record_bytes(error_record))
        # Evidence first, then a sanitized failure. No raw prediction, envelope,
        # prediction manifest, or harness run exists on this route.
        raise ExtractionError(
            "every provider attempt failed; the terminal cause is recorded in "
            "the provider-error record",
            reason_code=reason,
        ) from None

    raw_sha = write_raw_prediction(root, RAW_REFERENCE, response.raw_bytes)

    run_record = build_extraction_run(
        run_id=extraction_run_id,
        stage=stage,
        started_at=run_created_at,
        completed_at=run_created_at,
        status="completed",
        code_commit=code_commit,
        schema_hash=schema_hash,
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
        source_references=[RAW_REFERENCE, PROMPT_REFERENCE, CLIENT_CONTRACT_REFERENCE],
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
            "provider_client_contract": {
                "reference": CLIENT_CONTRACT_REFERENCE,
                "sha256": contract_sha,
            },
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
            CLIENT_CONTRACT_REFERENCE: contract_sha,
            RAW_REFERENCE: raw_sha,
            EXTRACTION_RUN_REFERENCE: run_sha,
            ENVELOPES_REFERENCE: envelopes_sha,
            PREDICTION_MANIFEST_REFERENCE: manifest_sha,
        },
    )
