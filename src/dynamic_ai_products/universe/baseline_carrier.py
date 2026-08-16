"""Stage 00B firm-level baseline carrier (W2-A, ADR-088).

Derives the firm-level universe carrier from a completed FRAME run: one row
per (stratum, CIK) with the firm's baseline filing selected against the
W0-frozen cutoff (``universe.baseline_cutoff`` in ``configs/project.yaml``,
ADR-077) and its cohort assignment. The frame is consumed read-only through
its manifest: the manifest is schema-validated and every output artifact
hash is verified before parsing, and the committed FRAME_v1 freeze record is
cited so the manifest records whether the consumed frame is the frozen one.

What this stage deliberately does not do:

- **No exclusions.** Every frame filer is retained. The EDGAR full index
  carries no cover-page issuer flags and no SIC, so no deterministic issuer
  exclusion is derivable here; every firm carries ``issuer_status:
  "unknown"`` with basis ``cover_page_evidence_not_yet_observed``. Real
  Stage 00B exclusions arrive with filing-document evidence in a later
  increment. ``issuer_filters`` is intentionally not imported: its decision
  model expects a ``company_id`` the frame does not carry, and this stage
  must not fabricate one.
- **No stratum merge.** Domestic and FPI-extension records are grouped
  within stratum; a CIK appearing in both strata is flagged
  ``dual_stratum``, never merged.
- **No entrant drop.** Firms whose earliest annual filing postdates the
  cutoff become ``post_baseline_entrant`` — a retained separate cohort.
- **No DERA.** DERA FSDS is a frame validation source only; nothing here
  imports a DERA module or reads a DERA-derived field.
- **No network, no model call.**
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from ..provenance import write_bytes_once
from .freeze import create_run_directory
from .io_utils import read_json, read_jsonl, sha256_bytes, sha256_file

FRAME_MANIFEST_SCHEMA_RELATIVE_PATH = Path(
    "schemas/filer_frame_manifest.schema.json"
)
CARRIER_SCHEMA_RELATIVE_PATH = Path(
    "schemas/universe_baseline_carrier_manifest.schema.json"
)
FREEZE_RECORD_RELATIVE_PATH = Path("configs/frame_v1_freeze.json")
CARRIER_MANIFEST_FILENAME = "universe_baseline_carrier_manifest.json"
CARRIER_ROWS_FILENAME = "universe_baseline_carrier.jsonl"
ISSUER_STATUS_BASIS = "cover_page_evidence_not_yet_observed"
SAMPLE_CAP = 5

_STRATA = (
    ("domestic", "historical_annual_filers.jsonl"),
    ("fpi_extension", "fpi_extension_filers.jsonl"),
)
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class CarrierInputError(ValueError):
    """The frame manifest, freeze record, or project config is unusable."""


class CarrierReconciliationError(RuntimeError):
    """A carrier count identity failed; the run is refused, nothing written."""


@dataclass
class CarrierRunResult:
    run_id: str
    dry_run: bool
    run_dir: Path | None = None
    manifest_path: Path | None = None
    counts: dict = field(default_factory=dict)
    reconciliation: dict = field(default_factory=dict)


def _load_verified_frame(
    repo_root: Path, frame_manifest_path: Path
) -> tuple[dict, dict[str, list[dict]]]:
    """Schema-validate the frame manifest and verify every artifact hash."""
    if not frame_manifest_path.is_file():
        raise CarrierInputError(
            f"Frame manifest not found: {frame_manifest_path}"
        )
    manifest = read_json(frame_manifest_path)
    schema = read_json(repo_root / FRAME_MANIFEST_SCHEMA_RELATIVE_PATH)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest),
        key=lambda e: e.json_path,
    )
    if errors:
        details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
        raise CarrierInputError(
            f"Frame manifest violates its canonical schema: {details}"
        )
    run_dir = frame_manifest_path.parent
    for filename, expected in manifest["output_hashes"].items():
        artifact = run_dir / filename
        if not artifact.is_file():
            raise CarrierInputError(f"Frame artifact missing: {artifact}")
        observed = sha256_file(artifact)
        if observed != expected:
            raise CarrierInputError(
                f"Frame artifact hash mismatch for {filename}: manifest "
                f"{expected}, observed {observed}. Refusing to build."
            )
    strata = {
        stratum: read_jsonl(run_dir / filename)
        for stratum, filename in _STRATA
    }
    return manifest, strata


def _load_baseline_cutoff(project_config_path: Path) -> date:
    if not project_config_path.is_file():
        raise CarrierInputError(
            f"Project config not found: {project_config_path}"
        )
    config = yaml.safe_load(project_config_path.read_text(encoding="utf-8"))
    universe = (config or {}).get("universe") or {}
    raw = universe.get("baseline_cutoff")
    if raw is None:
        raise CarrierInputError(
            "Project config carries no universe.baseline_cutoff; the "
            "baseline cutoff is the W0-frozen value, never a parameter."
        )
    return raw if isinstance(raw, date) else date.fromisoformat(str(raw))


def _build_firm_rows(
    stratum: str, records: list[dict], cutoff: date
) -> list[dict]:
    by_cik: dict[str, list[dict]] = {}
    for record in records:
        by_cik.setdefault(record["cik"], []).append(record)

    rows: list[dict] = []
    for cik in sorted(by_cik):
        filings = sorted(
            by_cik[cik],
            key=lambda r: (r["filing_date"], r["accession_number"]),
        )
        pre_cutoff = [
            f for f in filings
            if date.fromisoformat(f["filing_date"]) <= cutoff
        ]
        if pre_cutoff:
            baseline = pre_cutoff[-1]
            tie_broken = (
                sum(
                    1 for f in pre_cutoff
                    if f["filing_date"] == baseline["filing_date"]
                )
                > 1
            )
            status = "baseline_candidate"
        else:
            baseline = None
            tie_broken = False
            status = "post_baseline_entrant"
        rows.append(
            {
                "stratum": stratum,
                "cik": cik,
                "baseline_status": status,
                "baseline_accession": (
                    baseline["accession_number"] if baseline else None
                ),
                "baseline_form": baseline["form"] if baseline else None,
                "baseline_filing_date": (
                    baseline["filing_date"] if baseline else None
                ),
                "baseline_canonical_name": (
                    baseline["canonical_name"] if baseline else None
                ),
                "baseline_tie_broken": tie_broken,
                "dual_stratum": False,
                "filings_count": len(filings),
                "filings_on_or_before_cutoff": len(pre_cutoff),
                "first_filing_date": filings[0]["filing_date"],
                "last_filing_date": filings[-1]["filing_date"],
                "observed_names": sorted(
                    {f["canonical_name"] for f in filings}
                ),
                "issuer_status": "unknown",
                "issuer_status_basis": ISSUER_STATUS_BASIS,
            }
        )
    return rows


def _sample(entries: list) -> list:
    return entries[:SAMPLE_CAP]


def run_baseline_carrier(
    *,
    repo_root: str | Path,
    project_config_path: str | Path,
    frame_manifest_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    clock=None,
    dry_run: bool = False,
) -> CarrierRunResult:
    """Derive the firm-level baseline carrier from a completed FRAME run."""
    root = Path(repo_root)
    now = clock or (lambda: datetime.now(timezone.utc))
    if not _RUN_ID_RE.match(run_id):
        raise CarrierInputError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )

    frame_manifest_file = Path(frame_manifest_path)
    frame_manifest, strata = _load_verified_frame(root, frame_manifest_file)
    frame_manifest_sha256 = sha256_file(frame_manifest_file)

    freeze_path = root / FREEZE_RECORD_RELATIVE_PATH
    if not freeze_path.is_file():
        raise CarrierInputError(
            f"Committed FRAME freeze record not found: {freeze_path}"
        )
    freeze = read_json(freeze_path)
    frame_is_frozen_frame = (
        frame_manifest_sha256 == freeze["frame_artifact"]["manifest_sha256"]
    )

    config_path = Path(project_config_path)
    cutoff = _load_baseline_cutoff(config_path)
    window_start = date.fromisoformat(frame_manifest["filing_window_start"])
    window_end = date.fromisoformat(frame_manifest["filing_window_end"])
    if not window_start <= cutoff <= window_end:
        raise CarrierInputError(
            f"Baseline cutoff {cutoff} lies outside the frame filing window "
            f"{window_start}..{window_end}; the inputs are inconsistent. "
            "Refusing to build."
        )

    rows = [
        row
        for stratum, _ in _STRATA
        for row in _build_firm_rows(stratum, strata[stratum], cutoff)
    ]
    dual_ciks = {r["cik"] for r in rows if r["stratum"] == "domestic"} & {
        r["cik"] for r in rows if r["stratum"] == "fpi_extension"
    }
    for row in rows:
        row["dual_stratum"] = row["cik"] in dual_ciks

    def _stratum_rows(stratum: str) -> list[dict]:
        return [r for r in rows if r["stratum"] == stratum]

    def _with_status(entries: list[dict], status: str) -> list[dict]:
        return [r for r in entries if r["baseline_status"] == status]

    counts: dict[str, int] = {}
    for stratum, _ in _STRATA:
        stratum_rows = _stratum_rows(stratum)
        counts[f"frame_annual_records_{stratum}"] = len(strata[stratum])
        counts[f"firms_{stratum}"] = len(stratum_rows)
        counts[f"baseline_candidates_{stratum}"] = len(
            _with_status(stratum_rows, "baseline_candidate")
        )
        counts[f"post_baseline_entrants_{stratum}"] = len(
            _with_status(stratum_rows, "post_baseline_entrant")
        )
    counts["frame_annual_records_total"] = sum(
        len(strata[stratum]) for stratum, _ in _STRATA
    )
    counts["firms_total"] = len(rows)
    counts["baseline_candidates_total"] = len(
        _with_status(rows, "baseline_candidate")
    )
    counts["post_baseline_entrants_total"] = len(
        _with_status(rows, "post_baseline_entrant")
    )
    counts["no_eligible_filing_firms"] = sum(
        1 for r in rows if r["filings_count"] == 0
    )
    counts["baseline_ties_broken"] = sum(
        1 for r in rows if r["baseline_tie_broken"]
    )
    counts["dual_stratum_firms"] = len(dual_ciks)
    counts["filings_on_or_before_cutoff"] = sum(
        r["filings_on_or_before_cutoff"] for r in rows
    )
    counts["filings_after_cutoff"] = (
        counts["frame_annual_records_total"]
        - counts["filings_on_or_before_cutoff"]
    )

    frame_filer_keys = {
        (stratum, record["cik"])
        for stratum, _ in _STRATA
        for record in strata[stratum]
    }
    reconciliation = {
        "frame: manifest counts match loaded records": (
            frame_manifest["counts"]["domestic_annual_records"]
            == counts["frame_annual_records_domestic"]
            and frame_manifest["counts"]["fpi_extension_records"]
            == counts["frame_annual_records_fpi_extension"]
        ),
        "carrier: firm rows = domestic firms + fpi firms": (
            counts["firms_total"]
            == counts["firms_domestic"] + counts["firms_fpi_extension"]
        ),
        "carrier: firms = baseline candidates + post-baseline entrants": (
            counts["firms_total"]
            == counts["baseline_candidates_total"]
            + counts["post_baseline_entrants_total"]
            and counts["no_eligible_filing_firms"] == 0
        ),
        "carrier: per-firm filing counts sum to frame records": (
            sum(r["filings_count"] for r in rows)
            == counts["frame_annual_records_total"]
        ),
        "carrier: filings split at cutoff sums to frame records": (
            counts["filings_on_or_before_cutoff"]
            + counts["filings_after_cutoff"]
            == counts["frame_annual_records_total"]
        ),
        "carrier: every frame filer has exactly one row per stratum": (
            {(r["stratum"], r["cik"]) for r in rows} == frame_filer_keys
            and len(rows) == len(frame_filer_keys)
        ),
    }
    failed = sorted(name for name, ok in reconciliation.items() if not ok)
    if failed:
        raise CarrierReconciliationError(
            f"Carrier reconciliation failed: {'; '.join(failed)}. "
            "Nothing was written."
        )

    samples = {
        "baseline_candidates": _sample(
            [
                [r["stratum"], r["cik"], r["baseline_accession"]]
                for r in rows
                if r["baseline_status"] == "baseline_candidate"
            ]
        ),
        "post_baseline_entrants": _sample(
            [
                [r["stratum"], r["cik"], r["first_filing_date"]]
                for r in rows
                if r["baseline_status"] == "post_baseline_entrant"
            ]
        ),
        "baseline_ties_broken": _sample(
            [
                [r["stratum"], r["cik"], r["baseline_accession"]]
                for r in rows
                if r["baseline_tie_broken"]
            ]
        ),
        "dual_stratum_firms": _sample(sorted(dual_ciks)),
    }

    rows_payload = (
        "\n".join(
            json.dumps(row, default=str, sort_keys=True) for row in rows
        )
        + ("\n" if rows else "")
    ).encode("utf-8")

    schema_versions = read_json(
        root / "schemas" / "schema_version_manifest.json"
    )["schemas"]
    manifest = {
        "run_id": run_id,
        "frame_manifest_sha256": frame_manifest_sha256,
        "frame_run_dir": str(frame_manifest_file.parent),
        "frame_version": frame_manifest["frame_version"],
        "frame_freeze": {
            "path": str(FREEZE_RECORD_RELATIVE_PATH),
            "record_sha256": sha256_file(freeze_path),
            "frozen_version": freeze["frozen_version"],
            "frame_is_frozen_frame": frame_is_frozen_frame,
        },
        "baseline_cutoff": str(cutoff),
        "project_config_hash": sha256_file(config_path),
        "filing_window_start": str(window_start),
        "filing_window_end": str(window_end),
        "domestic_forms": list(frame_manifest["domestic_forms"]),
        "extension_forms": list(frame_manifest["extension_forms"]),
        "issuer_status_basis": ISSUER_STATUS_BASIS,
        "counts": counts,
        "reconciliation": reconciliation,
        "samples": samples,
        "output_hashes": {
            CARRIER_ROWS_FILENAME: sha256_bytes(rows_payload)
        },
        "run_timestamp": now().isoformat(),
        "schema_versions": {
            "universe_baseline_carrier_manifest": schema_versions[
                "universe_baseline_carrier_manifest"
            ]
        },
        "limitations": [
            "Stage 00B carrier only: no issuer exclusion is decided here; "
            "every frame filer is retained.",
            "Cover-page issuer flags and SIC are absent from the EDGAR full "
            "index; issuer status is unknown pending filing-document "
            "evidence from a later increment.",
            "Domestic and FPI-extension strata are carried separately and "
            "never merged; dual-stratum CIKs are flagged, not resolved.",
            "Post-baseline entrants are a retained separate cohort, never "
            "dropped and never pooled with baseline candidates.",
            "DERA FSDS plays no role in this artifact: it is a frame "
            "validation source only, never a universe eligibility input.",
        ],
    }
    schema = read_json(root / CARRIER_SCHEMA_RELATIVE_PATH)
    schema_errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest),
        key=lambda e: e.json_path,
    )
    if schema_errors:
        details = "; ".join(
            f"{e.json_path}: {e.message}" for e in schema_errors[:5]
        )
        raise ValueError(
            f"Carrier manifest violates the canonical schema: {details}"
        )

    result = CarrierRunResult(
        run_id=run_id,
        dry_run=dry_run,
        counts=counts,
        reconciliation=reconciliation,
    )
    if dry_run:
        return result

    run_dir = create_run_directory(output_dir, run_id)
    write_bytes_once(
        run_dir / CARRIER_ROWS_FILENAME, rows_payload,
        what="baseline carrier rows",
    )
    manifest_payload = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    write_bytes_once(
        run_dir / CARRIER_MANIFEST_FILENAME, manifest_payload,
        what="baseline carrier manifest",
    )
    result.run_dir = run_dir
    result.manifest_path = run_dir / CARRIER_MANIFEST_FILENAME
    return result
