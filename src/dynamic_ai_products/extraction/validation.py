"""Human validation decision sets and accepted-observation artifacts (ADR-033).

A decision set is a human judgement. No deterministic producer and no provider
may synthesise one. It pins the raw artifact, the candidate collection, the
stage input packet, the coverage artifact, and — per observation kind — the
parent snapshot it was judged against: Snapshot A for capability, Snapshot B
for task, neither for product.

Each accepted candidate is persisted as its own observation artifact, and the
decision set records that artifact's reference and SHA-256 so a snapshot's
expected member set is derivable.
"""

from __future__ import annotations

import re
from typing import Any

from .candidates import OBSERVATION_KINDS
from .errors import ExtractionError
from .manifests import _require_aware_instant
from .raw_artifacts import canonical_json_bytes, write_artifact

__all__ = [
    "DECISION_SET_CONTRACT",
    "DECISION_SET_CONTRACT_V2",
    "DECISION_SET_CONTRACT_V3",
    "DECISION_SET_KINDS_BY_CONTRACT",
    "DECISIONS",
    "KNOWN_DECISION_SET_CONTRACTS",
    "SNAPSHOT_AXIS_BY_KIND",
    "build_validation_decision_set",
    "build_validation_decision_set_v2",
    "build_validation_decision_set_v3",
    "decision_set_bytes",
    "persist_accepted_observations",
]

DECISION_SET_CONTRACT = "extraction_validation_decision_set@0.1.0"

# ADR-057. The successor exists because @0.1.0 records *what* a human decided
# and *why*, but not *who* decided or *when*. For an evidence-grounded dataset
# that is the wrong thing to leave out of the file: a later reader holding the
# decision set could not answer "who admitted this observation" from it.
DECISION_SET_CONTRACT_V2 = "extraction_validation_decision_set@0.2.0"

# ADR-071. @0.1.0 and @0.2.0 were written when only two observation kinds could
# reach a decision set, so both encode a two-way split: capability pins Snapshot
# A, everything-else pins nothing. The task kind pins Snapshot B -- the accepted
# *capability* parents -- and under the released contracts it fell into the
# "everything else" arm and was told it must not pin a snapshot at all. The
# successor carries three kinds and both snapshot axes.
DECISION_SET_CONTRACT_V3 = "extraction_validation_decision_set@0.3.0"

# Every decision-set contract this code has published, oldest first. Consumers
# recognise the set rather than one literal, for the reason ADR-053 established:
# a const pinned to a single version silently freezes the artifact it names.
KNOWN_DECISION_SET_CONTRACTS: tuple[str, ...] = (
    DECISION_SET_CONTRACT,
    DECISION_SET_CONTRACT_V2,
    DECISION_SET_CONTRACT_V3,
)

# Which parent snapshot each observation kind's decision set pins, as a closed
# map rather than a branch. The rule is a property of the *kind*, not of the
# contract version, so it is stated once here and every builder reads it.
#
#   product     -- predates both snapshots; pins neither
#   capability  -- judged against Snapshot A, the accepted product parents
#   task        -- judged against Snapshot B, the accepted capability parents
#
# A kind added to OBSERVATION_KINDS without an entry here fails closed with its
# own reason code. That is the ADR-053/058/061/062/064 lesson: the defect is
# never the missing entry, it is the neighbouring branch that silently absorbs
# it. `else` is what turned a task decision set into a product one.
SNAPSHOT_AXIS_BY_KIND: dict[str, str | None] = {
    "product": None,
    "capability": "a",
    "task": "b",
}

# Which kinds each published contract can express. @0.1.0 and @0.2.0 have no
# snapshot_b field, so a task decision set is not merely unvalidated under them
# -- it is unrepresentable. The gate is here so building one is refused rather
# than silently emitted in a shape no schema accepts.
DECISION_SET_KINDS_BY_CONTRACT: dict[str, tuple[str, ...]] = {
    DECISION_SET_CONTRACT: ("product", "capability"),
    DECISION_SET_CONTRACT_V2: ("product", "capability"),
    DECISION_SET_CONTRACT_V3: ("product", "capability", "task"),
}

DECISIONS: tuple[str, ...] = ("accept", "reject")

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_SNAPSHOT_LABELS = {"a": "Snapshot A", "b": "Snapshot B"}
# One reason code per snapshot axis. The A-axis code is the released one and its
# two messages are unchanged, so no existing caller's error contract moves.
_SNAPSHOT_CODES = {
    "a": "capability_decision_snapshot_a_mismatch",
    "b": "task_decision_snapshot_b_mismatch",
}


def _snapshot_axis_for(observation_kind: str) -> str | None:
    """Resolve the kind's snapshot rule, or refuse. Never defaults."""
    try:
        return SNAPSHOT_AXIS_BY_KIND[observation_kind]
    except KeyError:
        raise ExtractionError(
            "no parent-snapshot rule is declared for observation_kind "
            f"{observation_kind!r}",
            reason_code="decision_set_snapshot_rule_missing",
        ) from None


def _kinds_for_contract(target_contract: str) -> tuple[str, ...]:
    try:
        return DECISION_SET_KINDS_BY_CONTRACT[target_contract]
    except KeyError:
        raise ExtractionError(
            f"unknown decision-set contract: {target_contract!r}",
            reason_code="decision_set_contract_unknown",
        ) from None


