"""Stage-scoped extraction input packet and snapshot reconciliation (ADR-033).

The packet is the bounded, hash-bound provider input. It is stage-scoped: the
product stage forbids parent context, the capability stage requires the
Snapshot A identity plus product-validation provenance, and the task stage
requires the Snapshot B identity plus both validation provenances.

**Snapshot and decision-set content is never caller-supplied.** Callers pass
identity pins only; this module re-reads the bytes from ``artifact_root``,
verifies a safe relative reference, the SHA-256, and (for snapshots) the
declared ``snapshot_version`` before anything else happens. There is no
document parameter through which a forged payload could enter.

**Routing is by pinned identity, never by member shape.** A and B are distinct
persisted instances. A legitimate Snapshot B may carry zero accepted
capability parents while still carrying its product-parent carry-over, so role
presence can never be a discriminator.

Hash-verifying a snapshot proves it intact, not authorized. Every snapshot is
reconciled against the decision sets that authorized it **before** any parent
context is derived.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path, PureWindowsPath
from typing import Any

from .errors import ExtractionError
from .raw_artifacts import canonical_json_bytes, sha256_bytes

__all__ = [
    "CORPUS_SCOPE_SEC_ONLY",
    "PACKET_CONTRACT",
    "STAGES",
    "build_extraction_input_packet",
    "derive_parent_context",
    "hydrate_decision_set",
    "hydrate_snapshot",
    "packet_bytes",
    "reconcile_snapshot_a",
    "reconcile_snapshot_b",
]

PACKET_CONTRACT = "extraction_input_packet@0.1.0"
CORPUS_SCOPE_SEC_ONLY = "sec_only_partial"

STAGES: tuple[str, ...] = (
    "product_extraction",
    "capability_extraction",
    "task_extraction",
)

_COMPANY_ID_RE = re.compile(r"^CIK[0-9]{10}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _require_sha256(value: Any, what: str, code: str = "pin_invalid") -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ExtractionError(
            f"{what} must be 64 lowercase hex characters", reason_code=code
        )
    return value


# --- Safe reference resolution and hydration ---------------------------------


def _safe_target(artifact_root: str | Path, reference: Any, code: str) -> Path:
    """Resolve a relative reference that must stay inside ``artifact_root``."""
    if not isinstance(reference, str) or not reference.strip():
        raise ExtractionError(
            "artifact reference must be a non-empty string", reason_code=code
        )
    candidate = Path(reference)
    if candidate.is_absolute() or reference.startswith("/") or "\\" in reference:
        raise ExtractionError(
            f"artifact reference must be relative: {reference}", reason_code=code
        )
    # A drive-qualified reference such as "C:/x" is NOT absolute on POSIX, has no
    # ".." part, and resolves inside the root as a directory literally named
    # "C:" - so neither the absolute nor the escape check catches it.
    if PureWindowsPath(reference).drive:
        raise ExtractionError(
            f"artifact reference must not be drive-qualified: {reference}",
            reason_code=code,
        )
    if ".." in candidate.parts:
        raise ExtractionError(
            f"artifact reference must not traverse upward: {reference}",
            reason_code=code,
        )
    root = Path(artifact_root).resolve()
    target = root / candidate
    if target.is_symlink():
        raise ExtractionError(
            f"artifact reference must not be a symlink: {reference}", reason_code=code
        )
    resolved = target.resolve()
    if resolved != root and not str(resolved).startswith(str(root) + os.sep):
        raise ExtractionError(
            f"artifact reference escapes the artifact root: {reference}",
            reason_code=code,
        )
    return target


def _hydrate(
    artifact_root: str | Path,
    pin: Any,
    *,
    what: str,
    unsafe_code: str,
    sha_code: str,
) -> dict[str, Any]:
    """Read, hash-verify, and parse an artifact named only by its pin."""
    if not isinstance(pin, dict):
        raise ExtractionError(f"{what} pin must be a mapping", reason_code=unsafe_code)
    target = _safe_target(artifact_root, pin.get("reference"), unsafe_code)
    expected = _require_sha256(pin.get("sha256"), f"{what} sha256", sha_code)
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise ExtractionError(
            f"{what} is unreadable: {pin.get('reference')}", reason_code=sha_code
        ) from exc
    observed = sha256_bytes(raw)
    if observed != expected:
        raise ExtractionError(
            f"{what} bytes do not match the pinned sha256",
            reason_code=sha_code,
            detail=f"expected {expected}, observed {observed}",
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ExtractionError(
            f"{what} is not valid UTF-8 JSON", reason_code=sha_code
        ) from exc
    if not isinstance(payload, dict):
        raise ExtractionError(f"{what} is not an object", reason_code=sha_code)
    return payload


def hydrate_snapshot(artifact_root: str | Path, pin: Any) -> dict[str, Any]:
    """Load a parent snapshot from its pin and verify reference, sha, version."""
    payload = _hydrate(
        artifact_root,
        pin,
        what="parent snapshot",
        unsafe_code="snapshot_reference_unsafe",
        sha_code="snapshot_pin_sha_mismatch",
    )
    # The pinned version must be a well-formed non-blank string BEFORE any
    # comparison. Otherwise None-on-both-sides would compare equal and a
    # versionless snapshot would authenticate itself.
    pinned = pin.get("snapshot_version")
    if not isinstance(pinned, str) or not pinned.strip():
        raise ExtractionError(
            "pinned snapshot_version must be a non-blank string",
            reason_code="snapshot_pin_version_mismatch",
            detail=f"pinned={pinned!r}",
        )
    declared = payload.get("snapshot_version")
    if declared != pinned:
        raise ExtractionError(
            "snapshot_version does not match the pinned version",
            reason_code="snapshot_pin_version_mismatch",
            detail=f"pinned={pinned!r} parsed={declared!r}",
        )
    return payload


def hydrate_decision_set(artifact_root: str | Path, pin: Any) -> dict[str, Any]:
    """Load a validation decision set from its pin. Never caller-supplied."""
    return _hydrate(
        artifact_root,
        pin,
        what="validation decision set",
        unsafe_code="decision_set_reference_unsafe",
        sha_code="decision_set_pin_sha_mismatch",
    )


# --- Snapshot member handling ------------------------------------------------


def _members_of(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    members = snapshot.get("members")
    if not isinstance(members, list):
        raise ExtractionError(
            "snapshot carries no members list", reason_code="snapshot_invalid"
        )
    out: list[dict[str, Any]] = []
    for member in members:
        if not isinstance(member, dict):
            raise ExtractionError(
                "snapshot member is not an object", reason_code="snapshot_invalid"
            )
        role = member.get("role")
        if role not in {"product_parent", "capability_parent"}:
            raise ExtractionError(
                f"unknown snapshot member role: {role!r}", reason_code="snapshot_invalid"
            )
        out.append(
            {
                "role": role,
                "reference": member.get("reference"),
                "sha256": _require_sha256(member.get("sha256"), "member sha256"),
            }
        )
    keys = [(m["role"], str(m["reference"])) for m in out]
    if keys != sorted(keys):
        raise ExtractionError(
            "snapshot members are not in canonical order",
            reason_code="snapshot_member_order_invalid",
        )
    if len(set(keys)) != len(keys):
        raise ExtractionError(
            "snapshot contains duplicate members", reason_code="snapshot_invalid"
        )
    return out


def _triples(members: list[dict[str, Any]], role: str) -> set[tuple[str, str, str]]:
    return {
        (m["role"], str(m["reference"]), m["sha256"]) for m in members if m["role"] == role
    }


def _accepted_triples(decision_set: dict[str, Any], role: str) -> set[tuple[str, str, str]]:
    decisions = decision_set.get("decisions")
    if not isinstance(decisions, list):
        raise ExtractionError(
            "decision set carries no decisions list",
            reason_code="validation_provenance_missing",
        )
    out: set[tuple[str, str, str]] = set()
    for entry in decisions:
        if not isinstance(entry, dict):
            raise ExtractionError(
                "decision entry is not an object",
                reason_code="validation_provenance_missing",
            )
        if entry.get("decision") != "accept":
            continue
        reference = entry.get("accepted_artifact_reference")
        if not isinstance(reference, str) or not reference:
            raise ExtractionError(
                "accepted candidate lacks accepted_artifact_reference",
                reason_code="validation_provenance_missing",
            )
        digest = _require_sha256(
            entry.get("accepted_artifact_sha256"), "accepted_artifact_sha256"
        )
        out.add((role, reference, digest))
    return out


def _verify_member_artifacts(artifact_root: str | Path, members: list[dict[str, Any]]) -> None:
    """E5 - every referenced member artifact re-reads to its recorded SHA-256."""
    for member in members:
        target = _safe_target(
            artifact_root, member["reference"], "parent_member_hash_mismatch"
        )
        try:
            observed = sha256_bytes(target.read_bytes())
        except OSError as exc:
            raise ExtractionError(
                f"parent member artifact is unreadable: {member['reference']}",
                reason_code="parent_member_hash_mismatch",
            ) from exc
        if observed != member["sha256"]:
            raise ExtractionError(
                f"parent member artifact digest drifted: {member['reference']}",
                reason_code="parent_member_hash_mismatch",
                detail=f"expected {member['sha256']}, observed {observed}",
            )


# --- The five equalities -----------------------------------------------------


def _require_product_only(members: list[dict[str, Any]]) -> None:
    """Snapshot A is product-only *by definition*, so a capability member proves
    the supplied snapshot is not an A.

    This is not the forbidden role-presence discriminator. Absence of capability
    members never proves a snapshot is an A — a legal Snapshot B may carry zero
    of them. Only *presence* is conclusive, and only in the negative direction.
    Without this check E1 alone accepts a Snapshot B as Snapshot A, because B
    carries A's product members byte-for-byte by construction (E3).
    """
    foreign = sorted({m["role"] for m in members if m["role"] != "product_parent"})
    if foreign:
        raise ExtractionError(
            f"Snapshot A must carry product parents only; found {foreign}",
            reason_code="parent_context_wrong_snapshot",
        )


def reconcile_snapshot_a(
    *,
    artifact_root: str | Path,
    snapshot_a: dict[str, Any],
    product_decision_set: dict[str, Any],
) -> list[dict[str, Any]]:
    """E1 + E5. Returns A's verified members."""
    members = _members_of(snapshot_a)
    _require_product_only(members)
    expected = _accepted_triples(product_decision_set, "product_parent")
    observed = _triples(members, "product_parent")
    if observed != expected:
        raise ExtractionError(
            "Snapshot A product members do not equal the accepted product artifacts",
            reason_code="snapshot_a_product_members_mismatch",
            detail=f"missing={sorted(expected - observed)} extra={sorted(observed - expected)}",
        )
    _verify_member_artifacts(artifact_root, members)
    return members


