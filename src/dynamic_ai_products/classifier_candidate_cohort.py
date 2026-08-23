"""Derive the classifier-candidate cohort from a release and its overlay (ADR-125).

The classifier does not exist yet. This module answers the question that must be
settled before it does: which rows are eligible to be classified at all. The
answer is a derivation from two hash-bound inputs — an immutable SCREEN_v1
release and a complete human-review overlay — and it is written as a third
artifact that neither input knows about and no existing loader consumes.

**One admission rule.** A row is admitted when its standing judgement is
``LIKELY_ELIGIBLE`` or ``BOUNDARY_OR_UNCERTAIN``, whether that judgement came
from the screen or from a reviewer. Everything else is excluded and counted:
model ``LIKELY_INELIGIBLE``, human ``LIKELY_INELIGIBLE``, insufficient-evidence
packet failures, the truncated row, and any unresolved row whose decision did
not admit it. The exclusions are reported rather than implied, so the cohort
states its own shape instead of leaving a reader to subtract.

**Admission origin travels with every row.** A ``model_screen`` row was
validated by the screen; a ``human_review`` row failed validation twice and was
decided by a person against the immutable Item 1 bytes. These are not the same
kind of evidence and the cohort refuses to flatten them: the origin is on the
record, along with the screen's raw-response identity or the reviewer's identity,
protocol version, timestamp, evidence count and both prior failure reasons. A
later analysis can weight them differently, hold them apart, or drop one — but
it cannot fail to notice which is which.

**Counts are derived, never declared.** Every total comes from the two inputs.
No population size is written into this module, this schema, or its tests: a
literal would encode one particular release and would silently pass while
describing a different cohort.

**Structurally distinct from both neighbours.** The cohort is neither a screen
release nor a classifier output. It carries its own contract and filenames, so
the authoritative, promotion, diagnostic, continuation, repair and release
loaders all refuse it, and ``require_classifier_candidate_cohort`` refuses each
of them in turn.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products.provenance import WriteOnceError, write_bytes_once

from .human_review_overlay import (
    OVERLAY_DECISIONS_FILENAME,
    OVERLAY_MANIFEST_FILENAME,
    require_human_review_overlay,
)
from .lineage_screen_release import (
    RELEASE_MANIFEST_FILENAME,
    RELEASE_RECORDS_FILENAME,
    require_screen_release,
)
from .universe.freeze import create_run_directory
from .universe.lineage_screen import (
    ScreenInputError,
    _canonical_line,
    _decode_utf8,
    _load_schema,
    _RUN_ID_RE,
    _sha256,
    _validate,
)

__all__ = [
    "COHORT_MANIFEST_FILENAME",
    "COHORT_RECORDS_FILENAME",
    "ClassifierCandidateCohortResult",
    "build_classifier_candidate_cohort",
    "require_classifier_candidate_cohort",
]

COHORT_RECORDS_FILENAME = "universe_classifier_candidate_records.jsonl"
COHORT_MANIFEST_FILENAME = "universe_classifier_candidate_cohort_manifest.json"

RECORD_CONTRACT = "universe_classifier_candidate_record@0.1.0"
MANIFEST_CONTRACT = "universe_classifier_candidate_cohort_manifest@0.1.0"
COHORT_KIND = "classifier_candidate_cohort_v1"
RECORD_ORDER = "release_row_order"

RECORD_SCHEMA = "schemas/universe_classifier_candidate_record.schema.json"
MANIFEST_SCHEMA = "schemas/universe_classifier_candidate_cohort_manifest.schema.json"

ADMISSION_RULE = "eligible_or_boundary_from_screen_or_review@1"

#: The only two judgements a classifier may be handed, from either origin.
ADMITTED_STATUSES = ("LIKELY_ELIGIBLE", "BOUNDARY_OR_UNCERTAIN")
ADMITTED_ORIGINS = ("model_screen", "human_review")

#: The release origins a model-screened admission may carry.
MODEL_ORIGINS = ("base_valid", "repaired")
REVIEWED_ORIGIN = "unresolved_after_repair"


@dataclass
class ClassifierCandidateCohortResult:
    cohort_id: str
    cohort_dir: Path | None
    dry_run: bool
    status: str  # "completed" | "dry_run"
    counts: dict
    exclusions: dict
    reconciliation: dict
    manifest_path: Path | None = None


def _pin(manifest_path: Path, expected_sha256: str, *, filename: str, what: str
         ) -> tuple[dict, str]:
    if manifest_path.name != filename:
        raise ScreenInputError(
            f"The {what} manifest must be {filename}; {manifest_path.name} is a "
            "different artifact."
        )
    if not manifest_path.is_file():
        raise ScreenInputError(f"{what} manifest not found: {manifest_path}")
    raw = manifest_path.read_bytes()
    observed = _sha256(raw)
    if observed != expected_sha256:
        raise ScreenInputError(
            f"The {what} manifest hashes to {observed}, but {expected_sha256} "
            "was pinned; this is not the artifact that was admitted."
        )
    return json.loads(_decode_utf8(raw, filename)), observed


def build_classifier_candidate_cohort(
    *,
    repo_root: str | Path,
    release_manifest_path: str | Path,
    release_manifest_sha256: str,
    overlay_manifest_path: str | Path,
    overlay_manifest_sha256: str,
    output_dir: str | Path,
    cohort_id: str,
    clock: Callable[[], datetime],
    dry_run: bool = False,
) -> ClassifierCandidateCohortResult:
    """Admit the classifiable rows of one release plus its human overlay."""
    root = Path(repo_root)
    if not _RUN_ID_RE.match(cohort_id):
        raise ScreenInputError("Invalid cohort id.")
    release_manifest_path = Path(release_manifest_path)
    overlay_manifest_path = Path(overlay_manifest_path)
    release, release_sha = _pin(release_manifest_path, release_manifest_sha256,
                                filename=RELEASE_MANIFEST_FILENAME, what="release")
    require_screen_release(release_manifest_path.parent)
    overlay, overlay_sha = _pin(overlay_manifest_path, overlay_manifest_sha256,
                                filename=OVERLAY_MANIFEST_FILENAME, what="overlay")
    require_human_review_overlay(overlay_manifest_path.parent)

    if overlay["release"]["release_id"] != release["release_id"]:
        raise ScreenInputError(
            f"The overlay reviews release {overlay['release']['release_id']!r}, "
            f"but the release supplied is {release['release_id']!r}."
        )
    if overlay["release"]["manifest_sha256"] != release_sha:
        raise ScreenInputError(
            "The overlay pins a different release manifest digest; it reviewed "
            "other bytes than the release supplied here."
        )
    if not overlay["coverage"]["coverage_is_exact"]:
        raise ScreenInputError(
            "The overlay does not claim exact coverage; an incomplete review "
            "may not decide a cohort."
        )
    release_rows = [
        json.loads(line) for line
        in _decode_utf8((release_manifest_path.parent / RELEASE_RECORDS_FILENAME)
                        .read_bytes(), RELEASE_RECORDS_FILENAME).splitlines()
        if line.strip()
    ]
    decisions_raw = (overlay_manifest_path.parent / OVERLAY_DECISIONS_FILENAME
                     ).read_bytes()
    decisions = {}
    for line in _decode_utf8(decisions_raw, OVERLAY_DECISIONS_FILENAME).splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        key = (record["cik"], record["accession"])
        if key in decisions:
            raise ScreenInputError(
                f"The overlay decides {key} twice; it may not decide a cohort."
            )
        decisions[key] = record
    unresolved = {(r["cik"], r["accession"]) for r in release_rows
                  if r["release_origin"] == REVIEWED_ORIGIN}
    if set(decisions) != unresolved:
        raise ScreenInputError(
            f"The overlay covers {len(decisions)} row(s) but the release left "
            f"{len(unresolved)} unresolved; coverage must be exact."
        )

    records: list[dict] = []
    exclusions = {
        "model_likely_ineligible": 0, "human_likely_ineligible": 0,
        "insufficient_evidence": 0, "model_output_truncated": 0,
        "unresolved_without_admission": 0, "excluded_rows_total": 0,
    }

    def identity(row: dict) -> dict:
        return {
            "record_contract": RECORD_CONTRACT,
            "cik": row["cik"], "accession": row["accession"],
            "company_id": row["company_id"], "form": row["form"],
            "baseline_filing_date": row["baseline_filing_date"],
            "source_id": row["source_id"], "packet_sha256": row["packet_sha256"],
        }

    for row in release_rows:
        origin = row["release_origin"]
        key = (row["cik"], row["accession"])
        if origin in MODEL_ORIGINS:
            status = row["screen_status"]
            if status in ADMITTED_STATUSES:
                records.append({
                    **identity(row),
                    "admission_origin": "model_screen",
                    "screen_status": status,
                    "admission_provenance": {
                        "release_id": release["release_id"],
                        "release_origin": origin,
                        "model_screen": {
                            "raw_response_id":
                                row["release_provenance"]["repair"]["raw_response_id"]
                                if origin == "repaired"
                                else row["release_provenance"]["base"]["raw_response_id"],
                            "raw_response_sha256":
                                row["release_provenance"]["repair"]["raw_response_sha256"]
                                if origin == "repaired"
                                else row["release_provenance"]["base"]["raw_response_sha256"],
                        },
                        "human_review": None,
                    },
                })
            else:
                exclusions["model_likely_ineligible"] += 1
        elif origin == "insufficient_evidence":
            exclusions["insufficient_evidence"] += 1
        elif origin == "model_output_truncated":
            exclusions["model_output_truncated"] += 1
        elif origin == REVIEWED_ORIGIN:
            decision = decisions[key]
            if decision["decision"] in ADMITTED_STATUSES:
                records.append({
                    **identity(row),
                    "admission_origin": "human_review",
                    "screen_status": decision["decision"],
                    "admission_provenance": {
                        "release_id": release["release_id"],
                        "release_origin": origin,
                        "model_screen": None,
                        "human_review": {
                            "overlay_id": overlay["overlay_id"],
                            "reviewer_id": decision["reviewer_id"],
                            "review_protocol_version":
                                decision["review_protocol_version"],
                            "decision_timestamp": decision["decision_timestamp"],
                            "evidence_items": len(decision["evidence"]),
                            "base_failure_reason_code":
                                decision["base_failure_reason_code"],
                            "repair_failure_reason_code":
                                decision["repair_failure_reason_code"],
                        },
                    },
                })
            else:
                exclusions["human_likely_ineligible"] += 1
                exclusions["unresolved_without_admission"] += 1
        else:
            raise ScreenInputError(
                f"Release row {key} carries origin {origin!r}, which this "
                "cohort contract does not know how to admit or exclude."
            )
    exclusions["excluded_rows_total"] = (
        exclusions["model_likely_ineligible"] + exclusions["human_likely_ineligible"]
        + exclusions["insufficient_evidence"] + exclusions["model_output_truncated"])

    by_origin_status: dict[str, dict[str, int]] = {}
    for origin in ADMITTED_ORIGINS:
        by_origin_status[origin] = {
            status: sum(r["admission_origin"] == origin
                        and r["screen_status"] == status for r in records)
            for status in ADMITTED_STATUSES}
    counts = {
        "cohort_rows": len(records),
        "model_screen_admitted": sum(
            r["admission_origin"] == "model_screen" for r in records),
        "human_review_admitted": sum(
            r["admission_origin"] == "human_review" for r in records),
        "by_admission_origin_and_status": by_origin_status,
        "by_screen_status": {status: sum(r["screen_status"] == status
                                         for r in records)
                             for status in ADMITTED_STATUSES},
    }
    if dry_run:
        return ClassifierCandidateCohortResult(
            cohort_id, None, True, "dry_run", counts, exclusions, {})

    validator = Draft202012Validator(_load_schema(root, RECORD_SCHEMA),
                                     format_checker=FormatChecker())
    for row in records:
        errors = sorted(validator.iter_errors(row), key=lambda e: e.json_path)
        if errors:
            raise ScreenInputError(
                f"Built cohort record violates {RECORD_CONTRACT} at "
                f"{errors[0].json_path}: {errors[0].message}"
            )
    records_bytes = "".join(_canonical_line(r) + "\n" for r in records).encode("utf-8")
    release_counts = release["counts"]
    reconciliation = {
        "every admitted row carries an admitted status": all(
            r["screen_status"] in ADMITTED_STATUSES for r in records),
        "every admitted row carries an admission origin": all(
            r["admission_origin"] in ADMITTED_ORIGINS for r in records),
        "the two origins partition the cohort": (
            counts["model_screen_admitted"] + counts["human_review_admitted"]
            == counts["cohort_rows"] == len(records)),
        "status counts sum to the cohort": (
            sum(counts["by_screen_status"].values()) == len(records)),
        "the origin-by-status breakdown sums to the cohort": (
            sum(sum(v.values()) for v in by_origin_status.values()) == len(records)),
        "every model-screened row cites a screen response": all(
            r["admission_provenance"]["model_screen"]
            and r["admission_provenance"]["human_review"] is None
            for r in records if r["admission_origin"] == "model_screen"),
        "every human-reviewed row cites a reviewer and evidence": all(
            r["admission_provenance"]["human_review"]
            and r["admission_provenance"]["human_review"]["evidence_items"] >= 1
            and r["admission_provenance"]["model_screen"] is None
            for r in records if r["admission_origin"] == "human_review"),
        "every human-reviewed row keeps both prior failure reasons": all(
            r["admission_provenance"]["human_review"]["base_failure_reason_code"]
            and r["admission_provenance"]["human_review"]["repair_failure_reason_code"]
            for r in records if r["admission_origin"] == "human_review"),
        "human-reviewed rows come only from unresolved release rows": all(
            r["admission_provenance"]["release_origin"] == REVIEWED_ORIGIN
            for r in records if r["admission_origin"] == "human_review"),
        "model-screened rows come only from validated release rows": all(
            r["admission_provenance"]["release_origin"] in MODEL_ORIGINS
            for r in records if r["admission_origin"] == "model_screen"),
        "no row is admitted twice": (
            len({(r["cik"], r["accession"]) for r in records}) == len(records)),
        "the model admission equals the release's admitted statuses": (
            counts["model_screen_admitted"]
            == sum(release_counts["by_screen_status"][s] for s in ADMITTED_STATUSES)),
        "excluded model rows equal the release's ineligible population": (
            exclusions["model_likely_ineligible"]
            == release_counts["by_screen_status"]["LIKELY_INELIGIBLE"]),
        "carried-through exclusions equal the release's own counts": (
            exclusions["insufficient_evidence"]
            == release_counts["insufficient_evidence"]
            and exclusions["model_output_truncated"]
            == release_counts["model_output_truncated"]),
        "human admissions plus human exclusions equal the reviewed population": (
            counts["human_review_admitted"] + exclusions["human_likely_ineligible"]
            == len(unresolved) == len(decisions)),
        "admitted plus excluded equal the release's planned rows": (
            len(records) + exclusions["excluded_rows_total"]
            == release_counts["planned_rows"]),
        "both sources are byte-unchanged": (
            _sha256(release_manifest_path.read_bytes()) == release_sha
            and _sha256(overlay_manifest_path.read_bytes()) == overlay_sha),
    }
    if not all(reconciliation.values()):
        failed = sorted(k for k, v in reconciliation.items() if not v)
        raise ScreenInputError(
            f"Cohort reconciliation failed; nothing is written. Failed "
            f"identities: {failed}."
        )
    cohort_dir = create_run_directory(output_dir, cohort_id)
    manifest = {
        "manifest_contract": MANIFEST_CONTRACT,
        "cohort_id": cohort_id,
        "cohort_kind": COHORT_KIND,
        "run_timestamp": clock().isoformat(),
        "sources": {
            "release": {
                "release_id": release["release_id"],
                "manifest_sha256": release_sha,
                "records_jsonl_sha256":
                    release["output_hashes"][RELEASE_RECORDS_FILENAME],
            },
            "overlay": {
                "overlay_id": overlay["overlay_id"],
                "manifest_sha256": overlay_sha,
                "decisions_jsonl_sha256":
                    overlay["output_hashes"][OVERLAY_DECISIONS_FILENAME],
            },
            "sources_unmodified": True,
            "no_model_call": True,
        },
        "admission_rule": {
            "rule": ADMISSION_RULE,
            "admitted_statuses": list(ADMITTED_STATUSES),
            "admitted_origins": list(ADMITTED_ORIGINS),
            "human_ineligible_admitted": False,
        },
        "output_contract": RECORD_CONTRACT,
        "output_hashes": {COHORT_RECORDS_FILENAME: _sha256(records_bytes)},
        "record_order": RECORD_ORDER,
        "counts": counts,
        "exclusions": exclusions,
        "reconciliation": reconciliation,
        "schema_versions": {
            "universe_classifier_candidate_record": "0.1.0",
            "universe_classifier_candidate_cohort_manifest": "0.1.0",
            "source_release": release["manifest_contract"],
            "source_overlay": overlay["manifest_contract"],
        },
        "limitations": [
            "This is an admission decision, not a classification. No model "
            "was called and no judgement was formed here.",
            "Model-screened and human-reviewed rows are different kinds of "
            "evidence. The origin is on every row so they need never be "
            "treated as interchangeable.",
            "A row admitted as BOUNDARY_OR_UNCERTAIN is admitted precisely "
            "because it is uncertain; admission is not eligibility.",
            "Rows excluded here are excluded from classification, not judged "
            "ineligible as firms: the truncated and insufficient-evidence "
            "rows remain unknown rather than negative.",
        ],
    }
    _validate(manifest, _load_schema(root, MANIFEST_SCHEMA),
              "Universe classifier candidate cohort manifest")
    try:
        write_bytes_once(cohort_dir / COHORT_RECORDS_FILENAME, records_bytes,
                         what="classifier candidate records")
        write_bytes_once(
            cohort_dir / COHORT_MANIFEST_FILENAME,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            what="classifier candidate cohort manifest")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    return ClassifierCandidateCohortResult(
        cohort_id, cohort_dir, False, "completed", counts, exclusions,
        reconciliation, cohort_dir / COHORT_MANIFEST_FILENAME)


def require_classifier_candidate_cohort(cohort_dir: str | Path) -> Path:
    """Refuse anything that is not a complete classifier-candidate cohort."""
    directory = Path(cohort_dir)
    manifest_path = directory / COHORT_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ScreenInputError(
            f"Directory {directory} holds no classifier-candidate cohort manifest."
        )
    manifest = json.loads(_decode_utf8(manifest_path.read_bytes(),
                                       COHORT_MANIFEST_FILENAME))
    if manifest.get("manifest_contract") != MANIFEST_CONTRACT:
        raise ScreenInputError(
            f"Cohort {directory} declares {manifest.get('manifest_contract')!r}; "
            f"this loader consumes {MANIFEST_CONTRACT!r} only."
        )
    for filename, recorded in manifest["output_hashes"].items():
        target = directory / filename
        if not target.is_file() or _sha256(target.read_bytes()) != recorded:
            raise ScreenInputError(
                f"Cohort output {filename} is missing or no longer hashes to "
                "its manifest entry."
            )
    return manifest_path
