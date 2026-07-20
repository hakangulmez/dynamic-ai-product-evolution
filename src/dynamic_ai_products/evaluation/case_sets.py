"""Case-set manifest and membership-event handling (Slice 3).

Read-side behavior plus pure validation/hash functions only: load one
case-set manifest (JSON) or one membership-event log (JSONL) under an
explicit evaluation root with the strict parsing discipline of Slice 2;
compute the deterministic case-set snapshot hash; verify that a successor
manifest is fully explained by an ordered event sequence
(verification-form reconstruction — ``MembershipEvent`` carries no
``input_packet_hash``, so complete memberships are never derived from
events alone); and verify that one event log is an exact byte-prefix
extension of another.

No writers, no persistence, no overwrite protection, no exposure model,
no access control, no automatic partition movement, no case-ID-to-path
resolution, and no CLI live here. Resolved filesystem paths are used only
for containment and reading, never as artifact identity; diagnostics use
deterministic root-relative POSIX references and never include file
contents.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Literal, Sequence

from pydantic import ValidationError as PydanticValidationError

from .cases import InvalidEvaluationRootError
from .contracts import canonical_contract_bytes
from .models import CaseSetManifest, MembershipEvent
from ..universe.io_utils import sha256_bytes

ConflictKind = Literal[
    "duplicate_suite_membership",
    "version_chain_mismatch",
    "same_version_change",
    "unknown_case_reference",
    "stale_old_partition",
    "contradictory_suite_change",
    "unexplained_membership_change",
    "unexplained_event",
    "append_only_prefix_violation",
]


class CaseSetLoadError(Exception):
    """Base class for case-set artifact loading failures; never raised directly."""

    def __init__(self, message: str, *, artifact_reference: str | None = None) -> None:
        super().__init__(message)
        self.artifact_reference = artifact_reference


class CaseSetArtifactNotFoundError(CaseSetLoadError):
    """The contained case-set artifact path does not exist."""


class CaseSetArtifactNotAFileError(CaseSetLoadError):
    """The contained case-set artifact path exists but is not a regular file."""


class CaseSetPathEscapeError(CaseSetLoadError):
    """The requested case-set artifact path resolves outside the root."""


class CaseSetReadError(CaseSetLoadError):
    """Reading the case-set artifact bytes failed."""


class CaseSetDecodeError(CaseSetLoadError):
    """The case-set artifact bytes are not valid UTF-8."""


class CaseSetJsonError(CaseSetLoadError):
    """The case-set artifact text is not acceptable strict JSON."""

    def __init__(
        self,
        message: str,
        *,
        artifact_reference: str | None = None,
        duplicate_key: str | None = None,
        constant_name: str | None = None,
        line_number: int | None = None,
    ) -> None:
        super().__init__(message, artifact_reference=artifact_reference)
        self.duplicate_key = duplicate_key
        self.constant_name = constant_name
        self.line_number = line_number


class CaseSetTopLevelTypeError(CaseSetLoadError):
    """A parsed case-set document or event line is not a JSON object."""

    def __init__(
        self,
        message: str,
        *,
        artifact_reference: str | None = None,
        observed_type: str | None = None,
        line_number: int | None = None,
    ) -> None:
        super().__init__(message, artifact_reference=artifact_reference)
        self.observed_type = observed_type
        self.line_number = line_number


class CaseSetModelValidationError(CaseSetLoadError):
    """A case-set document or event line failed model/contract validation."""

    def __init__(
        self,
        message: str,
        *,
        artifact_reference: str | None = None,
        field_locations: tuple[str, ...] = (),
        error_types: tuple[str, ...] = (),
        line_number: int | None = None,
    ) -> None:
        super().__init__(message, artifact_reference=artifact_reference)
        self.field_locations = field_locations
        self.error_types = error_types
        self.line_number = line_number


class CaseSetConsistencyError(Exception):
    """A deterministic case-set membership or append-only consistency conflict."""

    def __init__(
        self,
        message: str,
        *,
        conflict_kind: ConflictKind,
        case_id: str | None = None,
        event_index: int | None = None,
        artifact_reference: str | None = None,
        related_artifact_reference: str | None = None,
    ) -> None:
        super().__init__(message)
        self.conflict_kind = conflict_kind
        self.case_id = case_id
        self.event_index = event_index
        self.artifact_reference = artifact_reference
        self.related_artifact_reference = related_artifact_reference


class _DuplicateKeyControl(Exception):
    """Private parser-control signal for a duplicate JSON object key."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


