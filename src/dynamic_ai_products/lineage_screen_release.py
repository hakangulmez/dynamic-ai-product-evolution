"""Reconcile a completed screen and its repair into one SCREEN release (ADR-124).

Two completed runs exist. The base full-cohort screen validated 6,467 rows and
left 574 unverified; the repair run re-asked exactly those 574 and recovered
363, leaving 211 that failed validation twice. This module joins them into the
first immutable SCREEN release, and it does so by derivation alone: no model is
called, no prompt is rendered, no provider is reached, and neither source run is
modified in any way.

**No authorization governs this.** Every grant in this project authorizes
spending — attempts, tokens, cost, an endpoint allowlist. A reconciliation
spends nothing, so a grant would authorize a set that is empty. What replaces it
is stricter binding: both source manifests are pinned by digest, every consumed
output is re-hashed against its own manifest before a single record is read,
both runs are revalidated through their committed loaders, and the repair run's
recorded source digests must equal the base run's actual digests. A repair
reconciled against the wrong base is refused structurally rather than by
convention.

**One rule decides every row.** A repair output supersedes a base row only when
the repair record is ``screened_packet`` and the base row is
``model_evidence_unverified``. Nothing else is replaceable: an attempt to
supersede a valid, insufficient-evidence or truncated row is a hard refusal, not
a skipped row. Coverage is checked as set equality against the base's unverified
population, so a gap, a duplicate, or a foreign row all stop the build.

**Both histories survive on every reconciled row.** A repaired row carries the
repair observation that now stands *and* the base observation it superseded,
including the reason the base row failed. A row that failed twice is named
``unresolved_after_repair`` rather than dropped: it keeps both raw-response
identities and both failure reasons, holds no status and no evidence, and is
excluded from every valid-status count and from any later classifier input. The
release states its own hole rather than leaving it to be inferred from an
absence.

**The residual is a const, not a range.** ``max_unresolved_after_repair`` is
pinned at exactly 211 — the residual this release measured. The 900 breaker it
might have inherited was a run-time budget for a 7,042-row screen, and carrying
it here would let a later reconciliation ship up to 900 holes under a threshold
nobody re-decided. A different residual requires a new contract version and a
new decision, which is the point.

**Structurally separate from every run.** The release is written under its own
root with its own filenames, so the authoritative, promotion, diagnostic,
diagnostic-repair, continuation and repair loaders all refuse it with no change
on their side; ``require_screen_release`` accepts nothing but a release. In
particular ``require_promotable_screen_run`` is untouched and continues to
refuse both source runs — the base is a continuation manifest it does not read,
and the repair run is non-promotable by contract.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products.provenance import WriteOnceError, write_bytes_once

from .lineage_screen_continuation_v5 import (
    CONTINUATION_V5_MANIFEST_FILENAME,
    CONTINUATION_V5_RECORDS_FILENAME,
    require_continuation_v5_run,
)
from .lineage_screen_repair import (
    REPAIR_MANIFEST_FILENAME,
    REPAIR_RECORDS_FILENAME,
    require_repair_run,
)
from .universe.freeze import create_run_directory
from .universe.lineage_screen import (
    FAILURE_RECEIPT_FILENAME,
    RAW_RESPONSES_FILENAME,
    SCREEN_STATUSES,
    ScreenInputError,
    _canonical_line,
    _decode_utf8,
    _load_schema,
    _RUN_ID_RE,
    _sha256,
    _validate,
)

__all__ = [
    "RELEASE_MANIFEST_FILENAME",
    "RELEASE_RECORDS_FILENAME",
    "ScreenReleaseResult",
    "build_screen_release",
    "require_screen_release",
]

RELEASE_RECORDS_FILENAME = "universe_screen_release_records.jsonl"
RELEASE_MANIFEST_FILENAME = "universe_screen_release_manifest.json"

RECORD_CONTRACT = "universe_screen_release_record@0.1.0"
MANIFEST_CONTRACT = "universe_screen_release_manifest@0.1.0"
RELEASE_KIND = "screen_release_v1"
RECORD_ORDER = "base_planned_row_order"

RECORD_SCHEMA = "schemas/universe_screen_release_record.schema.json"
MANIFEST_SCHEMA = "schemas/universe_screen_release_manifest.schema.json"

#: The one rule that decides supersession, named in the manifest so a reader
#: never has to infer it from the counts.
SUPERSESSION_RULE = "repair_screened_supersedes_base_unverified@1"
REPLACEABLE_KIND = "model_evidence_unverified"
REPLACING_KIND = "screened_packet"

#: The residual this release accepts, pinned exactly rather than inherited.
MAX_UNRESOLVED_AFTER_REPAIR = 211


@dataclass
class ScreenReleaseResult:
    release_id: str
    release_dir: Path | None
    dry_run: bool
    status: str  # "completed" | "dry_run"
    counts: dict
    rates: dict
    reconciliation: dict
    manifest_path: Path | None = None


def _load_source(
    root: Path, manifest_path: Path, *, expected_sha256: str, what: str,
    manifest_filename: str, records_filename: str, loader: Callable[[Path], Path],
) -> tuple[dict, list[dict], dict]:
    """Hydrate one completed source run by digest, then read its records.

    Order matters: the manifest is pinned, the run is revalidated through its
    own committed loader, and every declared output is re-hashed before a
    single record is parsed.
    """
    if manifest_path.name != manifest_filename:
        raise ScreenInputError(
            f"The {what} manifest must be {manifest_filename}; "
            f"{manifest_path.name} is a different run kind."
        )
    if not manifest_path.is_file():
        raise ScreenInputError(f"{what} manifest not found: {manifest_path}")
    raw = manifest_path.read_bytes()
    observed = _sha256(raw)
    if observed != expected_sha256:
        raise ScreenInputError(
            f"The {what} manifest hashes to {observed}, but {expected_sha256} "
            "was pinned; this is not the run that was reconciled."
        )
    directory = manifest_path.parent
    loader(directory)
    manifest = json.loads(_decode_utf8(raw, manifest_filename))
    for filename, recorded in manifest["output_hashes"].items():
        target = directory / filename
        if not target.is_file() or _sha256(target.read_bytes()) != recorded:
            raise ScreenInputError(
                f"{what} output {filename} is missing or no longer hashes to "
                "its manifest entry; nothing may be read from this run."
            )
    records = [
        json.loads(line) for line
        in _decode_utf8((directory / records_filename).read_bytes(),
                        records_filename).splitlines()
        if line.strip()
    ]
    digests = {
        "manifest_sha256": observed,
        "records_jsonl_sha256": _sha256((directory / records_filename).read_bytes()),
        "raw_responses_jsonl_sha256":
            _sha256((directory / RAW_RESPONSES_FILENAME).read_bytes()),
    }
    return manifest, records, digests


def _chain(run_id: str, record: dict, *, failure_reason_code=None,
           source_row_ordinal=None) -> dict:
    return {
        "run_id": run_id,
        "raw_response_id": record["raw_response_id"],
        "raw_response_sha256": record["raw_response_sha256"],
        "failure_reason_code": failure_reason_code,
        "source_row_ordinal": source_row_ordinal,
    }


def _carry(record: dict, origin: str, provenance: dict, **overrides) -> dict:
    """Build one release row from a source record without changing its meaning."""
    row = {
        "record_contract": RECORD_CONTRACT,
        "release_origin": origin,
        "record_kind": record["record_kind"],
        "cik": record["cik"],
        "company_id": record["company_id"],
        "accession": record["accession"],
        "form": record["form"],
        "baseline_filing_date": record["baseline_filing_date"],
        "source_id": record["source_id"],
        "packet_sha256": record["packet_sha256"],
        "prompt_sha256": record["prompt_sha256"],
        "model_route": record["model_route"],
        "screen_status": record["screen_status"],
        "screen_output": record["screen_output"],
        "failure_reason_code": record["failure_reason_code"],
        "failure_detail": record["failure_detail"],
        "truncation_evidence": record.get("truncation_evidence"),
        "release_provenance": provenance,
    }
    row.update(overrides)
    return row


def build_screen_release(
    *,
    repo_root: str | Path,
    base_manifest_path: str | Path,
    base_manifest_sha256: str,
    repair_manifest_path: str | Path,
    repair_manifest_sha256: str,
    output_dir: str | Path,
    release_id: str,
    clock: Callable[[], datetime],
    dry_run: bool = False,
) -> ScreenReleaseResult:
    """Reconcile one base screen and one repair run into a SCREEN release."""
    root = Path(repo_root)
    if not _RUN_ID_RE.match(release_id):
        raise ScreenInputError("Invalid release id.")

    base_manifest, base_records, base_digests = _load_source(
        root, Path(base_manifest_path), expected_sha256=base_manifest_sha256,
        what="base screen", manifest_filename=CONTINUATION_V5_MANIFEST_FILENAME,
        records_filename=CONTINUATION_V5_RECORDS_FILENAME,
        loader=require_continuation_v5_run)
    repair_manifest, repair_records, repair_digests = _load_source(
        root, Path(repair_manifest_path), expected_sha256=repair_manifest_sha256,
        what="repair", manifest_filename=REPAIR_MANIFEST_FILENAME,
        records_filename=REPAIR_RECORDS_FILENAME, loader=require_repair_run)

    base_run_id = base_manifest["run_id"]
    repair_run_id = repair_manifest["run_id"]
    # The repair must have been derived from THIS base run, proven by digest.
    source = repair_manifest["source"]
    if source["source_run_id"] != base_run_id:
        raise ScreenInputError(
            f"The repair run was derived from {source['source_run_id']!r}, but "
            f"the base run is {base_run_id!r}; they may not be reconciled."
        )
    for key, actual in (("source_manifest_sha256", base_digests["manifest_sha256"]),
                        ("source_records_jsonl_sha256",
                         base_digests["records_jsonl_sha256"]),
                        ("source_raw_responses_jsonl_sha256",
                         base_digests["raw_responses_jsonl_sha256"])):
        if source[key] != actual:
            raise ScreenInputError(
                f"The repair run recorded a different base {key}; it was "
                "derived from other bytes than the base run supplied here."
            )
    if len(base_records) != base_manifest["counts"]["planned_rows"]:
        raise ScreenInputError(
            "The base run's record count disagrees with its own manifest."
        )

    # --- coverage: exactly the base's unverified population, no more, no less
    base_unverified = {
        (r["cik"], r["accession"]): (i, r)
        for i, r in enumerate(base_records, 1)
        if r["record_kind"] == REPLACEABLE_KIND
    }
    repair_by_key: dict[tuple[str, str], dict] = {}
    for record in repair_records:
        key = (record["cik"], record["accession"])
        if key in repair_by_key:
            raise ScreenInputError(
                f"The repair run holds two records for {key}; a row may be "
                "re-asked once."
            )
        repair_by_key[key] = record
    missing = sorted(set(base_unverified) - set(repair_by_key))
    foreign = sorted(set(repair_by_key) - set(base_unverified))
    if missing or foreign:
        raise ScreenInputError(
            f"Repair coverage is not exact: {len(missing)} base unverified "
            f"row(s) were never re-asked and {len(repair_by_key) - len(base_unverified) + len(missing)} "
            f"repair row(s) target rows the base did not leave unverified. "
            f"First missing: {missing[:1]}; first foreign: {foreign[:1]}."
        )
    # A repair row may never target anything but an unverified base row. The
    # set equality above already proves it; this restates it as its own refusal
    # so the reason is legible when a future source shape changes.
    base_by_key = {(r["cik"], r["accession"]): r for r in base_records}
    for key in repair_by_key:
        kind = base_by_key[key]["record_kind"]
        if kind != REPLACEABLE_KIND:
            raise ScreenInputError(
                f"Repair row {key} targets a base row of kind {kind!r}; only "
                f"a {REPLACEABLE_KIND!r} row may be superseded."
            )

    # --- build one release row per planned base row, in base order
    records: list[dict] = []
    repaired_by_base_reason: dict[str, int] = {}
    unresolved_by_base_reason: dict[str, int] = {}
    unresolved_by_repair_reason: dict[str, int] = {}
    for ordinal, base in enumerate(base_records, 1):
        key = (base["cik"], base["accession"])
        kind = base["record_kind"]
        if kind == "screened_packet":
            records.append(_carry(
                base, "base_valid",
                {"base": _chain(base_run_id, base, source_row_ordinal=ordinal),
                 "repair": None}))
        elif kind == "insufficient_evidence":
            records.append(_carry(base, "insufficient_evidence",
                                  {"base": None, "repair": None}))
        elif kind == "model_output_truncated":
            records.append(_carry(base, "model_output_truncated",
                                  {"base": None, "repair": None}))
        elif kind == REPLACEABLE_KIND:
            repair = repair_by_key[key]
            base_reason = base["failure_reason_code"]
            base_chain = _chain(base_run_id, base,
                                failure_reason_code=base_reason,
                                source_row_ordinal=ordinal)
            if repair["record_kind"] == REPLACING_KIND:
                repaired_by_base_reason[base_reason] = (
                    repaired_by_base_reason.get(base_reason, 0) + 1)
                records.append(_carry(
                    repair, "repaired",
                    {"base": base_chain,
                     "repair": _chain(repair_run_id, repair)}))
            else:
                repair_reason = repair["failure_reason_code"]
                unresolved_by_base_reason[base_reason] = (
                    unresolved_by_base_reason.get(base_reason, 0) + 1)
                unresolved_by_repair_reason[repair_reason] = (
                    unresolved_by_repair_reason.get(repair_reason, 0) + 1)
                records.append(_carry(
                    repair, "unresolved_after_repair",
                    {"base": base_chain,
                     "repair": _chain(repair_run_id, repair,
                                      failure_reason_code=repair_reason)}))
        else:
            raise ScreenInputError(
                f"Base row {ordinal} carries kind {kind!r}, which this release "
                "contract does not know how to reconcile."
            )

    by_origin = {name: sum(r["release_origin"] == name for r in records)
                 for name in ("base_valid", "repaired", "unresolved_after_repair",
                              "insufficient_evidence", "model_output_truncated")}
    valid = [r for r in records if r["record_kind"] == "screened_packet"]
    unresolved = [r for r in records
                  if r["release_origin"] == "unresolved_after_repair"]
    if len(unresolved) > MAX_UNRESOLVED_AFTER_REPAIR:
        raise ScreenInputError(
            f"{len(unresolved)} rows remain unresolved after repair; this "
            f"release accepts exactly {MAX_UNRESOLVED_AFTER_REPAIR}. A "
            "different residual needs its own decision."
        )
    counts = {
        "planned_rows": len(records),
        "cohort_rows": base_manifest["counts"]["cohort_rows"],
        "base_valid": by_origin["base_valid"],
        "repaired": by_origin["repaired"],
        "unresolved_after_repair": by_origin["unresolved_after_repair"],
        "insufficient_evidence": by_origin["insufficient_evidence"],
        "model_output_truncated": by_origin["model_output_truncated"],
        "valid_screened_rows": len(valid),
        "max_unresolved_after_repair": MAX_UNRESOLVED_AFTER_REPAIR,
        "by_screen_status": {s: sum(r["screen_status"] == s for r in valid)
                             for s in SCREEN_STATUSES},
        "unresolved_by_base_reason": dict(unresolved_by_base_reason),
        "unresolved_by_repair_reason": dict(unresolved_by_repair_reason),
        "repaired_by_base_reason": dict(repaired_by_base_reason),
    }
    cohort = counts["cohort_rows"]
    rates = {
        "pre_repair_unverified_rate": round(len(base_unverified) / cohort, 6),
        "residual_unverified_rate": round(len(unresolved) / cohort, 6),
        "rate_denominator": "cohort_rows",
    }
    if dry_run:
        return ScreenReleaseResult(release_id, None, True, "dry_run", counts,
                                   rates, {})

    validator = Draft202012Validator(_load_schema(root, RECORD_SCHEMA),
                                     format_checker=FormatChecker())
    for row in records:
        errors = sorted(validator.iter_errors(row), key=lambda e: e.json_path)
        if errors:
            raise ScreenInputError(
                f"Built release record violates {RECORD_CONTRACT} at "
                f"{errors[0].json_path}: {errors[0].message}"
            )
    records_bytes = "".join(_canonical_line(r) + "\n" for r in records).encode("utf-8")

    base_dir, repair_dir = (Path(base_manifest_path).parent,
                            Path(repair_manifest_path).parent)
    reconciliation = {
        "one release row per planned base row": (
            len(records) == len(base_records)
            == base_manifest["counts"]["planned_rows"]),
        "the five origins partition the release": (
            sum(by_origin.values()) == len(records)),
        "release rows follow base planned order": (
            [(r["cik"], r["accession"]) for r in records]
            == [(r["cik"], r["accession"]) for r in base_records]),
        "base-valid rows equal the base screened population": (
            by_origin["base_valid"] == base_manifest["counts"]["screened_packets"]),
        "repaired plus unresolved equal the base unverified population": (
            by_origin["repaired"] + by_origin["unresolved_after_repair"]
            == base_manifest["counts"]["model_evidence_unverified"]
            == len(base_unverified)),
        "repaired equals the repair run's own recovered count": (
            by_origin["repaired"] == repair_manifest["counts"]["repaired_rows"]),
        "unresolved equals the repair run's own failed count": (
            by_origin["unresolved_after_repair"]
            == repair_manifest["counts"]["still_unverified_rows"]),
        "insufficient-evidence rows are carried through unchanged": (
            by_origin["insufficient_evidence"]
            == base_manifest["counts"]["insufficient_evidence"]),
        "the truncated row is carried through unchanged": (
            by_origin["model_output_truncated"]
            == base_manifest["counts"]["model_output_truncated"]),
        "every truncated row keeps its capture evidence": all(
            isinstance(r["truncation_evidence"], dict) for r in records
            if r["release_origin"] == "model_output_truncated"),
        "valid rows are exactly base-valid plus repaired": (
            len(valid) == by_origin["base_valid"] + by_origin["repaired"]),
        "status counts sum to the valid population": (
            sum(counts["by_screen_status"].values()) == len(valid)),
        "no unresolved row carries a status or evidence": all(
            r["screen_status"] is None and r["screen_output"] is None
            for r in unresolved),
        "unresolved rows appear in no valid-status count": not (
            {(r["cik"], r["accession"]) for r in unresolved}
            & {(r["cik"], r["accession"]) for r in valid}),
        "every repaired row keeps both provenance chains": all(
            isinstance(r["release_provenance"]["base"], dict)
            and isinstance(r["release_provenance"]["repair"], dict)
            and r["release_provenance"]["base"]["failure_reason_code"]
            for r in records if r["release_origin"] == "repaired"),
        "every unresolved row keeps both failure reasons": all(
            r["release_provenance"]["base"]["failure_reason_code"]
            and r["release_provenance"]["repair"]["failure_reason_code"]
            for r in unresolved),
        "no base-valid row was superseded": all(
            r["release_provenance"]["repair"] is None for r in records
            if r["release_origin"] == "base_valid"),
        "the residual stayed within the pinned tolerance": (
            len(unresolved) <= MAX_UNRESOLVED_AFTER_REPAIR),
        "repair coverage was exactly the base unverified population": (
            set(repair_by_key) == set(base_unverified)),
        "both sources are byte-unchanged": (
            _sha256((base_dir / CONTINUATION_V5_MANIFEST_FILENAME).read_bytes())
            == base_digests["manifest_sha256"]
            and _sha256((base_dir / CONTINUATION_V5_RECORDS_FILENAME).read_bytes())
            == base_digests["records_jsonl_sha256"]
            and _sha256((repair_dir / REPAIR_MANIFEST_FILENAME).read_bytes())
            == repair_digests["manifest_sha256"]
            and _sha256((repair_dir / REPAIR_RECORDS_FILENAME).read_bytes())
            == repair_digests["records_jsonl_sha256"]),
    }
    if not all(reconciliation.values()):
        failed = sorted(k for k, v in reconciliation.items() if not v)
        raise ScreenInputError(
            f"Release reconciliation failed; nothing is written. Failed "
            f"identities: {failed}."
        )
    release_dir = create_run_directory(output_dir, release_id)
    manifest = {
        "manifest_contract": MANIFEST_CONTRACT,
        "release_id": release_id,
        "release_kind": RELEASE_KIND,
        "run_timestamp": clock().isoformat(),
        "sources": {
            "base": {"run_id": base_run_id,
                     "manifest_path": str(base_manifest_path), **base_digests},
            "repair": {
                "run_id": repair_run_id,
                "manifest_path": str(repair_manifest_path),
                "selection_artifact_sha256":
                    repair_manifest["selection"]["selection_artifact_sha256"],
                **repair_digests},
            "sources_unmodified": True,
            "no_model_call": True,
        },
        "supersession_rule": {
            "rule": SUPERSESSION_RULE,
            "replaces_only_record_kind": REPLACEABLE_KIND,
            "requires_repair_record_kind": REPLACING_KIND,
            "coverage_is_exact": True,
        },
        "output_contract": RECORD_CONTRACT,
        "output_hashes": {RELEASE_RECORDS_FILENAME: _sha256(records_bytes)},
        "record_order": RECORD_ORDER,
        "counts": counts,
        "rates": rates,
        "reconciliation": reconciliation,
        "schema_versions": {
            "universe_screen_release_record": "0.1.0",
            "universe_screen_release_manifest": "0.1.0",
            "base_screen_manifest": base_manifest["manifest_contract"],
            "repair_manifest": repair_manifest["manifest_contract"],
        },
        "limitations": [
            "A repaired row is a second observation, not a corrected first "
            "one: no quote, reference or status was ever edited, and the "
            "superseded base observation is retained by digest.",
            f"{len(unresolved)} rows failed validation twice and are named "
            "rather than dropped. They carry no status, enter no valid-status "
            "count, and must not reach a classifier.",
            "The residual tolerance is pinned to this release's measured "
            "value; it is not a general threshold and may not be inherited.",
            "This release reconciles evidence validity only. It makes no "
            "claim about screening accuracy, and a validated row is not a "
            "correct row.",
        ],
    }
    _validate(manifest, _load_schema(root, MANIFEST_SCHEMA),
              "Universe screen release manifest")
    try:
        write_bytes_once(release_dir / RELEASE_RECORDS_FILENAME, records_bytes,
                         what="screen release records")
        write_bytes_once(
            release_dir / RELEASE_MANIFEST_FILENAME,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            what="screen release manifest")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    return ScreenReleaseResult(
        release_id, release_dir, False, "completed", counts, rates,
        reconciliation, release_dir / RELEASE_MANIFEST_FILENAME)


def require_screen_release(release_dir: str | Path) -> Path:
    """Refuse anything that is not a completed, self-consistent SCREEN release."""
    directory = Path(release_dir)
    if (directory / FAILURE_RECEIPT_FILENAME).exists():
        raise ScreenInputError(
            f"Release {directory} holds a failure receipt; a release is never "
            "built from or beside a failed run."
        )
    manifest_path = directory / RELEASE_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ScreenInputError(
            f"Directory {directory} holds no release manifest; only a "
            "reconciled release may be consumed here."
        )
    manifest = json.loads(_decode_utf8(manifest_path.read_bytes(),
                                       RELEASE_MANIFEST_FILENAME))
    if manifest.get("manifest_contract") != MANIFEST_CONTRACT:
        raise ScreenInputError(
            f"Release {directory} declares {manifest.get('manifest_contract')!r}; "
            f"this loader consumes {MANIFEST_CONTRACT!r} only."
        )
    for filename, recorded in manifest["output_hashes"].items():
        target = directory / filename
        if not target.is_file() or _sha256(target.read_bytes()) != recorded:
            raise ScreenInputError(
                f"Release output {filename} is missing or no longer hashes to "
                "its manifest entry."
            )
    return manifest_path
