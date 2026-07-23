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

## Evaluation-run manifest v0.2 and comparison visibility (ADR-025)

`evaluation_run_manifest` advances from `0.1.0` to `0.2.0` and is the authoritative binding point for immutable pre-execution semantic inputs. Beyond the existing prediction-run, case-set, target-registry, scoring/gate-config, code-commit, and runtime pins, v0.2 pins a caller-supplied RFC3339 `evaluation_created_at` (validated and persisted at run initialization, copied verbatim into validation snapshots and validator findings, never clock-read or inferred), the stage-profile registry version/hash and selected-entry hash, the semantic-adapter registry version/hash and selected-entry hash, the source/passage snapshot version/hash, the gold assertion-set version/hash, the axis-taxonomy version/hash, the validator-rule-parameters version/hash, the validator-bundle version/hash, and the applicable stage-evidence version/hash (absent for extraction stages). `registry_snapshot_hash` is not overloaded; each semantic input is a distinct field. Parsed prediction content is a derived output bound through the evaluation-output manifest, not a run-manifest input.

Historical `evaluation_run_manifest@0.1.0` (`7f8909d8e7059952c933c8e30f43044178b3f8a21d4baaa77bfb5c786b38d6ee`) remains readable through a governed frozen-shape historical model and constant; v0.1 documents are never rewritten and v0.2-only semantic identities are never retrofitted into them. A comparison whose two run manifests differ in version (v0.1 vs v0.2) is `noncomparable_contract`. The comparator consumes v0.2 bindings and maps a changed target-registry, gold assertion-set, axis-taxonomy, or applicable stage-evidence hash to `changed_gold`; a changed selected stage-profile entry identity/hash to `noncomparable_contract` (it changes metric-family applicability and/or required stage evidence); a changed selected semantic-adapter entry identity/hash to `noncomparable_contract`; a changed validator-bundle or validator-rule-parameters hash to `changed_validator_contract`; consumed source/passage byte changes through the authoritative per-case input-packet hash to `changed_input_packet`; a global source/passage snapshot difference with identical consumed per-case packets to provenance-only; and `prediction_run_manifest_hash` to provenance-only. A changed stage-profile registry version/hash whose selected entry identity/hash is identical, and a changed semantic-adapter registry version/hash whose selected adapter entry identity/hash is identical, are provenance-only for pairwise comparison; provenance-only here describes only pairwise run-comparison classification and is not a change-control exemption — registry edits still require normal governed version/hash updates and review. The existing noncomparability vocabulary suffices and no new `NoncomparabilityClass` value is added: `comparison_manifest` stays at `0.2.0` (`6a1253b72664bff73e872d1230fb3d52772a438f55915406010e105b4f5d29a5`) with its committed model hash unchanged; only comparator logic reads the new v0.2 fields.

## Revision history

- 2026-07-19 — Revised per ADR-012, ADR-014, ADR-019, ADR-020, ADR-021: evaluation runs and comparison artifacts as first-class immutable units, assertion-level regression accounting and ledgers, four chained state vocabularies, qualification registry, partition/suite report dimensions.
- 2026-07-23 — Revised per ADR-025: evaluation-run-manifest v0.2 semantic-input pins, v0.1 read-only compatibility, v0.1↔v0.2 noncomparability, and comparator visibility of gold/taxonomy/adapter/stage-evidence changes with the unchanged comparison-manifest contract.
