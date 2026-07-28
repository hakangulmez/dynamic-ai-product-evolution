"""Stage 00 minimal one-firm Pilot Universe Packet (HubSpot FY2024, Route A).

Implements the approved Pilot 0 contract lock: a frozen three-URL SEC
allowlist with redirect-safe transport semantics, write-once raw-byte and
collection-receipt preservation, receipt-anchored packet building, and a
human-supplied two-marker Item 1 evidence model whose validation proves byte
provenance and containment only.

Boundaries enforced here:

- exactly three frozen SEC URLs may ever be requested; redirects are disabled
  and any redirect status or final-URL mismatch is a fail-closed stop;
- every persisted file (three raw files plus ``collection_receipt.json``) is
  write-once (``O_EXCL`` + fsync + re-read SHA-256 verification) and a URL is
  never re-requested merely because a destination already exists;
- ``company_id`` is derived only from the persisted ``submissions.json``
  bytes, never asserted manually; SIC remains cross-checking metadata only;
- the positive admission requires two human-supplied, document-specific
  structural anchors for this already hash-locked HubSpot primary document —
  the exact raw bytes ``id="item_i_business"`` (start) and
  ``id="item_1a_risk_factors"`` (end) at human-supplied offsets — plus a
  human-selected evidence slice. The builder only slices at the supplied
  offsets, requires exact byte equality with the locked anchor bytes,
  verifies the supplied SHA-256 values, and enforces byte containment of the
  evidence between the anchors. These anchors are not a general SEC parser
  and not an automatic search mechanism: nothing is searched, parsed,
  rendered, normalized, or decoded in the intervening HTML range, and no
  model call occurs anywhere;
- the evidence slice keeps the strict ``utf-8-strict-text-slice-v1`` rule:
  strict UTF-8 decode, exact hash/text equality, nonblank after ``strip()``,
  and no literal ``<`` or ``>``;
- if no valid anchor exists, the raw files and receipt are preserved and the
  packet build refuses with an explicit materiality-evidence stop reason.

The clock is read only in this collection layer (retrieval timestamps are a
temporal-policy requirement); the evaluation harness remains clock-free.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..provenance import WriteOnceError, write_bytes_once
from .identifiers import IdentifierError, company_id_for_cik, normalize_cik

__all__ = [
    "AnchorSelection",
    "ByteSliceSelection",
    "CollectionOutcome",
    "PilotPacketError",
    "TransportResponse",
    "build_pilot_universe_packet",
    "collect_pilot_sources",
    "load_collection_receipt",
    "materiality_stop_report",
]

# --- Locked constants -------------------------------------------------------

PILOT_CIK = "0001404655"
PILOT_ACCESSION = "0000950170-25-018873"
PILOT_FORM = "10-K"
PILOT_FILING_DATE = "2025-02-12"
PILOT_PERIOD_OF_REPORT = "2024-12-31"
PILOT_OBSERVATION_CUTOFF = "2025-02-12"
PILOT_FISCAL_YEAR_END = "2024-12-31"
PILOT_PRIMARY_DOCUMENT = "hubs-20241231.htm"
PILOT_MECHANISM = "enterprise_workflow_software"
PILOT_ROUTE = "A"

USER_AGENT = "dynamic-ai-product-evolution research hakanzekigulmez@gmail.com"
REQUEST_SPACING_SECONDS = 1.0
MAX_RETRIES_PER_URL = 1

RECEIPT_FILENAME = "collection_receipt.json"
RECEIPT_VERSION = "collection_receipt_v1"
PACKET_VERSION = "pilot_universe_packet_v1"
EVIDENCE_TEXT_ENCODING = "utf-8-strict-text-slice-v1"

# The frozen three-URL allowlist: (key, url, destination filename), in the
# exact retrieval order. No other URL may ever be requested.
FROZEN_RETRIEVALS: tuple[tuple[str, str, str], ...] = (
    (
        "submissions",
        "https://data.sec.gov/submissions/CIK0001404655.json",
        "submissions.json",
    ),
    (
        "filing_index",
        "https://www.sec.gov/Archives/edgar/data/1404655/000095017025018873/index.json",
        "filing-index.json",
    ),
    (
        "primary_document",
        "https://www.sec.gov/Archives/edgar/data/1404655/000095017025018873/"
        "hubs-20241231.htm",
        "hubs-20241231.htm",
    ),
)
_ALLOWED_URLS = frozenset(url for _, url, _ in FROZEN_RETRIEVALS)

# Fixed, human-supplied, byte-verifiable structural anchors for THIS already
# hash-locked HubSpot primary document. Document-specific: not a general SEC
# parser and not an automatic search mechanism.
START_ANCHOR_BYTES = b'id="item_i_business"'
END_ANCHOR_BYTES = b'id="item_1a_risk_factors"'

_SOURCE_PACKET_FAMILIES = (
    "sec_edgar",
    "official_ir",
    "product_pages",
    "developer_docs",
    "web_archives",
)


class PilotPacketError(Exception):
    """Sanitized pilot-packet failure with a stable machine-readable code."""

    def __init__(
        self, message: str, *, reason_code: str, stop_reason: str | None = None
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.stop_reason = stop_reason


@dataclass(frozen=True)
class TransportResponse:
    """One HTTP response as seen by the collector."""

    status_code: int
    final_url: str
    content: bytes


@dataclass(frozen=True)
class CollectionOutcome:
    """Result of a completed (fully successful) collection attempt."""

    raw_directory: Path
    receipt_path: Path
    receipt_sha256: str
    file_sha256: dict[str, str]


@dataclass(frozen=True)
class ByteSliceSelection:
    """A human-selected raw-byte text slice with its recorded identity."""

    start_offset: int
    end_offset: int
    sha256: str
    text: str


@dataclass(frozen=True)
class AnchorSelection:
    """A human-supplied structural-anchor location (offsets plus SHA-256)."""

    start_offset: int
    end_offset: int
    sha256: str


# --- Small helpers ----------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


def _write_once(path: Path, data: bytes, *, what: str) -> str:
    """Translate the neutral write-once primitive into this module's boundary.

    The shared primitive (ADR-031) owns the persistence semantics and raises
    ``WriteOnceError``; that neutral type never escapes this module. Success
    and pre-existing-path refusal stay compatible with the committed Pilot 0
    API: same returned hash, same bytes, same ``reason_code`` values, and the
    same message text. The one intended difference is the strengthened error
    path — a failed write now removes the destination this call created
    instead of leaving a partial file that would block every retry.
    """
    try:
        return write_bytes_once(path, data, what=what)
    except WriteOnceError as exc:
        if exc.category == "destination_exists":
            raise PilotPacketError(
                str(exc), reason_code="destination_exists"
            ) from exc
        raise PilotPacketError(str(exc), reason_code="write_error") from exc


def _default_clock() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _raw_directory(raw_root: str | Path) -> Path:
    return Path(raw_root) / "sec" / f"CIK{PILOT_CIK}" / PILOT_ACCESSION


# --- Collection -------------------------------------------------------------


def collect_pilot_sources(
    *,
    raw_root: str | Path,
    transport: Callable[[str, dict[str, str]], TransportResponse] | None = None,
    sleeper: Callable[[float], None] | None = None,
    clock: Callable[[], str] | None = None,
) -> CollectionOutcome:
    """Execute the single frozen three-URL collection attempt, write-once.

    On full success the three raw files and the collection receipt are
    persisted and a :class:`CollectionOutcome` is returned. On any fail-closed
    stop (redirect, final-URL mismatch, HTTP error after the bounded retry, or
    transport failure) the receipt is still written — recording every
    attempted URL, the stop reason, and the not-attempted remainder — and a
    ``retrieval_stop`` error is raised. Already-persisted files are never
    touched, and a URL is never re-requested merely because a raw destination
    already exists.
    """
    # The universe package carries no network client (sentinel guard): the
    # transport is always injected by the operator of the single approved
    # live collection. With the receipt persisted, later invocations refuse
    # write-once before any transport use.
    sleeper = sleeper if sleeper is not None else time.sleep
    clock = clock if clock is not None else _default_clock

    raw_dir = _raw_directory(raw_root)
    raw_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = raw_dir / RECEIPT_FILENAME
    if receipt_path.is_symlink() or receipt_path.exists():
        raise PilotPacketError(
            "a collection receipt already exists; the collection attempt is "
            "single-shot and write-once",
            reason_code="receipt_exists",
        )
    for _, _, filename in FROZEN_RETRIEVALS:
        destination = raw_dir / filename
        if destination.is_symlink() or destination.exists():
            raise PilotPacketError(
                f"raw destination {filename!r} already exists; collection never "
                "re-requests an already-persisted URL",
                reason_code="destination_exists",
            )
    if transport is None:
        raise PilotPacketError(
            "a transport must be injected; the universe package carries no "
            "network client",
            reason_code="transport_required",
        )

    entries: list[dict[str, Any]] = []
    file_sha256: dict[str, str] = {}
    stop_reason: str | None = None

    for position, (key, url, filename) in enumerate(FROZEN_RETRIEVALS):
        if stop_reason is not None:
            entries.append(
                {
                    "key": key,
                    "requested_url": url,
                    "retry_count": 0,
                    "failure_reason": "not_attempted",
                }
            )
            continue
        if url not in _ALLOWED_URLS:  # structural guard; unreachable by design
            raise PilotPacketError(
                "a non-allowlisted URL reached the collector",
                reason_code="disallowed_url",
            )
        if position > 0:
            sleeper(REQUEST_SPACING_SECONDS)
        entry: dict[str, Any] = {"key": key, "requested_url": url, "retry_count": 0}
        response: TransportResponse | None = None
        for attempt in range(MAX_RETRIES_PER_URL + 1):
            if attempt > 0:
                entry["retry_count"] = attempt
                sleeper(REQUEST_SPACING_SECONDS)
            try:
                candidate = transport(url, {"User-Agent": USER_AGENT})
            except Exception:  # noqa: BLE001 - transport failure is a governed stop
                candidate = None
            if candidate is not None and candidate.status_code < 500:
                response = candidate
                break
            if attempt == MAX_RETRIES_PER_URL:
                response = candidate
        timestamp = clock()
        entry["retrieval_timestamp"] = timestamp
        if response is None:
            entry["failure_reason"] = "transport_error"
            stop_reason = "transport_error"
        elif 300 <= response.status_code < 400:
            entry["final_url"] = response.final_url
            entry["http_status"] = response.status_code
            entry["failure_reason"] = "redirect_response"
            stop_reason = "redirect_response"
        elif response.final_url != url:
            entry["final_url"] = response.final_url
            entry["http_status"] = response.status_code
            entry["failure_reason"] = "final_url_mismatch"
            stop_reason = "final_url_mismatch"
        elif response.status_code != 200:
            entry["final_url"] = response.final_url
            entry["http_status"] = response.status_code
            entry["failure_reason"] = "http_error"
            stop_reason = "http_error"
        else:
            digest = _write_once(
                raw_dir / filename, response.content, what=f"raw file {filename!r}"
            )
            entry["final_url"] = response.final_url
            entry["http_status"] = response.status_code
            entry["byte_count"] = len(response.content)
            entry["sha256"] = digest
            file_sha256[key] = digest
        entries.append(entry)

    receipt: dict[str, Any] = {
        "receipt_version": RECEIPT_VERSION,
        "completion_status": "complete" if stop_reason is None else "stopped",
        "identity": {
            "cik": PILOT_CIK,
            "accession": PILOT_ACCESSION,
            "form": PILOT_FORM,
            "filing_date": PILOT_FILING_DATE,
            "period_of_report": PILOT_PERIOD_OF_REPORT,
        },
        "retrievals": entries,
    }
    if stop_reason is not None:
        receipt["stop_reason"] = stop_reason
    receipt_bytes = _canonical_json_bytes(receipt)
    receipt_sha256 = _write_once(receipt_path, receipt_bytes, what="collection receipt")

    if stop_reason is not None:
        raise PilotPacketError(
            f"collection stopped fail-closed ({stop_reason}); the receipt records "
            "the attempt and persisted files are preserved",
            reason_code="retrieval_stop",
            stop_reason=stop_reason,
        )
    return CollectionOutcome(
        raw_directory=raw_dir,
        receipt_path=receipt_path,
        receipt_sha256=receipt_sha256,
        file_sha256=dict(file_sha256),
    )


# --- Receipt loading --------------------------------------------------------


def load_collection_receipt(raw_root: str | Path) -> tuple[dict[str, Any], str]:
    """Load, hash, and strictly validate the immutable collection receipt."""
    receipt_path = _raw_directory(raw_root) / RECEIPT_FILENAME
    if not receipt_path.is_file():
        raise PilotPacketError(
            "the collection receipt is missing", reason_code="receipt_missing"
        )
    try:
        raw = receipt_path.read_bytes()
    except OSError as exc:
        raise PilotPacketError(
            "the collection receipt could not be read", reason_code="receipt_invalid"
        ) from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PilotPacketError(
            "the collection receipt is not strict JSON", reason_code="receipt_invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise PilotPacketError(
            "the collection receipt top-level value must be a JSON object",
            reason_code="receipt_invalid",
        )
    if payload.get("receipt_version") != RECEIPT_VERSION:
        raise PilotPacketError(
            "the collection receipt carries an unsupported receipt_version",
            reason_code="receipt_invalid",
        )
    retrievals = payload.get("retrievals")
    if not isinstance(retrievals, list):
        raise PilotPacketError(
            "the collection receipt carries no retrieval list",
            reason_code="receipt_invalid",
        )
    recorded_urls = [
        entry.get("requested_url")
        for entry in retrievals
        if isinstance(entry, dict)
    ]
    expected_urls = [url for _, url, _ in FROZEN_RETRIEVALS]
    if recorded_urls != expected_urls:
        raise PilotPacketError(
            "the collection receipt does not represent exactly the locked three URLs",
            reason_code="receipt_invalid",
        )
    identity = payload.get("identity")
    if not isinstance(identity, dict) or identity.get("accession") != PILOT_ACCESSION:
        raise PilotPacketError(
            "the collection receipt does not carry the locked filing identity",
            reason_code="receipt_invalid",
        )
    return payload, _sha256(raw)


_LOCKED_RECEIPT_IDENTITY: dict[str, str] = {
    "cik": PILOT_CIK,
    "accession": PILOT_ACCESSION,
    "form": PILOT_FORM,
    "filing_date": PILOT_FILING_DATE,
    "period_of_report": PILOT_PERIOD_OF_REPORT,
}


def _is_lower_hex64(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_rfc3339_with_offset(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    candidate = f"{value[:-1]}+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _invalid_receipt(detail: str) -> PilotPacketError:
    return PilotPacketError(
        f"the collection receipt is not a valid successful receipt: {detail}",
        reason_code="receipt_invalid",
    )


def _require_successful_receipt(receipt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Strictly validate a receipt for packet building; never KeyError/TypeError.

    Every field a positive admission relies on is verified exactly: the locked
    filing identity, the frozen key/order/URL sequence, and each entry's
    final-URL equality, HTTP 200 status, byte count, lowercase 64-hex SHA-256,
    bounded retry count, and timezone-bearing RFC3339 retrieval timestamp.
    """
    if receipt.get("completion_status") != "complete":
        raise PilotPacketError(
            "the collection receipt does not record a successful completion",
            reason_code="receipt_incomplete",
        )
    identity = receipt.get("identity")
    if not isinstance(identity, dict) or identity != _LOCKED_RECEIPT_IDENTITY:
        raise _invalid_receipt(
            "the identity block does not equal the locked CIK/accession/form/"
            "filing-date/period identity"
        )
    retrievals = receipt.get("retrievals")
    if not isinstance(retrievals, list) or len(retrievals) != len(FROZEN_RETRIEVALS):
        raise _invalid_receipt("the retrieval list is not exactly the frozen three")
    entries: dict[str, dict[str, Any]] = {}
    for position, (key, url, _) in enumerate(FROZEN_RETRIEVALS):
        entry = retrievals[position]
        if not isinstance(entry, dict):
            raise _invalid_receipt("a retrieval entry is not a JSON object")
        if entry.get("failure_reason") is not None:
            raise PilotPacketError(
                "the collection receipt records a failed retrieval",
                reason_code="receipt_incomplete",
            )
        if entry.get("key") != key:
            raise _invalid_receipt(f"entry {position} does not carry key {key!r}")
        if entry.get("requested_url") != url:
            raise _invalid_receipt(f"entry {key!r} requested_url is not the frozen URL")
        if entry.get("final_url") != url:
            raise _invalid_receipt(
                f"entry {key!r} final_url does not equal the requested URL exactly"
            )
        status = entry.get("http_status")
        if not _is_strict_int(status) or status != 200:
            raise _invalid_receipt(f"entry {key!r} http_status is not exactly 200")
        byte_count = entry.get("byte_count")
        if not _is_strict_int(byte_count) or byte_count < 0:
            raise _invalid_receipt(
                f"entry {key!r} byte_count is not a nonnegative integer"
            )
        if not _is_lower_hex64(entry.get("sha256")):
            raise _invalid_receipt(
                f"entry {key!r} sha256 is not a lowercase 64-hex string"
            )
        retry_count = entry.get("retry_count")
        if not _is_strict_int(retry_count) or not 0 <= retry_count <= MAX_RETRIES_PER_URL:
            raise _invalid_receipt(
                f"entry {key!r} retry_count is not an integer in [0, "
                f"{MAX_RETRIES_PER_URL}]"
            )
        if not _is_rfc3339_with_offset(entry.get("retrieval_timestamp")):
            raise _invalid_receipt(
                f"entry {key!r} retrieval_timestamp is not a timezone-bearing "
                "RFC3339 timestamp"
            )
        entries[key] = entry
    return entries


