# Evaluations

The evaluation suite is a release gate, not a post-hoc dashboard. It includes:

- deterministic schema, provenance, temporal, and contamination tests;
- manually adjudicated gold data;
- adversarial passages;
- model/prompt regression fixtures;
- error-taxonomy reports.

Gold data should remain blinded from financial outcomes and prior project outputs.

## Key documents

- `EVAL_HARNESS.md`: evaluation layers and release gates.
- `CHANGE_CONTROL_PROTOCOL.md`: binding prompt-change workflow.
- `templates/`: case and change-request templates.
- `cases/`: immutable, split-agnostic evaluation-case files; partition (`dev`, `frozen_test`) and overlapping suite membership live in the versioned, append-only case-set manifest.
- `reports/`: immutable evaluation reports.

- `rubrics/UNIVERSE_CLASSIFICATION_RUBRIC.md`: Stage 00 screening, taxonomy, Tier A/B/C derivation, boundary review, and negative-audit evaluation.
