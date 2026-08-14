"""EDGAR full-index FRAME builder (fixture-only increment).

Governing documents:
- specs/SPEC-001-company-universe.md (Stage A: historical filer frame)
- docs/THESIS_EXECUTION_PLAN.md (W1: FRAME_v1)
- docs/methodology/SOFTWARE_FIRM_UNIVERSE.md (Section 6.1)

Parses SEC EDGAR full-index ``master.idx`` files supplied as local fixtures
and assembles the per-accession annual-filing frame. The frame preserves
filing history: one record per annual-filing accession, no CIK or firm-year
collapse. Amendment forms (``10-K/A``-style) never create an annual
observation; they are represented in a separate amendment-link artefact whose
original relationship is an explicit deterministic candidate, not a proven
link.

Row accounting is exhaustive and mutually exclusive, with this precedence:

    parse failure
    -> integrity failure (conflicting rows sharing one accession)
    -> duplicate (identical repeated row for an already-admitted accession)
    -> out-of-window (filing date outside the filing window)
    -> form partition: domestic annual | FPI extension | amendment link
       | out-of-scope form

Out-of-scope-form and out-of-window rows are counted (per form for the
former), not copied into run artefacts: the hashed immutable index files
remain their recoverable record.

The filing window is a pair of explicit filing-date bounds,
``filing_window_start`` and ``filing_window_end``. It is an admission bound
on ``Date Filed`` only; fiscal-period assignment is a later PCT/schema
concern and is never performed here. ``baseline_status`` is likewise never
assigned: the baseline cutoff belongs to the W0 design gate.

W0 boundary: this module performs no network access and calls no model. It
may only run over local fixture files until the W0 design gate opens live
collection.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from jsonschema import Draft202012Validator
from pydantic import Field, model_validator

from . import UNIVERSE_CODE_VERSION
from .frame_acquisition import ACQUISITION_MANIFEST_SCHEMA_RELATIVE_PATH
from .freeze import create_run_directory
from .identifiers import IdentifierError, normalize_accession, normalize_cik
from .io_utils import read_json, sha256_file, write_json, write_jsonl
from .models import HistoricalAnnualFiler, StrictModel

MASTER_INDEX_HEADER = "CIK|Company Name|Form Type|Date Filed|Filename"
AMENDMENT_SUFFIX = "/A"
AMENDMENT_CANDIDATE_RULE = (
    "latest_same_cik_same_base_form_filing_dated_on_or_before_amendment_v1"
)
FRAME_MANIFEST_SCHEMA_RELATIVE_PATH = Path("schemas/filer_frame_manifest.schema.json")
FIXTURE_MANIFEST_FILENAME = "fixture_manifest.json"

# Code-owned frame version for builds that consume an acquisition manifest.
# The label is fixed here, never CLI-supplied; the FRAME_v1 freeze (a later
# increment) records the released version.
FRAME_VERSION_ON_ACQUIRED_BUILD = "FRAME_v1.0-draft"

_SEPARATOR_RE = re.compile(r"^-{10,}\s*$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class FrameInputError(ValueError):
    """The index bundle, parameters, or master.idx structure is invalid."""


class FrameReconciliationError(RuntimeError):
    """A frame count identity failed; the run is refused, nothing is written."""


class ParsedIndexRow(StrictModel):
    """One structurally valid master.idx data row.

    ``accession_number`` is derived deterministically from the SEC
    ``Filename`` field (basename stem, validated by the canonical accession
    normalization); the raw ``Filename`` value is preserved verbatim in
    ``sec_filename`` as provenance.
    """

    cik: str
    company_name: str
    form: str
    date_filed: date
    accession_number: str
    sec_filename: str
    source_index_file: str
    source_line: int

    def content_key(self) -> tuple[str, str, str, str, str, str]:
        """Row identity excluding provenance; used for duplicate detection."""
        return (
            self.cik,
            self.company_name,
            self.form,
            str(self.date_filed),
            self.accession_number,
            self.sec_filename,
        )


class FrameParseFailure(StrictModel):
    """One data line that could not become a row. Never silently dropped."""

    source_index_file: str
    source_line: int
    reason_code: Literal[
        "wrong_field_count",
        "empty_field",
        "invalid_cik",
        "invalid_date",
        "invalid_accession_filename",
    ]
    raw_line: str


class FrameDuplicateRow(StrictModel):
    """An identical repeat of an already-admitted accession row."""

    accession_number: str
    cik: str
    source_index_file: str
    source_line: int
    first_source_index_file: str
    first_source_line: int


class FrameIntegrityFailure(StrictModel):
    """Conflicting rows sharing one accession. None of them enters the frame:
    the accession's true fields are unknown, and unknown is never coerced."""

    accession_number: str
    reason_code: Literal["conflicting_same_accession_rows"] = (
        "conflicting_same_accession_rows"
    )
    rows: list[ParsedIndexRow] = Field(min_length=2)


