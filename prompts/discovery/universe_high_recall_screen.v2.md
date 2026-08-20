# Company-Universe High-Recall Screen (v2)

## Governing spec

`SPEC-001`

## Successor note

This is the v2 successor of `universe_high_recall_screen.md` (ADR-110). The
v1 template is retained byte-identical and remains the only template of the
fixture/mock route. The screening question, the high-recall standard, the
temporal rule, the evidence-minimal input contract, the quote requirement,
and the output field set are unchanged. One thing is added: the closed
vocabulary of `candidate_customer_value_archetypes`, which v1 rendered as an
empty array without ever stating its permitted values.

## Role

You are performing the first high-recall screen of a historical SEC annual-filer frame. Your purpose is to avoid missing firms that may sell a material customer-facing functional digital product.

You are not extracting products or tasks, measuring AI, judging business quality, or making a final sample decision.

## Temporal rule

Use only the supplied baseline-dated SEC evidence. Do not use later knowledge, current company websites, later AI launches, later success or failure, or your memory of the company.

## Screening question

Does the supplied filing plausibly describe at least one material external offering in which software or a software-led digital system enables, produces, analyzes, executes, or adaptively delivers a customer outcome?

Use a deliberately high-recall standard. Preserve uncertain digital, data, transaction, platform, content, hardware, and service cases for the full classifier.

## Do not infer eligibility merely from

- “technology,” “digital,” “platform,” “cloud,” “AI,” or “software” wording;
- an internal technology stack;
- a mobile application;
- online sales;
- a customer portal;
- an advertising website;
- a software SIC code;
- a technology subsidiary that is not shown to be material.

## Candidate customer-value archetypes: a closed vocabulary

`candidate_customer_value_archetypes` is a JSON array containing zero or more
**exact** values from this closed list, and nothing else:

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

Rules for this field:

- Copy the value exactly as written above: same spelling, same underscores,
  same capitalization.
- Never invent synonyms, prose labels, descriptive phrases, or new
  categories. A value such as `Productivity/Efficiency`, `SaaS`,
  `Manufacturing`, or `Software` is invalid, and so is any lowercase or
  hyphenated variant of a listed value.
- Return `[]` when no listed archetype is directly supported by the supplied
  passages. An empty array is a valid, expected answer, and it is always
  better than a guess.
- Use `OTHER` only when the filing does support a customer-value archetype
  that plainly exists but is none of the twelve named ones. `OTHER` is not a
  substitute for `[]`.
- The array is a candidate list for the later classifier, not a decision. It
  never overrides `screen_status`.

## Input template

```text
BASELINE_CUTOFF: {{baseline_cutoff}}
COMPANY_METADATA:
{{company_metadata}}

BASELINE_SEC_PASSAGES:
{{passages_with_source_and_passage_ids}}
```

## Required output

Return JSON with:

```json
{
  "screen_status": "LIKELY_ELIGIBLE | LIKELY_INELIGIBLE | BOUNDARY_OR_UNCERTAIN",
  "plausible_customer_facing_digital_product": true,
  "candidate_customer_value_archetypes": [],
  "positive_evidence": [
    {
      "source_id": "",
      "passage_id": "",
      "quote": "",
      "supported_claim": ""
    }
  ],
  "negative_or_boundary_evidence": [],
  "missing_evidence": [],
  "confidence": "high | medium | low"
}
```

`candidate_customer_value_archetypes` holds only exact values from the closed
list above, or is empty.

Use `null` rather than guessing where evidence is insufficient.

## Silent final check

- Every positive claim has a direct quote.
- No evidence is after the cutoff.
- The decision is a screen, not final inclusion.
- Marketplace, content, transaction, hardware, and human-service cases remain boundary candidates when appropriate.
- Internal software use alone does not create an eligible product.
- Every archetype returned is an exact member of the closed list; anything else would be invalid, and `[]` is preferable to an invented label.
