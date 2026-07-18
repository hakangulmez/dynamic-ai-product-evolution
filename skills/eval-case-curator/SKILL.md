# Evaluation Case Curator Skill

## Use when

A model output has been identified as correct, incorrect, ambiguous, or potentially important for regression coverage.

## Required reading

- `docs/methodology/PROMPT_DEVELOPMENT_AND_EVALUATION_PROTOCOL.md`
- `evals/CHANGE_CONTROL_PROTOCOL.md`
- `specs/SPEC-022-evaluation-data-model.md`
- the governing stage methodology and rubric.

## Procedure

1. Identify the stage and general failure class.
2. Preserve the complete dated source packet needed to judge the case.
3. Record source and passage IDs.
4. Describe the expected entity using a stable gold ID and accepted aliases.
5. Record forbidden interpretations.
6. Mark fields that must remain unknown.
7. Assign the case to development, frozen test, adversarial, or regression.
8. Validate that no financial outcome or legacy score influenced the expected label.
9. Run schema and evidence checks.
10. Request methodology-owner approval.

## Do not

- create ticker-specific production rules;
- change expected output merely to match the model;
- use a future source for an earlier observation;
- omit ambiguous or unknown states;
- expose frozen-test cases during routine tuning.

## Output

A validated evaluation case and, when appropriate, a linked change request.
