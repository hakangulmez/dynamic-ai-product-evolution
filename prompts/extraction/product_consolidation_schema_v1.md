# Product Consolidation -- High Precision -- Schema v1

## Governing spec

`SPEC-008`

## System instruction

You are consolidating high-recall product candidates into a precise dated
product universe. Use only the candidates and the source passages supplied
below. Add nothing from outside them.

For each candidate you must choose exactly one action:

- **retain** as a distinct product;
- **merge** as an alias or delivery variant of another candidate;
- **place** as a member of a product family named by another candidate;
- **classify** as a bundle or a plan;
- **exclude** as strategy, capability, internal technology, or unsupported
  roadmap;
- **unresolved** when the evidence does not settle the question.

A bundle becomes a distinct product only when it creates a customer-facing
cross-product workflow or commercial experience that the constituent products
do not represent on their own. A label that merely groups other products is a
family, not a bundle.

`unresolved` is a real answer, not a failure. Use it when the evidence supports
more than one action and does not choose between them. Do not guess an action
to avoid leaving a case open.

Do not use future measurement concepts. Do not score adoption, replicability,
defensibility, quality or business success. AI terms receive no special status.

## Input template

```text
COMPANY: {{company_name}}
OBSERVATION_CUTOFF: {{cutoff}}

PRODUCT CANDIDATES:
{{product_candidates}}

SOURCE PASSAGES:
{{passages_with_ids}}
```

Each candidate begins with a header of the form:

```text
[ref: D1] [entity_type: ...] [availability_status: ...]
```

followed by its product name on the next line.

Each passage begins with a header of the form:

```text
[ref: P1] [passage_id: ...] [source_id: ...] [publication_date: ...]
```

Cite candidates and passages by their `ref` labels only. Do not copy
`passage_id`, `source_id`, `product_observation_id` or `normalized_name` into
your output; they appear in the headers for human readers and are resolved
downstream.

## Required output

Return a JSON array with **exactly one element per candidate shown above**, in
any order -- no other field, no wrapper object, no markdown fencing, no
commentary. Every candidate gets exactly one decision; a candidate you do not
mention is an error, and a candidate mentioned twice is an error.

Required on every element:

- `ref`: the candidate's label, copied exactly -- the letter `D` followed by
  its position number, written with no fixed width and no leading zeros:
  `"D1"`, `"D12"`.
- `action`: exactly one of `retain`, `merge_alias`, `place_family`,
  `classify_bundle`, `exclude`, `unresolved`.
- `reason`: one or two sentences saying why, in your own words.
- `evidence`: array, at least one entry, each entry exactly
  `{"ref": ..., "quote": ...}`.

Required only for the action named, and forbidden on every other action:

- `merge_alias` -> `canonical_ref`: the `D` label of the candidate this one is
  an alias or delivery variant **of**. Must differ from `ref`.
- `place_family` -> `family_ref`: the `D` label of the candidate that names the
  family this one belongs to. Must differ from `ref`.
- `classify_bundle` -> `bundle_kind`: `bundle` or `plan`; and
  `constituent_refs`: array of the `D` labels the bundle is composed of, each
  differing from `ref`.
- `unresolved` -> `open_question`: one sentence naming what the evidence does
  not settle.

Emit no other field. Do **not** emit `product_name`, `product_observation_id`,
`availability_status`, `entity_type`, `company_id`, `observation_cutoff` or any
identifier: the retained observation is assembled downstream from the candidate
you referenced, carried through unchanged. An element carrying any of them is
rejected.

### `evidence` -- how to cite

Each evidence entry has exactly two fields and no others:

- `ref`: the label of one passage shown above, copied exactly -- the letter `P`
  followed by that passage's position number, written with no fixed width and
  no leading zeros: `"P1"`, `"P16"`.
- `quote`: text quoted verbatim from that same passage. Quote **1 to 3
  sentences** -- the run that supports your decision, not the whole passage.

Binding rules:

- Use only `ref` labels that appear in the SOURCE PASSAGES block. Do not invent
  a label, do not guess a number, and do not cite a passage you were not shown.
- The `quote` must come from the passage that `ref` names.
- Copy the words exactly as they appear, without joining text across a gap. If
  the words you need are separated by other text, quote the shorter run that is
  contiguous, or cite a different passage.
- An exclusion needs evidence too. Quote the text that shows the candidate is
  strategy, a capability, internal technology, or an unsupported roadmap item.
- Never emit `source_id` or `passage_id`. An entry carrying either is rejected.

### `canonical_ref`, `family_ref`, `constituent_refs` -- how to link

- Use only `D` labels that appear in the PRODUCT CANDIDATES block.
- A link never points at itself.
- A link never points at a candidate you excluded. If A is an alias of B and B
  is not a product, exclude A on its own terms instead.
- Do not chain. If A is an alias of B and B is an alias of C, say so for each
  one separately and let the downstream assembler resolve the chain. Do not
  rewrite A to point at C.

## Silent final check

- Exactly one element per candidate, no candidate missing, none repeated.
- Every `action` is one of the six words.
- Every `ref`, `canonical_ref`, `family_ref` and `constituent_refs` entry is a
  `D` label shown above, and no link points at itself.
- Every evidence `ref` is a `P` label shown above.
- Every `quote` is 1 to 3 sentences, contiguous, and copied exactly.
- No element carries a name, a status, an identifier, `source_id` or
  `passage_id`.
- A case the evidence does not settle is `unresolved`, not a guess.
