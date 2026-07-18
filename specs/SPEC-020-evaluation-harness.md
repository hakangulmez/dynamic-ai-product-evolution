# SPEC-020 — Evaluation Harness

## Status

Draft

## Objective

Run deterministic, gold, adversarial, frozen-test, and regression evaluations and produce a versioned release decision.

## Inputs

- evaluation cases;
- source and passage registries;
- stage predictions;
- output schemas;
- accepted aliases and stable gold IDs;
- prompt, spec, model, and code versions.

## Outputs

- structured validator findings;
- machine-readable evaluation report;
- human-readable Markdown report;
- candidate-versus-accepted diff;
- pass/fail hard-gate result;
- release recommendation.

## Governing documents

- `CLAUDE.md`
- `docs/methodology/PROMPT_DEVELOPMENT_AND_EVALUATION_PROTOCOL.md`
- `evals/CHANGE_CONTROL_PROTOCOL.md`
- `docs/SOURCE_POLICY.md`
- `docs/TEMPORAL_POLICY.md`
- relevant stage methodology document.

## Core rules

- no behavior-changing prompt edit without a linked case and change request;
- original predictions and gold records are immutable;
- deterministic checks run before semantic metrics;
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

Stage-specific metrics are defined in `evals/EVAL_HARNESS.md`.

## Failure handling

Failures are emitted to a structured, versioned findings table. No record is silently skipped or repaired.

## Acceptance criteria

- all critical gates pass;
- accepted stage thresholds pass;
- frozen and regression results remain within approved tolerances;
- candidate comparison identifies all fixed and regressed cases;
- release decision links the change request, run, prompt hash, schema hash, spec version, and code commit.

## Run manifest

Every run records code commit, spec version, schema hash, prompt hash, model route, source-manifest hash, input-manifest hash, timestamps, retry count, fallback behavior, and exclusions.

## Open questions

Thresholds and adjudicator agreement targets will be finalized during the sentinel pilot and recorded in `docs/DECISION_LOG.md`.
