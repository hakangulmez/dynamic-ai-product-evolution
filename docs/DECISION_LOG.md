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

## ADR-023 — Per-case input-packet comparability and comparison manifest v0.2

**Decision:** The `changed_input_packet` noncomparability class binds to the authoritative per-case input-packet identity `(case_id, input_packet_hash)` from the evaluation run's `CaseSetManifest` membership, not to `prediction_run_manifest_hash`. The prediction-run manifest hash conflates prediction-run identity, prompt/model metadata, prediction outputs, and packet hashes; it remains provenance identity only and is not a comparability axis.

A comparison receives explicit immutable baseline and candidate comparison-scoped input-packet snapshots. Each snapshot contains the case-set version and hash, registry snapshot hash, sorted unique `(case_id, input_packet_hash)` entries, and a deterministic aggregate input-packet-set hash, and each snapshot is independently bound to its corresponding `EvaluationRunManifest`.

Run-level classification precedence is:

1. differing registry snapshot → `changed_gold`;
2. differing case-ID membership → `changed_gold`;
3. equal membership with any differing per-case `input_packet_hash` → `changed_input_packet`;
4. residual case-set version or hash difference → `changed_gold`;
5. changed validator or scoring contract → `changed_validator_contract`;
6. assertion-contract and remaining contract incompatibilities → `noncomparable_contract`;
7. otherwise ordinary transition classification.

A differing `prediction_run_manifest_hash` alone produces no noncomparability. The `validator_bridge_baseline` role provides no role-based comparability bypass.

`comparison_manifest` advances from `0.1.0` to `0.2.0`. Its `ComparisonRunReference` gains an `input_packet_set_hash` that is required for completed run references, persisted for both sides, and included in the deterministic comparison output hash. `assertion_transition`, `case_ledger_entry`, and `assertion_comparison_metadata` remain at `0.1.0`. `evaluation_run_manifest@0.1.0` is unchanged.

Existing `comparison_manifest@0.1.0` artifacts remain readable without migration. `load_comparison` dispatches on the explicit persisted comparison-contract version to retained read-only V1 shape models. Renaming a Pydantic model changes its generated JSON Schema title and nested `$defs`/`$ref` names and therefore does not reproduce the historical model-contract hash. Accordingly, the V1 models are used for strict historical shape validation, while the loader validates the persisted `contract.contract_hash` and `comparison_contract_hash` against the governed historical constant `ef1508e4e2ed06c1cbcaafaf3d30bb9cc6c88e72d1df0bf001c7315e5afb94f4`. V1 artifacts retain their original verdicts, transition ledgers, case ledgers, and output hashes under the V1 hash algorithm and are never rewritten or implicitly migrated.

New comparisons are always `comparison_manifest@0.2.0` and require explicit input-packet snapshots. The correction is implemented as a dedicated Slice 11 corrective amendment before Slice 12 is staged.

This decision amends ADR-020 and SPEC-024.

**Rejected alternatives:** Continuing to use `prediction_run_manifest_hash` as packet identity was rejected because it conflates model, prompt, output, and input identity and makes valid model or bridge comparisons falsely noncomparable. A `validator_bridge_baseline` role-based bypass was rejected because a caller-declared role cannot prove packet equality and would conceal genuine changed inputs. Requiring identical prediction manifests was rejected because it contradicts comparison of distinct prediction sets. Collapsing packet changes into `changed_gold` was rejected because it removes the governed distinction between changed gold and changed input packets. Passing an unpersisted comparison-only input hash was rejected because it prevents independent later auditability. Claiming that renamed V1 Pydantic models regenerate the historical contract hash was rejected because direct schema and hash probes disproved it.

## ADR-024 — Phase-1 semantic-substrate ownership and stage-general evaluation

**Decision:** Phase 1 is a stage-general evaluation harness. The committed Slices 1–12 are a contract-and-plumbing layer that deliberately defers the actual semantic evaluation to caller-supplied inputs (`assertions.py` copies a caller-supplied `ResolvedAssertionEvaluation.outcome`; `validators.py` consumes a caller-supplied `ValidationArtifactSnapshot`; `metrics.py` consumes a caller-supplied metric-input snapshot). Those semantic producers were owned by no slice — a build-plan ownership defect. This ADR inserts a governed prerequisite slice-set **12A–12M** between Slice 12 and Slice 13. Slice 13 remains the canonical runner/report/CLI orchestration layer only; it receives governed artifact references and invokes the semantic producers internally. Prebuilt `ResolvedAssertionEvaluation`, `ValidationArtifactSnapshot`, and `MetricInputSnapshot` objects are never public runner inputs, and no semantic producer lives in `runner.py`. Slices 1–12 are not renumbered; Slice 14 remains the final Phase-1 release-binding slice.

The substrate governs strict, frozen, extra-forbid, versioned, deterministically persisted contracts (model-contract hashing and canonical bytes unless a committed static schema already governs the source artifact): stage-profile registry, source/passage snapshot manifest, parsed prediction content, semantic-adapter registry, gold assertion set, axis taxonomy, validator-rule parameters, validator-bundle artifact, validation-artifact snapshot set, stage metric evidence set, metric-input snapshot, `metric_report@0.2.0`, and evaluation-output manifest. Parsed prediction content is a derived output (not a run input); its provenance and read-back hash are bound through the run and output artifacts. Gold is assertion-owned (keyed by case ID, assertion ID, assertion version/hash, resolved target reference) and separate from the target registry, which keeps its identity and alias ownership; no parallel `expected_entities`/`forbidden_entities` channel is reintroduced.

Metric-family applicability is derived deterministically from the hash-bound stage-profile registry, never from arbitrary booleans. Inapplicable metric families produce no `MetricDatum`; they carry an explicit applicability-ledger entry in `metric_report@0.2.0`, distinct from computed zero, low-support `indeterminate`, pass, and fail. A gate targeting an inapplicable family raises `GateApplicabilityBindingError` before datum selection (a binding error, not a verdict). The committed `metric_report@0.1.0` (`d9e3f6d7399af628b38754758a7cb580e57955ad695ee7d92fb56c67c4ceac39`) is preserved read-only.

Deterministic validation runs before semantic assertion evaluation; `deterministic_validation` assertions consume the persisted validator findings. Exactly one `ValidatorRuleParameterEntry` per rule in `VALIDATOR_RULE_ORDER` owns `rule_id`, canonically ordered unique `dependency_rule_ids` and `blocking_reason_codes`, and exactly four canonically ordered `stage_parameters` (`capability_extraction`, `task_extraction`, `universe_screen`, `universe_classification`) as a discriminated applicable/inapplicable union; the complete per-rule hash binds rule ID, dependencies, blocking reasons, and all four stage entries (excluding its own field) and equals `ValidatorRuleConfig.rule_params_hash`, with an aggregate parameter-set hash over the twelve canonical entries. Stage/payload models are module-private. Rule 1 applicable static-schema payloads bind `output_schema_id`, repository-relative reference, and `output_schema_sha256`; `universe_screen` has no static schema and binds the versioned adapter output contract `universe_screen_output@0.1.0` in Rules 1 and 2.

Validator coverage is one record per rule in canonical order with `fully_evaluated`, `partially_evaluated`, `inapplicable`, and `blocked_by_dependency` states plus candidate, evaluated-observation, blocked-candidate, and governed reason counts; validator metric denominators use the evaluated-observation count only; no dummy or blanket-passing observation is permitted. For Rules 5/6, an unresolved cited passage/source is a completed-run prediction defect that blocks that candidate and makes the evidence-provenance assertion `unsatisfied` but does not invalidate the run; a resolved source lacking its governed publication date invalidates the source snapshot and run. Rule 12 has exactly one candidate and is always fully evaluated after valid parsed content loads (no inapplicable or blocked state) and directly verifies raw-output preservation and repair reference/hash provenance; unloadable, hash-mismatched, malformed, or contract-invalid parsed content invalidates the run before validation-snapshot production. `ValidatorFinding@0.1.0` (`96f63fee300d363a662f4f956bacccdca596acfb0f22bf7039aa1335b6d61292`) is preserved byte-identical.

Semantic-outcome determination is a three-phase process, not flat numeric precedence: **Phase A** an aggregate input-validity gate that collects every applicable sanitized issue (missing/unresolvable required registry, config, gold, taxonomy, or semantic input; conflicting reference definitions; unsupported contract version; unloadable/hash-mismatched/contract-invalid required artifact; incomplete validation-snapshot structure; missing/inconsistent deterministic-validation coverage) and, if any exists, sets `execution_status = invalid`, leaves affected assertions not evaluated, and persists every issue in deterministic order; **Phase B** per-assertion semantics (governed applicability → `not_applicable`; incomplete required collection → `indeterminate`; then expected/forbidden entity, field-value operator, and evidence-provenance semantics, where source-resolution, passage-resolution, and quote-containment defects accumulate and any such defect makes the assertion `unsatisfied`); **Phase C** deterministic-validation mapping from coverage and relevant findings. The invalid-run artifact policy persists the run manifest and `EvaluationResultV2` without a gate verdict and validator findings produced before invalidation; assertion material exists only as explicitly-marked partial artifacts, never as completed `not_evaluated` outcomes, and no completed assertion-outcomes artifact, metric report, or gate verdict is produced. Slice 12M is a pre-runner integration proof over a dedicated coherent `capability_extraction` fixture bundle that constructs, persists, reloads, and hash-verifies the full producer chain through public APIs with no prebuilt-snapshot shortcut and no provider call.

This decision amends SPEC-020, SPEC-022, SPEC-023, and the build plan, and is applied through prerequisite Slices 12A–12M before Slice 13.

## ADR-025 — Evaluation-run-manifest v0.2 semantic-input binding

**Decision:** `evaluation_run_manifest` advances from `0.1.0` to `0.2.0` as the authoritative binding point for immutable pre-execution semantic inputs. Version `0.2.0` pins, in addition to the existing prediction-run, case-set, target-registry, scoring/gate-config, code-commit, and runtime identities: a caller-supplied RFC3339 `evaluation_created_at` (validated and persisted at run initialization, copied verbatim into validation snapshots and validator findings, never clock-read by a producer or inferred from `eval_run_id`); stage-profile registry version/hash and selected-entry hash; semantic-adapter registry version/hash and selected-entry hash; source/passage snapshot version/hash; gold assertion-set version/hash; axis-taxonomy version/hash; validator-rule-parameters version/hash; validator-bundle version/hash; and applicable stage-evidence version/hash (absent for extraction stages). The ambiguous `registry_snapshot_hash` is not overloaded; each semantic input is a distinct field. Parsed prediction content is a derived output bound through the evaluation-output manifest, not a pre-execution run-manifest input.

Historical `evaluation_run_manifest@0.1.0` (`7f8909d8e7059952c933c8e30f43044178b3f8a21d4baaa77bfb5c786b38d6ee`) remains readable through a governed frozen-shape historical model and constant; v0.1 documents are never rewritten and v0.2-only semantic identities are never retrofitted into them. A comparison whose two sides differ in manifest version (v0.1 vs v0.2) is `noncomparable_contract`. The comparator consumes v0.2 bindings and maps a changed target-registry, gold assertion-set, axis-taxonomy, or applicable stage-evidence hash to `changed_gold`; a changed selected stage-profile entry identity/hash to `noncomparable_contract` (it changes metric-family applicability and/or required stage evidence); a changed selected semantic-adapter entry identity/hash to `noncomparable_contract`; a changed validator-bundle or validator-rule-parameters hash to `changed_validator_contract`; consumed source/passage byte changes through the authoritative per-case input-packet hash to `changed_input_packet`; a global source/passage snapshot difference with identical consumed per-case packets to provenance-only; and `prediction_run_manifest_hash` to provenance-only. A changed stage-profile registry version/hash whose selected entry identity/hash is identical, and a changed semantic-adapter registry version/hash whose selected adapter entry identity/hash is identical, are provenance-only for pairwise comparison; provenance-only here describes only pairwise run-comparison classification and is not a change-control exemption — registry edits still require normal governed version/hash updates and review. The existing noncomparability vocabulary suffices and no new `NoncomparabilityClass` value is added: `comparison_manifest` stays at `0.2.0` (`6a1253b72664bff73e872d1230fb3d52772a438f55915406010e105b4f5d29a5`) and its committed model hash is unchanged; only comparator logic reads the new v0.2 fields. The evaluation-output manifest binds the read-back persisted-byte hash of every derived artifact for a complete audit chain.

This decision supplements ADR-011, ADR-012, and ADR-023, amends SPEC-024, and is applied through prerequisite Slice 12B (run manifest) and Slice 12C (comparator) before Slice 13.

## ADR-026 — Observation-target binding and evaluation-output-manifest v0.2

**Decision:** Raw extraction observation identities and canonical target-registry identities are **separate namespaces** and are never equated by renaming either side. Three namespaces are governed: (1) raw observation IDs, carried by the prediction source, `ParsedPredictionContent.entity_ref` values, and parent-observation-snapshot member owner IDs; (2) canonical target references, carried by `TargetRegistry.reference_id` (with its aliases), gold `canonical_target_reference`, case assertion `target_references`, and axis-taxonomy labels; (3) `observation_target_binding@0.1.0`, the **only** artifact permitted to map (1) onto (2). Extraction adapters therefore emit opaque observation IDs and carry any stable/canonical identity as an ordinary field value, never as the matched entity reference.

The binding is a post-parse, run-derived artifact, hash-pinned to the exact `ParsedPredictionContent` persisted bytes and to its raw artifact, and pinned to the target-registry version and SHA-256 taken from the case's own `CaseResolution` (reconciled against the supplied loaded registry before any persistence). Adjudication crosses the public boundary as strict, frozen, extra-forbid typed models — never dicts or `Any`: `ObservationTargetResolutionDecision` carries exactly `observation_id`, `observation_kind`, `resolution_status`, `canonical_target_reference`, `parent_referenced`, and `provenance`; `ObservationTargetResolutionProvenance` carries both *how* the decision was reached (resolution method, source field, matched registry entry/alias, unresolved reason) and its **governance record** (resolver kind and identities, reviewer identities, verification status and method, decision timestamps, change reason, adjudication reference). Resolver and reviewer identities must be disjoint, a verified or human-adjudicated decision requires a reviewer, and no timestamp is ever clock-generated by the producer. Every supplied decision is revalidated fail-closed before use.

The mapping is **many-to-one**: two distinct raw observations may legitimately resolve to the same canonical target, and that stays representable for validators and evaluation rather than failing construction; there is no canonical-target injectivity rule. `observation_id` remains unique through a completeness bijection against the parsed entity space (one decision per parsed entity, with matching entity kind). Exactly one decision is the owning subject (its kind fixed by the stage), every other is parent-referenced, and a task observation may never be a parent reference. `parent_referenced` is never merely caller-declared: whenever any observation is parent-referenced the producer **requires** the committed `parent_observation_snapshot@0.1.0` and verifies membership in the snapshot's verified owner set for that role plus `(case_id, company_id, observation_cutoff)` context equality. The snapshot proves parent existence, role, and context only — it never establishes canonical target identity, which stays independently verified against the registry and the adjudication provenance. Because the evaluation case carries no governed company field, `company_id` is an explicit caller claim that is verified against the snapshot's already-validated context and against any parsed `company_id` field value.

Unresolved decisions are first-class and auditable. `canonical_target_reference` is a **required** field, not an omit-or-non-null optional: a resolved decision carries a non-blank string, an unresolved decision carries JSON `null`, and it is never omitted. The omit-or-non-null rule — absence legal, explicit `null` rejected — applies instead to the optional provenance properties, the paired parent-snapshot pins, and the output-manifest optional hash fields.

Semantic assertion evaluation splits into two **mutually exclusive** producers. `build_resolved_assertion_evaluations` stays stage-general and binding-free and now rejects an extraction-stage case; `build_extraction_resolved_assertion_evaluations` requires the binding and rejects a non-extraction case. Non-extraction behaviour is unchanged. Extraction outcomes follow a fixed truth table over the resolved canonical set `C`, the present unresolved observations `U`, and the gold target set `T`, after the preserved incomplete-collection rule: `expected_entity` — `T ⊆ C` satisfied, else indeterminate if `U` non-empty, else unsatisfied; `forbidden_entity` — `T ∩ C` non-empty unsatisfied, else indeterminate if `U` non-empty, else satisfied; `field_value` and `evidence_provenance` — indeterminate if `U` non-empty, else unsatisfied when the target has no mapped observation, else evaluated over **all** mapped observations using the existing positive-any / negative-all operator semantics. A missing resolved mapping is not automatically indeterminate.

`evaluation_output_manifest` advances to `0.2.0` at the **same single canonical terminal-manifest path**, so one run can never hold two terminal manifests; version selection is a strict declared-contract-version peek, each public reader accepts only its own version with no fallback, and persisting either version into a run that already holds a terminal manifest collides with the preserved `artifact_exists` reason code. v0.2 retains the six v0.1 hash fields verbatim and adds a derived `derived_evaluation_stage` plus the conditional seventh `observation_target_binding_sha256`. Because `evaluation_run_manifest@0.2.0` deliberately does not persist `evaluation_stage`, v0.2 **derives** the stage by reverse-resolving the run manifest's `selected_stage_profile_entry_hash` against a supplied `LoadedStageProfileRegistry`: no stage parameter exists, registry version and semantic-content hash must equal the run pins, and **exactly one** entry must match — zero is `selected_stage_profile_entry_unresolved`, multiple is `selected_stage_profile_entry_ambiguous`, and the recovered stage must forward-resolve back to the same entry. No structural-uniqueness argument is relied upon. The binding hash is permitted only for a derived extraction stage, and supplied extraction assertion outcomes **require** it (`extraction_outcomes_require_binding`, enforced in the model, the builder, and the loader) while validator-findings-only invalid manifests stay valid at every stage. Validator findings remains the sole universal required output; `evaluation_output_manifest@0.1.0` keeps its fields, generated schema, governed contract hash, and behaviour unchanged through version-scoped artifact tables.

This decision supplements ADR-024 and ADR-025, amends SPEC-020 and SPEC-022, and is applied through prerequisite Slices Xe2a (parent-observation snapshot) and Xe-bind before Slice 13. Axis-taxonomy labels stay in the canonical namespace, so any future extraction-stage axis metric-input record construction must map through the binding; no such record is produced here and closing that path is a separate slice.

**Rejected alternatives:** Rekeying the target registry, gold set, case assertions, or axis labels to observation-shaped IDs was rejected because it destroys the stable canonical identity that longitudinal matching depends on and silently makes raw model output authoritative over the governed registry. Rekeying raw observation fixtures to canonical dot-form was rejected for the mirror reason: it fabricates canonical identity inside unverified extraction output. Embedding the mapping in `ParsedPredictionContent` was rejected because parsed content is a faithful parse of model output and must not carry adjudicated registry decisions. Untyped dict/`Any` adjudication input was rejected because the resolution boundary is exactly where governance evidence must be typed and revalidated. Canonical-target injectivity was rejected because duplicate extraction of one real capability is a legitimate, measurable outcome that validators must see rather than a construction failure. Treating any missing resolved mapping as `indeterminate` was rejected because it would erase genuine `unsatisfied` misses whenever resolution succeeded for every observation. Deferring parent-snapshot verification was rejected because a caller-declared `parent_referenced` flag proves nothing about parent existence or context. A separate `evaluation_output_manifest.v2.json` path was rejected because the output manifest is the terminal per-run audit root and two coexisting terminal manifests would make the audit chain ambiguous. Persisting or accepting a caller-supplied `evaluation_stage` in v0.2 was rejected because the run manifest deliberately does not persist it and a caller value cannot be verified.

## ADR-027 — Canonical runner boundary, adjudication ownership, and terminal-artifact policy

**Decision:** Slice 13's canonical runner is an orchestrator only. Its public input is a plan of hash-bound artifact references plus scalar identities; prebuilt `ResolvedAssertionEvaluation`, `ValidationArtifactSnapshot`, `MetricInputSnapshot`, `MetricReport`, `EvaluationResultV2`, and `ObservationTargetBinding` objects are rejected at the boundary. `--eval-root` names only the root the new immutable run directory is written under; governed inputs resolve against a separate `governed_artifact_root`, prediction inputs against `prediction_source_root`, and adjudication inputs against `adjudication_source_root`. Every reference carries a required SHA-256 pin in a typed, canonically ordered entry; `code_commit` and `evaluation_created_at` are plan-supplied (the runner never reads Git or a clock), and `prediction_run_id`/`prediction_run_manifest_hash` are pinned in the plan, re-derived from the prediction manifest's bytes, and re-verified post-normalization against `NormalizedPredictionRun`.

**Gate/result version dispatch.** `gates.py` accepts either governed run-manifest version across its whole build/persist/load path: the terminal builders and every binding helper take the `EvaluationRunManifest | EvaluationRunManifestV2` union, persistence and loading dispatch through the internal any-supported-version reader, and an inner-manifest check requires the concrete model class and the declared `contract.contract_version` to agree (`run_manifest_version_inconsistent`). The gate layer reads only the five fields v0.1 and v0.2 share, so the projection, `EvaluationResultV2`, and `evaluation_result.v2.schema.json` are unchanged, as is every v0.1 code path and error code. A v0.2 run may bind only `metric_report@0.2.0` (`metric_report_version_mismatch`); a v0.1 run keeps accepting either report version.

**Adjudication ownership (P1).** `ObservationTargetResolutionDecision` is a human/adjudicator judgement and no deterministic producer may synthesise it. `observation_target_resolution_decision_set@0.1.0` is a run-external, hash-bound artifact with a strict model, fail-closed revalidation, canonical write-once persistence, and a loader; a raw dict or hand-written JSON document is not a production authoring path. Because the set must pin the exact parsed-content artifact hash that only the persister could previously produce, `prediction_content` gains a public preparation boundary — `parsed_prediction_content_artifact_bytes` / `parsed_prediction_content_artifact_sha256` — and the persister and helpers share one private byte producer so the two can never drift. The authoring route is: parse in memory with the governed semantic adapter, take the artifact SHA-256, persist the typed set write-once, and let the runner re-derive the parse and verify every pin by exact equality (`decision_set_binding_mismatch`). Ownership of `EXTRACTION_EVALUATION_STAGES`, `ObservationTargetResolutionProvenance`, and `ObservationTargetResolutionDecision` moves to the new `resolution_decisions` module so the dependency runs one way; `observation_target_binding` imports and re-exports them under the same identities, and its `resolution_entries` tuple and the loaded decision set are mutually exclusive (`adjudication_channel_ambiguous`), with the runner permitted only the loaded-set channel. Moving the models changed no field, validator, or generated schema, so `observation_target_binding@0.1.0` (`f3ec0e0f2db9185333c667a6d7a52bf64a3b2a21b65bf1cbd90fa582ed67acd2`) and `parsed_prediction_content@0.1.0` (`ffeae7ab54fa03948f4498a3ceb5a634b17444791fd91f94a57c086afedbda3e`) are unchanged. Unlike the load-only `parent_observation_snapshot@0.1.0`, this contract owns a persister precisely because typed authoring is the only sanctioned route.

**Deterministic semantic-input producers (P2/P3).** Rules 1–11 validator observations with their coverage, and axis evaluation records, are deterministic values derived *after* parsed content (and, at an extraction stage, after the binding); they can never be plan inputs. They are pure public producers with no persisted artifact of their own: their outputs are embedded directly into the persisted `ValidationArtifactSnapshotSet` and `MetricInputSnapshot`, which `evaluation_output_manifest@0.2.0` already hash-binds. Giving them separate persisted artifacts would require a new output-manifest version; adding fields to v0.2 is forbidden.

**Terminal-artifact policy.** Failures split in three. Before the run manifest exists, nothing is written and no run directory is created — the rejection is operational only. After the run manifest exists but before validator findings can be produced, the run manifest, the config snapshot, any successfully persisted intermediate artifact, an `invalid`/`errored` `EvaluationResultV2`, and the presentation reports are written, while validator findings and the output manifest are **not**: `evaluation_output_manifest@0.2.0` makes findings mandatory, and writing an empty findings artifact would be a false claim that validation completed. A run directory is therefore legal and complete without an output manifest whenever the pre-runner audit chain never completed. Once findings exist, the output manifest can be built findings-only. `evaluation_output_manifest@0.2.0` binds the six pre-runner derived outputs plus the conditional binding hash — not `EvaluationResultV2` and not the reports — so it is the **pre-runner audit root**, never the whole-run audit root. Reports are non-authoritative presentation artifacts that bind nothing and are bound by nothing; the machine report requires the result and treats the metric report and output manifest as conditional, and report generation follows the terminal artifact's read-back.

