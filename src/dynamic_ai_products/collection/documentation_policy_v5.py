"""Documentation acquisition policy v0.5.0 (ADR-041, E-C-D4).

**Successor, not an edit.** The v0.3 and v0.4 policies stay byte-identical and keep
publishing their own receipt contracts. Under the v0.4 standard every governed
layer -- receipt, schema, routes and policy source -- succeeds rather than mutates,
so an archived receipt can be re-verified against the exact sources that produced
it.

**What v0.5 does: two-hop route grammar, and nothing else.** It corrects how the
chain is walked. It collects no content evidence, and a successful retrieval under
it is still retrieval status alone.

* ``redirect_twice_relative_path`` -- three sends. Send one and send two accept
  only 301/308. Send one's ``Location`` must be byte-exact against the frozen
  intermediate. Send two's ``Location`` must satisfy a narrow absolute-path
  grammar and be byte-exact against the frozen raw path; it is joined to a
  **fixed declared base**, never one parsed out of a response, and the join must
  reproduce the frozen final URL byte-exactly. Send three must answer 200.
* ``redirect_once`` -- two sends, as before, to an absolute frozen final.

**There is no ``direct`` kind.** v0.4's direct semantics are not carried forward.

**No new transport.** This module imports the unchanged ``http_adapter`` and never
``httpx``; the repository-wide httpx importer allowlist stays at two modules.

Preserved from v0.4: no injectable transport on the public surface, no clock read
inside the package, observations owned by the caller so they outlive a refusal,
``_EntryRefusal`` carrying only closed-vocabulary values, constant sanitized
exception messages, write-once persistence, no retry, and no total wall-clock
deadline at any layer.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit

from ..provenance import WriteOnceError, write_bytes_once
from . import http_adapter
from .documentation_receipt_v5 import (
    ENTRY_RECORDABLE_REASONS_V5 as _ENTRY_RECORDABLE,
)
from .documentation_receipt_v5 import (
    FAILURE_PHASES_V5,
    LOCATION_MAX_LENGTH,
    RECEIPT_CONTRACT_V5,
    absolute_path_reference_violation,
    build_documentation_receipt_v5,
    classify_observed_location,
    receipt_bytes_v5,
    resolve_absolute_path_reference,
    validate_receipt_schema_v5_bytes,
)
from .documentation_routes_v5 import (
    FROZEN_ROUTE_IDENTITIES_V5,
    RELATIVE_RESOLUTION_BASE,
    ROUTE_KINDS_V5,
    SENDS_BY_ROUTE_KIND,
)
from .errors import CollectionError
from .publication import canonical_json_bytes

__all__ = [
    "DOCUMENTATION_REASON_CODES_V5",
    "FROZEN_EVIDENCE_ENTRIES_V5",
    "MAX_ENTITY_BYTES_PER_RESPONSE",
    "POLICY_CONTRACT_V5",
    "REDIRECT_STATUSES",
    "RETRIEVAL_TIMESTAMP_MODE",
    "SPACING_SECONDS",
    "TOTAL_ACCEPTED_ENTITY_BYTES_MAX",
    "DocumentationCollectionResultV5",
    "RetrievalClock",
    "collect_documentation_evidence_v5",
]

# Routes are read from their own module, never redeclared here. This module holds
# no URL literal beyond the bare https:// scheme prefix used for a syntax check.
FROZEN_EVIDENCE_ENTRIES_V5: tuple[dict[str, Any], ...] = FROZEN_ROUTE_IDENTITIES_V5

REDIRECT_STATUSES: tuple[int, ...] = (301, 308)
TERMINAL_STATUS = 200
SPACING_SECONDS = 2.0
MAX_ENTITY_BYTES_PER_RESPONSE = http_adapter.MAX_ENTITY_BYTES_PER_RESPONSE
TOTAL_ACCEPTED_ENTITY_BYTES_MAX = (
    len(FROZEN_EVIDENCE_ENTRIES_V5) * MAX_ENTITY_BYTES_PER_RESPONSE
)
RETRIEVAL_TIMESTAMP_MODE = "caller_injected_request_start_utc_v1"
ACCEPTED_CONTENT_TYPE = "text/html"
_STATUS_MIN = 100
_STATUS_MAX = 599

MAX_SENDS_PER_ATTEMPT = sum(
    SENDS_BY_ROUTE_KIND[entry["route_kind"]] for entry in FROZEN_EVIDENCE_ENTRIES_V5
)

POLICY_CONTRACT_V5: dict[str, Any] = {
    "contract": "documentation_acquisition_policy@0.5.0",
    "policy_module": "dynamic_ai_products.collection.documentation_policy_v5",
    "policy_version": "0.5.0",
    "ordered_routes": [dict(entry) for entry in FROZEN_EVIDENCE_ENTRIES_V5],
    "route_kinds": list(ROUTE_KINDS_V5),
    "sends_by_route_kind": dict(SENDS_BY_ROUTE_KIND),
    "max_sends_per_attempt": MAX_SENDS_PER_ATTEMPT,
    "scheme": "https",
    "required_redirect_statuses": list(REDIRECT_STATUSES),
    "required_terminal_status": TERMINAL_STATUS,
    "first_hop_absolute_location_only": True,
    "second_hop_absolute_path_reference_only": True,
    "relative_resolution_base": RELATIVE_RESOLUTION_BASE,
    "relative_resolution_mode": "fixed_declared_base_concatenation_v1",
    "query_allowed": False,
    "fragment_allowed": False,
    "request_spacing_seconds": SPACING_SECONDS,
    "max_entity_bytes_per_response": MAX_ENTITY_BYTES_PER_RESPONSE,
    "total_accepted_entity_bytes_max": TOTAL_ACCEPTED_ENTITY_BYTES_MAX,
    "accepted_content_type": ACCEPTED_CONTENT_TYPE,
    "retrieval_timestamp_mode": RETRIEVAL_TIMESTAMP_MODE,
    "write_once": True,
    "failure_phases": list(FAILURE_PHASES_V5),
    "request_chain_semantics": "urls_this_collector_initiated_in_order",
    "observed_location_source": "adapter_exposed_httpx_headers_get_location_string",
    "observed_location_max_length": LOCATION_MAX_LENGTH,
    "observed_location_accepted_charset": "printable_ascii_0x20_0x7e",
    "observed_location_followed": False,
    "observed_location_truncated": False,
    "retry_policy": "none",
    # No total wall-clock deadline exists at any layer. Each send configures four
    # independent phase deadlines; they do not compose into a request bound, and
    # per-send bounds do not compose into a run bound.
    "total_wall_clock_deadline": None,
}

DOCUMENTATION_REASON_CODES_V5: frozenset[str] = frozenset(
    {
        "receipt_schema_claim_forbidden",
        "receipt_schema_invalid",
        "receipt_schema_contract_mismatch",
        "attempt_identity_invalid",
        "attempt_root_exists",
        "attempt_root_unsafe",
        "tls_keylog_environment_present",
        "retrieval_clock_invalid",
        "retrieval_clock_failed",
        "transport_timeout",
        "transport_failed",
        "response_request_identity_mismatch",
        "direct_terminal_not_permitted",
        "redirect_status_invalid",
        "redirect_location_missing",
        "redirect_location_not_absolute",
        "redirect_location_mismatch",
        "second_redirect_status_invalid",
        "second_location_missing",
        "second_location_not_relative_path",
        "second_location_mismatch",
        "resolved_final_mismatch",
        "redirect_chain_too_long",
        "terminal_status_invalid",
        "content_type_invalid",
        "entity_too_large",
        "attempt_byte_ceiling_exceeded",
        "entity_empty",
        "content_object_corrupt",
        "write_error",
        "destination_exists",
        "receipt_publication_failed",
    }
)

_SCHEMA_PIN_UNSET = object()
_RFC3339_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|\+00:00)$")

# Module-private seams. Absent from __all__; offline tests may patch them.
_send_once = http_adapter.send_once
_sleep = time.sleep


class RetrievalClock(Protocol):
    """Caller-injected source of the request-start instant."""

    def __call__(self) -> str:  # pragma: no cover - structural only
        ...


@dataclass(frozen=True)
class DocumentationCollectionResultV5:
    attempt_id: str
    attempt_root: Path
    completion_status: str
    entries: tuple[dict[str, Any], ...]
    receipt_reference: str | None
    receipt_sha256: str | None


class _EntryRefusal(Exception):
    """Entry-level refusal carrying only closed-vocabulary values."""

    def __init__(self, reason_code: str, phase: str) -> None:
        if reason_code not in _ENTRY_RECORDABLE or phase not in FAILURE_PHASES_V5:
            raise ValueError("an entry refusal must name a declared reason and phase")
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.phase = phase


@dataclass
class _Observation:
    """What this entry established, owned by the caller so it outlives a refusal."""

    request_chain: list[str] = field(default_factory=list)
    retrieval_timestamp: str | None = None
    send1_status: int | None = None
    send1_location: str | None = None
    send1_location_disposition: str = "no_response"
    send2_status: int | None = None
    send2_location: str | None = None
    send2_location_disposition: str = "no_response"
    send3_request_url: str | None = None
    send3_status: int | None = None
    send3_location: str | None = None
    send3_location_disposition: str = "no_response"
    content_type: str | None = None
    content_encoding: str | None = None
    byte_count: int | None = None
    content_sha256: str | None = None


# --- helpers ------------------------------------------------------------------


def _canonical(payload: Any) -> bytes:
    return canonical_json_bytes(payload)


def _require_clean_url(url: str, code: str) -> None:
    split = urlsplit(url)
    if split.scheme != "https" or split.query or split.fragment or "@" in split.netloc:
        raise CollectionError("the URL is not an accepted clean https URL", reason_code=code)


def _parse_utc_instant(value: Any) -> str | None:
    """Lexical **and** semantic: the calendar/time values must be real."""
    if not isinstance(value, str) or not _RFC3339_UTC.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return value


_TOKEN_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+\-.^_`|~]+$")


def _content_type_accepted(value: str) -> bool:
    """``text/html`` with at most one real ``charset`` token, case-insensitively."""
    parts = [segment.strip() for segment in value.strip().split(";")]
    if not parts or parts[0].lower() != ACCEPTED_CONTENT_TYPE:
        return False
    if len(parts) == 1:
        return True
    if len(parts) != 2:
        return False
    name, separator, parameter = parts[1].partition("=")
    if name.strip().lower() != "charset" or not separator:
        return False
    return bool(_TOKEN_RE.fullmatch(parameter.strip()))


def _observed_status(value: Any) -> int | None:
    """A usable HTTP status, or None when the response cannot be characterized."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if _STATUS_MIN <= value <= _STATUS_MAX else None


