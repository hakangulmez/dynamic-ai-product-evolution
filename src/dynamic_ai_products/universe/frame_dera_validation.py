"""DERA FSDS validation of a FRAME run (independent validation, never source).

Governing documents:
- docs/THESIS_EXECUTION_PLAN.md (W1: DERA FSDS is an independent validation
  source only, never the frame source)
- docs/DECISION_LOG.md ADR-080 (filer-accession grain), ADR-081 (this design)

Compares a completed FRAME run against locally supplied DERA Financial
Statement Data Set ``SUB``-level files at filer-accession ``(CIK, accession)``
grain. DERA never feeds the frame and never filters the universe: this module
reads the frame run read-only (verifying every frame artifact against its
manifest ``output_hashes`` first) and writes only its own validation artifact.

Construct rules, fixed by ADR-081:

- ``aciks`` follows the official FSDS contract: space-delimited additional
  registrant CIKs, optionally ending in a terminal ``PARTIAL`` token. PARTIAL
  is valid input, never a parse failure; every declared pair is retained and
  compared; omitted CIKs are never inferred; comparisons touching a PARTIAL
  submission are marked and can never gate or become a contradiction.
- Absence from DERA is expected FSDS/XBRL non-coverage, reported (total and
  per base form), never a FRAME error, never gated. Equality is not the gate.
- ``observed_through`` is a declared input, never inferred: an absent frame
  record filed after it is ``right_boundary_unobserved`` — a possible
  post-cutoff DERA release omission is never misreported as non-coverage.
- The amendment stratum reconciles and is fully reported but is report-only:
  it cannot fail the annual gate.
- Form and filed-date identity comparison is literal and fail-closed; no
  timing-rollover exception exists unless a real DERA canary supplies the
  evidence for one.

The gate (``frame_dera_validation_gate_v1``) fails closed on: any
``dera_only_unexplained`` annual pair; any annual ``identity_mismatch``; any
annual non-PARTIAL registrant-set contradiction
(``frame_filer_not_in_dera_registrants`` or ``dera_registrant_not_in_frame``
— only the partial/truncated unresolved class is non-gating); any DERA
parse failure (a malformed row must never yield a passing validation merely
because it was excluded); any broken reconciliation identity; or zero annual
matches when both comparable populations are nonempty.

ADR-085 refinements, each measured on the real full-window validation:

- ``nciks`` must be a positive integer. On non-PARTIAL rows, a count below
  1 + declared additional CIKs is a fatal parse failure, while a count
  above it is the measured FSDS ``aciks`` field-width truncation —
  valid, marked ``registrant_set_truncated``, handled like PARTIAL
  (declared pairs compared, omissions never inferred, non-gating). PARTIAL
  rows still require ``nciks`` strictly above the declared count.
- Filed-date drift with matching CIK, accession, and form is the report-only
  ``filed_date_drift`` category when DERA is later by at most
  ``FILED_DATE_DRIFT_BOUND_DAYS`` (the EDGAR next-business-day signature);
  DERA-earlier drift, drift beyond the bound, and any form mismatch remain
  gating identity mismatches.
- Contradictions carrying concrete evidence — a replaced submission with
  its replacement accession and backdating, or a deleted submission
  (present in point-in-time FSDS, absent from the current-regeneration
  index, no replacement anywhere; ADR-086) — are reclassified as non-gating
  adjudicated categories via the committed, append-only, hash-recorded
  ``configs/dera_validation_adjudications.json``; unadjudicated
  contradictions still gate.

This module performs no network access and calls no model.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from jsonschema import Draft202012Validator
from pydantic import Field

from ..provenance import write_bytes_once
from .freeze import create_run_directory
from .identifiers import IdentifierError, normalize_accession, normalize_cik
from .io_utils import read_json, read_jsonl, sha256_file
from .models import StrictModel

ANNUAL_BASE_FORMS = ("10-K", "10-KT", "20-F", "40-F")
PARTIAL_TOKEN = "PARTIAL"
GATE_RULE_ID = "frame_dera_validation_gate_v1"
# ADR-085 decision B: filed-date drift with matching CIK, accession, and
# form is report-only when DERA is later by at most this many days (the
# measured EDGAR next-business-day signature: +1 weekday, +3 over a
# weekend). DERA-earlier drift and anything beyond the bound remain gating
# identity mismatches. Recorded in every validation manifest's counts.
FILED_DATE_DRIFT_BOUND_DAYS = 3
# ADR-085 decision C: committed, append-only, evidence-backed adjudications
# of replaced-submission contradictions. Fixed path; hash recorded in the
# manifest samples. Unadjudicated contradictions still gate.
ADJUDICATIONS_RELATIVE_PATH = Path("configs/dera_validation_adjudications.json")
ADJUDICATIONS_CONTRACT = "dera_validation_adjudications@0.1.0"
VALIDATION_MANIFEST_FILENAME = "frame_dera_validation_manifest.json"
VALIDATION_MANIFEST_SCHEMA_RELATIVE_PATH = Path(
    "schemas/frame_dera_validation_manifest.schema.json"
)
FRAME_MANIFEST_SCHEMA_RELATIVE_PATH = Path(
    "schemas/filer_frame_manifest.schema.json"
)
DERA_FIXTURE_MANIFEST_FILENAME = "fixture_manifest.json"
DERA_REQUIRED_COLUMNS = ("adsh", "cik", "name", "form", "filed", "nciks", "aciks")
SAMPLE_LIMIT = 10

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class DeraInputError(ValueError):
    """The DERA bundle, frame reference, or parameters are invalid."""


class DeraSubParseFailure(StrictModel):
    """One SUB data line that could not become a submission row."""

    source_file: str
    source_line: int
    reason_code: Literal[
        "wrong_field_count",
        "empty_field",
        "invalid_accession",
        "invalid_cik",
        "invalid_date",
        "invalid_nciks",
        "malformed_aciks",
        "invalid_aciks_cik",
        "nciks_inconsistent",
        "conflicting_duplicate_submission",
    ]
    detail: str


class DeraSubmission(StrictModel):
    """One validated FSDS SUB row (fields needed for validation only)."""

    adsh: str
    cik: str
    name: str
    form: str
    filed: date
    nciks: int
    additional_ciks: list[str] = Field(default_factory=list)
    registrant_set_partial: bool = False
    # ADR-085 decision A: nciks above the declared count without a PARTIAL
    # token is the measured FSDS aciks field-width truncation — valid,
    # marked, non-gating, omissions never inferred.
    registrant_set_truncated: bool = False
    source_file: str
    source_line: int

    def registrant_pairs(self) -> list[tuple[str, str, str]]:
        """Declared (cik, adsh, role) pairs; PARTIAL never infers more."""
        pairs = [(self.cik, self.adsh, "primary")]
        pairs.extend((a, self.adsh, "co_registrant") for a in self.additional_ciks)
        return pairs


@dataclass
class ParsedSubFile:
    source_name: str
    rows: list[DeraSubmission]
    parse_failures: list[DeraSubParseFailure]
    data_rows: int


@dataclass
class DeraValidationResult:
    run_id: str
    run_dir: Path | None
    dry_run: bool
    gate_status: str
    failed_conditions: list[str]
    counts: dict[str, int]
    noncoverage_by_form: dict[str, dict]
    reconciliation: dict[str, bool]
    manifest_path: Path | None = None


def parse_sub_file(text: str, *, source_name: str) -> ParsedSubFile:
    """Parse one FSDS SUB TSV by header-name lookup.

    Requires the validation columns by name and ignores every other column,
    so real full-width ``sub.txt`` files parse unchanged.
    """
    lines = [line for line in text.splitlines()]
    header_line = next((l for l in lines if l.strip()), None)
    if header_line is None:
        raise DeraInputError(f"{source_name}: empty SUB file.")
    header = header_line.split("\t")
    missing = [c for c in DERA_REQUIRED_COLUMNS if c not in header]
    if missing:
        raise DeraInputError(
            f"{source_name}: SUB header is missing required columns: {missing}."
        )
    index_of = {c: header.index(c) for c in DERA_REQUIRED_COLUMNS}
    width = len(header)
    header_at = lines.index(header_line)

    rows: list[DeraSubmission] = []
    failures: list[DeraSubParseFailure] = []
    data_rows = 0
    for line_number, raw in enumerate(lines[header_at + 1 :], start=header_at + 2):
        if not raw.strip():
            continue
        data_rows += 1

        def failure(reason: str, detail: str) -> None:
            failures.append(
                DeraSubParseFailure(
                    source_file=source_name,
                    source_line=line_number,
                    reason_code=reason,  # type: ignore[arg-type]
                    detail=detail,
                )
            )

        fields = raw.split("\t")
        if len(fields) != width:
            failure(
                "wrong_field_count",
                f"expected {width} fields, got {len(fields)}",
            )
            continue
        adsh_raw = fields[index_of["adsh"]].strip()
        cik_raw = fields[index_of["cik"]].strip()
        form = fields[index_of["form"]].strip()
        filed_raw = fields[index_of["filed"]].strip()
        nciks_raw = fields[index_of["nciks"]].strip()
        aciks_raw = fields[index_of["aciks"]].strip()
        name = fields[index_of["name"]].strip()
        if not adsh_raw or not cik_raw or not form or not filed_raw:
            failure("empty_field", "adsh, cik, form, and filed are required")
            continue
        try:
            adsh = normalize_accession(adsh_raw)
        except IdentifierError as exc:
            failure("invalid_accession", str(exc))
            continue
        try:
            cik = normalize_cik(cik_raw)
        except IdentifierError as exc:
            failure("invalid_cik", str(exc))
            continue
        try:
            filed = datetime.strptime(filed_raw, "%Y%m%d").date()
        except ValueError:
            failure("invalid_date", f"filed {filed_raw!r} is not YYYYMMDD")
            continue
        try:
            nciks = int(nciks_raw)
        except ValueError:
            failure("invalid_nciks", f"nciks {nciks_raw!r} is not an integer")
            continue
        if nciks < 1:
            failure(
                "invalid_nciks",
                f"nciks must be a positive integer, got {nciks}",
            )
            continue

        tokens = aciks_raw.split() if aciks_raw else []
        partial = bool(tokens) and tokens[-1] == PARTIAL_TOKEN
        if partial:
            tokens = tokens[:-1]
        if PARTIAL_TOKEN in tokens:
            failure(
                "malformed_aciks",
                "PARTIAL is only valid as the terminal aciks token",
            )
            continue
        try:
            additional = [normalize_cik(t) for t in tokens]
        except IdentifierError as exc:
            failure("invalid_aciks_cik", str(exc))
            continue
        declared = 1 + len(additional)
        truncated = False
        if not partial:
            if nciks < declared:
                failure(
                    "nciks_inconsistent",
                    f"nciks={nciks} below 1 + additional CIKs = {declared}",
                )
                continue
            # nciks above the declared count without PARTIAL: the measured
            # FSDS aciks field-width truncation (ADR-085 decision A) —
            # valid, marked; genuinely impossible counts stay fatal above.
            truncated = nciks > declared
        elif nciks <= declared:
            failure(
                "nciks_inconsistent",
                f"PARTIAL declares at least one omitted co-registrant, so "
                f"nciks must exceed 1 + additional CIKs; nciks={nciks}, "
                f"declared={declared}",
            )
            continue
        rows.append(
            DeraSubmission(
                adsh=adsh,
                cik=cik,
                name=name,
                form=form,
                filed=filed,
                nciks=nciks,
                additional_ciks=additional,
                registrant_set_partial=partial,
                registrant_set_truncated=truncated,
                source_file=source_name,
                source_line=line_number,
            )
        )
    return ParsedSubFile(
        source_name=source_name,
        rows=rows,
        parse_failures=failures,
        data_rows=data_rows,
    )


def _sample(entries: list[dict]) -> list[dict]:
    return entries[:SAMPLE_LIMIT]


def load_adjudications(repo_root: Path) -> tuple[dict, str, int]:
    """Load the committed adjudication file; fail closed on any malformation.

    Returns a lookup keyed by (direction, cik, accession), the file's
    SHA-256, and the record count. Only exactly-matching contradictions are
    reclassified; everything else still gates (ADR-085 decisions C/D).
    """
    path = repo_root / ADJUDICATIONS_RELATIVE_PATH
    if not path.is_file():
        raise DeraInputError(f"Adjudication file not found: {path}")
    payload = read_json(path)
    if not isinstance(payload, dict) or payload.get(
        "adjudications_contract"
    ) != ADJUDICATIONS_CONTRACT:
        raise DeraInputError(
            f"Adjudication file must declare {ADJUDICATIONS_CONTRACT!r}."
        )
    required = {
        "cik", "accession_number", "direction", "reason",
        "replacement_accession", "backdating_evidence", "adr_reference",
        "evidence_note",
    }
    lookup: dict[tuple[str, str, str], dict] = {}
    records = payload.get("records")
    if not isinstance(records, list):
        raise DeraInputError("Adjudication records must be a list.")
    for index, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != required:
            raise DeraInputError(
                f"Adjudication record {index} must have exactly the keys "
                f"{sorted(required)}."
            )
        if record["direction"] not in ("dera_only", "filed_date"):
            raise DeraInputError(
                f"Adjudication record {index}: unknown direction "
                f"{record['direction']!r}."
            )
        if record["reason"] not in ("replaced_submission", "deleted_submission"):
            raise DeraInputError(
                f"Adjudication record {index}: only replaced_submission and "
                "deleted_submission are admitted reasons (ADR-085/ADR-086)."
            )
        replacement = record["replacement_accession"]
        if record["reason"] == "replaced_submission":
            # A replacement claim requires a concrete, normalizable accession.
            if not isinstance(replacement, str):
                raise DeraInputError(
                    f"Adjudication record {index}: replaced_submission "
                    "requires a non-null replacement_accession."
                )
            try:
                normalize_accession(replacement)
            except IdentifierError as exc:
                raise DeraInputError(
                    f"Adjudication record {index}: {exc}"
                ) from exc
        elif replacement is not None:
            # An evidenced deletion has, by definition, no replacement.
            raise DeraInputError(
                f"Adjudication record {index}: deleted_submission requires "
                "replacement_accession null."
            )
        try:
            cik = normalize_cik(record["cik"])
            accession = normalize_accession(record["accession_number"])
        except IdentifierError as exc:
            raise DeraInputError(
                f"Adjudication record {index}: {exc}"
            ) from exc
        key = (record["direction"], cik, accession)
        if key in lookup:
            raise DeraInputError(
                f"Adjudication record {index}: duplicate key {key}."
            )
        lookup[key] = record
    return lookup, sha256_file(path), len(records)


def _frame_record_key(record: dict) -> tuple[str, str]:
    return (record["cik"], record["accession_number"])


def run_dera_validation(
    *,
    repo_root: str | Path,
    frame_manifest_path: str | Path,
    dera_dir: str | Path,
    output_dir: str | Path,
    run_id: str,
    clock=None,
    dry_run: bool = False,
) -> DeraValidationResult:
    """Validate a completed FRAME run against local DERA SUB files."""
    root = Path(repo_root)
    now = clock or (lambda: datetime.now(timezone.utc))
    if not _RUN_ID_RE.match(run_id):
        raise DeraInputError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )

    # --- frame side: schema-validate the manifest, verify every artifact ---
    frame_manifest_file = Path(frame_manifest_path)
    if not frame_manifest_file.is_file():
        raise DeraInputError(f"Frame manifest not found: {frame_manifest_file}")
    frame_manifest = read_json(frame_manifest_file)
    frame_schema = read_json(root / FRAME_MANIFEST_SCHEMA_RELATIVE_PATH)
    errors = sorted(
        Draft202012Validator(frame_schema).iter_errors(frame_manifest),
        key=lambda e: e.json_path,
    )
    if errors:
        details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
        raise DeraInputError(
            f"Frame manifest violates its canonical schema: {details}"
        )
    frame_run_dir = frame_manifest_file.parent
    for filename, expected in frame_manifest["output_hashes"].items():
        artifact = frame_run_dir / filename
        if not artifact.is_file():
            raise DeraInputError(f"Frame artifact missing: {artifact}")
        observed = sha256_file(artifact)
        if observed != expected:
            raise DeraInputError(
                f"Frame artifact hash mismatch for {filename}: manifest "
                f"{expected}, observed {observed}. Refusing to validate."
            )
    window_start = date.fromisoformat(frame_manifest["filing_window_start"])
    window_end = date.fromisoformat(frame_manifest["filing_window_end"])
    domestic_forms = set(frame_manifest["domestic_forms"])
    extension_forms = set(frame_manifest["extension_forms"])
    annual_forms = domestic_forms | extension_forms

    adjudications, adjudications_sha256, adjudication_records = (
        load_adjudications(root)
    )
    applied_adjudications: list[dict] = []

    annual_records = [
        r
        for name in ("historical_annual_filers.jsonl", "fpi_extension_filers.jsonl")
        for r in read_jsonl(frame_run_dir / name)
    ]
    amendment_records = read_jsonl(frame_run_dir / "amendment_links.jsonl")
    integrity_accessions = {
        g["accession_number"]
        for g in read_jsonl(frame_run_dir / "frame_integrity_failures.jsonl")
    }

    # --- DERA side: bundle manifest, parse, dedupe ------------------------
    dera_path = Path(dera_dir)
    if not dera_path.is_dir():
        raise DeraInputError(f"DERA input directory not found: {dera_path}")
    bundle_manifest_path = dera_path / DERA_FIXTURE_MANIFEST_FILENAME
    if not bundle_manifest_path.is_file():
        raise DeraInputError(
            f"DERA bundle is missing {DERA_FIXTURE_MANIFEST_FILENAME}."
        )
    bundle = read_json(bundle_manifest_path)
    required_keys = {"description", "observed_through", "loaded_releases", "sub_files"}
    missing_keys = required_keys - set(bundle)
    if missing_keys:
        raise DeraInputError(
            f"{DERA_FIXTURE_MANIFEST_FILENAME} is missing keys: "
            f"{sorted(missing_keys)}"
        )
    observed_through = date.fromisoformat(str(bundle["observed_through"]))
    listed = sorted(str(n) for n in bundle["sub_files"])
    present = sorted(p.name for p in dera_path.glob("*.tsv"))
    if listed != present:
        raise DeraInputError(
            "DERA sub_files and on-disk *.tsv files disagree: "
            f"listed={listed}, present={present}"
        )
    parsed_files: list[ParsedSubFile] = []
    input_entries: list[dict] = []
    for name in listed:
        path = dera_path / name
        parsed = parse_sub_file(path.read_text(encoding="utf-8"), source_name=name)
        parsed_files.append(parsed)
        input_entries.append(
            {
                "filename": name,
                "sha256": sha256_file(path),
                "data_rows": parsed.data_rows,
                "parse_failures": len(parsed.parse_failures),
            }
        )
    parse_failures = [f for p in parsed_files for f in p.parse_failures]
    all_rows = [r for p in parsed_files for r in p.rows]

    by_adsh: dict[str, list[DeraSubmission]] = {}
    for row in all_rows:
        by_adsh.setdefault(row.adsh, []).append(row)
    unique_submissions: list[DeraSubmission] = []
    duplicate_rows = 0
    conflicting_rows = 0
    for adsh in sorted(by_adsh):
        group = by_adsh[adsh]
        content = {
            (r.cik, r.form, str(r.filed), r.nciks,
             tuple(r.additional_ciks), r.registrant_set_partial,
             r.registrant_set_truncated)
            for r in group
        }
        if len(content) > 1:
            conflicting_rows += len(group)
            for r in group:
                parse_failures.append(
                    DeraSubParseFailure(
                        source_file=r.source_file,
                        source_line=r.source_line,
                        reason_code="conflicting_duplicate_submission",
                        detail=f"adsh {adsh} carries conflicting rows",
                    )
                )
            continue
        unique_submissions.append(group[0])
        duplicate_rows += len(group) - 1

    # --- DERA scope split (window first, then form; mirrors the frame) ----
    def base_form(form: str) -> str | None:
        if form in annual_forms:
            return form
        if form.endswith("/A") and form[:-2] in annual_forms:
            return form[:-2]
        return None

    dera_annual: list[DeraSubmission] = []
    dera_amendment: list[DeraSubmission] = []
    dera_out_of_window = 0
    dera_out_of_scope_form = 0
    for sub in unique_submissions:
        if not window_start <= sub.filed <= window_end:
            dera_out_of_window += 1
        elif sub.form in annual_forms:
            dera_annual.append(sub)
        elif base_form(sub.form) is not None:
            dera_amendment.append(sub)
        else:
            dera_out_of_scope_form += 1

    def classify_stratum(
        frame_side: list[dict],
        dera_side: list[DeraSubmission],
        *,
        accession_field: str,
        form_field: str,
        date_field: str,
        stratum: str,
    ) -> dict:
        pair_to_sub: dict[tuple[str, str], tuple[DeraSubmission, str]] = {}
        adsh_to_subs: dict[str, list[DeraSubmission]] = {}
        expanded_pairs = 0
        for sub in dera_side:
            adsh_to_subs.setdefault(sub.adsh, []).append(sub)
            for cik, adsh, role in sub.registrant_pairs():
                expanded_pairs += 1
                pair_to_sub[(cik, adsh)] = (sub, role)

        cat: dict[str, list[dict]] = {
            "matched": [], "identity_mismatch": [], "filed_date_drift": [],
            "identity_adjudicated": [], "noncoverage": [],
            "right_boundary_unobserved": [],
            "unresolved_partial_registrant_set": [],
            "frame_filer_not_in_dera_registrants": [],
        }
        matched_pairs: set[tuple[str, str]] = set()
        matched_under_partial = 0
        matched_under_truncated = 0
        for record in frame_side:
            key = (record["cik"], record[accession_field])
            entry = {
                "cik": key[0],
                "accession_number": key[1],
                "form": record[form_field],
                "filed": str(record[date_field]),
            }
            hit = pair_to_sub.get(key)
            if hit is not None:
                sub, role = hit
                mismatches = []
                if record[form_field] != sub.form:
                    mismatches.append(
                        f"form: frame={record[form_field]!r} dera={sub.form!r}"
                    )
                if str(record[date_field]) != str(sub.filed):
                    mismatches.append(
                        f"filed: frame={record[date_field]} dera={sub.filed}"
                    )
                if mismatches:
                    form_matches = record[form_field] == sub.form
                    drift_days = (
                        (sub.filed - date.fromisoformat(str(record[date_field]))).days
                        if form_matches
                        else None
                    )
                    adjudication = adjudications.get(
                        ("filed_date", key[0], key[1])
                    )
                    if (
                        form_matches
                        and drift_days is not None
                        and 0 < drift_days <= FILED_DATE_DRIFT_BOUND_DAYS
                    ):
                        # ADR-085 decision B: bounded DERA-later drift is
                        # report-only; anything else stays gating.
                        cat["filed_date_drift"].append(
                            {**entry, "drift_days": drift_days,
                             "dera_filed": str(sub.filed)}
                        )
                    elif form_matches and adjudication is not None:
                        cat["identity_adjudicated"].append(
                            {**entry, "mismatches": mismatches,
                             "reason": adjudication["reason"],
                             "adr_reference": adjudication["adr_reference"]}
                        )
                        applied_adjudications.append(
                            {**adjudication, "stratum": stratum}
                        )
                    else:
                        cat["identity_mismatch"].append(
                            {**entry, "mismatches": mismatches}
                        )
                else:
                    matched_pairs.add(key)
                    if sub.registrant_set_partial:
                        matched_under_partial += 1
                    if sub.registrant_set_truncated:
                        matched_under_truncated += 1
                    cat["matched"].append(
                        {**entry, "role": role,
                         "dera_registrant_set_partial": sub.registrant_set_partial,
                         "dera_registrant_set_truncated": sub.registrant_set_truncated}
                    )
                continue
            subs_for_adsh = adsh_to_subs.get(key[1])
            if subs_for_adsh:
                # ADR-085 decision A: truncated sets are handled like PARTIAL
                # — the unlisted filer is unresolved, marked, non-gating.
                if any(
                    s.registrant_set_partial or s.registrant_set_truncated
                    for s in subs_for_adsh
                ):
                    cat["unresolved_partial_registrant_set"].append(entry)
                else:
                    cat["frame_filer_not_in_dera_registrants"].append(entry)
                continue
            filed = date.fromisoformat(str(record[date_field]))
            if filed > observed_through:
                cat["right_boundary_unobserved"].append(entry)
            else:
                cat["noncoverage"].append(entry)

        dera_only_unexplained: list[dict] = []
        dera_only_integrity_excluded: list[dict] = []
        dera_only_adjudicated: list[dict] = []
        dera_registrant_not_in_frame: list[dict] = []
        dera_matched = 0
        frame_keys = {(r["cik"], r[accession_field]) for r in frame_side}
        frame_adshs = {r[accession_field] for r in frame_side}
        for sub in dera_side:
            for cik, adsh, role in sub.registrant_pairs():
                entry = {
                    "cik": cik, "accession_number": adsh, "form": sub.form,
                    "filed": str(sub.filed), "role": role,
                    "dera_registrant_set_partial": sub.registrant_set_partial,
                }
                if (cik, adsh) in matched_pairs:
                    dera_matched += 1
                elif (cik, adsh) in frame_keys:
                    pass  # drift/adjudicated/mismatch, counted frame-side
                elif adsh in frame_adshs:
                    dera_registrant_not_in_frame.append(entry)
                elif adsh in integrity_accessions:
                    dera_only_integrity_excluded.append(entry)
                else:
                    adjudication = adjudications.get(("dera_only", cik, adsh))
                    if adjudication is not None:
                        dera_only_adjudicated.append(
                            {**entry, "reason": adjudication["reason"],
                             "adr_reference": adjudication["adr_reference"]}
                        )
                        applied_adjudications.append(
                            {**adjudication, "stratum": stratum}
                        )
                    else:
                        dera_only_unexplained.append(entry)
        frame_side_divergent = (
            len(cat["identity_mismatch"])
            + len(cat["filed_date_drift"])
            + len(cat["identity_adjudicated"])
        )
        return {
            "categories": cat,
            "matched_under_partial": matched_under_partial,
            "matched_under_truncated": matched_under_truncated,
            "expanded_pairs": expanded_pairs,
            "dera_matched": dera_matched,
            "dera_divergent_pairs": frame_side_divergent,
            "dera_only_unexplained": dera_only_unexplained,
            "dera_only_integrity_excluded": dera_only_integrity_excluded,
            "dera_only_adjudicated": dera_only_adjudicated,
            "dera_registrant_not_in_frame": dera_registrant_not_in_frame,
        }

    annual = classify_stratum(
        annual_records, dera_annual,
        accession_field="accession_number", form_field="form",
        date_field="filing_date", stratum="annual",
    )
    amendment = classify_stratum(
        amendment_records, dera_amendment,
        accession_field="amendment_accession", form_field="amendment_form",
        date_field="amendment_filing_date", stratum="amendment",
    )

    # --- noncoverage table: total and per base form (annual stratum) -------
    def form_table(records: list[dict], cats: dict) -> dict:
        keys_of = lambda entries: {(e["cik"], e["accession_number"]) for e in entries}  # noqa: E731
        matched_k = keys_of(cats["matched"])
        noncov_k = keys_of(cats["noncoverage"])
        boundary_k = keys_of(cats["right_boundary_unobserved"])
        partial_k = keys_of(cats["unresolved_partial_registrant_set"])
        table: dict[str, dict] = {}
        for scope in (*ANNUAL_BASE_FORMS, "total"):
            subset = [
                r for r in records
                if scope == "total" or r["form"] == scope
            ]
            keys = {(r["cik"], r["accession_number"]) for r in subset}
            n_boundary = len(keys & boundary_k)
            n_partial = len(keys & partial_k)
            observable = len(keys) - n_boundary - n_partial
            n_noncov = len(keys & noncov_k)
            table[scope] = {
                "records": len(keys),
                "observable_records": observable,
                "matched": len(keys & matched_k),
                "noncoverage": n_noncov,
                "noncoverage_rate": (
                    round(n_noncov / observable, 6) if observable else None
                ),
                "right_boundary_unobserved": n_boundary,
                "unresolved_partial_registrant_set": n_partial,
            }
        return table

    noncoverage_by_form = form_table(annual_records, annual["categories"])

    counts = {
        "dera_input_files": len(parsed_files),
        "dera_data_rows": sum(p.data_rows for p in parsed_files),
        "dera_parse_failures": len(parse_failures),
        "dera_duplicate_rows": duplicate_rows,
        "dera_conflicting_rows": conflicting_rows,
        "dera_unique_submissions": len(unique_submissions),
        "dera_out_of_window": dera_out_of_window,
        "dera_out_of_scope_form": dera_out_of_scope_form,
        "dera_annual_submissions": len(dera_annual),
        "dera_amendment_submissions": len(dera_amendment),
        "dera_registrant_set_truncated_submissions": sum(
            1 for s in unique_submissions if s.registrant_set_truncated
        ),
        "filed_date_drift_bound_days": FILED_DATE_DRIFT_BOUND_DAYS,
        "adjudication_records": adjudication_records,
        "adjudications_applied": len(applied_adjudications),
        "annual_frame_records": len(annual_records),
        "annual_matched": len(annual["categories"]["matched"]),
        "annual_matched_under_partial": annual["matched_under_partial"],
        "annual_matched_under_truncated": annual["matched_under_truncated"],
        "annual_identity_mismatch": len(annual["categories"]["identity_mismatch"]),
        "annual_filed_date_drift": len(annual["categories"]["filed_date_drift"]),
        "annual_identity_adjudicated": len(
            annual["categories"]["identity_adjudicated"]
        ),
        "annual_dera_only_adjudicated": len(annual["dera_only_adjudicated"]),
        "annual_noncoverage": len(annual["categories"]["noncoverage"]),
        "annual_right_boundary_unobserved": len(
            annual["categories"]["right_boundary_unobserved"]
        ),
        "annual_unresolved_partial_registrant_set": len(
            annual["categories"]["unresolved_partial_registrant_set"]
        ),
        "annual_frame_filer_not_in_dera_registrants": len(
            annual["categories"]["frame_filer_not_in_dera_registrants"]
        ),
        "annual_dera_expanded_pairs": annual["expanded_pairs"],
        "annual_dera_matched_pairs": annual["dera_matched"],
        "annual_dera_only_unexplained": len(annual["dera_only_unexplained"]),
        "annual_dera_only_integrity_excluded": len(
            annual["dera_only_integrity_excluded"]
        ),
        "annual_dera_registrant_not_in_frame": len(
            annual["dera_registrant_not_in_frame"]
        ),
        "amendment_frame_links": len(amendment_records),
        "amendment_matched": len(amendment["categories"]["matched"]),
        "amendment_matched_under_truncated": amendment["matched_under_truncated"],
        "amendment_identity_mismatch": len(
            amendment["categories"]["identity_mismatch"]
        ),
        "amendment_filed_date_drift": len(
            amendment["categories"]["filed_date_drift"]
        ),
        "amendment_identity_adjudicated": len(
            amendment["categories"]["identity_adjudicated"]
        ),
        "amendment_dera_only_adjudicated": len(
            amendment["dera_only_adjudicated"]
        ),
        "amendment_noncoverage": len(amendment["categories"]["noncoverage"]),
        "amendment_right_boundary_unobserved": len(
            amendment["categories"]["right_boundary_unobserved"]
        ),
        "amendment_unresolved_partial_registrant_set": len(
            amendment["categories"]["unresolved_partial_registrant_set"]
        ),
        "amendment_frame_filer_not_in_dera_registrants": len(
            amendment["categories"]["frame_filer_not_in_dera_registrants"]
        ),
        "amendment_dera_expanded_pairs": amendment["expanded_pairs"],
        "amendment_dera_matched_pairs": amendment["dera_matched"],
        "amendment_dera_only_unexplained": len(amendment["dera_only_unexplained"]),
        "amendment_dera_only_integrity_excluded": len(
            amendment["dera_only_integrity_excluded"]
        ),
        "amendment_dera_registrant_not_in_frame": len(
            amendment["dera_registrant_not_in_frame"]
        ),
    }

    parsed_rows_total = counts["dera_data_rows"] - sum(
        1 for f in parse_failures
        if f.reason_code != "conflicting_duplicate_submission"
    )
    reconciliation = {
        "dera: parsed rows = unique + duplicate + conflicting":
            parsed_rows_total
            == counts["dera_unique_submissions"]
            + counts["dera_duplicate_rows"]
            + counts["dera_conflicting_rows"],
        "dera: unique = annual + amendment + out_of_scope_form + out_of_window":
            counts["dera_unique_submissions"]
            == counts["dera_annual_submissions"]
            + counts["dera_amendment_submissions"]
            + counts["dera_out_of_scope_form"]
            + counts["dera_out_of_window"],
        "annual: frame records = matched + mismatch + drift + adjudicated"
        " + noncoverage + boundary + unresolved_partial + not_in_registrants":
            counts["annual_frame_records"]
            == counts["annual_matched"]
            + counts["annual_identity_mismatch"]
            + counts["annual_filed_date_drift"]
            + counts["annual_identity_adjudicated"]
            + counts["annual_noncoverage"]
            + counts["annual_right_boundary_unobserved"]
            + counts["annual_unresolved_partial_registrant_set"]
            + counts["annual_frame_filer_not_in_dera_registrants"],
        "annual: dera pairs = matched + divergent + registrant_disagreement"
        " + only_explained + only_adjudicated + only_unexplained":
            counts["annual_dera_expanded_pairs"]
            == counts["annual_dera_matched_pairs"]
            + annual["dera_divergent_pairs"]
            + counts["annual_dera_registrant_not_in_frame"]
            + counts["annual_dera_only_integrity_excluded"]
            + counts["annual_dera_only_adjudicated"]
            + counts["annual_dera_only_unexplained"],
        "amendment: frame links = matched + mismatch + drift + adjudicated"
        " + noncoverage + boundary + unresolved_partial + not_in_registrants":
            counts["amendment_frame_links"]
            == counts["amendment_matched"]
            + counts["amendment_identity_mismatch"]
            + counts["amendment_filed_date_drift"]
            + counts["amendment_identity_adjudicated"]
            + counts["amendment_noncoverage"]
            + counts["amendment_right_boundary_unobserved"]
            + counts["amendment_unresolved_partial_registrant_set"]
            + counts["amendment_frame_filer_not_in_dera_registrants"],
        "amendment: dera pairs = matched + divergent + registrant_disagreement"
        " + only_explained + only_adjudicated + only_unexplained":
            counts["amendment_dera_expanded_pairs"]
            == counts["amendment_dera_matched_pairs"]
            + amendment["dera_divergent_pairs"]
            + counts["amendment_dera_registrant_not_in_frame"]
            + counts["amendment_dera_only_integrity_excluded"]
            + counts["amendment_dera_only_adjudicated"]
            + counts["amendment_dera_only_unexplained"],
    }

    # --- gate: annual stratum only; equality is never the gate -------------
    failed_conditions: list[str] = []
    if counts["annual_dera_only_unexplained"] > 0:
        failed_conditions.append("annual_dera_only_unexplained > 0")
    if counts["annual_identity_mismatch"] > 0:
        failed_conditions.append("annual_identity_mismatch > 0")
    # Non-PARTIAL registrant-set contradictions gate; only the explicitly
    # PARTIAL unresolved class is non-gating.
    if counts["annual_frame_filer_not_in_dera_registrants"] > 0:
        failed_conditions.append("annual_frame_filer_not_in_dera_registrants > 0")
    if counts["annual_dera_registrant_not_in_frame"] > 0:
        failed_conditions.append("annual_dera_registrant_not_in_frame > 0")
    # A malformed or inconsistent DERA row must never yield a passing
    # validation merely because it was excluded from comparison.
    if counts["dera_parse_failures"] > 0:
        failed_conditions.append("dera_parse_failures > 0")
    broken = [name for name, holds in reconciliation.items() if not holds]
    failed_conditions.extend(f"reconciliation broken: {b}" for b in broken)
    if (
        counts["annual_frame_records"] > 0
        and counts["dera_annual_submissions"] > 0
        and counts["annual_matched"] == 0
    ):
        failed_conditions.append(
            "zero annual matches with both comparable populations nonempty"
        )
    gate_status = "fail" if failed_conditions else "pass"

    result = DeraValidationResult(
        run_id=run_id,
        run_dir=None,
        dry_run=dry_run,
        gate_status=gate_status,
        failed_conditions=failed_conditions,
        counts=counts,
        noncoverage_by_form=noncoverage_by_form,
        reconciliation=reconciliation,
    )
    if dry_run:
        return result

    samples = {
        f"annual_{name}": _sample(entries)
        for name, entries in annual["categories"].items()
    }
    samples["annual_dera_only_unexplained"] = _sample(
        annual["dera_only_unexplained"]
    )
    samples["annual_dera_only_adjudicated"] = _sample(
        annual["dera_only_adjudicated"]
    )
    samples["annual_dera_registrant_not_in_frame"] = _sample(
        annual["dera_registrant_not_in_frame"]
    )
    samples["adjudications_file"] = [
        {
            "path": str(ADJUDICATIONS_RELATIVE_PATH),
            "sha256": adjudications_sha256,
            "records": adjudication_records,
            "applied": len(applied_adjudications),
        }
    ]
    samples["adjudications_applied"] = _sample(applied_adjudications)
    samples.update(
        {
            f"amendment_{name}": _sample(entries)
            for name, entries in amendment["categories"].items()
        }
    )
    samples["amendment_dera_only_unexplained"] = _sample(
        amendment["dera_only_unexplained"]
    )
    samples["dera_parse_failures"] = _sample(
        [f.model_dump(mode="json") for f in parse_failures]
    )

    schema_versions = read_json(root / "schemas" / "schema_version_manifest.json")[
        "schemas"
    ]
    manifest = {
        "run_id": run_id,
        "frame_manifest_sha256": sha256_file(frame_manifest_file),
        "frame_run_dir": str(frame_run_dir),
        "frame_version": frame_manifest["frame_version"],
        "filing_window_start": str(window_start),
        "filing_window_end": str(window_end),
        "domestic_forms": sorted(domestic_forms),
        "extension_forms": sorted(extension_forms),
        "observed_through": str(observed_through),
        "loaded_releases": [str(r) for r in bundle["loaded_releases"]],
        "dera_inputs": input_entries,
        "counts": counts,
        "noncoverage_by_form": noncoverage_by_form,
        "reconciliation": reconciliation,
        "samples": samples,
        "gate": {
            "status": gate_status,
            "rule_id": GATE_RULE_ID,
            "failed_conditions": failed_conditions,
        },
        "run_timestamp": now().isoformat(),
        "schema_versions": {
            "frame_dera_validation_manifest": schema_versions[
                "frame_dera_validation_manifest"
            ]
        },
        "limitations": [
            "DERA FSDS is an independent validation source only: it is never "
            "the FRAME denominator and never a universe eligibility or "
            "filtering source.",
            "Absence from DERA is expected FSDS/XBRL non-coverage, reported "
            "and never gated; equality is not the gate.",
            "observed_through is a declared input; absences filed after it "
            "are right_boundary_unobserved, never non-coverage.",
            "PARTIAL registrant sets follow the official FSDS contract: "
            "declared pairs compared, omissions never inferred, affected "
            "comparisons marked and non-gating.",
            "The amendment stratum is report-only and cannot fail the gate.",
            f"Bundle: {bundle['description']}",
        ],
    }
    schema = read_json(root / VALIDATION_MANIFEST_SCHEMA_RELATIVE_PATH)
    validator = Draft202012Validator(schema)
    schema_errors = sorted(validator.iter_errors(manifest), key=lambda e: e.json_path)
    if schema_errors:
        details = "; ".join(
            f"{e.json_path}: {e.message}" for e in schema_errors[:5]
        )
        raise ValueError(
            f"Validation manifest violates the canonical schema: {details}"
        )
    run_dir = create_run_directory(output_dir, run_id)
    payload = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    manifest_path = run_dir / VALIDATION_MANIFEST_FILENAME
    write_bytes_once(manifest_path, payload, what="DERA validation manifest")
    result.run_dir = run_dir
    result.manifest_path = manifest_path
    return result
