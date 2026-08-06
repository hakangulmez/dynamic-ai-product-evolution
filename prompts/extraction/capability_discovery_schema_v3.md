# Capability Discovery -- High Recall -- Schema v3

## Governing spec

`SPEC-009`

## System instruction

For each validated product below, extract the concrete customer-facing functions
it provides. A capability describes what the product *enables a customer to do*,
not the customer's broader objective and not the underlying technical stack.

Good capabilities:

- generate images from text;
- answer document questions with citations;
- summarize and route support incidents;
- execute an approved user-provisioning workflow.

Reject:

- "AI-powered innovation";
- "improve productivity";
- internal model training with no customer-facing function;
- pricing and packaging alone.

AI terms receive no special status. Translate them into the concrete action the
evidence describes. Do not score adoption, replicability, defensibility, quality
or business success.

Every capability belongs to exactly one of the validated products listed below.
If the evidence describes a function but does not tie it to one of those
products, omit it rather than guessing a parent.

## Input template

```text
COMPANY: {{company_name}}
OBSERVATION_CUTOFF: {{cutoff}}

VALIDATED PRODUCTS:
{{validated_products}}

SOURCE PASSAGES:
{{passages_with_ids}}
```

Each validated product begins with a header of the form:

```text
[ref: A01] [product_family: ...] [entity_type: ...]
```

Each passage begins with a header of the form:

```text
[ref: P1] [passage_id: ...] [source_id: ...] [publication_date: ...]
```

Cite products and passages by their `ref` labels only. Do not copy
`passage_id`, `source_id`, or any product identifier into your output; they
appear in the headers for human readers and are resolved downstream.

## Required output

Return a JSON array. Each element is one capability candidate with exactly these
fields -- no other field, no wrapper object, no markdown fencing, no commentary.

Required on every candidate:

- `parent_ref`: the label of the one validated product this capability belongs
  to, copied exactly as it appears in that product's header -- the letter `A`
  followed by at least two digits, for example `"A01"`.
- `capability`: a short phrase naming the concrete function, in the form
  "verb + object" -- for example `"summarize support tickets"`. Do not repeat
  the product name inside it.
- `availability_status`: exactly one status **label** from the table below, for
  example `"S5"`. Never the status word itself.
- `confidence`: one of `high`, `medium`, `low`, `unknown`.
- `evidence`: array, at least one entry, each entry exactly
  `{"ref": ..., "quote": ...}`.

Include only when the evidence supports it, otherwise omit (never invent a
value):

- `input_types`: array of strings -- what the customer supplies, for example
  `["text", "support ticket"]`.
- `output_types`: array of strings -- what the capability returns, for example
  `["summary", "routing decision"]`.
- `ambiguity`: a short note when the scope or the parent attribution is
  uncertain.

Do **not** emit an identifier of any kind. `capability_observation_id`,
`product_observation_id` and `normalized_capability` are derived downstream from
your `parent_ref` and `capability`; a candidate carrying any of them is
rejected.

### `evidence` -- how to cite

Each evidence entry has exactly two fields and no others:

- `ref`: the label of one passage shown above, copied exactly as it appears --
  the letter `P` followed by that passage's position number, written with no
  fixed width and no leading zeros: `"P1"`, `"P25"`, `"P100"`.
- `quote`: text quoted verbatim from that same passage. Quote **1 to 3
  sentences** -- enough to support the capability you are claiming, not the
  entire passage. When a single clause carries the claim, quote that clause.

Binding rules:

- Use only `ref` labels that appear in the SOURCE PASSAGES above. Do not invent
  a label, do not guess a number, and do not cite a passage you were not shown.
- The `quote` must come from the passage that `ref` names.
- Quote the part that supports the claim, not the passage it sits in. If a
  passage describes five features and you are claiming one of them, quote the
  sentence naming that one. A passage may be long; a quote should not be.
- Copy the words exactly as they appear, without joining text across a gap. If
  the words you need are separated by other text, quote the shorter run that is
  contiguous, or cite a different passage.
- Never emit `source_id` or `passage_id`. An entry carrying either is rejected.

### `parent_ref` -- how to attribute

- Use only `A` labels that appear in the VALIDATED PRODUCTS block above.
- One capability, one parent. If a function is genuinely offered by two
  products, emit it once per product, each with its own evidence.
- If the evidence does not tie the function to a listed product, omit the
  capability entirely. An unattributable capability is not a finding.

### `availability_status` -- closed vocabulary

Do not write a status word. Emit the short **label** for the status you mean:

```text
  S1  =  announced
  S2  =  broadly_deployed_or_default
  S3  =  deprecated
  S4  =  discontinued
  S5  =  general_availability
  S6  =  private_beta
  S7  =  public_beta
  S8  =  unknown
```

The eight statuses these labels stand for are the closed vocabulary below. Read
them to decide which one applies; emit only the label. A status word written out
in full is rejected, and there is no ninth status -- never `planned`.

```
active_status_values           : broadly_deployed_or_default, general_availability,
                                  private_beta, public_beta
roadmap_status_values          : announced
non_active_known_status_values : deprecated, discontinued
unknown_status_values          : unknown
```

This status describes **the capability**, judged from its own evidence -- not
the availability of its parent product. If the evidence does not establish which
of the seven other tokens applies, use the label for `unknown`. Do not guess.

## Silent final check

- Every capability is customer-facing and describes a concrete action.
- Every `parent_ref` is a label that appears in the VALIDATED PRODUCTS block.
- Every `ref` is a label that appears in the SOURCE PASSAGES block.
- Every `quote` is 1 to 3 sentences, contiguous, and copied exactly.
- No entry carries `source_id`, `passage_id`, or any identifier field.
- `availability_status` is a label from the table (`S1`-`S8`), not a word.
- Uncertain attribution remains flagged via `ambiguity`, not resolved.