def _check_snapshot_pins(
    *,
    observation_kind: str,
    pins: dict[str, tuple[str | None, str | None]],
) -> None:
    """Enforce the closed rule: the kind's own axis is pinned, the other is not."""
    expected = _snapshot_axis_for(observation_kind)
    for axis in ("a", "b"):
        reference, digest = pins[axis]
        if axis == expected:
            if (
                not reference
                or not isinstance(digest, str)
                or not _SHA256_RE.fullmatch(digest)
            ):
                raise ExtractionError(
                    f"a {observation_kind} decision set must pin "
                    f"{_SNAPSHOT_LABELS[axis]}",
                    reason_code=_SNAPSHOT_CODES[axis],
                )
        elif reference is not None or digest is not None:
            raise ExtractionError(
                f"a {observation_kind} decision set must not pin "
                f"{_SNAPSHOT_LABELS[axis]}",
                reason_code=_SNAPSHOT_CODES[axis],
            )


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
    snapshot_b_reference: str | None = None,
    snapshot_b_sha256: str | None = None,
    target_contract: str = DECISION_SET_CONTRACT,
) -> dict[str, Any]:
    """Build the human decision set. Every pin is required.

    ``target_contract`` names the contract the caller is building, and decides
    only which observation kinds are admissible -- the judgement itself, every
    pin rule and the snapshot rule are identical across versions and computed
    here once. It defaults to the released contract, so this function's own
    output and its released behaviour are unchanged.

    The emitted mapping is always the @0.1.0 key set. A successor adds its own
    fields to the returned dict, as ``build_validation_decision_set_v2`` adds
    the human and ``build_validation_decision_set_v3`` adds the Snapshot B pin.
    """
    allowed_kinds = _kinds_for_contract(target_contract)
    if observation_kind not in OBSERVATION_KINDS:
        raise ExtractionError(
            f"unknown observation_kind: {observation_kind!r}",
            reason_code="observation_kind_invalid",
        )
    if observation_kind not in allowed_kinds:
        raise ExtractionError(
            f"{target_contract} does not carry observation_kind "
            f"{observation_kind!r}; it expresses {list(allowed_kinds)}",
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
    _check_snapshot_pins(
        observation_kind=observation_kind,
        pins={
            "a": (snapshot_a_reference, snapshot_a_sha256),
            "b": (snapshot_b_reference, snapshot_b_sha256),
        },
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


def build_validation_decision_set_v2(
    *,
    decided_by: str,
    decided_at: str,
    **fields: Any,
) -> dict[str, Any]:
    """The ``@0.2.0`` decision set: everything ``@0.1.0`` carries, plus the human.

    Delegates to the released builder for the whole judgement so the two cannot
    diverge on what a decision *is* -- every pin rule, the per-kind parent
    snapshot rule, the accepted-artifact requirement and the counts are computed
    once, in one place. This function adds exactly the two fields that make the
    artifact answer its own provenance question.

    ``decided_at`` is parsed and must carry an explicit UTC offset. A naive
    instant is refused rather than assumed to be UTC: guessing a zone on the
    record of a human admission decision would be inventing provenance.
    """
    if not isinstance(decided_by, str) or not decided_by.strip():
        raise ExtractionError(
            "decided_by must be a non-blank string; a decision set records who "
            "made the judgement",
            reason_code="validation_provenance_missing",
        )
    _require_aware_instant(
        decided_at, field="decided_at", code="validation_provenance_missing"
    )
    decision_set = build_validation_decision_set(**fields)
    decision_set["contract"] = DECISION_SET_CONTRACT_V2
    decision_set["schema_version"] = "0.2.0"
    decision_set["decided_by"] = decided_by
    decision_set["decided_at"] = decided_at
    return decision_set


def build_validation_decision_set_v3(
    *,
    decided_by: str,
    decided_at: str,
    snapshot_b_reference: str | None = None,
    snapshot_b_sha256: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """The ``@0.3.0`` decision set: three kinds, and the Snapshot B pin.

    Delegates the whole judgement down the released chain -- v3 -> v2 -> the
    base builder -- so who-decided, every artifact pin, the accepted-artifact
    requirement, the counts *and* the snapshot rule stay computed in one place.
    This function adds exactly the two fields the successor introduces.

    Only the base builder's admissible-kind gate moves, via ``target_contract``:
    ``task`` is representable here and nowhere earlier. The snapshot rule itself
    is not re-stated -- it lives in ``SNAPSHOT_AXIS_BY_KIND``, and a task
    decision set is refused unless it pins Snapshot B and leaves Snapshot A
    unpinned.
    """
    decision_set = build_validation_decision_set_v2(
        decided_by=decided_by,
        decided_at=decided_at,
        target_contract=DECISION_SET_CONTRACT_V3,
        snapshot_b_reference=snapshot_b_reference,
        snapshot_b_sha256=snapshot_b_sha256,
        **fields,
    )
    decision_set["contract"] = DECISION_SET_CONTRACT_V3
    decision_set["schema_version"] = "0.3.0"
    decision_set["snapshot_b_reference"] = snapshot_b_reference
    decision_set["snapshot_b_sha256"] = snapshot_b_sha256
    return decision_set


def decision_set_bytes(decision_set: dict[str, Any]) -> bytes:
    return canonical_json_bytes(decision_set)