def reconcile_snapshot_b(
    *,
    artifact_root: str | Path,
    snapshot_a: dict[str, Any],
    snapshot_a_pin: dict[str, str],
    snapshot_b: dict[str, Any],
    product_decision_set: dict[str, Any],
    capability_decision_set: dict[str, Any],
) -> list[dict[str, Any]]:
    """All five equalities for the task stage. Returns B's verified members."""
    # E1 - re-run here on purpose: E2-E5 are internal to the A/B/capability
    # triple and cannot detect a self-consistent forged A.
    a_members = _members_of(snapshot_a)
    _require_product_only(a_members)
    expected_products = _accepted_triples(product_decision_set, "product_parent")
    observed_products_a = _triples(a_members, "product_parent")
    if observed_products_a != expected_products:
        raise ExtractionError(
            "Snapshot A product members do not equal the accepted product artifacts",
            reason_code="snapshot_a_product_members_mismatch",
        )

    # E2 - the capability decision set's pinned A must be the loaded A.
    pinned_ref = capability_decision_set.get("snapshot_a_reference")
    pinned_sha = capability_decision_set.get("snapshot_a_sha256")
    if pinned_ref != snapshot_a_pin.get("reference") or pinned_sha != snapshot_a_pin.get("sha256"):
        raise ExtractionError(
            "capability decision set pins a different Snapshot A",
            reason_code="capability_decision_snapshot_a_mismatch",
        )

    b_members = _members_of(snapshot_b)

    # E3 - B's product members equal A's byte-for-byte.
    if _triples(b_members, "product_parent") != observed_products_a:
        raise ExtractionError(
            "Snapshot B product members do not equal Snapshot A product members",
            reason_code="snapshot_b_product_carryover_mismatch",
        )

    # E4 - B's capability members equal the accepted set. Exactly-empty is legal.
    expected_caps = _accepted_triples(capability_decision_set, "capability_parent")
    observed_caps = _triples(b_members, "capability_parent")
    if observed_caps != expected_caps:
        raise ExtractionError(
            "Snapshot B capability members do not equal the accepted capability artifacts",
            reason_code="snapshot_b_capability_members_mismatch",
            detail=f"missing={sorted(expected_caps - observed_caps)} extra={sorted(observed_caps - expected_caps)}",
        )

    _verify_member_artifacts(artifact_root, b_members)
    return b_members


