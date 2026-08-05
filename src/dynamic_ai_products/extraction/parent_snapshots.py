"""Parent-snapshot writer under the single evaluation import edge (ADR-033).

Extraction may import only ``provenance`` and ``evaluation.source_snapshot``,
so this module cannot construct the released ``ParentObservationSnapshot``
model. It emits the snapshot as a canonical JSON document using a **closed
static pin** for the released contract identity.

Inputs are **identity pins only**. There is no snapshot or decision-set
document parameter, so a forged payload has no channel into the chain: every
input is hydrated and hash-verified from ``artifact_root`` first.

``contract_metadata_forbidden`` guards only caller channels into the emitted
snapshot's own root stamp. A hydrated decision set or Snapshot A legitimately
carries its own ``contract`` field — those are governed artifacts and remain
usable as inputs. This builder extracts only the required members and context
fields; it never merges a hydrated document into the emitted root.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path, PureWindowsPath
from typing import Any

from .errors import ExtractionError
from .input_packet import hydrate_decision_set, hydrate_snapshot

# ADR-057. A closed set, not one literal. A const pinned to @0.1.0 would have
# refused every successor decision set at the snapshot step -- the same way the
# prompt-registry const froze the registry until ADR-053 replaced it with a
# published-version set. The rule is: recognise what this code has published.
from .validation import KNOWN_DECISION_SET_CONTRACTS
from .raw_artifacts import canonical_json_bytes, require_pin

__all__ = [
    "PARENT_SNAPSHOT_CONTRACT",
    "build_snapshot_a",
    "build_snapshot_b",
    "snapshot_bytes",
]

# Closed static pin for the released contract identity, measured from
# model_contract_hash(ParentObservationSnapshot, ...). A drift test re-derives
# it and fails loudly if the released model ever changes.
PARENT_SNAPSHOT_CONTRACT: dict[str, str] = {
    "contract_id": "parent_observation_snapshot",
    "contract_version": "0.1.0",
    "contract_hash": "70b197b6154f87d4bcdb37e92e3e354b7ed5714987cb067149abfbfa37f606ea",
}

_SHA256_CHARS = set("0123456789abcdef")
_ROLES = ("product_parent", "capability_parent")



def _safe_member_reference(value: Any) -> str:
    """Syntactic safe-relative check for a member reference."""
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ExtractionError(
            "member reference must be a non-blank relative string",
            reason_code="snapshot_invalid",
        )
    candidate = Path(value)
    if (
        candidate.is_absolute()
        or value.startswith("/")
        or "\\" in value
        or "\x00" in value
        or PureWindowsPath(value).drive
        or ".." in candidate.parts
    ):
        raise ExtractionError(
            f"member reference is not a safe relative reference: {value!r}",
            reason_code="snapshot_invalid",
        )
    # Segment grammar over the ORIGINAL string, not Path.parts, which silently
    # normalizes "a//b" and "a/." away. Every segment must be a real name.
    for segment in value.split("/"):
        if segment in ("", ".", ".."):
            raise ExtractionError(
                f"member reference has an invalid path segment {segment!r}: {value!r}",
                reason_code="snapshot_invalid",
            )
    return value


def _require_original_str(payload: dict[str, Any], field: str) -> str:
    """Require an original non-blank string. No coercion of any kind."""
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ExtractionError(
            f"snapshot {field} must be an original non-blank string",
            reason_code="snapshot_invalid",
        )
    return value


def _require_canonical_date(value: Any, *, field: str) -> str:
    """Require a canonical ``YYYY-MM-DD`` date.

    ``date.fromisoformat`` accepts several ISO spellings, so round-trip
    equality is required: only the canonical extended form survives.
    """
    if not isinstance(value, str) or not value:
        raise ExtractionError(
            f"snapshot {field} must be a YYYY-MM-DD string",
            reason_code="snapshot_invalid",
        )
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ExtractionError(
            f"snapshot {field} is not a valid ISO date: {value!r}",
            reason_code="snapshot_invalid",
        ) from exc
    if parsed.isoformat() != value:
        raise ExtractionError(
            f"snapshot {field} is not canonical YYYY-MM-DD: {value!r}",
            reason_code="snapshot_invalid",
        )
    return value


def _validated_member(member: Any, *, allowed_roles: tuple[str, ...]) -> dict[str, str]:
    """Validate one member's role, reference safety, and digest form."""
    if not isinstance(member, dict):
        raise ExtractionError(
            "snapshot member is not an object", reason_code="snapshot_invalid"
        )
    role = member.get("role")
    if role not in _ROLES:
        raise ExtractionError(
            f"unknown snapshot member role: {role!r}", reason_code="snapshot_invalid"
        )
    if role not in allowed_roles:
        raise ExtractionError(
            f"member role {role!r} is not permitted in this snapshot",
            reason_code="snapshot_invalid",
        )
    digest = member.get("sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or not set(digest) <= _SHA256_CHARS
    ):
        raise ExtractionError(
            "member sha256 must be 64 lowercase hex characters",
            reason_code="snapshot_invalid",
        )
    return {
        "role": role,
        "reference": _safe_member_reference(member.get("reference")),
        "sha256": digest,
    }


