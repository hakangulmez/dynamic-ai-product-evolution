"""Filing-index metadata probe (W2-C-alpha; fixture-first, canary-gated).

Governing documents:
- docs/DECISION_LOG.md ADR-089 (bounded document acquisition), ADR-090 (this
  probe)
- docs/methodology/SOFTWARE_FIRM_UNIVERSE.md (Stage 00C baseline packets)

**What this increment establishes, and nothing more.** A two-hop baseline
packet route needs a filing-directory metadata source that names the primary
annual-report document *by form type*. This module proves — or refuses — that
one endpoint supplies it:

    https://www.sec.gov/Archives/edgar/data/<cik_without_leading_zeros>/
        <accession_without_dashes>/<accession_with_dashes>-index.htm

It acquires no primary document, builds no packet, and authorizes nothing
downstream. Its manifest is evidence about a URL grammar, not about a firm.

**Why not the alternatives.** Two candidates were eliminated from the already
acquired 12-document submission canary, offline: ``FilingSummary.xml`` is
declared ``TYPE=XML`` in all twelve filings and names no form type, and the
SGML ``<SEC-HEADER>`` block carries no per-document list at all — the
``<TYPE>``/``<FILENAME>`` pairs that select a primary uniquely live only in
the full submission text file, which the two-hop route must never download.
``index.json`` is a *separately authorized* fallback and is never requested
by this module.

**Selection is deterministic and fails closed.** The Document Format Files
table is identified by its ``summary`` attribute or an explicitly associated
heading — never by column shape alone, since the same page carries a Data
Files table with the same Document and Type columns and may place it first —
and the primary is the single row whose
declared type equals the planned annual form. Zero matches, more than one
match, a sole match that is not HTML, an unparseable table, or a filename
that disagrees with the plan's recorded ground truth each refuse with a
distinct reason code. Nothing is guessed from a filename convention: the
measured corpus contains ``form10-kt.htm`` and ``lub-20220531.htm``, which no
ticker-and-date pattern would match.

**Ceiling.** ``max_metadata_bytes`` is an explicit, required plan field — never
defaulted in code. The transport must be constructed with exactly that bound,
and a transport bound to any other value is refused *before a request is
made*. Enforcement itself lives in the injected transport (streaming chunk
bound with a Content-Length preflight, ADR-089), and the enforced values are
recorded in the manifest.

This module contains no network code. The live transport is the committed
bounded streaming wrapper built outside the universe package and injected with
its identity as data; the fixture-replay transport defined here serves local
index pages. Fixture runs write the v0.1 manifest; ``sec_live`` runs write the
v0.2 successor that additionally embeds the transport contract whose hash it
records. Neither schema admits the other transport.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Optional

from jsonschema import Draft202012Validator

from ..provenance import WriteOnceError, write_bytes_once
from .document_acquisition import DocumentTransportResponse
from .frame_acquisition import (
    FIXTURE_REPLAY_TRANSPORT_IDENTITY,
    TRANSPORT_KIND_SEC_LIVE,
    TransportIdentity,
)
from .freeze import create_run_directory
from .identifiers import IdentifierError, normalize_accession, normalize_cik
from .io_utils import read_json, sha256_bytes

PROBE_PLAN_CONTRACT = "filing_index_probe_plan@0.1.0"
DOCUMENT_FORMAT_TABLE_IDENTITY = "document format files"
CANONICAL_BASE_URL = "https://www.sec.gov/Archives/"
ADMITTED_FORMS = ("10-K", "10-KT")
HTML_SUFFIXES = (".htm", ".html")

PROBE_MANIFEST_FILENAME = "filing_index_probe_manifest.json"
PROBE_FAILURE_RECEIPT_FILENAME = "filing_index_probe_failure_receipt.json"
PROBE_SCHEMA_RELATIVE_PATH = Path(
    "schemas/filing_index_probe_manifest.schema.json"
)
PROBE_V2_SCHEMA_RELATIVE_PATH = Path(
    "schemas/filing_index_probe_manifest.v2.schema.json"
)

_ACCESSION_IN_INDEX_URL_RE = re.compile(r"(\d{10}-\d{2}-\d{6})-index\.htm$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_WS_RE = re.compile(r"\s+")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ProbePlanError(ValueError):
    """The probe plan is malformed or outside the enforced grammar."""


def canonical_filing_index_url(directory_cik: str, accession: str) -> str:
    """Derive the filing-index URL for one accession.

    The accession appears twice — once undashed as the filing directory, once
    dashed in the page filename — and the directory CIK carries no leading
    zeros. A URL ending in ``<accession>.txt`` is unreachable by construction:
    this route never addresses the full submission.
    """
    cik_path = str(int(normalize_cik(directory_cik)))
    dashed = normalize_accession(accession)
    undashed = dashed.replace("-", "")
    return (
        f"{CANONICAL_BASE_URL}edgar/data/{cik_path}/{undashed}/"
        f"{dashed}-index.htm"
    )


# --- Document Format Files table parsing ------------------------------------


@dataclass
class IndexTableRow:
    """One parsed row of the Document Format Files table."""

    document: str
    document_type: str
    size: Optional[int] = None


class _ParsedTable:
    """One HTML table with the identity evidence that precedes it."""

    def __init__(self, summary: str, preceding_heading: str) -> None:
        self.summary = summary
        self.preceding_heading = preceding_heading
        self.rows: list[list[str]] = []

    def is_document_format_table(self) -> bool:
        """True only for the table SEC identifies as Document Format Files.

        Column shape is never sufficient: the same page carries a Data Files
        table with Document and Type columns, and a page may place it first.
        Identity comes from the table's own ``summary`` attribute or from an
        explicit heading immediately associated with it.
        """
        target = DOCUMENT_FORMAT_TABLE_IDENTITY
        return (
            self.summary.strip().lower() == target
            or self.preceding_heading.strip().lower() == target
        )


class _DocumentTableParser(HTMLParser):
    """Collect every HTML table with its summary and preceding heading.

    Anchor text is preferred for a cell that contains a link, because the
    Document cell renders the filename as a link and may carry additional
    viewer markup around it.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[_ParsedTable] = []
        self._table: _ParsedTable | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._anchor: list[str] | None = None
        self._recent_text: str = ""

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "table":
            summary = ""
            for key, value in attrs:
                if key.lower() == "summary" and value:
                    summary = value
            self._table = _ParsedTable(summary, self._recent_text)
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
            self._anchor = None
        elif tag == "a" and self._cell is not None:
            self._anchor = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._cell is not None and self._anchor is not None:
            text = "".join(self._anchor).strip()
            if text:
                self._cell = [text]
            self._anchor = None
        elif tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(_WS_RE.sub(" ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._table is not None and self._row is not None:
            self._table.rows.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None
            self._recent_text = ""

    def handle_data(self, data: str) -> None:
        if self._anchor is not None:
            self._anchor.append(data)
        elif self._cell is not None:
            self._cell.append(data)
        elif self._table is None:
            text = _WS_RE.sub(" ", data).strip()
            if text:
                self._recent_text = text


def parse_document_format_table(content: bytes) -> list[IndexTableRow]:
    """Return the Document Format Files rows, or raise ``ProbePlanError``.

    Identity first, shape second. The table must be the one SEC identifies as
    Document Format Files — by its ``summary`` attribute or by an explicit
    heading immediately associated with it — and only then must it declare
    Document and Type columns. Selecting the first table that merely *looks*
    right would be unsafe: the same page carries a Data Files table with the
    same two columns, and nothing guarantees it comes second.
    """
    parser = _DocumentTableParser()
    try:
        parser.feed(content.decode("utf-8", errors="replace"))
        parser.close()
    except Exception as exc:  # noqa: BLE001 - malformed markup is a refusal
        raise ProbePlanError(f"index page could not be parsed: {exc}") from exc

    identified = [t for t in parser.tables if t.is_document_format_table()]
    if not identified:
        raise ProbePlanError(
            "no table on this index page is identified as "
            f"{DOCUMENT_FORMAT_TABLE_IDENTITY!r} by summary or an associated "
            "heading; column shape alone is not admissible identity."
        )
    if len(identified) > 1:
        raise ProbePlanError(
            f"{len(identified)} tables claim the "
            f"{DOCUMENT_FORMAT_TABLE_IDENTITY!r} identity; exactly one is "
            "required."
        )
    table = identified[0]
    if not table.rows:
        raise ProbePlanError(
            "the Document Format Files table carries no rows."
        )
    header = [cell.strip().lower() for cell in table.rows[0]]
    if "document" not in header or "type" not in header:
        raise ProbePlanError(
            "the Document Format Files table declares no Document and Type "
            f"columns (header: {header})."
        )
    doc_at, type_at = header.index("document"), header.index("type")
    size_at = header.index("size") if "size" in header else None
    rows: list[IndexTableRow] = []
    for raw_row in table.rows[1:]:
        if len(raw_row) <= max(doc_at, type_at):
            continue
        size: Optional[int] = None
        if size_at is not None and len(raw_row) > size_at:
            digits = raw_row[size_at].replace(",", "").strip()
            size = int(digits) if digits.isdigit() else None
        rows.append(
            IndexTableRow(
                document=raw_row[doc_at].strip(),
                document_type=raw_row[type_at].strip(),
                size=size,
            )
        )
    if not rows:
        raise ProbePlanError(
            "the Document Format Files table declares columns but no "
            "document rows."
        )
    return rows


def select_primary_document(
    rows: list[IndexTableRow], form: str
) -> tuple[Optional[IndexTableRow], Optional[str]]:
    """Return ``(selected row, None)`` or ``(None, refusal reason code)``."""
    matches = [row for row in rows if row.document_type.upper() == form.upper()]
    if not matches:
        return None, "no_primary_candidate"
    if len(matches) > 1:
        return None, "ambiguous_primary_candidate"
    selected = matches[0]
    if not selected.document.lower().endswith(HTML_SUFFIXES):
        return None, "non_html_primary"
    return selected, None


# --- plan -------------------------------------------------------------------


@dataclass
class PlannedProbe:
    """One validated probe entry with its code-derived URL.

    ``ground_truth_source_sha256`` binds the expected primary filename to the
    exact local full submission it was read from, so the plan's ground truth
    is provenance rather than assertion.
    """

    accession: str
    form: str
    directory_cik: str
    expected_primary_document: str
    ground_truth_source_sha256: str
    url: str


def validate_probe_plan(payload: object) -> tuple[list[PlannedProbe], dict]:
    """Validate a probe-plan payload and return (entries, plan fields)."""
    if not isinstance(payload, dict):
        raise ProbePlanError("Probe plan must be a JSON object.")
    if payload.get("plan_contract") != PROBE_PLAN_CONTRACT:
        raise ProbePlanError(f"Probe plan must declare {PROBE_PLAN_CONTRACT!r}.")
    for key in ("description", "base_url", "max_metadata_bytes", "provenance",
                "entries"):
        if key not in payload:
            raise ProbePlanError(f"Probe plan is missing {key!r}.")
    if payload["base_url"] != CANONICAL_BASE_URL:
        raise ProbePlanError(
            f"Plan base_url must be {CANONICAL_BASE_URL!r}; URLs are derived "
            "in code, never taken from the plan."
        )
    ceiling = payload["max_metadata_bytes"]
    if not isinstance(ceiling, int) or isinstance(ceiling, bool) or ceiling <= 0:
        raise ProbePlanError(
            "max_metadata_bytes must be an explicit positive integer; it is "
            "never defaulted in code."
        )
    provenance = payload["provenance"]
    if not isinstance(provenance, dict):
        raise ProbePlanError("Plan provenance must be an object.")
    run_id_value = provenance.get("carrier_run_id")
    if not isinstance(run_id_value, str) or not run_id_value.strip():
        raise ProbePlanError("Plan provenance is missing 'carrier_run_id'.")
    # Every provenance hash is validated canonically here, before a request is
    # made. The manifest schemas check the same shape, but only once the probe
    # has already run: a malformed upstream hash must stop the plan, not
    # surface after the network work is done.
    for key in ("carrier_manifest_sha256", "freeze_record_sha256",
                "canary_acquisition_manifest_sha256"):
        value = provenance.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ProbePlanError(f"Plan provenance is missing {key!r}.")
        if not _SHA256_RE.match(value):
            raise ProbePlanError(
                f"Plan provenance {key!r} must be a canonical lowercase "
                f"64-character SHA-256 hex digest; got {value!r}."
            )

    raw_entries = payload["entries"]
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ProbePlanError("Plan entries must be a non-empty array.")
    entries: list[PlannedProbe] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_entries):
        where = f"entries[{index}]"
        if not isinstance(raw, dict):
            raise ProbePlanError(f"{where} must be an object.")
        for key in ("accession", "form", "directory_cik",
                    "expected_primary_document", "ground_truth_source_sha256"):
            if key not in raw:
                raise ProbePlanError(f"{where} is missing {key!r}.")
        if raw["form"] not in ADMITTED_FORMS:
            raise ProbePlanError(
                f"{where}: form {raw['form']!r} is outside the domestic annual "
                f"forms {list(ADMITTED_FORMS)}; this probe is domestic-only "
                "and the FPI extension cohort is preserved, not probed."
            )
        try:
            accession = normalize_accession(raw["accession"])
            directory_cik = normalize_cik(raw["directory_cik"])
        except IdentifierError as exc:
            raise ProbePlanError(f"{where}: {exc}") from exc
        if accession in seen:
            raise ProbePlanError(f"{where}: accession {accession} is repeated.")
        seen.add(accession)
        expected = str(raw["expected_primary_document"]).strip()
        if not expected or not expected.lower().endswith(HTML_SUFFIXES):
            raise ProbePlanError(
                f"{where}: expected_primary_document {expected!r} must be a "
                "non-empty HTML filename; it is the ground truth this probe "
                "is checked against."
            )
        # Validated as written, never normalized: coercing case or trimming
        # whitespace here would silently accept the same malformed values the
        # provenance hashes reject, and a plan is evidence, not input to be
        # repaired.
        source_hash = raw["ground_truth_source_sha256"]
        if not isinstance(source_hash, str) or not _SHA256_RE.match(source_hash):
            raise ProbePlanError(
                f"{where}: ground_truth_source_sha256 must be a canonical "
                "lowercase 64-character SHA-256 hex digest naming the local "
                "full submission the expected primary was read from; got "
                f"{source_hash!r}."
            )
        entries.append(
            PlannedProbe(
                accession=accession,
                form=raw["form"],
                directory_cik=directory_cik,
                expected_primary_document=expected,
                ground_truth_source_sha256=source_hash,
                url=canonical_filing_index_url(directory_cik, accession),
            )
        )
    fields = {
        "description": str(payload["description"]),
        "base_url": CANONICAL_BASE_URL,
        "max_metadata_bytes": ceiling,
        "provenance": {
            "carrier_run_id": provenance["carrier_run_id"],
            "carrier_manifest_sha256": provenance["carrier_manifest_sha256"],
            "freeze_record_sha256": provenance["freeze_record_sha256"],
            "canary_acquisition_manifest_sha256":
                provenance["canary_acquisition_manifest_sha256"],
        },
    }
    return entries, fields


def load_probe_plan(path: str | Path) -> tuple[list[PlannedProbe], dict, str]:
    plan_path = Path(path)
    if not plan_path.is_file():
        raise ProbePlanError(f"Probe plan not found: {plan_path}")
    raw = plan_path.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbePlanError(f"Probe plan is not valid JSON: {exc}") from exc
    entries, fields = validate_probe_plan(payload)
    return entries, fields, sha256_bytes(raw)


def make_filing_index_fixture_replay_transport(
    replay_dir: str | Path, *, max_bytes: int,
) -> Callable[[str], DocumentTransportResponse]:
    """Deterministic replay transport serving local index pages.

    The ceiling is enforced the same way the live transport enforces it: the
    on-disk size stands in for the declared length, so an oversized fixture is
    refused before its bytes are read and travels the identical runner path.
    """
    directory = Path(replay_dir)
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ProbePlanError(
            "max_bytes must be an explicit positive integer; the metadata "
            "ceiling is plan-owned and never defaulted."
        )

    def transport(url: str) -> DocumentTransportResponse:
        match = _ACCESSION_IN_INDEX_URL_RE.search(url)
        if match is None:
            return DocumentTransportResponse(
                status_code=404, final_url=url, content=b""
            )
        path = directory / f"{match.group(1)}-index.htm"
        if not path.is_file():
            return DocumentTransportResponse(
                status_code=404, final_url=url, content=b""
            )
        size = path.stat().st_size
        if size > max_bytes:
            return DocumentTransportResponse(
                status_code=200, final_url=url, content=b"",
                declared_content_length=size, bytes_received=0,
                ceiling_refusal="content_length_preflight",
            )
        content = path.read_bytes()
        return DocumentTransportResponse(
            status_code=200, final_url=url, content=content,
            declared_content_length=size, bytes_received=len(content),
        )

    return transport


# --- run --------------------------------------------------------------------


@dataclass
class ProbeObservation:
    """The recorded outcome for one probed accession."""

    accession: str
    form: str
    directory_cik: str
    url: str
    final_url: str
    status_code: int
    response_byte_length: int
    response_sha256: str
    declared_content_length: Optional[int]
    candidates: list[dict]
    selected_document: str
    expected_primary_document: str
    ground_truth_source_sha256: str
    ground_truth_match: bool
    retrieved_at: datetime


@dataclass
class ProbeFailureReceipt:
    run_id: str
    plan_sha256: str
    transport_kind: str
    transport_contract_hash: str
    reason_code: str
    detail: str
    attempted_accession: str
    attempted_url: str
    accessions_probed_before_failure: list[str]
    failed_at: datetime


@dataclass
class ProbeRunResult:
    run_id: str
    run_dir: Path | None
    dry_run: bool
    plan_sha256: str
    entries: list[PlannedProbe]
    observations: list[ProbeObservation] = field(default_factory=list)
    manifest_path: Path | None = None
    failure: Optional[ProbeFailureReceipt] = None
    failure_receipt_path: Path | None = None


def _ceiling_enforcement(ceiling: int, identity: TransportIdentity) -> dict:
    contract = identity.contract
    if contract.get("streaming") is True:
        chunk = int(contract["stream_chunk_bytes"])
        return {
            "max_metadata_bytes": ceiling,
            "mechanism": "streaming_chunk_bound",
            "content_length_preflight": True,
            "stream_chunk_bytes": chunk,
            "max_transport_bytes": ceiling + chunk,
        }
    return {
        "max_metadata_bytes": ceiling,
        "mechanism": "bounded_local_read",
        "content_length_preflight": True,
        "stream_chunk_bytes": None,
        "max_transport_bytes": ceiling,
    }


def run_filing_index_probe(
    *,
    repo_root: str | Path,
    plan_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    transport: Callable[[str], DocumentTransportResponse],
    transport_max_bytes: int,
    clock: Callable[[], datetime] | None = None,
    dry_run: bool = False,
    transport_identity: TransportIdentity | None = None,
) -> ProbeRunResult:
    """Probe every planned filing index, or fail closed.

    ``transport_max_bytes`` is the ceiling the injected transport was built
    with; it must equal the plan's ``max_metadata_bytes``, and a mismatch is
    refused here before any request is made.
    """
    root = Path(repo_root)
    now = clock or (lambda: datetime.now(timezone.utc))
    identity = transport_identity or FIXTURE_REPLAY_TRANSPORT_IDENTITY
    if not _RUN_ID_RE.match(run_id):
        raise ProbePlanError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )
    entries, fields, plan_sha256 = load_probe_plan(plan_path)
    ceiling = fields["max_metadata_bytes"]
    if transport_max_bytes != ceiling:
        raise ProbePlanError(
            f"Transport ceiling {transport_max_bytes} does not equal the "
            f"plan's max_metadata_bytes {ceiling}; the transport must enforce "
            "exactly the declared ceiling."
        )
    result = ProbeRunResult(
        run_id=run_id, run_dir=None, dry_run=dry_run,
        plan_sha256=plan_sha256, entries=entries,
    )
    if dry_run:
        return result

    run_dir = create_run_directory(output_dir, run_id)
    result.run_dir = run_dir

    def fail(entry: PlannedProbe, reason: str, detail: str) -> ProbeRunResult:
        receipt = ProbeFailureReceipt(
            run_id=run_id,
            plan_sha256=plan_sha256,
            transport_kind=identity.kind,
            transport_contract_hash=identity.contract_hash(),
            reason_code=reason,
            detail=detail,
            attempted_accession=entry.accession,
            attempted_url=entry.url,
            accessions_probed_before_failure=[
                o.accession for o in result.observations
            ],
            failed_at=now(),
        )
        payload = (
            json.dumps(
                {
                    "run_id": receipt.run_id,
                    "plan_sha256": receipt.plan_sha256,
                    "transport_kind": receipt.transport_kind,
                    "transport_contract_hash": receipt.transport_contract_hash,
                    "reason_code": receipt.reason_code,
                    "detail": receipt.detail,
                    "attempted_accession": receipt.attempted_accession,
                    "attempted_url": receipt.attempted_url,
                    "accessions_probed_before_failure":
                        receipt.accessions_probed_before_failure,
                    "failed_at": receipt.failed_at.isoformat(),
                },
                indent=2, sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        write_bytes_once(
            run_dir / PROBE_FAILURE_RECEIPT_FILENAME, payload,
            what="filing index probe failure receipt",
        )
        result.failure = receipt
        result.failure_receipt_path = run_dir / PROBE_FAILURE_RECEIPT_FILENAME
        return result

    for entry in entries:
        try:
            response = transport(entry.url)
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
            return fail(entry, "transport_exception", f"{type(exc).__name__}: {exc}")
        if response.ceiling_refusal is not None:
            return fail(
                entry, "metadata_over_ceiling",
                f"transport refused {entry.url} by {response.ceiling_refusal}: "
                f"declared_content_length={response.declared_content_length}, "
                f"bytes_received={response.bytes_received}, plan ceiling "
                f"{ceiling}. No body was retained.",
            )
        if response.status_code in _REDIRECT_STATUSES:
            return fail(
                entry, "metadata_http_failure",
                f"redirect status {response.status_code} for {entry.url}; "
                "redirects are disabled for the metadata probe.",
            )
        if response.status_code != 200:
            return fail(
                entry, "metadata_http_failure",
                f"status {response.status_code} for {entry.url}.",
            )
        if not response.final_url or response.final_url != entry.url:
            return fail(
                entry, "metadata_http_failure",
                f"requested {entry.url}, response reports "
                f"{response.final_url!r}.",
            )
        try:
            rows = parse_document_format_table(response.content)
        except ProbePlanError as exc:
            return fail(entry, "metadata_unparseable", str(exc))
        selected, refusal = select_primary_document(rows, entry.form)
        if refusal is not None:
            matched = [r.document for r in rows
                       if r.document_type.upper() == entry.form.upper()]
            return fail(
                entry, refusal,
                f"{entry.url}: {len(matched)} row(s) declare type "
                f"{entry.form!r} ({matched}); a primary document must be a "
                "single HTML row.",
            )
        assert selected is not None
        if selected.document != entry.expected_primary_document:
            return fail(
                entry, "ground_truth_mismatch",
                f"{entry.url}: selected {selected.document!r} but the plan's "
                f"recorded ground truth is {entry.expected_primary_document!r}.",
            )
        result.observations.append(
            ProbeObservation(
                accession=entry.accession,
                form=entry.form,
                directory_cik=entry.directory_cik,
                url=entry.url,
                final_url=response.final_url,
                status_code=response.status_code,
                response_byte_length=len(response.content),
                response_sha256=sha256_bytes(response.content),
                declared_content_length=response.declared_content_length,
                candidates=[
                    {
                        "document": r.document,
                        "document_type": r.document_type,
                        "reported_size": r.size,
                    }
                    for r in rows
                ],
                selected_document=selected.document,
                expected_primary_document=entry.expected_primary_document,
                ground_truth_source_sha256=entry.ground_truth_source_sha256,
                ground_truth_match=True,
                retrieved_at=now(),
            )
        )

    manifest = build_probe_manifest(
        repo_root=root,
        run_id=run_id,
        plan_sha256=plan_sha256,
        fields=fields,
        planned_count=len(entries),
        observations=result.observations,
        run_timestamp=now(),
        transport_identity=identity,
    )
    payload = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        write_bytes_once(
            run_dir / PROBE_MANIFEST_FILENAME, payload,
            what="filing index probe manifest",
        )
    except WriteOnceError as exc:  # pragma: no cover - immutable run dir
        raise ProbePlanError(str(exc)) from exc
    result.manifest_path = run_dir / PROBE_MANIFEST_FILENAME
    return result


def build_probe_manifest(
    *,
    repo_root: str | Path,
    run_id: str,
    plan_sha256: str,
    fields: dict,
    planned_count: int,
    observations: list[ProbeObservation],
    run_timestamp: datetime,
    transport_identity: TransportIdentity,
) -> dict:
    """Assemble and schema-validate the probe manifest (v0.1 or v0.2).

    ``planned_count`` comes from the plan, not from the observations, so the
    completeness identity below compares two independently sourced numbers
    instead of restating one of them.
    """
    root = Path(repo_root)
    schema_versions = read_json(root / "schemas" / "schema_version_manifest.json")[
        "schemas"
    ]
    live = transport_identity.kind == TRANSPORT_KIND_SEC_LIVE
    ceiling = fields["max_metadata_bytes"]
    manifest: dict = {
        "run_id": run_id,
        "plan_contract": PROBE_PLAN_CONTRACT,
        "plan_sha256": plan_sha256,
        "base_url": fields["base_url"],
        "max_metadata_bytes": ceiling,
        "ceiling_enforcement": _ceiling_enforcement(ceiling, transport_identity),
        "carrier_provenance": fields["provenance"],
        "transport_kind": transport_identity.kind,
        "transport_contract_hash": transport_identity.contract_hash(),
        "observations": [
            {
                "accession": o.accession,
                "form": o.form,
                "directory_cik": o.directory_cik,
                "url": o.url,
                "final_url": o.final_url,
                "status_code": o.status_code,
                "response_byte_length": o.response_byte_length,
                "response_sha256": o.response_sha256,
                "declared_content_length": o.declared_content_length,
                "candidates": o.candidates,
                "selected_document": o.selected_document,
                "expected_primary_document": o.expected_primary_document,
                "ground_truth_source_sha256": o.ground_truth_source_sha256,
                "ground_truth_match": o.ground_truth_match,
                "retrieved_at": o.retrieved_at.isoformat(),
            }
            for o in observations
        ],
        "counts": {
            "planned_probes": planned_count,
            "probes_resolved": len(observations),
            "ground_truth_matches": sum(
                1 for o in observations if o.ground_truth_match
            ),
        },
        "reconciliation": {
            "planned = resolved = ground-truth matches": (
                planned_count
                == len(observations)
                == sum(1 for o in observations if o.ground_truth_match)
            ),
            "every planned probe resolved": planned_count == len(observations),
            "every selection matched recorded ground truth": all(
                o.ground_truth_match for o in observations
            ),
            "every selection is a single HTML document": all(
                o.selected_document.lower().endswith(HTML_SUFFIXES)
                for o in observations
            ),
        },
        "run_timestamp": run_timestamp.isoformat(),
        "limitations": [
            "Metadata grammar only: this probe acquires no primary document, "
            "builds no packet, and authorizes nothing downstream.",
            "The probed endpoint is the filing index page alone; index.json "
            "is a separately authorized fallback and was never requested.",
            "Domestic annual forms only (10-K, 10-KT). The FPI extension "
            "cohort is preserved, not probed and not excluded.",
            "Primary selection is by declared document type; filename "
            "convention is never used, because the measured corpus contains "
            "primaries no ticker-and-date pattern would match.",
        ],
    }
    if live:
        manifest["transport_contract"] = dict(transport_identity.contract)
        manifest["schema_versions"] = {
            "filing_index_probe_manifest_v2": schema_versions[
                "filing_index_probe_manifest_v2"
            ]
        }
        schema_path = PROBE_V2_SCHEMA_RELATIVE_PATH
    else:
        manifest["schema_versions"] = {
            "filing_index_probe_manifest": schema_versions[
                "filing_index_probe_manifest"
            ]
        }
        manifest["limitations"].insert(
            0,
            "Fixture-replay probe: bytes were served from local fixture index "
            "pages; no network request was made.",
        )
        schema_path = PROBE_SCHEMA_RELATIVE_PATH
    if not all(manifest["reconciliation"].values()):
        failed = sorted(k for k, ok in manifest["reconciliation"].items() if not ok)
        raise ValueError(
            f"Probe reconciliation failed: {failed}. No manifest is written."
        )
    schema = read_json(root / schema_path)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest),
        key=lambda e: e.json_path,
    )
    if errors:
        details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
        raise ValueError(
            f"Filing index probe manifest violates the canonical schema: {details}"
        )
    return manifest
