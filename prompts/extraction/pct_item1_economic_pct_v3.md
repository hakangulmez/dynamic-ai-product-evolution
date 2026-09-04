# pct_item1_economic_pct_v3

## Input

You receive two things for one firm--filing observation:

1. the complete verified Item 1 packet, whose passages are labelled `P001`,
   `P002`, and so on; and
2. a **discovery candidate map**, containing local product-family IDs and
   product IDs.

The candidate map is high-recall working material, not a finding. Read the
whole Item 1 packet before deciding. Use Item 1 as the evidence for every
decision.

## Task

Build a concise product--capability--task (PCT) map for the firm's
**economically meaningful customer products**.

An economic product is a separately identifiable offering that a customer can
buy, license, subscribe to, deploy, or use as part of the firm's commercial
offering. It may combine two or more discovery candidates when they are names,
modules, editions, or delivery variants of one customer product. Do not create
a detailed product catalogue.

When you combine product candidates into one economic product, do not also
return any of those same candidates as separate economic products.

A product-family ID (`F#`) may help name or organize an economic product, but
it is not a source product. Every selected economic product must list one or
more underlying product IDs (`P#`) in `source_product_ids`. Keep candidates
separate only when Item 1 supports them as independently commercially distinct
offerings. Combine candidates that are modules, brands, editions, features, or
delivery variants of one customer product.

For every discovery product ID, do exactly one of the following:

- include it in exactly one `economic_product` through `source_product_ids`; or
- put it in `not_selected_product_ids`.

Do not create a new source-product ID and do not silently drop a candidate.
Select a product only where Item 1 supports its commercial distinctness. Do not
select features, plans, editions, add-ons, delivery channels, internal
technology, acquisitions, strategy, or generic benefits as economic products.

For each selected economic product:

1. give a concise commercial `name`;
2. state concrete customer-available **capabilities** as verb phrases; and
3. state commercially meaningful customer **tasks** that customers perform or
   accomplish by using the product.

A capability is a discrete function the customer can use in the product. It is
what the product enables the customer to do. Do not state a product name,
generic benefit, strategy, or business outcome as a capability.

A task is a commercially meaningful action that the customer performs on an
identifiable object by using that economic product. State it as an action plus
object, not as a benefit, desired result, or performance improvement.

A task is not the firm's internal operation, a generic benefit, a business
outcome, or an interface click.

Merge only entries that describe the same action in different wording, formats,
channels, or interface steps. Keep tasks separate when the customer produces,
manages, analyzes, designs, verifies, or delivers a materially different object
or result, even if the actions occur in the same workflow. Do not produce a
task catalogue.

Every task names one or more capabilities of its own economic product.

## Evidence

Every economic product, capability, and task must cite one to three
`passage_refs` that directly support it. Return only labels such as `P007`.
Do not write quotes, offsets, hashes, page numbers, explanations, scores,
tiers, revenue estimates, or reasoning. The pipeline resolves the selected
passages separately.

## Output

Return exactly one JSON object and nothing else. Use identifiers `EP1`, `EP2`,
... for economic products, `C1`, `C2`, ... for capabilities, and `T1`, `T2`,
... for tasks. `capability_ids` may name only capabilities in the same economic
product.

```json
{
  "economic_products": [
    {
      "id": "EP1",
      "name": "Example commercial platform",
      "source_product_ids": ["P2", "P4"],
      "passage_refs": ["P007"],
      "capabilities": [
        {
          "id": "C1",
          "text": "unify customer interaction records",
          "passage_refs": ["P007"]
        }
      ],
      "tasks": [
        {
          "id": "T1",
          "capability_ids": ["C1"],
          "text": "manage customer relationships using complete interaction records",
          "passage_refs": ["P007"]
        }
      ]
    }
  ],
  "not_selected_product_ids": ["P1", "P3"]
}
```
