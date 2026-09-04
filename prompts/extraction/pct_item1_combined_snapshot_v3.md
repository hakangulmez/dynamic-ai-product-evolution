# pct_item1_combined_snapshot_v3

**Status: development smoke draft.** It may be used only for the bounded, archived five-firm smoke route. It is not qualified for a production run, a scoring decision, or an inference about the full universe.

## Input

You receive the complete verified Item 1 packet for one firm--filing observation. It states the firm, observation date, source identifier, and passages labelled `P001`, `P002`, and so on. Read the whole packet before deciding what to return.

## Task

Build one conservative snapshot of the firm's customer value structure:

1. **Products** are identifiable customer offerings that customers can buy, license, subscribe to, deploy, or use.
2. **Capabilities** are concrete functions a product performs for customers.
3. **Task families** are enduring customer outcomes or coherent workflows that one or more capabilities enable. They are not individual interface steps.

Extract only what the Item 1 text supports. A filing may support zero, one, or several products. Do not assume a target count.

## Product and family boundary

Use `product_family` only as optional commercial context. Set it when Item 1 explicitly names a suite, cloud, solution family, or other commercial grouping containing the product; otherwise set it to `null`. A family is not a separate product record.

Record a product only where the packet establishes a distinct customer-facing offering. Use one consistent, non-overlapping commercial level. Do not output both an umbrella offering and its included applications, modules, plans, editions, or bundles as separate products. A plan, edition, add-on, delivery channel, internal system, strategy, or named technology is not itself a product. Separate products only where Item 1 establishes that customers obtain them independently as distinct offerings.

## Capability and task-family boundary

A capability states what the product does for the customer, as a concise verb phrase. It is not a generic benefit, company strategy, internal method, or UI click.

A task family states the customer result: `verb + object + intended outcome`. It must be durable enough to compare across years. Merge interface steps, delivery channels, formats, near-synonyms, and adjacent feature actions when they serve one customer outcome. Split task families only when the customer's outcome or deliverable is materially different.

Each task family belongs to exactly one product and may link to zero or more of that product's capabilities. State `customer_outcome` independently of the firm's product name.

## Evidence

Every product, capability, and task family must cite one to three `passage_refs` that directly support that entry. Return only labels such as `P007`; do not write quotations, offsets, hashes, page numbers, or reasoning. The pipeline resolves and verifies the evidence text separately. Before returning, check that no entry has more than three `passage_refs`.

For products only, set `availability_status` to exactly one of:

`announced`, `private_beta`, `public_beta`, `general_availability`, `broadly_deployed_or_default`, `deprecated`, `discontinued`, or `unknown`.

Use `unknown` where Item 1 does not establish availability. Do not promote a future plan or an acquisition into a current offering without direct support.

## Output

Return exactly one JSON object and nothing else. Use local identifiers only: products `P1`, `P2`, ...; capabilities `C1`, `C2`, ...; task families `TF1`, `TF2`, ... . List products first, capabilities second, and task families third. References between entries must use these local identifiers.

```json
{
  "products": [
    {
      "id": "P1",
      "name": "Example CRM",
      "product_family": "Example customer platform",
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
  "task_families": [
    {
      "id": "TF1",
      "product_id": "P1",
      "capability_ids": ["C1"],
      "text": "manage customer relationships using complete interaction records",
      "customer_outcome": "maintain and act on a complete view of customer relationships",
      "passage_refs": ["P007"]
    }
  ]
}
```

Do not output detailed sub-tasks, scores, tiers, confidence, revenue estimates, materiality, replicability, defensibility, AI-transition judgements, or reasoning. Those are separate later stages.