**Run cardinality.** Slice 13's first scope is a single-case runner: the case set must hold exactly one membership entry, the prediction manifest exactly one envelope, and the envelope must match exactly one case on `(input_packet_hash, stage)`. Anything else is a fail-closed rejection before the run directory is created; selecting the first case, implicit filtering, and partial set evaluation are prohibited. `evaluate_case_assertions` evaluates exactly one package-case (`no_package_case_match`, `ambiguous_package_case_match`), so a multi-case or package-case runner is a separate Slice 13B whose precondition is a design lock that explicitly changes that evaluation-cardinality contract; `assertions.py` is unchanged here.

This decision supplements ADR-024, ADR-025, and ADR-026, amends SPEC-020 and SPEC-024, and is applied through prerequisite slices P1 (adjudication contract and preparation boundary), P2/P3 (deterministic semantic-input producers), and then Slice 13.

**Rejected alternatives:** Letting the runner produce validator observations, coverage, axis records, or resolution decisions was rejected because it would make the orchestrator a semantic producer and, for decisions, would fabricate human judgement. Passing them as plan inputs was rejected for observations and axis records because they are derived after the parse and cannot exist before the run. A single ambiguous observation-input reference was rejected because it conflates three distinct ownership boundaries. Asking an adjudicator to guess or hand-compute the parsed-content artifact hash was rejected because only the governed serialization chain can produce it. Duplicating that serialization rule in a second helper was rejected because the two copies would silently drift — a single-stage `exclude_unset` dump already produces different bytes than the persist path for content that omitted defaulted fields. Writing an empty validator-findings artifact to satisfy the v0.2 output manifest was rejected as a false validation claim. Adding fields to `evaluation_output_manifest@0.2.0` was rejected because it is frozen. Keeping the adjudication models in `observation_target_binding` was rejected because the decision-set contract must reference them while the binding producer consumes the set, which would make the two modules import each other.

## ADR-028 — Validator parameter successor `@0.2.0` and Rule 11 extraction inapplicability

**Decision:** Rule 11 (`customer_task_outcome_and_evidence`) is **not derivable at either extraction stage** and is therefore inapplicable there. Neither extraction output schema carries `is_customer_facing_task` or `customer_outcome`, and `availability_status` is an unconstrained string in both, so no conforming extraction record can support the rule. Making this effective requires a new governed contract version, because `validator_rule_parameters@0.1.0`'s matrix hard-enforces Rule 11 as applicable at both extraction stages and schema governance forbids mutating an accepted contract in place.

**Additive successor.** `validator_rule_parameters@0.2.0` is carried by a parallel class tree (`ValidatorRuleParametersV2`, its own entry/stage/payload types, and its own governed matrix) plus a strict loader `load_validator_rule_parameters_v2`. The v0.1 tree is untouched: its model-contract hash stays `f9c20ba936e1c0541c721ac6c3c34bec183b4b360dfa177516c57b0bd0945822`, the v0.2 hash is the distinct `a15556e5935c3ba26a966aaac18f84267a3b3dbedca43c7a9bc360e49e00df08`, and every committed v0.1 parameter and bundle artifact keeps loading byte-identically. Version dispatch is explicit and closed in both directions: the v2 loader requires a declared `contract.contract_version` of exactly `0.2.0` and rejects anything else with `parameters_version_unsupported`, and the v0.1 loader continues to reject `0.2.0`. There is no untyped escape hatch and no coercion between versions. `parameter_set_version` remains an independent artifact identifier and is deliberately **not** required to equal the contract version.

**Exactly three governed differences.** (1) Rule 11 is inapplicable at `capability_extraction` and `task_extraction` with the already-governed reason `stage_emits_no_customer_facing_task`. (2) Rule 10's applicable payload adds `active_status_values` and `roadmap_status_values` — non-empty, ascending, duplicate-free, mutually disjoint — because `availability_status` is unconstrained in the schemas and the classification cannot be schema-derived; a status outside their union fails closed rather than defaulting to inactive. (3) Rule 10 additionally depends on `source_id_resolution` with the positionally aligned, already-governed `blocked_source_unresolved` code, because its per-evidence temporal classification needs resolved source documents. Neither the blocking-reason nor the inapplicable-reason vocabulary is widened, and no coverage state is added. Rule 2's corrected required-field values stay inside the existing stage payload's `required_fields`, already bound by `complete_rule_parameter_hash`; a duplicate top-level extraction-required-fields field was rejected.

**Consequences.** Rule 10's truthful dependency means a prediction citing a source absent from the case-resolved document set is a citation defect that Rule 3 reports while Rule 10 states `blocked_by_dependency` with `blocked_source_unresolved` — the producer does not abort, so Rule 3's normal failing path is preserved. Because the Rule-10 and Rule-11 entries change, their per-rule hashes and the aggregate parameter-set hash change under v0.2, so a v0.2 parameter artifact requires its own reconciled `validator_bundle_artifact` counterpart and cannot be loaded against the v0.1 bundle. Both hash helpers accept either governed model type; the canonical dump algorithm is version-independent, so every v0.1 hash result is unchanged. `_STAGE_OPTIONAL_INAPPLICABLE` in `validators.py` was extended to *permit* Rule 11 inapplicability at the two extraction stages; that table is a direct-construction permission gate, not an effect, so the extension is hash-neutral and inert until a v0.2 parameter set actually declares the state.

This decision supplements ADR-024 and ADR-027 and amends SPEC-023.

**Rejected alternatives:** Mutating `validator_rule_parameters@0.1.0` in place was rejected under schema governance and artifact immutability. Deriving Rule 11 from parsed content or from wording was rejected because the required fields do not exist in the governed schemas. Adding a top-level extraction-required-fields field was rejected as a duplicate of an already-hash-bound payload field. Widening the blocking-reason vocabulary for Rule 10's source dependency was rejected because `blocked_source_unresolved` already exists. Letting Rule 10 abort the producer on an unresolvable subject-owned citation was rejected because it would make Rule 3's failure path unreachable and misreport a prediction defect as an input defect. Classifying per-evidence `is_future_roadmap` from the availability-status vocabularies was rejected because record status and evidence date are different facts. Treating an unknown availability status as inactive was rejected under the unknown-over-guess rule.

## ADR-029 — Observation-target binding successor `@0.2.0`: durable task-stage parent-snapshot identity