class AmendmentLink(StrictModel):
    """An amendment filing with a deterministic candidate original.

    ``candidate_original_accession`` names the latest eligible same-CIK,
    same-base-form annual record filed on or before the amendment date. It is
    a deterministic candidate derived from index metadata only — not a proven
    amendment-to-original relationship, which would require reading the
    amendment's own cover page. ``unmatched`` means no eligible preceding
    filing exists in the admitted frame.
    """

    cik: str
    company_name: str
    amendment_accession: str
    amendment_form: str
    amendment_filing_date: date
    sec_filename: str
    source_index_file: str
    source_line: int
    partition: Literal["domestic", "fpi_extension"]
    candidate_status: Literal["deterministic_candidate", "unmatched"]
    candidate_original_accession: Optional[str] = None
    candidate_original_filing_date: Optional[date] = None
    candidate_rule: str = AMENDMENT_CANDIDATE_RULE

    @model_validator(mode="after")
    def _candidate_fields_match_status(self) -> "AmendmentLink":
        has_candidate = self.candidate_original_accession is not None
        if self.candidate_status == "deterministic_candidate" and not has_candidate:
            raise ValueError(
                "deterministic_candidate requires candidate_original_accession."
            )
        if self.candidate_status == "unmatched" and has_candidate:
            raise ValueError("unmatched must not carry a candidate accession.")
        return self


@dataclass(frozen=True)
class FrameParameters:
    """Explicit frame parameters. The window bounds admission by filing date
    only; no default exists for either bound."""

    filing_window_start: date
    filing_window_end: date
    domestic_forms: tuple[str, ...]
    extension_forms: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.filing_window_start > self.filing_window_end:
            raise FrameInputError(
                f"filing_window_start {self.filing_window_start} is after "
                f"filing_window_end {self.filing_window_end}."
            )
        if not self.domestic_forms:
            raise FrameInputError("domestic_forms must not be empty.")
        overlap = sorted(set(self.domestic_forms) & set(self.extension_forms))
        if overlap:
            raise FrameInputError(
                f"domestic_forms and extension_forms overlap: {overlap}"
            )


@dataclass
class ParsedIndexFile:
    """Structural parse of one master.idx file."""

    source_name: str
    rows: list[ParsedIndexRow]
    parse_failures: list[FrameParseFailure]
    data_lines: int


@dataclass
class FrameResult:
    """Full in-memory frame build with exhaustive row accounting."""

    parameters: FrameParameters
    domestic_records: list[HistoricalAnnualFiler]
    extension_records: list[HistoricalAnnualFiler]
    amendment_links: list[AmendmentLink]
    parse_failures: list[FrameParseFailure]
    duplicate_rows: list[FrameDuplicateRow]
    integrity_failures: list[FrameIntegrityFailure]
    out_of_scope_form_counts: dict[str, int]
    counts: dict[str, int]
    reconciliation: dict[str, bool]


@dataclass
class FrameRunResult:
    """Outcome of one frame-builder run (dry or written)."""

    run_id: str
    run_dir: Path | None
    dry_run: bool
    frame_version: str
    counts: dict[str, int]
    out_of_scope_form_counts: dict[str, int]
    reconciliation: dict[str, bool]
    manifest_path: Path | None = None