# --- Marker and evidence validation ----------------------------------------


def _validate_text_slice(
    document: bytes, selection: ByteSliceSelection, *, what: str, reason_code: str
) -> str:
    start, end = selection.start_offset, selection.end_offset
    if not isinstance(start, int) or not isinstance(end, int):
        raise PilotPacketError(f"{what} offsets must be integers", reason_code=reason_code)
    if start < 0 or end <= start or end > len(document):
        raise PilotPacketError(
            f"{what} offsets are out of range or inverted", reason_code=reason_code
        )
    fragment = document[start:end]
    if _sha256(fragment) != selection.sha256:
        raise PilotPacketError(
            f"{what} bytes do not hash to the recorded fragment SHA-256",
            reason_code=reason_code,
        )
    try:
        decoded = fragment.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PilotPacketError(
            f"{what} bytes are not strictly UTF-8 decodable", reason_code=reason_code
        ) from exc
    if decoded != selection.text:
        raise PilotPacketError(
            f"{what} decoded text does not equal the recorded text exactly",
            reason_code=reason_code,
        )
    if not decoded.strip():
        raise PilotPacketError(f"{what} text is blank", reason_code=reason_code)
    if "<" in decoded or ">" in decoded:
        raise PilotPacketError(
            f"{what} text contains literal HTML markup", reason_code=reason_code
        )
    return decoded