def _base_entry(entry: dict[str, Any], status: str) -> dict[str, Any]:
    """The 27-field v0.5 entry with every observation empty."""
    return {
        "evidence_kind": entry["evidence_kind"],
        "route_kind": entry["route_kind"],
        "requested_url": entry["requested_url"],
        "intermediate_url": entry["intermediate_url"],
        "second_hop_location": entry["second_hop_location"],
        "final_url": entry["final_url"],
        "entry_status": status,
        "request_chain": [],
        "content_type": None,
        "content_encoding": None,
        "byte_count": None,
        "content_sha256": None,
        "raw_reference": None,
        "object_disposition": None,
        "retrieval_timestamp": None,
        "failure_reason": None,
        "failure_phase": None,
        "send1_observed_status": None,
        "send1_observed_location": None,
        "send1_observed_location_disposition": "no_response",
        "send2_observed_status": None,
        "send2_observed_location": None,
        "send2_observed_location_disposition": "no_response",
        "send3_request_url": None,
        "send3_observed_status": None,
        "send3_observed_location": None,
        "send3_observed_location_disposition": "no_response",
    }


def _observed_fields(observation: _Observation) -> dict[str, Any]:
    return {
        "request_chain": list(observation.request_chain),
        "retrieval_timestamp": observation.retrieval_timestamp,
        "send1_observed_status": observation.send1_status,
        "send1_observed_location": observation.send1_location,
        "send1_observed_location_disposition": observation.send1_location_disposition,
        "send2_observed_status": observation.send2_status,
        "send2_observed_location": observation.send2_location,
        "send2_observed_location_disposition": observation.send2_location_disposition,
        "send3_request_url": observation.send3_request_url,
        "send3_observed_status": observation.send3_status,
        "send3_observed_location": observation.send3_location,
        "send3_observed_location_disposition": observation.send3_location_disposition,
    }


