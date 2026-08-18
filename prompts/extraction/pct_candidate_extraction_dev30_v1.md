# pct_candidate_extraction_dev30_v1

**Status: development draft.** Not released, not qualified, not authorized
for any model call. This document is fixture-first prompt text only; running
it, scoring it, or building a gold set from it are separate, later
decisions. See `docs/DECISION_LOG.md` (ADR-100).

**Contract this call must satisfy:** `pct_dev30_v0_model_output@0.2.0`.

## What you are given

One verified Item 1 span from a single company's annual filing, plus that
span's `legacy_source_id`. Both are supplied to you in full below this
prompt. You do not select, fetch, or infer either one.

## What you return

Exactly one JSON object and nothing else: no prose before or after it, no
markdown formatting, no code fence, no explanation of your reasoning. The
object must be valid JSON on its own and must conform to
`pct_dev30_v0_model_output@0.2.0`:

```
{
  "contract": "pct_dev30_v0_model_output@0.2.0",
  "schema_version": "0.2.0",
  "legacy_source_id": "<copied exactly from what you were given>",
  "candidates": [ ... ],
  "excluded_mentions": [ ... ],
  "zero_candidate_reason": null
}
```

Copy `legacy_source_id` from the supplied value exactly, character for
character. Never invent, guess, reformat, or partially transcribe it. If it
is missing from what you were given, treat that as an input error and still
copy nothing you were not given — do not construct a substitute.

## What you extract

Every customer-facing product, capability, and task that the Item 1 text
actually supports with evidence — not only ones described with AI-related
language. A company's ordinary, non-AI offerings are just as in scope as
anything described as AI-powered, an agent, or a copilot. Read the whole
span; do not stop after the first few paragraphs. A filing may describe one
product or several; extract every one the text supports, and do not assume
the count in advance. There is no target number of candidates — extract
exactly what the evidence supports, no more and no fewer.

## Local identifiers

Assign every candidate a local ID scoped to this one call only: products
`P1`, `P2`, ...; capabilities `C1`, `C2`, ...; tasks `T1`, `T2`, ..., each
counting up from 1 within its own kind. List `candidates` with every product
first, then every capability, then every task; within each kind, order
candidates by where their primary evidence first appears in the span. A
capability references its product by that product's local ID. A task
references exactly one product and zero or more capabilities, by their
local IDs — the same capability may support more than one task when the
text genuinely supports that link for each.

## Definitions

**Product** — an identifiable offering a customer can name, buy, or adopt.
Give it a `product_family` only when the text explicitly places it under a
named family; otherwise `product_family` is `null`. Do not infer a family
from a shared prefix or marketing category alone.

**Capability** — a concrete function the product performs for the customer.
Not: generic marketing language, company strategy, a single interface click
or menu item, or an internal technology the customer never directly uses
(internal data infrastructure, internal tooling, R&D method). A capability
must be something the product visibly *does*, from the customer's side. As a
contrast, "the product automatically flags anomalies for the user to
review" describes a capability; "we invested in expanding our internal data
science team" does not — the second sentence is about the company's own
operations, not something a customer experiences through the product.

**Task** — an economically distinct job the customer accomplishes, in
`verb + object + intended outcome` form (e.g. "reconcile transactions to
close the books faster", not just "reconciliation"). Every task carries a
`customer_need`: the underlying need the task serves, stated independently
of any specific product, concisely, and grounded in the same evidence. Every
task links to exactly one product and to zero or more capabilities that
support it.

**Granularity.** Do not create separate tasks for synonyms, delivery
channels, file formats, or individual UI steps within one job, and do not
split adjacent actions into separate tasks unless the customer's outcome or
deliverable is materially different. One real job is one task, however many
ways the text phrases or delivers it.

## Evidence

Every candidate, and every excluded mention, carries exactly one
`evidence_quote`: an exact, contiguous, verbatim substring of the Item 1
text you were given — not a paraphrase, not a merged pair of sentences with
material cut from the middle. Quote enough surrounding context that the
quote is specific to the one occurrence it is evidence for; a bare product
or feature name that could describe more than one place in the text is not
sufficient on its own. Do not report a character offset or position of any
kind — only the quoted text itself.

## Availability

Every product, capability, and task candidate carries an explicit
`availability_status`, using exactly one of these eight tokens: `announced`,
`private_beta`, `public_beta`, `general_availability`,
`broadly_deployed_or_default`, `deprecated`, `discontinued`, `unknown`.
Never default to `general_availability` from present-tense wording alone.
Roadmap or beta language is still a full candidate — record it as
`announced`, `private_beta`, or `public_beta`, whichever the text supports;
do not exclude it and do not upgrade it to general availability without
direct textual support for present, current deployment.

## Excluded mentions

`excluded_mentions` is optional and does not need to cover every passage you
considered and set aside — only the mentions worth recording. Route a
mention here, with exactly one `evidence_quote` and exactly one `reason`
from this closed list, when it does not qualify as a candidate:

- `internal_use` — the activity benefits the company's own operations, not
  an external customer.
- `vague_ai_marketing` — AI, agent, copilot, or similar language appears
  without a concrete customer-facing action attached to it.
- `not_customer_facing` — the passage describes the business generally
  (strategy, partnerships, hiring, positioning) rather than an offering.
- `insufficient_specificity` — a bare label ("AI", "platform",
  "innovation") with no distinct offering established.

## What you never output

No score, confidence, or uncertainty value of any kind on any candidate. No
task role, no screening or classification decision, no replicability
judgment, no defensibility judgment, no deployment-scale estimate, no
AI-adoption metric, no financial figure or claim, and no comparison to any
period after the one this filing covers. Those are separate, later analyses
and do not belong in this call's output.

## Zero candidates

If nothing in the span supports any candidate, `candidates` is an empty
array and `zero_candidate_reason` is exactly one of
`no_product_capability_or_task_evidence` (nothing was found at all) or
`all_mentions_excluded` (everything found was routed to
`excluded_mentions`). When `candidates` is non-empty, `zero_candidate_reason`
is `null`.

## Minimal shape (illustrative only, not a real filing)

```json
{
  "contract": "pct_dev30_v0_model_output@0.2.0",
  "schema_version": "0.2.0",
  "legacy_source_id": "legacy-item1:dev30-v0:<64-hex>",
  "candidates": [
    {"local_id": "P1", "kind": "product", "product_family": null,
     "product_name": "Northwind Insight", "availability_status": "general_availability",
     "evidence_quote": "our flagship offering, Northwind Insight"},
    {"local_id": "C1", "kind": "capability", "product_local_id": "P1",
     "capability_text": "automated variance reporting",
     "availability_status": "public_beta",
     "evidence_quote": "Northwind Insight now generates variance reports automatically"},
    {"local_id": "T1", "kind": "task", "product_local_id": "P1", "capability_local_ids": ["C1"],
     "task_text": "generate variance reports to close the books faster",
     "customer_need": "close accounting periods with less manual reconciliation work",
     "availability_status": "public_beta",
     "evidence_quote": "finance teams use this to close their books days faster"}
  ],
  "excluded_mentions": [
    {"reason": "vague_ai_marketing", "evidence_quote": "powered by our next-generation AI platform"}
  ],
  "zero_candidate_reason": null
}
```
