# SPEC-020 — Evaluation Harness

## Status

Draft

## Objective

Run deterministic, gold, adversarial, frozen-test, and regression evaluations and produce a versioned, layered acceptance result: evaluation validity → protected behavioral invariants → metric and regression gates → human review → lifecycle transition.

## Inputs

- evaluation cases and case-set manifests;
- prediction envelopes from manifest-bearing prediction runs;
- source and passage registry snapshots;
- output schemas;
- accepted aliases and stable gold IDs;
- versioned scoring/gate configuration;
- prompt artifact identity, declared version where available, and immutable content hash;
- governing spec path/identity and immutable spec content hash;
- declared numeric spec version only when one exists;
- model and execution-contract identity;
- code commit.

A Draft spec without a numeric version remains a valid governing input; no numeric version or placeholder version is invented.

## Outputs

- structured validator findings;
- machine-readable evaluation report;
- human-readable Markdown report;
- evaluation execution status (`completed`, `invalid`, `errored`);
- gate verdict (`pass`, `fail`, `indeterminate`);
- comparison artifact reference (SPEC-024);
- release recommendation, as input to human review — never a decision by itself.

## Governing documents

- `CLAUDE.md`
- `docs/DECISION_LOG.md` (ADR-011 through ADR-022)
- `docs/methodology/PROMPT_DEVELOPMENT_AND_EVALUATION_PROTOCOL.md`
- `evals/CHANGE_CONTROL_PROTOCOL.md`
- `docs/SOURCE_POLICY.md`
- `docs/TEMPORAL_POLICY.md`
- relevant stage methodology document.

## Core rules

- no behavior-changing prompt edit without a linked case and change request;
- original predictions and gold records are immutable;
- deterministic checks run before semantic metrics;
- the evaluation case is the execution unit, the assertion is the atomic scoring unit, and the evaluation run is the acceptance-gate unit (ADR-011);
- an `invalid` or `errored` evaluation produces no verdict about the candidate (ADR-019);
- blocking gates are computed only on verified gold; provisional-gold results are diagnostics (ADR-013);
- insufficient verified support yields `indeterminate`, never an automatic pass or fail (ADR-019);
- human dispositions and release exceptions never alter findings, metrics, or gate verdicts (ADR-018, ADR-019);
- critical evidence, time, schema, or contamination failures block release;
- exact textual equality is not required when stable gold IDs and accepted aliases match;
- no LLM judge in the initial deterministic harness;
- all reports are versioned and cannot overwrite an existing run.

## Deterministic validations

- output validates against the declared schema;
- required fields exist;
- source and passage references resolve;
- evidence quotes occur in cited passages;
- observation dates satisfy temporal policy;
- product–capability–task links resolve;
- duplicate IDs are detected;
- prohibited legacy fields are absent;
- roadmap-only evidence does not create active records;
- original model output and any repair records are preserved.

## Metrics

At minimum:

- schema-validity rate;
- evidence-validity rate;
- unsupported-claim rate;
- temporal-leakage count;
- duplicate rate;
- product precision/recall;
- capability precision/recall;
- task precision/recall.

Stage-specific metric families and error-cost profiles are binding:

- the universe screen is gated on the unsafe-exclusion confidence upper bound; pass-through burden is an operational profile, never a false-positive rate (ADR-016);
- classification axes use axis-native metric families with a separate abstention contract targeting false confidence, not a lower unknown rate (ADR-017);
- deterministic tier derivation is evaluated as a 100% contract; any deviation is a defect (ADR-017);
- no single aggregate score may serve as a gate.

Stage-specific metrics are defined in `evals/EVAL_HARNESS.md`.

## Scoring and gate configuration

This specification owns the behavioral contract of the versioned scoring/gate configuration. Each gate definition must specify at least:

- metric ID and population/slice identity;
- verified-support requirements;
- confidence-interval method references where applicable;
- blocking severity;
- protected-regression class references;
- slice definitions;
- configuration version and hash.

Numeric thresholds, tolerances, and budgets live in the versioned configuration, never in this specification or in schemas. The concrete configuration schema is defined separately.

## Failure handling

Failures are emitted to a structured, versioned findings table per SPEC-023. Human dispositions are recorded per SPEC-022 and never modify raw findings. No record is silently skipped or repaired.

## Acceptance criteria

- evaluation validity precedes all gate computation;
- all protected behavioral invariants hold; they are lexicographic and no metric improvement compensates for them;
- all critical gates pass on verified gold;
- frozen and regression results satisfy the versioned gate configuration;
- candidate comparison identifies all fixed and regressed cases per SPEC-024;
- the release decision links the change request, evaluation run, comparison artifact, prompt hash, schema hash, governing spec path and immutable spec content hash (plus the declared numeric spec version only when one exists), scoring-configuration hash, and code commit;
- no later layer compensates an earlier blocking layer (ADR-019).

## Run manifest

Every run records code commit, governing spec path/identity, immutable spec content hash, the declared numeric spec version only when one exists, schema hash, prompt hash, model route, source-manifest hash, input-manifest hash, timestamps, retry count, fallback behavior, and exclusions. Run manifests and release records remain valid while the governing spec is Draft and carries no numeric version; no substitute numeric version is invented. Acceptance binds to prompt artifact × execution/routing contract × stage/output contract (ADR-021); the qualification registry is defined in SPEC-024.

## Open questions

Numeric thresholds, tolerances, and adjudicator agreement targets live in the versioned scoring/gate configuration and are finalized during the sentinel pilot; open decisions are tracked in `docs/DECISION_LOG.md`.

## Revision history

- 2026-07-19 — Revised per ADR-011, ADR-013, ADR-016, ADR-017, ADR-018, ADR-019, ADR-021: assertion grain, execution-status and verdict vocabularies, verified-gold gating, stage-specific error-cost profiles, scoring/gate configuration ownership, disposition and exception boundaries.
