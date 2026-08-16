"""Baseline filing-document acquisition (W2-B, fixture-first; canary-gated live).

Governing documents:
- docs/methodology/SOFTWARE_FIRM_UNIVERSE.md (Stage 00C baseline packets)
- docs/DECISION_LOG.md ADR-087 (FRAME_v1 freeze), ADR-088 (baseline carrier),
  ADR-089 (this design)

Acquires the baseline annual-report document of each planned baseline
candidate through an injected transport callable and preserves the raw bytes
write-once with hash receipts. This increment acquires documents only: no
section extraction, no packet, no classification, no tier, no model call.

**URL derivation (ADR-089).** ``sec_filename`` from the FRAME row is
provenance and a validation input; it is never concatenated into a URL.
Every planned carrier row must carry a ``sec_filename`` of the full-index
shape ``edgar/data/<cik>/<accession>.txt`` whose embedded CIK equals the
row's own CIK and whose embedded accession equals the entry's accession —
three separate refusals. The requested URL is then *derived* in the SEC
filing-directory form already used on the Pilot 0 path::

    https://www.sec.gov/Archives/edgar/data/<cik_without_leading_zeros>/
        <accession_without_dashes>/<accession_with_dashes>.txt

**Document unit and shared accessions.** The unit is the accession, not the
firm: a combined filing shared by several filers is requested once and
mapped to every carrier row that selected it. The directory CIK is the
*lowest* CIK among the sharing rows — the accession's own 10-digit prefix is
frequently a filing agent that owns no EDGAR directory, so it can never be
used to build the path.

**Byte ceiling.** ``max_document_bytes`` is an explicit, required plan field
(never an implicit default), and it bounds the *download*, not merely the
write. Enforcement lives in the transport
(:mod:`dynamic_ai_products.sec_document_transport` for live runs, the
fixture transport below for replay): an oversized declared ``Content-Length``
refuses before any body chunk is read, and otherwise the first chunk that
would cross the ceiling is never retained and the stream is closed. This
runner binds the two together — ``transport_max_bytes`` must equal the
plan's ceiling, or the run is refused before a single request — classifies
the refusal into an all-or-nothing failure receipt, and keeps a defensive
post-hoc length assertion for any transport that ignores its own bound. The
enforced values are recorded in every receipt-bearing manifest.

This module contains no network code. The live transport is the committed
``sec_live`` policy wrapper, built outside the universe package and injected
with its identity as data; the fixture-replay transport defined here serves
local document bytes. DERA plays no role here and is never imported.

All-or-nothing: the first failed document ends the run with a write-once
failure receipt, leaving no acquisition manifest. Manifest presence is the
sole mark of an authoritative acquisition. Batched, resumable acquisition of
the full candidate cohort is deliberately absent; it belongs to the W3
download-queue increment.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from jsonschema import Draft202012Validator

from ..provenance import WriteOnceError, write_bytes_once
from .frame_acquisition import (
    FIXTURE_REPLAY_TRANSPORT_IDENTITY,
    TRANSPORT_KIND_SEC_LIVE,
    TransportIdentity,
)
from .freeze import create_run_directory
from .identifiers import IdentifierError, normalize_accession, normalize_cik
from .io_utils import read_json, sha256_bytes
from .models import StrictModel

DOCUMENT_PLAN_CONTRACT = "baseline_document_request_plan@0.1.0"
ADMITTED_COHORT = "baseline_candidates"
ADMITTED_FORMS = ("10-K", "10-KT", "20-F", "40-F")
ADMITTED_KINDS = ("regular", "shared")
ADMITTED_STRATA = ("domestic", "fpi_extension")
CANONICAL_BASE_URL = "https://www.sec.gov/Archives/"

DOCUMENT_ACQUISITION_MANIFEST_FILENAME = "baseline_document_acquisition_manifest.json"
DOCUMENT_FAILURE_RECEIPT_FILENAME = "baseline_document_failure_receipt.json"
DOCUMENT_ACQUISITION_SCHEMA_RELATIVE_PATH = Path(
    "schemas/baseline_document_acquisition_manifest.schema.json"
)
DOCUMENT_ACQUISITION_V2_SCHEMA_RELATIVE_PATH = Path(
    "schemas/baseline_document_acquisition_manifest.v2.schema.json"
)

_SEC_FILENAME_RE = re.compile(r"^edgar/data/(\d{1,10})/(\d{10}-\d{2}-\d{6})\.txt$")
_ACCESSION_IN_URL_RE = re.compile(r"(\d{10}-\d{2}-\d{6})\.txt$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class DocumentPlanError(ValueError):
    """The baseline-document request plan is malformed or out of grammar."""


@dataclass
class DocumentTransportResponse:
    """One document-transport response as seen by the acquirer.

    Mirrors the shape a bounded streaming transport produces WITHOUT
    importing it: the universe package imports neither ``collection`` nor
    ``ingestion`` and contains no network code, so the live transport is
    built outside this package and adapted to this type (the same
    pin-shape-without-import stance as ``IndexTransportResponse``).

    ``ceiling_refusal`` is the transport's own statement that it stopped:
    ``content_length_preflight`` (an oversized declared length, no body read)
    or ``stream_exceeded`` (a chunk would have crossed the ceiling). On
    either, ``content`` is empty — the partial body is discarded, never
    returned. ``bytes_received`` is what crossed the transport, which for a
    chunked refusal may exceed the ceiling by up to one chunk.
    """

    status_code: int
    final_url: str
    content: bytes
    location: str | None = None
    declared_content_length: int | None = None
    bytes_received: int = 0
    ceiling_refusal: str | None = None


def canonical_document_url(directory_cik: str, accession: str) -> str:
    """Derive the SEC filing-directory URL for one accession.

    ``directory_cik`` is a canonical CIK; its leading zeros are stripped for
    the path, and the accession appears twice — once undashed as the filing
    directory, once dashed as the complete-submission filename.
    """
    cik_path = str(int(normalize_cik(directory_cik)))
    dashed = normalize_accession(accession)
    undashed = dashed.replace("-", "")
    return f"{CANONICAL_BASE_URL}edgar/data/{cik_path}/{undashed}/{dashed}.txt"


class PlannedCarrierRow(StrictModel):
    """One carrier row mapped onto a planned document."""

    stratum: str
    cik: str
    sec_filename: str


class PlannedDocument(StrictModel):
    """One validated document request with its code-derived URL."""

    form: str
    kind: str
    accession: str
    directory_cik: str
    url: str
    document_filename: str
    carrier_rows: list[PlannedCarrierRow]


class DocumentReceipt(StrictModel):
    """Write-once provenance for one acquired document."""

    accession: str
    form: str
    kind: str
    directory_cik: str
    url: str
    status_code: int
    document_filename: str
    document_sha256: str
    byte_count: int
    declared_content_length: Optional[int]
    mapped_carrier_rows: int
    retrieved_at: datetime


class DocumentAcquisitionFailureReceipt(StrictModel):
    """The explicit, immutable record of a refused or failed acquisition."""

    run_id: str
    request_plan_sha256: str
    transport_kind: str
    transport_contract_hash: str
    reason_code: str
    detail: str
    attempted_accession: str
    attempted_url: str
    documents_acquired_before_failure: list[str]
    failed_at: datetime


@dataclass
class DocumentAcquisitionResult:
    run_id: str
    run_dir: Path | None
    dry_run: bool
    request_plan_sha256: str
    entries: list[PlannedDocument]
    receipts: list[DocumentReceipt] = field(default_factory=list)
    manifest_path: Path | None = None
    failure: Optional[DocumentAcquisitionFailureReceipt] = None
    failure_receipt_path: Path | None = None


def _validate_sec_filename(
    sec_filename: str, row_cik: str, accession: str, where: str
) -> None:
    """Three separate refusals: shape, CIK consistency, accession consistency."""
    match = _SEC_FILENAME_RE.match(sec_filename)
    if match is None:
        raise DocumentPlanError(
            f"{where}: sec_filename {sec_filename!r} does not have the "
            "full-index shape edgar/data/<cik>/<accession>.txt."
        )
    embedded_cik, embedded_accession = match.group(1), match.group(2)
    if int(embedded_cik) != int(normalize_cik(row_cik)):
        raise DocumentPlanError(
            f"{where}: sec_filename {sec_filename!r} embeds CIK "
            f"{embedded_cik}, which is not the row CIK {row_cik}."
        )
    if normalize_accession(embedded_accession) != accession:
        raise DocumentPlanError(
            f"{where}: sec_filename {sec_filename!r} embeds accession "
            f"{embedded_accession}, which is not the entry accession "
            f"{accession}."
        )


def validate_document_request_plan(
    payload: object,
) -> tuple[list[PlannedDocument], dict]:
    """Validate a plan payload and return (planned documents, plan fields)."""
    if not isinstance(payload, dict):
        raise DocumentPlanError("Request plan must be a JSON object.")
    if payload.get("plan_contract") != DOCUMENT_PLAN_CONTRACT:
        raise DocumentPlanError(
            f"Request plan must declare {DOCUMENT_PLAN_CONTRACT!r}."
        )
    for key in ("description", "cohort", "base_url", "max_document_bytes",
                "provenance", "documents"):
        if key not in payload:
            raise DocumentPlanError(f"Request plan is missing {key!r}.")
    if payload["cohort"] != ADMITTED_COHORT:
        raise DocumentPlanError(
            f"Only the {ADMITTED_COHORT!r} cohort is acquired; post-baseline "
            "entrants carry no baseline accession."
        )
    if payload["base_url"] != CANONICAL_BASE_URL:
        raise DocumentPlanError(
            f"Plan base_url must be {CANONICAL_BASE_URL!r}; URLs are derived "
            "in code, never taken from the plan."
        )
    ceiling = payload["max_document_bytes"]
    if not isinstance(ceiling, int) or isinstance(ceiling, bool) or ceiling <= 0:
        raise DocumentPlanError(
            "max_document_bytes must be an explicit positive integer; it is "
            "never defaulted in code."
        )
    provenance = payload["provenance"]
    if not isinstance(provenance, dict):
        raise DocumentPlanError("Plan provenance must be an object.")
    for key in ("carrier_run_id", "carrier_manifest_sha256",
                "freeze_record_sha256"):
        value = provenance.get(key)
        if not isinstance(value, str) or not value.strip():
            raise DocumentPlanError(f"Plan provenance is missing {key!r}.")

    documents = payload["documents"]
    if not isinstance(documents, list) or not documents:
        raise DocumentPlanError("Plan documents must be a non-empty array.")

    entries: list[PlannedDocument] = []
    seen_accessions: set[str] = set()
    for index, raw in enumerate(documents):
        where = f"documents[{index}]"
        if not isinstance(raw, dict):
            raise DocumentPlanError(f"{where} must be an object.")
        for key in ("form", "kind", "accession", "directory_cik",
                    "carrier_rows"):
            if key not in raw:
                raise DocumentPlanError(f"{where} is missing {key!r}.")
        if raw["form"] not in ADMITTED_FORMS:
            raise DocumentPlanError(
                f"{where}: form {raw['form']!r} is outside the admitted "
                f"annual forms {list(ADMITTED_FORMS)}."
            )
        if raw["kind"] not in ADMITTED_KINDS:
            raise DocumentPlanError(
                f"{where}: kind {raw['kind']!r} must be one of "
                f"{list(ADMITTED_KINDS)}."
            )
        try:
            accession = normalize_accession(raw["accession"])
        except IdentifierError as exc:
            raise DocumentPlanError(f"{where}: {exc}") from exc
        if accession in seen_accessions:
            raise DocumentPlanError(
                f"{where}: accession {accession} appears in more than one "
                "entry; the document unit is the accession and shared "
                "filings are requested once."
            )
        seen_accessions.add(accession)

        rows_raw = raw["carrier_rows"]
        if not isinstance(rows_raw, list) or not rows_raw:
            raise DocumentPlanError(
                f"{where}: carrier_rows must be a non-empty array proving "
                "which firms map to this document."
            )
        rows: list[PlannedCarrierRow] = []
        seen_rows: set[tuple[str, str]] = set()
        for row_index, row_raw in enumerate(rows_raw):
            row_where = f"{where}.carrier_rows[{row_index}]"
            if not isinstance(row_raw, dict):
                raise DocumentPlanError(f"{row_where} must be an object.")
            for key in ("stratum", "cik", "sec_filename"):
                if key not in row_raw:
                    raise DocumentPlanError(f"{row_where} is missing {key!r}.")
            if row_raw["stratum"] not in ADMITTED_STRATA:
                raise DocumentPlanError(
                    f"{row_where}: stratum {row_raw['stratum']!r} must be one "
                    f"of {list(ADMITTED_STRATA)}."
                )
            try:
                row_cik = normalize_cik(row_raw["cik"])
            except IdentifierError as exc:
                raise DocumentPlanError(f"{row_where}: {exc}") from exc
            _validate_sec_filename(
                str(row_raw["sec_filename"]), row_cik, accession, row_where
            )
            key = (row_raw["stratum"], row_cik)
            if key in seen_rows:
                raise DocumentPlanError(
                    f"{row_where}: duplicate carrier row {key} on one document."
                )
            seen_rows.add(key)
            rows.append(
                PlannedCarrierRow(
                    stratum=row_raw["stratum"],
                    cik=row_cik,
                    sec_filename=str(row_raw["sec_filename"]),
                )
            )
        if raw["kind"] == "regular" and len(rows) != 1:
            raise DocumentPlanError(
                f"{where}: a regular document maps exactly one carrier row, "
                f"got {len(rows)}."
            )
        if raw["kind"] == "shared" and len(rows) < 2:
            raise DocumentPlanError(
                f"{where}: a shared document maps more than one carrier row, "
                f"got {len(rows)}."
            )
        try:
            directory_cik = normalize_cik(raw["directory_cik"])
        except IdentifierError as exc:
            raise DocumentPlanError(f"{where}: {exc}") from exc
        lowest = min(row.cik for row in rows)
        if directory_cik != lowest:
            raise DocumentPlanError(
                f"{where}: directory_cik {directory_cik} is not the lowest "
                f"mapped CIK {lowest}; the filing-directory path always uses "
                "the lowest sharing CIK."
            )
        entries.append(
            PlannedDocument(
                form=raw["form"],
                kind=raw["kind"],
                accession=accession,
                directory_cik=directory_cik,
                url=canonical_document_url(directory_cik, accession),
                document_filename=f"{accession}.txt",
                carrier_rows=rows,
            )
        )

    fields = {
        "description": str(payload["description"]),
        "cohort": ADMITTED_COHORT,
        "base_url": CANONICAL_BASE_URL,
        "max_document_bytes": ceiling,
        "provenance": {
            "carrier_run_id": provenance["carrier_run_id"],
            "carrier_manifest_sha256": provenance["carrier_manifest_sha256"],
            "freeze_record_sha256": provenance["freeze_record_sha256"],
        },
    }
    return entries, fields


def load_document_request_plan(
    path: str | Path,
) -> tuple[list[PlannedDocument], dict, str]:
    plan_path = Path(path)
    if not plan_path.is_file():
        raise DocumentPlanError(f"Document request plan not found: {plan_path}")
    raw = plan_path.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DocumentPlanError(
            f"Document request plan is not valid JSON: {exc}"
        ) from exc
    entries, fields = validate_document_request_plan(payload)
    return entries, fields, sha256_bytes(raw)


def make_document_fixture_replay_transport(
    replay_dir: str | Path, *, max_bytes: int,
) -> Callable[[str], DocumentTransportResponse]:
    """Deterministic replay transport serving local document bytes.

    The accession is recovered from the derived URL; a URL without one, or a
    missing replay file, yields 404, which the runner records as a failure.
    The ceiling is enforced the same way the live transport enforces it and
    for the same reason: the on-disk size stands in for the declared length,
    so an oversized fixture is refused *before* its bytes are read, and the
    refusal travels the identical code path in the runner.
    """
    directory = Path(replay_dir)
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise DocumentPlanError(
            "max_bytes must be an explicit positive integer; the document "
            "ceiling is plan-owned and never defaulted."
        )

    def transport(url: str) -> DocumentTransportResponse:
        match = _ACCESSION_IN_URL_RE.search(url)
        if match is None:
            return DocumentTransportResponse(
                status_code=404, final_url=url, content=b""
            )
        path = directory / f"{match.group(1)}.txt"
        if not path.is_file():
            return DocumentTransportResponse(
                status_code=404, final_url=url, content=b""
            )
        size = path.stat().st_size
        if size > max_bytes:
            return DocumentTransportResponse(
                status_code=200,
                final_url=url,
                content=b"",
                declared_content_length=size,
                bytes_received=0,
                ceiling_refusal="content_length_preflight",
            )
        content = path.read_bytes()
        return DocumentTransportResponse(
            status_code=200,
            final_url=url,
            content=content,
            declared_content_length=size,
            bytes_received=len(content),
        )

    return transport


def run_document_acquisition(
    *,
    repo_root: str | Path,
    request_plan_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    transport: Callable[[str], DocumentTransportResponse],
    transport_max_bytes: int,
    clock: Callable[[], datetime] | None = None,
    dry_run: bool = False,
    transport_identity: TransportIdentity | None = None,
) -> DocumentAcquisitionResult:
    """Acquire every planned baseline document, or fail closed.

    ``transport_max_bytes`` is the ceiling the injected transport was built
    with. It must equal the plan's ``max_document_bytes``: a transport bound
    to a different value is refused here, before any request, rather than
    silently downloading past the declared ceiling.
    """
    root = Path(repo_root)
    now = clock or (lambda: datetime.now(timezone.utc))
    identity = transport_identity or FIXTURE_REPLAY_TRANSPORT_IDENTITY
    if not _RUN_ID_RE.match(run_id):
        raise DocumentPlanError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )
    entries, fields, plan_sha256 = load_document_request_plan(request_plan_path)
    if transport_max_bytes != fields["max_document_bytes"]:
        raise DocumentPlanError(
            f"Transport ceiling {transport_max_bytes} does not equal the "
            f"plan's max_document_bytes {fields['max_document_bytes']}; the "
            "transport must enforce exactly the declared ceiling."
        )
    result = DocumentAcquisitionResult(
        run_id=run_id, run_dir=None, dry_run=dry_run,
        request_plan_sha256=plan_sha256, entries=entries,
    )
    if dry_run:
        return result

    ceiling = fields["max_document_bytes"]
    run_dir = create_run_directory(output_dir, run_id)
    result.run_dir = run_dir

    def fail(
        entry: PlannedDocument, reason: str, detail: str
    ) -> DocumentAcquisitionResult:
        receipt = DocumentAcquisitionFailureReceipt(
            run_id=run_id,
            request_plan_sha256=plan_sha256,
            transport_kind=identity.kind,
            transport_contract_hash=identity.contract_hash(),
            reason_code=reason,
            detail=detail,
            attempted_accession=entry.accession,
            attempted_url=entry.url,
            documents_acquired_before_failure=[
                r.accession for r in result.receipts
            ],
            failed_at=now(),
        )
        payload = (
            json.dumps(receipt.model_dump(mode="json"), indent=2, sort_keys=True)
            + "\n"
        ).encode("utf-8")
        target = run_dir / DOCUMENT_FAILURE_RECEIPT_FILENAME
        write_bytes_once(
            target, payload, what="baseline document failure receipt"
        )
        result.failure = receipt
        result.failure_receipt_path = target
        return result

    output_hashes: dict[str, str] = {}
    for entry in entries:
        try:
            response = transport(entry.url)
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
            return fail(entry, "transport_exception", f"{type(exc).__name__}: {exc}")
        if response.ceiling_refusal is not None:
            declared = response.declared_content_length
            return fail(
                entry, "document_over_ceiling",
                f"transport refused {entry.url} by "
                f"{response.ceiling_refusal}: declared_content_length="
                f"{declared}, bytes_received={response.bytes_received}, "
                f"plan ceiling {ceiling}. No body was retained or persisted.",
            )
        if response.status_code in _REDIRECT_STATUSES:
            return fail(
                entry, "redirect_refused",
                f"redirect status {response.status_code} for {entry.url}; "
                "redirects are disabled for document acquisition.",
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
        if len(response.content) > ceiling:
            # Defensive only: enforcement is the transport's, which never
            # retains a body beyond the ceiling. Reaching here means an
            # injected transport ignored the bound it was built with.
            return fail(
                entry, "document_over_ceiling",
                f"transport returned {len(response.content)} bytes despite "
                f"the {ceiling}-byte ceiling for {entry.url}; nothing "
                "persisted.",
            )
        try:
            document_sha = write_bytes_once(
                run_dir / entry.document_filename, response.content,
                what=f"raw baseline document {entry.document_filename}",
            )
        except WriteOnceError as exc:
            return fail(entry, "write_once_refused", str(exc))
        output_hashes[entry.document_filename] = document_sha
        result.receipts.append(
            DocumentReceipt(
                accession=entry.accession,
                form=entry.form,
                kind=entry.kind,
                directory_cik=entry.directory_cik,
                url=entry.url,
                status_code=response.status_code,
                document_filename=entry.document_filename,
                document_sha256=document_sha,
                byte_count=len(response.content),
                declared_content_length=response.declared_content_length,
                mapped_carrier_rows=len(entry.carrier_rows),
                retrieved_at=now(),
            )
        )

    manifest = build_document_acquisition_manifest(
        repo_root=root,
        run_id=run_id,
        request_plan_sha256=plan_sha256,
        fields=fields,
        entries=entries,
        receipts=result.receipts,
        output_hashes=output_hashes,
        run_timestamp=now(),
        transport_identity=identity,
    )

    manifest_payload = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    manifest_path = run_dir / DOCUMENT_ACQUISITION_MANIFEST_FILENAME
    write_bytes_once(
        manifest_path, manifest_payload, what="baseline document acquisition manifest"
    )
    result.manifest_path = manifest_path
    return result


def _ceiling_enforcement(
    max_document_bytes: int, transport_identity: TransportIdentity
) -> dict:
    """Describe how the ceiling was enforced by the transport that ran.

    A streaming transport declares its chunk size, so the manifest can state
    the exact transport-level upper bound: one chunk may straddle the
    ceiling, hence ``max_document_bytes + stream_chunk_bytes``. A bounded
    local read (fixture replay) never exceeds the ceiling at all.
    """
    contract = transport_identity.contract
    if contract.get("streaming") is True:
        chunk = int(contract["stream_chunk_bytes"])
        return {
            "max_document_bytes": max_document_bytes,
            "mechanism": "streaming_chunk_bound",
            "content_length_preflight": True,
            "stream_chunk_bytes": chunk,
            "max_transport_bytes": max_document_bytes + chunk,
        }
    return {
        "max_document_bytes": max_document_bytes,
        "mechanism": "bounded_local_read",
        "content_length_preflight": True,
        "stream_chunk_bytes": None,
        "max_transport_bytes": max_document_bytes,
    }


def build_document_acquisition_manifest(
    *,
    repo_root: str | Path,
    run_id: str,
    request_plan_sha256: str,
    fields: dict,
    entries: list[PlannedDocument],
    receipts: list[DocumentReceipt],
    output_hashes: dict[str, str],
    run_timestamp: datetime,
    transport_identity: TransportIdentity,
) -> dict:
    """Assemble and schema-validate the acquisition manifest (v0.1 or v0.2)."""
    root = Path(repo_root)
    schema_versions = read_json(root / "schemas" / "schema_version_manifest.json")[
        "schemas"
    ]
    live = transport_identity.kind == TRANSPORT_KIND_SEC_LIVE
    mapping = [
        {
            "stratum": row.stratum,
            "cik": row.cik,
            "accession": entry.accession,
            "sec_filename": row.sec_filename,
            "document_filename": entry.document_filename,
        }
        for entry in entries
        for row in entry.carrier_rows
    ]
    mapping.sort(key=lambda item: (item["stratum"], item["cik"]))
    forms: dict[str, int] = {}
    for entry in entries:
        forms[entry.form] = forms.get(entry.form, 0) + 1
    manifest: dict = {
        "run_id": run_id,
        "request_plan_sha256": request_plan_sha256,
        "plan_contract": DOCUMENT_PLAN_CONTRACT,
        "cohort": fields["cohort"],
        "base_url": fields["base_url"],
        "max_document_bytes": fields["max_document_bytes"],
        "ceiling_enforcement": _ceiling_enforcement(
            fields["max_document_bytes"], transport_identity
        ),
        "carrier_provenance": fields["provenance"],
        "transport_kind": transport_identity.kind,
        "transport_contract_hash": transport_identity.contract_hash(),
        "documents": [receipt.model_dump(mode="json") for receipt in receipts],
        "firm_document_mapping": mapping,
        "counts": {
            "planned_documents": len(entries),
            "documents_acquired": len(receipts),
            "mapped_carrier_rows": len(mapping),
            "regular_documents": sum(
                1 for e in entries if e.kind == "regular"
            ),
            "shared_documents": sum(1 for e in entries if e.kind == "shared"),
            "documents_by_form": forms,
        },
        "output_hashes": output_hashes,
        "run_timestamp": run_timestamp.isoformat(),
        "limitations": [
            "Documents only: no section extraction, no packet, no screen, no "
            "classification, and no tier is produced by this run.",
            "sec_filename is provenance and a validation input; every URL is "
            "derived in code in the SEC filing-directory form (ADR-089).",
            "The document unit is the accession: a shared combined filing is "
            "requested once and mapped to every carrier row that selected it.",
            "All-or-nothing: no partial run is authoritative, and this "
            "runner has no resume; batched acquisition of the full candidate "
            "cohort belongs to the W3 download queue.",
            "The ceiling bounds the download, not merely the write: an "
            "oversized declared Content-Length refuses before any body chunk "
            "is read, and the first chunk that would cross the ceiling is "
            "never retained. A streamed refusal may receive up to one chunk "
            "beyond the ceiling; nothing beyond it is ever retained.",
            "Post-baseline entrants are out of scope here: they carry no "
            "baseline accession.",
        ],
    }
    if live:
        manifest["transport_contract"] = dict(transport_identity.contract)
        manifest["schema_versions"] = {
            "baseline_document_acquisition_manifest_v2": schema_versions[
                "baseline_document_acquisition_manifest_v2"
            ]
        }
        schema_path = DOCUMENT_ACQUISITION_V2_SCHEMA_RELATIVE_PATH
    else:
        manifest["schema_versions"] = {
            "baseline_document_acquisition_manifest": schema_versions[
                "baseline_document_acquisition_manifest"
            ]
        }
        manifest["limitations"].insert(
            0,
            "Fixture-replay acquisition: bytes were served from local "
            "fixture documents; no network request was made.",
        )
        schema_path = DOCUMENT_ACQUISITION_SCHEMA_RELATIVE_PATH
    schema = read_json(root / schema_path)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest),
        key=lambda e: e.json_path,
    )
    if errors:
        details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
        raise ValueError(
            "Baseline document acquisition manifest violates the canonical "
            f"schema: {details}"
        )
    return manifest
