# Decision Log

## ADR-001 — Clean-room repository

**Decision:** Build the longitudinal project in a new repository without importing legacy artifacts.

**Rationale:** The research question and data structure changed materially. Isolation prevents old scores and taxonomies from steering extraction.

## ADR-002 — Separate extraction from measurement

**Decision:** Product, capability, and task extraction will not score replicability, adoption, or defensibility.

**Rationale:** Measurement assumptions should not determine what observations are preserved.

## ADR-003 — Official, dated sources only for the canonical corpus

**Decision:** Use SEC and official company sources under a fixed hierarchy, with historical snapshots.

**Rationale:** This balances richer product evidence with reproducibility and temporal validity.

## ADR-004 — AI wording is not evidence of depth

**Decision:** AI language identifies candidate passages but does not produce a measurement value without concrete actions and deployment evidence.

## ADR-005 — Task-year is the central measurement level

**Decision:** Aggregate only after task-level validation.

## ADR-006 — No immediate commitment to a single score

**Decision:** Preserve separate measurement families and defer any composite score until pilot construct validation.

## ADR-007 — Multi-axis firm-universe classification

**Decision:** Construct the universe from the historical SEC annual-filer frame and classify firms separately by customer-value archetype, software centrality, complementary dependencies, and firm structure/materiality. Derive Tier A/B/C samples through versioned deterministic rules.

**Rationale:** A binary software label conflates functional software with marketplaces, content catalogues, physical services, hardware systems, and human-managed services. Separate axes preserve economic mechanisms and permit transparent sensitivity samples.

## ADR-008 — Ex-ante baseline cohort and negative audit

**Decision:** Baseline membership uses only pre-cutoff evidence; later outcomes cannot affect inclusion. Post-baseline entrants form a separate cohort, exited incumbents are retained, and a stratified sample of first-pass negatives must be audited before universe freeze.

**Rationale:** These rules reduce post-treatment selection, survivorship bias, and unobserved false-negative screening.

## ADR-009 — Mixed nonseparable firms are not Tier B

**Decision:** `MIXED_SEPARABLE` firms may enter Tier B when the other Tier B conditions hold. `MIXED_NONSEPARABLE` firms may not enter Tier B; they route to the Tier C boundary stratum or remain unresolved in manual review. `universe_sample_rules.yaml` 0.2.0 removes `MIXED_NONSEPARABLE` from the Tier B candidate structures.

**Rationale:** A mixed nonseparable firm can have material product-level software activity, but its firm-level outcomes cannot be cleanly mapped to that activity. Keeping such firms in the extension sample would silently blend unattributable outcomes into mechanism comparisons. The classifier's advisory tier remains non-authoritative.

## ADR-010 — Screen-derived exclusions are provisional until the negative audit completes

**Decision:** Deterministic issuer exclusions (fund, trust, asset-backed, shell/pre-combination SPAC, unsupported form, duplicate record) are definitive when evidenced. A high-recall screen result of `LIKELY_INELIGIBLE` is stored as a provisional, screen-derived exclusion with explicit provenance, enters the stratified negative-audit pool, and cannot be presented as a confirmed exclusion in a frozen universe until its audit record exists. Negative-audit completion is a freeze hard gate.

**Rationale:** The screen is a recall-optimized model pass, not a membership decision. Without an audit gate, first-pass negatives would silently define the sample boundary — the exact failure mode SPEC-001 lists under "prompt output silently defines the sample."

## ADR-011 — Evaluation grain: package-case, assertion, run

**Decision:** An evaluation case is one evaluation invocation of one pipeline stage over one immutable, bounded input packet. Assertions (expected-entity, forbidden-entity, field/value, evidence/provenance, and deterministic-validation expectations) are the atomic scoring units inside a case. The evaluation run is the acceptance-gate unit. Case identity is not universally `stage × company × observation_date`; company, observation date, secondary dates, and frontier-model context are stage-specific typed context fields, optional per case. A single expected entity is never a standalone case. Precision/recall/F1 are computed at the assertion/entity level, exact-set match and completeness at the case level, aggregate metrics and hard gates at the run level. Amends SPEC-022.

**Rationale:** Extraction stages emit sets; recall is only measurable against the full expected set per packet. A universal company/date envelope cannot represent longitudinal matching (two dates) or the frontier registry (no company), and mixing the case and assertion grains leaves partial correctness unmeasurable.

## ADR-012 — Independent immutable evaluation runs

