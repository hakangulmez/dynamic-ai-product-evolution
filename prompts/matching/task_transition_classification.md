# Task Transition Classification

## Governing spec

`SPEC-013`

## System instruction

Compare predecessor and successor task observations. Determine whether the same underlying customer need and deliverable continued, changed, or disappeared.

Allowed labels:

- same_task_unchanged
- renamed_or_repackaged
- expanded_scope
- contracted_scope
- ai_assisted
- generative_transformation
- workflow_integrated
- agentified_or_action_enabled
- split_into_multiple_tasks
- merged_from_multiple_tasks
- replaced
- discontinued
- new_task
- uncertain

AI wording alone cannot justify an AI transition label. Identify the concrete change in action, output, context, autonomy, or workflow.

Return predecessor and successor IDs, label, concise audit rationale, evidence from both dates, confidence, and alternative labels if unresolved.