def parse_master_index(text: str, *, source_name: str) -> ParsedIndexFile:
    """Parse one master.idx file.

    The preamble above the table header may vary (historical EDGAR preambles
    do); the canonical column-header line and the dashed separator directly
    beneath it are required exactly. A malformed data line becomes an explicit
    parse-failure record, never a silent skip.
    """
    lines = text.splitlines()
    header_at = None
    for index, line in enumerate(lines):
        if line.strip() == MASTER_INDEX_HEADER:
            header_at = index
            break
    if header_at is None:
        raise FrameInputError(
            f"{source_name}: canonical master.idx table header not found "
            f"(expected {MASTER_INDEX_HEADER!r})."
        )
    if header_at + 1 >= len(lines) or not _SEPARATOR_RE.match(lines[header_at + 1]):
        raise FrameInputError(
            f"{source_name}: dashed separator line missing directly after the "
            "table header."
        )
    rows: list[ParsedIndexRow] = []
    failures: list[FrameParseFailure] = []
    data_lines = 0
    for line_number, raw in enumerate(lines[header_at + 2 :], start=header_at + 3):
        if not raw.strip():
            continue
        data_lines += 1
        parsed = _parse_data_line(raw, source_name=source_name, line_number=line_number)
        if isinstance(parsed, ParsedIndexRow):
            rows.append(parsed)
        else:
            failures.append(parsed)
    return ParsedIndexFile(
        source_name=source_name,
        rows=rows,
        parse_failures=failures,
        data_lines=data_lines,
    )


def _parse_data_line(
    raw: str, *, source_name: str, line_number: int
) -> ParsedIndexRow | FrameParseFailure:
    def failure(reason: str) -> FrameParseFailure:
        return FrameParseFailure(
            source_index_file=source_name,
            source_line=line_number,
            reason_code=reason,  # type: ignore[arg-type]
            raw_line=raw,
        )

    fields = [part.strip() for part in raw.split("|")]
    if len(fields) != 5:
        return failure("wrong_field_count")
    cik_raw, company_name, form, date_raw, filename = fields
    if not company_name or not form or not filename:
        return failure("empty_field")
    try:
        cik = normalize_cik(cik_raw)
    except IdentifierError:
        return failure("invalid_cik")
    try:
        filed = date.fromisoformat(date_raw)
    except ValueError:
        return failure("invalid_date")
    accession = _accession_from_filename(filename)
    if accession is None:
        return failure("invalid_accession_filename")
    return ParsedIndexRow(
        cik=cik,
        company_name=company_name,
        form=form,
        date_filed=filed,
        accession_number=accession,
        sec_filename=filename,
        source_index_file=source_name,
        source_line=line_number,
    )


def _accession_from_filename(filename: str) -> str | None:
    """Derive the accession deterministically from the index Filename field.

    The basename stem of e.g. ``edgar/data/1/0000000001-22-000002.txt`` must
    normalize under the canonical accession rule; anything else is a parse
    failure, never a guess.
    """
    basename = filename.rsplit("/", 1)[-1]
    stem = basename.rsplit(".", 1)[0] if "." in basename else basename
    try:
        return normalize_accession(stem)
    except IdentifierError:
        return None


