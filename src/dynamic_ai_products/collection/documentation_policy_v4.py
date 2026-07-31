"""Documentation acquisition policy v0.4.0 (ADR-040, E-C-D3).

**Why a sibling module rather than an edit.** ``documentation_policy.py`` was
modified in place across E-C-D, E-C-D1 and E-C-D2. That was the historical
pattern; it is not the pattern from here on. Under the v0.4 standard every
governed layer -- receipt, schema, routes **and policy source** -- succeeds rather
than mutates, so an archived receipt can be re-verified against the exact policy
source, route declaration and schema that produced it, not merely against a
schema whose sibling policy has since moved. The v0.3 policy therefore stays
byte-identical and keeps publishing ``@0.3.0``; this module publishes ``@0.4.0``
through its own explicit entry point.

**Route kinds are declared, never inferred.** v0.1-v0.3 could only express one
redirect hop, which worked only because every frozen pair's two URLs differed.
E3 is now ``direct``: its requested and final URLs are the same URL.

* ``redirect_once`` -- two sends: one recognized hop, then the terminal document.
* ``direct`` -- **one send**. An initial 200 is the only success path. A 3xx is
  recorded (status, and the adapter-exposed ``Location`` under the unchanged
  transcription policy) and refused with ``direct_redirect_not_permitted``. It is
  never followed, and no second send is issued for that entry under any outcome.

**Observations are named by send ordinal.** Calling a direct route's only send
"terminal" while its failure phases stayed named "redirect" would describe a hop
that never happened, so the vocabulary is ``send1_*`` / ``send2_*`` throughout.

**Everything else from v0.3 is preserved**: no injectable transport on the public
surface, no clock read inside the package, observations owned by the caller so
they outlive a refusal, ``_EntryRefusal`` carrying only closed-vocabulary values,
constant sanitized exception messages, and write-once persistence.
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
from .documentation_receipt_v4 import (
    ENTRY_RECORDABLE_REASONS_V4 as _ENTRY_RECORDABLE,
)
from .documentation_receipt_v4 import (
    FAILURE_PHASES,
    LOCATION_MAX_LENGTH,
    RECEIPT_CONTRACT_V4,
    build_documentation_receipt_v4,
    classify_observed_location,
    receipt_bytes_v4,
    validate_receipt_schema_v4_bytes,
)
from .documentation_routes_v4 import FROZEN_ROUTE_IDENTITIES_V4, ROUTE_KINDS
from .errors import CollectionError
from .publication import canonical_json_bytes

__all__ = [
    "DOCUMENTATION_REASON_CODES_V4",
    "FROZEN_EVIDENCE_ENTRIES_V4",
    "MAX_ENTITY_BYTES_PER_RESPONSE",
    "POLICY_CONTRACT_V4",
    "REDIRECT_STATUSES",
    "RETRIEVAL_TIMESTAMP_MODE",
    "SPACING_SECONDS",
    "TOTAL_ACCEPTED_ENTITY_BYTES_MAX",
    "DocumentationCollectionResultV4",
    "RetrievalClock",
    "collect_documentation_evidence_v4",
]

# The routes are read from their own module, never redeclared here. This module
# holds no URL literal beyond the bare https:// scheme prefix used for the
# absolute-Location syntax check.
FROZEN_EVIDENCE_ENTRIES_V4: tuple[dict[str, str], ...] = FROZEN_ROUTE_IDENTITIES_V4

REDIRECT_STATUSES: tuple[int, ...] = (301, 308)
TERMINAL_STATUS = 200
SPACING_SECONDS = 2.0
MAX_ENTITY_BYTES_PER_RESPONSE = http_adapter.MAX_ENTITY_BYTES_PER_RESPONSE
# Derived defensive ceiling. Redundant under the current exact-three-entry
# contract -- three documents each strictly under 8 MiB cannot reach 24 MiB --
# and retained only against later entry-count or per-response policy drift.
TOTAL_ACCEPTED_ENTITY_BYTES_MAX = (
    len(FROZEN_EVIDENCE_ENTRIES_V4) * MAX_ENTITY_BYTES_PER_RESPONSE
)
RETRIEVAL_TIMESTAMP_MODE = "caller_injected_request_start_utc_v1"
ACCEPTED_CONTENT_TYPE = "text/html"
_STATUS_MIN = 100
_STATUS_MAX = 599

# Maximum sends per entry, by declared route kind. Two redirect_once entries and
# one direct entry give an attempt maximum of five sends.
MAX_SENDS_BY_ROUTE_KIND: dict[str, int] = {"direct": 1, "redirect_once": 2}

POLICY_CONTRACT_V4: dict[str, Any] = {
    "contract": "documentation_acquisition_policy@0.4.0",
    "policy_module": "dynamic_ai_products.collection.documentation_policy_v4",
    "policy_version": "0.4.0",
    "ordered_pairs": [dict(entry) for entry in FROZEN_EVIDENCE_ENTRIES_V4],
    "route_kinds": list(ROUTE_KINDS),
    "max_sends_by_route_kind": dict(MAX_SENDS_BY_ROUTE_KIND),
    "max_sends_per_attempt": sum(
        MAX_SENDS_BY_ROUTE_KIND[e["route_kind"]] for e in FROZEN_EVIDENCE_ENTRIES_V4
    ),
    "scheme": "https",
    "required_redirect_statuses": list(REDIRECT_STATUSES),
    "required_terminal_status": TERMINAL_STATUS,
    "absolute_location_only": True,
    "query_allowed": False,
    "fragment_allowed": False,
    "request_spacing_seconds": SPACING_SECONDS,
    "max_entity_bytes_per_response": MAX_ENTITY_BYTES_PER_RESPONSE,
    "total_accepted_entity_bytes_max": TOTAL_ACCEPTED_ENTITY_BYTES_MAX,
    "accepted_content_type": ACCEPTED_CONTENT_TYPE,
    "retrieval_timestamp_mode": RETRIEVAL_TIMESTAMP_MODE,
    "write_once": True,
    # Declarations, not implementation notes: changing any of them changes the
    # policy digest and therefore the attempt identity.
    "failure_phases": list(FAILURE_PHASES),
    "request_chain_semantics": "urls_this_collector_initiated_in_order",
    "observed_location_source": "adapter_exposed_httpx_headers_get_location_string",
    "observed_location_max_length": LOCATION_MAX_LENGTH,
    "observed_location_accepted_charset": "printable_ascii_0x20_0x7e",
    "observed_location_followed": False,
    "observed_location_truncated": False,
    "direct_route_redirect_followed": False,
    # No total wall-clock deadline exists at any layer. Each send configures four
    # independent phase deadlines; they do not compose into a request bound, and
    # per-send bounds do not compose into a run bound. A total deadline would be a
    # separately governed successor to the transport contract.
    "total_wall_clock_deadline": None,
}

DOCUMENTATION_REASON_CODES_V4: frozenset[str] = frozenset(
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
        "redirect_status_invalid",
        "redirect_location_missing",
        "redirect_location_not_absolute",
        "redirect_location_mismatch",
        "redirect_chain_too_long",
        "direct_terminal_not_permitted",
        "direct_redirect_not_permitted",
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
_RFC3339_UTC = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|\+00:00)$"
)

# Module-private seams. Absent from __all__: offline tests may patch them, and a
# patched seam is explicitly noncanonical and may write only under tmp_path.
_send_once = http_adapter.send_once
_sleep = time.sleep


class RetrievalClock(Protocol):
    """Caller-injected source of the request-start instant."""

    def __call__(self) -> str:  # pragma: no cover - structural only
        ...


@dataclass(frozen=True)
class DocumentationCollectionResultV4:
    attempt_id: str
    attempt_root: Path
    completion_status: str
    entries: tuple[dict[str, Any], ...]
    receipt_reference: str | None
    receipt_sha256: str | None


class _EntryRefusal(Exception):
    """Entry-level refusal carrying only closed-vocabulary values.

    Deliberately not a :class:`CollectionError`: it never crosses the public
    boundary, and it exists so an entry can fail without an observed value ever
    riding on an exception object. Its ``args`` hold the reason code alone, so
    ``str`` and ``repr`` are closed-vocabulary too.
    """

    def __init__(self, reason_code: str, phase: str) -> None:
        if reason_code not in _ENTRY_RECORDABLE or phase not in FAILURE_PHASES:
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
    content_type: str | None = None
    content_encoding: str | None = None
    byte_count: int | None = None
    content_sha256: str | None = None


# --- helpers ------------------------------------------------------------------


def _canonical(payload: Any) -> bytes:
    """The repository convention, shared with every other collection artifact."""
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


# RFC 7230 token characters. A charset value outside this set -- quoted, spaced,
# empty, or carrying a second "=" -- is refused rather than trimmed into shape.
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
    """A usable HTTP status, or None when the response cannot be characterized.

    ``bool`` is excluded explicitly: ``True == 1`` in Python, and a status of 1 is
    not a status. A response whose status cannot be read is treated as no usable
    response at all, which keeps the phase and the recorded facts consistent.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if _STATUS_MIN <= value <= _STATUS_MAX else None


