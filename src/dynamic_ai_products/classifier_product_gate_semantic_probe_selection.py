"""Write-once selection for the 23-filing product-gate semantic probe."""

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
    "SEMANTIC_PROBE_ROW_CAP",
    "SEMANTIC_PROBE_ROWS",
    "SEMANTIC_PROBE_SELECTION_CONTRACT",
    "SEMANTIC_PROBE_SELECTION_FILENAME",
    "SEMANTIC_PROBE_SELECTION_KIND",
    "SEMANTIC_PROBE_SELECTION_SCHEMA",
    "build_product_gate_semantic_probe_selection",
    "require_product_gate_semantic_probe_selection",
]

SEMANTIC_PROBE_ROW_CAP = 23
SEMANTIC_PROBE_SELECTION_FILENAME = (
    "universe_classifier_product_gate_semantic_probe_selection.json")
SEMANTIC_PROBE_SELECTION_CONTRACT = (
    "universe_classifier_product_gate_semantic_probe_selection@0.1.0")
SEMANTIC_PROBE_SELECTION_KIND = "classifier_product_gate_semantic_probe_v1"
SEMANTIC_PROBE_SELECTION_SCHEMA = (
    "schemas/universe_classifier_product_gate_semantic_probe_selection.v1.schema.json")

# The exact V9 YES decisions that the first 100-row semantic audit identified as
# boundary or likely-overbroad. Their old decisions never reach a rendered prompt.
SEMANTIC_PROBE_ROWS: tuple[tuple[str, str], ...] = (
    ("0000004457", "0000004457-22-000041"),  # U-Haul
    ("0000006281", "0000006281-22-000250"),  # Analog Devices
    ("0000006951", "0000006951-21-000043"),  # Applied Materials
    ("0000008858", "0000008858-22-000031"),  # Avnet
    ("0000012208", "0000012208-22-000011"),  # Bio-Rad
    ("0000012927", "0000012927-22-000010"),  # Boeing
    ("0000014930", "0000014930-22-000041"),  # Brunswick
    ("0000018230", "0000018230-22-000050"),  # Caterpillar
    ("0000020212", "0000020212-22-000056"),  # Churchill Downs
    ("0000022701", "0000022701-22-000004"),  # managed services
    ("0000027996", "0000027996-22-000078"),  # Deluxe
    ("0000030697", "0000030697-22-000003"),  # Wendy's
    ("0000034782", "0000034782-22-000038"),  # 1st Source
    ("0000037785", "0000037785-22-000025"),  # FMC
    ("0000039899", "0000039899-22-000012"),  # TEGNA
    ("0000040533", "0000040533-22-000007"),  # General Dynamics
    ("0000040729", "0000040729-22-000007"),  # Ally
    ("0000045012", "0000045012-22-000013"),  # Halliburton
    ("0000046080", "0000046080-22-000023"),  # Hasbro
    ("0000046765", "0000046765-22-000070"),  # Helmerich & Payne
    ("0000049196", "0000049196-22-000023"),  # Huntington
    ("0000051644", "0000051644-22-000010"),  # Interpublic
    ("0000062709", "0000062709-22-000009"),  # Marsh McLennan
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


def build_product_gate_semantic_probe_selection(
    *, repo_root: str | Path, cohort_manifest_path: str | Path,
    cohort_manifest_sha256: str, coverage_manifest_path: str | Path,
    coverage_manifest_sha256: str, packet_manifest_path: str | Path,
    output_path: str | Path, selection_id: str, clock: Callable[[], datetime],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Select the fixed 23 exact filings from one pinned coverage cohort."""
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
    missing = [key for key in SEMANTIC_PROBE_ROWS if key not in by_key]
    if missing:
        raise ScreenInputError(f"Semantic-probe filings are absent from the coverage cohort: {missing}.")
    rows = [{field: (
        dict(by_key[key][field]) if field == "admission_provenance"
        else list(by_key[key][field]) if field == "observed_annual_filing_years"
        else by_key[key][field]
    ) for field in _ROW_FIELDS} for key in SEMANTIC_PROBE_ROWS]

    packets = load_packet_run(root, packet_manifest_path)
    by_packet_key = {(packet["cik"], packet["accession"]): packet for packet in packets.packets}
    for row in rows:
        packet = by_packet_key.get((row["cik"], row["accession"]))
        if packet is None or packet["packet_sha256"] != row["packet_sha256"]:
            raise ScreenInputError("Semantic-probe selection row does not resolve to its pinned packet.")

    selection = {
        "selection_contract": SEMANTIC_PROBE_SELECTION_CONTRACT,
        "selection_id": selection_id,
        "selection_kind": SEMANTIC_PROBE_SELECTION_KIND,
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
            "This fixed 23-filing probe tests one general purchase-object instruction and is not a sample or a software-universe result.",
            "The prior classifications selected these filings for audit only and reach no rendered model prompt.",
        ],
        "run_timestamp": clock().isoformat(),
    }
    _validate(selection, _load_schema(root, SEMANTIC_PROBE_SELECTION_SCHEMA),
              "Product-gate semantic probe selection")
    if dry_run:
        return selection
    try:
        write_bytes_once(
            Path(output_path),
            (json.dumps(selection, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            what="product-gate semantic probe selection")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    return selection


def require_product_gate_semantic_probe_selection(
    path: str | Path, *, expected_sha256: str, repo_root: str | Path,
) -> dict[str, Any]:
    target = Path(path)
    if target.name != SEMANTIC_PROBE_SELECTION_FILENAME:
        raise ScreenInputError("A product-gate semantic-probe selection has the wrong filename.")
    raw = _read_pinned(target, expected_sha256, "Product-gate semantic probe selection")
    selection = json.loads(_decode_utf8(raw, SEMANTIC_PROBE_SELECTION_FILENAME))
    if selection.get("selection_contract") != SEMANTIC_PROBE_SELECTION_CONTRACT:
        raise ScreenInputError("The selection declares a different contract.")
    _validate(selection, _load_schema(Path(repo_root), SEMANTIC_PROBE_SELECTION_SCHEMA),
              "Product-gate semantic probe selection")
    if len(selection["rows"]) != SEMANTIC_PROBE_ROW_CAP:
        raise ScreenInputError("The product-gate semantic probe must contain exactly 23 filings.")
    if [(row["cik"], row["accession"]) for row in selection["rows"]] != list(SEMANTIC_PROBE_ROWS):
        raise ScreenInputError("The semantic probe names a different filing set or order.")
    return selection
