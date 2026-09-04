# pct_item1_tasks_flat_v5

## Input

You receive two things for one firm--filing observation:

1. a fixed economic-product and capability map produced by the preceding
   stage; and
2. a selected Item 1 evidence bundle. Its passages are labelled `P001`,
   `P002`, and so on, and are the only Item 1 evidence available for this
   stage.

The supplied map is fixed: do not add, remove, merge, rename, or otherwise
decide economic products or capabilities. Use only the selected evidence bundle
to support tasks. Do not infer information from Item 1 passages not supplied.

## Task

For each supplied economic product, state the distinct customer **tasks** its
capabilities enable.

A task is a commercially meaningful action that the customer performs on an
identifiable object by using that economic product. State it as an action plus
object, not as a benefit, desired result, or performance improvement.

A task is not the firm's internal operation, a generic benefit, a business
outcome, or an interface click.

Do not create one task for every capability. Combine capabilities into one task
when they support the same customer action on the same object. A task may use
one or more capabilities. Do not restate a capability as a task.

Keep tasks separate only when the customer works on a materially different
object, deliverable, or work objective. Do not split one customer job into a
catalogue of feature-level tasks.

Every task must belong to one supplied economic product and name one or more
supplied capabilities from that same product. Capability references are
composite IDs such as `EP1:C2`: use them exactly, never the local `C2` portion
alone. Produce at least one task for each supplied economic product, without
assuming a target count. When a product has only one supported customer action,
one task is sufficient.

## Evidence and output

Every task must cite one to three `passage_refs` from the selected evidence
bundle. Return no quotes, offsets, hashes, explanations, scores, tiers, revenue
estimates, workflows, or reasoning.

Return exactly one JSON object and nothing else. Use task IDs `T1`, `T2`, ... .

```json
{
  "tasks": [
    {
      "id": "T1",
      "economic_product_id": "EP1",
      "capability_refs": ["EP1:C2"],
      "text": "edit photographs for creative projects",
      "passage_refs": ["P007"]
    }
  ]
}
```
