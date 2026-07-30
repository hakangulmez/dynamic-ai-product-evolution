"""Write-once artifact persistence, canonical serialization, and raw provider
output preservation (ADR-033).

Raw provider bytes are preserved literally and are **never repaired in place**
(CLAUDE.md rule 9). The canonical serializers here are byte-identical to the
ingestion and collection serializers by contract; the three are pinned
together by a cross-package equality test rather than an import, because
extraction may not depend on those packages.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..provenance import WriteOnceError, write_bytes_once
from .errors import ExtractionError, translate_write_once_error

__all__ = [
    "PREDICTION_ENVELOPE_CONTRACT",
    "RAW_CAPTURE_REPRESENTATION",
    "build_prediction_envelope",
    "canonical_json_bytes",
    "canonical_jsonl_bytes",
    "reject_contract_metadata",
    "sha256_bytes",
    "write_artifact",
    "write_raw_prediction",
]

# Closed static pin for the released contract identity. Extraction may not
# import evaluation.contracts, and caller-supplied metadata would let any
# contract_hash be minted. A drift test re-derives this from the real model.
PREDICTION_ENVELOPE_CONTRACT: dict[str, str] = {
    "contract_id": "prediction_envelope",
    "contract_version": "0.1.0",
    "contract_hash": "5ac06fb78220c3f7369863cda32ee914a1d33ff01020fc01e57d9bd0ccbb18a3",
}

_SHA256_HEX = 64

# The archival unit of a captured raw prediction, recorded in the envelope's
# open prompt_model_metadata mapping. That mapping is hash-bound through
# envelopes_sha256 in the prediction manifest, so the representation is
# auditable in the run artifact chain rather than only in an ADR. The released
# extraction_provider_client_contract@0.1.0 is deliberately left unchanged
# (ADR-035).
RAW_CAPTURE_REPRESENTATION = "post_content_encoding_entity_body"


def reject_contract_metadata(forbidden: dict[str, Any], *mappings: Any) -> None:
    """Fail closed on any caller channel that could reach an artifact root."""
    if forbidden:
        raise ExtractionError(
            f"unsupported inputs: {sorted(forbidden)}; contract metadata is fixed "
            "by the closed static pin",
            reason_code="contract_metadata_forbidden",
        )
    for mapping in mappings:
        if isinstance(mapping, dict) and "contract" in mapping:
            raise ExtractionError(
                "caller-supplied contract metadata is forbidden",
                reason_code="contract_metadata_forbidden",
            )


def require_pin(
    pin: dict[str, str], *, contract_id: str, contract_version: str
) -> dict[str, str]:
    """Validate a closed static pin's COMPLETE identity.

    Checking only the digest would let a pin carry a correct hash under the
    wrong contract id or version.
    """
    if not isinstance(pin, dict):
        raise ExtractionError(
            "the contract pin must be a mapping", reason_code="contract_pin_invalid"
        )
    if sorted(pin) != ["contract_hash", "contract_id", "contract_version"]:
        raise ExtractionError(
            f"the contract pin must carry exactly id, version and hash: {sorted(pin)}",
            reason_code="contract_pin_invalid",
        )
    if pin.get("contract_id") != contract_id:
        raise ExtractionError(
            f"contract pin id mismatch: expected {contract_id!r}, got "
            f"{pin.get('contract_id')!r}",
            reason_code="contract_pin_invalid",
        )
    if pin.get("contract_version") != contract_version:
        raise ExtractionError(
            f"contract pin version mismatch: expected {contract_version!r}, got "
            f"{pin.get('contract_version')!r}",
            reason_code="contract_pin_invalid",
        )
    digest = pin.get("contract_hash")
    if (
        not isinstance(digest, str)
        or len(digest) != _SHA256_HEX
        or not all(c in "0123456789abcdef" for c in digest)
    ):
        raise ExtractionError(
            "contract pin hash must be 64 lowercase hex characters",
            reason_code="contract_pin_invalid",
        )
    return dict(pin)


def sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def canonical_json_bytes(payload: object) -> bytes:
    """Deterministic JSON bytes: sorted keys, compact separators, trailing newline."""
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def canonical_jsonl_bytes(records: list[object]) -> bytes:
    lines = [
        json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        for record in records
    ]
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


def write_artifact(root: str | Path, relative_path: str, data: bytes) -> str:
    """Write one artifact write-once and return its verified SHA-256."""
    destination = Path(root) / relative_path
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ExtractionError(
            f"failed to create directory for {relative_path}", reason_code="write_error"
        ) from exc
    try:
        return write_bytes_once(destination, data, what=f"extraction {relative_path}")
    except WriteOnceError as exc:
        raise translate_write_once_error(exc) from exc


def write_raw_prediction(
    root: str | Path, relative_path: str, raw_bytes: bytes
) -> str:
    """Persist the provider's literal output. Never normalized, never repaired."""
    if not isinstance(raw_bytes, (bytes, bytearray)):
        raise ExtractionError(
            "raw prediction output must be bytes", reason_code="raw_artifact_invalid"
        )
    return write_artifact(root, relative_path, bytes(raw_bytes))


def build_prediction_envelope(
    *,
    prediction_record_id: str,
    stage: str,
    source_references: list[str],
    prompt_model_metadata: dict[str, Any],
    input_packet_hash: str,
    prediction_run_manifest_reference: str,
    input_packet_reference: str,
    **forbidden: Any,
) -> dict[str, Any]:
    """One ``prediction_envelope@0.1.0`` record.

    There is no ``contract_metadata`` parameter: the contract stamp comes from
    the closed static pin and is set last, so no merge order can override it.

    ``source_references`` must include the stage input-packet artifact, which
    is how corpus scope and inherited coverage reach the harness without any
    field being added to the frozen envelope contract.

    ``prompt_model_metadata`` must declare ``raw_capture_representation``: the
    archived bytes are meaningless without knowing which representation they
    are, and the envelope is the one hash-bound, per-prediction-record home for
    that fact.
    """
    reject_contract_metadata(forbidden, prompt_model_metadata)
    if prompt_model_metadata.get("raw_capture_representation") != (
        RAW_CAPTURE_REPRESENTATION
    ):
        raise ExtractionError(
            "prompt_model_metadata must declare raw_capture_representation="
            f"{RAW_CAPTURE_REPRESENTATION!r}",
            reason_code="capture_representation_missing",
        )
    if not input_packet_reference:
        raise ExtractionError(
            "an envelope must reference the stage input packet",
            reason_code="envelope_missing_input_packet",
        )
    references = list(source_references)
    if input_packet_reference not in references:
        references.append(input_packet_reference)
    return {
        "prediction_record_id": prediction_record_id,
        "stage": stage,
        "source_references": sorted(set(references)),
        "prompt_model_metadata": dict(prompt_model_metadata),
        "input_packet_hash": input_packet_hash,
        "prediction_run_manifest_reference": prediction_run_manifest_reference,
        # Set last, from the closed pin only.
        "contract": require_pin(
            PREDICTION_ENVELOPE_CONTRACT,
            contract_id="prediction_envelope",
            contract_version="0.1.0",
        ),
    }