**Decision:** An evaluation case is a versioned test contract, not a production record. Production or fixture outputs are converted by an adapter layer into a canonical prediction envelope that preserves record IDs, source references, prompt/model metadata, and the input-packet hash; the harness never scores raw stage-specific output directly. An evaluation run is a first-class immutable unit, separate from extraction runs, referencing by hash: the prediction run and its manifest, the case-set version, the source/passage registry snapshot, the validator bundle, the scoring/gate config, the code commit, and any model/provider/prompt hashes. Predictions come only from manifest-bearing run artifacts; ad-hoc files must pass through an explicit import producing a manifest'd eval input snapshot. Evaluation reports, assertion results, and diffs are artifacts of the evaluation run, not of the extraction run directory. The canonical eval-run root path is deferred to the repository run-layout decision. Amends the run-directory listing in `docs/methodology/PROMPT_DEVELOPMENT_AND_EVALUATION_PROTOCOL.md`; a successor version of `universe_run_manifest.schema.json` deprecates the run-to-eval linking field `eval_report_ids` (linking direction is eval-run → prediction-run).

**Rationale:** The same prediction set must be re-verifiable with the same case set, re-evaluable under new validator versions, and comparable across case-set versions without re-running extraction. Storing evaluation artifacts inside extraction run directories either breaks run immutability or blocks re-evaluation, and a run manifest cannot know future evaluation IDs without mutation.

## ADR-013 — Gold labels have three orthogonal dimensions

**Decision:** Gold labels are described by `gold_origin` (constructed, human_annotated, imported_reference), `verification_status` (provisional, verified) with `verification_method` as separate metadata (dual_independent_adjudication, solo_blinded_retest, expert_second_review, construction_review), and case-set lifecycle (draft vs frozen), where `frozen` is a property of the versioned case-set snapshot, not of an individual gold record. No single ordered maturity enum. Frozen-test evaluation uses only verified records inside frozen snapshots; gate-bearing adversarial and regression cases must be verified; acceptance metrics used as hard gates are computed only over verified gold, with provisional results reported separately as diagnostics. Every gold assertion carries annotator IDs, timestamps, verification method, adjudication references, source packet hash, case version, change reason, and superseded-by links. Retest intervals live in policy/config, not schemas. Amends SPEC-022.

**Rationale:** Without maturity fields, single-annotator provisional labels silently leak into acceptance metrics — the gold-side counterpart of "unknown over guess." Origin, verification, and lifecycle vary independently; collapsing them into one ladder conflates how a label was produced with how well it was checked and whether its container is released.

## ADR-014 — Case membership is two-dimensional and manifest-based

**Decision:** Case usage membership lives in the versioned case-set manifest, not in case files or directory paths, in two dimensions: exactly one evaluation partition per case per case-set version (`dev`, `frozen_test`; extensible), and zero or more evaluation suites (`adversarial`, `regression`, `smoke`, `boundary`, `schema_validation`). Case records are partition- and suite-agnostic. Membership changes are versioned events carrying previous/new case-set version, case ID, partition/suite deltas, reason code, change-request or adjudication reference, actor, and timestamp. Promote-to-regression adds suite membership without changing partition and without auto-verifying. Directories under `evals/` are authoring/fixture organization only. Amends SPEC-022 (removes the required `split` case field) and SPEC-025 (`promote_to_regression` semantics).

**Rationale:** Adversarial and regression are roles a case can hold simultaneously while sitting in either partition; a single mutually exclusive split axis cannot express that. Encoding membership in file locations conflicts with immutable frozen snapshots and with the audit trail movement events require.

## ADR-015 — Frozen-set discipline through logged exposure

**Decision:** Frozen case-set snapshots are immutable; membership and exposure changes exist only as append-only events plus new case-set versions. Exposure is typed (aggregate_metrics_view, case_prediction_view, gold_detail_view, source_packet_view, adjudication_view) and every event records scope, purpose code, actor, timestamp, candidate reference, and disposition. Frozen-test evaluation runs are restricted to predeclared purposes (release_candidate_evaluation, baseline_establishment, reproducibility_check, approved_regression_diagnosis) and are always logged; per-cycle candidate/run budgets live in policy/config. Case-level frozen detail requires a recorded purpose; console, CLI, and review APIs route through the same access-control/exposure contract, and reports default to aggregates. A case whose prediction or gold detail was inspected during tuning or diagnosis is marked ever-exposed, moves to the dev partition in the next case-set version, and can never again serve as a blind frozen case. Post-release error analysis counts as exposure for future tuning. The methodology owner's authority is never silent: self-approval does not substitute for the append-only record.