class _NonFiniteControl(Exception):
    """Private parser-control signal for a non-finite JSON number."""

    def __init__(self, constant_name: str) -> None:
        super().__init__(constant_name)
        self.constant_name = constant_name


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise _DuplicateKeyControl(key)
        seen.add(key)
        result[key] = value
    return result


def _reject_non_finite_constant(name: str) -> Any:
    raise _NonFiniteControl(name)


def _validate_eval_root(eval_root: str | Path) -> Path:
    if not isinstance(eval_root, (str, Path)):
        raise InvalidEvaluationRootError(
            "eval_root must be an explicit str or Path evaluation root",
            observed_type=type(eval_root).__name__,
        )
    if isinstance(eval_root, str) and eval_root == "":
        raise InvalidEvaluationRootError(
            "eval_root must not be an empty string; supply the evaluation root explicitly",
            supplied_root="",
        )
    root = Path(eval_root)
    if not root.exists():
        raise InvalidEvaluationRootError(
            f"evaluation root {str(eval_root)!r} does not exist",
            supplied_root=str(eval_root),
        )
    if not root.is_dir():
        raise InvalidEvaluationRootError(
            f"evaluation root {str(eval_root)!r} is not a directory",
            supplied_root=str(eval_root),
        )
    return root.resolve()


def _resolve_contained_path(
    artifact_path: str | Path, resolved_root: Path
) -> tuple[Path, str]:
    """Resolve one requested path and require containment inside the root.

    Component-aware containment on resolved paths; on escape only the
    requested reference is reported, never the resolved outside target.
    """
    requested = Path(artifact_path)
    candidate = requested if requested.is_absolute() else resolved_root / requested
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise CaseSetPathEscapeError(
            f"case-set artifact path {str(artifact_path)!r} resolves outside "
            "the evaluation root",
            artifact_reference=str(artifact_path),
        )
    reference = resolved.relative_to(resolved_root).as_posix()
    if not resolved.exists():
        raise CaseSetArtifactNotFoundError(
            f"case-set artifact {reference!r} does not exist under the evaluation root",
            artifact_reference=reference,
        )
    if not resolved.is_file():
        raise CaseSetArtifactNotAFileError(
            f"case-set artifact {reference!r} is not a regular file",
            artifact_reference=reference,
        )
    return resolved, reference


def _read_artifact_bytes(resolved: Path, reference: str) -> bytes:
    try:
        return resolved.read_bytes()
    except OSError as exc:
        raise CaseSetReadError(
            f"failed to read case-set artifact {reference!r}",
            artifact_reference=reference,
        ) from exc


def _decode_strict_utf8(raw: bytes, reference: str) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CaseSetDecodeError(
            f"case-set artifact {reference!r} is not valid UTF-8",
            artifact_reference=reference,
        ) from exc


def _assert_finite_numbers(
    payload: Any, reference: str, line_number: int | None
) -> None:
    stack = [payload]
    while stack:
        value = stack.pop()
        if isinstance(value, float) and not math.isfinite(value):
            name = "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
            raise CaseSetJsonError(
                f"case-set artifact {reference!r} contains a non-finite JSON "
                f"number ({name})",
                artifact_reference=reference,
                constant_name=name,
                line_number=line_number,
            )
        elif isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)