def build_frame(
    parsed_files: list[ParsedIndexFile], parameters: FrameParameters
) -> FrameResult:
    """Assemble the per-accession frame from parsed index files.

    Raises :class:`FrameReconciliationError` if any count identity fails.
    """
    all_rows = [row for parsed in parsed_files for row in parsed.rows]
    parse_failures = sorted(
        (item for parsed in parsed_files for item in parsed.parse_failures),
        key=lambda item: (item.source_index_file, item.source_line),
    )

    by_accession: dict[str, list[ParsedIndexRow]] = {}
    for row in all_rows:
        by_accession.setdefault(row.accession_number, []).append(row)

    admitted: list[ParsedIndexRow] = []
    duplicates: list[FrameDuplicateRow] = []
    integrity: list[FrameIntegrityFailure] = []
    for accession in sorted(by_accession):
        group = by_accession[accession]
        if len({row.content_key() for row in group}) > 1:
            integrity.append(
                FrameIntegrityFailure(accession_number=accession, rows=group)
            )
            continue
        first, *rest = group
        admitted.append(first)
        for row in rest:
            duplicates.append(
                FrameDuplicateRow(
                    accession_number=accession,
                    cik=row.cik,
                    source_index_file=row.source_index_file,
                    source_line=row.source_line,
                    first_source_index_file=first.source_index_file,
                    first_source_line=first.source_line,
                )
            )

    domestic_scope = set(parameters.domestic_forms)
    extension_scope = set(parameters.extension_forms)
    in_scope_bases = domestic_scope | extension_scope
    domestic_rows: list[ParsedIndexRow] = []
    extension_rows: list[ParsedIndexRow] = []
    amendment_rows: list[ParsedIndexRow] = []
    out_of_scope: dict[str, int] = {}
    out_of_window = 0
    for row in admitted:
        in_window = (
            parameters.filing_window_start
            <= row.date_filed
            <= parameters.filing_window_end
        )
        if not in_window:
            out_of_window += 1
        elif row.form in domestic_scope:
            domestic_rows.append(row)
        elif row.form in extension_scope:
            extension_rows.append(row)
        elif (
            row.form.endswith(AMENDMENT_SUFFIX)
            and row.form[: -len(AMENDMENT_SUFFIX)] in in_scope_bases
        ):
            amendment_rows.append(row)
        else:
            out_of_scope[row.form] = out_of_scope.get(row.form, 0) + 1

    annuals_by_cik_form: dict[tuple[str, str], list[ParsedIndexRow]] = {}
    for row in [*domestic_rows, *extension_rows]:
        annuals_by_cik_form.setdefault((row.cik, row.form), []).append(row)

    links: list[AmendmentLink] = []
    for row in sorted(amendment_rows, key=lambda r: (r.cik, r.accession_number)):
        base_form = row.form[: -len(AMENDMENT_SUFFIX)]
        partition = "domestic" if base_form in domestic_scope else "fpi_extension"
        candidates = [
            annual
            for annual in annuals_by_cik_form.get((row.cik, base_form), [])
            if annual.date_filed <= row.date_filed
        ]
        common = {
            "cik": row.cik,
            "company_name": row.company_name,
            "amendment_accession": row.accession_number,
            "amendment_form": row.form,
            "amendment_filing_date": row.date_filed,
            "sec_filename": row.sec_filename,
            "source_index_file": row.source_index_file,
            "source_line": row.source_line,
            "partition": partition,
        }
        if candidates:
            best = max(candidates, key=lambda a: (a.date_filed, a.accession_number))
            links.append(
                AmendmentLink(
                    **common,
                    candidate_status="deterministic_candidate",
                    candidate_original_accession=best.accession_number,
                    candidate_original_filing_date=best.date_filed,
                )
            )
        else:
            links.append(AmendmentLink(**common, candidate_status="unmatched"))

    domestic_records = [
        _filer_record(row)
        for row in sorted(domestic_rows, key=lambda r: (r.cik, r.accession_number))
    ]
    extension_records = [
        _filer_record(row)
        for row in sorted(extension_rows, key=lambda r: (r.cik, r.accession_number))
    ]

    with_candidate = sum(
        1 for link in links if link.candidate_status == "deterministic_candidate"
    )
    counts = {
        "index_files": len(parsed_files),
        "data_lines": sum(parsed.data_lines for parsed in parsed_files),
        "parsed_rows": len(all_rows),
        "parse_failures": len(parse_failures),
        "integrity_failure_rows": sum(len(item.rows) for item in integrity),
        "duplicate_rows": len(duplicates),
        "admitted_rows": len(admitted),
        "domestic_annual_records": len(domestic_records),
        "fpi_extension_records": len(extension_records),
        "amendment_links": len(links),
        "amendment_links_with_candidate": with_candidate,
        "amendment_links_unmatched": len(links) - with_candidate,
        "out_of_scope_form_rows": sum(out_of_scope.values()),
        "out_of_window_rows": out_of_window,
    }
    reconciliation = {
        "data_lines = parsed_rows + parse_failures": counts["data_lines"]
        == counts["parsed_rows"] + counts["parse_failures"],
        "parsed_rows = admitted_rows + duplicate_rows + integrity_failure_rows": counts[
            "parsed_rows"
        ]
        == counts["admitted_rows"]
        + counts["duplicate_rows"]
        + counts["integrity_failure_rows"],
        "admitted_rows = domestic + fpi_extension + amendment_links"
        " + out_of_scope_form_rows + out_of_window_rows": counts["admitted_rows"]
        == counts["domestic_annual_records"]
        + counts["fpi_extension_records"]
        + counts["amendment_links"]
        + counts["out_of_scope_form_rows"]
        + counts["out_of_window_rows"],
        "amendment_links = with_candidate + unmatched": counts["amendment_links"]
        == counts["amendment_links_with_candidate"]
        + counts["amendment_links_unmatched"],
    }
    failed = [name for name, holds in reconciliation.items() if not holds]
    if failed:
        raise FrameReconciliationError(
            f"Frame count reconciliation failed: {failed}"
        )
    return FrameResult(
        parameters=parameters,
        domestic_records=domestic_records,
        extension_records=extension_records,
        amendment_links=links,
        parse_failures=parse_failures,
        duplicate_rows=duplicates,
        integrity_failures=integrity,
        out_of_scope_form_counts=dict(sorted(out_of_scope.items())),
        counts=counts,
        reconciliation=reconciliation,
    )