def _failed_entry(
    entry: dict[str, Any], observation: _Observation, refusal: _EntryRefusal
) -> dict[str, Any]:
    record = _base_entry(entry, "failed")
    record.update(_observed_fields(observation))
    record["failure_reason"] = refusal.reason_code
    record["failure_phase"] = refusal.phase
    if refusal.phase == "persistence":
        record.update(
            {
                "content_type": observation.content_type,
                "content_encoding": observation.content_encoding,
                "byte_count": observation.byte_count,
                "content_sha256": observation.content_sha256,
            }
        )
    return record


def _succeeded_entry(
    entry: dict[str, Any],
    observation: _Observation,
    *,
    reference: str,
    disposition: str,
) -> dict[str, Any]:
    record = _base_entry(entry, "succeeded")
    record.update(_observed_fields(observation))
    record.update(
        {
            "content_type": observation.content_type,
            "content_encoding": observation.content_encoding,
            "byte_count": observation.byte_count,
            "content_sha256": observation.content_sha256,
            "raw_reference": reference,
            "object_disposition": disposition,
        }
    )
    return record


def _require_no_symlink_ancestry(root: Path, target: Path, code: str) -> None:
    if root.is_symlink():
        raise CollectionError("the root is a symlink", reason_code=code)
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise CollectionError(
                "a governed path component is a symlink", reason_code=code
            )