def _validate_structural_anchor(
    document: bytes,
    selection: AnchorSelection,
    locked_bytes: bytes,
    *,
    what: str,
) -> None:
    """Prove byte provenance of one human-supplied structural anchor.

    Only slices at the supplied offsets and requires exact byte equality with
    the locked anchor bytes plus SHA-256 agreement — never searches for the
    anchor and never decodes anything.
    """
    start, end = selection.start_offset, selection.end_offset
    if not isinstance(start, int) or not isinstance(end, int):
        raise PilotPacketError(
            f"{what} offsets must be integers", reason_code="anchor_invalid"
        )
    if start < 0 or end <= start or end > len(document):
        raise PilotPacketError(
            f"{what} offsets are out of range or inverted",
            reason_code="anchor_invalid",
        )
    fragment = document[start:end]
    if fragment != locked_bytes:
        raise PilotPacketError(
            f"{what} bytes do not equal the locked structural-anchor bytes exactly",
            reason_code="anchor_invalid",
        )
    if _sha256(fragment) != selection.sha256:
        raise PilotPacketError(
            f"{what} supplied SHA-256 does not match the anchor bytes",
            reason_code="anchor_invalid",
        )


def _validate_anchors_and_evidence(
    document: bytes,
    start_anchor: AnchorSelection,
    end_anchor: AnchorSelection,
    evidence: ByteSliceSelection,
) -> None:
    _validate_structural_anchor(
        document, start_anchor, START_ANCHOR_BYTES,
        what="the Item 1 start structural anchor",
    )
    _validate_structural_anchor(
        document, end_anchor, END_ANCHOR_BYTES,
        what="the Item 1A end structural anchor",
    )
    if not (start_anchor.end_offset <= end_anchor.start_offset):
        raise PilotPacketError(
            "the end structural anchor does not follow the start structural anchor",
            reason_code="anchor_order_invalid",
        )
    _validate_text_slice(
        document, evidence, what="the materiality evidence slice",
        reason_code="evidence_invalid",
    )
    if not (
        start_anchor.end_offset
        <= evidence.start_offset
        < evidence.end_offset
        <= end_anchor.start_offset
    ):
        raise PilotPacketError(
            "the evidence slice is not contained between the verified "
            "structural anchors",
            reason_code="evidence_out_of_bounds",
        )


