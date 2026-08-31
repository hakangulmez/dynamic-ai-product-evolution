"""Write-once selection for the five-filing software-product wording probe."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .classifier_annual_coverage_cohort import (
    COVERAGE_MANIFEST_FILENAME,
    COVERAGE_RECORDS_FILENAME,
    require_annual_coverage_cohort,
)
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
    load_packet_run,
)

__all__ = [
    "PROBE_ROW_CAP",
    "PROBE_ROWS",
    "PROBE_SELECTION_CONTRACT",
    "PROBE_SELECTION_FILENAME",
    "PROBE_SELECTION_KIND",
    "PROBE_SELECTION_SCHEMA",
    "build_product_gate_probe_selection",
    "require_product_gate_probe_selection",
]

PROBE_ROW_CAP = 5
PROBE_SELECTION_FILENAME = "universe_classifier_product_gate_probe_selection.json"
PROBE_SELECTION_CONTRACT = "universe_classifier_product_gate_probe_selection@0.1.0"
PROBE_SELECTION_KIND = "classifier_product_gate_probe_v1"
PROBE_SELECTION_SCHEMA = "schemas/universe_classifier_product_gate_probe_selection.v1.schema.json"

# These are the five CORE rows from the completed V7 100-row gate, selected for
# a wording-only diagnostic. The selection is audit context and never reaches a
# rendered prompt.
PROBE_ROWS: tuple[tuple[str, str], ...] = (
    ("0000004962", "0000004962-22-000008"),
    ("0000008670", "0000008670-22-000038"),
    ("0000032604", "0000032604-22-000041"),
    ("0000033185", "0000033185-22-000014"),
    ("0000040729", "0000040729-22-000007"),
)

_ROW_FIELDS = (
    "cik", "accession", "company_id", "source_id", "packet_sha256",
    "admission_origin", "screen_status", "admission_provenance",
    "coverage_class", "observed_annual_filing_years",
)


def _read_pinned(path: Path, expected: str, what: str) -> bytes:
    if not path.is_file():
        raise ScreenInputError(f"{what} not found: {path}")
    raw = path.read_bytes()
    if _sha256(raw) != expected:
        raise ScreenInputError(f"{what} no longer hashes to its pinned digest.")
    return raw


def build_product_gate_probe_selection(
    *, repo_root: str | Path, cohort_manifest_path: str | Path,
    cohort_manifest_sha256: str, coverage_manifest_path: str | Path,
    coverage_manifest_sha256: str, packet_manifest_path: str | Path,
    output_path: str | Path, selection_id: str, clock: Callable[[], datetime],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Select the fixed five exact filings from a pinned coverage cohort."""
    root = Path(repo_root)
    cohort_path = Path(cohort_manifest_path)
    if cohort_path.name != COHORT_MANIFEST_FILENAME:
        raise ScreenInputError("The candidate cohort manifest has the wrong filename.")
    cohort_raw = _read_pinned(cohort_path, cohort_manifest_sha256, "Candidate cohort manifest")
    require_classifier_candidate_cohort(cohort_path.parent)
    cohort = json.loads(_decode_utf8(cohort_raw, COHORT_MANIFEST_FILENAME))
    cohort_records = _read_pinned(
        cohort_path.parent / COHORT_RECORDS_FILENAME,
        cohort["output_hashes"][COHORT_RECORDS_FILENAME], "Candidate cohort records")

    coverage_path = Path(coverage_manifest_path)
    if coverage_path.name != COVERAGE_MANIFEST_FILENAME:
        raise ScreenInputError("The annual coverage manifest has the wrong filename.")
    coverage_raw = _read_pinned(coverage_path, coverage_manifest_sha256, "Annual coverage manifest")
    require_annual_coverage_cohort(coverage_path.parent)
    coverage = json.loads(_decode_utf8(coverage_raw, COVERAGE_MANIFEST_FILENAME))
    source = coverage["sources"]["candidate_cohort"]
    if (source["cohort_id"] != cohort["cohort_id"]
            or source["manifest_sha256"] != cohort_manifest_sha256
            or source["records_jsonl_sha256"] != _sha256(cohort_records)):
        raise ScreenInputError("Annual coverage and candidate cohort do not bind the same bytes.")
    coverage_records = _read_pinned(
        coverage_path.parent / COVERAGE_RECORDS_FILENAME,
        coverage["output_hashes"][COVERAGE_RECORDS_FILENAME], "Annual coverage records")
    by_key = {(row["cik"], row["accession"]): row for row in (
        json.loads(line) for line in _decode_utf8(
            coverage_records, COVERAGE_RECORDS_FILENAME).splitlines() if line.strip())}
    if len(by_key) != coverage["counts"]["included"]:
        raise ScreenInputError("Annual coverage records contain a duplicate or wrong row count.")
    missing = [key for key in PROBE_ROWS if key not in by_key]
    if missing:
        raise ScreenInputError(f"Probe filings are absent from the annual coverage cohort: {missing}.")
    rows = [{field: (
        dict(by_key[key][field]) if field == "admission_provenance"
        else list(by_key[key][field]) if field == "observed_annual_filing_years"
        else by_key[key][field]
    ) for field in _ROW_FIELDS} for key in PROBE_ROWS]

    packets = load_packet_run(root, packet_manifest_path)
    for row in rows:
        packet = {(p["cik"], p["accession"]): p for p in packets.packets}.get(
            (row["cik"], row["accession"]))
        if packet is None or packet["packet_sha256"] != row["packet_sha256"]:
            raise ScreenInputError("Probe selection row does not resolve to its pinned packet.")

    selection = {
        "selection_contract": PROBE_SELECTION_CONTRACT,
        "selection_id": selection_id,
        "selection_kind": PROBE_SELECTION_KIND,
        "candidate_cohort_id": cohort["cohort_id"],
        "candidate_cohort_manifest_sha256": cohort_manifest_sha256,
        "coverage_cohort_id": coverage["coverage_cohort_id"],
        "coverage_cohort_manifest_sha256": coverage_manifest_sha256,
        "coverage_cohort_records_sha256": _sha256(coverage_records),
        "packet_manifest_sha256": packets.manifest_sha256,
        "rows": rows,
        "counts": {"selected_rows": len(rows)},
        "no_model_call": True,
        "limitations": [
            "This fixed five-filing probe tests one wording change and is not a sample or a software-universe result.",
            "Prior gate outcomes selected these filings for audit only and reach no rendered model prompt.",
        ],
        "run_timestamp": clock().isoformat(),
    }
    _validate(selection, _load_schema(root, PROBE_SELECTION_SCHEMA), "Product-gate probe selection")
    if dry_run:
        return selection
    try:
        write_bytes_once(
            Path(output_path),
            (json.dumps(selection, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            what="product-gate probe selection")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    return selection


def require_product_gate_probe_selection(
    path: str | Path, *, expected_sha256: str, repo_root: str | Path,
) -> dict[str, Any]:
    target = Path(path)
    if target.name != PROBE_SELECTION_FILENAME:
        raise ScreenInputError("A product-gate probe selection has the wrong filename.")
    raw = _read_pinned(target, expected_sha256, "Product-gate probe selection")
    selection = json.loads(_decode_utf8(raw, PROBE_SELECTION_FILENAME))
    if selection.get("selection_contract") != PROBE_SELECTION_CONTRACT:
        raise ScreenInputError("The selection declares a different contract.")
    _validate(selection, _load_schema(Path(repo_root), PROBE_SELECTION_SCHEMA), "Product-gate probe selection")
    if len(selection["rows"]) != PROBE_ROW_CAP:
        raise ScreenInputError("The product-gate probe must contain exactly five filings.")
    if [(row["cik"], row["accession"]) for row in selection["rows"]] != list(PROBE_ROWS):
        raise ScreenInputError("The product-gate probe names a different filing set or order.")
    return selection
