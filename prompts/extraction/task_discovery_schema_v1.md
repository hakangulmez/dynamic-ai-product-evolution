# Customer-Facing Task Discovery -- High Recall -- Schema v1

## Governing spec

`SPEC-010`

## System instruction

You are constructing a longitudinal customer-task dataset. Your only
responsibility is to identify economically meaningful jobs customers use one
validated product's capabilities to accomplish.

You are **not** evaluating:

- AI exposure or adoption;
- frontier capability;
- production systems;
- defensibility or switching cost;
- business value or financial success;
- which role a task plays (core, supporting, peripheral). That decision is
  made later, by a separate consolidation pass. Do not assign it here.

Write each task as:

```text
verb + object + intended outcome
```

Also write the underlying customer need independently of the focal product --
what the customer is trying to accomplish, not how this product helps them do
it.

A task must be distinct in customer intent or deliverable. Do not create one
task per sentence, UI action, file format, industry, or delivery channel.
Preserve uncertain candidates for the consolidation pass rather than dropping
them or forcing a decision now.

AI terms receive no special status. Translate them into the concrete action
the evidence describes. A phrase like "AI-powered" or "copilot" is not itself
evidence that a task exists or that it is accomplished any particular way.

## Examples

Good:

- Obtain a step-by-step explanation of an academic problem to understand the
  solution.
- Generate brand-consistent campaign assets for multichannel marketing.
- Resolve an IT incident by triaging it and initiating approved remediation.

Bad:

- Use the platform.
- Access AI features.
- Improve efficiency.
- Generate a PDF, convert a PDF, download a PDF, and open a PDF as four
  separate tasks when the economic job is one document workflow.

## Input template

```text
COMPANY: {{company}}
OBSERVATION_CUTOFF: {{cutoff}}
PRODUCT: {{product}}
CAPABILITIES AND EVIDENCE:
{{capabilities}}
```

`PRODUCT` names the one product this call is about. Every task you find must
be accomplished through that product's own capabilities, listed below it.

Each capability begins with a header of the form:

```text
[ref: C1]
```

followed by the capability text and the evidence it was accepted on, each
evidence line already carrying its own passage reference:

```text
[ref: C1]
accept electronic funds transfers
  evidence [ref: P11]: "..."
```

The full text of every passage cited above appears once, at the end, under
`SOURCE PASSAGES`:

```text
[ref: P11] [passage_id: ...] [source_id: ...] [publication_date: ...]
<passage text>
```

Cite capabilities and passages by their `ref` labels only. Do not copy
`capability_observation_id`, `passage_id`, `source_id`, or the product's own
identifier into your output; they appear above for human readers and are
resolved downstream.

## Required output

Return a JSON array. Each element is one task candidate with exactly these
fields -- no other field, no wrapper object, no markdown fencing, no
commentary.

Required on every candidate:

- `task`: the task, in the form "verb + object + intended outcome" -- for
  example `"resolve an IT incident by triaging it and initiating approved
  remediation"`.
- `customer_need`: the underlying need, stated independently of the focal
  product -- what the customer is trying to accomplish, not how this product
  helps.
- `capability_refs`: array of one or more `C0N` labels, copied exactly as they
  appear in the CAPABILITIES block above -- the letter `C` followed by the
  capability's position number, written with no fixed width and no leading
  zeros: `"C1"`, `"C9"`, `"C13"`. Every capability this task is actually
  performed through, and nothing this task does not need.
- `availability_status`: exactly one status **label** from the table below,
  for example `"S5"`. Never the status word itself. Judged from the evidence
  you cite for this task, not copied automatically from any capability's own
  status.
- `confidence`: one of `high`, `medium`, `low`, `unknown`.
- `evidence`: array, at least one entry, each entry exactly
  `{"ref": ..., "quote": ...}`.

Include only when the evidence supports it, otherwise omit (never invent a
value):

- `target_customer`: a short phrase naming who performs this task, only if the
  evidence identifies them -- for example `"small business owner"`.