def _base_entry(entry: dict[str, str], status: str) -> dict[str, Any]:
    """The 21-field v0.4 entry with every observation empty."""
    return {
        "evidence_kind": entry["evidence_kind"],
        "route_kind": entry["route_kind"],
        "requested_url": entry["requested_url"],
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
    }


def _failed_entry(
    entry: dict[str, str], observation: _Observation, refusal: _EntryRefusal
) -> dict[str, Any]:
    """A truthful failure record: what was established, and exactly how far it got."""
    record = _base_entry(entry, "failed")
    record.update(_observed_fields(observation))
    record["failure_reason"] = refusal.reason_code
    record["failure_phase"] = refusal.phase
    if refusal.phase == "persistence":
        # The entity was accepted and storage refused it, so the entity facts are
        # real. No object exists, so its two fields stay null.
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
    entry: dict[str, str],
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
    """Refuse a symlink anywhere from the root down to the target."""
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
    response: Any,
    observation: _Observation,
    *,
    accepted_total: int,
    phase: str,
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
        # Defensive drift branch: unreachable while three entries each cap at
        # 8 MiB and the total is 3 x 8 MiB.
        raise _EntryRefusal("attempt_byte_ceiling_exceeded", phase)

    encoding = response.headers.get("content-encoding")
    observation.content_type = observed_content_type
    observation.content_encoding = encoding if isinstance(encoding, str) and encoding else "identity"
    observation.byte_count = len(payload)
    observation.content_sha256 = sha256(payload).hexdigest()
    return payload


