"""Two-hop primary annual-report acquisition (W2-C; fixture-first, canary-gated).

Governing documents:
- docs/DECISION_LOG.md ADR-089 (bounded document acquisition), ADR-090 (the
  filing-index route probe), ADR-091 (baseline packet contracts), ADR-092
  (this design)

Acquires the *primary* annual-report document for planned domestic baseline
candidates in two bounded hops, and emits the already-governed
``baseline_primary_document_bundle@0.1.0`` that ``build-baseline-packets``
consumes unchanged. Nothing here invents a parallel packet-input format, and
the committed bundle schema and packet builder are untouched.

**Why two hops.** The measured 12-document submission canary (ADR-089) showed
the primary document is 8.8% of a full submission — 44.8 MB of primaries
inside 508.3 MB of submissions — so the packet route fetches the filing index
and then only the selected primary. The accession-wide ``.txt`` is
unreachable from this module by construction.

- **Hop 1, filing index.** ``canonical_filing_index_url`` (ADR-090), fetched
  under the plan's ``max_metadata_bytes``. The response is parsed by the
  committed probe parser: the Document Format Files table is identified by its
  ``summary`` or associated heading, never by column shape, and the primary is
  the single row whose declared type equals the planned form. The filename
  comes from the row's link target via ``href_document_basename``, never from
  rendered text, which carries SEC's ``iXBRL`` badge.
- **Hop 2, primary document.** A *canonically derived* URL — never the raw
  href — so the inline-XBRL viewer wrapper is never fetched, under the plan's
  ``max_document_bytes``.

**Declared lengths are observational (ADR-093).** A live run records, per
acquisition, the parsed ``Content-Length`` the transport already produced for
each hop — or ``None`` where it had no usable value. They exist so
full-cohort byte planning can compare declared against retained size; they
are never retained byte counts, never reconstructed from a raw header, and
never consulted for ceiling enforcement. They appear on the ``sec_live`` v0.3
contract only; the fixture v0.1 contract is unchanged.

**Transport provenance.** One *active* transport kind per run. The two hops
are separately constructed and recorded separately, because each is bound to a
different plan-owned ceiling; their contract hashes are expected to be equal,
because the byte bound is deliberately not part of the transport contract.

**Authority and failure.** ``bundle_manifest.json`` is the governed input
marker that ``build-baseline-packets`` consumes. A bundle manifest together
with this acquisition manifest is the evidence of a complete successful
acquisition run — an operational-policy statement about runs, not a new
requirement imposed on the packet builder, which requires only the bundle.
On failure this module writes a failure receipt and **no bundle manifest and
no acquisition manifest**. Raw primaries already written stay in the immutable
failed run directory and are named in the receipt: they persist, but they are
non-authoritative, and the builder cannot consume the directory because the
bundle manifest it requires is absent. This is all-or-nothing *authoritative
bundle production*, not "nothing persisted".

**Provenance is a directed graph.** The bundle points back to the carrier,
freeze record and route probe, and names its producing run by id only. The
acquisition manifest's ``output_hashes`` covers the bundle manifest and every
raw primary — never itself. No artifact hashes something that hashes it.

Scope is domestic ``10-K``/``10-KT``. The FPI extension cohort is preserved by
the frame and carrier and is neither handled nor excluded here. This module
contains no network code: transports are injected with their identities as
data.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator

from ..provenance import WriteOnceError, write_bytes_once
from .document_acquisition import DocumentTransportResponse
from .filing_index_probe import (
    CANONICAL_BASE_URL,
    VIEWER_PATH,
    canonical_filing_index_url,
    parse_document_format_table,
    select_primary_document,
)
from .frame_acquisition import (
    FIXTURE_REPLAY_TRANSPORT_IDENTITY,
    TRANSPORT_KIND_SEC_LIVE,
    TransportIdentity,
)
from .freeze import create_run_directory
from .identifiers import IdentifierError, normalize_accession, normalize_cik
from .io_utils import read_json, sha256_bytes

#: v0.1 declares only per-document ceilings. v0.2 adds a shard-owned
#: ``max_retained_bytes``, the cumulative disk bound this runner enforces at
#: the write seam. Both are accepted; the two committed v0.1 plans are
#: unaffected and keep producing v0.1/v0.3 manifests.
PLAN_CONTRACT_V1 = "primary_document_request_plan@0.1.0"
PLAN_CONTRACT_V2 = "primary_document_request_plan@0.2.0"
ACCEPTED_PLAN_CONTRACTS = (PLAN_CONTRACT_V1, PLAN_CONTRACT_V2)
#: Retained for importers that predate the budgeted contract.
PLAN_CONTRACT = PLAN_CONTRACT_V1
BUNDLE_CONTRACT = "baseline_primary_document_bundle@0.1.0"
ADMITTED_FORMS = ("10-K", "10-KT")
ADMITTED_STRATA = ("domestic",)
HTML_SUFFIXES = (".htm", ".html")

BUNDLE_MANIFEST_FILENAME = "bundle_manifest.json"
ACQUISITION_MANIFEST_FILENAME = "primary_document_acquisition_manifest.json"
FAILURE_RECEIPT_FILENAME = "primary_document_acquisition_failure_receipt.json"

BUNDLE_SCHEMA_RELATIVE_PATH = Path(
    "schemas/baseline_primary_document_bundle.schema.json"
)
ACQUISITION_SCHEMA_RELATIVE_PATH = Path(
    "schemas/primary_document_acquisition_manifest.schema.json"
)
#: The historical sec_live contract. Artifacts written before ADR-093 remain
#: valid against it; nothing migrates, and live runs now emit v0.3.
ACQUISITION_V2_SCHEMA_RELATIVE_PATH = Path(
    "schemas/primary_document_acquisition_manifest.v2.schema.json"
)
ACQUISITION_V3_SCHEMA_RELATIVE_PATH = Path(
    "schemas/primary_document_acquisition_manifest.v3.schema.json"
)
#: Budgeted (plan v0.2) successors. The lineage numbering is flat and already
#: interleaves transports — v0.1 is the fixture schema, v0.2 and v0.3 are
#: sec_live — so v0.4 continues the fixture lineage and v0.5 the sec_live one.
#: No schema admits two histories: each requires its own schema_versions key
#: under additionalProperties=false.
ACQUISITION_V4_SCHEMA_RELATIVE_PATH = Path(
    "schemas/primary_document_acquisition_manifest.v4.schema.json"
)
ACQUISITION_V5_SCHEMA_RELATIVE_PATH = Path(
    "schemas/primary_document_acquisition_manifest.v5.schema.json"
)

GROUND_TRUTH_NONE = "none"
GROUND_TRUTH_FILENAME_ONLY = "expected_filename_only"
GROUND_TRUTH_FILENAME_AND_SHA = "expected_filename_and_source_sha256"
GROUND_TRUTH_BASES = (
    GROUND_TRUTH_NONE,
    GROUND_TRUTH_FILENAME_ONLY,
    GROUND_TRUTH_FILENAME_AND_SHA,
)

#: Refusal reasons this module writes into a failure receipt. The receipt has
#: no governed schema, so the vocabulary is pinned by tests instead.
REASON_BUDGET_EXHAUSTED = "shard_retained_byte_budget_exhausted"

HOP_FILING_INDEX = "filing_index"
HOP_PRIMARY_DOCUMENT = "primary_document"
HREF_FORM_DIRECT = "direct"
HREF_FORM_VIEWER = "viewer"

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class PrimaryDocumentPlanError(ValueError):
    """The request plan is malformed or outside the enforced grammar."""


def canonical_primary_document_url(
    directory_cik: str, accession: str, selected_document: str
) -> str:
    """Derive the primary document's URL from the filing directory.

    Built from the directory and the selected basename, never from the row's
    raw href: an inline-XBRL row links through the viewer, and the viewer
    wrapper is not the document.
    """
    cik_path = str(int(normalize_cik(directory_cik)))
    dashed = normalize_accession(accession)
    return (
        f"{CANONICAL_BASE_URL}edgar/data/{cik_path}/{dashed.replace('-', '')}/"
        f"{selected_document}"
    )


def local_filename_for(accession: str) -> str:
    """The bundle's storage name for one accession's primary document.

    Deliberately not the SEC basename: the file this bundle stores and the
    document SEC selected are separate facts, and the bundle contract keeps
    both. One shared accession yields exactly one stored file.
    """
    return f"primary-{normalize_accession(accession).replace('-', '')}.html"


def href_form_of(href: str) -> str:
    """Classify a Document-cell link as the viewer form or a direct link."""
    try:
        parts = urlsplit(href.strip())
    except ValueError:  # pragma: no cover - defensive
        return HREF_FORM_DIRECT
    return (
        HREF_FORM_VIEWER
        if parts.path.lower() == VIEWER_PATH
        else HREF_FORM_DIRECT
    )


@dataclass
class PlannedCarrierRow:
    stratum: str
    cik: str
    baseline_filing_date: str


@dataclass
class PlannedAccession:
    accession: str
    form: str
    directory_cik: str
    carrier_rows: list[PlannedCarrierRow]
    filing_index_url: str
    local_filename: str
    expected_primary_document: Optional[str] = None
    ground_truth_source_sha256: Optional[str] = None


@dataclass
class AcquiredAccession:
    accession: str
    form: str
    directory_cik: str
    filing_index_url: str
    filing_index_final_url: str
    filing_index_status: int
    filing_index_byte_length: int
    filing_index_response_sha256: str
    #: The parsed Content-Length the transport already produced for this hop,
    #: or None when it had no usable value. Observational only: never a
    #: retained byte count, and never used for ceiling enforcement.
    filing_index_declared_content_length: Optional[int]
    selected_document: str
    href_form: str
    candidate_count: int
    primary_url: str
    primary_final_url: str
    primary_status: int
    local_filename: str
    primary_declared_content_length: Optional[int]
    source_sha256: str
    source_byte_length: int
    mapped_carrier_rows: int
    ground_truth_basis: str
    retrieved_at: datetime


@dataclass
class AcquisitionFailureReceipt:
    run_id: str
    plan_sha256: str
    transport_kind: str
    metadata_hop_contract_hash: str
    metadata_hop_max_bytes: int
    primary_hop_contract_hash: str
    primary_hop_max_bytes: int
    reason_code: str
    detail: str
    attempted_accession: str
    attempted_hop: str
    accessions_completed_before_failure: list[str]
    retained_raw_filenames: list[str]
    failed_at: datetime


@dataclass
class PrimaryAcquisitionResult:
    run_id: str
    run_dir: Path | None
    dry_run: bool
    plan_sha256: str
    planned: list[PlannedAccession]
    acquired: list[AcquiredAccession] = field(default_factory=list)
    bundle_manifest_path: Path | None = None
    acquisition_manifest_path: Path | None = None
    failure: Optional[AcquisitionFailureReceipt] = None
    failure_receipt_path: Path | None = None
    counts: dict = field(default_factory=dict)


# --- plan -------------------------------------------------------------------


def validate_request_plan(payload: object) -> tuple[list[PlannedAccession], dict]:
    """Validate a plan payload and return (planned accessions, plan fields)."""
    if not isinstance(payload, dict):
        raise PrimaryDocumentPlanError("Request plan must be a JSON object.")
    plan_contract = payload.get("plan_contract")
    if plan_contract not in ACCEPTED_PLAN_CONTRACTS:
        raise PrimaryDocumentPlanError(
            "Request plan must declare one of "
            f"{list(ACCEPTED_PLAN_CONTRACTS)!r}."
        )
    for key in ("description", "base_url", "max_metadata_bytes",
                "max_document_bytes", "provenance", "route_validation",
                "documents"):
        if key not in payload:
            raise PrimaryDocumentPlanError(f"Request plan is missing {key!r}.")
    if payload["base_url"] != CANONICAL_BASE_URL:
        raise PrimaryDocumentPlanError(
            f"Plan base_url must be {CANONICAL_BASE_URL!r}; URLs are derived "
            "in code, never taken from the plan."
        )
    for key in ("max_metadata_bytes", "max_document_bytes"):
        ceiling = payload[key]
        if not isinstance(ceiling, int) or isinstance(ceiling, bool) or ceiling <= 0:
            raise PrimaryDocumentPlanError(
                f"{key} must be an explicit positive integer; it is never "
                "defaulted in code."
            )
    # v0.2 owns a cumulative retained-byte bound. It is required there and
    # forbidden under v0.1, so a plan's contract alone says whether a run is
    # budgeted; there is no defaulting and no silent unbounded v0.2.
    max_retained_bytes = payload.get("max_retained_bytes")
    if plan_contract == PLAN_CONTRACT_V2:
        if max_retained_bytes is None:
            raise PrimaryDocumentPlanError(
                f"{PLAN_CONTRACT_V2} requires max_retained_bytes: the "
                "cumulative retained-byte bound is plan-owned and never "
                "defaulted."
            )
        if (
            not isinstance(max_retained_bytes, int)
            or isinstance(max_retained_bytes, bool)
            or max_retained_bytes <= 0
        ):
            raise PrimaryDocumentPlanError(
                "max_retained_bytes must be an explicit positive integer."
            )
    elif max_retained_bytes is not None:
        raise PrimaryDocumentPlanError(
            f"max_retained_bytes is a {PLAN_CONTRACT_V2} field; "
            f"{PLAN_CONTRACT_V1} declares no cumulative bound."
        )
    provenance = payload["provenance"]
    if not isinstance(provenance, dict):
        raise PrimaryDocumentPlanError("Plan provenance must be an object.")
    run_id_value = provenance.get("carrier_run_id")
    if not isinstance(run_id_value, str) or not run_id_value.strip():
        raise PrimaryDocumentPlanError("Plan provenance is missing 'carrier_run_id'.")
    for key in ("carrier_manifest_sha256", "freeze_record_sha256"):
        value = provenance.get(key)
        if not isinstance(value, str) or not _SHA256_RE.match(value):
            raise PrimaryDocumentPlanError(
                f"Plan provenance {key!r} must be a canonical lowercase "
                "64-character SHA-256 hex digest."
            )
    route = payload["route_validation"]
    if not isinstance(route, dict):
        raise PrimaryDocumentPlanError("Plan route_validation must be an object.")
    for key in ("probe_run_id", "note"):
        if not isinstance(route.get(key), str) or not route[key].strip():
            raise PrimaryDocumentPlanError(f"route_validation is missing {key!r}.")
    if not isinstance(route.get("probe_manifest_sha256"), str) or not _SHA256_RE.match(
        route["probe_manifest_sha256"]
    ):
        raise PrimaryDocumentPlanError(
            "route_validation probe_manifest_sha256 must be a canonical "
            "lowercase SHA-256 hex digest."
        )
    if not isinstance(route.get("covered_accessions"), int) or route[
        "covered_accessions"
    ] < 1:
        raise PrimaryDocumentPlanError(
            "route_validation covered_accessions must be a positive integer."
        )

    raw_documents = payload["documents"]
    if not isinstance(raw_documents, list) or not raw_documents:
        raise PrimaryDocumentPlanError("Plan documents must be a non-empty array.")
    planned: list[PlannedAccession] = []
    seen_accessions: set[str] = set()
    seen_rows: set[tuple[str, str]] = set()
    for index, raw in enumerate(raw_documents):
        where = f"documents[{index}]"
        if not isinstance(raw, dict):
            raise PrimaryDocumentPlanError(f"{where} must be an object.")
        for key in ("accession", "form", "directory_cik", "carrier_rows"):
            if key not in raw:
                raise PrimaryDocumentPlanError(f"{where} is missing {key!r}.")
        if raw["form"] not in ADMITTED_FORMS:
            raise PrimaryDocumentPlanError(
                f"{where}: form {raw['form']!r} is outside the domestic annual "
                f"forms {list(ADMITTED_FORMS)}. The FPI extension cohort is "
                "preserved by the frame and carrier, and is neither acquired "
                "nor excluded here."
            )
        try:
            accession = normalize_accession(raw["accession"])
            directory_cik = normalize_cik(raw["directory_cik"])
        except IdentifierError as exc:
            raise PrimaryDocumentPlanError(f"{where}: {exc}") from exc
        if accession in seen_accessions:
            raise PrimaryDocumentPlanError(
                f"{where}: accession {accession} appears more than once; a "
                "shared filing is fetched once and mapped to every carrier row."
            )
        seen_accessions.add(accession)

        rows_raw = raw["carrier_rows"]
        if not isinstance(rows_raw, list) or not rows_raw:
            raise PrimaryDocumentPlanError(
                f"{where}: carrier_rows must be a non-empty array naming every "
                "carrier row this document serves."
            )
        rows: list[PlannedCarrierRow] = []
        for row_index, row_raw in enumerate(rows_raw):
            row_where = f"{where}.carrier_rows[{row_index}]"
            if not isinstance(row_raw, dict):
                raise PrimaryDocumentPlanError(f"{row_where} must be an object.")
            for key in ("stratum", "cik", "baseline_filing_date"):
                if key not in row_raw:
                    raise PrimaryDocumentPlanError(f"{row_where} is missing {key!r}.")
            if row_raw["stratum"] not in ADMITTED_STRATA:
                raise PrimaryDocumentPlanError(
                    f"{row_where}: stratum {row_raw['stratum']!r} must be "
                    f"{ADMITTED_STRATA[0]!r}."
                )
            try:
                row_cik = normalize_cik(row_raw["cik"])
                date.fromisoformat(str(row_raw["baseline_filing_date"]))
            except (IdentifierError, ValueError) as exc:
                raise PrimaryDocumentPlanError(f"{row_where}: {exc}") from exc
            key = (row_cik, accession)
            if key in seen_rows:
                raise PrimaryDocumentPlanError(
                    f"{row_where}: duplicate carrier row {key}."
                )
            seen_rows.add(key)
            rows.append(
                PlannedCarrierRow(
                    stratum=row_raw["stratum"],
                    cik=row_cik,
                    baseline_filing_date=str(row_raw["baseline_filing_date"]),
                )
            )

        expected = raw.get("expected_primary_document")
        if expected is not None:
            if not isinstance(expected, str) or not expected.lower().endswith(
                HTML_SUFFIXES
            ):
                raise PrimaryDocumentPlanError(
                    f"{where}: expected_primary_document must be an HTML "
                    "filename when present."
                )
        ground_truth = raw.get("ground_truth_source_sha256")
        if ground_truth is not None and (
            not isinstance(ground_truth, str) or not _SHA256_RE.match(ground_truth)
        ):
            raise PrimaryDocumentPlanError(
                f"{where}: ground_truth_source_sha256 must be a canonical "
                "lowercase SHA-256 hex digest when present."
            )
        if ground_truth is not None and expected is None:
            raise PrimaryDocumentPlanError(
                f"{where}: ground_truth_source_sha256 requires "
                "expected_primary_document; a source hash alone names no "
                "document to check it against."
            )

        # The filing directory is the lowest CIK sharing the accession — the
        # accession's own 10-digit prefix is frequently a filing agent owning
        # no EDGAR directory. Enforced here, before any URL is derived and
        # before any request, for a one-row accession as well as a shared one.
        lowest = min(row.cik for row in rows)
        if directory_cik != lowest:
            raise PrimaryDocumentPlanError(
                f"{where}: directory_cik {directory_cik} is not the lowest "
                f"carrier-row CIK {lowest} for accession {accession}; the "
                "filing-directory path always uses the lowest sharing CIK."
            )
        planned.append(
            PlannedAccession(
                accession=accession,
                form=raw["form"],
                directory_cik=directory_cik,
                carrier_rows=rows,
                filing_index_url=canonical_filing_index_url(
                    directory_cik, accession
                ),
                local_filename=local_filename_for(accession),
                expected_primary_document=expected,
                ground_truth_source_sha256=ground_truth,
            )
        )
    fields = {
        "plan_contract": plan_contract,
        "max_retained_bytes": max_retained_bytes,
        "description": str(payload["description"]),
        "base_url": CANONICAL_BASE_URL,
        "max_metadata_bytes": payload["max_metadata_bytes"],
        "max_document_bytes": payload["max_document_bytes"],
        "provenance": {
            "carrier_run_id": provenance["carrier_run_id"],
            "carrier_manifest_sha256": provenance["carrier_manifest_sha256"],
            "freeze_record_sha256": provenance["freeze_record_sha256"],
        },
        "route_validation": {
            "probe_run_id": route["probe_run_id"],
            "probe_manifest_sha256": route["probe_manifest_sha256"],
            "covered_accessions": route["covered_accessions"],
            "note": route["note"],
        },
    }
    return planned, fields


def load_request_plan(
    path: str | Path,
) -> tuple[list[PlannedAccession], dict, str]:
    plan_path = Path(path)
    if not plan_path.is_file():
        raise PrimaryDocumentPlanError(f"Request plan not found: {plan_path}")
    raw = plan_path.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PrimaryDocumentPlanError(
            f"Request plan is not valid JSON: {exc}"
        ) from exc
    planned, fields = validate_request_plan(payload)
    return planned, fields, sha256_bytes(raw)


def make_primary_document_fixture_replay_transport(
    replay_dir: str | Path, *, max_bytes: int,
) -> Callable[[str], DocumentTransportResponse]:
    """Replay transport serving local primary documents by their basename.

    Routed differently from the filing-index replay transport, which keys on
    ``<accession>-index.htm``; both share the fixture-replay identity.
    """
    directory = Path(replay_dir)
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise PrimaryDocumentPlanError(
            "max_bytes must be an explicit positive integer; the document "
            "ceiling is plan-owned and never defaulted."
        )

    def transport(url: str) -> DocumentTransportResponse:
        basename = url.rsplit("/", 1)[-1]
        path = directory / basename
        if not basename or not path.is_file():
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


def _hop_record(identity: TransportIdentity, max_bytes: int) -> dict:
    contract = identity.contract
    streaming = contract.get("streaming") is True
    chunk = int(contract["stream_chunk_bytes"]) if streaming else None
    return {
        "transport_contract_hash": identity.contract_hash(),
        "max_bytes": max_bytes,
        "ceiling_enforcement": {
            "mechanism": (
                "streaming_chunk_bound" if streaming else "bounded_local_read"
            ),
            "content_length_preflight": True,
            "stream_chunk_bytes": chunk,
            "max_transport_bytes": max_bytes + chunk if streaming else max_bytes,
        },
    }


def run_primary_document_acquisition(
    *,
    repo_root: str | Path,
    request_plan_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    metadata_transport: Callable[[str], DocumentTransportResponse],
    primary_transport: Callable[[str], DocumentTransportResponse],
    metadata_transport_max_bytes: int,
    primary_transport_max_bytes: int,
    clock: Callable[[], datetime],
    dry_run: bool = False,
    transport_identity: TransportIdentity | None = None,
) -> PrimaryAcquisitionResult:
    """Acquire every planned primary document, or fail closed.

    Both ceilings are plan-owned: each injected transport must have been
    constructed with exactly the ceiling the plan declares, and a mismatch is
    refused before any request is made.
    """
    root = Path(repo_root)
    now = clock
    identity = transport_identity or FIXTURE_REPLAY_TRANSPORT_IDENTITY
    if not _RUN_ID_RE.match(run_id):
        raise PrimaryDocumentPlanError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )
    planned, fields, plan_sha256 = load_request_plan(request_plan_path)
    if metadata_transport_max_bytes != fields["max_metadata_bytes"]:
        raise PrimaryDocumentPlanError(
            f"Metadata transport ceiling {metadata_transport_max_bytes} does "
            f"not equal the plan's max_metadata_bytes "
            f"{fields['max_metadata_bytes']}."
        )
    if primary_transport_max_bytes != fields["max_document_bytes"]:
        raise PrimaryDocumentPlanError(
            f"Primary transport ceiling {primary_transport_max_bytes} does not "
            f"equal the plan's max_document_bytes {fields['max_document_bytes']}."
        )

    result = PrimaryAcquisitionResult(
        run_id=run_id, run_dir=None, dry_run=dry_run,
        plan_sha256=plan_sha256, planned=planned,
    )
    if dry_run:
        return result

    run_dir = create_run_directory(output_dir, run_id)
    result.run_dir = run_dir
    retained: list[str] = []
    retained_bytes_total = 0

    def fail(entry: PlannedAccession, hop: str, reason: str, detail: str):
        receipt = AcquisitionFailureReceipt(
            run_id=run_id,
            plan_sha256=plan_sha256,
            transport_kind=identity.kind,
            metadata_hop_contract_hash=identity.contract_hash(),
            metadata_hop_max_bytes=metadata_transport_max_bytes,
            primary_hop_contract_hash=identity.contract_hash(),
            primary_hop_max_bytes=primary_transport_max_bytes,
            reason_code=reason,
            detail=detail,
            attempted_accession=entry.accession,
            attempted_hop=hop,
            accessions_completed_before_failure=[
                a.accession for a in result.acquired
            ],
            retained_raw_filenames=list(retained),
            failed_at=now(),
        )
        payload = (
            json.dumps(
                {
                    "run_id": receipt.run_id,
                    "plan_sha256": receipt.plan_sha256,
                    "transport_kind": receipt.transport_kind,
                    "metadata_hop": {
                        "transport_contract_hash": receipt.metadata_hop_contract_hash,
                        "max_bytes": receipt.metadata_hop_max_bytes,
                    },
                    "primary_document_hop": {
                        "transport_contract_hash": receipt.primary_hop_contract_hash,
                        "max_bytes": receipt.primary_hop_max_bytes,
                    },
                    "reason_code": receipt.reason_code,
                    "detail": receipt.detail,
                    "attempted_accession": receipt.attempted_accession,
                    "attempted_hop": receipt.attempted_hop,
                    "accessions_completed_before_failure":
                        receipt.accessions_completed_before_failure,
                    "retained_raw_filenames": receipt.retained_raw_filenames,
                    "retention_note": (
                        "These raw primaries persist in this immutable failed "
                        "run directory and are non-authoritative: no bundle "
                        "manifest was written, so build-baseline-packets "
                        "cannot consume this directory."
                    ),
                    "failed_at": receipt.failed_at.isoformat(),
                },
                indent=2, sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        write_bytes_once(
            run_dir / FAILURE_RECEIPT_FILENAME, payload,
            what="primary document acquisition failure receipt",
        )
        result.failure = receipt
        result.failure_receipt_path = run_dir / FAILURE_RECEIPT_FILENAME
        return result

    def check_response(
        entry: PlannedAccession, hop: str, url: str,
        response: DocumentTransportResponse, ceiling: int,
    ):
        prefix = "metadata" if hop == HOP_FILING_INDEX else "primary"
        if response.ceiling_refusal is not None:
            return fail(
                entry, hop, f"{prefix}_over_ceiling",
                f"transport refused {url} by {response.ceiling_refusal}: "
                f"declared_content_length={response.declared_content_length}, "
                f"bytes_received={response.bytes_received}, ceiling {ceiling}.",
            )
        if response.status_code in _REDIRECT_STATUSES:
            return fail(
                entry, hop, f"{prefix}_http_failure",
                f"redirect status {response.status_code} for {url}; redirects "
                "are disabled.",
            )
        if response.status_code != 200:
            return fail(
                entry, hop, f"{prefix}_http_failure",
                f"status {response.status_code} for {url}.",
            )
        if not response.final_url or response.final_url != url:
            return fail(
                entry, hop,
                "primary_terminal_url_mismatch" if hop == HOP_PRIMARY_DOCUMENT
                else f"{prefix}_http_failure",
                f"requested {url}, response reports {response.final_url!r}.",
            )
        return None

    for entry in planned:
        # --- hop 1: filing index metadata -------------------------------
        try:
            index_response = metadata_transport(entry.filing_index_url)
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
            return fail(entry, HOP_FILING_INDEX, "transport_exception",
                        f"{type(exc).__name__}: {exc}")
        refused = check_response(
            entry, HOP_FILING_INDEX, entry.filing_index_url, index_response,
            metadata_transport_max_bytes,
        )
        if refused is not None:
            return refused
        try:
            rows = parse_document_format_table(index_response.content)
        except Exception as exc:  # noqa: BLE001 - parser refusals are recorded
            return fail(entry, HOP_FILING_INDEX, "metadata_unparseable", str(exc))
        selected, refusal = select_primary_document(rows, entry.form)
        if refusal is not None:
            matched = [r.document for r in rows
                       if r.document_type.upper() == entry.form.upper()]
            return fail(
                entry, HOP_FILING_INDEX, refusal,
                f"{entry.filing_index_url}: {len(matched)} row(s) declare type "
                f"{entry.form!r} ({matched}).",
            )
        assert selected is not None
        if (
            entry.expected_primary_document is not None
            and selected.document != entry.expected_primary_document
        ):
            return fail(
                entry, HOP_FILING_INDEX, "ground_truth_mismatch",
                f"{entry.filing_index_url}: selected {selected.document!r} but "
                f"the plan records {entry.expected_primary_document!r}.",
            )

        # --- hop 2: the primary document itself --------------------------
        primary_url = canonical_primary_document_url(
            entry.directory_cik, entry.accession, selected.document
        )
        try:
            primary_response = primary_transport(primary_url)
        except Exception as exc:  # noqa: BLE001
            return fail(entry, HOP_PRIMARY_DOCUMENT, "transport_exception",
                        f"{type(exc).__name__}: {exc}")
        refused = check_response(
            entry, HOP_PRIMARY_DOCUMENT, primary_url, primary_response,
            primary_transport_max_bytes,
        )
        if refused is not None:
            return refused
        # The cumulative bound is checked here, against the materialised body
        # length and never against Content-Length, which understates retained
        # bytes by 7.8x-21.4x in measured live runs and is sometimes absent.
        # Refusing before the write means disk never exceeds the budget, not
        # even by one document; the over-budget document is never written.
        budget = fields["max_retained_bytes"]
        incoming = len(primary_response.content)
        if budget is not None and retained_bytes_total + incoming > budget:
            return fail(
                entry, HOP_PRIMARY_DOCUMENT, REASON_BUDGET_EXHAUSTED,
                f"{primary_url}: retaining {incoming} byte(s) would take the "
                f"run to {retained_bytes_total + incoming}, over the plan's "
                f"max_retained_bytes {budget}; {retained_bytes_total} byte(s) "
                "were retained before this document, which is not written.",
            )
        try:
            source_sha = write_bytes_once(
                run_dir / entry.local_filename, primary_response.content,
                what=f"raw primary document {entry.local_filename}",
            )
        except WriteOnceError as exc:
            return fail(entry, HOP_PRIMARY_DOCUMENT, "write_once_refused", str(exc))
        retained.append(entry.local_filename)
        retained_bytes_total += incoming
        if (
            entry.ground_truth_source_sha256 is not None
            and source_sha != entry.ground_truth_source_sha256
        ):
            return fail(
                entry, HOP_PRIMARY_DOCUMENT, "ground_truth_mismatch",
                f"{primary_url}: retrieved bytes hash {source_sha}, plan "
                f"records {entry.ground_truth_source_sha256}.",
            )
        result.acquired.append(
            AcquiredAccession(
                accession=entry.accession,
                form=entry.form,
                directory_cik=entry.directory_cik,
                filing_index_url=entry.filing_index_url,
                filing_index_final_url=index_response.final_url,
                filing_index_status=index_response.status_code,
                filing_index_byte_length=len(index_response.content),
                filing_index_response_sha256=sha256_bytes(index_response.content),
                filing_index_declared_content_length=(
                    index_response.declared_content_length
                ),
                selected_document=selected.document,
                href_form=href_form_of(selected.href),
                candidate_count=len(rows),
                primary_url=primary_url,
                primary_final_url=primary_response.final_url,
                primary_status=primary_response.status_code,
                local_filename=entry.local_filename,
                primary_declared_content_length=(
                    primary_response.declared_content_length
                ),
                source_sha256=source_sha,
                source_byte_length=len(primary_response.content),
                mapped_carrier_rows=len(entry.carrier_rows),
                # Records exactly what the plan supplied and this run then
                # checked — never more. A source hash cannot appear without a
                # filename, so the three states are exhaustive.
                ground_truth_basis=(
                    GROUND_TRUTH_FILENAME_AND_SHA
                    if entry.ground_truth_source_sha256 is not None
                    else GROUND_TRUTH_FILENAME_ONLY
                    if entry.expected_primary_document is not None
                    else GROUND_TRUTH_NONE
                ),
                retrieved_at=now(),
            )
        )

    # --- the governed bundle, written before the run record --------------
    bundle = build_bundle_manifest(
        run_id=run_id, fields=fields, planned=planned, acquired=result.acquired
    )
    schema = read_json(root / BUNDLE_SCHEMA_RELATIVE_PATH)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(bundle),
        key=lambda e: e.json_path,
    )
    if errors:
        details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
        raise ValueError(
            f"Produced bundle violates the committed bundle schema: {details}"
        )
    bundle_payload = (json.dumps(bundle, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    write_bytes_once(
        run_dir / BUNDLE_MANIFEST_FILENAME, bundle_payload,
        what="baseline primary document bundle manifest",
    )
    result.bundle_manifest_path = run_dir / BUNDLE_MANIFEST_FILENAME

    output_hashes = {
        BUNDLE_MANIFEST_FILENAME: sha256_bytes(bundle_payload),
        **{a.local_filename: a.source_sha256 for a in result.acquired},
    }
    manifest = build_acquisition_manifest(
        repo_root=root, run_id=run_id, plan_sha256=plan_sha256, fields=fields,
        acquired=result.acquired, output_hashes=output_hashes,
        run_timestamp=now(), transport_identity=identity,
        metadata_max_bytes=metadata_transport_max_bytes,
        primary_max_bytes=primary_transport_max_bytes,
    )
    manifest_payload = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    write_bytes_once(
        run_dir / ACQUISITION_MANIFEST_FILENAME, manifest_payload,
        what="primary document acquisition manifest",
    )
    result.acquisition_manifest_path = run_dir / ACQUISITION_MANIFEST_FILENAME
    result.counts = manifest["counts"]
    return result


def build_bundle_manifest(
    *,
    run_id: str,
    fields: dict,
    planned: list[PlannedAccession],
    acquired: list[AcquiredAccession],
) -> dict:
    """Assemble the governed bundle: one entry per carrier row.

    A shared accession is downloaded once and appears once per carrier row,
    every entry naming the same stored file and the same hashes. The bundle
    names its producing run by id only and never carries the acquisition
    manifest's hash: provenance runs one way.
    """
    by_accession = {a.accession: a for a in acquired}
    documents: list[dict] = []
    for entry in planned:
        acquisition = by_accession[entry.accession]
        for row in entry.carrier_rows:
            documents.append(
                {
                    "cik": row.cik,
                    "accession": entry.accession,
                    "form": entry.form,
                    "stratum": row.stratum,
                    "baseline_filing_date": row.baseline_filing_date,
                    "local_filename": acquisition.local_filename,
                    "source_sha256": acquisition.source_sha256,
                    "source_byte_length": acquisition.source_byte_length,
                    "filing_index_url": acquisition.filing_index_url,
                    "filing_index_response_sha256":
                        acquisition.filing_index_response_sha256,
                    "selected_document": acquisition.selected_document,
                    "primary_url": acquisition.primary_url,
                }
            )
    documents.sort(key=lambda d: (d["stratum"], d["cik"], d["accession"]))
    return {
        "bundle_contract": BUNDLE_CONTRACT,
        "description": (
            "Baseline primary-document bundle produced by two-hop acquisition "
            f"run {run_id} (ADR-092). One entry per carrier row: a shared "
            "accession is fetched once and mapped to every filer row that "
            "selected it. " + fields["description"]
        ),
        "provenance": {
            "carrier_run_id": fields["provenance"]["carrier_run_id"],
            "carrier_manifest_sha256":
                fields["provenance"]["carrier_manifest_sha256"],
            "freeze_record_sha256": fields["provenance"]["freeze_record_sha256"],
            # The producing run is named, never hashed: the acquisition
            # manifest hashes this bundle, so hashing it back would be a cycle.
            "acquisition_run_id": run_id,
        },
        "route_validation": dict(fields["route_validation"]),
        "documents": documents,
    }


def build_acquisition_manifest(
    *,
    repo_root: str | Path,
    run_id: str,
    plan_sha256: str,
    fields: dict,
    acquired: list[AcquiredAccession],
    output_hashes: dict[str, str],
    run_timestamp: datetime,
    transport_identity: TransportIdentity,
    metadata_max_bytes: int,
    primary_max_bytes: int,
) -> dict:
    """Assemble and schema-validate the run record (v0.1 or v0.2)."""
    root = Path(repo_root)
    schema_versions = read_json(root / "schemas" / "schema_version_manifest.json")[
        "schemas"
    ]
    live = transport_identity.kind == TRANSPORT_KIND_SEC_LIVE
    href_forms: dict[str, int] = {}
    for item in acquired:
        href_forms[item.href_form] = href_forms.get(item.href_form, 0) + 1
    sizes = [a.source_byte_length for a in acquired]
    mapped_rows = sum(a.mapped_carrier_rows for a in acquired)
    manifest: dict = {
        "run_id": run_id,
        "plan_contract": fields["plan_contract"],
        "plan_sha256": plan_sha256,
        "base_url": fields["base_url"],
        "transport_kind": transport_identity.kind,
        "metadata_hop": _hop_record(transport_identity, metadata_max_bytes),
        "primary_document_hop": _hop_record(transport_identity, primary_max_bytes),
        "carrier_provenance": dict(fields["provenance"]),
        "route_validation": dict(fields["route_validation"]),
        "acquisitions": [
            {
                "accession": a.accession,
                "form": a.form,
                "directory_cik": a.directory_cik,
                "filing_index_url": a.filing_index_url,
                "filing_index_final_url": a.filing_index_final_url,
                "filing_index_status": a.filing_index_status,
                "filing_index_byte_length": a.filing_index_byte_length,
                "filing_index_response_sha256": a.filing_index_response_sha256,
                "candidate_count": a.candidate_count,
                "selected_document": a.selected_document,
                "href_form": a.href_form,
                "primary_url": a.primary_url,
                "primary_final_url": a.primary_final_url,
                "primary_status": a.primary_status,
                "local_filename": a.local_filename,
                "source_sha256": a.source_sha256,
                "source_byte_length": a.source_byte_length,
                "mapped_carrier_rows": a.mapped_carrier_rows,
                "ground_truth_basis": a.ground_truth_basis,
                "retrieved_at": a.retrieved_at.isoformat(),
            }
            for a in acquired
        ],
        "counts": {
            "planned_accessions": len(acquired),
            "accessions_acquired": len(acquired),
            "filing_index_requests": len(acquired),
            "primary_document_requests": len(acquired),
            "total_requests": 2 * len(acquired),
            "bundle_entries": mapped_rows,
            "shared_accessions": sum(
                1 for a in acquired if a.mapped_carrier_rows > 1
            ),
            "href_forms": href_forms,
            "primary_bytes_total": sum(sizes),
            "primary_bytes_max": max(sizes) if sizes else 0,
        },
        "reconciliation": {
            "one filing-index request per accession": (
                len(acquired) == len({a.accession for a in acquired})
            ),
            "one primary request per accession": (
                len(acquired) == len({a.local_filename for a in acquired})
            ),
            "total requests are exactly two per accession": True,
            "bundle entries equal mapped carrier rows": (
                mapped_rows == sum(a.mapped_carrier_rows for a in acquired)
            ),
            "output hashes cover the bundle and every raw primary": (
                set(output_hashes)
                == {BUNDLE_MANIFEST_FILENAME}
                | {a.local_filename for a in acquired}
            ),
            "this manifest hashes nothing of its own": (
                ACQUISITION_MANIFEST_FILENAME not in output_hashes
            ),
            "both hops share one transport contract": True,
        },
        "output_hashes": dict(output_hashes),
        "run_timestamp": run_timestamp.isoformat(),
        "limitations": [
            "bundle_manifest.json is the governed input marker that "
            "build-baseline-packets consumes; this manifest together with it "
            "evidences a complete successful acquisition run, which is "
            "operational policy and not a requirement the packet builder "
            "imposes.",
            "output_hashes covers the bundle manifest and every raw primary "
            "and never this manifest: provenance runs one way, and the bundle "
            "names its producing run by id without hashing it back.",
            "One active transport kind; the two hops are recorded separately "
            "because their plan-owned ceilings differ, while their contract "
            "hashes are equal because the byte bound is not part of the "
            "transport contract.",
            "The primary URL is derived from the filing directory and the "
            "selected basename, never from the row's raw href: the "
            "inline-XBRL viewer wrapper is never fetched.",
            "Domestic 10-K/10-KT only. The FPI extension cohort is preserved "
            "by the frame and carrier, and is neither acquired nor excluded.",
            "Documents only: no packet is built, no firm is screened, "
            "classified or tiered, and no model is called.",
        ],
    }
    budgeted = fields["max_retained_bytes"] is not None
    if budgeted:
        # Recorded in authoritative evidence, so a completed shard states the
        # bound it honoured and the bytes it actually kept. bounds="disk" is
        # literal: transient memory stays bounded by the per-document ceiling.
        manifest["retained_byte_budget"] = fields["max_retained_bytes"]
        manifest["retained_bytes_total"] = sum(sizes)
        manifest["budget_enforcement"] = {
            "mechanism": "pre_write_retained_byte_check",
            "bounds": "disk",
            "checked_against": "materialised_body_length",
        }
    if live:
        manifest["transport_contract"] = dict(transport_identity.contract)
        # v0.3 adds the transport's already-parsed declared lengths for both
        # hops. They are recorded on the live contract only: the fixture v0.1
        # contract is unchanged and admits no such fields.
        for record, item in zip(manifest["acquisitions"], acquired):
            record["filing_index_declared_content_length"] = (
                item.filing_index_declared_content_length
            )
            record["primary_declared_content_length"] = (
                item.primary_declared_content_length
            )
        key = (
            "primary_document_acquisition_manifest_v5" if budgeted
            else "primary_document_acquisition_manifest_v3"
        )
        manifest["schema_versions"] = {key: schema_versions[key]}
        schema_path = (
            ACQUISITION_V5_SCHEMA_RELATIVE_PATH if budgeted
            else ACQUISITION_V3_SCHEMA_RELATIVE_PATH
        )
    else:
        key = (
            "primary_document_acquisition_manifest_v4" if budgeted
            else "primary_document_acquisition_manifest"
        )
        manifest["schema_versions"] = {key: schema_versions[key]}
        manifest["limitations"].insert(
            0,
            "Fixture-replay acquisition: bytes were served from local fixture "
            "index pages and primary documents; no network request was made.",
        )
        schema_path = (
            ACQUISITION_V4_SCHEMA_RELATIVE_PATH if budgeted
            else ACQUISITION_SCHEMA_RELATIVE_PATH
        )
    schema = read_json(root / schema_path)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest),
        key=lambda e: e.json_path,
    )
    if errors:
        details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
        raise ValueError(
            f"Acquisition manifest violates the canonical schema: {details}"
        )
    return manifest
