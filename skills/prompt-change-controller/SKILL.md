# Prompt Change Controller Skill

## Use when

A behavior-changing edit to a production prompt, rubric instruction, or model contract is proposed.

## Required reading

- `docs/methodology/PROMPT_DEVELOPMENT_AND_EVALUATION_PROTOCOL.md`
- `evals/CHANGE_CONTROL_PROTOCOL.md`
- the relevant extraction or measurement spec;
- current accepted prompt report.

## Procedure

1. Confirm a change request exists.
2. Confirm the current accepted prompt fails the linked eval case.
3. State the general failure class.
4. Make the smallest general change that can address it.
5. Do not change unrelated examples or rules.
6. Run development, adversarial, regression, and frozen evaluations.
7. Produce candidate-versus-accepted comparison.
8. Identify fixed cases and new regressions.
9. Check all hard gates.
10. Submit an acceptance, rejection, or revision recommendation.

## Stop conditions

Stop and request a methodology decision if:

- the construct definition must change;
- the change trades recall for a protected precision class;
- gold labels conflict;
- temporal or evidence rules are unclear;
- the desired change is motivated only by one company’s final score.

## Output

A versioned candidate prompt, evaluation report, comparison report, and completed change request.