def _attempt_direct_entry(
    entry: dict[str, str],
    *,
    accepted_total: int,
    observation: _Observation,
) -> bytes:
    """A direct route: exactly one send, and no second send under any outcome.

    An initial 200 is the only success path. A 3xx is recorded -- status and the
    adapter-exposed ``Location`` under the unchanged transcription policy -- and
    refused. It is never followed.
    """
    requested = entry["requested_url"]

    # --- send1_request: the entry's only send is initiated --------------------
    observation.request_chain = [requested]
    remaining = TOTAL_ACCEPTED_ENTITY_BYTES_MAX - accepted_total
    try:
        response = _send_once(
            url=requested,
            iterate_body=True,
            max_entity_bytes=min(MAX_ENTITY_BYTES_PER_RESPONSE, max(remaining, 0)),
        )
    except CollectionError as exc:
        raise _EntryRefusal(exc.reason_code, "send1_request") from None
    status = _observed_status(getattr(response, "status", None))
    if status is None:
        raise _EntryRefusal("transport_failed", "send1_request")

    # --- send1_evaluation: the only send answered -----------------------------
    observation.send1_status = status
    location, disposition = classify_observed_location(
        response.location, response_received=True
    )
    observation.send1_location = location
    observation.send1_location_disposition = disposition

    if response.final_url != requested:
        raise _EntryRefusal("response_request_identity_mismatch", "send1_evaluation")
    if 300 <= status < 400:
        # Recorded above, refused here, and never followed: no second send is
        # issued for a direct route, so the observed target is never requested.
        raise _EntryRefusal("direct_redirect_not_permitted", "send1_evaluation")
    if status != TERMINAL_STATUS:
        raise _EntryRefusal("terminal_status_invalid", "send1_evaluation")
    return _accept_entity(
        response, observation, accepted_total=accepted_total, phase="send1_evaluation"
    )