def _persist_object(raw_root: Path, evidence_kind: str, payload: bytes) -> tuple[str, str]:
    """Content-address the bytes; create or verifiably reuse. Never overwrite."""
    digest = sha256(payload).hexdigest()
    reference = f"{evidence_kind}/sha256-{digest}/document.html"
    target = raw_root / reference
    _require_no_symlink_ancestry(raw_root, target, "content_object_corrupt")

    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_file():
            raise CollectionError(
                "an existing content object is not a regular file",
                reason_code="content_object_corrupt",
            )
        try:
            existing = target.read_bytes()
        except OSError:
            raise CollectionError(
                "an existing content object could not be re-read",
                reason_code="content_object_corrupt",
            ) from None
        if sha256(existing).hexdigest() != digest:
            raise CollectionError(
                "an existing content object does not match its path digest",
                reason_code="content_object_corrupt",
            )
        return reference, "reused"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise CollectionError(
            "the content object directory could not be created",
            reason_code="write_error",
        ) from None
    try:
        write_bytes_once(target, payload, what="documentation evidence")
    except WriteOnceError as exc:
        code = (
            "destination_exists" if exc.category == "destination_exists" else "write_error"
        )
        raise CollectionError("the content object could not be written", reason_code=code) from None
    except OSError:
        raise CollectionError(
            "the content object could not be written", reason_code="write_error"
        ) from None
    return reference, "created"


def _accept_entity(
    response: Any, observation: _Observation, *, accepted_total: int, phase: str
) -> bytes:
    """Validate and record the terminal document. Shared by both route kinds."""
    observed_content_type = response.headers.get("content-type")
    if not isinstance(observed_content_type, str):
        observed_content_type = ""
    if not _content_type_accepted(observed_content_type):
        raise _EntryRefusal("content_type_invalid", phase)
    payload = response.entity_bytes or b""
    if not payload:
        raise _EntryRefusal("entity_empty", phase)
    if accepted_total + len(payload) > TOTAL_ACCEPTED_ENTITY_BYTES_MAX:
        raise _EntryRefusal("attempt_byte_ceiling_exceeded", phase)
    encoding = response.headers.get("content-encoding")
    observation.content_type = observed_content_type
    observation.content_encoding = encoding if isinstance(encoding, str) and encoding else "identity"
    observation.byte_count = len(payload)
    observation.content_sha256 = sha256(payload).hexdigest()
    return payload