**Decision:** `build_extraction_validation_inputs` (SPEC-023 Rules 1–11) requires the committed `parent_observation_snapshot@0.1.0` at **both** extraction stages because Rule 7 validates raw parent-link fields, and it verifies that snapshot's identity against the binding's paired parent-snapshot pins. At `task_extraction` the parsed entity space holds only the task observation, so a governed binding carries no parent-referenced entry and `observation_target_binding@0.1.0` **forbids** the pins (`parent_snapshot_pins_forbidden`) — leaving the exact snapshot identity task-stage Rule 7 consumed unrepresentable in the persisted chain and making P2 structurally unsatisfiable at that stage. The correction is an explicit additive successor, `observation_target_binding@0.2.0` (`ObservationTargetBindingV2`): a field set identical to v0.1 except `parent_observation_snapshot_version` and `parent_observation_snapshot_sha256` are **required non-null**, and the contract binds only the `task_extraction` stage. Every other v0.1 invariant is retained verbatim (completeness bijection, exactly one owning subject of the stage's kind, a task observation is never a parent reference, canonical entry ordering and counts, registry and provenance coherence).

**Stage-dispatched production; v0.1 protected.** The sanctioned builder dispatches by stage: `capability_extraction` keeps producing `observation_target_binding@0.1.0` byte-for-byte (contract hash `f3ec0e0f2db9185333c667a6d7a52bf64a3b2a21b65bf1cbd90fa582ed67acd2`, unchanged), while `task_extraction` produces v0.2 (contract hash `658f2050a5ecf768ee8ee7384a8892bbe52209b122f4ca15f78d34ad31b924a1`), requires the snapshot, verifies `(case_id, company_id, observation_cutoff)` context, and records the snapshot's exact version and raw persisted-byte SHA-256 as required pins. The loader performs a strict declared-contract-version peek; every revalidation, persistence, and accessor path discriminates fail-closed on the concrete contract; and the non-contract-stamped loaded wrapper widens to the closed v0.1|v0.2 union. `validation_inputs.py` is unchanged: its exact parent-snapshot equality checks now pass at the task stage against the persisted pins and remain the rejection point for any foreign snapshot — including a context-matching one — that is not the snapshot bound to the run. The durable audit chain runs terminal result → `evaluation_output_manifest@0.2.0` (`observation_target_binding_sha256`) → write-once, hash-verified v0.2 binding → required snapshot pins; the identity is never merely a transient runner argument.

This decision supplements ADR-026 and ADR-027, amends SPEC-020 and SPEC-022, and is applied through the amended Slice 13 runner increment together with the task-stage end-to-end proof over the existing raw task material.

**Rejected alternatives:** Re-scoping the v0.1 pin invariant in place was rejected under schema governance because it would silently flip acceptance of same-stamped documents. Making P2's pin equality conditional on the binding carrying pins was rejected because task-stage Rule 7 would then consume a snapshot whose persisted identity nothing durably retains. Pinning the snapshot in `evaluation_run_manifest@0.2.0` was rejected as a protected-contract cascade through initialization, gate-manifest dispatch, and output-manifest reverse-resolution. Pinning it only in the validation snapshot set was rejected because P2's verification must precede that artifact's existence. Permitting v0.2 at `capability_extraction` was rejected to keep exactly one governed representation per stage.

## ADR-030 — Pilot 0 Route A one-firm admission: HubSpot FY2024 Pilot Universe Packet

**Decision:** HUBSPOT INC (CIK `0001404655`, NYSE `HUBS`) is admitted as the single Pilot 0 firm under **Route A** — a narrowly scoped, SEC-evidence-backed one-firm Pilot Universe Packet — for observation year **FY2024** with `observation_cutoff_date = 2025-02-12` (the annual filing date; fiscal-year-end `2024-12-31` recorded alongside so the filing-date vs fiscal-year-end convention comparison stays computable), mechanism category `enterprise_workflow_software`. The immutable `company_id` **`CIK0001404655`** is derived by `company_id_for_cik` exclusively from the persisted SEC submissions bytes — never manually asserted. The tracked packet is `data/registry/pilot_universe_packet_CIK0001404655.json`; the admission module and its offline tests are `src/dynamic_ai_products/universe/pilot_packet.py` and `tests/universe/test_pilot_packet.py`.

**Collection provenance and audit boundary.** One redirect-safe, write-once collection attempt against the frozen three-URL allowlist (submissions metadata, FY2024 10-K filing index `0000950170-25-018873`, primary document `hubs-20241231.htm`; form `10-K`, filed `2025-02-12`, period `2024-12-31`) completed with HTTP 200, zero retries, and requested-equals-final URLs on every request. Raw bytes are preserved gitignored under `data/raw/sec/CIK0001404655/0000950170-25-018873/` with the immutable receipt. Hashes: receipt `26e91fe2ea5127cb6e5233ba4b2170f42089c4fb07224874c8d617724c71299b`; submissions `6d2add25a7753cefa486d224c862f15b7b81a28707562a73848983587fdb8b19`; filing index `c6876565db97200958b4b30f2fcfe9da214d86836643f84d30fcb1fd93699880`; primary document `36257e638feb2059e3bbc58461938d6ffc11dd280e12d7af0f06c5394bf40b12` (4,764,421 bytes). **Audit boundary:** the receipt and raw-byte provenance — requested and final URLs, HTTP statuses, timestamps, byte counts, and SHA-256 values — are verified and immutable, but the historical collection was executed by a pre-refactor, uncommitted network-client implementation, so no committed executable collection-client identity exists for that one-time run. The committed `pilot_packet` module is injection-only, carries no network client and no CLI entry point, and the three snapshots plus receipt are a one-time Pilot 0 operator-collected source packet that is never recollected. A reproducible live SEC transport adapter belongs to a separately governed future ingestion/operator boundary outside the universe package and requires its own scope/path lock.

**Materiality evidence (human-selected, byte-verified).** Because this filing renders item headings across split spans, the admission uses two document-specific structural anchors rather than generic heading literals: start anchor raw bytes `id="item_i_business"` at offsets `[284999, 285019)` (SHA-256 `1bf4e0b59b93f0b8db79556cf5ca2eafdce6c4d2108df07c28669d32b51c2bd3`) and end anchor raw bytes `id="item_1a_risk_factors"` at offsets `[387363, 387388)` (SHA-256 `9f0eaf8d78f6ad94f1ac2f5fe5422bf08974c6391480ecec7a2861c5dbcee6ff`), each occurring exactly once in the primary document. The human-selected evidence slice (P8) at offsets `[285887, 286382)` (SHA-256 `cdea10b4fc505a05589c062d2797403fd5c7cd32b4d889dbdca104e95a5998ad`) lies between the anchors, satisfies `utf-8-strict-text-slice-v1` (strict decode, nonblank, no literal markup), and its text was re-read from the persisted bytes. The builder proved byte provenance and containment only; SIC 7372 remains cross-checking metadata, never the admission basis. No parser, renderer, entity decoder, normalizer, search, or model call participated in validation.

**Scope limitation.** This is a **pilot-only** admission: it is not a general universe decision, does not alter the `draft_pending_sentinel` universe status, `baseline_cutoff`, or any `configs/` flag, and must not be reused as precedent for universe membership. Stage 01–04 corpus collection, provider extraction runs, and harness evaluation for this firm remain separately approved boundaries.

**Rejected alternatives:** Admitting on submissions metadata/SIC alone was rejected (metadata is not materiality evidence). Generic text-only `Item 1. Business` heading markers were rejected after a read-only display proved this document's grammar renders headings across split spans, making that rule unsatisfiable; the `Item 2. Properties` end-marker alternative was likewise dropped for this route (zero text-only candidates). A manually asserted `company_id` was rejected in favor of derivation from persisted SEC bytes. Route B (admission exception) was not needed once the packet route was viable.

## ADR-031 — Pilot 0 Stage 01–04 ingestion preflight: boundary, persistence, and publication

**Decision:** The separately governed ingestion/operator boundary that ADR-030 deferred out of the universe package is `dynamic_ai_products.ingestion`. The dependency runs one way — `ingestion` → `universe` — and the receipt loader is imported from `universe.pilot_packet`, never reimplemented, because parallel serialization copies silently drift (ADR-027). Increment A is **code, governance, and tests only**: no artifact is written under `data/`, no adoption run is executed, Stage 01–04 registry statuses stay `stub`, and the four `pipelines/0[1-4]_*.py` stubs are untouched. The package is injection-only with no CLI entry point, contains no transport, no URL literal, no prompt, no provider client, and no harness reference, and reads neither clock nor VCS: `run_created_at` and `code_commit` are caller-injected, following the ADR-026 runner discipline. The offline adoption run against the existing raw 10-K is Increment B and requires separate approval.

**Shared write primitive and its narrow error-path strengthening.** `provenance.write_bytes_once` is dependency-neutral: `provenance.py` imports the standard library only and must never import from `universe` or `ingestion` or raise `PilotPacketError`. It raises `WriteOnceError`, whose closed category vocabulary is `destination_exists` and `write_verification_failed`, with an optional `step` diagnostic (`create`/`write`/`reread`/`verify`) and an optional `cleanup_detail`. The primitive is an **intentional strengthening**, not a verbatim move of the former `universe.pilot_packet._write_once`: on failure of create, write, fsync, re-read, or verification it now closes the descriptor and removes **only** the destination it newly created in that call, where the previous helper left a partial file that — under a write-once contract — permanently blocked every retry with `destination_exists`. Ownership is proven by a successful `O_EXCL` create, so a refusal path never unlinks anything; a pre-existing file or symlink is refused and survives with unchanged bytes. A cleanup failure is reported through `cleanup_detail` and never masks the original error. `universe.pilot_packet` retains `_write_once` as a thin translating wrapper mapping `destination_exists` → `PilotPacketError(reason_code="destination_exists")` and `write_verification_failed` → `reason_code="write_error"`, preserving the committed Pilot 0 API exactly: same returned hash, same bytes, same reason codes, same message text, with `__cause__` chaining to the neutral error. Ingestion translates the same neutral error into `IngestionError`. No committed Pilot 0 test asserted the old leave-behind behavior, so no existing assertion required reconciliation; four new assertions cover the translation boundary.

**Publication transaction.** Multi-artifact emission cannot claim "a stop writes no partial artifact" once publication has begun, so the model is `staging_root_atomic_rename`: all seven artifacts are built and verified inside a fresh run-scoped staging root on the same filesystem as the destination, the staging tree is fsynced, and the whole run is published by a single `os.rename`, followed by a parent-directory fsync. The run root either exists complete or does not exist. Only a successfully published `ingestion_preflight_manifest` is authoritative; a staging root is non-authoritative by name (`.staging-` prefix) and is **never removed automatically**, because automatic deletion would be silent repair. Residual guarantee, stated honestly: a failure before the rename leaves complete immutable files inside the staging root only, where nothing may read them, and the run is terminally incomplete; a crash between the rename and the parent fsync may leave the run root absent after reboot but never half-built. Rerun always uses a new run identity and root, and no file is ever overwritten. The alternative of retaining flat per-directory output paths was rejected precisely because four directories cannot be published by one rename; it would have left complete artifacts scattered across the tree after a late I/O failure.

**Run identity and output templates.** `run_id` is `"ing-" + sha256(canonical_json(...))[:32]`, derived only from injected values plus pinned input identities, and locked to `^ing-[0-9a-f]{32}$` — lowercase hex only, so no path separator or traversal sequence can appear. Identical inputs yield an identical run id, so a duplicate run is refused rather than silently creating a second root. The seven literal `data/runs/{run_id}/…` output templates are the **Pilot 0 Increment-B execution contract** and live solely in `dynamic_ai_products.ingestion.publication.RUN_ROOT_TEMPLATES`, where the package that owns the publication model owns them. Materialization is explicit and single-sited: `materialize_template` refuses any template whose placeholder set is not exactly `{run_id}` or whose placeholder is not a complete path segment, `preflight._relative` additionally confines every staged artifact to the run root, and a residual brace in a materialized path is a fail-closed error. There is no implicit substitution, no environment lookup, and no default value. Because run roots live under the already-gitignored `data/runs/`, no `.gitignore` change is required and no emitted artifact can trip the REPO_MANIFEST completeness test. Whether a published preflight manifest is later promoted into tracked storage is deferred; promotion may only copy from a published run root and never mutate one.

**Pilot 0's run-root layout does not amend the general Stage 01–04 registry.** `configs/pipeline_stages.yaml` is the general future pipeline registry, not a Pilot 0 execution profile, and its Stage 01–04 `inputs` and `outputs` remain the original generic flat declarations: Stage 01 `data/registry/sec_source_candidates.parquet` and `data/manifests/sec_discovery_manifest.json`; Stage 02 `data/registry/official_web_candidates.parquet` and `data/manifests/web_discovery_manifest.json`; Stage 03 `data/snapshots/**` and `data/manifests/snapshot_manifest.jsonl`; Stage 04 `data/normalized/documents.parquet` and `data/normalized/passages.parquet`. Encoding the Pilot's no-web-discovery and adoption-only-snapshot behavior by deleting generic future outputs was **wrong and is reverted**: a stage's declared outputs describe what that stage produces in the general pipeline, and a single narrowly scoped pilot that does not exercise a path must not erase it from the graph. Injecting `{run_id}` into registry outputs was likewise reverted, because it would make one pilot's run layout the general contract for every future firm-year. The **only** general governance improvement retained in the registry is Stage 03's `co_specs: [specs/SPEC-003-sec-ingestion.md]`, recording that SPEC-003 co-governs the SEC component of snapshotting; `validate_stage_registry` checks those paths exist and carries no template-shape logic. The general pipeline's run layout — whether future stages write to flat data zones, to run-scoped roots, and how a run is promoted into a release — **remains an open decision** and is not settled by this ADR.

**Normalization and provenance without schema changes.** `sec_html_item_span_v1` is authorized: deterministic, pure, offline, no model, operating only on an anchor-bounded byte span of an already hash-locked raw document rather than a whole filing, with the ordered transform chain markup-tag removal → HTML entity decoding → whitespace collapse. This is the repository's first normalizer; ADR-030 recorded that none participated in packet validation. `source_document@0.1.0` and `source_passage@0.1.0` are **not versioned up and gain no field** — both declare `additionalProperties: false`, so the earlier `text_provenance_mode` proposal was withdrawn. Provenance rides on existing carriers: `normalizer_version`, `start_offset`/`end_offset` **absolute into the raw document bytes**, the raw `content_hash`, the normalized `text_hash`, and a transform/provenance ledger in the preflight manifest. The asymmetry is deliberate and declared in the ledger: offsets address raw bytes while `text_hash` covers normalized text, so an emitted passage is not a byte-identical raw slice. `passage_id` is content-addressed — `sha256(source_id, text_hash, occurrence_index)` — and therefore stable when unrelated parts of the document change, as the corpus architecture requires; offset-addressed identity would not be.

**Coverage vocabulary and family set.** `not_attempted` is added to the coverage-state vocabulary alongside the seven states in `docs/architecture/CORPUS_ARCHITECTURE.md`. It is the only truthful state for a family that was never queried: `not_found` would claim we looked and `not_applicable` would claim the family does not apply, both violating the unknown-over-guess rule. The required Pilot 0 family set is exactly the five declared in the committed packet (`sec_edgar`, `official_ir`, `product_pages`, `developer_docs`, `web_archives`); `newsroom`, which appears in `configs/source_types.yaml` and has a playbook, is recorded as an explicit `out_of_required_set` optional family so its exclusion is auditable rather than silently absent.

**Spec governance and dependencies.** SPEC-003 co-governs the SEC component of Stage 03 through a new `co_specs` registry field whose paths the validator checks; SPEC-007 deduplication remains deferred with no stage slot. Parquet is retained for candidates, documents, and passages per the registry, with deterministic row ordering by a declared key, an explicit column schema, pinned writer options, and a SHA-256 over the exact emitted bytes; the mandatory writer metadata exists because the digest pins what was emitted while byte-identical *reproduction* holds only under the same writer library, version, and options. `pyarrow` was present in the environment but undeclared, and is now an explicit dependency.

New contracts, all `@0.1.0`: `sec_source_candidate`, `source_family_coverage`, `snapshot_manifest`, `ingestion_preflight_manifest`. `schema_version_manifest.json` moves `0.2.0` → `0.3.0`. The preflight manifest binds **six** artifacts, not seven: it is written last and cannot bind itself.

This decision supplements ADR-030, amends SPEC-002, SPEC-004, SPEC-005, and SPEC-006, and is applied through Increment A. It does **not** amend `configs/pipeline_stages.yaml` beyond adding Stage 03's `co_specs`.

**Rejected alternatives:** Adding `text_provenance_mode` to either extraction-adjacent schema was rejected because both forbid additional properties. Versioning `source_document`/`source_passage` up for a provenance note was rejected as unnecessary once the ledger carried it. Duplicating `_write_once` into the ingestion package was rejected under the ADR-027 anti-drift finding. Letting `WriteOnceError` escape a public API was rejected because it would leak a neutral transport type into two different consumer contracts. Removing a pre-existing file on a failure path was rejected as destroying data the primitive never owned. Auto-deleting a failed staging root was rejected as silent repair. Scattering the Pilot's *execution* outputs across four flat directories was rejected because four directories cannot be published by one rename, which is why Increment B writes under a single run root — this is a statement about Pilot 0 execution only, not about the general registry. Using JSONL instead of Parquet for candidates/documents/passages was rejected in favor of the declared Parquet outputs plus an explicit determinism contract. Mapping the four unqueried families to `not_found` or `not_applicable` was rejected as a false claim. Putting the seven run-root templates in `configs/pipeline_stages.yaml` was rejected because that registry is the general future pipeline graph, not a Pilot 0 execution profile, and one pilot's run layout must not become every future firm-year's contract. Deleting Stage 02's official-web outputs and Stage 03's `data/snapshots/**` because Pilot 0 does not exercise them was rejected for the same reason: a stage's declared outputs describe the general pipeline, and a narrowly scoped pilot must not erase a path from the graph merely by not using it. Keeping `{run_id}` shape validation in `workflow.py` was rejected because the registry no longer carries templates, so the validator would police a rule nothing declares; that validation now lives in the ingestion tests, where `RUN_ROOT_TEMPLATES` is owned.

## ADR-032 — Pilot 0 Stage 02–03 official-source collection: request-plan authority, apex trust boundary, and the sibling collection contract

**Decision:** Official-web discovery and snapshotting live in a new package, `dynamic_ai_products.collection`, the separately governed operator/transport boundary that ADR-030 and ADR-031 deferred out of `dynamic_ai_products.ingestion`. The dependency runs one way — `collection` → `provenance` only; `collection` never imports `ingestion`, `ingestion` never imports `collection`, and `universe` imports neither. Increment C-A is **code, governance, and offline tests only**: no live request, no artifact under `data/`, every test using an injected fake transport, and Stage 01–04 registry statuses unchanged at `stub`. ADR-030 recorded that Pilot 0's SEC bytes were collected by a pre-refactor, uncommitted client, leaving **no committed executable collection-client identity**; this ADR closes that gap by declaring the client contract in `transport.py`, hashing it, and making that hash both a recorded manifest field and an input to the run identity.

**Temporal admission.** `publication_date`, `retrieval_timestamp`, and `snapshot_timestamp` are recorded separately and never conflated. `retrieval_timestamp` is provenance only and is **never** a temporal-eligibility input — a structural point here, because any live retrieval for FY2024 now occurs roughly seventeen months after the `2025-02-12` cutoff. Two non-interchangeable routes exist: the **dated-document route**, where a document carrying a reliable firm-published date on or before the cutoff may be retrieved live because `publication_date` governs; and the **archive route**, where an undated or mutable page can only establish the FY2024 state through a capture whose `snapshot_timestamp` is on or before the cutoff. A `live` entry may therefore only declare `dated_document`; an `archive` entry may declare either, because an archived capture of a dated document is admitted on its publication date. Every snapshot carries a historical-validity flag, satisfying SPEC-005's acceptance criterion, and a missing date yields `uncertain` rather than a guess.

**Domain rule.** The frozen trust boundary is the SEC-derived registrable apex `hubspot.com`. Derivation binds **all three** committed SEC raw inputs: `derive_official_apex` hash-verifies the submissions, filing-index, and primary-document bytes against every entry in `SEC_DERIVATION_PINS` — each against both its caller-supplied pin and the committed Pilot 0 pin — and only then tests that the apex occurs literally in the primary document. The trust boundary therefore rests on the whole hash-verified filing triple rather than on a single document. A URL is an official-origin candidate iff its host is exactly the apex or a **strict subdomain**; subdomains need **not** appear literally in the SEC bytes, because delegation below the apex is inherited. No search engine, third-party directory, or live homepage lookup participates. **Archive hosts are transport-only exceptions**: an archive may serve a capture of an allowed original URL and is recorded as `archive_host`/`archive_url`, but the `source_url` of an archived document is always the original apex URL, and an archive host presented as an origin is `archive_host_as_origin`. Any other host is `third_party_domain_excluded`, enforcing SPEC-004's no-third-party-domain criterion structurally at admission rather than by post-hoc filtering.

**Request-plan authority and the three request classes.** `web_collection_request_plan@0.1.0` is a caller-prepared, strictly extra-forbidding artifact approved before collection and hash-pinned in **both** the receipt and the collection manifest. To avoid overclaiming what a schema file does at runtime: **the loader is the runtime authority**. `validate_request_plan` enforces the schema-equivalent top-level constraints in code — `company_id` must match `^CIK[0-9]{10}$` and `observation_cutoff_date` must pass the same strict real-calendar-date check used for storage path segments, with violations raising `request_plan_invalid` — in addition to the per-entry enum, route, ordering, duplicate, and archive-grammar rules. The JSON Schema is registered and separately registry-validated by the schema-validation CLI, but nothing in the collection path depends on a schema validator having run. Exactly three classes of HTTP request may occur, and the receipt accounts for each separately. (1) An **independently initiated document request** is permitted only for an exact plan entry; anything else is `undeclared_url_refused`. (2) A **robots request** is permitted only as the deterministic `https://{host}/robots.txt` for a host named by a plan entry, and is recorded in its own `robots_requests[]` array. (3) A **redirect hop is not an independently initiated candidate request** — it is a response-derived continuation of one already-authorized request, permitted only when it follows a redirect response for that request, stays inside the apex for `live` entries or that entry's declared archive host for `archive` entries, keeps the chain within five hops with no loop, and is fully recorded. A final URL becomes canonical for its own planned entry only and can never be reused as authority for another request. Crawling, link following, sitemap expansion, search-engine expansion, and cross-entry final-URL reuse remain impossible. This replaces the earlier absolute "no undeclared request of any kind" wording, which was imprecise: it would have forbidden ordinary canonicalization redirects that the bounded-boundary rule makes safe.

**Archive authority is structural, never substring-based.** Pilot 0 admits exactly one closed archive grammar: the host must be exactly `web.archive.org` (`ARCHIVE_HOST_ALLOWLIST`), the path must match the Wayback capture grammar `/web/<timestamp><optional modifier>/<embedded absolute http(s) URL>`, and the **embedded original URL must canonicalize to exactly the entry's `source_url`**. A query or fragment on the capture belongs to the embedded original — a genuine capture of `…/x?a=b` is spelled `/web/<ts>/https://host/x?a=b` — so it is reattached to the embedded URL rather than banned; a *spoofed* query is caught by the canonical-equality check, which is where it matters. Arbitrary archive hosts fail `archive_host_not_allowed`, malformed captures fail `archive_capture_malformed`, and a capture embedding any other original fails `archive_original_host_mismatch`. This replaces an earlier rule that admitted an archive URL merely because its text contained the source host, which a URL such as `https://web.archive.org/web/<ts>/https://evil.example/marketing?ref=www.hubspot.com` would have satisfied.

**Terminal transport identity fails closed.** In `follow_redirects`, a non-redirect response must carry a nonblank `final_url` exactly equal to the URL actually requested; a blank or mismatched value raises `terminal_url_mismatch` rather than silently substituting the requested URL. Inventing provenance for a response that never named its own URL would let an off-boundary terminal URL enter the record without ever passing a redirect-hop boundary check.

**Malformed URLs are sanitized at one seam.** `domains.split_url` is the single parsing entry point: it rejects non-http(s) schemes, hostless URLs, and — critically — URLs carrying credentials, and it converts `urlsplit`'s deferred `ValueError` on an invalid port into `CollectionError(reason_code="url_invalid")`. `host_of` and `canonical_url` both route through it, so no `ValueError` escapes the package and a userinfo segment can never smuggle a host past the apex check.

**Plan context binds discovery.** `build_official_web_candidates` revalidates the supplied plan rather than trusting it, and requires the caller's `company_id` and `observation_cutoff_date` to equal the plan's own; a mismatch fails closed with the stable `request_plan_context_mismatch` code, and rows are built only from the revalidated, context-matching plan. Without this a valid plan for one firm-year could be replayed to emit candidates under a different firm or a different observation cutoff — a temporal- and identity-integrity hole that no per-entry URL rule would catch.

**Path-segment safety.** No unrestricted timestamp is ever interpolated into a path. Raw bytes are stored at `data/raw/web/{company_id}/{content_family}/{date_key}/{content_sha256}.{ext}`, where `company_id` matches `^CIK\d{10}$`, `content_family` comes from a closed enum, `date_key` is a strict `^\d{4}-\d{2}-\d{2}$` real calendar date rejected on any separator or traversal sequence, `content_sha256` matches `^[0-9a-f]{64}$`, and `ext` comes from the closed allowlist `{html, pdf, json, txt}`. Every write goes through the ADR-031 strengthened `provenance.write_bytes_once`.

**Content role separated from access channel.** `web_archives` is **not** a document content family. Each document has exactly one `content_family` from `{official_ir, product_pages, developer_docs, newsroom}` and, independently, an `access_channel` from `{live, archive}`, so no document is counted twice. The successor `source_family_coverage@0.2.0` records both dimensions separately, inherits and pins `sec_edgar` from the parent Increment B manifest rather than recomputing it, and provides an **explicit derived bridge** for the Pilot Packet's legacy required `web_archives` entry: `available_and_retrieved` iff at least one temporally valid archived capture of an allowed official-origin URL was admitted, and otherwise a truthful terminal state with a reason code and an error record. `not_attempted` is not a permissible terminal state for a required content family once this stage has run. The published Increment B coverage artifact `c3df1406…f807ef` is **never mutated**; v0.1 remains valid and every committed v0.1 artifact keeps loading.

**Sibling collection contract.** `ingestion_preflight_manifest@0.1.0` is **not widened and not given a successor**, and the published Increment B run root stays immutable. The new immutable sibling `official_web_collection_manifest@0.1.0` lives in its own run root under `data/runs/{collection_run_id}/` with `collection_run_id` matching `^owc-[0-9a-f]{32}$`, a prefix distinct from `ing-`. It pins the parent Increment B manifest `aacc8cdb…df6bbb`, the five Pilot 0 input hashes, and the request-plan hash, and binds six artifacts — it is written last and cannot bind itself. Artifacts are canonical JSON/JSONL with **no Parquet in this increment**: that keeps every artifact byte-deterministic without Parquet's writer-version reproduction caveat and avoids both duplicating `ingestion.parquet_io` (the ADR-027 anti-drift finding) and importing it across the boundary. Combined normalized corpus artifacts belong to a later, separately approved adoption increment. Because `collection` may not import `ingestion`, its canonical JSON serializer is a second implementation pinned to the first by a cross-package byte-equality test rather than by an import.

**Run identity.** `collection_run_id` is `"owc-"` plus the first 32 lowercase hex characters of SHA-256 over canonical JSON containing **exactly fourteen keys**: `contract`, `code_commit`, `run_created_at`, `parent_ingestion_manifest_sha256`, the five Pilot 0 input pins, `request_plan_sha256`, `collection_client_contract_hash`, `canonicalization_version`, `robots_policy_version`, and `rate_limit_policy_version`. A missing or extra key is `run_identity_invalid`. Every value is caller-injected or pin-verified before collection; the package reads neither clock nor VCS. The identity is derived — and a duplicate refused — **before** a staging root is opened and before any network request, so a duplicate run issues **zero requests**. Publication reuses ADR-031's `staging_root_atomic_rename`, and a staging root is non-authoritative by name and never removed automatically.

**Zero-evidence route.** If no temporally valid document is admitted in any required content family, the outcome is the fail-closed `no_supported_case` verdict. The coverage artifact and error records **are** published, because what was requested, what failed, and why is the scientific result; no provider or model call is made, no evaluation-harness run is initiated, no extraction artifact is produced, and Stage 01–04 statuses stay `stub`. The collection manifest's verdict vocabulary is `{official_packet_ready, no_supported_case}` and deliberately excludes any extraction verdict.

`schema_version_manifest.json` moves `0.3.0` → `0.4.0` with seven new entries. The three REPO_MANIFEST count guards and the two schema-version-manifest SHA guards in `tests/evaluation/` are rebaselined; neither guard is weakened or removed, and `test_run_manifest_v2`'s evaluation-v2-specific assertion is preserved verbatim.

**Test filename deviation, ratified.** The lock named `tests/collection/test_publication_atomicity.py`, but the committed `tests/ingestion/test_publication_atomicity.py` already occupies that basename, and pytest imports test modules in non-package directories by basename alone — two identical basenames abort collection for the whole suite. The collection test is therefore named **`tests/collection/test_collection_publication_atomicity.py`**. This is the minimal resolution: it keeps the authorized path count at 39, touches no committed file, and stays inside the new collection package, whereas adding `--import-mode=importlib` to `pyproject.toml` or `__init__.py` files to both test directories would each have added paths outside the approved set.

This decision supplements ADR-030 and ADR-031, amends SPEC-004 and SPEC-005, and is applied through Increment C-A. It does **not** amend `configs/pipeline_stages.yaml`.

**Rejected alternatives:** Requiring each subdomain to appear literally in the SEC bytes was rejected because delegation below a verified apex is inherited and the literal rule would arbitrarily exclude valid official origins. Treating `web_archives` as a content family was rejected because it conflates an access channel with a content role and double-counts documents. Mutating the published Increment B coverage artifact to backfill the four families was rejected under artifact immutability. Widening or versioning `ingestion_preflight_manifest@0.1.0` was rejected because the sibling contract keeps the published run root untouched. Emitting Parquet here was rejected because it would force either an anti-drift violation or a boundary violation, and because writer-version-bound bytes weaken a hash-pinned receipt. Keeping the absolute no-undeclared-request wording was rejected because it conflated an independently initiated request with a response-derived redirect hop and would have made ordinary canonicalization redirects unrepresentable. Allowing a final URL discovered through one entry to authorize a request for another entry was rejected as crawling by another name. Interpolating a raw timestamp into a storage path segment was rejected as an injection and traversal hazard. Accepting an archive URL because its text contains the source host was rejected as substring authority that a crafted query parameter defeats. Banning every query string on a capture wrapper was rejected because it would make any original URL bearing a query uncapturable; canonical equality of the embedded original is the correct and narrower defense. Substituting the requested URL for a blank terminal `final_url` was rejected because it fabricates provenance. Deriving the apex from the primary document alone was rejected because it left the other two committed SEC inputs unbound. Returning the plan's `company_id` and `observation_cutoff_date` unvalidated, and letting discovery take them as independent arguments, was rejected because it let a valid plan emit candidates under a foreign firm or cutoff. Describing the plan as "schema-validated" was rejected as an overclaim: the schema file does not execute in the collection path, so the loader must enforce the equivalent constraints itself. Deriving the run identity after opening a staging root was rejected because a duplicate run would then perform network requests before being refused.

## ADR-033 — Pilot 0 Stage 05–07 extraction: provider boundary, parent-snapshot handoff, and validation-driven reconciliation

**Decision:** Product, capability, and task extraction run in a new `dynamic_ai_products.extraction` package whose provider execution is **separate from the evaluation harness**. ADR-026 fixed the runner as an orchestrator whose input is a plan of hash-bound references; it reads no clock, no VCS, and no model. Extraction therefore emits artifacts and the harness consumes them by hash, joined by nothing else. `extraction_run@0.1.0` is adopted **unchanged** as the provider-run provenance manifest: it is strict (`additionalProperties: false`, 15 properties) and already carries `model_provider`, `model_name`, `model_parameters`, `prompt_hash`, `schema_hash`, `source_manifest_hash`, `code_commit`, and `spec_version`. It has **no** provider-client-contract field and none is added; the provider-client contract is bound instead as a byte-referenced entry in the released `prediction_artifact_manifest@0.1.0`'s `source_artifacts` tuple, which is already `(reference, sha256)` pairs. `PredictionArtifactManifest.source_artifacts` pins six artifacts — raw prediction bytes, the stage input packet, the coverage artifact, the resolved prompt, the provider-client contract, and `extraction_run` itself. Write order is acyclic: input packet → prompt → provider-client contract → raw prediction → `extraction_run` → envelopes → prediction manifest last, with `extraction_run` never referencing the manifest. The prediction manifest is the single harness-visible root from which all provider provenance is reachable.

**Harness bridge.** The evaluation runner requires two distinct artifacts, and the Increment B normalized Parquet files are neither. The first is `prediction_artifact_manifest@0.1.0` with its envelopes and source artifacts. The second is `source_passage_snapshot_manifest@0.1.0` with loader-compatible `source_documents.jsonl` and `source_passages.jsonl` corpora, produced by a deterministic transcoding bridge that reads the **published** ingestion run root, verifies both Parquet files against the preflight manifest's `artifact_bindings`, and persists through the **existing** `persist_source_passage_snapshot_manifest`. The bridge is granted the **only** permitted `extraction → evaluation` import edge — `evaluation.source_snapshot`'s persister and hash helper — because a second serializer for a released contract would silently diverge (ADR-027). `evaluation` never imports `extraction`, and no other extraction module imports `evaluation`. The bridge reconciles all 15 `SourceDocumentRecord` fields and all 9 `SourcePassageRecord` fields plus both counts, and **never generates a timestamp**: `retrieval_timestamp`, `publication_date`, `snapshot_timestamp`, and `temporal_validity` are copied verbatim, preserving the seventeen-month retrieval-versus-cutoff gap that the contamination tests exist to police.

**Two parent-snapshot instances, one contract version.** `_ParentMember.role` is `Literal['product_parent', 'capability_parent']`, so `parent_observation_snapshot@0.1.0` has always expected both roles, and the contract version never changes. Two instances differ only in members, `snapshot_version`, and SHA-256. Snapshot **A** is product-only, built from human-accepted product observations; Stage 06 `capability_extraction` consumes A. Snapshot **B** carries A's product parents **byte-unchanged** plus exactly the accepted capability parents; Stage 07 `task_extraction` consumes B, and `observation_target_binding@0.2.0` pins B's version and SHA-256. Both stages still require the committed snapshot for `build_extraction_validation_inputs` Rule 7 (ADR-029); only the task stage durably pins its identity.

**Human validation is a typed artifact, never folded into snapshot authoring.** `product_extraction` is not in `EXTRACTION_EVALUATION_STAGES` and has no binding contract, so it is not harness-scorable; its gate is human. The chain is: raw literal output → `extraction_candidate_collection@0.1.0` (deterministic, schema-valid) → `extraction_validation_decision_set@0.1.0` (human accept/reject) → individually persisted accepted observation artifacts → snapshot members referencing exactly those. Candidate entries are **wrappers** — `{candidate_id, ordinal, observation_kind, observation}` — because `product_observation@0.1.0` and `capability_observation@0.1.0` are strict and cannot carry an appended `candidate_id`; the nested payload validates independently against the unchanged released schema. Identity is `candidate_id = sha256(raw_artifact_sha256 ‖ 0x00 ‖ ordinal ‖ 0x00 ‖ canonical_json_bytes(observation))[:32]`, binding to the raw digest and ordinal so an id is non-transferable across raw artifacts. Canonical order is ascending `ordinal`. Both collection and decision-set contracts are **parameterized** by an `observation_kind` discriminator rather than split per kind, avoiding near-identical schemas that would drift.

**Stage-scoped input packet and validation-driven reconciliation.** `extraction_input_packet@0.1.0` is stage-scoped: the product stage forbids parent context; the capability stage carries Snapshot A plus accepted product parents and product-validation provenance; the task stage carries Snapshot B plus accepted product and capability parents and **both** validation provenances. Parent IDs are derived **only** from re-read, hash-verified snapshot members — never caller-supplied, never inferred from prose. Hash-verifying a snapshot proves it intact, not authorized, so the packet builder reconciles every snapshot against the decision sets that authorized it **before** deriving any parent context. Stage 06 requires two equalities; Stage 07 requires **five**: (E1) A's `product_parent` members equal the accepted product artifacts in the **product** decision set; (E2) the capability decision set's pinned A equals the loaded A; (E3) B's `product_parent` members equal A's byte-for-byte; (E4) B's `capability_parent` members equal the accepted capability artifacts; (E5) every referenced member artifact re-reads to its recorded SHA-256. Failure codes are stage-specific: `snapshot_a_product_members_mismatch` (reused at Stage 07), `capability_decision_snapshot_a_mismatch`, `snapshot_b_product_carryover_mismatch`, `snapshot_b_capability_members_mismatch`, `parent_member_hash_mismatch`.

**Why Stage 07 re-runs E1.** E2 through E5 are all internal to the A/B/capability-decision triple. A self-consistent forged A, a B built from that forged A's product members plus genuinely accepted capabilities, and a capability decision set pinning the forged A satisfy E2–E5 completely. Only E1 reaches outside the triple to the human product judgement, so Stage 07 re-runs it rather than trusting that Stage 06 did. **These checks live only at the packet/orchestrator boundary.** `load_parent_observation_snapshot` is a frozen loader validating its own contract shape and digest, with no knowledge of decision sets. `observation_target_binding@0.1.0` **cannot** perform them: its snapshot pins are deliberately forbidden (`parent_snapshot_pins_forbidden`, ADR-029), leaving no field to compare, so Stage 06's correctness rests entirely on this boundary. `observation_target_binding@0.2.0` pins B's identity but not B's authorization.

**Corpus scope carried by exactly two carriers.** `ParentObservationSnapshot`, `PredictionEnvelope`, and `EvaluationOutputManifestV2` are strict extra-forbid models with no scope field, so no scope field is added to any of them. Scope is carried by the existing `source_family_coverage` artifact pinned by reference and SHA-256, and by `corpus_scope` inside `extraction_input_packet@0.1.0`. There is **no third scope artifact**. Envelope `source_references` include the stage input packet; `source_artifacts` pin packet and coverage; decision sets pin their stage packet and the same coverage artifact, with the capability set additionally pinning Snapshot A directly. Evaluation outputs remain technically valid and unmodified; their **interpretation** is constrained by that separately pinned provenance, and a reader presenting them without resolving it is misreading them.

**Non-run route.** The canonical input packet is persisted write-once **before either route branches**. On a zero-admissible-passage route the published run root holds exactly two files — the packet as an upstream input artifact, and `extraction_non_run_record@0.1.0` as the sole newly published extraction-run output, pinning the packet by reference and SHA-256 with the filter ledger as explanatory data beside it, never as a substitute for its bytes. **No `extraction_run` is written** on that route: `extraction_run@0.1.0` requires `prompt_hash` and `source_manifest_hash` and denotes a provider run, so writing one with a stopped status would assert a run that never began and force a fabricated `prompt_hash`. No raw prediction, envelope, prediction manifest, or harness run exists there either.

**Gate sequence and scope limitation.** E-0 (this ADR) → E-A (extraction package, offline, injected fake provider, **no SDK, no credentials, no network capability whatsoever**, nothing under `data/`) → **E-P** (provider-connector increment: concrete connector, model label, parameters, credentials, client-contract identity — its own scope lock) → E-B (SEC-only bounded smoke pilot) → E-C (capability) → E-D (task). Each gate stops for review; none authorizes the next. The **SEC-only smoke pilot is permitted after E-A solely as a provisional pipeline and harness exercise** under `corpus_scope = sec_only_partial` and the pinned coverage artifact; it must **never** be represented as a complete FY2024 product, capability, or task universe, and C-B official-web collection remains required for corpus completeness while `official_ir`, `product_pages`, `developer_docs`, and `web_archives` stay `not_attempted`. Stage 01–04 registry status stays `stub` throughout.

**Contracts ratified but not yet created.** `extraction_input_packet@0.1.0`, `extraction_candidate_collection@0.1.0`, `extraction_validation_decision_set@0.1.0`, and `extraction_non_run_record@0.1.0` are ratified here in text. Their schema files and their `schema_version_manifest.json` registration (`0.4.0` → `0.5.0`, 26 → 30 entries) are **deferred to E-A**, following the repository convention that a schema ships in the same increment as its producer — as `e64bb00` and `dc3c400` both did. Registering a contract with no producer, no loader, and no conformance test would be a governance claim with no control behind it, and the repository already carries one such orphan in `extraction_run@0.1.0`.

This decision supplements ADR-026, ADR-027, ADR-029, ADR-031, and ADR-032, amends SPEC-008, SPEC-009, and SPEC-010, and is applied through E-0 as documentation only.

**Rejected alternatives:** Adding a provider-client-contract field to `extraction_run@0.1.0` was rejected because it is strict and released. Adding `corpus_scope` to the parent snapshot, prediction envelope, or output manifest was rejected because all three are strict extra-forbid models. Inventing a third unnamed scope artifact was rejected as redundant with the existing coverage artifact. Treating the ingestion Parquet as either harness input role was rejected because neither role accepts it. Duplicating the released source-snapshot persister was rejected under ADR-027 anti-drift. Appending `candidate_id` to an observation object was rejected because both observation schemas are strict. Splitting candidate and decision-set contracts per kind was rejected as near-identical schemas that would drift. Deriving parent IDs from a caller-supplied list or from prose was rejected as unverifiable. Relying on `observation_target_binding@0.1.0` to detect a wrong snapshot at Stage 06 was rejected because its pins are deliberately forbidden. Running E1 only at Stage 06 was rejected because E2–E5 are triple-internal and cannot detect a self-consistent forged A. Pinning an input-packet digest whose bytes are never persisted was rejected as unauditable. Writing a stopped `extraction_run` on a non-run route was rejected as asserting a run that never began. Shipping the four schema files ahead of their producers in E-0 was rejected under the repository's own convention and because it would rebaseline the manifest and count guards twice.

### ADR-033 addendum — E-A implementation corrections

**Status:** applied in the E-A increment. This addendum records rules that
ADR-033 did not state and that the E-A test tranche established were necessary.
It adds no contract version and changes no released model.

**Schema registration completed.** The four contracts ratified in text by
ADR-033 now ship with their producers: `extraction_input_packet@0.1.0`,
`extraction_candidate_collection@0.1.0`,
`extraction_validation_decision_set@0.1.0`, and
`extraction_non_run_record@0.1.0`. `schema_version_manifest.json` moves
`0.4.0` -> `0.5.0`, 26 -> 30 entries, and the two schema-manifest SHA guards and
three repository-count guards (457 -> 489) are rebaselined accordingly.

**A capability member disproves Snapshot A; its absence proves nothing.**
ADR-033 fixed routing by pinned identity and forbade role presence as a
discriminator. That prohibition is correct in one direction only. E1 compares
`product_parent` triples, and Snapshot B carries A's product members
byte-for-byte by construction (E3), so E1 alone accepts a Snapshot B supplied
where Snapshot A was expected. Stage 06 and Stage 07 therefore refuse any
snapshot-A input carrying a non-`product_parent` member, with
`parent_context_wrong_snapshot`. This is not the forbidden inference: absence of
capability members still never proves a snapshot is an A, because a legal
Snapshot B may carry zero of them, and a zero-capability B substituted for A
remains indistinguishable by shape and is caught only by E1. The guard is
deliberately one-directional and its limit is pinned by test.

**Every emitted parent snapshot is validated at the single emission point.**
Extraction cannot import `evaluation.parent_observation_snapshot`, so the
locally enforceable invariants of the released model are enforced directly:
canonical `YYYY-MM-DD` `observation_cutoff` by `date.fromisoformat` round-trip
equality; non-empty members; per-member allowed role, safe relative reference,
and lowercase 64-hex digest; and, after canonical sorting, uniqueness by
`(role, reference)` **and** uniqueness of `reference` across roles. A shared
reference would otherwise make one artifact both a product and a capability
parent. Member-reference grammar rejects each empty, `.`, and `..` segment of
the original string rather than `Path.parts`, which silently normalises `a//b`
and `a/.` away. Snapshot A refuses an empty accepted-product set before
emitting, because the released model rejects empty members. Decision sets
hydrated by these builders must declare
`extraction_validation_decision_set@0.1.0`; this is inbound validation of a
governed artifact and is outside the `contract_metadata_forbidden` rule, which
guards only caller channels into an emitted artifact's own root stamp.

**Absence and explicit null are distinct in the harness bridge.**
`SourceDocumentRecord` rejects explicit null for `url`, `mime_type`,
`temporal_validity`, `access_status`, and `schema_version`, and
`SourcePassageRecord` for `heading_path` and `normalizer_version`, while
absence stays legal. Selecting Parquet columns with `row.get()` materialised a
null for every absent column and made an ordinary ingestion row
unrepresentable; rewriting a null into absence would have laundered it. The
bridge copies only the keys a row actually carries and lets the released model
refuse a genuine null. Records are serialised with
`model_dump(mode="json", exclude_unset=True)` for the same reason: a plain
`model_dump()` emits a null for every unset optional, which the released static
corpus schemas reject, leaving the transcoded corpus unloadable by the harness
the bridge exists to feed.

**Rejected alternatives:** Treating the Snapshot B-for-A substitution as
acceptable because the derived product context is identical was rejected: the
packet would then record B as the Stage 06 parent snapshot, which is false
provenance. Adding a new failure code for it was rejected because the ADR-033
code list is fixed and `parent_context_wrong_snapshot` already carries exactly
that meaning. Using `Path.parts` for member-reference grammar was rejected
because normalisation hides the malformed input instead of refusing it.
Rewriting an explicit null into absence in the bridge was rejected as silent
repair under CLAUDE.md rule 9. Emitting corpus records with a plain
`model_dump()` and relaxing the corpus schemas to accept nulls was rejected
because it would weaken a released contract to accommodate a producer.


## ADR-034 — E-P provider connector: Vertex AI Gemini, default-deny, and deterministic preflight

**Decision:** Model execution for Stage 05–07 uses **Google Vertex AI** with **`gemini-2.5-flash`** through the official **`google-genai==2.13.0`** SDK, constructed as `genai.Client(vertexai=True, project=<injected>, location=<injected>, http_options=HttpOptions(api_version="v1", timeout=...))`. Identity is **Application Default Credentials**, provisioned by the user outside this repository in a later increment. The repository holds no credential, key, service-account JSON, secret, token, or environment value, and the connector code reads **no environment variable at all** — the SDK resolves ADC itself, so credential material never passes through project code. That is a structural property, not a redaction pass. The constructor shape is Google's documented public API; no file, snippet, prompt, schema, constant, or output was read from or copied out of any legacy repository (CLAUDE.md rule 1).

**E-P cannot make a live call, as a code path rather than a claim.** `ExtractionProvider` moves to `extraction_provider_protocol_v2` with three members — `assert_run_permitted()`, `client_contract()`, and `complete()`. The Vertex connector refuses unconditionally in **both** `assert_run_permitted()` and `complete()` with `live_call_not_authorized`. **No module under `src/` imports `google.*`; the count is zero, not one.** An SDK factory that nothing could call would weaken the guard from an absolute count to an allowlist, so the factory, the authorization artifact, and the authorized execution path are all deferred to **E-L**; `LiveCallAuthorization` is not defined here. The gate chain is E-P0 (timeout-surface resolution) → E-P (connector, offline qualification) → E-L (live-call authorization) → E-B (SEC-only bounded smoke run). No gate authorizes the next.

**Timeout and retry have one owner each, both resolved by measurement.** The E-P0 gate resolved the SDK timeout surface network-free against the installed source: `google.genai.types.HttpOptions.timeout` is `Optional[int]` in **milliseconds** — proven behaviourally by `_api_client.get_timeout_in_seconds()`, which divides by `1000.0` before handing the value to `httpx`, not merely by the field description. `timeout_duration` is `300000`. The SDK's own retry is disabled **explicitly** with `HttpRetryOptions(attempts=1)`; the field is never left unset, because the released SDK defaults to five attempts and two overlapping retry layers would collide and corrupt the `error_count` accounting. The application policy is 3 total attempts, retrying only HTTP 408/429/5xx and transport timeout, with deterministic delays `[1, 2]` seconds, no jitter, and `fallbacks = []` with no code path able to populate it. `error_count` is the number of failed provider attempts, including failures preceding an eventual success.

**Every deterministic input is resolved before anything exists on disk.** The orchestrator order is: caller-pin sentinel refusal → in-memory packet build → route branch → `require_provider` → `assert_run_permitted()` → `client_contract()` with strict validation, credential-material refusal and canonical bytes → prompt resolution → stage output-schema pin → run-root absence → **only then** `mkdir` and the write-once writes. Three artifact counts are exact and separately asserted: a pre-run refusal publishes **0** artifacts and never calls `mkdir`, so the guarantee is "never created" rather than "cleaned up"; the zero-admissible-passage non-run route publishes **2** and never asks the provider anything; a terminal provider failure publishes **5**. This ordering also closes a real defect: the stage-schema pin was previously verified *after* `complete()` had run and the raw bytes had been written, so a fully deterministic, pre-call-knowable mismatch could only surface once the call had been paid for.

**The caller-supplied contract-pin channel is closed without losing its reason code.** `run_extraction_stage` keeps a keyword-only `provider_client_contract` parameter whose default is a module-private sentinel; any supplied value — including `None` — raises `contract_pin_forbidden`. `None` cannot be the default because it is itself a refused value. The contract bytes are produced by the connector, serialized and written write-once by the orchestrator, and the digest that enters `prediction_artifact_manifest@0.1.0`'s `source_artifacts` is the verified return value of `write_bytes_once`, never a caller assertion. Previously the pin's *form* was validated but the referenced bytes were never re-read, so a contract that did not exist could be pinned.

**Two new strict released contracts.** `extraction_provider_client_contract@0.1.0` carries the declared non-secret execution contract. `extraction_provider_error_record@0.1.0` exists because `extraction_run@0.1.0` carries `status` and `error_count` but **no** `error_reason`, so an errored run alone would lose the terminal cause; that released contract is **not** widened — 15 properties, `additionalProperties: false` — and the reason is bound in the companion record instead, which pins the packet, prompt, client contract, and `extraction_run` by reference and SHA-256. Neither schema has any free-text property, so an upstream exception message, response body, header, or token has **no channel** into an artifact. `reason_code` is a closed 11-value enum; `live_call_not_authorized` is deliberately absent because it is refused before any attempt begins. `schema_version_manifest.json` moves `0.5.0` → `0.6.0`, 30 → 32 entries.

**Import direction is an exact allowlist.** The single permitted edge is `providers → extraction.provider_adapter`, carrying only `ExtractionProvider`, `ProviderRequest`, and `ProviderResponse`. `extraction → providers` is forbidden, as is any edge from `evaluation`, `universe`, `ingestion`, or `collection` into either. Two consequences follow and are deliberate: `providers` cannot import the canonical serializer, so `client_contract()` returns a plain mapping and the orchestrator serializes it — no second serializer, preserving ADR-027 anti-drift; and `providers` cannot import `ExtractionError`, so it raises a neutral `ProviderError` translated at the seam, the same idiom as `translate_write_once_error`. The `extraction` boundary scan becomes recursive so a future subpackage cannot hide from it.

This decision supplements ADR-022, ADR-026, ADR-027, and ADR-033, and is governed by SPEC-027.

**Rejected alternatives:** Placing the connector inside `extraction/` was rejected because the landed boundary guard scanned non-recursively and a subpackage would have been invisible to every network, credential, URL, and clock check. Keeping an SDK factory in E-P was rejected because unreachable code that may import the vendor SDK converts an absolute zero-import guard into a one-entry allowlist for no benefit. Removing the `provider_client_contract` parameter outright was rejected because it would make `contract_pin_forbidden` unreachable and silently accept a caller that believed it was pinning something. Defaulting that parameter to `None` was rejected because `None` is itself a refused value. Adding `error_reason` to `extraction_run@0.1.0` was rejected because it is strict and released. Adding a twelfth enum value for unclassifiable failures was rejected; they collapse to `provider_response_unusable` rather than widening a released contract. Trusting the SDK's default retry was rejected because the default is five attempts and would silently double the retry layer. Writing an unverified timeout unit was rejected outright, which is why E-P0 was a blocking gate rather than an acceptance criterion. Scanning for the *word* "credential" in source literals was rejected after it flagged the very module that refuses credentials; the guard matches credential **value signatures** instead. A bare `token` substring in the key scanner was rejected after it flagged `max_output_tokens`, conflating a token count with a token value. Running the property-set check before the credential scan was rejected because a leaked credential is almost always an undeclared property too, which would have made `credential_material_in_artifact` unreachable for exactly the case it exists to catch.

## ADR-035 — E-L live-call authorization: SPEC-027 chain, byte-identical capture, and the budget-meter seam

**Decision:** The E-P connector gains an *authorized* execution path, opened only by a **two-key handshake**. The connector's half is two explicit constructor arguments — `expected_authorization_sha256` and `max_provider_requests` — neither derived from a file, an environment variable, or any ambient source, both defaulting to `None` so E-P's default-deny remains the default. The runner's half is a verified digest produced after it validates the governance chain. Comparison is constant-time. Neither half alone authorizes a run.

**The SPEC-027 chain is mandatory, not optional.** Three released contracts: `adapter_qualification_record@0.1.0` → `adapter_enablement_record@0.1.0` → `live_call_authorization@0.1.0`. Each record pins exactly one ring above it by reference and SHA-256; the chain is never transitive, and the validator walks upward re-reading and hash-verifying at every step. Per SPEC-027, the **enablement record** carries the SPEC-024 prompt/execution/routing/stage-contract qualification reference — Stage 05–07 is prompt-bearing, so that field is required there and not on the authorization. The authorization additionally pins the provider client contract and the budget-meter identity, so changing the client contract or swapping the meter invalidates it: *"execution-affecting contract changes never inherit enablement"* becomes code rather than prose. `schema_version_manifest.json` moves `0.6.0` → `0.7.0`, 32 → 35 entries.

**The authorization's endpoint allowlist is execution-bound, not merely recorded.** Validating `live_call_authorization.endpoint_allowlist` as artifact content is not sufficient: a connector holding the correct authorization digest and request cap could still carry a broader or different allowlist, and every per-request check inside the capture client would then be measured against the wrong set. The permission handshake therefore carries **three** keys, not two. `assert_run_permitted` is keyword-only and takes both `authorization_sha256` and `endpoint_allowlist`; the runner passes the allowlist it verified from the authorization artifact, and the connector fails closed with `live_call_not_authorized` unless that list is **semantically identical** to its constructor-configured one. Comparison is on normalized endpoints — the same scheme, host, port, userinfo, percent-decoding, and `.`/`..` rules the capture client applies per request, so there is one endpoint grammar rather than two — which means order is irrelevant and a differently written but identical set activates. An empty, missing, malformed, non-sequence, or duplicate-bearing list on either side is refused; a duplicate is rejected because it hides how many distinct endpoints were actually authorized. All of this happens at `[F]`, before prompt loading, meter use, `mkdir`, SDK import, factory construction, or any network, so a mismatch leaves **zero artifacts** and the connector is not left half-activated. Because the keyword-only protocol signature changed, `PROVIDER_PROTOCOL_VERSION` moves to `extraction_provider_protocol_v4` and the connector's closed pin follows; the client-contract schema types that field as an unconstrained string, so no released schema, manifest version, or count changes.

**The stage-output contract identity is bound to the stage, not merely agreed.** Requiring qualification and enablement to *agree* on `stage_output_contract_id`, with a digest equal to the released schema, still admitted two records naming the same arbitrary identity — the identity then asserted nothing about which stage had been qualified. A closed map is enforced instead: `product_extraction → product_observation@0.1.0`, `capability_extraction → capability_observation@0.1.0`, `task_extraction → task_observation@0.1.0`. Both records must carry the mapped identity for the run's stage, in addition to mutual equality and the released-schema digest; a stage with no mapping is refused rather than defaulted.

**A permit is revoked on every exit from the post-handshake region.** `assert_run_permitted` runs at the earliest possible point, which means the permit it grants outlives the client-contract validation, the qualification's execution-contract check, prompt resolution, the meter identity and budget calls, the run-root check, and the write-once artifact writes. Any of those may refuse, and a one-shot permit that is never spent is still *spendable*: a reproduction showed `governance_record_not_effective` leaving the activation live, after which `complete()` reached `provider_response_unusable` instead of `live_call_not_authorized`. `ExtractionProvider` therefore gains `revoke_run_permission`, the protocol moves `v5` → `v6` with the connector pin following, and the whole post-handshake region runs inside a `try/finally` that revokes unconditionally — so a client-contract mismatch, a qualification mismatch, a prompt failure, a meter or budget refusal, an existing or symlinked run root, an artifact-write failure, a terminal provider error, and a successful run all end with no reusable activation. Revocation is required to be **idempotent and infallible**: for the Vertex connector it clears one field and performs no SDK, factory, credential, or network work. Because it is called from `finally`, a failure there could otherwise replace the exception already propagating and hide why the run stopped; the helper therefore surfaces a revocation error only when nothing else is in flight, and a test pins that a broken revocation never masks the original refusal.

**A hash-valid chain is not an in-force chain.** Verifying references and digests proves the three records are the ones that were pinned; it says nothing about whether they are *effective*. Without the rules below a run could be authorized through a revoked qualification, a suspended or expired enablement, a foreign deployment environment, or a rollout state that was never meant to reach the network. **Every released `const` and `enum` in the three governance schemas is therefore re-enforced by the loader**, because no schema file executes on this path — the same lesson ADR-032 recorded when it rejected "schema-validated" as an overclaim. Enforced: all three `schema_version` values exactly `0.1.0`; `adapter_family == model_execution`, since the two adapter families have separate readiness gates; `qualification_status == qualified`, so `superseded` and `revoked` cannot pass as valid enum members; a **closed** rollout→status mapping (`live_dev → enabled_live_dev`, `controlled_pilot → enabled_pilot`, `release_or_research_production → enabled_release`) that refuses `disabled`, `suspended`, `expired`, `revoked`, `mock_only` — which performs no network by definition — and `full_scale`, for which SPEC-027 declares no enabled status and which would be premature scale (CLAUDE.md rule 10); exact `deployment_environment_id` and `rollout_state` equality between enablement and authorization; a timezone-aware, UTC-normalized enablement window that both contains `run_created_at` and **fully contains** the authorization window, so an authorization can neither predate nor outlive the enablement it rests on — checked independently of the run instant, because checking only the instant leaves that containment unverified; `enablement.stage` equal to the run's stage; qualification and enablement agreeing on `stage_output_contract_id`/`_sha256`, with that digest equal to the **actual released stage schema** the run validates against; and the qualification's `execution_contract_id`/`_sha256` equal to this run's **validated provider-client contract**, because SPEC-027 qualifies an adapter *under a specific execution contract* and an adapter qualified under a different digest was never qualified for what it is about to execute. Semantic ineffectiveness fails closed with the new pre-run `governance_record_not_effective`; malformed structure, pins, contract identities, and `schema_version` violations keep `authorization_chain_broken`. Every one of these refusals occurs before `mkdir`, the meter, the factory, and the network, so all of them are **zero-artifact**.

**Endpoint narrowing is enforced provider-side, in one grammar.** The chain is `enablement ⊇ authorization == connector`. An authorization may use *less* than its enablement allows — that is what a run authorization is for — but never more; the connector must be configured for exactly what was authorized; and the capture client checks every request against that same set. `assert_run_permitted` therefore takes a third keyword-only input, `enablement_endpoint_allowlist`, and the protocol moves `v4` → `v5` with the connector's closed pin following. The runner **forwards** both verified lists rather than comparing them: endpoint normalization is provider-side grammar, `extraction` may not import `providers`, and duplicating the rules in `extraction` would create a second grammar that could drift from the one actually applied per request. The subset helper lives beside the equality helper in `providers.authorization` so both use the identical normalization, and either step refuses an empty, malformed, non-sequence, or duplicate-bearing list on either side. The client-contract schema types `provider_protocol_version` as an unconstrained string, so no released schema, manifest version, schema count, or repository count changes.

**Activation is a one-shot, non-replayable permit.** A successful handshake authorizes exactly **one** `complete()` call. Two rules make that true rather than merely intended. First, every `assert_run_permitted` attempt clears any prior permit **before** it judges the digest, cap, or allowlist, so a failed handshake can never leave an earlier success standing and a rejected authorization cannot still be spent. Second, `complete()` **consumes** the permit as its first action, before any factory, SDK, credential, or network work: a success, a terminal provider error, a capture failure, a factory failure, and even a malformed request all spend it alike. Without this, one authorization artifact — with its own predeclared record, request, and cost budget — could fund an unbounded number of calls from a single provider instance, and the budget the runner validated would bound nothing. A second call requires a second handshake, which in turn requires the authorization to still be in its validity window and to still pin this client contract and meter identity.

**Authorization scope, and the validity window in particular.** The authorization must match the run exactly on `stage`, `company_id`, `observation_cutoff_date`, and `corpus_scope`. `effective_at`, `expires_at`, and the caller-injected `run_created_at` are **required timezone-aware ISO-8601 instants**: each is parsed, normalized to UTC, and compared **chronologically, never lexicographically**. Text comparison is wrong rather than merely imprecise — `2026-07-01T00:00:00Z` and `2026-07-01T02:00:00+02:00` denote the same instant yet are unequal as strings, and an offset-bearing timestamp can sort on either side of a `Z` one irrespective of chronology, so a lexicographic test admits out-of-window runs and refuses in-window ones. The interval endpoints are **inclusive**: an instant equal to `effective_at` or to `expires_at` is in window, and a zero-length window admits exactly its own instant. A timezone-naive instant is **refused rather than assumed to be UTC**, because guessing a zone would silently move a boundary by an unknown number of hours. A malformed instant, a naive instant, an inverted window where `effective_at > expires_at`, and an instant outside the interval all fail closed with `authorization_scope_mismatch`. Parsing only: this package still reads no clock, and the window is evaluated against the run's own declared instant.


**The runner changes, and owns the authorization artifact.** The earlier claim that `run_extraction.py` could stay untouched was wrong: writing the authorization write-once and binding it to the prediction manifest is the runner's job. Governance artifacts are read from an **explicitly injected `governance_artifact_root`, separate from the output `artifact_root`** — putting them in the same root would let a run write its own authorization. There is no cwd search, no `Path.cwd()`, and no environment fallback; a pin without a root is `governance_root_required`. Reading reuses the existing containment and hash discipline through a promoted public `hydrate_pinned_artifact`, so no second loader can drift. `REQUIRED_SOURCE_ARTIFACT_ROLES` grows 6 → 7; the released `prediction_artifact_manifest@0.1.0`'s `source_artifacts` is an unbounded tuple, so nothing is widened.

**The meter sees the exact request the provider receives.** `BudgetMeter` is declared on the existing `extraction/provider_adapter.py`, so no new extraction module appears and the 13-module count holds; the `providers` import allowlist stays at three names because the meter is injected into the runner, not the connector. The runner builds **one canonical `ProviderRequest`** and passes that same frozen object to the meter and then to `complete()`, so the prompt text, prompt digest, packet payload, and stage that were metered are byte-for-byte the ones sent. The packet payload and its digest are computed once in memory at `[B]`, and the same `bytes` object is later written, so the metered digest and the persisted digest cannot diverge. Metering happens after prompt resolution — a read-only operation — and **before** `mkdir`, the SDK factory, and the provider, so the zero-side-effect boundary is intact.

**Budget language is precise about what is enforced.** `budget_max_records`, `budget_max_requests`, and `budget_max_output_tokens` are genuinely enforced pre-call by the runner; the attempt cap is `min(3, budget_max_requests)` and the connector applies it internally, so the request bound does not depend on the runner. `budget_max_wall_clock_seconds` is a **compatibility floor** against the policy's theoretical ceiling (3 × 300 s + 3 s = 903 s), not elapsed enforcement — that belongs to the meter. `circuit_breaker_max_consecutive_failures` is **validated configuration only** in a single-call run: no second call is started because the invocation is not retried, and multi-call breaker enforcement is outside E-B. `budget_max_input_tokens` and `budget_max_estimated_cost_micros` are verifiable **only** through the injected meter, and with no meter the run is refused with `budget_meter_unavailable` rather than run unmetered. E-M supplies the real tokenizer, versioned pricing table, and monotonic clock behind the same seam; in-loop per-attempt elapsed enforcement is deferred to it.

**Capture is byte-identical over a public hook.** The SDK discards the raw bytes: `_api_client.py:1465-1467` builds its `HttpResponse` from `[response.text]` on the non-streaming path, and the public `types.HttpResponse.body` is a `str`. Because `httpx.Response.text` is *derived from* `self.content`, a `CapturingHttpxClient` supplied through the public `HttpOptions.httpx_client` hook captures exactly the bytes the SDK then decodes — no encode, no re-serialization, no private `_api_client` surface. The SDK uses the supplied client verbatim (`:817-818`) and declines to close one it did not create (`:2258`), so the lifecycle is ours and closing is guaranteed in `finally`. **Archival unit:** `content` is the HTTP entity body *after* transfer `Content-Encoding` is undone — httpx decompresses gzip/br transparently. That is the JSON payload and the correct thing to archive; it is not the compressed wire bytes, and nothing here claims otherwise. `stream=True` is refused because a streamed response cannot be read as bytes without consuming it. `follow_redirects=False` is set explicitly, **deliberately opposite to the SDK's own default** (`:565`, `:586`), and any 3xx is terminal: no hop to a new endpoint. The endpoint allowlist is checked **before** `super().send`, so an off-allowlist request never opens a socket; matching is on normalized origin plus path at a segment boundary, after percent-decoding and `.`/`..` resolution, with userinfo-bearing URLs refused outright.

**3xx maps to `provider_response_unusable`, and no enum is added.** `errors.APIError.raise_for_response` raises for anything other than 200, and E-P's status map holds no 3xx entry, so the existing fallthrough already yields the right code — measured, not assumed. **Error-response bodies are never persisted.** On the terminal route no raw prediction is written; the body is held in memory, never reaches a `ProviderError`, and is discarded. The only durable evidence of a terminal cause is the closed `reason_code` enum and `attempt_count` of `extraction_provider_error_record@0.1.0`.

**`raw_capture_representation` lives in the envelope.** `prediction_envelope@0.1.0`'s `prompt_model_metadata` is an open `dict[str, JsonValue]` on a released model, and the envelope is hash-bound through `envelopes_sha256` in the prediction manifest, so the representation is auditable in the run artifact chain rather than only in this ADR. `extraction_provider_client_contract@0.1.0` is deliberately **not** changed; a declared counterpart would have required a `0.1.0 → 0.2.0` bump for no additional guarantee.

**Artifact counts are re-derived, not carried over.** Pre-authorization refusal **0**; zero-admissible non-run **2**; terminal provider failure **6** (E-P's five plus the authorization); authorized successful run **8**. E-P's 5 and 7 no longer hold.

**The zero-`google.*`-import guard becomes an allowlist of exactly one.** E-P shipped zero such imports under `src/`; E-L raises that to one — `providers/sdk_factory.py` — and the guard is now an exact allowlist naming that file rather than a count. This is a weakening, recorded as such. The import is lazy, inside the factory body, so importing the module or the connector pulls in nothing, and the factory is reachable only after the handshake.

**Two limits stated plainly rather than papered over.** A caller inside this process that deliberately fabricates both the digest and the cap satisfies the connector handshake; and the meter identity pin enforces expected operational identity without structurally preventing an in-process implementation from imitating those values. Both are `noncanonical_experiment` under SPEC-027, require separate approval, and may never enter an evaluation or production record. What is guaranteed is **detectability** — a canonical run carries eight artifacts with the authorization bound as the seventh manifest role — not prevention.

**E-L makes no live call.** No real meter, no ADC, no real `genai.Client`, no HTTP. Every test drives injected fakes. Concrete budget numbers, `deployment_environment_id`, rollout state, and the Vertex project ID are **not** in this repository; they belong to the E-B authorization artifact, supplied outside it. Gate chain: E-L → **E-M** (budget meter) → E-B; E-B's live-call gate cannot open without E-M, enforced by `budget_meter_unavailable`.

This decision supplements ADR-022, ADR-026, ADR-027, ADR-033, and ADR-034, and is governed by SPEC-027 and SPEC-024.

**Rejected alternatives:** Making the SPEC-027 chain optional or two-ringed was rejected because the spec requires qualification, enablement, and run authorization for model-execution adapters. Placing the SPEC-024 prompt-qualification reference on the authorization was rejected because SPEC-027 places it on enablement. Claiming `run_extraction.py` need not change was rejected as false once the runner owns the authorization artifact. Extending `ProviderRequest` with `company_id`, cutoff, and scope was rejected because those are authorization context, not provider payload, and moving them there would hand the connector an authority the two-key handshake exists to split. Reading governance artifacts from the output `artifact_root` was rejected because a run could then write its own authorization. Any cwd or environment fallback for the governance root was rejected as ambient resolution. Using `sdk_http_response.body` was rejected because it is a `str` and encoding it would fabricate the bytes raw-before-parse exists to preserve. Using `_api_client.HttpResponse.byte_segments` was rejected as a private surface incompatible with an exact version pin. Following redirects was rejected because it would let a 3xx carry a request to an endpoint outside the allowlist. Mapping 3xx to `vertex_unavailable` was rejected after measurement showed the existing fallthrough already yields `provider_response_unusable`; adding a twelfth enum value was rejected for the same reason. Archiving error-response bodies was rejected as a new artifact and a new leak surface. Adding a declared `raw_capture_representation` to the client contract was rejected because it would bump a released contract for no additional guarantee. Claiming that a fake meter is structurally refused in E-B was rejected as untrue. Claiming that E-L enforces input-token or estimated-cost limits was rejected because no tokenizer or price table exists yet, which is why E-M is a blocking gate rather than an acceptance criterion. Keeping the zero-import guard as a count was rejected because the factory must import the SDK somewhere; an exact allowlist naming one file was preferred to a silent count change.

## ADR-036 — E-R canonical provider-request materialization: rendered contents, derived company identity, and the explicit single pass

**Decision:** The run now sends the packet. Before E-R the connector called `generate_content(contents=request.prompt_text)` and `request.payload` was never passed to the SDK at all, while `prompts.load_prompt` performed no template expansion by design — so `prompts/extraction/product_discovery_recall.md` still carried literal `{{company_name}}`, `{{cutoff}}` and `{{passages_with_ids}}`. A live call would therefore have handed the model a frozen instruction template with three unresolved markers and **no** company identity, observation cutoff, or HubSpot passages. The packet was metered and persisted but not transmitted. This was a live defect, not a gap in the design lock, and no smoke run could have been authorized while it stood.

**One representation, not two.** `extraction/contents_renderer.py` (`extraction_contents_renderer_v1`) emits a single canonical UTF-8 document. Those exact bytes are what the connector sends as `contents` and what the run persists at `inputs/rendered_provider_contents.md`, so "what was archived" and "what was sent" are one object rather than two views that can drift. Passages are ordered by `(source_id, passage_id)` with explicit delimiters, so arrival order cannot leak into the bytes; offsets are omitted because the manifest already binds them and they would only spend input tokens. The extraction module count moves **13 → 14**; ADR-035's claim that the 13-module count would hold is superseded, recorded as a change rather than glossed.

**`rendered_contents` is the sole provider-input authority.** `ProviderRequest` moves to `extraction_provider_protocol_v7` carrying `stage`, `rendered_contents`, `rendered_contents_sha256`, `prompt_sha256`, `input_packet_sha256`. `prompt_text` and `payload` are **removed**, not merely unused: keeping either would leave a second authority from which a connector could rebuild its own representation, and removal makes that structurally impossible rather than merely discouraged. `prompt_sha256` remains the digest of the raw frozen template and is provenance only; the two digests differ by construction. The `providers → extraction.provider_adapter` edge still carries exactly three names — E-R changes the request's shape, not the size of the import edge.

**Binding is a closed, stage-scoped map, and its gaps are recorded.** Only `product_extraction` is bound: `{{company_name}}` → the derived legal name, `{{cutoff}}` → `observation_cutoff_date`, `{{passages_with_ids}}` → the canonical passage block. Both `capability_extraction` and `task_extraction` are outside `MATERIALIZATION_SUPPORTED_STAGES`, and the renderer refuses **both** with `contents_placeholder_unbound` until E-S. Whether a prompt happens to carry markers is irrelevant to that gate: `capability_extraction.md` contains no placeholders and `task_discovery_recall.md` carries four, but neither stage can be materialized, because rendering a placeholder-free capability prompt would send an instruction naming no validated products at all. **E-C and E-D remain blocked until E-S.** At runner level the refusal route depends on what the invocation supplies, and both routes are tested. **Without** the required parent pins the packet builder refuses first with `parent_context_missing`, before the permit handshake — nothing is activated, so nothing is revoked. **With** fully valid, hash-pinned parent context — Snapshot A plus product decisions for Stage 06, and Snapshot A, Snapshot B plus product and capability decisions for Stage 07, alongside a stage-matched governance chain and a valid `@0.2.0` identity pin — every preflight succeeds, `assert_run_permitted` **is** reached, and the **renderer** is what refuses with `contents_placeholder_unbound`, after the handshake but before `mkdir` and before any provider call, followed by exactly one revocation. Neither route creates a run root or enters the SDK factory. A placeholder the map does not name is refused rather than left in place; a marker introduced by a substituted value is caught on a re-scan with `contents_placeholder_unresolved`. Both refusals happen before `mkdir`, the SDK factory, and the provider, so an unresolvable prompt costs zero artifacts.

**Company identity is derived from a hash-pinned admission artifact.** `extraction_input_packet@0.1.0` is released and unchanged: it carries `company_id` but no name field at all, so it cannot render a prompt needing a legal name, and binding `{{company_name}}` to a CIK while calling it a legal name was rejected. `extraction_input_packet@0.2.0` adds `company_identity_reference`, `company_identity_sha256`, and a builder-derived `legal_name`. The pin is **mandatory**; the *claim* is forbidden — a caller supplies a reference and a digest, and `legal_name`, `company_identity` or `company_name` from a caller raises `company_identity_pin_forbidden`. `company_identity_root` is a **runner/builder argument, never a packet field**: the packet records what it was pinned to, not where it was read from, and no path from the root appears in the artifact. Hydration reuses the existing containment and hash discipline through `hydrate_pinned_artifact`; there is no cwd search, no repository search and no environment fallback. Four equalities must hold against the admission artifact — `company_id`, the zero-padded `cik`, `observation_cutoff_date`, and a non-blank `legal_name` — because reconciling only the name would let a packet borrow a name from a different firm or a different observation year while still hash-verifying. A caller supplying neither pin still gets `@0.1.0` byte-for-byte, so every pre-E-R caller is unaffected, and the authorized route refuses a `@0.1.0` packet with `company_identity_pin_required` rather than sending a placeholder.

**The single pass is an explicit decision, not the by-product of indexing.** `product_extraction` registers two prompts: a high-recall discovery pass and a precision consolidation pass that consumes the first pass's output. `single_pass_prompt_plan` executes the first only and records `prompt_pass_index = 1`, `prompt_sequence_length = 2`, `prompt_sequence_complete = false` into the envelope's `prompt_model_metadata`, which is an open dict on a released model and is hash-bound through `envelopes_sha256`. A single-pass result is a recall-oriented candidate set and **must never be described as a complete product universe**.

**Counts re-derived.** `prediction_artifact_manifest@0.1.0`'s `REQUIRED_SOURCE_ARTIFACT_ROLES` grows **7 → 8** with `rendered_provider_contents`; `source_artifacts` is an unbounded tuple on the released model, so nothing is widened. A successful authorized run publishes **9** artifacts and a terminal provider failure **7**. `schema_version_manifest.json` moves `0.7.0` → `0.8.0`, 35 → 36 entries, registering the successor beside the unchanged `@0.1.0`. The v0.1 client contract now pins protocol v7 and gains **no** E-M thinking or metering field; those belong to E-M0 and E-M, which remain unauthorized.

**E-R makes no live call.** No countTokens, no pricing, no thinking configuration, no `BudgetSession` implementation, no evidence fetch, no ADC resolution, no real client. Every test drives injected fakes, and `data/` is byte-identical.

This decision supplements ADR-033, ADR-034, and ADR-035, and is governed by SPEC-008 and SPEC-027.

**Rejected alternatives:** Accepting a caller-supplied company name was rejected because the name would then assert nothing verifiable; binding `{{company_name}}` to the CIK was rejected because an identifier is not a legal name. A separate company-identity artifact alongside the packet was rejected because it would create a second identity authority next to `packet["company_id"]` — the same divergent-authority defect that removing `prompt_text` exists to prevent. Modifying `extraction_input_packet@0.1.0` was rejected because it is released and strict. Recording `company_identity_root` in the packet was rejected as leaking a local path into an artifact. Emitting a structured parts object *and* a text projection was rejected because two representations of the same request can drift, which is precisely what ADR-035 warned about for capture. Leaving `prompt_text` on `ProviderRequest` as "provenance only" was rejected because a field a connector can read is a field a connector can use. Binding the task-stage placeholders with plausible values was rejected as guessing; failing closed until E-S is the honest state. Keeping `prompts_for_stage(stage)[0]` implicit was rejected because a silent first-of-two pass reads as a complete extraction.

## ADR-037 — E-C-D documentation evidence collector: generic adapter, frozen routes, and the attempt receipt

**Decision:** E-M-S cannot collect its own evidence, so a governed collector lands first. Measured before deciding: `collection/` had **zero** network capability — only `urllib.parse` for parsing — and `collection/transport.py` declares policy, contracts and redirect/robots types but contains no fetch, no send and no `httpx`. The single `httpx` importer under `src/` was `providers/response_capture.py`, endpoint-allowlisted to Vertex operations and unusable for documentation. The one raw-collection precedent confirms the hazard rather than excusing it: `data/raw/sec/…/collection_receipt.json` has `contract`, `collection_client`, `code_commit`, `spec_version` and `run_created_at` all `None` with an empty `initial_requests`, so it does not conform to `web_collection_receipt@0.1.0`, and `data/raw/**` is gitignored. Those bytes came from an uncommitted client that left no reproducible provenance. Repeating that is what this increment exists to prevent.

**Two components, not one networking module.** `collection/http_adapter.py` is a generic, URL-policy-neutral single-send adapter: it follows no redirects, authorizes no URL, and reports status, `Location`, headers, final request identity and — only when asked — accepted decompressed entity bytes. `collection/documentation_policy.py` owns every decision: the three frozen `(requested, final)` pairs, HTTPS-only, exactly one hop, spacing, the byte ceilings and write-once persistence. The adapter is imported by that one production module and by nothing else.

**`collection.transport.follow_redirects` is neither duplicated nor replaced.** It permits a hop only inside the official apex or a declared archive host, within five hops, keyed on a request-plan entry — semantics ADR-032 hard-binds to the HubSpot run. The documentation routes cross apexes and need exactly one hop against a frozen pair list. Reusing it would mean loosening a hard-bound official-web guarantee for an unrelated purpose, so it remains the sole authority for official-web collection while the documentation policy implements its own rule over the same generic adapter. `collection.transport.CLIENT_CONTRACT` is untouched; two new versioned identities own the new values: `documentation_transport_client@0.1.0` (adapter module/version, user agent, timeouts, retry rule, redirects-disabled flag) and `documentation_acquisition_policy@0.1.0` (the ordered pairs, one-hop rule, spacing, ceilings, timestamp mode).

**Three measured facts corrected three wrong assumptions.** `httpx.Timeout(30.0)` resolves on the installed `httpx==0.28.1` to `connect/read/write/pool = 30.0` each — **four phase deadlines, not one 30-second total**; no total wall-clock ceiling is claimed because none is implemented. `httpx.Client(trust_env=False, verify=True)` **still creates a keylog file** when `SSLKEYLOGFILE` is set, so `trust_env=False` does not provide that guarantee: presence is refused before any SSL-context or client construction, the value never read, logged or interpolated. A reused client **sends `Cookie` on the second request** after `Set-Cookie` on the first, so the adapter constructs one client per send and closes it; a fresh-client regression proves request two carries no `Cookie`, and `Authorization` is never set.

**Exactly one hop, because all three pairs differ.** The initial response must be `301` or `308`; `Location` must be **absolute `https://`** and resolve byte-exactly to the frozen final URL; the terminal response must be `200 text/html`. A **direct 200 at the requested URL is refused** — under a "maximum one hop" reading it would have been silently accepted, which is why the rule is *exactly* one. Relative resolution is not implemented, so it cannot be ambiguous. `response_request_identity_mismatch` is checked **before** status, `Location` or any byte is trusted, so a transport that answers a different URL cannot influence the route.

**Redirect bodies are never evidence.** An accepted redirect is inspected for status and headers only and closed without body iteration, so a hostile multi-megabyte redirect payload is never downloaded. Only terminal `200 text/html` bodies are streamed in 64 KiB chunks, capped at **8 MiB** each, hashed and persisted. `TOTAL_ACCEPTED_ENTITY_BYTES_MAX = 3 × 8 MiB = 24 MiB` is **derived and defensive**: with three entries each capped at 8 MiB it is redundant, and three individually under-cap documents cannot cross it. `entity_too_large` is the independently reachable production refusal; `attempt_byte_ceiling_exceeded` is a drift branch exercised only through a parameterized accumulator, and that classification is recorded here so no reader infers a live route.

**No injectable transport on the public surface.** `collect_documentation_evidence` takes no `transport_send` and no `sleep`: a caller-supplied fake could otherwise be recorded under the canonical contract identity, breaking executable-client provenance. It constructs the committed adapter itself and records the hashes it actually used. There is no `url` parameter — the routes are frozen constants. Offline tests patch module-private seams absent from `__all__`; a patched seam is explicitly `noncanonical_experiment` and writes only under `tmp_path`.

**The clock is required and injected.** `retrieval_clock` has no default and no fallback; it is called once per attempted entry, after spacing and before the send, and its value is validated as a strict timezone-aware UTC RFC3339 instant **before** sending. Validation is **lexical and semantic**: the `Z`/`+00:00` restriction is kept, and the instant is also parsed, so `2026-02-30T09:00:00Z` and `2026-07-31T24:00:00Z` — which a regex admits but which name no instant — are rejected. `run_created_at` is validated the same way and fails with `attempt_identity_invalid`. An invalid clock value is `retrieval_clock_invalid`, a raising clock is `retrieval_clock_failed`; either fails that entry with **zero sends**, `retrieval_timestamp: null`, and later entries `not_attempted`, with earlier objects preserved. `retrieval_timestamp_mode = "caller_injected_request_start_utc_v1"` travels in both the policy contract and every receipt. Spacing calls `sleep(2.0)`, a fixed interval, **before every send after the attempt's first** — a run has six possible sends, so a full success produces exactly five delays, including the delay between an accepted redirect and its terminal request. An earlier per-entry-only rule would have issued two. The package still reads no wall clock.

**The receipt schema is validated from bytes and its digest derived.** The caller supplies raw schema bytes, never a digest; a supplied `receipt_schema_sha256` refuses with `receipt_schema_claim_forbidden` through a module-private sentinel, so the refusal is reachable rather than a bare `TypeError`. Validation is a **strict manual loader**, not `jsonschema`: that package sits in the `dev` extra while **11 modules under `src/` already import it**, and deepening that pre-existing packaging inconsistency was rejected — `pyproject.toml` is unchanged because `httpx>=0.27` is already a base dependency. The loader pins `$schema`, `$id`, `type`, `additionalProperties`, the top-level and nested property/required sets, and both enums, and treats **`properties.contract.const` as the contract identity** — `$id` is a bare filename and `title` is descriptive across this repository.

**One canonical serializer.** The adapter contract, the policy contract, the attempt-identity payload and the receipt all use `collection.publication.canonical_json_bytes` — sorted keys, compact separators, UTF-8, exactly one trailing newline — so no artifact in this package can drift from the convention every other collection artifact already follows. Byte equality and the single trailing newline are pinned by test across all three surfaces.

**The Content-Type grammar is parsed, and its charset must be a real token.** Only case-insensitive `text/html` with at most one `charset` parameter whose value matches the RFC 7230 token grammar is accepted; `text/html; boundary=evil`, `charset=`, `charset==`, `charset=""`, `charset=utf 8`, `charset=" "`, `charset=utf-8=evil`, a second parameter, a duplicate parameter and `text/htmlx` are all refused — a truthiness check on the parameter admitted five of those. Validation parses a **copy**; the receipt stores the **observed header verbatim**, including surrounding and internal whitespace, so it reports what the server actually sent. `Content-Length` remains advisory: the cap is enforced on accepted decompressed bytes.

**Filesystem escapes are closed.** Reuse requires a **regular, non-symlink** file whose re-read digest equals its path digest; a matching symlink is refused rather than followed, because the bytes it points at are not the bytes the path claims to hold. Every governed path component — raw root, `attempts/`, evidence-kind directory, digest directory, the document itself — is checked for a symlink, so a symlinked directory cannot redirect a write outside the intended root, and a directory or other non-regular object at `document.html` is refused. A symlinked raw root or `attempts/` refuses with `attempt_root_unsafe` before any request. `mkdir`, read and write failures are translated into the closed vocabulary: **no raw `OSError` crosses the public boundary**, and no upstream path or message travels with it. Pre-existing objects are never deleted by a refusal.

**One constructor is the single source of truth for the receipt schema.** `expected_receipt_schema()` builds the complete locked definition, the committed file is generated from it, and the loader compares supplied bytes against it with a **recursive, JSON-type-exact** comparator that also **refuses duplicate member names at any depth**. Ordinary Python deep equality is not type-exact for JSON — `True == 1` and `False == 0` — so a plain `!=` accepted `minLength: true` for `minLength: 1` and `additionalProperties: 0` for `false`, and `3 == 3.0` erased the integer/number distinction; type identity is now checked before value equality, with `bool` separated from `int`. `json.loads` silently keeps the last of a repeated member, so `{"a": 1, "a": 1}` parsed to one member: an `object_pairs_hook` refuses duplicates even when the values are identical, because which definition governs is otherwise ambiguous. `properties` and `required` are type-guarded before use, so no malformed shape leaks `AttributeError`, `TypeError`, `KeyError` or a raw parser error; `receipt_schema_contract_mismatch` is reserved for a shape that actually *names* another contract — `properties` a dict, `contract` a dict, and `contract.const` a **non-blank string** different from this one. A missing `const`, or one holding null, a bool, a number, a list, an object or a blank string, identifies nothing and is a weakening rather than a foreign contract, so it falls through to the type-exact comparison and refuses with `receipt_schema_invalid`. The correct string continues to that comparison normally, so a right name paired with a weakening is still `receipt_schema_invalid`. Formatting remains outside the comparison: an equivalent schema with different indentation or key order is accepted, and the digest is always derived from the exact bytes supplied. A hand-written checklist was rejected after it was shown to pass eight real weakenings — an emptied top-level `allOf`, an emptied entry condition, removed `content_type` nullability, a widened `http_status.maximum`, a changed `redirect_chain.maxItems`, a foreign `object_disposition` value, `retrieval_timestamp.pattern` replaced with `".*"`, and a relaxed `code_commit.minLength`. A checklist only verifies what someone remembered to list. This is **not** a raw-file SHA constant either: JSON is parsed first, so formatting may differ while semantics may not. The loader remains **runtime-`jsonschema`-free**; tests exercise the committed schema with `Draft202012Validator`.

**Terminal sequencing is exact, not merely counted.** Only four sequences are permitted, expressed as a positional `oneOf`: `completed` with `succeeded, succeeded, succeeded`, and `stopped` with `failed, not_attempted, not_attempted`, `succeeded, failed, not_attempted`, or `succeeded, succeeded, failed`. A "stopped has exactly one failure" rule alone accepted `not_attempted, failed, succeeded` — a run that cannot have happened, because the collector stops at the first failure. Every permitted sequence and eight impossible permutations are pinned with a real validator.

**Each status pins its own payload.** `succeeded` requires `redirect_chain` equal to **that entry's own** `[requested_url, final_url]`, `http_status` 200, non-blank `content_type` and `content_encoding`, `byte_count >= 1`, lowercase 64-hex `content_sha256`, non-blank `raw_reference`, `object_disposition` in `{created, reused}`, a real UTC `retrieval_timestamp`, and a null `failure_reason`. `failed` and `not_attempted` require an empty `redirect_chain` and every payload field null, with `failed` carrying an entry-recordable reason and `not_attempted` none. The earlier schema accepted a succeeded entry with null `content_type` and an empty or borrowed chain.

**The builder fails closed too.** `build_documentation_receipt` previously returned schema-invalid receipts such as `entries=[]` with `completion_status="stopped"`, and a serializer test relied on that. It now validates the three positional identities, every property set and type, the four permitted sequences, each status-specific payload invariant, and the top-level identity, digest and timestamp fields — timestamps semantically, not by regex. **The collector can never publish bytes its own schema rejects**, and that is proven by validating every builder output against the committed schema.

**Entry-recordable versus public-only reasons.** The public vocabulary is 27 codes; the subset an entry may record excludes the seven that cannot truthfully appear inside a successfully published receipt — the four preflight schema/identity refusals, `attempt_root_exists`, `attempt_root_unsafe`, and `receipt_publication_failed`. `tls_keylog_environment_present` **is** entry-recordable, because a keylog can appear between sends. A drift test binds the subset to the policy vocabulary so the two cannot diverge. `FROZEN_ENTRY_IDENTITIES` is duplicated in the receipt module deliberately, so the contract stays checkable without importing the orchestrator it validates, and a drift test pins the two declarations together.

**Ordering, and what a failure costs.** Claim refusal → keylog preflight → schema validation → contract derivation → `attempt_id` → duplicate-root refusal → **attempt-root creation** → sends and persistence → terminal receipt. Everything before the root leaves **zero artifacts and zero sends**, and a duplicate attempt issues no request at all. Content objects are content-addressed: absent → `created`; present and re-reading to the path digest → `reused`, never overwritten; present and mismatched → `content_object_corrupt`. **Object presence never authorizes skipping a request**; reuse is decided only after the bytes are in hand. The one write-once receipt lives outside any digest directory so it remains writable when the first entry fails before any hash exists, and it represents prior successes, the failing entry and later `not_attempted` entries separately.

**Retrieval status is not evidence adequacy.** This receipt owns `retrieval_status` only; a successfully persisted navigation shell is a successful retrieval. Whether the bytes contain the required official claim is a later judgement owned by `documentation_evidence_validation@0.1.0`, so `evidence_body_unusable` is never a collection failure reason.

**Recorded weakening.** The `httpx`-imported-by-exactly-one-module invariant becomes an **exact allowlist of two** — `providers/response_capture.py` and `collection/http_adapter.py` — the same pattern ADR-035 used when the zero-`google.*`-import guard became a one-entry allowlist. The collection URL-literal guard likewise moves from "one exempt module" to a named set of three, each with a **bounded** test proving it holds only its frozen pairs or the JSON Schema dialect URI. `schema_version_manifest.json` moves `0.8.0` → `0.9.0`, 36 → 37 entries.

**E-C-D makes no live call.** No URL is retrieved, nothing is written under `data/`, no ADC, no SDK client, no provider operation. Every transport test uses `MockTransport` or a stub and every filesystem test uses `tmp_path`. Gate chain: E-C-D → E-M-S acquisition → E-M implementation → E-B.

This decision supplements ADR-030, ADR-031, ADR-032, ADR-035 and ADR-036.

**Rejected alternatives:** Placing all networking inside a documentation module was rejected because it would fuse a reusable transport with one policy and make a second consumer impossible without duplication. Reusing `web_collection_receipt@0.1.0` was rejected on measurement: its `$defs/request_record` does carry `final_url`, `http_status`, `redirect_hops`, `retry_count`, `byte_count` and `content_sha256`, but the contract requires `company_id`, `request_plan_sha256`, `spec_version`, `prompt_hash` and `model_route`, has no `content_type` or `evidence_kind`, and cannot express `not_attempted`. Loosening `follow_redirects` to cross apexes was rejected as weakening a hard-bound official-web guarantee for an unrelated purpose. Accepting an injectable transport on the public API was rejected because a fake could then be recorded under the canonical identity. Accepting a caller-supplied schema digest was rejected for the same reason a caller-supplied legal name was rejected in ADR-036: the pin is derived, the claim forbidden. Treating `WebFetch` output, curl, browser extraction or an ad hoc script as authoritative raw-byte provenance was rejected — the first returns model-summarised markdown with no digest and produced navigation shells for two of three pages during E-M0. Placing the only receipt inside a digest directory was rejected because a zero-byte first failure has no digest to name one. Claiming a 30-second total wall-clock deadline was rejected once measurement showed four phase deadlines. Relying on `trust_env=False` for the keylog guarantee was rejected once measurement showed the file is still created.

## ADR-038 — Documentation collection receipt v0.2.0: observations survive a refusal (E-C-D1)

**Status:** Accepted.

**The measured defect.** The single authorized E-M-S acquisition
(`docattempt-f88b54ac65e04d0766d749cb606bcee2`, receipt SHA-256
`c5c8980d888517604581a4b491b51939c5ea8ee109eec31eddbcbf49952485bf`) stopped on its
first entry with `redirect_location_mismatch`. That receipt **retains only the
sanitized response-derived failure classification**. It contains no field-level
response observation: the concrete HTTP status, the request-start timestamp, the
observed `Location` value and the partial request chain were all discarded, and
`final_url` holds the *frozen expected* URL — an a-priori constant pinned by
`{"const": …}`, never an observation. The reason code proves only that a response
was received, that its status was 301 or 308, and that the `Location` was
non-empty, absolute HTTPS and unequal to the frozen expected final URL. **It does
not establish the new target value**, and no governed evidence currently does.

**Why a successor rather than a repair.** The erasure is enforced at three
layers, not one. `_fetch_entry` raised before assembling any record, so the
established facts died with the frame; `_blank_entry` then rebuilt the entry from
the frozen constants and a reason code alone. Independently, the 0.1.0 builder
refuses a `failed` entry carrying any non-null payload field, and the 0.1.0
schema pins every one of them to `{"const": null}`. A collector that recorded the
truth **could not publish a receipt at all** under 0.1.0. The defect is therefore
contractual, and 0.1.0 is never modified: it stays byte-frozen so the live
receipt remains verifiable against the exact contract that produced it. A
successor collision is structurally impossible — the receipt contract id and the
policy digest both feed the attempt identity, so the v0.2.0 collector cannot
derive the existing attempt root.

**`redirect_chain` becomes `request_chain`.** Under 0.1.0 the field could only
ever hold two frozen constants, so it carried no observation whatsoever. It now
means *URLs this collector initiated a request for, in order*, and a name
containing "redirect" would invite a future reader to write the observed
`Location` into it. It is schema-pinned per frozen entry to **exactly three
constant values** — `[]`, `[requested_url]`, `[requested_url, final_url]` — so an
observed `Location` is *structurally* incapable of entering it. That guarantee is
checkable from the schema alone, without trusting the collector, and it is what
separates recording from authorizing: an observation is never followed merely
because it was observed.

**The 20-field entry.** The thirteen applicable 0.1.0 fields are retained,
`http_status` is removed (superseded by `terminal_observed_status`),
`redirect_chain` is renamed, and seven fields are added: `failure_phase`, plus an
observed status, observed location and location disposition for each of the two
possible sends. Payload rules are conditioned on **both** status and phase, under
`additionalProperties: false`.

**Seven phases, twenty reasons.** `entry_preflight`, `redirect_request`,
`redirect_evaluation`, `terminal_preflight`, `terminal_request`,
`terminal_evaluation`, `persistence`. Every entry-recordable reason maps to the
phases it can truthfully arise in, and the map is bound to
`ENTRY_RECORDABLE_REASONS` by a drift test so a new code cannot be added without
a phase. The phase is **derived from the accumulator's state**, not a static
lookup, so a reason reachable from two points reports where it actually happened:
`response_request_identity_mismatch` raised inside the adapter lands on
`*_request` (no `AdapterResponse` escaped), and raised by the policy with a
response in hand lands on `*_evaluation`. A `persistence` failure records the
accepted entity facts — `content_type`, `content_encoding`, `byte_count`,
`content_sha256` — and leaves `raw_reference` and `object_disposition` null,
because the entity was real and no object exists. The schema pins phase to
payload; the builder additionally pins reason to phase.

**What an observed location is.** Exactly the adapter-exposed Python string
returned by the pinned `httpx` `Headers.get("location")` surface, before any
policy parsing, normalization, resolution, percent-decoding, truncation or
authorization comparison. It is **not** wire bytes, **not** a byte-verbatim HTTP
field, and it does **not** preserve duplicate header-line boundaries. Measured on
the installed httpx 0.28.1: response headers decode with `iso-8859-1`, so
`b"...\xe9\x01x"` surfaces as `'…é\x01x'`, and two `Location` field lines surface
through `.get()` as the single joined string `'https://a.test/x, https://b.test/y'`
(`get_list` would preserve them, and the adapter does not call it). If duplicate
lines are combined, the combined string **is** the observation; it is recorded
under the transcription policy and never split.

**Transcription, never truncation.** `no_response` when the hop was never
answered; `absent` when a response carried no `Location`; `rejected_oversize`
above 2048 characters; `rejected_uncharacterizable` for any character outside
`U+0020`–`U+007E`; otherwise `recorded` with the string unchanged. A shortened URL
is a fabricated artifact, so an untranscribable value is refused outright and the
disposition says why. `no_response` and `absent` are deliberately distinct:
collapsing "never asked" into "asked, got nothing" would reintroduce exactly the
class of untruth this contract removes. Classification is orthogonal to
authorization — a value may be `recorded` and still refused by the route grammar.
The charset rule is measurement-backed rather than defensive guesswork: the
pinned surface demonstrably can deliver `\x01`, `\t` and `é`.

**The exception guarantee, and its stated limits.** Entry-level refusals travel
on a module-private `_EntryRefusal` carrying **only** a closed-vocabulary reason
code and phase — never a message, never a value — and the observation accumulator
is owned by the *caller*, so it outlives the refusal without ever riding on an
exception. Every rendered `CollectionError` message is a constant; no observed
value reaches `str`, `repr`, `args`, `reason_code`, `detail`, `stop_reason`, any
intentionally exposed attribute, or an explicit `__cause__` chain. A dynamically
selected reason code is permitted after closed-vocabulary validation — an
AST-shape rule requiring only constants would have been impossible, because
`_persist_object` legitimately selects between `destination_exists` and
`write_error` and forwards the result through a local.

**Two residual limitations, stated rather than hidden.** (1) `raise … from None`
clears `__cause__` and sets `__suppress_context__`, but CPython still retains the
upstream object in `__context__` — measured. `http_adapter.py` is outside this
increment's path set, so that retention is documented, pinned by a regression
that fails loudly if it ever changes, and never rendered, serialized into a
receipt, or exposed as governed provenance. (2) Reasons raised *inside* the
adapter — `transport_timeout`, `transport_failed`, `entity_too_large` and
adapter-side `response_request_identity_mismatch` — destroy the `AdapterResponse`,
so no observed status can accompany them without an adapter change, which
v0.2.0 deliberately does not make.

**The observed location is bound to its disposition.** The first cut of this
contract declared the two fields independently, which let three untruthful shapes
through both the schema and the builder: a null location claiming `recorded`, a
non-null location claiming `absent` (or any other non-recorded disposition), and
a non-printable or blank value claiming `recorded`. Each describes an observation
that did not happen, which is the same class of defect this ADR exists to remove.
Both layers now enforce the binding in both directions, per observation pair:
`recorded` requires a non-blank string of at most 2048 characters, every
character in `U+0020`–`U+007E`; every other disposition requires null; and
therefore a non-null location implies `recorded`. `transcribable_location()` is
the single definition shared by the classifier, the builder and the committed
schema's predicates, so the three cannot disagree.

**Charset is decided before the space-only rule.** The locked order is: no
response → `no_response`; `None` or empty string → `absent`; non-string →
`rejected_uncharacterizable`; length above 2048 → `rejected_oversize`; any
character outside `U+0020`–`U+007E` → `rejected_uncharacterizable`; a non-empty
run of **ASCII `U+0020` alone** → `absent`; otherwise `recorded` unchanged. The
first cut tested emptiness with a bare `str.strip()` *before* the charset check,
which strips `\t`, `\n`, `\r`, `\x0b`, `\x0c` and every Unicode whitespace
codepoint — so `"\t"`, `"\n"`, `"\r"`, `" "`, `" "` and `" \t "` were
all classified `absent`, a benign disposition concealing forbidden characters.
Only `U+0020` may reach the space-only rule, which is why that rule tests
codepoints explicitly rather than calling `strip()`. `length before charset` is
preserved, so an over-long value carrying a control character is still reported
`rejected_oversize`. An ASCII-space-only `Location` is `absent` because it
arrived and names no target; recording it would claim an observation of nothing.

**The anchored pattern was replaced by two independent predicates.** JSON Schema
`pattern` is a **search**, not a full match, and in the installed engine `$` also
matches immediately before a final newline. The first cut used
`^[\x20-\x7e]*[\x21-\x7e][\x20-\x7e]*$`, which `re.search` accepts for `"x\n"` —
measured — while `transcribable_location()` and the builder reject it. The
committed schema was therefore strictly weaker than the code it was supposed to
mirror, and the divergence was invisible to the `re.fullmatch` check that had
been used to verify it. The anchor is gone: `recorded` now requires an
unanchored `[\x21-\x7e]` (at least one non-space printable) **and**
`not: {"pattern": "[^\x20-\x7e]"}` (no character outside printable ASCII),
alongside the existing `minLength`/`maxLength`. Neither predicate depends on
anchoring, so no end-of-string subtlety can weaken either, and both remain
portable JSON Schema — no Python-only `\A`/`\Z`. Regression cases for `"x\n"`,
`"x\r"`, `"x\r\n"`, `"\nx"`, `"x\t"`, `"x "`, `"x\v"`, `"x\f"` and
`"x "` run through `Draft202012Validator` against the committed **bytes**,
for both observation pairs and for succeeded and failed entries, because
exercising the real validator rather than `re.fullmatch` is what exposed the
defect.

**The adapter-side keylog recheck was an unpublishable path.** `send_once`
performs its own `require_no_tls_keylog()` at the top, *after* the policy's
precheck for that phase has passed. A keylog appearing in between is refused
there, with the send already initiated and no response received. The first cut of
`REASON_PHASES` allowed `tls_keylog_environment_present` only at
`entry_preflight` and `terminal_preflight`, so the policy recorded the refusal at
`redirect_request`/`terminal_request`, the builder refused the reason/phase pair
with `receipt_schema_invalid`, and the attempt was left with an empty root and
**no terminal receipt at all** — a reachable path that could not be published.
The reason now covers all four points at which it can genuinely be raised: two
policy prechecks and two adapter rechecks. The `*_request` treatment is the
truthful one and already the established meaning of those phases — `transport_failed`
has exactly the same shape — so `request_chain` records the send that was
initiated and both dispositions stay `no_response`.

**One incidental correction.** The frozen-pair cleanliness check previously ran
per entry and raised `redirect_location_mismatch` — a redirect reason code for a
self-check on constants, which cannot truthfully carry it. It now runs once, for
all three pairs, in the attempt preflight before any send, under
`attempt_identity_invalid`: the frozen pairs are part of the attempt identity, so
a malformed pair invalidates the attempt rather than one entry.

**Movements.** `schema_version_manifest.json` moves `0.9.0` → `0.10.0`, 37 → 38
entries; `documentation_collection_receipt` stays `0.1.0` and
`documentation_collection_receipt_v2` is added at `0.2.0`. Schema files 40 → 41.
`REPO_MANIFEST.md` 531 → 535. `documentation_transport_client@0.1.0`,
`documentation_receipt.py`, its schema, `http_adapter.py` and
`collection/__init__.py` are all unchanged.

**E-C-D1 makes no live call.** No URL is retrieved, nothing is written under
`data/`, no ADC, no SDK client, no provider operation. Every transport test uses a
stub or a substituted client factory and every filesystem test uses `tmp_path`.
Gate chain: E-C-D → E-M-S attempt one (stopped) → **E-C-D1** → E-M-S retry under
`@0.2.0` → E-M implementation → E-B.

This decision supplements ADR-037 and does not amend it.

**Rejected alternatives:** Modifying `documentation_collection_receipt@0.1.0` in
place was rejected because a live receipt already instantiates it and would stop
being verifiable. Recording the observation only in the returned result object was
rejected as the U0 defect in another form — an artifact that is not persisted is
not evidence. Truncating an over-long `Location` to fit was rejected because a
shortened URL is a fabricated artifact. Collapsing `no_response` into `absent` was
rejected as the same erasure at smaller scale. Adding `get_list` handling to
recover duplicate header-line boundaries was rejected as an adapter change outside
this increment's scope; the joined string is recorded and the limitation stated.
Requiring an `ast.Constant`-only shape for every `reason_code` was rejected on
measurement: `_persist_object` already selects dynamically, and the property worth
enforcing is closed-vocabulary membership, not call syntax. Claiming that no
observed value can exist anywhere in the exception-object graph was rejected once
measurement showed `__context__` retention that the unchanged adapter cannot erase.

## ADR-039 — Documentation routes v0.3.0: re-freezing E1 from a governed observation (E-C-D2)

**Status:** Accepted.

**The measured trigger.** The single authorized v0.2 attempt
`docattempt-c4082dd835f2f5228669487f50ca2308` (receipt SHA-256
`6ebddbd1131f89e74443363eeb672d729856e29327fdcc6be13de3cae15f6962`) stopped
truthfully at E1's redirect evaluation with `redirect_location_mismatch`. Because
ADR-038 had made observations survive a refusal, that receipt records — for the
first time in governed provenance — the `Location` the server actually returned:
`https://docs.cloud.google.com/vertex-ai/generative-ai/docs/thinking`. It is
absolute HTTPS, carries no query, fragment, userinfo or trailing slash, is
printable ASCII, and would pass `_require_clean_url`. It carries the **host** of
the previously frozen final and the **path** of the requested URL, and it is
neither member of any frozen pair.

**A frozen route is not a policy constant.** Measured: the route URLs are
`const`-pinned inside both committed schema files — **10** occurrences in v0.1,
**52** in v0.2 — and each loader deep-compares its committed file against a
constructor that reads the route declaration, which lives inside the frozen
v0.1.0 module. Editing that tuple in place would make **both** committed schemas
stop matching their own loaders, and **both** live receipts would become
unverifiable. A route change therefore cannot be an edit; it must be a successor.

**What this ADR does.** `documentation_routes.py` becomes a v0.3-only route home;
`documentation_collection_receipt@0.3.0` and `documentation_acquisition_policy@0.3.0`
read from it. `@0.1.0` and `@0.2.0`, their schemas, their loaders and both live
receipts are untouched and independently verifiable — the historical declaration
stays exactly where it is, describing the routes those contracts were built
against.

**E1 is a hypothesis under test, not a validated target.** Its new `final_url` is
the observed value above. Freezing it makes the value *testable*; it does not
make it correct. Nothing has been retrieved from it, no content has been
validated against it, and it authorizes exactly **one** separately governed
attempt. It is explicitly **not** an automatically authorized route, and a
successful retrieval from it would still be retrieval status only —
`documentation_evidence_validation@0.1.0` owns whether the bytes carry the
required official claim.

**The superseded E1 final was never validated.**
`https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/thinking`
was requested by no attempt: both stopped at E1's redirect evaluation. It is
recorded here as a superseded, never-validated hypothesis and is **not** carried
forward as a second hop, which would be treating a prior guess as evidence. It
remains permanently readable in the two committed receipts, which is where
superseded route history belongs.

**E2 and E3 are copied byte-identically.** Their finals sit on the same apexes and
may be wrong in the same way, but one observation about E1 is not evidence about
them. Transforming them by host/path pattern would be inference. The cost is
incremental discovery — potentially one authorized attempt per entry — and that
is the correct trade under the no-guess rule.

**Still exactly one hop.** Every v0.3 pair's two URLs differ, so the grammar
continues to require exactly one recognized redirect hop. A second redirect may
be **observed** and recorded at `terminal_observed_location` under
`redirect_chain_too_long`; it is never followed. No multi-hop contract is
designed or implemented, because no receipt has yet established that need.

**Only route identity and contract version change.** Every 0.2.0 rule is
preserved: the 20-field entry, the seven failure phases, the 20-reason phase map,
the location/disposition binding under two unanchored predicates, the
three-constant `request_chain` pin, and every fail-closed builder and loader
guard. This is proven, not asserted: a drift test normalises both schemas by
substituting route strings, contract id, schema id, version const and prose
comment, then requires byte equality — so any divergence in a bound, pattern,
phase, reason, disposition or conditional fails loudly.

**The URL-literal exemption moved rather than relaxed.** The bounded exact-pair
check now runs against `documentation_routes.py`, and the policy is separately
proven to declare no route at all. The one scheme occurrence left in the policy
is the bare `https://` prefix used by the absolute-`Location` check; a guard that
banned it outright would punish the code implementing the defence, so it is named
exactly rather than exempted wholesale.

**Attempt-identity safety.** `ordered_pairs`, `policy_contract_sha256` and
`receipt_schema_sha256` all move, so a v0.3 attempt cannot derive either
published attempt root. Neither live receipt can be overwritten, and a test pins
both non-collisions.

**Movements.** `schema_version_manifest.json` `0.10.0` → `0.11.0`, 38 → 39
entries; `documentation_collection_receipt` stays `0.1.0`, `_v2` stays `0.2.0`,
`_v3` added at `0.3.0`. Schema files 41 → 42. `REPO_MANIFEST.md` 535 → 539.
`documentation_transport_client@0.1.0` is unchanged — no transport change is
implied.

**E-C-D2 makes no live call.** No URL is retrieved, nothing is written under
`data/`, no ADC, no SDK client, no provider operation. Gate chain: E-C-D →
E-M-S attempt one (stopped) → E-C-D1 → E-M-S attempt two (stopped, truthful) →
**E-C-D2** → E-M-S attempt three under `@0.3.0` → E-M implementation → E-B.

This decision supplements ADR-037 and ADR-038 and amends neither.

**Rejected alternatives:** Editing the frozen pair in place was rejected on
measurement — it would invalidate both committed schemas and both live receipts.
Adopting a bounded multi-hop contract now was rejected as premature: no evidence
exists that a second authorized hop is needed, and v0.2/v0.3 already observe a
second redirect without following it, so the cheaper experiment strictly
dominates. Retaining the superseded E1 final as a second hop was rejected because
it was never validated. Re-freezing E2/E3 by the host/path transformation
observed for E1 was rejected as inference from a single observation. Treating the
observed value as authorized because it was observed was rejected outright: an
observation is evidence of what a server returned, not authority to follow it.

## ADR-040 — Route kinds, a direct route, and successor-only policy (E-C-D3)

**Status:** Accepted.

**Provenance is not uniform across these three routes, and the receipt must not
imply that it is.** E1's target is the `Location` that governed receipt
`docattempt-c4082dd835f2f5228669487f50ca2308` actually recorded — a collector
observation. **E2 and E3 carry human-supplied route hypotheses dated
2026-07-30.** They are not collector provenance and not raw-byte evidence:
ADR-037 rejected `WebFetch` output as authoritative on measurement, because it
returns model-summarised markdown with no digest and produced navigation shells
for two of three pages during E-M0. Freezing E2 and E3 makes them **testable, not
true**. E2's target follows the same host swap E1's governed observation
confirmed; that corroborates and does not prove, and nothing in this increment
treats it as proof. The superseded E3 final was requested by no attempt and is
dropped rather than demoted to a second hop.

**Route kinds are declared, never inferred.** v0.1–v0.3 could express only "one
redirect hop", which worked solely because every frozen pair's two URLs differed.
E3 is now `direct`: `requested_url == final_url`. `route_kind` is therefore
declared per entry and `const`-pinned, and both schema and builder enforce the
truthfulness constraint in each direction — `direct` requires the two URLs to be
the same one, `redirect_once` requires them to differ. A mislabelled route cannot
be published.

**A direct route issues exactly one send.** An initial 200 is its only success
path. A 3xx is **recorded** — status, and the adapter-exposed `Location` under
the unchanged transcription policy — and refused with the new reason
`direct_redirect_not_permitted`. It is never followed. The schema pins the three
`send2_*` phases unreachable for a direct entry and its `request_chain` to two
constants, so a second send cannot be described even by a malformed builder.
The attempt maximum falls from six sends to **five** (2 + 2 + 1).

**Observation slots are named by send ordinal.** Calling a direct route's only
send "terminal" while its failure phases stayed named "redirect" would describe a
hop that never happened. `redirect_observed_*`/`terminal_observed_*` become
`send1_observed_*`/`send2_observed_*`, and the seven phases become
`entry_preflight`, `send1_request`, `send1_evaluation`, `send2_preflight`,
`send2_request`, `send2_evaluation`, `persistence`. The reason vocabulary is
kind-scoped: the six hop-describing reasons are absent from a direct route's
enum, and `direct_redirect_not_permitted` is absent from a hop route's.

**Successor-only, now including the policy source.** `documentation_policy.py`
was modified in place across E-C-D, E-C-D1 and E-C-D2. That was the historical
pattern; it is not the pattern from here on. Under the v0.4 standard **every**
governed layer — receipt, schema, routes and policy source — succeeds rather than
mutates, so an archived receipt can be re-verified against the exact sources that
produced it. `documentation_policy_v4.py` publishes `@0.4.0` through the explicit
`collect_documentation_evidence_v4`; the v0.3 policy stays byte-identical and
keeps publishing `@0.3.0`. Both entry points are exported. Every v0.3 semantic
regression test remains unchanged; the sole legacy test file modified is
`test_documentation_policy.py`, and only its shared structural adapter-import
boundary.

**Two bounded weakenings, recorded rather than absorbed.** The adapter's importer
set moves from one policy module to an exact allowlist of **two named** ones, and
the URL-literal exemption gains `documentation_routes_v4.py` and
`documentation_policy_v4.py` — the latter for the bare `https://` scheme prefix
alone, with a test proving it declares no route URL. Both follow the pattern
ADR-037 used when the httpx importer became a two-entry list.
`collection.__all__` grows from four names to **five**: one governed entry point
and nothing else, with `send_once` and the adapter still absent.

**The v0.4 test double selects by call ordinal only.** Every earlier documentation
stub branched on `url == pair["requested_url"]`, which is ambiguous when a route's
two URLs are identical. `documentation_v4_transport.OrdinalTransport` picks its
response positionally; `url` and `iterate_body` are assertions, never selectors,
and a mismatch fails inside the transport seam. That is a property of the helper,
not something production code can enforce — a test double is test code, and the
collector never sees it. The event queue proves the send budget directly: exactly
one send for E3 under success, every refusal and persistence failure, and exactly
five ordered calls for a full success.

**No total wall-clock ceiling exists, and none is derived.** At most five sends;
four deterministic 2-second spacing delays if all sends are reached; four
independent 30-second connect/read/write/pool deadlines per send. Phase deadlines
do not compose into a request bound, and per-send bounds do not compose into a run
bound. `total_wall_clock_deadline` is declared `null` in the policy contract. A
total deadline would be a separately governed successor to
`documentation_transport_client@0.1.0`, which this increment leaves unchanged.

**Movements.** `schema_version_manifest.json` `0.11.0` → `0.12.0`, 39 → 40
entries; receipt v1/v2/v3 unchanged, `_v4` added at `0.4.0`. Schema files 42 → 43.
`REPO_MANIFEST.md` 539 → 548. Entry fields 20 → 21; entry-recordable reasons
20 → 21; public reason codes 27 → 28.

**E-C-D3 makes no live call.** No URL is retrieved, nothing is written under
`data/`, no ADC, no SDK client, no provider operation. Gate chain: E-C-D → E-M-S
one (stopped) → E-C-D1 → E-M-S two (stopped, truthful) → E-C-D2 → **E-C-D3** →
E-M-S three under `@0.4.0` → E-M implementation → E-B.

This decision supplements ADR-037, ADR-038 and ADR-039 and amends none of them.

**Rejected alternatives:** Editing the v0.3 routes, schema or policy in place was
rejected on measurement — the routes are `const`-pinned inside the committed v0.3
schema, so its loader would stop matching. Reusing `redirect_observed_*` /
`terminal_observed_*` for a direct route was rejected as misleading redirect-only
vocabulary. Inferring the route kind from URL inequality was rejected: an inferred
kind is a guess that happens to be right, and a declared one can be checked.
Deriving E2's target from E1's confirmed host swap was rejected as inference from
a single observation — it is frozen as a hypothesis on the same human-supplied
footing as E3, not on E1's. Claiming any finite elapsed-time ceiling was rejected
because no such bound is implemented at any layer.

## ADR-041 — Two-hop route grammar with a relative second hop (E-C-D4)

**Status:** Accepted.

**The measured trigger.** The governed v0.4 attempt
`docattempt-921cb253da290dc5dadadd5afc7244d6` stopped at `send2_evaluation` with
`redirect_chain_too_long`. That is a **positive observation**: E1's send-one hop
was accepted — the frozen intermediate matched byte-exactly — and the intermediate
itself answered with a further redirect. The route is two hops deep, and the
one-hop grammar could not express it. ADR-039's re-freeze of E1 was correct as far
as it went; it was simply one hop short.

**Provenance is not uniform, and the receipt must not imply that it is.**

* **E1's second-hop `Location`** is a governed observation. The v0.4 stopped
  receipt recorded it, under an attempt identity, with a digest. That is raw
  evidence.
* **E2's and E3's chain information is human/agent-supplied design input obtained
  with `curl`.** It is **not governed raw evidence**. No receipt attests it, it
  carries no digest, no manifest and no attempt identity, and it was pasted into a
  design conversation rather than collected. ADR-037 already rejected `WebFetch`
  as authoritative for redirect chains — it summarises rather than reports and
  reveals no hop structure — and curl output enjoys no better standing merely
  because it is more literal. Freezing E2 and E3 makes them **testable, not
  true**.

A test asserts both halves of this: the decision log states it in words, and no
governed artifact under `data/` attests a v0.5 route.

**Scope: route grammar only.** v0.5 collects no content evidence. A successful
retrieval under it is still retrieval status alone; whether the bytes carry the
required official claim remains `documentation_evidence_validation@0.1.0`'s
question.

**The second hop is an absolute-path reference, resolved against a fixed base.**
`redirect_twice_relative_path` performs three sends. Send one and send two accept
only 301/308. Send one's `Location` must be byte-exact against the frozen
intermediate. Send two's `Location` must satisfy a deliberately narrow grammar —
one leading `/`, and no `//`, scheme, colon, host, userinfo, query, fragment,
backslash or `..` segment — and be byte-exact against the frozen raw path. It is
then joined by plain concatenation to `https://docs.cloud.google.com`, a **module
constant**, and the result must reproduce the frozen final URL byte-exactly.
Nothing is parsed out of the observed value and reused as a base: a base taken
from a response would let the server choose where the join lands. Send three must
answer 200.

**No `direct` kind.** v0.4's direct semantics are not carried forward. Every v0.5
route performs at least one recognized hop, so no entry can describe a bare fetch.
E3 returns to `redirect_once`.

**Successor-only, at every layer.** `@0.1.0`–`@0.4.0`, their schemas, their route
modules and the v0.3/v0.4 policy sources are byte-identical. `@0.5.0` adds its
own routes, receipt, schema and policy, and `collect_documentation_evidence_v5`
joins the two existing entry points rather than replacing them. The v0.4 entry is
**extended** with send-three fields, not mutated: 21 fields become 27, and no v0.4
field is renamed or removed.

**Vocabulary movement.** Five reasons are added, all describing the second hop —
`second_redirect_status_invalid`, `second_location_missing`,
`second_location_not_relative_path`, `second_location_mismatch`,
`resolved_final_mismatch` — and `direct_redirect_not_permitted` is removed with
the kind it described. Public codes 28 → 32; entry-recordable 21 → 25. The five
new reasons are absent from a `redirect_once` route's enum, and phases are
kind-scoped: 10 for the two-hop kind, 7 for the one-hop kind.

**One bounded weakening, recorded rather than absorbed.** The adapter's importer
allowlist grows from two named policies to three. The **httpx** importer allowlist
is unchanged at two modules, and a test asserts `documentation_policy_v5` imports
no `httpx`. `collection.__all__` grows from five names to **six**: one governed
entry point and nothing else.

**Send budget.** At most **eight** sends — 3 + 3 + 2 — and **seven** deterministic
2-second spacing delays on the success path. Each send configures four independent
30-second connect/read/write/pool deadlines. **No request-total or run-total
wall-clock deadline exists at any layer, and none is derived**; phase deadlines do
not compose into a request bound, and per-send bounds do not compose into a run
bound. `total_wall_clock_deadline` is declared `null`. No retry.

**Movements.** `schema_version_manifest.json` `0.12.0` → `0.13.0`, 40 → 41
entries; receipt v1–v4 unchanged, `_v5` added at `0.5.0`. Schema files 43 → 44.
`REPO_MANIFEST.md` 548 → 557. Collection source modules 20 → 23.

**E-C-D4 makes no live call.** No URL is retrieved, nothing is written under
`data/`, no ADC, no SDK client, no provider operation, and no E-M-S retry. Gate
chain: E-C-D → E-M-S one → E-C-D1 → E-M-S two → E-C-D2 → E-M-S three (stopped at
`redirect_chain_too_long`) → **E-C-D4** → E-M-S four under `@0.5.0` → E-M
implementation → E-B.

This decision supplements ADR-037 through ADR-040 and amends none of them.

**Rejected alternatives:** Editing the v0.4 routes, schema or policy in place was
rejected on measurement — the routes are `const`-pinned inside the committed v0.4
schema, so its loader would stop matching and its live receipt would become
unverifiable. Resolving the second hop with a general URL joiner was rejected: a
permissive resolver is exactly how `//host/x` becomes an authority and how a
first segment becomes a scheme, so the grammar is narrow and the base is a
constant. Carrying v0.4's `direct` kind forward was rejected because no v0.5 route
is a bare fetch. Treating the curl-derived chain as evidence was rejected
outright: it is an input to a design decision, and only a governed attempt can
turn it into provenance.


## ADR-042 — Offline documentation evidence validation (`documentation_evidence_validation@0.1.0`)

**Status:** Accepted.

**The question this answers.** ADR-037 declared that a collection receipt owns
*retrieval status only*, and every receipt ADR since has repeated that whether the
bytes carry the required official claim belongs to a separate contract. This is
that contract. The v0.5 attempt `docattempt-ef3032c82e618c8ace8e33b26326d5c6`
completed and persisted three documents; this increment decides, offline, whether
named byte ranges of those documents contain named literal text.

**Five mechanical facts, and nothing else.** Validation proves: the receipt is the
pinned one (digest, attempt id, contract id, schema digest, `completed`); the raw
object is the pinned one (digest **and** byte count, and the receipt's own entry
agrees); the byte range lies inside the object and hashes to its pin; the range
decodes under **strict** UTF-8; and each required literal occurs in the decoded
range while each forbidden literal does not, by exact substring containment.

**What is refused, deliberately.** No HTML parser, renderer, entity decoder,
whitespace normalizer, model or network. Each is a way of turning *"the bytes say
X"* into *"something like X was probably meant"*, and each would let a claim
survive an edit to the evidence beneath it. Tests pin this: `&#39;` never matches
`'`, `&lt;td&gt;` never matches `<td>`, a doubled space never matches a single
one, and case never folds. A structural test forbids the module from importing any
parser or transport, and an AST test forbids normalizing calls inside the
verification path specifically — a whole-file ban was rejected because it flagged
a blank-string check in the schema loader that never touches evidence.

**The selection is a human act and is labelled as one.** Which byte range answers a
question is a judgement the code never makes and never re-derives.
`selection_provenance` is `human_selected_byte_slice_v1`, and each finding's
`claim` is carried with `claim_attribution: human_reading_of_the_verified_range`.
The code proves the range is what it says it is and that the literals are in it;
the reading remains attributed to a person.

**Qualifiers are bound so they cannot be dropped.** Two are load-bearing.
`CountTokens` is free of monetary charge *and* the same passage states a maximum
quota of 3000 requests per minute — so `maximum quota for the` and `3000 requests
per minute` are required literals, and the recorded claim states explicitly that
this evidence **does not support a claim that no quota applies**. Likewise
`thinking_budget = 0` suppresses returned thought content *while reasoning-style
text may still appear in the output*, and that qualifier is a required literal too.

**One measurement corrected a drafting assumption.** The `thinking_level` claim was
first drafted as an *absence* — that the parameter is simply not used for earlier
models. The bytes are stronger and more precise: *"If you use the `thinking_level`
parameter with a model earlier than Gemini 3, the model returns an error."* It is
therefore a **required** literal, not a forbidden one.

**Values are bound to their own table rows.** A bare "`$0.30` appears somewhere in
the slice" check would not tie a price to a row. The required literals are
multi-line spans — `<td>Gemini 2.5 Flash</td>\n<td>1</td>\n<td>24,576</td>` and the
two price rows including both prompt-length tier cells — so the 1..24,576 range
belongs to Gemini 2.5 Flash specifically and each price belongs to its own line
item in both tiers.

**Pricing is exact integer arithmetic, never float.** Canonical unit is
**microdollar per token**: 1 USD = 1,000,000 microdollar, so $0.30/1M = 300,000/1,000,000
= **3/10** and $2.50/1M = 2,500,000/1,000,000 = **5/2**. Cost is
`ceil(input_tokens * 3 / 10) + ceil(output_tokens * 5 / 2)`, each side rounded up
independently because that is what the declared rule says; summing first and
rounding once would be a different rule. A test pins the round trip: one million of
each costs 2,800,000 microdollar = $2.80 = $0.30 + $2.50, and no declared pricing
value is a float.

**Write-once, like every other governed artifact.** The registry record is
published under `data/registry/` — which is *not* gitignored, unlike `data/raw/**`
— and republication over an existing file is refused with `destination_exists`,
leaving the existing bytes untouched.

**Tests never read gitignored evidence.** Every case is synthetic and writes only
under `tmp_path`; a suite that needed `data/raw/**` would pass on the machine that
ran the collection and fail everywhere else. The one committed artifact that *is*
tracked, the registry record, is validated against the committed schema without
touching a raw object, and the frozen selections are checked for internal
consistency (bounds inside byte count, 64-hex digests, non-empty literals) the same
way.

**Movements.** `schema_version_manifest.json` `0.13.0` → `0.14.0`, 41 → 42 entries.
Schema files 44 → 45. `REPO_MANIFEST.md` 557 → 561. Collection source modules 23 →
24. `collection.__all__` 6 → 7, adding only the pure selection verifier — no raw
send, no adapter, no seam.

**No live call.** This increment constructs no HTTP client, retrieves no URL, and
makes no ADC, credential, SDK or provider call. It reads the three persisted raw
objects and the v0.5 receipt, and writes one registry record.

This decision supplements ADR-037 through ADR-041 and amends none of them.

**Rejected alternatives:** Parsing the HTML to locate claims was rejected — a
parser makes the validation depend on a parse tree that the source can change
without changing the claim, and vice versa. Normalizing whitespace or decoding
entities before comparison was rejected for the same reason, and is tested against
directly. Deriving the claim text from the bytes was rejected: selection and
reading are human acts, and pretending otherwise would launder a judgement into an
apparent measurement. Storing prices as floats or as dollars was rejected in favour
of exact integer ratios in microdollars, so that no rounding is implicit and the
cost rule is auditable.


## ADR-043 — E-M two-operation model execution: successor contracts, runner-owned capture, and the execution outcome

**Status:** Accepted.

**The question this answers.** E-L bought one authorized call and E-R fixed what
that call sends. Neither could say what the call would cost before making it. A
`countTokens` measurement can, but adding a second operation turns almost every
single-operation assumption into a wrong one, and the released contracts cannot
absorb the difference. This increment adds the second operation and states, once,
what changes.

**Released contracts are succeeded, never mutated.** Measured, not assumed:
`extraction_run@0.1.0` is closed and rejected all six measurement fields tried
against it; `extraction_provider_client_contract@0.1.0` has a closed
`model_parameters`, so `thinking_budget` produced a validation error there;
`extraction_provider_error_record@0.1.0` is closed, has no operation label,
attempt ordinal or raw reference, and its `reason_code` enum rejects
`write_error` and `destination_exists`. So `@0.2.0` successors sit beside the
first two, `extraction_execution_outcome@0.1.0` is new, and all five released
schemas stay byte-identical. `PROVIDER_PROTOCOL_VERSION` keeps saying `v7` and
`v8` is declared alongside it: rewriting the shared constant would have changed
the digest of every released contract instance and broken every governance record
that pins one.

**The phase order is the increment.** countTokens, then persist and hash-verify,
then parse, then reconcile, then admit, then generateContent. Nothing derived
from a response reaches the budget or the next request before that response's
bytes are durable. The honest limit is stated in the code: the SDK parses the
body and classifies its own errors *before* our persistence, so the guarantee
covers our derivations and our subsequent sends, not everything that touches the
bytes.

**Why the runner owns the sink.** An earlier shape had the connector finish every
retry under `tenacity` and hand back a bundle of captures. That makes "a
persistence failure permits no further send" unenforceable — by the time the
failure is visible the later sends have happened. The sink is now called after
each attempt and before the next, and a test asserts the send counter stops where
the failure did. Measured: an `ExtractionError` raised inside the retry wrapper
came out as `ProviderError('provider_response_unusable')`, which is a **valid**
member of the released provider-error enum, so a filesystem failure would have
been published as a provider failure with nothing to flag it. `CaptureSinkError`
now passes through unchanged and carries both reasons, because both can be true
at once.

**Capture is operation-labelled and single-use.** One slot was adequate while one
run meant one send. Two operations and up to three attempts need keys, and a
filled key is refused rather than overwritten, so a retryable body cannot be
silently replaced by the one after it. The label is a fixed code-path constant,
never a caller argument and never inferred from a URL.

**Endpoints are exact, and a 101 is refused.** Measured: the released matcher
admits, under a single `/v1/projects` prefix entry, another publisher's
`:predict` and another location's `:export`; and it strips a query before
comparing, so `?alt=sse` passes a query-free entry. The successor grammar
compares for equality against the *one* endpoint the active operation declares —
allowlist membership cannot catch a crossed operation, since both operations are
on the allowlist. Separately, `httpcore` breaks its receive loop on an
informational response with status 101, so a protocol switch reaches the capture
boundary; the released guard refused only 3xx, and it is now refused before
`response.content` is touched.

**Budget arithmetic, derived rather than declared.** `budget_max_requests` counted
retries of one call; a two-operation run makes requests that are not retries, so
`budget_max_external_requests` replaces it and the effective cap is
`min(3, budget_max_external_requests - 1)`. No independent
`budget_max_generate_attempts` field exists — a second source of truth could drift
from the formula. The wall-clock floor is tiered by that cap (600 / 901 / 1203s)
rather than flat: a flat 600 would have let a three-request budget claim a
one-request ceiling. All three numbers are computed from the timeout pins and
compared against the schema's tiers, so neither can bit-rot alone. Pricing stays
exact integer microdollar (3/10 and 5/2, each side rounded up independently), and
the reserve is the cap times the per-attempt ceiling because a retry re-sends the
same input.

**One canonical projection order.** `generation_config_projection` is six names in
one fixed order, enforced with `prefixItems` and `items: false`. An `items.enum`
plus `uniqueItems` construction admits every permutation, and a permuted list
serializes to different canonical bytes — `sort_keys` orders mapping keys, never
list elements — so two semantically identical contracts would have acquired
divergent provenance digests and an authorization pinning one would have stopped
matching the other. A test shows both halves: the permutation is refused, and the
digests it would have produced differ.

**What the wire actually carries.** Traced to the terminal `json.dumps`:
`thinkingConfig` serializes as `{"thinking_budget": 0}` — snake_case, not
`thinkingBudget`, because the converter passes the object through and
`convert_to_dict` applies no aliases. `thinking_level`, `include_thoughts`,
`systemInstruction` and `tools` appear in neither operation's body, and their
absence is structural: `ProviderRequest` has no such field and the config is
assembled from closed constants.

**The outcome owns what nothing else can.** Measurement status, budget
termination, reconciliation and persistence reasons, costs, per-attempt records,
operation counters and the evidence binding live in
`extraction_execution_outcome@0.1.0`, bound to the prediction manifest as one of
two new roles. It pins only what precedes it — never the envelopes or the
manifest, which are written after — and on routes that publish no manifest it is
itself the classifier root. Variable-count attempt bodies are deliberately not
roles: a role is a 1:1 pin, and they are reachable through the outcome instead.

**The classifier is diagnostic and grants nothing.** `authoritative_completed` is
the only harness-admissible label, and even it states internal consistency rather
than permission. A contract id or version mismatch is `corrupt`, not
`incomplete`: the pin is present and the file is present, so nothing is missing —
and such a document can hash-match its own pin, which is why the schema gate runs
before any digest comparison.

**Deviation from the plan, recorded.** The plan predicted the
`extraction -> providers` import edge would widen from three names to four. It is
six: `CaptureSinkError`, `BudgetAdmission` and `CaptureRecord`. Keeping the
`isinstance` check on an authorization-bearing admission was judged worth more
than matching a predicted count.

**No live call.** This increment constructs no client, resolves no ADC, reads no
credential, and calls neither `countTokens` nor `generateContent`. Every test runs
offline over `httpx.MockTransport` or an injected fake, and `data/` is unchanged.

**Movements.** `schema_version_manifest.json` `0.14.0` → `0.15.0`, 42 → 45
entries. Schema files 45 → 48. `REPO_MANIFEST.md` 561 → 575. Provider modules
8 → 11; extraction modules 14 → 16. Prediction-manifest roles 8 → 10 (v2 tuple;
the v1 tuple is unchanged). `google.*` importers stay at one and `httpx`
importers at two.

This decision supplements ADR-033 through ADR-036 and amends none of them.

**Rejected alternatives:** Widening `extraction_run@0.1.0` was rejected — it is
released and closed, and measured to reject every field this needed. Adding
`thinking_budget` to `model_parameters` was rejected for the same reason. A
connector-owned retry loop returning captures afterwards was rejected because it
makes the persistence rule unenforceable. Duck-typing the admission check to keep
the import edge at four names was rejected: the count is a prediction, the check
is a guarantee. Treating a contract mismatch as `incomplete` was rejected because
nothing is missing in that case. A flat wall-clock floor was rejected because it
under-constrains every budget above the smallest.


## ADR-044 — Prompt qualification bound to the two-operation route: a fourth artifact, two roots, and a pre-evaluation basis (G2)

**Status:** Accepted.

**The question this answers.** `adapter_enablement_record@0.1.0` has always
*required* `prompt_qualification_reference` and `prompt_qualification_sha256` —
SPEC-027 places the SPEC-024 reference on enablement rather than on the
authorization — but nothing ever opened the artifact those fields name. Measured:
the governance walk's only prompt-related line is
`_require_pin_pair(enablement, "prompt_qualification")`, which checks a non-blank
string and sixty-four hex characters and nothing else. Every fixture in the
repository satisfied it with `"3" * 64` naming a file that does not exist, and all
of them passed. So a live call could execute a frozen prompt under an enablement
pinning nothing, and editing that prompt could not break any run — the prompt's
digest chain and the governance chain were two disconnected hash trees.

**The binding is transitive, and stays that way.** `prompt_qualification_record`
→ enablement → authorization. No prompt property is added to
`live_call_authorization@0.2.0`: both authorization property sets are closed, and
a released test already forbids the addition. That test now asserts the same of
the v2 set, so a later "helpful" addition fails loudly rather than creating a
second, unwalked path to the same reference.

**No released contract is modified.** The binding surface already existed on the
enablement schema, so no successor enablement record is needed, and
`validate_governance_chain` stays byte-identical. The new gate is a separate
module and runs on the v2 route only.

**Two roots, one containment.** The record is JSON and hydrates from
`governance_artifact_root`. The two documents it cites — the SPEC-024
qualification policy and the tracked change request — are Markdown and live in
the repository tree, so they are read against the already-injected `repo_root`.
Measured: `hydrate_pinned_artifact` calls `json.loads`, so it cannot read them at
all. The answer is not a second loader. `_hydrate` was split so that
`hydrate_pinned_bytes` and `hydrate_pinned_artifact` share one `_safe_target` and
one digest comparison; the relative-reference rules cannot drift between the two
roots. A repository-relative reference is never resolved inside the governance
root, and the reference patterns make that unrepresentable rather than merely
discouraged.

**The governing spec is SPEC-024, as a const rather than a pattern.** The policy
governing a prompt qualification record is the qualification registry, whatever
stage the prompt serves. An earlier draft named SPEC-008 here, which mislabelled
stage context as qualification policy. SPEC-008 is cited by the change request.

**Only the bootstrap basis executes.** `evaluated_comparison` records cite
evaluation runs that resolve against a third root which nothing injects or
hash-verifies. Accepting one would let unverified references authorize a live
call, so that basis is refused *before* the property set is selected — the two
bases have different shapes, and checking shape first would report the wrong
cause and make the evaluated branch look unimplemented rather than deliberately
unreachable. G2 therefore declares exactly one runtime property set, the
twenty-eight-field bootstrap shape.

**A pre-evaluation record may not carry a review decision at all.**
`evals/CHANGE_CONTROL_PROTOCOL.md` states that a review decision presupposes a
completed valid evaluation, and the repository has none: no evaluation case, no
`evaluation_run_manifest` artifact. An empty or neutral decision would still be a
decision, so the property is absent, not blank. `declared_non_claims` is
bootstrap-only for the mirror-image reason: its fixed content says "not a release
qualification", which contradicts the release-capable branch. It is fixed with
`prefixItems` plus `items: false`, because an `enum` with `uniqueItems` would have
admitted any permutation, and a permuted tuple is a different statement.

**Placement.** The gate sits in `_run_two_operation_stage`, immediately after
`validate_qualification_execution_contract` and `load_prompt` — the first point
where both operands exist — and before the meter, the run root, `mkdir`, SDK
construction, and any send. A refusal there produces zero artifacts, and it is
raised inside the caller's `try`/`finally`, so the run permit is revoked on this
route exactly as on every other terminal one. Hydration happens earlier, in F0,
before the handshake, so a hydration refusal has no permit to release.

**Prose lives in the change request.** The record carries no free-text property;
`known_limitation_codes` is a closed vocabulary and the reviewer's reasoning is in
`CR-0001`, pinned by reference and digest. A governance chain must not become a
channel for prose any more than for secret material.

**Known limitation, stated rather than fixed here.** `run_extraction_stage` is a
public, provider-capable v1 entry point with no non-test caller, and it does not
carry this binding. It is therefore a bypass. Retiring its provider route touches
173 tests across five modules and roughly 368 lines of production code, so it is a
separate increment (G2b) rather than a silent widening of this one. **The live
smoke run is blocked until G2b is implemented, reviewed, committed, and pushed.**
That block is a decision recorded here, not a runbook note: a runbook is a human
document and the bypass is a code path.

**Rejected alternatives.** Adding the prompt fields to
`live_call_authorization@0.2.0` was rejected: the property sets are closed and
SPEC-027 places the reference on enablement. Tightening `validate_governance_chain`
was rejected because the v1 route still calls it and a released validator must
keep validating exactly what it was released as. Folding the rules into
`manifests.py` was rejected for the same reason. A free-text `known_limitations`
field was rejected as an unbounded channel into an authorization chain. Accepting
an `evaluated_comparison` record on the strength of being schema-valid was
rejected: schema validity is not verification. Allowing an empty
`supporting_evaluation_references` array under an evaluated basis was rejected —
it would have let a record claim an evaluation basis with no evaluation.


## ADR-045 — The v1 provider route is closed, not deleted: a retirement refusal, a private measurement helper, and 178 migrated cases (G2b)

**Status:** Accepted.

**The question this answers.** ADR-044 bound the SPEC-024 prompt qualification to
the two-operation route and recorded, as a known limitation, that
`run_extraction_stage` remained a public, provider-capable entry point without
that binding. It walked the three released governance rings and then sent, which
is what made it dangerous: it looked legitimate. A route that validates a chain
and still cannot say which prompt was qualified is a bypass, and a runbook cannot
close it because a runbook is a human document and this is a code path.

**Scope A: refuse, do not delete.** The refusal is three lines. Roughly 537 lines
of v1 production code become unreachable and are deliberately left in place;
physical removal is a separate cleanup increment. Deleting code and retiring a
route are different decisions and are not bundled.

**Placement, and the four consequences it fixes.** The refusal sits after the
non-run branch returns and before `require_provider`, the governance walk, the
permit handshake, the meter, `_require_absent_run_root` and `mkdir`. Therefore:
the caller-supplied contract-pin refusal and all nineteen packet-build refusals
keep their codes and their zero artifacts; the non-run route keeps its contract —
two artifacts, `inputs/extraction_input_packet.json` and
`manifests/extraction_non_run_record.json`, `zero_admissible_passages`, no
provider call; the retired route creates nothing and calls nothing; and **an
existing run root now reports `v1_live_route_retired` rather than
`run_root_exists`**, because `_require_absent_run_root` sits far below the
provider seam on that path. That last one is a deliberate behaviour change. The
refusal writes nothing and removes nothing, so the caller's directory is left
exactly as found, and a test asserts the pre- and post-run digests are equal.

**`run_two_operation_measurement` is private.** It hydrated nothing, validated no
chain, bound no prompt qualification and asked for no permit; its `authorization`
argument is a caller-supplied mapping read only for the attempt cap. An exported
function that sends while validating nothing is a second public route around the
ADR-044 gate. It is now `_run_two_operation_measurement` and out of `__all__`.
**The underscore is a boundary, not an enforcement:** an in-process caller can
still reach it by name, and `test_em_route_matrix.py` deliberately does. What
actually refuses a send without a permit is the connector, whose `count_tokens`
and `complete_v8` spend an operation-labelled permit that only
`assert_run_permitted` grants.

**Test disposition, measured rather than estimated.** A prior report said "173
tests"; that counted `def test_` and missed parametrisation. Measured through a
`pytest_runtest_makereport` hook: **318 cases across the five v1 modules, 191
broken, 127 untouched.** The 127 survive because several v1 refusals fire above
the retirement. Of the 191: **178 migrated**, **10 retired with reason**, **3
converted into retirement-refusal tests**. Nothing was dropped silently.

The 10 retirements are the v1 single-operation publication shape —
`predictions/raw_prediction.json` under the v1 reference, the eight-role v1
prediction manifest, the nine-artifact count. Their v2 counterparts already
exist. The 3 conversions are `provider_required`, `provider_protocol_invalid` and
`budget_meter_unavailable` on the v1 seam, which now collapse into one outcome:
the route is closed, so what was injected no longer matters.

**Four v1 invariants could not migrate unchanged, and are asserted in their v2
form rather than pretended to be unchanged.** Budget refusals no longer leave
zero artifacts, because v2 must send `countTokens` before the budget can decide
on a measured number; what survives is that nothing is generated, and the refusal
is published as a `pre_generation_invalid` chain instead of vanishing. Post-F1
failures republish as the classified terminal reason, so a meter refusal surfaces
as `budget_termination` rather than its own code. The meter is shown a measured
count, a reserve and the `provider_request_digest` rather than the request
object; the digest form is stronger and is checked against the persisted
artifacts. And `contract_pin_forbidden` has no v2 counterpart because the
`provider_client_contract` parameter does not exist on `run_extraction_stage_v2`
at all — the absence of the channel is asserted instead of a refusal.

**A coverage gap this migration surfaced, recorded rather than closed.** v1 ran
`validate_provider_client_contract` on the declared client contract, whose first
act is the credential scan. v2 cannot: that validator enforces the v1 property
set exactly and a `@0.2.0` contract legitimately carries fourteen more fields. So
**the v2 route performs no credential scan on the client-contract seam.** A
tampered contract is still refused, but by the digest guard; a contract that
carried credential material from the start and was pinned that way would not be.
A test locks the measured behaviour so that closing the gap must revisit this
record. Closing it is a production change beyond this increment's locked scope
and is left as an open decision.

**Rejected alternatives.** Deleting the v1 code in the same increment was
rejected: retirement and removal are separate decisions with different review
surfaces. Retiring the v7 connector was rejected on measurement —
`vertex_gemini_v2.py` imports four names from `vertex_gemini.py`, so the module
cannot be deleted. Folding the 178 migrated cases into `test_em_route_matrix.py`
was rejected: one module of roughly 400 cases would have made the route matrix
unreadable. Asserting the v1 zero-artifact budget invariant on v2 was rejected as
false. Silently dropping the 13 non-migrating cases was rejected outright.


## ADR-046 — Two different dates: the source-admission cutoff and the analytical period assignment (G3-1)

**Status:** Accepted.

**The question this answers.** `docs/TEMPORAL_POLICY.md` required the pilot to
compare two observation conventions before freezing one, and the open decision
carried the shorthand "filing-date versus fiscal-year". The shorthand hid the
real structure. Both documents define the second option as *"the source packet is
bounded by the filing date but assigned to the fiscal year"* — so the two
conventions **agree** on the source boundary and differ only on the label
attached to the observation. Treating them as competing cutoffs was a category
error, and this record separates the two ideas by name before fixing a value.

**Source-admission / evidence-availability cutoff.** This is what
`observation_cutoff_date` means in the packet and authorization schemas: the
right-hand side of `publication_date <= observation_cutoff_date`. For the HubSpot
FY2024 smoke it is the filing/publication date **2025-02-12**, copied from the
already hash-bound admission and ingestion artifacts rather than restated.
Measured: the SEC candidate registry, the normalized documents, the discovery and
preflight manifests, and the admission artifact all carry `2025-02-12`, with
`period_of_report` and `fiscal_year_end_date` held separately at `2024-12-31`.

**Analytical period assignment.** The observation belongs to **FY2024**. It is
carried today by `period_of_report`, `fiscal_year_end_date` and
`observation_year` in the admission/ingestion artifact. It is not a competing
cutoff and is not expressed through `observation_cutoff_date`.

**The rejected counterfactual.** Using `2024-12-31` as a *source-admission*
cutoff is rejected: measured on the real corpus, all 124 passages drop as
`temporally_invalid` and the run takes the non-run route. An annual report is
filed after the period it reports on, so a period-end admission cutoff would make
every annual filing invalid evidence for its own observation. **This says nothing
about fiscal-year panel assignment**, which is a different thing and is not
rejected.

**No new enforcement.** Three fail-closed routes already refuse a period-end
cutoff, all before the provider, the meter and `mkdir`: `hydrate_company_identity`
refuses with `company_identity_mismatch` and zero artifacts, because the
admission artifact declares `2025-02-12` and the equality is enforced; failing
that, the packet filter drops every passage and the run publishes the two-artifact
non-run record with `zero_admissible_passages` and no provider call; failing that,
`validate_authorization_scope` refuses with `authorization_scope_mismatch`. This
increment declares which value is correct; it does not build a gate.

**Known limitation — the analytical label stops at the admission artifact.**
Measured: no schema carries an `observation_year` field. `extraction_input_packet@0.2.0`
and `live_call_authorization@0.2.0` each carry exactly one date field,
`observation_cutoff_date`, and nothing downstream reads `observation_year`. So
**no extraction packet, authorization, prediction artifact or downstream panel
currently carries a reproducible FY2024 analytical key.** A successor increment
must add a hash-bound carrier before any extraction output is joined to a
fiscal-year panel. Until then a fiscal-year join would be an unpinned assertion,
and this record does not license one.

**Token and cost measurement is unrelated to corpus cardinality.** The smoke's
admitted corpus has 124 passages. That is a cardinality, not a token or monetary
measurement. The only authoritative input-token measurement is the verified
`countTokens` result over the canonical rendered contents; cost admission is that
result plus the declared output ceiling. Measured:
`reserve_cost_microdollars` takes `measured_input_tokens`, `max_output_tokens`
and `generate_attempt_cap` only — no passage count, no byte count.

**Runbook invariant, recorded here because no runbook exists.** When a canonical
G3/G4 runbook is written it must read the cutoff from the admission artifact,
pass that exact value as the run argument, and confirm the two are equal. No
runbook file exists in this repository today, and this increment deliberately
does not create one.

**Rejected alternatives.** Describing fiscal-year observation as a `2024-12-31`
source-admission cutoff was rejected as a mislabelling of both governing
documents. Adding a validator was rejected: three routes already refuse, and a
fourth would be redundant enforcement of a decision that is really about which
value is correct. Changing a schema, a contract version, or any artifact was
rejected: every artifact already carries `2025-02-12`, and nothing needs
rewriting. Claiming the panel key already exists was rejected as false.


## ADR-047 — A canonical budget session, a code-owned meter identity, and a closed injection seam (G3-2)

**Status:** Accepted.

**The question this answers.** G3-0 measured that `src/` declared a
`BudgetSession` protocol and shipped no implementation of it. Every run therefore
metered through whatever object a caller injected, and the authorization's
`budget_policy_version` had no producer anywhere in the code — it was a required
field that bound nothing. This increment supplies the producer and closes the
seam.

**The identity is owned by code, and that is the whole point.** An earlier draft
had the factory read `budget_meter_identity` and `budget_meter_version` out of
the authorization. That would have made `validate_budget_meter_identity` compare
the artifact with itself: a session echoing untrusted values back at the check
that is supposed to test them. `build_budget_session` does not accept the
authorization mapping at all — only the digest that identifies it, the run
identity, and the cap `resolve_attempt_cap_v2` derived — so the tautology is
unrepresentable rather than merely avoided.

**The policy version is not a third identity field.** `meter_identity` reports
exactly two, and the validator reads them through a `removeprefix("budget_")`
loop. Adding `budget_policy_version` to that loop would have made it look for a
`policy_version` key no session reports, failing **every** route including the
canonical one. It travels as its own required parameter instead, with no default
so that forgetting it is a `TypeError` rather than a skipped check, and it has
its own reason code: `budget_policy_version_mismatch`. Reusing
`budget_meter_identity_mismatch` was rejected — the current contracts do not
force it, because these refusals happen before F1 and never reach the terminal
classifier.

**Where the check sits.** F0, after the cap is resolved and the session is built,
and **before** `_assert_run_permitted_with`. A refusal there leaves no permit to
revoke, no run root, no artifact and no provider call. The old post-handshake
block — `if session is None` plus a second `validate_budget_meter_identity` — is
deleted rather than kept alongside it: two code paths for one rule is how they
drift. A test asserts by AST that the validator is called exactly twice, always
with three arguments, in `_run_authorized_stage` and `run_extraction_stage_v2`
and **never** in `_run_two_operation_stage` — which is what proves the move was a
move and not a copy.

**`session_nonce` is a property, and that is load-bearing.** `BudgetAdmission`
carries it as a plain field and the runner compares the two by attribute access.
Measured on 3.12: a `runtime_checkable` `isinstance` is a plain `hasattr` sweep
and cannot tell a value from a method, so a session defining
`def session_nonce(self)` would pass the protocol check and then compare a digest
against a bound method — never equal, refusing every admission for a reason
nobody could read off the code. `require_budget_session` closes that with a
64-hex shape check.

**The nonce is derived, not sampled.** Six inputs that are already fixed: the
authorization digest, the run identity, the cap, and the three code-owned
constants. No clock, no VCS, no network, no environment, no credential — the same
reason `code_commit` and `run_created_at` are injected. **Collision is bounded,
not impossible:** two sessions share a nonce exactly when the authorization
digest and the `extraction_run_id` are both equal, which is to say when they are
two sessions for one run. A caller reusing one run identity gets one nonce twice;
that caller is already violating run-identity uniqueness and the reused run root
is refused elsewhere. No global uniqueness is claimed. Before this increment the
field was never compared anywhere and was decorative; the runner now refuses an
admission whose nonce is not the session's own.

**One enforcement owner.** The runner already refuses on
`budget_max_input_tokens` and `budget_max_estimated_cost_micros` before it calls
`admit`, so neither ceiling is passed into the session and the session re-checks
neither. What the session actually is, stated plainly: a code-owned identity, a
cap bound at construction, a derived nonce, and an `admit` that may be spent
once. It is not a budget engine, and this record does not present it as one.

**The public seam is closed.** `run_extraction_stage_v2` no longer accepts
`budget_session`; it builds its own. The private
`_run_two_operation_measurement` still takes one, because the route-matrix tests
drive F2–F5 through it, and it gets **no exemption**: the same shape gate and the
same nonce comparison run at its entry. `budget_meter_protocol_invalid` can
therefore reach the terminal classifier post-F1 — the canonical route calls that
helper after `mkdir` — so it is added to the classifier's budget branch and maps
onto `pre_generation_invalid`/`budget_termination` rather than falling through to
the provider branch and publishing a provider reason for something the provider
never did. The underscore remains a boundary, not an enforcement, exactly as
ADR-045 recorded.

**The v1 legacy call is left compatible, not changed.** `_run_authorized_stage`
is unreachable after ADR-045, and its `validate_budget_meter_identity` call is
given the constant so that removing the unreachable block later surfaces as a
deletion rather than as a `TypeError` from a call nobody can execute.

**Measured test disposition.** Five retired v1 modules carry meter identities in
their fixtures and were left byte-identical: none of them calls
`run_extraction_stage_v2` or the private helper, so their values cannot reach the
canonical comparison. The tests that observed or misbehaved an injected session
moved to the private helper, where they assert the raised reason code — never a
route family, because that helper publishes nothing.

**Rejected alternatives.** A narrower test-only injection seam was rejected:
"production callers cannot use it" is not structurally enforceable in Python, so
it would have been a second weak path instead of a closed one. A `_PIN` constant
beside the policy version was rejected — the pin pattern exists for the
`extraction ↛ providers` boundary, and there is no such boundary here. Sampling
the nonce with `uuid4` or `secrets` was rejected as ambient nondeterminism.
Passing the two ceilings into the session was rejected: two copies of a ceiling
can disagree.


## ADR-048 — A produced routing contract and two bound policy versions: closing three unbound provenance fields (G3-3)

**Status:** Accepted.

**The question this answers.** G3-0 listed three fields the repository *declared*
and never *bound*. Measured again at the start of G3-3, across the whole tree:

- `routing_contract_id` and `routing_contract_sha256` are required properties of
  the released `adapter_enablement_record@0.1.0` and
  `prompt_qualification_record@0.1.0`, and SPEC-027 §37/§52 and SPEC-024 §81 both
  ask for a "routing contract identity/hash". **Nothing produced one.** The only
  check in the repository compared the prompt qualification's two routing fields
  with the enablement's two routing fields — both caller-supplied — so a digest
  of `"4" * 64` satisfied the entire suite, and did.
- `retry_policy_version` and `rate_limit_policy_version` are required properties
  of the authorization at both `@0.1.0` and `@0.2.0`, and are declared again by
  the client contract. **They were never compared to anything**, in either
  direction, anywhere.

**Decision.** A canonical routing-contract producer in `extraction`, a narrow v2
identity gate, and a policy-version validator bound to two code-owned pins.

**Why the producer lives in `extraction`.** Validation belongs where governance
lives, and `extraction` may not import `providers`. It does not need to: every
input to the digest already crosses the seam inside the contract mapping —
`operation_endpoints`, `endpoint_match_mode`, `endpoint_query_policy`,
`protocol_switch_policy`, `api_version`, and both policy versions. A second
producer on the `providers` side would have been a second source of truth.

**The digest is derived from what executes and compared with what governance
declared.** `derive_routing_contract` does not take `enablement` at all. This is
ADR-047's lesson applied again: a producer that could read the artifact it will
be checked against makes the tautology *representable*, and the only reliable
way to prevent it is to remove the parameter.

**The projection is closed at nine keys:** the code-owned `routing_contract_id`,
the executed `client_contract_id`, `api_version`, both operation endpoints, the
three endpoint/protocol policies, and both policy versions. `vertex_project`,
`vertex_location` and `model_name` are deliberately absent — each is already
encoded inside the two endpoint URLs, and a value that lives in two places can
drift in one of them.

**A byte binding, not a grammar binding — stated, not hidden.** Endpoint URLs
enter the projection exactly as the contract spells them. Re-implementing
`providers.endpoint_grammar_v2` inside `extraction` would create the second
grammar owner that module exists to prevent, so scheme, host, port, path, the
operation suffixes and the shared model base stay the connector's business.

The consequence is stated exactly rather than overstated: two spellings of one
endpoint produce **two different digests**, and that by itself is not a refusal.
An enablement pinned to the respelled contract's own digest matches it and the
run proceeds — measured, and asserted by a test. The refusal happens when a
*pre-existing* pin was minted from the other spelling. So what this binds is that
a route may not change underneath a fixed governance pin; it does **not**
deduplicate two spellings of one destination, and no claim to the contrary is
made. Deduplication is the connector's grammar, which normalizes before
comparing.

**The v2 identity gate is narrow, and is not a schema execution.**
`extraction_provider_client_contract_v2` declares forty-two properties under
`additionalProperties: false`; `validate_v2_contract_execution_fields` looks at
nine. The other thirty-three keep exactly the protection they had — the contract
digest the authorization pins. The gate exists because G4 materialization will
call `derive_routing_contract` directly, with no runner in the picture, and a v1
contract has no `operation_endpoints` at all: projected unchecked it would raise
`KeyError` at best, and at worst some future partial mapping would hash cleanly
into a digest describing a route nobody can execute.

**One owner for the v2 identity.** `CLIENT_CONTRACT_V2_CONTRACT` moved from
`run_extraction` to `manifests`, and `CLIENT_CONTRACT_V2_SCHEMA_VERSION` was
created because no constant existed — measured, the value lived only as a literal
inside the provider builder's returned mapping. Both are now imported by the
runner rather than re-spelled, an AST invariant keeps the identity literal to a
single occurrence under `extraction/`, and the schema version is checked against
`build_client_contract_v2(...)["schema_version"]` rather than against a literal,
because a literal would stay green if the builder started emitting `0.3.0`.

**Why four policy comparisons rather than one.** Comparing the authorization with
the client contract would accept two artifacts that echo one wrong value at each
other. Each side is compared with the pin instead, and their agreement follows.
The rate-limit pin carries a second job: `collection.transport` declares a field
of the same name with a different value for HTTP source retrieval, so the pin
states which namespace a model-execution run means.

**Order is part of the contract.** Shape/identity → digest comparisons → retry →
rate limit → routing → prompt plan. The gate precedes the digest comparisons so a
malformed contract is reported as malformed rather than as a digest mismatch;
policy precedes routing because a drifted policy version would also change the
routing digest, and blaming the route for carrying it would name the wrong cause;
retry precedes rate limit so a run whose two versions have both drifted always
reports `retry_policy_version_mismatch` instead of something that depends on
iteration order. Each of these three orderings is asserted by a test that makes
both defects true at once.

**Zero artifacts, and what is not claimed.** All three refusals happen after the
permit handshake and before `mkdir`, in a region no `try` encloses, so they never
reach `_classify_terminal`, publish no execution outcome, need no outcome-schema
successor, and leave no run root and no artifact. The permit is revoked by the
caller's `finally`. What is **not** claimed: that an injected provider's
`client_contract()` has no side effect. The runner calls it and cannot police it;
purity is the canonical connector's property, not a runtime guarantee.

**No schema and no spec change.** All four fields were already required by
released schemas, and both specs already asked for the routing identity/hash.
This increment implements an existing requirement rather than widening anything.

**Rejected alternatives.** Adding routing fields to the authorization was
rejected: it would have forced a `live_call_authorization@0.3.0` successor and a
full fixture migration to gain nothing, since the authorization already pins the
enablement by digest and the enablement already owns the route. Normalizing
endpoints inside `extraction` was rejected as a second grammar owner. Reusing
`budget_meter_protocol_invalid` for a routing failure was rejected: it maps to
`budget_termination`, which would publish a budget cause for something the budget
never did. Keeping the identity literal in `run_extraction` was rejected once a
second module needed it.



## ADR-049 — A canonical governance materializer: two roots, a sealed bundle, and eight post-write checks (G4-1)

**Status:** Accepted.

**The question this answers.** Since ADR-035 this package has *validated* four
governance records and *produced* none. Every test wrote them by hand and no code
path could state what a correct chain looks like, so the only executable
definition of a valid chain was the negative one embedded in the validators. This
module is the producer.

**Two roots, never one.** `governance_artifact_root` must already exist and be
empty when the four records are written, and is handed to
`run_extraction_stage_v2` afterwards so F0 can hydrate them again. `run_root` must
**not** exist when a run starts — `_require_absent_run_root` refuses it with
`run_root_exists`. The two requirements are opposites, so one path can never serve
both. The materializer has no concept of a run root at all, and an AST test
asserts the identifier is never bound in the module.

**Deterministic read-only, not pure.** Three digests in the prompt-qualification
record cannot be derived: they are the bytes of the frozen prompt, of SPEC-024,
and of the change request. `build_governance_records` therefore reads three files
under `repo_root`. What is asserted is the narrower true thing — nothing is
written, no clock, environment, socket or credential is reached, `providers` is
not imported, and the repository tree is byte-identical before and after. An
earlier draft claimed "no filesystem" and was wrong.

**The bundle is sealed.** `build_governance_records` returns canonical *bytes*, not
mappings. A caller that mutated a returned dict between building and writing would
change what the validators saw without changing what was written; bytes make that
unrepresentable. `GovernanceBuild` is frozen, `record()` re-parses on every call so
two callers never share an object, and the writer writes `payload()` verbatim and
then validates what it re-read **from disk**.

**Why the writer takes only the bundle.** `materialize_governance_records(build, *,
attempt_root)` has no third parameter. There is therefore no second place to pass
`stage` or `run_created_at`, and the value used to build a record cannot drift from
the value used to validate it. A signature test pins this.

**No caller-controlled reference — the second attempt.** The four references were
first published as a public `dict`, and that was a real defect rather than a
stylistic one: assigning into it changed both the pins a build returned *and* the
references embedded inside the written records, so the claim in this paragraph was
false in exactly the way it denies. The production source of truth is now a private
tuple reached through one private lookup, and `GOVERNANCE_REFERENCES` is a
read-only `MappingProxyType` that no internal path reads. Four tests hold the line:
item assignment and deletion are refused, rebinding the module attribute changes
neither the returned pins nor the embedded ones, every pin a build returns is one
of the four canonical paths, and the paths that land on disk survive a rebound
public view.

**Eight post-write checks, not one.** `validate_governance_chain_v2` has no
parameter for a prompt-qualification record, so calling it alone would leave P1–P14
unexercised — an earlier revision of this design made exactly that mistake. The
materializer runs the full set: chain, semantics, scope, prompt qualification,
policy versions, routing contract, budget meter identity, and the attempt-cap
arithmetic. The meter identity is passed as **code constants** rather than from the
bundle, because a caller-supplied value would restore the tautology ADR-047 closed.

**What `run_created_at` does and does not buy.** P14 checks `decided_at <=
run_created_at` and nothing more; no record stores a materialization timestamp.
A later instant inside both windows therefore passes, and the runtime cannot detect
that G5 used a different one. Using the same instant is a runbook rule, and the
suite asserts the limit rather than a guarantee. Full timestamp equality would need
a successor schema and is out of scope.

**Emptiness is total.** Not "the four targets are absent": a partial root left by a
failed attempt still lacks some of the four, and writing a second chain beside the
first one's remains would mix two attempts in one place. `os.listdir` never returns
`.` or `..` and does return dotfiles, so a stray `.gitkeep` disqualifies a root —
which is why a tracked container keeps its `.gitkeep` beside the attempt roots and
never inside one.

**Partial failure keeps what it wrote.** `write_bytes_once` is not a transaction: a
failure removes only the destination that call created. Earlier records stay, no
later record is written, and no authorization pin is returned — so a partial root
can never reach a run. The retry uses a new attempt root, and the emptiness rule
enforces that rather than merely recommending it.

**Declared symlink limit.** The materializer refuses a symlinked attempt root and
symlinked components beneath it, but does not walk the root's ancestry: refusing
every symlinked ancestor would reject ordinary platform paths — measured, `/tmp` is
itself a symlink on macOS. Creating the attempt root stays the runbook's explicit
step. The component guard is defence in depth over `write_artifact`'s `mkdir`,
because emptiness fires first for anything that pre-exists.

**Rejected alternatives.** A new top-level `governance` package was rejected once it
became clear the materializer needs no `providers` import: everything it wants is
inside the client-contract mapping its caller built, exactly as ADR-048 established.
Accepting `vertex_project` directly was rejected for the same reason — it arrives
inside the contract, and the module has no opinion about whether the project is real
or synthetic. Creating the attempt root was rejected as a side effect that would
leave "who made this root, under which container" answerable only by mtime.
Exposing the four private record builders was rejected: separately callable, they
would let a caller pin a chain in the wrong order.

**This ADR authorizes no materialization.** No real governance artifact has been
produced, no `vertex_project` value has been supplied, no ADC resolved, no client
built and no provider called. G5 remains unauthorized.


## Open decisions

- Required source packet by firm-year.
- Frontier-registry granularity.
- Gold-set size and expert-review protocol.
- Whether third-party sources receive a bounded validation-only role.
- Canonical eval-run root path (align with the repository run-layout decision; see ADR-012).
- General pipeline run layout and release promotion for Stages 01–04: whether future stages write to flat data zones or run-scoped roots, and how a run is promoted into a tracked release. Pilot 0's run-root layout is an Increment-B execution contract only and does not settle this (see ADR-031).
- Numeric gate thresholds, frozen-run budgets, and retest intervals (live in versioned scoring/gate/policy configs; see ADR-013, ADR-015, ADR-019).
- Protected-class taxonomy enumeration and change-classification policy contents (see ADR-020, ADR-021).
- Pilot cohort design document (see ADR-022).
- Physical removal of the ~537 unreachable lines of v1 provider-route code, left in place by ADR-045 as a separate cleanup increment.
- Whether the v2 client-contract seam should carry a credential scan. v1 had one through `validate_provider_client_contract`; v2 has none, and a contract pinned with credential material from the start would not be refused (see ADR-045).
- The evaluation-artifact root and the `evaluated_comparison` property set that would make an evaluated prompt qualification reachable (see ADR-044).
- A hash-bound carrier for the analytical period assignment. It stops at the admission artifact today, so no extraction output may be joined to a fiscal-year panel until a successor adds one (see ADR-046).
