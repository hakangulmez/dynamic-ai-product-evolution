"""Write-once annual-coverage-backed selection for the firm-level pilot.

The original pilot selection is a named subset of the forty-row calibration
selection.  This successor is intentionally not: it is a named stress set drawn
from ADR-138's completed analysis-eligibility cohort.  That distinction is an
input provenance fact, not a fact to show the model.  The model still receives
only Item 1 through the later pilot runner.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from jsonschema import Draft202012Validator, FormatChecker

from .classifier_annual_coverage_cohort import (
    COVERAGE_MANIFEST_FILENAME,
    COVERAGE_RECORDS_FILENAME,
    require_annual_coverage_cohort,
)
from .classifier_candidate_cohort import (
    COHORT_MANIFEST_FILENAME,
    require_classifier_candidate_cohort,
)
from .provenance import WriteOnceError, write_bytes_once
from .universe.lineage_screen import (
    ScreenInputError,
    _decode_utf8,
    _load_schema,
    _sha256,
    load_packet_run,
)

__all__ = [
    "PILOT_ROWS_V2",
    "PILOT_SELECTION_V2_CONTRACT",
    "PILOT_SELECTION_V2_FILENAME",
    "PILOT_SELECTION_V2_SCHEMA",
    "build_pilot_selection_v2_artifact",
    "require_pilot_selection_v2",
]

PILOT_SELECTION_V2_CONTRACT = "universe_classifier_pilot_selection@0.2.0"
PILOT_SELECTION_V2_SCHEMA = "schemas/universe_classifier_pilot_selection.v2.schema.json"
PILOT_SELECTION_V2_FILENAME = "universe_classifier_pilot_v2_selection.json"
PILOT_SELECTION_V2_KIND = "classifier_pilot_v2"
PILOT_ROW_CAP_V2 = 10

# This is a deliberately named stress set, never a random draw and never a
# model-selected population.  Every identity is asserted against the completed
# annual-coverage records before an artifact can be written.
PILOT_ROWS_V2: tuple[tuple[str, str, str], ...] = (
    ("0001441816", "0001441816-22-000059", "P1_obvious_software"),
    ("0001477333", "0001477333-22-000008", "P1_obvious_software"),
    ("0001867072", "0001558370-22-003291", "P2_model_screen_likely"),
    ("0001136893", "0001136893-22-000038", "P2_model_screen_likely"),
    ("0001405528", "0001410578-22-000214", "P3_model_screen_boundary"),
    ("0001783328", "0000950170-22-003175", "P3_model_screen_boundary"),
    ("0001056285", "0001564590-22-011815", "P5_economically_ambiguous"),
    ("0000082811", "0000082811-22-000069", "P5_economically_ambiguous"),
    ("0000096021", "0000096021-22-000151", "P5_economically_ambiguous"),
    ("0000822416", "0000822416-22-000007", "P6_clear_negative"),
)


def _validate(value: dict, schema: dict, what: str) -> None:
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value), key=str)
    if errors:
        raise ScreenInputError(f"{what} violates its contract at {errors[0].json_path}: {errors[0].message}")


def _read_hashed(path: Path, expected: str, what: str) -> bytes:
    if not path.is_file():
        raise ScreenInputError(f"{what} not found: {path}")
    raw = path.read_bytes()
    if _sha256(raw) != expected:
        raise ScreenInputError(f"{what} no longer hashes to its pinned digest; nothing runs.")
    return raw


def build_pilot_selection_v2_artifact(
    *, repo_root: str | Path, coverage_manifest_path: str | Path,
    coverage_manifest_sha256: str, candidate_cohort_manifest_path: str | Path,
    candidate_cohort_manifest_sha256: str, packet_manifest_path: str | Path,
    packet_manifest_sha256: str, output_path: str | Path,
    selection_id: str, clock: Callable[[], datetime], dry_run: bool = False,
) -> dict:
    """Build one named ten-filing selection from the completed coverage cohort."""
    root = Path(repo_root)
    coverage_path = Path(coverage_manifest_path)
    if coverage_path.name != COVERAGE_MANIFEST_FILENAME:
        raise ScreenInputError("The coverage manifest has the wrong filename.")
    coverage_raw = _read_hashed(coverage_path, coverage_manifest_sha256, "Annual coverage manifest")
    require_annual_coverage_cohort(coverage_path.parent)
    coverage = json.loads(_decode_utf8(coverage_raw, COVERAGE_MANIFEST_FILENAME))
    if not (coverage.get("no_model_call") is True
            and coverage.get("is_software_universe") is False
            and coverage.get("is_classifier_output") is False
            and coverage.get("applied_after_high_recall_screen") is True):
        raise ScreenInputError("The named coverage artifact is not the ADR-138 analysis cohort.")
    records_raw = _read_hashed(
        coverage_path.parent / COVERAGE_RECORDS_FILENAME,
        coverage["output_hashes"][COVERAGE_RECORDS_FILENAME],
        "Annual coverage records")
    coverage_rows = [json.loads(line) for line in _decode_utf8(
        records_raw, COVERAGE_RECORDS_FILENAME).splitlines() if line.strip()]
    if len(coverage_rows) != coverage["counts"]["included"]:
        raise ScreenInputError("Annual coverage records disagree with their manifest count.")

    candidate_path = Path(candidate_cohort_manifest_path)
    if candidate_path.name != COHORT_MANIFEST_FILENAME:
        raise ScreenInputError("The candidate cohort manifest has the wrong filename.")
    candidate_raw = _read_hashed(candidate_path, candidate_cohort_manifest_sha256, "Candidate cohort manifest")
    require_classifier_candidate_cohort(candidate_path.parent)
    candidate = json.loads(_decode_utf8(candidate_raw, COHORT_MANIFEST_FILENAME))
    bound_candidate = coverage["sources"]["candidate_cohort"]
    if (candidate["cohort_id"] != bound_candidate["cohort_id"]
            or candidate_cohort_manifest_sha256 != bound_candidate["manifest_sha256"]):
        raise ScreenInputError("Annual coverage was built from a different candidate cohort.")
    packets = load_packet_run(root, packet_manifest_path)
    if packets.manifest_sha256 != packet_manifest_sha256:
        raise ScreenInputError("The presented packet manifest differs from the pinned packet cohort.")
    packets_by_key = {(packet["cik"], packet["accession"]): packet
                      for packet in packets.packets}

    by_key = {(row["cik"], row["accession"]): row for row in coverage_rows}
    if len(by_key) != len(coverage_rows):
        raise ScreenInputError("Annual coverage records carry a duplicate filing identity.")
    rows: list[dict] = []
    for cik, accession, pilot_stratum in PILOT_ROWS_V2:
        row = by_key.get((cik, accession))
        if row is None:
            raise ScreenInputError(f"Named pilot filing {cik}/{accession} is absent from annual coverage.")
        if not {2022, 2023, 2024, 2025} <= set(row["observed_annual_filing_years"]):
            raise ScreenInputError(f"Named pilot filing {cik}/{accession} lacks required annual coverage.")
        packet = packets_by_key.get((cik, accession))
        if packet is None:
            raise ScreenInputError(
                f"Named pilot filing {cik}/{accession} is absent from the packet cohort.")
        if packet["packet_sha256"] != row["packet_sha256"]:
            raise ScreenInputError(
                f"Named pilot filing {cik}/{accession} no longer matches its packet digest.")
        rows.append({
            "cik": row["cik"], "accession": row["accession"],
            "company_id": row["company_id"], "source_id": row["source_id"],
            "packet_sha256": row["packet_sha256"], "pilot_stratum": pilot_stratum,
            "admission_origin": row["admission_origin"],
            "screen_status": row["screen_status"],
            "admission_provenance": dict(row["admission_provenance"]),
            "coverage_class": row["coverage_class"],
            "observed_annual_filing_years": list(row["observed_annual_filing_years"]),
        })
    if len(rows) != PILOT_ROW_CAP_V2 or len({(r["cik"], r["accession"]) for r in rows}) != len(rows):
        raise ScreenInputError("The V2 pilot must name exactly ten unique filings.")

    def counts(field: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for row in rows:
            result[row[field]] = result.get(row[field], 0) + 1
        return result

    selection = {
        "selection_contract": PILOT_SELECTION_V2_CONTRACT,
        "selection_id": selection_id,
        "selection_kind": PILOT_SELECTION_V2_KIND,
        "coverage_cohort_id": coverage["coverage_cohort_id"],
        "coverage_cohort_manifest_path": str(coverage_path),
        "coverage_cohort_manifest_sha256": coverage_manifest_sha256,
        "coverage_cohort_records_sha256": coverage["output_hashes"][COVERAGE_RECORDS_FILENAME],
        "candidate_cohort_id": candidate["cohort_id"],
        "candidate_cohort_manifest_path": str(candidate_path),
        "candidate_cohort_manifest_sha256": candidate_cohort_manifest_sha256,
        "packet_manifest_path": str(Path(packet_manifest_path)),
        "packet_manifest_sha256": packet_manifest_sha256,
        "sampling": {
            "algorithm": "named_annual_coverage_pilot_strata@1",
            "strata": [{"pilot_stratum": key, "selected": value}
                       for key, value in sorted(counts("pilot_stratum").items())]},
        "rows": rows,
        "counts": {"selected_rows": len(rows), "by_pilot_stratum": counts("pilot_stratum"),
                   "by_admission_origin": counts("admission_origin"),
                   "by_screen_status": counts("screen_status")},
        "no_model_call": True,
        "limitations": [
            "Ten firms cannot estimate a rate and this named stress set is not a random sample.",
            "The source is the ADR-138 analysis-eligibility cohort, not the older forty-row calibration selection.",
            "Annual coverage establishes panel eligibility, not software-universe membership.",
            "Admission provenance is audit-only and is never rendered to the model.",
            "This selection derives no tier and settles no membership decision.",
        ],
        "run_timestamp": clock().isoformat(),
    }
    _validate(selection, _load_schema(root, PILOT_SELECTION_V2_SCHEMA), "Pilot V2 selection")
    if dry_run:
        return selection
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(selection, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        write_bytes_once(Path(output_path), payload, what="pilot V2 selection")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    return selection


def require_pilot_selection_v2(
    path: str | Path, *, expected_sha256: str, repo_root: str | Path,
) -> dict:
    """Load only the annual-coverage-backed pilot selection contract."""
    target = Path(path)
    if target.name != PILOT_SELECTION_V2_FILENAME:
        raise ScreenInputError(f"A V2 pilot selection must be {PILOT_SELECTION_V2_FILENAME}; this is a different artifact.")
    raw = _read_hashed(target, expected_sha256, "Pilot V2 selection")
    selection = json.loads(_decode_utf8(raw, PILOT_SELECTION_V2_FILENAME))
    if selection.get("selection_contract") != PILOT_SELECTION_V2_CONTRACT:
        raise ScreenInputError("The artifact declares a different pilot selection contract.")
    _validate(selection, _load_schema(Path(repo_root), PILOT_SELECTION_V2_SCHEMA),
              "Pilot V2 selection")
    return selection
