# pct_item1_tasks_flat_v3

## Input

You receive two things for one firm--filing observation:

1. the complete verified Item 1 packet, whose passages are labelled `P001`,
   `P002`, and so on; and
2. a fixed economic-product and capability map produced by the preceding
   stage.

Read the whole Item 1 packet before deciding. Use Item 1 as the evidence for
every output. The supplied map is fixed: do not add, remove, merge, rename, or
otherwise decide economic products or capabilities.

## Task

For each supplied economic product, state the distinct customer **tasks** its
capabilities enable.

A task is a commercially meaningful action that the customer performs on an
identifiable object by using that economic product. State it as an action plus
object, not as a benefit, desired result, or performance improvement.

A task is not the firm's internal operation, a generic benefit, a business
outcome, or an interface click.

Do not create one task for every capability. A task may use one or more
capabilities. Include a task only when it represents a distinct customer work
objective; combine capabilities that support that same objective. Do not
restate a capability as a task.

Merge only entries that describe the same action in different wording, formats,
channels, or interface steps. Keep tasks separate when the customer produces,
manages, analyzes, designs, verifies, or delivers a materially different object
or result, even if the actions occur in the same workflow. Do not produce a
task catalogue.

Every task must belong to one supplied economic product and name one or more
supplied capabilities from that same product. Capability references are
composite IDs such as `EP1:C2`: use them exactly, never the local `C2` portion
alone. Produce at least one task for each supplied economic product, without
assuming a target count.

## Evidence and output

Every task must cite one to three `passage_refs` such as `P007` that directly
support it. Return no quotes, offsets, hashes, explanations, scores, tiers,
revenue estimates, workflows, or reasoning.

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
