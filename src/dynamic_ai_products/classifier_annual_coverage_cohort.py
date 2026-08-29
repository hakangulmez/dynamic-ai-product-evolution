"""Annual filing-year coverage: a later restriction, never an earlier screen (ADR-138).

The high-recall screen, the human-review overlay and the classifier candidate cohort
are finished and immutable. This module does not touch any of them. It reads the
4,045-row candidate cohort and the FRAME annual-filer inventory and answers one
mechanical question per firm: did it file an annual report in every calendar filing
year the analysis window requires?

**Order matters and is stated, not implied.** This filter runs *after* the historical
high-recall invocation, not before it. Every firm here was screened, and the screen's
verdict is carried through unchanged. Describing the result as though the coverage
rule had scoped the screen would misdescribe both: the screen saw 4,045 firms and
this restriction sees the same 4,045, keeping some.

**It is an analysis-eligibility cohort, not a universe.** Nothing here is a software
judgement. A firm is kept because a panel needs an observation in each year, and
dropped because it does not have one. The classifier has not run, no tier exists, and
membership in the software universe is not decided by this or any part of it.

**The selection it induces is a survivor sample, and that is a real limitation.**
Requiring a filing in every year from 2022 through 2025 keeps continuing reporters and
drops firms that were acquired, went private, deregistered, delisted or failed inside
the window, and firms that first registered after it began. Any estimate computed on
this cohort is conditional on surviving as a reporting registrant. The manifest says so
in its own bytes rather than leaving it for a reader to notice.

**No row is discarded.** Every excluded firm is written to its own immutable artifact
with the years it did file and the required years it did not, so the drop is auditable
and reversible by reading rather than by re-running anything.

**Two annual-filer inputs, because two forms are annual reports.** Domestic annual
filings (10-K, 10-KT) and the foreign-private-issuer extension forms (20-F, 40-F) are
separate FRAME outputs and both are annual coverage. Reading only the domestic file
would drop foreign private issuers for filing the form their regime requires, which is
a data-plumbing artifact and not a fact about the firm. Both files are hash-bound by
the same FRAME manifest and both are pinned here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .classifier_candidate_cohort import (
    COHORT_MANIFEST_FILENAME,
    COHORT_RECORDS_FILENAME,
    require_classifier_candidate_cohort,
)
from .provenance import WriteOnceError, write_bytes_once
from .universe.lineage_screen import (
    ScreenInputError,
    _decode_utf8,
    _load_schema,
    _sha256,
    _validate,
)

__all__ = [
    "COVERAGE_EXCLUSIONS_FILENAME",
    "COVERAGE_MANIFEST_CONTRACT",
    "COVERAGE_MANIFEST_FILENAME",
    "COVERAGE_RECORDS_FILENAME",
    "COVERAGE_RULE_ID",
    "EXCLUSION_CONTRACT",
    "FRAME_ANNUAL_FILENAMES",
    "FRAME_MANIFEST_FILENAME",
    "OPTIONAL_FILING_YEAR",
    "RECORD_CONTRACT",
    "REQUIRED_FILING_YEARS",
    "AnnualCoverageCohortResult",
    "build_annual_coverage_cohort",
    "require_annual_coverage_cohort",
]

COVERAGE_RECORDS_FILENAME = "universe_annual_coverage_cohort_records.jsonl"
COVERAGE_EXCLUSIONS_FILENAME = "universe_annual_coverage_cohort_exclusions.jsonl"
COVERAGE_MANIFEST_FILENAME = "universe_annual_coverage_cohort_manifest.json"

RECORD_CONTRACT = "universe_annual_coverage_cohort_record@0.1.0"
EXCLUSION_CONTRACT = "universe_annual_coverage_cohort_exclusion@0.1.0"
COVERAGE_MANIFEST_CONTRACT = "universe_annual_coverage_cohort_manifest@0.1.0"

RECORD_SCHEMA = "schemas/universe_annual_coverage_cohort_record.v1.schema.json"
EXCLUSION_SCHEMA = "schemas/universe_annual_coverage_cohort_exclusion.v1.schema.json"
COVERAGE_MANIFEST_SCHEMA = (
    "schemas/universe_annual_coverage_cohort_manifest.v1.schema.json")

COHORT_KIND = "annual_coverage_cohort_v1"
RECORD_ORDER = "candidate_cohort_row_order"
COVERAGE_RULE_ID = "annual_filing_year_continuity_2022_2025@1"

#: Every calendar filing year in which an annual filing is required. A firm missing
#: any one of these is excluded.
REQUIRED_FILING_YEARS: tuple[int, ...] = (2022, 2023, 2024, 2025)

#: Recorded when present and never required. 2021 is the pre-period year: a firm that
#: has it supports a longer panel, and a firm that does not is still eligible.
OPTIONAL_FILING_YEAR = 2021

#: No filing after 2025 bears on eligibility. Later years are counted for the record
#: and are never a condition, so a firm is not penalised for the window's right edge.
LAST_ELIGIBILITY_YEAR = max(REQUIRED_FILING_YEARS)

FRAME_MANIFEST_FILENAME = "filer_frame_manifest.json"

#: Both FRAME annual-filer outputs. Domestic annual reports and the FPI extension
#: forms are the same kind of coverage evidence and both are read.
FRAME_ANNUAL_FILENAMES: tuple[str, ...] = (
    "historical_annual_filers.jsonl",
    "fpi_extension_filers.jsonl",
)


@dataclass(frozen=True)
class AnnualCoverageCohortResult:
    cohort_dir: Path | None
    manifest_path: Path | None
    manifest: dict
    records: list[dict]
    exclusions: list[dict]


def _pin(path: Path, expected: str, *, filename: str, what: str) -> tuple[dict, bytes]:
    if path.name != filename:
        raise ScreenInputError(
            f"The {what} manifest must be {filename}; {path.name} is a different "
            "artifact.")
    if not path.is_file():
        raise ScreenInputError(f"{what} manifest not found: {path}")
    raw = path.read_bytes()
    observed = _sha256(raw)
    if observed != expected:
        raise ScreenInputError(
            f"The {what} manifest hashes to {observed}, but {expected} was pinned; "
            "this is not the artifact that was named.")
    return json.loads(_decode_utf8(raw, filename)), raw


def _read_recorded(directory: Path, filename: str, recorded: str) -> bytes:
    path = directory / filename
    if not path.is_file():
        raise ScreenInputError(f"Pinned input not found: {path}")
    raw = path.read_bytes()
    if _sha256(raw) != recorded:
        raise ScreenInputError(
            f"{filename} no longer hashes to the digest its manifest records; "
            "nothing may be read from it.")
    return raw


def _filing_year(row: dict, filename: str) -> int:
    """The calendar year the filing was filed in, from FRAME's own filing_date."""
    value = row.get("filing_date")
    if not isinstance(value, str) or len(value) < 4 or not value[:4].isdigit():
        raise ScreenInputError(
            f"{filename} carries a row with no usable filing_date; coverage cannot "
            "be derived from it.")
    return int(value[:4])


def annual_filing_years(frame_dir: Path, manifest: dict) -> dict[str, set[int]]:
    """Map every CIK to the calendar years it filed an annual report in.

    Both annual-filer outputs are read and merged. A firm filing 10-K in some years
    and 20-F in others has continuous coverage, and splitting the two files would
    manufacture a gap that the filings do not contain.
    """
    years: dict[str, set[int]] = {}
    for filename in FRAME_ANNUAL_FILENAMES:
        recorded = manifest.get("output_hashes", {}).get(filename)
        if not isinstance(recorded, str):
            raise ScreenInputError(
                f"The FRAME manifest records no output hash for {filename}; the "
                "annual-filer inventory it describes is not consumable.")
        raw = _read_recorded(frame_dir, filename, recorded)
        for line in _decode_utf8(raw, filename).splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            years.setdefault(row["cik"], set()).add(_filing_year(row, filename))
    return years


def classify_coverage(observed: set[int]) -> tuple[bool, list[int], str]:
    """Decide one firm from its observed filing years alone.

    Returns whether it is eligible, the required years it is missing, and which
    coverage class it falls in. Pure and total: the same set always gives the same
    answer, and no year after :data:`LAST_ELIGIBILITY_YEAR` can change it.
    """
    missing = sorted(y for y in REQUIRED_FILING_YEARS if y not in observed)
    if missing:
        return False, missing, "excluded_missing_required_year"
    if OPTIONAL_FILING_YEAR in observed:
        return True, [], "complete_2021_2025"
    return True, [], "2021_missing_2022_2025_present"


