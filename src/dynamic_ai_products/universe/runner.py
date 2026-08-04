"""Local sentinel fixture runner for Stage 00.

Orchestrates the fixture-driven sub-pipeline:

    filer frame -> issuer filters -> evidence packets -> high-recall screen
    -> multi-axis classification -> deterministic tier rules -> review queue
    -> append-only adjudication -> negative audit -> manifest / freeze gates

Only local fixture files are read. No network, no model API, no credential.
Raw inputs are immutable; every output goes to a fresh versioned run
directory that is never overwritten.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .audit import draw_negative_audit_sample
from .classification import (
    ClassificationFailure,
    MockClassificationProvider,
    load_schema_validator,
    validate_classification,
)
from .freeze import (
    FreezeBlockedError,
    attempt_freeze,
    build_run_manifest,
    create_run_directory,
    evaluate_hard_gates,
)
from .io_utils import read_json, sha256_file, sha256_text, write_json, write_jsonl
from .issuer_filters import run_issuer_filters
from .models import (
    AdjudicationRecord,
    BaselineEvidencePacket,
    FirmLineage,
    FirmYearEligibility,
    HistoricalAnnualFiler,
    PacketFailure,
    TierDecision,
    UniverseClassification,
)
from .packets import build_packet
from .review import AdjudicationLog, build_review_case, final_review_state, resolve_queue
from .rules import SampleRules, derive_tier, derive_tier_for_exclusion, derive_tier_for_uncertain
from .screening import (
    MockScreenProvider,
    PROMPT_RELATIVE_PATH,
    ScreenProviderError,
    render_screen_prompt,
    validate_screen_output,
)

INCLUDED_TIERS = {"TIER_A_CORE", "TIER_B_EXTENSION", "TIER_C_BOUNDARY"}

FIXTURE_FILES = {
    "manifest": "fixture_manifest.json",
    "filer_frame": "filer_frame.json",
    "evidence_packets": "evidence_packets.json",
    "screen_outputs": "screen_outputs.json",
    "classification_outputs": "classification_outputs.json",
    "adjudications": "adjudications.json",
    "lineage": "lineage.json",
    "firm_year_events": "firm_year_events.json",
    "negative_audit_results": "negative_audit_results.json",
}

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class FixtureError(ValueError):
    """The fixture bundle is missing files or fails validation."""


@dataclass
class SentinelResult:
    run_id: str
    run_dir: Path | None
    dry_run: bool
    counts: dict[str, int] = field(default_factory=dict)
    tier_by_cik: dict[str, str] = field(default_factory=dict)
    hard_gate_failures: list[str] = field(default_factory=list)
    freeze_status: str = "not_attempted"
    freeze_blockers: list[str] = field(default_factory=list)
    universe_version: str = "unreleased"
    manifest_path: Path | None = None


def _load_fixture_bundle(input_dir: Path) -> dict:
    if not input_dir.is_dir():
        raise FixtureError(f"Fixture input {input_dir} is not a directory.")
    bundle: dict = {}
    for key, filename in FIXTURE_FILES.items():
        path = input_dir / filename
        if not path.exists():
            raise FixtureError(f"Fixture bundle is missing {filename}.")
        bundle[key] = read_json(path)
        bundle[f"{key}_path"] = path
    required = {"baseline_cutoff", "form_scope", "universe_version_on_freeze"}
    missing = required - set(bundle["manifest"])
    if missing:
        raise FixtureError(f"fixture_manifest.json is missing keys: {sorted(missing)}")
    return bundle


def _git_revision(repo_root: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root, capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def run_universe_sentinel(
    *,
    repo_root: str | Path,
    rules_path: str | Path,
    input_dir: str | Path,
    output_dir: str | Path,
    run_id: str,
    seed: int,
    provider: str = "mock",
    dry_run: bool = False,
) -> SentinelResult:
    root = Path(repo_root)
    if provider != "mock":
        raise FixtureError(
            f"Provider {provider!r} is not available in Phase 0. Only the "
            "deterministic 'mock' provider is permitted; real model providers "
            "arrive with the Phase 1 eval harness."
        )
    if not _RUN_ID_RE.match(run_id):
        raise FixtureError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )
    bundle = _load_fixture_bundle(Path(input_dir))
    rules = SampleRules(rules_path)
    baseline_cutoff = date.fromisoformat(bundle["manifest"]["baseline_cutoff"])
    form_scope = list(bundle["manifest"]["form_scope"])
    taxonomy_version = rules_taxonomy_version(root)
    schema_versions = read_json(root / "schemas" / "schema_version_manifest.json")["schemas"]

    # --- 00A: historical annual-filer frame -------------------------------
    filers = [HistoricalAnnualFiler.model_validate(item) for item in bundle["filer_frame"]]
    baseline_candidates: list[HistoricalAnnualFiler] = []
    entrants: list[HistoricalAnnualFiler] = []
    for filer in filers:
        if filer.filing_date is not None and filer.filing_date > baseline_cutoff:
            entrants.append(filer.model_copy(update={"baseline_status": "post_baseline_entrant"}))
        else:
            baseline_candidates.append(
                filer.model_copy(update={"baseline_status": "baseline_candidate"})
            )

    # --- 00B: deterministic issuer filters --------------------------------
    passing, issuer_decisions = run_issuer_filters(baseline_candidates, form_scope)
    passing_ciks = {f.cik for f in passing}
    # Duplicate share-class records are excluded at record level; the firm
    # survives through its retained record and is not firm-level excluded.
    excluded_by_issuer = {
        d.cik: d
        for d in issuer_decisions
        if d.decision == "exclude" and d.cik not in passing_ciks
    }
    unknown_issuer = [d for d in issuer_decisions if d.decision == "unknown"]

    # --- 00C: baseline evidence packets -----------------------------------
    packets: dict[str, BaselineEvidencePacket] = {}
    packet_failures: list[PacketFailure] = []
    packet_fixture: dict = bundle["evidence_packets"]
    for filer in passing:
        result = build_packet(filer, packet_fixture.get(filer.cik, []), baseline_cutoff)
        if isinstance(result, PacketFailure):
            packet_failures.append(result)
        else:
            packets[filer.cik] = result

    # --- 00D: high-recall screen (mock provider) --------------------------
    screen_provider = MockScreenProvider(bundle["screen_outputs_path"])
    prompt_template = (root / PROMPT_RELATIVE_PATH).read_text(encoding="utf-8")
    screens: dict[str, dict] = {}
    screen_records: list[dict] = []
    screen_failures: list[dict] = []
    for filer in passing:
        packet = packets.get(filer.cik)
        if packet is None:
            continue
        prompt = render_screen_prompt(prompt_template, filer, packet)
        raw = None
        try:
            raw = screen_provider.screen(filer, packet, prompt)
            output = validate_screen_output(raw, filer, packet)
        except ScreenProviderError as exc:
            screen_failures.append({"cik": filer.cik, "error": str(exc), "raw": raw})
            continue
        screens[filer.cik] = output.model_dump(mode="json")
        screen_records.append(
            {**output.model_dump(mode="json"), "prompt_hash": sha256_text(prompt)}
        )

    # --- 00E: full classification (mock provider) -------------------------
    classification_provider = MockClassificationProvider(bundle["classification_outputs_path"])
    schema_validator = load_schema_validator(root)
    classifications: dict[str, UniverseClassification] = {}
    classification_failures: list[dict] = []
    for filer in passing:
        packet = packets.get(filer.cik)
        screen = screens.get(filer.cik)
        if packet is None or screen is None:
            continue
        if screen["screen_status"] == "LIKELY_INELIGIBLE":
            continue  # routed to the negative audit, not to classification
        try:
            raw = classification_provider.classify(filer, packet, screen)  # type: ignore[arg-type]
            record = validate_classification(raw, filer, packet, schema_validator)
        except ClassificationFailure as exc:
            classification_failures.append({"cik": filer.cik, "error": str(exc)})
            continue
        classifications[filer.cik] = record

    # --- 00F: deterministic tier derivation -------------------------------
    tier_decisions: dict[str, TierDecision] = {}
    for cik, decision in excluded_by_issuer.items():
        tier_decisions[cik] = derive_tier_for_exclusion(
            cik, decision.company_id, list(decision.reason_codes), rules,
            taxonomy_version, "issuer_filters",
        )
    for decision in unknown_issuer:
        tier_decisions[decision.cik] = derive_tier_for_uncertain(
            decision.cik, decision.company_id, ["unresolved_operating_status"],
            rules, taxonomy_version,
        )
    for failure in packet_failures:
        tier_decisions[failure.cik] = derive_tier_for_uncertain(
            failure.cik, failure.company_id, ["insufficient_baseline_evidence"],
            rules, taxonomy_version,
        )
    for item in screen_failures:
        filer = next(f for f in passing if f.cik == item["cik"])
        tier_decisions[filer.cik] = derive_tier_for_uncertain(
            filer.cik, filer.company_id, ["insufficient_baseline_evidence"],
            rules, taxonomy_version,
        )
    for filer in passing:
        screen = screens.get(filer.cik)
        if screen is None:
            continue
        if screen["screen_status"] == "LIKELY_INELIGIBLE":
            tier_decisions[filer.cik] = derive_tier_for_exclusion(
                filer.cik, filer.company_id, ["NO_CUSTOMER_FACING_DIGITAL_PRODUCT"],
                rules, taxonomy_version, "screen.likely_ineligible_pending_negative_audit",
                provenance="screen_derived",
            )
        elif filer.cik in classifications:
            tier_decisions[filer.cik] = derive_tier(classifications[filer.cik], rules)
        elif filer.cik not in tier_decisions:
            tier_decisions[filer.cik] = derive_tier_for_uncertain(
                filer.cik, filer.company_id, ["insufficient_baseline_evidence"],
                rules, taxonomy_version,
            )

    # --- 00G: boundary review queue + append-only adjudication ------------
    review_cases = [
        build_review_case(decision, classifications.get(cik))
        for cik, decision in sorted(tier_decisions.items())
        if decision.needs_manual_review
    ]
    fixture_adjudications = [
        AdjudicationRecord.model_validate(item) for item in bundle["adjudications"]
    ]
    resolved_cases, open_cases = resolve_queue(review_cases, fixture_adjudications)
    adjudication_by_case = {a.case_id: a for a in fixture_adjudications}
    manual_review_complete = not open_cases

    final_tiers: dict[str, str] = {}
    review_statuses: dict[str, str] = {}
    for cik, decision in tier_decisions.items():
        adjudication = adjudication_by_case.get(f"case-{cik}")
        final_tier, review_status = final_review_state(decision, adjudication)
        final_tiers[cik] = final_tier
        review_statuses[cik] = review_status

    # --- 00H: seeded stratified negative audit ----------------------------
    negatives: list[dict] = []
    filer_by_cik = {f.cik: f for f in filers}
    for filer in passing:
        screen = screens.get(filer.cik)
        if screen is not None and screen["screen_status"] == "LIKELY_INELIGIBLE":
            negatives.append(
                {
                    "cik": filer.cik,
                    "sic": filer.sic,
                    "candidate_customer_value_archetypes": screen[
                        "candidate_customer_value_archetypes"
                    ],
                    "exclusion_reason": "screen_likely_ineligible",
                    "confidence": screen["confidence"],
                }
            )
    for cik, decision in excluded_by_issuer.items():
        negatives.append(
            {
                "cik": cik,
                "sic": filer_by_cik[cik].sic if cik in filer_by_cik else None,
                "candidate_customer_value_archetypes": [],
                "exclusion_reason": (decision.reason_codes or ["unknown"])[0],
                "confidence": "high",
            }
        )
    negative_sample = draw_negative_audit_sample(negatives, seed=seed)

    # Screen-derived exclusions are provisional until every sampled negative
    # has an audit record (ADR-010). Audit results are append-only records.
    audit_results = {str(r["cik"]): r for r in bundle["negative_audit_results"]}
    sampled_ciks = {str(r["cik"]) for r in negative_sample}
    unaudited_ciks = sorted(sampled_ciks - set(audit_results))
    negative_audit_complete = not unaudited_ciks

    # --- firm-year eligibility, lineage, identity table -------------------
    events: dict = bundle["firm_year_events"]
    firm_years: list[FirmYearEligibility] = []
    seen_ciks: set[str] = set()
    for filer in [*passing, *(f for f in baseline_candidates if f.cik not in {p.cik for p in passing}), *entrants]:
        if filer.cik in seen_ciks:
            continue
        seen_ciks.add(filer.cik)
        overrides = events.get(filer.cik, {})
        is_entrant = filer.baseline_status == "post_baseline_entrant"
        tier = final_tiers.get(filer.cik)
        eligible = None if tier in (None, "UNCERTAIN") else tier in INCLUDED_TIERS
        firm_years.append(
            FirmYearEligibility(
                firm_year_id=f"{filer.cik}-{(filer.filing_date or baseline_cutoff).year}",
                company_id=filer.company_id,
                cik=filer.cik,
                observation_date=filer.filing_date or baseline_cutoff,
                annual_accession=filer.accession_number,
                filing_form=filer.form or "unknown",
                universe_class_at_date=tier,  # type: ignore[arg-type]
                operating_status=overrides.get(
                    "operating_status",
                    "shell" if filer.issuer_status_flags.shell_company else "operating",
                ),
                public_status=overrides.get(
                    "public_status", "listed" if filer.exchange else "unknown"
                ),
                entry_type=overrides.get(
                    "entry_type", "new_filer" if is_entrant else "baseline_incumbent"
                ),
                exit_type=overrides.get("exit_type", "none"),
                eligible_this_year=None if is_entrant else eligible,
                primary_incumbent=not is_entrant,
                dynamic_entrant=is_entrant,
                evidence_source_ids=filer.source_ids,
                schema_version=schema_versions["firm_year_eligibility"],
            )
        )
    lineage_records = [
        FirmLineage.model_validate(
            {**item, "schema_version": schema_versions["firm_lineage"]}
        )
        for item in bundle["lineage"]
    ]
    companies = _identity_table(filers, final_tiers, baseline_cutoff, schema_versions["company"])

    # --- processed classifications (derived tier + review state) ----------
    processed: list[dict] = []
    for cik, record in sorted(classifications.items()):
        decision = tier_decisions[cik]
        processed.append(
            record.model_copy(
                update={
                    "candidate_tier": final_tiers[cik],
                    "rule_trace": decision.rule_trace,
                    "sample_rules_version": decision.sample_rules_version,
                    "review_status": review_statuses[cik],
                }
            ).model_dump(mode="json")
        )

    # --- hard gates and freeze --------------------------------------------
    hard_gate_failures = evaluate_hard_gates(
        list(classifications.values()),
        list(tier_decisions.values()),
        set(excluded_by_issuer),
        open_cases,
    )
    unique_ciks = {f.cik for f in filers}
    baseline_firm_ciks = {f.cik for f in baseline_candidates}
    duplicate_records = len(filers) - len(unique_ciks)
    provenance_counts = {"deterministic": 0, "screen_derived": 0, "economic_classification": 0}
    for decision in tier_decisions.values():
        if decision.derived_tier == "EXCLUDED" and decision.exclusion_provenance:
            provenance_counts[decision.exclusion_provenance] += 1
    counts = {
        "filer_records": len(filers),
        "unique_firms": len(unique_ciks),
        "duplicate_records": duplicate_records,
        "baseline_firms": len(baseline_firm_ciks),
        "baseline_candidate_records": len(baseline_candidates),
        "post_baseline_entrants": len(entrants),
        "issuer_excluded": len(excluded_by_issuer),
        "issuer_unknown": len(unknown_issuer),
        "packets_built": len(packets),
        "packet_failures": len(packet_failures),
        "screened": len(screens),
        "screen_failures": len(screen_failures),
        "likely_eligible": sum(
            1 for s in screens.values() if s["screen_status"] == "LIKELY_ELIGIBLE"
        ),
        "likely_ineligible": sum(
            1 for s in screens.values() if s["screen_status"] == "LIKELY_INELIGIBLE"
        ),
        "boundary_or_uncertain": sum(
            1 for s in screens.values() if s["screen_status"] == "BOUNDARY_OR_UNCERTAIN"
        ),
        "classified": len(classifications),
        "classification_failures": len(classification_failures),
        "tier_a": sum(1 for t in final_tiers.values() if t == "TIER_A_CORE"),
        "tier_b": sum(1 for t in final_tiers.values() if t == "TIER_B_EXTENSION"),
        "tier_c": sum(1 for t in final_tiers.values() if t == "TIER_C_BOUNDARY"),
        "excluded": sum(1 for t in final_tiers.values() if t == "EXCLUDED"),
        "excluded_deterministic": provenance_counts["deterministic"],
        "excluded_screen_derived_provisional": provenance_counts["screen_derived"],
        "excluded_economic_classification": provenance_counts["economic_classification"],
        "uncertain": sum(1 for t in final_tiers.values() if t == "UNCERTAIN"),
        "review_cases": len(review_cases),
        "review_cases_resolved": len(resolved_cases),
        "review_cases_open": len(open_cases),
        "negative_audit_pool": len(negatives),
        "negative_audit_sampled": len(negative_sample),
        "negative_audit_completed": len(sampled_ciks & set(audit_results)),
        "negative_audit_pending": len(unaudited_ciks),
    }
    # Reconciliation identities: every record and firm is accounted for.
    reconciliation = {
        "filer_records = unique_firms + duplicate_records":
            counts["filer_records"] == counts["unique_firms"] + counts["duplicate_records"],
        "unique_firms = baseline_firms + post_baseline_entrants":
            counts["unique_firms"] == counts["baseline_firms"] + counts["post_baseline_entrants"],
        "baseline_firms = tier_a + tier_b + tier_c + excluded + uncertain":
            counts["baseline_firms"] == (
                counts["tier_a"] + counts["tier_b"] + counts["tier_c"]
                + counts["excluded"] + counts["uncertain"]
            ),
        "excluded = deterministic + screen_derived_provisional + economic":
            counts["excluded"] == (
                counts["excluded_deterministic"]
                + counts["excluded_screen_derived_provisional"]
                + counts["excluded_economic_classification"]
            ),
        "note": (
            "Post-baseline entrants are stored in the entrant cohort and are "
            "not part of the baseline tier denominator (SPEC-001 core rule 9)."
        ),
    }
    failed_identities = [k for k, v in reconciliation.items() if v is False]
    if failed_identities:
        raise FixtureError(f"Count reconciliation failed: {failed_identities}")

    freeze_status = "blocked"
    freeze_blockers: list[str] = []
    universe_version = "unreleased"
    try:
        attempt_freeze(
            hard_gate_failures=hard_gate_failures,
            open_review_cases=open_cases,
            manual_review_complete=manual_review_complete,
            negative_audit_complete=negative_audit_complete,
            unaudited_negative_ciks=unaudited_ciks,
        )
        freeze_status = "frozen"
        universe_version = str(bundle["manifest"]["universe_version_on_freeze"])
    except FreezeBlockedError as exc:
        freeze_blockers = exc.reasons

    result = SentinelResult(
        run_id=run_id,
        run_dir=None,
        dry_run=dry_run,
        counts=counts,
        tier_by_cik=dict(sorted(final_tiers.items())),
        hard_gate_failures=hard_gate_failures,
        freeze_status=freeze_status,
        freeze_blockers=freeze_blockers,
        universe_version=universe_version,
    )
    if dry_run:
        return result

    # --- write immutable run outputs --------------------------------------
    run_dir = create_run_directory(output_dir, run_id)
    outputs = {
        "historical_annual_filers.jsonl": [f.model_dump(mode="json") for f in filers],
        "issuer_filter_decisions.jsonl": [d.model_dump(mode="json") for d in issuer_decisions],
        "universe_evidence_packets.jsonl": [p.model_dump(mode="json") for p in packets.values()],
        "packet_failures.jsonl": [p.model_dump(mode="json") for p in packet_failures],
        "universe_screen_predictions.jsonl": screen_records,
        "screen_failures.jsonl": screen_failures,
        "universe_classifications_raw.jsonl": [
            r.model_dump(mode="json") for r in classifications.values()
        ],
        "classification_failures.jsonl": classification_failures,
        "tier_decisions.jsonl": [d.model_dump(mode="json") for d in tier_decisions.values()],
        "company_universe_classifications.jsonl": processed,
        "review_queue.jsonl": [
            c.model_dump(mode="json") for c in [*resolved_cases, *open_cases]
        ],
        "negative_audit_sample.jsonl": negative_sample,
        "negative_audit_results.jsonl": [
            audit_results[cik] for cik in sorted(audit_results) if cik in sampled_ciks
        ],
        "firm_year_eligibility.jsonl": [f.model_dump(mode="json") for f in firm_years],
        "firm_lineage.jsonl": [record.model_dump(mode="json") for record in lineage_records],
        "companies.jsonl": companies,
    }
    output_hashes: dict[str, str] = {}
    for filename, records in outputs.items():
        path = write_jsonl(run_dir / filename, records)
        output_hashes[filename] = sha256_file(path)

    adjudication_path = run_dir / "adjudications.jsonl"
    adjudication_path.touch()
    adjudication_log = AdjudicationLog(adjudication_path)
    for record in fixture_adjudications:
        adjudication_log.append(record)
    output_hashes["adjudications.jsonl"] = sha256_file(run_dir / "adjudications.jsonl")

    fixture_bundle_hash = sha256_text(
        "\n".join(
            f"{name}:{sha256_file(bundle[f'{name}_path'])}"
            for name in sorted(FIXTURE_FILES)
        )
    )
    manifest = build_run_manifest(
        repo_root=root,
        run_id=run_id,
        universe_version=universe_version,
        baseline_cutoff=str(baseline_cutoff),
        form_scope=form_scope,
        candidate_frame_hash=sha256_file(bundle["filer_frame_path"]),
        source_manifest_hash=fixture_bundle_hash,
        counts=counts,
        output_hashes=output_hashes,
        hard_gate_status=(
            "pass" if not hard_gate_failures and negative_audit_complete else "fail"
        ),
        manual_review_complete=manual_review_complete,
        negative_audit_seed=seed,
        limitations=[
            "Sentinel run over local synthetic fixtures only.",
            "No SEC EDGAR ingestion; the filer frame is a fixture.",
            "Screen and classification outputs are precomputed mock replays.",
        ],
        code_revision=_git_revision(root),
        model_routes=["mock:deterministic-fixture-replay"],
    )
    manifest_path = write_json(run_dir / "company_universe_manifest.json", manifest)
    write_json(
        run_dir / "run_summary.json",
        {
            "run_id": run_id,
            "counts": counts,
            "count_reconciliation": reconciliation,
            "tier_by_cik": result.tier_by_cik,
            "hard_gate_failures": hard_gate_failures,
            "freeze_status": freeze_status,
            "freeze_blockers": freeze_blockers,
            "negative_audit_complete": negative_audit_complete,
            "unaudited_negative_ciks": unaudited_ciks,
            "universe_version": universe_version,
            "seed": seed,
            "provider": provider,
        },
    )
    result.run_dir = run_dir
    result.manifest_path = manifest_path
    return result


def _identity_table(
    filers: list[HistoricalAnnualFiler],
    final_tiers: dict[str, str],
    baseline_cutoff: date,
    company_schema_version: str,
) -> list[dict]:
    companies: dict[str, dict] = {}
    for filer in sorted(filers, key=lambda f: (f.cik, f.filing_date or date.min)):
        if filer.cik in companies:
            continue
        tier = final_tiers.get(filer.cik)
        if tier in INCLUDED_TIERS:
            status, reason = "included", f"derived_tier={tier}"
        elif tier == "EXCLUDED":
            status, reason = "excluded", "deterministic_or_economic_exclusion"
        else:
            status, reason = "pending", "uncertain_or_entrant"
        companies[filer.cik] = {
            "company_id": filer.company_id,
            "company_name": filer.canonical_name,
            "cik": filer.cik,
            "ticker": filer.ticker,
            "observation_start": str(filer.filing_date or baseline_cutoff),
            "observation_end": str(baseline_cutoff),
            "inclusion_status": status,
            "inclusion_reason": reason,
            "schema_version": company_schema_version,
        }
    return [companies[cik] for cik in sorted(companies)]


def rules_taxonomy_version(repo_root: Path) -> str:
    import yaml

    return str(
        yaml.safe_load(
            (repo_root / "configs" / "universe_taxonomy.yaml").read_text(encoding="utf-8")
        )["taxonomy_version"]
    )