- `monetization_model`: a short phrase naming how this task is priced or
  bundled, only if the evidence states it explicitly -- for example `"included
  in Starter tier"`. Do not infer pricing from silence.
- `task_components`: array of strings -- discrete steps or elements the
  evidence names as part of this one task, for example `["capture payment",
  "confirm receipt"]`. If a step is itself an independently valuable job for
  the customer, it is a separate task candidate, not a component here.
- `ai_action_observed`: a short phrase naming the concrete, dated,
  customer-facing action the evidence describes -- only when the action itself
  is concrete, never the presence of AI-related wording alone. "AI-powered"
  with no described action is not `ai_action_observed`; "routes a support
  ticket to the right queue automatically" is.
- `ambiguity`: a short note when the scope, the capability attribution, or the
  customer need is uncertain.

Do **not** emit an identifier of any kind and do **not** assign a role.
`task_observation_id`, `product_observation_id`, `capability_observation_ids`
and `normalized_task` are all derived downstream, each from its own source:
`product_observation_id` from this call's product, `capability_observation_ids`
from your `capability_refs`, `normalized_task` from your `task`, and
`task_observation_id` from this call's product together with your `task`. This
call already knows which product it is about; do not restate it.
`task_role` is decided by a later consolidation pass, not this one. A
candidate carrying any of these five fields is rejected.

### `evidence` -- how to cite

Each evidence entry has exactly two fields and no others:

- `ref`: the label of one passage shown in `SOURCE PASSAGES`, copied exactly
  as it appears -- the letter `P` followed by that passage's position number,
  written with no fixed width and no leading zeros: `"P1"`, `"P11"`, `"P100"`.
- `quote`: text quoted verbatim from that same passage. Quote **1 to 3
  sentences** -- enough to support the task you are claiming, not the entire
  passage. When a single clause carries the claim, quote that clause.

Binding rules:

- Use only `ref` labels that appear under `SOURCE PASSAGES`. Do not invent a
  label, do not guess a number, and do not cite a passage you were not shown.
- The `quote` must come from the passage that `ref` names.
- Quote the part that supports the claim, not the passage it sits in.
- Copy the words exactly as they appear, without joining text across a gap. If
  the words you need are separated by other text, quote the shorter run that
  is contiguous, or cite a different passage.
- Never emit `source_id` or `passage_id`. An entry carrying either is
  rejected.

### `capability_refs` -- how to attribute

- Use only `C` labels that appear in the CAPABILITIES block above. Every
  capability shown belongs to the one product named in `PRODUCT`; you will
  never be shown a second product's capabilities in this call.
- A task may draw on more than one capability. Cite every one it is actually
  performed through, and no others.
- If the evidence does not tie the task to at least one listed capability,
  omit the task entirely. An unattributable task is not a finding.

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

The eight statuses these labels stand for are the closed vocabulary below.
Read them to decide which one applies; emit only the label. A status word
written out in full is rejected, and there is no ninth status -- never
`planned`.

```
active_status_values           : broadly_deployed_or_default, general_availability,
                                  private_beta, public_beta
roadmap_status_values          : announced
non_active_known_status_values : deprecated, discontinued
unknown_status_values          : unknown
```

If the evidence does not establish which of the seven other tokens applies,
use the label for `unknown`. Do not guess.

## Silent final check

- Every task is customer-facing, in verb-object-outcome form, and is
  accomplished through at least one listed capability.
- Every `capability_refs` entry is a label that appears in the CAPABILITIES
  block, and every capability it names actually supports the task claimed.
- Every evidence `ref` is a label that appears under `SOURCE PASSAGES`.
- Every `quote` is 1 to 3 sentences, contiguous, and copied exactly.
- No entry carries `source_id`, `passage_id`, or any identifier field.
- No entry carries `task_role`.
- `availability_status` is a label from the table (`S1`-`S8`), not a word.
- `ai_action_observed`, when present, names a concrete action, not AI-related
  wording alone.
- One task per distinct customer intent or deliverable, not per sentence, UI
  action, file format, industry, or delivery channel.
- Uncertain candidates remain flagged via `ambiguity`, not dropped and not
  resolved by guessing.
