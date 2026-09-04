# pct_item1_economic_pct_v1

**Status: development smoke draft.** This prompt may be used only with a
saved product-structure discovery output for the bounded five-firm smoke. It
does not authorize a production run, scoring, or a universe decision.

## Input

You receive two things for one firm--filing observation:

1. a **discovery candidate map**, containing local product-family IDs and
   product IDs; and
2. the complete verified Item 1 packet, whose passages are labelled `P001`,
   `P002`, and so on.

The candidate map is high-recall working material, not a finding. Read the
whole Item 1 packet before deciding. Use Item 1 as the evidence for every
decision.

## Task

Build a concise product--capability--task-family (PCT) map for the firm's
**economically meaningful customer products**.

An economic product is a separately identifiable offering that a customer can
buy, license, subscribe to, deploy, or use as part of the firm's commercial
offering. It may combine two or more discovery candidates when they are names,
modules, editions, or delivery variants of one customer product. Do not create
a detailed product catalogue.

For every discovery product ID, do exactly one of the following:

- include it in exactly one `economic_product` through `source_product_ids`; or
- put it in `not_selected_product_ids`.

Do not create a new source-product ID and do not silently drop a candidate.
Select a product only where Item 1 supports its commercial distinctness. Do not
select features, plans, editions, add-ons, delivery channels, internal
technology, acquisitions, strategy, or generic benefits as economic products.

For each selected economic product:

1. give a concise commercial `name`;
2. state the product's concrete customer-facing **capabilities** as verb
   phrases; and
3. state durable **task families** as customer outcomes or coherent workflows.

A capability is what the product does. A task family is the customer result it
enables. Merge interface steps, formats, near-synonyms, and adjacent actions
when they serve one customer outcome. Do not produce a task catalogue.

## Evidence

Every economic product, capability, and task family must cite one to three
`passage_refs` that directly support it. Return only labels such as `P007`.
Do not write quotes, offsets, hashes, page numbers, explanations, scores,
tiers, revenue estimates, or reasoning. The pipeline resolves the selected
passages separately.

## Output

Return exactly one JSON object and nothing else. Use identifiers `EP1`, `EP2`,
... for economic products, `C1`, `C2`, ... for capabilities, and `TF1`, `TF2`,
... for task families. `capability_ids` may name only capabilities in the same
economic product.

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
      "task_families": [
        {
          "id": "TF1",
          "capability_ids": ["C1"],
          "text": "manage customer relationships using complete interaction records",
          "customer_outcome": "maintain and act on a complete customer view",
          "passage_refs": ["P007"]
        }
      ]
    }
  ],
  "not_selected_product_ids": ["P1", "P3"]
}
```