def _filer_record(row: ParsedIndexRow) -> HistoricalAnnualFiler:
    """Map an admitted index row to the canonical frame row type.

    Fields the full index cannot supply stay unset, and ``baseline_status``
    keeps its ``unknown`` default: the baseline cutoff is a W0 decision. The
    raw SEC filename and the index-file position are carried as source ids.
    """
    return HistoricalAnnualFiler(
        cik=row.cik,
        canonical_name=row.company_name,
        accession_number=row.accession_number,
        filing_date=row.date_filed,
        form=row.form,
        source_ids=[
            f"edgar_full_index:{row.source_index_file}#L{row.source_line}",
            f"sec_filename:{row.sec_filename}",
        ],
    )


def run_frame_builder(
    *,
    repo_root: str | Path,
    project_config_path: str | Path,
    index_dir: str | Path | None = None,
    output_dir: str | Path,
    run_id: str,
    filing_window_start: date,
    filing_window_end: date,
    dry_run: bool = False,
    acquisition_manifest_path: str | Path | None = None,
) -> FrameRunResult:
    """Run the frame build from one index inventory; unless dry, write the run.

    Exactly one inventory source is required: ``index_dir`` (a fixture bundle
    carrying ``fixture_manifest.json``) or ``acquisition_manifest_path`` (an
    acquisition manifest that is validated against its canonical schema, must
    carry ``transport_kind == "fixture_replay"`` — the only reviewed
    consumption path in v0.1 — may not repeat a receipt filename, and whose
    raw-file hashes are verified against their receipts before any parsing;
    the frame version for that route is the code-owned
    ``FRAME_VERSION_ON_ACQUIRED_BUILD`` label, never caller text).
    """
    root = Path(repo_root)
    if not _RUN_ID_RE.match(run_id):
        raise FrameInputError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )
    config_path = Path(project_config_path)
    if not config_path.is_file():
        raise FrameInputError(f"Project config not found: {config_path}")
    import yaml

    project_config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    universe_config = project_config.get("universe") or {}
    domestic_forms = tuple(universe_config.get("domestic_form_scope") or ())
    extension_forms = tuple(
        universe_config.get("foreign_private_issuer_extension_forms") or ()
    )
    if not domestic_forms:
        raise FrameInputError(
            f"{config_path} declares no universe.domestic_form_scope."
        )
    parameters = FrameParameters(
        filing_window_start=filing_window_start,
        filing_window_end=filing_window_end,
        domestic_forms=domestic_forms,
        extension_forms=extension_forms,
    )

    if (index_dir is None) == (acquisition_manifest_path is None):
        raise FrameInputError(
            "Exactly one index inventory source is required: index_dir or "
            "acquisition_manifest_path."
        )
    if acquisition_manifest_path is not None:
        manifest_file = Path(acquisition_manifest_path)
        if not manifest_file.is_file():
            raise FrameInputError(
                f"Acquisition manifest not found: {manifest_file}"
            )
        acquisition = read_json(manifest_file)
        acquisition_schema = read_json(
            root / ACQUISITION_MANIFEST_SCHEMA_RELATIVE_PATH
        )
        schema_errors = sorted(
            Draft202012Validator(acquisition_schema).iter_errors(acquisition),
            key=lambda e: e.json_path,
        )
        if schema_errors:
            details = "; ".join(
                f"{e.json_path}: {e.message}" for e in schema_errors[:5]
            )
            raise FrameInputError(
                f"Acquisition manifest violates its canonical schema: {details}"
            )
        # v0.1 consumption path: only fixture_replay is admitted, checked
        # explicitly beside the schema enum. A live successor schema must get
        # its own reviewed consumption path here, not a widened conditional.
        if acquisition["transport_kind"] != "fixture_replay":
            raise FrameInputError(
                "Acquisition manifest transport_kind "
                f"{acquisition['transport_kind']!r} has no reviewed frame-"
                "consumption path; only 'fixture_replay' is admitted."
            )
        index_path = manifest_file.parent
        receipt_by_name: dict[str, str] = {}
        for item in acquisition["files"]:
            name = str(item["filename"])
            if "/" in name or "\\" in name or ".." in name:
                raise FrameInputError(
                    f"Unsafe filename in acquisition manifest: {name!r}"
                )
            if name in receipt_by_name:
                raise FrameInputError(
                    "Duplicate receipt filename in acquisition manifest: "
                    f"{name!r}"
                )
            receipt_by_name[name] = str(item["sha256"])
        listed = sorted(receipt_by_name)
        present = sorted(path.name for path in index_path.glob("*.idx"))
        if listed != present:
            raise FrameInputError(
                "acquisition manifest files and on-disk *.idx files disagree: "
                f"listed={listed}, present={present}"
            )
        for name in listed:
            observed = sha256_file(index_path / name)
            if observed != receipt_by_name[name]:
                raise FrameInputError(
                    f"Acquired index file hash mismatch for {name}: receipt "
                    f"{receipt_by_name[name]}, observed {observed}. "
                    "Refusing to parse."
                )
        frame_version = FRAME_VERSION_ON_ACQUIRED_BUILD
        limitations = [
            "Index inventory from acquisition manifest "
            f"sha256={sha256_file(manifest_file)}; every raw-file hash "
            "verified against its receipt before parsing.",
            "Out-of-scope-form and out-of-window rows are counted, not "
            "copied; the hashed index files are their recoverable record.",
            "Amendment originals are deterministic candidates derived from "
            "index metadata only, not proven relationships.",
            "Acquisition transport was fixture_replay, not live EDGAR "
            "retrieval (W0 gate).",
        ]
    else:
        index_path = Path(index_dir)
        if not index_path.is_dir():
            raise FrameInputError(f"Index fixture directory not found: {index_path}")
        fixture_manifest_path = index_path / FIXTURE_MANIFEST_FILENAME
        if not fixture_manifest_path.is_file():
            raise FrameInputError(
                f"Index fixture bundle is missing {FIXTURE_MANIFEST_FILENAME}."
            )
        fixture_manifest = read_json(fixture_manifest_path)
        required_keys = {"description", "frame_version_on_build", "index_files"}
        missing = required_keys - set(fixture_manifest)
        if missing:
            raise FrameInputError(
                f"{FIXTURE_MANIFEST_FILENAME} is missing keys: {sorted(missing)}"
            )
        listed = sorted(str(name) for name in fixture_manifest["index_files"])
        present = sorted(path.name for path in index_path.glob("*.idx"))
        if listed != present:
            raise FrameInputError(
                "fixture index_files and on-disk *.idx files disagree: "
                f"listed={listed}, present={present}"
            )
        frame_version = str(fixture_manifest["frame_version_on_build"])
        limitations = [
            "Fixture-only frame build: the index files are local synthetic "
            "fixtures, not live EDGAR full-index retrievals (W0 gate).",
            "Out-of-scope-form and out-of-window rows are counted, not "
            "copied; the hashed index files are their recoverable record.",
            "Amendment originals are deterministic candidates derived from "
            "index metadata only, not proven relationships.",
            f"Fixture bundle: {fixture_manifest['description']}",
        ]

    parsed_files: list[ParsedIndexFile] = []
    index_file_entries: list[dict] = []
    for name in listed:
        path = index_path / name
        parsed = parse_master_index(
            path.read_text(encoding="utf-8"), source_name=name
        )
        parsed_files.append(parsed)
        index_file_entries.append(
            {
                "filename": name,
                "sha256": sha256_file(path),
                "data_lines": parsed.data_lines,
                "parsed_rows": len(parsed.rows),
                "parse_failures": len(parsed.parse_failures),
            }
        )

    frame = build_frame(parsed_files, parameters)
    result = FrameRunResult(
        run_id=run_id,
        run_dir=None,
        dry_run=dry_run,
        frame_version=frame_version,
        counts=frame.counts,
        out_of_scope_form_counts=frame.out_of_scope_form_counts,
        reconciliation=frame.reconciliation,
    )
    if dry_run:
        return result

    run_dir = create_run_directory(output_dir, run_id)
    outputs = {
        "historical_annual_filers.jsonl": [
            record.model_dump(mode="json") for record in frame.domestic_records
        ],
        "fpi_extension_filers.jsonl": [
            record.model_dump(mode="json") for record in frame.extension_records
        ],
        "amendment_links.jsonl": [
            link.model_dump(mode="json") for link in frame.amendment_links
        ],
        "frame_parse_failures.jsonl": [
            item.model_dump(mode="json") for item in frame.parse_failures
        ],
        "frame_duplicates.jsonl": [
            item.model_dump(mode="json") for item in frame.duplicate_rows
        ],
        "frame_integrity_failures.jsonl": [
            item.model_dump(mode="json") for item in frame.integrity_failures
        ],
    }
    output_hashes: dict[str, str] = {}
    for filename, records in outputs.items():
        path = write_jsonl(run_dir / filename, records)
        output_hashes[filename] = sha256_file(path)

    manifest = build_frame_manifest(
        repo_root=root,
        run_id=run_id,
        frame_version=frame_version,
        parameters=parameters,
        index_files=index_file_entries,
        project_config_hash=sha256_file(config_path),
        counts=frame.counts,
        out_of_scope_form_counts=frame.out_of_scope_form_counts,
        reconciliation=frame.reconciliation,
        output_hashes=output_hashes,
        limitations=limitations,
        code_revision=_git_revision(root),
    )
    result.manifest_path = write_json(run_dir / "filer_frame_manifest.json", manifest)
    result.run_dir = run_dir
    return result


