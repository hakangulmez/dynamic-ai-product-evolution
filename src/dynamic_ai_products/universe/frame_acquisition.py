"""Fixture-replay EDGAR full-index acquisition (W1, pre-live increment).

Governing documents:
- specs/SPEC-001-company-universe.md (Stage A input acquisition)
- specs/SPEC-003-sec-ingestion.md (hash coverage, no overwrite, error records)
- docs/THESIS_EXECUTION_PLAN.md (W1; W0 gates all live collection)

Acquires a declared request plan of ``master.idx`` URLs through an injected
transport callable and persists write-once raw files plus one write-once,
schema-validated acquisition manifest. This module contains no network code:
the only transport that exists in this increment is a deterministic local
fixture replay, and the manifest truthfully records
``transport_kind = "fixture_replay"`` with the fixture-replay transport's own
contract hash. A real SEC transport contract — live user agent, rate-limit
enforcement, retries, and its client hash — belongs to the later post-W0
live-binding increment and is deliberately absent here.

Request-plan trust boundary: an entry declares only a quarter label and a
URL. The two must agree under the canonical full-index grammar
(``https://www.sec.gov/Archives/edgar/full-index/<YYYY>/QTR<n>/master.idx``),
and the local output filename is derived in code from the validated quarter
label — never read from the plan. Duplicate quarters (and therefore duplicate
local targets), unknown keys, non-SEC hosts, non-https schemes, and anything
outside the grammar are refused before any transport call.

Failure semantics: any redirect status, terminal-URL mismatch, non-200
status, transport exception, or raw-file write failure stops the run, and a
write-once, non-authoritative failure receipt is persisted with a stable
reason code and the attempted planned entry. The receipt covers failures
while acquiring raw planned entries only: a failure while persisting the
manifest itself propagates and leaves the run directory with raw files and no
manifest. Either way no acquisition manifest exists after a failure, and
manifest presence is the sole mark of an authoritative acquisition.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Callable, Literal, Optional

from jsonschema import Draft202012Validator

from ..provenance import WriteOnceError, write_bytes_once
from .freeze import create_run_directory
from .io_utils import read_json
from .models import StrictModel


@dataclass(frozen=True)
class IndexTransportResponse:
    """One transport response as seen by the index acquirer.

    Mirrors the shape of the collection transport's response deliberately
    WITHOUT importing it: the universe package imports neither ``collection``
    nor ``ingestion`` (tests/collection/test_collection_boundaries.py). The
    post-W0 live-binding increment adapts the real transport to this type
    outside the universe package.
    """

    status_code: int
    final_url: str
    content: bytes
    location: str | None = None


PLAN_CONTRACT = "edgar_index_request_plan@0.1.0"
TRANSPORT_KIND_FIXTURE_REPLAY = "fixture_replay"

# The identity of the only transport that exists in this increment. It is NOT
# the live collection client contract: no user agent is sent, no rate limit is
# enforced, and no retry policy applies, because no network request is made.
FIXTURE_REPLAY_TRANSPORT_CONTRACT: dict[str, str] = {
    "transport_kind": TRANSPORT_KIND_FIXTURE_REPLAY,
    "transport_version": "0.1.0",
    "description": (
        "Deterministic local-byte replay keyed by the derived index filename; "
        "no network capability exists in this transport."
    ),
}

ACQUISITION_MANIFEST_FILENAME = "edgar_index_acquisition_manifest.json"
FAILURE_RECEIPT_FILENAME = "acquisition_failure_receipt.json"
ACQUISITION_MANIFEST_SCHEMA_RELATIVE_PATH = Path(
    "schemas/edgar_index_acquisition_manifest.schema.json"
)

INDEX_URL_TEMPLATE = (
    "https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{qtr}/master.idx"
)
_QUARTER_RE = re.compile(r"^(\d{4})-QTR([1-4])$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MIN_INDEX_YEAR = 1993  # EDGAR full-index coverage starts in 1993.
_MAX_INDEX_YEAR = 2100


class AcquisitionPlanError(ValueError):
    """The request plan is malformed or outside the canonical grammar."""


def transport_contract_hash() -> str:
    """SHA-256 over the canonical fixture-replay transport contract."""
    payload = json.dumps(
        FIXTURE_REPLAY_TRANSPORT_CONTRACT,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


class PlannedIndexEntry(StrictModel):
    """One validated plan entry with its code-derived local filename."""

    quarter: str
    year: int
    qtr: int
    url: str
    filename: str


class IndexFileReceipt(StrictModel):
    """Write-once provenance for one acquired raw index file."""

    quarter: str
    url: str
    filename: str
    sha256: str
    byte_count: int
    status_code: int
    retrieved_at: datetime


class AcquisitionFailureReceipt(StrictModel):
    """Non-authoritative record of a failed acquisition run.

    Written write-once into the dead run directory. Its presence, and the
    absence of ``edgar_index_acquisition_manifest.json``, is what marks the
    run as failed: no successful manifest may exist after any failure.
    """

    run_id: str
    request_plan_sha256: str
    transport_kind: Literal["fixture_replay"]
    transport_contract_hash: str
    reason_code: Literal[
        "redirect_refused",
        "terminal_url_mismatch",
        "unexpected_http_status",
        "transport_exception",
        "write_once_refused",
    ]
    detail: str
    attempted_entry: PlannedIndexEntry
    files_acquired_before_failure: list[str]
    failed_at: datetime


@dataclass
class AcquisitionRunResult:
    """Outcome of one acquisition run (dry, failed, or successful)."""

    run_id: str
    run_dir: Path | None
    dry_run: bool
    request_plan_sha256: str
    entries: list[PlannedIndexEntry]
    receipts: list[IndexFileReceipt]
    manifest_path: Path | None = None
    failure: Optional[AcquisitionFailureReceipt] = None
    failure_receipt_path: Path | None = None


def validate_request_plan(payload: object) -> list[PlannedIndexEntry]:
    """Validate the plan and derive every local filename in code.

    Binds the quarter label to the canonical SEC URL exactly; refuses unknown
    keys (so a plan-supplied filename or path can never be trusted), duplicate
    quarters, and duplicate derived local targets.
    """
    if not isinstance(payload, dict):
        raise AcquisitionPlanError("Request plan must be a JSON object.")
    expected_keys = {"plan_contract", "description", "entries"}
    if set(payload) != expected_keys:
        raise AcquisitionPlanError(
            f"Request plan must have exactly the keys {sorted(expected_keys)}; "
            f"got {sorted(payload)}."
        )
    if payload["plan_contract"] != PLAN_CONTRACT:
        raise AcquisitionPlanError(
            f"Unknown plan contract {payload['plan_contract']!r}; "
            f"expected {PLAN_CONTRACT!r}."
        )
    raw_entries = payload["entries"]
    if not isinstance(raw_entries, list) or not raw_entries:
        raise AcquisitionPlanError("Request plan entries must be a non-empty list.")

    entries: list[PlannedIndexEntry] = []
    seen_quarters: set[str] = set()
    seen_filenames: set[str] = set()
    for index, raw in enumerate(raw_entries):
        if not isinstance(raw, dict) or set(raw) != {"quarter", "url"}:
            raise AcquisitionPlanError(
                f"Entry {index} must have exactly the keys ['quarter', 'url']; "
                "local filenames are derived in code and never read from the plan."
            )
        quarter = str(raw["quarter"])
        match = _QUARTER_RE.match(quarter)
        if not match:
            raise AcquisitionPlanError(
                f"Entry {index}: quarter {quarter!r} does not match YYYY-QTRn."
            )
        year, qtr = int(match.group(1)), int(match.group(2))
        if not _MIN_INDEX_YEAR <= year <= _MAX_INDEX_YEAR:
            raise AcquisitionPlanError(
                f"Entry {index}: year {year} outside "
                f"[{_MIN_INDEX_YEAR}, {_MAX_INDEX_YEAR}]."
            )
        expected_url = INDEX_URL_TEMPLATE.format(year=year, qtr=qtr)
        if raw["url"] != expected_url:
            raise AcquisitionPlanError(
                f"Entry {index}: url does not match the canonical full-index "
                f"grammar for {quarter}: expected {expected_url!r}, "
                f"got {raw['url']!r}."
            )
        filename = f"master-{quarter}.idx"
        if "/" in filename or "\\" in filename or ".." in filename:
            raise AcquisitionPlanError(  # unreachable by construction; defensive
                f"Entry {index}: derived filename {filename!r} is unsafe."
            )
        if quarter in seen_quarters:
            raise AcquisitionPlanError(f"Duplicate quarter in plan: {quarter}.")
        if filename in seen_filenames:
            raise AcquisitionPlanError(f"Duplicate local target in plan: {filename}.")
        seen_quarters.add(quarter)
        seen_filenames.add(filename)
        entries.append(
            PlannedIndexEntry(
                quarter=quarter, year=year, qtr=qtr,
                url=expected_url, filename=filename,
            )
        )
    return sorted(entries, key=lambda e: (e.year, e.qtr))


def load_request_plan(path: str | Path) -> tuple[list[PlannedIndexEntry], str]:
    """Load, validate, and hash-pin a request-plan file."""
    plan_path = Path(path)
    if not plan_path.is_file():
        raise AcquisitionPlanError(f"Request plan not found: {plan_path}")
    raw_bytes = plan_path.read_bytes()
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcquisitionPlanError(f"Request plan is not valid JSON: {exc}") from exc
    return validate_request_plan(payload), sha256(raw_bytes).hexdigest()


def filename_for_index_url(url: str) -> str | None:
    """Reverse the canonical grammar: URL -> derived local filename."""
    prefix = "https://www.sec.gov/Archives/edgar/full-index/"
    suffix = "/master.idx"
    if not url.startswith(prefix) or not url.endswith(suffix):
        return None
    middle = url[len(prefix) : -len(suffix)]
    parts = middle.split("/")
    if len(parts) != 2:
        return None
    year, qtr = parts
    quarter = f"{year}-{qtr}"
    if not _QUARTER_RE.match(quarter):
        return None
    return f"master-{quarter}.idx"


def make_fixture_replay_transport(
    replay_dir: str | Path,
) -> Callable[[str], IndexTransportResponse]:
    """Deterministic replay transport serving local bytes for planned URLs.

    A URL outside the canonical grammar or a missing replay file yields a 404
    response, which the runner records as a failed acquisition — never a
    guess, never a substitute byte source.
    """
    directory = Path(replay_dir)

    def transport(url: str) -> IndexTransportResponse:
        filename = filename_for_index_url(url)
        if filename is None:
            return IndexTransportResponse(status_code=404, final_url=url, content=b"")
        path = directory / filename
        if not path.is_file():
            return IndexTransportResponse(status_code=404, final_url=url, content=b"")
        return IndexTransportResponse(
            status_code=200, final_url=url, content=path.read_bytes()
        )

    return transport


def run_index_acquisition(
    *,
    repo_root: str | Path,
    request_plan_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    transport: Callable[[str], IndexTransportResponse],
    clock: Callable[[], datetime] | None = None,
    dry_run: bool = False,
) -> AcquisitionRunResult:
    """Acquire every planned index file, or fail closed with a receipt.

    Only planned URLs are ever passed to the transport. The clock is injected
    so a fixture run's manifest is reproducible byte for byte.
    """
    root = Path(repo_root)
    now = clock or (lambda: datetime.now(timezone.utc))
    if not _RUN_ID_RE.match(run_id):
        raise AcquisitionPlanError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )
    entries, plan_sha256 = load_request_plan(request_plan_path)
    result = AcquisitionRunResult(
        run_id=run_id,
        run_dir=None,
        dry_run=dry_run,
        request_plan_sha256=plan_sha256,
        entries=entries,
        receipts=[],
    )
    if dry_run:
        return result

    run_dir = create_run_directory(output_dir, run_id)
    result.run_dir = run_dir

    def fail(entry: PlannedIndexEntry, reason: str, detail: str) -> AcquisitionRunResult:
        receipt = AcquisitionFailureReceipt(
            run_id=run_id,
            request_plan_sha256=plan_sha256,
            transport_kind=TRANSPORT_KIND_FIXTURE_REPLAY,
            transport_contract_hash=transport_contract_hash(),
            reason_code=reason,  # type: ignore[arg-type]
            detail=detail,
            attempted_entry=entry,
            files_acquired_before_failure=[r.filename for r in result.receipts],
            failed_at=now(),
        )
        payload = (
            json.dumps(receipt.model_dump(mode="json"), indent=2, sort_keys=True)
            + "\n"
        ).encode("utf-8")
        target = run_dir / FAILURE_RECEIPT_FILENAME
        write_bytes_once(target, payload, what="acquisition failure receipt")
        result.failure = receipt
        result.failure_receipt_path = target
        return result

    for entry in entries:
        try:
            response = transport(entry.url)
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
            return fail(entry, "transport_exception", f"{type(exc).__name__}: {exc}")
        if response.status_code in _REDIRECT_STATUSES:
            return fail(
                entry, "redirect_refused",
                f"redirect status {response.status_code} for {entry.url}; "
                "redirects are disabled for index acquisition.",
            )
        if response.status_code != 200:
            return fail(
                entry, "unexpected_http_status",
                f"status {response.status_code} for {entry.url}.",
            )
        if not response.final_url or response.final_url != entry.url:
            return fail(
                entry, "terminal_url_mismatch",
                f"requested {entry.url}, response reports "
                f"{response.final_url!r}.",
            )
        try:
            digest = write_bytes_once(
                run_dir / entry.filename, response.content,
                what=f"raw index file {entry.filename}",
            )
        except WriteOnceError as exc:
            return fail(entry, "write_once_refused", str(exc))
        result.receipts.append(
            IndexFileReceipt(
                quarter=entry.quarter,
                url=entry.url,
                filename=entry.filename,
                sha256=digest,
                byte_count=len(response.content),
                status_code=response.status_code,
                retrieved_at=now(),
            )
        )

    manifest = build_acquisition_manifest(
        repo_root=root,
        run_id=run_id,
        request_plan_sha256=plan_sha256,
        receipts=result.receipts,
        run_timestamp=now(),
    )
    payload = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    manifest_path = run_dir / ACQUISITION_MANIFEST_FILENAME
    write_bytes_once(manifest_path, payload, what="acquisition manifest")
    result.manifest_path = manifest_path
    return result


def build_acquisition_manifest(
    *,
    repo_root: str | Path,
    run_id: str,
    request_plan_sha256: str,
    receipts: list[IndexFileReceipt],
    run_timestamp: datetime,
) -> dict:
    """Assemble and schema-validate the acquisition manifest."""
    root = Path(repo_root)
    schema_versions = read_json(root / "schemas" / "schema_version_manifest.json")[
        "schemas"
    ]
    manifest = {
        "run_id": run_id,
        "request_plan_sha256": request_plan_sha256,
        "transport_kind": TRANSPORT_KIND_FIXTURE_REPLAY,
        "transport_contract_hash": transport_contract_hash(),
        "files": [receipt.model_dump(mode="json") for receipt in receipts],
        "counts": {
            "planned_entries": len(receipts),
            "files_acquired": len(receipts),
        },
        "run_timestamp": run_timestamp.isoformat(),
        "schema_versions": {
            "edgar_index_acquisition_manifest": schema_versions[
                "edgar_index_acquisition_manifest"
            ]
        },
        "limitations": [
            "Fixture-replay acquisition: bytes were served from local fixture "
            "files; no network request was made and no live SEC transport "
            "exists in this increment (W0 gate).",
            "This manifest is not evidence of live EDGAR retrieval.",
        ],
    }
    schema = read_json(root / ACQUISITION_MANIFEST_SCHEMA_RELATIVE_PATH)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(manifest), key=lambda e: e.json_path)
    if errors:
        details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
        raise ValueError(
            f"Acquisition manifest violates the canonical schema: {details}"
        )
    return manifest
