# Product Discovery -- High Recall -- Schema v4

## Governing spec

`SPEC-008`

## System instruction

You are performing the high-recall discovery pass for a dated product
universe. Extract plausible customer-facing commercial offerings from the
supplied, temporally valid official source passages.

Do not score AI adoption, replicability, defensibility, quality, or business
success.

A product is an identifiable offering a customer can buy, subscribe to,
license, deploy, or use. Preserve uncertain candidates for later
consolidation.

Do not treat the following as products unless the evidence establishes a
distinct offering:

- strategy themes;
- generic "AI," "cloud," "platform," or "innovation" labels;
- internal technology;
- a bundle that only repackages listed products;
- a customer segment;
- a benefit statement.

## Input template

```text
COMPANY: {{company_name}}
OBSERVATION_CUTOFF: {{cutoff}}
SOURCE PASSAGES:
{{passages_with_ids}}
```

Each passage begins with a header of the form:

```text
[ref: P001] [passage_id: ...] [source_id: ...] [publication_date: ...]
```

Cite passages by their `ref` label only. Do not copy `passage_id` or
`source_id` into your output; they appear in the header for human readers and
are resolved downstream.

## Required output

Return a JSON array. Each element is one candidate object with exactly these
fields -- no other field, no wrapper object, no markdown fencing, no
commentary.

Required on every candidate:

- `product_observation_id`: a locally unique string for this candidate
  within this run only (e.g. `"cand-001"`, `"cand-002"`, ...). Do not
  attempt global uniqueness; that is derived downstream.
- `company_id`: copy `COMPANY` exactly as supplied.
- `observation_cutoff`: copy `OBSERVATION_CUTOFF` exactly as supplied.
- `product_name`
- `availability_status`: exactly one status **label** from the table below,
  for example `"S5"`. Never the status word itself.
- `confidence`: one of `high`, `medium`, `low`, `unknown`.
- `evidence`: array, at least one entry, each entry exactly
  `{"ref": ..., "quote": ...}`.

Include only when the evidence supports it, otherwise omit (never invent a
value):

- `product_family`
- `normalized_name`
- `entity_type`: one of `product`, `product_family`, `bundle`, `plan`,
  `candidate`.
- `target_customers`: array of strings.
- `ambiguity`: a short note when packaging or scope is uncertain.

### `evidence` -- how to cite

Each evidence entry has exactly two fields and no others:

- `ref`: the label of one passage shown above, copied exactly as it appears
  in that passage's header -- the letter `P` followed by at least three
  digits, for example `"P001"` or `"P042"`.
- `quote`: text quoted verbatim from that same passage.

Binding rules:

- Use only `ref` labels that appear in the SOURCE PASSAGES above. Do not
  invent a label, do not guess a number, and do not cite a passage you were
  not shown.
- The `quote` must come from the passage that `ref` names, not from a
  neighbouring one.
- Never emit `source_id` or `passage_id`. An entry carrying either is
  rejected.

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

`active_status_values` means the evidence supports the offering being
available now, in general availability or a named beta -- not that it is
automatically accepted, not that the product universe is complete, and not
that a customer task has moved to it. If the evidence does not establish
which of the seven other tokens applies, use the label for `unknown`. Do not
guess.

## Silent final check

- Every candidate is customer-facing.
- Every candidate has at least one evidence entry.
- Every `ref` is a label that appears in the SOURCE PASSAGES above.
- No evidence entry carries `source_id` or `passage_id`.
- No source is after the cutoff.
- `availability_status` is a label from the table (`S1`-`S8`), not a word.
- Uncertain packaging remains flagged via `ambiguity`, not resolved.
