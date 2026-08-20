# Company-Universe High-Recall Screen (v3)

## Governing spec

`SPEC-001`

## Successor note

This is the v3 successor of `universe_high_recall_screen.v2.md` (ADR-111).
The v1 and v2 templates are retained byte-identical; v1 remains the only
template of the fixture/mock route. Everything v2 established is unchanged:
the screening question, the high-recall standard, the temporal rule, the
evidence-minimal input contract, the quote requirement, the closed archetype
vocabulary, and the output field set. One thing is added: the evidence
identity and quote-binding rule below. The second governed canary measured
why it is needed — a response copied a passage header's `source_id` and
`passage_id` together into the single `source_id` field, cited a passage id
belonging to another passage, and quoted text that did not occur in the
passage it cited. Validation refused it, correctly and fail-closed; the
instruction, not the validator, is what changes here.

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

## Evidence identity and quote binding

Each displayed passage is introduced by one header line of exactly this form:

```text
[source_id=<SOURCE_ID> passage_id=<PASSAGE_ID> section=<SECTION>]
```

followed by that passage's body text on the lines beneath it. Every evidence
object you return carries **two distinct fields**, `source_id` and
`passage_id`, and both are copied out of **one and the same** header:

- `source_id` is exactly and only the text that follows `source_id=`, ending
  immediately before the space that precedes `passage_id=`. Nothing else
  belongs in this field.
- `passage_id` is exactly and only the text that follows `passage_id=`,
  ending immediately before the space that precedes `section=`.
- Never concatenate two header fields into one value. A `source_id`
  containing the substring `passage_id=` or `section=`, or containing a
  space, is always wrong.
- Never take `source_id` from one header and `passage_id` from a different
  header. The two values must come from the same displayed passage, the one
  your quote is drawn from.
- Never copy the surrounding brackets, the field names, or the `section`
  value into either field.

`quote` must be a **contiguous verbatim substring of that same passage's body
text** — the lines under its header — reproduced character for character. It
is never the header line, never text from a different passage, never a
paraphrase, never an ellipsis-joined excerpt, and never re-typed from memory.
Copy it directly from the displayed body.

Before you emit the final JSON, verify each `(source_id, passage_id, quote)`
triple independently: locate the one header whose `source_id=` and
`passage_id=` values match your two fields exactly, then confirm your quote
occurs verbatim in the body beneath that header. If a triple does not verify,
correct it or drop that evidence object.

If no resolving evidence exists for a claim, do not invent an identifier and
do not reconstruct a quote. Say so through the fields the contract already
provides: leave the evidence array empty, record what is absent in
`missing_evidence`, and choose the screen status the available evidence
actually supports. An empty evidence array is always better than an
unverifiable citation.

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
- Every evidence object carries a `source_id` and a `passage_id` copied separately from one same header, and a quote that occurs verbatim in that passage's body.
