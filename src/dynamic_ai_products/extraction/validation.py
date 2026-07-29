"""Human validation decision sets and accepted-observation artifacts (ADR-033).

A decision set is a human judgement. No deterministic producer and no provider
may synthesise one. It pins the raw artifact, the candidate collection, the
stage input packet, the coverage artifact, and — for capability — Snapshot A.

Each accepted candidate is persisted as its own observation artifact, and the
decision set records that artifact's reference and SHA-256 so a snapshot's
expected member set is derivable.
"""

from __future__ import annotations

import re
from typing import Any

from .candidates import OBSERVATION_KINDS
from .errors import ExtractionError
from .raw_artifacts import canonical_json_bytes, write_artifact

__all__ = [
    "DECISION_SET_CONTRACT",
    "DECISIONS",
    "build_validation_decision_set",
    "decision_set_bytes",
    "persist_accepted_observations",
]

DECISION_SET_CONTRACT = "extraction_validation_decision_set@0.1.0"
DECISIONS: tuple[str, ...] = ("accept", "reject")

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def persist_accepted_observations(
    *,
    artifact_root: str,
    relative_dir: str,
    collection: dict[str, Any],
    accepted_candidate_ids: list[str],
) -> dict[str, dict[str, str]]:
    """Persist each accepted observation as its own write-once artifact."""
    by_id = {entry["candidate_id"]: entry for entry in collection.get("entries", [])}
    unknown = sorted(set(accepted_candidate_ids) - set(by_id))
    if unknown:
        raise ExtractionError(
            f"accepted candidate ids absent from the collection: {unknown}",
            reason_code="candidate_id_unknown",
        )
    out: dict[str, dict[str, str]] = {}
    for candidate_id in sorted(set(accepted_candidate_ids)):
        entry = by_id[candidate_id]
        reference = f"{relative_dir}/{candidate_id}.json"
        digest = write_artifact(
            artifact_root, reference, canonical_json_bytes(entry["observation"])
        )
        out[candidate_id] = {"reference": reference, "sha256": digest}
    return out


def build_validation_decision_set(
    *,
    observation_kind: str,
    decision_set_version: str,
    raw_artifact_reference: str,
    raw_artifact_sha256: str,
    candidate_collection_reference: str,
    candidate_collection_sha256: str,
    input_packet_reference: str,
    input_packet_sha256: str,
    coverage_artifact_reference: str,
    coverage_artifact_sha256: str,
    collection: dict[str, Any],
    accepted_candidate_ids: list[str],
    rejection_reasons: dict[str, str] | None = None,
    accepted_artifacts: dict[str, dict[str, str]] | None = None,
    snapshot_a_reference: str | None = None,
    snapshot_a_sha256: str | None = None,
) -> dict[str, Any]:
    """Build the human decision set. Every pin is required."""
    if observation_kind not in OBSERVATION_KINDS:
        raise ExtractionError(
            f"unknown observation_kind: {observation_kind!r}",
            reason_code="observation_kind_invalid",
        )
    if collection.get("observation_kind") != observation_kind:
        raise ExtractionError(
            "candidate collection kind does not match the decision set",
            reason_code="observation_kind_invalid",
        )
    if collection.get("raw_artifact_sha256") != raw_artifact_sha256:
        raise ExtractionError(
            "candidate collection pins a different raw artifact",
            reason_code="raw_artifact_pin_mismatch",
        )
    for label, value in (
        ("raw_artifact_sha256", raw_artifact_sha256),
        ("candidate_collection_sha256", candidate_collection_sha256),
        ("input_packet_sha256", input_packet_sha256),
        ("coverage_artifact_sha256", coverage_artifact_sha256),
    ):
        if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
            raise ExtractionError(
                f"{label} must be 64 lowercase hex characters", reason_code="pin_invalid"
            )
    if observation_kind == "capability":
        if not snapshot_a_reference or not isinstance(snapshot_a_sha256, str) or not _SHA256_RE.fullmatch(snapshot_a_sha256):
            raise ExtractionError(
                "a capability decision set must pin Snapshot A",
                reason_code="capability_decision_snapshot_a_mismatch",
            )
    elif snapshot_a_reference is not None or snapshot_a_sha256 is not None:
        raise ExtractionError(
            "a product decision set must not pin Snapshot A",
            reason_code="capability_decision_snapshot_a_mismatch",
        )

    artifacts = dict(accepted_artifacts or {})
    reasons = dict(rejection_reasons or {})
    accepted = set(accepted_candidate_ids)
    decisions: list[dict[str, Any]] = []
    for entry in sorted(collection.get("entries", []), key=lambda e: e["ordinal"]):
        candidate_id = entry["candidate_id"]
        if candidate_id in accepted:
            pin = artifacts.get(candidate_id)
            if not pin:
                raise ExtractionError(
                    f"accepted candidate {candidate_id} has no persisted artifact",
                    reason_code="validation_provenance_missing",
                )
            decisions.append(
                {
                    "candidate_id": candidate_id,
                    "decision": "accept",
                    "reason": reasons.get(candidate_id, ""),
                    "accepted_artifact_reference": pin["reference"],
                    "accepted_artifact_sha256": pin["sha256"],
                }
            )
        else:
            decisions.append(
                {
                    "candidate_id": candidate_id,
                    "decision": "reject",
                    "reason": reasons.get(candidate_id, "rejected_by_human_review"),
                    "accepted_artifact_reference": None,
                    "accepted_artifact_sha256": None,
                }
            )
    return {
        "contract": DECISION_SET_CONTRACT,
        "schema_version": "0.1.0",
        "observation_kind": observation_kind,
        "decision_set_version": decision_set_version,
        "raw_artifact_reference": raw_artifact_reference,
        "raw_artifact_sha256": raw_artifact_sha256,
        "candidate_collection_reference": candidate_collection_reference,
        "candidate_collection_sha256": candidate_collection_sha256,
        "input_packet_reference": input_packet_reference,
        "input_packet_sha256": input_packet_sha256,
        "coverage_artifact_reference": coverage_artifact_reference,
        "coverage_artifact_sha256": coverage_artifact_sha256,
        "snapshot_a_reference": snapshot_a_reference,
        "snapshot_a_sha256": snapshot_a_sha256,
        "decisions": decisions,
        "accepted_count": sum(1 for d in decisions if d["decision"] == "accept"),
        "rejected_count": sum(1 for d in decisions if d["decision"] == "reject"),
    }


def decision_set_bytes(decision_set: dict[str, Any]) -> bytes:
    return canonical_json_bytes(decision_set)