def _require_member_uniqueness(members: list[dict[str, str]]) -> None:
    """No duplicate (role, reference), and no reference reused across roles."""
    keys = [(m["role"], m["reference"]) for m in members]
    if len(set(keys)) != len(keys):
        raise ExtractionError(
            "snapshot contains duplicate (role, reference) members",
            reason_code="snapshot_invalid",
        )
    references = [m["reference"] for m in members]
    if len(set(references)) != len(references):
        raise ExtractionError(
            "snapshot member references must be unique across roles",
            reason_code="snapshot_invalid",
        )


def _validate_snapshot_document(
    snapshot: dict[str, Any], *, allowed_roles: tuple[str, ...]
) -> list[dict[str, str]]:
    """Fail-closed validation of a hydrated snapshot against the released shape.

    Performed without importing evaluation.parent_observation_snapshot: the
    single permitted evaluation edge is source_snapshot only.
    """
    if snapshot.get("contract") != _pin():
        raise ExtractionError(
            "hydrated snapshot contract does not equal the closed pin identity",
            reason_code="snapshot_invalid",
        )
    for field in ("snapshot_version", "case_id", "company_id", "observation_cutoff"):
        _require_original_str(snapshot, field)
    # The carried cutoff must already be canonical, or Snapshot B would inherit
    # a malformed date that never faced the emitted-snapshot check.
    _require_canonical_date(snapshot.get("observation_cutoff"), field="observation_cutoff")

    members = snapshot.get("members")
    if not isinstance(members, list) or not members:
        raise ExtractionError(
            "snapshot members must be a non-empty list", reason_code="snapshot_invalid"
        )
    validated = [_validated_member(m, allowed_roles=allowed_roles) for m in members]

    keys = [(m["role"], m["reference"]) for m in validated]
    if keys != sorted(keys):
        raise ExtractionError(
            "snapshot members are not in canonical (role, reference) order",
            reason_code="snapshot_member_order_invalid",
        )
    _require_member_uniqueness(validated)
    return validated


def _require_decision_set_contract(decision_set: dict[str, Any]) -> None:
    """A hydrated decision set must declare its own released contract.

    This is inbound validation, not ``contract_metadata_forbidden``: a governed
    decision set legitimately carries a contract field.
    """
    if decision_set.get("contract") not in KNOWN_DECISION_SET_CONTRACTS:
        raise ExtractionError(
            "decision set must declare one of "
            f"{list(KNOWN_DECISION_SET_CONTRACTS)}",
            reason_code="validation_provenance_missing",
        )


def _pin() -> dict[str, str]:
    return require_pin(
        PARENT_SNAPSHOT_CONTRACT,
        contract_id="parent_observation_snapshot",
        contract_version="0.1.0",
    )


def _reject_caller_metadata(forbidden: dict[str, Any]) -> None:
    if forbidden:
        raise ExtractionError(
            f"unsupported inputs: {sorted(forbidden)}; the emitted snapshot's "
            "contract stamp comes from the closed static pin",
            reason_code="contract_metadata_forbidden",
        )


def _members_from_accepted(decision_set: dict[str, Any], role: str) -> list[dict[str, str]]:
    """Members are exactly the accepted artifacts named by the decision set."""
    decisions = decision_set.get("decisions")
    if not isinstance(decisions, list):
        raise ExtractionError(
            "decision set carries no decisions list",
            reason_code="validation_provenance_missing",
        )
    members: list[dict[str, str]] = []
    for entry in decisions:
        if not isinstance(entry, dict) or entry.get("decision") != "accept":
            continue
        reference = entry.get("accepted_artifact_reference")
        digest = entry.get("accepted_artifact_sha256")
        if not isinstance(reference, str) or not reference:
            raise ExtractionError(
                "accepted candidate lacks accepted_artifact_reference",
                reason_code="validation_provenance_missing",
            )
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or not set(digest) <= _SHA256_CHARS
        ):
            raise ExtractionError(
                "accepted candidate lacks a valid accepted_artifact_sha256",
                reason_code="validation_provenance_missing",
            )
        # A decision set is a governed artifact, but its references are still
        # untrusted path data: validate before one can enter any snapshot.
        members.append(
            {
                "role": role,
                "reference": _safe_member_reference(reference),
                "sha256": digest,
            }
        )
    members.sort(key=lambda m: (m["role"], m["reference"]))
    _require_member_uniqueness(members)
    return members


