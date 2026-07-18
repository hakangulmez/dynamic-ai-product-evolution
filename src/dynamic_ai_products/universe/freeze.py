"""Stage 00I hard gates, run manifest, and freeze control.

The manifest is validated against `schemas/universe_run_manifest.schema.json`.
A freeze is refused while any hard gate fails or any critical review case is
open. A rerun never overwrites a prior run directory.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

from .io_utils import sha256_file
from .models import BoundaryReviewCase, TierDecision, UniverseClassification

MANIFEST_SCHEMA_RELATIVE_PATH = Path("schemas/universe_run_manifest.schema.json")


class FreezeBlockedError(RuntimeError):
    """The universe cannot be frozen; reasons list every blocking condition."""

    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def evaluate_hard_gates(
    classifications: list[UniverseClassification],
    tier_decisions: list[TierDecision],
    issuer_excluded_ciks: set[str],
    open_review_cases: list[BoundaryReviewCase],
) -> list[str]:
    """Return the list of hard-gate failures (empty means all gates pass)."""
    failures: list[str] = []
    tiers_by_cik = {d.cik: d for d in tier_decisions}

    for record in classifications:
        for evidence in record.evidence:
            if not evidence.quote.strip():
                failures.append(f"empty evidence quote for {record.cik}")
        if record.baseline_filing_date > record.baseline_cutoff:
            failures.append(f"temporal leakage in classification for {record.cik}")
        decision = tiers_by_cik.get(record.cik)
        included = decision is not None and decision.derived_tier in {
            "TIER_A_CORE",
            "TIER_B_EXTENSION",
            "TIER_C_BOUNDARY",
        }
        if included and not record.evidence:
            failures.append(f"evidence-free inclusion for {record.cik}")

    for decision in tier_decisions:
        if decision.derived_tier == "TIER_A_CORE" and decision.cik in issuer_excluded_ciks:
            failures.append(f"issuer-excluded firm in Tier A: {decision.cik}")

    seen: set[str] = set()
    for decision in tier_decisions:
        if decision.cik in seen:
            failures.append(f"duplicate CIK in tier decisions: {decision.cik}")
        seen.add(decision.cik)

    for case in open_review_cases:
        failures.append(f"unresolved review case {case.case_id}")

    return failures


def build_run_manifest(
    *,
    repo_root: str | Path,
    run_id: str,
    universe_version: str,
    baseline_cutoff: str,
    form_scope: list[str],
    candidate_frame_hash: str,
    source_manifest_hash: str | None,
    counts: dict[str, int],
    output_hashes: dict[str, str],
    hard_gate_status: str,
    manual_review_complete: bool,
    negative_audit_seed: int | None,
    limitations: list[str],
    code_revision: str | None,
    model_routes: list[str],
) -> dict:
    """Assemble and schema-validate the immutable run manifest."""
    root = Path(repo_root)
    schema_versions = json.loads(
        (root / "schemas" / "schema_version_manifest.json").read_text(encoding="utf-8")
    )["schemas"]
    import yaml

    taxonomy_version = str(
        yaml.safe_load((root / "configs" / "universe_taxonomy.yaml").read_text())["taxonomy_version"]
    )
    sample_rules_version = str(
        yaml.safe_load((root / "configs" / "universe_sample_rules.yaml").read_text())["rules_version"]
    )
    manifest = {
        "run_id": run_id,
        "universe_version": universe_version,
        "baseline_cutoff": baseline_cutoff,
        "form_scope": form_scope,
        "candidate_frame_hash": candidate_frame_hash,
        "source_manifest_hash": source_manifest_hash,
        "code_revision": code_revision,
        "packet_builder_version": _package_version(),
        "screen_prompt_hash": sha256_file(root / "prompts/discovery/universe_high_recall_screen.md"),
        "classification_prompt_hash": sha256_file(
            root / "prompts/discovery/universe_full_classification.md"
        ),
        "model_routes": model_routes,
        "taxonomy_version": taxonomy_version,
        "sample_rules_version": sample_rules_version,
        "schema_versions": schema_versions,
        "negative_audit_seed": negative_audit_seed,
        "eval_report_ids": [],
        "manual_review_complete": manual_review_complete,
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
        "hard_gate_status": hard_gate_status,
        "limitations": limitations,
        "output_hashes": output_hashes,
    }
    schema = json.loads((root / MANIFEST_SCHEMA_RELATIVE_PATH).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(manifest), key=lambda e: e.json_path)
    if errors:
        details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
        raise ValueError(f"Run manifest violates the canonical schema: {details}")
    return manifest


def _package_version() -> str:
    from . import PACKET_BUILDER_VERSION

    return PACKET_BUILDER_VERSION


def attempt_freeze(
    *,
    hard_gate_failures: list[str],
    open_review_cases: list[BoundaryReviewCase],
    manual_review_complete: bool,
    negative_audit_complete: bool,
    unaudited_negative_ciks: list[str] | None = None,
) -> None:
    """Raise FreezeBlockedError listing every blocking condition."""
    reasons: list[str] = []
    reasons.extend(f"hard gate failed: {failure}" for failure in hard_gate_failures)
    if open_review_cases:
        reasons.append(
            f"{len(open_review_cases)} unresolved critical review case(s): "
            + ", ".join(sorted(c.case_id for c in open_review_cases))
        )
    if not manual_review_complete:
        reasons.append("manual review is not complete")
    if not negative_audit_complete:
        pending = ", ".join(sorted(unaudited_negative_ciks or [])) or "unknown"
        reasons.append(
            "negative audit is not complete; screen-derived exclusions remain "
            f"provisional (unaudited: {pending})"
        )
    if reasons:
        raise FreezeBlockedError(reasons)


def create_run_directory(output_dir: str | Path, run_id: str) -> Path:
    """Create the versioned run directory; refuse to reuse an existing one."""
    run_dir = Path(output_dir) / run_id
    if run_dir.exists():
        raise FileExistsError(
            f"Run directory {run_dir} already exists. Runs are immutable; "
            "choose a new --run-id instead of overwriting."
        )
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir
