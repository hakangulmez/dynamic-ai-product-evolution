# Evaluation Harness Build Plan

## Purpose

This document converts the evaluation methodology into an implementation sequence that Claude Code can execute in bounded phases. The first objective is not a polished dashboard. It is a reliable mechanism for deciding whether a prompt version improved general performance without violating evidence, temporal, or schema rules.

## Phase 1 — Evaluation foundation

### Deliverables

1. Typed evaluation-case model.
2. JSON schema for evaluation cases.
3. Deterministic validators.
4. Eval runner CLI.
5. Machine-readable and Markdown reports.
6. Explicit alias-based entity matching.
7. Twelve or more hand-readable fixtures.
8. Unit and integration tests.
9. Non-developer usage documentation.

### Required validators

- prediction schema validity;
- required fields;
- source ID resolution;
- passage ID resolution;
- evidence quote substring validation;
- publication date not later than observation cutoff;
- product–capability–task parent validity;
- duplicate record and duplicate ID detection;
- prohibited legacy fields;
- unsupported customer-facing task;
- roadmap-only evidence incorrectly coded as active;
- preservation of raw prediction and repair records.

### Initial metrics

- schema-validity rate;
- evidence-validity rate;
- unsupported-claim rate;
- temporal-leakage count;
- duplicate rate;
- product precision and recall;
- capability precision and recall;
- task precision and recall.

Semantic matching must not call an LLM in Phase 1. Use stable gold IDs and accepted aliases.

## Phase 2 — Version comparison and change control

### Deliverables

- accepted-prompt registry;
- candidate-versus-accepted comparison;
- fixed-case list;
- new-regression list;
- metric deltas;
- hard-gate comparison;
- change-request linkage;
- immutable prompt-release record.

### Acceptance logic

A candidate cannot be promoted if:

- any critical hard gate fails;
- frozen-set degradation exceeds the accepted tolerance;
- a new regression affects a protected failure class;
- the prompt and schema are incompatible;
- a construct change occurred without a methodology decision.

## Phase 3 — Minimal local review console

Build the first four Streamlit pages described in `docs/architecture/RESEARCH_CONSOLE_ARCHITECTURE.md`.

### Persistence

- SQLite for append-only human reviews;
- original predictions and gold cases remain immutable;
- derived accepted records are generated, not manually overwritten.

## Phase 4 — Extraction-pipeline integration

Connect the eval harness to:

- product discovery;
- product consolidation;
- capability extraction;
- task discovery;
- task consolidation;
- task-role classification.

Every pipeline stage must emit a run manifest compatible with the harness.

## Phase 5 — Longitudinal and measurement evaluation

Add:

- predecessor/successor matching fixtures;
- transition-label metrics;
- frontier-baseline validation;
- depth, scale, and defensibility component checks;
- unknown calibration;
- source-ablation comparisons.

## File layout

```text
evals/
├── cases/
│   ├── dev/
│   ├── frozen_test/
│   ├── adversarial/
│   └── regression/
├── expected/
├── templates/
├── change_requests/
├── rubrics/
├── reports/
└── snapshots/

src/dynamic_ai_products/evaluation/
├── models.py
├── loaders.py
├── validators.py
├── matcher.py
├── metrics.py
├── comparator.py
├── runner.py
└── report.py

apps/research_console/
├── app.py
├── pages/
├── components/
└── services/
```

## Stop conditions

Each implementation phase must stop after:

- deliverables are written;
- tests pass;
- commands are documented;
- changed files are listed;
- limitations are summarized.

Claude Code must not automatically continue into the next phase.