def _attempt_redirect_once_entry(
    entry: dict[str, str],
    *,
    accepted_total: int,
    spacer: Callable[[], None],
    observation: _Observation,
) -> bytes:
    """A redirect_once route: one recognized hop, then the terminal document."""
    requested, final = entry["requested_url"], entry["final_url"]

    # --- send1_request: the hop is initiated ----------------------------------
    observation.request_chain = [requested]
    try:
        hop = _send_once(url=requested, iterate_body=False)
    except CollectionError as exc:
        raise _EntryRefusal(exc.reason_code, "send1_request") from None
    hop_status = _observed_status(getattr(hop, "status", None))
    if hop_status is None:
        raise _EntryRefusal("transport_failed", "send1_request")

    # --- send1_evaluation: the hop answered -----------------------------------
    observation.send1_status = hop_status
    location, disposition = classify_observed_location(hop.location, response_received=True)
    observation.send1_location = location
    observation.send1_location_disposition = disposition

    if hop.final_url != requested:
        raise _EntryRefusal("response_request_identity_mismatch", "send1_evaluation")
    if hop_status == TERMINAL_STATUS:
        raise _EntryRefusal("direct_terminal_not_permitted", "send1_evaluation")
    if hop_status not in REDIRECT_STATUSES:
        raise _EntryRefusal("redirect_status_invalid", "send1_evaluation")
    # Authorization runs on the adapter-exposed value itself, independently of
    # whether that value was transcribable into the receipt.
    observed = hop.location
    if not observed:
        raise _EntryRefusal("redirect_location_missing", "send1_evaluation")
    if not isinstance(observed, str) or not observed.startswith("https://"):
        raise _EntryRefusal("redirect_location_not_absolute", "send1_evaluation")
    if observed != final:
        raise _EntryRefusal("redirect_location_mismatch", "send1_evaluation")

    # --- send2_preflight: the hop was accepted, send two not yet issued -------
    spacer()
    try:
        http_adapter.require_no_tls_keylog()
    except CollectionError as exc:
        raise _EntryRefusal(exc.reason_code, "send2_preflight") from None

    # --- send2_request: send two is initiated ---------------------------------
    observation.request_chain = [requested, final]
    remaining = TOTAL_ACCEPTED_ENTITY_BYTES_MAX - accepted_total
    try:
        terminal = _send_once(
            url=final,
            iterate_body=True,
            max_entity_bytes=min(MAX_ENTITY_BYTES_PER_RESPONSE, max(remaining, 0)),
        )
    except CollectionError as exc:
        raise _EntryRefusal(exc.reason_code, "send2_request") from None
    terminal_status = _observed_status(getattr(terminal, "status", None))
    if terminal_status is None:
        raise _EntryRefusal("transport_failed", "send2_request")

    # --- send2_evaluation: send two answered ----------------------------------
    observation.send2_status = terminal_status
    terminal_location, terminal_disposition = classify_observed_location(
        terminal.location, response_received=True
    )
    observation.send2_location = terminal_location
    observation.send2_location_disposition = terminal_disposition

    if terminal.final_url != final:
        raise _EntryRefusal("response_request_identity_mismatch", "send2_evaluation")
    if 300 <= terminal_status < 400:
        raise _EntryRefusal("redirect_chain_too_long", "send2_evaluation")
    if terminal_status != TERMINAL_STATUS:
        raise _EntryRefusal("terminal_status_invalid", "send2_evaluation")
    return _accept_entity(
        terminal, observation, accepted_total=accepted_total, phase="send2_evaluation"
    )


def _attempt_entry(
    entry: dict[str, str],
    *,
    retrieval_clock: RetrievalClock,
    accepted_total: int,
    spacer: Callable[[], None],
    observation: _Observation,
) -> bytes:
    """One entry: spacing, clock, keylog recheck, then its declared route kind.

    ``observation`` is owned by the caller and is populated as each fact is
    established, so a refusal anywhere below leaves the caller holding everything
    that was true at that moment. Returns the accepted entity bytes; raises
    :class:`_EntryRefusal` for every entry-level refusal.

    ``spacer`` delays before every send after the very first of the attempt. Five
    possible sends -- two, two and one -- so a full success produces exactly four
    delays.
    """
    # --- entry_preflight: no send has been issued for this entry --------------
    spacer()
    try:
        stamp = retrieval_clock()
    except Exception:  # noqa: BLE001 - the clock seam is total
        raise _EntryRefusal("retrieval_clock_failed", "entry_preflight") from None
    parsed = _parse_utc_instant(stamp)
    if parsed is None:
        raise _EntryRefusal("retrieval_clock_invalid", "entry_preflight")
    observation.retrieval_timestamp = parsed

    # Rechecked immediately before every client construction: an appearance
    # between sends must stop the attempt, not be inherited from the preflight.
    try:
        http_adapter.require_no_tls_keylog()
    except CollectionError as exc:
        raise _EntryRefusal(exc.reason_code, "entry_preflight") from None

    if entry["route_kind"] == "direct":
        return _attempt_direct_entry(
            entry, accepted_total=accepted_total, observation=observation
        )
    return _attempt_redirect_once_entry(
        entry, accepted_total=accepted_total, spacer=spacer, observation=observation
    )


