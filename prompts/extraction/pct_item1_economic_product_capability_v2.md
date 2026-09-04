# pct_item1_economic_product_capability_v2

## Input

You receive two things for one firm--filing observation:

1. the complete verified Item 1 packet, whose passages are labelled `P001`,
   `P002`, and so on; and
2. a **discovery candidate map**, containing product-family names and
   product IDs.

The candidate map is high-recall working material, not a finding. Read the
whole Item 1 packet before deciding. Use Item 1 as the evidence for every
decision.

## Task

Build a concise economic-product and capability map for the firm's
**economically meaningful customer products**. Do not return tasks in this
stage.

An economic product is a separately identifiable offering that a customer can
buy, license, subscribe to, deploy, or use as part of the firm's commercial
offering. Do not invent a product catalogue beyond the supplied discovery
candidates.

A product-family name is parent context, not a source product and not an
economic product by itself. Every selected economic product must list one or
more underlying product IDs (`P#`) in `source_product_ids`. Never return an
economic product with an empty `source_product_ids` array.

Treat each discovery product ID as a separate economic product by default.
Do not combine candidates merely because they belong to the same family,
suite, cloud, subscription, or Item 1 passage. A distinct named application or
platform remains separate when Item 1 supports it as a separately identifiable
customer offering.

Combine candidates only where Item 1 expressly establishes that they are the
same commercial offering, such as a renamed product, plan, edition, feature,
or delivery variant. When you combine candidates, do not also return any of
those same candidates as separate economic products.

For every discovery product ID, do exactly one of the following:

- include it in exactly one `economic_product` through `source_product_ids`; or
- put it in `not_selected_product_ids`.

Do not create a new source-product ID and do not silently drop a candidate.
Select a product only where Item 1 supports its commercial distinctness. Do not
select features, plans, editions, add-ons, delivery channels, internal
technology, acquisitions, strategy, or generic benefits as economic products.

For each selected economic product:

1. give a concise commercial `name`; and
2. state concrete customer-available **capabilities** as verb phrases.

A capability is a discrete function the customer can use in the product. It is
what the product enables the customer to do. Do not state a product name,
generic benefit, strategy, or business outcome as a capability.

## Evidence

Every economic product and capability must cite one to three `passage_refs`
that directly support it. Return only labels such as `P007`. Do not write
quotes, offsets, hashes, page numbers, explanations, scores, tiers, revenue
estimates, or reasoning.

## Output

Return exactly one JSON object and nothing else.

```json
{
  "economic_products": [
    {
      "id": "EP1",
      "name": "Example commercial platform",
      "source_product_ids": ["P2"],
      "passage_refs": ["P007"],
      "capabilities": [
        {
          "id": "C1",
          "text": "unify customer interaction records",
          "passage_refs": ["P007"]
        }
      ]
    }
  ],
  "not_selected_product_ids": ["P1", "P3"]
}
```
