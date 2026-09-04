# pct_item1_task_consolidation_v1

## Input

You receive two fixed maps for one firm--filing observation:

1. an economic-product and capability map; and
2. high-recall task candidates produced from that map.

Each task candidate already carries its supporting Item 1 passage references.
The maps are fixed working material. Do not add, remove, rename, or alter an
economic product, capability, task candidate, capability reference, or passage
reference.

## Task

Produce the smallest set of distinct customer tasks supported by the supplied
task candidates.

A final task is a commercially meaningful action a customer performs on an
identifiable object, record, decision, transaction, content item, analysis, or
delivered service by using one economic product.

Keep two tasks separate only when customers can reasonably seek one without the
other because they have materially different objects, deliverables, or customer
work objectives.

Merge candidates when they describe the same customer job through different
features, interface steps, formats, channels, or adjacent workflow actions. A
final task may therefore combine multiple candidate task IDs and multiple
capability references.

Exclude a candidate only when it is a capability restatement, generic benefit
or outcome, internal firm activity, pricing/sales/deployment/delivery mechanism,
or interface-level step.

Write every final task as an action plus its identifiable object. Do not write a
benefit such as "improve productivity", "increase engagement", or "enable
digital transformation". Do not assume a target number of final tasks.

## Provenance

Every final task must name one or more source task IDs. Its capability references
must be drawn only from those source task candidates and must belong to the same
economic product. Do not create or select passage references: the pipeline
retains the Item 1 evidence already attached to the named source tasks.

## Output

Return exactly one JSON object and nothing else. Use identifiers `FT1`, `FT2`,
... for final tasks.

```json
{
  "final_tasks": [
    {
      "id": "FT1",
      "economic_product_id": "EP1",
      "source_task_ids": ["T1", "T2"],
      "capability_refs": ["EP1:C1", "EP1:C2"],
      "text": "manage customer records and sales opportunities"
    }
  ],
  "excluded_task_candidates": [
    {"task_id": "T3", "reason": "capability_restatement"}
  ],
  "unresolved_task_ids": []
}
```
