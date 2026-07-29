"""Candidate collections as legal wrappers (ADR-033).

``product_observation@0.1.0`` and ``capability_observation@0.1.0`` are strict,
so ``candidate_id`` cannot be appended to an observation object. Each candidate
is a wrapper whose nested ``observation`` payload validates independently
against the unchanged released schema.

One parameterized contract carries both kinds, discriminated by
``observation_kind``, rather than two near-identical schemas that would drift.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .errors import ExtractionError
from .raw_artifacts import canonical_json_bytes

__all__ = [
    "CANDIDATE_COLLECTION_CONTRACT",
    "OBSERVATION_KINDS",
    "build_candidate_collection",
    "candidate_id_for",
    "collection_bytes",
]

CANDIDATE_COLLECTION_CONTRACT = "extraction_candidate_collection@0.1.0"
OBSERVATION_KINDS: tuple[str, ...] = ("product", "capability")

_SCHEMA_FOR_KIND = {
    "product": "product_observation.schema.json",
    "capability": "capability_observation.schema.json",
}


def candidate_id_for(raw_artifact_sha256: str, ordinal: int, observation: dict[str, Any]) -> str:
    """Bind identity to the raw artifact digest and the emission ordinal.

    Non-transferable across raw artifacts; disambiguates identical text.
    """
    material = (
        raw_artifact_sha256.encode("ascii")
        + b"\x00"
        + str(ordinal).encode("ascii")
        + b"\x00"
        + canonical_json_bytes(observation)
    )
    return sha256(material).hexdigest()[:32]


def _validator(schema_root: str | Path, kind: str) -> Draft202012Validator:
    schema_path = Path(schema_root) / _SCHEMA_FOR_KIND[kind]
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ExtractionError(
            f"released observation schema is unreadable: {schema_path}",
            reason_code="observation_schema_unavailable",
        ) from exc
    return Draft202012Validator(schema)


def build_candidate_collection(
    *,
    observation_kind: str,
    raw_artifact_reference: str,
    raw_artifact_sha256: str,
    observations: list[Any],
    schema_root: str | Path = "schemas",
) -> dict[str, Any]:
    """Wrap deterministic, schema-valid candidates. Rejects are counted, not dropped."""
    if observation_kind not in OBSERVATION_KINDS:
        raise ExtractionError(
            f"unknown observation_kind: {observation_kind!r}",
            reason_code="observation_kind_invalid",
        )
    validator = _validator(schema_root, observation_kind)
    entries: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for ordinal, observation in enumerate(observations):
        if not isinstance(observation, dict):
            rejected.append({"ordinal": ordinal, "reason": "not_an_object"})
            continue
        errors = sorted(validator.iter_errors(observation), key=lambda e: list(e.path))
        if errors:
            rejected.append(
                {
                    "ordinal": ordinal,
                    "reason": "schema_invalid",
                    "detail": errors[0].message,
                }
            )
            continue
        entries.append(
            {
                "candidate_id": candidate_id_for(raw_artifact_sha256, ordinal, observation),
                "ordinal": ordinal,
                "observation_kind": observation_kind,
                "observation": observation,
            }
        )
    entries.sort(key=lambda entry: entry["ordinal"])
    return {
        "contract": CANDIDATE_COLLECTION_CONTRACT,
        "schema_version": "0.1.0",
        "observation_kind": observation_kind,
        "raw_artifact_reference": raw_artifact_reference,
        "raw_artifact_sha256": raw_artifact_sha256,
        "entries": entries,
        "rejected": rejected,
        "accepted_candidate_count": len(entries),
        "rejected_candidate_count": len(rejected),
    }


def collection_bytes(collection: dict[str, Any]) -> bytes:
    return canonical_json_bytes(collection)