# --- Persisted-evidence parsing ---------------------------------------------


def _parse_submissions(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PilotPacketError(
            "the persisted submissions metadata is not strict JSON",
            reason_code="submissions_invalid",
        ) from exc
    if not isinstance(payload, dict):
        raise PilotPacketError(
            "the persisted submissions metadata must be a JSON object",
            reason_code="submissions_invalid",
        )
    return payload


def _derive_identity(submissions: dict[str, Any]) -> dict[str, Any]:
    try:
        cik = normalize_cik(submissions.get("cik", ""))
    except IdentifierError as exc:
        raise PilotPacketError(
            "the persisted submissions CIK does not normalize",
            reason_code="cik_mismatch",
        ) from exc
    if cik != PILOT_CIK:
        raise PilotPacketError(
            "the persisted submissions CIK is not the locked pilot CIK",
            reason_code="cik_mismatch",
        )
    name = submissions.get("name")
    if not isinstance(name, str) or not name.strip():
        raise PilotPacketError(
            "the persisted submissions metadata carries no legal entity name",
            reason_code="submissions_invalid",
        )
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    matched = None
    for form, accession, filed, period in zip(
        forms, accessions, filing_dates, report_dates
    ):
        if accession == PILOT_ACCESSION:
            matched = (form, filed, period)
            break
    if matched is None:
        raise PilotPacketError(
            "the locked accession is absent from the persisted filing history",
            reason_code="filing_missing",
        )
    form, filed, period = matched
    if form != PILOT_FORM or period != PILOT_PERIOD_OF_REPORT:
        raise PilotPacketError(
            "the persisted filing identity does not match the locked form/period",
            reason_code="filing_missing",
        )
    if filed != PILOT_FILING_DATE or filed != PILOT_OBSERVATION_CUTOFF:
        raise PilotPacketError(
            "the persisted filing date does not equal the locked observation cutoff",
            reason_code="cutoff_mismatch",
        )
    return {
        "company_id": company_id_for_cik(cik),
        "cik": cik,
        "legal_name": name,
        "tickers": submissions.get("tickers", []),
        "exchanges": submissions.get("exchanges", []),
        "sic": submissions.get("sic"),
        "sic_description": submissions.get("sicDescription"),
        "state_of_incorporation": submissions.get("stateOfIncorporation"),
        "fiscal_year_end_code": submissions.get("fiscalYearEnd"),
    }


def _require_primary_in_index(raw: bytes) -> None:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PilotPacketError(
            "the persisted filing index is not strict JSON",
            reason_code="index_invalid",
        ) from exc
    items = (
        payload.get("directory", {}).get("item", [])
        if isinstance(payload, dict)
        else []
    )
    names = {item.get("name") for item in items if isinstance(item, dict)}
    if PILOT_PRIMARY_DOCUMENT not in names:
        raise PilotPacketError(
            "the persisted filing index does not list the locked primary document",
            reason_code="index_invalid",
        )


# --- Packet build -----------------------------------------------------------


def _slice_record(selection: ByteSliceSelection) -> dict[str, Any]:
    return {
        "start_offset": selection.start_offset,
        "end_offset": selection.end_offset,
        "sha256": selection.sha256,
        "text": selection.text,
    }


def _anchor_record(selection: AnchorSelection, locked_bytes: bytes) -> dict[str, Any]:
    return {
        "anchor_bytes": locked_bytes.decode("ascii"),
        "start_offset": selection.start_offset,
        "end_offset": selection.end_offset,
        "sha256": selection.sha256,
    }


def build_pilot_universe_packet(
    *,
    raw_root: str | Path,
    packet_path: str | Path,
    start_anchor: AnchorSelection,
    end_anchor: AnchorSelection,
    evidence: ByteSliceSelection,
    selection_note: str,
) -> dict[str, Any]:
    """Build and persist (write-once) the tracked Pilot Universe Packet.

    Fails closed unless the immutable receipt exists, is complete and
    successful, hashes agree with every persisted raw file, the persisted
    submissions bytes establish the locked identity/cutoff, the filing index
    lists the primary document, and the human-supplied structural anchors and
    evidence slice satisfy every byte-provenance rule.
    """
    if not isinstance(selection_note, str) or not selection_note.strip():
        raise PilotPacketError(
            "the human selection note must be non-blank",
            reason_code="selection_note_blank",
        )
    receipt, receipt_sha256 = load_collection_receipt(raw_root)
    entries = _require_successful_receipt(receipt)

    raw_dir = _raw_directory(raw_root)
    raw_bytes: dict[str, bytes] = {}
    for key, _, filename in FROZEN_RETRIEVALS:
        path = raw_dir / filename
        if not path.is_file():
            raise PilotPacketError(
                f"the persisted raw file {filename!r} is missing",
                reason_code="receipt_hash_mismatch",
            )
        data = path.read_bytes()
        if _sha256(data) != entries[key]["sha256"]:
            raise PilotPacketError(
                f"the persisted raw file {filename!r} does not hash to its "
                "receipt entry",
                reason_code="receipt_hash_mismatch",
            )
        if entries[key]["byte_count"] != len(data):
            raise PilotPacketError(
                f"the persisted raw file {filename!r} length does not equal its "
                "receipt byte_count",
                reason_code="receipt_content_mismatch",
            )
        raw_bytes[key] = data

    identity = _derive_identity(_parse_submissions(raw_bytes["submissions"]))
    _require_primary_in_index(raw_bytes["filing_index"])
    document = raw_bytes["primary_document"]
    if not document:
        raise PilotPacketError(
            "the persisted primary document is empty", reason_code="evidence_invalid"
        )
    _validate_anchors_and_evidence(document, start_anchor, end_anchor, evidence)

    packet = {
        "packet_version": PACKET_VERSION,
        "route": PILOT_ROUTE,
        "company_id": identity["company_id"],
        "cik": identity["cik"],
        "legal_name": identity["legal_name"],
        "tickers": identity["tickers"],
        "exchanges": identity["exchanges"],
        "sic_cross_check_only": {
            "sic": identity["sic"],
            "sic_description": identity["sic_description"],
        },
        "state_of_incorporation": identity["state_of_incorporation"],
        "fiscal_year_end_code": identity["fiscal_year_end_code"],
        "observation_year": "FY2024",
        "observation_cutoff_date": PILOT_OBSERVATION_CUTOFF,
        "fiscal_year_end_date": PILOT_FISCAL_YEAR_END,
        "filing": {
            "form": PILOT_FORM,
            "accession": PILOT_ACCESSION,
            "filing_date": PILOT_FILING_DATE,
            "period_of_report": PILOT_PERIOD_OF_REPORT,
            "primary_document": PILOT_PRIMARY_DOCUMENT,
            "primary_document_sha256": entries["primary_document"]["sha256"],
        },
        "retrieval_provenance": receipt["retrievals"],
        "collection_receipt_sha256": receipt_sha256,
        "materiality_evidence": {
            "basis": "primary_10k_text_slice",
            "evidence_text_encoding": EVIDENCE_TEXT_ENCODING,
            "start_anchor": _anchor_record(start_anchor, START_ANCHOR_BYTES),
            "end_anchor": _anchor_record(end_anchor, END_ANCHOR_BYTES),
            "evidence": _slice_record(evidence),
            "selected_by": "human_reviewer",
            "selection_note": selection_note,
        },
        "eligibility": {
            "annual_filer": True,
            "cik_stable": True,
            "materiality_basis": "primary_10k_text_slice",
            "verdict": "admitted_pilot_only_route_a",
            "scope_limitation": (
                "pilot-only Route A admission; not a general universe decision; "
                "the draft_pending_sentinel universe status is unchanged"
            ),
        },
        "mechanism": PILOT_MECHANISM,
        "source_packet_families": list(_SOURCE_PACKET_FAMILIES),
    }
    destination = Path(packet_path)
    if destination.is_symlink() or destination.exists():
        raise PilotPacketError(
            "the pilot universe packet already exists; packets are write-once",
            reason_code="packet_exists",
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_once(destination, _canonical_json_bytes(packet), what="pilot universe packet")
    return packet


def materiality_stop_report(raw_root: str | Path, reason: str) -> dict[str, Any]:
    """The fail-closed no-admission outcome: report, never write.

    Confirms the immutable receipt is still present and returns the explicit
    materiality-evidence stop record for review. Creates nothing and mutates
    nothing; the tracked packet and the decision-log entry are refused.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise PilotPacketError(
            "a materiality stop requires a non-blank reason",
            reason_code="selection_note_blank",
        )
    receipt, receipt_sha256 = load_collection_receipt(raw_root)
    return {
        "outcome": "materiality_evidence_stop",
        "stop_reason": reason,
        "collection_receipt_sha256": receipt_sha256,
        "completion_status": receipt.get("completion_status"),
        "packet_created": False,
        "decision_log_entry_created": False,
    }