def _keylog_or_refuse(phase: str) -> None:
    try:
        http_adapter.require_no_tls_keylog()
    except CollectionError as exc:
        raise _EntryRefusal(exc.reason_code, phase) from None


def _terminal_send(
    url: str,
    *,
    accepted_total: int,
    observation: _Observation,
    ordinal: str,
) -> bytes:
    """Issue the document-bearing send and evaluate it. Shared by both kinds."""
    request_phase, evaluation_phase = f"{ordinal}_request", f"{ordinal}_evaluation"
    remaining = TOTAL_ACCEPTED_ENTITY_BYTES_MAX - accepted_total
    try:
        response = _send_once(
            url=url,
            iterate_body=True,
            max_entity_bytes=min(MAX_ENTITY_BYTES_PER_RESPONSE, max(remaining, 0)),
        )
    except CollectionError as exc:
        raise _EntryRefusal(exc.reason_code, request_phase) from None
    status = _observed_status(getattr(response, "status", None))
    if status is None:
        raise _EntryRefusal("transport_failed", request_phase)

    setattr(observation, f"{ordinal}_status", status)
    location, disposition = classify_observed_location(
        response.location, response_received=True
    )
    setattr(observation, f"{ordinal}_location", location)
    setattr(observation, f"{ordinal}_location_disposition", disposition)

    if response.final_url != url:
        raise _EntryRefusal("response_request_identity_mismatch", evaluation_phase)
    if 300 <= status < 400:
        raise _EntryRefusal("redirect_chain_too_long", evaluation_phase)
    if status != TERMINAL_STATUS:
        raise _EntryRefusal("terminal_status_invalid", evaluation_phase)
    return _accept_entity(
        response, observation, accepted_total=accepted_total, phase=evaluation_phase
    )


def _attempt_redirect_once_entry(
    entry: dict[str, Any],
    *,
    accepted_total: int,
    spacer: Callable[[], None],
    observation: _Observation,
) -> bytes:
    """One recognized hop to an absolute frozen final, then the document."""
    requested, final = entry["requested_url"], entry["final_url"]

    observation.request_chain = [requested]
    try:
        hop = _send_once(url=requested, iterate_body=False)
    except CollectionError as exc:
        raise _EntryRefusal(exc.reason_code, "send1_request") from None
    status = _observed_status(getattr(hop, "status", None))
    if status is None:
        raise _EntryRefusal("transport_failed", "send1_request")

    observation.send1_status = status
    location, disposition = classify_observed_location(hop.location, response_received=True)
    observation.send1_location = location
    observation.send1_location_disposition = disposition

    if hop.final_url != requested:
        raise _EntryRefusal("response_request_identity_mismatch", "send1_evaluation")
    if status == TERMINAL_STATUS:
        raise _EntryRefusal("direct_terminal_not_permitted", "send1_evaluation")
    if status not in REDIRECT_STATUSES:
        raise _EntryRefusal("redirect_status_invalid", "send1_evaluation")
    observed = hop.location
    if not observed:
        raise _EntryRefusal("redirect_location_missing", "send1_evaluation")
    if not isinstance(observed, str) or not observed.startswith("https://"):
        raise _EntryRefusal("redirect_location_not_absolute", "send1_evaluation")
    if observed != final:
        raise _EntryRefusal("redirect_location_mismatch", "send1_evaluation")

    spacer()
    _keylog_or_refuse("send2_preflight")
    observation.request_chain = [requested, final]
    return _terminal_send(
        final, accepted_total=accepted_total, observation=observation, ordinal="send2"
    )