# --- Parent context ----------------------------------------------------------


def derive_parent_context(
    *,
    artifact_root: str | Path,
    members: list[dict[str, Any]],
    role: str,
) -> list[dict[str, Any]]:
    """Derive parent entries only from re-read, hash-verified members."""
    id_field = {
        "product_parent": "product_observation_id",
        "capability_parent": "capability_observation_id",
    }[role]
    out: list[dict[str, Any]] = []
    for member in members:
        if member["role"] != role:
            continue
        target = _safe_target(
            artifact_root, member["reference"], "parent_member_hash_mismatch"
        )
        payload_bytes = target.read_bytes()
        if sha256_bytes(payload_bytes) != member["sha256"]:
            raise ExtractionError(
                f"parent member artifact digest drifted: {member['reference']}",
                reason_code="parent_member_hash_mismatch",
            )
        payload = json.loads(payload_bytes.decode("utf-8"))
        observation_id = payload.get(id_field)
        if not isinstance(observation_id, str) or not observation_id:
            raise ExtractionError(
                f"accepted observation lacks {id_field}",
                reason_code="parent_id_not_in_snapshot",
            )
        out.append(
            {
                "observation_id": observation_id,
                "reference": member["reference"],
                "sha256": member["sha256"],
                "payload": payload,
            }
        )
    out.sort(key=lambda entry: (entry["observation_id"], entry["reference"]))
    return out


