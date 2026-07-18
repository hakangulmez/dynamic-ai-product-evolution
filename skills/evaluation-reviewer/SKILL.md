# Evaluation Reviewer Skill

## Purpose

Review eval failures and determine whether to repair data, prompt, rubric, or code.

## Required reading

- `SPEC-020`
- `EVAL_HARNESS.md`

## Procedure

1. Classify error source.
2. Check for systematic patterns.
3. Avoid patching prompts to one firm.
4. Propose minimal versioned change.
5. Add regression fixture.

## Output discipline

- Use the governing schema.
- Cite source and passage IDs.
- Preserve unknowns and ambiguity.
- Write concise audit rationales, not hidden chain-of-thought.
- Produce a run manifest.

## Stop conditions

- A proposed change lacks a measurable acceptance criterion.