def _assemble(
    *,
    snapshot_version: str,
    case_id: str,
    company_id: str,
    observation_cutoff: str,
    members: list[dict[str, str]],
) -> dict[str, Any]:
    for field, value in (
        ("snapshot_version", snapshot_version),
        ("case_id", case_id),
        ("company_id", company_id),
        ("observation_cutoff", observation_cutoff),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ExtractionError(
                f"snapshot requires a non-blank {field}", reason_code="snapshot_invalid"
            )
    _require_canonical_date(observation_cutoff, field="observation_cutoff")
    if not isinstance(members, list) or not members:
        raise ExtractionError(
            "snapshot members must be a non-empty list", reason_code="snapshot_invalid"
        )
    # Re-validate at the single emission point: nothing reaches a persisted
    # snapshot without an allowed role, a safe reference, and a valid digest.
    emitted = sorted(
        (_validated_member(m, allowed_roles=_ROLES) for m in members),
        key=lambda m: (m["role"], m["reference"]),
    )
    _require_member_uniqueness(emitted)
    return {
        "snapshot_version": snapshot_version,
        "case_id": case_id,
        "company_id": company_id,
        "observation_cutoff": observation_cutoff,
        "members": emitted,
        # Set last, from the closed pin only.
        "contract": _pin(),
    }


def build_snapshot_a(
    *,
    artifact_root: str,
    product_decision_set_pin: dict[str, str],
    snapshot_version: str,
    case_id: str,
    company_id: str,
    observation_cutoff: str,
    **forbidden: Any,
) -> dict[str, Any]:
    """Snapshot A: exactly the accepted product artifacts, from a pinned set."""
    _reject_caller_metadata(forbidden)
    decision_set = hydrate_decision_set(artifact_root, product_decision_set_pin)
    _require_decision_set_contract(decision_set)
    if decision_set.get("observation_kind") != "product":
        raise ExtractionError(
            "Snapshot A requires a product validation decision set",
            reason_code="observation_kind_invalid",
        )
    members = _members_from_accepted(decision_set, "product_parent")
    if not members:
        # The released ParentObservationSnapshot rejects an empty member list
        # ("members must not be empty"), so refuse before emitting anything.
        raise ExtractionError(
            "Snapshot A requires at least one accepted product observation",
            reason_code="snapshot_invalid",
        )
    return _assemble(
        snapshot_version=snapshot_version,
        case_id=case_id,
        company_id=company_id,
        observation_cutoff=observation_cutoff,
        members=members,
    )


def build_snapshot_b(
    *,
    artifact_root: str,
    snapshot_a_pin: dict[str, str],
    capability_decision_set_pin: dict[str, str],
    snapshot_version: str,
    **forbidden: Any,
) -> dict[str, Any]:
    """Snapshot B: A's product members byte-unchanged plus accepted capabilities.

    An empty accepted-capability set is legal; B remains a distinct persisted
    instance identified by its own version, reference, and digest.
    """
    _reject_caller_metadata(forbidden)
    snapshot_a = hydrate_snapshot(artifact_root, snapshot_a_pin)
    # Fail-closed shape validation BEFORE any member is carried forward.
    # Snapshot A may carry product_parent members only.
    a_members = _validate_snapshot_document(
        snapshot_a, allowed_roles=("product_parent",)
    )
    decision_set = hydrate_decision_set(artifact_root, capability_decision_set_pin)
    _require_decision_set_contract(decision_set)
    if decision_set.get("observation_kind") != "capability":
        raise ExtractionError(
            "Snapshot B requires a capability validation decision set",
            reason_code="observation_kind_invalid",
        )
    if decision_set.get("snapshot_a_reference") != snapshot_a_pin.get("reference") or (
        decision_set.get("snapshot_a_sha256") != snapshot_a_pin.get("sha256")
    ):
        raise ExtractionError(
            "capability decision set pins a different Snapshot A",
            reason_code="capability_decision_snapshot_a_mismatch",
        )

    if snapshot_version == snapshot_a.get("snapshot_version"):
        raise ExtractionError(
            "Snapshot B must have a distinct snapshot_version",
            reason_code="parent_context_wrong_snapshot",
        )
    # Carried byte-unchanged from the validated members. Context fields are the
    # original strings from A; no coercion is applied.
    carried = [dict(m) for m in a_members]
    return _assemble(
        snapshot_version=snapshot_version,
        case_id=_require_original_str(snapshot_a, "case_id"),
        company_id=_require_original_str(snapshot_a, "company_id"),
        observation_cutoff=_require_original_str(snapshot_a, "observation_cutoff"),
        members=carried + _members_from_accepted(decision_set, "capability_parent"),
    )


def snapshot_bytes(snapshot: dict[str, Any]) -> bytes:
    return canonical_json_bytes(snapshot)