def _attempt_redirect_twice_entry(
    entry: dict[str, Any],
    *,
    accepted_total: int,
    spacer: Callable[[], None],
    observation: _Observation,
) -> bytes:
    """Two recognized hops -- absolute then absolute-path -- then the document."""
    requested = entry["requested_url"]
    intermediate = entry["intermediate_url"]
    raw_path = entry["second_hop_location"]
    final = entry["final_url"]

    # --- send1: the first hop, an absolute Location --------------------------
    observation.request_chain = [requested]
    try:
        hop = _send_once(url=requested, iterate_body=False)
    except CollectionError as exc:
        raise _EntryRefusal(exc.reason_code, "send1_request") from None
    status = _observed_status(getattr(hop, "status", None))
    if status is None:
        raise _EntryRefusal("transport_failed", "send1_request")

    observation.send1_status = status
    location, disposition = classify_observed_location(hop.location, response_received=True)
    observation.send1_location = location
    observation.send1_location_disposition = disposition

    if hop.final_url != requested:
        raise _EntryRefusal("response_request_identity_mismatch", "send1_evaluation")
    if status == TERMINAL_STATUS:
        raise _EntryRefusal("direct_terminal_not_permitted", "send1_evaluation")
    if status not in REDIRECT_STATUSES:
        raise _EntryRefusal("redirect_status_invalid", "send1_evaluation")
    observed = hop.location
    if not observed:
        raise _EntryRefusal("redirect_location_missing", "send1_evaluation")
    if not isinstance(observed, str) or not observed.startswith("https://"):
        raise _EntryRefusal("redirect_location_not_absolute", "send1_evaluation")
    if observed != intermediate:
        raise _EntryRefusal("redirect_location_mismatch", "send1_evaluation")

    # --- send2: the second hop, an absolute-path reference -------------------
    spacer()
    _keylog_or_refuse("send2_preflight")
    observation.request_chain = [requested, intermediate]
    try:
        second = _send_once(url=intermediate, iterate_body=False)
    except CollectionError as exc:
        raise _EntryRefusal(exc.reason_code, "send2_request") from None
    second_status = _observed_status(getattr(second, "status", None))
    if second_status is None:
        raise _EntryRefusal("transport_failed", "send2_request")

    observation.send2_status = second_status
    second_location, second_disposition = classify_observed_location(
        second.location, response_received=True
    )
    observation.send2_location = second_location
    observation.send2_location_disposition = second_disposition

    if second.final_url != intermediate:
        raise _EntryRefusal("response_request_identity_mismatch", "send2_evaluation")
    if second_status == TERMINAL_STATUS:
        raise _EntryRefusal("direct_terminal_not_permitted", "send2_evaluation")
    if second_status not in REDIRECT_STATUSES:
        raise _EntryRefusal("second_redirect_status_invalid", "send2_evaluation")
    observed_second = second.location
    if not observed_second:
        raise _EntryRefusal("second_location_missing", "send2_evaluation")
    # Authorization runs on the adapter-exposed value itself, independently of
    # whether that value was transcribable into the receipt.
    if absolute_path_reference_violation(observed_second) is not None:
        raise _EntryRefusal("second_location_not_relative_path", "send2_evaluation")
    if observed_second != raw_path:
        raise _EntryRefusal("second_location_mismatch", "send2_evaluation")
    # Mechanical join to a fixed declared base; never a base parsed out of a
    # response. The result must reproduce the frozen final URL byte-exactly.
    if resolve_absolute_path_reference(observed_second) != final:
        raise _EntryRefusal("resolved_final_mismatch", "send2_evaluation")
    observation.send3_request_url = final

    # --- send3: the terminal document ----------------------------------------
    spacer()
    _keylog_or_refuse("send3_preflight")
    observation.request_chain = [requested, intermediate, final]
    return _terminal_send(
        final, accepted_total=accepted_total, observation=observation, ordinal="send3"
    )


