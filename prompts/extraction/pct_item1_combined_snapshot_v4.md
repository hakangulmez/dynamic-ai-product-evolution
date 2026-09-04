# pct_item1_combined_snapshot_v4

**Status: development smoke draft.** It may be used only for the bounded,
archived five-firm smoke route. It is not qualified for a production run, a
scoring decision, or an inference about the full universe.

## Input

You receive the complete verified Item 1 packet for one firm--filing
observation. It states the firm, observation date, source identifier, and
passages labelled `P001`, `P002`, and so on. Read the whole packet before
deciding what to return.

## Task

Build one conservative snapshot of the firm's customer value structure:

1. **Product families** are expressly named commercial suites, clouds, or
   solution families that group products.
2. **Products** are independently identifiable customer offerings within a
   family or outside any named family.
3. **Capabilities** are concrete functions a product performs for customers.
4. **Customer tasks** are economically meaningful customer jobs enabled by a
   product's capabilities.

Extract only what the Item 1 text supports. A filing may support zero, one, or
several families or products. Do not assume a target count.

## Family and product boundary

Create a product-family record only where Item 1 explicitly names a suite,
cloud, or comparable commercial grouping. A family groups products; it is not
itself a product and never receives capabilities or tasks.

Record a product only where the packet establishes a distinct customer-facing
offering. Link it to one named family with `product_family_id`, or use `null`
when the text establishes no family. Use one consistent, non-overlapping
commercial level: if Item 1 presents a family and separately identifiable
products within it, record the family once and the products once. Do not turn
plans, editions, add-ons, delivery channels, internal systems, strategy, or a
named technology into a product. Separate products only where customers obtain
them independently as distinct offerings.

## Capability and task boundary

A capability states what one product does for the customer, as a concise verb
phrase. It is not a generic benefit, company strategy, internal method, or UI
click.

A task states the customer job as `verb + object + intended outcome`. A task is
not a UI step or a restatement of a capability. Merge adjacent steps, channels,
formats, and near-synonyms when they serve one customer job. Split tasks only
when the customer outcome or deliverable is materially different.

Each task belongs to exactly one product and may link to zero or more of that
product's capabilities. State `customer_need` independently of the product
name.

## Evidence

Every product family, product, capability, and task must cite one to three
`passage_refs` that directly support that entry. Return only labels such as
`P007`; do not write quotations, offsets, hashes, page numbers, or reasoning.
The pipeline resolves and verifies the evidence text separately. Before
returning, check that no entry has more than three `passage_refs`.

For products only, set `availability_status` to exactly one of:

`announced`, `private_beta`, `public_beta`, `general_availability`,
`broadly_deployed_or_default`, `deprecated`, `discontinued`, or `unknown`.

Use `unknown` where Item 1 does not establish availability. Do not promote a
future plan or an acquisition into a current offering without direct support.

## Output

Return exactly one JSON object and nothing else. Use local identifiers only:
families `F1`, `F2`, ...; products `P1`, `P2`, ...; capabilities `C1`, `C2`,
...; tasks `T1`, `T2`, ... . List families first, products second,
capabilities third, and tasks fourth. References between entries must use these
local identifiers.

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
  ],
  "capabilities": [
    {
      "id": "C1",
      "product_id": "P1",
      "text": "unify customer interaction records",
      "passage_refs": ["P007"]
    }
  ],
  "tasks": [
    {
      "id": "T1",
      "product_id": "P1",
      "capability_ids": ["C1"],
      "text": "manage customer relationships using complete interaction records",
      "customer_need": "maintain and act on a complete view of customer relationships",
      "passage_refs": ["P007"]
    }
  ]
}
```

Do not output scores, tiers, confidence, revenue estimates, materiality,
replicability, defensibility, AI-transition judgements, or reasoning. Those
are separate later stages.
