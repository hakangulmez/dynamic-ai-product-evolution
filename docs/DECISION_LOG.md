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



## ADR-050 — Governance root placement and audit-trail retention (G4-3)

**Status:** Accepted.

**The question this answers.** G4-1 shipped a materializer that writes four
governance records into any existing, empty directory it is handed. It has no
opinion about *where* that directory is, and no policy existed for what happens
to the records afterwards. Both were left open by G4-0 and are decided here.

### D1 — placement

The governance root convention is

```
container    : artifacts/governance/
attempt root : artifacts/governance/gov-<company_id>-<stage>-<nnnn>/
```

Inside an attempt root the layout is fixed by code and cannot be configured: one
`governance/` directory holding the four write-once records.

**This is a runbook convention, not a runtime guarantee.** Measured:
`_require_attempt_root` checks only that the root exists, is a real directory, is
not a symlink, and is completely empty. It contains no `startswith`, no
`relative_to` and no parent comparison — nothing about location at all. Placement
is enforced by step R7 of the G3 runbook and by nothing else. Making it
runtime-enforced would need a separate code increment: a new constraint, a new
reason code, new tests, and the container path becoming a code-owned constant.

**Two roots, never one.** `governance_artifact_root` must exist and be populated
when a run starts; `run_root` must not exist at all (`run_root_exists`). The two
requirements are opposites, so one path can never serve both, and the
materializer has no concept of a run root.

**Why B and not A.** Measured: `artifacts/**` is ignored (`.gitignore:39`), while
`data/registry/governance/…` is trackable. Option A would put the real project
identifier into git history permanently and irreversibly. That matters because
the identifier is not confined to opaque digests — it appears as **plaintext
inside the `endpoint_allowlist`** of both the live-call authorization and the
adapter enablement record, in full URL form. The contract and routing digests are
one-way; an allowlist entry is not.

### D2 — retention

The four records are the audit trail, so the policy protects them rather than
assuming they can be regenerated:

- **Access owner** — a single operator; the container is narrowly permissioned.
  Whether synchronization or backup tooling covers that path is confirmed in
  writing before materialization.
- **Backup and recovery** — an operator-managed encrypted backup. Recovery
  restores bytes; it never regenerates them.
- **Retention** — successful attempt roots for the duration of the thesis work;
  failed and partial roots retained as evidence, never deleted.
- **Deletion** — only with explicit user approval, and recorded as a deletion
  event.

**`code_commit` is not sufficient for audit.** Measured:
`build_governance_records` requires seventeen parameters besides `code_commit`
and `repo_root` — the budget ceilings, the window, the identities, the people and
the client contract. None of them is derivable from a commit. A commit fixes what
the *code* was, not what the *decisions* were. If the records are lost the audit
trail is lost with them, and because they are outside git the loss is silent:
`git status` stays empty.

**Ledger boundary.** The exact backup location, the access list and the real
deletion events are held in a protected operator ledger outside this repository.
Neither this decision record nor the G3 runbook contains any of them, and the
ledger's own location does not appear in either. The tracked documents describe
the deletion-event *schema* and *policy*; they never accumulate events.

**A mechanical guard rather than a promise.** Four structural checks run as tests
over both tracked documents: no real endpoint URL of the form
`projects/<value>/`, no `vertex_project` field carrying anything but a
placeholder, no absolute local path, and no concrete backup or ledger location.
A fifth test plants a violation of each and asserts the scanner catches it —
without that, a scanner whose patterns had rotted would stay green.

A general project-identifier grammar scan was **rejected**: measured, the
identifier grammar matches twenty out of twenty ordinary English words and 203
distinct words in a single existing operations document. It would have been noise
rather than a guard.

**Rejected alternatives.** Option A was rejected for the plaintext-allowlist
reason above; option C — an absolute path outside the repository — was rejected
because the location would then be recorded nowhere. Retention policy R1 (no
backup, partial roots deleted immediately) was rejected: it makes a lost root
unrecoverable, and partial roots are the evidence that a materialization was
attempted and refused.

**This ADR authorizes nothing further.** No governance artifact has been
produced, no `vertex_project` supplied, no directory created, no ADC resolved, no
client built and no provider called. R8 and G5 remain unauthorized.



## ADR-051 — The temporal policy's availability list is synchronised with the canonical ontology (G6-T)

**Status:** Accepted.

`docs/TEMPORAL_POLICY.md` carried a copy of the availability taxonomy that had
drifted from the canonical list in
`docs/methodology/PRODUCT_CAPABILITY_TASK_ONTOLOGY.md`: one status token was
spelled with its two words transposed, and the `unknown` status was missing
entirely. `docs/THESIS_METHODOLOGY_AND_DATA.md` already matched the ontology, so
the temporal policy was the single outlier of three.

Both defects are corrected. The list now carries the same eight statuses as the
ontology, in the same spelling, and the temporal policy states explicitly that it
holds a copy and that the ontology governs any disagreement.

**Why this is a prerequisite rather than housekeeping.** The product
candidate-admission vocabulary planned in G6-V pins the canonical taxonomy by
reference and SHA-256 and enforces its token set by exact match. A second tracked
document offering a different spelling of the same concept, or omitting a status,
would make it ambiguous which literal an operator is expected to use. The
correction therefore lands before any vocabulary artifact is produced.

**Scope.** Documentation only. No schema, no code, no artifact, and no other
section of the temporal policy changes: the source-admission cutoff rule, the
ADR-046 cutoff-versus-period vocabulary, the historical-web-content rule and the
frontier-baseline section are untouched. The ontology file itself is not edited,
so its digest is unchanged and remains available as a stable pin target.

**Rejected alternative.** Correcting the ontology to match the temporal policy was
rejected: the ontology is the document CLAUDE.md's required-reading map names as
the ontology, and two of the three tracked lists already agreed with it.

## ADR-052 — A pinned candidate-admission vocabulary: the exact eight, a four-way partition, and one recorded human judgement (G6-V)

**Status:** Accepted.

`availability_status` is `{"type": "string"}` in
`schemas/product_observation.schema.json` — measured, unconstrained. So "may this
status enter a candidate record" had no answer in the schema layer, and no answer
anywhere else either. `product_candidate_availability_vocabulary@0.1.0` is that
answer for the `product_extraction` stage, produced by
`src/dynamic_ai_products/extraction/availability_vocabulary.py`.

**It is not the Rule-10 evaluator vocabulary.** ADR-028 gave Rule 10 governed
`active_status_values` and `roadmap_status_values` so that a capability or task
record supported only by future-roadmap evidence can be identified at the
evaluation stages. This artifact decides candidate admission at extraction. The
two are separate contracts with separate consumers; neither is derived from the
other, and they are not required to carry the same tokens. SPEC-023's Rule-10
paragraph now records that boundary so a later reader cannot merge them by
accident. `product_extraction` is **not** added to the evaluator's governed stage
set, which stays the closed four, and no rule text, stage matrix, applicability
table, blocking-reason vocabulary, per-rule hash or aggregate hash changes.

**The taxonomy is pinned, not remembered.** The artifact carries
`availability_taxonomy_reference` and `availability_taxonomy_sha256`, bound to the
literal bytes of `docs/methodology/PRODUCT_CAPABILITY_TASK_ONTOLOGY.md` through
the same containment-and-digest loader every governance artifact uses. If the
ontology text changes, existing artifacts stop validating and a new one must be
minted; the taxonomy cannot drift underneath a live vocabulary.

**What the pin does not do, stated exactly.** Nothing parses the ontology at
runtime. The eight tokens are a code-owned reviewed constant, exactly like the
ADR-047 budget-meter identity and the ADR-048 routing-contract identity. The pin
proves *which* taxonomy text an artifact was minted against; it does not prove
the constant was mechanically extracted from that text. Claiming otherwise would
be the ambient document reading this design rejects. A test asserts the equality
in the test layer, where reading the document is legitimate.

**Exact set, not subset.** `admitted_status_values` is the canonical eight —
`announced`, `broadly_deployed_or_default`, `deprecated`, `discontinued`,
`general_availability`, `private_beta`, `public_beta`, `unknown` — ascending and
duplicate-free. Two independent layers enforce it: the schema pins
`minItems == maxItems == 8` over a closed `enum`, and the loader compares an
ordered tuple. Adding or removing a status under `@0.1.0` is therefore impossible
and requires a contract successor. `planned`, which the ontology does not define,
cannot enter any list of any artifact.

**Seven loader checks the schema cannot express**, each with its own reason code
so the operator learns which invariant broke: ascending order
(`vocabulary_not_ascending`), the exact canonical set
(`vocabulary_not_canonical_set`), partition completeness
(`vocabulary_partition_incomplete`), pairwise disjointness
(`vocabulary_partition_overlapping`), per-list grammar
(`vocabulary_list_invalid`), the fixed placement of `unknown`
(`vocabulary_unknown_misplaced`), and the taxonomy pin
(`availability_taxonomy_pin_mismatch`). Disjointness is checked **before**
completeness because a duplicated token also shortens the union elsewhere, and
reporting the arithmetic defect would point the operator at the wrong list.

**The one human judgement, and its exact scope.** Which tokens are admitted is
settled by the taxonomy, not by an operator. What each admitted token *means* for
candidate admission is the decision this artifact records, together with who made
it and when:

```
vocabulary_version             : product-candidate-availability-v1
active_status_values           : broadly_deployed_or_default, general_availability,
                                 private_beta, public_beta
roadmap_status_values          : announced
non_active_known_status_values : deprecated, discontinued
unknown_status_values          : unknown
```

`active` is **only** the candidate-admission class of availability-supported,
not-roadmap-only statuses. It does not mean automatic human acceptance
(accept/reject stays a human decision), it does not mean a complete product
universe (a single pass is recall, not closure), and it does not mean a deployed
task — that claim belongs to SPEC-010 and requires its own evidence. Treating
`private_beta` and `public_beta` as `active` follows directly from that
definition: a beta is availability-supported and is not a roadmap statement.

**`unknown` is carried, never reclassified.** `unknown_status_values` is fixed at
exactly `["unknown"]` and is not a builder parameter at all, so the constraint is
structural rather than merely validated. An `unknown` candidate is admitted into
the collection as an ordinary entry and its disposition is left to human review.
This is CLAUDE.md rule 7 made concrete: insufficient evidence is a result to
record, not a rejection. It is deliberately the opposite arrangement from Rule 10,
where `unknown` sits outside both governed sets — the two layers answer different
questions.

**Write-once, validated on both sides of the write.** Materialization validates
the document, writes it into an attempt root that must already exist as a real,
non-symlink, completely empty directory, then re-reads the persisted bytes and
validates *those*. What is certified is what was persisted, not what was
intended. Creating the root stays an explicit operator step so that "who made
this root and when" has an answer outside the code, and a retry uses a new root
rather than writing beside a failed attempt's remains. The artifact lives under
the already-ignored `data/runs/`, so no `.gitignore` change is needed and the
REPO_MANIFEST completeness test cannot be tripped by it.

**Scope.** `schema_version_manifest.json` moves `0.16.0` → `0.17.0` with one new
entry, 46 → 47; both schema-version-manifest SHA guards are rebaselined and
neither is weakened. `REPO_MANIFEST.md` 590 → 593; the three count guards are
rebaselined. Extraction modules 20 → 21. `product_observation.schema.json` is
**not** modified — `availability_status` stays an unconstrained string, because
admission is governed by an artifact rather than by mutating an accepted schema.
No released contract, validator, prompt, runner route or governance record
changes, and no run artifact is produced by this increment.

**Rejected alternative.** Expressing the vocabulary as a twelfth-rule extension of
`validator_rule_parameters` was rejected: `product_extraction` is absent from the
evaluator's governed stage universe, so the parameter set could not have carried
it without widening that universe — which would have made one artifact answer two
different questions at two different layers.

## ADR-053 — A schema-bound successor prompt, and the released validator that was silently freezing the prompt registry (G6-P)

**Status:** Accepted.

Four changes that look separable and are not. Each one alone leaves the test
suite red; only together do they produce a `product_extraction` pass that can
return output the run's own schema check accepts. They are recorded as one
decision because they were shown, by measurement, to be one.

**1. The predecessor prompt could not have produced valid output.** Measured:
`schemas/product_observation.schema.json` is `additionalProperties: false` and
declares no `candidate_status`, yet `product_discovery_recall.md` asks for that
field. A conforming response to that prompt cannot validate against the released
stage-output schema. Separately, `availability_status` is an unconstrained string
in the schema and the prompt named no vocabulary, so any word at all arrived
structurally valid. `prompts/extraction/product_discovery_schema_v2.md` asks for
exactly the schema's required fields, names only optional fields the schema
declares, asks for no `candidate_status`, and carries the eight-token
availability vocabulary of ADR-052 as four labelled lists.

The predecessor's bytes are **unchanged** and it stays registered at position
two. `ext-smoke-0002` resolved it, and that chain must remain verifiable —
verifiable, not replayable. No replay of that run is promised.

**2. The registry moves, and the vocabulary-bound set is closed.**
`EXTRACTION_PROMPTS["product_extraction"]` becomes a three-element sequence with
the successor first, so `single_pass_prompt_plan` executes it;
`PROMPT_REGISTRY_VERSION` moves `extraction_prompt_registry_v1` →
`extraction_prompt_registry_v2`. `VOCABULARY_BOUND_PROMPT_IDS` is a code-owned
frozenset naming the successor: a prompt inside it carries the availability
vocabulary as literal text, a prompt outside it does not, and both directions
read that one source.

**3. A released validator was freezing a registry it does not own.** This is the
finding that made the increment indivisible, and it was found by running the
change rather than by reading the code. `validate_prompt_qualification` demanded,
in the same call path, that a record declare `extraction_prompt_registry_v1`
(a `const`) *and* that it equal the registry version the current build resolved
(an equality against `load_prompt`'s stamp). The moment the registry moved for
any reason those two became unsatisfiable together, so **no prompt could be
added or reordered** while `prompt_qualification_record@0.1.0` was in force.

The equality asked the wrong question. `load_prompt` stamps
`prompt_registry_version` from a module constant at call time, so it describes
the *build*, not the prompt artifact — it added nothing to the binding that
`prompt_id`, `prompt_reference` and `prompt_artifact_sha256` already establish
byte-exactly, while making every historical record invalid on an unrelated
change. A qualification record documents the registry version that was current
when it was minted; that is what it is for.

The equality is removed and the `const` becomes membership in
`KNOWN_PROMPT_REGISTRY_VERSIONS`, a closed tuple owned by `prompts.py` — the
module that owns the registry — so no second list can fall behind it. A record
naming a version this code never published is refused.

**What this loosens, stated plainly.** One literal becomes a two-element set.
That is a real widening and it is bounded: the set is code-owned, contains only
versions actually published, and the three checks that tie a record to its prompt
are untouched. A v1 record still cannot qualify a prompt other than the one the
route resolved; a test asserts exactly that.

**4. The successor needs its own qualification, and CR-0001 does not cover it.**
Measured: CR-0001 names `product_discovery_recall` and never mentions the
successor, so after the registry move P1–P4 refused every chain — correctly.
`evals/change_requests/CR-0002-product-discovery-schema-v2-bootstrap-qualification.md`
is the tracked document behind the successor's record, on the same
`bootstrap_pre_evaluation` basis as CR-0001: status
`bootstrap_authorized_live_dev`, scope `qualified_for_development`, lifecycle
`candidate`, no `review_decision`, `live_dev` only. It records a fifth known
limitation honestly — whether the successor actually elicits schema-valid model
output is **untested against a model**; only the shape it asks for has been
validated offline.

**Two schema-file edits, not glossed.** `prompt_qualification_record@0.1.0` keeps
its identity, version and property set, and every record that validated before
still validates. But its `prompt_id` is a closed `enum` that deliberately mirrors
the registry — the guarding assertion is named *the prompt-id vocabulary is the
registry and not a second list* — so the successor id is added to it; and its
`prompt_registry_version` carried the same `const` the validator did, so it
becomes the same two-element `enum`. Both edits are additive: every previously
admissible value stays admissible. The file's digest is pinned by nothing, so no
released artifact's hash chain moves.

**Offline binding, and what it is not.** `parse_prompt_status_vocabulary` and
`validate_prompt_vocabulary_binding` are pure functions over prompt text and a
vocabulary mapping — no file is opened, no prompt is resolved, no provider is
reached, and a test demonstrates the purity rather than asserting it in prose.
They check B4a–B4d as **ordered** list equalities plus B4e over the ordered
union. Ordered, because a label swap between `active` and `roadmap` leaves every
set and the union unchanged; only a position-by-position comparison refuses it.
Parsing is scoped to the one fenced block that carries all four labels, because
the prompt also names those labels in prose and a document-wide scan would read
the explanation as data.

**This binding is not yet enforced on the live run path.** It is a pure function
and a test, deliberately. Whether it becomes a hash-pinned artifact the runner
hydrates before a provider send is a separate decision, deferred with the rest of
the execution-bound design.

**Scope.** `REPO_MANIFEST.md` 595 → 596; the three count guards are rebaselined.
No authorization contract, chain validator, runner route, governance record,
ledger or run artifact changes. `data/` and `artifacts/` are untouched, and
`prompt_qualification_record@0.1.0`'s contract identity, `schema_version` and
property set are unchanged.

**Rejected alternative.** Reverting the registry move and leaving the successor
registered below the predecessor was rejected: `single_pass_prompt_plan` would
still resolve the prompt that asks for a field the released schema refuses, the
suite would be green, and the defect this increment exists to fix would be
untouched. A green suite over a known-broken execution path is worse than a red
one, because it stops being a question.

## ADR-054 — Identity is derived, not requested: the candidate conformance gate and its wiring (G6-M)

**Status:** Accepted.

The first run of the schema-bound prompt produced nineteen schema-valid
candidates and, measured against the locked C1–C6 gate, failed four of six
checks. Three of those failures were not the model's fault and not the gate's:
the prompt asks for identity fields the gate expects the pipeline to own. This
ADR settles that, and wires the collection step that had never been connected to
anything.

**Three fields are derived, and the reason is the one `candidate_id` already
established.** `candidate_id` has never been requested from a model, because an
identifier a model invents cannot be recomputed, therefore cannot be checked,
and a field that cannot be checked is not provenance. The same rule now applies
to `company_id`, `normalized_name` and `product_observation_id`:

```
company_id             = packet.company_id
normalized_name        = slugify(product_name)
product_observation_id = "{company_id}:{observation_cutoff}:{normalized_name}"   (ID-1)
```

**This is not silent repair.** Silent repair would be reading a wrong value and
quietly correcting it toward what validation wants. Here the three fields are
*not model output at all*: whatever the model emitted is discarded before
anything reads it, exactly as `candidate_id` has always been computed rather
than read. What the model is trusted for — the product's name, its status, its
evidence — is untouched, and every one of those still faces a gate.

The prompt is deliberately **not** changed to stop asking for these fields. It is
pinned by digest into a qualification record and a governance chain; editing it
to remove three lines would invalidate that chain for no gain, because the values
are overwritten either way.

**Measured consequence.** C1, C2 and C4 become tautologies after derivation.
They are kept: they cost nothing and they are the only thing that would catch a
derivation bug, which is now the sole remaining way those fields can be wrong.

**`slugify` is total.** A name it cannot slug yields the empty string rather than
raising, so the grammar `^[a-z0-9]+(-[a-z0-9]+)*$` has exactly one owner — C3 —
instead of being enforced in two places that could drift. ASCII-only by
construction: a Unicode fold would let two visually distinct names collide
silently, which is the opposite of what an identity component should do.

**Collisions are refused, not disambiguated.** Two distinct `product_name`
values that slug alike produce one `product_observation_id`, and under ID-1 that
means two different products sharing one longitudinal identity. Appending a
counter would make the identity depend on emission order and stop being
recomputable, so the collision is a refusal
(`candidate_conformance_observation_id_collision`) naming both ordinals and the
slug.

**Three layers, separately owned.** Collapsing them would destroy the released
`rejected[]` contract, whose `reason` enum is closed to `not_an_object` and
`schema_invalid`:

| layer | scope | on failure |
|---|---|---|
| parse gates | the envelope | refuse; a truncated response is **not** an empty result |
| pre-schema check | which items are observations | non-objects and schema failures fall through to `rejected[]` |
| C1–C6 | the collection | atomic refusal; never written as `schema_invalid` |

A conformance failure is not representable inside a collection and is not made to
look like one. Atomicity is at the **collection** level, not per observation:
one non-conforming record stops the whole materialization, because a partial
collection would silently under-report what the run actually produced.

**C5 asks one question.** Membership in `admitted_status_values` — not active,
not roadmap. All eight statuses are admitted, `unknown` included; it enters the
collection as an ordinary entry and its disposition is a human decision made
later. The set is hydrated from the ADR-052 artifact through the shared
containment-and-digest loader and re-validated by its own loader, so it is never
a constant in the consuming module.

**Ordering: derivation runs before schema validation.** `product_observation_id`
is schema-required, so deriving it afterwards would record an observation that
omitted it as `schema_invalid` for a field the pipeline was always going to
supply.

**The collection is published outside the run root.** Two tests fix the run
root's contents as an exact eleven-member set, and that count is the audit record
of one provider call. A collection is a *derivative* of that record; putting it
inside would make the invariant negotiable again for every future derivative. It
is written write-once into its own root and bound back by a repo-root-relative
reference to the raw artifact it derives from.

**Wiring is opt-in.** `run_extraction_stage_v2` gains three parameters that
default to `None`; with no collection root supplied the run behaves exactly as it
did before they existed. Publication happens **after** the run permit is revoked:
deriving candidates needs no provider, so holding a live permit across it would
widen the window in which a call is possible for work that can never make one.

**Known limitation, recorded rather than implied.** The vocabulary pin is a
parameter of the collection step. The design's D1–D6 derivation — recovering it
from the run root's persisted authorization — requires
`live_call_authorization@0.3.0`, which is deferred. Until then a caller could
point the step at a different vocabulary and only review would catch it.

**Scope.** `REPO_MANIFEST.md` 596 → 597; the three count guards are rebaselined.
No released contract, schema, prompt, governance record or published run root
changes; `extraction_candidate_collection@0.1.0` is not extended and its
`rejected.reason` enum is not widened.

## ADR-055 — A passage is cited by position, not by transcription (G6-R)

**Status:** Accepted.

Measured twice, on two independent live calls, and the two measurements agree
character for character. Under `product_discovery_schema_v2` the model was asked
to copy a 32-character `passage_id` into each evidence entry. In both
`ext-smoke-0003` and `ext-smoke-0004` the same candidate returned the same
corruption: `04917fd59df6da2499d38ea749a2c819` came back as
`04917fd59df6da249982a2c819` — first eighteen characters right, last six right,
the eight middle characters `d38ea749` collapsed to `82`. The other three
citations on that same candidate were correct.

The rendered document was read back from `inputs/rendered_provider_contents.md`,
so the model was shown the right value. This is not a renderer defect. It is a
reproducible transcription failure on a long opaque string, and `source_id` is
49 characters of the same material.

The consequence was disproportionate and correct: C6 refuses a citation that
resolves to nothing, and C6 is atomic, so one unreliable copy operation blocked
all nineteen candidates — including the eighteen whose evidence was sound.

**The fix is the rule this repository already follows twice.** `candidate_id` has
never been requested from a model; ADR-054 moved `company_id`,
`normalized_name` and `product_observation_id` from requested to derived. Long
identifiers are the same problem in a different place. Each rendered passage now
carries a short positional label in its header —
`[ref: P001] [passage_id: ...] [source_id: ...] [publication_date: ...]` — and
`product_discovery_schema_v3` asks for `evidence` entries of exactly
`{"ref": ..., "quote": ...}`, forbidding `source_id` and `passage_id` outright.
`resolve_evidence_refs` turns each label back into the real pair before schema
validation, so a conforming observation still carries
`{source_id, passage_id, quote}` and `product_observation.schema.json` is
**not** modified.

**The identifiers stay in the rendered header.** The model no longer copies them;
a human auditing the archived document still needs to reach the underlying
passage without recomputing a label.

**One sorter, and this is the part that matters.** The renderer has always
emitted passages ordered by `(source_id, passage_id)`, not in the packet's own
list order — its docstring says so and a test has fixed it since E-R. A resolver
that indexed `packet["passages"]` would therefore have attached quotes to the
wrong passages. Measured on the pilot packet: **121 of 124 positions differ**
between the two orders. That failure would have been silent, because every
position named would still be a real one, and the corrupted candidate happens to
sit at canonical position `P003`.

So the order is decided in exactly one place. `canonical_passage_order(packet)`
is the single sorter; the renderer and the resolver both call it. Two `sorted`
calls that agree today would be one rule living in two places, and this
increment exists because a rule living in the model's memory did not hold.

**A new failure mode gets a new code, not a borrowed one.** An out-of-range or
malformed label is refused with
`candidate_conformance_evidence_ref_unresolvable`, separate from
`candidate_conformance_evidence_pair_unknown`. "Invented an identifier" and
"named a position it was not shown" are different faults with different fixes,
and folding them together would tell an operator less than the old code did.

**What this does not establish.** The two archived failures prove the long form
is unreliable. They do not prove the short form is reliable — that is untested
against a model and is recorded as a known limitation in CR-0003. A label also
names a position rather than a passage, so it is safe only because it is
resolved against the packet the run was built from, in the same process, through
the same function that rendered it. A label is never stored as an identity and
never carried across runs; the persisted artifact holds the real pair.

**Scope.** New prompt `product_discovery_schema_v3` at position one; the
registry moves `extraction_prompt_registry_v2` → `v3` and the ADR-053 known-set
mechanism absorbs it with no validator change. `product_discovery_schema_v2` and
`product_discovery_recall` keep their bytes and their registration so
`ext-smoke-0002`, `-0003` and `-0004` stay verifiable; CR-0001 and CR-0002 are
untouched. `prompt_qualification_record@0.1.0` keeps its identity, version and
property set; its `prompt_id` and `prompt_registry_version` enums mirror the
registry and gain the new values additively. `REPO_MANIFEST.md` 597 → 599.

**Rejected alternative.** Relaxing C6 to accept a near-miss identifier — for
example by prefix matching — was rejected outright. It would convert a refusal
that correctly caught a real defect into a heuristic that silently attaches
evidence to whichever passage looks closest, which is fabrication with extra
steps.

## ADR-056 — The status is named by label: the last transcription leaves the output (G6-R2)

**Status:** Accepted.

ADR-055 worked. On `ext-smoke-0005` the label mechanism resolved 28 of 28
citations and C6 passed for the first time. The run still produced no
collection, because the one remaining field the model was asked to copy
character for character failed in exactly the way the previous one had:
fourteen candidates wrote `broadly_deployed_or_default` and one wrote
`broadly_deployed_or_or_default` — the syllable `or` doubled, 30 characters
instead of 27.

Under the atomic C5 gate one ungoverned status refuses the whole
materialization, so a doubled syllable blocked fourteen correct candidates.

**Third instance, third application of one rule.** `candidate_id` was never
requested. ADR-054 derived `company_id`, `normalized_name` and
`product_observation_id`. ADR-055 replaced transcribed `passage_id` and
`source_id` with positional labels. The status token was the last field in the
output a model still had to reproduce exactly, and it is now the last one
removed: the prompt renders a table of `S1`–`S8` and asks for the label;
`resolve_status_labels` turns it back into the token before schema validation
and before C5.

**The label table is a view of the constant, not a second list.** It is
generated by `status_label_table()` from
`CANONICAL_AVAILABILITY_STATUS_VALUES` in its own order, and a test asserts the
prompt's rendered table matches that function's output exactly. Inventing an
ordering here would be the defect ADR-055 closed structurally for passages.

**Simpler than the passage case, and the difference is worth stating.** A
passage label names a position in a packet, so renderer and resolver had to
share one sorter or a label would mean two things. A status label names a
position in a code-owned tuple that no run can vary, so it is stable across
runs — but it is still not an identity: the persisted artifact stores the
resolved status word, never the label.

**The four partition lists stay in the prompt, with real tokens.** They are what
the model reads to decide *which* status applies, and they are what the B4
offline binding compares against the vocabulary artifact. Replacing them with
labels would have deleted the only check that proves the prompt's copy has not
drifted from the artifact — measured: `parse_prompt_status_vocabulary` enforces
`^[a-z][a-z0-9_]*$` per token and B4a–B4d compare element by element, so a block
of `S1`…`S8` would fail both. The model reads tokens for meaning and emits
labels for transport, which is the same split ADR-055 made for passages.

**Strict in both directions, deliberately.** A label outside `S1`–`S8`, a
malformed value, *and a correctly spelled status word* are all refused with
`candidate_conformance_status_label_unresolvable`. Accepting the spelled form
would let one run mix two conventions and would quietly restore the
transcription this change removes. The cost is real and is accepted: a run where
the model ignores the label instruction fails entirely rather than partially.

The code is separate from `candidate_conformance_status_not_governed` for the
reason ADR-055 gave for its own: "named a status outside the vocabulary" and
"gave something that is not a label at all" are different faults with different
fixes.

**What this does not establish.** Three archived runs establish that long
strings are copied unreliably. None of them establishes that short labels are
copied reliably — that is untested against a model and is recorded as a known
limitation in CR-0004.

**Scope.** New prompt `product_discovery_schema_v4` at position one; registry
`extraction_prompt_registry_v3` → `v4`. Every predecessor keeps its bytes and its
registration, so `ext-smoke-0002` through `-0005` stay verifiable; CR-0001
through CR-0003 are untouched. `product_observation.schema.json` is **not**
modified — the artifact still stores the real status word.
`prompt_qualification_record@0.1.0` keeps its identity, version and property set;
its two enums gain the new values additively. `REPO_MANIFEST.md` 599 → 601.

**Rejected alternative.** Re-running the same prompt and hoping the corruption
did not recur was rejected. The `passage_id` corruption reproduced character for
character across two independent runs; in this failure class, repetition has
already been measured not to help.

## ADR-057 — A decision set records who decided: `extraction_validation_decision_set@0.2.0` (G6-D)

**Status:** Accepted.

The first real human validation produced a decision set that says which
candidates were accepted and why, and cannot say who accepted them or when.
Measured: `@0.1.0` is `additionalProperties: false` and its property set has no
`decided_by` and no `decided_at`, so the field is not merely absent — it is
unrepresentable.

**Why this is not the `run_created_at` case.** That value has no carrier either
and lives in an operator ledger outside the repository, which was the right
answer for an operational timestamp about how a run was executed. This is a
different kind of fact: *who admitted which observation into the dataset, on
what grounds*. That sits at the centre of the project's evidence-grounded claim.
Keeping it in a repo-external ledger would separate the provenance from the
data, and a later reader holding the decision set would not find the answer in
the file they are holding. So it belongs in the artifact.

**Additive successor, released contract untouched.**
`extraction_validation_decision_set@0.1.0` and its schema file stay
byte-identical; `@0.2.0` adds `decided_by` and `decided_at` as **required**
fields and changes nothing else. Nineteen required properties instead of
seventeen. The two are separate contracts and the dispatch is closed both ways:
a `@0.2.0` document fails the `@0.1.0` schema on the `contract` const, and a
`@0.1.0` document fails `@0.2.0` on the two missing required fields. Both
directions are asserted.

**One definition of what a decision is.** `build_validation_decision_set_v2`
delegates the entire judgement to the released builder — every pin rule, the
Snapshot A product/capability split, the accepted-artifact requirement, the
counts — and adds exactly two fields. A second implementation would be a second
place for the rules to live. A test asserts the successor's output differs from
the released one only in `contract`, `schema_version` and the two new keys.

**`decided_at` must carry an explicit UTC offset**, parsed through the same
`_require_aware_instant` every governance record uses. A naive instant is
refused rather than assumed to be UTC: guessing a zone on the record of a human
admission decision would be inventing provenance, which is the specific thing
this ADR exists to stop.

**A const would have frozen the artifact, again.** Measured before writing
anything: `parent_snapshots` gated the decision set it reconciles against with
`decision_set.get("contract") != "extraction_validation_decision_set@0.1.0"` —
a single literal. Every `@0.2.0` decision set would have been refused at the
snapshot step, which is the *next* link in this chain. This is exactly what
ADR-053 found in the prompt-registry const, and it takes the same fix: a closed
`KNOWN_DECISION_SET_CONTRACTS` tuple owned by the module that publishes the
contracts, recognised rather than re-declared by the consumer.

**Scope.** New schema file
`schemas/extraction_validation_decision_set_v2.schema.json`;
`schema_version_manifest.json` `0.17.0` → `0.18.0`, 47 → 48 entries; both
manifest SHA guards rebaselined. `REPO_MANIFEST.md` 601 → 602. No prompt,
governance record, run root or published collection changes.

**The `@0.1.0` decision set already written is kept, not replaced.**
`data/runs/decisions-ext-smoke-0006-0001/` stays exactly as produced — it is
evidence of what the released contract could express. The `@0.2.0` set is
published beside it in `-0002` with the same eighteen decisions and the same
reasons, verified equal decision by decision. Overwriting a write-once artifact
to make a record look like it always carried a field it did not would be the
kind of silent repair CLAUDE.md rule 9 forbids.

**Rejected alternative.** Recording the human in the operator ledger, as with
`run_created_at`, was rejected for the reason above: it would put the dataset's
own admission provenance outside the dataset.

## ADR-058 — The capability stage becomes materializable, and its parents are labelled (E-S1)

**Status:** Accepted.

`capability_extraction` has failed closed at the renderer since E-R, and the
reason was never that the stage was unwanted: it had no governed parent context
to render. That changed when a human-validated Snapshot A came into existence.
The packet builder already reconciles A (E1 + E5) and hands the renderer
`parent_context.product_parents`, so `MATERIALIZATION_SUPPORTED_STAGES` gains
the stage and a fourth binding, `validated_products`, joins its map.
`task_extraction` stays closed: it needs Snapshot B, which does not exist.

**A deliberate subset, not the payload — and the measurements decided it.**
Rendering the full observation payload for eleven products costs 14,528
characters; the three-field subset costs 1,197. But cost is the weakest of the
three reasons:

- **`evidence` is 64% of the full payload and is text the model already has.**
  Those quotes come from the same passages rendered under
  `{{passages_with_ids}}` with `P0NN` labels. Showing them again under an `A0N`
  label gives the model a second place to quote from — one with no citation
  label attached — which reopens exactly the defect ADR-055 closed. This is the
  reason that would stand even if tokens were free.
- **`product_observation_id` is 44 characters.** It is the string the `A0N`
  label exists so the model never transcribes. Putting it back in the block
  invites the transcription.
- **The parent's `availability_status` would bias a judgement the capability
  must make from its own evidence.** A capability's availability is its own
  field, decided from what the passages say, not inherited.

What remains is `product_name`, plus `product_family` and `entity_type` when
present — enough to tell `Breeze Copilot`, `Breeze Agents` and
`Breeze Intelligence` apart, which is what attribution actually needs.
`target_customers` and `ambiguity` were measured absent on all eleven.

**No second sorter.** `derive_parent_context` already returns parents ordered by
`(observation_id, reference)`, from members that were re-read and hash-verified
against Snapshot A. The binding labels that sequence and renders it; it does not
choose an order. This is ADR-055's `canonical_passage_order` rule applied
again — one place decides, everyone else obeys.

**Enabling the stage removed a guard, and running the change is what found it.**
The E-R docstring had warned that rendering the placeholder-free capability
prompt verbatim "would send an instruction naming no products at all". That
warning was enforced only as a side effect of the stage being unsupported. With
the stage enabled, an existing end-to-end test stopped raising: a fully valid
capability run reached the provider carrying the old markerless prompt.

So the protection is made deliberate and narrow.
`STAGE_REQUIRED_PLACEHOLDERS` names placeholders a stage's prompt **must** use,
and the capability stage must use `validated_products`
(`contents_placeholder_required`). The rule encodes an invariant, not a style
preference: `capability_observation@0.1.0` requires `product_observation_id`, so
a capability extracted without its parents is attributable to nothing, and a
paid call that cannot produce a conforming record should not be made. The
product stage requires nothing — none of its three placeholders is load-bearing
in that way.

**`RENDERER_VERSION` is unchanged.** It identifies how rendered content is
determined, and the product stage's output is byte-identical: same bindings,
same block format, same order. Which stages are supported is
`MATERIALIZATION_SUPPORTED_STAGES`'s own business, and it is not folded into the
renderer identity.

**What this does not do.** The capability prompt is still
`prompts/extraction/capability_extraction.md`, unchanged and unusable: measured,
it carries zero placeholders, names three of six required schema fields, defines
no output format, no closed status vocabulary and no evidence format, and points
the model at a schema file it cannot see. E-S1 makes the stage renderable; it
does not make it runnable. The required-placeholder gate is what keeps that
distinction from being discovered by a live call.

**Test dispositions — five, none deleted.** The three renderer assertions the
scope named (the closed binding map, the supported-stage tuple, the two-stage
unbound parametrization) are rebaselined. The placeholder-free capability test
keeps asserting a refusal and changes only *which* refusal. The end-to-end
run-publication case keeps every other assertion — permit reached, zero
artifacts, neither send, permit revoked — and changes only the expected reason
code for the capability parameter.

**Scope.** Three modified paths, no new files, no manifest count change. No
prompt, schema, governance record, run root or published artifact changes.

## ADR-059 — A schema-bound capability prompt: the fourth application of one rule (E-S2)

**Status:** Accepted.

`prompts/extraction/capability_extraction.md` has never been executed, and
measured against the released schema it could not have produced a conforming
record. `capability_observation@0.1.0` is `additionalProperties: false` and
requires six fields. The prompt names three of them. It declares no output
format, no closed status vocabulary and no evidence format, carries **zero**
placeholders — so no company, cutoff, passages or parent products reach the
model at all — and instructs the model to "Return JSON conforming to
`capability_observation.schema.json`", a file the model cannot see.

That is the CR-0003/CR-0004 defect class one step worse: the product prompt
asked for a field the schema refuses; this one does not ask for most of the
fields at all. `capability_discovery_schema_v1` replaces it at position one;
the retired prompt keeps its bytes and its registration.

**Everything the pipeline can derive is derived — the fourth application.** The
model supplies `parent_ref`, `capability`, a status label, `confidence` and
labelled evidence. It supplies no identifier of any kind:

| field | how the model names it | what the pipeline does |
|---|---|---|
| parent product | `A01`…`A0N` (ADR-058 block) | resolves to `product_observation_id` |
| evidence | `{"ref": "P0NN", "quote": …}` (ADR-055) | resolves to `{source_id, passage_id, quote}` |
| status | `S1`…`S8` (ADR-056) | resolves to the token |
| `normalized_capability` | — | `slugify(capability)` (ADR-054) |
| `capability_observation_id` | — | `{product_observation_id}:{normalized_capability}` |

`product_observation_id` is 44 characters of colon-joined slug. Asking a model
to transcribe it is the failure this repository has now measured three times, so
it is not asked. The prompt says so explicitly and states that a candidate
carrying any derived identifier is rejected.

**One vocabulary, two stages.** `availability_status` is an unconstrained string
in the capability schema exactly as in the product one, so the ADR-052 artifact
governs both and the prompt carries the same four labelled partition lists. B4
binds it unchanged. The prompt states in words what ADR-058 enforced in the
rendered block: the status describes **the capability**, judged from its own
evidence, not the availability of its parent.

**`input_types` and `output_types` are optional, and the schema is why.**
SPEC-009's prose lists them among required fields; the released schema does not
put them in `required`. Throughout this work the schema has been the contract
and the prose the commentary, and that does not change here. They are requested
on the evidence-supported-or-omitted rule, because a model asked for a field it
cannot support will supply one anyway — which is how `candidate_status` and a
doubled syllable got into earlier runs.

**Attribution is the new failure surface, and it is not closed here.** A
capability attributed to the wrong neighbouring product would be structurally
valid: a real `A0N`, a real passage, a conforming record. Only review would
catch it. The prompt states the rule three times — one capability, one parent;
omit rather than guess; flag uncertainty in `ambiguity` — and the conformance
gate that checks the parent is genuinely a Snapshot A member is deferred to
E-S3 rather than assumed here. Recall is also bounded by Snapshot A by
construction: a capability of a product a human rejected cannot be found. That
is intended, and it means capability coverage inherits every limitation of the
product decision set.

**Scope.** New prompt at position one; registry `extraction_prompt_registry_v4`
→ `v5`; `KNOWN_PROMPT_REGISTRY_VERSIONS`, `VOCABULARY_BOUND_PROMPT_IDS` and both
`prompt_qualification_record` enums gain the new values additively. CR-0005 is
the tracked document the qualification record will pin. `REPO_MANIFEST.md`
602 → 604. No schema, governance record, run root or published artifact
changes; every product prompt and CR-0001 through CR-0004 are untouched.

**Two rebaselines worth naming.** The capability stage registered exactly one
prompt, so `prompt_sequence_complete` was `True` for it; with a two-element
sequence a single pass is a recall set there too, as it already was for product
and task. And the end-to-end case that asserted "a fully valid non-product stage
is blocked by the renderer" now refuses the capability stage *earlier* — its
fixture deliberately still names the retired prompt, so P1–P4 refuse with
`prompt_qualification_mismatch`. That a chain minted for a superseded prompt
cannot execute its successor is the protection ADR-053 built, and the test now
exercises it end to end instead of asserting a renderer gate that no longer
applies.

**What this does not do.** No derivation, no conformance gate, no governance
round and no live call. E-S2 makes the capability stage *qualifiable*; E-S3 and
E-S4 make it runnable.

## ADR-060 — The capability branch: one parameterized pipeline, and a gate with no product counterpart (E-S3)

**Status:** Accepted.

Measured before deciding: of the seven steps between a raw envelope and a
written collection, **five are already kind-agnostic** — the parse gates,
evidence resolution, status resolution, and `build_candidate_collection`, which
has taken `observation_kind` since ADR-033. Only `derive_identity_fields` and
`assert_candidate_conformance` assume the product, and only in which field names
they read and write.

So the pipeline is **parameterized, not duplicated**. A parallel capability path
would have copied those five steps and given the same rules two homes, which is
the failure this work has spent the whole increment series closing — one sorter,
one vocabulary owner, one registry-version set. `observation_kind` defaults to
`product` everywhere, so no existing caller and no published run changes.

**A third label family, resolved the same way.** `resolve_parent_refs` turns
`parent_ref: "A01"` into the `product_observation_id` it names, reading
`parent_context.product_parents` — the same ordered, hash-verified sequence
ADR-058 assigned the labels from, so there is no second mapping to keep in step.
The key is removed once resolved, because `capability_observation@0.1.0` is
`additionalProperties: false` and knows no `parent_ref`.

`product_observation_id` is 44 characters of colon-joined slug. Asking a model
to transcribe it is the failure ADR-055 and ADR-056 each measured; it is not
asked. Its own reason code, `candidate_conformance_parent_ref_unresolvable`,
stays separate from the evidence one for the reason ADR-055 gave: "named a
product position it was not shown" and "cited a passage that does not exist" are
different faults.

**The identity is derived from its parent, which fixes the order.**

```
product     -> {company_id}:{observation_cutoff}:{slug(product_name)}
capability  -> {product_observation_id}:{slug(capability)}
```

The parent id is a *component* of the child id, not a sibling field, so parent
resolution must precede derivation. The chain is therefore a dependency order
rather than a preference: evidence refs → parent ref → status label → identity →
schema.

**Collision scope falls out of the formula.** Two products may legitimately
offer the same capability — Marketing Hub and Sales Hub can both "generate
reports". Because a capability id begins with its parent's id, the existing
`seen` map gives per-parent scope with no second mechanism and no change to how
it is keyed. Measured: same parent plus a respelled name collides; different
parents with the identical name do not.

**C7 replaces C1 and C2 rather than joining them.** A capability record carries
neither `company_id` nor `observation_cutoff` — measured, neither is a property
of the released schema. Both facts reach it through the parent, whose id *is*
`{company_id}:{cutoff}:{slug}`. So C7 — the parent is one of this run's
Snapshot A members — proves what C1 and C2 proved, and proves something they
could not: **that a human admitted this parent**.

That gate has no product-side counterpart and is the one genuinely new check
here. Without it, a capability attributed to a product the human *rejected*
would be structurally valid — a real-looking id, a real passage, a conforming
record — and only review would catch it. Recall is bounded the same way by
construction: a capability of a rejected product cannot be found. That is
intended, and it means capability coverage inherits every limitation of the
product decision set.

**Verified against real data, not fixtures.** The chain was run end to end over
the pilot Snapshot A: `A04` resolved to `…:commerce-hub`, the derived identity
came out `…:commerce-hub:accept-and-reconcile-customer-payments`, C1–C7 passed,
and four negative cases refused with their own codes — out-of-range label,
malformed label, a parent the human rejected, and a within-parent collision —
while the same capability under two different parents correctly did not collide.

**Scope.** Two modified source paths, one modified test module, no new files, no
manifest count change. No prompt, schema, governance record, run root or
published artifact changes.

**What this does not do.** No governance round, no capability collection root,
no live call. E-S3 makes the capability branch *executable offline*; E-S4 runs
it.

## ADR-061 — A stage declares its observation kind: closing the gap ADR-060 left at the call site (E-S4 preflight)

**Status:** Accepted.

ADR-060 parameterized the candidate pipeline and did not thread the parameter
through its one caller. `run_extraction_stage_v2` called
`materialize_candidate_collection` without `observation_kind`, so the default
applied — and the default is `product`.

**Why that would have been silent.** A capability run would have collected
capability observations against the *product* schema. Each one fails it, so each
lands in `rejected[]` as `schema_invalid` and the collection is published
reporting `accepted_candidate_count: 0` — a structurally valid document, its
counts internally consistent, its schema satisfied. C1 through C7 would never
have run: they gate only what survives the pre-schema check, and nothing would.
No gate fires, no artifact is missing, and the only symptom is a collection that
found nothing.

Found before the live call rather than by it. A test reproduces it against the
released schemas: the same two capability observations collected as `product`
give `accepted=0` with two `schema_invalid` rejects; collected as `capability`
they give `accepted=2` with none.

**The fix is a closed map, not an inference.** `STAGE_OBSERVATION_KIND` names
the kind each stage produces, and `observation_kind_for_stage` resolves it or
refuses with `stage_observation_kind_undeclared`. **It never falls back**, which
is the whole point: a default is what turned a wrong kind into an empty
collection.

A mechanical derivation — stripping `_extraction` from the stage — was rejected
for the same reason. It would silently mint `task` as an observation kind, and
`OBSERVATION_KINDS` has exactly two members.

**`task_extraction` is deliberately absent.** A task is not an observation kind
and must not become one by inference; when it is, it will be added on purpose
with a schema behind it. The absence follows the pattern
`MATERIALIZATION_SUPPORTED_STAGES` and `STAGE_REQUIRED_PLACEHOLDERS` already
set: a stage missing from a closed map is refused with a named code, never
defaulted and never guessed.

**Scope.** One map, one resolver, one call site, one test section. No new files,
no manifest count change, no schema, prompt, governance record, run root or
published artifact changes. The default on `materialize_candidate_collection`
stays `product`, so nothing that calls it directly is affected.

## ADR-062 — A stage cites its own change request: the fourth stage-agnostic constant (E-S4 preflight)

**Status:** Accepted.

`governance_materializer.CHANGE_REQUEST_REFERENCE` was a single constant naming
the product prompt's change request. The first capability governance round used
it, and the capability chain was written citing
`CR-0004-product-discovery-schema-v4` — a document about a different prompt, for
a different stage.

**Nothing caught it, and the reason matters.** The reference resolves, the
document exists, its digest matches, and `validate_prompt_qualification` checks
exactly that. All eight post-write validators passed. The chain was internally
consistent and provably wrong: `CR-0005`'s own text says "Recorded in the
`prompt_qualification_record` issued against this change request", and no record
pointed at it.

**Fourth instance of one pattern.** ADR-053 found a `const` pinning the prompt
registry version, ADR-058 found a guard that existed only as a side effect of a
stage being unsupported, ADR-061 found a defaulted `observation_kind` at a call
site. Each was a value written when one stage existed, and each became wrong the
moment a second one did. This is the same shape in the governance producer.

**The fix is the same shape too.** `STAGE_CHANGE_REQUEST` maps each stage to its
own change request; `change_request_for_stage` resolves it or refuses with
`stage_change_request_undeclared`. It never falls back — a default is precisely
what let the wrong document through. `task_extraction` is absent because it has
no qualified prompt.

The digest is computed from whatever the resolver returned, so reference and
digest cannot disagree; a test asserts the two stages produce different values
for both.

**Known limitation, recorded rather than implied.** This map states *which
change request is current*, so it must be updated whenever a stage's prompt is
superseded — as CR-0002 → CR-0003 → CR-0004 already were, by hand each time.
Binding the change request to the prompt itself would remove that step. That is
a larger contract decision than this defect requires and is deliberately
deferred.

**The failed attempt root is kept.**
`artifacts/governance/gov-CIK0001404655-capability_extraction-0001` holds four
records citing the wrong change request. It is not deleted and not reused: a
populated attempt root is refused by construction, a retry uses a new one, and
the failed chain is evidence of what happened — the same treatment `-0001` and
`-0002` received on the product side. No ledger was written for it, so the wrong
chain never gained a durable witness.

**Scope.** One map, one resolver, one call-site change threading the resolved
reference through the builder, one test section. No new files, no manifest count
change, no schema, prompt, published run root or committed artifact changes.

## ADR-063 — C8: the quote must occur in the passage it cites

**Status:** Accepted.

**How this was found.** A separate tool, `codex`, reported a bad evidence quote
in the `ext-smoke-0006` product collection, candidate
`5a283c3092fdd07cea8e93dd9fd1d808` (Sales Hub). The operator verified it
independently, and so did this repository's own measurement before any code was
written. It is real.

**What the artifact actually says.** The first evidence entry cites passage
`5f626aca2f9ccb26f2aaa7bab4fdc6a6` and quotes 462 characters. Measured: the
first 259 of those are the entire text of that passage, and the remaining 203
are a space followed by the entire text of a *different* passage,
`154ebc01d989481530eba7b57f9c30e1`. The quote is exactly
`text(A) + " " + text(B)`, filed under A's identifier alone.

The two passages are not even adjacent: A ends at source offset 318807 and B
begins at 319702, 895 characters apart. So this is not a boundary-straddling
span that a reasonable reader would call one quotation. It is two separated
passages joined into one citation.

**How wide.** The whole `ext-smoke-0006` collection was scanned: 18 candidates,
34 evidence entries, **exactly one** failure. The other 33 quotes occur verbatim
in the passage they cite. This is a rare fault, not a systemic one — which is
why nothing downstream noticed it.

**Why C6 did not catch it, exactly.** C6 asks one question: is
`(source_id, passage_id)` a pair this run's packet contains? It never touches
`entry["quote"]`. Both identifiers here are genuine passages of this run, so C6
was satisfied with room to spare, and no other gate in the materialization path
reads the words at all. The evidence requirement in `CLAUDE.md` — every claim
carries a short evidence quote — was being enforced as *a quote is present*,
never as *the quote is there*.

**The semantics already existed and were not connected.**
`evaluation/validators.py::_handle_evidence_quote_containment` has carried the
same two conditions since the harness was built. It runs only on the evaluation
path; the product and capability materialization path in
`extraction/candidates.py` was never wired to it. That function is private,
returns a `_RuleOutcome` tuple shaped for finding records rather than a refusal,
and belongs to a different layer, so C8 is written independently in the C-series
style rather than imported. The cost is one duplicated rule; the alternative was
a cross-layer dependency between the evaluator and the extractor, which the
separate-layers rule forbids.

**Why a separate reason code.** `candidate_conformance_evidence_quote_uncontained`
is not folded into C6 for the same reason ADR-055 kept its label codes separate:
these are different failure classes and an operator needs to know which one
happened. C6 means *the identifier is not real* — the model invented or
mistranscribed a passage id. C8 means *the identifier is real and the words are
not in it*. Reporting a spliced quote as C6 would send someone looking for a
nonexistent identifier.

C8 runs immediately after C6, per evidence entry, and only once C6 has proved
the pair resolves — so the text it compares against is this run's own corpus and
cannot be some other run's. Both gates read one mapping, built once from
`packet["passages"]`: C6 asks whether a pair is a key, C8 asks what that key maps
to. A second pass over the same passages would have been a second chance to
disagree about which corpus is authoritative.

A blank quote fails rather than passing by the empty-string-is-a-substring
accident. The refusal message carries the ordinal and the cited pair and never
the quote or the passage text: a refusal names what failed, not the contents
that failed it.

**Atomicity is unchanged.** One bad quote refuses the entire collection
materialization. Nothing partial is written and nothing is silently dropped —
the same discipline C1 through C7 already had.

**The persisted Sales Hub record is deliberately untouched.**
`data/runs/decisions-ext-smoke-0006-0001` and `-0002` are not edited, not
deleted, not overwritten. Raw sources and persisted observations are immutable,
and a correction creates a new version with its own manifest; it is not a silent
repair applied to bytes a human already validated. That correction is a separate
decision and is not being made here. `ext-smoke-0006`, its candidate collection,
and Snapshot A are likewise unchanged. What C8 changes is what can be admitted
**from now on**.

**Scope.** One reason code, one check inside `assert_candidate_conformance`, one
mapping widened from a set to a dict, one test section. No schema change — C8 is
a code-side rule, and `product_observation.schema.json` still types `quote` as a
plain string. No new files, no manifest count change, no governance record, run
root or published artifact touched.

**Known limitation.** C8 proves the quote is a substring of the cited passage.
It does not prove the quote is *the right* substring, that it supports the claim
made, or that the model chose the most relevant passage. Those remain review and
evaluation obligations. Claiming otherwise would be the ambient reading this
project rejects.

## ADR-064 — The correct answer becomes the natural one: unpadded passage labels for the capability stage

**Status:** Accepted.

**The measurement, and why it ends the retry option.** Two capability live calls
were refused at the same place. `ext-smoke-cap-0001` returned 81 observations
with 81 evidence citations, 80 of them correctly written `P0NN`, and one written
`P25` where the rendered label was `P025`. `ext-smoke-cap-0002`, run against a
fresh governance chain at a later commit, returned output that was
**byte-identical** — the same SHA-256 over the model's text, the same single
failure, the same observation, the same label.

So `temperature=0` is doing what it says. This is not a sampling accident that a
third attempt clears; it is a reproducible property of this prompt, this packet
and this model. Two governance rounds and two paid calls bought the same
refusal.

**Root cause as stated by the operator, and confirmed by the artifact.** The
model reads `025`, processes it as a number, and re-emits the number the way
numbers are naturally written. The prompt asked it not to. `025` and `25` denote
the same position; the padding carries no information at all — it exists only so
labels have equal width.

**The chosen fix is to remove the disagreement, not to win it.** Make the
correct answer the one the model produces anyway. The two alternatives were both
worse:

- *Harden the prompt.* Already measured as failing: `capability_discovery_schema_v1`
  states the rule explicitly, and the model broke it identically twice. More
  emphatic wording is a bet against a measurement.
- *Repair `P25` to `P025` in the resolver.* That is a silent repair, forbidden by
  rule 9, and it would put interpretation into the layer whose whole job is to
  read what was written.

**Three parts.**

*The grammar widens.* `PASSAGE_REF_PATTERN` moves from `^P(\d{3,})$` to
`^P(\d+)$`. Measured on the widening: every label the old grammar accepted is
still accepted, and every one resolves to the same ordinal, because
`int("025") == int("25")`. No historical citation changes meaning, and the
regression set is empty. What stays refused is unchanged — a position outside the
packet, a zero ordinal however spelled, wrong case, missing prefix, non-digits.
The resolver is untouched: it already read digits as a number.

*The rendering style becomes per stage.* `STAGE_PASSAGE_REF_STYLE` maps
`product_extraction` to `P{:03d}` and `capability_extraction` to `P{:d}`;
`passage_ref_label(ordinal, *, stage)` resolves it or refuses with
`passage_ref_label_style_undeclared`. Closed, fail-closed, no default — the
ADR-062 shape, for the same reason.

Not global, and the reason is an artifact rather than a preference:
`product_discovery_schema_v4` says in its own text that the label is "the letter
`P` followed by at least three digits". That prompt is qualified and its digest
is pinned in six product qualification records. Changing the renderer under it
would leave the labels the model sees out of step with the instruction it is
reading — the exact disagreement this ADR exists to remove, reintroduced at the
other end. So the style moves with the prompt it belongs to, and the product
stage keeps both.

*The prompt is superseded, not edited.* `capability_discovery_schema_v2` is v1
with one section changed — how a passage label is described — plus the matching
header example. A test asserts that the only lines differing are those four.
`capability_discovery_schema_v1.md` is untouched, byte for byte, because
`ext-smoke-cap-0001` and `ext-smoke-cap-0002` resolved it and their chains must
stay verifiable; CR-0005 is untouched for the same reason. Registry
`v5 → v6`, the successor takes position one, and v1 is retained below it.

**The two stages now label the same passage differently, and that is accepted.**
A reader comparing a product rendering with a capability rendering of one packet
sees `P001` and `P1` for the same passage. The label is scoped to one rendered
document and resolved against that document's own canonical order, so nothing is
ambiguous; the alternative was reopening a qualified prompt that has no defect.

**A binder-signature change, chosen deliberately.** The stage has to reach
`_bind_passages_with_ids`, which previously took only the packet. Every binder now
takes `(packet, stage)` and most ignore it. The alternative — storing a
pre-parameterized callable per map entry — would have put a per-stage constant
somewhere a new stage could be added by copying, which is precisely the defect
ADR-053, ADR-058, ADR-061 and ADR-062 each found once. A uniform signature means
the stage always comes from the render call that is actually happening.

**`STAGE_CHANGE_REQUEST` moves for the first time.**
`capability_extraction` now cites CR-0006. ADR-062 recorded this as its own known
limitation — the map states which change request is *current*, so it must move
whenever a stage's prompt is superseded — and this is that step happening. The
`product_extraction` entry is untouched.

**What this does not fix, stated plainly.** The same measured output carries a
second, independent defect: two of the eighty resolvable citations quote text
that is not in the passage they cite — one whole passage with the trailing word
of another prepended, the same corpus seam that produced the `ext-smoke-0006`
Sales Hub failure. C8 (ADR-063) refuses exactly that and will refuse it again.
Nothing here weakens C8, and nothing here claims to address that defect. The
next capability run is expected to reach C8 rather than the ref resolver, which
is progress, not success.

**Scope.** One pattern, one closed map, one resolver, one binder-signature
change, one new prompt, one new change request, the registry version, two
additive enum widenings, `STAGE_CHANGE_REQUEST["capability_extraction"]`, the
manifest count, and tests. No schema contract version changes. No existing prompt
bytes change. No governance root, run root or published artifact is touched.

## ADR-065 — A quote is evidence for a claim, not a copy of its container

**Status:** Accepted.

**Where this came from.** The operator proposes regrouping passages on heading
boundaries rather than HTML block boundaries, which would make the average
passage roughly ten times larger. Quote length has never been specified
anywhere, so under that change a quote could grow with its container for no
reason. This ADR states the bound first, independently of whether the regrouping
happens.

**Measured before deciding, not assumed.**

- *In the prompts.* `capability_discovery_schema_v2` mentions `quote` three
  times — "text quoted verbatim from that same passage", "must come from the
  passage that `ref` names", and the field list — and never with a length, a
  sentence count, or any bound. `product_discovery_schema_v4` is the same. The
  word "short" appears in both, but only for `capability` and `ambiguity`.
- *In the schemas.* `evidence.items.quote` is `{"type": "string"}` in both
  `product_observation.schema.json` and `capability_observation.schema.json` —
  exactly the shape `availability_status` had before ADR-052.
- *In real output.* `ext-smoke-0006` (product): 34 quotes, median 204
  characters, longest 590. `ext-smoke-cap-0003` (capability): 84 quotes, median
  96, longest 220, none over 300.

So the capability stage is not currently producing long quotes. This is a bound
stated before the thing that would make it bite, not a repair of an observed
defect, and the ADR says so rather than implying a problem that the measurement
does not show.

**The bound is a prompt instruction and nothing else. That is a decision.**
Adding `maxLength` to the schema was considered and rejected on three grounds,
in increasing order of weight:

1. *It is a released-contract change.* Both observation schemas are
   `additionalProperties: false` released contracts. Narrowing an existing
   property is breaking — a successor contract and a manifest bump, not the
   additive enum widening these prompt increments have been using.
2. *It would retroactively invalidate accepted data.* Eleven human-validated
   product observations are persisted under `decisions-ext-smoke-0006-0002` with
   quotes up to 590 characters. Any cap below that would make records a human
   already accepted fail re-validation — the opposite of what immutability means
   here.
3. *Quote length is not an integrity property.* This is the decisive one, and it
   is the operator's own framing, which the measurement confirms. C6 proves the
   cited pair is a passage of this run; C8 proves the quoted words occur verbatim
   in it. Both hold identically for a 20-character quote and a 2,000-character
   one. A length gate would buy no verifiability and would reject truthful
   evidence for being verbose, with a refusal indistinguishable from real
   corruption. Rule 7 points the other way.

**What that costs, stated rather than implied.** The bound can be ignored and
nothing will notice. A thirty-sentence quote that occurs verbatim in its cited
passage passes every gate this repository has. A test asserts this state of
affairs directly — that `quote` is still an unconstrained string in both schemas
and that no length check exists in `candidates.py` — so that if a gate is ever
added, this decision is revisited rather than silently contradicted.

**A second rule, and why it is not a substitute for C8.** The successor also
tells the model to copy a contiguous run rather than joining text across a gap.
That is aimed at the splice class ADR-063 found twice — the `ext-smoke-0006`
Sales Hub citation and the two `ext-smoke-cap-0002` citations, all of which
reconstructed one source sentence that the corpus had split across two passages.
The instruction is not the fix. C8 is the fix, it stays exactly as strict, and
nothing here weakens it. The instruction only means a model that would otherwise
do it has been told not to.

**Superseded, not edited.** `capability_discovery_schema_v3` is v2 with the
`evidence` section extended and one line added to the silent final check;
a test asserts line by line that each capability supersession changed exactly
one thing. v2, v1 and `capability_extraction.md` keep their bytes — `ext-smoke-cap-0003`
resolved v2, and `ext-smoke-cap-0001`/`-0002` resolved v1. Registry `v6 → v7`.
`STAGE_CHANGE_REQUEST["capability_extraction"]` moves to CR-0007; the
`product_extraction` entry is untouched, and the product prompt is untouched.

**Scope.** One new prompt, one new change request, the registry version, two
additive enum widenings, one closed-map entry, the manifest count, and tests. No
schema contract version changes. No existing prompt bytes change. No normalizer,
snapshot, packet, governance root, run root or published artifact is touched.

## ADR-066 — Passages are sections, not HTML blocks: `sec_html_item_span_v2` (SPEC-006, ADR-031)

**Status:** Accepted.

**The defect.** `sec_html_item_span_v1` splits on HTML block closures. In the
pinned HubSpot 10-K, printed page numbers sit between the two halves of a
sentence, so each became its own passage and divided a sentence across two of
them. Four confirmed cases: pages 8, 9, 12 and 14. The consequence is not
cosmetic — a model that reassembled one of those sentences produced the
`ext-smoke-0006` Sales Hub citation that C8 (ADR-063) refuses, and two more of
the same shape appeared in `ext-smoke-cap-0002`. The corpus was manufacturing
the failure the gate then caught.

**A narrow fix was rejected in favour of a structural one.** A rule of
"digits-only block whose predecessor does not end in a full stop → merge" was
prototyped, reached 124 → 116 passages and caught 4 of 4. The operator proposed
grouping on section boundaries instead, which removes the class rather than the
four instances: an interruption inside a section stays inside one passage
whatever it is.

**The original design was wrong, and measuring it first is why that is known.**
The plan was to split on `</h1>`…`</h6>`. Measured on the raw filing: **zero**
`<hN>` tags in 4,764,421 bytes — not in Item 1, not anywhere. Every section
heading is an ordinary `<p>` whose entire content is inside bold `<span>` runs.
Had this been prototyped on synthetic HTML, the synthetic document would have
had the tags the plan assumed and the prototype would have "passed".

The blocker check is worth recording too: `data/snapshots/**` holds only a
`.gitkeep`, which is where the operator looked. The raw filing is at
`data/raw/sec/CIK0001404655/0000950170-25-018873/hubs-20241231.htm`, gitignored,
and its SHA-256 equals the `content_hash` the snapshot manifest already names.
The verification harness was itself checked before anything was concluded from
it: re-running v1 over that file reproduces all 124 committed passages field for
field.

**The rule, and why equality rather than presence.** A block is a heading when
its whole normalized text equals its bold runs' normalized text. *Presence* of
bold text would match any paragraph containing a bold phrase; equality matches
only a block that is nothing but its bold text. Measured over Item 1: 15
headings — Overview, The HubSpot Approach, Our Competitive Strengths, Our Growth
Strategy, Our Customer Platform, Our Services, Our Customers, Our Technology,
Marketing and Sales, Governmental Regulations, Human Capital Management,
Competition, Intellectual Property, Financial Information About Segments,
Available Information — and zero false positives. The operator and this
repository derived that list independently and got the same fifteen. Note the
count: **15**, not the 13 the proposal named.

The rule is restricted to blocks closing with `</p>`. Measured: allowing every
block type finds the same fifteen, so the restriction costs nothing here and
declines to generalize from one document.

**No heading hierarchy is available, and none is invented.** All 16 bold blocks
carry one identical style signature — 10pt, Times New Roman, bold. There is no
`<hN>` level, no font-size difference, no font-family difference. A nesting rule
would have to be guessed, so the grouping is flat.

**The item title needed no special case, which is the point.** `ITEM I. BUSINESS`
is not a heading under this rule: the anchored span begins *inside* its opening
`<p>` tag, so the block's text carries a leading `>` that its bold runs do not,
and the equality fails. It therefore becomes the record before the first
heading, by the same "a record ends where the next heading begins" rule.
Special-casing it was considered and rejected: with all 16 blocks sharing one
style, nothing in the markup identifies which one is the item title, so a merge
rule would have to hard-code a position or a string — a document-specific
constant, which is the defect class ADR-053, ADR-058, ADR-061 and ADR-062 each
found once.

**Result.** 124 passages → 16. Median 2,293 characters, mean 2,546, max 6,060
(Human Capital Management), min 18 (the item title). All nine page-number blocks
are now interior to a section; the four confirmed splits are gone. Grouping is
concatenation only — every v1 passage's text appears verbatim inside exactly one
v2 section, and the only characters added are the 108 single spaces joining
them, asserted by test.

An unplanned measured benefit: the rendered provider document *shrinks*, from
66,251 to 50,476 characters, because 108 per-passage headers disappear.
Estimated input tokens fall from 23,070 to about 17,580 — 35% of the ceiling
rather than 46%.

**Successor, not edit.** `normalize_span_v2` and `build_passages_v2` sit beside
the released functions and reuse `normalize_span` for block boundaries and text,
so the two normalizers cannot disagree about where a block ends. A mode flag was
rejected: a parameter with a default is how a released behaviour gets changed by
accident, and v1 produced the passages behind Snapshot A and every chain citing
them. `srcsnap-hubspot-fy2024-sec-v1` is untouched; the new corpus is
`srcsnap-hubspot-fy2024-sec-v2`, and a test asserts v1 still reproduces its
committed snapshot byte for byte.

**Known limitation, recorded rather than implied.**
`schemas/ingestion_preflight_manifest.schema.json` pins
`"normalizer_version": {"const": "sec_html_item_span_v1"}` — the same
const-written-when-one-existed shape as ADR-053 and ADR-062. Nothing in this
increment writes a preflight manifest, so nothing is blocked today, but a v2
ingestion preflight cannot validate until that const becomes an enum. Left
untouched here because no artifact this increment produces needs it, and
widening a schema nobody is exercising is a change without a caller.

**Not claimed.** This removes the corpus's contribution to the splice class. It
does not remove the class: a model can still assemble a quote from two
non-adjacent runs *within* one large passage, and C8 remains the thing that
catches it. C8 is unchanged and is not weakened by anything here.

**Scope.** One module gains two functions and two constants; no existing
function changes. One new snapshot root and one new packet, both write-once. No
schema change, no released contract change, no existing snapshot, run root,
governance root or published artifact touched.

## ADR-067 — The output ceiling is a contract, not a dial: `extraction_provider_client_contract@0.3.0`

**Status:** Accepted.

**Why the ceiling moves.** Four capability runs have now been refused, and the
last one was refused for a reason none of the fixes addressed. `ext-smoke-cap-0004`
(round `-0005`) cleared every defect it was built to clear: 71 citations with
zero malformed labels, zero C8 violations, and the one-to-three-sentence rule
observed at 70 one-sentence quotes and one two-sentence quote. It was cut off at
`finishReason: MAX_TOKENS` after 68 observations. Input had collapsed to 11,216
tokens — 22% of its ceiling — while output sat exactly on 8192.

Measured cause: quotes over section-scoped passages are longer, because the
sentences in those sections are longer. Cost per observation moved from ~97
output tokens (`ext-smoke-cap-0001`, which finished with `STOP`) to ~120. Nothing
was wrong; the budget was simply the wrong size for the corpus.

**The instruction that produced this ADR was based on a false premise, and
saying so is the point.** The round was specified with `max_output_tokens` as an
operator value, alongside the budget ceilings. It is not. It is
`MODEL_PARAMETERS["max_output_tokens"]`, a module constant in
`providers/client_contract.py`, and there is no injection point: neither
`VertexGeminiProviderV2.__init__` nor `run_extraction_stage_v2` accepts a client
contract. Editing it is a source change, which means:

- the worktree stops equalling HEAD, so R7b would record `code_commit` for a
  commit whose code did not run — and the runbook's triple equality compares
  `git rev-parse HEAD` only, so **nothing would catch it**;
- the bytes of a released contract change without its label changing.

The round was therefore stopped before R7 rather than run with a false
provenance record. Making this a run-time parameter is a separate design
decision — it would move a governed execution field out of the contract and into
a caller's hands, which is the opposite of what `provider_client_contract_sha256`
exists to pin — and it is deliberately not made here.

**The identity moves with the content.** `@0.2.0` → `@0.3.0`. The digest alone
would have caught the difference — `validate_qualification_execution_contract`
compares the recorded `execution_contract_sha256` with the live one — but this
project has bumped the label every time a pinned thing's content changed, for
prompts, for change requests, for decision sets. Two different byte sequences do
not share one label.

That has a measured consequence worth stating plainly: **existing governance
roots can no longer authorize a new run.** All eleven roots recorded the old
identity and digest, so a run against any of them now refuses with
`governance_record_not_effective`. That is not breakage — it is
"execution-affecting contract changes never inherit enablement" doing exactly
what it says. Their own records are unaltered and remain readable; a new round
mints the new identity.

**The v1 contract is not touched, and that took a design change.**
`MODEL_PARAMETERS` was shared: raising it in place would have changed the bytes
of `extraction_provider_client_contract@0.1.0` too, leaving two documents under
one released label — the same defect the version bump above exists to prevent,
one contract lower. `client_contract_v2.py`'s own docstring already claims
`@0.1.0` is "byte-identical and untouched", and that claim stays true.

So the successor owns its parameters: `MODEL_PARAMETERS_V2` is the v1 mapping
with one field replaced, the v1 route stays frozen at 8192, and
`vertex_gemini_v2` sends what the v2 contract declares. A test asserts the two
differ in exactly that one field and nowhere else. Un-sharing also removed two
of the six test rebaselines predicted before implementation: the two that pin
8192 are v1-path tests, and they now pass unmodified, correctly asserting that
the retired route is frozen.

**The product stage is affected, and it is harmless.** The v1 live route is
retired; both stages run through v2, so `product_extraction` gets the raised
ceiling too. A ceiling only permits — no existing behaviour changes, and no
product run has ever approached 8192.

**The schema is a successor file, not an edit.**
`extraction_provider_client_contract_v3.schema.json` sits beside the v2 document,
which keeps its `@0.2.0` and `0.2.0` consts byte-identical, following the
`extraction_validation_decision_set_v2` precedent. The registry gains one entry;
`manifest_version` moves 0.18.0 → 0.19.0, 48 → 49.

**The cost ceiling does not move, and that is measured rather than assumed.**
The round proposed 2,000,000 → 4,000,000 micros. Measured: at 16384 the reserve
for this run is 44,325 micros — one forty-fifth of the *existing* ceiling. The
reserve is linear in the output cap, so doubling it adds 20,480 micros, not a
factor. 2,000,000 stands.

**Not claimed.** This does not establish that the run will now complete. It
raises the ceiling that stopped the last one; whether 16384 is enough, and
whether the 68-of-71 concentration on one section is the corpus's real shape or
something else, are questions the next live call answers.

**Scope.** One new constant, one contract identity, one schema-version const,
one successor schema file, one registry entry, one manifest-count guard, and
test rebaselines. `client_contract.py` is untouched. No prompt, no corpus, no
snapshot, no governance root, no run root and no published artifact changes.

## ADR-068 — The third observation kind: `task`, one product at a time (E-T1)

**Status:** Accepted.

**Why now.** Product and capability recall have both proven the same shape:
render a placeholder-free prompt over governed parent context, gate the
model's output at the collection level (C1-C8), and hand the accepted
candidates to a human decision set. Task discovery is next in the dependency
chain -- a task is performed through a capability, which belongs to a product
-- and the thing it was waiting for now exists: Snapshot B is persisted and
reconciled by the packet builder, exactly as Snapshot A was the trigger for
ADR-058.

**`task` joins `product` and `capability` in `OBSERVATION_KINDS`, in
dependency order.** `candidates.derive_identity_fields` and
`assert_candidate_conformance` gain a third branch. The task identity is keyed
on its product, not on the capabilities it cites:
`task_observation_id = f"{product_observation_id}:{slug(task)}"`.
Deliberately not capability-keyed --
`capability_observation_ids` is an array, so an id derived from it would
depend on how many capabilities were cited and in what order, and two records
naming the same task through a different capability count would collide or
not depending on list ordering rather than on what the task actually is. The
collision scope falls out of the same formula that already governs capability
identity: two products may host the same task without colliding, because the
id begins with its own parent's.

**C9 and C10, the capability-side counterpart to C7.** C7 already proves a
capability's `product_observation_id` names a human-admitted Snapshot A
member; the task stage runs C7 against its own product for the same reason.
C9 is one level on: it proves every id in `capability_observation_ids` names a
human-admitted Snapshot B member (`candidate_conformance_capability_not_in_
snapshot`), and — because an empty list is schema-valid and a task is
performed *through* a capability — a task citing zero of them is refused here
too, not silently accepted as a task with no evidence for how it is
accomplished. C10 (`candidate_conformance_capability_parent_mismatch`) refuses
a cited capability that belongs to a *different* product than the task's own.
It is structurally unreachable today -- task discovery renders one product's
capabilities per call, so the model is never shown a second product's `C0N`
and cannot name one -- and is written anyway. "Impossible by construction" is
the assumption ADR-053, ADR-058, ADR-061, ADR-062 and ADR-064 each watched go
false when the construction changed later; C10 costs one set comparison and is
cheap insurance against the same thing happening here.

**The task schema moves to a `@0.2.0` successor for one field, and the
collection contract that wraps it gains a gap it was missing.**
`task_observation.schema.json` (`@0.1.0`, released) has no slug field at all,
so C3 -- the check that a name can be slugged into a stable identity, the same
check every other kind runs -- had nothing to read. `task_observation_v2.
schema.json` adds exactly one property, `normalized_task`, required; every
other property, and the schema's own `additionalProperties: false` shape, is
unchanged. The candidate-collection layer (`candidates._SCHEMA_FOR_KIND`)
validates task candidates against the successor. Measured separately, by the
first end-to-end attempt to materialize one:
`extraction_candidate_collection@0.1.0`'s own `observation_kind` enum was
still closed to `["product", "capability"]`, in both places it appears -- the
collection's own field and each entry's copy -- and refused every task
collection with `'task' is not one of ['product', 'capability']`, after every
resolver and every C-check below had already passed. Both enums widen
additively; nothing else in the schema changes.

**The renderer's third stage, and the one structural difference from the
other two.** `task_extraction` joins `MATERIALIZATION_SUPPORTED_STAGES`. Task
discovery runs **per product**, not once over the whole validated set the way
product and capability discovery do: `task_discovery_recall`'s own template is
`{{company}}`/`{{cutoff}}`/`{{product}}`/`{{capabilities}}` -- singular
`product`, not the capability stage's `{{validated_products}}` plural. That is
a deliberate decision, not an accident of the existing prompt: rendering every
product's capabilities into one call would repeat the exact failure ADR-063
and ADR-065 measured on the capability stage, where 68 of 71 citations from an
eleven-product run landed in a single section. Nine products means nine
separate render/materialize calls for a HubSpot-shaped chain, not one.

That makes the focal product a required, caller-supplied input rather than
something the packet or the renderer can infer -- a packet carries every
validated product, and picking one would be a guess about which call this is.
`render_provider_contents` gains a keyword-only `focal_product_observation_id`
parameter; omitting it on a task render fails closed with
`focal_product_required`, a new reason code, rather than silently rendering
the first product or every product at once.

**Two label families, one of them reused rather than invented.** `P0N` is the
passage label every stage already shares, resolved through the same
`canonical_passage_order` all three stages call — no second sorter. `C0N` is
new: a capability's `capability_observation_id` runs 46-111 characters on the
pilot data (worse than the 44-character `product_observation_id` ADR-060
replaced with `A0N`), so the model is shown a short position label instead.
The evidence block is folded into `{{capabilities}}` rather than bound
separately, because measured, `task_discovery_recall` carries no
`{{passages}}` marker at all — evidence is part of what a capability *is* at
this stage, exactly as the capability stage's own evidence lives inside each
product-scoped section.

**`C0N` is unpadded, on the ADR-064 measurement applied before it could
repeat rather than after.** ADR-064 found the capability stage's `P0N`
padding defect on two independent live turns -- shown `P025`, the model wrote
`P25`, identically both times. A padded `C0N` would carry the identical risk:
every product's capability count in the persisted HubSpot chain passes
through the single-digit range that failure lived in -- Content Hub alone has
thirteen -- so every one of the nine task-discovery calls this chain supports
would have carried it, not an occasional one. `capability_ref_label` emits
`f"C{ordinal}"` and `CAPABILITY_REF_PATTERN` is `^C(\d+)$`, the same widening
ADR-064 made for `P0N`: an already-resolved `"C01"` still parses (`int("01")
== int("1")`), but the label this module emits is always unpadded.

**`resolve_capability_refs`, the fourth label family resolved the same way as
the first three.** The model writes `capability_refs: ["C1", "C3"]`;
`resolve_capability_refs` turns that into `capability_observation_ids`,
resolved against `focal_capability_order` -- the same function
`_bind_capabilities` uses to assign the labels in the first place, exported
from `contents_renderer` rather than re-derived, on the same "no second
sorter" discipline `canonical_passage_order` already keeps for `P0N`. A label
naming a position the model was not shown is refused with its own reason code,
`candidate_conformance_capability_ref_unresolvable`, distinct from C9 -- which
judges the *resolved* id against Snapshot B -- exactly as `_REF_UNRESOLVABLE`
is kept distinct from C6.

**The focal product is injected, never requested.** The prompt asks for no
product label at all, unlike the capability stage's `parent_ref`: task
discovery renders one product per call, so the pipeline already knows
`product_observation_id` before the call is made and does not need to trust a
label for it. `materialize_candidate_collection` gains the same keyword-only
`focal_product_observation_id` parameter the renderer already required, fails
closed with the same `focal_product_required` reason code before parsing the
model's output at all if the kind is `task` and the parameter is absent, and
an internal `_inject_focal_product` step sets `product_observation_id`
unconditionally on every task observation -- not a resolution of something the
model wrote, a value supplied outright, the same way `derive_identity_fields`
already supplies `task_observation_id` and `normalized_task`.

**Two defects an adversarial review found and fixed before any of this was
committed, reproduced by running the code rather than reading it.** Both
turned a corrupted input into something that looked like an ordinary bad model
answer. A capability parent with no identity resolved to `None`:
`_parent_observation_ids` has always required an `A0N` parent's
`observation_id` to be a non-blank string; its structural analogue for `C0N`
did not. Reproduced: a `capability_parents` member missing `observation_id`
produced `capability_observation_ids: [null]`, which then failed the released
schema and was recorded as `schema_invalid` -- a corrupted packet reported as
a bad candidate. The second consumer was worse: `_capability_observation_ids`
coerced the missing id with `str`, making the literal string `"None"` a valid
key in the universe C9 and C10 judge against, so C9 would have admitted a task
citing nothing at all.

Fixed at both, and the choice of *where* is the point. `focal_capability_order`
is the single source both consumers read -- the renderer assigning `C0N` and
`resolve_capability_refs` resolving it -- so the check belongs there, for the
same reason `canonical_passage_order` owns the passage order; it keeps that
module's own `contents_context_invalid`, beside its three sibling raises, the
same shape `resolve_evidence_refs` already uses when it surfaces
`canonical_passage_order`'s code into a candidates path. `_capability_
observation_ids` gets its own check as well, not a duplicate: it reads **all**
capability parents, not only the focal product's, and it validates
`product_observation_id` too, because C10 compares against that field and a
missing one was being compared as though `"None"` were real. The new reason
code, `candidate_conformance_capability_context_malformed`, is kept apart from
C9 on purpose: "the model cited a capability nobody validated" is a statement
about the *answer*; "this run's capability context is corrupt" is a statement
about the *question*. An operator chasing the first would never find the
second -- ADR-055's rule, applied one level up, to the input rather than the
output. The two pre-existing `_C9` raises inside `_capability_observation_ids`
were moved onto it as well: they described context corruption while carrying
a model-fault code.

**C11 -- one capability, cited once.** `["C1", "C01"]` is two labels and one
capability; resolved, it produced the same id twice. `task_observation_v2`
declares no `uniqueItems` and C9 asks only about membership, so a reader
counting `len(capability_observation_ids)` would have been told a task rests
on two capabilities when it rests on one. `candidate_conformance_capability_
cited_twice` refuses it. Two decisions inside that: the check runs on the
**resolved ids**, because the defect is invisible in the labels -- `C1` and
`C01` are different strings for one position -- and it refuses rather than
deduplicating, on the same two standing rules as everything above: no silent
repair, unknown over guess. It is numbered in sequence with C1-C10 because it
is the same kind of thing they are: a conformance rule over a materialized
candidate.

**Not claimed.** This ADR makes the task stage materializable: it can render
one product's capabilities, resolve what a model cites back to real
identities, and gate the result at the collection level. It does not qualify
`task_discovery_recall` or any prompt to run against a live model -- that
prompt states no output contract a model could conform to, and is left
unqualified on purpose. Wiring the stage so a live run could actually reach it
is a separate decision, deferred to ADR-069. No provider was contacted at any
point in this work; the two silent-failure findings above were demonstrated
offline, against synthetic packets built to be malformed on purpose -- the
only way they could surface at all, since the real Snapshot B carries no
malformed member.

**Scope.** `OBSERVATION_KINDS`, three new conformance checks (C9, C10, C11)
and one new reason code for a corrupted capability context
(`candidate_conformance_capability_context_malformed`), one new schema
successor file (`task_observation_v2`), one additive schema-enum widening
(`extraction_candidate_collection`, in both places `observation_kind`
appears), one renderer stage, one new renderer parameter and one
identically-named candidate-pipeline parameter (`focal_product_observation_id`,
threaded through `materialize_candidate_collection`), one new resolver
(`resolve_capability_refs`) and its own reason code
(`candidate_conformance_capability_ref_unresolvable`), unpadded `C0N` labels
from this stage's first version, and test coverage including an offline
render over the real, persisted HubSpot capability chain. `STAGE_OBSERVATION_
KIND`, `STAGE_CHANGE_REQUEST`, and any live-callable prompt for this stage are
deliberately untouched.

## ADR-069 — Making the task stage runnable (E-T1 governance wiring)

**Status:** Accepted.

**The kind existing does not make the stage runnable, and that gap is closed
now.** ADR-068 added `task` to `OBSERVATION_KINDS` and made the renderer and
the candidate pipeline materialize the stage, but deliberately withheld two
entries: `STAGE_OBSERVATION_KIND["task_extraction"]` and `STAGE_CHANGE_
REQUEST["task_extraction"]`. Adding either before a qualified prompt existed
would have made a live task run reachable through `task_discovery_recall`,
which -- measured against `task_observation_v2.schema.json`'s eleven required
fields -- names only three of them and instructs the model to emit "product
and capability IDs" directly. That is the exact defect CR-0005 closed for the
capability stage, reopened here because this prompt predates the `C0N`/`P0N`
reference design entirely. `task_discovery_schema_v1` (CR-0008) closes it, so
both entries are added in this round, together, and only once the successor
prompt exists to be qualified against.

`task_discovery_schema_v1` states the output contract explicitly: capabilities
by the unpadded `C0N` label ADR-068 renders, passages by the unpadded `P0N`
every stage shares, the capability stage's own S1-S8 status vocabulary rather
than a second one, and an evidence quote bounded to one to three sentences
from this prompt's first version -- ADR-065's rule, not repeated after a
predecessor shipped without it. The prompt registry moves `v7` -> `v8`.

A sentence in that prompt was wrong, found by the same review that closed
ADR-068's two findings, before this round was committed. The "do not emit an
identifier" section said the first three of four derived fields come "from
this call's product and your `capability_refs`", which mixes them:
`task_observation_id` never derives from `capability_refs`, and `capability_
observation_ids` never derives from the product. The imperative was correct;
only the reason given for it was not. Each field now names its own source.
That edit changed the prompt's bytes, from `fd0bb375c05d8ad72fed09a1342
b414f79adc0040f9682f82a62e120b9c74b7a` (9,371) to `1f484896a4e51935d45e5c8
c4c575e48da1ed191305c066cb55f69255ea445c0` (9,524), and the rule that a frozen
prompt is superseded rather than edited did not apply: verified, this file
appears in **no** governance root and has been resolved against no
qualification record -- zero matches under `artifacts/`. Editing in place was
therefore safe, and it stops being safe the moment the first task
qualification cites it. CR-0008's scope note was updated to the new digest and
byte count, and a test asserts that agreement against the file's actual bytes
rather than a literal, so the value is not kept in two places.

**The stage-output contract identity moves to what the stage has already
validated against since ADR-068.** `STAGE_OUTPUT_CONTRACT_ID["task_
extraction"]` and `STAGE_OUTPUT_SCHEMA["task_extraction"]` move from
`task_observation@0.1.0` / `task_observation.schema.json` to `task_
observation@0.2.0` / `task_observation_v2.schema.json`. This was a live
inconsistency between two layers, not a new decision: `candidates._SCHEMA_
FOR_KIND` has read the `@0.2.0` file since ADR-068, while the governance layer
that mints prompt qualifications and run manifests still named the schema it
superseded. Left alone, a task run would have qualified against one contract
identity while validating against a different schema than the one that
identity names.

**The task stage reuses the ADR-052 vocabulary artifact rather than minting a
second one, and that makes it a third consumer of an artifact whose own name
now undersells it.** `availability_status` is `{"type": "string"}` in
`task_observation_v2.schema.json`, exactly as unconstrained as it is in the
product and capability schemas, so `product_candidate_availability_
vocabulary@0.1.0` -- the same eight tokens, the same `status_label_table()` --
governs all three. `VOCABULARY_BOUND_PROMPT_IDS` gains `task_discovery_
schema_v1` on that basis, no code change required: C5 reads `admitted_status_
values` from the artifact without asking which kind is being judged. Minting a
task-specific vocabulary was rejected on the same measurement ADR-059 already
made for capability -- the eight tokens are identical, and a second copy would
be the exact defect class ADR-053 exists to prevent, one artifact lower.
Measured on the real chain: every one of 69 accepted capabilities and all 11
accepted products carry `general_availability`, so task recall inherits that
same narrow band until a richer source diversifies it.

The artifact's own identity, `product_candidate_availability_vocabulary`, was
already a slight misnomer with two consumers; a third makes the name actively
misleading to a reader who has not traced `VOCABULARY_BOUND_PROMPT_IDS`. A
stage-agnostic rename is a real fix and is deliberately **not** made here: it
is a released-contract identity change, wider in scope than this round, and
the loader validates the artifact against its own recorded constant rather
than against the stage that is running, so nothing is functionally broken by
leaving it. Recorded as a known limitation to correct in its own increment,
not silently carried forward again.

**`prompt_qualification_record@0.1.0`'s two enums grow additively, the same
move ADR-053, ADR-059, ADR-064 and ADR-065 each made.** `extraction_prompt_
registry_v8` and `task_discovery_schema_v1` are added to the `prompt_
registry_version` and `prompt_id` enums in `prompt_qualification_record.
schema.json`. The schema's own identity and required-property set are
untouched; only the closed vocabularies each enum declares widen.

**Not claimed.** No live call has been made against `task_discovery_schema_v1`
-- it carries `no_completed_evaluation_run` and `no_baseline_comparison` as
known limitations, the same as every bootstrap-basis prompt before it. What
this ADR establishes is that a task run through the ordinary runner is now
reachable through governance and stopped, correctly, at
`focal_product_required` (asserted end to end in
`test_v2_a_fully_valid_non_product_stage_still_refuses_before_the_provider`)
-- not that the prompt elicits conforming output from a model.

**Scope.** One new prompt (`task_discovery_schema_v1`, CR-0008), two
governance map entries, one stage-output contract identity move, and one
additive schema-enum widening (`prompt_qualification_record`'s two, for the
registry version and the prompt id), and test coverage including the
governance-reachability path end to end. No product or capability prompt,
schema, change request, or qualification record changes. No live call is made
or authorized by this round.

## ADR-070 — The runner carries the focal product

**Status:** Accepted.

**What was missing.** ADR-068 gave the renderer a `focal_product_observation_id`
and ADR-069 qualified the task prompt, but neither touched
`run_extraction.py`. So the parameter existed at both ends of the pipeline —
`render_provider_contents` and `materialize_candidate_collection` — and nowhere
in the runner between them. No caller could supply one, and a task run was
refused at the render gate with `focal_product_required`.

**Not a defect, and worth saying why.** Each round's authorized scope excluded
the runner: E-T1 was "renderer binding, the new conformance checks, tests", and
the governance wiring round was the stage maps, the prompt and its change
request. The gap was measured and reported at the time, and the test that
covers it — `test_v2_a_fully_valid_non_product_stage_still_refuses_before_the_provider`
— was rebaselined to `focal_product_required` precisely because that was the new
truth. The gate was doing its job on a stage that was not finished yet.

It surfaced where a gap like this should: setting up the first live task call.
Nothing was spent finding it — the refusal happens at F1, before the count send.

**The change is one parameter, threaded twice.** `run_extraction_stage_v2` takes
`focal_product_observation_id`, passes it to `_run_two_operation_stage`, which
passes it to `render_provider_contents`; and the public entry point passes it to
`materialize_candidate_collection` on the publication path. Both were verified
by mutation: dropping either hand-off turns two tests red.

`_run_authorized_stage` is deliberately left alone. Its render call is on the v1
provider route, which ADR-045 retired — the code above it raises
`v1_live_route_retired` before reaching it, and the module says so in a comment
at that call. Threading a parameter through unreachable code would suggest it
matters there.

**Optional, and the refusal keeps one owner.** The product and capability stages
have no focal product; passing one changes nothing for them, asserted by running
each stage both ways and requiring identical outcomes. Omitting it on the task
stage still fails closed — but the runner does not re-check that. The rule lives
in `_require_focal` inside the renderer, and a second copy in the runner would
be the two-owners problem `canonical_passage_order` exists to avoid.

**What this does not do.** It makes a task run *reachable*; it does not make one
correct. No live call is authorized by this round, and the governance chain
minted for the first attempt goes stale the moment this lands — `code_commit`
pins the commit before it, so a new attempt root is needed, exactly as the
capability rounds needed one twice.

**Scope.** One optional parameter, two hand-offs, one docstring correction, four
tests. No schema, prompt, change request, governance record, run root or
published artifact changes.

## ADR-071 — The decision set carries three kinds and both snapshots

**Status:** Accepted.

**Where it was found.** Setting up the first task G6-D — the human accept/reject
pass over the two candidates the `ext-smoke-task-0001` run produced. The run
itself succeeded; the artifact that records the judgement could not be built.

**The defect.** `build_validation_decision_set` decides which parent snapshot a
decision set must pin with a two-way branch:

```text
if observation_kind == "capability":  Snapshot A is required
elif snapshot_a is not None:          "a product decision set must not pin Snapshot A"
```

It was written when only `product` and `capability` could reach a decision set,
and it is exactly correct for those two. A task decision set is judged against
**Snapshot B** — the accepted capability parents, which is what C9/C10/C11 check
membership against. It fell into the `elif`, was named a product in the error
message, and there was no `snapshot_b_reference` field for it to pin anyway.
Both released schemas enumerate `["product", "capability"]`, so a task decision
set was not merely unvalidated under `@0.1.0`/`@0.2.0` — it was unrepresentable.

**This is the sixth instance of one class.** ADR-053 (a registry const pinned to
one version), ADR-058 (a guard that only ever saw one stage), ADR-061 (an
`observation_kind` default), ADR-062 (a change-request reference) and ADR-064 (a
per-stage label style) are the same defect: *a constant or branch written when
only one stage or kind existed, silently wrong the moment a second appeared* —
the group ADR-068 already named as "the assumption ADR-053, ADR-058, ADR-061,
ADR-062 and ADR-064 each watched go false".

ADR-068, ADR-069 and ADR-070 are deliberately **not** in that list, though all
three are recent and all three touched the task kind:

- **ADR-068** added new conformance checks (C9/C10/C11) for a kind that had none.
  Adding a check is not repairing a branch that silently absorbed something.
- **ADR-069** wired governance for the task stage — stage maps, the prompt, its
  change request. New wiring, not a wrong arm.
- **ADR-070** was a different failure shape: a parameter that existed at both
  ends of a pipeline and nowhere between them. It fails *loudly*, at the render
  gate, before anything is spent — the opposite of a value quietly taking a
  neighbour's path.

Counting them would make the class mean "anything the task kind touched", which
is not a class one can watch for.

The fix pattern is the class's, and it is what this ADR applies rather than
patching the branch:

- `SNAPSHOT_AXIS_BY_KIND` — a closed map, `product → none`, `capability → a`,
  `task → b`, checked by test to be exhaustive over `OBSERVATION_KINDS`.
- `_snapshot_axis_for` — a fail-closed resolver with its own reason code,
  `decision_set_snapshot_rule_missing`. A fourth kind added without a decision
  about its parent snapshot is refused, not absorbed by a neighbouring arm.
- No `else`. The rule is data with one owner; every builder reads it.

**The successor, and where the branch lives.** `@0.3.0` adds the `task` kind and
`snapshot_b_reference` / `snapshot_b_sha256`, with the three-way conditional in
the schema as well as in code — capability pins A and not B, product pins
neither, task pins B and not A. A task cites Snapshot A only transitively,
through Snapshot B, so pinning both would record a redundant edge that could
disagree with itself.

`build_validation_decision_set_v3` delegates to `_v2`, which delegates to the
released builder, so the chain has one definition of what a decision *is*: the
counts, the artifact pins, the accepted-artifact requirement, who decided and
when are all computed once. **The snapshot rule could not have been fixed in the
successor alone** — it lives in the base builder, and a wrapper that re-stated it
would give the rule two owners, which is the failure mode `canonical_passage_order`
and `focal_capability_order` exist to prevent. So the base builder's branch is
what changed, and the successor adds exactly the two fields it introduces, in the
same shape ADR-057 used to add `decided_by`/`decided_at`.

**Released contracts are untouched.** `@0.1.0` and `@0.2.0` are byte-identical,
still enumerate two kinds, and still emit the same key set — asserted directly.
The base builder gained one optional `target_contract` parameter that decides
*only* which kinds are admissible; it defaults to the released contract, so a
call that does not pass it behaves exactly as before. Building a task decision
set under either released contract is refused with `observation_kind_invalid`
rather than emitted in a shape no schema accepts. All three contracts are
mutually closed: no loader accepts another's declared contract.

**Reason codes.** One per snapshot axis: the A-axis keeps the released
`capability_decision_snapshot_a_mismatch` with both of its messages unchanged, so
no existing caller's error contract moves; the B-axis gets
`task_decision_snapshot_b_mismatch`. The product message is now rendered from the
kind rather than hard-coded, which is what made it a lie for `task`.

**Scope.** One new schema, one manifest entry (`0.20.0` → `0.21.0`, 50 → 51), one
new contract constant, two closed maps, one resolver, one successor builder, 20
tests. No prompt, change request, governance record, run root or published
artifact changes. No live call. The two task candidates remain undecided until a
separate authorized round writes the decision set.

## ADR-072 — Page-number blocks are dropped, not concatenated: `sec_html_item_span_v3` (SPEC-006, ADR-066)

**Status:** Accepted.

**What ADR-066 fixed, and what it left.** Under `sec_html_item_span_v1` a printed
page number became its own passage, and where one sat between the two halves of a
sentence it split that sentence across two passages. Section grouping made every
page number *interior* to a section, so no sentence is divided any more. That was
the whole claim, and it holds.

But interior is not absent. Grouping is concatenation, so joining `…include:
email`, `9` and `templates and tracking…` produces `…include: email 9
templates…`. The corpus stopped splitting sentences and started corrupting them.

**Measured cost, not a hypothetical.** That one string — Sales Hub's `Features
include: email 9 templates and tracking` — is in **22** evidence quotes that have
already been written: 11 accepted capability observations, 10 accepted task
observations, and 1 candidate in the v2 product measurement run. C8 (ADR-063) did
not catch it and should not have: the quote *is* verbatim in its passage. The
defect is in the passage.

Nine page-number blocks exist in the pinned document's Item 1 — 7 through 15.
Four of them land mid-sentence and are visible as contamination; five fall after
a full stop and are silent. All nine are noise.

**The rejected alternative.** Reducing the passage count — the 124 → 116 shape
ADR-066 prototyped, or any other regrouping — was simulated and does not help.
Whatever the grouping, the same concatenation puts the same digit between the
same two words. The only thing that removes the digit is removing the block.

**The discriminator is structural, not a digit hunt.** A block is a page-number
block when its *entire* normalized text is a bare number (`^\d[\d,]*$`), and it
closes with `</p>`. Measured over the 124 blocks: 9 matches, all page numbers,
**zero** false positives. The 18 blocks that do carry figures — "between 2 and
2,000 employees", "247,939 Customers in more than 135 countries", "20 issued U.S.
Patents" — match nothing, because a statistic is always part of a sentence and
therefore never the whole of its block. A regex looking for digits *inside* prose
could not tell a page number from a headcount; this never has to.

The `</p>` restriction is `is_heading_block`'s, for its reason: all nine already
close that way, so it costs nothing here and declines to generalize from one
document.

**ADR-066's own rule was re-measured, and it was answering a different question.**
That ADR reported a "digits-only block whose predecessor does not end in a full
stop" test catching "4 of 4". Re-run over all nine, it fires on 4. It was never
separating page numbers from data — it was already gated on digits-only, so data
was never in scope. It separated the *sentence-splitting* page numbers from the
ones that fall on a sentence boundary. Under v1 that mattered, because the remedy
was merging two passages and a needless merge would have moved a `passage_id`.
Under section grouping all nine are interior and all nine are equally noise, so
the successor treats them alike and the predecessor test is not carried forward.

**The invariant is widened, deliberately and visibly.** ADR-066 could promise:

> every v1 passage's text appears verbatim inside exactly one v2 section, and the
> only characters added are the 108 single spaces joining them

No rule that removes anything can keep that sentence. Rather than quietly drop
the promise, it is replaced by one that is still checkable:

> every v1 block's text either appears verbatim inside exactly one v3 section
> **or** is listed in the ledger's `dropped_blocks` with its offsets and its
> text; the only characters added are the joining spaces; nothing inside a
> surviving block is rewritten

Two things make that honest. First, the deletion is **whole-block and never
intra-block**: `email 9 templates` becomes `email templates` because a block
vanished, not because a sentence was edited. The one thing a reader must be able
to trust about a passage — that its words are the document's words — still holds.
Second, `build_passages_v3` writes `dropped_blocks` into the ledger: nine
records, each carrying the removed block's `start_offset`, `end_offset` and exact
text. A removal that is counted and named is not the silent repair rule 9
forbids; an uncounted one would be.

**Section spans are v2's, unchanged (the `Our Customers` decision).** Eight of the
nine page numbers are interior blocks, so dropping them cannot move a span. The
ninth is the *last* block of section 7, `Our Customers`, and there the operator
chose to keep `end_offset` where v2 put it rather than pull it back to the last
surviving block. The reason is that the ledger already declares offsets to
address raw bytes while `text_hash` covers normalized text, and that the two are
not a byte-identical slice — tags and collapsed whitespace are dropped inside
every span already. Keeping the spans makes all 16 v3 offsets equal to v2's, so a
diff between the corpora is exactly the set of sections whose *text* changed. The
alternative would have made one section behave unlike the other fifteen.

**Result.** 16 sections, offsets identical to v2. Eight sections change text,
`text_hash` and `passage_id`; eight are unchanged in all three. 40,739 → 40,715
characters: fifteen digits plus the nine joins that no longer run. `Features
include: email 9 templates` is gone and `Features include: email templates`
appears exactly once. The new corpus is `srcsnap-hubspot-fy2024-sec-v3`.

**Successor, not edit.** `normalize_span_v3` and `build_passages_v3` sit beside
v1's and v2's and reuse `normalize_span` for block boundaries and
`is_heading_block` for section starts, so the three normalizers cannot disagree
about where a block ends or which block opens a section. A mode flag was rejected
for ADR-066's reason, which is stronger now than it was then: v1 produced the
passages behind Snapshot A, and **v2 produced Snapshot B, the 69 accepted
capability observations and every task run that cites them**. Both are asserted
field-for-field against their committed snapshots, v2 for the first time here.

**Generalization is explicitly not claimed.** This rule has been measured on one
filing. Before it is applied to another firm it needs one more condition: that
the matched blocks form a **monotonically increasing sequence in document order**,
as printed page numbers do. Without it, a filing whose tables put a bare figure in
its own `</p>` would lose a real number. The nine blocks here do satisfy that
condition — the ledger's offsets are already sorted and the values run 7, 8, 9 …
15 — but the check is not enforced, because enforcing it on a document that
cannot fail it proves nothing. It belongs to the round that first runs this on a
second company, and until then this normalizer is a HubSpot-measured rule.

**Out of scope, and named rather than implied.**

- The 21 already-written contaminated observations (11 capability, 10 task) are
  **not** re-run or corrected here. Fixing the corpus does not retroactively clean
  artifacts derived from the old one, and whether to re-run them is a separate
  decision with its own cost.
- `schemas/ingestion_preflight_manifest.schema.json` still pins
  `"normalizer_version": {"const": "sec_html_item_span_v1"}`. ADR-066 left it
  because nothing writes a preflight manifest; that is still true, so it is still
  left. Worth noting that there are now *three* versions behind that const.

**Scope.** One constant, one predicate, two successor functions, one ledger field,
11 tests, one new snapshot corpus. No schema, prompt, change request, governance
record or decision set changes. No provider call.

## ADR-073 — Consolidation is a stage, not a second pass (SPEC-008, CR-0009)

**Status:** Accepted.

**The gap.** `SPEC-008` defines a consolidation pass and
`product_consolidation_precision` has been registered since the first prompt
registry. It has never run, and measurement shows it could not:

- **No code path reaches it.** All three consumers of `single_pass_prompt_plan`
  take `sequence[0]` and none accepts a prompt selection. That function's
  docstring records executing position one as an explicit ADR-036 decision, not
  incidental indexing.
- **No input mechanism.** Zero `{{...}}` placeholders, and no binder or packet
  field could have supplied candidates even if one existed.
- **No output contract.** It asks for "retained product observations, alias
  links, family links, exclusions with reasons, and unresolved cases" and names
  no field, no type, no shape.

The third is the defect `prompts.py` already names for `task_discovery_recall` —
*"this prompt states no output contract at all"*, the CR-0005 defect — one stage
earlier. CR-0008 contrasts its own prompt against it in so many words. A
registry entry made a prompt look available that nothing could execute.

**Why a stage and not a pass.** Adding a `pass_index` to
`single_pass_prompt_plan` was rejected for ADR-066's reason, which is stronger
here than it was there: a parameter with a default is how a released behaviour
gets changed by accident, and this one would sit on the function whose entire
purpose is to record *which* prompt a run executed. A new stage needs no such
parameter — `single_pass_prompt_plan` returns position one, which for
`product_consolidation` is the only position. `prompt_sequence_complete` is
therefore `True` for the new stage and stays `False` for `product_extraction`,
and both readings are honest.

Every registry in this codebase is already stage-keyed, so a stage is one line
added to each closed map: `EXTRACTION_PROMPTS`, `STAGES`,
`STAGE_PLACEHOLDER_BINDINGS`, `STAGE_REQUIRED_PLACEHOLDERS`,
`STAGE_PASSAGE_REF_STYLE`, `MATERIALIZATION_SUPPORTED_STAGES`. That is the
additive shape ADR-058 used for capability and ADR-068/069 for task.

**Note what it is *not* added to.** `STAGE_OBSERVATION_KIND` gains nothing,
because consolidation produces decisions **about** observations, not
observations. `observation_kind_for_stage("product_consolidation")` refuses with
`stage_observation_kind_undeclared` — ADR-061's fail-closed resolver doing
exactly its job — and the candidate-collection publication path is therefore
unreachable for this stage. The universe is written by its own deterministic
assembler instead.

**The model decides; it does not rewrite.** This is the design rule the rest
follows from. A retained product's body is carried through byte-unchanged from
the candidate it came from, and the model emits only
`{"ref": "D3", "action": "retain", …}`. Two reasons, both measured in this
project rather than assumed here: a model cannot reliably copy a long opaque
string (ADR-055, and an observation is mostly those), and a re-emitted body is
one the model could have altered silently in a field a later reader takes for
discovery's finding. It is ADR-054's rule for derived identity, one artifact on.

The consequence is two schemas rather than one, mirroring
`raw_prediction` → `candidate_collection`:
`product_consolidation_output.schema.json` is what the model returns;
`product_consolidated_universe.schema.json` is what is persisted. Folding them
into one would have meant asking the model for an observation body.

**`D`, and not `C`.** The candidate label family is `D`, unpadded. `C` belongs
to `focal_capability_order` and means "a capability of the focal product";
giving one letter a second meaning is precisely the failure
`canonical_passage_order` exists to prevent — a label naming one thing at render
time and another at resolution time. `A`, `P` and `S` are taken for the same
reason. Unpadded per ADR-064: the correct answer should be what the model writes
naturally. The `A` family stays padded only because a released prompt cannot be
edited; a new family does not inherit that debt.

`candidate_ref_order` is public and shared, for the reason
`focal_capability_order` is: `_bind_product_candidates` assigns the labels the
model sees and `resolve_candidate_refs` resolves the labels it wrote back. Two
orderings that happened to agree would be the same lesson repeated silently.

**A third packet contract, and why it was unavoidable.**
`extraction_input_packet@0.3.0` adds `candidate_context`. The packet schemas are
`additionalProperties: false`, so this could not be a field added in place — but
the deeper reason is that the packet digest is the run's record of what the
model was shown. Passing candidates around the packet would have left
`input_packet_sha256` covering less than the model actually saw. `@0.1.0` and
`@0.2.0` are unchanged, and a caller supplying no candidate pin gets exactly the
packet it got before: the contract is resolved from a closed ladder, never
defaulted.

**What the schema cannot see, and therefore what the conformance layer checks.**
Exhaustiveness is a property of the candidate *set*, which a JSON Schema never
sees. Six reason codes, each with its own test:
`consolidation_candidate_not_decided`, `consolidation_candidate_decided_twice`,
`consolidation_ref_unresolvable`, `consolidation_self_link`,
`consolidation_link_targets_excluded` and
`consolidation_evidence_quote_uncontained` — the last being ADR-063's C8 applied
to a third artifact. A link into an excluded candidate is refused because it
would leave the universe carrying a relation to something the universe says is
not there.

`unresolved` is a first-class action rather than an error path. Rule 7 says
unknown over guess, and a rule the output cannot express is a rule the model
cannot follow.

**Additive, and asserted so.** `product_consolidation_precision` stays at
position five of the `product_extraction` sequence — a frozen prompt is never
moved and never deleted, and moving it would rewrite the record of what that
sequence was. The five-entry product tuple, `single_pass_prompt_plan`, the three
released corpora and the `ext-smoke-0009` chain with the decision set and
Snapshot A built on it are all asserted unchanged by test.

The prompt registry moves `v8` → `v9`. Nothing changed position; the registry
gained a key, and the version is a property of the registry rather than of any
prompt — a record naming `v8` was minted against a three-stage registry.

**What this does not do.** It makes the stage executable; it does not claim its
output is correct, and no live call is authorized by this round. There is no
human decision set over a consolidated universe: the artifact is a model output
with evidence, not an admitted finding, and nothing downstream may treat it as
one until that stage exists. It does not reconcile `entity_type` and
`product_family` — discovery's fields — with `entity_role` and `families[]`,
which are consolidation's; both are recorded, side by side, so which stage said
what stays legible.

**Scope.** One prompt, three schemas, one module, one CR, six registry lines,
one optional runner parameter, six reason codes, 42 tests. No change to any
discovery flow.

## ADR-074 — The detectors stop depending on one filing's markup: `sec_html_item_span_v4` (SPEC-006, ADR-066, ADR-072)

**Status:** Accepted.

**The rule warned about itself, and the second document proved it right.**
`is_heading_block` has carried this sentence since ADR-066:

> Restricted to blocks closing with `</p>` because that is what was verified.
> Measured: allowing every block type finds the same fifteen here, so the
> restriction costs nothing today and **refuses to generalize from one
> document**.

ADR-072 then copied the same gate into `is_page_number_block` for the same
reason. Both were honest about their evidence base. Both were measured on one
filing.

**Measured across fifteen filings, the gate holds in one.** The cohort is large
multi-product US 10-K filers, chosen for size and sector before any markup was
known: ServiceNow, Adobe, Intuit, Palo Alto Networks, CrowdStrike, Workday,
Snowflake, Datadog, MongoDB, Okta, Twilio, Atlassian, Veeva, HubSpot,
Salesforce. Every CIK was verified from EDGAR's `company_tickers.json`; all
fifteen file 10-K, none was dropped.

| signal | filings |
|---|---|
| `</p>` present in Item 1 | **1 / 15** |
| `</div>` the dominant container | 14 / 15 |
| `font-weight:bold` | **1 / 15** |
| `font-weight:700` | 14 / 15 |
| `font-weight:600` / `800` / `900` | **0 / 15** |
| `<b>` or `<strong>` | **0 / 15** |
| `<h1>`…`<h6>` | **0 / 15** |
| `id=` anchor for Item 1 | **1 / 15** |
| `is_heading_block` returns zero for every block | **14 / 15** |

The one filing in every left-hand column is the same one: the pinned HubSpot
10-K the normalizer was written against.

**"Zero dropped" was never "no page numbers".** Because
`is_page_number_block` shares the gate, fourteen filings reported zero
page-number blocks — which reads as an absence and is instead a detector that
never looked. Under v4 the same corpus yields drops in twelve of fifteen, and
ServiceNow's page furniture (bare `2`, bare `4`) is visible for the first time.

**What was broken was the detector, not the concept.** `_BLOCK_SPLIT_RE`
already accepts `p|div|tr|li|h1-6|table|section` and produced 75–240 blocks in
every one of the fifteen. Splitting was general all along. An emphasis detector
admitting `700` beside `bold`, with the container gate removed, finds headings
in **15 / 15** — median heading length 13–24 characters, mostly one to four
words, and only 10 of 419 detections longer than 60 characters. It is finding
headings, not prose.

**No regression, and this is the load-bearing check.** On the pinned HubSpot
Item 1, v4's detectors return the same 15 heading blocks and the same 9
page-number blocks as v3's, at the same indices; `build_passages_v4` reproduces
the committed 16-passage corpus field for field, with `normalizer_version` the
only value that differs.

**Only the measured emphasis forms are admitted.** `600`, `800`, `900`, `<b>`
and `<strong>` measured **zero** across all fifteen and are refused, with a test
asserting the refusal. Adding an unmeasured pattern because it seems plausible
is the speculation this project keeps declining; the zero counts are recorded
here so a filing that uses one is a known extension point rather than a
rediscovery. The measurement instrument used `[6-9]00`; v4 narrows that to `700`
on purpose.

**Locating Item 1 does not generalize either.** Only one filing carries an `id=`
anchor. The other fourteen must be found from heading text, which is written
four measured ways — separator `.` / `:` / `-`, the numeral as `1` or the Roman
`I`, `&#160;` entities interleaved, and runs of whitespace inserted at tag
boundaries. `find_item_one_span` tries the anchor first, so the pinned chain
keeps its exact span, and falls back to text. Two further properties are
measured, not assumed: the body heading is the **last** qualifying match,
because every filing lists Item 1 in its table of contents first; and both ends
must **open a block**, because one filing carries seven inline `see Part I, Item
1A Risk Factors` phrases and locking onto the first cuts that section from
104,132 bytes to 58,046 — a silent 44% loss. It raises `item_span_not_found`
rather than approximating.

**Successor, not edit, and the reason is concrete.** v1, v2 and v3 are
byte-unchanged and a test asserts all three still reproduce their committed
snapshots. The HubSpot chain is hash-pinned to v3's output —
`srcsnap-hubspot-fy2024-sec-v3`, `ext-smoke-0009`, `ext-smoke-cap-0006`, the
task runs and every decision set that cites them. A byte moved in v3 would make
all of it unverifiable.

**Out of scope, and named so it is not mistaken for solved.** ServiceNow's Item
1 yields 44 detections that are page furniture rather than section headings —
`Part I`, `2025 Annual Report 1`, bare `2`, bare `4`. Some are page numbers and
v4's page-number rule removes them; `Part I` is not a number and survives. This
class was measured in **one** filing of fifteen, which is exactly the evidence
base that produced the defect this ADR corrects. No furniture rule is added; it
is left to its own decision, with its own measurement.

**Scope.** One module: four constants, four functions, one finder, no change to
any existing function. One test file: 14 new tests, one existing full-set
assertion widened by one entry. Fixtures are synthetic; no filing HTML is
committed.

## ADR-075 — FRAME is a per-accession filing frame built from full-index fixtures (SPEC-001 Stage A, W1)

**Decision.** The first FRAME_v1 increment is a fixture-only builder:
`src/dynamic_ai_products/universe/frame.py` parses SEC EDGAR full-index
`master.idx` files supplied as local fixtures and assembles the per-accession
annual-filing frame. No live SEC or DERA collection, no real FRAME_v1 run, and
no model call occurs; all three remain gated behind W0. The W0 gate does not
block this implementation, because nothing is collected and no cutoff is
frozen: the filing window is a per-run parameter with no default.

**Grain.** One record per annual-filing accession. CIKs and firm-years are
never collapsed; a CIK with two annual filings inside the window yields two
records. A derived company/CIK view is a later artefact, not this one.
*Superseded in part by ADR-080*: the live 2020-QTR1 canary measured that
accession alone is not unique in the real index — combined multi-filer
submissions list one accession under several filer CIKs — so the natural key
is `(CIK, accession)`, one record per filer-accession. The
no-collapse principle and everything else in this entry stand.

**Window naming.** The frame window is `filing_window_start` /
`filing_window_end`, explicit filing-date admission bounds on the index
`Date Filed` field. The name `analytical_period` is not used anywhere in the
frame code, schema, CLI, or fixtures — fiscal analytical-period assignment
stays a PCT/schema concern with its own open decision (ADR-046), and
`docs/THESIS_EXECUTION_PLAN.md` W1 is corrected accordingly in this round.
`baseline_status` is never assigned by the builder; the baseline cutoff is
W0-owned.

**Accession derivation.** The accession is derived deterministically from the
index `Filename` field — basename stem, validated by the existing
`normalize_accession` rule — and the raw SEC filename is preserved verbatim as
a `sec_filename:` source id beside an `edgar_full_index:<file>#L<line>`
position id. A stem that fails normalization is a parse failure, never a
guess.

**Amendments.** `10-K/A`-style forms whose base form is in scope never create
an annual observation. They are written to a separate `amendment_links.jsonl`
artefact whose original relationship is an explicit **deterministic
candidate**, not a proven link: `candidate_status` is
`deterministic_candidate` with the latest eligible same-CIK, same-base-form
annual record filed on or before the amendment date
(`latest_same_cik_same_base_form_filing_dated_on_or_before_amendment_v1`,
recorded per link and in the manifest), or `unmatched` where none exists.
Proving the relationship would require reading the amendment's cover page,
which this increment does not do.

**Exhaustive accounting.** Every index data line lands in exactly one bucket,
with precedence: parse failure → integrity failure (conflicting rows sharing
one accession; none of them enters the frame, because the accession's true
fields are unknown and unknown is never coerced) → duplicate (identical
repeated row, recorded against the first occurrence) → out-of-window → form
partition (domestic annual | FPI extension | amendment link | out-of-scope
form). The manifest records the count identities and the build refuses to
write when one fails. Out-of-scope-form rows (counted per form) and
out-of-window rows are counted, not copied into artefacts: the hashed
immutable index files are their recoverable record.

**Structural format.** The canonical `master.idx` table header
(`CIK|Company Name|Form Type|Date Filed|Filename`) and the dashed separator
directly beneath it are required exactly; the preamble text above them may
vary, as historical EDGAR preambles do. Fixtures are fully synthetic — every
CIK, name, accession, and date invented — but reproduce that structural format
exactly.

**Interface.** The existing Stage 00 CLI gains a mutually exclusive
`--mode {sentinel,frame}` with `sentinel` as the default, so every
pre-existing invocation is byte-for-byte unchanged; each mode rejects the
other mode's flags explicitly. Frame mode reads the form scopes from
`configs/project.yaml` (`universe.domestic_form_scope`,
`universe.foreign_private_issuer_extension_forms`) and records the config
hash; the window bounds are required CLI parameters. No new pipeline stage,
no registry change, no notebook change.

**Schema governance.** `filer_frame_manifest.schema.json@0.1.0` is registered
in `schema_version_manifest.json` (manifest_version 0.22.0 → 0.23.0, 54 → 55
entries; every released schema byte-identical, only the registry grew), and
both pinned hashes of that manifest —
`tests/evaluation/test_schema_registry.py` and
`tests/evaluation/test_run_manifest_v2.py` — are rebaselined on that edit,
following the ADR-073 pattern.

**Scope.** New: the frame module, its manifest schema, the
`evals/fixtures/edgar_full_index` bundle (manifest, three `master.idx`
quarters, expected-frame gold), and one test file. Modified: the Stage 00 CLI
(mode dispatch only), the schema registry and its pinned hash, the W1 wording,
`REPO_MANIFEST.md` and its three count regression tests. Untouched: packets,
prompts, providers, normalisation, the sentinel runner, the notebook, and
every existing schema.

## ADR-076 — Index acquisition ships before its live transport, and says so (SPEC-001 Stage A, SPEC-003, W1)

This is not the W0 design record. That record — baseline cutoff, filing
window, identification design — remains undrafted and blocks all live
collection; this ADR covers only the fixture-replay acquisition increment.

**Decision.** `src/dynamic_ai_products/universe/frame_acquisition.py`
acquires a declared request plan of EDGAR full-index `master.idx` URLs
through an **injected transport callable** and persists write-once raw files
plus one write-once, schema-validated acquisition manifest. The only
transport that exists is a deterministic local fixture replay; the module
contains no network code and no live callable.

**Transport identity is truthful.** The manifest records
`transport_kind = "fixture_replay"` and the fixture-replay transport's own
contract hash. It does **not** record `collection.transport`'s
`CLIENT_CONTRACT` or its hash: no live client executes here, no user agent is
sent, no rate limit is enforced, and no retry policy applies. The real SEC
transport contract and its enforcement belong to the post-W0 live-binding
increment, which will extend the manifest schema in a successor version (the
`transport_kind` enum currently admits only `fixture_replay` on purpose).

**Request-plan trust boundary.** A plan entry declares only a quarter label
and a URL, which must agree exactly under the canonical grammar
`https://www.sec.gov/Archives/edgar/full-index/<YYYY>/QTR<n>/master.idx`
(https only, `www.sec.gov` only, years 1993–2100). The local output filename
is derived in code from the validated label — a plan-supplied filename or any
unknown key is refused, so separators, traversal text, duplicate local
targets, and duplicate quarters can never reach the filesystem. The plan file
is hash-pinned into the manifest.

**Failure semantics.** Redirect statuses are refused outright (the pilot
Route A stance; static index files never legitimately redirect), as are
terminal-URL mismatches, non-200 statuses, transport exceptions, and
write-once refusals. Any failure **while acquiring a raw planned entry**
persists a write-once, non-authoritative `acquisition_failure_receipt.json`
carrying a stable reason code, the attempted planned entry, and the files
acquired before the failure. The receipt's coverage stops there: a failure
while persisting the manifest itself is not converted into a receipt — it
propagates, leaving the run directory with raw files and no manifest. In
both cases no acquisition manifest exists after a failure, and manifest
presence is the sole mark of an authoritative acquisition. The failure
receipt is defined by a strict in-code model and this entry rather than a
JSON schema, because it is non-authoritative by construction and nothing
downstream may consume it.

**Determinism is tested honestly.** The clock is injected; a fixture run with
a fixed clock and the same run id produces a byte-identical manifest, and the
test asserts exactly that rather than excusing embedded timestamps.

**Frame consumption.** `run_frame_builder` accepts exactly one inventory
source: the existing fixture bundle (byte-identical behaviour, untouched
outputs) or an acquisition manifest. The manifest crosses a trust boundary
and is gated before any raw file is read or hashed: it must validate against
its canonical schema (every violation is a refusal); its `transport_kind`
must equal `fixture_replay`, checked explicitly beside the schema enum —
the only reviewed consumption path in v0.1, so a live successor schema must
receive its own reviewed path rather than widening a conditional; and a
duplicate receipt filename is refused rather than silently overwriting an
earlier receipt. Only then is every raw-file hash verified against its
receipt **before any parsing** — a mismatch refuses the build. The acquired
route's frame version is the code-owned `FRAME_VERSION_ON_ACQUIRED_BUILD`
(`FRAME_v1.0-draft`), never CLI text; the FRAME_v1 freeze records the
released version later.

**Schema governance.** `edgar_index_acquisition_manifest.schema.json@0.1.0`
is registered (manifest_version 0.23.0 → 0.24.0, 55 → 56 entries; every
released schema byte-identical, only the registry grew), and both pinned
hashes of the registry — `tests/evaluation/test_schema_registry.py` and
`tests/evaluation/test_run_manifest_v2.py` — are rebaselined, following the
ADR-073 pattern.

**Deferred, named so it is not mistaken for done.** Live SEC binding (real
client contract, user agent, rate limiting, retries), the DERA FSDS coverage
comparison (a W1 validation artefact consuming this same machinery), and the
real FRAME_v1 build and freeze. All remain gated behind W0.

**Scope.** New: the acquisition module, its manifest schema, the request-plan
fixture, and one test file. Modified: the frame builder (inventory input and
hash verification only), the Stage 00 CLI (third mode plus mode validation),
the schema registry and its two pinned hashes, `REPO_MANIFEST.md` and its
three count regression tests. Untouched: packets, prompts, providers,
normalisation, the sentinel runner, the notebook, `configs/project.yaml`,
pipelines/01–14, and every existing schema.

## ADR-077 — W0 design freeze: cutoff, filing window, and the comparison design (THESIS_EXECUTION_PLAN W0)

This is the W0 decision record the thesis plan requires before any live
collection. It freezes the design quantities named below, states exactly what
it does not freeze, and unblocks the live index-acquisition canary. It makes
no live request and enables no model call.

**Baseline cutoff: 2022-11-29, frozen ex ante.** One day before the ChatGPT
public launch of 2022-11-30, the shock date the literature review pins and
warns against treating imprecisely. Recorded in `configs/project.yaml`
`universe.baseline_cutoff` — the freeze surface
`docs/methodology/SOFTWARE_FIRM_UNIVERSE.md` §3.1 committed to — and to be
recorded in every universe manifest. Baseline incumbency uses only evidence
available on or before this date; the cutoff is a source-admission and
membership bound in the sense of `docs/TEMPORAL_POLICY.md`, not a fiscal
label.

**FRAME filing-date admission window: 2020-01-01 through 2026-06-30** (2020
QTR1 through 2026 QTR2 of the EDGAR full index), recorded as
`universe.filing_window_start` / `universe.filing_window_end`. This freezes
**filing-date admission only**. `observation_window` in `configs/project.yaml`
is deliberately unchanged in this increment, and that is **not a decision to
exclude FY2020/FY2021 baseline PCT evidence**: filing dates and fiscal
reporting periods differ across firms, so the eventual fiscal-period carrier
(the ADR-046 open item) and PCT observation coverage remain a separate
successor decision. The only frozen 2020–2026 range is FRAME filing-date
admission.

**FY2022 is retained as a transition observation.** Final
pre/transition/post classification is based on **actual reporting-period
start and end dates**, never firm fiscal-year labels — FY labels straddle the
shock differently across issuers, and a label-based split would misclassify
firms whose fiscal 2022 ends months before or after the cutoff.

**Comparison design.** Stated in full so no later reading narrows it:

- **No binary treated/control group is frozen.** The design has no discrete
  treatment assignment.
- **All eligible firms remain in the universe.** No firm is excluded by
  exposure level or by response.
- **Baseline frontier task replicability is a future continuous ex-ante
  exposure measure**, computed from pre-shock product-task observations only
  (the construct of `docs/methodology/MEASUREMENT_DESIGN.md` §1).
- **Post-shock AI transformation, mechanism reach, and deployment are
  observed responses**, never treatment criteria and never eligibility
  criteria. Baseline eligibility is governed by
  `docs/methodology/SOFTWARE_FIRM_UNIVERSE.md` §1 and §3.1; `CLAUDE.md`
  Rule 12 supports the construct separation but does not itself establish
  the eligibility rule.
- **The exact FTR rubric, weights, outcome variable, and estimator/FE
  specification remain pilot-gated.** The thesis plan's W0 scope is thereby
  split explicitly: the structural design above is frozen now; the
  specification is not, and the SAMPLE_v1 gate still stops for a scope
  decision if the pilot-determined firm requirement exceeds the 200-firm
  extraction ceiling.

**What W0 unblocks and what stays gated.** Live EDGAR full-index acquisition
(the canary first, reviewed before any range run) is unblocked from this
record. Model calls remain gated behind W3/W4 prompt qualification; the full
frame run remains gated behind the reviewed canary; `full_edgar_run_enabled`
stays `false`.

**Scope.** Modified: `configs/project.yaml` (three `universe` keys),
`docs/THESIS_EXECUTION_PLAN.md` (W0 gate entry),
`docs/methodology/SOFTWARE_FIRM_UNIVERSE.md` (§3.1 value, §11 item resolved),
`tests/universe/test_universe_design.py` (the legacy cutoff-is-None assertion
updated so no contradictory test survives, plus one focused W0 consistency
test). Untouched: extraction, measurement, taxonomy, every schema and both
pinned registry hashes, CLI behaviour, `observation_window`,
`REPO_MANIFEST.md` and its count tests, and all pipelines.

## ADR-078 — The live SEC index transport is a successor binding, not a widened fixture (SPEC-003, ADR-076, ADR-077)

W0 (ADR-077) unblocked live index acquisition. This increment adds the
smallest live successor path for a one-quarter canary. The canary itself has
**not** been run: no live request has been made, and no model is called.

**Placement.** The live transport lives in the new top-level module
`src/dynamic_ai_products/sec_index_transport.py`, not in the universe
package: the universe package imports neither `collection` nor `ingestion`
and contains no network code (the committed boundary tests), so the transport
is built outside and injected into the acquisition runner as a callable, with
its identity passed alongside as data. The repository-wide httpx allowlist —
the exact-importer guard ADR-037 set at one module and ADR-040 widened to
two — widens to three named modules to admit this transport; both guard
tests record this ADR as the reason, which is precisely the review those
guards exist to force.

**Committed live contract** (`SEC_LIVE_TRANSPORT_CONTRACT`, embedded verbatim
in every v0.2 manifest beside its hash): a descriptive SEC-compliant user
agent carrying a contact address; at most one request per second, enforced by
monotonic-clock spacing; a 30-second per-request timeout; at most two retries
per URL with a fixed 5s/15s backoff ladder, applied to retryable statuses
(429/500/502/503/504) and transport exceptions; redirects never followed —
a redirect status is returned as-is and the runner refuses it. The send, the
sleeper, and the monotonic clock are injectable, so every test asserts
spacing and backoff against fakes; the default httpx send (fresh client per
request, cookie isolation) is the only place a network request can originate,
and nothing in the test suite calls it.

**Successor manifest, not a widened contract.**
`edgar_index_acquisition_manifest.v2@0.2.0` admits only `sec_live` and
requires the embedded transport contract; v0.1 remains the fixture_replay
contract, byte-identical, and fixture runs still write it unchanged. The
runner takes an explicit `TransportIdentity`; omitting it preserves the
fixture-replay identity and v0.1 output exactly. The failure-receipt model's
kind literal widens to carry either identity truthfully.

**Frame consumption was deliberately absent at this increment.** Per
ADR-076, the live manifest required its own explicitly reviewed consumption
path; `run_frame_builder` refused a v0.2 manifest and a regression test
pinned that refusal. *Superseded by ADR-079*, which delivers the reviewed
sec_live consumption branch and replaces the refusal regression with
consumption and refusal coverage. The v0.2 manifest still never
self-authorizes consumption; the reviewed consumer path does.

**CLI.** `--mode acquire-index` gains `--transport {fixture,sec-live}` with
`fixture` as the default, so every pre-existing invocation is unchanged;
`sec-live` forbids `--replay-dir`, performs real requests when actually run,
and writes the v0.2 manifest. Dry-run validates the plan before any
transport call, so a `sec-live --dry-run` never sends. Two canonical live
request plans are committed, and possessing either authorizes nothing: the
one-quarter canary plan at `configs/edgar_index_canary_request_plan.json`
(exactly one entry, 2020 QTR1, the earliest frozen-window quarter, so the
reviewed canary makes exactly one real request) and the full-range plan at
`configs/edgar_index_full_request_plan.json` (26 contiguous quarters, 2020
QTR1 through 2026 QTR2, the frozen filing-date admission window of
ADR-077). Every actual live run remains separately authorized. The
three-quarter plan under `evals/fixtures/edgar_index_request_plan/` remains
a synthetic fixture input, unchanged. The CLI still requires
`--request-plan` explicitly; no plan is ever implied.

**Schema governance.** Registry manifest_version 0.24.0 → 0.25.0, 56 → 57
entries; every released schema byte-identical; both pinned registry hashes
rebaselined, following the ADR-073 pattern.

**Deferred, named so it is not mistaken for done.** The full-range
download; DERA validation; the real full FRAME_v1 build and freeze.

**Subsequent execution status (note added after this entry).** The
separately authorized one-quarter 2020-QTR1 canary was later run and
completed successfully — one request, one acquired file, a schema-valid
v0.2 manifest. Its immutable artifacts and the evidence they produced are
governed by ADR-079, which pins the artifact hashes and permits consumption
of the valid manifest, and ADR-080, which records the grain defect the
canary measured and its correction.

**Scope.** New: the transport module, the v0.2 schema, the canonical
one-quarter canary request plan, and one mocked-transport test file.
Modified: `frame_acquisition.py` (identity parametrization, the v0.2
builder, and a module docstring that describes the two-transport
architecture; fixture default unchanged), the Stage 00 CLI (`--transport`
flag), the schema registry and its two pinned hashes, the two httpx
exact-allowlist guard tests (two → three named importers),
`REPO_MANIFEST.md` and its three count regression tests. Untouched:
`frame.py` and all frame consumption, packets, prompts, providers,
normalisation, the sentinel runner, the notebook, `configs/project.yaml`,
pipelines/01–14, and every existing schema.

## ADR-079 — The reviewed sec_live consumption path: a v0.2 manifest never self-authorizes (SPEC-001 Stage A, ADR-076, ADR-078)

ADR-076 established that a live acquisition manifest must receive its own
explicitly reviewed frame-consumption path, and ADR-078 pinned the interim
refusal. This ADR delivers that path. It supersedes ADR-078's temporary
refusal statement and nothing else. No SEC request is made here, no further
quarter is downloaded, no model is called, and the real FRAME canary build
has not been run.

**Authority interpretation, stated precisely.** An immutable v0.2 manifest
does not self-authorize anything — its own limitation text says so, and the
already-created canary manifest's ADR-076-era wording remains true as
written. What now permits consuming a *valid* v0.2 manifest is this
separately reviewed consumer branch together with this ADR. That permission
covers the one-QTR canary artifact already on disk:
`edgar_index_acquisition_manifest.json` sha256
`c9b850d6ee93e0ec5aa0af4f35b323ce7a5ef52806d8603fbd15d02d6d7a1e6f` with raw
`master-2020-QTR1.idx` sha256
`1973b14fc2c8e437db28e733d23148e3b1ac7c07fe1fe5c81009031d8cde02fd`
(29,145,406 bytes, status 200). Manifests written from now on carry the
ADR-079 wording ("does not authorize frame consumption by itself").

**Consumption dispatch.** `run_frame_builder` selects the consumption branch
by the manifest's declared `transport_kind` and validates against the schema
that kind selects — not a widened conditional. `fixture_replay` keeps the
v0.1 branch behaviourally unchanged, including its defensive explicit kind
check. `sec_live` gets the new branch: v0.2 schema validation (every
violation a refusal), then the embedded transport contract is **recomputed
under the one canonical JSON form** (`canonical_contract_hash`, shared with
identity recording) **and matched against the recorded
`transport_contract_hash` before any raw `.idx` file is read**. Any other
kind is refused with the admitted paths named.

**Fail-closed checks preserved.** Both branches then share the same
inventory gate: safe filenames only, duplicate receipt filenames refused,
exact on-disk/manifest inventory match, and SHA-256 verification of every
raw index file against its receipt — all before parsing.

**Provenance.** The resulting FRAME manifest's limitations carry the parent
acquisition-manifest SHA-256, the `sec_live` identity, and the verified
transport-contract SHA-256. The frame version stays the code-owned
`FRAME_VERSION_ON_ACQUIRED_BUILD`; no schema is added or changed and the
registry is untouched — the existing `filer_frame_manifest@0.1.0` carries
the provenance in its limitations field.

**Tests.** The ADR-078 refusal regression is replaced by a consumption test:
fixture bytes served through the sec_live wrapper reproduce the committed
expected-frame gold exactly, with the three provenance lines asserted.
Refusals proven to fire before any raw read: malformed v0.2 manifest (extra
property, missing governed field), tampered `transport_contract_hash`
(schema-valid but wrong), tampered raw file (hash mismatch), and an unknown
transport kind. The v0.1 fixture-regression suite is untouched, and CLI
frame mode is exercised end-to-end against a fixture-backed v0.2 manifest.
No test reads `data/runs` or the network.

**Still gated.** The real FRAME canary build over the live 2020-QTR1
artifact (the next separately authorized action), the full-range download,
DERA validation, and all model calls.

**Scope.** Modified only: `frame.py` (dispatch + sec_live branch + shared
schema-validation helper), `frame_acquisition.py` (`canonical_contract_hash`
helper and the forward limitation wording), one test file, and ADR-078's
superseded statements. No new files, no schema change, no registry or
REPO_MANIFEST change.

## ADR-080 — The frame key is (CIK, accession): the canary refutes global-accession grain (SPEC-001 Stage A, ADR-075, ADR-079)

**The measurement that forces this entry.** The first real FRAME canary —
run `frame-live-canary-2020-qtr1-20260815` over the live 2020-QTR1 artifact
(acquisition manifest sha256
`c9b850d6ee93e0ec5aa0af4f35b323ce7a5ef52806d8603fbd15d02d6d7a1e6f`, raw
`master-2020-QTR1.idx` sha256
`1973b14fc2c8e437db28e733d23148e3b1ac7c07fe1fe5c81009031d8cde02fd`,
324,904 data lines, zero parse failures) — put 203,854 rows (63%) into the
integrity-failure bucket under ADR-075's global-accession rule. Read-only
characterization of that artifact: 97,300 groups, of which **97,296 span
multiple filer CIKs** — EDGAR's legitimate combined multi-filer submissions,
dominated by Section 16 Forms 4/3/5 (127,598 rows) and SC 13G/D group
filings — and only 4 are genuine single-CIK conflicts. The materially
important subset: 194 groups contained in-scope annual forms, wrongly
excluding 451 10-K/20-F filer rows, e.g. American Electric Power's combined
10-K (accession `0000004904-20-000007`) filed by the parent and its
registrant subsidiaries. The global-accession assumption was
synthetic-fixture-only; the real index's natural key is `(CIK, accession)`.

**Decision.** The FRAME observation key is the filer-accession pair
`(CIK, accession_number)`:

- same accession, different CIKs — a legitimate multi-filer/combined
  filing: one frame record per filer CIK, never an integrity failure;
- same `(CIK, accession)`, identical content differing only in provenance —
  a duplicate: the deterministic first row is kept and the repeat recorded;
- same `(CIK, accession)`, conflicting non-provenance content — a genuine
  integrity failure that excludes **only that filer-accession group**, never
  another CIK sharing the accession.

All four reconciliation identities keep their exact form and remain
exhaustive; the buckets are unchanged, only their key is corrected. The
amendment candidate rule already matched within one CIK and is unchanged; a
combined amendment now simply resolves per filer. The
`FrameIntegrityFailure` record gains the filer `cik` beside the accession
and its reason code is renamed to `conflicting_same_filer_accession_rows`.

**Version label.** Production FRAME semantics changed, so the code-owned
acquired-build label moves `FRAME_v1.0-draft` → `FRAME_v1.1-draft`. The
existing `data/runs` artifacts — the acquisition canary and the v1.0-draft
frame canary that measured this defect — remain immutable and are
superseded, not edited; the manifest schema is untouched (the grain is not
encoded in the schema).

**Fixtures and tests.** The synthetic bundle gains a combined multi-filer
10-K (accession `0002000012-23-000004` under three filer CIKs), and the
gold moves from accession lists to filer-accession pairs. Tests assert:
each combined filer enters the domestic partition (one record per CIK) and
appears in neither the integrity nor the duplicate bucket — the direct
regression that a combined filing can never silently exclude another
filer's annual record; the same-CIK conflict fixture still lands, alone, in
the integrity bucket; the identical-duplicate case still lands at its
`(CIK, accession)` key. Everything stays offline and independent of
`data/runs`.

**Scope.** Modified only: `frame.py` (grouping key, integrity model and
reason code, version label, grain wording), the fixture bundle (one file
extended, manifest description, expected-frame gold), one test file, and
ADR-075's superseded grain claim. No new files, no schema change, no
registry, REPO_MANIFEST, or pipeline change. W0, source policy,
AI-mechanism work, PCT, and prompts are untouched. The real FRAME canary
has not been rerun; that is the next separately authorized action.

## ADR-081 — DERA FSDS validates the frame and never defines it (THESIS W1, ADR-080)

The thesis plan fixes DERA FSDS as an independent validation source only,
never the frame source. This entry delivers the fixture-first validation
increment and records its construct rules. No live DERA or SEC request is
made; the live-DERA acquisition remains a separate, later increment whose
canary must verify the actual archive URL and derive `observed_through`
(with or without a post-window release buffer) from evidence rather than
assumption.

**Construct.** A completed FRAME run is compared against locally supplied
FSDS `SUB`-level files at the ADR-080 filer-accession `(CIK, accession)`
grain. The validator consumes the frame read-only — every frame artifact is
verified against the frame manifest's `output_hashes` before comparison —
and writes only its own schema-validated, write-once artifact
(`frame_dera_validation_manifest@0.1.0`). DERA is never a universe
eligibility or filtering source. The input contract is header-name lookup
over exactly `adsh`, `cik`, `name` (display only), `form`, `filed`,
`nciks`, `aciks`; real full-width `sub.txt` files parse unchanged.

**Registrant sets follow the official FSDS contract.** `aciks` is
space-delimited additional CIKs, optionally ending in a terminal `PARTIAL`
token, which is valid input and never a parse failure. `nciks` must always
be a positive integer. Non-PARTIAL rows must satisfy
`nciks == 1 + declared additional CIKs`; PARTIAL rows must satisfy
`nciks > 1 + declared additional CIKs`, because PARTIAL asserts that at
least one co-registrant is omitted. Every violation is an explicit parse
failure. PARTIAL rows retain every declared pair, mark the submission and
every affected comparison `dera_registrant_set_partial`, and never infer
omitted CIKs; a FRAME filer unlisted in a PARTIAL set lands in the visible,
non-gating `unresolved_partial_registrant_set` class, excluded from
noncoverage rates and structurally unable to become a contradiction. A
registrant-set disagreement against a **non-PARTIAL** (complete) set is a
genuine contradiction in either direction and gates. Each submission
expands to one comparison pair per declared registrant
(`primary` / `co_registrant`), so combined filings are compared per filer
and never collapsed — the ADR-080 lesson applied to the validation side.

**Categories and identities.** Every FRAME annual record lands in exactly
one of: matched (with under-PARTIAL sub-count), identity_mismatch,
noncoverage, right_boundary_unobserved, unresolved_partial_registrant_set,
frame_filer_not_in_dera_registrants. Every DERA expanded pair lands in:
matched, mismatched, registrant_not_in_frame, only_explained
(integrity-excluded accessions), only_unexplained. Six reconciliation
identities bind both sides and both strata.

**Absence is non-coverage, not error; the boundary is declared.** A FRAME
record absent from DERA is expected FSDS/XBRL non-coverage — reported in
total and per base form (10-K, 10-KT, 20-F, 40-F) as counts and rates over
observable records, never gated. `observed_through` is a declared input:
an absence filed after it is `right_boundary_unobserved`, so a possible
post-cutoff DERA release omission is never misreported as non-coverage,
and the validator never infers coverage it was not told about.

**Gate (`frame_dera_validation_gate_v1`).** Equality is not the gate. Fail
closed on: any annual `dera_only_unexplained`; any annual
`identity_mismatch` (form and filed-date comparison is literal — no
timing-rollover exception exists unless a real DERA canary supplies
evidence for one, at which point it would need its own entry); any annual
non-PARTIAL registrant-set contradiction
(`frame_filer_not_in_dera_registrants` or `dera_registrant_not_in_frame` —
only the explicitly PARTIAL unresolved class is non-gating); any DERA
parse failure (`dera_parse_failures > 0`: a malformed or inconsistent row
must never yield a passing validation merely because it was excluded from
comparison; the manifest is still written with `gate_status: fail`); any
broken reconciliation identity; zero annual matches when both comparable
populations are nonempty. The amendment stratum reconciles and is fully
reported but is report-only and cannot fail the gate.

**Fixtures.** Synthetic bundle with the genuine 36-column FSDS header,
aligned to the frame fixture: matched 10-K/20-F, a complete-`aciks`
combined 10-K, a PARTIAL combined 40-F (the frame fixture gained a
two-filer 40-F pair for this), a matched amendment, uncovered filings on
both sides of `observed_through`, an out-of-scope 10-Q, and an
out-of-window row. Gate failures are proven with mutated bundles; the
committed gold passes. Everything is offline and independent of
`data/runs`.

**Schema governance.** `frame_dera_validation_manifest@0.1.0` registered;
manifest_version 0.25.0 → 0.26.0 (57 → 58 entries); both pinned registry
hashes rebaselined, following the ADR-073 pattern.

**Scope.** New: the validation module, its manifest schema, the four-file
DERA fixture bundle, and one test file. Modified: the Stage 00 CLI (fourth
mode `dera-validate`), the frame fixture bundle (combined 40-F pair; FPI
gold 1 → 3), the schema registry and its two pinned hashes,
`REPO_MANIFEST.md` (647 → 654) and its three count regression tests.
Untouched: FRAME/acquisition/transport code and schemas,
`configs/project.yaml`, all `data/runs` artifacts, prompts, the notebook,
pipelines/01–14, and all live-network activity. The validation of the real
full FRAME run against real DERA data is a later, separately authorized
action that first requires the live-DERA acquisition increment.

## ADR-082 — DERA archives are acquired, receipted, and extracted; never assumed (THESIS W1, ADR-081)

The fixture-first DERA FSDS archive acquisition increment. No real DERA or
SEC request is made here; no model is called; the universe package stays
network-free — the live transport is the committed `sec_live` policy
wrapper, built outside the package and injected in with its identity as
data, exactly as the index acquisition does.

**Plan contract (`dera_fsds_request_plan@0.1.0`).** The plan declares one
`url_template` — enforced in code to be `https://`, host `www.sec.gov`,
with exactly one `{release}` placeholder — plus release labels matching
`YYYYq[1-4]` (2009–2100, no duplicates), `observed_through`, and its
required `observed_through_basis` evidence field. The template path is a
*candidate*: the separately authorized canary verifies it empirically, and
a wrong path fails closed with a receipt and revises the plan, never code.
Local filenames (`dera-<release>.zip`, `dera-<release>-sub.tsv`) are
derived in code, never read from the plan. The canonical one-release canary
plan is committed at `configs/dera_fsds_canary_request_plan.json`
(2020q1; basis recorded as the conservative release-quarter-end rule per
decision 2); possessing it authorizes nothing.

**Acquisition and extraction.** Raw release ZIPs are preserved write-once
with hash receipts before anything is extracted. Exactly one member named
`sub.txt` is then extracted per archive: a corrupt archive, a missing or
duplicate `sub.txt`, any member carrying an absolute path, a backslash, or
`..`, and an uncompressed `sub.txt` above the code-owned 512 MB ceiling
(recorded in every manifest; a bounded read also caps a lying size header)
are each refused with a stable-reason, write-once failure receipt — the
raw ZIP stays on disk, nothing is extracted, and no acquisition manifest or
bundle exists after any failure. Manifest presence is the sole mark of an
authoritative acquisition; a failure while persisting the final manifests
propagates and leaves no manifest, non-authoritative under the same rule.

**Two-schema pattern, per precedent.**
`dera_fsds_acquisition_manifest@0.1.0` admits only `fixture_replay`;
`dera_fsds_acquisition_manifest.v2@0.2.0` admits only `sec_live` and embeds
the live transport contract verbatim beside its hash — never a widened
fixture contract. Both record the plan hash, the template, the
plan-authored `observed_through` and its basis (copied verbatim; the runner
never infers coverage), the extraction ceiling, and per-archive receipts
(ZIP hash/bytes/status, member name and hash, extracted output hash).

**Consumer bundle.** The run directory doubles as a `dera-validate` input:
the runner writes the exact bundle shape the committed validator reads
(`fixture_manifest.json` — the name is the consumer contract — plus the
extracted `*.tsv` files), carrying the plan-authored `observed_through` and
basis, the release list, and provenance extras (acquisition run id, plan
hash) the validator ignores. `frame_dera_validation.py` is untouched
(decision 5); the end-to-end test proves a fixture acquisition validates
the fixture frame reproducing the ADR-081 gold exactly. Enforcing the
acquisition-to-bundle hash chain inside the validator remains deferred.

**CLI.** Fifth Stage 00 mode `acquire-dera`, sharing
`--request-plan`/`--replay-dir`/`--transport` with `acquire-index` under
the same fixture-default, sec-live-forbids-replay rules; every other mode
rejects its flags and vice versa. Dry-run validates the plan before any
transport call.

**Schema governance.** Registry manifest_version 0.26.0 → 0.27.0 (58 → 60
entries); every released schema byte-identical; both pinned registry hashes
rebaselined, following the ADR-073 pattern.

**Deferred, named so it is not mistaken for done.** The real one-release
canary download (separately authorized; it verifies the URL path and must
revisit the `observed_through` basis with observed evidence); the
full-range DERA plan and acquisition (authored after canary evidence,
including the post-window release-buffer decision); the real validation of
the existing full FRAME artifact; the FRAME_v1 freeze decision.

**Scope.** New: the acquisition module, the v0.1 and v0.2 schemas, the
canary plan config, the three-file archive fixture bundle, and one test
file. Modified: the Stage 00 CLI (fifth mode), the schema registry and its
two pinned hashes, `REPO_MANIFEST.md` (654 → 662) and its three count
regression tests. Untouched: `frame_dera_validation.py`, `frame.py`,
`frame_acquisition.py`, `sec_index_transport.py`, the committed `dera_fsds`
fixture bundle and its gold, `configs/project.yaml`, all `data/runs`
artifacts, prompts, the notebook, pipelines/01–14, and all live-network
activity.

## ADR-083 — The full-range DERA plan: 26 canary-verified releases, no buffer yet (ADR-081, ADR-082)

A plan/config-only increment: no code, no schema, no registry bump, no
pinned-hash rebaseline. It commits the full-range DERA request plan the
separately authorized acquisition will consume, following the
commit-before-acquire pattern the EDGAR index plan established: possessing
the plan authorizes nothing.

*Superseded in part by ADR-084*: the authorized 26-request acquisition
measured 2026q2 unavailable (HTTP 404 at the verified template), so the
**Release set** paragraph's 26-release span and **decision A's
`observed_through` = 2026-06-30** are revised there to 25 releases and
2026-03-31. Everything else in this entry stands.

**Canary evidence, pinned.** Run `dera-fsds-canary-2020q1-20260816`
(one real request, exit 0) empirically verified the URL template
`https://www.sec.gov/files/dera/data/financial-statement-data-sets/{release}.zip`:
acquisition manifest sha256
`7e6c44389a4299a76737533cc3144404b5a50354649467adc327272ccc3234d6`, raw ZIP
sha256
`48ed9834c66d565c21130d087eae941b25770e2d7cc8351d17652612289fcd67`
(96,584,608 bytes, status 200), extracted `sub.txt` sha256
`5c89b0295c403903909c34b9293d9a050f589b0722585f3ee6d6035b16501950`
(1,739,253 bytes, 5,817 lines), with the real SUB header matching the
parser's column contract exactly. The 5,816-submission quarter against the
index's 324,904 rows is the expected XBRL-only FSDS scoping that ADR-081's
non-coverage reporting was built to measure, not to gate.

**Release set.** 26 releases, 2020q1 through 2026q2 — one per quarter of
the frozen FRAME filing window (ADR-077). EDGAR's published acceptance rule
assigns a filing date no earlier than the acceptance day (post-5:30 p.m. ET
acceptances receive the next business day's filing date), so the release
union spans every in-window filed date; December-2019 filings appearing in
2020q1's dataset fall into the validator's `dera_out_of_window` bucket
harmlessly.

**No buffer release (decision B).** 2026q3 is not currently acquirable for
this freeze window — its quarter is incomplete and the release does not
exist. A successor plan may add it later **only if** real validation shows
late-June edge clustering; the right-boundary construct absorbs the edge
until then.

**`observed_through` = 2026-06-30 (decision A).** Plan-authored with the
acceptance-rule basis above and explicit residual-risk language: the
residual is dataset-cut slippage of late-June 2026 filings into the
unpublished 2026q3 release — operationally possible, not derivable from
published rules. Noncoverage is non-gating (ADR-081), and the basis names
the review checkpoint: if the full validation shows late-June edge
clustering, a successor plan revisits the value and/or adds 2026q3. The
ultra-conservative 2026-03-31 alternative was considered and rejected.

**Scale note for the later authorization.** ~26 requests at the committed
1 request/second spacing; roughly 2.5 GB of raw ZIPs by canary scale, with
extracted SUB files in the tens of megabytes.

**Deferred, named so it is not mistaken for done.** The full 26-release
live acquisition (separately authorized, consuming this plan); the real
validation of the full FRAME_v1.1-draft artifact through the ADR-081 gate;
the FRAME_v1 freeze decision.

**Scope.** New: `configs/dera_fsds_full_request_plan.json`. Modified: one
offline test in `tests/universe/test_dera_acquisition.py`,
`REPO_MANIFEST.md` (662 → 663), and its three count regression tests.
Untouched: everything else — all code, all schemas and both pinned registry
hashes, `frame_dera_validation.py`, `dera_acquisition.py`,
`sec_index_transport.py`, FRAME code and artifacts, `data/runs`,
`configs/project.yaml`, the canary and fixture plans, prompts, the
notebook, and pipelines.

## ADR-084 — 2026q2 is measured unavailable: the DERA plan drops to 25 releases (ADR-081, ADR-083)

**The measurement that forces this entry.** The separately authorized
26-request full-range acquisition
(run `dera-fsds-full-2020q1-2026q2-20260816`, consuming the ADR-083 plan,
sha256 `1d03bd0843a70531498d507a80c9a73d9f26614b6459124b1efc2515d5c3aefd`)
acquired 25 archives — 2020q1 through 2026q1, every one status 200,
write-once with `sub.txt` safely extracted, ~2.53 GB of raw ZIPs — and then
failed closed on the 26th: **HTTP 404 for
`https://www.sec.gov/files/dera/data/financial-statement-data-sets/2026q2.zip`
on 2026-08-16**, receipted at
`dera_acquisition_failure_receipt.json` in the run directory. DERA has not
yet published the 2026q2 FSDS release; its publication lag exceeds the ~6.5
weeks since that quarter ended. ADR-083's residual-risk language
anticipated exactly this evidence class.

**Fail-closed behavior worked as designed, and the dead run stays dead.**
No acquisition manifest and no consumer bundle were written; manifest
presence is the sole mark of authority, so the run is non-authoritative and
`dera-validate` structurally cannot consume it (its required bundle
manifest never exists). The 25 acquired ZIPs and extracted TSVs remain
immutable and gitignored under `data/runs/dera-fsds-full/…-20260816` —
never deleted, never repaired, never partially salvaged. Runs are
all-or-nothing: the rerun re-acquires all 25 releases under a fresh run-id,
which is the price of the no-silent-repair guarantee.

**Revised construct (in-place plan revision).**
`configs/dera_fsds_full_request_plan.json` is revised in place — it is a
versioned repository config, not an immutable run artifact; the superseded
26-release version survives in git history and its hash is pinned by the
failure receipt, and keeping a known-unusable plan active would invite
accidental reuse. The revised plan (sha256
`87e216b3ad56bc082a11c801a41ba968d5391b9ee77db83059ac4e25252abf1c`)
declares:

- **25 releases, 2020q1 through 2026q1** — every FSDS release measured
  available;
- **`observed_through` = 2026-03-31**, on the last-available-release
  quarter-end basis, with the 404 evidence recorded verbatim in the basis;
- the classification consequence, stated in the plan and enforced by the
  committed ADR-081 boundary rule without any code change: **every FRAME
  absence filed after 2026-03-31 (all of Q2 2026) is
  `right_boundary_unobserved`, never FSDS/XBRL noncoverage** — publication
  reality now forces the shape previously rejected as a choice;
- unchanged boundaries: possessing the plan authorizes nothing, and DERA
  remains an independent FRAME validation source only, never eligibility or
  universe input.

**Successor path.** Once DERA publishes 2026q2, a successor plan revision
may add it and restore `observed_through` 2026-06-30 under ADR-083's
acceptance-rule basis — only via its own reviewed revision and separately
authorized acquisition.

**Deferred, named so it is not mistaken for done.** Committing this
revision; the 25-release rerun under a new run-id; the real validation of
the full FRAME_v1.1-draft artifact through the ADR-081 gate; the FRAME_v1
freeze decision.

**Scope.** Modified only: `configs/dera_fsds_full_request_plan.json`
(in-place revision), one offline test in
`tests/universe/test_dera_acquisition.py`, and ADR-083's superseded
paragraphs. No new files, no code, no schema, no registry bump, no
REPO_MANIFEST or count-test change, no pinned-hash rebaseline, and no
deletion or reuse of any `data/runs` artifact.

## ADR-085 — The real validation refines the gate: truncation, drift, and adjudication (ADR-081, ADR-084)

**The measurement that forces this entry.** The first real FRAME-versus-DERA
validation (run `frame-dera-validation-full-v11-2020q1-2026q1-20260816`,
manifest sha256
`d9f950ceac54e4ca922e8799f2ecd0cc38e1ed7c480f5f9cf7ea5e90816ef796`) failed
its gate on 45 anomalous rows out of roughly 220,000 inputs, with 47,535
exact matches, zero registrant contradictions across 47,573 expanded pairs,
and all six reconciliation identities true. Read-only characterization
resolved the 45 rows into three classes:

- **Truncation (7 parse failures).** FSDS hard-truncates `aciks` at ~120
  characters without a PARTIAL token (one CIK severed mid-token), while
  `nciks` keeps the true count — all seven on out-of-scope registration
  forms here, but possible in scope in principle.
- **Timing drift (33 mismatches).** Filed-date drift of exactly +1 day (30
  cases) or +3 days (3 cases, Friday→Monday), always DERA-later, never
  DERA-earlier, never a form mismatch — the EDGAR next-business-day
  signature. This is the evidence ADR-081 reserved judgment for.
- **Replaced submissions (2 mismatch outliers + 3 DERA-only orphans).**
  EDGAR submissions deleted and re-filed: the point-in-time FSDS retains
  the original while the regenerated index carries only the replacement,
  backdated to the original date. Proven end-to-end for Salesforce's FY2021
  10-K (original `0001108524-21-000014` deleted; replacement
  `0001108524-22-000008` backdated to 2021-03-17; DERA carries both) and
  for Bally's FY2021 10-K (same accession re-accepted 2022-08-08 with FSDS
  `prevrpt=1` against index date 2022-03-01).

**Decision A — truncation is implicit partial.** A non-PARTIAL row with
`nciks > 1 + declared` parses as valid, marked
`registrant_set_truncated`, and is handled like PARTIAL: declared pairs
compared, omissions never inferred, affected comparisons non-gating and
excluded from noncoverage rates, all counted. Genuinely impossible counts
stay fatal: `nciks < 1` and `nciks < 1 + declared` remain parse failures,
and `dera_parse_failures > 0` still gates real malformation.

**Decision B — bounded drift is report-only.** With matching CIK,
accession, and form, DERA-later drift of at most
`FILED_DATE_DRIFT_BOUND_DAYS = 3` days is the report-only
`filed_date_drift` category; the bound is recorded in every validation
manifest's counts. DERA-earlier drift, drift beyond the bound, and any form
mismatch remain gating identity mismatches.

**Decision C — evidence-backed adjudication.** The committed, append-only
`configs/dera_validation_adjudications.json` records replaced-submission
events only, each with CIK, accession, direction, reason, replacement
accession, backdating evidence, ADR reference, and an evidence note. The
validator loads it fail-closed from its fixed path, reclassifies
exactly-matching contradictions into the non-gating
`dera_only_adjudicated` / `identity_adjudicated` categories, and records
the file's SHA-256, record count, and every applied record in the manifest
samples. Three records are committed: Salesforce's two event sides and
Bally's re-acceptance. **The samples surface is a bounded bridge**: with
five or fewer records it fits the existing ≤10-item sample arrays, and if
adjudications ever exceed that cap or become a regular surface, a schema
successor is required rather than further bridging.

**Decision D — no evidence, no adjudication.** Two measured events are
deliberately NOT adjudicated and remain gating, reported unresolved:
Vodafone (`0000839923`, `0001104659-22-116238`), a deleted late-filed
FY2018 20-F (period 2018-03-31) with no replacement accession, and CASI
Pharmaceuticals (`0000895051`, `0001558370-23-006754`), a 20-F filed after
the entity's Form 15-12G deregistration of 2023-03-22 with succession under
a different CIK. The post-ADR-085 validation rerun is therefore expected to
fail its gate with `annual_dera_only_unexplained = 2` until those two
receive their own reviewed decision — that is the gate working, not a
defect.

**Boundaries.** DERA remains an independent FRAME validation source only,
never eligibility or universe input. Every existing `data/runs` artifact —
both DERA acquisitions, the failed 26-release run, the FRAME runs, and the
failed validation itself — remains immutable and ignored.

**Scope.** New: `configs/dera_validation_adjudications.json`. Modified:
`frame_dera_validation.py` (truncation rule, drift category and bound,
adjudication consumption and hash recording), its test file, the
`dera_fsds` fixture bundle (one committed truncated out-of-scope SUB row
and the regenerated gold) plus the regenerated
`evals/fixtures/dera_fsds_archives/dera-2022q4.zip` whose `sub.txt` member
must stay byte-identical to the committed TSV, `REPO_MANIFEST.md`
(663 → 664) and its three count regression tests. No schema change, no
registry bump, no pinned-hash rebaseline. Deferred: the validation rerun
under a new run-id and the FRAME_v1 freeze decision, each separately
authorized.

## ADR-086 — The last two residuals close: a succession replacement and an evidenced deletion (ADR-085)

The ADR-085 validation rerun
(`frame-dera-validation-full-v11-2020q1-2026q1-adr085-20260816`, manifest
sha256
`d789aaebd71aac2b9c61ce6be5d542e8a4824f92a1ca853416650217a60163df`) failed
on exactly one condition — `annual_dera_only_unexplained = 2` — with
47,535 matches, 33 report-only drift cases, 3 applied adjudications, zero
identity mismatches, zero parse failures, and every reconciliation identity
true. This entry closes those two rows.

**CASI Pharmaceuticals (0000895051, 0001558370-23-006754) — a replaced
submission across a CIK succession, adjudicated under the existing ADR-085
reason.** Read-only index evidence: the same-day replacement
`0001558370-23-006757` (20-F, filed 2023-04-26, same filing agent, three
accessions later) exists under successor CIK 1962738 — the Cayman entity
CASI redomiciled into — while the old Delaware CIK's Form 15-12G
deregistration of 2023-03-22 (`0001104659-23-035268`) is index-confirmed
and no current index row carries the old accession. **Nothing is missing
from the FRAME denominator**: the FY2022 20-F is in the frame at
`(1962738, 0001558370-23-006757)`.

**Vodafone (0000839923, 0001104659-22-116238) — an evidenced deletion,
requiring the one new reason `deleted_submission`.** The row exists in
point-in-time FSDS 2022q4 (accepted 2022-11-09, period 2018-03-31, fy
2017 — a late-filed historical annual report) and is absent from all 26
current-regeneration index files while every neighboring Vodafone filing is
present; no replacement accession exists anywhere. The construct rationale:
the FRAME denominator is the **current authoritative index**, and a deleted
filing's absence from it is correctness, not omission — an evidenced
deletion is a DERA-side point-in-time artifact, so explaining it is not a
waiver. The reason carries a strict per-reason rule enforced fail-closed:
`replaced_submission` requires a non-null, normalizable
`replacement_accession`; `deleted_submission` requires
`replacement_accession` null. Its content period predating the study window
means no in-window frame observation is affected either way.

**Materiality.** The two rows are 0.0036% of 56,271 FRAME annual records
and 0.0042% of 47,573 DERA expanded pairs, and neither corresponds to a
missing in-window frame observation.

**Bridge bound reached.** The adjudication file now carries **five
records — exactly the bounded-bridge cap ADR-085 recorded.** The next
adjudication, whatever its merits, requires the schema successor for the
validation manifest's adjudication surface; no further bridging is
permitted. A committed test pins the five records' exact keys and both
reasons.

**Expected rerun outcome.** With deterministic inputs, the next separately
authorized validation rerun must pass its gate: `annual_dera_only_unexplained
= 0`, `annual_dera_only_adjudicated = 3`, `annual_identity_adjudicated =
2`, `adjudications_applied = 5`, all reconciliation identities true. The
FRAME_v1 freeze then cites a gate-passing validation manifest.

**Boundaries.** DERA remains an independent FRAME validation source only,
never eligibility or universe input; every `data/runs` artifact remains
immutable and ignored.

**Scope.** Modified only: `configs/dera_validation_adjudications.json`
(two records appended; description updated),
`frame_dera_validation.py` (reason admission and the per-reason replacement
rule; docstring), its test file, and the fixture gold's adjudication-record
count. No new files, no schema change, no registry bump, no REPO_MANIFEST
or count-test change, no pinned-hash rebaseline. Deferred: the gate-passing
validation rerun and the FRAME_v1 freeze decision, each separately
authorized.

## ADR-087 — FRAME_v1 freeze: the released frame artifact and its validation evidence

**Status.** Accepted. Closes THESIS_EXECUTION_PLAN W1.

**What freezing is.** Freezing designates an existing immutable run artifact
as the released frame; nothing is rebuilt and nothing under `data/runs` is
modified. FRAME_v1 is the run `frame-live-full-v11-2020q1-2026q2-20260815`,
whose manifest (SHA-256
`5203660fe4c6093041383284ad36614a5ac4d7116a1e1259138e14ebde164cee`) carries
the code-owned build label `FRAME_v1.1-draft`. The committed freeze record
`configs/frame_v1_freeze.json` (`frame_v1_freeze@0.1.0`, the
adjudications-file pattern: a contract-declaring config validated by tests,
no `schemas/` entry) maps the released name onto that build and pins the run
identity, the manifest hash, the six output-file hashes, the recorded
provenance (`code_revision 215557d0…`, `project_config_hash efc1b4a4…`), the
W0-frozen window 2020-01-01..2026-06-30, the form scopes 10-K/10-KT and
20-F/40-F, and the final counts. Deeper chain links — the EDGAR acquisition
manifest and request plan — are already hash-chained inside the pinned frame
manifest and are not repeated.

**The code label does not change.**
`FRAME_VERSION_ON_ACQUIRED_BUILD = "FRAME_v1.1-draft"` labels *future*
builds, which are correctly drafts until a freeze record designates one; the
constant's own comment anticipated exactly this division. Corrections create
FRAME_v1.x through a new run and a successor freeze record, never by editing
this one (Rule 4: immutable raw sources; no silent repair).

**Final FRAME_v1 counts.** 26 index files; 7,694,062 data lines, all parsed,
zero parse failures; 510 integrity-failure rows; zero duplicates; 7,693,552
admitted; **48,793 domestic annual filer-accession records** and **7,478 FPI
extension records** (denominator 56,271); 6,795 amendment links (6,692 with a
deterministic candidate, 103 unmatched); 7,630,486 out-of-scope-form rows;
zero out-of-window rows.

**Validation evidence.** The freeze cites the gate-passing DERA validation
run `frame-dera-validation-full-v11-2020q1-2026q1-adr086-20260816` (manifest
SHA-256 `6154fe43f6a2577f2f3bdee2736c0b45299947568ed46f0b80c9d4965899af48`):
`gate_status = pass`, no failed conditions, zero unexplained dera-only rows
in both strata, zero identity mismatches, 47,535 annual matches, the five
committed adjudications (file SHA-256 `61407826…`) all applied
(`identity_adjudicated = 2`, `dera_only_adjudicated = 3`), and all six
reconciliation identities true (ADR-081, ADR-085, ADR-086). DERA is observed
through 2026-03-31 (ADR-084); the 1,169 annual right-boundary rows are
unobserved, not contradicted, and a future 2026q2 revalidation under a
successor plan is optional and does not reopen this freeze.

**Out of scope.** FRAME_v1 is the denominator only; nothing is excluded from
it. Universe filtering and issuer flags (Stage 00B), Item 1 packet creation,
prompts, product/capability/task extraction, and scoring/measurement all
remain downstream, each behind its own spec and authorization.
`universe.release_status: draft_pending_sentinel` in `configs/project.yaml`
gates the universe stage, not the frame, and is untouched.

**Scope.** Added: `configs/frame_v1_freeze.json` and its guard-test file
`tests/universe/test_frame_freeze.py` (all assertions run against the
committed record; one read-only verification test recomputes the two
manifest hashes and skips where `data/runs` is absent). Modified:
`REPO_MANIFEST.md` (664 → 666) and the three manifest count tests. No
`src/`, `schemas/`, fixture, pipeline, or `configs/project.yaml` change; the
schema registry stays at 0.27.0 with 60 entries and no pinned hash is
rebaselined.

## ADR-088 — W2-A Stage 00B firm-level baseline carrier

**Status.** Accepted. First increment after the FRAME_v1 freeze (ADR-087)
toward UNIVERSE_v1.

**What the carrier is.** `baseline_carrier.py` derives one row per
(stratum, CIK) from a completed FRAME run: the firm's baseline filing
selected against the W0-frozen cutoff, its cohort assignment, and its
filing-history summary. The frame is consumed read-only through its
manifest — schema-validated, every output-artifact hash verified before
parsing — and the committed freeze record is cited so every carrier
manifest records whether the consumed frame is the frozen FRAME_v1
(`frame_freeze.frame_is_frozen_frame`). The manifest contract is
`universe_baseline_carrier_manifest@0.1.0`.

**Baseline selection.** `universe.baseline_cutoff` (2022-11-29, ADR-077) is
read from `configs/project.yaml`, never CLI-supplied, and must lie inside
the frame's filing window (refused otherwise). Per firm: the latest annual
filing with filing date on or before the cutoff → `baseline_candidate`;
firms whose earliest annual filing postdates the cutoff →
`post_baseline_entrant`, a retained separate cohort, never dropped and
never pooled. Same-day ties break deterministically to the highest
accession number and are flagged `baseline_tie_broken`, visible in counts
and samples. `no_eligible_filing` is structurally unreachable from FRAME_v1
and its count is reconciliation-checked to zero.

**Strata are never merged.** Domestic and FPI-extension records group
within stratum; a CIK appearing in both strata yields two rows flagged
`dual_stratum`, a surfaced condition, not a resolved one.

**No exclusions, and no issuer_filters call.** The EDGAR full index carries
no cover-page issuer flags and no SIC, so no deterministic issuer exclusion
is derivable in this increment; every frame filer is retained with
`issuer_status: "unknown"` and basis `cover_page_evidence_not_yet_observed`.
`issuer_filters.py` is deliberately not imported: its decision model
expects a `company_id` the frame does not carry, and the carrier must not
fabricate one or create a hidden dependency. Name-pattern signals
("…ACQUISITION CORP", "…FUND") are not used even as candidate flags — a
name is wording, not evidence (Rule 2). Real Stage 00B exclusions arrive
with filing-document cover-page evidence in a later increment, which will
also settle the `company_id` seam.

**DERA boundary.** DERA FSDS plays no role: the carrier imports no DERA
module, reads no DERA-derived field, and a test pins the import ban. DERA
remains a frame validation source only (ADR-081/085/086).

**Reconciliation and immutability.** Six count identities (frame-manifest
consistency, stratum sums, cohort partition, per-firm filing sums, cutoff
split, exact filer-key coverage) must all hold or the run is refused with
nothing written. Run directories are write-once; reruns of an existing
run-id are refused; `write_bytes_once` carries both outputs.

**Downstream (not this increment).** Stage 00C baseline evidence packets —
the first live filing-document download, under its own request plan, canary,
and authorization — then the 00D screen (first prompt use, behind the
W3/W4 gates), 00E classification, 00F tiers, 00G–00I adjudication, audit,
and the UNIVERSE_v1 freeze. Product/capability/task extraction, scoring,
the AI-mechanism measure, and sample construction remain governed by their
own specs.

**Scope.** Added: the carrier module, its manifest schema, its test file,
and the fixture carrier gold (`expected_carrier.json`; the committed index
fixtures already span both cohorts and the combined-filing case, so no
fixture row changed). Modified: the pipeline entrypoint (sixth mode
`baseline-carrier`, no new CLI flag), the schema registry (0.27.0 → 0.28.0,
60 → 61 entries) with both pinned-hash rebaselines, `REPO_MANIFEST.md`
(666 → 670), and the three manifest count tests. `data/runs` untouched; the
real carrier run over the frozen FRAME_v1 is a separately authorized
execution.

## ADR-089 — W2-B baseline filing-document acquisition

**Status.** Accepted. First increment after the baseline carrier (ADR-088)
toward Stage 00C packets. Fixture-first; the live canary is separately
authorized.

**Scope of the artifact.** Documents only. This runner acquires the baseline
annual-report document of planned baseline candidates and preserves the raw
bytes write-once with receipts. No section extraction, no packet, no
high-recall screen, no classification, no tier, no model call. DERA is not
imported and plays no role.

**URL derivation — the corrected contract.** `sec_filename` from the FRAME
row is provenance and a validation input; it is **never** concatenated into
a URL. An earlier draft of this plan proposed
`https://www.sec.gov/Archives/` + `sec_filename`; that form was withdrawn
before implementation. Each planned carrier row must carry a `sec_filename`
of the full-index shape `edgar/data/<cik>/<accession>.txt`, and three
separate refusals apply: malformed shape, embedded CIK unequal to the row
CIK, embedded accession unequal to the entry accession. The requested URL is
then derived in the SEC filing-directory form already used on the Pilot 0
path:

```text
https://www.sec.gov/Archives/edgar/data/<cik_without_leading_zeros>/<accession_without_dashes>/<accession_with_dashes>.txt
```

**Document unit and shared accessions.** The unit is the accession, not the
firm. A combined filing selected by several carrier rows is requested once
and mapped to every one of them; `firm_document_mapping` carries the full
mapping, and the plan itself must prove it through per-entry `carrier_rows`.
The directory CIK is the **lowest** CIK among the sharing rows. The
accession's own 10-digit prefix can never be used: it is frequently a filing
agent that owns no EDGAR directory. Both cases are real in the measured
cohort and both are in the canary — the 10-K group `0001437749-22-027522`
has a filing-agent prefix owning no directory, and the 40-F group
`0001232384-22-000014` has a prefix that *is* a filer but not the lowest
sharing CIK.

**Cohort.** `baseline_candidates` only, enforced by the plan grammar.
Post-baseline entrants carry no baseline accession, so there is nothing to
acquire; this is a structural consequence of the carrier, not a preference.

**Byte ceiling: the download is bounded, not just the write.**
`max_document_bytes` is an explicit, required plan field — never defaulted
in code — set to 268435456 (256 MiB) in the committed canary plan. A first
implementation checked the ceiling *after* the transport had materialized
the whole response body; that proved only "never persist over-ceiling
bytes", while an unexpectedly huge submission would still be downloaded in
full and held in memory. **That check was withdrawn as the enforcement
mechanism before any live request was made**, and survives only as a
defensive assertion against a transport that ignores its own bound.

Enforcement now lives in the transport, with this contract (chunk size
65536):

- a parseable `Content-Length` strictly greater than the ceiling refuses
  before a single body chunk is consumed. The header lookup is explicitly
  case-insensitive — HTTP header names fold case, a plain `dict` does not,
  and an adapted mapping may preserve whatever casing the server sent;
- an absent, empty, non-numeric, or negative `Content-Length` is treated as
  *absent*: never fatal, never a bypass. A malformed header is not evidence
  of size, and the stream check below is authoritative;
- chunks are consumed with a running count, and the first chunk that would
  cross the ceiling is never appended — not even a partial slice — so the
  retained body is always `<= max_document_bytes`;
- transport-level received bytes may reach `max_document_bytes +
  stream_chunk_bytes`, because one chunk may straddle the limit. That bound
  is stated in the contract, recorded in each manifest's
  `ceiling_enforcement`, and asserted in tests;
- a ceiling refusal is terminal and never retried;
- a non-200 status and a terminal-URL mismatch are refused *before* any body
  chunk is read. Both are classified by the runner, so a 200 served from a
  URL other than the one requested must not first be read up to the ceiling;
  the mismatching URL is returned unchanged so the runner's existing
  `terminal_url_mismatch` receipt is unaffected.

**Streaming resource lifetime.** The seam is an explicit streaming response
exposing status, final URL, headers, chunk iteration, and an idempotent
`close()`; returning a naked iterator from an exited `with httpx.Client(...)`
block would hand back either an already-closed stream or a leaked
connection, so the client and stream contexts are entered manually and held
until `close()`. The document transport closes in a `finally` on every path:
accepted response, preflight refusal, chunk-limit refusal, redirect,
terminal-URL mismatch, non-200, send exception, and each retry transition.
Tests assert closure on all of them; "the iterator was not exhausted" is not
accepted as evidence.

**Where the streaming code lives, and what did not change.** The one
httpx-originating streaming send is added to `sec_index_transport.py`,
already the single module allowed to originate SEC network requests, so the
**repository-wide httpx allowlist stays at three modules** — a new
top-level importer would have forced widening a security guard to four for
no benefit. All policy (preflight, chunk bounding, lifetime, spacing/retry
reuse) lives in the new `sec_document_transport.py`, which imports no HTTP
library. The document transport declares its **own** contract and identity,
so its canonical hash necessarily differs from the index one;
`SEC_LIVE_TRANSPORT_CONTRACT`, its identity, `_httpx_send`, and
`make_sec_live_transport` are byte-identical, and no index or DERA
acquisition's recorded provenance changes. `max_document_bytes` is
plan-owned and per-run, so it is deliberately not part of the contract and
does not perturb the hash. The runner binds the two by requiring
`transport_max_bytes` to equal the plan ceiling, refusing the run before any
request otherwise.

Complete-submission text files carry exhibits and inline XBRL, so whether
the full run keeps whole submissions or moves to a two-hop primary-document
strategy is a decision the canary's measured sizes will settle, not one
taken here.

**Canary selection.** Twelve documents mapping sixteen carrier rows, derived
deterministically from the carrier run pinned in the plan's provenance
(`universe-baseline-carrier-frame-v1-20260816`, manifest SHA-256
`50a2582f…`, freeze record SHA-256 `27eb6d23…`): per form, the lowest-CIK
regular documents plus the lowest-CIK shared-accession group. Measured
distribution of shared groups among the 9,916 candidates (139 groups
covering 336 rows): 10-K 134, 20-F 3, 40-F 2, **10-KT 0** — so the declared
fallback applies to exactly one form and 10-KT contributes three regular
documents. Not covered, and stated rather than implied: no tie-broken firm
falls in the selection, and shared-group behaviour for 10-KT is unobservable
because no such group exists. The selection also happens to include CIK
9631, one of the 122 dual-stratum firms, whose 40-F baseline is a different
accession from its domestic 10-K baseline — so the canary confirms
per-stratum rows resolve to distinct documents rather than collapsing by
CIK.

**Failure and resume policy.** All-or-nothing: the first failed document
ends the run with a write-once failure receipt and no acquisition manifest;
manifest presence remains the sole mark of an authoritative acquisition.
There is deliberately **no resume and no batching** here. Batched,
resumable acquisition of the full candidate cohort is the W3 download-queue
increment, and the full 9,916-candidate acquisition is not authorized by
this ADR: it requires canary volume evidence, a projected byte budget, the
queue, its own derived plan, and its own run authorization.

**Transport.** The committed `sec_live` contract is reused unchanged through
the existing injected-transport boundary; the universe package still
contains no network code and the three-module httpx allowlist is untouched.
Fixture runs write the v0.1 manifest, `sec_live` runs the v0.2 successor
that additionally pins the embedded transport contract.

**Scope.** Added: the acquisition module, the bounded document transport,
their v0.1 and v0.2 manifest schemas, the committed canary request plan, the
synthetic document fixture bundle (plan, two submissions, gold), and the
acquisition test file. Modified: `sec_index_transport.py` (additive
streaming send and a corrected module docstring), the pipeline entrypoint
(seventh mode `acquire-docs`, no new CLI flag, plus the stale
"four modes" count and the `--request-plan` / `--replay-dir` / `--transport`
help text that named only `acquire-index`), the live-transport tests
(no-regression pins), the schema registry (0.28.0 → 0.29.0, 61 → 63 entries)
with both pinned-hash rebaselines, `REPO_MANIFEST.md` (670 → 680), and the
three manifest count tests. Both document manifest schemas gained
`ceiling_enforcement` and per-document `declared_content_length`; because
both files are new in this increment and uncommitted, that is authoring
rather than a governed schema change, and no successor version is required.
`data/runs` untouched; no live request has been made.

## ADR-090 — W2-C-alpha: the filing-index metadata probe

**Status.** Accepted. Fixture-first capability only; the three-request live
probe is separately authorized and has not been run.

**Why a probe at all.** Building baseline evidence packets for the domestic
candidate cohort by downloading whole SEC submissions is not viable: the
completed 12-document canary (ADR-089) measured 508.3 MB for twelve filings,
one of them 213.5 MB — 79.5% of the 256 MiB ceiling. Reading those same
submissions offline shows the primary annual-report document is **8.8% of
the bytes**, an 11.4× reduction, with the largest primary at 9.27 MB. A
two-hop route — filing-directory metadata, then the selected primary — is
therefore worth building, but it depends entirely on there being a
deterministic, type-bearing metadata source. This increment proves or
refutes that, and does nothing else.

**Two candidates eliminated offline, before any request.** `FilingSummary.xml`
is declared `TYPE=XML` in all twelve canary filings and names no form type;
it identifies nothing. The SGML `<SEC-HEADER>` block carries no per-document
list at all — roughly 1 KB of filer metadata — so `-index-headers.html`,
which renders that header, cannot carry the mapping either. The
`<TYPE>`/`<FILENAME>` pairs that do select a primary uniquely (12/12) exist
only inside the full submission, which the two-hop route must never fetch.

**What is probed, and only that.** One endpoint:
`…/Archives/edgar/data/<cik_without_leading_zeros>/<accession_without_dashes>/<accession_with_dashes>-index.htm`.
Table selection is identity first, shape second. The parser requires the SEC
Document Format Files table **identity** — the table's own `summary`
attribute, or an explicitly associated heading — and only then validates that
the identified table declares Document and Type columns. Header cells alone
never identify the table: the same index page carries a Data Files table with
the identical two columns, nothing guarantees it appears second, and a
shape-only parser would select a plausible annual-form row out of it. A page
where no table claims the identity, or where more than one does, or where the
identified table lacks those columns, is refused as `metadata_unparseable`.
The primary is then the single **HTML** row of that table whose declared type
equals the planned annual form. Eligibility is decided before cardinality:
declared Type first, then the HTML suffix, and uniqueness is required **among
the form-matching HTML candidates only**. A same-form non-HTML companion — a
PDF rendering of the very same filing — is **not an eligible primary
candidate** and therefore cannot make a filing ambiguous. Superseded by
ADR-096, which records the measurement that forced this ordering. **Filename
convention is never used**: the measured corpus contains `form10-kt.htm` and
`lub-20220531.htm`, which no ticker-and-date pattern matches. Zero matches,
more than one **HTML** match, no HTML among the matches, an unparseable page, a
transport-level failure, a ceiling refusal, or a filename disagreeing with
the plan's recorded ground truth each refuse with a distinct reason code and
end the run with a write-once receipt and no manifest. `index.json` is a
**separately authorized fallback** and is never requested by this module; a
test asserts that against the URLs actually requested rather than against
prose.

**Ground truth is local.** All three committed live entries are domestic,
single-filer accessions whose full submissions are already on disk from the
ADR-089 canary, so the probe's selection is checked against known primaries
(`air-20220531x10k.htm`, `abt-20211231x10k.htm`, `form10-kt.htm`) rather
than against belief. The third is included precisely because its filename
defeats every convention.

**Ceiling.** `max_metadata_bytes` is an explicit, required plan field set to
8388608 (8 MiB) — never defaulted in code. The transport is constructed with
exactly that bound and the runner refuses any mismatch **before a request is
made**; enforcement itself is the committed bounded streaming transport
(ADR-089), reused unchanged, and the manifest records both the plan ceiling
and the mechanism applied.

**Fixture/live contract separation.** Two schemas, never one widened
contract: v0.1 admits `fixture_replay` only and carries no embedded
transport contract; the v0.2 `sec_live` successor requires the embedded
contract alongside its recorded canonical hash. Tests assert each schema
**rejects** the other transport's manifest.

**Scope.** Added: the probe module, its v0.1 and v0.2 manifest schemas, the
committed three-request probe plan, the synthetic index-page fixture bundle
(plan, two pages, gold), and the probe test file — nine paths. Modified: the
pipeline entrypoint (one new mode, `probe-filing-index`, no new CLI flag),
the schema registry (0.29.0 → 0.30.0, 63 → 65 entries) with both pinned-hash
rebaselines, `REPO_MANIFEST.md` (680 → 689), the three manifest count tests,
and this log — nine paths. **Not in this increment**: packet contracts,
primary-document acquisition, any `ingestion` change, any packet CLI mode,
and any live request. The full-submission acquisition path is untouched, so
the completed canary stays reproducible.

**Deliberately unchanged and carried forward.** Domestic annual forms only
(10-K, 10-KT); the FPI extension cohort is preserved, not probed and not
excluded. When packets are later built, cover-page absence is **non-fatal**
— recorded through `missing_sections`, never a failure and never an
exclusion — while missing Item 1 remains a packet failure, and issuer status
stays `unknown` where cover-page evidence is absent, recorded as the
deferred Stage 00B limitation. The orchestration boundary stands:
`ingestion` may import `universe`, `universe` never imports `ingestion`, and
the Stage-00 CLI wires both without violating either guard.

**Canary finding: the filename comes from the link, not the rendered text.**
The first authorized live probe (`filing-index-probe-frame-v1-20260816`)
**failed** on the first of its three URLs, with `non_html_primary`, and its
immutable failure receipt is retained as evidence. The refusal was
informative rather than a refutation: the endpoint returned 200, the
Document Format Files table was correctly identified, and exactly one row
declared type `10-K` — but the parser read the row's *rendered* cell text,
which SEC renders as `air-20220531x10k.htm iXBRL`, appending an inline-XBRL
badge. The trailing badge defeated the HTML-suffix check. The synthetic
fixtures had carried no badge, which is why they passed while the live page
did not.

The corrected rule: **a row's filename is derived from the parsed path of its
Document-cell link target**, never from visible text, which is presentation
only. The href is parsed structurally with the standard library, never
scanned for substrings, and both link shapes must be relative or on an
approved SEC host (`sec.gov` / `www.sec.gov`).

A **direct archive link** yields the last segment of its parsed path, and its
query and fragment are ignored entirely, so `…/actual.htm?doc=wrong.htm`
yields `actual.htm`. Its path must begin `/Archives/`: a filing document
lives nowhere else, so an off-host link or an SEC path outside the archive is
refused **even when its basename equals the expected primary document** — a
matching name is not evidence of a legitimate source.

The **inline-XBRL viewer link** is recognized *only* when the parsed path is
**exactly** `/ix`, because that endpoint's path tail is `ix` rather than a
document, so its `doc` parameter is authoritative there and nowhere else. The
rule is bound to that one endpoint, **not to any href containing `doc=`** and
not to a near-miss path: `/ix/`, `/ixviewer`, `/other/ix` and `/notix` are
ordinary links, and their `doc` value never resolves. A viewer link whose
`doc` parameter is missing, blank, repeated, off-host, or outside the archive
is refused, as is any unsupported scheme such as `javascript:` or `data:`. Fail-closed behaviour is unchanged
and extended: a Document cell with no usable link, href, or path basename is
refused as `metadata_unparseable` rather than reconstructed from text;
selection
remains exactly one row whose declared type equals the planned form; and the
href-derived basename must still be HTML and still equal the plan's
hash-bound expected filename. Rendered text that merely *looks* like an HTML
filename cannot rescue a non-HTML link target, and a badge-bearing expected
filename is refused at plan load. Both committed fixture pages now carry
real hrefs, and page one reproduces the live condition permanently: iXBRL
badge plus `/ix?doc=` viewer link.

**Decision gate.** A 3/3 pass makes the probe manifest the cited evidence
for the next increment (packet contracts, then extraction, then
primary-document acquisition, then a packet mode and its canary). Any
failure stops the direction here; `index.json` then becomes a separately
authorized fallback probe under the same success condition. The first live
attempt did not pass, so no probe evidence exists yet; the corrected probe
run is a separate authorization after this correction is reviewed.

## ADR-091 — W2-C-beta: baseline packet contracts

**Status.** Accepted. Fixture-first; no acquisition, no live request, no model
call. Builds Stage 00C baseline evidence packets from primary documents that
are already local and hash-verified.

**Where the code lives, and why it must.** `universe` may not import
`ingestion` (AST-enforced), while `ingestion → universe` is the documented
direction, and the span/passage machinery this needs — `find_item_one_span`,
`build_passages_v4` — is in `ingestion/normalize.py`. So extraction lives in
`ingestion/baseline_packet.py` and the contracts in `universe/models.py`,
which also gives the builder ingestion's no-network and no-URL-literal guards
for free: it *cannot* fetch a document.

**Three governed contracts.**
`baseline_primary_document_bundle@0.1.0` is the builder's input — a local
directory plus a manifest — and it is governed rather than informal because a
later acquisition increment must emit exactly it.
`universe_baseline_packet@0.1.0` is the packet record, and
`baseline_packet_manifest@0.1.0` the run record. Registry 0.30.0 → 0.31.0,
65 → 68 entries.

**Route validation is not selection evidence.** The 3/3 filing-index probe
proved a URL grammar for *its own three accessions*. It is recorded in every
packet as `route_validation`, carrying a note that says exactly that, and it
is never allowed to stand for per-firm selection. Per-document evidence is
`selection_provenance` — filing-index URL and response hash, selected
document, primary URL — required on every bundle entry, so a packet always
cites how *its* bytes were chosen. A bundle entry missing any of those fields
refuses the run.

**End boundary: a priority, not a single item.** `find_item_one_span` ends
only at Item 1A, so a filing that omits risk factors — smaller reporting
companies may — was unreadable rather than differently shaped. The successor
`find_item_one_span_v2` keeps Item 1A as its first tier and falls back in
filing order to **Item 1B**, then **Item 2**, recording `end_boundary_kind`.
The v1 function is left byte-identical: its callers must not shift.
Trustworthiness is not loosened to buy that reach — a candidate must open a
block (the cross-reference guard that ADR-066 measured, where seven inline
"see Part I, Item 1A" phrases would have cut a span by 44%) and lie after the
body heading, and the body heading is the *last* qualifying Item 1 match — so
when a body heading exists, a table-of-contents entry can never win, because
the TOC is printed first. **Two surviving candidates in one tier
are ambiguous and refuse**, rather than taking the earlier one as v1's
`min()` did: a second block-opening Item 1A after the body is evidence the
document is not shaped as assumed.

**What a v0.1 packet contains, and what it refuses to guess.** The full
normalized Item 1 span, every passage classified `ITEM1_OVERVIEW`.
`COVER_PAGE` is recorded **explicitly missing** and all five issuer flags are
`unknown` **cohort-wide**: this route retrieves no SGML header and no
inline-XBRL cover-fact parser exists, and neither is being added here. Silence
is never evidence, so a flag is `true`/`false` only from a directly observed
source fact. `PRODUCTS_SERVICES`, `CUSTOMERS`, `SEGMENTS_MATERIALITY` and
`TECHNOLOGY_DELIVERY` are recorded missing rather than inferred: deterministic
subsection tagging has not been measured, and a later measured increment may
add it. Cover-page absence is **not** a packet failure, and no firm is ever
excluded — a document that cannot yield a packet is recorded as a failure with
its reason (`missing_item_one`, `ambiguous_end_boundary`, `no_end_boundary`,
`empty_item_one_span`, `temporal_mismatch`).

**Identity and hashing.** `source_id` is
`sec-primary:<cik>:<accession>:<selected_document>` — a stable document
identity, deliberately **not** the mutable raw SHA-256, so passage identity
survives a re-download of identical content and an unrelated edit elsewhere
in the document; a test proves that regression is meaningful.
`source_sha256` travels separately as mandatory provenance. `packet_sha256`
covers the canonical JSON serialization (`sort_keys`, `(",", ":")`,
`ensure_ascii=False`, UTF-8) **with the hash field omitted**, and
`packet_byte_size` measures that serialization with *both* self-referential
fields omitted, so neither definition is circular.

**No packet cap.** Sizes are recorded — total, max, mean — for the later
Canary B decision; the raw-document acquisition ceiling (ADR-089) remains the
only size bound.

**Scope and its consequence.** Domestic `10-K`/`10-KT` only; the bundle
grammar refuses `20-F`/`40-F` naming the FPI extension cohort as preserved by
the frame and carrier, neither handled nor excluded. **A later real
primary-document Canary B must include at least one 10-KT**: the v4 detectors
were measured by ADR-074 on fifteen 10-K filings from large software filers,
so 10-KT support is presently fixture-evidenced only.

**A limitation found while building the fixtures, stated precisely.** The
last-qualifying rule is a defence against the table of contents *only while a
later body heading exists*. Where a document's **only** qualifying Item 1
match is its TOC entry, that entry is the last qualifying match, so the span
is anchored on the TOC rather than refused — the TOC line opens a block like
any other, and the rule has nothing better to choose. The two statements are
not in tension: TOC entries lose to a real body heading, and win only when no
body heading exists at all. No threshold is invented to catch that case — a
minimum-span heuristic would be unmeasured — so it is recorded here as an
explicit Canary-B limitation, to be measured against real filings before the
full cohort runs.

**Input integrity.** A bundle is verified fail-closed before anything is
parsed, and nothing is ever repaired from what was observed. Filenames must be
safe leaf names — no absolute path, separator, dot segment, traversal or
drive/home prefix — checked **before the filesystem is touched**, so a
traversal target that happens to exist is refused on its name rather than
opened. ``local_filename`` and ``selected_document`` stay distinct fields and
are never required to be equal: the document SEC selected and the file this
bundle stores it as are separate facts, and packet identity follows the
selected document. Each document's declared ``source_byte_length`` **and**
``source_sha256`` are both verified against the bytes on disk; a declared
length that disagrees with the bytes refuses the run even when the hash
matches.

**Scope.** Added: the packet builder, three schemas, the six-document
synthetic bundle with its manifest and gold, and the packet test file —
thirteen paths. Modified: `ingestion/normalize.py` (adds
`find_item_one_span_v2`; v1 unchanged), `universe/models.py` (three records
beside the untouched `BaselineEvidencePacket`/`EvidencePassage`/
`PacketFailure`), the pipeline entrypoint (one mode,
`build-baseline-packets`, with one new `--bundle-dir` flag), the schema
registry with both pinned-hash rebaselines, `REPO_MANIFEST.md` (689 → 702),
the three count tests, and this log — eleven paths. No issuer filtering,
screening, classification, tier derivation or PCT extraction, and no
`data/runs` artifact is read or written.

## ADR-092 — W2-C: two-hop primary-document acquisition and its Canary B plan

**Status.** Accepted. Fixture-first; the live Canary B run is separately
authorized and has not been executed.

**Why two hops.** The completed 12-document submission canary (ADR-089)
measured 508.3 MB for twelve filings, one of them 213.5 MB. Reading those
submissions offline showed the primary annual-report document is **8.8% of
the bytes** — 44.8 MB inside 508.3 MB, an 11.4× reduction, largest primary
9.27 MB. The packet route therefore fetches the filing index and then only
the selected primary; the accession-wide `.txt` is unreachable from this
module by construction.

**What is reused rather than rebuilt.** The bounded streaming transport
(ADR-089), the filing-index URL grammar and the whole probe parser (ADR-090)
— identity-first table selection, declared-type matching, and
`href_document_basename`, which understands both the direct archive link and
the `/ix?doc=` viewer form. New here: the sequencing module, the canonical
primary-document URL derivation, a code-validated
`primary_document_request_plan@0.1.0`, and the v0.1/v0.2 acquisition
manifests. **The committed bundle schema and packet builder are untouched.**

**The primary URL is derived, never taken from the href.** It is built from
the filing directory and the selected basename, so the inline-XBRL viewer
wrapper is never fetched. `href_form` (`direct` | `viewer`) is **measured and
recorded per document**, because existing evidence — the probe manifest
records candidate *names*, not hrefs — cannot say in advance which filings
link through the viewer.

**The filing directory is the lowest sharing CIK, enforced at plan load.**
`directory_cik` must equal the lowest normalized carrier-row CIK for its
accession — checked **before any URL is derived and before any request**, for
a one-row accession as much as a shared one. The accession's own 10-digit
prefix is frequently a filing agent that owns no EDGAR directory, and a
non-lowest *real* sharing filer is the plausible wrong answer, so both are
refused rather than resolved. A skipif-guarded test re-derives the rule from
the committed carrier run when present: every Canary-B row must match a real
baseline candidate on CIK, accession, form, domestic stratum and baseline
filing date, the plan must list the **complete** accession group, and each
`directory_cik` must be that group's minimum.

**Shared accessions.** One accession is fetched **once** and emits **one
bundle entry per carrier filer row**, every entry naming the same stored file
and the same hashes and differing only in CIK. That is legal under the
bundle's `(cik, accession)` duplicate rule and yields one packet per firm from
a single download. Request accounting is therefore exactly two per accession,
independent of how many filers share it.

**Storage naming.** `local_filename` is `primary-<accession_without_dashes>.html`;
`selected_document` remains the real SEC basename. The two are distinct facts
and are never required to be equal — and with this convention they always
differ in a real bundle, so W2-C-beta's distinctness property is exercised by
every entry rather than only by a synthetic test.

**Provenance is a directed graph with no cycle.** The bundle points back to
artifacts that already exist and are immutable — carrier manifest
`50a2582f…`, freeze record `27eb6d23…`, route probe `7aa16a0e…` — plus its
own per-document `filing_index_response_sha256`, and it names its producing
run by **id only**. The acquisition manifest's `output_hashes` covers exactly
the bundle manifest and every raw primary — *N + 1* entries — and **never
itself**; it carries no self-hash field, and no self-excluding hash convention
is introduced anywhere. Nothing hashes an artifact that hashes it back.

**Authority, stated as the contracts behave.** `bundle_manifest.json` is the
governed input marker that `build-baseline-packets` consumes; that builder
requires the bundle and nothing else, and it is **not** extended here. The
bundle together with this acquisition manifest is the evidence of a complete
successful acquisition run — an operational-policy statement about runs, not
a new builder requirement. A bundle manifest without an acquisition manifest
is therefore an incomplete acquisition-run record that the packet builder
still accepts; that asymmetry is recorded and tested honestly rather than
enforced by expanding the builder.

**Failure semantics: all-or-nothing authoritative bundle production.** On a
later per-document failure, raw primaries already written **remain** in the
immutable failed run directory and are named in the failure receipt's
`retained_raw_filenames`. They persist, and they are non-authoritative: no
bundle manifest and no acquisition manifest is written, so the builder cannot
consume the directory — it refuses on the missing bundle manifest before
opening any file. This path is never described as "nothing persisted".

**Transport provenance.** One *active* `transport_kind` per run. The two hops
are recorded separately — `metadata_hop` and `primary_document_hop` — because
each is constructed with a different plan-owned ceiling (8 MiB and 256 MiB);
their `transport_contract_hash` values are **equal**, because the byte bound
is deliberately not part of the transport contract, and a test asserts that
equality so a future divergence becomes visible. The failure receipt records
the same shape plus `attempted_hop`.

**Canary B, planned and not executed.** Six domestic baseline candidates from
frozen FRAME_v1 → **12 requests** (6 index + 6 primary) → **8 bundle entries**
→ ≈21.9 MB of primaries against ≈96.4 MB for the same six as submissions.
Three real 10-KT filings are included, one of them `form10-kt.htm`, a filename
no convention would match; the Spire combined 10-K supplies the shared
accession mapping three carrier rows. **All six index pages are fetched by
that run, including the three the probe already covered**: route validation
proves a URL grammar, never per-firm selection, so every document must carry
its own filing-index response hash. The plan records
`expected_primary_document` from the submission canary's own DOCUMENT blocks
but **omits `ground_truth_source_sha256`**, because the standalone primary
file has never been downloaded and only its filename is known. Each
acquisition therefore records `ground_truth_basis` — one of `none`,
`expected_filename_only`, `expected_filename_and_source_sha256` — stating
exactly what the plan supplied and this run then checked. A boolean
`ground_truth_verified` was withdrawn as ambiguous: it could not distinguish a
filename check from a byte check. **All six Canary-B entries are
`expected_filename_only`**, and the manifest may not claim source-byte ground
truth that does not exist. A source hash without an expected filename is
refused at plan load, which keeps the three states exhaustive; the fixture
bundle exercises all three. Canary B will
measure primary sizes and ceiling behaviour, selection provenance, `href_form`
distribution, and bundle integrity; the packet build over its bundle — and
with it the Item-1 boundary-kind distribution and any real instance of the
TOC-only limitation ADR-091 recorded — remains a **separate authorization**.

**Scope.** Added: the acquisition module, its v0.1 and v0.2 manifest schemas,
the committed Canary B request plan, the synthetic fixture bundle (plan,
three index pages covering direct/viewer/shared, three primaries, gold), and
the acquisition test file — thirteen paths. Modified: the pipeline entrypoint
(one mode, `acquire-primary-docs`, reusing the existing acquisition flags),
the schema registry (0.31.0 → 0.32.0, 68 → 70) with both pinned-hash
rebaselines, `REPO_MANIFEST.md` (702 → 715), the three count tests, and this
log — nine paths. Domestic 10-K/10-KT only; the FPI extension cohort is
preserved by the frame and carrier and is neither acquired nor excluded. No
cover-page or DEI parsing, no third fetch, no issuer filtering, no subsection
tagging, no screening, classification, tiering or PCT extraction, no model
call, and no cohort-wide download plan — batched, resumable acquisition of
the 9,916 candidates remains the W3 queue increment.

## ADR-093 — v0.3 observational successor: declared Content-Length per hop

**Status.** Accepted. Fixture-first; no live request was made, Canary B was
not re-run, and no acquisition behaviour changed.

**What the completed Canary B could not answer.** The live run (ADR-092)
retrieved six primaries totalling 21.9 MB with the largest at 6.50 MB, 2.42%
of the 256 MiB ceiling. Full-cohort byte planning wants the *declared* size
next to the *retained* size — the earlier document canary (ADR-089) recorded
`declared_content_length` per document and measured that SEC's declared
lengths understated retained bytes by up to 13.2×, because responses are
gzip-encoded. The primary-document acquisition manifest never recorded that
field, so its own run cannot be read that way. This increment adds the
recording and nothing else.

**Observational only.** Each live acquisition now records
`filing_index_declared_content_length` and
`primary_declared_content_length`: the parsed value the transport had
**already produced** for that specific hop, unchanged. Either may be `null`,
meaning the transport had no usable value because the header was absent or
malformed; nothing is reconstructed, normalized, inferred, or retained as a
raw header string. They are **not** retained byte counts and play no part in
ceiling enforcement, URL selection, retries, bundle construction, or
authority. Download behaviour is byte-for-byte identical to ADR-092.

**A successor, not a migration.** `schemas/primary_document_acquisition_manifest.schema.json`
(fixture v0.1) and `.v2.schema.json` (the historical `sec_live` contract) are
left **byte-for-byte unchanged**, and the completed Canary B artifact remains
a valid v0.2 record with no declared-length fields — a skipif-guarded test
re-validates that real artifact against the unchanged v0.2 schema and asserts
it was not rewritten. Live runs now emit **v0.3**, which requires the two new
fields; fixture replay still emits **v0.1**, which admits no such fields.
Each contract rejects the others' manifests.

**Governance.** `primary_document_acquisition_manifest_v3` registered at
0.3.0; registry 0.32.0 → 0.33.0, 70 → 71 entries; both established pinned
hashes rebaselined; `REPO_MANIFEST.md` 715 → 716.

**Scope.** Added: the v0.3 schema. Modified: the acquisition module (record
fields, live branch only), its test file, the schema registry, both pin
tests, `REPO_MANIFEST.md`, the three count tests, and this log — eleven paths
in total. Deliberately untouched: `sec_document_transport.py`, the
request-plan grammar, `bundle_manifest.json` and the bundle schema,
`baseline_packet.py`, the CLI, acquisition URLs, retry behaviour, and the
failed-run receipt format. **No new acquisition capability or policy is
introduced.**

## ADR-094 — Stage 00B-S: deterministic shell-company determination, alone

**Status.** Accepted. Fixture-first; no live request, no candidate-validation
canary, no model call, and no `data/runs` write.

**Exactly one fact, deliberately.** This increment reads
`dei:EntityShellCompany` and sets `shell_company` only. The four other Stage
00B flags — `investment_company`, `asset_backed_issuer`,
`non_operating_trust`, `blank_check_precombination` — are neither read, set,
inferred, nor represented, `issuer_filters.py` is not imported, and its
five-flag contract is unchanged. That separation is not tidiness: the measured
cohort contains a **liquidating trust that declares shell = false**, and a
five-flag path invites conflating `non_operating_trust` with `shell_company`
when only the latter has a governed source fact. `run_issuer_filters` could
not simply be called — it iterates all five flags and would have to fabricate
positions on four of them, and it consumes a `HistoricalAnnualFiler` keyed on
a `company_id` the frame does not carry (ADR-088).

**Outcomes.** `true` is a deterministic hard exclusion carrying dated
evidence. `false` means the firm is **retained** and asserts nothing about
software, product, or general eligibility. `unknown` is retained. Nothing is
ever excluded on absent or ambiguous evidence.

**Boolean evaluation is a transform-application contract.** The declared
transform alone does not decide the value: one measured AAR filing yields
both outcomes under `ixt-sec:boolballotbox` — `dei:DocumentAnnualReport` with
U+2612 ☒ is true while `dei:EntityShellCompany` with U+2610 ☐ is false in the
same document. Decoded content is therefore evaluated *under* its transform.
`ixt-sec:boolballotbox` is the **only** content-dependent transform (☐ ⇒
false, ☒ ⇒ true, any other content ⇒ unknown). Four transforms are
content-**independent**, taking their output from the XBRL Transformation
Registry rather than from anything a filing renders: `ixt:booleanfalse` ⇒
false, `ixt:fixed-false` ⇒ false, `ixt:booleantrue` ⇒ true, `ixt:fixed-true`
⇒ true. No checkbox glyph is consulted for those four in either direction —
`fixed-false` rendered with ☒ still returns false, and `booleantrue` rendered
with ☐ still returns true. U+2611 ☑ was never observed and is not admitted.
Entity decoding is mandatory: `&#9744;` and `&#x2610;` are the same codepoint
and both occur. Any transform outside these five, and an absent one, yield
unknown.

**Correction, v0.1 → v0.2 (`ixt:booleantrue`, `ixt:fixed-true`).** v0.1
excluded both on the stated ground that neither had been observed and no
canonical registry was cited here for them. The executed shell-validation
canary then observed both — `ixt:booleantrue` twice and `ixt:fixed-true`
once — on three real 10-K cover pages, each carrying exactly one assignable
fact.

**Cited authority.** The mapping comes from the **XBRL Inline Transformation
Registry 4 (TR4)**, namespace
`http://www.xbrl.org/inlineXBRL/transformation/2020-02-12`, prefix `ixt`,
which defines `booleantrue` as producing the boolean value *true* and
`fixed-true` as producing the fixed value *true*, each independently of the
element's rendered content — the exact mirror of `booleanfalse` and
`fixed-false` in the same registry, which v0.1 already supported on that same
authority. The registry defines the meaning; the three observations only
prompted citing it, and are not themselves the warrant.

Under v0.1 those three rows returned `unknown` / `unsupported_transform`
although their glyph was ☒; the v0.1 rule was refusing to resolve a
registry-defined transform, not guarding against one. **This is a correction
of an under-supported transform set, not a relaxation of evidence
standards**: inference from checkbox glyphs remains forbidden for all four
fixed and boolean transforms, in both directions, and every context and
CIK-binding safeguard is unchanged.

**Schema succession, not schema mutation.** An earlier draft of this entry
claimed that widening `supported_transforms` in place preserved v0.1
validity. **That claim was wrong and is withdrawn**: both v0.1 schemas pin
`determination_contract` as a `const` of
`shell_company_determination@0.1.0`, so no widening of the transform array
could have admitted a v0.1 artefact under a v0.2 contract, and mutating the
files would have left the completed v0.1 canary manifest validated by nothing.
The repository's versioned-successor pattern applies instead. Both v0.1
schema files are **retained byte-unchanged** and remain the only validators
for artefacts written under that contract. Two explicit successors are added
— `shell_company_determination.v2.schema.json` and
`shell_company_determination_manifest.v2.schema.json` — declaring
`@0.2.0` and requiring **exactly the five** supported transforms. The
successor is deliberately **not** permissive: a v0.1 manifest is rejected by
v2, and a v0.2 manifest is rejected by v0.1, in both cases on the contract
const. New v0.2 runs validate against the successors and report
`shell_company_determination_v2` and
`shell_company_determination_manifest_v2`; the registry carries all four
entries, 0.1.0 and 0.2.0 side by side, and nothing migrates. The synthetic
fixture keeps the filename
`shell_unsupported_transform.html` and its bytes are unchanged; it now
exercises `ixt:booleantrue` against a contradicting empty box, and its gold
outcome moves from `unknown` to `true`. Its name is a residue of v0.1 and is
not a claim about the transform.

**Context resolution, and why it is strict.** Every fact resolves through its
`contextRef`; the identifier scheme must be exactly `http://www.sec.gov/CIK`,
and an unmembered context binds only when its identifier equals the carrier
row's CIK. A context carrying a `dei:LegalEntityAxis` member is
**unassignable** unless the filing itself maps that member to the row CIK.
The measured evidence is decisive: the real Spire combined filing carries
**three** `EntityShellCompany` facts whose contexts **all bear the parent's
CIK 0001126956**, distinguishing registrants only by filer-defined
`sr:SpireMissouriMember` / `sr:SpireAlabamaIncMember` tokens that carry no
CIK. So that filing yields **false for the parent and unknown for both
subsidiary rows** — not false for three firms. A member token is never
resolved by name resemblance.

**Fail-closed multiplicity.** Missing, malformed, unsupported, conflicting,
unassignable, or more than one assignable fact all yield `unknown`. In v0.1
even *agreeing* duplicates yield `unknown` rather than being collapsed:
agreement is not evidence that the duplication was intended.

**Provenance.** Each determination retains CIK, accession, form, baseline
filing date, `source_sha256`, the transform and decoded-content observations,
`fact_byte_start`, `fact_byte_end`, `fact_element_sha256`, and the bundle and
carrier provenance. Byte ranges are **half-open** `[start, end)` and
`fact_element_sha256` covers exactly `raw[start:end]` — the complete raw
`ix:nonNumeric` element, unnormalized and undecoded.

**Input.** It consumes the committed `baseline_primary_document_bundle@0.1.0`
unchanged, reusing `load_bundle` read-only, so it introduces no acquisition
format and fetches nothing. `baseline_packet.py`, the bundle schema,
primary-document acquisition, and the document transport are untouched.

**Scope.** Added: the determination module, its record and run-manifest
schemas, a twelve-document synthetic bundle with manifest and gold, and the
test file — eighteen paths. Modified: the pipeline entrypoint (one mode,
`determine-shell-company`), the schema registry (0.33.0 → 0.34.0, 71 → 73)
with both pinned-hash rebaselines, `REPO_MANIFEST.md` (716 → 734), the three
count tests, and this log — nine paths. The 20-row candidate roster remains a
**roster, not gold**: every name-pattern selection is provisional until its
own primary document proves the label, and the 24-request validation canary
is not run here.

### Planned shell-validation canary — pre-registration only

**Status of this subsection.** It records a **pre-registered validation plan**.
It is **not gold data and not an executed run**. No request has been made, no
bundle exists, and no label below except the three marked *observed* has ever
been measured. Authorization for the acquisition run and for the local
determination run remains separate and is not implied by this entry or by
possession of the committed request plan.

**The 20-row roster referred to above was never enumerated anywhere in this
repository**, so it is unavailable as evidence. The cohort below was selected
fresh from the frozen carrier and is not a reconstruction of it.

**Cohort.** `configs/shell_validation_canary_request_plan.json`, under the
committed `primary_document_request_plan@0.1.0` contract: twelve unique
domestic accessions, 23 complete carrier rows, 24 requests, 23 bundle entries.
Three combined filings carry complete groups of three, seven and four rows.
The CMBS trust `0001888524-22-003211` is **retained inside this same canary**
rather than replaced or split off: its plausible no-fact outcome is the only
live exercise of the `no_shell_fact_in_document` branch, which the ordinary
operating-filer controls cannot reach. Only Spire records ground truth.

**Three layers, kept separate.**

*Observed labels* — three rows already measured on real bytes in
`primary-document-canary-frame-v1-20260816`: `0001126956` false
(`boolballotbox_empty_box`, 3 facts / 1 assignable); `0000003146` and
`0000057183` unknown (`no_fact_assignable_to_this_cik`, 3 facts / 0
assignable). These are measurements, not predictions.

*Hypotheses* — H1 (combined filings): a filing's unmembered context carries
one identifier CIK, so at most one row per combined filing binds and every
other row resolves unknown; support is one observation, and H1 does not say
*which* row binds. H2 (blank-check structure): `filings_count = 1` with first
filing = last filing, plus a **provisional** `ACQUISITION|CAPITAL CORP` name
pattern that carries no weight alone. H3 (continuous filer): `filings_count =
7`, first filing on or before 2020, still filing in 2026. H4 (asset-backed
tagging): a Reg AB mortgage-trust 10-K carries an HTML primary but no
inline-XBRL cover-page tagging — the weakest hypothesis in the set.

*Predictions* — one entry per `(CIK, accession)` row. Where a hypothesis
yields a compound uncertainty the row is recorded `no_prediction` rather than
guessed.

| # | CIK | Accession | Prediction | Basis |
| --- | --- | --- | --- | --- |
| 1 | 0000003146 | 0001437749-22-027522 | unknown | observation |
| 2 | 0000057183 | 0001437749-22-027522 | unknown | observation |
| 3 | 0001126956 | 0001437749-22-027522 | false | observation |
| 4 | 0000020947 | 0001578443-22-000007 | unknown | H1 |
| 5 | 0000073960 | 0001578443-22-000007 | unknown | H1 |
| 6 | 0000352049 | 0001578443-22-000007 | unknown | H1 |
| 7 | 0001573279 | 0001578443-22-000007 | unknown | H1 |
| 8 | 0001573334 | 0001578443-22-000007 | unknown | H1 |
| 9 | 0001573352 | 0001578443-22-000007 | unknown | H1 |
| 10 | 0001578443 | 0001578443-22-000007 | no_prediction | compound |
| 11 | 0000922358 | 0001558370-22-014733 | no_prediction | compound |
| 12 | 0000922359 | 0001558370-22-014733 | unknown | H1 |
| 13 | 0000922360 | 0001558370-22-014733 | unknown | H1 |
| 14 | 0001012493 | 0001558370-22-014733 | unknown | H1 |
| 15 | 0001833909 | 0001213900-22-020143 | true | H2 |
| 16 | 0001829558 | 0001193125-22-091842 | true | H2 |
| 17 | 0001844840 | 0001104659-22-030631 | true | H2 |
| 18 | 0001841867 | 0001410578-22-000778 | true | H2 |
| 19 | 0000002488 | 0000002488-22-000016 | false | H3 |
| 20 | 0000009092 | 0001564590-22-006284 | false | H3 |
| 21 | 0000007431 | 0000950170-22-001531 | false | H3 |
| 22 | 0001558546 | 0001888524-22-003211 | unknown | H4 |
| 23 | 0001227654 | 0001227654-21-000309 | false | H3 |

Row 10's accession prefix equals its own CIK, so that trust submitted the
filing; if it binds it could resolve either way under Rule 12b-2, and if it
does not bind it is unknown — three live outcomes, no directional basis. The
group has **no parent in the carrier**, so the Spire shape does not transfer.
Row 11 is the top-level partnership, structurally like the Spire parent: false
if it binds, unknown if it does not, with no basis to choose.

**Reconciliation — four categories totalling exactly 23.** Predicted true: 4
(rows 15–18). Predicted false: 5 (rows 3, 19, 20, 21, 23). Predicted unknown:
12 (rows 1, 2, 4–9, 12–14, 22). `no_prediction`: 2 (rows 10, 11). 4 + 5 + 12 +
2 = 23. The Spire parent appears **once**, under predicted false; its observed
label is the same row, recorded as the measurement generating the prediction,
not as a second unit. The twelve predicted-unknown rows decompose exactly as
9 + 1 + 2: nine from H1 (rows 4–9 and 12–14), one from H4 (row 22), and two
observed Spire reproduction unknowns (rows 1–2).

**`no_prediction` is a pre-registration category, not a determination
outcome.** The determination contract emits only `true`, `false` or `unknown`;
all three are represented in the register. Rows 10 and 11 will each return one
of those three, and the register simply declines to say which, so those two
rows confirm and refute nothing by construction.

**H1 falsification rule.** H1 permits at most one determinate row per shared
accession, so a **single** `true` or `false` anywhere within an accession group
is **consistent** with H1 — it means only that the binding row is not the one
the notes nominate. H1 is falsified in exactly two ways: **two or more carrier
rows of the same accession return determinate `true`/`false` results**, or
**the implementation assigns a fact without the required CIK-binding
evidence** — a determinate result on a row whose only candidate contexts carry
a `dei:LegalEntityAxis` member, or whose identifier scheme is not the SEC CIK
scheme. The second form is the failure the context-membership correction
closed, so the three combined filings are also a live regression check;
`facts_in_document`, `assignable_facts` and `detail` are what distinguish the
two cases and must be read before any group is judged. Zero `true` across rows
15–18 falsifies H2 and would mean no observed shell exclusion exists in this
slice. A resolved fact at row 22 falsifies H4.

## ADR-095 — W3: batch primary-document acquisition queue, fixture-first

**Status.** Accepted. Fixture-first; no live request, no download, neither
canary rerun, and no cohort-scale run authorized here.

**Problem.** The committed two-hop acquisition runner acquires a plan. It has
no way to cover a cohort: nothing derives plans from the frozen carrier,
nothing bounds how much a run may retain, and nothing distinguishes a
completed batch from an abandoned one.

**Scope, stated separately.** In scope is the **domestic 10-K/10-KT** queue,
derived from `universe-baseline-carrier-frame-v1-20260816`: **8,718 carrier
rows over 8,526 unique accessions**, so **17,052 requests** at two per
accession, and 86 shards at `shard_size` 100. Dedup is real — 134 shared
accessions cover 326 rows, so 8,526 fetches serve 8,718 rows. The **FPI
extension** (1,198 rows, 1,193 accessions, 1,014 20-F and 184 40-F) is
**preserved and deferred, not excluded**: it is recorded in every queue
definition's `deferred_cohorts`, because the acquisition form enum admits
10-K/10-KT only and FPI cover-page structure has never been measured here.
**The four shell-canary exclusions do not reduce this queue**: determinations
exist for 23 rows only, and none can exist before acquisition, because
determination reads the document this queue fetches.

**Three separately gated stages.** A **planner** derives shard plans, an
**executor** runs an operator-named allowlist, and an **aggregator** reports
coverage. Each writes its own governed manifest, and each is a separate
command.

**Shard plans are artefacts, not arguments.** The planner writes every plan
write-once and hashes each into a plan manifest. **Before any run directory or
transport exists**, the executor loads and schema-validates that planner
manifest from the plan directory and verifies, for every requested shard, that
the manifest's `queue_definition_sha256` equals the named definition, that it
**enumerates** the shard index under its exact plan filename, that its
`output_hashes` **records that artefact** and the bytes on disk hash to the
recorded value, and that the recorded `shard_plan_sha256` equals the plan
regenerated from the definition. Only then does it compare the artefact **byte
for byte** and execute the persisted file. A directory holding a byte-identical
shard plan but no valid planner manifest is not a plan directory and carries no
authority. Because the whole allowlist is verified first, a missing, corrupt,
mismatched or unenumerated artefact leaves **no execution run directory**
behind. The executor never runs an ephemeral or hand-supplied plan, and
`--request-plan` is refused outright in queue mode.

**Determinism.** Membership is a pure function of (carrier bytes, filters,
shard size, index): accessions are sorted lexicographically and sliced. No
clock, no randomness, no cursor. Complete carrier groups cannot straddle a
boundary, because shards partition accessions and each accession carries its
whole row group.

**The byte budget is enforced inside the runner, not around it.** A planner or
aggregator wrapped around the runner cannot bound disk: the runner writes each
primary itself, and `primary_document_request_plan@0.1.0` declares only
per-document ceilings, so a post-hoc check would observe an overrun that had
already happened. `@0.2.0` therefore adds a required `max_retained_bytes`, and
the runner checks `retained + len(content) > budget` **immediately before**
`write_bytes_once`, against the materialised body length and never against
Content-Length, which understates retained bytes by 7.8x-21.4x in measured
live runs and is sometimes absent entirely. Disk never exceeds the budget, not
even by one document: the over-budget document is discarded unwritten and the
receipt carries `shard_retained_byte_budget_exhausted`. **Transient memory is
not bounded by this** — it stays bounded by the per-document ceiling, because
the transport materialises a body before the runner sees its length. Making
the *download* stop early would need a per-document effective bound and would
collide with the runner's fail-closed invariant that the transport's bound
equals the plan's `max_document_bytes`; that is the known follow-up and is
deliberately out of scope.

**The complete contract matrix.** The runner selects its output schema by
transport kind, so a budgeted **fixture** run needed a successor just as much
as a live one. Flat numbering is not an invention here: the lineage already
interleaves transports — v0.1 is the fixture schema, v0.2 and v0.3 are
sec_live — so v0.4 continues the fixture lineage and v0.5 the sec_live one.

| Transport | Plan | Manifest schema | Version |
| --- | --- | --- | --- |
| fixture | v0.1 | `…manifest.schema.json` **unchanged** | 0.1.0 |
| sec_live | v0.1 | `…manifest.v3.schema.json` **unchanged** | 0.3.0 |
| fixture | v0.2 | **new** `…manifest.v4.schema.json` | 0.4.0 |
| sec_live | v0.2 | **new** `…manifest.v5.schema.json` | 0.5.0 |

**No schema is permissive.** Every schema in the lineage sets
`additionalProperties: false` and requires exactly its own `schema_versions`
key, so a v0.2 fixture manifest is rejected by v0.1, a v0.2 live manifest is
rejected by v0.3, and v0.4 and v0.5 reject each other. v0.1, v0.2 and v0.3 are
retained **byte-unchanged**, and both committed v0.1 plans still load and
still produce their historical manifests.

**Candidacy, authority, and the two failure shapes.** A run directory holding
**both** a bundle manifest and an acquisition manifest is a **candidate for
admission** — presence, and nothing more. Two files with the right names are
not evidence. **Executor and aggregator alike admit a candidate as
authoritative only after its content binds**: the acquisition manifest must
validate against the applicable budgeted successor (v0.5 for `sec_live`, v0.4
for fixture replay), declare `primary_document_request_plan@0.2.0`, carry a
`plan_sha256` equal to the regenerated shard plan hash, report accession,
carrier-row, bundle-entry and request counts consistent with that shard, record
`retained_bytes_total` no greater than the shard budget, and hold an output
hash for `bundle_manifest.json` matching the bundle bytes on disk. A candidate
that fails any of these raises `ShardIntegrityError` and is **never recorded as
authoritative**: no execution manifest may label it so, no aggregate is
written, and it is not downgraded to ordinary partial coverage, because corrupt
or mismatched evidence is an integrity error rather than an incomplete shard.
The same binding decides whether an earlier run counts as completed work that
blocks re-execution. A **handled** failure also writes a receipt; an
**interrupted or crashed** shard may write nothing at all. Receipt presence
stays **diagnostic only** — never read as success when missing, never the sole
failure marker when present — and both shapes remain non-authoritative and
ineligible for aggregation.

**Authorization boundary.** The executor requires an enumerated
`--shard-indices` allowlist and an `--expected-request-count` that must equal
the computed total, so the scale being authorized is stated rather than
discovered. There is no value that expands to the whole queue: `all`, ranges
and empty segments are all refused. `--on-shard-failure` is operator-declared
with no default. An index that already has an authoritative run is refused, so
resume means naming the non-authoritative indices. The executor writes no
aggregate.

**The live canary is a cohort, not two shards of the full queue.**
`configs/queue_canary_definition.json` enumerates six accessions explicitly
and shards them 3 + 3; **its indices 0 and 1 are relative only to those six**,
and the full queue's shard 0 contains entirely different accessions. It plans
to 12 requests and 14 bundle rows, and covers two shared accessions (3 and 7
carrier rows), two 10-KT filings, both measured href forms, and the Spire
filename-plus-source-hash reproducibility control. Its rederivation test
proves every selected accession carries its **complete** carrier group. The
canary is **not run here**.

**Budget evidence.** Measured over 18 accessions in two completed live runs:
primaries total 53,746,436 bytes, mean 2,985,913, median 2,624,373, max
6,499,830. The 12 MiB per-accession allowance is roughly twice the observed
maximum and is a **bound, not a prediction**; a shard that legitimately
exceeds it fails closed and must be re-planned under a new plan hash.
Extrapolating the mean to 8,526 accessions gives ~25.6 GB and the maximum
~55.6 GB, but that is extrapolation from n=18, not a measurement.

**Gates.** Queue fixture tests → review → 12-request live queue canary →
review → controlled batch authorization for an explicit shard list → per
completed authoritative shard, local shell determination and packet build →
later 00D high-recall screen. Each arrow is a separate authorization.

**Scope.** Added: the queue module and its test file, four queue schemas, the
two budgeted manifest successors, two committed queue definitions and four
queue fixtures — fourteen paths. Modified: the acquisition runner (plan v0.2,
the pre-write budget check, the v4/v5 branches, one reason code), the pipeline
entrypoint (three modes), the schema registry (0.35.0 → 0.36.0, 75 → 81),
`REPO_MANIFEST.md` (737 → 751), the count and pinned-hash tests, and this log.

## ADR-096 — Filing-index selection: eligibility before cardinality

**Status.** Accepted. Fixture-first correction; no live request, no retry of
the failed shard, no new queue plan, and no historical schema or plan touched.

**Measurement.** The first controlled W3 domestic shard failed closed on its
21st accession. Its immutable receipt records the cause exactly: accession
`0000007332-22-000009` declares Type `10-K` for **two** rows of its Document
Format Files table — `swn-20211231.htm` and `swn20211231x10k.pdf`. The
selector counted matches by declared Type first and refused
`ambiguous_primary_candidate` before ever considering the HTML rule, so a
filing carrying a PDF rendering of the same document was treated as having
two rival primaries.

**The filing was never ambiguous.** A PDF cannot be a primary document under
this route: the acquisition contract admits `.htm`/`.html` only, and the
downstream packet and determination stages parse HTML. The PDF was never a
candidate, so counting it as one refused a filing whose primary is uniquely
determined. Because a same-form PDF companion is common in EDGAR, this rule
would have refused many of the remaining 85 shards.

**Decision: eligibility is decided before cardinality.** Selection is now
ordered — declared Type equals the planned form, **then** the document is
HTML, **then** uniqueness is required among those HTML-eligible rows.
Consequently: one matching HTML beside any number of matching non-HTML
companions selects the single HTML; **two or more matching HTML rows still
refuse `ambiguous_primary_candidate`**; matching rows with no HTML among them
refuse `non_html_primary`; and zero matching rows refuse
`no_primary_candidate`.

**This narrows eligibility; it does not tie-break.** Nothing reads document
order, sequence number, size, description or rendered text. A larger,
earlier, better-described PDF still loses to the HTML row because it was
never eligible, not because it lost a comparison, and two HTML rows of the
same Type remain genuinely ambiguous and are still refused. Table identity by
`summary`/heading, href-derived filenames, the viewer and direct link forms,
both byte ceilings, and the ground-truth rules are all unchanged.

**Evidence.** A committed fixture reproduces the measured shape — an index
page declaring Type `10-K` for both an `.htm` and a `.pdf`, with both
documents present in the replay directory. End-to-end acquisition over it
proves the selected URL is the HTML row, that **exactly two requests are
made** and neither addresses the PDF, and that no `.pdf` byte is retained.
Order-independence, multiple companions, and the still-ambiguous two-HTML
case are pinned separately.

**Not done here.** The failed shard directory is untouched and stays
non-authoritative; shard 0 is not retried and no new queue plan is created.
Whether to re-plan the domestic queue under the corrected selector is a
separate decision.

**Scope.** Added: three fixture files (the index page, its HTML primary, its
PDF companion). Modified: `select_primary_document`, the probe and
primary-acquisition test files, `REPO_MANIFEST.md` with its count tests, and
this log. No schema, no registry entry, and no plan contract changes.

## ADR-097 — Plain-text primaries: a separate representation, not a disguise

**Status.** Accepted. Fixture-first; no live request, no v0.3 plan created, no
shard retried, no aggregate, no packet built from a live run.

**Measurement.** The first controlled W3 domestic batch stopped on shard 2 at
accession `0000074925-22-000002`, whose Document Format Files table declares
Type `10-K` for exactly one row: `10k2021.txt`. The HTML route refused it
`non_html_primary`, correctly — a `.txt` is not HTML — but a genuine annual
report was therefore unreachable.

**Decision: admit text as its own representation, never as pretend HTML.** A
`.txt` may be selected only when the form-matching rows contain **no HTML at
all** and only when the plan opts in. HTML always wins where both exist, so
the existing route is unchanged. Text bytes are stored as
`primary-<18-digit-accession>.txt`, never rewritten, renamed, or converted:
`local_filename_for` is representation-aware, because a `.html` name on text
bytes would be a silent conversion.

**Admission is positive evidence, decided before any byte is retained.** Two
shapes and nothing else. `single_sgml_document`: exactly one `<DOCUMENT>`
whose `<TYPE>` equals the planned form and whose `<FILENAME>` equals the
selected document. `bare_text`: no wrapper, but a **line-start** `FORM 10-K`
or `FORM 10-KT` matching the planned form **and** a line-start Item 1 heading.
A file is never admitted merely for lacking a wrapper. Multi-document
submissions, ambiguous embedded documents, type or filename disagreement, and
unsupported structure are recorded refusals. The check runs after the hop-2
response and **before `write_bytes_once`**, so a rejected candidate leaves no
byte on disk and only previously completed documents appear in the receipt.

**Item 1 in text.** `find_item_one_span_text` reuses the existing heading and
boundary patterns and the same end priority — Item 1A, then 1B, then Item 2 —
replacing the HTML block guard with a line guard, because `_starts_a_block`
measures bytes since the previous block close and so rejects every candidate
in tagless prose. In-tier ambiguity refuses. `find_item_one_span` and
`find_item_one_span_v2` are **byte-identical**.

**The TOC-only limitation is preserved, not replaced.** The last-qualifying-
match rule defeats a contents entry only when a real body heading follows it.
Measured on the fixture: when the contents entry is the only qualifying match
the finder takes it and returns a degenerate span of the contents line itself.
That is the ADR-091 limitation carried forward and recorded, not a new
unmeasured refusal threshold.

**Passage granularity, stated as a limitation.** The normalizer is reused
unchanged, and its block segmentation is HTML-driven, so a text Item 1 span
normalizes to **exactly one passage** — measured on all six fixture packets.
Recorded here, not fixed: blank-line segmentation would change what a passage
means per representation, which is a measurement decision of its own and
feeds the open packet-granularity question.

**Provenance: written once, forwarded thereafter.** The four admission-
evidence fields — `admission`, `document_blocks`, `declared_type`,
`declared_filename` — are written at acquisition time into **both** the v0.2
bundle document entry and the v0.6 acquisition manifest, present-and-null on
HTML rows so absence can never be read as "not text". The v0.2 packet
forwards them verbatim as `text_structure`; `baseline_packet.py` does not
import the admission module, and a test proves forwarding by giving the
bundle evidence that disagrees with the bytes and asserting the packet
mirrors the bundle.

**Succession, not widening.** Predecessors are retained byte-unchanged:
bundle v0.1, packet v0.1, packet manifest v0.1, queue definition v0.1, and
acquisition manifest v0.1/v0.2/v0.3/v0.4/v0.5 — none of which admits a `.txt`.
Successors: `baseline_primary_document_bundle@0.2.0`,
`universe_baseline_packet@0.2.0`, `baseline_packet_manifest@0.2.0`,
`acquisition_queue_definition@0.2.0`, and
`primary_document_acquisition_manifest@0.6.0`. `primary_document_request_plan`
gains a code-governed `@0.3.0` requiring `admit_plain_text` to be exactly
`true`; a plan admitting no plain text is a `@0.2.0` plan. The bundle advances
to v0.2 only when a shard actually admits text, so an all-HTML shard emits
exactly what it emits today. A v0.1 packet omits the two v0.2 fields entirely
— enforced in the model serializer, because both are inside `packet_sha256`
and emitting them would rewrite every historical packet hash. Registry 0.36.0
→ 0.37.0, 81 → 86.

**Lineage.** `configs/domestic_primary_document_queue_text.json` is a new
committed v0.2 definition; the v0.1 one is byte-unchanged. Same carrier,
filters, shard size and allowance, so membership is identical — 8,718 rows,
8,526 accessions, 86 shards, 17,052 requests — but its definition hash
differs, so **every shard plan hash differs** and v0.2-lineage artefacts do
not bind against v0.3 plans. Shards 0 and 1 remain authoritative under the
v0.2 lineage and are retained immutable; shard 2 requires a fresh v0.3
planner run and **cannot reuse the v0.2 plan directory**. The settled retry
sequence is: publish this increment, plan v0.3, re-run shard 0, re-run shard
1, then retry shard 2, and aggregate only within the v0.3 lineage. None of
that is done here.

**Scope.** Item 1 acquisition and normalization only. No cover-page, DEI or
XBRL parsing, no shell determination for text filings, no screening,
classification or PCT extraction, and no third fetch.

## ADR-098 — PCT_Dev30_v0 combined-candidate contract: local-ID staging, ledger-anchored candidate IDs, no self-confidence fields

**Status.** Accepted. Fixture-first and offline: two governed schemas plus a
pure adapter module, no `pct_candidate_extraction_dev30_v1` prompt drafted,
no model called, no Dev30 firm scored, no holdout output touched, no
`data/runs`/W3 contact.

**What this is for.** A future single Dev30 extraction call must emit
product, capability and task claims for one Item 1 span in one shape, rather
than three separate calls each guessing at the others' identities. This ADR
governs the exact two-stage contract that call will have to produce and the
deterministic, non-model code that turns its raw output into a persisted,
verifiable artifact. It authorizes no extraction prompt and no live call.

**Two stages, not one.** Stage 1 (`pct_dev30_v0_model_output@0.1.0`) is the
shape a model is instructed to emit: candidates keyed by local, per-call IDs
(`P1`, `C1`, `T1`, kind-prefixed and pattern-typed) so a task can reference
its product and capabilities before any persisted identity exists. Stage 2
(`pct_dev30_v0_persisted_candidates@0.1.0`) is what
`src/dynamic_ai_products/dev30/combined_candidate_adapter.py` — pure,
deterministic, no model call — produces from it: every local reference
rewritten to a persisted `candidate_id`, `local_id` retained only as
non-authoritative diagnostic metadata. Computing `candidate_id` from a
payload that already contained `candidate_id` would be circular; the local-ID
stage exists specifically to avoid that.

**The model is not trusted for its own identity.** The adapter takes a
`ticker`, resolves the one canonical
`evals/registries/pct_dev30_v0_item1_locator_ledger.json` from the
repository root, and reads it to obtain the `legacy_source_id` and
`source_text_hash` that ticker is allowed to claim. `build_persisted_candidates`
has no `locator_ledger_path` parameter or any other way for a caller to
redirect it to a different file. A Stage-1 output that echoes a different
`legacy_source_id` is refused (`legacy_source_id_mismatch`) before any
`candidate_id` is computed. The caller also supplies `span_text` — the Item 1
content quote-containment is checked against — and the adapter refuses
unless `sha256(span_text) == ` the hash embedded in the ledger's
`legacy_source_id` (`span_text_hash_mismatch`), so an arbitrary or stale
string cannot be used to rubber-stamp a candidate's evidence quote.

**Correction (same increment, before commit).** The first version of this
adapter took a `locator_ledger_path` parameter and let the caller supply an
arbitrary file. It computed that file's real sha256 into
`locator_ledger_sha256`, but always wrote the fixed, canonical-looking
string into `locator_ledger_relative_path` regardless of what was actually
read — so a caller-selected, non-canonical ledger could be consumed while
the persisted Stage-2 artifact still claimed canonical-ledger provenance. No
Stage-2 artifact was ever produced against a real Dev30 ticker under this
defect; it was caught before commit. The fix: the ledger path is now a fixed
internal constant (`_LEDGER_PATH = _REPO_ROOT / LOCATOR_LEDGER_RELATIVE_PATH`)
with its own reviewed hash pin (`_CANONICAL_LEDGER_SHA256`), read and
verified exactly like the two schema files, and checked before any ticker
row is extracted — mismatch refuses with the new `ledger_file_tampered`
reason. Tests redirect the adapter only by monkeypatching the two
module-private names together (`_LEDGER_PATH`, `_CANONICAL_LEDGER_SHA256`);
no public parameter offers an equivalent.

**`candidate_id` anchors to the raw model output, not to the source.**
`candidate_id = sha256(model_output_sha256 || 0x00 || ordinal || 0x00 || kind
|| 0x00 || canonical_json_bytes(fields))[:32]`, where `fields` excludes
`candidate_id`, `local_id`, `kind` and `ordinal`, and every relationship
field is rewritten to an already-computed persisted `candidate_id` by
processing products, then capabilities, then tasks — acyclic by
construction. `model_output_sha256` is the raw Stage-1 bytes' own hash,
computed before parsing. Anchoring there rather than on `legacy_source_id`
makes every `candidate_id` non-transferable across distinct raw outputs even
when their logical content agrees, matching
`extraction_candidate_collection@0.1.0`'s existing `raw_artifact_sha256`
anchor pattern. `ordinal` is the row's index in the **original** Stage-1
array, independent of the adapter's topological processing order.

**Candidates carry no disposition and no self-confidence field.** A prior
round of this design put `excluded_internal_use`/
`excluded_pending_scope_decision` values inside a `disposition` field on
candidate rows, conflating "this is a candidate" with "this was excluded."
That field is gone. `candidates` is in-scope only; a separate, optional,
non-exhaustive `excluded_mentions` list carries evidence-backed exclusions
under a closed four-value reason enum (`internal_use`, `vague_ai_marketing`,
`not_customer_facing`, `insufficient_specificity`). Roadmap or beta language
is never routed there — it is an ordinary candidate carrying a non-GA
`availability_status`. Neither schema carries a confidence, uncertainty, or
`ai_relevance_status` field; the quality controls are evidence quote, exact
offsets, explicit availability, relationship validation, and later human
review — nothing the model self-rates.

**Discriminated, closed schemas.** Both stages use a `kind`-discriminated
`oneOf` over product/capability/task branches, each `additionalProperties:
false`. `local_id` is kind-prefix-patterned (`^P[1-9][0-9]*$` etc.), which
closes "correctly typed link" at the schema level: a capability or task
reference can only ever validate against a local_id string whose own branch
requires the matching `kind` value, so a referential wrong-kind condition is
unreachable once schema validation has passed and is not re-checked in the
adapter (only existence and duplication are — JSON Schema cannot express
either across a heterogeneous array). `zero_candidate_reason` is schema-
enforced (via `if`/`then`) to be non-null exactly when `candidates` is empty.

**Registry treatment, and its boundary.** Both schema files are registered in
`schemas/schema_version_manifest.json` (0.37.0 → 0.38.0, 86 → 88 entries).
Neither is added to `EVALUATION_SCHEMA_CONTRACTS` or
`RELEASED_EVALUATION_CONTRACTS` in
`src/dynamic_ai_products/evaluation/schemas.py` — Dev30 is not a production
evaluation-harness contract, and folding it into that registry would put an
unauthorized-for-scale artifact on the harness's own release surface. The
adapter instead hash-pins both schema files itself (`_STAGE1_SCHEMA_SHA256`,
`_STAGE2_SCHEMA_SHA256`) and refuses on drift
(`schema_file_tampered`), the same fail-closed posture the production
registry uses, self-contained rather than shared. The committed locator
ledger gets the identical treatment: hash-pinned as `_CANONICAL_LEDGER_SHA256`
against the fixed `_LEDGER_PATH`, refusing with `ledger_file_tampered` on
drift, checked before any ticker row is extracted.

**Scope.** Added: the two schemas, the adapter module, and its test file (54
synthetic cases — no real Dev30 firm text, no holdout access — covering
every schema branch, every one of the eleven `REASON_*` refusal codes,
ordinal preservation under out-of-order declaration, non-transferability
across distinct raw outputs, reproducibility of the exact `candidate_id`
formula, canonical-ledger tamper detection, and the absence of any public
ledger-selecting parameter). Modified: the schema registry, `REPO_MANIFEST.md`
(782 → 786), the three manifest-count tests, and `test_schema_registry.py`'s
pinned manifest hash. This authorizes no extraction prompt, model call, or
Dev30 score.

## ADR-099 — PCT_Dev30_v0 v0.2 successor: adapter-derived evidence offsets, not model-supplied ones

**Status.** Accepted. Fixture-first and offline: two new schemas plus a new,
self-contained adapter module, no prompt drafted, no model called, no Dev30
firm scored, no holdout row touched, no `data/runs`/W3 contact. v0.1
(`combined_candidate_adapter.py` and its two schemas) is untouched.

**The question.** Requiring a model to emit exact `char_start`/`char_end`
offsets for every evidence quote across a full Item 1 span (up to ~9,600
words in this cohort) asks it to do precise character counting over long
text — a well-documented general LLM weakness. Is that burden operationally
justified, or can the adapter derive offsets deterministically from a
model-supplied exact quote instead?

**Measured, visible-Dev24 only.** Using the already-committed
`item1_locator` module and the committed manifest/ledger for identity (every
located span cross-checked against its ledger row before measuring; zero
holdout files opened), duplicate-occurrence rates across the 24 visible
spans:

| granularity | firms with ≥1 duplicate | dup-rate: min / median / mean / max |
|---|---|---|
| short capitalized phrase (1–4 words, "bare-name"-like) | 24/24 | 8.90% / 15.33% / 15.14% / 19.01% |
| 6-word sliding window | 24/24 | 0.09% / 0.74% / 1.13% / 4.36% |
| 10-word sliding window | 21/24 | 0.00% / 0.33% / 0.55% / 2.81% |
| 15-word sliding window | 17/24 | 0.00% / 0.13% / 0.30% / 1.93% |

Bare/short quotes collide often enough (~1 in 6–7) that "not a bare product
name" is a load-bearing prompt requirement. Ambiguity falls sharply as
quotes lengthen but never reaches zero — 17/24 firms still have at least one
duplicated 15-word window — so a refuse-on-ambiguity path is a regularly
reachable code path across this cohort, not a theoretical one. Illustration
(ASAN, visible): `"Asana Work Graph,"` occurs 4 times verbatim, each with a
distinguishable continuation; the bare phrase is genuinely ambiguous, and a
quote extended to its surrounding clause resolves to exactly one occurrence.

**Decision: retire model-supplied offsets.** The model supplies
`evidence_quote` only. The adapter finds every occurrence of the quote in
the ledger-anchored span (see below) and accepts only when there is exactly
one. This removes a task models are unreliable at while keeping every
guarantee v0.1 had: the adapter never trusts an unverified offset, because
there no longer is one to trust — either the derivation is unambiguous or it
refuses.

**Overlap-aware search, not `str.count`.** `"aaaaa".count("aaa")` is `1`
(Python's `str.count` is non-overlapping), but `"aaaaa"` genuinely contains
three overlapping `"aaa"` occurrences at offsets 0, 1 and 2. Using `count()`
as the ambiguity test would silently accept a match at an arbitrary one of
several true occurrences. `_find_all_occurrences` instead advances the
search cursor by 1 (not by the match length) after each hit, so every
overlapping occurrence is counted; zero → `evidence_quote_not_found_in_span`,
exactly one → derive `char_start`/`char_end`, two or more →
`evidence_quote_ambiguous_in_span`. Applied identically to `candidates` and
`excluded_mentions`.

**No fixed length minimum.** `evidence_quote` keeps `minLength: 1` and
nothing stronger — the measured table above shows disambiguation is a
function of contextual specificity, not raw length alone, and a fixed
character floor (e.g. 40) would be an uncalibrated guess dressed as a rule.
Specificity is a future prompt instruction; the schema stays permissive and
the adapter's exact-occurrence check is the real, complete enforcement
mechanism regardless of quote length.

**Everything else preserved, reimplemented not imported.** The fixed,
hash-pinned canonical ledger path and its tamper check before any ticker row
is extracted; the raw-bytes `model_output_sha256` computed before parsing;
the `legacy_source_id` and `span_text`-hash checks against the ledger; local-
ID existence/duplication validation; the topological product-then-
capability-then-task relationship rewrite; and the exact `candidate_id`
formula (anchored on `model_output_sha256`, unchanged) — all carried over
from v0.1 with identical behavior. `combined_candidate_adapter_v2.py` does
not import v0.1's module: the handful of shared helpers are reimplemented
locally so each version stays independently self-contained and auditable,
matching this repository's existing per-version module pattern (e.g.
`documentation_receipt_v4.py`/`v5.py`). v0.1's own byte-identity is
re-verified behaviorally in `test_combined_candidate_adapter_v2.py` — v0.1's
schema and ledger pins are re-hashed against its own committed files, and
its schema is asked to reject a candidate without `evidence_locator` — not
by diffing git history.

**Reason codes.** `evidence_quote_not_found_in_span` and
`evidence_quote_ambiguous_in_span` replace v0.1's `invalid_locator_bounds`
and `evidence_quote_containment_failed`, which have no meaning once there is
no model-supplied offset to bounds-check or verify containment against. The
other nine v0.1 codes carry over unchanged. Eleven total, a different set
from v0.1's eleven.

**Registry.** Two new entries in `schemas/schema_version_manifest.json`
(0.38.0 → 0.39.0, 88 → 90): `pct_dev30_v0_model_output_v2@0.2.0`,
`pct_dev30_v0_persisted_candidates_v2@0.2.0`. Neither is added to
`EVALUATION_SCHEMA_CONTRACTS` or `RELEASED_EVALUATION_CONTRACTS` in
`src/dynamic_ai_products/evaluation/schemas.py`, matching v0.1: Dev30 stays
outside the production evaluation-harness contract surface, and the adapter
hash-pins both its own schema files (and the shared canonical ledger, same
pin value as v0.1 since it is the same physical file).

**Scope.** Added: two successor schemas, `combined_candidate_adapter_v2.py`,
and its test file (50 synthetic cases — no real Dev30 firm text, visible or
holdout — including dedicated overlap-vs-`str.count` regressions and four
tests that re-verify v0.1's own byte-identity and behavior). Modified: the
schema registry, `REPO_MANIFEST.md` (786 → 790), the three manifest-count
tests, and `test_schema_registry.py`/`test_run_manifest_v2.py`'s pinned
manifest hash. `combined_candidate_adapter.py` and both v0.1 schema files
are unedited. This authorizes no extraction prompt, model call, or Dev30
score.

## ADR-100 — `pct_candidate_extraction_dev30_v1`: first prompt draft, development-only

**Status.** Development draft. Not released, not qualified, not authorized
for any model call. Creating this file authorizes nothing beyond its own
existence: no run, no gold label, no Dev24 (visible or holdout) evaluation.
Whether and when to run it, what protocol governs a run
(`docs/methodology/PROMPT_DEVELOPMENT_AND_EVALUATION_PROTOCOL.md`, the
Dev30-Visible/Dev30-Holdout split already on record), and how output would
be scored are separate, later decisions, each requiring its own explicit
authorization. This ADR grants none of them.

**What it is.** `prompts/extraction/pct_candidate_extraction_dev30_v1.md`
targets `pct_dev30_v0_model_output@0.2.0` (ADR-099's quote-only Stage 1):
one combined product/capability/task extraction call over one verified,
already-supplied Item 1 span, returning exactly one JSON object and nothing
else. It carries every rule fixed across the prior design rounds: local-ID
staging (`P`/`C`/`T`, products then capabilities then tasks) so no
`candidate_id` is asked of the model; a capability/task ontology matching
`docs/methodology/PRODUCT_CAPABILITY_TASK_ONTOLOGY.md` (task in
verb+object+outcome form, a product-independent `customer_need`, exactly one
product link and zero-or-more capability links); extraction is not limited
to AI-labelled content; the closed eight-token availability vocabulary with
roadmap/beta staying a candidate rather than an exclusion; evidence as an
exact contiguous verbatim quote with no offset request (ADR-099's
derivation happens after the call, not in it); the optional, non-exhaustive
`excluded_mentions` log under its closed four-reason enum; an explicit
prohibition list (no score, confidence, uncertainty, task role, screening or
classification decision, replicability or defensibility judgment,
deployment-scale estimate, AI-adoption metric, financial claim, or
post-period comparison); and the `zero_candidate_reason` biconditional.

**Style.** 1,049 core words (whitespace-split, fenced code blocks excluded —
the two illustrative JSON blocks are reference material, not prompt prose),
inside the requested 1,000–1,500 band. Model-agnostic: no named provider or
model. No firm-specific rule, no real Dev30 or holdout company name or
ticker, no historical exception catalogue — the one illustrative JSON
example uses a fictional company (Northwind) with no relation to any Dev30
or holdout firm.

**Tests, not a run.** `test_pct_candidate_extraction_dev30_v1_prompt.py` is
text-only: it reads the committed markdown file and the committed cohort
manifest (ticker list only) and asserts things about their content — the
declared contract and schema-version literals; the absence of
`char_start`/`char_end`; presence of the ontology, granularity,
availability, and exclusion rules; that the JSON blocks shown to the model
as its actual output target carry no field for any prohibited category
(checked separately from the prohibition prose, which correctly names those
categories in order to forbid them); the 1,000–1,500 core-word band; and
that no real Dev30 or holdout ticker or company name appears, checked
against the full 30-row manifest roster rather than a hand-typed subset. No
test opens a legacy filing, calls a model, or reads a holdout row.

**Scope.** Added: the prompt file and its test file. Modified:
`REPO_MANIFEST.md` (790 → 792), the three manifest-count tests. No schema
changed, so `schemas/schema_version_manifest.json` and
`test_schema_registry.py`/`test_run_manifest_v2.py`'s pinned hash are
untouched this round. `data/runs` and W3 are untouched; no holdout row was
opened to write this file.

## ADR-101 — Lineage aggregation: enumerated execution runs, not one run id

**Status.** Accepted. Fixture-first; no live request, no aggregate written
over `data/runs`, no packet built, no shell determined, no model called.

**Measurement.** The W3 v0.3 text-admitting lineage completed on 2026-08-18:
86 of 86 shards authoritative and bound, 8,526 accessions, 8,718 carrier rows,
17,052 requests, 24,180,231,616 retained bytes. It was assembled across
**seventeen** execution runs — r1 through r17, contributing 1, 1, 1, 3, 29, 1,
10, 1, 1, 1, 5, 5, 5, 5, 5, 5 and 7 shards. Aggregating it was then refused,
not by a bug but by the contract: `run_queue_aggregator` discovers shards
through `find_shard_run_dirs`, whose pattern anchors
`^{execution_run_id}-shard-NNNN$`, and
`acquisition_queue_aggregate_manifest@0.1.0` carries `execution_run_id` as a
single string. Empirically the prefix `…-r5` reaches 30 directories, `…-r17`
reaches 7, and the common stem `domestic-text-queue-execution-frame-v1`
reaches 0, because `-shard-` must follow the prefix immediately.

**Why seventeen runs, and why that is not an accident.** Two committed rules
produce fresh run ids faster than shards are consumed. First, run directories
are immutable: `create_run_directory` refuses reuse, so a shard that fails
cannot be retried under its own run id — r5's shard 35 was re-acquired as r6,
r7's shard 46 as r8, r9's shard 48 as r10. Second, every batch is separately
authorized, and an authorization names its own run id. A completed lineage is
therefore **intrinsically multi-run**, and a single-run aggregate can never
assert one. This is the ADR-095 assumption that reality did not meet.

**Decision: a successor, not a widening.** `@0.1.0` stays byte-identical and
keeps `execution_run_id`; `@0.2.0` is a new file carrying `execution_run_ids`
and no singular field, so under `additionalProperties: false` neither
generation validates as the other. `run_lineage_aggregator` sits beside an
untouched `run_queue_aggregator`, and `aggregate-acquisition-lineage` sits
beside an untouched `aggregate-acquisition-queue`. Nothing about the v0.1 path
moves: same mode name, same flag, same function, same output.

**The enumeration is the complete authority boundary.** Run ids are named
explicitly on the command line — `--execution-run-ids ea,eb,ec` — exactly as
the executor's `--shard-indices` names shard indices. There is no value that
expands to every run under an output root, no range syntax and no glob. An
enumerated id matching zero directories is refused as a typo rather than
silently contributing nothing. The list is parsed at the entrypoint, before
the aggregator is reached and therefore before any run directory could exist,
and the aggregator re-checks what it is handed; empty values, empty segments
and duplicates are each refused with their own message. Both modes refuse the
other's flag, so singular and plural can never be mixed in either direction.

**An unenumerated directory is invisible, structurally.** Isolation is not a
filter applied to a directory listing: discovery only ever asks
`find_shard_run_dirs` for a *named* run id, so a directory belonging to an
unenumerated run is never opened. It cannot reach authoritative selection, a
count, coverage, supersession or an output hash by any path — proven for four
shapes (a directory that would bind cleanly, a receipt-only one, one holding
malformed JSON, and one holding two files merely named like manifests), each
leaving the manifest byte-identical to the run without it. Enumerating that
same run changes the answer, which is what makes the isolation the
enumeration's doing rather than an accident of shape.

**Ambiguous authority is refused, never resolved.** Discovery across several
runs can find two candidate directories at one shard index. Both are bound,
so corrupt evidence still raises `ShardIntegrityError`; if both *bind*, the
aggregate is refused. Preferring the newest run would silently pick a winner
between two artefacts that each claim to be the same shard.

**Superseded directories are named, never counted.** A non-authoritative
directory at an index that is covered authoritatively *within the
enumeration* is recorded in `superseded_directories` with its receipt flag,
reason code, retained file count and bytes, and the run directory that
superseded it. Under v0.1 such a directory simply vanished from the aggregate's
view. `reason` is deliberately absent from these records: `no_run_directory`
is impossible where a directory exists, and handled-failure versus interrupted
is exactly `receipt_present`. The remaining correspondence is enforced **in
the schema**, not merely in code — a receipt present requires a non-empty
`failure_reason_code`, and its absence requires `null`.

**Ordering.** Shard record arrays are ordered by `shard_index`, independent of
the order the run ids were supplied, so two enumerations differing only in
order produce identical shard arrays. `execution_run_ids` itself is recorded
verbatim in the supplied order: it is the operator's authorization and is
reproduced rather than normalized.

**Limits.** This aggregate reports coverage. It authorizes no packet build, no
shell determination and no extraction, and it confers nothing on any run id it
does not list. A shard index holding several non-authoritative directories and
no authoritative one is **refused**, not represented by one of them: naming a
representative would make `shards_not_authoritative` depend on the order the
runs were enumerated, which the ordering invariant forbids, and no tie-break —
enumeration order, run-id order, timestamp — is evidence about which failure
describes the shard. `coverage_complete` is true only at the queue's full
shard count.

**Scope.** Twelve paths: the new v0.2 schema; the schema registry
(0.39.0 → 0.40.0, 90 → 91 entries); `acquisition_queue.py`;
`pipelines/00_build_company_universe.py`; the queue tests; this log;
`REPO_MANIFEST.md` (792 → 793); and the five evaluation guard modules whose
pinned registry hash and manifest counts move. The v0.1 aggregate schema is
byte-unchanged, verified by hash and by validating a v0.1 payload against it.

## ADR-102 — Full-cohort shell determination reads the lineage aggregate

**Status.** Accepted. Fixture-first; every lineage in the tests is synthesized
under a temporary root. No real cohort determination was run, no SEC request
made, no packet built, no model called.

**Measurement.** `run_shell_company_determination` takes one `--bundle-dir`
and reads that bundle's rows. The completed W3 v0.3 cohort is **8,718 carrier
rows across 86 bundles in 17 execution runs**, and the only artefact naming
them authoritatively is the ADR-101 aggregate
(`b78f35c7a813d30cd1113d19d348eba39213556f52bfb31ce224830bbd9298b6`,
`coverage_complete: true`). Two obvious routes are wrong before they are
tried: copying 8,718 primaries into one directory would make a second,
unhashed copy of 22.5 GiB of immutable evidence, and merging 86 bundle
manifests would fabricate an artefact no acquisition run wrote. The aggregate
already *is* the merge.

**Decision: read the aggregate, and read nothing else.** `--aggregate-manifest`
is the only data location `determine-shell-company-lineage` accepts. There is
no shard-output root, no bundle directory, no replay directory, no glob and no
search path, so there is nothing to scan *with*. Every directory the run opens
is exactly a `shards_authoritative[].run_dir` value from the validated
manifest, resolved against the repository root and never joined with an
operator-supplied prefix. A `run_dir` that is absolute, traverses a parent, or
resolves outside the repository root is refused before any open.
`superseded_directories` and `shards_not_authoritative` are **counted and
never resolved**: a nearby shard directory the aggregate does not name is
unreachable, because no code path constructs its name. Pinned by making an
unnamed shard directory unreadable and observing that the run still produces
byte-identical output.

**Full cohort means complete coverage.** `coverage_complete: true` is
required. A cohort assembled from 80 of 86 shards would under-count exclusions
without saying so, and partial coverage is refused rather than reported.

**Hash re-verification precedes every read.** For each authoritative record,
the bundle manifest and the acquisition manifest are re-hashed on disk and
compared to the aggregate's own record **before** any primary is opened. Hash
equality means the bytes read are byte-identical to the bytes the aggregate
bound, which is why the shard plans are not regenerated here — doing so would
require the queue definition and frozen carrier as inputs, pulling planning
into determination for a guarantee the recorded hashes already give. The
unchanged bundle loader then verifies every document's byte length and
SHA-256, and the unchanged `determine_for_row` reads the bytes.

**The record contract does not move.** Determinations are written under
`shell_company_determination@0.2.0` exactly as before, and a row determined
through the lineage path and through the single-bundle path yields an
identical record — asserted directly, field by field, against a single-bundle
run over the same fixture rows. Only the manifest describing the *run* is
versioned, because v0.2's single `bundle_manifest_sha256` cannot describe a
cohort spread over many bundles. `shell_company_determination_manifest@0.3.0`
binds the aggregate by path, hash and run id, the queue identity, the supplied
`execution_run_ids`, every consumed shard, the record-order constant, and the
ignored superseded and non-authoritative counts. v0.1 and v0.2 stay
byte-unchanged and neither validates a v0.3 manifest.

**Deterministic record order.** The JSONL is written in `shard_index`
ascending order, then in each bundle manifest's own entry order. Both keys
come from artefacts, never from an argument, and the order is **computed by
sorting on the shard index** rather than inherited from the aggregate's array
position — so it holds even for an array that arrived out of order. Permuting
`execution_run_ids` therefore changes the aggregate's own bytes and hence
`aggregate_manifest_sha256`, but cannot move a determination record: the JSONL
and its output hash are byte-identical, asserted directly.

**Fail-closed, before output creation.** Missing, malformed, wrong-contract or
partial aggregate; empty authoritative set; duplicate shard index or run
directory; escaping `run_dir`; missing or hash-mismatched bundle or
acquisition manifest; any bundle-loader failure; the same `(cik, accession)`
in two shards; carrier-provenance disagreement; and a bundle row count that
disagrees with the aggregate's `carrier_rows`. Each leaves no run directory.

**Outcome semantics unchanged.** `true` is a deterministic hard exclusion;
`false` and `unknown` are retained and assert nothing. `firms_excluded` equals
exactly the count of true determinations.

**Limits.** This determines one fact for one cohort. It authorizes no packet
build, no screening, no classification and no extraction, and it confers
nothing on a run id the aggregate does not list. The CLI anchors `run_dir`
resolution at the repository root, so a lineage outside that root is
unreachable through the entrypoint by construction; the success path is
exercised in-process against a synthetic root, and the CLI tests pin the
refusal surface and that anchoring. Recorded now and not repaired here: the
six plain-text primaries carry no `ix:nonNumeric` markup and will yield
`unknown` on `no_shell_fact_in_document`, retained rather than excluded, as
will shard 41's 179-byte document. That is a property of the corpus.

**Scope.** Twelve paths: the new v0.3 manifest schema; the schema registry
(0.40.0 → 0.41.0, 91 → 92 entries); `shell_company_determination.py`;
`pipelines/00_build_company_universe.py`; the Stage 00B-S tests; this log;
`REPO_MANIFEST.md` (793 → 794); and the five evaluation guard modules whose
pinned registry hash and manifest counts move.

## ADR-103 — Full-cohort Item 1 packets read the aggregate and the shell determination

**Status.** Accepted. Fixture-first; every lineage in the tests is synthesized
under a temporary root, determinations produced by the real ADR-102 runner
over that lineage. No real packet build was run, no SEC request made, no
model called, and `data/runs` is untouched.

**Measurement.** `run_baseline_packet_build` takes one `--bundle-dir`. The
completed W3 v0.3 cohort is 8,718 carrier rows across 86 bundles in 17
execution runs, screened by one shell determination that excluded 795 rows
and retained 7,923. Copying the primaries into one directory would duplicate
22.5 GiB as a second, unhashed copy of immutable evidence; merging 86 bundle
manifests would fabricate an artefact no acquisition run wrote. And the v0.2
packet-run manifest cannot describe the run either way: its
`bundle_manifest_sha256` names one bundle, and its `counts.firms_excluded` is
pinned to `{"minimum": 0, "maximum": 0}`, so a run excluding 795 firms cannot
validate under it.

**Decision: consume the two governing artefacts, and nothing else.**
`build-baseline-packets-lineage` takes `--aggregate-manifest`,
`--shell-determination-manifest` and `--config`. It has no directory argument
at all — no shard-output root, bundle directory, replay directory, glob or
search path — so every directory the run opens is exactly a
`shards_authoritative[].run_dir` value from the validated aggregate, and a
shard directory the aggregate does not name is unreachable. Superseded and
non-authoritative directories are never resolved.

**A neutral authority boundary, not a duplicate and not a cycle.** The
aggregate validation ADR-102 built lived inside
`shell_company_determination`, which imports this package's bundle loader; a
packet builder importing it back out of that module would have closed a
cycle. It moved to `ingestion/lineage_authority.py`, raising its own
`LineageAuthorityError`; `shell_company_determination.load_lineage_bundles`
became a thin delegate that re-raises as `ShellDeterminationError` with the
identical message, so its signature, return shape, refusal messages and
exception type did not move — proven by the ADR-102 test file passing
byte-unmodified. The import graph stays acyclic: `lineage_packet` →
{`lineage_authority`, `baseline_packet`, determination constants};
`shell_company_determination` → `lineage_authority` → `baseline_packet`.
`baseline_packet.py` itself is untouched.

**The two inputs bind relationally, never against a pinned literal.** No
production hash appears in source, schema or fixture. The aggregate's bytes
are re-hashed at run time and the determination manifest's recorded
`aggregate_manifest_sha256` must equal that recomputation; the determination
JSONL is re-hashed and must equal that manifest's own `output_hashes` entry;
every JSONL record must validate under the unchanged v0.2 record contract.
Shard binding is an **exact per-index tuple mapping** — `(shard_index,
run_dir, bundle_manifest_sha256, acquisition_manifest_sha256, rows)` —
identical between the aggregate's authoritative records and the
determination's consumed records. Mapping equality is the point: independent
set comparisons per column would pass two shards whose directories were
swapped between indices, and a test pins exactly that forgery being refused.

**Reconciliation before any output.** Every bundle row must have exactly one
determination record and every record must cite its own shard's bundle hash;
omissions, extras, duplicates and cross-shard mismatches are refused even
when the JSONL's recorded hash was forged to match, so the hash check is
never the only guard. Recomputed outcome tallies must equal the determination
manifest's counts; carrier provenance and route validation must agree across
all bundles and with the determination; every consumed bundle must declare
`baseline_primary_document_bundle@0.2.0`. All of it happens before
`create_run_directory`, so an input-integrity failure writes nothing.

**Only `shell_company == true` excludes.** `false` and `unknown` rows are
retained and packetized by the unchanged `build_packet`, so the ADR-097
plain-text route, passage normalization and admission-evidence forwarding are
reused rather than reimplemented. A retained document without a usable Item 1
is a per-row failure record in the failures JSONL — never an exclusion, never
a silent drop. The shell filter is per **row**, not per accession: one
registrant of a combined filing can be excluded while its sibling row, citing
the same source bytes, is retained — shared-accession rows are never merged.

**The record contract does not move.** Every packet stays
`universe_baseline_packet@0.2.0`, byte-identical to what the single-bundle
path builds for the same row (asserted by packet_sha256 equality), with all
five issuer flags null and basis `cover_page_evidence_not_yet_observed` — the
packet still has no cover-page route, and the shell result is bound in the
run manifest, never written into record fields it did not evidence.
`baseline_packet_manifest@0.3.0` binds the aggregate (path, recomputed hash,
run id, queue identity, verbatim `execution_run_ids`), the determination
(path, hash, run id, JSONL hash), per-shard consumption and exclusion counts,
and the record-order constant. v0.1 and v0.2 stay byte-unchanged and the
three generations mutually reject.

**Deterministic order.** Packets and failures are written in `shard_index`
ascending order, then in each bundle manifest's own entry order, after
shell-true omission. Both keys come from artefacts: permuting
`execution_run_ids` (which forces a fresh determination, since the aggregate's
bytes change) moves no packet byte — the JSONLs and their output hashes are
byte-identical, asserted directly.

**Total flag gating.** Every mode that does not consume a lineage-input flag
refuses it: `--aggregate-manifest` is accepted only by
`determine-shell-company-lineage` and `build-baseline-packets-lineage`, and
`--shell-determination-manifest` only by the latter. No mode silently ignores
either, swept mode-by-mode in the tests.

**Limits.** This builds Item 1 packets for one cohort. No screening,
classification, tier derivation or PCT extraction is performed, and no model
is called. The CLI anchors `run_dir` resolution at the repository root, so a
synthetic lineage outside it is unreachable through the entrypoint by
construction; the success path is exercised in-process against a synthetic
root. The real 7,923-row build is separately authorized and expects: planned
8,718, excluded 795, retained 7,923, packets plus failures equal to 7,923,
the six plain-text rows retained, and shard 41's 179-byte text document
surfacing as a per-row Item 1 failure rather than vanishing.

**Scope.** Fourteen paths: the new v0.3 packet-run manifest schema; the
schema registry (0.41.0 → 0.42.0, 92 → 93 entries); the new
`lineage_authority.py` and `lineage_packet.py`; the delegation in
`shell_company_determination.py`; `pipelines/00_build_company_universe.py`;
the new `tests/ingestion/test_lineage_packet.py`; this log;
`REPO_MANIFEST.md` (794 → 798); and the five evaluation guard modules whose
pinned registry hash and manifest counts move. `baseline_packet.py`, the
ADR-102 test file, the existing packet tests and every predecessor schema are
untouched.

## ADR-104 — Item 1 locator v3: the combined heading, and only it

**Status.** Accepted. Fixture-first; no packet rebuild, no `data/runs` write,
no SEC request, no model call. The full-cohort rebuild under the new locator
is a separate, future authorization.

**Measurement, phase by phase.** The ADR-103 full-cohort build left 730
Item 1 failures (`missing_item_one` 492, `ambiguous_end_boundary` 206,
`no_end_boundary` 32). A read-only audit of all 730, a frozen cohort built
under `adr104_bucket_method@1` (appendix below), and scratch ablations
measured what a deterministic successor could safely recover:

- **Phase 0 (frozen cohort).** Bound triple: method-definition sha256
  `b0ef02d3017a300071da304f324d54deae66f36023e6deb47d0aceaeb7ecd742`,
  mapping sha256
  `a686217450c4d08e4bc1bf0fa471f4efae5d6c38cc5544a8d8ea6455f0039840`,
  failure-JSONL sha256
  `34e5fc88f0e68062e281484e5ca73b31c336f226dcb82736224ab366486c2ac8`.
  Exact bucket counts over a proven 730-row partition: s1_plain_present 115,
  s2_combined 59, s3_single 188, s3_multi 18, n0_no_end_boundary 32,
  token_early_only 176, bare_numeric 58, other_worded 55, no_token 24,
  part_iv_financial_statements 5. S1 mechanism table over the 115:
  guard_rejected 69 (sampled contexts dominated by genuine inline
  cross-references the guard exists to refuse), stream_splitting 26,
  wording_only_s1a 19, plain_text 1.

- **A first, wider candidate failed its gates and was withdrawn.** An
  experimental v3 carrying S1 wording, the combined heading, and an S3
  running-header deduplication recovered 385 rows — but 31% of them were
  out-of-scope breadth, S1 reached only 28 of 115, and the dedup rule
  recovered all 18 multi-registrant rows with degenerate 1.2–7.8 KB spans:
  identical-title-with-no-intervening-Item-1 cannot distinguish a running
  header from a TOC-row/genuine-heading pair. The rule and the experiment
  were removed; **no dedup rule ships, and span size is an audit metric,
  never a parser rule.**

- **Arm B (v2 + S2 only), the accepted evidence.** 51 of the frozen 59
  combined-bucket rows recovered — G4-S2 floor ≥36 passed — 82 recoveries in
  total (the 31 outside the bucket each individually rule-attributed to the
  combined pattern; the 15%-proxy had mis-bucketed them). 81 recovered
  spans end at Item 1A and one at Item 1B — both authorized tiers; min
  57,451 B, median 273,636 B, max 2,126,037 B;
  none below 4 KB or 0.5% of its document. G1: 7,190/7,190 prior HTML spans
  byte-identical. G2: 238/238 ambiguous and no-end rows re-raise v2's
  exception with identical reason code and message — all 18 multi-registrant
  rows among them. G3: zero unattributable recoveries.

**Decision: ship S2 alone.** `find_item_one_span_v3` calls
`find_item_one_span_v2` first and returns its result unchanged; only
`item_span_not_found` enters the retry; `ambiguous_end_boundary` and
`no_end_boundary` re-raise unchanged — the original exception object
propagates. The retry admits exactly one start shape, the block-opening
combined `Items 1 and 2 [.:-] Business and Propert…` heading with the
measured optional dots and ampersand spelling, and ends at Item 1A then
Item 1B under v2's single-candidate rule. **The Item 2 tier is never used on
the retry**: Item 2 lies inside the merged section, so a later Item 2 token
cannot truncate it; a combined section followed by neither boundary fails
closed as `no_end_boundary`. The Item 3 tier is deliberately absent, so the
packet record's closed `end_boundary_kind` enum never widens and
`universe_baseline_packet@0.2.0` is untouched. Not implemented, by
measurement rather than omission: S1a (19 of 115 — under any plausible
floor), S1b (its dominant mechanism is contaminated with legitimate
refusals), S3 in any form, broad guard relaxation, and every historical
heuristic.

**The locator is selected, never defaulted and never free text.** The
lineage packet mode requires `--item-one-locator`, a closed functional
selector over exactly
`{"item_one_span_v2": find_item_one_span_v2, "item_one_span_v3":
find_item_one_span_v3}`: the callable comes only from that mapping, an
unmapped value — including whitespace variants and function names — is
refused before any output directory exists, and the v0.4 manifest records
the canonical key re-derived from the selected entry. No caller-supplied
callable exists. `build_packet` gains a keyword-only `locate_html`
defaulting to v2, so the single-bundle path is behaviorally unchanged; the
plain-text route is selector-independent and its three cohort packets stay
byte-identical.

**Succession.** v1, v2 and the plain-text locator bodies are byte-identical.
`baseline_packet_manifest@0.4.0` adds exactly one required field to v0.3 —
`item_one_locator`, enum-closed to the two canonical keys — and v0.3/v0.4
mutually reject under `additionalProperties: false`; the ADR-103 artifact
remains valid under v0.3 alone. Registry 0.42.0 → 0.43.0, 93 → 94 entries.

**Acceptance replay.** An opt-in test
(`ADR104_ARMB_REPLAY=1`) replays the Arm B gates against the pinned
artifacts with the production locator and fails the implementation if any
gate differs from the measured result above. A companion always-on test pins
the appendix below to the Phase-0 method hash, so the frozen cohort's
authority survives byte-for-byte or the evidence is declared invalid.

**Measurement appendix — `adr104_bucket_method@1`** (normative; sha256
`b0ef02d3017a300071da304f324d54deae66f36023e6deb47d0aceaeb7ecd742` over
exactly the block between the markers):

<!-- ADR104-METHOD-BLOCK-BEGIN -->
adr104_bucket_method@1
======================

Frozen bucket method for the 730-row ADR-103 packet-failure cohort.
Input: baseline_packet_failures.jsonl (sha256
34e5fc88f0e68062e281484e5ca73b31c336f226dcb82736224ab366486c2ac8), with each
row's source document and representation resolved solely through the packet
manifest's shards_consumed bundle entries.

1. Probe stream.
   html rows: the raw document bytes with every HTML tag replaced by one
   space and every entity replaced by one space, applied in this order:
     tag pattern     (bytes, DOTALL not set):  <[^>]*>
     entity pattern  (bytes):                  &[#a-zA-Z0-9]{1,8};
   plain_text rows: the raw document bytes unmodified.
   n = max(1, len(stream)).

2. Probe expressions (bytes patterns, case-insensitive where written (?i)).
   ITEM1_ANY:   (?i)\bItems?\s{0,20}1\b
   Context extraction: for a match m, ctx = the 90 bytes
   stream[m.start():m.start()+90], whitespace runs collapsed to one space
   (regex \s+ -> " "), decoded UTF-8 with errors=replace, lowercased.
   Context classifiers, applied to ctx with re.match (anchored at start):
     S2_COMBINED:  items? 1\.? ?(?:and|&) ?2\b
     S1_PLAIN:     items? 1[\.\:\-‐-―]? ?(?:description of )?business
     PART_IV:      the substring "financial statement" occurs in ctx[:60]
     OTHER_WORDED: items? 1[\.\:\-‐-―]? ?[a-z]
   (‐-― is the unicode hyphen..horizontal-bar range.)

3. Body region. A token match is in the body region iff
   m.start() / n >= 0.15. This is a proxy threshold, not a proof of
   table-of-contents membership.

4. Bucket priority order (first matching rule assigns the bucket; every row
   receives exactly one bucket):
   a. reason_code == "ambiguous_end_boundary":
        "s3_multi"  iff the row's accession appears on more than one failure
                    row within the 730-row set, else
        "s3_single".
   b. reason_code == "no_end_boundary": "n0_no_end_boundary".
   c. reason_code == "missing_item_one": let B = ITEM1_ANY matches in the
      body region.
        B empty and no ITEM1_ANY match anywhere -> "no_token"
        B empty but an early ITEM1_ANY match exists -> "token_early_only"
        else, with ctx taken from the LAST match in B, first of:
          S2_COMBINED matches ctx          -> "s2_combined"
          S1_PLAIN matches ctx             -> "s1_plain_present"
          PART_IV holds                    -> "part_iv_financial_statements"
          OTHER_WORDED matches ctx         -> "other_worded"
          otherwise                        -> "bare_numeric"

5. Representation handling. representation is read from the bundle entry
   ("html" or "plain_text"); it is never inferred from document content.

6. Canonical mapping serialization. The mapping is the UTF-8 JSON array of
   one record per failure row, each record exactly
   {"accession": <accession>, "bucket": <bucket>, "cik": <cik>},
   the array sorted lexicographically by (cik, accession), serialized with
   json.dumps(records, sort_keys=True, separators=(",", ":")) and NO trailing
   newline. The mapping sha256 is computed over exactly these bytes.
<!-- ADR104-METHOD-BLOCK-END -->

## ADR-105 — Deterministic asset-backed-issuer determination, evidence-first

**Status.** Accepted. Fixture-first; no live determination run, no packet
rebuild, no SEC request, no model call, no `data/runs` write. The live
cohort run — and the pipeline entrypoint it would require — are separate,
future authorizations.

**Why this flag, and why now.** The Item 1 length audit over the 7,193-packet
artifact flagged 947 packets with degenerate spans, and the failure audit
before it showed Part-IV-only and instruction-omitted filings among the 730
failures: asset-backed issuers file 10-Ks that legitimately omit Item 1
under General Instruction J and disclose under Regulation AB instead. Those
filings are not short *businesses*; they are a different filing shape, and
`issuer_filters` has always reserved the `ASSET_BACKED_ISSUER` reason code
for them without any deterministic rule ever earning it. This increment adds
the rule — and nothing else.

**Decision: two positive conditions, both required, in the same filing.**
`asset_backed_issuer` is `true` only when the document carries **(1)** a
**non-negated Item 1 / Part I omission construction tied structurally to
General Instruction J** — one contiguous expression, omission verb
(`omitted`, `not included`, `not applicable`) immediately joined by
`pursuant to / in accordance with / in reliance (up)on / under` to
`General Instruction J`, with an `Item 1` or `Part I` reference in the 150
bytes before the construction and no negator in the 40 bytes before it —
**and (2)** a structural Regulation AB signature: at least one
**block-opening** `Item 1112/1114/1115/1117/1119/1122/1123` heading under
the same `_starts_a_block` guard the Item 1 locator uses (line-start for
plain text). A first draft accepted `pursuant to` as an omission token
inside a 400-byte proximity window and any textual Item 11xx mention; it
returned `true` for operating-company prose of the form "…pursuant to
General Instruction J for administrative reasons, but no Item 1 section is
omitted. Our securitization note refers investors to Item 1122…" and was
corrected before staging — that exact prose is now a pinned regression, as
are a genuine omission beside only inline Regulation AB prose, a bare
`pursuant to General Instruction J`, and a negated omission construction.
Every `true` record preserves the source SHA-256, the **exact minimal
matched span** of each condition — never a surrounding window — as
half-open raw-byte offsets computed through the same offset map the Item 1
locator uses, plus the quote, the rule id
`instruction_j_omission_and_reg_ab_items@1`, and the reason code
`ASSET_BACKED_ISSUER` verbatim. The **offsets are authoritative**: the quote
is the deterministic tag/entity/whitespace-normalized rendering of the raw
span through the locator offset-map stream, so where the span contains HTML
entities — `Item&nbsp;1112`, measured on 95 of the 351 dry-run trues — the
quote (`Item 1112`) is not raw-byte-equal to the slice, and normalizing the
slice reconciles them exactly; a synthetic entity regression pins this.

**The only other outcome is `unknown`, and `false` does not exist.** Absence
of the signature is absence of evidence, never evidence of an operating
company. Either half-condition alone stays `unknown`
(`general_instruction_j_only`, `regulation_ab_items_only`), and so do the
look-alikes measured to matter: an operating company discussing
securitization or asset-backed securities, a trust-styled name, and a short
Item 1 — **no word count, span length, or source-size ratio is ever
consulted**, pinned by a test that pads a document five-thousand-fold and
requires the identical determination. The record schema enforces both
directions conditionally: `true` without full evidence is invalid, and the
exclusion code can never ride on `unknown` — so the evidence requirement
cannot be routed around by setting a generic flag, and the five-flag
`issuer_filters` contract is untouched.

**Authority and shape.** The module consumes only the ADR-101
aggregate-authorized, local, hash-verified primaries through the shared
`lineage_authority` boundary — no glob, no alternate shard root, every
bundle and primary re-hashed before any byte is read, unenumerated shards
invisible (pinned by the chmod-intruder test). One record per carrier row,
written in shard-index-then-bundle-entry order, write-once, deterministic
across run ids. Two new contracts:
`asset_backed_issuer_determination@0.1.0` (record) and
`asset_backed_issuer_determination_manifest@0.1.0` (lineage run manifest,
binding the aggregate by path, recomputed hash and run id, and embedding the
rule constants). The manifest and the shell-determination manifests mutually
reject. The sibling shell module, its three manifest schemas, its two record
schemas, and its live artifact are byte-identical — asserted by test.

**Scope.** Twelve paths: the new module, its two schemas, the registry
(0.43.0 → 0.44.0, 94 → 96 entries), the new test module, this log,
`REPO_MANIFEST.md` (799 → 803), and the five evaluation guard modules.
Deliberately absent: a CLI mode (the live run is unauthorized, and wiring an
entrypoint is its own gated increment), any change to
`shell_company_determination`, `issuer_filters`, packet contracts, or
`data/runs`.

## ADR-106 — CLI entrypoint for the lineage asset-backed determination

**Status.** Accepted. **CLI wiring only: this ADR authorizes no live
determination**, writes nothing under `data/runs`, and changes no detector
logic, schema, registry entry, or manifest count. ADR-105's detector and
schema decisions stand unchanged.

**Why.** ADR-105 shipped the determination as a library deliberately without
an entrypoint, because the live cohort run was (and remains) its own gated
authorization. A governed run, when authorized, must go through a pipeline
mode with the same flag discipline as every other lineage consumer — not a
hand-written script. This increment adds exactly that mode:
`determine-asset-backed-issuer-lineage`.

**Shape.** The mode's only evidence-location input is `--aggregate-manifest`;
it uses the global `--output-dir`, `--run-id` and `--dry-run`, requires the
aggregate file to exist before anything runs, and calls
`run_asset_backed_determination` with the repository root and an injected UTC
clock. Its summary is the governed JSON shape: run_id, dry_run, run_dir,
aggregate_manifest_sha256, counts, reconciliation, manifest_path.
`--aggregate-manifest` is now accepted by exactly the three lineage
consumers — shell determination, asset-backed determination, and the packet
build — and by nothing else; the new mode refuses every other data-location
flag (`--bundle-dir`, `--shard-output-dir`, `--queue-definition`,
`--replay-dir`, plus the sentinel/frame/acquire/dera/config families) and
the other modes' lineage inputs (`--shell-determination-manifest`,
`--item-one-locator`). Repo-root anchoring of shard resolution is inherited
from the library and pinned by a CLI test, exactly as for the sibling modes.

**Scope.** Four paths: the pipeline entrypoint, this log, and the two test
modules (CLI coverage in the asset-backed module; the all-mode flag sweeps in
the lineage-packet module updated so the new mode is treated as an aggregate
consumer while still proving it rejects the shell-determination and locator
flags). No schema, registry version/count, or `REPO_MANIFEST` count moves:
no new file is introduced.

## ADR-107 — Two-determination lineage packet successor

**Status.** Accepted. Fixture-first; no live packet rebuild, no `data/runs`
write, no SEC or model call. The real cohort rebuild under this successor is
a separate, future authorization.

**Why.** The full-cohort screening now has two governed deterministic
exclusions: the ADR-102 shell determination (795 true) and the ADR-105
asset-backed-issuer determination (351 true, measured overlap 0 — the two
signatures are structurally disjoint: shells assert a cover-page fact,
asset-backed issuers omit Part I under Instruction J). The ADR-103/104
packet builder consumes only the shell determination, so a rebuilt cohort
would still packetize 351 rows whose Item 1 the filer legitimately omitted.
A successor consumes both.

**Decision: a new generation beside an untouched predecessor.**
`run_lineage_packet_build` and `build-baseline-packets-lineage` are retained
byte- and behavior-identical, still emitting the v0.4 manifest.
`run_lineage_packet_build_v2` and `build-baseline-packets-lineage-v2` are
the successor: a carrier row is excluded **iff** its shell determination or
its asset-backed determination is the literal `true`. `false` and `unknown`
always remain eligible — every shell-unknown and asset-backed-unknown row is
retained — and **packetization establishes nothing beyond a locatable
Item 1**: it does not establish software eligibility. Packet records keep
`universe_baseline_packet@0.2.0` with all five issuer flags null; the
determinations are bound at run-manifest level, never written into
evidence-less packet fields.

**Authority and binding.** The aggregate remains the sole authority for
which directories may be opened (shared `lineage_authority` boundary; no
glob, no alternate roots; unenumerated shards invisible, pinned by the
chmod-intruder test). Each determination is independently validated against
its own manifest and record contracts, its JSONL re-hashed against its own
`output_hashes` entry and required to be sound UTF-8, and bound relationally
to the supplied aggregate: recomputed aggregate SHA, aggregate run id, queue
id, queue-definition SHA, carrier provenance, and the exact per-shard tuple
mapping `(shard_index, run_dir, bundle_manifest_sha256,
acquisition_manifest_sha256, rows)`. Each JSONL must hold **one and only
one** record per aggregate `(cik, accession)` row, each citing its own
shard's bundle hash — duplicates, omissions, extras, swapped hashes,
mismatched aggregates, and malformed records all refuse before
`create_run_directory`. Recomputed outcome tallies must equal each
manifest's own counts. No live hash or count is hard-coded anywhere.

**Manifest transparency.** `baseline_packet_manifest@0.5.0` binds both
inputs (path, manifest SHA, run id, JSONL SHA each) and records the
**five-way exclusion accounting both cohort-wide and per shard**:
`shell_true`, `asset_backed_true`, `both_true`, `shell_only_true`,
`asset_backed_only_true` appear in the cohort counts and in every
`shards_consumed[]` record alike, beside `firms_excluded` (the union,
exactly `shell + abs − both`), `retained_rows`/`rows_retained`,
`packets_built`, `packet_failures`. Reconciliation identities prove both
determinations partition the planned rows, the union arithmetic, excluded +
retained = planned, packets + failures = retained, per-shard sums equal to
cohort totals, and — per shard — `shell_only + both = shell`,
`abs_only + both = abs`, `excluded = shell_only + abs_only + both`,
`excluded + retained = rows`, `built + failed = retained`. The arithmetic is
beyond JSON Schema's reach, so the runner's reconciliation is the guard and
refuses before writing; a regression forges one per-shard value to pin
exactly that division of labor. Records are written in shard-index-then-bundle-entry order after
union-exclusion omission (`…_after_union_exclusion`). v0.1–v0.4 stay
byte-identical; v0.4 and v0.5 mutually reject (the single-determination
binding fields are replaced by the two named bindings, and the per-shard
record shape differs).

**CLI.** The successor requires `--aggregate-manifest`,
`--shell-determination-manifest`, `--asset-backed-determination-manifest`,
`--item-one-locator` (the ADR-104 closed selector, unchanged) and
`--config`; it refuses every directory/replay/queue input. The new
asset-backed flag is refused by every other mode, the shell-only packet mode
included; total gating is preserved and swept mode-by-mode in the tests. The
entrypoint docstring's mode count moves to nineteen.

**Expected live accounting — a preflight check only, never a source
constant**: 8,718 planned rows; shell true 795; ABS true 351; observed
overlap 0; exclusion union 1,146; retained 7,572. This increment runs no
rebuild.

**Scope.** Twelve paths: `lineage_packet.py` (successor appended; v1
function untouched), the new v0.5 schema, the registry (0.44.0 → 0.45.0,
96 → 97), the pipeline, the lineage-packet tests, this log,
`REPO_MANIFEST.md` (803 → 804), and the five evaluation guard modules.

## ADR-108 — Production high-recall screen over the lineage packet cohort

**Status.** Accepted. Fixture-first and mock-only: this increment calls no
live model, makes no SEC or network request, writes nothing under
`data/runs`, and rebuilds no packets. The 100-packet canary and the full
7,042-row run are separate, future authorizations that will name the model
route, pricing and both request caps explicitly.

**Why.** The sentinel screen is fixture-bound: it consumes hand-built
`BaselineEvidencePacket` fixtures and no code consumed the canonical v0.5
packet artifact at all. Gate B needs a production successor that screens the
real cohort — every valid Item 1 packet — while keeping the 530 packet-build
failures visible instead of silently dropping the firms they represent.

**Decision: one authority, two record kinds, three statuses.**
`universe/lineage_screen.py` consumes exactly one named
`baseline_packet_manifest@0.5.0` — never a directory scan or glob. Before
any output directory or provider call: the manifest's bytes are re-hashed,
both JSONLs are re-hashed against the manifest's own `output_hashes` and
UTF-8-guarded, every packet record is re-validated against
`universe_baseline_packet@0.2.0`, the failure rows are checked against their
closed seven-key shape, and the partition (packets + failures = retained
rows, `(cik, accession)` unique, no overlap) is re-proven. All bindings are
relational; no production hash appears in code, schema or fixture. Every
retained row becomes exactly one `universe_screen_record@0.1.0`:
`screened_packet` (non-null filing date from the packet, one of the three
closed statuses LIKELY_ELIGIBLE | LIKELY_INELIGIBLE | BOUNDARY_OR_UNCERTAIN,
packet SHA, prompt SHA, model route, raw-response binding, validated
evidence) or `insufficient_evidence` (null filing date — the v0.5 failures
JSONL is the only authority for these rows and it measurably carries no
date, so none is derived from a carrier or any other source; null status —
INSUFFICIENT_EVIDENCE is a roll-up state, never a fourth model status;
original failure reason and detail preserved; every model field null). The
schema conditionals make the kinds mutually rejecting.

**Evidence-minimal rendering.** The model sees CIK, accession, form, filing
date, the packet cutoff, and the verbatim Item 1 passages with
source/passage identifiers — never a company name, ticker, exchange or SIC
code. The committed prompt template is unmodified (its placeholders are
generic); the production renderer fills them minimally, and the template
plus the untouched sentinel `screening.py` are hash-pinned as predecessors.
Deterministic SIC stratification, if used for the canary, happens outside
the model entirely.

**Raw-response authority.** Every received raw response is appended to
`universe_screen_raw_responses.jsonl` verbatim — before any parsing or
validation — as `{raw_response_id = <run_id>-<cik>-<accession>, cik,
accession, raw_response, raw_response_sha256 over the exact original
bytes}`, fsynced per line so a mid-run failure retains every captured
response. The screen manifest's `output_hashes` covers the records JSONL
and the raw archive both; each screened record binds its archive entry by
id and SHA, and the runner re-reads the archive from disk and re-derives
every binding before writing anything else.

**Fail-closed semantics.** A successful run directory holds exactly three
files, and `universe_screen_manifest.json` is written last: its presence
plus its hash bindings are what make a run authoritative. On the first
terminal provider error, invalid model JSON, adapter rejection,
quote-resolution failure, temporal violation or attempt-cap breach, the run
stops: no records JSONL, no manifest — only the raw archive captured so far
plus `universe_screen_failure_receipt.json` (module-governed shape, the
acquisition-receipt precedent; closed five-reason vocabulary). Pinned
counters: `records_completed_before_failure = k - 1` always; on a provider
terminal error no raw exists for the stopping row, so
`raw_responses_captured = k - 1`; on invalid JSON, adapter, quote or
temporal errors the raw was archived before parsing, so it is `k`.
`require_authoritative_screen_run` refuses receipt-bearing, manifest-less
and hash-mismatched directories, so no partial run is consumable by a
SCREEN release or classifier loader. Run directories are write-once in
success and failure alike; a retry needs a new run id and new
authorization. An internal reconciliation failure raises instead of
writing a receipt — the vocabulary describes row-level stops only — and
still leaves no manifest.

**Request accounting (contract B).** `logical_request_cap` must equal the
valid-packet count exactly (7,042 full run, 100 canary — preflight facts,
never source constants); `provider_attempt_cap` is declared separately and
must equal logical × (1 + 2 bounded transient retries). A retry never
creates a second logical record; only the final received response enters
the archive. The manifest records both caps, both made-counters,
`rows_retried` and nullable token totals (null under the mock).

**Firm roll-up.** `eligible_over_boundary_over_ineligible_failsafe@1`,
pinned as a manifest const: LIKELY_ELIGIBLE > BOUNDARY_OR_UNCERTAIN >
LIKELY_INELIGIBLE per CIK; any eligible or boundary packet prevents
firm-negative treatment; a CIK with no valid packet rolls up to
INSUFFICIENT_EVIDENCE — non-negative, visible in the manifest counts, and
excluded from later classifier call lists (insufficient rows are never
model-called; the mock's call counter proves it). Shared accessions stay
separate rows per CIK; firms are never merged.

**CLI.** One new mode, `screen-universe-lineage`, requiring
`--packet-manifest`, `--provider` (mock only in this increment),
`--screen-fixture`, `--logical-request-cap` and `--provider-attempt-cap`,
with dry-run support (full validation and rendering, no provider call, no
write). All four screen flags are totally gated: every other mode refuses
them, and the screen mode refuses every other data location. The
entrypoint's mode count moves to twenty. `providers/*` is untouched; the
live route binding is the canary increment's decision.

**Boundaries.** Screen only: no classifier, no tiers, no PCT/Dev30 field
anywhere, no live model call, no `data/runs` write. The sentinel modules
(`screening.py`, `classification.py`, `runner.py`, `models.py`, `rules.py`,
`review.py`, `audit.py`, `freeze.py`, `packets.py`, `taxonomy.py`), both
discovery prompts, `providers/*`, and every packet/determination/aggregate
schema and ingestion module are byte-unchanged. The universe→ingestion
import boundary holds: the screen re-implements manifest loading against
the committed schemas and pins its filename constants equal to the
ingestion originals by test.

**Scope.** Thirteen paths: `universe/lineage_screen.py`, the two new
schemas (`universe_screen_record`, `universe_screen_manifest`), the
registry (0.45.0 → 0.46.0, 97 → 99), the pipeline entrypoint,
`tests/universe/test_lineage_screen.py`, this log, `REPO_MANIFEST.md`
(804 → 808), and the five evaluation guard modules.

## ADR-109 — Governed Vertex/Gemini binding for the lineage screen

**Status.** Accepted. Fixture-first and offline: this increment calls no live
model, builds no real SDK client, resolves no credential, makes no network
request, and writes nothing under `data/runs`. The 100-packet canary and the
full-cohort live run remain separate, future authorizations.

**Why.** ADR-108 shipped the production screen mock-only. Gate B needs the
governed Vertex/Gemini stack bound to the same screen contract so a
separately authorized canary can run — without touching the predecessor, the
provider stack, or the extraction stack.

**Decision: an explicit successor beside an untouched predecessor.**
`run_lineage_screen`, its mock path, `universe_screen_record@0.1.0`,
`universe_screen_manifest@0.1.0` and the ADR-108 test module keep their exact
behavior; the live route is `src/dynamic_ai_products/lineage_screen_live.py` —
`run_lineage_screen_live` plus the adapter, selection builder, cohort budget
and promotion gate. It imports the predecessor's loader, renderer, row
validator and roll-up so the validation logic cannot drift, and pins the
predecessor files by SHA-256 so a silent edit is loud. A parity test proves
the mock path and the live path produce identical model-derived record
fields from identical model text.

**What a live authorization binds** (`universe_screen_live_authorization@0.1.0`,
runtime-only, never committed): the packet cohort (`packet_manifest_sha256`)
+ the selected rows or full-cohort mode (`selection_artifact_sha256`,
`selection_kind`) + the prompt bytes (`prompt_template_sha256`, the SHA-256
of the exact committed `prompts/discovery/universe_high_recall_screen.md`,
re-verified against the current committed bytes at preflight and recorded
again in the v0.2 manifest) + the provider client contract (canonical
digest, recomputed from the connector's own declared contract) + the
enablement (reference plus sha) + the endpoints (allowlist equality across
connector, authorization and enablement) + the model route + the caps and
budgets (logical, attempt, external, token, cost, wall-clock) + the
committed retry/rate-limit policy versions. A run under any different value
is a different authorization, refused before a run directory, an SDK
import, credential resolution, or any network send exists. The canary
arithmetic is schema-pinned: canary_100 carries exactly 100 logical
requests, 300 generate attempts, 400 external requests, controlled_pilot.

**Selection authority** (`universe_screen_selection@0.1.0`). A canary_100
selection enumerates exactly one hundred `(cik, accession, packet_sha256)`
rows bound to the named v0.5 manifest SHA under
`seeded_stratified_quartiles@1` — representation × filing-date quartile ×
packet-byte-size quartile, largest-remainder allocation, per-stratum seeded
sampling; packet-native only, no SIC carrier, no external authority
(resolutions 1 and 2 of the plan approval). full_cohort is the explicitly
different mode: it enumerates nothing, because the packet manifest is the
row authority. The live runner accepts exactly one named artifact and
refuses foreign rows, drifted packet SHAs, duplicates, wrong counts and
cross-cohort bindings. `require_promotable_screen_run` accepts only a live
full-cohort manifest: a canary is a measurement run and is structurally
non-promotable to a SCREEN release; a mock v0.1 run has no selection block
and is refused the same way.

**The enablement chain** (`universe_screen_adapter_enablement@0.1.0`). The
connector's three-list handshake gets a genuine independent third list: a
standing capability record referenced by the authorization by (reference,
sha), pinning the same client-contract digest and the same two operation
endpoints. It inherits no extraction prompt/stage semantics — the screen has
no prompt-qualification layer; the prompt binds through the authorization's
hash instead. As with ADR-035, this buys detectability, not prevention.

**Retry ownership and accounting.** The connector's tenacity loop is the
single retry owner; the adapter never raises the screen's transient error,
so double retry is structurally impossible. One logical request per selected
packet; at most 3 generate attempts per row; 1 countTokens + ≤3 generate
sends per row; external cap = logical × 4. Attempt truth comes from the
capture ledger, not a loop counter — a failed run's receipt reports the
stopping row's real sends.

**Dual raw authority.** The screen raw archive keeps ADR-108's rule exactly:
final verbatim model *text*, archived before parsing. The wire envelopes —
every count and generate attempt body — persist write-once under
`provider_captures/` before the next send (the extraction sink's rule,
reimplemented screen-side; a persistence failure permits no further send).
The capture ledger is the complete file mapping: every referenced file is
re-hashed and an orphan walk runs both before the v0.2 manifest is written
and again inside the promotion gate. Records + archive are the row-level
model-output authority; ledger + envelopes are the attempt-level wire
authority. Reconciliation proves count + generate captures == external
requests, generate captures == provider attempts, and every archived
response equals the text extracted from its terminal hash-verified envelope
under `vertex_generate_content_candidates0_text_parts@1` (exactly one
candidate; every part a string text; blocked, empty, malformed,
multi-candidate, part-less and truncated envelopes are terminal).

**Cohort budget.** `ScreenCohortBudget` — the narrow screen wrapper of
resolution 1 — owns cumulative input tokens, settled cost, external sends
and wall clock against the authorization budgets and mints the one-shot
admissions itself; extraction's per-record session is not the cohort
authority. Pricing is the committed exact-integer rule in
`extraction.count_reconciliation`; no price appears in any schema or
authorization. Settlement is conservative: usage cost when the usage block
verified on a single attempt, else the per-attempt ceiling times attempts
made.

**Import boundary.** The live binding is a top-level composition module
(`src/dynamic_ai_products/lineage_screen_live.py`, beside `provenance.py`
and `workflow.py`), because the committed E-P boundary guards forbid any
module under `universe/` — or the other three data packages — from
referencing `providers` or `extraction` at all. Both guards stay
byte-identical and at full strength: universe still imports neither
stack, `lineage_screen.py` is untouched, an AST test pins that no
universe module gained such an import, `sdk_factory` remains the only
`google.*` importer, and the offline tests prove the live path adds no
google module to a shared process plus, in a fresh subprocess, that the
preflight never imports it at all.

**One narrowly scoped mechanical exception.** ADR-108's test module
`tests/universe/test_lineage_screen.py` pinned the registry literally
(0.46.0, 99 entries), which no ADR-109 implementation can satisfy while
registering its four schemas. Under explicit authorization, exactly two
literals in `test_registry_registers_the_two_screen_schemas` were
rebaselined (0.46.0 → 0.47.0, 99 → 103) — no other byte of the module moved,
and the live suite's byte-identity pin freezes the rebaselined bytes.

**Scope.** Sixteen paths: `src/dynamic_ai_products/lineage_screen_live.py`, the four new
schemas (selection, adapter enablement, live authorization, manifest v0.2),
the registry (0.46.0 → 0.47.0, 99 → 103), the pipeline entrypoint (two new
modes, twenty-two total, total gating), `tests/universe/test_lineage_screen_live.py`,
the two-literal rebaseline above, this log, `REPO_MANIFEST.md` (808 → 814),
and the five evaluation guard modules. `providers/*`, `extraction/*`, both
prompts, every packet/determination/aggregate schema and ingestion module,
and everything under `data/runs` are byte-unchanged.

**Correction (2026-08-20) — the output ceiling is now enforced
pre-send.** As merged, `budget_max_output_tokens` was recorded and
schema-required but never spent against: no send was ever refused by
it. Corrected in place, three paths (`lineage_screen_live.py`, its test
module, this note): the cohort budget now accounts terminal output
conservatively — the verified terminal usage when the envelope's usage
block verifies, else the route's declared per-call `max_output_tokens`
for that completed row, so absent or unverifiable usage can only shrink
future headroom, never bypass the ceiling — and the adapter refuses the
next row before anything exists for it: no handshake, no countTokens
send and no generateContent send happens once the accounted output plus
the route's maximum possible terminal output would exceed the ceiling.
Every post-limit external call is prevented, not detected after another
generation. Input, cost, external-request, retry, archive, receipt and
manifest semantics are byte-unchanged, and no schema moved.

## ADR-110 — The screen prompt names its own closed vocabulary

**Status.** Accepted. Fixture-first: no model call, no `data/runs` write, no
retry of the failed canary. The first governed canary run remains immutable,
non-authoritative evidence and is neither deleted nor reused.

**Measured cause.** The first live Vertex/Gemini canary
(`universe-high-recall-canary-v1-20260820`) stopped fail-closed at row 1 with
`adapter_rejection`. The provider call itself was healthy — `countTokens`
returned 5,478 tokens, `generateContent` returned `finishReason: STOP` with
778 output tokens, well-formed JSON, a valid `screen_status`, and two quotes
that resolved verbatim into the packet. Exactly one field failed:
`candidate_customer_value_archetypes: ["Productivity/Efficiency"]`, which is
not a member of the closed thirteen-value `Archetype` vocabulary. Grepped
against the v1 template, "archetype" appears exactly once — as the empty
array `"candidate_customer_value_archetypes": []` in the output block. The
model was asked for a value from a vocabulary it was never shown, and
supplied a plausible prose label. Total cost of the discovery: two external
requests on one row.

**Decision: fix the prompt, never the validator.** Relaxing the pydantic
literal or widening the taxonomy would let unbounded free text into a field
three later stages consume, and would silently convert a measurement error
into permanent data. `prompts/discovery/universe_high_recall_screen.v2.md`
is a successor that keeps v1's high-recall standard, temporal rule,
evidence-minimal input contract, quote requirement and output field set
verbatim, and adds the closed list of thirteen values with three explicit
rules: copy values exactly, never invent synonyms or prose labels, and
return `[]` when no listed archetype is directly supported (with `OTHER`
reserved for a real but unnamed archetype, never as a substitute for `[]`).
`Productivity/Efficiency` is named in the prompt as invalid and stays
invalid in the validator; a regression test asserts the exact measured
payload is still refused.

**Successor-only evolution, on both axes.** The v1 template stays
byte-identical and remains the mock route's only template, so the ADR-108
path — module, schemas, tests and rendered bytes — does not move at all. The
live route defines its own `LIVE_PROMPT_TEMPLATE_RELATIVE_PATH` rather than
importing the predecessor's constant, and continues to reuse the predecessor
renderer and row validator unchanged. Because `universe_screen_manifest@0.2.0`
pins `prompt_template_path` as a const, a live manifest naming the v2 prompt
cannot validate under it; rather than widen a released schema,
`universe_screen_manifest.v3.schema.json` is added as a strict successor.
The v0.2 and v0.3 schemas differ in exactly seven structural points — `$id`,
`title`, `description`, the `prompt_template_path` const, and the
`schema_versions` key rename — and mutually reject, proven by test. Registry
0.47.0 → 0.48.0, 103 → 104 entries.

**Consequence for governance.** Every previously minted live authorization
binds the v1 prompt hash and is therefore stale under this ADR: preflight
refuses it before any output directory, SDK import, credential resolution or
network send, which a test pins directly. A future canary needs a fresh
governance materialization carrying
`prompt_template_sha256 = 8bf0e3010241efe9aafd7d41af2857764c48ce218a7aa0f009086ec69a5d6694`
(the v2 template's bytes) and a fresh run id. The v1 governance artifacts
and the canary selection are untouched and stay usable only as history.

**Scope.** Seven paths: the v2 prompt, the v0.3 manifest schema,
`lineage_screen_live.py`, its test module, the registry, this log, and
`REPO_MANIFEST.md` (814 → 816), plus the mechanically required guard
rebaselines. No provider, extraction, v0.1/v0.2 schema, v1 prompt, mock
runner, selection or `data/runs` change.

## ADR-111 — The screen prompt states how evidence is identified and quoted

**Status.** Accepted. Fixture-first: no model call, no `data/runs` write, no
retry of either failed canary. Both canary directories remain immutable,
non-authoritative evidence.

**Measured cause.** The second governed canary
(`universe-high-recall-canary-v2-20260820`) ran under the ADR-110 v2 prompt
and **passed rows 1-3** — the archetype defect that stopped the first canary
did not recur, and the three completed rows returned exact closed-vocabulary
values (`[]`, and two four-element lists). It stopped fail-closed at row 4
(CIK 0000811156) with `quote_resolution_failure`. The response was otherwise
sound: a valid `screen_status`, a correct empty archetype array. The evidence
object was not. The rendered passage header is one line —
`[source_id=<S> passage_id=<P> section=<SEC>]` — and the model returned
`source_id` = `"<S> passage_id=<P>"`, both header fields concatenated into
one; it then cited a `passage_id` belonging to a different passage, and its
quote did not occur in the passage it cited. Cost of the discovery: four
rows, 55,855 input and 9,071 output tokens, 39,435 microdollars.

**Decision: instruct, never relax.** The validator behaved correctly — a
citation whose quote does not exist in the cited passage must be refused,
and `_validate_row_output` is reused byte-unchanged. What was missing is
instruction: v2 displayed the header format but never said that `source_id`
and `passage_id` are two separate values, each copied from its own token of
one same header, nor that the quote must come from that passage's body.
`prompts/discovery/universe_high_recall_screen.v3.md` adds an "Evidence
identity and quote binding" section stating exactly that: two distinct
fields; each copied only from the text following its own `=`; never
concatenated; never drawn from different headers; brackets, field names and
`section` never copied in; the quote a contiguous verbatim substring of that
passage's body, never the header and never another passage; the
`(source_id, passage_id, quote)` triple verified independently before
output; and, when nothing resolves, an empty evidence array with
`missing_evidence` rather than an invented identifier or reconstructed
quote. Every other v2 section — governing spec, role, temporal rule,
screening question, non-inference list, the closed archetype vocabulary, the
input template and the required output — is carried over **byte-identical**,
proven section by section in test.

**Successor-only on both axes, again.** v1 and v2 templates and the v0.2 and
v0.3 manifest schemas are retained byte-identical and stay pinned by SHA;
v1 remains the mock route's only template. Because `universe_screen_manifest@0.3.0`
pins `prompt_template_path` as a const, `universe_screen_manifest.v4.schema.json`
is added as a strict successor whose only structural differences from v0.3
are `$id`, `title`, `description`, that const, and the `schema_versions` key
rename — seven points, verified by a structural diff, with all four
generations mutually rejecting. Registry 0.48.0 -> 0.49.0, 104 -> 105.

**Consequence for governance.** The v3 governance pair minted for the second
canary binds the v2 prompt hash and is now stale: preflight refuses it
before any output directory, SDK import, credential resolution or network
send, pinned by a parametrized test over both superseded templates. A third
canary needs a fresh governance materialization carrying
`prompt_template_sha256 = 1d371255d9b650bd5ff6ffd1d58d6a42b649436cfbcaf905bf3e53c5a7a58c78`
and a fresh run id; the v5 cohort and the 100-row selection artifact remain
valid and unchanged.

**A question this does not settle.** Two canaries have now halted on one bad
row out of the first four, which is the fail-closed contract working as
designed but is not a measurement strategy: a 100-row canary will keep
stopping at whichever row first violates a contract. Whether per-row
evidence failures should become a recorded row outcome instead of a
run-stopping error is a substantive change to ADR-108's fail-closed
semantics, is not made here, and is recorded in the open decisions.

**Scope.** Thirteen paths: the v3 prompt, the v0.4 manifest schema,
`lineage_screen_live.py`, its test module, the registry, this log,
`REPO_MANIFEST.md` (816 -> 818), the five evaluation guards, and the
recurring two-literal registry rebaseline in the ADR-108 test module. No
validator, passage-generation, provider, extraction, governance-logic,
predecessor-prompt, predecessor-schema or `data/runs` change.

## ADR-112 — A diagnostic canary measures the distribution, not the first defect

**Status.** Accepted. Fixture-first: no model call, no `data/runs` write, no
retry of any prior canary. All three failed canary directories remain
immutable and non-authoritative.

**Measured cause.** Three governed canaries stopped at rows 1, 4 and 28.
Each stop was correct and each fix was a prompt successor, never a relaxed
validator: ADR-110 closed an out-of-vocabulary archetype, ADR-111 closed
malformed evidence identity. Canary v3 then ran 27 rows fully clean, with
105 of 105 citations resolving verbatim, before row 28 produced fabricated
long quotes in a multi-subsidiary filing. The pattern is now clear and is
not a defect in the fail-closed contract: an all-or-nothing 100-row run
measures *the next remaining defect*, one per run, at four rows per
discovery. It cannot report how often each failure mode occurs, in which
filings, or at what cost.

**Decision: a separate diagnostic successor, never a permissive variant.**
`lineage_screen_diagnostic.py` screens one canary_100 selection and applies
the **identical** strict row validator, imported unchanged from the live
module — it is not more permissive per row, only more informative per
cohort. What differs is the policy on a failed row: the authoritative runner
aborts, the diagnostic runner records a `rejected_output` row and continues.
`run_lineage_screen_live` and every artifact contract it consumes or emits
are byte-unchanged, and the live module is SHA-pinned by the diagnostic test
suite.

**The continuation set is definitional.** A row is recorded and the run
continues for exactly the reason codes the shared validator can raise —
`invalid_model_json`, `adapter_rejection`, `quote_resolution_failure`,
`temporal_violation` — and nothing else, because every other failure reaches
the runner as a different exception type. Governance, binding and hash
failures; provider terminal failures and retry exhaustion; envelope-level
failures (blocked, empty, multi-candidate, part-less, malformed), which are
transport-contract failures rather than model-output content; capture
persistence and integrity failures; cap, budget and wall-clock breaches; and
any write-once or reconciliation invariant all hard-stop the run with a
governed receipt and no manifest, exactly as on the authoritative path. The
two vocabularies are disjoint and a test proves it.

**A rejected row carries no result.** `screen_output` is null and the record
contract has no screen-status field at all, so nothing invalid can be read
as an outcome. The detail is bounded to 600 characters and sanitized to name
where validation failed; the full invalid payload is retained **only** in
the hash-bound raw-response archive, which every row — rejected included —
binds by id and SHA-256. Raw-before-parse is unchanged. Per-row attempts,
measured input tokens, reported output tokens, usage verification and
settled cost are recorded for both kinds, so the price of failure is
measured alongside its frequency.

**A circuit breaker, because a measurement is not a licence to spend.**
`max_rejected_rows` is required in the authorization and is 25 for the
100-row canary. Exceeding it hard-stops the run with the distribution
measured so far retained as raw evidence. A breaker larger than the cohort
is refused: one that can never trip is not a breaker.

**Receipt counter semantics, stated exactly.** For every hard stop that
fires *before* a row record exists — provider, envelope, capture, cap,
budget — `stopping_row_index` is the row being attempted and
`records_completed_before_failure` is the count of rows that finished
before it, both derived as `len(records) + 1` and `len(records)`. The
circuit breaker is the one case where that derivation is wrong: it fires
only after its triggering row has been validated, archived and counted, so
that row is already in `records`. It therefore passes both counters
explicitly — `stopping_row_index` is the triggering row's own ordinal and
`records_completed_before_failure` is one less. The triggering row remains
counted in `rejected_rows` and present in the raw archive, because it was
genuinely measured; what the failed run does not write is the records
JSONL, the capture ledger and the manifest.

**A separate authorization contract, decided honestly.** The live
authorization is closed and carries no run-kind discriminator, so extending
it was impossible and reusing it would have let an authorization minted for
authoritative screening silently authorize diagnostic collection.
`universe_screen_diagnostic_authorization@0.1.0` therefore stands beside it,
carrying every binding the live contract carries — proven by a subset test
over its property and required sets — plus `run_kind`, `diagnostic_only`,
`promotable`, `output_contract` and `max_rejected_rows`. Neither runner can
consume the other's authorization. The adapter enablement is reused
unchanged: it governs which endpoints may exist at all, which is
run-kind-agnostic, and it authorizes no run by itself.

**Non-promotability is structural, not declarative.** Four independent
mechanisms, any one sufficient: the outputs carry diagnostic filenames, so
`require_authoritative_screen_run` and `require_promotable_screen_run`
refuse the directory for having no `universe_screen_manifest.json` **with no
code change**; the record and manifest contracts share no `$id` or field set
with the authoritative ones and every schema is closed, so they mutually
reject; the manifest pins `diagnostic_only`, `promotable`, `run_kind` and
`selection_kind` as consts; and the authorization contract differs. A new
`require_diagnostic_run` is the only loader that admits these directories,
and it refuses receipt-bearing, manifest-less, authoritative and
hash-mismatched runs alike.

**The v3 prompt is deliberately unchanged.** The first diagnostic canary
exists to measure the true remaining error distribution of the prompt that
is committed today, not to hide it behind another successor.

**A recurring coupling, resolved.** For four consecutive increments the
ADR-108 test module has needed a two-literal registry rebaseline. Under
explicit authorization its two absolute registry version and count
assertions are now **removed permanently**; its schema-key assertions
remain, and ownership of registry version and count moves to the five
evaluation guard modules, which already carry the pinned manifest hash and
the rebaseline history. Nothing else in that module changed.

**Scope.** Fifteen paths: the diagnostic module, its three contracts, its
test module, the pipeline entrypoint (mode count 22 to 23), the registry
(0.49.0 to 0.50.0, 105 to 108), this log, `REPO_MANIFEST.md` (818 to 823),
the five evaluation guards, and the ADR-108 literal removal. No provider,
extraction, packet, passage, validator, live-runner, prompt, predecessor
schema or `data/runs` change.

## ADR-113 — Short deterministic passage references preserve strict evidence

**Status.** Accepted from the completed ADR-112 diagnostic canary. The canary
validated 90 of 100 rows and rejected 10. Of 14 defective evidence objects,
10 contained a quote that resolved exactly somewhere in the same Item 1 packet
but carried either a corrupted opaque passage hash or a hash for another
passage. Four quotes were non-verbatim and one output omitted a required
claim field. The evidence validator correctly refused every one; it is not
weakened.

**Decision.** The v4 prompt presents ordered packet passages with short
deterministic `P001`-style references in the model-facing `passage_id` slot.
The live and diagnostic runners derive a one-to-one reference-to-immutable
hash map from the packet's ordered passages, archive the model response before
any transformation, then resolve a known short reference to the original hash
before calling the unchanged `_validate_row_output`. An unknown reference,
malformed response, non-verbatim quote, or wrong source remains a strict
rejection. Accepted records therefore preserve real immutable passage hashes,
while the raw archive preserves exactly what the model returned.

**Why not one whole Item 1 passage.** A single huge passage would remove an
addressing problem by discarding the evidence granularity needed for audit and
would not fix non-verbatim constructed quotes. The diagnostic evidence instead
supports simplifying the model-facing address, not removing passage-level
provenance.

**Succession.** `universe_high_recall_screen.v4.md` and
`universe_screen_manifest.v5.schema.json` are successors. v0.5 pins the v4
prompt path; v0.1–v0.4 schemas and prompts remain byte-identical and mutually
reject. A new fixture-only validation run is required before any new model
canary authorization.

## ADR-114 — Diagnostic prompt removes a redundant source-copy task

**Status.** Accepted, fixture-first. This is a diagnostic-only prompt
successor; it makes no live model call, changes no authoritative runner or
manifest, and does not promote any diagnostic result to SCREEN_v1.

**Measured input.** The completed v4 diagnostic canary validated 93 of 100
rows and recorded seven `quote_resolution_failure` rows. Offline inspection
of the hash-bound raw archive and the v5 packets found one pure source-copy
error, one quote paired with the wrong passage, and five non-verbatim model
edits (re-capitalisation, abbreviation, dropped scope, stitching, or added
context). The wrong passage was P009 while the exact quote was in P037; it is
not adjacent-reference confusion. Rejected rows averaged 4.57 evidence items
versus 3.95 for validated rows, an insufficient seven-row signal to impose an
evidence-item cap. No maximum quote length is introduced: valid citations can
be longer than a generic threshold.

**Decision.** The diagnostic v5 prompt no longer displays or asks the model
to emit `source_id`. Each row is one immutable filing, so source identity has
one permitted value and no screening information. The diagnostic renderer
instead exposes only an ordered `passage_ref` (`P001`, `P002`, ...) and the
passage body. Before the existing strict validator runs, the diagnostic
resolver maps an exact known reference to the packet's immutable passage ID
and injects the packet-owned source ID. The raw archive remains the
unmodified model response. Unknown references are never repaired and
non-verbatim quotes remain strict rejections.

**Prompt discipline.** Quote is explicitly a copy operation, not writing.
The prompt makes the exact-substring acceptance test visible and forbids the
five observed editing behaviours. It asks for the shortest directly
supporting span as a preference only, never a length cap. A model output uses
`passage_ref`, `quote`, and `supported_claim`; it does not carry a source
identifier.

**Scope.** Eight paths: the v5 diagnostic prompt, diagnostic runner, its
fixture tests, this decision log, `REPO_MANIFEST.md` (832 to 833), and the
three mechanically necessary manifest-count guards. No registry or schema
contract changes occur.
`lineage_screen_live.py`, all authoritative contracts, the shared validator,
all predecessor prompts and every `data/runs` artifact remain byte-identical.
A governed seven-row live repair measurement requires a separate selection
and authorization successor: the current diagnostic contract intentionally
pins a 100-row canary and is not bypassed here.

## ADR-115 — Governed seven-row diagnostic repair measurement

**Status.** Accepted, fixture-first. No live model call, no `data/runs`
write, no change to any authoritative contract, and no promotion path: a
repair run is a diagnostic measurement forever.

**Question.** ADR-114's closing note left one gap open: the completed v2
diagnostic canary (93 validated, 7 `quote_resolution_failure` rejections)
measured the v4 prompt, while the committed v5 prompt that responds to those
seven failures has never been exercised against the rows that motivated it.
The existing diagnostic contract intentionally pins a 100-row canary
selection and cannot re-screen seven rows without being loosened — which is
exactly what must not happen.

**Decision.** A third, structurally isolated run kind: `diagnostic_repair_7`.
Its row authority is a new hash-bound artifact,
`universe_screen_diagnostic_repair_selection@0.1.0`, whose seven rows are
never authored but derived relationally from one completed source diagnostic
run under the closed rule
`rejected_quote_resolution_rows_ascending_ordinal@1`: exactly the rows whose
`record_kind` was `rejected_output` with reason `quote_resolution_failure`,
ascending by source row ordinal. The artifact binds the source run three
ways (manifest path, manifest bytes SHA, records JSONL SHA) and the v0.5
packet cohort two ways, and each row carries the packet SHA and a per-row
eligibility proof (source ordinal, record kind const, reason const). The
builder refuses a source run holding a failure receipt, any output-hash
mismatch, a foreign contract, an incomplete or duplicated partition, a
missing or drifted packet, and any eligible count other than exactly seven —
another count is a different population needing its own contract.

**Authorization.** A separate
`universe_screen_diagnostic_repair_authorization@0.1.0` contract with
run_kind const `diagnostic_repair_7`, `diagnostic_only` true and
`promotable` false as consts, the V5 prompt hash binding, the repair
selection SHA, provider/enablement/endpoint bindings, caps pinned by schema
const to exactly 7 logical requests, 21 provider attempts and 28 external
requests, and a rejected-row breaker bounded to [1, 7]. Neither the
authoritative runner nor the 100-row diagnostic runner can consume this
grant, and the repair runner refuses both of theirs.

**Runner.** A separate module,
`src/dynamic_ai_products/lineage_screen_diagnostic_repair.py`, with two CLI
modes (`select-screen-repair-rows`, `screen-universe-lineage-diagnostic-repair`).
It reuses the adapter, the unchanged strict validator, the v5
renderer/resolver and the capture logic by import, and re-derives the seven
rows from the bound source bytes at preflight, refusing a selection that no
longer reproduces — a doctored selection fails even with a matching digest
chain. Outputs are repair-named
(`universe_screen_diagnostic_repair_records.jsonl`,
`universe_screen_diagnostic_repair_manifest.json` under
`universe_screen_diagnostic_repair_manifest@0.1.0`), so every other loader
refuses a repair run structurally, and `require_diagnostic_repair_run`
refuses receipts, authoritative and diagnostic directories, foreign
contracts and output-hash drift.

**Scope.** Sixteen paths: three repair schemas, the repair module, its
fixture-only test module (fake client factory, no network), the CLI,
`schemas/schema_version_manifest.json` (0.51.0 to 0.52.0, 109 to 112
entries), this decision log, `REPO_MANIFEST.md` (833 to 838), the five
manifest/registry guards, and the two-literal absolute registry assertions
in the live and diagnostic screen test modules. `lineage_screen_live.py`,
`lineage_screen_diagnostic.py`, the shared validator, every prompt, every
authoritative and diagnostic contract, and every `data/runs` artifact remain
byte-identical.

## ADR-116 — Authoritative V5 screen preserves model-evidence uncertainty

**Status.** Accepted, fixture-first successor. This decision does not alter
the all-or-nothing ADR-109 live route, its v0.1 record contract, or any
completed diagnostic artifact.

**Measured basis.** The V5 governed diagnostic canary completed all 100
selected packet rows: 97 validated and 3 rejected for
`quote_resolution_failure`. The three rejected outputs contained model text
that could not be verified as a contiguous quote in the packet passage. The
strict validator correctly rejected them; accepting them as a negative screen
result would be unsafe. Conversely, stopping an entire 7,042-packet screen at
the first such model-output defect would make the already measured error
surface invisible and prevent an auditable full cohort result.

**Decision.** `lineage_screen_live_v2.py` is an authoritative successor,
bound to the V5 source-minimal passage-reference prompt. It applies the
unchanged strict validator after deterministic `passage_ref` resolution and
packet-owned source injection. A model-output validation failure in the
closed vocabulary `invalid_model_json`, `adapter_rejection`,
`quote_resolution_failure`, or `temporal_violation` produces one
`universe_screen_record@0.2.0` row of kind
`model_evidence_unverified`. The row binds its packet, rendered prompt,
model route and pre-parse raw response, but has null `screen_status` and null
`screen_output`; it is not a fourth model status and cannot be interpreted as
`LIKELY_INELIGIBLE` or a sample exclusion. Its bounded reason/detail support
a review queue; the full raw payload remains only in the hash-bound archive.

**Existing missing-packet state remains distinct.** The 530 retained rows
whose Item 1 packet could not be constructed remain
`insufficient_evidence`: no model call, no prompt/raw binding, null filing
date as imposed by the failure-row authority. The two states answer different
questions and must never be merged.

**Fail-safe firm roll-up.** The successor's raw-CIK order is
`LIKELY_ELIGIBLE > BOUNDARY_OR_UNCERTAIN > MODEL_EVIDENCE_UNVERIFIED >
LIKELY_INELIGIBLE > INSUFFICIENT_EVIDENCE`. Hence any valid packet whose
model evidence is unverified blocks firm-negative treatment. The current
cohort has one packet or failure per CIK, but this rule is explicit for later
multi-observation cohorts.

**No permissive transport change.** Governance, input binding, client
contract/endpoint equality, provider and envelope failures, capture
persistence/integrity, request caps, token/cost/wall-clock budgets, write-once
failure and every reconciliation failure remain run-fatal and receipt-bearing.
Only model-content failures that the existing strict validator can name are
recorded. A per-run, authorization-bound `max_model_evidence_unverified`
circuit breaker limits their number; the full-run numeric limit is a separate
live authorization decision, not a source literal.

**Contracts.** The successor adds v0.2 record and authorization contracts and
a v0.6 manifest. Their closed names and schema versions prevent old loaders
and authorizations from silently consuming this generation. V0.6 pins the V5
prompt path and records the five-way row accounting, raw archive and capture
ledger hashes.

## ADR-117 — The screen waits out a 429 instead of spending its packets

**Status.** Accepted, fixture-first successor. No live model call, no
`data/runs` write, and no change to the ADR-116 route, the committed
extraction retry policy, either shared Vertex connector, the V2 screen
contracts or the V5 prompt — all of them are pinned byte-identical by test.

**Problem.** A 429 is the provider declaring a quota or a rate limit, not a
transport hiccup. The committed policy
(`extraction_provider_retry_policy_v1`) answers it with three attempts at 1s
then 2s, which re-sends twice inside the same rate-limit window and then
gives up. On the authoritative route a give-up is run-fatal, so a
rate-limited cohort does not lose one packet, it loses the run — and the
7,042-packet full cohort is exactly the shape where sustained rate limiting
is expected rather than exceptional. Widening the generic policy is not
available: it governs every extraction caller, and its three-attempt
ceiling is a committed E-P contract.

**Decision.** A second, screen-only policy and a screen-only connector,
beside the generic ones rather than instead of them.
`providers/screen_retry_policy.py` declares
`universe_screen_generate_retry_policy_v1`: five total `generateContent`
attempts per logical packet — the original send plus four retries — with
fixed waits of 15s, 30s, 60s and 120s, no jitter, and `countTokens` pinned
to exactly one un-retried send. `providers/vertex_gemini_screen_v3.py`
subclasses the V2 connector and overrides exactly two methods: the handshake,
so that a five-attempt cap is admissible, and the generate call, so that the
screen's wait chain drives it. Everything else is inherited, including
`count_tokens` — which has no loop at all — and `_attempt`, which is what
keeps the per-attempt rule true: each attempt's body reaches the runner's
sink before the wrapper may wait or re-send, so a persistence failure still
stops the loop while there is a loop to stop.

**What is not retried.** The trigger set is not restated here. The screen
policy re-exports the committed `should_retry` object itself, so the
retryable conditions remain 408, 429, 500, 502, 503, 504 and a transport
timeout, and a validation, capture, governance, budget or evidence failure is
outside the predicate by construction rather than by convention. A
capture-sink failure is proven non-retryable; an undeclared exception is
terminal on its first attempt.

**Arithmetic.** One logical packet may now spend five generate attempts and
one count send, so a run of `n` selected packets authorizes `n × 5` provider
attempts and `n × 6` external requests. For the full cohort: 7,042 logical
requests, 35,210 generate attempts, 42,252 external requests. The ceilings
are re-derived from the selection at preflight and checked against the grant;
no cohort size is pinned in code or schema, and a test asserts that those
three numbers appear in neither.

**Contracts.** `universe_screen_live_authorization@0.3.0` and
`universe_screen_manifest@0.7.0`. The grant carries the policy version and
the per-row arithmetic as consts, so a three-attempt grant cannot execute
here and this grant cannot execute on the v0.1 or v0.2 routes; the manifest
records the wait chain it actually ran under, and its contract const makes
the v0.5, v0.6 and v0.7 generations mutually exclusive even though all three
write the same authoritative filename. The record contract is unchanged:
this is a transport decision, and `universe_screen_record@0.2.0` still
describes the rows. The ADR-116 evidence semantics — `model_evidence_unverified`
rows, the fail-safe roll-up, the model-evidence breaker — are inherited by
import, not restated.

**Cost of the change, stated.** A single rate-limited packet can now occupy
225 seconds of wall clock before failing, and the cohort cost reserve must
pay for five attempts per row rather than three. Both are bounded and both
are authorized up front: the budget wrapper prices the five-attempt reserve
before the row's first send, and the wall-clock budget remains a hard stop.

**Scope.** Eighteen paths: the screen policy, the screen connector, the v3
runner, its two contracts, its fixture-only test module, the CLI mode, the
registry (0.55.0 to 0.56.0, 115 to 117), this decision log, `REPO_MANIFEST.md`
(843 to 849), the five manifest/registry guards, and the two-literal absolute
registry assertions in the three sibling screen suites. The CLI docstring's
mode count is corrected from twenty-five to twenty-seven; it had gone stale
when the v2 route landed without updating it.

## ADR-118 — A failed run's completed prefix is evidence, not waste

**Status.** Accepted, fixture-first. No live model call, no `data/runs` write,
and no change to the V3 route, its generate policy, its connector, any earlier
contract, any prompt, or the failed run this successor is designed to continue.

**Measured input.** The V3 full-cohort run completed 3,939 of 7,042 rows and
stopped because one `countTokens` call timed out after 300 seconds. Under
ADR-117 that call is a single un-retried send, so the run did exactly what it
was told; the cost was 3,939 rows of finished work with no way to keep them,
because the governance model has no artifact between "failure receipt" and
"complete authoritative manifest". Offline revalidation of the archive shows
the work is intact: all 3,939 responses re-hash, the archive is a contiguous
prefix of the selection in order, and re-rendering each packet reproduces every
row's outcome — 3,644 `screened_packet` and 295 `model_evidence_unverified`.

**Decision, part one: reuse is earned.** A continuation route revalidates the
prefix of one **explicitly named** failed run and model-calls only the suffix.
There is no discovery: the source directory and its receipt digest are stated
on the command line and pinned in the grant. Nothing about the parent is
trusted. Every reused response is re-parsed, re-reference-resolved against a
freshly derived `P001` map and re-validated by the unchanged strict validator,
so a reused row is held to the identical standard as a fresh one and its
outcome is recomputed rather than copied. Reuse is admitted only for the one
enumerated failure shape — a provider timeout with a contiguous completed
prefix and no archived response for the stopping row — and every other shape,
including an exhausted model-evidence breaker, is refused rather than assumed
safe.

**What is proven before a run directory, an SDK import or a send exists:** the
receipt matches its pin and its enumerated shape; the archive matches its pin
line for line and hash for hash; the archive maps in selection order onto a
contiguous prefix with nothing skipped, reordered, duplicated, foreign or
drawn from the suffix; the parent ran under a grant whose packet, selection,
prompt, route, contract and endpoint bindings are identical to this run's; and
every reused response still validates.

**Decision, part two: countTokens gets a bounded retry.**
`universe_screen_count_retry_policy_v1` — three total attempts at 15s and 30s,
screen-only, on the same declared transient class the generate policy uses,
reached through the committed `should_retry` object rather than a restatement.
The measurement call is idempotent, so retrying it invents no evidence and
changes no model output; it remains a precondition, and generation still does
not begin until a count has succeeded. The V3 connector keeps sending it
exactly once, and the V4 connector inherits `complete_v8` unchanged, so the
five-attempt 15/30/60/120 generate chain is the same code.

**Honest telemetry.** A failed run leaves no capture ledger, so no per-attempt
token, cost or wire accounting exists for the prefix. The manifest records the
parent receipt's aggregates and pins `per_attempt_telemetry_available` false
rather than inventing them; `request_accounting` describes this run's own sends
only; and the capture ledger beside the manifest covers model-called rows only,
with cohort-numbered ordinals. The new archive opens with the parent's bytes
verbatim — each reused line keeps the id it was written under, so its
provenance is readable rather than asserted — and a reconciliation identity
proves the byte-identical prefix.

**"All quotes resolve", stated exactly.** Every `screened_packet` record's
quotes resolve verbatim; every quote, adapter or JSON failure is persisted as
an explicit `model_evidence_unverified` record naming its closed reason; no
unverified row may be represented as screened or silently omitted. A reused row
that no longer validates therefore becomes an unverified record, not a
refusal — the one exception being that a prefix whose unverified rows already
exceed the authorized breaker refuses before any network, because such a
continuation cannot complete and should not spend.

**The breaker is a governance number.** The prefix alone carries 295 unverified
rows, and the parent's grant allowed 300, so continuing under it would trip
after roughly 67 of the 3,103 remaining rows. The parent was five rows from
dying on its own breaker when the timeout arrived; "retry and it will finish"
was never true. The continuation contract therefore carries its own
whole-cohort breaker, counting reused rows, set for the live case at 700
against a projected ~527 — measured headroom, not a quality target, and still
stopping a materially worse regime near 10% of the cohort.

**Contracts.** `universe_screen_record@0.3.0` adds `row_provenance` and changes
nothing else; `universe_screen_continuation_authorization@0.1.0` binds the
source four ways and splits the accounting into cohort rows, reused rows,
model-called rows and the three send ceilings derived from the called rows
alone; `universe_screen_manifest@0.8.0` separates the two populations and the
two telemetries. Per-row multipliers are schema consts; row counts never are,
and no live cohort size appears in any source file or schema.

**The parent stays what it is.** Receipt-bearing, immutable, and permanently
non-authoritative. Only the continuation's own manifest may be consumed, and a
continuation that itself fails is equally non-authoritative even though its
directory holds the reused prefix bytes.

**Scope.** Twenty-one paths: two provider modules, the continuation runner,
three schemas, its fixture-only test module, the CLI mode, the registry
(0.56.0 to 0.57.0, 117 to 120), this decision log, `REPO_MANIFEST.md` (849 to
856), the five registry/manifest guards, the provider boundary count, and the
absolute registry literals in the four screen suites.

## ADR-119 — An empty successful response is an absence, not an answer

**Status.** Accepted, fixture-first. No live model call, no `data/runs` write,
and no change to the V3 or V4 routes, either screen retry policy, any prompt,
any earlier contract, or either immutable failed run.

**Measured input.** The ADR-118 continuation reused 3,939 rows, added 358 more,
and stopped at cohort row 4,298 when `generateContent` **returned** with an
empty entity body. The evidence is unambiguous: the stopping row holds a
157-byte `countTokens` capture and no generate body at all, and the receipt's
360 generate attempts exceed its 358 completed rows by exactly two — one 429
that recovered on its first 15-second wait, and the stopping row's single call.
Neither retry policy was at fault and neither could have helped. ADR-117
answers a raised transient failure; ADR-118 answers a measurement timeout; an
HTTP-successful empty response raises nothing, so it reached the terminal check
directly. Three consecutive full-cohort attempts have now died three different
ways, which is itself the finding: each stop was a real defect, and each was
outside what the previous decision had made survivable.

**Decision, part one: the anomaly is retryable, and only it.** A screen-only
connector successor detects an empty generate body **before** any persistence
or parse is attempted, classifies it `empty_generate_body`, and retries it
through the **unchanged** ADR-117 schedule — five total attempts at 15s, 30s,
60s and 120s. No new schedule and no second budget are introduced. Everything
else keeps its meaning: a malformed, blocked, truncated, part-less, non-text or
invalid-JSON response is still terminal on its first occurrence, because those
are answers rather than the absence of one, and a capture, validation, quote,
evidence, governance, cap or budget failure remains outside the predicate by
construction. `countTokens` is inherited unchanged, so an empty body never
re-measures the input.

**Nothing empty is ever hashed.** An empty body is never written and never
digested — that was already true, and it is why the run stopped rather than
publishing a valid-looking digest for content that never existed. What this
decision adds is that the attempt stays auditable: each empty attempt writes a
ledger event with a null raw reference, a null hash, and the explicit
`empty_generate_body` reason, so an attempted external call is visible without
inventing evidence for it.

**Why the provider error enum is not widened.** `ProviderError` carries a
closed `reason_code` pinned to the released `extraction_provider_error_record`
enum. Adding a term would change a released contract, so exhaustion is reported
as `provider_response_unusable` — literally "the provider outcome could not be
used" — while the distinct classification lives where this successor owns the
contract: the ledger event and a terminal receipt reason of
`empty_generate_body_exhausted`.

**Decision, part two: the stop is reusable, narrowly.** A successor loader
admits an empty-body-stopped continuation as a source, and the admission is not
"any `provider_response_unusable`". Seven independent proofs must hold, and the
two decisive ones are read from the source's own captures rather than from its
reason string: the stopping row must carry a real, non-empty `countTokens`
capture, and it must carry no persisted generate body at all. A source that
stopped for another reason, that persisted a body it could not use, whose
archive is not a contiguous unique prefix in selection order, whose responses
no longer re-hash, or whose counters do not close, is refused before a run
directory or any SDK or network access exists.

**Contracts and structural isolation.** `universe_screen_continuation_authorization@0.2.0`
adds a `source_kind` const naming the one newly admitted state and pins the
empty-body ceiling to the existing five-attempt schedule; the v0.9 manifest
adds `empty_generate_body_telemetry` — attempts, rows affected, rows recovered
— and is written under its own filename, so the v0.5 through v0.8 loaders
refuse the directory outright. Promoting an ADR-119 run to a SCREEN release is
therefore a deliberate loader decision with its own tests, not something
inherited by filename. The v0.3 record contract is reused unchanged: reuse
provenance already carries the source run, archive digest and receipt digest,
and a reused row keeps the `raw_response_id` it was first written under, which
may name a run earlier than its immediate source.

**What this does not settle.** The empty-body rate is unknown — one occurrence
in 359 model-called rows is a sample of one — and a fourth distinct failure
mode remains possible. Nothing here promises the next full-cohort attempt
completes; it removes one specific way of losing finished work.

**Scope.** Nineteen paths: the connector, the continuation successor, two
schemas, its fixture-only test module, the CLI mode, the registry (0.57.0 to
0.58.0, 120 to 122), this decision log, `REPO_MANIFEST.md` (856 to 861), the
five registry/manifest guards, the provider boundary count, and the absolute
registry literals in five screen suites.

## ADR-120 — The same absence, on the other operation

**Status.** Accepted, fixture-first. No live model call, no `data/runs` write,
and no change to any earlier connector, runner, prompt, schema or failed run.

**Measured input.** ADR-119's continuation reused 4,297 rows and added 524 more
before `countTokens` returned once with no usable body. The receipt arithmetic
names the operation exactly: one count attempt for the stopping row, zero
generate attempts, and no capture directory at all. The bounded count retry
never engaged, because a call that returns raises nothing — the identical
structural gap ADR-119 closed for the generation, on the operation it
deliberately left out of scope. **The ADR-119 fix was correct and incomplete,
and the next run found the half left open.**

**Decision, part one: the counterpart anomaly is retryable, and only it.** A
connector successor detects an empty count body before any persistence or
parse, classifies it `empty_count_body`, and retries it through the
**unchanged** ADR-118 count schedule — three attempts at 15s and 30s. ADR-119's
generate behaviour is preserved by inheritance rather than restatement. An
empty count never invokes the generation on that attempt: the measurement is a
precondition, so the connector raises before the adapter can proceed. Nothing
else becomes retryable, and the released `ProviderError` enum stays closed —
the operation-specific state lives in the ledger event and the receipt.

**Decision, part two: the stop is reusable, narrowly.** The successor loader
admits an empty-count-stopped continuation only on proofs read from the
source's own counters and captures: exactly one count attempt for the stopping
row, zero generate attempts for it, no stopping-row capture of any kind, and
zero empty generate bodies anywhere in the run. A generic
`provider_response_unusable`, an arbitrarily missing capture directory, or a
run that met both anomalies is refused.

**Contracts.** `universe_screen_continuation_authorization@0.3.0` and
`universe_screen_continuation_manifest@0.10.0`, under their own filenames, so
every earlier loader refuses the directory. The manifest reports the two
anomalies separately and adds `inherited_source_limitations`, naming the chain
of failed runs whose evidence a reused row rests on — that chain is now three
deep, and a reader should not have to reconstruct it.

**What this does not settle.** Four full-cohort attempts have now stopped four
ways, three of them single-row provider anomalies rather than systematic
defects. Each decision removed one way of losing finished work; none of them
makes completion likely by itself. Whether a per-row abandonment budget belongs
in the design — so that one unusable row costs one row rather than a run — is
the open question this sequence keeps raising, and it is not answered here.

**Scope.** Twenty-one paths: the connector, the continuation successor, two
schemas, its fixture-only test module, the CLI mode, the registry (0.58.0 to
0.59.0, 122 to 124), this decision log, `REPO_MANIFEST.md` (861 to 866), the
five registry/manifest guards, the provider boundary count, and the absolute
registry literals in six screen suites.

## ADR-121 — One unresolvable row must not cost a cohort

**Status.** Accepted, fixture-first. No live model call, no `data/runs` write,
and no change to any existing connector, runner, prompt, schema or failed run.

**Measured basis.** Four full-cohort attempts have stopped four ways, and three
of those stops were a single row whose provider transport failed *after* the
retries this project had already authorized were spent: quota exhaustion at
row 24 and 119, a count timeout at 3,940, an empty generate body at 4,298, an
empty count body at 4,822. ADR-117 through ADR-120 each removed one mechanism
of failure. None of them addressed the *shape* of the loss, which is that one
row the provider will not resolve discards every completed row with it.

**Decision.** A fourth row outcome, `PROVIDER_UNRESOLVED`, for one closed
class: a provider or transport condition that has already exhausted an
authorized retry path. Exhausted quota and transient retries, a governed
terminal timeout after its eligible retries, `empty_generate_body_exhausted`
and `empty_count_body_exhausted` qualify. Nothing else does — not invalid
JSON, an adapter rejection, a quote or evidence failure, a malformed or
blocked response, a capture failure, a governance or binding failure, a budget
or cap breach, nor any content ambiguity. Those remain run-fatal.

**The classification is structural, not textual.** The shared adapter re-raises
a `ProviderError` as the `__cause__` of its terminal error, so a capture-sink
failure, a count-reconciliation failure and an envelope failure each carry a
different cause or none, and are excluded by construction. On top of that, the
failing operation's attempts must actually be exhausted: the same provider
error on its first attempt is a stop, because it was never retried.

**What such a row is, and is not.** It stays in the cohort with its exact
identity, its closed provider reason and its attempt telemetry. It carries no
screen status, no evidence, no archetypes and no archived response, because
none exists. It is not negative, not an exclusion, and not
`model_evidence_unverified` — that kind means a response *arrived* and failed
validation, which is the opposite situation. It is excluded from classifier
call lists and from every valid-status count, and it is named rather than
dropped, so the gap is auditable instead of inferred from an absence.

**The tolerance is bounded and authorized.** The grant must pin
`max_provider_unresolved` at 25; the run may finish authoritatively only while
such rows number 25 or fewer; the twenty-sixth stops it fail-closed with no
manifest. A provider failing that often is a systematic condition, not a stray
row, and the run should end rather than quietly produce a cohort full of
holes. The manifest records the count, the breakdown by closed reason, and the
threshold the run finished under, and the reconciliation proves the cohort
closes over all four populations: screened, model-evidence-unverified,
insufficient-evidence and provider-unresolved.

**Honest limits.** This makes a cohort survivable, not correct. Twenty-five
unresolved rows are twenty-five rows about which nothing is known, and a
release built on such a cohort inherits that hole. The threshold is a
governance choice about what a cohort may tolerate, not a measurement, and
whether 25 is the right number for a 7,042-row frame is a question the first
completed run should be used to revisit.

**Scope.** Twenty-one paths: the continuation successor, three schemas, its
fixture-only test module, the CLI mode, the registry (0.59.0 to 0.60.0, 124 to
127), this decision log, `REPO_MANIFEST.md` (866 to 871), the five
registry/manifest guards, and the absolute registry literals in seven screen
suites. No new provider module is added: the classification is a runner
decision, so the connector line is untouched.

## ADR-122 — A row the model never finished is an outcome, not a stop

**Status.** Accepted, fixture-first. No live model call, no `data/runs` write,
no governance materialization, and no change to any existing connector,
runner, prompt, released schema or failed run.

**Measured basis.** The fifth full-cohort attempt stopped at row 4,893 of
7,042, and it was the first stop that was not a transport problem. The request
succeeded, the envelope was well-formed, and it carried exactly one candidate
with `finishReason: MAX_TOKENS` — 16,384 candidate tokens and 72,928
characters of unfinished JSON. ADR-121's tolerance correctly did not apply:
its classification is structural, and an envelope failure carries no
`ProviderError` cause. The transport worked; the model simply did not finish.

**Decision.** A fifth row outcome, `MODEL_OUTPUT_TRUNCATED`, for exactly one
condition: a generation returning a single candidate whose `finishReason` is
`MAX_TOKENS`. The row keeps its identity, the closed reason `max_tokens`, its
attempt counts, and the reference and digest of the captured envelope that
proves it. It carries no status, no output, no evidence, no archetypes and no
archived response line, because there is no finished answer to record. It is
excluded from classifier call lists and from every valid-status count.

**A truncated answer is never re-sent.** The model returned. Repeating the
identical request under the identical `max_output_tokens` invents nothing and
costs a second generation. `max_output_tokens` is unchanged and the client
contract is untouched: raising the ceiling is a separate decision with its own
cost and its own evidence, and it is not taken here.

**The stopping row is re-derived, not re-called.** The failed run's own
capture is hash-verified evidence of what the model returned, so the successor
reconstructs row 4,893 from that capture and issues live calls only for rows
4,894 through 7,042 — 2,149 rows rather than 2,150. Reusing 4,892 archived
rows and re-deriving one costs no send at all, and every reused row is still
revalidated offline through the unchanged strict validator.

**The source proof is inverted, deliberately.** Every earlier continuation
source proved itself by what its stopping row did *not* capture. This one
proves itself by what it did: a non-empty countTokens capture, a
generateContent capture whose bytes parse to exactly one `MAX_TOKENS`
candidate, a terminal detail naming that finish reason, and counters showing
exactly one count and one generate attempt for the stopping row. A malformed,
blocked, multi-candidate or normally finished envelope is not a truncation and
is refused before a run directory exists. ADR-120's "zero empty generate
bodies anywhere in the run" proof is *not* carried forward: since ADR-119 and
ADR-120 an empty body is a recovered, archived row like any other, and every
reused row is revalidated regardless, so requiring zero would refuse a sound
source for a condition its own prefix already answers.

**The tolerance is bounded and authorized.** The grant must pin
`max_model_output_truncated` at 25, alongside the unchanged
`max_provider_unresolved` of 25 and `max_model_evidence_unverified` of 900.
The twenty-sixth truncated row stops the run fail-closed with no manifest. The
manifest records the count, how many were re-derived from the source, the
threshold the run finished under, and that no truncated row was retried; the
reconciliation proves the cohort closes over all five populations: screened,
model-evidence-unverified, insufficient-evidence, provider-unresolved and
model-output-truncated.

**Honest limits.** This records the loss; it does not reduce it. A truncated
row is a row about which nothing is known, and it is a *model* condition
rather than a provider one — the same packet may truncate again on any later
run. Whether 16,384 output tokens is the right ceiling for the densest packets
in this frame is the question this stop actually raises, and it is not
answered here; the first completed run should be used to size it. Nor is the
count of one a rate: a single truncated row in 4,893 says almost nothing about
what the remaining 2,149 will do.

**Scope.** Twenty-two paths: the continuation successor, three schemas, its
fixture-only test module, the CLI mode, the registry (0.60.0 to 0.61.0, 127 to
130), this decision log, `REPO_MANIFEST.md` (871 to 876), the five
registry/manifest guards, and the absolute registry literals in eight screen
suites. No new provider module is added: the classification is a runner
decision, so the connector line is untouched.

## ADR-123 — An unverified row is re-asked, never edited

**Status.** Accepted, fixture-first. No live model call, no `data/runs` write,
no governance materialization, and no change to any existing prompt, runner,
validator, connector, retry policy or promotion loader.

**Measured basis.** The first complete full-cohort screen
(`universe-high-recall-continuation-v5b-20260822`, 6,467 screened rows) left
**574** rows `model_evidence_unverified`: 570 `quote_resolution_failure`, three
`adapter_rejection` and one `invalid_model_json`. Replaying the committed
resolver and the unchanged strict validator offline over the archived bytes
reproduces all 574 exactly, with zero rows revalidating clean, so the
population is a property of the evidence on disk rather than of the run.
Sub-classified at row level: **451** rows contain at least one quote that
appears verbatim in no passage of their packet, and **119** cite a passage that
does not contain the quote while another passage in the same packet does.

**Decision.** Every unverified row is re-asked. The 119 wrong-passage rows are
**not** repaired by re-attribution, although they could be closed with no model
call: substituting a passage manufactures an attribution no model ever made,
and repairing model output after the fact is what this project forbids. They
are recorded as measured evidence of a prompt defect and re-asked like the rest.

**The selection is derived and unfiltered.** Population: every
`model_evidence_unverified` record, ascending by source row ordinal, under
`unverified_rows_ascending_ordinal@1`. No status-based filter is applied, and
this is a substantive choice rather than a simplification: the claimed status
inside a rejected payload is an assertion that failed validation, and letting
it choose which rows get a second chance would make selection depend on the
outcome being measured. It would also bias the result — the unverified rows
claim `LIKELY_ELIGIBLE` at 54.2% against the validated cohort's 44.4%.

**A repair is a fresh observation.** The prompt receives the packet and nothing
else: no earlier status, quote, `passage_ref`, failure reason, or retry
identity. The prompt's own title was changed from a "repair" wording during
implementation for exactly this reason — the model must not learn that the row
was screened before.

**A narrow prompt successor.** `universe_high_recall_screen_repair.v1.md`
differs from the committed V5 screen prompt in exactly two places: a five-step
ordering requiring the model to find the span first and read `passage_ref` off
the body it copied from, and a sentence making omission the outcome when no
contiguous span exists. Every other section is byte-identical, asserted
section-by-section, along with the status vocabulary, the closed archetype list
in order, the JSON output block and the placeholders. The grant pins the repair
prompt's digest; the manifest records the V5 prompt's digest beside it.

**Scope stops at the measurement.** ADR-123 ends with a completed,
structurally non-promotable repair run. `promotable` is false in both grant and
manifest, the outputs carry repair-only filenames, and the authoritative,
promotion, diagnostic, diagnostic-repair and continuation-v5 loaders all refuse
the directory. Reconciliation into a SCREEN release is a separate ADR taken
after this measurement is read.

**One tolerance, and no others.** A row failing validation again stays
`model_evidence_unverified` up to the grant's `max_repair_unverified`; above it
the run stops fail-closed. Provider failures are deliberately **not** tolerated
here: ADR-121's and ADR-122's outcomes exist because losing a cohort run costs
thousands of rows, and a 574-row repair is cheaper to re-authorize than to
absorb. Importing those tolerances would widen thresholds this ADR did not
measure.

**Honest limits.** ADR-114 already strengthened copy discipline, and the
unverified rate rose afterwards: 3% on the 100-row canary, 7.5% at 3,939 rows,
8.2% across the full cohort. 451 of 570 failures are the model rewriting text
it was told to copy — the class a prompt instruction has already failed to fix
once. This ADR is a measurement of whether prompt strengthening moves that
rate, not a repair expected to recover most of the 574. A separate observation,
deliberately left unaddressed: the three `adapter_rejection` rows put the
archetype `HARDWARE_SOFTWARE_SYSTEM` into `screen_status`, which the approved
diff does not cover and which no prompt change here attempts to fix.

**Scope.** Twenty-six paths: the repair prompt successor, four schemas, the
repair module, two fixture-only test modules, two CLI modes, the registry
(0.61.0 to 0.62.0, 130 to 134), this decision log, `REPO_MANIFEST.md` (876 to
884), the five registry/manifest guards, and the absolute registry literals in
nine screen suites. No new provider module and no prompt edit: the V5 screen
prompt is byte-identical and SHA-pinned in the new suite.

## Open decisions

- **Why 7.5% of V5 screen rows fail quote validation.** Read-only
  sub-classification of the 295 unverified prefix rows, recorded here as
  evidence for the next review gate and acted on in no way by ADR-118: 78%
  are non-verbatim edits, where the model rewrites a quote it could have
  copied; 19% cite the wrong passage while quoting text that appears verbatim
  in another passage of the same packet; 1.7% cite a reference that does not
  exist, and the observed forms are malformed rather than absent (`P06`, `P03`
  where the renderer emits three digits, and an out-of-range `P046`); the
  remainder are one concatenation across passages, one unparseable payload and
  one out-of-vocabulary status. The unverified population is systematically
  denser than the validated one — 6.28 evidence items versus 4.14, 24.1
  passages per packet versus 18.1 — so the failure correlates with packet
  length rather than with any firm characteristic. The measured 7.5% is 2.5x
  the 3% the 100-row V5 diagnostic canary showed, which is itself evidence
  that a 100-row canary cannot size this rate. Three of these classes are
  addressable without weakening verbatim strictness — the reference format,
  the wrong-passage attribution, and the copy-versus-write instruction — and
  none may be addressed by repairing model output after the fact.

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
- A stage-agnostic rename of `product_candidate_availability_vocabulary@0.1.0`. Three stages now govern `availability_status` through it (see ADR-069); the name still names only the first.
- Whether the second evidence quote on the `Breeze Agents` and `Breeze Copilot` product observations supports the `general_availability` status recorded for them. That quote — "We are also investing in powerful AI capabilities through Breeze Copilot, Breeze Agents…" — is forward-looking investment language, and investing in a capability is not a statement that the capability is generally available. The primary evidence ("Breeze includes Breeze Copilot, an AI-powered companion…") is present-tense and appears sufficient on its own, so the recorded status would most likely survive review. The product decisions are **not** reopened for now: both products have zero accepted capabilities, so nothing downstream reads them — no capability observation, no Snapshot B member, no task run. Noted here so the weak quote is not later mistaken for a checked one; if action is wanted it belongs in its own round, alongside the more general question of whether one sufficient quote should retire a weaker sibling.
- Whether `Payments` is a genuine standalone product or a named feature of `Commerce Hub`. The source text presents it as included within Commerce Hub ("It includes an end-to-end payment solution, Payments…") and Commerce Hub's own "Features include" list sits beside it in the same sentence, but Payments alone carries a dedicated risk-factor paragraph (third-party payment facilitator, money-laundering/fraud liability) that none of Commerce Hub's other named features (payment links, invoicing, quoting) carry — a candidate signal for its own commercial/administrative boundary. Not resolved; the existing product boundary (both as separate Snapshot A members) is left unchanged for this round. Surfaced while deciding the first live `task_extraction` candidates, both of which cite Payments as their product.
- Whether the exploratory extraction beyond ADR-030's admitted firm is to be brought onto the governed path, bounded, or discarded. ADR-030 admits one firm-year, HubSpot FY2024. Fifteen firms were subsequently ingested at one period each, and a five-year panel of eighty firm-periods was ingested and put through product extraction, entirely outside the governed path: packets were built ad hoc because `pilot_packet.py` is pinned to one CIK, no run wrote a governance chain, and no output entered a decision set, snapshot or universe. Eighty-six model calls carry no prompt hash, no packet hash and no run manifest, so none of their results is citable; counted as the scratchpad JSON files carrying `usageMetadata`, and costing 1,559,367 microdollars against the 362,721 of the thirty-five governed runs. An earlier revision of this entry said "roughly 121", a figure repeated from a review without checking it against the files. The corpus and the measurements exist; the admission does not. Recorded so that a later reader does not mistake the disk contents for an admitted universe.
- Whether official-web collection is deferred, bounded to a validation-only role, or still required. ADR-033 records it as "required for corpus completeness" and treats `corpus_scope = sec_only_partial` as provisional, with `official_ir`, `product_pages`, `developer_docs` and `web_archives` at `not_attempted`; that ADR has not been superseded. The measured ground the deferral rested on is withdrawn. It counted URLs beneath a `/products` path -- a range of 8 to 167 across firms -- and those lists carry campaign-parameter duplicates and page types no reading would call products (`business-card-scanner-app`, `ui-builder`, `reporting`). The unit that answers the question is the firm's own product index, and reading one for three firms at temporally valid capture dates gives 6 products plus a bundle for HubSpot, 170 links for ServiceNow, and 16 for MongoDB. Those three captures also settle a narrower point: ADR-033's `not_attempted` cannot be read as `unavailable`, because the sources were located and retrieved -- `web.archive.org/web/20241102000438id_/https://www.hubspot.com/products` (sha256 `e0c6d27e…`, inside FY2024 and before the 2025-02-12 filing), `.../20260101061641id_/https://www.servicenow.com/products-by-category.html` (`d4ce4f08…`, before the 2026-01-29 filing), `.../20260118015728id_/https://www.mongodb.com/products` (`6f5c82cb…`, before the 2026-01-31 period end), and `.../20260101212852id_/https://www.servicenow.com/products/itsm.html` (`ea575c4f…`). All four are exploratory fetches outside the governed collection path, with no snapshot, passage identity or receipt, so none may be cited by an observation. What they measure is not quantity but role. `docs/SOURCE_POLICY.md` gives the product page two roles at once, "customer-facing capability and product packaging", and in these three firms the two do not arrive together: HubSpot's index labels every product "Free and premium plans" and describes no function; ServiceNow's ITSM page carries eighteen or more verb-object-outcome phrases and no commercial term at all -- `Prime`, `pricing`, `per user`, `SKU` and `license` are each zero -- and ServiceNow has no archived pricing page under any of the paths searched. The ablation's question is therefore not whether the site is better than Item 1 but which role it fills in which firm, and a single extraction contract will not cover all three. The counter-evidence is of a different kind, and it is about kind rather than quantity: `docs/SOURCE_POLICY.md` assigns capability to product pages rather than to filings, and Item 1 names features where a product page describes functions. HubSpot's Item 1 gives Marketing Hub four terms ("marketing automation and email, social media, SEO, and reporting and analytics"); the same product's current public pages describe scheduling and tracking posts across four named networks from one dashboard, behavioural workflow triggers, and multi-touch revenue attribution. Deriving a capability from the first requires inventing the verb; the second supplies it. That comparison is itself outside the corpus -- the pages are current, name Hubs that appear in no filing through FY2025, and can support no observation under Rule 3 -- so it bears on the source-scope question and on nothing else. `docs/methodology/VALIDATION_STRATEGY.md` and the ninety-day roadmap both ask for this to be settled by the "Item 1 only versus enriched official corpus" ablation, whose scoring depends on a gold set that does not yet exist. The deferral is therefore reasonable and unrecorded until now; it is not a decision.
- RESOLVED by ADR-112: a per-row model-output failure is a recorded outcome in a separate, structurally non-promotable diagnostic canary, while the authoritative screen keeps its all-or-nothing fail-closed contract unchanged. The authoritative path was not weakened; a second path was added beside it.
- Which cases remain eligible for the frozen test partition after ADR-015 exposure. The product-stage predictions of all fifteen firms at their most recent period were inspected during design work and are permanently ever-exposed; no blind frozen case can be built from that stage at that period. Capability-stage output was inspected for two firms and task-stage output for one, and the 2021-2024 periods were examined only in aggregate. A frozen partition is therefore still constructible from the capability and task stages of the thirteen unexamined firms and from earlier periods, and does not require ingesting new firms. The partition membership itself is a case-set-manifest decision and is not settled here.
- Whether a verb-less feature name is a capability. `docs/methodology/PRODUCT_CAPABILITY_TASK_ONTOLOGY.md` defines a capability as "a concrete function the product provides" and every one of its five examples is a verb phrase, but the definition sentence does not require one; the verb rule is stated in `capability_discovery_schema_v3` and nowhere in the governing documents. Measured on one filing, HubSpot FY2024, three readings put the capability count at 58, 66 and 69: the rule changes the recorded form rather than the count, because the registered prompt verbalises each noun one-for-one (`call tracking` becomes `track calls`). The structural divergence sits one layer down and is stated as a count rather than a rate: of the pipeline's 64 tasks, 60 reference exactly one capability. A single smoke run supports that count; it does not support a rate, and an earlier revision of this entry claimed a factor-of-two capability difference and a task-per-capability ratio without checking either against the outputs on disk. It is a construct decision and belongs to the methodology owner; recording it in the ontology rather than in a prompt is what would bind a gold annotation.
