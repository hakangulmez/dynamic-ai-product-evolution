# High-recall software-universe screen — v5.1 (evidence binding)

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

## Evidence identity and exact-copy binding

Each displayed passage has a header in exactly this form:

```text
[passage_ref=P001 section=<SECTION>]
```

`passage_ref` is the only source-location field you return. There is exactly
one filing for this task; do not return a `source_id`, a document identifier,
or any hidden hash. Return one displayed reference exactly as written, such as
`P001`, `P002`, or `P017`. Never invent, alter, pad, truncate, or substitute a
reference. An empty evidence array is always better than an unverifiable
reference.

Build every evidence object in this order, and in no other:

1. Decide the claim you want to support.
2. Find the passage body that already contains a span of characters proving
   it. If no passage body contains such a span, stop here and record the gap
   in `missing_evidence`; do not continue to step 3.
3. Select one contiguous run of characters inside that one body. Begin at a
   character you can see and end at a character you can see. Do not extend the
   span past the end of that body, and do not join it to text elsewhere.
4. Copy that run character for character into `quote`.
5. Read `passage_ref` off the header of the body you copied from in step 3 and
   write that value. The reference is a consequence of where the span was
   found; it is never chosen before the span.

Choosing a reference first and then writing text to fit it produces evidence
that fails verification even when the underlying claim is correct.

`quote` is a copy operation, not a writing task. Transcribe a contiguous span
of characters that already appears in the body beneath the cited header. Do
not improve, summarize, normalize, or compose it. Your quote will be checked
by an exact substring search in that cited passage: one changed capital letter,
one shortened entity name, one dropped leading word, or text joined from two
places makes the evidence unusable.

- Copy `passage_ref` exactly and only from `passage_ref=` in one displayed
  header. Do not copy brackets, field names, or the section label.
- Preserve every word, capital letter, punctuation mark, and entity name in
  `quote` exactly as it appears. If a quote starts mid-sentence, retain its
  original lower-case letter rather than re-capitalising it.
- Never shorten or abbreviate a company, division, subsidiary, or regulator
  name, even if an abbreviation appears elsewhere in the filing.
- Never drop opening words to make a sentence tidier. Never prepend or append
  nearby text for context. Put interpretation only in `supported_claim`.
- Never combine text about separate entities, subsidiaries, sentences, or
  passages. If a claim needs two spans, return two separate evidence objects.
- Prefer the shortest span that directly supports the claim, usually one
  sentence. This is a preference, not a maximum length rule.
- Before final JSON, independently verify every `(passage_ref, quote)` pair:
  locate the displayed header and confirm the quote occurs exactly in that
  passage body. If it does not, drop that evidence object and state the gap in
  `missing_evidence`.

If a contiguous span cannot be copied from one body, the evidence object is
omitted rather than approximated. An empty evidence array is a correct
answer when no exact quote can be copied.

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
      "passage_ref": "P001",
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