def build_annual_coverage_cohort(
    *, repo_root: str | Path, cohort_manifest_path: str | Path,
    cohort_manifest_sha256: str, frame_manifest_path: str | Path,
    frame_manifest_sha256: str, output_dir: str | Path, coverage_cohort_id: str,
    clock: Callable[[], datetime], dry_run: bool = False,
) -> AnnualCoverageCohortResult:
    """Derive and write one annual-coverage cohort, write-once. No model call."""
    root = Path(repo_root)
    cohort_path = Path(cohort_manifest_path)
    cohort, cohort_manifest_raw = _pin(
        cohort_path, cohort_manifest_sha256, filename=COHORT_MANIFEST_FILENAME,
        what="candidate cohort")
    require_classifier_candidate_cohort(cohort_path.parent)
    records_raw = _read_recorded(
        cohort_path.parent, COHORT_RECORDS_FILENAME,
        cohort["output_hashes"][COHORT_RECORDS_FILENAME])
    source_rows = [json.loads(x) for x
                   in _decode_utf8(records_raw, COHORT_RECORDS_FILENAME).splitlines()
                   if x.strip()]
    if len(source_rows) != cohort["counts"]["cohort_rows"]:
        raise ScreenInputError(
            "The candidate cohort's record count disagrees with its manifest.")
    if len({(r["cik"], r["accession"]) for r in source_rows}) != len(source_rows):
        raise ScreenInputError("The candidate cohort carries a row identity twice.")

    frame_path = Path(frame_manifest_path)
    frame, frame_manifest_raw = _pin(
        frame_path, frame_manifest_sha256, filename=FRAME_MANIFEST_FILENAME,
        what="FRAME")
    years_by_cik = annual_filing_years(frame_path.parent, frame)

    records: list[dict] = []
    exclusions: list[dict] = []
    for row in source_rows:
        observed = sorted(years_by_cik.get(row["cik"], set()))
        eligible, missing, coverage_class = classify_coverage(set(observed))
        # The screen's own verdict and provenance travel unchanged. This filter
        # observes filing dates and has no opinion about either.
        identity = {
            "cik": row["cik"], "accession": row["accession"],
            "company_id": row["company_id"], "source_id": row["source_id"],
            "form": row["form"],
            "baseline_filing_date": row["baseline_filing_date"],
            "packet_sha256": row["packet_sha256"],
            "admission_origin": row["admission_origin"],
            "screen_status": row["screen_status"],
            "admission_provenance": dict(row["admission_provenance"]),
            "observed_annual_filing_years": observed,
        }
        if eligible:
            records.append({
                "record_contract": RECORD_CONTRACT, **identity,
                "coverage_class": coverage_class,
                "required_filing_years": list(REQUIRED_FILING_YEARS),
                "has_optional_2021": OPTIONAL_FILING_YEAR in observed})
        else:
            exclusions.append({
                "record_contract": EXCLUSION_CONTRACT, **identity,
                "exclusion_reason_code": coverage_class,
                "required_filing_years": list(REQUIRED_FILING_YEARS),
                "missing_required_filing_years": missing})
    if len(records) + len(exclusions) != len(source_rows):
        raise ScreenInputError(
            "The kept and dropped rows do not partition the source cohort; a row "
            "would have been silently discarded.")

    complete = sum(r["coverage_class"] == "complete_2021_2025" for r in records)
    without_2021 = sum(
        r["coverage_class"] == "2021_missing_2022_2025_present" for r in records)
    counts = {
        "source_cohort_rows": len(source_rows),
        "included": len(records),
        "excluded": len(exclusions),
        "complete_2021_2025": complete,
        "2021_missing_2022_2025_present": without_2021,
        "by_admission_origin": {
            origin: sum(r["admission_origin"] == origin for r in records)
            for origin in ("model_screen", "human_review")},
        "by_screen_status": {
            status: sum(r["screen_status"] == status for r in records)
            for status in ("LIKELY_ELIGIBLE", "BOUNDARY_OR_UNCERTAIN")},
        "excluded_by_missing_year": {
            str(year): sum(year in e["missing_required_filing_years"]
                           for e in exclusions)
            for year in REQUIRED_FILING_YEARS},
        "excluded_by_missing_year_count": {
            str(n): sum(len(e["missing_required_filing_years"]) == n
                        for e in exclusions)
            for n in range(1, len(REQUIRED_FILING_YEARS) + 1)},
    }
    records_bytes = "".join(
        json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n"
        for r in records).encode("utf-8")
    exclusions_bytes = "".join(
        json.dumps(e, sort_keys=True, separators=(",", ":")) + "\n"
        for e in exclusions).encode("utf-8")

    reconciliation = {
        "every source row is kept or dropped, and none is discarded": (
            len(records) + len(exclusions) == len(source_rows)),
        "the two outputs share no row identity": not (
            {(r["cik"], r["accession"]) for r in records}
            & {(e["cik"], e["accession"]) for e in exclusions}),
        "the coverage classes sum to the included population": (
            complete + without_2021 == len(records)),
        "every included row has every required year": all(
            set(REQUIRED_FILING_YEARS) <= set(r["observed_annual_filing_years"])
            for r in records),
        "every excluded row names at least one missing required year": all(
            e["missing_required_filing_years"]
            and set(e["missing_required_filing_years"]) <= set(REQUIRED_FILING_YEARS)
            for e in exclusions),
        "no missing year is one the rule never required": all(
            year in REQUIRED_FILING_YEARS
            for e in exclusions for year in e["missing_required_filing_years"]),
        "2021 decided nothing": all(
            OPTIONAL_FILING_YEAR not in e["missing_required_filing_years"]
            for e in exclusions),
        "no year after the last required one decided anything": all(
            classify_coverage(set(r["observed_annual_filing_years"]))[0]
            == classify_coverage({y for y in r["observed_annual_filing_years"]
                                  if y <= LAST_ELIGIBILITY_YEAR})[0]
            for r in records + exclusions),
        "records follow the source cohort's own row order": (
            [(r["cik"], r["accession"]) for r in records]
            == [(r["cik"], r["accession"]) for r in source_rows
                if (r["cik"], r["accession"])
                in {(x["cik"], x["accession"]) for x in records}]),
        "every row keeps the screen verdict it arrived with": all(
            r["screen_status"] in ("LIKELY_ELIGIBLE", "BOUNDARY_OR_UNCERTAIN")
            and r["admission_origin"] in ("model_screen", "human_review")
            for r in records + exclusions),
        "the source cohort and frame inputs are the pinned ones": (
            _sha256(cohort_manifest_raw) == cohort_manifest_sha256
            and _sha256(frame_manifest_raw) == frame_manifest_sha256),
    }
    if not all(reconciliation.values()):
        failed = sorted(k for k, v in reconciliation.items() if not v)
        raise ScreenInputError(
            f"Annual-coverage reconciliation failed; nothing is written. Failed "
            f"identities: {failed}.")

    manifest = {
        "manifest_contract": COVERAGE_MANIFEST_CONTRACT,
        "coverage_cohort_id": coverage_cohort_id,
        "cohort_kind": COHORT_KIND,
        "artifact_role": "analysis_eligibility_cohort",
        "no_model_call": True,
        "is_software_universe": False,
        "is_classifier_output": False,
        "applied_after_high_recall_screen": True,
        "coverage_rule": {
            "rule_id": COVERAGE_RULE_ID,
            "required_filing_years": list(REQUIRED_FILING_YEARS),
            "optional_filing_year": OPTIONAL_FILING_YEAR,
            "last_eligibility_year": LAST_ELIGIBILITY_YEAR,
            "filing_year_basis": "calendar year of the SEC filing date",
            "annual_forms_read": sorted(FRAME_ANNUAL_FILENAMES),
        },
        "sources": {
            "candidate_cohort": {
                "cohort_id": cohort["cohort_id"],
                "manifest_sha256": cohort_manifest_sha256,
                "records_jsonl_sha256": _sha256(records_raw),
                "cohort_rows": len(source_rows)},
            "frame": {
                "run_id": frame["run_id"],
                "manifest_sha256": frame_manifest_sha256,
                "annual_filer_jsonl_sha256": {
                    name: frame["output_hashes"][name]
                    for name in FRAME_ANNUAL_FILENAMES},
                "filing_window_start": frame["filing_window_start"],
                "filing_window_end": frame["filing_window_end"]},
            "sources_unmodified": True},
        "output_contract": RECORD_CONTRACT,
        "exclusion_contract": EXCLUSION_CONTRACT,
        "record_order": RECORD_ORDER,
        "output_hashes": {
            COVERAGE_RECORDS_FILENAME: _sha256(records_bytes),
            COVERAGE_EXCLUSIONS_FILENAME: _sha256(exclusions_bytes)},
        "counts": counts,
        "reconciliation": reconciliation,
        "schema_versions": {
            "universe_annual_coverage_cohort_record":
                RECORD_CONTRACT.rsplit("@", 1)[1],
            "universe_annual_coverage_cohort_exclusion":
                EXCLUSION_CONTRACT.rsplit("@", 1)[1],
            "universe_annual_coverage_cohort_manifest":
                COVERAGE_MANIFEST_CONTRACT.rsplit("@", 1)[1]},
        "run_timestamp": clock().isoformat(),
        "limitations": [
            "This is an analysis-eligibility cohort. It is not a software universe, "
            "not a classifier result, and it settles no firm's membership in any "
            "universe. No model was called and no judgement about any firm's "
            "business was made or revised here.",
            "It is a restriction applied AFTER the historical high-recall screen, "
            "the human-review overlay and the candidate cohort, all of which are "
            "byte-unchanged. It did not scope the screen and must not be described "
            "as though it had: the screen saw every one of these firms.",
            "Requiring an annual filing in each of 2022, 2023, 2024 and 2025 selects "
            "a survivor / continuing-reporter sample. Firms acquired, taken private, "
            "deregistered, delisted or failed inside the window are dropped, as are "
            "firms that first began filing after it opened. Any estimate computed on "
            "this cohort is conditional on surviving as a reporting registrant, and "
            "that conditioning is not ignorable for questions about entry, exit or "
            "firm survival.",
            "A 2021 filing is recorded and never required, so the cohort mixes firms "
            "with a five-year panel and firms with a four-year one. The two are "
            "labelled and must not be pooled where the pre-period year matters.",
            "Coverage is counted by calendar filing year, not fiscal year. A firm "
            "whose fiscal year end moves can file twice in one calendar year and not "
            "at all in the next; such a firm is excluded by this rule even though its "
            "fiscal-year coverage is continuous.",
            "Every excluded firm is retained in the exclusions artifact with the "
            "years it filed and the required years it did not. Nothing is discarded, "
            "and the drop can be audited by reading rather than by re-running.",
        ],
    }
    _validate(manifest, _load_schema(root, COVERAGE_MANIFEST_SCHEMA),
              "Annual coverage cohort manifest")
    record_schema = _load_schema(root, RECORD_SCHEMA)
    exclusion_schema = _load_schema(root, EXCLUSION_SCHEMA)
    for record in records:
        _validate(record, record_schema, "Annual coverage cohort record")
    for exclusion in exclusions:
        _validate(exclusion, exclusion_schema, "Annual coverage cohort exclusion")

    if dry_run:
        return AnnualCoverageCohortResult(
            cohort_dir=None, manifest_path=None, manifest=manifest,
            records=records, exclusions=exclusions)

    cohort_dir = Path(output_dir) / coverage_cohort_id
    cohort_dir.mkdir(parents=True, exist_ok=True)
    try:
        write_bytes_once(cohort_dir / COVERAGE_RECORDS_FILENAME, records_bytes,
                         what="annual coverage cohort records")
        write_bytes_once(cohort_dir / COVERAGE_EXCLUSIONS_FILENAME, exclusions_bytes,
                         what="annual coverage cohort exclusions")
        write_bytes_once(
            cohort_dir / COVERAGE_MANIFEST_FILENAME,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            what="annual coverage cohort manifest")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    return AnnualCoverageCohortResult(
        cohort_dir=cohort_dir, manifest_path=cohort_dir / COVERAGE_MANIFEST_FILENAME,
        manifest=manifest, records=records, exclusions=exclusions)


def require_annual_coverage_cohort(cohort_dir: str | Path) -> Path:
    """Refuse any coverage cohort that is not complete and self-consistent."""
    directory = Path(cohort_dir)
    manifest_path = directory / COVERAGE_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ScreenInputError(
            f"Directory {directory} holds no {COVERAGE_MANIFEST_FILENAME}; this "
            "loader consumes annual coverage cohorts only.")
    manifest: dict[str, Any] = json.loads(
        _decode_utf8(manifest_path.read_bytes(), COVERAGE_MANIFEST_FILENAME))
    if manifest.get("manifest_contract") != COVERAGE_MANIFEST_CONTRACT:
        raise ScreenInputError(
            f"{directory} declares {manifest.get('manifest_contract')!r}; this "
            f"loader consumes {COVERAGE_MANIFEST_CONTRACT!r} only.")
    for filename, recorded in manifest["output_hashes"].items():
        target = directory / filename
        if not target.is_file() or _sha256(target.read_bytes()) != recorded:
            raise ScreenInputError(
                f"Annual coverage output {filename} is missing or no longer hashes "
                "to its manifest entry.")
    return manifest_path