def _parse_strict_json_value(
    text: str, reference: str, line_number: int | None
) -> Any:
    location = "" if line_number is None else f" line {line_number}"
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except json.JSONDecodeError as exc:
        raise CaseSetJsonError(
            f"case-set artifact {reference!r}{location} is not valid JSON: "
            f"{exc.msg} (column {exc.colno})",
            artifact_reference=reference,
            line_number=line_number,
        ) from exc
    except _DuplicateKeyControl as exc:
        raise CaseSetJsonError(
            f"case-set artifact {reference!r}{location} contains a duplicate "
            f"JSON object key {exc.key!r}",
            artifact_reference=reference,
            duplicate_key=exc.key,
            line_number=line_number,
        ) from exc
    except _NonFiniteControl as exc:
        raise CaseSetJsonError(
            f"case-set artifact {reference!r}{location} contains the non-JSON "
            f"constant {exc.constant_name}",
            artifact_reference=reference,
            constant_name=exc.constant_name,
            line_number=line_number,
        ) from exc
    _assert_finite_numbers(payload, reference, line_number)
    return payload


def _require_object(
    payload: Any, reference: str, line_number: int | None
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        location = "" if line_number is None else f" line {line_number}"
        raise CaseSetTopLevelTypeError(
            f"case-set artifact {reference!r}{location} must be a JSON object, "
            f"got {type(payload).__name__}",
            artifact_reference=reference,
            observed_type=type(payload).__name__,
            line_number=line_number,
        )
    return payload


def _validate_model(
    model_cls: type, payload: dict[str, Any], reference: str, line_number: int | None
) -> Any:
    try:
        return model_cls.model_validate(payload)
    except PydanticValidationError as exc:
        pairs = sorted(
            ("/".join(str(part) for part in error["loc"]), error["type"])
            for error in exc.errors()
        )
        locations = tuple(location for location, _ in pairs)
        error_types = tuple(error_type for _, error_type in pairs)
        location = "" if line_number is None else f" line {line_number}"
        raise CaseSetModelValidationError(
            f"case-set artifact {reference!r}{location} failed "
            f"{model_cls.__name__} validation at location(s): "
            f"{', '.join(locations) or '<root>'}",
            artifact_reference=reference,
            field_locations=locations,
            error_types=error_types,
            line_number=line_number,
        ) from exc


def _first_duplicate(values: Sequence[str]) -> str | None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            return value
        seen.add(value)
    return None


def _require_unique_membership_suites(
    manifest: CaseSetManifest, artifact_reference: str | None
) -> None:
    for entry in manifest.entries:
        duplicate = _first_duplicate(entry.suites)
        if duplicate is not None:
            raise CaseSetConsistencyError(
                f"case membership {entry.case_id!r} lists suite "
                f"{duplicate!r} more than once",
                conflict_kind="duplicate_suite_membership",
                case_id=entry.case_id,
                artifact_reference=artifact_reference,
            )


def _require_unique_event_suites(
    event: MembershipEvent,
    event_index: int,
    artifact_reference: str | None,
) -> None:
    for label, values in (("added", event.added_suites), ("removed", event.removed_suites)):
        duplicate = _first_duplicate(values)
        if duplicate is not None:
            raise CaseSetConsistencyError(
                f"membership event {event_index} for case {event.case_id!r} "
                f"lists {label} suite {duplicate!r} more than once",
                conflict_kind="duplicate_suite_membership",
                case_id=event.case_id,
                event_index=event_index,
                artifact_reference=artifact_reference,
            )


def _parse_membership_events(
    raw: bytes, reference: str
) -> tuple[MembershipEvent, ...]:
    if raw == b"":
        return ()
    text = _decode_strict_utf8(raw, reference)
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    events: list[MembershipEvent] = []
    for index, line in enumerate(lines):
        line_number = index + 1
        if not line or not line.strip():
            raise CaseSetJsonError(
                f"case-set artifact {reference!r} line {line_number} is blank "
                "or whitespace-only; event logs may not contain blank lines",
                artifact_reference=reference,
                line_number=line_number,
            )
        payload = _parse_strict_json_value(line, reference, line_number)
        payload = _require_object(payload, reference, line_number)
        event = _validate_model(MembershipEvent, payload, reference, line_number)
        _require_unique_event_suites(event, index, reference)
        events.append(event)
    return tuple(events)


def load_case_set_manifest(
    manifest_path: str | Path, *, eval_root: str | Path
) -> CaseSetManifest:
    """Load and validate one case-set manifest under the explicit root.

    ``eval_root`` is explicit and required with no default. Every
    successful call returns a fresh frozen ``CaseSetManifest``; duplicate
    suite entries in any membership are rejected as a consistency conflict.
    """
    resolved_root = _validate_eval_root(eval_root)
    resolved, reference = _resolve_contained_path(manifest_path, resolved_root)
    raw = _read_artifact_bytes(resolved, reference)
    text = _decode_strict_utf8(raw, reference)
    payload = _parse_strict_json_value(text, reference, None)
    payload = _require_object(payload, reference, None)
    manifest = _validate_model(CaseSetManifest, payload, reference, None)
    _require_unique_membership_suites(manifest, reference)
    return manifest


def load_membership_events(
    events_path: str | Path, *, eval_root: str | Path
) -> tuple[MembershipEvent, ...]:
    """Load one membership-event JSONL log in physical line order.

    A completely empty file yields ``()``. One final line terminator is
    permitted; blank or whitespace-only lines are rejected; every line must
    be one strict JSON object validating as a ``MembershipEvent``. Events
    are never reordered.
    """
    resolved_root = _validate_eval_root(eval_root)
    resolved, reference = _resolve_contained_path(events_path, resolved_root)
    raw = _read_artifact_bytes(resolved, reference)
    return _parse_membership_events(raw, reference)


def case_set_snapshot_hash(manifest: CaseSetManifest) -> str:
    """Deterministic SHA-256 snapshot hash of one case-set manifest.

    Hashes the canonical JSON serialization (recursively sorted object
    keys, compact separators, UTF-8) of ``model_dump(mode="json",
    exclude_unset=True)``, including the nested contract metadata and
    preserving entry and suite order. No filesystem I/O, mutation, or
    caching.
    """
    if not isinstance(manifest, CaseSetManifest):
        raise TypeError(
            f"case_set_snapshot_hash requires a CaseSetManifest, "
            f"got {type(manifest).__name__}"
        )
    _require_unique_membership_suites(manifest, None)
    payload = manifest.model_dump(mode="json", exclude_unset=True)
    return sha256_bytes(canonical_contract_bytes(payload))


class _MembershipState:
    """Mutable ordered reconstruction state for one case during succession."""

    __slots__ = ("case_id", "partition", "suites", "input_packet_hash")

    def __init__(
        self, case_id: str, partition: str, suites: list[str], input_packet_hash: str
    ) -> None:
        self.case_id = case_id
        self.partition = partition
        self.suites = suites
        self.input_packet_hash = input_packet_hash


def verify_case_set_succession(
    base: CaseSetManifest,
    events: Sequence[MembershipEvent],
    successor: CaseSetManifest,
) -> None:
    """Verify that ``successor`` is fully explained by ``events`` over ``base``.

    Verification-form reconstruction: ordered events are applied to the
    base membership; a genuinely new case — absent from the original base
    manifest, not merely from the current reconstruction state — takes its
    ``input_packet_hash`` from the successor (the event contract does not
    carry that field), while a base case that is removed and later re-added
    keeps its original base packet hash. For every case ID present in both
    base and successor the packet hash must remain exactly unchanged,
    regardless of intermediate remove/re-add events. The reconstructed
    ordered state must then match the successor exactly. Every unexplained
    event or unexplained successor difference raises
    ``CaseSetConsistencyError``. No conflict resolution is performed.
    """
    for name, value in (("base", base), ("successor", successor)):
        if not isinstance(value, CaseSetManifest):
            raise TypeError(
                f"verify_case_set_succession requires CaseSetManifest for "
                f"{name}, got {type(value).__name__}"
            )
    _require_unique_membership_suites(base, None)
    _require_unique_membership_suites(successor, None)
    if base.case_set_version == successor.case_set_version:
        raise CaseSetConsistencyError(
            f"base and successor share case-set version "
            f"{base.case_set_version!r}; membership changes require a new "
            "case-set version",
            conflict_kind="same_version_change",
        )
    successor_by_id = {entry.case_id: entry for entry in successor.entries}
    base_packet_hashes = {
        entry.case_id: entry.input_packet_hash for entry in base.entries
    }
    for base_entry in base.entries:
        successor_entry = successor_by_id.get(base_entry.case_id)
        if (
            successor_entry is not None
            and successor_entry.input_packet_hash != base_entry.input_packet_hash
        ):
            raise CaseSetConsistencyError(
                f"case {base_entry.case_id!r} carries a different input "
                "packet hash in the successor manifest; an existing case "
                "packet-hash change is not representable by membership events",
                conflict_kind="unexplained_membership_change",
                case_id=base_entry.case_id,
            )
    order: list[str] = [entry.case_id for entry in base.entries]
    state: dict[str, _MembershipState] = {
        entry.case_id: _MembershipState(
            entry.case_id, entry.partition, list(entry.suites), entry.input_packet_hash
        )
        for entry in base.entries
    }
    for index, event in enumerate(events):
        if not isinstance(event, MembershipEvent):
            raise TypeError(
                f"verify_case_set_succession requires MembershipEvent items, "
                f"got {type(event).__name__} at index {index}"
            )
        _require_unique_event_suites(event, index, None)
        if (
            event.previous_case_set_version != base.case_set_version
            or event.new_case_set_version != successor.case_set_version
        ):
            raise CaseSetConsistencyError(
                f"membership event {index} for case {event.case_id!r} does "
                "not link the base version to the successor version",
                conflict_kind="version_chain_mismatch",
                case_id=event.case_id,
                event_index=index,
            )
        current = state.get(event.case_id)
        if current is None:
            if event.old_partition is not None or event.new_partition is None:
                raise CaseSetConsistencyError(
                    f"membership event {index} references case "
                    f"{event.case_id!r}, which is not present in the base "
                    "membership",
                    conflict_kind="unknown_case_reference",
                    case_id=event.case_id,
                    event_index=index,
                )
            if event.removed_suites:
                raise CaseSetConsistencyError(
                    f"membership event {index} adds case {event.case_id!r} "
                    "but also removes suites",
                    conflict_kind="contradictory_suite_change",
                    case_id=event.case_id,
                    event_index=index,
                )
            if event.case_id in base_packet_hashes:
                # Re-addition of an original base case: its identity is the
                # original base packet hash, never a successor-supplied one.
                packet_hash = base_packet_hashes[event.case_id]
            else:
                successor_entry = successor_by_id.get(event.case_id)
                if successor_entry is None:
                    raise CaseSetConsistencyError(
                        f"membership event {index} adds case {event.case_id!r} "
                        "but the successor manifest carries no such entry to "
                        "supply its input packet hash",
                        conflict_kind="unexplained_event",
                        case_id=event.case_id,
                        event_index=index,
                    )
                packet_hash = successor_entry.input_packet_hash
            order.append(event.case_id)
            state[event.case_id] = _MembershipState(
                event.case_id,
                event.new_partition,
                list(event.added_suites),
                packet_hash,
            )
            continue
        if event.new_partition is None:
            if event.old_partition != current.partition:
                raise CaseSetConsistencyError(
                    f"membership event {index} removes case {event.case_id!r} "
                    "with a stale old partition",
                    conflict_kind="stale_old_partition",
                    case_id=event.case_id,
                    event_index=index,
                )
            if event.added_suites:
                raise CaseSetConsistencyError(
                    f"membership event {index} removes case {event.case_id!r} "
                    "but also adds suites",
                    conflict_kind="contradictory_suite_change",
                    case_id=event.case_id,
                    event_index=index,
                )
            if list(event.removed_suites) != current.suites:
                raise CaseSetConsistencyError(
                    f"membership event {index} removes case {event.case_id!r} "
                    "without listing its exact current suites",
                    conflict_kind="contradictory_suite_change",
                    case_id=event.case_id,
                    event_index=index,
                )
            order.remove(event.case_id)
            del state[event.case_id]
            continue
        if event.old_partition is None or event.old_partition != current.partition:
            raise CaseSetConsistencyError(
                f"membership event {index} updates case {event.case_id!r} "
                "with a stale old partition",
                conflict_kind="stale_old_partition",
                case_id=event.case_id,
                event_index=index,
            )
        added = list(event.added_suites)
        removed = list(event.removed_suites)
        if set(added) & set(removed):
            raise CaseSetConsistencyError(
                f"membership event {index} for case {event.case_id!r} adds "
                "and removes the same suite",
                conflict_kind="contradictory_suite_change",
                case_id=event.case_id,
                event_index=index,
            )
        for suite in added:
            if suite in current.suites:
                raise CaseSetConsistencyError(
                    f"membership event {index} adds suite {suite!r} already "
                    f"present on case {event.case_id!r}",
                    conflict_kind="contradictory_suite_change",
                    case_id=event.case_id,
                    event_index=index,
                )
        for suite in removed:
            if suite not in current.suites:
                raise CaseSetConsistencyError(
                    f"membership event {index} removes suite {suite!r} not "
                    f"present on case {event.case_id!r}",
                    conflict_kind="contradictory_suite_change",
                    case_id=event.case_id,
                    event_index=index,
                )
        if event.new_partition == current.partition and not added and not removed:
            raise CaseSetConsistencyError(
                f"membership event {index} for case {event.case_id!r} causes "
                "no effective partition or suite change",
                conflict_kind="unexplained_event",
                case_id=event.case_id,
                event_index=index,
            )
        current.suites = [s for s in current.suites if s not in removed] + added
        current.partition = event.new_partition
    reconstructed = [
        (state[cid].case_id, state[cid].partition, tuple(state[cid].suites), state[cid].input_packet_hash)
        for cid in order
    ]
    actual = [
        (entry.case_id, entry.partition, entry.suites, entry.input_packet_hash)
        for entry in successor.entries
    ]
    limit = max(len(reconstructed), len(actual))
    for position in range(limit):
        rec = reconstructed[position] if position < len(reconstructed) else None
        act = actual[position] if position < len(actual) else None
        if rec != act:
            mismatch_case = act[0] if act is not None else rec[0]  # type: ignore[index]
            raise CaseSetConsistencyError(
                f"successor membership at position {position} (case "
                f"{mismatch_case!r}) is not explained by the supplied "
                "membership events",
                conflict_kind="unexplained_membership_change",
                case_id=mismatch_case,
            )


def verify_event_log_extension(
    previous_path: str | Path,
    current_path: str | Path,
    *,
    eval_root: str | Path,
) -> None:
    """Verify that the current event log extends the previous one append-only.

    Both logs are resolved under the explicit root and must independently
    parse and validate as membership-event logs; the complete previous raw
    byte sequence must then be an exact prefix of the current raw byte
    sequence (equality is a valid zero-event extension). No normalization
    of any kind is performed, and no filesystem-level append-only
    enforcement is claimed.
    """
    resolved_root = _validate_eval_root(eval_root)
    previous_resolved, previous_reference = _resolve_contained_path(
        previous_path, resolved_root
    )
    current_resolved, current_reference = _resolve_contained_path(
        current_path, resolved_root
    )
    previous_raw = _read_artifact_bytes(previous_resolved, previous_reference)
    current_raw = _read_artifact_bytes(current_resolved, current_reference)
    _parse_membership_events(previous_raw, previous_reference)
    _parse_membership_events(current_raw, current_reference)
    if not current_raw.startswith(previous_raw):
        raise CaseSetConsistencyError(
            f"event log {current_reference!r} does not extend "
            f"{previous_reference!r} append-only: the previous log is not an "
            "exact byte prefix of the current log",
            conflict_kind="append_only_prefix_violation",
            artifact_reference=previous_reference,
            related_artifact_reference=current_reference,
        )
