# pct_item1_economic_product_capability_v1

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

Build a concise economic-product and capability map for the firm's
**economically meaningful customer products**.

An economic product is a separately identifiable offering that a customer can
buy, license, subscribe to, deploy, or use as part of the firm's commercial
offering. It may combine two or more discovery product candidates when they
are names, modules, editions, or delivery variants of one customer product.
Do not create a detailed product catalogue.

For every discovery product ID, do exactly one of the following:

- include it in exactly one `economic_product` through `source_product_ids`; or
- put it in `not_selected_product_ids`.

Do not create a new source-product ID and do not silently drop a candidate.
`source_product_ids` contains only discovery product labels such as `P1`, never
discovery family labels such as `F1`.

You may use a discovery product-family name to name an `economic_product` when
it combines its underlying product candidates, but list only those `P#` product
IDs in `source_product_ids`.

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
      "source_product_ids": ["P2", "P4"],
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
