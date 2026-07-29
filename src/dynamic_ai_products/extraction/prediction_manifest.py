"""The harness-visible prediction manifest root (ADR-033).

``prediction_artifact_manifest@0.1.0`` is a released model contract; this module
emits a conforming document without importing the model. Its ``source_artifacts``
tuple pins **six** artifacts, making all provider provenance reachable by hash:

1. the raw prediction bytes
2. the stage input packet          (carries corpus_scope + the coverage pin)
3. the coverage artifact
4. the resolved prompt artifact
5. the provider-client contract artifact
6. ``extraction_run@0.1.0`` itself

Write order is acyclic — ``extraction_run`` is written before the manifest and
never references it, so the manifest is the single root.
"""

from __future__ import annotations

import re
from typing import Any

from .errors import ExtractionError
from .raw_artifacts import canonical_json_bytes, reject_contract_metadata

__all__ = [
    "PREDICTION_MANIFEST_CONTRACT",
    "REQUIRED_SOURCE_ARTIFACT_ROLES",
    "build_prediction_artifact_manifest",
    "manifest_bytes",
]

# Closed static pin; a drift test re-derives it from the released model.
PREDICTION_MANIFEST_CONTRACT: dict[str, str] = {
    "contract_id": "prediction_artifact_manifest",
    "contract_version": "0.1.0",
    "contract_hash": "4b164aea18fc99f9518854aca0fb98587eb71d81c972a477d48cb815ddc0dbe4",
}

REQUIRED_SOURCE_ARTIFACT_ROLES: tuple[str, ...] = (
    "raw_prediction",
    "extraction_input_packet",
    "coverage_artifact",
    "resolved_prompt",
    "provider_client_contract",
    "extraction_run",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def build_prediction_artifact_manifest(
    *,
    prediction_run_id: str,
    envelopes_reference: str,
    envelopes_sha256: str,
    record_count: int,
    source_artifacts: dict[str, dict[str, str]],
    **forbidden: Any,
) -> dict[str, Any]:
    """Emit the released manifest shape with all six source artifacts pinned.

    No ``contract_metadata`` parameter exists; the stamp comes from the closed
    static pin and is set last.
    """
    reject_contract_metadata(forbidden, source_artifacts, *source_artifacts.values())
    missing = sorted(set(REQUIRED_SOURCE_ARTIFACT_ROLES) - set(source_artifacts))
    if missing:
        raise ExtractionError(
            f"prediction manifest is missing source artifacts: {missing}",
            reason_code="source_artifact_missing",
        )
    extra = sorted(set(source_artifacts) - set(REQUIRED_SOURCE_ARTIFACT_ROLES))
    if extra:
        raise ExtractionError(
            f"prediction manifest carries undeclared source artifacts: {extra}",
            reason_code="source_artifact_unknown",
        )
    if not isinstance(envelopes_sha256, str) or not _SHA256_RE.fullmatch(envelopes_sha256):
        raise ExtractionError(
            "envelopes_sha256 must be 64 lowercase hex characters",
            reason_code="pin_invalid",
        )

    entries: list[dict[str, str]] = []
    for role in REQUIRED_SOURCE_ARTIFACT_ROLES:
        pin = source_artifacts[role]
        reference = pin.get("reference")
        digest = pin.get("sha256")
        if not isinstance(reference, str) or not reference:
            raise ExtractionError(
                f"source artifact {role} lacks a reference",
                reason_code="source_artifact_missing",
            )
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise ExtractionError(
                f"source artifact {role} lacks a valid sha256",
                reason_code="pin_invalid",
            )
        entries.append({"reference": reference, "sha256": digest})
    entries.sort(key=lambda entry: (entry["reference"], entry["sha256"]))

    digest = PREDICTION_MANIFEST_CONTRACT.get("contract_hash")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise ExtractionError(
            "the prediction-manifest contract pin is malformed",
            reason_code="contract_pin_invalid",
        )
    return {
        "prediction_run_id": prediction_run_id,
        "envelopes_reference": envelopes_reference,
        "envelopes_sha256": envelopes_sha256,
        "record_count": int(record_count),
        "source_artifacts": entries,
        # Set last, from the closed pin only.
        "contract": dict(PREDICTION_MANIFEST_CONTRACT),
    }


def manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return canonical_json_bytes(manifest)