**Rationale:** In a solo-researcher setting no external referee exists; the realistic protection is not making violations impossible but making unrecorded access impossible in the normal workflow. Repeated candidate selection against a fixed frozen set is leaderboard overfitting even when only aggregates are viewed, so frozen use itself must be purpose-bound and counted.

## ADR-016 — Screening error costs are asymmetric and separately gated

**Decision:** The high-recall screen decides only whether a firm can be safely excluded on its evidence packet; outcomes preserve `screen_negative`, `screen_nonnegative`, and `unresolved/insufficient_evidence` (never auto-negative). The primary scientific estimand is the weighted unsafe-exclusion (false-omission) rate P(actually eligible-or-boundary-relevant | screen_negative), estimated from the seeded, stratified negative audit; its confidence upper bound is the hard gate, with the target-label definition, audit snapshot hash, strata, sampling design and weights, estimator, CI method, confidence level, and thresholds pinned in versioned scoring/gate config. Reports give rate and absolute missed-firm estimates, per-stratum results with an `insufficient_audit_evidence` finding when minimum audit evidence is unmet, and stratum-concentration guardrails. Firms passing the screen but excluded downstream are pass-through burden, measured by operational metrics (pass-through rate, review volume, workload, unresolved share), never labeled a false-positive rate; capacity pressure never loosens the unsafe-exclusion gate. Precision-like metrics and F1 are diagnostics only. Audit labels backing the hard gate must be verified gold drawn from a frozen screen-output snapshot. Mechanizes ADR-010 in the evaluation harness.

**Rationale:** A wrongly excluded firm permanently biases the universe and cannot be caught downstream; a wrongly passed firm costs only review capacity. A single symmetric score hides exactly this asymmetry, and unweighted audit proportions are invalid under stratified sampling.

## ADR-017 — Axis-native classification metrics and deterministic tier contract

**Decision:** Each classification axis declares its metric type (multi_label, nominal_single_label, ordinal_single_label, structured_set, abstention_allowed) and is scored with the matching family: per-label and macro/micro P/R/F1 with exact-set match as diagnostic for multi-label axes; confusion matrices, per-class P/R, macro F1, and balanced accuracy for nominal axes; distance-sensitive error, mean absolute ordinal distance, and weighted kappa for ordinal axes. UNKNOWN, OTHER, and NOT_APPLICABLE are distinct; gold carries evidence-resolvability; abstention quality is measured by coverage, selective risk, unnecessary abstention, false confidence, and correct abstention, and UNKNOWN→confident transitions are classified as beneficial resolution, false-confidence regression, or unsupported confidence. Classification errors are additionally assessed for tier consequence under the fixed tier-rule version, with directional severities in versioned config. Deterministic tier derivation is tested as a 100% contract (exact tier, reason codes, rule traces, repeatability) where any deviation is a defect, separately from end-to-end tier agreement whose mismatches are attributed to rule-engine defects, upstream classification, or screen exclusion. Conditional and end-to-end views are reported together; screen-excluded firms keep the terminal outcome NOT_CLASSIFIED_DUE_TO_SCREEN_EXCLUSION instead of leaving denominators. Hard gates use verified gold only, and low-support slices yield `insufficient_evaluation_evidence` rather than passing. Amends the evaluation-metric contracts referenced by SPEC-020 and SPEC-022.

**Rationale:** One aggregate accuracy lets axes compensate for one another and hides rare but tier-consequential confusions such as MIXED_SEPARABLE↔MIXED_NONSEPARABLE (ADR-009). Granting statistical tolerance to a deterministic rule layer buries code defects in metric noise, and dropping screen-excluded firms from end-to-end denominators produces survivorship bias.

## ADR-018 — Findings are immutable; humans add dispositions; resolution requires re-runs

