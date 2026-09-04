# pct_item1_capability_extraction_v1

## Input

You receive two things for one firm--filing observation:

1. the complete verified Item 1 packet, whose passages are labelled `P001`,
   `P002`, and so on; and
2. a fixed economic-product map.

Read the whole Item 1 packet before deciding. Use Item 1 as the evidence for
every capability. The supplied economic products are fixed: do not add, remove,
merge, split, rename, or otherwise re-decide them.

## Task

For every supplied economic product, state its concrete customer-available
capabilities as concise verb phrases.

A capability is a discrete function a customer can use in that product. It is
what the product enables the customer to do. Do not state a product name,
generic benefit, strategy, business outcome, internal firm activity, delivery
channel, or task as a capability.

Every supplied economic product must appear exactly once in the output. Do not
assume a target number of capabilities.

## Evidence

Every capability must cite one to three `passage_refs` that directly support
it. Return only labels such as `P007`. Do not write quotes, offsets, hashes,
page numbers, explanations, scores, tiers, revenue estimates, tasks, or
reasoning.

## Output

Return exactly one JSON object and nothing else. Use capability identifiers
`C1`, `C2`, ... separately within each economic product.

```json
{
  "economic_product_capabilities": [
    {
      "economic_product_id": "EP1",
      "capabilities": [
        {
          "id": "C1",
          "text": "unify customer interaction records",
          "passage_refs": ["P007"]
        }
      ]
    }
  ]
}
```
