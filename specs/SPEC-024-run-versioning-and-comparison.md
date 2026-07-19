# SPEC-024 — Run Versioning and Prompt Comparison

## Status

Draft

## Objective

Ensure every extraction/prediction run, evaluation run, and comparison is immutable, reproducible, and comparable under an explicit comparison contract, and define the qualification registry and the state vocabularies used for prompt release.

## Run directory

```text
data/runs/<run_id>/
```

Required artifacts for an extraction/prediction run:

- run manifest;
- input manifest;
- source packet manifest;
- raw output;
- parsed output;
- repair records;
- deterministic findings.

Evaluation reports, assertion results, and comparison outputs are not extraction-run artifacts; they belong to independent immutable evaluation runs and comparison artifacts (ADR-012, ADR-020). The canonical evaluation-run root path is an open decision tracked in `docs/DECISION_LOG.md`. Historical run directories remain valid as written.

## Run identity

The run ID must be unique and include a timestamp or generated identifier. Existing directories cannot be overwritten.

## Evaluation runs

An evaluation run is a first-class immutable unit referencing by hash:

- prediction run ID and manifest hash;
- case-set version/hash;
- source/passage registry snapshot version/hash;
- validator bundle version/hash;
- scoring/gate configuration version/hash;
- code commit;
- model/provider/prompt hashes where applicable.

The same prediction run must be re-verifiable with the same case set, re-evaluable under new validator versions, and comparable across case-set versions without re-running extraction (ADR-012).

## Comparison outputs

The regression primitive is a comparable assertion outcome transition `satisfied → unsatisfied` under an explicit comparison contract (ADR-020). Comparisons must produce:

- an assertion-level transition ledger over the outcome vocabulary (`satisfied`, `unsatisfied`, `indeterminate`, `not_applicable`, `not_evaluated`), with transition classes including regression, improvement, coverage_or_certainty_degradation, and explicit noncomparability classes: `changed_assertion_contract`, `changed_gold`, `changed_input_packet`, `changed_validator_contract`, `added_assertion`, `removed_assertion`, `noncomparable_contract`;
- `new_failure_without_comparable_baseline` for failures with no baseline counterpart — reported separately, never counted as regression, and still able to fail current gates;
- a derived case-level ledger: `newly_failing`, `newly_passing`, `degraded_but_still_passing`, `degraded_and_still_failing`, `improved_but_still_failing`, `unchanged_passing`, `unchanged_failing`, `indeterminate`, `noncomparable`, `added_case`, `removed_case`, and `additional_protected_regression`;
- slice and metric deltas with support counts and, where applicable, confidence intervals;
- hard-gate changes;
- results by stage, partition, suite, assertion kind, failure class, severity, company, year, firm stratum, classification axis, tier boundary, verification status, gold origin, and protected status (ADR-014, ADR-020).

## Comparison artifacts

A comparison is a separate immutable artifact with its own ID and manifest, referencing the baseline and candidate evaluation runs by ID and manifest hash, plus the comparison-contract version/hash, case/assertion mapping version, failure-taxonomy version, scoring/gate configuration version, and code commit. Identical inputs must reproduce an identical deterministic output hash; a differing hash is a determinism defect. Comparisons carry their own execution status (`completed`, `invalid`, `errored`) and verdict (`pass`, `fail`, `indeterminate`).

Baselines are versioned roles fixed before candidate results are seen: `current_frozen_prompt`, `accepted_release`, `previous_candidate`, `model_upgrade_baseline`, `validator_bridge_baseline`, `reproducibility_baseline` (ADR-020).

## State vocabularies

Four distinct, chained vocabularies (ADR-019):

1. evaluation execution status: `completed`, `invalid`, `errored`;
2. gate verdict: `pass`, `fail`, `indeterminate`;
3. review decision: `accept_candidate`, `accept_with_documented_nonblocking_tradeoff`, `revise`, `reject`;
4. prompt lifecycle: `draft`, `candidate`, `accepted`, `frozen`, `deprecated`.

`rejected` is not a lifecycle state; a rejected candidate retains its immutable artifact and review event. Release exceptions are separate governance records; the evaluation verdict remains `fail`.

## Qualification registry

Qualification binds prompt artifact × execution/routing contract × stage/output contract (ADR-021). The registry records at least:

- qualification ID;
- prompt path and prompt artifact version/hash;
- execution/routing contract identity/hash;
- stage/output contract identity/hash;
- compatible schema;
- governing spec;
- qualification scope: `qualified_for_development`, `qualified_for_shadow_or_pilot`, `qualified_for_release`;
- supporting eval/comparison references;
- qualification status;
- decision timestamp;
- supersedes/superseded-by references;
- known limitations.

Requalification scope is fixed by the versioned change-classification policy before candidate results are seen; the policy contents are an open decision. Adapter-level qualification, enablement, and run authorization are defined in SPEC-027, which consumes qualification references from this registry without redefining them.

## Acceptance criteria

A release decision must link the qualification record, evaluation run, comparison artifact, change request, prompt hash, schema hash, governing spec path and immutable spec content hash (plus the declared numeric spec version only when one exists), scoring/gate configuration hash, and code commit. Release records remain valid while the governing spec is Draft and carries no numeric version; no substitute numeric version is invented.

## Revision history

- 2026-07-19 — Revised per ADR-012, ADR-014, ADR-019, ADR-020, ADR-021: evaluation runs and comparison artifacts as first-class immutable units, assertion-level regression accounting and ledgers, four chained state vocabularies, qualification registry, partition/suite report dimensions.
