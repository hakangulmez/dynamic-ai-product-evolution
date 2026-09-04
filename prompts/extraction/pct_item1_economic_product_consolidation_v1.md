# pct_item1_economic_product_consolidation_v1

## Input

You receive two things for one firm--filing observation:

1. the complete verified Item 1 packet, whose passages are labelled `P001`,
   `P002`, and so on; and
2. a discovery candidate map containing product-family names and product IDs.

The candidate map is high-recall working material, not a finding. Read the
whole Item 1 packet before deciding. Use Item 1 as the evidence for every
decision.

## Task

Build the smallest evidence-supported map of the firm's economically meaningful
customer products.

An economic product is a separately identifiable offering that a customer can
buy, license, subscribe to, deploy, or use as part of the firm's commercial
offering.

Keep candidates separate only when Item 1 supports them as independently
commercially distinct offerings. Different technical names, modules, brands,
editions, features, or delivery variants do not by themselves establish
separate economic products.

Combine candidates into one economic product when they describe the same
customer-facing product, customer purchase, license, subscription, deployment,
or customer work. In particular, if candidates have the same customer-facing
function and Item 1 gives them the same supporting description, combine them
rather than creating separate economic products.

For every discovery product ID, do exactly one of the following:

- include it in exactly one `economic_product` through `source_product_ids`; or
- put it in `not_selected_product_ids`.

Do not create a new source-product ID and do not silently drop a candidate.
Do not select a feature, plan, edition, add-on, delivery channel, internal
technology, acquisition, strategy, or generic benefit as its own economic
product unless Item 1 establishes that customers obtain it as an independently
commercially distinct offering.

For each selected economic product, give one concise commercial `name`. Do not
extract capabilities, tasks, task families, customer benefits, revenue, tiers,
scores, or reasoning in this stage.

## Evidence

Every economic product must cite one to three `passage_refs` that directly
support its commercial distinctness. Return only labels such as `P007`. Do not
write quotes, offsets, hashes, page numbers, explanations, or reasoning.

## Output

Return exactly one JSON object and nothing else. Use identifiers `EP1`, `EP2`,
... for economic products.

```json
{
  "economic_products": [
    {
      "id": "EP1",
      "name": "Example commercial platform",
      "source_product_ids": ["P2", "P4"],
      "passage_refs": ["P007"]
    }
  ],
  "not_selected_product_ids": ["P1", "P3"]
}
```
