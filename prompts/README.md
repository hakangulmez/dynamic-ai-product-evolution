# Prompt Library

Prompts are versioned research instruments. Production prompts must:

- cite the governing spec;
- declare input and output schemas;
- require evidence IDs and quotes;
- prohibit future leakage and unsupported inference;
- preserve unknowns;
- avoid hidden dependence on later measurement stages.

Files contain system instructions, user-input templates, and final validation checklists. Do not edit a frozen prompt in place; create a new version.

## Prompt change policy

No behavior-changing production prompt edit is allowed without:

- a linked evaluation case;
- an approved expected result;
- a change request;
- full development, adversarial, regression, and frozen comparison;
- a release decision.

Read `docs/methodology/PROMPT_DEVELOPMENT_AND_EVALUATION_PROTOCOL.md`.

## Implementation prompts

`prompts/implementation/` contains copy-paste task specifications for Claude Code. These are engineering instructions, not extraction instruments. The current sequence is:

1. `phase_0_company_universe.md`
2. `phase_1_eval_harness.md`
3. `phase_2_review_console.md`