**Decision:** A validator finding is the immutable, reproducible result of a specific validator bundle and rule on a specific artifact, with full provenance. Humans never modify, delete, or flip findings; they append typed dispositions (confirmed_defect, suspected/confirmed_validator_false_positive, source_snapshot_defect, prediction_artifact_defect, gold_or_case_defect, policy_or_rule_mismatch, accepted_nonblocking_risk, duplicate_finding, needs_investigation) with rationale and links. Resolution happens only by producing a new version of the faulty component (prediction, source snapshot, gold/case-set, validator bundle, or scoring/gate config) and a new immutable evaluation run. Critical findings are never waived per case, and release exceptions are never modeled as validator waivers — they follow the run-level governance path in ADR-019. `accepted_nonblocking_risk` applies only to warning/info severities; severity itself is versioned configuration, not a per-case judgment. Gate computation uses only raw unresolved blocking findings; disposition-enriched review views never replace raw views. Repairs are append-only with supersedes/derived_from links. Findings follow the lifecycle open → dispositioned → remediation_pending → resolved_by_rerun/superseded/unresolved. Amends SPEC-023 and SPEC-025.

**Rationale:** Per-case waivers erode hard gates — in a solo setting a "just this once" door is unauditable. Routing every correction through a new component version applies the fix corpus-wide, keeps it testable and reversible, and cleanly separates mechanical fact production (validators) from semantic judgment (humans).

## ADR-019 — Layered acceptance with four chained state vocabularies

**Decision:** Prompt acceptance runs through ordered layers that later layers can never compensate: (0) evaluation validity — execution status `completed`/`invalid`/`errored`, where invalid or errored evaluations produce no verdict about the candidate; (1) non-negotiable behavioral invariants, lexicographically prior to all metrics, where the protected condition is wrong or unsupported confidence rather than "UNKNOWN decreased"; (2) versioned metric and regression gates computed on verified gold with verdicts `pass`/`fail`/`indeterminate` (low support is indeterminate, never auto-pass/fail), under an explicit baseline-comparability contract covering case set, gold, registries, validator bundle, scoring config, and model/provider/runtime; (3) human review (accept_candidate, accept_with_documented_nonblocking_tradeoff, revise, reject) that can never convert a blocking fail or promote an indeterminate result. Frozen regression accounting uses a case-level ledger; one verified new regression in a protected class can block, and improvements never offset protected regressions. Release exceptions are separate governance records — the eval verdict stays `fail` — and `conditional_pass` is removed from the verdict vocabulary. Four vocabularies remain distinct and chained: execution status → gate verdict → review decision → prompt lifecycle (draft, candidate, accepted, frozen, deprecated), with every transition a separate provenance-bearing event. Amends SPEC-020, SPEC-024, `schemas/evaluation_result.schema.json` (via version increment), and `evals/CHANGE_CONTROL_PROTOCOL.md`.

**Rationale:** An invalid evaluation is not a bad prompt; conflating them poisons both diagnosis and records. Merging the four vocabularies invites states like `conditional_pass` that let partial failures masquerade as qualified releases, and post-hoc tolerance judgments on small frozen sets are exactly how hard gates erode.

## ADR-020 — Assertion-level regression primitive and immutable comparison artifacts

**Decision:** The regression primitive is a comparable assertion outcome transition satisfied → unsatisfied under an explicit comparison contract, keyed by stable case ID, stable assertion ID, assertion semantic version, gold/case-set version, matcher/scoring version, and evaluation-contract hash. Assertion outcomes are satisfied, unsatisfied, indeterminate, not_applicable, and not_evaluated, with named transition classes (including coverage_or_certainty_degradation for satisfied → indeterminate). Changed gold, changed packets, changed validator semantics, or added/removed assertions produce explicit noncomparability classes, never silent regressions; failures without a comparable baseline are `new_failure_without_comparable_baseline` (still able to fail current gates), with bridge baselines preferred when contracts change. Baselines are versioned roles (current_frozen_prompt, accepted_release, previous_candidate, model_upgrade_baseline, validator_bridge_baseline, reproducibility_baseline) fixed before candidate results are seen. The case-level ledger is derived from assertion outcomes (newly_failing, newly_passing, degraded_but_still_passing, degraded_and_still_failing, improved_but_still_failing, unchanged, indeterminate, noncomparable, added_case, removed_case; additional_protected_regression for already-failing cases). Protected regression classes bind to versioned assertion metadata. The comparison is a separate immutable, deterministic artifact with its own ID, manifest, execution status, and verdict, referencing both eval runs by hash; identical inputs must reproduce an identical output hash. Report dimensions use partition/suite terminology. Amends SPEC-024.

**Rationale:** Case-level flips lose partial degradation and force protected-class accounting onto coarse labels; metric deltas alone cannot satisfy the protocol's fixed/regressed case listing. Writing comparisons into either eval run directory would mutate immutable runs, and post-hoc baseline selection is a form of results shopping.

