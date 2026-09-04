# pct_item1_economic_product_capability_v3

## Input

You receive:

1. the complete verified Item 1 packet for one firm; and
2. a discovery map containing product families and product candidates `P1`,
   `P2`, and so on.

Read Item 1 before deciding. The discovery map is only a candidate list.
Item 1 is the evidence.

## Task

Produce the firm's customer-facing economic products and their capabilities.

A product family is parent context. Do not return it as an economic product
merely because it organizes product candidates.

Treat each discovery product candidate as one economic product by default.
Keep a candidate only if Item 1 supports it as a separately identifiable
offering a customer can buy, license, subscribe to, deploy, or use.

Keep separately named applications or platforms separate. Do not combine them
merely because they belong to the same suite, cloud, subscription, or family.

Combine candidates only when Item 1 clearly establishes that they are the same
commercial product, such as a renamed product, edition, feature, or delivery
variant. A plan, bundle, or package that merely contains other products is not
a separate economic product.

Every discovery product ID must appear exactly once: either in one returned
economic product or in `not_selected_product_ids`.

For each selected product, provide a concise name and its concrete
customer-available capabilities as verb phrases. A capability is what a
customer can do with that product, not a product name, benefit, strategy, or
task.

## Evidence and output

Every product and capability must cite one to three Item 1 `passage_refs`.
Return JSON only. Do not write quotes, explanations, scores, revenue, or tasks.

```json
{
  "economic_products": [
    {
      "id": "EP1",
      "name": "Example product",
      "source_product_ids": ["P2"],
      "passage_refs": ["P007"],
      "capabilities": [
        {
          "id": "C1",
          "text": "manage customer records",
          "passage_refs": ["P007"]
        }
      ]
    }
  ],
  "not_selected_product_ids": ["P1"]
}
```