def build_frame_manifest(
    *,
    repo_root: str | Path,
    run_id: str,
    frame_version: str,
    parameters: FrameParameters,
    index_files: list[dict],
    project_config_hash: str,
    counts: dict[str, int],
    out_of_scope_form_counts: dict[str, int],
    reconciliation: dict[str, bool],
    output_hashes: dict[str, str],
    limitations: list[str],
    code_revision: str | None,
) -> dict:
    """Assemble and schema-validate the immutable frame run manifest."""
    root = Path(repo_root)
    schema_versions = read_json(root / "schemas" / "schema_version_manifest.json")[
        "schemas"
    ]
    manifest = {
        "run_id": run_id,
        "frame_version": frame_version,
        "filing_window_start": str(parameters.filing_window_start),
        "filing_window_end": str(parameters.filing_window_end),
        "domestic_forms": list(parameters.domestic_forms),
        "extension_forms": list(parameters.extension_forms),
        "amendment_candidate_rule": AMENDMENT_CANDIDATE_RULE,
        "index_files": index_files,
        "project_config_hash": project_config_hash,
        "code_revision": code_revision,
        "universe_code_version": UNIVERSE_CODE_VERSION,
        "counts": counts,
        "out_of_scope_form_counts": out_of_scope_form_counts,
        "reconciliation": reconciliation,
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "schema_versions": {
            "filer_frame_manifest": schema_versions["filer_frame_manifest"]
        },
        "limitations": limitations,
        "output_hashes": output_hashes,
    }
    schema = read_json(root / FRAME_MANIFEST_SCHEMA_RELATIVE_PATH)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(manifest), key=lambda e: e.json_path)
    if errors:
        details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
        raise ValueError(f"Frame manifest violates the canonical schema: {details}")
    return manifest


def _git_revision(repo_root: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root, capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
