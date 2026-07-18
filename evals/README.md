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
- `cases/`: development, frozen, adversarial, and regression splits.
- `reports/`: immutable evaluation reports.

- `rubrics/UNIVERSE_CLASSIFICATION_RUBRIC.md`: Stage 00 screening, taxonomy, Tier A/B/C derivation, boundary review, and negative-audit evaluation.