# --- public entry point -------------------------------------------------------


def collect_documentation_evidence_v4(
    *,
    raw_root: str | Path,
    receipt_schema_bytes: bytes,
    code_commit: str,
    run_created_at: str,
    retrieval_clock: RetrievalClock,
    receipt_schema_sha256: object = _SCHEMA_PIN_UNSET,
) -> DocumentationCollectionResultV4:
    """Acquire the three frozen v0.4 documentation snapshots, or stop truthfully.

    The only governed route that may publish a ``@0.4.0`` receipt. It constructs
    the committed adapter itself and records the contract hashes it actually used,
    so no caller-selectable fake can be represented as the canonical collector.
    There is no ``url`` parameter: the routes are frozen constants.
    """
    # [1] The digest is derived, never claimed.
    if receipt_schema_sha256 is not _SCHEMA_PIN_UNSET:
        raise CollectionError(
            "the receipt schema digest is derived from the supplied bytes and "
            "is never accepted from a caller",
            reason_code="receipt_schema_claim_forbidden",
        )
    # [2] Static keylog preflight, before anything exists.
    http_adapter.require_no_tls_keylog()
    # [3] Schema bytes validated; digest derived. No file is re-read later.
    schema_digest = validate_receipt_schema_v4_bytes(receipt_schema_bytes)
    # [4] Contract identities.
    adapter_digest = sha256(http_adapter.adapter_contract_bytes()).hexdigest()
    policy_digest = sha256(_canonical(POLICY_CONTRACT_V4)).hexdigest()
    # [5] Canonical attempt identity. The frozen pairs are part of that identity,
    # so their cleanliness and their declared kinds are attempt-level properties
    # checked once, before any send.
    if not isinstance(code_commit, str) or not code_commit.strip():
        raise CollectionError("code_commit is required", reason_code="attempt_identity_invalid")
    _require_utc_instant_identity(run_created_at)
    for entry in FROZEN_EVIDENCE_ENTRIES_V4:
        _require_clean_url(entry["requested_url"], "attempt_identity_invalid")
        _require_clean_url(entry["final_url"], "attempt_identity_invalid")
        kind = entry["route_kind"]
        if kind not in ROUTE_KINDS:
            raise CollectionError(
                "a frozen route declares an unknown kind",
                reason_code="attempt_identity_invalid",
            )
        same = entry["requested_url"] == entry["final_url"]
        if (kind == "direct") != same:
            raise CollectionError(
                "a frozen route's declared kind contradicts its URLs",
                reason_code="attempt_identity_invalid",
            )
    attempt_id = "docattempt-" + sha256(
        _canonical(
            {
                "code_commit": code_commit,
                "run_created_at": run_created_at,
                "adapter_contract_sha256": adapter_digest,
                "policy_contract_sha256": policy_digest,
                "receipt_contract_id": RECEIPT_CONTRACT_V4,
                "receipt_schema_sha256": schema_digest,
                "ordered_pairs": [dict(e) for e in FROZEN_EVIDENCE_ENTRIES_V4],
            }
        )
    ).hexdigest()[:32]

    root = Path(raw_root)
    attempt_root = root / "attempts" / attempt_id
    # [6] Duplicate and unsafe-ancestry refusal, before any request.
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
    # [7] First filesystem effect.
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

    for index, entry in enumerate(FROZEN_EVIDENCE_ENTRIES_V4):
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
                # Translated at the seam so the persistence phase is named and no
                # explicit cause carries anything outward.
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
    receipt = build_documentation_receipt_v4(
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
    payload = receipt_bytes_v4(receipt)
    try:
        digest = write_bytes_once(
            attempt_root / reference, payload, what="documentation collection receipt"
        )
    except (WriteOnceError, OSError):
        # Best-effort publication: the storage failure is never masked by a receipt
        # write, and an attempt without a terminal receipt is not authoritative.
        raise CollectionError(
            "the terminal receipt could not be published",
            reason_code="receipt_publication_failed",
        ) from None
    return DocumentationCollectionResultV4(
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
