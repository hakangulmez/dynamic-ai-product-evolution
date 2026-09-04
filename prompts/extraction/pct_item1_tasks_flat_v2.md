# pct_item1_tasks_flat_v2

**Status: development A/B smoke draft.** Use only with a saved economic-product
and capability candidate map plus the complete Item 1 packet. It is not a
production, scoring, or universe-membership prompt.

## Input

You receive a working candidate map of selected economic products and their
capability candidates, followed by the complete verified Item 1 packet for one
firm--filing observation. The map is not a finding. Read the whole packet and
use Item 1 as evidence for every output.

## Task

For each input economic product, state the distinct customer **tasks** its
capabilities enable. A task is one customer action on an identifiable object or
deliverable. Write a concise verb phrase such as `edit photographs for creative
projects`.

Split tasks when they produce, manage, analyze, edit, design, or deliver a
materially different customer output. Merge only genuine substeps, formats, or
near-synonyms of the same action. Do not produce interface clicks, generic
benefits, strategies, or a task catalogue. Do not add, remove, merge, rename,
or otherwise decide economic products or capabilities: this call maps them to
tasks only.

Every task must belong to one supplied economic product and cite one or more
supplied capability references from that same product. Capability references
are composite IDs such as `EP1:C2`: use them exactly, never the local `C2`
portion alone. Produce at least one task for each supplied economic product,
without assuming a target count.

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
