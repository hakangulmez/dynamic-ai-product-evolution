# pct_item1_product_structure_v1

## Input

You receive the complete verified Item 1 packet for one firm--filing
observation. It states the firm, observation date, source identifier, and
passages labelled `P001`, `P002`, and so on. Read the whole packet before
deciding.

## Task

Map only the firm's customer-facing commercial product structure.

1. **Product families** are explicitly named commercial suites, clouds,
   platforms, or solution families that group offerings.
2. **Products** are distinct customer-facing offerings that customers can
   separately buy, license, subscribe to, deploy, or use.

A product family is not itself a product. A product may belong to one named
family or to no family.

## Boundary

Use the commercial structure Item 1 establishes. Create a product-family
record only where Item 1 explicitly names a commercial grouping.

Create a product only where Item 1 establishes it as an independently
identifiable customer offering. Do not treat a named application, module,
feature, plan, edition, add-on, delivery channel, internal technology,
acquisition, strategy, or benefit as a separate product without that support.

Return a product family only if at least one returned product names it through
`product_family_id`. A family may have one product when Item 1 establishes no
other product.

Do not use substantially the same named commercial grouping as both a product
family and a product unless Item 1 distinguishes the family from a separately
purchasable collection or offering.

Do not turn a list of names into a product catalogue merely because the names
appear together. If Item 1 names a family and lists things inside it, record
the family once. Record an individual product only when the text supports that
customers obtain or use it as a distinct offering.

If the evidence does not resolve whether something is a product or a feature of
another offering, omit it. Do not guess.

Do not assess or describe products beyond their commercial structure.
Do not extract capabilities or customer tasks.

## Evidence

Every family and product must cite one to three `passage_refs` that directly
support that entry. Return only labels such as `P007`; do not write quotations,
offsets, hashes, page numbers, or explanations. The pipeline resolves and
verifies the evidence text separately.

For products only, set `availability_status` to exactly one of:
`announced`, `private_beta`, `public_beta`, `general_availability`,
`broadly_deployed_or_default`, `deprecated`, `discontinued`, or `unknown`.

## Output

Return exactly one JSON object and nothing else. Use local identifiers only:
families `F1`, `F2`, ...; products `P1`, `P2`, ... .

```json
{
  "product_families": [
    {"id": "F1", "name": "Example customer platform", "passage_refs": ["P007"]}
  ],
  "products": [
    {
      "id": "P1",
      "name": "Example CRM",
      "product_family_id": "F1",
      "availability_status": "general_availability",
      "passage_refs": ["P007"]
    }
  ]
}
```

Use `null` for `product_family_id` only when Item 1 establishes no named family.
