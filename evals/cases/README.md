# Evaluation Case Splits

- `dev/`: visible cases used during prompt development.
- `frozen_test/`: protected generalization cases not used for routine tuning.
- `adversarial/`: deliberately misleading or difficult examples.
- `regression/`: permanent cases for previously corrected failures.

Use `evals/templates/eval_case.template.json` and follow `SPEC-022`.