# --- Packet construction -----------------------------------------------------


def _admissible(
    passages: list[dict[str, Any]],
    document_publication_dates: dict[str, str],
    observation_cutoff_date: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Admissibility is nonblank text plus the locked temporal rule.

    No numeric length threshold exists: a one-character nonblank passage is
    admissible. Every drop is recorded with its reason.
    """
    kept: list[dict[str, Any]] = []
    blank_drops: list[dict[str, Any]] = []
    temporal_drops: list[dict[str, Any]] = []
    for passage in passages:
        text = passage.get("text")
        if not isinstance(text, str) or not text.strip():
            blank_drops.append(
                {"passage_id": passage.get("passage_id"), "reason": "blank_text"}
            )
            continue
        published = document_publication_dates.get(str(passage.get("source_id")))
        if not published or published > observation_cutoff_date:
            temporal_drops.append(
                {"passage_id": passage.get("passage_id"), "reason": "temporally_invalid"}
            )
            continue
        kept.append(passage)
    kept.sort(
        key=lambda p: (
            str(p.get("source_id")),
            int(p.get("start_offset") or 0),
            int(p.get("end_offset") or 0),
            str(p.get("passage_id")),
        )
    )
    return kept, blank_drops, temporal_drops


def _provenance_of(pin: dict[str, str], decision_set: dict[str, Any]) -> dict[str, Any]:
    return {
        "reference": pin["reference"],
        "sha256": pin["sha256"],
        "raw_artifact_sha256": decision_set.get("raw_artifact_sha256"),
        "candidate_collection_sha256": decision_set.get("candidate_collection_sha256"),
    }


def build_extraction_input_packet(
    *,
    stage: str,
    company_id: str,
    observation_cutoff_date: str,
    passages: list[dict[str, Any]],
    document_publication_dates: dict[str, str],
    coverage_artifact: dict[str, str],
    source_snapshot_manifest: dict[str, str],
    artifact_root: str | Path | None = None,
    snapshot_a_pin: dict[str, str] | None = None,
    snapshot_b_pin: dict[str, str] | None = None,
    product_decision_set_pin: dict[str, str] | None = None,
    capability_decision_set_pin: dict[str, str] | None = None,
    **forbidden: Any,
) -> dict[str, Any]:
    """Build a stage-scoped packet from identity pins only.

    There is no snapshot or decision-set document parameter: content is
    hydrated here from ``artifact_root`` and verified before use.
    """
    if forbidden:
        raise ExtractionError(
            f"unsupported packet inputs: {sorted(forbidden)}; snapshots and decision "
            "sets are hydrated from pins and parent ids are derived, never supplied",
            reason_code="parent_id_not_in_snapshot",
        )
    if stage not in STAGES:
        raise ExtractionError(
            f"unknown extraction stage: {stage!r}", reason_code="packet_stage_invalid"
        )
    if not _COMPANY_ID_RE.fullmatch(str(company_id)):
        raise ExtractionError(
            "company_id must match ^CIK[0-9]{10}$", reason_code="packet_context_invalid"
        )
    if not _DATE_RE.fullmatch(str(observation_cutoff_date)):
        raise ExtractionError(
            "observation_cutoff_date must be YYYY-MM-DD",
            reason_code="packet_context_invalid",
        )
    _require_sha256(coverage_artifact.get("sha256"), "coverage sha256")
    _require_sha256(source_snapshot_manifest.get("sha256"), "source snapshot sha256")

    admissible, blank_drops, temporal_drops = _admissible(
        list(passages), document_publication_dates, observation_cutoff_date
    )

    parent_context: dict[str, Any] | None = None
    product_provenance: dict[str, Any] | None = None
    capability_provenance: dict[str, Any] | None = None

    if stage == "product_extraction":
        if any(
            value is not None
            for value in (
                snapshot_a_pin,
                snapshot_b_pin,
                product_decision_set_pin,
                capability_decision_set_pin,
            )
        ):
            raise ExtractionError(
                "the product stage forbids parent context and validation provenance",
                reason_code="parent_context_forbidden",
            )

    elif stage == "capability_extraction":
        if snapshot_b_pin is not None or capability_decision_set_pin is not None:
            raise ExtractionError(
                "the capability stage accepts only the Snapshot A identity",
                reason_code="parent_context_wrong_snapshot",
            )
        if snapshot_a_pin is None:
            raise ExtractionError(
                "the capability stage requires the Snapshot A identity",
                reason_code="parent_context_missing",
            )
        if product_decision_set_pin is None:
            raise ExtractionError(
                "the capability stage requires product-validation provenance",
                reason_code="validation_provenance_missing",
            )
        snapshot_a = hydrate_snapshot(artifact_root, snapshot_a_pin)
        product_decisions = hydrate_decision_set(artifact_root, product_decision_set_pin)
        members = reconcile_snapshot_a(
            artifact_root=artifact_root,
            snapshot_a=snapshot_a,
            product_decision_set=product_decisions,
        )
        parent_context = {
            "snapshot": dict(snapshot_a_pin),
            "product_parents": derive_parent_context(
                artifact_root=artifact_root, members=members, role="product_parent"
            ),
        }
        product_provenance = _provenance_of(product_decision_set_pin, product_decisions)

    else:  # task_extraction
        if snapshot_b_pin is None:
            raise ExtractionError(
                "the task stage requires the Snapshot B identity",
                reason_code="parent_context_missing",
            )
        if snapshot_a_pin is None:
            raise ExtractionError(
                "the task stage requires Snapshot A for reconciliation",
                reason_code="parent_context_missing",
            )
        if (
            snapshot_a_pin.get("reference") == snapshot_b_pin.get("reference")
            or snapshot_a_pin.get("sha256") == snapshot_b_pin.get("sha256")
            or snapshot_a_pin.get("snapshot_version") == snapshot_b_pin.get("snapshot_version")
        ):
            raise ExtractionError(
                "Snapshot A and Snapshot B must be distinct pinned identities",
                reason_code="parent_context_wrong_snapshot",
            )
        if product_decision_set_pin is None:
            raise ExtractionError(
                "the task stage requires product-validation provenance",
                reason_code="validation_provenance_missing",
            )
        if capability_decision_set_pin is None:
            raise ExtractionError(
                "the task stage requires capability-validation provenance",
                reason_code="validation_provenance_missing",
            )
        snapshot_a = hydrate_snapshot(artifact_root, snapshot_a_pin)
        snapshot_b = hydrate_snapshot(artifact_root, snapshot_b_pin)
        product_decisions = hydrate_decision_set(artifact_root, product_decision_set_pin)
        capability_decisions = hydrate_decision_set(
            artifact_root, capability_decision_set_pin
        )
        members = reconcile_snapshot_b(
            artifact_root=artifact_root,
            snapshot_a=snapshot_a,
            snapshot_a_pin=snapshot_a_pin,
            snapshot_b=snapshot_b,
            product_decision_set=product_decisions,
            capability_decision_set=capability_decisions,
        )
        parent_context = {
            "snapshot": dict(snapshot_b_pin),
            "product_parents": derive_parent_context(
                artifact_root=artifact_root, members=members, role="product_parent"
            ),
            "capability_parents": derive_parent_context(
                artifact_root=artifact_root, members=members, role="capability_parent"
            ),
        }
        product_provenance = _provenance_of(product_decision_set_pin, product_decisions)
        capability_provenance = _provenance_of(
            capability_decision_set_pin, capability_decisions
        )

    return {
        "contract": PACKET_CONTRACT,
        "schema_version": "0.1.0",
        "stage": stage,
        "company_id": company_id,
        "observation_cutoff_date": observation_cutoff_date,
        "corpus_scope": CORPUS_SCOPE_SEC_ONLY,
        "coverage_artifact": dict(coverage_artifact),
        "source_snapshot_manifest": dict(source_snapshot_manifest),
        "passages": admissible,
        "filter_ledger": {
            "input_passage_count": len(passages),
            "blank_drop_count": len(blank_drops),
            "temporal_drop_count": len(temporal_drops),
            "surviving_count": len(admissible),
            "blank_drops": blank_drops,
            "temporal_drops": temporal_drops,
        },
        "parent_context": parent_context,
        "product_validation_provenance": product_provenance,
        "capability_validation_provenance": capability_provenance,
    }


def packet_bytes(packet: dict[str, Any]) -> bytes:
    return canonical_json_bytes(packet)
