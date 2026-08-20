# High-recall software-universe screen — v4

## Governing specification

Use only the supplied baseline-dated SEC evidence. This is a high-recall
screen, not a final classifier and not a final inclusion decision. Do not use
company knowledge, present-day knowledge, a ticker, a brand name, or facts
outside the supplied passages.

## Role

Determine whether the filing contains direct evidence that this firm offered
a plausible customer-facing digital product or service at the baseline date.

Return exactly one `screen_status`:

- `LIKELY_ELIGIBLE`: direct evidence supports a customer-facing digital
  product or service.
- `LIKELY_INELIGIBLE`: direct evidence supports a primarily non-digital
  offering and no contrary evidence is present.
- `BOUNDARY_OR_UNCERTAIN`: evidence is mixed, indirect, incomplete, or the
  offering is a boundary case.

Use a deliberately high-recall standard. If a customer-facing digital offering
is plausibly supported, prefer `LIKELY_ELIGIBLE` or `BOUNDARY_OR_UNCERTAIN`
over `LIKELY_INELIGIBLE`.

## Temporal rule

Use only the supplied evidence. Every passage is baseline-bounded. Do not
infer current products, later acquisitions, later technology, or future
strategy from a filing-date observation.

## Do not infer eligibility from wording alone

Do not treat any of the following alone as proof of a customer-facing digital
product: internal software use; an IT department; patents; R&D; cloud use;
data use; AI use; websites; a mobile app mentioned without an offering;
automation used only internally; physical products with embedded software;
human services assisted by software; acquisitions; or generic statements that
the firm is "technology enabled".

## Customer-facing product test

Look for direct evidence that an external customer, user, client, consumer,
merchant, developer, or partner receives or uses a digital product, platform,
application, data/analytics product, transaction service, marketplace,
content product, or hardware-software system.

Marketplace, content, transaction, hardware, and human-service cases remain
boundary candidates when appropriate. Internal software use alone does not create an eligible product.

## Candidate customer-value archetypes

Use only exact members of this closed vocabulary. Never invent synonyms, prose labels, descriptive phrases, or new categories: `Productivity/Efficiency` is invalid. Return `[]` if no listed archetype is directly supported.

```text
FUNCTIONAL_SOFTWARE
ADAPTIVE_DIGITAL_SERVICE
DATA_ANALYTICS_PRODUCT
TRANSACTION_INFRASTRUCTURE
MARKETPLACE_COORDINATION
CONTENT_CATALOG
ATTENTION_SOCIAL_PLATFORM
INTERACTIVE_ENTERTAINMENT
HARDWARE_SOFTWARE_SYSTEM
HUMAN_MANAGED_SERVICE
ECOMMERCE_RETAIL
PHYSICAL_SERVICE_NETWORK
OTHER
```

## Evidence identity and quote binding

Each displayed passage has a header in exactly this form:

```text
[source_id=<SOURCE_ID> passage_id=P001 section=<SECTION>]
```

The `passage_id` shown to you is a short deterministic citation reference,
such as `P001`, `P002`, or `P017`. It is the only passage identifier you may
return. Never invent, alter, pad, truncate, or substitute a reference. Do not
return any hidden hash or any identifier not displayed in a header.
Do not invent an identifier. An empty evidence array is always better than an
unverifiable reference.

- Copy `source_id` exactly and only from `source_id=` in the same header.
- Copy `passage_id` exactly and only as the displayed short reference (for
  example `P017`) from that same header.
- Never concatenate header fields, copy brackets or field names, or combine a
  source from one header with a reference from another.
- `quote` must be a short, contiguous, verbatim substring of the body beneath
  that exact header. It must not include header text, an ellipsis, a paraphrase,
  or text from another passage.
- Keep each quote to one directly relevant sentence or short contiguous excerpt
  (normally no more than 280 characters). Use multiple evidence objects rather
  than one long constructed quotation.
- Before final JSON, verify each `(source_id, passage_id, quote)` triple by
  locating the exact header and checking the quote in that passage body. If it
  does not verify, correct it or drop that evidence object.

When no valid evidence remains, return an empty evidence array and explain the
gap in `missing_evidence`; never manufacture a citation.

## Input

```text
BASELINE_CUTOFF:
{{baseline_cutoff}}

COMPANY_METADATA:
{{company_metadata}}

BASELINE_SEC_PASSAGES:
{{passages_with_source_and_passage_ids}}
```

## Required output

Return JSON with exactly this field structure:

```json
{
  "screen_status": "LIKELY_ELIGIBLE | LIKELY_INELIGIBLE | BOUNDARY_OR_UNCERTAIN",
  "plausible_customer_facing_digital_product": true,
  "candidate_customer_value_archetypes": [],
  "positive_evidence": [
    {
      "source_id": "",
      "passage_id": "P001",
      "quote": "",
      "supported_claim": ""
    }
  ],
  "negative_or_boundary_evidence": [],
  "missing_evidence": [],
  "confidence": "high | medium | low"
}
```

Use `null` rather than guessing where evidence is insufficient.

## Silent final check

- Every positive claim has a direct quote.
- No evidence is after the cutoff.
- The decision is a screen, not final inclusion.
- Every archetype is an exact member of the closed list, or the list is empty.
- Every evidence object uses one displayed short passage reference and a quote
  that occurs verbatim in that passage's body.