def _attempt_entry(
    entry: dict[str, Any],
    *,
    retrieval_clock: RetrievalClock,
    accepted_total: int,
    spacer: Callable[[], None],
    observation: _Observation,
) -> bytes:
    """One entry: spacing, clock, keylog recheck, then its declared route kind.

    ``spacer`` delays before every send after the very first of the attempt.
    Eight possible sends -- three, three and two -- so a full success produces
    exactly seven delays.
    """
    spacer()
    try:
        stamp = retrieval_clock()
    except Exception:  # noqa: BLE001 - the clock seam is total
        raise _EntryRefusal("retrieval_clock_failed", "entry_preflight") from None
    parsed = _parse_utc_instant(stamp)
    if parsed is None:
        raise _EntryRefusal("retrieval_clock_invalid", "entry_preflight")
    observation.retrieval_timestamp = parsed
    _keylog_or_refuse("entry_preflight")

    if entry["route_kind"] == "redirect_once":
        return _attempt_redirect_once_entry(
            entry, accepted_total=accepted_total, spacer=spacer, observation=observation
        )
    return _attempt_redirect_twice_entry(
        entry, accepted_total=accepted_total, spacer=spacer, observation=observation
    )


# --- public entry point -------------------------------------------------------


def collect_documentation_evidence_v5(
    *,
    raw_root: str | Path,
    receipt_schema_bytes: bytes,
    code_commit: str,
    run_created_at: str,
    retrieval_clock: RetrievalClock,
    receipt_schema_sha256: object = _SCHEMA_PIN_UNSET,
) -> DocumentationCollectionResultV5:
    """Acquire the three frozen v0.5 documentation snapshots, or stop truthfully.

    The only governed route that may publish a ``@0.5.0`` receipt. It constructs
    the committed adapter itself and records the contract hashes it actually used,
    so no caller-selectable fake can be represented as the canonical collector.
    There is no ``url`` parameter: the routes are frozen constants.
    """
    if receipt_schema_sha256 is not _SCHEMA_PIN_UNSET:
        raise CollectionError(
            "the receipt schema digest is derived from the supplied bytes and "
            "is never accepted from a caller",
            reason_code="receipt_schema_claim_forbidden",
        )
    http_adapter.require_no_tls_keylog()
    schema_digest = validate_receipt_schema_v5_bytes(receipt_schema_bytes)
    adapter_digest = sha256(http_adapter.adapter_contract_bytes()).hexdigest()
    policy_digest = sha256(_canonical(POLICY_CONTRACT_V5)).hexdigest()

    if not isinstance(code_commit, str) or not code_commit.strip():
        raise CollectionError("code_commit is required", reason_code="attempt_identity_invalid")
    _require_utc_instant_identity(run_created_at)
    # The frozen routes are part of the attempt identity, so their cleanliness,
    # declared kinds and resolution are attempt-level properties checked once,
    # before any send.
    for entry in FROZEN_EVIDENCE_ENTRIES_V5:
        kind = entry["route_kind"]
        if kind not in ROUTE_KINDS_V5:
            raise CollectionError(
                "a frozen route declares an unknown kind",
                reason_code="attempt_identity_invalid",
            )
        _require_clean_url(entry["requested_url"], "attempt_identity_invalid")
        _require_clean_url(entry["final_url"], "attempt_identity_invalid")
        if kind == "redirect_once":
            if entry["intermediate_url"] is not None or entry["second_hop_location"] is not None:
                raise CollectionError(
                    "a one-hop frozen route declares an intermediate hop",
                    reason_code="attempt_identity_invalid",
                )
            if entry["requested_url"] == entry["final_url"]:
                raise CollectionError(
                    "a one-hop frozen route must declare two different URLs",
                    reason_code="attempt_identity_invalid",
                )
            continue
        _require_clean_url(entry["intermediate_url"], "attempt_identity_invalid")
        if absolute_path_reference_violation(entry["second_hop_location"]) is not None:
            raise CollectionError(
                "a two-hop frozen route's raw path is not an absolute-path reference",
                reason_code="attempt_identity_invalid",
            )
        if resolve_absolute_path_reference(entry["second_hop_location"]) != entry["final_url"]:
            raise CollectionError(
                "a two-hop frozen route's raw path must resolve to its final URL",
                reason_code="attempt_identity_invalid",
            )
        if len({entry["requested_url"], entry["intermediate_url"], entry["final_url"]}) != 3:
            raise CollectionError(
                "a two-hop frozen route must declare three distinct URLs",
                reason_code="attempt_identity_invalid",
            )

    attempt_id = "docattempt-" + sha256(
        _canonical(
            {
                "code_commit": code_commit,
                "run_created_at": run_created_at,
                "adapter_contract_sha256": adapter_digest,
                "policy_contract_sha256": policy_digest,
                "receipt_contract_id": RECEIPT_CONTRACT_V5,
                "receipt_schema_sha256": schema_digest,
                "ordered_routes": [dict(e) for e in FROZEN_EVIDENCE_ENTRIES_V5],
            }
        )
    ).hexdigest()[:32]

    root = Path(raw_root)
    attempt_root = root / "attempts" / attempt_id
    if attempt_root.is_symlink() or attempt_root.exists():
        raise CollectionError(
            "this attempt root already exists; attempts are never overwritten",
            reason_code="attempt_root_exists",
        )
    if root.is_symlink() or (root / "attempts").is_symlink():
        raise CollectionError(
            "the raw root or attempts directory is a symlink",
            reason_code="attempt_root_unsafe",
        )
    try:
        attempt_root.mkdir(parents=True, exist_ok=False)
    except OSError:
        raise CollectionError(
            "the attempt root could not be created", reason_code="attempt_root_unsafe"
        ) from None

    entries: list[dict[str, Any]] = []
    accepted_total = 0
    stopped_at: int | None = None
    sent_any = {"value": False}

    def spacer() -> None:
        """Delay before every send after the attempt's first."""
        if sent_any["value"]:
            _sleep(SPACING_SECONDS)
        sent_any["value"] = True

    for index, entry in enumerate(FROZEN_EVIDENCE_ENTRIES_V5):
        if stopped_at is not None:
            entries.append(_base_entry(entry, "not_attempted"))
            continue
        observation = _Observation()
        try:
            payload = _attempt_entry(
                entry,
                retrieval_clock=retrieval_clock,
                accepted_total=accepted_total,
                spacer=spacer,
                observation=observation,
            )
            try:
                reference, disposition = _persist_object(
                    root, entry["evidence_kind"], payload
                )
            except CollectionError as exc:
                raise _EntryRefusal(exc.reason_code, "persistence") from None
            accepted_total += len(payload)
            entries.append(
                _succeeded_entry(
                    entry, observation, reference=reference, disposition=disposition
                )
            )
        except _EntryRefusal as refusal:
            entries.append(_failed_entry(entry, observation, refusal))
            stopped_at = index

    completion = "completed" if stopped_at is None else "stopped"
    receipt = build_documentation_receipt_v5(
        attempt_id=attempt_id,
        code_commit=code_commit,
        run_created_at=run_created_at,
        adapter_contract_sha256=adapter_digest,
        policy_contract_sha256=policy_digest,
        receipt_schema_sha256=schema_digest,
        retrieval_timestamp_mode=RETRIEVAL_TIMESTAMP_MODE,
        entries=entries,
        completion_status=completion,
    )
    reference = "collection_receipt.json"
    payload = receipt_bytes_v5(receipt)
    try:
        digest = write_bytes_once(
            attempt_root / reference, payload, what="documentation collection receipt"
        )
    except (WriteOnceError, OSError):
        raise CollectionError(
            "the terminal receipt could not be published",
            reason_code="receipt_publication_failed",
        ) from None
    return DocumentationCollectionResultV5(
        attempt_id=attempt_id,
        attempt_root=attempt_root,
        completion_status=completion,
        entries=tuple(entries),
        receipt_reference=reference,
        receipt_sha256=digest,
    )


def _require_utc_instant_identity(value: Any) -> None:
    if _parse_utc_instant(value) is None:
        raise CollectionError(
            "run_created_at must be a strict timezone-aware UTC RFC3339 instant",
            reason_code="attempt_identity_invalid",
        )
