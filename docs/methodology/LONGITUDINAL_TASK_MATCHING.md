# Longitudinal Task Matching

## Goal

Determine whether task observations across adjacent periods represent continuity, transformation, replacement, or genuinely new work.

## Candidate generation

Use deterministic features to create possible predecessor links:

- same firm and related product;
- normalized product names;
- customer-need embedding similarity;
- capability overlap;
- object and deliverable similarity;
- predecessor/successor dates.

Candidate generation should favor recall and may propose many-to-many links.

## Adjudication labels

- `same_task_unchanged`
- `renamed_or_repackaged`
- `expanded_scope`
- `contracted_scope`
- `ai_assisted`
- `generative_transformation`
- `workflow_integrated`
- `agentified_or_action_enabled`
- `split_into_multiple_tasks`
- `merged_from_multiple_tasks`
- `replaced`
- `discontinued`
- `new_task`
- `uncertain`

## Governing question

> Does the successor serve the same underlying customer need and deliverable, or does it create a distinct economic job?

Production technology may change while the task remains the same. Conversely, a product-name continuity does not prove task continuity.

## Evidence

Transition decisions cite both predecessor and successor evidence. Disappearance from one filing alone is not discontinuation; seek corroboration from product status, later filings, or official pages.

## Confidence

- high: explicit continuity or replacement evidence;
- medium: strong semantic and product continuity;
- low: plausible but source coverage incomplete;
- unresolved: preserve alternatives.

## Evaluation

The gold set must include renames, bundles, acquisitions, split/merge cases, and true AI-driven task transformations.
