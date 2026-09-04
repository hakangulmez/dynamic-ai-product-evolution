# pct_item1_combined_snapshot_v2

**Status: development smoke draft.** It may be used only for the bounded,
archived five-firm smoke route. It is not qualified for a production run, a
scoring decision, or an inference about the full universe.

## Input

You receive one verified Item 1 packet from one annual filing. The packet
states the firm, observation date, source identifier, and passages labelled
`P001`, `P002`, and so on. Read the whole Item 1 packet before deciding what
to return.

## Task

Build one connected, evidence-grounded snapshot of what the firm's external
customers can obtain and do at this observation date:

1. **Products** are identifiable customer offerings: something a customer can
   buy, license, subscribe to, deploy, or use.
2. **Capabilities** are concrete functions a product performs for its
   customer.
3. **Customer tasks** are economically meaningful jobs a customer accomplishes
   with that product. Write each task as `verb + object + intended outcome`.

Extract what the Item 1 text supports. A firm may have no qualifying product,
one product, or several products. Do not assume a target count.

## Product boundary

Record a product only where the Item 1 packet establishes a distinct
customer-facing offering. A generic strategy, an internal system, a company
initiative, or a named technology without a customer offering is not a
product.

Use one consistent, non-overlapping commercial level. Prefer the highest
stable offering the customer obtains. Do not output both an umbrella offering
and its included applications, modules, plans, editions, or bundles as
separate products. Do not make a plan, edition, add-on, or delivery channel a
product by itself. Separate products only where Item 1 establishes that
customers obtain them independently as distinct offerings.

`product_family` is optional context only. Use it only when Item 1 explicitly
names a commercial grouping that contains the product. Otherwise set it to
`null`. Do not create a standalone family record, and do not infer a family
from a shared name, marketing language, or a common technical component.

## Capability boundary

Describe what the customer-facing product concretely does. Use a concise verb
phrase. Do not turn a vague benefit, a strategy statement, an internal method,
or a single user-interface click into a capability.

## Task boundary

Describe the customer's job, not a feature label. A task has a distinct
customer objective or deliverable and must be stable enough to compare over
time. Do not split one job merely because the text names several interface
steps, delivery channels, formats, or near-synonyms. Merge tasks that have the
same customer objective and deliverable, even when the packet lists several
features or workflows supporting that one job.

Every task belongs to exactly one product and may link to zero or more of that
product's capabilities. State the underlying `customer_need` independently of
the firm's product name.

## Evidence and availability

Every product, capability, and task must cite one to three `passage_refs`.
Each reference must directly support that specific entry. Return only passage
labels such as `P007`; do not write quotations, offsets, hashes, page numbers,
or explanations. The pipeline resolves and verifies evidence text separately.

For every entry, set `availability_status` to exactly one of:

`announced`, `private_beta`, `public_beta`, `general_availability`,
`broadly_deployed_or_default`, `deprecated`, `discontinued`, or `unknown`.

Use `unknown` when the packet does not establish availability. Do not promote a
future plan or an acquisition into a currently available customer offering
without direct support in the packet.

## Output

Return exactly one JSON object and nothing else. Use local identifiers only:
products `P1`, `P2`, ...; capabilities `C1`, `C2`, ...; tasks `T1`, `T2`, ... .
List products first, capabilities second, and tasks third. References between
entries must use these local identifiers. Before returning, check that no entry
has more than three `passage_refs`.

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
      "availability_status": "general_availability",
      "passage_refs": ["P007"]
    }
  ],
  "tasks": [
    {
      "id": "T1",
      "product_id": "P1",
      "capability_ids": ["C1"],
      "text": "unify customer interactions to manage the sales pipeline",
      "customer_need": "manage customer relationships using a complete interaction record",
      "availability_status": "general_availability",
      "passage_refs": ["P007"]
    }
  ]
}
```

Do not output scores, tiers, confidence, revenue estimates, materiality,
replicability, defensibility, AI-transition judgements, or reasoning. Those
are separate later stages.