## ADR-021 — Contract-bound qualification with predeclared requalification scopes

**Decision:** Qualification binds to prompt artifact × execution/routing contract × stage/output contract. There is no prompt-centric acceptance and no acceptance inheritance across execution-affecting contract changes; old qualification records remain historically valid but never transfer. Requalification scope is risk-based and fixed by a versioned change-classification policy before candidate results are seen: major behavioral changes (provider, model family/snapshot, tool permissions, routing/fallback policy, pre/post-processing or output-contract semantics) require full requalification including the frozen release gate and a model-upgrade bridge; bounded behavioral changes receive predeclared scoped requalification; non-behavioral metadata changes require none. Each change class predefines required partitions, suites, bridge arms, frozen-gate requirement, minimum verified support, and the qualification scope granted (qualified_for_development, qualified_for_shadow_or_pilot, qualified_for_release). Model-change bridges use old-prompt×old-contract, old-prompt×new-contract, and new-prompt×new-contract arms (optionally new-prompt×old-contract). Silent provider drift is handled by sentinel monitoring and requalification events; declared routing bundles are evaluable contracts, and undeclared fallback is contamination. Amends SPEC-024 and the accepted-prompt registry definition in `docs/methodology/PROMPT_DEVELOPMENT_AND_EVALUATION_PROTOCOL.md`.

**Rationale:** Prompts are tuned to model behavior; acceptance that survives a model change silently converts run-manifest model fields into decoration and invalidates the evidence behind the acceptance. Deciding requalification depth after seeing results would make the evaluation plan adaptive — the failure mode the harness exists to prevent.

## ADR-022 — Default-deny adapter governance with staged rollout

**Decision:** Adapter capability is governed by four distinct states — adapter_available (code exists), adapter_qualified (passed gates under a specific execution contract), adapter_enabled (permitted for an environment and rollout scope via a versioned enablement record), and run_authorized (a specific external-call run with predeclared budget and scope) — in the chain implemented → qualified → enabled → authorized → executed and audited. Enablement records bind stage, adapter, contract hashes, environment, rollout scope, permitted partitions/suites, qualification reference, endpoint allowlist, budget and rate policies, approver, effective/expiry dates, and supersedes links; contract changes never inherit enablement. External source adapters and model execution adapters have separate readiness and safety gates. Rollout proceeds mock_only (default) → live_dev (dev partition only, low budgets, manual authorization) → controlled_pilot (predeclared cohort in a separate design document; cohort size never hardcoded in schema or policy) → release/research production → full scale, with each transition an append-only enablement event. Frozen partitions are never used in live_dev. Live calls run only through the canonical runner with pre-call and post-call provenance, raw-before-parse archival, canonical request fingerprints for idempotent resume, budget/circuit-breaker limits, and secret-manager credentials behind an explicit `--live` authorization; ad-hoc SDK calls are noncanonical experiments requiring separate approval and never enter production or evaluation records. Enablement is suspendable and revocable. Phase 1 implements only the data models, readiness contracts, mock runner, budget config, and default-deny enforcement; live adapter implementation and enablement is a later explicit phase, and completing the harness never auto-enables live calls. Governs SPEC-003/004/005 ingestion adapters and the Phase 4 integration in `docs/implementation/EVAL_HARNESS_BUILD_PLAN.md`.

**Rationale:** This is the adapter counterpart of "no premature scale": one global switch would open unready stages alongside ready ones, and ad-hoc transitions would break manifest discipline on day one. Paid, non-idempotent external calls need budget, provenance, and authorization decided before execution, not after.

## Open decisions

- Exact baseline cutoff, first-release form scope, and final Tier A/Tier B thresholds after the universe sentinel.
- Filing-date versus fiscal-year observation convention.
- Required source packet by firm-year.
- Frontier-registry granularity.
- Gold-set size and expert-review protocol.
- Whether third-party sources receive a bounded validation-only role.
- Canonical eval-run root path (align with the repository run-layout decision; see ADR-012).
- Numeric gate thresholds, frozen-run budgets, and retest intervals (live in versioned scoring/gate/policy configs; see ADR-013, ADR-015, ADR-019).
- Protected-class taxonomy enumeration and change-classification policy contents (see ADR-020, ADR-021).
- Pilot cohort design document (see ADR-022).
