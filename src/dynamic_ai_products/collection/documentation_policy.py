"""Documentation evidence acquisition policy (ADR-037, E-C-D).

**This module owns every decision; the adapter owns none.** The three frozen
requested/final URL pairs, the HTTPS-only rule, the exactly-one-hop grammar, the
spacing, the byte ceilings and the write-once persistence all live here. The
adapter is URL-policy neutral and is imported by this module alone.

**Why this is separate from ``collection.transport.follow_redirects``.** That
function permits a hop only inside the official apex or a declared archive host,
within five hops, keyed on a request-plan entry — semantics ADR-032 hard-binds
to the HubSpot official-web run. The documentation routes cross apexes
(``cloud.google.com`` to ``docs.cloud.google.com``) and need exactly one hop
against an exact pair list. Reusing that function would mean loosening a
hard-bound official-web guarantee for an unrelated purpose, so it is neither
duplicated nor replaced: it remains the sole authority for official-web
collection, and this policy implements its own rule over the same generic
adapter.

**No injectable transport on the public surface.** A caller-supplied transport
could be recorded under the canonical contract identity, which would break
executable-client provenance. The public entry point constructs the committed
adapter itself; offline tests patch module-private seams that are absent from
``__all__`` and are explicitly noncanonical.

**The package reads no clock.** ``run_created_at`` and every retrieval instant
are caller-injected. Calling ``sleep`` for spacing is permitted; reading a wall
clock is not.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit

from ..provenance import WriteOnceError, write_bytes_once
from . import http_adapter
from .publication import canonical_json_bytes
from .documentation_receipt import (
    build_documentation_receipt,
    receipt_bytes,
    validate_receipt_schema_bytes,
)
from .errors import CollectionError

__all__ = [
    "DOCUMENTATION_REASON_CODES",
    "FROZEN_EVIDENCE_ENTRIES",
    "MAX_ENTITY_BYTES_PER_RESPONSE",
    "POLICY_CONTRACT",
    "REDIRECT_STATUSES",
    "RETRIEVAL_TIMESTAMP_MODE",
    "SPACING_SECONDS",
    "TOTAL_ACCEPTED_ENTITY_BYTES_MAX",
    "DocumentationCollectionResult",
    "RetrievalClock",
    "collect_documentation_evidence",
]

# --- frozen routes ------------------------------------------------------------

FROZEN_EVIDENCE_ENTRIES: tuple[dict[str, str], ...] = (
    {
        "evidence_kind": "gemini_thinking",
        "requested_url": "https://cloud.google.com/vertex-ai/generative-ai/docs/thinking",
        "final_url": (
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/"
            "models/thinking"
        ),
    },
    {
        "evidence_kind": "count_tokens",
        "requested_url": (
            "https://cloud.google.com/vertex-ai/generative-ai/docs/multimodal/"
            "get-token-count"
        ),
        "final_url": (
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/"
            "models/capabilities/get-token-count"
        ),
    },
    {
        "evidence_kind": "pricing_standard",
        "requested_url": "https://cloud.google.com/vertex-ai/generative-ai/pricing",
        "final_url": (
            "https://cloud.google.com/gemini-enterprise-agent-platform/"
            "generative-ai/pricing"
        ),
    },
)

REDIRECT_STATUSES: tuple[int, ...] = (301, 308)
TERMINAL_STATUS = 200
SPACING_SECONDS = 2.0
MAX_ENTITY_BYTES_PER_RESPONSE = http_adapter.MAX_ENTITY_BYTES_PER_RESPONSE
# Derived defensive ceiling. Redundant under the current exact-three-entry
# contract -- three documents each strictly under 8 MiB cannot reach 24 MiB --
# and retained only against later entry-count or per-response policy drift.
TOTAL_ACCEPTED_ENTITY_BYTES_MAX = (
    len(FROZEN_EVIDENCE_ENTRIES) * MAX_ENTITY_BYTES_PER_RESPONSE
)
RETRIEVAL_TIMESTAMP_MODE = "caller_injected_request_start_utc_v1"
ACCEPTED_CONTENT_TYPE = "text/html"

POLICY_CONTRACT: dict[str, Any] = {
    "contract": "documentation_acquisition_policy@0.1.0",
    "policy_module": "dynamic_ai_products.collection.documentation_policy",
    "policy_version": "0.1.0",
    "ordered_pairs": [dict(entry) for entry in FROZEN_EVIDENCE_ENTRIES],
    "scheme": "https",
    "max_redirect_hops": 1,
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
}

DOCUMENTATION_REASON_CODES: frozenset[str] = frozenset(
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

# Module-private seams. Absent from __all__: offline tests may patch them, and
# a patched seam is explicitly noncanonical and may write only under tmp_path.
_send_once = http_adapter.send_once
_sleep = time.sleep


class RetrievalClock(Protocol):
    """Caller-injected source of the request-start instant."""

    def __call__(self) -> str:  # pragma: no cover - structural only
        ...


@dataclass(frozen=True)
class DocumentationCollectionResult:
    attempt_id: str
    attempt_root: Path
    completion_status: str
    entries: tuple[dict[str, Any], ...]
    receipt_reference: str | None
    receipt_sha256: str | None


# --- helpers ------------------------------------------------------------------


def _canonical(payload: Any) -> bytes:
    """The repository convention, shared with every other collection artifact."""
    return canonical_json_bytes(payload)


def _require_clean_url(url: str, code: str) -> None:
    split = urlsplit(url)
    if split.scheme != "https" or split.query or split.fragment or "@" in split.netloc:
        raise CollectionError("the URL is not an accepted clean https URL", reason_code=code)


def _parse_utc_instant(value: Any) -> str | None:
    """Lexical **and** semantic: the calendar/time values must be real.

    A regex alone admits ``2026-02-30T09:00:00Z`` and ``2026-07-31T24:00:00Z``,
    which name no instant. Parsing rejects them, and the lexical rule is kept so
    a non-UTC offset cannot slip through a permissive parser.
    """
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
    """``text/html`` with at most one real ``charset`` token, case-insensitively.

    A prefix check would admit ``text/html; boundary=evil`` and ``text/htmlx``;
    a truthiness check on the parameter would admit ``charset==``,
    ``charset=" "`` and ``charset=utf-8=evil``. The grammar is therefore parsed
    and the token validated.
    """
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


def _require_utc_instant(value: Any) -> str:
    parsed = _parse_utc_instant(value)
    if parsed is None:
        raise CollectionError(
            "the retrieval clock returned a value that is not a strict "
            "timezone-aware UTC RFC3339 instant",
            reason_code="retrieval_clock_invalid",
        )
    return parsed


def _blank_entry(entry: dict[str, str], status: str, reason: str | None) -> dict[str, Any]:
    return {
        "evidence_kind": entry["evidence_kind"],
        "requested_url": entry["requested_url"],
        "final_url": entry["final_url"],
        "entry_status": status,
        "redirect_chain": [],
        "http_status": None,
        "content_type": None,
        "content_encoding": None,
        "byte_count": None,
        "content_sha256": None,
        "raw_reference": None,
        "object_disposition": None,
        "retrieval_timestamp": None,
        "failure_reason": reason,
    }


def _require_no_symlink_ancestry(root: Path, target: Path, code: str) -> None:
    """Refuse a symlink anywhere from the root down to the target.

    Checking only the final file would let a symlinked evidence-kind or digest
    directory redirect a write outside the intended root, so every governed
    descendant is inspected.
    """
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
    """Content-address the bytes; create or verifiably reuse. Never overwrite.

    Reuse requires a **regular, non-symlink** file whose re-read digest equals
    its path digest. A matching symlink is refused rather than followed: the
    bytes it points at are not the bytes this path claims to hold.
    """
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
        # No raw filesystem error may cross the public boundary, and no upstream
        # path or message may travel with it.
        raise CollectionError(
            "the content object could not be written", reason_code="write_error"
        ) from None
    return reference, "created"


def _fetch_entry(
    entry: dict[str, str],
    *,
    retrieval_clock: RetrievalClock,
    accepted_total: int,
    spacer: Callable[[], None],
) -> tuple[dict[str, Any], bytes]:
    """One entry: spacing, clock, keylog recheck, redirect hop, terminal document.

    ``spacer`` delays before every send after the very first of the attempt --
    six possible sends, so a full success produces exactly five delays. The
    clock is read once per entry, after any spacing that precedes that entry's
    initial request and immediately before it.
    """
    requested, final = entry["requested_url"], entry["final_url"]
    _require_clean_url(requested, "redirect_location_mismatch")
    _require_clean_url(final, "redirect_location_mismatch")

    spacer()  # before this entry's initial request
    try:
        stamp = retrieval_clock()
    except CollectionError:
        raise
    except Exception:  # noqa: BLE001 - the clock seam is total
        raise CollectionError(
            "the injected retrieval clock failed", reason_code="retrieval_clock_failed"
        ) from None
    stamp = _require_utc_instant(stamp)

    # Rechecked immediately before every client construction: an appearance
    # between sends must stop the attempt, not be inherited from the preflight.
    http_adapter.require_no_tls_keylog()
    hop = _send_once(url=requested, iterate_body=False)
    if hop.final_url != requested:
        raise CollectionError(
            "the transport answered a different request identity",
            reason_code="response_request_identity_mismatch",
        )
    if hop.status == TERMINAL_STATUS:
        raise CollectionError(
            "the frozen route requires one redirect hop; a direct terminal "
            "response is not the authorized route",
            reason_code="direct_terminal_not_permitted",
        )
    if hop.status not in REDIRECT_STATUSES:
        raise CollectionError(
            "the initial response is not an accepted permanent redirect",
            reason_code="redirect_status_invalid",
        )
    location = hop.location
    if not location:
        raise CollectionError(
            "the redirect carries no Location", reason_code="redirect_location_missing"
        )
    if not location.startswith("https://"):
        raise CollectionError(
            "only an absolute https Location is accepted",
            reason_code="redirect_location_not_absolute",
        )
    if location != final:
        raise CollectionError(
            "the Location does not match the frozen final URL",
            reason_code="redirect_location_mismatch",
        )

    spacer()  # between the accepted redirect and its terminal request
    http_adapter.require_no_tls_keylog()
    remaining = TOTAL_ACCEPTED_ENTITY_BYTES_MAX - accepted_total
    terminal = _send_once(
        url=final,
        iterate_body=True,
        max_entity_bytes=min(MAX_ENTITY_BYTES_PER_RESPONSE, max(remaining, 0)),
    )
    if terminal.final_url != final:
        raise CollectionError(
            "the transport answered a different request identity",
            reason_code="response_request_identity_mismatch",
        )
    if terminal.status in REDIRECT_STATUSES or 300 <= terminal.status < 400:
        raise CollectionError(
            "a second redirect is not permitted", reason_code="redirect_chain_too_long"
        )
    if terminal.status != TERMINAL_STATUS:
        raise CollectionError(
            "the terminal response status is not 200",
            reason_code="terminal_status_invalid",
        )
    # The observed header is recorded verbatim; only a parsed copy is validated,
    # so the receipt reports what the server actually sent.
    observed_content_type = terminal.headers.get("content-type") or ""
    if not _content_type_accepted(observed_content_type):
        raise CollectionError(
            "the terminal content type is not accepted",
            reason_code="content_type_invalid",
        )
    payload = terminal.entity_bytes or b""
    if not payload:
        raise CollectionError(
            "the terminal entity body is empty", reason_code="entity_empty"
        )
    if accepted_total + len(payload) > TOTAL_ACCEPTED_ENTITY_BYTES_MAX:
        # Defensive drift branch: unreachable while three entries each cap at
        # 8 MiB and the total is 3 x 8 MiB.
        raise CollectionError(
            "the cumulative accepted entity ceiling would be exceeded",
            reason_code="attempt_byte_ceiling_exceeded",
        )

    record = _blank_entry(entry, "succeeded", None)
    record.update(
        {
            "redirect_chain": [requested, final],
            "http_status": terminal.status,
            "content_type": observed_content_type,
            "content_encoding": terminal.headers.get("content-encoding") or "identity",
            "byte_count": len(payload),
            "retrieval_timestamp": stamp,
        }
    )
    return record, payload


# --- public entry point -------------------------------------------------------


def collect_documentation_evidence(
    *,
    raw_root: str | Path,
    receipt_schema_bytes: bytes,
    code_commit: str,
    run_created_at: str,
    retrieval_clock: RetrievalClock,
    receipt_schema_sha256: object = _SCHEMA_PIN_UNSET,
) -> DocumentationCollectionResult:
    """Acquire the three frozen documentation snapshots, or stop truthfully.

    The only governed route that may publish a terminal receipt. It constructs
    the committed adapter itself and records the contract hashes it actually
    used, so no caller-selectable fake can be represented as the canonical
    collector. There is no ``url`` parameter: the routes are frozen constants.
    """
    # [1] The digest is derived, never claimed. A sentinel default makes this
    # reachable; an unknown keyword would only raise TypeError.
    if receipt_schema_sha256 is not _SCHEMA_PIN_UNSET:
        raise CollectionError(
            "the receipt schema digest is derived from the supplied bytes and "
            "is never accepted from a caller",
            reason_code="receipt_schema_claim_forbidden",
        )
    # [2] Static keylog preflight, before anything exists.
    http_adapter.require_no_tls_keylog()
    # [3] Schema bytes validated; digest derived. No file is re-read later.
    schema_digest = validate_receipt_schema_bytes(receipt_schema_bytes)
    # [4] Contract identities.
    adapter_digest = sha256(http_adapter.adapter_contract_bytes()).hexdigest()
    policy_digest = sha256(_canonical(POLICY_CONTRACT)).hexdigest()
    # [5] Canonical attempt identity.
    if not isinstance(code_commit, str) or not code_commit.strip():
        raise CollectionError("code_commit is required", reason_code="attempt_identity_invalid")
    _require_utc_instant_identity(run_created_at)
    attempt_id = "docattempt-" + sha256(
        _canonical(
            {
                "code_commit": code_commit,
                "run_created_at": run_created_at,
                "adapter_contract_sha256": adapter_digest,
                "policy_contract_sha256": policy_digest,
                "receipt_contract_id": "documentation_collection_receipt@0.1.0",
                "receipt_schema_sha256": schema_digest,
                "ordered_pairs": [dict(e) for e in FROZEN_EVIDENCE_ENTRIES],
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

    for index, entry in enumerate(FROZEN_EVIDENCE_ENTRIES):
        if stopped_at is not None:
            entries.append(_blank_entry(entry, "not_attempted", None))
            continue
        try:
            record, payload = _fetch_entry(
                entry,
                retrieval_clock=retrieval_clock,
                accepted_total=accepted_total,
                spacer=spacer,
            )
            reference, disposition = _persist_object(
                root, entry["evidence_kind"], payload
            )
            record["content_sha256"] = sha256(payload).hexdigest()
            record["raw_reference"] = reference
            record["object_disposition"] = disposition
            accepted_total += len(payload)
            entries.append(record)
        except CollectionError as exc:
            entries.append(_blank_entry(entry, "failed", exc.reason_code))
            stopped_at = index

    completion = "completed" if stopped_at is None else "stopped"
    receipt = build_documentation_receipt(
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
    payload = receipt_bytes(receipt)
    try:
        digest = write_bytes_once(
            attempt_root / reference, payload, what="documentation collection receipt"
        )
    except (WriteOnceError, OSError):
        # Best-effort publication: the storage failure is never masked by a
        # receipt write, and an attempt without a terminal receipt is not
        # authoritative. Content objects already written survive.
        raise CollectionError(
            "the terminal receipt could not be published",
            reason_code="receipt_publication_failed",
        ) from None
    return DocumentationCollectionResult(
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
